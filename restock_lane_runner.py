#!/usr/bin/env python3
"""Final Restock-channel ownership wrapper.

Tier A Pokemon RESTOCK events are owned by the dedicated fast/local lanes:
- HOT owns online restocks for Coolshop, Proshop, BR, Bilka and Foetex.
- Local Stock owns target-store restocks for BR, Bilka and Foetex.

The main scanner still fetches Tier A for state, Price Watch/History and new/
preorder discovery, but it no longer duplicates Tier A Pokemon RESTOCK alerts.
Tier A Lorcana remains on the main lane because HOT is Pokemon-only.

Pokemonportalen currently marks the entire preorder category as preorder,
including sold-out placeholder products. Until Wave 4 owns a parser that can
verify buyability, main-lane PREORDER alerts from Pokemonportalen are suppressed.
This is intentionally fail-closed: ordinary restock/new events remain unchanged.
"""

import restock_v2_runner as base

_ORIGINAL_CHANNEL_POLICY = base.restock_v2_channel_alert_allowed


def _pokemon_headline(headline):
    upper = str(headline or "").upper().replace("POKÉMON", "POKEMON")
    return "[POKEMON]" in upper


def _pokemonportalen_headline(headline):
    upper = str(headline or "").upper().replace("É", "E")
    return "POKEMONPORTALEN" in upper or "POKEMON PORTALEN" in upper


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

        # Pokemonportalen's preorder category contains sold-out placeholders.
        # Do not surface PREORDER from this legacy lane until Wave 4 verifies
        # that the product is actually buyable. This prevents false alerts.
        if event == "PREORDER" and _pokemonportalen_headline(headline):
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
