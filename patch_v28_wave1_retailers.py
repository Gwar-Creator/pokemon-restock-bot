from pathlib import Path

PATH = Path("restock_bot_github.py")
text = PATH.read_text(encoding="utf-8")

MARKER = "WAVE1_RETAILERS_V28 = True"

if MARKER in text:
    print("V28 Wave 1 retailers already applied")
    raise SystemExit(0)


def replace_once(old, new, label):
    global text
    if old not in text:
        raise RuntimeError(f"V28 patch failed: marker not found for {label}")
    text = text.replace(old, new, 1)


replace_once(
    '''ENGLISH_ONLY_V26 = True
PRICE_HISTORY_COMPACT_V27 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    '''ENGLISH_ONLY_V26 = True
PRICE_HISTORY_COMPACT_V27 = True
WAVE1_RETAILERS_V28 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    "V28 marker",
)

replace_once(
    '''    "musenogslottet": 5,
    "nostalgic": 5,
''',
    '''    "musenogslottet": 5,
    "symbizon": 10,
    "cardx": 10,
    "matraws": 20,
    "halmeshule": 5,
    "cardsdirect": 5,
    "nostalgic": 5,
''',
    "source minimums",
)

replace_once(
    '''    "musenogslottet": {
        "label": "MUSEN & SLOTTET",
        "base": "https://www.musenogslottet.dk",
        "feeds": [
            {"game": "POKÉMON", "path": "/collections/pokemon-tcg/products.json"},
            {"game": "LORCANA", "path": "/collections/disney-lorcana/products.json"}
        ]
    }
}
''',
    '''    "musenogslottet": {
        "label": "MUSEN & SLOTTET",
        "base": "https://www.musenogslottet.dk",
        "feeds": [
            {"game": "POKÉMON", "path": "/collections/pokemon-tcg/products.json"},
            {"game": "LORCANA", "path": "/collections/disney-lorcana/products.json"}
        ]
    },
    "symbizon": {
        "label": "SYMBIZON",
        "base": "https://symbizon.dk",
        "feeds": [
            {"game": "POKÉMON", "path": "/collections/pokemon-kort/products.json"}
        ]
    },
    "cardx": {
        "label": "CARDX",
        "base": "https://www.cardx.dk",
        "feeds": [
            {"game": "POKÉMON", "path": "/collections/pokemon/products.json"},
            {"game": "LORCANA", "path": "/collections/disney-lorcana/products.json"}
        ]
    },
    "matraws": {
        "label": "MATRAWS",
        "base": "https://matraws.dk",
        "feeds": [
            {"game": "POKÉMON", "path": "/collections/alt-pokemon/products.json"},
            {"game": "LORCANA", "path": "/collections/disney-lorcana-tcg/products.json"}
        ]
    },
    "halmeshule": {
        "label": "HALMES HULE",
        "base": "https://halmeshule.dk",
        "feeds": [
            {"game": "POKÉMON", "path": "/collections/pokemon-produkter/products.json"},
            {"game": "LORCANA", "path": "/collections/disney-lorcana/products.json"},
            {"game": None, "path": "/collections/preorder/products.json", "preorder": True}
        ]
    },
    "cardsdirect": {
        "label": "CARDSDIRECT",
        "base": "https://cardsdirect.dk",
        "feeds": [
            {"game": "POKÉMON", "path": "/collections/all/products.json"}
        ]
    }
}
''',
    "Shopify Wave 1 sites",
)

replace_once(
    '''                "in_stock": shopify_variant_available(raw),
                "preorder": shopify_is_preorder(raw),
                "url": f"{site['base']}/products/{handle}"
''',
    '''                "in_stock": shopify_variant_available(raw),
                "preorder": bool(feed.get("preorder")) or shopify_is_preorder(raw),
                "url": f"{site['base']}/products/{handle}"
''',
    "feed-level preorder support",
)

replace_once(
    '''        f"+ PokeHulen + Rogerz + MTGwebshop + Luckbox + Spilforsyningen "
        f"+ Musen & Slottet + Nostalgic + &Cards + Pokecards.dk + Epic Panda "
        f"+ Steffen-O + Next Level Games hvert {CHECK_EVERY}. sekund."
''',
    '''        f"+ PokeHulen + Rogerz + MTGwebshop + Luckbox + Spilforsyningen "
        f"+ Musen & Slottet + Symbizon + CardX + Matraws + Halmes Hule "
        f"+ CardsDirect + Nostalgic + &Cards + Pokecards.dk + Epic Panda "
        f"+ Steffen-O + Next Level Games hvert {CHECK_EVERY}. sekund."
''',
    "startup source list",
)

PATH.write_text(text, encoding="utf-8")
print("Applied V28 Wave 1 retailers: Symbizon, CardX, Matraws, Halmes Hule, CardsDirect")
