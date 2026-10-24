# Chapter 3 — The first brain (and the conversation becomes memory)

> **You are here:** the request from chapter 2 becomes a class, and the class's
> output becomes a `Thought`. The agent now remembers what you said — because it
> resends the whole conversation every turn.

This is the first chapter where behaviour feels like magic. It is not. The model
has no memory; the *list* has the memory, and you send it again and again.

## The idea in one picture

```
  turn 1                     turn 2                     turn 3
  ──────                     ──────                     ──────
  conversation = []          conversation = [           conversation = [
    + user "my name is Sam"      user  "my name is Sam"      user  "my name is Sam"
                                 assistant "Hello Sam"      assistant "Hello Sam"
                                 + user "what is my name?"  assistant "Your name is Sam"
                                                            + user "and again?"
                                                          ]
        │                          │                          │
        ▼                          ▼                          ▼
   brain.think(conv)  ─────►  brain.think(conv)  ─────►  brain.think(conv)
```

The arrow into `brain.think` always carries *everything*. That is the memory.

## What's new on disk

```
ch03/
  llm.py       Thought, ToolCall, OpenRouter      <- the brain, in its own file
  nanocode.py  Agent gains a conversation list
  hooks.py     lifecycle events (this fork's addition)
  ui.py        adds thinking lines
```

Three new ideas, in order of importance:

| Idea | Where | Why it matters |
|---|---|---|
| `Thought` | `llm.py` | one shape for "what the model said", whatever the provider |
| `conversation` | `nanocode.py` | the entire state of the agent |
| hooks | `hooks.py` | the loop can be observed without being edited |

## The brain, and the object it returns

```python
class OpenRouter:
    def think(self, conversation):
        headers = {...}
        payload = {"model": self.model, "max_tokens": 4096, "messages": conversation}
        response = requests.post(self.url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        return self._parse_response(response.json()["choices"][0]["message"])
```

The important line is the last one: the raw provider JSON never leaves this
class. The agent receives a `Thought`:

```python
class Thought:
    def __init__(self, text=None, tool_calls=None, thinking=None):
        self.text = text              # what to show the user
        self.tool_calls = tool_calls or []  # empty here; tools arrive in ch05
        self.thinking = thinking      # reasoning, for the dim 💭 lines only
```

That empty `tool_calls` list is a promise being made early: the loop already
knows it might be asked to run something.

## The agent, and the list that remembers

```python
self.conversation.append({"role": "user", "content": user_input})

try:
    thought = self.brain.think(self.conversation)
    ui.thinking(thought.thinking)

    text = thought.text or ""
    self.conversation.append({"role": "assistant", "content": text})
    return text
except Exception as e:
    self.conversation.pop()   # the question never got an answer: drop it
```

Two details students usually miss:

1. **The reply is appended too.** If you only append user messages, the next
   request contains a conversation where the model talks to itself.
2. **A failed call pops the user message.** Otherwise the history has two user
   turns in a row, and some providers reject that outright.

## Watch it run (frame by frame)

Real output, with the reasoning lines this fork adds:

```
[openrouter] ❯ my name is Sam
  💭 The user gave their name. Acknowledge it briefly.
Hello, Sam! Nice to meet you.

[openrouter] ❯ what is my name?
  💭 We know from the prior turn: Sam. Answer concisely.
Your name is Sam.
```

Now look at the hook lines that this fork prints (they are on by default; set
`NANOCODE_HOOKS=0` to hide them):

```
[openrouter] ❯   ⟡ hook:turn_start  "what is my name?"
  ⟡ hook:before_think  3 message(s) queued        <- 3, because history is resent
  💭 We know from the prior turn: Sam.
  ⟡ hook:after_think  text 18 chars
  ⟡ hook:turn_end  answer 18 chars
```

`3 message(s)` is the whole lesson of this chapter: user, assistant, user.

## Why it is built this way

**The brain moved to `llm.py` even though there is only one provider.** Chapter 4
adds two more; moving a class while it is still small is cheap, moving it later is
a refactor.

**`Thought` has exactly three fields.** Every one of them is used by the agent or
the UI this chapter. Fields are added when a chapter needs them (`raw_content` in
ch05, token counts in ch09) — not in advance.

**Hooks exist from the first brain onwards.** They are the cheapest way to make
the loop legible: five `emit` calls in the agent, and any listener can watch.

## Try it

```bash
uv run ch03/nanocode.py
```

1. Tell it your name, then ask for it. Then ask again after three unrelated
   questions. Does it still know? Look at how many messages were sent
   (`hook:before_think`).
2. Ask it something that needs your project: "what is in this repo?" It cannot
   know — it has never seen a file. Remember that feeling; chapter 5 fixes it.
3. Register a hook without editing the agent:

```python
import nanocode
from hooks import Hooks

agent = nanocode.Agent(brain=nanocode.OpenRouter())
agent.hooks.on("turn_end", lambda output, **_: print("ANSWER LEN:", len(output)))
```

   Four lines, no changes to `nanocode.py`. That is what "observable" buys you.

## Checkpoint

<details>
<summary>Where does the model's "memory" actually live?</summary>

In `Agent.conversation` — a plain Python list on your machine. The model is
stateless between requests; resending the list is what feels like memory. This is
also why long conversations get expensive: every turn resends everything.
</details>

<details>
<summary>Why does a failed call remove the user message?</summary>

A conversation with a dangling user question has the wrong shape: two user
messages in a row on the next attempt. Removing it keeps the alternation
user/assistant/user that providers expect.
</details>

<details>
<summary>What is <code>thinking</code> for, if it is not sent back?</summary>

It is shown once, dimmed, then dropped. Reasoning is produced by the model, but
you do not need to replay it — the answer (and later the tool calls) carry the
information forward. Keeping it would inflate every subsequent request.
</details>

**Next:** chapter 4 adds a second and third provider, a retry policy, and
`/switch` — without touching the agent loop.
