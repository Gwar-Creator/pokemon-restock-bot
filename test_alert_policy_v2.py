import unittest
from datetime import date

from alert_policy import (
    backup_retail_signal_allowed,
    set_status,
    source_tier,
    tier_a_signal_allowed,
    tier_b_signal_allowed,
)


class RestockV2PolicyTests(unittest.TestCase):
    def test_source_tiers(self):
        self.assertEqual(source_tier("coolshop"), "A")
        self.assertEqual(source_tier("proshop"), "A")
        self.assertEqual(source_tier("boozt"), "A")
        self.assertEqual(source_tier("magasin"), "A")
        self.assertEqual(source_tier("indeks_retail"), "B")
        self.assertEqual(source_tier("matraws"), "SPECIALTY")
        self.assertEqual(source_tier("softgunshoppen"), "SPECIALTY")
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

    def test_specialty_gate_is_filtered_open_by_default(self):
        for event in ("NEW", "PREORDER", "RESTOCK"):
            self.assertTrue(
                tier_b_signal_allowed("Pokemon 151 Booster Bundle", event=event)
            )
            self.assertTrue(
                tier_b_signal_allowed("Journey Together Booster Box", event=event)
            )

        self.assertFalse(
            tier_b_signal_allowed("Journey Together Elite Trainer Box", event="RESTOCK")
        )

    def test_explicitly_muted_specialty_sources_stay_data_only(self):
        for source_key in ("matraws", "kelz0r", "rogerz"):
            self.assertFalse(
                tier_b_signal_allowed(
                    "Pokemon 151 Booster Bundle",
                    event="RESTOCK",
                    source_key=source_key,
                )
            )
            self.assertFalse(
                tier_b_signal_allowed(
                    "Journey Together Booster Box",
                    event="RESTOCK",
                    source_key=source_key,
                )
            )

    def test_backup_retail_normal_is_strict(self):
        self.assertTrue(
            backup_retail_signal_allowed("Journey Together Booster Box")
        )
        self.assertFalse(
            backup_retail_signal_allowed("Journey Together Elite Trainer Box")
        )
        self.assertFalse(
            backup_retail_signal_allowed("Journey Together Booster Pack")
        )

    def test_backup_retail_watch_sets_are_broader(self):
        self.assertTrue(
            backup_retail_signal_allowed("Pokemon 151 Elite Trainer Box")
        )
        self.assertTrue(
            backup_retail_signal_allowed("Prismatic Evolutions Booster Pack")
        )
        self.assertTrue(
            backup_retail_signal_allowed("First Partner Illustration Collection")
        )

    def test_backup_retail_abundant_sets_stay_quiet_for_low_signal_formats(self):
        self.assertFalse(
            backup_retail_signal_allowed("Pitch Black Elite Trainer Box")
        )
        self.assertFalse(
            backup_retail_signal_allowed("Chaos Rising Booster Pack")
        )
        self.assertTrue(
            backup_retail_signal_allowed("Pitch Black Booster Bundle")
        )
        self.assertTrue(
            backup_retail_signal_allowed("Chaos Rising Booster Box")
        )

    def test_backup_catalogue_new_does_not_bypass_product_filter(self):
        self.assertTrue(
            backup_retail_signal_allowed("Journey Together Booster Box", event="NEW")
        )
        self.assertFalse(
            backup_retail_signal_allowed("Journey Together Collection Box", event="NEW")
        )
        self.assertFalse(
            backup_retail_signal_allowed("Journey Together Booster Pack", event="NEW")
        )
        self.assertTrue(
            backup_retail_signal_allowed("Pokemon 151 Booster Pack", event="NEW")
        )
        self.assertFalse(
            backup_retail_signal_allowed("Pitch Black Elite Trainer Box", event="NEW")
        )

    def test_backup_preorder_widens_normal_formats_but_not_loose_packs(self):
        self.assertTrue(
            backup_retail_signal_allowed("Future Illustration Collection", event="PREORDER")
        )
        self.assertTrue(
            backup_retail_signal_allowed("Future Elite Trainer Box", event="PREORDER")
        )
        self.assertFalse(
            backup_retail_signal_allowed("Future Booster Pack", event="PREORDER")
        )
        self.assertTrue(
            backup_retail_signal_allowed("Pokemon 151 Booster Pack", event="PREORDER")
        )

    def test_release_date_can_mark_real_new_set_for_backup_retail(self):
        self.assertTrue(
            backup_retail_signal_allowed(
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
            backup_retail_signal_allowed("Pokemon 151 Elite Trainer Box", event="PRICE")
        )
        self.assertFalse(
            backup_retail_signal_allowed("Pokemon 151 Elite Trainer Box", event="EARLY_RADAR")
        )
        self.assertFalse(
            tier_a_signal_allowed("Pokemon 151 Booster Pack", event="PRICE")
        )


if __name__ == "__main__":
    unittest.main()
