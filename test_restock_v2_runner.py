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

    def test_price_watch_focus_caps_premium_formats(self):
        namespace = {
            "collect_price_watch_focus_listings": lambda _state, fresh_sources=None: {
                "upc-ok": {"type": "UPC", "price": 2000.0},
                "upc-high": {"type": "UPC", "price": 2000.01},
                "spc-ok": {"type": "SPC", "price": 1500.0},
                "spc-high": {"type": "SPC", "price": 1500.01},
                "collection-ok": {"type": "COLLECTION", "price": 1000.0},
                "collection-high": {"type": "COLLECTION", "price": 1000.01},
                "tin-ok": {"type": "TIN", "price": 500.0},
                "tin-high": {"type": "TIN", "price": 500.01},
                "bundle": {"type": "BOOSTER BUNDLE", "price": 749.0},
            }
        }
        runner._install_price_watch_focus_caps(namespace)
        listings = namespace["collect_price_watch_focus_listings"]({})

        self.assertEqual(
            set(listings),
            {"upc-ok", "spc-ok", "collection-ok", "tin-ok", "bundle"},
        )

    def test_price_watch_focus_sets_are_extended_without_duplicates(self):
        namespace = {
            "PRICE_WATCH_FOCUS_SETS": (
                ("151", ("151",)),
                ("Crown Zenith", ("crown zenith",)),
            )
        }
        runner._install_price_watch_focus_sets(namespace)
        runner._install_price_watch_focus_sets(namespace)

        names = [name for name, _aliases in namespace["PRICE_WATCH_FOCUS_SETS"]]
        self.assertEqual(names.count("Surging Sparks"), 1)
        self.assertEqual(names.count("Twilight Masquerade"), 1)
        self.assertEqual(names.count("Mega Evolution"), 1)
        self.assertEqual(names.count("Journey Together"), 1)
        self.assertEqual(names.count("30th Anniversary"), 1)
        anniversary = dict(namespace["PRICE_WATCH_FOCUS_SETS"])["30th Anniversary"]
        self.assertIn("30th anniversary", anniversary)
        self.assertIn("30th celebration", anniversary)

    def test_price_watch_regular_drop_requires_50_dkk_and_10_percent(self):
        self.assertTrue(runner.price_watch_focus_drop_allowed(500.0, 450.0))
        self.assertTrue(runner.price_watch_focus_drop_allowed(1000.0, 900.0))
        self.assertFalse(runner.price_watch_focus_drop_allowed(1000.0, 920.0))
        self.assertFalse(runner.price_watch_focus_drop_allowed(400.0, 355.0))

    def test_price_watch_restock_combo_can_pass_at_25_dkk_and_5_percent(self):
        self.assertTrue(runner.price_watch_focus_drop_allowed(500.0, 475.0, combo=True))
        self.assertFalse(runner.price_watch_focus_drop_allowed(500.0, 480.0, combo=True))
        self.assertFalse(runner.price_watch_focus_drop_allowed(1000.0, 960.0, combo=True))

    def test_price_watch_market_gap_shadow_finds_clear_standardized_gap(self):
        listings = {
            "a": {
                "set": "151",
                "type": "BOOSTER BUNDLE",
                "name": "Pokemon 151 Booster Bundle",
                "shop": "SHOP A",
                "price": 800.0,
                "in_stock": True,
            },
            "b": {
                "set": "151",
                "type": "BOOSTER BUNDLE",
                "name": "Pokemon 151 Booster Bundle",
                "shop": "SHOP B",
                "price": 1000.0,
                "in_stock": True,
            },
            "c": {
                "set": "151",
                "type": "BOOSTER BUNDLE",
                "name": "Pokemon 151 Booster Bundle",
                "shop": "SHOP C",
                "price": 1050.0,
                "in_stock": True,
            },
        }
        signals = runner.price_watch_market_gap_signals(listings)

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["best"]["shop"], "SHOP A")
        self.assertEqual(signals[0]["next_best"]["shop"], "SHOP B")
        self.assertAlmostEqual(signals[0]["saving_pct"], 0.20)

    def test_price_watch_market_gap_shadow_ignores_small_gap_and_variant_formats(self):
        listings = {
            "small-a": {
                "set": "Crown Zenith",
                "type": "ETB",
                "name": "Crown Zenith Elite Trainer Box",
                "shop": "SHOP A",
                "price": 920.0,
                "in_stock": True,
            },
            "small-b": {
                "set": "Crown Zenith",
                "type": "ETB",
                "name": "Crown Zenith Elite Trainer Box",
                "shop": "SHOP B",
                "price": 1000.0,
                "in_stock": True,
            },
            "collection-a": {
                "set": "151",
                "type": "COLLECTION",
                "name": "151 Poster Collection",
                "shop": "SHOP A",
                "price": 300.0,
                "in_stock": True,
            },
            "collection-b": {
                "set": "151",
                "type": "COLLECTION",
                "name": "151 Binder Collection",
                "shop": "SHOP B",
                "price": 600.0,
                "in_stock": True,
            },
        }
        self.assertEqual(runner.price_watch_market_gap_signals(listings), [])

    def test_price_watch_market_gap_splits_pokemon_center_etb(self):
        listings = {
            "regular": {
                "set": "Surging Sparks",
                "type": "ETB",
                "name": "Surging Sparks Elite Trainer Box",
                "shop": "SHOP A",
                "price": 500.0,
                "in_stock": True,
            },
            "pc": {
                "set": "Surging Sparks",
                "type": "ETB",
                "name": "Surging Sparks Pokemon Center Elite Trainer Box",
                "shop": "SHOP B",
                "price": 1000.0,
                "in_stock": True,
            },
        }
        self.assertEqual(runner.price_watch_market_gap_signals(listings), [])

    def test_price_watch_signal_hook_blocks_small_drop_before_discord(self):
        calls = []

        def fake_alert(listing, old_price, combo=False):
            calls.append((listing, old_price, combo))
            return True

        def fake_process(*_args, **_kwargs):
            return {"ok": True}

        namespace = {
            "_price_watch_focus_alert": fake_alert,
            "process_price_watch": fake_process,
            "collect_price_watch_focus_listings": lambda _state, fresh_sources=None: {},
        }
        runner._install_price_watch_signal_policy(namespace)

        small = namespace["_price_watch_focus_alert"](
            {"shop": "TEST", "name": "151 ETB", "price": 920.0},
            1000.0,
            combo=False,
        )
        strong = namespace["_price_watch_focus_alert"](
            {"shop": "TEST", "name": "151 ETB", "price": 900.0},
            1000.0,
            combo=False,
        )

        self.assertFalse(small)
        self.assertTrue(strong)
        self.assertEqual(len(calls), 1)

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
