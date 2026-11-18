"""Offline Proshop source-health regressions. No Proshop requests or Discord."""

import unittest
from unittest.mock import patch

from restock_v2_runner import _install_proshop_reader_v2


class ProshopMainHealthTests(unittest.TestCase):
    def setUp(self):
        mocked = patch(
            "restock_v2_runner.extend_with_known_details",
            side_effect=lambda current, old, state: current,
        )
        mocked.start()
        self.addCleanup(mocked.stop)
        self.messages = []
        self.change_calls = []
        self.state = {"_source_health": {}}

        def updated(state, key, **fields):
            entry = state.setdefault("_source_health", {}).setdefault(key, {})
            entry.update(fields)
            return entry

        def original_fetch(key, old, fetcher, target):
            # Mirror the legacy count/drop guard so tests catch accidental
            # reintroduction of strict 3/6 limits or historical drift errors.
            try:
                products = fetcher()
                if not isinstance(products, dict):
                    raise RuntimeError("not a product dictionary")
                minimum = self.ns["SOURCE_MIN_PRODUCTS"].get(key, 1)
                if len(products) < minimum:
                    raise RuntimeError(f"too few products: {len(products)} < {minimum}")
                if len(old) >= minimum and len(products) < len(old) * 0.30:
                    raise RuntimeError("suspicious historic drop")
            except Exception as exc:
                prev = (target.get("_source_health") or {}).get(key) or {}
                updated(target, key, status="failed",
                        consecutive_failures=prev.get("consecutive_failures", 0) + 1,
                        last_error=str(exc))
                raise
            prev = (target.get("_source_health") or {}).get(key) or {}
            if prev.get("consecutive_failures", 0) >= 3:
                self.ns["send_scanner_health"](
                    "✅ **SCANNERKILDE KØRER IGEN**\n"
                    f"**{key.upper()}**\nProdukter fundet: {len(products)}"
                )
            updated(target, key, status="ok", last_count=len(products),
                    consecutive_failures=0, last_error="")
            return products

        self.ns = {
            "_proshop_is_tcg_text": lambda name: "booster" in name.lower(),
            "SOURCE_MIN_PRODUCTS": {"proshop": 2, "other": 2},
            "process_proshop_changes": lambda old, new: self.change_calls.append((old, new)),
            "fetch_source_products": original_fetch,
            "_source_health_update": updated,
            "send_scanner_health": lambda message: self.messages.append(message),
        }
        _install_proshop_reader_v2(self.ns)

    def fetch(self, key="proshop", old=None, items=None):
        if items is None:
            items = {"sku-1": {"stock": "PÅ LAGER", "fetch_via": "jina_reader"}}
        return self.ns["fetch_source_products"](
            key, old or {}, lambda: items, self.state
        )

    def test_single_valid_tcg_card_is_not_a_transport_failure(self):
        self.assertEqual(self.ns["SOURCE_MIN_PRODUCTS"]["proshop"], 1)
        self.fetch()
        health = self.state["_source_health"]["proshop"]
        self.assertEqual(health["consecutive_failures"], 0)
        self.assertEqual(health["category_count"], 1)
        self.assertEqual(health["catalogue_status"], "available")
        self.assertEqual(health["coverage_status"], "unverified")
        self.assertEqual(health["usable_fresh_count"], 1)
        self.assertEqual(health["status"], "degraded")
        self.assertEqual(len(self.messages), 1)
        self.assertIn("DÆKNING UVIS", self.messages[0])

    def test_one_to_seven_products_never_claim_full_coverage(self):
        self.fetch()
        for n in (1, 4, 7):
            items = {str(k): {"stock": "UDSOLGT"} for k in range(n)}
            self.fetch(items=items)
        health = self.state["_source_health"]["proshop"]
        self.assertEqual(health["category_count"], 7)
        self.assertEqual(health["coverage_status"], "unverified")
        self.assertEqual(health["status"], "degraded")
        self.assertEqual(len(self.messages), 1)

    def test_recovery_does_not_claim_full_catalogue_is_back(self):
        self.state["_source_health"]["proshop"] = {
            "status": "failed", "consecutive_failures": 49
        }
        self.ns["send_scanner_health"](
            "✅ **SCANNERKILDE KØRER IGEN**\n**PROSHOP**\nProdukter fundet: 1"
        )
        self.assertEqual(self.messages, [])
        self.fetch()
        self.assertEqual(len(self.messages), 1)
        self.assertIn("DÆKNING UVIS", self.messages[0])
        self.assertNotIn("GENOPRETTET", self.messages[0])
        self.assertEqual(
            self.state["_source_health"]["proshop"]["consecutive_failures"], 0
        )

    def test_historic_cache_does_not_trigger_drift_failure(self):
        # A category with one product cannot be compared to a cache with
        # products discovered by separate brand/search pages in past scans.
        old = {str(k): {"stock": "UDSOLGT"} for k in range(19)}
        fresh = {"1": {"stock": "PÅ LAGER"}}
        self.fetch(old=old, items=fresh)
        self.assertEqual(
            self.state["_source_health"]["proshop"]["last_count"], 1
        )
        self.assertEqual(
            self.state["_source_health"]["proshop"]["category_count"], 1
        )

    def test_zero_catalogue_and_no_details_still_fails(self):
        with self.assertRaisesRegex(RuntimeError, "too few products"):
            self.fetch(items={})
        health = self.state["_source_health"]["proshop"]
        self.assertEqual(health["status"], "failed")
        self.assertEqual(health["consecutive_failures"], 1)

    def test_transport_exception_is_not_masked(self):
        def broken():
            raise RuntimeError("Jina Reader blocked")
        with self.assertRaisesRegex(RuntimeError, "Jina Reader blocked"):
            self.ns["fetch_source_products"](
                "proshop", {}, broken, self.state
            )
        self.assertEqual(
            self.state["_source_health"]["proshop"]["status"], "failed"
        )

    def test_known_details_do_not_prove_full_catalogue(self):
        with patch(
            "restock_v2_runner.extend_with_known_details",
            side_effect=lambda current, old, state: {
                **current,
                "3478496": {
                    "stock": "UDSOLGT", "fetch_via": "jina_verified_detail"
                },
                "3478497": {
                    "stock": "PÅ LAGER", "fetch_via": "jina_verified_detail"
                },
            },
        ):
            self.fetch(items={"sku-1": {"stock": "UKENDT"}})
        health = self.state["_source_health"]["proshop"]
        self.assertEqual(health["category_count"], 1)
        self.assertEqual(health["verified_detail_count"], 2)
        self.assertEqual(health["usable_fresh_count"], 2)
        self.assertEqual(health["coverage_status"], "unverified")

    def test_migration_does_not_send_false_new_alerts(self):
        fn = self.ns["process_proshop_changes"]
        fn({"old": {}}, {"1": {}, "2": {}, "3": {}, "4": {}})
        self.assertEqual(self.change_calls, [])
        fn({"old": {}, "1": {}, "2": {}, "3": {}},
           {"1": {}, "2": {}, "3": {}, "4": {}})
        self.assertEqual(len(self.change_calls), 1)

    def test_known_old_products_baseline_without_new_alert(self):
        old = {"3421827": {"stock": "PÅ LAGER", "fetch_via": "jina_reader"}}
        fresh = {
            "3421827": {"stock": "PÅ LAGER", "fetch_via": "jina_reader"},
            "3478497": {"stock": "BESTILLINGSVARE", "fetch_via": "jina_reader"},
        }
        self.ns["process_proshop_changes"](old, fresh)
        prior, current = self.change_calls[-1]
        self.assertEqual(prior["3478497"]["stock"], "BESTILLINGSVARE")
        self.assertIn("3478497", current)

    def test_other_sources_unchanged(self):
        self.fetch(key="other", items={"a": {}, "b": {}})
        self.assertEqual(self.state["_source_health"]["other"]["status"], "ok")
        self.assertEqual(len(self.messages), 0)
        self.assertEqual(self.ns["SOURCE_MIN_PRODUCTS"]["other"], 2)


if __name__ == "__main__":
    unittest.main()
