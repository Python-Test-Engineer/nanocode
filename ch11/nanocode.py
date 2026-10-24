"""nanocode.py - Chapter 11: web search.

The last feature before the capstone: search_web gives the agent the ability to
look things up (library versions, error messages, API changes) instead of relying
on training data. The agent itself is now finished - the loop, the modes, the
memory, the compaction and the hooks are all the same code you will read in ch12.

If you compare ch11 and ch12 you will find them identical: the book's chapter 12
is a capstone exercise, not a new feature.
"""

import os
import sys

from dotenv import load_dotenv

import ui
from hooks import Hooks, install
# Re-exported on purpose: the book's tests (and anything a reader writes) import
# names like `Agent`, `tools`, `BRAINS` from `nanocode`, exactly as they did when
# this was one file. Splitting the file must not change the import surface.
from llm import (  # noqa: F401  (re-exported: tests and callers import from nanocode)
    BRAINS,
    Brain,
    Claude,
    DeepSeek,
    Ollama,
    OpenRouter,
    Thought,
    ToolCall,
    request_with_retry,
)
from tools import (  # noqa: F401  (re-exported for convenience)
    DDGS,
    EditFile,
    ListFiles,
    ReadFile,
    RunCommand,
    SaveMemory,
    SearchCodebase,
    SearchWeb,
    ToolContext,
    WriteFile,
    WritePlan,
    get_tool,
    tool_definitions,
    tools,
)

load_dotenv()

MAX_ITERATIONS = 50


# --- Exceptions ---

class AgentStop(Exception):
    """Raised when the agent should stop processing."""
    pass


# --- Memory Class ---

class Memory:
    """Persistent scratchpad for the agent.

    One markdown file, read at startup and sent as the system prompt. The agent
    can rewrite it through save_memory, which is how a preference survives a
    restart - the conversation does not, but the memory does.

    A file (not a database, not a vector store) on purpose: you can open it,
    edit it, diff it and delete it. That is the whole feature.
    """

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
    """A coding agent with tools, memory, and safety mode.

    State worth knowing about:
      conversation    the messages sent to the brain each turn (shape: llm.py)
      mode            "plan" (read-only tools) or "act" (everything)
      tools           the tool OBJECTS; the brain gets their *definitions*
      hooks           event bus (see hooks.py); passive observers only
      output_rendered True when a command already printed its own result, so
                      main() does not print the returned string a second time
    """

    def __init__(self, brain, tools, memory=None, mode="plan", brain_name="openrouter"):
        self.brain = brain
        self.tools = list(tools)  # Copy the tools list
        self.memory = memory
        self.mode = mode  # "plan" or "act"
        self.brain_name = brain_name
        self.conversation: list[dict] = []
        self.hooks = Hooks()  # lifecycle hooks; see hooks.py
        self.output_rendered = False  # True when the UI already showed the text
        self.brain.tools = self._tools_for_mode()
        self.brain.system = self._build_system_prompt()

    # --- Prompt & tool menu ---

    def _build_system_prompt(self):
        """Build system prompt from memory and current mode.

        Two parts: who the agent is (the memory file) and what it may do right now
        (the mode rule). The mode rule is stated to the model *and* enforced by
        the tool menu in _tools_for_mode() - telling a model it cannot write is a
        request; not giving it write_file is a guarantee.
        """
        parts = [self.memory.content] if self.memory else []
        if self.mode == "plan":
            parts.append(
                "You are in PLAN mode. You cannot write code files. "
                "Use write_plan to save your plans to PLAN.md."
            )
        return "\n".join(parts)

    def _tools_for_mode(self):
        """Return tool definitions based on current mode.

        PLAN mode sends only plan_safe tools, so the model cannot even see
        write_file, edit_file or run_command. This is the safety harness: it does
        not depend on the model behaving.
        """
        if self.mode == "act":
            return tool_definitions(self.tools)
        return tool_definitions([t for t in self.tools if t.plan_safe])

    def _refresh_brain(self):
        """Push the current prompt and tool menu into the brain."""
        self.brain.tools = self._tools_for_mode()
        self.brain.system = self._build_system_prompt()

    # --- Input handling ---

    def handle_input(self, user_input):
        """Handle user input. Returns output string, raises AgentStop to quit."""
        self.output_rendered = False
        command = user_input.strip()

        # Slash commands are handled before anything reaches the model: they are
        # agent operations, not conversation. /q raises instead of returning so
        # main() can exit from anywhere.
        if command == "/q":
            raise AgentStop()

        if command == "/switch":
            return self._switch_brain()

        if command == "/help":
            ui.help_table()
            ui.help_meta(self.brain_name, getattr(self.brain, "model", "?"), self.mode)
            self.output_rendered = True
            return ""

        if not command:
            return ""

        # Handle mode switching
        if command.startswith("/mode"):
            return self._handle_mode_command(command)

        self.conversation.append({"role": "user", "content": user_input})
        self.hooks.emit("turn_start", user_input=user_input)

        try:
            return self._agentic_loop()
        except Exception as e:
            self.conversation.pop()  # Remove failed user message
            ui.error(str(e))
            return ""

    def _handle_mode_command(self, user_input):
        """Handle /mode command to switch between plan and act."""
        parts = user_input.strip().split()
        self.mode = "act" if len(parts) > 1 and parts[1] == "act" else "plan"
        self._refresh_brain()
        ui.mode_switch(self.mode)
        self.output_rendered = True
        return f"Switched to {'ACT' if self.mode == 'act' else 'PLAN'} MODE"

    def _agentic_loop(self):
        """Process brain responses, executing tools until done.

        The heart of the agent. Each iteration is one round trip to the model;
        the loop ends when a reply contains no tool calls. MAX_ITERATIONS is a
        guard against a model that keeps calling tools forever - without it, a
        confused model could spend your budget in a loop.
        """
        output_parts = []

        for _iteration in range(MAX_ITERATIONS):
            self.hooks.emit("before_think", messages=len(self.conversation))
            ui.send()
            thought = self.brain.think(self.conversation)
            self.hooks.emit("after_think", thought=thought)

            # Display thinking
            if thought.thinking:
                ui.thinking(thought.thinking)

            # Compact if approaching context limit
            if self.brain.last_input_tokens > self.brain.context_limit * 0.75:
                self._compact_conversation()

            # Append the provider's own blocks, not thought.text. The next request
            # must see exactly what the model said - including tool_use ids -
            # otherwise the tool results that follow would refer to nothing.
            self.conversation.append({"role": "assistant", "content": thought.raw_content})

            # Collect text output
            if thought.text:
                output_parts.append(thought.text)

            # Check for tool calls
            if not thought.tool_calls:
                break

            # Execute the requested tools. Results go back as a *user* message
            # made of tool_result blocks: in this dialect the "user turn" is
            # whatever the model needs to hear next, and that includes tool output.
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
        else:
            output_parts.append("(Stopped: too many iterations)")

        output = "\n".join(output_parts)
        self.hooks.emit("turn_end", output=output)
        return output

    def _compact_conversation(self):
        """Summarize old messages to stay within context limits."""
        ui.compact()
        # A crude transcript for the summariser: role plus the first 500 chars of
        # each message. Truncating is the point - the history is too long to send,
        # and the summary only needs to preserve decisions, not every byte.
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
        # Ask for the summary with the tool menu temporarily removed: this is a
        # bookkeeping request, not a turn the model should act on. try/finally
        # restores the menu even if the call raises.
        saved_tools = self.brain.tools
        self.brain.tools = []
        try:
            thought = self.brain.think(prompt)
        finally:
            self.brain.tools = saved_tools
        # History is *replaced* by the summary. One message, far fewer tokens -
        # and the only thing lost is detail the summary was asked to keep.
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
            # Tools receive a context (agent state they may use) plus the model's
            # arguments as keywords. A TypeError here means the model invented an
            # argument name - a useful message, not a crash.
            context = ToolContext(memory=self.memory)
            return tool.execute(context, **args)
        except TypeError as e:
            return f"Error: Invalid arguments - {e}"

    # --- Brains ---

    def _switch_brain(self):
        """Toggle to the next brain.

        Cycles BRAINS in order and rebuilds the new brain with the same memory and
        tool menu. History is untouched: because raw_content is stored in one
        canonical dialect, the new provider can read everything said so far.
        """
        names = list(BRAINS.keys())
        idx = names.index(self.brain_name) if self.brain_name in names else -1
        new_name = names[(idx + 1) % len(names)]

        try:
            self.brain = BRAINS[new_name](memory=self.memory, tools=self._tools_for_mode())
            self.brain.system = self._build_system_prompt()
            self.brain_name = new_name
            ui.switched(new_name, getattr(self.brain, "model", None))
            self.output_rendered = True
            return f"Switched to: {new_name}"
        except ValueError as e:
            ui.error(f"Cannot switch to {new_name}: {e}")
            return ""


# --- Main Loop ---

def main():
    # Two entry points into the same agent: plan (read-only, the safe default)
    # and act (writes allowed). Parsed by hand - one flag does not need argparse.
    mode = "act" if "--act" in sys.argv[1:] else "plan"
    brain_name = os.getenv("NANOCODE_BRAIN", "openrouter")

    ui.configure()
    memory = Memory()

    try:
        brain = BRAINS[brain_name](memory=memory, tools=tool_definitions(tools))
    except (KeyError, ValueError) as e:
        ui.error(f"Cannot start brain '{brain_name}': {e}")
        ui.info(f"Available: {', '.join(BRAINS)}")
        return 1

    agent = Agent(brain=brain, tools=tools, memory=memory, mode=mode, brain_name=brain_name)

    install(agent.hooks)  # coloured hook lines; NANOCODE_HOOKS=0 hides them
    ui.banner(
        brain=brain_name,
        model=getattr(brain, "model", "?"),
        mode=mode,
        version="v1.0",
        tool_count=len(agent.tools),
    )

    # The read-eval-print loop. All it does is: ask, hand the line to the agent,
    # render what comes back. Ctrl+C and Ctrl+D both mean "stop politely".
    while True:
        try:
            user_input = ui.ask(agent.brain_name, agent.mode)
            output = agent.handle_input(user_input)
            if output and not agent.output_rendered:
                # Commands print their own coloured result and set the flag, so
                # they are not echoed a second time here.
                ui.answer(output)

        except AgentStop:
            ui.goodbye("Exiting...")
            break
        except (KeyboardInterrupt, EOFError):
            ui.goodbye("Exiting...")
            break

    return 0


if __name__ == "__main__":
    sys.exit(main())
