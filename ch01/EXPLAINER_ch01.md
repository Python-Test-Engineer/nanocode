# Chapter 1 — The event loop (there is no AI yet)

> **You are here:** nothing talks to a model. This chapter builds the *shape* every
> later chapter plugs into: read a line, hand it to an Agent, print what comes
> back, repeat until the user leaves.

That sounds trivial, and it is — which is exactly why it is chapter one. Every
agent you have ever used is this loop with more interesting things happening
inside step 2.

## The idea in one picture

```
        ┌──────────────────────────────────────────────┐
        │                 main() loop                  │
        │                                              │
        ▼                                              │
  ui.ask()  ──►  Agent.handle_input(text)  ──►  ui.answer(output)
   "❯ "              │                                   │
                     │ "/q" ?                            │
                     ├── yes ──► raise AgentStop ─────────┼──► exit
                     └── no  ──► return a string ─────────┘
```

Four moving parts, and only one of them will grow:

| Part | What it does | Does it change later? |
|---|---|---|
| `main()` | reads input, prints output | barely |
| `Agent` | turns input into output | **everything happens here** |
| `ui.py` | draws the prompt and the answer | grows a lot (colour, Markdown) |
| `ui.json` | the colours | grows a lot |

## What's new on disk

```
ch01/
  nanocode.py   AgentStop, Agent, main()      <- the whole chapter
  ui.py         Rich wrappers: banner, ask, answer
  ui.json       every colour, as data
  test_nanocode.py  the book's tests (4 of them)
```

`Agent` is deliberately empty of intelligence. It records nothing, remembers
nothing, and calls nothing:

```python
class Agent:
    """A coding agent that processes user input."""

    def __init__(self):
        pass

    def handle_input(self, user_input):
        if user_input.strip() == "/q":
            raise AgentStop()

        if not user_input.strip():
            return ""

        # Chapter 1 has no model behind the curtain. Returning the input proves
        # the plumbing works: something reads, something answers, something draws.
        return f"You said: {user_input}\n(Agent not yet connected)"
```

## Watch it run (frame by frame)

Each frame is one pass around the loop:

```
frame 1                          frame 2                     frame 3
┌─────────────────────┐          ┌────────────────────┐      ┌──────────────┐
│ ❯ hi                │          │ ❯ /q               │      │ Exiting...   │
│ You said: hi        │          │ (AgentStop raised) │      │              │
│ (Agent not ...)     │          │                    │      │              │
└─────────────────────┘          └────────────────────┘      └──────────────┘
```

The real run looks like this — note that the prompt shows no brain and no mode,
because this chapter has neither:

```
⚡ Nanocode v0.1
  type /q to quit
────────────────────────────────────────────────────────────────
❯ hi
You said: hi (Agent not yet connected)

❯ /q
Exiting...
```

## Why it is built this way

**Quitting is an exception, not a flag.** `/q` can be typed at a prompt deep
inside a future chapter, and the only code that cares is `main()`, which catches
`AgentStop` once. A boolean `running = False` would have to be threaded through
every layer.

**Empty input returns `""`, not a message.** `main()` only prints when there is
something to print, so pressing Enter does not produce a stray blank line.

**All printing goes through `ui.py`.** The book uses `print()` here. This version
calls `ui.answer(...)` so that later chapters can restyle output without touching
the loop — the loop should not know what a colour is.

## Try it

```bash
uv run ch01/nanocode.py
```

Then, in order:

1. Type `hello` and press Enter. Predict the exact output before you do.
2. Press Enter on an empty line. How many lines get printed? Why?
3. Type `/q hej` (with trailing text). Does it quit? Look at the `==` comparison
   in `handle_input` and explain what you see.
4. Open `ui.json`, change `banner.title`'s `style` to `"bold magenta"`, restart.
   You have just re-themed the app without editing Python.

## Checkpoint

<details>
<summary>Why does <code>handle_input</code> return a string instead of printing?</summary>

Because "produce the answer" and "draw the answer" are different jobs. Returning
a string means the agent can be tested without a terminal, and `main()` decides
how the answer appears. Every later chapter keeps this split: `Agent` returns,
`ui` renders.
</details>

<details>
<summary>What would break if <code>Agent</code> printed directly?</summary>

The tests. `test_nanocode.py` calls `handle_input` and asserts on the *return
value*; printed text would be invisible to them. It would also duplicate output
the moment a chapter wants to render Markdown instead of plain text.
</details>

**Next:** chapter 2 makes one real HTTP request to a model — still with no agent.
