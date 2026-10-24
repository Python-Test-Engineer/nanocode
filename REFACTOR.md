# Nanocode, refactored: Rich UI + OpenRouter, chapter by chapter

Every chapter in this repo was one self-contained `nanocode.py`. Each one is now
split the same way, and every chapter still passes its own `test_chNN_nanocode.py`
unmodified (except one ch04 test, see "Deviations").

```
chNN/
  nanocode.py       Memory + Agent (the loop) + main()      <- only this changes per chapter
  llm.py            brains: OpenRouter (+ Claude, DeepSeek, Ollama) -> Thought
  tools.py          what the agent can do -> str
  ui.py             everything printed, built on Rich
  ui.json           every colour, icon and label
  nanocode_copy.py  the original book file, kept for side-by-side diffing
  ui.py / ui.json are identical in every chapter.
```

`nanocode.py` re-exports the module-level names each chapter's tests import
(`Agent`, `tools`, `BRAINS`, `ReadFile`, `DDGS`, ...), which is why the book's
tests run against the split version unchanged.

## Run

```bash
uv run ch01/nanocode.py                 # no brain yet
uv run ch03/nanocode.py                 # first brain, conversation memory
uv run ch07/nanocode.py                 # plan mode (read-only)
uv run ch07/nanocode.py --act           # act mode
uv run ch09/nanocode.py --act           # write -> run -> read traceback -> fix
uv run ch12/nanocode.py --act           # capstone
uv run ch02/api_check.py                # raw API check, no agent
```

`.env` (repo root) supplies `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`,
`NANOCODE_BRAIN`. Every chapter defaults to `NANOCODE_BRAIN=openrouter`, so the
same key drives the whole workshop. `/switch` cycles to Claude or DeepSeek when
those keys exist.

Optional env: `NANOCODE_COLOR=1` (force colour when piping output),
`NANOCODE_TIMEOUT` (shell tool, 30s), `OPENROUTER_MAX_TOKENS`,
`OPENROUTER_CONTEXT_LIMIT`, `ANTHROPIC_MODEL`, `DEEPSEEK_MODEL`, `OLLAMA_MODEL`.

## Test

```bash
uv run pytest                      # all 11 chapters, 197 tests, one process
uv run pytest ch09                 # one chapter
uv run pytest ch09/test_nanocode.py::test_run_command_executes   # one test
cd ch09 && ../../.venv/Scripts/python.exe -m pytest -q   # the book's way
uv run python run_all_tests.py     # one process per chapter (isolation view)
```

Chapter files keep the book's names, including `test_nanocode.py`, so `pytest`
from the repo root needs `conftest.py` + `--import-mode=importlib` from
`pyproject.toml`: every chapter defines modules called `nanocode`, `llm`,
`tools`, `ui` (and a test file called `test_nanocode.py`). Before a test module
is imported - and again before each test runs - the conftest puts that chapter's
directory at the front of `sys.path` and republishes the chapter's modules in
`sys.modules`. Order does not matter, and runtime string lookups
(`monkeypatch.setattr("nanocode.DDGS", ...)`) hit the right chapter.

`ch02` is excluded from `testpaths`: `test_api.py` is a script that calls the API
at import time, not a test module. The unported `appendix/` (book file) also
passes: `uv run pytest appendix` -> 13 tests.

## What each chapter contains

| Chapter | nanocode.py | llm.py | tools.py | New UI |
|---|---|---|---|---|
| ch01 | loop, echo | — | — | banner, bare prompt |
| ch02 | `api_check.py`: raw OpenRouter call | — | — | syntax-highlighted JSON |
| ch03 | + conversation history | OpenRouter only, plain-text messages | — | thinking lines |
| ch04 | + `/switch` | `Brain` base, + Claude + DeepSeek, retries | — | brain switch line |
| ch05 | + `_agentic_loop` | + `raw_content`, tool calls, dialect translation | `ReadFile`, `WriteFile` (`execute(path)`) | tool lines |
| ch06 | + `Memory` | — | + `ToolContext`, `SaveMemory`, `execute(context, ...)` | memory tool line |
| ch07 | + plan/act gating, `/mode`, `/help` | + `system` prompt | + `plan_safe`, `WritePlan` | mode switch line, help table |
| ch08 | — | — | + `ListFiles`, `SearchCodebase` | — |
| ch09 | + compaction | + token accounting | + `EditFile`, `RunCommand` | compaction notice |
| ch10 | — | + `Ollama` | — | — |
| ch11 | = ch12 (book: identical snapshots) | + `BRAINS` complete | + `SearchWeb` | — |
| ch12 | capstone | same as ch11 | same as ch11 | — |

`ui.json` is shared by all chapters; `ui.help_table(only=...)` is how a chapter
advertises only the commands it actually implements.

## Deviations from the book (deliberate)

1. **OpenRouter is the first provider, not Claude.** Chapter 3 introduces one
   brain; here it speaks OpenRouter's OpenAI dialect because that is the key in
   `.env`. Claude and DeepSeek join in chapter 4 as the book intends.
2. **ch04 `test_ch04_nanocode.py`: one test adapted.** `test_switch_command_toggles_brain_name`
   assumed exactly two providers (`claude <-> deepseek`). With three registered
   brains it now walks `BRAINS` generically and checks the cycle wraps. Same
   intent, no hard-coded pair.
3. **`Thought.raw_content` is always Anthropic block form**, even for OpenRouter.
   `llm.to_openai_messages()` translates on the way out, `_parse_openai()`
   re-shapes on the way back. This is what makes `/switch` mid-conversation safe.
4. **Commands return text as well as printing.** `/mode` and `/switch` render a
   coloured line *and* return a string (`"Switched to ACT MODE"`) because the
   book's tests assert on the return value. `Agent.output_rendered` stops `main()`
   from printing it twice.
5. **Rich colour on Windows** needs `legacy_windows=False` (set from `ui.json`),
   otherwise Rich silently emits no ANSI at all as soon as stdout is redirected.
6. **Ollama probe timeout is 0.5s**, not 2s: Windows doubles connect timeouts, so
   each `Ollama()` instantiation cost ~4s when the daemon is not running.

## Re-theming

Edit `ui.json`, restart. Keys resolve as `styles.<key>` -> `commands.<command>` ->
`tools.<tool_name>` -> `theme.<accent>`. Styles are Rich style strings
(`"bold bright_cyan"`, `"grey58 italic"`, `#ff8800`). A tool with no entry falls
back to `tools.default`.
