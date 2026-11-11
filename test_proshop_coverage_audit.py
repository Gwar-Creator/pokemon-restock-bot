"""Offline contract tests; no network, Discord, or state writes."""
import unittest
from unittest.mock import Mock

from tools.diagnostics.proshop_coverage_audit import audit, parse_hot_log, summarize


class ProshopCoverageAuditTests(unittest.TestCase):
    def test_ignores_offline_unit_test_logs_and_counts_real_cycles(self):
        log = """
        PROSHOP DETAIL 3478497: verificeret PÅ LAGER
        HOT PROSHOP reader: primary=1 · broad_added=0 · total=1
        2026-11-11T09:30:04Z HOT scan 1/3
        2026-11-11T09:30:10Z HOT PROSHOP reader: primary=4 · broad_added=0 · total=4
        2026-11-11T09:30:11Z PROSHOP DETAIL 3478497: verificeret UDSOLGT
        2026-11-11T09:30:13Z HOT PROSHOP: 4 friske relevante · 2 på lager
        2026-11-11T09:30:14Z HOT scan færdig: 7/7 kilder lykkedes
        2026-11-11T09:31:05Z HOT scan 2/3
        2026-11-11T09:31:12Z HOT PROSHOP reader: primary=0 · broad_added=0 · total=0
        2026-11-11T09:31:13Z HOT PROSHOP FEJL: Proshop has neither fresh catalogue cards nor verified SKU details
        2026-11-11T09:31:14Z HOT scan færdig: 5/7 kilder lykkedes
        2026-11-11T09:32:05Z HOT scan 3/3
        2026-11-11T09:32:12Z HOT PROSHOP BACKOFF: springer over i 40s (niveau 1)
        2026-11-11T09:32:14Z HOT scan færdig: 5/7 kilder lykkedes
        """
        cycles = parse_hot_log(log)
        self.assertEqual(len(cycles), 3)
        self.assertEqual([x["primary"] for x in cycles], [4, 0, None])
        self.assertEqual([x["fresh"] for x in cycles], [4, None, None])
        self.assertEqual(cycles[0]["detail_verified"], 1)
        self.assertEqual(cycles[0]["detail_in_stock"], 0)
        summary = summarize([{"conclusion": "success", "cycles": cycles}])
        self.assertEqual(summary["primary_catalog_zero"], 1)
        self.assertEqual(summary["proshop_failed"], 1)
        self.assertEqual(summary["proshop_backoff"], 1)
        self.assertEqual(summary["verified_detail_checks"], 1)
        self.assertEqual(summary["runs_with_proshop_failure_or_backoff"], 1)
        self.assertEqual(summary["github_green_runs"], 1)

    def test_zero_cycle_data_is_not_interpreted_as_healthy(self):
        report = summarize([{"conclusion": "success", "cycles": []}])
        self.assertEqual(report["cycles"], 0)
        self.assertEqual(report["proshop_failed"], 0)
        self.assertEqual(report["github_green_runs"], 1)

    def test_rejects_missing_credentials_and_invalid_limits(self):
        with self.assertRaises(ValueError):
            audit("Gwar-Creator/pokemon-restock-bot", "", 8)
        with self.assertRaises(ValueError):
            audit("bad repository", "TOKEN", 8)
        with self.assertRaises(ValueError):
            audit("Gwar-Creator/pokemon-restock-bot", "TOKEN", 13)

    def test_repository_api_is_read_only_and_uses_existing_job_logs(self):
        seen = []

        class Response:
            def __init__(self, data=None, text=""):
                self.data = data
                self.text = text
            def raise_for_status(self):
                return None
            def json(self):
                return self.data

        def fake_get(url, **kwargs):
            seen.append((url, kwargs))
            if url.endswith("runs?status=completed&per_page=1"):
                return Response({"workflow_runs": [
                    {"id": 10, "created_at": "2026-11-11", "conclusion": "success"}
                ]})
            if url.endswith("/actions/runs/10/jobs?per_page=100"):
                return Response({"jobs": [{"id": 20, "name": "hot-scan"}]})
            if url.endswith("/actions/jobs/20/logs"):
                return Response(text="HOT scan 1/1\nHOT PROSHOP reader: primary=2 · broad_added=0 · total=2\nHOT PROSHOP: 2 friske relevante · 1 på lager\n")
            raise AssertionError(url)

        session = Mock()
        session.get.side_effect = fake_get
        output = audit("Gwar-Creator/pokemon-restock-bot", "fake-token", 1, session)
        self.assertEqual(output["summary"]["primary_catalog_positive"], 1)
        self.assertEqual(len(seen), 3)
        self.assertTrue(all(url.startswith("https://api.github.com/repos/") for url, _ in seen))
        self.assertTrue(all(options.get("timeout") == 40 for _, options in seen))
        session.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
