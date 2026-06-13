"""Private Viktor duty DM config (no network)."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from luna_discord_private_duty_dm import (
    _archive_filename_stem,
    _clean_generated_line,
    _save_duty_reminder_archive,
    _too_similar,
    private_duty_dm_archive_dir,
    private_duty_dm_archive_enabled,
    private_duty_dm_discord_tts_enabled,
    private_duty_dm_enabled,
    private_duty_dm_interval_sec,
    private_duty_dm_max_retries,
    private_duty_dm_owner_ids,
)


class PrivateDutyDmTests(unittest.TestCase):
    def test_disabled_by_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LUNA_DISCORD_PRIVATE_DUTY_DM", None)
            self.assertFalse(private_duty_dm_enabled())

    def test_discord_tts_follows_luna_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LUNA_DISCORD_PRIVATE_DUTY_DM_TTS", None)
            os.environ.pop("LUNA_DISCORD_TTS", None)
            self.assertTrue(private_duty_dm_discord_tts_enabled())
        with mock.patch.dict(os.environ, {"LUNA_DISCORD_TTS": "0"}, clear=False):
            os.environ.pop("LUNA_DISCORD_PRIVATE_DUTY_DM_TTS", None)
            self.assertFalse(private_duty_dm_discord_tts_enabled())
        with mock.patch.dict(
            os.environ,
            {"LUNA_DISCORD_TTS": "0", "LUNA_DISCORD_PRIVATE_DUTY_DM_TTS": "1"},
            clear=False,
        ):
            self.assertTrue(private_duty_dm_discord_tts_enabled())

    def test_owner_ids_from_env(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"LUNA_OWNER_DISCORD_ID": "111,222"},
            clear=False,
        ):
            self.assertEqual(private_duty_dm_owner_ids(), frozenset({111, 222}))

    def test_owner_ids_discord_dm_owner_fallback(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"DISCORD_DM_OWNER_ID": "333"},
            clear=False,
        ):
            os.environ.pop("LUNA_OWNER_DISCORD_ID", None)
            os.environ.pop("LUNA_DISCORD_PRIVATE_DUTY_DM_USER_ID", None)
            self.assertEqual(private_duty_dm_owner_ids(), frozenset({333}))

    def test_interval_bounds(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"LUNA_DISCORD_PRIVATE_DUTY_DM_INTERVAL_SEC": "99999"},
            clear=False,
        ):
            self.assertEqual(private_duty_dm_interval_sec(), 86_400.0)

    def test_max_retries(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"LUNA_DISCORD_PRIVATE_DUTY_DM_RETRIES": "4"},
            clear=False,
        ):
            self.assertEqual(private_duty_dm_max_retries(), 4)

    def test_clean_strips_speaker_prefix(self) -> None:
        self.assertTrue(
            _clean_generated_line("Viktor: Honor is a habit, not a mood.").startswith("Honor")
        )

    def test_too_similar(self) -> None:
        a = "discipline is choosing the harder right"
        self.assertTrue(_too_similar(a, [a]))

    def test_archive_dir_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LUNA_DISCORD_PRIVATE_DUTY_DM_ARCHIVE_DIR", None)
            path = private_duty_dm_archive_dir()
            self.assertEqual(path.name, "viktor 's wisdom for men")

    def test_archive_filename_stem(self) -> None:
        stem = _archive_filename_stem(when=1_700_000_000.0)
        self.assertTrue(stem.startswith("viktor-wisdom_"))

    def test_save_archive_copies_mp3_and_txt(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.mp3"
            src.write_bytes(b"fake-mp3")
            archive = Path(tmp) / "archive"
            with mock.patch.dict(
                os.environ,
                {"LUNA_DISCORD_PRIVATE_DUTY_DM_ARCHIVE_DIR": str(archive)},
                clear=False,
            ):
                saved = _save_duty_reminder_archive(
                    "Honor is a habit.",
                    [src],
                    when=1_700_000_000.0,
                )
            mp3s = [p for p in saved if p.suffix == ".mp3"]
            txts = [p for p in saved if p.suffix == ".txt"]
            self.assertEqual(len(mp3s), 1)
            self.assertEqual(len(txts), 1)
            self.assertEqual(mp3s[0].read_bytes(), b"fake-mp3")
            self.assertIn("Honor is a habit.", txts[0].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
