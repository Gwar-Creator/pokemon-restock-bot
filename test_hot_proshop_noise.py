"""Regression tests for Proshop duplicate Discord notifications."""

import time
import unittest
from unittest.mock import patch

import hot_restock as hot
import hot_restock_v4 as hot_v4


def proshop_product(stock="PÅ LAGER"):
    return {
        "name": "Pokemon TCG Mega Greninja ex Premium Collection",
        "game": "POKÉMON",
        "price": 499.0,
        "stock": stock,
        "url": "https://www.proshop.dk/Pokemon/Pokemon-TCG-Mega-Greninja-ex-Premium-Collection/3478496",
    }


class ProshopNoiseTests(unittest.TestCase):
    def setUp(self):
        mock = patch.object(
            hot, "extend_with_known_details",
            side_effect=lambda current, old, state: current,
        )
        mock.start()
        self.addCleanup(mock.stop)

    def test_bestillingsvare_to_in_stock_is_not_restock(self):
        self.assertTrue(hot.product_available("proshop", proshop_product("BESTILLINGSVARE")))
        self.assertTrue(hot.product_available("proshop", proshop_product("PÅ LAGER")))
        self.assertFalse(hot.product_available("proshop", proshop_product("UKENDT")))
        self.assertFalse(hot.product_available("proshop", proshop_product("UDSOLGT")))

    def test_missing_proshop_product_retained_to_avoid_false_new(self):
        old = {"3478496": proshop_product("PÅ LAGER")}
        merged = hot._preserve_missing_proshop_products(old, {})
        self.assertEqual(merged["3478496"]["stock"], "PÅ LAGER")
        self.assertEqual(merged["3478496"]["fetch_via"], "preserved_previous_scan")
        self.assertEqual(old["3478496"].get("fetch_via"), None)

    def test_discovery_reappearance_does_not_generate_new_alert(self):
        state = {
            "sources": {"proshop": {"3478496": proshop_product()}},
            "source_controls": {},
            "proshop_discovery_version": hot.PROSHOP_DISCOVERY_VERSION,
        }
        response = [
            {},  # Unstable Proshop search omits the already-known SKU.
            {"3478496": proshop_product("BESTILLINGSVARE")},
            {"3478496": proshop_product("PÅ LAGER")},
        ]
        shared = {"restock_alert_allowed": lambda product, game: True}
        with patch.object(hot, "SOURCE_LABELS", {"proshop": "PROSHOP"}), \
             patch.object(hot, "_fetch_expanded_proshop_products", side_effect=response), \
             patch.object(hot, "save_state"), \
             patch.object(hot, "send_hot_alert") as sender:
            for _ in response:
                hot.run_scan(shared, state)
        self.assertEqual(state["sources"]["proshop"]["3478496"]["stock"], "PÅ LAGER")
        sender.assert_not_called()

    def test_real_out_of_stock_to_in_stock_sends_one_alert(self):
        state = {
            "sources": {"proshop": {"3478496": proshop_product("UDSOLGT")}},
            "source_controls": {},
            "proshop_discovery_version": hot.PROSHOP_DISCOVERY_VERSION,
        }
        response = [
            {"3478496": proshop_product("PÅ LAGER")},
            {"3478496": proshop_product("UDSOLGT")},
            {"3478496": proshop_product("PÅ LAGER")},
        ]
        shared = {"restock_alert_allowed": lambda product, game: True}
        with patch.object(hot, "SOURCE_LABELS", {"proshop": "PROSHOP"}), \
             patch.object(hot, "_fetch_expanded_proshop_products", side_effect=response), \
             patch.object(hot, "save_state"), \
             patch.object(hot, "send_hot_alert", return_value=True) as sender:
            for _ in response:
                hot.run_scan(shared, state)
        self.assertEqual(sender.call_count, 1)
        self.assertIn("proshop:3478496", state["last_hot_alerts"])

    def test_known_two_pack_first_appearance_is_not_a_false_new_launch(self):
        state = {
            "sources": {"proshop": {"3421827": proshop_product()}},
            "source_controls": {},
            "proshop_discovery_version": hot.PROSHOP_DISCOVERY_VERSION,
        }
        known = {
            "name": "Pokemon TCG 2-pack Booster",
            "price": None,
            "stock": "PÅ LAGER",
            "url": hot.KNOWN_PRODUCTS["3478497"],
            "game": "POKÉMON",
        }
        shared = {"restock_alert_allowed": lambda product, game: True}
        with patch.object(hot, "SOURCE_LABELS", {"proshop": "PROSHOP"}), \
             patch.object(hot, "_fetch_expanded_proshop_products",
                          return_value={"3478497": known}), \
             patch.object(hot, "save_state"), \
             patch.object(hot, "send_hot_alert") as sender:
            hot.run_scan(shared, state)
        sender.assert_not_called()
        self.assertIn("3478497", state["sources"]["proshop"])

    def test_persisted_cooldown_expires(self):
        state = {"last_hot_alerts": {"proshop:3478496": 1000}}
        self.assertFalse(hot._hot_alert_allowed(state, "proshop", "3478496", now=1001))
        self.assertTrue(
            hot._hot_alert_allowed(
                state, "proshop", "3478496",
                now=1000 + hot.PROSHOP_ALERT_COOLDOWN_SECONDS,
            )
        )
        # Every source now uses the same persisted duplicate protection.
        self.assertFalse(hot._hot_alert_allowed(state, "proshop", "3478496", now=1001))
        self.assertTrue(hot._hot_alert_allowed(state, "br", "3478496", now=1001))
        across = {"last_hot_alerts": {"br:11406758-EA": 1000}}
        self.assertFalse(hot._hot_alert_allowed(across, "br", "11406758-EA", now=1001))
        self.assertTrue(hot._hot_alert_allowed(
            across, "br", "11406758-EA",
            now=1000 + hot.HOT_ALERT_COOLDOWN_SECONDS,
        ))

    def test_all_sources_save_successful_alert_history(self):
        stock = {"name": "Pokemon TCG", "online_count": 10}
        state = {}
        with patch.object(hot, "send_hot_alert", return_value=True):
            self.assertTrue(hot.maybe_send_hot_alert(
                state, "br", "11406758-EA", stock, "RESTOCK"))
            self.assertFalse(hot.maybe_send_hot_alert(
                state, "br", "11406758-EA", stock, "RESTOCK"))
        self.assertIn("br:11406758-EA", state["last_hot_alerts"])


class ProshopDiscoveryRadarTests(unittest.TestCase):
    @staticmethod
    def product(sku="3591111", stock="UKENDT", name="Pokemon ex Box Sylveon 30th Celebration"):
        return {
            "name": name,
            "url": f"https://www.proshop.dk/Pokemon/{name.replace(' ', '-')}/{sku}",
            "stock": stock, "fetch_via": "jina_broad_reader",
        }

    def test_new_unknown_sylveon_is_radar_not_verified_restock(self):
        product = self.product()
        self.assertEqual(hot._proshop_radar_event("3591111", product, None), "KATALOGFUND")
        self.assertFalse(hot_v4.online_lane_product_available("proshop", product))
        for stock in ("UKENDT", "BESTILLINGSVARE", "FJERNLAGER", "UDSOLGT"):
            self.assertEqual(hot._proshop_radar_event(
                "3591111", {**product, "stock": stock}, None), "KATALOGFUND")

    def test_existing_product_only_radar_if_order_state_changed(self):
        product = self.product(stock="BESTILLINGSVARE")
        self.assertEqual(hot._proshop_radar_event(
            "3591111", product, {"stock": "UDSOLGT"}), "BESTILLINGSVARE")
        self.assertEqual(hot._proshop_radar_event(
            "3591111", product, {"stock": "UKENDT"}), "BESTILLINGSVARE")
        self.assertIsNone(hot._proshop_radar_event(
            "3591111", product, {"stock": "BESTILLINGSVARE"}))
        self.assertIsNone(hot._proshop_radar_event(
            "3591111", product, {"stock": "PÅ LAGER"}))

    def test_early_radar_rejects_preserved_wrong_url_and_known_sku(self):
        product = self.product()
        variants = (
            {**product, "fetch_via": "jina_reader+preserved_previous_scan"},
            {**product, "url": "https://example.com/Pokemon/slug/3591111"},
            {**product, "url": "https://www.proshop.dk/Pokemon/X/3591112"},
        )
        for bad in variants:
            with self.subTest(bad=bad):
                self.assertIsNone(hot._proshop_radar_event("3591111", bad, None))
        known = self.product(sku="3478496")
        self.assertIsNone(hot._proshop_radar_event("3478496", known, None))

    def test_early_radar_posts_only_to_dedicated_webhook_with_dedupe(self):
        product = self.product()
        response = type("Response", (), {"raise_for_status": lambda self: None})()
        state = {}
        with patch.object(hot, "PROSHOP_EARLY_WEBHOOK_URL", "https://example.org/early"), \
             patch.object(hot, "HOT_DRY_RUN", False), \
             patch.object(hot.requests, "post", return_value=response) as sender:
            self.assertTrue(hot.maybe_send_proshop_early_alert(state, "3591111", product))
            self.assertFalse(hot.maybe_send_proshop_early_alert(state, "3591111", product))
        self.assertEqual(sender.call_count, 1)
        self.assertEqual(sender.call_args.args[0], "https://example.org/early")
        data = sender.call_args.kwargs["json"]
        self.assertIn("KATALOGFUND", data["embeds"][0]["title"])
        self.assertIn("ikke verificeret", str(data["embeds"][0]).lower())
        self.assertEqual(data["allowed_mentions"], {"parse": []})

    def test_expanded_proshop_reader_discovers_two_ex_boxes_offline(self):
        # Two independent search cards; no real Proshop/Jina/Discord traffic.
        text = (
            "* [![Image 1: Sylveon](https://image.test/1.png)]"
            "(https://www.proshop.dk/Pokemon/Pokemon-ex-Box-Sylveon-30th-Celebration/3591111)\n"
            "Pokemon ex Box Sylveon 30th Celebration\n"
            "Bestillingsvare\n"
            "* [![Image 2: Greninja](https://image.test/2.png)]"
            "(https://www.proshop.dk/Pokemon/Pokemon-Ex-Box-Greninja-30th-Celebration/3591112)\n"
            "Pokemon Ex Box Greninja 30th Celebration\n"
            "På lager\n599,00 kr.\n"
        )
        response = type("Response", (), {
            "text": text, "raise_for_status": lambda self: None,
        })()
        with patch.object(hot.requests, "get", return_value=response):
            found = hot._fetch_proshop_broad_reader_products(
                {"_proshop_is_tcg_text": lambda _value: False})
        self.assertEqual(set(found), {"3591111", "3591112"})
        self.assertEqual(found["3591111"]["stock"], "BESTILLINGSVARE")
        self.assertEqual(found["3591112"]["stock"], "PÅ LAGER")



class VerifiedOnlyHotGuardTests(unittest.TestCase):
    def test_salling_fresh_published_online_stock_is_alerted_neutrally(self):
        product = {
            "name": "Pokémon 30th Celebration Ultra-Premium Collection",
            "url": "https://www.br.dk/example",
            "online_count": 20,
            "is_exposed": True,
            "price": 2599,
        }
        with patch.object(hot_v4, "_ORIGINAL_SEND_HOT_ALERT", return_value=True) as send:
            for source in ("br", "bilka", "foetex"):
                self.assertTrue(hot_v4.verified_only_hot_alert(
                    source, product, "RESTOCK"))
            self.assertEqual(send.call_count, 3)

    def test_salling_hidden_stale_or_zero_never_posts(self):
        source = "br"
        product = {
            "name": "Pokémon 30th Celebration Ultra-Premium Collection",
            "url": "https://www.br.dk/example",
            "online_count": 20, "is_exposed": True,
        }
        with patch.object(hot_v4, "_ORIGINAL_SEND_HOT_ALERT") as send:
            for change in (
                {"is_exposed": False},
                {"is_exposed": None},
                {"online_count": 0},
                {"online_count": False},
                {"preorder": True},
                {"fetch_via": "feed+preserved_previous_scan"},
            ):
                with self.subTest(change=change):
                    self.assertFalse(hot_v4.verified_only_hot_alert(
                        source, {**product, **change}, "RESTOCK"))
            send.assert_not_called()

    def test_verified_fresh_stock_is_allowed(self):
        cases = (
            ("coolshop", {"online_stock": True}),
            ("proshop", {"stock": "PÅ LAGER"}),
        )
        for source, attrs in cases:
            with self.subTest(source=source), patch.object(
                hot_v4, "_ORIGINAL_SEND_HOT_ALERT", return_value=True
            ) as send:
                product = {"name": "Pokemon booster bundle",
                           "url": "https://example.org/item", **attrs}
                self.assertTrue(hot_v4.verified_only_hot_alert(
                    source, product, "RESTOCK"))
                send.assert_called_once()

    def test_uncertain_or_stale_data_fails_closed(self):
        cases = (
            ("coolshop", {"online_stock": True, "preorder": True}),
            ("coolshop", {"online_stock": True,
                          "fetch_via": "feed+preserved_previous_scan"}),
            ("coolshop", {"online_stock": False}),
            ("proshop", {"stock": "BESTILLINGSVARE"}),
            ("proshop", {"stock": "PÅ LAGER", "preorder": True}),
            ("proshop", {"stock": "PÅ LAGER",
                         "fetch_via": "jina_reader+preserved_previous_scan"}),
        )
        with patch.object(hot_v4, "_ORIGINAL_SEND_HOT_ALERT") as send:
            for source, attrs in cases:
                with self.subTest(source=source, attrs=attrs):
                    product = {"name": "Pokemon booster bundle",
                               "url": "https://example.org/item", **attrs}
                    self.assertFalse(hot_v4.verified_only_hot_alert(
                        source, product, "RESTOCK"))
            send.assert_not_called()

    def test_renderer_error_or_unknown_cannot_fall_back_to_legacy(self):
        product = {"name": "Pokemon", "url": "https://example.org/item",
                   "online_stock": True}
        with patch.object(hot_v4.base, "hot_payload",
                          side_effect=ValueError("malformed")), patch.object(
                          hot_v4, "_ORIGINAL_SEND_HOT_ALERT") as send:
            self.assertFalse(hot_v4.verified_only_hot_alert(
                "coolshop", product, "RESTOCK"))
            send.assert_not_called()

    def test_production_entrypoint_installs_final_guard(self):
        original = hot_v4.base.send_hot_alert
        try:
            with patch.object(hot_v4.base, "main") as main:
                hot_v4.main()
                main.assert_called_once()
                self.assertIs(hot_v4.base.send_hot_alert,
                              hot_v4.verified_only_hot_alert)
        finally:
            hot_v4.base.send_hot_alert = original


if __name__ == "__main__":
    unittest.main()
