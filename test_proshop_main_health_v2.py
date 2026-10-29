"""Offline status and migration tests for Proshop in the main restock lane."""
import unittest

from restock_v2_runner import _install_proshop_reader_v2


class ProshopMainHealthTests(unittest.TestCase):
    def setUp(self):
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

    def test_other_sources_unchanged(self):
        products = self.ns["fetch_source_products"](
            "other", {}, lambda: {"x": {}}, self.state
        )
        self.assertEqual(len(products), 1)
        self.assertEqual(self.state["_source_health"]["other"]["status"], "ok")
        self.assertEqual(self.messages, [])


if __name__ == "__main__":
    unittest.main()
