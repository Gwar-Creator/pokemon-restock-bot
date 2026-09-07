#!/usr/bin/env python3
"""Run Tier B Wave 4 as the live Restock owner.

The historical filename/state path is intentionally preserved so promotion reuses
the qualified shadow baseline and never replays current inventory as NEW alerts.
Wave 4 still reuses the freshly written main-scanner snapshots, so promotion adds
no duplicate retailer traffic. Price Watch remains off for this lane.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from alert_policy import tier_b_signal_allowed


MAIN_STATE_FILE = Path("restock_state_v2.json")
STATE_FILE = Path("tier_b_wave4_shadow_state.json")
STATE_VERSION = 2
MAX_DROP_RATIO = 0.70
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

WAVE4_SOURCES = {
    "vaulted": {"label": "VAULTED", "minimum": 15, "state_group": "shopify"},
    "pokedexet": {"label": "POKEDEXET", "minimum": 10, "state_group": "shopify"},
    "pokemonportalen": {"label": "POKEMONPORTALEN", "minimum": 10, "state_group": "woocommerce"},
    "tcgbruus": {"label": "TCGBRUUS", "minimum": 5, "state_group": "woocommerce"},
    "pokemonplaza": {"label": "POKEMON PLAZA", "minimum": 5, "state_group": "woocommerce"},
}
LIVE_SOURCES = tuple(WAVE4_SOURCES)


def _now():
    return datetime.now(ZoneInfo("UTC")).isoformat()


def _load_json(path, default):
    if not path.exists():
        return default
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return value if isinstance(value, dict) else default


def _load_state():
    state = _load_json(
        STATE_FILE,
        {"version": STATE_VERSION, "mode": "live", "sources": {}},
    )
    state.setdefault("sources", {})
    return state


def _main_products(main_state, source_key):
    config = WAVE4_SOURCES[source_key]
    group = config.get("state_group")
    if group:
        products = ((main_state.get(group) or {}).get(source_key))
    else:
        products = main_state.get(source_key)
    if not isinstance(products, dict):
        raise RuntimeError(
            f"kilden mangler i restock_state_v2.json under {group or 'top-level'}"
        )
    return products


def _validate_snapshot(source_key, products, old_products):
    config = WAVE4_SOURCES[source_key]
    new_count = len(products)
    old_count = len(old_products) if isinstance(old_products, dict) else 0
    minimum = int(config["minimum"])

    if new_count < minimum:
        raise RuntimeError(f"mistænkeligt lavt produktantal: {new_count} < {minimum}")
    if old_count >= minimum and new_count < old_count * (1.0 - MAX_DROP_RATIO):
        raise RuntimeError(f"mistænkeligt produktfald: {old_count} -> {new_count}")


def _product_in_stock(product):
    if product.get("in_stock") is True:
        return True
    if product.get("online_stock") is True:
        return True
    stock = str(product.get("stock") or "").strip().lower()
    return stock in {"på lager", "pa lager", "in stock", "available"}


def _counts(products):
    pokemon = sum(1 for product in products.values() if product.get("game") == "POKÉMON")
    lorcana = sum(1 for product in products.values() if product.get("game") == "LORCANA")
    stock = sum(1 for product in products.values() if _product_in_stock(product))
    preorders = sum(1 for product in products.values() if product.get("preorder") is True)
    return pokemon, lorcana, stock, preorders


def _event_for_product(source_key, old_product, new_product):
    old_stock = _product_in_stock(old_product or {})
    new_stock = _product_in_stock(new_product)
    new_preorder = new_product.get("preorder") is True
    old_preorder = (old_product or {}).get("preorder") is True

    # Pokemonportalen marks sold-out placeholders as preorder. Until the source
    # exposes a trustworthy buyable flag, PREORDER is fail-closed for this shop.
    preorder_allowed = source_key != "pokemonportalen"

    if old_product is None:
        if preorder_allowed and new_preorder:
            return "PREORDER"
        if new_stock:
            return "NEW"
        return None

    if preorder_allowed and not old_preorder and new_preorder:
        return "PREORDER"
    if not old_stock and new_stock:
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


def _discord_message(label, product, event):
    headline = {
        "NEW": "🆕 NYT",
        "PREORDER": "📅 FORUDBESTILLING",
        "RESTOCK": "🚨 RESTOCK",
    }.get(str(event or "").upper(), "🚨 RESTOCK")
    lines = [
        f"**{headline} — {label}**",
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
        raise RuntimeError("DISCORD_WEBHOOK_URL mangler til live Tier B-kilder")
    response = requests.post(WEBHOOK_URL, json={"content": message}, timeout=15)
    response.raise_for_status()


def _noop_sender(_message):
    return None


def _emit_live_alerts(source_key, label, old_products, products, *, sender=_post_discord):
    if source_key not in LIVE_SOURCES:
        return 0

    # Baseline-safe promotion: a missing/corrupt prior state must never turn the
    # whole catalogue into a burst of NEW alerts.
    if not old_products:
        print(f"WAVE4 LIVE {label}: ingen tidligere baseline; alerts undertrykt denne kørsel")
        return 0

    sent = 0
    for product_id, product in products.items():
        event = _event_for_product(source_key, old_products.get(product_id), product)
        if event is None:
            continue
        name = str(product.get("name") or "").strip()
        if not tier_b_signal_allowed(name, event=event):
            continue
        sender(_discord_message(label, product, event))
        sent += 1
    return sent


def _health_success(count, now):
    return {
        "status": "ok",
        "last_attempt": now,
        "last_success": now,
        "consecutive_failures": 0,
        "last_error": "",
        "observed_count": count,
    }


def _health_failure(old_health, error, observed_count, now):
    failures = int((old_health or {}).get("consecutive_failures") or 0) + 1
    return {
        "status": "failed",
        "last_attempt": now,
        "last_success": (old_health or {}).get("last_success"),
        "consecutive_failures": failures,
        "last_error": str(error)[:500],
        "observed_count": observed_count,
    }


def run_scan(main_state=None, sender=None):
    if main_state is None:
        main_state = _load_json(MAIN_STATE_FILE, {})
    if not main_state:
        raise RuntimeError("restock_state_v2.json mangler eller er ugyldig")
    if sender is None:
        sender = _post_discord

    old_state = _load_state()
    old_sources = old_state.get("sources") or {}
    new_sources = {}
    failures = 0
    sent_alerts = 0

    for source_key, config in WAVE4_SOURCES.items():
        old_entry = old_sources.get(source_key) or {}
        old_products = old_entry.get("products") or {}
        old_health = old_entry.get("health") or {}
        now = _now()
        products = old_products

        try:
            products = _main_products(main_state, source_key)
            _validate_snapshot(source_key, products, old_products)
            sent_alerts += _emit_live_alerts(
                source_key,
                config["label"],
                old_products,
                products,
                sender=sender,
            )
            health = _health_success(len(products), now)
            pokemon, lorcana, stock, preorders = _counts(products)
            print(
                f"WAVE4 LIVE {config['label']}: {pokemon} Pokémon | {lorcana} Lorcana | "
                f"på lager {stock} | preorders {preorders} | health=ok"
            )
        except Exception as error:
            failures += 1
            observed = len(products) if isinstance(products, dict) and products is not old_products else None
            products = old_products
            health = _health_failure(old_health, error, observed, now)
            print(
                f"WAVE4 LIVE {config['label']} FEJL: {error} | "
                f"failures={health['consecutive_failures']} | gammel baseline bevaret"
            )

        new_sources[source_key] = {
            "label": config["label"],
            "mode": "live",
            "stock_trust": "trusted",
            "health": health,
            "products": products,
        }

    state = {
        "version": STATE_VERSION,
        "mode": "live",
        "updated_at": _now(),
        "sources": new_sources,
    }
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"WAVE4: {len(WAVE4_SOURCES) - failures}/{len(WAVE4_SOURCES)} kilder ok | "
        f"{failures} fejl | live={len(LIVE_SOURCES)} | Discord alerts={sent_alerts} | PriceWatch=off"
    )
    return failures


def main():
    # Individual source failures preserve the old baseline and do not block the
    # primary scanner. A later recovery can still form a genuine transition.
    run_scan()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
