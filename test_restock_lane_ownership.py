import unittest

import hot_restock_v4 as hot_v4
import restock_lane_runner as lane


class RestockLaneOwnershipTests(unittest.TestCase):
    def test_main_suppresses_tier_a_pokemon_restock(self):
        message = (
            "🔥 **[POKÉMON] FØTEX RESTOCK**\n"
            "**Pokemon rare coll sv6.5 shrouded fable**\n"
            "🏪 føtex Kolding Syd: 0 → 2 stk."
        )
        self.assertFalse(lane.restock_lane_channel_alert_allowed(message))

    def test_main_keeps_tier_a_pokemon_new_discovery(self):
        message = (
            "🆕 **[POKÉMON] NYT PÅ FØTEX**\n"
            "**Pokemon 151 Booster Bundle**\n"
            "📦 Nyt relevant produkt"
        )
        self.assertTrue(lane.restock_lane_channel_alert_allowed(message))

    def test_main_keeps_tier_a_lorcana_restock(self):
        message = (
            "🔥 **[LORCANA] COOLSHOP RESTOCK**\n"
            "**Disney Lorcana Shimmering Skies Booster Bundle**\n"
            "✅ På lager online"
        )
        self.assertTrue(lane.restock_lane_channel_alert_allowed(message))

    def test_main_suppresses_pokemonportalen_preorder_until_buyability_is_verified(self):
        message = (
            "🟡 **[POKÉMON] POKEMONPORTALEN FORUDBESTILLING**\n"
            "**Pokemon 30th Anniversary Booster Box**\n"
            "📦 Forudbestilling fundet"
        )
        self.assertFalse(lane.restock_lane_channel_alert_allowed(message))

    def test_main_keeps_pokemonportalen_restock(self):
        message = (
            "🔥 **[POKÉMON] POKEMONPORTALEN RESTOCK**\n"
            "**Pokemon 151 Booster Bundle**\n"
            "✅ På lager"
        )
        self.assertTrue(lane.restock_lane_channel_alert_allowed(message))

    def test_hot_salling_is_online_only(self):
        local_only = {
            "online_count": 0,
            "local_stocks": {
                "1370": {"name": "føtex Kolding Syd", "stock": 2}
            },
        }
        online = {
            "online_count": 3,
            "local_stocks": {
                "1370": {"name": "føtex Kolding Syd", "stock": 0}
            },
        }
        self.assertFalse(hot_v4.online_lane_product_available("foetex", local_only))
        self.assertTrue(hot_v4.online_lane_product_available("foetex", online))

    def test_hot_shared_tier_a_policy_mutes_abundant_pack(self):
        shared = {"restock_alert_allowed": lambda _product, _game: True}
        products = {
            "pack": {
                "name": "Pitch Black Booster Pack",
                "game": "POKÉMON",
            },
            "bundle": {
                "name": "Pitch Black Booster Bundle",
                "game": "POKÉMON",
            },
            "normal": {
                "name": "Shrouded Fable Special Collection",
                "game": "POKÉMON",
            },
        }
        filtered = hot_v4.policy_filtered_hot_products(shared, products)
        self.assertNotIn("pack", filtered)
        self.assertIn("bundle", filtered)
        self.assertIn("normal", filtered)


if __name__ == "__main__":
    unittest.main()
