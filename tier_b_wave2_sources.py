"""Read-only source adapters for Tier B Wave 2 shadow qualification."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from tier_b_wave1_sources import (
    BROWSER_HEADERS,
    _clean,
    _parse_danish_prices,
    _sealed_allowed,
    fetch_shopify_source,
)


WAVE2_SOURCES = {
    "cardquest": {
        "label": "CARDQUEST",
        "kind": "shopify",
        "base": "https://cardquest.dk",
        "minimum": 5,
        "feeds": [
            {"path": "/collections/pokemon/products.json", "game": "POKÉMON"},
            {"path": "/collections/disney-lorcana/products.json", "game": "LORCANA"},
        ],
        # The rendered collections expose clear Add-to-cart/Sold-out controls,
        # so use them as a secondary availability check without broadening the
        # catalogue beyond the two sealed TCG collections above.
        "html_stock_paths": [
            "/collections/pokemon",
            "/collections/disney-lorcana",
        ],
    },
    "hobbykniven": {
        "label": "HOBBYKNIVEN",
        "kind": "hobbykniven_html",
        "base": "https://hobbykniven.dk",
        "minimum": 5,
        "url": "https://hobbykniven.dk/katalog/kategori/pokemon-sealed",
    },
}


HOBBY_STOCK_POSITIVE = (
    "på lager",
    "pa lager",
    "få tilbage",
    "fa tilbage",
    "læg i kurv",
    "laeg i kurv",
)

HOBBY_STOCK_NEGATIVE = (
    "udsolgt",
    "ikke på lager",
    "ikke pa lager",
)


def _nearest_hobby_product_card(link):
    node = link
    best = link
    for _ in range(9):
        parent = getattr(node, "parent", None)
        if parent is None or not getattr(parent, "name", None):
            break
        node = parent
        text = _clean(node.get_text(" ", strip=True))
        product_links = node.select('a[href*="/katalog/produkt/"]')
        urls = {str(anchor.get("href") or "").split("?", 1)[0] for anchor in product_links}
        if product_links:
            best = node

        has_price = bool(_parse_danish_prices(text))
        low = text.lower()
        has_stock = any(marker in low for marker in HOBBY_STOCK_POSITIVE + HOBBY_STOCK_NEGATIVE)
        if len(urls) == 1 and has_price and has_stock:
            return node
        if len(urls) > 1:
            break
    return best


def parse_hobbykniven_html(document: str, base: str):
    soup = BeautifulSoup(document or "", "html.parser")
    products = {}

    for link in soup.select('a[href*="/katalog/produkt/"]'):
        href = str(link.get("href") or "").strip()
        name = _clean(link.get_text(" ", strip=True))
        if not href or not name:
            continue

        product_url = urljoin(base, href.split("?", 1)[0])
        if product_url in products:
            continue

        card = _nearest_hobby_product_card(link)
        card_text = _clean(card.get_text(" ", strip=True))
        if not _sealed_allowed(name, f"pokemon sealed {name} {card_text}"):
            continue

        prices = _parse_danish_prices(card_text)
        low = card_text.lower()
        explicit_out = any(marker in low for marker in HOBBY_STOCK_NEGATIVE)
        explicit_in = any(marker in low for marker in HOBBY_STOCK_POSITIVE)
        product_id = hashlib.sha256(product_url.encode("utf-8")).hexdigest()[:20]

        products[product_url] = {
            "id": product_id,
            "name": name,
            "game": "POKÉMON",
            "price": min(prices) if prices else None,
            "in_stock": bool(explicit_in and not explicit_out),
            "preorder": "forudbest" in low or "preorder" in low or "pre-order" in low,
            "url": product_url,
        }

    return {product["id"]: {key: value for key, value in product.items() if key != "id"} for product in products.values()}


def fetch_hobbykniven_source(config):
    response = requests.get(
        config["url"],
        headers={
            **BROWSER_HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        timeout=30,
    )
    response.raise_for_status()
    return parse_hobbykniven_html(response.text, config["base"])


def fetch_wave2_source(source_key: str):
    config = WAVE2_SOURCES[source_key]
    if config["kind"] == "shopify":
        return fetch_shopify_source(config)
    if config["kind"] == "hobbykniven_html":
        return fetch_hobbykniven_source(config)
    raise KeyError(f"Ukendt Wave 2 source kind: {config['kind']}")
