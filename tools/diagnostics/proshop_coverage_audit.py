#!/usr/bin/env python3
"""Read-only coverage audit of recent *actual* Proshop HOT scans.

Uses GitHub Actions logs already produced by HOT. No Proshop/Jina requests,
Discord, workflow dispatch, repository writes, or changes to production alerts.
A green GitHub job is NOT evidence that every Proshop scan succeeded.
"""
import argparse
import json
import os
import re

import requests


ITERATION = re.compile(r"\bHOT scan (\d+)/(\d+)\b")
PRIMARY = re.compile(r"\bHOT PROSHOP reader: primary=(\d+)\s*·\s*broad_added=(\d+)\s*·\s*total=(\d+)")
FRESH = re.compile(r"\bHOT PROSHOP: (\d+) friske relevante\s*·\s*(\d+) på lager")
DETAIL = re.compile(r"\bPROSHOP DETAIL \d+: verificeret (PÅ LAGER|UDSOLGT|FJERNLAGER|BESTILLINGSVARE)")
COMPLETED = re.compile(r"\bHOT scan færdig: (\d+)/(\d+) kilder lykkedes")


def parse_hot_log(log):
    """Ignore diagnostic unit-test printouts before the real scan 1/N marker."""
    cycles = []
    current = None
    for line in (log or "").splitlines():
        iteration = ITERATION.search(line)
        if iteration:
            current = {
                "iteration": int(iteration.group(1)),
                "primary": None,
                "broad_added": None,
                "reader_total": None,
                "fresh": None,
                "in_stock": None,
                "detail_verified": 0,
                "detail_in_stock": 0,
                "failed": False,
                "backoff": False,
                "successful_sources": None,
            }
            cycles.append(current)
            continue
        if current is None:
            continue
        primary = PRIMARY.search(line)
        if primary:
            current["primary"], current["broad_added"], current["reader_total"] = (
                int(value) for value in primary.groups()
            )
        fresh = FRESH.search(line)
        if fresh:
            current["fresh"], current["in_stock"] = (int(value) for value in fresh.groups())
        if "HOT PROSHOP FEJL:" in line:
            current["failed"] = True
        if "HOT PROSHOP BACKOFF:" in line:
            current["backoff"] = True
        detail = DETAIL.search(line)
        if detail:
            current["detail_verified"] += 1
            if detail.group(1) == "PÅ LAGER":
                current["detail_in_stock"] += 1
        finished = COMPLETED.search(line)
        if finished:
            current["successful_sources"] = int(finished.group(1))
    return cycles


def summarize(run_rows):
    cycles = [cycle for row in run_rows for cycle in row["cycles"]]
    return {
        "completed_hot_runs": len(run_rows),
        "cycles": len(cycles),
        "primary_catalog_zero": sum(c["primary"] == 0 for c in cycles),
        "primary_catalog_positive": sum(c["primary"] is not None and c["primary"] > 0 for c in cycles),
        "proshop_failed": sum(c["failed"] for c in cycles),
        "proshop_backoff": sum(c["backoff"] for c in cycles),
        "fresh_products_zero": sum(c["fresh"] == 0 for c in cycles),
        "fresh_products_positive": sum(c["fresh"] is not None and c["fresh"] > 0 for c in cycles),
        "verified_detail_checks": sum(c["detail_verified"] for c in cycles),
        "verified_in_stock_details": sum(c["detail_in_stock"] for c in cycles),
        "github_green_runs": sum(r["conclusion"] == "success" for r in run_rows),
        "runs_with_proshop_failure_or_backoff": sum(
            any(c["failed"] or c["backoff"] for c in r["cycles"]) for r in run_rows
        ),
    }


def api_get(session, url, token, *, text=False):
    response = session.get(
        url,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=40,
    )
    response.raise_for_status()
    return response.text if text else response.json()


def audit(repo, token, limit=8, session=None):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo or ""):
        raise ValueError("A valid GITHUB_REPOSITORY owner/repo is required")
    if not token:
        raise ValueError("GITHUB_TOKEN is required for read-only GitHub Actions access")
    if not 1 <= limit <= 12:
        raise ValueError("limit must be between 1 and 12")
    session = session or requests.Session()
    base = "https://api.github.com/repos/" + repo
    runs = api_get(
        session,
        base + "/actions/workflows/hot_restock.yml/runs?status=completed&per_page=" + str(limit),
        token,
    ).get("workflow_runs", [])

    rows = []
    for run in runs[:limit]:
        jobs = api_get(
            session, base + "/actions/runs/" + str(run["id"]) + "/jobs?per_page=100", token,
        ).get("jobs", [])
        hot = next((job for job in jobs if job.get("name") == "hot-scan"), None)
        if hot is None:
            rows.append({"id": run["id"], "conclusion": run.get("conclusion"),
                         "created_at": run.get("created_at"), "cycles": [],
                         "diagnostic_error": "hot-scan job not found"})
            continue
        log = api_get(
            session, base + "/actions/jobs/" + str(hot["id"]) + "/logs", token, text=True,
        )
        rows.append({
            "id": run["id"], "created_at": run.get("created_at"),
            "conclusion": run.get("conclusion"), "cycles": parse_hot_log(log),
        })

    return {"summary": summarize(rows), "runs": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=8)
    args = parser.parse_args()
    report = audit(
        os.environ.get("GITHUB_REPOSITORY", ""),
        os.environ.get("GITHUB_TOKEN", ""),
        args.runs,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
