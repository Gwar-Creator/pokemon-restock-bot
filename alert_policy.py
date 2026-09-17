import re
from datetime import date, datetime

# Restock source classes.
# Tier A = broad retail fast lane.
# Tier B = broad backup retail; currently only Indeks Retail (Bog & ide/Legekaeden).
# SPECIALTY = specialist stores that remain useful for scan/state/price data but
# do not emit product-event Discord alerts.
TIER_A_SOURCES = (
    "coolshop",
    "proshop",
    "br",
    "bilka",
    "foetex",
)

BACKUP_RETAIL_SOURCES = (
    "indeks_retail",
)

RETIRED_SOURCES = (
    "elgiganten",
    "cardstorecph",
    "zzgames",
)

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

# Backup retail stays stricter than Tier A. Normal sets only surface the most
# decision-useful sealed formats; WATCH/NEW sets can surface the wider sealed
# range below.
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

TIER_B_PREORDER_MARKERS = TIER_B_CORE_MARKERS + (
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


def source_tier(source_key):
    """Return the alert class for one source key.

    Unknown active sources deliberately default to SPECIALTY, not Tier B. This
    makes new specialist sources fail closed for Discord until they are
    explicitly promoted to broad retail.
    """
    key = str(source_key or "").strip().lower()
    if key in RETIRED_SOURCES:
        return "RETIRED"
    if key in TIER_A_SOURCES:
        return "A"
    if key in BACKUP_RETAIL_SOURCES:
        return "B"
    return "SPECIALTY"


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
        if age_days <= NEW_SET_WINDOW_DAYS:
            return "NEW"

    return "NORMAL"


def abundant_set_signal_allowed(name, series=None):
    text = _normalize(f"{name or ''} {series or ''}")
    if set_status(name, series) != "ABUNDANT":
        return True
    return any(marker in text for marker in ABUNDANT_SET_HIGH_SIGNAL_MARKERS)


def tier_a_signal_allowed(
    name,
    series=None,
    *,
    event="RESTOCK",
    release_date=None,
):
    """Fast-lane gate for the five broad Tier A retailers."""
    event = str(event or "RESTOCK").strip().upper()
    status = set_status(name, series, release_date=release_date)

    if event in {"PRICE", "HEALTH", "EARLY_RADAR"}:
        return False

    if status == "ABUNDANT":
        return abundant_set_signal_allowed(name, series)

    return True


def backup_retail_signal_allowed(
    name,
    series=None,
    *,
    event="RESTOCK",
    release_date=None,
):
    """Strict product gate for the broad Tier B backup-retail lane."""
    event = str(event or "RESTOCK").strip().upper()
    text = _normalize(f"{name or ''} {series or ''}")
    status = set_status(name, series, release_date=release_date)

    if event in {"PRICE", "HEALTH", "EARLY_RADAR"}:
        return False

    if status == "ABUNDANT":
        return abundant_set_signal_allowed(name, series)

    if status in {"WATCH", "NEW"}:
        return any(marker in text for marker in TIER_B_WATCH_MARKERS)

    if event in {"PREORDER", "FORUDBESTILLING"}:
        return any(marker in text for marker in TIER_B_PREORDER_MARKERS)

    return any(marker in text for marker in TIER_B_CORE_MARKERS)


def tier_b_signal_allowed(
    name,
    series=None,
    *,
    event="RESTOCK",
    release_date=None,
):
    """Legacy specialist gate: specialist stores are data-only for Discord.

    Existing Wave 1-4 and legacy main-scanner callers still use this function.
    Returning False centrally mutes NEW/PREORDER/RESTOCK from specialist stores
    without disabling their scanning, source health, state or price data.
    """
    return False
