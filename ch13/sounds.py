"""sounds.py - make the loop audible (a chapter 13 addition, not from the book).

Chapter 12 left the loop observable: hooks emit events and a listener prints a
line for each one. That is enough while you are *watching* the terminal - and
useless the moment you step away, alt-tab to your editor, or run the agent in a
window behind something else. This module is the same idea for the other
channel: a lifecycle event becomes a sound, so you can hear the agent start,
think, run a tool and finish without looking at it at all.

WHY SOUND (and why here)
  A hook is a *seam*, not a feature: anything that cares can listen, and nothing
  in the agent changes because of it. Chapter 12 used that seam to print. This
  chapter uses the exact same seam to play - which is the proof that the seam is
  real. `sounds.install(agent.hooks)` is four lines of wiring and the agent loop
  does not know it exists.

A sound is data, not code
  Which file plays for which event lives in `sounds.json`, next to `ui.json` and
  for the same reason: taste should not need a Python edit. Add an event, point
  it at a WAV, restart.

Two ways to make a noise on Windows
  * "media" - `winsound.PlaySound` plays a real WAV (C:\\Windows\\Media\\*.wav).
    The pleasant option. Asynchronous, so the agent is never blocked by audio.
  * "beep"  - `winsound.Beep(freq, ms)` is a pure tone from the motherboard.
    Ugly, but it works over a remote session, inside a VM, and when the WAVs are
    not there - which is exactly when a "media" setup goes quiet.

Graceful degradation is the whole safety story here
  Sound is a nicety. So: not on Windows -> do nothing; the WAV is missing -> fall
  back to the tone; winsound itself fails -> report once and go silent. A hook
  that raises is already reported and skipped by `hooks.py`; a sound that fails
  must likewise never be able to break a turn.

Configure (all optional - sound is off until asked for)
  NANOCODE_SOUND=media            # media | beep | off  (unset follows sounds.json)
  NANOCODE_SOUND_START=<path.wav> # override the session_start sound
  NANOCODE_SOUND_LOOP=<path.wav>  # override the turn_start sound
  NANOCODE_SOUND_DONE=<path.wav>  # override the turn_end sound
"""

import json
import os
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).with_name("sounds.json")

# Minimal fallback so a missing/broken sounds.json is silent, not fatal.
_FALLBACK = {"mode": "off", "muted": False, "sounds": {}}

# The three knobs .env exposes, and the hook event each one overrides. The names
# (START / LOOP / DONE) are the human words for the three moments worth hearing:
# the session starts, a turn begins, a turn finishes.
ENV_OVERRIDES = {
    "session_start": "NANOCODE_SOUND_START",
    "turn_start": "NANOCODE_SOUND_LOOP",
    "turn_end": "NANOCODE_SOUND_DONE",
}

# Modes that mean "make a noise", mapped to their playback style.
_MEDIA_MODES = ("media", "wav", "sound")
_BEEP_MODES = ("beep", "1", "true", "yes", "on", "tones")

_config = None  # merged sounds.json, loaded lazily and cached (see config())


# --- Configuration ---

def load_config(path=None):
    """Read sounds.json and merge it over the built-in fallbacks."""
    path = Path(path) if path else CONFIG_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        raw = {}

    merged = dict(_FALLBACK)
    merged.update({k: v for k, v in raw.items() if not k.startswith("_")})
    return merged


def config():
    """The merged sounds.json contents (loaded once, then cached)."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def configure(path=None):
    """(Re)load sounds.json. Returns the merged config."""
    global _config
    _config = load_config(path)
    return _config


def mode(cfg=None):
    """Resolve the playback mode: env NANOCODE_SOUND wins, else sounds.json.

    Returning "off" for anything unrecognised is deliberate: a typo in a config
    file should mean silence, never a surprise or a crash.
    """
    cfg = cfg if cfg is not None else config()
    value = os.getenv("NANOCODE_SOUND")
    if value is None:
        value = str(cfg.get("mode", "off"))
    value = value.strip().lower()
    if value in _MEDIA_MODES:
        return "media"
    if value in _BEEP_MODES:
        return "beep"
    return "off"


def enabled(cfg=None):
    """True when a sound would actually play right now."""
    cfg = cfg if cfg is not None else config()
    if cfg.get("muted"):
        return False
    return available() and mode(cfg) != "off"


def available():
    """True when this platform can play a sound at all (Windows, via winsound)."""
    return os.name == "nt"


# --- What plays, for which event ---

def spec_for(event, cfg=None):
    """The sound spec for a hook event, or None if that event is silent.

    Order matters: the per-event WAV from .env (NANOCODE_SOUND_*) beats the one
    in sounds.json, which beats "no sound". That lets you re-point an event for
    one run without editing the shipped defaults.
    """
    cfg = cfg if cfg is not None else config()
    sounds = cfg.get("sounds", {})
    spec = dict(sounds.get(event) or {})
    if not spec:
        return None

    override = os.getenv(ENV_OVERRIDES.get(event, ""), "").strip()
    if override:
        spec["file"] = override
        spec.setdefault("label", event)
    return spec


def _beep_tones(spec):
    """Normalise the "beep" field into a list of (frequency, milliseconds).

    Two shapes are accepted in sounds.json, because writing a single tone the
    long way round is annoying:  "beep": [880, 120]  or  "beep": [[880, 120], ...]
    """
    tones: Any = spec.get("beep") or [880, 120]
    if isinstance(tones[0], (int, float)):  # a bare [freq, ms]
        tones = [tones]
    return [(int(frequency), int(milliseconds)) for frequency, milliseconds in tones]


# --- Playback (the only platform-specific code in the chapter) ---

def _play_file(path):
    """Play a WAV asynchronously. Returns True if winsound accepted it."""
    import winsound  # only importable on Windows; guarded by available()
    winsound.PlaySound(
        str(path),
        winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
    )
    return True


def _play_beep(tones):
    """Play a sequence of tones. Blocks for the duration, so keep them short."""
    import winsound
    for frequency, milliseconds in tones:
        winsound.Beep(frequency, milliseconds)
    return True


def play(event, cfg=None):
    """Play the sound for `event`. Never raises; returns True if sound was made.

    Called from the hook handlers below - but usable on its own:
        sounds.play("session_start")   # the Windows tada, if configured
    """
    cfg = cfg if cfg is not None else config()
    if not enabled(cfg):
        return False

    spec = spec_for(event, cfg)
    if spec is None:
        return False

    try:
        if mode(cfg) == "media":
            path = spec.get("file")
            # Missing WAV is the common failure (different Windows, a cleaned-up
            # machine). Fall back to the tone rather than going silent.
            if path and Path(path).exists():
                return _play_file(path)
        return _play_beep(_beep_tones(spec))
    except Exception:
        # Winsound can fail on machines with no audio device or in a session
        # without a console. Sound is never allowed to break the agent, so a
        # failure here is not even worth a warning line after the first one.
        return False


# --- Hooks wiring ---

def install(hooks, cfg=None):
    """Register one sound per configured hook event. Returns `hooks`.

    This is the entire chapter: an observer that turns events into noise. It
    subscribes to the events it has a sound for and absorbs every payload with
    **_, so a new field on an event cannot break it.
    """
    cfg = cfg if cfg is not None else config()
    for event in cfg.get("sounds", {}):
        def make_handler(name):
            def handler(**_payload):
                play(name, cfg)
            return handler
        hooks.on(event, make_handler(event))
    return hooks


def legend(cfg=None):
    """One-line description of what is audible now, for the banner."""
    cfg = cfg if cfg is not None else config()
    if not available():
        return None
    if mode(cfg) == "off" or cfg.get("muted"):
        return None
    names = ", ".join(sorted(cfg.get("sounds", {})))
    return f"sound {mode(cfg)} ({names})"
