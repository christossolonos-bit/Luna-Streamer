"""Rolling live-chat context for Luna/Viktor (YouTube Live, TikTok Live)."""

from __future__ import annotations

import os
from collections import deque
from typing import Literal

LivePlatform = Literal["youtube", "tiktok"]

_PLATFORM: dict[LivePlatform, dict[str, str]] = {
    "youtube": {
        "label": "YouTube Live",
        "lines": "LUNA_YOUTUBE_LIVE_SESSION_LINES",
        "conversational": "LUNA_YOUTUBE_LIVE_CONVERSATIONAL",
        "banter": "LUNA_YOUTUBE_LIVE_BANTER_FROM_CHAT",
    },
    "tiktok": {
        "label": "TikTok Live",
        "lines": "LUNA_TIKTOK_LIVE_SESSION_LINES",
        "conversational": "LUNA_TIKTOK_LIVE_CONVERSATIONAL",
        "banter": "LUNA_TIKTOK_LIVE_BANTER_FROM_CHAT",
    },
}


def _max_lines(platform: LivePlatform) -> int:
    key = _PLATFORM[platform]["lines"]
    default = "48"
    raw = (os.environ.get(key) or default).strip() or default
    try:
        n = int(raw)
    except ValueError:
        n = 48
    return max(8, min(n, 200))


def _env_enabled(key: str, *, default: bool = True) -> bool:
    raw = (os.environ.get(key) or ("1" if default else "0")).strip().lower()
    return raw not in ("0", "false", "no", "off")


def live_platform_conversational_enabled(platform: LivePlatform) -> bool:
    return _env_enabled(_PLATFORM[platform]["conversational"], default=True)


def live_platform_reply_style_block(platform: LivePlatform) -> str:
    label = _PLATFORM[platform]["label"]
    if not live_platform_conversational_enabled(platform):
        return ""
    return (
        f"## {label} — how to talk with chat\n"
        "- **Conversation, not Q&A:** react to what they meant; ask a short follow-up when it fits.\n"
        "- **Use their name** and, when you remember it, **what they or others said earlier this stream**.\n"
        "- **2–5 sentences** is fine when the topic needs it; one line is enough for a simple hi.\n"
        "- You are on stream with Luna — sound present and interested, not like a help desk."
    )


def live_platform_banter_from_chat_enabled(platform: LivePlatform) -> bool:
    return _env_enabled(_PLATFORM[platform]["banter"], default=True)


class LivePlatformSessionLog:
    """Viewer lines + Luna/Viktor replies for one live platform connection."""

    def __init__(self, platform: LivePlatform) -> None:
        self._platform = platform
        self._label = _PLATFORM[platform]["label"]
        self._lines: deque[tuple[str, str]] = deque(maxlen=_max_lines(platform))

    def clear(self) -> None:
        self._lines.clear()

    def note_viewer(self, author: str, text: str) -> None:
        who = (author or "viewer").strip()
        body = (text or "").strip()
        if not body:
            return
        self._lines.append(("viewer", f"{who}: {body}"))

    def note_reply(
        self,
        *,
        speaker: str,
        author: str,
        user_text: str,
        reply: str,
        cohost_display: str = "Viktor",
    ) -> None:
        tag = "luna" if speaker == "luna" else cohost_display.strip().lower() or "cohost"
        who = (author or "viewer").strip()
        ref = (user_text or "").strip().replace("\n", " ")
        if len(ref) > 100:
            ref = ref[:97] + "…"
        body = (reply or "").strip().replace("\n", " ")
        if len(body) > 280:
            body = body[:277] + "…"
        self._lines.append((tag, f"{tag.title()} → {who} (re: «{ref}»): {body}"))

    def _recent_body(self, *, limit: int) -> str:
        if not self._lines:
            return ""
        rows = list(self._lines)[-limit:]
        return "\n".join(f"- [{role}] {line}" for role, line in rows)

    def block_for_chat_reply(self) -> str:
        body = self._recent_body(limit=24)
        if not body:
            return ""
        return (
            f"## {self._label} chat thread (this stream)\n"
            "Treat this as ongoing conversation — reference earlier lines when relevant.\n"
            f"{body}"
        )

    def block_for_banter(self, *, cohost_name: str = "Viktor") -> str:
        if not live_platform_banter_from_chat_enabled(self._platform):
            return ""
        body = self._recent_body(limit=32)
        if not body:
            return ""
        return (
            f"## Recent {self._label} chat — debrief together now\n"
            f"Luna and {cohost_name} are quiet on mic; chat was active. Discuss **specific** viewers "
            "and what they said — jokes, takes, who surprised you, what you might say when they return. "
            "Do not read the log line-by-line; talk like co-hosts after a segment.\n"
            f"{body}"
        )

    def has_context(self) -> bool:
        return bool(self._lines)


class YouTubeLiveSessionLog(LivePlatformSessionLog):
    def __init__(self) -> None:
        super().__init__("youtube")


class TikTokLiveSessionLog(LivePlatformSessionLog):
    def __init__(self) -> None:
        super().__init__("tiktok")


def youtube_live_conversational_replies_enabled() -> bool:
    return live_platform_conversational_enabled("youtube")


def youtube_live_reply_style_block() -> str:
    return live_platform_reply_style_block("youtube")


def youtube_live_banter_from_chat_enabled() -> bool:
    return live_platform_banter_from_chat_enabled("youtube")


def tiktok_live_conversational_replies_enabled() -> bool:
    return live_platform_conversational_enabled("tiktok")


def tiktok_live_reply_style_block() -> str:
    return live_platform_reply_style_block("tiktok")


def tiktok_live_banter_from_chat_enabled() -> bool:
    return live_platform_banter_from_chat_enabled("tiktok")
