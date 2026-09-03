#!/usr/bin/env python3
"""Read-only V56 marketplace-article probe using Cardmarket's official API 2.0.

This module is intentionally NOT scheduled. Cardmarket currently restricts API app
access to manually approved professional sellers and warns against using dedicated
apps as a continuous marketplace-price crawler. Run this probe manually only when
approved Cardmarket OAuth credentials are available.

The official Articles resource can verify exact product ID, English language,
condition, seller country and concrete listing price. It does not expose whether a
seller ships this article to Denmark or the buyer-specific shipping cost, so those
fields are written as null and must be verified separately before LISTING_REVIEW.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from requests_oauthlib import OAuth1

from personal import singles_collection_runner as collection_runner
from personal import singles_v55 as v55

API_BASE = "https://apiv2.cardmarket.com/ws/v2.0/output.json"
DEFAULT_STATE = Path("cardmarket_chase_state.json")
DEFAULT_PROFILE = Path("personal/singles_profile.json")
DEFAULT_COLLECTION = Path("personal/personal_collection.json")
DEFAULT_INCOMING = Path("personal/personal_incoming.json")
DEFAULT_RARITY = Path("personal/pokemon_rarity_metadata.json")
DEFAULT_OUTPUT = Path("personal/cardmarket_listing_snapshot.json")
DEFAULT_LIMIT = 20
DEFAULT_OFFERS_PER_PRODUCT = 25


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def credentials_from_env() -> dict[str, str] | None:
    values = {
        "app_token": os.getenv("CARDMARKET_APP_TOKEN", "").strip(),
        "app_secret": os.getenv("CARDMARKET_APP_SECRET", "").strip(),
        "access_token": os.getenv("CARDMARKET_ACCESS_TOKEN", "").strip(),
        "access_secret": os.getenv("CARDMARKET_ACCESS_TOKEN_SECRET", "").strip(),
    }
    return values if all(values.values()) else None


def oauth_for(url: str, credentials: dict[str, str]) -> OAuth1:
    return OAuth1(
        credentials["app_token"],
        client_secret=credentials["app_secret"],
        resource_owner_key=credentials["access_token"],
        resource_owner_secret=credentials["access_secret"],
        signature_method="HMAC-SHA1",
        realm=url,
    )


def seller_fields(article: dict[str, Any]) -> tuple[str, str]:
    seller = article.get("seller")
    if not isinstance(seller, dict):
        return "", ""
    name = str(seller.get("username") or seller.get("name") or "")
    address = seller.get("address")
    country = str(address.get("country") or "") if isinstance(address, dict) else ""
    if not country:
        country = str(seller.get("country") or "")
    return name, country.upper()


def language_fields(article: dict[str, Any]) -> tuple[int | None, str]:
    language = article.get("language")
    if isinstance(language, dict):
        raw_id = language.get("idLanguage")
        try:
            language_id = int(raw_id)
        except (TypeError, ValueError):
            language_id = None
        return language_id, str(language.get("languageName") or "")
    raw_id = article.get("idLanguage")
    try:
        return int(raw_id), str(language or "")
    except (TypeError, ValueError):
        return None, str(language or "")


def normalize_article(
    article: dict[str, Any],
    *,
    product_id: str,
    expected_variant: str,
    checked_at: str,
) -> dict[str, Any] | None:
    offered_product = str(article.get("idProduct") or "")
    if offered_product != str(product_id):
        return None

    language_id, language_name = language_fields(article)
    seller_name, seller_country = seller_fields(article)
    is_foil = article.get("isFoil") is True
    expected_foil = str(expected_variant or "").strip().casefold() == "foil"

    try:
        price = float(article.get("price"))
    except (TypeError, ValueError):
        return None
    if price < 0:
        return None

    return {
        "source": "official_cardmarket_api_v2",
        "id_article": str(article.get("idArticle") or ""),
        "product_id": offered_product,
        "language_id": language_id,
        "language": language_name,
        "condition": str(article.get("condition") or "").upper(),
        "price_eur": price,
        "seller_name": seller_name,
        "seller_country": seller_country,
        "is_foil": is_foil,
        "expected_variant": str(expected_variant or "Normal"),
        "variant_match": is_foil == expected_foil,
        "is_signed": article.get("isSigned") is True,
        "is_altered": article.get("isAltered") is True,
        "is_first_ed": article.get("isFirstEd") is True,
        "last_edited": article.get("lastEdited"),
        "checked_at": checked_at,
        "ships_to_denmark": None,
        "shipping_eur": None,
    }


def extract_articles(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("article", "articles"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def fetch_product_offers(
    session: requests.Session,
    credentials: dict[str, str],
    *,
    product_id: str,
    expected_variant: str,
    checked_at: str,
    max_results: int = DEFAULT_OFFERS_PER_PRODUCT,
) -> list[dict[str, Any]]:
    url = f"{API_BASE}/articles/{product_id}"
    expected_foil = str(expected_variant or "").strip().casefold() == "foil"
    params = {
        "idLanguage": 1,
        "minCondition": "NM",
        "isFoil": "true" if expected_foil else "false",
        "isSigned": "false",
        "isAltered": "false",
        "start": 0,
        "maxResults": max(1, min(100, int(max_results))),
    }
    response = session.get(
        url,
        params=params,
        headers={"Accept": "application/json", "User-Agent": "pokemon-restock-bot/v56-readonly"},
        auth=oauth_for(url, credentials),
        timeout=30,
        allow_redirects=False,
    )
    if response.status_code == 307:
        raise RuntimeError(
            "Cardmarket forced pagination redirect encountered. V56 refuses to follow an OAuth-signed redirect blindly."
        )
    response.raise_for_status()
    rows = extract_articles(response.json())
    output = []
    for row in rows:
        normalized = normalize_article(
            row,
            product_id=product_id,
            expected_variant=expected_variant,
            checked_at=checked_at,
        )
        if normalized is not None:
            output.append(normalized)
    return sorted(output, key=lambda row: (row["price_eur"], row["id_article"]))


def v55_review_candidates(
    state: dict[str, Any],
    profile: dict[str, Any],
    collection: dict[str, Any],
    incoming: dict[str, Any],
    rarity_metadata: dict[str, dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    effective_profile, _ = collection_runner.apply_collection_filters(profile, collection, incoming)
    rows = v55.evaluate_state(state, effective_profile, rarity_metadata)
    return [row for row in rows if row.get("signal") == "REVIEW"][: max(1, limit)]


def refresh_snapshot(
    candidates: list[dict[str, Any]],
    credentials: dict[str, str],
    *,
    session: requests.Session | None = None,
    offers_per_product: int = DEFAULT_OFFERS_PER_PRODUCT,
) -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    own_session = session is None
    session = session or requests.Session()
    offers: dict[str, list[dict[str, Any]]] = {}
    try:
        for candidate in candidates:
            product_id = str(candidate.get("id") or "")
            if not product_id:
                continue
            offers[product_id] = fetch_product_offers(
                session,
                credentials,
                product_id=product_id,
                expected_variant=str(candidate.get("variant") or "Normal"),
                checked_at=checked_at,
                max_results=offers_per_product,
            )
    finally:
        if own_session:
            session.close()

    return {
        "version": 1,
        "source": "official_cardmarket_api_v2",
        "updated_at": checked_at,
        "shipping_scope": "NOT_EXPOSED_BY_ARTICLE_API",
        "notes": (
            "Read-only official Articles API snapshot. Exact product/language/condition/seller country/listing price "
            "are captured. ships_to_denmark and shipping_eur remain null until separately verified."
        ),
        "offers": offers,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--collection", type=Path, default=DEFAULT_COLLECTION)
    parser.add_argument("--incoming", type=Path, default=DEFAULT_INCOMING)
    parser.add_argument("--rarity", type=Path, default=DEFAULT_RARITY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--offers-per-product", type=int, default=DEFAULT_OFFERS_PER_PRODUCT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    credentials = credentials_from_env()
    if credentials is None:
        raise SystemExit(
            "Official Cardmarket OAuth credentials are not configured. V56 will not scrape Cardmarket or substitute the aggregate third-party price feed for listings."
        )

    state = load_json(args.state, {})
    profile = load_json(args.profile, {})
    collection = load_json(args.collection, {})
    incoming = load_json(args.incoming, {})
    rarity_metadata = v55.load_rarity_metadata(args.rarity)
    candidates = v55_review_candidates(
        state,
        profile,
        collection,
        incoming,
        rarity_metadata,
        args.limit,
    )
    snapshot = refresh_snapshot(
        candidates,
        credentials,
        offers_per_product=args.offers_per_product,
    )
    args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    offer_count = sum(len(rows) for rows in snapshot["offers"].values())
    print(
        f"V56 OFFICIAL LISTINGS: {offer_count} concrete offers across {len(snapshot['offers'])} V55 REVIEW products. "
        "Shipping-to-Denmark remains unverified until explicitly checked."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
