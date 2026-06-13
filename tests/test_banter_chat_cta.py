"""Banter chat engagement CTA helpers."""

from __future__ import annotations

import unittest

from luna_cast import CastScene
from luna_cohost_banter import (
    choose_banter_cta_speaker,
    line_looks_like_chat_cta,
)


class BanterChatCtaTests(unittest.TestCase):
    def test_line_looks_like_chat_cta(self) -> None:
        self.assertTrue(line_looks_like_chat_cta("Chat, is anyone alive out there?"))
        self.assertFalse(line_looks_like_chat_cta("Viktor, your tie is ridiculous."))

    def test_choose_speaker_luna_on_stage(self) -> None:
        scene = CastScene(viktor_in_scene=True, himari_in_scene=True, luna_in_scene=True)
        self.assertEqual(
            choose_banter_cta_speaker(scene, [("viktor", "hm")]),
            "luna",
        )

    def test_choose_speaker_cohost_duo(self) -> None:
        scene = CastScene(viktor_in_scene=True, himari_in_scene=True, luna_in_scene=False)
        self.assertEqual(
            choose_banter_cta_speaker(scene, [("himari", "um")]),
            "himari",
        )


if __name__ == "__main__":
    unittest.main()
