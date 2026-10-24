"""api_check.py - Chapter 2: first contact with the model.

The book's version (kept untouched as test_api.py) fires one raw request at
Claude and prints the JSON. Same idea here, two changes for this workshop:

    * it talks to OpenRouter (OpenAI chat-completions dialect)
    * it prints through ui.py, so the JSON is syntax-highlighted and the
      status line is coloured

Still no agent, no loop, no abstraction - chapter 3 builds the first Brain.

Run:  uv run ch02/api_check.py
"""

import json
import os
import sys

import requests
from dotenv import load_dotenv
from rich.syntax import Syntax

import ui

load_dotenv()

URL = "https://openrouter.ai/api/v1/chat/completions"


def main():
    ui.configure()

    # 1. Load the vault
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        ui.error("OPENROUTER_API_KEY not found in .env")
        return 1

    model = os.getenv("OPENROUTER_MODEL", "deepseek-v4.1-flash-1017")

    # 2. Define the target
    url = os.getenv("OPENROUTER_URL", URL)

    # 3. Authenticate
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "Nanocode",
    }

    # 4. Construct the payload
    payload = {
        "model": model,
        "max_tokens": 256,
        "messages": [
            {"role": "user", "content": "Hello, are you ready to code?"}
        ],
    }

    ui.banner(version="v0.2 (first contact)", model=model, hint=f"POST {url}")
    ui.info("Sending request...")

    # 5. Fire!
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
    except requests.exceptions.RequestException as e:
        ui.error(f"Network error: {e}")
        return 1

    # 6. Inspect the raw result
    ui.info(f"Status: {response.status_code}")

    if response.status_code != 200:
        ui.error(response.text)
        return 1

    data = response.json()

    # The one field that matters for now: what the model said back.
    message = data["choices"][0]["message"]
    ui.success(message.get("content") or "(no content)")

    # ...and everything else, for the curious.
    ui.print()
    ui.print(Syntax(json.dumps(data, indent=2), "json", theme="ansi_dark", line_numbers=False))
    ui.print()

    usage = data.get("usage") or {}
    ui.tokens(usage.get("prompt_tokens", 0), usage.get("total_tokens", 0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
