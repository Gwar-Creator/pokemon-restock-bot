#!/usr/bin/env python3
"""V54 collectability-aware ranking layer over V53 singles radar.

Shadow-only. No network requests, Discord posts, or production state writes.
Aggregate Cardmarket values remain market context, never verified offer prices.
"""

from __future__ import annotations

from typing import Any

from personal import singles_opportunity as v53

HERITAGE_SETS = {
    "base set", "base set 2", "jungle", "fossil", "team rocket",
    "gym heroes", "gym challenge", "neo genesis", "neo discovery",
    "neo revelation", "neo destiny", "legendary collection",
    "expedition base set", "aquapolis", "skyridge",
}

OLDER_ERA_SETS = {
    "diamond pearl", "mysterious treasures", "secret wonders",
    "great encounters", "majestic dawn", "legends awakened", "stormfront",
    "platinum", "rising rivals", "supreme victors", "arceus",
    "heartgold soulsilver", "unleashed", "undaunted", "triumphant",
    "call of legends", "black white", "emerging powers", "noble victories",
    "next destinies", "dark explorers", "dragons exalted",
    "boundaries crossed", "plasma storm", "plasma freeze", "plasma blast",
    "legendary treasures", "xy", "flashfire", "furious fists",
    "phantom forces", "primal clash", "roaring skies", "ancient origins",
    "breakthrough", "breakpoint", "fates collide", "steam siege",
}


def collectability_score(card: dict[str, Any]) -> tuple[float, str, list[str]]:
    """Conservative collector score from metadata that exists in radar state."""
    set_name = v53.normalize_text(card.get("set"))
    subject = v53.normalize_text(v53.subject_name(card.get("name")))
    variant = v53.normalize_text(card.get("variant"))
    score = 35.0
    reasons: list[str] = []

    if set_name in HERITAGE_SETS:
        score = 80.0
        reasons.append("heritage set")
    elif set_name.startswith("ex "):
        score = 78.0
        reasons.append("EX-era set")
    elif set_name in OLDER_ERA_SETS:
        score = 65.0
        reasons.append("older-era set")

    special_subjects = (
        ("gold star", 100.0, "Gold Star"),
        ("delta species", 95.0, "Delta Species"),
        ("shining", 95.0, "Shining"),
        (" lv x", 90.0, "Lv.X"),
        (" prime", 88.0, "Prime"),
        (" legend", 88.0, "LEGEND"),
    )
    padded_subject = f" {subject} "
    for marker, value, reason in special_subjects:
        if marker in padded_subject:
            score = max(score, value)
            reasons.append(reason)
            break

    if subject.endswith(" vmax") or subject.endswith(" vstar") or subject.endswith(" gx"):
        score = max(score, 65.0)
    elif subject.endswith(" ex"):
        score = max(score, 55.0)
    elif subject.endswith(" v"):
        score = max(score, 45.0)

    variant_signals = (
        ("special illustration", 95.0, "special illustration"),
        ("illustration rare", 88.0, "illustration rare"),
        ("trainer gallery", 85.0, "trainer gallery"),
        ("full art", 85.0, "full art"),
        ("secret rare", 90.0, "secret rare"),
        ("rainbow", 85.0, "rainbow"),
        ("radiant", 80.0, "radiant"),
        ("shiny", 80.0, "shiny"),
        ("1st edition", 90.0, "1st edition"),
        ("promo", 75.0, "promo"),
        ("reverse holo", 72.0, "reverse holo"),
        ("holo", 68.0, "holo"),
    )
    for marker, value, reason in variant_signals:
        if marker in variant:
            score = max(score, value)
            reasons.append(reason)
            break

    if score >= 90:
        tier = "ICONIC"
    elif score >= 75:
        tier = "STRONG"
    elif score >= 60:
        tier = "COLLECTABLE"
    else:
        tier = "STANDARD"
    return score, tier, reasons


def target_for(card: dict[str, Any], profile: dict[str, Any], collectability: float) -> float:
    overrides = profile.get("target_overrides_dkk", {})
    override = v53.number(overrides.get(str(card.get("id") or ""))) if isinstance(overrides, dict) else None
    if override is not None and override > 0:
        return override

    default = v53.number(profile.get("default_target_dkk")) or 75.0
    strong_target = v53.number(profile.get("collectable_target_dkk")) or default
    threshold = v53.number(profile.get("collectable_target_min_score")) or 75.0
    return max(default, strong_target) if collectability >= threshold else default


def evaluate_card(card: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any] | None:
    base = v53.evaluate_card(card, profile)
    if base is None:
        return None

    collectability, tier, collect_reasons = collectability_score(card)
    personal, personal_reasons = v53.personal_score(card, profile)
    confidence, spread = v53.data_confidence(card)
    confidence_component = {"HIGH": 100.0, "MEDIUM": 70.0, "LOW": 20.0}[confidence]
    value = v53.relative_value_score(card)
    timing = v53.timing_score(card)
    target = target_for(card, profile, collectability)
    market_band, market_fit, market_ratio = v53.market_scale_fit(base["reference_dkk"], target)
    explicitly_curated = "wishlist" in personal_reasons or "manual priority" in personal_reasons

    score = (
        value * 0.25
        + timing * 0.10
        + personal * 0.25
        + confidence_component * 0.10
        + market_fit * 0.15
        + collectability * 0.15
    )
    if explicitly_curated:
        score += 5.0
    if confidence == "LOW":
        score = min(score, 59.9)

    thirty_day = v53.pct(card.get("trend"), card.get("avg30"))
    strong_dip = thirty_day is not None and thirty_day <= -20.0
    moderate_dip = thirty_day is not None and thirty_day <= -10.0
    review_ceiling = v53.number(profile.get("automatic_review_ceiling_dkk")) or 150.0
    actionable = base["reference_dkk"] <= review_ceiling or explicitly_curated

    if confidence != "LOW" and score >= 72.0 and actionable and (
        strong_dip or (explicitly_curated and moderate_dip)
    ):
        signal = "REVIEW"
    elif confidence != "LOW" and score >= 58.0 and moderate_dip:
        signal = "WATCH"
    else:
        signal = "PASS"

    reasons = list(personal_reasons)
    if collect_reasons:
        reasons.append(collect_reasons[0])
    if thirty_day is not None and thirty_day <= -5:
        reasons.append(f"trend {abs(thirty_day):.1f}% under avg30")
    reasons.append(f"aggregate market scale: {market_band.lower()}")
    if confidence == "LOW":
        reasons.append("low aggregate confidence")

    return {
        **base,
        "signal": signal,
        "score": round(score, 1),
        "purchase_budget_dkk": round(target, 2),
        "market_band": market_band,
        "market_ratio_to_target": round(market_ratio, 3),
        "collectability_score": round(collectability, 1),
        "collectability_tier": tier,
        "aggregate_spread_pct": spread,
        "reasons": reasons,
    }


def evaluate_state(state: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    raw_cards = state.get("cards", {}) if isinstance(state, dict) else {}
    if not isinstance(raw_cards, dict):
        return []
    rows = [evaluate_card(card, profile) for card in raw_cards.values() if isinstance(card, dict)]
    rows = [row for row in rows if row is not None]
    signal_order = {"REVIEW": 0, "WATCH": 1, "PASS": 2}
    collect_order = {"ICONIC": 0, "STRONG": 1, "COLLECTABLE": 2, "STANDARD": 3}
    return sorted(
        rows,
        key=lambda row: (
            signal_order[row["signal"]],
            -row["score"],
            collect_order.get(row.get("collectability_tier"), 9),
            row["reference_dkk"],
            row["name"],
        ),
    )


def build_report(rows: list[dict[str, Any]], profile: dict[str, Any], limit: int = 10) -> str:
    visible = [row for row in rows if row["signal"] != "PASS"][:limit]
    reviews = sum(row["signal"] == "REVIEW" for row in rows)
    watches = sum(row["signal"] == "WATCH" for row in rows)
    strong = sum(row.get("collectability_tier") in {"ICONIC", "STRONG"} for row in rows)
    normal_target = profile.get("default_target_dkk", 75)
    strong_target = profile.get("collectable_target_dkk", normal_target)
    ceiling = profile.get("automatic_review_ceiling_dkk", 150)

    lines = [
        "# Personal Singles Scout · V54 collectability shadow",
        "",
        "> REVIEW is a manual-inspection signal only; aggregate Cardmarket values are not verified purchase prices.",
        "> Verify exact version, English, MT/NM, EU/EEA seller and shipping to Denmark before purchase.",
        "",
        f"- Personal candidate pool: {len(rows)} cards",
        f"- REVIEW: {reviews}",
        f"- WATCH: {watches}",
        f"- Strong/iconic collectability: {strong}",
        f"- Normal singles target: {v53.fmt_money(normal_target)}",
        f"- Strong collectable target: {v53.fmt_money(strong_target)}",
        f"- Automatic REVIEW ceiling: {v53.fmt_money(ceiling)}",
        "- 150 kr. is not a blanket target; it is reserved for strong/iconic collectability or explicit overrides.",
        "- Collectability is conservative because the aggregate state has no canonical rarity field.",
        "",
        "## Ranked radar candidates",
        "",
        "| Signal | Score | Card | Set | Market ref | Collectability | Target | 30d move | Why |",
        "|---|---:|---|---|---:|---|---:|---:|---|",
    ]
    if not visible:
        lines.append("| – | – | No current candidates | – | – | – | – | – | – |")
    for row in visible:
        move = row.get("trend_vs_avg30_pct")
        move_text = "–" if move is None else f"{move:+.1f}%"
        why = "; ".join(row["reasons"][:3])
        lines.append(
            f"| {row['signal']} | {row['score']:.1f} | {row['name'].replace('|', '/')} | "
            f"{row['set'].replace('|', '/')} | {v53.fmt_money(row['reference_dkk'])} | "
            f"{row['collectability_tier']} | {v53.fmt_money(row['purchase_budget_dkk'])} | {move_text} | {why} |"
        )
    lines += [
        "",
        "## Guardrail",
        "",
        "V54 never emits BUY and never treats aggregate Cardmarket data as an available purchase price.",
        "",
    ]
    return "\n".join(lines)
