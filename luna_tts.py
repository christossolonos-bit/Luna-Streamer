"""Luna TTS via selectable backends (Edge TTS or Chatterbox).

Env:
  LUNA_TTS                If 1/true/yes, synthesize after each reply.
  LUNA_TTS_PLAY           If 1, play the WAV locally.
  LUNA_TTS_BACKEND        edge (default) or chatterbox
  LUNA_EDGE_VOICE         Edge voice id; default en-US-JennyNeural
  LUNA_EDGE_RATE          Rate adjustment, e.g. +0% / -10%
  LUNA_EDGE_PITCH         Pitch adjustment, e.g. +0Hz / -2Hz
  LUNA_TTS_SPEAKER        Optional alias from LUNA_TTS_VOICES; falls back to LUNA_EDGE_VOICE.
  LUNA_TTS_VOICES         Optional CSV list of voice ids or id:Label entries.
  LUNA_TTS_MAX_CHARS      Truncate cleaned text for TTS (default 500).
  LUNA_CHATTERBOX_DEVICE  cpu/cuda (default auto)
  LUNA_CHATTERBOX_RANGE         expressive range control (alias of exaggeration), default 0.5
  LUNA_CHATTERBOX_EXAGGERATION  default 0.5
  LUNA_CHATTERBOX_CFG_WEIGHT    default 0.5
  LUNA_CHATTERBOX_TEMPERATURE   default 0.8
  LUNA_CHATTERBOX_VOICE_REF     Optional path to reference wav/mp3 for custom voice cloning.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

_selected_speaker: str | None = None
_cb_model: Any = None
_tts_play_lock = threading.Lock()
_edge_prewarmed = False


def _env_bool(key: str, default: str = "") -> bool:
    return os.environ.get(key, default).strip().lower() in ("1", "true", "yes")


def tts_enabled() -> bool:
    return _env_bool("LUNA_TTS")


def tts_playback_enabled() -> bool:
    return _env_bool("LUNA_TTS_PLAY")


def _default_voice() -> str:
    return os.environ.get("LUNA_EDGE_VOICE", "en-US-JennyNeural").strip() or "en-US-JennyNeural"


def _backend() -> str:
    return os.environ.get("LUNA_TTS_BACKEND", "edge").strip().lower()


def voice_options() -> list[tuple[str, str]]:
    if _backend() == "chatterbox":
        return [("default", "Chatterbox Default")]
    avail = [_default_voice(), "en-US-AriaNeural", "en-US-GuyNeural", "en-GB-SoniaNeural"]
    raw = os.environ.get("LUNA_TTS_VOICES", "").strip()
    if not raw:
        return [(v, v) for v in avail]
    out: list[tuple[str, str]] = []
    for part in [p.strip() for p in raw.split(",") if p.strip()]:
        if ":" in part:
            vid, label = part.split(":", 1)
            vid = vid.strip()
            label = label.strip() or vid
        else:
            vid, label = part, part
        if vid:
            out.append((vid, label))
    return out if out else [(v, v) for v in avail]


def get_effective_speaker() -> str:
    global _selected_speaker
    valid = {v for v, _ in voice_options()}
    if _selected_speaker is None or _selected_speaker not in valid:
        default = "default" if _backend() == "chatterbox" else _default_voice()
        start = os.environ.get("LUNA_TTS_SPEAKER", default).strip() or default
        _selected_speaker = start if start in valid else next(iter(valid))
    return _selected_speaker


def set_selected_speaker(speaker_id: str) -> bool:
    global _selected_speaker
    sid = (speaker_id or "").strip()
    valid = {v for v, _ in voice_options()}
    if sid not in valid:
        return False
    _selected_speaker = sid
    return True


def tts_voices_control_message() -> dict[str, Any]:
    return {
        "type": "control",
        "name": "tts_voices",
        "voices": [{"id": i, "label": label} for i, label in voice_options()],
        "current": get_effective_speaker(),
        "enabled": tts_enabled(),
    }


def _action_sound(action_text: str) -> str:
    a = action_text.strip().lower()
    if any(k in a for k in ("scream", "shout", "yell")):
        return " ahhh! "
    if any(k in a for k in ("scared", "afraid", "terrified", "panic")):
        return " eek! "
    if any(k in a for k in ("laugh", "giggle", "chuckle", "lol")):
        return " haha! "
    if any(k in a for k in ("happy", "smile", "cheerful", "joy")):
        return " hehe! "
    if any(k in a for k in ("excited", "hype", "energetic")):
        return " woo! "
    if any(k in a for k in ("sad", "upset", "down", "cry", "teary")):
        return " sniff... "
    if any(k in a for k in ("sigh", "exhale")):
        return " ahh... "
    if any(k in a for k in ("gasp", "surprised")):
        return " oh! "
    if any(k in a for k in ("angry", "mad", "annoyed", "frustrated")):
        return " tsk... "
    if any(k in a for k in ("nervous", "shy", "embarrassed")):
        return " uh... "
    if any(k in a for k in ("hmm", "thinking")):
        return " hmm... "
    if any(k in a for k in ("confused", "unsure", "puzzled")):
        return " hmm? "
    # Default: drop unknown action tag from spoken text.
    return " "


def _classify_emotion(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ("*scream*", "*shout*", " screaming", " shouted", "shouting", " ahhh")):
        return "shout"
    if any(k in t for k in ("*scared*", "*afraid*", " terrified", " scared", "frightened", " eek")):
        return "scared"
    if any(k in t for k in ("*surprised*", "*gasp*", " surprised", " gasp", " oh!")):
        return "surprised"
    if any(k in t for k in ("*cry*", "*crying*", "*sad*", " i cried", " sob", "tears", "sad ")):
        return "sad"
    if any(k in t for k in ("*angry*", "*mad*", " furious", " angry", "annoyed", " tsk")):
        return "angry"
    if any(k in t for k in ("*excited*", " let's go", " woo", " so hyped", " excited", " hehe", " haha")):
        return "excited"
    if re.search(r"\b(o+h+|a+h+|w+o+w+|y+a+y+)\b", t):
        return "excited"
    return "neutral"


def _prosody_for_emotion(emotion: str) -> tuple[str, str]:
    # Defaults can be overridden globally.
    default_rate = os.environ.get("LUNA_EDGE_RATE", "+0%").strip() or "+0%"
    default_pitch = os.environ.get("LUNA_EDGE_PITCH", "+0Hz").strip() or "+0Hz"

    # Per-emotion overrides (optional) e.g. LUNA_EDGE_RATE_EXCITED=+12%
    # Fallbacks below are intentionally subtle.
    if emotion == "excited":
        return (
            os.environ.get("LUNA_EDGE_RATE_EXCITED", "+18%").strip() or "+18%",
            os.environ.get("LUNA_EDGE_PITCH_EXCITED", "+10Hz").strip() or "+10Hz",
        )
    if emotion == "sad":
        return (
            os.environ.get("LUNA_EDGE_RATE_SAD", "-12%").strip() or "-12%",
            os.environ.get("LUNA_EDGE_PITCH_SAD", "-4Hz").strip() or "-4Hz",
        )
    if emotion == "angry":
        return (
            os.environ.get("LUNA_EDGE_RATE_ANGRY", "+6%").strip() or "+6%",
            os.environ.get("LUNA_EDGE_PITCH_ANGRY", "-3Hz").strip() or "-3Hz",
        )
    if emotion in {"surprised", "scared"}:
        return (
            os.environ.get("LUNA_EDGE_RATE_SURPRISED", "+20%").strip() or "+20%",
            os.environ.get("LUNA_EDGE_PITCH_SURPRISED", "+12Hz").strip() or "+12Hz",
        )
    if emotion == "shout":
        return (
            os.environ.get("LUNA_EDGE_RATE_SHOUT", "+26%").strip() or "+26%",
            os.environ.get("LUNA_EDGE_PITCH_SHOUT", "+16Hz").strip() or "+16Hz",
        )
    return default_rate, default_pitch


def _enhance_interjections_for_tts(text: str) -> str:
    # Stretch common reactions so Edge TTS sounds more emotive.
    t = text
    t = re.sub(r"\boh+\b", "oooh", t, flags=re.IGNORECASE)
    t = re.sub(r"\bwoo+\b", "wooo", t, flags=re.IGNORECASE)
    t = re.sub(r"\bah+\b", "aaah", t, flags=re.IGNORECASE)
    t = re.sub(r"\baww+\b", "awww", t, flags=re.IGNORECASE)
    return t


def _is_song_style_text(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in ("verse", "chorus", "bridge", "lyrics", "song"))


def _is_action_phrase(phrase: str) -> bool:
    p = phrase.strip().lower()
    action_words = (
        "laugh",
        "giggle",
        "chuckle",
        "tail",
        "wag",
        "twitch",
        "sigh",
        "gasp",
        "shout",
        "scream",
        "whisper",
        "smile",
        "blush",
        "nod",
        "wink",
        "sniff",
        "sob",
        "cry",
    )
    return any(w in p for w in action_words)


def _split_tts_chunks(text: str, target_chars: int) -> list[str]:
    target = max(60, target_chars)
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    if not parts:
        return [text] if text else []
    out: list[str] = []
    buf = ""
    for part in parts:
        if not buf:
            buf = part
            continue
        if len(buf) + 1 + len(part) <= target:
            buf = f"{buf} {part}"
        else:
            out.append(buf)
            buf = part
    if buf:
        out.append(buf)

    # Hard-wrap very long leftovers without punctuation.
    final: list[str] = []
    for chunk in out:
        c = chunk.strip()
        while len(c) > target:
            split_at = c.rfind(" ", 0, target + 1)
            if split_at < 30:
                split_at = target
            final.append(c[:split_at].strip())
            c = c[split_at:].strip()
        if c:
            final.append(c)
    return final


def _clean_text_for_tts(reply_text: str) -> tuple[str, str]:
    """Clean a reply for synthesis.

    Returns ``(cleaned_text, emotion)``. ``cleaned_text`` may be empty if the
    reply was entirely emojis / decoration, in which case callers should skip
    synthesis. ``emotion`` is the detected emotion label used for prosody.
    """
    text = (reply_text or "").strip()
    # Remove common ASCII emoticons/smiley faces before TTS.
    text = re.sub(r"(?::|;|=|8)(?:-)?(?:\)|\(|D|P|p|/|\\|\||\*)", " ", text)
    text = re.sub(r"(?:<3|:\'\(|:\'\))", " ", text)
    # Remove most Unicode emoji/symbol pictographs.
    text = re.sub(
        r"[\U0001F300-\U0001F5FF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\U0001F700-\U0001F77F\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\u2600-\u27BF]+",
        " ",
        text,
    )
    song_mode = _is_song_style_text(text)

    def _star_replace(m: re.Match[str]) -> str:
        inner = m.group(1).strip()
        if not inner:
            return " "
        if song_mode and _is_action_phrase(inner):
            return " "
        return f" {inner} "

    text = re.sub(r"\*([^*]+)\*", _star_replace, text)
    text = re.sub(r"\(([^()]+)\)", lambda m: _action_sound(m.group(1)), text)
    text = re.sub(r"[*_`]+", "", text)
    text = re.sub(r"\s+", " ", text)
    max_chars = int(os.environ.get("LUNA_TTS_MAX_CHARS", "500").strip() or "500")
    if len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."
    if not text:
        return "", ""
    text = _enhance_interjections_for_tts(text)
    emotion = _classify_emotion(text)
    return text, emotion


def maybe_speak(reply_text: str) -> None:
    """Synthesize and PLAY a reply locally (used by Twitch / viewer pipelines)."""
    if not tts_enabled():
        return
    text, emotion = _clean_text_for_tts(reply_text)
    if not text:
        return
    rate, pitch = _prosody_for_emotion(emotion)

    backend = _backend()
    with _tts_play_lock:
        try:
            if backend == "chatterbox":
                chunk_chars = int(os.environ.get("LUNA_CHATTERBOX_CHUNK_CHARS", "120").strip() or "120")
                chunks = _split_tts_chunks(text, chunk_chars)
                if not chunks:
                    return
                for part in chunks:
                    fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="luna_chatter_")
                    os.close(fd)
                    wav_out = Path(tmp)
                    try:
                        _synthesize_chatterbox_to_wav(part, wav_out, emotion=emotion)
                        if tts_playback_enabled():
                            _play_wav(wav_out)
                    finally:
                        try:
                            wav_out.unlink(missing_ok=True)
                        except OSError:
                            pass
                return

            fd, tmp = tempfile.mkstemp(suffix=".mp3", prefix="luna_edge_")
            os.close(fd)
            mp3_out = Path(tmp)
            wav_out = mp3_out.with_suffix(".wav")
            try:
                _synthesize_edge_to_mp3(text, mp3_out, voice=get_effective_speaker(), rate=rate, pitch=pitch)
                _mp3_to_wav(mp3_out, wav_out)
                if tts_playback_enabled():
                    _play_wav(wav_out)
            finally:
                try:
                    mp3_out.unlink(missing_ok=True)
                    wav_out.unlink(missing_ok=True)
                except OSError:
                    pass
        except Exception as exc:
            print(f"(LUNA_TTS {backend} synthesis failed: {exc})", flush=True)


def synthesize_reply_to_file(reply_text: str) -> Path | None:
    """Synthesize a reply to a standalone audio file without playing it.

    Returns the path to an MP3 (Edge backend) or WAV (Chatterbox). The caller
    owns the file and should delete it when finished (e.g. after uploading to
    Discord). Returns None if TTS is disabled or the reply is empty.
    """
    if not tts_enabled():
        return None
    text, emotion = _clean_text_for_tts(reply_text)
    if not text:
        return None
    rate, pitch = _prosody_for_emotion(emotion)

    backend = _backend()
    try:
        if backend == "chatterbox":
            chunk_chars = int(os.environ.get("LUNA_CHATTERBOX_CHUNK_CHARS", "120").strip() or "120")
            chunks = _split_tts_chunks(text, chunk_chars) or [text]
            # Chatterbox needs to render each chunk; concatenate to a single WAV.
            fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="luna_chatter_out_")
            os.close(fd)
            combined = Path(tmp)
            if len(chunks) == 1:
                _synthesize_chatterbox_to_wav(chunks[0], combined, emotion=emotion)
                return combined
            # Multi-chunk: synth each to temp, then concat with ffmpeg.
            tmp_parts: list[Path] = []
            try:
                for i, part in enumerate(chunks):
                    fd_p, p_tmp = tempfile.mkstemp(suffix=".wav", prefix=f"luna_chatter_part_{i}_")
                    os.close(fd_p)
                    p = Path(p_tmp)
                    _synthesize_chatterbox_to_wav(part, p, emotion=emotion)
                    tmp_parts.append(p)
                _concat_audio_with_ffmpeg(tmp_parts, combined)
            finally:
                for p in tmp_parts:
                    try:
                        p.unlink(missing_ok=True)
                    except OSError:
                        pass
            return combined

        # Edge: single MP3 output.
        fd, tmp = tempfile.mkstemp(suffix=".mp3", prefix="luna_discord_")
        os.close(fd)
        mp3_out = Path(tmp)
        _synthesize_edge_to_mp3(text, mp3_out, voice=get_effective_speaker(), rate=rate, pitch=pitch)
        return mp3_out
    except Exception as exc:
        print(f"(LUNA_TTS {backend} file synth failed: {exc})", flush=True)
        return None


def _concat_audio_with_ffmpeg(parts: list[Path], out_path: Path) -> None:
    """Concatenate multiple WAV files into one via ffmpeg's concat demuxer."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        # Fallback: just copy the first one so we still have a usable file.
        if parts:
            out_path.write_bytes(parts[0].read_bytes())
        return
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, prefix="luna_concat_"
    ) as listfile:
        for p in parts:
            listfile.write(f"file '{str(p).replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'\n")
        list_path = listfile.name
    try:
        cmd = [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            list_path,
            "-c",
            "copy",
            str(out_path),
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=False)
    finally:
        try:
            os.unlink(list_path)
        except OSError:
            pass


def _synthesize_edge_to_mp3(text: str, out_path: Path, voice: str, rate: str, pitch: str) -> None:
    import edge_tts

    async def _run() -> None:
        comm = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
        await comm.save(str(out_path))

    asyncio.run(_run())


def prewarm_edge_tts() -> None:
    """Warm Edge TTS so the first user reply doesn't pay DNS + TLS handshake.

    Synthesises a single short sample and discards it. No-op after first
    success. Safe to call multiple times.
    """
    global _edge_prewarmed
    if _edge_prewarmed:
        return
    if not tts_enabled() or _backend() != "edge":
        _edge_prewarmed = True
        return
    try:
        fd, tmp = tempfile.mkstemp(suffix=".mp3", prefix="luna_edge_warm_")
        os.close(fd)
        warm_out = Path(tmp)
        try:
            _synthesize_edge_to_mp3(
                "hi",
                warm_out,
                voice=get_effective_speaker(),
                rate=os.environ.get("LUNA_EDGE_RATE", "+0%").strip() or "+0%",
                pitch=os.environ.get("LUNA_EDGE_PITCH", "+0Hz").strip() or "+0Hz",
            )
        finally:
            try:
                warm_out.unlink(missing_ok=True)
            except OSError:
                pass
        _edge_prewarmed = True
    except Exception as exc:
        # Non-fatal — first real reply will just be ~200 ms slower.
        print(f"(tts prewarm) skipped: {exc}", flush=True)


def _mp3_to_wav(src: Path, dst: Path) -> None:
    """Convert MP3 → 24 kHz mono WAV via a single ffmpeg subprocess.

    Avoids pulling pydub / AudioSegment (which itself shells out to ffmpeg
    plus loads pydub's audioop). Cuts per-reply TTS overhead by ~200 ms.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        # Last-ditch: pydub still works if ffmpeg isn't on PATH.
        from pydub import AudioSegment

        AudioSegment.from_file(src, format="mp3").export(dst, format="wav")
        return
    cmd = [
        ffmpeg,
        "-y",
        "-v",
        "error",
        "-i",
        str(src),
        "-ac",
        "1",
        "-ar",
        "24000",
        "-f",
        "wav",
        str(dst),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not dst.exists() or dst.stat().st_size < 256:
        err = (proc.stderr or "").strip() or "ffmpeg mp3->wav failed"
        raise RuntimeError(err)


def _ensure_chatterbox_loaded() -> Any:
    global _cb_model
    if _cb_model is not None:
        return _cb_model
    from chatterbox import ChatterboxTTS

    device = os.environ.get("LUNA_CHATTERBOX_DEVICE", "").strip().lower()
    if not device:
        try:
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            device = "cpu"
    _cb_model = ChatterboxTTS.from_pretrained(device=device)
    return _cb_model


def _synthesize_chatterbox_to_wav(text: str, out_path: Path, emotion: str) -> None:
    model = _ensure_chatterbox_loaded()
    import torchaudio

    # "Range" is a friendlier alias for exaggeration.
    exaggeration = float(
        os.environ.get(
            "LUNA_CHATTERBOX_RANGE",
            os.environ.get("LUNA_CHATTERBOX_EXAGGERATION", "0.5"),
        ).strip()
        or "0.5"
    )
    cfg_weight = float(os.environ.get("LUNA_CHATTERBOX_CFG_WEIGHT", "0.5").strip() or "0.5")
    temperature = float(os.environ.get("LUNA_CHATTERBOX_TEMPERATURE", "0.8").strip() or "0.8")
    if emotion in {"excited", "surprised", "shout"}:
        exaggeration = max(exaggeration, 0.75)
        cfg_weight = max(cfg_weight, 0.65)
    elif emotion in {"sad", "angry"}:
        exaggeration = max(exaggeration, 0.6)
    voice_ref = os.environ.get("LUNA_CHATTERBOX_VOICE_REF", "").strip() or None
    if voice_ref:
        p = Path(voice_ref)
        if not p.exists():
            print(f"(LUNA_TTS chatterbox voice ref not found: {voice_ref})", flush=True)
            voice_ref = None
    wav = model.generate(
        text,
        audio_prompt_path=voice_ref,
        exaggeration=exaggeration,
        cfg_weight=cfg_weight,
        temperature=temperature,
    )
    torchaudio.save(str(out_path), wav.cpu(), getattr(model, "sr", 24000))


def _play_wav(path: Path) -> None:
    p = str(path)
    if sys.platform == "win32":
        import winsound

        winsound.PlaySound(p, winsound.SND_FILENAME)
    elif sys.platform == "darwin":
        subprocess.run(["afplay", p], check=False)
    else:
        subprocess.run(["aplay", "-q", p], check=False)
