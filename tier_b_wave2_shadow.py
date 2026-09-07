#!/usr/bin/env python3
"""Run Tier B Wave 2 as live Restock sources.

The historical filename/state path is intentionally preserved so promotion reuses
the qualified shadow baseline and never replays existing inventory as NEW alerts.
Price Watch remains off for Wave 2.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from alert_policy import tier_b_signal_allowed
from tier_b_wave2_sources import WAVE2_SOURCES, fetch_wave2_source


STATE_FILE = Path("tier_b_wave2_shadow_state.json")
STATE_VERSION = 2
MAX_DROP_RATIO = 0.70
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
LIVE_SOURCES = tuple(WAVE2_SOURCES)


def _now():
    return datetime.now(ZoneInfo("UTC")).isoformat()


def _load_state():
    if not STATE_FILE.exists():
        return {"version": STATE_VERSION, "mode": "live", "sources": {}}
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": STATE_VERSION, "mode": "live", "sources": {}}
    if not isinstance(value, dict):
        return {"version": STATE_VERSION, "mode": "live", "sources": {}}
    value.setdefault("sources", {})
    return value


def _validate_snapshot(source_key, products, old_products):
    if not isinstance(products, dict):
        raise RuntimeError("kilden returnerede ikke et produkt-dictionary")

    config = WAVE2_SOURCES[source_key]
    new_count = len(products)
    old_count = len(old_products) if isinstance(old_products, dict) else 0
    minimum = int(config.get("minimum") or 1)

    if new_count < minimum:
        raise RuntimeError(f"mistænkeligt lavt produktantal: {new_count} < {minimum}")
    if old_count >= minimum and new_count < old_count * (1.0 - MAX_DROP_RATIO):
        raise RuntimeError(f"mistænkeligt produktfald: {old_count} -> {new_count}")


def _health_success(old_health, count, now):
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


def _counts(products):
    pokemon = sum(1 for product in products.values() if product.get("game") == "POKÉMON")
    lorcana = sum(1 for product in products.values() if product.get("game") == "LORCANA")
    stock = sum(1 for product in products.values() if product.get("in_stock") is True)
    preorders = sum(1 for product in products.values() if product.get("preorder") is True)
    return pokemon, lorcana, stock, preorders


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

    # Promotion is baseline-safe. Missing/corrupt prior state must never turn a
    # complete catalogue into a burst of NEW notifications.
    if not old_products:
        print(f"WAVE2 LIVE {label}: ingen tidligere baseline; alerts undertrykt denne kørsel")
        return 0

    sent = 0
    for product_id, product in products.items():
        event = _event_for_product(old_products.get(product_id), product)
        if event is None:
            continue
        name = str(product.get("name") or "").strip()
        if not tier_b_signal_allowed(name, event=event):
            continue
        sender(_discord_message(label, product, event))
        sent += 1
    return sent


def run_scan(fetcher=fetch_wave2_source, sender=None):
    # Deterministic tests inject a fetcher; keep those offline unless a sender
    # is explicitly supplied.
    if sender is None:
        sender = _post_discord if fetcher is fetch_wave2_source else _noop_sender

    old_state = _load_state()
    old_sources = old_state.get("sources") or {}
    new_sources = {}
    failures = 0
    sent_alerts = 0

    for source_key, config in WAVE2_SOURCES.items():
        old_entry = old_sources.get(source_key) or {}
        old_products = old_entry.get("products") or {}
        old_health = old_entry.get("health") or {}
        fetched_products = None
        now = _now()

        try:
            fetched_products = fetcher(source_key)
            _validate_snapshot(source_key, fetched_products, old_products)
            products = fetched_products
            sent_alerts += _emit_live_alerts(
                source_key,
                config["label"],
                old_products,
                products,
                sender=sender,
            )
            health = _health_success(old_health, len(products), now)
            pokemon, lorcana, stock, preorders = _counts(products)
            print(
                f"WAVE2 LIVE {config['label']}: {pokemon} Pokémon | {lorcana} Lorcana | "
                f"på lager {stock} | preorders {preorders} | health=ok"
            )
        except Exception as error:
            failures += 1
            observed = len(fetched_products) if isinstance(fetched_products, dict) else None
            products = old_products
            health = _health_failure(old_health, error, observed, now)
            print(
                f"WAVE2 LIVE {config['label']} FEJL: {error} | "
                f"failures={health['consecutive_failures']} | gammel state bevaret"
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
        f"WAVE2: {len(WAVE2_SOURCES) - failures}/{len(WAVE2_SOURCES)} kilder ok | "
        f"{failures} fejl | live={len(LIVE_SOURCES)} | Discord alerts={sent_alerts} | PriceWatch=off"
    )
    return failures


def main():
    # Individual Wave 2 failures preserve the old snapshot and must not block
    # the primary scanner. Recovery can therefore still create a real transition.
    run_scan()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
