import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode, urljoin

import requests

ROOT = Path(__file__).resolve().parent
SHARED_FILE = ROOT / "restock_bot_github.py"
STATE_FILE = ROOT / "salling_victini_state.json"
TARGET_PRODUCT_ID = "200329839"
TARGET_NAME = "Pokemon Box illust rare Collection W+B"
TARGET_SKU = "11065927-EA"
SITES = ("bilka", "foetex")


def load_shared_namespace():
    source = SHARED_FILE.read_text(encoding="utf-8")
    marker = (
        "# =========================================================\n"
        "# START\n"
        "# ========================================================="
    )
    if marker not in source:
        raise RuntimeError("Kunne ikke finde START-markøren i restock_bot_github.py")

    namespace = {
        "__name__": "salling_victini_watch_shared",
        "__file__": str(SHARED_FILE),
    }
    exec(compile(source.split(marker, 1)[0], str(SHARED_FILE), "exec"), namespace)
    return namespace


def load_state():
    if not STATE_FILE.exists():
        return {"version": 1, "sites": {}, "updated_at": None}
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "sites": {}, "updated_at": None}
    if not isinstance(value, dict):
        return {"version": 1, "sites": {}, "updated_at": None}
    value.setdefault("version", 1)
    value.setdefault("sites", {})
    return value


def save_state(state):
    state["updated_at"] = time.time()
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def fetch_target(shared, site_key):
    site = shared["SALLING_SITES"][site_key]
    config = shared["get_salling_frontend_config"](site_key)
    algolia_url = (
        "https://"
        f"{config['algolia_app_id'].lower()}"
        "-dsn.algolia.net/1/indexes/*/queries"
    )

    params = {
        "query": "illust rare",
        "attributesToRetrieve": '["*"]',
        "hitsPerPage": 50,
        "page": 0,
        "getRankingInfo": "true",
    }
    payload = {
        "requests": [
            {
                "indexName": config["algolia_index"],
                "params": urlencode(params),
            }
        ],
        "strategy": "none",
    }

    response = requests.post(
        algolia_url,
        headers={
            **shared["BROWSER_HEADERS"],
            "Content-Type": "application/json",
            "x-algolia-application-id": config["algolia_app_id"],
            "x-algolia-api-key": config["algolia_api_key"],
        },
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    hits = response.json().get("results", [{}])[0].get("hits", [])

    hit = None
    for candidate in hits:
        product_id = str(candidate.get("id") or candidate.get("objectID") or "")
        sku = str(candidate.get("sku") or candidate.get("erp_product_id") or "")
        if product_id == TARGET_PRODUCT_ID or sku == TARGET_SKU:
            hit = candidate
            break

    # Fallback in case Algolia search ranking changes.
    if hit is None:
        params["query"] = ""
        params["hitsPerPage"] = 250
        payload["requests"][0]["params"] = urlencode(params)
        response = requests.post(
            algolia_url,
            headers={
                **shared["BROWSER_HEADERS"],
                "Content-Type": "application/json",
                "x-algolia-application-id": config["algolia_app_id"],
                "x-algolia-api-key": config["algolia_api_key"],
            },
            json=payload,
            timeout=20,
        )
        response.raise_for_status()
        for candidate in response.json().get("results", [{}])[0].get("hits", []):
            product_id = str(candidate.get("id") or candidate.get("objectID") or "")
            sku = str(candidate.get("sku") or candidate.get("erp_product_id") or "")
            if product_id == TARGET_PRODUCT_ID or sku == TARGET_SKU:
                hit = candidate
                break

    if hit is None:
        raise RuntimeError(f"Victini target {TARGET_PRODUCT_ID} blev ikke fundet")

    sku = str(hit.get("sku") or hit.get("erp_product_id") or TARGET_SKU)
    store_count = max(0, shared["safe_int"](hit.get("in_stock_stores_count"), 0))
    local_stocks = {}

    if sku and store_count > 0:
        try:
            local_stocks = shared["get_salling_local_stocks"](
                site_key,
                sku,
                requests.Session(),
                config,
            )
        except Exception as error:
            print(f"VICTINI {site_key.upper()} lokal lagerfejl: {error}")

    product_url = hit.get("product_url")
    return {
        "id": TARGET_PRODUCT_ID,
        "sku": sku,
        "name": hit.get("name") or TARGET_NAME,
        "price": hit.get("sales_price"),
        "is_exposed": bool(hit.get("is_exposed")),
        "online_count": max(0, shared["safe_int"](hit.get("stock_count_online"), 0)),
        "store_count": store_count,
        "local_stocks": local_stocks,
        "url": urljoin(site["base"], product_url) if product_url else site["home"],
    }


def positive_local_stocks(snapshot):
    result = {}
    for site_id, store in (snapshot.get("local_stocks") or {}).items():
        stock = int(store.get("stock") or 0)
        if stock > 0:
            result[site_id] = {
                "name": store.get("name") or site_id,
                "stock": stock,
            }
    return result


def events_between(old, current):
    events = []
    if not old.get("is_exposed") and current.get("is_exposed"):
        events.append("PRODUKTET ER NU EKSPONERET")
    if int(old.get("online_count") or 0) <= 0 < int(current.get("online_count") or 0):
        events.append(f"ONLINE LAGER {current['online_count']} STK.")
    if int(old.get("store_count") or 0) <= 0 < int(current.get("store_count") or 0):
        events.append(f"BUTIKSLAGER I {current['store_count']} BUTIKKER")

    old_local = positive_local_stocks(old)
    current_local = positive_local_stocks(current)
    for site_id, store in current_local.items():
        old_stock = int((old_local.get(site_id) or {}).get("stock") or 0)
        if old_stock <= 0 < int(store.get("stock") or 0):
            events.append(f"{store['name']} {store['stock']} STK.")

    return events


def snapshot_is_live(snapshot):
    return (
        bool(snapshot.get("is_exposed"))
        or int(snapshot.get("online_count") or 0) > 0
        or int(snapshot.get("store_count") or 0) > 0
        or bool(positive_local_stocks(snapshot))
    )


def send_alert(site_key, current, events):
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        raise RuntimeError("DISCORD_WEBHOOK_URL mangler")

    label = site_key.upper()
    local_bits = [
        f"{store['name']} {store['stock']} stk."
        for store in positive_local_stocks(current).values()
    ]
    stock_line = (
        f"Online {current.get('online_count', 0)} stk. · "
        f"butikker {current.get('store_count', 0)}"
    )
    if local_bits:
        stock_line += " · " + " · ".join(local_bits)

    message = (
        f"🚨 **VICTINI TARGET · {label}**\n"
        f"**{current.get('name') or TARGET_NAME}**\n"
        f"⚡ {' · '.join(events)}\n"
        f"💰 {current.get('price')} kr.\n"
        f"📦 {stock_line}\n"
        f"🆔 {current.get('id')} · SKU {current.get('sku')}\n"
        f"🔗 {current.get('url')}"
    )

    response = requests.post(webhook, json={"content": message}, timeout=15)
    response.raise_for_status()


def main():
    if not os.getenv("DISCORD_WEBHOOK_URL"):
        raise RuntimeError("DISCORD_WEBHOOK_URL mangler")

    shared = load_shared_namespace()
    state = load_state()
    sites_state = state.setdefault("sites", {})

    for site_key in SITES:
        try:
            current = fetch_target(shared, site_key)
        except Exception as error:
            print(f"VICTINI {site_key.upper()} FEJL: {error}")
            continue

        old = sites_state.get(site_key)
        if not isinstance(old, dict):
            if snapshot_is_live(current):
                send_alert(site_key, current, ["TARGET ALLEREDE LIVE VED BASELINE"])
            else:
                print(
                    f"VICTINI {site_key.upper()} baseline: skjult, "
                    f"online {current['online_count']}, butikker {current['store_count']}"
                )
        else:
            events = events_between(old, current)
            if events:
                send_alert(site_key, current, events)
                print(f"VICTINI {site_key.upper()} ALERT: {' | '.join(events)}")
            else:
                print(
                    f"VICTINI {site_key.upper()}: exposed={current['is_exposed']} · "
                    f"online={current['online_count']} · butikker={current['store_count']}"
                )

        sites_state[site_key] = current

    save_state(state)


if __name__ == "__main__":
    main()
