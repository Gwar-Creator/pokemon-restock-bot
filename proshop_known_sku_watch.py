"""Conservative Proshop TCG title fix and bounded verification of known SKUs.

This supplements (not replaces) category discovery. Never trust an HTTP 200
as a stock signal: Reader sometimes redirects silently to a generic catalogue.
"""
import re
import time

import requests

KNOWN_PRODUCTS = {
    "3417744": "https://www.proshop.dk/Pokemon/Pokemon-TCG-Mega-Charizard-X-ex-Ultra-Premium-Collection/3417744",
    "3447592": "https://www.proshop.dk/Pokemon/Pokemon-TCG-Mega-EvolutionChaos-Rising-Booster-box-with-36-boosters/3447592",
    "3478496": "https://www.proshop.dk/Pokemon/Pokemon-TCG-Mega-Greninja-ex-Premium-Collection/3478496",
    "3478497": "https://www.proshop.dk/Pokemon/Pokemon-TCG-2-pack-Booster/3478497",
    "3478498": "https://www.proshop.dk/Pokemon/Pokemon-TCG-First-Partner-Illustration-Collection-Box-Series-2/3478498",
    "3519999": "https://www.proshop.dk/Pokemon/Pokemon-TCG-Mini-Tins-30th-Celebration-assorted/3519999",
}
CHECK_INTERVAL_SECONDS = 15 * 60
MAX_CHECKS_PER_SCAN = 2
REQUEST_TIMEOUT_SECONDS = 20


def is_proshop_tcg_title(value, original):
    """Admit real 2-pack Booster SKUs without allowing booster-themed binders."""
    name = re.sub(r"\s+", " ", str(value or "").lower())
    if re.search(r"\bpokemon\s+tcg\s+\d+[\s-]*pack\s+boosters?\b", name):
        accessory = re.search(
            r"\b(portfolio|sleeves?|binder|album|deck\s*box|playmat|"
            r"kortlommer|samlemappe|opbevaring|storage\s*box)\b",
            name,
        )
        if not accessory:
            return True
    return bool(original(value))


def parse_verified_detail(page, sku, url):
    """Accept only exact SKU identity and *own-product* sale availability.

    The primary product information is inspected before recommendation cards.
    Legal disclaimer references to 'udsolgte varer' are not stock data.
    """
    page = str(page or "")
    sku = str(sku)
    source = re.search(r"(?m)^URL Source:\s*(\S+)", page)
    if not source or source.group(1).rstrip("/") != url:
        return None
    title = re.search(r"(?m)^Title:\s*([^\n]+)", page)
    if not title or "pokemon tcg" not in title.group(1).lower():
        return None
    marker = re.search(r"\bVarenummer:\s*\**\s*(\d{7})\s*\**", page)
    if not marker or marker.group(1) != sku:
        return None

    # Recommendations typically start at a second image card, not at the
    # actual product. Do not interpret their 'på lager' as this SKU's stock.
    own = page[marker.end():]
    boundary = re.search(
        r"(?m)^\*\s+\[!\[Image\s+[2-9]\d*|"
        r"(?m)^#{1,4}\s+(?:Lignende|Relaterede|Anbefalede)\s+produkter",
        own,
    )
    if boundary:
        own = own[:boundary.start()]
    # The 'Generelt' section contains a stock-irrelevant legal disclaimer.
    general = re.search(r"(?m)^#{1,3}\s+Generelt\b", own)
    if general:
        own = own[:general.start()]

    lowered = re.sub(r"\s+", " ", own).lower()
    if re.search(r"varen er udgået|produktet er udgået", lowered):
        stock = "UDSOLGT"
    elif re.search(r"vi tager.{0,70}ikke imod ordrer på dette produkt", lowered):
        stock = "UDSOLGT"
    elif re.search(r"\bikke på lager\b|\budsolgt\b", lowered):
        stock = "UDSOLGT"
    elif re.search(r"\bpå lager\b", lowered):
        stock = "PÅ LAGER"
    elif "fjernlager" in lowered:
        stock = "FJERNLAGER"
    else:
        # "Bestillingsvare" without a real buy action is not orderable.
        stock = "UKENDT"

    if stock == "UKENDT":
        return None

    # Pricing is only trusted for an in-stock product with a price near the
    # product's own availability, never delivery fees or similar items.
    price = None
    if stock == "PÅ LAGER":
        match = re.search(r"(?<!\d)(\d{1,3}(?:\.\d{3})*|\d{1,5})(?:,(\d{2}))?\s*kr\.?", own, re.I)
        if match:
            price = float(match.group(1).replace(".", "") + ("." + match.group(2) if match.group(2) else ""))

    return {
        "name": re.sub(r"\s+", " ", title.group(1).split("|")[0]).strip(),
        "price": price,
        "stock": stock,
        "url": url,
        "fetch_via": "jina_verified_detail",
    }


def extend_with_known_details(current, old, state, *, get=None, now=None, max_checks=MAX_CHECKS_PER_SCAN):
    """Check at most two missing SKUs per scan, with per-SKU 15m cooldown.

    A failed/ambiguous probe never overwrites an old record. Fresh category
    data always wins; only exact verified detail pages can extend coverage.
    """
    updated = dict(current or {})
    meta = state.setdefault("proshop_detail_checks", {})
    when = time.time() if now is None else float(now)
    fetch = get or requests.get
    missing = [
        (sku, url) for sku, url in KNOWN_PRODUCTS.items()
        if sku not in updated and when - float(meta.get(sku, 0) or 0) >= CHECK_INTERVAL_SECONDS
    ]
    missing.sort(key=lambda item: (float(meta.get(item[0], 0) or 0), item[0]))
    for sku, url in missing[:max(0, max_checks)]:
        meta[sku] = when   # Throttle even if Reader fails/CAPTCHA returns 200.
        try:
            response = fetch(
                "https://r.jina.ai/" + url,
                headers={
                    "Accept": "text/plain, text/markdown;q=0.9, */*;q=0.5",
                    "User-Agent": "Pokemon-Restock-Bot/ProshopKnownSku",
                    "x-no-cache": "true",
                    "x-engine": "browser",
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            item = parse_verified_detail(response.text, sku, url)
        except (requests.RequestException, ValueError) as err:
            print(f"PROSHOP DETAIL {sku}: kunne ikke verificere ({type(err).__name__})")
            continue
        if item is None:
            print(f"PROSHOP DETAIL {sku}: ingen verificeret lagerstatus")
            continue
        # Price-less non-orderable products remain useful as baselines.
        if item["price"] is None:
            item["price"] = (old.get(sku) or {}).get("price")
        updated[sku] = item
        print(f"PROSHOP DETAIL {sku}: verificeret {item['stock']}")
    return updated
