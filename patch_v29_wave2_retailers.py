from pathlib import Path
import re

PATH = Path("restock_bot_github.py")
text = PATH.read_text(encoding="utf-8")

MARKER = "WAVE2_RETAILERS_V29 = True"

if MARKER in text:
    print("V29 Wave 2 retailers already applied")
    raise SystemExit(0)


def replace_once(old, new, label):
    global text
    if old not in text:
        raise RuntimeError(f"V29 patch failed: marker not found for {label}")
    text = text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# 1) Durable marker + source health minimums
# ---------------------------------------------------------------------------
replace_once(
    '''PRICE_HISTORY_COMPACT_V27 = True
WAVE1_RETAILERS_V28 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    '''PRICE_HISTORY_COMPACT_V27 = True
WAVE1_RETAILERS_V28 = True
WAVE2_RETAILERS_V29 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    "V29 marker",
)

replace_once(
    '''    "cardsdirect": 5,
    "nostalgic": 5,
''',
    '''    "cardsdirect": 5,
    "baltzer": 5,
    "tcgshoppen": 5,
    "pokemonsdk": 5,
    "pocketmonster": 5,
    "cardstorecph": 3,
    "nostalgic": 5,
''',
    "Wave 2 source minimums",
)


# ---------------------------------------------------------------------------
# 2) Shopify: Baltzer Games + TCG Shoppen
# ---------------------------------------------------------------------------
replace_once(
    '''    "cardsdirect": {
        "label": "CARDSDIRECT",
        "base": "https://cardsdirect.dk",
        "feeds": [
            {"game": "POKÉMON", "path": "/collections/all/products.json"}
        ]
    }
}
''',
    '''    "cardsdirect": {
        "label": "CARDSDIRECT",
        "base": "https://cardsdirect.dk",
        "feeds": [
            {"game": "POKÉMON", "path": "/collections/all/products.json"}
        ]
    },
    "baltzer": {
        "label": "BALTZER GAMES",
        "base": "https://baltzergames.dk",
        "feeds": [
            {"game": "POKÉMON", "path": "/collections/pokemon-booster-packs/products.json"},
            {"game": "POKÉMON", "path": "/collections/pokemon-booster-display/products.json"},
            {"game": "POKÉMON", "path": "/collections/pokemon-tins/products.json"},
            {"game": "POKÉMON", "path": "/collections/pokemon-blister-pakker/products.json"},
            {"game": "POKÉMON", "path": "/collections/pokemon-v-ex-gx/products.json"},
            {"game": "LORCANA", "path": "/collections/lorcana/products.json"}
        ]
    },
    "tcgshoppen": {
        "label": "TCG SHOPPEN",
        "base": "https://www.tcgshoppen.dk",
        "feeds": [
            {"game": "POKÉMON", "path": "/collections/hele-vores-udvalg-af-pokemon/products.json"}
        ]
    }
}
''',
    "Wave 2 Shopify sites",
)


# ---------------------------------------------------------------------------
# 3) WooCommerce: Pokemons.dk + Pocket Monster via targeted Store API search
# ---------------------------------------------------------------------------
replace_once(
    '''    "pokecards": {
        "label": "POKECARDS.DK",
        "base": "https://pokecards.dk",
        "trust_total_pages": False,
        "categories": {
            "POKÉMON": 16
        }
    },
}
''',
    '''    "pokecards": {
        "label": "POKECARDS.DK",
        "base": "https://pokecards.dk",
        "trust_total_pages": False,
        "categories": {
            "POKÉMON": 16
        }
    },
    "pokemonsdk": {
        "label": "POKEMONS.DK",
        "base": "https://www.pokemons.dk",
        "categories": {},
        "searches": {
            "POKÉMON": ["booster", "elite trainer", "tin", "collection", "box"]
        }
    },
    "pocketmonster": {
        "label": "POCKET MONSTER",
        "base": "https://pocketmonster.dk",
        "categories": {},
        "searches": {
            "POKÉMON": ["booster", "elite trainer", "tin", "collection", "box"]
        }
    },
}
''',
    "Wave 2 WooCommerce sites",
)

replace_once(
    '''    return list(collected.values())


def get_woocommerce_products(site_key):
''',
    '''    return list(collected.values())


def fetch_woocommerce_search(base, search_term, max_pages=5):
    """Targeted Woo Store API search for shops with huge mixed catalogs."""
    collected = {}

    for page in range(1, max_pages + 1):
        response = requests.get(
            base + WOOCOMMERCE_API_PATH,
            headers={
                **BROWSER_HEADERS,
                "Accept": "application/json,text/plain,*/*"
            },
            params={
                "search": search_term,
                "per_page": WOOCOMMERCE_PAGE_SIZE,
                "page": page,
                "orderby": "id",
                "order": "desc"
            },
            timeout=30
        )
        response.raise_for_status()
        page_products = response.json()

        if not isinstance(page_products, list) or not page_products:
            break

        for product in page_products:
            product_id = str(product.get("id", "")).strip()
            if product_id:
                collected[product_id] = product

        total_pages = response.headers.get("X-WP-TotalPages")
        if total_pages:
            try:
                if page >= min(int(total_pages), max_pages):
                    break
            except ValueError:
                pass

        if len(page_products) < WOOCOMMERCE_PAGE_SIZE:
            break

    return list(collected.values())


def get_woocommerce_products(site_key):
''',
    "WooCommerce targeted search helper",
)

pattern = re.compile(
    r'''def get_woocommerce_products\(site_key\):\n.*?\n    return products\n\n\ndef count_woocommerce_products''',
    re.DOTALL,
)
replacement = '''def get_woocommerce_products(site_key):
    site = WOOCOMMERCE_SITES[site_key]
    products = {}

    def add_raw_products(game, raw_products):
        for raw in raw_products:
            if not woocommerce_is_relevant_sealed(raw):
                continue

            product_id = str(raw.get("id", "")).strip()
            name = woocommerce_clean_text(raw.get("name"))

            if not product_id or not name:
                continue

            url = str(raw.get("permalink") or "").strip()
            if not url:
                url = f"{site['base']}/?p={product_id}"

            products[product_id] = {
                "name": name,
                "game": game,
                "price": woocommerce_price(raw),
                "in_stock": bool(raw.get("is_in_stock", False)),
                "preorder": woocommerce_is_preorder(raw),
                "url": url
            }

    for game, category_id in (site.get("categories") or {}).items():
        add_raw_products(
            game,
            fetch_woocommerce_category(
                site["base"],
                category_id,
                trust_total_pages=site.get("trust_total_pages", True),
            ),
        )

    # Targeted searches are used only where the shop's category IDs are not
    # stable/public enough to hard-code. Results are unioned and then pass the
    # same sealed-product filter as category feeds.
    for game, search_terms in (site.get("searches") or {}).items():
        for search_term in search_terms:
            add_raw_products(
                game,
                fetch_woocommerce_search(
                    site["base"],
                    search_term,
                    max_pages=site.get("search_max_pages", 5),
                ),
            )

    return products


def count_woocommerce_products'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise RuntimeError("V29 patch failed: WooCommerce get_products block not found")


# ---------------------------------------------------------------------------
# 4) CardstoreCPH: custom category parser for its hosted-shop platform
# ---------------------------------------------------------------------------
cardstore_code = r'''

# =========================================================
# CARDSTORECPH
# =========================================================

CARDSTORECPH_BASE = "https://cardstorecph.dk"
CARDSTORECPH_FEEDS = (
    ("POKÉMON", "https://cardstorecph.dk/shop/3-pokemon/"),
    ("LORCANA", "https://cardstorecph.dk/shop/125-disney-lorcana/"),
)


def _cardstorecph_price(text):
    match = re.search(
        r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d+(?:,\d{2})?)\s*DKK",
        text or "",
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    try:
        return float(match.group(1).replace(".", "").replace(",", "."))
    except ValueError:
        return None


def get_cardstorecph_products():
    products = {}

    for game, category_url in CARDSTORECPH_FEEDS:
        response = requests.get(
            category_url,
            headers=BROWSER_HEADERS,
            timeout=30,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        category_prefix = category_url.rstrip("/") + "/"

        for link in soup.find_all("a", href=True):
            href = urljoin(CARDSTORECPH_BASE, link.get("href"))
            if not href.startswith(category_prefix):
                continue

            name = re.sub(r"\s+", " ", link.get_text(" ", strip=True)).strip()
            if not name or name.lower() in {"vis produkt", "køb", "koeb"}:
                continue

            product_match = re.search(r"/(\d{6,})-[^/]+/?$", href)
            if not product_match:
                continue

            card = None
            for parent in link.parents:
                if parent is soup:
                    break
                parent_text = re.sub(r"\s+", " ", parent.get_text(" ", strip=True)).strip()
                low_parent = parent_text.lower()
                if (
                    "dkk" in low_parent
                    and (
                        "på lager" in low_parent
                        or "pa lager" in low_parent
                        or "ikke på lager" in low_parent
                        or "ikke pa lager" in low_parent
                        or "udsolgt" in low_parent
                    )
                    and len(parent_text) <= 2500
                ):
                    card = parent
                    break

            if card is None:
                continue

            card_text = re.sub(r"\s+", " ", card.get_text(" ", strip=True)).strip()
            low = card_text.lower()
            explicit_out = (
                "ikke på lager" in low
                or "ikke pa lager" in low
                or "udsolgt" in low
            )
            explicit_in = (
                ("på lager" in low or "pa lager" in low)
                and not explicit_out
            )

            product = {
                "name": name,
                "game": game,
                "price": _cardstorecph_price(card_text),
                "in_stock": explicit_in,
                "preorder": any(
                    marker in low
                    for marker in ("forudbestil", "forudbestilling", "preorder", "pre-order")
                ),
                "url": href,
            }

            if not restock_alert_allowed(product, game):
                continue

            products[product_match.group(1)] = product

    return products


def count_cardstorecph_products(products):
    return {
        "POKÉMON": sum(1 for p in products.values() if p.get("game") == "POKÉMON"),
        "LORCANA": sum(1 for p in products.values() if p.get("game") == "LORCANA"),
        "POKÉMON_STOCK": sum(1 for p in products.values() if p.get("game") == "POKÉMON" and p.get("in_stock")),
        "LORCANA_STOCK": sum(1 for p in products.values() if p.get("game") == "LORCANA" and p.get("in_stock")),
    }


def process_cardstorecph_changes(old_products, new_products):
    new_products = filter_restock_alert_products(new_products)

    for product_id, product in new_products.items():
        if product_id not in old_products:
            headline = (
                "🚨 NY FORUDBESTILLING"
                if product.get("preorder")
                else "🆕 NYT PRODUKT"
            )
            send_discord(
                f"{headline} **[{product.get('game', 'TCG')}] CARDSTORECPH**\n"
                f"**{product['name']}**\n"
                f"📦 {'På lager' if product.get('in_stock') else 'Ikke på lager'}\n"
                f"💰 {format_price(product.get('price'))}\n"
                f"🔗 {product['url']}"
            )
            continue

        old = old_products.get(product_id) or {}
        if not old.get("in_stock") and product.get("in_stock"):
            send_discord(
                f"🔥 **[{product.get('game', 'TCG')}] CARDSTORECPH RESTOCK**\n"
                f"**{product['name']}**\n"
                "📦 **PÅ LAGER**\n"
                f"💰 {format_price(product.get('price'))}\n"
                f"🔗 {product['url']}"
            )
'''

replace_once(
    '''# =========================================================
# STEFFEN-O
# =========================================================
''',
    cardstore_code + '''\n\n# =========================================================
# STEFFEN-O
# =========================================================
''',
    "CardstoreCPH parser",
)


# ---------------------------------------------------------------------------
# 5) Price Watch / source observation integration for CardstoreCPH
# ---------------------------------------------------------------------------
replace_once(
    '''        "epicpanda", "steffeno", "nextlevel"
    }:
''',
    '''        "epicpanda", "steffeno", "nextlevel", "cardstorecph"
    }:
''',
    "Cardstore source observations",
)

replace_once(
    '''    add_products(
        "NEXT LEVEL GAMES",
        "nextlevel",
        current_state.get("nextlevel", {})
    )

    return candidates
''',
    '''    add_products(
        "NEXT LEVEL GAMES",
        "nextlevel",
        current_state.get("nextlevel", {})
    )

    add_products(
        "CARDSTORECPH",
        "cardstorecph",
        current_state.get("cardstorecph", {})
    )

    return candidates
''',
    "Cardstore Price Watch candidates",
)


# ---------------------------------------------------------------------------
# 6) Main loop: baseline-safe CardstoreCPH source before Price Watch
# ---------------------------------------------------------------------------
cardstore_main = r'''
        # -------------------------
        # CARDSTORECPH
        # -------------------------

        try:
            cardstore_was_initialized = "cardstorecph" in state
            old_cardstore = state.get("cardstorecph", {})
            cardstore = fetch_source_products(
                "cardstorecph",
                old_cardstore,
                get_cardstorecph_products,
                new_state,
            )
            cardstore_counts = count_cardstorecph_products(cardstore)

            print(
                f"CARDSTORECPH: {cardstore_counts['POKÉMON']} Pokémon | "
                f"{cardstore_counts['LORCANA']} Lorcana | "
                f"på lager "
                f"{cardstore_counts['POKÉMON_STOCK'] + cardstore_counts['LORCANA_STOCK']}"
            )

            if cardstore_was_initialized:
                process_cardstorecph_changes(old_cardstore, cardstore)
            else:
                print("CARDSTORECPH baseline tilføjet uden historiske alerts.")
                send_discord(
                    "🟢 **CARDSTORECPH overvågning aktiveret**\n"
                    f"⚡ Pokémon: {cardstore_counts['POKÉMON']} produkter "
                    f"({cardstore_counts['POKÉMON_STOCK']} på lager)\n"
                    f"✨ Lorcana: {cardstore_counts['LORCANA']} produkter "
                    f"({cardstore_counts['LORCANA_STOCK']} på lager)\n"
                    "🆕 Nye produkter og restocks overvåges."
                )

            new_state["cardstorecph"] = cardstore
            price_watch_fresh_sources.add("cardstorecph")

        except Exception as error:
            print("CARDSTORECPH fejl:", error)

'''

replace_once(
    '''        # -------------------------
        # PRICE WATCH V3
        # -------------------------
''',
    cardstore_main + '''        # -------------------------
        # PRICE WATCH V3
        # -------------------------
''',
    "Cardstore main loop",
)


# ---------------------------------------------------------------------------
# 7) Human-readable source list
# ---------------------------------------------------------------------------
replace_once(
    '''        f"+ CardsDirect + Nostalgic + &Cards + Pokecards.dk + Epic Panda "
        f"+ Steffen-O + Next Level Games hvert {CHECK_EVERY}. sekund."
''',
    '''        f"+ CardsDirect + Baltzer Games + TCG Shoppen + Pokemons.dk "
        f"+ Pocket Monster + CardstoreCPH + Nostalgic + &Cards + Pokecards.dk "
        f"+ Epic Panda + Steffen-O + Next Level Games hvert {CHECK_EVERY}. sekund."
''',
    "startup Wave 2 source list",
)

PATH.write_text(text, encoding="utf-8")
print(
    "Applied V29 Wave 2 retailers: Baltzer Games, TCG Shoppen, "
    "Pokemons.dk, Pocket Monster, CardstoreCPH"
)
