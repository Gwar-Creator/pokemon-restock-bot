#!/usr/bin/env python3
"""Thin production runner for Restock V2 Discord routing.

The legacy scanner remains the data/fetch engine while channel policy is moved
out of its large module. The legacy file has executable startup code after its
START marker, so this runner loads definitions first, patches the channel gate,
and only then executes the startup section.
"""

import re
from pathlib import Path

from alert_policy import TIER_A_SOURCES, tier_b_signal_allowed
from faraos_parser_v2 import faraos_name_v2

SCANNER_FILE = Path(__file__).resolve().parent / "restock_bot_github.py"
START_MARKER = (
    "# =========================================================\n"
    "# START\n"
    "# ========================================================="
)

TIER_A_LABELS = {
    "coolshop": "COOLSHOP",
    "proshop": "PROSHOP",
    "br": "BR",
    "bilka": "BILKA",
    "foetex": "FØTEX",
}

# Faraos' top-level Pokemon category currently reports many products but only
# renders part of the catalogue in the repeated card structure used by the
# legacy parser. Scan the stable public sealed subcategories instead. Keep the
# parent pages first so existing IDs remain stable for products still visible
# there, while the granular feeds recover the missing catalogue rows.
FARAOS_V3_FEEDS = (
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon"),
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon/booster"),
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon/boosterdisplay"),
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon/pokemondisplays"),
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon/collectionbokse"),
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon/elitetrainerbox"),
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon/premiumcollection"),
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon/tins"),
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon/3-pak"),
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon/2-pack"),
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon/checklane"),
    ("LORCANA", "https://www.faraos.dk/games/kortspil/lorcana"),
    ("LORCANA", "https://www.faraos.dk/games/kortspil/lorcana/boosters"),
)

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


def restock_v2_channel_alert_allowed(message, legacy_policy=None):
    """Keep Tier A fast; make Tier B Discord output deliberately strict."""
    lines = _clean_lines(message)
    if not lines:
        return False

    headline = lines[0]
    event = _event_from_headline(headline)

    # Non-product operational output keeps the legacy decision until those
    # concerns are moved to their dedicated channels in a later cleanup.
    if event is None:
        return legacy_policy(message) if legacy_policy is not None else True

    if _is_tier_a_headline(headline):
        return True

    if len(lines) < 2:
        return False

    product_name = lines[1]
    return tier_b_signal_allowed(product_name, event=event)


def load_scanner_parts():
    source = SCANNER_FILE.read_text(encoding="utf-8")
    if START_MARKER not in source:
        raise RuntimeError("Kunne ikke finde START-markøren i restock_bot_github.py")
    definitions, startup = source.split(START_MARKER, 1)
    return definitions, startup


def _install_faraos_parser(namespace):
    legacy_name = namespace.get("_faraos_name")
    clean_text = namespace.get("woocommerce_clean_text")
    if legacy_name is None or clean_text is None:
        raise RuntimeError("Faraos parser-hook mangler forventede legacy-funktioner")

    def patched_faraos_name(card):
        return faraos_name_v2(card, legacy_name, clean_text)

    namespace["_faraos_name"] = patched_faraos_name
    namespace["FARAOS_FEEDS"] = FARAOS_V3_FEEDS


def main():
    definitions, startup = load_scanner_parts()
    namespace = {
        "__name__": "restock_v2_scanner",
        "__file__": str(SCANNER_FILE),
    }

    exec(compile(definitions, str(SCANNER_FILE), "exec"), namespace)
    legacy_policy = namespace["restock_channel_alert_allowed"]
    _install_faraos_parser(namespace)

    def channel_policy(message):
        return restock_v2_channel_alert_allowed(
            message,
            legacy_policy=legacy_policy,
        )

    namespace["restock_channel_alert_allowed"] = channel_policy
    exec(compile(startup, str(SCANNER_FILE), "exec"), namespace)


if __name__ == "__main__":
    main()
