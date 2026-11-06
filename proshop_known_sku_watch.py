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
    # Newly published 30th Celebration ex Boxes often omit the "TCG"
    # keyword entirely. These are sealed boxes, not figurines/accessories.
    if re.search(r"\bpokemon\b", name) and re.search(r"\b(?:ex[\s-]*box|box[\s-]*ex)\b", name):
        if not re.search(
            r"\b(figure|figur|bamse|plush|vinyl|funko|sleeve|binder|"
            r"portfolio|album|storage|display[\s-]*case|toy)\b", name,
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
    # Jina may return HTTP 200 for a requested SKU but redirect the final
    # page to a generic brand/category. Reject the response even if that
    # generic page happens to contain the SKU in related items.
    final = re.search(r"(?m)^Final URL:\s*(\S+)", text)
    if final and final.group(1).rstrip("/") != url.rstrip("/"):
        return None
    title = re.search(r"(?m)^Title:\s*([^\n]+)", text)
    # Most recent boxes do not carry the literal "TCG" in their title.
    # Product URL, exact item number and sealed-card title must all agree.
    if not title:
        return None
    heading = title.group(1).lower().replace("pokémon", "pokemon")
    if not re.search(r"\bpokemon\b", heading):
        return None
    sealed_markers = (
        "tcg", "booster", "elite trainer box", "etb", "tin", "blister",
        "premium collection", "ultra-premium collection", "ex box",
        "collection box", "illustration collection", "battle deck",
        "trainer toolkit", "display",
    )
    if not any(word in heading for word in sealed_markers):
        return None
    if re.search(r"\b(funko|figure|figur|bamse|plush|portfolio|"
                 r"deck box|card case|display case|sleeves?)\b", heading):
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


def _tracked_sku_urls(current, previous):
    """Stable public Proshop product IDs, including newly discovered SKUs.

    All input URLs must match the exact numeric SKU. No speculative product
    pages or accessory discovery. Existing saved IDs survive category gaps.
    """
    urls = dict(KNOWN_PRODUCTS)
    pattern = re.compile(r"^https://www\.proshop\.dk/Pokemon/[^/?#\s]+/(\d+)/?$", re.I)
    for products in (previous or {}, current or {}):
        for sku, product in products.items():
            if not isinstance(product, dict):
                continue
            url = str(product.get("url") or "").strip()
            match = pattern.fullmatch(url)
            if not match or match.group(1) != str(sku):
                continue
            urls[str(sku)] = url
    return urls


def extend_with_known_details(current, old, state, *, get=None, now=None,
                              max_checks=MAX_CHECKS_PER_SCAN):
    """Bounded, rotating per-SKU verification independent of catalogue health.

    The old implementation visited six static SKUs only. Priority now goes to
    stale/unknown/sold-out known catalogue items. A bad/redirected detail page
    never changes availability, and the same SKU is not re-requested within
    the 15-minute check window.
    """
    updated = dict(current or {})
    known_urls = _tracked_sku_urls(updated, old)
    meta = state.setdefault("proshop_detail_checks", {})
    when = time.time() if now is None else float(now)
    fetch = get or requests.get

    def order(item):
        sku, _url = item
        current_stock = (updated.get(sku) or old.get(sku) or {}).get("stock")
        # Unknown and confirmed sold-out products matter most for restocks.
        priority = 0 if current_stock in ("UDSOLGT", "UKENDT") else 1
        return (float(meta.get(sku, 0) or 0), priority, sku)

    eligible = [
        item for item in known_urls.items()
        if when - float(meta.get(item[0], 0) or 0) >= CHECK_INTERVAL_SECONDS
    ]
    eligible.sort(key=order)

    for sku, url in eligible[:max(0, max_checks)]:
        meta[sku] = when  # Throttle failures too; never retry-storm blocked pages.
        try:
            response = fetch(
                "https://r.jina.ai/" + url,
                headers={
                    "Accept": "text/plain, text/markdown;q=0.9, */*;q=0.5",
                    "User-Agent": "Pokemon-Restock-Bot/ProshopSkuCheck",
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
            item["price"] = (
                (updated.get(sku) or {}).get("price")
                or (old.get(sku) or {}).get("price")
            )
        updated[sku] = item
        print(f"PROSHOP DETAIL {sku}: verificeret {item['stock']}")
    return updated
