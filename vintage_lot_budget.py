"""Conservative MANUAL vintage-lot budget worksheet; never generates BUY/BID alerts.

Inputs are explicitly verified evidence, not scraped assumptions or Tradera
title matches. All money uses Decimal. No FX or comparable prices are fetched
or invented. Produces a *budget ceiling*, not a market valuation.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR

from vintage_finder_tradera import _safe_public_listing_url

REQUIRED_ATTESTATIONS = (
    "seller_reputation_checked",
    "english_cards_verified",
    "identities_verified",
    "front_back_photos_checked",
    "condition_verified",
    "authenticity_checked",
    "shipping_to_denmark_verified",
    "all_fees_verified",
    "eu_comparables_reviewed",
    "inventory_checked",
    "personal_cap_approved",
    "budget_available_confirmed",
)
ACCEPTED_INTEREST = {"KEEP", "SELL", "FILLER"}
MONEY_FIELDS = (
    "current_required_price_sek",
    "shipping_to_denmark_sek",
    "platform_fees_sek",
    "payment_fees_dkk",
    "sek_to_dkk_rate",
    "available_hobby_budget_dkk",
    "conservative_personal_cap_dkk",
)


def _dec(value, *, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, str, Decimal)):
        raise ValueError("Unverified numeric field")
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Unverified numeric field") from None
    if not amount.is_finite() or (amount < 0 if allow_zero else amount <= 0):
        raise ValueError("Invalid money amount")
    return amount


def _fresh(value, now, max_age):
    if not isinstance(value, str):
        return False
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        return False
    return now - max_age <= dt <= now


def _summary(status, reasons, **extra):
    return {
        "status": status,
        "missing_or_blocking": list(reasons),
        "buy_bid_signal": None,
        "discord_eligible": False,
        "notice": "Manual financial review only. No purchase, bid or market-value claim.",
        **extra,
    }


def evaluate_manual_lot(listing, evidence, now=None):
    """Compute an explicit affordability cap if *all* manual evidence exists.

    Even COMPLETE evidence does not authorize a purchase or notification.
    """
    if not isinstance(listing, dict) or not isinstance(evidence, dict):
        return _summary("MISSING_EVIDENCE", ["listing_or_evidence_missing"])
    listing_id = str(listing.get("id") or "").strip()
    if not listing_id.isdecimal() or not _safe_public_listing_url(listing.get("url")):
        return _summary("MISSING_EVIDENCE", ["untrusted_listing_identity"])
    if str(evidence.get("listing_id") or "").strip() != listing_id:
        return _summary("MISSING_EVIDENCE", ["listing_evidence_id_mismatch"])

    now = now or datetime.now(timezone.utc)
    missing = [f for f in REQUIRED_ATTESTATIONS if evidence.get(f) is not True]
    if not _fresh(evidence.get("reviewed_at"), now, timedelta(hours=6)):
        missing.append("fresh_manual_listing_review")
    if not _fresh(evidence.get("fx_checked_at"), now, timedelta(hours=24)):
        missing.append("verified_recent_exchange_rate")

    cards = evidence.get("card_details")
    if not isinstance(cards, list) or not cards:
        missing.append("verified_card_inventory")
    else:
        for card in cards:
            if not isinstance(card, dict) or any(
                not isinstance(card.get(field), str) or not card[field].strip()
                for field in ("name", "set", "number", "condition", "edition")
            ) or card.get("interest") not in ACCEPTED_INTEREST:
                missing.append("complete_card_level_review")
                break
    values = {}
    for field in MONEY_FIELDS:
        try:
            values[field] = _dec(
                evidence.get(field),
                allow_zero=field in ("shipping_to_denmark_sek", "platform_fees_sek",
                                     "payment_fees_dkk"),
            )
        except ValueError:
            missing.append("verified_" + field)
    if missing:
        return _summary("MISSING_EVIDENCE", sorted(set(missing)))

    selected = sum(c["interest"] == "KEEP" for c in cards)
    resell = sum(c["interest"] == "SELL" for c in cards)
    filler = sum(c["interest"] == "FILLER" for c in cards)
    if selected + resell == 0:
        return _summary("NOT_RELEVANT", ["no_identified_keeper_or_saleable_card"],
                        identified_cards=len(cards), filler_cards=filler)

    price = values["current_required_price_sek"]
    ship = values["shipping_to_denmark_sek"]
    platform = values["platform_fees_sek"]
    payment = values["payment_fees_dkk"]
    rate = values["sek_to_dkk_rate"]
    budget = values["available_hobby_budget_dkk"]
    personal_cap = values["conservative_personal_cap_dkk"]
    ceiling = min(budget, personal_cap)
    raw_total = (price + ship + platform) * rate + payment
    total = raw_total.quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    ceiling_bid = (((ceiling - payment) / rate) - ship - platform)
    max_bid = max(Decimal("0"), ceiling_bid.to_integral_value(rounding=ROUND_FLOOR))
    status = "MANUAL_FINANCIAL_REVIEW" if total <= ceiling and max_bid > 0 else "OVER_LIMIT"
    return _summary(
        status,
        [] if status == "MANUAL_FINANCIAL_REVIEW" else ["current_total_exceeds_verified_cap"],
        total_cost_dkk=str(total),
        verified_budget_dkk=str(budget),
        conservative_personal_cap_dkk=str(personal_cap),
        enforced_cap_dkk=str(ceiling),
        max_bid_sek=str(max_bid),
        verified_keep_cards=selected,
        proposed_sell_cards=resell,
        filler_cards=filler,
        identified_cards=len(cards),
        price_is_not_guaranteed="Auction price, FX and shipping may change; verify again before action.",
    )
