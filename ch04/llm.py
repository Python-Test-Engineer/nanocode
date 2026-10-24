"""llm.py - Chapter 4: more than one brain.

Chapter 3 hard-coded one provider into the agent. Now the agent talks to a
`Brain` - an interface with a single method, `think()` - and each provider fills
it in however it likes. Swapping brains becomes swapping objects.

Two dialects live here:
    OpenRouter   OpenAI chat-completions (default; one key, any model)
    Claude       Anthropic /v1/messages
    DeepSeek     Anthropic-compatible endpoint

No tools yet, so the conversation is plain {"role", "content"} text and both
dialects understand it as-is. Chapter 5 adds tool calls, and with them the
translation layer.

THE THREE JOBS OF THIS FILE
  1. describe what a brain must do (class Brain)
  2. implement it once per provider (Claude, DeepSeek, OpenRouter)
  3. keep a registry the agent can switch between (BRAINS)

Notice what is NOT here: any knowledge of tools, the agent loop, or the console.
A provider is a request builder and a response parser, nothing else.
"""

import os
import time

import requests
from dotenv import load_dotenv

import ui

load_dotenv()

DEFAULT_MODEL = "deepseek-v4.1-flash-1017"
DEFAULT_URL = "https://openrouter.ai/api/v1/chat/completions"


# --- HTTP Helpers ---

def request_with_retry(url, headers, payload, max_retries=10):
    """Make HTTP POST with retry on rate limit (429), server errors (5xx), and network failures.

    New in this chapter: chapter 3 called requests.post() directly, so a rate
    limit killed the turn. Here a transient failure is waited out (1, 2, 4, 8 ...
    seconds, or the provider's Retry-After when it sends one), while a 4xx that
    means "your request is wrong" is raised immediately - retrying cannot help.
    """
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
        except requests.exceptions.RequestException as e:
            wait_time = 2 ** attempt
            ui.warning(f"Network error: {e}. Retrying in {wait_time}s...")
            time.sleep(wait_time)
            continue

        if response.status_code == 429 or response.status_code >= 500:
            retry_after = response.headers.get("retry-after")
            try:
                wait_time = int(retry_after) if retry_after else 2 ** attempt
            except (ValueError, TypeError):
                wait_time = 2 ** attempt
            ui.warning(f"Error {response.status_code}. Retrying in {wait_time}s...")
            time.sleep(wait_time)
            continue

        if response.status_code >= 400:
            raise Exception(f"API error ({response.status_code}): {api_error_message(response)}")

        return response

    raise Exception(f"Request failed after {max_retries} retries")


def api_error_message(response):
    """Pull the human-readable error out of whatever shape the provider used."""
    try:
        data = response.json()
    except ValueError:
        return response.text
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return error.get("message") or str(error)
    if error:
        return str(error)
    return response.text


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


# --- Brain Interface ---

class Brain:
    """Base class for LLM providers.

    Two methods matter: think() (which every provider must implement) and
    _parse_response() (shared by the Anthropic-shaped providers, which all return
    content blocks). `context_limit` and `last_input_tokens` are not used until
    chapter 9, when the agent starts compacting.
    """

    def think(self, conversation):
        """Process conversation, return Thought."""
        raise NotImplementedError

    def _parse_response(self, content):
        """Convert Anthropic content blocks to a Thought."""
        text_parts = []
        tool_calls = []
        thinking = None

        # A reply can be several blocks at once: reasoning, prose, and (from
        # chapter 5) tool calls. All of them become one Thought.
        for block in content:
            if block["type"] == "thinking":
                thinking = block["thinking"]
            elif block["type"] == "text":
                text_parts.append(block["text"])
            elif block["type"] == "tool_use":
                tool_calls.append(ToolCall(
                    id=block["id"],
                    name=block["name"],
                    args=block["input"],
                ))

        return Thought(
            text="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            thinking=thinking,
        )


# --- Anthropic-shaped providers ---

class Claude(Brain):
    """Claude API implementation."""

    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in .env")
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        self.url = "https://api.anthropic.com/v1/messages"

    def think(self, conversation):
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": 16000,
            "thinking": {"type": "enabled", "budget_tokens": 10000},
            "messages": conversation,
        }

        # Anthropic returns `content` as a list of blocks; _parse_response turns
        # them into a Thought, so the agent never sees this shape.
        response = request_with_retry(self.url, headers, payload)
        return self._parse_response(response.json()["content"])


class DeepSeek(Brain):
    """DeepSeek API (Anthropic-compatible)."""

    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY not found in .env")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        self.url = "https://api.deepseek.com/anthropic/v1/messages"

    def think(self, conversation):
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        # DeepSeek's Anthropic-compatible endpoint: same request shape as Claude,
        # different base URL and no thinking budget.
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": conversation,
        }

        response = request_with_retry(self.url, headers, payload)
        return self._parse_response(response.json()["content"])


# --- OpenRouter (OpenAI-compatible) ---

class OpenRouter(Brain):
    """OpenRouter: one key, any model, OpenAI chat-completions dialect."""

    def __init__(self):
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not found in .env")
        self.model = os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
        self.url = os.getenv("OPENROUTER_URL", DEFAULT_URL)

    def think(self, conversation):
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

        # OpenAI dialect: the reply is choices[0].message, and `content` is a
        # string rather than a list of blocks - hence the separate parser below.
        response = request_with_retry(self.url, headers, payload)
        return self._parse_response(response.json()["choices"][0]["message"])

    def _parse_response(self, message):
        """Convert an OpenAI-style message to a Thought."""
        text = message.get("content")
        if isinstance(text, list):  # some providers return content parts
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))

        return Thought(
            text=text or None,
            tool_calls=[],
            thinking=message.get("reasoning") or message.get("reasoning_content"),
        )


# Available brains
BRAINS = {
    "openrouter": OpenRouter,
    "claude": Claude,
    "deepseek": DeepSeek,
}
