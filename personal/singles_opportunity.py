#!/usr/bin/env python3
"""V50 personal singles opportunity engine.

Shadow-only decision layer over the existing aggregate Cardmarket state.
It performs no network requests, sends no Discord messages, and writes no
production state. Aggregate `low` is deliberately excluded from scoring because
V49 showed that it is not purchase-grade for the user's EN/NM/EU->DK constraints.
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
DEFAULT_LIMIT = 20


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


def reference_price_eur(card: dict[str, Any]) -> float | None:
    """Purchase radar reference: trend first; averages are fallbacks, never low."""
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


def budget_score(price_dkk: float, target_dkk: float) -> float:
    if target_dkk <= 0:
        return 0.0
    ratio = price_dkk / target_dkk
    if ratio <= 0.5:
        return 100.0
    if ratio <= 1.0:
        return 100.0 - (ratio - 0.5) * 40.0
    return clamp(80.0 - (ratio - 1.0) * 100.0)


def relative_value_score(card: dict[str, Any]) -> float:
    change = pct(card.get("trend"), card.get("avg30"))
    if change is None:
        return 50.0
    return clamp(50.0 - change * 2.0)


def timing_score(card: dict[str, Any]) -> float:
    change = pct(card.get("avg1"), card.get("avg7"))
    if change is None:
        return 50.0
    return clamp(50.0 - change * 1.5)


def personal_score(card: dict[str, Any], profile: dict[str, Any]) -> tuple[float, list[str]]:
    card_id = str(card.get("id") or "")
    reasons: list[str] = []
    score = 35.0

    wishlist = {str(value) for value in profile.get("wishlist_ids", [])}
    manual_priority = {str(value) for value in profile.get("manual_priority_ids", [])}

    if card_id in wishlist:
        score += 40.0
        reasons.append("wishlist")
    if card_id in manual_priority:
        score += 45.0
        reasons.append("manual priority")

    primary = profile.get("priority_pokemon", [])
    secondary = profile.get("secondary_pokemon", [])
    if any(contains_name(card.get("name"), value) for value in primary):
        score += 30.0
        reasons.append("priority Pokémon")
    elif any(contains_name(card.get("name"), value) for value in secondary):
        score += 15.0
        reasons.append("secondary Pokémon")

    return clamp(score), reasons


def target_for(card: dict[str, Any], profile: dict[str, Any]) -> float:
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
    if card_id in ignored or card_id in owned:
        return None

    reference_eur = reference_price_eur(card)
    if reference_eur is None or reference_eur <= 0:
        return None

    eur_dkk = number(profile.get("eur_to_dkk")) or 7.46
    reference_dkk = reference_eur * eur_dkk
    target_dkk = target_for(card, profile)
    budget = budget_score(reference_dkk, target_dkk)
    value = relative_value_score(card)
    timing = timing_score(card)
    personal, personal_reasons = personal_score(card, profile)
    confidence, spread = data_confidence(card)

    score = budget * 0.40 + value * 0.25 + timing * 0.15 + personal * 0.20
    if confidence == "LOW":
        score = min(score, 64.9)

    budget_ratio = reference_dkk / target_dkk if target_dkk > 0 else math.inf
    if confidence != "LOW" and score >= 70 and budget_ratio <= 1.0:
        signal = "CHECK_NOW"
    elif score >= 55 and budget_ratio <= 1.35:
        signal = "WATCH"
    else:
        signal = "PASS"

    reasons = list(personal_reasons)
    thirty_day = pct(card.get("trend"), card.get("avg30"))
    one_week = pct(card.get("avg1"), card.get("avg7"))
    if thirty_day is not None:
        if thirty_day <= -5:
            reasons.append(f"trend {abs(thirty_day):.1f}% under avg30")
        elif thirty_day >= 8:
            reasons.append(f"trend {thirty_day:.1f}% over avg30")
    if reference_dkk <= target_dkk:
        reasons.append("reference within target")
    else:
        reasons.append(f"reference {budget_ratio:.2f}x target")
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
        "target_dkk": round(target_dkk, 2),
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
    signal_order = {"CHECK_NOW": 0, "WATCH": 1, "PASS": 2}
    return sorted(rows, key=lambda row: (signal_order[row["signal"]], -row["score"], row["reference_dkk"], row["name"]))


def fmt_money(value: Any, currency: str = "kr.") -> str:
    parsed = number(value)
    if parsed is None:
        return "–"
    return f"{parsed:.0f} {currency}" if currency == "kr." else f"€{parsed:.2f}"


def build_report(rows: list[dict[str, Any]], profile: dict[str, Any], limit: int = DEFAULT_LIMIT) -> str:
    visible = [row for row in rows if row["signal"] != "PASS"][:limit]
    checks = sum(1 for row in rows if row["signal"] == "CHECK_NOW")
    watches = sum(1 for row in rows if row["signal"] == "WATCH")
    lines = [
        "# Personal Singles Scout · V50 shadow",
        "",
        "> Aggregate Cardmarket radar only. CHECK_NOW is not a buy signal.",
        "> Verify exact version, English, MT/NM, EU/EEA seller and shipping to Denmark before purchase.",
        "",
        f"- Evaluated: {len(rows)} Pokémon cards",
        f"- CHECK_NOW: {checks}",
        f"- WATCH: {watches}",
        f"- Default target: {fmt_money(profile.get('default_target_dkk', 75))}",
        "- `low` is diagnostic only and has zero weight in the score.",
        "",
        "## Ranked opportunities",
        "",
        "| Signal | Score | Card | Set | Reference | Target | Confidence | Why |",
        "|---|---:|---|---|---:|---:|---|---|",
    ]
    if not visible:
        lines.append("| – | – | No current candidates | – | – | – | – | – |")
    for row in visible:
        why = "; ".join(row["reasons"][:3]) or "aggregate pricing"
        lines.append(
            f"| {row['signal']} | {row['score']:.1f} | {row['name'].replace('|', '/')} | "
            f"{row['set'].replace('|', '/')} | {fmt_money(row['reference_dkk'])} | "
            f"{fmt_money(row['target_dkk'])} | {row['confidence']} | {why} |"
        )
    lines.extend(
        [
            "",
            "## Guardrail",
            "",
            "This engine never emits BUY. Its strongest status is CHECK_NOW because the current aggregate feed cannot verify language, condition, seller region or Denmark shipping.",
            "Trend is the primary price reference; avg7/avg30 provide context and fallbacks. Aggregate low is never used for ranking or thresholds.",
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
        raise SystemExit(f"No usable Pokemon aggregate cards found in {args.state}")
    report = build_report(rows, profile, max(1, args.limit))
    args.output.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
