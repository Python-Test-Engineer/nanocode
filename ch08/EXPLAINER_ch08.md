# Chapter 8 — Eyes on the project (list and search)

> **You are here:** so far the agent could only open a file whose path it already
> knew. Now it can see the tree and search the contents — which is the difference
> between guessing and knowing.

The loop does not change this chapter. That is the lesson: adding capability means
adding a tool, not editing the agent.

## The idea in one picture

```
  "add a --verbose flag to the CLI"
              │
              ▼
      ┌───────────────┐        ┌──────────────────────────────────────┐
      │  list_files   │ ─────► │ ch01/  ch02/  ...  cli.py  README.md │
      └───────────────┘        └──────────────────────────────────────┘
              │
              ▼
      ┌────────────────────┐   ┌────────────────────────────────────────────┐
      │  search_codebase   │──►│ cli.py:42:     parser = argparse.ArgumentParser()
      └────────────────────┘   │ cli.py:57:     parser.add_argument("--name")│
                               └────────────────────────────────────────────┘
              │
              ▼
      read_file("cli.py")  ->  edit_file(...)      (chapter 9)
```

Two cheap, read-only tools replace a lot of expensive guessing.

## What's new on disk

```
ch08/
  tools.py     ListFiles, SearchCodebase   (both plan_safe = True)
  ui.json      colours for "Listing" and "Searching codebase for"
```

| Tool | Returns | Typical size |
|---|---|---|
| `list_files(path=".")` | an indented tree of paths | hundreds of tokens |
| `search_codebase(query, path=".")` | `path:line: text` matches | proportional to matches |

Both are `plan_safe`, so they work in plan mode. Research belongs in plan mode.

## `list_files`: pruning is part of the design

```python
for root, dirs, files in os.walk(path):
    # dirs[:] = ... prunes the walk IN PLACE (os.walk reads this list back);
    # reassigning `dirs` would have no effect.
    dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "venv", ".venv", ".nanocode"}]

    level = root.replace(path, "").count(os.sep)
    indent = " " * 4 * level
    file_list.append(f"{indent}{os.path.basename(root)}/")
```

Three decisions hiding in five lines:

- **`dirs[:] = ...` is in-place.** `dirs = [...]` would rebind a local name and
  `os.walk` would happily descend into `.git`.
- **Skip lists are context engineering.** A tree that includes `.git` and
  `__pycache__` burns tokens and hides the signal.
- **Indentation carries structure.** A flat list of paths loses the hierarchy the
  model needs to reason about modules.

## `search_codebase`: the output format is the feature

```python
results.append(f"{file_path}:{i+1}: {line.strip()}")
```

That is `path:line: text` — the same shape as `grep -n`, and for the same reason:
it is scannable by a human, and it gives the model everything it needs to ask the
next question ("read `cli.py` around line 42").

Search is case-insensitive on purpose (`query.lower() in line.lower()`), because a
model asked for "ArgumentParser" should still find `argparse.ArgumentParser`.

## Watch it run (frame by frame)

```
[openrouter:plan] ❯ Where are CLI arguments parsed?
  → Searching codebase for 'argparse'
  ⟡ hook:tool_call  search_codebase(query=argparse) → 214 chars back
  → Reading cli.py
  ⟡ hook:after_think  text 96 chars
cli.py:12 parses arguments with argparse (it defines --name at cli.py:57).
```

Compare with the same question in chapter 7: the agent would have had to invent
`cli.py`, or ask you where it is. Now it looks.

## Why it is built this way

**Two small tools, not one clever one.** `list_files` answers "what is here?";
`search_codebase` answers "where is this string?". Merging them into
`explore_project()` would hide two different intentions behind one vague name —
and the model chooses tools by their names and descriptions.

**Search returns matches, not file contents.** A match is cheap; the model can
then decide which file is worth reading in full. This keeps the context window
for things that matter.

**Both are read-only.** Anything that can be done without changing the project is
available in plan mode, so the plan can be based on facts.

## Try it

```bash
uv run ch08/nanocode.py            # plan mode is enough — both tools are safe
```

1. "How many chapters are there?" (it should count directories, not guess).
2. "Where is `tool_definitions` defined?" Check the `path:line` answer against
   `grep -rn`.
3. "Search for a string that appears 200 times" (e.g. `import`). Watch the tool
   result size in the `hook:tool_call` line. What could you add to the tool to
   keep that bounded?
4. Ask it to read a file it has not listed. It will guess a path; notice whether
   the error makes it search first.

## Checkpoint

<details>
<summary>Why is the tree indented rather than a flat list of paths?</summary>

Because the model reasons about structure: "the tests sit under `ch09/`" is only
visible if nesting is visible. Flat paths force it to reconstruct the hierarchy
from string prefixes, which it does worse than your terminal does.
</details>

<details>
<summary>What would you change to make search cheaper on a big repo?</summary>

Cap the number of matches, truncate long lines, or return only counts per file
until the model asks for a specific file. All three are five-line changes to
`SearchCodebase.execute` — which is the point of keeping tools small.
</details>

<details>
<summary>Why not let <code>search_codebase</code> read binary files too?</summary>

It does — and skips what it cannot decode (`errors="ignore"`, per-file try). One
unreadable file must not abort a search across a whole repository.
</details>

**Next:** chapter 9 closes the loop: run the code, read the traceback, fix it, run
again — and learn to compact the conversation before it overflows.
