import re
from html import unescape
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None

BASE = "https://www.proshop.dk"
TARGET = BASE + "/?s=Pokemon+TCG"


def browser_get(url, accept="*/*"):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36",
        "Accept": accept,
        "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
        "Referer": TARGET,
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


def main():
    response, method = browser_get(TARGET, "text/html,application/xhtml+xml,*/*;q=0.8")
    response.raise_for_status()
    html = response.text or ""
    print(f"FACET page: method={method} status={response.status_code} bytes={len(response.content)}")

    soup = BeautifulSoup(html, "html.parser")
    scripts = []
    for script in soup.find_all("script", src=True):
        scripts.append(urljoin(TARGET, unescape(script.get("src") or "")))
    scripts = list(dict.fromkeys(scripts))
    print(f"FACET scripts={len(scripts)}")

    # Print page-level data attributes and nearby markup that appear to seed
    # the product-list/facet controller. These are public values rendered to
    # every browser and help us reproduce exactly what the frontend requests.
    facet_tags = []
    for tag in soup.find_all(True):
        attrs = tag.attrs or {}
        serialized = " ".join(f"{k}={v}" for k, v in attrs.items())
        if "facet" in serialized.lower() or "productlist" in serialized.lower() or "product-list" in serialized.lower():
            facet_tags.append(str(tag)[:1800])
    print(f"FACET seed tags={len(facet_tags)}")
    for item in facet_tags[:30]:
        print("FACET SEED " + re.sub(r"\s+", " ", item))

    inspected = 0
    for script_url in scripts:
        js_response, js_method = browser_get(script_url)
        if js_response.status_code != 200:
            continue
        text = js_response.text or ""
        low = text.lower()
        if "api/facets" not in low and "loadfacet" not in low:
            continue
        inspected += 1
        print(
            f"FACET JS {script_url}: method={js_method} status={js_response.status_code} "
            f"bytes={len(js_response.content)}"
        )
        for needle in ("api/facets", "loadFacetCollections", "loadFacets", "selectedFacetIds", "fetchUrlGet", "fetchUrlPost"):
            start = 0
            while True:
                idx = text.find(needle, start)
                if idx < 0:
                    idx = low.find(needle.lower(), start)
                if idx < 0:
                    break
                left = max(0, idx - 1400)
                right = min(len(text), idx + 2400)
                snippet = re.sub(r"\s+", " ", text[left:right])
                print(f"FACET CONTEXT [{needle}] {snippet}")
                start = idx + len(needle)
                if start > idx + 1 and start > len(text):
                    break
    print(f"FACET JS inspected={inspected}")


if __name__ == "__main__":
    main()
