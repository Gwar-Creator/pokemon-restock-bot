"""Read-only source adapters for Tier B Wave 3 shadow qualification.

Wave 3 deliberately uses source-specific card boundaries where the storefront
markup differs from the generic Wave 1 Shopify/HTML assumptions.  All sources
remain shadow-only; this module never sends Discord or Price Watch messages.
"""

from __future__ import annotations

import hashlib
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
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
        "kind": "wave3_shopify",
        "base": "https://snydepels.dk",
        "minimum": 5,
        "feeds": [
            {"path": "/collections/tcg-ccg-pokemon/products.json", "game": "POKÉMON"},
            {"path": "/collections/tcg-ccg-disney-lorcana/products.json", "game": "LORCANA"},
        ],
        "stock_pages": [
            "/collections/tcg-ccg-pokemon",
            "/collections/tcg-ccg-disney-lorcana",
        ],
        "stock_card_selector": ".grid-item__content, .product-grid-item",
    },
    "kidsworld": {
        "label": "KIDS-WORLD",
        "kind": "selector_catalog",
        "base": "https://www.kids-world.dk",
        "minimum": 3,
        "pages": [
            {
                "url": "https://www.kids-world.dk/pokemon-kort-c-38626.html",
                "game": "POKÉMON",
                "link_pattern": r"/pokemon-[^?#]+-p-\d+\.html$",
                "card_selector": "div.product.product-size-selection",
            },
        ],
    },
    "borneneskartel": {
        "label": "BØRNENES KARTEL",
        "kind": "wave3_shopify",
        "base": "https://www.borneneskartel.dk",
        "minimum": 5,
        "feeds": [
            {"path": "/collections/samlekort-mapper/products.json", "game": None},
        ],
        "stock_pages": ["/collections/samlekort-mapper"],
        "stock_card_selector": "article.product-card, .product-card__wrapper",
    },
    "ergames": {
        "label": "ER-GAMES",
        "kind": "selector_catalog",
        "base": "https://er-games.dk",
        "minimum": 5,
        "pages": [
            {
                # The parent /kategori/pokemon/ is dominated by PSA slabs.
                # The dedicated Pokemon Kort child category is the sealed feed.
                "url": "https://er-games.dk/kategori/pokemon/pokemon-kort/",
                "game": "POKÉMON",
                "link_pattern": r"/vare/[^/?#]+/?$",
                "card_selector": ".e-loop-item.product",
                "paginate": True,
                "max_pages": 5,
            },
            {
                "url": "https://er-games.dk/kategori/trading-card-games/disney-lorcana/",
                "game": "LORCANA",
                "link_pattern": r"/vare/[^/?#]+/?$",
                "card_selector": ".e-loop-item.product",
            },
        ],
    },
    "mugglealley": {
        "label": "MUGGLE ALLEY",
        "kind": "mugglealley",
        "base": "https://www.mugglealley.dk",
        "minimum": 5,
        "url": "https://www.mugglealley.dk/shop/240-pokemon-kort-pakke/",
        "game": "POKÉMON",
        "link_pattern": r"/shop/239-pokemon-kort/\d+-[^/?#]+/?$",
    },
    "superhelten": {
        "label": "SUPERHELTEN LEGETØJ",
        "kind": "selector_catalog",
        "base": "https://www.superheltenlegetoej.dk",
        "minimum": 5,
        "pages": [
            {
                "url": "https://www.superheltenlegetoej.dk/da/pokemon-kort-booster-pakker--tin-boxes",
                "game": "POKÉMON",
                "link_pattern": r"/da/pokemon-kort-booster-pakker--tin-boxes/[^/?#]+/?$",
                "card_selector": "div.product-preview",
                # This storefront exposes this grid specifically under its
                # live "På lager" grouping; explicit negative text still wins.
                "listed_is_in_stock": True,
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
    "kan på nuværende tidspunkt ikke bestilles",
    "kan pa nuvaerende tidspunkt ikke bestilles",
    "produktet er udsolgt",
)

MUGGLE_RENDER_HEADERS = {
    **BROWSER_HEADERS,
    # Muggle Alley's category is Angular-rendered for ordinary requests.  Its
    # SEO renderer returns the same public catalogue as the browser after JS.
    "User-Agent": (
        "Mozilla/5.0 (compatible; Googlebot/2.1; "
        "+http://www.google.com/bot.html)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _normalized_product_url(base: str, href: str) -> str:
    return urljoin(base, str(href or "").split("#", 1)[0].split("?", 1)[0])


def _path_matches(url: str, link_pattern: str) -> bool:
    return bool(re.search(link_pattern, urlparse(str(url or "")).path, flags=re.IGNORECASE))


def _product_handle(url: str) -> str:
    match = re.search(r"/products/([^/?#]+)", urlparse(str(url or "")).path, flags=re.IGNORECASE)
    return match.group(1).strip().lower() if match else ""


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
    """Find one-product boundary, preferring an explicit stock-bearing card."""
    node = link
    price_candidate = None
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
        if len(urls) == 1 and has_stock:
            return node
        if len(urls) == 1 and has_price and price_candidate is None:
            price_candidate = node
        if len(urls) > 1:
            break
    return price_candidate or best


def _best_link_name(card, base: str, product_url: str, fallback_link) -> str:
    candidates = []
    for anchor in card.select("a[href]"):
        url = _normalized_product_url(base, anchor.get("href"))
        if url != product_url:
            continue
        text = _clean(anchor.get_text(" ", strip=True)) or _clean(anchor.get("title"))
        if text:
            candidates.append(text)
    if candidates:
        return max(candidates, key=len)
    return _clean(fallback_link.get_text(" ", strip=True)) or _clean(fallback_link.get("title"))


def _build_product(name: str, game: str, card_text: str, product_url: str, in_stock) -> dict:
    prices = _parse_danish_prices(card_text)
    return {
        "name": name,
        "game": game,
        "price": min(prices) if prices else None,
        "in_stock": bool(in_stock),
        "preorder": bool(_is_preorder(card_text)),
        "url": product_url,
    }


def parse_html_catalog(document: str, base: str, game: str, link_pattern: str):
    """Generic fallback parser using one-product ancestor scoping."""
    soup = BeautifulSoup(document or "", "html.parser")
    products = {}

    for link in soup.select("a[href]"):
        product_url = _normalized_product_url(base, link.get("href"))
        if not _path_matches(product_url, link_pattern):
            continue

        card = _nearest_product_card(link, base, link_pattern)
        name = _best_link_name(card, base, product_url, link)
        if not name:
            continue

        card_text = _clean(card.get_text(" ", strip=True))
        metadata = f"{game} {name} {card_text}"
        if not _sealed_allowed(name, metadata):
            continue

        product_id = hashlib.sha256(product_url.encode("utf-8")).hexdigest()[:20]
        products[product_id] = _build_product(
            name,
            game,
            card_text,
            product_url,
            _html_stock_signal(card) is True,
        )

    return products


def parse_selector_catalog(
    document: str,
    base: str,
    game: str,
    link_pattern: str,
    card_selector: str,
    listed_is_in_stock: bool = False,
):
    """Parse storefront cards with a known source-specific card boundary."""
    soup = BeautifulSoup(document or "", "html.parser")
    products = {}

    for card in soup.select(card_selector):
        links = []
        for link in card.select("a[href]"):
            product_url = _normalized_product_url(base, link.get("href"))
            if _path_matches(product_url, link_pattern):
                links.append((link, product_url))
        unique_urls = {url for _, url in links}
        if len(unique_urls) != 1:
            continue

        product_url = next(iter(unique_urls))
        fallback_link = next(link for link, url in links if url == product_url)
        name = _best_link_name(card, base, product_url, fallback_link)
        if not name:
            continue

        card_text = _clean(card.get_text(" ", strip=True))
        if not _sealed_allowed(name, f"{game} {name} {card_text}"):
            continue

        stock_signal = _html_stock_signal(card)
        if stock_signal is None and listed_is_in_stock:
            stock_signal = True
        product_id = hashlib.sha256(product_url.encode("utf-8")).hexdigest()[:20]
        products[product_id] = _build_product(
            name,
            game,
            card_text,
            product_url,
            stock_signal is True,
        )

    return products


def parse_shopify_card_stock(document: str, card_selector: str):
    """Return handle -> stock from a source-specific Shopify card selector."""
    soup = BeautifulSoup(document or "", "html.parser")
    stock = {}
    for card in soup.select(card_selector):
        handles = {
            _product_handle(anchor.get("href"))
            for anchor in card.select('a[href*="/products/"]')
            if _product_handle(anchor.get("href"))
        }
        if len(handles) != 1:
            continue
        value = _html_stock_signal(card)
        if value is None:
            continue
        handle = next(iter(handles))
        if handle not in stock or value is True:
            stock[handle] = bool(value)
    return stock


def fetch_wave3_shopify_source(config):
    """Use Shopify JSON for discovery and exact storefront cards for stock."""
    discovery_config = dict(config)
    discovery_config.pop("stock_pages", None)
    discovery_config.pop("stock_card_selector", None)
    # Do not invoke the generic Wave 1 rendered overlay for these themes.
    discovery_config.pop("html_stock_paths", None)
    discovery_config.pop("html_stock_path", None)
    products = fetch_shopify_source(discovery_config)

    overlay = {}
    for path in config.get("stock_pages") or []:
        response = requests.get(
            config["base"].rstrip("/") + path,
            headers={
                **BROWSER_HEADERS,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout=30,
        )
        response.raise_for_status()
        incoming = parse_shopify_card_stock(response.text, config["stock_card_selector"])
        for handle, value in incoming.items():
            if handle not in overlay or value is True:
                overlay[handle] = value

    if not overlay:
        raise RuntimeError("storefront stock overlay gav 0 produkter")

    matched = 0
    for product in products.values():
        handle = _product_handle(product.get("url"))
        if handle in overlay:
            product["in_stock"] = bool(overlay[handle])
            matched += 1
    if products and matched == 0:
        raise RuntimeError("storefront stock overlay matchede 0 katalogprodukter")
    return products


def _page_url(url: str, page_number: int) -> str:
    if page_number <= 1:
        return url
    return url.rstrip("/") + f"/page/{page_number}/"


def fetch_selector_catalog_source(config):
    products = {}
    for page in config.get("pages") or []:
        max_pages = int(page.get("max_pages") or 1) if page.get("paginate") else 1
        for page_number in range(1, max_pages + 1):
            response = requests.get(
                _page_url(page["url"], page_number),
                headers={
                    **BROWSER_HEADERS,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                timeout=30,
            )
            if page_number > 1 and response.status_code == 404:
                break
            response.raise_for_status()
            parsed = parse_selector_catalog(
                response.text,
                config["base"],
                page["game"],
                page["link_pattern"],
                page["card_selector"],
                bool(page.get("listed_is_in_stock")),
            )
            before = len(products)
            products.update(parsed)
            if page_number > 1 and (not parsed or len(products) == before):
                break
    return products


def fetch_html_catalog_source(config):
    """Backward-compatible generic Wave 3 HTML dispatcher used by tests."""
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
        products.update(
            parse_html_catalog(
                response.text,
                config["base"],
                page["game"],
                page["link_pattern"],
            )
        )
    return products


def _muggle_detail_stock(document: str):
    soup = BeautifulSoup(document or "", "html.parser")
    text = _clean(soup.get_text(" ", strip=True)).lower()
    if any(marker in text for marker in HTML_STOCK_NEGATIVE):
        return False
    for control in soup.select('button, input[type="submit"], [role="button"]'):
        control_text = " ".join(
            value
            for value in (
                _clean(control.get_text(" ", strip=True)),
                _clean(control.get("value")),
                _clean(control.get("aria-label")),
            )
            if value
        ).lower()
        if re.search(r"\b(?:køb|koeb)\b", control_text) and not _control_disabled(control):
            return True
    if re.search(r"lagerstatus\s*:\s*(?:\d+\s*-\s*\d+\s*hverdage|på lager|pa lager)", text):
        return True
    return None


def _probe_muggle_product(product_id: str, product: dict):
    response = requests.get(
        product["url"],
        headers=MUGGLE_RENDER_HEADERS,
        timeout=15,
    )
    response.raise_for_status()
    return product_id, _muggle_detail_stock(response.text)


def fetch_mugglealley_source(config):
    """Fetch Muggle Alley's public SEO-rendered category, then verify stock.

    The normal category response contains Angular templates with
    ``{{product.handle}}`` rather than real product links.  The public SEO
    renderer exposes the same catalogue that search engines and users receive
    after rendering, so discovery remains one request.  Stock is then checked
    on the relevant sealed product pages with a small bounded worker pool.
    """
    response = requests.get(config["url"], headers=MUGGLE_RENDER_HEADERS, timeout=30)
    response.raise_for_status()
    products = parse_html_catalog(
        response.text,
        config["base"],
        config["game"],
        config["link_pattern"],
    )
    if not products:
        raise RuntimeError("SEO-renderet Muggle Alley katalog gav 0 relevante produkter")

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(_probe_muggle_product, product_id, product): product_id
            for product_id, product in products.items()
        }
        for future in as_completed(futures):
            product_id = futures[future]
            try:
                _, stock = future.result()
            except requests.RequestException:
                # A single detail timeout must not turn a known product into a
                # false restock. Keep it non-buyable until a later clean probe.
                products[product_id]["in_stock"] = False
                continue
            products[product_id]["in_stock"] = stock is True
    return products


def fetch_wave3_source(source_key: str):
    config = WAVE3_SOURCES[source_key]
    if config["kind"] == "wave3_shopify":
        return fetch_wave3_shopify_source(config)
    if config["kind"] == "selector_catalog":
        return fetch_selector_catalog_source(config)
    if config["kind"] == "html_catalog":
        return fetch_html_catalog_source(config)
    if config["kind"] == "mugglealley":
        return fetch_mugglealley_source(config)
    raise KeyError(f"Ukendt Wave 3 source kind: {config['kind']}")
