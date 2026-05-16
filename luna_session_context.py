"""Shared session context for Luna + co-host: where they exist and what “mode” the streamer is in."""

from __future__ import annotations

import os

from vampire_cohost import cohost_name

_SECTION_TITLE = "## Stream setup (facts — stay in character)"


def session_mode() -> str:
    """``auto`` | ``live`` | ``local`` (``viewer`` is treated as ``local``)."""
    raw = (os.environ.get("LUNA_SESSION_MODE") or "auto").strip().lower()
    if raw == "viewer":
        return "local"
    if raw in ("auto", "live", "local"):
        return raw
    return "auto"


def format_dual_presence_block(
    *,
    twitch_channel: str = "",
    youtube_live_listening: bool = False,
) -> str:
    """Text appended to system prompts so both personas know each other and the current setup.

    - **Who**: Luna (wolf-girl VTuber) and the vampire co-host appear as separate VRMs in the
      streamer's viewer and are usually composited in OBS.
    - **Where**: ``LUNA_SESSION_MODE`` + optional YouTube listener state + optional ``LUNA_SESSION_NOTE``.
    """
    vamp = cohost_name()
    mode = session_mode()
    note = (os.environ.get("LUNA_SESSION_NOTE") or "").strip()
    ch = (twitch_channel or "").strip().lstrip("#")

    creator = (os.environ.get("LUNA_CREATOR_NAME") or os.environ.get("LUNA_STREAMER_NAME") or "").strip()
    if not creator:
        creator = (os.environ.get("TWITCH_CHANNEL") or "").strip().lstrip("#")
    creator_clause = ""
    if creator:
        creator_clause = (
            f" The streamer **{creator}** is your **creator** (they run this setup); "
            f"when they use the viewer panel chat or enrolled mic, treat them as speaking directly to you—not a random viewer."
        )
    who = (
        f"You are Luna (wolf-girl VTuber) and **share the session** with {vamp}, your vampire co-host. "
        f"You are not the same person—you each control only your own voice. "
        f"You both render as separate VRM avatars in the streamer's **local viewer app** "
        f"and are typically shown together in **OBS** for stream output."
        f"{creator_clause}"
    )

    if mode == "live":
        situation = (
            "**Session mode: LIVE.** Treat this as a public-facing stream: chat may be from a live audience; "
            "you may reference being on stream when it fits naturally."
        )
    elif mode == "local":
        situation = (
            "**Session mode: LOCAL / VRM viewer.** The streamer may be rehearsing, testing lip-sync, "
            "or off-air—not necessarily broadcasting. Do not assume thousands of viewers unless chat implies it."
        )
    else:
        # auto
        parts = [
            "**Session mode: AUTO (infer from context).** "
            "You might be live on Twitch/YouTube, or only using the local VRM viewer—do not insist you are 'live' unless it fits."
        ]
        if youtube_live_listening:
            parts.append(
                "**Right now:** YouTube Live chat is **connected** to this bot, so some messages may be from the **live YouTube** chat."
            )
        else:
            parts.append(
                "YouTube Live chat ingestion is **not** active in this process unless the streamer turned it on."
            )
        parts.append(
            "If Twitch is connected, Twitch chat is real channel chat—viewers can chat whether the channel is live or not."
        )
        situation = " ".join(parts)

    lines: list[str] = [_SECTION_TITLE, who, situation]
    if ch:
        lines.append(f"Twitch channel (login) tied to this bot: `{ch}`.")
    if note:
        lines.append(f"Streamer note: {note}")
    return "\n\n".join(lines).strip()
