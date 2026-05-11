"""
Twitch chat -> Ollama (gemma4:e4b by default).

Uses Twitch IRC via twitchio. Messages must use a command prefix (default !ai / !luna)
so normal chat is not sent to the model.

Environment (or use CLI flags where noted):
  TWITCH_TOKEN   OAuth token, usually starting with oauth:
  TWITCH_CHANNEL Channel login to join (no #), e.g. mychannel
  OLLAMA_HOST    Optional, default http://127.0.0.1:11434
  OLLAMA_MODEL   Optional, default gemma4:e4b
  TWITCH_SEND_REPLIES  If "1", post model replies to chat (needs chat:write on token)
  TWITCH_AUTO_REPLY    If "1", generate replies from regular chat messages
  TWITCH_AUTO_TRIGGER  "mention" (default) or "all"
  TWITCH_AUTO_COOLDOWN Seconds between auto replies (default 6)
  TWITCH_SYSTEM  Optional extra system prompt (in addition to --system). Can stay short if you use ``ollama create`` with a Modelfile (see ollama/Modelfile.luna) to bake persona into OLLAMA_MODEL.
  LUNA_CHAT_WS_HOST  WebSocket bind host (default 127.0.0.1)
  LUNA_CHAT_WS_PORT  WebSocket port; set 0 to disable (default 8765)
  LUNA_TTS           If 1, enable Edge TTS synthesis after each reply
  LUNA_TTS_PLAY      If 1, play generated WAV locally
  LUNA_EDGE_VOICE    Default Edge voice id (e.g. en-US-JennyNeural)
  LUNA_EDGE_RATE     Edge rate adjustment like +0% / -10%
  LUNA_EDGE_PITCH    Edge pitch adjustment like +0Hz / -2Hz
  LUNA_TTS_SPEAKER   Initial voice id
  LUNA_TTS_VOICES    CSV voice list (voice or voice:Label) for viewer menu
  LUNA_STT_LOCAL_MODEL  faster-whisper size (default tiny); LUNA_STT_LOCAL_DEVICE cpu|cuda (unset = auto GPU if available)
  LUNA_SPEAKER_ONLY  If 1, viewer mic clips must match the enrolled voice (see chat panel "Enroll my voice")
  LUNA_SPEAKER_MIN_SIM  Cosine similarity threshold for the speaker check (default 0.75)
  LUNA_SPEAKER_REF  Path to the enrolled reference WAV (default: <project>/speaker_ref.wav)
  LUNA_VOICE_GATE_MALE_ONLY  Coarse fallback: drop clips with median pitch above LUNA_VOICE_GATE_MAX_F0_HZ (only used if speaker gate is off)
  LUNA_VOICE_GATE_MAX_F0_HZ  Default 172 — median voiced F0 must be ≤ this (Hz) to count as “male” for the fallback gate
  LUNA_SCREEN_CONTEXT  If 0/false/off, ignore viewer_screen_frame (default on)
  LUNA_SCREEN_CONTEXT_INTERVAL_SEC  Min seconds between vision summarizations (default 15)
  LUNA_SCREEN_VISION_MODEL  Ollama model for frames (default: same as OLLAMA_MODEL)
  LUNA_SCREEN_CONTEXT_MAX_CHARS  Cap stored summary length (default 1200)
  LUNA_SCREEN_SUMMARY_PROMPT  Vision prompt for each frame (optional)
  LUNA_SCREEN_CONTEXT_INJECTION  System text; use {summary} placeholder (optional)
  LUNA_SCREEN_CONTEXT_STATUS  If 1, post a chat-panel status line on each successful refresh
  LUNA_CHAT_MODEL  Text-only Ollama model for chat (faster than VL). Default: OLLAMA_MODEL
  LUNA_OLLAMA_NUM_GPU  Layers on GPU per request (default: max offload). Set 0 or cpu for CPU-only.
  LUNA_OLLAMA_NUM_PREDICT  Max new tokens per chat reply (smaller = faster; optional)
  LUNA_SCREEN_NUM_PREDICT  Max new tokens for screen summaries (default 240)
  LUNA_OLLAMA_KEEP_ALIVE  e.g. -1 to keep models loaded between calls (optional)
  LUNA_OLLAMA_TEMPERATURE  Sampling temperature (optional)
  LUNA_SCREEN_YIELD_TO_CHAT  If 0, may run vision while a reply generates (default 1 = skip frames while chat uses Ollama)
  LUNA_STREAM_ASSISTANT_WS  If 1 (default), stream tokens to the viewer over WS as they arrive (faster perceived replies)
  LUNA_OLLAMA_PRINT_STREAM  If 1, also print streamed tokens to the console (default 0; reduces overhead on Windows)
  LUNA_YOUTUBE_CHANNEL_ID   YouTube channel id (UC…) to watch for new uploads (announces in panel; optional Twitch chat).
  LUNA_YOUTUBE_POLL_SEC     Poll interval in seconds (default 300, min 60).
  LUNA_YOUTUBE_ANNOUNCE_TWITCH  If 1 and send_replies is on, also post the upload line in Twitch chat.
  LUNA_YT_DOWNLOAD          If 1, !play also downloads the file (default 1).
  LUNA_YT_DOWNLOAD_DIR      Folder where !play stores downloaded audio (default <project>/data/yt_audio).
  LUNA_YT_DEFAULT_FORMAT    yt-dlp format string (default bestaudio[ext=m4a]/bestaudio/best).
  LUNA_YT_TRANSCRIPT_MAX_CHARS  Cap transcript chars passed to the model for !explain (default 4000).
  DISCORD_TOKEN             Discord bot token. If set, Luna joins a voice channel and plays !play tracks there.
  DISCORD_COMMAND_PREFIX    Default "!".
  DISCORD_VOICE_GUILD_ID    Guild id; with DISCORD_VOICE_CHANNEL_ID enables auto-join on ready and remote enqueue from Twitch / panel.
  DISCORD_VOICE_CHANNEL_ID  Voice channel id to auto-join.
  DISCORD_TEXT_CHANNEL_ID   Optional. Text channel for now-playing announcements (else first channel the bot can write in).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import os
import sys
import threading
import time
from collections import deque
from typing import TYPE_CHECKING

from chat_ws import ChatHub, start_chat_ws_server, stop_chat_ws_server
from luna_tts import maybe_speak, set_selected_speaker, tts_enabled, tts_playback_enabled, tts_voices_control_message
from luna_discord_bot import LunaDiscordBot, discord_enabled
from luna_speaker_id import (
    clear_enrollment as speaker_clear,
    enroll_from_bytes as speaker_enroll,
    speaker_state,
)
from luna_stt import stt_status_line, transcribe_audio
from youtube_audio import (
    download_enabled as yt_download_enabled,
    download_to_dir as yt_download_to_dir,
    fetch_transcript as yt_fetch_transcript,
    resolve_track as yt_resolve_track,
    short_status_line as yt_short_status_line,
)
from youtube_feed import channel_id as yt_channel_id, run_feed_poller as yt_run_feed_poller
from ollama_client import (
    build_client,
    chat_once,
    chat_request_kwargs,
    configure_stdio_utf8,
    summarize_viewer_screen,
)

if TYPE_CHECKING:
    from ollama import Client

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[misc, assignment]

from aiohttp import web
from aiohttp.web import AppRunner, TCPSite
from twitchio import Message
from twitchio.ext import commands


TWITCH_MSG_LIMIT = 450


def _env_truthy(key: str, *, default: bool) -> bool:
    raw = (os.environ.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def _speaker_state_control_message() -> dict:
    state = speaker_state()
    return {
        "type": "control",
        "name": "enroll_state",
        "enabled": bool(state.get("enabled")),
        "enrolled": bool(state.get("enrolled")),
        "min_sim": float(state.get("min_sim") or 0.0),
        "last_sim": state.get("last_sim"),
    }


def detect_avatar_emotion(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ("*scream*", "*shout*", " screaming", " shouted", "shouting")):
        return "shout"
    if any(k in t for k in ("*scared*", "*afraid*", " terrified", " scared", "frightened")):
        return "surprised"
    if any(k in t for k in ("*surprised*", "*gasp*", " surprised", " gasp")):
        return "surprised"
    if any(k in t for k in ("*cry*", "*crying*", "*sad*", " i cried", " sob", "tears", "sad ")):
        return "sad"
    if any(k in t for k in ("*angry*", "*mad*", " furious", " angry", "annoyed")):
        return "angry"
    if any(k in t for k in ("*excited*", " let's go", " woo", " so hyped", " excited")):
        return "happy"
    if any(k in t for k in ("*laugh*", "*giggle*", "*chuckle*", " haha", " lol")):
        return "happy"
    return "neutral"


async def safe_send(ctx: commands.Context, content: str) -> None:
    try:
        await ctx.send(content[:500])
    except Exception as exc:
        print(f"(Twitch send failed — need chat write scope? {exc})", flush=True)


def chunk_reply(text: str, limit: int = TWITCH_MSG_LIMIT) -> list[str]:
    text = text.strip()
    if not text:
        return ["(empty reply)"]
    chunks: list[str] = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:].lstrip()
    return chunks


class LunaTwitchBot(commands.Bot):
    def __init__(
        self,
        *,
        token: str,
        channel: str,
        model: str,
        system_prompt: str,
        send_replies: bool,
        auto_reply: bool,
        auto_trigger: str,
        auto_cooldown_sec: float,
        ollama_client: Client,
        chat_hub: ChatHub | None,
        discord_bot: LunaDiscordBot | None = None,
    ) -> None:
        super().__init__(
            token=token,
            prefix="!",
            initial_channels=[channel],
        )
        self._discord = discord_bot
        self._ollama = ollama_client
        self._model = model
        self._chat_model = (os.environ.get("LUNA_CHAT_MODEL") or "").strip() or self._model
        self._system = system_prompt.strip()
        self._send_replies = send_replies
        self._auto_reply = auto_reply
        self._auto_trigger = auto_trigger
        self._auto_cooldown_sec = max(0.0, auto_cooldown_sec)
        self._last_auto_reply_ts = 0.0
        self._ollama_lock = asyncio.Lock()
        self._chat_hub = chat_hub
        # Rolling chat memory so replies stay context-aware.
        # Each turn = user + assistant message pair.
        self._memory_turns = max(0, int(os.environ.get("LUNA_CHAT_MEMORY_TURNS", "10").strip() or "10"))
        self._memory_max_chars = max(
            500,
            int(os.environ.get("LUNA_CHAT_MEMORY_MAX_CHARS", "5000").strip() or "5000"),
        )
        self._memory: deque[dict[str, str]] = deque(maxlen=max(2, self._memory_turns * 2))
        self._screen_context_summary = ""
        self._screen_context_lock = asyncio.Lock()
        self._last_screen_summarize_ts = 0.0
        if self._chat_model != self._model:
            print(
                f"(ollama) LUNA_CHAT_MODEL={self._chat_model!r} (text chat) | "
                f"OLLAMA_MODEL / vision={self._model!r}",
                flush=True,
            )

    async def ingest_viewer_screen_frame(self, image_b64: str) -> None:
        raw = (os.environ.get("LUNA_SCREEN_CONTEXT", "1") or "1").strip().lower()
        if raw in ("0", "false", "no", "off"):
            return
        if _env_truthy("LUNA_SCREEN_YIELD_TO_CHAT", default=True) and self._ollama_lock.locked():
            return
        interval = float(os.environ.get("LUNA_SCREEN_CONTEXT_INTERVAL_SEC", "15").strip() or "15")
        interval = max(3.0, interval)
        async with self._screen_context_lock:
            now = time.time()
            if now - self._last_screen_summarize_ts < interval:
                return
            self._last_screen_summarize_ts = now
            vision_model = (os.environ.get("LUNA_SCREEN_VISION_MODEL") or "").strip() or self._model
            try:
                summary = await asyncio.to_thread(
                    summarize_viewer_screen,
                    self._ollama,
                    vision_model,
                    image_b64,
                )
            except Exception as exc:
                print(f"(viewer_screen) summarize failed: {exc}", flush=True)
                if self._chat_hub:
                    await self._chat_hub.broadcast(
                        {"type": "status", "text": f"Screen context error: {exc}"}
                    )
                return
        max_chars = int(os.environ.get("LUNA_SCREEN_CONTEXT_MAX_CHARS", "1200").strip() or "1200")
        max_chars = max(200, max_chars)
        summary = (summary or "").strip()
        if not summary:
            return
        if len(summary) > max_chars:
            summary = summary[: max_chars - 1] + "…"
        self._screen_context_summary = summary
        print(f"(viewer_screen) context updated ({len(summary)} chars)", flush=True)
        if self._chat_hub and os.environ.get("LUNA_SCREEN_CONTEXT_STATUS", "").strip() == "1":
            await self._chat_hub.broadcast(
                {
                    "type": "status",
                    "text": f"Screen share context updated ({len(summary)} chars).",
                }
            )

    async def event_ready(self) -> None:
        names = [c.name for c in self.connected_channels if c]
        joined = ", ".join(f"#{n}" for n in names) or "(no channels yet)"
        print(f"Logged in as {self.nick} | {joined}", flush=True)
        if self._chat_hub:
            await self._chat_hub.broadcast(
                {
                    "type": "status",
                    "text": f"Twitch connected as {self.nick} in {joined}",
                }
            )
            await self._chat_hub.broadcast(
                {
                    "type": "control",
                    "name": "speak_enabled",
                    "value": self._send_replies,
                }
            )
            await self._chat_hub.broadcast(tts_voices_control_message())

    async def set_speak_enabled(self, enabled: bool) -> None:
        self._send_replies = enabled
        if self._chat_hub:
            await self._chat_hub.broadcast(
                {
                    "type": "control",
                    "name": "speak_enabled",
                    "value": self._send_replies,
                }
            )
            await self._chat_hub.broadcast(
                {
                    "type": "status",
                    "text": f"speak {'enabled' if enabled else 'disabled'}",
                }
            )

    async def event_message(self, message: Message) -> None:
        if message.echo:
            return
        if not message.content:
            return
        if self._chat_hub:
            ch = message.channel.name if message.channel else ""
            ts = int(message.timestamp.timestamp() * 1000)
            text = message.content or ""
            await self._chat_hub.broadcast(
                {
                    "type": "chat",
                    "user": message.author.name,
                    "text": text,
                    "channel": ch,
                    "ts": ts,
                }
            )
        await self.handle_commands(message)
        if self._should_auto_reply(message):
            await self._generate_and_dispatch_reply(
                channel_name=message.channel.name if message.channel else "",
                author=(message.author.name if message.author else "unknown"),
                question=message.content.strip(),
            )

    def _should_auto_reply(self, message: Message) -> bool:
        if not self._auto_reply:
            return False
        text = (message.content or "").strip()
        if not text:
            return False
        if text.startswith("!"):
            return False
        now = time.time()
        if now - self._last_auto_reply_ts < self._auto_cooldown_sec:
            return False
        if self._auto_trigger == "all":
            return True
        lowered = text.lower()
        return "luna" in lowered or "@luna" in lowered

    async def _ollama_stream_to_hub(self, channel_name: str, messages: list[dict]) -> str:
        """Stream Ollama tokens to the chat hub while collecting the full reply."""
        loop = asyncio.get_running_loop()
        chunk_q: asyncio.Queue[str | None] = asyncio.Queue()
        err: list[BaseException] = []
        acc: list[str] = []

        def pump() -> None:
            try:
                kwargs = chat_request_kwargs(self._chat_model, messages, stream=True)
                for chunk in self._ollama.chat(**kwargs):
                    if chunk.message and chunk.message.content:
                        piece = chunk.message.content
                        loop.call_soon_threadsafe(chunk_q.put_nowait, piece)
            except BaseException as exc:
                err.append(exc)
            finally:
                loop.call_soon_threadsafe(chunk_q.put_nowait, None)

        async def consume() -> None:
            hub = self._chat_hub
            u = self.nick or "luna"
            while True:
                piece = await chunk_q.get()
                if piece is None:
                    break
                acc.append(piece)
                if hub is not None:
                    await hub.broadcast(
                        {
                            "type": "assistant_delta",
                            "user": u,
                            "channel": channel_name,
                            "text": piece,
                        }
                    )

        th = threading.Thread(target=pump, daemon=True)
        th.start()
        try:
            await consume()
        finally:
            th.join(timeout=180.0)
        if err:
            raise err[0]
        return "".join(acc)

    async def _generate_and_dispatch_reply(
        self,
        *,
        channel_name: str,
        author: str,
        question: str,
        send_to_twitch: bool = True,
    ) -> None:
        user_line = f"[{author} in Twitch chat]: {question.strip()}"

        messages: list[dict] = []
        system_content = self._system
        if self._screen_context_summary:
            block = os.environ.get(
                "LUNA_SCREEN_CONTEXT_INJECTION",
                (
                    "\n\n## Viewer shared screen (latest auto-summary)\n"
                    "The streamer may be showing this on their shared monitor. Use it only when relevant:\n{summary}"
                ),
            ).strip()
            if "{summary}" in block:
                extra = block.format(summary=self._screen_context_summary)
            else:
                extra = f"{block}\n{self._screen_context_summary}"
            system_content = f"{system_content}{extra}" if system_content else extra.lstrip()
        if system_content:
            messages.append({"role": "system", "content": system_content})
        if self._memory_turns > 0:
            total = 0
            kept: list[dict[str, str]] = []
            for msg in reversed(self._memory):
                c = msg.get("content", "")
                total += len(c)
                if total > self._memory_max_chars:
                    break
                kept.append(msg)
            messages.extend(reversed(kept))
        messages.append({"role": "user", "content": user_line})

        print(f"\n--- Twitch /{channel_name} {author}: {question.strip()}", flush=True)
        stream_ws = self._chat_hub is not None and _env_truthy(
            "LUNA_STREAM_ASSISTANT_WS",
            default=True,
        )
        if stream_ws:
            print("Assistant: (streaming to viewer…)", flush=True)
        else:
            print("Assistant: ", end="", flush=True)

        async with self._ollama_lock:
            if stream_ws:
                reply = await self._ollama_stream_to_hub(channel_name, messages)
            else:
                reply = await asyncio.to_thread(
                    chat_once,
                    self._ollama,
                    self._chat_model,
                    messages,
                    stream=True,
                )
        reply_stripped = reply.strip()
        if self._memory_turns > 0:
            self._memory.append({"role": "user", "content": user_line})
            self._memory.append({"role": "assistant", "content": reply_stripped})
        self._last_auto_reply_ts = time.time()

        if send_to_twitch and self._send_replies:
            for part in chunk_reply(reply):
                # Send generated answer back to Twitch.
                channel = self.get_channel(channel_name) if channel_name else None
                if channel:
                    await channel.send(part[:500])

        if self._chat_hub:
            ts = int(time.time() * 1000)
            await asyncio.gather(
                self._chat_hub.broadcast(
                    {
                        "type": "assistant",
                        "user": self.nick or "luna",
                        "text": reply_stripped,
                        "channel": channel_name,
                        "ts": ts,
                    }
                ),
                self._chat_hub.broadcast(
                    {
                        "type": "control",
                        "name": "avatar_emotion",
                        "value": detect_avatar_emotion(reply_stripped),
                    }
                ),
            )

        if tts_enabled():
            if self._chat_hub:
                await self._chat_hub.broadcast(
                    {
                        "type": "control",
                        "name": "avatar_speaking",
                        "value": True,
                    }
                )
            try:
                await asyncio.to_thread(maybe_speak, reply_stripped)
            finally:
                if self._chat_hub:
                    await self._chat_hub.broadcast(
                        {
                            "type": "control",
                            "name": "avatar_speaking",
                            "value": False,
                        }
                    )

    @commands.command(name="ai", aliases=["luna"])
    async def cmd_ai(self, ctx: commands.Context, *, question: str | None = None) -> None:
        if not question or not question.strip():
            hint = "Usage: !ai <message>  (alias: !luna)"
            if self._send_replies:
                await safe_send(ctx, hint)
            else:
                print(f"(console) {hint}", flush=True)
            return
        await self._generate_and_dispatch_reply(
            channel_name=ctx.channel.name,
            author=(ctx.author.name if ctx.author else "unknown"),
            question=question.strip(),
        )

    @commands.command(name="play")
    async def cmd_play(self, ctx: commands.Context, *, query: str | None = None) -> None:
        text = (query or "").strip()
        if not text:
            await safe_send(ctx, "Usage: !play <YouTube url or search terms>")
            return
        author = ctx.author.name if ctx.author else "viewer"
        channel = ctx.channel.name if ctx.channel else ""
        result = await self.handle_play_request(text, author=author, channel_name=channel)
        if self._send_replies:
            await safe_send(ctx, result)

    @commands.command(name="explain", aliases=["yt", "summarize"])
    async def cmd_explain(self, ctx: commands.Context, *, url: str | None = None) -> None:
        target = (url or "").strip()
        if not target:
            await safe_send(ctx, "Usage: !explain <YouTube url>")
            return
        author = ctx.author.name if ctx.author else "viewer"
        channel = ctx.channel.name if ctx.channel else ""
        await self.handle_yt_summary_request(
            target,
            author=author,
            channel_name=channel,
            send_to_twitch=self._send_replies,
        )

    async def _broadcast_status(self, text: str) -> None:
        if self._chat_hub is not None:
            await self._chat_hub.broadcast({"type": "status", "text": text})
        print(text, flush=True)

    async def handle_play_request(
        self,
        query: str,
        *,
        author: str = "viewer",
        channel_name: str = "panel",
    ) -> str:
        await self._broadcast_status(f"!play ({author}): resolving “{query}”…")

        # Prefer Discord voice playback when the Discord bot is connected.
        if self._discord is not None:
            try:
                msg = await self._discord.enqueue_external(
                    query=query, requested_by=author or "Twitch"
                )
            except Exception as exc:  # pragma: no cover - defensive
                msg = f"discord: enqueue error: {exc}"
            await self._broadcast_status(f"discord: {msg}")
            return msg

        # Fallback: resolve + optional local download (OBS Media Source workflow).
        ok, payload = await asyncio.to_thread(yt_resolve_track, query)
        if not ok:
            msg = f"!play error: {payload}"
            await self._broadcast_status(msg)
            return msg
        meta = payload  # type: ignore[assignment]
        line = yt_short_status_line(meta)  # type: ignore[arg-type]
        await self._broadcast_status(f"Queued: {line}")
        if yt_download_enabled():
            ok_dl, path_or_err = await asyncio.to_thread(yt_download_to_dir, query, None)
            if ok_dl:
                await self._broadcast_status(f"Downloaded to: {path_or_err}")
            else:
                await self._broadcast_status(f"Download failed: {path_or_err}")
        if self._chat_hub is not None:
            await self._chat_hub.broadcast(
                {
                    "type": "control",
                    "name": "yt_track",
                    "title": meta.get("title", ""),  # type: ignore[union-attr]
                    "uploader": meta.get("uploader", ""),  # type: ignore[union-attr]
                    "duration_sec": meta.get("duration_sec"),  # type: ignore[union-attr]
                    "web_url": meta.get("web_url", ""),  # type: ignore[union-attr]
                    "thumbnail": meta.get("thumbnail", ""),  # type: ignore[union-attr]
                }
            )
        return f"Now playing: {line}"

    async def handle_yt_summary_request(
        self,
        url: str,
        *,
        author: str = "viewer",
        channel_name: str = "panel",
        send_to_twitch: bool = False,
    ) -> None:
        await self._broadcast_status(f"!explain ({author}): fetching transcript…")
        ok, title, transcript = await asyncio.to_thread(yt_fetch_transcript, url)
        if not ok:
            await self._broadcast_status(f"!explain error: {transcript}")
            return
        cap = int(os.environ.get("LUNA_YT_TRANSCRIPT_MAX_CHARS", "4000").strip() or "4000")
        cap = max(800, cap)
        snippet = transcript if len(transcript) <= cap else transcript[: cap - 1] + "…"
        nice_title = title or url
        question = (
            f"A viewer shared this YouTube video: {nice_title} ({url}). "
            "Here is the transcript (may be auto-captioned):\n\n"
            f"{snippet}\n\n"
            "React to it for the stream in 1-3 short sentences — give your honest take, "
            "highlight the most interesting part, and keep it natural for live chat."
        )
        await self._generate_and_dispatch_reply(
            channel_name=channel_name or "panel",
            author=author,
            question=question,
            send_to_twitch=send_to_twitch,
        )


async def _run_async(
    *,
    token: str,
    channel: str,
    model: str,
    system: str,
    send_replies: bool,
    auto_reply: bool,
    auto_trigger: str,
    auto_cooldown_sec: float,
) -> None:
    ws_host = os.environ.get("LUNA_CHAT_WS_HOST", "127.0.0.1").strip()
    ws_port = int(os.environ.get("LUNA_CHAT_WS_PORT", "8765"))

    hub: ChatHub | None = None
    runner: AppRunner | None = None
    site: TCPSite | None = None

    if ws_port > 0:
        hub = ChatHub()

        async def _on_ws_join(ws: web.WebSocketResponse) -> None:
            await hub.send_to(ws, tts_voices_control_message())
            await hub.send_to(ws, _speaker_state_control_message())

        runner, site = await start_chat_ws_server(
            hub, host=ws_host, port=ws_port, on_ws_join=_on_ws_join
        )
        print(
            f"Chat bridge WebSocket: ws://{ws_host}:{ws_port}/ws "
            f"(set VITE_CHAT_WS_URL in the viewer .env)",
            flush=True,
        )

    client = build_client()

    discord_bot_obj: LunaDiscordBot | None = None
    discord_task: asyncio.Task | None = None
    discord_token = (os.environ.get("DISCORD_TOKEN") or "").strip()
    if discord_enabled() and discord_token:
        try:
            discord_bot_obj = LunaDiscordBot(
                prefix=(os.environ.get("DISCORD_COMMAND_PREFIX") or "!").strip() or "!"
            )

            async def _run_discord_bot() -> None:
                try:
                    await discord_bot_obj.start(discord_token)
                except Exception as exc:  # noqa: BLE001
                    name = type(exc).__name__
                    if name == "PrivilegedIntentsRequired":
                        print(
                            "(discord) FAILED: Message Content Intent is OFF in the Developer Portal. "
                            "Enable it: https://discord.com/developers/applications → your bot → Bot → "
                            "Privileged Gateway Intents → Message Content Intent → Save Changes, then restart.",
                            flush=True,
                        )
                    elif name == "LoginFailure":
                        print(
                            "(discord) FAILED: invalid DISCORD_TOKEN (LoginFailure). "
                            "Reset the token in the Developer Portal and update .env.",
                            flush=True,
                        )
                    else:
                        print(f"(discord) FAILED at startup: {name}: {exc}", flush=True)

            discord_task = asyncio.create_task(_run_discord_bot(), name="luna-discord-bot")
            print(
                "Discord bot starting (DISCORD_TOKEN set). "
                f"Auto-join guild={os.environ.get('DISCORD_VOICE_GUILD_ID', '(unset)')} "
                f"channel={os.environ.get('DISCORD_VOICE_CHANNEL_ID', '(unset)')}",
                flush=True,
            )
        except Exception as exc:
            print(f"Discord bot init failed: {exc}", flush=True)
            discord_bot_obj = None

    bot = LunaTwitchBot(
        token=token,
        channel=channel,
        model=model,
        system_prompt=system,
        send_replies=send_replies,
        auto_reply=auto_reply,
        auto_trigger=auto_trigger,
        auto_cooldown_sec=auto_cooldown_sec,
        ollama_client=client,
        chat_hub=hub,
        discord_bot=discord_bot_obj,
    )
    if hub:
        async def _on_client_message(payload: dict) -> None:
            msg_type = payload.get("type")
            if msg_type == "control":
                name = payload.get("name")
                if name == "speak_enabled":
                    value = payload.get("value")
                    if isinstance(value, bool):
                        await bot.set_speak_enabled(value)
                    return
                if name == "tts_speaker":
                    raw = str(payload.get("value", "")).strip()
                    if set_selected_speaker(raw):
                        await hub.broadcast(tts_voices_control_message())
                    return
                if name == "enroll_state_request":
                    await hub.broadcast(_speaker_state_control_message())
                    return
                return

            if msg_type == "viewer_enroll_voice":
                raw_b64 = payload.get("data")
                if not isinstance(raw_b64, str) or not raw_b64.strip():
                    await hub.broadcast({"type": "status", "text": "Enroll: empty clip."})
                    return
                mime = str(payload.get("mime", "audio/webm"))
                try:
                    audio = base64.b64decode(raw_b64, validate=False)
                except (binascii.Error, ValueError):
                    await hub.broadcast({"type": "status", "text": "Enroll: invalid base64."})
                    return
                ok, note = await asyncio.to_thread(speaker_enroll, audio, mime)
                await hub.broadcast({"type": "status", "text": note})
                await hub.broadcast(_speaker_state_control_message())
                print(f"(enroll) ok={ok} ({note})", flush=True)
                return

            if msg_type == "viewer_enroll_clear":
                ok = await asyncio.to_thread(speaker_clear)
                await hub.broadcast(
                    {
                        "type": "status",
                        "text": "Enrollment cleared." if ok else "Enrollment: nothing to clear.",
                    }
                )
                await hub.broadcast(_speaker_state_control_message())
                return

            if msg_type == "viewer_screen_frame":
                raw_b64 = payload.get("data")
                if not isinstance(raw_b64, str) or not raw_b64.strip():
                    return
                await bot.ingest_viewer_screen_frame(raw_b64.strip())
                return

            if msg_type == "viewer_play":
                query = str(payload.get("query") or payload.get("url") or "").strip()
                if not query:
                    await hub.broadcast({"type": "status", "text": "!play: missing query."})
                    return
                await bot.handle_play_request(query, author="viewer", channel_name="panel")
                return

            if msg_type == "viewer_yt_summary":
                url = str(payload.get("url") or "").strip()
                if not url:
                    await hub.broadcast({"type": "status", "text": "!explain: missing URL."})
                    return
                await bot.handle_yt_summary_request(
                    url,
                    author="viewer",
                    channel_name="panel",
                    send_to_twitch=False,
                )
                return

            if msg_type == "viewer_prompt":
                text = str(payload.get("text", "")).strip()
                if not text:
                    return
                await hub.broadcast(
                    {
                        "type": "chat",
                        "user": "you",
                        "text": text,
                        "channel": "panel",
                        "ts": int(time.time() * 1000),
                    }
                )
                await bot._generate_and_dispatch_reply(
                    channel_name="panel",
                    author="viewer",
                    question=text,
                    send_to_twitch=False,
                )
                return

            if msg_type == "viewer_voice":
                try:
                    raw_b64 = payload.get("data")
                    if not isinstance(raw_b64, str) or not raw_b64.strip():
                        return
                    mime = str(payload.get("mime", "audio/webm"))
                    try:
                        audio = base64.b64decode(raw_b64, validate=False)
                    except (binascii.Error, ValueError):
                        await hub.broadcast(
                            {
                                "type": "status",
                                "text": "STT: invalid base64 audio",
                            }
                        )
                        return
                    print(f"(viewer_voice) {len(audio)} bytes, mime={mime!r}", flush=True)
                    text, note = await asyncio.to_thread(transcribe_audio, audio, mime)
                    if not text:
                        await hub.broadcast(
                            {
                                "type": "status",
                                "text": f"STT ({note}): no transcript",
                            }
                        )
                        print(f"(viewer_voice) STT failed: {note}", flush=True)
                        return
                    print(f"(viewer_voice) transcript ({note}): {text[:120]!r}…", flush=True)
                    await hub.broadcast(
                        {
                            "type": "status",
                            "text": f"STT ({note}): {text[:200]}{'…' if len(text) > 200 else ''}",
                        }
                    )
                    await hub.broadcast(
                        {
                            "type": "chat",
                            "user": "you",
                            "text": text,
                            "channel": "panel",
                            "ts": int(time.time() * 1000),
                        }
                    )
                    await bot._generate_and_dispatch_reply(
                        channel_name="panel",
                        author="viewer",
                        question=text,
                        send_to_twitch=False,
                    )
                except Exception as exc:
                    print(f"(viewer_voice) error: {exc}", flush=True)
                    await hub.broadcast(
                        {
                            "type": "status",
                            "text": f"Voice/STT error: {exc}",
                        }
                    )
                return

        hub.set_client_message_handler(_on_client_message)

    feed_task: asyncio.Task | None = None
    if hub is not None and yt_channel_id():
        async def _hub_status(text: str) -> None:
            await hub.broadcast({"type": "status", "text": text})

        async def _twitch_announce(text: str) -> None:
            if not bot._send_replies:
                return
            for room in list(bot.connected_channels or []):
                try:
                    await room.send(text[:450])
                except Exception:
                    pass

        feed_task = asyncio.create_task(
            yt_run_feed_poller(broadcast_status=_hub_status, twitch_send=_twitch_announce),
            name="luna-youtube-feed",
        )

    try:
        await bot.start()
    finally:
        if feed_task is not None:
            feed_task.cancel()
            try:
                await feed_task
            except (asyncio.CancelledError, Exception):
                pass
        if discord_bot_obj is not None:
            try:
                await discord_bot_obj.close()
            except Exception:
                pass
        if discord_task is not None:
            discord_task.cancel()
            try:
                await discord_task
            except (asyncio.CancelledError, Exception):
                pass
        if runner is not None and site is not None:
            await stop_chat_ws_server(runner, site)


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    configure_stdio_utf8()
    if load_dotenv:
        # override=True so values in .env beat any pre-set Windows/Shell env vars
        # (e.g. an old HKCU\Environment\DISCORD_TOKEN left over from another bot).
        load_dotenv(override=True)

    parser = argparse.ArgumentParser(description="Twitch chat commands -> Ollama.")
    parser.add_argument(
        "--channel",
        default=os.environ.get("TWITCH_CHANNEL", ""),
        help="Channel login without # (or set TWITCH_CHANNEL).",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("TWITCH_TOKEN", ""),
        help="OAuth token including oauth: prefix (or set TWITCH_TOKEN).",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OLLAMA_MODEL", "gemma4:e4b"),
        help="Ollama model name.",
    )
    parser.add_argument(
        "--system",
        default=os.environ.get("TWITCH_SYSTEM", ""),
        help="System prompt (stacked with TWITCH_SYSTEM env if you set both via code — here: single --system).",
    )
    args = parser.parse_args()

    extra = os.environ.get("TWITCH_SYSTEM", "").strip()
    system = " ".join(s for s in (args.system.strip(), extra) if s).strip()
    if not system:
        system = (
            "You are Luna, a friendly VTuber-style stream assistant. "
            "Keep answers concise for live chat unless the viewer asks for detail. "
            "Do not use Twitch-specific markdown that does not read well aloud."
        )

    token = args.token.strip()
    channel = args.channel.strip().lstrip("#").lower()
    if not token or not channel:
        print(
            "Set TWITCH_TOKEN (oauth:...) and TWITCH_CHANNEL (channel name), "
            "or pass --token and --channel.",
            file=sys.stderr,
        )
        sys.exit(1)
    if "oauth:" not in token.lower():
        token = f"oauth:{token.lstrip('oauth:')}"

    send_replies = os.environ.get("TWITCH_SEND_REPLIES", "").strip() in ("1", "true", "yes")
    auto_reply = os.environ.get("TWITCH_AUTO_REPLY", "").strip() in ("1", "true", "yes")
    auto_trigger = os.environ.get("TWITCH_AUTO_TRIGGER", "mention").strip().lower()
    if auto_trigger not in {"mention", "all"}:
        auto_trigger = "mention"
    auto_cooldown_sec = float(os.environ.get("TWITCH_AUTO_COOLDOWN", "6").strip() or "6")

    print(
        f"Starting Twitch bot | channel #{channel} | model {args.model} | "
        f"ollama {os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434')} | "
        f"send_replies={send_replies} | auto_reply={auto_reply} ({auto_trigger}) | "
        f"LUNA_TTS={tts_enabled()} | LUNA_TTS_PLAY={tts_playback_enabled()}",
        flush=True,
    )
    if tts_enabled():
        tts_backend = os.environ.get("LUNA_TTS_BACKEND", "edge").strip().lower()
        print(f"(LUNA_TTS enabled: using {tts_backend} backend)", flush=True)
    print(f"STT backends (order): {stt_status_line()}", flush=True)
    asyncio.run(
        _run_async(
            token=token,
            channel=channel,
            model=args.model,
            system=system,
            send_replies=send_replies,
            auto_reply=auto_reply,
            auto_trigger=auto_trigger,
            auto_cooldown_sec=auto_cooldown_sec,
        )
    )


if __name__ == "__main__":
    main()
