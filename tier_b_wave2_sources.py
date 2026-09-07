"""Read-only source adapters for Tier B Wave 2 shadow qualification."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin, urlparse

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
        "kind": "shopify_cardquest",
        "base": "https://cardquest.dk",
        "minimum": 5,
        "feeds": [
            {"path": "/collections/pokemon/products.json", "game": "POKÉMON"},
            {"path": "/collections/disney-lorcana/products.json", "game": "LORCANA"},
        ],
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

CARDQUEST_STOCK_POSITIVE = (
    "tilføj til kurv",
    "tilfoj til kurv",
    "kun få tilbage",
    "kun fa tilbage",
    "på lager",
    "pa lager",
    "add to cart",
)

CARDQUEST_STOCK_NEGATIVE = (
    "udsolgt",
    "ikke på lager",
    "ikke pa lager",
    "sold out",
    "out of stock",
)

CARDQUEST_MAX_PAGES = 10


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


def _cardquest_handle(url: str) -> str:
    path = urlparse(str(url or "")).path
    match = re.search(r"/products/([^/?#]+)", path)
    return match.group(1).strip().lower() if match else ""


def _cardquest_control_disabled(control) -> bool:
    if control.has_attr("disabled"):
        return True
    return str(control.get("aria-disabled") or "").strip().lower() == "true"


def _cardquest_stock_signal(card):
    """Return CardQuest's rendered buyable state for one product card."""
    saw_negative = False
    for control in card.select('button, input[type="submit"], [role="button"]'):
        control_text = " ".join(
            value
            for value in (
                _clean(control.get_text(" ", strip=True)),
                _clean(control.get("value")),
                _clean(control.get("aria-label")),
                _clean(control.get("title")),
            )
            if value
        ).lower()
        if not control_text:
            continue

        if any(marker in control_text for marker in CARDQUEST_STOCK_POSITIVE):
            if not _cardquest_control_disabled(control):
                return True
            saw_negative = True
        if any(marker in control_text for marker in CARDQUEST_STOCK_NEGATIVE):
            saw_negative = True

    text = _clean(card.get_text(" ", strip=True)).lower()
    has_positive = any(marker in text for marker in CARDQUEST_STOCK_POSITIVE)
    has_negative = any(marker in text for marker in CARDQUEST_STOCK_NEGATIVE)

    if has_positive and not has_negative:
        return True
    if has_negative and not has_positive:
        return False
    if saw_negative:
        return False
    return None


def _nearest_cardquest_product_card(link):
    node = link
    best = link
    for _ in range(10):
        parent = getattr(node, "parent", None)
        if parent is None or not getattr(parent, "name", None):
            break
        node = parent
        product_links = node.select('a[href*="/products/"]')
        handles = {
            _cardquest_handle(anchor.get("href"))
            for anchor in product_links
            if _cardquest_handle(anchor.get("href"))
        }
        if product_links:
            best = node

        if len(handles) == 1 and _cardquest_stock_signal(node) is not None:
            return node
        if len(handles) > 1:
            break
    return best


def parse_cardquest_html_stock(document: str):
    """Parse CardQuest collection cards where the frontend is authoritative.

    Their Shopify JSON can report variants unavailable while the rendered store
    still shows an enabled ``Tilføj til kurv`` button or ``Kun få tilbage``.
    """
    soup = BeautifulSoup(document or "", "html.parser")
    stock = {}

    for link in soup.select('a[href*="/products/"]'):
        handle = _cardquest_handle(link.get("href"))
        if not handle:
            continue
        card = _nearest_cardquest_product_card(link)
        value = _cardquest_stock_signal(card)
        if value is None:
            continue
        if handle not in stock or value is True:
            stock[handle] = value

    return stock


def fetch_cardquest_html_stock(config):
    stock = {}
    for path in config.get("html_stock_paths") or []:
        for page in range(1, CARDQUEST_MAX_PAGES + 1):
            response = requests.get(
                config["base"].rstrip("/") + path,
                headers={
                    **BROWSER_HEADERS,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                params={"page": page},
                timeout=30,
            )
            response.raise_for_status()
            page_stock = parse_cardquest_html_stock(response.text)
            if not page_stock:
                break

            before = len(stock)
            for handle, value in page_stock.items():
                if handle not in stock or value is True:
                    stock[handle] = value
            if len(stock) == before:
                break
    return stock


def fetch_cardquest_source(config):
    # CardQuest needs its source-specific rendered-stock parser. The shared
    # Shopify adapter also knows about ``html_stock_paths``, so passing the full
    # config there would fetch the same collection pages twice on every scan.
    # Use Shopify JSON only for discovery, then apply the authoritative overlay
    # exactly once below.
    catalog_config = dict(config)
    catalog_config["html_stock_paths"] = []
    catalog_config.pop("html_stock_path", None)
    products = fetch_shopify_source(catalog_config)

    try:
        overlay = fetch_cardquest_html_stock(config)
    except requests.RequestException:
        return products

    product_ids_by_handle = {}
    for product_id, product in products.items():
        handle = _cardquest_handle(product.get("url"))
        if handle:
            product_ids_by_handle[handle] = product_id

    for handle, in_stock in overlay.items():
        product_id = product_ids_by_handle.get(handle)
        if product_id in products:
            products[product_id]["in_stock"] = bool(in_stock)

    return products


def fetch_wave2_source(source_key: str):
    config = WAVE2_SOURCES[source_key]
    if config["kind"] == "shopify_cardquest":
        return fetch_cardquest_source(config)
    if config["kind"] == "hobbykniven_html":
        return fetch_hobbykniven_source(config)
    raise KeyError(f"Ukendt Wave 2 source kind: {config['kind']}")
