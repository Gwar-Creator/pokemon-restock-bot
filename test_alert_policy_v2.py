import unittest
from datetime import date

from alert_policy import set_status, source_tier, tier_b_signal_allowed


class RestockV2PolicyTests(unittest.TestCase):
    def test_source_tiers(self):
        self.assertEqual(source_tier("coolshop"), "A")
        self.assertEqual(source_tier("proshop"), "A")
        self.assertEqual(source_tier("matraws"), "B")
        self.assertEqual(source_tier("zzgames"), "RETIRED")

    def test_set_status(self):
        self.assertEqual(set_status("Pokemon 151 Elite Trainer Box"), "WATCH")
        self.assertEqual(set_status("Chaos Rising Elite Trainer Box"), "ABUNDANT")
        self.assertEqual(
            set_status(
                "Some New Set Elite Trainer Box",
                release_date="2026-09-01",
                today=date(2026, 9, 6),
            ),
            "NEW",
        )
        self.assertEqual(set_status("Journey Together Elite Trainer Box"), "NORMAL")

    def test_tier_b_normal_is_strict(self):
        self.assertTrue(tier_b_signal_allowed("Journey Together Booster Box"))
        self.assertFalse(tier_b_signal_allowed("Journey Together Elite Trainer Box"))
        self.assertFalse(tier_b_signal_allowed("Journey Together Booster Pack"))

    def test_watch_sets_are_broader(self):
        self.assertTrue(tier_b_signal_allowed("Pokemon 151 Elite Trainer Box"))
        self.assertTrue(tier_b_signal_allowed("Prismatic Evolutions Booster Pack"))
        self.assertTrue(tier_b_signal_allowed("First Partner Illustration Collection"))

    def test_abundant_sets_stay_quiet_for_low_signal_formats(self):
        self.assertFalse(tier_b_signal_allowed("Pitch Black Elite Trainer Box"))
        self.assertFalse(tier_b_signal_allowed("Chaos Rising Booster Pack"))
        self.assertTrue(tier_b_signal_allowed("Pitch Black Booster Bundle"))
        self.assertTrue(tier_b_signal_allowed("Chaos Rising Booster Box"))

    def test_preorder_and_non_restock_channels(self):
        self.assertTrue(
            tier_b_signal_allowed("Future Collection Box", event="PREORDER")
        )
        self.assertFalse(
            tier_b_signal_allowed("Pokemon 151 Elite Trainer Box", event="PRICE")
        )
        self.assertFalse(
            tier_b_signal_allowed("Pokemon 151 Elite Trainer Box", event="EARLY_RADAR")
        )


if __name__ == "__main__":
    unittest.main()
