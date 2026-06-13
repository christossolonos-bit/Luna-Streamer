"""Private hourly Viktor DMs to the owner — isolated from engagement, chat, and viewer.

Every message is generated fresh by the local LLM (no canned scripts).
Themes: duty, honor, self-mastery, and becoming a respected man — in all of life.
Enable only with LUNA_DISCORD_PRIVATE_DUTY_DM=1 and LUNA_OWNER_DISCORD_ID set.
Uses Viktor's Edge voice for a follow-up MP3 when LUNA_DISCORD_TTS=1 (same as Luna DMs).
Each reminder MP3 (and .txt transcript) is archived under ``viktor 's wisdom for men/`` for CapCut/YouTube.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ollama_client import build_client, chat_request_kwargs, strip_think_blocks
from vampire_cohost import build_vampire_system_prompt, cohost_name

_DISCORD_DM_MAX = 1900

_LIFE_ANGLES: tuple[str, ...] = (
    "friendship and loyalty",
    "romantic restraint and dignity",
    "family or the people who depend on him",
    "solitude and what he does when bored",
    "reputation and keeping his word",
    "pride, ego, and not needing the last word",
    "physical desire versus long-term purpose",
    "courage in a small uncomfortable conversation",
    "how he spends money, time, and attention",
    "patience when he feels overlooked",
    "apologizing without excuses",
    "building habits that match the man he wants to be",
)


def _env_truthy(key: str, *, default: bool = False) -> bool:
    raw = (os.environ.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def private_duty_dm_enabled() -> bool:
    return _env_truthy("LUNA_DISCORD_PRIVATE_DUTY_DM", default=False)


def private_duty_dm_discord_tts_enabled() -> bool:
    """Follow-up MP3 on private Viktor DMs (defaults to LUNA_DISCORD_TTS)."""
    raw = (os.environ.get("LUNA_DISCORD_PRIVATE_DUTY_DM_TTS") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return _env_truthy("LUNA_DISCORD_TTS", default=True)


def private_duty_dm_archive_enabled() -> bool:
    return _env_truthy("LUNA_DISCORD_PRIVATE_DUTY_DM_ARCHIVE", default=True)


def private_duty_dm_archive_dir() -> Path:
    raw = (os.environ.get("LUNA_DISCORD_PRIVATE_DUTY_DM_ARCHIVE_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path(__file__).resolve().parent / "viktor 's wisdom for men").resolve()


def _archive_filename_stem(*, when: float | None = None, dt: datetime | None = None) -> str:
    if dt is not None:
        return dt.strftime("viktor-wisdom_%Y-%m-%d_%H-%M-%S")
    ts = when if when is not None else time.time()
    return datetime.fromtimestamp(ts).strftime("viktor-wisdom_%Y-%m-%d_%H-%M-%S")


def _unique_archive_stem(dt: datetime, dest_dir: Path) -> str:
    base = _archive_filename_stem(dt=dt)
    stem = base
    n = 0
    while (dest_dir / f"{stem}.mp3").exists() or (dest_dir / f"{stem}.txt").exists():
        n += 1
        stem = f"{base}_{n}"
    return stem


def _save_duty_reminder_archive(
    text: str,
    audio_paths: list[Path],
    *,
    when: float | None = None,
    dt: datetime | None = None,
    stem: str | None = None,
) -> list[Path]:
    """Copy Viktor duty MP3(s) + transcript into the wisdom archive folder."""
    if not private_duty_dm_archive_enabled() or not audio_paths:
        return []
    dest_dir = private_duty_dm_archive_dir()
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"(discord private) wisdom archive mkdir failed: {exc}", flush=True)
        return []

    if not stem:
        stem = _unique_archive_stem(dt or datetime.fromtimestamp(when or time.time()), dest_dir)
    saved: list[Path] = []
    for i, src in enumerate(audio_paths):
        if not src.is_file():
            continue
        suffix = src.suffix or ".mp3"
        name = f"{stem}{suffix}" if len(audio_paths) == 1 else f"{stem}_part{i + 1}{suffix}"
        dest = dest_dir / name
        try:
            shutil.copy2(src, dest)
            saved.append(dest)
        except OSError as exc:
            print(f"(discord private) wisdom archive mp3 failed: {exc}", flush=True)

    body = (text or "").strip()
    if body and saved:
        txt_path = dest_dir / f"{stem}.txt"
        try:
            txt_path.write_text(body + "\n", encoding="utf-8")
            saved.append(txt_path)
        except OSError as exc:
            print(f"(discord private) wisdom archive txt failed: {exc}", flush=True)

    if saved:
        print(
            f"(discord private) wisdom archived ({len([p for p in saved if p.suffix == '.mp3'])} mp3) -> {dest_dir}",
            flush=True,
        )
    return saved


def _parse_discord_user_ids(raw: str) -> frozenset[int]:
    out: set[int] = set()
    for part in (raw or "").replace(";", ",").split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.add(int(p))
        except ValueError:
            continue
    return frozenset(out)


def private_duty_dm_owner_ids() -> frozenset[int]:
    """Recipient(s) for private Viktor duty DMs (same owner ids as ``!dm`` when unset)."""
    explicit = (os.environ.get("LUNA_DISCORD_PRIVATE_DUTY_DM_USER_ID") or "").strip()
    if explicit:
        return _parse_discord_user_ids(explicit)
    raw = (
        os.environ.get("LUNA_OWNER_DISCORD_ID")
        or os.environ.get("DISCORD_DM_OWNER_ID")
        or ""
    ).strip()
    return _parse_discord_user_ids(raw)


def private_duty_dm_interval_sec() -> float:
    raw = (os.environ.get("LUNA_DISCORD_PRIVATE_DUTY_DM_INTERVAL_SEC") or "3600").strip() or "3600"
    try:
        sec = float(raw)
    except ValueError:
        sec = 3600.0
    return max(300.0, min(sec, 86_400.0))


def private_duty_dm_model() -> str:
    return (
        (os.environ.get("LUNA_DISCORD_PRIVATE_DUTY_DM_MODEL") or "").strip()
        or (os.environ.get("LUNA_CHAT_MODEL") or "").strip()
        or "qwen3.5:4b"
    )


def private_duty_dm_max_retries() -> int:
    raw = (os.environ.get("LUNA_DISCORD_PRIVATE_DUTY_DM_RETRIES") or "2").strip() or "2"
    try:
        n = int(raw)
    except ValueError:
        n = 2
    return max(0, min(n, 5))


def _state_path() -> Path:
    raw = (os.environ.get("LUNA_DISCORD_PRIVATE_DUTY_DM_STATE_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path(__file__).resolve().parent / "data" / "private_duty_dm_state.json").resolve()


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {"last_sent_ts": 0.0, "recent_norms": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {"last_sent_ts": 0.0, "recent_norms": []}


def _save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=0) + "\n", encoding="utf-8")


def _norm_line(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())[:200]


def _too_similar(text: str, recent_norms: list[str]) -> bool:
    n = _norm_line(text)
    if not n:
        return True
    for r in recent_norms:
        if not r:
            continue
        if n == r:
            return True
        if len(n) > 40 and (n in r or r in n):
            return True
    return False


def _clean_generated_line(raw: str) -> str:
    line = re.sub(r"^#+\s*", "", (raw or "").strip())
    line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
    line = re.sub(r"^(?:luna|viktor|himari)\s*:\s*", "", line, flags=re.I).strip()
    return line.strip("\"' ")


def generate_private_duty_reminder_sync(*, model: str, recent_norms: list[str]) -> str | None:
    """One fresh Viktor DM — returns None if the model cannot produce a genuine line."""
    viktor = cohost_name()
    persona = build_vampire_system_prompt()
    avoid = ""
    if recent_norms:
        avoid = (
            "Do not repeat or closely paraphrase these recent reminders:\n"
            + "\n".join(f"- {n[:120]}" for n in recent_norms[-6:] if n)
            + "\n\n"
        )
    system = (
        f"You are {viktor}, writing a **private** Discord DM to one person (the streamer/owner only). "
        "No one else will see this.\n\n"
        f"{persona}\n\n"
        "Write 2–4 sentences. You are mentoring one man privately about **life**, not a single context. "
        "Themes (weave naturally, vary each hour — do not fixate only on the office):\n"
        "- **Honor** — keeping your word, truth, dignity under temptation, how he treats people who cannot reward him.\n"
        "- **Duty and discipline** — mastery over impulse in work, desire, pride, comfort, and distraction.\n"
        "- **Becoming respected** — character, reliability, courage, restraint; the man others trust in friendship, "
        "family, love, and solitude.\n"
        "You may mention work sometimes, but also home, relationships, habits, reputation, patience, and how he "
        "carries himself in ordinary moments. Speak as Viktor: dry, elegant, slightly stern, wry, like an older "
        "man who has seen cowards and gentlemen both — you want him to become the second kind.\n"
        "CRITICAL: Write **only original words for this exact moment**. No stock quotes, no pre-written "
        "motivational lines, no generic platitudes you could paste anywhere. Sound like you actually thought "
        "of this now. Never preachy, never crude, no explicit sexual content. Do not mention Discord servers, "
        "chat, viewers, streams, or other bot features. Do not say goodnight or imply ending anything. "
        "Plain text only; no markdown headers or bullets.\n\n"
        f"{avoid}"
    )
    client = build_client()
    retries = private_duty_dm_max_retries()
    hour_bucket = int(time.time() // 3600)

    for attempt in range(retries + 1):
        angle = _LIFE_ANGLES[(hour_bucket + attempt) % len(_LIFE_ANGLES)]
        user = (
            f"Write this hour's private reminder (attempt {attempt + 1}). "
            f"Let today's angle be **{angle}** — still honor, discipline, and becoming a respected man. "
            "Fresh, specific, genuine — as if you just thought of it."
        )
        if attempt > 0:
            user += " Your last try was too short, empty, or too similar — write something new."

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        kwargs = chat_request_kwargs(model, messages, stream=False)
        opts = dict(kwargs.get("options") or {})
        opts["num_predict"] = min(320, opts.get("num_predict", 320) or 320)
        kwargs["options"] = opts
        try:
            response = client.chat(**kwargs)
            raw = strip_think_blocks((response.message.content or "").strip())
        except Exception as exc:  # noqa: BLE001
            print(
                f"(discord private) duty reminder LLM failed (attempt {attempt + 1}): {exc}",
                flush=True,
            )
            continue
        line = _clean_generated_line(raw)
        if len(line) < 40:
            continue
        if _too_similar(line, recent_norms):
            continue
        return line[:_DISCORD_DM_MAX]

    print(
        f"(discord private) no genuine reminder after {retries + 1} tries — skipping this hour",
        flush=True,
    )
    return None


async def _send_private_dm_quiet(bot: Any, user_id: int, text: str) -> bool:
    """DM the owner: text first, then optional Viktor TTS MP3 (like Luna Discord DMs)."""
    body = (text or "").strip()
    if not body:
        return False
    audio_paths: list[Path] = []
    try:
        user = await bot.fetch_user(int(user_id))
        if getattr(user, "bot", False):
            return False
        ch = await user.create_dm()
        await ch.send(body[:_DISCORD_DM_MAX])

        if private_duty_dm_discord_tts_enabled():
            try:
                from luna_cast import partner_edge_voice
                from luna_tts import synthesize_discord_reply_files, tts_enabled

                if tts_enabled():
                    audio_paths = await asyncio.to_thread(
                        synthesize_discord_reply_files,
                        body,
                        voice=partner_edge_voice("viktor"),
                    )
            except Exception as exc:  # noqa: BLE001
                print(f"(discord private) duty reminder TTS failed: {exc}", flush=True)

        if audio_paths:
            import discord  # noqa: PLC0415

            for i, path in enumerate(audio_paths):
                if not path.is_file():
                    continue
                fname = (
                    f"viktor_discord_{i + 1}{path.suffix or '.mp3'}"
                    if len(audio_paths) > 1
                    else f"Viktor_discord{path.suffix or '.mp3'}"
                )
                try:
                    await ch.send(file=discord.File(str(path), filename=fname))
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"(discord private) duty reminder TTS upload failed: {exc}",
                        flush=True,
                    )
                    break
            else:
                print(
                    f"(discord private) duty reminder TTS sent ({len(audio_paths)} file(s))",
                    flush=True,
                )

        if audio_paths:
            _save_duty_reminder_archive(body, audio_paths)

        print("(discord private) duty reminder DM sent", flush=True)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"(discord private) duty reminder DM failed: {exc}", flush=True)
        return False
    finally:
        for path in audio_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


async def private_duty_dm_loop(bot: Any) -> None:
    """Hourly private Viktor DM to LUNA_OWNER_DISCORD_ID (or LUNA_DISCORD_PRIVATE_DUTY_DM_USER_ID)."""
    if not private_duty_dm_enabled():
        return
    owner_ids = private_duty_dm_owner_ids()
    if not owner_ids:
        print(
            "(discord private) duty DM enabled but no owner id — set LUNA_OWNER_DISCORD_ID",
            flush=True,
        )
        return

    await bot.wait_until_ready()
    await asyncio.sleep(20.0)
    interval = private_duty_dm_interval_sec()
    model = private_duty_dm_model()
    tts_note = (
        " + Viktor TTS MP3"
        if private_duty_dm_discord_tts_enabled()
        else " (text only; LUNA_DISCORD_TTS=0)"
    )
    archive_note = (
        f", archive -> {private_duty_dm_archive_dir()}"
        if private_duty_dm_archive_enabled() and private_duty_dm_discord_tts_enabled()
        else ""
    )
    print(
        f"(discord private) Viktor honor/duty reminders ON — LLM-only, every {int(interval)}s, "
        f"{len(owner_ids)} recipient(s){tts_note}{archive_note}",
        flush=True,
    )

    while not bot.is_closed():
        state = _load_state()
        last = float(state.get("last_sent_ts") or 0.0)
        now = time.time()
        if now - last >= interval:
            recent = [str(x) for x in (state.get("recent_norms") or []) if x][-12:]
            text = await asyncio.to_thread(
                generate_private_duty_reminder_sync,
                model=model,
                recent_norms=recent,
            )
            if not text:
                await asyncio.sleep(min(300.0, interval))
                continue
            for uid in sorted(owner_ids):
                ok = await _send_private_dm_quiet(bot, uid, text)
                if ok:
                    norm = _norm_line(text)
                    recent = (recent + [norm])[-12:]
                    state["recent_norms"] = recent
                    state["last_sent_ts"] = now
                    _save_state(state)
                    break
        sleep_for = max(30.0, min(interval, interval - (time.time() - last)))
        await asyncio.sleep(sleep_for)


def _is_viktor_discord_mp3(filename: str) -> bool:
    return bool(re.search(r"viktor_discord", (filename or ""), re.I)) and (
        filename or ""
    ).lower().endswith(".mp3")


def _is_luna_discord_mp3(filename: str) -> bool:
    return bool(re.search(r"luna_discord|luna_tts", (filename or ""), re.I)) and (
        filename or ""
    ).lower().endswith(".mp3")


def _looks_like_luna_dm_reply(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return True
    if re.search(r"wolf-girl|circuits hum|i'm luna\b|glad you're here", t):
        return True
    if re.search(r"^hey!?\b", t) and len(t) < 220:
        return True
    if "🍌" in text or "✨" in text:
        return True
    return False


def _looks_like_viktor_duty_text(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 40 or _looks_like_luna_dm_reply(t):
        return False
    return bool(
        re.search(
            r"\b(honor|duty|discipline|respect|character|impulse|dignity|word|reputation|"
            r"loyalty|patience|courage|habit|man who|men who|gentlemen|coward)\b",
            t,
            re.I,
        )
    )


async def backfill_viktor_wisdom_archive_from_discord(
    bot: Any,
    *,
    synthesize_missing: bool = True,
) -> dict[str, int]:
    """Download past Viktor duty MP3s from owner DMs; optionally synth text-only reminders."""
    import tempfile

    import discord  # noqa: PLC0415

    owner_ids = private_duty_dm_owner_ids()
    if not owner_ids:
        print("(discord private) backfill: no LUNA_OWNER_DISCORD_ID", flush=True)
        return {"downloaded": 0, "synthesized": 0, "skipped": 0}

    dest_dir = private_duty_dm_archive_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    stats = {"downloaded": 0, "synthesized": 0, "skipped": 0}
    me = bot.user
    if me is None:
        return stats

    for uid in sorted(owner_ids):
        try:
            user = await bot.fetch_user(int(uid))
        except Exception as exc:  # noqa: BLE001
            print(f"(discord private) backfill: fetch user {uid} failed: {exc}", flush=True)
            continue
        dm = user.dm_channel
        if dm is None:
            try:
                dm = await user.create_dm()
            except Exception as exc:  # noqa: BLE001
                print(f"(discord private) backfill: open DM failed: {exc}", flush=True)
                continue

        messages: list[Any] = []
        async for msg in dm.history(limit=None, oldest_first=True):
            messages.append(msg)
        print(f"(discord private) backfill: scanning {len(messages)} DM message(s)", flush=True)

        archived_stems: set[str] = {p.stem for p in dest_dir.glob("viktor-wisdom_*.mp3")}
        handled_text_ids: set[int] = set()

        for i, msg in enumerate(messages):
            if int(getattr(msg.author, "id", 0) or 0) != int(me.id):
                continue

            viktor_atts = [
                att
                for att in (msg.attachments or [])
                if _is_viktor_discord_mp3(getattr(att, "filename", "") or "")
            ]
            if viktor_atts:
                text = ""
                if i > 0:
                    prev = messages[i - 1]
                    if (
                        int(getattr(prev.author, "id", 0) or 0) == int(me.id)
                        and (prev.content or "").strip()
                        and not _looks_like_luna_dm_reply(prev.content)
                    ):
                        text = (prev.content or "").strip()
                        handled_text_ids.add(int(prev.id))

                created = msg.created_at.astimezone().replace(tzinfo=None)
                stem = _unique_archive_stem(created, dest_dir)
                if stem in archived_stems:
                    stats["skipped"] += 1
                    continue

                tmp_paths: list[Path] = []
                try:
                    for j, att in enumerate(viktor_atts):
                        fd, tmp = tempfile.mkstemp(suffix=".mp3", prefix="viktor_backfill_")
                        os.close(fd)
                        tmp_path = Path(tmp)
                        await att.save(tmp_path)
                        tmp_paths.append(tmp_path)
                    saved = _save_duty_reminder_archive(
                        text,
                        tmp_paths,
                        dt=created,
                        stem=stem,
                    )
                    if saved:
                        archived_stems.add(stem)
                        stats["downloaded"] += len(
                            [p for p in saved if p.suffix.lower() == ".mp3"]
                        )
                        print(f"(discord private) backfill: saved {stem}.mp3", flush=True)
                except Exception as exc:  # noqa: BLE001
                    print(f"(discord private) backfill download failed: {exc}", flush=True)
                finally:
                    for p in tmp_paths:
                        try:
                            p.unlink(missing_ok=True)
                        except OSError:
                            pass
                continue

            if not synthesize_missing:
                continue
            text = (msg.content or "").strip()
            if not text or int(msg.id) in handled_text_ids:
                continue
            if not _looks_like_viktor_duty_text(text):
                continue

            # Skip Luna chat replies (user spoke right before).
            if i > 0:
                prev = messages[i - 1]
                if not getattr(prev.author, "bot", False):
                    delta = (msg.created_at - prev.created_at).total_seconds()
                    if 0 <= delta <= 120:
                        continue

            # Skip if Luna TTS follows (interactive reply).
            if i + 1 < len(messages):
                nxt = messages[i + 1]
                if int(getattr(nxt.author, "id", 0) or 0) == int(me.id):
                    if any(
                        _is_luna_discord_mp3(getattr(att, "filename", "") or "")
                        for att in (nxt.attachments or [])
                    ):
                        continue
                    if (nxt.created_at - msg.created_at).total_seconds() <= 120 and any(
                        _is_viktor_discord_mp3(getattr(att, "filename", "") or "")
                        for att in (nxt.attachments or [])
                    ):
                        continue

            created = msg.created_at.astimezone().replace(tzinfo=None)
            stem = _unique_archive_stem(created, dest_dir)
            if stem in archived_stems:
                stats["skipped"] += 1
                continue

            try:
                from luna_cast import partner_edge_voice
                from luna_tts import synthesize_discord_reply_files, tts_enabled

                if not tts_enabled():
                    continue
                audio_paths = await asyncio.to_thread(
                    synthesize_discord_reply_files,
                    text,
                    voice=partner_edge_voice("viktor"),
                )
                if not audio_paths:
                    continue
                saved = _save_duty_reminder_archive(text, audio_paths, dt=created, stem=stem)
                for p in audio_paths:
                    try:
                        p.unlink(missing_ok=True)
                    except OSError:
                        pass
                if saved:
                    archived_stems.add(stem)
                    stats["synthesized"] += len([p for p in saved if p.suffix.lower() == ".mp3"])
                    print(f"(discord private) backfill: synthesized {stem}.mp3", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"(discord private) backfill synth failed: {exc}", flush=True)

    print(
        f"(discord private) backfill done: {stats['downloaded']} downloaded, "
        f"{stats['synthesized']} synthesized, {stats['skipped']} skipped -> {dest_dir}",
        flush=True,
    )
    return stats
