import re
from html import unescape
from urllib.parse import urljoin, urlparse

import requests

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None

TARGETS = (
    "https://www.proshop.dk/",
    "https://www.proshop.dk/?s=Pokemon+TCG",
    "https://www.proshop.dk/Pokemon/Pokemon",
    "https://www.proshop.dk/Pokemon/Pokemon-TCG-Mega-Charizard-X-ex-Ultra-Premium-Collection/3417744",
)

SAFE_HOST_SUFFIXES = ("proshop.dk",)
MAX_ASSETS = 30

SCRIPT_SRC_RE = re.compile(r"<script[^>]+src=[\"']([^\"']+)[\"']", re.I)
LINK_HREF_RE = re.compile(r"<link[^>]+href=[\"']([^\"']+)[\"']", re.I)

ENDPOINT_PATTERNS = (
    re.compile(r"[\"']((?:https?:)?//[^\"'\s]+(?:api|search|suggest|autocomplete|graphql|product)[^\"'\s]*)[\"']", re.I),
    re.compile(r"[\"'](/[^\"'\s]*(?:api|search|suggest|autocomplete|graphql|product)[^\"'\s]*)[\"']", re.I),
)

KEYWORDS = (
    "fetch(", "axios", "xmlhttprequest", "/api/", "autocomplete", "suggest",
    "search", "graphql", "productsearch", "searchproduct", "instantsearch",
    "algolia", "meilisearch", "typesense", "elastic", "solr",
)


def allowed_url(url):
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return any(host == suffix or host.endswith("." + suffix) for suffix in SAFE_HOST_SUFFIXES)


def fetch_direct(url):
    attempts = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
    }

    try:
        response = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        attempts.append(("requests", response.status_code, len(response.content), response.url, response.text))
    except Exception as error:
        attempts.append(("requests", None, 0, url, f"ERROR {error}"))

    if curl_requests is not None:
        try:
            response = curl_requests.get(
                url,
                headers=headers,
                timeout=30,
                allow_redirects=True,
                impersonate="chrome",
            )
            attempts.append(("curl_cffi", response.status_code, len(response.content), response.url, response.text))
        except Exception as error:
            attempts.append(("curl_cffi", None, 0, url, f"ERROR {error}"))

    for method, status, size, final_url, text in attempts:
        print(f"FRONTEND fetch {method}: {url} -> {status} bytes={size} final={final_url}")

    successful = [row for row in attempts if row[1] == 200 and "<html" in row[4].lower()]
    if not successful:
        return None, attempts
    successful.sort(key=lambda row: row[2], reverse=True)
    return successful[0][4], attempts


def extract_assets(base_url, html):
    urls = []
    for raw in SCRIPT_SRC_RE.findall(html or "") + LINK_HREF_RE.findall(html or ""):
        raw = unescape(raw.strip())
        if not raw or raw.startswith("data:"):
            continue
        full = urljoin(base_url, raw)
        if allowed_url(full):
            urls.append(full)
    return list(dict.fromkeys(urls))


def endpoint_candidates(base_url, text):
    found = []
    for pattern in ENDPOINT_PATTERNS:
        for match in pattern.findall(text or ""):
            candidate = unescape(match.strip())
            if candidate.startswith("//"):
                candidate = "https:" + candidate
            elif candidate.startswith("/"):
                candidate = urljoin(base_url, candidate)
            if allowed_url(candidate):
                found.append(candidate)
    return list(dict.fromkeys(found))


def print_keyword_context(label, text):
    lowered = (text or "").lower()
    hits = 0
    for keyword in KEYWORDS:
        start = 0
        needle = keyword.lower()
        while hits < 60:
            idx = lowered.find(needle, start)
            if idx < 0:
                break
            left = max(0, idx - 180)
            right = min(len(text), idx + 300)
            snippet = re.sub(r"\s+", " ", text[left:right])
            print(f"FRONTEND context {label} [{keyword}]: {snippet[:520]}")
            hits += 1
            start = idx + len(needle)
        if hits >= 60:
            break


def fetch_asset(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36",
        "Accept": "*/*",
        "Referer": "https://www.proshop.dk/",
    }
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.text, response.status_code, len(response.content)
        if curl_requests is not None:
            response = curl_requests.get(url, headers=headers, timeout=30, impersonate="chrome")
            return response.text, response.status_code, len(response.content)
        return response.text, response.status_code, len(response.content)
    except Exception as first_error:
        if curl_requests is not None:
            try:
                response = curl_requests.get(url, headers=headers, timeout=30, impersonate="chrome")
                return response.text, response.status_code, len(response.content)
            except Exception as second_error:
                return f"ERROR {first_error}; {second_error}", None, 0
        return f"ERROR {first_error}", None, 0


def main():
    all_assets = []
    all_candidates = []

    for url in TARGETS:
        html, attempts = fetch_direct(url)
        if not html:
            print(f"FRONTEND no raw HTML for {url}")
            continue

        print(f"FRONTEND raw HTML success: {url} chars={len(html)}")
        assets = extract_assets(url, html)
        print(f"FRONTEND assets {url}: {len(assets)}")
        for asset in assets[:40]:
            print(f"FRONTEND asset: {asset}")
        all_assets.extend(assets)

        candidates = endpoint_candidates(url, html)
        for candidate in candidates:
            print(f"FRONTEND endpoint-inline: {candidate}")
        all_candidates.extend(candidates)
        print_keyword_context("html", html)

    all_assets = list(dict.fromkeys(all_assets))[:MAX_ASSETS]
    print(f"FRONTEND unique allowed assets to inspect: {len(all_assets)}")

    for asset in all_assets:
        text, status, size = fetch_asset(asset)
        print(f"FRONTEND asset fetch: {status} bytes={size} {asset}")
        if status != 200 or not text:
            continue
        candidates = endpoint_candidates(asset, text)
        for candidate in candidates:
            print(f"FRONTEND endpoint-js: {candidate}")
        all_candidates.extend(candidates)
        print_keyword_context(asset.rsplit("/", 1)[-1][:80], text)

    unique_candidates = list(dict.fromkeys(all_candidates))
    print(f"FRONTEND SUMMARY endpoint_candidates={len(unique_candidates)}")
    for candidate in unique_candidates[:100]:
        print(f"FRONTEND CANDIDATE {candidate}")


if __name__ == "__main__":
    main()
