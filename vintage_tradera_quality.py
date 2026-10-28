"""Read-only Tradera Vintage Finder quality audit. No webhooks, bids or state writes.

This is a TITLE-based discovery audit, not verified card identification,
market valuation, or a buy/bid recommendation. Public listing references only.
"""
import argparse
import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

import requests

from vintage_finder_tradera import (
    _norm, _safe_public_listing_url, assess_title, fetch_search,
)

# One page for each targeted search. No schedule, pagination loops or scraping.
AUDIT_QUERIES = (
    "pokemon samling",
    "gamla pokemon kort",
    "pokemon kort lot",
    "pokemon fossil",
    "pokemon aquapolis",
    "pokemon gym heroes",
)
STRONG_VINTAGE = (
    "base set", "jungle", "fossil", "team rocket", "neo destiny",
    "neo genesis", "neo revelation", "neo discovery", "gym heroes",
    "gym challenge", "expedition", "aquapolis", "skyridge",
    "ex ruby", "ex sandstorm", "ex dragon", "wotc",
    "dark pokemon", "light pokemon", "dark charizard", "light arcanine",
)
MODERN_ONLY = (
    "scarlet", "violet", "sword shield", "vmax", "vstar", "pokemon 151",
    "prismatic", "surging sparks", "destined rivals", "mega evolution",
    "paldea", "obsidian flames", "temporal forces", "2025", "2026",
    "bulk", "1000 kort", "1000 cards", "digital", "code card",
)
MAX_PUBLIC_SAMPLES = 20


def classify_title(title):
    """Report TITLE_VINTAGE, TITLE_UNCERTAIN or EXCLUDED, never KØB/BYD."""
    s = _norm(title)
    original = assess_title(title)
    if original["priority"] == "SKIP":
        return "EXCLUDED", original["reasons"][0]
    strong = any(re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", s)
                 for k in STRONG_VINTAGE)
    if any(re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", s)
           for k in MODERN_ONLY) and not strong:
        return "EXCLUDED", "modern/bulk signal without verified vintage"
    if strong:
        return "TITLE_VINTAGE", "specific vintage text"
    # Dates or generic collections do not prove a vintage card.
    return "TITLE_UNCERTAIN", "generic/ambiguous collection text"


def _summary_record(row):
    if not isinstance(row, dict):
        return None
    item_id = row.get("id")
    title = row.get("shortDescription")
    if isinstance(item_id, bool) or not isinstance(item_id, (str, int)):
        return None
    if not str(item_id).strip() or not isinstance(title, str) or not title.strip():
        return None
    url = _safe_public_listing_url(row.get("itemUrl"))
    if not url:
        return None
    category, reason = classify_title(title)
    return {
        "id": str(item_id),
        "title": re.sub(r"[\x00-\x1f\x7f]+", " ", title).strip()[:160],
        "url": url,
        "category": category,
        "reason": reason,
    }


def audit_batches(batches, sample_limit=MAX_PUBLIC_SAMPLES):
    """Count search noise vs title matches; NOT manually verified precision."""
    seen = {}
    query_counts = {}
    scanned = duplicates = malformed = 0
    for query, rows in batches:
        if not isinstance(rows, list):
            raise ValueError("Expected official Tradera rows list")
        query_counts[query] = len(rows)
        scanned += len(rows)
        for row in rows:
            parsed = _summary_record(row)
            if parsed is None:
                malformed += 1
                continue
            if parsed["id"] in seen:
                duplicates += 1
                continue
            seen[parsed["id"]] = parsed

    breakdown = Counter(r["category"] for r in seen.values())
    samples = sorted(
        (r for r in seen.values() if r["category"] != "EXCLUDED"),
        key=lambda r: (r["category"] != "TITLE_VINTAGE", r["id"]),
    )[:min(max(int(sample_limit), 0), MAX_PUBLIC_SAMPLES)]
    return {
        "mode": "SHADOW_ONLY_NO_DISCORD",
        "queries": query_counts,
        "scanned_rows": scanned,
        "unique_valid_listings": len(seen),
        "duplicate_search_hits": duplicates,
        "malformed_or_unsafe_links": malformed,
        "title_vintage": breakdown["TITLE_VINTAGE"],
        "title_uncertain": breakdown["TITLE_UNCERTAIN"],
        "title_excluded": breakdown["EXCLUDED"],
        "manual_verified_relevant": None,
        "manual_verified_false_positives": None,
        "precision": None,
        "buy_bid_alerts": 0,
        "note": "Title signals only; actual relevance, language, condition, price and shipping are unverified.",
        "public_review_samples": samples,
    }


def actionable_signal(listing, evidence, now=None):
    """Fail-closed gate for a *future* publisher; not wired to Discord.

    Every factual attestation and price cap must be checked independently by
    a person. A search result never supplies these fields automatically.
    """
    if not isinstance(listing, dict) or not isinstance(evidence, dict):
        return None
    item_id = str(listing.get("id") or "")
    if not item_id or not _safe_public_listing_url(listing.get("url")):
        return None
    if classify_title(listing.get("title"))[0] != "TITLE_VINTAGE":
        return None
    if str(evidence.get("listing_id") or "") != item_id:
        return None
    checks = (
        "human_approved", "card_ids_verified", "photos_front_back_verified",
        "language_english_verified", "condition_verified",
        "authenticity_verified", "seller_reputation_verified",
        "shipping_to_denmark_verified", "fees_verified",
        "current_total_verified", "eu_comparables_verified",
    )
    if any(evidence.get(flag) is not True for flag in checks):
        return None
    if not isinstance(evidence.get("card_details"), list) or not evidence["card_details"]:
        return None
    for card in evidence["card_details"]:
        if not isinstance(card, dict) or any(
            not isinstance(card.get(field), str) or not card[field].strip()
            for field in ("name", "set", "number", "condition")
        ):
            return None
    try:
        total = evidence["total_cost_sek"]
        cap = evidence["conservative_max_total_sek"]
        if isinstance(total, bool) or isinstance(cap, bool):
            return None
        total, cap = float(total), float(cap)
    except (ValueError, TypeError, KeyError):
        return None
    if not (0 < total <= cap < 1000000):
        return None
    stamp = evidence.get("reviewed_at")
    if not isinstance(stamp, str):
        return None
    try:
        reviewed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if reviewed.tzinfo is None:
        return None
    now = now or datetime.now(timezone.utc)
    if reviewed > now or now - reviewed > timedelta(hours=6):
        return None
    # This is only a conditional eligibility verdict; no sender exists here.
    return evidence.get("action") if evidence.get("action") in ("KØB", "BYD") else None


def live_audit(app_id, app_key, transport=requests.get):
    if not app_id or not app_key:
        raise ValueError("Tradera application credentials are missing")
    batches = []
    for index, query in enumerate(AUDIT_QUERIES, 1):
        try:
            rows = fetch_search(query, app_id, app_key, transport=transport)
        except requests.HTTPError as exc:
            # Status and query ordinal only: never log URL, body or headers.
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if isinstance(status, int) and 100 <= status <= 599:
                raise RuntimeError(
                    f"Official Tradera search HTTP {status} at query #{index}"
                ) from None
            raise RuntimeError(
                f"Official Tradera search HTTP failure at query #{index}"
            ) from None
        except requests.RequestException:
            raise RuntimeError(
                f"Official Tradera search transport failure at query #{index}"
            ) from None
        except ValueError:
            raise RuntimeError(
                f"Official Tradera search response/schema failure at query #{index}"
            ) from None
        batches.append((query, rows))
    return audit_batches(batches)


def main():
    parser = argparse.ArgumentParser(description="Inert Tradera title-quality audit")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", help="Local JSON report path (not repo state)")
    args = parser.parse_args()
    if not args.live:
        report = audit_batches([])
    else:
        try:
            report = live_audit(os.getenv("TRADERA_APP_ID"), os.getenv("TRADERA_APP_KEY"))
        except (ValueError, RuntimeError) as exc:
            parser.exit(1, "SHADOW AUDIT FAILED: " + str(exc) + "\n")
    result = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as file:
            file.write(result + "\n")
    print(result)


if __name__ == "__main__":
    main()
