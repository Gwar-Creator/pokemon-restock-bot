import ast
import re
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_functions(filename, names, namespace):
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    ]
    exec(compile(ast.Module(body=selected, type_ignores=[]), filename, "exec"), namespace)
    return namespace


class V45RuleTests(unittest.TestCase):
    def test_new_catalog_alert_requires_actionable_status(self):
        namespace = load_functions(
            "restock_bot_github.py",
            {"new_product_alert_allowed"},
            {"safe_int": lambda value, default=0: int(value or default)},
        )
        allowed = namespace["new_product_alert_allowed"]

        self.assertFalse(allowed({"name": "New ETB", "in_stock": False}))
        self.assertTrue(allowed({"name": "New ETB", "preorder": True}))
        self.assertTrue(allowed({"name": "New Bundle", "online_count": 2}))
        self.assertTrue(
            allowed({"local_stocks": {"1662": {"stock": 3}}})
        )

    def test_price_filter_matches_known_restock_exclusions(self):
        namespace = load_functions(
            "restock_bot_github.py",
            {"get_price_watch_type"},
            {
                "re": re,
                "is_english_card_product": lambda name: True,
                "is_low_signal_accessory_name": lambda name: False,
            },
        )
        product_type = namespace["get_price_watch_type"]

        self.assertIsNone(product_type("Perfect Order Checklane Booster", "POKÉMON"))
        self.assertIsNone(product_type("Pokémon Battle Deck Booster", "POKÉMON"))
        self.assertEqual(
            product_type("Perfect Order Booster Pack", "POKÉMON"),
            "BOOSTER PACK",
        )

    def test_shopify_suppresses_unavailable_new_item_but_keeps_restock(self):
        sent = []
        namespace = load_functions(
            "restock_bot_github.py",
            {"process_shopify_changes"},
            {
                "filter_restock_alert_products": lambda products: products,
                "new_product_alert_allowed": lambda product: bool(
                    product.get("preorder") or product.get("in_stock")
                ),
                "SHOPIFY_SITES": {"shop": {"label": "SHOP"}},
                "send_discord": sent.append,
                "shopify_status_lines": lambda product: "status",
                "format_price": str,
            },
        )
        process = namespace["process_shopify_changes"]
        unavailable = {
            "name": "New ETB",
            "game": "POKÉMON",
            "in_stock": False,
            "price": 499,
            "url": "https://example.test/new",
        }

        process("shop", {}, {"new": unavailable})
        self.assertEqual(sent, [])

        available = dict(unavailable, in_stock=True)
        process("shop", {"new": unavailable}, {"new": available})
        self.assertEqual(len(sent), 1)
        self.assertIn("RESTOCK", sent[0])

    def test_local_stock_keeps_high_signal_sealed_products(self):
        namespace = load_functions(
            "local_stock_watch.py",
            {"pokemon_product_type"},
            {"re": re},
        )
        product_type = namespace["pokemon_product_type"]

        self.assertEqual(product_type("Ascended Heroes Booster Bundle"), "BOOSTER BUNDLE")
        self.assertEqual(product_type("Pokémon Booster Display"), "BOOSTER BOX")
        self.assertEqual(product_type("Victini Illustration Collection"), "COLLECTION")
        self.assertIsNone(product_type("Pokémon 9 Pocket Binder"))
        self.assertIsNone(product_type("Booster Bundle Display"))

    def test_woocommerce_retry_recovers_from_transient_failures(self):
        class RequestException(Exception):
            pass

        class Timeout(RequestException):
            pass

        class ConnectionError(RequestException):
            pass

        class Response:
            headers = {}

            def raise_for_status(self):
                return None

            def json(self):
                return []

        calls = []
        sleeps = []

        def fake_get(*args, **kwargs):
            calls.append((args, kwargs))
            if len(calls) < 3:
                raise Timeout("temporary")
            return Response()

        fake_requests = types.SimpleNamespace(
            get=fake_get,
            RequestException=RequestException,
            Timeout=Timeout,
            ConnectionError=ConnectionError,
        )
        namespace = load_functions(
            "restock_bot_github.py",
            {"fetch_woocommerce_search"},
            {
                "requests": fake_requests,
                "time": types.SimpleNamespace(sleep=sleeps.append),
                "BROWSER_HEADERS": {},
                "WOOCOMMERCE_API_PATH": "/wp-json/wc/store/v1/products",
                "WOOCOMMERCE_PAGE_SIZE": 100,
            },
        )

        result = namespace["fetch_woocommerce_search"](
            "https://example.test",
            "booster",
            request_retries=2,
            retry_backoff_seconds=1,
        )

        self.assertEqual(result, [])
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [1, 2])

    def test_cardmarket_has_no_price_history_fallback(self):
        source = (ROOT / "cardmarket_chase_watch.py").read_text(encoding="utf-8")
        self.assertNotIn('or os.getenv("PRICE_HISTORY_WEBHOOK_URL"', source)


if __name__ == "__main__":
    unittest.main()
