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
        self.assertEqual(sources.WAVE2_SOURCES["cardquest"]["kind"], "shopify")
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

    def test_wave2_shopify_dispatch_reuses_shared_normalizer(self):
        fake_products = {"1": {"name": "Pokemon Booster Box"}}
        with patch.object(sources, "fetch_shopify_source", return_value=fake_products) as fetcher:
            products = sources.fetch_wave2_source("cardquest")
        self.assertEqual(products, fake_products)
        fetcher.assert_called_once_with(sources.WAVE2_SOURCES["cardquest"])


class TierBWave2ShadowTests(unittest.TestCase):
    def test_shadow_run_is_state_only_and_preserves_failed_source(self):
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
                        "products": {"old": {"name": "Pokemon Booster Box", "game": "POKÉMON", "in_stock": True}},
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
                        "url": f"https://example.test/{index}",
                    }
                    for index in range(minimum)
                }

            with patch.object(shadow, "STATE_FILE", state_path):
                failures = shadow.run_scan(fetcher=fake_fetch)

            self.assertEqual(failures, 1)
            new = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(new["sources"]["cardquest"]["products"], old["sources"]["cardquest"]["products"])
            self.assertEqual(new["sources"]["cardquest"]["health"]["status"], "failed")
            self.assertEqual(new["sources"]["hobbykniven"]["mode"], "shadow")


if __name__ == "__main__":
    unittest.main()
