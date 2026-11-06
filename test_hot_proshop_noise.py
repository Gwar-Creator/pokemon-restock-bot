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
