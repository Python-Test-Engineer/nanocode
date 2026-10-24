# Chapter 4 — More than one brain (an interface, a registry, retries)

> **You are here:** the agent stops knowing which model answers it. A `Brain` is
> now a contract, providers are implementations, and `/switch` swaps them
> mid-conversation.

The interesting thing about this chapter is how little the agent changed. Adding
two providers added zero lines of loop code. That is what an abstraction is for —
not tidiness, but *leverage*.

## The idea in one picture

```
                    ┌──────────────────────────────┐
        Agent ────► │  brain.think(conversation)   │ ────►  Thought
                    └──────────────────────────────┘
                                  ▲
              ┌───────────────────┼───────────────────┐
              │                   │                   │
        ┌───────────┐       ┌───────────┐       ┌────────────┐
        │  Claude   │       │ DeepSeek  │       │ OpenRouter │
        │ Anthropic │       │ anthropic-│       │ OpenAI     │
        │  /messages│       │ compatible│       │ chat/compl.│
        └───────────┘       └───────────┘       └────────────┘
              └────────────── BRAINS[name] ───────────┘
```

The agent only ever sees the arrow on the left. Everything on the right is
replaceable.

## What's new on disk

```
ch04/
  llm.py       Brain (base class), Claude, DeepSeek, request_with_retry, BRAINS
  nanocode.py  Agent gains _switch_brain() and a brain_name
```

| New thing | Purpose | Where |
|---|---|---|
| `Brain` | the contract: implement `think()`, share `_parse_response()` | `llm.py` |
| `request_with_retry` | survive 429s and 5xx without losing the turn | `llm.py` |
| `BRAINS` | name → class, the list `/switch` walks | `llm.py` |
| `_switch_brain` | swap the object, keep the history | `nanocode.py` |

## The contract, and why a base class earns its keep

```python
class Brain:
    """Base class for LLM providers.

    Two methods matter: think() (which every provider must implement) and
    _parse_response() (shared by the Anthropic-shaped providers).
    """

    def think(self, conversation):
        raise NotImplementedError

    def _parse_response(self, content):
        # Anthropic-shaped providers all return a list of blocks: thinking,
        # text, tool_use. This conversion is written once and shared.
        ...
```

`Claude` and `DeepSeek` differ only in URL, headers and payload — the parsing is
identical, so it lives in the base class. `OpenRouter` speaks a different dialect
and overrides `_parse_response`. The base class is doing exactly one job: naming
the shared parts.

## Retries: three cases, three behaviours

```text
requests raises RequestException        -> network died: wait 2**attempt, retry
status 429 or >= 500                    -> server busy: wait Retry-After (or 2**attempt), retry
status >= 400                           -> our request is wrong: raise, do not retry
```

The distinction matters: a 429 is "later", a 401 is "never". Retrying the second
one just wastes ten seconds before failing anyway.

## `/switch` — and why the history survives

```python
names = list(BRAINS.keys())              # cycle order = dict order
idx = names.index(self.brain_name)
new_name = names[(idx + 1) % len(names)]

self.brain = BRAINS[new_name]()          # construct inside try: no key -> ValueError
self.brain_name = new_name
```

At this chapter the conversation is plain `{"role", "content"}` text, so every
provider can read it and nothing has to be translated. Chapter 5 changes that:
tool calls force the two dialects apart, and `llm.py` grows translation functions.

## Watch it run (frame by frame)

```
[openrouter] ❯ explain a monad in one line
  💭 Keep it short...
A monad is a way to chain operations while carrying context.

[openrouter] ❯ /switch
  ⇄ Switched to: claude (claude-sonnet-4-6)        <- or an error if no key
[claude]     ❯ and again, shorter
  ...                                               <- same history, new provider
```

If the next provider has no API key, the switch fails *politely*:

```
  ✗ Cannot switch to claude: ANTHROPIC_API_KEY not found in .env
```

The agent keeps running. A provider you cannot afford should not end your session.

## Why it is built this way

**The registry is an ordered dict, not a list of tuples.** `/switch` needs an
order and `main()` needs a lookup; one structure serves both.

**Construction happens inside the `try`.** A missing key raises `ValueError` at
`__init__` time, so the switch must be able to fail without corrupting the agent.

**The base class holds no state.** Its `context_limit`/`last_input_tokens` are
placeholders for chapter 9; a provider is otherwise a pure request builder.

## Try it

```bash
uv run ch04/nanocode.py
```

1. Ask a question, `/switch`, ask "what did I just ask?". Does the new provider
   know? Why?
2. `/switch` twice. Where do you end up? (Count the entries in `BRAINS`.)
3. Set `NANOCODE_BRAIN=claude` with no Anthropic key. Read the error and note
   *where* it is raised (`main()` catches it, not the agent).
4. Add a fake provider in the REPL:

```python
import nanocode
class Echo(nanocode.Brain):
    def think(self, conversation):
        return nanocode.Thought(text=f"echo: {conversation[-1]['content']}")
nanocode.BRAINS["echo"] = Echo
# then /switch until you reach "echo"
```

## Checkpoint

<details>
<summary>Why not put the retry loop inside each provider?</summary>

Because it is the same retry loop. Duplicating it three times means three places
to fix when a provider adds a new status code. Shared code belongs where the
providers can share it — a module-level function, not a base method, because it
does not need `self`.
</details>

<details>
<summary>What breaks if you switch brains mid-tool-call (after chapter 5)?</summary>

The message history holds provider-shaped content blocks. This fork solves it by
storing history in *one* canonical shape (Anthropic blocks) and translating per
provider at send time — see chapter 5's `to_openai_messages`.
</details>

**Next:** chapter 5 gives the agent hands. The loop stops being a single request
and becomes a cycle.
