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
  LUNA_PERSONA    Character depth (see luna_persona.py; merged with TWITCH_SYSTEM + LUNA_VOICE_RULES).
  LUNA_VOICE_RULES  Anti–stream-bot rules (default bans pack/tail-wag/stream filler unless user mentions them).
  LUNA_CHAT_MEMORY_RESET  If 1, wipe chat_memory.json once on startup (use after persona change).
  LUNA_OLLAMA_TEMPERATURE  Optional Ollama temperature (e.g. 0.85 for more natural variety).
  LUNA_CHAT_WS_HOST  WebSocket bind host (default 127.0.0.1)
  LUNA_CHAT_WS_PORT  WebSocket port; set 0 to disable (default 8765)
  LUNA_TTS           If 1, enable Edge TTS synthesis after each reply
  LUNA_TTS_PLAY      If 1, play on PC speakers when LUNA_TTS_PLAY_TARGET is local or both
  LUNA_TTS_PLAY_TARGET  local (default) | viewer (VRM browser / OBS) | both
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
  LUNA_SCREEN_CONTEXT_INTERVAL_SEC  Min seconds between Ollama vision summaries (default 15; viewer may send frames at 1 FPS)
  LUNA_SCREEN_CAPTURE_INTERVAL_MS   Viewer JPEG upload interval (Vite: VITE_SCREEN_CONTEXT_INTERVAL_MS, default 1000 = 1 FPS)
  LUNA_SCREEN_CAPTURE_MAX_WIDTH     Viewer max frame width (Vite: VITE_SCREEN_CAPTURE_MAX_WIDTH, default 1280)
  LUNA_SCREEN_CAPTURE_JPEG_QUALITY  Viewer JPEG quality 0–1 (Vite: VITE_SCREEN_CAPTURE_JPEG_QUALITY, default 0.72)
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
  LUNA_YOUTUBE_LIVE_CHAT           If 1, read YouTube Live chat via pytchat (no replies posted to YouTube).
  LUNA_YOUTUBE_LIVE_VIDEO_ID       Live stream video id (11 chars) or use LUNA_YOUTUBE_LIVE_URL.
  LUNA_YOUTUBE_LIVE_URL            watch URL for the live stream (alternative to VIDEO_ID).
  LUNA_YOUTUBE_LIVE_AUTO_REPLY     If 1 (default), Luna replies in the viewer/TTS only (not YouTube chat).
  LUNA_YOUTUBE_LIVE_AUTO_TRIGGER   mention | all (default all for live chat).
  LUNA_YOUTUBE_LIVE_CHECK_URL      Single @handle/live or watch URL for manual “check YouTube live” (default @Solonaras1/live).
  LUNA_SOCIAL_LIVE_SHARE           If 1, post to X/Facebook when you go live on YouTube or Twitch.
  LUNA_SOCIAL_LIVE_POLL_SEC        How often to check for live (default 90s).
  LUNA_SOCIAL_LIVE_TITLE_PREFIX    Prepended to stream title in social posts (default "Live now:").
  LUNA_SOCIAL_LIVE_YOUTUBE_URLS    Extra YouTube channel/live URLs to watch (optional).
  LUNA_TWITCH_LIVE_ANNOUNCE        If 1, detect Twitch go-live (Discord all servers + optional X/Facebook).
  LUNA_TWITCH_LIVE_DISCORD         If 1 (default when ANNOUNCE=1), post to every Discord server Luna is in.
  LUNA_TWITCH_LIVE_SOCIAL          If 1 (default when ANNOUNCE=1), post invitation on X and Facebook profile.
  LUNA_TWITCH_LIVE_DISCORD_MESSAGE Template with {title} and {url} for Discord go-live posts.
  DISCORD_LIVE_ANNOUNCE_CHANNEL_ID Optional. Fixed text channel id for go-live posts (else system/first writable).
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
  LUNA_COHOST_BANTER        If 1, idle Luna ↔ vampire co-host banter (vampire_cohost.py / luna_cohost_banter.py).
  LUNA_COHOST_NAME          Display name (default Viktor). LUNA_COHOST_VRM path (default aichris.vrm). LUNA_COHOST_EDGE_VOICE.
  LUNA_COHOST_CHAT_PERSONAS If 1 (with BANTER=1), auto-replies to Twitch / YouTube chat may be Luna or the co-host (see LUNA_COHOST_CHAT_SPEAKER).
  LUNA_COHOST_CHAT_SPEAKER  random (default) | luna | cohost | alternate — who speaks for chat auto-replies when CHAT_PERSONAS=1.
  LUNA_COHOST_CHAT_TWITCH_PREFIX  If 1 (default), Twitch chat replies from the co-host are prefixed [Name] when posting as the bot.
  LUNA_COHOST_IDLE_SEC      Quiet time before banter (default 90). LUNA_COHOST_MIN_GAP_SEC between exchanges (default 10).
  LUNA_COHOST_DYNAMICS      If 1 (default with BANTER), evolving Luna↔Viktor relationship notes in prompts (data/cohost_dynamics.json).
  LUNA_COHOST_DYNAMICS_LLM_EVERY  Re-summarize relationship with Ollama every N exchanges (default 10; 0=heuristics only).
  LUNA_SESSION_MODE         auto (default) | live | local — whether to frame replies as public broadcast vs local VRM / off-air rehearsal.
  LUNA_SESSION_NOTE         Optional freeform line injected into the dual-presence context (e.g. "Tonight: game X").
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
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from chat_ws import ChatHub, start_chat_ws_server, stop_chat_ws_server
from luna_tts import (
    maybe_speak,
    prewarm_edge_tts,
    set_selected_speaker,
    synthesize_playback_bundle,
    synthesize_reply_to_file,
    tts_enabled,
    tts_play_locally,
    tts_play_to_viewer,
    tts_play_target,
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
    fetch_video_context as yt_fetch_video_context,
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
from youtube_live_chat import (
    YouTubeLiveChatRunner,
    set_youtube_live_url,
    youtube_live_auto_reply_enabled,
    youtube_live_auto_trigger,
    youtube_live_chat_requested,
    youtube_live_check_probe_url,
    youtube_live_video_id,
)
from live_social_share import (
    live_social_share_enabled,
    live_watch_enabled,
    run_live_social_poller,
)
from luna_cohost_banter import run_cohost_banter_loop
from luna_cohost_dynamics import CohostDynamics, dynamics_enabled
from vampire_cohost import cohost_chat_personas_enabled, cohost_enabled
from social_playwright_share import (
    default_youtube_storage_path,
    generate_and_post_youtube_video_comment,
    post_youtube_video_comment,
    run_interactive_social_login,
    share_new_youtube_upload,
    social_playwright_configured,
    youtube_comment_posting_enabled,
    youtube_comment_posting_requested,
    youtube_comment_setup_hint,
)
from luna_creator import (
    cohost_replies_to_creator_enabled,
    creator_chat_system_block,
    creator_display_name,
    format_creator_user_line,
    is_creator_viewer_turn,
)
from luna_persona import build_luna_system_prompt
from luna_session_context import format_dual_presence_block
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
        self._twitch_channel_login = (channel or "").strip().lstrip("#").lower()
        self._youtube_live_active_cb: Callable[[], bool] | None = None
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
        self._latest_screen_frame_b64 = ""
        self._screen_summarize_task: asyncio.Task[None] | None = None
        # Server-side mic gate: while local TTS is playing (and briefly after),
        # reject viewer_voice packets so Luna cannot transcribe her own output.
        self._avatar_speaking = False
        self._last_avatar_speaking_end_ts = 0.0
        self._viewer_voice_block_after_tts_sec = max(
            0.0, float(os.environ.get("LUNA_VIEWER_VOICE_BLOCK_AFTER_TTS_SEC", "3.0").strip() or "3.0")
        )
        self._mic_ready_task: asyncio.Task[None] | None = None
        self._last_assistant_reply = ""
        self._last_activity_ts = time.monotonic()
        self._last_cohost_banter_ts = 0.0
        self._cohost_banter_active = False
        # Viewer checkbox: idle co-host uses open-ended full script vs short exchange (see luna_cohost_banter).
        self._cohost_idle_full_script = False
        self._viewer_tts_done = asyncio.Event()
        self._viewer_tts_done.set()
        # Luna/co-host alternation for TWITCH_AUTO_REPLY + LUNA_COHOST_CHAT_PERSONAS (see _cohost_for_chat_reply).
        self._chat_reply_alt_next_luna = True
        self._cohost_dynamics = CohostDynamics()
        from luna_cohost_scene import load_cohost_in_scene

        self._viewer_cohost_in_scene = load_cohost_in_scene(default=False)
        self._cohost_banter_task: asyncio.Task[None] | None = None
        if _env_truthy("LUNA_CHAT_MEMORY_RESET", default=False):
            self._memory.clear()
            self._persist_memory_to_disk()
            print("(memory) cleared (LUNA_CHAT_MEMORY_RESET=1)", flush=True)
        else:
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

    async def finish_viewer_tts(self) -> None:
        """Viewer finished playing ``tts_audio`` — release speaking gate + mic tail guard."""
        self._avatar_speaking = False
        self._last_avatar_speaking_end_ts = time.monotonic()
        self._viewer_tts_done.set()
        if self._chat_hub:
            await self._chat_hub.broadcast(
                {"type": "control", "name": "avatar_speaking", "value": False}
            )
            self._schedule_mic_ready_after_tts(self._chat_hub)

    def touch_activity(self) -> None:
        """Mark hub/chat/voice activity so co-host banter waits for a quiet moment."""
        self._last_activity_ts = time.monotonic()

    def cohost_idle_ready(self) -> bool:
        from vampire_cohost import cohost_enabled, cohost_idle_sec, cohost_min_gap_sec

        if not cohost_enabled():
            return False
        if self._cohost_banter_active or self._avatar_speaking:
            return False
        if not self._viewer_cohost_in_scene:
            return False
        now = time.monotonic()
        if now - self._last_activity_ts < cohost_idle_sec():
            return False
        if self._last_cohost_banter_ts > 0 and now - self._last_cohost_banter_ts < cohost_min_gap_sec():
            return False
        return True

    async def _wait_viewer_tts_done(self, timeout_sec: float) -> None:
        self._viewer_tts_done.clear()
        try:
            await asyncio.wait_for(self._viewer_tts_done.wait(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            self._viewer_tts_done.set()

    async def _dispatch_banter_line(
        self,
        speaker: str,
        text: str,
        *,
        cohost_display: str,
    ) -> None:
        """Play one line of Luna ↔ co-host banter in the viewer (dual voice)."""
        from vampire_cohost import cohost_edge_voice, cohost_vrm_viewer_url

        line = (text or "").strip()
        if not line or self._chat_hub is None:
            return
        if speaker == "cohost" and not self._viewer_cohost_in_scene:
            return
        is_luna = speaker == "luna"
        display = (self.nick or "Luna") if is_luna else cohost_display
        channel = "cohost"
        ts = int(time.time() * 1000)
        await self._chat_hub.broadcast(
            {
                "type": "assistant",
                "user": display,
                "text": line,
                "channel": channel,
                "ts": ts,
            }
        )
        if not tts_enabled() or not tts_play_to_viewer():
            return
        voice_override = None if is_luna else cohost_edge_voice()
        bundle = await asyncio.to_thread(
            synthesize_playback_bundle, line, voice=voice_override
        )
        if bundle is None:
            return
        await self._chat_hub.broadcast(
            {
                "type": "control",
                "name": "cohost_avatar",
                "active_speaker": "luna" if is_luna else "cohost",
            }
        )
        if is_luna:
            self._cancel_mic_ready_task()
            self._avatar_speaking = True
            await self._chat_hub.broadcast(
                {"type": "control", "name": "avatar_speaking", "value": True}
            )
        await self._chat_hub.broadcast(
            {
                "type": "control",
                "name": "avatar_emotion",
                "value": detect_avatar_emotion(line),
                "duration_ms": min(12_000, max(1_800, int(len(line) * 42))),
            }
        )
        payload: dict = {
            "type": "control",
            "name": "tts_audio",
            "mime": bundle.mime,
            "data": base64.b64encode(bundle.audio).decode("ascii"),
            "duration_ms": bundle.duration_ms,
            "visemes": bundle.visemes,
            "drive_avatar": True,
            "avatar": "luna" if is_luna else "cohost",
        }
        await self._chat_hub.broadcast(payload)
        wait = max(2.0, (bundle.duration_ms or 3000) / 1000.0 + 0.35)
        await self._wait_viewer_tts_done(wait)
        if is_luna:
            self._avatar_speaking = False
            self._last_avatar_speaking_end_ts = time.monotonic()
            await self._chat_hub.broadcast(
                {"type": "control", "name": "avatar_speaking", "value": False}
            )

    async def run_cohost_banter_exchange(self, *, full_conversation: bool = False) -> None:
        from luna_cohost_banter import _generate_banter_script_sync
        from vampire_cohost import (
            cohost_exchange_lines,
            cohost_full_banter_line_cap,
            cohost_name,
            cohost_vrm_viewer_url,
        )

        if self._cohost_banter_active:
            return
        if not self._viewer_cohost_in_scene:
            return
        name = cohost_name()
        self._cohost_banter_active = True
        self.touch_activity()
        try:
            if full_conversation:
                line_budget = cohost_full_banter_line_cap()
            else:
                line_budget = cohost_exchange_lines()
            async with self._ollama_lock:
                presence = self._dual_presence_context_block()
                dynamics = self._cohost_dynamics.block_for_banter()
                extra_ctx = "\n\n".join(x for x in (presence, dynamics) if x).strip()
                script = await asyncio.to_thread(
                    _generate_banter_script_sync,
                    model=self._chat_model,
                    luna_name=self.nick or "Luna",
                    cohost=name,
                    max_lines=line_budget,
                    full_conversation=full_conversation,
                    presence_block=extra_ctx,
                )
            if len(script) < 2:
                print("(cohost) script too short — skipped", flush=True)
                return
            mode = "open-ended full" if full_conversation else "short"
            print(
                f"(cohost) exchange ({len(script)} lines, {mode}) Luna ↔ {name}",
                flush=True,
            )
            if self._chat_hub:
                await self._chat_hub.broadcast(
                    {
                        "type": "status",
                        "text": f"Cohost banter: Luna ↔ {name}",
                    }
                )
            vrm_url = cohost_vrm_viewer_url()
            if vrm_url and self._chat_hub and self._viewer_cohost_in_scene:
                await self._chat_hub.broadcast(
                    {
                        "type": "control",
                        "name": "cohost_avatar",
                        "dual_layout": True,
                        "vrm_url": vrm_url,
                    }
                )
            elif not self._viewer_cohost_in_scene:
                print("(cohost) banter skipped — co-host dismissed (solo mode)", flush=True)
                return
            for spk, line in script:
                if not self._viewer_cohost_in_scene:
                    break
                if spk == "cohost" and not self._viewer_cohost_in_scene:
                    continue
                await self._dispatch_banter_line(spk, line, cohost_display=name)
            self._cohost_dynamics.observe_banter_script(script)
            if dynamics_enabled():
                asyncio.create_task(
                    self._maybe_refresh_cohost_dynamics(),
                    name="cohost-dynamics-refresh",
                )
            self._last_cohost_banter_ts = time.monotonic()
        finally:
            if self._chat_hub and self._viewer_cohost_in_scene:
                await self._chat_hub.broadcast(
                    {
                        "type": "control",
                        "name": "cohost_avatar",
                        "active_speaker": "luna",
                    }
                )
            self._cohost_banter_active = False
            self._cohost_banter_task = None
            self.touch_activity()

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

    def _screen_context_interval_sec(self) -> float:
        raw = (os.environ.get("LUNA_SCREEN_CONTEXT_INTERVAL_SEC") or "15").strip() or "15"
        try:
            sec = float(raw)
        except ValueError:
            sec = 15.0
        return max(5.0, min(sec, 300.0))

    async def ingest_viewer_screen_frame(self, image_b64: str) -> None:
        """Accept viewer JPEG frames (~1 FPS); run vision on the latest frame every N seconds."""
        raw = (os.environ.get("LUNA_SCREEN_CONTEXT", "1") or "1").strip().lower()
        if raw in ("0", "false", "no", "off"):
            return
        b64 = (image_b64 or "").strip()
        if not b64:
            return

        schedule = False
        frame = ""
        async with self._screen_context_lock:
            self._latest_screen_frame_b64 = b64
            if _env_truthy("LUNA_SCREEN_YIELD_TO_CHAT", default=True) and self._ollama_lock.locked():
                return
            now = time.time()
            if now - self._last_screen_summarize_ts < self._screen_context_interval_sec():
                return
            if self._screen_summarize_task is not None and not self._screen_summarize_task.done():
                return
            self._last_screen_summarize_ts = now
            frame = self._latest_screen_frame_b64
            schedule = bool(frame)

        if not schedule:
            return
        self._screen_summarize_task = asyncio.create_task(
            self._summarize_latest_screen_frame(frame),
            name="luna-screen-summarize",
        )

    async def _summarize_latest_screen_frame(self, image_b64: str) -> None:
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
            self.touch_activity()
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
                allow_cohost_persona=True,
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
        return self._mention_triggers_chat_reply(text)

    def _mention_triggers_chat_reply(self, text: str) -> bool:
        lowered = text.lower()
        if "luna" in lowered or "@luna" in lowered:
            return True
        if cohost_enabled():
            from vampire_cohost import cohost_name

            cn = cohost_name().lower()
            if cn and (cn in lowered or f"@{cn}" in lowered):
                return True
        return False

    def _should_auto_reply_youtube(self, text: str) -> bool:
        if not youtube_live_auto_reply_enabled():
            return False
        cleaned = (text or "").strip()
        if not cleaned or cleaned.startswith("!"):
            return False
        now = time.time()
        if now - self._last_auto_reply_ts < self._auto_cooldown_sec:
            return False
        if youtube_live_auto_trigger() == "all":
            return True
        return self._mention_triggers_chat_reply(cleaned)

    async def dismiss_cohost_from_viewer(self) -> None:
        """Viewer dismissed Viktor — stop banter/TTS pipeline until summoned again."""
        from luna_cohost_scene import save_cohost_in_scene

        self._viewer_cohost_in_scene = False
        save_cohost_in_scene(False)
        task = self._cohost_banter_task
        self._cohost_banter_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                print("(cohost) banter cancelled (dismissed)", flush=True)
            except Exception as exc:
                print(f"(cohost) banter cancel: {exc}", flush=True)
        self._cohost_banter_active = False
        self._avatar_speaking = False
        if self._chat_hub:
            await self._chat_hub.broadcast(
                {"type": "control", "name": "avatar_speaking", "value": False}
            )
            await self._chat_hub.broadcast(
                {
                    "type": "control",
                    "name": "cohost_avatar",
                    "active_speaker": "luna",
                }
            )

    def _cohost_for_chat_reply(self) -> bool:
        """Use the vampire co-host persona for this chat auto-reply (voice + system prompt)."""
        import random

        if not self._viewer_cohost_in_scene:
            return False
        if not cohost_chat_personas_enabled():
            return False
        mode = (os.environ.get("LUNA_COHOST_CHAT_SPEAKER") or "random").strip().lower()
        if mode in ("luna", "luna_only"):
            return False
        if mode in ("cohost", "viktor", "cohost_only", "vampire"):
            return True
        if mode == "alternate":
            use_luna = self._chat_reply_alt_next_luna
            self._chat_reply_alt_next_luna = not self._chat_reply_alt_next_luna
            return not use_luna
        return random.choice((True, False))

    def _cohost_chat_system(self) -> str:
        from vampire_cohost import build_vampire_system_prompt, cohost_name

        vn = cohost_name()
        luna_ctx = build_luna_system_prompt()
        parts = [
            f"You are {vn}, the vampire co-host on stream with Luna.\n\n",
            build_vampire_system_prompt(),
            f"\n\nLuna (your co-host — context only; never reply as Luna):\n{luna_ctx}\n\n",
            "A viewer sent a chat message. Reply in your voice only, as plain text for TTS. "
            "Keep it to one short paragraph or a few sentences unless they asked for more. "
            "Do not prefix with your name or a role tag.",
        ]
        return "".join(parts)

    def _cohost_off_stage_context_block(self) -> str:
        from vampire_cohost import cohost_enabled

        if not cohost_enabled() or self._viewer_cohost_in_scene:
            return ""
        from luna_cohost_scene import format_cohost_off_stage_block

        return format_cohost_off_stage_block()

    def _append_cohost_dynamics_to_system(self, system_content: str, *, as_cohost: bool) -> str:
        if not dynamics_enabled():
            return system_content
        block = (
            self._cohost_dynamics.block_for_viktor()
            if as_cohost
            else self._cohost_dynamics.block_for_luna()
        )
        if not block:
            return system_content
        return f"{system_content}\n\n{block}".strip() if system_content else block

    def _parse_dynamics_json(self, raw: str) -> dict | None:
        text = strip_think_blocks((raw or "").strip())
        if not text:
            return None
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            pass
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None

    async def _maybe_refresh_cohost_dynamics(self) -> None:
        if not self._cohost_dynamics.needs_llm_refresh():
            return
        recent = list(self._memory)[-12:]
        messages = self._cohost_dynamics.build_llm_refresh_messages(recent)
        try:
            async with self._ollama_lock:
                raw = await asyncio.to_thread(
                    chat_once,
                    self._ollama,
                    self._chat_model,
                    messages,
                    stream=False,
                )
            payload = self._parse_dynamics_json(raw)
            if payload:
                self._cohost_dynamics.apply_llm_refresh(payload)
        except Exception as exc:
            print(f"(cohost_dynamics) llm refresh failed: {exc}", flush=True)

    def _dual_presence_context_block(self) -> str:
        yt = False
        cb = self._youtube_live_active_cb
        if cb is not None:
            try:
                yt = bool(cb())
            except Exception:
                yt = False
        return format_dual_presence_block(
            twitch_channel=self._twitch_channel_login,
            youtube_live_listening=yt,
        )

    async def handle_youtube_live_chat(self, author: str, question: str, ts_ms: int) -> None:
        """YouTube Live chat → viewer panel + optional Luna reply (never posted to YouTube)."""
        self.touch_activity()
        source = "YouTube Live"
        if self._chat_hub:
            await self._chat_hub.broadcast(
                {
                    "type": "chat",
                    "user": author,
                    "text": question,
                    "channel": source,
                    "ts": ts_ms,
                }
            )
        if not self._should_auto_reply_youtube(question):
            return
        await self._generate_and_dispatch_reply(
            channel_name=source,
            author=author,
            question=question.strip(),
            send_to_twitch=False,
            source=source,
            local_speak=True,
            allow_cohost_persona=True,
        )

    async def _ollama_stream_to_hub(
        self,
        channel_name: str,
        messages: list[dict],
        *,
        assistant_display_name: str | None = None,
    ) -> str:
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
            u = (assistant_display_name or "").strip() or self.nick or "luna"
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
        allow_cohost_persona: bool = False,
        from_creator: bool = False,
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

        Set ``allow_cohost_persona=True`` for passive Twitch / YouTube *live*
        chat when ``LUNA_COHOST_CHAT_PERSONAS=1``, or creator viewer panel/voice
        when ``LUNA_COHOST_CREATOR_CHAT=1``. ``!ai`` stays Luna-only by default.

        Set ``from_creator=True`` (or use viewer panel/voice ``source``) so Luna
        and Viktor know the streamer is speaking directly.
        """
        is_creator = from_creator or is_creator_viewer_turn(source=source, author=author)
        display_author = creator_display_name() if is_creator else author

        vc_note = ""
        if discord_voice_channel:
            vc_note = (
                f" — speaker is currently in Discord voice channel {discord_voice_channel}"
            )
        if is_creator:
            user_line = format_creator_user_line(
                author=display_author, question=question, source=source
            )
            if vc_note:
                user_line = f"{user_line}{vc_note}"
        else:
            user_line = f"[{author} in {source}{vc_note}]: {question.strip()}"
        self.touch_activity()

        from vampire_cohost import cohost_name

        if is_creator and cohost_replies_to_creator_enabled():
            allow_cohost_persona = True

        as_cohost = bool(allow_cohost_persona and self._cohost_for_chat_reply())
        assistant_user = cohost_name() if as_cohost else (self.nick or "luna")

        messages: list[dict] = []
        if as_cohost:
            system_content = self._cohost_chat_system()
        else:
            system_content = self._system
        presence = self._dual_presence_context_block()
        if presence:
            system_content = (
                f"{system_content}\n\n{presence}".strip() if system_content else presence
            )
        off_stage = self._cohost_off_stage_context_block()
        if off_stage:
            system_content = (
                f"{system_content}\n\n{off_stage}".strip() if system_content else off_stage
            )
        system_content = self._append_cohost_dynamics_to_system(
            system_content, as_cohost=as_cohost
        )
        if is_creator:
            creator_block = creator_chat_system_block(name=display_author)
            system_content = (
                f"{system_content}\n\n{creator_block}".strip()
                if system_content
                else creator_block
            )
        self._remember_user_facts(display_author, source, question)
        user_memory = self._user_memory_block(display_author, source)
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
                reply = await self._ollama_stream_to_hub(
                    channel_name,
                    messages,
                    assistant_display_name=assistant_user,
                )
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
            mem_assistant = (
                f"[{cohost_name()}] {reply_stripped}" if as_cohost else reply_stripped
            )
            self._append_memory("assistant", mem_assistant)
        self._cohost_dynamics.observe_exchange(
            author=author,
            source=source,
            user_line=user_line,
            assistant_line=reply_stripped,
            speaker="cohost" if as_cohost else "luna",
        )
        if dynamics_enabled():
            asyncio.create_task(
                self._maybe_refresh_cohost_dynamics(),
                name="cohost-dynamics-refresh",
            )
        self._last_auto_reply_ts = time.time()

        twitch_out = reply_stripped
        if as_cohost and _env_truthy("LUNA_COHOST_CHAT_TWITCH_PREFIX", default=True):
            twitch_out = f"[{cohost_name()}] {reply_stripped}"

        if send_to_twitch and self._send_replies:
            for part in chunk_reply(twitch_out):
                # Send generated answer back to Twitch.
                channel = self.get_channel(channel_name) if channel_name else None
                if channel:
                    await channel.send(part[:500])

        if self._chat_hub:
            ts = int(time.time() * 1000)
            # Tell the viewer TTS is about to start *before* the assistant line so
            # the UI does not fire text-timed lip animation (luna-assistant-reply).
            if local_speak and tts_enabled() and not as_cohost:
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
                        "user": assistant_user,
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
            from vampire_cohost import cohost_edge_voice

            loop = asyncio.get_running_loop()
            viewer_only = tts_play_to_viewer() and not tts_play_locally()

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
                    pass

            try:
                if as_cohost:
                    if tts_play_to_viewer() and self._chat_hub:
                        await self._chat_hub.broadcast(
                            {
                                "type": "control",
                                "name": "cohost_avatar",
                                "active_speaker": "cohost",
                            }
                        )
                        bundle = await asyncio.to_thread(
                            synthesize_playback_bundle,
                            reply_stripped,
                            voice=cohost_edge_voice(),
                        )
                        if bundle is not None:
                            await self._chat_hub.broadcast(
                                {
                                    "type": "control",
                                    "name": "tts_audio",
                                    "mime": bundle.mime,
                                    "data": base64.b64encode(bundle.audio).decode("ascii"),
                                    "duration_ms": bundle.duration_ms,
                                    "visemes": bundle.visemes,
                                    "drive_avatar": True,
                                    "avatar": "cohost",
                                }
                            )
                    if tts_play_locally():
                        await asyncio.to_thread(
                            maybe_speak,
                            reply_stripped,
                            viseme_cb=_emit_viseme,
                            voice=cohost_edge_voice(),
                        )
                else:
                    if tts_play_to_viewer() and self._chat_hub:
                        bundle = await asyncio.to_thread(
                            synthesize_playback_bundle, reply_stripped
                        )
                        if bundle is not None:
                            await self._chat_hub.broadcast(
                                {
                                    "type": "control",
                                    "name": "tts_audio",
                                    "mime": bundle.mime,
                                    "data": base64.b64encode(bundle.audio).decode("ascii"),
                                    "duration_ms": bundle.duration_ms,
                                    "visemes": bundle.visemes,
                                }
                            )
                    if tts_play_locally():
                        await asyncio.to_thread(
                            maybe_speak, reply_stripped, viseme_cb=_emit_viseme
                        )
            finally:
                if not viewer_only and not as_cohost:
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
        self.touch_activity()
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
        if self._chat_hub:
            await self._chat_hub.broadcast(
                {
                    "type": "chat",
                    "user": author,
                    "text": f"Comment on this video: {url.strip()}",
                    "channel": channel_name,
                    "ts": int(time.time() * 1000),
                }
            )
        await self._broadcast_status(f"!explain ({author}): fetching video context…")
        ok, title, context, source = await asyncio.to_thread(yt_fetch_video_context, url)
        if not ok:
            await self._broadcast_status(f"!explain error: {context}")
            return
        cap = int(os.environ.get("LUNA_YT_TRANSCRIPT_MAX_CHARS", "4000").strip() or "4000")
        cap = max(800, cap)
        snippet = context if len(context) <= cap else context[: cap - 1] + "…"
        nice_title = title or url
        source_note = {
            "transcript": "captions/transcript",
            "subtitles": "subtitles",
            "vision+whisper": "vision (see) + Whisper (hear) combined",
            "vision": "vision model video description (no captions)",
            "whisper": "Whisper audio transcription (no captions)",
            "description": "video description (no captions on this upload)",
            "title": "title only (no captions or description)",
        }.get(source, "video metadata")
        await self._broadcast_status(f"!explain: using {source_note} as context.")
        question = (
            f"A viewer shared this YouTube video: {nice_title} ({url}). "
            f"Here is what we know from the {source_note}:\n\n"
            f"{snippet}\n\n"
            "React to it for the stream in 1-3 short sentences — give your honest take, "
            "highlight the most interesting part, and keep it natural for live chat."
        )
        reply = await self._generate_and_dispatch_reply(
            channel_name=channel_name or "panel",
            author=author,
            question=question,
            send_to_twitch=send_to_twitch,
        )

        if not youtube_comment_posting_requested():
            return

        use_stream_reply = (os.environ.get("LUNA_YT_COMMENT_USE_STREAM_REPLY") or "1").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )

        async def _post_public_yt_comment() -> None:
            if not youtube_comment_posting_enabled():
                await self._broadcast_status(youtube_comment_setup_hint())
                return
            await self._broadcast_status(
                "YouTube: launching Chrome to post comment (Playwright, like Facebook share)…"
            )
            stream_line = (reply or "").strip()
            if use_stream_reply and stream_line:
                ok_post, msg = await post_youtube_video_comment(
                    video_url=url.strip(),
                    comment=stream_line,
                )
            else:
                ok_post, msg = await generate_and_post_youtube_video_comment(
                    video_url=url.strip(),
                    title=nice_title,
                    transcript=snippet,
                    context_source=source_note,
                )
            await self._broadcast_status(msg if ok_post else f"YouTube comment: {msg}")

        asyncio.create_task(_post_public_yt_comment(), name="luna-youtube-comment-post")


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

    prompted_yt_stream_ids: set[str] = set()
    yt_runner = YouTubeLiveChatRunner()
    bot._youtube_live_active_cb = lambda: yt_runner.is_running

    async def _hub_status(text: str) -> None:
        if hub is not None:
            await hub.broadcast({"type": "status", "text": text})

    async def _on_youtube_live_chat(author: str, text: str, ts_ms: int) -> None:
        await bot.handle_youtube_live_chat(author, text, ts_ms)

    async def _on_yt_live_stopped() -> None:
        pass

    async def _prompt_youtube_live_url(item: dict[str, str], *, force: bool = False) -> None:
        sid = str(item.get("id") or "").strip()
        if not sid:
            return
        if yt_runner.is_running and yt_runner.active_video_id == sid:
            if hub is not None:
                await hub.broadcast(
                    {
                        "type": "status",
                        "text": f"YouTube Live chat (pytchat): already listening ({sid}).",
                    }
                )
            return
        if not force and sid in prompted_yt_stream_ids:
            return
        prompted_yt_stream_ids.add(sid)
        if hub is None:
            return
        await hub.broadcast(
            {
                "type": "control",
                "name": "youtube_live_prompt",
                "open": True,
                "title": str(item.get("title") or "YouTube Live"),
                "url": str(item.get("url") or ""),
                "stream_id": sid,
            }
        )

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

            if msg_type == "viewer_cohost_idle_full_script":
                bot._cohost_idle_full_script = payload.get("full") is True
                return

            if msg_type == "viewer_cohost_scene":
                from luna_cohost_scene import save_cohost_in_scene

                in_scene = payload.get("in_scene") is True
                if in_scene:
                    bot._viewer_cohost_in_scene = True
                    save_cohost_in_scene(True)
                else:
                    await bot.dismiss_cohost_from_viewer()
                if hub is not None:
                    label = "in scene" if bot._viewer_cohost_in_scene else "solo (Luna only)"
                    await hub.broadcast(
                        {"type": "status", "text": f"Co-host: {label}"},
                    )
                return

            if msg_type == "viewer_cohost_banter":
                if not cohost_enabled():
                    await hub.broadcast(
                        {
                            "type": "status",
                            "text": "Co-host banter is disabled (set LUNA_COHOST_BANTER=1 and restart bot).",
                        },
                    )
                    return
                if bot._cohost_banter_active:
                    await hub.broadcast(
                        {"type": "status", "text": "Co-host banter is already playing."},
                    )
                    return
                full_exc = payload.get("full") is True
                if not bot._viewer_cohost_in_scene:
                    await hub.broadcast(
                        {
                            "type": "status",
                            "text": "Summon the co-host first — banter is off while Luna is solo.",
                        },
                    )
                    return
                prev = bot._cohost_banter_task
                if prev is not None and not prev.done():
                    prev.cancel()
                bot._cohost_banter_task = asyncio.create_task(
                    bot.run_cohost_banter_exchange(full_conversation=full_exc),
                    name="luna-cohost-banter",
                )
                await hub.broadcast(
                    {
                        "type": "status",
                        "text": (
                            "Starting co-host banter (full exchange)…"
                            if full_exc
                            else "Starting co-host banter…"
                        ),
                    },
                )
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

            if msg_type == "viewer_youtube_live_check":
                if not youtube_live_chat_requested():
                    await hub.broadcast(
                        {
                            "type": "status",
                            "text": "YouTube Live chat off — set LUNA_YOUTUBE_LIVE_CHAT=1.",
                        },
                    )
                    return
                from live_social_share import probe_youtube_live

                url = youtube_live_check_probe_url()
                await hub.broadcast({"type": "status", "text": f"YouTube live: checking {url}…"})
                item = await asyncio.to_thread(probe_youtube_live, url)
                if not item:
                    await hub.broadcast(
                        {
                            "type": "status",
                            "text": "YouTube live: not detected on this channel (tap again after you go live).",
                        },
                    )
                    return
                await _prompt_youtube_live_url(item, force=True)
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
                                "then open **Settings → Social login** (X / Facebook): sign in in the first tab, **close that tab** "
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
                elif site_raw in ("youtube", "yt"):
                    site = "youtube"
                    env_key = "LUNA_SOCIAL_YOUTUBE_STORAGE_STATE"
                else:
                    site = "x"
                    env_key = "LUNA_SOCIAL_X_STORAGE_STATE"
                out_raw = str(payload.get("out_path") or os.environ.get(env_key) or "").strip()
                if not out_raw and site == "youtube":
                    out_raw = str(default_youtube_storage_path())
                if not out_raw:
                    await hub.broadcast(
                        {
                            "type": "status",
                            "text": f"Social login: set {env_key} in .env to the JSON path to create (e.g. D:/secrets/luna_x.json).",
                        }
                    )
                    return
                out_path = Path(out_raw).expanduser()
                if site == "youtube":
                    out_path.parent.mkdir(parents=True, exist_ok=True)

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

            if msg_type == "viewer_tts_ended":
                await bot.finish_viewer_tts()
                return

            if msg_type == "viewer_prompt":
                text = str(payload.get("text", "")).strip()
                if not text:
                    return
                creator = creator_display_name()
                await hub.broadcast(
                    {
                        "type": "chat",
                        "user": creator,
                        "text": text,
                        "channel": "panel",
                        "ts": int(time.time() * 1000),
                    }
                )
                await bot._generate_and_dispatch_reply(
                    channel_name="panel",
                    author=creator,
                    question=text,
                    send_to_twitch=False,
                    source="viewer panel",
                    from_creator=True,
                )
                return

            if msg_type == "viewer_youtube_live_url":
                url = str(payload.get("url") or "").strip()
                if not url:
                    await hub.broadcast(
                        {"type": "status", "text": "YouTube Live: paste a watch URL."},
                    )
                    return
                vid = set_youtube_live_url(url)
                if not vid:
                    await hub.broadcast(
                        {
                            "type": "status",
                            "text": "YouTube Live: use a YouTube watch, live, or youtu.be link.",
                        },
                    )
                    return
                await yt_runner.start(
                    video_id=vid,
                    on_chat=_on_youtube_live_chat,
                    broadcast_status=_hub_status,
                    on_stopped=_on_yt_live_stopped,
                )
                prompted_yt_stream_ids.add(vid)
                await hub.broadcast(
                    {
                        "type": "control",
                        "name": "youtube_live_prompt",
                        "open": False,
                    }
                )
                await hub.broadcast(
                    {
                        "type": "status",
                        "text": f"YouTube Live chat (pytchat): connected ({vid}).",
                    }
                )
                return

            if msg_type == "viewer_youtube_live_dismiss":
                sid = str(payload.get("stream_id") or "").strip()
                if sid:
                    prompted_yt_stream_ids.add(sid)
                await hub.broadcast(
                    {
                        "type": "control",
                        "name": "youtube_live_prompt",
                        "open": False,
                    }
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
                    bot.touch_activity()
                    creator = creator_display_name()
                    await hub.broadcast(
                        {
                            "type": "chat",
                            "user": creator,
                            "text": text,
                            "channel": "panel",
                            "ts": int(time.time() * 1000),
                        }
                    )
                    await bot._generate_and_dispatch_reply(
                        channel_name="panel",
                        author=creator,
                        question=text,
                        send_to_twitch=False,
                        source="viewer voice",
                        from_creator=True,
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
    live_social_task: asyncio.Task | None = None
    cohost_task: asyncio.Task | None = None
    if hub is not None:
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

        async def _social_playwright_live(title: str, stream_url: str) -> None:
            await _social_playwright_upload(title, stream_url)

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

        if youtube_live_chat_requested():
            if youtube_live_video_id():
                await yt_runner.start(
                    video_id=youtube_live_video_id(),
                    on_chat=_on_youtube_live_chat,
                    broadcast_status=_hub_status,
                    on_stopped=_on_yt_live_stopped,
                )

        if live_watch_enabled():

            async def _live_social_share_send(title: str, url: str) -> None:
                await _social_playwright_live(title, url)

            async def _discord_twitch_live_announce(text: str) -> None:
                if discord_bot_obj is None:
                    return
                dbot = discord_bot_obj.bot
                try:
                    await asyncio.wait_for(dbot.wait_until_ready(), timeout=180.0)
                except Exception as exc:
                    print(f"(discord live) wait_until_ready failed: {exc}", flush=True)
                    return
                n = await discord_bot_obj.announce_live_all_guilds(text)
                await _hub_status(f"Discord live announce: posted to {n} server(s).")

            live_social_task = asyncio.create_task(
                run_live_social_poller(
                    social_share_send=_live_social_share_send,
                    discord_live_send=_discord_twitch_live_announce,
                    broadcast_status=_hub_status,
                    twitch_bot=bot,
                    twitch_login=channel,
                ),
                name="luna-live-social-share",
            )

        if cohost_enabled():
            cohost_task = asyncio.create_task(
                run_cohost_banter_loop(bot),
                name="luna-cohost-banter",
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
        await yt_runner.stop()
        if live_social_task is not None:
            live_social_task.cancel()
            try:
                await live_social_task
            except (asyncio.CancelledError, Exception):
                pass
        if cohost_task is not None:
            cohost_task.cancel()
            try:
                await cohost_task
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
        default="",
        help="Optional extra system text prepended (persona comes from TWITCH_SYSTEM / LUNA_PERSONA / LUNA_VOICE_RULES).",
    )
    args = parser.parse_args()

    cli_system = args.system.strip()
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

    system = build_luna_system_prompt()
    if cli_system:
        system = f"{cli_system}\n\n{system}".strip() if system else cli_system

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
        f"LUNA_TTS={tts_enabled()} | LUNA_TTS_PLAY={tts_playback_enabled()} | "
        f"LUNA_TTS_PLAY_TARGET={tts_play_target()}",
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
