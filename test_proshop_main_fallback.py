"""Offline tests for the real production Proshop catalogue fallback function.

The legacy scanner's source file contains executable startup code. Extract
only the fetch function so no live requests, state or Discord can run.
"""
import ast
from pathlib import Path
import unittest
from unittest.mock import patch


def get_isolated_proshop_fetch(primary, *, direct=None):
    source_file = Path(__file__).with_name("restock_bot_github.py")
    tree = ast.parse(source_file.read_text(encoding="utf-8"))
    fn = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "get_proshop_products"
    )
    isolated = compile(
        ast.Module(body=[fn], type_ignores=[]),
        str(source_file), "exec",
    )
    namespace = {
        "get_proshop_products_via_reader": primary,
        "curl_requests": direct,
        "PROSHOP_BASE": "https://www.proshop.dk",
        "PROSHOP_URL": "https://www.proshop.dk/pokemon-kort",
        "_proshop_is_tcg_text": lambda title: "booster" in title.lower(),
        "BROWSER_HEADERS": {},
    }
    exec(isolated, namespace)
    return namespace["get_proshop_products"]


def product(sku, via="jina_reader", stock="UDSOLGT"):
    return {
        "name": "Pokemon TCG Booster Bundle",
        "url": f"https://www.proshop.dk/Pokemon/Booster-Bundle/{sku}",
        "stock": stock,
        "price": None,
        "fetch_via": via,
    }


class ProductionProshopReaderFallbackTests(unittest.TestCase):
    def test_small_valid_category_is_supplemented_without_alert_changes(self):
        sku_a = product("1111111")
        sku_b = product("2222222")
        source = get_isolated_proshop_fetch(lambda: {"1111111": sku_a})
        with patch("proshop_reader_v2.fetch_verified_proshop_reader_catalog",
                   side_effect=[{"2222222": sku_b}, {"2222222": sku_b}]) as fetch:
            result = source()
        self.assertEqual(set(result), {"1111111", "2222222"})
        self.assertEqual(result["1111111"]["fetch_via"], "jina_reader")
        self.assertEqual(result["2222222"]["fetch_via"], "jina_broad_reader")
        self.assertEqual(fetch.call_count, 2)

    def test_healthy_category_avoids_extra_reader_requests(self):
        items = {str(i): product(str(i)) for i in range(3)}
        source = get_isolated_proshop_fetch(lambda: items)
        with patch("proshop_reader_v2.fetch_verified_proshop_reader_catalog") as fetch:
            result = source()
        self.assertEqual(result, items)
        fetch.assert_not_called()

    def test_blocked_category_recovers_from_verified_brand(self):
        def unavailable():
            raise RuntimeError("CAPTCHA")
        source = get_isolated_proshop_fetch(unavailable)
        with patch("proshop_reader_v2.fetch_verified_proshop_reader_catalog",
                   side_effect=[{"1111111": product("1111111")}, RuntimeError("blocked")]):
            result = source()
        self.assertEqual(list(result), ["1111111"])
        self.assertEqual(result["1111111"]["fetch_via"], "jina_broad_reader")

    def test_all_blocked_sources_fail_closed_no_fake_stock(self):
        def unavailable():
            raise RuntimeError("CAPTCHA")
        source = get_isolated_proshop_fetch(unavailable)
        with patch("proshop_reader_v2.fetch_verified_proshop_reader_catalog",
                   side_effect=RuntimeError("CAPTCHA")) as fetch:
            with self.assertRaisesRegex(RuntimeError, "Proshop utilgængelig"):
                source()
        self.assertEqual(fetch.call_count, 2)


if __name__ == "__main__":
    unittest.main()
