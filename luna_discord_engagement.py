"""Discord server engagement memory + daily fan posts (Wolf Den / community guilds)."""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Weekday themes aligned with the Wolf Den engagement plan (rotate Mon–Sun).
DAILY_THEMES: tuple[dict[str, str], ...] = (
    {
        "id": "mon_momentum",
        "title": "Monday momentum",
        "focus": "Weekend recap, what is coming on stream, link #community-chat for discussion.",
        "ctas": "#luna-chat for questions, #fan-videos for clips, #introductions for new wolves.",
    },
    {
        "id": "tue_prompt",
        "title": "Tuesday check-in",
        "focus": "Low-bar community prompt: one word or one laugh from their week.",
        "ctas": "Reply in #community-chat; art WIP welcome in #fan-images.",
    },
    {
        "id": "wed_wolf_den",
        "title": "Wolf Den Wednesday",
        "focus": "Weekly theme: fan art spotlight, co-host shout-out, pack energy without spam.",
        "ctas": "#fan-images fan art, #viktor-chat or #himari-chat for co-host banter.",
    },
    {
        "id": "thu_ama",
        "title": "Thursday AMA",
        "focus": "Open Q&A hour vibe — ask Luna anything (lore, games, stream).",
        "ctas": "#luna-chat is the mic; mention Viktor/Himari if you want their take.",
    },
    {
        "id": "fri_fan_art",
        "title": "Fan art Friday",
        "focus": "Celebrate creators; credit artists; invite new submissions.",
        "ctas": "Post in #fan-images; best piece gets a shoutout next stream.",
    },
    {
        "id": "sat_clips",
        "title": "Saturday clip challenge",
        "focus": "15s highlight or funniest moment; meme edits welcome.",
        "ctas": "#fan-videos; tag friends in #community-chat.",
    },
    {
        "id": "sun_intro",
        "title": "Sunday introductions",
        "focus": "Welcome lurkers; introductions bump; cozy recap of the week.",
        "ctas": "Say hi in #introductions; veterans welcome newcomers.",
    },
)

_state_lock = asyncio.Lock()


def _env_truthy(key: str, default: bool = False) -> bool:
    raw = (os.environ.get(key, "") or "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def engagement_enabled() -> bool:
    return _env_truthy("LUNA_DISCORD_ENGAGEMENT", default=True)


def daily_post_enabled() -> bool:
    return engagement_enabled() and _env_truthy("LUNA_DISCORD_DAILY_POST", default=True)


def engagement_guild_ids() -> frozenset[int]:
    raw = (os.environ.get("LUNA_DISCORD_ENGAGEMENT_GUILD_IDS") or "").strip()
    if not raw:
        raw = (os.environ.get("LUNA_DISCORD_COMMUNITY_GUILD_IDS") or "").strip()
    if not raw:
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


def _daily_post_hour_local() -> int:
    raw = (os.environ.get("LUNA_DISCORD_DAILY_POST_HOUR") or "10").strip()
    try:
        return max(0, min(23, int(raw)))
    except ValueError:
        return 10


def _poll_interval_sec() -> float:
    raw = (os.environ.get("LUNA_DISCORD_ENGAGEMENT_POLL_SEC") or "900").strip()
    try:
        return max(120.0, float(raw))
    except ValueError:
        return 900.0


def _state_path() -> Path:
    raw = (os.environ.get("LUNA_DISCORD_ENGAGEMENT_STATE_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(__file__).resolve().parent / "data" / "discord_engagement_state.json"


def _local_today() -> str:
    return datetime.now().astimezone().date().isoformat()


def _local_weekday() -> int:
    return datetime.now().astimezone().weekday()


def _theme_for_today() -> dict[str, str]:
    return DAILY_THEMES[_local_weekday() % len(DAILY_THEMES)]


def load_all_state() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_all_state(data: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _guild_bucket(data: dict[str, Any], guild_id: int) -> dict[str, Any]:
    key = str(int(guild_id))
    bucket = data.get(key)
    if not isinstance(bucket, dict):
        bucket = {}
        data[key] = bucket
    return bucket


def _today_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    today = _local_today()
    day = bucket.get("today")
    if not isinstance(day, dict) or day.get("date") != today:
        day = {
            "date": today,
            "messages_total": 0,
            "by_channel": {},
            "new_member_ids": [],
            "samples": [],
        }
        bucket["today"] = day
    return day


def _sanitize_sample(text: str, *, max_len: int = 100) -> str:
    s = re.sub(r"<@[!&]?\d+>", "@member", (text or "").strip())
    s = re.sub(r"https?://\S+", "[link]", s)
    s = re.sub(r"\s+", " ", s)
    if len(s) > max_len:
        s = s[: max_len - 3].rstrip() + "..."
    return s


async def record_message(
    guild_id: int,
    *,
    channel_id: int,
    channel_name: str,
    author_id: int,
    content: str,
    is_bot: bool,
) -> None:
    """Track community-channel activity for daily post context."""
    if not engagement_enabled() or is_bot:
        return
    if guild_id not in engagement_guild_ids():
        return
    from luna_discord_community import community_channel_ids_for_guild

    tracked = community_channel_ids_for_guild(guild_id)
    if tracked and int(channel_id) not in tracked:
        return

    preview = _sanitize_sample(content)
    if not preview:
        return

    async with _state_lock:
        data = load_all_state()
        bucket = _guild_bucket(data, guild_id)
        day = _today_bucket(bucket)
        day["messages_total"] = int(day.get("messages_total") or 0) + 1
        by_ch = day.setdefault("by_channel", {})
        ch_key = str(channel_id)
        ch_row = by_ch.get(ch_key)
        if not isinstance(ch_row, dict):
            ch_row = {"name": channel_name, "count": 0}
            by_ch[ch_key] = ch_row
        ch_row["count"] = int(ch_row.get("count") or 0) + 1
        ch_row["name"] = channel_name or ch_row.get("name") or ch_key

        samples: list[str] = day.setdefault("samples", [])
        if preview and preview not in samples and len(samples) < 10:
            samples.append(preview)

        bucket["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_all_state(data)


async def note_new_member(guild_id: int, user_id: int, display_name: str) -> None:
    if not engagement_enabled() or guild_id not in engagement_guild_ids():
        return
    async with _state_lock:
        data = load_all_state()
        bucket = _guild_bucket(data, guild_id)
        day = _today_bucket(bucket)
        ids: list[str] = day.setdefault("new_member_ids", [])
        uid = str(user_id)
        if uid not in ids:
            ids.append(uid)
        names: dict[str, str] = day.setdefault("new_member_names", {})
        names[uid] = (display_name or uid)[:64]
        save_all_state(data)


async def refresh_guild_snapshot(guild: Any) -> None:
    """Persist member count, channel map, and community layout ids."""
    if guild is None or not engagement_enabled():
        return
    gid = int(guild.id)
    if gid not in engagement_guild_ids():
        return

    from luna_discord_community import load_guild_state

    comm = load_guild_state(gid)
    channels_meta: dict[str, Any] = {}
    if comm:
        for key, meta in (comm.channels or {}).items():
            if isinstance(meta, dict):
                channels_meta[key] = {
                    "id": meta.get("id"),
                    "persona": meta.get("persona"),
                    "fan_gallery": bool(meta.get("fan_gallery")),
                }

    async with _state_lock:
        data = load_all_state()
        bucket = _guild_bucket(data, gid)
        bucket["guild_name"] = getattr(guild, "name", str(gid))
        bucket["member_count"] = int(getattr(guild, "member_count", 0) or len(guild.members))
        bucket["community_channels"] = channels_meta
        bucket["snapshot_at"] = datetime.now(timezone.utc).isoformat()
        _today_bucket(bucket)
        save_all_state(data)


def _daily_post_channel_id() -> int | None:
    raw = (os.environ.get("LUNA_DISCORD_DAILY_CHANNEL_ID") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def resolve_daily_channel_id(guild_id: int) -> int | None:
    forced = _daily_post_channel_id()
    if forced:
        return forced
    from luna_discord_community import load_guild_state

    st = load_guild_state(guild_id)
    if st:
        for key in ("community-chat", "luna-chat"):
            meta = st.channels.get(key)
            if isinstance(meta, dict) and meta.get("id"):
                try:
                    return int(meta["id"])
                except (TypeError, ValueError):
                    continue
    return None


def build_state_summary(guild_id: int) -> str:
    """Human-readable snapshot for the LLM daily post prompt."""
    data = load_all_state()
    bucket = _guild_bucket(data, guild_id)
    day = bucket.get("today") if isinstance(bucket.get("today"), dict) else {}
    if day.get("date") != _local_today():
        day = {}

    theme = _theme_for_today()
    lines = [
        f"Server: {bucket.get('guild_name', guild_id)}",
        f"Members (approx): {bucket.get('member_count', '?')}",
        f"Today's theme: {theme['title']} — {theme['focus']}",
        f"Messages today in tracked channels: {day.get('messages_total', 0)}",
    ]

    by_ch = day.get("by_channel") if isinstance(day.get("by_channel"), dict) else {}
    if by_ch:
        lines.append("Activity by channel today:")
        for row in sorted(
            by_ch.values(),
            key=lambda r: int(r.get("count", 0)) if isinstance(r, dict) else 0,
            reverse=True,
        ):
            if isinstance(row, dict) and row.get("count"):
                lines.append(f"  - #{row.get('name', '?')}: {row['count']} messages")

    new_names = day.get("new_member_names") if isinstance(day.get("new_member_names"), dict) else {}
    if new_names:
        lines.append(f"New members today: {', '.join(new_names.values())}")

    samples = day.get("samples") if isinstance(day.get("samples"), list) else []
    if samples:
        lines.append("Sample fan messages (paraphrase, do not quote verbatim):")
        for s in samples[:6]:
            lines.append(f"  - {s}")

    layout = bucket.get("community_channels") if isinstance(bucket.get("community_channels"), dict) else {}
    if layout:
        lines.append("Community channels: " + ", ".join(f"#{k}" for k in sorted(layout.keys())))

    lines.append(f"Suggested CTAs for today: {theme['ctas']}")
    return "\n".join(lines)


def _llm_daily_post(system_extra: str, user_prompt: str) -> str:
    from ollama_client import (
        build_client,
        chat_request_kwargs,
        resolve_chat_model,
        strip_think_blocks,
    )
    from luna_persona import build_luna_system_prompt

    system = build_luna_system_prompt()
    system += (
        "\n\nYou are posting the **daily Wolf Den engagement message** in your Discord server. "
        "Write as Luna in plain text (Discord markdown ok: **bold**, bullet lines). "
        "Be warm, specific, and actionable — not generic VTuber spam. "
        "Include 2–4 short sections max, emoji light (0–3 total). "
        "End with clear calls-to-action using channel names like #luna-chat. "
        "Do not mention being an AI or a bot."
        f"\n\n{system_extra}"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]
    client = build_client()
    model = resolve_chat_model()
    kwargs = chat_request_kwargs(model, messages, stream=False)
    response = client.chat(**kwargs)
    return strip_think_blocks((response.message.content or "").strip())


def _fallback_daily_post(guild_name: str, theme: dict[str, str], summary: str) -> str:
    today = datetime.now().astimezone().strftime("%A %d %b")
    return (
        f"**🐺 {guild_name} — Daily ({today})**\n"
        f"**{theme['title']}**\n\n"
        f"{theme['focus']}\n\n"
        f"**Where to hang out**\n{theme['ctas']}\n\n"
        f"_Pack notes:_ {summary.splitlines()[2] if summary else 'Come say hi.'}"
    )[:1900]


async def generate_daily_post_text(guild_id: int) -> str:
    data = load_all_state()
    bucket = _guild_bucket(data, guild_id)
    gname = str(bucket.get("guild_name") or "the Wolf Den")
    theme = _theme_for_today()
    summary = build_state_summary(guild_id)
    user_prompt = (
        f"Write today's daily engagement post for **{gname}**.\n\n"
        f"Server snapshot:\n{summary}\n\n"
        "Requirements:\n"
        "- Opening line with today's theme name.\n"
        "- One paragraph tying theme to what fans can do today.\n"
        "- Bullet list: 3 concrete activities (use the channel names from the snapshot).\n"
        "- One line welcoming new members if any joined today.\n"
        "- Keep under 1200 characters.\n"
    )
    try:
        text = await asyncio.to_thread(
            _llm_daily_post,
            f"Theme id: {theme['id']}.",
            user_prompt,
        )
        if text and len(text) >= 80:
            return text[:1900]
    except Exception as exc:  # noqa: BLE001
        print(f"(discord engagement) LLM daily post failed: {exc}", flush=True)
    return _fallback_daily_post(gname, theme, summary)


def _already_posted_today(bucket: dict[str, Any]) -> bool:
    posts = bucket.get("daily_posts")
    if not isinstance(posts, dict):
        return False
    return posts.get("last_date") == _local_today()


def _mark_posted_today(bucket: dict[str, Any], *, channel_id: int, theme_id: str, preview: str) -> None:
    posts = bucket.setdefault("daily_posts", {})
    if not isinstance(posts, dict):
        posts = {}
        bucket["daily_posts"] = posts
    posts["last_date"] = _local_today()
    posts["last_theme"] = theme_id
    posts["last_channel_id"] = channel_id
    history = posts.setdefault("history", [])
    if isinstance(history, list):
        history.append(
            {
                "date": _local_today(),
                "theme": theme_id,
                "preview": (preview or "")[:200],
            }
        )
        posts["history"] = history[-30:]


def should_run_daily_post_now(bucket: dict[str, Any]) -> bool:
    if _already_posted_today(bucket):
        return False
    hour = datetime.now().astimezone().hour
    return hour >= _daily_post_hour_local()


async def try_post_daily(
    bot: Any,
    guild: Any,
    *,
    force: bool = False,
) -> bool:
    """Post one daily engagement message if due (or force=True)."""
    if not daily_post_enabled() or guild is None:
        return False
    gid = int(guild.id)
    if gid not in engagement_guild_ids():
        return False

    async with _state_lock:
        data = load_all_state()
        bucket = _guild_bucket(data, gid)
        if not force and not should_run_daily_post_now(bucket):
            return False
        if _already_posted_today(bucket) and not force:
            return False

    await refresh_guild_snapshot(guild)
    cid = resolve_daily_channel_id(gid)
    if cid is None:
        print(f"(discord engagement) no daily channel for guild {gid}", flush=True)
        return False

    ch = guild.get_channel(cid)
    if ch is None:
        try:
            ch = await bot.fetch_channel(cid)
        except Exception as exc:  # noqa: BLE001
            print(f"(discord engagement) fetch_channel({cid}) failed: {exc}", flush=True)
            return False

    perms = getattr(ch, "permissions_for", None)
    if perms and guild.me and not perms(guild.me).send_messages:
        print(f"(discord engagement) cannot send in #{getattr(ch, 'name', cid)}", flush=True)
        return False

    theme = _theme_for_today()
    body = await generate_daily_post_text(gid)
    if not body.strip():
        return False

    header = f"**🐺 Wolf Den Daily — {theme['title']}** ({_local_today()})\n\n"
    if not body.lstrip().startswith("**"):
        body = header + body
    elif "Wolf Den Daily" not in body[:120]:
        body = header + body

    try:
        await ch.send(body[:1900])
    except Exception as exc:  # noqa: BLE001
        print(f"(discord engagement) daily post send failed: {exc}", flush=True)
        return False

    async with _state_lock:
        data = load_all_state()
        bucket = _guild_bucket(data, gid)
        _mark_posted_today(
            bucket,
            channel_id=cid,
            theme_id=theme["id"],
            preview=body[:200],
        )
        save_all_state(data)

    print(
        f"(discord engagement) daily post in #{getattr(ch, 'name', cid)} "
        f"({guild.name!r}, theme={theme['id']})",
        flush=True,
    )
    return True


async def engagement_loop(bot: Any) -> None:
    """Background loop: refresh snapshots and post daily engagement when due."""
    await bot.wait_until_ready()
    await asyncio.sleep(12.0)
    ids = engagement_guild_ids()
    if not ids:
        print("(discord engagement) no guild ids configured", flush=True)
        return

    print(
        f"(discord engagement) memory ON — guild(s) {', '.join(str(i) for i in sorted(ids))}; "
        f"daily post hour>={_daily_post_hour_local()}:00 local",
        flush=True,
    )

    while not bot.is_closed():
        for gid in ids:
            guild = bot.get_guild(int(gid))
            if guild is None:
                continue
            try:
                await refresh_guild_snapshot(guild)
                if daily_post_enabled():
                    await try_post_daily(bot, guild, force=False)
            except Exception as exc:  # noqa: BLE001
                print(f"(discord engagement) loop error for {gid}: {exc}", flush=True)
        await asyncio.sleep(_poll_interval_sec())
