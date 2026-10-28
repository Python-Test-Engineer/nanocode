"""sandbox.py - where the agent is allowed to write (a chapter 14 addition).

Chapter 7 made PLAN mode safe *by construction*: the write tools simply are not
in the menu the model sees. ACT mode handed them all back, and with them the
whole disk. This module is the same idea one level down: the write tools exist,
but each one asks a policy object first - and the policy only says yes inside a
folder you chose.

WHY THIS EXISTS
  "The model should be careful" is a prompt. A prompt is a request. A `check()`
  that runs before `open(path, "w")` is a guarantee, and the guarantee is worth
  more than any wording in the system prompt. This is the same trade chapter 7
  made, applied to *where* instead of *whether*.

WHERE THE FENCE IS
  roots   the folders writes are allowed in. Default: the directory the agent
          was started in (`["."]`), so "just in the folder" out of the box.
  deny    subtrees refused even when they sit inside a root (secrets, `.git`).
  Both are data, in `sandbox.json` next to this file, overridable per run with
  NANOCODE_SANDBOX_ROOTS (os.pathsep-separated) - the way ui.json and
  sounds.json are data.

WHAT "INSIDE" MEANS
  Paths are resolved first: `..` and symlinks are folded with os.path.realpath
  *before* the comparison, so `project/../../Windows/System32/x.dll` is judged
  as the absolute path it becomes, not the innocent-looking string it started
  as. The check is then a prefix test on normalised paths (commonpath), which is
  case-insensitive on Windows.

  A textual check ("does the string contain '..'?") would be a bug generator.
  Resolve, then compare.

WHAT IT IS NOT
  A container. `run_command` gets a best-effort check that reads the obvious
  write targets out of the command line (redirects, rm/cp/mv/mkdir/...), and a
  shell can still do whatever a shell can do. The fence is drawn around the
  *file tools*, where the agent's intent is explicit; the command check is a
  speed bump, and this file says so out loud rather than pretending.

THE ALARM
  A refusal is not a log line nobody reads. `install(hooks)` subscribes to the
  `sandbox_denied` event: the console prints FORBIDDEN (red, with the path and
  the reason) and `sounds.alarm()` plays the Windows warning WAV. Deliberately
  *not* behind NANOCODE_SOUND: ordinary sounds are decoration and opt-in, a
  blocked write is an alarm.
"""

import json
import os
import re
from pathlib import Path

import sounds
import ui

CONFIG_PATH = Path(__file__).with_name("sandbox.json")

# Minimal fallbacks so a missing/broken sandbox.json still fences something:
# "writes in the folder the agent was started in" is the safe default.
_FALLBACK = {"enabled": True, "roots": ["."], "deny": []}

# The hook event a refusal emits, and the sounds.json entry it plays.
DENIED_EVENT = "sandbox_denied"

_config = None  # merged sandbox.json, loaded lazily and cached (see config())


# --- Configuration ---

def load_config(path=None):
    """Read sandbox.json and merge it over the built-in fallbacks."""
    path = Path(path) if path else CONFIG_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        raw = {}

    merged = dict(_FALLBACK)
    merged.update({key: value for key, value in raw.items() if not key.startswith("_")})
    return merged


def config():
    """The merged sandbox.json contents (loaded once, then cached)."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def configure(path=None):
    """(Re)load sandbox.json. Returns the merged config."""
    global _config
    _config = load_config(path)
    return _config


def enabled(cfg=None):
    """Resolve the master switch: env NANOCODE_SANDBOX wins, else sandbox.json.

    NANOCODE_SANDBOX=0 turns the fence off for a run (e.g. a deliberate
    demonstration of the refusal it prevents). Anything unrecognised is left to
    sandbox.json - a typo should not silently widen the fence.
    """
    cfg = cfg if cfg is not None else config()
    value = os.getenv("NANOCODE_SANDBOX")
    if value is None:
        value = cfg.get("enabled", True)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("0", "false", "no", "off")


def roots_from_config(cfg=None):
    """The configured roots as written (NANOCODE_SANDBOX_ROOTS wins)."""
    cfg = cfg if cfg is not None else config()
    override = os.getenv("NANOCODE_SANDBOX_ROOTS", "").strip()
    if override:
        # os.pathsep is ";" on Windows and ":" elsewhere: the same separator
        # PATH uses, so a reader already knows how to write it.
        return [part for part in override.split(os.pathsep) if part.strip()]
    return list(cfg.get("roots") or ["."])


# --- Path arithmetic ---

def _resolve(path):
    """Absolute, symlink-free, normalised form of `path` (relative to cwd)."""
    candidate = Path(os.path.expanduser(str(path)))
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    # realpath folds "..", "." and symlinks. strict=False because the target
    # usually does not exist yet - the agent is about to create it.
    return Path(os.path.realpath(candidate))


def _inside(path, root):
    """True when `path` is `root` or below it. Different drives -> False."""
    path, root = os.path.normcase(str(path)), os.path.normcase(str(root))
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False  # C: and D: have no common path; that is a "no"


# --- The refusal ---

class SandboxViolation(Exception):
    """One refused path: what was asked for, where it really pointed, and why."""

    def __init__(self, path, resolved, roots=(), reason="outside the writable roots", tool=""):
        super().__init__(str(path))
        self.path = str(path)
        self.resolved = str(resolved)
        self.roots = tuple(str(root) for root in roots)
        self.reason = reason
        self.tool = tool

    def message(self):
        """The string a tool returns to the model. Errors are information."""
        allowed = ", ".join(self.roots) or "(none configured)"
        return (
            f"Error: FORBIDDEN - {self.tool or 'write'} was refused by the sandbox: "
            f"{self.path} resolves to {self.resolved}, which is {self.reason}. "
            f"Writable roots: {allowed}. Nothing was changed."
        )


# --- The policy ---

class Sandbox:
    """The write policy: a list of roots, a list of denials, and an armed flag.

    `active` is the mode switch: tools.js only writes in ACT mode, so the sandbox
    only needs to police ACT mode. `Agent` calls arm(mode) on every mode change;
    `enabled` stays the operator's master switch (sandbox.json / env).
    """

    def __init__(self, roots=None, enabled=None, deny=None, cfg=None):
        cfg = config() if cfg is None else cfg
        self.enabled = globals()["enabled"](cfg) if enabled is None else bool(enabled)
        raw_roots = roots if roots is not None else roots_from_config(cfg)
        raw_deny = deny if deny is not None else list(cfg.get("deny") or [])
        self.roots = tuple(_resolve(root) for root in raw_roots)
        self.deny = tuple(_resolve(root) for root in raw_deny)
        self.active = True  # narrowed to ACT mode by arm()

    # --- mode ---

    def arm(self, mode):
        """Police writes only when the agent can write. Returns armed state."""
        self.active = str(mode).strip().lower() == "act"
        return self.armed

    @property
    def armed(self):
        """True when a check would actually refuse something right now."""
        return bool(self.enabled and self.active)

    # --- checks ---

    def resolve(self, path):
        return _resolve(path)

    def check(self, path, tool=""):
        """Return a SandboxViolation for `path`, or None when it is allowed."""
        if not self.armed:
            return None
        resolved = _resolve(path)
        # Deny beats root: a path can be inside a root and still forbidden.
        for denied in self.deny:
            if _inside(resolved, denied):
                return SandboxViolation(path, resolved, self.roots, "inside a denied path", tool)
        for root in self.roots:
            if _inside(resolved, root):
                return None
        return SandboxViolation(path, resolved, self.roots, "outside the writable roots", tool)

    def check_command(self, command, tool="run_command"):
        """Best-effort check of the write targets named in a shell command.

        A shell is a general-purpose escape hatch, so this is explicitly a speed
        bump, not a fence: it reads redirect targets and the arguments of the
        obvious mutating commands, and says nothing about anything cleverer.
        """
        if not self.armed:
            return []
        violations, seen = [], set()
        for target in write_targets(command):
            violation = self.check(target, tool=tool)
            if violation and violation.resolved not in seen:
                seen.add(violation.resolved)
                violations.append(violation)
        return violations

    def describe(self):
        """One line for the banner, or None when writes are unpoliced."""
        if not self.armed:
            return None
        return "writes allowed in " + "; ".join(str(root) for root in self.roots)


# --- Reading write targets out of a command line ---

# A redirect: > out, >> out, 2> out, 2>&1 (the last one is filtered below).
_REDIRECT = re.compile(r"(?:\d?>>?|\d?>&?)\s*(\"[^\"]*\"|'[^']*'|[^\s;|&<>]+)")

# Commands whose arguments are, in the overwhelming majority of uses, paths.
_MUTATORS = {
    "rm", "rmdir", "rd", "del", "erase", "unlink", "mv", "move", "ren", "rename",
    "cp", "copy", "xcopy", "robocopy", "mkdir", "md", "touch", "tee", "truncate",
    "ln", "chmod", "chown", "attrib",
}

_SKIP_TARGETS = {"&1", "&2", "/dev/null", "nul"}


def _words(text):
    """Split a shell segment into words, keeping quoted strings together."""
    words = re.findall(r"\"[^\"]*\"|'[^']*'|[^\s]+", text)
    return [word[1:-1] if len(word) > 1 and word[0] == word[-1] and word[0] in "\"'" else word
            for word in words]


def write_targets(command):
    """The paths a shell command is most obviously writing to (may be empty)."""
    targets = []
    for segment in re.split(r"&&|\|\||;|\|", str(command or "")):
        for match in _REDIRECT.finditer(segment):
            targets.append(match.group(1).strip("\"'"))
        words = _words(segment)
        if words and os.path.basename(words[0]).lower() in _MUTATORS:
            targets.extend(word for word in words[1:] if not word.startswith("-"))
    return [target for target in targets if target and target.lower() not in _SKIP_TARGETS]


# --- Hooks wiring (the alarm) ---

def install(hooks, cfg=None):
    """Subscribe the refusal alarm: FORBIDDEN on the console + a Windows warning.

    One handler, one event. `sandbox_denied` is emitted by ToolContext.refuse()
    when a tool's guard refuses a path - see tools.py.
    """
    cfg = cfg if cfg is not None else config()

    def on_sandbox_denied(tool="", path="", reason="", roots=(), **_payload):
        ui.forbidden(path or "?", reason, roots=roots)
        sounds.alarm(DENIED_EVENT, cfg)

    hooks.on(DENIED_EVENT, on_sandbox_denied)
    return hooks
