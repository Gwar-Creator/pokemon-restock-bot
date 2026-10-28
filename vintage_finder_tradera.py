"""Tradera Vintage Finder: independent READ-ONLY prototype, no Discord.

Requires app credentials for live search, and deliberately does not store
search results or automate bidding/buying. /v4/search is a Tradera official
beta API; response fields must be verified before scheduling production.

Official docs:
https://api.tradera.com/documentation/rest/search
https://api.tradera.com/documentation/rest-getting-started
"""
import argparse
import json
import os
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

import requests

SEARCH_TERMS = (
    "pokemon samling",
    "gamla pokemon kort",
    "pokemon kort lot",
    "pokemon neo destiny",
    "pokemon expedition",
    "pokemon aquapolis",
    "pokemon skyridge",
    "pokemon ex dragon",
)
SEARCH_URL = "https://api.tradera.com/v4/search"

class TraderaResponseFormatError(ValueError):
    """Safe metadata only; never retain API body, headers, URL or credentials."""

    def __init__(self, status_code, content_type):
        self.http_status = (
            status_code if type(status_code) is int and 100 <= status_code <= 599
            else "unknown"
        )
        mime = (content_type.split(";", 1)[0].strip().lower()
                if isinstance(content_type, str) else "")
        self.content_kind = (
            "json" if mime == "application/json" or mime.endswith("+json")
            else "html" if mime == "text/html"
            else "plain_text" if mime == "text/plain"
            else "other"
        )
        super().__init__("Tradera response was not valid JSON")


# These indicate a card language or fake products, not the language used
# in the seller's description. A Swedish title is fine for English cards.
BLOCKED_MARKERS = (
    "japanska kort", "japanese cards", "japanese edition",
    "tyska kort", "german cards", "german edition",
    "franska kort", "french cards", "french edition",
    "koreanska kort", "korean cards",
    "proxy", "orica", "fake card", "replica", "repack",
    "mystery box", "digital code", "online code",
    "bulk only", "bulk kort", "bulk cards",
)
SEALED_MARKERS = (
    "booster pack", "booster box", "elite trainer box", "booster bundle",
    "etb ", "sealed display", "sealed booster",
)
VINTAGE_MARKERS = (
    "base set", "jungle", "fossil", "team rocket", "neo destiny",
    "neo discovery", "neo revelation", "neo genesis", "gym heroes",
    "gym challenge", "expedition", "aquapolis", "skyridge",
    "ex ruby", "ex sandstorm", "ex dragon", "wotc", "1999", "2000",
    "2001", "2002", "2003", "2004",
)
LOT_MARKERS = (
    "samling", "collection", "lot", "kortlek", "album",
    "binder", "gammal", "gamla", "old cards", "vintage",
)


def _norm(value):
    value = unicodedata.normalize("NFKD", str(value or "").lower())
    return re.sub(r"\s+", " ", "".join(
        ch for ch in value if not unicodedata.combining(ch)
    )).strip()


def assess_title(title):
    """Review priority, NOT market value or a recommendation to purchase."""
    clean = _norm(title)
    if not clean or not any(token in clean for token in ("pokemon", "pokémon")):
        return {"priority": "SKIP", "reasons": ("not clearly Pokemon",)}
    if any(marker in clean for marker in BLOCKED_MARKERS):
        return {"priority": "SKIP", "reasons": ("unwanted language/repack/bulk",)}
    if any(marker in clean for marker in SEALED_MARKERS):
        return {"priority": "SKIP", "reasons": ("sealed is out of scope",)}

    vintage = [marker for marker in VINTAGE_MARKERS if marker in clean]
    lot = [marker for marker in LOT_MARKERS if marker in clean]
    if vintage:
        return {"priority": "REVIEW_HIGH", "reasons": ("vintage keyword",)}
    if lot:
        return {"priority": "REVIEW", "reasons": ("possible old collection",)}
    return {"priority": "SKIP", "reasons": ("no convincing vintage signal",)}


def _safe_public_listing_url(value):
    """Canonicalize public Tradera HTTP links to HTTPS, never other domains.

    Legacy HTTP URLs may be supplied by the official API; these are NOT
    additional sources or website scraping. Avoid unsafe ports/userinfo.
    """
    if not isinstance(value, str) or len(value) > 2048:
        return ""
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https"):
        return ""
    if not (host == "tradera.com" or host.endswith(".tradera.com")):
        return ""
    if port is not None or parsed.username or parsed.password or not parsed.path:
        return ""
    if parsed.scheme == "http":
        return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, ""))
    return value


def normalize_listing(record):
    """Strict normalized shape; refuse to invent unavailable card metadata."""
    if not isinstance(record, dict):
        return None
    item_id = record.get("id", record.get("itemId"))
    title = record.get("shortDescription", record.get("title", record.get("name")))
    if item_id is None or not isinstance(title, str):
        return None
    report = assess_title(title)
    if report["priority"] == "SKIP":
        return None
    # Do not infer the seller ships to Denmark, condition, card language,
    # sale value or currency conversion from a title or price.
    return {
        "id": str(item_id),
        "title": title[:250],
        "url": _safe_public_listing_url(record.get("itemUrl") or record.get("url")),
        "priority": report["priority"],
        "price_sek": record.get("price"),
        "shipping_to_denmark": "UNKNOWN",
        "card_language": "UNVERIFIED",
        "condition": "UNVERIFIED",
        "fair_price": "UNVERIFIED",
        "purchase_decision": "DO_NOT_BUY_WITHOUT_REVIEW",
    }


def extract_search_rows(response):
    """Fail closed until the current beta response shape is validated."""
    if not isinstance(response, dict):
        raise ValueError("Unexpected Tradera search response (not object)")
    # Verified 28 October 2026: errors, items, totalNumberOfItems, totalNumberOfPages.
    errors = response.get("errors")
    if errors is not None and (not isinstance(errors, list) or errors):
        raise ValueError("Tradera search returned API errors")
    value = response.get("items")
    if not isinstance(value, list):
        raise ValueError("Unexpected Tradera REST v4 items shape")
    return value


def fetch_search(query, app_id, app_key, transport=requests.get):
    """Official read-only search, never bids, purchases or messages a seller."""
    if not app_id or not app_key:
        raise ValueError("TRADERA_APP_ID and TRADERA_APP_KEY are required")
    if not query or len(query) > 120:
        raise ValueError("Query must contain 1-120 characters")
    response = transport(
        SEARCH_URL,
        params={"query": query, "pageNumber": 0},
        headers={
            "X-App-Id": str(app_id),
            "X-App-Key": str(app_key),
            "Accept": "application/json",
        },
        timeout=20,
    )
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError:
        # requests.JSONDecodeError is ALSO a RequestException. Convert it
        # before the audit's transport handler can misclassify it.
        headers = getattr(response, "headers", {})
        content_type = headers.get("Content-Type") if hasattr(headers, "get") else None
        raise TraderaResponseFormatError(
            getattr(response, "status_code", None), content_type
        ) from None
    return extract_search_rows(data)


def select_candidates(rows, limit=12):
    candidates = {}
    for record in rows:
        candidate = normalize_listing(record)
        if candidate is not None:
            candidates[candidate["id"]] = candidate
    ranked = sorted(
        candidates.values(),
        key=lambda x: (x["priority"] != "REVIEW_HIGH", x["title"].lower()),
    )
    return ranked[:max(0, min(int(limit), 30))]


def main():
    parser = argparse.ArgumentParser(description="Read-only vintage search prototype")
    parser.add_argument("--live", action="store_true",
                        help="Use the official Tradera API, without any Discord or bids")
    parser.add_argument("--query", action="append", choices=SEARCH_TERMS,
                        help="Search expression (may be repeated)")
    args = parser.parse_args()
    terms = args.query or SEARCH_TERMS
    if not args.live:
        print(json.dumps({
            "mode": "dry-run", "queries": terms,
            "next_step": "register Tradera app and review beta response schema",
            "discord": "off", "bids": "off",
        }, ensure_ascii=False, indent=2))
        return

    app_id = os.getenv("TRADERA_APP_ID", "").strip()
    app_key = os.getenv("TRADERA_APP_KEY", "").strip()
    if not app_id or not app_key:
        parser.error("Missing TRADERA_APP_ID or TRADERA_APP_KEY (never commit secrets)")
    rows = []
    for term in terms:
        rows.extend(fetch_search(term, app_id, app_key))
    print(json.dumps({
        "mode": "live-read-only", "searched": len(terms),
        "candidates_for_manual_review": select_candidates(rows),
        "discord": "off", "bids": "off",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
