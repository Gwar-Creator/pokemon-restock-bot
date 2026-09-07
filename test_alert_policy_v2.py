import unittest
from datetime import date

from alert_policy import (
    set_status,
    source_tier,
    tier_a_signal_allowed,
    tier_b_signal_allowed,
)


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

    def test_catalogue_new_does_not_bypass_product_filter(self):
        self.assertTrue(
            tier_b_signal_allowed("Journey Together Booster Box", event="NEW")
        )
        self.assertFalse(
            tier_b_signal_allowed("Journey Together Collection Box", event="NEW")
        )
        self.assertFalse(
            tier_b_signal_allowed("Journey Together Booster Pack", event="NEW")
        )
        self.assertTrue(
            tier_b_signal_allowed("Pokemon 151 Booster Pack", event="NEW")
        )
        # ABUNDANT remains strict even when a product is newly discovered.
        self.assertFalse(
            tier_b_signal_allowed("Pitch Black Elite Trainer Box", event="NEW")
        )

    def test_preorder_widens_normal_formats_but_not_loose_packs(self):
        self.assertTrue(
            tier_b_signal_allowed("Future Illustration Collection", event="PREORDER")
        )
        self.assertTrue(
            tier_b_signal_allowed("Future Elite Trainer Box", event="PREORDER")
        )
        self.assertFalse(
            tier_b_signal_allowed("Future Booster Pack", event="PREORDER")
        )
        self.assertTrue(
            tier_b_signal_allowed("Pokemon 151 Booster Pack", event="PREORDER")
        )

    def test_release_date_can_mark_real_new_set(self):
        self.assertTrue(
            tier_b_signal_allowed(
                "Some New Set Booster Pack",
                event="RESTOCK",
                release_date="2026-09-01",
            )
        )

    def test_tier_a_keeps_fast_lane_but_mutes_abundant_noise(self):
        self.assertTrue(
            tier_a_signal_allowed("Journey Together Booster Pack", event="RESTOCK")
        )
        self.assertTrue(
            tier_a_signal_allowed("Pokemon 151 Booster Pack", event="RESTOCK")
        )
        self.assertFalse(
            tier_a_signal_allowed("Pitch Black Booster Pack", event="RESTOCK")
        )
        self.assertFalse(
            tier_a_signal_allowed("Chaos Rising Elite Trainer Box", event="NEW")
        )
        self.assertTrue(
            tier_a_signal_allowed("Pitch Black Booster Bundle", event="RESTOCK")
        )

    def test_non_restock_channels_are_blocked(self):
        self.assertFalse(
            tier_b_signal_allowed("Pokemon 151 Elite Trainer Box", event="PRICE")
        )
        self.assertFalse(
            tier_b_signal_allowed("Pokemon 151 Elite Trainer Box", event="EARLY_RADAR")
        )
        self.assertFalse(
            tier_a_signal_allowed("Pokemon 151 Booster Pack", event="PRICE")
        )


if __name__ == "__main__":
    unittest.main()
