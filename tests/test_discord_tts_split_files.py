"""Discord TTS: default single MP3; optional multi-file split."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch


class DiscordTtsSplitFilesTests(unittest.TestCase):
    @patch("luna_tts.tts_enabled", return_value=True)
    @patch("luna_tts._backend", return_value="edge")
    @patch("luna_tts._synthesize_discord_part_to_file")
    @patch("luna_tts.discord_tts_single_file", return_value=True)
    def test_long_reply_default_one_mp3(
        self,
        _single: unittest.mock.MagicMock,
        mock_part: unittest.mock.MagicMock,
        _mock_backend: unittest.mock.MagicMock,
        _mock_enabled: unittest.mock.MagicMock,
    ) -> None:
        from luna_tts import synthesize_discord_reply_files

        mock_part.return_value = Path("/tmp/luna_discord_one.mp3")
        paths = synthesize_discord_reply_files("Hello friend. " * 80)
        self.assertEqual(len(paths), 1)
        self.assertEqual(mock_part.call_count, 1)

    @patch("luna_tts.tts_enabled", return_value=True)
    @patch("luna_tts._backend", return_value="edge")
    @patch("luna_tts._synthesize_discord_part_to_file")
    @patch("luna_tts.discord_tts_single_file", return_value=False)
    def test_split_mode_returns_multiple(
        self,
        _single: unittest.mock.MagicMock,
        mock_part: unittest.mock.MagicMock,
        _mock_backend: unittest.mock.MagicMock,
        _mock_enabled: unittest.mock.MagicMock,
    ) -> None:
        from luna_tts import synthesize_discord_reply_files

        mock_part.side_effect = lambda *a, **k: Path("/tmp/luna_discord_part.mp3")
        paths = synthesize_discord_reply_files("Hello friend. " * 80)
        self.assertGreaterEqual(len(paths), 2)
        self.assertGreaterEqual(mock_part.call_count, 2)

    @patch("luna_tts.tts_enabled", return_value=True)
    @patch("luna_tts._backend", return_value="edge")
    @patch("luna_tts._synthesize_discord_part_to_file")
    def test_short_reply_returns_one_path(
        self,
        mock_part: unittest.mock.MagicMock,
        _mock_backend: unittest.mock.MagicMock,
        _mock_enabled: unittest.mock.MagicMock,
    ) -> None:
        from luna_tts import synthesize_discord_reply_files

        mock_part.return_value = Path("/tmp/luna_discord_one.mp3")
        paths = synthesize_discord_reply_files("Short answer.")
        self.assertEqual(len(paths), 1)
        self.assertEqual(mock_part.call_count, 1)


class DiscordTtsNoLimitTests(unittest.TestCase):
    def test_discord_max_chars_zero_means_unlimited(self) -> None:
        from luna_tts import _clean_text_for_tts, _discord_tts_max_chars

        self.assertEqual(_discord_tts_max_chars(), 0)
        long = "Word. " * 800
        clean, _ = _clean_text_for_tts(long, max_chars=0)
        self.assertGreater(len(clean), 3000)


if __name__ == "__main__":
    unittest.main()
