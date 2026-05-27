"""Viewer TTS uses the same stitched single clip as Discord (no Edge truncation)."""

import unittest
from unittest.mock import patch

from luna_tts import synthesize_playback_bundle


class ViewerTtsBundleTests(unittest.TestCase):
    @patch("luna_tts.tts_enabled", return_value=True)
    @patch("luna_tts._resolve_viseme_timeline", return_value=[])
    @patch("luna_tts._wav_duration_sec", return_value=12.5)
    @patch("luna_tts._mp3_to_wav")
    @patch("luna_tts._synthesize_discord_part_to_file")
    def test_playback_bundle_uses_discord_stitch_path(
        self,
        mock_part,
        _mock_mp3_wav,
        _mock_dur,
        _mock_visemes,
        _mock_enabled,
    ) -> None:
        import tempfile
        from pathlib import Path

        fd, tmp = tempfile.mkstemp(suffix=".mp3")
        import os

        os.close(fd)
        mp3 = Path(tmp)
        mp3.write_bytes(b"\xff\xfb" + b"\x00" * 64)
        mock_part.return_value = mp3
        try:
            bundle = synthesize_playback_bundle("Hello. " * 200)
        finally:
            try:
                mp3.unlink(missing_ok=True)
            except OSError:
                pass
        self.assertIsNotNone(bundle)
        assert bundle is not None
        self.assertEqual(bundle.mime, "audio/mpeg")
        mock_part.assert_called_once()
        call_text = mock_part.call_args[0][0]
        self.assertGreater(len(call_text), 400)

    @patch("luna_tts.tts_enabled", return_value=True)
    @patch("luna_tts._viewer_tts_max_chars", return_value=0)
    @patch("luna_tts._clean_text_for_tts")
    @patch("luna_tts._synthesize_discord_part_to_file", return_value=None)
    def test_unlimited_chars_when_viewer_max_zero(
        self,
        _mock_part,
        mock_clean,
        _mock_max,
        _mock_enabled,
    ) -> None:
        mock_clean.return_value = ("x" * 3000, "relaxed")
        synthesize_playback_bundle("ignored")
        mock_clean.assert_called_once()
        self.assertEqual(mock_clean.call_args.kwargs.get("max_chars"), 0)


if __name__ == "__main__":
    unittest.main()
