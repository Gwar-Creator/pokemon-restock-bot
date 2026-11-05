"""Offline tests: Salling HOT never imports hidden Early Radar listings.

Exercise the actual BR/Bilka/Foetex source functions with mocked HTTP:
not just a string check. No network, Discord, or saved state.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urljoin
import unittest

SOURCE = Path(__file__).with_name("restock_bot_github.py")


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        return None

    def json(self):
        return {"results": [{"hits": self.data}]}


def source_function(name, namespace):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    exec(compile(ast.Module(body=[function], type_ignores=[]),
                 str(SOURCE), "exec"), namespace)
    return namespace[name]


class SallingHotExposureGuardTests(unittest.TestCase):
    @staticmethod
    def fake_hits():
        base = {
            "name": "Pokemon 151 Booster Bundle",
            "sku": "SKU",
            "sales_price": 249,
            "stock_count_online": 8,
            "in_stock_stores_count": 0,
            "product_url": "/pokemon/booster-bundle",
        }
        return [
            {**base, "id": "EXPOSED", "is_exposed": True},
            {**base, "id": "HIDDEN", "is_exposed": False},
            {**base, "id": "UNKNOWN"},
        ]

    def check_source(self, site):
        captured = []
        response = FakeResponse(self.fake_hits())

        def post(url, **kwargs):
            captured.append(kwargs["json"]["requests"][0]["params"])
            return response

        namespace = {
            "requests": SimpleNamespace(
                post=post, Session=lambda: object(),
            ),
            "urlencode": urlencode,
            "urljoin": urljoin,
            "BROWSER_HEADERS": {},
            "is_real_pokemon_tcg": lambda product: True,
            "safe_int": lambda value, default=0: int(value or default),
            "get_br_frontend_config": lambda: {
                "algolia_app_id": "demo", "algolia_api_key": "key",
            },
            "BR_ALGOLIA_INDEX": "demo",
            "BR_BASE": "https://www.br.dk/",
            "BR_HOME": "https://www.br.dk/",
            "get_salling_frontend_config": lambda key: {
                "algolia_app_id": "demo", "algolia_api_key": "key",
                "algolia_index": "demo",
            },
            "SALLING_SITES": {
                "bilka": {
                    "base": "https://www.bilka.dk/",
                    "home": "https://www.bilka.dk/",
                    "label": "BILKA",
                    "local_stores": {"1": "Bilka Kolding"},
                },
                "foetex": {
                    "base": "https://www.foetex.dk/",
                    "home": "https://www.foetex.dk/",
                    "label": "FØTEX",
                    "local_stores": {"1": "føtex Kolding"},
                },
            },
        }
        if site == "br":
            fetcher = source_function("get_br_products", namespace)
            products = fetcher()
        else:
            fetcher = source_function("get_salling_products", namespace)
            products = fetcher(site)
        self.assertEqual(list(products), ["EXPOSED"])
        self.assertIs(products["EXPOSED"]["is_exposed"], True)
        self.assertEqual(products["EXPOSED"]["online_count"], 8)
        self.assertEqual(len(captured), 1)
        filt = parse_qs(captured[0])["filters"][0]
        self.assertIn("is_exposed:true AND", filt)
        self.assertIn('AND (f_brand:"Pokemon" OR ', filt)
        self.assertIn('f_brand:"Pokémon" OR ', filt)
        self.assertIn('facets.productSeriesToys:"Pokémon")', filt)

    def test_br_does_not_send_hidden_products_to_hot(self):
        self.check_source("br")

    def test_bilka_does_not_send_hidden_products_to_hot(self):
        self.check_source("bilka")

    def test_foetex_does_not_send_hidden_products_to_hot(self):
        self.check_source("foetex")


if __name__ == "__main__":
    unittest.main()
