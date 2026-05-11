"""Broadcast Twitch chat (and Luna replies) to browser clients over WebSocket."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Coroutine

from aiohttp import web

logger = logging.getLogger(__name__)


class ChatHub:
    """Fan-out JSON messages to all connected WebSocket clients."""

    def __init__(self) -> None:
        self._clients: set[web.WebSocketResponse] = set()
        self._lock = asyncio.Lock()
        self._client_message_handler: (
            Callable[[dict[str, Any]], Coroutine[Any, Any, Any] | Any] | None
        ) = None

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def add(self, ws: web.WebSocketResponse) -> None:
        async with self._lock:
            self._clients.add(ws)

    async def remove(self, ws: web.WebSocketResponse) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        text = json.dumps(payload, ensure_ascii=False)
        async with self._lock:
            clients = list(self._clients)
        if not clients:
            return
        if len(clients) == 1:
            ws = clients[0]
            try:
                await ws.send_str(text)
            except Exception:
                await self.remove(ws)
            return
        results = await asyncio.gather(
            *(ws.send_str(text) for ws in clients), return_exceptions=True
        )
        dead = [ws for ws, res in zip(clients, results) if isinstance(res, BaseException)]
        for ws in dead:
            await self.remove(ws)

    async def send_to(self, ws: web.WebSocketResponse, payload: dict[str, Any]) -> None:
        await ws.send_str(json.dumps(payload, ensure_ascii=False))

    def set_client_message_handler(
        self, handler: Callable[[dict[str, Any]], Coroutine[Any, Any, Any] | Any]
    ) -> None:
        self._client_message_handler = handler

    async def handle_client_message(self, payload: dict[str, Any]) -> None:
        if self._client_message_handler is None:
            return
        result = self._client_message_handler(payload)
        if asyncio.iscoroutine(result):
            await result


async def _websocket_handler(request: web.Request) -> web.WebSocketResponse:
    hub: ChatHub = request.app["hub"]
    # Voice payloads are base64 JSON; allow larger than default 4 MiB.
    ws = web.WebSocketResponse(max_msg_size=32 * 1024 * 1024)
    await ws.prepare(request)
    await hub.add(ws)
    on_join = request.app.get("on_ws_join")
    if on_join is not None:
        try:
            await on_join(ws)
        except Exception:
            logger.debug("on_ws_join failed", exc_info=True)
    await hub.broadcast(
        {
            "type": "status",
            "text": f"bridge online ({hub.client_count} viewer socket(s))",
        }
    )
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                    if isinstance(payload, dict):
                        await hub.handle_client_message(payload)
                except Exception:
                    logger.debug("Invalid ws payload from client", exc_info=True)
                continue
            if msg.type in (web.WSMsgType.CLOSE, web.WSMsgType.ERROR):
                break
    finally:
        await hub.remove(ws)
    return ws


def build_chat_app(
    hub: ChatHub,
    *,
    on_ws_join: Callable[[web.WebSocketResponse], Awaitable[None]] | None = None,
) -> web.Application:
    app = web.Application()
    app["hub"] = hub
    if on_ws_join is not None:
        app["on_ws_join"] = on_ws_join
    app.router.add_get("/ws", _websocket_handler)
    return app


async def start_chat_ws_server(
    hub: ChatHub,
    *,
    host: str,
    port: int,
    on_ws_join: Callable[[web.WebSocketResponse], Awaitable[None]] | None = None,
) -> tuple[web.AppRunner, web.TCPSite]:
    app = build_chat_app(hub, on_ws_join=on_ws_join)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("Chat WebSocket listening on ws://%s:%s/ws", host, port)
    return runner, site


async def stop_chat_ws_server(runner: web.AppRunner, site: web.TCPSite) -> None:
    await site.stop()
    await runner.cleanup()
