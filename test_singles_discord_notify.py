import unittest

from personal import singles_discord_notify as notify


def row(
    card_id="1",
    signal="REVIEW",
    listing_signal="RADAR_ONLY",
    reference_dkk=60.0,
    score=80.0,
):
    return {
        "id": card_id,
        "name": "Pikachu [Zap]",
        "set": "151",
        "canonical_rarity": "Illustration Rare",
        "v55_signal": signal,
        "listing_signal": listing_signal,
        "reference_dkk": reference_dkk,
        "purchase_budget_dkk": 75.0,
        "trend_vs_avg30_pct": -22.0,
        "score": score,
    }


class SinglesDiscordNotifyTests(unittest.TestCase):
    def test_first_run_only_surfaces_top_five_and_baselines_rest(self):
        rows = [row(str(index), score=100 - index) for index in range(1, 8)]
        alerts = notify.plan_alerts(rows, {"version": 1, "cards": {}}, limit=5)
        self.assertEqual(len(alerts), 5)
        self.assertTrue(all(item["alert_reason"] == "NEW_REVIEW" for item in alerts))
        snapshot = notify.state_snapshot(rows, "2026-09-03T00:00:00+00:00")
        self.assertEqual(len(snapshot["cards"]), 7)

    def test_unchanged_review_is_not_repeated(self):
        current = row()
        state = {
            "cards": {
                "1": {
                    "v55_signal": "REVIEW",
                    "listing_signal": "RADAR_ONLY",
                    "reference_dkk": 60.0,
                    "score": 80.0,
                }
            }
        }
        self.assertEqual(notify.plan_alerts([current], state), [])

    def test_watch_to_review_alerts(self):
        state = {
            "cards": {
                "1": {
                    "v55_signal": "WATCH",
                    "listing_signal": "RADAR_ONLY",
                    "reference_dkk": 60.0,
                    "score": 70.0,
                }
            }
        }
        alerts = notify.plan_alerts([row()], state)
        self.assertEqual(alerts[0]["alert_reason"], "PROMOTED_REVIEW")

    def test_material_price_improvement_alerts(self):
        state = {
            "cards": {
                "1": {
                    "v55_signal": "REVIEW",
                    "listing_signal": "RADAR_ONLY",
                    "reference_dkk": 70.0,
                    "score": 80.0,
                }
            }
        }
        alerts = notify.plan_alerts([row(reference_dkk=60.0)], state)
        self.assertEqual(alerts[0]["alert_reason"], "PRICE_IMPROVED")

    def test_small_price_move_is_silent(self):
        state = {
            "cards": {
                "1": {
                    "v55_signal": "REVIEW",
                    "listing_signal": "RADAR_ONLY",
                    "reference_dkk": 62.0,
                    "score": 80.0,
                }
            }
        }
        self.assertEqual(notify.plan_alerts([row(reference_dkk=60.0)], state), [])

    def test_exact_listing_escalation_alerts_before_price_check(self):
        state = {
            "cards": {
                "1": {
                    "v55_signal": "REVIEW",
                    "listing_signal": "LISTING_WATCH",
                    "reference_dkk": 60.0,
                    "score": 80.0,
                }
            }
        }
        alerts = notify.plan_alerts([row(listing_signal="LISTING_REVIEW")], state)
        self.assertEqual(alerts[0]["alert_reason"], "EXACT_LISTING")

    def test_score_gain_alerts(self):
        state = {
            "cards": {
                "1": {
                    "v55_signal": "REVIEW",
                    "listing_signal": "RADAR_ONLY",
                    "reference_dkk": 60.0,
                    "score": 74.0,
                }
            }
        }
        alerts = notify.plan_alerts([row(score=80.0)], state)
        self.assertEqual(alerts[0]["alert_reason"], "SCORE_IMPROVED")

    def test_non_review_never_alerts(self):
        self.assertEqual(notify.plan_alerts([row(signal="WATCH")], {"cards": {}}), [])

    def test_cardmarket_search_text_matches_cardmarket_display_format(self):
        rarity_metadata = {
            "1": {
                "canonical_name": "Umbreon",
                "canonical_number": "10",
                "source_set_id": "hgss3",
            }
        }
        exact = row()
        exact["set"] = "Undaunted"
        self.assertEqual(
            notify.cardmarket_search_text(exact, rarity_metadata),
            "Umbreon (UD 10)",
        )

    def test_explicit_cardmarket_set_code_wins(self):
        rarity_metadata = {
            "1": {
                "canonical_name": "Umbreon",
                "canonical_number": "10",
                "source_set_id": "hgss3",
                "cardmarket_set_code": "XYZ",
            }
        }
        self.assertEqual(
            notify.cardmarket_search_text(row(), rarity_metadata),
            "Umbreon (XYZ 10)",
        )

    def test_radar_only_cardmarket_is_neutral_without_buy_claim(self):
        product = row()
        product["alert_reason"] = "NEW_REVIEW"
        embed = notify.embed_for(product, {})
        fields = {field["name"]: field["value"] for field in embed["fields"]}
        self.assertEqual(embed["color"], 0x95A5A6)
        self.assertIn("RADAR_ONLY", fields["Status"])
        self.assertIn("ingen verificeret annonce", fields["Status"])
        self.assertIn("ikke en købsanbefaling", embed["description"])
        self.assertEqual(fields["Maksbudget – ikke annoncepris"], "75 kr.")
        self.assertNotIn("KØB NU", str(embed))
        self.assertNotIn("url", embed)

    def test_exact_listing_review_is_not_green_or_buy_now(self):
        product = row(listing_signal="LISTING_REVIEW")
        product.update({"alert_reason": "EXACT_LISTING", "listing_total_dkk": 65.0})
        embed = notify.embed_for(product, {})
        fields = {field["name"]: field["value"] for field in embed["fields"]}
        self.assertEqual(embed["color"], 0x95A5A6)
        self.assertIn("LISTING_REVIEW", fields["Status"])
        self.assertIn("kontrollér manuelt", fields["Status"])
        self.assertIn("Verificeret total", fields)
        self.assertEqual(fields["Verificeret total"], "65 kr.")
        self.assertIn("fragt og gebyrer", embed["description"])
        self.assertNotIn("BUY_NOW", str(embed))
        self.assertNotIn("url", embed)

    def test_cardmarket_post_remains_single_batch_and_no_mentions(self):
        from unittest.mock import patch
        products = [row(str(i)) for i in range(3)]
        for item in products:
            item["alert_reason"] = "NEW_REVIEW"
        with patch.object(notify.requests, "post") as post:
            notify.post_discord("https://example.invalid/webhook", products, {})
        self.assertEqual(post.call_count, 1)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(len(payload["embeds"]), 3)
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertTrue(all(item["color"] == 0x95A5A6 for item in payload["embeds"]))

    def test_embed_contains_copyable_cardmarket_search_text(self):
        rarity_metadata = {
            "1": {
                "canonical_name": "Umbreon",
                "canonical_number": "10",
                "source_set_id": "hgss3",
            }
        }
        exact = row()
        exact["set"] = "Undaunted"
        exact["alert_reason"] = "PROMOTED_REVIEW"
        embed = notify.embed_for(exact, rarity_metadata)
        search_field = next(field for field in embed["fields"] if field["name"] == "Cardmarket-søgning")
        self.assertEqual(search_field["value"], "`Umbreon (UD 10)`")


if __name__ == "__main__":
    unittest.main()
