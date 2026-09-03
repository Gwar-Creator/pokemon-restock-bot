#!/usr/bin/env python3
"""Refresh exact Cardmarket-ID rarity metadata from TCGdex.

This updater fixes the V55 coverage problem without weakening its safety gate.
It only writes metadata when TCGdex exposes the same exact Cardmarket product ID
and the TCGdex card's set/name agree with a personal-radar card in our state.

The updater is intentionally separate from the daily radar: the generated JSON is
committed periodically, so normal Personal Singles CI remains deterministic and
network-free.
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests

from personal import singles_opportunity as v53

DEFAULT_STATE = Path("cardmarket_chase_state.json")
DEFAULT_PROFILE = Path("personal/singles_profile.json")
DEFAULT_METADATA = Path("personal/pokemon_rarity_metadata.json")
TCGDEX_API = "https://api.tcgdex.net/v2/en"
SOURCE_REPO = "tcgdex/cards-database"
REQUEST_TIMEOUT = 25
MAX_WORKERS = 8
NAME_BATCH_SIZE = 8
LIST_PAGE_SIZE = 250

# TCGdex follows official set names while Cardmarket sometimes keeps the EX-era
# prefix. Normalize those known naming differences before comparing sets.
SET_ALIASES = {
    "base": "base set",
    "ruby sapphire": "ex ruby sapphire",
    "sandstorm": "ex sandstorm",
    "dragon": "ex dragon",
    "team magma vs team aqua": "ex team magma vs team aqua",
    "hidden legends": "ex hidden legends",
    "firered leafgreen": "ex firered leafgreen",
    "team rocket returns": "ex team rocket returns",
    "deoxys": "ex deoxys",
    "emerald": "ex emerald",
    "unseen forces": "ex unseen forces",
    "delta species": "ex delta species",
    "legend maker": "ex legend maker",
    "holon phantoms": "ex holon phantoms",
    "crystal guardians": "ex crystal guardians",
    "dragon frontiers": "ex dragon frontiers",
    "power keepers": "ex power keepers",
}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def normalized_set(value: Any) -> str:
    normalized = v53.normalize_text(value)
    return SET_ALIASES.get(normalized, normalized)


def personal_candidates(
    state: dict[str, Any], profile: dict[str, Any]
) -> dict[str, dict[str, str]]:
    """Return exact Cardmarket IDs that are relevant to the personal radar."""
    result: dict[str, dict[str, str]] = {}
    cards = state.get("cards", {}) if isinstance(state, dict) else {}
    if not isinstance(cards, dict):
        return result

    ignored = {str(value) for value in profile.get("ignore_ids", [])}
    owned = {str(value) for value in profile.get("owned_ids", [])}

    for raw in cards.values():
        if not isinstance(raw, dict) or str(raw.get("game") or "") != "POKÉMON":
            continue
        card_id = str(raw.get("id") or "")
        if not card_id or card_id in ignored or card_id in owned or v53.is_non_physical_card(raw):
            continue
        _, reasons = v53.personal_score(raw, profile)
        if not reasons:
            continue
        subject = v53.subject_name(raw.get("name"))
        if not subject:
            continue
        result[card_id] = {
            "set": str(raw.get("set") or ""),
            "set_key": normalized_set(raw.get("set")),
            "subject": subject,
            "subject_key": v53.normalize_text(subject),
        }
    return result


def chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def request_json(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    retries: int = 3,
) -> Any:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", "1") or 1)
                time.sleep(min(5.0, max(0.5, retry_after)))
                continue
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(0.75 * (attempt + 1))
    raise RuntimeError(f"TCGdex request failed: {url}: {last_error}")


def set_name_map(session: requests.Session) -> dict[str, str]:
    rows = request_json(session, f"{TCGDEX_API}/sets")
    if not isinstance(rows, list):
        raise RuntimeError("Unexpected TCGdex /sets response")
    result = {}
    for row in rows:
        if isinstance(row, dict) and row.get("id") and row.get("name"):
            result[str(row["id"])] = str(row["name"])
    return result


def brief_cards_for_subjects(
    session: requests.Session, subjects: list[str]
) -> list[dict[str, Any]]:
    """Fetch TCGdex card briefs in exact-name batches, including pagination."""
    unique: dict[str, dict[str, Any]] = {}
    for batch in chunks(sorted(set(subjects), key=str.casefold), NAME_BATCH_SIZE):
        page = 1
        while True:
            rows = request_json(
                session,
                f"{TCGDEX_API}/cards",
                params={
                    "name": "eq:" + "|".join(batch),
                    "pagination:page": page,
                    "pagination:itemsPerPage": LIST_PAGE_SIZE,
                },
            )
            if not isinstance(rows, list):
                raise RuntimeError("Unexpected TCGdex /cards response")
            for row in rows:
                if isinstance(row, dict) and row.get("id"):
                    unique[str(row["id"])] = row
            if len(rows) < LIST_PAGE_SIZE:
                break
            page += 1
    return list(unique.values())


def card_set_id(card_id: str) -> str:
    return card_id.rsplit("-", 1)[0] if "-" in card_id else ""


def candidate_brief_ids(
    briefs: list[dict[str, Any]],
    candidates: dict[str, dict[str, str]],
    sets: dict[str, str],
) -> list[str]:
    wanted_pairs = {
        (row["subject_key"], row["set_key"])
        for row in candidates.values()
    }
    result: list[str] = []
    for brief in briefs:
        brief_id = str(brief.get("id") or "")
        name_key = v53.normalize_text(brief.get("name"))
        set_id = card_set_id(brief_id)
        set_key = normalized_set(sets.get(set_id, ""))
        if brief_id and (name_key, set_key) in wanted_pairs:
            result.append(brief_id)
    return sorted(set(result))


def cardmarket_variant_ids(card: dict[str, Any]) -> dict[str, str]:
    """Return Cardmarket product IDs exposed by TCGdex and their finish labels."""
    result: dict[str, str] = {}

    pricing = card.get("pricing") if isinstance(card, dict) else None
    cardmarket = pricing.get("cardmarket") if isinstance(pricing, dict) else None
    if isinstance(cardmarket, dict) and cardmarket.get("idProduct") is not None:
        result[str(cardmarket["idProduct"])] = "root"

    third_party = card.get("thirdParty") if isinstance(card, dict) else None
    if isinstance(third_party, dict) and third_party.get("cardmarket") is not None:
        result[str(third_party["cardmarket"])] = "root"

    variants = card.get("variants_detailed") if isinstance(card, dict) else None
    if isinstance(variants, list):
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            source = variant.get("thirdParty")
            if not isinstance(source, dict) or source.get("cardmarket") is None:
                continue
            finish = str(variant.get("type") or variant.get("variant") or "variant")
            result[str(source["cardmarket"])] = finish
    return result


def metadata_from_card(
    card: dict[str, Any],
    candidates: dict[str, dict[str, str]],
) -> dict[str, dict[str, Any]]:
    """Extract only exact Cardmarket IDs that also agree on set and card name."""
    set_info = card.get("set") if isinstance(card, dict) else None
    set_name = str(set_info.get("name") or "") if isinstance(set_info, dict) else ""
    source_set_id = (
        str(set_info.get("id") or "")
        if isinstance(set_info, dict)
        else card_set_id(str(card.get("id") or ""))
    )
    canonical_name = str(card.get("name") or "")
    rarity = str(card.get("rarity") or "").strip()
    if not canonical_name or not set_name or not rarity:
        return {}

    subject_key = v53.normalize_text(canonical_name)
    set_key = normalized_set(set_name)
    output: dict[str, dict[str, Any]] = {}
    for product_id, finish in cardmarket_variant_ids(card).items():
        wanted = candidates.get(product_id)
        if not wanted:
            continue
        if wanted["subject_key"] != subject_key or wanted["set_key"] != set_key:
            continue
        output[product_id] = {
            "source": "TCGdex",
            "source_card_id": str(card.get("id") or ""),
            "source_set_id": source_set_id,
            "cardmarket_set": wanted["set"],
            "canonical_name": canonical_name,
            "canonical_number": str(card.get("localId") or ""),
            "canonical_rarity": rarity,
            "finish": finish,
            "metadata_confidence": "EXACT_CARDMARKET_ID",
            "verified_by": ["exact Cardmarket idProduct", "set", "name"],
        }
    return output


def fetch_detail(
    session: requests.Session,
    card_id: str,
) -> dict[str, Any]:
    payload = request_json(session, f"{TCGDEX_API}/cards/{card_id}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected TCGdex card response for {card_id}")
    return payload


def refresh_metadata(
    state: dict[str, Any],
    profile: dict[str, Any],
    existing_payload: dict[str, Any],
    *,
    session: requests.Session | None = None,
    workers: int = MAX_WORKERS,
) -> tuple[dict[str, Any], dict[str, int]]:
    candidates = personal_candidates(state, profile)
    existing_cards = existing_payload.get("cards", {}) if isinstance(existing_payload, dict) else {}
    if not isinstance(existing_cards, dict):
        existing_cards = {}

    own_session = session is None
    session = session or requests.Session()
    session.headers.update({"User-Agent": "pokemon-restock-bot/personal-rarity-v55.1"})

    try:
        sets = set_name_map(session)
        subjects = sorted({row["subject"] for row in candidates.values()})
        briefs = brief_cards_for_subjects(session, subjects)
        detail_ids = candidate_brief_ids(briefs, candidates, sets)

        matched: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            futures = {executor.submit(fetch_detail, session, card_id): card_id for card_id in detail_ids}
            for future in as_completed(futures):
                card = future.result()
                matched.update(metadata_from_card(card, candidates))
    finally:
        if own_session:
            session.close()

    cards = dict(existing_cards)
    cards.update(matched)
    payload = {
        "version": 2,
        "source": "TCGdex exact Cardmarket IDs + retained manually verified seed metadata",
        "source_repository": SOURCE_REPO,
        "matching_policy": (
            "Exact Cardmarket product ID is required. TCGdex set and English card name must also agree "
            "with the personal Cardmarket radar state. No fuzzy rarity linking is accepted."
        ),
        "cards": dict(sorted(cards.items(), key=lambda item: int(item[0]))),
    }
    stats = {
        "candidates": len(candidates),
        "subjects": len(subjects),
        "briefs": len(briefs),
        "detail_cards": len(detail_ids),
        "matched_exact_ids": len(matched),
        "coverage": sum(card_id in cards for card_id in candidates),
    }
    return payload, stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state = load_json(args.state, {})
    profile = load_json(args.profile, {})
    existing = load_json(args.metadata, {})
    payload, stats = refresh_metadata(
        state,
        profile,
        existing,
        workers=max(1, min(16, args.workers)),
    )
    args.metadata.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "RARITY METADATA: "
        f"{stats['coverage']}/{stats['candidates']} personal candidates covered; "
        f"{stats['matched_exact_ids']} exact TCGdex/Cardmarket IDs refreshed from "
        f"{stats['detail_cards']} candidate source cards."
    )
    if stats["coverage"] <= 10:
        raise SystemExit("Rarity coverage did not improve beyond the V55 seed baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
