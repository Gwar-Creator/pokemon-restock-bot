"""Temporary CI-only live validation for Wave 3 source adapters."""

from collections import Counter
import time

import requests
from bs4 import BeautifulSoup

import tier_b_wave3_sources as sources


def summarize(source_key: str):
    started = time.monotonic()
    try:
        products = sources.fetch_wave3_source(source_key)
    except Exception as exc:
        print(f"LIVE {source_key.upper()}: ERROR {type(exc).__name__}: {exc}")
        return

    games = Counter(product.get("game") for product in products.values())
    stock = sum(product.get("in_stock") is True for product in products.values())
    preorder = sum(product.get("preorder") is True for product in products.values())
    elapsed = time.monotonic() - started
    print(
        f"LIVE {source_key.upper()}: total={len(products)} "
        f"pokemon={games.get('POKÉMON', 0)} lorcana={games.get('LORCANA', 0)} "
        f"stock={stock} preorder={preorder} elapsed={elapsed:.1f}s"
    )
    for product in list(products.values())[:5]:
        print(
            "  SAMPLE",
            repr(product.get("name")),
            "stock=", product.get("in_stock"),
            "preorder=", product.get("preorder"),
            "price=", product.get("price"),
            "url=", product.get("url"),
        )


def validate_muggle_renderer():
    config = sources.WAVE3_SOURCES["mugglealley"]
    try:
        response = requests.get(
            config["url"],
            headers=sources.MUGGLE_RENDER_HEADERS,
            timeout=30,
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"MUGGLE RENDERER: ERROR {type(exc).__name__}: {exc}")
        return

    soup = BeautifulSoup(response.text, "html.parser")
    matches = []
    for anchor in soup.select("a[href]"):
        url = sources._normalized_product_url(config["base"], anchor.get("href"))
        if sources._path_matches(url, config["link_pattern"]):
            matches.append(url)
    matches = list(dict.fromkeys(matches))
    print(
        f"MUGGLE RENDERER: status={response.status_code} bytes={len(response.content)} "
        f"matching_product_links={len(matches)}"
    )
    for url in matches[:5]:
        print("  MUGGLE LINK", url)


def main():
    validate_muggle_renderer()
    for source_key in sources.WAVE3_SOURCES:
        summarize(source_key)


if __name__ == "__main__":
    main()
