#!/usr/bin/env python3
"""Apply explicitly verified Cardmarket product IDs to a collection copy.

V52 keeps the source collection untouched. Exact links live in a sidecar and are
only applied when tcg + name + set + number + variant matches an existing
collection record exactly after case-folding. No fuzzy matching is performed.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

DEFAULT_COLLECTION = Path("personal/collection.json")
DEFAULT_LINKS = Path("personal/cardmarket_links.json")
DEFAULT_OUTPUT = Path("personal_collection_linked.json")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def norm(value: Any) -> str:
    return str(value or "").strip().casefold()


def exact_key(*, tcg: Any, name: Any, set_name: Any, number: Any, variant: Any) -> str:
    return "|".join([norm(tcg), norm(set_name), norm(number), norm(name), norm(variant)])


def iter_links(payload: dict[str, Any]):
    links = payload.get("links")
    if not isinstance(links, list):
        raise ValueError("links payload must contain links[]")

    fields = payload.get("fields")
    if fields is None:
        for index, link in enumerate(links):
            if not isinstance(link, dict):
                raise ValueError(f"link {index} must be an object")
            yield link
        return

    if not isinstance(fields, list):
        raise ValueError("links fields must be a list")
    field_names = [str(value) for value in fields]
    for index, row in enumerate(links):
        if not isinstance(row, list) or len(row) != len(field_names):
            raise ValueError(f"invalid compact link row {index}")
        yield dict(zip(field_names, row))


def _collection_refs(collection: dict[str, Any]) -> dict[str, tuple[dict[str, Any] | list[Any], int | str]]:
    refs: dict[str, tuple[dict[str, Any] | list[Any], int | str]] = {}

    cards = collection.get("cards")
    if isinstance(cards, list):
        for index, card in enumerate(cards):
            if not isinstance(card, dict):
                raise ValueError(f"collection card {index} must be an object")
            key = exact_key(
                tcg=card.get("tcg") or "POKEMON",
                name=card.get("name"),
                set_name=card.get("set"),
                number=card.get("number"),
                variant=card.get("variant"),
            )
            if key in refs:
                raise ValueError(f"duplicate collection exact key: {key}")
            refs[key] = (card, "cardmarket_product_id")
        return refs

    groups = collection.get("groups")
    fields = collection.get("fields")
    if not isinstance(groups, dict) or not isinstance(fields, list):
        raise ValueError("collection must contain cards[] or compact fields+groups")
    field_names = [str(value) for value in fields]
    required = {"name", "set", "number", "variant", "cardmarket_product_id"}
    if not required.issubset(field_names):
        raise ValueError("compact collection is missing required fields")
    positions = {name: field_names.index(name) for name in required}

    for group_name, rows in groups.items():
        if not isinstance(rows, list):
            raise ValueError(f"collection group {group_name} must be a list")
        tcg = "LORCANA" if "lorcana" in str(group_name).casefold() else "POKEMON"
        for index, row in enumerate(rows):
            if not isinstance(row, list) or len(row) != len(field_names):
                raise ValueError(f"invalid compact collection row {group_name}[{index}]")
            key = exact_key(
                tcg=tcg,
                name=row[positions["name"]],
                set_name=row[positions["set"]],
                number=row[positions["number"]],
                variant=row[positions["variant"]],
            )
            if key in refs:
                raise ValueError(f"duplicate collection exact key: {key}")
            refs[key] = (row, positions["cardmarket_product_id"])
    return refs


def apply_links(collection: dict[str, Any], links_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    linked = copy.deepcopy(collection)
    refs = _collection_refs(linked)
    seen_link_keys: set[str] = set()
    applied = 0

    for index, link in enumerate(iter_links(links_payload)):
        product_id = str(link.get("cardmarket_product_id") or "").strip()
        if not product_id.isdigit():
            raise ValueError(f"invalid Cardmarket product id in link {index}: {product_id or '<empty>'}")
        key = exact_key(
            tcg=link.get("tcg") or "POKEMON",
            name=link.get("name"),
            set_name=link.get("set"),
            number=link.get("number"),
            variant=link.get("variant"),
        )
        if key in seen_link_keys:
            raise ValueError(f"duplicate exact link: {key}")
        seen_link_keys.add(key)
        target = refs.get(key)
        if target is None:
            raise ValueError(f"verified link has no exact collection record: {key}")
        row, field = target
        current = row[field]  # type: ignore[index]
        if current not in (None, "") and str(current).strip() != product_id:
            raise ValueError(f"Cardmarket id conflict for {key}: collection={current} links={product_id}")
        row[field] = product_id  # type: ignore[index]
        applied += 1

    linked_count = 0
    for row, field in refs.values():
        value = row[field]  # type: ignore[index]
        if value not in (None, ""):
            linked_count += 1

    totals = linked.get("totals")
    if isinstance(totals, dict):
        totals["linked_cardmarket_product_ids"] = linked_count

    stats = {
        "collection_records": len(refs),
        "sidecar_links": len(seen_link_keys),
        "applied_links": applied,
        "linked_records": linked_count,
        "unlinked_records": len(refs) - linked_count,
    }
    return linked, stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", type=Path, default=DEFAULT_COLLECTION)
    parser.add_argument("--links", type=Path, default=DEFAULT_LINKS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    linked, stats = apply_links(load_json(args.collection), load_json(args.links))
    args.output.write_text(json.dumps(linked, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(
        "V52 exact links: "
        f"{stats['applied_links']} applied / {stats['collection_records']} records; "
        f"{stats['unlinked_records']} unresolved"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
