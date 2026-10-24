# Chapter 7 — Plan mode (safety by construction, not by instruction)

> **You are here:** the agent can write files, so it needs a way to work *without*
> writing them. Two modes, one flag per tool, and a rule: what the model cannot
> see, it cannot call.

This is the chapter to read twice. It is the difference between an agent you can
let loose and one you cannot.

## The idea in one picture

```
                     ┌────────────────────────────────────────────┐
                     │              full tool list                │
                     │ read · write · edit · run · plan · memory  │
                     └────────────────────────────────────────────┘
                              │                        │
             mode == "plan"   │                        │   mode == "act"
                              ▼                        ▼
                ┌──────────────────────┐   ┌──────────────────────────────┐
                │ read_file            │   │ read_file                    │
                │ write_plan           │   │ write_plan                   │
                │ save_memory          │   │ save_memory                  │
                │ (no write/edit/run)  │   │ write_file, edit_file,       │
                └──────────────────────┘   │ run_command                  │
                                           └──────────────────────────────┘
                       sent to the model as its tool menu
```

Two independent switches, and both matter:

1. **the menu** — `plan_safe` filters what is offered (a guarantee)
2. **the prompt** — one sentence explains *why* (a hint that improves plans)

Only the first one is a safety mechanism. The second is quality.

## What's new on disk

```
ch07/
  tools.py     plan_safe on every tool; WritePlan (writes PLAN.md)
  nanocode.py  Agent(mode=...), _build_system_prompt, _tools_for_mode,
               /mode command, /help
  ui.py        ui.mode_switch(), ui.help_table()
```

| New thing | Purpose |
|---|---|
| `plan_safe = True/False` | a fact each tool declares about itself |
| `_tools_for_mode()` | the filter that turns that fact into enforcement |
| `_build_system_prompt()` | memory + the current mode's rule |
| `/mode` | switching at runtime, with a coloured confirmation |
| `write_plan` | plan mode's only writable file: `PLAN.md` |

## The safety mechanism is one list comprehension

```python
def _tools_for_mode(self):
    """Return tool definitions based on current mode.

    The whole safety harness is this list comprehension: in plan mode the model
    is only *told about* tools whose plan_safe flag is True. There is no runtime
    permission check later, because an unoffered tool simply cannot be called -
    which is a much stronger guarantee.
    """
    if self.mode == "act":
        return tool_definitions(self.tools)
    return tool_definitions([t for t in self.tools if t.plan_safe])
```

Compare the two ways of saying "do not write files":

```
  prompt-only:   "Please do not write files."          <- a request
  menu filtering: write_file is not in the request      <- a fact
```

A model can ignore a request. It cannot call a tool it was never told about.
That is why the flag lives on the tool (`plan_safe = False`) and not in a
paragraph of system prompt.

## Switching requires rebuilding two things

```python
def _refresh_brain(self):
    """Push the current prompt and tool menu into the brain.

    The brain stores tools/system as attributes, so a mode change is only live
    once these two lines run. Forgetting this is the classic bug: the agent says
    "act mode" but the model still sees the old menu.
    """
    self.brain.tools = self._tools_for_mode()
    self.brain.system = self._build_system_prompt()
```

`/mode` is deliberately forgiving in one direction and strict in the other:

```python
self.mode = "act" if len(parts) > 1 and parts[1] == "act" else "plan"
```

A typo (`/mode actt`) means **plan**, never act. The safe choice is the default.

## Watch it run (frame by frame)

```
$ uv run ch07/nanocode.py                 # plan is the default
⚡ Nanocode v0.6 (Plan Mode)
  brain openrouter  model ...  mode plan  tools 4
  /help for commands
  ⟡ lifecycle hooks (NANOCODE_HOOKS=0 hides them)

[openrouter:plan] ❯ Add a --verbose flag to cli.py
  ⟡ hook:before_think  1 message(s) queued
  → Reading cli.py
  → Searching codebase for 'argparse'
  → Writing plan to PLAN.md
  ⟡ hook:turn_end  answer ...
Here is the plan I saved to PLAN.md ...
  (note: no write_file line, because write_file was never offered)

[openrouter:plan] ❯ /mode act
  ⚡ Switched to ACT MODE (Writing Enabled)
[openrouter:act]  ❯ now implement it
  → Editing cli.py                 <- now the tool exists
```

The `tools 4` in the banner is the same fact from the other direction: count the
tools in plan vs act mode and you can see the harness working.

## Why it is built this way

**Plan mode is read-only, not a no-op.** It still has `read_file`,
`search_codebase`, `list_files` (ch08) — research is the point. A mode that could
not look at anything would produce plans based on guesses.

**`PLAN.md`, not "a file the model chooses".** One writable target, fixed name.
The model cannot pick a path, so it cannot pick a dangerous one.

**The prompt still explains the mode.** Filtering prevents accidents; explaining
prevents *bad plans*. A model that knows it is read-only proposes changes instead
of silently doing half of them.

## Try it

```bash
uv run ch07/nanocode.py            # plan
uv run ch07/nanocode.py --act      # act
```

1. In plan mode, ask it to create a file. Watch the refusal and the tool menu in
   `hook:` lines. Then `/mode act` and repeat the same request.
2. `/mode`, `/mode plan`, `/mode nonsense` — what mode are you in each time? Why
   is the answer the same for the last two?
3. Read `PLAN.md` after a planning turn. Does the plan reference files it
   actually read? (If not, it guessed — good thing it could not act.)
4. Two terminals: one in plan mode, one in act mode, same prompt. Compare the
   transcripts. The visible difference is the tool menu, not the model.

## Checkpoint

<details>
<summary>Could the model still write a file in plan mode by calling <code>write_plan</code> with a path?</summary>

No — `write_plan` takes no path; it always writes `PLAN.md`. The schema is part
of the harness: arguments the model cannot express are arguments it cannot abuse.
</details>

<details>
<summary>Why does <code>_refresh_brain()</code> exist instead of setting mode and letting the brain read it?</summary>

Because the brain is deliberately dumb: providers know HTTP, not agent policy.
Passing policy in as `tools`/`system` keeps that boundary, and means a custom
brain (chapter 4's exercise) needs no changes to respect modes.
</details>

<details>
<summary>What is the danger of adding a "dangerous" tool with <code>plan_safe = True</code>?</summary>

It is now available in plan mode with no confirmation, and the harness silently
stops protecting you. `plan_safe` is a claim about the tool; audit it whenever you
add one — `run_command` with `rm -rf` is one typo away from a disaster.
</details>

**Next:** chapter 8 teaches the agent to look around the project before planning.
