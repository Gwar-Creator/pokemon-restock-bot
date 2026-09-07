import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tier_b_wave3_shadow as shadow
import tier_b_wave3_sources as sources


class TierBWave3SourceTests(unittest.TestCase):
    def test_wave3_has_six_shadow_sources(self):
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

    def test_html_catalog_scopes_stock_to_one_product(self):
        document = """
        <div class="grid">
          <article class="product-card">
            <a href="/pokemon-samlekort-mega-evolution-pitch-black-booster-bundle-p-450001.html">
              Pokémon Samlekort - Mega Evolution: Pitch Black - Booster Bundle
            </a>
            <span>389,95 kr.</span>
            <button>Læg i kurv</button>
          </article>
          <article class="product-card">
            <a href="/pokemon-samlekort-prismatic-super-premium-p-450002.html">
              Pokémon Prismatic Evolutions Super Premium Collection
            </a>
            <span>2.499,95 kr.</span>
            <button disabled>Udsolgt</button>
          </article>
          <article class="product-card">
            <a href="/pokemon-samlemappe-charizard-p-450003.html">Pokémon Samlemappe Charizard</a>
            <span>159,95 kr.</span>
            <button>Læg i kurv</button>
          </article>
        </div>
        """
        products = sources.parse_html_catalog(
            document,
            "https://www.kids-world.dk",
            "POKÉMON",
            r"/pokemon-[^?#]+-p-\d+\.html$",
        )
        self.assertEqual(len(products), 2)
        rows = {product["name"]: product for product in products.values()}
        self.assertTrue(
            rows["Pokémon Samlekort - Mega Evolution: Pitch Black - Booster Bundle"]["in_stock"]
        )
        self.assertEqual(
            rows["Pokémon Samlekort - Mega Evolution: Pitch Black - Booster Bundle"]["price"],
            389.95,
        )
        self.assertFalse(
            rows["Pokémon Prismatic Evolutions Super Premium Collection"]["in_stock"]
        )

    def test_html_catalog_filters_graded_and_non_english_products(self):
        document = """
        <section>
          <article>
            <a href="/vare/pokemon-pitch-black-elite-trainer-box/">Pokemon Pitch Black Elite Trainer Box</a>
            <span>699,95 kr.</span><span>141 på lager</span><button>Tilføj til kurv</button>
          </article>
          <article>
            <a href="/vare/blastoise-psa-10/">Blastoise Collection PSA 10</a>
            <span>3.000,00 kr.</span><span>1 på lager</span>
          </article>
          <article>
            <a href="/vare/japanese-booster-box/">Pokemon Japanese Booster Box</a>
            <span>799,95 kr.</span><span>På lager</span>
          </article>
          <article>
            <a href="/vare/30th-etb/">Pokemon 30th Celebration Elite Trainer Box</a>
            <span>Forudbestil 16/9</span><span>1.199,95 kr.</span><span>215 på lager</span>
          </article>
        </section>
        """
        products = sources.parse_html_catalog(
            document,
            "https://er-games.dk",
            "POKÉMON",
            r"/vare/[^/?#]+/?$",
        )
        rows = {product["name"]: product for product in products.values()}
        self.assertEqual(set(rows), {
            "Pokemon Pitch Black Elite Trainer Box",
            "Pokemon 30th Celebration Elite Trainer Box",
        })
        self.assertTrue(rows["Pokemon Pitch Black Elite Trainer Box"]["in_stock"])
        self.assertTrue(rows["Pokemon 30th Celebration Elite Trainer Box"]["preorder"])

    def test_wave3_dispatches_shopify_and_html_adapters(self):
        fake_products = {"1": {"name": "Pokemon Booster Box"}}
        with patch.object(sources, "fetch_shopify_source", return_value=fake_products) as shopify:
            products = sources.fetch_wave3_source("snydepels")
        self.assertEqual(products, fake_products)
        shopify.assert_called_once_with(sources.WAVE3_SOURCES["snydepels"])

        with patch.object(sources, "fetch_html_catalog_source", return_value=fake_products) as html:
            products = sources.fetch_wave3_source("kidsworld")
        self.assertEqual(products, fake_products)
        html.assert_called_once_with(sources.WAVE3_SOURCES["kidsworld"])


class TierBWave3ShadowTests(unittest.TestCase):
    def test_shadow_run_preserves_failed_source_and_has_no_alert_side_effects(self):
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

            with patch.object(shadow, "STATE_FILE", state_path):
                failures = shadow.run_scan(fetcher=fake_fetch)

            self.assertEqual(failures, 1)
            new = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                new["sources"]["snydepels"]["products"],
                old["sources"]["snydepels"]["products"],
            )
            self.assertEqual(new["sources"]["snydepels"]["health"]["status"], "failed")
            self.assertEqual(new["sources"]["kidsworld"]["mode"], "shadow")


if __name__ == "__main__":
    unittest.main()
