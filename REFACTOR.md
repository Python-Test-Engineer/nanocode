# Nanocode, refactored: Rich UI + OpenRouter, chapter by chapter

Every chapter in this repo was one self-contained `nanocode.py`. Each one is now
split the same way, and every chapter still passes its own `test_nanocode.py`
unmodified (except one ch04 test, see "Deviations").

```
chNN/
  nanocode.py       Memory + Agent (the loop) + main()      <- only this changes per chapter
  llm.py            brains: OpenRouter (+ Claude, DeepSeek, Ollama) -> Thought
  tools.py          what the agent can do -> str
  ui.py             everything printed, built on Rich
  ui.json           every colour, icon and label
  hooks.py          lifecycle events (ch03 onward; identical in every chapter)
  nanocode_copy.py  the original book file, kept for side-by-side diffing
  ui.py / ui.json / hooks.py are identical in every chapter.
```

Files are written to be read: module docstrings state the chapter's idea and what
to look at, and non-obvious lines carry a "why" comment. About a third of every
source file is teaching text.

`nanocode.py` re-exports the module-level names each chapter's tests import
(`Agent`, `tools`, `BRAINS`, `ReadFile`, `DDGS`, ...), which is why the book's
tests run against the split version unchanged.

Repo root:

```
conftest.py       lets one `pytest` run cover all 14 tested chapters (see "Test")
run_all_tests.py  the other view: pytest once per chapter
pyproject.toml    deps + [tool.pytest.ini_options]
REFACTOR.md       this file
```

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
uv run pytest                      # all 14 tested chapters, 380 tests, one process
uv run pytest ch09                 # one chapter
uv run pytest ch09/test_nanocode.py::test_run_command_executes   # one test
cd ch09 && uv run pytest -q        # the book's way (pytest inside the chapter)
uv run python run_all_tests.py     # one process per chapter (isolation view)
```

Two commands, two purposes:

| Command | What it does | When |
|---|---|---|
| `uv run pytest` | all 14 tested chapters in one process, `-k`, single test ids, IDE test panel | everyday |
| `uv run python run_all_tests.py` | pytest once per chapter, in its own directory | when a failure appears only in the combined run |

Chapter files keep the book's names - `nanocode.py`, `test_nanocode.py` - so a
single pytest process has two collisions to survive:

1. **fourteen `test_nanocode.py`** -> handled by `addopts = "--import-mode=importlib"`
   in `pyproject.toml` (the default mode imports test modules by basename and errors).
2. **fourteen `nanocode` (and `llm`/`tools`/`ui`/`hooks`/`sounds`/`sandbox`/`workflows`) modules** -> handled by
   `conftest.py`: before a test module is imported, and again before each test
   runs, it puts that chapter's directory at the front of `sys.path` and
   republishes the chapter's modules in `sys.modules`.

Order does not matter (`uv run pytest ch12 ch11 ch01` is fine), and runtime
string lookups - `monkeypatch.setattr("nanocode.DDGS", ...)`, `import nanocode`
inside a test - hit the right chapter.

**Escape hatch.** If you would rather have no machinery at all, delete
`conftest.py` and the `[tool.pytest.ini_options]` block, then use only
`uv run python run_all_tests.py`. You lose one-command runs (bare `pytest` at the
root errors on the duplicate names) and the IDE panel; you gain zero sys.path /
sys.modules juggling in a teaching repo. Verified: with the conftest removed,
10 chapters fail collection.

`ch02` is excluded from `testpaths`: `test_api.py` is a script that calls the API
at import time, not a test module. The unported `appendix/` (book file) also
passes: `uv run pytest appendix` -> 13 tests.

## What each chapter contains

| Chapter | nanocode.py | llm.py | tools.py | New UI |
|---|---|---|---|---|
| ch01 | loop, echo | — | — | banner, bare prompt |
| ch02 | `api_check.py`: raw OpenRouter call | — | — | syntax-highlighted JSON |
| ch03 | + conversation history, hooks | OpenRouter only, plain-text messages | — | thinking lines |
| ch04 | + `/switch` | `Brain` base, + Claude + DeepSeek, retries | — | brain switch line |
| ch05 | + `_agentic_loop` | + `raw_content`, tool calls, dialect translation | `ReadFile`, `WriteFile` (`execute(path)`) | tool lines |
| ch06 | + `Memory` | — | + `ToolContext`, `SaveMemory`, `execute(context, ...)` | memory tool line |
| ch07 | + plan/act gating, `/mode`, `/help` | + `system` prompt | + `plan_safe`, `WritePlan` | mode switch line, help table |
| ch08 | — | — | + `ListFiles`, `SearchCodebase` | — |
| ch09 | + compaction | + token accounting | + `EditFile`, `RunCommand` | compaction notice |
| ch10 | — | + `Ollama` | — | — |
| ch11 | = ch12 (book: identical snapshots) | + `BRAINS` complete | + `SearchWeb` | — |
| ch12 | capstone | same as ch11 | same as ch11 | — |
| ch13 | = ch12 | same as ch11 | same as ch11 | `sounds.py` + `sounds.json`; `session_start` hook line |
| ch14 | = ch13 | same as ch11 | + `ToolContext.guard()`; four write tools call it | `sandbox.py` + `sandbox.json`; `FORBIDDEN` line, `sandbox_denied` hook |
| ch15 | + `_spawn_subagent`, `_spawn_many`, per-agent `max_iterations` | same as ch11 | + `RunSubagent`/`RunSubagents`; `ToolContext.spawn`/`spawn_many` | `workflows.py` + `demo_workflows.py`; `[subN]` labels, `subagent_start`/`subagent_end` hooks |

`ui.json` is shared by all chapters; `ui.help_table(only=...)` is how a chapter
advertises only the commands it actually implements.

## Deviations from the book (deliberate)

1. **OpenRouter is the first provider, not Claude.** Chapter 3 introduces one
   brain; here it speaks OpenRouter's OpenAI dialect because that is the key in
   `.env`. Claude and DeepSeek join in chapter 4 as the book intends.
2. **ch04 `test_nanocode.py`: one test adapted.** `test_switch_command_toggles_brain_name`
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
7. **`hooks.py` is not in the book at all.** It is the fork's one new subsystem:
   the agent emits `turn_start`, `before_think`, `after_think`, `tool_call` and
   `turn_end`; handlers are passive observers (return values ignored, exceptions
   reported and skipped). Wired into chapters 3-12 at the same five points, and
   `NANOCODE_TRACE=1` writes JSONL via `Hooks.trace()`. Nothing else depends on
   it - delete `hooks.py` and the five `emit` calls per chapter and the agent
   behaves identically.
8. **`sounds.py` (ch13) is a second observer on that same seam.** It subscribes
   to the hook events and plays a Windows sound per event via `winsound`
   (`PlaySound` for a WAV in `media` mode, `Beep` tones in `beep` mode). Off
   unless `NANOCODE_SOUND` (or `sounds.json`) asks for it, and it degrades to
   silence on any failure so it can never break a turn. `session_start` is the one
   event ch13 adds - emitted once by `main()`, heard as the startup tada.
9. **`sandbox.py` (ch14) is the write policy for ACT mode.** `roots` may be
   configured in `sandbox.json` (default `["."]`, i.e. "just in the folder"),
   `deny` subtrees always lose, and paths are judged after `os.path.realpath`, so
   `..` and symlinks are folded before the prefix test. The write tools ask
   `ToolContext.guard()` first and return its error string instead of writing.
   A refusal emits `sandbox_denied`, which `sandbox.install()` turns into a red
   FORBIDDEN line plus `sounds.alarm()` - the one sound that ignores the
   `NANOCODE_SOUND` opt-in (`NANOCODE_SOUND_ALARM=0` silences it). `run_command`
   is only a best-effort check (redirects and obvious mutators); the chapter says
   so, because a Python fence is not a container.
10. **`workflows.py` (ch15) is composition, not a framework.** A subagent is a
    second `Agent` run by `Agent._spawn_subagent(task)` on the same Python stack;
    the tools `run_subagent`/`run_subagents` reach it through
    `ToolContext.spawn`/`spawn_many`, so no tool imports the agent. A child gets
    its own sandbox, hook bus, brain and conversation - sharing any of them is
    the bug the chapter tests for - and a filtered menu
    (`SUBAGENT_BLOCKED_TOOLS`: no recursion, no `write_plan`, no `save_memory`),
    in PLAN mode with a 20-iteration budget. `_spawn_many` uses a
    `ThreadPoolExecutor` (HTTP waits release the GIL) and `pool.map` keeps results
    in task order. `workflows.py` turns that one verb into `fan_out`,
    `pipeline`, `map_reduce` and `critic_loop`; `demo_workflows.py` runs all four
    offline with a scripted `DemoBrain`, so the chapter needs no key to
    demonstrate.

## Lifecycle hooks

`hooks.py` (ch03 onward; identical up to ch14, plus the ch15 pair) is the one piece with no
counterpart in the book. The five core events never change:

| Event | Payload | Fires |
|---|---|---|
| `turn_start` | `user_input` | after the user message enters the conversation |
| `before_think` | `messages` | before each `brain.think()` |
| `after_think` | `thought` | after each `brain.think()` |
| `tool_call` | `name`, `args`, `result` | after each tool returns |
| `turn_end` | `output` | when the turn's answer is ready |

Three later chapters add events without changing those five: `session_start`
(ch13), `sandbox_denied` (ch14, emitted out of band by a tool's guard), and
`subagent_start` / `subagent_end` (ch15, emitted on the parent's bus around a
delegated child).

```python
agent.hooks.on("tool_call", lambda **e: print(e["name"], e["args"]))
agent.hooks.off("tool_call", handler)          # deregister

@agent.hooks.on("after_think")                 # decorator form
def log(thought, **rest):
    print("tokens in:", agent.brain.last_input_tokens)
```

They are printed, not just available: every chapter's `main()` calls
`install(agent.hooks)`, which registers a console listener that prints one
coloured line per event (`ui.hook_event`, styled by `hook.<event>` in `ui.json`)
and adds the banner hint. `NANOCODE_HOOKS=0` hides the lines without unregistering
anything, so user hooks and tracing keep working.

```
[openrouter:act] ❯   ⟡ hook:turn_start  "Create note.txt containing hello…"
  ⟡ hook:before_think  1 message(s) queued
  ↑ Thinking...
  ⟡ hook:after_think  text 43 chars · wants write_file
  → Writing note.txt
  ⟡ hook:tool_call  write_file(path=note.txt, content=hello) → 43 chars back
  ⟡ hook:turn_end  answer 154 chars
```

Rules the implementation enforces: handlers are passive (return values are
ignored), exceptions inside a handler are reported with `ui.warning` and skipped,
and `on()` rejects unknown event names immediately. `Hooks.trace(path)` appends
one JSON object per event (`Thought` objects are flattened, long strings
truncated); `install()` turns that on when `NANOCODE_TRACE` is set.

## Re-theming

Edit `ui.json`, restart. Keys resolve as `styles.<key>` -> `commands.<command>` ->
`tools.<tool_name>` -> `theme.<accent>`. Styles are Rich style strings
(`"bold bright_cyan"`, `"grey58 italic"`, `#ff8800`). A tool with no entry falls
back to `tools.default`.
