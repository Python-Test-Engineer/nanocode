# Chapter 2 — First contact (one raw request)

> **You are here:** still no agent. This chapter sends a single HTTP request to a
> model and prints the JSON that comes back, so you can see exactly what a "brain"
> looks like before any abstraction hides it.

The book does this with Claude. This fork does it with OpenRouter, because the
same key then drives every later chapter. The mechanics are identical — a URL, a
key, a JSON body, a JSON reply.

## The idea in one picture

```
  your script                     the provider                  the model
  ───────────                     ────────────                  ─────────
  POST /chat/completions   ───►   auth + routing     ───►       tokens in
      { model, messages }                                            │
                                                                     ▼
  print(data)              ◄───   JSON response      ◄───       tokens out
```

No loop, no tools, no memory. If you understand this arrow diagram, every
chapter after this one is bookkeeping.

## What's new on disk

```
ch02/
  api_check.py    the ported script (this is what you read)
  test_api.py     the book's original, untouched, for comparison
  ui.py, ui.json  same console layer as chapter 1
```

`test_api.py` is the book's version and it calls Anthropic directly. It is kept
so you can diff the two dialects side by side:

```text
# book (test_api.py)                    # this fork (api_check.py)
"x-api-key": api_key,                   "Authorization": f"Bearer {api_key}",
url = ".../v1/messages"                 url = ".../v1/chat/completions",
payload["messages"] = [...]             payload["messages"] = [...]      # same
```

## The request, field by field

```python
headers = {
    "Authorization": f"Bearer {api_key}",   # who you are
    "Content-Type": "application/json",     # what you are sending
    "X-Title": "Nanocode",                  # shows up in OpenRouter's dashboard
}

payload = {
    "model": model,        # which model; overridable with OPENROUTER_MODEL
    "max_tokens": 256,     # budget for the REPLY, not the request
    "messages": [          # the conversation so far (here: one message)
        {"role": "user", "content": "Hello, are you ready to code?"}
    ],
}
```

The response is bigger than you expect. Two fields matter now:

```
choices[0].message.content    <- what the model said
usage.prompt_tokens           <- what the request cost (used in chapter 9)
```

Everything else — `id`, `provider`, `service_tier`, `system_fingerprint` — is
provider bookkeeping. It is printed, syntax-highlighted, because seeing it once
makes the later abstractions feel less magical.

## Watch it run (frame by frame)

```
  · Sending request...            <- before the network call
  · Status: 200                   <- the HTTP status nobody checks until it is 500
  ✔ Ready when you are! ...       <- the one field a user cares about

  {                               <- everything else, for the curious
    "id": "gen-...",
    "model": "deepseek/deepseek-v4.1-flash-1017",
    "provider": "Wafer",
    "choices": [ { "message": { "content": "Ready when you are! ..." } } ],
    "usage": { "prompt_tokens": 36, "completion_tokens": 12, "total_tokens": 48 }
  }
```

## Why it is built this way

**No error handling on purpose (mostly).** The book fires the request "with no
safety net". Chapter 4 adds retries. Here, a 401 should be loud — you are meant
to see what a failure looks like before you start hiding failures.

**The JSON is printed, not summarised.** An abstraction you have not seen the
insides of is a superstition. Once you have read `choices[0].message`, chapter 3's
`Thought` object reads like a translation, not a trick.

**The key never appears in output.** `ui.error` prints the provider's message on
failure, not the request — a small habit worth copying.

## Try it

```bash
uv run ch02/api_check.py
```

1. Run it twice. Which fields change between runs? Which stay the same?
2. Break the key on purpose (add a letter in `.env`), run again, and read the
   error. What status code comes back, and where does the message live in the
   JSON?
3. Change `max_tokens` to `8`. What happens to the reply, and what is
   `finish_reason` now? (Add a print if it is not shown.)
4. Change the prompt to ask for a 5-item Markdown list. Notice the JSON string
   contains `\n` escapes — this is why chapter 3 stores text, not formatted
   output.

## Checkpoint

<details>
<summary>Why is <code>max_tokens</code> in the request if the model already knows when to stop?</summary>

Because it caps cost and latency. A model will happily write 2000 tokens when 20
would do; `max_tokens` is your budget, and hitting it shows up as
`finish_reason: "length"` — a truncated reply, not an error.
</details>

<details>
<summary>What does the model actually receive from you?</summary>

The messages array, serialised as JSON, plus the model name. No files, no memory,
no state: everything the model knows about your project is whatever you literally
put in those messages. That fact is the whole reason tools exist.
</details>

**Next:** chapter 3 wraps this request in a class, keeps the messages around, and
gives the agent its first memory.
