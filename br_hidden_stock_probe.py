"""Independent BR hidden-stock diagnostic. No Discord alerts.

Cross-check the detailed public click-and-collect endpoint even when Salling
Algolia reports zero stock-bearing stores. These are *unconfirmed* counts,
not purchasable stock. Does not modify local-stock/restock alert state.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

from local_stock_watch import get_frontend_config, probe_hidden_br_inventory

STATE_FILE = Path("br_hidden_stock_probe_state.json")


def run():
    try:
        config = get_frontend_config("br")
        results = probe_hidden_br_inventory(config, requests.Session())
        status = "completed"
    except Exception as error:
        status = "source_unavailable"
        results = {}
        print(f"BR HIDDEN PROBE SOURCE ERROR: {type(error).__name__}")

    now = datetime.now(timezone.utc).isoformat()
    data = {
        "version": 1,
        "status": status,
        "checked_at": now,
        "products": results,
        "interpretation": (
            "Raw detailed Salling stock, not proof of shelf availability. "
            "PRE-PUBLISH/Algolia zero-stock conflicts must be independently checked."
        ),
    }

    old = {}
    if STATE_FILE.exists():
        try:
            old = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            old = {}
    # Commit changing results immediately; otherwise heartbeat at most once
    # per 30 minutes rather than bloating Git history every 5-minute scan.
    unchanged = (
        old.get("status") == status
        and old.get("products") == results
    )
    if unchanged:
        try:
            before = datetime.fromisoformat(
                str(old.get("checked_at", "")).replace("Z", "+00:00")
            )
            if (datetime.now(timezone.utc) - before).total_seconds() < 1800:
                print("BR HIDDEN PROBE: unchanged; saved previous result")
                return
        except (ValueError, TypeError):
            pass
    STATE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(
        f"BR HIDDEN PROBE: {status} | "
        + ", ".join(
            f"{product_id}={entry['status']}"
            f"(Kolding={entry.get('kolding')}, "
            f"Viborg={entry.get('viborg')})"
            for product_id, entry in results.items()
        )
    )


if __name__ == "__main__":
    run()
