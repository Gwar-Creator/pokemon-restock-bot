"""Inert Discord preview formatter for Tradera vintage candidates.

Intended destination is the EXISTING #marketplace-deals channel.
This module never makes network calls or sends a webhook.
An interesting listing is NOT a verified deal or buy recommendation.
"""
from vintage_finder_tradera import _safe_public_listing_url

MAX_DESCRIPTION = 4000
MAX_EMBEDS = 4


def candidate_embed(candidate):
    """Conservative Discord V2-compatible card for manual review only."""
    if not isinstance(candidate, dict):
        raise ValueError("Candidate must be a dictionary")

    title = str(candidate.get("title") or "Ukendt annonce").strip()[:190]
    priority = candidate.get("priority")
    if priority not in ("REVIEW", "REVIEW_HIGH"):
        raise ValueError("Only reviewed vintage candidate tiers are supported")
    url = _safe_public_listing_url(candidate.get("url"))
    # Unknown listing URL is not a usable Discord alert: do not invent one.
    if not url:
        raise ValueError("Verified public Tradera listing URL is required")
    notes = "Manuel gennemgang – ikke et bekræftet godt køb."
    category = "Muligt særligt vintagefund" if priority == "REVIEW_HIGH" else "Mulig ældre samling"
    fields = [
        {"name": "KATEGORI", "value": category, "inline": True},
        {"name": "PRIS / FRAGT", "value": "Samlet pris til Danmark er ikke verificeret", "inline": False},
        {"name": "KORTENE", "value": "Indhold, sprog, stand og ægthed er ikke verificeret", "inline": False},
        {"name": "VURDERING", "value": "Intet køb eller bud uden manuel kontrol", "inline": False},
    ]
    return {
        "title": f"TRADERA · TIL GENNEMGANG · {title}"[:256],
        "url": url,
        "description": notes,
        "color": 0x95A5A6,
        "fields": fields,
        "footer": {"text": "Vintage Finder · #marketplace-deals · Ikke et købsråd"},
    }


def preview_payload(candidates, limit=MAX_EMBEDS):
    """Return a draft payload, NOT a network call or a publishing action."""
    requested = min(max(int(limit), 0), MAX_EMBEDS)
    if not requested:
        return {"username": "MasterBot", "allowed_mentions": {"parse": []}, "embeds": []}
    embeds = []
    used = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        identifier = str(candidate.get("id") or "").strip()
        if not identifier or identifier in used:
            continue
        try:
            embed = candidate_embed(candidate)
        except ValueError:
            continue
        used.add(identifier)
        embeds.append(embed)
        if len(embeds) >= requested:
            break
    return {
        "username": "MasterBot",
        "allowed_mentions": {"parse": []},
        "embeds": embeds,
    }
