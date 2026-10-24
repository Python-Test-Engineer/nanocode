"""Build EXPLAINER.md (the combined book) from the per-chapter explainers.

Each chapter keeps its own `chNN/EXPLAINER_chNN.md`; this script glues them into
one document with front matter, a table of contents and appendices, and demotes
their headings by one level so the combined file has a single `#` title.

    uv run python build_explainer.py
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).parent
CHAPTERS = [f"ch{n:02d}" for n in range(1, 13)]

HEADER = """# Nanocode, explained

**A chapter-by-chapter walkthrough of a small coding agent, written for students.**

This is the companion book to the code in this repository. It assumes you have the
code open beside it. Each chapter explains one new idea, shows the code that
implements it, walks through what happens when the program runs, and ends with
things to try and questions to check yourself against.

The repository is an educational refactor of *Build Your Own Coding Agent*: the
chapters and their ideas are the book's, the structure is not. Every chapter's
original single file is kept as `nanocode_copy.py`, so you can diff the refactor
against the source at any point.

## How to use this book

Three ways, all valid:

1. **Cover to cover.** Read chapters 1-12 in order. Each builds on the last, and
   nothing is assumed except basic Python.
2. **Alongside the code.** Open `chNN/nanocode.py` and the chapter here at the
   same time. Every section names the file and function it is talking about.
3. **As a reference.** Appendix A is the whole architecture on one page; Appendix
   B is a glossary; the checkpoint boxes answer the questions students actually
   ask.

Each chapter has the same shape:

| Section | What it is for |
|---|---|
| **You are here** | one sentence: what this chapter adds |
| **The idea in one picture** | an ASCII diagram you can redraw from memory |
| **What's new on disk** | which files changed, and why those files |
| **The code** | the real snippets, annotated |
| **Watch it run** | a frame-by-frame trace of the program running |
| **Why it is built this way** | the trade-offs, stated as trade-offs |
| **Try it** | exercises that fail in instructive ways |
| **Checkpoint** | collapsible questions with answers |

## What you need

```bash
# 1. install uv (https://docs.astral.sh/uv/getting-started/installation/)
curl -LsSf https://astral.sh/uv/install.sh | sh        # macOS / Linux
# powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"   # Windows

# 2. get the code and the dependencies
git clone <this-repo> && cd build-your-own-coding-agent-main
uv sync

# 3. a key for the default brain (OpenRouter), in .env at the repo root
#    OPENROUTER_API_KEY=sk-or-...
#    OPENROUTER_MODEL="deepseek-v4.1-flash-1017"
#    NANOCODE_BRAIN="openrouter"
```

Chapters 1 and 2 need no key. From chapter 3 on, every chapter needs one model
provider — OpenRouter by default, or `NANOCODE_BRAIN=claude|deepseek|ollama`.

## Conventions used here

- **Diagrams are plain ASCII.** They render identically in Markdown, in
  `book.html`, in a terminal and on paper — no diagram plugin required.
- **`──►` is data flow, `▼` is time moving down.** Boxes are components; the text
  inside is what is passed between them.
- **Frame-by-frame traces** are real program output, split into "frames". Read
  them top to bottom; they are the animation.
- **Hook lines** (`⟡ hook:tool_call ...`) are printed by this fork, not by the
  original book. They are on by default; `NANOCODE_HOOKS=0` hides them.
- **Collapsible answers** use HTML `<details>`. In a plain terminal view you will
  see the tags — read around them.
- **Snippets are excerpts, not photocopies.** Long expressions are sometimes joined
  onto one line, `...` marks omitted code, and comments are occasionally added for
  the point being made. The files themselves are the source of truth.

## Contents

| # | Chapter | The one new idea |
|---|---|---|
| [1](#ch01) | The event loop | a prompt, an agent, a reply — nothing else |
| [2](#ch02) | First contact | one HTTP request, seen in full |
| [3](#ch03) | The first brain | `Thought`, and a conversation that remembers |
| [4](#ch04) | More than one brain | an interface, a registry, retries |
| [5](#ch05) | Hands | tools, and the loop becomes a cycle |
| [6](#ch06) | Memory that survives | a file as the system prompt |
| [7](#ch07) | Plan mode | safety by construction, not instruction |
| [8](#ch08) | Eyes on the project | list and search before acting |
| [9](#ch09) | Closing the loop | run it, read the error, fix it; compaction |
| [10](#ch10) | Local models | a fourth brain, no network |
| [11](#ch11) | A window outside | web search as a tool |
| [12](#ch12) | Capstone | the finished agent, and how to read it |

Each chapter also exists as its own file (`chNN/EXPLAINER_chNN.md`); this document
is the combined edition.

---
"""

APPENDIX = """
---

## Appendix A — The whole architecture on one page

```
chNN/
  nanocode.py    Memory, Agent (the loop), main()        <- policy: what to do next
  llm.py         Brain, Thought, one class per provider  <- transport: how to ask
  tools.py       execute(context, **args) -> str         <- capability: what can be done
  ui.py          Rich rendering; ui.json holds colours    <- presentation
  hooks.py       lifecycle events + JSONL trace           <- observation
  test_nanocode.py   the book's tests, unmodified
  nanocode_copy.py   the book's original file, for diffing
```

The four data contracts that hold it together:

| Contract | Shape | Why it never changes |
|---|---|---|
| Agent → Brain | `think(conversation)` | every provider speaks this one method |
| Brain → Agent | `Thought(text, tool_calls, raw_content, thinking)` | the loop only needs "what to say" and "what to run" |
| Agent → Tool | `execute(context, **args)` | agent state arrives in one object, arguments as keywords |
| Tool → Agent | a string | errors are information the model can act on |

Lifecycle events, for the whole project:

```
turn_start ─► before_think ─► after_think ─┐
                                           ├─► (tool_call ─► before_think ...)*
                                           └─► turn_end
```

## Appendix B — Glossary

**Brain** — a provider behind one method, `think(conversation) -> Thought`. The
agent never knows which one it is talking to.

**content blocks** — the Anthropic message shape: a list of `{"type": "text"}`,
`{"type": "tool_use"}`, `{"type": "tool_result"}` dicts. This fork stores history
in this shape for every provider and translates at the edge.

**compaction** — replacing long history with a summary when the context window
fills (chapter 9). Keeps continuity, loses detail.

**dialect** — a provider's wire format. Anthropic and DeepSeek accept content
blocks; OpenRouter uses OpenAI chat-completions. `to_openai_messages()` converts.

**hook** — a passive observer of the loop: `turn_start`, `before_think`,
`after_think`, `tool_call`, `turn_end`. Return values are ignored; a hook that
raises is reported and skipped.

**plan mode** — the mode where only `plan_safe` tools are offered to the model. The
enforcement is the tool menu, not the prompt.

**raw_content** — the provider's own response blocks, stored verbatim in history
so tool results keep referring to real tool-call ids.

**Thought** — the only object a brain returns: text, tool calls, raw content,
reasoning.

**ToolContext** — the small object passed to every tool; today it carries `Memory`,
tomorrow whatever else a tool is allowed to see.

**tool_result** — the block that carries a tool's string output back to the model,
paired with the `tool_use_id` of the call that requested it.

## Appendix C — Turning this into `book.html`

The text is deliberately boring Markdown so any converter works. Two common paths:

```bash
# pandoc: one file in, one file out, with a table of contents
pandoc EXPLAINER.md -f gfm -t html5 --standalone --toc --toc-depth=2 \\
       --metadata title="Nanocode, explained" -o book.html
```

```bash
# or let Python Markdown handle it (fenced code + tables + details)
python -m markdown EXPLAINER.md -f fenced_code,tables,attr_list -o book.html
```

Things to check after conversion:

- **`<details>` blocks** need raw HTML passthrough (both converters above keep it).
- **ASCII diagrams** must stay in `<pre>` — do not let a converter wrap them at 80
  columns. `pandoc` respects fenced blocks; if your pipeline re-flows text, add
  `white-space: pre` to `pre` in the stylesheet.
- **Table of contents links** (`#ch01` … `#ch12`) rely on the `<a id="chNN">`
  anchors placed before each chapter heading; both converters preserve them.

If you want the diagrams to *move*, keep the ASCII as the source of truth and add
a small CSS animation for the HTML build, for example a pulsing dot that walks the
four contracts in Appendix A:

```html
<style>
  @keyframes hop { 0%,100% { opacity:.35 } 50% { opacity:1 } }
  .lane span { animation: hop 2.4s infinite }
  .lane span:nth-child(2) { animation-delay:.6s }
  .lane span:nth-child(3) { animation-delay:1.2s }
  .lane span:nth-child(4) { animation-delay:1.8s }
</style>
<p class="lane"><span>Agent</span> → <span>Brain</span> → <span>Thought</span> → <span>Tool</span></p>
```

Keep such extras out of the Markdown source: the book should read correctly with
no CSS at all, which is also what makes it printable.
"""


def demote(text):
    """Push every heading down one level, leaving fenced code untouched."""
    out, in_fence = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith("#"):
            line = "#" + line
        out.append(line)
    return "\n".join(out).strip()


def main():
    parts = [HEADER]
    for chapter in CHAPTERS:
        source = ROOT / chapter / f"EXPLAINER_{chapter}.md"
        body = demote(source.read_text(encoding="utf-8"))
        parts.append(f'<a id="ch{chapter[2:]}"></a>\n\n{body}\n')
    parts.append(APPENDIX)

    combined = "\n".join(parts)
    (ROOT / "EXPLAINER.md").write_text(combined, encoding="utf-8")

    chapters = len(CHAPTERS)
    print(f"EXPLAINER.md written: {len(combined.splitlines())} lines from {chapters} chapters")
    missing = [c for c in CHAPTERS if not (ROOT / c / f"EXPLAINER_{c}.md").exists()]
    if missing:
        print("missing chapter files:", missing)


if __name__ == "__main__":
    main()
