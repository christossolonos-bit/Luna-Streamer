"""Discord community channel layout helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_guild_state_persona_and_fan_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from luna_discord_community import (
        GuildCommunityState,
        is_fan_gallery_channel,
        persona_for_channel_id,
        save_all_states,
    )

    state_path = tmp_path / "discord_community_channels.json"
    monkeypatch.setenv("LUNA_DISCORD_COMMUNITY_STATE_PATH", str(state_path))

    gid = 1465362923428778110
    save_all_states(
        {
            str(gid): {
                "categories": {"talk-to-the-cast": 111},
                "channels": {
                    "luna-chat": {"id": 1001, "persona": "luna"},
                    "viktor-chat": {"id": 1002, "persona": "viktor"},
                    "fan-images": {"id": 2001, "fan_gallery": True},
                },
            }
        }
    )

    assert persona_for_channel_id(gid, 1001) == "luna"
    assert persona_for_channel_id(gid, 1002) == "viktor"
    assert persona_for_channel_id(gid, 9999) is None
    assert is_fan_gallery_channel(gid, 2001) is True
    assert is_fan_gallery_channel(gid, 1001) is False

    st = GuildCommunityState(guild_id=gid)
    st.channels = {
        "fan-videos": {"id": 2002, "fan_gallery": True},
    }
    assert st.is_fan_channel(2002) is True


def test_default_layout_includes_luna_and_respects_cohost_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from luna_discord_community import default_community_layout

    monkeypatch.setenv("LUNA_COHOST_BANTER", "0")
    monkeypatch.setenv("LUNA_HIMARI_ENABLED", "0")
    layout = default_community_layout()
    names: list[str] = []
    for cat in layout:
        for ch in cat.channels:
            names.append(ch.name)
    assert "luna-chat" in names
    assert "viktor-chat" not in names
    assert "himari-chat" not in names
    assert "fan-images" in names
    assert "fan-videos" in names


def test_community_auto_guild_ids_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from luna_discord_community import community_auto_setup_guild_ids

    monkeypatch.delenv("LUNA_DISCORD_COMMUNITY_GUILD_IDS", raising=False)
    monkeypatch.setenv("LUNA_DISCORD_WELCOME_GUILD_ID", "1465362923428778110")
    assert 1465362923428778110 in community_auto_setup_guild_ids()
