"""nanocode.py - Chapter 9: the feedback loop.

Now the loop can close: the agent writes code, runs it, reads the traceback,
edits the file, runs it again. run_command is just another tool - the feedback
is just another string in the conversation, and a failed test is information the
model can act on rather than an exception that ends the turn.

Also here: conversation compaction. The brain reports the input tokens it used;
past 75% of the context window the agent summarises history instead of
overflowing and getting a 400 from the provider.
"""

import os
import sys

from dotenv import load_dotenv

import ui
from hooks import Hooks, install
from llm import BRAINS, Brain, Claude, DeepSeek, OpenRouter, Thought, ToolCall  # noqa: F401
from tools import (  # noqa: F401  (re-exported: tests and callers import from nanocode)
    ReadFile,
    SaveMemory,
    ToolContext,
    WriteFile,
    EditFile,
    ListFiles,
    RunCommand,
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
        self.hooks = Hooks()  # lifecycle hooks; see hooks.py
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
        """Return tool definitions based on current mode.

        The whole safety harness is this list comprehension: in plan mode the
        model is only *told about* tools whose plan_safe flag is True. There is
        no runtime permission check later, because an unoffered tool simply
        cannot be called - which is a much stronger guarantee.
        """
        if self.mode == "act":
            return tool_definitions(self.tools)
        return tool_definitions([t for t in self.tools if t.plan_safe])

    def _refresh_brain(self):
        """Push the current prompt and tool menu into the brain.

        The brain stores tools/system as attributes, so a mode change is only
        live once these two lines run. Forgetting this is the classic bug: the
        agent says "act mode" but the model still sees the old menu.
        """
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

        # /mode and /mode act|plan. Deliberately forgiving: "/mode" alone means
        # plan (the safe default), and anything else that is not "act" also means
        # plan - a typo should never silently enable writes.
        if command.startswith("/mode"):
            return self._handle_mode_command(command)

        self.conversation.append({"role": "user", "content": user_input})
        self.hooks.emit("turn_start", user_input=user_input)

        try:
            return self._agentic_loop()
        except Exception as e:
            self.conversation.pop()  # Remove failed user message
            return f"Error: {e}"

    def _handle_mode_command(self, user_input):
        """Handle /mode command to switch between plan and act."""
        parts = user_input.strip().split()
        # Explicit opt-in for writes: only the literal word "act" enables them.
        self.mode = "act" if len(parts) > 1 and parts[1] == "act" else "plan"
        self._refresh_brain()
        ui.mode_switch(self.mode)
        # The line above already drew the result, so main() must not print the
        # returned string as well; the string is for tests and other callers.
        self.output_rendered = True
        return f"Switched to {'ACT' if self.mode == 'act' else 'PLAN'} MODE"

    def _agentic_loop(self):
        """Process brain responses, executing tools until done."""
        output_parts = []

        while True:
            self.hooks.emit("before_think", messages=len(self.conversation))
            thought = self.brain.think(self.conversation)
            self.hooks.emit("after_think", thought=thought)
            ui.thinking(thought.thinking)

            # Compact if approaching the context limit
            if self.brain.last_input_tokens > self.brain.context_limit * 0.75:
                self._compact_conversation()

            # Store raw content for message history
            self.conversation.append({"role": "assistant", "content": thought.raw_content})

            if thought.text:
                output_parts.append(thought.text)

            if not thought.tool_calls:
                break

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

    def _compact_conversation(self):
        """Summarize old messages to stay within context limits.

        Called when the last reply reported using more than 75% of the window.
        The threshold is a judgement call: too low and you summarise away detail
        the agent still needs, too high and the next request is rejected.

        The transcript sent to the summariser is truncated to 500 chars per
        message - the point is to keep decisions, not every byte.
        """
        ui.compact()
        history = "\n".join(
            f"{m['role']}: {str(m['content'])[:500]}"
            for m in self.conversation
        )
        prompt = [{
            "role": "user",
            "content": f"Summarize this conversation for continuity. "
                       f"Focus on what was accomplished, what's in progress, "
                       f"and key decisions:\n\n{history}",
        }]
        # Summarising with the tool menu removed: this is a bookkeeping request,
        # not a turn the model should act on. try/finally puts the menu back even
        # if the call fails.
        saved_tools = self.brain.tools
        self.brain.tools = []
        try:
            thought = self.brain.think(prompt)
        finally:
            self.brain.tools = saved_tools
        # History is replaced by the summary: one message, far fewer tokens, and
        # the only detail lost is what the summary was asked to keep.
        self.conversation = [
            {"role": "user", "content": f"Previous conversation summary: {thought.text}"},
        ]

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
    # The CLI mirrors /mode: plan is the default because it is the safe one.
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
    install(agent.hooks)  # coloured hook lines; NANOCODE_HOOKS=0 hides them
    ui.banner(version="v0.8 (Feedback Loop)", brain=brain_name,
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
