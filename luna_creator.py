"""Recognize the streamer (creator) on the local viewer panel / enrolled mic."""

from __future__ import annotations

import os


def creator_display_name() -> str:
    """Human name Luna/Viktor should use for the streamer."""
    for key in ("LUNA_CREATOR_NAME", "LUNA_STREAMER_NAME", "STREAMER_NAME"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return raw
    ch = (os.environ.get("TWITCH_CHANNEL") or "").strip().lstrip("#")
    if ch:
        return ch
    return "Creator"


def _creator_aliases() -> set[str]:
    name = creator_display_name().lower()
    extras = (os.environ.get("LUNA_CREATOR_ALIASES") or "").strip()
    out = {
        name,
        "creator",
        "streamer",
        "you",
        "viewer",
        "host",
        "owner",
    }
    if extras:
        for part in extras.replace(",", " ").split():
            p = part.strip().lower()
            if p:
                out.add(p)
    return out


def is_creator_viewer_turn(
    *,
    source: str,
    author: str = "",
    speaker_verified: bool = False,
) -> bool:
    """True when the turn is the streamer talking on the local viewer (not Twitch/YouTube chat)."""
    if speaker_verified:
        return True
    src = (source or "").strip().lower()
    if src in ("viewer panel", "viewer voice", "viewer mic"):
        return True
    if "viewer panel" in src or "viewer voice" in src:
        return True
    auth = (author or "").strip().lower()
    if auth and auth in _creator_aliases():
        return True
    return False


def cohost_replies_to_creator_enabled() -> bool:
    """When True, creator panel/voice may route to Viktor as well as Luna (if co-host chat personas on)."""
    from vampire_cohost import cohost_chat_personas_enabled

    if not cohost_chat_personas_enabled():
        return False
    raw = (os.environ.get("LUNA_COHOST_CREATOR_CHAT") or "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def creator_chat_system_block(*, name: str | None = None) -> str:
    """Injected into Luna/Viktor system prompts when the creator is speaking."""
    n = (name or creator_display_name()).strip() or "Creator"
    return (
        "## Your creator is speaking\n"
        f"**{n}** is your creator — the streamer who built and runs you. "
        "They are talking to you **directly** on the local viewer (typed chat or their enrolled mic), "
        "not anonymous Twitch/YouTube chat.\n"
        "- Acknowledge that it is them when it fits (use their name; warm and in-character, not cringe worship).\n"
        "- Answer them like someone you know well, not like a random viewer.\n"
        "- Viktor and Luna both treat this person as the authority behind the stream setup."
    )


def format_creator_user_line(*, author: str, question: str, source: str) -> str:
    """User-turn prefix so memory/models keep creator identity explicit."""
    n = (author or creator_display_name()).strip() or creator_display_name()
    src = (source or "viewer").strip()
    return f"[{n} — your creator, via {src}]: {question.strip()}"
