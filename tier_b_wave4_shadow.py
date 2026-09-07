#!/usr/bin/env python3
"""Observe the legacy Wave 4 retailers as a dedicated Tier B shadow lane.

Wave 4 is already fetched by the main scanner. This shadow harness snapshots the
fresh main-scan output after each run, validates minimum product counts, and
builds an isolated baseline without sending Discord alerts or touching Price
Watch. It is deliberately read-only with respect to retailer traffic so we can
qualify the five sources before extracting/promoting them to their own live lane.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


MAIN_STATE_FILE = Path("restock_state_v2.json")
STATE_FILE = Path("tier_b_wave4_shadow_state.json")
STATE_VERSION = 1
MAX_DROP_RATIO = 0.70

WAVE4_SOURCES = {
    "vaulted": {"label": "VAULTED", "minimum": 15},
    "pokedexet": {"label": "POKEDEXET", "minimum": 10},
    "pokemonportalen": {"label": "POKEMONPORTALEN", "minimum": 10},
    "tcgbruus": {"label": "TCGBRUUS", "minimum": 5},
    "pokemonplaza": {"label": "POKEMON PLAZA", "minimum": 5},
}


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
    return _load_json(
        STATE_FILE,
        {"version": STATE_VERSION, "mode": "shadow", "sources": {}},
    )


def _main_products(main_state, source_key):
    products = main_state.get(source_key)
    if not isinstance(products, dict):
        raise RuntimeError("kilden mangler i restock_state_v2.json")
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


def run_scan(main_state=None):
    if main_state is None:
        main_state = _load_json(MAIN_STATE_FILE, {})
    if not main_state:
        raise RuntimeError("restock_state_v2.json mangler eller er ugyldig")

    old_state = _load_state()
    old_sources = old_state.get("sources") or {}
    new_sources = {}
    failures = 0

    for source_key, config in WAVE4_SOURCES.items():
        old_entry = old_sources.get(source_key) or {}
        old_products = old_entry.get("products") or {}
        old_health = old_entry.get("health") or {}
        now = _now()

        try:
            products = _main_products(main_state, source_key)
            _validate_snapshot(source_key, products, old_products)
            health = {
                "status": "ok",
                "last_attempt": now,
                "last_success": now,
                "consecutive_failures": 0,
                "last_error": "",
                "observed_count": len(products),
            }
            pokemon, lorcana, stock, preorders = _counts(products)
            print(
                f"WAVE4 SHADOW {config['label']}: {pokemon} Pokémon | {lorcana} Lorcana | "
                f"på lager {stock} | preorders {preorders} | health=ok"
            )
        except Exception as error:
            failures += 1
            products = old_products
            health = {
                "status": "failed",
                "last_attempt": now,
                "last_success": old_health.get("last_success"),
                "consecutive_failures": int(old_health.get("consecutive_failures") or 0) + 1,
                "last_error": str(error)[:500],
                "observed_count": None,
            }
            print(
                f"WAVE4 SHADOW {config['label']} FEJL: {error} | "
                f"failures={health['consecutive_failures']} | gammel baseline bevaret"
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
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"WAVE4 SHADOW: {len(WAVE4_SOURCES) - failures}/{len(WAVE4_SOURCES)} kilder ok | "
        f"{failures} fejl | Discord=off | PriceWatch=off"
    )
    return failures


def main():
    # Shadow failures are diagnostic and must not block the production scanner.
    run_scan()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
