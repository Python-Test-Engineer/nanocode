"""tools.py - everything the agent can *do* to the world.

Each tool is a class with four pieces the model sees:
    name         the string the model calls
    description  when to use it
    input_schema JSON schema for the arguments
    plan_safe    True = allowed in PLAN mode (read-only / harmless)

...and one method the agent calls:
    execute(context, **args) -> str

Tools return strings, errors included. Never raise at the model: an error
message is information the agent can act on, a traceback is not.

Console feedback goes through ui.tool_action(name, detail) so each tool's
colour lives in ui.json, not here.

THE CONTRACT, IN ONE PLACE
  name          the string the model must call - it is the API, keep it stable
  description   when to use it; this is prompt engineering, not documentation
  input_schema  JSON Schema; the model is constrained by it, so be precise
  plan_safe     True  = read-only / harmless, offered in PLAN mode
                False = changes the world, offered only in ACT mode
  execute(...)  returns a STRING. Always. Even when it fails.

WHY ERRORS ARE STRINGS
  A traceback ends the turn; an error message continues it. "Error: File not
  found: app.py" goes back to the model as a tool result, and the model can try
  another path. That single decision is what makes the feedback loop work.

WHY EACH TOOL LOGS ITS OWN ACTION
  tools.py is the only place that knows a tool has started, so it is the honest
  place to emit "→ Reading app.py". Through ui.tool_action the colour stays in
  ui.json, so a tool never mentions a colour.

WHERE THE SANDBOX FITS (chapter 14)
  Every tool that writes asks `context.guard(path, self.name)` first and returns
  its error string instead of writing when the answer is no. The policy lives in
  sandbox.py, the refusal event lives on the hook bus, and this file only knows
  two words: "check, then write". That is why the fence did not need a new tool
  signature or a single change to the agent loop.

WHERE SUBAGENTS FIT (chapter 15)
  Delegation is a tool like any other, which is the point: `RunSubagent` has the
  same shape as `ReadFile` and returns a string. It does not own an agent and
  does not start a process - it calls `context.spawn(task)`, and the Agent that
  built the context decides what a subagent is. The tool knows how to *ask*,
  the agent knows how to *make one*, and neither knows about the other.
"""

import os
import subprocess
import sys
import time

import ui

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None


# --- Bounded walking ---

# Directories that are never worth listing: caches, dependencies, and the system
# trees that made `list_files C:\` hang for minutes in ACT mode.
SKIP_DIRS = {
    ".git", "__pycache__", "venv", ".venv", ".nanocode", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".ipynb_checkpoints",
    "Windows", "Program Files", "Program Files (x86)", "ProgramData",
    "$Recycle.Bin", "System Volume Information", "Recovery", "PerfLogs",
    "AppData", "OneDriveTemp",
}

# A file bigger than this is not source code; searching it only costs time.
MAX_FILE_BYTES = 5_000_000


def walk_budget():
    """(entries, seconds) a walk may spend. Env-tunable, read per call for tests."""
    entries = int(os.environ.get("NANOCODE_MAX_ENTRIES", "2000"))
    seconds = float(os.environ.get("NANOCODE_WALK_TIMEOUT", "10"))
    return max(1, entries), max(0.0, seconds)


def walk_bounded(path=".", state=None):
    """os.walk with a budget: skip caches, cap the entries, stop at a deadline.

    Reads are not sandboxed the way writes are, and that is exactly why this
    exists: a refusal at `C:\\hello.py` made the model try `list_files C:\\`,
    which walked the whole drive with no ceiling - a hang, not an answer.

    `state` is filled in as we go (`truncated`, `reason`, `seen`) so the caller
    can tell the model the listing is partial instead of implying it is complete.
    Yields (root, dirs, files), same shape as os.walk.
    """
    state = state if state is not None else {}
    state.update({"truncated": False, "reason": "", "seen": 0})
    limit, seconds = walk_budget()
    deadline = time.monotonic() + seconds

    # onerror swallows PermissionError on trees like "System Volume Information"
    # instead of aborting the whole listing with one traceback.
    for root, dirs, files in os.walk(path, onerror=lambda _error: None):
        # dirs[:] = ... edits IN PLACE, which is how os.walk is told to skip a
        # subtree. Reassigning `dirs` would not prune it.
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        state["seen"] += 1 + len(files)
        if state["seen"] > limit:
            state["truncated"] = True
            state["reason"] = f"entry limit {limit}"
            return
        if time.monotonic() > deadline:
            state["truncated"] = True
            state["reason"] = f"time limit {seconds:g}s"
            return
        yield root, dirs, files


def truncation_note(state, path):
    """The line that stops a partial listing from looking complete."""
    if not state.get("truncated"):
        return ""
    return (
        f"\n(stopped after {state.get('seen', 0)} entries under {path}: "
        f"{state['reason']} reached. Narrow the path, or raise "
        f"NANOCODE_MAX_ENTRIES / NANOCODE_WALK_TIMEOUT.)"
    )


# --- Tool Context ---

class ToolContext:
    """What tools need to know about the agent's state.

    memory     the Memory object (or None)
    sandbox    the write policy (or None: no policy, every path allowed)
    hooks      the event bus, so a refusal can be announced (or None: tools
               print it themselves, see guard())
    spawn      callable(task) -> str: run one subagent to completion and return
               its final answer (chapter 15). None means "no subagents here".
    spawn_many callable(tasks) -> list[str]: the same for several tasks, in
               parallel. Kept separate from spawn so a tool never has to know
               whether the agent uses threads, processes or nothing at all.

    `guard()` and `guard_command()` are the whole chapter-14 contract: a tool
    calls one of them before it touches the disk, and gets back either None
    (carry on) or an error string to return to the model instead of writing.

    `spawn` is the chapter-15 contract, and it is the same trick: the tool asks
    the agent to do the thing the tool is not allowed to know about. That is why
    `RunSubagent` can be a dozen lines long and still start a whole nested agent.
    """

    def __init__(self, memory=None, sandbox=None, hooks=None, spawn=None, spawn_many=None):
        self.memory = memory  # Memory object or None
        self.sandbox = sandbox  # sandbox.Sandbox or None
        self.hooks = hooks  # Hooks bus or None
        self.spawn = spawn  # callable(task) -> str or None
        self.spawn_many = spawn_many  # callable(tasks) -> list[str] or None

    def guard(self, path, tool=""):
        """Check one write target. Returns an error string, or None to proceed."""
        sandbox = self.sandbox
        if sandbox is None:
            return None
        violation = sandbox.check(path, tool=tool)
        if violation is None:
            return None
        self.refuse(violation, sandbox)
        return violation.message()

    def guard_command(self, command, tool="run_command"):
        """Check the write targets a shell command names (best effort)."""
        sandbox = self.sandbox
        if sandbox is None:
            return []
        violations = sandbox.check_command(command, tool=tool)
        if violations:
            self.refuse(violations[0], sandbox)
        return violations

    def refuse(self, violation, sandbox=None):
        """Announce a refusal: the event if there is a bus, else console + sound.

        The tool itself never decides what a refusal looks like - that is the
        console's job (ui.forbidden) and the alarm's (sounds.alarm). This is the
        one line where the three modules meet, and it is one line on purpose.
        """
        sandbox = sandbox if sandbox is not None else self.sandbox
        roots = tuple(sandbox.roots) if sandbox is not None else ()
        if self.hooks is not None:
            self.hooks.emit(
                "sandbox_denied",
                tool=violation.tool,
                path=violation.path,
                resolved=violation.resolved,
                reason=violation.reason,
                roots=roots,
            )
        else:
            import sounds

            ui.forbidden(violation.path, violation.reason, roots=roots)
            sounds.alarm("sandbox_denied")


# --- Tool Classes ---

class ReadFile:
    """Reads a file from the filesystem."""

    name = "read_file"
    plan_safe = True
    description = "Reads a file from the filesystem. Use this to examine code."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "The path to the file"}
        },
        "required": ["path"],
    }

    def execute(self, context, path):
        ui.tool_action("read_file", path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                # Numbered lines are for the MODEL, not for you: they let it say
                # "line 42" and let edit_file target text it has actually seen.
                # encoding is pinned so Windows does not fall back to cp1252.
                lines = f.readlines()
            numbered_lines = [f"{i+1} | {line}" for i, line in enumerate(lines)]
            return "".join(numbered_lines)
        except FileNotFoundError:
            return f"Error: File not found: {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error reading file: {e}"


class WriteFile:
    """Writes content to a file."""

    name = "write_file"
    plan_safe = False
    description = "Writes content to a file."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "The path to the file"},
            "content": {"type": "string", "description": "The full content to write"},
        },
        "required": ["path", "content"],
    }

    def execute(self, context, path, content):
        ui.tool_action("write_file", path)
        # Chapter 14: ask the policy before touching the disk. A refusal is an
        # error STRING like any other, so the model can read it and try a path
        # inside the sandbox - the loop keeps working, the file never lands.
        blocked = context.guard(path, self.name)
        if blocked:
            return blocked
        try:
            # "w" truncates. Whole-file writes are fine for new files; for edits
            # to existing code the model is told to prefer edit_file, which
            # cannot silently drop the parts it did not copy.
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote {len(content)} characters to {path}"
        except Exception as e:
            return f"Error writing file: {e}"


class WritePlan:
    """Saves a plan to PLAN.md."""

    name = "write_plan"
    plan_safe = True
    description = "Saves a plan to PLAN.md. Use this to outline your approach before making changes."
    input_schema = {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The plan content in markdown"}
        },
        "required": ["content"],
    }

    def execute(self, context, content):
        ui.tool_action("write_plan", "PLAN.md")
        # PLAN.md is fixed, but a configured sandbox may not include the working
        # directory at all - so the fixed path is checked like any other.
        blocked = context.guard("PLAN.md", self.name)
        if blocked:
            return blocked
        try:
            with open("PLAN.md", "w", encoding="utf-8") as f:
                f.write(content)
            return "Plan saved to PLAN.md"
        except Exception as e:
            return f"Error saving plan: {e}"


class EditFile:
    """Replaces text in a file (surgical edit)."""

    name = "edit_file"
    plan_safe = False
    description = "Replaces specific text in a file. Use for surgical edits instead of rewriting entire files."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file"},
            "old_text": {"type": "string", "description": "Exact text to find and replace"},
            "new_text": {"type": "string", "description": "Text to replace it with"},
        },
        "required": ["path", "old_text", "new_text"],
    }

    def execute(self, context, path, old_text, new_text):
        ui.tool_action("edit_file", path)
        blocked = context.guard(path, self.name)
        if blocked:
            return blocked
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            # Exact match, replaced ONCE. Not a regex, not fuzzy: if the model
            # quotes text that is not there, the honest answer is an error it can
            # read, not a guessed edit. count=1 keeps repeated snippets safe.
            if old_text not in content:
                return f"Error: Could not find the specified text in {path}"
            new_content = content.replace(old_text, new_text, 1)
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
            return f"Successfully edited {path}"
        except Exception as e:
            return f"Error editing file: {e}"


class ListFiles:
    """Lists files in the project structure."""

    name = "list_files"
    plan_safe = True
    description = "Lists all files in the project structure. Useful to understand the project layout."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "The root path (default '.')"}
        },
    }

    def execute(self, context, path="."):
        ui.tool_action("list_files", path)
        try:
            file_list = []
            state = {}
            for root, dirs, files in walk_bounded(path, state):
                # Depth = how many separators the current root sits below `path`,
                # which turns a flat walk into an indented tree.
                level = root.replace(path, "").count(os.sep)
                indent = " " * 4 * level
                file_list.append(f"{indent}{os.path.basename(root)}/")
                subindent = " " * 4 * (level + 1)
                for f in files:
                    file_list.append(f"{subindent}{f}")

            # Partial listings say so: the model must not read a truncated tree
            # as proof that a file does or does not exist.
            return "\n".join(file_list) + truncation_note(state, path)
        except Exception as e:
            return f"Error listing files: {e}"


class SearchCodebase:
    """Searches for a string in all files."""

    name = "search_codebase"
    plan_safe = True
    description = "Searches the entire codebase for a text string. Useful to find where functions or variables are defined."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The string to search for"},
            "path": {"type": "string", "description": "The root path (default '.')"},
        },
        "required": ["query"],
    }

    def execute(self, context, query, path="."):
        ui.tool_action("search_codebase", f"'{query}'")
        results = []
        state = {}
        try:
            for root, dirs, files in walk_bounded(path, state):
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        # A 200 MB binary is not source: skip it by size rather
                        # than by decoding it line by line.
                        if os.path.getsize(file_path) > MAX_FILE_BYTES:
                            continue
                        # errors="ignore" and a per-file try: searching a repo
                        # means meeting binaries and odd encodings. One unreadable
                        # file must not abort the search.
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            for i, line in enumerate(f):
                                if query.lower() in line.lower():
                                    results.append(f"{file_path}:{i+1}: {line.strip()}")
                    except Exception:
                        continue

            if not results:
                found = "No matches found."
            else:
                found = "\n".join(results)
            return found + truncation_note(state, path)
        except Exception as e:
            return f"Error searching: {e}"


class SaveMemory:
    """Updates the agent's internal memory/scratchpad."""

    name = "save_memory"
    plan_safe = True
    description = "Updates your internal memory/scratchpad. Use this to remember user preferences."
    input_schema = {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The full text to save."}
        },
        "required": ["content"],
    }

    def execute(self, context, content):
        ui.tool_action("save_memory", f"{len(content)} chars")
        if context.memory is None:
            return "Error: Memory not available"
        context.memory.save(content)
        return "Memory updated successfully."


class RunCommand:
    """Executes shell commands."""

    name = "run_command"
    plan_safe = False
    description = "Executes a terminal command. Use this to run scripts, tests, or install packages."
    input_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command to run (e.g., 'python test.py')"}
        },
        "required": ["command"],
    }

    def execute(self, context, command):
        preview = command if len(command) <= 60 else command[:57] + "..."
        ui.tool_action("run_command", preview)
        # Best effort only: the redirects and mutators named on the command line
        # are checked; everything a shell can do beyond that is out of scope for
        # a fence that lives in a Python function. sandbox.py says so too.
        violations = context.guard_command(command, self.name)
        if violations:
            return violations[0].message()
        try:
            # shell=True because the model writes shell syntax ("python x.py &&
            # pytest"). capture_output keeps stdout/stderr out of the console and
            # inside the tool result, where the model can read them. The timeout
            # is a hard stop: a hung command would otherwise freeze the agent,
            # and NANOCODE_TIMEOUT lets you raise it for slow test suites.
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=int(os.environ.get("NANOCODE_TIMEOUT", "30")),
                cwd=os.getcwd(),
            )

            output = ""
            if result.stdout:
                output += f"STDOUT:\n{result.stdout}\n"
            if result.stderr:
                output += f"STDERR:\n{result.stderr}\n"
            if not output:
                output = "(No output)"

            return output.strip()

        except subprocess.TimeoutExpired:
            return "Error: Command timed out."
        except Exception as e:
            return f"Error executing command: {e}"


class RunSubagent:
    """Hands a self-contained task to a fresh agent and returns its answer.

    Three things make this a tool rather than an agent:

      * it does not construct anything - `context.spawn(task)` does, and the
        Agent that built the context decides the subagent's brain, menu, sandbox
        and budget. Swap the agent and the tool is unchanged.
      * it returns a STRING, like every other tool. The parent model sees one
        tool result, not the subagent's conversation, so a subagent can burn
        20,000 tokens and cost the parent one paragraph.
      * `plan_safe = True` because a subagent here is a *researcher*: it runs in
        PLAN mode, so it can read and search but not write. Delegation is
        therefore safe in either mode, which is why the parent's mode does not
        have to be checked.
    """

    name = "run_subagent"
    plan_safe = True
    description = (
        "Delegate a self-contained investigation to a fresh subagent with its own "
        "context. Give it the complete task and every fact it needs: it cannot see "
        "this conversation and cannot ask follow-up questions. It returns only its "
        "final answer, so ask for the answer in the shape you want to use."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The complete task and context for the subagent",
            },
        },
        "required": ["task"],
    }

    def execute(self, context, task):
        ui.tool_action("run_subagent", _clip(task, 60))
        if context.spawn is None:
            return "Error: subagents are not available in this agent"
        if not str(task or "").strip():
            return "Error: the subagent's task is empty"
        try:
            return context.spawn(task)
        except Exception as e:  # the parent's turn must survive a broken child
            return f"Error: subagent failed: {e}"


class RunSubagents:
    """The same delegation, for several independent tasks at once.

    The model asks for a fan-out; the agent decides whether that means threads,
    processes or a `for` loop (see `Agent._spawn_many`). The tool's only job is
    to bound the list and label the answers, so the parent can tell them apart.
    """

    name = "run_subagents"
    plan_safe = True
    description = (
        "Delegate several INDEPENDENT tasks at once, one subagent per task. Use "
        "this instead of repeated run_subagent calls when the tasks do not depend "
        "on each other. Each subagent is isolated and cannot ask questions; "
        "results come back in the same order as the tasks."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "One complete, self-contained task per subagent",
            },
        },
        "required": ["tasks"],
    }

    def execute(self, context, tasks):
        if isinstance(tasks, str):  # some models send one string instead of a list
            tasks = [tasks]
        if not isinstance(tasks, (list, tuple)) or not tasks:
            return "Error: tasks must be a non-empty list of strings"
        wanted = [t for t in tasks if str(t or "").strip()]
        limit = subagent_limit()
        tasks = wanted[:limit]
        if not tasks:
            return "Error: every task was empty"
        ui.tool_action("run_subagents", f"{len(tasks)} task(s) in parallel")
        try:
            if context.spawn_many is not None:
                results = context.spawn_many(tasks)
            elif context.spawn is not None:
                # No parallel machinery: the honest fallback is one at a time.
                results = [context.spawn(task) for task in tasks]
            else:
                return "Error: subagents are not available in this agent"
        except Exception as e:
            return f"Error: subagents failed: {e}"

        note = ""
        if len(wanted) > len(tasks):
            note = (f"\n\n({len(wanted) - len(tasks)} task(s) dropped: the limit is "
                    f"{limit}. Raise NANOCODE_MAX_SUBAGENTS or send fewer.)")
        return "\n\n".join(
            f"Subagent {index}:\n{result}"
            for index, result in enumerate(results, start=1)
        ) + note


class SearchWeb:
    """Searches the internet using DuckDuckGo."""

    name = "search_web"
    plan_safe = True
    description = "Searches the internet for current information. Use when you need knowledge beyond your training data."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"}
        },
        "required": ["query"],
    }

    def execute(self, context, query):
        ui.tool_action("search_web", f"'{query}'")
        backend = resolve_ddgs()
        if backend is None:
            return "Error: ddgs package not installed. Run: pip install ddgs"
        try:
            results = backend().text(query, max_results=3)
            if not results:
                return "No results found."

            formatted = []
            for r in results:
                formatted.append(f"Title: {r['title']}\nURL: {r['href']}\nSummary: {r['body']}\n")

            return "\n".join(formatted)
        except Exception as e:
            return f"Error searching web: {e}"


# --- Tool Helpers ---

def subagent_limit():
    """How many subagents one fan-out may start. Env-tunable, read per call.

    A ceiling is not a nicety: `run_subagents` takes a list the *model* wrote,
    and "summarise every file in the repo" is a perfectly reasonable thing to
    ask for and a very expensive thing to obey.
    """
    try:
        return max(1, int(os.environ.get("NANOCODE_MAX_SUBAGENTS", "8")))
    except ValueError:
        return 8


def _clip(text, limit=60):
    """One short line of text for a tool line or a log message."""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def resolve_ddgs():
    """The DuckDuckGo backend, honouring an override on the host module.

    Tests and embedders swap the search backend by setting `nanocode.DDGS`
    (e.g. monkeypatch); otherwise this module's own import is used.

    This indirection exists because the book's tests patch
    `nanocode.DDGS` while the tool lives here. Looking the name up at call time
    (instead of binding it at import time) keeps both honest, and costs nothing
    outside tests. It is also a small lesson in why module-level globals and
    monkeypatching are such close friends.
    """
    global DDGS
    host = sys.modules.get("nanocode")
    if host is not None and getattr(host, "DDGS", None) is not None:
        DDGS = host.DDGS
    return DDGS


def get_tool(tools, name):
    """Find a tool by name, or None if not found."""
    return next((t for t in tools if t.name == name), None)


def tool_definitions(tools):
    """Return tool definitions for the API."""
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


# --- Tools List ---

tools = [ReadFile(), WritePlan(), SaveMemory(), ListFiles(), SearchCodebase(), SearchWeb(),
         WriteFile(), EditFile(), RunCommand(), RunSubagent(), RunSubagents()]
