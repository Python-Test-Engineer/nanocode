# ch13 — Nanocode + sound (hooks you can hear, on Windows)

Chapter 13 is chapter 12 with **one new module**: the lifecycle hooks that
chapter 12 printed are now also *played*, so you can hear the agent start, work
and finish without watching the terminal.

The agent loop, the brains, the tools and the UI are unchanged. Sound is an
observer on the same hook seam — that is the whole lesson.

| File | Holds | Depends on |
|------|-------|-----------|
| `llm.py` | Brains: `OpenRouter`, `Claude`, `DeepSeek`, `Ollama`, `Thought`, `ToolCall`, HTTP retry, dialect translation | `requests`, `dotenv`, `ui` |
| `tools.py` | `ReadFile`, `WriteFile`, `EditFile`, `WritePlan`, `ListFiles`, `SearchCodebase`, `SearchWeb`, `SaveMemory`, `RunCommand`, `ToolContext`, `tool_definitions`, `get_tool` | `ui` |
| `ui.py` | Everything printed: banner, prompt, thinking, tool lines, answers (Rich Markdown), errors, `/help` table | `rich`, `ui.json` |
| `ui.json` | Every colour, icon and label. No Python needed to re-theme | — |
| `hooks.py` | Lifecycle events (`session_start`, `turn_start`, `before_think`, `after_think`, `tool_call`, `turn_end`) + JSONL tracer | `ui` |
| **`sounds.py`** | **Events → sound: `install(hooks)`, `play(event)`, `winsound` media/beep** | **`winsound` (Windows)** |
| **`sounds.json`** | **Which sound for which event. Data, like `ui.json`** | — |
| `nanocode.py` | `Memory`, `Agent` (the loop), `main()`; re-exports the old public names so `test_nanocode.py` runs unchanged | all of the above |

`nanocode_copy.py` is the untouched original from the book, kept for diffing.

## What chapter 13 changed

```
hooks.py        EVENTS gains "session_start"; log_to_console prints it
nanocode.py     import sounds; sounds.install(agent.hooks); emit("session_start")
ui.json         a colour for the session_start hook line
sounds.py       new - the whole feature (see below)
sounds.json     new - session_start -> tada.wav, turn_start -> ding.wav, ...
test_nanocode.py   the ch12 suite + 11 sound tests (33 total)
```

## Sound

`main()` wires it up next to the console hook:

```python
install(agent.hooks)          # chapter 12: the events, printed
sounds.install(agent.hooks)   # chapter 13: the events, heard
agent.hooks.emit("session_start", ...)   # the startup tada
```

`sounds.install()` subscribes one handler per event in `sounds.json`:

| Event | Default WAV | When |
|---|---|---|
| `session_start` | `C:\Windows\Media\tada.wav` | the session comes up (**the startup sound**) |
| `turn_start` | `C:\Windows\Media\ding.wav` | you submit a turn |
| `tool_call` | `C:\Windows\Media\chimes.wav` | a tool is running |
| `turn_end` | `C:\Windows\Media\Windows Notify.wav` | the answer is ready |

Two playback modes, picked by `NANOCODE_SOUND`:

* `media` — `winsound.PlaySound(wav, SND_ASYNC | SND_NODEFAULT)`. The nice one;
  asynchronous, so the agent never blocks on audio.
* `beep` — `winsound.Beep(freq, ms)` tones. Works over RDP / in a VM / with no
  WAVs, which is exactly where `media` goes quiet.

It fails soft, always: not on Windows → silent; WAV missing → fall back to the
event's tone; `winsound` raises → swallowed; the hook raises → reported and
skipped by `hooks.py`. A peripheral never ends a turn.

## Run

From the repo root:

```bash
NANOCODE_SOUND=media uv run ch13/nanocode.py          # PLAN mode; you hear the tada
NANOCODE_SOUND=media uv run ch13/nanocode.py --act    # ACT mode (writes enabled)
NANOCODE_SOUND=beep  uv run ch13/nanocode.py          # tones only
uv run ch13/nanocode.py                               # unset -> silent (opt-in)
```

`.env` at the repo root supplies:

```
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL="deepseek-v4.1-flash-1017"
NANOCODE_BRAIN="openrouter"        # openrouter | claude | deepseek | ollama
NANOCODE_COLOR=1                   # optional: force colour when piping output
NANOCODE_SOUND=media               # media | beep | off  (unset follows sounds.json)
```

The `.env` overrides for individual sounds (full paths):

```
NANOCODE_SOUND_START=C:\Windows\Media\tada.wav            # session_start
NANOCODE_SOUND_LOOP=C:\Windows\Media\ding.wav             # turn_start
NANOCODE_SOUND_DONE=C:\Windows\Media\Windows Notify.wav   # turn_end
```

Other optional overrides: `OPENROUTER_MAX_TOKENS` (default 8192),
`OPENROUTER_CONTEXT_LIMIT` (default 128000), `NANOCODE_TIMEOUT` (shell tool, 30s),
`OLLAMA_MODEL`, `ANTHROPIC_MODEL`, `DEEPSEEK_MODEL`.

## How the pieces talk

```
main() ──> ui.ask()            styled prompt
  │
  └─> Agent.handle_input()
        ├─> llm.Brain.think(conversation) ──> Thought(text, tool_calls, raw_content, thinking)
        │        (OpenRouter translates Anthropic-style history <-> OpenAI messages)
        ├─> ui.thinking(thought.thinking)
        ├─> tool.execute(ToolContext, **args) ──> str   (tools.py, logs via ui.tool_action)
        └─> ui.answer(output)   Rich Markdown
```

`Brain.raw_content` is always stored in Anthropic content-block form, even when
the provider is OpenAI-compatible — so `/switch` mid-conversation keeps history
readable by whichever provider speaks next.

## Hooks

```python
from hooks import Hooks

agent.hooks.on("tool_call", lambda **e: print(e["name"], e["args"]))
agent.hooks.on("turn_end", lambda output, **rest: print(len(output), "chars"))
```

Events: `session_start`, `turn_start`, `before_think`, `after_think`,
`tool_call`, `turn_end` (`session_start` is new in ch13). Handlers observe only -
return values are ignored and exceptions are reported and skipped.

Each event is also printed while the agent runs (a coloured `⟡ hook:<event>` line,
styled by the `hooks` section of `ui.json`); `main()` wires that up with
`install(agent.hooks)`. `NANOCODE_HOOKS=0` hides the lines, and
`NANOCODE_TRACE=1` appends the same events to `.nanocode/trace.jsonl`.

## Re-theming

Edit `ui.json`, restart. Keys resolve as `styles.<key>`, then
`commands.<command>`, then `tools.<tool_name>`, then `theme.<accent>`.
Styles are Rich style strings (`"bold bright_cyan"`, `"grey58 italic"`, `#ff8800`).

Add a new tool? Give it an entry in `tools` (icon/style/verb) and it shows up
coloured; without one it falls back to `tools.default`.

## Tests

```bash
uv run pytest        # all chapters from the repo root (230 tests)
cd ch13 && uv run pytest -q     # 33 passed
```

`uv run pytest` covers every chapter because the repo-root `conftest.py` gives
each one a private import root; ch13 is the first chapter with a `sounds.py`, and
`conftest.py` now binds it too so it cannot leak between chapters.
`uv run python run_all_tests.py` is the same suites, one process per chapter.

The suite is the book's original (importing `Agent`, `tools`, `BRAINS`,
`ReadFile`, ... which `nanocode.py` re-exports, and patching `nanocode.DDGS`, which
`tools.resolve_ddgs()` honours) plus this chapter's sound tests: the startup sound
is `tada.wav`, sound is off until `NANOCODE_SOUND` asks for it,
`NANOCODE_SOUND_START` overrides the file, a missing WAV falls back to the tone,
and a broken player never breaks a turn.

## Porting to another chapter

Already done for ch01-ch11; `../REFACTOR.md` has the per-chapter table and the
list of deliberate deviations (OpenRouter as first provider, the adapted ch04
switch test, the `output_rendered` flag for command feedback, Rich colour on
Windows, the Ollama probe timeout). The appendix (streaming) is not ported yet:
it needs `llm.Brain.think_stream()` plus a `ui.stream()` helper, nothing else.
