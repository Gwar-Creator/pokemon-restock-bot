"""Regression tests for Proshop duplicate Discord notifications."""

import time
import unittest
from unittest.mock import patch

import hot_restock as hot


def proshop_product(stock="PÅ LAGER"):
    return {
        "name": "Pokemon TCG Mega Greninja ex Premium Collection",
        "game": "POKÉMON",
        "price": 499.0,
        "stock": stock,
        "url": "https://www.proshop.dk/Pokemon/Pokemon-TCG-Mega-Greninja-ex-Premium-Collection/3478496",
    }


class ProshopNoiseTests(unittest.TestCase):
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

    def test_persisted_cooldown_expires(self):
        state = {"last_hot_alerts": {"proshop:3478496": 1000}}
        self.assertFalse(hot._hot_alert_allowed(state, "proshop", "3478496", now=1001))
        self.assertTrue(
            hot._hot_alert_allowed(
                state, "proshop", "3478496",
                now=1000 + hot.PROSHOP_ALERT_COOLDOWN_SECONDS,
            )
        )
        self.assertTrue(hot._hot_alert_allowed(state, "br", "3478496", now=1001))


if __name__ == "__main__":
    unittest.main()
