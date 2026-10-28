# =============================================================================
#                          NANOCODE, CHAPTER 4
#     more than one brain - an interface, a registry, and a retry policy
# =============================================================================
#
# Chapter 3 wrote one model into the loop. This chapter makes the model a
# replaceable part, which requires three small structural decisions:
#
#   1. an interface    - Brain, the base class the loop is allowed to know
#   2. a registry      - BRAINS, name -> class, so a name is enough to build one
#   3. a shared home   - _parse_response moves out of Claude, because every
#                        provider that speaks this protocol needs the same parser
#
# Plus one thing that is not architecture but survival: request_with_retry.
# Model APIs answer 429 and 5xx as a matter of routine, and an agent that dies
# on the first hiccup is not usable.
#
# The payoff at the end is /switch - the same conversation, continued by a
# different company's model, mid-task.
#
# Run it with ANTHROPIC_API_KEY and/or DEEPSEEK_API_KEY in .env:
#
#     python nanocode.py                       # claude by default
#     NANOCODE_BRAIN=deepseek python nanocode.py
#
# Commands: /q quits, /switch rotates to the next brain.
# =============================================================================


# =============================================================================
# 1. Imports - the entire dependency list
# =============================================================================
# Three ideas, three imports:
#   os          reading API keys out of the environment
#   time        sleeping between retries
#   requests    every call to a model is one HTTP POST
# The retry loop is fifteen lines of ordinary Python, so no SDK, no backoff
# library, no framework.
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

# Quitting is not an error, but it does have to unwind handle_input and the REPL
# loop. Raising a private exception and catching it once in main() keeps "/q"
# out of every function's return values. KeyboardInterrupt is caught in the same
# place for the same reason.
class AgentStop(Exception):
    """Raised when the agent should stop processing."""
    pass


# =============================================================================
# 4. Brain response types - one shape, whatever the provider
# =============================================================================
# Providers disagree about the details of a reply, so the rest of the program is
# not allowed to see those details. think() returns a Thought and nothing else;
# everything downstream depends on these two small classes instead of on a
# particular company's JSON layout.

# A tool call is an address book entry: which call this is (id, echoed back in
# the result so the model can match request to answer), what to run (name), and
# with what (args, already a dict). Nothing executes anything yet - this chapter
# only records the requests the model makes.
class ToolCall:
    """A tool invocation request from the brain."""

    def __init__(self, id, name, args):
        self.id = id
        self.name = name
        self.args = args  # dict


# One reply from one model turn, flattened into the two things this chapter can
# act on: text to show the user, and private reasoning to maybe display.
class Thought:
    """Standardized response from any Brain."""

    def __init__(self, text=None, tool_calls=None, thinking=None):
        self.text = text  # str or None
        self.tool_calls = tool_calls or []  # list of ToolCall
        self.thinking = thinking  # str or None


# =============================================================================
# 5. Brain interface - how to talk to a model without caring which one
# =============================================================================

class Brain:
    """Base class for LLM providers."""

    def think(self, conversation):
        """Process conversation, return Thought."""
        # The only method the loop needs. Each subclass fills it in with its own
        # URL, key, model name and payload quirks. Calling it on the base class
        # is a programming error, not a runtime state.
        raise NotImplementedError

    def _parse_response(self, content):
        """Convert API response format to Thought."""
        # This is the second reason the base class exists. The Anthropic-style
        # block format is identical across providers, so the parser is written
        # once here instead of once per brain - and a provider that returns
        # something else only has to override this method.
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
            thinking=thinking
        )


# The first brain, now a subclass. Everything Anthropic-specific is in this
# class and nowhere else: the header names, the URL, the model id, and the
# decision to switch extended thinking on.

class Claude(Brain):
    """Claude API implementation."""

    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            # Fail at construction, not on the first turn: a missing key is a
            # setup mistake, and there is no point starting a REPL around it.
            raise ValueError("ANTHROPIC_API_KEY not found in .env")
        self.model = "claude-sonnet-4-6"
        self.url = "https://api.anthropic.com/v1/messages"

    def think(self, conversation):
        # Three headers, all required by Anthropic: the key, the API version
        # (a date, not a number), and the content type.
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

        # The only line that changed from chapter 3: the raw POST is now the
        # shared retry helper.
        response = request_with_retry(self.url, headers, payload)
        return self._parse_response(response.json()["content"])


# The second brain. The value here is not DeepSeek itself, it is the proof that
# adding a provider costs one class and nothing else: no change to Thought, no
# change to the loop, no conditionals. DeepSeek exposes an Anthropic-compatible
# endpoint, which is why this is a near-copy of Claude.

class DeepSeek(Brain):
    """DeepSeek API (Anthropic-compatible)."""

    def __init__(self):
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
# 6. Agent - the same loop, with a brain you can swap
# =============================================================================

class Agent:
    """A coding agent with switchable brain."""

    def __init__(self, brain, brain_name="claude"):
        self.brain = brain
        # The name is kept alongside the object because it is what the human
        # sees in the prompt, and because /switch needs to know its position in
        # the registry to find the next one.
        self.brain_name = brain_name
        # The conversation survives a brain switch. That is the whole point:
        # the history is the agent's state, and the brain is just the interpreter.
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

        # The user's message goes into the history *before* the call, so the
        # model sees it.
        self.conversation.append({"role": "user", "content": user_input})

        try:
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

            # Still plain text, still a simplification: a reply that asks for a
            # tool is stored as its text alone, so nothing can act on it yet.
            text = thought.text or ""
            self.conversation.append({"role": "assistant", "content": text})
            return text
        except Exception as e:
            # If the turn failed (network, API error), remove the message again.
            # Otherwise a dead turn stays in the history and every later request
            # inherits it.
            self.conversation.pop()
            return f"Error: {e}"

    def _switch_brain(self):
        """Toggle to the next brain."""
        names = list(BRAINS.keys())
        idx = names.index(self.brain_name)
        # Modulo, so the last brain wraps round to the first.
        new_name = names[(idx + 1) % len(names)]

        try:
            # The registry turns a name into a constructed brain. Note that the
            # conversation is deliberately *not* reset.
            self.brain = BRAINS[new_name]()
            self.brain_name = new_name
            return f"Switched to: {new_name}"
        except ValueError as e:
            # Constructors raise when a key is missing (no DEEPSEEK_API_KEY).
            # Report it and stay on the brain that works.
            return f"Cannot switch to {new_name}: {e}"


# =============================================================================
# 7. Main - the program around the loop
# =============================================================================
# Everything above is a library. This is the part that makes it a command, and
# it deliberately contains no agent logic: read the environment, build the
# objects, loop on input, print results.

def main():
    # Which brain to start with is a configuration decision, so it comes from
    # the environment rather than from the code.
    brain_name = os.getenv("NANOCODE_BRAIN", "claude")
    brain = BRAINS[brain_name]()
    agent = Agent(brain, brain_name)

    # The banner doubles as documentation: a reader should be able to see which
    # brain is live without asking.
    print(f"⚡ Nanocode v0.3")
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
