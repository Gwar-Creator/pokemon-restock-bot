#!/usr/bin/env python3
"""Shadow scanner for Indeks Retail's Pokémon TCG catalogues.

Bog & idé and Legekæden are intentionally data-only while we qualify the new
Shopify feeds and determine whether the two storefronts share the same online
inventory. No Discord webhook is read or called from this module.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


STATE_FILE = Path("indeks_retail_shadow_state.json")
STATE_VERSION = 1
MAX_PAGES = 5
PAGE_SIZE = 250
TIMEOUT_SECONDS = 20

SOURCES = {
    "legekaeden": {
        "label": "LEGEKÆDEN",
        "base": "https://www.legekaeden.dk",
        "path": "/collections/pokemon-tcg/products.json",
    },
    "bogide": {
        "label": "BOG & IDÉ",
        "base": "https://www.bog-ide.dk",
        "path": "/collections/pokemon-tcg/products.json",
    },
}

PREORDER_MARKERS = ("forudbestilling", "preorder", "pre-order")


def _now() -> str:
    return datetime.now(ZoneInfo("UTC")).isoformat()


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {"version": STATE_VERSION, "mode": "shadow", "sources": {}}
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": STATE_VERSION, "mode": "shadow", "sources": {}}
    return value if isinstance(value, dict) else {"version": STATE_VERSION, "mode": "shadow", "sources": {}}


def _price(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _normalise_product(source_key: str, raw: dict) -> tuple[str, dict] | None:
    title = str(raw.get("title") or "").strip()
    handle = str(raw.get("handle") or "").strip()
    if not title or not handle:
        return None

    variants = raw.get("variants") or []
    if not isinstance(variants, list):
        variants = []

    available_variants = [variant for variant in variants if isinstance(variant, dict) and variant.get("available") is True]
    priced_available = [(_price(variant.get("price")), variant) for variant in available_variants]
    priced_available = [(price, variant) for price, variant in priced_available if price is not None]
    priced_all = [(_price(variant.get("price")), variant) for variant in variants if isinstance(variant, dict)]
    priced_all = [(price, variant) for price, variant in priced_all if price is not None]

    chosen = min(priced_available or priced_all, key=lambda item: item[0], default=(None, {}))
    chosen_price, chosen_variant = chosen

    skus = sorted({str(variant.get("sku") or "").strip() for variant in variants if isinstance(variant, dict)} - {""})
    barcodes = sorted({str(variant.get("barcode") or "").strip() for variant in variants if isinstance(variant, dict)} - {""})

    source = SOURCES[source_key]
    searchable = " ".join([title, str(raw.get("tags") or "")]).lower()
    product = {
        "name": title,
        "handle": handle,
        "shopify_product_id": str(raw.get("id") or ""),
        "game": "POKÉMON",
        "price": chosen_price,
        "in_stock": bool(available_variants),
        "preorder": any(marker in searchable for marker in PREORDER_MARKERS),
        "url": f"{source['base']}/products/{handle}",
        "skus": skus,
        "barcodes": barcodes,
        "variant_id": str((chosen_variant or {}).get("id") or ""),
        "published_at": raw.get("published_at"),
        "updated_at": raw.get("updated_at"),
    }
    return handle, product


def fetch_source(source_key: str, session=None) -> dict:
    if source_key not in SOURCES:
        raise KeyError(source_key)
    session = session or requests.Session()
    source = SOURCES[source_key]
    products = {}
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; PokemonRestockBot/1.0; +https://github.com/Gwar-Creator/pokemon-restock-bot)",
    }

    for page in range(1, MAX_PAGES + 1):
        response = session.get(
            source["base"] + source["path"],
            params={"limit": PAGE_SIZE, "page": page},
            headers=headers,
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        raw_products = payload.get("products") if isinstance(payload, dict) else None
        if not isinstance(raw_products, list):
            raise RuntimeError("Shopify feed mangler products-listen")

        for raw in raw_products:
            if not isinstance(raw, dict):
                continue
            normalised = _normalise_product(source_key, raw)
            if normalised is None:
                continue
            product_id, product = normalised
            products[product_id] = product

        if len(raw_products) < PAGE_SIZE:
            break

    return products


def _sku_index(products: dict) -> dict[str, str]:
    result = {}
    for handle, product in products.items():
        for sku in product.get("skus") or []:
            if sku:
                result.setdefault(str(sku), handle)
        for barcode in product.get("barcodes") or []:
            if barcode:
                result.setdefault(f"barcode:{barcode}", handle)
    return result


def _comparison(sources: dict) -> dict:
    left = ((sources.get("legekaeden") or {}).get("products") or {})
    right = ((sources.get("bogide") or {}).get("products") or {})

    left_handles = set(left)
    right_handles = set(right)
    shared_handles = sorted(left_handles & right_handles)

    left_skus = _sku_index(left)
    right_skus = _sku_index(right)
    shared_skus = sorted(set(left_skus) & set(right_skus))

    stock_disagreements = []
    price_disagreements = []
    for handle in shared_handles:
        lp = left[handle]
        rp = right[handle]
        if bool(lp.get("in_stock")) != bool(rp.get("in_stock")):
            stock_disagreements.append(handle)
        if lp.get("price") != rp.get("price"):
            price_disagreements.append(handle)

    return {
        "shared_handles": len(shared_handles),
        "shared_skus_or_barcodes": len(shared_skus),
        "legekaeden_only_handles": len(left_handles - right_handles),
        "bogide_only_handles": len(right_handles - left_handles),
        "stock_disagreements": stock_disagreements[:50],
        "price_disagreements": price_disagreements[:50],
    }


def _success_health(old_health: dict, count: int, now: str, changed: bool) -> dict:
    if (
        not changed
        and (old_health or {}).get("status") == "ok"
        and (old_health or {}).get("observed_count") == count
    ):
        return old_health
    return {
        "status": "ok",
        "last_success": now,
        "consecutive_failures": 0,
        "last_error": "",
        "observed_count": count,
    }


def _failure_health(old_health: dict, error: Exception, now: str) -> dict:
    return {
        "status": "failed",
        "last_success": (old_health or {}).get("last_success"),
        "last_failure": now,
        "consecutive_failures": int((old_health or {}).get("consecutive_failures") or 0) + 1,
        "last_error": str(error)[:500],
        "observed_count": (old_health or {}).get("observed_count"),
    }


def run_scan(fetcher=fetch_source) -> int:
    old_state = _load_state()
    old_sources = old_state.get("sources") or {}
    new_sources = {}
    successful = 0
    changed = False
    now = _now()

    for source_key, config in SOURCES.items():
        old_entry = old_sources.get(source_key) or {}
        old_products = old_entry.get("products") or {}
        old_health = old_entry.get("health") or {}
        products = old_products

        try:
            products = fetcher(source_key)
            source_changed = products != old_products
            health = _success_health(old_health, len(products), now, source_changed)
            successful += 1
            changed = changed or source_changed or health != old_health
            stock = sum(1 for product in products.values() if product.get("in_stock") is True)
            print(f"INDEKS SHADOW {config['label']}: {len(products)} produkter | på lager {stock} | health=ok")
        except Exception as error:
            health = _failure_health(old_health, error, now)
            changed = True
            print(f"INDEKS SHADOW {config['label']} FEJL: {error} | gammel baseline bevaret")

        new_sources[source_key] = {
            "label": config["label"],
            "mode": "shadow",
            "health": health,
            "products": products,
        }

    comparison = _comparison(new_sources)
    old_comparison = old_state.get("comparison") or {}
    changed = changed or comparison != old_comparison

    state = {
        "version": STATE_VERSION,
        "mode": "shadow",
        "updated_at": now if changed or not old_state.get("updated_at") else old_state.get("updated_at"),
        "sources": new_sources,
        "comparison": comparison,
    }
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    print(
        "INDEKS SHADOW overlap: "
        f"handles={comparison['shared_handles']} | "
        f"sku/barcode={comparison['shared_skus_or_barcodes']} | "
        f"stock-forskelle={len(comparison['stock_disagreements'])} | "
        f"prisforskelle={len(comparison['price_disagreements'])}"
    )
    print(f"INDEKS SHADOW: {successful}/{len(SOURCES)} kilder ok | Discord=off")
    return 0 if successful else 1


def main() -> int:
    return run_scan()


if __name__ == "__main__":
    raise SystemExit(main())
