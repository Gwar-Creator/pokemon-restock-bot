"""Inert Vintage Finder shortlist: relevant lots, not verified BUY/BID deals.

Seller titles are untrusted. Never infer language, condition, card identity,
DK shipping or value from text. No network, state writes or Discord here.
"""
import hashlib
import re
from datetime import datetime, timedelta, timezone

from vintage_finder_tradera import _norm, _safe_public_listing_url
from vintage_tradera_quality import classify_title

LOT_WORDS = (
    "samling", "samlingar", "kortsamling", "barndomssamling",
    "collection", "lot", "kortlot", "album", "binder", "mapp",
    "mappe", "parm", "parmar", "blandat", "blandade", "kortpaket",
)
OLD_WORDS = (
    "gammal", "gamla", "gammel", "gamle", "aldre", "barndom", "barndomen", "vintage",
    "wotc", "ex series", "old cards", "old collection",
    "1999", "2000", "2001", "2002", "2003", "2004",
)
EXCLUDE_WORDS = (
    "lorcana", "proxy", "orica", "fake", "replica", "repack",
    "mystery", "sealed", "booster", "etb", "display",
    "graded", "psa", "cgc", "code card", "digital",
    "bulk", "bulk only", "bulk kort", "bulk cards", "1000 kort",
    "1000 cards", "vmax", "vstar", "prismatic",
    "surging sparks", "destined rivals", "paldea",
    "scarlet", "violet", "pokemon 151", "mega evolution",
    "pris per kort", "pris per styck", "individuella priser",
)
SPECIAL_SINGLE = ("holo", "reverse", "stamped", "gold star", "shining",
                  "crystal", "1st edition", "first edition", "delta species")
SPECIAL_SETS = ("expedition", "aquapolis", "skyridge", "neo destiny",
                "ex ruby", "ex sandstorm", "ex dragon", "gym heroes",
                "gym challenge", "team rocket")
BINDER_WORDS = ("album", "binder", "mapp", "mappe", "parm", "parmar")
TIERS = {"VINTAGE_LOT": 0, "OLD_COLLECTION": 1,
         "VINTAGE_SINGLE": 2, "POSSIBLE_BINDER": 3}
MAX_PER_RUN = 3
MAX_PER_DAY = 3
MAX_PER_WEEK = 8
SEEN_DAYS = 45


def has_word(text, words):
    return any(re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text)
               for word in words)


def pick_title(row):
    """Select only potential vintage lots; never call them good buys."""
    if not isinstance(row, dict):
        return None
    ident, title = row.get("id"), row.get("shortDescription")
    url = _safe_public_listing_url(row.get("itemUrl"))
    if (type(ident) not in (int, str) or not str(ident).isdigit()
            or not isinstance(title, str) or not url):
        return None
    s = _norm(title)
    if "pokemon" not in s or has_word(s, EXCLUDE_WORDS):
        return None
    category, reason = classify_title(title)
    if category == "EXCLUDED" and reason != "no convincing vintage signal":
        return None
    lot = has_word(s, LOT_WORDS)
    old = has_word(s, OLD_WORDS)
    vintage = category == "TITLE_VINTAGE"
    if lot and vintage:
        tier = "VINTAGE_LOT"
    elif old and (lot or "kort" in s or "cards" in s):
        tier = "OLD_COLLECTION"
    elif vintage and (has_word(s, SPECIAL_SINGLE)
                      or has_word(s, SPECIAL_SETS)
                      or has_word(s, ("dark", "light"))):
        tier = "VINTAGE_SINGLE"
    elif has_word(s, BINDER_WORDS):
        tier = "POSSIBLE_BINDER"
    else:
        return None
    return {
        "id": str(ident),
        "title": re.sub(r"[\x00-\x1f\x7f]", " ", title).strip()[:180],
        "url": url,
        "tier": tier,
        "verification": "UNVERIFIED",
    }


def _date(text):
    if not isinstance(text, str):
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None
    except ValueError:
        return None


def propose_shortlist(rows, state=None, now=None):
    """Deduped shortlist for INTERNAL review. No Discord send even if selected.

    First scan establishes baseline; no historical flood.
    State must be persisted by a separate safe workflow if ever scheduled.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    state = state if isinstance(state, dict) else {}
    old_seen = state.get("seen", {})
    old_sent = state.get("sent_at", [])
    old_seen = old_seen if isinstance(old_seen, dict) else {}
    old_sent = old_sent if isinstance(old_sent, list) else []
    seen = {str(k): str(v) for k, v in old_seen.items()
            if _date(v) and _date(v) >= now - timedelta(days=SEEN_DAYS)}
    sent = [str(v) for v in old_sent
            if _date(v) and now - timedelta(days=7) <= _date(v) <= now]
    candidates = {}
    for row in rows:
        item = pick_title(row)
        if item:
            candidates[item["id"]] = item

    first_run = state.get("initialized") is not True
    daily = sum(_date(x).date() == now.date() for x in sent)
    cap = min(MAX_PER_RUN, max(0, MAX_PER_DAY - daily),
              max(0, MAX_PER_WEEK - len(sent)))
    new_items = [x for x in candidates.values() if x["id"] not in seen]
    proposed = [] if first_run else sorted(
        new_items,
        key=lambda x: (
            TIERS.get(x["tier"], 99),
            hashlib.sha256(x["id"].encode()).hexdigest(),
        )
    )[:cap]
    stamp = now.isoformat().replace("+00:00", "Z")
    seen.update({ident: stamp for ident in candidates})
    # Reservations reflect shortlists, NOT successfully published messages.
    sent.extend([stamp] * len(proposed))
    return {
        "initialized": True, "version": 1,
        "seen": seen, "sent_at": sent, "last_checked_at": stamp,
    }, proposed, first_run


def internal_preview(item):
    """May be printed or saved privately; must NOT be posted to #marketplace-deals."""
    return {
        "title": item["title"],
        "url": item["url"],
        "reason": item["tier"],
        "status": "UNVERIFIED_MANUAL_REVIEW",
        "buy_bid_signal": None,
        "discord_eligible": False,
    }
