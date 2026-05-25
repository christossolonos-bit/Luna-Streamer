"""Discord per-guild chat allowlist parsing."""

import os
import unittest

from luna_discord_bot import (
    _discord_cast_triggered,
    _discord_chat_trigger_mode,
    _discord_guild_chat_channel_rules,
    _discord_guild_chat_triggers,
)


class DiscordGuildChatRulesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_channels = os.environ.get("LUNA_DISCORD_GUILD_CHAT_CHANNELS")
        self._prev_triggers = os.environ.get("LUNA_DISCORD_GUILD_CHAT_TRIGGERS")
        self._prev_global = os.environ.get("LUNA_DISCORD_CHAT_CHANNEL_IDS")

    def tearDown(self) -> None:
        for key, val in (
            ("LUNA_DISCORD_GUILD_CHAT_CHANNELS", self._prev_channels),
            ("LUNA_DISCORD_GUILD_CHAT_TRIGGERS", self._prev_triggers),
            ("LUNA_DISCORD_CHAT_CHANNEL_IDS", self._prev_global),
        ):
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val

    def test_guild_star_means_all_channels(self) -> None:
        os.environ["LUNA_DISCORD_GUILD_CHAT_CHANNELS"] = "1465362923428778110:*"
        rules = _discord_guild_chat_channel_rules()
        self.assertIn(1465362923428778110, rules)
        self.assertIsNone(rules[1465362923428778110])

    def test_per_guild_trigger_all(self) -> None:
        os.environ["LUNA_DISCORD_GUILD_CHAT_TRIGGERS"] = "1465362923428778110:all"
        os.environ["LUNA_DISCORD_CHAT_TRIGGER"] = "mention"
        triggers = _discord_guild_chat_triggers()
        self.assertEqual(triggers[1465362923428778110], "all")

        class _Guild:
            id = 1465362923428778110

        self.assertEqual(_discord_chat_trigger_mode(_Guild()), "all")


    def test_cast_triggered_by_viktor_name(self) -> None:
        os.environ["LUNA_COHOST_BANTER"] = "1"
        os.environ["LUNA_COHOST_CHAT_PERSONAS"] = "1"
        self.assertTrue(_discord_cast_triggered("hey Viktor what's up", None, None))

    def test_cast_triggered_by_himari_name(self) -> None:
        os.environ["LUNA_HIMARI_ENABLED"] = "1"
        self.assertTrue(_discord_cast_triggered("Himari are you there?", None, None))


if __name__ == "__main__":
    unittest.main()
