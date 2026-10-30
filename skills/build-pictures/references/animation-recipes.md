# Animation recipes for `build-pictures`

The generator deliberately has a small SVG vocabulary. Learn six primitives and
you can draw every picture in the book without adding a library.

## The canvas

Every diagram uses the same coordinate system:

```
viewBox="0 0 860 H"      H = 380 normally, 390-530 for tall diagrams
```

Width 860 is fixed. Heights are chosen per picture; the SVG scales to the reading
column through CSS (`width: 100%; height: auto`). Coordinates are absolute, so
there is no responsive reflow inside the diagram — keep labels short and test
the page at mobile width.

```python
def svg(idx, aria, inner, height=380):
    ...
```

`idx` must be unique per diagram. It creates the arrow marker id
`arrow{idx}` and keeps each SVG self-contained.

## Primitives

```python
node(x, y, w, h, title, sub=None, cls="", rx=12)
label(x, y, text, cls="svg-label", anchor="middle")
line(idx, d, cls="svg-line")
packet(d, dur=5, begin=0, r=5)
```

### `node`

```python
node(335, 130, 190, 65, "Agent.handle_input()", "turns text into text")
```

- `title` is one line, centred, mono 14px.
- `sub` is a string or a list of strings, centred, sans 12px.
- `cls="accent"` gives the terracotta active style; `ok` and `deny` are used by
  the sandbox picture.

The text is **not wrapped**. If a label is too long, widen the box or shorten the
label. Estimate ~8.4px per mono character at 14px.

### `line`

```python
line(1, "M320,85 C250,105 155,105 155,130")
```

A path plus the local arrow marker. The endpoint is where the arrowhead lands, so
aim at the destination box edge, not its centre.

### `packet`

```python
packet("M220,57 L450,57 L590,57", 8, 0)   # first traveller
packet("M220,57 L450,57 L590,57", 8, 3)   # second, three seconds later
```

Use `begin` to stagger packets on one route. For a cycle, a single long path with
a longer duration reads better than several disjoint packets.

`animateMotion` follows the path exactly. It ignores CSS `animation-play-state`,
so the page pauses it with `svg.pauseAnimations()`.

## CSS classes available inside the SVG

| class | use |
|---|---|
| `svg-box` | default component |
| `svg-box accent` | the current/central component |
| `svg-box ok` / `svg-box deny` | allowed / refused branch |
| `svg-title` | box title |
| `svg-sub` | box sub-line |
| `svg-label` | normal annotation |
| `svg-label-sm` | faint caption / lane label |
| `svg-note` | terracotta callout (for example `/q ?`) |
| `svg-line` | arrow shaft |
| `svg-packet` | moving dot |
| `svg-chip` + `svg-chiptext` | conversation-message chip |
| `svg-zone` | dashed container (session, machine, internet, memory) |
| `svg-zone memory` | highlighted memory zone |
| `svg-list` | mono list row |
| `svg-list strike` | filtered-out row |
| `svg-meter-bg` / `svg-meter-fill` | context-window meter |
| `turn` | a column that fades in/out in sequence |
| `glow` | a node that pulses |

All colours are CSS custom properties. Never write `fill="#d97757"` in a diagram;
use the classes or `var(--terra)` in custom CSS.

## Recipes

### 1. Closed loop (chapter 1)

Place four boxes around the canvas. Draw three forward arrows and one return
curve. One packet traverses the whole loop:

```python
packet(
    "M320,85 C250,105 155,105 155,160 "
    "L335,160 L525,160 L705,160 C750,150 760,75 560,58",
    6, 0,
)
```

Add a second short packet for an exit branch (`/q` → `AgentStop`) with a later
`begin`, so the eye sees the normal path first.

### 2. Request / response lanes (chapter 2)

Two parallel horizontal paths: request at `y=170`, response at `y=215`. The
request packet runs left→right; the response packet right→left with `begin=2.5`.
Labels sit above and below the lanes.

### 3. Growing conversation (chapter 3)

Three columns of chips. Wrap each column in `<g class="turn"
style="animation-delay:Ns">`; the `turnGlow` keyframe makes the active turn
brightest in sequence. Every column has a short arrow into one central
`brain.think(conversation)` box.

### 4. One interface, many providers (chapter 4)

Agent → Brain is one arrow. Brain fans out to three provider boxes with three
slightly different curves. Stagger the packets so they alternate providers. The
agent only ever sits on the left of the single interface arrow.

### 5. Branch and return (chapter 5)

The decision node has two outgoing edges:

- no tool calls → `answer`;
- tool calls → `execute each tool` → `append results` → back to `brain.think()`.

The return path should visibly re-enter the brain, not stop at the canvas edge.
A `one iteration` sub-label on the tools box explains the loop unit.

### 6. Two zones (chapters 6, 10)

Draw two large `svg-zone` rectangles. The top/left is transient (RAM, local
machine); the bottom/right is durable or external (memory file, internet).
Packets that cross the zone boundary carry the chapter's lesson:

- ch06: `save_memory writes` down, `system prompt every request` up;
- ch10: local model inside the machine, providers outside it.

### 7. Filter / split (chapter 7)

A full list box at the top, two large menu boxes below. Use `.svg-list` for rows
and `.svg-list.strike` for tools that were filtered out. The `planPulse` /
`actPulse` animations alternate the highlighted mode.

### 8. Sequential narrowing (chapter 8)

A task at the top, then list → tree → search → matches → edit. Packets should
follow the sequence, not run in parallel: the point is that each read-only step
narrows the next one.

### 9. Feedback cycle + meter (chapter 9)

Top half: write → run → output → model reads error → edit → run again. Bottom
half: `svg-meter-bg` with `svg-meter-fill`; the fill animates to the 75% mark,
then an arrow runs to `summarise history` and `summary`.

Print/reduced motion must force the fill to its final width:

```css
@media print {
  .svg-meter-fill { animation: none !important; width: 270px !important; }
}
```

### 10. Query branches (chapter 11)

A wide query box at the top. Two branches: internal knowledge and `search_web`.
Search results (Title/URL/Summary) return as text to the model box. The returned
packet should end at the model, not at a special "web" component — there is no
special web path in the agent.

### 11. Architecture contracts (chapter 12)

Four boxes: `nanocode.py` at the top, `llm.py` left, `tools.py` right,
`ui.py + hooks.py` below. Four arrows, each with its own packet and label:

- conversation + tool menu → Brain
- Thought → Agent
- ToolContext + args → Tool
- a string → Agent

Keep the labels near their shafts, and avoid letting a return curve cross the
central down-arrow.

### 12. Event bus (chapter 13)

`Hooks bus` at top → four event boxes → four sound boxes. One packet per lane,
staggered `begin` by lane index. A small `♪` beside each lane makes the payload
obvious without introducing audio in the page.

### 13. Gate with two outcomes (chapter 14)

A vertical guard pipeline:

```
model → WriteFile.execute → context.guard → sandbox.check
```

Then split into `allowed` and `refused`. Both branches converge on a single
`tool returns a string` box: the lesson is that refusal is data, not an
exception. Use `svg-box ok` and `svg-box deny`, and send two packets with
different `begin` times down the two branches.

### 14. Recursion (chapter 15)

Parent stack on the left, child stack on the right. The critical edges are:

- `context.spawn` → `child._agentic_loop()` (the tool asks, it does not build);
- child loop → its own tool calls → back to child loop (recursion);
- child `answer` → parent `tool_result` (one string);
- parent `thought: merged answer` (the parent's conversation grew by one message).

A single long packet can trace spawn → child work → return. Label the return
`one message back`; that is the economics of a subagent.

## Adding a new chapter

1. Add `(N, "Title")` to `CHAPTERS`.
2. Add `CAPTIONS[N]`.
3. If the source heading is unusual, add `SOURCE_HEADING[N]` or extend
   `extract_picture()`.
4. Write `diagram_N()` using the primitives. Start from the closest recipe above.
5. Register it in `DIAGRAMS`.
6. Rebuild:

   ```bash
   python skills/build-pictures/scripts/build_pictures.py --root .
   ```

7. Render the page to PDF or open it in a browser and check every new diagram for:
   - text inside its box;
   - labels not sitting on an arrow or another label;
   - branch arrows ending at the correct box edge;
   - loop-back arrows re-entering the intended node;
   - reduced-motion/print snapshots still readable.

## Timing conventions

| effect | duration | notes |
|---|---|---|
| single short edge | 4-5s | one packet is enough |
| full architecture loop | 6-10s | give the eye time to follow |
| staggered providers / events | 1.5-2.5s apart | use `begin` |
| turn columns | 6s cycle, 2s apart | `.turn` animation delays |
| meter | 6s | fill to 75%, hold, reset |

The page is a reading aid, not a video. Slower is almost always clearer.
