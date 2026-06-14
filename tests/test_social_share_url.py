"""Social share URL detection (YouTube + TikTok)."""

from __future__ import annotations

import unittest

from youtube_audio import is_social_share_video_url, looks_like_tiktok_url


class SocialShareUrlTests(unittest.TestCase):
    def test_youtube_urls(self) -> None:
        self.assertTrue(is_social_share_video_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
        self.assertTrue(is_social_share_video_url("https://youtu.be/dQw4w9WgXcQ"))

    def test_tiktok_urls(self) -> None:
        u = "https://www.tiktok.com/@user/video/7123456789012345678"
        self.assertTrue(looks_like_tiktok_url(u))
        self.assertTrue(is_social_share_video_url(u))
        self.assertTrue(is_social_share_video_url("https://vm.tiktok.com/ZMabcdef/"))

    def test_rejects_random(self) -> None:
        self.assertFalse(is_social_share_video_url("https://example.com/not-a-video"))


if __name__ == "__main__":
    unittest.main()
