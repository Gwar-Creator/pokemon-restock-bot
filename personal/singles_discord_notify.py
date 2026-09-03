#!/usr/bin/env python3
"""V56.2 delta-only Discord alerts for the personal singles radar.

This module deliberately uses the existing V55/V56 radar as discovery only. It
never presents aggregate Cardmarket prices as concrete offers and never emits BUY.
Discord is notified only when a personal REVIEW candidate is new or materially
better, or when a fully verified V56 listing appears.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from personal import singles_collection_runner as cr
from personal import singles_v55 as v55
from personal import singles_v56 as v56

DEFAULT_ALERT_STATE = Path("personal/personal_singles_discord_state.json")
DEFAULT_LIMIT = 5
PRICE_DROP_PCT = 12.0
PRICE_DROP_DKK = 3.0
SCORE_GAIN = 5.0


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def previous_cards(alert_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cards = alert_state.get("cards", {}) if isinstance(alert_state, dict) else {}
    if not isinstance(cards, dict):
        return {}
    return {str(key): value for key, value in cards.items() if isinstance(value, dict)}


def alert_reason(row: dict[str, Any], previous: dict[str, Any] | None) -> str | None:
    if row.get("v55_signal") != "REVIEW":
        return None

    if previous is None:
        return "NEW_REVIEW"

    previous_signal = str(previous.get("v55_signal") or "")
    if previous_signal != "REVIEW":
        return "PROMOTED_REVIEW"

    listing_signal = str(row.get("listing_signal") or "RADAR_ONLY")
    previous_listing = str(previous.get("listing_signal") or "RADAR_ONLY")
    if listing_signal == "LISTING_REVIEW" and previous_listing != "LISTING_REVIEW":
        return "EXACT_LISTING"

    current_ref = number(row.get("reference_dkk"))
    previous_ref = number(previous.get("reference_dkk"))
    if current_ref is not None and previous_ref is not None and previous_ref > 0:
        drop_dkk = previous_ref - current_ref
        drop_pct = drop_dkk / previous_ref * 100.0
        if drop_dkk >= PRICE_DROP_DKK and drop_pct >= PRICE_DROP_PCT:
            return "PRICE_IMPROVED"

    current_score = number(row.get("score"))
    previous_score = number(previous.get("score"))
    if current_score is not None and previous_score is not None and current_score - previous_score >= SCORE_GAIN:
        return "SCORE_IMPROVED"

    return None


def plan_alerts(
    rows: list[dict[str, Any]],
    alert_state: dict[str, Any],
    limit: int = DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    previous = previous_cards(alert_state)
    first_run = not previous
    planned: list[dict[str, Any]] = []

    for row in rows:
        product_id = str(row.get("id") or "")
        reason = alert_reason(row, previous.get(product_id))
        if reason:
            planned.append({**row, "alert_reason": reason})

    # First deployment establishes a baseline instead of dumping every current
    # REVIEW card into Discord. Only the strongest few are surfaced once.
    if first_run:
        planned = [row for row in planned if row["alert_reason"] == "NEW_REVIEW"]

    return planned[: max(0, limit)]


def state_snapshot(rows: list[dict[str, Any]], stamp: str) -> dict[str, Any]:
    cards: dict[str, dict[str, Any]] = {}
    for row in rows:
        product_id = str(row.get("id") or "")
        if not product_id:
            continue
        cards[product_id] = {
            "v55_signal": row.get("v55_signal"),
            "listing_signal": row.get("listing_signal"),
            "reference_dkk": number(row.get("reference_dkk")),
            "score": number(row.get("score")),
            "trend_vs_avg30_pct": number(row.get("trend_vs_avg30_pct")),
            "updated_at": stamp,
        }
    return {"version": 1, "updated_at": stamp, "cards": cards}


def metadata_display(row: dict[str, Any], rarity_metadata: dict[str, dict[str, Any]]) -> tuple[str, str]:
    meta = rarity_metadata.get(str(row.get("id") or ""), {})
    if not isinstance(meta, dict):
        meta = {}
    name = str(meta.get("canonical_name") or row.get("name") or "Ukendt kort")
    number_text = str(meta.get("canonical_number") or "").strip()
    return name, number_text


def cardmarket_search_text(row: dict[str, Any], rarity_metadata: dict[str, dict[str, Any]]) -> str:
    """Return a copy/paste Cardmarket query for the exact intended print."""
    name, card_number = metadata_display(row, rarity_metadata)
    set_name = str(row.get("set") or "").strip()
    parts = [name]
    if card_number:
        parts.append(card_number)
    if set_name:
        parts.append(set_name)
    return " ".join(" ".join(parts).split())


def money(value: Any) -> str:
    parsed = number(value)
    return "–" if parsed is None else f"{parsed:.0f} kr."


def pct(value: Any) -> str:
    parsed = number(value)
    return "–" if parsed is None else f"{parsed:+.1f}%"


def reason_text(reason: str) -> str:
    return {
        "NEW_REVIEW": "Ny REVIEW-kandidat",
        "PROMOTED_REVIEW": "Promoted til REVIEW",
        "EXACT_LISTING": "Konkret V56-listing er fuldt verificeret",
        "PRICE_IMPROVED": "Markant bedre aggregate prisreference",
        "SCORE_IMPROVED": "Radar-score er forbedret markant",
    }.get(reason, reason)


def embed_for(row: dict[str, Any], rarity_metadata: dict[str, dict[str, Any]]) -> dict[str, Any]:
    name, card_number = metadata_display(row, rarity_metadata)
    number_suffix = f" #{card_number}" if card_number else ""
    exact_listing = row.get("listing_signal") == "LISTING_REVIEW"
    manual_status = "LISTING_REVIEW" if exact_listing else "MANUAL LISTING CHECK"
    description = (
        f"**{row.get('set', 'Ukendt sæt')}** · {row.get('canonical_rarity', 'UNVERIFIED')}\n"
        f"Cardmarket product ID: `{row.get('id', '')}`"
    )
    fields = [
        {"name": "Cardmarket-søgning", "value": f"`{cardmarket_search_text(row, rarity_metadata)}`", "inline": False},
        {"name": "Market ref (aggregate)", "value": money(row.get("reference_dkk")), "inline": True},
        {"name": "Vores budget", "value": money(row.get("purchase_budget_dkk")), "inline": True},
        {"name": "30d", "value": pct(row.get("trend_vs_avg30_pct")), "inline": True},
        {"name": "Score", "value": str(row.get("score", "–")), "inline": True},
        {"name": "Hvorfor nu", "value": reason_text(str(row.get("alert_reason") or "")), "inline": True},
        {"name": "Status", "value": manual_status, "inline": True},
    ]
    if exact_listing:
        fields.append({"name": "Verificeret total", "value": money(row.get("listing_total_dkk")), "inline": True})

    return {
        "title": f"🔎 SINGLE REVIEW · {name}{number_suffix}"[:256],
        "description": description[:4096],
        "color": 0xF1C40F if not exact_listing else 0x57F287,
        "fields": fields[:25],
        "footer": {
            "text": "V56.2 · Kopiér Cardmarket-søgningen · Tjek English · NM/MT · EU/EEA · DK-fragt · aldrig BUY"
        },
    }


def post_discord(webhook: str, alerts: list[dict[str, Any]], rarity_metadata: dict[str, dict[str, Any]]) -> None:
    for index in range(0, len(alerts), 10):
        payload = {
            "username": "MasterBot",
            "allowed_mentions": {"parse": []},
            "embeds": [embed_for(row, rarity_metadata) for row in alerts[index:index + 10]],
        }
        response = requests.post(webhook, json=payload, timeout=30)
        response.raise_for_status()


def evaluate_rows(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    state = cr.load_json(args.state)
    profile = cr.load_json(args.profile)
    collection = cr.load_json(args.collection)
    incoming = cr.load_json(args.incoming)
    rarity_metadata = v55.load_rarity_metadata(args.rarity_metadata)
    listings = v56.load_listing_snapshot(args.listings)
    shipping = v56.load_shipping_overrides(args.shipping)
    effective_profile, _ = cr.apply_collection_filters(profile, collection, incoming)
    rows = v56.evaluate_state(state, effective_profile, rarity_metadata, listings, shipping)
    return rows, rarity_metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=cr.DEFAULT_STATE)
    parser.add_argument("--profile", type=Path, default=cr.DEFAULT_PROFILE)
    parser.add_argument("--collection", type=Path, default=cr.DEFAULT_COLLECTION)
    parser.add_argument("--incoming", type=Path, default=cr.DEFAULT_INCOMING)
    parser.add_argument("--rarity-metadata", type=Path, default=v55.DEFAULT_RARITY_METADATA)
    parser.add_argument("--listings", type=Path, default=v56.DEFAULT_LISTINGS)
    parser.add_argument("--shipping", type=Path, default=v56.DEFAULT_SHIPPING)
    parser.add_argument("--alert-state", type=Path, default=DEFAULT_ALERT_STATE)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--require-webhook", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows, rarity_metadata = evaluate_rows(args)
    old_state = load_json(args.alert_state, {"version": 1, "cards": {}})
    alerts = plan_alerts(rows, old_state, args.limit)
    webhook = os.getenv("CARDMARKET_WEBHOOK_URL", "").strip()

    print(f"V56.2 DISCORD: {len(alerts)} delta alert(s) planned from {len(rows)} candidates")
    for row in alerts:
        name, number_text = metadata_display(row, rarity_metadata)
        print(f"- {row['alert_reason']}: {name} {number_text} | {row.get('set')} | {money(row.get('reference_dkk'))}")

    if args.dry_run:
        return 0
    if not webhook:
        if args.require_webhook:
            raise SystemExit("CARDMARKET_WEBHOOK_URL mangler; Discord alert state blev ikke ændret")
        print("CARDMARKET_WEBHOOK_URL mangler; ingen Discord-post eller state-write")
        return 0

    if alerts:
        post_discord(webhook, alerts, rarity_metadata)

    stamp = datetime.now(timezone.utc).isoformat()
    save_json(args.alert_state, state_snapshot(rows, stamp))
    print(f"V56.2 DISCORD: state saved to {args.alert_state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
