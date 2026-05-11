"""Speaker verification for the viewer panel.

Enroll a short reference clip; later, accept mic clips only if their MFCC
embedding is close enough (cosine similarity) to the enrollment.

Lightweight (librosa + numpy only — no torch). Good enough to tell the
streamer's voice from Luna's TTS / other speakers.

Env:
  LUNA_SPEAKER_ONLY      1/true = drop viewer mic clips that don't match the enrolled voice.
  LUNA_SPEAKER_MIN_SIM   Cosine similarity threshold to pass (default 0.75; 1.0 = identical).
  LUNA_SPEAKER_REF       Path to reference WAV (default: <project>/speaker_ref.wav).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

_ref_emb: np.ndarray | None = None
_ref_mtime: float = 0.0
_last_similarity: float | None = None


def _ref_path() -> Path:
    raw = (os.environ.get("LUNA_SPEAKER_REF") or "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parent / "speaker_ref.wav"


def speaker_gate_enabled() -> bool:
    raw = (os.environ.get("LUNA_SPEAKER_ONLY") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def speaker_min_sim() -> float:
    raw = (os.environ.get("LUNA_SPEAKER_MIN_SIM") or "0.75").strip() or "0.75"
    try:
        return max(0.1, min(0.99, float(raw)))
    except ValueError:
        return 0.75


def is_enrolled() -> bool:
    p = _ref_path()
    return p.is_file() and p.stat().st_size > 1024


def last_similarity() -> float | None:
    return _last_similarity


def _compute_embedding(wav_path: Path) -> np.ndarray | None:
    """MFCC mean over voiced/trimmed frames -> unit-norm vector."""
    try:
        import librosa
    except ImportError:
        return None

    y, sr = librosa.load(str(wav_path), sr=16000, mono=True)
    if y.size < sr // 2:  # need at least 0.5 s
        return None
    yt, _ = librosa.effects.trim(y, top_db=30)
    if yt.size < sr // 4:
        yt = y
    mfcc = librosa.feature.mfcc(y=yt, sr=sr, n_mfcc=20)
    mfcc -= mfcc.mean(axis=1, keepdims=True)
    std = mfcc.std(axis=1, keepdims=True)
    std[std < 1e-8] = 1e-8
    mfcc /= std
    emb = mfcc.mean(axis=1)
    norm = float(np.linalg.norm(emb))
    if norm < 1e-8:
        return None
    return emb / norm


def _reference_embedding() -> np.ndarray | None:
    global _ref_emb, _ref_mtime
    p = _ref_path()
    if not p.is_file():
        _ref_emb, _ref_mtime = None, 0.0
        return None
    mt = p.stat().st_mtime
    if _ref_emb is None or mt != _ref_mtime:
        _ref_emb = _compute_embedding(p)
        _ref_mtime = mt
    return _ref_emb


def verify(wav_path: Path) -> tuple[bool, str]:
    """Return (passes, status text). Stores similarity in _last_similarity."""
    global _last_similarity
    _last_similarity = None
    if not speaker_gate_enabled():
        return True, ""
    ref = _reference_embedding()
    if ref is None:
        return False, "speaker check: no enrolled voice — record one in the panel first"
    emb = _compute_embedding(wav_path)
    if emb is None:
        return False, "speaker check: clip too short / silent"
    sim = float(np.dot(ref, emb))
    _last_similarity = sim
    threshold = speaker_min_sim()
    if sim >= threshold:
        return True, f"(speaker ok, sim {sim:.2f})"
    return False, f"speaker rejected (sim {sim:.2f} < {threshold:.2f})"


def _suffix_for_mime(mime: str) -> str:
    m = (mime or "").lower()
    if "webm" in m:
        return ".webm"
    if "wav" in m:
        return ".wav"
    if "mp4" in m or "m4a" in m or "mpga" in m:
        return ".m4a"
    if "ogg" in m:
        return ".ogg"
    return ".webm"


def _ffmpeg_decode(audio: bytes, suffix: str, out_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found in PATH")
    with tempfile.TemporaryDirectory(prefix="luna_enroll_") as td:
        in_path = Path(td) / f"in{suffix}"
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
            str(out_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0 or not out_path.exists() or out_path.stat().st_size < 1024:
            err = (proc.stderr or "").strip() or "ffmpeg conversion failed"
            raise RuntimeError(err)


def enroll_from_bytes(audio: bytes, mime: str) -> tuple[bool, str]:
    """Save reference WAV and validate it produces a usable embedding."""
    global _ref_emb, _ref_mtime
    if not audio or len(audio) < 4096:
        return False, "enroll: clip too short (record 3-5 sec)"
    suffix = _suffix_for_mime(mime)
    ref = _ref_path()
    ref.parent.mkdir(parents=True, exist_ok=True)
    try:
        _ffmpeg_decode(audio, suffix, ref)
    except Exception as exc:
        return False, f"enroll: decode failed ({exc})"

    _ref_emb = None
    _ref_mtime = 0.0
    emb = _reference_embedding()
    if emb is None:
        try:
            ref.unlink()
        except OSError:
            pass
        return False, "enroll: no clear voice in clip — try again with steady speech"
    return True, f"enroll: voice saved ({ref.name})"


def clear_enrollment() -> bool:
    global _ref_emb, _ref_mtime, _last_similarity
    _ref_emb = None
    _ref_mtime = 0.0
    _last_similarity = None
    p = _ref_path()
    if p.is_file():
        try:
            p.unlink()
            return True
        except OSError:
            return False
    return False


def speaker_state() -> dict:
    return {
        "enabled": speaker_gate_enabled(),
        "enrolled": is_enrolled(),
        "min_sim": speaker_min_sim(),
        "last_sim": _last_similarity,
    }


def speaker_status_line() -> str:
    if not speaker_gate_enabled():
        return "speaker gate: off"
    if not is_enrolled():
        return "speaker gate: enabled but not enrolled"
    return f"speaker gate: enrolled (≥{speaker_min_sim():.2f})"
