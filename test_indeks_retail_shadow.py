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


LOCAL_SAMPLE = {
    "id": "gid://shopify/Product/999",
    "title": "Pokemon 30th Anniversary Elite Trainer Box",
    "handle": "pokemon-30th-anniversary-elite-trainer-box",
    "updatedAt": "2026-09-21T10:00:00Z",
    "variants": {
        "nodes": [
            {
                "id": "gid://shopify/ProductVariant/123",
                "title": "Default Title",
                "sku": "30ETB",
                "barcode": "0196214100000",
                "availableForSale": False,
                "price": {"amount": "899.95", "currencyCode": "DKK"},
                "storeAvailability": {
                    "nodes": [
                        {
                            "available": True,
                            "quantityAvailable": 4,
                            "pickUpTime": "Usually ready in 2-4 days",
                            "location": {
                                "id": mod.LEGEKAEDEN_VEJEN_LOCATION_ID,
                                "name": "Legekæden Vejen",
                                "address": {
                                    "address1": "Rådhusstien 3 - 5",
                                    "city": "Vejen",
                                    "zip": "6600",
                                    "country": "Denmark",
                                },
                                "metafields": [
                                    None,
                                    {"key": "store_id", "value": mod.LEGEKAEDEN_VEJEN_STORE_ID},
                                ],
                            },
                        }
                    ]
                },
            }
        ]
    },
}


LOCAL_SAMPLE = {
    "id": "gid://shopify/Product/999",
    "title": "Pokemon 30th Anniversary Elite Trainer Box",
    "handle": "pokemon-30th-anniversary-elite-trainer-box",
    "updatedAt": "2026-09-21T10:00:00Z",
    "variants": {
        "nodes": [
            {
                "id": "gid://shopify/ProductVariant/9991",
                "title": "Default Title",
                "sku": "30-ETB",
                "barcode": "1234567890123",
                "availableForSale": True,
                "price": {"amount": "899.95", "currencyCode": "DKK"},
                "storeAvailability": {
                    "nodes": [
                        {
                            "available": True,
                            "quantityAvailable": 0,
                            "location": {
                                "id": mod.LEGEKAEDEN_VEJEN_LOCATION_ID,
                                "name": "Legekæden Vejen",
                                "address": {
                                    "address1": "Rådhusstien 3 - 5",
                                    "city": "Vejen",
                                    "zip": "6600",
                                    "country": "Denmark",
                                },
                                "metafields": [
                                    None,
                                    {"key": "store_id", "value": mod.LEGEKAEDEN_VEJEN_STORE_ID},
                                ],
                            },
                        },
                        {
                            "available": True,
                            "quantityAvailable": 9,
                            "location": {
                                "id": "gid://shopify/Location/other",
                                "name": "Legekæden Aars",
                                "address": {"city": "Aars"},
                                "metafields": [{"key": "store_id", "value": "86707"}],
                            },
                        },
                    ]
                },
            }
        ]
    },
}


class IndeksRetailShadowTests(unittest.TestCase):
    def test_extract_storefront_credentials_from_pickup_markup(self):
        markup = (
            '<div class="pickup-availability__storefront-data" '
            'data-shop-domain="legekaeden.myshopify.com" '
            'data-storefront-token="public-token"></div>'
        )
        self.assertEqual(
            mod._extract_storefront_credentials(markup),
            ("legekaeden.myshopify.com", "public-token"),
        )

    def test_local_storefront_product_uses_physical_vejen_quantity(self):
        handle, product = mod._normalise_local_storefront_product(LOCAL_SAMPLE)
        self.assertEqual(handle, LOCAL_SAMPLE["handle"])
        self.assertTrue(product["in_stock"])
        self.assertEqual(product["local_quantity"], 4)
        self.assertEqual(product["price"], 899.95)
        self.assertEqual(product["local_store_id"], mod.LEGEKAEDEN_VEJEN_STORE_ID)

    def test_local_storefront_does_not_treat_available_flag_as_physical_stock(self):
        sample = json.loads(json.dumps(LOCAL_SAMPLE))
        node = sample["variants"]["nodes"][0]["storeAvailability"]["nodes"][0]
        node["available"] = True
        node["quantityAvailable"] = 0
        _, product = mod._normalise_local_storefront_product(sample)
        self.assertFalse(product["in_stock"])
        self.assertEqual(product["local_quantity"], 0)

    def test_local_watch_alerts_on_zero_to_positive_for_watch_product(self):
        old = mod._normalise_local_storefront_product(
            json.loads(json.dumps(LOCAL_SAMPLE))
        )[1]
        old["in_stock"] = False
        old["local_quantity"] = 0
        new = dict(old, in_stock=True, local_quantity=3)
        sent = []

        count = mod._emit_local_alerts(
            {LOCAL_SAMPLE["handle"]: old},
            {LOCAL_SAMPLE["handle"]: new},
            sender=sent.append,
        )

        self.assertEqual(count, 1)
        self.assertEqual(len(sent), 1)
        self.assertIn("LEGEKÆDEN VEJEN", sent[0])
        self.assertIn("3 stk.", sent[0])
        self.assertIn("30th Anniversary Elite Trainer Box", sent[0])

    def test_local_first_scan_is_silent_baseline(self):
        product = mod._normalise_local_storefront_product(LOCAL_SAMPLE)[1]
        sent = []
        count = mod._emit_local_alerts(
            {},
            {LOCAL_SAMPLE["handle"]: product},
            sender=sent.append,
        )
        self.assertEqual(count, 0)
        self.assertEqual(sent, [])

    def test_extract_storefront_credentials_from_pickup_widget(self):
        html = (
            '<div class="pickup-availability__storefront-data" '
            'data-shop-domain="legekaeden.myshopify.com" '
            'data-storefront-token="public-token"></div>'
        )
        self.assertEqual(
            mod._extract_storefront_credentials(html),
            ("legekaeden.myshopify.com", "public-token"),
        )

    def test_vejen_location_matches_store_id_and_location_id(self):
        self.assertTrue(
            mod._is_vejen_location({
                "id": "other",
                "name": "Something",
                "address": {"city": "Elsewhere"},
                "metafields": [{"key": "store_id", "value": "13280"}],
            })
        )
        self.assertTrue(
            mod._is_vejen_location({
                "id": mod.LEGEKAEDEN_VEJEN_LOCATION_ID,
                "metafields": [],
            })
        )

    def test_local_stock_uses_physical_quantity_not_available_flag(self):
        handle, product = mod._normalise_local_storefront_product(LOCAL_SAMPLE)
        self.assertEqual(handle, LOCAL_SAMPLE["handle"])
        self.assertFalse(product["in_stock"])
        self.assertEqual(product["local_quantity"], 0)
        self.assertEqual(product["price"], 899.95)

        stocked = json.loads(json.dumps(LOCAL_SAMPLE))
        stocked["variants"]["nodes"][0]["storeAvailability"]["nodes"][0][
            "quantityAvailable"
        ] = 3
        _, product = mod._normalise_local_storefront_product(stocked)
        self.assertTrue(product["in_stock"])
        self.assertEqual(product["local_quantity"], 3)

    def test_local_30th_etb_restock_alert_passes_watch_filter(self):
        _, new_product = mod._normalise_local_storefront_product(LOCAL_SAMPLE)
        new_product["in_stock"] = True
        new_product["local_quantity"] = 4
        old_product = dict(new_product, in_stock=False, local_quantity=0)
        sent = []

        count = mod._emit_local_alerts(
            {LOCAL_SAMPLE["handle"]: old_product},
            {LOCAL_SAMPLE["handle"]: new_product},
            sender=sent.append,
        )

        self.assertEqual(count, 1)
        self.assertEqual(len(sent), 1)
        self.assertIn("LEGEKÆDEN VEJEN", sent[0])
        self.assertIn("4 stk.", sent[0])
        self.assertIn("30th Anniversary Elite Trainer Box", sent[0])

    def test_local_normal_etb_stays_filtered(self):
        product = {
            "name": "Journey Together Elite Trainer Box",
            "in_stock": True,
            "local_quantity": 2,
            "price": 599.95,
            "url": "https://example.test/journey-etb",
        }
        old = dict(product, in_stock=False, local_quantity=0)
        sent = []

        count = mod._emit_local_alerts(
            {"journey": old},
            {"journey": product},
            sender=sent.append,
        )

        self.assertEqual(count, 0)
        self.assertEqual(sent, [])

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

    def test_first_scan_writes_shadow_sources_and_live_logical_baseline_without_webhook(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"

            def fake_fetch(source_key):
                product = mod._normalise_product(source_key, SAMPLE)[1]
                return {SAMPLE["handle"]: product}

            with patch.object(mod, "STATE_FILE", state_file):
                status = mod.run_scan(fetcher=fake_fetch)
                state = json.loads(state_file.read_text(encoding="utf-8"))

            self.assertEqual(status, 0)
            self.assertEqual(state["mode"], "mixed")
            self.assertEqual(state["version"], 4)
            self.assertEqual(set(state["sources"]), {"legekaeden", "bogide"})
            self.assertTrue(all(row["mode"] == "shadow" for row in state["sources"].values()))
            self.assertEqual(state["local_sources"], {})
            self.assertEqual(state["comparison"]["shared_handles"], 1)
            logical = state["logical_sources"]["indeks_retail"]
            self.assertEqual(logical["mode"], "live")
            self.assertEqual(len(logical["products"]), 1)
            self.assertEqual(next(iter(logical["products"].values()))["source_count"], 2)

    def test_logical_restock_emits_one_deduplicated_backup_retail_alert(self):
        old_product = {
            "name": "Pokemon 151 Booster Bundle",
            "game": "POKÉMON",
            "price": 549.95,
            "in_stock": False,
            "preorder": False,
            "url": "https://www.legekaeden.dk/products/pokemon-151-booster-bundle",
            "source_count": 2,
        }
        new_product = dict(old_product, in_stock=True)
        sent = []

        count = mod._emit_backup_alerts(
            {"sku:151": old_product},
            {"sku:151": new_product},
            sender=sent.append,
        )

        self.assertEqual(count, 1)
        self.assertEqual(len(sent), 1)
        self.assertIn("INDEKS RETAIL", sent[0])
        self.assertIn("RESTOCK", sent[0])
        self.assertIn("Pokemon 151 Booster Bundle", sent[0])

    def test_local_first_scan_is_baseline_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"
            sent = []

            def fake_fetch(source_key):
                product = mod._normalise_product(source_key, SAMPLE)[1]
                return {SAMPLE["handle"]: product}

            def fake_local_fetch(_bootstrap):
                stocked = json.loads(json.dumps(LOCAL_SAMPLE))
                stocked["variants"]["nodes"][0]["storeAvailability"]["nodes"][0][
                    "quantityAvailable"
                ] = 5
                handle, product = mod._normalise_local_storefront_product(stocked)
                return {handle: product}

            with patch.object(mod, "STATE_FILE", state_file):
                status = mod.run_scan(
                    fetcher=fake_fetch,
                    sender=sent.append,
                    local_fetcher=fake_local_fetch,
                )
                state = json.loads(state_file.read_text(encoding="utf-8"))

            self.assertEqual(status, 0)
            self.assertEqual(sent, [])
            local = state["local_sources"][mod.LOCAL_SOURCE_KEY]
            self.assertEqual(local["mode"], "live")
            self.assertEqual(local["products"][LOCAL_SAMPLE["handle"]]["local_quantity"], 5)
            self.assertEqual(local["health"]["status"], "ok")

    def test_failed_source_preserves_old_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"
            old_product = mod._normalise_product("legekaeden", SAMPLE)[1]
            state_file.write_text(json.dumps({
                "version": 2,
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
