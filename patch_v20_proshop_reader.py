from pathlib import Path

BOT = Path("restock_bot_github.py")
PATCH = Path("patch_v20_proshop_reader.py")

text = BOT.read_text(encoding="utf-8")

# V1.9 must have introduced _parse_proshop_products. The workflow applies
# patches in order, so this works both before and after V1.9 has self-deleted.
if "def _parse_proshop_products(response):" not in text:
    raise RuntimeError("V2.0 requires the V1.9 Proshop parser")

helper_anchor = '''def get_proshop_products():\n'''

reader_helper = r'''PROSHOP_READER_URL = "https://r.jina.ai/" + PROSHOP_URL


def _proshop_is_tcg_text(value):
    low = (value or "").lower()
    markers = (
        " tcg ", "tcg ", " tcg", "booster", "elite trainer",
        "battle deck", "world championships deck", "samlekort",
        "poké ball tin", "poke ball tin", "premium collection",
        "illustration collection", "trainer box", "trainer toolkit",
        "portfolio", "card game", "ultra-premium collection",
    )
    return any(marker in low for marker in markers)


def _parse_proshop_reader_markdown(markdown):
    """Parse Proshop data from Jina Reader without trusting generated values.

    Reader is only used as a browser/proxy transport. Product id/name come
    from the real Proshop product URL, while price and stock are parsed from
    the adjacent page text. This prevents a structured-extraction model from
    inventing product data.
    """
    products = {}

    # Reader normally turns Proshop product anchors into Markdown links.
    # Support both absolute and relative Proshop URLs.
    pattern = re.compile(
        r"\[(?P<label>[^\]]{2,2500})\]\("
        r"(?P<absolute>https?://(?:www\.)?proshop\.dk)?"
        r"(?P<href>/Pokemon/[^)\s?#]+/(?P<id>\d+))"
        r"(?:[?#][^)]*)?\)",
        re.IGNORECASE | re.DOTALL,
    )
    matches = list(pattern.finditer(markdown or ""))

    for index, match in enumerate(matches):
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        # Keep the segment bounded so a missing price cannot bleed into a far
        # away product. Proshop places price/stock directly after each card.
        segment = (markdown[match.end():next_start] or "")[:2500]
        href = match.group("href")
        product_id = match.group("id")
        label = re.sub(r"\s+", " ", match.group("label") or "").strip()
        name = clean_proshop_name(href)

        if not _proshop_is_tcg_text(name + " " + label + " " + segment[:800]):
            continue

        price_match = re.search(
            r"(?<!\d)(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d+(?:,\d{2})?)\s*kr\.?",
            segment,
            flags=re.IGNORECASE,
        )
        if not price_match:
            continue

        raw_price = price_match.group(1).replace(".", "").replace(",", ".")
        try:
            price = float(raw_price)
        except ValueError:
            continue

        if price <= 0:
            continue

        stock_text = segment.lower()
        if "på lager" in stock_text or "pa lager" in stock_text:
            stock = "PÅ LAGER"
        elif "fjernlager" in stock_text:
            stock = "FJERNLAGER"
        elif "bestillingsvare" in stock_text or "bestilt" in stock_text:
            stock = "BESTILLINGSVARE"
        else:
            stock = "UKENDT"

        # If the same product link appears more than once, prefer the entry
        # with an explicit stock status.
        candidate = {
            "name": name,
            "price": price,
            "stock": stock,
            "url": urljoin(PROSHOP_BASE, href),
            "fetch_via": "jina_reader",
        }
        current = products.get(product_id)
        if current is None or (
            current.get("stock") == "UKENDT" and stock != "UKENDT"
        ):
            products[product_id] = candidate

    return products


def get_proshop_products_via_reader():
    response = requests.get(
        PROSHOP_READER_URL,
        headers={
            "Accept": "text/plain, text/markdown;q=0.9, */*;q=0.5",
            "User-Agent": "Pokemon-Lorcana-MasterBot/2.0 ProshopFallback",
        },
        timeout=50,
    )
    response.raise_for_status()

    products = _parse_proshop_reader_markdown(response.text)

    # Fail closed. A partial/broken Reader response must not become a fresh
    # Proshop snapshot and trigger false out-of-stock/restock transitions.
    priced = sum(1 for product in products.values() if product.get("price"))
    if len(products) < 5 or priced < 5:
        raise RuntimeError(
            f"Jina Reader returned too little usable Proshop data "
            f"({len(products)} products / {priced} prices)"
        )

    print(
        f"PROSHOP: bruger Jina Reader fallback "
        f"({len(products)} TCG-produkter)"
    )
    return products


'''

if "def get_proshop_products_via_reader():" not in text:
    if helper_anchor not in text:
        raise RuntimeError("Could not find Proshop function anchor")
    text = text.replace(helper_anchor, reader_helper + helper_anchor, 1)

old_tail = '''    short = "; ".join(errors[-4:]) if errors else "ukendt fejl"\n    raise RuntimeError(f"Proshop utilgængelig fra GitHub runner ({short})")\n'''
new_tail = '''    # Direct GitHub egress is frequently blocked by Proshop. Use Jina Reader\n    # as a low-rate browser/proxy fallback for the same public category page.\n    try:\n        return get_proshop_products_via_reader()\n    except Exception as reader_error:\n        errors.append(f"Jina Reader: {reader_error}")\n\n    short = "; ".join(errors[-5:]) if errors else "ukendt fejl"\n    raise RuntimeError(f"Proshop utilgængelig ({short})")\n'''

if new_tail not in text:
    if old_tail not in text:
        raise RuntimeError("Could not find Proshop failure tail")
    text = text.replace(old_tail, new_tail, 1)

BOT.write_text(text, encoding="utf-8")
PATCH.unlink(missing_ok=True)
print("V2.0 applied: Proshop Jina Reader fallback with fail-closed parsing.")
