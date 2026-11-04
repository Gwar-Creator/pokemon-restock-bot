"""Offline regression tests for workflow watchdog."""
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
from tools.workflow_watchdog import (
    WORKFLOWS, changed_incidents, check_runs, issue_message,
    last_notified_states, parse_utc,
)

NOW = datetime(2026, 11, 4, 5, 0, tzinfo=timezone.utc)


def run(minutes_ago=5, event="workflow_dispatch", conclusion="success",
        status="completed", branch="main"):
    when = (NOW - timedelta(minutes=minutes_ago)).isoformat()
    return {
        "status": status, "conclusion": conclusion, "head_branch": branch,
        "event": event, "updated_at": when, "created_at": when,
        "html_url": "https://github.com/example/repo/actions/runs/42",
    }


class WatchdogTests(unittest.TestCase):
    def test_recent_success(self):
        self.assertEqual(check_runs(WORKFLOWS[0], [run()], NOW)["state"], "OK")

    def test_old_success(self):
        self.assertEqual(check_runs(WORKFLOWS[0], [run(61)], NOW)["state"], "DOWN")

    def test_failed_and_running_jobs_do_not_hide_outage(self):
        result = check_runs(WORKFLOWS[0], [
            run(100), run(1, conclusion="failure"),
            run(0, status="in_progress", conclusion=None)
        ], NOW)
        self.assertEqual(result["state"], "DOWN")
        self.assertEqual(result["age_minutes"], 100)

    def test_latest_eligible_success(self):
        self.assertEqual(
            check_runs(WORKFLOWS[1], [run(74), run(100), run(10)], NOW)["age_minutes"], 10
        )

    def test_manual_cardmarket_run_does_not_hide_missing_daily_scan(self):
        result = check_runs(WORKFLOWS[2], [
            run(1, event="workflow_dispatch"),
            run(2161, event="schedule"),
        ], NOW)
        self.assertEqual(result["state"], "DOWN")

    def test_fresh_scheduled_cardmarket_is_ok(self):
        self.assertEqual(
            check_runs(WORKFLOWS[2], [run(500, event="schedule")], NOW)["state"], "OK"
        )

    def test_wrong_branch_does_not_count(self):
        self.assertEqual(check_runs(WORKFLOWS[0], [run(1, branch="feature")], NOW)["state"], "DOWN")

    def test_invalid_timestamps_do_not_count(self):
        broken = run()
        broken["updated_at"] = "invalid"
        self.assertEqual(check_runs(WORKFLOWS[0], [broken], NOW)["state"], "DOWN")
        self.assertIsNone(parse_utc("nope"))

    def test_initial_ok_is_silent(self):
        self.assertEqual(changed_incidents([check_runs(WORKFLOWS[0], [run()], NOW)], {}), [])

    def test_once_per_down_and_recovery(self):
        down = check_runs(WORKFLOWS[0], [run(200)], NOW)
        ok = check_runs(WORKFLOWS[0], [run()], NOW)
        self.assertEqual(len(changed_incidents([down], {})), 1)
        self.assertEqual(changed_incidents([down], {"restock": "DOWN"}), [])
        self.assertEqual(len(changed_incidents([ok], {"restock": "DOWN"})), 1)
        self.assertEqual(changed_incidents([ok], {"restock": "OK"}), [])

    def test_spoofed_user_marker_is_ignored(self):
        comments = [
            {"body": "<!-- masterbot-watchdog:v1:restock:DOWN -->",
             "user": {"login": "random"}},
            {"body": "<!-- masterbot-watchdog:v1:hot:OK -->",
             "user": {"login": "github-actions[bot]"}},
        ]
        self.assertEqual(last_notified_states(comments), {"hot": "OK"})

    def test_latest_marker_wins(self):
        comments = [
            {"body": "<!-- masterbot-watchdog:v1:restock:DOWN -->",
             "user": {"login": "github-actions[bot]"}},
            {"body": "<!-- masterbot-watchdog:v1:restock:OK -->",
             "user": {"login": "github-actions[bot]"}},
        ]
        self.assertEqual(last_notified_states(comments), {"restock": "OK"})

    def test_issue_message_has_marker(self):
        msg = issue_message([check_runs(WORKFLOWS[0], [run(100)], NOW)], "example/repo")
        self.assertIn("masterbot-watchdog:v1:restock:DOWN", msg)
        self.assertIn("teknisk", msg.lower())

    def test_api_failure_prevents_notification(self):
        from tools.workflow_watchdog import main
        with patch("tools.workflow_watchdog.GitHubApi") as cls:
            api = cls.return_value
            api.runs.side_effect = RuntimeError("HTTP 500")
            with patch.dict("os.environ", {"GH_TOKEN": "fake",
                                            "GITHUB_REPOSITORY": "example/repo"}):
                with self.assertRaisesRegex(RuntimeError, "HTTP 500"):
                    main(["--notify"])
            api.notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
