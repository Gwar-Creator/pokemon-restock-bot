#!/usr/bin/env python3
"""Thin production runner for Restock V2 Discord routing.

The legacy scanner remains the data/fetch engine while channel policy is moved
out of its large module. Tier A is always allowed through the Restock channel;
Tier B uses the strict central policy. This keeps broad ingestion separate from
Discord noise without duplicating retailer parsers.
"""

import re

import restock_bot_github as bot
from alert_policy import TIER_A_SOURCES, tier_b_signal_allowed

LEGACY_CHANNEL_POLICY = bot.restock_channel_alert_allowed

TIER_A_LABELS = {
    "coolshop": "COOLSHOP",
    "proshop": "PROSHOP",
    "br": "BR",
    "bilka": "BILKA",
    "foetex": "FØTEX",
}

if tuple(TIER_A_LABELS) != tuple(TIER_A_SOURCES):
    raise RuntimeError("Restock runner er ikke synkron med TIER_A_SOURCES")


def _clean_lines(message):
    return [
        line.replace("**", "").strip()
        for line in str(message or "").splitlines()
        if line.strip()
    ]


def _event_from_headline(headline):
    upper = str(headline or "").upper()
    if "FORUDBESTILLING" in upper or "PREORDER" in upper:
        return "PREORDER"
    if "RESTOCK" in upper:
        return "RESTOCK"
    if "NYT" in upper or "NY " in upper:
        return "NEW"
    return None


def _is_tier_a_headline(headline):
    upper = str(headline or "").upper()
    return any(
        re.search(rf"\b{re.escape(label)}\b", upper)
        for label in TIER_A_LABELS.values()
    )


def restock_v2_channel_alert_allowed(message):
    """Keep Tier A fast; make Tier B Discord output deliberately strict."""
    lines = _clean_lines(message)
    if not lines:
        return False

    headline = lines[0]
    event = _event_from_headline(headline)

    # Non-product operational output keeps the legacy decision until those
    # concerns are moved to their dedicated channels in a later cleanup.
    if event is None:
        return LEGACY_CHANNEL_POLICY(message)

    if _is_tier_a_headline(headline):
        return True

    if len(lines) < 2:
        return False

    product_name = lines[1]
    return tier_b_signal_allowed(product_name, event=event)


def main():
    bot.restock_channel_alert_allowed = restock_v2_channel_alert_allowed
    bot.main()


if __name__ == "__main__":
    main()
