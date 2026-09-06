import re
from datetime import date, datetime

# Restock V2 source tiers. Tier A is the fast lane; every other active source
# defaults to Tier B unless it is explicitly retired/data-only.
TIER_A_SOURCES = (
    "coolshop",
    "proshop",
    "br",
    "bilka",
    "foetex",
)

RETIRED_SOURCES = (
    "elgiganten",
    "cardstorecph",
    "zzgames",
)

# Set/product status is deliberately small and easy to tune. NEW is derived
# from release dates when a source exposes one. WATCH and ABUNDANT are explicit.
WATCH_TERMS = (
    "151",
    "prismatic evolutions",
    "first partner",
    "30th anniversary",
    "30th",
    "ascended heroes",
)

ABUNDANT_SETS = (
    "chaos rising",
    "pitch black",
)

NEW_SET_WINDOW_DAYS = 90

# High-signal products that are useful even from broad Tier B coverage.
TIER_B_CORE_MARKERS = (
    "booster bundle",
    "booster box",
    "booster display",
    "display box",
    "ultra-premium collection",
    "ultra premium collection",
    "super-premium collection",
    "super premium collection",
    " upc ",
    " spc ",
)

# WATCH/NEW sets may surface a wider selection of official sealed products.
TIER_B_WATCH_MARKERS = TIER_B_CORE_MARKERS + (
    "elite trainer box",
    " etb ",
    "premium collection",
    "special collection",
    "illustration collection",
    "illustration rare collection",
    "binder collection",
    "poster collection",
    "playmat collection",
    "collection box",
    " ex box ",
    " tin ",
    "mini tin",
    "poké ball tin",
    "poke ball tin",
    "booster pack",
    "sleeved booster",
    "sleeve booster",
)

# Chaos Rising and Pitch Black are abundant enough that ordinary pack-level
# products and ETBs create noise. Keep only higher-signal sealed formats.
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


def source_tier(source_key):
    key = str(source_key or "").strip().lower()
    if key in RETIRED_SOURCES:
        return "RETIRED"
    if key in TIER_A_SOURCES:
        return "A"
    return "B"


def _parse_release_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None


def set_status(name, series=None, release_date=None, today=None):
    text = _normalize(f"{name or ''} {series or ''}")

    if any(f" {set_name} " in text for set_name in ABUNDANT_SETS):
        return "ABUNDANT"

    if any(term in text for term in WATCH_TERMS):
        return "WATCH"

    released = _parse_release_date(release_date)
    if released is not None:
        current = today or date.today()
        if isinstance(current, datetime):
            current = current.date()
        age_days = (current - released).days
        # Pre-release and first 90 days count as NEW.
        if age_days <= NEW_SET_WINDOW_DAYS:
            return "NEW"

    return "NORMAL"


def abundant_set_signal_allowed(name, series=None):
    """Return False for low-signal Chaos Rising/Pitch Black products."""
    text = _normalize(f"{name or ''} {series or ''}")
    if set_status(name, series) != "ABUNDANT":
        return True
    return any(marker in text for marker in ABUNDANT_SET_HIGH_SIGNAL_MARKERS)


def tier_b_signal_allowed(
    name,
    series=None,
    *,
    event="RESTOCK",
    release_date=None,
):
    """Strict Discord gate for broad Tier B coverage."""
    event = str(event or "RESTOCK").strip().upper()
    text = _normalize(f"{name or ''} {series or ''}")
    status = set_status(name, series, release_date=release_date)

    if event in {"PRICE", "HEALTH", "EARLY_RADAR"}:
        return False

    if status == "ABUNDANT":
        return abundant_set_signal_allowed(name, series)

    if event in {"PREORDER", "FORUDBESTILLING"}:
        return True

    if status in {"WATCH", "NEW"}:
        return any(marker in text for marker in TIER_B_WATCH_MARKERS)

    return any(marker in text for marker in TIER_B_CORE_MARKERS)
