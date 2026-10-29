#!/usr/bin/env python3
"""Read-only Proshop transport coverage probe. No Discord, no state writes."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import re

import requests
from proshop_reader_v2 import parse_proshop_reader

SOURCES = {
    "cards-category": "https://www.proshop.dk/pokemon-kort",
    "pokemon-brand": "https://www.proshop.dk/Pokemon/Pokemon",
    "pokemon-search": "https://www.proshop.dk/?s=Pokemon+TCG",
    "booster-search": "https://www.proshop.dk/?s=Pokemon+booster",
    "collection-search": "https://www.proshop.dk/?s=Pokemon+Premium+Collection",
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
        parsed = parse_proshop_reader(page, lambda name: any(word in name.lower() for word in (
            "booster", "elite trainer", "premium collection",
            "illustration collection", "battle deck", "world championships",
            "mini tin", " tin ", "blister", "collection box",
        )))
        md = MARKDOWN_LINK.findall(page)
        seen_paths = list(dict.fromkeys(re.findall(r"/Pokemon/[^)\\s?#\\\"<>]+/\\d+", page, re.I)))
        relevant = [(name.strip().replace("\n", " ")[:110], path) for name, path in md if TCG.search(name)]
        return {
            "source": label, "status": response.status_code,
            "bytes": len(page), "raw_unique_ids": len(ids),
            "markdown_links": len(md), "tcg_markdown": len(relevant),
            "v2_tcg_count": len(parsed),
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
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(probe, k, v) for k, v in SOURCES.items()]
        for future in as_completed(futures):
            print("PROSHOP PROBE", future.result(), flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
