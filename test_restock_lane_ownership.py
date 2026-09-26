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

    def test_main_suppresses_all_wave4_product_events(self):
        for label in ("VAULTED", "POKEDEXET", "POKEMONPORTALEN", "TCGBRUUS", "POKEMON PLAZA"):
            for event_text in ("RESTOCK", "FORUDBESTILLING", "NYT"):
                message = (
                    f"🔥 **[POKÉMON] {label} {event_text}**\n"
                    "**Pokemon 151 Booster Bundle**\n"
                    "✅ Relevant produkt"
                )
                with self.subTest(label=label, event=event_text):
                    self.assertFalse(lane.restock_lane_channel_alert_allowed(message))

    def test_main_mutes_non_wave4_specialty_event(self):
        message = (
            "🔥 **[POKÉMON] MATRAWS RESTOCK**\n"
            "**Pokemon 151 Booster Bundle**\n"
            "✅ På lager"
        )
        self.assertFalse(lane.restock_lane_channel_alert_allowed(message))

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


    def test_hot_broad_retail_sources_use_online_stock_flag(self):
        self.assertTrue(
            hot_v4.base.product_available(
                "boozt",
                {"in_stock": True},
            )
        )
        self.assertFalse(
            hot_v4.base.product_available(
                "boozt",
                {"in_stock": False},
            )
        )
        self.assertTrue(
            hot_v4.base.product_available(
                "magasin",
                {"in_stock": True},
            )
        )

    def test_hot_retail_product_url_detection(self):
        self.assertTrue(
            hot_v4.base._boozt_product_url(
                "https://www.boozt.com/dk/da/pokmon-trading-cards/"
                "poke-me05-elite-trainer-box_33181863/233181708"
            )
        )
        self.assertFalse(
            hot_v4.base._boozt_product_url(
                "https://www.boozt.com/dk/da/pokemon-trading-cards/born"
            )
        )
        self.assertTrue(
            hot_v4.base._magasin_product_url(
                "https://www.magasin.dk/poke-me05-booster/BRXZ18.html"
            )
        )

    def test_missing_retail_product_is_preserved_as_out_of_stock(self):
        old = {
            "https://example.invalid/product": {
                "name": "Pokemon Binder Collection",
                "game": "POKÉMON",
                "price": 499.0,
                "in_stock": True,
                "url": "https://example.invalid/product",
            }
        }
        merged = hot_v4.base._preserve_missing_as_out_of_stock(old, {})
        self.assertIn("https://example.invalid/product", merged)
        self.assertFalse(
            merged["https://example.invalid/product"]["in_stock"]
        )

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
