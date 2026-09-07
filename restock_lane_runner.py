#!/usr/bin/env python3
"""Final Restock-channel ownership wrapper.

Tier A Pokemon RESTOCK events are owned by the dedicated fast/local lanes:
- HOT owns online restocks for Coolshop, Proshop, BR, Bilka and Foetex.
- Local Stock owns target-store restocks for BR, Bilka and Foetex.

The main scanner still fetches Tier A for state, Price Watch/History and new/
preorder discovery, but it no longer duplicates Tier A Pokemon RESTOCK alerts.
Tier A Lorcana remains on the main lane because HOT is Pokemon-only.
"""

import restock_v2_runner as base

_ORIGINAL_CHANNEL_POLICY = base.restock_v2_channel_alert_allowed


def _pokemon_headline(headline):
    upper = str(headline or "").upper().replace("POKÉMON", "POKEMON")
    return "[POKEMON]" in upper


def restock_lane_channel_alert_allowed(message, legacy_policy=None):
    lines = base._clean_lines(message)
    if lines:
        headline = lines[0]
        event = base._event_from_headline(headline)

        if (
            event == "RESTOCK"
            and base._is_tier_a_headline(headline)
            and _pokemon_headline(headline)
        ):
            return False

    return _ORIGINAL_CHANNEL_POLICY(
        message,
        legacy_policy=legacy_policy,
    )


def main():
    base.restock_v2_channel_alert_allowed = restock_lane_channel_alert_allowed
    base.main()


if __name__ == "__main__":
    main()
