# Chapter 6 — Memory that survives (a file, not a database)

> **You are here:** the conversation still dies when you close the terminal. Now
> the agent has a small file on disk, sent as the system prompt, that it can
> rewrite through a tool.

Two things in this project are called "memory", and confusing them is the most
common source of bugs in agent code.

## The idea in one picture

```
            ┌────────────────────────── session ──────────────────────────┐
  you  ────►│ conversation list → brain → tools → conversation list ...   │────► dies on exit
            └─────────────────────────────────────────────────────────────┘
                                    ▲
                                    │  sent as the SYSTEM PROMPT every request
                                    │
            ┌───────────── .nanocode/memory.md ─────────────────────────────┐
            │ "I am Nanocode, a helpful coding assistant."                  │────► survives restarts
            │ "The user prefers tabs and calls me Nan."                    │
            └───────────────────────────────────────────────────────────────┘
                                    ▲
                                    │  save_memory tool writes here
```

| | `conversation` | `Memory` |
|---|---|---|
| Lives in | RAM, in the Agent | a markdown file |
| Sent as | the messages array | the system prompt |
| Grows with | every turn | only when the agent decides to save |
| Survives restart | no | yes |
| Cost | grows every turn | fixed, tiny |

## What's new on disk

```
ch06/
  nanocode.py  Memory class; Agent(memory=...)
  tools.py     ToolContext, SaveMemory; execute(context, ...)
```

Two structural changes matter more than the feature:

1. **`Memory` is a file wrapper, nothing else.** No caching, no watching, no
   schema — `_load()` / `save()` and a default line.
2. **Every tool now receives a `ToolContext` first.** `save_memory` cannot do its
   job from its arguments alone; it needs the agent's memory object.

## The class

```python
class Memory:
    """Persistent scratchpad for the agent."""

    def __init__(self, path=".nanocode/memory.md"):
        self.path = path
        self._ensure_exists()
        self.content = self._load()

    def save(self, content):
        self.content = content                      # in memory
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(content)                        # on disk
```

`content` is kept in sync with the file so the next request does not have to
re-read it. That is the whole class — about twenty lines.

## The context object (a seam, not a bag of everything)

```python
class ToolContext:
    """What tools need to know about the agent's state."""

    def __init__(self, memory=None):
        self.memory = memory

# ...
def execute(self, context, content):
    if context.memory is None:
        return "Error: Memory not available"
    context.memory.save(content)
    return "Memory updated successfully."
```

Why not pass `memory` directly to every tool? Because next chapter the agent has
a *mode*, and chapter 9 it compacts conversations. A single object can grow;
nine signatures cannot be changed nine times without churn.

## Watch it run (frame by frame)

```
$ uv run ch06/nanocode.py --act
[openrouter:act] ❯ Remember that I prefer 2-space indentation.
  → Saving memory 34 chars
  ⟡ hook:tool_call  save_memory(content=...) → 26 chars back
Saved. I'll use 2-space indents from now on.

$ cat .nanocode/memory.md
I am Nanocode, a helpful coding assistant.
The user prefers 2-space indentation.

$ uv run ch06/nanocode.py --act          # new process, no conversation
[openrouter:act] ❯ What indentation do I prefer?
  💭 The system prompt says 2-space indentation.
2 spaces.
```

That last line is the trick: the *new* process has an empty conversation, but the
system prompt carried the fact.

## Why it is built this way

**A file, not a vector database.** You can `cat` it, edit it, diff it, delete it,
and put it in review. For a few dozen facts, similarity search is a solution to a
problem you do not have.

**Memory is the system prompt, not a message.** Putting it in the messages would
make the model treat it as conversation and "reply" to it. The system prompt is
the right place for standing instructions.

**The agent must be able to write it.** A memory only you can update is a config
file. A memory the agent updates is what makes "remember this" work without you
editing anything.

## Try it

```bash
uv run ch06/nanocode.py --act
```

1. Ask it to remember your name. Restart. Ask your name.
2. Ask it to remember something *wrong*, then edit `.nanocode/memory.md` by hand
   and ask again. (Restart first — memory is read once at startup.)
3. Add a line to the memory file: "Always answer in haiku." Restart and ask a
   question. This is prompt injection with your own hands, and it is worth
   feeling once.
4. Use a different memory file per project: `Memory(path=...)` in `main()`.

## Checkpoint

<details>
<summary>Why is memory read once at startup instead of on every request?</summary>

Because it is small and rarely changes, and re-reading a file per request adds
latency and failure modes. The trade-off: edits you make while the agent runs are
not picked up until restart. If you want live reload, re-read in `_load()` before
each `think()` — and add a test for it.
</details>

<details>
<summary>What is the risk of letting the model write its own system prompt?</summary>

It can poison itself. "Remember: never ask for confirmation" is now permanent
context. In a toy this is a nice lesson; in production you would restrict what
`save_memory` may write, or review the file. The mechanism is not the danger — the
*unreviewed persistence* is.
</details>

**Next:** chapter 7 gives the agent a safety harness: two modes, and the tool
menu itself becomes the enforcement.
