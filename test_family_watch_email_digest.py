import unittest
from datetime import datetime, timedelta, timezone

import family_watch as fw
import family_watch_email_digest as digest


class FamilyWatchEmailDigestTests(unittest.TestCase):
    def _offer(self, *, name="Cheasy skyr", store="Bilka", start=None, offer_id="o1"):
        start = start or datetime(2026, 9, 5, tzinfo=timezone.utc)
        return fw.Offer(
            source="etilbudsavis",
            group_id="cheasy_skyr",
            group_label="Cheasy skyr",
            store=store,
            name=name,
            description="",
            price=24.0,
            valid_from=start,
            valid_until=start + timedelta(days=7),
            offer_id=offer_id,
            publication_id="p1",
            publication_label="Uge 36",
            url="https://etilbudsavis.dk/x",
            image="",
        )

    def test_current_and_upcoming_have_independent_dedupe(self):
        now = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
        current = self._offer()
        upcoming = self._offer(name="SEMPER Smoothie-mix", store="Lidl", start=now + timedelta(days=3), offer_id="o2")
        state = {"sent": {digest.phase_token(current, "upcoming"): {"sent_at": "x"}}}
        items = digest.pending_items([current, upcoming], state, now)
        self.assertEqual([(phase, offer.name) for phase, offer in items], [
            ("current", "Cheasy skyr"),
            ("upcoming", "SEMPER Smoothie-mix"),
        ])

    def test_same_phase_is_not_repeated(self):
        now = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
        offer = self._offer()
        state = {"sent": {digest.phase_token(offer, "current"): {"sent_at": "x"}}}
        self.assertEqual(digest.pending_items([offer], state, now), [])

    def test_same_logical_offer_is_not_repeated_when_source_key_changes(self):
        now = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
        offer = self._offer(name="Cheasy skyr eller Matilde kakaomælk*", store="365discount")
        state = {
            "sent": {
                "manual|365discount|cheasy-skyr-eller-matilde-kakaomaelk|2026-09-05|current": {
                    "sent_at": "2026-09-05T11:00:30Z",
                    "phase": "current",
                    "store": "365discount",
                    "name": "Cheasy skyr eller Matilde kakaomælk*",
                    "valid_from": offer.valid_from.isoformat().replace("+00:00", "Z"),
                    "valid_until": offer.valid_until.isoformat().replace("+00:00", "Z"),
                }
            }
        }
        self.assertEqual(digest.pending_items([offer], state, now), [])

    def test_digest_contains_official_link_and_period(self):
        now = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
        offer = self._offer()
        subject, body = digest.build_digest([("current", offer)], now)
        self.assertIn("1 nye tilbud", subject)
        self.assertIn("AKTUELLE TILBUD", body)
        self.assertIn("Gælder: 5/9–12/9", body)
        self.assertIn("https://www.bilka.dk/bilkaavisen/", body)
        self.assertNotIn("etilbudsavis.dk", body)


if __name__ == "__main__":
    unittest.main()
