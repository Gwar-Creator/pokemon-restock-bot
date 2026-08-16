from pathlib import Path

BOT = Path("restock_bot_github.py")
PATCH = Path("patch_v22_proshop_filter.py")

text = BOT.read_text(encoding="utf-8")

# V2.0 Reader fallback must already be present when this patch runs.
if "def _proshop_is_tcg_text(value):" not in text:
    raise RuntimeError("V2.2 requires the Proshop Reader fallback")

old_filter = r'''def _proshop_is_tcg_text(value):
    low = (value or "").lower()
    markers = (
        " tcg ", "tcg ", " tcg", "booster", "elite trainer",
        "battle deck", "world championships deck", "samlekort",
        "poké ball tin", "poke ball tin", "premium collection",
        "illustration collection", "trainer box", "trainer toolkit",
        "portfolio", "card game", "ultra-premium collection",
    )
    return any(marker in low for marker in markers)
'''

new_filter = r'''def _proshop_is_tcg_text(value):
    """Keep real Pokemon TCG products; reject binders/sleeves/accessories.

    Stock status is deliberately NOT part of this filter. Out-of-stock and
    orderable products remain in state so later restocks can be detected.
    """
    low = " " + re.sub(r"\s+", " ", (value or "").lower()) + " "

    blocked = (
        "portfolio", "binder", "mappe", "album", "pocket page",
        "pocket pages", "kortlomme", "kortlommer", "sleeve", "sleeves",
        "dragonshield", "dragon shield", "ultrapro", "ultra pro",
        "playmat", "deck protector", "deck box", "storage box",
        "toploader", "top loader", "card case", "display case",
        "card holder", "kortbeskytter", "kortbeskyttelse",
    )
    if any(marker in low for marker in blocked):
        return False

    wanted = (
        "booster pack", "booster packs", "booster box", "booster display",
        "booster bundle", "sleeved booster", "elite trainer box", " etb ",
        "blister", "poké ball tin", "poke ball tin", "mini tin", " tin ",
        "premium collection", "illustration collection", "collection box",
        "collection", "ultra-premium collection", "ultra premium collection",
        "league battle deck", "deluxe battle deck", "ex battle deck",
        "battle deck", "world championships deck", "championship deck",
        "trainer toolkit", "battle academy", "build & battle", "build and battle",
    )
    return any(marker in low for marker in wanted)
'''

if new_filter not in text:
    if old_filter not in text:
        raise RuntimeError("Could not find old Proshop TCG filter")
    text = text.replace(old_filter, new_filter, 1)

# Direct HTML parser from V1.9 had its own broad marker list. Route it through
# the same strict helper so direct and Reader paths behave identically.
old_direct = r'''        tcg_text = (name + " " + text_card).lower()
        tcg_markers = (
            " tcg ", "tcg ", " tcg", "booster", "elite trainer",
            "battle deck", "world championships deck", "samlekort",
            "poké ball tin", "poke ball tin", "premium collection",
            "illustration collection", "trainer box", "trainer toolkit",
            "portfolio", "card game",
        )
        if not any(marker in tcg_text for marker in tcg_markers):
            continue
'''
new_direct = r'''        tcg_text = name + " " + text_card
        if not _proshop_is_tcg_text(tcg_text):
            continue
'''
if old_direct in text:
    text = text.replace(old_direct, new_direct, 1)

# Reader validity should depend on whether we received a real Proshop product
# page, not on how many products currently match our sealed/playable filter.
old_validation = r'''    products = _parse_proshop_reader_markdown(response.text)

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

new_validation = r'''    raw_link_pattern = re.compile(
        r"(?:https?://(?:www\.)?proshop\.dk)?/Pokemon/[^)\s?#]+/\d+",
        re.IGNORECASE,
    )
    raw_product_links = len(set(raw_link_pattern.findall(response.text or "")))

    # Fail closed if Reader did not return a plausible Proshop product page.
    # The number of relevant TCG products may legitimately be zero.
    if raw_product_links < 5:
        raise RuntimeError(
            f"Jina Reader returned too little raw Proshop data "
            f"({raw_product_links} product links)"
        )

    products = _parse_proshop_reader_markdown(response.text)
    priced = sum(1 for product in products.values() if product.get("price"))

    print(
        f"PROSHOP: bruger Jina Reader fallback "
        f"({len(products)} relevante TCG-produkter; "
        f"{raw_product_links} rå produktlinks)"
    )
    return products
'''

if new_validation not in text:
    if old_validation not in text:
        raise RuntimeError("Could not find Proshop Reader validation block")
    text = text.replace(old_validation, new_validation, 1)

BOT.write_text(text, encoding="utf-8")
PATCH.unlink(missing_ok=True)
print("V2.2 applied: strict Proshop TCG filter without stock-count assumptions.")
