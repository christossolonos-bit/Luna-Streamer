"""Social share readiness (no network)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from social_playwright_share import (
    interactive_login_prefers_user_chrome,
    social_playwright_configured,
    social_playwright_ready,
    social_share_setup_hint,
)


class SocialPlaywrightReadyTests(unittest.TestCase):
    def test_configured_without_session_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            x_path = Path(tmp) / "x.json"
            with mock.patch.dict(
                os.environ,
                {
                    "LUNA_SOCIAL_PLAYWRIGHT": "1",
                    "LUNA_SOCIAL_X_STORAGE_STATE": str(x_path),
                },
                clear=False,
            ):
                os.environ.pop("LUNA_SOCIAL_FACEBOOK_STORAGE_STATE", None)
                self.assertTrue(social_playwright_configured())
                self.assertFalse(social_playwright_ready())
                self.assertIn("X", social_share_setup_hint())

    def test_ready_when_session_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fb_path = Path(tmp) / "fb.json"
            fb_path.write_text("{}", encoding="utf-8")
            with mock.patch.dict(
                os.environ,
                {
                    "LUNA_SOCIAL_PLAYWRIGHT": "1",
                    "LUNA_SOCIAL_FACEBOOK_STORAGE_STATE": str(fb_path),
                },
                clear=False,
            ):
                os.environ.pop("LUNA_SOCIAL_X_STORAGE_STATE", None)
                self.assertTrue(social_playwright_ready())

    def test_setup_hint_mentions_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            x_path = Path(tmp) / "x.json"
            with mock.patch.dict(
                os.environ,
                {
                    "LUNA_SOCIAL_PLAYWRIGHT": "1",
                    "LUNA_SOCIAL_X_STORAGE_STATE": str(x_path),
                },
                clear=False,
            ):
                os.environ.pop("LUNA_SOCIAL_FACEBOOK_STORAGE_STATE", None)
                self.assertIn("Export", social_share_setup_hint())

    def test_tiktok_prefers_user_chrome_by_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            for key in (
                "LUNA_SOCIAL_INTERACTIVE_CDP_URL",
                "LUNA_SOCIAL_INTERACTIVE_AUTO_CDP",
                "LUNA_SOCIAL_INTERACTIVE_PLAYWRIGHT_LAUNCH",
            ):
                os.environ.pop(key, None)
            self.assertTrue(interactive_login_prefers_user_chrome("tiktok"))
            self.assertTrue(interactive_login_prefers_user_chrome("x"))
            self.assertFalse(interactive_login_prefers_user_chrome("facebook"))
            self.assertFalse(interactive_login_prefers_user_chrome("youtube"))


if __name__ == "__main__":
    unittest.main()
