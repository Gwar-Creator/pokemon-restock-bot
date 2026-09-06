import re

SEALED_MARKERS = (
    "booster",
    "elite trainer box",
    " etb",
    "collection",
    " tin",
    "blister",
    "display",
    "starter",
    "trove",
)


def _clean_candidate(value):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"^[-–—]?\s*\d+\s*%\s*", "", text)
    text = re.sub(
        r"\s+Pokemon\s*:\s*Release\s+d\.\s*\d{1,2}/\d{1,2}.*$",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"\s+(?:Pokemon|Pokémon|Disney Lorcana|Lorcana)\s*$", "", text, flags=re.I)
    return text.strip(" -–—")


def _looks_like_sealed_name(value):
    low = f" {str(value or '').lower()} "
    return any(marker in low for marker in SEALED_MARKERS)


def faraos_name_v2(card, legacy_name, clean_text):
    """Recover split Faraos titles without churning already-good product names.

    Faraos sometimes renders the set and product type as separate title lines,
    e.g. ``Journey Together`` + ``Booster``. The legacy parser returns only the
    first line and then rejects the product as non-sealed. Keep legacy names
    whenever they already describe a sealed product, and otherwise build the
    complete title from the card text before the first DKK price marker.
    """
    old_name = _clean_candidate(legacy_name(card))
    if old_name and _looks_like_sealed_name(old_name):
        return old_name

    card_text = clean_text(card.get_text(" ", strip=True))
    before_price = re.split(r"\bDKK\b", card_text, maxsplit=1, flags=re.I)[0]
    candidate = _clean_candidate(before_price)

    if candidate and _looks_like_sealed_name(candidate):
        return candidate

    return old_name or candidate
