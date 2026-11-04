#!/usr/bin/env python3
"""Independent watchdog. Report missing successful runs once per transition.

No Discord, no stock state writes, no new secrets; GitHub issue #62 stores the
last notification via bot-authored issue comments.
"""
from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote
import requests

ISSUE_NUMBER = 62
MARKER_RE = re.compile(r"<!-- masterbot-watchdog:v1:([a-z-]+):(DOWN|OK) -->")
BOT_AUTHOR = "github-actions[bot]"


@dataclass(frozen=True)
class WatchedWorkflow:
    key: str
    label: str
    filename: str
    stale_after_minutes: int
    allowed_events: tuple[str, ...] = ()


WORKFLOWS = (
    WatchedWorkflow("restock", "Pokemon Restock Bot", "restock.yml", 60),
    WatchedWorkflow("hot", "Pokemon HOT Restock", "hot_restock.yml", 75),
    # Manual Cardmarket webhook tests can finish green without scanning cards.
    WatchedWorkflow("cardmarket", "Card Market Watch", "cardmarket.yml", 2160, ("schedule",)),
)


def parse_utc(value):
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None


def check_runs(workflow, runs, now=None):
    """Check the most recent eligible completed success, not newest green job."""
    current = now or datetime.now(timezone.utc)
    successes = []
    for run in runs:
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            continue
        if run.get("head_branch") != "main":
            continue
        if workflow.allowed_events and run.get("event") not in workflow.allowed_events:
            continue
        finished = parse_utc(run.get("updated_at") or run.get("created_at"))
        if finished:
            successes.append((finished, run))

    if not successes:
        return {
            "workflow": workflow,
            "state": "DOWN",
            "age_minutes": None,
            "url": None,
            "detail": "No completed successful eligible run returned by GitHub",
        }

    last_time, last_run = max(successes, key=lambda item: item[0])
    age = max(0, int((current - last_time).total_seconds() / 60))
    return {
        "workflow": workflow,
        "state": "DOWN" if age > workflow.stale_after_minutes else "OK",
        "age_minutes": age,
        "url": last_run.get("html_url"),
        "detail": f"Last successful run {age} min ago, limit {workflow.stale_after_minutes} min",
    }


def last_notified_states(comments):
    """Only bot-authored markers are trusted for deduplication."""
    states = {}
    for comment in comments:
        if (comment.get("user") or {}).get("login") != BOT_AUTHOR:
            continue
        for key, status in MARKER_RE.findall(comment.get("body") or ""):
            states[key] = status
    return states


def changed_incidents(results, previous):
    """Initial healthy status stays silent; one DOWN and one recovery comment."""
    changed = []
    for result in results:
        key, state = result["workflow"].key, result["state"]
        prior = previous.get(key)
        if (state == "DOWN" and prior != "DOWN") or (state == "OK" and prior == "DOWN"):
            changed.append(result)
    return changed


def issue_message(changed, repo):
    lines = [
        "### MasterBot – automatisk driftsalarm",
        "",
        "Dette er en teknisk driftsbesked, ikke en anbefaling om Pokémon-køb.",
        "",
    ]
    for row in changed:
        workflow = row["workflow"]
        if row["state"] == "DOWN":
            lines.append(f"- **FEJL: {workflow.label}**: {row['detail']}.")
        else:
            lines.append(f"- **GENOPRETTET: {workflow.label}**: {row['detail']}.")
        if row["url"]:
            lines.append(f"  - [Seneste godkendte kørsel]({row['url']})")
        lines.append(f"<!-- masterbot-watchdog:v1:{workflow.key}:{row['state']} -->")
    lines.extend(("", f"Automatisk statuskontrol i {repo}. Én besked per ændring."))
    return "\n".join(lines)


class GitHubApi:
    def __init__(self, repo, token):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("Invalid GITHUB_REPOSITORY")
        self.repo = repo
        self.base = f"https://api.github.com/repos/{repo}"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def get(self, path, params=None):
        response = self.session.get(self.base + path, params=params, timeout=25)
        response.raise_for_status()
        return response.json()

    def runs(self, filename):
        result = self.get(
            f"/actions/workflows/{quote(filename)}/runs",
            {"branch": "main", "per_page": 50},
        )
        rows = result.get("workflow_runs")
        if not isinstance(rows, list):
            raise RuntimeError(f"Invalid GitHub runs API for {filename}")
        return rows

    def recent_issue_comments(self):
        issue = self.get(f"/issues/{ISSUE_NUMBER}")
        if issue.get("state") != "open":
            raise RuntimeError(f"Watchdog issue #{ISSUE_NUMBER} is closed")
        total = max(0, int(issue.get("comments") or 0))
        last_page = max(1, (max(total, 1) - 1) // 100 + 1)
        pages = sorted({max(1, last_page - 1), last_page})
        comments = []
        for page in pages:
            data = self.get(
                f"/issues/{ISSUE_NUMBER}/comments", {"per_page": 100, "page": page}
            )
            if not isinstance(data, list):
                raise RuntimeError("Invalid issue comments API")
            comments.extend(data)
        return sorted(comments, key=lambda item: item.get("created_at") or "")

    def notify(self, message):
        response = self.session.post(
            self.base + f"/issues/{ISSUE_NUMBER}/comments",
            json={"body": message},
            timeout=25,
        )
        response.raise_for_status()


def write_summary(results, transitions, notifications):
    lines = [
        "### MasterBot workflow watchdog",
        "",
        "Heartbeat is a recent successful GitHub Actions run, not proof that all retail sources work.",
        "",
        "| Workflow | Status | Minutes since success | Limit |",
        "| --- | --- | ---: | ---: |",
    ]
    for row in results:
        name, age, limit = (row["workflow"].label, row["age_minutes"], row["workflow"].stale_after_minutes)
        lines.append(f"| {name} | {row['state']} | {age if age is not None else 'n/a'} | {limit} |")
    lines.append("")
    lines.append(f"Mode: {'NOTIFY' if notifications else 'DRY-RUN'}; transitions: {len(transitions)}.")
    summary = "\n".join(lines) + "\n"
    print(summary)
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as file:
            file.write(summary)


def main(argv=None):
    parser = argparse.ArgumentParser(description="MasterBot workflow heartbeat")
    parser.add_argument("--notify", action="store_true", help="Comment once per status change on issue 62")
    args = parser.parse_args(argv)
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    token = os.environ.get("GH_TOKEN", "").strip()
    if not repo or not token:
        raise RuntimeError("GITHUB_REPOSITORY and GH_TOKEN are required")

    api = GitHubApi(repo, token)
    now = datetime.now(timezone.utc)
    # Complete all reads before posting any notification: fail-closed on API errors.
    results = [check_runs(wf, api.runs(wf.filename), now) for wf in WORKFLOWS]
    previous = last_notified_states(api.recent_issue_comments())
    transitions = changed_incidents(results, previous)
    write_summary(results, transitions, args.notify)
    for row in results:
        if row["state"] == "DOWN":
            print(f"::warning title=Missing workflow:{row['workflow'].key}::{row['detail']}")
    if args.notify and transitions:
        api.notify(issue_message(transitions, repo))
        print(f"WATCHDOG: {len(transitions)} transitions posted to issue #{ISSUE_NUMBER}")
    elif args.notify:
        print("WATCHDOG: no changes, no duplicate alarm")
    else:
        print(f"WATCHDOG: dry-run, {len(transitions)} potential transitions, no write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
