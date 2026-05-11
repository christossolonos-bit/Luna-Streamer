"""Optional male-voice gate for viewer mic (reduces picking up female TTS / Luna from headphones).

Uses median fundamental frequency (F0) on decoded PCM — rough but lightweight.
Env:
  LUNA_VOICE_GATE_MALE_ONLY   1/true = reject clips classified as female-range pitch (default 0).
  LUNA_VOICE_GATE_MAX_F0_HZ   Median F0 must be <= this (Hz) to pass (default 172).
"""

from __future__ import annotations

import os
from pathlib import Path


def voice_gate_enabled() -> bool:
    raw = (os.environ.get("LUNA_VOICE_GATE_MALE_ONLY") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def voice_gate_max_f0_hz() -> float:
    raw = (os.environ.get("LUNA_VOICE_GATE_MAX_F0_HZ") or "172").strip() or "172"
    try:
        return max(80.0, float(raw))
    except ValueError:
        return 172.0


def median_f0_hz(wav_path: Path) -> float | None:
    """Median voiced F0 in Hz, or None if no voiced frames."""
    import librosa
    import numpy as np

    y, sr = librosa.load(str(wav_path), sr=None, mono=True)
    if y.size < sr // 4:
        return None

    f0_hz, _, _ = librosa.pyin(
        y,
        fmin=librosa.note_to_hz("C2"),
        fmax=librosa.note_to_hz("C7"),
        sr=sr,
        frame_length=2048,
        hop_length=160,
    )
    voiced = ~np.isnan(f0_hz)
    if not np.any(voiced):
        return None
    vals = f0_hz[voiced]
    return float(np.median(vals))


def male_voice_accepted(wav_path: Path) -> tuple[bool, str]:
    """Return (passes_gate, human-readable note). When gate disabled, always (True, '')."""
    if not voice_gate_enabled():
        return True, ""

    try:
        import librosa  # noqa: F401
    except ImportError:
        return (
            False,
            "voice gate: install librosa (pip install librosa)",
        )

    max_hz = voice_gate_max_f0_hz()
    med = median_f0_hz(wav_path)
    if med is None:
        return False, "voice gate: no clear voiced pitch"

    if med <= max_hz:
        return True, f"(voice gate ok: median F0 ~{med:.0f} Hz)"

    return False, f"voice gate: rejected female-range pitch (~{med:.0f} Hz; max {max_hz:.0f} Hz)"


def gate_status_line() -> str:
    if not voice_gate_enabled():
        return "voice gate: off"
    return f"voice gate: male≤{voice_gate_max_f0_hz():.0f} Hz"
