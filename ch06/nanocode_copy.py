# =============================================================================
#                          NANOCODE, CHAPTER 6
#            memory that survives - a file, not a database
# =============================================================================
#
# The conversation is the agent's memory, and it dies with the process. Close
# the terminal and Nanocode forgets everything: your name, your conventions, the
# fact that you hate tabs.
#
# This chapter adds the smallest thing that fixes that: a markdown file at
# .nanocode/memory.md, loaded at startup, sent to the model as part of the system
# prompt, and rewritten by the agent itself through a new save_memory tool.
#
# Three consequences worth noticing, because they are the chapter:
#
#   1. a file is enough. No vector store, no embeddings, no database - the
#      scratchpad is small and the model reads all of it on every request.
#   2. tools now need something from the agent, so execute() grows a first
#      argument, context. That is ToolContext's whole job: hand a tool the one
#      piece of state it is allowed to touch, and nothing else.
#   3. memory is fed to the model through the *system prompt*, not as a message.
#      It is standing context, not something anybody said.
#
# Still missing: any safety mode. save_memory writes, write_file writes, and
# nothing asks permission yet - that is chapter 7.
#
# Run it:  python nanocode.py     (ANTHROPIC_API_KEY or DEEPSEEK_API_KEY in .env)
# =============================================================================


# =============================================================================
# 1. Imports - the entire dependency list
# =============================================================================
# Three ideas, three imports:
#   os          API keys, and the filesystem (memory.md has to live somewhere)
#   time        sleeping between retries
#   requests    every call to a model is one HTTP POST
import os
import time
import requests
from dotenv import load_dotenv

# Read .env from the current directory into os.environ, before anything reads a
# key - which is why it sits above every class in this file.
load_dotenv()


# =============================================================================
# 2. HTTP helpers - everything network-shaped lives here
# =============================================================================

# A single POST that assumes the network is perfect is fine for a demo and
# useless in practice. Model APIs answer 429 (slow down) and 5xx (our problem)
# regularly. So every call goes through this function, which retries 429 / 5xx /
# connection failures with exponential backoff, obeys Retry-After when it is a
# plain number of seconds, turns any other 4xx into an exception carrying the
# API's own message, and gives up after max_retries so a hung call cannot block
# the loop forever.
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

        # 429 = the provider's rate limiter, 5xx = the provider is unwell. Both
        # are temporary by contract, so both are worth waiting out.
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
        # bad payload). Retrying cannot help, so surface the API's own message.
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

# Quitting is not an error, but it does have to unwind the tool loop,
# handle_input and the REPL. Raising a private exception and catching it once in
# main() keeps "/q" out of every function's return values.
class AgentStop(Exception):
    """Raised when the agent should stop processing."""
    pass


# =============================================================================
# 4. Brain response types - one shape, whatever the provider
# =============================================================================

# A tool call is an address book entry: which call this is (id, echoed back in
# the result so the model can match request to answer), what to run (name), and
# with what (args, already a dict).
class ToolCall:
    """A tool invocation request from the brain."""

    def __init__(self, id, name, args):
        self.id = id
        self.name = name
        self.args = args  # dict


# One reply from one model turn. raw_content is the untouched provider payload -
# it has to go back into the conversation verbatim, tool_use blocks included, or
# the next request is rejected as having an unmatched tool call.
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
# The conversation is forgotten when the program exits; this file is not.
# Keeping it as plain markdown means it can be read, edited and version
# controlled by a human, and the model can rewrite it with the save_memory tool
# below.

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
            # A seed line, so the model starts with an identity rather than with
            # an empty string it has no instruction to fill.
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
        # self.content into the system prompt, so both have to agree.
        self.content = content
        with open(self.path, 'w') as f:
            f.write(content)


# =============================================================================
# 6. Tool context - what a tool is allowed to know
# =============================================================================
# Tools now receive a small context object rather than the Agent itself. That is
# a deliberate restriction: a tool gets the memory it needs, and no handle on the
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
        # Written once here instead of once per provider: the block format is
        # the same across every Anthropic-compatible API.
        #
        # A reply arrives as a list of typed blocks, and a turn can contain
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
                # The model has decided to act. Its arguments arrive already
                # parsed: the model emits JSON, the API hands us a dict.
                tool_calls.append(ToolCall(
                    id=block["id"],
                    name=block["name"],
                    args=block["input"]
                ))

        # Several text blocks are joined with newlines; no text at all becomes
        # None so the caller can tell "said nothing" from "said empty string".
        return Thought(
            text="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            raw_content=content,
            thinking=thinking
        )


# The brain now receives two pieces of state: the tool menu, and the memory. It
# does not interpret the memory - it just forwards its text as the system prompt.
# Deciding *what* the system prompt should say is the Agent's job, not the
# brain's, and chapter 7 moves that decision where it belongs.

class Claude(Brain):
    """Claude API - the brain of our agent."""

    def __init__(self, memory=None, tools=None):
        self.memory = memory
        self.tools = tools or []
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
        # The request is the conversation plus three decisions:
        #   max_tokens   how long the answer may be
        #   thinking     let the model reason before it answers; budget_tokens is
        #                how many tokens it may spend doing so, billed as output
        #   messages     the history, in Anthropic's block format
        payload = {
            "model": self.model,
            "max_tokens": 16000,
            "thinking": {
                "type": "enabled",
                "budget_tokens": 10000
            },
            "messages": conversation
        }
        # Memory goes in the system prompt, not into messages. The system prompt
        # is standing context: it is not something a participant said, and it is
        # not part of the transcript the model is asked to continue.
        if self.memory:
            payload["system"] = self.memory.content
        if self.tools:
            payload["tools"] = self.tools

        response = request_with_retry(self.url, headers, payload)
        return self._parse_response(response.json()["content"])


# The second brain takes the same memory and the same menu. Adding memory to the
# system changed this class by two lines, and the loop not at all.

class DeepSeek(Brain):
    """DeepSeek API (Anthropic-compatible, with tool support)."""

    def __init__(self, memory=None, tools=None):
        self.memory = memory
        self.tools = tools or []
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
        if self.memory:
            payload["system"] = self.memory.content
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
# Every tool is a name, a JSON schema the model reads to decide whether to call
# it, and an execute() method. The schema is not documentation: it is the only
# information the model has.
#
# The signature change is the chapter's real lesson. execute(self, context, ...)
# means every tool now receives the same small bundle of agent state. Today that
# bundle holds only memory; the shape matters because it is how a capability gets
# access to state without being handed the whole agent.

class ReadFile:
    """Reads a file from the filesystem."""
    name = "read_file"
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

    # context is accepted and ignored: the interface is uniform, and a tool that
    # needs nothing from the agent simply does not look.
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
    # The description says OVERWRITES in capitals on purpose. It is the one
    # warning the model gets, and it is the one that stops it from confidently
    # destroying a file it only meant to append to.
    description = "Writes content to a file. OVERWRITES existing content."
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
            # exactly is a good way to lose it, which is why a later chapter adds
            # an edit_file tool alongside this one.
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            # Echoing the character count gives the model a cheap sanity check
            # that what it wrote is the size it expected.
            return f"Successfully wrote {len(content)} characters to {path}"
        except Exception as e:
            return f"Error writing file: {e}"


class SaveMemory:
    """Updates the agent's internal memory/scratchpad."""
    name = "save_memory"
    # This description is doing real work: it is how the model learns that it
    # *has* a long-term memory at all. Without it, a model treats every session
    # as the first one.
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
# Three tools, two of which write: write_file changes the project, save_memory
# changes the agent. Neither asks permission yet.

tools = [ReadFile(), WriteFile(), SaveMemory()]


# =============================================================================
# 11. Agent - the loop that makes it an agent
# =============================================================================

class Agent:
    """A coding agent with tools and memory."""

    def __init__(self, brain, tools, memory=None, brain_name="claude"):
        self.brain = brain
        self.tools = list(tools)  # Copy the tools list
        # The agent holds the memory so it can hand it to each tool as part of
        # the ToolContext - the brain only ever sees its text.
        self.memory = memory
        self.brain_name = brain_name
        self.conversation = []
        # Note that the agent does not push memory onto the brain: main() has
        # already given it to both. Two references to one object is the contract
        # here, and it is worth knowing that adding memory meant touching three
        # constructors - agent, brain, main.

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

        # The user's message goes into the history *before* the loop runs, so
        # the loop sees it on its very first think() call.
        self.conversation.append({"role": "user", "content": user_input})

        try:
            return self._agentic_loop()
        except Exception as e:
            # If the turn failed outright (network, API error), remove the
            # message again. Otherwise a dead turn stays in the history and every
            # later request inherits it.
            self.conversation.pop()  # Remove failed user message
            return f"Error: {e}"

    def _agentic_loop(self):
        """Process brain responses, executing tools until done."""
        # This is the whole agent: ask the model, run whatever tools it asked
        # for, hand the results back, ask again, stop when it stops asking.
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
            # The assistant's reply goes back exactly as it arrived, thinking
            # blocks and tool_use blocks included - the API validates the
            # history, and a lossy copy makes the next request invalid.
            self.conversation.append({"role": "assistant", "content": thought.raw_content})

            # Collect text output
            if thought.text:
                output_parts.append(thought.text)

            # Check for tool calls
            # No tool calls means the model is finished thinking for this turn.
            # This is the loop's only exit.
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
            # Note what it does *not* contain - the brain, the conversation, the
            # other tools. That restraint is the design.
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
            # A new brain needs the same memory and the same tool menu the old
            # one had. The conversation is deliberately kept.
            self.brain = BRAINS[new_name](memory=self.memory, tools=tool_definitions(self.tools))
            self.brain_name = new_name
            return f"Switched to: {new_name}"
        except ValueError as e:
            # Constructors raise when a key is missing (no DEEPSEEK_API_KEY).
            # Report it and stay on the brain that works.
            return f"Cannot switch to {new_name}: {e}"


# =============================================================================
# 12. Main - the program around the loop
# =============================================================================
# Everything above is a library. This is the part that makes it a command: build
# the objects, loop on input, print results.

def main():
    brain_name = os.getenv("NANOCODE_BRAIN", "claude")
    # Memory is built first, because it is handed to both the brain and the
    # agent. One object, two consumers, one file on disk.
    memory = Memory()
    brain = BRAINS[brain_name](memory=memory, tools=tool_definitions(tools))
    agent = Agent(brain=brain, tools=tools, memory=memory, brain_name=brain_name)

    # The banner doubles as documentation: a reader should be able to see which
    # brain is live without asking.
    print(f"⚡ Nanocode v0.5 (Memory Enabled)")
    print(f"Commands: /q quit, /switch toggle brain")
    print(f"Brain: {brain_name}")

    while True:
        try:
            # The brain name is in the prompt because it can change mid-session,
            # and the prompt is where you actually look.
            user_input = input(f"[{agent.brain_name}] ❯ ")
            output = agent.handle_input(user_input)
            # handle_input returns "" for blank lines, so a stray Enter prints
            # nothing at all.
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
