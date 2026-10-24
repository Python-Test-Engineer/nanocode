# ch12 — refactored Nanocode (Rich UI + OpenRouter)

The book's single-file `nanocode.py` (770 lines) split into four modules with
no behaviour changes to the agent loop:

| File | Holds | Depends on |
|------|-------|-----------|
| `llm.py` | Brains: `OpenRouter`, `Claude`, `DeepSeek`, `Ollama`, `Thought`, `ToolCall`, HTTP retry, dialect translation | `requests`, `dotenv`, `ui` |
| `tools.py` | `ReadFile`, `WriteFile`, `EditFile`, `WritePlan`, `ListFiles`, `SearchCodebase`, `SearchWeb`, `SaveMemory`, `RunCommand`, `ToolContext`, `tool_definitions`, `get_tool` | `ui` |
| `ui.py` | Everything printed: banner, prompt, thinking, tool lines, answers (Rich Markdown), errors, `/help` table | `rich`, `ui.json` |
| `ui.json` | Every colour, icon and label. No Python needed to re-theme | — |
| `nanocode.py` | `Memory`, `Agent` (the loop), `main()`; re-exports the old public names so `test_nanocode.py` runs unchanged | all of the above |

`nanocode_copy.py` is the untouched original from the book, kept for diffing.

## Run

From the repo root:

```bash
uv run ch12/nanocode.py          # start in PLAN mode
uv run ch12/nanocode.py --act    # start in ACT mode (writes enabled)
```

`.env` at the repo root supplies:

```
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL="deepseek-v4.1-flash-1017"
NANOCODE_BRAIN="openrouter"        # openrouter | claude | deepseek | ollama
NANOCODE_COLOR=1                   # optional: force colour when piping output
```

Optional overrides: `OPENROUTER_MAX_TOKENS` (default 8192),
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

## Re-theming

Edit `ui.json`, restart. Keys resolve as `styles.<key>`, then
`commands.<command>`, then `tools.<tool_name>`, then `theme.<accent>`.
Styles are Rich style strings (`"bold bright_cyan"`, `"grey58 italic"`, `#ff8800`).

Add a new tool? Give it an entry in `tools` (icon/style/verb) and it shows up
coloured; without one it falls back to `tools.default`.

## Tests

```bash
uv run pytest        # all 11 chapters from the repo root (197 tests)
cd ch12 && ../.venv/Scripts/python.exe -m pytest -q   # 22 passed
```

The suite is the book's original: it imports `Agent`, `tools`, `BRAINS`,
`ReadFile`, ... from `nanocode`, all of which are re-exported, and patches
`nanocode.DDGS`, which `tools.resolve_ddgs()` honours.

## Porting to another chapter

Already done for ch01-ch11; `../REFACTOR.md` has the per-chapter table and the
list of deliberate deviations (OpenRouter as first provider, the adapted ch04
switch test, the `output_rendered` flag for command feedback, Rich colour on
Windows, the Ollama probe timeout). The appendix (streaming) is not ported yet:
it needs `llm.Brain.think_stream()` plus a `ui.stream()` helper, nothing else.
