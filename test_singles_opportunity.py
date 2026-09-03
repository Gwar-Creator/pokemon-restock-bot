import unittest

from personal import singles_opportunity as so

PROFILE = {
    "eur_to_dkk": 7.46,
    "default_target_dkk": 75,
    "priority_pokemon": ["Mew", "Snorlax"],
    "secondary_pokemon": ["Rayquaza"],
    "wishlist_ids": [],
    "manual_priority_ids": [],
    "owned_ids": [],
    "ignore_ids": [],
    "target_overrides_dkk": {},
}


def card(card_id="1", name="Mew ex [Restart]", trend=8, avg1=8, avg7=8.5, avg30=9, low=2):
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

    def test_priority_budget_card_can_be_check_now(self):
        row = so.evaluate_card(card(), PROFILE)
        self.assertEqual(row["signal"], "CHECK_NOW")
        self.assertIn("priority Pokémon", row["reasons"])

    def test_over_budget_card_is_not_check_now(self):
        row = so.evaluate_card(card(trend=25, avg1=24, avg7=25, avg30=26), PROFILE)
        self.assertNotEqual(row["signal"], "CHECK_NOW")

    def test_owned_and_ignored_cards_are_filtered(self):
        owned = {**PROFILE, "owned_ids": ["1"]}
        ignored = {**PROFILE, "ignore_ids": ["1"]}
        self.assertIsNone(so.evaluate_card(card(), owned))
        self.assertIsNone(so.evaluate_card(card(), ignored))

    def test_mew_does_not_match_mewtwo(self):
        score, reasons = so.personal_score(card(name="Mewtwo ex [Psychic]"), PROFILE)
        self.assertNotIn("priority Pokémon", reasons)
        self.assertEqual(score, 35.0)

    def test_wishlist_adds_personal_priority(self):
        base = so.evaluate_card(card(), PROFILE)
        wishlist = {**PROFILE, "wishlist_ids": ["1"]}
        wanted = so.evaluate_card(card(), wishlist)
        self.assertGreater(wanted["score"], base["score"])
        self.assertIn("wishlist", wanted["reasons"])

    def test_low_confidence_caps_signal(self):
        row = so.evaluate_card(card(trend=5, avg1=5, avg7=20, avg30=40), PROFILE)
        self.assertEqual(row["confidence"], "LOW")
        self.assertNotEqual(row["signal"], "CHECK_NOW")

    def test_reference_uses_trend_not_low(self):
        row = so.evaluate_card(card(trend=9, avg7=10, avg30=11, low=0.5), PROFILE)
        self.assertEqual(row["reference_eur"], 9.0)
        self.assertEqual(row["diagnostic_low_eur"], 0.5)

    def test_target_override_can_make_card_eligible(self):
        expensive = card(trend=15, avg1=15, avg7=15.5, avg30=16)
        base = so.evaluate_card(expensive, PROFILE)
        override = {**PROFILE, "target_overrides_dkk": {"1": 130}}
        raised = so.evaluate_card(expensive, override)
        self.assertNotEqual(base["signal"], "CHECK_NOW")
        self.assertEqual(raised["signal"], "CHECK_NOW")

    def test_report_never_calls_a_signal_buy(self):
        rows = [so.evaluate_card(card(), PROFILE)]
        report = so.build_report(rows, PROFILE)
        self.assertIn("CHECK_NOW is not a buy signal", report)
        self.assertIn("never emits BUY", report)
        self.assertIn("zero weight", report)


if __name__ == "__main__":
    unittest.main()
