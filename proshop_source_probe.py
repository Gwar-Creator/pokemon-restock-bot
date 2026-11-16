#!/usr/bin/env python3
"""Read-only Proshop transport coverage probe. No Discord, no state writes."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import json

import requests
from proshop_reader_v2 import parse_proshop_reader
from proshop_known_sku_watch import is_proshop_tcg_title

SOURCES = {
    "cards-category": "https://www.proshop.dk/pokemon-kort",
    "pokemon-brand": "https://www.proshop.dk/Pokemon/Pokemon",
    "pokemon-search": "https://www.proshop.dk/?s=Pokemon+TCG",
    "booster-search": "https://www.proshop.dk/?s=Pokemon+booster",
    "collection-search": "https://www.proshop.dk/?s=Pokemon+Premium+Collection",
    "detail-greninja": "https://www.proshop.dk/Pokemon/Pokemon-TCG-Mega-Greninja-ex-Premium-Collection/3478496",
    "detail-chaos-box": "https://www.proshop.dk/Pokemon/Pokemon-TCG-Mega-EvolutionChaos-Rising-Booster-box-with-36-boosters/3447592",
    "detail-first-partner": "https://www.proshop.dk/Pokemon/Pokemon-TCG-First-Partner-Illustration-Collection-Box-Series-2/3478498",
}
PRODUCT_LINK = re.compile(
    r"(?:https?://(?:www\.)?proshop\.dk)?/Pokemon/[^)\s?#\"<>]+/(\d+)",
    re.I,
)
MARKDOWN_LINK = re.compile(
    r"\[([^\]]{2,300})\]\((?:https?://(?:www\.)?proshop\.dk)?"
    r"(/Pokemon/[^)\s?#]+/\d+)(?:[?#][^)]*)?\)",
    re.I | re.S,
)
TCG = re.compile(
    r"(?i)(?:\bTCG\b|booster|elite trainer|\bETB\b|"
    r"premium collection|illustration collection|battle deck|world championships|mini tin)"
)

def _is_tcg(value):
    """Diagnostics mirror the conservative sealed TCG title criteria.

    Keep accessories out of observed TCG coverage. No status is inferred.
    """
    text = " " + re.sub(r"\\s+", " ", str(value or "").lower()) + " "
    allowed = (
        "booster", "elite trainer", " etb ", "premium collection",
        "ultra-premium collection", "illustration collection",
        "battle deck", "world championships", "championships deck",
        "mini tin", " tin ", "blister", "collection box",
        "binder collection", "playmat collection", "trainer toolkit",
    )
    blocked = (
        "portfolio", "sleeves", "deck box", "card case", "display case",
        "storage box", "samlemappe", "kortlomme", "binder", "playmat",
    )
    if any(marker in text for marker in blocked) and not any(
        marker in text for marker in ("binder collection", "playmat collection")
    ):
        return False
    return is_proshop_tcg_title(value, lambda name: any(
        marker in (" " + str(name or "").lower() + " ") for marker in allowed
    ))


def summarize_probes(results):
    """Union of *observed* TCG SKUs, not a claim of complete Proshop stock."""
    rows = {row["source"]: row for row in results}
    catalogue_labels = (
        "cards-category", "pokemon-brand", "pokemon-search",
        "booster-search", "collection-search",
    )
    observed = {
        label: set(rows.get(label, {}).get("v2_ids") or ())
        for label in catalogue_labels
    }
    union = set().union(*observed.values())
    category = observed["cards-category"]
    extras = union - category
    return {
        "coverage_status": "unverified",
        "note": "Only observed parser-matched SKUs; not the full Proshop catalogue",
        "category_skus": sorted(category),
        "catalogue_union_skus": sorted(union),
        "extra_skus_outside_category": sorted(extras),
        "extra_count": len(extras),
        "catalogue_source_counts": {
            label: len(observed[label]) for label in catalogue_labels
        },
        "source_results": {
            row["source"]: {
                "http_status": row.get("status"),
                "error_type": row.get("error_type"),
                "raw_unique_ids": row.get("raw_unique_ids"),
                "parsed_tcg": row.get("v2_tcg_count"),
            }
            for row in results
        },
    }


def probe(label, url):
    reader_url = "https://r.jina.ai/" + url
    try:
        response = requests.get(reader_url, headers={
            "Accept": "text/plain, text/markdown;q=0.9",
            "User-Agent": "Pokemon-Restock-Proshop-Diagnostics/1.0",
            "x-no-cache": "true",
            "x-engine": "browser",
        }, timeout=50)
        page = response.text
        ids = set(PRODUCT_LINK.findall(page))
        parsed = parse_proshop_reader(page, _is_tcg)
        md = MARKDOWN_LINK.findall(page)
        seen_paths = list(dict.fromkeys(re.findall(r"/Pokemon/[^)\\s?#\\\"<>]+/\\d+", page, re.I)))
        relevant = [(name.strip().replace("\n", " ")[:110], path) for name, path in md if TCG.search(name)]
        return {
            "source": label, "status": response.status_code,
            "bytes": len(page), "raw_unique_ids": len(ids),
            "markdown_links": len(md), "tcg_markdown": len(relevant),
            "v2_tcg_count": len(parsed),
            "v2_ids": sorted(parsed),
            "verified_stock_cards": sum(
                product["stock"] not in (None, "UKENDT")
                for product in parsed.values()
            ),
            "v2_products": [(key, row["name"], row["price"], row["stock"]) for key, row in parsed.items()],
            "tcg_examples": relevant[:15],
            "all_paths": seen_paths[:70],
            "sample_text": page[:450].replace("\\n", " "),
            "product_link_contexts": [
                page[max(0, m.start() - 105):min(len(page), m.end() + 180)].replace("\\n", " ")
                for m in list(PRODUCT_LINK.finditer(page))[:8]
            ],
            "error_type": None,
        }
    except requests.RequestException as exc:
        return {"source": label, "error_type": type(exc).__name__, "message": str(exc)[:180]}

def main():
    results = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(probe, k, v) for k, v in SOURCES.items()]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print("PROSHOP PROBE", json.dumps(
                result, ensure_ascii=False
            ), flush=True)

    # The check is deliberately read-only; coverage always stays unverified.
    print("PROSHOP COVERAGE SUMMARY", json.dumps(
        summarize_probes(results), ensure_ascii=False
    ), flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
