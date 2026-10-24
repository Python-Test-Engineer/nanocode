# Nanocode: Build Your Own AI Coding Agent

This is the companion code repository for [**Build Your Own Coding Agent**](https://buildyourowncodingagent.com) — a book that teaches you how to build an autonomous AI coding agent from scratch using pure Python.

No LangChain. No vector databases. No "orchestration frameworks." Just `requests`, `subprocess`, and code you can debug with `print()`.

**This repository is an educational refactor of that code.** The chapters, their order and their ideas are the book's; the structure is not. Every chapter's single `nanocode.py` has been split into small, named pieces, and the console output was rebuilt on [Rich](https://rich.readthedocs.io). It exists to be read alongside the book, to be taken apart in a workshop, and to make the seams of an agent visible. The book's original file is kept in every chapter as `nanocode_copy.py`, so you can diff the two and see exactly what moved. See [REFACTOR.md](REFACTOR.md) for the full map and the list of deliberate deviations.

## What the refactor adds

### 1. Abstractions instead of one long file

Each chapter keeps the book's behaviour but separates the four things an agent is actually made of:

| File | Responsibility | Knows about |
|---|---|---|
| `nanocode.py` | `Memory`, `Agent` (the loop), `main()` | everything |
| `llm.py` | Brains: one class per provider, all returning a `Thought` | HTTP, `ui` |
| `tools.py` | What the agent can *do*: one class per tool, `execute(...) -> str` | `ui` |
| `ui.py` + `ui.json` | Everything a human sees: banner, prompt, thinking, tool lines, answers | `rich` |
| `hooks.py` | Lifecycle events (see below) | `ui` |

The dependency arrows only point one way: `ui.py` knows nothing about LLMs or tools; `llm.py` knows nothing about tools; `tools.py` knows nothing about the agent. That is what makes each chapter's new idea small enough to hold in your head, and what lets you replace any one layer without touching the others.

`ui.py` and `ui.json` are identical in every chapter; `llm.py` and `tools.py` grow chapter by chapter with only the providers and tools that chapter has introduced.

### 2. Rich UI, with every colour in JSON

The book prints with `print()`. This fork prints with Rich — a styled prompt that shows the current brain and mode, dimmed reasoning lines, one coloured line per tool call, Markdown-rendered answers, and a `/help` table. Colour choices live in `ui.json`, not in Python:

```json
{ "tools": { "read_file":   { "icon": "→", "style": "cyan",          "verb": "Reading" },
             "run_command": { "icon": "→", "style": "bright_yellow", "verb": "Running" } } }
```

Edit a style, restart, done — no code changes, no rebuild. Set `NANOCODE_COLOR=1` if you need colour when piping output (Windows terminals need it; see REFACTOR.md).

### 3. Lifecycle hooks

The book's agent is a closed loop with no way in from the outside. This fork emits named events at the points worth watching, so you can instrument the agent **without editing it**:

| Event | Payload |
|---|---|
| `turn_start` | `user_input` |
| `before_think` | `messages` (how many messages are about to be sent) |
| `after_think` | `thought` (an `llm.Thought`: text, thinking, tool calls) |
| `tool_call` | `name`, `args`, `result` |
| `turn_end` | `output` |

```python
import nanocode

agent = nanocode.Agent(brain=..., tools=nanocode.tools)
agent.hooks.on("tool_call", lambda **e: print(f"{e['name']} -> {e['result'][:40]}"))

@agent.hooks.on("turn_end")
def log(output, **rest):
    print(f"answered in {len(output)} chars")
```

Hooks observe; they never steer. Return values are ignored, and a hook that raises is reported and skipped, so a broken listener cannot break a turn. A JSONL tracer is built in:

```bash
NANOCODE_TRACE=1 uv run ch09/nanocode.py --act    # appends to .nanocode/trace.jsonl
```

Hooks arrive with the first brain (`ch03/`) and are present through `ch12/`; `hooks.py` is identical in each of those chapters.

### 4. OpenRouter first

The book's chapter 3 introduces Claude. Here the first brain speaks OpenRouter's OpenAI-compatible dialect, because one key then drives the whole workshop:

```
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL="deepseek-v4.1-flash-1017"
NANOCODE_BRAIN="openrouter"
```

Claude, DeepSeek and Ollama are still there — `NANOCODE_BRAIN=claude|deepseek|ollama`, or `/switch` at runtime to cycle brains mid-conversation. Conversation history is stored in one canonical shape (Anthropic content blocks) and translated at the provider edge, so switching providers does not replay history in the wrong dialect.

### 5. The book's tests, unmodified

Every chapter still passes its own `test_nanocode.py` — 197 assertions in total, with one adapted ch04 test (documented in REFACTOR.md). Each `nanocode.py` re-exports the module-level names its tests import, which is why the split could be verified rather than assumed.

## What You'll Build

**Nanocode** is a terminal-based AI coding agent that can:

- Read, write, and edit files in your codebase
- Execute shell commands and iterate on errors
- Search code across your project
- Remember context across sessions
- Search the web for current information
- Run on OpenRouter, Claude, DeepSeek, or local models via Ollama

By the end of the book, you'll have a small Python agent that rivals commercial coding assistants — and you'll understand every line because you wrote it.

## Repository Structure

Each `chXX/` folder contains a complete, runnable snapshot of the code at the end of that chapter:

| Chapter | What You Build | Also new in that chapter |
|---------|----------------|--------------------------|
| `ch01/` | Event loop — the skeleton | Rich banner + prompt (`ui.py`, `ui.json`) |
| `ch02/` | API test — first contact with the model | `api_check.py`, JSON syntax highlighting |
| `ch03/` | Stateful chatbot — memory within a session | `llm.py`, first brain, lifecycle hooks |
| `ch04/` | Multi-provider — OpenRouter + Claude + DeepSeek | `Brain` base class, retries, `/switch` |
| `ch05/` | Tools — read and write files | `tools.py`, the agentic loop |
| `ch06/` | Persistent memory — cross-session context | `Memory`, `ToolContext`, `save_memory` |
| `ch07/` | Plan mode — safety harness | `plan_safe`, `/mode`, `/help` |
| `ch08/` | Codebase context — list and search files | `list_files`, `search_codebase` |
| `ch09/` | Feedback loop — run commands, fix errors | `edit_file`, `run_command`, compaction |
| `ch10/` | Local models — Ollama integration | `Ollama` brain |
| `ch11/` | Web search — DuckDuckGo tool | `search_web` |
| `ch12/` | Capstone — build a game with AI | — |
| `appendix/` | Streaming — real-time output with extended thinking | (book file, not yet ported) |

## Quick Start

```bash
# Clone this fork
git clone <this-repo> && cd build-your-own-coding-agent-main

# Create the environment (uv is used here; pip works too)
uv venv && uv sync

# Point it at a model: create .env in the repo root
#   OPENROUTER_API_KEY=sk-or-...
#   OPENROUTER_MODEL="deepseek-v4.1-flash-1017"
#   NANOCODE_BRAIN="openrouter"
```

## Running Examples

```bash
# Chapter 1: event loop (no API key needed)
uv run ch01/nanocode.py

# Chapter 2: raw API call, no agent
uv run ch02/api_check.py

# Chapter 3+: needs the key in .env
uv run ch03/nanocode.py

# Chapter 7+: plan mode is the default; --act enables writes
uv run ch07/nanocode.py --act

# Chapter 10+: local models
NANOCODE_BRAIN=ollama uv run ch10/nanocode.py

# Capstone
uv run ch12/nanocode.py --act

# Trace every lifecycle event to .nanocode/trace.jsonl
NANOCODE_TRACE=1 uv run ch09/nanocode.py --act
```

Tests (no API key needed):

```bash
uv run pytest                      # all eleven chapter suites, one process (197 tests)
cd ch09 && pytest                  # one chapter, the book's way
uv run python run_all_tests.py     # one pytest process per chapter (isolation view)
```

## Requirements

- Python 3.10+ (this fork's `pyproject.toml` targets 3.12+)
- An API key for the brain you use. This fork defaults to OpenRouter:
  `OPENROUTER_API_KEY` + `OPENROUTER_MODEL` in `.env`, with
  `NANOCODE_BRAIN=openrouter`
- Optional: `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, or Ollama for local models
  (`NANOCODE_BRAIN=claude|deepseek|ollama`, or `/switch` at runtime)
- `rich` for the console layer (declared in `requirements.txt` and `pyproject.toml`)

## Community Implementations

The book's reference implementation is Python, but the concepts — the loop, the tools, the brain abstraction — are language-agnostic. Community ports live in the `contrib/` directory:

| Language | Directory | Contributor |
|----------|-----------|-------------|
| *Your language here* | — | [See CONTRIBUTING.md](CONTRIBUTING.md) |

## The Book

This code accompanies the book **Build Your Own Coding Agent**, available on:

- [Leanpub](https://leanpub.com/build-your-own-coding-agent)
- [Amazon/Kindle](https://mybook.to/build-a-coding-agent)

The book follows a "Zero Magic" philosophy — every abstraction is explained with physical metaphors, and every line of code serves a purpose you'll understand. This fork keeps that spirit: the extra structure (`ui.py`, `llm.py`, `tools.py`, `hooks.py`) is small, readable, and exists so each book chapter's idea has somewhere to live.

## License

MIT License. See [LICENSE](LICENSE) for details.
