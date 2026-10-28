# =============================================================================
#                          NANOCODE, CHAPTER 8
#                    eyes on the project - list and search
# =============================================================================
#
# Reading a file you already know the name of is not much use in a project you
# have never seen. This chapter adds the two tools that make the agent able to
# find out what is there:
#
#   list_files      walk the tree and print it as an indented outline
#   search_codebase case-insensitive grep across every file, in file:line form
#
# Both are read-only, so both are plan_safe, and both share a habit worth
# copying: they prune .git, __pycache__, venv and .nanocode as they walk. An
# agent that reads its own noise spends its context on nothing.
#
# The interesting design point is not the walking, it is the *shape of what
# comes back*. Lines that say "path/to/file.py:42: text" are how every editor
# and compiler talks, so the model can quote a location straight back to you.
#
# Run it:  python nanocode.py           # PLAN mode - code is read-only
#          python nanocode.py --act     # ACT mode  - code can be written
# =============================================================================


# =============================================================================
# 1. Imports - the entire dependency list
# =============================================================================
# Four ideas, four imports:
#   os          API keys, and the filesystem (memory.md has to live somewhere)
#   sys         argv, so --act can choose the mode before the loop starts
#   time        sleeping between retries
#   requests    every call to a model is one HTTP POST
# Everything else - the loop, the tools, the memory, the retry policy - is
# written here by hand. That is the point: an agent is a few hundred lines of
# ordinary Python, not a framework.
import os
import sys
import time
import requests
from dotenv import load_dotenv

# Read .env from the current directory into os.environ. Must happen before any
# code reads a key - which is why it sits above every class in this file.
load_dotenv()


# =============================================================================
# 2. HTTP helpers - everything network-shaped lives here
# =============================================================================

# A single POST that assumes the network is perfect is fine for a demo and
# useless in practice. Model APIs answer 429 (slow down) and 5xx (our problem)
# regularly, and a local model that is still loading will simply refuse the
# connection. So every call goes through this function, which:
#
#   - retries 429 / 5xx / connection failures, with exponential backoff
#     (1s, 2s, 4s, 8s...) and obeying the server's Retry-After header if it
#     sends one,
#   - turns any other 4xx into an exception carrying the API's own error text,
#     because a bad key or a malformed request will never succeed on retry,
#   - gives up after max_retries so a hung call cannot block the loop forever.
#
# Ten retries at doubling intervals is generous; the point is that the *agent*
# never has to think about this. It just calls think().
def request_with_retry(url, headers, payload, max_retries=10):
    """Make HTTP POST with retry on rate limit (429), server errors (5xx), and network failures."""
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
        except requests.exceptions.RequestException as e:
            # No response at all: DNS, refused connection, timeout. Same policy
            # as a 5xx - wait longer each time and try again.
            wait_time = 2 ** attempt
            print(f"Network error: {e}. Retrying in {wait_time}s...")
            time.sleep(wait_time)
            continue

        # 429 = the provider's rate limiter, 5xx = the provider is unwell.
        # Both are temporary by contract, so both are worth waiting out.
        if response.status_code == 429 or response.status_code >= 500:
            # Retry-After may be seconds ("12") or an HTTP date; if it is not a
            # plain integer we fall back to our own backoff rather than parse it.
            retry_after = response.headers.get("retry-after")
            try:
                wait_time = int(retry_after) if retry_after else 2 ** attempt
            except (ValueError, TypeError):
                wait_time = 2 ** attempt
            print(f"Error {response.status_code}. Retrying in {wait_time}s...")
            time.sleep(wait_time)
            continue

        # Any remaining error is the caller's fault (bad key, bad model name,
        # bad payload). Retrying cannot help, so surface the API's own message -
        # it is almost always more specific than anything we could invent.
        if response.status_code >= 400:
            try:
                error_msg = response.json()["error"]["message"]
            except (KeyError, ValueError):
                error_msg = response.text
            raise Exception(f"API error ({response.status_code}): {error_msg}")

        return response

    # The for/else idea, spelled out: we ran out of attempts without returning.
    raise Exception(f"Request failed after {max_retries} retries")


# =============================================================================
# 3. Exceptions - the one piece of control flow done with an exception
# =============================================================================

# Quitting is not an error, but it does have to unwind three nested layers:
# the tool loop, handle_input, and the REPL. Raising a private exception and
# catching it once in main() keeps "/q" out of every function's return values.
# KeyboardInterrupt is caught in the same place for the same reason.
class AgentStop(Exception):
    """Raised when the agent should stop processing."""
    pass


# =============================================================================
# 4. Brain response types - one shape, whatever the provider
# =============================================================================
# Providers disagree about the details of a reply, so the rest of the program
# is not allowed to see those details. think() returns a Thought and nothing
# else; everything downstream depends on these two small classes instead of on
# Anthropic's JSON layout.

# A tool call is just an address book entry: which call this is (id, echoed
# back in the result so the model can match request to answer), what to run
# (name), and with what (args, already a dict).
class ToolCall:
    """A tool invocation request from the brain."""

    def __init__(self, id, name, args):
        self.id = id
        self.name = name
        self.args = args  # dict


# One reply from one model turn, flattened into the three things a loop can
# act on: text to show the user, tools to run, and private reasoning to maybe
# display. raw_content is the untouched provider payload - it has to go back
# into the conversation verbatim, or the next request will not line up.
class Thought:
    """Standardized response from any Brain."""

    def __init__(self, text=None, tool_calls=None, raw_content=None, thinking=None):
        self.text = text  # str or None
        self.tool_calls = tool_calls or []  # list of ToolCall
        self.raw_content = raw_content  # original API response for message history
        self.thinking = thinking  # str or None


# =============================================================================
# 5. Memory - the part of the agent that survives the process
# =============================================================================
# The conversation is forgotten when the program exits; the memory file is not.
# Keeping it as plain markdown on disk means it can be read, edited and version
# controlled by a human, and the model can rewrite it with the save_memory tool.

class Memory:
    """Persistent scratchpad for the agent."""

    def __init__(self, path=".nanocode/memory.md"):
        self.path = path
        self._ensure_exists()
        # The whole file is held in memory as one string: it is short, and it is
        # needed on every request (it becomes part of the system prompt).
        self.content = self._load()

    def _ensure_exists(self):
        """Create memory file with default content if needed."""
        # makedirs first: the file may live in a directory that does not exist
        # yet (.nanocode/), and open() will not create that for you.
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if not os.path.exists(self.path):
            # A seed line, so the model starts with an identity rather than
            # with an empty string it has no instruction to fill.
            default = "I am Nanocode, a helpful coding assistant.\n"
            with open(self.path, "w") as f:
                f.write(default)

    def _load(self):
        """Load content from disk."""
        with open(self.path, 'r') as f:
            return f.read()

    def save(self, content):
        """Update memory content and persist to disk."""
        # Update the in-memory copy *and* the file. The next think() call reads
        # self.content through the system prompt, so both have to agree.
        self.content = content
        with open(self.path, 'w') as f:
            f.write(content)


# =============================================================================
# 6. Tool context - what a tool is allowed to know
# =============================================================================
# Tools receive a small context object rather than the Agent itself. That is a
# deliberate restriction: a tool gets the memory it needs, and no handle on the
# brain, the conversation, or the agent's other powers.

class ToolContext:
    """What tools need to know about the agent's state."""

    def __init__(self, memory=None):
        self.memory = memory  # Memory object or None


# =============================================================================
# 7. Brain interface - how to talk to a model without caring which one
# =============================================================================

class Brain:
    """Base class for LLM providers."""

    def think(self, conversation):
        """Process conversation, return Thought."""
        # The only method the loop needs. Each subclass fills it in with its own
        # URL, key, model name and payload quirks.
        raise NotImplementedError

    def _parse_response(self, content):
        """Convert API response format to Thought."""
        # One reply arrives as a list of typed blocks. A turn can contain
        # several at once - "here is my reasoning, here is what I say, here are
        # the tools I want" - so this walks the list rather than assuming one type.
        text_parts = []
        tool_calls = []
        thinking = None

        for block in content:
            if block["type"] == "thinking":
                # Extended thinking: the model's scratch work. Kept aside so the
                # UI can show it without mixing it into the answer.
                thinking = block["thinking"]
            elif block["type"] == "text":
                text_parts.append(block["text"])
            elif block["type"] == "tool_use":
                # The model has decided to act. Note that args are already a
                # parsed dict - the model emits JSON, the API parses it.
                tool_calls.append(ToolCall(
                    id=block["id"],
                    name=block["name"],
                    args=block["input"]
                ))

        # Multiple text blocks are joined with newlines; no text at all becomes
        # None so the loop can treat "said nothing" differently from "said ''".
        return Thought(
            text="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            raw_content=content,
            thinking=thinking
        )


# The first real brain. Everything provider-specific about Anthropic is in this
# class and nowhere else: the header names, the URL, the model id, and the
# decision to turn extended thinking on.

class Claude(Brain):
    """Claude API - the brain of our agent."""

    def __init__(self, memory=None, tools=None):
        self.memory = memory
        # tools here are *definitions* (name/description/schema dicts), not tool
        # objects: the API wants JSON, and the agent already knows the objects.
        self.tools = tools or []
        # Filled in by Agent._build_system_prompt(). Kept on the brain rather
        # than passed per call so think() stays a one-argument function.
        self.system = None
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            # Fail at construction, not on the first turn: a missing key is a
            # setup mistake, and there is no point starting a REPL around it.
            raise ValueError("ANTHROPIC_API_KEY not found in .env")
        self.model = "claude-sonnet-4-6"
        self.url = "https://api.anthropic.com/v1/messages"

    def think(self, conversation):
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        # The request is mostly the conversation plus three decisions:
        #   max_tokens      how long the answer may be
        #   thinking        let the model reason before it answers (budget is
        #                   tokens it may spend doing so, billed as output)
        #   messages        the history, in Anthropic's block format
        payload = {
            "model": self.model,
            "max_tokens": 16000,
            "thinking": {
                "type": "enabled",
                "budget_tokens": 10000
            },
            "messages": conversation
        }
        # The system prompt is a top-level field, not a message with
        # role="system" - that is an Anthropic-specific difference from OpenAI.
        if self.system:
            payload["system"] = self.system
        # Only send tools when there are some; an empty "tools": [] is a
        # different (and less useful) request than no tools at all.
        if self.tools:
            payload["tools"] = self.tools

        response = request_with_retry(self.url, headers, payload)
        return self._parse_response(response.json()["content"])


# A second brain with the same protocol. The value here is not DeepSeek itself,
# it is the demonstration that swapping providers changes a handful of strings
# and nothing in the loop. (DeepSeek exposes an Anthropic-compatible endpoint,
# which is why this class is a near-copy of Claude.)

class DeepSeek(Brain):
    """DeepSeek API (Anthropic-compatible, with tool support)."""

    def __init__(self, memory=None, tools=None):
        self.memory = memory
        self.tools = tools or []
        self.system = None
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY not found in .env")
        self.model = "deepseek-chat"
        self.url = "https://api.deepseek.com/anthropic/v1/messages"

    def think(self, conversation):
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        # Same payload shape as Claude, minus the thinking budget (this model
        # does not take one) and with a smaller max_tokens.
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": conversation
        }
        if self.system:
            payload["system"] = self.system
        if self.tools:
            payload["tools"] = self.tools

        response = request_with_retry(self.url, headers, payload)
        return self._parse_response(response.json()["content"])


# Brains are registered in a dict rather than being constructed directly. Two
# reasons: main() can select one by name from an environment variable, and
# /switch can walk the dict to find "the next one" without knowing the names.
# Available brains
BRAINS = {
    "claude": Claude,
    "deepseek": DeepSeek,
}


# =============================================================================
# 8. Tools - the agent's entire power over the world
# =============================================================================
# Every tool is the same three things written three times: a name, a JSON schema
# the model reads to decide whether to call it, and an execute() method that
# runs when it does. The classes carry no state - they are bundles of
# capability, not objects with identity.
#
# Note what a tool *is not*: it is not a permission system. plan_safe below is
# an honour system enforced by which schemas we send, not by the machine.

class ReadFile:
    """Reads a file from the filesystem."""
    name = "read_file"
    # plan_safe marks a tool safe to offer while in PLAN mode. Reads cannot
    # damage anything, so they stay available when writes do not.
    plan_safe = True
    description = "Reads a file from the filesystem. Use this to examine code."
    # input_schema is the model's instruction manual for calling the tool. The
    # "required" list is load-bearing: without it the model will happily call
    # read_file() with no path and get a Python TypeError back.
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "The path to the file"}
        },
        "required": ["path"]
    }

    def execute(self, context, path):
        # The print is not decoration: it is the only visibility the human has
        # into what the agent decided to do while the loop runs.
        print(f"  → Reading {path}")
        try:
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            # Line numbers are added because the model cannot edit what it
            # cannot address ("the bug is on line 42" needs line 42 to exist in
            # the text it sees).
            numbered_lines = [f"{i+1} | {line}" for i, line in enumerate(lines)]
            return "".join(numbered_lines)
        # Errors are returned as text, never raised. A failed tool call is a
        # message to the model ("that file does not exist"), which is far more
        # useful than a traceback that kills the loop.
        except Exception as e:
            return f"Error reading file: {e}"


class WriteFile:
    """Writes content to a file."""
    name = "write_file"
    # Not plan_safe: this is exactly the power PLAN mode exists to withhold,
    # so in PLAN mode its schema is never sent and the model cannot call it.
    plan_safe = False
    description = "Writes content to a file."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "The path to the file"},
            "content": {"type": "string", "description": "The full content to write"}
        },
        "required": ["path", "content"]
    }

    def execute(self, context, path, content):
        print(f"  → Writing {path}")
        try:
            # Wholesale overwrite. Asking a model to reproduce a long file
            # exactly is a good way to lose it - which is why a later chapter
            # adds an edit_file tool alongside this one.
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            # Echoing the byte count gives the model a cheap sanity check that
            # what it wrote is the size it expected.
            return f"Successfully wrote {len(content)} characters to {path}"
        except Exception as e:
            return f"Error writing file: {e}"


class WritePlan:
    """Saves a plan to PLAN.md."""
    name = "write_plan"
    # The one writing tool allowed in PLAN mode: it writes to a single fixed
    # file that is documentation, not code. This is the escape hatch that makes
    # PLAN mode useful rather than merely restrictive.
    plan_safe = True
    description = "Saves a plan to PLAN.md. Use this to outline your approach before making changes."
    input_schema = {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The plan content in markdown"}
        },
        "required": ["content"]
    }

    def execute(self, context, content):
        print("  → Writing PLAN.md")
        try:
            with open("PLAN.md", 'w', encoding='utf-8') as f:
                f.write(content)
            return "Plan saved to PLAN.md"
        except Exception as e:
            return f"Error saving plan: {e}"


# Walking the tree is how the agent learns a project it has never seen. The
# pruning matters as much as the walking: without it, .git and __pycache__ fill
# the context window with noise the model cannot use.

class ListFiles:
    """Lists files in the project structure."""
    name = "list_files"
    plan_safe = True
    description = "Lists all files in the project structure. Useful to understand the project layout."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "The root path (default '.')"}
        }
        # No "required" here, and execute() defaults path to "." - a tool the
        # model can call with no arguments at all is a tool it will actually use.
    }

    def execute(self, context, path="."):
        print(f"  → Listing {path}")
        try:
            file_list = []
            for root, dirs, files in os.walk(path):
                # Prune in place. Assigning to dirs[:] stops os.walk from
                # descending into these directories at all; without it the agent
                # would drown in .git and __pycache__ noise.
                dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "venv", ".nanocode"}]

                # Indent by depth so the flat output still reads as a tree.
                level = root.replace(path, '').count(os.sep)
                indent = ' ' * 4 * (level)
                file_list.append(f"{indent}{os.path.basename(root)}/")
                subindent = ' ' * 4 * (level + 1)
                for f in files:
                    file_list.append(f"{subindent}{f}")

            return "\n".join(file_list)
        except Exception as e:
            return f"Error listing files: {e}"


# The mirror of list_files: instead of "what is here", "where is this word".
# This is the tool that turns "I don't know where that function lives" into a
# file and line number the model can then go and read.

class SearchCodebase:
    """Searches for a string in all files."""
    name = "search_codebase"
    plan_safe = True
    description = "Searches the entire codebase for a text string. Useful to find where functions or variables are defined."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The string to search for"},
            "path": {"type": "string", "description": "The root path (default '.')"}
        },
        "required": ["query"]
    }

    def execute(self, context, query, path="."):
        print(f"  → Searching for '{query}'")
        results = []
        try:
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "venv", ".nanocode"}]

                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        # errors='ignore' matters more than it looks: one binary
                        # file in the tree would otherwise abort the whole search
                        # with a UnicodeDecodeError.
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            for i, line in enumerate(f):
                                # Case-insensitive, substring. This is grep's
                                # default behaviour and what the model expects;
                                # a case-sensitive search would look "broken".
                                if query.lower() in line.lower():
                                    # file:line: text - the same format an editor
                                    # and a compiler use, so the model can quote
                                    # a location back to the human.
                                    results.append(f"{file_path}:{i+1}: {line.strip()}")
                    except Exception:
                        continue

            return "\n".join(results) if results else "No matches found."
        except Exception as e:
            return f"Error searching: {e}"


class SaveMemory:
    """Updates the agent's internal memory/scratchpad."""
    name = "save_memory"
    plan_safe = True
    # Memory is not code, so writing it is allowed in either mode.
    description = "Updates your internal memory/scratchpad. Use this to remember user preferences."
    input_schema = {
        "type": "object",
        "properties": {
            # The whole text, not a patch: memory is small, and "replace it all"
            # cannot half-apply.
            "content": {"type": "string", "description": "The full text to save."}
        },
        "required": ["content"]
    }

    def execute(self, context, content):
        print(f"  → Saving memory")
        # This is why tools get a ToolContext: save_memory needs the memory
        # object, and a tool built without one should say so rather than crash.
        if context.memory is None:
            return "Error: Memory not available"
        context.memory.save(content)
        return "Memory updated successfully."


# =============================================================================
# 9. Tool plumbing - the two small functions every agent needs
# =============================================================================

def get_tool(tools, name):
    """Find a tool by name, or None if not found."""
    # The model names a tool as a string; this is the lookup that turns that
    # string back into something executable. next(..., None) means "return None
    # on no match" instead of raising StopIteration.
    return next((t for t in tools if t.name == name), None)


def tool_definitions(tools):
    """Return tool definitions for the API."""
    # Objects in, JSON out. The loop keeps the objects (it needs execute()); the
    # model only ever sees this list of dicts.
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


# =============================================================================
# 10. The tool list - the agent's menu
# =============================================================================
# Read-only tools first, mutating tools last. The order has no effect on the
# model, but it does make the menu read like a list of increasing risk, which is
# a useful thing to see when you are deciding what to enable.

tools = [ReadFile(), WritePlan(), SaveMemory(), ListFiles(), SearchCodebase(), WriteFile()]


# =============================================================================
# 11. Agent - the loop that makes it an agent
# =============================================================================

class Agent:
    """A coding agent with tools, memory, and safety mode."""

    def __init__(self, brain, tools, memory=None, mode="plan", brain_name="claude"):
        self.brain = brain
        self.tools = list(tools)  # Copy the tools list
        self.memory = memory
        self.mode = mode  # "plan" or "act"
        self.brain_name = brain_name
        # The conversation is the agent's actual state. Everything the model
        # knows about this session lives in this list, in provider format.
        self.conversation = []
        # Push both derived values onto the brain now, so think() can stay a
        # pure "here is the history, what next" call.
        self.brain.tools = self._tools_for_mode()
        self.brain.system = self._build_system_prompt()

    def _build_system_prompt(self):
        """Build system prompt from memory and current mode."""
        # The system prompt is assembled, not hard-coded: memory is the agent's
        # long-term self, and the mode paragraph is the instruction that makes
        # PLAN mode stick (the tool menu alone is a hint; this is the reason).
        parts = [self.memory.content] if self.memory else []
        if self.mode == "plan":
            parts.append(
                "You are in PLAN mode. You cannot write code files. "
                "Use write_plan to save your plans to PLAN.md."
            )
        return "\n".join(parts)

    def _tools_for_mode(self):
        """Return tool definitions based on current mode."""
        if self.mode == "act":
            # Every tool the agent has.
            return tool_definitions(self.tools)
        # Enforcement happens right here: in PLAN mode the mutating tools are
        # not described to the model at all, so it cannot request them. Nothing
        # has to refuse - the capability is simply absent.
        return tool_definitions([t for t in self.tools if t.plan_safe])

    def handle_input(self, user_input):
        """Handle user input. Returns output string, raises AgentStop to quit."""
        # Slash commands are handled before anything reaches the model. They are
        # the human's controls, not the agent's.
        if user_input.strip() == "/q":
            raise AgentStop()

        if user_input.strip() == "/switch":
            return self._switch_brain()

        # Empty input returns empty output; main() then prints nothing.
        if not user_input.strip():
            return ""

        # Handle mode switching
        if user_input.strip().startswith("/mode"):
            return self._handle_mode_command(user_input)

        # The user's message goes into the history *before* the loop runs, so
        # the loop sees it on its very first think() call.
        self.conversation.append({"role": "user", "content": user_input})

        try:
            return self._agentic_loop()
        except Exception as e:
            # If the turn failed outright (network, API error), remove the
            # message again. Otherwise a dead turn stays in the history and
            # every later request inherits it.
            self.conversation.pop()  # Remove failed user message
            return f"Error: {e}"

    def _handle_mode_command(self, user_input):
        """Handle /mode command to switch between plan and act."""
        parts = user_input.strip().split()
        if len(parts) > 1 and parts[1] == "act":
            self.mode = "act"
            # Both the tool menu and the system prompt have to be rebuilt.
            # Changing one without the other is how "plan mode" quietly becomes
            # advisory.
            self.brain.tools = self._tools_for_mode()
            self.brain.system = self._build_system_prompt()
            return "⚠️  Switched to ACT MODE (Writing Enabled)"
        else:
            # Anything that is not "/mode act" means plan - including a bare
            # "/mode". Defaulting to the safe mode is the right way round.
            self.mode = "plan"
            self.brain.tools = self._tools_for_mode()
            self.brain.system = self._build_system_prompt()
            return "🛡️  Switched to PLAN MODE (Code Read-Only)"

    def _agentic_loop(self):
        """Process brain responses, executing tools until done."""
        # This is the whole agent. Read it once, carefully:
        #
        #   ask the model -> if it asked for tools, run them and hand back the
        #   results -> ask again -> stop when it stops asking for tools.
        #
        # "Agentic" means nothing more than that the model's reply can cause
        # another round of model calls, with the program deciding when to stop.
        output_parts = []

        # while True, with the exit buried two levels down. That is honest about
        # how the loop works - and it is also the reason a runaway model costs
        # money. A later chapter puts a counter on this.
        while True:
            thought = self.brain.think(self.conversation)

            # Display thinking
            # Extended thinking is shown dimmed and capped at five lines: enough
            # for the human to follow the reasoning, not enough to bury the
            # actual answer.
            if thought.thinking:
                lines = thought.thinking.strip().split("\n")[:5]
                for i, line in enumerate(lines):
                    prefix = "  💭 " if i == 0 else "     "
                    print(f"\033[2m{prefix}{line}\033[0m")

            # Store raw content for message history
            # The assistant's reply must go back exactly as it arrived,
            # thinking blocks and tool_use blocks included - the API validates
            # the history, and a lossy copy makes the next request invalid.
            self.conversation.append({"role": "assistant", "content": thought.raw_content})

            # Collect text output
            if thought.text:
                output_parts.append(thought.text)

            # Check for tool calls
            # No tool calls means the model is finished thinking for this turn.
            # This is the loop's only natural exit.
            if not thought.tool_calls:
                break

            # Execute tools and collect results
            tool_results = []
            for tool_call in thought.tool_calls:
                result = self._execute_tool(tool_call.name, tool_call.args)
                # A tool result is a *user* message in this protocol, keyed by
                # tool_use_id so the model can match each answer to its request.
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call.id,
                    "content": result
                })

            # One user message carrying every result from this round - even
            # when the model asked for several tools at once.
            self.conversation.append({"role": "user", "content": tool_results})

        return "\n".join(output_parts)

    def _execute_tool(self, name, args):
        """Execute a tool by name with given arguments."""
        tool = get_tool(self.tools, name)
        if tool is None:
            # Models do hallucinate tool names. Answering with a sentence keeps
            # the loop alive and usually gets a corrected call next turn.
            return f"Error: Tool '{name}' not found"
        try:
            # A fresh context per call: tools cannot stash state between calls.
            context = ToolContext(memory=self.memory)
            return tool.execute(context, **args)
        except TypeError as e:
            # Wrong or missing arguments is a model mistake, and a TypeError is
            # exactly the message that lets it fix the call.
            return f"Error: Invalid arguments - {e}"

    def _switch_brain(self):
        """Toggle to the next brain."""
        names = list(BRAINS.keys())
        idx = names.index(self.brain_name)
        # Modulo, so the last brain wraps round to the first.
        new_name = names[(idx + 1) % len(names)]

        try:
            # A new brain needs the same things the original had: memory and the
            # current mode's tool menu. The conversation is kept, which is what
            # makes switching mid-task useful.
            self.brain = BRAINS[new_name](memory=self.memory, tools=self._tools_for_mode())
            self.brain.system = self._build_system_prompt()
            self.brain_name = new_name
            return f"Switched to: {new_name}"
        except ValueError as e:
            # Constructors raise when a key is missing (no DEEPSEEK_API_KEY).
            # Report it and stay on the brain that works.
            return f"Cannot switch to {new_name}: {e}"


# =============================================================================
# 12. Main - the program around the loop
# =============================================================================
# Everything above is a library. This is the part that makes it a command, and
# it deliberately contains no agent logic: read args, build objects, loop on
# input, print results.

def main():
    # Parse mode from CLI
    # --act is the only flag; anything else means the safe default.
    mode = "act" if len(sys.argv) > 1 and sys.argv[1] == "--act" else "plan"
    brain_name = os.getenv("NANOCODE_BRAIN", "claude")

    memory = Memory()
    # Note that the brain is constructed with tool *definitions*, while the
    # agent is constructed with the tool *objects*. Same menu, two forms.
    brain = BRAINS[brain_name](memory=memory, tools=tool_definitions(tools))
    agent = Agent(brain=brain, tools=tools, memory=memory, mode=mode, brain_name=brain_name)

    # The banner doubles as documentation: a reader should be able to see which
    # brain and which mode are live without asking.
    print(f"⚡ Nanocode v0.7")
    print(f"Commands: /q quit, /switch toggle brain, /mode [plan|act]")
    print(f"Brain: {brain_name}")
    if mode == "act":
        print("Mode: ACT (Writing Enabled)")
    else:
        print("Mode: PLAN (Code Read-Only)")

    while True:
        try:
            # State in the prompt, not just in the banner: mode can change
            # mid-session, and the prompt is where you actually look.
            user_input = input(f"[{agent.brain_name}:{agent.mode}] ❯ ")
            output = agent.handle_input(user_input)
            # handle_input returns "" for blank lines, so nothing is printed
            # for a stray Enter.
            if output:
                print(f"\n{output}\n")

        # Both roads out of the REPL arrive here: /q via AgentStop, Ctrl-C via
        # KeyboardInterrupt. One exit path, one goodbye.
        except (AgentStop, KeyboardInterrupt):
            print("\nExiting...")
            break


# Only run when executed as a script, so the file can also be imported (tests,
# notebooks) without starting a REPL.
if __name__ == "__main__":
    main()
