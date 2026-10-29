"""Parse Proshop Jina Reader catalog cards without relying on fragile heading links.

Reader embeds the same product URL in thumbnail and heading links. Headings
often have long descriptions, titles and nested markdown; the old [label](url)
parser silently missed them. Bound price/stock to the image-led product card.
"""
import re
from urllib.parse import unquote

PRODUCT_URL_RE = re.compile(
    r"https?://(?:www\.)?proshop\.dk/Pokemon/"
    r"(?P<slug>[^)\s?#\"<>]+?)/(?P<id>\d+)(?=[)\s?#\"])",
    re.IGNORECASE,
)
CARD_START_RE = re.compile(r"(?m)^[ \t]*\*[ \t]+\[!\[Image\s+\d+(?::|\])")
PRICE_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:\.\d{3})+|\d{1,6})(?:,(\d{2}))?\s*kr\.?",
    re.IGNORECASE,
)


def _price(text):
    match = PRICE_RE.search(text or "")
    if not match:
        return None
    whole = match.group(1).replace(".", "")
    fractional = match.group(2)
    price = float(whole + ("." + fractional if fractional else ""))
    return price if price > 0 else None


def _stock(text):
    low = (text or "").lower()
    # Negative conditions must be checked before the bare "på lager".
    if re.search(r"\b(ikke på lager|udsolgt|midlertidigt udsolgt)\b", low):
        return "UDSOLGT"
    if "fjernlager" in low:
        return "FJERNLAGER"
    if "bestillingsvare" in low or re.search(r"\bbestilt\s*:", low):
        return "BESTILLINGSVARE"
    if re.search(r"\bpå lager\b|\bpa lager\b", low):
        return "PÅ LAGER"
    return "UKENDT"


def _name_from_slug(slug):
    return re.sub(r"\s+", " ", unquote(slug).replace("-", " ")).strip()


def parse_proshop_reader(markdown, is_tcg):
    """Return normal Proshop product dict keyed by stable numeric SKU.

    Do not infer missing prices or availability, and do not let one product's
    status bleed into the following card.
    """
    text = markdown or ""
    markers = list(CARD_START_RE.finditer(text))
    if not markers:
        return {}

    products = {}
    for i, marker in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        card = text[marker.start():end]
        matches = list(PRODUCT_URL_RE.finditer(card))
        if not matches:
            continue
        # The thumbnail's URL is present even if the heading has >2500 chars
        # or Reader changes its heading/markdown link representation.
        first = matches[0]
        product_id = first.group("id")
        name = _name_from_slug(first.group("slug"))
        if not is_tcg(name):
            continue

        # The final product link in the card precedes its availability and price.
        # Never pull a price/status out of the next product card.
        own = [m for m in matches if m.group("id") == product_id]
        tail = card[own[-1].end():][:850]
        # Proshop links can contain optional quoted titles after the URL.
        # Skip that wrapper, not genuine product availability text.
        tail = re.sub(r'^\s*(?:"[^"]{0,500}")?\s*\)', "", tail, count=1)
        item = {
            "name": name,
            "price": _price(tail),
            "stock": _stock(tail),
            "url": "https://www.proshop.dk/Pokemon/" + first.group("slug") + "/" + product_id,
            "fetch_via": "jina_reader",
        }
        current = products.get(product_id)
        if current is None or (
            current.get("stock") == "UKENDT" and item["stock"] != "UKENDT"
        ):
            products[product_id] = item
    return products


def raw_product_id_count(markdown):
    return len({m.group("id") for m in PRODUCT_URL_RE.finditer(markdown or "")})
