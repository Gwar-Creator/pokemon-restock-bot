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


def normalize_listing(record):
    """Strict normalized shape; refuse to invent unavailable card metadata."""
    if not isinstance(record, dict):
        return None
    item_id = record.get("id", record.get("itemId"))
    title = record.get("title", record.get("name"))
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
    # The v4 OpenAPI beta describes SearchResult as an opaque object.
    # Accept common variants only after a real API integration confirms one.
    for key in ("items", "Items"):
        value = response.get(key)
        if isinstance(value, list):
            return value
    raise ValueError(
        "Tradera beta response keys are unverified; inspect schema before live alerts"
    )


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
    data = response.json()
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
