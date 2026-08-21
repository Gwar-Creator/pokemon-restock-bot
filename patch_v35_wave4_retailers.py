from pathlib import Path

PATH = Path("restock_bot_github.py")
text = PATH.read_text(encoding="utf-8")

MARKER = "WAVE4_RETAILERS_V35 = True"

if MARKER in text:
    print("V35 Wave 4 retailers already applied")
    raise SystemExit(0)


def replace_once(old, new, label):
    global text
    if old not in text:
        raise RuntimeError(f"V35 patch failed: marker not found for {label}")
    text = text.replace(old, new, 1)


replace_once(
    '''WAVE3_SOURCE_FIX_V33 = True
KOCARDZ_ANCHOR_PARSER_V34 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    '''WAVE3_SOURCE_FIX_V33 = True
KOCARDZ_ANCHOR_PARSER_V34 = True
WAVE4_RETAILERS_V35 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    "V35 marker",
)

replace_once(
    '''    "pbcards": 10,
    "kocardz": 5,
    "nostalgic": 5,
''',
    '''    "pbcards": 10,
    "kocardz": 5,
    "vaulted": 15,
    "pokedexet": 10,
    "pokemonportalen": 10,
    "tcgbruus": 5,
    "pokemonplaza": 5,
    "nostalgic": 5,
''',
    "Wave 4 source minimums",
)

replace_once(
    '''    "pbcards": {
        "label": "PBCARDS",
        "base": "https://pbcards.dk",
        "feeds": [
            {"game": "POKÉMON", "path": "/collections/pokemon/products.json"},
            {"game": None, "path": "/collections/new-releases/products.json"}
        ]
    }
}
''',
    '''    "pbcards": {
        "label": "PBCARDS",
        "base": "https://pbcards.dk",
        "feeds": [
            {"game": "POKÉMON", "path": "/collections/pokemon/products.json"},
            {"game": None, "path": "/collections/new-releases/products.json"}
        ]
    },
    "vaulted": {
        "label": "VAULTED",
        "base": "https://www.vaulted.dk",
        "feeds": [
            {"game": None, "path": "/collections/all/products.json"}
        ]
    },
    "pokedexet": {
        "label": "POKEDEXET",
        "base": "https://pokedexet.dk",
        "feeds": [
            {"game": None, "path": "/collections/all/products.json"}
        ]
    }
}
''',
    "Wave 4 Shopify sites",
)

replace_once(
    '''    "kocardz": {
        "label": "KOCARDZ",
        "base": "https://www.kocardz.dk",
        "categories": {},
        "search_max_pages": 3,
        "searches": {
            "POKÉMON": [
                "pokemon booster",
                "pokemon elite trainer",
                "pokemon tin",
                "pokemon collection",
                "pokemon box",
                "pokemon bundle",
                "pokemon blister",
                "pokemon upc"
            ],
            "LORCANA": [
                "lorcana booster",
                "lorcana trove",
                "lorcana gift set",
                "lorcana collection"
            ]
        }
    },
}
''',
    '''    "kocardz": {
        "label": "KOCARDZ",
        "base": "https://www.kocardz.dk",
        "categories": {},
        "search_max_pages": 3,
        "searches": {
            "POKÉMON": [
                "pokemon booster",
                "pokemon elite trainer",
                "pokemon tin",
                "pokemon collection",
                "pokemon box",
                "pokemon bundle",
                "pokemon blister",
                "pokemon upc"
            ],
            "LORCANA": [
                "lorcana booster",
                "lorcana trove",
                "lorcana gift set",
                "lorcana collection"
            ]
        }
    },
    "pokemonportalen": {
        "label": "POKEMONPORTALEN",
        "base": "https://pokemonportalen.dk",
        "categories": {},
        "search_max_pages": 5,
        "searches": {
            "POKÉMON": [
                "booster",
                "elite trainer",
                "tin",
                "collection",
                "booster bundle",
                "blister",
                "ultra premium"
            ]
        }
    },
    "tcgbruus": {
        "label": "TCGBRUUS",
        "base": "https://tcgbruus.dk",
        "categories": {},
        "search_max_pages": 5,
        "searches": {
            "POKÉMON": [
                "pokemon booster",
                "elite trainer",
                "pokemon tin",
                "pokemon collection",
                "booster bundle",
                "pokemon blister",
                "pokemon box"
            ],
            "LORCANA": [
                "lorcana booster",
                "lorcana trove",
                "lorcana gift set"
            ]
        }
    },
    "pokemonplaza": {
        "label": "POKEMON PLAZA",
        "base": "https://pokemonplaza.dk",
        "categories": {},
        "searches": {}
    },
}
''',
    "Wave 4 Woo/custom sites",
)

pokemonplaza_code = r'''

POKEMONPLAZA_BASE = "https://pokemonplaza.dk"
POKEMONPLAZA_API_URL = POKEMONPLAZA_BASE + "/json/products"
POKEMONPLAZA_FEEDS = (
    {"id": 3, "url": POKEMONPLAZA_BASE + "/shop/3-booster-boxes/", "preorder": False},
    {"id": 4, "url": POKEMONPLAZA_BASE + "/shop/4-booster-packs/", "preorder": False},
    {"id": 7, "url": POKEMONPLAZA_BASE + "/shop/7-elite-trainer-box/", "preorder": False},
    {"id": 8, "url": POKEMONPLAZA_BASE + "/shop/8-tins-og-collection-boxes/", "preorder": False},
    {"id": 24, "url": POKEMONPLAZA_BASE + "/shop/24-forudbestilling/", "preorder": True},
)


def _pokemonplaza_price(raw):
    rows = raw.get("Prices") or []
    if not rows:
        return None
    row = rows[0] or {}
    for key in ("PriceMinWithVat", "PriceMin", "PriceMaxWithVat", "PriceMax"):
        value = row.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return None


def _pokemonplaza_stock(raw):
    for key in ("StockWithoutReservation", "Stock"):
        value = raw.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return None


def _pokemonplaza_preorder(raw, force=False):
    if force:
        return True
    text_value = " ".join(
        [
            woocommerce_clean_text(raw.get("Title")),
            woocommerce_clean_text(raw.get("DeliveryTimeText")),
        ]
    ).lower()
    return any(
        marker in text_value
        for marker in ("forudbestil", "forudbestilling", "preorder", "pre-order")
    )


def get_pokemonplaza_products():
    session = requests.Session()
    session.headers.update(
        {
            **BROWSER_HEADERS,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
        }
    )

    session.get(POKEMONPLAZA_BASE + "/", timeout=20).raise_for_status()
    products = {}

    for feed in POKEMONPLAZA_FEEDS:
        session.get(feed["url"], timeout=20).raise_for_status()
        response = session.get(
            POKEMONPLAZA_API_URL,
            params={
                "field": "categoryId",
                "id": feed["id"],
                "page": 1,
                "limit": 96,
                "filterGenerate": "true",
                "currencyIso": "DKK",
            },
            headers={"Referer": feed["url"]},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()

        for raw in payload.get("products") or []:
            name = woocommerce_clean_text(raw.get("Title"))
            if not name:
                continue

            synthetic = {
                "name": name,
                "categories": [{"name": "Pokemon"}],
                "short_description": "",
                "description": "",
            }
            if not woocommerce_is_relevant_sealed(synthetic):
                continue

            product_id = str(raw.get("Id") or "").strip()
            if not product_id:
                continue

            preorder = _pokemonplaza_preorder(raw, force=feed["preorder"])
            stock = _pokemonplaza_stock(raw)
            delivery = woocommerce_clean_text(raw.get("DeliveryTimeText")).lower()
            explicit_out = (
                "udsolgt" in delivery
                or "ikke på lager" in delivery
                or "ikke pa lager" in delivery
            )
            in_stock = (
                (stock is not None and stock > 0)
                or (
                    stock is None
                    and not explicit_out
                    and ("på lager" in delivery or "pa lager" in delivery)
                )
            ) and not preorder

            handle = str(raw.get("Handle") or "").strip()
            products[product_id] = {
                "name": name,
                "game": "POKÉMON",
                "price": _pokemonplaza_price(raw),
                "in_stock": bool(in_stock),
                "preorder": bool(preorder),
                "url": urljoin(POKEMONPLAZA_BASE, handle) if handle else feed["url"],
            }

    return products
'''

replace_once(
    '''def get_woocommerce_products(site_key):
    if site_key == "kocardz":
        return get_kocardz_products()

    site = WOOCOMMERCE_SITES[site_key]
''',
    pokemonplaza_code + '''\n\ndef get_woocommerce_products(site_key):
    if site_key == "kocardz":
        return get_kocardz_products()
    if site_key == "pokemonplaza":
        return get_pokemonplaza_products()

    site = WOOCOMMERCE_SITES[site_key]
''',
    "Pokemon Plaza DanDomain adapter",
)

PATH.write_text(text, encoding="utf-8")
print(
    "Applied V35 Wave 4 retailers: Vaulted, Pokedexet, Pokemonportalen, "
    "TCGBruuS, Pokemon Plaza"
)
