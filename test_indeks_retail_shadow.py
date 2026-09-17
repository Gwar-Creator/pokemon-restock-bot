import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import indeks_retail_shadow as mod


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.payloads.pop(0))


SAMPLE = {
    "id": 123,
    "title": "Pokémon TCG: Mega Evolution Elite Trainer Box",
    "handle": "pokemon-mega-evolution-etb",
    "tags": ["Pokemon", "TCG"],
    "published_at": "2026-09-01T00:00:00+02:00",
    "updated_at": "2026-09-16T20:00:00+02:00",
    "variants": [
        {"id": 1, "available": False, "price": "599.95", "sku": "ABC", "barcode": "111"},
        {"id": 2, "available": True, "price": "549.95", "sku": "ABC2", "barcode": "222"},
    ],
}


class IndeksRetailShadowTests(unittest.TestCase):
    def test_normalise_uses_cheapest_available_variant(self):
        handle, product = mod._normalise_product("legekaeden", SAMPLE)
        self.assertEqual(handle, SAMPLE["handle"])
        self.assertTrue(product["in_stock"])
        self.assertEqual(product["price"], 549.95)
        self.assertEqual(product["variant_id"], "2")
        self.assertIn("ABC2", product["skus"])
        self.assertEqual(product["url"], "https://www.legekaeden.dk/products/pokemon-mega-evolution-etb")

    def test_fetch_source_reads_shopify_collection_feed(self):
        session = FakeSession([{"products": [SAMPLE]}])
        products = mod.fetch_source("bogide", session=session)
        self.assertIn(SAMPLE["handle"], products)
        self.assertEqual(len(session.calls), 1)
        url, kwargs = session.calls[0]
        self.assertEqual(url, "https://www.bog-ide.dk/collections/pokemon-tcg/products.json")
        self.assertEqual(kwargs["params"]["limit"], 250)

    def test_comparison_detects_shared_catalog_and_stock_difference(self):
        left = mod._normalise_product("legekaeden", SAMPLE)[1]
        right = dict(mod._normalise_product("bogide", SAMPLE)[1])
        right["in_stock"] = False
        result = mod._comparison({
            "legekaeden": {"products": {SAMPLE["handle"]: left}},
            "bogide": {"products": {SAMPLE["handle"]: right}},
        })
        self.assertEqual(result["shared_handles"], 1)
        self.assertGreaterEqual(result["shared_skus_or_barcodes"], 1)
        self.assertEqual(result["stock_disagreements"], [SAMPLE["handle"]])

    def test_logical_catalogue_merges_same_product_across_storefronts(self):
        left = mod._normalise_product("legekaeden", SAMPLE)[1]
        right = dict(mod._normalise_product("bogide", SAMPLE)[1])
        right["price"] = 529.95
        sources = {
            "legekaeden": {"products": {SAMPLE["handle"]: left}},
            "bogide": {"products": {SAMPLE["handle"]: right}},
        }

        merged = mod._merge_logical_catalogue(sources)

        self.assertEqual(len(merged), 1)
        product = next(iter(merged.values()))
        self.assertEqual(product["source_count"], 2)
        self.assertEqual(set(product["retailers"]), {"legekaeden", "bogide"})
        self.assertTrue(product["in_stock"])
        self.assertEqual(product["price"], 529.95)
        self.assertEqual(product["url"], right["url"])

    def test_logical_catalogue_prefers_in_stock_offer_over_cheaper_sold_out_offer(self):
        left = mod._normalise_product("legekaeden", SAMPLE)[1]
        right = dict(mod._normalise_product("bogide", SAMPLE)[1])
        left["price"] = 549.95
        left["in_stock"] = True
        right["price"] = 499.95
        right["in_stock"] = False
        sources = {
            "legekaeden": {"products": {SAMPLE["handle"]: left}},
            "bogide": {"products": {SAMPLE["handle"]: right}},
        }

        merged = mod._merge_logical_catalogue(sources)
        product = next(iter(merged.values()))

        self.assertEqual(product["price"], 549.95)
        self.assertEqual(product["url"], left["url"])

    def test_logical_catalogue_keeps_store_specific_product(self):
        unique = dict(SAMPLE)
        unique["id"] = 999
        unique["title"] = "Pokémon TCG: Unique Collection Box"
        unique["handle"] = "pokemon-unique-collection-box"
        unique["variants"] = [
            {"id": 9, "available": True, "price": "299.95", "sku": "UNIQUE", "barcode": "999"}
        ]
        left = mod._normalise_product("legekaeden", SAMPLE)[1]
        right = mod._normalise_product("bogide", unique)[1]
        sources = {
            "legekaeden": {"products": {SAMPLE["handle"]: left}},
            "bogide": {"products": {unique["handle"]: right}},
        }

        merged = mod._merge_logical_catalogue(sources)

        self.assertEqual(len(merged), 2)
        self.assertEqual(sorted(product["source_count"] for product in merged.values()), [1, 1])

    def test_first_scan_is_shadow_and_writes_logical_baseline_without_webhook(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"

            def fake_fetch(source_key):
                product = mod._normalise_product(source_key, SAMPLE)[1]
                return {SAMPLE["handle"]: product}

            with patch.object(mod, "STATE_FILE", state_file):
                status = mod.run_scan(fetcher=fake_fetch)
                state = json.loads(state_file.read_text(encoding="utf-8"))

            self.assertEqual(status, 0)
            self.assertEqual(state["mode"], "shadow")
            self.assertEqual(state["version"], 2)
            self.assertEqual(set(state["sources"]), {"legekaeden", "bogide"})
            self.assertEqual(state["comparison"]["shared_handles"], 1)
            logical = state["logical_sources"]["indeks_retail"]
            self.assertEqual(len(logical["products"]), 1)
            self.assertEqual(next(iter(logical["products"].values()))["source_count"], 2)

    def test_failed_source_preserves_old_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"
            old_product = mod._normalise_product("legekaeden", SAMPLE)[1]
            state_file.write_text(json.dumps({
                "version": 1,
                "mode": "shadow",
                "sources": {
                    "legekaeden": {
                        "label": "LEGEKÆDEN",
                        "mode": "shadow",
                        "health": {"status": "ok", "observed_count": 1},
                        "products": {SAMPLE["handle"]: old_product},
                    }
                },
                "comparison": {},
            }), encoding="utf-8")

            def fake_fetch(source_key):
                if source_key == "legekaeden":
                    raise RuntimeError("temporary source failure")
                return {}

            with patch.object(mod, "STATE_FILE", state_file):
                mod.run_scan(fetcher=fake_fetch)
                state = json.loads(state_file.read_text(encoding="utf-8"))

            self.assertIn(SAMPLE["handle"], state["sources"]["legekaeden"]["products"])
            self.assertEqual(state["sources"]["legekaeden"]["health"]["status"], "failed")
            logical = state["logical_sources"]["indeks_retail"]["products"]
            self.assertEqual(len(logical), 1)


if __name__ == "__main__":
    unittest.main()
