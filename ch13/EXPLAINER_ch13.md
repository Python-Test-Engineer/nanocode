# Chapter 13 — Sound (the agent's hooks you can hear)

> **You are here:** the loop already announces itself. Chapter 12 printed those
> announcements; this chapter *plays* them. Nothing in the agent loop changes —
> only what listens to it.

Chapter 12 ended with a claim: hooks exist because an agent you cannot see is an
agent you cannot debug. This chapter cashes that claim in. A hook is a **seam**,
not a feature — anything that cares can listen at it. So the same events the
console prints become events a speaker plays, and the proof that the seam is real
is that adding sound touches exactly one new file.

## The whole chapter, in one function

```python
def install(hooks, cfg=None):
    cfg = cfg if cfg is not None else config()
    for event in cfg.get("sounds", {}):
        def make_handler(name):
            def handler(**_payload):
                play(name, cfg)
            return handler
        hooks.on(event, make_handler(event))
    return hooks
```

Register a sound per event; hear the loop. `nanocode.py` calls it once:

```python
install(agent.hooks)      # chapter 12: print the events
sounds.install(agent.hooks)   # chapter 13: play them
```

The agent does not know either one exists.

## Why sound at all

Hooks are what make the loop observable. Printing is the cheap version of that —
and it is useless the moment you leave the terminal. You alt-tab to your editor,
the agent runs in a window behind something else, and the one question you always
have ("is it still working, or did it hang?") has no answer you can perceive.

Sound answers it from across the room:

```
session_start ─► ♪ tada         the session is up
turn_start    ─► ♪ ding         your turn is being handled
tool_call     ─► ♪ chimes       something is being read/written/run right now
turn_end      ─► ♪ notify       the answer is ready
```

The startup sound is the first one, and it is the point of the chapter: before
you type anything, the first hook fires and you *hear* the agent come alive.

## What was added (and what was not)

| File | Change |
|------|--------|
| `sounds.py` | **new** — hooks → sound, on Windows, via `winsound` |
| `sounds.json` | **new** — which sound for which event. Data, like `ui.json` |
| `hooks.py` | one new event, `session_start`; one new console line for it |
| `nanocode.py` | `import sounds`, `sounds.install(agent.hooks)`, one `emit("session_start")` |
| `ui.json` | a colour for the `session_start` hook line |
| `test_nanocode.py` | the ch12 suite, plus twelve sound tests |

Everything else — `llm.py`, `tools.py`, the agent loop, the providers — is
untouched. That is the lesson: an observability feature that required editing the
loop would not have been an observability feature.

## A new event: `session_start`

Every hook event so far belonged to a *turn* (`turn_start` … `turn_end`). The
session beginning is not a turn, so chapter 13 adds one more to `hooks.EVENTS`:

```python
EVENTS = ("session_start", "turn_start", "before_think", "after_think", "tool_call", "turn_end")
```

and `main()` emits it once, right after the banner and before the first prompt:

```python
agent.hooks.emit("session_start", brain=brain_name, model=..., mode=mode)
```

Adding an event is safe for old code by construction: `log_to_console` handlers
each absorb unknown fields with `**_`, so a chapter-12 listener still works.

## Two ways to make a noise on Windows

`winsound` is the whole platform story — and it only exists on Windows, which is
why `sounds.py` is silent everywhere else rather than pretending otherwise.

```python
winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)  # "media"
winsound.Beep(frequency, milliseconds)                                                        # "beep"
```

* **media** plays a real WAV from `C:\Windows\Media\` (`tada.wav`, `ding.wav`,
  `chimes.wav`, `notify.wav` …). `SND_ASYNC` matters: the sound starts and
  returns, so the agent is never blocked by audio. `SND_NODEFAULT` stops Windows
  from substituting the system ding when a file is missing.
* **beep** is a pure tone straight from the speaker. Ugly, but it survives over
  Remote Desktop, inside a VM, and anywhere the WAVs are not — which is exactly
  where "media" goes quiet.

## Graceful degradation is the safety story

Sound is a nicety, so it is never allowed to be a failure mode:

1. not on Windows → do nothing (`available()` is False);
2. the WAV is missing → fall back to the tone for that event;
3. `winsound` raises (no audio device, no console) → swallow it;
4. the hook itself raises → `hooks.py` already reports and skips it.

Four levels deep, and the agent loop never notices any of them. The same
principle as "tools return strings, never exceptions": a peripheral must not be
able to end a turn.

## Configuration: a sound is data

`sounds.json` sits next to `sounds.py`, the way `ui.json` sits next to `ui.py`.
Add an event, point it at a WAV, restart — no Python.

```json
{
  "mode": "off",
  "sounds": {
    "session_start": { "label": "start", "file": "C:\\Windows\\Media\\tada.wav",
                       "beep": [[880, 120], [1174, 120], [1568, 200]] },
    "turn_start":    { "label": "loop",  "file": "C:\\Windows\\Media\\ding.wav",  "beep": [[740, 90]] },
    "turn_end":      { "label": "done",  "file": "C:\\Windows\\Media\\Windows Notify.wav",
                       "beep": [[660, 90], [440, 140]] }
  }
}
```

`"mode": "off"` is the shipped default on purpose: **sound is opt-in**. Nothing
makes a noise until you ask for it — a library that beeps is a library people
turn off.

The three knobs in `.env` (`.env` wins over `sounds.json`):

```
NANOCODE_SOUND=media                    # media | beep | off  (unset follows sounds.json)
NANOCODE_SOUND_START=<path.wav>         # override the session_start sound
NANOCODE_SOUND_LOOP=<path.wav>          # override the turn_start sound
NANOCODE_SOUND_DONE=<path.wav>          # override the turn_end sound
```

`START` / `LOOP` / `DONE` are the human names for the three moments worth
hearing: the session starts (the Windows **tada**), a turn begins, a turn ends.
The other events (`tool_call`) simply have no env override — edit the JSON.

## Run it

```bash
cd ch13
NANOCODE_SOUND=media uv run nanocode.py          # start in PLAN mode; you hear the tada
NANOCODE_SOUND=media uv run nanocode.py --act    # writes enabled
NANOCODE_SOUND=beep  uv run nanocode.py          # a keyboard, no WAVs needed
uv run nanocode.py                               # NANOCODE_SOUND unset -> silent
```

With sound on, a single turn is now a small piece of music: `ding` when you
submit, `chimes` on each tool call, `notify` when the answer lands — the audited
version of the chapter-12 diagram.

## Checkpoint

<details>
<summary>Why is `session_start` a new event instead of reusing `turn_start`?</summary>

Because the session beginning is not a turn, and an event should carry only what
it promises. If the startup sound rode on `turn_start`, every listener that counts
turns would be wrong by one, and no listener could fire a *startup-only* action
without also firing on every turn. A new event costs one tuple entry and keeps
every existing handler honest — the rules in `hooks.py` add fields freely, but
each event still means exactly one thing.
</details>

<details>
<summary>Why fall back to a beep when the WAV is missing, instead of warning?</summary>

Because the fallback is what makes the feature *trustworthy*. A warning line is
seen only by someone watching the console — the same person who would have heard
the sound anyway. Degrading to a tone means the signal arrives on the channel you
chose, even on a machine that never had `tada.wav`. Predictable behaviour beats a
helpful message here.
</details>

<details>
<summary>Where would you add a sound for a *failed* turn?</summary>

Not in `sounds.py` — in the hook that knows about failure. The loop already
reports errors to `ui` (`ui.error`); the seam-specific way is to emit an event
(say `turn_error`) from the `except` in `handle_input` and add a `turn_error`
entry to `sounds.json`. The sound engine needs no new code at all — that is the
sign the seam is in the right place.
</details>

## Extensions that teach the most

Each is a small change to one file — the same measure chapter 12 used.

| Idea | Touch | What you learn |
|---|---|---|
| a distinct sound per tool (`tool_call.name`) | `sounds.py` + `sounds.json` | event payload as a lookup key |
| volume / mute toggle from a `/sound` command | `nanocode.py` + `sounds.py` | agent operations vs. conversation |
| speak the answer with SAPI (`win32com`) | `sounds.py` | the seam is not only for beeps |
| play *only* when the terminal is unfocused | `sounds.py` | observability that knows context |
| per-event sound for `before_think` | `sounds.json` only | how far data-not-code goes |

**You are done with the loop — now you are decorating the seam.** Point it at
something other than sound and the same four lines wire up anything: a
notification toast, a log to a second screen, a status LED. That is what a hook
buys you.
