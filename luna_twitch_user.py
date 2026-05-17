"""Twitch chatter identity for prompts and per-user memory."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from luna_creator import (
    creator_chat_system_block,
    creator_display_name,
    creator_twitch_logins,
    format_creator_user_line,
    is_creator_twitch_display,
    is_creator_twitch_login,
)


@dataclass(frozen=True)
class TwitchChatterProfile:
    """Who is speaking in Twitch chat (login is the stable id)."""

    login: str
    display_name: str
    is_broadcaster: bool = False
    is_mod: bool = False
    is_vip: bool = False
    is_subscriber: bool = False

    def address_name(self) -> str:
        """Chat name to use when speaking TO this chatter (display name, not login)."""
        return (self.display_name or self.login or "").strip() or "friend"

    def spoken_name(self) -> str:
        """Full label for logs / memory (includes login when it differs from display)."""
        login = (self.login or "").strip()
        display = self.address_name()
        if not login or display.lower() == login.lower():
            return display
        return f"{display} (@{login})"

    def role_labels(self) -> list[str]:
        tags: list[str] = []
        if self.is_broadcaster:
            tags.append("broadcaster / streamer")
        if self.is_mod and not self.is_broadcaster:
            tags.append("moderator")
        if self.is_vip and not self.is_broadcaster:
            tags.append("VIP")
        if self.is_subscriber and not self.is_broadcaster:
            tags.append("subscriber")
        return tags

    def role_phrase(self) -> str:
        labels = self.role_labels()
        if labels:
            return ", ".join(labels)
        return "viewer"


def is_creator_twitch_profile(profile: TwitchChatterProfile) -> bool:
    return (
        profile.is_broadcaster
        or is_creator_twitch_login(profile.login)
        or is_creator_twitch_display(profile.display_name)
    )


def profile_from_chatter(chatter: Any) -> TwitchChatterProfile:
    """Build a profile from a twitchio ``Chatter`` (or compatible object)."""
    login = (getattr(chatter, "name", None) or "").strip()
    display = (getattr(chatter, "display_name", None) or login).strip()
    return TwitchChatterProfile(
        login=login or "unknown",
        display_name=display or login or "unknown",
        is_broadcaster=bool(getattr(chatter, "is_broadcaster", False)),
        is_mod=bool(getattr(chatter, "is_mod", False)),
        is_vip=bool(getattr(chatter, "is_vip", False)),
        is_subscriber=bool(getattr(chatter, "is_subscriber", False)),
    )


def profile_from_login(
    login: str,
    *,
    display_name: str | None = None,
) -> TwitchChatterProfile:
    """Fallback when only a name string is known (e.g. YouTube live author)."""
    h = (login or "").strip() or "unknown"
    disp = (display_name or h).strip() or h
    return TwitchChatterProfile(
        login=h,
        display_name=disp,
        is_broadcaster=is_creator_twitch_login(h),
    )


def chatter_reply_system_note(
    *,
    profile: TwitchChatterProfile,
    message: str,
    speaker: str,
    platform: str = "Twitch",
    cohost_name: str = "Viktor",
    session_messages: int = 1,
    returning: bool = False,
) -> str:
    """Tell Luna/Viktor who this chatter is and to reply TO them by name."""
    who = cohost_name if speaker == "cohost" else "Luna"
    other = "Luna" if speaker == "cohost" else cohost_name
    chat_name = profile.address_name()
    login = profile.login
    roles = profile.role_phrase()
    visit = (
        f"They have sent **{session_messages}** messages this stream."
        if session_messages > 1
        else "First message from them this stream."
    )
    if returning:
        visit = f"{visit} You have talked with them before in this channel."
    return (
        f"## {platform} chatter (reply as **{who}** only — not as {other})\n"
        f"You are answering **{chat_name}**, a real person in {platform} chat — not a generic viewer.\n"
        f"- **Chat name (use this in your reply):** {chat_name}\n"
        f"- Twitch login (identity only, do not read aloud): `{login}`\n"
        f"- Role: {roles}\n"
        f"- {visit}\n"
        f"Open by using **{chat_name}** when it fits. Do not confuse them with anyone else in chat.\n"
        f"What they said:\n{message.strip()}"
    )


def live_chatter_system_note(
    *,
    profile: TwitchChatterProfile,
    message: str,
    speaker: str,
    platform: str = "Twitch",
    cohost_name: str = "Viktor",
    session_messages: int = 1,
    returning: bool = False,
) -> str:
    """Who is speaking on a live platform — system prompt only (not a fake user turn)."""
    if is_creator_twitch_profile(profile):
        who = cohost_name if speaker == "cohost" else "Luna"
        other = "Luna" if speaker == "cohost" else cohost_name
        owner = creator_display_name()
        return (
            f"## {platform} chat (for {who} only)\n"
            f"**{profile.address_name()}** (Twitch login `{profile.login}`) — {profile.role_phrase()} — "
            f"wrote in {platform} chat.\n"
            f"This is **{owner}**, your **owner and creator** — the person who built you and runs this stream. "
            f"**Never treat them as a random chatter.** Reply as **{who}** only; do not speak as {other}. "
            f"Speak to them with familiarity.\n"
            f"What they said:\n{message.strip()}"
        )
    return chatter_reply_system_note(
        profile=profile,
        message=message,
        speaker=speaker,
        platform=platform,
        cohost_name=cohost_name,
        session_messages=session_messages,
        returning=returning,
    )


def twitch_chatter_system_note(
    *,
    profile: TwitchChatterProfile,
    message: str,
    speaker: str,
    cohost_name: str = "Viktor",
) -> str:
    return live_chatter_system_note(
        profile=profile,
        message=message,
        speaker=speaker,
        platform="Twitch",
        cohost_name=cohost_name,
    )


def format_creator_twitch_user_line(*, profile: TwitchChatterProfile, question: str) -> str:
    """User turn when the owner speaks in Twitch chat."""
    n = profile.address_name()
    owner = creator_display_name()
    return (
        f"[{n} — your owner **{owner}** (Twitch `{profile.login}`), via Twitch chat]: "
        f"{question.strip()}"
    )


def format_twitch_reply_to_chatter(
    reply: str,
    profile: TwitchChatterProfile | None,
    *,
    mention: bool = True,
) -> str:
    """Prefix Twitch chat send with @login so the chatter gets notified."""
    text = (reply or "").strip()
    if not text or not profile or not mention:
        return text
    login = (profile.login or "").strip()
    if not login or login.lower() == "unknown":
        return text
    low = text.lower()
    if low.startswith(f"@{login.lower()}") or low.startswith(f"{login.lower()},"):
        return text
    combined = f"@{login} {text}"
    return combined[:500]


def creator_twitch_chat_system_block(*, profile: TwitchChatterProfile) -> str:
    """Extra system context when the owner chats on Twitch."""
    owner = creator_display_name()
    base = creator_chat_system_block(name=owner)
    logins = ", ".join(sorted(creator_twitch_logins())) or profile.login
    return (
        f"{base}\n"
        f"## Owner on Twitch chat (critical)\n"
        f"The message is from **{profile.address_name()}** — Twitch login **`{profile.login}`**. "
        f"That account is **{owner}**, your **owner**. Recognized owner logins include: {logins}.\n"
        f"- This is the same person as on the viewer panel, just typing in public chat.\n"
        f"- Do **not** greet them like a first-time viewer or ask who they are.\n"
        f"- Follow their lead; they outrank every other chatter."
    )
