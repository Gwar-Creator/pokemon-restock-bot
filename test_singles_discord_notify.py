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


if __name__ == "__main__":
    unittest.main()
