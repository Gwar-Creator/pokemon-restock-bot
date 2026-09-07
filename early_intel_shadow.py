#!/usr/bin/env python3
"""Shadow-only early retail intelligence audit.

Purpose: learn which public metadata moves before real Pokemon TCG launches/restocks.
No Discord output. The script persists snapshots for BR/Bilka/Foetex and Proshop
and prints only compact diagnostics about meaningful field changes.
"""

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlencode, urljoin

import requests

ROOT = Path(__file__).resolve().parent
SHARED_FILE = ROOT / "restock_bot_github.py"
STATE_FILE = ROOT / "early_intel_shadow_state.json"
STATE_VERSION = 1
SALLING_SITES = ("br", "bilka", "foetex")

TRACKED_SALLING_FIELDS = (
    "sales_price",
    "is_exposed",
    "stock_count_online",
    "in_stock_stores_count",
    "f_campaign_name",
    "f_stock_availability",
    "expected_available_from",
    "online_from",
    "online_to",
    "promotion_start_date",
    "promotion_end_date",
    "not_reservable_from",
    "not_reservable_to",
    "is_click_and_collectible",
    "is_reservable",
    "sold_online",
    "sold_in_stores",
    "quantity_restriction",
    "has_image",
    "image_primary",
    "epoch_updated_at",
)

EXPECTED_DATE_RE = re.compile(
    r"(?:forventet\s+p[åa]\s+lager|forventes\s+p[åa]\s+eget\s+lager)\s*"
    r"(\d{1,2}-\d{1,2}-\d{4})",
    re.I,
)


def load_shared_namespace():
    source = SHARED_FILE.read_text(encoding="utf-8")
    marker = (
        "# =========================================================\n"
        "# START\n"
        "# ========================================================="
    )
    definitions = source.split(marker, 1)[0]
    namespace = {"__name__": "early_intel_shared", "__file__": str(SHARED_FILE)}
    exec(compile(definitions, str(SHARED_FILE), "exec"), namespace)
    return namespace


def normalize(value):
    if isinstance(value, list):
        return sorted(str(item) for item in value if item not in (None, ""))
    if isinstance(value, dict):
        return {str(k): normalize(v) for k, v in sorted(value.items())}
    return value


def load_state():
    if not STATE_FILE.exists():
        return None
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if state.get("version") != STATE_VERSION:
        return None
    return state


def save_state(snapshot):
    STATE_FILE.write_text(
        json.dumps(
            {"version": STATE_VERSION, "updated_at": time.time(), **snapshot},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def salling_config(shared, site_key):
    if site_key == "br":
        config = shared["get_br_frontend_config"]()
        return {
            "base": shared["BR_BASE"],
            "index": config["algolia_index"],
            "app_id": config["algolia_app_id"],
            "api_key": config["algolia_api_key"],
        }

    site = shared["SALLING_SITES"][site_key]
    config = shared["get_salling_frontend_config"](site_key)
    return {
        "base": site["base"],
        "index": config["algolia_index"],
        "app_id": config["algolia_app_id"],
        "api_key": config["algolia_api_key"],
    }


def fetch_salling_catalog(shared, site_key):
    config = salling_config(shared, site_key)
    url = f"https://{config['app_id'].lower()}-dsn.algolia.net/1/indexes/*/queries"
    params = {
        "query": "",
        "attributesToRetrieve": '["*"]',
        "filters": (
            'cfh_nodes:"CFH.CollectionCards" AND '
            '(f_brand:"Pokemon" OR f_brand:"Pokémon" OR facets.productSeriesToys:"Pokémon")'
        ),
        "hitsPerPage": 500,
        "page": 0,
        "getRankingInfo": "true",
    }
    response = requests.post(
        url,
        headers={
            **shared["BROWSER_HEADERS"],
            "Content-Type": "application/json",
            "x-algolia-application-id": config["app_id"],
            "x-algolia-api-key": config["api_key"],
        },
        json={"requests": [{"indexName": config["index"], "params": urlencode(params)}]},
        timeout=25,
    )
    response.raise_for_status()
    result = response.json().get("results", [{}])[0]
    hits = result.get("hits") or []

    products = {}
    for hit in hits:
        if not shared["is_real_pokemon_tcg"](hit):
            continue
        product_id = str(hit.get("id") or hit.get("objectID") or "").strip()
        if not product_id:
            continue
        name = str(hit.get("name") or "")
        if not shared["restock_alert_allowed"]({"name": name, "game": "POKÉMON"}, "POKÉMON"):
            continue
        row = {
            "id": product_id,
            "sku": str(hit.get("sku") or hit.get("erp_product_id") or ""),
            "name": name,
            "url": urljoin(config["base"], hit.get("product_url") or ""),
        }
        for field in TRACKED_SALLING_FIELDS:
            row[field] = normalize(hit.get(field))
        products[product_id] = row
    return products, int(result.get("nbHits") or len(hits))


def proshop_status(segment):
    low = segment.lower()
    if "bestilt: forventet på lager" in low:
        return "BESTILT_DATO"
    if "fjernlager" in low:
        return "FJERNLAGER"
    if "på lager" in low or "pa lager" in low:
        return "PÅ LAGER"
    if "bestillingsvare" in low or "bestilt" in low:
        return "BESTILLINGSVARE"
    return "UKENDT"


def parse_proshop_reader(text):
    products = {}
    # Reader output contains normal markdown links. Segment each product by the
    # next Proshop product link so status/date text stays attached to that item.
    matches = list(re.finditer(r"\[([^\]]+)\]\((https://www\.proshop\.dk/[^)]+/(\d+))\)", text))
    for index, match in enumerate(matches):
        name = re.sub(r"\s+", " ", match.group(1)).strip()
        if "pokemon" not in name.lower() or "tcg" not in name.lower():
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else min(len(text), match.end() + 2500)
        segment = text[match.start():end]
        expected = EXPECTED_DATE_RE.search(segment)
        price_match = re.search(r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*kr\.", segment)
        price = None
        if price_match:
            try:
                price = float(price_match.group(1).replace(".", "").replace(",", "."))
            except ValueError:
                pass
        product_id = match.group(3)
        products[product_id] = {
            "id": product_id,
            "name": name,
            "url": match.group(2),
            "status": proshop_status(segment),
            "expected_stock_date": expected.group(1) if expected else None,
            "price": price,
            "new_badge": "NYHED" in segment.upper(),
            "raw_status_excerpt": re.sub(r"\s+", " ", segment)[:500],
        }
    return products


def fetch_proshop(shared):
    response = requests.get(
        shared["PROSHOP_READER_URL"],
        headers={
            "Accept": "text/plain, text/markdown;q=0.9, */*;q=0.5",
            "User-Agent": "Pokemon-Lorcana-MasterBot/2.6 EarlyIntelShadow",
            "x-no-cache": "true",
            "x-engine": "browser",
        },
        timeout=40,
    )
    response.raise_for_status()
    return parse_proshop_reader(response.text)


def changed_fields(old, new, ignore=("raw_status_excerpt",)):
    keys = sorted(set(old) | set(new))
    return [key for key in keys if key not in ignore and old.get(key) != new.get(key)]


def report_source(source, old_products, new_products):
    old_products = old_products or {}
    new_ids = sorted(set(new_products) - set(old_products))
    removed_ids = sorted(set(old_products) - set(new_products))
    changes = []
    for product_id in sorted(set(new_products) & set(old_products)):
        fields = changed_fields(old_products[product_id], new_products[product_id])
        if fields:
            changes.append((product_id, fields, new_products[product_id]))

    print(
        f"EARLY INTEL SHADOW {source.upper()}: {len(new_products)} products | "
        f"new={len(new_ids)} | removed={len(removed_ids)} | changed={len(changes)}"
    )
    for product_id in new_ids[:10]:
        product = new_products[product_id]
        print(f"EARLY INTEL NEW: {source} | {product_id} | {product.get('name')}")
    for product_id, fields, product in changes[:20]:
        print(
            f"EARLY INTEL CHANGE: {source} | {product_id} | "
            f"{','.join(fields)} | {product.get('name')}"
        )


def main():
    shared = load_shared_namespace()
    previous = load_state() or {"sources": {}}
    old_sources = previous.get("sources") or {}
    sources = {}

    for site_key in SALLING_SITES:
        try:
            products, raw_count = fetch_salling_catalog(shared, site_key)
            sources[site_key] = products
            print(f"EARLY INTEL {site_key.upper()}: raw Pokemon hits={raw_count}")
            report_source(site_key, old_sources.get(site_key), products)
        except Exception as error:
            print(f"EARLY INTEL {site_key.upper()} FEJL: {error}")
            if site_key in old_sources:
                sources[site_key] = old_sources[site_key]

    try:
        proshop = fetch_proshop(shared)
        sources["proshop"] = proshop
        report_source("proshop", old_sources.get("proshop"), proshop)
    except Exception as error:
        print(f"EARLY INTEL PROSHOP FEJL: {error}")
        if "proshop" in old_sources:
            sources["proshop"] = old_sources["proshop"]

    save_state({"sources": sources})
    print("EARLY INTEL SHADOW: snapshot saved; Discord=off")


if __name__ == "__main__":
    main()
