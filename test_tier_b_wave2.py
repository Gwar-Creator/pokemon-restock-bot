import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tier_b_wave2_shadow as shadow
import tier_b_wave2_sources as sources


class TierBWave2SourceTests(unittest.TestCase):
    def test_wave2_has_cardquest_and_hobbykniven(self):
        self.assertEqual(set(sources.WAVE2_SOURCES), {"cardquest", "hobbykniven"})
        self.assertEqual(sources.WAVE2_SOURCES["cardquest"]["kind"], "shopify_cardquest")
        self.assertEqual(sources.WAVE2_SOURCES["hobbykniven"]["kind"], "hobbykniven_html")

    def test_cardquest_uses_dedicated_pokemon_and_lorcana_collections(self):
        feeds = sources.WAVE2_SOURCES["cardquest"]["feeds"]
        self.assertIn(
            {"path": "/collections/pokemon/products.json", "game": "POKÉMON"},
            feeds,
        )
        self.assertIn(
            {"path": "/collections/disney-lorcana/products.json", "game": "LORCANA"},
            feeds,
        )

    def test_cardquest_rendered_cards_distinguish_buyable_and_sold_out(self):
        document = """
        <div class="grid">
          <article class="product-card">
            <a href="/products/prismatic-super-premium">Prismatic Evolutions Super Premium Collection</a>
            <span>2.499,00 kr</span>
            <span>Kun få tilbage</span>
            <button>Tilføj til kurv</button>
          </article>
          <article class="product-card">
            <a href="/products/phantasmal-booster-box">Phantasmal Flames Booster Display Box</a>
            <span>2.995,00 kr</span>
            <span>Udsolgt</span>
            <button disabled>Udsolgt</button>
          </article>
          <article class="product-card">
            <a href="/products/surging-sparks-bundle">Surging Sparks Booster Bundle</a>
            <span>599,00 kr</span>
            <span>Kun få tilbage</span>
            <button aria-label="Tilføj til kurv">+</button>
          </article>
        </div>
        """
        stock = sources.parse_cardquest_html_stock(document)
        self.assertTrue(stock["prismatic-super-premium"])
        self.assertFalse(stock["phantasmal-booster-box"])
        self.assertTrue(stock["surging-sparks-bundle"])

    def test_cardquest_rendered_overlay_overrides_false_shopify_availability(self):
        config = sources.WAVE2_SOURCES["cardquest"]
        normalized = {
            "1": {
                "name": "Prismatic Evolutions Super Premium Collection",
                "game": "POKÉMON",
                "price": 2499.0,
                "in_stock": False,
                "preorder": False,
                "url": "https://cardquest.dk/products/prismatic-super-premium",
            },
            "2": {
                "name": "Phantasmal Flames Booster Display Box",
                "game": "POKÉMON",
                "price": 2995.0,
                "in_stock": False,
                "preorder": False,
                "url": "https://cardquest.dk/products/phantasmal-booster-box",
            },
        }
        with patch.object(sources, "fetch_shopify_source", return_value=normalized) as generic, patch.object(
            sources,
            "fetch_cardquest_html_stock",
            return_value={
                "prismatic-super-premium": True,
                "phantasmal-booster-box": False,
            },
        ) as rendered:
            products = sources.fetch_cardquest_source(config)

        self.assertTrue(products["1"]["in_stock"])
        self.assertFalse(products["2"]["in_stock"])
        generic.assert_called_once()
        rendered.assert_called_once_with(config)
        discovery_config = generic.call_args.args[0]
        self.assertEqual(discovery_config.get("html_stock_paths"), [])
        self.assertNotIn("html_stock_path", discovery_config)
        self.assertEqual(config["html_stock_paths"], [
            "/collections/pokemon",
            "/collections/disney-lorcana",
        ])

    def test_hobbykniven_category_fixture_parses_stock_and_price(self):
        document = """
        <div class="grid">
          <article class="product-card">
            <a href="/katalog/produkt/first-partner">Pokémon First Partner Illustration Collection</a>
            <span>299,95 kr</span><span>På lager</span><button>Læg i kurv</button>
          </article>
          <article class="product-card">
            <a href="/katalog/produkt/sold-booster-box">Pokémon Journey Together Booster Box</a>
            <span>1.799,95 kr</span><span>Udsolgt</span>
          </article>
          <article class="product-card">
            <a href="/katalog/produkt/plain-binder">Pokémon 9-Pocket Binder</a>
            <span>199,95 kr</span><span>På lager</span><button>Læg i kurv</button>
          </article>
        </div>
        """
        products = sources.parse_hobbykniven_html(document, "https://hobbykniven.dk")
        self.assertEqual(len(products), 2)
        rows = {product["name"]: product for product in products.values()}
        self.assertTrue(rows["Pokémon First Partner Illustration Collection"]["in_stock"])
        self.assertEqual(rows["Pokémon First Partner Illustration Collection"]["price"], 299.95)
        self.assertFalse(rows["Pokémon Journey Together Booster Box"]["in_stock"])
        self.assertEqual(rows["Pokémon Journey Together Booster Box"]["price"], 1799.95)

    def test_wave2_cardquest_dispatch_uses_rendered_stock_adapter(self):
        fake_products = {"1": {"name": "Pokemon Booster Box"}}
        with patch.object(sources, "fetch_cardquest_source", return_value=fake_products) as fetcher:
            products = sources.fetch_wave2_source("cardquest")
        self.assertEqual(products, fake_products)
        fetcher.assert_called_once_with(sources.WAVE2_SOURCES["cardquest"])


class TierBWave2LiveTests(unittest.TestCase):
    def test_both_wave2_sources_are_live(self):
        self.assertEqual(set(shadow.LIVE_SOURCES), set(sources.WAVE2_SOURCES))

    def test_live_run_preserves_failed_source_and_marks_all_modes_live(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "wave2.json"
            old = {
                "version": 1,
                "mode": "shadow",
                "sources": {
                    "cardquest": {
                        "label": "CARDQUEST",
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
                if source_key == "cardquest":
                    raise RuntimeError("temporary")
                minimum = int(sources.WAVE2_SOURCES[source_key]["minimum"])
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
                new["sources"]["cardquest"]["products"],
                old["sources"]["cardquest"]["products"],
            )
            self.assertEqual(new["sources"]["cardquest"]["health"]["status"], "failed")
            self.assertTrue(all(entry["mode"] == "live" for entry in new["sources"].values()))

    def test_promotion_is_baseline_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "wave2.json"

            def fake_fetch(source_key):
                minimum = int(sources.WAVE2_SOURCES[source_key]["minimum"])
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
            "cardquest",
            "CARDQUEST",
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
