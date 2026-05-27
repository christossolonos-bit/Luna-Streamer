"""Website canned replies are defined in TS; this tests the Python export script if added later."""

import unittest


class WebsiteCannedPlaceholderTests(unittest.TestCase):
    def test_canned_module_exists_in_repo(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        ts = root / "website" / "src" / "cannedResponses.ts"
        pick = root / "website" / "src" / "pickCannedReply.ts"
        self.assertTrue(ts.is_file(), "cannedResponses.ts missing")
        self.assertTrue(pick.is_file(), "pickCannedReply.ts missing")
        text = ts.read_text(encoding="utf-8")
        self.assertIn("luna:", text)
        self.assertIn("himari:", text)
        self.assertIn("viktor:", text)
        self.assertGreaterEqual(text.count('"'), 200)


if __name__ == "__main__":
    unittest.main()
