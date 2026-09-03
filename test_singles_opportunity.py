import unittest

from personal import singles_opportunity as so

PROFILE = {
    "eur_to_dkk": 7.46,
    "default_target_dkk": 75,
    "priority_pokemon": ["Mew", "Snorlax", "Pikachu"],
    "secondary_pokemon": ["Rayquaza"],
    "wishlist_ids": [],
    "manual_priority_ids": [],
    "owned_ids": [],
    "ignore_ids": [],
    "target_overrides_dkk": {},
}


def card(card_id="1", name="Mew ex [Restart]", trend=6, avg1=6, avg7=7, avg30=8, low=2):
    return {
        "game": "POKÉMON",
        "id": card_id,
        "name": name,
        "set": "Test Set",
        "variant": "Normal",
        "trend": trend,
        "avg1": avg1,
        "avg7": avg7,
        "avg30": avg30,
        "low": low,
    }


class SinglesOpportunityTests(unittest.TestCase):
    def test_low_has_zero_effect_on_score(self):
        a = so.evaluate_card(card(low=1), PROFILE)
        b = so.evaluate_card(card(low=999), PROFILE)
        self.assertEqual(a["score"], b["score"])
        self.assertEqual(a["signal"], b["signal"])

    def test_priority_card_with_strong_market_dip_can_be_review(self):
        row = so.evaluate_card(card(), PROFILE)
        self.assertEqual(row["signal"], "REVIEW")
        self.assertEqual(row["market_band"], "CORE")
        self.assertIn("priority Pokémon", row["reasons"])

    def test_manual_budget_shapes_actionability_but_is_not_purchase_price(self):
        base = so.evaluate_card(card(trend=6, avg1=6, avg7=7, avg30=8), PROFILE)
        tiny_budget = {**PROFILE, "default_target_dkk": 10}
        changed = so.evaluate_card(card(trend=6, avg1=6, avg7=7, avg30=8), tiny_budget)
        self.assertGreater(base["score"], changed["score"])
        self.assertEqual(base["signal"], "REVIEW")
        self.assertEqual(changed["signal"], "WATCH")
        self.assertEqual(base["market_band"], "CORE")
        self.assertEqual(changed["market_band"], "HIGH-END")
        self.assertEqual(base["diagnostic_low_eur"], changed["diagnostic_low_eur"])

    def test_target_override_can_make_a_specific_card_actionable(self):
        expensive = card(trend=30, avg1=30, avg7=35, avg30=40)
        base = so.evaluate_card(expensive, PROFILE)
        override = {**PROFILE, "target_overrides_dkk": {"1": 300}}
        raised = so.evaluate_card(expensive, override)
        self.assertEqual(base["market_band"], "PREMIUM")
        self.assertNotEqual(base["signal"], "REVIEW")
        self.assertEqual(raised["market_band"], "CORE")
        self.assertEqual(raised["signal"], "REVIEW")
        self.assertEqual(raised["purchase_budget_dkk"], 300.0)

    def test_expensive_non_curated_priority_card_is_demoted_from_review(self):
        expensive = so.evaluate_card(card(trend=50, avg1=50, avg7=60, avg30=70), PROFILE)
        self.assertEqual(expensive["market_band"], "HIGH-END")
        self.assertEqual(expensive["signal"], "WATCH")

    def test_wishlist_can_keep_high_end_card_in_review(self):
        wishlist = {**PROFILE, "wishlist_ids": ["1"]}
        expensive = so.evaluate_card(card(trend=50, avg1=50, avg7=60, avg30=70), wishlist)
        self.assertEqual(expensive["market_band"], "HIGH-END")
        self.assertEqual(expensive["signal"], "REVIEW")
        self.assertIn("wishlist", expensive["reasons"])

    def test_market_scale_boundaries(self):
        self.assertEqual(so.market_scale_fit(75, 75)[0], "CORE")
        self.assertEqual(so.market_scale_fit(150, 75)[0], "STRETCH")
        self.assertEqual(so.market_scale_fit(151, 75)[0], "PREMIUM")
        self.assertEqual(so.market_scale_fit(301, 75)[0], "HIGH-END")

    def test_non_personal_card_is_filtered_before_scoring(self):
        self.assertIsNone(so.evaluate_card(card(name="Absol [Raid]"), PROFILE))

    def test_code_card_is_filtered_even_when_name_contains_priority_pokemon(self):
        code = card(name="Online Code Card (Detective Pikachu Tins: Mewtwo GX Tin)")
        self.assertIsNone(so.evaluate_card(code, PROFILE))

    def test_owned_and_ignored_cards_are_filtered(self):
        owned = {**PROFILE, "owned_ids": ["1"]}
        ignored = {**PROFILE, "ignore_ids": ["1"]}
        self.assertIsNone(so.evaluate_card(card(), owned))
        self.assertIsNone(so.evaluate_card(card(), ignored))

    def test_mew_does_not_match_mewtwo(self):
        score, reasons = so.personal_score(card(name="Mewtwo ex [Psychic]"), PROFILE)
        self.assertNotIn("priority Pokémon", reasons)
        self.assertEqual(score, 0.0)

    def test_wishlist_makes_non_named_card_eligible(self):
        wishlist = {**PROFILE, "wishlist_ids": ["1"]}
        wanted = so.evaluate_card(card(name="Articuno [Ice Beam]"), wishlist)
        self.assertIsNotNone(wanted)
        self.assertIn("wishlist", wanted["reasons"])

    def test_low_confidence_cannot_be_review(self):
        row = so.evaluate_card(card(trend=5, avg1=5, avg7=20, avg30=40), PROFILE)
        self.assertEqual(row["confidence"], "LOW")
        self.assertNotEqual(row["signal"], "REVIEW")

    def test_reference_uses_trend_not_low(self):
        row = so.evaluate_card(card(trend=9, avg7=10, avg30=11, low=0.5), PROFILE)
        self.assertEqual(row["reference_eur"], 9.0)
        self.assertEqual(row["diagnostic_low_eur"], 0.5)

    def test_pikachu_delta_example_is_review_not_purchase_claim(self):
        row = so.evaluate_card(
            card(
                name="Pikachu δ Delta Species [Tail Whap / Steel Headbutt]",
                trend=3.98,
                avg1=6.15,
                avg7=5.25,
                avg30=5.74,
                low=0.90,
            ),
            PROFILE,
        )
        self.assertEqual(row["signal"], "REVIEW")
        self.assertAlmostEqual(row["reference_dkk"], 29.69, places=2)
        self.assertEqual(row["market_band"], "CORE")
        self.assertIn("aggregate market scale: core", row["reasons"])

    def test_report_uses_v53_radar_language_and_never_buy(self):
        rows = [so.evaluate_card(card(), PROFILE)]
        report = so.build_report(rows, PROFILE)
        self.assertIn("V53 actionability shadow", report)
        self.assertIn("Market reference is NOT an EN/NM purchase price", report)
        self.assertIn("never emits BUY", report)
        self.assertIn("CORE market scale", report)
        self.assertNotIn("reference within target", report)


if __name__ == "__main__":
    unittest.main()
