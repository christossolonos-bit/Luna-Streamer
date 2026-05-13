"""Background poller for a YouTube channel RSS feed.

When the channel publishes a new video, broadcast a status line to the
chat WS hub so the streamer panel / viewer can react on stream.

Env:
  LUNA_YOUTUBE_CHANNEL_ID   YouTube channel id (UC…). Enables the legacy single-feed poller if set.
  LUNA_YOUTUBE_POLL_SEC     Poll interval in seconds (default 300, min 60).
  LUNA_YOUTUBE_STATE_PATH   Path to JSON state file (default <project>/data/youtube_feed_state.json).
  LUNA_YOUTUBE_ANNOUNCE_TWITCH  If 1 and bot.send_replies, also post in Twitch chat (default 0).

Multi-channel observer (takes precedence over LUNA_YOUTUBE_CHANNEL_ID when non-empty):
  LUNA_YOUTUBE_OBSERVE_CHANNELS   Comma or whitespace separated @handles, channel URLs, UC… ids,
                                  or a full channel ``/videos?...`` tab URL (uses yt-dlp for that
                                  shelf/sort order, e.g. ``.../@Handle/videos?view=0&sort=dd&shelf_id=4``).
  LUNA_YOUTUBE_ANNOUNCE_DISCORD_CHANNEL_ID  Discord text channel id for upload announcements.
  LUNA_YOUTUBE_OBSERVE_TODAY_ONLY  If 1 (default), only announce videos published today (host local time).

The viewer can trigger ``manual_check_today_uploads()`` via WebSocket (see ``viewer_youtube_observe_check`` in twitch_bot).

Optional Playwright sharing (see ``social_playwright_share.py``): ``run_observe_feed_poller(..., social_share_send=...)``.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import hashlib
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

FEED_URL_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}


def _env_truthy(key: str, *, default: bool = False) -> bool:
    raw = (os.environ.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def channel_id() -> str:
    return (os.environ.get("LUNA_YOUTUBE_CHANNEL_ID") or "").strip()


def observe_channel_entries() -> list[str]:
    """Raw entries from LUNA_YOUTUBE_OBSERVE_CHANNELS (comma or newline separated)."""
    raw = (os.environ.get("LUNA_YOUTUBE_OBSERVE_CHANNELS") or "").strip()
    if not raw:
        return []
    return [p.strip() for p in re.split(r"[\s,]+", raw) if p.strip()]


def observe_feed_enabled() -> bool:
    return bool(observe_channel_entries())


def observe_today_only() -> bool:
    return _env_truthy("LUNA_YOUTUBE_OBSERVE_TODAY_ONLY", default=True)


def announce_discord_channel_id() -> int | None:
    raw = (os.environ.get("LUNA_YOUTUBE_ANNOUNCE_DISCORD_CHANNEL_ID") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _published_is_local_today(published: str) -> bool:
    if not published:
        return False
    try:
        s = published.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            from datetime import timezone

            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone()
        return local.date() == datetime.now().astimezone().date()
    except ValueError:
        return False


def _scrape_channel_id_from_page(url: str) -> str | None:
    base = url.split("?", 1)[0].strip()
    if not base.startswith("http"):
        base = f"https://www.youtube.com/{base.lstrip('/')}"
    req = urllib.request.Request(
        base,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=22) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except (OSError, urllib.error.URLError, ValueError):
        return None
    for pat in (
        r'"channelId":"(UC[A-Za-z0-9_-]{22})"',
        r'"browseId":"(UC[A-Za-z0-9_-]{22})"',
        r'"externalId":"(UC[A-Za-z0-9_-]{22})"',
        r"channel_id=(UC[A-Za-z0-9_-]{22})",
    ):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


def resolve_channel_id(raw: str) -> str | None:
    """Resolve @handle URL, channel URL, or bare UC... id to a channel id for RSS."""
    s = (raw or "").strip()
    if not s:
        return None
    if re.fullmatch(r"UC[A-Za-z0-9_-]{22}", s):
        return s
    for pat in (r"/channel/(UC[A-Za-z0-9_-]{22})", r"channel_id=(UC[A-Za-z0-9_-]{22})"):
        m = re.search(pat, s, re.I)
        if m:
            return m.group(1)
    url = s if s.startswith("http") else f"https://www.youtube.com/{s.lstrip('/')}"
    cid = _scrape_channel_id_from_page(url)
    if cid:
        return cid
    try:
        import yt_dlp
    except ImportError:
        return None
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
        "extract_flat": True,
        "playlistend": 1,
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return None
    if not isinstance(info, dict):
        return None
    ch = (info.get("channel_id") or "").strip()
    if ch and re.fullmatch(r"UC[A-Za-z0-9_-]{22}", ch):
        return ch
    rid = str(info.get("id") or "").strip()
    if re.fullmatch(r"UC[A-Za-z0-9_-]{22}", rid):
        return rid
    return None


def _is_youtube_observe_tab_url(s: str) -> bool:
    """True for channel ``/videos`` tab URLs (optional ``?sort=`` / ``shelf_id=``)."""
    raw = (s or "").strip()
    if not raw:
        return False
    u = raw if raw.startswith("http") else f"https://www.youtube.com/{raw.lstrip('/')}"
    try:
        p = urlparse(u.lower())
    except ValueError:
        return False
    host = (p.netloc or "").split(":")[0]
    if host not in ("www.youtube.com", "youtube.com", "m.youtube.com"):
        return False
    path = (p.path or "").lower()
    return "/videos" in path


def _tab_cache_key(raw: str) -> str:
    """Stable state key for a tab URL (separate from UC RSS cache)."""
    h = hashlib.sha256(raw.strip().encode("utf-8")).hexdigest()[:20]
    return f"yt_tab_{h}"


def _ytdlp_entry_published_iso(e: dict[str, Any]) -> str:
    """Best-effort ISO 8601 UTC from a yt-dlp entry dict."""
    ts = e.get("release_timestamp")
    if ts is None:
        ts = e.get("timestamp")
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
        except (OSError, ValueError, OverflowError):
            pass
    ud = e.get("upload_date")
    if isinstance(ud, str) and len(ud) == 8 and ud.isdigit():
        try:
            y, mo, d = int(ud[:4]), int(ud[4:6]), int(ud[6:8])
            return datetime(y, mo, d, 12, 0, 0, tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    return ""


def _fetch_youtube_tab_entries(url: str, *, limit: int = 30) -> list[dict[str, str]]:
    """Videos in tab/shelf order (matches browser ``/videos?...``)."""
    try:
        import yt_dlp
    except ImportError:
        return []
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
        "extract_flat": True,
        "playlistend": max(1, min(limit, 50)),
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url.strip(), download=False)
    except Exception:
        return []
    if not isinstance(info, dict):
        return []
    entries = info.get("entries") or []
    out: list[dict[str, str]] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        vid = str(e.get("id") or "").strip()
        if not re.fullmatch(r"[0-9A-Za-z_-]{11}", vid):
            continue
        title = str(e.get("title") or "").strip() or "?"
        link = str(e.get("url") or "").strip()
        if not link.startswith("http"):
            link = f"https://www.youtube.com/watch?v={vid}"
        pub = _ytdlp_entry_published_iso(e)
        out.append({"id": vid, "title": title, "url": link, "published": pub})
    return out


def _enrich_published_from_rss(entries: list[dict[str, str]], channel_id: str) -> None:
    """Fill missing ``published`` from channel RSS (in place)."""
    try:
        rss = _fetch_latest_entries(channel_id, limit=50, cache=None)
    except Exception:
        return
    if not rss:
        return
    by_id = {e["id"]: (e.get("published") or "").strip() for e in rss if e.get("id")}
    for e in entries:
        if (e.get("published") or "").strip():
            continue
        pid = e.get("id") or ""
        if pid in by_id and by_id[pid]:
            e["published"] = by_id[pid]


def _fetch_observe_rows_tab(tab_url: str, limit: int = 30) -> list[dict[str, str]]:
    rows = _fetch_youtube_tab_entries(tab_url, limit=limit)
    cid = resolve_channel_id(tab_url)
    if cid and rows:
        _enrich_published_from_rss(rows, cid)
    return rows


def poll_interval_sec() -> float:
    raw = (os.environ.get("LUNA_YOUTUBE_POLL_SEC") or "300").strip() or "300"
    try:
        return max(60.0, float(raw))
    except ValueError:
        return 300.0


def state_path() -> Path:
    raw = (os.environ.get("LUNA_YOUTUBE_STATE_PATH") or "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parent / "data" / "youtube_feed_state.json"


def _load_state() -> dict[str, Any]:
    p = state_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict[str, Any]) -> None:
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _fetch_latest_entries(
    cid: str,
    *,
    limit: int = 5,
    cache: dict[str, str] | None = None,
) -> list[dict[str, str]] | None:
    """Fetch the channel RSS feed. ``cache`` (if provided) is a dict updated
    with ``etag`` / ``last_modified`` and used for conditional GETs - returns
    ``None`` when YouTube responds 304 Not Modified so the caller can skip parsing.
    """
    url = FEED_URL_TEMPLATE.format(channel_id=cid)
    headers = {"User-Agent": "Mozilla/5.0 (LunaStreamer)"}
    if cache is not None:
        etag = cache.get("etag")
        last_mod = cache.get("last_modified")
        if etag:
            headers["If-None-Match"] = etag
        if last_mod:
            headers["If-Modified-Since"] = last_mod
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if cache is not None:
                new_etag = resp.headers.get("ETag")
                new_lm = resp.headers.get("Last-Modified")
                if new_etag:
                    cache["etag"] = new_etag
                if new_lm:
                    cache["last_modified"] = new_lm
            xml_text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return None
        raise

    root = ET.fromstring(xml_text)
    out: list[dict[str, str]] = []
    for entry in root.findall("atom:entry", _NS)[:limit]:
        title = (entry.findtext("atom:title", default="", namespaces=_NS) or "").strip()
        vid = (entry.findtext("yt:videoId", default="", namespaces=_NS) or "").strip()
        published = (entry.findtext("atom:published", default="", namespaces=_NS) or "").strip()
        link = ""
        link_el = entry.find("atom:link[@rel='alternate']", _NS)
        if link_el is not None:
            link = (link_el.attrib.get("href") or "").strip()
        if not link and vid:
            link = f"https://www.youtube.com/watch?v={vid}"
        if vid and title:
            out.append({"id": vid, "title": title, "url": link, "published": published})
    return out


async def run_feed_poller(
    *,
    broadcast_status: Callable[[str], Awaitable[None]],
    twitch_send: Callable[[str], Awaitable[None]] | None = None,
) -> None:
    """Loop forever (or until cancelled). broadcast_status(text) and twitch_send(text) are async."""
    cid = channel_id()
    if not cid:
        return
    interval = poll_interval_sec()
    state = _load_state()
    seen: set[str] = set(state.get("seen_ids", []))
    http_cache: dict[str, str] = {
        k: v for k, v in (("etag", state.get("etag", "")), ("last_modified", state.get("last_modified", ""))) if v
    }

    if not seen:
        # First run: seed with whatever exists so we don't spam old uploads.
        try:
            entries = await asyncio.to_thread(_fetch_latest_entries, cid, cache=http_cache)
            for e in (entries or []):
                seen.add(e["id"])
            _save_state({"seen_ids": list(seen), **http_cache})
            await broadcast_status(
                f"YouTube feed: watching channel {cid} every {int(interval)}s."
            )
        except Exception as exc:
            await broadcast_status(f"YouTube feed: initial fetch failed ({exc}).")

    while True:
        try:
            entries = await asyncio.to_thread(_fetch_latest_entries, cid, cache=http_cache)
        except Exception as exc:
            await broadcast_status(f"YouTube feed: fetch failed ({exc}).")
            await asyncio.sleep(interval)
            continue

        if entries is None:  # 304 Not Modified — nothing to do.
            await asyncio.sleep(interval)
            continue

        new_items = [e for e in entries if e["id"] not in seen]
        # entries arrive newest-first; announce in chronological order so the latest is last
        for item in reversed(new_items):
            seen.add(item["id"])
            text = f"New YouTube upload: {item['title']} — {item['url']}"
            await broadcast_status(text)
            if twitch_send is not None and _env_truthy("LUNA_YOUTUBE_ANNOUNCE_TWITCH"):
                try:
                    await twitch_send(text)
                except Exception:
                    pass

        if new_items:
            _save_state({"seen_ids": list(seen)[-50:], **http_cache})
        elif http_cache:
            # Refresh cached ETag/Last-Modified even when nothing new.
            _save_state({"seen_ids": list(seen)[-50:], **http_cache})

        await asyncio.sleep(interval)


async def manual_check_today_uploads() -> list[str]:
    """Poll each observe channel's RSS and list videos whose published date is today (host local time).

    Tab URLs (``/videos?...``) use yt-dlp in shelf order; dates are merged from RSS when missing.

    Read-only: does not update ``observe_seen_ids`` or HTTP caches used by the background poller.
    """
    raw_entries = observe_channel_entries()
    if not raw_entries:
        return [
            "YouTube observe: set LUNA_YOUTUBE_OBSERVE_CHANNELS to enable manual checks.",
        ]
    pending: list[tuple[str, str, str]] = []  # label, "tab"|"rss", url_or_cid
    for raw in raw_entries:
        label = raw if len(raw) <= 56 else raw[:53] + "..."
        if _is_youtube_observe_tab_url(raw):
            pending.append((label, "tab", raw.strip()))
        else:
            cid = await asyncio.to_thread(resolve_channel_id, raw)
            pending.append((label, "rss", cid or ""))
    n_ok = sum(1 for _lb, kind, key in pending if kind == "tab" or key)
    out: list[str] = [
        f"YouTube (check now): {n_ok}/{len(raw_entries)} channel(s) resolved — "
        "today's uploads (local time):",
    ]
    for label, kind, key in pending:
        if kind == "rss" and not key:
            out.append(f"• {label}: could not resolve channel id.")
            continue
        try:
            if kind == "tab":
                rows = await asyncio.to_thread(_fetch_observe_rows_tab, key, 30)
            else:
                got = await asyncio.to_thread(
                    _fetch_latest_entries,
                    key,
                    limit=30,
                    cache=None,
                )
                rows = list(got or [])
        except Exception as exc:
            out.append(f"• {label}: fetch error ({exc}).")
            continue
        today_e = [e for e in rows if _published_is_local_today(e.get("published", ""))]
        if not today_e:
            src = "tab shelf" if kind == "tab" else "latest feed"
            out.append(f"• {label}: none published today (in {src}).")
            continue
        today_e.sort(key=lambda x: x.get("published", ""))
        for e in today_e:
            title = (e.get("title") or "?").strip()
            if len(title) > 160:
                title = title[:157] + "…"
            url = (e.get("url") or "").strip()
            out.append(f"• {label}: {title} — {url}")
    return out


def _merge_save_observe_state(
    seen: set[str], per_channel_caches: dict[str, dict[str, str]]
) -> None:
    full = _load_state()
    full["observe_seen_ids"] = list(seen)[-800:]
    full["observe_http_cache"] = {k: dict(v) for k, v in per_channel_caches.items()}
    _save_state(full)


async def run_observe_feed_poller(
    *,
    broadcast_status: Callable[[str], Awaitable[None]],
    twitch_send: Callable[[str], Awaitable[None]] | None = None,
    discord_send: Callable[[str], Awaitable[None]] | None = None,
    social_share_send: Callable[[str, str], Awaitable[None]] | None = None,
) -> None:
    """Watch multiple channels; optionally only announce uploads published *today* (local time)."""
    raw_entries = observe_channel_entries()
    if not raw_entries:
        return
    interval = poll_interval_sec()
    today_only = observe_today_only()

    # (label, rss_cache_key, tab_url_or_none) — rss_cache_key is UC… for RSS, or yt_tab_… for tab URLs.
    sources: list[tuple[str, str, str | None]] = []
    for raw in raw_entries:
        label = raw if len(raw) <= 56 else raw[:53] + "..."
        if _is_youtube_observe_tab_url(raw):
            sources.append((label, _tab_cache_key(raw), raw.strip()))
        else:
            cid = await asyncio.to_thread(resolve_channel_id, raw)
            if cid:
                sources.append((label, cid, None))
            else:
                await broadcast_status(f"YouTube observe: could not resolve {raw!r} — skipped.")

    if not sources:
        await broadcast_status("YouTube observe: no valid channels after resolution.")
        return

    state = _load_state()
    seen: set[str] = set(state.get("observe_seen_ids", []))
    raw_cache = state.get("observe_http_cache") or {}
    per_cache: dict[str, dict[str, str]] = {}
    if isinstance(raw_cache, dict):
        for k, v in raw_cache.items():
            if isinstance(v, dict):
                per_cache[str(k)] = {
                    str(k2): str(v2)
                    for k2, v2 in v.items()
                    if isinstance(k2, str) and isinstance(v2, str)
                }

    if not seen:
        for _label, cache_key, tab in sources:
            try:
                if tab is not None:
                    entries = await asyncio.to_thread(_fetch_observe_rows_tab, tab, 15)
                else:
                    entries = await asyncio.to_thread(
                        _fetch_latest_entries,
                        cache_key,
                        limit=15,
                        cache=per_cache.setdefault(cache_key, {}),
                    )
                for e in entries or []:
                    seen.add(e["id"])
            except Exception as exc:
                await broadcast_status(f"YouTube observe: initial seed failed for {cache_key} ({exc}).")
        _merge_save_observe_state(seen, per_cache)
        mode = "today's uploads only" if today_only else "all new RSS entries"
        await broadcast_status(
            f"YouTube observe: watching {len(sources)} channel(s) every {int(interval)}s ({mode})."
        )

    while True:
        try:
            discovered: dict[str, dict[str, str]] = {}
            for _label, cache_key, tab in sources:
                if tab is not None:
                    entries = await asyncio.to_thread(_fetch_observe_rows_tab, tab, 15)
                else:
                    entries = await asyncio.to_thread(
                        _fetch_latest_entries,
                        cache_key,
                        limit=15,
                        cache=per_cache.setdefault(cache_key, {}),
                    )
                if not entries:
                    continue
                for e in entries:
                    vid = e.get("id") or ""
                    if vid and vid not in seen and vid not in discovered:
                        discovered[vid] = e
            new_list = sorted(discovered.values(), key=lambda x: x.get("published", ""))
            for item in new_list:
                seen.add(item["id"])
                if today_only and not _published_is_local_today(item.get("published", "")):
                    continue
                title = item.get("title", "")
                url = item.get("url", "")
                if today_only:
                    text = f"New YouTube upload today: {title} — {url}"
                else:
                    text = f"New YouTube upload: {title} — {url}"
                await broadcast_status(text)
                if twitch_send is not None and _env_truthy("LUNA_YOUTUBE_ANNOUNCE_TWITCH"):
                    try:
                        await twitch_send(text)
                    except Exception:
                        pass
                if discord_send is not None:
                    try:
                        await discord_send(text)
                    except Exception:
                        pass
                if social_share_send is not None:
                    t = (title or "").strip()
                    u = (url or "").strip()
                    if t and u:

                        def _log_social_task(task: asyncio.Task) -> None:
                            try:
                                exc = task.exception()
                                if exc:
                                    print(f"(social playwright) background: {exc}", flush=True)
                            except asyncio.CancelledError:
                                pass

                        try:
                            _tsk = asyncio.create_task(social_share_send(t, u))
                            _tsk.add_done_callback(_log_social_task)
                        except Exception:
                            pass
            if new_list:
                _merge_save_observe_state(seen, per_cache)
            elif any(
                per_cache.get(cache_key) for _label, cache_key, tab in sources if tab is None
            ):
                _merge_save_observe_state(seen, per_cache)
        except Exception as exc:
            await broadcast_status(f"YouTube observe: poll failed ({exc}).")
        await asyncio.sleep(interval)
