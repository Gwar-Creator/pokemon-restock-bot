import os
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

# Publicly observed production Coop app hostnames. We only use unauthenticated
# read-only GET requests. No login/session tokens and no auth bypass attempts.
SEED_URLS = (
    "https://barcode.app.coop.dk/",
    "https://scan-pay.app.coop.dk/",
    "https://apim.app.coop.dk/",
    "https://member.app.coop.dk/",
    "https://mobile-payment.app.coop.dk/",
    "https://app.coop.dk/",
)

# Common public documentation/health paths. 401/403 is recorded as a signal,
# never bypassed. We do not brute-force arbitrary paths.
PUBLIC_PATHS = (
    "",
    "health",
    "healthz",
    "swagger",
    "swagger/index.html",
    "swagger/v1/swagger.json",
    "openapi.json",
    "docs",
    "api",
)

KEYWORDS = (
    "barcode",
    "ean",
    "gtin",
    "product",
    "article",
    "item",
    "assortment",
    "availability",
    "stock",
    "quantity",
    "inventory",
    "store",
    "shop",
    "scan-pay",
    "scanpay",
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json,text/plain,*/*",
}


def request(url):
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=15,
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


def interesting_text(text):
    value = str(text or "").lower()
    return any(keyword in value for keyword in KEYWORDS)


def summarize_host(url):
    parsed = urlparse(url)
    return parsed.netloc or url


def extract_candidate_strings(text, base_url):
    found = set()
    if not text:
        return found

    for absolute in extract_absolute_urls(text):
        if interesting_text(absolute):
            found.add(absolute)

    # API-ish relative strings in HTML/JS/OpenAPI JSON.
    patterns = (
        r'["\'](/[^"\']{0,180}(?:barcode|ean|gtin|product|article|item|assortment|availability|stock|quantity|inventory|store)[^"\']{0,180})["\']',
        r'["\']([^"\']{0,180}(?:scan-pay|scanpay)[^"\']{0,180})["\']',
    )
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            if len(match) <= 300:
                found.add(urljoin(base_url, match))

    return found


def inspect_html_and_scripts(response):
    candidates = set()
    scripts = []
    content_type = response.headers.get("content-type", "").lower()
    body = response.text[:3_000_000]

    candidates.update(extract_candidate_strings(body, response.url))

    if "html" in content_type:
        soup = BeautifulSoup(body, "html.parser")
        for script in soup.find_all("script", src=True):
            scripts.append(urljoin(response.url, script["src"]))

        for script_url in scripts[:25]:
            script_response, script_error = request(script_url)
            if script_error or script_response is None:
                continue
            candidates.update(
                extract_candidate_strings(
                    script_response.text[:3_000_000],
                    response.url,
                )
            )

    return scripts, candidates


def inspect_seed(seed):
    probes = []
    all_candidates = set()
    total_scripts = 0

    for path in PUBLIC_PATHS:
        url = urljoin(seed, path)
        response, error = request(url)
        if error:
            probes.append(
                {
                    "path": path or "/",
                    "status": "ERR",
                    "content_type": "",
                    "final_url": "",
                    "error": error,
                }
            )
            continue

        content_type = response.headers.get("content-type", "")
        probes.append(
            {
                "path": path or "/",
                "status": response.status_code,
                "content_type": content_type,
                "final_url": response.url,
                "error": None,
            }
        )

        # Only inspect successful/public content. 401/403 is a useful boundary.
        if response.status_code < 400:
            scripts, candidates = inspect_html_and_scripts(response)
            total_scripts += len(scripts)
            all_candidates.update(candidates)

    return {
        "seed": seed,
        "probes": probes,
        "scripts": total_scripts,
        "candidates": sorted(all_candidates),
    }


def useful_probe(probe):
    status = probe["status"]
    if status == "ERR":
        return False
    return int(status) not in (404,)


def send_report(results):
    if not WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL mangler")

    discovered = []
    for result in results:
        for url in result["candidates"]:
            if url not in discovered:
                discovered.append(url)

    lines = [
        "**Read-only V2 - kun offentlige GET requests. Ingen login/auth bypass.**",
        "Mål: finde den konkrete prod-service bag barcode/Scan&Betal.",
        "",
        "**Produktions-hosts:**",
    ]

    for result in results:
        host = summarize_host(result["seed"])
        signals = [probe for probe in result["probes"] if useful_probe(probe)]
        if not signals:
            root = result["probes"][0]
            if root["status"] == "ERR":
                lines.append(f"• {host}: ❌ {root['error'][:90]}")
            else:
                lines.append(f"• {host}: root **HTTP {root['status']}** · ingen public docs")
            continue

        status_text = ", ".join(
            f"{probe['path']}={probe['status']}"
            for probe in signals[:5]
        )
        lines.append(
            f"• **{host}**: {status_text} · {result['scripts']} scripts"
        )

    lines.append("")
    if discovered:
        lines.append(f"**Produkt/EAN/stock-strenge fundet: {len(discovered)}**")
        for url in discovered[:18]:
            lines.append(f"• `{url[:240]}`")
    else:
        lines.append("**Ingen konkrete produkt/EAN/stock-ruter fundet i public content.**")

    lines.extend(
        [
            "",
            "**Fortolkning:**",
            "`barcode.app.coop.dk` og `scan-pay.app.coop.dk` er nu de primære spor. "
            "Hvis en service kun svarer 401/403, har vi fundet servicegrænsen men "
            "stopper dér. Hvis Swagger/OpenAPI eller en public route findes, går "
            "næste test på butik + kendt EAN og undersøger kun svarets felter.",
        ]
    )

    payload = {
        "username": "MasterBot",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": "🧪 COOP APP ENDPOINT PROBE V2",
                "description": "\n".join(lines)[:4090],
                "color": 0x5865F2,
                "footer": {"text": "MasterBot · Coop barcode/scan-pay discovery"},
            }
        ],
    }

    response = requests.post(WEBHOOK_URL, json=payload, timeout=20)
    response.raise_for_status()


if __name__ == "__main__":
    results = []
    for seed in SEED_URLS:
        print(f"COOP APP PROBE V2: {seed}")
        results.append(inspect_seed(seed))
    send_report(results)
