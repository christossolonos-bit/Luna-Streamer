"""Detect YouTube / Twitch / TikTok go-live; announce on Discord + post to X / Facebook."""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from youtube_audio import extract_video_id
from youtube_feed import (
    _is_youtube_observe_tab_url,
    channel_id as yt_legacy_channel_id,
    observe_channel_entries,
    resolve_channel_id,
)
from tiktok_live_chat import tiktok_live_username
from youtube_live_chat import youtube_live_check_probe_url, youtube_live_video_id

SocialShareSend = Callable[[str, str], Awaitable[None]]
BroadcastStatus = Callable[[str], Awaitable[None]]
DiscordLiveSend = Callable[[str], Awaitable[None]]


def _env_truthy(key: str, *, default: bool = False) -> bool:
    raw = (os.environ.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def live_social_share_enabled() -> bool:
    from social_playwright_share import social_playwright_configured

    return social_playwright_configured() and _env_truthy("LUNA_SOCIAL_LIVE_SHARE", default=False)


def twitch_live_announce_enabled() -> bool:
    return _env_truthy("LUNA_TWITCH_LIVE_ANNOUNCE", default=False)


def twitch_live_discord_enabled() -> bool:
    if not twitch_live_announce_enabled():
        return False
    return _env_truthy("LUNA_TWITCH_LIVE_DISCORD", default=True)


def twitch_live_social_enabled() -> bool:
    if not twitch_live_announce_enabled():
        return False
    if not _env_truthy("LUNA_TWITCH_LIVE_SOCIAL", default=True):
        return False
    from social_playwright_share import social_playwright_configured

    return social_playwright_configured()


def live_watch_enabled() -> bool:
    return live_social_share_enabled() or twitch_live_announce_enabled()


def live_social_poll_sec() -> float:
    raw = (os.environ.get("LUNA_SOCIAL_LIVE_POLL_SEC") or "90").strip() or "90"
    try:
        sec = float(raw)
    except ValueError:
        sec = 90.0
    return max(45.0, min(sec, 600.0))


def _state_path() -> Path:
    raw = (os.environ.get("LUNA_SOCIAL_LIVE_STATE_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(__file__).resolve().parent / "data" / "live_social_state.json"


def _load_state() -> dict[str, Any]:
    p = _state_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(data: dict[str, Any]) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _youtube_live_page_url(entry: str) -> str | None:
    raw = (entry or "").strip()
    if not raw:
        return None
    vid = extract_video_id(raw)
    if vid:
        return f"https://www.youtube.com/watch?v={vid}"
    if _is_youtube_observe_tab_url(raw):
        base = raw.split("?", 1)[0].strip().rstrip("/")
        if "/videos" in base.lower():
            base = re.split(r"/videos", base, flags=re.I)[0].rstrip("/")
        if not base.startswith("http"):
            base = f"https://www.youtube.com/{base.lstrip('/')}"
        return f"{base}/live"
    if raw.startswith("@"):
        return f"https://www.youtube.com/{raw}/live"
    url = raw if raw.startswith("http") else f"https://www.youtube.com/{raw.lstrip('/')}"
    if "/live" in url.lower():
        return url.split("?", 1)[0]
    if re.search(r"/(channel|@|c)/", url, re.I):
        return f"{url.rstrip('/')}/live"
    return f"{url.rstrip('/')}/live"


def youtube_live_probe_targets() -> list[str]:
    """URLs to probe with yt-dlp for an active YouTube live broadcast."""
    seen: set[str] = set()
    out: list[str] = []

    def add(u: str | None) -> None:
        if not u:
            return
        u = u.strip()
        if u and u not in seen:
            seen.add(u)
            out.append(u)

    vid = youtube_live_video_id()
    if vid:
        add(f"https://www.youtube.com/watch?v={vid}")

    check = (youtube_live_check_probe_url() or "").strip()
    if check:
        add(_youtube_live_page_url(check) or check)

    extra = (os.environ.get("LUNA_SOCIAL_LIVE_YOUTUBE_URLS") or "").strip()
    if extra:
        for part in re.split(r"[\s,]+", extra):
            add(_youtube_live_page_url(part) or part.strip())

    for entry in observe_channel_entries():
        add(_youtube_live_page_url(entry))

    legacy = yt_legacy_channel_id()
    if legacy:
        add(f"https://www.youtube.com/channel/{legacy}/live")

    return out


def probe_youtube_live(url: str) -> dict[str, str] | None:
    return _probe_youtube_live_sync(url)


class _YDLQuietLogger:
    """Swallow yt-dlp stderr noise when probing offline channels."""

    def debug(self, msg: str) -> None:  # noqa: ARG002
        pass

    def info(self, msg: str) -> None:  # noqa: ARG002
        pass

    def warning(self, msg: str) -> None:  # noqa: ARG002
        pass

    def error(self, msg: str) -> None:  # noqa: ARG002
        pass


def _probe_youtube_live_sync(url: str) -> dict[str, str] | None:
    try:
        import yt_dlp
    except ImportError:
        return None
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "logger": _YDLQuietLogger(),
        "skip_download": True,
        "noplaylist": True,
        "ignoreerrors": True,
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return None
    if not isinstance(info, dict):
        return None
    live = bool(info.get("is_live")) or str(info.get("live_status") or "").lower() == "is_live"
    if not live:
        return None
    vid = str(info.get("id") or "").strip()
    if not vid:
        return None
    title = (info.get("title") or "YouTube live").strip()
    page = (info.get("webpage_url") or "").strip() or f"https://www.youtube.com/watch?v={vid}"
    return {"id": vid, "title": title, "url": page, "platform": "youtube"}


async def probe_tiktok_live(unique_id: str) -> dict[str, str] | None:
    """Return live metadata when ``unique_id`` is live on TikTok (TikTokLive)."""
    uid = (unique_id or "").strip()
    if not uid:
        return None
    try:
        from TikTokLive import TikTokLiveClient
    except ImportError:
        return None
    if not uid.startswith("@"):
        uid = f"@{uid}"
    client = TikTokLiveClient(unique_id=uid)
    try:
        if not await client.is_live():
            return None
        room_id = int(await client._web.fetch_room_id_from_api(client.unique_id))
        title = "TikTok live"
        try:
            info = await client._web.fetch_room_info(room_id=room_id)
            if isinstance(info, dict):
                for k in ("title", "room_title", "stream_title", "live_title"):
                    raw = info.get(k)
                    if isinstance(raw, str) and raw.strip():
                        title = raw.strip()
                        break
        except Exception:
            pass
        handle = (client.unique_id or uid).lstrip("@")
        url = f"https://www.tiktok.com/@{handle}/live"
        return {
            "id": str(room_id),
            "title": title,
            "url": url,
            "platform": "tiktok",
        }
    except Exception as exc:
        print(f"(live social) TikTok probe failed: {exc}", flush=True)
        return None
    finally:
        try:
            await client.close()
        except Exception:
            pass


async def probe_twitch_live(bot: object, login: str) -> dict[str, str] | None:
    login = (login or "").strip().lower().lstrip("#")
    if not login:
        return None
    try:
        streams = await bot.fetch_streams(user_logins=[login])  # type: ignore[union-attr]
    except Exception as exc:
        print(f"(live social) Twitch stream check failed: {exc}", flush=True)
        return None
    if not streams:
        return None
    s = streams[0]
    sid = str(getattr(s, "id", "") or "").strip()
    title = (getattr(s, "title", None) or "Twitch live").strip()
    if not sid:
        return None
    return {
        "id": sid,
        "title": title,
        "url": f"https://www.twitch.tv/{login}",
        "platform": "twitch",
    }


def _live_post_title(platform: str, title: str) -> str:
    prefix = (os.environ.get("LUNA_SOCIAL_LIVE_TITLE_PREFIX") or "Live now:").strip()
    plat = platform.strip().lower()
    if prefix:
        return f"{prefix} [{plat}] {title}".strip()
    return title


def format_twitch_live_discord_message(title: str, url: str) -> str:
    tmpl = (
        os.environ.get("LUNA_TWITCH_LIVE_DISCORD_MESSAGE")
        or "🔴 **Live now on Twitch!**\n{title}\n\nJoin here: {url}"
    ).strip()
    return tmpl.replace("{title}", title).replace("{url}", url)


def _should_social_share(platform: str) -> bool:
    if platform == "twitch":
        return live_social_share_enabled() or twitch_live_social_enabled()
    if platform == "tiktok":
        return live_social_share_enabled()
    return live_social_share_enabled()


def _should_discord_announce(platform: str) -> bool:
    return platform == "twitch" and twitch_live_discord_enabled()


async def _announce_live(
    item: dict[str, str],
    *,
    state: dict[str, Any],
    social_share_send: SocialShareSend | None,
    discord_live_send: DiscordLiveSend | None,
    broadcast_status: BroadcastStatus | None,
) -> None:
    platform = item.get("platform") or "live"
    sid = item.get("id") or ""
    title = item.get("title") or "Live stream"
    url = item.get("url") or ""
    if not sid or not url:
        return

    announced: dict[str, list[str]] = state.setdefault("announced", {})
    if platform == "youtube":
        key = "youtube"
    elif platform == "tiktok":
        key = "tiktok"
    else:
        key = "twitch"
    ids: list[str] = list(announced.get(key) or [])
    if sid in ids:
        return

    post_title = _live_post_title(platform, title)
    line = f"Going live on {platform}: {title} — {url}"
    print(f"(live announce) {line}", flush=True)
    if broadcast_status:
        await broadcast_status(line)

    if _should_discord_announce(platform) and discord_live_send is not None:
        try:
            await discord_live_send(format_twitch_live_discord_message(title, url))
        except Exception as exc:
            print(f"(live announce) Discord failed: {exc}", flush=True)

    if _should_social_share(platform) and social_share_send is not None:
        try:
            await social_share_send(post_title, url)
        except Exception as exc:
            print(f"(live announce) social share failed: {exc}", flush=True)

    ids.append(sid)
    announced[key] = ids[-40:]
    state["announced"] = announced
    _save_state(state)


async def run_live_social_poller(
    *,
    social_share_send: SocialShareSend | None,
    discord_live_send: DiscordLiveSend | None = None,
    broadcast_status: BroadcastStatus | None,
    twitch_bot: object | None = None,
    twitch_login: str = "",
) -> None:
    """Poll YouTube / Twitch / TikTok; on new live session announce Discord + X/Facebook once per id."""
    if not live_watch_enabled():
        return

    interval = live_social_poll_sec()
    yt_targets = youtube_live_probe_targets() if live_social_share_enabled() else []
    tiktok_uid = (tiktok_live_username() or "").strip() if live_social_share_enabled() else ""
    twitch_login = (twitch_login or os.environ.get("TWITCH_CHANNEL") or "").strip().lower().lstrip("#")
    watch_twitch = bool(twitch_login) and (
        twitch_live_announce_enabled() or live_social_share_enabled()
    )

    if not yt_targets and not watch_twitch and not tiktok_uid:
        msg = (
            "Live announce: set TWITCH_CHANNEL, LUNA_TIKTOK_LIVE_USERNAME, "
            "and/or YouTube targets (LUNA_YOUTUBE_LIVE_CHECK_URL, LUNA_SOCIAL_LIVE_YOUTUBE_URLS, observe channels)."
        )
        print(f"(live announce) {msg}", flush=True)
        if broadcast_status:
            await broadcast_status(msg)
        return

    state = _load_state()
    parts = []
    if yt_targets:
        parts.append(f"{len(yt_targets)} YouTube target(s)")
    if tiktok_uid:
        parts.append(f"TikTok {tiktok_uid}")
    if watch_twitch:
        parts.append(f"Twitch #{twitch_login}")
    actions = []
    if twitch_live_discord_enabled():
        actions.append("Discord (all servers)")
    if live_social_share_enabled() or twitch_live_social_enabled():
        actions.append("X/Facebook")
    action_txt = " + ".join(actions) if actions else "status only"
    hello = (
        f"Live announce: watching {' + '.join(parts)} every {int(interval)}s ({action_txt})."
    )
    print(f"(live announce) {hello}", flush=True)
    if broadcast_status:
        await broadcast_status(hello)

    while True:
        try:
            for url in yt_targets:
                item = await asyncio.to_thread(_probe_youtube_live_sync, url)
                if item:
                    await _announce_live(
                        item,
                        state=state,
                        social_share_send=social_share_send,
                        discord_live_send=discord_live_send,
                        broadcast_status=broadcast_status,
                    )

            if twitch_bot is not None and watch_twitch:
                t_item = await probe_twitch_live(twitch_bot, twitch_login)
                if t_item:
                    await _announce_live(
                        t_item,
                        state=state,
                        social_share_send=social_share_send,
                        discord_live_send=discord_live_send,
                        broadcast_status=broadcast_status,
                    )

            if tiktok_uid:
                tt_item = await probe_tiktok_live(tiktok_uid)
                if tt_item:
                    await _announce_live(
                        tt_item,
                        state=state,
                        social_share_send=social_share_send,
                        discord_live_send=discord_live_send,
                        broadcast_status=broadcast_status,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"(live announce) poll error: {exc}", flush=True)

        await asyncio.sleep(interval)
