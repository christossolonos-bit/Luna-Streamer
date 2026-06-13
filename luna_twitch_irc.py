"""Twitch IRC: primary channel + optional guest channels with per-channel triggers."""

from __future__ import annotations

import os


def parse_extra_irc_channels() -> dict[str, str]:
    """Parse ``TWITCH_EXTRA_IRC_CHANNELS`` → {login: 'all' | 'mention'}.

    Formats:
      rayen
      rayen:mention
      rayen:mention,other:all
    Default trigger for bare names: ``TWITCH_EXTRA_IRC_REPLY_TRIGGER`` (default mention).
    """
    default = (os.environ.get("TWITCH_EXTRA_IRC_REPLY_TRIGGER") or "mention").strip().lower()
    if default not in ("all", "mention"):
        default = "mention"

    raw = (os.environ.get("TWITCH_EXTRA_IRC_CHANNELS") or "").strip()
    out: dict[str, str] = {}
    for part in raw.replace(";", ",").split(","):
        p = part.strip()
        if not p:
            continue
        if ":" in p:
            name, trig = p.split(":", 1)
            ch = name.strip().lstrip("#").lower()
            mode = trig.strip().lower()
            if mode not in ("all", "mention"):
                mode = default
        else:
            ch = p.lstrip("#").lower()
            mode = default
        if ch:
            out[ch] = mode
    return out


def extra_irc_reply_cooldown_sec() -> float:
    raw = (os.environ.get("TWITCH_EXTRA_IRC_REPLY_COOLDOWN_SEC") or "").strip()
    if not raw:
        return 0.0
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.0


def twitch_initial_channel_logins(primary: str, extra: dict[str, str]) -> list[str]:
    """IRC rooms to join: primary first, then extras (no duplicates)."""
    main = (primary or "").strip().lstrip("#").lower()
    channels: list[str] = []
    if main:
        channels.append(main)
    for ch in extra:
        if ch and ch not in channels:
            channels.append(ch)
    return channels
