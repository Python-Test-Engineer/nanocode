# =============================================================================
#                          NANOCODE, CHAPTER 1
#                   the event loop (there is no AI yet)
# =============================================================================
#
# Every agent is a loop that reads what a person typed and does something with
# it. Before there is a model, a tool, or a single byte of JSON, there is that
# loop - and it is worth building on its own, because almost everything that
# goes wrong in a bigger agent goes wrong here:
#
#   - what happens when the user types nothing?
#   - how does the program end when the user types /q, or presses Ctrl-C?
#   - where does output come from, and who prints it?
#
# The agent below is a stub. It echoes. Its only real job is to establish the
# shape that the rest of the book fills in: a class that turns one line of input
# into one line of output, and a function that reads lines in a loop.
#
# Run it:  python nanocode.py
# =============================================================================


# =============================================================================
# 1. Exceptions - the one piece of control flow done with an exception
# =============================================================================

# Quitting is not an error, but it does have to unwind two nested layers:
# handle_input and the REPL. Raising a private exception and catching it once in
# main() keeps "/q" out of every function's return values. KeyboardInterrupt is
# caught in the same place for the same reason.
class AgentStop(Exception):
    """Raised when the agent should stop processing."""
    pass


# =============================================================================
# 2. Agent - one line in, one line out
# =============================================================================

class Agent:
    """A coding agent that processes user input."""

    # Nothing to set up yet. The class exists so that later chapters can grow a
    # brain, a tool list and a conversation in this method without changing the
    # shape of the program around it.
    def __init__(self):
        pass

    def handle_input(self, user_input):
        """Handle user input. Returns output string, raises AgentStop to quit."""
        # The command layer comes first, and it never reaches the agent itself:
        # /q is a control for the human, not a message for a model.
        if user_input.strip() == "/q":
            raise AgentStop()

        # A stray Enter should do nothing at all. Returning "" rather than None
        # keeps the caller's check simple ("if output: print(...)").
        if not user_input.strip():
            return ""

        # The whole of "the agent" for now: echo, plus an honest note that
        # nothing is connected. Every chapter after this replaces this one line.
        return f"You said: {user_input}\n(Agent not yet connected)"


# =============================================================================
# 3. Main - the loop that makes it a program
# =============================================================================
# Everything above is a library. This is the part that makes it a command, and
# it deliberately contains no agent logic: build the object, loop on input,
# print what comes back.

def main():
    agent = Agent()
    print("⚡ Nanocode v0.1 initialized.")
    print("Type '/q' to quit.")

    while True:
        try:
            # The prompt character is the only UI there is. Note that unlike
            # later chapters it carries no state - there is no mode or brain to
            # show yet.
            user_input = input("\n❯ ")
            output = agent.handle_input(user_input)
            # handle_input returns "" for blank lines, so a stray Enter prints
            # nothing at all.
            if output:
                print(output)

        # Both roads out of the REPL arrive here: /q via AgentStop, Ctrl-C via
        # KeyboardInterrupt. One exit path, one goodbye.
        except (AgentStop, KeyboardInterrupt):
            print("\nExiting...")
            break


# Only run when executed as a script, so the file can also be imported (tests,
# notebooks) without starting a REPL.
if __name__ == "__main__":
    main()
