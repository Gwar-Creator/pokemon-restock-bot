from pathlib import Path

PATH = Path("restock_bot_github.py")
text = PATH.read_text(encoding="utf-8")

MARKER = "WAVE3_RETAILERS_V31 = True"

if MARKER in text:
    print("V31 Wave 3 retailers already applied")
    raise SystemExit(0)


def replace_once(old, new, label):
    global text
    if old not in text:
        raise RuntimeError(f"V31 patch failed: marker not found for {label}")
    text = text.replace(old, new, 1)


replace_once(
    '''WAVE2_RETAILERS_V29 = True
CARDSTORECPH_RETIRED_V30 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    '''WAVE2_RETAILERS_V29 = True
CARDSTORECPH_RETIRED_V30 = True
WAVE3_RETAILERS_V31 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    "V31 marker",
)

replace_once(
    '''    "pokemonsdk": 5,
    "pocketmonster": 5,
    "nostalgic": 5,
''',
    '''    "pokemonsdk": 5,
    "pocketmonster": 5,
    "funshop": 10,
    "pokepulls": 10,
    "staalz": 5,
    "pbcards": 10,
    "kocardz": 5,
    "nostalgic": 5,
''',
    "Wave 3 source minimums",
)

replace_once(
    '''    "tcgshoppen": {
        "label": "TCG SHOPPEN",
        "base": "https://www.tcgshoppen.dk",
        "feeds": [
            {"game": "POKÉMON", "path": "/collections/hele-vores-udvalg-af-pokemon/products.json"}
        ]
    }
}
''',
    '''    "tcgshoppen": {
        "label": "TCG SHOPPEN",
        "base": "https://www.tcgshoppen.dk",
        "feeds": [
            {"game": "POKÉMON", "path": "/collections/hele-vores-udvalg-af-pokemon/products.json"}
        ]
    },
    "funshop": {
        "label": "FUN-SHOP",
        "base": "https://www.fun-shop.dk",
        "feeds": [
            {"game": "POKÉMON", "path": "/collections/boosters-1/products.json"},
            {"game": "POKÉMON", "path": "/collections/pokemon-bokse-og-tins/products.json"}
        ]
    },
    "pokepulls": {
        "label": "POKÉPULLS",
        "base": "https://pokepulls.dk",
        "feeds": [
            {"game": None, "path": "/collections/all/products.json"}
        ]
    },
    "staalz": {
        "label": "STAALZ",
        "base": "https://staalz.dk",
        "feeds": [
            {"game": None, "path": "/products.json"}
        ]
    },
    "pbcards": {
        "label": "PBCARDS",
        "base": "https://pbcards.dk",
        "feeds": [
            {"game": "POKÉMON", "path": "/collections/pokemon/products.json"},
            {"game": None, "path": "/collections/new-releases/products.json"}
        ]
    }
}
''',
    "Wave 3 Shopify sites",
)

replace_once(
    '''    "pocketmonster": {
        "label": "POCKET MONSTER",
        "base": "https://pocketmonster.dk",
        "categories": {},
        "searches": {
            "POKÉMON": ["booster", "elite trainer", "tin", "collection", "box"]
        }
    },
}
''',
    '''    "pocketmonster": {
        "label": "POCKET MONSTER",
        "base": "https://pocketmonster.dk",
        "categories": {},
        "searches": {
            "POKÉMON": ["booster", "elite trainer", "tin", "collection", "box"]
        }
    },
    "kocardz": {
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
    "KoCardz WooCommerce source",
)

replace_once(
    '''        f"+ CardsDirect + Baltzer Games + TCG Shoppen + Pokemons.dk "
        f"+ Pocket Monster + Nostalgic + &Cards + Pokecards.dk "
        f"+ Epic Panda + Steffen-O + Next Level Games hvert {CHECK_EVERY}. sekund."
''',
    '''        f"+ CardsDirect + Baltzer Games + TCG Shoppen + Pokemons.dk "
        f"+ Pocket Monster + Fun-shop + PokéPulls + Staalz + PBCards + KoCardz "
        f"+ Nostalgic + &Cards + Pokecards.dk + Epic Panda + Steffen-O "
        f"+ Next Level Games hvert {CHECK_EVERY}. sekund."
''',
    "startup source list",
)

PATH.write_text(text, encoding="utf-8")
print("Applied V31 Wave 3 retailers: KoCardz, Fun-shop, PokéPulls, Staalz, PBCards")
