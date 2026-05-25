"""Discord file TTS must chunk long Edge replies (single request truncates)."""

import unittest
from unittest.mock import patch

from luna_tts import (
    _split_text_for_discord_files,
    _split_tts_chunks,
    _synthesize_edge_to_mp3_file,
)


class DiscordTtsChunkTests(unittest.TestCase):
    def test_split_for_discord_files_covers_all_text(self) -> None:
        text = ("First sentence here. " * 20 + "Second half continues. " * 20).strip()
        parts = _split_text_for_discord_files(text)
        self.assertGreaterEqual(len(parts), 2)
        joined = " ".join(parts)
        self.assertEqual(joined.replace("  ", " "), text.replace("  ", " "))
        for part in parts:
            self.assertLessEqual(len(part), 220)

    def test_long_lyric_style_splits_only_in_multi_file_mode(self) -> None:
        from luna_tts import discord_tts_single_file

        text = ("Verse line one here.\n" * 8 + "Chorus sing loud.\n" * 6) * 4
        if not discord_tts_single_file():
            parts = _split_text_for_discord_files(text)
            self.assertGreaterEqual(len(parts), 3)

    def test_long_text_splits_into_multiple_chunks(self) -> None:
        text = "Hello. " * 120
        chunks = _split_tts_chunks(text, 380)
        self.assertGreater(len(chunks), 1)

    @patch("luna_tts._wav_to_mp3")
    @patch("luna_tts._concat_audio_with_ffmpeg")
    @patch("luna_tts._mp3_to_wav")
    @patch("luna_tts._synthesize_edge_to_mp3")
    def test_edge_file_export_calls_synth_per_chunk(
        self,
        mock_edge,
        _mock_mp3_wav,
        _mock_concat,
        _mock_wav_mp3,
    ) -> None:
        import tempfile
        from pathlib import Path

        text = "Word. " * 200
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            out = Path(f.name)
        try:
            _synthesize_edge_to_mp3_file(
                text,
                out,
                voice="en-US-AvaNeural",
                rate="+0%",
                pitch="+0Hz",
            )
        finally:
            try:
                out.unlink(missing_ok=True)
            except OSError:
                pass
        self.assertGreater(mock_edge.call_count, 1)


if __name__ == "__main__":
    unittest.main()
