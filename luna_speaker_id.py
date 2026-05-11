"""Speaker verification for the viewer panel.

Enroll one or more short reference clips (record again to add another one);
later, accept viewer mic clips only if their embedding is close enough
(cosine similarity) to ANY of the enrolled references.

Embedding (per clip):
  - 13 MFCC + 13 ΔMFCC + 13 ΔΔMFCC frames
  - energy-based VAD: drop frames quieter than (mean − k·std) RMS
  - CMVN per utterance (subtract mean, divide by std along time axis)
  - mean ⊕ std pool → 78-dim
  - L2-normalised

This is much more stable across different phonetic content than a plain MFCC
mean, which is why earlier same-speaker clips were producing wildly varying
similarities.

Env:
  LUNA_SPEAKER_ONLY      1/true = drop viewer mic clips that don't match the enrolled voice.
  LUNA_SPEAKER_MIN_SIM   Cosine similarity threshold (default 0.65; 1.0 = identical).
  LUNA_SPEAKER_REF       Path to PRIMARY reference WAV (default: <project>/speaker_ref.wav).
                         Additional enrollments are stored alongside it.
  LUNA_SPEAKER_REF_DIR   Folder for extra enrollments (default: <project>/data/speaker_refs).
  LUNA_SPEAKER_TOPK      How many top-scoring refs to log when verify fails (default 1).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

# Cached references: list of (path, mtime, embedding).
_ref_cache: list[tuple[Path, float, np.ndarray]] = []
_last_similarity: float | None = None


def _ref_path() -> Path:
    raw = (os.environ.get("LUNA_SPEAKER_REF") or "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parent / "speaker_ref.wav"


def _ref_dir() -> Path:
    raw = (os.environ.get("LUNA_SPEAKER_REF_DIR") or "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parent / "data" / "speaker_refs"


def speaker_gate_enabled() -> bool:
    raw = (os.environ.get("LUNA_SPEAKER_ONLY") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def speaker_min_sim() -> float:
    raw = (os.environ.get("LUNA_SPEAKER_MIN_SIM") or "0.65").strip() or "0.65"
    try:
        return max(0.1, min(0.99, float(raw)))
    except ValueError:
        return 0.65


def _existing_ref_files() -> list[Path]:
    """All on-disk reference clips. Primary first, then sorted dir entries."""
    primary = _ref_path()
    extra_dir = _ref_dir()
    files: list[Path] = []
    if primary.is_file() and primary.stat().st_size > 1024:
        files.append(primary)
    if extra_dir.is_dir():
        for p in sorted(extra_dir.glob("*.wav")):
            if p.resolve() == primary.resolve():
                continue
            if p.stat().st_size > 1024:
                files.append(p)
    return files


def is_enrolled() -> bool:
    return bool(_existing_ref_files())


def last_similarity() -> float | None:
    return _last_similarity


def _load_wav_16k_mono(wav_path: Path) -> tuple[np.ndarray, int] | None:
    """Fast 16k mono float32 load via soundfile, with librosa as a fallback."""
    try:
        import soundfile as sf

        data, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
        if data.ndim > 1:
            data = data.mean(axis=1)
        if sr != 16000:
            ratio = 16000 / float(sr)
            idx = (np.arange(int(len(data) * ratio)) / ratio).astype(np.int64)
            idx = np.clip(idx, 0, len(data) - 1)
            data = data[idx]
            sr = 16000
        return data.astype(np.float32), sr
    except Exception:
        pass
    try:
        import librosa

        y, sr = librosa.load(str(wav_path), sr=16000, mono=True)
        return y.astype(np.float32), sr
    except Exception:
        return None


def _energy_vad(
    y: np.ndarray, frame_len: int = 512, hop: int = 256, k: float = 1.0
) -> np.ndarray:
    """Boolean per-frame mask: True where the frame is louder than the floor.

    Floor = mean RMS − k * std RMS, clipped at a small minimum so a near-silent
    clip doesn't keep every frame.
    """
    if y.size < frame_len:
        return np.ones(1, dtype=bool)
    n_frames = 1 + (y.size - frame_len) // hop
    if n_frames < 2:
        return np.ones(n_frames, dtype=bool)
    rms = np.empty(n_frames, dtype=np.float32)
    for i in range(n_frames):
        seg = y[i * hop : i * hop + frame_len]
        rms[i] = float(np.sqrt(np.mean(seg * seg) + 1e-12))
    rms_log = np.log(rms + 1e-8)
    floor = rms_log.mean() - k * rms_log.std()
    floor = max(floor, np.log(1e-3))
    return rms_log > floor


def _compute_embedding(wav_path: Path) -> np.ndarray | None:
    """MFCC + delta + delta-delta with energy VAD, CMVN, mean+std pooling.

    Returns a 78-dim L2-normalised vector, or None if the clip is too short
    or silent.
    """
    try:
        import librosa
    except ImportError:
        return None

    loaded = _load_wav_16k_mono(wav_path)
    if loaded is None:
        return None
    y, sr = loaded
    if y.size < sr // 2:  # need at least 0.5 s of audio
        return None
    # Soft-trim leading/trailing silence so VAD can focus on the actual speech.
    yt, _ = librosa.effects.trim(y, top_db=30)
    if yt.size < sr // 4:
        yt = y
    # 25 ms / 10 ms frames is standard for speech features.
    n_fft = 512
    hop_length = 160  # 10 ms @ 16 kHz
    win_length = 400  # 25 ms @ 16 kHz
    mfcc = librosa.feature.mfcc(
        y=yt,
        sr=sr,
        n_mfcc=13,
        n_fft=n_fft,
        hop_length=hop_length,
        win_length=win_length,
    )
    d1 = librosa.feature.delta(mfcc)
    d2 = librosa.feature.delta(mfcc, order=2)
    feats = np.vstack([mfcc, d1, d2])  # (39, T)

    # Energy VAD on the same hop so we can mask frames consistently.
    voiced = _energy_vad(yt, frame_len=win_length, hop=hop_length)
    # Align lengths defensively (librosa and our VAD can differ by one frame).
    T = min(feats.shape[1], voiced.size)
    feats = feats[:, :T]
    voiced = voiced[:T]
    if voiced.sum() < 8:
        # Not enough voiced frames — fall back to using everything.
        voiced = np.ones(T, dtype=bool)

    feats_v = feats[:, voiced]

    # CMVN per utterance (per-feature mean/std along time).
    mean = feats_v.mean(axis=1, keepdims=True)
    std = feats_v.std(axis=1, keepdims=True)
    std[std < 1e-8] = 1e-8
    feats_v = (feats_v - mean) / std

    # Pool: mean and std across remaining frames.
    pooled_mean = feats_v.mean(axis=1)
    pooled_std = feats_v.std(axis=1)
    emb = np.concatenate([pooled_mean, pooled_std]).astype(np.float32)

    norm = float(np.linalg.norm(emb))
    if norm < 1e-8 or not np.isfinite(norm):
        return None
    return emb / norm


def _refresh_cache() -> list[np.ndarray]:
    """Re-load any reference clip whose mtime changed; drop deleted ones."""
    global _ref_cache
    files = _existing_ref_files()
    by_path = {p: (mt, emb) for (p, mt, emb) in _ref_cache}
    new_cache: list[tuple[Path, float, np.ndarray]] = []
    for p in files:
        mt = p.stat().st_mtime
        cached = by_path.get(p)
        if cached is not None and cached[0] == mt:
            new_cache.append((p, mt, cached[1]))
            continue
        emb = _compute_embedding(p)
        if emb is not None:
            new_cache.append((p, mt, emb))
    _ref_cache = new_cache
    return [emb for _, _, emb in new_cache]


def verify(wav_path: Path) -> tuple[bool, str]:
    """Return (passes, status text). Stores best similarity in last_similarity()."""
    global _last_similarity
    _last_similarity = None
    if not speaker_gate_enabled():
        return True, ""
    refs = _refresh_cache()
    if not refs:
        return False, "speaker check: no enrolled voice — record one in the panel first"
    emb = _compute_embedding(wav_path)
    if emb is None:
        return False, "speaker check: clip too short / silent"
    sims = [float(np.dot(r, emb)) for r in refs]
    best = max(sims)
    _last_similarity = best
    threshold = speaker_min_sim()
    if best >= threshold:
        note = f"(speaker ok, sim {best:.2f}"
        if len(refs) > 1:
            note += f" of {len(refs)} refs"
        note += ")"
        return True, note
    return False, (
        f"speaker rejected (sim {best:.2f} < {threshold:.2f}"
        f"{f' across {len(refs)} refs' if len(refs) > 1 else ''}). "
        "Try recording another enrollment clip to improve coverage."
    )


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


def _next_extra_ref_path() -> Path:
    extra_dir = _ref_dir()
    extra_dir.mkdir(parents=True, exist_ok=True)
    n = 2
    while True:
        candidate = extra_dir / f"speaker_ref_{n}.wav"
        if not candidate.exists():
            return candidate
        n += 1
        if n > 999:  # absurd ceiling
            return candidate


def enroll_from_bytes(audio: bytes, mime: str) -> tuple[bool, str]:
    """Save reference WAV and validate it produces a usable embedding.

    First enrollment goes to ``LUNA_SPEAKER_REF`` (default ``speaker_ref.wav``).
    Subsequent calls APPEND additional references in
    ``LUNA_SPEAKER_REF_DIR`` (default ``data/speaker_refs/``). Verification then
    accepts any clip that matches *any* of the stored references — which is
    why re-recording with different phonetic content makes Luna much less
    picky.
    """
    global _ref_cache
    if not audio or len(audio) < 4096:
        return False, "enroll: clip too short (record 3-5 sec)"
    suffix = _suffix_for_mime(mime)

    primary = _ref_path()
    if primary.is_file() and primary.stat().st_size > 1024:
        target = _next_extra_ref_path()
    else:
        target = primary
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        _ffmpeg_decode(audio, suffix, target)
    except Exception as exc:
        return False, f"enroll: decode failed ({exc})"

    # Force re-load of this file on next verify, but also probe now to confirm
    # the clip is actually usable before telling the user "ok".
    _ref_cache = [(p, mt, emb) for (p, mt, emb) in _ref_cache if p != target]
    emb = _compute_embedding(target)
    if emb is None:
        try:
            target.unlink()
        except OSError:
            pass
        return False, "enroll: no clear voice in clip — try again with steady speech"

    _ref_cache.append((target, target.stat().st_mtime, emb))
    total = len(_existing_ref_files())
    if total == 1:
        return True, f"enroll: voice saved ({target.name}). Record again to add more samples for robustness."
    return True, f"enroll: voice saved ({target.name}, {total} samples total)."


def clear_enrollment() -> bool:
    """Wipe every stored reference clip + clear the cache."""
    global _ref_cache, _last_similarity
    deleted_any = False
    for p in _existing_ref_files():
        try:
            p.unlink()
            deleted_any = True
        except OSError:
            pass
    extra_dir = _ref_dir()
    if extra_dir.is_dir():
        try:
            shutil.rmtree(extra_dir, ignore_errors=True)
        except OSError:
            pass
    _ref_cache = []
    _last_similarity = None
    return deleted_any


def speaker_state() -> dict:
    files = _existing_ref_files()
    return {
        "enabled": speaker_gate_enabled(),
        "enrolled": bool(files),
        "min_sim": speaker_min_sim(),
        "last_sim": _last_similarity,
        "samples": len(files),
    }


def speaker_status_line() -> str:
    if not speaker_gate_enabled():
        return "speaker gate: off"
    files = _existing_ref_files()
    if not files:
        return "speaker gate: enabled but not enrolled"
    return f"speaker gate: enrolled ({len(files)} sample{'s' if len(files) != 1 else ''}, ≥{speaker_min_sim():.2f})"
