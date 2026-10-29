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

    def test_coverage_three_to_five_is_degraded_not_green(self):
        self.assertEqual(self.ns["SOURCE_MIN_PRODUCTS"]["proshop"], 3)
        for n in [4, 4, 5]:
            self.ns["fetch_source_products"]("proshop", {}, lambda: {str(x): {} for x in range(n)}, self.state)
        self.assertEqual(self.state["_source_health"]["proshop"]["status"], "degraded")
        self.assertEqual(len(self.messages), 1)
        self.assertIn("DELVIST", self.messages[0])

    def test_recovery_only_after_six_and_no_false_green(self):
        self.state["_source_health"]["proshop"] = {"status": "failed", "consecutive_failures": 3}
        self.ns["send_scanner_health"](
            "✅ **SCANNERKILDE KØRER IGEN**\n**PROSHOP**\nProdukter fundet: 4"
        )
        self.assertEqual(self.messages, [])
        self.ns["fetch_source_products"]("proshop", {}, lambda: {str(x): {} for x in range(4)}, self.state)
        self.ns["fetch_source_products"]("proshop", {}, lambda: {str(x): {} for x in range(7)}, self.state)
        self.assertEqual(len(self.messages), 2)
        self.assertIn("GENOPRETTET", self.messages[-1])
        self.assertEqual(self.state["_source_health"]["proshop"]["status"], "ok")

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

    def test_detail_supplement_does_not_make_category_green(self):
        # Even when a confirmed extra known SKU raises total from 4 to 6,
        # the category still provides only four fresh catalogue products.
        with patch(
            "restock_v2_runner.extend_with_known_details",
            side_effect=lambda current, old, state: {
                **current,
                "3478496": {"stock": "UDSOLGT"},
                "3478497": {"stock": "UDSOLGT"},
            },
        ):
            self.ns["fetch_source_products"](
                "proshop", {}, lambda: {str(x): {} for x in range(4)},
                self.state,
            )
        self.assertEqual(self.state["_source_health"]["proshop"]["status"], "degraded")
        self.assertIn("Kategori 4", self.state["_source_health"]["proshop"]["last_error"])

    def test_other_sources_unchanged(self):
        products = self.ns["fetch_source_products"](
            "other", {}, lambda: {"x": {}}, self.state
        )
        self.assertEqual(len(products), 1)
        self.assertEqual(self.state["_source_health"]["other"]["status"], "ok")
        self.assertEqual(self.messages, [])


if __name__ == "__main__":
    unittest.main()
