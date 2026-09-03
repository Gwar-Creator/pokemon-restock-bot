#!/usr/bin/env python3
"""V56 exact-collection + canonical-rarity + concrete-listing shadow runner."""

from __future__ import annotations

import argparse
from pathlib import Path

from personal import singles_collection_runner as cr
from personal import singles_v55 as v55
from personal import singles_v56 as v56

DEFAULT_OUTPUT = Path("personal_singles_listing_report.md")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=cr.DEFAULT_STATE)
    parser.add_argument("--profile", type=Path, default=cr.DEFAULT_PROFILE)
    parser.add_argument("--collection", type=Path, default=cr.DEFAULT_COLLECTION)
    parser.add_argument("--incoming", type=Path, default=cr.DEFAULT_INCOMING)
    parser.add_argument("--rarity-metadata", type=Path, default=v55.DEFAULT_RARITY_METADATA)
    parser.add_argument("--listings", type=Path, default=v56.DEFAULT_LISTINGS)
    parser.add_argument("--shipping", type=Path, default=v56.DEFAULT_SHIPPING)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=cr.DEFAULT_LIMIT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state = cr.load_json(args.state)
    profile = cr.load_json(args.profile)
    collection = cr.load_json(args.collection)
    incoming = cr.load_json(args.incoming)
    rarity_metadata = v55.load_rarity_metadata(args.rarity_metadata)
    snapshot = v56.load_listing_snapshot(args.listings)
    shipping = v56.load_shipping_overrides(args.shipping)

    effective_profile, stats = cr.apply_collection_filters(profile, collection, incoming)
    diagnostics = cr.suppression_diagnostics(state, profile, collection, incoming)
    unresolved = cr.unresolved_collection_rows(collection)

    rows = v56.evaluate_state(state, effective_profile, rarity_metadata, snapshot, shipping)
    if not rows:
        raise SystemExit(f"No usable personal Pokemon radar candidates found in {args.state}")

    header = cr.collection_header(stats, diagnostics, unresolved).replace(
        "V52.1 exact-link diagnostics shadow",
        "V56 exact-link + canonical-rarity + listing-verification shadow",
    )
    base_report = v56.build_report(rows, effective_profile, max(1, args.limit))
    base_lines = base_report.splitlines()
    if base_lines and base_lines[0].startswith("# Personal Singles Scout"):
        base_lines = base_lines[1:]
    report = header + "\n" + "\n".join(base_lines).lstrip("\n")
    args.output.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
