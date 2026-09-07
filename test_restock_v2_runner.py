import hashlib
import os
import unittest
from urllib.parse import urljoin

from bs4 import BeautifulSoup

os.environ.setdefault("DISCORD_WEBHOOK_URL", "https://example.invalid/webhook")

import restock_v2_runner as runner


class RestockV2RunnerTests(unittest.TestCase):
    def test_tier_a_restock_stays_broad_for_non_abundant_sets(self):
        message = (
            "🔥 **[POKÉMON] COOLSHOP RESTOCK**\n"
            "**Journey Together Elite Trainer Box**\n"
            "✅ På lager online"
        )
        self.assertTrue(runner.restock_v2_channel_alert_allowed(message))

    def test_tier_a_abundant_pack_is_muted(self):
        message = (
            "🔥 **[POKÉMON] BR RESTOCK**\n"
            "**Pitch Black Booster Pack**\n"
            "✅ På lager online"
        )
        self.assertFalse(runner.restock_v2_channel_alert_allowed(message))

    def test_tier_a_abundant_bundle_still_passes(self):
        message = (
            "🔥 **[POKÉMON] FØTEX RESTOCK**\n"
            "**Pitch Black Booster Bundle**\n"
            "✅ På lager online"
        )
        self.assertTrue(runner.restock_v2_channel_alert_allowed(message))

    def test_tier_b_normal_etb_is_muted(self):
        message = (
            "🔥 **[POKÉMON] MATRAWS RESTOCK**\n"
            "**Journey Together Elite Trainer Box**\n"
            "📦 Udsolgt → På lager"
        )
        self.assertFalse(runner.restock_v2_channel_alert_allowed(message))

    def test_tier_b_booster_box_passes(self):
        message = (
            "🔥 **[POKÉMON] MATRAWS RESTOCK**\n"
            "**Journey Together Booster Box**\n"
            "📦 Udsolgt → På lager"
        )
        self.assertTrue(runner.restock_v2_channel_alert_allowed(message))

    def test_tier_b_watch_etb_passes(self):
        message = (
            "🔥 **[POKÉMON] POKEHULEN RESTOCK**\n"
            "**Pokemon 151 Elite Trainer Box**\n"
            "📦 Udsolgt → På lager"
        )
        self.assertTrue(runner.restock_v2_channel_alert_allowed(message))

    def test_tier_b_abundant_etb_is_muted(self):
        message = (
            "🔥 **[POKÉMON] CARDX RESTOCK**\n"
            "**Pitch Black Elite Trainer Box**\n"
            "📦 Udsolgt → På lager"
        )
        self.assertFalse(runner.restock_v2_channel_alert_allowed(message))

    def test_tier_b_preorder_collection_passes(self):
        message = (
            "🚨 **[POKÉMON] NY FORUDBESTILLING HOS HALMES HULE**\n"
            "**Future Illustration Collection**\n"
            "📅 Forudbestilling"
        )
        self.assertTrue(runner.restock_v2_channel_alert_allowed(message))

    def test_tier_b_preorder_booster_pack_is_muted_unless_watch(self):
        ordinary = (
            "🚨 **[POKÉMON] NY FORUDBESTILLING HOS HALMES HULE**\n"
            "**Future Booster Pack**\n"
            "📅 Forudbestilling"
        )
        watch = (
            "🚨 **[POKÉMON] NY FORUDBESTILLING HOS HALMES HULE**\n"
            "**Pokemon 151 Booster Pack**\n"
            "📅 Forudbestilling"
        )
        self.assertFalse(runner.restock_v2_channel_alert_allowed(ordinary))
        self.assertTrue(runner.restock_v2_channel_alert_allowed(watch))

    def test_tier_b_catalogue_new_booster_pack_is_muted(self):
        message = (
            "🆕 **[POKÉMON] NYT HOS MATRAWS**\n"
            "**Journey Together Booster Pack**\n"
            "✅ På lager"
        )
        self.assertFalse(runner.restock_v2_channel_alert_allowed(message))

    def test_faraos_v3_installs_granular_category_feeds(self):
        namespace = {
            "_faraos_name": lambda _card: "Journey Together",
            "woocommerce_clean_text": lambda value: str(value or ""),
            "FARAOS_FEEDS": (("POKÉMON", "https://example.invalid/old"),),
        }

        runner._install_faraos_parser(namespace)

        self.assertEqual(namespace["FARAOS_FEEDS"], runner.FARAOS_V3_FEEDS)
        self.assertGreaterEqual(len(namespace["FARAOS_FEEDS"]), 10)
        urls = {url for _game, url in namespace["FARAOS_FEEDS"]}
        self.assertIn(
            "https://www.faraos.dk/games/kortspil/pokemon/booster",
            urls,
        )
        self.assertIn(
            "https://www.faraos.dk/games/kortspil/lorcana/boosters",
            urls,
        )

    def test_kelz0r_fast_hook_preserves_product_shape_and_ids(self):
        class FakeResponse:
            def __init__(self, text):
                self.text = text

            def raise_for_status(self):
                return None

        class FakeSession:
            def __init__(self):
                self.headers = {}

            def get(self, url, timeout=30):
                if "page=2" in url:
                    return FakeResponse("<html></html>")
                product_id = "123" if "boosters" in url else "456"
                return FakeResponse(
                    "<article>"
                    f'<a href="/pokemon-test-p-{product_id}.html">Pokemon Booster Box {product_id}</a>'
                    "<span>DKK 999</span><button>Køb nu</button>"
                    "</article>"
                )

        class FakeRequests:
            Session = FakeSession

        namespace = {
            "KELZ0R_FEEDS": (
                "https://kelz0r.test/pokemon-boosters.html?currency=DKK",
                "https://kelz0r.test/pokemon-tins.html?currency=DKK",
            ),
            "requests": FakeRequests,
            "BeautifulSoup": BeautifulSoup,
            "BROWSER_HEADERS": {"User-Agent": "test"},
            "urljoin": urljoin,
            "hashlib": hashlib,
            "woocommerce_clean_text": lambda value: " ".join(str(value or "").split()),
            "woocommerce_is_relevant_sealed": lambda _product: True,
            "_wave5_synthetic": lambda name, game: {"name": name, "game": game},
            "_wave5_nearest_card": lambda anchor, _matcher: anchor.parent,
            "_wave5_anchor_name": lambda anchor, _card=None: anchor.get_text(" ", strip=True),
            "_wave5_price": lambda _text: 999.0,
            "_wave5_product": lambda name, game, price, in_stock, preorder, url: {
                "name": name,
                "game": game,
                "price": price,
                "in_stock": bool(in_stock and not preorder),
                "preorder": bool(preorder),
                "url": url,
            },
            "get_kelz0r_products": lambda: {"legacy": {}},
        }

        runner._install_kelz0r_fast_fetch(namespace)
        products = namespace["get_kelz0r_products"]()

        self.assertEqual(set(products), {"kelz0r:123", "kelz0r:456"})
        self.assertTrue(all(product["in_stock"] for product in products.values()))
        self.assertTrue(all(product["price"] == 999.0 for product in products.values()))


if __name__ == "__main__":
    unittest.main()
