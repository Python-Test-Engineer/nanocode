# Nanocode: Build Your Own AI Coding Agent

This is the companion code repository for [**Build Your Own Coding Agent**](https://buildyourowncodingagent.com) — a book that teaches you how to build an autonomous AI coding agent from scratch using pure Python.

No LangChain. No vector databases. No "orchestration frameworks." Just `requests`, `subprocess`, and code you can debug with `print()`.

**This repository is an educational refactor of that code.** The chapters, their order and their ideas are the book's; the structure is not. Every chapter's single `nanocode.py` has been split into small, named pieces, and the console output was rebuilt on [Rich](https://rich.readthedocs.io). It exists to be read alongside the book, to be taken apart in a workshop, and to make the seams of an agent visible. The book's original file is kept in every chapter as `nanocode_copy.py`, so you can diff the two and see exactly what moved. See [REFACTOR.md](REFACTOR.md) for the full map and the list of deliberate deviations.

## Read the book

There is a written walkthrough for every chapter, built from the code: each one
explains the new idea, shows the annotated snippet, traces a real run frame by
frame, and ends with exercises and self-check questions.

- **[EXPLAINER.md](EXPLAINER.md)** — the combined book (all 15 chapters, plus
  an architecture summary, glossary and `book.html` conversion notes)
- `chNN/EXPLAINER_chNN.md` — the same chapter on its own
- **[book.html](book.html)** — the same book as a two-pane web page: contents and
  filter on the left, text on the right, with scroll-spy, copy buttons, a reading
  progress bar, dark mode and print styles. Styling follows
  `anthropic-ui.css` (warm paper, terracotta accent, serif headings) but the file
  is self-contained, so it opens straight from disk.

Rebuild after editing any chapter:

```bash
uv run python build_explainer.py   # chapter files -> EXPLAINER.md
uv run python build_book.py        # EXPLAINER.md -> book.html
```

### Restyling book.html

The look of `book.html` comes from **[book_theme.toml](book_theme.toml)**: font
stacks, the two font-size bases every other size is derived from, line heights,
sidebar and reading-column widths, plus every colour in both schemes. Edit a
value and rebuild — nothing is hard-coded in the template any more:

```bash
uv run python build_book.py                          # uses book_theme.toml
uv run python build_book.py --theme other.toml --out other.html
```

`book.html` also carries a live "Aa" panel (bottom right): sliders for type and
layout, swatches for both colour schemes, a light/dark/auto switch. Changes
apply instantly and are remembered in `localStorage` for that build; "Reset"
restores the config, and "Copy TOML" puts the current settings on the clipboard
so you can paste them over `book_theme.toml`. Rebuilding with a changed config
starts from the new config (the saved state is keyed by a hash of it).

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

`ui.py` and `ui.json` are identical in every chapter except chapter 15, which adds `[subN]` labels and a per-subagent colour palette; `llm.py` and `tools.py` grow chapter by chapter with only the providers and tools that chapter has introduced.

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

They are visible while the agent runs — one coloured line per event, on by default, so the loop reads like a transcript:

```
[openrouter:act] ❯   ⟡ hook:turn_start  "Create note.txt containing the word hello…"
  ⟡ hook:before_think  1 message(s) queued
  ↑ Thinking...
  ⟡ hook:after_think  text 43 chars · wants write_file
  → Writing note.txt
  ⟡ hook:tool_call  write_file(path=note.txt, content=hello) → 43 chars back
  ⟡ hook:before_think  3 message(s) queued
  ⟡ hook:after_think  wants read_file · reasoning
  💭 Now read it back.
  → Reading note.txt
  ⟡ hook:tool_call  read_file(path=note.txt) → 10 chars back
  ⟡ hook:turn_end  answer 154 chars
```

Colours come from `ui.json` (`hook.<event>`), so `hook:tool_call` and `tool_call` can be re-themed independently of the tool lines. `NANOCODE_HOOKS=0` hides the lines; the events still fire, so your own handlers and `NANOCODE_TRACE` keep working.

Hooks observe; they never steer. Return values are ignored, and a hook that raises is reported and skipped, so a broken listener cannot break a turn. A JSONL tracer is built in:

```bash
NANOCODE_TRACE=1 uv run ch09/nanocode.py --act    # appends to .nanocode/trace.jsonl
```

Hooks arrive with the first brain (`ch03/`) and are present through `ch14/`; `hooks.py` is identical in each of those chapters up to chapter 14. Chapter 13 (`ch13/`) adds a sixth event, `session_start`, and a new observer on the same seam: `sounds.py`, which plays a Windows sound per hook. Chapter 14 (`ch14/`) adds a seventh, `sandbox_denied`, and a second observer: `sandbox.py`, which refuses writes outside the configured folders, prints **FORBIDDEN** and plays the Windows warning sound. Chapter 15 (`ch15/`) adds `subagent_start` and `subagent_end`, two tools that delegate to a nested agent (`run_subagent`, `run_subagents`), and `workflows.py`: fan-out, pipeline, map-reduce and a critic loop over one `spawn(task)` verb.

### 4. OpenRouter first

The book's chapter 3 introduces Claude. Here the first brain speaks OpenRouter's OpenAI-compatible dialect, because one key then drives the whole workshop:

```
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL="deepseek-v4.1-flash-1017"
NANOCODE_BRAIN="openrouter"
```

Claude, DeepSeek and Ollama are still there — `NANOCODE_BRAIN=claude|deepseek|ollama`, or `/switch` at runtime to cycle brains mid-conversation. Conversation history is stored in one canonical shape (Anthropic content blocks) and translated at the provider edge, so switching providers does not replay history in the wrong dialect.

### 5. Comments written for students

Every file opens with a docstring that says what it is for, what to look at and
which invariant it protects; non-obvious lines carry a `why` comment rather than
a restatement of the code. Examples: why `raw_content` is stored instead of the
reply text, why tool results travel as a *user* message, why `dirs[:] = ...` must
be an in-place edit, why Rich needs `legacy_windows=False` on Windows, why a hook
that raises is swallowed.

Roughly a third of every file is teaching text (docstrings plus comments), and
the annotated versions are the same files you run — there is no separate
"teaching copy" to drift out of sync.

### 6. The book's tests, unmodified

Every chapter still passes its own `test_nanocode.py` — 384 tests in total (ch13 adds 11 for sound, ch14 adds 29 for the sandbox and bounded reads, ch15 adds 30 for subagents, colours and the workflow patterns), with one adapted ch04 test (documented in REFACTOR.md). Each `nanocode.py` re-exports the module-level names its tests import, which is why the split could be verified rather than assumed.

## What You'll Build

**Nanocode** is a terminal-based AI coding agent that can:

- Read, write, and edit files in your codebase
- Execute shell commands and iterate on errors
- Search code across your project
- Remember context across sessions
- Search the web for current information
- Delegate work to subagents — fan-out, pipeline, map-reduce or a critic loop
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
| `ch13/` | Sound — hear the hooks on Windows | `sounds.py`, `sounds.json`, `session_start` event |
| `ch14/` | Sandbox — ACT mode writes only where allowed | `sandbox.py`, `sandbox.json`, `sandbox_denied` event |
| `ch15/` | Subagents — one agent asks another | `run_subagent`/`run_subagents`, `workflows.py`, offline demo |
| `appendix/` | Streaming — real-time output with extended thinking | (book file, not yet ported) |

## Quick Start

Everything in this repo runs through [uv](https://docs.astral.sh/uv/): it manages
the Python interpreter, the `.venv` and the locked dependencies, so you never
activate anything or `pip install` by hand.

### 1. Install uv

| Platform | Command |
|---|---|
| macOS / Linux | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Windows (PowerShell) | `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| Windows (WinGet) | `winget install --id=astral-sh.uv -e` |
| macOS (Homebrew) | `brew install uv` |
| any platform with pipx | `pipx install uv` |

All the options — installers, version pinning, upgrading, uninstalling — are in
the **[uv installation docs](https://docs.astral.sh/uv/getting-started/installation/)**.

Check it worked:

```bash
uv --version       # this repo was built with uv 0.9.x; any recent uv is fine
```

### 2. Get the code and dependencies

```bash
git clone <this-repo>
cd build-your-own-coding-agent-main

# Creates .venv and installs everything from pyproject.toml + uv.lock.
# uv also fetches a suitable Python (3.12+) if you do not have one.
uv sync
```

### 3. Point it at a model

Create `.env` in the repo root:

```
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL="deepseek-v4.1-flash-1017"
NANOCODE_BRAIN="openrouter"
```

### 4. Run a chapter

```bash
uv run ch01/nanocode.py     # no API key needed
uv run ch03/nanocode.py     # first brain
uv run ch12/nanocode.py --act
```

## Running Examples

`uv run` uses the project environment automatically — no activation, no `python`
path juggling:

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

# Chapter 15: subagents and the four workflow patterns (offline, no key needed)
uv run python ch15/demo_workflows.py
uv run python ch15/demo_workflows.py --list
```

Tests (no API key needed):

```bash
uv run pytest                      # all fourteen chapter suites, one process (384 tests)
uv run pytest ch09                 # one chapter
uv run python run_all_tests.py     # one pytest process per chapter (isolation view)
```

## Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/) — see Quick Start;
  it supplies the Python 3.12+ interpreter and the locked dependencies
- `rich`, `requests`, `python-dotenv`, `ddgs` and `pytest`, all installed by `uv sync`
- An API key for the brain you use. This fork defaults to OpenRouter:
  `OPENROUTER_API_KEY` + `OPENROUTER_MODEL` in `.env`, with
  `NANOCODE_BRAIN=openrouter`
- Optional: `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, or Ollama for local models
  (`NANOCODE_BRAIN=claude|deepseek|ollama`, or `/switch` at runtime)

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
