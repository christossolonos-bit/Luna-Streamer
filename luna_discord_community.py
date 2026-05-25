"""Discord community layout: persona chat + fan media channels (create-only, never delete)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import discord
except ImportError:  # pragma: no cover
    discord = None  # type: ignore[assignment]


def _env_truthy(key: str, default: bool = False) -> bool:
    raw = (os.environ.get(key, "") or "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def community_setup_enabled() -> bool:
    return _env_truthy("LUNA_DISCORD_COMMUNITY_SETUP", default=True)


def community_auto_setup_guild_ids() -> frozenset[int]:
    raw = (os.environ.get("LUNA_DISCORD_COMMUNITY_GUILD_IDS") or "").strip()
    if not raw:
        # Default: welcome guild when set.
        raw = (os.environ.get("LUNA_DISCORD_WELCOME_GUILD_ID") or "").strip()
    out: set[int] = set()
    for part in raw.replace(";", " ").replace(",", " ").split():
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            continue
    return frozenset(out)


def community_auto_on_ready() -> bool:
    return _env_truthy("LUNA_DISCORD_COMMUNITY_AUTO_ON_READY", default=True)


def _state_path() -> Path:
    raw = (os.environ.get("LUNA_DISCORD_COMMUNITY_STATE_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(__file__).resolve().parent / "data" / "discord_community_channels.json"


def _slug(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9\-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:96] or "channel"


@dataclass(frozen=True)
class ChannelSpec:
    name: str
    topic: str
    persona: str | None = None  # luna | viktor | himari → dedicated chat
    intro: str = ""
    allow_attachments: bool = True


@dataclass(frozen=True)
class CategorySpec:
    name: str
    channels: tuple[ChannelSpec, ...]


def default_community_layout() -> tuple[CategorySpec, ...]:
    from himari_cohost import himari_enabled, himari_name
    from vampire_cohost import cohost_enabled, cohost_name

    ln = "Luna"
    vn = cohost_name()
    hn = himari_name()
    cast_channels: list[ChannelSpec] = [
        ChannelSpec(
            "luna-chat",
            f"Chat with **{ln}** — every message here is for Luna.",
            persona="luna",
            intro=(
                f"Welcome to **{ln} Chat**.\n"
                "Talk to Luna here — every message is for Luna. "
                "Be kind; no spam. This channel is never auto-deleted."
            ),
        ),
    ]
    if cohost_enabled():
        cast_channels.append(
            ChannelSpec(
                "viktor-chat",
                f"Chat with **{vn}** — every message here is for Viktor.",
                persona="viktor",
                intro=(
                    f"Welcome to **{vn} Chat**.\n"
                    f"Talk to **{vn}** directly — the co-host replies here. "
                    "Keep it cozy — we're building a community."
                ),
            ),
        )
    if himari_enabled():
        cast_channels.append(
            ChannelSpec(
                "himari-chat",
                f"Chat with **{hn}** — every message here is for Himari.",
                persona="himari",
                intro=(
                    f"Welcome to **{hn} Chat**.\n"
                    f"Talk to **{hn}** directly — shy shrine-maiden energy welcome. "
                    "Soft vibes only."
                ),
            ),
        )
    return (
        CategorySpec("Talk to the Cast", tuple(cast_channels)),
        CategorySpec(
            "Fan Gallery",
            (
                ChannelSpec(
                    "fan-images",
                    "Share fan art and screenshots. Images only — be respectful.",
                    intro=(
                        "**Fan images** — post your art, edits, and screenshots.\n"
                        "Credit artists when you can. Luna may reply if you @ her. "
                        "Channels here are kept forever (never deleted by the bot)."
                    ),
                    allow_attachments=True,
                ),
                ChannelSpec(
                    "fan-videos",
                    "Share fan clips, highlights, and short videos.",
                    intro=(
                        "**Fan videos** — clips, highlights, memes, and edits.\n"
                        "Keep uploads reasonable; follow Discord ToS."
                    ),
                    allow_attachments=True,
                ),
            ),
        ),
        CategorySpec(
            "Community Lounge",
            (
                ChannelSpec(
                    "community-chat",
                    "General hangout for fans — all cast members may chime in if mentioned.",
                    intro=(
                        "**Community lounge** — meet other fans.\n"
                        "Mention **Luna**, **Viktor**, or **Himari** (or @ the bot) for a reply."
                    ),
                ),
                ChannelSpec(
                    "introductions",
                    "Say hi — tell us what you watch and what you like.",
                    intro="**Introductions** — who are you, and how did you find the stream?",
                ),
            ),
        ),
    )


@dataclass
class GuildCommunityState:
    guild_id: int
    categories: dict[str, int] = field(default_factory=dict)
    channels: dict[str, dict[str, Any]] = field(default_factory=dict)

    def channel_ids(self) -> frozenset[int]:
        out: set[int] = set()
        for meta in self.channels.values():
            try:
                out.add(int(meta.get("id") or 0))
            except (TypeError, ValueError):
                continue
        return frozenset(cid for cid in out if cid > 0)

    def persona_for_channel(self, channel_id: int) -> str | None:
        for meta in self.channels.values():
            try:
                if int(meta.get("id") or 0) != int(channel_id):
                    continue
            except (TypeError, ValueError):
                continue
            p = str(meta.get("persona") or "").strip().lower()
            if p in ("luna", "viktor", "himari"):
                return p
        return None

    def is_fan_channel(self, channel_id: int) -> bool:
        for key, meta in self.channels.items():
            try:
                if int(meta.get("id") or 0) != int(channel_id):
                    continue
            except (TypeError, ValueError):
                continue
            return key.startswith("fan-") or bool(meta.get("fan_gallery"))
        return False


def load_all_states() -> dict[str, dict[str, Any]]:
    path = _state_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_all_states(data: dict[str, dict[str, Any]]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_guild_state(guild_id: int) -> GuildCommunityState | None:
    raw = load_all_states().get(str(int(guild_id)))
    if not isinstance(raw, dict):
        return None
    return GuildCommunityState(
        guild_id=int(guild_id),
        categories=dict(raw.get("categories") or {}),
        channels=dict(raw.get("channels") or {}),
    )


def save_guild_state(state: GuildCommunityState) -> None:
    data = load_all_states()
    data[str(state.guild_id)] = {
        "categories": state.categories,
        "channels": state.channels,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    save_all_states(data)


def persona_for_channel_id(guild_id: int | None, channel_id: int) -> str | None:
    if guild_id is None:
        return None
    st = load_guild_state(int(guild_id))
    if st is None:
        return None
    return st.persona_for_channel(int(channel_id))


def is_fan_gallery_channel(guild_id: int | None, channel_id: int) -> bool:
    if guild_id is None:
        return False
    st = load_guild_state(int(guild_id))
    if st is None:
        return False
    return st.is_fan_channel(int(channel_id))


def community_channel_ids_for_guild(guild_id: int) -> frozenset[int]:
    st = load_guild_state(guild_id)
    if st is None:
        return frozenset()
    return st.channel_ids()


async def _find_category(guild: Any, name: str) -> Any | None:
    slug = _slug(name)
    for cat in getattr(guild, "categories", []) or []:
        if _slug(getattr(cat, "name", "")) == slug:
            return cat
    return None


async def _find_text_channel(
    guild: Any,
    name: str,
    *,
    category: Any | None = None,
) -> Any | None:
    slug = _slug(name)
    for ch in getattr(guild, "text_channels", []) or []:
        if _slug(getattr(ch, "name", "")) != slug:
            continue
        if category is not None and getattr(ch, "category_id", None) != category.id:
            continue
        return ch
    return None


async def _send_intro(channel: Any, text: str) -> None:
    body = (text or "").strip()
    if not body:
        return
    try:
        history = [m async for m in channel.history(limit=5)]
        if history:
            return
    except Exception:
        pass
    try:
        await channel.send(body[:1900])
    except Exception:
        pass


async def setup_guild_community(
    guild: Any,
    *,
    layout: tuple[CategorySpec, ...] | None = None,
) -> tuple[list[str], list[str]]:
    """Create missing categories/channels. Never deletes or renames existing ones."""
    if discord is None:
        return [], ["discord.py is not installed"]

    me = guild.me
    if me is None:
        return [], ["Bot member not resolved — try again in a moment"]

    perms = me.guild_permissions
    if not getattr(perms, "manage_channels", False):
        return (
            [],
            [
                "Missing **Manage Channels** permission. Re-invite the bot with that permission "
                "or enable it for Luna's role, then run `!setup-community` again.",
            ],
        )

    layout = layout or default_community_layout()
    state = load_guild_state(int(guild.id)) or GuildCommunityState(guild_id=int(guild.id))
    created: list[str] = []
    notes: list[str] = []

    for cat_spec in layout:
        cat_key = _slug(cat_spec.name)
        category = await _find_category(guild, cat_spec.name)
        if category is None:
            try:
                category = await guild.create_category(cat_spec.name)
                created.append(f"category:{cat_spec.name}")
            except Exception as exc:  # noqa: BLE001
                notes.append(f"Could not create category {cat_spec.name!r}: {exc}")
                continue
        state.categories[cat_key] = int(category.id)

        for ch_spec in cat_spec.channels:
            ch_key = _slug(ch_spec.name)
            existing = await _find_text_channel(guild, ch_spec.name, category=category)
            if existing is None:
                try:
                    existing = await guild.create_text_channel(
                        ch_spec.name,
                        category=category,
                        topic=(ch_spec.topic or "")[:1024],
                    )
                    created.append(f"#{ch_spec.name}")
                except Exception as exc:  # noqa: BLE001
                    notes.append(f"Could not create #{ch_spec.name}: {exc}")
                    continue

            meta: dict[str, Any] = {
                "id": int(existing.id),
                "name": ch_spec.name,
                "category": cat_spec.name,
            }
            if ch_spec.persona:
                meta["persona"] = ch_spec.persona
            if ch_key.startswith("fan-"):
                meta["fan_gallery"] = True
            state.channels[ch_key] = meta
            await _send_intro(existing, ch_spec.intro)

    save_guild_state(state)
    return created, notes


def format_setup_report(
    guild: Any,
    created: list[str],
    notes: list[str],
) -> str:
    st = load_guild_state(int(guild.id))
    lines = [
        f"**Community layout** for **{getattr(guild, 'name', guild.id)}**",
        "Created only what was missing — **nothing was deleted or renamed**.",
    ]
    if created:
        lines.append("\n**New:** " + ", ".join(created))
    else:
        lines.append("\nAll categories/channels already exist.")
    if st and st.channels:
        lines.append("\n**Channels tracked:**")
        for key in sorted(st.channels.keys()):
            meta = st.channels[key]
            pid = meta.get("id")
            persona = meta.get("persona")
            tag = f" → {persona}" if persona else ""
            lines.append(f"• `#{meta.get('name', key)}` (id `{pid}`){tag}")
    if notes:
        lines.append("\n**Notes:**")
        lines.extend(f"• {n}" for n in notes)
    lines.append(
        "\n**Tips:** `#luna-chat` / `#viktor-chat` / `#himari-chat` route to that cast member. "
        "`#fan-images` and `#fan-videos` are for uploads (mention Luna/Viktor/Himari to get a reply)."
    )
    return "\n".join(lines)[:1900]
