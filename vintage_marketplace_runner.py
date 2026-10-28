"""Read-only one-shot vintage discovery. No channel, webhook, bids or buys.

Official Tradera search REST v4 only. Emits a small internal review artifact;
never call it BUY/BID or deliver to #marketplace-deals.
"""
import argparse
import json
import os

import requests

from vintage_finder_tradera import fetch_search
from vintage_tradera_quality import AUDIT_QUERIES
from vintage_marketplace_shortlist import (
    pick_title, propose_shortlist, internal_preview,
)

MAX_SHOW = 8


def discover(app_id, app_key, transport=requests.get):
    app_id = app_id.strip() if isinstance(app_id, str) else ""
    app_key = app_key.strip() if isinstance(app_key, str) else ""
    if not app_id or not app_key:
        raise ValueError("Tradera app credentials required")
    all_rows = []
    for query in AUDIT_QUERIES:
        all_rows.extend(fetch_search(query, app_id, app_key, transport=transport))
    unique = {}
    for item in all_rows:
        candidate = pick_title(item)
        if candidate is not None:
            unique[candidate["id"]] = candidate
    candidates = sorted(unique.values(), key=lambda x:
                        (x["tier"] != "VINTAGE_LOT", x["id"]))
    return {
        "mode": "READ_ONLY_INTERNAL_REVIEW",
        "query_count": len(AUDIT_QUERIES),
        "search_hits": len(all_rows),
        "selected_lot_count": len(unique),
        "selected": [internal_preview(x) for x in candidates[:MAX_SHOW]],
        "discord_alerts": 0,
        "note": "Titles only. No verified card identity, condition, language, price or DK shipping.",
    }


def main():
    parser = argparse.ArgumentParser(description="Read-only vintage discovery shortlist")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", default="vintage_shortlist_review.json")
    args = parser.parse_args()
    if not args.live:
        report = {
            "mode": "DRY_RUN", "selected": [], "discord_alerts": 0,
            "note": "Live requires --live; no webhook code in this tool.",
        }
    else:
        try:
            report = discover(os.getenv("TRADERA_APP_ID"), os.getenv("TRADERA_APP_KEY"))
        except (ValueError, requests.RequestException):
            parser.exit(1, "Read-only Tradera shortlist failed; no output published\n")
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    # Summary only: detailed link list remains in the private Actions artifact.
    print(json.dumps({key: value for key, value in report.items()
                      if key != "selected"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
