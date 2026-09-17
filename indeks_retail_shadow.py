#!/usr/bin/env python3
"""Indeks Retail backup-retail scanner.

Bog & ide and Legekaeden are fetched separately for source health, then merged
into one logical Indeks Retail catalogue. The two storefronts can therefore
never produce duplicate Discord product alerts. Physical feeds remain diagnostic;
the deduplicated logical source is the only live Tier B/backup-retail source.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from alert_policy import backup_retail_signal_allowed


STATE_FILE = Path("indeks_retail_shadow_state.json")
STATE_VERSION = 3
MAX_PAGES = 5
PAGE_SIZE = 250
TIMEOUT_SECONDS = 20
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

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

LOGICAL_SOURCE_KEY = "indeks_retail"
LOGICAL_SOURCE_LABEL = "INDEKS RETAIL (Bog & idé / LegeKæden)"
PREORDER_MARKERS = ("forudbestilling", "preorder", "pre-order")


def _now() -> str:
    return datetime.now(ZoneInfo("UTC")).isoformat()


def _empty_state() -> dict:
    return {
        "version": STATE_VERSION,
        "mode": "mixed",
        "sources": {},
        "logical_sources": {},
    }


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return _empty_state()
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_state()
    if not isinstance(value, dict):
        return _empty_state()
    value.setdefault("sources", {})
    value.setdefault("logical_sources", {})
    return value


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

    available_variants = [
        variant
        for variant in variants
        if isinstance(variant, dict) and variant.get("available") is True
    ]
    priced_available = [
        (_price(variant.get("price")), variant) for variant in available_variants
    ]
    priced_available = [
        (price, variant) for price, variant in priced_available if price is not None
    ]
    priced_all = [
        (_price(variant.get("price")), variant)
        for variant in variants
        if isinstance(variant, dict)
    ]
    priced_all = [
        (price, variant) for price, variant in priced_all if price is not None
    ]

    chosen_price, chosen_variant = min(
        priced_available or priced_all,
        key=lambda item: item[0],
        default=(None, {}),
    )

    skus = sorted(
        {
            str(variant.get("sku") or "").strip()
            for variant in variants
            if isinstance(variant, dict)
        }
        - {""}
    )
    barcodes = sorted(
        {
            str(variant.get("barcode") or "").strip()
            for variant in variants
            if isinstance(variant, dict)
        }
        - {""}
    )

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
        "User-Agent": (
            "Mozilla/5.0 (compatible; PokemonRestockBot/1.0; "
            "+https://github.com/Gwar-Creator/pokemon-restock-bot)"
        ),
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


def _product_markers(handle: str, product: dict) -> list[str]:
    markers = []
    for sku in product.get("skus") or []:
        if sku:
            markers.append(f"sku:{sku}")
    for barcode in product.get("barcodes") or []:
        if barcode:
            markers.append(f"barcode:{barcode}")
    if handle:
        markers.append(f"handle:{handle}")
    return markers


def _new_logical_product(source_key: str, handle: str, product: dict) -> dict:
    return {
        "name": product.get("name"),
        "game": "POKÉMON",
        "price": product.get("price"),
        "in_stock": bool(product.get("in_stock")),
        "preorder": bool(product.get("preorder")),
        "url": product.get("url"),
        "skus": sorted(set(product.get("skus") or [])),
        "barcodes": sorted(set(product.get("barcodes") or [])),
        "handles": [handle] if handle else [],
        "retailers": {
            source_key: {
                "label": SOURCES[source_key]["label"],
                "price": product.get("price"),
                "in_stock": bool(product.get("in_stock")),
                "preorder": bool(product.get("preorder")),
                "url": product.get("url"),
            }
        },
    }


def _refresh_logical_summary(entry: dict) -> None:
    retailers = entry.get("retailers") or {}
    offers = [value for value in retailers.values() if isinstance(value, dict)]
    in_stock_offers = [offer for offer in offers if offer.get("in_stock") is True]
    priced_stock = [
        offer for offer in in_stock_offers if _price(offer.get("price")) is not None
    ]
    priced_all = [offer for offer in offers if _price(offer.get("price")) is not None]
    best = min(
        priced_stock or priced_all,
        key=lambda offer: float(offer["price"]),
        default=None,
    )

    entry["in_stock"] = bool(in_stock_offers)
    entry["preorder"] = any(offer.get("preorder") is True for offer in offers)
    entry["price"] = _price(best.get("price")) if best else None
    entry["url"] = best.get("url") if best else next(
        (offer.get("url") for offer in offers if offer.get("url")),
        None,
    )
    entry["source_count"] = len(retailers)


def _merge_logical_catalogue(sources: dict) -> dict:
    merged = {}
    marker_to_key = {}

    for source_key in SOURCES:
        products = ((sources.get(source_key) or {}).get("products") or {})
        for handle, product in products.items():
            markers = _product_markers(handle, product)
            existing_keys = [
                marker_to_key[marker] for marker in markers if marker in marker_to_key
            ]
            logical_key = existing_keys[0] if existing_keys else (
                markers[0] if markers else f"handle:{handle}"
            )

            entry = merged.get(logical_key)
            if entry is None:
                entry = _new_logical_product(source_key, handle, product)
                merged[logical_key] = entry
            else:
                entry.setdefault("retailers", {})[source_key] = {
                    "label": SOURCES[source_key]["label"],
                    "price": product.get("price"),
                    "in_stock": bool(product.get("in_stock")),
                    "preorder": bool(product.get("preorder")),
                    "url": product.get("url"),
                }
                entry["skus"] = sorted(
                    set(entry.get("skus") or []) | set(product.get("skus") or [])
                )
                entry["barcodes"] = sorted(
                    set(entry.get("barcodes") or []) | set(product.get("barcodes") or [])
                )
                if handle and handle not in entry.setdefault("handles", []):
                    entry["handles"].append(handle)
                    entry["handles"].sort()

            for marker in markers:
                marker_to_key.setdefault(marker, logical_key)
            _refresh_logical_summary(entry)

    return merged


def _event_for_product(old_product, new_product):
    if old_product is None:
        if new_product.get("preorder") is True:
            return "PREORDER"
        if new_product.get("in_stock") is True:
            return "NEW"
        return None
    if old_product.get("preorder") is not True and new_product.get("preorder") is True:
        return "PREORDER"
    if old_product.get("in_stock") is not True and new_product.get("in_stock") is True:
        return "RESTOCK"
    return None


def _format_price(value):
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    if price.is_integer():
        return f"{int(price):,}".replace(",", ".") + " kr."
    return f"{price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " kr."


def _discord_message(product, event):
    headline = {
        "NEW": "🆕 NYT",
        "PREORDER": "📅 FORUDBESTILLING",
        "RESTOCK": "🚨 RESTOCK",
    }.get(str(event or "").upper(), "🚨 RESTOCK")
    lines = [
        f"**{headline} — {LOGICAL_SOURCE_LABEL}**",
        f"**{product.get('name') or 'Ukendt produkt'}**",
    ]
    price = _format_price(product.get("price"))
    if price:
        lines.append(f"Pris: {price}")
    url = str(product.get("url") or "").strip()
    if url:
        lines.append(f"<{url}>")
    return "\n".join(lines)


def _post_discord(message):
    if not WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL mangler til Indeks Retail")
    response = requests.post(WEBHOOK_URL, json={"content": message}, timeout=15)
    response.raise_for_status()


def _noop_sender(_message):
    return None


def _emit_backup_alerts(old_products, products, *, sender=_post_discord):
    # A missing logical baseline must never replay the current catalogue.
    if not old_products:
        print("INDEKS LIVE: ingen tidligere logisk baseline; alerts undertrykt denne kørsel")
        return 0

    sent = 0
    for product_id, product in products.items():
        event = _event_for_product(old_products.get(product_id), product)
        if event is None:
            continue
        name = str(product.get("name") or "").strip()
        if not backup_retail_signal_allowed(name, event=event):
            continue
        sender(_discord_message(product, event))
        sent += 1
    return sent


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


def run_scan(fetcher=fetch_source, sender=None) -> int:
    # Deterministic tests inject a fetcher; keep them offline unless a sender is
    # explicitly provided. Production uses the shared Restock webhook.
    if sender is None:
        sender = _post_discord if fetcher is fetch_source else _noop_sender

    old_state = _load_state()
    old_sources = old_state.get("sources") or {}
    old_logical = (
        ((old_state.get("logical_sources") or {}).get(LOGICAL_SOURCE_KEY) or {})
        .get("products")
        or {}
    )
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
            print(
                f"INDEKS SOURCE {config['label']}: {len(products)} produkter | "
                f"på lager {stock} | health=ok"
            )
        except Exception as error:
            health = _failure_health(old_health, error, now)
            changed = True
            print(
                f"INDEKS SOURCE {config['label']} FEJL: {error} | "
                "gammel baseline bevaret"
            )

        new_sources[source_key] = {
            "label": config["label"],
            "mode": "shadow",
            "health": health,
            "products": products,
        }

    comparison = _comparison(new_sources)
    changed = changed or comparison != (old_state.get("comparison") or {})

    merged_products = _merge_logical_catalogue(new_sources)
    sent_alerts = _emit_backup_alerts(old_logical, merged_products, sender=sender)
    logical_sources = {
        LOGICAL_SOURCE_KEY: {
            "label": LOGICAL_SOURCE_LABEL,
            "mode": "live",
            "products": merged_products,
        }
    }
    changed = changed or logical_sources != (old_state.get("logical_sources") or {})

    state = {
        "version": STATE_VERSION,
        "mode": "mixed",
        "updated_at": now if changed or not old_state.get("updated_at") else old_state.get("updated_at"),
        "sources": new_sources,
        "logical_sources": logical_sources,
        "comparison": comparison,
    }
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    logical_stock = sum(
        1 for product in merged_products.values() if product.get("in_stock") is True
    )
    print(
        "INDEKS overlap: "
        f"handles={comparison['shared_handles']} | "
        f"sku/barcode={comparison['shared_skus_or_barcodes']} | "
        f"stock-forskelle={len(comparison['stock_disagreements'])} | "
        f"prisforskelle={len(comparison['price_disagreements'])}"
    )
    print(
        f"INDEKS LOGICAL LIVE: {len(merged_products)} unikke produkter | "
        f"på lager {logical_stock} | Discord alerts={sent_alerts}"
    )
    return 0 if successful else 1


def main() -> int:
    return run_scan()


if __name__ == "__main__":
    raise SystemExit(main())
