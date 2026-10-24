"""nanocode.py - Chapter 8: codebase context.

The agent can now see the shape of the project before it touches anything:
list_files gives it the tree, search_codebase gives it "where is this defined?".
Both are read-only (plan_safe), so they work in plan mode too.

Two modes, one agent:

    plan  read-only tools only; the agent researches and writes PLAN.md
    act   everything; the agent changes files and runs commands

The mode changes two things at once - which tools the brain is offered, and
what the system prompt says - so the model is never asked to police itself.
Start in act with:  uv run ch08/nanocode.py --act
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
    ListFiles,
    SearchCodebase,
    WritePlan,
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
    """A coding agent with tools, memory, and a safety mode."""

    def __init__(self, brain, tools, memory=None, mode="plan", brain_name="openrouter"):
        self.brain = brain
        self.tools = list(tools)  # Copy the tools list
        self.memory = memory
        self.mode = mode  # "plan" or "act"
        self.brain_name = brain_name
        self.conversation: list[dict] = []
        self.brain.tools = self._tools_for_mode()
        self.brain.system = self._build_system_prompt()
        self.output_rendered = False

    def _build_system_prompt(self):
        """Build system prompt from memory and current mode."""
        parts = [self.memory.content] if self.memory else []
        if self.mode == "plan":
            parts.append(
                "You are in PLAN mode. You cannot write code files. "
                "Use write_plan to save your plans to PLAN.md."
            )
        return "\n".join(parts)

    def _tools_for_mode(self):
        """Return tool definitions based on current mode."""
        if self.mode == "act":
            return tool_definitions(self.tools)
        return tool_definitions([t for t in self.tools if t.plan_safe])

    def _refresh_brain(self):
        """Push the current prompt and tool menu into the brain."""
        self.brain.tools = self._tools_for_mode()
        self.brain.system = self._build_system_prompt()

    def handle_input(self, user_input):
        """Handle user input. Returns output string, raises AgentStop to quit."""
        self.output_rendered = False
        command = user_input.strip()

        if command == "/q":
            raise AgentStop()

        if command == "/switch":
            return self._switch_brain()

        if command == "/help":
            ui.help_table(only=("/q", "/switch", "/mode"))
            ui.help_meta(self.brain_name, getattr(self.brain, "model", "?"), self.mode)
            self.output_rendered = True
            return ""

        if not command:
            return ""

        if command.startswith("/mode"):
            return self._handle_mode_command(command)

        self.conversation.append({"role": "user", "content": user_input})

        try:
            return self._agentic_loop()
        except Exception as e:
            self.conversation.pop()  # Remove failed user message
            return f"Error: {e}"

    def _handle_mode_command(self, user_input):
        """Handle /mode command to switch between plan and act."""
        parts = user_input.strip().split()
        self.mode = "act" if len(parts) > 1 and parts[1] == "act" else "plan"
        self._refresh_brain()
        ui.mode_switch(self.mode)
        self.output_rendered = True
        return f"Switched to {'ACT' if self.mode == 'act' else 'PLAN'} MODE"

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
            self.brain = BRAINS[new_name](memory=self.memory, tools=self._tools_for_mode())
            self.brain.system = self._build_system_prompt()
            self.brain_name = new_name
            ui.switched(new_name, getattr(self.brain, "model", None))
            self.output_rendered = True
            return f"Switched to: {new_name}"
        except ValueError as e:
            return f"Cannot switch to {new_name}: {e}"


# --- Main Loop ---

def main():
    mode = "act" if "--act" in sys.argv[1:] else "plan"
    brain_name = os.getenv("NANOCODE_BRAIN", "openrouter")

    ui.configure()
    memory = Memory()

    try:
        brain = BRAINS[brain_name](memory=memory, tools=tool_definitions(tools))
    except (KeyError, ValueError) as e:
        ui.error(f"Cannot start brain '{brain_name}': {e}")
        return 1

    agent = Agent(brain=brain, tools=tools, memory=memory, mode=mode, brain_name=brain_name)
    ui.banner(version="v0.7 (Codebase Context)", brain=brain_name,
              model=getattr(brain, "model", "?"), mode=mode, tool_count=len(agent.tools))

    while True:
        try:
            user_input = ui.ask(agent.brain_name, agent.mode)
            output = agent.handle_input(user_input)
            if output and not agent.output_rendered:
                ui.answer(output)

        except (AgentStop, KeyboardInterrupt, EOFError):
            ui.goodbye("Exiting...")
            break

    return 0


if __name__ == "__main__":
    sys.exit(main())
