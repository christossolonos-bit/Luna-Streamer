"""Local speech-to-text with faster-whisper (Whisper model weights).

Env:
  LUNA_STT_LOCAL_MODEL   Model size: tiny, base, small, medium, large-v2, large-v3 (default tiny).
  LUNA_STT_LOCAL_DEVICE  cpu or cuda (unset = auto: cuda if a CUDA GPU is visible, else cpu).
  LUNA_STT_LOCAL_COMPUTE int8, float16, etc. (unset = float16 on cuda, int8 on cpu).
  LUNA_VOICE_GATE_*      See luna_voice_gate.py (viewer mic male-voice filter).
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from luna_speaker_id import speaker_gate_enabled, speaker_status_line, verify as speaker_verify
from luna_voice_gate import gate_status_line, male_voice_accepted, voice_gate_enabled

_local_model = None


def _resolve_whisper_device() -> str:
    explicit = (os.environ.get("LUNA_STT_LOCAL_DEVICE") or "").strip()
    if explicit:
        return explicit
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _resolve_whisper_compute(device: str) -> str:
    explicit = (os.environ.get("LUNA_STT_LOCAL_COMPUTE") or "").strip()
    if explicit:
        return explicit
    return "float16" if device == "cuda" else "int8"


def _suffix_for_mime(mime: str) -> str:
    m = (mime or "").lower()
    if "webm" in m:
        return ".webm"
    if "wav" in m:
        return ".wav"
    if "mp4" in m or "mpga" in m or "m4a" in m:
        return ".m4a"
    if "ogg" in m:
        return ".ogg"
    return ".webm"


@contextmanager
def _decoded_wav_temp(audio: bytes, suffix: str):
    """Yield path to 16 kHz mono WAV (ffmpeg). Cleans up temp dir on exit."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found in PATH")

    with tempfile.TemporaryDirectory(prefix="luna_stt_") as td:
        in_path = Path(td) / f"in{suffix}"
        wav_path = Path(td) / "norm.wav"
        in_path.write_bytes(audio)

        cmd = [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-i",
            str(in_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            str(wav_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0 or (not wav_path.exists()) or wav_path.stat().st_size < 256:
            err = (proc.stderr or "").strip() or "ffmpeg conversion failed"
            raise RuntimeError(err)
        yield wav_path


def _transcribe_wav_path(wav_path: Path) -> str:
    global _local_model
    from faster_whisper import WhisperModel

    name = os.environ.get("LUNA_STT_LOCAL_MODEL", "tiny").strip() or "tiny"
    if _local_model is None:
        device = _resolve_whisper_device()
        ctype = _resolve_whisper_compute(device)
        _local_model = WhisperModel(name, device=device, compute_type=ctype)

    segments, _info = _local_model.transcribe(str(wav_path), vad_filter=True)
    parts = [s.text.strip() for s in segments if s.text and s.text.strip()]
    return " ".join(parts).strip()


def _transcribe_local(audio: bytes, _suffix: str) -> str:
    global _local_model
    from faster_whisper import WhisperModel

    name = os.environ.get("LUNA_STT_LOCAL_MODEL", "tiny").strip() or "tiny"
    if _local_model is None:
        device = _resolve_whisper_device()
        ctype = _resolve_whisper_compute(device)
        _local_model = WhisperModel(name, device=device, compute_type=ctype)
    bio = io.BytesIO(audio)
    segments, _info = _local_model.transcribe(bio, vad_filter=True)
    parts = [s.text.strip() for s in segments if s.text and s.text.strip()]
    return " ".join(parts).strip()


def transcribe_audio(audio: bytes, mime: str = "") -> tuple[str, str]:
    """Return (transcript, note). note is ``faster-whisper`` or ``failed: …``."""
    if not audio or len(audio) < 64:
        return "", "failed: audio too short"
    suffix = _suffix_for_mime(mime)

    try:
        with _decoded_wav_temp(audio, suffix) as wav_path:
            gate_note = ""
            if speaker_gate_enabled():
                ok, gate_note = speaker_verify(wav_path)
                if not ok:
                    return "", gate_note
            elif voice_gate_enabled():
                ok, gate_note = male_voice_accepted(wav_path)
                if not ok:
                    return "", gate_note
            t = _transcribe_wav_path(wav_path)
            if not t:
                return "", "failed: no speech detected"
            note = "faster-whisper"
            if gate_note:
                note = f"faster-whisper {gate_note}"
            return t, note
    except Exception:
        try:
            t = _transcribe_local(audio, suffix)
            if t:
                return t, "faster-whisper (raw, gates bypassed)"
            return "", "failed: no speech detected"
        except Exception as exc:
            return "", f"failed: {exc}"


def stt_status_line() -> str:
    model = os.environ.get("LUNA_STT_LOCAL_MODEL", "tiny").strip() or "tiny"
    device = _resolve_whisper_device()
    return (
        f"faster-whisper:{model} ({device}); "
        f"{speaker_status_line()}; {gate_status_line()}"
    )
