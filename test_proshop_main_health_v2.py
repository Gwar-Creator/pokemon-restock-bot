"""Offline status and migration tests for Proshop in the main restock lane."""
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
            d = state.setdefault("_source_health", {}).setdefault(key, {})
            d.update(fields)
            return d

        def original_fetch(key, old, fetcher, target):
            products = fetcher()
            updated(target, key, status="ok", last_count=len(products), consecutive_failures=0)
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

    def test_one_to_five_filtered_products_are_healthy_when_fetch_succeeds(self):
        self.assertEqual(self.ns["SOURCE_MIN_PRODUCTS"]["proshop"], 1)
        for n in [1, 2, 3, 4, 5]:
            products = self.ns["fetch_source_products"](
                "proshop", {}, lambda n=n: {str(x): {} for x in range(n)},
                self.state,
            )
            self.assertEqual(len(products), n)
            health = self.state["_source_health"]["proshop"]
            self.assertEqual(health["status"], "ok")
            self.assertEqual(health["category_count"], n)
            self.assertEqual(health["transport_status"], "available")
            self.assertEqual(health["coverage_status"], "unverified")
        self.assertEqual(self.messages, [])

    def test_small_valid_scan_does_not_fail_due_to_large_historic_cache(self):
        old = {str(i): {} for i in range(25)}
        products = self.ns["fetch_source_products"](
            "proshop", old, lambda: {"1": {}}, self.state
        )
        self.assertEqual(list(products), ["1"])
        self.assertEqual(self.state["_source_health"]["proshop"]["status"], "ok")

    def test_failed_transport_is_not_relabelled_healthy(self):
        def failing_fetch(source, old, fetcher, state):
            try:
                fetcher()
            except RuntimeError:
                self.ns["_source_health_update"](
                    state, source, status="failed", consecutive_failures=1
                )
                raise

        self.ns["fetch_source_products"] = failing_fetch
        with self.assertRaisesRegex(RuntimeError, "reader blocked"):
            self.ns["fetch_source_products"](
                "proshop", {}, lambda: (_ for _ in ()).throw(
                    RuntimeError("reader blocked")
                ), self.state,
            )
        self.assertEqual(self.state["_source_health"]["proshop"]["status"], "failed")

    def test_migration_does_not_send_false_new_alerts(self):
        fn = self.ns["process_proshop_changes"]
        fn({"old": {}}, {"1": {}, "2": {}, "3": {}, "4": {}})
        self.assertEqual(self.change_calls, [])
        fn({"old": {}, "1": {}, "2": {}, "3": {}}, {"1": {}, "2": {}, "3": {}, "4": {}})
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

    def test_known_details_do_not_fake_category_count(self):
        with patch(
            "restock_v2_runner.extend_with_known_details",
            side_effect=lambda current, old, state: {
                **current,
                "3478496": {"stock": "UDSOLGT", "fetch_via": "jina_verified_detail"},
                "3478497": {"stock": "UDSOLGT", "fetch_via": "jina_verified_detail"},
            },
        ):
            self.ns["fetch_source_products"](
                "proshop", {}, lambda: {str(x): {} for x in range(2)},
                self.state,
            )
        health = self.state["_source_health"]["proshop"]
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["category_count"], 2)
        self.assertEqual(health["coverage_status"], "unverified")
        self.assertEqual(health["last_count"], 4)

    def test_other_sources_unchanged(self):
        products = self.ns["fetch_source_products"](
            "other", {}, lambda: {"x": {}}, self.state
        )
        self.assertEqual(len(products), 1)
        self.assertEqual(self.state["_source_health"]["other"]["status"], "ok")
        self.assertEqual(self.messages, [])


if __name__ == "__main__":
    unittest.main()
