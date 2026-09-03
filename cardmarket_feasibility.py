#!/usr/bin/env python3
"""Shadow-only Cardmarket feasibility evaluator.

This tool never calls Cardmarket, never sends Discord messages, and never writes
production state. It samples the aggregate Cardmarket data already stored by the
bot and combines it with a small manual review file for fields the current price
feed cannot verify: language, condition, seller country and Denmark shipping.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_STATE = Path("cardmarket_chase_state.json")
DEFAULT_REVIEW = Path("cardmarket_feasibility_reviews.json")
DEFAULT_OUTPUT = Path("cardmarket_feasibility_report.md")
DEFAULT_CASES = 20
EU_EEA_COUNTRIES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE",
    "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT",
    "RO", "SK", "SI", "ES", "SE", "IS", "LI", "NO",
}
ACCEPTED_CONDITIONS = {"MT", "NM"}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def price_band(value: float) -> str:
    if value < 2:
        return "micro"
    if value < 10:
        return "budget"
    if value < 30:
        return "mid"
    return "premium"


def normalized_cards(state: dict[str, Any]) -> list[dict[str, Any]]:
    raw_cards = state.get("cards", {}) if isinstance(state, dict) else {}
    if not isinstance(raw_cards, dict):
        return []

    cards: list[dict[str, Any]] = []
    for key, raw in raw_cards.items():
        if not isinstance(raw, dict) or raw.get("game") != "POKÉMON":
            continue
        low = number(raw.get("low"))
        market = number(raw.get("market"))
        if low is None or market is None or low < 0 or market <= 0:
            continue
        card = dict(raw)
        card["state_key"] = str(key)
        card["id"] = str(card.get("id") or str(key).split("|")[-1])
        card["low"] = low
        card["market"] = market
        cards.append(card)
    return cards


def _stable_card_sort(card: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(card.get("set") or "").casefold(),
        str(card.get("name") or "").casefold(),
        str(card.get("id") or ""),
    )


def select_cases(cards: list[dict[str, Any]], limit: int = DEFAULT_CASES) -> list[dict[str, Any]]:
    """Choose a deterministic, price-diverse sample while spreading across sets."""
    if limit <= 0:
        return []

    buckets: dict[str, list[dict[str, Any]]] = {name: [] for name in ("micro", "budget", "mid", "premium")}
    for card in cards:
        buckets[price_band(card["low"])].append(card)
    for rows in buckets.values():
        rows.sort(key=_stable_card_sort)

    weights = {"micro": 0.15, "budget": 0.35, "mid": 0.30, "premium": 0.20}
    quotas = {name: int(math.floor(limit * weight)) for name, weight in weights.items()}
    while sum(quotas.values()) < limit:
        for name in ("budget", "mid", "premium", "micro"):
            if sum(quotas.values()) >= limit:
                break
            quotas[name] += 1

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    selected_sets: set[str] = set()

    for band in ("budget", "mid", "premium", "micro"):
        count = quotas[band]
        preferred = [row for row in buckets[band] if str(row.get("set")) not in selected_sets]
        fallback = [row for row in buckets[band] if row not in preferred]
        taken = 0
        for row in preferred + fallback:
            card_id = str(row.get("id"))
            if card_id in selected_ids:
                continue
            selected.append(row)
            selected_ids.add(card_id)
            selected_sets.add(str(row.get("set") or ""))
            taken += 1
            if taken >= count:
                break

    if len(selected) < limit:
        remaining = sorted(
            (card for card in cards if str(card.get("id")) not in selected_ids),
            key=lambda row: (abs((number(row.get("low")) or 0) - 10), *_stable_card_sort(row)),
        )
        selected.extend(remaining[: limit - len(selected)])

    return selected[:limit]


def normalize_review_map(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    reviews = raw.get("reviews", raw)
    if not isinstance(reviews, dict):
        return {}
    return {str(key): value for key, value in reviews.items() if isinstance(value, dict)}


def review_complete(review: dict[str, Any]) -> bool:
    required = (
        "product_match",
        "language",
        "condition",
        "seller_country",
        "ships_to_denmark",
        "listing_price_eur",
    )
    return all(field in review and review.get(field) not in (None, "") for field in required)


def evaluate_case(card: dict[str, Any], review: dict[str, Any] | None) -> dict[str, Any]:
    review = review or {}
    complete = review_complete(review)
    listing_price = number(review.get("listing_price_eur"))
    shipping = number(review.get("shipping_eur"))
    low = number(card.get("low"))

    gap_pct = None
    if listing_price is not None and low is not None and low > 0:
        gap_pct = (listing_price / low - 1.0) * 100.0

    country = str(review.get("seller_country") or "").strip().upper()
    language = str(review.get("language") or "").strip().upper()
    condition = str(review.get("condition") or "").strip().upper()
    product_match = review.get("product_match") is True
    ships = review.get("ships_to_denmark") is True
    usable = complete and product_match and language in {"EN", "ENGLISH"} and condition in ACCEPTED_CONDITIONS and country in EU_EEA_COUNTRIES and ships

    total = listing_price
    if listing_price is not None and shipping is not None:
        total = listing_price + shipping

    return {
        "id": str(card.get("id") or ""),
        "name": str(card.get("name") or "Ukendt kort"),
        "set": str(card.get("set") or "Ukendt sæt"),
        "variant": str(card.get("variant") or ""),
        "aggregate_low_eur": low,
        "trend_eur": number(card.get("trend")),
        "avg30_eur": number(card.get("avg30")),
        "price_band": price_band(low or 0),
        "reviewed": complete,
        "usable_listing": bool(usable),
        "listing_price_eur": listing_price,
        "shipping_eur": shipping,
        "total_price_eur": total,
        "low_gap_pct": gap_pct,
        "review": review,
    }


@dataclass(frozen=True)
class Verdict:
    level: str
    explanation: str


def decide(rows: list[dict[str, Any]]) -> Verdict:
    reviewed = [row for row in rows if row["reviewed"]]
    if len(reviewed) < min(15, len(rows)):
        return Verdict(
            "PENDING",
            f"Kun {len(reviewed)}/{len(rows)} cases er fuldt verificeret. Ingen purchase-grade konklusion endnu.",
        )

    usable = [row for row in reviewed if row["usable_listing"]]
    usable_rate = len(usable) / len(reviewed)
    gaps = [row["low_gap_pct"] for row in usable if row["low_gap_pct"] is not None]
    median_gap = statistics.median(gaps) if gaps else math.inf
    p90_gap = sorted(gaps)[max(0, math.ceil(len(gaps) * 0.9) - 1)] if gaps else math.inf

    if usable_rate >= 0.80 and median_gap <= 10 and p90_gap <= 25:
        return Verdict(
            "PURCHASE_READY",
            "Aggregate low er tæt nok på en verificeret EN/NM EU→DK listing til at kunne være purchase-grade signal med guardrails.",
        )
    return Verdict(
        "RADAR_ONLY",
        "Data er nyttige som markedsradar, men ikke stabile nok til automatisk købssignal uden manuel offer-verifikation.",
    )


def fmt(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "–"
    return f"{value:.2f}{suffix}"


def build_report(rows: list[dict[str, Any]]) -> str:
    verdict = decide(rows)
    reviewed = [row for row in rows if row["reviewed"]]
    usable = [row for row in reviewed if row["usable_listing"]]
    gaps = [row["low_gap_pct"] for row in usable if row["low_gap_pct"] is not None]
    median_gap = statistics.median(gaps) if gaps else None
    p90_gap = sorted(gaps)[max(0, math.ceil(len(gaps) * 0.9) - 1)] if gaps else None

    lines = [
        "# Cardmarket feasibility report",
        "",
        "> Shadow-only. Ingen Discord, ingen state-write, ingen Cardmarket scraping.",
        "",
        f"**Verdict: {verdict.level}** — {verdict.explanation}",
        "",
        "## Metrics",
        "",
        f"- Cases: {len(rows)}",
        f"- Fuldt verificeret: {len(reviewed)}/{len(rows)}",
        f"- Brugbar EN/NM EU→DK listing: {len(usable)}/{len(reviewed) if reviewed else 0}",
        f"- Median gap fra aggregate low: {fmt(median_gap, '%')}",
        f"- P90 gap fra aggregate low: {fmt(p90_gap, '%')}",
        "",
        "## Cases",
        "",
        "| ID | Kort | Sæt | API low | Trend | Review | Brugbar | Listing | Gap |",
        "|---|---|---|---:|---:|---|---|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {id} | {name} | {set} | €{low} | €{trend} | {reviewed} | {usable} | {listing} | {gap} |".format(
                id=row["id"],
                name=row["name"].replace("|", "/"),
                set=row["set"].replace("|", "/"),
                low=fmt(row["aggregate_low_eur"]),
                trend=fmt(row["trend_eur"]),
                reviewed="✅" if row["reviewed"] else "⏳",
                usable="✅" if row["usable_listing"] else "—",
                listing="€" + fmt(row["listing_price_eur"]) if row["listing_price_eur"] is not None else "–",
                gap=fmt(row["low_gap_pct"], "%"),
            )
        )

    lines.extend(
        [
            "",
            "## Purchase-grade krav",
            "",
            "En case tæller kun som brugbar, når exact product match, English, MT/NM, EU/EEA seller og shipping til Danmark alle er verificeret.",
            "Shipping holdes separat fra API-low, fordi aggregate price feed ikke inkluderer brugerens konkrete fragt.",
            "",
            "**PURCHASE_READY** kræver mindst 15 verificerede cases, ≥80% brugbare listings, median-gap ≤10% og P90-gap ≤25%.",
            "Ellers er konklusionen **RADAR_ONLY**. Manglende review giver **PENDING**.",
            "",
        ]
    )
    return "\n".join(lines)


def review_template(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "notes": "Udfyld kun fra den konkrete Cardmarket product-side. shipping_eur er valgfri; øvrige felter er nødvendige for fuld review.",
        "reviews": {
            row["id"]: {
                "product_match": None,
                "language": None,
                "condition": None,
                "seller_country": None,
                "ships_to_denmark": None,
                "listing_price_eur": None,
                "shipping_eur": None,
                "source_url": None,
                "checked_at": None,
            }
            for row in rows
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--reviews", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cases", type=int, default=DEFAULT_CASES)
    parser.add_argument("--write-review-template", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state = load_json(args.state, {})
    cards = normalized_cards(state)
    if not cards:
        raise SystemExit(f"Ingen brugbare Pokémon-kort fundet i {args.state}")

    sample = select_cases(cards, args.cases)
    reviews = normalize_review_map(load_json(args.reviews, {}))
    rows = [evaluate_case(card, reviews.get(str(card.get("id")))) for card in sample]
    args.output.write_text(build_report(rows), encoding="utf-8")

    if args.write_review_template and not args.reviews.exists():
        args.reviews.write_text(json.dumps(review_template(rows), ensure_ascii=False, indent=2), encoding="utf-8")

    verdict = decide(rows)
    print(f"CARDMARKET FEASIBILITY: {verdict.level} | {verdict.explanation}")
    print(f"Report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
