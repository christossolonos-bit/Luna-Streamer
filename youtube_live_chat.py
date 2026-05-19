"""YouTube Live chat reader for Luna (pytchat). Incoming chat only — replies stay in the viewer."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Awaitable, Callable

from youtube_audio import extract_video_id

OnChat = Callable[[str, str, int], Awaitable[None]]
BroadcastStatus = Callable[[str], Awaitable[None]]
OnStopped = Callable[[], Awaitable[None]]


def _env_truthy(key: str, *, default: bool = False) -> bool:
    raw = (os.environ.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def youtube_live_video_id() -> str:
    """Video id from ``LUNA_YOUTUBE_LIVE_VIDEO_ID`` or ``LUNA_YOUTUBE_LIVE_URL``."""
    raw_id = (os.environ.get("LUNA_YOUTUBE_LIVE_VIDEO_ID") or "").strip()
    if raw_id and "/" not in raw_id and "?" not in raw_id and len(raw_id) >= 11:
        return raw_id[:11]
    for raw in (
        (os.environ.get("LUNA_YOUTUBE_LIVE_URL") or "").strip(),
        raw_id,
    ):
        if not raw:
            continue
        vid = extract_video_id(raw)
        if vid:
            return vid
    return ""


def youtube_live_chat_requested() -> bool:
    """Master switch for YouTube Live chat (URL may be supplied later from the viewer)."""
    return _env_truthy("LUNA_YOUTUBE_LIVE_CHAT", default=False)


def youtube_live_chat_enabled() -> bool:
    return youtube_live_chat_requested() and bool(youtube_live_video_id())


def set_youtube_live_url(url: str) -> str:
    """Persist the live watch URL in-process and return the extracted video id."""
    raw = (url or "").strip()
    if not raw:
        return ""
    vid = extract_video_id(raw)
    if not vid:
        return ""
    os.environ["LUNA_YOUTUBE_LIVE_URL"] = raw
    os.environ["LUNA_YOUTUBE_LIVE_VIDEO_ID"] = vid
    return vid


def youtube_live_auto_reply_enabled() -> bool:
    return _env_truthy("LUNA_YOUTUBE_LIVE_AUTO_REPLY", default=True)


def youtube_live_auto_trigger() -> str:
    raw = (os.environ.get("LUNA_YOUTUBE_LIVE_AUTO_TRIGGER") or "all").strip().lower()
    return raw if raw in {"mention", "all"} else "all"


def youtube_live_check_probe_url() -> str:
    """Single channel /live page to probe when the viewer taps “check YouTube live”."""
    raw = (os.environ.get("LUNA_YOUTUBE_LIVE_CHECK_URL") or "").strip()
    if raw:
        return raw
    return "https://www.youtube.com/@Solonaras1/live"


def youtube_live_watch_poll_enabled() -> bool:
    """Background /live probe (same as the viewer button) on an interval."""
    if not youtube_live_chat_requested():
        return False
    return _env_truthy("LUNA_YOUTUBE_LIVE_WATCH_POLL", default=True)


def youtube_live_watch_poll_sec() -> float:
    raw = (os.environ.get("LUNA_YOUTUBE_LIVE_WATCH_POLL_SEC") or "900").strip() or "900"
    try:
        sec = float(raw)
    except ValueError:
        sec = 900.0
    return max(60.0, min(sec, 86_400.0))


def youtube_live_reconnect_enabled() -> bool:
    return _env_truthy("LUNA_YOUTUBE_LIVE_RECONNECT", default=True)


def youtube_live_reconnect_delay_sec() -> float:
    raw = (os.environ.get("LUNA_YOUTUBE_LIVE_RECONNECT_DELAY_SEC") or "5").strip() or "5"
    try:
        sec = float(raw)
    except ValueError:
        sec = 5.0
    return max(2.0, min(sec, 120.0))


class YouTubeLiveChatRunner:
    """Start/stop the pytchat listener for a single live video id."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._video_id = ""

    @property
    def active_video_id(self) -> str:
        return self._video_id

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def stop(self) -> None:
        task = self._task
        self._task = None
        self._video_id = ""
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def start(
        self,
        *,
        video_id: str,
        on_chat: OnChat,
        broadcast_status: BroadcastStatus | None = None,
        on_stopped: OnStopped | None = None,
    ) -> asyncio.Task[None] | None:
        vid = (video_id or "").strip()
        if not vid:
            return None
        if self.is_running and self._video_id == vid:
            return self._task
        await self.stop()
        self._video_id = vid

        async def _run() -> None:
            reconnect = youtube_live_reconnect_enabled()
            delay = youtube_live_reconnect_delay_sec()
            try:
                while True:
                    try:
                        await run_youtube_live_chat_listener(
                            video_id=vid,
                            on_chat=on_chat,
                            broadcast_status=broadcast_status,
                        )
                    except asyncio.CancelledError:
                        raise
                    if not reconnect or self._video_id != vid:
                        break
                    print(
                        f"(youtube live) pytchat session ended — reconnecting in {delay:.0f}s…",
                        flush=True,
                    )
                    if broadcast_status:
                        await broadcast_status(
                            f"YouTube Live chat: disconnected — reconnecting in {int(delay)}s…"
                        )
                    try:
                        await asyncio.sleep(delay)
                    except asyncio.CancelledError:
                        raise
            finally:
                self._task = None
                self._video_id = ""
                if on_stopped is not None:
                    try:
                        await on_stopped()
                    except Exception:
                        pass

        self._task = asyncio.create_task(_run(), name=f"luna-youtube-live-chat-{vid}")
        return self._task


OnLiveDetected = Callable[[dict[str, str]], Awaitable[None]]


async def run_youtube_live_watch_poller(
    *,
    probe_url: str,
    on_live: OnLiveDetected,
    broadcast_status: BroadcastStatus | None = None,
    interval_sec: float | None = None,
) -> None:
    """Probe a channel /live URL on a timer (default every 15 minutes)."""
    from live_social_share import probe_youtube_live

    interval = interval_sec if interval_sec is not None else youtube_live_watch_poll_sec()
    url = (probe_url or youtube_live_check_probe_url()).strip()
    print(
        f"(youtube live watch) probing {url} every {int(interval)}s",
        flush=True,
    )
    if broadcast_status:
        await broadcast_status(
            f"YouTube live watch: checking {url} every {int(interval // 60)} min."
        )

    while True:
        try:
            item = await asyncio.to_thread(probe_youtube_live, url)
            if item:
                try:
                    await on_live(item)
                except Exception as exc:  # noqa: BLE001
                    print(f"(youtube live watch) on_live error: {exc}", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"(youtube live watch) probe error: {exc}", flush=True)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise


async def run_youtube_live_chat_listener(
    *,
    video_id: str,
    on_chat: OnChat,
    broadcast_status: BroadcastStatus | None = None,
) -> None:
    """Poll YouTube Live chat and call ``on_chat(author, text, ts_ms)`` for each new message."""
    try:
        import pytchat
    except ImportError:
        msg = "YouTube Live chat: install pytchat (pip install pytchat)"
        print(f"(youtube live) {msg}", flush=True)
        if broadcast_status:
            await broadcast_status(msg)
        return

    poll = float((os.environ.get("LUNA_YOUTUBE_LIVE_POLL_SEC") or "0.5").strip() or "0.5")
    poll = max(0.2, min(poll, 5.0))
    url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"(youtube live) listening: {url}", flush=True)
    if broadcast_status:
        await broadcast_status(f"YouTube Live chat (pytchat): listening ({video_id})…")

    seen: set[str] = set()

    # pytchat registers signal.SIGINT in __init__ — that only works on the main thread,
    # so we must not use asyncio.to_thread() for create() (worker thread → crash, no chat).
    try:
        chat = pytchat.create(video_id=video_id)
    except Exception as exc:
        print(f"(youtube live) pytchat.create failed: {exc}", flush=True)
        if broadcast_status:
            await broadcast_status(f"YouTube Live chat: could not start pytchat ({exc}).")
        return

    def _pull_sync() -> list[tuple[str, str, str]]:
        out: list[tuple[str, str, str]] = []
        data = chat.get()
        if data is None:
            return out
        for m in data.sync_items():
            mid = str(getattr(m, "id", "") or "").strip()
            if not mid:
                author_id = getattr(getattr(m, "author", None), "channelId", "") or ""
                mid = f"{author_id}:{getattr(m, 'datetime', '')}:{m.message}"
            author = (getattr(getattr(m, "author", None), "name", None) or "viewer").strip()
            text = (m.message or "").strip()
            out.append((mid, author, text))
        return out

    try:
        while True:
            if not chat.is_alive():
                print("(youtube live) chat ended or stream offline", flush=True)
                if broadcast_status:
                    await broadcast_status("YouTube Live chat: stream ended or chat closed.")
                break

            try:
                batch = _pull_sync()
            except Exception as exc:
                print(f"(youtube live) poll error: {exc}", flush=True)
                await asyncio.sleep(poll)
                continue

            for mid, author, text in batch:
                if mid in seen or not text:
                    continue
                seen.add(mid)
                if len(seen) > 8000:
                    seen.clear()
                ts_ms = int(time.time() * 1000)
                try:
                    await on_chat(author, text, ts_ms)
                except Exception as exc:
                    print(f"(youtube live) handler error: {exc}", flush=True)

            await asyncio.sleep(poll)
    finally:
        try:
            chat.terminate()
        except Exception:
            pass
