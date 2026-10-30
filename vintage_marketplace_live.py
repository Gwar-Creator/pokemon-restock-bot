"""Vintage Finder Light: official Tradera -> selected-find Discord notifications.

Title-based DISCOVERY only, never a purchase recommendation. Uses a separate
durable seen ledger, first-run baseline, maximum three finds daily, no bidding.
The workflow must commit the state BEFORE calling publish().
"""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests

from vintage_finder_tradera import fetch_search
from vintage_marketplace_shortlist import pick_title, propose_shortlist
from vintage_marketplace_webhook_check import verify_webhook_destination
from vintage_marketplace_shortlist import TIERS

# Searches deliberately mirror the useful categories in the morning discovery agent.
DISCOVERY_QUERIES = (
    'pokemon samling', 'gamla pokemon kort', 'pokemon kort lot',
    'pokemon album', 'pokemon parmar', 'pokemon holo',
    'pokemon gym heroes', 'pokemon neo destiny',
    'pokemon expedition', 'pokemon aquapolis', 'pokemon skyridge',
    'pokemon ex dragon', 'pokemon ex sandstorm',
)

CHANNEL_ID = "1540094708439711904"
STATE_PATH = Path("vintage_marketplace_state_v1.json")
PENDING_PATH = Path("vintage_marketplace_pending.json")
DETAIL_ROOT = "https://api.tradera.com/v4/items/"
MAX_DETAIL_CHECKS = 30


def image_url(raw):
    """No arbitrary seller image URL in Discord embeds."""
    if not isinstance(raw, str) or not raw or len(raw) > 1800:
        return ""
    try:
        parts = urlsplit(raw)
        host = (parts.hostname or "").lower()
        if (parts.scheme not in ("http", "https") or
                host not in ("img.tradera.net", "tradera.com", "www.tradera.com")
                or parts.username or parts.password or parts.port is not None
                or not parts.path):
            return ""
        return urlunsplit(("https", parts.netloc, parts.path, "", ""))
    except ValueError:
        return ""


def _positive_price(raw):
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str, Decimal)):
        return None
    try:
        number = Decimal(str(raw))
        if number.is_finite() and number > 0 and number < Decimal("1000000"):
            return str(number.normalize())
    except InvalidOperation:
        pass
    return None


def read_state(path=STATE_PATH):
    if not path.exists():
        raise ValueError("Dedicated Vintage Finder state must exist")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("version") != 1 or
            not isinstance(data.get("seen"), dict) or
            not isinstance(data.get("sent_at"), list)):
        raise ValueError("Invalid dedicated vintage state; refuse to send")
    return data


def get_details(item_id, app_id, app_key, transport=requests.get):
    if not str(item_id).isdigit():
        return None
    try:
        resp = transport(
            DETAIL_ROOT + str(item_id),
            headers={"X-App-Id": app_id, "X-App-Key": app_key,
                     "Accept": "application/json"},
            timeout=12,
        )
        if getattr(resp, "status_code", None) != 200:
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None
    except (requests.RequestException, ValueError):
        return None


def enrich(candidate, detail, now=None):
    """Requires open listing, visible image, and explicit live SEK amount."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(detail, dict) or str(detail.get("id")) != candidate["id"]:
        return None
    if (not isinstance(detail.get("shortDescription"), str)
            or not detail["shortDescription"].strip().startswith(candidate["title"])):
        return None
    status = detail.get("status")
    if not isinstance(status, dict) or status.get("ended") is not False:
        return None
    end = detail.get("endDate")
    if not isinstance(end, str):
        return None
    try:
        end_time = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return None
    if end_time.tzinfo is None or end_time <= now:
        return None
    if type(detail.get("numberOfImages")) is not int or detail["numberOfImages"] < 1:
        return None

    photo = ""
    items = detail.get("detailedImageLinks")
    if isinstance(items, list):
        for value in items:
            if isinstance(value, dict):
                photo = image_url(value.get("url"))
            if photo:
                break
    if not photo:
        raw_links = detail.get("imageLinks")
        if isinstance(raw_links, list):
            for raw in raw_links:
                photo = image_url(raw)
                if photo:
                    break
    if not photo:
        photo = image_url(detail.get("thumbnailLink"))
    if not photo:
        return None

    price = label = None
    if detail.get("nextBidSpecified") is True:
        price = _positive_price(detail.get("nextBid"))
        label = "Næste bud" if price else None
    if price is None and detail.get("buyItNowPriceSpecified") is True:
        price = _positive_price(detail.get("buyItNowPrice"))
        label = "Køb nu" if price else None
    if price is None and detail.get("openingBidSpecified") is True:
        price = _positive_price(detail.get("openingBid"))
        label = "Startbud" if price else None
    if price is None:
        return None
    return {**candidate, "image": photo, "price_sek": price,
            "price_label": label, "photo_count": detail["numberOfImages"],
            "checked_at": now.isoformat()}


def prepare(app_id, app_key, state, now=None,
            search_transport=requests.get, detail_transport=requests.get):
    """Inert until first baseline is committed. Never sends Discord."""
    now = now or datetime.now(timezone.utc)
    app_id = app_id.strip() if isinstance(app_id, str) else ""
    app_key = app_key.strip() if isinstance(app_key, str) else ""
    if not app_id or not app_key:
        raise ValueError("Tradera credentials unavailable")

    found = {}
    for q in DISCOVERY_QUERIES:
        rows = fetch_search(q, app_id, app_key, transport=search_transport)
        for row in rows:
            candidate = pick_title(row)
            if candidate:
                found[candidate["id"]] = candidate

    if state.get("initialized") is not True:
        new_state, _, _ = propose_shortlist(
            [{"id": item["id"], "shortDescription": item["title"],
              "itemUrl": item["url"]} for item in found.values()],
            state, now,
        )
        return new_state, [], len(found), True

    eligible = []
    ranked = sorted(found.values(),
                    key=lambda x: (TIERS.get(x["tier"], 99), -int(x["id"])))
    seen = state["seen"]
    checked_count = 0
    for item in ranked:
        if item["id"] in seen:
            continue
        if checked_count >= MAX_DETAIL_CHECKS:
            break
        checked_count += 1
        detail = get_details(item["id"], app_id, app_key, detail_transport)
        checked = enrich(item, detail, now)
        if checked:
            eligible.append(checked)

    rows = [{"id": x["id"], "shortDescription": x["title"], "itemUrl": x["url"]}
            for x in eligible]
    # The existing shortlist policy reserves only up to 3/run, 3/day, 8/week.
    new_state, shortlisted, _ = propose_shortlist(rows, state, now)
    if (not shortlisted and new_state["seen"] == state["seen"]
            and new_state["sent_at"] == state["sent_at"]):
        # Avoid unrelated empty state commits on scheduled checks.
        return state, [], len(found), False
    selected = {x["id"] for x in shortlisted}
    return new_state, [x for x in eligible if x["id"] in selected], len(found), False


def payload(item):
    if not isinstance(item, dict) or item.get("verification") != "UNVERIFIED":
        raise ValueError("Only honest selected-find titles may be shown")
    if item.get("tier") not in TIERS:
        raise ValueError("Not a selected vintage lot")
    if not item.get("url", "").startswith("https://www.tradera.com/item/"):
        raise ValueError("Untrusted Tradera listing URL")
    return {
        "username": "Pokémon MasterBot",
        "allowed_mentions": {"parse": []},
        "embeds": [{
            "title": ("TRADERA · UDVALGT FUND · " + item["title"])[:256],
            "url": item["url"],
            "description": (
                "Interessant vintageannonce til din egen vurdering – "
                "**ikke et købsråd**. Kort, stand, sprog og fragt til DK "
                "er ikke verificeret."
            ),
            "thumbnail": {"url": item["image"]},
            "fields": [
                {"name": item["price_label"],
                 "value": item["price_sek"] + " SEK", "inline": True},
                {"name": "Billeder i annoncen", "value": str(item["photo_count"]),
                 "inline": True},
                {"name": "Fragt til Danmark", "value": "Ikke verificeret",
                 "inline": False},
            ],
            "color": 10066329,
            "footer": {"text": "Vintage Finder Light · kig på billeder og pris før bud"},
        }],
    }


def publish(items, state, webhook, now=None,
            verify_transport=requests.get, send_transport=requests.post):
    """After durable state commit only. Exact webhook check before POST."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(items, list) or not 0 < len(items) <= 3:
        return 0
    if not isinstance(state, dict) or not isinstance(state.get("seen"), dict):
        return 0
    seen = state["seen"]
    ready = []
    used = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        ident = str(item.get("id") or "")
        if ident in used:
            continue
        stamp = seen.get(ident)
        if not isinstance(stamp, str):
            continue
        try:
            reserved = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            checked = datetime.fromisoformat(item["checked_at"])
            if reserved.tzinfo is None or checked.tzinfo is None:
                continue
            if not (timedelta(0) <= now - reserved <= timedelta(minutes=5) and
                    timedelta(0) <= now - checked <= timedelta(minutes=5)):
                continue
            card = payload(item)
        except (ValueError, KeyError, TypeError):
            continue
        ready.append(card)
        used.add(ident)
    if not ready:
        return 0
    if verify_webhook_destination(webhook, CHANNEL_ID, verify_transport) != "VERIFIED":
        raise RuntimeError("Marketplace webhook target not verified; no messages sent")
    posted = 0
    for card in ready:
        try:
            result = send_transport(webhook, json=card, timeout=10,
                                    allow_redirects=False)
            if getattr(result, "status_code", None) == 204:
                posted += 1
        except requests.RequestException:
            pass
        # Never retry failed/ambiguous sends: the item remains in dedicated state.
    return posted


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "publish"))
    args = parser.parse_args()
    if args.mode == "prepare":
        state = read_state()
        new_state, selected, count, baseline = prepare(
            os.getenv("TRADERA_APP_ID"), os.getenv("TRADERA_APP_KEY"), state
        )
        STATE_PATH.write_text(
            json.dumps(new_state, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        PENDING_PATH.write_text(
            json.dumps(selected, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Vintage Finder: {count} title candidates; "
              f"{len(selected)} reserved; first-run baseline={baseline}.")
    else:
        state = read_state()
        items = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
        if not isinstance(items, list) or len(items) > 3:
            raise SystemExit("Unsafe pending batch")
        count = publish(items, state, os.getenv("MARKETPLACE_WEBHOOK_URL"))
        print(f"Vintage Finder: {count} selected-find messages accepted by Discord.")


if __name__ == "__main__":
    main()
