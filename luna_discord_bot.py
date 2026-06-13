"""Discord music + chat bot for Luna streamer.

Runs in the same asyncio loop as the Twitch bot (started from twitch_bot._run_async).
Resolves tracks via youtube_audio.resolve_track and streams them with FFmpeg.
Free-text messages (anything that is not a ``!command``) are forwarded to the
LunaTwitchBot reply pipeline so memory is shared across viewer / Twitch / Discord.

Discord commands (in any text channel the bot can read):
  !join                   Join the caller's current voice channel
  !leave                  Leave voice
  !play <url|search>      Queue a YouTube URL or search phrase
  !skip                   Skip the current track
  !stop                   Stop and clear the queue
  !pause / !resume        Toggle playback
  !queue / !nowplaying    Show queue / current track
  !dm <@user|user_id> <message>  Send that user a DM (owner only; see LUNA_OWNER_DISCORD_ID)
  !setup-community        Create persona + fan channels (owner only; never deletes)
  !daily-post             Post today's Wolf Den engagement message now (owner only)

Env:
  DISCORD_TOKEN                    Bot token (required to enable Discord).
  DISCORD_COMMAND_PREFIX           Command prefix (default "!").
  DISCORD_VOICE_GUILD_ID           Optional. With DISCORD_VOICE_CHANNEL_ID, auto-join on ready.
  DISCORD_VOICE_CHANNEL_ID         Optional voice channel id to auto-join.
  DISCORD_TEXT_CHANNEL_ID          Optional text channel id for now-playing messages.
  LUNA_DISCORD_SELF_DEAF           If 0/false/no/off, join VC without self-deafen (cosmetic;
                                   bot still does not use VC audio for STT). Default: 1.
  LUNA_DISCORD_CHAT                Master switch for free-text chat replies. Default 1.
  LUNA_DISCORD_CHAT_TRIGGER        "all" (any non-command msg in allowed channels) or
                                   "mention" (only when @bot, reply to bot, or luna/viktor/himari
                                   in text). Default "mention".
  LUNA_DISCORD_COHOST_CHAT         If 1 (default when co-host personas enabled), Viktor/Himari
                                   can answer Discord when their names are used (see twitch_bot).
  LUNA_DISCORD_CHAT_CHANNEL_IDS    Optional global allowlist (all servers). Empty = all channels
                                   except servers listed in LUNA_DISCORD_GUILD_CHAT_CHANNELS.
  LUNA_DISCORD_GUILD_CHAT_CHANNELS Per-server allowlists: guild_id:channel_id[,channel_id…]
                                   or guild_id:* / guild_id:all for every text channel in that server.
                                   Space-separated entries. Example:
                                   1464575233783631886:1505683058601361488
                                   1465362923428778110:*
  LUNA_DISCORD_GUILD_CHAT_TRIGGERS  Optional per-server trigger override:
                                   guild_id:all|mention (space-separated). Example:
                                   1465362923428778110:all
  LUNA_DISCORD_CHAT_READ_BOTS      1 to treat other bots like users in allowed channels (default 0).
                                   Bots must still @-mention Luna or say "luna" (even if TRIGGER=all).
  LUNA_DISCORD_CHAT_BOT_IDS        Optional comma-separated bot user ids; empty = any bot (not self).
  LUNA_DISCORD_CHAT_DEBUG          1 to log skipped messages and reasons (default 0).
  LUNA_DISCORD_CHAT_DM             1 to also reply to DMs (default 1).
  LUNA_DISCORD_DM_COMMAND          1 to enable !dm (default 1).
  LUNA_OWNER_DISCORD_ID            Your Discord user id (can use !dm). Comma list ok.
  LUNA_DISCORD_DM_ALLOWED_IDS      Optional extra user ids allowed to use !dm.
  LUNA_DISCORD_WELCOME             1 to greet new members (default 1 when channel id set).
  LUNA_DISCORD_WELCOME_CHANNEL_ID  Text channel id for join messages (requires Members intent).
  LUNA_DISCORD_WELCOME_GUILD_ID    Optional server id; empty = infer from channel.
  LUNA_DISCORD_WELCOME_MESSAGE     Template with {mention} {user} {server} {username}.
  LUNA_DISCORD_WELCOME_CHECK_ON_READY  If 1 (default), scan for today's joins on startup.
  LUNA_DISCORD_WELCOME_TODAY_SUMMARY   If 1 (default), post one daily list in the welcome channel.
  LUNA_DISCORD_WELCOME_STATE_PATH      JSON file tracking who was already welcomed.
  LUNA_DISCORD_CHAT_COOLDOWN_SEC   Min seconds between Luna replies per channel. Default 4.
  LUNA_DISCORD_TTS                 1 to attach one TTS MP3 under the reply (default 1; no length cap).
  LUNA_DISCORD_TTS_SINGLE_FILE     1 (default) = one MP3 for the full reply (3+ min ok). 0 = split files.
  LUNA_DISCORD_TTS_MAX_CHARS       0 (default) = no truncation for Discord TTS.
  LUNA_DISCORD_TTS_CHARS_PER_FILE  When SINGLE_FILE=0: max chars per MP3 (default 200).
  LUNA_DISCORD_TTS_MAX_FILES       When SINGLE_FILE=0: max MP3 attachments (default 6).
                                   Does not play on local speakers; viewer TTS is skipped for Discord.
  LUNA_DISCORD_VOICE_TTS           If 1 (default), after a chat reply Luna queues TTS in the
                                   same voice pipeline as !play (FFmpeg queue; waits behind songs).
  LUNA_DISCORD_VOICE_TTS_CHANNEL_IDS  Optional comma-separated voice channel ids Luna may join
                                   to speak when you are not in VC (you are always followed
                                   into your current voice channel). Empty = only VCs she is
                                   already connected to.
  LUNA_DISCORD_VOICE_TTS_PAD_SEC     Extra seconds after VC TTS ends (like viewer pad; default 1.5).
  LUNA_DISCORD_COMMUNITY_SETUP      If 1 (default), allow !setup-community (create-only layout).
  LUNA_DISCORD_COMMUNITY_AUTO_ON_READY  If 1 (default), run setup on ready for guild ids below.
  LUNA_DISCORD_COMMUNITY_GUILD_IDS Comma-separated guild ids (defaults to LUNA_DISCORD_WELCOME_GUILD_ID).
  LUNA_DISCORD_COMMUNITY_STATE_PATH JSON map of created channel ids (data/discord_community_channels.json).
  LUNA_DISCORD_ENGAGEMENT          If 1 (default), track Wolf Den activity in data/discord_engagement_state.json.
  LUNA_DISCORD_ENGAGEMENT_GUILD_IDS  Guild ids for memory + daily posts (default: welcome/community guild).
  LUNA_DISCORD_DAILY_POST          If 1 (default), Luna posts one themed daily message per guild per day.
  LUNA_DISCORD_DAILY_POST_HOUR     Local hour (0–23) before posting runs (default 10).
  LUNA_DISCORD_DAILY_CHANNEL_ID    Text channel for daily posts (default #community-chat from layout).
  LUNA_DISCORD_ENGAGEMENT_POLL_SEC How often to check for daily post (default 900).
  Voice context                    When the author is in a voice channel, Luna's model
                                   prompt includes which VC they are in (so she can refer
                                   to it). !join replies also name that channel explicitly.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

try:
    import discord
    from discord.ext import commands as dcommands
    _DISCORD_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when extra not installed
    discord = None  # type: ignore[assignment]
    dcommands = None  # type: ignore[assignment]
    _DISCORD_AVAILABLE = False

from youtube_audio import resolve_track, short_status_line

_FFMPEG_BEFORE_OPTS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
_FFMPEG_OPTS = "-vn"
_FFMPEG_LOCAL_BEFORE = "-nostdin"
_FFMPEG_LOCAL_OPTS = "-vn -loglevel quiet"


def _probe_media_duration_sec(path: Path) -> float:
    """Length of a local audio file (ffprobe), for full Discord VC playback."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not path.is_file():
        return 0.0
    try:
        proc = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return max(0.0, float(proc.stdout.strip()))
    except (ValueError, subprocess.TimeoutExpired, OSError):
        pass
    return 0.0


def _discord_voice_tts_pad_sec() -> float:
    try:
        return max(0.0, float(os.environ.get("LUNA_DISCORD_VOICE_TTS_PAD_SEC", "1.5") or "1.5"))
    except ValueError:
        return 1.5

# Discord hard cap is 2000 chars per message; leave a little headroom.
_DISCORD_MSG_CHUNK = 1900

# Handler may return ``reply`` (str) or ``(reply, audio_paths)`` where audio_paths is
# a list of temp MP3/WAV paths (one or two files for long TTS).
ChatHandler = Callable[..., Awaitable[Any]]


def _env_truthy(key: str, default: bool = False) -> bool:
    raw = (os.environ.get(key, "") or "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def discord_dm_command_enabled() -> bool:
    return _env_truthy("LUNA_DISCORD_DM_COMMAND", default=True)


def discord_dm_allowed_user_ids() -> frozenset[int]:
    """Discord user ids that may run ``!dm``."""
    raw = (
        os.environ.get("LUNA_DISCORD_DM_ALLOWED_IDS")
        or os.environ.get("LUNA_OWNER_DISCORD_ID")
        or os.environ.get("DISCORD_DM_OWNER_ID")
        or ""
    ).strip()
    out: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            continue
    return frozenset(out)


def _can_use_discord_dm_command(author_id: int) -> bool:
    allowed = discord_dm_allowed_user_ids()
    return bool(allowed) and int(author_id) in allowed


def _discord_chat_allowed_channel_ids() -> frozenset[str]:
    raw = (os.environ.get("LUNA_DISCORD_CHAT_CHANNEL_IDS") or "").strip()
    if not raw:
        return frozenset()
    return frozenset(s.strip() for s in raw.replace(" ", ",").split(",") if s.strip())


def _discord_guild_chat_channel_rules() -> dict[int, frozenset[int] | None]:
    """Parse LUNA_DISCORD_GUILD_CHAT_CHANNELS → {guild_id: channel ids or None = all channels}."""
    raw = (os.environ.get("LUNA_DISCORD_GUILD_CHAT_CHANNELS") or "").strip()
    if not raw:
        return {}
    rules: dict[int, frozenset[int] | None] = {}
    for entry in raw.replace(";", " ").split():
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            try:
                rules[int(entry)] = None
            except ValueError:
                continue
            continue
        guild_s, ch_part = entry.split(":", 1)
        try:
            guild_id = int(guild_s.strip())
        except ValueError:
            continue
        if ch_part.strip().lower() in ("*", "all", "any"):
            rules[guild_id] = None
            continue
        ch_ids: set[int] = set()
        for part in ch_part.replace(" ", ",").split(","):
            part = part.strip().lower()
            if not part or part in ("*", "all", "any"):
                if part:
                    rules[guild_id] = None
                continue
            try:
                ch_ids.add(int(part))
            except ValueError:
                continue
        if rules.get(guild_id) is None:
            continue
        if ch_ids:
            prev = rules.get(guild_id)
            merged = set(prev) if prev is not None else set()
            rules[guild_id] = frozenset(merged | ch_ids)
    return rules


def _discord_guild_chat_triggers() -> dict[int, str]:
    """Parse LUNA_DISCORD_GUILD_CHAT_TRIGGERS → {guild_id: 'all' | 'mention'}."""
    raw = (os.environ.get("LUNA_DISCORD_GUILD_CHAT_TRIGGERS") or "").strip()
    if not raw:
        return {}
    out: dict[int, str] = {}
    for entry in raw.replace(";", " ").split():
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        guild_s, mode_s = entry.split(":", 1)
        try:
            guild_id = int(guild_s.strip())
        except ValueError:
            continue
        mode = mode_s.strip().lower()
        if mode in ("all", "mention"):
            out[guild_id] = mode
    return out


def _discord_chat_trigger_mode(guild: Any | None) -> str:
    default = (os.environ.get("LUNA_DISCORD_CHAT_TRIGGER") or "mention").strip().lower()
    if default not in ("all", "mention"):
        default = "mention"
    if guild is None:
        return default
    return _discord_guild_chat_triggers().get(int(guild.id), default)


def _channel_id_candidates(channel: Any) -> list[int]:
    ids = [int(channel.id)]
    parent = getattr(channel, "parent", None)
    if parent is not None:
        ids.append(int(parent.id))
    return ids


def _channel_allowed_for_chat(channel: Any, guild: Any | None) -> bool:
    """Guild-specific allowlist wins; else optional global allowlist; else all channels."""
    candidates = _channel_id_candidates(channel)
    if guild is not None:
        from luna_discord_community import community_channel_ids_for_guild

        community_ids = community_channel_ids_for_guild(int(guild.id))
        if community_ids and any(cid in community_ids for cid in candidates):
            return True

        guild_rules = _discord_guild_chat_channel_rules()
        gid = int(guild.id)
        if gid in guild_rules:
            allowed = guild_rules[gid]
            if allowed is None:
                return True
            return any(cid in allowed for cid in candidates)

    global_allowed = _discord_chat_allowed_channel_ids()
    if not global_allowed:
        return True
    return any(str(cid) in global_allowed for cid in candidates)


def _discord_persona_channel_partner(message: Any) -> str | None:
    """In #luna-chat / #viktor-chat / #himari-chat, route to that cast without a name mention."""
    if message.guild is None:
        return None
    from luna_discord_community import persona_for_channel_id

    return persona_for_channel_id(int(message.guild.id), int(message.channel.id))


def _discord_should_reply_to_message(
    content: str,
    message: Any,
    bot_user: Any | None,
    *,
    is_dm: bool,
    from_other_bot: bool,
) -> bool:
    if is_dm:
        return True
    partner = _discord_persona_channel_partner(message)
    if partner:
        return True
    from luna_discord_community import is_fan_gallery_channel

    if message.guild and is_fan_gallery_channel(
        int(message.guild.id), int(message.channel.id)
    ):
        return _discord_cast_triggered(content, message, bot_user)
    trigger = _discord_chat_trigger_mode(message.guild)
    if trigger == "all":
        return True
    if from_other_bot:
        return _discord_cast_triggered(content, message, bot_user)
    return _discord_cast_triggered(content, message, bot_user)


def _discord_chat_debug() -> bool:
    return _env_truthy("LUNA_DISCORD_CHAT_DEBUG", default=False)


_discord_skip_logged: set[tuple[int, int]] = set()


def _discord_chat_log(msg: str) -> None:
    print(f"(discord chat) {msg}", flush=True)


def _discord_message_text(message: Any) -> str:
    """Plain text plus embed title/description (common for bot messages)."""
    text = (getattr(message, "content", None) or "").strip()
    if text:
        return text
    embeds = getattr(message, "embeds", None) or []
    parts: list[str] = []
    for emb in embeds:
        for bit in (
            getattr(emb, "title", None),
            getattr(emb, "description", None),
            getattr(getattr(emb, "author", None), "name", None),
        ):
            if bit and str(bit).strip():
                parts.append(str(bit).strip())
    return "\n".join(parts).strip()


def _env_id_set(key: str) -> frozenset[int]:
    raw = (os.environ.get(key) or "").strip()
    if not raw:
        return frozenset()
    out: set[int] = set()
    for part in raw.replace(" ", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            continue
    return frozenset(out)


def _voice_tts_allowed(channel_id: int) -> bool:
    allowed = _env_id_set("LUNA_DISCORD_VOICE_TTS_CHANNEL_IDS")
    if not allowed:
        return True
    return channel_id in allowed


def _discord_read_bots_enabled() -> bool:
    return _env_truthy("LUNA_DISCORD_CHAT_READ_BOTS", default=False)


def _discord_bot_allowed(author_id: int) -> bool:
    allowed = _env_id_set("LUNA_DISCORD_CHAT_BOT_IDS")
    if not allowed:
        return True
    return author_id in allowed


def _discord_welcome_channel_id() -> int | None:
    raw = (os.environ.get("LUNA_DISCORD_WELCOME_CHANNEL_ID") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _discord_welcome_guild_id() -> int | None:
    raw = (os.environ.get("LUNA_DISCORD_WELCOME_GUILD_ID") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _discord_welcome_enabled() -> bool:
    if not _discord_welcome_channel_id():
        return False
    return _env_truthy("LUNA_DISCORD_WELCOME", default=True)


def _format_discord_welcome(member: Any) -> str:
    guild = getattr(member, "guild", None)
    server = getattr(guild, "name", "the server") if guild is not None else "the server"
    template = (
        os.environ.get("LUNA_DISCORD_WELCOME_MESSAGE")
        or "Welcome to **{server}**, {mention}! I'm Luna — glad you made it. 🐺"
    ).strip()
    display = getattr(member, "display_name", None) or getattr(member, "name", "friend")
    return template.format(
        mention=getattr(member, "mention", display),
        user=display,
        server=server,
        username=getattr(member, "name", display),
    )


_welcome_state_lock = asyncio.Lock()


def _welcome_state_path() -> Path:
    raw = (os.environ.get("LUNA_DISCORD_WELCOME_STATE_PATH") or "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parent / "data" / "discord_welcome_state.json"


def _load_welcome_state() -> dict[str, Any]:
    path = _welcome_state_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_welcome_state(state: dict[str, Any]) -> None:
    path = _welcome_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _local_today() -> str:
    return datetime.now().astimezone().date().isoformat()


def _member_joined_local_today(member: Any) -> bool:
    joined = getattr(member, "joined_at", None)
    if joined is None:
        return False
    try:
        return joined.astimezone().date().isoformat() == _local_today()
    except (ValueError, OSError):
        return False


def _guild_welcome_bucket(state: dict[str, Any], guild_id: int) -> dict[str, Any]:
    key = str(guild_id)
    bucket = state.get(key)
    if not isinstance(bucket, dict):
        bucket = {}
        state[key] = bucket
    welcomed = bucket.get("welcomed_user_ids")
    if not isinstance(welcomed, list):
        bucket["welcomed_user_ids"] = []
    return bucket


def _was_welcomed(state: dict[str, Any], guild_id: int, user_id: int) -> bool:
    bucket = _guild_welcome_bucket(state, guild_id)
    return str(user_id) in bucket.get("welcomed_user_ids", [])


def _mark_welcomed_in_state(state: dict[str, Any], guild_id: int, user_id: int) -> None:
    bucket = _guild_welcome_bucket(state, guild_id)
    ids: list[str] = bucket["welcomed_user_ids"]  # type: ignore[assignment]
    uid = str(user_id)
    if uid not in ids:
        ids.append(uid)


def _discord_luna_triggered(content: str, message: Any, bot_user: Any | None) -> bool:
    """True when the message @-mentions the bot or contains the word luna."""
    if bot_user is not None and bot_user in (getattr(message, "mentions", None) or []):
        return True
    lowered = (content or "").lower()
    if "luna" in lowered:
        return True
    if bot_user is not None:
        bid = bot_user.id
        if f"<@{bid}>" in content or f"<@!{bid}>" in content:
            return True
    ref = getattr(message, "reference", None)
    if ref and bot_user is not None:
        ref_msg = getattr(ref, "resolved", None)
        ref_author = getattr(ref_msg, "author", None) if ref_msg is not None else None
        if ref_author is not None and getattr(ref_author, "id", None) == bot_user.id:
            return True
    return False


def _discord_cast_triggered(content: str, message: Any, bot_user: Any | None) -> bool:
    """True when the message should get a cast reply (Luna, Viktor, or Himari by name)."""
    from luna_cast import public_chat_addressees

    if public_chat_addressees(content, trigger_all=False):
        return True
    return _discord_luna_triggered(content, message, bot_user)


def _discord_cast_trigger_hint() -> str:
    from himari_cohost import himari_name
    from vampire_cohost import cohost_name

    parts = ["@Luna", '"luna"', f'"{cohost_name().lower()}"', f'"{himari_name().lower()}"']
    return "need " + ", ".join(parts) + ", or reply to the bot"


def _chunk_discord(text: str, limit: int = _DISCORD_MSG_CHUNK) -> list[str]:
    text = (text or "").strip()
    if len(text) <= limit:
        return [text] if text else []
    chunks: list[str] = []
    buf = ""
    for line in text.splitlines(keepends=True):
        if len(buf) + len(line) > limit and buf:
            chunks.append(buf)
            buf = ""
        if len(line) > limit:
            for i in range(0, len(line), limit):
                chunks.append(line[i : i + limit])
            buf = ""
            continue
        buf += line
    if buf:
        chunks.append(buf)
    return chunks


def discord_enabled() -> bool:
    if not _DISCORD_AVAILABLE:
        return False
    return bool((os.environ.get("DISCORD_TOKEN") or "").strip())


def _int_env(key: str) -> int:
    raw = (os.environ.get(key) or "").strip()
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


@dataclass
class Track:
    query: str
    title: str
    web_url: str
    stream_url: str
    duration_sec: int | None
    requested_by: str
    uploader: str = ""
    local_path: str | None = None  # TTS / local file — same FFmpeg path as stream tracks


class _GuildPlayer:
    """Per-guild queue + voice client manager."""

    def __init__(self, bot: "LunaDiscordBot", guild_id: int) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.queue: deque[Track] = deque()
        self.current: Track | None = None
        self.voice: "discord.VoiceClient | None" = None
        self._advance_lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        return self.voice is not None and self.voice.is_connected()

    async def ensure_voice(self, channel: "discord.VoiceChannel") -> "discord.VoiceClient | None":
        if self.is_connected:
            if self.voice and self.voice.channel and self.voice.channel.id != channel.id:
                try:
                    await self.voice.move_to(channel)
                except Exception:
                    return None
            return self.voice
        try:
            # self_deaf=True (default for many music bots): we only transmit playback,
            # so we don't subscribe to incoming voice — Discord shows the "deafened" icon.
            # Set LUNA_DISCORD_SELF_DEAF=0 if you prefer the bot to appear not deafened
            # (cosmetic only; this bot still does not process VC audio for STT).
            _deaf = (os.environ.get("LUNA_DISCORD_SELF_DEAF", "1") or "1").strip().lower() not in (
                "0",
                "false",
                "no",
                "off",
            )
            self.voice = await channel.connect(self_deaf=_deaf, reconnect=True)
        except Exception:
            self.voice = None
        return self.voice

    async def leave(self) -> None:
        self.queue.clear()
        self.current = None
        vc = self.voice
        self.voice = None
        if vc is not None:
            try:
                vc.stop()
            except Exception:
                pass
            try:
                await vc.disconnect(force=True)
            except Exception:
                pass

    def add(self, track: Track) -> None:
        self.queue.append(track)

    def skip(self) -> bool:
        if self.voice and self.voice.is_playing():
            self.voice.stop()
            return True
        return False

    def stop_all(self) -> None:
        self.queue.clear()
        if self.voice and (self.voice.is_playing() or self.voice.is_paused()):
            self.voice.stop()

    async def _wait_local_clip_finished(
        self,
        *,
        path: Path | None,
        duration_sec: float,
    ) -> None:
        """Hold the queue until the reply MP3 has played through (ffprobe length + pad)."""
        pad = _discord_voice_tts_pad_sec()
        probed = _probe_media_duration_sec(path) if path and path.is_file() else 0.0
        min_play = max(float(duration_sec or 0), probed, 0.5)
        play_start = time.monotonic()
        hard_deadline = play_start + min_play + pad + 45.0

        while time.monotonic() < hard_deadline:
            vc = self.voice
            still_playing = bool(vc and (vc.is_playing() or vc.is_paused()))
            elapsed = time.monotonic() - play_start
            if not still_playing and elapsed >= min_play - 0.12:
                break
            await asyncio.sleep(0.1)

        while True:
            vc = self.voice
            if not (vc and (vc.is_playing() or vc.is_paused())):
                break
            if time.monotonic() - play_start > min_play + pad + 90.0:
                break
            await asyncio.sleep(0.1)

        elapsed = time.monotonic() - play_start
        tail = min_play + pad - elapsed
        if tail > 0:
            await asyncio.sleep(tail)
        await asyncio.sleep(pad)

    async def _finish_local_playback(
        self,
        loop: asyncio.AbstractEventLoop,
        track: Track,
        cleanup_path: str | None,
        error: BaseException | None,
    ) -> None:
        if error is not None:
            print(f"(discord voice tts) FFmpeg ended: {error}", flush=True)
        path = Path(cleanup_path) if cleanup_path else None
        dur = float(track.duration_sec or 0)
        try:
            await self._wait_local_clip_finished(path=path, duration_sec=dur)
        except Exception as exc:  # noqa: BLE001
            print(f"(discord voice tts) wait failed: {exc}", flush=True)
        if cleanup_path:
            try:
                Path(cleanup_path).unlink(missing_ok=True)
            except OSError:
                pass
        asyncio.run_coroutine_threadsafe(self.play_next(), loop)

    async def play_next(self) -> None:
        async with self._advance_lock:
            if not self.is_connected:
                return
            if self.voice and (self.voice.is_playing() or self.voice.is_paused()):
                return
            if not self.queue:
                self.current = None
                return
            track = self.queue.popleft()
            self.current = track
            audio_src = (track.local_path or track.stream_url or "").strip()
            if not audio_src:
                asyncio.run_coroutine_threadsafe(self.play_next(), asyncio.get_running_loop())
                return

            if track.local_path:
                # Local MP3/WAV from Luna's reply — full file, no stream reconnect flags.
                source = discord.FFmpegPCMAudio(
                    audio_src,
                    before_options=_FFMPEG_LOCAL_BEFORE,
                    options=_FFMPEG_LOCAL_OPTS,
                )
            else:
                source = discord.FFmpegPCMAudio(
                    audio_src,
                    before_options=_FFMPEG_BEFORE_OPTS,
                    options=_FFMPEG_OPTS,
                )

            loop = asyncio.get_running_loop()
            cleanup_path = track.local_path
            is_local_tts = bool(track.local_path)

            if is_local_tts:

                def _after_local(error: BaseException | None) -> None:
                    asyncio.run_coroutine_threadsafe(
                        self._finish_local_playback(loop, track, cleanup_path, error),
                        loop,
                    )

                after_cb = _after_local
            else:

                def _after_stream(error: BaseException | None) -> None:
                    if error is not None:
                        print(f"(discord) FFmpeg playback error: {error}", flush=True)
                    asyncio.run_coroutine_threadsafe(self.play_next(), loop)

                after_cb = _after_stream

            try:
                self.voice.play(source, after=after_cb)  # type: ignore[union-attr]
            except Exception as exc:
                print(f"(discord) play() failed: {exc}", flush=True)
                if cleanup_path:
                    try:
                        Path(cleanup_path).unlink(missing_ok=True)
                    except OSError:
                        pass
                asyncio.run_coroutine_threadsafe(self.play_next(), loop)
                return

            if track.local_path:
                dur = float(track.duration_sec or 0) or _probe_media_duration_sec(
                    Path(track.local_path)
                )
                print(
                    f"(discord voice) playing TTS: {track.title}"
                    + (f" (~{dur:.1f}s)" if dur > 0 else ""),
                    flush=True,
                )
            else:
                await self.bot.announce_now_playing(self.guild_id, track)

    def enqueue_voice_clip(
        self,
        path: Path,
        *,
        title: str = "Luna (TTS)",
        own_file: bool = False,
    ) -> bool:
        """Queue the reply MP3 on the same FFmpeg path as !play.

        When ``own_file`` is True, the queue deletes ``path`` after playback
        (the Discord chat attachment uses the same file until then).
        """
        if not path.is_file() or path.stat().st_size < 32:
            return False
        if own_file:
            dest = str(path.resolve())
        else:
            suffix = path.suffix if path.suffix else ".mp3"
            fd, tmp = tempfile.mkstemp(suffix=suffix, prefix="luna_discord_vc_")
            os.close(fd)
            dest_path = Path(tmp)
            try:
                shutil.copy2(path, dest_path)
            except OSError as exc:
                print(f"(discord voice tts) copy failed: {exc}", flush=True)
                try:
                    dest_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return False
            dest = str(dest_path)
        dur_sec = _probe_media_duration_sec(Path(dest))
        dur_int = int(round(dur_sec)) if dur_sec > 0 else None
        self.add(
            Track(
                query=title,
                title=title,
                web_url="",
                stream_url="",
                duration_sec=dur_int,
                requested_by="Luna",
                uploader="TTS",
                local_path=dest,
            )
        )
        return True

    async def play_voice_clip(
        self,
        path: Path,
        *,
        title: str = "Luna (TTS)",
        own_file: bool = False,
    ) -> bool:
        """Join/play the reply MP3 via the music queue (waits behind current song if needed)."""
        if not self.is_connected or self.voice is None:
            return False
        was_busy = bool(
            self.voice.is_playing() or self.voice.is_paused()  # type: ignore[union-attr]
        )
        if not self.enqueue_voice_clip(path, title=title, own_file=own_file):
            return False
        await self.play_next()
        if was_busy:
            print(f"(discord voice tts) queued behind current audio ({len(self.queue)} waiting)", flush=True)
        else:
            print(f"(discord voice tts) playing reply mp3: {path.name}", flush=True)
        return True


class LunaDiscordBot:
    """Wrapper that owns a discord.ext commands.Bot and per-guild players."""

    def __init__(self, *, prefix: str = "!") -> None:
        if not _DISCORD_AVAILABLE:
            raise RuntimeError("discord.py is not installed. Run: pip install 'discord.py[voice]'")
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        intents.members = True  # on_member_join welcomes
        self.bot = dcommands.Bot(command_prefix=prefix, intents=intents)
        self.players: dict[int, _GuildPlayer] = {}
        self._prefix = prefix
        self._chat_handler: ChatHandler | None = None
        # Per-channel cooldown so Luna doesn't spam in a busy room.
        self._chat_last_reply_ts: dict[int, float] = {}
        # Per-channel single-flight lock so two near-simultaneous messages don't
        # both go to Ollama for the same channel.
        self._chat_locks: dict[int, asyncio.Lock] = {}
        self._register_events_and_commands()

    def set_chat_handler(self, handler: ChatHandler | None) -> None:
        """Wire a coroutine that turns an incoming Discord message into a reply.

        The handler is called as ``handler(author=..., question=...,
        discord_channel_label=..., is_dm=..., voice_channel_label=...)`` and must return the assistant
        reply text (or None to skip sending). Typically this is
        ``LunaTwitchBot.handle_discord_chat`` so memory + viewer + TTS stay in
        sync with Twitch.
        """
        self._chat_handler = handler

    def _chat_lock(self, channel_id: int) -> asyncio.Lock:
        lock = self._chat_locks.get(channel_id)
        if lock is None:
            lock = asyncio.Lock()
            self._chat_locks[channel_id] = lock
        return lock

    async def send_user_dm(self, user: Any, text: str) -> str:
        """Send a DM as the bot. Returns a short status for ``!dm`` replies."""
        import discord as _discord  # noqa: PLC0415

        body = (text or "").strip()
        if not body:
            return "Usage: `!dm @user your message here`"
        if getattr(user, "bot", False):
            return "Can't DM bots."
        label = getattr(user, "display_name", None) or str(user)
        try:
            ch = await user.create_dm()
            await ch.send(body[:_DISCORD_MSG_CHUNK])
            print(f"(discord dm) sent to {user.id} ({label}): {body[:120]}", flush=True)
            return f"DM sent to **{label}**."
        except _discord.Forbidden:
            return (
                "Couldn't DM that user — they may have DMs closed or have blocked the bot."
            )
        except Exception as exc:  # noqa: BLE001
            print(f"(discord dm) failed for {user.id}: {exc}", flush=True)
            return f"DM failed: {exc}"

    async def resolve_welcome_channel(self, guild: Any) -> Any | None:
        import discord as _discord  # noqa: PLC0415

        cid = _discord_welcome_channel_id()
        if cid is None or guild is None:
            return None
        ch = guild.get_channel(cid)
        if ch is None:
            try:
                ch = await self.bot.fetch_channel(cid)
            except Exception as exc:  # noqa: BLE001
                print(f"(discord welcome) fetch_channel({cid}) failed: {exc}", flush=True)
                return None
        if not isinstance(ch, _discord.TextChannel):
            print(f"(discord welcome) channel {cid} is not a text channel", flush=True)
            return None
        if int(ch.guild.id) != int(guild.id):
            return None
        if not ch.permissions_for(guild.me).send_messages:
            print(
                f"(discord welcome) no Send Messages in #{ch.name} ({guild.name})",
                flush=True,
            )
            return None
        return ch

    async def welcome_member(self, member: Any, *, channel: Any | None = None) -> bool:
        """Send the welcome line and remember this user was greeted."""
        if not _discord_welcome_enabled() or getattr(member, "bot", False):
            return False
        guild = getattr(member, "guild", None)
        if guild is None:
            return False
        want_guild = _discord_welcome_guild_id()
        if want_guild is not None and int(guild.id) != want_guild:
            return False
        ch = channel or await self.resolve_welcome_channel(guild)
        if ch is None:
            return False
        async with _welcome_state_lock:
            state = _load_welcome_state()
            if _was_welcomed(state, int(guild.id), int(member.id)):
                return False
        text = _format_discord_welcome(member)
        try:
            await ch.send(text[:1900])
        except Exception as exc:  # noqa: BLE001
            print(f"(discord welcome) send failed: {exc}", flush=True)
            return False
        async with _welcome_state_lock:
            state = _load_welcome_state()
            _mark_welcomed_in_state(state, int(guild.id), int(member.id))
            _save_welcome_state(state)
        print(
            f"(discord welcome) greeted {member.display_name} in #{ch.name} ({guild.name})",
            flush=True,
        )
        try:
            from luna_discord_engagement import note_new_member

            await note_new_member(
                int(guild.id),
                int(member.id),
                str(getattr(member, "display_name", member)),
            )
        except Exception:
            pass
        return True

    async def members_joined_today(self, guild: Any) -> list[Any]:
        """Return non-bot members whose joined_at is today (local timezone)."""
        if guild is None:
            return []
        try:
            if int(guild.member_count or 0) > len(guild.members):
                await guild.chunk()
        except Exception as exc:  # noqa: BLE001
            print(f"(discord welcome) member chunk failed: {exc}", flush=True)
        out: list[Any] = []
        for member in guild.members:
            if getattr(member, "bot", False):
                continue
            if _member_joined_local_today(member):
                out.append(member)
        out.sort(
            key=lambda m: (
                getattr(m, "joined_at").timestamp()
                if getattr(m, "joined_at", None) is not None
                else 0.0
            )
        )
        return out

    def format_today_joins_message(self, guild: Any, members: list[Any]) -> str:
        today = _local_today()
        gname = getattr(guild, "name", "server")
        if not members:
            return f"No new members joined **{gname}** today ({today}) — yet."
        lines = [f"**Joined {gname} today** ({today}) — {len(members)} member(s):"]
        for m in members:
            joined = getattr(m, "joined_at", None)
            at = joined.astimezone().strftime("%H:%M") if joined else "?"
            lines.append(f"• {m.mention} ({m.display_name}) — {at}")
        return "\n".join(lines)[:1900]

    async def check_today_joins(
        self,
        *,
        post_summary: bool = True,
        send_welcomes: bool = True,
    ) -> list[Any]:
        """Find members who joined today; welcome any not yet greeted; optional daily list."""
        if not _discord_welcome_enabled():
            return []
        gid = _discord_welcome_guild_id()
        guild = self.bot.get_guild(gid) if gid else None
        if guild is None:
            cid = _discord_welcome_channel_id()
            if cid:
                for g in self.bot.guilds:
                    if g.get_channel(cid) is not None:
                        guild = g
                        break
        if guild is None:
            print("(discord welcome) guild not found for today-join scan", flush=True)
            return []

        members = await self.members_joined_today(guild)
        names = ", ".join(getattr(m, "display_name", str(m)) for m in members) or ["(none)"]
        print(f"(discord welcome) joined today in {guild.name!r}: {names}", flush=True)

        if send_welcomes:
            ch = await self.resolve_welcome_channel(guild)
            for member in members:
                await self.welcome_member(member, channel=ch)

        if post_summary and _env_truthy("LUNA_DISCORD_WELCOME_TODAY_SUMMARY", default=True):
            ch = await self.resolve_welcome_channel(guild)
            if ch is not None:
                async with _welcome_state_lock:
                    state = _load_welcome_state()
                    bucket = _guild_welcome_bucket(state, int(guild.id))
                    if bucket.get("last_summary_date") == _local_today():
                        return members
                    bucket["last_summary_date"] = _local_today()
                    _save_welcome_state(state)
                try:
                    await ch.send(self.format_today_joins_message(guild, members))
                except Exception as exc:  # noqa: BLE001
                    print(f"(discord welcome) today summary failed: {exc}", flush=True)

        return members

    async def _send_reply_with_audio(
        self,
        channel: Any,
        reply_text: str,
        audio_paths: Path | list[Path] | None,
    ) -> None:
        """Post a Discord reply with optional TTS audio attached to the last chunk.

        Sends text first so it appears in the timeline immediately; voice clip(s)
        attach to the FINAL text chunk (usually one full-length MP3).
        Falls back to text-only if the file upload fails.
        """
        import discord  # local import: optional dependency

        paths: list[Path] = []
        if isinstance(audio_paths, Path):
            paths = [audio_paths]
        elif audio_paths:
            paths = [p for p in audio_paths if isinstance(p, Path) and p.is_file()]

        chunks = _chunk_discord(reply_text) if reply_text else []
        if not chunks:
            for i, path in enumerate(paths):
                try:
                    name = f"luna_tts_{i + 1}.mp3" if len(paths) > 1 else path.name
                    await channel.send(file=discord.File(str(path), filename=name))
                except Exception as exc:  # noqa: BLE001
                    print(f"(discord chat) audio-only send failed: {exc}", flush=True)
            return

        for idx, part in enumerate(chunks):
            is_last = idx == len(chunks) - 1
            try:
                if is_last and paths:
                    files = [
                        discord.File(
                            str(p),
                            filename=(
                                f"luna_tts_{i + 1}{p.suffix or '.mp3'}"
                                if len(paths) > 1
                                else p.name
                            ),
                        )
                        for i, p in enumerate(paths)
                    ]
                    try:
                        await channel.send(content=part, files=files)
                    except Exception as exc:  # noqa: BLE001
                        print(
                            f"(discord chat) audio attach failed, sending text only: {exc}",
                            flush=True,
                        )
                        await channel.send(part)
                else:
                    await channel.send(part)
            except Exception as exc:  # noqa: BLE001
                print(f"(discord chat) send failed: {exc}", flush=True)
                break

    def _player(self, guild_id: int) -> _GuildPlayer:
        if guild_id not in self.players:
            self.players[guild_id] = _GuildPlayer(self, guild_id)
        return self.players[guild_id]

    def _voice_tts_target_channel(
        self,
        guild_id: int,
        *,
        member: Any | None = None,
        guild: Any | None = None,
    ) -> Any | None:
        """Pick a voice channel to speak in: speaker's VC first, else bot VC, else configured homes."""
        import discord  # noqa: PLC0415

        player = self._player(guild_id)

        if member is not None:
            av = getattr(member, "voice", None)
            ch = getattr(av, "channel", None) if av is not None else None
            if ch is not None and isinstance(ch, discord.VoiceChannel):
                return ch

        if player.is_connected and player.voice and player.voice.channel:
            ch = player.voice.channel
            if isinstance(ch, discord.VoiceChannel) and _voice_tts_allowed(ch.id):
                return ch

        allowed = _env_id_set("LUNA_DISCORD_VOICE_TTS_CHANNEL_IDS")
        if guild is not None and allowed:
            for cid in allowed:
                ch = guild.get_channel(cid)
                if ch is not None and isinstance(ch, discord.VoiceChannel):
                    return ch

        return None

    async def play_reply_tts_in_voice(
        self,
        guild_id: int,
        audio_paths: Path | list[Path],
        *,
        member: Any | None = None,
        guild: Any | None = None,
    ) -> bool:
        """Play reply MP3(s) in VC as !play (returns True if any file was queued)."""
        if not _env_truthy("LUNA_DISCORD_VOICE_TTS", default=True):
            return False
        if isinstance(audio_paths, Path):
            paths = [audio_paths]
        else:
            paths = [p for p in audio_paths if isinstance(p, Path) and p.is_file()]
        if not paths:
            print("(discord voice tts) missing mp3", flush=True)
            return False

        player = self._player(guild_id)
        target = self._voice_tts_target_channel(guild_id, member=member, guild=guild)

        if target is None:
            allowed = _env_id_set("LUNA_DISCORD_VOICE_TTS_CHANNEL_IDS")
            if allowed:
                print(
                    "(discord voice tts) skipped — join a voice channel or set "
                    "LUNA_DISCORD_VOICE_TTS_CHANNEL_IDS to a channel Luna can join",
                    flush=True,
                )
            return False

        if not await player.ensure_voice(target):
            print("(discord voice tts) could not join voice channel", flush=True)
            return False
        name = getattr(target, "name", target.id)
        n = len(paths)
        print(
            f"(discord voice tts) joining #{name} — "
            f"{'playing' if n == 1 else f'queuing {n}'} message mp3 in VC",
            flush=True,
        )
        queued = False
        for i, path in enumerate(paths):
            title = "Luna (TTS)" if n == 1 else f"Luna (TTS {i + 1}/{n})"
            if await player.play_voice_clip(path, title=title, own_file=True):
                queued = True
            else:
                print(f"(discord voice tts) could not queue: {path.name}", flush=True)
        return queued

    def _announce_text_channel(self, guild: Any) -> Any | None:
        import discord  # noqa: PLC0415

        forced_id = _int_env("DISCORD_LIVE_ANNOUNCE_CHANNEL_ID")
        if forced_id:
            ch = guild.get_channel(forced_id)
            if ch is not None and isinstance(ch, discord.TextChannel):
                if ch.permissions_for(guild.me).send_messages:
                    return ch
        sys_ch = guild.system_channel
        if sys_ch is not None and sys_ch.permissions_for(guild.me).send_messages:
            return sys_ch
        for c in guild.text_channels:
            if c.permissions_for(guild.me).send_messages:
                return c
        return None

    async def _discord_live_send_payload(
        self,
        channel: Any,
        text: str,
        image_path: str | Path | None,
    ) -> None:
        import discord  # noqa: PLC0415

        content = text[:1900]
        file_obj = None
        if image_path:
            p = Path(image_path).expanduser()
            if p.is_file():
                file_obj = discord.File(str(p))
        if file_obj is not None:
            await channel.send(content=content, file=file_obj)
        else:
            await channel.send(content)

    async def announce_live_to_channel_ids(
        self,
        text: str,
        channel_ids: list[int],
        *,
        image_path: str | Path | None = None,
    ) -> int:
        """Post go-live to specific Discord text channel ids."""
        import discord  # noqa: PLC0415

        if not text.strip() or not channel_ids:
            return 0
        sent = 0
        for cid in channel_ids:
            ch = self.bot.get_channel(cid)
            if ch is None or not isinstance(ch, discord.TextChannel):
                print(f"(discord live) channel {cid} not found or not text", flush=True)
                continue
            if not ch.permissions_for(ch.guild.me).send_messages:
                print(f"(discord live) no send permission in #{ch.name}", flush=True)
                continue
            try:
                await self._discord_live_send_payload(ch, text, image_path)
                sent += 1
                print(f"(discord live) posted in #{ch.name} ({ch.guild.name})", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"(discord live) #{ch.name}: {exc}", flush=True)
        return sent

    async def announce_live_all_guilds(
        self,
        text: str,
        *,
        image_path: str | Path | None = None,
    ) -> int:
        """Post a go-live line to every joined server (system or first writable text channel)."""
        if not text.strip():
            return 0
        sent = 0
        for guild in self.bot.guilds:
            channel = self._announce_text_channel(guild)
            if channel is None:
                print(f"(discord live) skip {guild.name!r}: no writable text channel", flush=True)
                continue
            try:
                await self._discord_live_send_payload(channel, text, image_path)
                sent += 1
                print(f"(discord live) posted in #{channel.name} ({guild.name})", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"(discord live) {guild.name!r}: {exc}", flush=True)
        return sent

    async def announce_now_playing(self, guild_id: int, track: Track) -> None:
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return
        text_id = _int_env("DISCORD_TEXT_CHANNEL_ID")
        channel: Any = None
        if text_id:
            channel = guild.get_channel(text_id)
        if channel is None:
            for c in guild.text_channels:
                if c.permissions_for(guild.me).send_messages:
                    channel = c
                    break
        if channel is None:
            return
        line = short_status_line(
            {
                "title": track.title,
                "uploader": track.uploader,
                "duration_sec": track.duration_sec,
            }
        )
        try:
            await channel.send(f"▶ Now playing: {line}\n{track.web_url}")
        except Exception:
            pass

    async def enqueue_resolved_for_caller_or_autojoin(
        self,
        ctx: "dcommands.Context",
        query: str,
    ) -> str:
        author_voice = (
            ctx.author.voice.channel if (ctx.author and ctx.author.voice) else None
        )
        guild = ctx.guild
        if guild is None:
            return "This command must be used in a server."
        target_channel: Any = author_voice
        if target_channel is None:
            target_channel = self._configured_voice_channel(guild)
        if target_channel is None:
            return "Join a voice channel first, or set DISCORD_VOICE_CHANNEL_ID."

        player = self._player(guild.id)
        if not await player.ensure_voice(target_channel):
            return "Could not join the voice channel."

        return await self._resolve_and_enqueue(
            guild_id=guild.id,
            query=query,
            requested_by=str(ctx.author.display_name if ctx.author else "viewer"),
        )

    async def enqueue_external(
        self,
        *,
        query: str,
        requested_by: str = "Twitch",
    ) -> str:
        """Called from Twitch / panel without a Discord context. Uses configured auto-join."""
        guild_id = _int_env("DISCORD_VOICE_GUILD_ID")
        channel_id = _int_env("DISCORD_VOICE_CHANNEL_ID")
        if not guild_id or not channel_id:
            return "discord: DISCORD_VOICE_GUILD_ID / DISCORD_VOICE_CHANNEL_ID not set"
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return "discord: guild not visible (bot not in server?)"
        channel = guild.get_channel(channel_id)
        if channel is None or not isinstance(channel, discord.VoiceChannel):
            return "discord: voice channel id is not a voice channel"
        player = self._player(guild.id)
        if not await player.ensure_voice(channel):
            return "discord: could not join configured voice channel"
        return await self._resolve_and_enqueue(
            guild_id=guild.id,
            query=query,
            requested_by=requested_by,
        )

    async def _resolve_and_enqueue(
        self,
        *,
        guild_id: int,
        query: str,
        requested_by: str,
    ) -> str:
        ok, payload = await asyncio.to_thread(resolve_track, query)
        if not ok:
            return f"discord: {payload}"
        meta = payload  # type: ignore[assignment]
        track = Track(
            query=query,
            title=meta.get("title") or "(unknown)",
            web_url=meta.get("web_url") or "",
            stream_url=meta.get("stream_url") or "",
            duration_sec=meta.get("duration_sec"),
            uploader=meta.get("uploader") or "",
            requested_by=requested_by,
        )
        if not track.stream_url:
            return "discord: no streamable audio url for that track"
        player = self._player(guild_id)
        player.add(track)
        line = short_status_line(meta)  # type: ignore[arg-type]
        if player.voice and not player.voice.is_playing() and not player.voice.is_paused():
            await player.play_next()
            return f"Now playing: {line}"
        return f"Queued: {line} (position {len(player.queue)})"

    def _configured_voice_channel(self, guild: "discord.Guild") -> "discord.VoiceChannel | None":
        cid = _int_env("DISCORD_VOICE_CHANNEL_ID")
        if not cid:
            return None
        ch = guild.get_channel(cid)
        return ch if isinstance(ch, discord.VoiceChannel) else None

    def _register_events_and_commands(self) -> None:
        bot = self.bot
        outer = self

        @bot.event
        async def on_message(message: "discord.Message") -> None:
            me = bot.user
            is_self_bot = bool(me) and message.author.id == me.id
            if is_self_bot:
                return

            from_other_bot = bool(message.author.bot)
            if from_other_bot:
                if not _discord_read_bots_enabled():
                    return
                if not _discord_bot_allowed(message.author.id):
                    return
            else:
                # Let the command framework see human messages first (!play / !join / …).
                await bot.process_commands(message)

            content = _discord_message_text(message)
            ch_name = getattr(message.channel, "name", message.channel.id)
            if not content:
                if _discord_chat_debug():
                    _discord_chat_log(f"skip #{ch_name}: empty message (no text/embed)")
                return
            if content.startswith(outer._prefix):
                return
            if outer._chat_handler is None:
                _discord_chat_log("skip: chat handler not wired")
                return
            if not _env_truthy("LUNA_DISCORD_CHAT", default=True):
                return

            is_dm = message.guild is None
            if is_dm:
                if from_other_bot:
                    return
                if not _env_truthy("LUNA_DISCORD_CHAT_DM", default=True):
                    return
                channel_label = "DM"
            else:
                if not _channel_allowed_for_chat(message.channel, message.guild):
                    if _discord_chat_debug():
                        gid = int(message.guild.id)
                        cid = int(message.channel.id)
                        key = (gid, cid)
                        if key not in _discord_skip_logged:
                            _discord_skip_logged.add(key)
                            parent = getattr(message.channel, "parent", None)
                            pid = f" (thread parent {parent.id})" if parent else ""
                            gname = getattr(message.guild, "name", message.guild.id)
                            _discord_chat_log(
                                f"skip #{ch_name}{pid} in {gname!r}: channel id {cid} "
                                "not allowed for this server (see LUNA_DISCORD_GUILD_CHAT_CHANNELS)"
                            )
                    return
                channel_label = f"#{ch_name}"

            if (
                not is_dm
                and message.guild is not None
                and not from_other_bot
            ):
                try:
                    from luna_discord_engagement import (
                        engagement_enabled,
                        engagement_guild_ids,
                        record_message,
                    )

                    gid = int(message.guild.id)
                    if engagement_enabled() and gid in engagement_guild_ids():
                        await record_message(
                            gid,
                            channel_id=int(message.channel.id),
                            channel_name=str(ch_name),
                            author_id=int(message.author.id),
                            content=content,
                            is_bot=False,
                        )
                except Exception:
                    pass

            if not _discord_should_reply_to_message(
                content, message, me, is_dm=is_dm, from_other_bot=from_other_bot
            ):
                if _discord_chat_debug():
                    partner = _discord_persona_channel_partner(message)
                    if partner:
                        hint = f"persona channel → {partner}"
                    else:
                        hint = (
                            f"{_discord_cast_trigger_hint()} "
                            f"(LUNA_DISCORD_CHAT_TRIGGER={_discord_chat_trigger_mode(message.guild)})"
                        )
                    _discord_chat_log(f"skip #{ch_name}: {hint}")
                return

            # Per-channel cooldown.
            try:
                cooldown = float(os.environ.get("LUNA_DISCORD_CHAT_COOLDOWN_SEC", "4") or "4")
            except ValueError:
                cooldown = 4.0
            now = time.time()
            last = outer._chat_last_reply_ts.get(message.channel.id, 0.0)
            if cooldown > 0 and (now - last) < cooldown:
                if _discord_chat_debug():
                    _discord_chat_log(f"skip #{ch_name}: cooldown ({cooldown}s)")
                return

            lock = outer._chat_lock(message.channel.id)
            if lock.locked():
                if _discord_chat_debug():
                    _discord_chat_log(f"skip #{ch_name}: already generating a reply")
                return
            async with lock:
                outer._chat_last_reply_ts[message.channel.id] = time.time()
                author_name = getattr(message.author, "display_name", None) or str(message.author)
                if from_other_bot:
                    author_name = f"{author_name} (Discord bot)"
                _discord_chat_log(f"replying in {channel_label} to {author_name}")
                voice_channel_label: str | None = None
                if not is_dm and message.author:
                    av = getattr(message.author, "voice", None)
                    if av and av.channel is not None:
                        voice_channel_label = f"#{av.channel.name}"
                channel_partner = _discord_persona_channel_partner(message)
                try:
                    async with message.channel.typing():
                        result = await outer._chat_handler(
                            author=author_name,
                            question=content,
                            discord_channel_label=channel_label,
                            is_dm=is_dm,
                            voice_channel_label=voice_channel_label,
                            author_is_bot=from_other_bot,
                            channel_partner=channel_partner,
                        )
                except Exception as exc:  # noqa: BLE001
                    print(f"(discord chat) handler error: {exc}", flush=True)
                    return

                # Handler may return a plain str or (str, list[Path] | Path | None).
                audio_paths: list[Path] = []
                if isinstance(result, tuple):
                    reply = result[0] if result else ""
                    if len(result) >= 2 and result[1] is not None:
                        raw_audio = result[1]
                        if isinstance(raw_audio, Path):
                            audio_paths = [raw_audio]
                        elif isinstance(raw_audio, (list, tuple)):
                            for item in raw_audio:
                                try:
                                    p = Path(item)
                                    if p.is_file():
                                        audio_paths.append(p)
                                except TypeError:
                                    continue
                else:
                    reply = result or ""

                if not (reply or "").strip():
                    _discord_chat_log(f"no reply generated for {author_name} (Ollama empty?)")
                    return

                vc_owns_mp3 = False
                try:
                    await outer._send_reply_with_audio(
                        message.channel, reply, audio_paths or None
                    )
                    audio_note = (
                        f", {len(audio_paths)} audio file(s)"
                        if audio_paths
                        else ""
                    )
                    _discord_chat_log(
                        f"sent reply in {channel_label} ({len(reply)} chars{audio_note})"
                    )
                    if (
                        not is_dm
                        and message.guild is not None
                        and audio_paths
                    ):
                        try:
                            vc_owns_mp3 = await outer.play_reply_tts_in_voice(
                                message.guild.id,
                                audio_paths,
                                member=message.author,
                                guild=message.guild,
                            )
                        except Exception as exc:  # noqa: BLE001
                            print(f"(discord voice tts) {exc}", flush=True)
                finally:
                    if not vc_owns_mp3:
                        for path in audio_paths:
                            try:
                                path.unlink(missing_ok=True)
                            except OSError:
                                pass

        @bot.event
        async def on_member_join(member: "discord.Member") -> None:
            await outer.welcome_member(member)

        @bot.event
        async def on_ready() -> None:
            user = bot.user
            print(f"(discord) ready as {user} ({user.id if user else '?'})", flush=True)
            guilds = list(bot.guilds)
            if not guilds:
                print(
                    "(discord) bot is in 0 servers. Invite this bot first: "
                    "https://discord.com/developers/applications → your app → OAuth2 → URL Generator. "
                    "Scopes: bot, applications.commands. Permissions: Connect, Speak, Send Messages.",
                    flush=True,
                )
            else:
                print("(discord) servers visible:", flush=True)
                for g in guilds:
                    print(f"(discord)   - {g.name!r} id={g.id}", flush=True)
            global_allowed = _discord_chat_allowed_channel_ids()
            guild_rules = _discord_guild_chat_channel_rules()
            trigger = (os.environ.get("LUNA_DISCORD_CHAT_TRIGGER") or "mention").strip().lower()
            read_bots = _discord_read_bots_enabled()
            if not _env_truthy("LUNA_DISCORD_CHAT", default=True):
                print("(discord chat) OFF (LUNA_DISCORD_CHAT=0)", flush=True)
            else:
                import discord as _discord  # noqa: PLC0415

                if global_allowed:
                    scope = f"global allowlist ({len(global_allowed)} channel id(s))"
                elif guild_rules:
                    scope = "all servers except per-guild rules below"
                else:
                    scope = "ALL readable text channels in every server"
                print(
                    f"(discord chat) {scope} | trigger={trigger} | read_bots={read_bots}",
                    flush=True,
                )

                async def _log_channel(cid: int, label: str) -> None:
                    ch = bot.get_channel(cid)
                    if ch is None:
                        try:
                            ch = await bot.fetch_channel(cid)
                        except Exception as exc:  # noqa: BLE001
                            print(f"(discord chat)   - {label} id={cid}: not visible ({exc})", flush=True)
                            return
                    name = getattr(ch, "name", cid)
                    guild_name = getattr(getattr(ch, "guild", None), "name", "?")
                    perms = None
                    if getattr(ch, "guild", None) is not None:
                        perms = ch.permissions_for(ch.guild.me)
                    can_read = getattr(perms, "read_messages", True) if perms else True
                    can_send = getattr(perms, "send_messages", True) if perms else True
                    kind = "thread" if isinstance(ch, _discord.Thread) else type(ch).__name__
                    print(
                        f"(discord chat)   - {label} #{name} id={cid} ({guild_name}) "
                        f"read={can_read} send={can_send} [{kind}]",
                        flush=True,
                    )

                for cid_s in sorted(global_allowed):
                    try:
                        await _log_channel(int(cid_s), "global")
                    except ValueError:
                        print(f"(discord chat)   - invalid global id {cid_s!r}", flush=True)

                guild_triggers = _discord_guild_chat_triggers()
                for gid, ch_set in sorted(guild_rules.items()):
                    g = bot.get_guild(gid)
                    gname = g.name if g is not None else str(gid)
                    trig = guild_triggers.get(gid)
                    trig_note = f" trigger={trig}" if trig else ""
                    if ch_set is None:
                        print(
                            f"(discord chat)   server {gname!r} id={gid}: "
                            f"ALL text channels{trig_note}",
                            flush=True,
                        )
                    else:
                        print(
                            f"(discord chat)   server {gname!r} id={gid}: "
                            f"{len(ch_set)} channel(s) only{trig_note}",
                            flush=True,
                        )
                        for cid in sorted(ch_set):
                            await _log_channel(cid, f"{gname}")

                print(
                    "(discord chat) tip: @bot, reply to bot, or say luna / viktor / himari "
                    "(and co-host aliases); set LUNA_DISCORD_CHAT_DEBUG=1 to log skips",
                    flush=True,
                )
                from luna_discord_community import community_setup_enabled

                if community_setup_enabled():
                    print(
                        "(discord community) persona channels (#luna-chat, #viktor-chat, "
                        "#himari-chat) auto-reply; #fan-images/#fan-videos need @bot or a name. "
                        "Owner: !setup-community (create-only, never deletes).",
                        flush=True,
                    )
            if _discord_welcome_enabled():
                cid = _discord_welcome_channel_id()
                gid = _discord_welcome_guild_id()
                print(
                    f"(discord welcome) ON — channel id={cid}"
                    + (f" guild id={gid}" if gid else " (any guild with that channel)"),
                    flush=True,
                )
                print(
                    "(discord welcome) requires Server Members Intent in the Developer Portal",
                    flush=True,
                )
                if _env_truthy("LUNA_DISCORD_WELCOME_CHECK_ON_READY", default=True):

                    async def _scan_today_joins() -> None:
                        try:
                            await bot.wait_until_ready()
                            await asyncio.sleep(8.0)
                            await outer.check_today_joins()
                        except Exception as exc:  # noqa: BLE001
                            print(f"(discord welcome) today-join scan failed: {exc}", flush=True)

                    asyncio.create_task(_scan_today_joins(), name="discord-welcome-today-scan")

                from luna_discord_community import (
                    community_auto_on_ready,
                    community_auto_setup_guild_ids,
                    community_setup_enabled,
                    setup_guild_community,
                )

                if community_setup_enabled() and community_auto_on_ready():
                    ids = community_auto_setup_guild_ids()

                    async def _auto_community_setup() -> None:
                        await bot.wait_until_ready()
                        await asyncio.sleep(6.0)
                        for gid in ids:
                            guild = bot.get_guild(int(gid))
                            if guild is None:
                                continue
                            try:
                                created, notes = await setup_guild_community(guild)
                                if created:
                                    print(
                                        f"(discord community) {guild.name!r}: "
                                        + ", ".join(created),
                                        flush=True,
                                    )
                                for n in notes:
                                    print(f"(discord community) {n}", flush=True)
                            except Exception as exc:  # noqa: BLE001
                                print(
                                    f"(discord community) setup failed for {gid}: {exc}",
                                    flush=True,
                                )

                    asyncio.create_task(
                        _auto_community_setup(), name="discord-community-auto-setup"
                    )
                    if ids:
                        print(
                            f"(discord community) auto-setup on ready for guild(s): "
                            + ", ".join(str(i) for i in sorted(ids)),
                            flush=True,
                        )

                from luna_discord_engagement import (
                    daily_post_enabled,
                    engagement_enabled,
                    engagement_guild_ids,
                    engagement_loop,
                )

                if engagement_enabled():
                    asyncio.create_task(engagement_loop(bot), name="discord-engagement-loop")
                    if daily_post_enabled() and engagement_guild_ids():
                        print(
                            "(discord engagement) daily fan posts ON for guild(s): "
                            + ", ".join(str(i) for i in sorted(engagement_guild_ids())),
                            flush=True,
                        )

                from luna_discord_private_duty_dm import (
                    private_duty_dm_enabled,
                    private_duty_dm_loop,
                    private_duty_dm_owner_ids,
                )

                if private_duty_dm_enabled():
                    if private_duty_dm_owner_ids():
                        asyncio.create_task(
                            private_duty_dm_loop(bot),
                            name="discord-private-duty-dm",
                        )
                    else:
                        print(
                            "(discord private) duty DM enabled but no recipient — set "
                            "LUNA_OWNER_DISCORD_ID (or LUNA_DISCORD_PRIVATE_DUTY_DM_USER_ID) in .env",
                            flush=True,
                        )
                else:
                    print(
                        "(discord private) Viktor hourly duty DMs OFF — set "
                        "LUNA_DISCORD_PRIVATE_DUTY_DM=1 and LUNA_OWNER_DISCORD_ID in .env, then restart",
                        flush=True,
                    )
            guild_id = _int_env("DISCORD_VOICE_GUILD_ID")
            channel_id = _int_env("DISCORD_VOICE_CHANNEL_ID")
            if guild_id and channel_id:
                guild = bot.get_guild(guild_id)
                if guild is None:
                    print(
                        f"(discord) WARNING: DISCORD_VOICE_GUILD_ID={guild_id} is not a server this bot is in. "
                        "Either invite the bot to that server, or set DISCORD_VOICE_GUILD_ID to one of the ids printed above.",
                        flush=True,
                    )
                    return
                ch = guild.get_channel(channel_id)
                if ch is None:
                    print(
                        f"(discord) WARNING: DISCORD_VOICE_CHANNEL_ID={channel_id} is not a channel in {guild.name!r}.",
                        flush=True,
                    )
                    return
                if not isinstance(ch, discord.VoiceChannel):
                    print(
                        f"(discord) WARNING: channel id {channel_id} ({ch.name!r}) is not a voice channel.",
                        flush=True,
                    )
                    return
                player = outer._player(guild.id)
                vc = await player.ensure_voice(ch)
                if vc is None:
                    print(
                        f"(discord) WARNING: could not join #{ch.name}. Check Connect+Speak permissions for the bot.",
                        flush=True,
                    )
                else:
                    print(f"(discord) auto-joined #{ch.name} in {guild.name!r}", flush=True)

        @bot.command(name="setup-community", aliases=["community-setup", "setup-server"])
        async def cmd_setup_community(ctx: dcommands.Context) -> None:
            """Create Luna/Viktor/Himari chat + fan gallery channels (never deletes)."""
            from luna_discord_community import (
                community_setup_enabled,
                format_setup_report,
                setup_guild_community,
            )

            if not community_setup_enabled():
                await ctx.reply(
                    "Community setup is disabled (`LUNA_DISCORD_COMMUNITY_SETUP=0`)."
                )
                return
            if ctx.guild is None:
                await ctx.reply("Run this in the server you want to set up.")
                return
            if not _can_use_discord_dm_command(ctx.author.id):
                await ctx.reply(
                    "Only the streamer/owner can run this. Set `LUNA_OWNER_DISCORD_ID` in `.env`."
                )
                return
            await ctx.reply("Setting up community channels (create-only, nothing deleted)…")
            created, notes = await setup_guild_community(ctx.guild)
            report = format_setup_report(ctx.guild, created, notes)
            await ctx.reply(report[:1900])

        @bot.command(name="dm")
        async def cmd_dm(ctx: dcommands.Context, user: "discord.User", *, message: str) -> None:
            """Send a DM to a user (streamer only). Works in servers or in DM with the bot."""
            if not discord_dm_command_enabled():
                await ctx.reply("`!dm` is disabled (set `LUNA_DISCORD_DM_COMMAND=1`).")
                return
            if not _can_use_discord_dm_command(ctx.author.id):
                await ctx.reply(
                    "Only allowed owners can use `!dm`. Add your Discord user id to "
                    "`LUNA_OWNER_DISCORD_ID` in `.env` (Developer Mode → right-click your "
                    "profile → Copy User ID), then restart the bot."
                )
                return
            result = await outer.send_user_dm(user, message)
            await ctx.reply(result[:_DISCORD_MSG_CHUNK])

        @bot.command(name="daily-post", aliases=["daily", "wolfden-daily"])
        async def cmd_daily_post(ctx: dcommands.Context) -> None:
            """Post today's Wolf Den engagement message now (owner only)."""
            from luna_discord_engagement import daily_post_enabled, try_post_daily

            if not daily_post_enabled():
                await ctx.reply(
                    "Daily posts are off (`LUNA_DISCORD_DAILY_POST=0` or engagement disabled)."
                )
                return
            if ctx.guild is None:
                await ctx.reply("Run this in the server you want the daily post in.")
                return
            if not _can_use_discord_dm_command(ctx.author.id):
                await ctx.reply("Only the streamer/owner can run this.")
                return
            await ctx.reply("Writing today's Wolf Den daily…")
            ok = await try_post_daily(bot, ctx.guild, force=True)
            if ok:
                await ctx.reply("Posted today's daily engagement message.")
            else:
                await ctx.reply(
                    "Could not post (check bot permissions, `LUNA_DISCORD_DAILY_CHANNEL_ID`, "
                    "or logs). If already posted today, only one automatic post runs per day."
                )

        @bot.command(name="joins_today", aliases=["joined_today", "joinstoday"])
        async def cmd_joins_today(ctx: dcommands.Context) -> None:
            if ctx.guild is None:
                await ctx.reply("Use this in a server.")
                return
            gid = _discord_welcome_guild_id()
            if gid is not None and int(ctx.guild.id) != gid:
                await ctx.reply("Today-join check is only configured for another server.")
                return
            await ctx.reply("Checking who joined today…")
            members = await outer.check_today_joins(post_summary=False, send_welcomes=True)
            msg = outer.format_today_joins_message(ctx.guild, members)
            await ctx.reply(msg[:1900])

        @bot.command(name="join")
        async def cmd_join(ctx: dcommands.Context) -> None:
            if ctx.guild is None:
                await ctx.reply("Use this in a server.")
                return
            if not (ctx.author and ctx.author.voice and ctx.author.voice.channel):
                await ctx.reply("Join a voice channel first, then run `!join` — I need to see which channel you're in.")
                return
            ch = ctx.author.voice.channel
            player = outer._player(ctx.guild.id)
            vc = await player.ensure_voice(ch)
            if vc:
                await ctx.reply(
                    f"I see you in voice **{ch.name}**. Joining that channel now — "
                    "I'll include it in context when you chat here."
                )
            else:
                await ctx.reply("Could not join voice.")

        @bot.command(name="leave", aliases=["dc", "disconnect"])
        async def cmd_leave(ctx: dcommands.Context) -> None:
            if ctx.guild is None:
                return
            player = outer._player(ctx.guild.id)
            await player.leave()
            await ctx.reply("Left voice.")

        @bot.command(name="play", aliases=["p"])
        async def cmd_play(ctx: dcommands.Context, *, query: str | None = None) -> None:
            text = (query or "").strip()
            if not text:
                await ctx.reply("Usage: `!play <YouTube url or search terms>`")
                return
            msg = await outer.enqueue_resolved_for_caller_or_autojoin(ctx, text)
            await ctx.reply(msg)

        @bot.command(name="skip", aliases=["next"])
        async def cmd_skip(ctx: dcommands.Context) -> None:
            if ctx.guild is None:
                return
            player = outer._player(ctx.guild.id)
            if player.skip():
                await ctx.reply("Skipped.")
            else:
                await ctx.reply("Nothing playing.")

        @bot.command(name="stop")
        async def cmd_stop(ctx: dcommands.Context) -> None:
            if ctx.guild is None:
                return
            player = outer._player(ctx.guild.id)
            player.stop_all()
            await ctx.reply("Stopped and cleared queue.")

        @bot.command(name="pause")
        async def cmd_pause(ctx: dcommands.Context) -> None:
            if ctx.guild is None:
                return
            player = outer._player(ctx.guild.id)
            if player.voice and player.voice.is_playing():
                player.voice.pause()
                await ctx.reply("Paused.")

        @bot.command(name="resume")
        async def cmd_resume(ctx: dcommands.Context) -> None:
            if ctx.guild is None:
                return
            player = outer._player(ctx.guild.id)
            if player.voice and player.voice.is_paused():
                player.voice.resume()
                await ctx.reply("Resumed.")

        @bot.command(name="queue", aliases=["q"])
        async def cmd_queue(ctx: dcommands.Context) -> None:
            if ctx.guild is None:
                return
            player = outer._player(ctx.guild.id)
            lines: list[str] = []
            if player.current is not None:
                lines.append(f"▶ {player.current.title}")
            for i, t in enumerate(list(player.queue)[:10], start=1):
                lines.append(f"{i}. {t.title}")
            if not lines:
                lines = ["Queue empty."]
            await ctx.reply("\n".join(lines)[:1900])

        @bot.command(name="nowplaying", aliases=["np"])
        async def cmd_np(ctx: dcommands.Context) -> None:
            if ctx.guild is None:
                return
            player = outer._player(ctx.guild.id)
            if player.current is None:
                await ctx.reply("Nothing playing.")
                return
            await ctx.reply(f"▶ {player.current.title}\n{player.current.web_url}")

    async def start(self, token: str) -> None:
        await self.bot.start(token)

    async def close(self) -> None:
        for player in list(self.players.values()):
            try:
                await player.leave()
            except Exception:
                pass
        try:
            await self.bot.close()
        except Exception:
            pass
