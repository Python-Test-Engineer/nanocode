"""nanocode.py - Chapter 5: tools.

The agent can now change the world instead of only talking about it. The shape
is small and it never changes again:

    1. send the conversation (+ the tool menu) to the brain
    2. if the reply asks for tools, run them
    3. append the results as a *user* message and loop
    4. stop when the reply has no tool calls left

Tools live in tools.py, the wire format in llm.py, the printing in ui.py.

WHAT TO WATCH FOR
  * the loop has no idea what a tool *does* - it only knows name + args
  * a reply may contain several tool calls at once; they are all executed before
    the next request, so the model sees all the results together
  * results go back as a user message of tool_result blocks; the conversation is
    always user / assistant / user / assistant, it just gets lumpier
  * `raw_content` is stored, not `text` - the next request must echo what the
    model actually said, including the ids that the results refer to
"""

import os
import sys

from dotenv import load_dotenv

import ui
from hooks import Hooks, install
from llm import BRAINS, Brain, Claude, DeepSeek, OpenRouter, Thought, ToolCall  # noqa: F401
from tools import (  # noqa: F401  (re-exported: tests and callers import from nanocode)
    ReadFile,
    WriteFile,
    get_tool,
    tool_definitions,
    tools,
)

load_dotenv()


# --- Exceptions ---

class AgentStop(Exception):
    """Raised when the agent should stop processing."""
    pass


# --- Agent Class ---

class Agent:
    """A coding agent with tools."""

    def __init__(self, brain, tools, brain_name="openrouter"):
        self.brain = brain
        self.tools = list(tools)  # Copy the tools list
        self.brain_name = brain_name
        self.conversation: list[dict] = []
        self.hooks = Hooks()  # lifecycle hooks; see hooks.py
        # The brain holds the *definitions* (the menu it shows the model), the
        # agent holds the objects (the code). Chapter 7 filters this menu.
        self.brain.tools = tool_definitions(self.tools)
        self.output_rendered = False

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
            return self._agentic_loop()
        except Exception as e:
            self.conversation.pop()  # Remove failed user message
            return f"Error: {e}"

    def _switch_brain(self):
        """Toggle to the next brain."""
        names = list(BRAINS.keys())
        idx = names.index(self.brain_name)
        new_name = names[(idx + 1) % len(names)]

        try:
            self.brain = BRAINS[new_name](tools=tool_definitions(self.tools))
            self.brain_name = new_name
            ui.switched(new_name, getattr(self.brain, "model", None))
            self.output_rendered = True
            return f"Switched to: {new_name}"
        except ValueError as e:
            return f"Cannot switch to {new_name}: {e}"

    def _agentic_loop(self):
        """Process brain responses, executing tools until done.

        This replaces chapter 3's single think() call. The difference between a
        chatbot and an agent is entirely this while-loop: ask, act, feed the
        result back, ask again - until a reply asks for nothing.
        """
        output_parts = []

        while True:
            self.hooks.emit("before_think", messages=len(self.conversation))
            thought = self.brain.think(self.conversation)
            self.hooks.emit("after_think", thought=thought)
            ui.thinking(thought.thinking)

            # Store raw content for message history (Claude expects this format)
            self.conversation.append({"role": "assistant", "content": thought.raw_content})

            if thought.text:
                output_parts.append(thought.text)

            if not thought.tool_calls:
                break  # No more tools to execute

            # One message per tool call, all collected before the next request.
            # The tool_use_id is what ties a result to the call that asked for it.
            tool_results = []
            for tool_call in thought.tool_calls:
                result = self._execute_tool(tool_call.name, tool_call.args)
                self.hooks.emit("tool_call", name=tool_call.name, args=tool_call.args, result=result)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call.id,
                    "content": result,
                })

            self.conversation.append({"role": "user", "content": tool_results})

        output = "\n".join(output_parts)
        self.hooks.emit("turn_end", output=output)
        return output

    def _execute_tool(self, name, args):
        """Execute a tool by name with given arguments.

        The agent looks tools up by NAME because that is all the model can send.
        Unknown names and bad arguments are returned as text, not raised: the
        model can read "Error: Tool 'foo' not found" and correct itself.
        """
        tool = get_tool(self.tools, name)
        if tool is None:
            ui.warning(f"Unknown tool: {name}")
            return f"Error: Tool '{name}' not found"
        try:
            return tool.execute(**args)
        except TypeError as e:
            return f"Error: Invalid arguments - {e}"


# --- Main Loop ---

def main():
    brain_name = os.getenv("NANOCODE_BRAIN", "openrouter")

    ui.configure()
    try:
        brain = BRAINS[brain_name](tools=tool_definitions(tools))
    except (KeyError, ValueError) as e:
        ui.error(f"Cannot start brain '{brain_name}': {e}")
        return 1

    agent = Agent(brain=brain, tools=tools, brain_name=brain_name)
    install(agent.hooks)  # coloured hook lines; NANOCODE_HOOKS=0 hides them
    ui.banner(version="v0.4 (Tools Enabled)", brain=brain_name,
              model=getattr(brain, "model", "?"), tool_count=len(agent.tools))

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
