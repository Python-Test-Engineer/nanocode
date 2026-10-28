# Chapter 15 — Subagents, and four ways to arrange them

> **You are here:** fourteen chapters built one agent that does everything in one
> conversation. This chapter lets that agent hand a *self-contained* piece of
> work to another agent, get one answer back, and keep going — without a new
> process, a queue or a framework. Then it names the four ways people arrange
> those agents, and shows each one running.

The trick is smaller than it sounds. Everything a subagent needs already exists
in this repository: `Agent` is a class, `handle_input` is a method, and a tool is
just a callable that returns a string. Delegation is what you get when you put
those three facts next to each other:

```python
sub = Agent(brain=..., tools=..., memory=..., sandbox=..., max_iterations=20)
sub.hooks = Hooks()
answer = sub.handle_input(task)          # same method, one stack frame deeper
```

No new process. The only real OS process in this repository is still
`RunCommand` → `subprocess.run(...)`, and that runs a shell command, not an agent.

## The idea in one picture

```
   parent._agentic_loop()                         one Python process
   │
   ├─ thought: run_subagent(task)
   │     │
   │     └─ tools.RunSubagent.execute(context, task)
   │           │
   │           └─ context.spawn(task)             ← the tool only ASKS
   │                 │
   │                 └─ Agent._spawn_subagent(task)
   │                       │  fresh brain / conversation / tools
   │                       │  fresh sandbox / hooks
   │                       ▼
   │                    child._agentic_loop()     ← the same method, recursing
   │                       ├─ thought: read_file(...)   ┐
   │                       ├─ thought: search_codebase  ├ the child's own turn:
   │                       └─ answer: "…"               ┘ its own context, its own
   │                                                        tool results, its own
   │                       ▲                                iteration budget
   │                       │  one string
   │     ◄─────────────────┘
   │
   ├─ tool_result: "…"        ← the parent's conversation grew by ONE message
   └─ thought: the merged answer
```

Two things to notice in that picture.

**The recursion is the loop, not beside it.** `_agentic_loop()` is not
special-cased for children: the parent calls a tool, the tool calls the parent's
`spawn`, and `spawn` calls `handle_input` → `_agentic_loop()` on a new object.
Recursion through the tool table is what a subagent *is*.

**The parent is blind on purpose.** It sees one tool result — the child's final
text — and two events on its hook bus. It does not see the child's conversation,
tool calls or reasoning. That is the feature: a child can spend twenty
iterations and a hundred thousand tokens investigating, and the parent pays one
paragraph for it.

## What's new on disk

| File | Change | Why this file |
|---|---|---|
| `tools.py` | `RunSubagent`, `RunSubagents`; `ToolContext` gains `spawn`/`spawn_many`; `subagent_limit()` | a tool is the only thing the model can *ask with* |
| `nanocode.py` | `_spawn_subagent`, `_spawn_many`, `_subagent_tools`; `max_iterations` moves onto the agent | only the agent may build an agent |
| `workflows.py` | **new** — `fan_out`, `pipeline`, `map_reduce`, `critic_loop` | arrangement is a separate concern from capability |
| `demo_workflows.py` | **new** — offline demo with `DemoBrain` | a demo you cannot run is not a demo |
| `ui.py` | `ui.scope(label)`, a per-thread `[subN]` prefix, and `subagent_color()` / `subagent_style()` | one console, many speakers — each in its own colour |
| `hooks.py` | `subagent_start`, `subagent_end` | delegation is observable on the same seam as everything else |
| `ui.json` | two tool lines, two hook lines, `styles.subagent`, and `subagents.palette` | taste stays out of Python |
| `sounds.json` | `subagent_start`, `subagent_end` | the ch13 seam, reused, no code |
| `test_nanocode.py` | the ch14 suite + 30 tests | isolation, concurrency and colour are exactly what tests are for |

The sandbox and the brains are untouched. A change that needed a new provider or
a new `Sandbox` rule would have been a change in the wrong place.

## The code

### 1. The tool only asks

```python
class RunSubagent:
    name = "run_subagent"
    plan_safe = True

    def execute(self, context, task):
        ui.tool_action("run_subagent", _clip(task, 60))
        if context.spawn is None:
            return "Error: subagents are not available in this agent"
        try:
            return context.spawn(task)
        except Exception as e:
            return f"Error: subagent failed: {e}"
```

Nine lines, and not one of them knows what an `Agent` is. That is deliberate:
the tool's job is to describe the capability to the model and to survive its
own failure. The *policy* — which brain, which tools, which budget, which
sandbox — belongs to whatever built the context.

`plan_safe = True` because a child is a researcher: it runs in PLAN mode, so it
can read and search but not write. Delegation is therefore safe in either mode,
and the tool does not need to check the parent's mode at all.

### 2. The context carries the callable

```python
class ToolContext:
    def __init__(self, memory=None, sandbox=None, hooks=None, spawn=None, spawn_many=None):
        ...
        self.spawn = spawn            # callable(task) -> str
        self.spawn_many = spawn_many  # callable(tasks) -> list[str]
```

This is chapter 14's lesson again. `guard()` let a tool ask *the policy* a
question it was not allowed to answer itself; `spawn()` lets a tool ask *the
agent* to do the thing the tool is not allowed to know about. Both keep the
knowledge on the side that owns it, and both default to `None`, so every older
chapter's tools keep working unchanged — `ToolContext()` still means "no
policy, no subagents".

### 3. The agent builds the child

```python
def _spawn_subagent(self, task):
    text = str(task or "").strip()
    if not text:
        return "Error: the subagent's task is empty"

    with self._subagent_lock:                 # labels stay unique under threads
        self.subagents_spawned += 1
        label = f"sub{self.subagents_spawned}"

    sub_sandbox = Sandbox(                    # a COPY, not the parent's object
        roots=list(self.sandbox.roots),
        enabled=self.sandbox.enabled,
        deny=list(self.sandbox.deny),
    )
    sub = Agent(
        brain=self._subagent_brain_for(self._subagent_tools()),
        tools=self._subagent_tools(),
        memory=self.memory,                   # shared, and read-only by menu
        mode="plan",                          # read-only by construction
        sandbox=sub_sandbox,
        max_iterations=self.subagent_max_iterations,
    )
    sub.hooks = Hooks()                       # fresh bus: the parent hears 2 events
    sub.brain.system = SUBAGENT_SYSTEM_PROMPT + (sub.brain.system or "")

    self.hooks.emit("subagent_start", label=label, task=text)
    try:
        with ui.scope(label):
            result = sub.handle_input(text)
    finally:
        self.hooks.emit("subagent_end", label=label, task=text, result=result, ...)
    return result
```

Read it as a list of things **not** to share. Every line in that list is a bug
that was waiting to happen, and the tests in this chapter pin each one down.

### 4. Four fresh objects, and a filtered menu

| Object | Why fresh |
|---|---|
| `Sandbox` | `arm()` **mutates** the object. A PLAN-mode child sharing the parent's sandbox would disarm the ACT parent's fence for the rest of the session. |
| `Hooks` | The parent's observers would receive the child's `tool_call`s as if the parent had made them. Two events per child is a trace you can read; N events is noise. |
| `Brain` | `last_input_tokens`, `tools` and `system` are per-instance. Two agents on one brain overwrite each other mid-turn. |
| `conversation` | It is created by `__init__` and grows with `handle_input`. Sharing it is not even expressible — which is the point. |

The tool list is filtered, not copied:

```python
SUBAGENT_BLOCKED_TOOLS = frozenset({
    "run_subagent", "run_subagents",   # no recursion: no depth limit needed
    "write_plan",                      # PLAN.md is the parent's plan
    "save_memory",                     # memory is shared; the writer goes
})
```

Three names remove three whole classes of problem. No recursion means no depth
counter, no budget tree and no "which grandchild did this?" in the trace. No
`write_plan` means a child in PLAN mode really cannot write *anything*.
No `save_memory` means the shared memory stays a read-only input.

### 5. A smaller budget, on the object

Chapter 14's loop used a module constant:

```python
for _iteration in range(MAX_ITERATIONS):     # ch14
for _iteration in range(self.max_iterations): # ch15
```

That one-word change is the chapter's only edit to `_agentic_loop()`, and it is
not a feature — it is a scope fix. A module constant cannot say "this agent gets
20 steps and that one gets 50". `Agent.__init__` now takes `max_iterations=`,
`subagent_max_iterations=` and `subagent_parallel=`, with the same defaults as
before for the parent. Nothing about the parent's behaviour changed.

### 6. Threads, with the order kept

```python
def _spawn_many(self, tasks):
    tasks = list(tasks)
    if len(tasks) == 1:
        return [self._spawn_subagent(tasks[0])]
    workers = max(1, min(self.subagent_parallel, len(tasks)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="subagent") as pool:
        return list(pool.map(self._spawn_subagent, tasks))
```

Four decisions in six lines:

* **Threads, not processes.** `brain.think()` is a blocking `requests.post`, so
  the GIL is released for the part that takes the time — the wait. Four threads
  cost nothing and give four overlapping HTTP calls. Processes would give CPU
  parallelism this workload does not need, and cost pickling, the Windows spawn
  start method, duplicated imports and no shared console.
* **`pool.map`, not `as_completed`.** Results stay in task order even though the
  children finish out of order, which is the contract `RunSubagents` promises the
  model ("results come back in the same order as the tasks").
* **A bounded pool.** `subagent_parallel` is 4; fifty tasks start four at a time.
  `RunSubagents` also caps the list at `NANOCODE_MAX_SUBAGENTS` (8) and says how
  many it dropped — the model wrote that list, and "summarise every file in the
  repo" is a reasonable thing to ask and an expensive thing to obey.
* **A lock for the label only.** `self._subagent_lock` guards the counter that
  names children `sub1`, `sub2`, … Everything else the children touch is
  per-object. If a wider lock were needed, threads would have been the wrong
  choice.

### 7. One console, many speakers

Parallel children interleave their output, and the console is one shared object.
So the label lives in `threading.local()`:

```python
@contextlib.contextmanager
def scope(name):
    previous = label()
    _scope.label = name
    try:
        yield
    finally:
        _scope.label = previous
```

Every line `ui` prints asks `_lead()` for the prefix, which is why this works for
tool lines, errors, thinking and answers without any of them knowing about
subagents:

```
  [sub3] ↑ Thinking...
  [sub3] → Listing .
  [sub1] ↑ Thinking...
  [sub1] → Listing .
  [sub2] ↑ Thinking...
```

A module global would have been overwritten by whichever thread wrote last.
`threading.local()` gives each thread its own label and keeps the console shared,
which is exactly the split we want: one screen, many speakers.

A label tells you *which* child; it does not help you *follow* one down an
interleaved screen. So each child also gets a colour, and the colour is derived
from the label rather than passed around:

```python
def subagent_color(name=None):
    name = label() if name is None else str(name)
    palette = subagent_palette()                       # ui.json -> subagents.palette
    digits = "".join(character for character in name if character.isdigit())
    index = int(digits) - 1 if digits else zlib.crc32(name.encode("utf-8"))
    return palette[index % len(palette)]
```

`sub1` is always `palette[0]`, `sub2` always `palette[1]`, and a ninth child
wraps to `palette[0]` — colour is the fast cue, the label is the truth. The
palette is data (`["bright_cyan", "bright_magenta", "bright_yellow", …]`), so a
light terminal or a colour-blind reader changes one list in `ui.json` and no
Python. `ui.subagent_style(label)` combines the child's colour with the shared
modifier in `styles.subagent` (`"bold"`), and every line helper paints `_lead()`
with it:

```
  ⇉ hook:subagent_start  sub1  SECURITY review: …      sub1 = bright_cyan
  ⇉ hook:subagent_start  sub2  TEST review: …          sub2 = bright_magenta
  ⇉ hook:subagent_start  sub3  LAYOUT review: …        sub3 = bright_yellow
  [sub2] → Listing .
```

The two `subagent_*` lines are the parent's, printed with no thread scope, so
`ui.hook_event(..., subagent_label=label)` paints just the child's name — the
same colour its own lines will use, which is what makes a fan-out read as
colour-coded columns.

### 8. Delegation is two events

```python
self.hooks.emit("subagent_start", label=label, task=text)
...
self.hooks.emit("subagent_end", label=label, task=text, result=result,
                seconds=..., ok=ok)
```

Chapter 13 played a sound per event; chapter 14 raised an alarm per refusal. This
chapter adds no observer at all — it adds two *events*, and the observers that
already exist pick them up: `hooks.log_to_console` prints two lines per child,
and `sounds.json` maps them to two short notes with no code change. That is what
a real seam buys you on the third chapter of using it.

### 9. The four arrangements

`workflows.py` is four functions over the same signature, `spawn(task) -> str`:

```python
def fan_out(spawn, tasks, workers=4):
    with ThreadPoolExecutor(max_workers=...) as pool:
        return list(pool.map(spawn, tasks))

def pipeline(spawn, task, stages):
    text = task
    for index, instruction in enumerate(stages, start=1):
        text = spawn(_with_input(f"Stage {index} of {len(stages)}. {instruction}", text))
    return text

def map_reduce(spawn, tasks, reduce_task, workers=4):
    answers = fan_out(spawn, tasks, workers=workers)
    sections = [f"### Task {i}\n{task}\n\n### Answer {i}\n{answer}" for ...]
    return spawn(f"{reduce_task}\n\n" + "\n\n".join(sections))

def critic_loop(spawn, task, rounds=2):
    draft = spawn(...)
    for _round in range(rounds):
        critique = spawn(...)
        draft = spawn(...)
    return draft
```

| Pattern | Shape | When it is the right tool | What it costs |
|---|---|---|---|
| fan-out | N children, side by side | the tasks are independent | wall-clock of the slowest; N× tokens |
| pipeline | A → B → C, one at a time | the work is a sequence | latency is the sum; each stage is blind to the rest |
| map-reduce | N children, then one merger | many views must become one decision | one more call, and a summary of summaries |
| critic loop | write → critique → revise × N | the answer must get better | 2N+1 calls for N rounds |

Because they take `spawn` rather than an `Agent`, they are testable without a
model — `lambda task: task.upper()` is a perfectly valid `spawn` — and they work
with a real agent (`agent._spawn_subagent`), a fake one, or a future
implementation that reaches another machine.

### 10. The demo's brain is a stand-in, its agents are not

`demo_workflows.py` replaces only the model:

```python
class DemoBrain(Brain):
    def think(self, conversation):
        if self._is_subagent():
            if not _has_tool_result(conversation):
                return self._tool("list_files", {"path": "."})   # real tool, real loop
            return self._say(_answer(self.task))
        ...
```

Everything below the model is the real thing: the tool table, `context.spawn`,
`_spawn_many`'s thread pool, the copied sandbox, the fresh hook bus and the
`[subN]` labels. That is the point of an offline demo — you are watching the
chapter's actual code, with the one part that needs a key and a bill replaced.

## Watch it run

```
$ uv run python demo_workflows.py fanout
⚡ Nanocode ch15 · subagents offline
   the real Agent, tool and hook code; only the model is scripted

── fan-out · the agent delegates through the tool
   run_subagents -> Agent._spawn_many -> 3 threads -> one merged answer

  ⟡ hook:turn_start  "AUDIT THE CHAPTER: review security, tests and layou…"
  ⟡ hook:before_think  1 message(s) queued
  ↑ Thinking...
  ⟡ hook:after_think  wants run_subagents
  ⇉ Fanning out 3 task(s) in parallel
  ⇉ hook:subagent_start  sub1 · SECURITY review: read ch15/tools.py and say wha…
  ⇉ hook:subagent_start  sub2 · TEST review: read ch15/nanocode.py and list whi…
  ⇉ hook:subagent_start  sub3 · LAYOUT review: explain the module layout of ch1…
  [sub3] ↑ Thinking...
  [sub3] → Listing .
  [sub1] ↑ Thinking...
  [sub1] → Listing .
  [sub2] ↑ Thinking...
  [sub2] → Listing .
  [sub3] ↑ Thinking...
  ⇊ hook:subagent_end  sub3 · ok · 226 chars · 0.3s
  [sub1] ↑ Thinking...
  ⇊ hook:subagent_end  sub1 · ok · 269 chars · 0.3s
  [sub2] ↑ Thinking...
  ⇊ hook:subagent_end  sub2 · ok · 192 chars · 0.3s
  ⟡ hook:tool_call  run_subagents(tasks=['SECURITY review…) → 727 chars back
  ⟡ hook:before_think  3 message(s) queued
  ⟡ hook:after_think  text 336 chars
  ⟡ hook:turn_end  answer 336 chars

Audit summary

3 reviewers reported. Themes, in one line each:

 • capability is fenced at the tool, not in the prompt
 • the tests to add are about isolation, not about answers
 • the layout has one rule: capability, policy, arrangement.

(The child answers arrived as a single tool result; their conversations never
entered this one.)
```

Three things are worth reading frame by frame.

1. **`[sub3]` before `[sub1]`.** The children are not running in the order they
   were started, because they are running at the same time. No thread means no
   interleaving, and the trace would be a tidy lie about a parallel fan-out.
   Each child's lines are also in its own colour (sub1 cyan, sub2 magenta, sub3
   yellow), so one child can be followed down an interleaved screen.
2. **Two hook lines per child, none of the child's own.** `subagent_start` and
   `subagent_end` are emitted on the *parent's* bus. The child's `before_think`
   and `tool_call` events go to its own bus, which has no listeners — the same
   granularity the parent's conversation gets.
3. **`→ 727 chars back`.** Three children, each with a tool call, a tool result
   and a final answer, arrived in the parent's conversation as one tool result
   of 727 characters. That ratio is the entire economic argument for subagents.

Then the sequential patterns:

```
── pipeline · each stage's answer is the next stage's input
   outline -> draft -> tighten, three subagents, one at a time

  ⇉ hook:subagent_start  sub1 · Stage 1 of 3. Outline the introduction in four …
  ⇊ hook:subagent_end  sub1 · ok · 143 chars · 0.3s
  ⇉ hook:subagent_start  sub2 · Stage 2 of 3. Write the first draft from this o…
  ⇊ hook:subagent_end  sub2 · ok · 228 chars · 0.3s
  ⇉ hook:subagent_start  sub3 · Stage 3 of 3. Tighten the draft: cut every sent…
  ⇊ hook:subagent_end  sub3 · ok · 271 chars · 0.3s
```

`sub1` ends before `sub2` begins, by construction: `pipeline` hands each stage's
answer to the next as its input, so there is nothing to parallelise. Contrast
that with the map-reduce run, where three `subagent_start`s appear before the
first `subagent_end`.

## Why it is built this way

**Why not a process per subagent?** Because nothing here needs one. A subagent's
job is *context* isolation, not fault or memory isolation: its conversation,
tool menu, sandbox and budget are separate objects, and that is what makes it a
separate agent. A process would add pickling, the Windows spawn start method,
duplicated imports, IPC for the answer, and a startup cost per task — for a
workload that is 99% waiting on a socket.

**Why threads rather than asyncio?** Because the whole codebase is blocking
`requests`, and rewriting every tool and brain as `async` to gain concurrency
that `ThreadPoolExecutor` already gives us would be the tail wagging the dog.
Threads are enough *because* the expensive call releases the GIL. If the
subagents were CPU-bound, the answer would change: processes.

**Why are children read-only?** Three reasons, in order of importance. (1) A
fan-out of writers needs conflict handling — two children editing the same file
is a merge problem this chapter is not about. (2) A child that reports is easier
to audit than a child that also changed things: the parent's transcript shows
exactly what was written, in one place. (3) PLAN mode already means "the menu
has no write tools", so the guarantee costs one argument, not a new policy.

**Why not a recursion limit instead of removing the tool?** A depth limit is a
counter you have to thread through, test at every level, and explain to the
model. Removing `run_subagent` from the child's menu makes recursion
unrepresentable. Same argument as chapter 7: not offering a tool is a
guarantee; a rule about using it is a request.

**Why does the child share memory at all?** Because memory is the agent's
*identity*, not its working state: "I am Nanocode, and this user prefers X" is
exactly what a researcher should know. It is shared read-only — `save_memory` is
not in the child's menu — so the sharing cannot become a race.

**Why one-shot instead of a chat with the subagent?** Because a second turn needs
a session registry, an id the parent can address, and a way to explain to the
model when to use `send_to_subagent` rather than `run_subagent`. One-shot is the
90% case and the whole of this chapter; the registry is a good extension and a
bad default.

**Why keep `workflows.py` free of imports from this repository?** So the
patterns survive the codebase. They are four functions over a callable; the only
thing they know about Nanocode is that a subagent can be asked a question and
answers with a string. That is also why they can be tested with `lambda`.

## Try it

1. **Watch the ratio.** Run `demo_workflows.py fanout` and note the tool result's
   size against the three children's answers. Then add a fourth task and note
   that the parent's next request grows by one section, not by a conversation.
2. **Make it recurse.** Remove `"run_subagent"` from `SUBAGENT_BLOCKED_TOOLS` and
   ask a child to delegate. It will, and then a grandchild will, until the
   budgets stop you. Put the name back and notice that no other code changed.
3. **Share the sandbox.** In `_spawn_subagent`, pass `sandbox=self.sandbox`
   instead of `sub_sandbox`. Run the sandbox tests: the one asserting the parent
   is still armed fails, because `Agent.__init__` arms the child in PLAN mode.
   That test exists because this bug is easy and silent.
4. **Serialize the fan-out.** Set `agent.subagent_parallel = 1` in the demo and
   watch the barrier test fail while the demo still looks fine — the difference
   between "works" and "works concurrently".
5. **Break the barrier test on purpose.** Change `_spawn_many` to
   `[self._spawn_subagent(t) for t in tasks]`. `test_spawn_many_really_runs_at_
   the_same_time` hangs for five seconds and fails with three empty answers.
6. **Add a fifth pattern.** A "tournament" — fan out N attempts, then have a
   judge pick one — is `fan_out` plus one `spawn`. Add it to `workflows.py` with
   a test that uses a fake `spawn`, and see how little code it takes.
7. **Re-colour the fan-out.** Change `subagents.palette` in `ui.json` to
   `["red", "green", "blue"]` and run the demo again: `sub4` now shares `sub1`'s
   colour, and the labels are what keep them apart. Then try a palette of one —
   every child the same colour, which is what this chapter looked like before
   the palette existed.
8. **Turn a child into a writer.** Give `_spawn_subagent` a `mode="act"` and
   think about what else has to change: conflict handling, a per-child sandbox
   root, and a rule for who wins. This is the exercise that shows why the
   read-only default is a design decision and not a limitation.

## Checkpoint

<details>
<summary>Does a subagent run in a new process or thread by default?</summary>

Neither, when you call `run_subagent`: it runs on the **same thread**, one stack
frame deeper, inside `context.spawn`. Only `run_subagents` uses threads, and only
because several independent tasks are worth overlapping. A single subagent is
just a nested call — `parent → tool → spawn → child.handle_input → child loop`.

</details>

<details>
<summary>Why does the child get its own `Sandbox` rather than a reference to the parent's?</summary>

Because `Sandbox.arm(mode)` mutates the object, and `Agent.__init__` calls it.
A PLAN-mode child sharing the parent's sandbox would call `arm("plan")` on it,
silently disarming the ACT parent's write fence for the rest of the session.
`test_subagent_runs_in_plan_mode_with_a_fresh_sandbox_and_bus` asserts the
parent is still armed afterwards.

</details>

<details>
<summary>The parent model asks for a subagent, and the child model calls a tool. Which hooks fire, and on which bus?</summary>

On the parent's bus: `tool_call` for `run_subagent`, plus `subagent_start` before
the child runs and `subagent_end` after it returns. On the child's bus: its own
`before_think`, `after_think`, `tool_call` and `turn_end` — and that bus has no
listeners, because `_spawn_subagent` gives the child a fresh `Hooks()`. The
parent's conversation likewise gets exactly one `tool_result`.

</details>

<details>
<summary>Why is `plan_safe = True` right for a tool that starts another agent?</summary>

Because the child is read-only: it runs in PLAN mode, so its menu is `plan_safe`
tools only, and `write_plan` and `save_memory` are filtered out on top of that.
Delegating research in PLAN mode is safe *by construction*, not by permission —
there is no write tool for the child to misuse. An ACT-mode child would need a
different answer, and a different chapter.

</details>

<details>
<summary>Two fan-out tasks take 3s and 1s. How long does `_spawn_many` take, and in what order are the results?</summary>

About 3s, not 4s: with `workers >= 2` the calls overlap, because the time is
spent waiting on HTTP and the GIL is released during the wait. The results come
back in **task order** (`pool.map` preserves it), not completion order, so
`results[0]` is always the answer to `tasks[0]` — which is what `RunSubagents`
promises the model when it labels them "Subagent 1", "Subagent 2", …

</details>

<details>
<summary>Why remove `save_memory` from the child's tools instead of letting it save?</summary>

Because memory is shared, and it *is* the parent's system prompt. A child that
called `save_memory` would silently rewrite the instructions of the agent that
spawned it — including, in a fan-out, halfway through the parent's turn. Removing
the tool keeps memory a read-only input. If a child has something worth
remembering, it says so in its answer, and the parent decides.

</details>

<details>
<summary>What would break if the child shared the parent's `Hooks` object?</summary>

Everything that makes the trace readable. Every child `tool_call` would arrive as
if the parent had made it, `turn_start`/`turn_end` would nest unpredictably
(especially under threads), and any observer that counts or budgets by event —
`sounds.play` per `tool_call`, a future cost tracker — would attribute a child's
work to its parent. The two-event bridge exists so the parent's trace stays a
*summary* of delegation rather than a merge of two conversations.

</details>

<details>
<summary>Why is `max_iterations` an attribute now, when a module constant worked for fourteen chapters?</summary>

Because a constant cannot express "this agent gets less". Chapter 14's global
`MAX_ITERATIONS = 50` is right for the parent and wrong for a researcher sent to
grep one folder: a confused child would spend the parent's whole budget. Moving
it to `self.max_iterations` is a one-word change in the loop and the only
modification chapter 15 makes to `_agentic_loop()`.

</details>

## Extensions that teach the most

| Idea | Touch | What you learn |
|---|---|---|
| a session registry: `send_to_subagent` / `check_subagent` | `nanocode.py` + `tools.py` | why one-shot is the 90% case |
| a depth limit instead of a filtered menu | `_subagent_tools` | why "impossible" beats "forbidden" |
| a per-child token/cost budget reported by `subagent_end` | `hooks.py` + `nanocode.py` | delegation economics, measured |
| a `tournament` pattern (fan out, then judge) | `workflows.py` | composition of the four shapes |
| let a child *propose* a diff and have the parent apply it | `_spawn_subagent` + `WriteFile` | who should own the write |
| run children in processes (`ProcessPoolExecutor`) | `_spawn_many` | what "isolation" costs when it is real |
| stream a child's progress to the parent's UI | `ui.py` + `hooks.py` | observability across agents |

**Chapter 14 fenced what the agent may touch. Chapter 15 divides what it must
think about — and the division is one callable, four fresh objects and a filtered
menu. The loop never learned that it can recurse.**
