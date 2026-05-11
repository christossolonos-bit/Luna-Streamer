"""Local speech-to-text with faster-whisper (Whisper model weights).

Env:
  LUNA_STT_LOCAL_MODEL   Model size: tiny, base, small, medium, large-v2, large-v3 (default tiny).
  LUNA_STT_LOCAL_DEVICE  cpu or cuda (unset = auto: cuda if a CUDA GPU is visible, else cpu).
  LUNA_STT_LOCAL_COMPUTE int8, float16, etc. (unset = float16 on cuda, int8 on cpu).
  LUNA_STT_LANGUAGE      Language code passed to whisper (default "en" — skip auto-detect).
                         Set "auto" to enable language detection on every clip.
  LUNA_STT_BEAM_SIZE     Beam size for decode (default 1 — fastest, fine for short live clips).
  LUNA_VOICE_GATE_*      See luna_voice_gate.py (viewer mic male-voice filter).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from luna_speaker_id import speaker_gate_enabled, speaker_status_line, verify as speaker_verify
from luna_voice_gate import gate_status_line, male_voice_accepted, voice_gate_enabled

_local_model = None
_prewarm_attempted = False


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


def _resolve_language() -> str | None:
    raw = (os.environ.get("LUNA_STT_LANGUAGE") or "en").strip().lower()
    if raw in ("", "auto", "detect"):
        return None
    return raw


def _resolve_beam_size() -> int:
    raw = (os.environ.get("LUNA_STT_BEAM_SIZE") or "1").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


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


def _ensure_local_model():
    """Load the faster-whisper model once and reuse it."""
    global _local_model
    if _local_model is None:
        from faster_whisper import WhisperModel

        name = os.environ.get("LUNA_STT_LOCAL_MODEL", "tiny").strip() or "tiny"
        device = _resolve_whisper_device()
        ctype = _resolve_whisper_compute(device)
        _local_model = WhisperModel(name, device=device, compute_type=ctype)
    return _local_model


def _transcribe_wav_path(wav_path: Path) -> str:
    model = _ensure_local_model()
    language = _resolve_language()
    beam = _resolve_beam_size()
    # Use soundfile to read the already-normalised 16k mono PCM — skips
    # faster-whisper's internal ffmpeg shell-out per clip.
    audio_arr = None
    try:
        import numpy as np
        import soundfile as sf

        data, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
        if isinstance(data, np.ndarray):
            if data.ndim > 1:
                data = data.mean(axis=1)
            if sr != 16000:
                # _decoded_wav_temp already resamples to 16k, but stay safe.
                ratio = 16000 / float(sr)
                idx = (np.arange(int(len(data) * ratio)) / ratio).astype(np.int64)
                idx = np.clip(idx, 0, len(data) - 1)
                data = data[idx]
            audio_arr = data.astype(np.float32)
    except Exception:
        audio_arr = None

    target = audio_arr if audio_arr is not None else str(wav_path)
    segments, _info = model.transcribe(
        target,
        vad_filter=True,
        language=language,
        beam_size=beam,
        condition_on_previous_text=False,
    )
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
    except Exception as exc:
        return "", f"failed: {exc}"


def prewarm() -> None:
    """Force-load the Whisper model + run one tiny dummy decode in the background.

    Cuts the wall-clock cost of the first real user utterance from ~3–6 s
    (model + CUDA kernels initialisation) down to the actual decode time.
    Safe to call multiple times — it is a no-op after the first success.
    """
    global _prewarm_attempted
    if _prewarm_attempted:
        return
    _prewarm_attempted = True
    try:
        import numpy as np

        model = _ensure_local_model()
        # 0.5 s of silence at 16 kHz — fastest possible decode that still
        # exercises the CT2 / CUDA path.
        dummy = np.zeros(8000, dtype=np.float32)
        # Drain the generator so the work actually happens.
        for _ in model.transcribe(
            dummy,
            vad_filter=False,
            language=_resolve_language() or "en",
            beam_size=1,
            condition_on_previous_text=False,
        )[0]:
            pass
    except Exception as exc:
        print(f"(stt prewarm) skipped: {exc}", flush=True)


def stt_status_line() -> str:
    model = os.environ.get("LUNA_STT_LOCAL_MODEL", "tiny").strip() or "tiny"
    device = _resolve_whisper_device()
    language = _resolve_language() or "auto"
    return (
        f"faster-whisper:{model} ({device}, lang={language}, beam={_resolve_beam_size()}); "
        f"{speaker_status_line()}; {gate_status_line()}"
    )
