from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

import family_watch as fw

ACCESS_MARKER = "[FW_ACCESS]"
_COOP_STORES = {"365discount", "superbrugsen", "kvickly", "daglibrugsen", "brugsen"}

_ORIGINAL_EXTRACT = fw.extract_etilbudsavis_offer_dicts
_ORIGINAL_MATCHES = fw.matches_group


def _norm(value: Any) -> str:
    return fw.normalize_text(value)


def _store_from_raw(raw: dict[str, Any]) -> str:
    seller = raw.get("seller") or raw.get("business") or {}
    if isinstance(seller, dict):
        return str(seller.get("name") or "")
    return str(seller or "")


def _date_token(value: Any) -> str:
    parsed = fw.parse_timestamp(value)
    return parsed.isoformat() if parsed else ""


def _offer_match_key(raw: dict[str, Any]) -> tuple[str, str, str, str]:
    valid_until = raw.get("validThrough") or raw.get("priceValidUntil") or raw.get("availabilityEnds") or raw.get("validUntil")
    return (
        _norm(raw.get("name")),
        fw.canonical_store(_store_from_raw(raw)),
        _date_token(raw.get("validFrom") or raw.get("availabilityStarts")),
        _date_token(valid_until),
    )


def extract_embedded_product_dicts(html: str) -> list[dict[str, Any]]:
    """Extract eTilbudsavis' richer product objects from page hydration JSON.

    These objects include appPrice/membershipPrice and department metadata that
    are not consistently present in the JSON-LD Offer objects.
    """
    decoder = json.JSONDecoder()
    found: dict[str, dict[str, Any]] = {}
    for match in re.finditer(r'\{"publicId":', html):
        try:
            value, _ = decoder.raw_decode(html[match.start():])
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(value, dict):
            continue
        if not value.get("publicId") or not value.get("name"):
            continue
        if not isinstance(value.get("business"), dict):
            continue
        if not any(key in value for key in ("price", "appPrice", "membershipPrice", "validFrom", "publicationPublicId")):
            continue
        found[str(value["publicId"])] = value
    return list(found.values())


def infer_access_note(store: str, description: str, app_price: float | None, membership_price: float | None) -> str:
    text = _norm(description)
    canonical = fw.canonical_store(store)
    has_special_price = app_price is not None or membership_price is not None

    if "netto+" in text or "netto plus" in text or (canonical == "netto" and has_special_price):
        return "Netto+ app"
    if "lidl plus" in text or (canonical == "lidl" and has_special_price):
        return "Lidl Plus app/medlemskab"
    if canonical in _COOP_STORES and (has_special_price or "medlemspris" in text or "coop app" in text):
        return "Coop-medlemskab/app"
    if canonical == "matas" and (has_special_price or "club matas" in text):
        return "Club Matas"
    if "medlemspris" in text or "medlemskab" in text or membership_price is not None:
        return "medlemskab"
    if "gælder kun med" in text and "app" in text:
        return "app"
    if app_price is not None:
        return "app/medlemskab"
    return ""


def _with_access_metadata(raw_offer: dict[str, Any], product: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(raw_offer)
    regular_price = fw.maybe_float(product.get("price"))
    app_price = fw.maybe_float(product.get("appPrice"))
    membership_price = fw.maybe_float(product.get("membershipPrice"))
    description = str(product.get("description") or enriched.get("description") or "").strip()
    store = _store_from_raw(product) or _store_from_raw(enriched)
    access_note = infer_access_note(store, description, app_price, membership_price)

    special_price = app_price if app_price is not None else membership_price
    if special_price is not None:
        enriched["price"] = special_price

    meta: dict[str, Any] = {}
    if access_note:
        meta["access"] = access_note
    if special_price is not None and regular_price is not None and abs(special_price - regular_price) > 0.001:
        meta["regular_price"] = regular_price

    enriched["description"] = description
    if meta:
        enriched["description"] = (description + "\n" if description else "") + ACCESS_MARKER + json.dumps(meta, ensure_ascii=False, separators=(",", ":"))
    return enriched


def extract_etilbudsavis_offer_dicts(html: str) -> list[dict[str, Any]]:
    jsonld = _ORIGINAL_EXTRACT(html)
    products = extract_embedded_product_dicts(html)
    if not products:
        return jsonld

    exact: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    loose: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for product in products:
        exact[_offer_match_key(product)] = product
        loose.setdefault((_norm(product.get("name")), fw.canonical_store(_store_from_raw(product))), []).append(product)

    enriched: list[dict[str, Any]] = []
    for raw in jsonld:
        product = exact.get(_offer_match_key(raw))
        if product is None:
            candidates = loose.get((_norm(raw.get("name")), fw.canonical_store(_store_from_raw(raw))), [])
            if len(candidates) == 1:
                product = candidates[0]
        enriched.append(_with_access_metadata(raw, product) if product else raw)
    return enriched


def matches_group(product: dict[str, Any], group: dict[str, Any]) -> bool:
    if not _ORIGINAL_MATCHES(product, group):
        return False
    text = fw.combined_product_text(product)
    for token_set in group.get("include_any_sets", []):
        tokens = [_norm(token) for token in token_set if token]
        if tokens and not any(token in text for token in tokens):
            return False
    return True


def _access_from_description(description: str) -> tuple[str, dict[str, Any]]:
    if ACCESS_MARKER not in description:
        return description, {}
    clean, raw_meta = description.rsplit(ACCESS_MARKER, 1)
    try:
        meta = json.loads(raw_meta.strip())
    except json.JSONDecodeError:
        return description, {}
    return clean.rstrip(), meta if isinstance(meta, dict) else {}


def build_message(offer: fw.Offer, phase: str) -> str:
    if phase == "upcoming":
        heading = f"🟡 **KOMMENDE TILBUD — {offer.store}**"
    else:
        heading = f"🟢 **AKTUELT TILBUD — {offer.store}**"

    clean_description, meta = _access_from_description(offer.description)
    price_line = f"💰 **{fw.format_price(offer.price)}**"
    regular_price = fw.maybe_float(meta.get("regular_price"))
    if regular_price is not None:
        price_line += f" _(normalpris {fw.format_price(regular_price)})_"

    lines = [
        heading,
        f"**{offer.name}**",
        price_line,
        f"📅 Gælder: **{fw.format_period(offer)}**",
    ]
    if meta.get("access"):
        lines.append(f"🔐 Kræver: **{meta['access']}**")
    lines.append(f"🔎 Matcher: {offer.group_label}")

    if clean_description:
        short_description = clean_description[:220].strip()
        if short_description and _norm(short_description) != _norm(offer.name):
            lines.append(f"ℹ️ {short_description}")
    if offer.publication_label:
        lines.append(f"📖 {offer.publication_label}")
    if offer.url:
        lines.append(offer.url)
    return "\n".join(lines)


def patch_family_watch() -> None:
    fw.extract_etilbudsavis_offer_dicts = extract_etilbudsavis_offer_dicts
    fw.matches_group = matches_group
    fw.build_message = build_message


def main() -> int:
    patch_family_watch()
    return fw.main()


if __name__ == "__main__":
    raise SystemExit(main())
