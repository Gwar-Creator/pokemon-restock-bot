#!/usr/bin/env python3
"""Scan Tier B Wave 1 without Discord or Price Watch side effects."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tier_b_wave1_sources import WAVE1_SOURCES, fetch_wave1_source


STATE_FILE = Path("tier_b_wave1_shadow_state.json")
STATE_VERSION = 1
MAX_DROP_RATIO = 0.70


def _now():
    return datetime.now(ZoneInfo("UTC")).isoformat()


def _load_state():
    if not STATE_FILE.exists():
        return {"version": STATE_VERSION, "mode": "shadow", "sources": {}}
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": STATE_VERSION, "mode": "shadow", "sources": {}}
    if not isinstance(value, dict):
        return {"version": STATE_VERSION, "mode": "shadow", "sources": {}}
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


def run_scan(fetcher=fetch_wave1_source):
    old_state = _load_state()
    old_sources = old_state.get("sources") or {}
    new_sources = {}
    failures = 0

    for source_key, config in WAVE1_SOURCES.items():
        old_entry = old_sources.get(source_key) or {}
        old_products = old_entry.get("products") or {}
        old_health = old_entry.get("health") or {}
        now = _now()
        fetched_products = None

        try:
            fetched_products = fetcher(source_key)
            _validate_snapshot(source_key, fetched_products, old_products)
            products = fetched_products
            health = _health_success(old_health, len(products), now)
            pokemon, lorcana, stock, preorders = _counts(products)
            print(
                f"WAVE1 SHADOW {config['label']}: {pokemon} Pokémon | "
                f"{lorcana} Lorcana | på lager {stock} | preorders {preorders} | health=ok"
            )
        except Exception as error:
            failures += 1
            observed = len(fetched_products) if isinstance(fetched_products, dict) else None
            products = old_products
            health = _health_failure(old_health, error, observed, now)
            print(
                f"WAVE1 SHADOW {config['label']} FEJL: {error} | "
                f"failures={health['consecutive_failures']} | gammel state bevaret"
            )

        new_sources[source_key] = {
            "label": config["label"],
            "mode": "shadow",
            "health": health,
            "products": products,
        }

    state = {
        "version": STATE_VERSION,
        "mode": "shadow",
        "updated_at": _now(),
        "sources": new_sources,
    }
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    healthy = len(WAVE1_SOURCES) - failures
    print(
        f"WAVE1 SHADOW: {healthy}/{len(WAVE1_SOURCES)} kilder ok | "
        f"{failures} fejl | Discord=off | PriceWatch=off"
    )
    return failures


def main():
    # Individual source failures are expected during shadow qualification and
    # must not block the production restock scanner or its state commit.
    run_scan()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
