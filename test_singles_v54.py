import unittest

from personal import singles_v54 as v54

PROFILE = {
    "eur_to_dkk": 7.46,
    "default_target_dkk": 75,
    "collectable_target_dkk": 150,
    "collectable_target_min_score": 75,
    "automatic_review_ceiling_dkk": 150,
    "priority_pokemon": ["Pikachu", "Psyduck", "Mew"],
    "secondary_pokemon": ["Rayquaza"],
    "wishlist_ids": [],
    "manual_priority_ids": [],
    "owned_ids": [],
    "ignore_ids": [],
    "target_overrides_dkk": {},
}


def card(
    name="Pikachu [Zap]",
    set_name="Test Set",
    variant="Normal",
    trend=6,
    avg1=6,
    avg7=7,
    avg30=8,
    card_id="1",
):
    return {
        "game": "POKÉMON",
        "id": card_id,
        "name": name,
        "set": set_name,
        "variant": variant,
        "trend": trend,
        "avg1": avg1,
        "avg7": avg7,
        "avg30": avg30,
        "low": 1,
    }


class SinglesV54Tests(unittest.TestCase):
    def test_fossil_card_gets_strong_150_tier(self):
        row = v54.evaluate_card(card(name="Psyduck [Headache]", set_name="Fossil"), PROFILE)
        self.assertEqual(row["collectability_tier"], "STRONG")
        self.assertEqual(row["purchase_budget_dkk"], 150.0)

    def test_delta_species_is_iconic(self):
        row = v54.evaluate_card(
            card(name="Pikachu δ Delta Species [Tail Whap]", set_name="EX Holon Phantoms"),
            PROFILE,
        )
        self.assertEqual(row["collectability_tier"], "ICONIC")
        self.assertEqual(row["purchase_budget_dkk"], 150.0)

    def test_generic_v_does_not_unlock_150(self):
        row = v54.evaluate_card(card(name="Pikachu V [Thunder]", set_name="Sword & Shield"), PROFILE)
        self.assertEqual(row["collectability_tier"], "STANDARD")
        self.assertEqual(row["purchase_budget_dkk"], 75.0)

    def test_explicit_illustration_variant_unlocks_150(self):
        row = v54.evaluate_card(card(variant="Illustration Rare"), PROFILE)
        self.assertEqual(row["collectability_tier"], "STRONG")
        self.assertEqual(row["purchase_budget_dkk"], 150.0)

    def test_automatic_review_ceiling_stays_150(self):
        row = v54.evaluate_card(
            card(
                name="Pikachu δ Delta Species [Tail Whap]",
                set_name="EX Holon Phantoms",
                trend=25,
                avg1=25,
                avg7=30,
                avg30=35,
            ),
            PROFILE,
        )
        self.assertGreater(row["reference_dkk"], 150)
        self.assertNotEqual(row["signal"], "REVIEW")

    def test_wishlist_can_still_override_ceiling_for_manual_review(self):
        profile = {**PROFILE, "wishlist_ids": ["1"]}
        row = v54.evaluate_card(
            card(trend=25, avg1=25, avg7=30, avg30=35),
            profile,
        )
        self.assertEqual(row["signal"], "REVIEW")

    def test_report_explains_two_tier_budget(self):
        row = v54.evaluate_card(card(), PROFILE)
        report = v54.build_report([row], PROFILE)
        self.assertIn("V54 collectability shadow", report)
        self.assertIn("Normal singles target: 75 kr.", report)
        self.assertIn("Strong collectable target: 150 kr.", report)
        self.assertIn("150 kr. is not a blanket target", report)
        self.assertIn("never emits BUY", report)


if __name__ == "__main__":
    unittest.main()
