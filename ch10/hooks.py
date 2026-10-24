"""hooks.py - lifecycle hooks (an addition to the book, not from it).

The book's agent is a closed loop: it thinks, calls tools, answers. There is no
seam to observe it from the outside without editing the loop itself. This module
adds that seam, and nothing in the agent behaves differently because of it.

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
    turn_start    user_input
    before_think  messages        (how many messages are about to be sent)
    after_think   thought         (an llm.Thought)
    tool_call     name, args, result
    turn_end      output, tool_calls

Built in: `Hooks.trace(path)` writes one JSON line per event. main() calls
`trace_from_env(agent.hooks)`, so `NANOCODE_TRACE=1` is enough to get a trace.
"""

import json
import os
import time

import ui

EVENTS = ("turn_start", "before_think", "after_think", "tool_call", "turn_end")


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
        """Call every handler for `event`. Failures are reported, never raised."""
        for function in list(self._handlers.get(event, [])):
            try:
                function(**payload)
            except Exception as e:
                ui.warning(f"hook for '{event}' failed: {e}")

    # --- built-in sinks ---

    def trace(self, path):
        """Append every event to `path` as JSON Lines. Returns the path."""
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


def _jsonable(value):
    """Make a payload value readable in a trace: Thoughts become plain data."""
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
