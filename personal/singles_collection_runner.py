#!/usr/bin/env python3
"""V51 collection-aware runner for the V50.1 personal singles radar.

The collection is the source of truth for what is owned. The runner only blocks
Cardmarket cards when an exact, explicitly verified ``cardmarket_product_id`` is
present in collection/incoming data. It deliberately does not fuzzy-match names,
sets or variants, because a false owned match is worse than an extra REVIEW.

Shadow-only: no network requests, no Discord messages and no production state
writes are performed here.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

DEFAULT_STATE = Path("cardmarket_chase_state.json")
DEFAULT_PROFILE = Path("personal/singles_profile.json")
DEFAULT_COLLECTION = Path("personal/collection.json")
DEFAULT_INCOMING = Path("personal/incoming.json")
DEFAULT_OUTPUT = Path("personal_singles_opportunity_report.md")
DEFAULT_LIMIT = 10


def load_json(path: Path, *, required: bool = True) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if required:
            raise SystemExit(f"Required JSON file missing: {path}")
        return {}
    if not isinstance(value, dict):
        raise SystemExit(f"Expected JSON object in {path}")
    return value


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def iter_collection_rows(collection: dict[str, Any]):
    """Yield normalized collection rows from verbose or compact V1 schemas."""
    cards = collection.get("cards")
    if isinstance(cards, list):
        for card in cards:
            if isinstance(card, dict):
                yield card
        return

    groups = collection.get("groups")
    fields = collection.get("fields")
    if not isinstance(groups, dict) or not isinstance(fields, list):
        raise ValueError("collection must contain cards[] or compact fields+groups")
    field_names = [str(value) for value in fields]
    for group_name, rows in groups.items():
        if not isinstance(rows, list):
            raise ValueError(f"collection group {group_name} must be a list")
        tcg = "LORCANA" if "lorcana" in str(group_name).lower() else "POKEMON"
        status = "owned"
        for index, row in enumerate(rows):
            if not isinstance(row, list) or len(row) != len(field_names):
                raise ValueError(f"invalid compact row {group_name}[{index}]")
            card = dict(zip(field_names, row))
            card["tcg"] = tcg
            card["status"] = status
            card["collection_group"] = str(group_name)
            card["collection_key"] = "|".join(
                [
                    tcg.lower(),
                    str(card.get("set") or "").casefold(),
                    str(card.get("number") or "").casefold(),
                    str(card.get("name") or "").casefold(),
                    str(card.get("variant") or "").casefold(),
                ]
            )
            yield card


def validate_collection(collection: dict[str, Any]) -> dict[str, int]:
    rows = list(iter_collection_rows(collection))

    seen_keys: set[str] = set()
    physical_cards = 0
    pokemon_cards = 0
    lorcana_cards = 0
    linked_ids = 0

    for index, card in enumerate(rows):
        key = str(card.get("collection_key") or "").strip()
        if not key:
            raise ValueError(f"collection row {index} is missing collection_key")
        if key in seen_keys:
            raise ValueError(f"duplicate collection_key: {key}")
        seen_keys.add(key)

        quantity = _positive_int(card.get("quantity"))
        if quantity is None:
            raise ValueError(f"invalid quantity for {key}")
        physical_cards += quantity

        tcg = str(card.get("tcg") or "").strip().upper()
        if tcg == "POKEMON":
            pokemon_cards += quantity
        elif tcg == "LORCANA":
            lorcana_cards += quantity
        else:
            raise ValueError(f"unsupported tcg for {key}: {tcg or '<empty>'}")

        product_id = card.get("cardmarket_product_id")
        if product_id not in (None, ""):
            text = str(product_id).strip()
            if not text.isdigit():
                raise ValueError(f"invalid Cardmarket product id for {key}: {product_id}")
            linked_ids += 1

    stats = {
        "physical_cards": physical_cards,
        "unique_exact_records": len(rows),
        "pokemon_cards": pokemon_cards,
        "lorcana_cards": lorcana_cards,
        "linked_cardmarket_product_ids": linked_ids,
    }

    declared = collection.get("totals")
    if isinstance(declared, dict):
        for field in ("physical_cards", "unique_exact_records", "pokemon_cards", "lorcana_cards"):
            expected = declared.get(field)
            if expected is not None and int(expected) != stats[field]:
                raise ValueError(
                    f"collection totals mismatch for {field}: declared={expected} actual={stats[field]}"
                )
    return stats


def linked_product_ids(payload: dict[str, Any], *, allowed_statuses: set[str]) -> set[str]:
    if "groups" in payload:
        cards = list(iter_collection_rows(payload))
    else:
        cards = payload.get("cards", [])
        if not isinstance(cards, list):
            raise ValueError("cards must be a list")
    result: set[str] = set()
    for card in cards:
        if not isinstance(card, dict):
            continue
        if str(card.get("tcg") or "POKEMON").strip().upper() != "POKEMON":
            continue
        status = str(card.get("status") or "").strip().lower()
        if status not in allowed_statuses:
            continue
        product_id = card.get("cardmarket_product_id")
        if product_id in (None, ""):
            continue
        text = str(product_id).strip()
        if not text.isdigit():
            raise ValueError(f"invalid linked Cardmarket product id: {product_id}")
        result.add(text)
    return result


def apply_collection_filters(
    profile: dict[str, Any],
    collection: dict[str, Any],
    incoming: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, int]]:
    stats = validate_collection(collection)
    owned_ids = linked_product_ids(collection, allowed_statuses={"owned"})
    incoming_ids = linked_product_ids(incoming, allowed_statuses={"incoming"})
    legacy_ids = {str(value).strip() for value in profile.get("owned_ids", []) if str(value).strip()}

    merged = copy.deepcopy(profile)
    merged["owned_ids"] = sorted(legacy_ids | owned_ids | incoming_ids, key=lambda x: (len(x), x))

    stats = {
        **stats,
        "linked_owned_ids": len(owned_ids),
        "linked_incoming_ids": len(incoming_ids),
        "effective_blocked_ids": len(merged["owned_ids"]),
    }
    return merged, stats


def collection_header(stats: dict[str, int]) -> str:
    unlinked = stats["unique_exact_records"] - stats["linked_cardmarket_product_ids"]
    return "\n".join(
        [
            "# Personal Singles Scout · V51 collection-aware shadow",
            "",
            f"- Owned baseline: {stats['physical_cards']} physical cards / {stats['unique_exact_records']} exact records",
            f"- Pokémon owned: {stats['pokemon_cards']} · Lorcana owned: {stats['lorcana_cards']}",
            f"- Verified Cardmarket links in collection: {stats['linked_cardmarket_product_ids']}",
            f"- Verified incoming Cardmarket links: {stats['linked_incoming_ids']}",
            f"- Unlinked collection records: {unlinked}",
            "- No fuzzy owned matching: unlinked cards are never hidden by name/set guesses.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--collection", type=Path, default=DEFAULT_COLLECTION)
    parser.add_argument("--incoming", type=Path, default=DEFAULT_INCOMING)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    return parser.parse_args()


def main() -> int:
    from personal import singles_opportunity as radar

    args = parse_args()
    state = load_json(args.state)
    profile = load_json(args.profile)
    collection = load_json(args.collection)
    incoming = load_json(args.incoming)
    effective_profile, stats = apply_collection_filters(profile, collection, incoming)

    rows = radar.evaluate_state(state, effective_profile)
    if not rows:
        raise SystemExit(f"No usable personal Pokemon radar candidates found in {args.state}")
    base_report = radar.build_report(rows, effective_profile, max(1, args.limit))
    base_lines = base_report.splitlines()
    if base_lines and base_lines[0].startswith("# Personal Singles Scout"):
        base_lines = base_lines[1:]
    report = collection_header(stats) + "\n" + "\n".join(base_lines).lstrip("\n")
    args.output.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
