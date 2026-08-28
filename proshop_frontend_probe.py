import base64
import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None

BASE = "https://www.proshop.dk"
LOCATION = "/?s=Pokemon+TCG"
TARGET = BASE + LOCATION


def headers(accept="*/*", referer=None):
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36",
        "Accept": accept,
        "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
        "Referer": referer or TARGET,
        "Content-Type": "application/json",
    }


def encode_location(location):
    raw = location[1:] if location.startswith("/") else location
    return base64.b64encode(raw.encode("ascii")).decode("ascii").replace("+", "-").replace("/", "_").rstrip("=")


def extract_products(fragment):
    soup = BeautifulSoup(fragment or "", "html.parser")
    products = []
    seen = set()
    for anchor in soup.select('a[href*="/Pokemon/"]'):
        href = anchor.get("href") or ""
        match = re.search(r"/Pokemon/([^/?#]+)/([0-9]{6,9})(?:[/?#]|$)", href, re.I)
        if not match:
            continue
        slug, product_id = match.groups()
        if product_id in seen:
            continue
        seen.add(product_id)
        card = anchor.find_parent("li") or anchor.parent
        text = " ".join((card or anchor).stripped_strings)
        products.append((product_id, slug, text[:500], urljoin(BASE, href)))
    return products


def summarize_json(label, payload):
    print(f"{label} type={type(payload).__name__}")
    if not isinstance(payload, dict):
        print(f"{label} value={str(payload)[:4000]}")
        return

    print(f"{label} keys={sorted(payload.keys())}")
    for key, value in payload.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            rendered = str(value)
            if len(rendered) <= 400:
                print(f"{label} FIELD {key}={rendered}")

    order_list = payload.get("OrderByList") or payload.get("orderByList") or []
    print(f"{label} OrderByList={json.dumps(order_list, ensure_ascii=False)[:5000]}")

    collections = payload.get("Collections") or payload.get("collections") or []
    print(f"{label} Collections={len(collections) if isinstance(collections, list) else type(collections).__name__}")
    if isinstance(collections, list):
        for item in collections[:30]:
            if isinstance(item, dict):
                print(f"{label} COLLECTION {json.dumps(item, ensure_ascii=False)[:1200]}")

    for key, value in payload.items():
        if not isinstance(value, str):
            continue
        if "<" not in value or ">" not in value:
            continue
        products = extract_products(value)
        print(f"{label} HTMLFIELD {key} chars={len(value)} products={len(products)}")
        for product in products[:30]:
            print(f"{label} PRODUCT {product[0]} {product[1]} | {product[2]} | {product[3]}")


def main():
    if curl_requests is None:
        raise RuntimeError("curl_cffi unavailable")

    encoded = encode_location(LOCATION)
    print(f"FACET SESSION encoded_location={encoded}")

    with curl_requests.Session(impersonate="chrome") as session:
        page = session.get(
            TARGET,
            headers=headers("text/html,application/xhtml+xml,*/*;q=0.8", BASE + "/"),
            timeout=30,
            allow_redirects=True,
        )
        print(
            f"FACET SESSION warmup: status={page.status_code} bytes={len(page.content)} "
            f"cookie_names={sorted(session.cookies.get_dict().keys())}"
        )
        page.raise_for_status()

        candidates = (
            BASE + "/api/facets//" + encoded,
            BASE + "/api/facets/" + encoded,
        )
        payload = None
        working_url = None

        for facet_url in candidates:
            response = session.get(
                facet_url,
                headers=headers("application/json,*/*;q=0.8", TARGET),
                timeout=30,
                allow_redirects=True,
            )
            print(
                f"FACET SESSION metadata: status={response.status_code} bytes={len(response.content)} "
                f"content-type={response.headers.get('content-type')} url={response.url}"
            )
            if response.status_code != 200:
                print(f"FACET SESSION BODY {response.text[:400]}")
                continue
            try:
                payload = response.json()
            except Exception:
                print(f"FACET SESSION NONJSON {response.text[:1000]}")
                continue
            working_url = facet_url
            break

        if payload is None:
            print("FACET SESSION RESULT no public facet JSON from GitHub runner")
            return

        print(f"FACET SESSION RESULT working_url={working_url}")
        summarize_json("FACET META", payload)

        order_list = payload.get("OrderByList") or payload.get("orderByList") or []
        if not isinstance(order_list, list):
            return

        for order in order_list:
            if not isinstance(order, dict):
                continue
            key = order.get("Key") if "Key" in order else order.get("key")
            label = order.get("Value") if "Value" in order else order.get("value")
            if key is None:
                continue
            order_url = BASE + f"/api/facets/order/{key}/" + encoded
            response = session.get(
                order_url,
                headers=headers("application/json,*/*;q=0.8", TARGET),
                timeout=30,
                allow_redirects=True,
            )
            print(
                f"FACET ORDER key={key!r} label={label!r}: status={response.status_code} "
                f"bytes={len(response.content)} url={response.url}"
            )
            if response.status_code != 200:
                print(f"FACET ORDER BODY {response.text[:400]}")
                continue
            try:
                summarize_json(f"FACET ORDER {key}", response.json())
            except Exception:
                print(f"FACET ORDER NONJSON {response.text[:1000]}")


if __name__ == "__main__":
    main()
