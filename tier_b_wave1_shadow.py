#!/usr/bin/env python3
"""Run Tier B Wave 1 with seven live Restock sources and Flinamania in shadow.

The historical filename/state path is kept to preserve the qualified baseline and
avoid replaying existing inventory as new products during promotion.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from alert_policy import tier_b_signal_allowed
from tier_b_wave1_sources import WAVE1_SOURCES, fetch_wave1_source


STATE_FILE = Path("tier_b_wave1_shadow_state.json")
STATE_VERSION = 2
MAX_DROP_RATIO = 0.70
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

LIVE_SOURCES = (
    "cardcollective",
    "softgunshoppen",
    "pockomonsters",
    "orbitalkickz",
    "kofodtrading",
    "andishop",
    "cardstop",
)
SHADOW_SOURCES = ("flinamania",)

if set(LIVE_SOURCES) | set(SHADOW_SOURCES) != set(WAVE1_SOURCES):
    raise RuntimeError("Wave 1 live/shadow source-listen matcher ikke WAVE1_SOURCES")
if set(LIVE_SOURCES) & set(SHADOW_SOURCES):
    raise RuntimeError("En Wave 1-kilde kan ikke være både live og shadow")


def _now():
    return datetime.now(ZoneInfo("UTC")).isoformat()


def _source_mode(source_key):
    return "live" if source_key in LIVE_SOURCES else "shadow"


def _load_state():
    if not STATE_FILE.exists():
        return {"version": STATE_VERSION, "mode": "mixed", "sources": {}}
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": STATE_VERSION, "mode": "mixed", "sources": {}}
    if not isinstance(value, dict):
        return {"version": STATE_VERSION, "mode": "mixed", "sources": {}}
    value.setdefault("sources", {})
    return value


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


def _validate_snapshot(source_key, products, old_products):
    if not isinstance(products, dict):
        raise RuntimeError("kilden returnerede ikke et produkt-dictionary")

    config = WAVE1_SOURCES[source_key]
    new_count = len(products)
    old_count = len(old_products) if isinstance(old_products, dict) else 0
    minimum = int(config.get("minimum") or 1)

    if new_count < minimum:
        raise RuntimeError(f"mistænkeligt lavt produktantal: {new_count} < {minimum}")

    if old_count >= minimum and new_count < old_count * (1.0 - MAX_DROP_RATIO):
        raise RuntimeError(f"mistænkeligt produktfald: {old_count} -> {new_count}")


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
    event = str(event or "").upper()
    headline = {
        "NEW": "🆕 NYT",
        "PREORDER": "📅 FORUDBESTILLING",
        "RESTOCK": "🚨 RESTOCK",
    }.get(event, "🚨 RESTOCK")

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
    response = requests.post(
        WEBHOOK_URL,
        json={"content": message},
        timeout=15,
    )
    response.raise_for_status()


def _noop_sender(_message):
    return None


def _emit_live_alerts(source_key, label, old_products, products, *, sender=_post_discord):
    if source_key not in LIVE_SOURCES:
        return 0

    # Promotion is baseline-safe. A missing/corrupt prior snapshot must never
    # turn the complete current catalogue into a burst of NEW notifications.
    if not old_products:
        print(f"WAVE1 LIVE {label}: ingen tidligere baseline; alerts undertrykt denne kørsel")
        return 0

    sent = 0
    for product_id, product in products.items():
        old_product = old_products.get(product_id)
        event = _event_for_product(old_product, product)
        if event is None:
            continue

        name = str(product.get("name") or "").strip()
        if not tier_b_signal_allowed(name, event=event):
            continue

        sender(_discord_message(label, product, event))
        sent += 1

    return sent


def run_scan(fetcher=fetch_wave1_source, sender=None):
    # Injected fetchers are used by deterministic tests/fixtures. Keep those
    # offline unless a sender is explicitly injected as well.
    if sender is None:
        sender = _post_discord if fetcher is fetch_wave1_source else _noop_sender

    old_state = _load_state()
    old_sources = old_state.get("sources") or {}
    new_sources = {}
    failures = 0
    sent_alerts = 0

    for source_key, config in WAVE1_SOURCES.items():
        old_entry = old_sources.get(source_key) or {}
        old_products = old_entry.get("products") or {}
        old_health = old_entry.get("health") or {}
        now = _now()
        fetched_products = None
        mode = _source_mode(source_key)

        try:
            fetched_products = fetcher(source_key)
            _validate_snapshot(source_key, fetched_products, old_products)
            products = fetched_products

            if mode == "live":
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
                f"WAVE1 {mode.upper()} {config['label']}: {pokemon} Pokémon | "
                f"{lorcana} Lorcana | på lager {stock} | preorders {preorders} | health=ok"
            )
        except Exception as error:
            failures += 1
            observed = len(fetched_products) if isinstance(fetched_products, dict) else None
            products = old_products
            health = _health_failure(old_health, error, observed, now)
            print(
                f"WAVE1 {mode.upper()} {config['label']} FEJL: {error} | "
                f"failures={health['consecutive_failures']} | gammel state bevaret"
            )

        new_sources[source_key] = {
            "label": config["label"],
            "mode": mode,
            "stock_trust": "unverified" if source_key == "flinamania" else "trusted",
            "health": health,
            "products": products,
        }

    state = {
        "version": STATE_VERSION,
        "mode": "mixed",
        "updated_at": _now(),
        "sources": new_sources,
    }
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    healthy = len(WAVE1_SOURCES) - failures
    print(
        f"WAVE1: {healthy}/{len(WAVE1_SOURCES)} kilder ok | {failures} fejl | "
        f"live={len(LIVE_SOURCES)} | shadow={len(SHADOW_SOURCES)} | "
        f"Discord alerts={sent_alerts} | PriceWatch=off"
    )
    return failures


def main():
    # Individual source failures must not block the primary production scanner.
    # A failed live source preserves its previous snapshot so a later recovery
    # can still generate a genuine transition instead of silently losing it.
    run_scan()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
