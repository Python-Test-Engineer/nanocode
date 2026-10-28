# ch15 — Subagents, and four ways to arrange them

Chapter 15 is chapter 14 with **one new verb**: the agent can hand a task to
another agent. Not a new process, not a framework, not a queue — a second
`Agent` instance with its own brain, conversation, tool menu, sandbox and hook
bus, driven by `handle_input(task)` on the same Python stack.

Two tools ask for it (`run_subagent`, `run_subagents`), one method builds it
(`Agent._spawn_subagent`), and one new file arranges it into the patterns people
give names to (`workflows.py`). `demo_workflows.py` runs all four arrangements
offline, with the real Agent code and a scripted brain, so the chapter can be
demonstrated without a key, a network or a bill.

| File | Holds | Depends on |
|------|-------|-----------|
| `llm.py` | Brains, `Thought`, `ToolCall`, HTTP retry, dialect translation | `requests`, `dotenv`, `ui` |
| `tools.py` | All chapter-14 tools, plus **`RunSubagent`** and **`RunSubagents`**; `ToolContext` gains **`spawn`/`spawn_many`**; `subagent_limit()` | `ui`, `sandbox` (passed in) |
| `ui.py` | Everything printed, plus **`ui.scope(label)`** — a per-thread `[subN]` prefix | `rich`, `ui.json` |
| `ui.json` | Colours and labels for the two new tool lines and the two new hook events | — |
| `hooks.py` | Events, plus **`subagent_start` / `subagent_end`** and their console lines | `ui` |
| `sounds.py` / `sounds.json` | unchanged machinery, two new optional sounds | `winsound` (Windows) |
| `sandbox.py` / `sandbox.json` | unchanged; a child gets a *copy* of the policy | `ui`, `sounds` |
| **`workflows.py`** | **`fan_out`, `pipeline`, `map_reduce`, `critic_loop` — pure functions over `spawn`** | — |
| `nanocode.py` | `Agent` gains **`_spawn_subagent`**, **`_spawn_many`**, a per-agent `max_iterations`, and the subagent budget constants | all of the above |
| **`demo_workflows.py`** | **the offline demo: `DemoBrain` + the four patterns, through the real Agent** | all of the above |
| `test_nanocode.py` | the ch14 suite + 26 subagent/workflow tests (88 total) | — |

`nanocode_copy.py` is the book's original single file, kept for diffing.

## The shape in one table

| Question | Answer | Where |
|---|---|---|
| What is a subagent? | an `Agent` instance, built fresh, driven by `handle_input(task)` | `Agent._spawn_subagent` |
| How does a tool ask for one? | `context.spawn(task) -> str`, or `context.spawn_many(tasks) -> list[str]` | `ToolContext` |
| Where does it run? | the same thread (and the same stack), or a thread from `ThreadPoolExecutor` | `_spawn_many` |
| What does it inherit? | the parent's memory (read-only) and its tool *types* | `_subagent_tools` |
| What must it never share? | sandbox, hooks, brain, conversation, PLAN.md, the memory *writer* | `SUBAGENT_BLOCKED_TOOLS` + four fresh objects |
| How many steps may it take? | `SUBAGENT_MAX_ITERATIONS` (20), not the parent's 50 | `Agent.max_iterations` |
| How many at once? | 4 (`subagent_parallel`), max 8 per fan-out (`NANOCODE_MAX_SUBAGENTS`) | `_spawn_many`, `subagent_limit` |
| What does the parent see? | one tool result per child, and two hook events | `_agentic_loop` |

## What chapter 15 changed

```
workflows.py      new - fan_out, pipeline, map_reduce, critic_loop, PATTERNS
demo_workflows.py new - offline demo: DemoBrain + the four patterns
tools.py          RunSubagent, RunSubagents; ToolContext(spawn=, spawn_many=);
                  subagent_limit(); both tools registered
nanocode.py       Agent._spawn_subagent / _spawn_many / _subagent_tools;
                  max_iterations moved from a module constant onto the agent;
                  subagent_* knobs; _execute_tool passes spawn/spawn_many
ui.py             ui.scope(label) + _lead(): every line can say which agent spoke
hooks.py          subagent_start / subagent_end in EVENTS + console handlers
ui.json           tools.run_subagent(s), hooks.subagent_start/end, styles.subagent
sounds.json       subagent_start -> Windows Notify, subagent_end -> ding
test_nanocode.py  the ch14 suite + 26 subagent/workflow tests (88 total)
```

## A subagent is an Agent, not a process

```python
def _spawn_subagent(self, task):
    sub = Agent(brain=..., tools=self._subagent_tools(), memory=self.memory,
                mode="plan", sandbox=fresh_sandbox, max_iterations=20)
    sub.hooks = Hooks()                      # the child is on its own
    with ui.scope(label):                    # its lines say [sub1]
        result = sub.handle_input(task)
    return result                            # one string, like any tool
```

That is the whole feature. The parent's `_agentic_loop()` is unchanged: it sees
a tool call, it calls `_execute_tool`, the tool calls `context.spawn`, and a
nested `_agentic_loop()` runs one stack frame deeper. The only real OS process
in this repository is still `RunCommand` → `subprocess.run(...)`, and that runs a
shell command, not an agent.

## The four things a child must not share

Each one is a bug the chapter's tests pin down:

| Not shared | What breaks if you pass the parent's object |
|---|---|
| `Sandbox` | `Sandbox.arm(mode)` **mutates**. A PLAN-mode child would disarm the ACT parent's fence for the rest of the session. |
| `Hooks` | The parent's observers would receive the child's `tool_call`s as if the parent had made them; the trace becomes one flat, unattributable stream. |
| `Brain` | `last_input_tokens`, `tools` and `system` are per-instance; two agents sharing one brain overwrite each other mid-turn. |
| Tool list | `run_subagent` would recurse without a depth limit; `write_plan` would let a "read-only" child rewrite `PLAN.md`; `save_memory` would let it rewrite the parent's system prompt. |

`SUBAGENT_BLOCKED_TOOLS` is therefore four names long, and `_subagent_tools()`
is one list comprehension. That is the safety story: not a prompt that says
"don't", a menu that cannot.

## One-shot, read-only, bounded

A subagent gets **one** task string and returns **one** final answer. It cannot
ask a question, cannot see the parent's conversation, and runs in **PLAN mode**,
so its tool menu is `plan_safe` only: it can read, list, search files and search
the web; it cannot write. The parent does the writing.

Three consequences worth stating out loud:

* **The task must carry its own context.** Every `run_subagent` description says
  so, and the demo's tasks show it: goal, inputs, and the shape of the answer.
* **It costs one summary, not a transcript.** A child can spend 20 iterations
  and 100k tokens; the parent's conversation grows by one tool result.
* **It cannot loop forever.** `SUBAGENT_MAX_ITERATIONS = 20` per child and
  `NANOCODE_MAX_SUBAGENTS = 8` per fan-out, both checked before anything starts.

## Parallelism: threads, and why not processes

```python
with ThreadPoolExecutor(max_workers=workers) as pool:
    return list(pool.map(self._spawn_subagent, tasks))   # order preserved
```

`brain.think()` is a blocking `requests.post`, so the GIL is released for the
part that takes the time — the network wait — and four children really do
overlap. Processes would buy CPU parallelism this workload does not need, at the
cost of pickling, the Windows spawn start method, duplicated imports and no
shared console. The test suite proves the overlap with a `threading.Barrier`:
it deadlocks and fails if `_spawn_many` ever goes sequential.

`ui.scope(label)` is the other half of running in parallel: the console is one
shared object, so each thread carries its own label in `threading.local()` and
every line it prints is prefixed `[sub1]`, `[sub2]`, …

## Four arrangements (`workflows.py`)

| Pattern | Function | When |
|---|---|---|
| fan-out | `fan_out(spawn, tasks)` | the tasks do not depend on each other |
| pipeline | `pipeline(spawn, task, stages)` | the work is a sequence: outline → draft → tighten |
| map-reduce | `map_reduce(spawn, tasks, reduce_task)` | many views must become one decision |
| critic loop | `critic_loop(spawn, task, rounds)` | the answer has to get better, not just arrive |

They are pure functions over `spawn`, which is what makes them testable without
a model (`lambda task: task.upper()` is a valid `spawn`) and usable with either a
real agent (`agent._spawn_subagent`) or a fake one.

## The demo

```bash
cd ch15
uv run python demo_workflows.py            # all four, offline
uv run python demo_workflows.py fanout     # one
uv run python demo_workflows.py --list     # what the patterns are for
```

No key, no network: `DemoBrain` answers from the task's own words. Everything
else is real — the tool, `Agent._spawn_many`, the threads, the sandbox copy, the
hook bus and the `[subN]` labels.

What to look for:

```
  ⇉ Fanning out 3 task(s) in parallel
  ⇉ hook:subagent_start  sub1 · SECURITY review: read ch15/tools.py and say wha…
  ⇉ hook:subagent_start  sub2 · TEST review: read ch15/nanocode.py and list whi…
  ⇉ hook:subagent_start  sub3 · LAYOUT review: explain the module layout of ch1…
  [sub3] ↑ Thinking...
  [sub3] → Listing .
  [sub1] ↑ Thinking...
  ...
  ⇊ hook:subagent_end  sub1 · ok · 269 chars · 0.3s
  ⟡ hook:tool_call  run_subagents(tasks=['SECURITY review…) → 727 chars back
```

The interleaving is the point (the children run at once), and the two hook lines
per child are the only thing the *parent's* bus hears. Then:

```bash
uv run python demo_workflows.py --live "audit ch15/ and report the three biggest risks"
```

Same wiring, real provider, `mode="act"` — the model decides whether to delegate
at all. A subagent is a tool the model may ignore.

## Run the agent

From the repo root:

```bash
uv run ch15/nanocode.py --act     # same agent as ch14, now with delegation
```

Then try:

```
use a subagent to find every place MAX_ITERATIONS is mentioned, then summarise
```

`.env` at the repo root supplies the usual:

```
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL="deepseek-v4.1-flash-1017"
NANOCODE_BRAIN="openrouter"
NANOCODE_MAX_SUBAGENTS=8        # ceiling on one fan-out
NANOCODE_SOUND=media            # media | beep | off
```

## Tests

```bash
uv run pytest                   # all chapters from the repo root: 380 passed
cd ch15 && uv run pytest -q     # 88 passed
```

The new tests cover: both tools' error paths, the parent receiving only the
child's answer, the filtered tool menu, a fresh sandbox/hook bus (via a spy
`Agent`), the per-agent iteration budget, the two hook events and their order,
empty tasks, a failing brain factory, result order, real concurrency (barrier),
the fan-out ceiling, the bare-string argument models sometimes send, per-thread
UI labels, and each of the four workflow patterns with a fake `spawn`.

`conftest.py` binds `workflows` alongside the other per-chapter modules, so the
root `uv run pytest` cannot leak ch15's patterns into another chapter.

## Porting to another chapter

`workflows.py` has no imports from this repository: copy it anywhere. The
subagent support is one tool pair, one `ToolContext` field pair and two methods
on `Agent`; nothing else in the loop changed. If you only want the demo, copy
`workflows.py` and `demo_workflows.py` and replace `Agent` with your own class
that has a `_spawn_subagent`-shaped callable — the patterns only need `spawn`.
