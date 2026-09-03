#!/usr/bin/env python3
"""V50.1 personal singles radar.

Shadow-only decision layer over the existing aggregate Cardmarket state.
It performs no network requests, sends no Discord messages, and writes no
production state.

V50.1 deliberately stops treating aggregate Cardmarket trend/averages as a
purchase price. They are market-radar signals only. A card can therefore be
flagged for manual review because its market trend looks interesting, but the
engine never claims that the user's EN/NM/EU->DK purchase constraints are met.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import unicodedata
from pathlib import Path
from typing import Any

DEFAULT_STATE = Path("cardmarket_chase_state.json")
DEFAULT_PROFILE = Path("personal/singles_profile.json")
DEFAULT_OUTPUT = Path("personal_singles_opportunity_report.md")
DEFAULT_LIMIT = 10

NON_PHYSICAL_PATTERNS = (
    "code card",
    "online code",
    "online-code",
)


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


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def pct(current: Any, baseline: Any) -> float | None:
    current_value = number(current)
    baseline_value = number(baseline)
    if current_value is None or baseline_value is None or baseline_value <= 0:
        return None
    return (current_value / baseline_value - 1.0) * 100.0


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def subject_name(card_name: Any) -> str:
    """Return the card subject rather than attack text stored in square brackets."""
    return str(card_name or "").split("[", 1)[0].strip()


def contains_name(card_name: Any, wanted: Any) -> bool:
    haystack = f" {normalize_text(subject_name(card_name))} "
    needle = normalize_text(wanted)
    if not needle:
        return False
    return f" {needle} " in haystack


def is_non_physical_card(card: dict[str, Any]) -> bool:
    name = normalize_text(card.get("name"))
    return any(pattern in name for pattern in NON_PHYSICAL_PATTERNS)


def reference_price_eur(card: dict[str, Any]) -> float | None:
    """Market-radar reference only: trend first; averages are fallbacks, never low."""
    trend = number(card.get("trend"))
    if trend is not None and trend > 0:
        return trend
    averages = [number(card.get(key)) for key in ("avg7", "avg30")]
    averages = [value for value in averages if value is not None and value > 0]
    return statistics.median(averages) if averages else None


def data_confidence(card: dict[str, Any]) -> tuple[str, float | None]:
    values = [number(card.get(key)) for key in ("trend", "avg7", "avg30")]
    values = [value for value in values if value is not None and value > 0]
    if len(values) < 2:
        return "LOW", None
    center = statistics.median(values)
    spread = (max(values) / center - min(values) / center) * 100.0 if center else None
    if len(values) == 3 and spread is not None and spread <= 20:
        return "HIGH", spread
    if spread is not None and spread <= 45:
        return "MEDIUM", spread
    return "LOW", spread


def relative_value_score(card: dict[str, Any]) -> float:
    """Score market weakness vs 30-day average; this is not purchase value."""
    change = pct(card.get("trend"), card.get("avg30"))
    if change is None:
        return 35.0
    return clamp(50.0 - change * 2.0)


def timing_score(card: dict[str, Any]) -> float:
    change = pct(card.get("avg1"), card.get("avg7"))
    if change is None:
        return 40.0
    return clamp(50.0 - change * 1.5)


def personal_score(card: dict[str, Any], profile: dict[str, Any]) -> tuple[float, list[str]]:
    """Personal relevance is now a gate, not a small bonus over the full catalogue."""
    card_id = str(card.get("id") or "")
    reasons: list[str] = []
    score = 0.0

    wishlist = {str(value) for value in profile.get("wishlist_ids", [])}
    manual_priority = {str(value) for value in profile.get("manual_priority_ids", [])}

    if card_id in wishlist:
        score = max(score, 100.0)
        reasons.append("wishlist")
    if card_id in manual_priority:
        score = max(score, 100.0)
        reasons.append("manual priority")

    primary = profile.get("priority_pokemon", [])
    secondary = profile.get("secondary_pokemon", [])
    if any(contains_name(card.get("name"), value) for value in primary):
        score = max(score, 80.0)
        reasons.append("priority Pokémon")
    elif any(contains_name(card.get("name"), value) for value in secondary):
        score = max(score, 60.0)
        reasons.append("secondary Pokémon")

    return score, reasons


def target_for(card: dict[str, Any], profile: dict[str, Any]) -> float:
    """Manual purchase budget metadata only; never compared with aggregate reference."""
    overrides = profile.get("target_overrides_dkk", {})
    override = number(overrides.get(str(card.get("id") or ""))) if isinstance(overrides, dict) else None
    default = number(profile.get("default_target_dkk")) or 75.0
    return override if override is not None and override > 0 else default


def evaluate_card(card: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any] | None:
    if str(card.get("game") or "") != "POKÉMON":
        return None

    card_id = str(card.get("id") or "")
    ignored = {str(value) for value in profile.get("ignore_ids", [])}
    owned = {str(value) for value in profile.get("owned_ids", [])}
    if card_id in ignored or card_id in owned or is_non_physical_card(card):
        return None

    personal, personal_reasons = personal_score(card, profile)
    if not personal_reasons:
        return None

    reference_eur = reference_price_eur(card)
    if reference_eur is None or reference_eur <= 0:
        return None

    eur_dkk = number(profile.get("eur_to_dkk")) or 7.46
    reference_dkk = reference_eur * eur_dkk
    purchase_budget_dkk = target_for(card, profile)
    value = relative_value_score(card)
    timing = timing_score(card)
    confidence, spread = data_confidence(card)
    confidence_component = {"HIGH": 100.0, "MEDIUM": 70.0, "LOW": 20.0}[confidence]

    # V50.1: no budget component. Aggregate price data cannot prove a usable
    # English/NM/EU listing, so price-to-budget math must not drive the signal.
    score = value * 0.45 + timing * 0.20 + personal * 0.25 + confidence_component * 0.10
    if confidence == "LOW":
        score = min(score, 59.9)

    thirty_day = pct(card.get("trend"), card.get("avg30"))
    strong_dip = thirty_day is not None and thirty_day <= -20.0
    moderate_dip = thirty_day is not None and thirty_day <= -10.0
    explicitly_curated = "wishlist" in personal_reasons or "manual priority" in personal_reasons

    if confidence != "LOW" and score >= 72.0 and (strong_dip or (explicitly_curated and moderate_dip)):
        signal = "REVIEW"
    elif confidence != "LOW" and score >= 58.0 and moderate_dip:
        signal = "WATCH"
    else:
        signal = "PASS"

    reasons = list(personal_reasons)
    one_week = pct(card.get("avg1"), card.get("avg7"))
    if thirty_day is not None:
        if thirty_day <= -5:
            reasons.append(f"trend {abs(thirty_day):.1f}% under avg30")
        elif thirty_day >= 8:
            reasons.append(f"trend {thirty_day:.1f}% over avg30")
    reasons.append("aggregate reference is not purchase price")
    if confidence == "LOW":
        reasons.append("low aggregate confidence")

    return {
        "id": card_id,
        "name": str(card.get("name") or "Ukendt kort"),
        "set": str(card.get("set") or "Ukendt sæt"),
        "variant": str(card.get("variant") or ""),
        "signal": signal,
        "score": round(score, 1),
        "reference_eur": round(reference_eur, 2),
        "reference_dkk": round(reference_dkk, 2),
        "purchase_budget_dkk": round(purchase_budget_dkk, 2),
        "trend_eur": number(card.get("trend")),
        "avg1_eur": number(card.get("avg1")),
        "avg7_eur": number(card.get("avg7")),
        "avg30_eur": number(card.get("avg30")),
        "diagnostic_low_eur": number(card.get("low")),
        "trend_vs_avg30_pct": thirty_day,
        "avg1_vs_avg7_pct": one_week,
        "confidence": confidence,
        "aggregate_spread_pct": spread,
        "reasons": reasons,
    }


def evaluate_state(state: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    raw_cards = state.get("cards", {}) if isinstance(state, dict) else {}
    if not isinstance(raw_cards, dict):
        return []
    rows = []
    for card in raw_cards.values():
        if not isinstance(card, dict):
            continue
        row = evaluate_card(card, profile)
        if row is not None:
            rows.append(row)
    signal_order = {"REVIEW": 0, "WATCH": 1, "PASS": 2}
    return sorted(rows, key=lambda row: (signal_order[row["signal"]], -row["score"], row["reference_dkk"], row["name"]))


def fmt_money(value: Any, currency: str = "kr.") -> str:
    parsed = number(value)
    if parsed is None:
        return "–"
    return f"{parsed:.0f} {currency}" if currency == "kr." else f"€{parsed:.2f}"


def build_report(rows: list[dict[str, Any]], profile: dict[str, Any], limit: int = DEFAULT_LIMIT) -> str:
    visible = [row for row in rows if row["signal"] != "PASS"][:limit]
    reviews = sum(1 for row in rows if row["signal"] == "REVIEW")
    watches = sum(1 for row in rows if row["signal"] == "WATCH")
    lines = [
        "# Personal Singles Scout · V50.1 shadow",
        "",
        "> Aggregate Cardmarket radar only. REVIEW means: open the actual listings and verify them.",
        "> Market reference is NOT an EN/NM purchase price and is never compared with the purchase budget.",
        "> Verify exact version, English, MT/NM, EU/EEA seller and shipping to Denmark before purchase.",
        "",
        f"- Personal candidate pool: {len(rows)} cards",
        f"- REVIEW: {reviews}",
        f"- WATCH: {watches}",
        f"- Manual purchase budget: {fmt_money(profile.get('default_target_dkk', 75))}",
        "- `low` has zero weight; aggregate trend/averages are market context only.",
        "- Non-personal cards and code cards are filtered before scoring.",
        "",
        "## Ranked radar candidates",
        "",
        "| Signal | Score | Card | Set | Market ref | 30d move | Confidence | Why |",
        "|---|---:|---|---|---:|---:|---|---|",
    ]
    if not visible:
        lines.append("| – | – | No current candidates | – | – | – | – | – |")
    for row in visible:
        move = row.get("trend_vs_avg30_pct")
        move_text = "–" if move is None else f"{move:+.1f}%"
        why = "; ".join(row["reasons"][:3]) or "aggregate market movement"
        lines.append(
            f"| {row['signal']} | {row['score']:.1f} | {row['name'].replace('|', '/')} | "
            f"{row['set'].replace('|', '/')} | {fmt_money(row['reference_dkk'])} | "
            f"{move_text} | {row['confidence']} | {why} |"
        )
    lines.extend(
        [
            "",
            "## Guardrail",
            "",
            "V50.1 never emits BUY and does not infer a purchase price from aggregate Cardmarket data.",
            "REVIEW is only a manual-inspection signal. The 75 kr. budget is metadata until a concrete EN/NM/EU->DK offer is verified.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state = load_json(args.state, {})
    profile = load_json(args.profile, {})
    if not profile:
        raise SystemExit(f"Personal profile missing or empty: {args.profile}")
    rows = evaluate_state(state, profile)
    if not rows:
        raise SystemExit(f"No usable personal Pokemon radar candidates found in {args.state}")
    report = build_report(rows, profile, max(1, args.limit))
    args.output.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
