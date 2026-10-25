# Chapter 12 — Capstone (the whole agent, and how to read it)

> **You are here:** nothing new is added. This chapter is the same code as chapter
> 11, used on a real task — and a map for reading the finished agent in one
> sitting.

The book's chapter 12 is a build-it exercise (a snake game with the agent). The
exercise is the point: you already have every piece, and now you find out which
piece you actually understood.

## The finished architecture in one picture

```
                        ┌──────────────────────────────────────────┐
                        │              nanocode.py                 │
   your keystrokes ───► │  main() ─► Agent ─► ui.answer()          │ ───► your screen
                        │             │                            │
                        │             ├─ conversation (the memory)  │
                        │             ├─ mode (plan / act)         │
                        │             └─ hooks.emit(...)           │
                        └──────┬──────────────┬────────────────────┘
                               │              │
             ┌─────────────────▼───┐   ┌──────▼──────────────────┐
             │        llm.py       │   │        tools.py         │
             │ Brain: think()      │   │ execute(context, **a)   │
             │  OpenRouter         │   │  read write edit run    │
             │  Claude DeepSeek    │   │  list search plan save  │
             │  Ollama             │   │  web                    │
             └─────────────────────┘   └─────────────────────────┘
                               │              │
                        ┌──────▼──────────────▼───────┐
                        │  ui.py + ui.json (Rich)     │
                        │  hooks.py (events + trace)  │
                        └─────────────────────────────┘
```

Four arrows to memorise:

| From | To | Carries |
|---|---|---|
| Agent | Brain | the conversation, plus the tool menu |
| Brain | Agent | a `Thought` (text, tool_calls, raw_content, thinking) |
| Agent | Tool | `ToolContext` + the model's arguments |
| Tool | Agent | a **string** — output or error, never an exception |

Every chapter you have read is one of those arrows getting better.

## What's on disk (the whole project)

```
ch01  loop, echo                          ch07  plan/act modes
ch02  raw API call                        ch08  list + search
ch03  first brain, conversation           ch09  edit + run + compaction
ch04  multi-provider, retries, /switch    ch10  Ollama (local)
ch05  tools + agentic loop                ch11  web search
ch06  persistent memory                   ch12  capstone (== ch11)
                                          ch13  sound on the hook seam
```

Inside every chapter from 05 on: `nanocode.py` (agent), `llm.py` (brains),
`tools.py` (capabilities), `ui.py` + `ui.json` (console), `hooks.py` (events),
`test_nanocode.py` (the book's tests), `nanocode_copy.py` (the original file);
from ch13 on, `sounds.py` + `sounds.json` (events, heard).

## How to read the finished agent (a route, not a pile)

If you have one hour, read in this order and skip everything else:

1. **`nanocode.py: _agentic_loop()`** — twenty lines; the whole agent.
2. **`llm.py: class Thought`** — the only shape the agent passes around.
3. **`tools.py: class ReadFile`** — the tool contract in fifty lines.
4. **`nanocode.py: _tools_for_mode()`** — the safety model in four lines.
5. **`nanocode.py: _compact_conversation()`** — what endurance costs.
6. **`hooks.py: class Hooks`** — how the loop becomes observable.
7. **`ui.py: entry()`** — how theming resolves, and why colour is data.

Everything else is variation on those seven.

## Watch a full turn (the animation to keep in your head)

```
you type ──► Agent.handle_input
                │  append user message        conversation: 1
                ├─ emit turn_start
                ├─ emit before_think
                ├─ brain.think(conversation)  ──► Thought(tool_calls=[write_file])
                ├─ emit after_think
                ├─ append assistant raw_content         conversation: 2
                ├─ execute tool  ──► "Successfully wrote 27 characters"
                ├─ emit tool_call
                ├─ append tool_result as user            conversation: 3
                ├─ emit before_think
                ├─ brain.think(conversation)  ──► Thought(tool_calls=[run_command])
                ├─ ...                                    conversation: 5
                ├─ brain.think(conversation)  ──► Thought(text="done", no calls)
                └─ emit turn_end  ──► ui.answer(text)
```

Two tools, three requests, one answer. If you can redraw this from memory, you
understand the project.

## The capstone exercise

Build a small game (the book uses snake) with the agent, in a fresh directory:

```bash
mkdir snake && cd snake
uv run --project .. <path-to>/ch12/nanocode.py --act
```

Then, in this order — the order matters, it is the loop teaching you to work:

1. **Plan first.** Without `--act`, ask: "plan a single-file snake game with
   curses, arrow keys, score and game over". Read `PLAN.md`. Edit it by hand if
   the plan is wrong; that is allowed.
2. **Implement in slices.** `/mode act`, then: "implement step 1 of PLAN.md and run
   it". One slice per turn beats "write the whole game" — fewer moving parts when
   something fails.
3. **Make it fail on purpose.** "Make the snake wrap around the edges" then "that
   broke the score — fix it". Watch `run_command` output drive the next request.
4. **Use the harness.** `/mode plan` for a design question you do not want acted
   on. `/switch` to a second provider for a code review: "review snake.py as a
   reviewer; do not edit".
5. **Trace it.** `NANOCODE_TRACE=1` and read `.nanocode/trace.jsonl` afterwards:
   how many requests did the feature actually cost?

## Extensions that teach the most

Each of these is a small change to one file — the sign of a decent architecture:

| Idea | Touch | What you learn |
|---|---|---|
| `glob_files(pattern)` tool | `tools.py` + `ui.json` | the tool contract, without touching the loop |
| `read_file(start, end)` line range | `tools.py` | token budgeting inside a tool |
| streaming replies | `llm.py` + `ui.py` | the boundary between transport and rendering |
| approval hook before `run_command` | `hooks.py` + `nanocode.py` | hooks that observe vs policy that decides |
| cost meter per turn | hooks + `usage` in `llm.py` | what an agent actually costs |
| retry-on-empty-answer | `nanocode.py` | the loop's failure modes |

## Why it is built this way (the summary of the whole book)

**One loop.** Every capability is a tool, every provider is a brain. Nothing gets
a special case in the loop, which is why 12 chapters did not turn into 12 variants
of the agent.

**Strings, not exceptions, inside the loop.** Errors are data the model can act
on; exceptions end the turn.

**Safety by construction.** Plan mode removes tools from the request instead of
asking the model to behave.

**Observation built in.** Hooks and traces exist because an agent you cannot see
is an agent you cannot debug — or teach.

## Checkpoint (a final one)

<details>
<summary>Where would you add a "max 3 tool calls per turn" limit, and why there?</summary>

In `_agentic_loop`, next to `MAX_ITERATIONS` — it is a property of the turn's
shape, not of any tool or provider. That is the same reasoning that put compaction
there: the loop is where cross-cutting concerns live.
</details>

<details>
<summary>Why does the same agent code work with four providers and nine tools?</summary>

Because everything provider-specific lives behind `think()` and everything
capability-specific lives behind `execute()`. The agent is a policy layer: it
decides *when* to call, not *how* to talk or *what* to do.
</details>

<details>
<summary>What is the first thing you would change for production use?</summary>

Not the loop — the guard rails: a confirmation step before `run_command`, a
restricted workspace root, and a cost ceiling. The architecture supports all three
without restructuring, which is the point of keeping the loop small.
</details>

**You are done.** Go back to `ch01` and read it again; it will look different now.
