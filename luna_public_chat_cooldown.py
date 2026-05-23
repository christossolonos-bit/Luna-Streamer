"""Shared reply spacing for Twitch, YouTube Live, and TikTok Live chat."""

from __future__ import annotations

import os


def _parse_sec(raw: str, *, default: float) -> float:
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default


def public_chat_cooldown_sec() -> float:
    """Min seconds between auto-replies on any public chat surface (default 4)."""
    raw = (
        os.environ.get("LUNA_PUBLIC_CHAT_COOLDOWN_SEC")
        or os.environ.get("TWITCH_AUTO_COOLDOWN")
        or "4"
    ).strip() or "4"
    return _parse_sec(raw, default=4.0)


def youtube_live_cooldown_sec() -> float:
    raw = (os.environ.get("LUNA_YOUTUBE_LIVE_COOLDOWN_SEC") or "").strip()
    if raw:
        return _parse_sec(raw, default=4.0)
    return public_chat_cooldown_sec()


def tiktok_live_cooldown_sec() -> float:
    raw = (os.environ.get("LUNA_TIKTOK_LIVE_COOLDOWN_SEC") or "").strip()
    if raw:
        return _parse_sec(raw, default=4.0)
    return public_chat_cooldown_sec()


def _max_speakers_from_env(*keys: str, default: int) -> int:
    for key in keys:
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            continue
        try:
            return max(0, int(raw))
        except ValueError:
            continue
    return max(0, default)


def live_chat_max_speakers_per_message(source: str) -> int:
    """Max cast replies for one incoming live line (0 = no cap). TikTok/YouTube default 1."""
    s = (source or "").strip().lower()
    shared = (os.environ.get("LUNA_LIVE_CHAT_MAX_SPEAKERS_PER_MESSAGE") or "").strip()
    if shared:
        try:
            return max(0, int(shared))
        except ValueError:
            pass
    if s == "tiktok live":
        return _max_speakers_from_env(
            "LUNA_TIKTOK_LIVE_MAX_SPEAKERS_PER_MESSAGE",
            default=1,
        )
    if s == "youtube live":
        return _max_speakers_from_env(
            "LUNA_YOUTUBE_LIVE_MAX_SPEAKERS_PER_MESSAGE",
            default=1,
        )
    return _max_speakers_from_env("LUNA_TWITCH_MAX_SPEAKERS_PER_MESSAGE", default=0)
