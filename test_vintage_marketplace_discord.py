"""No-send preview rules for the existing marketplace-deals channel."""
import unittest
from vintage_marketplace_discord import candidate_embed, preview_payload


class MarketplaceDealsPreviewTests(unittest.TestCase):
    def test_interesting_vintage_card_uses_existing_channel_label(self):
        c = {
            "id": "123", "priority": "REVIEW_HIGH",
            "title": "Pokemon Aquapolis samling",
            "url": "https://www.tradera.com/item/11/123",
            "price_sek": 2,
        }
        payload = preview_payload([c])
        self.assertEqual(len(payload["embeds"]), 1)
        embed = payload["embeds"][0]
        self.assertIn("#marketplace-deals", embed["footer"]["text"])
        self.assertIn("TIL GENNEMGANG", embed["title"])
        self.assertNotIn("KØB NU", str(payload))
        self.assertNotIn("god handel", str(payload).lower())
        self.assertIn("ikke verificeret", str(payload).lower())
        self.assertEqual(payload["allowed_mentions"], {"parse": []})

    def test_non_vintage_and_missing_public_link_do_not_create_draft(self):
        rows = [
            {"id": "1", "priority": "SKIP", "url": "https://www.tradera.com/item/1"},
            {"id": "2", "priority": "REVIEW", "url": ""},
            {"id": "3", "priority": "REVIEW", "url": "https://example.invalid/item"},
            {"id": "4", "priority": "REVIEW", "url": "https://www.tradera.com/item/4", "title": "Pokemon samling"},
        ]
        self.assertEqual(len(preview_payload(rows)["embeds"]), 1)

    def test_dedupe_and_cap(self):
        rows = [
            {"id": str(i), "priority": "REVIEW", "title": "Pokemon old collection",
             "url": "https://www.tradera.com/item/" + str(i)}
            for i in range(10)
        ]
        self.assertEqual(len(preview_payload(rows + [rows[0]])["embeds"]), 4)
        self.assertEqual(len(preview_payload(rows, limit=1)["embeds"]), 1)
        self.assertEqual(len(preview_payload(rows, limit=0)["embeds"]), 0)

    def test_invalid_candidate_not_reported_as_good_buy(self):
        with self.assertRaises(ValueError):
            candidate_embed({"priority": "REVIEW", "url": ""})
        with self.assertRaises(ValueError):
            candidate_embed({"priority": "BUY_NOW", "url": "https://www.tradera.com/item/1"})


if __name__ == "__main__":
    unittest.main()
