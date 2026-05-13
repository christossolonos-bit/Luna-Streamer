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
  LUNA_VIEWER_VOICE_BLOCK_AFTER_TTS_SEC  Seconds after TTS playback ends before viewer mic
    clips are accepted (echo / ring-out guard; default 3). Set 0 to disable the tail guard.
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
  LUNA_YOUTUBE_CHANNEL_ID   UC… id for legacy single-feed poller (ignored if LUNA_YOUTUBE_OBSERVE_CHANNELS is set).
  LUNA_YOUTUBE_POLL_SEC     Poll interval for YouTube RSS (default 300, min 60).
  LUNA_YOUTUBE_OBSERVE_CHANNELS  Comma/space separated @handles or URLs to watch for new uploads.
  LUNA_YOUTUBE_ANNOUNCE_DISCORD_CHANNEL_ID  Discord text channel id for those upload announcements.
  LUNA_YOUTUBE_OBSERVE_TODAY_ONLY  1 = only same-calendar-day uploads (local PC time). Default 1.
  LUNA_YT_DOWNLOAD          If 1, !play also downloads the file (default 1).
  LUNA_YT_DOWNLOAD_DIR      Folder where !play stores downloaded audio (default <project>/data/yt_audio).
  LUNA_YT_DEFAULT_FORMAT    yt-dlp format string (default bestaudio[ext=m4a]/bestaudio/best).
  LUNA_YT_TRANSCRIPT_MAX_CHARS  Cap transcript chars passed to the model for !explain (default 4000).
  DISCORD_TOKEN             Discord bot token. If set, Luna joins a voice channel and plays !play tracks there.
  DISCORD_COMMAND_PREFIX    Default "!".
  DISCORD_VOICE_GUILD_ID    Guild id; with DISCORD_VOICE_CHANNEL_ID enables auto-join on ready and remote enqueue from Twitch / panel.
  DISCORD_VOICE_CHANNEL_ID  Voice channel id to auto-join.
  DISCORD_TEXT_CHANNEL_ID   Optional. Text channel for now-playing announcements (else first channel the bot can write in).
  LUNA_DISCORD_VOICE_TTS    If 1 (default), play Luna's Discord reply TTS in the connected VC when idle (see luna_discord_bot.py).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import json
import os
import re
import sys
import threading
import time
from difflib import SequenceMatcher
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

from chat_ws import ChatHub, start_chat_ws_server, stop_chat_ws_server
from luna_tts import (
    maybe_speak,
    prewarm_edge_tts,
    set_selected_speaker,
    synthesize_reply_to_file,
    tts_enabled,
    tts_playback_enabled,
    tts_voices_control_message,
)
from luna_discord_bot import LunaDiscordBot, discord_enabled
from luna_speaker_id import (
    clear_enrollment as speaker_clear,
    enroll_from_bytes as speaker_enroll,
    speaker_state,
)
from luna_stt import prewarm as stt_prewarm, stt_status_line, transcribe_audio
from youtube_audio import (
    download_enabled as yt_download_enabled,
    download_to_dir as yt_download_to_dir,
    extract_video_id as yt_extract_video_id,
    fetch_transcript as yt_fetch_transcript,
    resolve_track as yt_resolve_track,
    short_status_line as yt_short_status_line,
)
from youtube_feed import (
    announce_discord_channel_id,
    channel_id as yt_channel_id,
    manual_check_today_uploads,
    observe_feed_enabled,
    run_feed_poller as yt_run_feed_poller,
    run_observe_feed_poller as yt_run_observe_feed_poller,
)
from social_playwright_share import (
    run_interactive_social_login,
    share_new_youtube_upload,
    social_playwright_configured,
)
from ollama_client import (
    ThinkStripper,
    build_client,
    chat_once,
    chat_request_kwargs,
    configure_stdio_utf8,
    strip_think_blocks,
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
        "samples": int(state.get("samples") or 0),
    }


def detect_avatar_emotion(text: str) -> str:
    """Map assistant reply text to a VRM preset face id (viewer: happy|sad|angry|surprised|relaxed).

    Uses weighted keyword / phrase cues so the face roughly matches the reply tone.
    """
    t = (text or "").lower()
    scores: dict[str, float] = {"happy": 0.0, "sad": 0.0, "angry": 0.0, "surprised": 0.0, "relaxed": 0.0}

    def add(emotion: str, weight: float) -> None:
        scores[emotion] = scores.get(emotion, 0.0) + weight

    # Strong action / roleplay markers (same spirit as before, higher weight).
    if any(k in t for k in ("*scream*", "*shout*", " screaming", " shouted", "shouting")):
        add("surprised", 5.0)
    if any(k in t for k in ("*scared*", "*afraid*", " terrified", " frightened")):
        add("surprised", 4.0)
    if any(k in t for k in ("*surprised*", "*gasp*", " gasp", " jaw dropped")):
        add("surprised", 4.0)
    if any(k in t for k in ("*cry*", "*crying*", "*sob*", " i cried", " tears", "heartbroken")):
        add("sad", 5.0)
    if any(k in t for k in ("*angry*", "*mad*", " furious", " livid", " outraged")):
        add("angry", 5.0)
    if any(k in t for k in ("*laugh*", "*giggle*", "*chuckle*", " haha", " hehe", " lol", " lmao")):
        add("happy", 4.0)
    if any(k in t for k in ("*excited*", " woo", " let's go", " hyped", " can't wait")):
        add("happy", 3.5)

    # Phrase buckets (contextual reactions).
    happy_hits = (
        "thank you",
        " thanks ",
        "appreciate",
        "love that",
        " so happy",
        "glad to",
        "great news",
        "awesome",
        "amazing",
        "wonderful",
        "congrats",
        "proud of you",
        "you got this",
        " rooting for",
        "cute",
        "adorable",
        "sweet",
        "hugs",
        " mwah",
    )
    for phrase in happy_hits:
        if phrase in t:
            add("happy", 2.0)

    sad_hits = (
        "i'm sorry",
        " im sorry",
        "that's rough",
        " that sucks",
        "unfortunate",
        "disappointing",
        "feel bad",
        "sympath",
        "condolences",
        "rest in peace",
        " rip ",
        "miss them",
        "lonely",
        "depressing",
    )
    for phrase in sad_hits:
        if phrase in t:
            add("sad", 2.0)

    angry_hits = (
        "not fair",
        "unacceptable",
        "ridiculous",
        "frustrating",
        "annoying",
        "angry",
        "furious",
        "fed up",
        "cut it out",
        "stop that",
        "enough already",
    )
    for phrase in angry_hits:
        if phrase in t:
            add("angry", 2.0)

    surprise_hits = (
        "no way",
        "wait what",
        " seriously?",
        " holy ",
        "omg",
        " oh my",
        "wow",
        " incredible",
        " i can't believe",
        "plot twist",
        "shocked",
        "astonished",
    )
    for phrase in surprise_hits:
        if phrase in t:
            add("surprised", 2.0)

    calm_hits = (
        "take your time",
        "no rush",
        " step by step",
        " calmly",
        " for now",
        "by the way",
        " anyway",
        " in short",
        " basically",
    )
    for phrase in calm_hits:
        if phrase in t:
            add("relaxed", 1.2)

    # Question / uncertainty → slight surprise or neutral, not anger.
    if "?" in t and scores["surprised"] < 1 and scores["happy"] < 2:
        add("surprised", 0.8)

    # Pick winner; tie-break prefers more specific expressive faces over neutral.
    tie = {"surprised": 5, "angry": 4, "sad": 3, "happy": 2, "relaxed": 1}
    best = max(scores, key=lambda k: (scores[k], tie.get(k, 0)))
    if scores[best] <= 0:
        return "relaxed"
    return best


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
        self._memory_file = (os.environ.get("LUNA_CHAT_MEMORY_FILE") or "").strip() or str(
            Path(__file__).resolve().parent / "data" / "chat_memory.json"
        )
        self._memory_persist = _env_truthy("LUNA_CHAT_MEMORY_PERSIST", default=True)
        self._user_memory_file = (os.environ.get("LUNA_USER_MEMORY_FILE") or "").strip() or str(
            Path(__file__).resolve().parent / "data" / "user_memory.json"
        )
        self._user_memory_persist = _env_truthy("LUNA_USER_MEMORY_PERSIST", default=True)
        self._user_facts_max_per_user = max(
            2, int(os.environ.get("LUNA_USER_MEMORY_MAX_FACTS", "24").strip() or "24")
        )
        self._user_fact_max_chars = max(
            30, int(os.environ.get("LUNA_USER_MEMORY_MAX_FACT_CHARS", "220").strip() or "220")
        )
        self._user_memory_inject_max_chars = max(
            180, int(os.environ.get("LUNA_USER_MEMORY_INJECT_MAX_CHARS", "900").strip() or "900")
        )
        self._user_facts: dict[str, list[str]] = {}
        self._screen_context_summary = ""
        self._screen_context_lock = asyncio.Lock()
        self._last_screen_summarize_ts = 0.0
        # Server-side mic gate: while local TTS is playing (and briefly after),
        # reject viewer_voice packets so Luna cannot transcribe her own output.
        self._avatar_speaking = False
        self._last_avatar_speaking_end_ts = 0.0
        self._viewer_voice_block_after_tts_sec = max(
            0.0, float(os.environ.get("LUNA_VIEWER_VOICE_BLOCK_AFTER_TTS_SEC", "3.0").strip() or "3.0")
        )
        self._mic_ready_task: asyncio.Task[None] | None = None
        self._last_assistant_reply = ""
        self._load_memory_from_disk()
        self._load_user_memory_from_disk()
        if self._chat_model != self._model:
            print(
                f"(ollama) LUNA_CHAT_MODEL={self._chat_model!r} (text chat) | "
                f"OLLAMA_MODEL / vision={self._model!r}",
                flush=True,
            )

    def viewer_voice_allowed(self) -> bool:
        if self._avatar_speaking:
            return False
        # Small tail guard for buffered recorder chunks / playback ring-out.
        return (time.monotonic() - self._last_avatar_speaking_end_ts) >= self._viewer_voice_block_after_tts_sec

    def viewer_voice_cooldown_remaining_sec(self) -> float:
        """Seconds until the post-TTS mic tail guard clears (0 if ready)."""
        if self._avatar_speaking:
            return 0.0
        elapsed = time.monotonic() - self._last_avatar_speaking_end_ts
        return max(0.0, self._viewer_voice_block_after_tts_sec - elapsed)

    def _cancel_mic_ready_task(self) -> None:
        t = self._mic_ready_task
        self._mic_ready_task = None
        if t is not None and not t.done():
            t.cancel()

    async def _mic_ready_broadcast_after_delay(self, hub: ChatHub, delay_sec: float) -> None:
        try:
            if delay_sec > 0:
                await asyncio.sleep(delay_sec)
            await hub.broadcast(
                {
                    "type": "control",
                    "name": "mic_ready",
                    "value": True,
                    "hint": "You can speak into the mic now.",
                }
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    def _schedule_mic_ready_after_tts(self, hub: ChatHub) -> None:
        """Tell the viewer when the post-TTS echo guard has cleared (new TTS cancels this)."""
        self._cancel_mic_ready_task()
        delay = self._viewer_voice_block_after_tts_sec
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._mic_ready_task = loop.create_task(self._mic_ready_broadcast_after_delay(hub, delay))

    @staticmethod
    def _normalize_text_for_echo(text: str) -> str:
        cleaned = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
        return " ".join(cleaned.split())

    def looks_like_assistant_echo(self, text: str) -> bool:
        current = self._normalize_text_for_echo(text)
        prev = self._normalize_text_for_echo(self._last_assistant_reply)
        if len(current) < 20 or len(prev) < 20:
            return False
        sim = SequenceMatcher(None, current[:400], prev[:400]).ratio()
        # Near-verbatim replay (typical headphone bleed of Luna's TTS).
        if sim >= 0.78:
            return True
        c_tokens = set(current.split())
        p_tokens = set(prev.split())
        if not c_tokens or not p_tokens:
            return False
        # Short answers often reuse Luna's vocabulary without being a replay;
        # only use token overlap when the transcript is long enough to plausibly
        # be a full line picked up from speakers.
        if len(c_tokens) < 16:
            return False
        if len(current) < max(100, int(len(prev) * 0.36)):
            return False
        overlap = len(c_tokens & p_tokens) / max(1, len(c_tokens))
        return overlap >= 0.82

    def _persist_memory_to_disk(self) -> None:
        if not self._memory_persist or self._memory_turns <= 0:
            return
        try:
            path = Path(self._memory_file).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = [{"role": m.get("role", ""), "content": m.get("content", "")} for m in self._memory]
            path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"(memory) persist failed: {exc}", flush=True)

    def _load_memory_from_disk(self) -> None:
        if not self._memory_persist or self._memory_turns <= 0:
            return
        try:
            path = Path(self._memory_file).expanduser()
            if not path.is_file():
                return
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, list):
                return
            loaded: list[dict[str, str]] = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role", "")).strip()
                content = str(item.get("content", "")).strip()
                if role not in {"user", "assistant"} or not content:
                    continue
                loaded.append({"role": role, "content": content})
            self._memory.clear()
            for msg in loaded[-self._memory.maxlen :]:
                self._memory.append(msg)
            if self._memory:
                print(f"(memory) restored {len(self._memory)} messages from {path}", flush=True)
        except Exception as exc:
            print(f"(memory) restore failed: {exc}", flush=True)

    def _append_memory(self, role: str, content: str) -> None:
        if self._memory_turns <= 0:
            return
        c = content.strip()
        if not c:
            return
        self._memory.append({"role": role, "content": c})
        self._persist_memory_to_disk()

    def _platform_from_source(self, source: str) -> str | None:
        s = (source or "").strip().lower()
        if s.startswith("discord"):
            return "discord"
        if s.startswith("twitch"):
            return "twitch"
        return None

    def _user_memory_key(self, author: str, source: str) -> str | None:
        platform = self._platform_from_source(source)
        handle = (author or "").strip().lower()
        if not platform or not handle:
            return None
        return f"{platform}:{handle}"

    def _persist_user_memory_to_disk(self) -> None:
        if not self._user_memory_persist:
            return
        try:
            path = Path(self._user_memory_file).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self._user_facts, ensure_ascii=True, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"(user_memory) persist failed: {exc}", flush=True)

    def _load_user_memory_from_disk(self) -> None:
        if not self._user_memory_persist:
            return
        try:
            path = Path(self._user_memory_file).expanduser()
            if not path.is_file():
                return
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            out: dict[str, list[str]] = {}
            for raw_key, raw_facts in data.items():
                key = str(raw_key or "").strip().lower()
                if ":" not in key or not isinstance(raw_facts, list):
                    continue
                facts: list[str] = []
                for f in raw_facts:
                    txt = str(f or "").strip()
                    if not txt:
                        continue
                    if len(txt) > self._user_fact_max_chars:
                        txt = txt[: self._user_fact_max_chars - 1] + "…"
                    if txt not in facts:
                        facts.append(txt)
                    if len(facts) >= self._user_facts_max_per_user:
                        break
                if facts:
                    out[key] = facts
            self._user_facts = out
            if out:
                print(f"(user_memory) restored {len(out)} users from {path}", flush=True)
        except Exception as exc:
            print(f"(user_memory) restore failed: {exc}", flush=True)

    def _extract_user_facts(self, text: str) -> list[str]:
        t = " ".join((text or "").strip().split())
        if not t:
            return []
        facts: list[str] = []
        patterns = (
            r"\bmy name is\s+([a-zA-Z][a-zA-Z0-9_\- ]{1,40})",
            r"\bcall me\s+([a-zA-Z][a-zA-Z0-9_\- ]{1,40})",
            r"\bi(?:\s*'m|\s+am)\s+([a-zA-Z][a-zA-Z0-9_\- ]{1,40})\b",
            r"\bi(?:\s*'m|\s+am)\s+from\s+([a-zA-Z0-9 ,.'\-]{2,60})",
            r"\bi live in\s+([a-zA-Z0-9 ,.'\-]{2,60})",
            r"\bmy pronouns are\s+([a-zA-Z0-9/ \-]{2,40})",
            r"\bmy birthday is\s+([a-zA-Z0-9 ,./\-]{2,40})",
            r"\bi (?:like|love|enjoy)\s+([a-zA-Z0-9 ,.'\-]{2,80})",
            r"\bmy favorite (?:game|games|food|music|color|anime|movie) is\s+([a-zA-Z0-9 ,.'\-]{2,80})",
        )
        for p in patterns:
            m = re.search(p, t, flags=re.IGNORECASE)
            if not m:
                continue
            value = " ".join((m.group(1) or "").strip().strip(".,!?;:").split())
            if not value:
                continue
            label = p
            if "my name is" in p or "call me" in p:
                fact = f"name: {value}"
            elif "pronouns" in p:
                fact = f"pronouns: {value}"
            elif "birthday" in p:
                fact = f"birthday: {value}"
            elif "from" in p:
                fact = f"from: {value}"
            elif "live in" in p:
                fact = f"lives in: {value}"
            elif "favorite" in p:
                fact = f"favorite: {value}"
            elif "like|love|enjoy" in label:
                fact = f"likes: {value}"
            else:
                fact = value
            if len(fact) > self._user_fact_max_chars:
                fact = fact[: self._user_fact_max_chars - 1] + "…"
            if fact not in facts:
                facts.append(fact)
        return facts

    def _remember_user_facts(self, author: str, source: str, text: str) -> None:
        key = self._user_memory_key(author, source)
        if not key:
            return
        extracted = self._extract_user_facts(text)
        if not extracted:
            return
        bucket = self._user_facts.get(key, [])
        changed = False
        for fact in extracted:
            if fact in bucket:
                continue
            bucket.append(fact)
            changed = True
        if not changed:
            return
        # Keep the most recent facts if we exceed cap.
        if len(bucket) > self._user_facts_max_per_user:
            bucket = bucket[-self._user_facts_max_per_user :]
        self._user_facts[key] = bucket
        self._persist_user_memory_to_disk()

    def _user_memory_block(self, author: str, source: str) -> str:
        key = self._user_memory_key(author, source)
        if not key:
            return ""
        facts = self._user_facts.get(key, [])
        if not facts:
            return ""
        speaker = f"{source}:{author}"
        lines: list[str] = []
        total = 0
        for fact in facts:
            row = f"- {fact}"
            if total + len(row) > self._user_memory_inject_max_chars:
                break
            lines.append(row)
            total += len(row)
        if not lines:
            return ""
        return (
            "\n\n## Known facts about this speaker\n"
            f"Source user: {speaker}\n"
            "Use only when relevant, and do not invent missing details.\n"
            + "\n".join(lines)
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
        """Stream Ollama tokens to the chat hub while collecting the full reply.

        Filters out reasoning-model ``<think>...</think>`` blocks so the viewer
        only sees the visible answer (the raw chunks still accumulate so we can
        return / strip the full text once the stream ends).
        """
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

        # Coalesce tokens into ~50 ms windows (or every 48+ chars) so the
        # viewer renders ~10 deltas per reply instead of ~200 — cuts WS frames
        # and React re-renders by an order of magnitude with no visible lag.
        try:
            flush_ms = max(10, int(os.environ.get("LUNA_STREAM_FLUSH_MS", "50") or "50"))
        except ValueError:
            flush_ms = 50
        try:
            flush_chars = max(8, int(os.environ.get("LUNA_STREAM_FLUSH_CHARS", "48") or "48"))
        except ValueError:
            flush_chars = 48
        flush_interval = flush_ms / 1000.0

        async def consume() -> None:
            hub = self._chat_hub
            u = self.nick or "luna"
            stripper = ThinkStripper()
            pending = ""
            last_flush = loop.time()

            async def flush() -> None:
                nonlocal pending, last_flush
                if pending and hub is not None:
                    await hub.broadcast(
                        {
                            "type": "assistant_delta",
                            "user": u,
                            "channel": channel_name,
                            "text": pending,
                        }
                    )
                pending = ""
                last_flush = loop.time()

            while True:
                # Block for the next chunk unless we already have pending text
                # to flush — in that case timeout so the user sees tokens.
                timeout = None
                if pending:
                    elapsed = loop.time() - last_flush
                    timeout = max(0.0, flush_interval - elapsed)
                try:
                    if timeout is None:
                        piece = await chunk_q.get()
                    else:
                        piece = await asyncio.wait_for(chunk_q.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    await flush()
                    continue

                if piece is None:
                    visible = stripper.finalize()
                else:
                    acc.append(piece)
                    visible = stripper.feed(piece)
                if visible:
                    pending += visible
                    if piece is None or len(pending) >= flush_chars:
                        await flush()
                    elif (loop.time() - last_flush) >= flush_interval:
                        await flush()
                if piece is None:
                    await flush()
                    break

        th = threading.Thread(target=pump, daemon=True)
        th.start()
        try:
            await consume()
        finally:
            th.join(timeout=180.0)
        if err:
            raise err[0]
        return strip_think_blocks("".join(acc))

    async def _generate_and_dispatch_reply(
        self,
        *,
        channel_name: str,
        author: str,
        question: str,
        send_to_twitch: bool = True,
        source: str = "Twitch chat",
        local_speak: bool = True,
        discord_voice_channel: str | None = None,
    ) -> str:
        """Generate a reply, append to shared memory, broadcast to hub + TTS.

        Returns the assistant reply text so non-Twitch callers (Discord, viewer
        panel) can forward it to their own destination. ``source`` is the human
        label injected into the user turn so Luna's memory knows where the
        message came from (e.g. ``"Twitch chat"``, ``"Discord #general"``,
        ``"Discord DM"``, ``"viewer panel"``).

        Set ``local_speak=False`` for replies whose audio should NOT play on
        the streamer's speakers (e.g. Discord chat, which uploads its own
        audio attachment instead). The viewer still receives the assistant
        message + emotion broadcasts so the panel stays in sync.
        """
        vc_note = ""
        if discord_voice_channel:
            vc_note = (
                f" — speaker is currently in Discord voice channel {discord_voice_channel}"
            )
        user_line = f"[{author} in {source}{vc_note}]: {question.strip()}"

        messages: list[dict] = []
        system_content = self._system
        self._remember_user_facts(author, source, question)
        user_memory = self._user_memory_block(author, source)
        if user_memory:
            system_content = f"{system_content}{user_memory}" if system_content else user_memory.lstrip()
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
        reply_stripped = strip_think_blocks(reply).strip()
        self._last_assistant_reply = reply_stripped
        if self._memory_turns > 0:
            self._append_memory("user", user_line)
            self._append_memory("assistant", reply_stripped)
        self._last_auto_reply_ts = time.time()

        if send_to_twitch and self._send_replies:
            for part in chunk_reply(reply):
                # Send generated answer back to Twitch.
                channel = self.get_channel(channel_name) if channel_name else None
                if channel:
                    await channel.send(part[:500])

        if self._chat_hub:
            ts = int(time.time() * 1000)
            # Tell the viewer TTS is about to start *before* the assistant line so
            # the UI does not fire text-timed lip animation (luna-assistant-reply).
            if local_speak and tts_enabled():
                self._cancel_mic_ready_task()
                await self._chat_hub.broadcast(
                    {
                        "type": "control",
                        "name": "avatar_speaking",
                        "value": True,
                    }
                )
                self._avatar_speaking = True
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
                        "duration_ms": min(
                            12_000,
                            max(1_800, int(len(reply_stripped) * 42)),
                        ),
                    }
                ),
            )

        if local_speak and tts_enabled():
            loop = asyncio.get_running_loop()

            def _emit_viseme(vowel: str, intensity: float, hold_ms: int) -> None:
                hub = self._chat_hub
                if hub is None:
                    return
                payload = {
                    "type": "control",
                    "name": "avatar_viseme",
                    "value": str(vowel or "").lower(),
                    "intensity": max(0.0, min(1.0, float(intensity))),
                    "hold_ms": max(40, min(400, int(hold_ms))),
                }
                try:
                    asyncio.run_coroutine_threadsafe(hub.broadcast(payload), loop)
                except RuntimeError:
                    # Event loop stopped during shutdown.
                    pass

            try:
                await asyncio.to_thread(maybe_speak, reply_stripped, viseme_cb=_emit_viseme)
            finally:
                self._avatar_speaking = False
                self._last_avatar_speaking_end_ts = time.monotonic()
                if self._chat_hub:
                    await self._chat_hub.broadcast(
                        {
                            "type": "control",
                            "name": "avatar_speaking",
                            "value": False,
                        }
                    )
                    self._schedule_mic_ready_after_tts(self._chat_hub)
        return reply_stripped

    async def handle_discord_chat(
        self,
        *,
        author: str,
        question: str,
        discord_channel_label: str,
        is_dm: bool,
        voice_channel_label: str | None = None,
    ) -> tuple[str, "Path | None"]:
        """Entry point for Discord text messages.

        Mirrors the incoming message to the viewer panel, then runs the same
        reply pipeline as Twitch / viewer so memory + chat hub stay in sync.
        Skips LOCAL TTS playback (the streamer doesn't want Discord chatter
        spoken through their headphones) and instead synthesises a separate
        audio file that the Discord layer attaches to its text reply. Set
        ``LUNA_DISCORD_TTS=0`` to disable the audio attachment entirely.
        """
        source = "Discord DM" if is_dm else f"Discord {discord_channel_label}"
        ts = int(time.time() * 1000)
        if self._chat_hub:
            await self._chat_hub.broadcast(
                {
                    "type": "chat",
                    "user": author,
                    "text": question,
                    "channel": source,
                    "ts": ts,
                }
            )
        reply = await self._generate_and_dispatch_reply(
            channel_name=source,
            author=author,
            question=question,
            send_to_twitch=False,
            source=source,
            local_speak=False,
            discord_voice_channel=voice_channel_label,
        )

        audio_path: Path | None = None
        if reply and _env_truthy("LUNA_DISCORD_TTS", default=True) and tts_enabled():
            try:
                audio_path = await asyncio.to_thread(synthesize_reply_to_file, reply)
            except Exception as exc:
                print(f"(discord tts) synth failed: {exc}", flush=True)
                audio_path = None
        return reply, audio_path

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
    # Wire Discord free-text chat into LunaTwitchBot's shared memory pipeline.
    if discord_bot_obj is not None:
        discord_bot_obj.set_chat_handler(bot.handle_discord_chat)

    # Kick off STT + TTS warmups in the background. These cost a few seconds
    # of model load / DNS handshake the FIRST time they're called, so doing
    # them up front means the first user utterance / first reply is fast.
    async def _warm_stt() -> None:
        try:
            await asyncio.to_thread(stt_prewarm)
        except Exception as exc:
            print(f"(stt prewarm) failed: {exc}", flush=True)

    async def _warm_tts() -> None:
        try:
            await asyncio.to_thread(prewarm_edge_tts)
        except Exception as exc:
            print(f"(tts prewarm) failed: {exc}", flush=True)

    asyncio.create_task(_warm_stt(), name="luna-stt-prewarm")
    asyncio.create_task(_warm_tts(), name="luna-tts-prewarm")
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

            if msg_type == "viewer_youtube_observe_check":
                if not observe_feed_enabled():
                    await hub.broadcast(
                        {
                            "type": "status",
                            "text": "YouTube observe: not configured (set LUNA_YOUTUBE_OBSERVE_CHANNELS).",
                        }
                    )
                    return
                try:
                    lines = await manual_check_today_uploads()
                except Exception as exc:
                    await hub.broadcast(
                        {"type": "status", "text": f"YouTube observe check failed: {exc}"},
                    )
                    return
                for line in lines:
                    await hub.broadcast({"type": "status", "text": line})
                if discord_bot_obj is not None and announce_discord_channel_id() is not None:
                    body = "\n".join(lines)
                    for start in range(0, len(body), 1900):
                        await _discord_yt_upload(body[start : start + 1900])
                return

            if msg_type == "viewer_social_share_video":
                url = str(payload.get("url") or "").strip()
                if not url:
                    await hub.broadcast({"type": "status", "text": "Social share: missing URL."})
                    return
                if not yt_extract_video_id(url):
                    await hub.broadcast(
                        {
                            "type": "status",
                            "text": "Social share: use a YouTube video link (watch, Shorts, or youtu.be).",
                        }
                    )
                    return
                if not social_playwright_configured():
                    await hub.broadcast(
                        {
                            "type": "status",
                            "text": (
                                "Social share: not configured. The dock button does not open a login browser. "
                                "Log in once from a terminal (see next line), then set LUNA_SOCIAL_* in .env and restart Luna."
                            ),
                        }
                    )
                    await hub.broadcast(
                        {
                            "type": "status",
                            "text": (
                                "Set LUNA_SOCIAL_X_STORAGE_STATE / LUNA_SOCIAL_FACEBOOK_STORAGE_STATE in .env, restart Luna, "
                                "then use the **X** or **Facebook** dock buttons: sign in in the first tab, **close that tab** "
                                "(wait for “saved” in chat). Or: python scripts/social_playwright_login.py https://x.com D:/x.json"
                            ),
                        }
                    )
                    return

                async def _manual_social_share() -> None:
                    try:
                        ok, meta = await asyncio.to_thread(yt_resolve_track, url)
                        if not ok or not isinstance(meta, dict):
                            err = meta if isinstance(meta, str) else "Could not resolve that URL."
                            await hub.broadcast({"type": "status", "text": f"Social share: {err}"})
                            return
                        title = (meta.get("title") or "YouTube").strip()
                        web_url = (meta.get("web_url") or url).strip()
                        await share_new_youtube_upload(title=title, video_url=web_url)
                    except Exception as exc:
                        await hub.broadcast({"type": "status", "text": f"Social share: {exc}"})
                        return
                    await hub.broadcast(
                        {
                            "type": "status",
                            "text": "Social share: Playwright run finished (check X/Facebook or terminal if nothing posted).",
                        }
                    )

                await hub.broadcast(
                    {"type": "status", "text": "Social share: resolving title, then Playwright (X/Facebook)..."}
                )
                asyncio.create_task(_manual_social_share())
                return

            if msg_type == "viewer_social_interactive_login":
                site_raw = str(payload.get("site") or "x").strip().lower()
                if site_raw in ("facebook", "fb"):
                    site = "facebook"
                    env_key = "LUNA_SOCIAL_FACEBOOK_STORAGE_STATE"
                else:
                    site = "x"
                    env_key = "LUNA_SOCIAL_X_STORAGE_STATE"
                out_raw = str(payload.get("out_path") or os.environ.get(env_key) or "").strip()
                if not out_raw:
                    await hub.broadcast(
                        {
                            "type": "status",
                            "text": f"Social login: set {env_key} in .env to the JSON path to create (e.g. D:/secrets/luna_x.json).",
                        }
                    )
                    return
                out_path = Path(out_raw).expanduser()

                async def _login_bcast(text: str) -> None:
                    await hub.broadcast({"type": "status", "text": text})

                def _login_done(task: asyncio.Task) -> None:
                    try:
                        exc = task.exception()
                    except asyncio.CancelledError:
                        return
                    if exc:
                        print(f"(social playwright) interactive login: {exc}", flush=True)

                tsk = asyncio.create_task(
                    run_interactive_social_login(site=site, out_path=out_path, broadcast=_login_bcast)
                )
                tsk.add_done_callback(_login_done)
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
                    source="viewer panel",
                )
                return

            if msg_type == "viewer_voice":
                try:
                    if not bot.viewer_voice_allowed():
                        if bot._avatar_speaking:
                            gate_msg = "Mic clip ignored: Luna is still speaking."
                        else:
                            rem = bot.viewer_voice_cooldown_remaining_sec()
                            w = max(1, int(rem + 0.99))
                            gate_msg = (
                                f"Mic clip ignored: wait ~{w}s after Luna's voice (echo guard). "
                                "Watch for a 'Mic ready' line, then speak."
                            )
                        await hub.broadcast({"type": "status", "text": gate_msg})
                        return
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
                    if bot.looks_like_assistant_echo(text):
                        await hub.broadcast(
                            {
                                "type": "status",
                                "text": "Mic clip ignored: detected Luna voice echo.",
                            }
                        )
                        await hub.broadcast(
                            {
                                "type": "control",
                                "name": "mic_ready",
                                "value": True,
                                "hint": "You can speak now — try again (rephrase if it still matches Luna's last line).",
                            }
                        )
                        print("(viewer_voice) dropped likely assistant echo", flush=True)
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
                        source="viewer voice",
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
    if hub is not None:
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

        async def _discord_yt_upload(text: str) -> None:
            if discord_bot_obj is None:
                return
            cid = announce_discord_channel_id()
            if cid is None:
                return
            dbot = discord_bot_obj.bot
            try:
                await asyncio.wait_for(dbot.wait_until_ready(), timeout=180.0)
            except Exception as exc:
                print(f"(discord yt announce) wait_until_ready failed: {exc}", flush=True)
                return
            for attempt in range(6):
                ch = dbot.get_channel(cid)
                if ch is None:
                    try:
                        ch = await dbot.fetch_channel(cid)
                    except Exception as exc:
                        if attempt == 5:
                            print(f"(discord yt announce) fetch_channel({cid}) failed: {exc}", flush=True)
                        ch = None
                if ch is not None:
                    try:
                        await ch.send(text[:1900])
                    except Exception as exc:
                        print(f"(discord yt announce) send failed: {exc}", flush=True)
                    return
                await asyncio.sleep(1.2)
            print(f"(discord yt announce) channel {cid} not available after retries.", flush=True)

        async def _social_playwright_upload(title: str, video_url: str) -> None:
            try:
                await share_new_youtube_upload(title=title, video_url=video_url)
            except Exception as exc:
                print(f"(social playwright) share failed: {exc}", flush=True)

        if observe_feed_enabled():
            d_send = (
                _discord_yt_upload
                if discord_bot_obj is not None and announce_discord_channel_id() is not None
                else None
            )
            s_send = _social_playwright_upload if social_playwright_configured() else None
            feed_task = asyncio.create_task(
                yt_run_observe_feed_poller(
                    broadcast_status=_hub_status,
                    twitch_send=_twitch_announce,
                    discord_send=d_send,
                    social_share_send=s_send,
                ),
                name="luna-youtube-observe",
            )
        elif yt_channel_id():
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
        # Playwright's async driver uses asyncio.create_subprocess_exec; SelectorEventLoop
        # does not implement subprocess transport on Windows (NotImplementedError). Proactor does.
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
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
