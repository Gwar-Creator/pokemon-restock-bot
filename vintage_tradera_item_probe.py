"""Bounded, official Tradera REST v4 item-detail schema probe (read-only).

Only logs field names, field types, and anonymous availability flags.
Never logs item content, images, usernames, prices, or credentials.
This is NOT a valuation or purchase/recommendation system.
"""
import json
import os

import requests

ITEMS_URL = "https://api.tradera.com/v4/items"
# Explicitly chosen from the previously verified official search results.
SAMPLE_IDS = (752649647, 757471847, 757471322, 757750760)
MAX_FIELDS = 80
MAX_DEPTH = 2


def _describe(value, depth=0):
    """Return only structural data, never any value or key-derived guess."""
    if isinstance(value, dict):
        out = {"type": "object", "fields": sorted(str(k) for k in value)[:MAX_FIELDS]}
        if depth < MAX_DEPTH:
            out["children"] = {
                str(key): _describe(val, depth + 1)
                for key, val in sorted(value.items())[:MAX_FIELDS]
                if isinstance(val, (dict, list))
            }
        return out
    if isinstance(value, list):
        sample = next((x for x in value if isinstance(x, dict)), None)
        return {
            "type": "array",
            "count": len(value),
            "sample_fields": sorted(str(k) for k in sample)[:MAX_FIELDS]
            if sample else [],
        }
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "bool"}
    if isinstance(value, (int, float)):
        return {"type": "number"}
    return {"type": "string"}


def probe_item(item_id, app_id, app_key, transport=requests.get):
    """Exactly one read-only GET; errors contain status only, not response data."""
    if type(item_id) is not int or item_id <= 0:
        raise ValueError("Only positive numeric Tradera item IDs are permitted")
    app_id = app_id.strip() if isinstance(app_id, str) else ""
    app_key = app_key.strip() if isinstance(app_key, str) else ""
    if not app_id or not app_key:
        raise ValueError("Tradera secrets missing")
    try:
        response = transport(
            f"{ITEMS_URL}/{item_id}",
            headers={"X-App-Id": app_id, "X-App-Key": app_key,
                     "Accept": "application/json"},
            timeout=20,
        )
    except requests.RequestException:
        raise RuntimeError("Tradera item-detail network request failed") from None
    status = getattr(response, "status_code", None)
    if status != 200:
        status = status if type(status) is int and 100 <= status <= 599 else "unknown"
        raise RuntimeError(f"Tradera item-detail HTTP {status}")
    try:
        data = response.json()
    except ValueError:
        raise RuntimeError("Tradera item-detail returned invalid JSON") from None
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected Tradera item-detail response shape")
    return _describe(data)


def probe_samples(app_id, app_key, transport=requests.get):
    """Independent errors; four fixed item IDs, no recursive pagination."""
    results = []
    for i, item_id in enumerate(SAMPLE_IDS, 1):
        try:
            shape = probe_item(item_id, app_id, app_key, transport)
            results.append({"sample_index": i, "success": True, "shape": shape})
        except (ValueError, RuntimeError) as exc:
            results.append({
                "sample_index": i,
                "success": False,
                "error_category": str(exc),
            })
    return {"mode": "READ_ONLY_NO_DISCORD", "sample_count": len(SAMPLE_IDS),
            "results": results, "buy_bid_alerts": 0}


def main():
    report = probe_samples(
        os.getenv("TRADERA_APP_ID"), os.getenv("TRADERA_APP_KEY")
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not any(row["success"] for row in report["results"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
