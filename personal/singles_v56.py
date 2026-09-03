#!/usr/bin/env python3
"""V56 exact-listing verification layer for the personal singles radar.

V56 preserves V55's canonical-rarity and collection guardrails, then overlays a
read-only snapshot of concrete Cardmarket marketplace articles. Aggregate price
fields remain radar context only. A card becomes LISTING_REVIEW only when an
individual offer is exact-product matched, English, MT/NM, from an EU/EEA seller,
confirmed to ship to Denmark, fresh, and within the card's DKK purchase budget.

The official Cardmarket Articles API does not expose destination-specific shipping
eligibility or shipping cost in an Article entity. Those two fields therefore stay
unverified until supplied by a separate explicit shipping verification step. V56
never infers them from seller country and never emits BUY.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from personal import singles_opportunity as v53
from personal import singles_v55 as v55

DEFAULT_LISTINGS = Path("personal/cardmarket_listing_snapshot.json")
DEFAULT_SHIPPING = Path("personal/cardmarket_listing_shipping_overrides.json")
MAX_LISTING_AGE_HOURS = 36.0
EU_EEA_COUNTRIES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "D",
    "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO",
    "SK", "SI", "ES", "SE", "IS", "LI", "NO",
}
ACCEPTED_CONDITIONS = {"MT", "NM"}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def load_listing_snapshot(path: Path = DEFAULT_LISTINGS) -> dict[str, Any]:
    payload = load_json(path, {})
    return payload if isinstance(payload, dict) else {}


def load_shipping_overrides(path: Path = DEFAULT_SHIPPING) -> dict[str, dict[str, Any]]:
    payload = load_json(path, {})
    if not isinstance(payload, dict):
        return {}
    rows = payload.get("articles", payload)
    if not isinstance(rows, dict):
        return {}
    return {str(key): value for key, value in rows.items() if isinstance(value, dict)}


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def listing_age_hours(checked_at: Any, now: datetime | None = None) -> float | None:
    stamp = parse_time(checked_at)
    if stamp is None:
        return None
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0.0, (now.astimezone(timezone.utc) - stamp).total_seconds() / 3600.0)


def listing_rows_for(snapshot: dict[str, Any], product_id: str) -> list[dict[str, Any]]:
    offers = snapshot.get("offers", {}) if isinstance(snapshot, dict) else {}
    if not isinstance(offers, dict):
        return []
    rows = offers.get(str(product_id), [])
    if isinstance(rows, dict):
        rows = [rows]
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def merged_offer(offer: dict[str, Any], shipping: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result = dict(offer)
    article_id = str(result.get("id_article") or result.get("idArticle") or "")
    override = shipping.get(article_id)
    if isinstance(override, dict):
        for field in ("ships_to_denmark", "shipping_eur", "shipping_checked_at", "shipping_source"):
            if field in override:
                result[field] = override[field]
    return result


def offer_checks(
    offer: dict[str, Any],
    product_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    offered_product = str(offer.get("product_id") or offer.get("idProduct") or "")
    language_id = offer.get("language_id")
    if language_id is None and isinstance(offer.get("language"), dict):
        language_id = offer["language"].get("idLanguage")
    language = str(offer.get("language") or "") if not isinstance(offer.get("language"), dict) else str(offer["language"].get("languageName") or "")
    condition = str(offer.get("condition") or "").upper()
    seller_country = str(offer.get("seller_country") or "").upper()
    price_eur = number(offer.get("price_eur") if "price_eur" in offer else offer.get("price"))
    shipping_eur = number(offer.get("shipping_eur"))
    age = listing_age_hours(offer.get("checked_at"), now)

    exact_product = offered_product == str(product_id)
    english = str(language_id) == "1" or language.strip().casefold() == "english"
    condition_ok = condition in ACCEPTED_CONDITIONS
    eu_eea = seller_country in EU_EEA_COUNTRIES
    ships = offer.get("ships_to_denmark") is True
    fresh = age is not None and age <= MAX_LISTING_AGE_HOURS
    listing_price_known = price_eur is not None
    shipping_known = shipping_eur is not None
    total_eur = price_eur + shipping_eur if listing_price_known and shipping_known else None

    return {
        "exact_product": exact_product,
        "english": english,
        "condition_ok": condition_ok,
        "eu_eea": eu_eea,
        "ships_to_denmark": ships,
        "fresh": fresh,
        "listing_price_known": listing_price_known,
        "shipping_known": shipping_known,
        "listing_price_eur": price_eur,
        "shipping_eur": shipping_eur,
        "total_eur": total_eur,
        "age_hours": age,
    }


def candidate_quality(checks: dict[str, Any]) -> int:
    fields = (
        "exact_product", "english", "condition_ok", "eu_eea", "fresh",
        "listing_price_known", "ships_to_denmark", "shipping_known",
    )
    return sum(bool(checks.get(field)) for field in fields)


def best_offer_for(
    product_id: str,
    snapshot: dict[str, Any],
    shipping: dict[str, dict[str, Any]],
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    candidates: list[tuple[tuple[Any, ...], dict[str, Any], dict[str, Any]]] = []
    for raw in listing_rows_for(snapshot, product_id):
        offer = merged_offer(raw, shipping)
        checks = offer_checks(offer, product_id, now=now)
        total = checks["total_eur"]
        price = checks["listing_price_eur"]
        sort_key = (
            -candidate_quality(checks),
            total if total is not None else 10**9,
            price if price is not None else 10**9,
            str(offer.get("id_article") or offer.get("idArticle") or ""),
        )
        candidates.append((sort_key, offer, checks))
    if not candidates:
        return None, None
    _, offer, checks = min(candidates, key=lambda row: row[0])
    return offer, checks


def evaluate_card(
    card: dict[str, Any],
    profile: dict[str, Any],
    rarity_metadata: dict[str, dict[str, Any]],
    snapshot: dict[str, Any],
    shipping: dict[str, dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    base = v55.evaluate_card(card, profile, rarity_metadata)
    if base is None:
        return None

    product_id = str(card.get("id") or "")
    offer, checks = best_offer_for(product_id, snapshot, shipping, now=now)
    result = dict(base)
    result["v55_signal"] = base["signal"]
    result["listing_status"] = "NO_OFFER"
    result["listing_signal"] = "RADAR_ONLY"
    result["listing_offer"] = offer
    result["listing_checks"] = checks
    result["listing_total_eur"] = None
    result["listing_total_dkk"] = None

    if offer is None or checks is None:
        return result

    required_listing = all(
        checks[field]
        for field in (
            "exact_product", "english", "condition_ok", "eu_eea", "fresh", "listing_price_known"
        )
    )
    shipping_verified = checks["ships_to_denmark"] and checks["shipping_known"]
    total_eur = checks["total_eur"]
    eur_to_dkk = number(profile.get("eur_to_dkk")) or 7.46
    total_dkk = total_eur * eur_to_dkk if total_eur is not None else None
    within_budget = total_dkk is not None and total_dkk <= float(base["purchase_budget_dkk"])

    result["listing_total_eur"] = round(total_eur, 2) if total_eur is not None else None
    result["listing_total_dkk"] = round(total_dkk, 2) if total_dkk is not None else None
    result["listing_within_budget"] = within_budget

    if required_listing and shipping_verified:
        result["listing_status"] = "VERIFIED"
        if base["signal"] == "REVIEW" and within_budget:
            result["listing_signal"] = "LISTING_REVIEW"
        else:
            result["listing_signal"] = "LISTING_WATCH"
    elif required_listing:
        result["listing_status"] = "SHIPPING_UNVERIFIED"
        result["listing_signal"] = "LISTING_WATCH"
    else:
        result["listing_status"] = "REJECTED"
        result["listing_signal"] = "RADAR_ONLY"

    return result


def evaluate_state(
    state: dict[str, Any],
    profile: dict[str, Any],
    rarity_metadata: dict[str, dict[str, Any]],
    snapshot: dict[str, Any],
    shipping: dict[str, dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    raw_cards = state.get("cards", {}) if isinstance(state, dict) else {}
    if not isinstance(raw_cards, dict):
        return []
    rows = [
        evaluate_card(card, profile, rarity_metadata, snapshot, shipping, now=now)
        for card in raw_cards.values()
        if isinstance(card, dict)
    ]
    rows = [row for row in rows if row is not None]
    order = {"LISTING_REVIEW": 0, "LISTING_WATCH": 1, "RADAR_ONLY": 2}
    return sorted(
        rows,
        key=lambda row: (
            order.get(row["listing_signal"], 9),
            0 if row.get("v55_signal") == "REVIEW" else 1,
            -float(row.get("score") or 0),
            row.get("listing_total_dkk") if row.get("listing_total_dkk") is not None else 10**9,
            str(row.get("name") or ""),
        ),
    )


def fmt_dkk(value: Any) -> str:
    number_value = number(value)
    if number_value is None:
        return "–"
    return f"{number_value:.0f} kr."


def fmt_eur(value: Any) -> str:
    number_value = number(value)
    if number_value is None:
        return "–"
    return f"€{number_value:.2f}"


def build_report(rows: list[dict[str, Any]], profile: dict[str, Any], limit: int = 10) -> str:
    listing_reviews = sum(row["listing_signal"] == "LISTING_REVIEW" for row in rows)
    listing_watch = sum(row["listing_signal"] == "LISTING_WATCH" for row in rows)
    shipping_unverified = sum(row.get("listing_status") == "SHIPPING_UNVERIFIED" for row in rows)
    verified = sum(row.get("listing_status") == "VERIFIED" for row in rows)
    with_offer = sum(row.get("listing_offer") is not None for row in rows)
    visible = [row for row in rows if row["listing_signal"] != "RADAR_ONLY"][: max(1, limit)]

    lines = [
        "# Personal Singles Scout · V56 exact-listing verification",
        "",
        "> V56 never emits BUY. LISTING_REVIEW is still a manual purchase check.",
        "> Aggregate Cardmarket low/trend values remain radar context only.",
        "> Denmark shipping is never inferred from seller country; it must be explicitly verified.",
        "",
        f"- Personal candidate pool: {len(rows)} cards",
        f"- Concrete offers in snapshot: {with_offer}",
        f"- Fully verified EN + MT/NM + EU/EEA + DK shipping offers: {verified}",
        f"- Offers waiting only/partly on shipping verification: {shipping_unverified}",
        f"- LISTING_REVIEW: {listing_reviews}",
        f"- LISTING_WATCH: {listing_watch}",
        "",
        "## Concrete listing candidates",
        "",
        "| Signal | V55 | Card | Set | Rarity | Listing | Shipping | Total | Budget | Seller |",
        "|---|---|---|---|---|---:|---:|---:|---:|---|",
    ]
    if not visible:
        lines.append("| – | – | No verified/partial listing candidates yet | – | – | – | – | – | – | – |")

    for row in visible:
        offer = row.get("listing_offer") or {}
        checks = row.get("listing_checks") or {}
        seller = str(offer.get("seller_name") or offer.get("seller") or "–")
        country = str(offer.get("seller_country") or "")
        if country:
            seller = f"{seller} ({country})"
        shipping_text = fmt_eur(checks.get("shipping_eur")) if checks.get("shipping_known") else "UNVERIFIED"
        lines.append(
            f"| {row['listing_signal']} | {row['v55_signal']} | {str(row['name']).replace('|', '/')} | "
            f"{str(row['set']).replace('|', '/')} | {row.get('canonical_rarity', '–')} | "
            f"{fmt_eur(checks.get('listing_price_eur'))} | {shipping_text} | "
            f"{fmt_dkk(row.get('listing_total_dkk'))} | {fmt_dkk(row.get('purchase_budget_dkk'))} | {seller.replace('|', '/')} |"
        )

    lines += [
        "",
        "## V56 gate",
        "",
        "LISTING_REVIEW requires exact Cardmarket product ID, English, MT/NM, EU/EEA seller, a fresh concrete listing, explicit shipping-to-Denmark verification, known shipping cost, total price within the card budget, and an underlying V55 REVIEW.",
        "If Cardmarket's Article API confirms the listing but destination shipping is unavailable, the card remains LISTING_WATCH rather than being guessed into a purchase candidate.",
        "",
    ]
    return "\n".join(lines)
