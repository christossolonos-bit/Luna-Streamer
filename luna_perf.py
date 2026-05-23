"""Viewer/bot performance helpers (screen capture sync, DPR cap)."""

from __future__ import annotations

import os


def screen_context_interval_sec(requested: float) -> float:
    return max(5.0, min(requested, 300.0))


def screen_capture_interval_ms() -> int:
    raw = (os.environ.get("LUNA_SCREEN_CAPTURE_INTERVAL_MS") or "1000").strip() or "1000"
    try:
        ms = int(float(raw))
    except ValueError:
        ms = 1000
    return max(2000, min(ms, 120_000))


def screen_capture_max_width() -> int:
    raw = (os.environ.get("LUNA_SCREEN_CAPTURE_MAX_WIDTH") or "1280").strip() or "1280"
    try:
        return max(480, min(int(float(raw)), 1920))
    except ValueError:
        return 1280


def screen_capture_jpeg_quality() -> float:
    raw = (os.environ.get("LUNA_SCREEN_CAPTURE_JPEG_QUALITY") or "0.72").strip() or "0.72"
    try:
        return max(0.4, min(float(raw), 0.92))
    except ValueError:
        return 0.72


def screen_context_max_chars() -> int:
    raw = (os.environ.get("LUNA_SCREEN_CONTEXT_MAX_CHARS") or "1200").strip() or "1200"
    try:
        return max(200, min(int(raw), 4000))
    except ValueError:
        return 1200


def _parse_keep_alive(raw: str, *, default: str | None) -> float | str | int | None:
    val = (raw or default or "").strip()
    if not val:
        return None
    if val == "-1":
        return -1
    try:
        return float(val)
    except ValueError:
        return val


def screen_ollama_keep_alive() -> float | str | int | None:
    """Vision-only keep_alive (chat uses ``LUNA_OLLAMA_KEEP_ALIVE``)."""
    return _parse_keep_alive(
        (os.environ.get("LUNA_SCREEN_KEEP_ALIVE") or "").strip(),
        default="2m",
    )


def viewer_renderer_max_dpr() -> float:
    raw = (os.environ.get("LUNA_VIEWER_MAX_DPR") or "").strip()
    if not raw:
        return 1.5
    try:
        return max(0.75, min(float(raw), 2.0))
    except ValueError:
        return 1.5


def viewer_perf_control_message() -> dict:
    raw = (os.environ.get("LUNA_SCREEN_CONTEXT_INTERVAL_SEC") or "15").strip() or "15"
    try:
        ctx_sec = float(raw)
    except ValueError:
        ctx_sec = 15.0
    return {
        "type": "control",
        "name": "perf_config",
        "screen_capture_interval_ms": screen_capture_interval_ms(),
        "screen_context_interval_sec": screen_context_interval_sec(ctx_sec),
        "screen_capture_max_width": screen_capture_max_width(),
        "screen_capture_jpeg_quality": screen_capture_jpeg_quality(),
        "renderer_max_dpr": viewer_renderer_max_dpr(),
    }
