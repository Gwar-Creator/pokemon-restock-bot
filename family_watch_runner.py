from __future__ import annotations

import json
import re
from copy import deepcopy
from html import unescape
from typing import Any

import family_watch as fw

ACCESS_MARKER = "[FW_ACCESS]"
AGG_MARKER = "[FW_AGG]"
_COOP_STORES = {"365discount", "superbrugsen", "kvickly", "daglibrugsen", "brugsen"}

_ORIGINAL_EXTRACT = fw.extract_etilbudsavis_offer_dicts
_ORIGINAL_MATCHES = fw.matches_group
_ORIGINAL_LOVBJERG = fw.collect_lovbjerg_offers
_ORIGINAL_COLLECT = fw.collect_offers


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


def _is_rich_offer_dict(value: dict[str, Any]) -> bool:
    return bool(
        value.get("publicId")
        and value.get("name")
        and isinstance(value.get("business"), dict)
        and any(
            key in value
            for key in (
                "price",
                "appPrice",
                "membershipPrice",
                "validFrom",
                "publicationPublicId",
            )
        )
    )


def _collect_rich_offer_dicts(value: Any, found: dict[str, dict[str, Any]]) -> None:
    if isinstance(value, dict):
        if _is_rich_offer_dict(value):
            found[str(value["publicId"])] = value
        for child in value.values():
            _collect_rich_offer_dicts(child, found)
    elif isinstance(value, list):
        for child in value:
            _collect_rich_offer_dicts(child, found)


def extract_embedded_product_dicts(html: str) -> list[dict[str, Any]]:
    """Extract eTilbudsavis' richer offer data from <app-data> hydration JSON."""
    found: dict[str, dict[str, Any]] = {}

    for match in re.finditer(r"<app-data\b[^>]*>(.*?)</app-data>", html, flags=re.I | re.S):
        payload_text = unescape(match.group(1)).strip()
        if not payload_text:
            continue
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            continue
        _collect_rich_offer_dicts(payload, found)

    decoder = json.JSONDecoder()
    for match in re.finditer(r'\{"publicId":', html):
        try:
            value, _ = decoder.raw_decode(html[match.start():])
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(value, dict) and _is_rich_offer_dict(value):
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
    if canonical in _COOP_STORES and (has_special_price or "medlemspris" in text or "medlemskab" in text or "coop app" in text):
        return "Coop-medlemskab/app"
    if canonical == "matas" and (has_special_price or "club matas" in text):
        return "Club Matas"
    if "medlemspris" in text or "medlemskab" in text or membership_price is not None:
        return "medlemskab"
    if ("gaelder kun med" in text or "kun med" in text) and "app" in text:
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
        enriched.append(_with_access_metadata(raw, product or raw))
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


def config_for_lovbjerg(config: dict[str, Any]) -> dict[str, Any]:
    filtered = deepcopy(config)
    filtered["watch_groups"] = [
        group for group in config.get("watch_groups", []) if not group.get("skip_lovbjerg_direct")
    ]
    return filtered


def collect_lovbjerg_offers(config: dict[str, Any], session: Any, now: Any = None):
    return _ORIGINAL_LOVBJERG(config_for_lovbjerg(config), session, now=now)


def _group_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(group.get("id")): group for group in config.get("watch_groups", []) if group.get("id")}


def _store_allowed_for_group(offer: fw.Offer, group: dict[str, Any]) -> bool:
    allowed = {fw.canonical_store(store) for store in group.get("allowed_stores", []) if store}
    if not allowed:
        return True
    return fw.canonical_store(offer.store) in allowed


def _extract_size_ranges(offers: list[fw.Offer]) -> list[str]:
    found: list[str] = []
    for offer in offers:
        text = f"{offer.name} {offer.description}"
        for match in re.findall(r"\b\d{2,3}\s*[-–]\s*\d{2,3}\s*cm\b", text, flags=re.I):
            clean = re.sub(r"\s+", "", match).replace("-", "–")
            clean = clean.replace("cm", " cm")
            if clean not in found:
                found.append(clean)
    return found[:4]


def _matches_highlight(offer: fw.Offer, terms: list[str]) -> bool:
    text = _norm(f"{offer.name} {offer.description}")
    for raw_term in terms:
        term = _norm(raw_term)
        if not term:
            continue
        if term == "uld":
            # Match uld, uldbody, uldblanding etc., but not unrelated words like guld.
            if re.search(r"(?<![a-z0-9])uld", text):
                return True
            continue
        if term in text:
            return True
    return False


def _aggregate_group_offers(offers: list[fw.Offer], group: dict[str, Any]) -> list[fw.Offer]:
    if group.get("aggregate") != "store_period":
        return offers

    buckets: dict[tuple[str, str, str], list[fw.Offer]] = {}
    for offer in offers:
        key = (
            fw.canonical_store(offer.store),
            offer.valid_from.isoformat(),
            offer.valid_until.isoformat(),
        )
        buckets.setdefault(key, []).append(offer)

    aggregated: list[fw.Offer] = []
    for (store_key, start, end), items in buckets.items():
        items = sorted(items, key=lambda o: (o.price if o.price is not None else 10**9, o.name))
        names: list[str] = []
        access_notes: list[str] = []
        for item in items:
            if item.name not in names:
                names.append(item.name)
            _, item_meta = _access_from_description(item.description)
            note = str(item_meta.get("access") or "")
            if note and note not in access_notes:
                access_notes.append(note)

        highlight_terms = [str(value) for value in group.get("highlight_terms", []) if value]
        highlighted = [item for item in items if _matches_highlight(item, highlight_terms)]
        highlighted_names: list[str] = []
        for item in highlighted:
            if item.name not in highlighted_names:
                highlighted_names.append(item.name)

        prices = [item.price for item in items if item.price is not None]
        meta = {
            "count": len(items),
            "items": names[:6],
            "min_price": min(prices) if prices else None,
            "max_price": max(prices) if prices else None,
            "sizes": _extract_size_ranges(items),
            "access": access_notes,
            "highlight_label": str(group.get("highlight_label") or ""),
            "highlight_count": len(highlighted),
            "highlight_items": highlighted_names[:6],
        }
        first = items[0]
        aggregate_id = f"{group['id']}:{store_key}:{start}:{end}"
        # Keep the old key when no highlight is present, but allow one extra
        # alert if a high-signal item (e.g. wool) appears later in the period.
        if highlighted:
            aggregate_id += ":highlight"
        aggregated.append(
            fw.Offer(
                source="family_watch_aggregate",
                group_id=first.group_id,
                group_label=first.group_label,
                store=first.store,
                name="Børnetøj i tilbudsavisen",
                description=AGG_MARKER + json.dumps(meta, ensure_ascii=False, separators=(",", ":")),
                price=min(prices) if prices else None,
                valid_from=first.valid_from,
                valid_until=first.valid_until,
                offer_id=aggregate_id,
                publication_id="grouped",
                publication_label="",
                url=first.url,
                image="",
            )
        )
    return aggregated


def collect_offers(config: dict[str, Any], session: Any, now: Any = None):
    offers, errors = _ORIGINAL_COLLECT(config, session, now=now)
    max_days = int(config.get("max_offer_days", 45))
    groups = _group_map(config)

    filtered: list[fw.Offer] = []
    skipped_long = 0
    skipped_store = 0
    for offer in offers:
        duration_days = (offer.valid_until - offer.valid_from).total_seconds() / 86400
        if max_days > 0 and duration_days > max_days:
            skipped_long += 1
            continue
        group = groups.get(offer.group_id, {})
        if not _store_allowed_for_group(offer, group):
            skipped_store += 1
            continue
        filtered.append(offer)

    final: list[fw.Offer] = []
    for group_id, group in groups.items():
        group_offers = [offer for offer in filtered if offer.group_id == group_id]
        final.extend(_aggregate_group_offers(group_offers, group))

    known_ids = set(groups)
    final.extend(offer for offer in filtered if offer.group_id not in known_ids)

    if skipped_long:
        print(f"Family Watch sanity: skipped {skipped_long} long-running catalogue offers (> {max_days} days)")
    if skipped_store:
        print(f"Family Watch sanity: skipped {skipped_store} offers outside group-specific store rules")

    return sorted(
        final,
        key=lambda o: (
            0 if fw.offer_phase(o, now) == "current" else 1,
            o.valid_from,
            o.group_label,
            o.price if o.price is not None else 10**9,
            o.store,
        ),
    ), errors


def _access_from_description(description: str) -> tuple[str, dict[str, Any]]:
    if ACCESS_MARKER not in description:
        return description, {}
    clean, raw_meta = description.rsplit(ACCESS_MARKER, 1)
    try:
        meta = json.loads(raw_meta.strip())
    except json.JSONDecodeError:
        return description, {}
    return clean.rstrip(), meta if isinstance(meta, dict) else {}


def _aggregate_meta(description: str) -> dict[str, Any]:
    if not description.startswith(AGG_MARKER):
        return {}
    try:
        value = json.loads(description[len(AGG_MARKER):])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _format_price_range(meta: dict[str, Any]) -> str:
    low = fw.maybe_float(meta.get("min_price"))
    high = fw.maybe_float(meta.get("max_price"))
    if low is None and high is None:
        return "pris ikke oplyst"
    if high is None or low == high:
        return fw.format_price(low)
    return f"{fw.format_price(low)}–{fw.format_price(high)}"


def build_message(offer: fw.Offer, phase: str) -> str:
    aggregate = _aggregate_meta(offer.description)
    if aggregate:
        heading = (
            f"🟡 **KOMMENDE TØJTILBUD — {offer.store}**"
            if phase == "upcoming"
            else f"🟢 **AKTUELT TØJTILBUD — {offer.store}**"
        )
        lines = [
            heading,
            "**Børnetøj i tilbudsavisen**",
        ]
        highlight_count = int(aggregate.get("highlight_count") or 0)
        highlight_label = str(aggregate.get("highlight_label") or "").strip()
        highlight_items = [str(value) for value in aggregate.get("highlight_items", []) if value]
        if highlight_count:
            label = highlight_label or "SÆRLIGT FUND"
            lines.append(f"🧶🔥 **{label}: {highlight_count} tilbud**")
            if highlight_items:
                lines.append("🧶 " + " · ".join(highlight_items[:5]))

        lines.extend([
            f"👕 **{int(aggregate.get('count') or 0)} relevante tøjtilbud samlet**",
            f"💰 **{_format_price_range(aggregate)}**",
            f"📅 Gælder: **{fw.format_period(offer)}**",
        ])
        sizes = [str(value) for value in aggregate.get("sizes", []) if value]
        if sizes:
            lines.append("📏 Størrelser: " + " · ".join(sizes))
        names = [str(value) for value in aggregate.get("items", []) if value]
        if names:
            lines.append("🧥 Fx: " + " · ".join(names[:5]))
        access = [str(value) for value in aggregate.get("access", []) if value]
        if access:
            lines.append("🔐 Nogle tilbud kræver: **" + " / ".join(access) + "**")
        if offer.url:
            lines.append(offer.url)
        return "\n".join(lines)

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
    fw.collect_lovbjerg_offers = collect_lovbjerg_offers
    fw.collect_offers = collect_offers
    fw.build_message = build_message


def main() -> int:
    patch_family_watch()
    return fw.main()


if __name__ == "__main__":
    raise SystemExit(main())