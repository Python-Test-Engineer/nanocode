"""llm.py - Chapter 3: the first Brain.

One provider, one job: turn a conversation into a Thought. No retries, no
tools, no second provider yet - those arrive in chapters 4 and 5.

The book uses Claude here; this workshop uses OpenRouter so the same key works
all the way to the capstone. OpenRouter speaks the OpenAI chat-completions
dialect; because this chapter only sends plain text messages there is nothing
to translate yet.
"""

import os

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "deepseek-v4.1-flash-1017"
DEFAULT_URL = "https://openrouter.ai/api/v1/chat/completions"


# --- Brain Response Types ---

class ToolCall:
    """A tool invocation request from the brain."""

    def __init__(self, id, name, args):
        self.id = id
        self.name = name
        self.args = args  # dict


class Thought:
    """Standardized response from any Brain."""

    def __init__(self, text=None, tool_calls=None, thinking=None):
        self.text = text  # str or None
        self.tool_calls = tool_calls or []  # list of ToolCall
        self.thinking = thinking  # str or None


# --- The Brain ---

class OpenRouter:
    """OpenRouter (OpenAI-compatible) - the brain of our agent."""

    def __init__(self):
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not found in .env")
        self.model = os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
        self.url = os.getenv("OPENROUTER_URL", DEFAULT_URL)

    def think(self, conversation):
        """Send the conversation, return a Thought."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Title": "Nanocode",
        }
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": conversation,
        }

        response = requests.post(self.url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        return self._parse_response(response.json()["choices"][0]["message"])

    def _parse_response(self, message):
        """Convert an OpenAI-style message to a Thought."""
        text = message.get("content")
        if isinstance(text, list):  # some providers return content parts
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))

        return Thought(
            text=text or None,
            tool_calls=[],  # tools arrive in chapter 5
            thinking=message.get("reasoning") or message.get("reasoning_content"),
        )


# Available brains
BRAINS = {
    "openrouter": OpenRouter,
}
