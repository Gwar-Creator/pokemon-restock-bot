import base64
import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None

BASE = "https://www.proshop.dk"
LOCATION = "/?s=Pokemon+TCG"
TARGET = BASE + LOCATION


def browser_get(url, accept="*/*"):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36",
        "Accept": accept,
        "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
        "Referer": TARGET,
        "Content-Type": "application/json",
    }
    try:
        response = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        if response.status_code == 200:
            return response, "requests"
    except Exception:
        pass
    if curl_requests is None:
        raise RuntimeError("curl_cffi unavailable")
    response = curl_requests.get(
        url,
        headers=headers,
        timeout=30,
        allow_redirects=True,
        impersonate="chrome",
    )
    return response, "curl_cffi"


def encode_location(location):
    # Exact public frontend implementation:
    # slice leading slash -> btoa -> URL-safe substitutions -> remove padding.
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
    if isinstance(payload, dict):
        print(f"{label} keys={sorted(payload.keys())}")
        for key in ("Hits", "hits", "Count", "count", "ProductCount", "productCount", "Url", "url"):
            if key in payload:
                print(f"{label} {key}={payload[key]}")
        order_list = payload.get("OrderByList") or payload.get("orderByList") or []
        print(f"{label} OrderByList={json.dumps(order_list, ensure_ascii=False)[:4000]}")
        collections = payload.get("Collections") or payload.get("collections") or []
        print(f"{label} Collections={len(collections) if isinstance(collections, list) else type(collections).__name__}")
        if isinstance(collections, list):
            for item in collections[:20]:
                if isinstance(item, dict):
                    print(
                        f"{label} COLLECTION id={item.get('FacetId')} name={item.get('DisplayName')} "
                        f"type={item.get('FacetType')} behavior={item.get('FacetBehaviorType')}"
                    )
        for key in ("Html", "html", "ProductsHtml", "productsHtml"):
            if isinstance(payload.get(key), str):
                products = extract_products(payload[key])
                print(f"{label} {key} chars={len(payload[key])} products={len(products)}")
                for product in products[:30]:
                    print(f"{label} PRODUCT {product[0]} {product[1]} | {product[2]} | {product[3]}")
    else:
        print(f"{label} value={str(payload)[:4000]}")


def main():
    encoded = encode_location(LOCATION)
    print(f"FACET CALL encoded_location={encoded}")

    facet_url = BASE + "/api/facets//" + encoded
    response, method = browser_get(facet_url, "application/json,*/*;q=0.8")
    print(
        f"FACET CALL metadata: method={method} status={response.status_code} "
        f"bytes={len(response.content)} content-type={response.headers.get('content-type')} url={response.url}"
    )
    response.raise_for_status()
    payload = response.json()
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
        order_response, order_method = browser_get(order_url, "application/json,*/*;q=0.8")
        print(
            f"FACET ORDER key={key!r} label={label!r}: method={order_method} "
            f"status={order_response.status_code} bytes={len(order_response.content)} url={order_response.url}"
        )
        if order_response.status_code != 200:
            print(f"FACET ORDER BODY {order_response.text[:1000]}")
            continue
        try:
            order_payload = order_response.json()
        except Exception:
            print(f"FACET ORDER NONJSON {order_response.text[:2000]}")
            continue
        summarize_json(f"FACET ORDER {key}", order_payload)


if __name__ == "__main__":
    main()
