"""tools.py - Chapter 6: tools that need context.

save_memory is the first tool that cannot do its job from its arguments alone:
it needs the agent's Memory object. So every tool now receives a `ToolContext`
as its first argument - the bag of agent state a tool is allowed to touch.

    execute(context, **args) -> str

Tools still return strings and never raise at the model.

WHY A CONTEXT OBJECT
  save_memory cannot work from its arguments alone: it needs the agent's Memory.
  Passing `memory` to every tool would couple tools to the agent's internals;
  passing a small ToolContext keeps that coupling in one typed-looking place, and
  means chapter 7+ can add agent state without changing nine signatures again.
"""

import ui


# --- Tool Context ---

class ToolContext:
    """What tools need to know about the agent's state."""

    def __init__(self, memory=None):
        self.memory = memory  # Memory object or None


# --- Tool Classes ---

class ReadFile:
    """Reads a file from the filesystem."""

    name = "read_file"
    description = "Reads a file from the filesystem. Use this to examine code."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "The path to the file"}
        },
        "required": ["path"],
    }

    def execute(self, context, path):
        ui.tool_action("read_file", path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            numbered_lines = [f"{i+1} | {line}" for i, line in enumerate(lines)]
            return "".join(numbered_lines)
        except Exception as e:
            return f"Error reading file: {e}"


class WriteFile:
    """Writes content to a file."""

    name = "write_file"
    description = "Writes content to a file. OVERWRITES existing content."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "The path to the file"},
            "content": {"type": "string", "description": "The full content to write"},
        },
        "required": ["path", "content"],
    }

    def execute(self, context, path, content):
        ui.tool_action("write_file", path)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote {len(content)} characters to {path}"
        except Exception as e:
            return f"Error writing file: {e}"


class SaveMemory:
    """Updates the agent's internal memory/scratchpad."""

    name = "save_memory"
    description = "Updates your internal memory/scratchpad. Use this to remember user preferences."
    input_schema = {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The full text to save."}
        },
        "required": ["content"],
    }

    def execute(self, context, content):
        # The whole point of the context: the tool reaches the agent's Memory
        # through it. If memory is missing the tool says so instead of crashing.
        ui.tool_action("save_memory", f"{len(content)} chars")
        if context.memory is None:
            return "Error: Memory not available"
        context.memory.save(content)
        return "Memory updated successfully."


# --- Tool Helpers ---

def get_tool(tools, name):
    """Find a tool by name, or None if not found."""
    return next((t for t in tools if t.name == name), None)


def tool_definitions(tools):
    """Return tool definitions for the API."""
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


# --- Tools List ---

tools = [ReadFile(), WriteFile(), SaveMemory()]
