"""Offline regression tests for read-only Proshop coverage comparison."""

import unittest

from proshop_source_probe import _is_tcg, summarize_probes


class ProshopSourceProbeTests(unittest.TestCase):
    def test_product_title_classifier_rejects_accessories(self):
        self.assertTrue(_is_tcg("Pokemon TCG Mega Lucario ex League Battle Deck"))
        self.assertTrue(_is_tcg("Pokemon TCG Mega Greninja ex Premium Collection"))
        self.assertTrue(_is_tcg("Pokemon ex Box Sylveon 30th Celebration"))
        self.assertTrue(_is_tcg("Pokemon TCG 2-pack Booster"))
        self.assertFalse(_is_tcg("Pokemon TCG Portfolio 9-P"))
        self.assertFalse(_is_tcg("Pokemon TCG Card Sleeves for Booster Packs"))
        self.assertFalse(_is_tcg("Pokemon Trading Card Deck Box"))

    def test_catalogue_observed_union_not_full_inventory(self):
        rows = [
            {"source": "cards-category", "status": 200,
             "raw_unique_ids": 9, "v2_ids": ["100", "101"], "v2_tcg_count": 2},
            {"source": "pokemon-brand", "status": 200,
             "raw_unique_ids": 12, "v2_ids": ["101", "102"], "v2_tcg_count": 2},
            {"source": "pokemon-search", "status": 200,
             "raw_unique_ids": 8, "v2_ids": ["103"], "v2_tcg_count": 1},
            {"source": "booster-search", "status": 429,
             "raw_unique_ids": 0, "v2_ids": [], "v2_tcg_count": 0},
            {"source": "collection-search", "error_type": "Timeout"},
            {"source": "detail-greninja", "status": 200,
             "v2_ids": ["999"], "v2_tcg_count": 1},
        ]
        result = summarize_probes(rows)
        self.assertEqual(result["coverage_status"], "unverified")
        self.assertEqual(result["category_skus"], ["100", "101"])
        self.assertEqual(result["catalogue_union_skus"], ["100", "101", "102", "103"])
        self.assertEqual(result["extra_skus_outside_category"], ["102", "103"])
        self.assertEqual(result["extra_count"], 2)
        self.assertNotIn("999", result["catalogue_union_skus"])
        self.assertEqual(result["source_results"]["collection-search"]["error_type"], "Timeout")

    def test_no_responses_are_unknown_not_proof_of_empty_shop(self):
        result = summarize_probes([
            {"source": "cards-category", "error_type": "ConnectionError"},
            {"source": "pokemon-brand", "status": 403, "v2_ids": []},
        ])
        self.assertEqual(result["category_skus"], [])
        self.assertEqual(result["catalogue_union_skus"], [])
        self.assertEqual(result["coverage_status"], "unverified")


if __name__ == "__main__":
    unittest.main()
