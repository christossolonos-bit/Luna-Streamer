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
  LUNA_DISCORD_CHAT_CHANNEL_IDS    Optional comma-separated allowlist of text channel ids.
                                   Empty = all text channels Luna can see.
  LUNA_DISCORD_CHAT_DM             1 to also reply to DMs (default 1).
  LUNA_DISCORD_CHAT_COOLDOWN_SEC   Min seconds between Luna replies per channel. Default 4.
  LUNA_DISCORD_TTS                 1 to attach a TTS voice clip of Luna's reply under the
                                   text in Discord chat (default 1). The clip is generated
                                   per-reply and uploaded as a file; it does NOT play on
                                   the streamer's local speakers (the VRM viewer's TTS is
                                   skipped for Discord-originated messages).
"""

from __future__ import annotations

import asyncio
import os
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


def _channel_allowed_for_chat(channel_id: int) -> bool:
    raw = (os.environ.get("LUNA_DISCORD_CHAT_CHANNEL_IDS") or "").strip()
    if not raw:
        return True
    allowed = {s.strip() for s in raw.split(",") if s.strip()}
    return str(channel_id) in allowed


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
            source = discord.FFmpegPCMAudio(
                track.stream_url,
                before_options=_FFMPEG_BEFORE_OPTS,
                options=_FFMPEG_OPTS,
            )

            loop = asyncio.get_running_loop()

            def _after(error: BaseException | None) -> None:
                if error is not None:
                    print(f"(discord) FFmpeg playback error: {error}", flush=True)
                asyncio.run_coroutine_threadsafe(self.play_next(), loop)

            try:
                self.voice.play(source, after=_after)  # type: ignore[union-attr]
            except Exception as exc:
                print(f"(discord) play() failed: {exc}", flush=True)
                # Try the next track instead of stalling forever.
                asyncio.run_coroutine_threadsafe(self.play_next(), loop)
                return

            await self.bot.announce_now_playing(self.guild_id, track)


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
        discord_channel_label=..., is_dm=...)`` and must return the assistant
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
            # Ignore our own messages and other bots so we never loop on
            # bot-to-bot chatter.
            if message.author.bot:
                return
            # Always let the command framework see the message first so
            # !play / !join / !skip etc. keep working.
            await bot.process_commands(message)

            content = (message.content or "").strip()
            if not content:
                return
            if content.startswith(outer._prefix):
                return
            if outer._chat_handler is None:
                return
            if not _env_truthy("LUNA_DISCORD_CHAT", default=True):
                return

            is_dm = message.guild is None
            if is_dm:
                if not _env_truthy("LUNA_DISCORD_CHAT_DM", default=True):
                    return
                channel_label = "DM"
            else:
                if not _channel_allowed_for_chat(message.channel.id):
                    return
                channel_label = f"#{getattr(message.channel, 'name', message.channel.id)}"

            # Trigger gate: "all" answers everything, "mention" needs an explicit
            # ping or the word "luna" in the message.
            trigger = (os.environ.get("LUNA_DISCORD_CHAT_TRIGGER") or "mention").strip().lower()
            if not is_dm and trigger != "all":
                me = bot.user
                mentioned = bool(me) and me in (message.mentions or [])
                lowered = content.lower()
                name_hit = "luna" in lowered
                if not (mentioned or name_hit):
                    return

            # Per-channel cooldown.
            try:
                cooldown = float(os.environ.get("LUNA_DISCORD_CHAT_COOLDOWN_SEC", "4") or "4")
            except ValueError:
                cooldown = 4.0
            now = time.time()
            last = outer._chat_last_reply_ts.get(message.channel.id, 0.0)
            if cooldown > 0 and (now - last) < cooldown:
                return

            lock = outer._chat_lock(message.channel.id)
            if lock.locked():
                return
            async with lock:
                outer._chat_last_reply_ts[message.channel.id] = time.time()
                author_name = getattr(message.author, "display_name", None) or str(message.author)
                try:
                    async with message.channel.typing():
                        result = await outer._chat_handler(
                            author=author_name,
                            question=content,
                            discord_channel_label=channel_label,
                            is_dm=is_dm,
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

                try:
                    await outer._send_reply_with_audio(message.channel, reply, audio_path)
                finally:
                    if audio_path is not None:
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
                await ctx.reply("Join a voice channel first.")
                return
            player = outer._player(ctx.guild.id)
            vc = await player.ensure_voice(ctx.author.voice.channel)
            if vc:
                await ctx.reply(f"Joined #{ctx.author.voice.channel.name}.")
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
