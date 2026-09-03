#!/usr/bin/env python3
"""V56.3 delta-only Discord alerts for the personal singles radar.

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
TCGDEX_SET_API = "https://api.tcgdex.net/v2/en/sets"

# Cardmarket does not always use the same set abbreviation as upstream TCG data.
# Known differences and high-frequency personal-radar sets are pinned here so the
# Discord copy text matches Cardmarket's own display syntax exactly.
CARDMARKET_SET_CODE_OVERRIDES = {
    "hgss1": "HS",
    "hgss2": "UL",
    "hgss3": "UD",
    "hgss4": "TM",
    "swsh7": "EVS",
    "swsh12": "SIT",
    "swsh12.5": "CRZ",
    "sv01": "SVI",
    "sv02": "PAL",
    "sv03": "OBF",
    "sv3pt5": "MEW",
    "sv04": "PAR",
    "sv4pt5": "PAF",
    "sv05": "TEF",
    "sv06": "TWM",
    "sv6pt5": "SFA",
    "sv07": "SCR",
    "sv08": "SSP",
    "sv8pt5": "PRE",
    "sv09": "JTG",
    "sv10": "DRI",
}
_SET_CODE_CACHE: dict[str, str] = {}


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


def metadata_for(row: dict[str, Any], rarity_metadata: dict[str, dict[str, Any]]) -> dict[str, Any]:
    meta = rarity_metadata.get(str(row.get("id") or ""), {})
    return meta if isinstance(meta, dict) else {}


def metadata_display(row: dict[str, Any], rarity_metadata: dict[str, dict[str, Any]]) -> tuple[str, str]:
    meta = metadata_for(row, rarity_metadata)
    name = str(meta.get("canonical_name") or row.get("name") or "Ukendt kort")
    number_text = str(meta.get("canonical_number") or "").strip()
    return name, number_text


def cardmarket_set_code(
    row: dict[str, Any],
    rarity_metadata: dict[str, dict[str, Any]],
) -> str:
    """Resolve Cardmarket's displayed set code without guessing from set name."""
    meta = metadata_for(row, rarity_metadata)
    explicit = str(meta.get("cardmarket_set_code") or "").strip().upper()
    if explicit:
        return explicit

    source_set_id = str(meta.get("source_set_id") or "").strip()
    if not source_set_id:
        return ""
    if source_set_id in CARDMARKET_SET_CODE_OVERRIDES:
        return CARDMARKET_SET_CODE_OVERRIDES[source_set_id]
    if source_set_id in _SET_CODE_CACHE:
        return _SET_CODE_CACHE[source_set_id]

    # For sets where Cardmarket follows the official Pokemon abbreviation, use
    # TCGdex's official code. Known Cardmarket exceptions are always overridden
    # above. Failure is safe: we show no fabricated set code.
    try:
        response = requests.get(f"{TCGDEX_SET_API}/{source_set_id}", timeout=10)
        response.raise_for_status()
        payload = response.json()
        abbreviations = payload.get("abbreviations") if isinstance(payload, dict) else None
        official = str(abbreviations.get("official") or "").strip().upper() if isinstance(abbreviations, dict) else ""
    except (requests.RequestException, ValueError):
        official = ""

    _SET_CODE_CACHE[source_set_id] = official
    return official


def cardmarket_search_text(row: dict[str, Any], rarity_metadata: dict[str, dict[str, Any]]) -> str:
    """Return Cardmarket's own single-card label syntax: Name (SET NUMBER)."""
    name, card_number = metadata_display(row, rarity_metadata)
    set_code = cardmarket_set_code(row, rarity_metadata)
    if set_code and card_number:
        return f"{name} ({set_code} {card_number})"
    if card_number:
        return f"{name} ({card_number})"
    return name


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
            "text": "V56.3 · Cardmarket-format: navn (setkode nummer) · Tjek English · NM/MT · EU/EEA · DK-fragt · aldrig BUY"
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

    print(f"V56.3 DISCORD: {len(alerts)} delta alert(s) planned from {len(rows)} candidates")
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
    print(f"V56.3 DISCORD: state saved to {args.alert_state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
