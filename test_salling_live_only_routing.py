"""Regression: #restocks must never show Salling PRE-PUBLISH system inventory.

All tests are offline and exercise production scanner functions with fake
requests and state. No live Discord, state writes or provider API access.
"""
import os
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

import local_stock_watch as local
import hidden_stock_watch as hidden

SKU = "11398796-EA"
ID = "200397051"
KEY = "bilka:" + ID


def product(visibility, stock, include_store=True):
    return {
        "id": ID,
        "sku": SKU,
        "name": "Pokemon Elite Trainer Box: Mega Evolution Delta Reign samlekort box",
        "type": "ETB",
        "series": None,
        "price": 599,
        "site": "BILKA",
        "visibility": visibility,
        "store_count": 16,
        "url": "https://www.bilka.dk/produkter/test/200397051/",
        "stocks": {"1662": {"name": "Bilka Kolding", "stock": stock}}
                  if include_store else {},
        "national_stores": {"1662": {"name": "Bilka Kolding", "stock": stock}},
        "observed_at": "2026-11-05T15:01:58+00:00",
    }


def scan_state(old_product, new_product):
    saved = []
    state = {
        "version": 1,
        "baseline_complete": True,
        "products": {KEY: deepcopy(old_product)},
    }

    def observe(site, _old):
        if site == "bilka":
            return {KEY: deepcopy(new_product)}, 0, None
        return {}, 0, None

    response = Mock()
    response.raise_for_status.return_value = None
    with patch.object(local, "load_state", return_value=state), \
         patch.object(local, "scan_site", side_effect=observe), \
         patch.object(local, "save_state", side_effect=saved.append), \
         patch.object(local, "WEBHOOK_URL", "https://example.test/restocks"), \
         patch.dict(os.environ, {"DISCORD_V2_LOCAL_MODE": "on"}), \
         patch.object(local.requests, "post", return_value=response) as api:
        local.main()
    return saved[0], api.call_args_list


class RestocksLiveOnlyRoutingTests(unittest.TestCase):
    def test_actual_november_5_0_to_9_hidden_event_is_state_only(self):
        state, posts = scan_state(
            product("PRE-PUBLISH", 0), product("PRE-PUBLISH", 9)
        )
        self.assertEqual(posts, [])
        self.assertEqual(state["products"][KEY]["stocks"]["1662"]["stock"], 9)

    def test_unknown_visibility_fails_closed(self):
        state, posts = scan_state(product("UNKNOWN", 0), product("UNKNOWN", 9))
        self.assertEqual(posts, [])
        self.assertEqual(state["products"][KEY]["stocks"]["1662"]["stock"], 9)

    def test_live_0_to_9_still_posts_once_to_restocks(self):
        _, posts = scan_state(product("LIVE", 0), product("LIVE", 9))
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].kwargs["url"], "https://example.test/restocks")
        title = posts[0].kwargs["json"]["embeds"][0]["title"]
        self.assertIn("LOKALT LAGER", title)
        self.assertIn("BUTIKSLAGER", title)
        self.assertNotIn("KLARGØRES", title)

    def test_missing_old_store_is_not_invented_as_zero(self):
        state, posts = scan_state(
            product("LIVE", 0, include_store=False), product("LIVE", 9)
        )
        self.assertEqual(posts, [])
        self.assertEqual(state["products"][KEY]["stocks"]["1662"]["stock"], 9)

    def test_duplicate_pre_publish_discovery_is_not_sent_to_restocks(self):
        with patch.object(local, "WEBHOOK_URL", "https://example.test/restocks"), \
             patch.object(local.requests, "post") as api:
            sent = local.send_discovery_alert([product("PRE-PUBLISH", 9)])
        self.assertFalse(sent)
        api.assert_not_called()

    def test_hidden_stock_sends_only_to_existing_early_channel(self):
        row = {
            "site": "bilka", "store": "Bilka Kolding", "stock": 9,
            "price": 599, "name": "Pokemon Delta Reign ETB",
            "product_id": ID, "sku": SKU,
        }
        response = Mock()
        response.raise_for_status.return_value = None
        with patch.object(hidden, "WEBHOOK", "https://example.test/early"), \
             patch.object(hidden.requests, "post", return_value=response) as api:
            hidden.send_alert([row])
        self.assertEqual(api.call_count, 1)
        self.assertEqual(api.call_args.args[0], "https://example.test/early")

    def test_hidden_stock_missing_early_webhook_never_falls_back(self):
        row = {"site": "bilka", "store": "Bilka Kolding", "stock": 9}
        with patch.object(hidden, "WEBHOOK", ""), \
             patch.object(hidden.requests, "post") as api:
            with self.assertRaisesRegex(RuntimeError, "EARLY_RADAR_SALLING_WEBHOOK_URL"):
                hidden.send_alert([row])
        api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
