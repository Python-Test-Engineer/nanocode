# Chapter 9 — Closing the loop (run it, read the error, fix it)

> **You are here:** the agent can now execute commands and make surgical edits. The
> feedback loop closes: write → run → read the traceback → edit → run again. And
> the conversation learns to forget, before it overflows.

This is the chapter that makes the agent feel competent. It is also the chapter
with the two most important engineering details in the whole project: **the
traceback is data**, and **context is finite**.

## The idea in one picture

```
        ┌──────────────────────────────────────────────────────────────┐
        │                                                              │
        ▼                                                              │
   write_file / edit_file ──► run_command ──► STDOUT / STDERR ──────────┤
        ▲                                          │                   │
        │                                          ▼                   │
        └──────────── edit_file(path, old, new) ◄── model reads the error
                                                   and proposes a fix
```

And underneath it, a second loop nobody sees until it fires:

```
  tokens used > 75% of window ──► summarise history ──► replace it with the summary
```

## What's new on disk

```
ch09/
  tools.py     EditFile, RunCommand
  llm.py       token accounting (usage.input_tokens -> brain.last_input_tokens)
  nanocode.py  compaction: _compact_conversation(), plus the 75% check in the loop
```

| New thing | Why it exists |
|---|---|
| `edit_file(old_text, new_text)` | change one snippet without rewriting the file |
| `run_command(command)` | the agent's only source of ground truth |
| `brain.last_input_tokens` | how full the context is, straight from the provider |
| `_compact_conversation()` | stay inside the window instead of getting a 400 |

## `edit_file`: exact, once, or refuse

```python
with open(path, "r", encoding="utf-8") as f:
    content = f.read()
# Exact match, replaced ONCE. Not a regex, not fuzzy: if the model quotes text
# that is not there, the honest answer is an error it can read, not a guessed edit.
if old_text not in content:
    return f"Error: Could not find the specified text in {path}"
new_content = content.replace(old_text, new_text, 1)
```

Three properties worth naming:

- **exact** — no fuzzy matching, so a failed edit is visible rather than silent
- **once** (`count=1`) — repeated snippets do not all change at once
- **refuses loudly** — the model gets a message it can act on ("text not found"),
  then usually reads the file again and retries with the right quote

## `run_command`: stdout, stderr, timeout, and no exceptions

```python
result = subprocess.run(
    command,
    shell=True,            # the model writes shell syntax: "python x.py && pytest"
    capture_output=True,   # keep output OUT of the console, IN the tool result
    text=True,
    timeout=int(os.environ.get("NANOCODE_TIMEOUT", "30")),   # a hung command must not hang the agent
    cwd=os.getcwd(),
)

output = ""
if result.stdout: output += f"STDOUT:\n{result.stdout}\n"
if result.stderr: output += f"STDERR:\n{result.stderr}\n"
if not output:    output = "(No output)"
```

`capture_output=True` is the key: the agent needs the text, and your terminal does
not. A non-zero exit code is **not** an error here — it is evidence. The model
reads `STDERR`, edits the file, and runs again.

## Compaction: budgeting the context window

```python
# in the loop, after each reply
if self.brain.last_input_tokens > self.brain.context_limit * 0.75:
    self._compact_conversation()
```

```python
# in _compact_conversation
history = "\n".join(f"{m['role']}: {str(m['content'])[:500]}" for m in self.conversation)
prompt = [{"role": "user", "content": f"Summarize this conversation for continuity...\n\n{history}"}]
saved_tools, self.brain.tools = self.brain.tools, []     # no tools for bookkeeping
try:
    thought = self.brain.think(prompt)
finally:
    self.brain.tools = saved_tools
self.conversation = [{"role": "user", "content": f"Previous conversation summary: {thought.text}"}]
```

Read the last line carefully: history is **replaced** by a summary. You lose
detail, you keep continuity, and you gain room to work. That is the trade.

`last_input_tokens` is real data from the response (`usage`), not an estimate.
Estimating tokens with a character count is the classic way to be surprised by a
400 at the worst moment.

## Watch it run (frame by frame)

```
[openrouter:act] ❯ Create fib.py printing the first 10 Fibonacci numbers, then run it.
  ⟡ hook:before_think  1 message(s) queued
  ⟡ hook:after_think  text 43 chars · wants write_file
  → Writing fib.py
  ⟡ hook:tool_call  write_file(path=fib.py, content=...) → 43 chars back
  ⟡ hook:before_think  3 message(s) queued
  ⟡ hook:after_think  wants run_command
  → Running python fib.py
  ⟡ hook:tool_call  run_command(command=python fib.py) → 27 chars back
  ⟡ hook:before_think  5 message(s) queued
  ⟡ hook:after_think  text 110 chars
  ⟡ hook:turn_end  answer 154 chars
```

A failure looks almost the same, and that is the point:

```
  → Running python fib.py
  ⟡ hook:tool_call  run_command(...) → 138 chars back      <- STDOUT/STDERR included
  ⟡ hook:after_think  wants edit_file
  → Editing fib.py
  → Running python fib.py
  ⟡ hook:tool_call  run_command(...) → 27 chars back       <- green this time
```

## Why it is built this way

**The exit code is not an exception.** Throwing on a non-zero exit would delete
the most useful information in the loop. The agent is *supposed* to see failures.

**Compaction summarises instead of truncating.** Dropping old messages loses the
decisions; summarising keeps them at a fraction of the tokens.

**The threshold is 75%, not 100%.** By the time you are at 100% the request has
already failed. Headroom is where the summariser fits.

## Try it

```bash
uv run ch09/nanocode.py --act
```

1. "Write a script that divides two numbers from argv, then run it with args 6 and
   0." Watch the traceback come back as tool output, then the fix.
2. "Write a script, run it, and keep improving it until `pytest` passes" (there is
   no pytest in a fresh dir — watch how it reacts to a missing command).
3. Check the token line: run a long conversation and watch
   `hook:before_think  N message(s) queued` grow, then reset after a compaction
   (`⧉ Compacting conversation`).
4. Set `NANOCODE_TIMEOUT=1` and ask it to run `sleep 5`. What does the tool return?

## Checkpoint

<details>
<summary>Why is a failed test "information" rather than an error?</summary>

Because the loop exists to react to output. If failures raised exceptions, the
turn would end at the most interesting moment. Strings let the model decide:
retry, change approach, or report back to you.
</details>

<details>
<summary>What exactly survives a compaction?</summary>

Only the summary message. It is asked to preserve what was accomplished, what is
in progress, and key decisions — so file paths and intent usually survive, exact
code does not. If a task depends on verbatim content, re-read the file after
compaction.
</details>

<details>
<summary>Why remove the tool menu while summarising?</summary>

The summary request is bookkeeping, not a task. Leaving tools on invites the model
to call one mid-summary, which would then be appended to the very history you are
about to throw away.
</details>

**Next:** chapter 10 adds a brain that runs on your own machine.
