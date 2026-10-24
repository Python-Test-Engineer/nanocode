"""tools.py - Chapter 7: plan mode.

Every tool now declares `plan_safe`. The agent filters the tool menu by that
flag, so "plan mode" is not a rule the model is asked to respect - it is a
narrower menu it physically cannot see. Safety by construction, not by trust.

    plan_safe = True   read-only / harmless (read, search, write_plan, memory)
    plan_safe = False  changes the world (write, edit, run)

THE SAFETY MODEL IN ONE LINE
  Plan mode does not *tell* the model to avoid writes; it removes those tools
  from the request. A capability that is not offered cannot be used, which is a
  guarantee rather than an instruction. The agent does the filtering in
  Agent._tools_for_mode(); each tool only declares the fact here.
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
    plan_safe = True
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
    plan_safe = False
    description = "Writes content to a file."
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


class WritePlan:
    """Saves a plan to PLAN.md."""

    name = "write_plan"
    plan_safe = True
    description = "Saves a plan to PLAN.md. Use this to outline your approach before making changes."
    input_schema = {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The plan content in markdown"}
        },
        "required": ["content"],
    }

    def execute(self, context, content):
        # Plans are always PLAN.md, never a path argument: plan mode has exactly
        # one writable file, so the model has nothing to get wrong.
        ui.tool_action("write_plan", "PLAN.md")
        try:
            with open("PLAN.md", "w", encoding="utf-8") as f:
                f.write(content)
            return "Plan saved to PLAN.md"
        except Exception as e:
            return f"Error saving plan: {e}"


class SaveMemory:
    """Updates the agent's internal memory/scratchpad."""

    name = "save_memory"
    plan_safe = True
    description = "Updates your internal memory/scratchpad. Use this to remember user preferences."
    input_schema = {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The full text to save."}
        },
        "required": ["content"],
    }

    def execute(self, context, content):
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

tools = [ReadFile(), WritePlan(), SaveMemory(), WriteFile()]
