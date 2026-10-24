"""nanocode.py - Chapter 3: a stateful chatbot.

The loop from chapter 1 now has a brain behind it. Two lists of messages - what
the user said, what the model said - are the whole of "memory" in this chapter:
the conversation is resent on every turn, so the model can see what came before.

The brain lives in llm.py, the printing in ui.py.
"""

import os
import sys

from dotenv import load_dotenv

import ui
from hooks import Hooks, install
from llm import BRAINS, OpenRouter, Thought, ToolCall  # noqa: F401  (re-exported for tests)

load_dotenv()


# --- Exceptions ---

class AgentStop(Exception):
    """Raised when the agent should stop processing."""
    pass


# --- Agent Class ---

class Agent:
    """A coding agent with conversation memory."""

    def __init__(self, brain, brain_name="openrouter"):
        self.brain = brain
        self.brain_name = brain_name
        self.conversation = []
        self.hooks = Hooks()  # lifecycle hooks; see hooks.py

    def handle_input(self, user_input):
        """Handle user input. Returns output string, raises AgentStop to quit."""
        if user_input.strip() == "/q":
            raise AgentStop()

        if not user_input.strip():
            return ""

        self.conversation.append({"role": "user", "content": user_input})
        self.hooks.emit("turn_start", user_input=user_input)

        try:
            self.hooks.emit("before_think", messages=len(self.conversation))
            thought = self.brain.think(self.conversation)
            self.hooks.emit("after_think", thought=thought)
            ui.thinking(thought.thinking)

            text = thought.text or ""
            self.conversation.append({"role": "assistant", "content": text})
            self.hooks.emit("turn_end", output=text)
            return text
        except Exception as e:
            self.conversation.pop()  # Remove failed user message
            return f"Error: {e}"


# --- Main Loop ---

def main():
    brain_name = os.getenv("NANOCODE_BRAIN", "openrouter")

    ui.configure()
    try:
        brain = BRAINS[brain_name]()
    except (KeyError, ValueError) as e:
        ui.error(f"Cannot start brain '{brain_name}': {e}")
        return 1

    agent = Agent(brain, brain_name=brain_name)
    install(agent.hooks)  # coloured hook lines; NANOCODE_HOOKS=0 hides them
    ui.banner(version="v0.2 (Conversation Memory)", brain=brain_name,
              model=getattr(brain, "model", "?"), hint="type /q to quit")

    while True:
        try:
            user_input = ui.ask()
            output = agent.handle_input(user_input)
            if output:
                ui.answer(output)

        except (AgentStop, KeyboardInterrupt, EOFError):
            ui.goodbye("Exiting...")
            break

    return 0


if __name__ == "__main__":
    sys.exit(main())
