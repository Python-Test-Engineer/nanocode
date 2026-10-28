"""nanocode.py - the agent itself.

The book's single-file Nanocode split into small modules:

    llm.py       brains (providers)        -> Thought
    tools.py     what the agent can do     -> str
    ui.py        how it looks (Rich)       -> console, colours in ui.json
    hooks.py     who else is listening     -> events
    sandbox.py   where it may write        -> policy + FORBIDDEN alarm
    workflows.py ways to arrange agents    -> spawn + a design pattern
    nanocode.py  this file: Memory, Agent (the loop), main()

The Agent is unchanged in behaviour from ch12's single file: same conversation
format, same plan/act gating, same compaction. It just talks to ui instead of
print() and to llm.Brain instead of a hardcoded provider. Chapter 14 hands it
one more object - the sandbox - which the write tools consult; the loop itself
does not check a single path.

CHAPTER 15: A SUBAGENT IS AN AGENT, NOT A PROCESS
  The one new method here is `_spawn_subagent(task)`: it builds a second Agent -
  its own brain, conversation, tool menu, sandbox and hook bus - and calls
  `handle_input(task)` on it. That runs a nested `_agentic_loop()` on the same
  Python stack. No new process, no IPC, no framework:

      parent._agentic_loop()
        └─ tool: run_subagent(task)
             └─ context.spawn(task)
                  └─ child._agentic_loop()      <- the same method, one stack deeper
                       └─ tools ... (read-only)
             <- one string, appended to the parent's conversation as tool output

  The loop did not change to allow this. `_agentic_loop` calls itself through
  the tool table, which is what recursion looks like when the thing you recurse
  into is a class.

THE LOOP, IN FIVE LINES
  1. append the user's message to self.conversation
  2. ask the brain for a Thought
  3. if it asked for tools, run them and append the results (as a user message)
  4. repeat from 2 until a reply has no tool calls
  5. return the text collected along the way

Everything else in this file exists to keep that loop safe (modes), affordable
(compaction) or observable (hooks). If you only read one function, read
_agentic_loop() - it is the whole agent.

WHERE THE OTHER PIECES LIVE
  llm.py    the brain, and the wire formats   -> returns Thought
  tools.py  what can be done                 -> returns str
  ui.py     what the human sees              -> consumes events
  hooks.py  who else is listening            -> consumes events
  this file what happens next                -> the only place that decides
"""

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

import sounds
import ui
from hooks import Hooks, install
# Chapter 14: the write policy. Imported as a module because `sandbox` is also
# the name of an Agent attribute, and the alias keeps the two readable.
import sandbox as sandbox_policy
# Re-exported on purpose: the book's tests (and anything a reader writes) import
# names like `Agent`, `tools`, `BRAINS` from `nanocode`, exactly as they did when
# this was one file. Splitting the file must not change the import surface.
from llm import (  # noqa: F401  (re-exported: tests and callers import from nanocode)
    BRAINS,
    Brain,
    Claude,
    DeepSeek,
    Ollama,
    OpenRouter,
    Thought,
    ToolCall,
    request_with_retry,
)
from tools import (  # noqa: F401  (re-exported for convenience)
    DDGS,
    EditFile,
    ListFiles,
    ReadFile,
    RunCommand,
    RunSubagent,
    RunSubagents,
    SaveMemory,
    SearchCodebase,
    SearchWeb,
    ToolContext,
    WriteFile,
    WritePlan,
    get_tool,
    subagent_limit,
    tool_definitions,
    tools,
)
from sandbox import Sandbox, SandboxViolation  # noqa: F401  (re-exported)

load_dotenv()

MAX_ITERATIONS = 50

# --- Chapter 15: the shape of a subagent ---

# The parent's iteration budget, when the parent has none of its own. Kept as a
# module constant so `max_iterations` can be smaller per agent: an orchestrator
# may legitimately think for 50 steps, a researcher sent to grep one folder
# should not.
SUBAGENT_MAX_ITERATIONS = 20

# How many children may run at once. Threads, not processes: `brain.think()` is a
# blocking HTTP request, so four threads waiting on four sockets cost nothing and
# four answers arrive in the time of the slowest one.
SUBAGENT_PARALLEL = 4

# Tools a child may never inherit, whatever the parent was given:
#   run_subagent / run_subagents - recursion, with no ceiling and no visibility
#   write_plan                   - PLAN.md is the *parent's* plan
#   save_memory                  - memory is shared, so a child would silently
#                                  rewrite the parent's system prompt
SUBAGENT_BLOCKED_TOOLS = frozenset({"run_subagent", "run_subagents", "write_plan", "save_memory"})

SUBAGENT_SYSTEM_PROMPT = (
    "You are a subagent working for another agent. You cannot see its "
    "conversation and you cannot ask it questions, so work only from the task "
    "you were given. Investigate with the tools you have, then return ONE final "
    "answer that is complete enough for the parent to act on without asking "
    "you anything else.\n\n"
)


# --- Exceptions ---

class AgentStop(Exception):
    """Raised when the agent should stop processing."""
    pass


# --- Memory Class ---

class Memory:
    """Persistent scratchpad for the agent.

    One markdown file, read at startup and sent as the system prompt. The agent
    can rewrite it through save_memory, which is how a preference survives a
    restart - the conversation does not, but the memory does.

    A file (not a database, not a vector store) on purpose: you can open it,
    edit it, diff it and delete it. That is the whole feature.
    """

    def __init__(self, path=".nanocode/memory.md"):
        self.path = path
        self._ensure_exists()
        self.content = self._load()

    def _ensure_exists(self):
        """Create memory file with default content if needed."""
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        if not os.path.exists(self.path):
            default = "I am Nanocode, a helpful coding assistant.\n"
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(default)

    def _load(self):
        """Load content from disk."""
        with open(self.path, "r", encoding="utf-8") as f:
            return f.read()

    def save(self, content):
        """Update memory content and persist to disk."""
        self.content = content
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(content)


# --- Agent Class ---

class Agent:
    """A coding agent with tools, memory, and safety mode.

    State worth knowing about:
      conversation    the messages sent to the brain each turn (shape: llm.py)
      mode            "plan" (read-only tools) or "act" (everything)
      tools           the tool OBJECTS; the brain gets their *definitions*
      sandbox         where writes are allowed when ACT is on (sandbox.py);
                      armed and disarmed by the mode, never by the model
      hooks           event bus (see hooks.py); passive observers only
      output_rendered True when a command already printed its own result, so
                      main() does not print the returned string a second time
      max_iterations  round trips one turn may take (ch15: per agent, so a
                      subagent can be given a smaller budget than its parent)
      subagents_spawned  how many children this agent has started; the counter
                      behind the [sub1], [sub2] console labels
    """

    def __init__(self, brain, tools, memory=None, mode="plan", brain_name="openrouter", sandbox=None,
                 max_iterations=None, subagent_max_iterations=None, subagent_parallel=None):
        self.brain = brain
        self.tools = list(tools)  # Copy the tools list
        self.memory = memory
        self.mode = mode  # "plan" or "act"
        self.brain_name = brain_name
        self.conversation: list[dict] = []
        self.hooks = Hooks()  # lifecycle hooks; see hooks.py
        # Handed in by main() so the same object is shared with the hook alarm;
        # a default one keeps an embedded Agent fenced to the working directory.
        self.sandbox = sandbox if sandbox is not None else Sandbox()
        self.sandbox.arm(self.mode)  # PLAN has no write tools; write nothing
        self.output_rendered = False  # True when the UI already showed the text
        # How many round trips one turn may take. It was a module constant in
        # chapter 14; a subagent needs a *smaller* budget than its parent, and a
        # global cannot say that. This is the whole reason it moved onto the
        # object - not a feature, a scope fix.
        self.max_iterations = MAX_ITERATIONS if max_iterations is None else max_iterations
        # Chapter 15: the delegation knobs. `subagent_brain` is a seam for tests
        # and demos: callable(memory, tools) -> Brain. None means "another one of
        # whatever my brain is", which is the useful default.
        self.subagent_max_iterations = (
            SUBAGENT_MAX_ITERATIONS if subagent_max_iterations is None else subagent_max_iterations
        )
        self.subagent_parallel = SUBAGENT_PARALLEL if subagent_parallel is None else subagent_parallel
        self.subagent_brain = None
        self.subagents_spawned = 0
        self._subagent_lock = threading.Lock()  # labels stay unique under threads
        self.brain.tools = self._tools_for_mode()
        self.brain.system = self._build_system_prompt()

    # --- Prompt & tool menu ---

    def _build_system_prompt(self):
        """Build system prompt from memory and current mode.

        Two parts: who the agent is (the memory file) and what it may do right now
        (the mode rule). The mode rule is stated to the model *and* enforced by
        the tool menu in _tools_for_mode() - telling a model it cannot write is a
        request; not giving it write_file is a guarantee.
        """
        parts = [self.memory.content] if self.memory else []
        if self.mode == "plan":
            parts.append(
                "You are in PLAN mode. You cannot write code files. "
                "Use write_plan to save your plans to PLAN.md."
            )
        else:
            # Told to the model *and* enforced by sandbox.check(): the sentence
            # saves a wasted tool call, the check is what actually stops it.
            scope = self.sandbox.describe()
            if scope:
                parts.append(
                    f"You are in ACT mode. {scope}. Any path outside that is "
                    "refused with an error; do not retry it, and do not go "
                    "looking for a way around it outside those folders."
                )
        return "\n".join(parts)

    def _tools_for_mode(self):
        """Return tool definitions based on current mode.

        PLAN mode sends only plan_safe tools, so the model cannot even see
        write_file, edit_file or run_command. This is the safety harness: it does
        not depend on the model behaving.
        """
        if self.mode == "act":
            return tool_definitions(self.tools)
        return tool_definitions([t for t in self.tools if t.plan_safe])

    def _refresh_brain(self):
        """Push the current prompt and tool menu into the brain."""
        self.brain.tools = self._tools_for_mode()
        self.brain.system = self._build_system_prompt()

    # --- Input handling ---

    def handle_input(self, user_input):
        """Handle user input. Returns output string, raises AgentStop to quit."""
        self.output_rendered = False
        command = user_input.strip()

        # Slash commands are handled before anything reaches the model: they are
        # agent operations, not conversation. /q raises instead of returning so
        # main() can exit from anywhere.
        if command == "/q":
            raise AgentStop()

        if command == "/switch":
            return self._switch_brain()

        if command == "/help":
            ui.help_table()
            ui.help_meta(self.brain_name, getattr(self.brain, "model", "?"), self.mode)
            self.output_rendered = True
            return ""

        if not command:
            return ""

        # Handle mode switching
        if command.startswith("/mode"):
            return self._handle_mode_command(command)

        self.conversation.append({"role": "user", "content": user_input})
        self.hooks.emit("turn_start", user_input=user_input)

        try:
            return self._agentic_loop()
        except Exception as e:
            self.conversation.pop()  # Remove failed user message
            ui.error(str(e))
            return ""

    def _handle_mode_command(self, user_input):
        """Handle /mode command to switch between plan and act."""
        parts = user_input.strip().split()
        self.mode = "act" if len(parts) > 1 and parts[1] == "act" else "plan"
        self.sandbox.arm(self.mode)  # the fence follows the mode, not the model
        self._refresh_brain()
        if self.mode == "act":
            ui.sandbox_scope(self.sandbox.roots, self.sandbox.armed)
        ui.mode_switch(self.mode)
        self.output_rendered = True
        return f"Switched to {'ACT' if self.mode == 'act' else 'PLAN'} MODE"

    def _agentic_loop(self):
        """Process brain responses, executing tools until done.

        The heart of the agent. Each iteration is one round trip to the model;
        the loop ends when a reply contains no tool calls. `self.max_iterations`
        is a guard against a model that keeps calling tools forever - without it,
        a confused model could spend your budget in a loop. Chapter 15 made it an
        attribute so a subagent can be given a smaller one than its parent.

        The same method runs for a subagent: it is called by the *parent's*
        `_execute_tool`, one stack frame deeper, through `_spawn_subagent`.
        """
        output_parts = []

        for _iteration in range(self.max_iterations):
            self.hooks.emit("before_think", messages=len(self.conversation))
            ui.send()
            thought = self.brain.think(self.conversation)
            self.hooks.emit("after_think", thought=thought)

            # Display thinking
            if thought.thinking:
                ui.thinking(thought.thinking)

            # Compact if approaching context limit
            if self.brain.last_input_tokens > self.brain.context_limit * 0.75:
                self._compact_conversation()

            # Append the provider's own blocks, not thought.text. The next request
            # must see exactly what the model said - including tool_use ids -
            # otherwise the tool results that follow would refer to nothing.
            self.conversation.append({"role": "assistant", "content": thought.raw_content})

            # Collect text output
            if thought.text:
                output_parts.append(thought.text)

            # Check for tool calls
            if not thought.tool_calls:
                break

            # Execute the requested tools. Results go back as a *user* message
            # made of tool_result blocks: in this dialect the "user turn" is
            # whatever the model needs to hear next, and that includes tool output.
            tool_results = []
            for tool_call in thought.tool_calls:
                result = self._execute_tool(tool_call.name, tool_call.args)
                self.hooks.emit("tool_call", name=tool_call.name, args=tool_call.args, result=result)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call.id,
                    "content": result,
                })

            self.conversation.append({"role": "user", "content": tool_results})
        else:
            output_parts.append(f"(Stopped: too many iterations, limit {self.max_iterations})")

        output = "\n".join(output_parts)
        self.hooks.emit("turn_end", output=output)
        return output

    def _compact_conversation(self):
        """Summarize old messages to stay within context limits."""
        ui.compact()
        # A crude transcript for the summariser: role plus the first 500 chars of
        # each message. Truncating is the point - the history is too long to send,
        # and the summary only needs to preserve decisions, not every byte.
        history = "\n".join(
            f"{m['role']}: {str(m['content'])[:500]}"
            for m in self.conversation
        )
        prompt = [{
            "role": "user",
            "content": f"Summarize this conversation for continuity. "
                       f"Focus on what was accomplished, what's in progress, "
                       f"and key decisions:\n\n{history}",
        }]
        # Ask for the summary with the tool menu temporarily removed: this is a
        # bookkeeping request, not a turn the model should act on. try/finally
        # restores the menu even if the call raises.
        saved_tools = self.brain.tools
        self.brain.tools = []
        try:
            thought = self.brain.think(prompt)
        finally:
            self.brain.tools = saved_tools
        # History is *replaced* by the summary. One message, far fewer tokens -
        # and the only thing lost is detail the summary was asked to keep.
        self.conversation = [
            {"role": "user", "content": f"Previous conversation summary: {thought.text}"},
        ]

    def _execute_tool(self, name, args):
        """Execute a tool by name with given arguments."""
        tool = get_tool(self.tools, name)
        if tool is None:
            ui.warning(f"Unknown tool: {name}")
            return f"Error: Tool '{name}' not found"
        try:
            # Tools receive a context (agent state they may use) plus the model's
            # arguments as keywords. A TypeError here means the model invented an
            # argument name - a useful message, not a crash. ch14 adds the sandbox
            # and the hook bus to the context: the guard needs both. ch15 adds
            # `spawn`: the tools that delegate do not build agents, they ask the
            # agent that owns them to.
            context = ToolContext(
                memory=self.memory,
                sandbox=self.sandbox,
                hooks=self.hooks,
                spawn=self._spawn_subagent,
                spawn_many=self._spawn_many,
            )
            return tool.execute(context, **args)
        except TypeError as e:
            return f"Error: Invalid arguments - {e}"

    # --- Subagents (chapter 15) ---

    def _subagent_tools(self):
        """The parent's tool menu, minus the tools that make no sense in a child.

        The filter is the *whole* safety story of delegation, and it is one line:

          * no `run_subagent` / `run_subagents` -> no recursion. A child that
            could spawn grandchildren would need a depth limit, a budget tree and
            a way to see what they did. Removing the tool removes all three.
          * no `write_plan` -> PLAN.md belongs to the parent. In PLAN mode this
            tool is one of the few that writes, so it would otherwise be the one
            hole in "children cannot write".
          * no `save_memory` -> memory is *shared* (see _spawn_subagent), so a
            child could silently rewrite its parent's system prompt.
        """
        return [t for t in self.tools if t.name not in SUBAGENT_BLOCKED_TOOLS]

    def _subagent_brain_for(self, tools):
        """A brain for a child: the parent's class, a fresh instance.

        Fresh matters as much as the class: `brain.last_input_tokens` and
        `brain.tools` are per-instance state, and two agents sharing one brain
        object would overwrite each other's token counts mid-turn.
        """
        if self.subagent_brain is not None:
            return self.subagent_brain(self.memory, tools)
        return type(self.brain)(memory=self.memory, tools=tools)

    def _spawn_subagent(self, task):
        """Run one subagent to completion on this thread. Returns its answer.

        This is the chapter, and it is mostly a list of things NOT to share. Read
        the comments as "what breaks if you pass the parent's object through":

          sandbox  `Sandbox.arm(mode)` MUTATES the object. A PLAN-mode child
                   sharing the parent's sandbox would disarm the ACT parent's
                   fence for the rest of the session.
          tools    a child with the parent's menu can recurse, rewrite memory or
                   write PLAN.md (see _subagent_tools).
          hooks    the parent's observers would receive the child's tool calls as
                   if the parent had made them. The trace would be one flat,
                   unattributable stream.
          brain    per-instance token counts and tool menus; sharing one lets the
                   child's request rewrite the parent's state.

        What IS shared: the Memory object (read-only, because save_memory was
        filtered out) and the process. That is the whole feature: isolation of
        context, not of memory or of the OS.
        """
        text = str(task or "").strip()
        if not text:
            return "Error: the subagent's task is empty"

        # Labels are claimed under a lock because _spawn_many runs this on four
        # threads: without it, two children could both be "sub3" and the console
        # lines - the only place the user can see them - would be a lie.
        with self._subagent_lock:
            self.subagents_spawned += 1
            label = f"sub{self.subagents_spawned}"

        sub_tools = self._subagent_tools()
        try:
            brain = self._subagent_brain_for(sub_tools)
        except Exception as e:
            return f"Error: could not start a subagent (check the API key): {e}"

        sub_sandbox = Sandbox(
            roots=list(self.sandbox.roots),
            enabled=self.sandbox.enabled,
            deny=list(self.sandbox.deny),
        )
        # PLAN mode, deliberately: the child's menu is plan_safe tools only, so it
        # can read, list, search and search the web, and cannot write. The parent
        # does the writing. A subagent that reports is easier to trust than one
        # that also edits, and a fan-out of writers needs conflict handling that
        # this chapter is not about.
        sub = Agent(
            brain=brain,
            tools=sub_tools,
            memory=self.memory,
            mode="plan",
            brain_name=self.brain_name,
            sandbox=sub_sandbox,
            max_iterations=self.subagent_max_iterations,
        )
        # A fresh bus, then the child is on its own. The parent hears the two
        # events emitted below and nothing else - the same granularity it gets in
        # its conversation, where the whole child is one tool result.
        sub.hooks = Hooks()
        sub.output_rendered = True  # the parent's REPL is not printing for it
        sub.brain.system = SUBAGENT_SYSTEM_PROMPT + (sub.brain.system or "")

        self.hooks.emit("subagent_start", label=label, task=text)
        started = time.monotonic()
        ok, result = True, ""
        try:
            with ui.scope(label):  # this thread's lines are prefixed [subN]
                result = sub.handle_input(text)
        except Exception as e:  # a broken child must not end the parent's turn
            ok, result = False, f"Error: subagent failed: {e}"
        finally:
            self.hooks.emit(
                "subagent_end",
                label=label,
                task=text,
                result=result,
                seconds=time.monotonic() - started,
                ok=ok,
            )
        # The child's answer, unlabelled. It is a tool result like any other: the
        # parent model already knows it called run_subagent, so a "Subagent
        # result:" header would only be tokens - and, in a pipeline, a header the
        # next stage would faithfully quote back as if it were content.
        return result

    def _spawn_many(self, tasks):
        """Run several independent subagents, in parallel, in order.

        Threads, not processes, and this is the one concurrency decision worth
        stating out loud: `brain.think()` is a blocking `requests.post`, so the
        GIL is released for the part that takes the time (the network wait) and
        the four calls really do overlap. Processes would buy CPU parallelism
        this workload does not need, at the cost of pickling, a Windows spawn
        start-method, duplicated imports and no shared console.

        `pool.map` preserves input order, so results[i] belongs to tasks[i] even
        though they finish out of order. That is the contract `RunSubagents`
        promises the model.
        """
        tasks = list(tasks)
        if not tasks:
            return []
        if len(tasks) == 1:
            return [self._spawn_subagent(tasks[0])]
        workers = max(1, min(self.subagent_parallel, len(tasks)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="subagent") as pool:
            return list(pool.map(self._spawn_subagent, tasks))

    # --- Brains ---

    def _switch_brain(self):
        """Toggle to the next brain.

        Cycles BRAINS in order and rebuilds the new brain with the same memory and
        tool menu. History is untouched: because raw_content is stored in one
        canonical dialect, the new provider can read everything said so far.
        """
        names = list(BRAINS.keys())
        idx = names.index(self.brain_name) if self.brain_name in names else -1
        new_name = names[(idx + 1) % len(names)]

        try:
            self.brain = BRAINS[new_name](memory=self.memory, tools=self._tools_for_mode())
            self.brain.system = self._build_system_prompt()
            self.brain_name = new_name
            ui.switched(new_name, getattr(self.brain, "model", None))
            self.output_rendered = True
            return f"Switched to: {new_name}"
        except ValueError as e:
            ui.error(f"Cannot switch to {new_name}: {e}")
            return ""


# --- Main Loop ---

def main():
    # Two entry points into the same agent: plan (read-only, the safe default)
    # and act (writes allowed). Parsed by hand - one flag does not need argparse.
    mode = "act" if "--act" in sys.argv[1:] else "plan"
    brain_name = os.getenv("NANOCODE_BRAIN", "openrouter")

    ui.configure()
    memory = Memory()

    try:
        brain = BRAINS[brain_name](memory=memory, tools=tool_definitions(tools))
    except (KeyError, ValueError) as e:
        ui.error(f"Cannot start brain '{brain_name}': {e}")
        ui.info(f"Available: {', '.join(BRAINS)}")
        return 1

    agent = Agent(brain=brain, tools=tools, memory=memory, mode=mode, brain_name=brain_name,
                  sandbox=sandbox_policy.Sandbox())

    install(agent.hooks)  # coloured hook lines; NANOCODE_HOOKS=0 hides them
    # ch13: the same hooks, heard instead of read. Sound is off unless
    # NANOCODE_SOUND (or sounds.json) asks for it - see sounds.py.
    sounds.install(agent.hooks)
    # ch14: the refusal alarm - FORBIDDEN on the console plus the warning WAV.
    sandbox_policy.install(agent.hooks)
    ui.banner(
        brain=brain_name,
        model=getattr(brain, "model", "?"),
        mode=mode,
        version="v1.0",
        tool_count=len(agent.tools),
    )
    # ACT mode is the only mode with write tools, so it is the only mode where
    # the fence is worth announcing up front.
    if mode == "act":
        ui.sandbox_scope(agent.sandbox.roots, agent.sandbox.armed)

    # The session is now underway. Nothing in a turn would announce that, so we
    # emit it ourselves - and ch13 gives it the Windows "tada" in sounds.json.
    agent.hooks.emit(
        "session_start",
        brain=brain_name,
        model=getattr(brain, "model", "?"),
        mode=mode,
    )

    # The read-eval-print loop. All it does is: ask, hand the line to the agent,
    # render what comes back. Ctrl+C and Ctrl+D both mean "stop politely".
    while True:
        try:
            user_input = ui.ask(agent.brain_name, agent.mode)
            output = agent.handle_input(user_input)
            if output and not agent.output_rendered:
                # Commands print their own coloured result and set the flag, so
                # they are not echoed a second time here.
                ui.answer(output)

        except AgentStop:
            ui.goodbye("Exiting...")
            break
        except (KeyboardInterrupt, EOFError):
            ui.goodbye("Exiting...")
            break

    return 0


if __name__ == "__main__":
    sys.exit(main())
