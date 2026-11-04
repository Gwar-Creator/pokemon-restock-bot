#!/usr/bin/env python3
"""Final Restock-channel ownership wrapper.

Tier A RESTOCK events are owned by the dedicated fast/local lanes:
- HOT owns online restocks for Coolshop, Proshop, BR, Bilka, Foetex, Boozt and Magasin.
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


def _wave4_headline(headline):
    upper = str(headline or "").upper().replace("É", "E")
    return any(label in upper for label in WAVE4_LABELS)


def restock_lane_channel_alert_allowed(message, legacy_policy=None):
    lines = base._clean_lines(message)
    if lines:
        headline = lines[0]
        event = base._event_from_headline(headline)

        # HOT owns all online Tier A RESTOCK events, and Local Stock owns
        # selected Salling physical restocks. The main Restock lane must not
        # create a duplicate or a misleading green legacy embed merely
        # because a source omitted the [POKÉMON] tag. Lorcana is muted in
        # send_discord regardless; no need to exempt it here.
        if event == "RESTOCK" and base._is_tier_a_headline(headline):
            return False

        # The main scanner is now data/Price-Watch first. Specialist and backup
        # retail product events stay out of the Restock channel; only Tier A
        # discovery and preorders can pass through this legacy lane.
        if (
            event in {"NEW", "PREORDER", "RESTOCK"}
            and not base._is_tier_a_headline(headline)
        ):
            return False

        # Wave 4 remains explicitly owned outside the main scanner if those
        # jobs are re-enabled later.
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
