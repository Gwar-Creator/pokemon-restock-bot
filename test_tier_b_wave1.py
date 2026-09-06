import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tier_b_wave1_shadow as shadow
import tier_b_wave1_sources as sources


class TierBWave1SourceTests(unittest.TestCase):
    def test_wave_contains_all_eight_agreed_sources(self):
        self.assertEqual(
            set(sources.WAVE1_SOURCES),
            {
                "cardcollective",
                "flinamania",
                "softgunshoppen",
                "pockomonsters",
                "orbitalkickz",
                "kofodtrading",
                "andishop",
                "cardstop",
            },
        )

    def test_filters_non_english_singles_livebreak_and_repack(self):
        self.assertFalse(
            sources._sealed_allowed(
                "Pokemon Booster Box",
                "Pokemon Japanese Booster Box",
            )
        )
        self.assertFalse(
            sources._sealed_allowed(
                "Pokemon Display (CHN)",
                "Pokemon Scorching Skies Display (CHN)",
            )
        )
        self.assertFalse(
            sources._sealed_allowed(
                "Charizard ex Collection",
                "Pokemon Singles Charizard ex Collection",
            )
        )
        self.assertFalse(
            sources._sealed_allowed(
                "Pokemon Booster Pack Livebreak",
                "Pokemon Booster Pack Livebreak",
            )
        )
        self.assertFalse(
            sources._sealed_allowed(
                "Pokemon Super Repack Booster Pack",
                "Pokemon Super Repack Booster Pack",
            )
        )

    def test_keeps_official_binder_collection_but_not_plain_binder(self):
        self.assertTrue(
            sources._sealed_allowed(
                "Pokemon 151 Binder Collection",
                "Pokemon 151 Binder Collection",
            )
        )
        self.assertFalse(
            sources._sealed_allowed(
                "Pokemon 9-pocket Binder",
                "Pokemon 9-pocket Binder",
            )
        )

    def test_shopify_normalization_keeps_stock_price_and_preorder(self):
        config = {
            "base": "https://example.test",
            "feeds": [{"path": "/products.json", "game": "POKÉMON"}],
        }
        raw = {
            "id": 123,
            "handle": "future-booster-box",
            "title": "Pokemon Future Booster Box",
            "product_type": "Sealed Pokemon",
            "vendor": "Pokemon",
            "tags": ["preorder"],
            "variants": [
                {"available": False, "price": "999.00"},
                {"available": True, "price": "899.00"},
            ],
        }
        with patch.object(sources, "fetch_shopify_feed", return_value=[raw]):
            products = sources.fetch_shopify_source(config)
        self.assertEqual(products["123"]["price"], 899.0)
        self.assertTrue(products["123"]["in_stock"])
        self.assertTrue(products["123"]["preorder"])

    def test_shopify_html_stock_parser_distinguishes_cart_and_sold_out(self):
        document = """
        <div class="grid">
          <div class="card-wrapper">
            <a href="/products/live-booster-box">Pokemon Live Booster Box</a>
            <span>1.700,00 DKK</span><button>Læg i kurv</button>
          </div>
          <div class="card-wrapper">
            <a href="/products/sold-etb">Pokemon Sold ETB</a>
            <span>700,00 DKK</span><button>Udsolgt</button>
          </div>
        </div>
        """
        stock = sources.parse_shopify_html_stock(document)
        self.assertTrue(stock["live-booster-box"])
        self.assertFalse(stock["sold-etb"])

    def test_shopify_html_overlay_can_correct_false_json_availability(self):
        config = {
            "base": "https://example.test",
            "feeds": [{"path": "/products.json", "game": "POKÉMON"}],
            "html_stock_path": "/collections/all",
        }
        raw = {
            "id": 123,
            "handle": "booster-box",
            "title": "Pokemon Booster Box",
            "product_type": "Sealed Pokemon",
            "vendor": "Pokemon",
            "tags": [],
            "variants": [{"available": False, "price": "999.00"}],
        }
        with (
            patch.object(sources, "fetch_shopify_feed", return_value=[raw]),
            patch.object(
                sources,
                "fetch_shopify_html_stock",
                return_value={"booster-box": True},
            ),
        ):
            products = sources.fetch_shopify_source(config)
        self.assertTrue(products["123"]["in_stock"])

    def test_softgun_magento_fixture_parses_stock_and_blocks_repack_and_chn(self):
        document = """
        <ol class="products">
          <li class="product-item">
            <div class="product-item-info">
              <strong class="product-item-name">
                <a class="product-item-link" href="/pokemon/first-partner.html">
                  Pokemon First Partner Illustration Collection
                </a>
              </strong>
              <span class="price">375,00 kr.</span>
              <button>Tilføj kurv</button>
            </div>
          </li>
          <li class="product-item">
            <div class="product-item-info">
              <strong class="product-item-name">
                <a class="product-item-link" href="/pokemon/repack.html">
                  Pokemon Super Repack - 50 Kort Booster Pack
                </a>
              </strong>
              <span class="price">99,00 kr.</span>
              <button>Tilføj kurv</button>
            </div>
          </li>
          <li class="product-item">
            <div class="product-item-info">
              <strong class="product-item-name">
                <a class="product-item-link" href="/pokemon/chn.html">
                  Pokemon Scorching Skies Display (CHN)
                </a>
              </strong>
              <span class="price">580,00 kr.</span>
              <button>Tilføj kurv</button>
            </div>
          </li>
        </ol>
        """
        products = sources.parse_softgun_html(document, "https://www.softgunshoppen.com")
        self.assertEqual(len(products), 1)
        product = next(iter(products.values()))
        self.assertEqual(product["price"], 375.0)
        self.assertTrue(product["in_stock"])
        self.assertIn("First Partner", product["name"])


class TierBWave1ShadowTests(unittest.TestCase):
    def test_failed_source_preserves_previous_products_without_breaking_run(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "shadow.json"
            old_sources = {}
            for key, config in sources.WAVE1_SOURCES.items():
                old_sources[key] = {
                    "label": config["label"],
                    "mode": "shadow",
                    "health": {
                        "status": "ok",
                        "consecutive_failures": 0,
                        "last_success": "old",
                    },
                    "products": {
                        "old": {
                            "name": "Pokemon Booster Box",
                            "game": "POKÉMON",
                            "price": 1000.0,
                            "in_stock": True,
                            "preorder": False,
                            "url": "https://example.test/old",
                        }
                    },
                }
            state_path.write_text(
                json.dumps({"version": 1, "mode": "shadow", "sources": old_sources}),
                encoding="utf-8",
            )

            def fake_fetch(source_key):
                if source_key == "cardcollective":
                    raise RuntimeError("temporary failure")
                minimum = int(sources.WAVE1_SOURCES[source_key]["minimum"])
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
            new_state = json.loads(state_path.read_text(encoding="utf-8"))
            cardcollective = new_state["sources"]["cardcollective"]
            self.assertEqual(cardcollective["products"], old_sources["cardcollective"]["products"])
            self.assertEqual(cardcollective["health"]["status"], "failed")
            self.assertEqual(cardcollective["health"]["consecutive_failures"], 1)


if __name__ == "__main__":
    unittest.main()
