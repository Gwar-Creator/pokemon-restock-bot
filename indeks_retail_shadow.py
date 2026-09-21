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
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from alert_policy import backup_retail_signal_allowed


STATE_FILE = Path("indeks_retail_shadow_state.json")
STATE_VERSION = 4
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
LOCAL_SOURCE_KEY = "legekaeden_vejen"
LOCAL_SOURCE_LABEL = "LEGEKÆDEN VEJEN"
LEGEKAEDEN_VEJEN_STORE_ID = "13280"
LEGEKAEDEN_VEJEN_LOCATION_ID = "gid://shopify/Location/89871876349"
STOREFRONT_API_VERSION = "2025-07"
STOREFRONT_SEARCH_TERMS = ("Pokemon", "Pokémon")
STOREFRONT_MAX_PAGES = 3
STOREFRONT_PAGE_SIZE = 100
STOREFRONT_BOOTSTRAP_URL = (
    "https://www.legekaeden.dk/products/bogbind-selvklaebende-50cmx3m-531054"
)
PREORDER_MARKERS = ("forudbestilling", "preorder", "pre-order")


def _now() -> str:
    return datetime.now(ZoneInfo("UTC")).isoformat()


def _empty_state() -> dict:
    return {
        "version": STATE_VERSION,
        "mode": "mixed",
        "sources": {},
        "logical_sources": {},
        "local_sources": {},
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
    value.setdefault("local_sources", {})
    return value


def _price(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _extract_storefront_credentials(document: str) -> tuple[str, str] | None:
    """Read the public Storefront API credentials used by pickup availability."""
    text = str(document or "")
    domain_match = re.search(r'data-shop-domain="([^"]+)"', text, re.IGNORECASE)
    token_match = re.search(
        r'data-storefront-token="([^"]+)"',
        text,
        re.IGNORECASE,
    )
    if not domain_match or not token_match:
        return None
    return domain_match.group(1).strip(), token_match.group(1).strip()


def _storefront_credentials(session, bootstrap_products=None) -> tuple[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; PokemonRestockBot/1.0; "
            "+https://github.com/Gwar-Creator/pokemon-restock-bot)"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
    }
    urls = []
    for product in (bootstrap_products or {}).values():
        url = str((product or {}).get("url") or "").strip()
        if url and url not in urls:
            urls.append(url)
        if len(urls) >= 5:
            break
    if STOREFRONT_BOOTSTRAP_URL not in urls:
        urls.append(STOREFRONT_BOOTSTRAP_URL)

    last_error = None
    for url in urls:
        try:
            response = session.get(url, headers=headers, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
            credentials = _extract_storefront_credentials(response.text)
            if credentials:
                return credentials
        except Exception as error:
            last_error = error

    suffix = f": {last_error}" if last_error else ""
    raise RuntimeError(f"kunne ikke finde LegeKædens Storefront API credentials{suffix}")


def _location_store_id(location: dict) -> str:
    for metafield in (location or {}).get("metafields") or []:
        if not isinstance(metafield, dict):
            continue
        if str(metafield.get("key") or "").strip() == "store_id":
            return str(metafield.get("value") or "").strip()
    return ""


def _is_vejen_location(location: dict) -> bool:
    location = location or {}
    if str(location.get("id") or "").strip() == LEGEKAEDEN_VEJEN_LOCATION_ID:
        return True
    if _location_store_id(location) == LEGEKAEDEN_VEJEN_STORE_ID:
        return True
    address = location.get("address") or {}
    name = str(location.get("name") or "").lower()
    city = str(address.get("city") or "").lower()
    return "legekæden vejen" in name or "legekaeden vejen" in name or city == "vejen"


def _storefront_variant_price(variant: dict):
    value = (variant or {}).get("price")
    if isinstance(value, dict):
        value = value.get("amount")
    return _price(value)


def _normalise_local_storefront_product(raw: dict) -> tuple[str, dict] | None:
    title = str((raw or {}).get("title") or "").strip()
    handle = str((raw or {}).get("handle") or "").strip()
    if not title or not handle:
        return None

    variants = ((raw.get("variants") or {}).get("nodes") or [])
    if not isinstance(variants, list):
        variants = []

    quantity = 0
    saw_vejen_location = False
    prices = []
    skus = set()
    barcodes = set()
    variant_ids = []

    for variant in variants:
        if not isinstance(variant, dict):
            continue
        variant_id = str(variant.get("id") or "").strip()
        if variant_id:
            variant_ids.append(variant_id)
        sku = str(variant.get("sku") or "").strip()
        barcode = str(variant.get("barcode") or "").strip()
        if sku:
            skus.add(sku)
        if barcode:
            barcodes.add(barcode)
        price = _storefront_variant_price(variant)
        if price is not None:
            prices.append(price)

        availability = ((variant.get("storeAvailability") or {}).get("nodes") or [])
        for stock in availability:
            if not isinstance(stock, dict):
                continue
            location = stock.get("location") or {}
            if not _is_vejen_location(location):
                continue
            saw_vejen_location = True
            try:
                local_quantity = int(stock.get("quantityAvailable") or 0)
            except (TypeError, ValueError):
                local_quantity = 0
            quantity += max(0, local_quantity)

    product = {
        "name": title,
        "handle": handle,
        "shopify_product_id": str(raw.get("id") or ""),
        "game": "POKÉMON",
        "price": min(prices) if prices else None,
        # Shopify available can be true when central stock can be ordered to
        # the store. Physical Vejen stock is quantityAvailable > 0.
        "in_stock": quantity > 0,
        "local_quantity": quantity,
        "local_store": LOCAL_SOURCE_LABEL,
        "local_store_id": LEGEKAEDEN_VEJEN_STORE_ID,
        "local_location_id": LEGEKAEDEN_VEJEN_LOCATION_ID,
        "local_location_seen": saw_vejen_location,
        "url": f"{SOURCES['legekaeden']['base']}/products/{handle}",
        "skus": sorted(skus),
        "barcodes": sorted(barcodes),
        "variant_ids": sorted(set(variant_ids)),
        "updated_at": raw.get("updatedAt"),
    }
    return handle, product


STOREFRONT_PRODUCTS_QUERY = """
query SearchProducts($query: String!, $after: String, $first: Int!) {
  products(first: $first, after: $after, query: $query, sortKey: UPDATED_AT, reverse: true) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      title
      handle
      updatedAt
      variants(first: 20) {
        nodes {
          id
          title
          sku
          barcode
          availableForSale
          price { amount currencyCode }
          storeAvailability(first: 250) {
            nodes {
              available
              quantityAvailable
              pickUpTime
              location {
                id
                name
                address { address1 city zip country }
                metafields(identifiers: [
                  { namespace: "store", key: "page_url" },
                  { namespace: "store", key: "store_id" }
                ]) { key value }
              }
            }
          }
        }
      }
    }
  }
}
"""


def fetch_legekaeden_vejen_stock(bootstrap_products=None, session=None) -> dict:
    """Fetch physical LegeKæden Vejen inventory exposed by the public storefront.

    This is independent of online availability. Only products published to
    LegeKæden's Storefront API can be discovered; truly store-only unpublished
    products remain invisible until Indeks publishes them to the storefront.
    """
    session = session or requests.Session()
    shop_domain, token = _storefront_credentials(session, bootstrap_products)
    endpoint = f"https://{shop_domain}/api/{STOREFRONT_API_VERSION}/graphql.json"
    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Storefront-Access-Token": token,
        "User-Agent": "PokemonRestockBot/1.0",
    }

    raw_products = {}
    for search_term in STOREFRONT_SEARCH_TERMS:
        after = None
        for _page in range(STOREFRONT_MAX_PAGES):
            response = session.post(
                endpoint,
                headers=headers,
                json={
                    "query": STOREFRONT_PRODUCTS_QUERY,
                    "variables": {
                        "query": search_term,
                        "after": after,
                        "first": STOREFRONT_PAGE_SIZE,
                    },
                },
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("errors"):
                messages = "; ".join(
                    str(error.get("message") or error)
                    for error in payload.get("errors") or []
                )
                raise RuntimeError(f"Storefront API fejl: {messages}")

            data = ((payload.get("data") or {}).get("products") or {})
            nodes = data.get("nodes") or []
            if not isinstance(nodes, list):
                raise RuntimeError("Storefront API mangler products.nodes")

            for raw in nodes:
                if not isinstance(raw, dict):
                    continue
                key = str(raw.get("id") or raw.get("handle") or "").strip()
                if key:
                    raw_products[key] = raw

            page_info = data.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            after = page_info.get("endCursor")
            if not after:
                break

    products = {}
    for raw in raw_products.values():
        normalised = _normalise_local_storefront_product(raw)
        if normalised is None:
            continue
        handle, product = normalised
        products[handle] = product

    if not products:
        raise RuntimeError("LegeKæden Storefront API gav 0 Pokémon-produkter")
    return products


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


def _local_event_for_product(old_product, new_product):
    if old_product is None:
        return "NEW" if (new_product or {}).get("in_stock") is True else None
    if old_product.get("in_stock") is not True and new_product.get("in_stock") is True:
        return "RESTOCK"
    return None


def _local_discord_message(product, event):
    headline = "🆕 LOKALT NYT" if str(event or "").upper() == "NEW" else "🚨 LOKALT RESTOCK"
    lines = [
        f"**{headline} — {LOCAL_SOURCE_LABEL}**",
        f"**{product.get('name') or 'Ukendt produkt'}**",
        f"🏪 Vejen: **{int(product.get('local_quantity') or 0)} stk.**",
    ]
    price = _format_price(product.get("price"))
    if price:
        lines.append(f"Pris: {price}")
    url = str(product.get("url") or "").strip()
    if url:
        lines.append(f"<{url}>")
    return "\n".join(lines)


def _emit_local_alerts(old_products, products, *, sender=None):
    # First deployment establishes a silent local baseline to avoid replaying
    # every currently stocked item as NEW.
    if sender is None:
        sender = _post_discord
    if not old_products:
        print("INDEKS LOCAL VEJEN: ingen tidligere baseline; alerts undertrykt denne kørsel")
        return 0

    sent = 0
    for product_id, product in products.items():
        event = _local_event_for_product(old_products.get(product_id), product)
        if event is None:
            continue
        name = str(product.get("name") or "").strip()
        if not backup_retail_signal_allowed(name, event=event):
            continue
        sender(_local_discord_message(product, event))
        sent += 1
    return sent


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


def run_scan(fetcher=fetch_source, sender=None, local_fetcher=None) -> int:
    # Deterministic tests inject a fetcher; keep them offline unless a sender is
    # explicitly provided. Production uses the shared Restock webhook.
    if sender is None:
        sender = _post_discord if fetcher is fetch_source else _noop_sender
    if local_fetcher is None and fetcher is fetch_source:
        local_fetcher = fetch_legekaeden_vejen_stock

    old_state = _load_state()
    old_sources = old_state.get("sources") or {}
    old_logical = (
        ((old_state.get("logical_sources") or {}).get(LOGICAL_SOURCE_KEY) or {})
        .get("products")
        or {}
    )
    old_local_sources = old_state.get("local_sources") or {}
    old_local_entry = old_local_sources.get(LOCAL_SOURCE_KEY) or {}
    old_local_products = old_local_entry.get("products") or {}
    old_local_health = old_local_entry.get("health") or {}
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

    local_sources = dict(old_local_sources)
    local_alerts = 0
    if local_fetcher is not None:
        local_products = old_local_products
        local_health = old_local_health
        try:
            legekaeden_products = (
                (new_sources.get("legekaeden") or {}).get("products") or {}
            )
            local_products = local_fetcher(legekaeden_products)
            local_changed = local_products != old_local_products
            local_health = _success_health(
                old_local_health,
                len(local_products),
                now,
                local_changed,
            )
            local_alerts = _emit_local_alerts(
                old_local_products,
                local_products,
                sender=sender,
            )
            changed = changed or local_changed or local_health != old_local_health
            local_in_stock = sum(
                1
                for product in local_products.values()
                if product.get("in_stock") is True
            )
            print(
                f"INDEKS LOCAL {LOCAL_SOURCE_LABEL}: {len(local_products)} Pokémon | "
                f"fysisk på lager {local_in_stock} | alerts={local_alerts} | health=ok"
            )
        except Exception as error:
            local_products = old_local_products
            local_health = _failure_health(old_local_health, error, now)
            changed = True
            print(
                f"INDEKS LOCAL {LOCAL_SOURCE_LABEL} FEJL: {error} | "
                "gammel lokal baseline bevaret"
            )

        local_sources[LOCAL_SOURCE_KEY] = {
            "label": LOCAL_SOURCE_LABEL,
            "mode": "live",
            "health": local_health,
            "products": local_products,
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
        "local_sources": local_sources,
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
        f"på lager {logical_stock} | Discord alerts={sent_alerts} | "
        f"lokale Vejen-alerts={local_alerts}"
    )
    return 0 if successful else 1


def main() -> int:
    return run_scan()


if __name__ == "__main__":
    raise SystemExit(main())
