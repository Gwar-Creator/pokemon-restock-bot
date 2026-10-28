"""Lorcana coverage audit must remain read-only and never notify Discord."""
import copy
import unittest

from price_watch_lorcana_shadow import summarize_lorcana_coverage, format_lorcana_coverage


class LorcanaShadowAuditTests(unittest.TestCase):
    def test_game_isolation_and_source_breakdown(self):
        rows = [
            {"game": "LORCANA", "type": "BOOSTER BOX", "source": "coolshop",
             "price": 800, "url": "https://example.invalid/box"},
            {"game": "LORCANA", "type": "BOOSTER PACK", "source": "shop_a",
             "price": 40, "url": ""},
            {"game": "POKÉMON", "type": "BOOSTER BOX", "source": "coolshop",
             "price": 800, "url": "https://example.invalid/pokemon"},
        ]
        before = copy.deepcopy(rows)
        result = summarize_lorcana_coverage(rows)
        self.assertEqual(result["listings"], 2)
        self.assertEqual(result["sources"], 2)
        self.assertEqual(result["missing_urls"], 1)
        self.assertEqual(result["formats"], {"BOOSTER BOX": 1, "BOOSTER PACK": 1})
        self.assertEqual(result["per_source"], {"coolshop": 1, "shop_a": 1})
        self.assertEqual(before, rows)
        self.assertIn("Discord=off", format_lorcana_coverage(result))

    def test_empty_and_incomplete_rows(self):
        rows = [{}, None, {"game": "LORCANA", "source": "", "type": ""}]
        result = summarize_lorcana_coverage(rows)
        self.assertEqual(result["listings"], 1)
        self.assertEqual(result["per_source"], {"unknown": 1})
        self.assertEqual(result["formats"], {"unknown": 1})
        self.assertEqual(result["missing_urls"], 1)
        self.assertIn("missing_links=1", format_lorcana_coverage(result))


if __name__ == "__main__":
    unittest.main()
