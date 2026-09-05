from __future__ import annotations

import concurrent.futures
import json
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import family_watch as fw
import family_watch_runner as runner


COOP_SITES = {
    "kvickly": ("Kvickly", "https://kvickly.coop.dk/avis/"),
    "superbrugsen": ("SuperBrugsen", "https://superbrugsen.coop.dk/avis/"),
    "daglibrugsen": ("Dagli Brugsen", "https://brugsen.coop.dk/avis/"),
    "365discount": ("365discount", "https://365discount.coop.dk/365avis/"),
}

OFFICIAL_STORE_URLS = {
    "netto": "https://netto.dk/netto-avisen/",
    "rema1000": "https://rema1000.dk/avis",
    "lidl": "https://www.lidl.dk/c/tilbudsavis/s10013730",
    "lovbjerg": "https://www.lovbjerg.dk/avis/denne-uges-avis/vejen",
    "matas": "https://www.matas.dk/tilbud",
    "kvickly": "https://kvickly.coop.dk/avis/",
    "bilka": "https://www.bilka.dk/bilkaavisen/",
    "superbrugsen": "https://superbrugsen.coop.dk/avis/",
    "daglibrugsen": "https://brugsen.coop.dk/avis/",
    "brugsen": "https://brugsen.coop.dk/avis/",
    "365discount": "https://365discount.coop.dk/365avis/",
}

COOP_CANONICAL_STORES = set(COOP_SITES)
BASE_SOURCE_COLLECT = runner._ORIGINAL_COLLECT
BASE_BUILD_MESSAGE = runner.build_message


def _normalize_label(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _parse_offer_label(label: str) -> tuple[str, float | None]:
    clean = _normalize_label(label)
    match = re.match(r"^(.*?),\s*DKK\s*([0-9]+(?:[.,][0-9]+)?)\s*$", clean, re.I)
    if not match:
        return clean, None
    return match.group(1).strip(), fw.maybe_float(match.group(2))


def _direct_terms_match(product: dict[str, Any], group: dict[str, Any]) -> bool:
    terms = [runner._norm(value) for value in group.get("direct_include_any", []) if value]
    if not terms:
        return True
    text = fw.combined_product_text(product)
    return any(term in text for term in terms)


def _access_enriched_description(store: str, description: str) -> str:
    note = runner.infer_access_note(store, description, None, None)
    if not note:
        return description
    meta = {"access": note}
    return (description + "\n" if description else "") + runner.ACCESS_MARKER + json.dumps(
        meta, ensure_ascii=False, separators=(",", ":")
    )


def _coop_metadata(session: Any, base_url: str) -> tuple[str, str, dict[str, Any]]:
    response = session.get(base_url, timeout=fw.TIMEOUT_SECONDS)
    response.raise_for_status()
    html = response.text

    key_match = re.search(r"_shopgunApiKey=['\"]([^'\"]+)", html, re.I)
    soup = fw.BeautifulSoup(html, "html.parser")
    wrapper = soup.select_one(
        ".incito-wrapper[data-publication-id], .shopgun-wrapper[data-publication-id]"
    )
    api_key = key_match.group(1) if key_match else ""
    publication_id = str(wrapper.get("data-publication-id") or "") if wrapper else ""
    if not api_key or not publication_id:
        raise ValueError("Coop page is missing public ShopGun metadata")

    headers = {
        "User-Agent": fw.USER_AGENT,
        "X-Api-Key": api_key,
        "X-Widgets-Version": "v1",
        "Content-Type": "application/json",
    }
    detail = session.get(
        f"{fw.TJEK_CATALOGS_URL}/{publication_id}",
        headers=headers,
        timeout=fw.TIMEOUT_SECONDS,
    )
    detail.raise_for_status()
    catalog = detail.json()
    if not isinstance(catalog, dict) or not catalog.get("dealer_id"):
        raise ValueError("Coop catalog detail is missing dealer_id")
    return api_key, publication_id, catalog


def _visible_coop_catalogs(
    session: Any,
    api_key: str,
    dealer_id: str,
    now: datetime,
) -> list[dict[str, Any]]:
    headers = {
        "User-Agent": fw.USER_AGENT,
        "X-Api-Key": api_key,
        "X-Widgets-Version": "v1",
    }
    response = session.get(
        fw.TJEK_CATALOGS_URL,
        params={"dealer_id": dealer_id, "types": "paged,incito"},
        headers=headers,
        timeout=fw.TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    catalogs = response.json()
    if not isinstance(catalogs, list):
        raise ValueError("Coop catalog list is not a list")

    future_limit = now + timedelta(days=14)
    visible: list[dict[str, Any]] = []
    seen_periods: set[tuple[str, str]] = set()
    for catalog in catalogs:
        if not isinstance(catalog, dict):
            continue
        types = {str(value).lower() for value in catalog.get("types", [])}
        if "incito" not in types:
            continue
        run_from = fw.parse_timestamp(catalog.get("run_from"))
        run_till = fw.parse_timestamp(catalog.get("run_till"))
        publish = fw.parse_timestamp(catalog.get("publish"))
        if not run_from or not run_till:
            continue
        if publish and publish > now:
            continue
        if run_till < now or run_from > future_limit:
            continue
        period = (run_from.isoformat(), run_till.isoformat())
        if period in seen_periods:
            continue
        seen_periods.add(period)
        visible.append(catalog)
    return visible


def _fetch_catalog_nodes(
    session: Any,
    api_key: str,
    publication_id: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    headers = {
        "User-Agent": fw.USER_AGENT,
        "X-Api-Key": api_key,
        "X-Widgets-Version": "v1",
        "Content-Type": "application/json",
    }
    root_body = {
        "id": publication_id,
        "device_category": "desktop",
        "orientation": "vertical",
        "pointer": "fine",
        "pixel_ratio": 1,
        "max_width": 1000,
        "versions_supported": ["1.0.0"],
    }
    root_response = session.post(
        fw.TJEK_INCITO_URL,
        headers=headers,
        json=root_body,
        timeout=fw.TIMEOUT_SECONDS,
    )
    root_response.raise_for_status()
    root = root_response.json()
    section_bodies = fw._find_section_bodies(root.get("root_view"))

    unique_bodies: list[dict[str, Any]] = []
    seen_sections: set[str] = set()
    for body in section_bodies:
        section_id = str(body.get("section_id") or "")
        if section_id and section_id not in seen_sections:
            seen_sections.add(section_id)
            unique_bodies.append(body)

    def fetch_section(body: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        try:
            response = session.post(
                fw.TJEK_SECTION_URL,
                headers=headers,
                json=body,
                timeout=fw.TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {}, None
        except Exception as exc:
            return {}, f"section {body.get('section_id')}: {type(exc).__name__}: {exc}"

    nodes: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for section, error in pool.map(fetch_section, unique_bodies):
            if error:
                errors.append(error)
                continue
            nodes.extend(fw._find_offer_nodes(section))
    return nodes, errors


def collect_coop_offers(
    config: dict[str, Any],
    session: Any,
    now: datetime | None = None,
) -> tuple[list[fw.Offer], list[str]]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    errors: list[str] = []
    offers: dict[str, fw.Offer] = {}
    globally_allowed = {
        fw.canonical_store(store) for store in config.get("allowed_stores", []) if store
    }

    for store_key, (store_name, base_url) in COOP_SITES.items():
        if globally_allowed and store_key not in globally_allowed:
            continue
        try:
            api_key, _, current_catalog = _coop_metadata(session, base_url)
            catalogs = _visible_coop_catalogs(
                session,
                api_key,
                str(current_catalog["dealer_id"]),
                now,
            )
        except Exception as exc:
            errors.append(f"{store_name}: {type(exc).__name__}: {exc}")
            continue

        for catalog in catalogs:
            publication_id = str(catalog.get("id") or "")
            valid_from = fw.parse_timestamp(catalog.get("run_from"))
            valid_until = fw.parse_timestamp(catalog.get("run_till"))
            if not publication_id or not valid_from or not valid_until:
                continue
            try:
                nodes, node_errors = _fetch_catalog_nodes(session, api_key, publication_id)
                errors.extend(f"{store_name} {publication_id} {error}" for error in node_errors)
            except Exception as exc:
                errors.append(
                    f"{store_name} {publication_id}: {type(exc).__name__}: {exc}"
                )
                continue

            for node in nodes:
                name, price = _parse_offer_label(str(node.get("accessibility_label") or ""))
                if not name:
                    continue
                description = " | ".join(
                    dict.fromkeys(
                        text for text in fw._descendant_texts(node) if text and text != name
                    )
                )
                product = {"store": store_name, "name": name, "description": description}
                for group in config.get("watch_groups", []):
                    group_allowed = {
                        fw.canonical_store(store)
                        for store in group.get("allowed_stores", [])
                        if store
                    }
                    if group_allowed and store_key not in group_allowed:
                        continue
                    if not _direct_terms_match(product, group):
                        continue
                    if not runner.matches_group(product, group):
                        continue

                    offer_id = str(node.get("id") or "")
                    deep_link = base_url
                    if offer_id:
                        deep_link = base_url + "?" + urlencode({"view_id": offer_id})
                    enriched_description = _access_enriched_description(
                        store_name, description
                    )
                    offer = fw.Offer(
                        source="coop_direct",
                        group_id=str(group["id"]),
                        group_label=str(group["label"]),
                        store=store_name,
                        name=name,
                        description=enriched_description,
                        price=price,
                        valid_from=valid_from,
                        valid_until=valid_until,
                        offer_id=offer_id or f"{publication_id}:{name}",
                        publication_id=publication_id,
                        publication_label=str(catalog.get("label") or store_name),
                        url=deep_link,
                        image="",
                    )
                    if fw.offer_phase(offer, now) != "expired":
                        offers[offer.key] = offer

    return list(offers.values()), errors


def source_collect(
    config: dict[str, Any], session: Any, now: datetime | None = None
) -> tuple[list[fw.Offer], list[str]]:
    base_offers, errors = BASE_SOURCE_COLLECT(config, session, now=now)
    # Coop is authoritative from the official Coop/ShopGun feed. Drop any
    # third-party eTilbudsavis copies before adding direct Coop results.
    base_offers = [
        offer
        for offer in base_offers
        if not (
            offer.source == "etilbudsavis"
            and fw.canonical_store(offer.store) in COOP_CANONICAL_STORES | {"brugsen"}
        )
    ]
    coop_offers, coop_errors = collect_coop_offers(config, session, now=now)
    errors.extend(coop_errors)

    preferred: dict[str, fw.Offer] = {}
    for offer in base_offers + coop_offers:
        preferred[offer.fingerprint] = offer
    return list(preferred.values()), errors


def official_offer_url(offer: fw.Offer) -> str:
    url = str(offer.url or "")
    # Preserve already-official direct links, including Coop view_id deep links.
    if any(domain in url for domain in ("coop.dk", "lovbjerg.dk", "matas.dk", "bilka.dk", "netto.dk", "rema1000.dk", "lidl.dk")):
        return url
    return OFFICIAL_STORE_URLS.get(fw.canonical_store(offer.store), url)


def build_message(offer: fw.Offer, phase: str) -> str:
    official_url = official_offer_url(offer)
    display_offer = replace(offer, url="")
    message = BASE_BUILD_MESSAGE(display_offer, phase)
    if official_url:
        message += f"\n🔗 [Se tilbud hos {offer.store}]({official_url})"
    return message


def install() -> None:
    runner._ORIGINAL_COLLECT = source_collect
    runner.build_message = build_message
    runner.patch_family_watch()


def main() -> int:
    install()
    return fw.main()


if __name__ == "__main__":
    raise SystemExit(main())
