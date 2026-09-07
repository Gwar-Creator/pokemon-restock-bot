"""Read-only source adapters for Tier B Wave 3 shadow qualification."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from tier_b_wave1_sources import (
    BROWSER_HEADERS,
    _clean,
    _is_preorder,
    _parse_danish_prices,
    _sealed_allowed,
    fetch_shopify_source,
)


WAVE3_SOURCES = {
    "snydepels": {
        "label": "SNYDEPELS",
        "kind": "shopify",
        "base": "https://snydepels.dk",
        "minimum": 5,
        "feeds": [
            {"path": "/collections/tcg-ccg-pokemon/products.json", "game": "POKÉMON"},
            {"path": "/collections/tcg-ccg-disney-lorcana/products.json", "game": "LORCANA"},
        ],
        "html_stock_paths": [
            "/collections/tcg-ccg-pokemon",
            "/collections/tcg-ccg-disney-lorcana",
        ],
    },
    "kidsworld": {
        "label": "KIDS-WORLD",
        "kind": "html_catalog",
        "base": "https://www.kids-world.dk",
        "minimum": 3,
        "pages": [
            {
                "url": "https://www.kids-world.dk/pokemon-kort-c-38626.html",
                "game": "POKÉMON",
                "link_pattern": r"/pokemon-[^?#]+-p-\d+\.html$",
            },
        ],
    },
    "borneneskartel": {
        "label": "BØRNENES KARTEL",
        "kind": "shopify",
        "base": "https://www.borneneskartel.dk",
        "minimum": 5,
        "feeds": [
            {"path": "/collections/samlekort-mapper/products.json", "game": None},
        ],
        "html_stock_path": "/collections/samlekort-mapper",
    },
    "ergames": {
        "label": "ER-GAMES",
        "kind": "html_catalog",
        "base": "https://er-games.dk",
        "minimum": 5,
        "pages": [
            {
                # The broad Pokemon category also contains graded cards. The
                # shared English/sealed guard strips PSA/CGC/BGS singles.
                "url": "https://er-games.dk/kategori/pokemon/",
                "game": "POKÉMON",
                "link_pattern": r"/vare/[^/?#]+/?$",
            },
            {
                "url": "https://er-games.dk/kategori/trading-card-games/disney-lorcana/",
                "game": "LORCANA",
                "link_pattern": r"/vare/[^/?#]+/?$",
            },
        ],
    },
    "mugglealley": {
        "label": "MUGGLE ALLEY",
        "kind": "html_catalog",
        "base": "https://www.mugglealley.dk",
        "minimum": 5,
        "pages": [
            {
                "url": "https://www.mugglealley.dk/shop/240-pokemon-kort-pakke/",
                "game": "POKÉMON",
                "link_pattern": r"/shop/\d+-pokemon-kort/[^/?#]+/?$",
            },
        ],
    },
    "superhelten": {
        "label": "SUPERHELTEN LEGETØJ",
        "kind": "html_catalog",
        "base": "https://www.superheltenlegetoej.dk",
        "minimum": 5,
        "pages": [
            {
                "url": "https://www.superheltenlegetoej.dk/da/pokemon-kort-booster-pakker--tin-boxes",
                "game": "POKÉMON",
                "link_pattern": r"/da/pokemon-kort-booster-pakker--tin-boxes/[^/?#]+/?$",
            },
        ],
    },
}


HTML_STOCK_POSITIVE = (
    "læg i kurv",
    "laeg i kurv",
    "tilføj til kurv",
    "tilfoj til kurv",
    "add to cart",
    "på lager",
    "pa lager",
    "få tilbage",
    "fa tilbage",
    "klar til afsend",
)

HTML_STOCK_NEGATIVE = (
    "udsolgt",
    "ikke på lager",
    "ikke pa lager",
    "sold out",
    "out of stock",
    "endnu ikke til salg",
)


def _normalized_product_url(base: str, href: str) -> str:
    return urljoin(base, str(href or "").split("#", 1)[0].split("?", 1)[0])


def _path_matches(url: str, link_pattern: str) -> bool:
    return bool(re.search(link_pattern, urlparse(str(url or "")).path, flags=re.IGNORECASE))


def _control_disabled(control) -> bool:
    if control.has_attr("disabled"):
        return True
    return str(control.get("aria-disabled") or "").strip().lower() == "true"


def _html_stock_signal(card):
    """Return explicit rendered stock state; otherwise None."""
    saw_negative_control = False
    for control in card.select('button, input[type="submit"], [role="button"]'):
        text = " ".join(
            value
            for value in (
                _clean(control.get_text(" ", strip=True)),
                _clean(control.get("value")),
                _clean(control.get("aria-label")),
                _clean(control.get("title")),
            )
            if value
        ).lower()
        if not text:
            continue
        if any(marker in text for marker in HTML_STOCK_POSITIVE):
            if not _control_disabled(control):
                return True
            saw_negative_control = True
        if any(marker in text for marker in HTML_STOCK_NEGATIVE):
            saw_negative_control = True

    text = _clean(card.get_text(" ", strip=True)).lower()
    has_positive = any(marker in text for marker in HTML_STOCK_POSITIVE)
    has_negative = any(marker in text for marker in HTML_STOCK_NEGATIVE)
    if has_positive and not has_negative:
        return True
    if has_negative and not has_positive:
        return False
    if saw_negative_control:
        return False
    return None


def _matching_product_links(node, base: str, link_pattern: str):
    urls = set()
    for anchor in node.select("a[href]"):
        url = _normalized_product_url(base, anchor.get("href"))
        if _path_matches(url, link_pattern):
            urls.add(url)
    return urls


def _nearest_product_card(link, base: str, link_pattern: str):
    node = link
    best = link
    for _ in range(10):
        parent = getattr(node, "parent", None)
        if parent is None or not getattr(parent, "name", None):
            break
        node = parent
        urls = _matching_product_links(node, base, link_pattern)
        if urls:
            best = node

        text = _clean(node.get_text(" ", strip=True))
        has_price = bool(_parse_danish_prices(text))
        has_stock = _html_stock_signal(node) is not None
        if len(urls) == 1 and (has_price or has_stock):
            return node
        if len(urls) > 1:
            break
    return best


def _best_link_name(card, product_url: str, fallback_link) -> str:
    candidates = []
    for anchor in card.select("a[href]"):
        url = _normalized_product_url(product_url, anchor.get("href"))
        if url != product_url:
            continue
        text = _clean(anchor.get_text(" ", strip=True)) or _clean(anchor.get("title"))
        if text:
            candidates.append(text)
    if candidates:
        return max(candidates, key=len)
    return _clean(fallback_link.get_text(" ", strip=True)) or _clean(fallback_link.get("title"))


def parse_html_catalog(document: str, base: str, game: str, link_pattern: str):
    """Parse a server-rendered category using product-link scoped cards."""
    soup = BeautifulSoup(document or "", "html.parser")
    products = {}

    for link in soup.select("a[href]"):
        product_url = _normalized_product_url(base, link.get("href"))
        if not _path_matches(product_url, link_pattern):
            continue

        card = _nearest_product_card(link, base, link_pattern)
        name = _best_link_name(card, product_url, link)
        if not name:
            continue

        card_text = _clean(card.get_text(" ", strip=True))
        metadata = f"{game} {name} {card_text}"
        if not _sealed_allowed(name, metadata):
            continue

        prices = _parse_danish_prices(card_text)
        preorder = _is_preorder(card_text)
        stock_signal = _html_stock_signal(card)
        product_id = hashlib.sha256(product_url.encode("utf-8")).hexdigest()[:20]
        products[product_id] = {
            "name": name,
            "game": game,
            "price": min(prices) if prices else None,
            "in_stock": stock_signal is True,
            "preorder": bool(preorder),
            "url": product_url,
        }

    return products


def fetch_html_catalog_source(config):
    products = {}
    for page in config.get("pages") or []:
        response = requests.get(
            page["url"],
            headers={
                **BROWSER_HEADERS,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout=30,
        )
        response.raise_for_status()
        parsed = parse_html_catalog(
            response.text,
            config["base"],
            page["game"],
            page["link_pattern"],
        )
        products.update(parsed)
    return products


def fetch_wave3_source(source_key: str):
    config = WAVE3_SOURCES[source_key]
    if config["kind"] == "shopify":
        return fetch_shopify_source(config)
    if config["kind"] == "html_catalog":
        return fetch_html_catalog_source(config)
    raise KeyError(f"Ukendt Wave 3 source kind: {config['kind']}")
