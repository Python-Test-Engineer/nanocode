"""hooks.py - lifecycle hooks (an addition to the book, not from it).

The book's agent is a closed loop: it thinks, calls tools, answers. There is no
seam to observe it from the outside without editing the loop itself. This module
adds that seam, and nothing in the agent behaves differently because of it.

WHY THIS EXISTS
  Everything interesting in an agent happens mid-loop: before a request, after a
  reply, around a tool. Without hooks the only way to look is to edit the loop -
  and then your observation code is mixed into the thing being observed. Hooks
  invert that: the loop announces what happened, and anything that cares listens.
  That is also why they are synchronous and return nothing - they are for
  watching, not for steering (see "Rules").

A hook is any callable that accepts the event's keyword arguments:

    agent.hooks.on("tool_call", lambda **e: print(e["name"], e["result"][:60]))

    @agent.hooks.on("turn_end")
    def log_turn(output, **rest):
        print(f"{len(output)} chars")

Rules
  * hooks observe, they do not steer: return values are ignored, so a hook can
    never change what the agent does.
  * a hook that raises is reported and skipped - a broken listener must not
    break the turn.
  * every event carries only what it promises, so a hook written against
    chapter 5 still works in chapter 12.

Events
    session_start (this chapter) fired once by main() after the banner, before
                  the first prompt. It is the one event that is not part of a
                  turn - it is the session beginning - which is why ch13's
                  sounds.py uses it for the startup sound.
    sandbox_denied (chapter 14) tool, path, resolved, reason, roots - a write the
                  sandbox refused. Emitted by tools.py through ToolContext and
                  heard by sandbox.install(): FORBIDDEN on the console, plus the
                  Windows warning sound.
    turn_start    user_input
    before_think  messages        (how many messages are about to be sent)
    after_think   thought         (an llm.Thought)
    tool_call     name, args, result
    turn_end      output, tool_calls

Built in:
  * `install(hooks)` - what every chapter's main() calls. Prints one coloured
    line per event so the loop is visible while it runs (`NANOCODE_HOOKS=0`
    hides them), and turns on tracing when `NANOCODE_TRACE` is set.
  * `Hooks.trace(path)` - one JSON line per event, for later analysis.
"""

import json
import os
import time

import ui

EVENTS = ("session_start", "sandbox_denied", "turn_start", "before_think", "after_think", "tool_call", "turn_end")


class Hooks:
    """A tiny synchronous event bus: register handlers, emit events."""

    def __init__(self, handlers=None):
        self._handlers = {event: [] for event in EVENTS}
        for event, functions in (handlers or {}).items():
            for function in functions:
                self.on(event, function)

    # --- registration ---

    def on(self, event, function=None):
        """Register a handler. Usable bare or as a decorator.

            hooks.on("turn_end", log)
            @hooks.on("turn_end")
            def log(output, **rest): ...
        """
        if event not in self._handlers:
            raise ValueError(
                f"Unknown hook event '{event}'. Known events: {', '.join(EVENTS)}"
            )

        if function is None:  # decorator form
            def register(handler):
                self._handlers[event].append(handler)
                return handler
            return register

        self._handlers[event].append(function)
        return function

    def off(self, event, function):
        """Remove a handler (no error if it was never registered)."""
        if function in self._handlers.get(event, []):
            self._handlers[event].remove(function)

    def handlers_for(self, event):
        """The handlers currently registered for an event (a copy)."""
        return list(self._handlers.get(event, []))

    # --- emitting ---

    def emit(self, event, **payload):
        """Call every handler for `event`. Failures are reported, never raised.

        Two deliberate choices:
          * iterate over a COPY of the handler list, so a handler that adds or
            removes handlers cannot mutate the list mid-loop
          * wrap each call: an observer must never be able to break the agent.
            A bad handler is a warning line, not a traceback.
        """
        for function in list(self._handlers.get(event, [])):
            try:
                function(**payload)
            except Exception as e:
                ui.warning(f"hook for '{event}' failed: {e}")

    # --- built-in sinks ---

    def trace(self, path):
        """Append every event to `path` as JSON Lines. Returns the path.

        JSON Lines (one object per line) rather than one big JSON array: a crash
        leaves every completed record intact, and `tail -f` works while the agent
        runs. The sink is built per event with make_sink(event) so the closure
        captures the event name, not the loop variable.
        """
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        def make_sink(event):
            def sink(**payload):
                record = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event}
                record.update({key: _jsonable(value) for key, value in payload.items()})
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
            return sink

        for event in EVENTS:
            self.on(event, make_sink(event))
        return path


def _clip(text, limit=52):
    """One short line of text for a console event."""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def log_to_console(hooks):
    """Print one coloured line per event. This is the teaching view of the loop."""

    # Each handler takes exactly the payload it needs and absorbs the rest with
    # **_, so adding a field to an event does not break existing listeners.
    def on_session_start(brain=None, model=None, mode=None, **_):
        detail = " · ".join(str(v) for v in (brain, model, mode) if v)
        ui.hook_event("session_start", detail)

    def on_turn_start(user_input, **_):
        ui.hook_event("turn_start", f'"{_clip(user_input)}"')

    def on_sandbox_denied(tool="", path="", **_):
        # One line, and the alarm's own FORBIDDEN line follows it (sandbox.py).
        ui.hook_event("sandbox_denied", f"{tool or 'write'} → {_clip(path, 46)}")

    def on_before_think(messages, **_):
        ui.hook_event("before_think", f"{messages} message(s) queued")

    def on_after_think(thought, **_):
        # Summarise rather than dump: "text 43 chars · wants write_file" says
        # more at a glance than the full Thought would.
        parts = []
        if thought.text:
            parts.append(f"text {len(thought.text)} chars")
        if thought.tool_calls:
            parts.append("wants " + ", ".join(call.name for call in thought.tool_calls))
        if getattr(thought, "thinking", None):
            parts.append("reasoning")
        ui.hook_event("after_think", " · ".join(parts) or "empty thought")

    def on_tool_call(name, args, result, **_):
        # args is a dict; show it like a call signature. Result is summarised by
        # size because it can be a whole file.
        arguments = ", ".join(f"{key}={_clip(value, 18)}" for key, value in (args or {}).items())
        ui.hook_event("tool_call", f"{name}({arguments}) → {len(str(result))} chars back")

    def on_turn_end(output, **_):
        ui.hook_event("turn_end", f"answer {len(output or '')} chars")

    hooks.on("session_start", on_session_start)
    hooks.on("sandbox_denied", on_sandbox_denied)
    hooks.on("turn_start", on_turn_start)
    hooks.on("before_think", on_before_think)
    hooks.on("after_think", on_after_think)
    hooks.on("tool_call", on_tool_call)
    hooks.on("turn_end", on_turn_end)
    return hooks


def install(hooks):
    """Default wiring for main(): coloured event lines, plus tracing if asked.

    `NANOCODE_HOOKS=0` (or false/no/off) hides the console lines; the hooks are
    still emitted, so your own handlers and NANOCODE_TRACE keep working.
    """
    enabled = os.getenv("NANOCODE_HOOKS", "1").strip().lower() not in ("0", "false", "no", "off")
    if enabled:
        log_to_console(hooks)
        ui.set_hooks_visible(True)
    trace_from_env(hooks)
    return hooks


def _jsonable(value):
    """Make a payload value readable in a trace: Thoughts become plain data.

    Without this, json.dumps(default=str) would write
    "<llm.Thought object at 0x...>" - technically valid JSON, useless to read.
    Long strings are clipped too: a `tool_call` result can be an entire file,
    and a trace should stay greppable.
    """
    if hasattr(value, "tool_calls") and hasattr(value, "raw_content"):
        return {
            "text": value.text,
            "thinking": getattr(value, "thinking", None),
            "tool_calls": [
                {"name": call.name, "args": call.args} for call in value.tool_calls
            ],
        }
    if isinstance(value, str) and len(value) > 2000:
        return value[:2000] + f"... ({len(value) - 2000} chars truncated)"
    return value


def trace_from_env(hooks, default=".nanocode/trace.jsonl"):
    """Turn on JSONL tracing when NANOCODE_TRACE is set. No-op otherwise."""
    value = os.getenv("NANOCODE_TRACE", "").strip()
    if not value:
        return hooks
    hooks.trace(default if value.lower() in ("1", "true", "yes", "on") else value)
    return hooks
