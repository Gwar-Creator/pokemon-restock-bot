"""Offline tests for low-noise, non-Discord vintage lot shortlist."""
import unittest
from datetime import datetime, timezone

from vintage_marketplace_shortlist import pick_title, propose_shortlist, internal_preview

T = datetime(2026, 10, 28, 19, 0, tzinfo=timezone.utc)


def row(ident, title):
    return {"id": ident, "shortDescription": title,
            "itemUrl": f"http://www.tradera.com/item/1001342/{ident}/some-lot"}


class VintageShortlistTests(unittest.TestCase):
    def test_high_value_vintage_title_lots_are_discovery_only(self):
        examples = (
            "Pokemon kort lot vintage WotC 10 st",
            "Pokemon Gym Heroes lot 11 st",
            "Pokemon e-card Expedition Aquapolis samling",
            "Pokemon barndomssamling med gamla ex series kort",
            "Stor samling med gamla Pokemonkort",
        )
        for index, title in enumerate(examples, 1):
            with self.subTest(title=title):
                item = pick_title(row(index, title))
                self.assertIsNotNone(item)
                self.assertEqual(item["verification"], "UNVERIFIED")
                self.assertEqual(item["url"].split(":")[0], "https")
                preview = internal_preview(item)
                self.assertFalse(preview["discord_eligible"])
                self.assertIsNone(preview["buy_bid_signal"])

    def test_modern_bulk_sealed_language_and_singles_suppressed(self):
        titles = (
            "Pokemon Fossil Kingler 38/62",
            "Pokemon 151 bulk samling",
            "Pokemon vintage booster box lot",
            "Pokemon VMAX lot samling",
            "Lorcana WotC samling",
            "Pokemon proxy jungle lot",
            "Pokemon samling med blandade kort",  # no vintage proof
            "Pokemon Fossil Egg collection",
            "Pokemon Gym Heroes lot japanska kort",
        )
        for index, title in enumerate(titles, 10):
            with self.subTest(title=title):
                self.assertIsNone(pick_title(row(index, title)))

    def test_invalid_links_and_ids_fail_closed(self):
        self.assertIsNone(pick_title({"id": 1, "shortDescription": "Pokemon Gym Heroes lot",
                                      "itemUrl": "http://tradera.com.evil.invalid/1"}))
        self.assertIsNone(pick_title({"id": True, "shortDescription": "Pokemon WotC lot",
                                      "itemUrl": "https://tradera.com/item/1"}))

    def test_initial_baseline_no_sends(self):
        rows = [row(101, "Pokemon WotC lot"), row(102, "Pokemon Jungle samling")]
        state, selected, baseline = propose_shortlist(rows, now=T)
        self.assertTrue(baseline)
        self.assertEqual(selected, [])
        self.assertEqual(len(state["seen"]), 2)

        after, again, baseline = propose_shortlist(rows, state, T)
        self.assertFalse(baseline)
        self.assertEqual(again, [])
        self.assertEqual(after["sent_at"], [])

    def test_dedupe_and_run_daily_weekly_limits(self):
        state, _, _ = propose_shortlist([row(1, "Pokemon WotC lot")], now=T)
        rows = [row(i, "Pokemon Gym Heroes lot") for i in range(2, 14)]
        state, selected, baseline = propose_shortlist(rows, state, T)
        self.assertFalse(baseline)
        self.assertEqual(len(selected), 3)
        self.assertEqual(len({x["id"] for x in selected}), 3)
        state, again, _ = propose_shortlist(rows, state, T)
        self.assertEqual(again, [])
        more = [row(i, "Pokemon Aquapolis samling") for i in range(20, 30)]
        state, later, _ = propose_shortlist(more, state, T)
        self.assertEqual(later, [])
        tomorrow = datetime(2026, 10, 29, 19, tzinfo=timezone.utc)
        state, picked, _ = propose_shortlist([row(i, "Pokemon Fossil samling")
                                                for i in range(50, 60)], state, tomorrow)
        self.assertEqual(len(picked), 3)
        days_later = datetime(2026, 10, 30, 19, tzinfo=timezone.utc)
        state, picked, _ = propose_shortlist([row(i, "Pokemon WotC samling")
                                                for i in range(70, 80)], state, days_later)
        self.assertEqual(len(picked), 2)

    def test_no_secret_or_purchase_fields_in_preview(self):
        candidate = pick_title(row(789, "Pokemon Gym Challenge samling"))
        candidate["private_secret"] = "DO_NOT_LEAK"
        payload = internal_preview(candidate)
        self.assertNotIn("DO_NOT_LEAK", str(payload))
        self.assertNotIn("price", str(payload).lower())
        self.assertEqual(payload["status"], "UNVERIFIED_MANUAL_REVIEW")


if __name__ == "__main__":
    unittest.main()
