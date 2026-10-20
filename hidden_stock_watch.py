"""Confirmed PRE-PUBLISH shop inventory for BR, Bilka and Foetex.

The official Algolia store_count can be zero while Salling's detailed
click-and-collect endpoint reports stock. Such quantities are NOT proof that
items are available for purchase. This lane never edits standard restock state.
"""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

import local_stock_watch as local

STATE_PATH = Path("hidden_stock_state_v1.json")
WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
SITES = ("br", "bilka", "foetex")
WORKERS = 6
MAX_ALERTS_PER_RUN = 4
STATE_VERSION = 1


def empty_state():
    return {"version": STATE_VERSION, "baseline_sites": {}, "site_scan_seq": {},
            "items": {}, "health": {}, "last_run": None}


def load_state():
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if state.get("version") != STATE_VERSION or not isinstance(state.get("items"), dict):
            return empty_state()
        for key, default in empty_state().items():
            state.setdefault(key, default)
        return state
    except (OSError, ValueError, TypeError):
        return empty_state()


def fetch_detailed_stocks(site_key, config, product):
    """Return actual endpoint rows (including explicit zero) or None if unknown."""
    url = f"{config['api_url']}/clickcollect/availability/{product['sku']}"
    headers = {
        **local.BROWSER_HEADERS,
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {config['api_token']}",
        "Origin": local.SITES[site_key]["base"],
        "Referer": local.SITES[site_key]["home"],
    }
    try:
        response = requests.get(url, headers=headers, timeout=12)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list) or not payload:
            # Salling sometimes replies HTTP 200 + []; that is unknown, NOT 0.
            return None
        stocks = {}
        for entry in payload:
            store = entry.get("store") or {}
            site_id = str(store.get("sapSiteId") or "").strip()
            if not site_id:
                continue
            raw = entry.get("currentStock")
            if raw is None:
                continue
            stocks[site_id] = {
                "name": str(store.get("name") or site_id).strip(),
                "stock": max(0, local.safe_int(raw)),
            }
        return stocks or None
    except (requests.RequestException, ValueError, TypeError):
        return None


def fetch_site(site_key):
    config = local.get_frontend_config(site_key)
    products, catalog_count = local.get_algolia_candidates(site_key, config)
    # The ordinary scanner already handles positive store_count products.
    # This lane is reserved for explicitly hidden, store_count=0 SKUs.
    selected = {}
    for product in products:
        if product.get("visibility") != "PRE-PUBLISH":
            continue
        if local.safe_int(product.get("store_count")) != 0:
            continue
        sku = product.get("sku")
        if sku:
            selected.setdefault(str(sku), product)
    entries = []
    unavailable = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {
            pool.submit(fetch_detailed_stocks, site_key, config, product): product
            for product in selected.values()
        }
        for future in as_completed(futures):
            product = futures[future]
            try:
                stocks = future.result()
            except Exception:
                stocks = None
            if stocks is None:
                unavailable += 1
                continue
            entries.append((product, stocks))
    return catalog_count, len(selected), unavailable, entries


def item_key(site_key, sku, store_id):
    return f"{site_key}|{sku}|{store_id}"


def merge_site(state, site_key, observations, now):
    """Two consecutive successful site scans are required for new alerts.

    Positive stock on the very first baseline is recorded silently. Unknown
    endpoint responses never turn inventory into a zero, and do not qualify
    as a second positive scan for that SKU.
    """
    items = state["items"]
    seq = int(state["site_scan_seq"].get(site_key, 0)) + 1
    state["site_scan_seq"][site_key] = seq
    first_scan = not state["baseline_sites"].get(site_key, False)
    candidates = {}
    for product, stores in observations:
        for store_id, store in stores.items():
            key = item_key(site_key, product["sku"], store_id)
            old = items.get(key)
            count = store["stock"]
            # Do not store hundreds of zeros for products never in stock.
            if count == 0 and not old:
                continue
            if count == 0:
                if old["stock"] != 0 or old["streak"] or old["notified"]:
                    items[key] = {**old, "stock": 0, "streak": 0, "notified": False,
                                  "last_seq": seq}
                continue

            sequential = bool(old and old.get("stock", 0) > 0
                              and old.get("last_seq") == seq - 1)
            streak = min(2, int(old.get("streak", 0)) + 1) if sequential else 1
            notified = bool(old.get("notified", False)) if old else False
            if first_scan:
                # Old, unverified legacy stock must not become a mass alert.
                notified = True
            row = {
                "site": site_key,
                "sku": product["sku"],
                "product_id": product["id"],
                "name": product["name"],
                "type": product["type"],
                "series": product.get("series"),
                "price": product.get("price"),
                "url": product.get("url"),
                "store_id": store_id,
                "store": store["name"],
                "stock": count,
                "streak": streak,
                "notified": notified,
                "last_seq": seq,
            }
            items[key] = row
            if streak >= 2 and not notified and local.local_stock_signal_allowed(product):
                group = (site_key, product["sku"])
                candidates.setdefault(group, []).append(key)

    state["baseline_sites"][site_key] = True
    return candidates


def send_alert(rows):
    if not WEBHOOK:
        raise RuntimeError("DISCORD_WEBHOOK_URL mangler")
    first = rows[0]
    chain = local.SITES[first["site"]]["label"]
    locations = sorted(rows, key=lambda r: (
        not any(word in r["store"].lower()
                for word in ("kolding", "esbjerg", "fredericia", "vejle", "vejen", "brørup")),
        r["store"].lower(),
    ))
    store_lines = [f"**{r['store']}** · {r['stock']} stk."
                   for r in locations[:12]]
    if len(locations) > 12:
        store_lines.append(f"+ {len(locations)-12} andre butikker")
    price = first.get("price")
    price_text = f"{price} kr. (katalog)" if price is not None else "Ukendt"
    embed = {
        "title": f"SKJULT BUTIKSLAGER · {chain} · PRE-PUBLISH",
        "description": (
            f"**{first['name']}**\n"
            "To på hinanden følgende positive API-aflæsninger.\n"
            "**Ikke bekræftet til salg – butikslager kan være historisk eller reserveret.**"
        ),
        "color": 0xF1C40F,
        "fields": [
            {"name": "Butikker med nyt lagersignal",
             "value": "\n".join(store_lines)[:1024], "inline": False},
            {"name": "Pris", "value": price_text, "inline": True},
            {"name": "Vare-ID / SKU",
             "value": f"{first['product_id']} / {first['sku']}", "inline": True},
        ],
        "footer": {"text": "MasterBot · skjult lager, systemtal – ring til butikken"}
    }
    response = requests.post(
        WEBHOOK,
        json={"username": "MasterBot", "allowed_mentions": {"parse": []},
              "embeds": [embed]},
        timeout=15,
    )
    response.raise_for_status()


def main():
    state = load_state()
    now = datetime.now(timezone.utc).isoformat()
    pending = {}
    for site_key in SITES:
        try:
            hits, chosen, unavailable, entries = fetch_site(site_key)
        except Exception as exc:
            print(f"HIDDEN STOCK {site_key.upper()} KILDEFEJL: {type(exc).__name__}: {exc}")
            state["health"][site_key] = {"status": "source_error"}
            continue
        # If an entire retailer stops returning usable detailed data,
        # preserve its baseline and confirmation counters.
        if chosen and not entries:
            state["health"][site_key] = {
                "status": "no_availability", "candidates": chosen,
                "unknown": unavailable,
            }
            print(f"HIDDEN STOCK {site_key.upper()}: ingen gyldige availability-svar")
            continue
        new = merge_site(state, site_key, entries, now)
        pending.update(new)
        state["health"][site_key] = {
            "status": "ok", "catalog_hits": hits, "candidates": chosen,
            "checked": len(entries), "unknown": unavailable,
        }
        positive = sum(r["stock"] > 0 for r in state["items"].values()
                       if r["site"] == site_key)
        print(
            f"HIDDEN STOCK {site_key.upper()}: {chosen} skjulte kandidater | "
            f"{len(entries)} svar | {unavailable} ukendte | "
            f"{positive} positive butiksposter"
        )

    # A queued second-positive candidate is retried if a webhook failed
    # or the per-run spam limit postponed it.
    queued = {}
    for key, row in state["items"].items():
        if (row.get("stock", 0) > 0 and row.get("streak", 0) >= 2
                and not row.get("notified")
                and local.local_stock_signal_allowed(row)):
            queued.setdefault((row["site"], row["sku"]), []).append(key)

    successes = 0
    for group in sorted(queued, key=lambda g: (
        not any(
            word in state["items"][key]["store"].lower()
            for key in queued[g]
            for word in ("kolding", "esbjerg", "fredericia", "vejle", "vejen", "brørup")
        ), g)):
        if successes >= MAX_ALERTS_PER_RUN:
            break
        keys = queued[group]
        try:
            send_alert([state["items"][key] for key in keys])
        except Exception as exc:
            print(f"HIDDEN STOCK ALERT ERROR for {group}: {type(exc).__name__}")
            continue
        for key in keys:
            state["items"][key]["notified"] = True
        successes += 1

    state["last_run"] = now
    state["last_run_alerts"] = successes
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
                          encoding="utf-8")
    print(f"HIDDEN STOCK: scan complete | {successes} Discord alerts")


if __name__ == "__main__":
    main()
