import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tier_b_wave3_shadow as shadow
import tier_b_wave3_sources as sources


class TierBWave3SourceTests(unittest.TestCase):
    def test_wave3_has_six_sources(self):
        self.assertEqual(
            set(sources.WAVE3_SOURCES),
            {
                "snydepels",
                "kidsworld",
                "borneneskartel",
                "ergames",
                "mugglealley",
                "superhelten",
            },
        )

    def test_snydepels_covers_pokemon_and_lorcana(self):
        feeds = sources.WAVE3_SOURCES["snydepels"]["feeds"]
        self.assertIn(
            {"path": "/collections/tcg-ccg-pokemon/products.json", "game": "POKÉMON"},
            feeds,
        )
        self.assertIn(
            {"path": "/collections/tcg-ccg-disney-lorcana/products.json", "game": "LORCANA"},
            feeds,
        )

    def test_snydepels_stock_cards_distinguish_buyable_and_sold_out(self):
        document = """
        <div class="grid-item__content">
          <a href="/collections/tcg-ccg-pokemon/products/pitch-black-bundle">
            Pokemon TCG Pitch Black Booster Bundle
          </a>
          <button>Tilføj til kurv</button><span>299,00 kr.</span>
        </div>
        <div class="grid-item__content">
          <a href="/collections/tcg-ccg-pokemon/products/perfect-order-booster">
            Pokemon TCG Perfect Order Booster Pack
          </a>
          <span>Udsolgt</span><span>49,00 kr.</span>
        </div>
        """
        stock = sources.parse_shopify_card_stock(document, ".grid-item__content")
        self.assertIs(stock["pitch-black-bundle"], True)
        self.assertIs(stock["perfect-order-booster"], False)

    def test_kidsworld_uses_outer_card_with_add_to_cart(self):
        document = """
        <div class="product product-size-selection">
          <div class="product__body">
            <a href="/pokemon-samlekort-mega-evolution-pitch-black-booster-bundle-p-450001.html">
              Pokémon Samlekort - Mega Evolution: Pitch Black - Booster Bundle
            </a>
            <span>389,95 kr.</span>
          </div>
          <button>Læg i kurv</button>
        </div>
        <div class="product product-size-selection">
          <div class="product__body">
            <a href="/pokemon-prismatic-super-premium-collection-p-450002.html">
              Pokémon Prismatic Evolutions Super Premium Collection
            </a>
            <span>2.499,95 kr.</span>
          </div>
          <button disabled>Udsolgt</button>
        </div>
        """
        products = sources.parse_selector_catalog(
            document,
            "https://www.kids-world.dk",
            "POKÉMON",
            r"/pokemon-[^?#]+-p-\d+\.html$",
            "div.product.product-size-selection",
        )
        rows = {product["name"]: product for product in products.values()}
        self.assertEqual(len(rows), 2)
        self.assertTrue(
            rows["Pokémon Samlekort - Mega Evolution: Pitch Black - Booster Bundle"]["in_stock"]
        )
        self.assertEqual(
            rows["Pokémon Samlekort - Mega Evolution: Pitch Black - Booster Bundle"]["price"],
            389.95,
        )
        self.assertFalse(rows["Pokémon Prismatic Evolutions Super Premium Collection"]["in_stock"])

    def test_borneneskartel_stock_is_scoped_per_product_card(self):
        document = """
        <article class="product-card">
          <a href="/collections/samlekort-mapper/products/pitch-black-etb">Pokemon Pitch Black Elite Trainer Box</a>
          <button>Tilføj til kurv</button>
        </article>
        <article class="product-card">
          <a href="/products/old-booster-box">Pokemon Old Booster Box</a>
          <span>Udsolgt</span>
        </article>
        """
        stock = sources.parse_shopify_card_stock(document, "article.product-card")
        self.assertIs(stock["pitch-black-etb"], True)
        self.assertIs(stock["old-booster-box"], False)

    def test_ergames_uses_dedicated_pokemon_kort_category_and_paginates(self):
        pokemon_page = sources.WAVE3_SOURCES["ergames"]["pages"][0]
        self.assertEqual(
            pokemon_page["url"],
            "https://er-games.dk/kategori/pokemon/pokemon-kort/",
        )
        self.assertTrue(pokemon_page["paginate"])
        self.assertEqual(pokemon_page["max_pages"], 5)

    def test_ergames_selector_filters_graded_and_non_english_products(self):
        document = """
        <div class="e-loop-item product">
          <a href="/vare/pokemon-pitch-black-elite-trainer-box/">Pokemon Pitch Black Elite Trainer Box</a>
          <span>699,95 kr.</span><span>141 på lager</span>
        </div>
        <div class="e-loop-item product">
          <a href="/vare/blastoise-psa-10/">Blastoise Collection PSA 10</a>
          <span>3.000,00 kr.</span><span>1 på lager</span>
        </div>
        <div class="e-loop-item product">
          <a href="/vare/japanese-booster-box/">Pokemon Japanese Booster Box</a>
          <span>799,95 kr.</span><span>På lager</span>
        </div>
        <div class="e-loop-item product">
          <a href="/vare/30th-etb/">Pokemon 30th Celebration Elite Trainer Box</a>
          <span>Forudbestil 16/9</span><span>1.199,95 kr.</span><span>215 på lager</span>
        </div>
        """
        products = sources.parse_selector_catalog(
            document,
            "https://er-games.dk",
            "POKÉMON",
            r"/vare/[^/?#]+/?$",
            ".e-loop-item.product",
        )
        rows = {product["name"]: product for product in products.values()}
        self.assertEqual(
            set(rows),
            {
                "Pokemon Pitch Black Elite Trainer Box",
                "Pokemon 30th Celebration Elite Trainer Box",
            },
        )
        self.assertTrue(rows["Pokemon Pitch Black Elite Trainer Box"]["in_stock"])
        self.assertTrue(rows["Pokemon 30th Celebration Elite Trainer Box"]["preorder"])

    def test_superhelten_listed_cards_are_stock_unless_explicitly_negative(self):
        document = """
        <div class="product-preview">
          <a href="/da/pokemon-kort-booster-pakker--tin-boxes/pokemon-30th-mini-tin">Pokémon TCG 30th Celebration Mini Tin</a>
          <span>DKK 199,95</span>
        </div>
        <div class="product-preview">
          <a href="/da/pokemon-kort-booster-pakker--tin-boxes/pokemon-old-etb">Pokémon Old Elite Trainer Box</a>
          <span>DKK 699,95</span><span>Udsolgt</span>
        </div>
        """
        products = sources.parse_selector_catalog(
            document,
            "https://www.superheltenlegetoej.dk",
            "POKÉMON",
            r"/da/pokemon-kort-booster-pakker--tin-boxes/[^/?#]+/?$",
            "div.product-preview",
            listed_is_in_stock=True,
        )
        rows = {product["name"]: product for product in products.values()}
        self.assertTrue(rows["Pokémon TCG 30th Celebration Mini Tin"]["in_stock"])
        self.assertFalse(rows["Pokémon Old Elite Trainer Box"]["in_stock"])

    def test_muggle_detail_stock_uses_buy_control_and_sold_out_text(self):
        buyable = """
        <h1>Pokemon Pitch Black Booster Box</h1>
        <div>Lagerstatus: 1 - 3 hverdage</div>
        <button>Køb</button>
        """
        sold_out = """
        <h1>Pokemon White Flare Booster Bundle</h1>
        <div>Lagerstatus: Produktet er udsolgt</div>
        <div>Kan på nuværende tidspunkt ikke bestilles</div>
        """
        self.assertIs(sources._muggle_detail_stock(buyable), True)
        self.assertIs(sources._muggle_detail_stock(sold_out), False)

    def test_wave3_dispatches_source_specific_adapters(self):
        fake_products = {"1": {"name": "Pokemon Booster Box"}}

        with patch.object(sources, "fetch_wave3_shopify_source", return_value=fake_products) as shopify:
            products = sources.fetch_wave3_source("snydepels")
        self.assertEqual(products, fake_products)
        shopify.assert_called_once_with(sources.WAVE3_SOURCES["snydepels"])

        with patch.object(sources, "fetch_selector_catalog_source", return_value=fake_products) as html:
            products = sources.fetch_wave3_source("kidsworld")
        self.assertEqual(products, fake_products)
        html.assert_called_once_with(sources.WAVE3_SOURCES["kidsworld"])

        with patch.object(sources, "fetch_mugglealley_source", return_value=fake_products) as muggle:
            products = sources.fetch_wave3_source("mugglealley")
        self.assertEqual(products, fake_products)
        muggle.assert_called_once_with(sources.WAVE3_SOURCES["mugglealley"])


class TierBWave3LiveTests(unittest.TestCase):
    def test_all_six_wave3_sources_are_live(self):
        self.assertEqual(set(shadow.LIVE_SOURCES), set(sources.WAVE3_SOURCES))

    def test_live_run_preserves_failed_source_and_marks_all_modes_live(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "wave3.json"
            old = {
                "version": 1,
                "mode": "shadow",
                "sources": {
                    "snydepels": {
                        "label": "SNYDEPELS",
                        "mode": "shadow",
                        "health": {"status": "ok", "consecutive_failures": 0, "last_success": "old"},
                        "products": {
                            "old": {
                                "name": "Pokemon Booster Box",
                                "game": "POKÉMON",
                                "in_stock": True,
                            }
                        },
                    }
                },
            }
            state_path.write_text(json.dumps(old), encoding="utf-8")

            def fake_fetch(source_key):
                if source_key == "snydepels":
                    raise RuntimeError("temporary")
                minimum = int(sources.WAVE3_SOURCES[source_key]["minimum"])
                return {
                    str(index): {
                        "name": f"Pokemon Booster Box {index}",
                        "game": "POKÉMON",
                        "price": 1000.0,
                        "in_stock": True,
                        "preorder": False,
                        "url": f"https://example.test/{source_key}/{index}",
                    }
                    for index in range(minimum)
                }

            sent = []
            with patch.object(shadow, "STATE_FILE", state_path):
                failures = shadow.run_scan(fetcher=fake_fetch, sender=sent.append)

            self.assertEqual(failures, 1)
            self.assertEqual(sent, [])
            new = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(new["mode"], "live")
            self.assertEqual(
                new["sources"]["snydepels"]["products"],
                old["sources"]["snydepels"]["products"],
            )
            self.assertEqual(new["sources"]["snydepels"]["health"]["status"], "failed")
            self.assertTrue(all(entry["mode"] == "live" for entry in new["sources"].values()))

    def test_promotion_is_baseline_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "wave3.json"

            def fake_fetch(source_key):
                minimum = int(sources.WAVE3_SOURCES[source_key]["minimum"])
                return {
                    str(index): {
                        "name": f"Pokemon 30th Celebration Booster Bundle {index}",
                        "game": "POKÉMON",
                        "price": 500.0,
                        "in_stock": True,
                        "preorder": False,
                        "url": f"https://example.test/{source_key}/{index}",
                    }
                    for index in range(minimum)
                }

            sent = []
            with patch.object(shadow, "STATE_FILE", state_path):
                shadow.run_scan(fetcher=fake_fetch, sender=sent.append)
            self.assertEqual(sent, [])

    def test_live_transition_uses_shared_strict_tier_b_gate(self):
        sent = []
        old_products = {
            "good": {
                "name": "Pokemon 30th Celebration Booster Bundle",
                "game": "POKÉMON",
                "in_stock": False,
                "preorder": False,
            },
            "noise": {
                "name": "Pokemon Checklane Blister",
                "game": "POKÉMON",
                "in_stock": False,
                "preorder": False,
            },
        }
        products = {
            "good": {
                "name": "Pokemon 30th Celebration Booster Bundle",
                "game": "POKÉMON",
                "price": 499.0,
                "in_stock": True,
                "preorder": False,
                "url": "https://example.test/good",
            },
            "noise": {
                "name": "Pokemon Checklane Blister",
                "game": "POKÉMON",
                "price": 49.0,
                "in_stock": True,
                "preorder": False,
                "url": "https://example.test/noise",
            },
        }
        count = shadow._emit_live_alerts(
            "snydepels",
            "SNYDEPELS",
            old_products,
            products,
            sender=sent.append,
        )
        self.assertEqual(count, 1)
        self.assertEqual(len(sent), 1)
        self.assertIn("30th Celebration Booster Bundle", sent[0])
        self.assertNotIn("Checklane", sent[0])


if __name__ == "__main__":
    unittest.main()
