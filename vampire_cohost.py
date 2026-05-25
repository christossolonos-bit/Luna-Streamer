"""Male vampire co-host persona (Luna's dry, slightly-older foil)."""

from __future__ import annotations

import os
import re
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
    raw = (os.environ.get("LUNA_COHOST_CHAT_PERSONAS") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def cohost_name_aliases() -> list[str]:
    """Lowercase names that count as addressing the co-host in chat."""
    names: list[str] = []
    primary = cohost_name().strip().lower()
    if primary:
        names.append(primary)
    extras = (os.environ.get("LUNA_COHOST_CHAT_ALIASES") or "").strip()
    for part in extras.replace(",", " ").split():
        p = part.strip().lower()
        if p and p not in names:
            names.append(p)
    return names


def _name_mention_index(text: str, name: str) -> int | None:
    """Start index of a whole-word / @mention hit, or None."""
    n = (name or "").strip().lower()
    if not n or not text:
        return None
    pat = rf"(?:^|(?<=[^a-z0-9_]))@?{re.escape(n)}(?=[^a-z0-9_]|$)"
    m = re.search(pat, text.lower())
    return m.start() if m else None


def chat_directed_at_cohost(text: str) -> bool:
    return any(_name_mention_index(text, n) is not None for n in cohost_name_aliases())


def chat_directed_at_luna(text: str) -> bool:
    return _name_mention_index(text, "luna") is not None


def twitch_message_addressees(text: str, *, trigger_all: bool = False) -> list[str]:
    """Who should answer this Twitch / YouTube / TikTok line (``luna`` | ``viktor`` | ``himari``).

    Delegates to :func:`luna_cast.public_chat_addressees`. Legacy ``cohost`` is normalized to
    ``viktor`` for callers that still expect the old token.
    """
    from luna_cast import public_chat_addressees

    return public_chat_addressees(text, trigger_all=trigger_all)


def twitch_speaker_system_note(*, chatter: str, message: str, speaker: str) -> str:
    """Context for who the Twitch line is for — not a fake chat user turn."""
    from luna_twitch_user import profile_from_login, twitch_chatter_system_note

    profile = profile_from_login(chatter)
    return twitch_chatter_system_note(
        profile=profile,
        message=message,
        speaker=speaker,
        cohost_name=cohost_name(),
    )


def resolve_chat_reply_speaker(text: str, *, cohost_in_scene: bool = True) -> str:
    """Return ``luna`` or ``cohost`` for who should answer this chat line.

  Explicit @Viktor (or co-host aliases) always routes to the co-host, even when dismissed
    from the VRM viewer or when ``LUNA_COHOST_CHAT_PERSONAS=0``. Random/alternate routing
    only applies when neither name is clearly targeted.
    """
    import random

    if not cohost_enabled():
        return "luna"

    at_cohost = chat_directed_at_cohost(text)
    at_luna = chat_directed_at_luna(text)

    if at_cohost and not at_luna:
        return "cohost"
    if at_luna and not at_cohost:
        return "luna"

    if at_cohost and at_luna:
        c_idx = min(
            (i for n in cohost_name_aliases() if (i := _name_mention_index(text, n)) is not None),
            default=10**9,
        )
        l_idx = _name_mention_index(text, "luna")
        if c_idx < (l_idx if l_idx is not None else 10**9):
            return "cohost"
        return "luna"

    if not cohost_chat_personas_enabled() or not cohost_in_scene:
        return "luna"

    mode = (os.environ.get("LUNA_COHOST_CHAT_SPEAKER") or "random").strip().lower()
    if mode in ("luna", "luna_only"):
        return "luna"
    if mode in ("cohost", "viktor", "cohost_only", "vampire"):
        return "cohost"
    if mode == "alternate":
        return "cohost" if random.random() < 0.5 else "luna"
    return "cohost" if random.random() < 0.5 else "luna"


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


def viewer_viktor_persona_blurb() -> str:
    from luna_persona import persona_blurb_for_viewer

    return persona_blurb_for_viewer(build_vampire_system_prompt())


def cohost_after_chat_sec() -> float:
    """Quiet time after any Twitch/YouTube chat (or reply) before idle banter resumes."""
    raw = (os.environ.get("LUNA_COHOST_AFTER_CHAT_SEC") or "10").strip() or "10"
    try:
        sec = float(raw)
    except ValueError:
        sec = 10.0
    return max(3.0, min(sec, 600.0))


def cohost_idle_sec() -> float:
    """Legacy / optional extra quiet before banter (max with :func:`cohost_after_chat_sec`)."""
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


def cohost_banter_fail_backoff_sec() -> float:
    """Quiet period after a banter script fails to parse (stops rapid retry spam)."""
    raw = (os.environ.get("LUNA_COHOST_BANTER_FAIL_BACKOFF_SEC") or "45").strip() or "45"
    try:
        sec = float(raw)
    except ValueError:
        sec = 45.0
    return max(15.0, min(sec, 600.0))


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
