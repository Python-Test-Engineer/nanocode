# =============================================================================
#                          NANOCODE, CHAPTER 5
#            hands - tools, and the loop becomes a cycle
# =============================================================================
#
# Until now the agent could only talk. This chapter gives it two hands -
# read_file and write_file - and, in doing so, changes the shape of the loop.
#
# In chapters 3 and 4 one user message produced exactly one model call. Now a
# user message can produce:
#
#     model asks for a tool -> we run it -> model asks for another -> ... -> done
#
# The loop has become a *cycle*, and the model decides how many times round it
# goes. Note how little code that took: a while True, a list of tool results,
# and one break. The power is not in the plumbing, it is in who controls the
# exit condition.
#
# Two things are deliberately still missing, and both matter:
#   - no iteration cap, so a model that never stops asking for tools spins
#     forever (and bills you for it),
#   - no safety mode, so write_file is available from the first keystroke.
# The next chapters fix each of them.
#
# Run it:  python nanocode.py     (ANTHROPIC_API_KEY or DEEPSEEK_API_KEY in .env)
# =============================================================================


# =============================================================================
# 1. Imports - the entire dependency list
# =============================================================================
# Three ideas, three imports:
#   os          reading API keys out of the environment
#   time        sleeping between retries
#   requests    every call to a model is one HTTP POST
# The tools that follow use nothing but the standard library's open().
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
# regularly. So every call goes through this function, which:
#
#   - retries 429 / 5xx / connection failures, with exponential backoff
#     (1s, 2s, 4s, 8s...) and obeying the server's Retry-After header if it
#     sends one,
#   - turns any other 4xx into an exception carrying the API's own error text,
#     because a bad key or a malformed request will never succeed on retry,
#   - gives up after max_retries so a hung call cannot block the loop forever.
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
# with what (args, already a dict). From this chapter on, these are executed
# rather than merely recorded.
class ToolCall:
    """A tool invocation request from the brain."""

    def __init__(self, id, name, args):
        self.id = id
        self.name = name
        self.args = args  # dict


# One reply from one model turn. raw_content is new in this chapter and it is
# load-bearing: the assistant's reply has to go back into the conversation
# exactly as it arrived, tool_use blocks included, or the next request is
# rejected as having an unmatched tool call.
class Thought:
    """Standardized response from any Brain."""

    def __init__(self, text=None, tool_calls=None, raw_content=None, thinking=None):
        self.text = text  # str or None
        self.tool_calls = tool_calls or []  # list of ToolCall
        self.raw_content = raw_content  # original API response for message history
        self.thinking = thinking  # str or None


# =============================================================================
# 5. Brain interface - how to talk to a model without caring which one
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


# The brain now has to be told what tools exist, because the tool menu is part
# of every request. Note that it is handed *definitions* - plain dicts - not the
# tool objects; the API wants JSON, the agent keeps the objects.

class Claude(Brain):
    """Claude API - the brain of our agent."""

    def __init__(self, tools=None):
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
        # Only send tools when there are some; an empty "tools": [] is a
        # different (and less useful) request than no tools at all.
        if self.tools:
            payload["tools"] = self.tools

        response = request_with_retry(self.url, headers, payload)
        return self._parse_response(response.json()["content"])


# The second brain takes the same menu. The value of the registry is visible
# here: adding tools changed this class by two lines, and the loop not at all.

class DeepSeek(Brain):
    """DeepSeek API (Anthropic-compatible, with tool support)."""

    def __init__(self, tools=None):
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
# 6. Tools - the agent's entire power over the world
# =============================================================================
# Every tool is the same three things written three times: a name, a JSON schema
# the model reads to decide whether to call it, and an execute() method that runs
# when it does. The classes carry no state - they are bundles of capability, not
# objects with identity.
#
# The schema is not documentation. It is the only information the model has: it
# decides whether to call read_file based on the description string, and it
# fills the arguments from the properties.

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

    # Note the signature: no context argument yet. A tool that needs to know
    # something about the agent (its memory, for instance) has nowhere to get it
    # from - which is why chapter 6 introduces ToolContext.
    def execute(self, path):
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

    def execute(self, path, content):
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


# =============================================================================
# 7. Tool plumbing - the two small functions every agent needs
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
# 8. The tool list - the agent's menu
# =============================================================================
# Two tools, and both of them change the machine. There is no read-only mode
# yet, so this list is also the reason the next two chapters exist.

tools = [ReadFile(), WriteFile()]


# =============================================================================
# 9. Agent - the loop that makes it an agent
# =============================================================================

class Agent:
    """A coding agent with tools."""

    def __init__(self, brain, tools, brain_name="claude"):
        self.brain = brain
        self.tools = list(tools)  # Copy the tools list
        self.brain_name = brain_name
        # The conversation is the agent's actual state. Everything the model
        # knows about this session lives in this list, in provider format - and
        # from now on that includes tool calls and their results.
        self.conversation = []

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

    def _switch_brain(self):
        """Toggle to the next brain."""
        names = list(BRAINS.keys())
        idx = names.index(self.brain_name)
        # Modulo, so the last brain wraps round to the first.
        new_name = names[(idx + 1) % len(names)]

        try:
            # A new brain needs the same tool menu the old one had. The
            # conversation is deliberately kept.
            self.brain = BRAINS[new_name](tools=tool_definitions(self.tools))
            self.brain_name = new_name
            return f"Switched to: {new_name}"
        except ValueError as e:
            # Constructors raise when a key is missing (no DEEPSEEK_API_KEY).
            # Report it and stay on the brain that works.
            return f"Cannot switch to {new_name}: {e}"

    def _agentic_loop(self):
        """Process brain responses, executing tools until done."""
        # This is the whole agent, and it is shorter than you expect. Read it
        # once, carefully:
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

            # Store raw content for message history (Claude expects this format)
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
                break  # No more tools to execute

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
            return tool.execute(**args)
        except TypeError as e:
            # Wrong or missing arguments is a model mistake, and a TypeError is
            # exactly the message that lets it fix the call.
            return f"Error: Invalid arguments - {e}"


# =============================================================================
# 10. Main - the program around the loop
# =============================================================================
# Everything above is a library. This is the part that makes it a command, and
# it deliberately contains no agent logic: read the environment, build the
# objects, loop on input, print results.

def main():
    brain_name = os.getenv("NANOCODE_BRAIN", "claude")
    # Note the two forms of the same menu: the brain is constructed with tool
    # *definitions*, the agent with the tool *objects*.
    brain = BRAINS[brain_name](tools=tool_definitions(tools))
    agent = Agent(brain=brain, tools=tools, brain_name=brain_name)

    # The banner doubles as documentation: a reader should be able to see which
    # brain is live without asking.
    print(f"⚡ Nanocode v0.4 (Tools Enabled)")
    print(f"Commands: /q quit, /switch toggle brain")
    print(f"Brain: {brain_name}\n")

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
