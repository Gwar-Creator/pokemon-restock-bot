import unittest
from datetime import datetime, timezone

from personal import singles_v56 as v56

NOW = datetime(2026, 9, 3, 16, 0, tzinfo=timezone.utc)
PROFILE = {
    "eur_to_dkk": 7.46,
    "default_target_dkk": 75,
    "collectable_target_dkk": 150,
    "collectable_target_min_score": 75,
    "automatic_review_ceiling_dkk": 150,
    "priority_pokemon": ["Pikachu"],
    "secondary_pokemon": [],
    "wishlist_ids": [],
    "manual_priority_ids": [],
    "owned_ids": [],
    "ignore_ids": [],
    "target_overrides_dkk": {},
}


def card():
    return {
        "game": "POKÉMON",
        "id": "1",
        "name": "Pikachu δ Delta Species [Tail Whap | Steel Headbutt]",
        "set": "EX Holon Phantoms",
        "variant": "Normal",
        "trend": 6,
        "avg1": 6,
        "avg7": 7,
        "avg30": 8,
        "low": 1,
    }


def metadata():
    return {
        "1": {
            "source_card_id": "ex13-79",
            "cardmarket_set": "EX Holon Phantoms",
            "canonical_rarity": "Common",
        }
    }


def offer(**changes):
    row = {
        "source": "official_cardmarket_api_v2",
        "id_article": "A1",
        "product_id": "1",
        "language_id": 1,
        "language": "English",
        "condition": "NM",
        "price_eur": 5.0,
        "seller_name": "Seller",
        "seller_country": "DE",
        "is_foil": False,
        "expected_variant": "Normal",
        "variant_match": True,
        "checked_at": "2026-09-03T15:00:00Z",
        "ships_to_denmark": None,
        "shipping_eur": None,
    }
    row.update(changes)
    return row


def snapshot(row):
    return {"version": 1, "source": "official_cardmarket_api_v2", "offers": {"1": [row]}}


class SinglesV56Tests(unittest.TestCase):
    def test_verified_listing_with_shipping_becomes_listing_review(self):
        shipping = {"A1": {"ships_to_denmark": True, "shipping_eur": 1.0}}
        row = v56.evaluate_card(card(), PROFILE, metadata(), snapshot(offer()), shipping, now=NOW)
        self.assertEqual(row["v55_signal"], "REVIEW")
        self.assertEqual(row["listing_status"], "VERIFIED")
        self.assertEqual(row["listing_signal"], "LISTING_REVIEW")
        self.assertAlmostEqual(row["listing_total_dkk"], 44.76, places=2)

    def test_official_listing_without_destination_shipping_stays_watch(self):
        row = v56.evaluate_card(card(), PROFILE, metadata(), snapshot(offer()), {}, now=NOW)
        self.assertEqual(row["listing_status"], "SHIPPING_UNVERIFIED")
        self.assertEqual(row["listing_signal"], "LISTING_WATCH")
        self.assertIsNone(row["listing_total_dkk"])

    def test_non_eu_seller_is_rejected(self):
        row = v56.evaluate_card(
            card(), PROFILE, metadata(), snapshot(offer(seller_country="US")), {}, now=NOW
        )
        self.assertEqual(row["listing_status"], "REJECTED")
        self.assertEqual(row["listing_signal"], "RADAR_ONLY")

    def test_stale_listing_is_rejected(self):
        row = v56.evaluate_card(
            card(), PROFILE, metadata(), snapshot(offer(checked_at="2026-09-01T00:00:00Z")), {}, now=NOW
        )
        self.assertEqual(row["listing_status"], "REJECTED")

    def test_variant_mismatch_is_rejected(self):
        row = v56.evaluate_card(
            card(), PROFILE, metadata(), snapshot(offer(is_foil=True, variant_match=False)), {}, now=NOW
        )
        self.assertEqual(row["listing_status"], "REJECTED")
        self.assertEqual(row["listing_signal"], "RADAR_ONLY")

    def test_verified_but_over_budget_stays_listing_watch(self):
        expensive = offer(price_eur=30.0)
        shipping = {"A1": {"ships_to_denmark": True, "shipping_eur": 1.0}}
        row = v56.evaluate_card(card(), PROFILE, metadata(), snapshot(expensive), shipping, now=NOW)
        self.assertEqual(row["listing_status"], "VERIFIED")
        self.assertFalse(row["listing_within_budget"])
        self.assertEqual(row["listing_signal"], "LISTING_WATCH")

    def test_wrong_product_id_never_verifies(self):
        row = v56.evaluate_card(
            card(), PROFILE, metadata(), snapshot(offer(product_id="999")), {}, now=NOW
        )
        self.assertEqual(row["listing_status"], "REJECTED")

    def test_report_keeps_manual_guardrail(self):
        row = v56.evaluate_card(card(), PROFILE, metadata(), snapshot(offer()), {}, now=NOW)
        report = v56.build_report([row], PROFILE)
        self.assertIn("V56 exact-listing verification", report)
        self.assertIn("shipping", report.lower())
        self.assertIn("never emits BUY", report)
        self.assertNotIn("| BUY |", report)


if __name__ == "__main__":
    unittest.main()
