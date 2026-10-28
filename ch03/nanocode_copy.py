# =============================================================================
#                          NANOCODE, CHAPTER 3
#          the first brain - and the conversation becomes memory
# =============================================================================
#
# Chapter 1 was a loop with nothing in it. This chapter puts a language model
# inside that loop, which turns it into something you can genuinely call an
# agent:
#
#   the user types -> the message joins a *conversation* -> the model answers
#   -> the answer is appended to the conversation -> the loop asks again
#
# The important new word is "conversation". A model is stateless: it remembers
# nothing between HTTP requests. Everything it appears to remember is the list
# of messages we send it every single time. That list is the agent's memory,
# and at this point in the book it is the only state there is.
#
# There are no tools yet, and no safety mode. The agent can talk. It cannot act.
#
# Run it with ANTHROPIC_API_KEY set in .env:
#
#     python nanocode.py
#
# Type /q to quit.
# =============================================================================


# =============================================================================
# 1. Imports - the entire dependency list
# =============================================================================
# Two ideas, two imports, for now:
#   os          reading ANTHROPIC_API_KEY out of the environment
#   requests    every call to the model is one HTTP POST
# Nothing else is needed. An agent at this stage is a loop around an API call -
# no framework, no SDK, no abstractions to learn first.
import os
import requests
from dotenv import load_dotenv

# Read .env from the current directory into os.environ, before anything reads a
# key - which is why it sits above every class in this file.
load_dotenv()


# =============================================================================
# 2. Exceptions - the one piece of control flow done with an exception
# =============================================================================

# Quitting is not an error, but it does have to unwind both handle_input and the
# REPL loop. Raising a private exception and catching it once in main() keeps
# "/q" out of every function's return values. KeyboardInterrupt is caught in the
# same place for the same reason.
class AgentStop(Exception):
    """Raised when the agent should stop processing."""
    pass


# =============================================================================
# 3. Brain response types - one shape, whatever the provider
# =============================================================================
# The model's reply arrives as a list of typed content blocks, not as a string.
# Rather than let that JSON shape leak into the loop, it is converted into two
# small classes the loop can reason about.

# A tool call is an address book entry: which call this is (id, echoed back in
# the result so the model can match request to answer), what to run (name), and
# with what (args, already a dict). Nothing here executes anything yet - this
# chapter only *records* the requests the model makes.
class ToolCall:
    """A tool invocation request from the brain."""

    def __init__(self, id, name, args):
        self.id = id
        self.name = name
        self.args = args  # dict


# One reply from one model turn, flattened into the two things this chapter can
# act on: text to show the user, and private reasoning to maybe display.
# tool_calls is carried but unused - it is the hook the next chapter hangs the
# tool loop on.
class Thought:
    """Standardized response from any Brain."""

    def __init__(self, text=None, tool_calls=None, thinking=None):
        self.text = text  # str or None
        self.tool_calls = tool_calls or []  # list of ToolCall
        self.thinking = thinking  # str or None


# =============================================================================
# 4. Claude - the first brain
# =============================================================================
# Everything Anthropic-specific lives in this class and nowhere else: the header
# names, the URL, the model id, the decision to switch extended thinking on, and
# the parsing of the reply. The rest of the program never sees any of it.

class Claude:
    """Claude API - the brain of our agent."""

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

        # No retry logic yet, and no error formatting: raise_for_status turns a
        # 4xx/5xx into an exception, which handle_input catches and shows to the
        # user. Chapter 4 replaces this line with something that survives a rate
        # limit.
        response = requests.post(self.url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        return self._parse_response(response.json()["content"])

    def _parse_response(self, content):
        """Convert Claude's response format to Thought."""
        # A reply can contain several blocks at once - reasoning, prose, tool
        # requests - so this walks the list instead of assuming one type.
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


# =============================================================================
# 5. Agent - the conversation is the agent's entire state
# =============================================================================

class Agent:
    """A coding agent with conversation memory."""

    def __init__(self, brain):
        self.brain = brain
        # The conversation is the agent's actual state. Everything the model
        # knows about this session lives in this list, and it is re-sent in full
        # on every request - that is what "memory" means for an LLM.
        self.conversation = []

    def handle_input(self, user_input):
        """Handle user input. Returns output string, raises AgentStop to quit."""
        # Slash commands are handled before anything reaches the model. They are
        # the human's controls, not the agent's.
        if user_input.strip() == "/q":
            raise AgentStop()

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

            # The assistant's reply is appended as plain text. That is a
            # simplification the next chapters have to undo: a real reply may
            # contain thinking and tool_use blocks, and the API validates the
            # history it is given.
            text = thought.text or ""
            self.conversation.append({"role": "assistant", "content": text})
            return text
        except Exception as e:
            # If the turn failed (bad key, network, API error), remove the
            # message again. Otherwise a dead turn stays in the history and every
            # later request inherits it.
            self.conversation.pop()  # Remove failed user message
            return f"Error: {e}"


# =============================================================================
# 6. Main - the program around the loop
# =============================================================================
# Everything above is a library. This is the part that makes it a command, and
# it deliberately contains no agent logic: build the objects, loop on input,
# print what comes back.

def main():
    brain = Claude()
    agent = Agent(brain)
    print("⚡ Nanocode v0.2 (Conversation Memory)")
    print("Type '/q' to quit.\n")

    while True:
        try:
            user_input = input("❯ ")
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
