import re

# Chaos Rising and Pitch Black are abundant enough that ordinary pack-level
# products and ETBs create noise. Keep only higher-signal sealed formats.
ABUNDANT_SETS = (
    "chaos rising",
    "pitch black",
)

ABUNDANT_SET_HIGH_SIGNAL_MARKERS = (
    "booster bundle",
    "booster box",
    "booster display",
    "display box",
    "premium collection",
    "ultra-premium collection",
    "ultra premium collection",
    "special collection",
    "illustration collection",
    "illustration rare collection",
    "binder collection",
    "poster collection",
    "playmat collection",
    "collection box",
    " ex box ",
    " upc ",
    " tin ",
    "mini tin",
    "poké ball tin",
    "poke ball tin",
)


def _normalize(value):
    text = str(value or "").lower().replace("pokémon", "pokemon")
    text = text.replace("–", " ").replace("—", " ").replace("-", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return f" {text} "


def abundant_set_signal_allowed(name, series=None):
    """Return False for low-signal Chaos Rising/Pitch Black products.

    This is intentionally default-deny inside the two abundant sets: ordinary
    boosters, 1-packs, multi-pack blisters, portfolios and ETBs stay silent
    even when a retailer uses an unusual title such as only "samlekort".
    Booster bundles/boxes/displays, collections and tins still pass.
    """
    text = _normalize(f"{name or ''} {series or ''}")
    if not any(f" {set_name} " in text for set_name in ABUNDANT_SETS):
        return True

    return any(marker in text for marker in ABUNDANT_SET_HIGH_SIGNAL_MARKERS)
