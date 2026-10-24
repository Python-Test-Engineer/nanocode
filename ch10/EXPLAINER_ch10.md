# Chapter 10 — Local models (a brain on your own machine)

> **You are here:** a fourth brain, `Ollama`, running locally. Same interface, no
> API key, no network. Nothing in the agent changes — which is the point.

If `/switch` worked in chapter 4, this chapter is proof: a new provider is one
class and one registry entry.

## The idea in one picture

```
        ┌────────────── your machine ──────────────┐        ┌── internet ──┐
        │                                          │        │              │
        │  nanocode ──► localhost:11434 ──► model  │        │  OpenRouter  │
        │                     ▲                     │        │  Claude      │
        │                     │                     │        │  DeepSeek    │
        │              ollama serve                 │        │              │
        └──────────────────────────────────────────┘        └──────────────┘
                     private, offline                      key, network, $$$
```

Same `Brain` contract on both sides. `/switch` walks the registry; the agent does
not care which one answers.

## What's new on disk

```
ch10/
  llm.py   class Ollama  (+ one BRAINS entry)
```

That is the whole diff. `tools.py`, `nanocode.py`, `ui.py`, `hooks.py` are
identical to chapter 9 — the local model gets the same tools and the same UI.

## The class, and the one interesting line

```python
class Ollama(Brain):
    """Ollama local model (Anthropic-compatible API, with tool support)."""

    context_limit = 32_000

    def __init__(self, memory=None, tools=None):
        super().__init__(memory, tools)
        self.model = os.getenv("OLLAMA_MODEL", "qwen3-coder:30b")
        self.url = "http://localhost:11434/v1/messages"   # no auth, no TLS
        self._detect_context_limit()
```

```python
def _detect_context_limit(self):
    """Query Ollama for the model's context window size."""
    try:
        response = requests.post("http://localhost:11434/api/show",
                                 json={"model": self.model}, timeout=0.5)
        for key, value in response.json().get("model_info", {}).items():
            if key.endswith(".context_length"):
                self.context_limit = value
                return
    except Exception:
        pass  # the daemon may not be running; keep the default
```

Why this exists at all: chapter 9's compaction compares
`last_input_tokens > context_limit * 0.75`. With a hosted model you know the
window; with a local model the window depends on the model file you loaded. So we
ask the daemon, and fall back to a conservative 32k.

The `timeout=0.5` is not sloppiness — it is a *probe*. If Ollama is not running,
the probe should cost half a second, not block the chapter.

## Watch it run (frame by frame)

```
$ ollama serve            # in one terminal
$ ollama pull qwen3-coder:30b

$ NANOCODE_BRAIN=ollama uv run ch10/nanocode.py --act
⚡ Nanocode v0.9 (Local Models)
  brain ollama  model qwen3-coder:30b  mode act  tools 8

[ollama:act] ❯ /switch
  ⇄ Switched to: openrouter (deepseek-v4.1-flash-1017)     <- and back again
```

The same conversation, two very different machines — one local, one in a
datacenter — and not a single line of agent code written twice.

## Why it is built this way

**`Brain` is a boundary, not a base class for its own sake.** Three providers
already proved it; the fourth is the test of whether the abstraction was real.

**Fallback beats failure.** A missing daemon or a model without `context_length`
information must not crash a chapter; the probe keeps defaults.

**Local models are slower and less capable — say so in the docs, not in code.**
The interface is identical; expectations are not. Small models need more
explicit tool descriptions and more patience with retries.

## Try it

```bash
ollama serve &
ollama pull qwen3-coder:30b          # any tool-capable model works
NANOCODE_BRAIN=ollama uv run ch10/nanocode.py --act
```

1. Ask the same question to the local model and then `/switch` to OpenRouter.
   Compare the plans. Which one reads files it did not need?
2. Set `OLLAMA_MODEL` to a model you have not pulled. What error do you get, and
   where does it surface (`main()` catches, or the loop)?
3. Stop `ollama serve` mid-session and send a message. How long does the failure
   take? Which line decides that?
4. Ask for a task needing 3+ tool calls. Smaller models often stop early — count
   iterations with `hook:before_think` and compare with a hosted model.

## Checkpoint

<details>
<summary>Why does Ollama's URL need no API key while the others do?</summary>

Because it is your machine: the endpoint is bound to localhost and there is no
account to bill. The code still sends a placeholder `x-api-key` header because the
Anthropic-compatible endpoint expects the field to exist.
</details>

<details>
<summary>Why probe <code>/api/show</code> instead of hard-coding 32k?</summary>

The window is a property of the model file, not of the client. Probing means a
larger model gets a larger budget and compaction fires later — with a safe
fallback when the probe fails.
</details>

<details>
<summary>What is the real cost of a local model?</summary>

Latency and quality, not money. You trade tokens-per-second and reasoning depth
for privacy and zero marginal cost. The agent does not know the difference,
which is exactly why the trade is yours to make per task.
</details>

**Next:** chapter 11 gives the agent a window to the outside world.
