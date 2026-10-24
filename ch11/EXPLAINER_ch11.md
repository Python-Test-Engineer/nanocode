# Chapter 11 — A window outside (web search)

> **You are here:** the last feature before the capstone. The agent can search the
> web, so it can check a library version or read an error message it has never
> seen — instead of confidently inventing one.

Training data has a date on it. A coding agent that cannot look things up will
happily write code against an API that changed two years ago.

## The idea in one picture

```
  "why does pytest-asyncio 0.23 warn about event_loop?"
              │
              ├── internal knowledge (training data, possibly stale)
              │
              └── search_web("pytest-asyncio 0.23 event_loop warning")
                            │
                            ▼
                  ┌───────────────────────────────┐
                  │ Title: ...                    │
                  │ URL:   https://...            │   <- 3 results, formatted
                  │ Summary: ...                  │
                  └───────────────────────────────┘
                            │
                            ▼
                  the model reads, then answers (or reads the page)
```

The tool returns **text**, like every other tool. There is no special "web" path
in the agent.

## What's new on disk

```
ch11/
  tools.py     SearchWeb + resolve_ddgs()
  ui.json      colour for "Searching web for"
  nanocode.py, llm.py   identical to ch12 (the book's ch11 and ch12 are the same code)
```

## The tool

```python
class SearchWeb:
    name = "search_web"
    plan_safe = True     # read-only: research belongs in plan mode too
    description = ("Searches the internet for current information. Use when you "
                   "need knowledge beyond your training data.")
    input_schema = {"type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"]}

    def execute(self, context, query):
        ui.tool_action("search_web", f"'{query}'")
        backend = resolve_ddgs()
        if backend is None:
            return "Error: ddgs package not installed. Run: pip install ddgs"
        results = backend().text(query, max_results=3)
        formatted = [f"Title: {r['title']}\nURL: {r['href']}\nSummary: {r['body']}\n"
                     for r in results]
        return "\n".join(formatted)
```

Three deliberate choices:

- **`max_results=3`.** The output is going into a prompt; ten results is a lot of
  context for a small gain.
- **`Title / URL / Summary` on separate lines.** Easy for the model to cite, easy
  for you to read in a trace.
- **`plan_safe = True`.** Reading the web changes nothing locally, and research is
  exactly what plan mode is for.

## The test hook (`resolve_ddgs`)

```python
def resolve_ddgs():
    """The DuckDuckGo backend, honouring an override on the host module."""
    global DDGS
    host = sys.modules.get("nanocode")
    if host is not None and getattr(host, "DDGS", None) is not None:
        DDGS = host.DDGS
    return DDGS
```

The book's tests patch `nanocode.DDGS` while the tool lives in `tools.py`. Looking
the name up at call time (instead of binding it at import) keeps both honest and
costs nothing outside tests. It is also a small lesson in why monkeypatching and
module-level globals are such close friends.

## Watch it run (frame by frame)

```
[openrouter:plan] ❯ Does the ddgs package still use the `DDGS().text()` API?
  ⟡ hook:after_think  wants search_web
  → Searching web for 'ddgs python text max_results'
  ⟡ hook:tool_call  search_web(query=ddgs python ...) → 812 chars back
  ⟡ hook:before_think  3 message(s) queued
  ⟡ hook:after_think  text 214 chars
Yes — `DDGS().text(query, max_results=n)` is still the entry point (source: ...).
```

Now the same question with the network disabled: the tool returns
`Error searching web: ...` and the model must decide whether to answer from memory
and *say* it is doing so. Whether it admits that is a good test of the model.

## Why it is built this way

**Search is a tool, not a mode.** Anything the agent can do is a tool; that keeps
one loop, one permission model, one trace format.

**Results are text, not links to follow.** Following a page would mean a fetch
tool with its own failure modes. Three summaries are usually enough to correct a
stale belief, and the URL lets *you* check.

**Failures stay inside the tool.** `ddgs` is a scraper; it breaks. The error is a
string, the turn continues, and the model can try a different query.

## Try it

```bash
uv run ch11/nanocode.py            # plan mode: search is read-only
```

1. Ask for the current version of a library you use. Compare with what the model
   says when you add `NANOCODE_HOOKS=0` and cut the network (unplug/deny).
2. Ask a question whose answer is in the repo, e.g. "what does `to_openai_tools`
   do?" Watch whether it searches the web or reads the code. If it searches, your
   tool descriptions need work — this is a real prompt-engineering exercise.
3. Search for something with no results. Read the error path and the model's
   recovery.
4. Add a `max_results` argument to the schema and see if the model uses it.

## Checkpoint

<details>
<summary>Why is <code>search_web</code> marked <code>plan_safe</code>?</summary>

Because it does not modify the project — it only reads. Plan mode is read-only,
not offline; research is how a good plan gets made.
</details>

<details>
<summary>What is the risk of putting web results straight into the prompt?</summary>

Prompt injection: a page can contain text that reads like instructions. The safe
habit is to treat tool results as data, never as authority — and to keep the
agent's dangerous tools behind explicit user intent (which plan mode already
does).
</details>

<details>
<summary>Why does the tool return the URL if the model cannot open it?</summary>

So *you* can verify the claim, and so the model can cite it. Trustworthy output
that cannot be checked is worse than an honest "I am not sure".
</details>

**Next:** chapter 12 — the capstone. Same code, a real task, and a checklist for
reading the whole thing in one sitting.
