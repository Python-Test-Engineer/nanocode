---
name: build-pictures
description: Use when turning chapter ASCII diagrams into an animated single-file HTML page in the book.html style.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [book, diagrams, animation, svg, html, teaching, nanocode]
    related_skills: [make-book, book-project-guide, markdown-book-two-pane]
---

# build-pictures: every chapter's central diagram, animated

## When to Use

Load this when you want the pictures in a book/repo — the `## The idea in one
picture` ASCII blocks — as one readable page where the diagrams **move**:

- packets travel along the arrows;
- loops visibly loop;
- branches split into allowed/refused or tools/answers;
- sessions fill, hooks fire, subagents recurse;
- the original ASCII stays available under each animation.

This skill is the runnable implementation used for this repo's
`pictures.html`. It reuses the exact shell of `book.html` (sidebar TOC, filter,
scroll-spy, progress bar, copy buttons, mobile drawer, dark mode, print styles,
and the live **Aa** appearance panel) and adds an SVG animation layer.

```
build-pictures/
  SKILL.md                         workflow, animation rules, verification
  scripts/build_pictures.py        extract + compose the whole page
  references/animation-recipes.md  SVG primitives, timing, and the 15 patterns
```

## Quickstart

Run from the repository root (the directory containing `book.html`, `chNN/`,
and the chapter EXPLAINER files):

```bash
python skills/build-pictures/scripts/build_pictures.py --root .
# writes ./pictures.html
```

Then open `pictures.html` in a browser. Useful flags:

| flag | default | meaning |
|---|---|---|
| `--root` | current directory | repository root containing `chNN/` and `book.html` |
| `--book` | `<root>/book.html` | page whose `<style>` and scripts are reused |
| `--out` | `<root>/pictures.html` | output file |

The builder has no third-party dependencies: Python 3.11+, stdlib only. The
output page also has no runtime dependency except the existing Google Fonts
`<link>` inherited from `book.html`.

## How the builder works

1. **Reuse the house shell.** Read `book.html` and extract its `<style>`,
   `<script>` (TOC/filter/copy/mobile/appearance panel), the appearance button,
   and the `#stylepanel` aside. This is why the result feels like the book
   rather than a separate mini-site.
2. **Extract the ASCII source.** For chapters 1-11 and 14-15 read the first
   fenced block under `## The idea in one picture`. Chapter 12 uses
   `## The finished architecture in one picture`; chapter 13 has no literal
   "idea in one picture", so the builder uses the four sound-event lines from
   "Why sound at all".
3. **Wrap it.** Every chapter becomes an `<h2 id="chNN">`, a short caption, one
   animated SVG, a Replay button, and a collapsed `<details>` containing the
   original ASCII in a `<pre>`.
4. **Add the animation layer.** `EXTRA_CSS` defines the SVG diagram language
   (`.svg-box`, `.svg-line`, `.svg-packet`, `.svg-zone`, …), the picture-page
   layout, print/reduced-motion rules, and the pause styles. `own_script` adds
   Replay and Pause motion on top of the book's existing script.
5. **Generate the sidebar.** The TOC is one `.chapter` link per picture, so the
   book's existing filter and scroll-spy work unchanged.

The ASCII is never discarded. Animations are an *additional* rendering; the
original block remains the source of truth and is copyable.

## Anatomy of one chapter

```python
CHAPTERS = [(1, "The event loop (there is no AI yet)"), ...]

CAPTIONS[1] = "A packet walks the loop: ask, handle, answer, repeat."

def diagram_1():
    i = 1
    inner = "".join([
        node(300, 30, 260, 55, "main() loop"),
        node(335, 130, 190, 65, "Agent.handle_input()", "turns text into text"),
        line(i, "M430,195 L430,285"),
        packet("M320,85 C250,105 155,105 155,160", 6, 0),
    ])
    return svg(i, "aria label", inner)

DIAGRAMS = {1: diagram_1, ...}
```

When adding a chapter or changing a diagram:

1. Add/update the `CHAPTERS` tuple.
2. Add `CAPTIONS[num]`.
3. Write `diagram_N()` using the primitives in
   `references/animation-recipes.md`.
4. Register it in `DIAGRAMS`.
5. If the source heading differs, add `SOURCE_HEADING[num]`; if extraction is
   unusual, extend `extract_picture()`.
6. Rebuild and inspect the result as a browser page, not just as source.

## Animation rules that keep it legible

- **One idea per diagram.** The moving packet should trace the chapter's single
  new mechanism, not every implementation detail.
- **Motion follows the ASCII arrows.** Keep the original topology: loops loop,
  branches branch, cycles return to the right box.
- **Show the contract, not the code.** A box says `Brain.think()`, not a 30-line
  excerpt. The book already carries the code.
- **Use the palette variables.** All fills/strokes come from `--surface`,
  `--line`, `--terra`, `--muted`, etc. Hard-coded colours break dark mode and the
  **Aa** panel.
- **Respect reduced motion.** `prefers-reduced-motion` disables CSS animation;
  the page script calls `svg.pauseAnimations()` for SVG/SMIL. Replay and Pause
  motion remain available.
- **Print must make sense.** Hide the animation toolbar, keep the SVG static,
  and restore `.turn` opacity and `meter` width so the printed diagram is not
  caught mid-fade.
- **No external images or JS libraries.** Inline SVG + CSS + the book's vanilla
  JS. The page must open from `file://`.

### SVG primitives

| helper | purpose |
|---|---|
| `node(x, y, w, h, title, sub)` | rounded component box, centred label and optional sub-lines |
| `label(x, y, text, cls)` | annotation text |
| `line(idx, path)` | arrow with marker `#arrow{idx}` |
| `packet(path, dur, begin)` | circle moving along an SVG path via `animateMotion` |
| `svg(idx, aria, inner, height)` | wraps the diagram, unique marker, ARIA label |
| `packet(...)` with a `begin` offset | stagger multiple travellers on the same route |

Every SVG gets its **own marker id** (`arrow1`, `arrow2`, …). Reusing one global
marker across sibling SVGs is fragile in some browsers.

### Pattern catalogue

| chapter | visual pattern |
|---|---|
| 01 event loop | packet around a closed loop + exit branch |
| 02 raw request | outbound and return packet on parallel lanes |
| 03 conversation growth | three columns, each turn glows, arrows to one brain |
| 04 provider registry | one Brain fanning out to three providers |
| 05 agentic loop | Thought branching to answer or tools, then looping back |
| 06 session vs memory | RAM zone + file zone, write down / system-prompt up |
| 07 plan/act | full list splitting into two filtered menus |
| 08 list/search | sequential read-only narrowing flow |
| 09 run/error/fix | feedback cycle + compaction meter |
| 10 local vs cloud | machine zone vs internet zone, same contract |
| 11 web search | query branches to internal knowledge or search, results return as text |
| 12 architecture | four contract arrows with packets |
| 13 hooks | event bus fanning out to sounds |
| 14 sandbox | guard pipeline splitting to allowed/refused, back to a string |
| 15 subagents | parent stack → spawn → child loop → one string back |

## Verify before handing it over

Rebuild, then open the page in Chrome and check:

```bash
python skills/build-pictures/scripts/build_pictures.py --root .
```

- `#toc .chapter` count = number of chapters (15 here).
- `#content section.picture-chapter` count = same.
- every chapter has one `svg.diagram` and one `details.source` with `<pre>`.
- clicking **Replay** restarts that diagram.
- **Pause motion** freezes both CSS and SVG motion; clicking again resumes.
- the filter hides non-matching chapter links.
- scroll-spy highlights the chapter you are reading; progress bar advances.
- dark mode and **Aa** still work (the shell is inherited).
- print preview: sidebar/toolbar hidden, no text overflow, no mid-animation bar.

For a fast static render of every page (useful for spotting overflow), print to
PDF with headless Chrome and render the pages with PyMuPDF:

```bash
"/c/Program Files/Google/Chrome/Application/chrome.exe" --headless=new \
  --disable-gpu --no-sandbox --print-to-pdf=/tmp/pictures.pdf \
  "file:///C:/path/to/pictures.html"

python - <<'PY'
import pymupdf
doc = pymupdf.open('/tmp/pictures.pdf')
for n in range(doc.page_count):
    doc[n].get_pixmap(dpi=120).save(f'/tmp/page_{n+1}.png')
PY
```

Inspect at least every chapter that contains long labels or a branch. SVG text
does not wrap: overflow is the most common defect.

## Pitfalls

- **Text wider than its box.** SVG does not wrap. Widen the node, shorten the
  label, or lower the font size. Check `localhost:11434`, long file paths,
  `edit_file(path, old, new)`, and `brain.think(conversation)`.
- **A path that crosses a box or label.** The loop-back arrow is the usual
  offender. Redraw the curve, move the annotation, or move the destination box.
- **Escaping twice.** `label()` escapes text, so pass `>` not `&gt;`. Passing
  `&gt;` prints the literal entity.
- **Global marker IDs.** Each `svg()` call must get a distinct `idx`; otherwise
  the second diagram can borrow the first diagram's arrowhead.
- **Animation at time zero in print.** Set static CSS for `.svg-meter-fill` and
  `.turn` inside `@media print`; otherwise the print snapshot can be empty/faded.
- **Touching the ASCII.** Do not "tidy" the original diagram in the animated
  version. The ASCII stays verbatim in the `<details>` block.
- **Reimplementing the shell.** Do not hand-copy the sidebar/style panel; extract
  them from `book.html`. That is what keeps `pictures.html` and `book.html`
  visually identical after a theme change.
- **Assuming chapter 13 has the same heading.** It does not. Its picture is the
  four event→sound lines; keep that special case explicit.
- **Forgetting reduced motion.** A looping SVG with no pause is hostile to some
  readers, and `animateMotion` ignores ordinary CSS animation rules — pause it
  with the SVG API.

## Files

- `scripts/build_pictures.py` — the full generator. `--help` for flags. Sections:
  extraction, SVG helpers, `diagram_N()` functions, `EXTRA_CSS`, page assembly,
  Replay/Pause script.
- `references/animation-recipes.md` — coordinates, timing, CSS class reference,
  branch/loop recipes, and a checklist for adding a new chapter.
