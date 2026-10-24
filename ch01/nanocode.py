"""nanocode.py - Chapter 1: the event loop.

Nothing clever yet: a prompt, a reply, and a way out. What this chapter really
builds is the *shape* everything later plugs into - read a line, hand it to the
Agent, print whatever comes back, repeat until /q.

The only thing that is not from the book is where the printing happens: all of
it goes through ui.py so later chapters can colour it without touching the loop.

WHAT TO NOTICE
  * the loop already has its final shape: read a line, hand it to the agent,
    render the result - everything later plugs into these three lines
  * quitting is an exception (AgentStop), not a flag, so /q works from anywhere
  * the Agent has no brain yet, which is why handle_input returns a canned string
"""

import sys

import ui


# --- Exceptions ---

class AgentStop(Exception):
    """Raised when the agent should stop processing.

    An exception rather than a "should_quit" flag because quitting has to work
    from inside handle_input, from inside the loop, from anywhere - and the only
    caller that cares is main(), which catches it once.
    """
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

        # Chapter 1 has no model behind the curtain. Returning the input proves
        # the plumbing works: something reads, something answers, something draws.
        return f"You said: {user_input}\n(Agent not yet connected)"


# --- Main Loop ---

def main():
    ui.configure()
    agent = Agent()

    # The banner is the only "config" in this chapter: ui.banner takes whatever
    # the chapter knows about itself and omits the rest (no brain, no mode yet).
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
