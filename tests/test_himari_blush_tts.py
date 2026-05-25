"""Himari blush kaomoji must not reach TTS."""

import unittest

from himari_cohost import sanitize_himari_speech_text, strip_himari_blush_kaomoji
from luna_tts import _reply_text_before_tts_clean


class HimariBlushTtsTests(unittest.TestCase):
    def test_strip_common_blush_faces(self) -> None:
        self.assertEqual(
            strip_himari_blush_kaomoji("sorry >///< that was loud"),
            "sorry that was loud",
        )
        self.assertEqual(
            strip_himari_blush_kaomoji("um >\\< hi"),
            "um hi",
        )
        self.assertEqual(
            strip_himari_blush_kaomoji("wait >/< no"),
            "wait no",
        )

    def test_sanitize_includes_blush_strip(self) -> None:
        self.assertEqual(
            sanitize_himari_speech_text("I mean >///< the boss is scary"),
            "I mean the boss is scary",
        )

    def test_himari_voice_preprocess(self) -> None:
        from himari_cohost import himari_edge_voice

        out = _reply_text_before_tts_clean(
            "okay >///< sure",
            himari_edge_voice(),
        )
        self.assertNotIn(">", out)
        self.assertIn("okay", out)


if __name__ == "__main__":
    unittest.main()
