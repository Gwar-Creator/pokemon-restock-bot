"""Temporary CI-only diagnostics for Wave 3 storefront markup."""

import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from tier_b_wave1_sources import BROWSER_HEADERS, _clean


TARGETS = [
    ("snydepels", "https://snydepels.dk/collections/tcg-ccg-pokemon", r"/products/"),
    ("kidsworld", "https://www.kids-world.dk/pokemon-kort-c-38626.html", r"/pokemon-.*-p-\d+\.html"),
    ("borneneskartel", "https://www.borneneskartel.dk/collections/samlekort-mapper", r"/products/"),
    ("ergames", "https://er-games.dk/kategori/pokemon/", r"/vare/"),
    ("mugglealley", "https://www.mugglealley.dk/shop/240-pokemon-kort-pakke/", r"/shop/"),
    ("superhelten", "https://www.superheltenlegetoej.dk/da/pokemon-kort-booster-pakker--tin-boxes", r"/da/pokemon-kort-booster-pakker--tin-boxes/"),
]

MARKERS = (
    "læg i kurv", "laeg i kurv", "tilføj til kurv", "tilfoj til kurv",
    "add to cart", "køb", "på lager", "pa lager", "udsolgt",
    "ikke på lager", "ikke pa lager", "bestillingsvare", "endnu ikke til salg",
)


def classes(node):
    return ".".join(node.get("class") or [])


def main():
    for label, url, href_pattern in TARGETS:
        print(f"\n===== {label.upper()} =====")
        try:
            response = requests.get(
                url,
                headers={
                    **BROWSER_HEADERS,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                timeout=30,
            )
            print("status", response.status_code, "bytes", len(response.content), "final", response.url)
            response.raise_for_status()
        except Exception as exc:
            print("FETCH ERROR", repr(exc))
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        links = []
        for anchor in soup.select("a[href]"):
            href = str(anchor.get("href") or "")
            if re.search(href_pattern, href, flags=re.I):
                links.append(anchor)
        print("matching anchors", len(links))

        seen = set()
        shown = 0
        for anchor in links:
            absolute = urljoin(response.url, anchor.get("href"))
            path = urlparse(absolute).path
            if path in seen:
                continue
            seen.add(path)
            text = _clean(anchor.get_text(" ", strip=True)) or _clean(anchor.get("title"))
            if label == "mugglealley" and not re.search(r"/shop/\d+-.+?/\d+-.+?/?$", path, flags=re.I):
                continue
            if label == "ergames" and "/vare/" not in path:
                continue
            print("PRODUCT", path, "|", text[:120])
            node = anchor
            for depth in range(1, 7):
                node = getattr(node, "parent", None)
                if node is None or not getattr(node, "name", None):
                    break
                snippet = _clean(node.get_text(" ", strip=True)).lower()
                hits = [marker for marker in MARKERS if marker in snippet]
                related = {
                    urlparse(urljoin(response.url, a.get("href"))).path
                    for a in node.select("a[href]")
                    if re.search(href_pattern, str(a.get("href") or ""), flags=re.I)
                }
                print(
                    "  A", depth,
                    node.name,
                    classes(node)[:100],
                    "links", len(related),
                    "markers", hits[:8],
                    "text", snippet[:260],
                )
            shown += 1
            if shown >= 3:
                break

        if label == "ergames":
            for anchor in soup.select("a[href]"):
                text = _clean(anchor.get_text(" ", strip=True)).lower()
                href = str(anchor.get("href") or "")
                if "pokemon kort" in text or "page" in href.lower():
                    print("ER NAV", text[:100], "=>", href)


if __name__ == "__main__":
    main()
