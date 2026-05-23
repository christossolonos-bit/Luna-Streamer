"""Persist cast on stage (summoned/dismissed). Delegates to luna_cast."""

from __future__ import annotations

from luna_cast import (
    format_partner_off_stage_block,
    load_cast_scene,
    load_cohost_in_scene,
    save_cast_scene,
    save_cohost_in_scene,
)


def format_cohost_off_stage_block() -> str:
    """System text for co-hosts dismissed — Luna must not summon them back."""
    from himari_cohost import himari_enabled
    from vampire_cohost import cohost_enabled

    scene = load_cast_scene()
    parts: list[str] = []
    if cohost_enabled() and not scene.viktor_in_scene:
        parts.append(format_partner_off_stage_block("viktor"))
    if himari_enabled() and not scene.himari_in_scene:
        parts.append(format_partner_off_stage_block("himari"))
    return "\n\n".join(parts) if parts else ""
