import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlencode, urljoin

import requests

ROOT = Path(__file__).resolve().parent
SHARED_FILE = ROOT / "restock_bot_github.py"
STATE_FILE = ROOT / "salling_early_radar_state.json"
STATE_VERSION = 1
SITES = ("bilka", "foetex")

# High-signal sealed products. Single loose boosters and battle/accessory noise
# are deliberately excluded; the shared restock relevance filter is applied too.
CORE_MARKERS = (
    "booster bundle",
    "booster box",
    "booster display",
    "elite trainer box",
    " etb ",
    "premium collection",
    "premium box",
    "ultra-premium",
    "ultra premium",
    " upc ",
    "special collection",
    "illustration collection",
    "illustration rare collection",
    "illust rare collection",
    "binder collection",
    "poster collection",
    "first partner",
    "collection box",
    " ex box",
    "ex box",
    " tin ",
)

WATCH_MARKERS = (
    "victini",
    "first partner",
    "30th",
    "30th anniversary",
    "30 year",
    "30 år",
    "anniversary",
    "ascended heroes",
    "black bolt",
    "white flare",
)

PACK_MARKERS = (
    "booster pack",
    "sleeved booster",
    "sleeve booster",
)


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
        "__name__": "salling_early_radar_shared",
        "__file__": str(SHARED_FILE),
    }
    exec(compile(source.split(marker, 1)[0], str(SHARED_FILE), "exec"), namespace)
    return namespace


def load_state():
    if not STATE_FILE.exists():
        return None
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("version") != STATE_VERSION:
        return None
    if not isinstance(value.get("products"), dict):
        return None
    return value


def save_state(products):
    payload = {
        "version": STATE_VERSION,
        "updated_at": time.time(),
        "products": products,
    }
    STATE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def clean_name(name):
    return " " + re.sub(r"\s+", " ", str(name or "").lower()).strip() + " "


def early_product_allowed(shared, hit):
    product = {
        "name": hit.get("name") or "",
        "game": "POKÉMON",
    }
    if not shared["restock_alert_allowed"](product, "POKÉMON"):
        return False

    text = clean_name(product["name"])
    if any(marker in text for marker in PACK_MARKERS):
        return False

    # A title that is merely a loose "booster" should not enter Early Radar.
    if (
        " booster " in text
        and "booster bundle" not in text
        and "booster box" not in text
        and "booster display" not in text
        and "elite trainer box" not in text
        and not re.search(r"\betb\b", text)
    ):
        return False

    if any(marker in text for marker in WATCH_MARKERS):
        return True
    return any(marker in text for marker in CORE_MARKERS)


def priority_for(name):
    text = clean_name(name)
    if any(marker in text for marker in WATCH_MARKERS):
        return "WATCH"
    if any(
        marker in text
        for marker in (
            "booster bundle",
            "booster box",
            "booster display",
            "elite trainer box",
            " etb ",
            "ultra-premium",
            "ultra premium",
            " upc ",
            "illustration collection",
            "illustration rare collection",
            "illust rare collection",
            "first partner",
        )
    ):
        return "HIGH"
    return "NORMAL"


def fetch_hidden_catalog(shared, site_key):
    site = shared["SALLING_SITES"][site_key]
    config = shared["get_salling_frontend_config"](site_key)
    algolia_url = (
        "https://"
        f"{config['algolia_app_id'].lower()}"
        "-dsn.algolia.net/1/indexes/*/queries"
    )

    # Empty query intentionally omits is_exposed:true. 250 comfortably covers
    # the current Salling Pokemon catalogue and avoids one request per keyword.
    params = {
        "query": "",
        "attributesToRetrieve": '["*"]',
        "hitsPerPage": 250,
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
        timeout=25,
    )
    response.raise_for_status()

    all_hits = response.json().get("results", [{}])[0].get("hits", [])
    products = {}

    for hit in all_hits:
        if not shared["is_real_pokemon_tcg"](hit):
            continue
        if not early_product_allowed(shared, hit):
            continue

        product_id = str(hit.get("id") or hit.get("objectID") or "").strip()
        if not product_id:
            continue

        product_url = hit.get("product_url")
        products[product_id] = {
            "id": product_id,
            "sku": str(hit.get("sku") or hit.get("erp_product_id") or ""),
            "name": hit.get("name") or "Ukendt Pokemon-produkt",
            "price": hit.get("sales_price"),
            "is_exposed": bool(hit.get("is_exposed")),
            "online_count": max(0, shared["safe_int"](hit.get("stock_count_online"), 0)),
            "store_count": max(0, shared["safe_int"](hit.get("in_stock_stores_count"), 0)),
            "priority": priority_for(hit.get("name")),
            "url": urljoin(site["base"], product_url) if product_url else site["home"],
            "site": site_key,
        }

    return products, len(all_hits)


def merge_catalogs(site_catalogs):
    merged = {}
    for site_key, products in site_catalogs.items():
        for product_id, product in products.items():
            entry = merged.setdefault(
                product_id,
                {
                    "id": product_id,
                    "sku": product.get("sku") or "",
                    "name": product.get("name") or "Ukendt Pokemon-produkt",
                    "price": product.get("price"),
                    "priority": product.get("priority") or "NORMAL",
                    "sites": {},
                },
            )
            if not entry.get("sku") and product.get("sku"):
                entry["sku"] = product["sku"]
            if entry.get("price") is None and product.get("price") is not None:
                entry["price"] = product["price"]
            if product.get("priority") == "WATCH":
                entry["priority"] = "WATCH"
            elif product.get("priority") == "HIGH" and entry.get("priority") != "WATCH":
                entry["priority"] = "HIGH"

            entry["sites"][site_key] = {
                "is_exposed": product.get("is_exposed", False),
                "online_count": product.get("online_count", 0),
                "store_count": product.get("store_count", 0),
                "url": product.get("url") or "",
            }

    return merged


def hidden_somewhere(product):
    return any(not site.get("is_exposed") for site in (product.get("sites") or {}).values())


def live_signal(product):
    for site in (product.get("sites") or {}).values():
        if site.get("is_exposed"):
            return True
        if int(site.get("online_count") or 0) > 0:
            return True
        if int(site.get("store_count") or 0) > 0:
            return True
    return False


def stock_signal_text(product):
    bits = []
    for site_key, site in sorted((product.get("sites") or {}).items()):
        online = int(site.get("online_count") or 0)
        stores = int(site.get("store_count") or 0)
        exposed = bool(site.get("is_exposed"))
        flags = []
        if exposed:
            flags.append("synlig")
        if online > 0:
            flags.append(f"online {online}")
        if stores > 0:
            flags.append(f"{stores} butikker")
        if flags:
            bits.append(f"{site_key.upper()}: " + ", ".join(flags))
    return " · ".join(bits) if bits else "stadig skjult uden lager"


def best_url(product):
    sites = product.get("sites") or {}
    for key in ("bilka", "foetex"):
        url = (sites.get(key) or {}).get("url")
        if url:
            return url
    return ""


def send_alert(title, product, detail):
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        raise RuntimeError("DISCORD_WEBHOOK_URL mangler")

    price = product.get("price")
    price_text = f"{price} kr." if price is not None else "Pris ikke oplyst"
    message = (
        f"🕵️ **SALLING EARLY RADAR · {title}**\n"
        f"**{product.get('name') or 'Ukendt Pokemon-produkt'}**\n"
        f"🎯 {product.get('priority') or 'NORMAL'} · {detail}\n"
        f"💰 {price_text}\n"
        f"🆔 {product.get('id')} · SKU {product.get('sku') or '-'}\n"
        f"📦 {stock_signal_text(product)}\n"
        f"🔗 {best_url(product)}"
    )

    response = requests.post(webhook, json={"content": message}, timeout=15)
    response.raise_for_status()


def became_live(old, current):
    return not live_signal(old) and live_signal(current)


def became_hidden_stocked(old, current):
    if not hidden_somewhere(current):
        return False

    def total_stock_signal(product):
        return sum(
            int(site.get("online_count") or 0) + int(site.get("store_count") or 0)
            for site in (product.get("sites") or {}).values()
        )

    return total_stock_signal(old) <= 0 < total_stock_signal(current)


def main():
    if not os.getenv("DISCORD_WEBHOOK_URL"):
        raise RuntimeError("DISCORD_WEBHOOK_URL mangler")

    shared = load_shared_namespace()
    site_catalogs = {}

    for site_key in SITES:
        try:
            products, raw_count = fetch_hidden_catalog(shared, site_key)
        except Exception as error:
            print(f"EARLY RADAR {site_key.upper()} FEJL: {error}")
            continue
        site_catalogs[site_key] = products
        hidden_count = sum(not product.get("is_exposed") for product in products.values())
        print(
            f"EARLY RADAR {site_key.upper()}: {raw_count} rå hits · "
            f"{len(products)} relevante · {hidden_count} skjulte"
        )

    if not site_catalogs:
        raise RuntimeError("Ingen Salling-kataloger kunne hentes")

    current = merge_catalogs(site_catalogs)
    previous_state = load_state()

    if previous_state is None:
        save_state(current)
        print(
            f"EARLY RADAR baseline: {len(current)} relevante produkt-ID'er, ingen alerts"
        )
        return

    previous = previous_state.get("products") or {}

    for product_id, product in current.items():
        old = previous.get(product_id)

        # The main edge: a brand-new relevant product appears in the hidden
        # public catalogue before Salling exposes it on the storefront.
        if old is None:
            if hidden_somewhere(product):
                send_alert("NY SKJULT VARE", product, "nyt produkt-ID fundet før offentlig visning")
            else:
                # Still useful if Salling creates + exposes between two scans.
                send_alert("NY VARE", product, "nyt produkt-ID fundet")
            continue

        # Hidden catalogue stock/exposure transitions can be earlier than the
        # ordinary storefront scanner. Alert once when the signal first turns live.
        if became_hidden_stocked(old, product):
            send_alert("LAGER FØR LIVE", product, "skjult vare har fået lager-signal")
        elif became_live(old, product):
            send_alert("GÅR LIVE", product, "vare har fået første live-signal")

    save_state(current)
    print(f"EARLY RADAR færdig: {len(current)} relevante produkt-ID'er")


if __name__ == "__main__":
    main()
