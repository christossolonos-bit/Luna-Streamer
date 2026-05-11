"""Background poller for a YouTube channel RSS feed.

When the channel publishes a new video, broadcast a status line to the
chat WS hub so the streamer panel / viewer can react on stream.

Env:
  LUNA_YOUTUBE_CHANNEL_ID   YouTube channel id (UC...). Required to enable.
  LUNA_YOUTUBE_POLL_SEC     Poll interval in seconds (default 300, min 60).
  LUNA_YOUTUBE_STATE_PATH   Path to JSON state file (default <project>/data/youtube_feed_state.json).
  LUNA_YOUTUBE_ANNOUNCE_TWITCH  If 1 and bot.send_replies, also post in Twitch chat (default 0).
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Awaitable, Callable

FEED_URL_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}


def channel_id() -> str:
    return (os.environ.get("LUNA_YOUTUBE_CHANNEL_ID") or "").strip()


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
    with ``etag`` / ``last_modified`` and used for conditional GETs — returns
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


def _env_truthy(key: str, *, default: bool = False) -> bool:
    raw = (os.environ.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")
