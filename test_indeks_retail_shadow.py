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

    def test_first_scan_is_shadow_and_writes_baseline_without_webhook(self):
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
            self.assertEqual(set(state["sources"]), {"legekaeden", "bogide"})
            self.assertEqual(state["comparison"]["shared_handles"], 1)

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


if __name__ == "__main__":
    unittest.main()
