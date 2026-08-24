import json
import os
import re
from pathlib import Path
from urllib.parse import urlencode

import requests

ROOT = Path(__file__).resolve().parent
SHARED_FILE = ROOT / "restock_bot_github.py"
TARGET_PRODUCT_ID = "200329839"
TARGET_SKU = "11065927-EA"

SEARCH_TERMS = (
    "victini",
    "black bolt",
    "white flare",
    "illustration collection",
)

WATCH_MARKERS = SEARCH_TERMS + (
    "unova",
    "collection",
)

METADATA_MARKERS = (
    "date",
    "time",
    "start",
    "end",
    "from",
    "until",
    "campaign",
    "publish",
    "release",
    "avail",
    "stock",
    "expos",
    "active",
    "create",
    "update",
    "valid",
    "launch",
    "sold",
    "reserv",
)

SITES = ("br", "bilka", "foetex")


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
        "__name__": "salling_prerelease_probe_shared",
        "__file__": str(SHARED_FILE),
    }
    exec(compile(source.split(marker, 1)[0], str(SHARED_FILE), "exec"), namespace)
    return namespace


def frontend_config(shared, site_key):
    if site_key == "br":
        config = shared["get_br_frontend_config"]()
        return {
            **config,
            "algolia_index": shared["BR_ALGOLIA_INDEX"],
            "api_url": shared["BR_API_BASE"],
            "base": shared["BR_BASE"],
            "home": shared["BR_HOME"],
        }

    config = shared["get_salling_frontend_config"](site_key)
    site = shared["SALLING_SITES"][site_key]
    return {
        **config,
        "base": site["base"],
        "home": site["home"],
    }


def compact_hit(site_key, term, hit):
    return {
        "site": site_key,
        "term": term,
        "id": str(hit.get("id") or hit.get("objectID") or ""),
        "name": hit.get("name"),
        "price": hit.get("sales_price"),
        "list_price": hit.get("list_price"),
        "is_exposed": hit.get("is_exposed"),
        "online_stock": hit.get("stock_count_online"),
        "stores": hit.get("in_stock_stores_count"),
        "sold_online": hit.get("sold_online"),
        "sold_in_stores": hit.get("sold_in_stores"),
        "is_click_and_collectible": hit.get("is_click_and_collectible"),
        "is_reservable": hit.get("is_reservable"),
        "sku": hit.get("sku") or hit.get("erp_product_id"),
        "product_url": hit.get("product_url"),
    }


def algolia_query(shared, site_key, params):
    config = frontend_config(shared, site_key)
    algolia_url = (
        "https://"
        f"{config['algolia_app_id'].lower()}"
        "-dsn.algolia.net/1/indexes/*/queries"
    )
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
    return response.json().get("results", [{}])[0].get("hits", [])


def run_query(shared, site_key, term):
    hits = algolia_query(
        shared,
        site_key,
        {
            "query": term,
            "attributesToRetrieve": '["*"]',
            "hitsPerPage": 100,
            "page": 0,
            "getRankingInfo": "true",
        },
    )

    relevant = []
    for hit in hits:
        name = str(hit.get("name") or "")
        normalized = re.sub(r"\s+", " ", name.lower()).strip()
        if any(marker in normalized for marker in SEARCH_TERMS):
            relevant.append(compact_hit(site_key, term, hit))

    return relevant, len(hits)


def fetch_hidden_pokemon_hits(shared, site_key):
    hits = algolia_query(
        shared,
        site_key,
        {
            "query": "",
            "attributesToRetrieve": '["*"]',
            "filters": (
                'cfh_nodes:"CFH.CollectionCards" AND '
                '(f_brand:"Pokemon" OR f_brand:"Pokémon" OR '
                'facets.productSeriesToys:"Pokémon")'
            ),
            "hitsPerPage": 250,
            "page": 0,
            "getRankingInfo": "true",
        },
    )

    pokemon_hits = []
    for hit in hits:
        try:
            if not shared["is_real_pokemon_tcg"](hit):
                continue
        except Exception:
            continue
        pokemon_hits.append(hit)

    return hits, pokemon_hits


def run_hidden_catalog(shared, site_key):
    hits, pokemon_hits = fetch_hidden_pokemon_hits(shared, site_key)
    hidden = [hit for hit in pokemon_hits if hit.get("is_exposed") is False]
    suspicious = []
    for hit in hidden:
        name = re.sub(r"\s+", " ", str(hit.get("name") or "").lower()).strip()
        try:
            price = float(hit.get("sales_price"))
        except (TypeError, ValueError):
            price = None

        if (
            any(marker in name for marker in WATCH_MARKERS)
            or (price is not None and 278.0 <= price <= 280.0)
        ):
            suspicious.append(compact_hit(site_key, "hidden-catalog", hit))

    return len(hits), len(pokemon_hits), len(hidden), suspicious


def metadata_fields(hit):
    found = {}
    for key, value in hit.items():
        lowered = str(key).lower()
        if any(marker in lowered for marker in METADATA_MARKERS):
            found[key] = value
    return found


def find_target(shared, site_key):
    hits = algolia_query(
        shared,
        site_key,
        {
            "query": "illust rare",
            "attributesToRetrieve": '["*"]',
            "hitsPerPage": 100,
            "page": 0,
            "getRankingInfo": "true",
        },
    )
    for hit in hits:
        product_id = str(hit.get("id") or hit.get("objectID") or "")
        sku = str(hit.get("sku") or hit.get("erp_product_id") or "")
        if product_id == TARGET_PRODUCT_ID or sku == TARGET_SKU:
            return hit
    return None


def availability_probe(shared, site_key, sku):
    config = frontend_config(shared, site_key)
    url = f"{config['api_url']}/clickcollect/availability/{sku}"
    headers = {
        **shared["BROWSER_HEADERS"],
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {config['api_token']}",
        "Origin": config["base"],
        "Referer": config["home"],
    }
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        return {"response_type": type(payload).__name__, "raw": payload}

    stores = []
    total_units = 0
    positive_units = 0
    positive_stores = 0
    for item in payload:
        store = item.get("store") or {}
        try:
            stock = max(0, int(item.get("currentStock") or 0))
        except (TypeError, ValueError):
            stock = 0
        total_units += stock
        if stock > 0:
            positive_units += stock
            positive_stores += 1
            stores.append({
                "site_id": str(store.get("sapSiteId") or ""),
                "name": store.get("name"),
                "stock": stock,
                "available": item.get("available"),
            })

    return {
        "records": len(payload),
        "positive_stores": positive_stores,
        "positive_units": positive_units,
        "total_units": total_units,
        "stores": stores[:50],
    }


def run_metadata_diagnostics(shared, site_key):
    _, pokemon_hits = fetch_hidden_pokemon_hits(shared, site_key)
    hidden = [hit for hit in pokemon_hits if hit.get("is_exposed") is False]

    target = None
    for hit in pokemon_hits:
        product_id = str(hit.get("id") or hit.get("objectID") or "")
        sku = str(hit.get("sku") or hit.get("erp_product_id") or "")
        if product_id == TARGET_PRODUCT_ID or sku == TARGET_SKU:
            target = hit
            break

    print(f"METADATA {site_key.upper()}: {len(hidden)} skjulte Pokemon-poster")

    if target is None:
        target = find_target(shared, site_key)

    if target is None:
        print(f"TARGET {site_key.upper()}: {TARGET_PRODUCT_ID}/{TARGET_SKU} ikke fundet")
    else:
        print(
            f"TARGET {site_key.upper()} SUMMARY "
            + json.dumps(compact_hit(site_key, "target", target), ensure_ascii=False, sort_keys=True)
        )
        print(
            f"TARGET {site_key.upper()} METADATA "
            + json.dumps(metadata_fields(target), ensure_ascii=False, sort_keys=True, default=str)
        )

    try:
        availability = availability_probe(shared, site_key, TARGET_SKU)
        print(
            f"AVAILABILITY {site_key.upper()} "
            + json.dumps(availability, ensure_ascii=False, sort_keys=True, default=str)
        )
    except Exception as error:
        print(f"AVAILABILITY {site_key.upper()}: FEJL {error}")


def main():
    if not os.getenv("DISCORD_WEBHOOK_URL"):
        raise RuntimeError("DISCORD_WEBHOOK_URL mangler til shared loader")

    shared = load_shared_namespace()
    all_hits = []

    print("SALLING PRE-RELEASE PROBE")
    print("BR + Bilka + Foetex hidden catalogue and all-store availability")

    for site_key in SITES:
        for term in SEARCH_TERMS:
            try:
                relevant, raw_count = run_query(shared, site_key, term)
            except Exception as error:
                print(f"PROBE {site_key.upper()} / {term}: FEJL {error}")
                continue

            print(
                f"PROBE {site_key.upper()} / {term}: "
                f"{raw_count} rå hits · {len(relevant)} relevante"
            )
            all_hits.extend(relevant)

        try:
            raw_count, pokemon_count, hidden_count, suspicious = run_hidden_catalog(
                shared,
                site_key,
            )
            print(
                f"HIDDEN {site_key.upper()}: {raw_count} rå · "
                f"{pokemon_count} Pokémon TCG · {hidden_count} skjulte · "
                f"{len(suspicious)} interessante"
            )
            for hit in suspicious:
                print("HIDDEN HIT " + json.dumps(hit, ensure_ascii=False, sort_keys=True))
            all_hits.extend(suspicious)
        except Exception as error:
            print(f"HIDDEN {site_key.upper()}: FEJL {error}")

        try:
            run_metadata_diagnostics(shared, site_key)
        except Exception as error:
            print(f"METADATA {site_key.upper()}: FEJL {error}")

    unique = {}
    for hit in all_hits:
        key = (hit.get("site"), hit.get("id") or hit.get("name"))
        unique[key] = hit

    print(f"PROBE RESULTAT: {len(unique)} unikke relevante produkter")


if __name__ == "__main__":
    main()
