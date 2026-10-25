# Chapter 14 — A sandbox for ACT mode

> **You are here:** chapter 7 made PLAN mode safe by *construction* — the write
> tools simply are not in the menu. ACT mode handed them all back, and with them
> the whole disk. This chapter draws the same kind of guarantee one level down:
> the tools exist, but each one asks a policy *where* before it writes.

Chapter 7's lesson was that a prompt is a request and a missing tool is a
guarantee. This chapter applies it to a second question — not "may the agent
write?" but "**where**?" — and the answer is decided by a `check()` that runs
before `open(path, "w")`, not by a sentence in the system prompt.

```
PLAN mode   no write tools at all              (chapter 7)
ACT mode    write tools, fenced by sandbox.py  (chapter 14)
```

## The idea in one picture

```
                    ACT mode only
   ┌──────────────────────────────────────────────────────────────┐
   │  model: write_file("C:\\Windows\\Temp\\proof.txt", ...)      │
   └───────────────────────────────┬──────────────────────────────┘
                                   ▼
                         tools.WriteFile.execute
                                   │
                    context.guard(path, "write_file")
                                   ▼
                         sandbox.Sandbox.check
                     resolve ─► deny? ─► root prefix test
                                   │
              ┌────────────────────┴─────────────────────┐
              ▼ allowed                                  ▼ refused
        open(path, "w")                    hooks.emit("sandbox_denied")
        "Successfully wrote …"                        │
                                          ┌───────────┴────────────┐
                                          ▼                        ▼
                                   ui.forbidden            sounds.alarm
                                 ⛔ FORBIDDEN …        ♪ Windows Exclamation
                                          │
                                          ▼
                        tool returns "Error: FORBIDDEN … "
                        (the model reads it; the loop continues)
```

Two outcomes, two channels. The refusal never raises: it is an error *string*
like every other tool error, which is what lets the agent recover and try a path
inside the fence instead of ending the turn.

## What's new on disk

| File | Change | Why this file |
|---|---|---|
| `sandbox.py` | **new** — `Sandbox`, `SandboxViolation`, `write_targets()`, `install(hooks)` | the policy is one object with one question to answer |
| `sandbox.json` | **new** — `enabled`, `roots`, `deny` | the fence's shape is data, like `ui.json` and `sounds.json` |
| `tools.py` | `ToolContext` gains `sandbox`/`hooks` and `guard()`/`guard_command()`; the four writing tools call them | tools are the only place that knows a write is about to happen |
| `nanocode.py` | holds a `Sandbox`, arms it per mode, installs the alarm | one owner for "which mode are we in" |
| `hooks.py` | `sandbox_denied` joins `EVENTS`; one console line for it | the refusal is announced, not printed by the tool |
| `ui.py` | `forbidden()` and `sandbox_scope()` | every byte a human sees still goes through ui |
| `ui.json` | the FORBIDDEN badge | taste stays out of Python |
| `sounds.py` | `alarm()` | one sound that is not opt-in |
| `sounds.json` | `sandbox_denied` → Windows Exclamation | the alarm is data too |
| `test_nanocode.py` | the ch13 suite + 29 sandbox/read-bound tests | the fence is testable, which is why it can be trusted |

The agent loop is untouched. That is the measure of a well-placed boundary: if
`_agentic_loop()` had to learn about paths, the boundary would be in the wrong
place.

## The code

### 1. The policy is one class

```python
class Sandbox:
    def __init__(self, roots=None, enabled=None, deny=None, cfg=None):
        cfg = config() if cfg is None else cfg
        self.enabled = enabled(cfg) if enabled is None else bool(enabled)
        self.roots = tuple(_resolve(r) for r in (roots or roots_from_config(cfg)))
        self.deny = tuple(_resolve(d) for d in (deny or cfg.get("deny") or []))
        self.active = True

    def arm(self, mode):
        """Police writes only when the agent can write."""
        self.active = str(mode).strip().lower() == "act"
        return self.armed

    @property
    def armed(self):
        return self.enabled and self.active
```

`enabled` is the operator's switch (`sandbox.json`, `NANOCODE_SANDBOX`).
`active` is the *mode* switch, and `Agent` flips it: PLAN mode has no write tools
to police, so the fence is disarmed there and armed in ACT.

### 2. Resolve, then compare

```python
def _resolve(path):
    candidate = Path(os.path.expanduser(str(path)))
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return Path(os.path.realpath(candidate))          # '..' and symlinks folded

def _inside(path, root):
    path, root = os.path.normcase(str(path)), os.path.normcase(str(root))
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False                                  # different drives
```

The order matters more than the code. `realpath` first means
`project/../../Windows/System32/x.dll` is judged as the absolute path it
*becomes*, not the string it started as. `commonpath` then answers "is this below
that" correctly, including `C:\proj` vs `C:\proj-other` — a case `startswith`
gets wrong. And `normcase` makes it case-insensitive on Windows, which is what
the filesystem already is.

### 3. Deny beats root

```python
def check(self, path, tool=""):
    if not self.armed:
        return None
    resolved = _resolve(path)
    for denied in self.deny:
        if _inside(resolved, denied):
            return SandboxViolation(path, resolved, self.roots, "inside a denied path", tool)
    for root in self.roots:
        if _inside(resolved, root):
            return None
    return SandboxViolation(path, resolved, self.roots, "outside the writable roots", tool)
```

A path can be inside a root and still forbidden. Putting that rule here — once,
before the root test — is why `.git` and `.env` need no special casing anywhere
else in the codebase.

### 4. Three lines per write tool

```python
def execute(self, context, path, content):
    ui.tool_action("write_file", path)
    blocked = context.guard(path, self.name)
    if blocked:
        return blocked
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Successfully wrote {len(content)} characters to {path}"
```

`guard()` returns either `None` (carry on) or the `FORBIDDEN` error string, which
the tool returns exactly as it would return "File not found". The model sees a
normal tool error and can act on it. Nothing raises, nothing ends the turn.

`write_plan` checks its fixed `PLAN.md` path too — a configured `roots` may point
somewhere other than the working directory, and a hard-coded path is not an
exception.

### 5. The refusal is an event

```python
def refuse(self, violation, sandbox=None):
    roots = tuple(sandbox.roots) if sandbox is not None else ()
    if self.hooks is not None:
        self.hooks.emit("sandbox_denied", tool=violation.tool, path=violation.path,
                        resolved=violation.resolved, reason=violation.reason, roots=roots)
    else:
        ui.forbidden(violation.path, violation.reason, roots=roots)
        sounds.alarm("sandbox_denied")
```

The tool does not print, and it does not beep. It *announces*. `sandbox.install`
is the listener:

```python
def on_sandbox_denied(tool="", path="", reason="", roots=(), **_payload):
    ui.forbidden(path or "?", reason, roots=roots)
    sounds.alarm(DENIED_EVENT, cfg)
```

Two lines, two channels — the red badge and the warning sound — and neither the
tool nor the policy knows what a `FORBIDDEN` line looks like.

### 6. The alarm is not decoration

```python
def alarm(event="sandbox_denied", cfg=None):
    if not available() or cfg.get("muted"):
        return False
    if os.getenv("NANOCODE_SOUND_ALARM", "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    return _play_spec(spec_for(event, cfg), "media")
```

Chapter 13 shipped `"mode": "off"` on purpose: sound is decoration and a library
that beeps is a library people turn off. A *refused write* is not decoration, so
`alarm()` ignores the opt-in and plays anyway — while still respecting `muted`,
the platform, and its own explicit `NANOCODE_SOUND_ALARM=0`. `sounds.install()`
skips `sandbox_denied`, so the alarm never plays twice.

## Watch it run

```
[openrouter:act] ❯ write a file at C:\Windows\Temp\proof.txt

  ↑ Thinking...
  ⟡ hook:before_think  4 message(s) queued
  ⟡ hook:after_think   wants write_file
  → Writing C:\Windows\Temp\proof.txt
  ⟡ hook:sandbox_denied  write_file → C:\Windows\Temp\proof.txt
  ⛔ FORBIDDEN  C:\Windows\Temp\proof.txt  (outside the writable roots)  allowed: C:\Users\me\project
  ♪ (Windows Exclamation.wav)
  ⟡ hook:tool_call  write_file(path=C:\Windows\Temp\proof…) → 244 chars back
  ↑ Thinking...
  ⟡ hook:after_think   wants write_file
  → Writing proof.txt
  ⟡ hook:tool_call  write_file(path=proof.txt) → 44 chars back
  ⟡ hook:turn_end  answer 96 chars

The first path is outside the sandbox, so I wrote `proof.txt` in the project instead.
```

Read the two tool calls: the refusal did not stop the turn, it *steered* it. That
is the difference between a fence and a crash.

## Why it is built this way

**Why not just prompt it?** Because "only write in this folder" is a request, and
requests are for models that always comply. The system prompt still states the
rule (`_build_system_prompt` adds "writes allowed in …"), but only to save a
wasted round trip. `check()` is what makes it true.

**Why realpath instead of a `..` ban?** A string test is a bug generator: it
misses symlinks, misses `C:\Windows` vs `C:/Windows`, and blocks legitimate names
like `my..notes.txt`. Resolve once, compare once.

**Why a class instead of a function?** Because the fence has *state* — which mode
we are in, which roots, which denials — and something has to own it. `Agent` owns
one instance and shares it with the hook listener; tests construct one in a
tempdir.

**Why is `run_command` only a speed bump?** Because a shell is a general-purpose
escape hatch: `python -c "open(...)"`, encoded paths, child processes. A Python
function cannot win that game, and pretending otherwise would be worse than the
honest best-effort check. File tools are fenced strictly; the shell is fenced
where the *intent is visible* (`>`, `>>`, `rm`, `cp`, `mv`, `mkdir`, `tee`), and
`sandbox.py` says so in its own docstring.

**Why are *reads* bounded when only writes are fenced?** Because the first real
run of this chapter hung: refused at `C:\hello.py`, the model asked for
`list_files C:\`, and `os.walk` cheerfully started on the whole drive. A fence
around writes does not make a tree walk cheap, so `walk_bounded()` gives every
walk a ceiling (2000 entries, 10 s, system/cache directories pruned) and makes a
truncated result *say* it is truncated. The model gets an answer in under a
second instead of a hang, which is the difference between a boundary and an
outage.

**Why does the tool return a string instead of raising?** Same reason as every
other error in this book: a traceback ends the turn, an error message continues
it. The model reads "FORBIDDEN, writable roots: …" and tries again inside the
fence.

## Try it

1. **Widen the fence.** Add `".."` to `roots` in `sandbox.json`, restart, and
   watch the same request … still fail for `C:\Windows` but now succeed for the
   parent folder. Then put `NANOCODE_SANDBOX_ROOTS` in `.env` and notice it wins.
2. **Add a denial.** Put `"secrets"` in `deny` and ask the agent to write
   `secrets/key.txt`. The path is inside the root and still refused — deny beats
   root.
3. **Break the alarm.** Set `NANOCODE_SOUND_ALARM=0`. The FORBIDDEN line stays,
   the sound goes. Two channels, independently configurable.
4. **Turn it off.** `NANOCODE_SANDBOX=0 uv run nanocode.py --act` and prove the
   refusal was the sandbox's, not the filesystem's.
5. **Fence a different tool.** `save_memory` writes to `.nanocode/memory.md`.
   Add `context.guard` to `Memory.save()`'s caller and decide which event a
   refusal there should emit.

## Checkpoint

<details>
<summary>Why does the sandbox only arm in ACT mode, when PLAN cannot write anyway?</summary>

Because a fence that is always on has to be right about every path in every mode,
while a fence that follows the mode only has to be right where writes are
possible. Disarming it in PLAN is not a hole — PLAN's guarantee is the tool menu
(chapter 7) — it is one less thing to reason about. It also keeps `write_plan`,
which *is* plan-safe, from turning into a special case.

</details>

<details>
<summary>What would `check("../project/x.py")` return, and why is that safe?</summary>

Whatever the resolved absolute path deserves. Relative paths are joined to the
current directory and then folded by `realpath`, so `..` is arithmetic, not
syntax. If the result is under a root, it is allowed — including when the model
typed a path that merely *looked* like an escape but never left the root.

</details>

<details>
<summary>The model ignores the FORBIDDEN error and retries the same path. What happens?</summary>

Nothing changes: the guard runs again, the alarm fires again, and after
`MAX_ITERATIONS` the loop stops with "(Stopped: too many iterations)". The fence
is not a rate limiter — it is a boundary — so a model looping against it costs
tokens, not files. Adding a retry counter is a legitimate extension, and it
belongs in the agent, not here.

</details>

<details>
<summary>Why is `sandbox_denied` an event instead of a direct `ui.forbidden()` call in the tool?</summary>

Because the tool would then own taste (colour, wording) and the alarm (sound),
and both already have owners. It is the same reason chapter 13's sounds listen to
`tool_call` instead of every tool calling `winsound`: one seam, many observers.
This chapter's observer happens to be the newest one, and it can be replaced
without touching a single tool.

</details>

## Extensions that teach the most

| Idea | Touch | What you learn |
|---|---|---|
| a `/sandbox` command showing roots and denials | `nanocode.py` + `ui.py` | agent operations vs. conversation |
| a read-only fence (paths the agent may *read*) | `sandbox.py` + `ReadFile` | capability is not one dimension |
| log refusals to the trace and count them per session | `hooks.py` trace, already there | observability you get for free |
| refuse a `run_command` containing `..` outside roots | `sandbox.write_targets` | where best-effort ends |
| ask the human to approve a denied write, once | `sandbox.install` + `ui.ask` | hooks observe; approvals need steering |
| run the whole agent in a container | outside the code | the 10% a Python fence cannot do |

**Chapter 7 drew the fence around *whether*. Chapter 14 draws it around *where*,
and the two are enforced the same way: by removing the possibility, not by
asking nicely.**
