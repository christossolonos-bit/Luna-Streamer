"""Extra Twitch IRC channel config."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from luna_twitch_irc import parse_extra_irc_channels, twitch_initial_channel_logins


class TwitchExtraIrcTests(unittest.TestCase):
    def test_parse_bare_names_default_mention(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"TWITCH_EXTRA_IRC_CHANNELS": "rayen, justrayen_ch"},
            clear=False,
        ):
            os.environ.pop("TWITCH_EXTRA_IRC_REPLY_TRIGGER", None)
            self.assertEqual(
                parse_extra_irc_channels(),
                {"rayen": "mention", "justrayen_ch": "mention"},
            )

    def test_parse_per_channel_trigger(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"TWITCH_EXTRA_IRC_CHANNELS": "rayen:mention,other:all"},
            clear=False,
        ):
            self.assertEqual(
                parse_extra_irc_channels(),
                {"rayen": "mention", "other": "all"},
            )

    def test_initial_channels_primary_first(self) -> None:
        out = twitch_initial_channel_logins("solonaras", {"rayen": "mention"})
        self.assertEqual(out, ["solonaras", "rayen"])


if __name__ == "__main__":
    unittest.main()
