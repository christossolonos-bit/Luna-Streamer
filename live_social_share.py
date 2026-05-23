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

SocialShareSend = Callable[[str, str, str], Awaitable[None]]  # title, url, platform
BroadcastStatus = Callable[[str], Awaitable[None]]
DiscordLiveSend = Callable[[str, str, str], Awaitable[None]]  # message, platform, image_path
LiveSocialTitlePrompt = Callable[[dict[str, str]], Awaitable[None]]


def _env_truthy(key: str, *, default: bool = False) -> bool:
    raw = (os.environ.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def live_announce_master_enabled() -> bool:
    """Master switch: watch Twitch / YouTube / TikTok for go-live (``LUNA_LIVE_ANNOUNCE``)."""
    return _env_truthy("LUNA_LIVE_ANNOUNCE", default=False)


def live_social_share_enabled() -> bool:
    from social_playwright_share import social_playwright_configured

    if live_announce_master_enabled():
        return social_playwright_configured() and _env_truthy(
            "LUNA_LIVE_SOCIAL", default=True
        )
    return social_playwright_configured() and _env_truthy("LUNA_SOCIAL_LIVE_SHARE", default=False)


def twitch_live_announce_enabled() -> bool:
    return live_announce_master_enabled() or _env_truthy("LUNA_TWITCH_LIVE_ANNOUNCE", default=False)


def live_discord_enabled() -> bool:
    if not twitch_live_announce_enabled() and not live_social_share_enabled():
        return False
    if live_announce_master_enabled():
        return _env_truthy("LUNA_LIVE_DISCORD", default=True)
    if _env_truthy("LUNA_TWITCH_LIVE_ANNOUNCE", default=False):
        return _env_truthy("LUNA_TWITCH_LIVE_DISCORD", default=True)
    return _env_truthy("LUNA_SOCIAL_LIVE_DISCORD", default=True)


def twitch_live_discord_enabled() -> bool:
    return live_discord_enabled()


def twitch_live_social_enabled() -> bool:
    if not twitch_live_announce_enabled():
        return False
    if live_announce_master_enabled():
        return live_social_share_enabled()
    if not _env_truthy("LUNA_TWITCH_LIVE_SOCIAL", default=True):
        return False
    from social_playwright_share import social_playwright_configured

    return social_playwright_configured()


def live_watch_enabled() -> bool:
    return live_social_share_enabled() or twitch_live_announce_enabled()


def live_announce_image_path() -> Path | None:
    raw = (os.environ.get("LUNA_LIVE_ANNOUNCE_IMAGE") or "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser()
    if p.is_file():
        return p
    print(f"(live announce) image not found: {p}", flush=True)
    return None


def live_ask_social_title_enabled() -> bool:
    """If true, X/Facebook wait for streamer title in the viewer before posting."""
    return _env_truthy("LUNA_LIVE_ASK_SOCIAL_TITLE", default=True)


def _platform_state_key(platform: str) -> str:
    p = (platform or "").strip().lower()
    if p == "youtube":
        return "youtube"
    if p == "tiktok":
        return "tiktok"
    return "twitch"


def live_discord_channel_ids() -> list[int]:
    """Optional fixed channel list (comma-separated). Falls back to all guilds when empty."""
    raw = (
        os.environ.get("LUNA_LIVE_DISCORD_CHANNEL_IDS")
        or os.environ.get("LUNA_PUBLISH_ANNOUNCE_DISCORD_CHANNEL_IDS")
        or os.environ.get("DISCORD_LIVE_ANNOUNCE_CHANNEL_ID")
        or ""
    ).strip()
    if not raw:
        return []
    out: list[int] = []
    for part in re.split(r"[\s,]+", raw):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out


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


def _platform_display(platform: str) -> str:
    p = (platform or "").strip().lower()
    return {"twitch": "Twitch", "youtube": "YouTube", "tiktok": "TikTok"}.get(p, p.title() or "Live")


def format_live_discord_message(platform: str, title: str, url: str) -> str:
    plat = _platform_display(platform)
    tmpl = (
        os.environ.get("LUNA_LIVE_DISCORD_MESSAGE")
        or os.environ.get("LUNA_TWITCH_LIVE_DISCORD_MESSAGE")
        or "🔴 **We're live on {platform}!**\n{title}\n\nCome hang out — Luna & Viktor are on stage 💫\n{url}"
    ).strip()
    return (
        tmpl.replace("{platform}", plat)
        .replace("{title}", title)
        .replace("{url}", url)
    )


def format_twitch_live_discord_message(title: str, url: str) -> str:
    return format_live_discord_message("twitch", title, url)


def _should_social_share(platform: str) -> bool:
    if platform == "twitch":
        return live_social_share_enabled() or twitch_live_social_enabled()
    return live_social_share_enabled()


def _should_discord_announce(platform: str) -> bool:
    return live_discord_enabled()


def _announced_ids(state: dict[str, Any], bucket: str, platform: str) -> list[str]:
    root = state.setdefault(bucket, {})
    if not isinstance(root, dict):
        root = {}
        state[bucket] = root
    return list(root.get(_platform_state_key(platform)) or [])


def _mark_announced(state: dict[str, Any], bucket: str, platform: str, sid: str) -> None:
    root = state.setdefault(bucket, {})
    if not isinstance(root, dict):
        root = {}
        state[bucket] = root
    key = _platform_state_key(platform)
    ids: list[str] = list(root.get(key) or [])
    if sid not in ids:
        ids.append(sid)
    root[key] = ids[-40:]
    state[bucket] = root


def _legacy_announced_ids(state: dict[str, Any], platform: str) -> list[str]:
    announced = state.setdefault("announced", {})
    if not isinstance(announced, dict):
        announced = {}
        state["announced"] = announced
    return list(announced.get(_platform_state_key(platform)) or [])


def _mark_legacy_announced(state: dict[str, Any], platform: str, sid: str) -> None:
    sid = (sid or "").strip()
    if not sid:
        return
    announced = state.setdefault("announced", {})
    if not isinstance(announced, dict):
        announced = {}
        state["announced"] = announced
    key = _platform_state_key(platform)
    ids: list[str] = list(announced.get(key) or [])
    if sid not in ids:
        ids.append(sid)
    announced[key] = ids[-40:]
    state["announced"] = announced


def _live_session_handled(state: dict[str, Any], platform: str, sid: str) -> bool:
    """True when this stream id was already logged or announced (any channel)."""
    sid = (sid or "").strip()
    if not sid:
        return True
    key = _platform_state_key(platform)
    if sid in _legacy_announced_ids(state, key):
        return True
    if sid in _announced_ids(state, "announced_discord", key):
        return True
    if sid in _announced_ids(state, "announced_social", key):
        return True
    pending = state.get("pending_social")
    if isinstance(pending, dict):
        entry = pending.get(key)
        if isinstance(entry, dict) and str(entry.get("id") or "") == sid:
            return True
    return False


def skip_live_social_share(
    *,
    platform: str,
    stream_id: str,
    state: dict[str, Any] | None = None,
) -> None:
    """Mark social go-live as handled without posting (streamer dismissed the title prompt)."""
    sid = (stream_id or "").strip()
    plat = _platform_state_key(platform)
    if not sid:
        return
    st = state if state is not None else _load_state()
    _mark_announced(st, "announced_social", plat, sid)
    pending = st.get("pending_social")
    if isinstance(pending, dict):
        pending.pop(plat, None)
        st["pending_social"] = pending
    _save_state(st)


async def complete_live_social_share(
    *,
    platform: str,
    stream_id: str,
    title: str,
    url: str,
    state: dict[str, Any] | None = None,
    social_share_send: SocialShareSend | None,
    broadcast_status: BroadcastStatus | None,
) -> bool:
    """Post X/Facebook after the streamer confirms the stream title in the viewer."""
    sid = (stream_id or "").strip()
    url = (url or "").strip()
    title = (title or "").strip() or "Live stream"
    plat = _platform_state_key(platform)
    if not sid or not url or social_share_send is None:
        return False
    st = state if state is not None else _load_state()
    if sid in _announced_ids(st, "announced_social", plat):
        return True
    line = f"Social share ({plat}): {title} — {url}"
    print(f"(live announce) {line}", flush=True)
    if broadcast_status:
        await broadcast_status(f"Posting to X & Facebook: {title}")
    try:
        await social_share_send(title, url, plat)
    except Exception as exc:
        print(f"(live announce) social share failed: {exc}", flush=True)
        return False
    _mark_announced(st, "announced_social", plat, sid)
    pending = st.get("pending_social")
    if isinstance(pending, dict):
        pending.pop(plat, None)
        st["pending_social"] = pending
    _save_state(st)
    return True


async def _announce_live(
    item: dict[str, str],
    *,
    state: dict[str, Any],
    social_share_send: SocialShareSend | None,
    discord_live_send: DiscordLiveSend | None,
    broadcast_status: BroadcastStatus | None,
    request_social_title_prompt: LiveSocialTitlePrompt | None = None,
) -> None:
    platform = item.get("platform") or "live"
    sid = item.get("id") or ""
    title = item.get("title") or "Live stream"
    url = item.get("url") or ""
    if not sid or not url:
        return

    key = _platform_state_key(platform)
    if _live_session_handled(state, platform, sid):
        return

    _mark_legacy_announced(state, platform, sid)
    _save_state(state)

    post_title = _live_post_title(platform, title)
    line = f"Going live on {platform}: {title} — {url}"
    print(f"(live announce) {line}", flush=True)
    if broadcast_status:
        await broadcast_status(line)

    img = live_announce_image_path()
    img_str = str(img) if img else ""

    if _should_discord_announce(platform) and discord_live_send is not None:
        if sid not in _announced_ids(state, "announced_discord", key):
            try:
                await discord_live_send(
                    format_live_discord_message(platform, title, url),
                    platform,
                    img_str,
                )
            except Exception as exc:
                print(f"(live announce) Discord failed: {exc}", flush=True)
            _mark_announced(state, "announced_discord", key, sid)

    want_social = _should_social_share(platform) and social_share_send is not None
    if want_social and sid not in _announced_ids(state, "announced_social", key):
        if live_ask_social_title_enabled() and request_social_title_prompt is not None:
            pending = state.setdefault("pending_social", {})
            if not isinstance(pending, dict):
                pending = {}
                state["pending_social"] = pending
            pending[key] = {
                "id": sid,
                "url": url,
                "suggested_title": title,
                "platform": platform,
            }
            _save_state(state)
            try:
                await request_social_title_prompt(
                    {
                        "platform": platform,
                        "stream_id": sid,
                        "url": url,
                        "suggested_title": title,
                    }
                )
            except Exception as exc:
                print(f"(live announce) title prompt failed: {exc}", flush=True)
            if broadcast_status:
                await broadcast_status(
                    f"Go-live on {platform}: enter stream title in the viewer for X & Facebook."
                )
        else:
            try:
                await social_share_send(post_title, url, platform)
            except Exception as exc:
                print(f"(live announce) social share failed: {exc}", flush=True)
            _mark_announced(state, "announced_social", key, sid)

    _mark_legacy_announced(state, platform, sid)
    _save_state(state)


async def run_live_social_poller(
    *,
    social_share_send: SocialShareSend | None,
    discord_live_send: DiscordLiveSend | None = None,
    broadcast_status: BroadcastStatus | None,
    request_social_title_prompt: LiveSocialTitlePrompt | None = None,
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
    if live_discord_enabled():
        ch_ids = live_discord_channel_ids()
        actions.append(
            f"Discord ({len(ch_ids)} channel(s))" if ch_ids else "Discord (all servers)"
        )
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
                        request_social_title_prompt=request_social_title_prompt,
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
                        request_social_title_prompt=request_social_title_prompt,
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
                        request_social_title_prompt=request_social_title_prompt,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"(live announce) poll error: {exc}", flush=True)

        await asyncio.sleep(interval)
