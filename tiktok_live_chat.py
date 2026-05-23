"""TikTok Live chat reader for Luna. Incoming chat only — replies stay in the viewer.

Reply spacing uses ``LUNA_TIKTOK_LIVE_COOLDOWN_SEC`` or ``LUNA_PUBLIC_CHAT_COOLDOWN_SEC`` (see
``luna_public_chat_cooldown``), shared with Twitch/YouTube so rapid viewer chat does not stack.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Awaitable, Callable

OnChat = Callable[[str, str, int], Awaitable[None]]
BroadcastStatus = Callable[[str], Awaitable[None]]
OnStopped = Callable[[], Awaitable[None]]


def _env_truthy(key: str, *, default: bool = False) -> bool:
    raw = (os.environ.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def tiktok_live_chat_requested() -> bool:
    return _env_truthy("LUNA_TIKTOK_LIVE_CHAT", default=False)


def tiktok_live_username() -> str:
    raw = (os.environ.get("LUNA_TIKTOK_LIVE_USERNAME") or "").strip()
    if not raw:
        return ""
    return raw if raw.startswith("@") else f"@{raw}"


def tiktok_live_auto_reply_enabled() -> bool:
    return _env_truthy("LUNA_TIKTOK_LIVE_AUTO_REPLY", default=True)


def tiktok_live_auto_trigger() -> str:
    raw = (os.environ.get("LUNA_TIKTOK_LIVE_AUTO_TRIGGER") or "all").strip().lower()
    return raw if raw in {"mention", "all"} else "all"


def tiktok_live_reconnect_enabled() -> bool:
    return _env_truthy("LUNA_TIKTOK_LIVE_RECONNECT", default=True)


def tiktok_live_reconnect_delay_sec() -> float:
    raw = (os.environ.get("LUNA_TIKTOK_LIVE_RECONNECT_DELAY_SEC") or "5").strip() or "5"
    try:
        sec = float(raw)
    except ValueError:
        sec = 5.0
    return max(2.0, min(sec, 120.0))


def tiktok_live_watch_poll_enabled() -> bool:
    """Probe @handle on an interval and connect chat only when live."""
    if not tiktok_live_chat_requested():
        return False
    return _env_truthy("LUNA_TIKTOK_LIVE_WATCH_POLL", default=True)


def tiktok_live_watch_poll_sec() -> float:
    raw = (os.environ.get("LUNA_TIKTOK_LIVE_WATCH_POLL_SEC") or "900").strip() or "900"
    try:
        sec = float(raw)
    except ValueError:
        sec = 900.0
    return max(60.0, min(sec, 86_400.0))


def _normalize_uid(username: str) -> str:
    uid = (username or "").strip()
    if not uid:
        return ""
    return uid if uid.startswith("@") else f"@{uid}"


def _exception_end_reason(exc: BaseException) -> str:
    try:
        from TikTokLive.client.errors import UserNotFoundError, UserOfflineError
    except ImportError:
        UserOfflineError = UserNotFoundError = ()  # type: ignore[misc, assignment]

    if isinstance(exc, UserOfflineError):
        return "offline"
    if isinstance(exc, UserNotFoundError):
        return "not_found"
    msg = str(exc).lower()
    if "offline" in msg:
        return "offline"
    if "not found" in msg or "user_not_found" in msg:
        return "not_found"
    return "error"


async def is_tiktok_user_live(username: str) -> bool:
    """True when TikTokLive reports the creator is currently live."""
    uid = _normalize_uid(username)
    if not uid:
        return False
    try:
        from TikTokLive import TikTokLiveClient
    except ImportError:
        return False
    client = TikTokLiveClient(unique_id=uid)
    try:
        return bool(await client.is_live())
    except Exception:
        return False
    finally:
        try:
            await client.close()
        except Exception:
            pass


class TikTokLiveChatRunner:
    """Start/stop TikTokLive listener for one @username."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._username = ""

    @property
    def active_username(self) -> str:
        return self._username

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def stop(self) -> None:
        task = self._task
        self._task = None
        self._username = ""
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
        username: str,
        on_chat: OnChat,
        broadcast_status: BroadcastStatus | None = None,
        on_stopped: OnStopped | None = None,
    ) -> asyncio.Task[None] | None:
        uid = _normalize_uid(username)
        if not uid:
            return None
        if self.is_running and self._username.lower() == uid.lower():
            return self._task
        await self.stop()
        self._username = uid

        async def _run() -> None:
            reconnect = tiktok_live_reconnect_enabled()
            delay = tiktok_live_reconnect_delay_sec()
            try:
                while True:
                    try:
                        end_reason = await run_tiktok_live_chat_listener(
                            username=uid,
                            on_chat=on_chat,
                            broadcast_status=broadcast_status,
                        )
                    except asyncio.CancelledError:
                        raise
                    if self._username.lower() != uid.lower():
                        break
                    if end_reason in ("offline", "not_found"):
                        break
                    if not reconnect:
                        break
                    if end_reason == "session_ended":
                        still_live = await is_tiktok_user_live(uid)
                        if not still_live:
                            print(
                                f"(tiktok live) {uid} no longer live — listener stopped",
                                flush=True,
                            )
                            if broadcast_status:
                                await broadcast_status(
                                    f"TikTok Live: {uid} ended — chat listener stopped."
                                )
                            break
                        print(
                            f"(tiktok live) session ended — reconnecting in {delay:.0f}s…",
                            flush=True,
                        )
                        if broadcast_status:
                            await broadcast_status(
                                f"TikTok Live chat: disconnected — reconnecting in {int(delay)}s…"
                            )
                        try:
                            await asyncio.sleep(delay)
                        except asyncio.CancelledError:
                            raise
                        continue
                    break
            finally:
                self._task = None
                self._username = ""
                if on_stopped is not None:
                    try:
                        await on_stopped()
                    except Exception:
                        pass

        self._task = asyncio.create_task(_run(), name=f"luna-tiktok-live-chat-{uid}")
        return self._task


async def run_tiktok_live_chat_listener(
    *,
    username: str,
    on_chat: OnChat,
    broadcast_status: BroadcastStatus | None = None,
) -> str:
    """Listen to TikTok Live comments. Returns ``offline``, ``session_ended``, etc."""
    try:
        from TikTokLive import TikTokLiveClient
        from TikTokLive.events import CommentEvent, ConnectEvent
    except ImportError:
        msg = "TikTok Live chat: install TikTokLive (pip install TikTokLive)"
        print(f"(tiktok live) {msg}", flush=True)
        if broadcast_status:
            await broadcast_status(msg)
        return "create_failed"

    uid = _normalize_uid(username)
    if not uid:
        return "not_found"

    if not await is_tiktok_user_live(uid):
        print(
            f"(tiktok live) {uid} is offline — listener idle (restart Luna or go live to connect)",
            flush=True,
        )
        if broadcast_status:
            await broadcast_status(f"TikTok Live: {uid} is not live — chat listener stopped.")
        return "offline"

    print(f"(tiktok live) listening: {uid}", flush=True)
    if broadcast_status:
        await broadcast_status(f"TikTok Live chat: listening ({uid})…")

    seen: set[tuple[str, str, str]] = set()
    client = TikTokLiveClient(unique_id=uid)
    loop = asyncio.get_running_loop()

    @client.on(ConnectEvent)
    async def _on_connect(event: ConnectEvent) -> None:  # noqa: ARG001
        print(f"(tiktok live) connected: {uid}", flush=True)

    @client.on(CommentEvent)
    async def _on_comment(event: CommentEvent) -> None:
        author = (
            str(getattr(getattr(event, "user", None), "nickname", None) or "").strip()
            or str(getattr(getattr(event, "user", None), "unique_id", None) or "").strip()
            or "viewer"
        )
        text = str(getattr(event, "comment", "") or "").strip()
        if not text:
            return
        ev_id = str(getattr(event, "msg_id", "") or "").strip()
        stamp = str(getattr(event, "create_time", "") or "").strip()
        key = (ev_id, author, text if not ev_id else stamp)
        if key in seen:
            return
        seen.add(key)
        if len(seen) > 8000:
            seen.clear()
        ts_ms = int(time.time() * 1000)
        fut = asyncio.run_coroutine_threadsafe(on_chat(author, text, ts_ms), loop)
        try:
            await asyncio.wrap_future(fut)
        except Exception as exc:  # noqa: BLE001
            print(f"(tiktok live) handler error: {exc}", flush=True)

    start_task: asyncio.Task | None = None
    try:
        start_task = await client.start(
            fetch_room_info=False,
            fetch_gift_info=False,
            fetch_live_check=True,
        )
        await start_task
        return "session_ended"
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        reason = _exception_end_reason(exc)
        if reason == "offline":
            print(f"(tiktok live) {uid} went offline — listener stopped", flush=True)
            if broadcast_status:
                await broadcast_status(f"TikTok Live: {uid} is offline — chat listener stopped.")
        elif reason == "not_found":
            print(f"(tiktok live) user not found: {uid}", flush=True)
            if broadcast_status:
                await broadcast_status(f"TikTok Live: user {uid} not found.")
        else:
            print(f"(tiktok live) listener error: {exc}", flush=True)
            if broadcast_status:
                await broadcast_status(f"TikTok Live chat: {exc}")
        return reason
    finally:
        try:
            await client.disconnect(close_client=True)
        except Exception:
            pass
        try:
            await client.close()
        except Exception:
            pass


OnLiveDetected = Callable[[dict[str, str]], Awaitable[None]]
OnOffline = Callable[[], Awaitable[None]]


async def run_tiktok_live_watch_poller(
    *,
    username: str,
    on_live: OnLiveDetected,
    on_offline: OnOffline | None = None,
    broadcast_status: BroadcastStatus | None = None,
    interval_sec: float | None = None,
) -> None:
    """Probe TikTok @handle on a timer; connect chat when live."""
    from live_social_share import probe_tiktok_live

    uid = _normalize_uid(username or tiktok_live_username())
    if not uid:
        return
    interval = interval_sec if interval_sec is not None else tiktok_live_watch_poll_sec()
    print(
        f"(tiktok live watch) probing {uid} every {int(interval)}s",
        flush=True,
    )
    if broadcast_status:
        await broadcast_status(
            f"TikTok live watch: checking {uid} every {int(interval // 60)} min."
        )

    while True:
        try:
            item = await probe_tiktok_live(uid)
            if item:
                try:
                    await on_live(item)
                except Exception as exc:  # noqa: BLE001
                    print(f"(tiktok live watch) on_live error: {exc}", flush=True)
            elif on_offline is not None:
                try:
                    await on_offline()
                except Exception as exc:  # noqa: BLE001
                    print(f"(tiktok live watch) on_offline error: {exc}", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"(tiktok live watch) probe error: {exc}", flush=True)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
