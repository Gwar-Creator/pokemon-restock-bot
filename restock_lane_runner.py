#!/usr/bin/env python3
"""Final Restock-channel ownership wrapper.

Tier A Pokemon RESTOCK events are owned by the dedicated fast/local lanes:
- HOT owns online restocks for Coolshop, Proshop, BR, Bilka and Foetex.
- Local Stock owns target-store restocks for BR, Bilka and Foetex.

Wave 4 product events are owned by the dedicated Tier B Wave 4 live lane:
Vaulted, Pokedexet, Pokemonportalen, TCGBruuS and Pokemon Plaza. The main scanner
still fetches these shops for shared state/Price data but must not duplicate
NEW/PREORDER/RESTOCK alerts from them.
"""

import restock_v2_runner as base

_ORIGINAL_CHANNEL_POLICY = base.restock_v2_channel_alert_allowed

WAVE4_LABELS = (
    "VAULTED",
    "POKEDEXET",
    "POKEMONPORTALEN",
    "POKEMON PORTALEN",
    "TCGBRUUS",
    "TCG BRUUS",
    "POKEMON PLAZA",
)


def _pokemon_headline(headline):
    upper = str(headline or "").upper().replace("POKÉMON", "POKEMON")
    return "[POKEMON]" in upper


def _wave4_headline(headline):
    upper = str(headline or "").upper().replace("É", "E")
    return any(label in upper for label in WAVE4_LABELS)


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

        # Wave 4 has its own live transition/baseline handling. Main still scans
        # these sources, but all product-event alert ownership is suppressed here
        # to guarantee one Discord owner per source.
        if event in {"NEW", "PREORDER", "RESTOCK"} and _wave4_headline(headline):
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
