from pathlib import Path

BOT = Path("restock_bot_github.py")
PATCH = Path("patch_v17_pricewatch.py")

text = BOT.read_text(encoding="utf-8")

marker = '''# =========================================================
# PRICE WATCH V3
# =========================================================
'''

helper = r'''# =========================================================
# PRICE WATCH V4 - SOURCE-CONFIRMED ANTI-FLAP
# =========================================================

def _price_watch_raw_products_for_source(current_state, source_key):
    if source_key in {
        "coolshop", "proshop", "br", "bilka", "foetex",
        "elgiganten", "epicpanda", "steffeno", "nextlevel"
    }:
        products = current_state.get(source_key, {})
        return products if isinstance(products, dict) else {}

    shopify = current_state.get("shopify", {})
    if isinstance(shopify, dict) and source_key in shopify:
        products = shopify.get(source_key, {})
        return products if isinstance(products, dict) else {}

    woocommerce = current_state.get("woocommerce", {})
    if isinstance(woocommerce, dict) and source_key in woocommerce:
        products = woocommerce.get(source_key, {})
        return products if isinstance(products, dict) else {}

    return {}


def build_price_watch_source_observations(current_state, fresh_sources):
    """Build raw per-source observations, including unavailable products.

    A fresh source alone is not proof that a missing listing disappeared.
    We only confirm a negative price move when the former cheapest source
    explicitly exposes the same normalized product as unavailable/preorder
    or at a higher price.
    """
    observations = {}
    pokemon_only = {"proshop", "br", "bilka", "foetex", "elgiganten", "steffeno"}

    for source_key in fresh_sources:
        source_rows = {}
        raw_products = _price_watch_raw_products_for_source(current_state, source_key)

        for _, product in raw_products.items():
            if not isinstance(product, dict):
                continue

            name = product.get("name", "")
            game = "POKÉMON" if source_key in pokemon_only else product.get("game")
            if game not in ("POKÉMON", "LORCANA"):
                continue

            product_type = get_price_watch_type(name, game)
            if not product_type:
                continue

            product_key = get_price_watch_product_key({
                "game": game,
                "type": product_type,
                "name": name,
            })
            if not product_key:
                continue

            raw_price = product.get("price")
            try:
                price = float(raw_price) if raw_price is not None else None
            except (TypeError, ValueError):
                price = None

            available = bool(get_price_watch_availability(source_key, product))

            source_rows.setdefault(product_key, []).append({
                "available": available,
                "price": price,
                "preorder": bool(product.get("preorder")),
                "name": name,
            })

        observations[source_key] = source_rows

    return observations


def price_watch_old_offer_explicitly_gone(
    source_observations,
    old_sources,
    product_key,
    old_price,
):
    """Return True only when every former cheapest source explicitly
    confirms that the old cheap offer is no longer available.

    Missing from an otherwise fresh feed is UNKNOWN, not out of stock.
    """
    if not old_sources or old_price is None:
        return False

    for source_key in old_sources:
        rows = (source_observations.get(source_key) or {}).get(product_key)

        # Source fetched, but the product/listing vanished from the feed.
        # That is exactly the condition that caused the old flap.
        if not rows:
            return False

        available_rows = [row for row in rows if row.get("available")]

        if not available_rows:
            # Explicitly present but unavailable/preorder: old offer is gone.
            continue

        available_prices = [
            row.get("price")
            for row in available_rows
            if isinstance(row.get("price"), (int, float)) and row.get("price") > 0
        ]

        # Available product without a trustworthy price is not enough evidence
        # for a price increase.
        if not available_prices:
            return False

        # If the old source still exposes the old/lower price, do not promote
        # a more expensive competitor.
        if min(available_prices) <= old_price + 0.005:
            return False

        # Otherwise this source explicitly moved to a higher price.

    return True


'''

if "def build_price_watch_source_observations(" not in text:
    if marker not in text:
        raise RuntimeError("Could not find Price Watch marker")
    text = text.replace(marker, helper + marker.replace("V3", "V4"), 1)
else:
    text = text.replace(marker, marker.replace("V3", "V4"), 1)

old_candidates = '''    comparable_groups = build_price_watch_groups(
        candidates
    )

    print(
        f"PRICE WATCH V3: "
'''
new_candidates = '''    comparable_groups = build_price_watch_groups(
        candidates
    )

    source_observations = build_price_watch_source_observations(
        current_state,
        fresh_sources
    )

    print(
        f"PRICE WATCH V4: "
'''
if old_candidates not in text:
    raise RuntimeError("Could not find Price Watch candidates block")
text = text.replace(old_candidates, new_candidates, 1)

old_changes = '''    # V3: En højere bedste pris / tab af billigste butik skal ses i
    # to på hinanden følgende friske scans før den bliver bekræftet.
    # Et enkelt midlertidigt manglende produkt kan derfor ikke længere
    # få 1.479 -> 1.499 -> 1.479 til at spamme Discord.
    changes_enabled = (
        bool(PRICE_WATCH_WEBHOOK_URL)
        and last_daily_date == today
        and not daily_sent
        and not is_first_price_watch_run
        and previous_version >= 3
    )
'''
new_changes = '''    # V4: Negative ændringer kræver både eksplicit kildebevis og to
    # ens scans. En vare, der blot mangler fra et frisk kategori-feed,
    # må aldrig løfte den registrerede bedste pris.
    changes_enabled = (
        bool(PRICE_WATCH_WEBHOOK_URL)
        and last_daily_date == today
        and not daily_sent
        and not is_first_price_watch_run
        and previous_version >= 4
    )
'''
if old_changes not in text:
    raise RuntimeError("Could not find changes_enabled block")
text = text.replace(old_changes, new_changes, 1)

old_fresh = '''        old_sources_are_fresh = (
            bool(old_sources)
            and all(source in fresh_sources for source in old_sources)
        )

'''
if old_fresh not in text:
    raise RuntimeError("Could not find old_sources_are_fresh block")
text = text.replace(old_fresh, "", 1)

old_negative = '''        # Pris op / billigste butik væk er negativ information og kan
        # skyldes et midlertidigt hul i et produktfeed. Kræv 2 ens scans.
        if price_is_higher or cheapest_shop_changed:
            if not old_sources_are_fresh:
                kept = dict(old_entry)
                kept.pop("pending_change", None)
                kept["last_seen"] = now_local.isoformat()
                next_products[product_key] = kept
                continue

            signature = (
'''
new_negative = '''        # Pris op / billigste butik væk er negativ information. Før vi
        # overhovedet starter 2-scan confirmation, skal den tidligere
        # billigste kilde eksplicit vise samme produkt som udsolgt/preorder
        # eller dyrere. Mangler produktet bare fra feedet, er status UNKNOWN.
        if price_is_higher or cheapest_shop_changed:
            old_offer_gone = price_watch_old_offer_explicitly_gone(
                source_observations,
                old_sources,
                product_key,
                old_price,
            )

            if not old_offer_gone:
                kept = dict(old_entry)
                kept.pop("pending_change", None)
                kept["last_seen"] = now_local.isoformat()
                kept["hold_reason"] = "former_cheapest_source_not_explicitly_resolved"
                next_products[product_key] = kept
                continue

            signature = (
'''
if old_negative not in text:
    raise RuntimeError("Could not find negative-change block")
text = text.replace(old_negative, new_negative, 1)

old_stable = '''        # Stabilt scan: opdater metadata og nulstil evt. pending flap.
        next_products[product_key] = confirmed_entry(
'''
new_stable = '''        # Stabilt scan: opdater metadata og nulstil evt. pending flap.
        next_products[product_key] = confirmed_entry(
'''
# No functional replacement needed; retained as an anchor for validation.
if old_stable not in text:
    raise RuntimeError("Could not find stable scan block")

text = text.replace(
    'print("PRICE WATCH V3 baseline oprettet uden ændringsalerts.")',
    'print("PRICE WATCH V4 baseline oprettet uden ændringsalerts.")',
    1,
)
text = text.replace(
    'elif previous_version < 3:\n        print("PRICE WATCH V3 anti-flap aktiveret uden overgangsalerts.")',
    'elif previous_version < 4:\n        print("PRICE WATCH V4 source-confirmed anti-flap aktiveret uden overgangsalerts.")',
    1,
)
text = text.replace(
    '"version": 3,\n        "products": next_products,',
    '"version": 4,\n        "products": next_products,',
    1,
)

BOT.write_text(text, encoding="utf-8")
PATCH.unlink(missing_ok=True)
print("V1.7 applied: Price Watch source-confirmed anti-flap.")
