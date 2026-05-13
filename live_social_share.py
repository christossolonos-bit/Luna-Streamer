"""Detect YouTube / Twitch go-live and post to X + Facebook (same Playwright flow as uploads)."""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from youtube_audio import extract_video_id
from youtube_feed import (
    _is_youtube_observe_tab_url,
    channel_id as yt_legacy_channel_id,
    observe_channel_entries,
    resolve_channel_id,
)
from youtube_live_chat import youtube_live_video_id

SocialShareSend = Callable[[str, str], Awaitable[None]]
BroadcastStatus = Callable[[str], Awaitable[None]]


def _env_truthy(key: str, *, default: bool = False) -> bool:
    raw = (os.environ.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def live_social_share_enabled() -> bool:
    from social_playwright_share import social_playwright_configured

    return social_playwright_configured() and _env_truthy("LUNA_SOCIAL_LIVE_SHARE", default=False)


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


def _probe_youtube_live_sync(url: str) -> dict[str, str] | None:
    try:
        import yt_dlp
    except ImportError:
        return None
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
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


async def probe_twitch_live(bot: object, login: str) -> dict[str, str] | None:
    login = (login or "").strip().lower().lstrip("#")
    if not login:
        return None
    try:
        streams = await bot.fetch_streams(user_login=[login])  # type: ignore[union-attr]
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


async def _announce_live(
    item: dict[str, str],
    *,
    state: dict[str, Any],
    social_share_send: SocialShareSend | None,
    broadcast_status: BroadcastStatus | None,
) -> None:
    platform = item.get("platform") or "live"
    sid = item.get("id") or ""
    title = item.get("title") or "Live stream"
    url = item.get("url") or ""
    if not sid or not url:
        return

    announced: dict[str, list[str]] = state.setdefault("announced", {})
    key = "youtube" if platform == "youtube" else "twitch"
    ids: list[str] = list(announced.get(key) or [])
    if sid in ids:
        return

    post_title = _live_post_title(platform, title)
    line = f"Going live on {platform}: {title} — {url}"
    print(f"(live social) {line}", flush=True)
    if broadcast_status:
        await broadcast_status(line)
    if social_share_send is not None:
        await social_share_send(post_title, url)

    ids.append(sid)
    announced[key] = ids[-40:]
    state["announced"] = announced
    _save_state(state)


async def run_live_social_poller(
    *,
    social_share_send: SocialShareSend | None,
    broadcast_status: BroadcastStatus | None,
    twitch_bot: object | None = None,
    twitch_login: str = "",
) -> None:
    """Poll YouTube / Twitch; on new live session, trigger X + Facebook share once per broadcast id."""
    if not live_social_share_enabled():
        return

    interval = live_social_poll_sec()
    yt_targets = youtube_live_probe_targets()
    twitch_login = (twitch_login or os.environ.get("TWITCH_CHANNEL") or "").strip().lower().lstrip("#")

    if not yt_targets and not twitch_login:
        msg = "Live social: set LUNA_YOUTUBE_OBSERVE_CHANNELS, LUNA_YOUTUBE_LIVE_URL, or TWITCH_CHANNEL."
        print(f"(live social) {msg}", flush=True)
        if broadcast_status:
            await broadcast_status(msg)
        return

    state = _load_state()
    parts = []
    if yt_targets:
        parts.append(f"{len(yt_targets)} YouTube target(s)")
    if twitch_login:
        parts.append(f"Twitch #{twitch_login}")
    hello = f"Live social: watching {' + '.join(parts)} every {int(interval)}s (X/Facebook when live)."
    print(f"(live social) {hello}", flush=True)
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
                        broadcast_status=broadcast_status,
                    )

            if twitch_bot is not None and twitch_login:
                t_item = await probe_twitch_live(twitch_bot, twitch_login)
                if t_item:
                    await _announce_live(
                        t_item,
                        state=state,
                        social_share_send=social_share_send,
                        broadcast_status=broadcast_status,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"(live social) poll error: {exc}", flush=True)

        await asyncio.sleep(interval)
