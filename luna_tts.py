"""Luna TTS via selectable backends (Edge TTS or Chatterbox).

Env:
  LUNA_TTS                If 1/true/yes, synthesize after each reply.
  LUNA_TTS_PLAY           If 1, play on the PC speakers (``local`` / ``both`` targets).
  LUNA_TTS_PLAY_TARGET    ``local`` (default), ``viewer`` (VRM browser / OBS window), or ``both``.
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
  LUNA_TTS_VISEME_OFFSET_SEC    Extra delay (seconds) added to every viseme timestamp so lips
                                track local speakers / WebSocket latency (default 0.05).
  LUNA_TTS_VISEME_SOURCE        Lip cues: ``audio`` (analyze WAV — follows sound shape),
                                ``edge`` (Edge word/sentence boundaries only), or ``auto``
                                (prefer audio when librosa yields a timeline; default auto).
  LUNA_TTS_VISEME_N_FFT         STFT size for audio visemes (default 960).
  LUNA_TTS_VISEME_HOP           STFT hop for audio visemes (default n_fft/4).
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
import time
import wave
from pathlib import Path
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_selected_speaker: str | None = None
_cb_model: Any = None
_tts_play_lock = threading.Lock()
_edge_prewarmed = False
VisemeCallback = Callable[[str, float, int], None]


def _env_bool(key: str, default: str = "") -> bool:
    return os.environ.get(key, default).strip().lower() in ("1", "true", "yes")


def tts_enabled() -> bool:
    return _env_bool("LUNA_TTS")


def tts_play_target() -> str:
    """Where synthesized audio is played: ``local`` | ``viewer`` | ``both``."""
    raw = (os.environ.get("LUNA_TTS_PLAY_TARGET") or "local").strip().lower()
    if raw in ("viewer", "browser", "vrm", "obs"):
        return "viewer"
    if raw == "both":
        return "both"
    return "local"


def tts_play_to_viewer() -> bool:
    return tts_play_target() in ("viewer", "both")


def tts_play_locally() -> bool:
    return _env_bool("LUNA_TTS_PLAY") and tts_play_target() in ("local", "both")


def tts_playback_enabled() -> bool:
    return tts_play_locally()


@dataclass(frozen=True)
class TtsPlaybackBundle:
    audio: bytes
    mime: str
    duration_ms: int
    visemes: list[dict[str, Any]]


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
    normalized = re.sub(r"\n{2,}", ". ", (text or "").replace("\n", " "))
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", normalized) if p.strip()]
    if not parts:
        parts = [p.strip() for p in re.split(r"\n+", text or "") if p.strip()]
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


def _reply_text_before_tts_clean(reply_text: str, voice: str | None = None) -> str:
    """Himari-specific decorations (blush kaomoji, stutter collapse) before shared TTS clean."""
    edge_voice = (voice or "").strip()
    if not edge_voice:
        return reply_text
    try:
        from himari_cohost import himari_edge_voice, sanitize_himari_speech_text

        if edge_voice == himari_edge_voice():
            return sanitize_himari_speech_text(reply_text)
    except ImportError:
        pass
    return reply_text


def _clean_text_for_tts(reply_text: str, *, max_chars: int | None = None) -> tuple[str, str]:
    """Clean a reply for synthesis.

    Returns ``(cleaned_text, emotion)``. ``cleaned_text`` may be empty if the
    reply was entirely emojis / decoration, in which case callers should skip
    synthesis. ``emotion`` is the detected emotion label used for prosody.

    Pass ``max_chars=0`` for no length cap (Discord long single MP3).
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
    def _star_replace(m: re.Match[str]) -> str:
        inner = m.group(1).strip()
        if not inner:
            return " "
        # Long *narration* (e.g. *ears perk up, tail wagging*) — drop entirely, no TTS.
        if len(inner) > 48 or inner.count(" ") >= 3:
            return " "
        # Short *cues* (*laugh*, *gasp*) → interjection sound or silence.
        return _action_sound(inner)

    text = re.sub(r"\*([^*]+)\*", _star_replace, text)
    text = re.sub(r"\(([^()]+)\)", lambda m: _action_sound(m.group(1)), text)
    text = re.sub(r"[*_`]+", "", text)
    text = re.sub(r"\s+", " ", text)
    limit = max_chars
    if limit is None:
        limit = int(os.environ.get("LUNA_TTS_MAX_CHARS", "2500").strip() or "2500")
    if limit > 0 and len(text) > limit:
        text = text[: limit - 3].rstrip() + "..."
    if not text:
        return "", ""
    text = _enhance_interjections_for_tts(text)
    emotion = _classify_emotion(text)
    return text, emotion


def _visemes_for_timeline(
    timeline: list[tuple[float, str, float, int]] | None,
) -> list[dict[str, Any]]:
    offset = float(os.environ.get("LUNA_TTS_VISEME_OFFSET_SEC", "0.05").strip() or "0.05")
    out: list[dict[str, Any]] = []
    for at_sec, vis, amp, hold_ms in sorted(timeline or [], key=lambda x: x[0]):
        out.append(
            {
                "at_ms": max(0, int((at_sec + offset) * 1000)),
                "vowel": str(vis or "").lower(),
                "intensity": max(0.0, min(1.0, float(amp))),
                "hold_ms": max(40, min(400, int(hold_ms))),
            }
        )
    return out


def synthesize_playback_bundle(
    reply_text: str,
    *,
    voice: str | None = None,
) -> TtsPlaybackBundle | None:
    """Synthesize reply audio + lip-sync timeline for the VRM viewer (no local playback)."""
    if not tts_enabled():
        return None
    edge_voice = (voice or "").strip() or get_effective_speaker()
    text, emotion = _clean_text_for_tts(_reply_text_before_tts_clean(reply_text, edge_voice))
    if not text:
        return None
    rate, pitch = _prosody_for_emotion(emotion)
    backend = _backend()
    with _tts_play_lock:
        try:
            if backend == "chatterbox":
                chunk_chars = int(os.environ.get("LUNA_CHATTERBOX_CHUNK_CHARS", "120").strip() or "120")
                chunks = _split_tts_chunks(text, chunk_chars)
                if not chunks:
                    return None
                fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="luna_viewer_")
                os.close(fd)
                wav_out = Path(tmp)
                try:
                    if len(chunks) == 1:
                        _synthesize_chatterbox_to_wav(chunks[0], wav_out, emotion=emotion)
                    else:
                        tmp_parts: list[Path] = []
                        try:
                            for i, part in enumerate(chunks):
                                fd_p, p_tmp = tempfile.mkstemp(
                                    suffix=".wav", prefix=f"luna_viewer_part_{i}_"
                                )
                                os.close(fd_p)
                                p = Path(p_tmp)
                                _synthesize_chatterbox_to_wav(part, p, emotion=emotion)
                                tmp_parts.append(p)
                            _concat_audio_with_ffmpeg(tmp_parts, wav_out)
                        finally:
                            for p in tmp_parts:
                                try:
                                    p.unlink(missing_ok=True)
                                except OSError:
                                    pass
                    cues = _resolve_viseme_timeline(wav_out, [])
                    audio = wav_out.read_bytes()
                    dur_ms = max(1, int(_wav_duration_sec(wav_out) * 1000))
                    return TtsPlaybackBundle(
                        audio=audio,
                        mime="audio/wav",
                        duration_ms=dur_ms,
                        visemes=_visemes_for_timeline(cues),
                    )
                finally:
                    try:
                        wav_out.unlink(missing_ok=True)
                    except OSError:
                        pass

            chunk_chars = int(os.environ.get("LUNA_TTS_CHUNK_CHARS", "380").strip() or "380")
            chunks = _split_tts_chunks(text, chunk_chars)
            if len(chunks) <= 1:
                fd, tmp = tempfile.mkstemp(suffix=".mp3", prefix="luna_viewer_")
                os.close(fd)
                mp3_out = Path(tmp)
                wav_out = mp3_out.with_suffix(".wav")
                try:
                    cues_edge = _synthesize_edge_to_mp3(
                        text,
                        mp3_out,
                        voice=edge_voice,
                        rate=rate,
                        pitch=pitch,
                    )
                    _mp3_to_wav(mp3_out, wav_out)
                    cues = _resolve_viseme_timeline(wav_out, cues_edge)
                    audio = mp3_out.read_bytes()
                    dur_ms = max(1, int(_wav_duration_sec(wav_out) * 1000))
                    visemes = _visemes_for_timeline(cues)
                    return TtsPlaybackBundle(
                        audio=audio,
                        mime="audio/mpeg",
                        duration_ms=dur_ms,
                        visemes=visemes,
                    )
                finally:
                    try:
                        mp3_out.unlink(missing_ok=True)
                        wav_out.unlink(missing_ok=True)
                    except OSError:
                        pass

            fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="luna_viewer_long_")
            os.close(fd)
            wav_out = Path(tmp)
            tmp_parts: list[Path] = []
            try:
                for i, part in enumerate(chunks):
                    fd_p, p_tmp = tempfile.mkstemp(
                        suffix=".mp3", prefix=f"luna_viewer_edge_{i}_"
                    )
                    os.close(fd_p)
                    mp3_part = Path(p_tmp)
                    wav_part = mp3_part.with_suffix(".wav")
                    _synthesize_edge_to_mp3(
                        part,
                        mp3_part,
                        voice=edge_voice,
                        rate=rate,
                        pitch=pitch,
                    )
                    _mp3_to_wav(mp3_part, wav_part)
                    tmp_parts.append(wav_part)
                    try:
                        mp3_part.unlink(missing_ok=True)
                    except OSError:
                        pass
                _concat_audio_with_ffmpeg(tmp_parts, wav_out)
                cues = _resolve_viseme_timeline(wav_out, [])
                audio = wav_out.read_bytes()
                dur_ms = max(1, int(_wav_duration_sec(wav_out) * 1000))
                return TtsPlaybackBundle(
                    audio=audio,
                    mime="audio/wav",
                    duration_ms=dur_ms,
                    visemes=_visemes_for_timeline(cues),
                )
            finally:
                for p in tmp_parts:
                    try:
                        p.unlink(missing_ok=True)
                    except OSError:
                        pass
                try:
                    wav_out.unlink(missing_ok=True)
                except OSError:
                    pass
        except Exception as exc:
            print(f"(LUNA_TTS {backend} viewer bundle failed: {exc})", flush=True)
            return None
    return None


def maybe_speak(
    reply_text: str,
    *,
    viseme_cb: VisemeCallback | None = None,
    voice: str | None = None,
) -> None:
    """Synthesize and PLAY a reply on local speakers (when ``LUNA_TTS_PLAY_TARGET`` includes ``local``)."""
    if not tts_enabled() or not tts_play_locally():
        return
    edge_voice = (voice or "").strip() or get_effective_speaker()
    text, emotion = _clean_text_for_tts(_reply_text_before_tts_clean(reply_text, edge_voice))
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
                        cues = _resolve_viseme_timeline(wav_out, [])
                        _play_wav(
                            wav_out,
                            viseme_events=cues or None,
                            viseme_cb=viseme_cb,
                        )
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
                cues_edge = _synthesize_edge_to_mp3(
                    text,
                    mp3_out,
                    voice=edge_voice,
                    rate=rate,
                    pitch=pitch,
                )
                _mp3_to_wav(mp3_out, wav_out)
                cues = _resolve_viseme_timeline(wav_out, cues_edge)
                _play_wav(
                    wav_out,
                    viseme_events=cues or None,
                    viseme_cb=viseme_cb,
                )
            finally:
                try:
                    mp3_out.unlink(missing_ok=True)
                    wav_out.unlink(missing_ok=True)
                except OSError:
                    pass
        except Exception as exc:
            print(f"(LUNA_TTS {backend} synthesis failed: {exc})", flush=True)


def _edge_tts_chunk_chars() -> int:
    raw = (os.environ.get("LUNA_TTS_CHUNK_CHARS", "220").strip() or "220")
    try:
        return max(80, min(400, int(raw)))
    except ValueError:
        return 220


def _synthesize_edge_to_mp3_file(
    text: str,
    mp3_out: Path,
    *,
    voice: str,
    rate: str,
    pitch: str,
) -> None:
    """Edge TTS export for Discord/files — chunks long replies so nothing is cut off."""
    chunk_chars = _edge_tts_chunk_chars()
    chunks = _split_tts_chunks(text, chunk_chars) or [text]
    # Edge often truncates single requests; always concat when text is non-trivial.
    if len(chunks) <= 1 and len(text) <= chunk_chars:
        _synthesize_edge_to_mp3(text, mp3_out, voice=voice, rate=rate, pitch=pitch)
        return

    wav_parts: list[Path] = []
    try:
        for i, part in enumerate(chunks):
            fd_p, p_tmp = tempfile.mkstemp(suffix=".mp3", prefix=f"luna_edge_file_{i}_")
            os.close(fd_p)
            mp3_part = Path(p_tmp)
            wav_part = mp3_part.with_suffix(".wav")
            _synthesize_edge_to_mp3(part, mp3_part, voice=voice, rate=rate, pitch=pitch)
            _mp3_to_wav(mp3_part, wav_part)
            wav_parts.append(wav_part)
            try:
                mp3_part.unlink(missing_ok=True)
            except OSError:
                pass
        fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="luna_edge_file_combined_")
        os.close(fd)
        combined_wav = Path(tmp)
        try:
            _concat_audio_with_ffmpeg(wav_parts, combined_wav)
            _wav_to_mp3(combined_wav, mp3_out)
        finally:
            try:
                combined_wav.unlink(missing_ok=True)
            except OSError:
                pass
    finally:
        for p in wav_parts:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass


def _env_truthy(key: str, default: bool = False) -> bool:
    raw = (os.environ.get(key, "") or "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def discord_tts_single_file() -> bool:
    """Discord replies use one MP3 (default). Set LUNA_DISCORD_TTS_SINGLE_FILE=0 to split."""
    return _env_truthy("LUNA_DISCORD_TTS_SINGLE_FILE", default=True)


def _discord_tts_max_chars() -> int:
    """Character cap for Discord TTS text; 0 = no limit (full reply, any duration)."""
    raw = (os.environ.get("LUNA_DISCORD_TTS_MAX_CHARS") or "0").strip()
    if raw.lower() in ("0", "none", "unlimited", "off"):
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _discord_tts_chars_per_file() -> int:
    raw = (os.environ.get("LUNA_DISCORD_TTS_CHARS_PER_FILE") or "").strip()
    if raw:
        try:
            return max(100, min(400, int(raw)))
        except ValueError:
            pass
    return 200


def _discord_tts_max_files() -> int:
    raw = (os.environ.get("LUNA_DISCORD_TTS_MAX_FILES") or "6").strip()
    try:
        return max(2, min(10, int(raw)))
    except ValueError:
        return 6


def _find_text_break(s: str, ideal: int, start: int, end: int) -> int:
    """Return split index in ``[start, end]`` closest to ``ideal``."""
    window = s[start:end]
    if not window:
        return end
    local_ideal = ideal - start
    best = -1
    for sep in (". ", "! ", "? ", "; ", ", ", "\n"):
        idx = window.rfind(sep, 0, local_ideal + 40)
        if idx >= 0:
            cut = start + idx + len(sep)
            if cut > best:
                best = cut
    if best > start:
        return best
    idx = window.rfind(" ", max(0, local_ideal - 50), local_ideal + 50)
    if idx > 0:
        return start + idx
    return min(end, ideal)


def _split_text_for_discord_files(text: str) -> list[str]:
    """Split cleaned reply into multiple MP3-sized parts (each <= chars per file)."""
    s = (text or "").strip()
    if not s:
        return []
    per_file = _discord_tts_chars_per_file()
    if len(s) <= per_file:
        return [s]

    max_files = _discord_tts_max_files()
    n = min(max_files, max(2, (len(s) + per_file - 1) // per_file))
    parts: list[str] = []
    start = 0
    size = len(s)
    for i in range(n - 1):
        remaining_parts = n - i
        remaining_len = size - start
        target_len = max(per_file, remaining_len // remaining_parts)
        ideal = start + target_len
        end_bound = min(size, start + per_file + 40)
        cut = _find_text_break(s, ideal, start + max(20, per_file // 3), end_bound)
        if cut <= start:
            cut = min(size, start + per_file)
        chunk = s[start:cut].strip()
        if chunk:
            parts.append(chunk)
        start = cut
    tail = s[start:].strip()
    if tail:
        parts.append(tail)
    # Hard-cap any oversized slice (break logic can overshoot slightly).
    capped: list[str] = []
    for part in parts:
        c = part
        while len(c) > per_file:
            split_at = c.rfind(" ", 0, per_file + 1)
            if split_at < 40:
                split_at = per_file
            capped.append(c[:split_at].strip())
            c = c[split_at:].strip()
        if c:
            capped.append(c)
    return [p for p in capped if p]


def _synthesize_discord_part_to_file(
    part: str,
    *,
    edge_voice: str,
    rate: str,
    pitch: str,
    backend: str,
    emotion: str,
) -> Path | None:
    if not (part or "").strip():
        return None
    try:
        if backend == "chatterbox":
            chunk_chars = int(
                os.environ.get("LUNA_CHATTERBOX_CHUNK_CHARS", "120").strip() or "120"
            )
            chunks = _split_tts_chunks(part, chunk_chars) or [part]
            fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="luna_chatter_discord_")
            os.close(fd)
            out = Path(tmp)
            if len(chunks) == 1:
                _synthesize_chatterbox_to_wav(chunks[0], out, emotion=emotion)
                return out
            tmp_parts: list[Path] = []
            try:
                for i, chunk in enumerate(chunks):
                    fd_p, p_tmp = tempfile.mkstemp(
                        suffix=".wav", prefix=f"luna_chatter_discord_{i}_"
                    )
                    os.close(fd_p)
                    p = Path(p_tmp)
                    _synthesize_chatterbox_to_wav(chunk, p, emotion=emotion)
                    tmp_parts.append(p)
                _concat_audio_with_ffmpeg(tmp_parts, out)
            finally:
                for p in tmp_parts:
                    try:
                        p.unlink(missing_ok=True)
                    except OSError:
                        pass
            return out

        fd, tmp = tempfile.mkstemp(suffix=".mp3", prefix="luna_discord_")
        os.close(fd)
        mp3_out = Path(tmp)
        _synthesize_edge_to_mp3_file(
            part,
            mp3_out,
            voice=edge_voice,
            rate=rate,
            pitch=pitch,
        )
        return mp3_out
    except Exception as exc:
        print(f"(LUNA_TTS {backend} discord part failed: {exc})", flush=True)
        return None


def synthesize_discord_reply_files(
    reply_text: str, *, voice: str | None = None
) -> list[Path]:
    """Synthesize Discord reply audio.

    Default: **one MP3** for the full reply (no length cap; 3+ minutes ok).
    Edge chunks are stitched inside that file. Set ``LUNA_DISCORD_TTS_SINGLE_FILE=0``
    to attach multiple smaller MP3s instead.
    """
    if not tts_enabled():
        return []
    edge_voice = (voice or "").strip() or get_effective_speaker()
    raw_len = len((reply_text or "").strip())
    text, emotion = _clean_text_for_tts(
        _reply_text_before_tts_clean(reply_text, edge_voice),
        max_chars=_discord_tts_max_chars(),
    )
    if not text:
        return []
    rate, pitch = _prosody_for_emotion(emotion)
    backend = _backend()

    if discord_tts_single_file():
        parts = [text]
    else:
        parts = _split_text_for_discord_files(text)

    paths: list[Path] = []
    for part in parts:
        p = _synthesize_discord_part_to_file(
            part,
            edge_voice=edge_voice,
            rate=rate,
            pitch=pitch,
            backend=backend,
            emotion=emotion,
        )
        if p is not None:
            paths.append(p)

    if paths:
        durs = [_probe_audio_duration_sec(p) for p in paths]
        dur_note = f", ~{sum(durs):.0f}s audio" if any(durs) else ""
        print(
            f"(discord tts) {len(text)} chars (raw {raw_len}) -> {len(paths)} mp3"
            f"{dur_note}",
            flush=True,
        )
    return paths


def _probe_audio_duration_sec(path: Path) -> float:
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


def synthesize_reply_to_file(reply_text: str, *, voice: str | None = None) -> Path | None:
    """Synthesize a reply to a standalone audio file without playing it.

    Returns the path to an MP3 (Edge backend) or WAV (Chatterbox). The caller
    owns the file and should delete it when finished (e.g. after uploading to
    Discord). Returns None if TTS is disabled or the reply is empty.

    Prefer ``synthesize_discord_reply_files`` for Discord (may return two files).
    """
    files = synthesize_discord_reply_files(reply_text, voice=voice)
    return files[0] if files else None


def _concat_audio_pydub(parts: list[Path], out_path: Path) -> bool:
    try:
        from pydub import AudioSegment
    except ImportError:
        return False
    if not parts:
        return False
    try:
        combined = AudioSegment.empty()
        for p in parts:
            combined += AudioSegment.from_file(str(p))
        fmt = "wav" if out_path.suffix.lower() == ".wav" else out_path.suffix.lstrip(".") or "wav"
        combined.export(str(out_path), format=fmt)
        return out_path.is_file() and out_path.stat().st_size > 32
    except Exception as exc:
        print(f"(LUNA_TTS concat pydub) failed: {exc}", flush=True)
        return False


def _concat_audio_with_ffmpeg(parts: list[Path], out_path: Path) -> None:
    """Concatenate multiple WAV (or audio) files into one."""
    if not parts:
        return
    if len(parts) == 1:
        out_path.write_bytes(parts[0].read_bytes())
        return

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            delete=False,
            prefix="luna_concat_",
            encoding="utf-8",
        ) as listfile:
            for p in parts:
                # Windows paths: forward slashes + escaped single quotes for concat demuxer.
                path_str = str(p.resolve()).replace("\\", "/").replace("'", "'\\''")
                listfile.write(f"file '{path_str}'\n")
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
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 32:
                return
            err = (proc.stderr or proc.stdout or "").strip()
            if err:
                print(f"(LUNA_TTS concat ffmpeg) {err[:300]}", flush=True)
        finally:
            try:
                os.unlink(list_path)
            except OSError:
                pass

    if _concat_audio_pydub(parts, out_path):
        return

    print(
        f"(LUNA_TTS concat) WARNING: stitched only chunk 1/{len(parts)} — "
        "install ffmpeg on PATH or fix concat; speech may be cut off",
        flush=True,
    )
    out_path.write_bytes(parts[0].read_bytes())


def _word_to_vowel_viseme(word: str) -> str:
    w = re.sub(r"[^a-z]", "", (word or "").lower())
    if not w:
        return ""
    counts = {v: w.count(v) for v in "aeiou"}
    if not any(counts.values()):
        return ""
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _synthesize_edge_to_mp3(
    text: str, out_path: Path, voice: str, rate: str, pitch: str
) -> list[tuple[float, str, float, int]]:
    import edge_tts

    cues: list[tuple[float, str, float, int]] = []

    async def _run() -> None:
        comm = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
        with open(out_path, "wb") as f:
            async for chunk in comm.stream():
                kind = str(chunk.get("type", ""))
                if kind == "audio":
                    data = chunk.get("data")
                    if isinstance(data, (bytes, bytearray)):
                        f.write(data)
                    continue
                # Edge may emit per-word or per-sentence boundaries depending on version.
                if kind == "WordBoundary":
                    raw_text = str(chunk.get("text", "")).strip()
                    vis = _word_to_vowel_viseme(raw_text)
                    if not vis:
                        continue
                    start_sec = max(0.0, float(chunk.get("offset", 0)) / 10_000_000.0)
                    dur_sec = max(0.04, float(chunk.get("duration", 0)) / 10_000_000.0)
                    hold_ms = int(max(70.0, min(260.0, dur_sec * 1000.0 * 0.85)))
                    cues.append((start_sec, vis, 0.95, hold_ms))
                    rest_at = start_sec + min(max(0.05, dur_sec * 0.9), 0.32)
                    cues.append((rest_at, "", 0.0, 85))
                    continue

                if kind == "SentenceBoundary":
                    raw_text = str(chunk.get("text", "")).strip()
                    start_sec = max(0.0, float(chunk.get("offset", 0)) / 10_000_000.0)
                    dur_sec = max(0.06, float(chunk.get("duration", 0)) / 10_000_000.0)
                    words = re.findall(r"[A-Za-z']+", raw_text)
                    if not words:
                        continue
                    weights = [max(1, len(w)) for w in words]
                    total_w = float(sum(weights)) or 1.0
                    span = dur_sec * 0.92
                    acc = 0.0
                    for i, w in enumerate(words):
                        frac = weights[i] / total_w
                        slice_dur = span * frac
                        vis = _word_to_vowel_viseme(w)
                        if vis:
                            t0w = start_sec + acc
                            wdur = max(0.05, slice_dur)
                            hold_ms = int(max(70.0, min(260.0, wdur * 1000.0 * 0.85)))
                            cues.append((t0w, vis, 0.95, hold_ms))
                            rest_at = t0w + min(max(0.05, wdur * 0.88), 0.28)
                            cues.append((rest_at, "", 0.0, 85))
                        acc += slice_dur
                    continue

    asyncio.run(_run())
    cues.sort(key=lambda x: x[0])
    return cues


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


def _wav_to_mp3(src: Path, dst: Path) -> None:
    """Convert WAV → MP3 for Discord file attachments."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg required for WAV→MP3 export")
    cmd = [
        ffmpeg,
        "-y",
        "-v",
        "error",
        "-i",
        str(src),
        "-codec:a",
        "libmp3lame",
        "-q:a",
        "4",
        str(dst),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not dst.exists() or dst.stat().st_size < 32:
        err = (proc.stderr or "").strip() or "ffmpeg wav->mp3 failed"
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


def _viseme_source() -> str:
    v = (os.environ.get("LUNA_TTS_VISEME_SOURCE", "auto").strip() or "auto").lower()
    return v if v in ("auto", "audio", "edge") else "auto"


def _pick_vowel_from_spectrum(
    cent: float,
    r0: float,
    r1: float,
    r2: float,
    r3: float,
    rms_norm: float,
) -> str:
    """Map band energy ratios + centroid to a single mouth vowel (VRM preset ids)."""
    if rms_norm < 0.06:
        return ""
    # Front / high brightness → i / e
    if r3 > 0.16 or (cent > 2600.0 and (r2 + r3) > (r0 + r1) * 0.95):
        return "i"
    if cent > 2100.0 and r2 > r0 * 1.1:
        return "e"
    # Very low, sub-heavy → rounded back (u vs o)
    if r0 > 0.36 and cent < 1150.0:
        return "u" if r0 > r1 * 1.15 else "o"
    if cent < 1450.0 and (r0 + r1) > (r2 + r3) * 1.05:
        return "o" if r0 > 0.22 else "a"
    if r1 > r2 * 1.05 and cent < 2000.0:
        return "a"
    return "e"


def _wav_viseme_timeline_from_audio(path: Path) -> list[tuple[float, str, float, int]]:
    """Build viseme events from the actual TTS waveform (spectral shape + loudness)."""
    try:
        import numpy as np
        import librosa
        import soundfile as sf
    except ImportError:
        return []

    try:
        y, sr = sf.read(str(path), dtype="float32", always_2d=False)
    except OSError:
        return []

    y = np.asarray(y, dtype=np.float32)
    if y.ndim > 1:
        y = np.mean(y, axis=1)
    n_fft = int(os.environ.get("LUNA_TTS_VISEME_N_FFT", "960").strip() or "960")
    n_fft = max(256, min(2048, n_fft))
    hop_default = max(64, n_fft // 4)
    hop = int(os.environ.get("LUNA_TTS_VISEME_HOP", str(hop_default)).strip() or str(hop_default))
    hop = max(32, min(hop, n_fft // 2))

    if y.size < n_fft + hop:
        return []

    center = False
    S = np.abs(
        librosa.stft(y, n_fft=n_fft, hop_length=hop, win_length=n_fft, center=center)
    )
    rms = librosa.feature.rms(
        y=y, frame_length=n_fft, hop_length=hop, center=center
    )[0]
    cent = librosa.feature.spectral_centroid(S=S, sr=sr, n_fft=n_fft, hop_length=hop)[0]

    n = int(min(S.shape[1], len(rms), len(cent)))
    if n < 2:
        return []

    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    ny = float(sr) / 2.0

    def band(lo: float, hi: float) -> np.ndarray:
        m = (freqs >= lo) & (freqs < min(hi, ny))
        return S[m, :n].sum(axis=0) + 1e-10

    e0 = band(0.0, 400.0)
    e1 = band(400.0, 1200.0)
    e2 = band(1200.0, 3500.0)
    e3 = band(3500.0, ny + 1.0)
    et = e0 + e1 + e2 + e3
    r0 = (e0 / et).astype(np.float64)
    r1 = (e1 / et).astype(np.float64)
    r2 = (e2 / et).astype(np.float64)
    r3 = (e3 / et).astype(np.float64)

    rms_n = rms[:n].astype(np.float64)
    mx = float(np.max(rms_n)) + 1e-12
    gate = max(mx * 0.07, 1e-5)
    raw: list[str] = []
    amps: list[float] = []
    for i in range(n):
        rn = float(np.clip(rms_n[i] / mx, 0.0, 1.0))
        if rms_n[i] < gate:
            raw.append("")
            amps.append(0.0)
            continue
        v = _pick_vowel_from_spectrum(
            float(cent[i]),
            float(r0[i]),
            float(r1[i]),
            float(r2[i]),
            float(r3[i]),
            rn,
        )
        raw.append(v)
        amps.append(float(np.clip(rn**0.52 * 1.05, 0.14, 1.0)))

    # Short median smooth to reduce single-frame flicker.
    vow_to_id = {"": 0, "a": 1, "e": 2, "i": 3, "o": 4, "u": 5}
    id_to_vow = {v: k for k, v in vow_to_id.items()}
    ids = np.array([vow_to_id[v] for v in raw], dtype=np.int32)
    win = 3
    pad = win // 2
    ids_p = np.pad(ids, (pad, pad), mode="edge")
    smooth = np.array(
        [int(np.median(ids_p[i : i + win])) for i in range(n)], dtype=np.int32
    )

    hop_sec = hop / float(sr)
    out: list[tuple[float, str, float, int]] = []
    i = 0
    while i < n:
        vid = int(smooth[i])
        v = id_to_vow.get(vid, "")
        if not v:
            i += 1
            continue
        j = i
        peak = amps[i]
        while j + 1 < n and id_to_vow.get(int(smooth[j + 1]), "") == v:
            j += 1
            peak = max(peak, amps[j])
        t0 = float(librosa.frames_to_time(i, sr=sr, hop_length=hop, n_fft=n_fft))
        span_sec = (j - i + 1) * hop_sec
        hold_ms = int(max(48, min(300, span_sec * 1000.0 * 1.08)))
        out.append((t0, v, peak, hold_ms))
        i = j + 1

    return out


def _resolve_viseme_timeline(
    wav_path: Path,
    edge_cues: list[tuple[float, str, float, int]],
) -> list[tuple[float, str, float, int]]:
    src = _viseme_source()
    audio_cues: list[tuple[float, str, float, int]] = []
    try:
        audio_cues = _wav_viseme_timeline_from_audio(wav_path)
    except Exception as exc:
        print(f"(LUNA_TTS audio viseme analysis failed: {exc})", flush=True)

    if src == "edge":
        return sorted(edge_cues, key=lambda x: x[0])
    if src == "audio":
        return audio_cues if audio_cues else sorted(edge_cues, key=lambda x: x[0])
    # auto: prefer sound-shaped timeline when it has body
    if len(audio_cues) >= 3:
        return audio_cues
    return sorted(edge_cues, key=lambda x: x[0]) if edge_cues else audio_cues


def _wav_duration_sec(path: Path) -> float:
    """Best-effort WAV length for scheduling visemes against playback."""
    try:
        with wave.open(str(path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate() or 24000
            if frames <= 0 or rate <= 0:
                return 3.0
            return max(0.05, frames / float(rate))
    except Exception:
        return 3.0


def _blocking_play_wav(path_str: str) -> None:
    if sys.platform == "win32":
        import winsound

        winsound.PlaySound(path_str, winsound.SND_FILENAME)
    elif sys.platform == "darwin":
        subprocess.run(["afplay", path_str], check=False)
    else:
        subprocess.run(["aplay", "-q", path_str], check=False)


def _play_wav(
    path: Path,
    *,
    viseme_events: list[tuple[float, str, float, int]] | None = None,
    viseme_cb: VisemeCallback | None = None,
) -> None:
    stop_scheduler = threading.Event()
    p = str(path)
    timeline = (
        sorted(viseme_events, key=lambda x: x[0])
        if viseme_cb and viseme_events
        else []
    )
    dur = _wav_duration_sec(path)
    offset = float(os.environ.get("LUNA_TTS_VISEME_OFFSET_SEC", "0.05").strip() or "0.05")
    viseme_thread: threading.Thread | None = None
    cb = viseme_cb if timeline else None

    def _emit_timeline(t0: float, boot_slip: float) -> None:
        if not cb:
            return
        for at_sec, vis, amp, hold_ms in timeline:
            if stop_scheduler.is_set():
                break
            target = t0 + boot_slip + offset + at_sec
            delay = target - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            if stop_scheduler.is_set():
                break
            try:
                cb(vis, float(amp), int(hold_ms))
            except Exception:
                pass

    try:
        if not timeline:
            _blocking_play_wav(p)
            return

        if sys.platform == "win32":
            import winsound

            SND_ASYNC = getattr(winsound, "SND_ASYNC", 0x0001)
            async_ok = False
            try:
                winsound.PlaySound(p, winsound.SND_FILENAME | SND_ASYNC)
                async_ok = True
            except Exception:
                pass
            if async_ok:
                t0 = time.monotonic()
                _emit_timeline(t0, boot_slip=0.03)
                remain = (t0 + dur) - time.monotonic()
                if remain > 0:
                    time.sleep(remain)
                return

            cv = threading.Condition()
            st: dict[str, float | bool] = {"go": False, "t0": 0.0}

            def _vis_win_sync() -> None:
                with cv:
                    while not st["go"]:
                        cv.wait(timeout=8.0)
                    t0w = float(st["t0"])
                _emit_timeline(t0w, boot_slip=0.12)

            def _audio_win_sync() -> None:
                with cv:
                    st["t0"] = time.monotonic()
                    st["go"] = True
                    cv.notify_all()
                winsound.PlaySound(p, winsound.SND_FILENAME)

            viseme_thread = threading.Thread(target=_vis_win_sync, daemon=True)
            viseme_thread.start()
            _audio_win_sync()
            stop_scheduler.set()
            viseme_thread.join(timeout=max(3.0, dur + 4.0))
            return

        if sys.platform == "darwin":
            proc = subprocess.Popen(
                ["afplay", p],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            t0 = time.monotonic()
            _emit_timeline(t0, boot_slip=0.05)
            try:
                proc.wait(timeout=max(5.0, dur + 8.0))
            except subprocess.TimeoutExpired:
                proc.kill()
            return

        ffplay = shutil.which("ffplay")
        if ffplay:
            proc = subprocess.Popen(
                [
                    ffplay,
                    "-nodisp",
                    "-autoexit",
                    "-loglevel",
                    "quiet",
                    "-vn",
                    p,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            t0 = time.monotonic()
            _emit_timeline(t0, boot_slip=0.05)
            try:
                proc.wait(timeout=max(5.0, dur + 8.0))
            except subprocess.TimeoutExpired:
                proc.kill()
            return

        proc = subprocess.Popen(
            ["aplay", "-q", p],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        t0 = time.monotonic()
        _emit_timeline(t0, boot_slip=0.05)
        try:
            proc.wait(timeout=max(5.0, dur + 8.0))
        except subprocess.TimeoutExpired:
            proc.kill()
    finally:
        stop_scheduler.set()
        if viseme_thread is not None:
            viseme_thread.join(timeout=0.5)
        if viseme_cb:
            try:
                viseme_cb("", 0.0, 80)
            except Exception:
                pass
