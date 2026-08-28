import re
from html import unescape
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None

BASE = "https://www.proshop.dk"
AUTOCOMPLETE = BASE + "/ClientPlugins/AutoComplete/SearchResult"
SEARCH_TERMS = (
    "Pokemon TCG",
    "Pokemon booster",
    "Pokemon collection",
    "Pokemon Elite Trainer Box",
    "Ascended Heroes",
    "Pokemon Ascended Heroes",
    "First Partner",
    "Mega Evolution",
    "30th Pokemon",
)

PRODUCT_LINK_RE = re.compile(
    r"(?:https?://(?:www\.)?proshop\.dk)?/Pokemon/([^\"'<>?\s]+)/([0-9]{6,9})",
    re.IGNORECASE,
)


def browser_get(url, accept="text/html,*/*"):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36",
        "Accept": accept,
        "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
        "Referer": BASE + "/",
        "X-Requested-With": "XMLHttpRequest",
    }

    try:
        response = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        if response.status_code == 200:
            return response, "requests"
    except Exception:
        pass

    if curl_requests is None:
        return response if "response" in locals() else None, "requests"

    response = curl_requests.get(
        url,
        headers=headers,
        timeout=30,
        allow_redirects=True,
        impersonate="chrome",
    )
    return response, "curl_cffi"


def extract_products(html):
    products = {}
    soup = BeautifulSoup(html or "", "html.parser")

    for anchor in soup.find_all("a", href=True):
        href = unescape(anchor.get("href") or "")
        match = PRODUCT_LINK_RE.search(href)
        if not match:
            continue
        slug, product_id = match.groups()
        text = " ".join(anchor.stripped_strings)
        container = anchor
        for _ in range(4):
            parent = getattr(container, "parent", None)
            if parent is None:
                break
            parent_text = " ".join(parent.stripped_strings)
            if len(parent_text) <= 600:
                container = parent
            else:
                break
        container_text = " ".join(container.stripped_strings)
        products[product_id] = {
            "id": product_id,
            "slug": slug,
            "url": urljoin(BASE, href),
            "anchor_text": text[:220],
            "context": container_text[:500],
        }

    # Fallback in case links are present in attributes/script snippets rather
    # than normal anchors.
    for slug, product_id in PRODUCT_LINK_RE.findall(html or ""):
        products.setdefault(
            product_id,
            {
                "id": product_id,
                "slug": slug,
                "url": f"{BASE}/Pokemon/{slug}/{product_id}",
                "anchor_text": "",
                "context": "",
            },
        )
    return products


def probe_autocomplete(term):
    url = AUTOCOMPLETE + "?searchInput=" + quote(term)
    response, method = browser_get(url)
    if response is None:
        print(f"AUTO {term!r}: no response")
        return {}

    text = response.text or ""
    products = extract_products(text)
    print(
        f"AUTO {term!r}: method={method} status={response.status_code} "
        f"bytes={len(response.content)} products={len(products)}"
    )
    for product in products.values():
        print(
            f"AUTO PRODUCT {term!r} {product['id']}: {product['slug']} | "
            f"{product['anchor_text']} | {product['context']} | {product['url']}"
        )
    return products


def probe_full_search(term):
    url = BASE + "/?s=" + quote(term)
    response, method = browser_get(url)
    if response is None:
        print(f"FULL {term!r}: no response")
        return {}
    products = extract_products(response.text or "")
    print(
        f"FULL {term!r}: method={method} status={response.status_code} "
        f"bytes={len(response.content)} products={len(products)}"
    )
    for product in list(products.values())[:40]:
        print(
            f"FULL PRODUCT {term!r} {product['id']}: {product['slug']} | "
            f"{product['context']} | {product['url']}"
        )
    return products


def main():
    all_auto = {}
    all_full = {}

    for term in SEARCH_TERMS:
        auto = probe_autocomplete(term)
        for product_id, product in auto.items():
            all_auto.setdefault(product_id, product)

    # Full search is heavier; compare the two most useful broad queries plus
    # the exact set name we care about.
    for term in ("Pokemon TCG", "Pokemon booster", "Ascended Heroes"):
        full = probe_full_search(term)
        for product_id, product in full.items():
            all_full.setdefault(product_id, product)

    auto_ids = set(all_auto)
    full_ids = set(all_full)
    print(
        f"DISCOVERY SUMMARY autocomplete_unique={len(auto_ids)} "
        f"full_search_unique={len(full_ids)} "
        f"autocomplete_only={len(auto_ids - full_ids)} "
        f"full_only={len(full_ids - auto_ids)}"
    )
    for product_id in sorted(auto_ids - full_ids):
        product = all_auto[product_id]
        print(
            f"DISCOVERY AUTOCOMPLETE-ONLY {product_id}: "
            f"{product['slug']} | {product['context']} | {product['url']}"
        )


if __name__ == "__main__":
    main()
