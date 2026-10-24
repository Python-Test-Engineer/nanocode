"""tools.py - everything the agent can *do* to the world.

Each tool is a class with four pieces the model sees:
    name         the string the model calls
    description  when to use it
    input_schema JSON schema for the arguments
    plan_safe    True = allowed in PLAN mode (read-only / harmless)

...and one method the agent calls:
    execute(context, **args) -> str

Tools return strings, errors included. Never raise at the model: an error
message is information the agent can act on, a traceback is not.

Console feedback goes through ui.tool_action(name, detail) so each tool's
colour lives in ui.json, not here.
"""

import os
import subprocess
import sys

import ui

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None


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
        except FileNotFoundError:
            return f"Error: File not found: {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
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
        ui.tool_action("write_plan", "PLAN.md")
        try:
            with open("PLAN.md", "w", encoding="utf-8") as f:
                f.write(content)
            return "Plan saved to PLAN.md"
        except Exception as e:
            return f"Error saving plan: {e}"


class EditFile:
    """Replaces text in a file (surgical edit)."""

    name = "edit_file"
    plan_safe = False
    description = "Replaces specific text in a file. Use for surgical edits instead of rewriting entire files."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file"},
            "old_text": {"type": "string", "description": "Exact text to find and replace"},
            "new_text": {"type": "string", "description": "Text to replace it with"},
        },
        "required": ["path", "old_text", "new_text"],
    }

    def execute(self, context, path, old_text, new_text):
        ui.tool_action("edit_file", path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            if old_text not in content:
                return f"Error: Could not find the specified text in {path}"
            new_content = content.replace(old_text, new_text, 1)
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
            return f"Successfully edited {path}"
        except Exception as e:
            return f"Error editing file: {e}"


class ListFiles:
    """Lists files in the project structure."""

    name = "list_files"
    plan_safe = True
    description = "Lists all files in the project structure. Useful to understand the project layout."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "The root path (default '.')"}
        },
    }

    def execute(self, context, path="."):
        ui.tool_action("list_files", path)
        try:
            file_list = []
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "venv", ".venv", ".nanocode"}]

                level = root.replace(path, "").count(os.sep)
                indent = " " * 4 * level
                file_list.append(f"{indent}{os.path.basename(root)}/")
                subindent = " " * 4 * (level + 1)
                for f in files:
                    file_list.append(f"{subindent}{f}")

            return "\n".join(file_list)
        except Exception as e:
            return f"Error listing files: {e}"


class SearchCodebase:
    """Searches for a string in all files."""

    name = "search_codebase"
    plan_safe = True
    description = "Searches the entire codebase for a text string. Useful to find where functions or variables are defined."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The string to search for"},
            "path": {"type": "string", "description": "The root path (default '.')"},
        },
        "required": ["query"],
    }

    def execute(self, context, query, path="."):
        ui.tool_action("search_codebase", f"'{query}'")
        results = []
        try:
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "venv", ".venv", ".nanocode"}]

                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            for i, line in enumerate(f):
                                if query.lower() in line.lower():
                                    results.append(f"{file_path}:{i+1}: {line.strip()}")
                    except Exception:
                        continue

            return "\n".join(results) if results else "No matches found."
        except Exception as e:
            return f"Error searching: {e}"


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


class RunCommand:
    """Executes shell commands."""

    name = "run_command"
    plan_safe = False
    description = "Executes a terminal command. Use this to run scripts, tests, or install packages."
    input_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command to run (e.g., 'python test.py')"}
        },
        "required": ["command"],
    }

    def execute(self, context, command):
        preview = command if len(command) <= 60 else command[:57] + "..."
        ui.tool_action("run_command", preview)
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=int(os.environ.get("NANOCODE_TIMEOUT", "30")),
                cwd=os.getcwd(),
            )

            output = ""
            if result.stdout:
                output += f"STDOUT:\n{result.stdout}\n"
            if result.stderr:
                output += f"STDERR:\n{result.stderr}\n"
            if not output:
                output = "(No output)"

            return output.strip()

        except subprocess.TimeoutExpired:
            return "Error: Command timed out."
        except Exception as e:
            return f"Error executing command: {e}"


class SearchWeb:
    """Searches the internet using DuckDuckGo."""

    name = "search_web"
    plan_safe = True
    description = "Searches the internet for current information. Use when you need knowledge beyond your training data."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"}
        },
        "required": ["query"],
    }

    def execute(self, context, query):
        ui.tool_action("search_web", f"'{query}'")
        backend = resolve_ddgs()
        if backend is None:
            return "Error: ddgs package not installed. Run: pip install ddgs"
        try:
            results = backend().text(query, max_results=3)
            if not results:
                return "No results found."

            formatted = []
            for r in results:
                formatted.append(f"Title: {r['title']}\nURL: {r['href']}\nSummary: {r['body']}\n")

            return "\n".join(formatted)
        except Exception as e:
            return f"Error searching web: {e}"


# --- Tool Helpers ---

def resolve_ddgs():
    """The DuckDuckGo backend, honouring an override on the host module.

    Tests and embedders swap the search backend by setting `nanocode.DDGS`
    (e.g. monkeypatch); otherwise this module's own import is used.
    """
    global DDGS
    host = sys.modules.get("nanocode")
    if host is not None and getattr(host, "DDGS", None) is not None:
        DDGS = host.DDGS
    return DDGS


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

tools = [ReadFile(), WritePlan(), SaveMemory(), ListFiles(), SearchCodebase(), SearchWeb(),
         WriteFile(), EditFile(), RunCommand()]
