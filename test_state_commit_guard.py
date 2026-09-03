import unittest

from state_commit_guard import (
    compact_hot_state,
    compact_local_stock,
    compact_restock_state,
    compact_updated_at_only,
)


class StateCommitGuardTests(unittest.TestCase):
    def test_local_stock_reuses_timestamp_for_unchanged_product(self):
        old = {
            "version": 1,
            "products": {"x": {"stock": 2, "observed_at": "old"}},
            "last_run_errors": 0,
        }
        new = {
            "version": 1,
            "products": {"x": {"stock": 2, "observed_at": "new"}},
            "last_run_errors": 0,
        }
        result = compact_local_stock(old, new)
        self.assertEqual(result["products"]["x"]["observed_at"], "old")

    def test_local_stock_keeps_timestamp_when_stock_changed(self):
        old = {"products": {"x": {"stock": 2, "observed_at": "old"}}}
        new = {"products": {"x": {"stock": 3, "observed_at": "new"}}}
        result = compact_local_stock(old, new)
        self.assertEqual(result["products"]["x"]["observed_at"], "new")

    def test_restock_throttles_heartbeat_but_reuses_health_timestamps(self):
        old = {
            "_last_full_scan_epoch": 100,
            "_source_health": {
                "shop": {
                    "status": "ok",
                    "last_count": 10,
                    "last_attempt": "old-a",
                    "last_success": "old-s",
                }
            },
        }
        new = {
            "_last_full_scan_epoch": 200,
            "_source_health": {
                "shop": {
                    "status": "ok",
                    "last_count": 10,
                    "last_attempt": "new-a",
                    "last_success": "new-s",
                }
            },
        }
        result = compact_restock_state(old, new)
        self.assertEqual(result["_last_full_scan_epoch"], 100)
        self.assertEqual(result["_source_health"]["shop"]["last_attempt"], "old-a")
        self.assertEqual(result["_source_health"]["shop"]["last_success"], "old-s")

    def test_restock_refreshes_heartbeat_after_15_minutes(self):
        old = {"_last_full_scan_epoch": 100, "_source_health": {}}
        new = {"_last_full_scan_epoch": 1001, "_source_health": {}}
        result = compact_restock_state(old, new)
        self.assertEqual(result["_last_full_scan_epoch"], 1001)

    def test_restock_keeps_fresh_health_timestamp_on_real_health_change(self):
        old = {
            "_source_health": {
                "shop": {
                    "status": "ok",
                    "consecutive_failures": 0,
                    "last_attempt": "old-a",
                    "last_success": "old-s",
                }
            }
        }
        new = {
            "_source_health": {
                "shop": {
                    "status": "failed",
                    "consecutive_failures": 1,
                    "last_attempt": "new-a",
                    "last_success": "old-s",
                }
            }
        }
        result = compact_restock_state(old, new)
        self.assertEqual(result["_source_health"]["shop"]["last_attempt"], "new-a")

    def test_hot_reuses_success_and_updated_at_when_only_heartbeat_changed(self):
        old = {
            "updated_at": "old-u",
            "source_controls": {
                "br": {"backoff_level": 0, "last_success_at": "old-s"}
            },
        }
        new = {
            "updated_at": "new-u",
            "source_controls": {
                "br": {"backoff_level": 0, "last_success_at": "new-s"}
            },
        }
        result = compact_hot_state(old, new)
        self.assertEqual(result["updated_at"], "old-u")
        self.assertEqual(result["source_controls"]["br"]["last_success_at"], "old-s")

    def test_hot_keeps_current_timestamp_when_backoff_changed(self):
        old = {
            "updated_at": "old-u",
            "source_controls": {
                "br": {"backoff_level": 0, "last_success_at": "old-s"}
            },
        }
        new = {
            "updated_at": "new-u",
            "source_controls": {
                "br": {"backoff_level": 1, "last_success_at": "new-s"}
            },
        }
        result = compact_hot_state(old, new)
        self.assertEqual(result["updated_at"], "new-u")
        self.assertEqual(result["source_controls"]["br"]["last_success_at"], "new-s")

    def test_updated_at_only_reuses_timestamp_if_nothing_else_changed(self):
        old = {"version": 1, "updated_at": 1, "products": {"x": 1}}
        new = {"version": 1, "updated_at": 2, "products": {"x": 1}}
        result = compact_updated_at_only(old, new)
        self.assertEqual(result["updated_at"], 1)


if __name__ == "__main__":
    unittest.main()
