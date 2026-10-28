import unittest

from discord_alert_v2 import STATUS, classify, format_price, render_embed, safe_url, webhook_payload


class DiscordV2StatusTests(unittest.TestCase):
    def test_unverified_in_stock_is_not_a_buy_alert(self):
        self.assertEqual(classify({"in_stock": True, "url": "https://example.org/item"}), "UNKNOWN")

    def test_verified_online_requires_public_url(self):
        self.assertEqual(classify({"online_buyable": True}), "UNKNOWN")
        self.assertEqual(classify({"online_buyable": True, "url": "https://example.org/item"}), "BUY_NOW")

    def test_reservation_requires_store_and_url(self):
        sample = {"click_collect_reservable": True, "stores": [{"name": "BR Kolding", "stock": 2}]}
        self.assertEqual(classify(sample), "STORE_STOCK")
        sample["url"] = "https://example.org/item"
        self.assertEqual(classify(sample), "RESERVE_NOW")

    def test_store_stock_is_not_confirmed_buyability(self):
        sample = {"stores": [{"name": "Bilka Kolding", "stock": 12}], "url": "https://example.org/item"}
        self.assertEqual(classify(sample), "STORE_STOCK")
        self.assertNotIn("url", render_embed(sample))

    def test_prepublish_stock_does_not_claim_buyable(self):
        sample = {"is_pre_publish": True, "stores": [{"name": "BR Kolding", "stock": 12}]}
        self.assertEqual(classify(sample), "PREPUBLISH")
        self.assertIn("ikke dokumentation", str(render_embed(sample)["fields"]))

    def test_conflicting_purchase_evidence_is_unknown(self):
        sample = {"is_pre_publish": True, "online_buyable": True, "url": "https://example.org/item"}
        self.assertEqual(classify(sample), "UNKNOWN")
        self.assertEqual(classify({"preorder_open": True, "online_buyable": True, "url": sample["url"]}), "UNKNOWN")

    def test_preorder_is_not_restock(self):
        self.assertEqual(classify({"preorder_open": True, "url": "https://example.org/item"}), "PREORDER")

    def test_bad_urls_and_bad_prices(self):
        self.assertEqual(safe_url("javascript:alert(1)"), "")
        self.assertEqual(safe_url("https://somewhere.invalid/path with spaces"), "")
        self.assertEqual(format_price(float("nan")), "")
        self.assertEqual(format_price(0), "")
        self.assertEqual(format_price(1599), "1.599,00 kr.")

    def test_no_phantom_stock_and_mention_protection(self):
        sample = {"name": "Test", "source": "BR", "stores": [{"name": "A", "stock": -5}, {"name": "B", "stock": 0}, {"name": "C", "stock": "x"}]}
        self.assertEqual(classify(sample), "UNKNOWN")
        self.assertEqual(webhook_payload(sample)["allowed_mentions"], {"parse": []})

    def test_six_statuses_are_distinct(self):
        self.assertEqual(len(STATUS), 6)
        self.assertEqual(len({v[1] for v in STATUS.values()}), 6)

    def test_store_list_is_bounded(self):
        event = {"stores": [{"name": f"Store {i}", "stock": 1} for i in range(30)]}
        fields = render_embed(event)["fields"]
        self.assertTrue(all(len(str(field["value"])) <= 1024 for field in fields))
        self.assertIn("18 yderligere", str(fields))


if __name__ == "__main__":
    unittest.main()
