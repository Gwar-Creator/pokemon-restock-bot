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
        self.assertEqual(live[1], "UNKNOWN")
        embed = live[0]["embeds"][0]
        self.assertEqual(embed["title"], "UKENDT · PROSHOP")
        self.assertNotIn("url", embed)
        self.assertIn("BESTILLINGSVARE", str(embed["fields"]))
        self.assertIn("IKKE LAGER-RESTOCK", str(embed["fields"]))
        preserved = self._p(stock="PÅ LAGER", fetch_via="preserved_previous_scan")
        self.assertEqual(hot_payload("proshop", preserved, "RESTOCK")[1], "UNKNOWN")

    def test_salling_online_stock_is_never_confirmed_checkout(self):
        for source in ("br", "bilka", "foetex"):
            for exposed in (None, True, False):
                product = self._p(online_count=8, is_exposed=exposed)
                payload, status = hot_payload(source, product, "RESTOCK")
                expected = "PREPUBLISH" if exposed is False else "UNKNOWN"
                with self.subTest(source=source, exposed=exposed):
                    self.assertEqual(status, expected)
                    embed = payload["embeds"][0]
                    self.assertNotIn("url", embed)
                    self.assertNotIn("KØB NU", embed["title"])
                    self.assertIn("IKKE VERIFICERET RESTOCK", str(embed["fields"]))
                    self.assertIn("ikke bekræftet", str(embed["fields"]).lower())

    def test_salling_local_stock_only_is_not_hot(self):
        # Physical shop counts belong to Local Stock and must not leak into
        # an online-only HOT embed.
        product = self._p(online_count=0, kolding_stock=4, esbjerg_stock=0)
        payload, status = hot_payload("br", product, "NEW")
        self.assertEqual(status, "UNKNOWN")
        self.assertNotIn("url", payload["embeds"][0])
        self.assertNotIn("BR Kolding: 4 stk.", str(payload["embeds"][0]["fields"]))

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


    def test_live_mode_proshop_order_item_is_neutral_not_restock(self):
        product = self._p(stock="BESTILLINGSVARE")
        with patch.object(hot, "DISCORD_V2_HOT_MODE", "on"), \
             patch.object(hot, "WEBHOOK_URL", "https://example.invalid/webhook"), \
             patch.object(hot, "HOT_DRY_RUN", False), \
             patch.object(hot.requests, "post") as post:
            self.assertTrue(hot.send_hot_alert("proshop", product, "RESTOCK"))
        self.assertEqual(post.call_count, 1)
        embed = post.call_args.kwargs["json"]["embeds"][0]
        self.assertEqual(embed["title"], "UKENDT · PROSHOP")
        self.assertNotIn("url", embed)
        self.assertIn("BESTILLINGSVARE", str(embed["fields"]))
        self.assertIn("IKKE LAGER-RESTOCK", str(embed["fields"]))
        self.assertEqual(post.call_args.kwargs["json"]["allowed_mentions"], {"parse": []})

    def test_preserved_composite_proshop_source_cannot_go_green(self):
        product = self._p(stock="PÅ LAGER", fetch_via="jina_reader+preserved_previous_scan")
        self.assertEqual(hot_payload("proshop", product, "RESTOCK")[1], "UNKNOWN")

    def test_order_only_live_mode_does_not_create_second_post(self):
        product = self._p(stock="BESTILLINGSVARE", fetch_via="jina_reader")
        with (
            patch.object(hot, "DISCORD_V2_HOT_MODE", "on"),
            patch.object(hot, "WEBHOOK_URL", "https://example.invalid/webhook"),
            patch.object(hot, "HOT_DRY_RUN", False),
            patch.object(hot.requests, "post") as post,
        ):
            self.assertTrue(hot.send_hot_alert("proshop", product, "NEW"))
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["json"]["embeds"][0]["title"],
                         "UKENDT · PROSHOP")

    def test_explicit_proshop_preorder_keeps_purple_label(self):
        product = self._p(stock="BESTILLINGSVARE", preorder=True)
        self.assertEqual(hot_payload("proshop", product, "NEW")[1], "PREORDER")
        with (
            patch.object(hot, "DISCORD_V2_HOT_MODE", "on"),
            patch.object(hot, "WEBHOOK_URL", "https://example.invalid/webhook"),
            patch.object(hot, "HOT_DRY_RUN", False),
            patch.object(hot.requests, "post") as post,
        ):
            self.assertTrue(hot.send_hot_alert("proshop", product, "NEW"))
        self.assertEqual(post.call_count, 1)
        embed = post.call_args.kwargs["json"]["embeds"][0]
        self.assertEqual(embed["title"], "FORUDBESTIL · PROSHOP")

    def test_live_salling_hot_online_signal_does_not_show_local_stock(self):
        for source in ("br", "bilka", "foetex"):
            local = (
                {"kolding_stock": 2} if source == "br"
                else {"local_stocks": {"1": {"name": "Kolding", "stock": 2}}}
            )
            product = self._p(online_count=15, is_exposed=True, **local)
            with (
                patch.object(hot, "DISCORD_V2_HOT_MODE", "on"),
                patch.object(hot, "WEBHOOK_URL", "https://example.invalid/webhook"),
                patch.object(hot, "HOT_DRY_RUN", False),
                patch.object(hot.requests, "post") as post,
            ):
                self.assertTrue(hot.send_hot_alert(source, product, "RESTOCK"))
            with self.subTest(source=source):
                self.assertEqual(post.call_count, 1)
                payload = post.call_args.kwargs["json"]
                embed = payload["embeds"][0]
                title_source = source.upper() if source != "foetex" else "FØTEX"
                self.assertEqual(embed["title"], f"UKENDT · {title_source}")
                self.assertEqual(embed["color"], 0x95A5A6)
                self.assertNotIn("url", embed)
                self.assertIn("ONLINE SYSTEMLAGER", str(embed["fields"]))
                self.assertNotIn("REGISTRERET BUTIKSLAGER", str(embed["fields"]))
                self.assertEqual(payload["allowed_mentions"], {"parse": []})

    def test_live_salling_system_only_is_neutral_not_green(self):
        product = self._p(online_count=15, is_exposed=True)
        with (
            patch.object(hot, "DISCORD_V2_HOT_MODE", "on"),
            patch.object(hot, "WEBHOOK_URL", "https://example.invalid/webhook"),
            patch.object(hot, "HOT_DRY_RUN", False),
            patch.object(hot.requests, "post") as post,
        ):
            self.assertTrue(hot.send_hot_alert("br", product, "RESTOCK"))
        self.assertEqual(post.call_count, 1)
        embed = post.call_args.kwargs["json"]["embeds"][0]
        self.assertEqual(embed["title"], "UKENDT · BR")
        self.assertEqual(embed["color"], 0x95A5A6)
        self.assertNotIn("url", embed)

    def test_live_hidden_salling_uses_prepublish_yellow(self):
        product = self._p(online_count=15, is_exposed=False, kolding_stock=3)
        with (
            patch.object(hot, "DISCORD_V2_HOT_MODE", "on"),
            patch.object(hot, "WEBHOOK_URL", "https://example.invalid/webhook"),
            patch.object(hot, "HOT_DRY_RUN", False),
            patch.object(hot.requests, "post") as post,
        ):
            self.assertTrue(hot.send_hot_alert("br", product, "RESTOCK"))
        self.assertEqual(post.call_count, 1)
        embed = post.call_args.kwargs["json"]["embeds"][0]
        self.assertEqual(embed["title"], "KLARGØRES · BR")
        self.assertEqual(embed["color"], 0xF1C40F)
        self.assertNotIn("url", embed)

    def test_live_salling_renderer_failure_stays_neutral(self):
        product = self._p(online_count=15, is_exposed=True)
        with (
            patch.object(hot, "DISCORD_V2_HOT_MODE", "on"),
            patch.object(hot, "WEBHOOK_URL", "https://example.invalid/webhook"),
            patch.object(hot, "HOT_DRY_RUN", False),
            patch.object(hot, "hot_payload", side_effect=ValueError("unexpected")),
            patch.object(hot.requests, "post") as post,
        ):
            self.assertTrue(hot.send_hot_alert("br", product, "RESTOCK"))
        self.assertEqual(post.call_count, 1)
        embed = post.call_args.kwargs["json"]["embeds"][0]
        self.assertEqual(embed["title"], "UKENDT · BR")
        self.assertEqual(embed["color"], 0x95A5A6)
        self.assertNotIn("url", embed)
        self.assertNotIn("Se produkt", str(embed))

    def test_salling_unexpected_buy_now_renderer_result_is_blocked(self):
        product = self._p(online_count=15, is_exposed=True)
        unsafe = {"embeds": [{
            "title": "KØB NU · BR", "color": 0x57F287,
            "url": URL, "fields": [],
        }]}
        with (
            patch.object(hot, "DISCORD_V2_HOT_MODE", "on"),
            patch.object(hot, "WEBHOOK_URL", "https://example.invalid/webhook"),
            patch.object(hot, "HOT_DRY_RUN", False),
            patch.object(hot, "hot_payload", return_value=(unsafe, "BUY_NOW")),
            patch.object(hot.requests, "post") as post,
        ):
            self.assertTrue(hot.send_hot_alert("br", product, "RESTOCK"))
        self.assertEqual(post.call_count, 1)
        embed = post.call_args.kwargs["json"]["embeds"][0]
        self.assertEqual(embed["title"], "UKENDT · BR")
        self.assertNotIn("url", embed)

    def test_salling_cached_store_counts_are_not_promoted(self):
        product = self._p(
            online_count=15, is_exposed=True, kolding_stock=9,
            fetch_via="jina_reader+preserved_previous_scan",
        )
        payload, status = hot_payload("br", product, "RESTOCK")
        self.assertEqual(status, "UNKNOWN")
        embed = payload["embeds"][0]
        self.assertNotIn("REGISTRERET BUTIKSLAGER", str(embed["fields"]))
        self.assertIn("tidligere scanning", str(embed["fields"]))

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
