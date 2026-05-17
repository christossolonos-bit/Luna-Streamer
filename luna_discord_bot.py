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
                                   "mention" (only when bot is @-mentioned or "luna" appears).
                                   Default "mention".
  LUNA_DISCORD_CHAT_CHANNEL_IDS    Optional global allowlist (all servers). Empty = all channels
                                   except servers listed in LUNA_DISCORD_GUILD_CHAT_CHANNELS.
  LUNA_DISCORD_GUILD_CHAT_CHANNELS Per-server allowlists: guild_id:channel_id[,channel_id…]
                                   separated by spaces. Example:
                                   1464575233783631886:1505683058601361488
  LUNA_DISCORD_CHAT_READ_BOTS      1 to treat other bots like users in allowed channels (default 0).
                                   Bots must still @-mention Luna or say "luna" (even if TRIGGER=all).
  LUNA_DISCORD_CHAT_BOT_IDS        Optional comma-separated bot user ids; empty = any bot (not self).
  LUNA_DISCORD_CHAT_DEBUG          1 to log skipped messages and reasons (default 0).
  LUNA_DISCORD_CHAT_DM             1 to also reply to DMs (default 1).
  LUNA_DISCORD_CHAT_COOLDOWN_SEC   Min seconds between Luna replies per channel. Default 4.
  LUNA_DISCORD_TTS                 1 to attach a TTS voice clip of Luna's reply under the
                                   text in Discord chat (default 1). The clip is generated
                                   per-reply and uploaded as a file; it does NOT play on
                                   the streamer's local speakers (the VRM viewer's TTS is
                                   skipped for Discord-originated messages).
  LUNA_DISCORD_VOICE_TTS           If 1 (default), after a chat reply Luna queues TTS in the
                                   same voice pipeline as !play (FFmpeg queue; waits behind songs).
  LUNA_DISCORD_VOICE_TTS_CHANNEL_IDS  Optional comma-separated voice channel ids Luna may join
                                   to speak when you are not in VC (you are always followed
                                   into your current voice channel). Empty = only VCs she is
                                   already connected to.
  Voice context                    When the author is in a voice channel, Luna's model
                                   prompt includes which VC they are in (so she can refer
                                   to it). !join replies also name that channel explicitly.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
from collections import deque
from dataclasses import dataclass
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

# Discord hard cap is 2000 chars per message; leave a little headroom.
_DISCORD_MSG_CHUNK = 1900

# Handler may return either ``reply`` (str) or ``(reply, audio_path | None)``.
ChatHandler = Callable[..., Awaitable[Any]]


def _env_truthy(key: str, default: bool = False) -> bool:
    raw = (os.environ.get(key, "") or "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def _discord_chat_allowed_channel_ids() -> frozenset[str]:
    raw = (os.environ.get("LUNA_DISCORD_CHAT_CHANNEL_IDS") or "").strip()
    if not raw:
        return frozenset()
    return frozenset(s.strip() for s in raw.replace(" ", ",").split(",") if s.strip())


def _discord_guild_chat_channel_rules() -> dict[int, frozenset[int]]:
    """Parse LUNA_DISCORD_GUILD_CHAT_CHANNELS → {guild_id: {channel_id, …}}."""
    raw = (os.environ.get("LUNA_DISCORD_GUILD_CHAT_CHANNELS") or "").strip()
    if not raw:
        return {}
    rules: dict[int, set[int]] = {}
    for entry in raw.replace(";", " ").split():
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        guild_s, ch_part = entry.split(":", 1)
        try:
            guild_id = int(guild_s.strip())
        except ValueError:
            continue
        ch_ids: set[int] = set()
        for part in ch_part.replace(" ", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ch_ids.add(int(part))
            except ValueError:
                continue
        if ch_ids:
            rules[guild_id] = rules.get(guild_id, set()) | ch_ids
    return {gid: frozenset(cids) for gid, cids in rules.items()}


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
        guild_rules = _discord_guild_chat_channel_rules()
        allowed = guild_rules.get(int(guild.id))
        if allowed is not None:
            return any(cid in allowed for cid in candidates)

    global_allowed = _discord_chat_allowed_channel_ids()
    if not global_allowed:
        return True
    return any(str(cid) in global_allowed for cid in candidates)


def _discord_chat_debug() -> bool:
    return _env_truthy("LUNA_DISCORD_CHAT_DEBUG", default=False)


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


def _discord_luna_triggered(content: str, message: Any, bot_user: Any | None) -> bool:
    """True when the message @-mentions Luna or contains the word luna."""
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
                # Local MP3/WAV from Luna's reply — no stream reconnect flags.
                source = discord.FFmpegPCMAudio(audio_src, options=_FFMPEG_OPTS)
            else:
                source = discord.FFmpegPCMAudio(
                    audio_src,
                    before_options=_FFMPEG_BEFORE_OPTS,
                    options=_FFMPEG_OPTS,
                )

            loop = asyncio.get_running_loop()
            cleanup_path = track.local_path

            def _after(error: BaseException | None) -> None:
                if error is not None:
                    print(f"(discord) FFmpeg playback error: {error}", flush=True)
                if cleanup_path:
                    try:
                        Path(cleanup_path).unlink(missing_ok=True)
                    except OSError:
                        pass
                asyncio.run_coroutine_threadsafe(self.play_next(), loop)

            try:
                self.voice.play(source, after=_after)  # type: ignore[union-attr]
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
                print(f"(discord voice) playing TTS: {track.title}", flush=True)
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
        self.add(
            Track(
                query=title,
                title=title,
                web_url="",
                stream_url="",
                duration_sec=None,
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

    async def _send_reply_with_audio(
        self,
        channel: Any,
        reply_text: str,
        audio_path: Path | None,
    ) -> None:
        """Post a Discord reply with optional TTS audio attached to the last chunk.

        Sends text first so it appears in the timeline immediately; the voice
        clip is attached to the FINAL text chunk so it renders right under
        the text. If the reply is empty but audio exists, just sends the
        audio. Falls back to text-only if the file upload fails.
        """
        import discord  # local import: optional dependency

        chunks = _chunk_discord(reply_text) if reply_text else []
        # No text? Just send the audio if we have it.
        if not chunks:
            if audio_path is not None and audio_path.exists():
                try:
                    await channel.send(file=discord.File(str(audio_path), filename=audio_path.name))
                except Exception as exc:  # noqa: BLE001
                    print(f"(discord chat) audio-only send failed: {exc}", flush=True)
            return

        for idx, part in enumerate(chunks):
            is_last = idx == len(chunks) - 1
            try:
                if is_last and audio_path is not None and audio_path.exists():
                    try:
                        await channel.send(
                            content=part,
                            file=discord.File(str(audio_path), filename=audio_path.name),
                        )
                    except Exception as exc:  # noqa: BLE001
                        print(f"(discord chat) audio attach failed, sending text only: {exc}", flush=True)
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
        audio_path: Path,
        *,
        member: Any | None = None,
        guild: Any | None = None,
    ) -> bool:
        """Play the same reply MP3 in VC as !play (returns True if the file was queued)."""
        if not _env_truthy("LUNA_DISCORD_VOICE_TTS", default=True):
            return False
        if not audio_path.is_file():
            print(f"(discord voice tts) missing mp3: {audio_path}", flush=True)
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
        print(f"(discord voice tts) joining #{name} — playing message mp3 in VC", flush=True)
        ok = await player.play_voice_clip(audio_path, own_file=True)
        if not ok:
            print("(discord voice tts) could not queue reply mp3", flush=True)
        return ok

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

    async def announce_live_all_guilds(self, text: str) -> int:
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
                await channel.send(text[:1900])
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
                        parent = getattr(message.channel, "parent", None)
                        pid = f" (thread parent {parent.id})" if parent else ""
                        gname = getattr(message.guild, "name", message.guild.id)
                        _discord_chat_log(
                            f"skip #{ch_name}{pid} in {gname!r}: channel id {message.channel.id} "
                            "not allowed for this server (see LUNA_DISCORD_GUILD_CHAT_CHANNELS)"
                        )
                    return
                channel_label = f"#{ch_name}"

            # Trigger: humans honor TRIGGER=all|mention; other bots always need @Luna / "luna".
            trigger = (os.environ.get("LUNA_DISCORD_CHAT_TRIGGER") or "mention").strip().lower()
            if from_other_bot or (not is_dm and trigger != "all"):
                if not _discord_luna_triggered(content, message, me):
                    if _discord_chat_debug():
                        _discord_chat_log(
                            f"skip #{ch_name}: need @Luna or 'luna' in text "
                            f"(LUNA_DISCORD_CHAT_TRIGGER={trigger})"
                        )
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
                try:
                    async with message.channel.typing():
                        result = await outer._chat_handler(
                            author=author_name,
                            question=content,
                            discord_channel_label=channel_label,
                            is_dm=is_dm,
                            voice_channel_label=voice_channel_label,
                            author_is_bot=from_other_bot,
                        )
                except Exception as exc:  # noqa: BLE001
                    print(f"(discord chat) handler error: {exc}", flush=True)
                    return

                # Handler may return either a plain str or (str, audio_path|None).
                audio_path: Path | None = None
                if isinstance(result, tuple):
                    reply = result[0] if result else ""
                    if len(result) >= 2 and result[1] is not None:
                        try:
                            audio_path = Path(result[1])  # type: ignore[arg-type]
                        except TypeError:
                            audio_path = None
                else:
                    reply = result or ""

                if not (reply or "").strip():
                    _discord_chat_log(f"no reply generated for {author_name} (Ollama empty?)")
                    return

                vc_owns_mp3 = False
                try:
                    await outer._send_reply_with_audio(message.channel, reply, audio_path)
                    _discord_chat_log(f"sent reply in {channel_label} ({len(reply)} chars)")
                    if (
                        not is_dm
                        and message.guild is not None
                        and audio_path is not None
                        and audio_path.exists()
                    ):
                        try:
                            vc_owns_mp3 = await outer.play_reply_tts_in_voice(
                                message.guild.id,
                                audio_path,
                                member=message.author,
                                guild=message.guild,
                            )
                        except Exception as exc:  # noqa: BLE001
                            print(f"(discord voice tts) {exc}", flush=True)
                finally:
                    if audio_path is not None and not vc_owns_mp3:
                        try:
                            audio_path.unlink(missing_ok=True)
                        except OSError:
                            pass

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

                for gid, ch_set in sorted(guild_rules.items()):
                    g = bot.get_guild(gid)
                    gname = g.name if g is not None else str(gid)
                    print(
                        f"(discord chat)   server {gname!r} id={gid}: "
                        f"{len(ch_set)} channel(s) only",
                        flush=True,
                    )
                    for cid in sorted(ch_set):
                        await _log_channel(cid, f"{gname}")

                print(
                    "(discord chat) tip: @Luna or include 'luna' in each message; "
                    "set LUNA_DISCORD_CHAT_DEBUG=1 to log skips",
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
