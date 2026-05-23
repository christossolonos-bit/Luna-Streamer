"""
Twitch chat -> Ollama (gemma4:e4b by default).

Uses Twitch IRC via twitchio. Messages must use a command prefix (default !ai / !luna)
so normal chat is not sent to the model.

Environment (or use CLI flags where noted):
  TWITCH_TOKEN   OAuth token, usually starting with oauth:
  TWITCH_CHANNEL Channel login to join (no #), e.g. mychannel
  OLLAMA_HOST    Optional, default http://127.0.0.1:11434
  OLLAMA_MODEL   Optional, default gemma4:e4b (also used for screen/YouTube vision)
  LUNA_LLM_PROVIDER  ollama (default) | openrouter — cloud chat via OpenRouter API
  OPENROUTER_API_KEY Required when LUNA_LLM_PROVIDER=openrouter (https://openrouter.ai/keys)
  LUNA_OPENROUTER_MODEL  e.g. qwen/qwen3-4b:free (chat; like local qwen3.5:4b)
  LUNA_OPENROUTER_MODEL_FALLBACKS  Comma list tried on 429 (default includes openrouter/free)
  LUNA_OPENROUTER_VISION_MODEL  e.g. qwen/qwen2.5-vl-3b-instruct:free for screen/YouTube
  OPENROUTER_HTTP_REFERER  Optional site URL (OpenRouter attribution)
  OPENROUTER_APP_TITLE     Optional app name header (default Luna Streamer)
  TWITCH_SEND_REPLIES  If "1", post model replies to chat (needs chat:write on token)
  TWITCH_AUTO_REPLY    If "1", generate replies from regular chat messages
  TWITCH_AUTO_TRIGGER  "all" (default: Luna replies even without @; Viktor only when named) or "mention"
  TWITCH_AUTO_COOLDOWN / LUNA_PUBLIC_CHAT_COOLDOWN_SEC  Seconds between public-chat replies (default 4).
  LUNA_YOUTUBE_LIVE_COOLDOWN_SEC  YouTube Live override (defaults to public chat cooldown).
  LUNA_TIKTOK_LIVE_COOLDOWN_SEC   TikTok Live override (defaults to public chat cooldown).
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
  LUNA_VIEWER_VOICE_BLOCK_AFTER_TTS_SEC  Seconds after TTS ends before mic STT (default 1.5; 0=off).
  LUNA_TTS_VIEWER_WAIT_MAX_SEC       Max seconds live chat blocks on viewer TTS (default 18).
  LUNA_CREATOR_TTS_BLOCK_UNTIL_DONE    If 1, panel/voice waits for TTS (default 0).
  LUNA_STT_LOCAL_MODEL  faster-whisper size (default tiny); LUNA_STT_LOCAL_DEVICE cpu|cuda (unset = auto GPU if available)
  LUNA_SPEAKER_ONLY  If 1, viewer mic clips must match the enrolled voice (see chat panel "Enroll my voice")
  LUNA_SPEAKER_MIN_SIM  Cosine similarity threshold for the speaker check (default 0.75)
  LUNA_SPEAKER_REF  Path to the enrolled reference WAV (default: <project>/speaker_ref.wav)
  LUNA_VOICE_GATE_MALE_ONLY  Coarse fallback: drop clips with median pitch above LUNA_VOICE_GATE_MAX_F0_HZ (only used if speaker gate is off)
  LUNA_VOICE_GATE_MAX_F0_HZ  Default 172 — median voiced F0 must be ≤ this (Hz) to count as “male” for the fallback gate
  LUNA_SCREEN_CONTEXT  If 0/false/off, ignore viewer_screen_frame (default on)
  LUNA_SCREEN_CONTEXT_INTERVAL_SEC  Min seconds between Ollama vision summaries (default 1; pair with viewer 1000ms upload)
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
  LUNA_SCREEN_KEEP_ALIVE         Vision-only keep_alive (default 2m; chat uses LUNA_OLLAMA_KEEP_ALIVE).
  LUNA_SCREEN_CAPTURE_INTERVAL_MS  Viewer JPEG upload interval (default 1000).
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
  LUNA_YOUTUBE_LIVE_CONVERSATIONAL If 1 (default), Luna/Viktor discuss with viewers; use thread context.
  LUNA_YOUTUBE_LIVE_BANTER_FROM_CHAT  If 1 (default), idle banter debriefs recent YouTube chat.
  LUNA_YOUTUBE_LIVE_SESSION_LINES  Rolling log size for YouTube context (default 48).
  LUNA_YOUTUBE_LIVE_CHECK_URL      Single @handle/live or watch URL for manual “check YouTube live” (default @Solonaras1/live).
  LUNA_YOUTUBE_LIVE_WATCH_POLL     If 1 (default when live chat on), probe CHECK_URL on an interval and auto-connect pytchat.
  Viewer dock “Check YouTube live” also probes TikTok (LUNA_TIKTOK_LIVE_CHAT) and connects TikTok chat when live.
  LUNA_YOUTUBE_LIVE_WATCH_POLL_SEC Probe interval in seconds (default 900 = 15 minutes).
  LUNA_YOUTUBE_LIVE_RECONNECT      If 1 (default), restart pytchat when the session drops mid-stream.
  LUNA_TIKTOK_LIVE_CHAT            If 1, read TikTok Live chat into the viewer (requires TikTokLive).
  LUNA_TIKTOK_LIVE_USERNAME        TikTok @handle to listen to (e.g. @solonaras).
  LUNA_TIKTOK_LIVE_AUTO_REPLY      If 1 (default), Luna/Viktor reply in viewer/TTS only.
  LUNA_TIKTOK_LIVE_AUTO_TRIGGER    mention | all (default all).
  LUNA_TIKTOK_LIVE_CONVERSATIONAL  If 1 (default), Luna/Viktor discuss with viewers; use thread context.
  LUNA_TIKTOK_LIVE_BANTER_FROM_CHAT  If 1 (default), idle banter debriefs recent TikTok chat.
  LUNA_TIKTOK_LIVE_SESSION_LINES   Rolling log size for TikTok context (default 48).
  LUNA_TIKTOK_LIVE_WATCH_POLL      If 1 (default when chat on), probe @handle and auto-connect when live.
  LUNA_TIKTOK_LIVE_WATCH_POLL_SEC  Probe interval in seconds (default 900).
  LUNA_TIKTOK_LIVE_RECONNECT       If 1 (default), reconnect after disconnects mid-stream (not when offline).
  LUNA_SOCIAL_LIVE_SHARE           If 1, post to X/Facebook when you go live on YouTube, TikTok, or Twitch (needs Playwright + storage).
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
  LUNA_DISCORD_VOICE_TTS_CHANNEL_IDS  Optional allowlist of voice channel ids for VC TTS (empty = any VC).
  LUNA_DISCORD_VOICE_TTS_PAD_SEC     Extra seconds after VC reply audio (default 1.5; like viewer pad).
  LUNA_DISCORD_GUILD_CHAT_CHANNELS  Per-server text channel allowlists (guild_id:channel_id, …).
  LUNA_DISCORD_CHAT_READ_BOTS  If 1, reply to other bots (must @Luna / say luna).
  LUNA_DISCORD_CHAT_BOT_IDS    Optional allowlist of bot user ids (empty = any bot except Luna herself).
  LUNA_DISCORD_WELCOME         If 1, post LUNA_DISCORD_WELCOME_MESSAGE when someone joins (Members intent).
  LUNA_DISCORD_WELCOME_CHANNEL_ID  Text channel for join welcomes.
  LUNA_DISCORD_WELCOME_GUILD_ID    Optional guild id filter.
  LUNA_COHOST_BANTER        If 1, idle Luna ↔ vampire co-host banter (vampire_cohost.py / luna_cohost_banter.py).
  LUNA_COHOST_NAME          Display name (default Viktor). LUNA_COHOST_VRM path (default aichris.vrm). LUNA_COHOST_EDGE_VOICE.
  LUNA_COHOST_CHAT_PERSONAS If 1 (with BANTER=1), auto-replies to Twitch / YouTube chat may be Luna or the co-host (see LUNA_COHOST_CHAT_SPEAKER).
  LUNA_COHOST_CHAT_SPEAKER  random (default) | luna | viktor | himari | cohost | alternate — who speaks when CHAT_PERSONAS=1 and no @name.
  LUNA_COHOST_CHAT_TWITCH_PREFIX  If 1 (default), Twitch chat replies from the co-host are prefixed [Name] when posting as the bot.
  LUNA_COHOST_AFTER_CHAT_SEC  Quiet after Twitch/YouTube chat before banter resumes (default 10).
  LUNA_COHOST_IDLE_SEC      Optional longer quiet before banter if set (default unused for resume; legacy 90).
  LUNA_COHOST_MIN_GAP_SEC   Minimum gap between banter exchanges (default 10).
  LUNA_COHOST_DYNAMICS      If 1 (default with BANTER), evolving Luna↔Viktor relationship notes in prompts (data/cohost_dynamics.json).
  LUNA_COHOST_DYNAMICS_LLM_EVERY  Re-summarize relationship with Ollama every N exchanges (default 10; 0=heuristics only).
  LUNA_CAST_CONSCIOUSNESS   If 1 (default with BANTER), rolling on-mic threads + inner monologue for Luna↔cast (data/cast_consciousness.json).
  LUNA_CAST_CONSCIOUSNESS_LLM_EVERY  Refresh thread topic / head notes with Ollama every N observes per partner (default 6; 0=heuristics only).
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
from luna_perf import (
    screen_context_interval_sec,
    screen_context_max_chars,
    viewer_perf_control_message,
)
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
    clear_youtube_live_stream,
    run_youtube_live_watch_poller,
    set_youtube_live_url,
    youtube_live_auto_reply_enabled,
    youtube_live_auto_trigger,
    youtube_live_chat_requested,
    youtube_live_check_probe_url,
    youtube_live_video_id,
    youtube_live_watch_poll_enabled,
)
from tiktok_live_chat import (
    TikTokLiveChatRunner,
    run_tiktok_live_watch_poller,
    tiktok_live_auto_reply_enabled,
    tiktok_live_auto_trigger,
    tiktok_live_chat_requested,
    tiktok_live_username,
    tiktok_live_watch_poll_enabled,
)
from live_social_share import (
    _load_state as live_social_load_state,
    complete_live_social_share,
    live_discord_channel_ids,
    skip_live_social_share,
    live_social_share_enabled,
    live_watch_enabled,
    run_live_social_poller,
)
from luna_cohost_banter import run_cohost_banter_loop
from luna_cast_consciousness import CastConsciousness, consciousness_enabled
from luna_cohost_dynamics import CohostDynamics, dynamics_enabled
from vampire_cohost import (
    cohost_chat_personas_enabled,
    cohost_enabled,
    cohost_name,
    twitch_message_addressees,
)
from social_playwright_share import (
    default_youtube_storage_path,
    generate_and_post_youtube_video_comment,
    post_youtube_video_comment,
    run_interactive_social_login,
    share_live_stream,
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
    creator_twitch_logins,
    format_creator_user_line,
    is_creator_viewer_turn,
)
from luna_twitch_user import (
    TwitchChatterProfile,
    creator_twitch_chat_system_block,
    format_creator_twitch_user_line,
    format_twitch_reply_to_chatter,
    is_creator_twitch_profile,
    live_chatter_system_note,
    profile_from_chatter,
    profile_from_login,
)
from luna_chat_safety import (
    chat_injection_guard_enabled,
    chat_injection_guard_system_block,
    scan_chat_prompt_injection,
)
from luna_persona import build_luna_system_prompt
from luna_session_context import format_dual_presence_block
from luna_youtube_live_session import (
    TikTokLiveSessionLog,
    YouTubeLiveSessionLog,
    tiktok_live_reply_style_block,
    youtube_live_reply_style_block,
)
from ollama_client import (
    ThinkStripper,
    build_client,
    build_vision_client,
    chat_once,
    chat_request_kwargs,
    configure_stdio_utf8,
    llm_provider,
    openrouter_configured,
    openrouter_streaming_enabled,
    resolve_chat_model,
    resolve_vision_model,
    vision_provider,
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


from luna_public_chat_cooldown import (
    live_chat_max_speakers_per_message,
    public_chat_cooldown_sec,
    tiktok_live_cooldown_sec,
    youtube_live_cooldown_sec,
)


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


def viewer_avatar_id(partner_id: str | None = None, *, speaker: str = "luna") -> str:
    """Map cast partner / banter speaker to viewer lip-sync target (``luna`` | ``cohost`` | ``himari``)."""
    if speaker == "luna":
        return "luna"
    if (partner_id or "").strip().lower() == "himari":
        return "himari"
    return "cohost"


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
        vision_ollama_client: Client | None = None,
    ) -> None:
        super().__init__(
            token=token,
            prefix="!",
            initial_channels=[channel],
        )
        self._discord = discord_bot
        self._ollama = ollama_client
        self._vision_ollama = vision_ollama_client or ollama_client
        self._model = model
        self._chat_model = resolve_chat_model()
        self._system = system_prompt.strip()
        self._twitch_channel_login = (channel or "").strip().lstrip("#").lower()
        self._youtube_live_active_cb: Callable[[], bool] | None = None
        self._tiktok_live_active_cb: Callable[[], bool] | None = None
        self._send_replies = send_replies
        self._auto_reply = auto_reply
        self._auto_trigger = auto_trigger
        self._auto_cooldown_sec = max(0.0, auto_cooldown_sec)
        self._youtube_cooldown_sec = youtube_live_cooldown_sec()
        self._tiktok_cooldown_sec = tiktok_live_cooldown_sec()
        self._last_auto_reply_ts = 0.0
        self._cohost_banter_blocked_until = 0.0
        self._public_chat_dedupe: dict[tuple[str, str, str], float] = {}
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
        self._chatter_session_counts: dict[str, int] = {}
        self._youtube_live_session = YouTubeLiveSessionLog()
        self._tiktok_live_session = TikTokLiveSessionLog()
        from luna_banter_novelty import get_banter_novelty_ledger

        self._banter_novelty = get_banter_novelty_ledger()
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
            0.0,
            float(
                os.environ.get("LUNA_VIEWER_VOICE_BLOCK_AFTER_TTS_SEC", "1.5").strip() or "1.5"
            ),
        )
        self._mic_ready_task: asyncio.Task[None] | None = None
        self._last_assistant_reply = ""
        self._last_activity_ts = time.monotonic()
        self._last_cohost_banter_ts = 0.0
        self._cohost_banter_active = False
        # Viewer checkbox: idle co-host uses open-ended full script vs short exchange (see luna_cohost_banter).
        self._cohost_idle_full_script = True
        self._viewer_tts_done = asyncio.Event()
        self._viewer_tts_done.set()
        self._viewer_tts_avatar: str = "luna"
        # Luna/co-host alternation for TWITCH_AUTO_REPLY + LUNA_COHOST_CHAT_PERSONAS (see _cohost_for_chat_reply).
        self._chat_reply_alt_next_luna = True
        self._cohost_dynamics = CohostDynamics()
        self._cast_consciousness = CastConsciousness()
        from luna_cast import load_cast_scene

        self._cast_scene = load_cast_scene(default_viktor=False)
        self._viewer_cohost_in_scene = self._cast_scene.any_in_scene()
        self._active_banter_partner: str | None = None
        self._cohost_banter_task: asyncio.Task[None] | None = None
        self._public_chat_reply_depth = 0
        # One public-chat reply (incl. viewer TTS) at a time — next message waits.
        self._public_chat_serial_lock = asyncio.Lock()
        if _env_truthy("LUNA_CHAT_MEMORY_RESET", default=False):
            self._memory.clear()
            self._persist_memory_to_disk()
            print("(memory) cleared (LUNA_CHAT_MEMORY_RESET=1)", flush=True)
        else:
            self._load_memory_from_disk()
        self._load_user_memory_from_disk()
        owner_logins = creator_twitch_logins()
        if owner_logins:
            print(
                f"(creator) Twitch owner logins: {', '.join(sorted(owner_logins))} "
                f"| display name: {creator_display_name()!r}",
                flush=True,
            )
        if llm_provider() == "openrouter":
            vp = vision_provider()
            if vp == "openrouter":
                print(
                    f"(llm) OpenRouter chat+vision={self._chat_model!r}",
                    flush=True,
                )
            else:
                print(
                    f"(llm) OpenRouter chat={self._chat_model!r} | "
                    f"Ollama vision={self._model!r} @ {os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434')}",
                    flush=True,
                )
        elif self._chat_model != self._model:
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

    def _public_chat_cooldown_sec_for(self, source: str) -> float:
        s = (source or "").strip().lower()
        if s == "youtube live":
            return self._youtube_cooldown_sec
        if s == "tiktok live":
            return self._tiktok_cooldown_sec
        return self._auto_cooldown_sec

    def _public_chat_on_cooldown(self, source: str) -> bool:
        sec = self._public_chat_cooldown_sec_for(source)
        if sec <= 0:
            return False
        return (time.time() - self._last_auto_reply_ts) < sec

    async def _wait_public_chat_cooldown(self, source: str = "Twitch chat") -> None:
        """Space out public-chat replies so back-to-back viewer lines do not stack."""
        sec = self._public_chat_cooldown_sec_for(source)
        if sec <= 0:
            return
        remaining = sec - (time.time() - self._last_auto_reply_ts)
        if remaining > 0:
            await asyncio.sleep(remaining)

    def _trim_public_chat_dedupe(self, max_age_sec: float) -> None:
        now = time.time()
        self._public_chat_dedupe = {
            k: ts for k, ts in self._public_chat_dedupe.items() if (now - ts) < max_age_sec
        }

    def _try_claim_public_chat_line(self, source: str, author: str, text: str) -> bool:
        """Drop duplicate live lines (same author + text within cooldown)."""
        body = (text or "").strip().lower()
        if not body:
            return False
        key = (source.strip().lower(), author.strip().lower(), body)
        sec = self._public_chat_cooldown_sec_for(source)
        now = time.time()
        self._trim_public_chat_dedupe(max(sec * 4, 30.0))
        last = self._public_chat_dedupe.get(key)
        if last is not None and sec > 0 and (now - last) < sec:
            return False
        self._public_chat_dedupe[key] = now
        return True

    def _cap_public_chat_addressees(self, source: str, addressees: list[str]) -> list[str]:
        cap = live_chat_max_speakers_per_message(source)
        if cap <= 0 or len(addressees) <= cap:
            return addressees
        kept = addressees[:cap]
        dropped = addressees[cap:]
        print(
            f"(chat) {source}: capped to {kept[0]!r} "
            f"(also named: {', '.join(dropped)}) — set LUNA_LIVE_CHAT_MAX_SPEAKERS_PER_MESSAGE>1 to allow all",
            flush=True,
        )
        return kept

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
            avatar = (self._viewer_tts_avatar or "luna").strip().lower()
            await self._chat_hub.broadcast(
                {
                    "type": "control",
                    "name": "avatar_speaking",
                    "value": False,
                    "avatar": avatar,
                }
            )
            if avatar == "luna":
                self._schedule_mic_ready_after_tts(self._chat_hub)

    def touch_activity(self) -> None:
        """Mark hub/chat/voice activity so co-host banter waits for a quiet moment."""
        self._last_activity_ts = time.monotonic()

    def public_chat_reply_priority_busy(self) -> bool:
        """Twitch / YouTube live auto-reply in progress — banter must wait."""
        return self._public_chat_reply_depth > 0

    async def _stop_cohost_banter_for_chat(self) -> None:
        """End Luna↔Viktor banter when chat needs the floor; never cut viewer TTS for a user reply."""
        task = self._cohost_banter_task
        stopping_banter = self._cohost_banter_active or (
            task is not None and not task.done()
        )
        if not stopping_banter:
            return
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                print(f"(cohost) banter cancel: {exc}", flush=True)
        self._cohost_banter_active = False
        if self._chat_hub is not None:
            await self._chat_hub.broadcast({"type": "control", "name": "stop_tts"})
        print("(cohost) banter stopped for chat", flush=True)

    async def begin_public_chat_reply_priority(self) -> None:
        """Public chat reply — banter must not run in parallel."""
        self._public_chat_reply_depth += 1
        self.touch_activity()
        await self._stop_cohost_banter_for_chat()

    def end_public_chat_reply_priority(self) -> None:
        self._public_chat_reply_depth = max(0, self._public_chat_reply_depth - 1)
        self.touch_activity()

    def _sync_cast_scene_flags(self, scene=None) -> None:
        from luna_cast import load_cast_scene

        self._cast_scene = scene if scene is not None else load_cast_scene()
        self._viewer_cohost_in_scene = self._cast_scene.any_in_scene()

    async def _broadcast_avatar_thinking(self, partner: str, active: bool) -> None:
        """Viewer VRMA (``thinking.vrma``) while the LLM composes a reply."""
        pid = (partner or "").strip().lower()
        if pid in ("viktor", "cohost"):
            if not self._cast_scene.viktor_in_scene:
                return
            avatar = "cohost"
        elif pid == "himari":
            if not self._cast_scene.himari_in_scene:
                return
            avatar = "himari"
        elif pid == "luna":
            avatar = "luna"
        else:
            return
        if self._chat_hub is None:
            return
        await self._chat_hub.broadcast(
            {
                "type": "control",
                "name": "avatar_thinking",
                "avatar": avatar,
                "value": bool(active),
            }
        )

    async def _broadcast_cast_thinking(self, active: bool) -> None:
        """Only Luna shows thinking while shared LLM runs (avoids synced VRMA poses)."""
        await self._broadcast_avatar_thinking("luna", active)

    def cohost_idle_ready(self) -> bool:
        from vampire_cohost import (
            cohost_after_chat_sec,
            cohost_banter_fail_backoff_sec,
            cohost_enabled,
            cohost_min_gap_sec,
        )

        if not cohost_enabled():
            return False
        if self.public_chat_reply_priority_busy():
            return False
        if self._cohost_banter_active or self._avatar_speaking:
            return False
        if not self._cast_scene.idle_partner_ids():
            return False
        now = time.monotonic()
        if now < self._cohost_banter_blocked_until:
            return False
        if now - self._last_activity_ts < cohost_after_chat_sec():
            return False
        if self._last_cohost_banter_ts > 0 and now - self._last_cohost_banter_ts < cohost_min_gap_sec():
            return False
        return True

    def _block_cohost_banter_after_fail(self, *, got_lines: int, need_lines: int) -> None:
        from vampire_cohost import cohost_banter_fail_backoff_sec

        backoff = cohost_banter_fail_backoff_sec()
        self._cohost_banter_blocked_until = time.monotonic() + backoff
        print(
            f"(cohost) script too short ({got_lines}/{need_lines} lines) — "
            f"idle banter pauses {int(backoff)}s (model must use LUNA: / VIKTOR: / HIMARI: lines). "
            f"Set LUNA_COHOST_BANTER=0 to disable, or turn off “full conversation” in the viewer dock.",
            flush=True,
        )

    def _viewer_tts_wait_max_sec(self) -> float:
        raw = (os.environ.get("LUNA_TTS_VIEWER_WAIT_MAX_SEC") or "18").strip() or "18"
        try:
            cap = float(raw)
        except ValueError:
            cap = 18.0
        return max(4.0, min(cap, 120.0))

    def _creator_tts_blocks_until_done(self) -> bool:
        return _env_truthy("LUNA_CREATOR_TTS_BLOCK_UNTIL_DONE", default=False)

    def _viewer_tts_wait_seconds(self, bundle: object, text: str) -> float:
        pad = float(os.environ.get("LUNA_TTS_VIEWER_WAIT_PAD_SEC", "1.5").strip() or "1.5")
        dur_ms = int(getattr(bundle, "duration_ms", 0) or 0)
        audio_sec = max(0.0, dur_ms / 1000.0)
        char_est = len((text or "").strip()) * 0.07
        est = max(3.0, audio_sec + pad, char_est + 1.0)
        return min(self._viewer_tts_wait_max_sec(), est)

    async def _wait_viewer_tts_done(self, timeout_sec: float) -> None:
        self._viewer_tts_done.clear()
        try:
            await asyncio.wait_for(self._viewer_tts_done.wait(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            print(
                f"(tts) viewer playback wait timed out after {timeout_sec:.1f}s — releasing gate",
                flush=True,
            )
            await self.finish_viewer_tts()

    async def _emit_viewer_tts(
        self,
        bundle: "TtsPlaybackBundle",
        *,
        reply_text: str,
        extra: dict | None = None,
        block_until_done: bool = True,
    ) -> bool:
        """Send ``tts_audio`` to the viewer; optionally block until playback finishes."""
        if self._chat_hub is None or bundle is None:
            return False
        payload: dict = {
            "type": "control",
            "name": "tts_audio",
            "mime": bundle.mime,
            "data": base64.b64encode(bundle.audio).decode("ascii"),
            "duration_ms": bundle.duration_ms,
            "visemes": bundle.visemes,
            "drive_avatar": True,
        }
        if extra:
            payload.update(extra)
        avatar = str(payload.get("avatar") or "luna").strip().lower()
        if avatar in ("luna", "cohost", "himari"):
            self._viewer_tts_avatar = avatar
        await self._chat_hub.broadcast(payload)
        if not block_until_done:
            return True
        wait = self._viewer_tts_wait_seconds(bundle, reply_text)
        await self._wait_viewer_tts_done(wait)
        return True

    async def _emit_viewer_tts_and_wait(
        self,
        bundle: "TtsPlaybackBundle",
        *,
        reply_text: str,
        extra: dict | None = None,
    ) -> bool:
        return await self._emit_viewer_tts(
            bundle, reply_text=reply_text, extra=extra, block_until_done=True
        )

    async def _broadcast_cast_on_viewer_for_banter(
        self,
        partner_ids: list[str],
        *,
        trio: bool = False,
    ) -> None:
        """Ensure summoned co-hosts are visible in the viewer before banter TTS."""
        from luna_cast import partner_vrm_viewer_url

        if not self._chat_hub:
            return
        viktor_url = (
            partner_vrm_viewer_url("viktor") if "viktor" in partner_ids else ""
        )
        himari_url = (
            partner_vrm_viewer_url("himari") if "himari" in partner_ids else ""
        )
        if trio and viktor_url:
            payload: dict = {
                "type": "control",
                "name": "cohost_avatar",
                "dual_layout": True,
                "trio_layout": True,
                "vrm_url": viktor_url,
            }
            if himari_url:
                payload["himari_vrm_url"] = himari_url
            await self._chat_hub.broadcast(payload)
        elif "viktor" in partner_ids and viktor_url:
            await self._chat_hub.broadcast(
                {
                    "type": "control",
                    "name": "cohost_avatar",
                    "dual_layout": True,
                    "vrm_url": viktor_url,
                }
            )

    async def _dispatch_banter_line(
        self,
        speaker: str,
        text: str,
        *,
        cohost_display: str,
        partner_id: str | None = None,
    ) -> None:
        """Play one banter line (luna | viktor | himari) in the viewer."""
        from luna_cast import partner_display_name, partner_edge_voice

        if self.public_chat_reply_priority_busy():
            return
        line = (text or "").strip()
        spk = (speaker or "").strip().lower()
        if spk == "himari" or (partner_id or "").strip().lower() == "himari":
            from himari_cohost import himari_banter_line_broken, sanitize_himari_speech_text

            line = sanitize_himari_speech_text(line)
            if himari_banter_line_broken(line):
                print("(cohost) Himari banter line unusable after sanitize — skipped", flush=True)
                return
        if not line or self._chat_hub is None:
            return
        is_luna = spk == "luna"
        pid = (
            (partner_id or spk or self._active_banter_partner or "viktor")
            .strip()
            .lower()
        )
        if not is_luna:
            if pid not in ("viktor", "himari"):
                pid = (self._active_banter_partner or "viktor").strip().lower()
            if pid == "himari" and not self._cast_scene.himari_in_scene:
                return
            if pid == "viktor" and not self._cast_scene.viktor_in_scene:
                return
        display = (self.nick or "Luna") if is_luna else (
            cohost_display or partner_display_name(pid)
        )
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
        voice_override = None if is_luna else partner_edge_voice(pid)
        bundle = await asyncio.to_thread(
            synthesize_playback_bundle, line, voice=voice_override
        )
        if bundle is None:
            return
        banter_avatar = viewer_avatar_id(pid, speaker=speaker)
        cohost_payload: dict = {
            "type": "control",
            "name": "cohost_avatar",
            "active_speaker": "luna" if is_luna else banter_avatar,
        }
        if not is_luna:
            from luna_cast import partner_vrm_viewer_url

            vrm_url = partner_vrm_viewer_url(pid)
            if vrm_url:
                cohost_payload["vrm_url"] = vrm_url
        await self._chat_hub.broadcast(cohost_payload)
        if is_luna:
            self._cancel_mic_ready_task()
        self._avatar_speaking = True
        await self._chat_hub.broadcast(
            {
                "type": "control",
                "name": "avatar_speaking",
                "value": True,
                "avatar": banter_avatar,
            }
        )
        await self._chat_hub.broadcast(
            {
                "type": "control",
                "name": "avatar_emotion",
                "value": detect_avatar_emotion(line),
                "duration_ms": min(12_000, max(1_800, int(len(line) * 42))),
                "avatar": banter_avatar,
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
            "avatar": banter_avatar,
        }
        await self._chat_hub.broadcast(payload)
        wait = self._viewer_tts_wait_seconds(bundle, line)
        await self._wait_viewer_tts_done(wait)
        self._avatar_speaking = False
        self._last_avatar_speaking_end_ts = time.monotonic()
        await self._chat_hub.broadcast(
            {
                "type": "control",
                "name": "avatar_speaking",
                "value": False,
                "avatar": banter_avatar,
            }
        )

    async def run_cohost_banter_exchange(self, *, full_conversation: bool = False) -> None:
        from luna_cast import (
            choose_idle_banter_partner_sync,
            partner_display_name,
            save_last_idle_partner,
        )
        from luna_banter_novelty import banter_novelty_strict_on_tiktok
        from luna_cohost_banter import generate_banter_script_with_novelty
        from vampire_cohost import (
            cohost_exchange_lines,
            cohost_full_banter_line_cap,
        )

        if self._cohost_banter_active:
            return
        partner_ids = self._cast_scene.idle_partner_ids()
        if not partner_ids:
            return
        trio = self._cast_scene.trio_on_stage()
        partner = partner_ids[0]
        if not trio:
            if len(partner_ids) == 1:
                partner = partner_ids[0]
            else:
                async with self._ollama_lock:
                    partner = await asyncio.to_thread(
                        choose_idle_banter_partner_sync,
                        model=self._chat_model,
                        luna_name=self.nick or "Luna",
                        scene=self._cast_scene,
                        recent_memory=list(self._memory),
                    )
            if not partner:
                return
            save_last_idle_partner(partner)
        self._active_banter_partner = partner if not trio else "viktor"
        viktor_name = partner_display_name("viktor")
        himari_name = partner_display_name("himari")
        duo_name = partner_display_name(partner) if not trio else ""
        self._cohost_banter_active = True
        self.touch_activity()
        played: list[tuple[str, str]] = []
        try:
            if full_conversation:
                line_budget = cohost_full_banter_line_cap()
            else:
                line_budget = cohost_exchange_lines()
            if trio:
                line_budget = max(line_budget, cohost_exchange_lines() * 2)
            min_lines = 3 if trio else 2
            script: list[tuple[str, str]] = []
            await self._broadcast_cast_thinking(True)
            try:
                async with self._ollama_lock:
                    presence = self._dual_presence_context_block()
                    dynamics = self._cohost_dynamics.block_for_banter()
                    if trio:
                        consciousness = self._cast_consciousness.block_for_trio_banter(
                            viktor_name=viktor_name,
                            himari_name=himari_name,
                        )
                        cast_label = f"{viktor_name} and {himari_name}"
                        yt_banter = self._youtube_live_session.block_for_banter(
                            cohost_name=cast_label
                        )
                        tt_banter = self._tiktok_live_session.block_for_banter(
                            cohost_name=cast_label
                        )
                    else:
                        consciousness = self._cast_consciousness.block_for_banter(
                            partner, cohost_name=duo_name
                        )
                        yt_banter = self._youtube_live_session.block_for_banter(
                            cohost_name=duo_name
                        )
                        tt_banter = self._tiktok_live_session.block_for_banter(
                            cohost_name=duo_name
                        )
                    extra_ctx = "\n\n".join(
                        x for x in (presence, dynamics, yt_banter, tt_banter) if x
                    ).strip()
                    strict_novelty = banter_novelty_strict_on_tiktok() and self._tiktok_live_listening()
                    script = await asyncio.to_thread(
                        generate_banter_script_with_novelty,
                        model=self._chat_model,
                        luna_name=self.nick or "Luna",
                        trio=trio,
                        ledger=self._banter_novelty,
                        strict_novelty=strict_novelty,
                        max_lines=line_budget,
                        full_conversation=full_conversation,
                        presence_block=extra_ctx,
                        consciousness_block=consciousness,
                        cohost=duo_name,
                        partner_id=partner,
                        viktor_name=viktor_name,
                        himari_name=himari_name,
                        min_lines=min_lines,
                    )
                    overlaps = self._banter_novelty.count_overlaps(script)
                    if overlaps >= 2:
                        print(
                            f"(banter_novelty) warning: {overlaps} lines still near recent banter",
                            flush=True,
                        )
            finally:
                await self._broadcast_cast_thinking(False)
            if len(script) < min_lines:
                self._block_cohost_banter_after_fail(
                    got_lines=len(script),
                    need_lines=min_lines,
                )
                return
            mode = "open-ended full" if full_conversation else "short"
            if trio:
                print(
                    f"(cohost) trio exchange ({len(script)} lines, {mode}) "
                    f"Luna + {viktor_name} + {himari_name}",
                    flush=True,
                )
                status_label = f"Luna + {viktor_name} + {himari_name}"
            else:
                print(
                    f"(cohost) exchange ({len(script)} lines, {mode}) Luna ↔ {duo_name}",
                    flush=True,
                )
                status_label = f"Luna ↔ {duo_name}"
            if self._chat_hub:
                await self._chat_hub.broadcast(
                    {
                        "type": "status",
                        "text": f"Cast banter: {status_label}",
                    }
                )
            on_stage = set(self._cast_scene.idle_partner_ids())
            if not on_stage:
                print("(cohost) banter skipped — cast left the stage", flush=True)
                return
            await self._broadcast_cast_on_viewer_for_banter(
                list(on_stage),
                trio=trio,
            )
            for spk, line in script:
                if on_stage != set(self._cast_scene.idle_partner_ids()):
                    break
                if self.public_chat_reply_priority_busy():
                    print("(cohost) banter yielding — chat reply in progress", flush=True)
                    break
                if spk not in ("luna", *on_stage):
                    continue
                pname = (
                    partner_display_name(spk)
                    if spk in ("viktor", "himari")
                    else (self.nick or "Luna")
                )
                await self._dispatch_banter_line(
                    spk,
                    line,
                    cohost_display=pname,
                    partner_id=spk if spk != "luna" else None,
                )
                if self.public_chat_reply_priority_busy():
                    print("(cohost) banter yielding — chat took priority", flush=True)
                    break
                played.append((spk, line))
            if played:
                self._banter_novelty.record_script(played)
                if trio:
                    self._cast_consciousness.observe_trio_banter_script(played)
                    viktor_lines = [
                        ("luna" if s == "luna" else "cohost", t)
                        for s, t in played
                        if s in ("luna", "viktor")
                    ]
                    if viktor_lines:
                        self._cohost_dynamics.observe_banter_script(viktor_lines)
                else:
                    self._cast_consciousness.observe_banter_script(partner, played)
                    if partner == "viktor":
                        self._cohost_dynamics.observe_banter_script(played)
            if dynamics_enabled():
                asyncio.create_task(
                    self._maybe_refresh_cohost_dynamics(),
                    name="cohost-dynamics-refresh",
                )
            if consciousness_enabled():
                if trio:
                    for pid in ("viktor", "himari"):
                        asyncio.create_task(
                            self._maybe_refresh_cast_consciousness(pid),
                            name=f"cast-consciousness-refresh-{pid}",
                        )
                else:
                    asyncio.create_task(
                        self._maybe_refresh_cast_consciousness(partner),
                        name="cast-consciousness-refresh",
                    )
            self._last_cohost_banter_ts = time.monotonic()
        except asyncio.CancelledError:
            print("(cohost) banter cancelled (chat or dismissed)", flush=True)
            raise
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

    def _register_twitch_chatter(self, profile: TwitchChatterProfile) -> None:
        """Track each Twitch chatter this session (display name + visit count)."""
        login = (profile.login or "").strip().lower()
        if not login or login == "unknown":
            return
        self._chatter_session_counts[login] = self._chatter_session_counts.get(login, 0) + 1
        key = self._user_memory_key(profile.login, "Twitch chat")
        if not key:
            return
        disp = profile.address_name()
        if not disp:
            return
        disp_fact = f"display: {disp}"
        bucket = [f for f in self._user_facts.get(key, []) if not f.startswith("display:")]
        bucket.append(disp_fact)
        if len(bucket) > self._user_facts_max_per_user:
            bucket = bucket[-self._user_facts_max_per_user :]
        self._user_facts[key] = bucket
        self._persist_user_memory_to_disk()

    def _chatter_session_stats(self, profile: TwitchChatterProfile) -> tuple[int, bool]:
        login = (profile.login or "").strip().lower()
        count = max(1, self._chatter_session_counts.get(login, 1))
        key = f"twitch:{login}"
        returning = count > 1 or bool(self._user_facts.get(key))
        return count, returning

    def _register_youtube_chatter(self, profile: TwitchChatterProfile) -> None:
        login = (profile.login or "").strip().lower()
        if not login or login == "unknown":
            return
        key = f"yt:{login}"
        self._chatter_session_counts[key] = self._chatter_session_counts.get(key, 0) + 1

    def _youtube_session_stats(self, profile: TwitchChatterProfile) -> tuple[int, bool]:
        login = (profile.login or "").strip().lower()
        key = f"yt:{login}"
        count = max(1, self._chatter_session_counts.get(key, 1))
        mem_key = self._user_memory_key(profile.login, "YouTube Live")
        returning = count > 1 or bool(self._user_facts.get(mem_key))
        return count, returning

    def _register_tiktok_chatter(self, profile: TwitchChatterProfile) -> None:
        login = (profile.login or "").strip().lower()
        if not login or login == "unknown":
            return
        key = f"tt:{login}"
        self._chatter_session_counts[key] = self._chatter_session_counts.get(key, 0) + 1

    def _tiktok_session_stats(self, profile: TwitchChatterProfile) -> tuple[int, bool]:
        login = (profile.login or "").strip().lower()
        key = f"tt:{login}"
        count = max(1, self._chatter_session_counts.get(key, 1))
        mem_key = self._user_memory_key(profile.login, "TikTok Live")
        returning = count > 1 or bool(self._user_facts.get(mem_key))
        return count, returning

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

    def _user_memory_block(
        self, author: str, source: str, *, spoken_name: str | None = None
    ) -> str:
        key = self._user_memory_key(author, source)
        if not key:
            return ""
        facts = self._user_facts.get(key, [])
        if not facts:
            return ""
        label = (spoken_name or author).strip() or author
        speaker = f"{source}:{author} ({label})"
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
        return screen_context_interval_sec(sec)

    async def ingest_viewer_screen_frame(self, image_b64: str) -> None:
        """Accept viewer JPEG frames (~1/sec); run vision on the latest frame every N seconds (default 1)."""
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
            now = time.monotonic()
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
        vision_model = resolve_vision_model() or self._model
        try:
            summary = await asyncio.to_thread(
                summarize_viewer_screen,
                self._vision_ollama,
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
        max_chars = screen_context_max_chars()
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

    async def _prompt_live_social_title(self, item: dict[str, str]) -> None:
        if self._chat_hub is None:
            return
        await self._chat_hub.broadcast(
            {
                "type": "control",
                "name": "live_social_title_prompt",
                "open": True,
                "platform": str(item.get("platform") or "live"),
                "suggested_title": str(item.get("suggested_title") or ""),
                "url": str(item.get("url") or ""),
                "stream_id": str(item.get("stream_id") or item.get("id") or ""),
            }
        )

    async def event_message(self, message: Message) -> None:
        if message.echo:
            return
        if not message.content:
            return
        self.touch_activity()
        await self._stop_cohost_banter_for_chat()
        profile = (
            profile_from_chatter(message.author)
            if message.author
            else profile_from_login("unknown")
        )
        self._register_twitch_chatter(profile)
        if self._chat_hub:
            ch = message.channel.name if message.channel else ""
            ts = int(message.timestamp.timestamp() * 1000)
            text = message.content or ""
            await self._chat_hub.broadcast(
                {
                    "type": "chat",
                    "user": profile.display_name,
                    "text": text,
                    "channel": ch,
                    "ts": ts,
                }
            )
        await self.handle_commands(message)
        if self._should_auto_reply(message):
            await self._dispatch_twitch_chat_replies(message)

    async def _dispatch_twitch_chat_replies(self, message: Message) -> None:
        """One Twitch line; Luna and/or cast partners each reply when named."""
        text = (message.content or "").strip()
        if not text:
            return
        profile = (
            profile_from_chatter(message.author)
            if message.author
            else profile_from_login("unknown")
        )
        author = profile.login
        channel = message.channel.name if message.channel else ""
        addressees = twitch_message_addressees(
            text, trigger_all=self._auto_trigger == "all"
        )
        if not addressees:
            return
        source = "Twitch chat"
        if not self._try_claim_public_chat_line(source, author, text):
            return
        addressees = self._cap_public_chat_addressees(source, addressees)
        if len(addressees) > 1:
            print(
                f"(chat) Twitch → {author}: "
                f"{' then '.join(addressees)} reply separately",
                flush=True,
            )
        print(f"\n--- Twitch /{channel} {author}: {text.strip()}", flush=True)
        async with self._public_chat_serial_lock:
            await self.begin_public_chat_reply_priority()
            try:
                await self._wait_public_chat_cooldown(source)
                for i, speaker in enumerate(addressees):
                    if i > 0:
                        await self._wait_public_chat_cooldown(source)
                    await self._generate_and_dispatch_reply(
                        channel_name=channel,
                        author=author,
                        question=text,
                        send_to_twitch=True,
                        source=source,
                        allow_cohost_persona=True,
                        force_speaker=speaker,
                        record_user_memory=(i == 0),
                        update_auto_reply_cooldown=True,
                        chatter_profile=profile,
                        log_incoming_chat=False,
                    )
            finally:
                self.end_public_chat_reply_priority()

    def _should_auto_reply(self, message: Message) -> bool:
        if not self._auto_reply:
            return False
        text = (message.content or "").strip()
        if not text:
            return False
        if text.startswith("!"):
            return False
        if self._public_chat_on_cooldown("Twitch chat"):
            return False
        addressees = twitch_message_addressees(
            text, trigger_all=self._auto_trigger == "all"
        )
        return bool(addressees)

    def _mention_triggers_chat_reply(self, text: str) -> bool:
        from luna_cast import public_chat_addressees

        return bool(public_chat_addressees(text, trigger_all=False))

    def _should_auto_reply_youtube(self, text: str) -> bool:
        if not youtube_live_auto_reply_enabled():
            return False
        cleaned = (text or "").strip()
        if not cleaned or cleaned.startswith("!"):
            return False
        if self._public_chat_on_cooldown("YouTube Live"):
            return False
        if youtube_live_auto_trigger() == "all":
            return True
        return bool(
            twitch_message_addressees(
                cleaned, trigger_all=youtube_live_auto_trigger() == "all"
            )
        )

    def _should_auto_reply_tiktok(self, text: str) -> bool:
        if not tiktok_live_auto_reply_enabled():
            return False
        cleaned = (text or "").strip()
        if not cleaned or cleaned.startswith("!"):
            return False
        if self._public_chat_on_cooldown("TikTok Live"):
            return False
        if tiktok_live_auto_trigger() == "all":
            return True
        return bool(
            twitch_message_addressees(
                cleaned, trigger_all=tiktok_live_auto_trigger() == "all"
            )
        )

    async def _broadcast_partner_chat_reply_viewer(self, partner_id: str) -> None:
        """Show partner VRM + route lip-sync before Twitch/YouTube live chat TTS."""
        from luna_cast import partner_vrm_viewer_url

        if not self._chat_hub:
            return
        pid = (partner_id or "viktor").strip().lower()
        avatar = viewer_avatar_id(pid, speaker="cohost")
        payload: dict = {
            "type": "control",
            "name": "cohost_avatar",
            "active_speaker": avatar,
            "chat_reply": True,
        }
        vrm_url = partner_vrm_viewer_url(pid)
        if vrm_url:
            payload["vrm_url"] = vrm_url
        if self._viewer_cohost_in_scene or (
            pid == "himari" and self._cast_scene.himari_in_scene
        ):
            payload["dual_layout"] = True
        await self._chat_hub.broadcast(payload)

    async def dismiss_cohost_from_viewer(self) -> None:
        """Viewer dismissed co-host(s) — stop banter/TTS until summoned again."""
        from luna_cast import CastScene, save_cast_scene

        scene = CastScene()
        save_cast_scene(scene)
        self._sync_cast_scene_flags(scene)
        self._active_banter_partner = None
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

    def _chat_reply_partner(self, question: str) -> str:
        """``luna``, ``viktor``, or ``himari`` (Twitch / YouTube / TikTok)."""
        from luna_cast import resolve_chat_reply_partner

        return resolve_chat_reply_partner(
            (question or "").strip(), self._cast_scene
        )

    def _creator_panel_reply_partner(
        self, question: str, *, creator_reply_to: str | None = None
    ) -> str:
        """Creator panel/voice routing — viewer ``reply_to`` + on-stage cast."""
        from luna_cast import resolve_creator_reply_partner

        return resolve_creator_reply_partner(
            (question or "").strip(),
            self._cast_scene,
            explicit_target=creator_reply_to,
        )

    def _chat_reply_speaker(self, question: str) -> str:
        """Legacy: ``luna`` or ``cohost``."""
        partner = self._chat_reply_partner(question)
        return "cohost" if partner in ("viktor", "himari") else "luna"

    def _cohost_for_chat_reply(self, question: str = "") -> bool:
        return self._chat_reply_partner(question) != "luna"

    def _partner_chat_system(self, partner_id: str) -> str:
        from himari_cohost import build_himari_chat_system, build_himari_system_prompt, himari_enabled
        from luna_cast import format_cast_roster_block, partner_cast_line
        from vampire_cohost import build_vampire_system_prompt, cohost_name

        if partner_id == "himari":
            base = build_himari_chat_system()
        else:
            vn = cohost_name()
            luna_ctx = build_luna_system_prompt()
            cast_extra = ""
            if himari_enabled():
                cast_extra = (
                    f"\n\n{partner_cast_line('himari')}\n"
                    f"Himari (context only — never reply as her):\n"
                    f"{build_himari_system_prompt()}\n"
                )
            base = (
                f"You are {vn}, the male vampire co-host on stream with Luna.\n\n"
                f"{build_vampire_system_prompt()}"
                f"{cast_extra}"
                f"\n\nLuna (your co-host — context only; never reply as Luna):\n{luna_ctx}\n\n"
                "A viewer sent a Twitch, YouTube Live, or TikTok Live chat message. If they used your name, "
                "they want **you** — not Luna. Reply in your voice only, as plain text for TTS. "
                "Use he/him for yourself. "
                "Keep it to one short paragraph or a few sentences unless they asked for more. "
                "Do not prefix with your name or a role tag."
            )
        roster = format_cast_roster_block(self._cast_scene)
        return f"{base}\n\n{roster}".strip() if roster else base

    def _cohost_off_stage_context_block(
        self, *, as_cohost: bool = False, partner_id: str = "viktor"
    ) -> str:
        from luna_cast import partner_display_name
        from vampire_cohost import cohost_enabled

        if as_cohost:
            if partner_id == "viktor" and (not cohost_enabled() or self._cast_scene.viktor_in_scene):
                return ""
            if partner_id == "himari" and self._cast_scene.himari_in_scene:
                return ""
            pn = partner_display_name(partner_id)
            return (
                f"## {pn} — off camera, answering chat\n"
                f"Your VRM may be dismissed in the viewer, but a chatter addressed **{pn}** by name. "
                "Reply in your voice; you do not need Luna to proxy for you."
            )
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

    async def _maybe_refresh_cast_consciousness(self, partner_id: str) -> None:
        if not self._cast_consciousness.needs_llm_refresh(partner_id):
            return
        messages = self._cast_consciousness.build_llm_refresh_messages(partner_id)
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
                self._cast_consciousness.apply_llm_refresh(partner_id, payload)
        except Exception as exc:
            print(f"(cast_consciousness) llm refresh failed: {exc}", flush=True)

    def _tiktok_live_listening(self) -> bool:
        cb = self._tiktok_live_active_cb
        if cb is None:
            return False
        try:
            return bool(cb())
        except Exception:
            return False

    def _dual_presence_context_block(self) -> str:
        yt = False
        cb = self._youtube_live_active_cb
        if cb is not None:
            try:
                yt = bool(cb())
            except Exception:
                yt = False
        tt = False
        tt_cb = self._tiktok_live_active_cb
        if tt_cb is not None:
            try:
                tt = bool(tt_cb())
            except Exception:
                tt = False
        return format_dual_presence_block(
            twitch_channel=self._twitch_channel_login,
            youtube_live_listening=yt,
            tiktok_live_listening=tt,
        )

    async def handle_youtube_live_chat(self, author: str, question: str, ts_ms: int) -> None:
        """YouTube Live chat → viewer panel + optional Luna reply (never posted to YouTube)."""
        self.touch_activity()
        await self._stop_cohost_banter_for_chat()
        source = "YouTube Live"
        self._youtube_live_session.note_viewer(author, question)
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
        q = question.strip()
        addressees = twitch_message_addressees(
            q, trigger_all=youtube_live_auto_trigger() == "all"
        )
        if not addressees:
            return
        if not self._try_claim_public_chat_line(source, author, q):
            return
        addressees = self._cap_public_chat_addressees(source, addressees)
        yt_profile = profile_from_login(author)
        self._register_youtube_chatter(yt_profile)
        print(f"\n--- Twitch /{source} {author}: {q}", flush=True)
        async with self._public_chat_serial_lock:
            await self.begin_public_chat_reply_priority()
            try:
                await self._wait_public_chat_cooldown(source)
                for i, speaker in enumerate(addressees):
                    if i > 0:
                        await self._wait_public_chat_cooldown(source)
                    reply = await self._generate_and_dispatch_reply(
                        channel_name=source,
                        author=author,
                        question=q,
                        send_to_twitch=False,
                        source=source,
                        local_speak=True,
                        allow_cohost_persona=True,
                        force_speaker=speaker,
                        record_user_memory=(i == 0),
                        update_auto_reply_cooldown=True,
                        chatter_profile=yt_profile,
                        log_incoming_chat=False,
                    )
                    if reply:
                        from luna_cast import partner_display_name

                        self._youtube_live_session.note_reply(
                            speaker=speaker,
                            author=author,
                            user_text=q,
                            reply=reply,
                            cohost_display=(
                                partner_display_name(speaker)
                                if speaker != "luna"
                                else cohost_name()
                            ),
                        )
            finally:
                self.end_public_chat_reply_priority()

    async def handle_tiktok_live_chat(self, author: str, question: str, ts_ms: int) -> None:
        """TikTok Live chat → viewer panel + optional Luna reply (never posted to TikTok)."""
        self.touch_activity()
        await self._stop_cohost_banter_for_chat()
        source = "TikTok Live"
        self._tiktok_live_session.note_viewer(author, question)
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
        if not self._should_auto_reply_tiktok(question):
            return
        q = question.strip()
        addressees = twitch_message_addressees(
            q, trigger_all=tiktok_live_auto_trigger() == "all"
        )
        if not addressees:
            return
        if not self._try_claim_public_chat_line(source, author, q):
            return
        addressees = self._cap_public_chat_addressees(source, addressees)
        tt_profile = profile_from_login(author, display_name=author)
        self._register_tiktok_chatter(tt_profile)
        print(f"\n--- Twitch /{source} {author}: {q}", flush=True)
        async with self._public_chat_serial_lock:
            await self.begin_public_chat_reply_priority()
            try:
                await self._wait_public_chat_cooldown(source)
                for i, speaker in enumerate(addressees):
                    if i > 0:
                        await self._wait_public_chat_cooldown(source)
                    reply = await self._generate_and_dispatch_reply(
                        channel_name=source,
                        author=author,
                        question=q,
                        send_to_twitch=False,
                        source=source,
                        local_speak=True,
                        allow_cohost_persona=True,
                        force_speaker=speaker,
                        record_user_memory=(i == 0),
                        update_auto_reply_cooldown=True,
                        chatter_profile=tt_profile,
                        log_incoming_chat=False,
                    )
                    if reply:
                        from luna_cast import partner_display_name

                        self._tiktok_live_session.note_reply(
                            speaker=speaker,
                            author=author,
                            user_text=q,
                            reply=reply,
                            cohost_display=(
                                partner_display_name(speaker)
                                if speaker != "luna"
                                else cohost_name()
                            ),
                        )
            finally:
                self.end_public_chat_reply_priority()

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
        author_is_bot: bool = False,
        allow_cohost_persona: bool = False,
        from_creator: bool = False,
        force_speaker: str | None = None,
        record_user_memory: bool = True,
        update_auto_reply_cooldown: bool = True,
        chatter_profile: TwitchChatterProfile | None = None,
        log_incoming_chat: bool = True,
        creator_reply_to: str | None = None,
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
        is_twitch = source.strip().lower() == "twitch chat"
        is_youtube_live = source.strip().lower() == "youtube live"
        is_tiktok_live = source.strip().lower() == "tiktok live"
        is_public_chat = is_twitch or is_youtube_live or is_tiktok_live

        if chatter_profile is None and is_twitch:
            chatter_profile = profile_from_login(author)
        if chatter_profile is None and (is_youtube_live or is_tiktok_live):
            chatter_profile = profile_from_login(author)

        is_creator = from_creator or is_creator_viewer_turn(source=source, author=author)
        if chatter_profile is not None and is_twitch and is_creator_twitch_profile(chatter_profile):
            is_creator = True
        src_lower = source.strip().lower()
        is_creator_panel = src_lower in ("viewer panel", "viewer voice") or (
            is_creator and not is_public_chat
        )

        memory_author = (
            chatter_profile.login if chatter_profile is not None else author
        )
        if is_creator:
            display_author = creator_display_name()
        elif chatter_profile is not None:
            display_author = chatter_profile.spoken_name()
        else:
            display_author = author

        vc_note = ""
        if discord_voice_channel:
            vc_note = (
                f" — speaker is currently in Discord voice channel {discord_voice_channel}"
            )
        if is_creator:
            if chatter_profile is not None and is_twitch:
                user_line = format_creator_twitch_user_line(
                    profile=chatter_profile, question=question
                )
            else:
                user_line = format_creator_user_line(
                    author=display_author, question=question, source=source
                )
            if vc_note:
                user_line = f"{user_line}{vc_note}"
        elif is_public_chat:
            user_line = question.strip()
        else:
            user_line = f"[{author} in {source}{vc_note}]: {question.strip()}"
        self.touch_activity()

        if is_creator and cohost_replies_to_creator_enabled():
            allow_cohost_persona = True
        elif is_creator_panel:
            from himari_cohost import chat_directed_at_himari, himari_enabled
            from vampire_cohost import chat_directed_at_cohost, cohost_enabled

            if (himari_enabled() and chat_directed_at_himari(question)) or (
                cohost_enabled() and chat_directed_at_cohost(question)
            ):
                allow_cohost_persona = True

        if force_speaker in ("luna", "viktor", "himari"):
            partner = force_speaker
        elif force_speaker == "cohost":
            partner = "viktor"
        elif allow_cohost_persona and is_creator_panel:
            partner = self._creator_panel_reply_partner(
                question, creator_reply_to=creator_reply_to
            )
        elif allow_cohost_persona:
            partner = self._chat_reply_partner(question)
        else:
            partner = "luna"
        as_cohost = partner in ("viktor", "himari")
        if is_creator_panel and as_cohost:
            from luna_cast import partner_display_name as _partner_name

            print(
                f"(creator) routing panel/voice reply → {_partner_name(partner)}",
                flush=True,
            )
        # Luna panel/voice: non-blocking by default. Live chat + co-hosts always wait for playback.
        block_viewer_tts = (
            is_public_chat
            or as_cohost
            or (not is_creator_panel)
            or self._creator_tts_blocks_until_done()
        )
        from luna_cast import format_cast_roster_block, format_viewer_addressee_note, partner_display_name

        display_name = partner_display_name(partner) if as_cohost else (self.nick or "luna")
        assistant_user = display_name

        messages: list[dict] = []
        if as_cohost:
            system_content = self._partner_chat_system(partner)
        else:
            system_content = self._system
            roster = format_cast_roster_block(self._cast_scene)
            if roster:
                system_content = (
                    f"{system_content}\n\n{roster}".strip() if system_content else roster
                )
            addressee = format_viewer_addressee_note(question, self._cast_scene)
            if addressee:
                system_content = (
                    f"{system_content}\n\n{addressee}".strip() if system_content else addressee
                )
        presence = self._dual_presence_context_block()
        if presence:
            system_content = (
                f"{system_content}\n\n{presence}".strip() if system_content else presence
            )
        off_stage = self._cohost_off_stage_context_block(as_cohost=as_cohost, partner_id=partner)
        if off_stage:
            system_content = (
                f"{system_content}\n\n{off_stage}".strip() if system_content else off_stage
            )
        if partner == "viktor":
            system_content = self._append_cohost_dynamics_to_system(
                system_content, as_cohost=as_cohost
            )
        if partner in ("viktor", "himari"):
            cast_block = self._cast_consciousness.block_for_partner_chat(
                partner, as_cohost=as_cohost
            )
            if cast_block:
                system_content = (
                    f"{system_content}\n\n{cast_block}".strip()
                    if system_content
                    else cast_block
                )
        if not as_cohost:
            on_stage = self._cast_scene.idle_partner_ids()
            if on_stage:
                couch = self._cast_consciousness.block_for_luna(on_stage_partners=on_stage)
                if couch:
                    system_content = (
                        f"{system_content}\n\n{couch}".strip()
                        if system_content
                        else couch
                    )
        if is_creator:
            if chatter_profile is not None and is_twitch:
                creator_block = creator_twitch_chat_system_block(profile=chatter_profile)
            else:
                creator_block = creator_chat_system_block(name=display_author)
            system_content = (
                f"{system_content}\n\n{creator_block}".strip()
                if system_content
                else creator_block
            )
        if is_public_chat and not is_creator and chatter_profile is not None:
            platform = "Twitch" if is_twitch else "YouTube Live" if is_youtube_live else "TikTok Live"
            session_msgs, returning = (1, False)
            if is_twitch:
                session_msgs, returning = self._chatter_session_stats(chatter_profile)
            elif is_youtube_live:
                session_msgs, returning = self._youtube_session_stats(chatter_profile)
            elif is_tiktok_live:
                session_msgs, returning = self._tiktok_session_stats(chatter_profile)
            chat_note = live_chatter_system_note(
                profile=chatter_profile,
                message=question,
                speaker="cohost" if as_cohost else "luna",
                platform=platform,
                cohost_name=display_name,
                session_messages=session_msgs,
                returning=returning,
            )
            system_content = (
                f"{system_content}\n\n{chat_note}".strip()
                if system_content
                else chat_note
            )
        if is_youtube_live:
            for yt_extra in (
                self._youtube_live_session.block_for_chat_reply(),
                youtube_live_reply_style_block(),
            ):
                if yt_extra:
                    system_content = (
                        f"{system_content}\n\n{yt_extra}".strip()
                        if system_content
                        else yt_extra
                    )
        if is_tiktok_live:
            from luna_banter_novelty import block_for_chat_novelty

            recent_assistant = [
                str(m.get("content") or "").strip()
                for m in self._memory
                if str(m.get("role") or "").strip().lower() == "assistant"
            ]
            chat_novelty = block_for_chat_novelty(
                recent_assistant,
                strict=self._tiktok_live_listening(),
            )
            for tt_extra in (
                self._tiktok_live_session.block_for_chat_reply(),
                tiktok_live_reply_style_block(),
                chat_novelty,
            ):
                if tt_extra:
                    system_content = (
                        f"{system_content}\n\n{tt_extra}".strip()
                        if system_content
                        else tt_extra
                    )
        if (
            (is_public_chat or author_is_bot)
            and not is_creator
            and chat_injection_guard_enabled()
        ):
            injection = scan_chat_prompt_injection(question)
            if injection.suspected:
                if author_is_bot:
                    plat = "Discord bot"
                elif is_twitch:
                    plat = "Twitch"
                elif is_tiktok_live:
                    plat = "TikTok Live"
                else:
                    plat = "YouTube Live"
                chatter_label = (
                    chatter_profile.address_name()
                    if chatter_profile is not None
                    else author
                )
                guard = chat_injection_guard_system_block(
                    platform=plat,
                    chatter_name=chatter_label,
                    scan=injection,
                )
                system_content = (
                    f"{system_content}\n\n{guard}".strip()
                    if system_content
                    else guard
                )
                who = memory_author or author
                print(
                    f"(chat) injection guard ({injection.severity}) — {who}: "
                    f"{'; '.join(injection.reasons[:3])}",
                    flush=True,
                )
        self._remember_user_facts(memory_author, source, question)
        mem_spoken = (
            chatter_profile.address_name() if chatter_profile is not None else None
        )
        user_memory = self._user_memory_block(
            memory_author, source, spoken_name=mem_spoken
        )
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

        if log_incoming_chat:
            print(f"\n--- Twitch /{channel_name} {author}: {question.strip()}", flush=True)
        stream_ws = self._chat_hub is not None and _env_truthy(
            "LUNA_STREAM_ASSISTANT_WS",
            default=True,
        )
        use_or_buffer = llm_provider() == "openrouter" and not openrouter_streaming_enabled()
        if stream_ws and not use_or_buffer:
            print("Assistant: (streaming to viewer…)", flush=True)
        else:
            print("Assistant: ", end="", flush=True)

        thinking_partner: str | None = None
        if partner == "luna":
            thinking_partner = "luna"
        elif partner == "himari" and self._cast_scene.himari_in_scene:
            thinking_partner = "himari"
        elif partner == "viktor" and self._cast_scene.viktor_in_scene:
            thinking_partner = "cohost"
        if thinking_partner:
            await self._broadcast_avatar_thinking(thinking_partner, True)
        try:
            async with self._ollama_lock:
                if stream_ws and not use_or_buffer:
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
                        stream=False,
                    )
        finally:
            if thinking_partner:
                await self._broadcast_avatar_thinking(thinking_partner, False)
        reply_stripped = strip_think_blocks(reply).strip()
        self._last_assistant_reply = reply_stripped
        if self._memory_turns > 0:
            if record_user_memory:
                if is_public_chat:
                    mem_user = (
                        chatter_profile.address_name()
                        if chatter_profile is not None
                        else author
                    )
                    self._append_memory("user", f"({mem_user}): {question.strip()}")
                else:
                    self._append_memory("user", user_line)
            mem_assistant = (
                f"[{display_name}] {reply_stripped}" if as_cohost else reply_stripped
            )
            self._append_memory("assistant", mem_assistant)
        if partner in ("viktor", "himari"):
            self._cast_consciousness.observe_exchange(
                partner,
                user_line=user_line,
                assistant_line=reply_stripped,
                speaker="cohost" if as_cohost else "luna",
            )
            if consciousness_enabled():
                asyncio.create_task(
                    self._maybe_refresh_cast_consciousness(partner),
                    name="cast-consciousness-refresh",
                )
        if partner == "viktor":
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
        twitch_out = reply_stripped
        if as_cohost and _env_truthy("LUNA_COHOST_CHAT_TWITCH_PREFIX", default=True):
            twitch_out = f"[{display_name}] {reply_stripped}"

        if send_to_twitch and self._send_replies:
            if is_twitch and chatter_profile is not None and not is_creator:
                twitch_out = format_twitch_reply_to_chatter(
                    twitch_out,
                    chatter_profile,
                    mention=_env_truthy("LUNA_TWITCH_REPLY_MENTION", default=True),
                )
            for part in chunk_reply(twitch_out):
                # Send generated answer back to Twitch.
                channel = self.get_channel(channel_name) if channel_name else None
                if channel:
                    await channel.send(part[:500])

        cohost_route_viewer = as_cohost and (is_public_chat or is_creator_panel)
        if self._chat_hub:
            ts = int(time.time() * 1000)
            if (
                cohost_route_viewer
                and local_speak
                and tts_enabled()
                and tts_play_to_viewer()
            ):
                await self._broadcast_partner_chat_reply_viewer(partner)
            # Tell the viewer TTS is about to start *before* the assistant line so
            # the UI does not fire text-timed lip animation (luna-assistant-reply).
            if local_speak and tts_enabled():
                if not as_cohost:
                    self._cancel_mic_ready_task()
                chat_avatar = viewer_avatar_id(partner) if as_cohost else "luna"
                await self._chat_hub.broadcast(
                    {
                        "type": "control",
                        "name": "avatar_speaking",
                        "value": True,
                        "avatar": chat_avatar,
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
                        **({"avatar": viewer_avatar_id(partner)} if as_cohost else {}),
                    }
                ),
            )

        if local_speak and tts_enabled():
            from luna_cast import partner_edge_voice

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
                if as_cohost:
                    payload["avatar"] = viewer_avatar_id(partner)
                try:
                    asyncio.run_coroutine_threadsafe(hub.broadcast(payload), loop)
                except RuntimeError:
                    pass

            viewer_tts_played = False
            try:
                if tts_play_to_viewer() and self._chat_hub:
                    voice = partner_edge_voice(partner) if as_cohost else None
                    bundle = await asyncio.to_thread(
                        synthesize_playback_bundle,
                        reply_stripped,
                        voice=voice,
                    )
                    if bundle is not None:
                        extra: dict = {}
                        if as_cohost:
                            extra["avatar"] = viewer_avatar_id(partner)
                            if cohost_route_viewer:
                                extra["chat_reply"] = True
                        viewer_tts_played = await self._emit_viewer_tts(
                            bundle,
                            reply_text=reply_stripped,
                            extra=extra,
                            block_until_done=block_viewer_tts,
                        )
                if tts_play_locally():
                    await asyncio.to_thread(
                        maybe_speak,
                        reply_stripped,
                        viseme_cb=_emit_viseme,
                        voice=partner_edge_voice(partner) if as_cohost else None,
                    )
            finally:
                if viewer_tts_played and not block_viewer_tts:
                    # Creator panel/voice: audio plays in viewer; gate clears on viewer_tts_ended.
                    pass
                elif viewer_tts_played and block_viewer_tts:
                    pass
                elif not viewer_only:
                    self._avatar_speaking = False
                    self._last_avatar_speaking_end_ts = time.monotonic()
                    if self._chat_hub:
                        end_avatar = viewer_avatar_id(partner) if as_cohost else "luna"
                        await self._chat_hub.broadcast(
                            {
                                "type": "control",
                                "name": "avatar_speaking",
                                "value": False,
                                "avatar": end_avatar,
                            }
                        )
                        if not as_cohost:
                            self._schedule_mic_ready_after_tts(self._chat_hub)
        if update_auto_reply_cooldown and is_public_chat:
            self._last_auto_reply_ts = time.time()
        return reply_stripped

    async def handle_discord_chat(
        self,
        *,
        author: str,
        question: str,
        discord_channel_label: str,
        is_dm: bool,
        voice_channel_label: str | None = None,
        author_is_bot: bool = False,
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
            author_is_bot=author_is_bot,
        )

        audio_path: Path | None = None
        want_chat_mp3 = _env_truthy("LUNA_DISCORD_TTS", default=True)
        want_vc_mp3 = _env_truthy("LUNA_DISCORD_VOICE_TTS", default=True) and not is_dm
        if reply and tts_enabled() and (want_chat_mp3 or want_vc_mp3):
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


def _quiet_asyncio_connection_reset(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    """Suppress noisy WinError 10054 when Discord/HTTP peers close sockets abruptly."""
    exc = context.get("exception")
    if isinstance(exc, ConnectionResetError):
        return
    msg = str(context.get("message") or "")
    if "connection_lost" in msg.lower() and isinstance(
        exc, (ConnectionResetError, BrokenPipeError, OSError)
    ):
        return
    loop.default_exception_handler(context)


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
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(_quiet_asyncio_connection_reset)

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
            await hub.send_to(ws, viewer_perf_control_message())

        runner, site = await start_chat_ws_server(
            hub, host=ws_host, port=ws_port, on_ws_join=_on_ws_join
        )
        print(
            f"Chat bridge WebSocket: ws://{ws_host}:{ws_port}/ws "
            f"(set VITE_CHAT_WS_URL in the viewer .env)",
            flush=True,
        )

    if llm_provider() == "openrouter" and not openrouter_configured():
        print(
            "LUNA_LLM_PROVIDER=openrouter requires OPENROUTER_API_KEY in .env "
            "(https://openrouter.ai/keys)",
            file=sys.stderr,
        )
        sys.exit(1)
    client = build_client()
    vision_client = build_vision_client()

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
        vision_ollama_client=vision_client,
    )
    # Wire Discord free-text chat into LunaTwitchBot's shared memory pipeline.
    if discord_bot_obj is not None:
        discord_bot_obj.set_chat_handler(bot.handle_discord_chat)

    prompted_yt_stream_ids: set[str] = set()
    yt_runner = YouTubeLiveChatRunner()
    tt_runner = TikTokLiveChatRunner()
    bot._youtube_live_active_cb = lambda: yt_runner.is_running
    bot._tiktok_live_active_cb = lambda: tt_runner.is_running

    async def _hub_status(text: str) -> None:
        if hub is not None:
            await hub.broadcast({"type": "status", "text": text})

    async def _on_youtube_live_chat(author: str, text: str, ts_ms: int) -> None:
        await bot.handle_youtube_live_chat(author, text, ts_ms)

    async def _on_tiktok_live_chat(author: str, text: str, ts_ms: int) -> None:
        await bot.handle_tiktok_live_chat(author, text, ts_ms)

    async def _on_yt_live_stopped() -> None:
        pass

    async def _on_tt_live_stopped() -> None:
        bot._tiktok_live_session.clear()

    async def _connect_tiktok_live_stream(
        item: dict[str, str] | None = None,
    ) -> bool:
        uid = tiktok_live_username()
        if not uid:
            return False
        if tt_runner.is_running and tt_runner.active_username.lower() == uid.lower():
            return True
        bot._tiktok_live_session.clear()
        title = ""
        if item:
            title = str(item.get("title") or "").strip()
        await tt_runner.start(
            username=uid,
            on_chat=_on_tiktok_live_chat,
            broadcast_status=_hub_status,
            on_stopped=_on_tt_live_stopped,
        )
        label = f" ({title})" if title else ""
        await _hub_status(f"TikTok Live chat: connected ({uid}){label}.")
        return True

    async def _disconnect_tiktok_live_stream(*, reason: str = "") -> None:
        if tt_runner.is_running:
            if reason:
                print(f"(tiktok live) stopping listener — {reason}", flush=True)
            await tt_runner.stop()
        bot._tiktok_live_session.clear()

    async def _on_tiktok_live_watch_detected(item: dict[str, str]) -> None:
        uid = tiktok_live_username()
        if not uid:
            return
        if tt_runner.is_running:
            return
        title = str(item.get("title") or "TikTok Live")
        print(f"(tiktok live watch) live: {title} ({uid})", flush=True)
        await _hub_status(f"TikTok live watch: live detected — connecting chat ({uid})…")
        await _connect_tiktok_live_stream(item)

    async def _on_tiktok_live_watch_offline() -> None:
        if not tt_runner.is_running:
            return
        await _disconnect_tiktok_live_stream(reason="not live (watch poll)")
        await _hub_status("TikTok live watch: not live — chat listener idle.")

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

    async def _connect_youtube_live_stream(
        item: dict[str, str],
        *,
        close_prompt: bool = True,
    ) -> bool:
        sid = str(item.get("id") or "").strip()
        if not sid:
            return False
        if yt_runner.is_running and yt_runner.active_video_id == sid:
            return True
        bot._youtube_live_session.clear()
        page_url = str(item.get("url") or "").strip()
        if page_url:
            set_youtube_live_url(page_url)
        elif not youtube_live_video_id():
            set_youtube_live_url(f"https://www.youtube.com/watch?v={sid}")
        await yt_runner.start(
            video_id=sid,
            on_chat=_on_youtube_live_chat,
            broadcast_status=_hub_status,
            on_stopped=_on_yt_live_stopped,
        )
        prompted_yt_stream_ids.add(sid)
        if close_prompt and hub is not None:
            await hub.broadcast(
                {
                    "type": "control",
                    "name": "youtube_live_prompt",
                    "open": False,
                }
            )
        await _hub_status(f"YouTube Live chat (pytchat): connected ({sid}).")
        return True

    async def _disconnect_youtube_live_stream(*, reason: str = "") -> None:
        if yt_runner.is_running:
            if reason:
                print(f"(youtube live) stopping listener — {reason}", flush=True)
            await yt_runner.stop()
        clear_youtube_live_stream()
        bot._youtube_live_session.clear()
        if reason and hub is not None:
            await hub.broadcast(
                {
                    "type": "control",
                    "name": "youtube_live_prompt",
                    "open": False,
                }
            )

    async def _on_youtube_live_watch_detected(item: dict[str, str]) -> None:
        sid = str(item.get("id") or "").strip()
        if not sid:
            return
        if yt_runner.is_running and yt_runner.active_video_id == sid:
            return
        title = str(item.get("title") or "YouTube Live")
        print(f"(youtube live watch) live: {title} ({sid})", flush=True)
        await _hub_status(
            f"YouTube live watch: live detected — connecting pytchat ({sid})…",
        )
        await _connect_youtube_live_stream(item)

    async def _on_youtube_live_watch_offline() -> None:
        if not yt_runner.is_running and not youtube_live_video_id():
            return
        await _disconnect_youtube_live_stream(reason="channel not live (watch poll)")
        await _hub_status("YouTube live watch: not live — chat listener idle.")

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
                from luna_cast import load_cast_scene, partner_display_name, save_cast_scene

                in_scene = payload.get("in_scene") is True
                partner = str(payload.get("partner") or "").strip().lower()
                cast = payload.get("cast")
                scene = load_cast_scene()
                if isinstance(cast, dict):
                    if "viktor" in cast:
                        scene.viktor_in_scene = bool(cast.get("viktor"))
                    if "himari" in cast:
                        scene.himari_in_scene = bool(cast.get("himari"))
                elif partner == "himari":
                    scene.himari_in_scene = in_scene
                elif partner == "viktor":
                    scene.viktor_in_scene = in_scene
                else:
                    scene.viktor_in_scene = in_scene
                    if not in_scene:
                        scene.himari_in_scene = False
                save_cast_scene(scene)
                bot._sync_cast_scene_flags(scene)
                if not scene.any_in_scene():
                    await bot.dismiss_cohost_from_viewer()
                if hub is not None:
                    on_stage = [
                        partner_display_name(p)
                        for p in scene.idle_partner_ids()
                    ]
                    label = ", ".join(on_stage) if on_stage else "solo (Luna only)"
                    await hub.broadcast(
                        {"type": "status", "text": f"On stage: {label}"},
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
                        {
                            "type": "status",
                            "text": "Co-host banter is already playing.",
                        },
                    )
                    return
                if bot.public_chat_reply_priority_busy():
                    await hub.broadcast(
                        {
                            "type": "status",
                            "text": "Twitch/YouTube chat replies in progress — try banter again after.",
                        },
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
                from live_social_share import probe_tiktok_live, probe_youtube_live

                async def _manual_youtube_live_check() -> None:
                    if not youtube_live_chat_requested():
                        await hub.broadcast(
                            {
                                "type": "status",
                                "text": "YouTube Live chat off — set LUNA_YOUTUBE_LIVE_CHAT=1.",
                            },
                        )
                        return
                    url = youtube_live_check_probe_url()
                    await hub.broadcast(
                        {"type": "status", "text": f"YouTube live: checking {url}…"}
                    )
                    item = await asyncio.to_thread(probe_youtube_live, url)
                    if not item:
                        await hub.broadcast(
                            {
                                "type": "status",
                                "text": (
                                    "YouTube live: not detected on this channel "
                                    "(tap again after you go live)."
                                ),
                            },
                        )
                        return
                    await _prompt_youtube_live_url(item, force=True)

                async def _manual_tiktok_live_check() -> None:
                    if not tiktok_live_chat_requested():
                        await hub.broadcast(
                            {
                                "type": "status",
                                "text": "TikTok Live chat off — set LUNA_TIKTOK_LIVE_CHAT=1.",
                            },
                        )
                        return
                    uid = tiktok_live_username()
                    if not uid:
                        await hub.broadcast(
                            {
                                "type": "status",
                                "text": "TikTok Live: set LUNA_TIKTOK_LIVE_USERNAME (e.g. @handle).",
                            },
                        )
                        return
                    if (
                        tt_runner.is_running
                        and tt_runner.active_username.lower() == uid.lower()
                    ):
                        await hub.broadcast(
                            {
                                "type": "status",
                                "text": f"TikTok Live chat: already listening ({uid}).",
                            },
                        )
                        return
                    await hub.broadcast(
                        {"type": "status", "text": f"TikTok live: checking {uid}…"}
                    )
                    tt_item = await probe_tiktok_live(uid)
                    if not tt_item:
                        await hub.broadcast(
                            {
                                "type": "status",
                                "text": f"TikTok live: not detected for {uid} (tap again after you go live).",
                            },
                        )
                        return
                    await _on_tiktok_live_watch_detected(tt_item)

                await asyncio.gather(
                    _manual_youtube_live_check(),
                    _manual_tiktok_live_check(),
                )
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
                reply_to = str(payload.get("reply_to") or payload.get("target") or "").strip()
                await bot._generate_and_dispatch_reply(
                    channel_name="panel",
                    author=creator,
                    question=text,
                    send_to_twitch=False,
                    source="viewer panel",
                    from_creator=True,
                    creator_reply_to=reply_to or None,
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
                await _connect_youtube_live_stream({"id": vid, "url": url})
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

            if msg_type == "viewer_live_social_title":
                title = str(payload.get("title") or "").strip()
                platform = str(payload.get("platform") or "twitch").strip().lower()
                sid = str(payload.get("stream_id") or "").strip()
                url = str(payload.get("url") or "").strip()
                if not title or not sid or not url:
                    await hub.broadcast(
                        {
                            "type": "status",
                            "text": "Go-live post: enter a stream title.",
                        },
                    )
                    return
                st = live_social_load_state()

                async def _social_send(post_title: str, stream_url: str, plat: str) -> None:
                    await _social_playwright_live(post_title, stream_url, plat)

                ok = await complete_live_social_share(
                    platform=platform,
                    stream_id=sid,
                    title=title,
                    url=url,
                    state=st,
                    social_share_send=_social_send,
                    broadcast_status=_hub_status,
                )
                await hub.broadcast(
                    {
                        "type": "control",
                        "name": "live_social_title_prompt",
                        "open": False,
                    }
                )
                if ok:
                    await hub.broadcast(
                        {
                            "type": "status",
                            "text": f"Posted to X & Facebook: {title}",
                        },
                    )
                return

            if msg_type == "viewer_live_social_title_dismiss":
                platform = str(payload.get("platform") or "twitch").strip().lower()
                sid = str(payload.get("stream_id") or "").strip()
                if sid:
                    skip_live_social_share(
                        platform=platform,
                        stream_id=sid,
                        state=live_social_load_state(),
                    )
                await hub.broadcast(
                    {
                        "type": "control",
                        "name": "live_social_title_prompt",
                        "open": False,
                    },
                )
                await hub.broadcast(
                    {
                        "type": "status",
                        "text": "Skipped X/Facebook go-live post.",
                    },
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
                    reply_to = str(
                        payload.get("reply_to") or payload.get("target") or ""
                    ).strip()
                    await bot._generate_and_dispatch_reply(
                        channel_name="panel",
                        author=creator,
                        question=text,
                        send_to_twitch=False,
                        source="viewer voice",
                        from_creator=True,
                        creator_reply_to=reply_to or None,
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
    yt_watch_task: asyncio.Task | None = None
    tt_watch_task: asyncio.Task | None = None
    tt_task: asyncio.Task | None = None
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

        async def _social_playwright_live(title: str, stream_url: str, platform: str) -> None:
            try:
                await share_live_stream(
                    platform=platform,
                    title=title,
                    stream_url=stream_url,
                )
            except Exception as exc:
                print(f"(social playwright) live share failed: {exc}", flush=True)

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
            if youtube_live_watch_poll_enabled():
                yt_watch_task = asyncio.create_task(
                    run_youtube_live_watch_poller(
                        probe_url=youtube_live_check_probe_url(),
                        on_live=_on_youtube_live_watch_detected,
                        on_offline=_on_youtube_live_watch_offline,
                        broadcast_status=_hub_status,
                    ),
                    name="luna-youtube-live-watch",
                )

        if tiktok_live_chat_requested():
            uid = tiktok_live_username()
            if not uid:
                await _hub_status(
                    "TikTok Live chat: set LUNA_TIKTOK_LIVE_USERNAME (e.g. @yourhandle)."
                )
            elif tiktok_live_watch_poll_enabled():
                tt_watch_task = asyncio.create_task(
                    run_tiktok_live_watch_poller(
                        username=uid,
                        on_live=_on_tiktok_live_watch_detected,
                        on_offline=_on_tiktok_live_watch_offline,
                        broadcast_status=_hub_status,
                    ),
                    name="luna-tiktok-live-watch",
                )
            else:
                tt_task = await tt_runner.start(
                    username=uid,
                    on_chat=_on_tiktok_live_chat,
                    broadcast_status=_hub_status,
                    on_stopped=_on_tt_live_stopped,
                )

        if live_watch_enabled():

            async def _live_social_share_send(title: str, url: str, platform: str) -> None:
                await _social_playwright_live(title, url, platform)

            async def _discord_live_announce(text: str, platform: str, image_path: str) -> None:
                if discord_bot_obj is None:
                    return
                dbot = discord_bot_obj.bot
                try:
                    await asyncio.wait_for(dbot.wait_until_ready(), timeout=180.0)
                except Exception as exc:
                    print(f"(discord live) wait_until_ready failed: {exc}", flush=True)
                    return
                img = image_path.strip() or None
                ch_ids = live_discord_channel_ids()
                if ch_ids:
                    n = await discord_bot_obj.announce_live_to_channel_ids(
                        text, ch_ids, image_path=img
                    )
                    await _hub_status(
                        f"Discord live announce ({platform}): posted to {n} channel(s)."
                    )
                else:
                    n = await discord_bot_obj.announce_live_all_guilds(text, image_path=img)
                    await _hub_status(
                        f"Discord live announce ({platform}): posted to {n} server(s)."
                    )

            live_social_task = asyncio.create_task(
                run_live_social_poller(
                    social_share_send=_live_social_share_send,
                    discord_live_send=_discord_live_announce,
                    broadcast_status=_hub_status,
                    request_social_title_prompt=bot._prompt_live_social_title,
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
        await tt_runner.stop()
        if yt_watch_task is not None:
            yt_watch_task.cancel()
            try:
                await yt_watch_task
            except (asyncio.CancelledError, Exception):
                pass
        if tt_watch_task is not None:
            tt_watch_task.cancel()
            try:
                await tt_watch_task
            except (asyncio.CancelledError, Exception):
                pass
        if tt_task is not None:
            tt_task.cancel()
            try:
                await tt_task
            except (asyncio.CancelledError, Exception):
                pass
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
        default=resolve_vision_model(),
        help="Ollama vision model (screen/YouTube frames). Chat model: LUNA_CHAT_MODEL or OpenRouter env.",
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
    auto_trigger = os.environ.get("TWITCH_AUTO_TRIGGER", "all").strip().lower()
    if auto_trigger not in {"mention", "all"}:
        auto_trigger = "all"
    auto_cooldown_sec = public_chat_cooldown_sec()

    chat_model = resolve_chat_model()
    provider = llm_provider()
    vision_model = resolve_vision_model()
    if provider == "openrouter" and vision_provider() == "openrouter":
        llm_line = f"openrouter chat+vision {chat_model}"
    elif provider == "openrouter":
        llm_line = f"openrouter chat {chat_model} | ollama vision {vision_model}"
    else:
        llm_line = (
            f"ollama {os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434')} "
            f"chat={chat_model} vision={vision_model}"
        )
    print(
        f"Starting Twitch bot | channel #{channel} | "
        f"{llm_line} | "
        f"send_replies={send_replies} | auto_reply={auto_reply} ({auto_trigger}) | "
        f"public_chat_cooldown twitch={auto_cooldown_sec}s "
        f"youtube={youtube_live_cooldown_sec()}s tiktok={tiktok_live_cooldown_sec()}s | "
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
