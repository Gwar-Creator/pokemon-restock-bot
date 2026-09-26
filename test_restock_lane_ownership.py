import unittest
from urllib.parse import urljoin

from bs4 import BeautifulSoup

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

    def _retail_shared(self):
        return {
            "BeautifulSoup": BeautifulSoup,
            "urljoin": urljoin,
            "restock_alert_allowed": lambda _product, _game: True,
        }

    def test_boozt_category_parser_reads_price_but_defers_stock(self):
        html = """
        <div class="product-card">
          <a href="/dk/da/pokmon-trading-cards/poke-me05-etb_33181863/233181708">
            <h3>Pokemon ME05 Elite Trainer Box</h3>
          </a>
          <span>599,00 kr.</span>
          <button>Læg i kurv</button>
        </div>
        """
        products = hot_v4.base._parse_broad_retail_products(
            self._retail_shared(),
            "boozt",
            hot_v4.base.BOOZT_CATEGORY_URL,
            html,
            hot_v4.base._boozt_product_url,
        )
        self.assertEqual(len(products), 1)
        product = next(iter(products.values()))
        self.assertEqual(product["price"], 599.0)
        self.assertFalse(product["availability_known"])

    def test_boozt_detail_parser_reads_cart_and_notify_states(self):
        self.assertTrue(
            hot_v4.base._parse_retail_detail_availability(
                self._retail_shared(),
                "boozt",
                "<html><body><h1>Poke ETB</h1><button>Læg i kurv</button></body></html>",
            )
        )
        self.assertFalse(
            hot_v4.base._parse_retail_detail_availability(
                self._retail_shared(),
                "boozt",
                "<html><body><h1>Poke ETB</h1><button>Giv mig besked</button></body></html>",
            )
        )

    def test_magasin_category_parser_keeps_binder_collection(self):
        html = """
        <div class="product-card">
          <a href="/pokemon-binder-collection/ABC123.html">
            <h3>Pokemon Binder Collection</h3>
          </a>
          <span>499,00 kr.</span>
          <button>Tilføj til kurv</button>
        </div>
        <div class="product-card">
          <a href="/poke-me05-booster/BRXZ18.html">
            <h3>Poke ME05 Booster</h3>
          </a>
          <span>49,95 kr.</span>
          <button>Skriv mig op</button>
        </div>
        """
        products = hot_v4.base._parse_broad_retail_products(
            self._retail_shared(),
            "magasin",
            hot_v4.base.MAGASIN_CATEGORY_URL,
            html,
            hot_v4.base._magasin_product_url,
        )
        self.assertEqual(len(products), 2)
        by_name = {product["name"]: product for product in products.values()}
        self.assertEqual(by_name["Pokemon Binder Collection"]["price"], 499.0)
        self.assertFalse(by_name["Pokemon Binder Collection"]["availability_known"])
        self.assertFalse(by_name["Poke ME05 Booster"]["availability_known"])

    def test_magasin_detail_cart_wins_over_hidden_subscribe_dialog(self):
        html = """
        <html><body>
          <h1>Pokemon Binder Collection</h1>
          <button>Tilføj til kurv</button>
          <div hidden>Skriv mig op</div>
        </body></html>
        """
        self.assertTrue(
            hot_v4.base._parse_retail_detail_availability(
                self._retail_shared(),
                "magasin",
                html,
            )
        )
        self.assertFalse(
            hot_v4.base._parse_retail_detail_availability(
                self._retail_shared(),
                "magasin",
                "<html><body><h1>Poke Tin</h1><button>Skriv mig op</button></body></html>",
            )
        )

    def test_magasin_catalog_gate_rejects_non_tcg_brand_products(self):
        self.assertTrue(
            hot_v4.base._retail_catalog_product_allowed(
                "magasin",
                "Pokemon Binder Collection",
            )
        )
        self.assertTrue(
            hot_v4.base._retail_catalog_product_allowed(
                "magasin",
                "Poke ME05 Booster",
            )
        )
        self.assertFalse(
            hot_v4.base._retail_catalog_product_allowed(
                "magasin",
                "Pokemon Battle figure 6pack",
            )
        )
        self.assertFalse(
            hot_v4.base._retail_catalog_product_allowed(
                "magasin",
                "Magasin Goodie fordelsunivers",
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
        merged = hot_v4.base._preserve_missing_as_out_of_stock(
            "magasin",
            old,
            {},
        )
        self.assertIn("https://example.invalid/product", merged)
        self.assertFalse(
            merged["https://example.invalid/product"]["in_stock"]
        )
        self.assertTrue(
            merged["https://example.invalid/product"]["availability_known"]
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
