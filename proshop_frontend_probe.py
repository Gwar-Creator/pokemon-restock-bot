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
NEEDLES = (
    "createBToAUrl",
    "10469:",
    "createBToA",
    "btoa(",
    "base64",
    "api/facets",
)


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


def contexts(text, needle, radius=2600, max_hits=4):
    low = text.lower()
    target = needle.lower()
    start = 0
    out = []
    while len(out) < max_hits:
        idx = low.find(target, start)
        if idx < 0:
            break
        left = max(0, idx - radius)
        right = min(len(text), idx + radius)
        out.append(re.sub(r"\s+", " ", text[left:right]))
        start = idx + len(target)
    return out


def main():
    response, method = browser_get(TARGET, "text/html,application/xhtml+xml,*/*;q=0.8")
    response.raise_for_status()
    html = response.text or ""
    print(f"ENCODER page: method={method} status={response.status_code} bytes={len(response.content)}")

    soup = BeautifulSoup(html, "html.parser")
    scripts = [
        urljoin(TARGET, unescape(script.get("src") or ""))
        for script in soup.find_all("script", src=True)
        if script.get("src")
    ]
    scripts = list(dict.fromkeys(scripts))
    print(f"ENCODER scripts={len(scripts)}")
    for url in scripts:
        print(f"ENCODER SCRIPT {url}")

    matches = 0
    for script_url in scripts:
        js_response, js_method = browser_get(script_url)
        if js_response.status_code != 200:
            print(f"ENCODER fetch failed {js_response.status_code}: {script_url}")
            continue
        text = js_response.text or ""
        hit_needles = [needle for needle in NEEDLES if needle.lower() in text.lower()]
        if not hit_needles:
            continue
        matches += 1
        print(
            f"ENCODER MATCH {script_url}: method={js_method} bytes={len(js_response.content)} "
            f"needles={','.join(hit_needles)}"
        )
        for needle in hit_needles:
            for snippet in contexts(text, needle):
                print(f"ENCODER CONTEXT [{needle}] {snippet}")

    print(f"ENCODER SUMMARY matched_assets={matches}")


if __name__ == "__main__":
    main()
