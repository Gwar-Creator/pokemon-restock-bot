"""Unit tests for source-aware HOT Discord V2 shadow adapter."""
import unittest
from unittest.mock import patch

import hot_restock as hot

from discord_v2_hot_adapter import hot_event, hot_payload


URL = "https://example.org/pokemon/product"


class HotDiscordV2AdapterTests(unittest.TestCase):
    def _p(self, **extras):
        return {"name": "Pokémon Booster Bundle", "price": 249, "url": URL, **extras}

    def test_coolshop_verified_online(self):
        self.assertEqual(hot_payload("coolshop", self._p(online_stock=True), "RESTOCK")[1], "BUY_NOW")
        self.assertEqual(hot_payload("coolshop", self._p(online_stock=False), "RESTOCK")[1], "UNKNOWN")

    def test_proshop_orderable_but_cached_cannot_go_green(self):
        live = hot_payload("proshop", self._p(stock="BESTILLINGSVARE"), "NEW")
        self.assertEqual(live[1], "BUY_NOW")
        self.assertIn("BESTILLINGSVARE", str(live[0]["embeds"][0]["fields"]))
        preserved = self._p(stock="PÅ LAGER", fetch_via="preserved_previous_scan")
        self.assertEqual(hot_payload("proshop", preserved, "RESTOCK")[1], "UNKNOWN")

    def test_salling_online_stock_needs_explicit_exposure(self):
        self.assertEqual(hot_payload("br", self._p(online_count=8), "RESTOCK")[1], "UNKNOWN")
        self.assertEqual(hot_payload("br", self._p(online_count=8, is_exposed=True), "RESTOCK")[1], "BUY_NOW")

    def test_salling_local_stock_only_is_orange(self):
        product = self._p(online_count=0, kolding_stock=4, esbjerg_stock=0)
        payload, status = hot_payload("br", product, "NEW")
        self.assertEqual(status, "STORE_STOCK")
        self.assertNotIn("url", payload["embeds"][0])
        self.assertIn("BR Kolding: 4 stk.", str(payload["embeds"][0]["fields"]))

    def test_hidden_salling_stock_is_yellow(self):
        product = self._p(is_exposed=False, online_count=10, kolding_stock=6)
        self.assertEqual(hot_payload("br", product, "NEW")[1], "PREPUBLISH")

    def test_prepublish_with_preorder_is_not_live_buyable(self):
        self.assertEqual(hot_payload("br", self._p(is_exposed=False, preorder=True), "PREORDER")[1], "PREPUBLISH")

    def test_preorder_is_purple(self):
        self.assertEqual(hot_payload("br", self._p(preorder=True), "NEW")[1], "PREORDER")

    def test_untrusted_negative_stock_does_not_create_store_alert(self):
        event = hot_event("bilka", self._p(local_stocks={
            "2": {"name": "Bilka Kolding", "stock": -1},
            "3": {"name": "Bilka Esbjerg", "stock": 0},
        }), "RESTOCK")
        self.assertEqual(event["stores"], [])

    def test_mentions_never_enabled(self):
        self.assertEqual(hot_payload("coolshop", self._p(online_stock=True), "RESTOCK")[0]["allowed_mentions"], {"parse": []})


    def test_shadow_posts_original_embed_only(self):
        product = self._p(online_stock=True)
        with patch.object(hot, "DISCORD_V2_HOT_MODE", "shadow"), \
             patch.object(hot, "HOT_DRY_RUN", False), \
             patch.object(hot, "WEBHOOK_URL", "https://example.invalid/webhook"), \
             patch.object(hot.requests, "post") as post:
            self.assertTrue(hot.send_hot_alert("coolshop", product, "RESTOCK"))
        self.assertEqual(post.call_count, 1)
        embed = post.call_args.kwargs["json"]["embeds"][0]
        self.assertEqual(embed["title"], "RESTOCK · COOLSHOP")

    def test_enabled_posts_v2_embed_only(self):
        product = self._p(online_stock=True)
        with patch.object(hot, "DISCORD_V2_HOT_MODE", "on"), \
             patch.object(hot, "HOT_DRY_RUN", False), \
             patch.object(hot, "WEBHOOK_URL", "https://example.invalid/webhook"), \
             patch.object(hot.requests, "post") as post:
            self.assertTrue(hot.send_hot_alert("coolshop", product, "RESTOCK"))
        self.assertEqual(post.call_count, 1)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["embeds"][0]["title"], "KØB NU · COOLSHOP")
        self.assertEqual(payload["allowed_mentions"], {"parse": []})


    def test_live_mode_keeps_legacy_proshop_order_item(self):
        product = self._p(stock="BESTILLINGSVARE")
        with patch.object(hot, "DISCORD_V2_HOT_MODE", "on"), \
             patch.object(hot, "WEBHOOK_URL", "https://example.invalid/webhook"), \
             patch.object(hot, "HOT_DRY_RUN", False), \
             patch.object(hot.requests, "post") as post:
            self.assertTrue(hot.send_hot_alert("proshop", product, "RESTOCK"))
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["json"]["embeds"][0]["title"],
                         "RESTOCK · PROSHOP")

    def test_live_mode_keeps_legacy_salling_system_stock(self):
        product = self._p(online_count=15, kolding_stock=2)
        with patch.object(hot, "DISCORD_V2_HOT_MODE", "on"), \
             patch.object(hot, "WEBHOOK_URL", "https://example.invalid/webhook"), \
             patch.object(hot, "HOT_DRY_RUN", False), \
             patch.object(hot.requests, "post") as post:
            self.assertTrue(hot.send_hot_alert("br", product, "RESTOCK"))
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["json"]["embeds"][0]["title"],
                         "RESTOCK · BR")

    def test_live_proshop_in_stock_requires_fresh_source(self):
        product = self._p(stock="PÅ LAGER", fetch_via="jina_reader")
        with patch.object(hot, "DISCORD_V2_HOT_MODE", "on"), \
             patch.object(hot, "WEBHOOK_URL", "https://example.invalid/webhook"), \
             patch.object(hot, "HOT_DRY_RUN", False), \
             patch.object(hot.requests, "post") as post:
            self.assertTrue(hot.send_hot_alert("proshop", product, "RESTOCK"))
        embed = post.call_args.kwargs["json"]["embeds"][0]
        self.assertEqual(embed["title"], "KØB NU · PROSHOP")
        self.assertIn("HÆNDELSE", [x["name"] for x in embed["fields"]])


if __name__ == "__main__":
    unittest.main()
