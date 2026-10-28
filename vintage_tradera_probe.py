"""Single-page, read-only Tradera REST v4 credentials and response-shape probe.

Runs only on explicit workflow invocation or the workflow's initial deployment.
No titles, prices, sellers, tokens, raw HTTP bodies, listing content or secret
headers are written to logs. Never bids, buys, posts to Discord or saves state.
"""
import os

import requests

SEARCH_URL = "https://api.tradera.com/v4/search"
SEARCH_QUERY = "pokemon samling"
MAX_KEYS = 25


def _shape(value, depth=0):
    """Return only structural metadata, never raw market/user/API values."""
    if isinstance(value, list):
        sample = next((item for item in value if isinstance(item, dict)), None)
        return {
            "type": "array",
            "length": len(value),
            "sample_fields": sorted(str(k) for k in sample)[:MAX_KEYS] if sample else [],
        }
    if isinstance(value, dict):
        return {
            "type": "object",
            "fields": sorted(str(k) for k in value)[:MAX_KEYS],
            "children": {
                str(key): _shape(item, depth + 1)
                for key, item in sorted(value.items())[:MAX_KEYS]
                if depth < 2 and isinstance(item, (dict, list))
            },
        }
    return {"type": type(value).__name__}


def inspect_response(data):
    """Fail closed on unexpected top-level format; describe keys only."""
    if not isinstance(data, dict):
        raise ValueError("Unexpected Tradera API response type")
    summary = _shape(data)
    # No data values, titles, prices, names, seller identities or tokens.
    return summary


def run_probe(app_id=None, app_key=None, transport=requests.get):
    app_id = app_id if app_id is not None else os.getenv("TRADERA_APP_ID", "").strip()
    app_key = app_key if app_key is not None else os.getenv("TRADERA_APP_KEY", "").strip()
    if not app_id or not app_key:
        raise RuntimeError("Missing Tradera application secrets in GitHub Actions")

    try:
        response = transport(
            SEARCH_URL,
            params={"query": SEARCH_QUERY, "pageNumber": 0},
            headers={
                "X-App-Id": str(app_id),
                "X-App-Key": str(app_key),
                "Accept": "application/json",
            },
            timeout=20,
        )
    except requests.RequestException:
        # Avoid printing exception strings, which may include request URLs.
        raise RuntimeError("Tradera network request failed") from None
    status = getattr(response, "status_code", 0)
    if status != 200:
        # Never print raw response: beta error bodies may include request metadata.
        raise RuntimeError(f"Tradera API returned HTTP {status}")

    try:
        response_data = response.json()
    except ValueError:
        raise RuntimeError("Tradera API returned invalid JSON") from None

    return inspect_response(response_data)


def main():
    import json
    try:
        shape = run_probe()
    except (RuntimeError, ValueError) as exc:
        print(f"TRADERA PROBE FAILED: {exc}")
        raise SystemExit(1) from None
    print("TRADERA PROBE: HTTP 200; one read-only search; Discord=off; bids=off")
    print("TRADERA RESPONSE SHAPE (field names only, no data values):")
    print(json.dumps(shape, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
