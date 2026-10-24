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

THE CONTRACT
  name / description / input_schema are what the MODEL sees: the name it must
  call, the sentence telling it when to call it, and the JSON Schema that shapes
  the arguments. execute(**args) is what YOU run. The two halves never mix.

WHY ERRORS ARE STRINGS
  A traceback ends the turn; an error message continues it. "Error: File not
  found" goes back to the model as a tool result, and it can try another path.
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
        # The tool announces itself: tools.py is the only place that knows a tool
        # has started. The colour/verb come from ui.json's tools.read_file.
        ui.tool_action("read_file", path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                # Numbered lines are for the MODEL: they let it refer to "line 42"
                # later, and they make greps in the conversation unambiguous.
                lines = f.readlines()
            numbered_lines = [f"{i+1} | {line}" for i, line in enumerate(lines)]
            return "".join(numbered_lines)
        except Exception as e:
            # Catch-all on purpose: a tool must always return a string. The model
            # reads the error and decides what to do next.
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
            # "w" truncates the file. That is fine for new files; for edits to
            # existing code the model is expected to use edit_file (chapter 9),
            # which cannot silently drop what it forgot to copy.
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
