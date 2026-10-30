#!/usr/bin/env python3
"""Build pictures.html: every chapter's "idea in one picture", animated.

The static ASCII stays the source of truth. This script extracts it from the
chapter EXPLAINER files, wraps it in the same shell as book.html, and adds an
animated SVG version of each diagram.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BOOK = ROOT / "book.html"
OUT = ROOT / "pictures.html"

CHAPTERS = [
    (1, "The event loop (there is no AI yet)"),
    (2, "First contact (one raw request)"),
    (3, "The first brain (and the conversation becomes memory)"),
    (4, "More than one brain (an interface, a registry, retries)"),
    (5, "Hands (tools, and the loop becomes a cycle)"),
    (6, "Memory that survives (a file, not a database)"),
    (7, "Plan mode (safety by construction, not by instruction)"),
    (8, "Eyes on the project (list and search)"),
    (9, "Closing the loop (run it, read the error, fix it)"),
    (10, "Local models (a brain on your own machine)"),
    (11, "A window outside (web search)"),
    (12, "Capstone (the whole agent, and how to read it)"),
    (13, "Sound (the agent's hooks you can hear)"),
    (14, "A sandbox for ACT mode"),
    (15, "Subagents, and four ways to arrange them"),
]

CAPTIONS = {
    1: "A packet walks the loop: ask, handle, answer, repeat. The /q branch leaves the loop through AgentStop.",
    2: "One request goes out; one JSON response comes back. Nothing else exists yet.",
    3: "Every turn carries the whole conversation. Watch the same list grow as it enters brain.think().",
    4: "The agent sees one Brain. The registry chooses which provider sits behind it.",
    5: "Thought asks for a tool, the result is appended, and the same loop runs again. No tool calls means answer.",
    6: "The session list dies at exit. The memory file is written back into the system prompt on every request.",
    7: "The full tool list is filtered by mode. This menu is the safety mechanism; the prompt is only a hint.",
    8: "Listing and searching are cheap, read-only moves. They narrow the place where the expensive edit will happen.",
    9: "The error becomes text the model can read, so the loop closes: run, read, edit, run again. Under it, compaction keeps the context small.",
    10: "The same Brain contract on both sides: a local Ollama model, or a cloud provider reached with a key.",
    11: "The query can be answered from memory or sent through search_web. Either way the model receives text.",
    12: "Four arrows hold the finished agent together: conversation, Thought, ToolContext, and a string.",
    13: "The hook bus is a seam. Register a sound per event, and the loop becomes audible without changing the loop.",
    14: "Every write passes the guard and the sandbox. Allowed writes open the file; refused writes return an error string.",
    15: "A tool asks the parent to spawn. The child runs the same loop, one stack frame deeper, and returns one string.",
}

SOURCE_HEADING = {
    12: "The finished architecture in one picture",
    13: "Why sound at all — the four events",
}


def T(value: str) -> str:
    return html.escape(str(value), quote=False)


def node(x, y, w, h, title, sub=None, cls="", rx=12):
    """A rounded diagram box, centred title, optional small sub-lines."""
    out = [f'<rect class="svg-box {cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}"/>']
    subs = [] if sub is None else ([sub] if isinstance(sub, str) else list(sub))
    title_y = y + h / 2 + (5 if not subs else -4 - 8 * (len(subs) - 1))
    out.append(f'<text class="svg-title" x="{x + w / 2}" y="{title_y}" text-anchor="middle">{T(title)}</text>')
    for i, s in enumerate(subs):
        out.append(f'<text class="svg-sub" x="{x + w / 2}" y="{title_y + 18 + i * 15}" text-anchor="middle">{T(s)}</text>')
    return "".join(out)


def label(x, y, value, cls="svg-label", anchor="middle"):
    return f'<text class="{cls}" x="{x}" y="{y}" text-anchor="{anchor}">{T(value)}</text>'


def line(idx, d, cls="svg-line"):
    return f'<path class="{cls}" marker-end="url(#arrow{idx})" d="{d}"/>'


def packet(d, dur=5, begin=0, r=5):
    return (
        f'<circle class="svg-packet" r="{r}">'
        f'<animateMotion dur="{dur}s" begin="{begin}s" repeatCount="indefinite" path="{d}"/>'
        "</circle>"
    )


def svg(idx, aria, inner, height=380):
    return f'''<svg class="diagram" viewBox="0 0 860 {height}" role="img" aria-label="{html.escape(aria)}">
  <defs>
    <marker id="arrow{idx}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path class="arrowhead" d="M0,0 L10,5 L0,10 z"/>
    </marker>
  </defs>
  {inner}
</svg>'''


def diagram_1():
    i = 1
    inner = "".join([
        node(300, 30, 260, 55, "main() loop"),
        node(60, 130, 190, 60, "ui.ask()", "the prompt"),
        node(335, 130, 190, 65, "Agent.handle_input()", "turns text into text"),
        node(610, 130, 190, 60, "ui.answer()", "the output"),
        node(335, 285, 190, 55, "raise AgentStop", "only main() catches it", cls="accent"),
        label(440, 208, "/q ?", "svg-note"),
        line(i, "M320,85 C250,105 155,105 155,130"),
        line(i, "M250,160 L335,160"),
        line(i, "M525,160 L610,160"),
        line(i, "M705,130 C705,65 650,58 560,58"),
        line(i, "M430,195 L430,285"),
        packet("M320,85 C250,105 155,105 155,160 L335,160 L525,160 L705,160 C750,150 760,75 560,58", 6, 0),
        packet("M430,195 L430,285", 6, 3),
        label(155, 225, "prompt", "svg-label-sm"),
        label(430, 365, "only step 2 grows in later chapters", "svg-label-sm"),
    ])
    return svg(i, "The event loop: main calls ui.ask, Agent.handle_input, ui.answer, and loops. /q raises AgentStop.", inner)


def diagram_2():
    i = 2
    inner = "".join([
        node(50, 150, 210, 80, "your script", ["POST /chat/completions", "{ model, messages }"]),
        node(330, 150, 200, 80, "the provider", ["auth + routing"]),
        node(610, 150, 200, 80, "the model", ["tokens in → tokens out"]),
        line(i, "M260,170 L330,170"),
        line(i, "M530,170 L610,170"),
        line(i, "M610,215 L530,215"),
        line(i, "M330,215 L260,215"),
        packet("M260,170 L610,170", 5, 0),
        packet("M610,215 L260,215", 5, 2.5),
        label(445, 152, "request", "svg-label-sm"),
        label(445, 238, "JSON response", "svg-label-sm"),
        label(430, 330, "no loop · no tools · no memory", "svg-label-sm"),
    ])
    return svg(i, "A request travels from your script through the provider to the model, and a JSON response travels back.", inner)


def diagram_3():
    i = 3
    cols = [
        (50, "turn 1", ["user: my name is Sam"]),
        (315, "turn 2", ["user: my name is Sam", "assistant: Hello Sam", "user: what is my name?"]),
        (580, "turn 3", ["user: my name is Sam", "assistant: Hello Sam", "user: what is my name?", "assistant: Your name is Sam", "user: and again?"]),
    ]
    inner = []
    for n, (x, title, chips) in enumerate(cols):
        inner.append(f'<g class="turn" style="animation-delay:{n * 2}s">')
        inner.append(label(x + 115, 40, title, "svg-title"))
        for k, chip in enumerate(chips):
            y = 58 + k * 39
            inner.append(f'<rect class="svg-chip" x="{x}" y="{y}" width="230" height="30" rx="7"/>')
            inner.append(f'<text class="svg-chiptext" x="{x + 12}" y="{y + 20}">{T(chip)}</text>')
        inner.append("</g>")
    inner.extend([
        node(280, 305, 300, 50, "brain.think(conversation)", cls="accent"),
        line(i, "M165,295 C165,305 260,300 280,318"),
        line(i, "M430,295 L430,305"),
        line(i, "M695,295 C695,305 600,300 580,318"),
        packet("M165,295 C165,305 260,300 280,318", 5, 0),
        packet("M430,295 L430,305", 5, 1.5),
        packet("M695,295 C695,305 600,300 580,318", 5, 3),
        label(430, 372, "the arrow always carries everything — that is the memory", "svg-label-sm"),
    ])
    return svg(i, "Three turns of a conversation grow a list, and each full list is passed into brain.think.", inner)


def diagram_4():
    i = 4
    inner = "".join([
        node(30, 150, 150, 70, "Agent", "one contract"),
        node(235, 145, 190, 80, "brain.think()", "same call every time", cls="accent"),
        node(540, 30, 270, 70, "Claude", "Anthropic /messages"),
        node(540, 145, 270, 70, "DeepSeek", "anthropic-compatible"),
        node(540, 260, 270, 70, "OpenRouter", "OpenAI chat/completions"),
        line(i, "M180,185 L235,185"),
        line(i, "M425,167 C470,135 500,95 540,75"),
        line(i, "M425,185 L540,185"),
        line(i, "M425,205 C470,235 500,270 540,290"),
        packet("M180,185 L235,185", 5, 0),
        packet("M425,167 C470,135 500,95 540,75", 6, 0.8),
        packet("M425,185 L540,185", 6, 2.2),
        packet("M425,205 C470,235 500,270 540,290", 6, 3.6),
        label(90, 265, "the agent sees only this arrow", "svg-label-sm"),
        label(675, 365, "BRAINS[name] chooses the provider", "svg-label-sm"),
    ])
    return svg(i, "The Agent calls one Brain interface. Behind it, a registry can route to Claude, DeepSeek, or OpenRouter.", inner)


def diagram_5():
    i = 5
    inner = "".join([
        node(40, 30, 180, 55, "conversation"),
        node(270, 30, 180, 55, "brain.think()"),
        node(500, 30, 180, 55, "Thought"),
        node(500, 125, 180, 55, "tool calls?"),
        node(720, 125, 120, 55, "answer", cls="accent"),
        node(240, 250, 250, 60, "execute each tool", "one iteration"),
        node(540, 250, 240, 60, "append results", "as a USER message"),
        line(i, "M220,57 L270,57"),
        line(i, "M450,57 L500,57"),
        line(i, "M590,85 L590,125"),
        line(i, "M680,152 L720,152"),
        line(i, "M565,180 L565,220 L365,220 L365,250"),
        line(i, "M490,280 L540,280"),
        line(i, "M660,250 C760,220 760,120 360,85"),
        packet("M220,57 L450,57 L590,57 L590,150 L565,180 L365,220 L365,280 L490,280 L660,280 C760,240 760,130 360,85", 9, 0),
        packet("M590,180 L720,152", 5, 3.5),
        label(600, 213, "tool_calls", "svg-label-sm"),
        label(705, 143, "no calls", "svg-label-sm"),
        label(430, 365, "MAX_ITERATIONS = 50 — a confused model cannot loop forever", "svg-label-sm"),
    ])
    return svg(i, "The agentic loop: conversation goes to the brain, a Thought may request tools, results are appended, and the loop repeats until an answer.", inner)


def diagram_6():
    i = 6
    inner = "".join([
        '<rect class="svg-zone" x="60" y="25" width="740" height="150" rx="14"/>',
        label(430, 50, "session — lives in RAM, dies on exit", "svg-title"),
        node(80, 75, 190, 55, "conversation"),
        node(330, 75, 170, 55, "brain"),
        node(560, 75, 190, 55, "tools"),
        line(i, "M270,102 L330,102"),
        line(i, "M500,102 L560,102"),
        line(i, "M655,130 C655,155 190,155 175,130"),
        packet("M270,102 L560,102 C655,102 655,155 175,155 L175,130", 6, 0),
        '<rect class="svg-zone memory" x="60" y="255" width="740" height="90" rx="14"/>',
        label(430, 280, ".nanocode/memory.md — survives restarts", "svg-title"),
        label(430, 305, '"I am Nanocode, a helpful coding assistant."', "svg-sub"),
        label(430, 325, '"The user prefers tabs and calls me Nan."', "svg-sub"),
        line(i, "M620,175 C620,215 560,230 500,255"),
        line(i, "M300,255 C300,220 300,205 300,175"),
        packet("M620,175 C620,215 560,230 500,255", 5, 0),
        packet("M300,255 C300,220 300,205 300,175", 5, 2.5),
        label(600, 207, "save_memory writes", "svg-label-sm"),
        label(205, 218, "system prompt every request", "svg-label-sm"),
    ])
    return svg(i, "A session is a conversation in RAM. A memory file survives restarts and is sent as the system prompt.", inner, height=380)


def diagram_7():
    i = 7
    plan = ["read_file", "write_plan", "save_memory", "no write / edit / run"]
    act = ["read_file", "write_plan", "save_memory", "write_file", "edit_file", "run_command"]
    inner = [
        node(280, 20, 300, 55, "full tool list", "read · write · edit · run · plan · memory"),
        '<rect class="svg-box plan" x="50" y="155" width="350" height="200" rx="12"/>',
        label(225, 184, 'mode == "plan"', "svg-title"),
    ]
    for k, item in enumerate(plan):
        cls = "svg-list strike" if item.startswith("no ") else "svg-list"
        inner.append(f'<text class="{cls}" x="76" y="{220 + k * 24}">{T(item)}</text>')
    inner.extend([
        '<rect class="svg-box act" x="460" y="155" width="350" height="200" rx="12"/>',
        label(635, 184, 'mode == "act"', "svg-title"),
    ])
    for k, item in enumerate(act):
        inner.append(f'<text class="svg-list" x="486" y="{220 + k * 24}">{T(item)}</text>')
    inner.extend([
        line(i, "M370,75 C320,105 250,120 225,155"),
        line(i, "M490,75 C540,105 610,120 635,155"),
        packet("M370,75 C320,105 250,120 225,155", 5, 0),
        packet("M490,75 C540,105 610,120 635,155", 5, 2.5),
        label(430, 365, "the menu is the guarantee; the prompt is only a hint", "svg-label-sm"),
    ])
    return svg(i, "The full tool list splits into a PLAN-mode menu without write, edit or run, and an ACT-mode menu with them.", inner)


def diagram_8():
    i = 8
    inner = "".join([
        node(60, 20, 740, 50, '"add a --verbose flag to the CLI"', cls="accent"),
        node(120, 105, 230, 60, "list_files"),
        node(470, 105, 320, 60, "ch01/  ch02/ ...  cli.py  README.md"),
        node(120, 210, 230, 60, "search_codebase"),
        node(470, 200, 320, 90, "cli.py matches", ["cli.py:42: parser = argparse.ArgumentParser()", 'cli.py:57: parser.add_argument("--name")']),
        node(250, 325, 360, 45, "read_file → edit_file", "the next chapter"),
        line(i, "M235,75 C235,90 235,95 235,105"),
        line(i, "M350,135 L470,135"),
        line(i, "M470,165 C420,185 400,190 350,220"),
        line(i, "M350,240 L470,240"),
        line(i, "M630,290 C630,315 540,320 540,325"),
        packet("M235,75 L235,105 L470,135 C540,145 540,200 470,220", 7, 0),
        packet("M350,240 L470,240", 4, 2.8),
        packet("M630,290 C630,315 540,320 540,325", 5, 4),
        label(430, 392, "two cheap, read-only tools replace expensive guessing", "svg-label-sm"),
    ])
    return svg(i, "A task goes through list_files, a file tree, search_codebase, matching lines, and then read_file and edit_file.", inner, height=400)


def diagram_9():
    i = 9
    inner = "".join([
        node(60, 30, 210, 60, "write_file / edit_file"),
        node(330, 30, 180, 60, "run_command"),
        node(560, 30, 240, 60, "STDOUT / STDERR"),
        node(560, 145, 240, 60, "model reads the error", "and proposes a fix"),
        node(290, 145, 240, 60, "edit_file(path, old, new)"),
        line(i, "M270,60 L330,60"),
        line(i, "M510,60 L560,60"),
        line(i, "M680,90 L680,145"),
        line(i, "M560,175 L530,175"),
        line(i, "M430,145 C430,120 430,100 430,90"),
        packet("M270,60 L510,60 L680,90 L680,175 L530,175 L430,175 L430,90", 8, 0),
        '<rect class="svg-meter-bg" x="60" y="285" width="360" height="22" rx="11"/>',
        '<rect class="svg-meter-fill" x="60" y="285" width="260" height="22" rx="11"/>',
        label(60, 272, "tokens used > 75% of window", "svg-label-sm", anchor="start"),
        node(480, 272, 170, 50, "summarise history"),
        node(690, 272, 120, 50, "summary"),
        line(i, "M420,296 L480,296"),
        line(i, "M650,296 L690,296"),
        packet("M420,296 L690,296", 5, 1.5),
        label(430, 365, "the error is information the model can act on", "svg-label-sm"),
    ])
    return svg(i, "A write and run loop: command output, error, model fix, edit, and run again. Below it compaction summarises a full context.", inner)


def diagram_10():
    i = 10
    inner = "".join([
        '<rect class="svg-zone" x="30" y="30" width="370" height="310" rx="14"/>',
        '<rect class="svg-zone" x="460" y="30" width="370" height="310" rx="14"/>',
        label(215, 58, "your machine", "svg-title"),
        label(645, 58, "the internet", "svg-title"),
        node(60, 90, 160, 55, "nanocode"),
        node(235, 90, 150, 55, "localhost:11434"),
        node(60, 180, 320, 55, "local model", "same Brain.think() contract", cls="accent"),
        node(235, 270, 150, 45, "ollama serve"),
        line(i, "M220,117 L235,117"),
        line(i, "M310,145 C310,160 250,160 220,180"),
        line(i, "M310,270 L310,235"),
        packet("M60,117 L380,117 C380,160 260,170 220,207", 6, 0),
        node(500, 90, 290, 55, "OpenRouter", "OpenAI chat/completions"),
        node(500, 165, 290, 55, "Claude", "Anthropic /messages"),
        node(500, 240, 290, 55, "DeepSeek", "anthropic-compatible"),
        label(645, 320, "key · network · $$$", "svg-label-sm"),
        label(215, 320, "private · offline", "svg-label-sm"),
        packet("M645,90 C720,90 720,240 790,267", 7, 0.8),
        label(430, 368, "/switch walks the registry; the agent does not care which one answers", "svg-label-sm"),
    ])
    return svg(i, "A local private model behind Ollama, versus cloud providers on the internet. Both satisfy the same Brain contract.", inner, height=390)


def diagram_11():
    i = 11
    inner = "".join([
        node(90, 20, 680, 50, '"why does pytest-asyncio 0.23 warn about event_loop?"', cls="accent"),
        node(50, 115, 270, 60, "internal knowledge", "training data, possibly stale"),
        node(430, 115, 380, 60, 'search_web("pytest-asyncio 0.23 ...")'),
        node(430, 215, 380, 90, "3 results, formatted", ["Title: ...", "URL: https://...", "Summary: ..."]),
        node(150, 330, 560, 45, "the model reads, then answers (or reads the page)"),
        line(i, "M310,70 C310,90 230,95 200,115"),
        line(i, "M550,70 C550,90 600,95 620,115"),
        line(i, "M620,175 L620,215"),
        line(i, "M430,260 C380,285 380,310 380,330"),
        line(i, "M250,175 C250,260 300,295 340,330"),
        packet("M550,70 L620,115 L620,215 L620,260 C560,300 480,320 430,330", 8, 0),
        packet("M310,70 C310,90 230,95 200,115", 5, 2.5),
        label(430, 392, "the tool returns text; there is no special web path in the agent", "svg-label-sm"),
    ])
    return svg(i, "A question branches into internal knowledge or search_web, whose formatted results go back to the model as text.", inner, height=400)


def diagram_12():
    i = 12
    inner = "".join([
        '<rect class="svg-box" x="200" y="20" width="460" height="110" rx="12"/>',
        label(430, 48, "nanocode.py", "svg-title"),
        label(270, 82, "main()", "svg-list"),
        label(405, 82, "Agent", "svg-list"),
        label(555, 82, "ui.answer()", "svg-list"),
        label(430, 112, "conversation · mode · hooks.emit(...)", "svg-sub"),
        node(60, 200, 250, 90, "llm.py", ["Brain.think()", "OpenRouter · Claude", "DeepSeek · Ollama"]),
        node(550, 200, 250, 90, "tools.py", ["execute(context, **args)", "read write edit run", "list search plan save web"]),
        node(280, 320, 300, 50, "ui.py + hooks.py", ["colour, events, trace"]),
        line(i, "M300,130 C250,155 210,170 185,200"),
        line(i, "M260,200 C280,170 330,155 380,130"),
        line(i, "M560,130 C610,155 650,170 675,200"),
        line(i, "M650,200 C630,170 580,155 520,130"),
        line(i, "M430,130 L430,320"),
        packet("M300,130 C250,155 210,170 185,200", 6, 0),
        packet("M260,200 C280,170 330,155 380,130", 6, 1.5),
        packet("M560,130 C610,155 650,170 675,200", 6, 3),
        packet("M650,200 C630,170 580,155 520,130", 6, 4.5),
        label(165, 165, "conversation + tool menu", "svg-label-sm"),
        label(335, 188, "Thought", "svg-label-sm"),
        label(695, 165, "ToolContext + args", "svg-label-sm"),
        label(550, 188, "a string", "svg-label-sm"),
        label(445, 185, "ui + hooks", "svg-label-sm"),
    ])
    return svg(i, "The finished architecture: nanocode connects to llm.py and tools.py, with ui and hooks observing the loop. Four arrows carry the contracts.", inner, height=390)


def diagram_13():
    i = 13
    events = [
        (60, "session_start", "session_start", "♪ tada"),
        (250, "turn_start", "turn_start", "♪ ding"),
        (440, "tool_call", "tool_call", "♪ chimes"),
        (630, "turn_end", "turn_end", "♪ notify"),
    ]
    inner = [node(320, 20, 220, 50, "Hooks bus", "events do not know who listens", cls="accent")]
    for x, name, label_text, sound in events:
        inner.append(node(x, 100, 170, 55, label_text, cls="glow"))
        inner.append(node(x, 235, 170, 65, sound, "plays on the speaker"))
        inner.append(line(i, f"M{x + 85},70 C{x + 85},80 {x + 85},90 {x + 85},100"))
        inner.append(line(i, f"M{x + 85},155 L{x + 85},235"))
        inner.append(packet(f"M{x + 85},155 L{x + 85},235", 5, (x - 60) / 240))
        inner.append(f'<text class="svg-note" x="{x + 142}" y="205">♪</text>')
    inner.extend([
        label(430, 345, "install(hooks) registers one sound per event", "svg-label-sm"),
        label(430, 368, "the agent loop never learns that sound exists", "svg-label-sm"),
    ])
    return svg(i, "The hook bus emits session_start, turn_start, tool_call and turn_end; each event is wired to a sound.", inner)


def diagram_14():
    i = 14
    inner = "".join([
        node(100, 20, 660, 55, 'model: write_file("C:\\Windows\\Temp\\proof.txt", ...)', "ACT mode only", cls="accent"),
        node(290, 100, 280, 50, "WriteFile.execute"),
        node(290, 175, 280, 50, "context.guard(path, \"write_file\")"),
        node(290, 250, 280, 55, "sandbox.Sandbox.check", "resolve → deny? → root prefix test"),
        label(430, 335, "allowed or refused?", "svg-note"),
        node(80, 360, 300, 70, "allowed", "open(path, \"w\") → success", cls="ok"),
        node(480, 360, 300, 70, "refused", "hooks.emit + ui.forbidden + sound", cls="deny"),
        node(230, 455, 420, 45, "tool returns a string", "success or FORBIDDEN — never an exception"),
        line(i, "M430,75 L430,100"),
        line(i, "M430,150 L430,175"),
        line(i, "M430,225 L430,250"),
        line(i, "M380,305 C320,325 240,330 230,360"),
        line(i, "M480,305 C540,325 620,330 630,360"),
        line(i, "M230,430 L230,455"),
        line(i, "M630,430 L630,455"),
        packet("M430,75 L430,305 C380,330 300,335 230,360", 7, 0),
        packet("M430,75 L430,305 C480,330 560,335 630,360", 7, 3.5),
        label(690, 340, "the model reads the error, and the loop continues", "svg-label-sm"),
    ])
    return svg(i, "A write request passes through WriteFile, the guard and the sandbox, then splits into allowed and refused paths. Both return a string.", inner, height=520)


def diagram_15():
    i = 15
    inner = "".join([
        label(430, 18, "one Python process", "svg-label-sm"),
        node(40, 30, 280, 50, "parent._agentic_loop()", cls="accent"),
        node(40, 105, 280, 50, "thought: run_subagent(task)"),
        node(40, 180, 280, 50, "tools.RunSubagent.execute"),
        node(40, 255, 280, 50, "context.spawn(task)", "the tool only ASKS"),
        node(40, 400, 280, 50, "tool_result: one string"),
        node(40, 470, 280, 45, "thought: the merged answer"),
        node(500, 30, 310, 50, "Agent._spawn_subagent"),
        node(500, 105, 310, 60, "fresh brain · conversation · tools", "fresh sandbox · hooks"),
        node(500, 190, 310, 50, "child._agentic_loop()", "the same method recursing", cls="accent"),
        node(500, 265, 310, 60, "child's own tool calls", "own context and budget"),
        node(500, 350, 310, 50, "answer: \"…\"", "one string"),
        line(i, "M180,80 L180,105"),
        line(i, "M180,155 L180,180"),
        line(i, "M180,230 L180,255"),
        line(i, "M580,80 L580,105"),
        line(i, "M580,165 L580,190"),
        line(i, "M655,240 C740,250 740,265 655,265"),
        line(i, "M655,325 L655,350"),
        line(i, "M320,280 C400,280 420,215 500,215"),
        line(i, "M655,400 C655,440 360,425 320,425"),
        line(i, "M180,450 L180,470"),
        packet("M180,80 L180,255 C260,255 300,240 500,215 L655,265 L655,400 C655,435 360,425 320,425", 10, 0),
        label(380, 290, "spawn", "svg-label-sm"),
        label(475, 440, "one message back", "svg-label-sm"),
        label(430, 510, "recursion through the tool table is what a subagent is", "svg-label-sm"),
    ])
    return svg(i, "The parent runs the agentic loop, calls run_subagent, spawns a child that runs the same loop, and receives one string back.", inner, height=530)


DIAGRAMS = {
    1: diagram_1, 2: diagram_2, 3: diagram_3, 4: diagram_4, 5: diagram_5,
    6: diagram_6, 7: diagram_7, 8: diagram_8, 9: diagram_9, 10: diagram_10,
    11: diagram_11, 12: diagram_12, 13: diagram_13, 14: diagram_14, 15: diagram_15,
}


def extract_picture(num: int) -> str:
    path = ROOT / f"ch{num:02d}" / f"EXPLAINER_ch{num:02d}.md"
    text = path.read_text(encoding="utf-8")
    if num == 13:
        blocks = re.findall(r"```[^\n]*\n(.*?)```", text, re.S)
        for block in blocks:
            if "session_start" in block and "turn_end" in block and "♪" in block:
                return block.strip("\n")
        raise RuntimeError("chapter 13 sound picture not found")

    heading = "## The finished architecture in one picture" if num == 12 else "## The idea in one picture"
    start = text.index(heading)
    rest = text[start + len(heading):]
    match = re.search(r"```[^\n]*\n(.*?)```", rest, re.S)
    if not match:
        raise RuntimeError(f"no fenced picture in chapter {num}")
    return match.group(1).strip("\n")


EXTRA_CSS = r"""
/* ============================================================
   pictures.html — the animated diagram layer
   ============================================================ */

.picture-intro {
  margin: 0 0 2.2rem;
  color: var(--muted);
  font-size: calc(var(--fs-content) * .74);
  line-height: 1.55;
}

.chapter-kicker {
  display: block;
  margin-bottom: .35rem;
  color: var(--terra-dark);
  font: 700 var(--fs-eyebrow)/1.2 var(--sans);
  letter-spacing: .14em;
  text-transform: uppercase;
}

.picture-lede {
  max-width: 62ch;
  margin: 0 0 1.4rem;
  color: var(--muted);
  font-size: calc(var(--fs-content) * .64);
  line-height: 1.55;
}

.anim-block {
  margin: 1.2rem 0 1.3rem;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--ivory);
  overflow: hidden;
}

.anim-stage {
  padding: 18px 18px 8px;
  background:
    radial-gradient(circle at 15% 20%, color-mix(in srgb, var(--terra) 8%, transparent), transparent 35%),
    radial-gradient(circle at 85% 80%, color-mix(in srgb, var(--terra) 7%, transparent), transparent 38%);
}

.diagram {
  display: block;
  width: 100%;
  height: auto;
  overflow: visible;
}

.anim-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 15px;
  border-top: 1px solid var(--line-soft);
  background: var(--surface);
}

.anim-caption {
  flex: 1 1 auto;
  color: var(--muted);
  font-size: var(--fs-section);
  line-height: 1.4;
}

.replay {
  flex: none;
  padding: 5px 11px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--ivory);
  color: var(--terra-dark);
  font: 600 var(--fs-section) var(--sans);
  cursor: pointer;
}

.replay:hover { border-color: var(--quote-border); background: var(--open-bg); }
.replay:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 1px; }

.source {
  margin: .8rem 0 1.2rem;
  padding: 0;
  overflow: hidden;
}

.source summary { padding: 12px 16px; }
.source pre { margin: 0; border-radius: 0; }
.source .src-heading { color: var(--stone); font-weight: 400; }

.sidebar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
}

#motionbtn {
  padding: 4px 9px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--ivory);
  color: var(--muted);
  font: var(--fs-foot) var(--sans);
  cursor: pointer;
}

#motionbtn:hover { border-color: var(--quote-border); color: var(--terra-dark); }

/* SVG diagram language */
.diagram text { user-select: none; }
.arrowhead { fill: var(--stone); }
.svg-box { fill: var(--surface); stroke: var(--line); stroke-width: 1.5; }
.svg-box.accent { fill: var(--active-bg); stroke: var(--terra); stroke-width: 2; }
.svg-box.ok { fill: var(--active-bg); stroke: var(--terra); }
.svg-box.deny { fill: var(--quote-bg); stroke: var(--quote-border); stroke-width: 2; }
.svg-title { fill: var(--ink); font: 600 14px var(--mono); }
.svg-sub { fill: var(--muted); font: 400 12px var(--sans); }
.svg-label { fill: var(--muted); font: 400 12px var(--sans); }
.svg-label-sm { fill: var(--stone); font: 400 11px var(--sans); letter-spacing: .02em; }
.svg-note { fill: var(--terra-dark); font: 700 16px var(--sans); }
.svg-line { fill: none; stroke: var(--stone); stroke-width: 1.8; }
.svg-dash { fill: none; stroke: var(--terra); stroke-width: 1.4; stroke-dasharray: 5 7; opacity: .45; animation: dash 1.6s linear infinite; }
.svg-packet { fill: var(--terra); filter: drop-shadow(0 0 5px var(--terra)); }
.svg-chip { fill: var(--surface); stroke: var(--line); stroke-width: 1; }
.svg-chiptext { fill: var(--muted); font: 11px var(--mono); }
.svg-zone { fill: var(--surface); stroke: var(--line); stroke-width: 1.4; stroke-dasharray: 5 5; }
.svg-zone.memory { fill: var(--open-bg); stroke: var(--quote-border); }
.svg-list { fill: var(--ink); font: 13px var(--mono); }
.svg-list.strike { fill: var(--stone); text-decoration: line-through; }
.svg-meter-bg { fill: var(--line-soft); }
.svg-meter-fill { fill: var(--terra); animation: meterFill 6s ease-in-out infinite; }
.turn { animation: turnGlow 6s ease-in-out infinite; }
.glow { animation: nodeGlow 4s ease-in-out infinite; }
.svg-box.plan { animation: planPulse 7s ease-in-out infinite; }
.svg-box.act { animation: actPulse 7s ease-in-out infinite; }

@keyframes dash { to { stroke-dashoffset: -48; } }
@keyframes meterFill {
  0%, 8% { width: 0; }
  52%, 92% { width: 270px; }
  100% { width: 270px; opacity: .25; }
}
@keyframes nodeGlow {
  0%, 100% { filter: none; }
  50% { filter: drop-shadow(0 0 8px var(--focus-ring)); }
}
@keyframes turnGlow {
  0%, 100% { opacity: .48; }
  8%, 28% { opacity: 1; }
  38%, 100% { opacity: .48; }
}
@keyframes planPulse {
  0%, 42%, 100% { stroke: var(--line); }
  8%, 30% { stroke: var(--terra); }
}
@keyframes actPulse {
  0%, 50%, 100% { stroke: var(--line); }
  58%, 82% { stroke: var(--terra); }
}

body.motion-paused .diagram * { animation-play-state: paused !important; }

@media (prefers-reduced-motion: reduce) {
  .svg-dash, .svg-meter-fill, .turn, .glow, .svg-box.plan, .svg-box.act { animation: none !important; }
  .svg-meter-fill { width: 270px !important; }
  .turn { opacity: 1 !important; }
}

@media (max-width: 980px) {
  .anim-stage { padding: 10px 8px 4px; }
  .anim-bar { align-items: flex-start; }
  .picture-lede { max-width: none; }
}

@media print {
  .anim-bar { display: none !important; }
  .anim-stage { padding: 0; background: none; }
  .anim-block, .source { break-inside: avoid; }
  .source pre { white-space: pre-wrap; }
  .svg-meter-fill { animation: none !important; width: 270px !important; }
  .turn { animation: none !important; opacity: 1 !important; }
}
"""


def build() -> None:
    book = BOOK.read_text(encoding="utf-8")
    style = re.search(r"<style>(.*?)</style>", book, re.S).group(1)
    scripts = re.findall(r"<script>(.*?)</script>", book, re.S)
    main_script = scripts[-1]
    aside = re.search(r'<aside id="stylepanel".*?</aside>', book, re.S).group(0)
    style_btn = re.search(r'<button id="stylebtn".*?</button>', book, re.S).group(0)

    toc = []
    sections = []
    for num, title in CHAPTERS:
        cid = f"ch{num:02d}"
        toc.append(
            f'<li class="chapter"><a href="#{cid}"><span class="num">{num:02d}</span>{T(title)}</a></li>'
        )
        ascii_pic = extract_picture(num)
        source_heading = SOURCE_HEADING.get(num, "The idea in one picture")
        sections.append(f"""
<section class="picture-chapter" aria-labelledby="{cid}">
  <h2 id="{cid}"><span class="chapter-kicker">Chapter {num:02d}</span>{T(title)}</h2>
  <p class="picture-lede">{T(CAPTIONS[num])}</p>
  <div class="anim-block">
    <div class="anim-stage">
      {DIAGRAMS[num]()}
    </div>
    <div class="anim-bar">
      <span class="anim-caption">The animation is the diagram in motion. The original ASCII is preserved below.</span>
      <button class="replay" type="button">↻ Replay</button>
    </div>
  </div>
  <details class="source">
    <summary>Original ASCII picture <span class="src-heading">— {T(source_heading)}</span></summary>
    <pre><code>{html.escape(ascii_pic)}</code></pre>
  </details>
</section>""")

    own_script = r"""
(() => {
  // Keep the moving diagrams keyboard-accessible and restartable.
  const diagrams = () => [...document.querySelectorAll('.anim-stage svg')];
  let paused = false;

  document.querySelectorAll('.replay').forEach(btn => {
    btn.addEventListener('click', () => {
      const stage = btn.closest('.anim-block').querySelector('.anim-stage');
      const clone = stage.cloneNode(true);
      stage.replaceWith(clone);
      if (paused) clone.querySelectorAll('svg').forEach(svg => {
        try { svg.pauseAnimations(); } catch (e) { /* not an SVG */ }
      });
    });
  });

  const motionBtn = document.getElementById('motionbtn');
  if (motionBtn) {
    motionBtn.addEventListener('click', () => {
      paused = !paused;
      document.body.classList.toggle('motion-paused', paused);
      motionBtn.textContent = paused ? '▶ Resume motion' : '⏸ Pause motion';
      diagrams().forEach(svg => {
        try { paused ? svg.pauseAnimations() : svg.unpauseAnimations(); } catch (e) { /* ignore */ }
      });
    });
  }

  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    document.body.classList.add('motion-paused');
    if (motionBtn) motionBtn.textContent = '▶ Resume motion';
    paused = true;
    diagrams().forEach(svg => {
      try { svg.pauseAnimations(); } catch (e) { /* ignore */ }
    });
  }
})();
"""

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nanocode, one picture at a time</title>
<meta name="description" content="Every chapter's central idea as an animated diagram, with the original ASCII preserved.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>{style}
{EXTRA_CSS}</style>
</head>
<body>
<button id="menu" type="button" aria-label="Toggle contents">☰ Contents</button>

<nav id="sidebar" aria-label="Table of contents">
  <div class="brand">
    <p class="eyebrow">Build your own coding agent</p>
    <h1>One picture at a time</h1>
    <p>Every chapter's central idea, set in motion.</p>
  </div>
  <div class="filter">
    <input id="filter" type="search" placeholder="Filter pictures…" aria-label="Filter table of contents">
  </div>
  <div id="toc"><ol>
{''.join(toc)}
  </ol></div>
  <div class="sidebar-foot">
    The static ASCII is kept under every animation.
    <div class="sidebar-actions">
      <button id="motionbtn" type="button">⏸ Pause motion</button>
      <a href="book.html">Full book →</a>
    </div>
  </div>
</nav>

<main id="pane">
  <div id="progress" aria-hidden="true"><span></span></div>
  <article id="content">
    <h1>Nanocode, one picture at a time</h1>
    <p class="picture-intro">Each chapter of <em>Nanocode, explained</em> turns on one diagram.
    Here those diagrams move: packets follow the arrows, sessions fill, gates open and refuse,
    and subagents recurse. The original ASCII is preserved under every animation, because the
    ASCII is still the source of truth.</p>
{''.join(sections)}
  </article>
</main>

{style_btn}

{aside}

<script>{main_script}</script>
<script>{own_script}</script>
</body>
</html>
"""
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT} ({len(page):,} bytes)")


if __name__ == "__main__":
    build()
