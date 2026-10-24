"""ui.py - the console layer for Nanocode.

Every byte the agent shows a human goes through this module. Nothing here
knows about LLMs, tools or the agent loop: it takes semantic events
("a tool is running", "the brain is thinking", "here is the answer") and
renders them with Rich.

Colours live in ui.json, not in Python. Change a style there, restart, done.
Keys resolve in this order:

    styles.<key>          e.g. "banner.title", "thinking"
    commands.<cmd>        e.g. "/q"  (used by help and command feedback)
    tools.<tool_name>     e.g. "read_file" (used by tool_action)
    theme.<name>          fallback accents: accent, muted, success, warning, danger

A missing key is never fatal - it falls back to the defaults below.
"""

import json
import os
from pathlib import Path

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

CONFIG_PATH = Path(__file__).with_name("ui.json")

# Minimal fallbacks so a missing/broken ui.json still produces a usable UI.
_FALLBACK = {
    "console": {"highlight": False, "render_markdown": True},
    "theme": {
        "accent": "bright_cyan",
        "muted": "grey58",
        "success": "bold green",
        "warning": "bold yellow",
        "danger": "bold red",
    },
    "styles": {},
    "commands": {},
    "tools": {"default": {"icon": "→", "style": "grey62", "verb": "Tool"}},
}


# --- Configuration ---

def load_config(path=None):
    """Read ui.json and merge it over the built-in fallbacks."""
    path = Path(path) if path else CONFIG_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        raw = {}

    merged = {section: dict(values) for section, values in _FALLBACK.items()}
    for section, values in raw.items():
        if isinstance(values, dict) and isinstance(merged.get(section), dict):
            merged[section].update(values)
        else:
            merged[section] = values
    return merged


def _console_options(cfg, force_terminal):
    """Turn the "console" section of ui.json into Console() keyword arguments."""
    options = cfg.get("console", {})
    env_force = os.getenv("NANOCODE_COLOR", os.getenv("FORCE_COLOR", "")).strip().lower()
    if force_terminal is None and env_force in ("1", "true", "yes", "on"):
        force_terminal = True
    elif force_terminal is None and env_force in ("0", "false", "no", "off"):
        force_terminal = False

    kwargs = {
        "highlight": bool(options.get("highlight", False)),
        "force_terminal": force_terminal,
        "color_system": options.get("color_system", "auto"),
    }
    # Windows: default to ANSI output (Windows Terminal, VS Code, PowerShell 7).
    # The legacy Win32 colouring path only works on a real console and produces
    # colourless output whenever stdout is redirected.
    if os.name == "nt":
        kwargs["legacy_windows"] = bool(options.get("legacy_windows", False))
    return kwargs


# Module singletons. Created eagerly (not None) so callers and type checkers
# never have to reason about "not configured yet"; configure() replaces them.
_config = load_config()
_console = Console(**_console_options(_config, None))


def configure(path=None, console=None, force_terminal=None):
    """(Re)load ui.json and rebuild the Rich Console. Returns the Console."""
    global _config, _console
    _config = load_config(path)
    _console = console or Console(**_console_options(_config, force_terminal))
    return _console


def config():
    """The merged ui.json contents."""
    return _config


def console():
    """The Rich Console every helper writes to."""
    return _console


# --- Style lookup ---

def entry(key):
    """Return the config dict for a dotted key (never None)."""
    cfg = config()
    if key in cfg["styles"]:
        return cfg["styles"][key]
    if key.startswith("tool."):
        return cfg["tools"].get(key[5:], cfg["tools"]["default"])
    if key.startswith("command."):
        return cfg["commands"].get(key[8:], {})
    section, _, name = key.partition(".")
    if section in ("accent", "muted", "success", "warning", "danger"):
        return {"style": cfg["theme"].get(section, "")}
    if name and name in cfg["theme"]:
        return {"style": cfg["theme"][name]}
    return {}


def style_of(key, default=""):
    """Just the Rich style string for a key."""
    return entry(key).get("style") or default


def text_of(key, default=""):
    return entry(key).get("text", default)


def icon_of(key, default=""):
    return entry(key).get("icon", default)


# --- Primitives ---

def print(*objects, **kwargs):
    console().print(*objects, **kwargs)


def blank():
    console().print()


def rule():
    console().rule(style=style_of("banner.rule", "grey30"))


def _line(key, message, detail=None):
    """One event line: icon + message + optional dim detail."""
    icon = icon_of(key)
    style = style_of(key)
    line = Text("  ")
    if icon:
        line.append(f"{icon} ", style=style)
    line.append(message, style=style)
    if detail:
        line.append(f" {detail}", style=style_of("tool.detail", "grey58"))
    console().print(line)


# --- High-level events ---

def banner(brain=None, model=None, mode=None, version="v1.0", tool_count=None, hint="/help for commands"):
    """The startup block: title, then whatever this chapter knows about itself.

    Every field is optional so early chapters can show a bare title; anything
    passed as None is simply omitted.
    """
    title = entry("banner.title")
    console().print()
    console().print(Text(f"{title.get('text', '⚡ Nanocode')} {version}", style=title.get("style", "")))

    fields = (
        ("brain", brain),
        ("model", model),
        ("mode", mode),
        ("tools", tool_count),
    )
    meta = Text("  ")
    for label, value in fields:
        if value is None:
            continue
        meta.append(f"{label} ", style=style_of("banner.meta.label", "grey46"))
        meta.append(f"{value}  ", style=style_of("banner.meta.value", "bright_white"))
    if meta.plain.strip():
        console().print(meta)
    if hint:
        console().print(Text(f"  {hint}", style=style_of("muted")))
    rule()


def ask(brain="", mode=""):
    """Styled input prompt. Raises EOFError/KeyboardInterrupt like input()."""
    spec = entry("prompt")
    if brain or mode:
        text = spec.get("format", "[{brain}:{mode}] ❯ ").format(brain=brain, mode=mode)
    else:
        text = spec.get("bare", "❯ ")  # chapters without a brain or a mode
    return console().input(Text(text, style=spec.get("style", "")), markup=False)


def thinking(reasoning, max_lines=5):
    """Dim, truncated peek at the model's reasoning."""
    if not reasoning:
        return
    lines = str(reasoning).strip().split("\n")[:max_lines]
    prefix = icon_of("thinking")
    style = style_of("thinking", "grey50 italic")
    for i, line in enumerate(lines):
        lead = f"  {prefix} " if i == 0 else "     "
        console().print(Text(f"{lead}{line}", style=style))


def tool_action(name, detail=""):
    """A tool is about to run, e.g. '→ Reading app.py'."""
    spec = entry(f"tool.{name}")
    verb = spec.get("verb") or name
    line = Text("  ")
    line.append(f"{spec.get('icon', '→')} {verb}", style=spec.get("style", ""))
    if detail:
        line.append(f" {detail}", style=style_of("tool.detail", "grey58"))
    console().print(line)


def answer(text):
    """The agent's final answer for one turn."""
    if not text:
        return
    console().print()
    if config()["console"].get("render_markdown", True):
        console().print(Markdown(str(text)))
    else:
        console().print(Text(str(text), style=style_of("answer")))
    console().print()


def error(message):
    _line("error", str(message))


def warning(message):
    _line("warning", str(message))


def success(message):
    _line("success", str(message))


def info(message):
    _line("info", str(message))


def send():
    _line("send", text_of("send", "Thinking") + "...")


def compact():
    _line("compact", text_of("compact", "Compacting conversation") + "...")


def mode_switch(mode):
    """Announce a plan/act switch using the per-mode style."""
    key = "mode.act" if mode == "act" else "mode.plan"
    _line(key, "Switched to " + text_of(key, mode.upper() + " MODE"))


def switched(name, model=None):
    detail = f"({model})" if model else None
    _line("switched", f"Switched to: {name}", detail)


def tokens(used, limit):
    console().print(Text(f"  {used:,} / {limit:,} tokens in context", style=style_of("tokens", "grey46")))


def goodbye(message="Exiting..."):
    console().print()
    console().print(Text(message, style=style_of("goodbye", "grey58")))


def help_table(only=None):
    """Rich table of slash commands, coloured from ui.json.

    `only` limits the table to the commands a chapter actually implements -
    ui.json is shared, so /mode must not be advertised by chapter 3.
    """
    table = Table(box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False, header_style=style_of("muted"))
    table.add_column("command", style=style_of("muted"))
    table.add_column("what it does", style=style_of("answer"))
    for command, spec in config()["commands"].items():
        if only is not None and command not in only:
            continue
        cmd = Text(f"{spec.get('icon', '')} {command}".strip(), style=spec.get("style", ""))
        table.add_row(cmd, spec.get("description", ""))
    console().print()
    console().print(table)
    console().print(Text("  anything else is a message to the agent", style=style_of("muted")))


def help_meta(brain, model, mode):
    """Second half of /help: what the current brain is."""
    console().print(Text(f"  brain {brain} · model {model} · mode {mode}", style=style_of("muted")))
    console().print()
