#!/usr/bin/env python3
"""Read-only, bounded Proshop product-detail availability experiment.

Never makes Discord posts or mutates state. A 200 response is NOT counted as
a successful product observation unless the real product number is present.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import re

import requests

SKUS = {
    "3417744": "https://www.proshop.dk/Pokemon/Pokemon-TCG-Mega-Charizard-X-ex-Ultra-Premium-Collection/3417744",
    "3447592": "https://www.proshop.dk/Pokemon/Pokemon-TCG-Mega-EvolutionChaos-Rising-Booster-box-with-36-boosters/3447592",
    "3478496": "https://www.proshop.dk/Pokemon/Pokemon-TCG-Mega-Greninja-ex-Premium-Collection/3478496",
    "3478498": "https://www.proshop.dk/Pokemon/Pokemon-TCG-First-Partner-Illustration-Collection-Box-Series-2/3478498",
    "3519999": "https://www.proshop.dk/Pokemon/Pokemon-TCG-Mini-Tins-30th-Celebration-assorted/3519999",
    "3447589": "https://www.proshop.dk/Pokemon/Pokemon-TCG-Mega-Zygarde-ex-Premium-Collection/3447589",
}
STOCK = re.compile(
    r"ikke på lager|udsolgt|bestillingsvare|bestilt|fjernlager|på lager|pa lager",
    re.I,
)
PRICE = re.compile(r"(?<!\d)\d{1,3}(?:\.\d{3})*(?:,\d{2})?\s*kr\.", re.I)


def fetch(item):
    sku, url = item
    try:
        response = requests.get(
            "https://r.jina.ai/" + url,
            headers={
                "Accept": "text/plain, text/markdown;q=0.9, */*;q=0.5",
                "User-Agent": "Pokemon-Restock-Proshop-ReadOnlyProbe/1",
                "x-no-cache": "true",
                "x-engine": "browser",
            },
            timeout=48,
        )
        body = response.text
        body_start = body[:6000]
        item_no = re.search(r"Varenummer:\s*\**\s*(\d{7})\s*\**", body_start, re.I)
        verified = bool(item_no and item_no.group(1) == sku)
        # A product page can return a valid HTTP 200 but display a generic
        # brand listing. Never interpret such results as product availability.
        section = body_start[item_no.end():][:3600] if verified else ""
        stock = STOCK.findall(section)
        price = PRICE.findall(section)
        return {
            "sku": sku,
            "http": response.status_code,
            "body_chars": len(body),
            "product_verified": verified,
            "seen_item_no": item_no.group(1) if item_no else None,
            "first_status_matches": stock[:8],
            "first_prices": price[:4],
            "status_context": [
                re.sub(r"\s+", " ", section[max(0, m.start()-90):m.end()+110])
                for m in list(STOCK.finditer(section))[:3]
            ],
            "preview": re.sub(r"\s+", " ", body[:230]),
        }
    except requests.RequestException as error:
        return {"sku": sku, "error_type": type(error).__name__}


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in as_completed([pool.submit(fetch, row) for row in SKUS.items()]):
            print("PROSHOP SKU DETAIL", future.result(), flush=True)
