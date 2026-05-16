"""Male vampire co-host persona (Luna's dry, slightly-older foil)."""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_NAME = "Viktor"

_DEFAULT_VAMPIRE_PERSONA = (
    "You're a centuries-old vampire who carries himself like a man in his mid-twenties — "
    "effortlessly superior, mildly exasperated, and not particularly interested in hiding it. "
    "You find Luna entertaining in the way you'd find a slightly reckless younger woman entertaining — "
    "you're not her mentor, not her enemy, just someone who's seen everything and isn't impressed yet. "
    "You speak with dry wit and quiet confidence; you don't lecture, but you don't pretend "
    "she's your equal either — not out of cruelty, just honest self-assurance. "
    "Historical references slip out naturally, not as lessons. "
    "You're not protective on purpose. It just happens sometimes. You don't talk about it."
)


def cohost_enabled() -> bool:
    raw = (os.environ.get("LUNA_COHOST_BANTER") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def cohost_chat_personas_enabled() -> bool:
    """When True with :func:`cohost_enabled`, Twitch / YouTube chat auto-replies may be Luna or the co-host."""
    if not cohost_enabled():
        return False
    raw = (os.environ.get("LUNA_COHOST_CHAT_PERSONAS") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def cohost_name() -> str:
    return (os.environ.get("LUNA_COHOST_NAME") or _DEFAULT_NAME).strip() or _DEFAULT_NAME


def cohost_edge_voice() -> str:
    return (
        (os.environ.get("LUNA_COHOST_EDGE_VOICE") or "en-US-BrianMultilingualNeural").strip()
        or "en-US-BrianMultilingualNeural"
    )


def cohost_vrm_path() -> Path:
    raw = (os.environ.get("LUNA_COHOST_VRM") or r"D:\Luna streamer\aichris.vrm").strip()
    return Path(raw).expanduser()


def cohost_vrm_viewer_url() -> str:
    """Vite ``/@fs/`` URL for the co-host VRM (viewer preload)."""
    path = cohost_vrm_path()
    if not path.is_file():
        return ""
    return f"/@fs/{path.resolve().as_posix()}"


def build_vampire_system_prompt() -> str:
    raw = (os.environ.get("LUNA_COHOST_PERSONA") or "").strip()
    return raw if raw else _DEFAULT_VAMPIRE_PERSONA


def cohost_idle_sec() -> float:
    raw = (os.environ.get("LUNA_COHOST_IDLE_SEC") or "90").strip() or "90"
    try:
        sec = float(raw)
    except ValueError:
        sec = 90.0
    return max(30.0, min(sec, 600.0))


def cohost_min_gap_sec() -> float:
    raw = (os.environ.get("LUNA_COHOST_MIN_GAP_SEC") or "10").strip() or "10"
    try:
        sec = float(raw)
    except ValueError:
        sec = 10.0
    return max(5.0, min(sec, 1800.0))


def cohost_poll_sec() -> float:
    raw = (os.environ.get("LUNA_COHOST_POLL_SEC") or "30").strip() or "30"
    try:
        sec = float(raw)
    except ValueError:
        sec = 30.0
    return max(10.0, min(sec, 120.0))


def cohost_exchange_lines() -> int:
    raw = (os.environ.get("LUNA_COHOST_EXCHANGE_LINES") or "4").strip() or "4"
    try:
        n = int(raw)
    except ValueError:
        n = 4
    return max(2, min(n, 8))


def cohost_full_banter_line_cap() -> int:
    """Max parsed alternating lines when “full conversation” is on (open-ended script; safety ceiling only)."""
    raw = (os.environ.get("LUNA_COHOST_FULL_BANTER_MAX_LINES") or "").strip()
    if not raw:
        raw = (os.environ.get("LUNA_COHOST_EXCHANGE_LINES_FULL") or "72").strip() or "72"
    try:
        n = int(raw)
    except ValueError:
        n = 72
    return max(24, min(n, 200))


def cohost_exchange_lines_full() -> int:
    """Deprecated alias for :func:`cohost_full_banter_line_cap` (kept for .env compatibility)."""
    return cohost_full_banter_line_cap()
