"""Conservative Proshop TCG title classification and known-SKU detail checks.

Public pages often return generic category HTML with HTTP 200. A status is
accepted only if the requested URL AND product number match, with an explicit
own-product status. Never infer stock from related products or legal text.
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
    """Admit Pokemon TCG 2-pack Booster without admitting booster accessories."""
    name = re.sub(r"\s+", " ", str(value or "").lower())
    if re.search(r"\bpokemon[\s-]+tcg[\s-]+\d+[\s-]*pack[\s-]+boosters?\b", name):
        if not re.search(
            r"\b(portfolio|sleeves?|binder|album|deck[\s-]*box|playmat|"
            r"kortlommer|samlemappe|opbevaring|storage[\s-]*box)\b",
            name,
        ):
            return True
    return bool(original(value))


def parse_verified_detail(page, sku, url):
    """Return product only if identity and own-product stock are unequivocal."""
    text = str(page or "")
    sku = str(sku)
    source = re.search(r"(?m)^URL Source:\s*(\S+)", text)
    if not source or source.group(1).rstrip("/") != url:
        return None
    title = re.search(r"(?m)^Title:\s*([^\n]+)", text)
    if not title or "pokemon tcg" not in title.group(1).lower():
        return None
    marker = re.search(r"\bVarenummer:\s*\**\s*(\d{7})\s*\**", text)
    if not marker or marker.group(1) != sku:
        return None

    own = text[marker.end():]
    # Stop before related-item cards and before stock-irrelevant boilerplate.
    boundary = re.search(
        r"(?m)^\*\s+\[!\[Image\s+[2-9]\d*"
        r"|^#{1,4}\s+(?:Lignende|Relaterede|Anbefalede)\s+produkter"
        r"|^#{1,4}\s+(?:Generelt|Specifikationer|Produktinfo)\b"
        r"|I tilfælde af trykfejl|Proshop tager forbehold|Vi bestræber os på",
        own,
    )
    if boundary:
        own = own[:boundary.start()]
    own = own[:1800]

    # A generic sentence containing "udsolgte varer" cannot imply this
    # product is sold out. Require short, explicit status lines.
    lines = [re.sub(r"\s+", " ", s).strip().lower() for s in own.splitlines()]
    stock = "UKENDT"
    for line in lines:
        if len(line) > 165:
            continue
        if re.search(r"^(produktet er udgået|varen er udgået|"
                     r"ikke på lager|udsolgt|kan ikke bestilles)\b", line):
            stock = "UDSOLGT"
            break
        if re.search(r"^(på lager|[1-9]\d*(?:\+)? stk\. på lager)\b", line):
            stock = "PÅ LAGER"
            break
        if re.search(r"^fjernlager\b", line):
            stock = "FJERNLAGER"
            break

    if stock == "UKENDT":
        return None

    price = None
    if stock == "PÅ LAGER":
        price_match = re.search(
            r"(?<!\d)(\d{1,3}(?:\.\d{3})*|\d{1,5})(?:,(\d{2}))?\s*kr\.?",
            own, re.I,
        )
        if price_match:
            price = float(price_match.group(1).replace(".", "") + (
                "." + price_match.group(2) if price_match.group(2) else ""
            ))

    return {
        "name": re.sub(r"\s+", " ", title.group(1).split("|")[0]).strip(),
        "price": price,
        "stock": stock,
        "url": url,
        "fetch_via": "jina_verified_detail",
    }


def extend_with_known_details(current, old, state, *, get=None, now=None,
                              max_checks=MAX_CHECKS_PER_SCAN):
    """At most two independent missing-SKU checks per scan, 15min per SKU.

    Invalid, redirected and ambiguous pages cannot change state. Fresh
    category data wins. Preserve the original SKU and anti-duplicate state.
    """
    updated = dict(current or {})
    meta = state.setdefault("proshop_detail_checks", {})
    when = time.time() if now is None else float(now)
    fetch = get or requests.get
    missing = [
        (sku, url) for sku, url in KNOWN_PRODUCTS.items()
        if sku not in updated
        and when - float(meta.get(sku, 0) or 0) >= CHECK_INTERVAL_SECONDS
    ]
    missing.sort(key=lambda item: (float(meta.get(item[0], 0) or 0), item[0]))
    for sku, url in missing[:max(0, max_checks)]:
        meta[sku] = when  # Throttle failures, too.
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
        except (requests.RequestException, ValueError, TypeError) as err:
            print(f"PROSHOP DETAIL {sku}: kunne ikke verificere ({type(err).__name__})")
            continue
        if item is None:
            print(f"PROSHOP DETAIL {sku}: ingen verificeret lagerstatus")
            continue
        if item["price"] is None:
            item["price"] = (old.get(sku) or {}).get("price")
        updated[sku] = item
        print(f"PROSHOP DETAIL {sku}: verificeret {item['stock']}")
    return updated
