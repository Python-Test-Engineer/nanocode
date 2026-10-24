# Chapter 5 — Hands (tools, and the loop becomes a cycle)

> **You are here:** the agent can read and write files. More importantly, the
> single request from chapter 3 becomes a *cycle*: ask → act → feed the result
> back → ask again.

This is the chapter where "chatbot" becomes "agent". Everything after this is
more tools, more safety, more endurance — not a new idea.

## The idea in one picture

```
                   ┌──────────────────────────────────────────────┐
                   │                                              │
                   ▼                                              │
   conversation ──► brain.think() ──► Thought ──┬── no tool calls? ──► answer
                                                │
                                                └── tool_calls ──► execute each
                                                                       │
                                        append results as a USER message
                                                                       │
                                                                       └──┐
                                                                          │
                   ◄──────────────────────────────────────────────────────┘
```

One trip around that loop is one "iteration". `MAX_ITERATIONS = 50` in the
capstone exists because a confused model can keep asking for tools forever.

## What's new on disk

```
ch05/
  tools.py     ReadFile, WriteFile, get_tool, tool_definitions
  llm.py       Thought.raw_content, tool_calls, to_openai_messages(), to_openai_tools()
  nanocode.py  _agentic_loop(), _execute_tool()
  ui.py        ui.tool_action() — one coloured line per tool call
```

| New thing | Why it exists |
|---|---|
| tool `execute(**args) -> str` | a tool is a function with metadata the model can read |
| `raw_content` | the next request must echo exactly what the model said |
| `to_openai_*` | OpenAI needs a different message shape than Anthropic |
| `_agentic_loop` | the cycle above, in twenty lines |

## A tool is metadata plus a function

```python
class ReadFile:
    name = "read_file"
    description = "Reads a file from the filesystem. Use this to examine code."
    input_schema = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "The path to the file"}},
        "required": ["path"],
    }

    def execute(self, path):
        ui.tool_action("read_file", path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            numbered_lines = [f"{i+1} | {line}" for i, line in enumerate(lines)]
            return "".join(numbered_lines)
        except Exception as e:
            # A tool must always return a string. The model reads the error
            # and decides what to do next.
            return f"Error reading file: {e}"
```

Four things to notice:

- `description` and `input_schema` are **prompt engineering**, not documentation.
  They are pasted into the request; the model chooses tools by reading them.
- `execute` never raises. A traceback ends the turn; `"Error: File not found"`
  continues it.
- The line numbers (`1 | import os`) are for the model, so it can refer to
  "line 42" later.
- `ui.tool_action(...)` is the only console call in `tools.py`. Colour lives in
  `ui.json`, so a tool never mentions a colour.

## The loop, annotated

```python
while True:
    thought = self.brain.think(self.conversation)          # 1. ask
    ui.thinking(thought.thinking)

    # Append the provider's own blocks, not thought.text: the next request must
    # see the tool_use ids that the results will refer to.
    self.conversation.append({"role": "assistant", "content": thought.raw_content})

    if thought.text:
        output_parts.append(thought.text)

    if not thought.tool_calls:
        break                                              # 2. done

    tool_results = []
    for tool_call in thought.tool_calls:                   # 3. act
        result = self._execute_tool(tool_call.name, tool_call.args)
        tool_results.append({
            "type": "tool_result",
            "tool_use_id": tool_call.id,                   # ties result -> call
            "content": result,
        })

    self.conversation.append({"role": "user", "content": tool_results})  # 4. feed back
```

Step 4 surprises people: the tool output is appended as a **user** message. In
this dialect, "user turn" means "whatever the model needs to hear next", and tool
output is exactly that.

## One conversation, two dialects

The agent stores history in one shape; providers disagree about the wire format:

```
 Anthropic wire format                    OpenAI wire format
 ─────────────────────                    ──────────────────
 {"role":"user",                          {"role":"user",
  "content":[{"type":"tool_result",        "content":"..."}         <- plain text
              "tool_use_id":"c1",         {"role":"assistant",
              "content":"1 | import os"}] "content":null,
                                          "tool_calls":[{"id":"c1",
                                            "function":{"name":"read_file",
                                                        "arguments":"{\"path\":\"app.py\"}"}}]}
                                          {"role":"tool",
                                           "tool_call_id":"c1",
                                           "content":"1 | import os"}
```

`to_openai_messages()` performs that translation on every request. It is the
reason `/switch` still works once tools are involved.

## Watch it run (frame by frame)

A real two-tool turn, with this fork's hook lines interleaved:

```
[openrouter:act] ❯   ⟡ hook:turn_start  "Create note.txt containing hello, then read it back."
  ⟡ hook:before_think  1 message(s) queued
  ↑ Thinking...
  ⟡ hook:after_think  text 43 chars · wants write_file
  → Writing note.txt
  ⟡ hook:tool_call  write_file(path=note.txt, content=hello) → 43 chars back
  ⟡ hook:before_think  3 message(s) queued          <- now 3: user, assistant, tool_result
  ↑ Thinking...
  ⟡ hook:after_think  wants read_file · reasoning
  💭 Now read it back.
  → Reading note.txt
  ⟡ hook:tool_call  read_file(path=note.txt) → 10 chars back
  ⟡ hook:before_think  5 message(s) queued          <- 5, and still climbing
  ⟡ hook:after_think  text 110 chars
  ⟡ hook:turn_end  answer 154 chars
```

The message count is the animation: 1 → 3 → 5. Two tools, two round trips, one
answer.

## Why it is built this way

**Tools return strings, not exceptions.** The model cannot catch a traceback; it
*can* read "Error: File not found: app.py" and try `app.py` instead. This single
decision is what makes the feedback loop work.

**`raw_content` instead of `text`.** If you rebuild the assistant message from
the text, you lose the tool-call ids, and the tool results refer to nothing.

**`MAX_ITERATIONS`.** An unbounded loop with a paid API is a way to lose money.
Fifty is generous for real work and short enough to stop a spiral.

## Try it

```bash
uv run ch05/nanocode.py --act
```

1. "Read `ch05/ui.json` and tell me the colour of `read_file`." Watch which tools
   it chooses and how many round trips it takes (`hook:before_think`).
2. "Show me the contents of a file that does not exist." Read the error the model
   gets back, then watch it recover.
3. Ask for something impossible, e.g. "run the tests". It has no such tool. Does
   it explain, or hallucinate? This is what chapter 9 fixes.
4. In plan mode (the default: no `--act`), `write_file` is still offered in this
   chapter — plan mode arrives in chapter 7. Try to write a file anyway, then
   compare with chapter 7.

## Checkpoint

<details>
<summary>Why does the loop append tool results as a "user" message?</summary>

Because the conversation must alternate. The model produced an assistant message
(possibly with tool calls); the results are the next thing it needs to "hear", so
they occupy the user slot. Anthropic models know this shape as `tool_result`
blocks; OpenAI models use a dedicated `role: "tool"` message instead.
</details>

<details>
<summary>What happens if you forget <code>tool_use_id</code> in a result?</summary>

Providers reject the request or (worse) the model cannot tell which call the
result belongs to and re-issues the call. With two tool calls in one reply, the
ids are what keep the answers matched to the questions.
</details>

<details>
<summary>Why are tool descriptions phrased as instructions ("Use this to examine code")?</summary>

They are read by the model when it decides what to call, so they answer "when
should I use this?" rather than "what is this?". A description that says
"ReadFile class" is useless; "Use this to examine code" is a decision aid.
</details>

**Next:** chapter 6 makes memory survive a restart.
