"""Creator panel/voice routes to on-stage co-host when talk target is Luna but only one partner is up."""

import os
import unittest

from luna_cast import CastScene, resolve_creator_reply_partner


class CreatorCastRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["LUNA_COHOST_BANTER"] = "1"
        os.environ["LUNA_HIMARI_ENABLED"] = "1"
    def test_single_partner_on_stage_without_explicit_target(self) -> None:
        scene = CastScene(viktor_in_scene=True, himari_in_scene=False)
        pick = resolve_creator_reply_partner(
            "hey what do you think",
            scene,
            explicit_target="",
        )
        self.assertEqual(pick, "viktor")

    def test_explicit_luna_with_name_in_message(self) -> None:
        scene = CastScene(viktor_in_scene=True, himari_in_scene=False)
        pick = resolve_creator_reply_partner(
            "Luna can you ask Viktor something",
            scene,
            explicit_target="luna",
        )
        self.assertEqual(pick, "luna")

    def test_explicit_himari_beats_single_on_stage(self) -> None:
        scene = CastScene(viktor_in_scene=True, himari_in_scene=False)
        pick = resolve_creator_reply_partner(
            "hello",
            scene,
            explicit_target="himari",
        )
        self.assertEqual(pick, "himari")


if __name__ == "__main__":
    unittest.main()
