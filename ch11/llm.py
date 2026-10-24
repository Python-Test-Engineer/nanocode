"""llm.py - Chapter 11: web search (and the finished brain layer).

The brains are done here: OpenRouter, Claude, DeepSeek, Ollama. The chapter's
new code lives in tools.py (search_web); this file is unchanged from chapter 10
except for the docstring, which is exactly what "the brain layer is finished"
looks like.
"""

import json
import os
import time

import requests
from dotenv import load_dotenv

import ui

load_dotenv()

DEFAULT_OPENROUTER_MODEL = "deepseek-v4.1-flash-1017"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


# --- HTTP Helpers ---

def request_with_retry(url, headers, payload, max_retries=10, timeout=120):
    """POST with retry on rate limit (429), server errors (5xx), network failures.

    Three cases, deliberately treated differently:
      * the connection itself failed  -> exponential backoff, try again
      * 429 or 5xx                    -> the server is busy; honour Retry-After
                                         when it sends one, else back off
      * any other 4xx                 -> our request is wrong; retrying cannot
                                         help, so raise with the provider's own
                                         message
    Backoff is 2**attempt seconds: 1, 2, 4, 8 ... which is why max_retries is
    generous - the total wait is what protects you, not the count.
    """
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)
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
    """Pull the human-readable error out of whatever shape the provider used.

    Providers disagree ({"error": {"message": ...}} vs {"error": "..."} vs plain
    text), and a rate limit that reports "[object Object]" helps nobody.
    """
    try:
        data = response.json()
    except ValueError:
        return response.text
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return error.get("message") or json.dumps(error)
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

    def __repr__(self):
        return f"ToolCall({self.name}, {self.args})"


class Thought:
    """Standardized response from any Brain.

    Four fields, each with a job:
      text         what to show the user (may be None on a tool-calling turn)
      tool_calls   what the agent should run next (empty list = we are done)
      raw_content  the provider's own blocks, appended to history verbatim, so
                   the next request sees exactly what the model said - including
                   thinking blocks and tool_use ids. Never rebuild this by hand.
      thinking     reasoning to peek at in the UI; never sent back to the model
    """

    def __init__(self, text=None, tool_calls=None, raw_content=None, thinking=None):
        self.text = text  # str or None
        self.tool_calls = tool_calls or []  # list of ToolCall
        self.raw_content = raw_content  # content blocks, for message history
        self.thinking = thinking  # str or None


# --- Brain Interface ---

class Brain:
    """Base class for LLM providers."""

    context_limit = 200_000  # Subclasses override as needed
    last_input_tokens = 0    # Updated after each think() call

    def __init__(self, memory=None, tools=None):
        self.memory = memory
        self.tools = tools or []
        self.system = None
        self.model = ""
        self.url = ""

    def think(self, conversation):
        """Process conversation, return Thought."""
        raise NotImplementedError

    def _post(self, headers, payload):
        """Send the payload, return parsed JSON."""
        response = request_with_retry(self.url, headers, payload)
        data = response.json()
        self.last_input_tokens = (data.get("usage") or {}).get("input_tokens", 0)
        return data

    def _parse_response(self, content):
        """Convert Anthropic content blocks to a Thought.

        A reply is a list of blocks, and one reply can hold several at once
        (reasoning + text + two tool calls). We keep them all: text is joined,
        tool_use becomes ToolCall, thinking is kept aside for the UI.
        """
        text_parts = []
        tool_calls = []
        thinking = None

        for block in content or []:
            if block["type"] == "thinking":
                thinking = block.get("thinking")
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
            raw_content=content,
            thinking=thinking,
        )


# --- Anthropic-shaped providers ---

class Claude(Brain):
    """Claude API - the brain the book starts with."""

    def __init__(self, memory=None, tools=None):
        super().__init__(memory, tools)
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in .env")
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        self.url = "https://api.anthropic.com/v1/messages"

    def think(self, conversation):
        # Claude's native API: key in a header, version pinned, system prompt as a
        # top-level field. budget_tokens is how much of max_tokens may be spent
        # thinking before the answer starts, and it must be smaller than
        # max_tokens.
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
        if self.system:
            payload["system"] = self.system
        if self.tools:
            payload["tools"] = self.tools

        data = self._post(headers, payload)
        return self._parse_response(data["content"])


class DeepSeek(Brain):
    """DeepSeek API (Anthropic-compatible, with tool support)."""

    context_limit = 128_000

    def __init__(self, memory=None, tools=None):
        super().__init__(memory, tools)
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
        payload = {
            "model": self.model,
            "max_tokens": 8192,
            "messages": conversation,
        }
        if self.system:
            payload["system"] = self.system
        if self.tools:
            payload["tools"] = self.tools

        data = self._post(headers, payload)
        return self._parse_response(data["content"])


class Ollama(Brain):
    """Ollama local model (Anthropic-compatible API, with tool support)."""

    context_limit = 32_000

    def __init__(self, memory=None, tools=None):
        super().__init__(memory, tools)
        self.model = os.getenv("OLLAMA_MODEL", "qwen3-coder:30b")
        self.url = "http://localhost:11434/v1/messages"
        self._detect_context_limit()

    def _detect_context_limit(self):
        """Query Ollama for the model's context window size."""
        try:
            response = requests.post(
                "http://localhost:11434/api/show",
                json={"model": self.model},
                timeout=0.5,  # fail fast: the probe is optional
            )
            model_info = response.json().get("model_info", {})
            for key, value in model_info.items():
                if key.endswith(".context_length"):
                    self.context_limit = value
                    return
        except Exception:
            pass  # Keep default

    def think(self, conversation):
        headers = {
            "x-api-key": "ollama",  # Required but not validated
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": 8192,
            "messages": conversation,
        }
        if self.system:
            payload["system"] = self.system
        if self.tools:
            payload["tools"] = self.tools

        data = self._post(headers, payload)
        return self._parse_response(data["content"])


# --- OpenRouter (OpenAI-compatible) ---

class OpenRouter(Brain):
    """OpenRouter: one key, any model, OpenAI chat-completions dialect.

    Nanocode stores history in Anthropic block form, so this class translates
    on the way out (to_openai_messages / to_openai_tools) and back (the
    response is re-shaped into text / tool_use blocks).
    """

    context_limit = int(os.getenv("OPENROUTER_CONTEXT_LIMIT", "128000"))

    def __init__(self, memory=None, tools=None):
        super().__init__(memory, tools)
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not found in .env")
        self.model = os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL)
        self.url = os.getenv("OPENROUTER_URL", OPENROUTER_URL)
        self.max_tokens = int(os.getenv("OPENROUTER_MAX_TOKENS", "8192"))

    def think(self, conversation):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Title": "Nanocode",
        }
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": to_openai_messages(conversation, self.system),
        }
        if self.tools:
            # "auto" lets the model decide whether to call a tool or just answer;
            # omitting it would still mostly work, but some OpenAI-compatible
            # backends treat a missing tool_choice differently.
            payload["tools"] = to_openai_tools(self.tools)
            payload["tool_choice"] = "auto"

        response = request_with_retry(self.url, headers, payload)
        data = response.json()
        if "choices" not in data:
            raise Exception(f"OpenRouter error: {api_error_message(response)}")

        self.last_input_tokens = int((data.get("usage") or {}).get("prompt_tokens") or 0)
        return self._parse_openai(data["choices"][0].get("message") or {})

    def _parse_openai(self, message):
        """OpenAI message -> Anthropic-shaped blocks + Thought."""
        # Content is usually a string, but the OpenAI schema also allows a list
        # of parts ({"type": "text", "text": ...}) - some providers use it.
        text = message.get("content")
        if isinstance(text, list):  # some providers return content parts
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))

        blocks = []
        if text:
            blocks.append({"type": "text", "text": text})

        tool_calls = []
        for i, call in enumerate(message.get("tool_calls") or []):
            function = call.get("function") or {}
            # OpenAI sends arguments as a JSON *string* produced by the model, so
            # it can be empty or malformed. Never let that crash the turn: hand
            # the tool {} and let it report the missing argument itself.
            raw_args = function.get("arguments")
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args) if raw_args.strip() else {}
                except json.JSONDecodeError:
                    args = {}
            else:
                args = raw_args or {}

            # Some providers omit the call id; the agent needs *an* id to match
            # the result back to the request, so synthesise a stable one.
            call_id = call.get("id") or f"call_{i}"
            name = function.get("name") or ""
            blocks.append({"type": "tool_use", "id": call_id, "name": name, "input": args})
            tool_calls.append(ToolCall(id=call_id, name=name, args=args))

        thinking = message.get("reasoning") or message.get("reasoning_content")
        return Thought(
            text=text or None,
            tool_calls=tool_calls,
            raw_content=blocks,
            thinking=thinking,
        )


# --- Dialect translation (Anthropic blocks <-> OpenAI messages) ---

def to_openai_messages(conversation, system=None):
    """Convert Nanocode's Anthropic-style history to OpenAI chat messages.

    The two dialects disagree about three things, and this function is the whole
    of the difference:

    1. the system prompt is a message with role "system", not a top-level field
    2. a tool result is its own message with role "tool" + tool_call_id, not a
       content block inside a user message
    3. tool arguments are a JSON *string* on an assistant message, not an object

    Everything else passes through unchanged, which is why /switch mid-turn is
    safe: history is stored once and translated per provider at send time.
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})

    for message in conversation:
        role = message.get("role", "user")
        content = message.get("content")

        # Plain text turns pass straight through.
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
            continue

        blocks = content or []
        if role == "assistant":
            # One assistant message can carry both prose and tool calls. OpenAI
            # wants content=None (not "") when there is only a tool call.
            text_parts = []
            calls = []
            for block in blocks:
                block_type = block.get("type")
                if block_type == "text":
                    text_parts.append(block.get("text", ""))
                elif block_type == "tool_use":
                    calls.append({
                        "id": block.get("id"),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(block.get("input") or {}),
                        },
                    })
            entry = {"role": "assistant", "content": "\n".join(text_parts) or None}
            if calls:
                entry["tool_calls"] = calls
            messages.append(entry)
        else:
            # A user turn carrying tool results: OpenAI wants role="tool" per result.
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    messages.append({
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id"),
                        "content": str(block.get("content", "")),
                    })
            texts = [b.get("text", "") for b in blocks
                     if isinstance(b, dict) and b.get("type") == "text"]
            if texts:
                messages.append({"role": "user", "content": "\n".join(texts)})

    return messages


def to_openai_tools(definitions):
    """Convert Nanocode tool definitions (name/description/input_schema) to OpenAI tools.

    Same information, one extra wrapper: {"type": "function", "function": {...}}.
    The schema itself is untouched - both dialects use JSON Schema.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": d["name"],
                "description": d.get("description", ""),
                "parameters": d.get("input_schema") or {"type": "object", "properties": {}},
            },
        }
        for d in definitions
    ]


# The registry /switch cycles through and main() looks up by name. Order is the
# cycle order, so put the provider you want as the default first.
# Adding a brain = write the class above, add one line here.
BRAINS = {
    "openrouter": OpenRouter,
    "claude": Claude,
    "deepseek": DeepSeek,
    "ollama": Ollama,
}
