"""Tests for avatar expression detection and TTS viseme / timing helpers.

Run (from repo root):
  python -m unittest discover -s tests -p "test_*.py" -v

Optional Edge TTS network test (monotonic word-boundary times):
  set LUNA_RUN_EDGE_TTS_TESTS=1
  python -m unittest tests.test_luna_expressions_and_visemes.EdgeVisemeIntegrationTests -v
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


class WordToVowelTests(unittest.TestCase):
    """Phonetic-ish vowel pick per word (dominant vowel letter count)."""

    def setUp(self) -> None:
        from luna_tts import _word_to_vowel_viseme

        self._vis = _word_to_vowel_viseme

    def test_no_vowels(self) -> None:
        self.assertEqual(self._vis("rhythm"), "")
        self.assertEqual(self._vis(""), "")

    def test_clear_winner(self) -> None:
        self.assertEqual(self._vis("banana"), "a")
        self.assertEqual(self._vis("hello"), "e")  # e and o both 1; max picks earlier vowel slot
        self.assertEqual(self._vis("see"), "e")
        self.assertEqual(self._vis("moon"), "o")

    def test_strips_non_letters(self) -> None:
        self.assertEqual(self._vis("WOW!"), "o")


class VisemeTimingFormulaTests(unittest.TestCase):
    """Mirror clamp logic for per-word hold_ms (see luna_tts._synthesize_edge_to_mp3)."""

    def setUp(self) -> None:
        from luna_tts import _pick_vowel_from_spectrum

        self._pick = _pick_vowel_from_spectrum

    def test_hold_ms_clamped(self) -> None:
        dur_sec = 0.2
        hold_ms = int(max(70.0, min(260.0, dur_sec * 1000.0 * 0.85)))
        self.assertGreaterEqual(hold_ms, 70)
        self.assertLessEqual(hold_ms, 260)
        # Very long word duration should still cap at 260
        long_hold = int(max(70.0, min(260.0, 2.0 * 1000.0 * 0.85)))
        self.assertEqual(long_hold, 260)

    def test_audio_viseme_spectrum_mapping(self) -> None:
        """High centroid / treble → front vowels; sub-heavy → back rounded."""
        self.assertEqual(self._pick(3000.0, 0.1, 0.2, 0.25, 0.35, 0.5), "i")
        self.assertEqual(self._pick(900.0, 0.5, 0.25, 0.15, 0.05, 0.6), "u")
        self.assertEqual(self._pick(0.0, 0.0, 0.0, 0.0, 0.0, 0.02), "")


class AudioVisemeWavTests(unittest.TestCase):
    """WAV-driven viseme timeline (requires librosa + soundfile)."""

    def test_synthetic_high_pitch_prefers_front_vowel(self) -> None:
        import os
        import struct
        import tempfile
        import wave
        import math
        from pathlib import Path

        from luna_tts import _wav_viseme_timeline_from_audio

        fd, p = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            sr = 24000
            with wave.open(p, "w") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(sr)
                n = int(sr * 0.35)
                frames = b"".join(
                    struct.pack(
                        "<h",
                        int(0.4 * 32767 * math.sin(2 * math.pi * 3000 * t / sr)),
                    )
                    for t in range(n)
                )
                w.writeframes(frames)
            cues = _wav_viseme_timeline_from_audio(Path(p))
            self.assertGreater(len(cues), 0, "expected at least one viseme cue")
            vowels = {c[1] for c in cues if c[1]}
            self.assertTrue(vowels & {"i", "e"}, msg=f"got vowels {vowels!r}")
        finally:
            try:
                os.unlink(p)
            except OSError:
                pass


class AvatarEmotionTests(unittest.TestCase):
    """Face preset from assistant reply text (must match viewer preset ids)."""

    _allowed = frozenset({"happy", "sad", "angry", "surprised", "relaxed"})

    def setUp(self) -> None:
        from twitch_bot import detect_avatar_emotion

        self._detect = detect_avatar_emotion

    def assert_emotion(self, text: str, expected: str) -> None:
        got = self._detect(text)
        self.assertIn(got, self._allowed, msg=f"unexpected emotion {got!r}")
        self.assertEqual(got, expected, msg=f"text={text[:80]!r}")

    def test_happy_phrases(self) -> None:
        self.assert_emotion("Thank you so much - that's amazing!", "happy")
        self.assert_emotion("haha lol that got me", "happy")

    def test_sad_phrases(self) -> None:
        self.assert_emotion("I'm sorry, that's rough.", "sad")
        self.assert_emotion("My sympathies — very unfortunate.", "sad")

    def test_angry_phrases(self) -> None:
        self.assert_emotion("This is not fair and frankly frustrating.", "angry")

    def test_surprised_phrases(self) -> None:
        self.assert_emotion("Wait what - no way! Wow.", "surprised")
        self.assert_emotion("OMG I can't believe that plot twist.", "surprised")

    def test_relaxed_when_flat(self) -> None:
        self.assert_emotion("The API returns JSON. By the way, use GET.", "relaxed")

    def test_star_actions(self) -> None:
        self.assert_emotion("*gasp* really?", "surprised")
        self.assert_emotion("*laugh* nice one", "happy")


@unittest.skipUnless(
    os.environ.get("LUNA_RUN_EDGE_TTS_TESTS", "").strip() == "1",
    "Set LUNA_RUN_EDGE_TTS_TESTS=1 to run Edge TTS word-boundary timing test (network).",
)
class EdgeVisemeIntegrationTests(unittest.TestCase):
    """Requires edge-tts, network, and a valid Edge voice."""

    def test_word_boundary_cues_monotonic_and_mp3_written(self) -> None:
        from luna_tts import _synthesize_edge_to_mp3, get_effective_speaker

        voice = get_effective_speaker()
        fd, tmp = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        path = Path(tmp)
        try:
            cues = _synthesize_edge_to_mp3(
                "Hi there Luna",
                path,
                voice=voice,
                rate=os.environ.get("LUNA_EDGE_RATE", "+0%").strip() or "+0%",
                pitch=os.environ.get("LUNA_EDGE_PITCH", "+0Hz").strip() or "+0Hz",
            )
            self.assertTrue(path.is_file(), "mp3 file should exist")
            self.assertGreater(path.stat().st_size, 500, "mp3 should have body bytes")
            self.assertGreater(len(cues), 0, "expected at least one viseme/rest cue from WordBoundary")

            times = [c[0] for c in cues]
            self.assertEqual(times, sorted(times), "viseme/rest times must be non-decreasing")

            for row in cues:
                self.assertGreaterEqual(row[0], 0.0, msg=f"bad start {row}")
                if row[1]:  # vowel viseme
                    self.assertIn(row[1], "aeiou", msg=f"bad viseme {row}")
                    self.assertGreater(row[2], 0.0)
                    self.assertGreaterEqual(row[3], 40)
        finally:
            path.unlink(missing_ok=True)


class ViewerAvatarIdTests(unittest.TestCase):
    def test_partner_only_himari(self) -> None:
        from twitch_bot import viewer_avatar_id

        self.assertEqual(viewer_avatar_id("himari"), "himari")

    def test_partner_only_viktor(self) -> None:
        from twitch_bot import viewer_avatar_id

        self.assertEqual(viewer_avatar_id("viktor"), "cohost")

    def test_explicit_luna_speaker(self) -> None:
        from twitch_bot import viewer_avatar_id

        self.assertEqual(viewer_avatar_id("himari", speaker="luna"), "luna")
        self.assertEqual(viewer_avatar_id("viktor", speaker="luna"), "luna")

    def test_banter_speakers(self) -> None:
        from twitch_bot import viewer_avatar_id

        self.assertEqual(viewer_avatar_id("himari", speaker="himari"), "himari")
        self.assertEqual(viewer_avatar_id("viktor", speaker="cohost"), "cohost")


if __name__ == "__main__":
    unittest.main()
