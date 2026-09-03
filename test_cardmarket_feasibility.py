import unittest

import cardmarket_feasibility as cf


def card(card_id, low, set_name, name=None):
    return {
        "game": "POKÉMON",
        "id": str(card_id),
        "name": name or f"Card {card_id}",
        "set": set_name,
        "variant": "Normal",
        "low": low,
        "market": low * 1.2 if low else 1,
        "trend": low * 1.2 if low else 1,
        "avg30": low * 1.25 if low else 1,
    }


def review(price, *, language="EN", condition="NM", country="DE", ships=True, match=True):
    return {
        "product_match": match,
        "language": language,
        "condition": condition,
        "seller_country": country,
        "ships_to_denmark": ships,
        "listing_price_eur": price,
    }


class CardmarketFeasibilityTests(unittest.TestCase):
    def test_normalized_cards_filters_non_pokemon_and_missing_prices(self):
        state = {
            "cards": {
                "POKÉMON|1": card(1, 5, "A"),
                "LORCANA|2": {**card(2, 5, "B"), "game": "LORCANA"},
                "POKÉMON|3": {**card(3, 5, "C"), "low": None},
            }
        }
        rows = cf.normalized_cards(state)
        self.assertEqual([row["id"] for row in rows], ["1"])

    def test_select_cases_is_deterministic_and_price_diverse(self):
        cards = []
        lows = [0.5, 1.0, 2.5, 4.0, 6.0, 8.0, 12.0, 18.0, 24.0, 35.0, 50.0, 80.0]
        for index, low in enumerate(lows, 1):
            cards.append(card(index, low, f"Set {index}"))
        first = cf.select_cases(cards, 8)
        second = cf.select_cases(list(reversed(cards)), 8)
        self.assertEqual([row["id"] for row in first], [row["id"] for row in second])
        self.assertGreaterEqual(len({cf.price_band(row["low"]) for row in first}), 3)

    def test_complete_english_nm_eu_denmark_listing_is_usable(self):
        row = cf.evaluate_case(card(1, 10, "Set"), review(10.5))
        self.assertTrue(row["reviewed"])
        self.assertTrue(row["usable_listing"])
        self.assertAlmostEqual(row["low_gap_pct"], 5.0)

    def test_foreign_language_is_not_usable(self):
        row = cf.evaluate_case(card(1, 10, "Set"), review(10.0, language="DE"))
        self.assertTrue(row["reviewed"])
        self.assertFalse(row["usable_listing"])

    def test_played_condition_is_not_usable(self):
        row = cf.evaluate_case(card(1, 10, "Set"), review(10.0, condition="LP"))
        self.assertFalse(row["usable_listing"])

    def test_non_eu_or_no_shipping_is_not_usable(self):
        self.assertFalse(cf.evaluate_case(card(1, 10, "Set"), review(10, country="GB"))["usable_listing"])
        self.assertFalse(cf.evaluate_case(card(1, 10, "Set"), review(10, ships=False))["usable_listing"])

    def test_incomplete_reviews_are_pending(self):
        rows = [cf.evaluate_case(card(i, 10, f"S{i}"), {}) for i in range(20)]
        self.assertEqual(cf.decide(rows).level, "PENDING")

    def test_good_review_set_can_be_purchase_ready(self):
        rows = [
            cf.evaluate_case(card(i, 10, f"S{i}"), review(10.5 if i < 18 else 11.0))
            for i in range(20)
        ]
        self.assertEqual(cf.decide(rows).level, "PURCHASE_READY")

    def test_large_gap_or_constraint_failures_stay_radar_only(self):
        rows = []
        for i in range(20):
            r = review(14.0)
            if i < 5:
                r["language"] = "DE"
            rows.append(cf.evaluate_case(card(i, 10, f"S{i}"), r))
        self.assertEqual(cf.decide(rows).level, "RADAR_ONLY")

    def test_report_explicitly_states_shadow_only_and_constraints(self):
        rows = [cf.evaluate_case(card(1, 10, "Set"), {})]
        report = cf.build_report(rows)
        self.assertIn("Shadow-only", report)
        self.assertIn("English", report)
        self.assertIn("EU→DK", report)


if __name__ == "__main__":
    unittest.main()
