"""Conservative manual cost limit tests; synthetic evidence, no Tradera traffic."""
import unittest
from datetime import datetime, timezone

from vintage_lot_budget import evaluate_manual_lot

NOW = datetime(2026, 10, 28, 21, tzinfo=timezone.utc)
LISTING = {
    "id": "757471322",
    "url": "https://www.tradera.com/item/1001342/757471322",
    "title": "Pokemon e-Card lot - Aquapolis & Expedition",
}


def verified():
    return {
        "listing_id": "757471322",
        "seller_reputation_checked": True,
        "english_cards_verified": True,
        "identities_verified": True,
        "front_back_photos_checked": True,
        "condition_verified": True,
        "authenticity_checked": True,
        "shipping_to_denmark_verified": True,
        "all_fees_verified": True,
        "eu_comparables_reviewed": True,
        "inventory_checked": True,
        "personal_cap_approved": True,
        "budget_available_confirmed": True,
        "reviewed_at": "2026-10-28T20:00:00Z",
        "fx_checked_at": "2026-10-28T18:00:00Z",
        "card_details": [
            {"name": "Chikorita", "set": "Expedition", "number": "99/165",
             "condition": "LP", "edition": "Unlimited", "interest": "KEEP"},
            {"name": "Random Trainer", "set": "Expedition", "number": "1/165",
             "condition": "LP", "edition": "Unlimited", "interest": "FILLER"},
        ],
        "current_required_price_sek": "200",
        "shipping_to_denmark_sek": "50",
        "platform_fees_sek": "10",
        "payment_fees_dkk": "5",
        "sek_to_dkk_rate": "0.65",
        "available_hobby_budget_dkk": "240",
        "conservative_personal_cap_dkk": "200",
    }


class ManualVintageBudgetTests(unittest.TestCase):
    def test_zero_evidence_never_claims_a_deal(self):
        report = evaluate_manual_lot(LISTING, {}, NOW)
        self.assertEqual(report["status"], "MISSING_EVIDENCE")
        self.assertIsNone(report["buy_bid_signal"])
        self.assertFalse(report["discord_eligible"])
        self.assertNotIn("total_cost_dkk", report)
        self.assertNotIn("max_bid_sek", report)

    def test_verified_cost_including_denmark_shipping_and_fees(self):
        report = evaluate_manual_lot(LISTING, verified(), NOW)
        self.assertEqual(report["status"], "MANUAL_FINANCIAL_REVIEW")
        self.assertEqual(report["total_cost_dkk"], "174.00")
        self.assertEqual(report["enforced_cap_dkk"], "200")
        self.assertEqual(report["max_bid_sek"], "240")
        self.assertEqual(report["verified_keep_cards"], 1)
        self.assertEqual(report["filler_cards"], 1)
        self.assertFalse(report["discord_eligible"])
        self.assertIsNone(report["buy_bid_signal"])

    def test_actual_price_above_manual_cap_is_not_buy(self):
        evidence = {**verified(), "current_required_price_sek": "500"}
        report = evaluate_manual_lot(LISTING, evidence, NOW)
        self.assertEqual(report["status"], "OVER_LIMIT")
        self.assertEqual(report["total_cost_dkk"], "369.00")
        self.assertIn("current_total_exceeds_verified_cap", report["missing_or_blocking"])
        self.assertFalse(report["discord_eligible"])

    def test_budget_is_stricter_than_personal_valuation_cap(self):
        evidence = {**verified(), "available_hobby_budget_dkk": "100"}
        report = evaluate_manual_lot(LISTING, evidence, NOW)
        self.assertEqual(report["enforced_cap_dkk"], "100")
        self.assertEqual(report["max_bid_sek"], "86")
        self.assertEqual(report["status"], "OVER_LIMIT")

    def test_missing_dk_shipping_price_variants_and_user_cap_block(self):
        for name, value in (
            ("shipping_to_denmark_verified", False),
            ("shipping_to_denmark_sek", None),
            ("platform_fees_sek", None),
            ("sek_to_dkk_rate", None),
            ("available_hobby_budget_dkk", None),
            ("conservative_personal_cap_dkk", None),
            ("english_cards_verified", False),
            ("seller_reputation_checked", False),
            ("inventory_checked", False),
            ("personal_cap_approved", False),
            ("card_details", []),
            ("card_details", [{"name": "Pikachu", "interest": "KEEP"}]),
            ("fx_checked_at", "2026-10-25T10:00:00Z"),
            ("reviewed_at", "2026-10-27T10:00:00Z"),
        ):
            with self.subTest(name=name):
                evidence = {**verified(), name: value}
                report = evaluate_manual_lot(LISTING, evidence, NOW)
                self.assertEqual(report["status"], "MISSING_EVIDENCE")
                self.assertIsNone(report["buy_bid_signal"])
                self.assertNotIn("max_bid_sek", report)

    def test_missing_price_and_bad_numbers_block(self):
        for value in ("-1", "NaN", "Infinity", "0", True, "", "Not a number"):
            with self.subTest(value=value):
                report = evaluate_manual_lot(
                    LISTING, {**verified(), "current_required_price_sek": value}, NOW
                )
                self.assertEqual(report["status"], "MISSING_EVIDENCE")

    def test_filler_only_is_not_useful_even_under_budget(self):
        evidence = verified()
        evidence["card_details"] = [{**evidence["card_details"][0], "interest": "FILLER"}]
        report = evaluate_manual_lot(LISTING, evidence, NOW)
        self.assertEqual(report["status"], "NOT_RELEVANT")
        self.assertNotIn("max_bid_sek", report)

    def test_mismatched_listing_and_untrusted_urls_fail_closed(self):
        for listing, ev in (
            (LISTING, {**verified(), "listing_id": "unexpected"}),
            ({**LISTING, "url": "https://evil.invalid/item/1"}, verified()),
            ({**LISTING, "id": "not-an-id"}, verified()),
        ):
            report = evaluate_manual_lot(listing, ev, NOW)
            self.assertEqual(report["status"], "MISSING_EVIDENCE")
            self.assertFalse(report["discord_eligible"])

    def test_manual_approval_does_not_turn_this_into_discord(self):
        evidence = {**verified(), "human_approved": True, "action": "KØB"}
        report = evaluate_manual_lot(LISTING, evidence, NOW)
        self.assertIsNone(report["buy_bid_signal"])
        self.assertFalse(report["discord_eligible"])


if __name__ == "__main__":
    unittest.main()
