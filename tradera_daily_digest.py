"""Daily read-only official Tradera REST-v4 vintage auction shortlist.

No Discord, seller contact, purchases, bids, or modifications to other state.
Listing screenshots/condition, shipping to Denmark and inventory not verified.
"""
import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html import unescape
from urllib.parse import urlsplit
from xml.etree import ElementTree

import requests

from vintage_finder_tradera import fetch_search, _norm, _safe_public_listing_url
from vintage_marketplace_live import get_details

SEARCHES = [
    "pokemon samling", "gamla pokemon kort", "pokemon kort lot",
    "pokemon pärm", "pokemon album", "pokemon vintage", "pokemon holo",
    "pokemon reverse", "pokemon gym", "pokemon neo", "pokemon dark",
    "pokemon light", "pokemon expedition", "pokemon aquapolis",
    "pokemon skyridge", "pokemon ex ruby", "pokemon sandstorm",
    "pokemon ex dragon", "pokemon fossil", "pokemon jungle", "pokemon base set",
]
LOT = ("samling", "collection", "lot", "kortlot", "pärm", "parm", "album",
       "binder", "mapp", "gamla kort", "äldre", "aldre", "vintage",
       "blandade", "blandat", "barndom")
VINTAGE = ("base set", "jungle", "fossil", "team rocket", "gym heroes",
           "gym challenge", "neo", "expedition", "aquapolis", "skyridge",
           "ruby sapphire", "ruby & sapphire", "ex ruby", "sandstorm",
           "ex dragon", "delta species", "deoxys", "hidden legends",
           "legend maker", "dragon frontiers", "holon phantoms",
           "crystal guardians", "unseen forces", "fire red", "firered",
           "wotc", "1999", "2000", "2001", "2002", "2003", "2004",
           "2005", "2006", "2007")
FOIL = ("holo", "reverse", "stamped", "shining", "gold star", "crystal")
BLOCK = ("proxy", "orica", "replica", "fake", "repack", "mystery",
         "sealed", "booster pack", "booster box", "display", "graded",
         "psa ", "cgc ", "digital", "code card", "vmax", "vstar",
         "prismatic", "scarlet", "violet", "surging sparks",
         "destined rivals", "pokemon 151", "mega evolution")
FAV = ("tangela", "abra", "alakazam", "psyduck", "snorlax", "ditto",
       "togepi", "mew", "farfetch", "squirtle", "pikachu", "charmander", "gloom")
MAX_DETAILS = 75
MAX_DKK = Decimal("1500")


def positive(value):
    if isinstance(value, bool):
        return None
    try:
        num = Decimal(str(value))
        return num if num.is_finite() and Decimal("0") < num < 1000000 else None
    except (TypeError, ValueError, InvalidOperation):
        return None


def candidate(title):
    s = _norm(title)
    if not s or "pokemon" not in s or any(block in s for block in BLOCK):
        return False
    if any(term in s for term in ("japanska kort", "japanese cards",
                                 "tyska kort", "german cards", "koreanska kort")):
        return False
    return any(word in s for word in LOT + VINTAGE + FOIL)


def category(title):
    s = _norm(title)
    if any(word in s for word in LOT):
        return "holo_lots" if any(word in s for word in FOIL) else "collections"
    return "singles"


def end_time(value):
    if not isinstance(value, str):
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.tzinfo is None:
            from zoneinfo import ZoneInfo
            date = date.replace(tzinfo=ZoneInfo("Europe/Stockholm"))
        return date
    except ValueError:
        return None


def ecb_fx(get=requests.get):
    response = get("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml",
                   timeout=15)
    response.raise_for_status()
    xml = ElementTree.fromstring(response.content)
    rates, asof = {}, None
    for node in xml.iter():
        if node.attrib.get("time"):
            asof = node.attrib["time"]
        if node.attrib.get("currency") in ("SEK", "DKK"):
            rates[node.attrib["currency"]] = positive(node.attrib.get("rate"))
    if not asof or not rates.get("SEK") or not rates.get("DKK"):
        raise ValueError("ECB SEK/DKK reference unavailable")
    return rates["DKK"] / rates["SEK"], asof


def screen(search_row, item, rate, now):
    ident = str(search_row.get("id", ""))
    title = search_row.get("shortDescription")
    if not ident.isdigit() or not isinstance(title, str) or not candidate(title):
        return None
    url = _safe_public_listing_url(search_row.get("itemUrl"))
    if not url or not isinstance(item, dict) or str(item.get("id")) != ident:
        return None
    if not isinstance(item.get("status"), dict) or item["status"].get("ended") is not False:
        return None
    if not isinstance(item.get("shortDescription"), str):
        return None
    # Detail response is authoritative for the same numeric listing ID; search
    # titles may be abbreviated, so revalidate its own title, not exact equality.
    title = item["shortDescription"].strip()
    if not candidate(title):
        return None
    ends = end_time(item.get("endDate"))
    if ends is None or ends <= now:
        return None
    # Only bid auctions, not buy-now-only listings.
    label, amount = None, None
    # Since the 2026-11-04 REST v4 migration Tradera omits all
    # '*Specified' fields; a missing numeric price means not supplied.
    if positive(item.get("nextBid")) is not None:
        label, amount = "next bid", positive(item.get("nextBid"))
    elif positive(item.get("openingBid")) is not None:
        label, amount = "opening bid", positive(item.get("openingBid"))
    if amount is None or amount * rate > MAX_DKK:
        return None
    # The v4 detail response may not include the old numberOfImages field.
    # Demand at least one safe official Tradera image URL instead.
    from vintage_marketplace_live import image_url
    image = image_url(item.get("thumbnailLink"))
    image_links = item.get("detailedImageLinks")
    if isinstance(image_links, list):
        for pic in image_links:
            if not image and isinstance(pic, dict):
                image = image_url(pic.get("url"))
    raw_links = item.get("imageLinks")
    if isinstance(raw_links, list):
        for pic in raw_links:
            if not image:
                image = image_url(pic.get("url") if isinstance(pic, dict) else pic)
    if not image:
        return None
    image_count = item.get("numberOfImages")
    if type(image_count) is not int or image_count < 1:
        image_count = len(image_links or []) or len(raw_links or []) or 1
    description = unescape(re.sub(r"<[^>]+>", " ", str(item.get("longDescription") or item.get("description") or "")))
    titled = _norm(title)
    body = _norm(description)
    vintage_in_title = any(x in titled for x in VINTAGE)
    vintage_in_body = any(x in body for x in VINTAGE)
    # Honest uncertainty: an old-looking binder is only a lead until photos are checked.
    vintage_evidence = "title" if vintage_in_title else "description" if vintage_in_body else "unverified"
    if category(title) == "singles" and vintage_evidence == "unverified":
        return None
    group = category(title)
    score = 8 if vintage_in_title else 3 if vintage_in_body else 0
    score += 6 if any(x in titled for x in ("expedition", "aquapolis", "skyridge",
                                             "ruby", "sandstorm", "dragon")) else 0
    score += 4 if any(x in titled for x in FOIL) else 0
    score += 3 if any(x in titled for x in ("gym", "dark", "light", "neo")) else 0
    score += 3 if any(x in titled for x in FAV) else 0
    return {
        "id": ident, "title": title[:150], "url": url, "group": group,
        "price_basis": label, "bid_sek": str(amount),
        "bid_dkk": str((amount * rate).quantize(Decimal("0.01"))),
        "end": ends.isoformat(), "vintage_evidence": vintage_evidence,
        "score": score, "photo_count": image_count, "image_url": image,
        "shipping_to_denmark": "unknown", "language": "unverified",
        "condition": "unverified", "buy_advice": "NONE - MANUAL REVIEW",
    }


def run(app_id, app_key):
    # GitHub secrets may include a trailing newline from copy/paste.
    app_id = app_id.strip() if isinstance(app_id, str) else ""
    app_key = app_key.strip() if isinstance(app_key, str) else ""
    if not app_id or not app_key:
        raise ValueError("Existing Tradera API secrets not configured")
    fx, day = ecb_fx()
    now = datetime.now(timezone.utc)
    found, failed = {}, []
    ok_queries = 0
    for term in SEARCHES:
        try:
            rows = fetch_search(term, app_id, app_key)
            ok_queries += 1
            for row in rows:
                if not isinstance(row, dict) or not candidate(row.get("shortDescription")):
                    continue
                item_id = str(row.get("id", ""))
                if item_id.isdigit() and _safe_public_listing_url(row.get("itemUrl")):
                    found[item_id] = row
        except (requests.RequestException, ValueError) as exc:
            if isinstance(exc, requests.HTTPError):
                response = getattr(exc, "response", None)
                status = getattr(response, "status_code", None)
                category_name = "http_" + str(status if type(status) is int else "unknown")
            elif isinstance(exc, requests.Timeout):
                category_name = "timeout"
            elif isinstance(exc, requests.ConnectionError):
                category_name = "connection"
            else:
                category_name = type(exc).__name__
            failed.append({"query": term, "cause": category_name})
            print("Tradera search status: " + category_name + " for term " + term)
    if ok_queries == 0:
        raise RuntimeError("All official Tradera v4 searches failed")
    ranked = sorted(found.values(), key=lambda x: (
        category(x["shortDescription"]) == "singles",
        not any(token in _norm(x["shortDescription"]) for token in VINTAGE),
        -int(x["id"])))
    from collections import Counter
    matches, checked = [], 0
    reasons = Counter()
    for row in ranked[:MAX_DETAILS]:
        checked += 1
        item = get_details(row["id"], app_id, app_key)
        result = screen(row, item, fx, now)
        if result:
            matches.append(result)
            continue
        if not isinstance(item, dict):
            reasons["detail_unavailable"] += 1
        elif not isinstance(item.get("status"), dict) or item["status"].get("ended") is not False:
            reasons["not_open_or_missing_status"] += 1
        elif end_time(item.get("endDate")) is None:
            reasons["invalid_end_date"] += 1
        elif end_time(item.get("endDate")) <= now:
            reasons["already_ended_by_time"] += 1
        elif ("nextBid" not in item and "openingBid" not in item):
            reasons["not_an_auction_or_no_bid"] += 1
        elif (positive(item.get("nextBid")) is None
              and positive(item.get("openingBid")) is None):
            reasons["invalid_bid"] += 1
        elif any(positive(item.get(k)) is not None and positive(item[k]) * fx > MAX_DKK
                 for k in ("nextBid", "openingBid")):
            reasons["over_price_cap"] += 1
        elif not isinstance(item.get("shortDescription"), str) or not candidate(item.get("shortDescription")):
            reasons["detail_title_not_relevant"] += 1
        elif not isinstance(item.get("numberOfImages"), int) or item["numberOfImages"] < 1:
            reasons["image_count_missing_or_zero"] += 1
        else:
            reasons["other_filter"] += 1
    print("Tradera detail rejection counts: " + repr(dict(reasons)))
    by_group = {}
    for group in ("collections", "holo_lots", "singles"):
        ordered = sorted((x for x in matches if x["group"] == group),
                         key=lambda x: (-x["score"], -x["photo_count"], Decimal(x["bid_dkk"])))
        by_group[group] = ordered[:3]
    return {
        "generated_at": now.isoformat(), "source": "Tradera REST v4 API",
        "fx_source": "ECB EUR reference SEK/DKK", "fx_date": day,
        "screening_ceiling_dkk": 1500, "queries_ok": ok_queries,
        "queries_total": len(SEARCHES), "queries_failed": failed,
        "candidates_found": len(found), "details_checked": checked,
        "active_under_ceiling": len(matches), "shortlist": by_group,
        "disclaimer": "No proof of condition, English language, DK delivery, inventory, or bargain. No buying or bidding.",
    }


def main():
    result = run(os.getenv("TRADERA_APP_ID", ""), os.getenv("TRADERA_APP_KEY", ""))
    with open("tradera_daily_digest.json", "w", encoding="utf-8") as file:
        json.dump(result, file, indent=2, ensure_ascii=False)
    # Public auction URLs and bidding amounts may be logged; secrets never are.
    print("TRADERA REPORT START")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("TRADERA REPORT END")


if __name__ == "__main__":
    main()
