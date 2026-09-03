#!/usr/bin/env python3
"""V55 canonical-rarity quality layer for the personal singles radar.

Shadow-only. V55 keeps the V54 75/150 DKK budget model and exact collection
suppression, but no longer lets heuristic collectability alone create REVIEW.
Canonical rarity metadata is keyed by exact Cardmarket product ID and is used to
calibrate collectability. Cards without verified canonical metadata can still be
WATCH candidates, but cannot become REVIEW unless explicitly curated.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from personal import singles_opportunity as v53
from personal import singles_v54 as v54

DEFAULT_RARITY_METADATA = Path("personal/pokemon_rarity_metadata.json")


def load_rarity_metadata(path: Path = DEFAULT_RARITY_METADATA) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    cards = payload.get("cards", {}) if isinstance(payload, dict) else {}
    return cards if isinstance(cards, dict) else {}


def canonical_rarity_score(rarity: Any) -> float:
    """Map canonical Pokémon TCG rarity text to a conservative collector score."""
    value = v53.normalize_text(rarity)
    if not value:
        return 50.0
    if "special illustration" in value:
        return 100.0
    if "hyper rare" in value or "secret rare" in value or value == "rare secret":
        return 98.0
    if "illustration rare" in value:
        return 92.0
    if "ultra rare" in value or "rainbow rare" in value:
        return 90.0
    if "rare holo" in value:
        return 82.0
    if "double rare" in value:
        return 78.0
    if value == "rare" or value.startswith("rare "):
        return 68.0
    if "promo" in value:
        return 72.0
    if value == "uncommon":
        return 50.0
    if value == "common":
        return 35.0
    return 55.0


def verified_metadata_for(
    card: dict[str, Any], rarity_metadata: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """Return metadata only when exact Cardmarket ID and expected set still agree."""
    card_id = str(card.get("id") or "")
    meta = rarity_metadata.get(card_id)
    if not isinstance(meta, dict):
        return None
    expected_set = v53.normalize_text(meta.get("cardmarket_set"))
    actual_set = v53.normalize_text(card.get("set"))
    if expected_set and expected_set != actual_set:
        return None
    if not str(meta.get("canonical_rarity") or "").strip():
        return None
    return meta


def calibrated_collectability(
    card: dict[str, Any], rarity_metadata: dict[str, dict[str, Any]]
) -> tuple[float, str, list[str], dict[str, Any] | None]:
    """Blend V54 card-character evidence with canonical rarity when verified.

    Heuristic-only cards are deliberately capped below STRONG. This prevents an
    old set name or special mechanic text from silently unlocking the 150 DKK
    tier without canonical rarity coverage.
    """
    heuristic, _, heuristic_reasons = v54.collectability_score(card)
    meta = verified_metadata_for(card, rarity_metadata)

    if meta is None:
        score = min(heuristic * 0.75, 69.9)
        tier = "COLLECTABLE" if score >= 60 else "STANDARD"
        reasons = list(heuristic_reasons)
        reasons.append("canonical rarity unverified")
        return score, tier, reasons, None

    rarity = str(meta.get("canonical_rarity") or "Unknown")
    rarity_component = canonical_rarity_score(rarity)
    score = heuristic * 0.70 + rarity_component * 0.30
    if score >= 90:
        tier = "ICONIC"
    elif score >= 75:
        tier = "STRONG"
    elif score >= 60:
        tier = "COLLECTABLE"
    else:
        tier = "STANDARD"

    reasons = list(heuristic_reasons)
    reasons.append(f"canonical rarity: {rarity}")
    return score, tier, reasons, meta


def evaluate_card(
    card: dict[str, Any],
    profile: dict[str, Any],
    rarity_metadata: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    rarity_metadata = rarity_metadata if rarity_metadata is not None else load_rarity_metadata()
    base = v53.evaluate_card(card, profile)
    if base is None:
        return None

    collectability, tier, collect_reasons, meta = calibrated_collectability(card, rarity_metadata)
    canonical_verified = meta is not None
    canonical_rarity = str(meta.get("canonical_rarity")) if meta else "UNVERIFIED"
    canonical_card_id = str(meta.get("source_card_id")) if meta else ""

    personal, personal_reasons = v53.personal_score(card, profile)
    confidence, spread = v53.data_confidence(card)
    confidence_component = {"HIGH": 100.0, "MEDIUM": 70.0, "LOW": 20.0}[confidence]
    value = v53.relative_value_score(card)
    timing = v53.timing_score(card)
    target = v54.target_for(card, profile, collectability)
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
    within_review_ceiling = base["reference_dkk"] <= review_ceiling or explicitly_curated
    rarity_gate = canonical_verified or explicitly_curated

    if confidence != "LOW" and score >= 72.0 and within_review_ceiling and rarity_gate and (
        strong_dip or (explicitly_curated and moderate_dip)
    ):
        signal = "REVIEW"
    elif confidence != "LOW" and score >= 58.0 and moderate_dip:
        signal = "WATCH"
    else:
        signal = "PASS"

    reasons = list(personal_reasons)
    if collect_reasons:
        reasons.append(collect_reasons[-1] if canonical_verified else "canonical rarity unverified")
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
        "canonical_rarity": canonical_rarity,
        "canonical_rarity_verified": canonical_verified,
        "canonical_card_id": canonical_card_id,
        "aggregate_spread_pct": spread,
        "reasons": reasons,
    }


def evaluate_state(
    state: dict[str, Any],
    profile: dict[str, Any],
    rarity_metadata: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rarity_metadata = rarity_metadata if rarity_metadata is not None else load_rarity_metadata()
    raw_cards = state.get("cards", {}) if isinstance(state, dict) else {}
    if not isinstance(raw_cards, dict):
        return []
    rows = [
        evaluate_card(card, profile, rarity_metadata)
        for card in raw_cards.values()
        if isinstance(card, dict)
    ]
    rows = [row for row in rows if row is not None]
    signal_order = {"REVIEW": 0, "WATCH": 1, "PASS": 2}
    collect_order = {"ICONIC": 0, "STRONG": 1, "COLLECTABLE": 2, "STANDARD": 3}
    return sorted(
        rows,
        key=lambda row: (
            signal_order[row["signal"]],
            -row["score"],
            0 if row.get("canonical_rarity_verified") else 1,
            collect_order.get(row.get("collectability_tier"), 9),
            row["reference_dkk"],
            row["name"],
        ),
    )


def build_report(rows: list[dict[str, Any]], profile: dict[str, Any], limit: int = 10) -> str:
    visible = [row for row in rows if row["signal"] != "PASS"][:limit]
    reviews = sum(row["signal"] == "REVIEW" for row in rows)
    watches = sum(row["signal"] == "WATCH" for row in rows)
    canonical = sum(bool(row.get("canonical_rarity_verified")) for row in rows)
    review_verified = sum(
        row["signal"] == "REVIEW" and bool(row.get("canonical_rarity_verified")) for row in rows
    )
    strong = sum(row.get("collectability_tier") in {"ICONIC", "STRONG"} for row in rows)
    normal_target = profile.get("default_target_dkk", 75)
    strong_target = profile.get("collectable_target_dkk", normal_target)
    ceiling = profile.get("automatic_review_ceiling_dkk", 150)

    lines = [
        "# Personal Singles Scout · V55 canonical-rarity shadow",
        "",
        "> REVIEW remains manual inspection only; aggregate Cardmarket values are not verified purchase prices.",
        "> Canonical rarity metadata is linked by exact Cardmarket product ID. No fuzzy rarity linking is used.",
        "> Verify exact version, English, MT/NM, EU/EEA seller and shipping to Denmark before purchase.",
        "",
        f"- Personal candidate pool: {len(rows)} cards",
        f"- REVIEW: {reviews}",
        f"- WATCH: {watches}",
        f"- Canonical rarity coverage: {canonical}/{len(rows)}",
        f"- REVIEW with verified canonical rarity: {review_verified}/{reviews}",
        f"- Strong/iconic collectability after rarity calibration: {strong}",
        f"- Normal singles target: {v53.fmt_money(normal_target)}",
        f"- Strong collectable target: {v53.fmt_money(strong_target)}",
        f"- Automatic REVIEW ceiling: {v53.fmt_money(ceiling)}",
        "- Unverified rarity can WATCH but cannot REVIEW unless explicitly curated.",
        "- 150 kr. remains reserved for STRONG/ICONIC collectability or explicit overrides.",
        "",
        "## Ranked radar candidates",
        "",
        "| Signal | Score | Card | Set | Market ref | Rarity | Quality | Target | 30d move | Why |",
        "|---|---:|---|---|---:|---|---|---:|---:|---|",
    ]
    if not visible:
        lines.append("| – | – | No current candidates | – | – | – | – | – | – | – |")
    for row in visible:
        move = row.get("trend_vs_avg30_pct")
        move_text = "–" if move is None else f"{move:+.1f}%"
        why = "; ".join(row["reasons"][:3])
        lines.append(
            f"| {row['signal']} | {row['score']:.1f} | {row['name'].replace('|', '/')} | "
            f"{row['set'].replace('|', '/')} | {v53.fmt_money(row['reference_dkk'])} | "
            f"{row['canonical_rarity']} | {row['collectability_tier']} | "
            f"{v53.fmt_money(row['purchase_budget_dkk'])} | {move_text} | {why} |"
        )
    lines += [
        "",
        "## Guardrail",
        "",
        "V55 never emits BUY and never treats aggregate Cardmarket data as an available purchase price.",
        "Canonical rarity improves card-quality ranking only; an actual listing still requires separate verification.",
        "",
    ]
    return "\n".join(lines)
