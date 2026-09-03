import unittest

from personal import singles_v55 as v55

PROFILE = {
    "eur_to_dkk": 7.46,
    "default_target_dkk": 75,
    "collectable_target_dkk": 150,
    "collectable_target_min_score": 75,
    "automatic_review_ceiling_dkk": 150,
    "priority_pokemon": ["Pikachu", "Psyduck", "Mew"],
    "secondary_pokemon": ["Vaporeon"],
    "wishlist_ids": [],
    "manual_priority_ids": [],
    "owned_ids": [],
    "ignore_ids": [],
    "target_overrides_dkk": {},
}


def card(
    card_id="1",
    name="Pikachu δ Delta Species [Tail Whap | Steel Headbutt]",
    set_name="EX Holon Phantoms",
    trend=6,
    avg1=6,
    avg7=7,
    avg30=8,
    variant="Normal",
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


def metadata(rarity="Common", set_name="EX Holon Phantoms", source_id="ex13-79", finish="normal"):
    return {
        "1": {
            "source_card_id": source_id,
            "cardmarket_set": set_name,
            "canonical_rarity": rarity,
            "finish": finish,
        }
    }


class SinglesV55Tests(unittest.TestCase):
    def test_canonical_rarity_ordering(self):
        self.assertGreater(v55.canonical_rarity_score("Rare Holo"), v55.canonical_rarity_score("Rare"))
        self.assertGreater(v55.canonical_rarity_score("Rare"), v55.canonical_rarity_score("Uncommon"))
        self.assertGreater(v55.canonical_rarity_score("Uncommon"), v55.canonical_rarity_score("Common"))
        self.assertGreater(v55.canonical_rarity_score("Special Illustration Rare"), v55.canonical_rarity_score("Rare Holo"))

    def test_verified_common_delta_no_longer_unlocks_review_or_150(self):
        row = v55.evaluate_card(card(), PROFILE, metadata("Common"))
        self.assertTrue(row["canonical_rarity_verified"])
        self.assertEqual(row["canonical_rarity"], "Common")
        self.assertEqual(row["collectability_tier"], "STANDARD")
        self.assertEqual(row["purchase_budget_dkk"], 75.0)
        self.assertFalse(row["automatic_review_quality"])
        self.assertNotEqual(row["signal"], "REVIEW")

    def test_verified_heritage_common_no_longer_unlocks_150(self):
        psyduck = card(name="Psyduck [Headache | Fury Swipes]", set_name="Fossil")
        row = v55.evaluate_card(psyduck, PROFILE, metadata("Common", "Fossil", "base3-53"))
        self.assertEqual(row["collectability_tier"], "STANDARD")
        self.assertEqual(row["purchase_budget_dkk"], 75.0)
        self.assertNotEqual(row["signal"], "REVIEW")

    def test_plain_rare_favourite_cannot_auto_review(self):
        ditto = card(name="Pikachu [Zap]", set_name="Test Set")
        row = v55.evaluate_card(ditto, PROFILE, metadata("Rare", "Test Set"))
        self.assertFalse(row["automatic_review_quality"])
        self.assertNotEqual(row["signal"], "REVIEW")

    def test_holo_rare_can_pass_quality_gate(self):
        holo = card(name="Pikachu [Zap]", set_name="Test Set", trend=4, avg1=4, avg7=5, avg30=6)
        row = v55.evaluate_card(holo, PROFILE, metadata("Rare Holo", "Test Set", finish="holo"))
        self.assertTrue(row["automatic_review_quality"])
        self.assertGreater(row["collectability_score"], 70)

    def test_rarity_calibrates_same_card_upward(self):
        common = v55.evaluate_card(card(name="Pikachu [Zap]", set_name="Test Set"), PROFILE, metadata("Common", "Test Set"))
        sir = v55.evaluate_card(card(name="Pikachu [Zap]", set_name="Test Set"), PROFILE, metadata("Special Illustration Rare", "Test Set"))
        self.assertGreater(sir["collectability_score"], common["collectability_score"])
        self.assertGreater(sir["score"], common["score"])

    def test_unverified_rarity_cannot_create_review(self):
        row = v55.evaluate_card(card(), PROFILE, {})
        self.assertFalse(row["canonical_rarity_verified"])
        self.assertEqual(row["canonical_rarity"], "UNVERIFIED")
        self.assertNotEqual(row["signal"], "REVIEW")
        self.assertLess(row["collectability_score"], 60.0)

    def test_set_mismatch_invalidates_exact_id_metadata(self):
        wrong = metadata("Rare Holo", "Different Set")
        row = v55.evaluate_card(card(), PROFILE, wrong)
        self.assertFalse(row["canonical_rarity_verified"])
        self.assertNotEqual(row["signal"], "REVIEW")

    def test_explicit_wishlist_can_review_without_canonical_rarity(self):
        profile = {**PROFILE, "wishlist_ids": ["1"]}
        row = v55.evaluate_card(card(), profile, {})
        self.assertEqual(row["signal"], "REVIEW")
        self.assertFalse(row["canonical_rarity_verified"])

    def test_report_surfaces_rarity_first_guardrail(self):
        verified = v55.evaluate_card(card(), PROFILE, metadata("Common"))
        unknown = v55.evaluate_card(card(card_id="2"), PROFILE, {})
        report = v55.build_report([verified, unknown], PROFILE)
        self.assertIn("V55.2 rarity-first shadow", report)
        self.assertIn("Canonical rarity coverage: 1/2", report)
        self.assertIn("Plain Common/Uncommon/Rare cards", report)
        self.assertIn("favourite Pokemon is a booster", report)
        self.assertIn("never emits BUY", report)


if __name__ == "__main__":
    unittest.main()
