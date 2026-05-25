"""Discord engagement state + daily post scheduling."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_engagement_guild_ids_default_welcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from luna_discord_engagement import engagement_guild_ids

    monkeypatch.delenv("LUNA_DISCORD_ENGAGEMENT_GUILD_IDS", raising=False)
    monkeypatch.setenv("LUNA_DISCORD_WELCOME_GUILD_ID", "1465362923428778110")
    assert 1465362923428778110 in engagement_guild_ids()


def test_should_not_post_twice_same_day() -> None:
    from luna_discord_engagement import _local_today, should_run_daily_post_now

    bucket: dict = {"daily_posts": {"last_date": _local_today()}}
    assert should_run_daily_post_now(bucket) is False


def test_record_message_updates_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from luna_discord_engagement import load_all_state, record_message

    state_path = tmp_path / "discord_engagement_state.json"
    monkeypatch.setenv("LUNA_DISCORD_ENGAGEMENT_STATE_PATH", str(state_path))
    monkeypatch.setenv("LUNA_DISCORD_ENGAGEMENT_GUILD_IDS", "1465362923428778110")

    monkeypatch.setattr(
        "luna_discord_community.community_channel_ids_for_guild",
        lambda _gid: frozenset({999}),
    )

    async def _run() -> None:
        await record_message(
            1465362923428778110,
            channel_id=999,
            channel_name="community-chat",
            author_id=1,
            content="Hello Wolf Den!",
            is_bot=False,
        )

    asyncio.run(_run())
    data = load_all_state()
    bucket = data["1465362923428778110"]
    assert bucket["today"]["messages_total"] == 1
    assert "Hello Wolf Den!" in bucket["today"]["samples"]


def test_weekday_theme_count() -> None:
    from luna_discord_engagement import DAILY_THEMES

    assert len(DAILY_THEMES) == 7
