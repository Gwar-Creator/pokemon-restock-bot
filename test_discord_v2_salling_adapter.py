"""Conservative shadow classification for Salling Local, Hidden and Early."""
import unittest
from unittest.mock import Mock, patch

import discord_v2_salling_adapter as adapter
import local_stock_watch as local
import hidden_stock_watch as hidden
import salling_early_radar as radar


URL = "https://www.br.dk/produkter/test/123/"


class SallingV2ShadowTests(unittest.TestCase):
    def test_local_visible_store_stock_is_orange_not_green(self):
        event = adapter.local_stock_event(
            {"site": "BR", "name": "Booster Bundle", "url": URL,
             "price": 249, "visibility": "EXPOSED"},
            [{"name": "BR Kolding", "old": 0, "new": 5}],
        )
        self.assertEqual(adapter.classify(event), "STORE_STOCK")
        self.assertNotIn("url", adapter.preview_payload(event)["embeds"][0])

    def test_local_hidden_is_yellow_even_with_stock(self):
        event = adapter.local_stock_event(
            {"site": "BILKA", "name": "Collection", "url": URL,
             "visibility": "PRE-PUBLISH"},
            [{"name": "Bilka Kolding", "new": 12}],
        )
        self.assertEqual(adapter.classify(event), "PREPUBLISH")
        self.assertNotIn("url", adapter.preview_payload(event)["embeds"][0])

    def test_local_unknown_visibility_does_not_infer_online(self):
        event = adapter.local_stock_event(
            {"site": "FØTEX", "name": "Collection", "visibility": "UNKNOWN",
             "online_count": 200, "url": URL},
            [{"name": "føtex Esbjerg", "new": 2}],
        )
        self.assertEqual(adapter.classify(event), "STORE_STOCK")
        self.assertFalse(event["online_buyable"])

    def test_hidden_keeps_only_passed_approved_stores(self):
        rows = [{"site": "br", "name": "Collection", "store": "BR Kolding",
                 "stock": 4, "price": 450, "url": URL}]
        event = adapter.hidden_stock_event(rows)
        self.assertEqual(adapter.classify(event), "PREPUBLISH")
        payload = adapter.preview_payload(event)
        self.assertIn("BR Kolding", str(payload))
        self.assertNotIn("url", payload["embeds"][0])

    def test_hidden_requires_rows(self):
        with self.assertRaises(ValueError):
            adapter.hidden_stock_event([])

    def test_early_hidden_catalog_not_live(self):
        event = adapter.early_radar_event(
            "NY SKJULT VARE",
            {"name": "Vintage Collection", "sites": {
                "br": {"is_exposed": False, "store_count": 91, "online_count": 141,
                       "url": URL, "price": 349}}},
            "Katalogfund", "br",
        )
        self.assertEqual(adapter.classify(event), "PREPUBLISH")

    def test_early_exposed_catalog_not_buyable(self):
        event = adapter.early_radar_event(
            "SYNLIGT PRODUKT",
            {"name": "Bundle", "sites": {
                "bilka": {"is_exposed": True, "online_count": 10, "url": URL}}},
            "Katalogændring", "bilka",
        )
        self.assertEqual(adapter.classify(event), "UNKNOWN")

    def test_shadow_does_not_modify_events(self):
        product = {"site": "BR", "name": "Box", "visibility": "EXPOSED"}
        transitions = [{"name": "BR Kolding", "old": 0, "new": 1}]
        original = (dict(product), [dict(x) for x in transitions])
        event = adapter.local_stock_event(product, transitions)
        adapter.shadow_line("LOCAL", event)
        self.assertEqual(product, original[0])
        self.assertEqual(transitions, original[1])

    def test_local_sender_unchanged_one_post(self):
        product = {"site": "BR", "name": "Test Collection", "type": "COLLECTION",
                   "price": 449, "url": URL, "visibility": "EXPOSED"}
        response = Mock()
        with patch.object(local, "WEBHOOK_URL", "https://example.invalid/webhook"), \
             patch.object(local, "local_stock_signal_allowed", return_value=True), \
             patch.object(local.requests, "post", return_value=response) as post:
            local.send_local_alert(product, [{"name": "BR Kolding", "old": 0, "new": 4}])
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["json"]["embeds"][0]["title"],
                         "LOKALT LAGER · BR")

    def test_hidden_sender_unchanged_one_post(self):
        row = {"site": "br", "name": "Test Collection", "store": "BR Kolding",
               "stock": 4, "price": 200, "product_id": "1", "sku": "2"}
        response = Mock()
        with patch.object(hidden, "WEBHOOK", "https://example.invalid/webhook"), \
             patch.object(hidden.requests, "post", return_value=response) as post:
            hidden.send_alert([row])
        self.assertEqual(post.call_count, 1)
        self.assertIn("PRE-PUBLISH", post.call_args.kwargs["json"]["embeds"][0]["title"])

    def test_early_sender_unchanged_one_post(self):
        response = Mock()
        sample = {"name": "Test", "price": 225, "id": "123", "sku": "ABC",
                  "priority": "NORMAL", "sites": {"br": {"is_exposed": False,
                  "url": URL, "online_count": 1}}}
        with patch.dict("os.environ", {"DISCORD_WEBHOOK_URL": "https://example.invalid/webhook"}), \
             patch.object(radar.requests, "post", return_value=response) as post:
            radar.send_alert("NY SKJULT VARE", sample, "Katalogfund", "br")
        self.assertEqual(post.call_count, 1)
        self.assertIn("content", post.call_args.kwargs["json"])


    def test_enabled_local_posts_one_orange_v2_card_with_transition(self):
        product = {"site": "BR", "name": "Test Collection", "type": "COLLECTION",
                   "price": 449, "url": URL, "visibility": "EXPOSED", "sku": "ABC"}
        response = Mock()
        with patch.dict("os.environ", {"DISCORD_V2_LOCAL_MODE": "on"}), \
             patch.object(local, "WEBHOOK_URL", "https://example.invalid/webhook"), \
             patch.object(local, "local_stock_signal_allowed", return_value=True), \
             patch.object(local.requests, "post", return_value=response) as post:
            local.send_local_alert(product, [{"name": "BR Kolding", "old": 0, "new": 4}])
        self.assertEqual(post.call_count, 1)
        embed = post.call_args.kwargs["json"]["embeds"][0]
        self.assertEqual(embed["title"], "BUTIKSLAGER · BR")
        self.assertIn("0 → 4", str(embed["fields"]))
        self.assertNotIn("url", embed)

    def test_enabled_hidden_posts_one_yellow_card_local_only(self):
        local_row = {"site": "br", "name": "Test Collection", "store": "BR Kolding",
                     "stock": 4, "price": 200, "product_id": "1", "sku": "ABC"}
        remote_row = {**local_row, "store": "BR Viborg", "stock": 9}
        response = Mock()
        with patch.dict("os.environ", {"DISCORD_V2_HIDDEN_MODE": "on"}), \
             patch.object(hidden, "WEBHOOK", "https://example.invalid/webhook"), \
             patch.object(hidden.requests, "post", return_value=response) as post:
            hidden.send_alert([remote_row, local_row])
        self.assertEqual(post.call_count, 1)
        embed = post.call_args.kwargs["json"]["embeds"][0]
        self.assertEqual(embed["title"], "KLARGØRES · BR")
        self.assertNotIn("Viborg", str(embed))
        self.assertIn("Kolding", str(embed))
        self.assertIn("To på hinanden", str(embed))
        self.assertNotIn("url", embed)

    def test_enabled_early_posts_one_yellow_embed_not_plain_text(self):
        product = {"name": "Test", "price": 225, "id": "123", "sku": "ABC",
                   "priority": "NORMAL", "sites": {"br": {
                       "is_exposed": False, "url": URL, "online_count": 1}}}
        response = Mock()
        with patch.dict("os.environ", {
                     "DISCORD_WEBHOOK_URL": "https://example.invalid/webhook",
                     "DISCORD_V2_EARLY_MODE": "on",
                 }), patch.object(radar.requests, "post", return_value=response) as post:
            radar.send_alert("NY SKJULT VARE", product, "Katalogfund", "br")
        self.assertEqual(post.call_count, 1)
        data = post.call_args.kwargs["json"]
        self.assertNotIn("content", data)
        self.assertEqual(data["embeds"][0]["title"],
                         "KLARGØRES · SALLING EARLY RADAR")
        self.assertIn("Katalogfund", str(data["embeds"][0]))
        self.assertNotIn("url", data["embeds"][0])

    def test_early_exposure_is_from_relevant_retailer(self):
        data = {"name": "Box", "sites": {
            "br": {"is_exposed": False, "url": URL},
            "bilka": {"is_exposed": True, "url": URL},
        }}
        self.assertEqual(adapter.classify(
            adapter.early_radar_event("METADATA", data, "Test", "bilka")),
            "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
