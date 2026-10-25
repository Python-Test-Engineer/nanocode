# ch14 — Nanocode + a sandbox for ACT mode

Chapter 14 is chapter 13 with **one new module**: `sandbox.py`. ACT mode used to
mean "the agent may write anywhere the process can". Now it means "the agent may
write inside the folders you allowed", and a refusal is loud: a red **FORBIDDEN**
line and the Windows warning sound.

The agent loop, the brains, the tools' contracts and the UI are unchanged. The
write tools gained three lines each: check, then write.

| File | Holds | Depends on |
|------|-------|-----------|
| `llm.py` | Brains: `OpenRouter`, `Claude`, `DeepSeek`, `Ollama`, `Thought`, `ToolCall`, HTTP retry, dialect translation | `requests`, `dotenv`, `ui` |
| `tools.py` | `ReadFile`, `WriteFile`, `EditFile`, `WritePlan`, `ListFiles`, `SearchCodebase`, `SearchWeb`, `SaveMemory`, `RunCommand`, `ToolContext` (`guard`/`guard_command`), `tool_definitions`, `get_tool` | `ui`, `sandbox` (passed in) |
| `ui.py` | Everything printed: banner, prompt, thinking, tool lines, answers, errors, **`forbidden()`**, `/help` table | `rich`, `ui.json` |
| `ui.json` | Every colour, icon and label — including the FORBIDDEN badge | — |
| `hooks.py` | Lifecycle events (`session_start`, **`sandbox_denied`**, `turn_start`, `before_think`, `after_think`, `tool_call`, `turn_end`) + JSONL tracer | `ui` |
| `sounds.py` | Events → sound, plus **`alarm()`** — the one sound that is not opt-in | `winsound` (Windows) |
| `sounds.json` | Which sound for which event; `sandbox_denied` → Windows Exclamation | — |
| **`sandbox.py`** | **The policy: `Sandbox`, `SandboxViolation`, `write_targets()`, `install(hooks)`** | **`ui`, `sounds`** |
| **`sandbox.json`** | **Where writes are allowed (`roots`) and where never (`deny`). Data, like `ui.json`** | — |
| `nanocode.py` | `Memory`, `Agent` (the loop, now holding a `Sandbox`), `main()`; re-exports the old public names so `test_nanocode.py` runs unchanged | all of the above |

`nanocode_copy.py` is the untouched original from the book, kept for diffing.

## The fence in one table

| Question | Answer | Where |
|---|---|---|
| When is the fence on? | ACT mode only — PLAN has no write tools to police | `Sandbox.arm(mode)`, called by `Agent` |
| Where may it write? | `roots` from `sandbox.json`, default `["."]` (the folder the agent started in) | `sandbox.json` / `NANOCODE_SANDBOX_ROOTS` |
| What is never allowed? | `deny` subtrees (`.git`, `.env` by default), even inside a root | `sandbox.json` |
| How is "inside" decided? | `os.path.realpath` first (`..` and symlinks folded), then `os.path.commonpath` — never string matching | `sandbox._inside` |
| What happens on a refusal? | Nothing is written; the model gets an `Error: FORBIDDEN ...` string; the console prints FORBIDDEN; the alarm plays | `ToolContext.refuse` → `sandbox.install` |
| How do you turn it off? | `NANOCODE_SANDBOX=0`, or `"enabled": false` in `sandbox.json` | `sandbox.enabled()` |

## What chapter 14 changed

```
sandbox.py       new - the whole feature (see below)
sandbox.json     new - enabled, roots ["."], deny [".git", ".env"]
tools.py         ToolContext(sandbox=, hooks=) + guard()/guard_command();
                 write_file, edit_file, write_plan, run_command call them
nanocode.py      import sandbox as sandbox_policy; Agent holds a Sandbox and
                 arms it on every mode change; main() installs the alarm
hooks.py         EVENTS gains "sandbox_denied"; log_to_console prints it
sounds.py        alarm() - plays sandbox_denied regardless of NANOCODE_SOUND
sounds.json      sandbox_denied -> C:\Windows\Media\Windows Exclamation.wav
ui.py            forbidden(path, reason, roots) + sandbox_scope(roots)
ui.json          the FORBIDDEN badge + the sandbox_denied hook colour
test_nanocode.py the ch13 suite + 24 sandbox tests (57 total)
```

## Why this is chapter 7 again, one level down

Chapter 7 said: telling a model "do not write" is a request; *not giving it
`write_file`* is a guarantee, and that is why PLAN mode is safe by construction.

The same argument applies to **where**. "Only edit files in this project" in a
system prompt is a request. A `check()` that runs before `open(path, "w")` is a
guarantee:

```python
blocked = context.guard(path, self.name)   # tools.py
if blocked:
    return blocked                          # nothing touched the disk
```

Three lines per write tool, no change to the loop, no new tool signature. The
policy itself is one class:

```python
def check(self, path, tool=""):
    if not self.armed:                       # PLAN mode, or the fence is off
        return None
    resolved = _resolve(path)                # realpath: '..' and symlinks folded
    for denied in self.deny:                 # deny beats root
        if _inside(resolved, denied):
            return SandboxViolation(path, resolved, self.roots, "inside a denied path", tool)
    for root in self.roots:
        if _inside(resolved, root):
            return None
    return SandboxViolation(path, resolved, self.roots, "outside the writable roots", tool)
```

Two decisions in that snippet are the lesson:

* **resolve, then compare.** `project/../../Windows/System32/x.dll` is judged as
  the path it *becomes*. A substring test for `..` is a bug generator; a prefix
  test on real paths is not.
* **deny beats root.** A path can be inside a root and still forbidden, which is
  why `.git` and `.env` need no special casing anywhere else in the codebase.

## The alarm rides the hook seam

A refused write is not a log line: it is the one moment a human needs to know
about *now*. So it is an event, and the chapter 13 seam carries it:

```
tools.py  context.refuse(violation)
              │
              └─► hooks.emit("sandbox_denied", tool=, path=, resolved=, reason=, roots=)
                        │
                        └─► sandbox.install(agent.hooks)
                                  ├─► ui.forbidden(...)        ⛔ FORBIDDEN  C:\Windows\x (outside ...)
                                  └─► sounds.alarm(...)        ♪ Windows Exclamation.wav
```

`sounds.alarm()` deliberately ignores `NANOCODE_SOUND`: ordinary sounds are
decoration and opt-in (`"mode": "off"` ships as the default), but a blocked write
is an alarm. `NANOCODE_SOUND_ALARM=0` silences alarms specifically, which keeps
the escape hatch deliberate instead of a side effect of a config typo.
`sounds.install()` skips `sandbox_denied` so the alarm never plays twice.

## It is not a container

The file tools are fenced strictly: every path they touch is checked.

`run_command` gets a best-effort check that reads the obvious write targets out
of the command line — redirects (`>`, `>>`) and the arguments of `rm`, `cp`,
`mv`, `mkdir`, `tee` and friends:

```python
sandbox.write_targets('echo hi > "C:\\Windows\\x.txt"')   # ['C:\\Windows\\x.txt']
sandbox.write_targets("rm -rf ../secrets")               # ['../secrets']
sandbox.write_targets("pytest -q")                        # []
```

A shell can do anything a shell can do, and this file says so out loud rather
than pretending otherwise. If you need a real boundary, that is a container, a
VM or an OS user account — not a Python function. Fencing the tools where the
agent's *intent is explicit* is the cheap 90%, and knowing which 10% is missing
is the point of the chapter.

## Run

From the repo root:

```bash
NANOCODE_SOUND=media uv run ch14/nanocode.py --act    # ACT: sandbox armed, writes fenced
uv run ch14/nanocode.py --act                          # silent, same fence
NANOCODE_SANDBOX_ROOTS=".;C:\\tmp\\scratch" uv run ch14/nanocode.py --act
NANOCODE_SANDBOX=0 uv run ch14/nanocode.py --act       # fence off (deliberate)
```

Then try, in ACT mode:

```
write a file at C:\Windows\Temp\proof.txt
```

You get the coloured `⟡ hook:sandbox_denied` line, the red `⛔ FORBIDDEN …`
line, the warning sound, and the model is told exactly what it may do instead.

`.env` at the repo root supplies:

```
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL="deepseek-v4.1-flash-1017"
NANOCODE_BRAIN="openrouter"        # openrouter | claude | deepseek | ollama
NANOCODE_SANDBOX_ROOTS="."         # optional: widen the fence (os.pathsep-separated)
NANOCODE_SANDBOX=1                 # 0 turns the fence off
NANOCODE_SOUND=media               # media | beep | off  (unset follows sounds.json)
NANOCODE_SOUND_ALARM=1             # 0 silences the FORBIDDEN alarm only
```

## Tests

```bash
uv run pytest                   # all chapters from the repo root
cd ch14 && uv run pytest -q     # 57 passed
```

The suite is the book's original plus chapter 13's sound tests plus this
chapter's sandbox tests: inside writes, outside writes, `..` escapes, `deny`
beating `roots`, PLAN disarmed / ACT armed, the env overrides, the shipped
`sandbox.json`, the hook event, the FORBIDDEN line on a fake console, the alarm
playing while ordinary sounds are off, and one end-to-end turn where the model
asks for a forbidden path, gets refused, and the loop carries on.

`conftest.py` binds `sandbox` alongside the other per-chapter modules, so the
root `uv run pytest` cannot leak one chapter's policy into another.

## Porting to another chapter

Already done for ch01-ch13; `../REFACTOR.md` has the per-chapter table and the
list of deliberate deviations. Chapter 14's only structural change is one more
object on `ToolContext` — every older chapter's tools keep working because
`ToolContext()` still defaults `sandbox=None`, which means "no policy".
