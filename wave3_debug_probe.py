"""Temporary CI-only diagnostics for Wave 3 storefront markup."""

import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from tier_b_wave1_sources import BROWSER_HEADERS, _clean


TARGET = "https://www.mugglealley.dk/shop/240-pokemon-kort-pakke/"
MARKERS = (
    "køb", "koeb", "lagerstatus", "udsolgt", "ikke på lager", "ikke pa lager",
    "kan på nuværende tidspunkt ikke bestilles", "kan pa nuvaerende tidspunkt ikke bestilles",
)


def classes(node):
    return ".".join(node.get("class") or [])


def main():
    response = requests.get(
        TARGET,
        headers={
            **BROWSER_HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        timeout=30,
    )
    print("status", response.status_code, "bytes", len(response.content), "final", response.url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    candidates = []
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "")
        text = _clean(anchor.get_text(" ", strip=True)) or _clean(anchor.get("title"))
        low = f"{href} {text}".lower()
        if "/shop/" in low or "vis produkt" in low or "pokemon" in low:
            candidates.append((anchor, href, text))

    print("candidate anchors", len(candidates))
    seen = set()
    shown = 0
    for anchor, href, text in candidates:
        key = (href, text)
        if key in seen:
            continue
        seen.add(key)
        print("ANCHOR", repr(href), "|", repr(text[:180]))
        node = anchor
        for depth in range(1, 5):
            node = getattr(node, "parent", None)
            if node is None or not getattr(node, "name", None):
                break
            snippet = _clean(node.get_text(" ", strip=True)).lower()
            hits = [marker for marker in MARKERS if marker in snippet]
            links = [str(a.get("href") or "") for a in node.select("a[href]")][:8]
            print(
                "  A", depth, node.name, classes(node)[:120],
                "markers", hits,
                "links", [repr(value) for value in links],
                "text", snippet[:360],
            )
        shown += 1
        if shown >= 25:
            break

    print("DATA ATTRIBUTES")
    shown = 0
    for node in soup.find_all(True):
        attrs = {str(k): str(v) for k, v in node.attrs.items()}
        packed = " ".join(f"{k}={v}" for k, v in attrs.items()).lower()
        if "product" in packed and ("id" in packed or "url" in packed or "href" in packed):
            print(node.name, classes(node)[:100], repr(packed[:500]))
            shown += 1
            if shown >= 20:
                break


if __name__ == "__main__":
    main()
