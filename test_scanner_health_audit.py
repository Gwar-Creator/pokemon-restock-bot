import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import scanner_health_audit as audit


class ScannerHealthAuditTests(unittest.TestCase):
    def _row(self, health, products=7, minimum=5):
        state = {
            "coolshop": {str(i): {} for i in range(products)},
            "_source_health": {"coolshop": health} if health is not None else {},
        }
        return audit.inspect_sources(state, {"coolshop": minimum})[0]

    def test_healthy_source(self):
        row = self._row({"status": "ok", "consecutive_failures": 0})
        self.assertEqual(row["status"], "OK")
        self.assertEqual(row["cached_count"], 7)

    def test_transient_failure_is_degraded_not_down(self):
        row = self._row({"status": "failed", "consecutive_failures": 1})
        self.assertEqual(row["status"], "DEGRADED")

    def test_three_failures_are_down_even_with_cached_products(self):
        row = self._row({"status": "failed", "consecutive_failures": 3})
        self.assertEqual(row["status"], "DOWN")
        self.assertEqual(row["cached_count"], 7)

    def test_success_with_low_cached_count_is_degraded_not_down(self):
        row = self._row({"status": "ok", "consecutive_failures": 0}, products=3)
        self.assertEqual(row["status"], "DEGRADED")

    def test_missing_source_health_is_unknown_not_healthy(self):
        row = self._row(None, products=20)
        self.assertEqual(row["status"], "UNKNOWN")

    def test_invalid_failure_counter_does_not_crash(self):
        row = self._row({"status": "failed", "consecutive_failures": "??"})
        self.assertEqual(row["status"], "UNKNOWN")

    def test_strict_exit_is_opt_in_and_summary_is_generated(self):
        state = {
            "coolshop": {"a": {}},
            "_source_health": {"coolshop": {"status": "failed", "consecutive_failures": 3}},
        }
        with tempfile.TemporaryDirectory() as directory:
            summary = os.path.join(directory, "summary.md")
            with (
                patch.object(audit, "load_state", return_value=state),
                patch.object(audit, "SOURCE_MINIMUMS", {"coolshop": 1}),
                patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": summary}),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(audit.main([]), 0)
                self.assertEqual(audit.main(["--strict"]), 1)
            with open(summary, encoding="utf-8") as file:
                content = file.read()
            self.assertIn("DOWN", content)
            self.assertIn("not** confirmation", content)
            self.assertIn("| coolshop | DOWN |", content)


if __name__ == "__main__":
    unittest.main()
