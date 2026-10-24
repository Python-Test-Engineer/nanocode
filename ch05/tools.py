"""tools.py - Chapter 5: the agent's first hands.

A tool is a class with three things the model can read:
    name         the string it calls
    description  when to use it
    input_schema JSON schema for the arguments

...and one method the agent calls: execute(**args) -> str.

Tools return strings, errors included. Never raise at the model: an error
message is information the agent can act on, a traceback is not.

Console feedback goes through ui.tool_action(name, detail) so each tool's
colour lives in ui.json, not here.
"""

import ui


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

    def execute(self, path):
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

    def execute(self, path, content):
        ui.tool_action("write_file", path)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote {len(content)} characters to {path}"
        except Exception as e:
            return f"Error writing file: {e}"


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

tools = [ReadFile(), WriteFile()]
