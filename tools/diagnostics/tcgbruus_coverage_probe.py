#!/usr/bin/env python3
"""Read-only diagnostic of TCGBruuS public sealed catalogue HTML.

Manual/PR quality check only; never writes state or posts Discord.
The site's public display depends on the caller's locale/cookies, so this
probe intentionally mirrors the existing production homepage -> category flow.
"""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

BASE = "https://tcgbruus.dk/"
TARGET = BASE + "product-category/pokemon/sealed_produkter/?v=0ecbf9426bcf"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def inspect_html(source):
    soup = BeautifulSoup(source, "html.parser")
    unique_urls = set()
    for a in soup.find_all("a", href=True):
        full = urljoin(BASE, a["href"])
        parts = urlparse(full)
        if parts.netloc not in {"tcgbruus.dk", "www.tcgbruus.dk"}:
            continue
        if "/product/" in parts.path:
            unique_urls.add(parts.path.rstrip("/") + "/")

    cards = soup.select("li.product, .products .product, .product-grid-item, .wd-product")
    rows = []
    for card in cards:
        link = card.select_one('a[href*="/product/"]')
        if link is None:
            continue
        title = None
        for selector in (".woocommerce-loop-product__title", ".wd-entities-title", ".product-title", "h2", "h3", "h4"):
            node = card.select_one(selector)
            if node and node.get_text(" ", strip=True):
                title = " ".join(node.get_text(" ", strip=True).split())
                break
        if not title:
            image = card.select_one("img[alt]")
            if image:
                title = " ".join(image.get("alt", "").split())
        rows.append({
            "name": (title or "(no title)")[:130],
            "has_price": bool(re.search(r"(?:DKK|kr\.)\s*\d+", card.get_text(" ", strip=True), re.I)),
            "has_stock_marker": bool(re.search(r"på lager|udsolgt|tilføj til kurv|add to cart", card.get_text(" ", strip=True), re.I)),
        })
    return {
        "unique_product_urls": len(unique_urls),
        "product_card_elements": len(cards),
        "linked_product_cards": len(rows),
        "sample_cards": rows[:24],
    }


def main():
    try:
        from curl_cffi import requests as client
        session = client.Session(impersonate="chrome")
        transport = "curl_cffi_chrome"
    except ImportError:
        import requests as client
        session = client.Session()
        transport = "requests_fallback"

    print(f"TCGBRUUS PUBLIC READ-ONLY DIAGNOSTIC | transport={transport}", flush=True)
    try:
        home = session.get(BASE, headers=HEADERS, timeout=25)
        print("homepage HTTP status:", home.status_code, flush=True)
    except Exception as exc:
        print("homepage warning:", type(exc).__name__, flush=True)

    try:
        response = session.get(TARGET, headers=HEADERS, timeout=35)
        print("sealed category HTTP status:", response.status_code)
        print("content type:", response.headers.get("content-type", "")[:90])
        print("html length:", len(response.content))
        print("html fingerprint:", hashlib.sha256(response.content).hexdigest()[:14])
        if response.status_code != 200:
            print("READ_ONLY_PROBE: unavailable; cannot validate coverage")
            return 0
        print(json.dumps(inspect_html(response.text), ensure_ascii=False, indent=2))
        print("READ_ONLY_PROBE complete - no alert / purchase / state write")
    except Exception as exc:
        print("sealed category request failed:", type(exc).__name__)
        print("READ_ONLY_PROBE unavailable; no conclusion about product coverage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
