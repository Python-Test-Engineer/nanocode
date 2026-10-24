"""nanocode.py - Chapter 6: persistent memory.

Conversation history dies when the process exits. Memory does not: it is one
markdown file, read at startup and sent as the system prompt, so preferences
survive across sessions - and the agent can rewrite it with save_memory.

Memory knows nothing about HTTP or Rich; it is a file with a save() method.
"""

import os
import sys

from dotenv import load_dotenv

import ui
from llm import BRAINS, Brain, Claude, DeepSeek, OpenRouter, Thought, ToolCall  # noqa: F401
from tools import (  # noqa: F401  (re-exported: tests and callers import from nanocode)
    ReadFile,
    SaveMemory,
    ToolContext,
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


# --- Memory Class ---

class Memory:
    """Persistent scratchpad for the agent."""

    def __init__(self, path=".nanocode/memory.md"):
        self.path = path
        self._ensure_exists()
        self.content = self._load()

    def _ensure_exists(self):
        """Create memory file with default content if needed."""
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        if not os.path.exists(self.path):
            default = "I am Nanocode, a helpful coding assistant.\n"
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(default)

    def _load(self):
        """Load content from disk."""
        with open(self.path, "r", encoding="utf-8") as f:
            return f.read()

    def save(self, content):
        """Update memory content and persist to disk."""
        self.content = content
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(content)


# --- Agent Class ---

class Agent:
    """A coding agent with tools and memory."""

    def __init__(self, brain, tools, memory=None, brain_name="openrouter"):
        self.brain = brain
        self.tools = list(tools)  # Copy the tools list
        self.memory = memory
        self.brain_name = brain_name
        self.conversation: list[dict] = []
        self.brain.tools = tool_definitions(self.tools)
        # Chapter 6 has no prompt builder yet: memory IS the system prompt.
        self.brain.system = memory.content if memory else None
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

        try:
            return self._agentic_loop()
        except Exception as e:
            self.conversation.pop()  # Remove failed user message
            return f"Error: {e}"

    def _agentic_loop(self):
        """Process brain responses, executing tools until done."""
        output_parts = []

        while True:
            thought = self.brain.think(self.conversation)
            ui.thinking(thought.thinking)

            # Store raw content for message history
            self.conversation.append({"role": "assistant", "content": thought.raw_content})

            if thought.text:
                output_parts.append(thought.text)

            if not thought.tool_calls:
                break

            tool_results = []
            for tool_call in thought.tool_calls:
                result = self._execute_tool(tool_call.name, tool_call.args)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call.id,
                    "content": result,
                })

            self.conversation.append({"role": "user", "content": tool_results})

        return "\n".join(output_parts)

    def _execute_tool(self, name, args):
        """Execute a tool by name with given arguments."""
        tool = get_tool(self.tools, name)
        if tool is None:
            ui.warning(f"Unknown tool: {name}")
            return f"Error: Tool '{name}' not found"
        try:
            context = ToolContext(memory=self.memory)
            return tool.execute(context, **args)
        except TypeError as e:
            return f"Error: Invalid arguments - {e}"

    def _switch_brain(self):
        """Toggle to the next brain."""
        names = list(BRAINS.keys())
        idx = names.index(self.brain_name)
        new_name = names[(idx + 1) % len(names)]

        try:
            self.brain = BRAINS[new_name](memory=self.memory, tools=tool_definitions(self.tools))
            self.brain.system = self.memory.content if self.memory else None
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
    memory = Memory()

    try:
        brain = BRAINS[brain_name](memory=memory, tools=tool_definitions(tools))
    except (KeyError, ValueError) as e:
        ui.error(f"Cannot start brain '{brain_name}': {e}")
        return 1

    agent = Agent(brain=brain, tools=tools, memory=memory, brain_name=brain_name)
    ui.banner(version="v0.5 (Memory Enabled)", brain=brain_name,
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
