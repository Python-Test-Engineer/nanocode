"""nanocode.py - Chapter 4: multi-provider.

The agent no longer knows which model answers it. It holds a `Brain`, asks it
for a `Thought`, and can swap the brain mid-conversation with /switch.

Adding a provider is now: write a class with think(), put it in BRAINS.

WHY THE AGENT GOT SHORTER, NOT LONGER
  The provider-specific code (URL, headers, auth, payload) moved behind Brain in
  llm.py. The agent only ever calls `self.brain.think(conversation)`, so adding
  Claude and DeepSeek changed zero lines of agent logic - it added two classes
  and two registry entries.

WHAT /switch REALLY DOES
  It swaps the object, then rebuilds it with the same memory and tool menu. The
  conversation is untouched: it is plain text at this chapter, so every provider
  can read it.
"""

import os
import sys

from dotenv import load_dotenv

import ui
from hooks import Hooks, install
from llm import (  # noqa: F401  (re-exported: tests and callers import from nanocode)
    BRAINS,
    Brain,
    Claude,
    DeepSeek,
    OpenRouter,
    Thought,
    ToolCall,
    request_with_retry,
)

load_dotenv()


# --- Exceptions ---

class AgentStop(Exception):
    """Raised when the agent should stop processing."""
    pass


# --- Agent Class ---

class Agent:
    """A coding agent with a switchable brain."""

    def __init__(self, brain, brain_name="openrouter"):
        self.brain = brain
        self.brain_name = brain_name
        self.conversation: list[dict] = []
        self.hooks = Hooks()  # lifecycle hooks; see hooks.py
        self.output_rendered = False  # True when the UI already showed the text

    def handle_input(self, user_input):
        """Handle user input. Returns output string, raises AgentStop to quit."""
        self.output_rendered = False

        if user_input.strip() == "/q":
            raise AgentStop()

        if user_input.strip() == "/switch":
            return self._switch_brain()

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

    def _switch_brain(self):
        """Toggle to the next brain."""
        names = list(BRAINS.keys())
        idx = names.index(self.brain_name)
        new_name = names[(idx + 1) % len(names)]

        try:
            # Construct the next brain lazily, inside try: a provider with no API
            # key raises ValueError, and the agent should survive that instead
            # of dying mid-conversation.
            self.brain = BRAINS[new_name]()
            self.brain_name = new_name
            ui.switched(new_name, getattr(self.brain, "model", None))
            self.output_rendered = True
            return f"Switched to: {new_name}"
        except ValueError as e:
            return f"Cannot switch to {new_name}: {e}"


# --- Main Loop ---

def main():
    brain_name = os.getenv("NANOCODE_BRAIN", "openrouter")

    ui.configure()
    try:
        brain = BRAINS[brain_name]()
    except (KeyError, ValueError) as e:
        ui.error(f"Cannot start brain '{brain_name}': {e}")
        return 1

    agent = Agent(brain, brain_name)
    install(agent.hooks)  # coloured hook lines; NANOCODE_HOOKS=0 hides them
    ui.banner(version="v0.3", brain=brain_name, model=getattr(brain, "model", "?"))

    while True:
        try:
            user_input = ui.ask(agent.brain_name)
            output = agent.handle_input(user_input)
            if output and not agent.output_rendered:
                ui.answer(output)

        except (AgentStop, KeyboardInterrupt, EOFError):
            ui.goodbye("Exiting...")
            break

    return 0


if __name__ == "__main__":
    sys.exit(main())
