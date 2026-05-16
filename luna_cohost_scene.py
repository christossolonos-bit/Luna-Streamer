"""Persist whether the co-host is on stage (summoned) or dismissed (Luna solo)."""

from __future__ import annotations

import json
import os
from pathlib import Path


def _state_path() -> Path:
    raw = (os.environ.get("LUNA_COHOST_SCENE_STATE_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path(__file__).resolve().parent / "data" / "cohost_scene_state.json").resolve()


def load_cohost_in_scene(*, default: bool = False) -> bool:
    path = _state_path()
    if not path.is_file():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "in_scene" in data:
            return bool(data["in_scene"])
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return default


def save_cohost_in_scene(in_scene: bool) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"in_scene": bool(in_scene)}, indent=0) + "\n",
        encoding="utf-8",
    )


def format_cohost_off_stage_block() -> str:
    """System text when Viktor was dismissed — Luna must not summon him back."""
    from vampire_cohost import cohost_name

    n = cohost_name()
    return (
        f"## {n} is off stage (dismissed)\n"
        f"The streamer sent {n} away with **Dismiss**. Luna is **solo** on screen until the streamer "
        f"presses **Summon** in the dock.\n"
        f"- Do NOT call {n} back, ping them to appear, or write dialogue as if they can hear you.\n"
        f"- Do NOT start banter or invite them on mic.\n"
        f"- You may mention them only if the streamer explicitly asks about them."
    )
