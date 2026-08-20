import os
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

SEED_URLS = (
    "https://app.coop.dk/",
    "https://prime.app.coop.dk/",
    "https://static.scan-pay.acs.coop.dk/",
    "https://acs.coop.dk/",
    "https://api.coop.dk/",
)

KEYWORDS = (
    "scan",
    "pay",
    "product",
    "barcode",
    "ean",
    "gtin",
    "assortment",
    "availability",
    "stock",
    "quantity",
    "inventory",
    "store",
    "kardex",
    "coop.dk",
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )
}


def request(url):
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20,
            allow_redirects=True,
        )
        return response, None
    except Exception as error:
        return None, f"{type(error).__name__}: {error}"


def extract_absolute_urls(text):
    if not text:
        return set()
    pattern = r'https?://[^\s"\'<>\\)]+'
    return {match.rstrip(".,;]") for match in re.findall(pattern, text)}


def interesting_url(url):
    text = url.lower()
    return any(keyword in text for keyword in KEYWORDS)


def summarize_host(url):
    parsed = urlparse(url)
    return parsed.netloc or url


def inspect_seed(seed):
    response, error = request(seed)
    if error:
        return {
            "seed": seed,
            "status": "ERR",
            "final_url": "",
            "scripts": [],
            "interesting": [],
            "error": error,
        }

    final_url = response.url
    content_type = response.headers.get("content-type", "")
    text = response.text if "text" in content_type or "html" in content_type or "javascript" in content_type else ""

    interesting = set(url for url in extract_absolute_urls(text) if interesting_url(url))
    scripts = []

    if "html" in content_type and text:
        soup = BeautifulSoup(text, "html.parser")
        for script in soup.find_all("script", src=True):
            script_url = urljoin(final_url, script["src"])
            scripts.append(script_url)

    for script_url in scripts[:20]:
        script_response, script_error = request(script_url)
        if script_error or script_response is None:
            continue
        body = script_response.text[:2_000_000]
        for found in extract_absolute_urls(body):
            if interesting_url(found):
                interesting.add(found)

        # Relative API-ish paths are also useful if absolute hosts are injected elsewhere.
        relative_patterns = (
            r'["\'](/[^"\']*(?:product|barcode|ean|gtin|assortment|availability|stock|inventory|store)[^"\']*)["\']',
            r'["\']([^"\']*(?:scan-pay|scanandpay|scan_and_pay)[^"\']*)["\']',
        )
        for pattern in relative_patterns:
            for match in re.findall(pattern, body, flags=re.IGNORECASE):
                if len(match) <= 220:
                    interesting.add(urljoin(final_url, match))

    return {
        "seed": seed,
        "status": response.status_code,
        "final_url": final_url,
        "scripts": scripts,
        "interesting": sorted(interesting),
        "error": None,
    }


def send_report(results):
    if not WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL mangler")

    discovered = []
    for result in results:
        for url in result["interesting"]:
            if url not in discovered:
                discovered.append(url)

    lines = [
        "**Read-only discovery probe - ingen køb, login eller ændring af Coop-data.**",
        "Mål: finde offentligt synlige app/Scan&Betal endpoints til næste EAN-test.",
        "",
        "**Seed-status:**",
    ]

    for result in results:
        host = summarize_host(result["seed"])
        if result["error"]:
            lines.append(f"• {host}: ❌ {result['error'][:100]}")
        else:
            redirect = ""
            if result["final_url"].rstrip("/") != result["seed"].rstrip("/"):
                redirect = f" → {result['final_url']}"
            lines.append(
                f"• {host}: **HTTP {result['status']}** · {len(result['scripts'])} scripts{redirect}"
            )

    lines.append("")
    if discovered:
        lines.append(f"**Interessante endpoint-/URL-signaler: {len(discovered)}**")
        for url in discovered[:20]:
            lines.append(f"• `{url[:220]}`")
    else:
        lines.append("**Ingen brugbare endpoint-strenge fundet endnu.**")

    lines.extend(
        [
            "",
            "**Gate:**",
            "Vi går kun videre til EAN + butik, hvis denne probe finder et offentligt "
            "anvendeligt produkt/Scan&Betal-endpoint. Et 401/403-signal er nyttigt, "
            "men vi forsøger ikke at omgå login eller adgangskontrol.",
        ]
    )

    payload = {
        "username": "MasterBot",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": "🧪 COOP APP ENDPOINT PROBE V1",
                "description": "\n".join(lines)[:4090],
                "color": 0x5865F2,
                "footer": {"text": "MasterBot · Coop app endpoint discovery"},
            }
        ],
    }

    response = requests.post(WEBHOOK_URL, json=payload, timeout=20)
    response.raise_for_status()


if __name__ == "__main__":
    results = []
    for seed in SEED_URLS:
        print(f"COOP APP PROBE: {seed}")
        results.append(inspect_seed(seed))
    send_report(results)
