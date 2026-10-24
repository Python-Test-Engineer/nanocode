"""nanocode.py - Chapter 1: the event loop.

Nothing clever yet: a prompt, a reply, and a way out. What this chapter really
builds is the *shape* everything later plugs into - read a line, hand it to the
Agent, print whatever comes back, repeat until /q.

The only thing that is not from the book is where the printing happens: all of
it goes through ui.py so later chapters can colour it without touching the loop.
"""

import sys

import ui


# --- Exceptions ---

class AgentStop(Exception):
    """Raised when the agent should stop processing."""
    pass


# --- Agent Class ---

class Agent:
    """A coding agent that processes user input."""

    def __init__(self):
        pass

    def handle_input(self, user_input):
        """Handle user input. Returns output string, raises AgentStop to quit."""
        if user_input.strip() == "/q":
            raise AgentStop()

        if not user_input.strip():
            return ""

        return f"You said: {user_input}\n(Agent not yet connected)"


# --- Main Loop ---

def main():
    ui.configure()
    agent = Agent()

    ui.banner(version="v0.1", hint="type /q to quit")

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
