"""Read-only source adapters for Tier B Wave 1.

These sources are deliberately isolated from Discord and Price Watch while they
are validated in shadow mode.  Every adapter returns the same small normalized
product shape so promotion into the normal Tier B pipeline can happen later
without rewriting the source parsers.
"""

from __future__ import annotations

import hashlib
import html
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
}

SHOPIFY_PAGE_SIZE = 250
SHOPIFY_MAX_PAGES = 10

WAVE1_SOURCES = {
    "cardcollective": {
        "label": "CARD COLLECTIVE",
        "kind": "shopify",
        "base": "https://cardcollective.dk",
        "minimum": 20,
        "feeds": [
            {"path": "/collections/pokemon/products.json", "game": "POKÉMON"},
        ],
    },
    "flinamania": {
        "label": "FLINAMANIA",
        "kind": "shopify",
        "base": "https://flinamania.dk",
        "minimum": 5,
        "feeds": [
            {"path": "/products.json", "game": None},
        ],
    },
    "softgunshoppen": {
        "label": "SOFTGUNSHOPPEN",
        "kind": "softgun_html",
        "base": "https://www.softgunshoppen.com",
        "minimum": 5,
        "url": (
            "https://www.softgunshoppen.com/pokemon-shop-danmark/"
            "engelske-pokemon-serier.html"
        ),
    },
    "pockomonsters": {
        "label": "POCKO MONSTERS",
        "kind": "shopify",
        "base": "https://pockomonsters.dk",
        "minimum": 20,
        "feeds": [
            {"path": "/products.json", "game": None},
        ],
    },
    "orbitalkickz": {
        "label": "ORBITALKICKZ",
        "kind": "shopify",
        "base": "https://orbitalkickz.dk",
        "minimum": 5,
        "feeds": [
            {"path": "/products.json", "game": None},
        ],
    },
    "kofodtrading": {
        "label": "KOFOD TRADING",
        "kind": "shopify",
        "base": "https://kofodtrading.dk",
        "minimum": 5,
        "feeds": [
            {"path": "/collections/engelsk/products.json", "game": "POKÉMON"},
        ],
    },
    "andishop": {
        "label": "ANDISHOP",
        "kind": "shopify",
        "base": "https://andishop.dk",
        "minimum": 1,
        "feeds": [
            {"path": "/collections/engelsk/products.json", "game": "POKÉMON"},
        ],
    },
    "cardstop": {
        "label": "CARDSTOP",
        "kind": "shopify",
        "base": "https://cardstop.dk",
        "minimum": 5,
        "feeds": [
            {"path": "/collections/pokemon/products.json", "game": "POKÉMON"},
        ],
    },
}


NON_ENGLISH_MARKERS = (
    "japanese",
    "japansk",
    "japan edition",
    "korean",
    "koreansk",
    "chinese",
    "kinesisk",
    "simplified chinese",
    "traditional chinese",
)

SINGLE_MARKERS = (
    "single card",
    "single cards",
    "singles",
    "enkeltkort",
    "graded card",
    "graded cards",
    "gradede kort",
    "psa 10",
    "psa 9",
    "psa 8",
    "cgc 10",
    "cgc 9",
    "bgs 10",
    "bgs 9",
)

NOISE_MARKERS = (
    "livebreak",
    "live break",
    "rip and ship",
    "rip & ship",
    "mystery pack",
    "mystery box",
    "repack",
)

SEALED_MARKERS = (
    "booster",
    "elite trainer",
    " etb",
    "etb ",
    "collection",
    " box",
    "box ",
    "bundle",
    "blister",
    " tin",
    "tin ",
    "deck",
    "toolkit",
    "battle academy",
    "chest",
    "trove",
    "starter",
    "gift set",
    "premium",
    " upc",
    "upc ",
    "poster",
    "calendar",
    "display",
)

ACCESSORY_MARKERS = (
    "sleeve",
    "sleeves",
    "kortlommer",
    "mappe",
    "binder",
    "portfolio",
    "playmat",
    "play mat",
    "deck box",
    "deckbox",
    "toploader",
    "top loader",
    "akryl",
    "acryl",
    "acrylic",
    "storage box",
    "display case",
    "card case",
    "card holder",
)


def _clean(value) -> str:
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _shopify_text(product) -> str:
    tags = product.get("tags") or []
    if isinstance(tags, list):
        tags = " ".join(str(tag) for tag in tags)
    return " ".join(
        [
            _clean(product.get("title")),
            _clean(product.get("product_type")),
            _clean(product.get("vendor")),
            _clean(tags),
        ]
    ).lower()


def _detect_game(product):
    text = _shopify_text(product)
    if "lorcana" in text:
        return "LORCANA"
    if "pokemon" in text or "pokémon" in text:
        return "POKÉMON"
    return None


def _english_allowed(text: str) -> bool:
    low = f" {str(text or '').lower()} "
    return not any(marker in low for marker in NON_ENGLISH_MARKERS)


def _sealed_allowed(title: str, metadata_text: str = "") -> bool:
    low_title = f" {str(title or '').lower()} "
    low_all = f" {str(metadata_text or '').lower()} "

    if not _english_allowed(low_all):
        return False
    if any(marker in low_all for marker in NOISE_MARKERS):
        return False
    if any(marker in low_all for marker in SINGLE_MARKERS):
        return False

    # Common single-card labels used by OrbitalKickz/CardStop are especially
    # useful because card names can otherwise contain words like Collection.
    if re.search(r"\b(?:single|singles)\b", low_all):
        return False

    is_sealed = any(marker in low_title for marker in SEALED_MARKERS)
    if not is_sealed:
        return False

    is_accessory = any(marker in low_title for marker in ACCESSORY_MARKERS)
    if is_accessory:
        # Official collection products may contain an accessory word while
        # still being genuine sealed TCG products with boosters.
        return "collection" in low_title and (
            "binder" in low_title or "playmat" in low_title or "play mat" in low_title
        )

    return True


def _variant_price(product):
    values = []
    for variant in product.get("variants") or []:
        raw = variant.get("price")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            values.append(value)
    return min(values) if values else None


def _variant_available(product):
    return any(variant.get("available") is True for variant in product.get("variants") or [])


def _is_preorder(text):
    low = str(text or "").lower()
    return any(
        marker in low
        for marker in (
            "preorder",
            "pre-order",
            "pre order",
            "forudbestil",
            "forudbestilling",
            "kommer snart",
        )
    )


def fetch_shopify_feed(base: str, path: str):
    collected = {}
    for page in range(1, SHOPIFY_MAX_PAGES + 1):
        response = requests.get(
            base.rstrip("/") + path,
            headers={**BROWSER_HEADERS, "Accept": "application/json,text/plain,*/*"},
            params={"limit": SHOPIFY_PAGE_SIZE, "page": page},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("products") or []
        if not isinstance(rows, list) or not rows:
            break

        new_on_page = 0
        for product in rows:
            product_id = str(product.get("id") or "").strip()
            if not product_id:
                continue
            if product_id not in collected:
                new_on_page += 1
            collected[product_id] = product

        if new_on_page == 0 or len(rows) < SHOPIFY_PAGE_SIZE:
            break

    return list(collected.values())


def fetch_shopify_source(config):
    products = {}
    for feed in config.get("feeds") or []:
        rows = fetch_shopify_feed(config["base"], feed["path"])
        for raw in rows:
            game = feed.get("game") or _detect_game(raw)
            if game not in ("POKÉMON", "LORCANA"):
                continue

            name = _clean(raw.get("title"))
            product_id = str(raw.get("id") or "").strip()
            handle = str(raw.get("handle") or "").strip()
            metadata = _shopify_text(raw)
            if not name or not product_id or not handle:
                continue
            if not _sealed_allowed(name, metadata):
                continue

            products[product_id] = {
                "name": name,
                "game": game,
                "price": _variant_price(raw),
                "in_stock": _variant_available(raw),
                "preorder": _is_preorder(metadata),
                "url": f"{config['base'].rstrip('/')}/products/{handle}",
            }
    return products


def _parse_danish_prices(value):
    values = []
    for raw in re.findall(
        r"(?<!\d)(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:,\d{1,2})?)\s*(?:kr\.?|DKK)",
        _clean(value),
        flags=re.IGNORECASE,
    ):
        try:
            price = float(raw.replace(".", "").replace(",", "."))
        except ValueError:
            continue
        if price > 0:
            values.append(price)
    return values


def parse_softgun_html(document: str, base: str):
    soup = BeautifulSoup(document, "html.parser")
    cards = soup.select("li.product-item, .product-item-info")

    # Magento themes can make .product-item-info both the child and the card.
    # Deduplicate by product URL rather than relying on exact theme classes.
    products = {}
    for card in cards:
        link = (
            card.select_one("a.product-item-link[href]")
            or card.select_one(".product-item-name a[href]")
            or card.select_one('a[href*="pokemon"]')
        )
        if not link:
            continue

        name = _clean(link.get_text(" ", strip=True)) or _clean(link.get("title"))
        product_url = urljoin(base, link.get("href"))
        if not name or not product_url:
            continue

        card_text = _clean(card.get_text(" ", strip=True))
        if not _sealed_allowed(name, f"pokemon {name} {card_text}"):
            continue

        low = card_text.lower()
        explicit_out = "ikke på lager" in low or "ikke pa lager" in low or "out of stock" in low
        explicit_in = any(
            marker in low
            for marker in ("tilføj kurv", "tilfoj kurv", "læg i kurv", "laeg i kurv", "add to cart", "på lager")
        )
        preorder = _is_preorder(card_text)
        prices = _parse_danish_prices(card_text)
        product_id = hashlib.sha256(product_url.encode("utf-8")).hexdigest()[:20]

        products[product_id] = {
            "name": name,
            "game": "POKÉMON",
            "price": min(prices) if prices else None,
            "in_stock": bool(explicit_in and not explicit_out and not preorder),
            "preorder": bool(preorder),
            "url": product_url,
        }

    return products


def fetch_softgun_source(config):
    response = requests.get(
        config["url"],
        headers={
            **BROWSER_HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        timeout=30,
    )
    response.raise_for_status()
    return parse_softgun_html(response.text, config["base"])


def fetch_wave1_source(source_key: str):
    config = WAVE1_SOURCES[source_key]
    if config["kind"] == "shopify":
        return fetch_shopify_source(config)
    if config["kind"] == "softgun_html":
        return fetch_softgun_source(config)
    raise KeyError(f"Ukendt Wave 1 source kind: {config['kind']}")
