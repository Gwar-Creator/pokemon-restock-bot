import requests

try:
    from requests_oauthlib import OAuth1
except ImportError:
    OAuth1 = None

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None
import json
import csv
import io
import time
import os
import re
import base64
import html
import hashlib
import unicodedata

from bs4 import BeautifulSoup
from urllib.parse import urljoin, unquote, urlencode
from datetime import datetime
from zoneinfo import ZoneInfo


# =========================================================
# INDSTILLINGER
# =========================================================

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
PRICE_WATCH_WEBHOOK_URL = os.getenv("PRICE_WATCH_WEBHOOK_URL", "").strip()
PRICE_HISTORY_WEBHOOK_URL = os.getenv("PRICE_HISTORY_WEBHOOK_URL", "").strip()

# Persistent alert memory is hydrated from state before scanning starts.
# It prevents a flapping source from repeating the same Discord alert.
RESTOCK_ALERT_MEMORY = {}
PRICE_ALERT_MEMORY = {}

PRICE_SIGNAL_CLEANUP_V23 = True
RETAILER_CLEANUP_V25 = True
ENGLISH_ONLY_V26 = True
PRICE_HISTORY_COMPACT_V27 = True
WAVE1_RETAILERS_V28 = True
WAVE2_RETAILERS_V29 = True
CARDSTORECPH_RETIRED_V30 = True
WAVE3_RETAILERS_V31 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
RESTOCK_NEW_PRODUCT_COOLDOWN_SECONDS = 24 * 60 * 60
PRICE_ALERT_COOLDOWN_SECONDS = 24 * 60 * 60
PRICE_ALERT_MIN_IMPROVEMENT_DKK = 25.0
PRICE_ALERT_MIN_IMPROVEMENT_PCT = 0.05

# Kanalroller: Restock viser lagerhændelser. Prisændringer hører hjemme i
# Price Watch / Price History, så samme prisfald ikke støjer i flere kanaler.
RESTOCK_PRICE_ALERTS_ENABLED = False

SOURCE_MIN_PRODUCTS = {
    "coolshop": 10,
    "proshop": 2,
    "br": 5,
    "bilka": 5,
    "foetex": 5,
    "pokehulen": 10,
    "rogerz": 20,
    "mtgwebshop": 10,
    "luckbox": 5,
    "spilforsyningen": 5,
    "musenogslottet": 5,
    "symbizon": 10,
    "cardx": 10,
    "matraws": 20,
    "halmeshule": 5,
    "cardsdirect": 5,
    "baltzer": 5,
    "tcgshoppen": 5,
    "pokemonsdk": 5,
    "pocketmonster": 5,
    "funshop": 10,
    "pokepulls": 10,
    "staalz": 5,
    "pbcards": 10,
    "kocardz": 5,
    "nostalgic": 5,
    "andcards": 5,
    "pokecards": 10,
    "epicpanda": 10,
    "steffeno": 5,
    "nextlevel": 5,
}
SOURCE_MAX_DROP_RATIO = 0.60

CARDMARKET_APP_TOKEN = os.getenv("CARDMARKET_APP_TOKEN", "").strip()
CARDMARKET_APP_SECRET = os.getenv("CARDMARKET_APP_SECRET", "").strip()
CARDMARKET_ACCESS_TOKEN = os.getenv("CARDMARKET_ACCESS_TOKEN", "").strip()
CARDMARKET_ACCESS_SECRET = os.getenv("CARDMARKET_ACCESS_SECRET", "").strip()
CARDMARKET_BASE = "https://apiv2.cardmarket.com/ws/v2.0"
CARDMARKET_MIN_SELLS = 25
CARDMARKET_EXCLUDED_COUNTRIES = {"GB", "UK", "CH"}
CARDMARKET_GAME_IDS = {}

RUN_ONCE = os.getenv("RUN_ONCE", "0").strip() == "1"
CHECK_EVERY = int(os.getenv("CHECK_EVERY", "300"))
STATE_FILE = "restock_state_v2.json"

PRICE_WATCH_TIMEZONE = os.getenv(
    "PRICE_WATCH_TIMEZONE",
    "Europe/Copenhagen"
).strip()

try:
    PRICE_WATCH_DAILY_HOUR = int(
        os.getenv("PRICE_WATCH_DAILY_HOUR", "9")
    )
except ValueError:
    PRICE_WATCH_DAILY_HOUR = 9

PRICE_WATCH_DAILY_HOUR = max(
    0,
    min(23, PRICE_WATCH_DAILY_HOUR)
)

try:
    PRICE_HISTORY_DAILY_HOUR = int(
        os.getenv("PRICE_HISTORY_DAILY_HOUR", "9")
    )
except ValueError:
    PRICE_HISTORY_DAILY_HOUR = 9

PRICE_HISTORY_DAILY_HOUR = max(
    0,
    min(23, PRICE_HISTORY_DAILY_HOUR)
)

if not WEBHOOK_URL:
    raise RuntimeError(
        "DISCORD_WEBHOOK_URL mangler. "
        "Opret den som GitHub Actions repository secret."
    )


# =========================================================
# COOLSHOP
# =========================================================

COOLSHOP_API = "https://www.coolshop.dk/api/search"
COOLSHOP_BASE = "https://www.coolshop.dk"

COOLSHOP_FEEDS = [
    {
        "game": "POKÉMON",
        "path": "legetoej/samlekort/maerke=pokemon/",
        "filter": None,
        "sort": ""
    },
    {
        "game": "LORCANA",
        "path": "legetoej/samlekort/maerke=disney/",
        "filter": "lorcana",
        "sort": "newest"
    }
]


# =========================================================
# PROSHOP
# =========================================================

PROSHOP_URL = "https://www.proshop.dk/pokemon-kort"
PROSHOP_BASE = "https://www.proshop.dk"


# =========================================================
# BR
# =========================================================

BR_HOME = "https://www.br.dk/"
BR_BASE = "https://www.br.dk"
BR_API_BASE = "https://api.sallinggroup.com/v1/ecommerce/br"
BR_ALGOLIA_INDEX = "prod_BR_PRODUCTS"
BR_KOLDING_SITE_ID = "2021"
BR_ESBJERG_SITE_ID = "2011"

BR_CONFIG_CACHE = None


# =========================================================
# BILKA + FOETEX (SAMME SALLING-ARKITEKTUR)
# =========================================================

SALLING_SITES = {
    "bilka": {
        "label": "BILKA",
        "home": "https://www.bilka.dk/",
        "base": "https://www.bilka.dk",
        "local_stores": {
            "1662": "Bilka Kolding",
            "1659": "Bilka Esbjerg"
        }
    },
    "foetex": {
        "label": "FØTEX",
        "home": "https://www.foetex.dk/",
        "base": "https://www.foetex.dk",
        "local_stores": {
            "1307": "føtex Kolding",
            "1370": "føtex Kolding Syd",
            "1223": "føtex Esbjerg Broen"
        }
    }
}

SALLING_CONFIG_CACHE = {}


# =========================================================
# ELGIGANTEN
# =========================================================

ELGIGANTEN_HOME = "https://www.elgiganten.dk/"
ELGIGANTEN_BASE = "https://www.elgiganten.dk"
ELGIGANTEN_SIGNED_KEY_URL = (
    "https://www.elgiganten.dk/api/algolia/signed-api-key"
)
ELGIGANTEN_CATEGORY_URL = (
    "https://www.elgiganten.dk/sport-fritid-hobby/"
    "samleobjekter-merchandise/samlekort/pokemon-kort-tcg"
)
ELGIGANTEN_ALGOLIA_APP_ID = "Z0FL7R8UBH"
ELGIGANTEN_ALGOLIA_INDEX = "commerce_b2c_OCDKELG"
ELGIGANTEN_KOLDING_STORE_ID = "3003"
ELGIGANTEN_ESBJERG_STORE_ID = "3022"

ELGIGANTEN_KEY_CACHE = {
    "api_key": None,
    "valid_until": 0,
    "retry_after": 0,
    "rate_limit_failures": 0,
}


# =========================================================
# SHOPIFY-WEBSHOPS
# =========================================================

SHOPIFY_SITES = {
    "pokehulen": {
        "label": "POKEHULEN",
        "base": "https://pokehulen.dk",
        "feeds": [
            {
                "game": None,
                "path": "/products.json"
            }
        ]
    },
    "rogerz": {
        "label": "ROGERZ",
        "base": "https://rogerz.dk",
        "feeds": [
            {
                "game": "POKÉMON",
                "path": "/collections/pokemon-kort/products.json"
            },
            {
                "game": "LORCANA",
                "path": "/collections/disney-lorcana/products.json"
            }
        ]
    },
    "mtgwebshop": {
        "label": "MTGWEBSHOP",
        "base": "https://mtgwebshop.dk",
        "feeds": [
            {
                "game": "POKÉMON",
                "path": "/collections/pokemontilbud/products.json"
            },
            {
                "game": "LORCANA",
                "path": "/collections/disney-lorcana/products.json"
            }
        ]
    },
    "luckbox": {
        "label": "LUCKBOX",
        "base": "https://www.luckboxcardshop.dk",
        "feeds": [
            {
                "game": "POKÉMON",
                "path": "/collections/booster-box/products.json"
            },
            {
                "game": "POKÉMON",
                "path": "/collections/bundles-1/products.json"
            },
            {
                "game": "POKÉMON",
                "path": "/collections/booster-packs/products.json"
            },
            {
                "game": "POKÉMON",
                "path": "/collections/ex-box/products.json"
            },
            {
                "game": "POKÉMON",
                "path": "/collections/elite-trainer-box/products.json"
            },
            {
                "game": "POKÉMON",
                "path": "/collections/blisters/products.json"
            },
            {
                "game": "POKÉMON",
                "path": "/collections/tins/products.json"
            },
            {
                "game": "POKÉMON",
                "path": "/collections/japansk-sealed-produkter/products.json"
            }
        ]
    },
    "spilforsyningen": {
        "label": "SPILFORSYNINGEN",
        "base": "https://spilforsyningen.dk",
        "feeds": [
            {"game": "POKÉMON", "path": "/collections/pokemon-boosters/products.json"},
            {"game": "POKÉMON", "path": "/collections/pokemon-boxes/products.json"},
            {"game": "POKÉMON", "path": "/collections/pokemon-decks/products.json"},
            {"game": "POKÉMON", "path": "/collections/pokemon-displays-og-boosters/products.json"},
            {"game": "POKÉMON", "path": "/collections/pokemon-tins/products.json"},
            {"game": "LORCANA", "path": "/collections/disney-lorcana/products.json"}
        ]
    },
    "musenogslottet": {
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

SHOPIFY_MAX_PAGES = 20
SHOPIFY_PAGE_SIZE = 250


# =========================================================
# WOOCOMMERCE-WEBSHOPS
# =========================================================

WOOCOMMERCE_SITES = {
    "nostalgic": {
        "label": "NOSTALGIC",
        "base": "https://nostalgiccollectibles.dk",
        "categories": {
            "POKÉMON": 15,
            "LORCANA": 75
        }
    },
    "andcards": {
        "label": "ANDCARDS",
        "base": "https://www.andcards.dk",
        "categories": {
            "POKÉMON": 21,
            "LORCANA": 1264
        }
    },
    "pokecards": {
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

WOOCOMMERCE_API_PATH = "/wp-json/wc/store/v1/products"
WOOCOMMERCE_PAGE_SIZE = 100
WOOCOMMERCE_MAX_PAGES = 20



# =========================================================
# NEXT LEVEL GAMES
# =========================================================

NEXTLEVEL_BASE = "https://www.nextlevelgames.dk"
NEXTLEVEL_FEEDS = [
    {"game": "POKÉMON", "label": "Forudbestillinger", "url": "https://www.nextlevelgames.dk/144-pokemon-tcg-forudbestillinger", "preorder_feed": True},
    {"game": "POKÉMON", "label": "Booster Packs", "url": "https://www.nextlevelgames.dk/153-pokemon-tcg-booster-packs", "preorder_feed": False},
    {"game": "POKÉMON", "label": "Booster Box", "url": "https://www.nextlevelgames.dk/154-pokemon-tcg-booster-box", "preorder_feed": False},
    {"game": "POKÉMON", "label": "Elite Trainer Box", "url": "https://www.nextlevelgames.dk/155-pokemon-tcg-elite-trainer-box", "preorder_feed": False},
    {"game": "POKÉMON", "label": "Tin Box", "url": "https://www.nextlevelgames.dk/156-pokemon-tcg-tin-box", "preorder_feed": False},
    {"game": "POKÉMON", "label": "V Box og andre Boxe", "url": "https://www.nextlevelgames.dk/145-pokemon-tcg-v-box-og-andre-boxe", "preorder_feed": False},
    {"game": "LORCANA", "label": "Lorcana sealed", "url": "https://www.nextlevelgames.dk/376-disney-lorcana-tcg-produkter-typer", "preorder_feed": False}
]

NEXTLEVEL_BLOCKED_MARKERS = (
    "deckbox", "deck box", "playmat", "mappe", "binder",
    "portfolio", "sleeve", "sleeves", "lommer"
)


# =========================================================
# EPIC PANDA
# =========================================================

EPICPANDA_BASE = "https://epicpanda.dk"
EPICPANDA_FEEDS = [
    {
        "game": "POKÉMON",
        "pattern": "https://epicpanda.dk/shop/pokemon-kort-360s{page}.html"
    },
    {
        "game": "LORCANA",
        "pattern": "https://epicpanda.dk/shop/disney-lorcana-1253s{page}.html"
    }
]
EPICPANDA_MAX_PAGES = 20



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


# =========================================================
# STEFFEN-O
# =========================================================

STEFFENO_BASE = "https://steffen-o.dk"
STEFFENO_CATEGORY_URL = "https://steffen-o.dk/shop/16-pokemon/"
STEFFENO_API_URL = "https://steffen-o.dk/json/products"
STEFFENO_CATEGORY_ID = 16
STEFFENO_PAGE_SIZE = 96


# =========================================================
# HEADERS
# =========================================================

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )
}


# =========================================================
# DISCORD
# =========================================================

def _discord_embed_color(message, kind="restock"):
    upper = (message or "").upper()

    if "FORUDBESTILLING" in upper or "PREORDER" in upper:
        return 0xFEE75C

    if (
        "BEDRE PRIS" in upper
        or "PRISFALD" in upper
        or "RESTOCK" in upper
    ):
        return 0x57F287

    if "BEDSTE PRIS ÆNDRET" in upper:
        return 0xF0B232

    if "NYT" in upper or "DAGENS BEDSTE PRISER" in upper:
        return 0x5865F2

    return 0x5865F2 if kind == "restock" else 0x57F287


def _discord_embed_payload(message, kind="restock"):
    lines = (message or "").splitlines()

    if lines:
        title = lines[0].replace("**", "").strip()
        description = "\n".join(lines[1:]).strip()
    else:
        title = "MasterBot"
        description = ""

    if not title:
        title = "MasterBot"

    # Discord limits: title 256, description 4096.
    title = title[:256]
    description = (description or " ")[:4096]

    footer = (
        "MasterBot · Price Watch"
        if kind == "price"
        else "MasterBot · Restock Watch"
    )

    return {
        "username": "MasterBot",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": _discord_embed_color(message, kind),
                "footer": {"text": footer},
            }
        ],
    }


def _post_discord(webhook_url, message, kind):
    response = requests.post(
        webhook_url,
        json=_discord_embed_payload(message, kind),
        headers={
            "User-Agent": "Pokemon-Lorcana-MasterBot/1.3"
        },
        timeout=20,
    )

    response.raise_for_status()


def send_discord(message):
    alert_decision = restock_alert_decision(message)

    if not alert_decision:
        print("RESTOCK ALERT: dublet/flap undertrykt")
        return False

    _post_discord(
        WEBHOOK_URL,
        message,
        "restock",
    )
    alert_key, alert_entry = alert_decision
    if alert_key:
        RESTOCK_ALERT_MEMORY[alert_key] = alert_entry
    return True


def send_price_watch(message):
    if not PRICE_WATCH_WEBHOOK_URL:
        print(
            "PRICE_WATCH_WEBHOOK_URL mangler - "
            "springer Price Watch-besked over."
        )
        return False

    alert_decision = price_alert_decision(message)

    if not alert_decision:
        print("PRICE WATCH: gentaget prisalert undertrykt")
        return False

    _post_discord(
        PRICE_WATCH_WEBHOOK_URL,
        message,
        "price",
    )
    alert_key, alert_entry = alert_decision
    if alert_key:
        PRICE_ALERT_MEMORY[alert_key] = alert_entry
    return True


def send_price_history_embed(title, description, color=0x5865F2, footer=None):
    if not PRICE_HISTORY_WEBHOOK_URL:
        return False

    embed = {
        "title": (title or "Price History")[:256],
        "description": (description or " ")[:4096],
        "color": color,
        "footer": {
            "text": (
                footer
                or "MasterBot · Price History"
            )[:2048]
        },
    }

    response = requests.post(
        PRICE_HISTORY_WEBHOOK_URL,
        json={
            "username": "MasterBot",
            "allowed_mentions": {"parse": []},
            "embeds": [embed],
        },
        headers={
            "User-Agent": "Pokemon-Lorcana-MasterBot/1.4"
        },
        timeout=20,
    )
    response.raise_for_status()
    return True


# =========================================================
# PRIS
# =========================================================

def parse_price(text):
    match = re.search(
        r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d+(?:,\d{2})?)\s*kr",
        text
    )

    if not match:
        return None

    value = match.group(1)

    value = value.replace(".", "")
    value = value.replace(",", ".")

    try:
        return float(value)
    except ValueError:
        return None


def format_price(price):
    if price is None:
        return "Pris ikke oplyst"

    return (
        f"{price:,.2f} kr."
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _now_epoch():
    return int(time.time())


def _alert_memory_cleanup(memory, max_age_seconds=7 * 24 * 60 * 60):
    cutoff = _now_epoch() - max_age_seconds
    return {
        key: value
        for key, value in (memory or {}).items()
        if isinstance(value, dict)
        and safe_int(value.get("sent_at"), 0) >= cutoff
    }


def _alert_identity(message, channel):
    lines = [
        line.replace("**", "").strip()
        for line in str(message or "").splitlines()
        if line.strip()
    ]
    headline = lines[0].upper() if lines else "UNKNOWN"
    product = lines[1].lower() if len(lines) > 1 else "unknown"
    url_match = re.search(r"https?://\S+", str(message or ""))
    url = url_match.group(0).rstrip(").,>") if url_match else ""

    if "PRISFALD" in headline or "BEDRE PRIS" in headline:
        event_type = "PRICE"
    elif "RESTOCK" in headline:
        event_type = "RESTOCK"
    elif "FORUDBESTILLING" in headline or "PREORDER" in headline:
        event_type = "PREORDER"
    elif "NYT" in headline:
        event_type = "NEW"
    elif "BILLIGSTE BUTIK" in headline:
        event_type = "SHOP"
    else:
        event_type = headline[:80]

    identity_url = "" if channel == "price" else url
    raw = "|".join((channel, event_type, product, identity_url))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32], event_type


def _price_values_from_change(message):
    for line in str(message or "").splitlines():
        if "→" not in line or "kr" not in line.lower():
            continue

        values = []
        for raw in re.findall(
            r"(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:,\d{1,2})?)\s*kr",
            line,
            flags=re.IGNORECASE,
        ):
            try:
                values.append(float(raw.replace(".", "").replace(",", ".")))
            except ValueError:
                continue

        if len(values) >= 2:
            return values[0], values[-1]

    return None, None


def _price_beats_recent_alert(previous, new_price):
    if not isinstance(previous, dict):
        return True

    sent_at = safe_int(previous.get("sent_at"), 0)
    if _now_epoch() - sent_at >= PRICE_ALERT_COOLDOWN_SECONDS:
        return True

    try:
        old_alert_price = float(previous.get("price"))
    except (TypeError, ValueError):
        return False

    required_improvement = max(
        PRICE_ALERT_MIN_IMPROVEMENT_DKK,
        old_alert_price * PRICE_ALERT_MIN_IMPROVEMENT_PCT,
    )
    return new_price <= old_alert_price - required_improvement


def restock_alert_decision(message):
    global RESTOCK_ALERT_MEMORY
    RESTOCK_ALERT_MEMORY = _alert_memory_cleanup(RESTOCK_ALERT_MEMORY)
    key, event_type = _alert_identity(message, "restock")
    previous = RESTOCK_ALERT_MEMORY.get(key)
    now_epoch = _now_epoch()

    if event_type == "PRICE":
        if not RESTOCK_PRICE_ALERTS_ENABLED:
            print("RESTOCK ALERT: prisændring håndteres i priskanalerne")
            return None

        _, new_price = _price_values_from_change(message)
        if new_price is None:
            cooldown = PRICE_ALERT_COOLDOWN_SECONDS
            if (
                isinstance(previous, dict)
                and now_epoch - safe_int(previous.get("sent_at"), 0) < cooldown
            ):
                return None
        elif not _price_beats_recent_alert(previous, new_price):
            return None

        return key, {"sent_at": now_epoch, "price": new_price}

    cooldown = (
        RESTOCK_NEW_PRODUCT_COOLDOWN_SECONDS
        if event_type in ("NEW", "PREORDER")
        else RESTOCK_DUPLICATE_COOLDOWN_SECONDS
    )
    if (
        isinstance(previous, dict)
        and now_epoch - safe_int(previous.get("sent_at"), 0) < cooldown
    ):
        return None

    return key, {"sent_at": now_epoch}


def price_alert_decision(message):
    global PRICE_ALERT_MEMORY
    upper = str(message or "").upper()

    # Daily summaries are intentionally not deduplicated here; their own
    # last_daily_date gate already guarantees one summary per day.
    if "BEDRE PRIS FUNDET" not in upper and "BILLIGSTE BUTIK ÆNDRET" not in upper:
        return "", {}

    PRICE_ALERT_MEMORY = _alert_memory_cleanup(PRICE_ALERT_MEMORY)
    key, event_type = _alert_identity(message, "price")
    previous = PRICE_ALERT_MEMORY.get(key)
    now_epoch = _now_epoch()

    # A retailer becoming cheapest at the same price is not actionable enough
    # for an intraday Discord alert. Price/history state still records it.
    if event_type == "SHOP":
        return None

    if event_type == "PRICE":
        _, new_price = _price_values_from_change(message)
        if new_price is None or not _price_beats_recent_alert(previous, new_price):
            return None
        return key, {"sent_at": now_epoch, "price": new_price}

    if (
        isinstance(previous, dict)
        and now_epoch - safe_int(previous.get("sent_at"), 0) < 6 * 60 * 60
    ):
        return None

    return key, {"sent_at": now_epoch}


def _source_health_update(state_target, source_key, **updates):
    health = dict(state_target.get("_source_health") or {})
    entry = dict(health.get(source_key) or {})
    entry.update(updates)
    health[source_key] = entry
    state_target["_source_health"] = health
    return entry


def _source_failure(state_target, source_key, error, observed_count=None):
    old_entry = (state_target.get("_source_health") or {}).get(source_key) or {}
    failures = safe_int(old_entry.get("consecutive_failures"), 0) + 1
    entry = _source_health_update(
        state_target,
        source_key,
        status="failed",
        last_attempt=datetime.now(ZoneInfo("UTC")).isoformat(),
        consecutive_failures=failures,
        last_error=str(error)[:500],
        observed_count=observed_count,
    )

    if failures == 3:
        send_discord(
            "⚠️ **SCANNERKILDE HAR FEJLET 3 GANGE**\n"
            f"**{source_key.upper()}**\n"
            f"Fejl: {entry['last_error']}"
        )


def fetch_source_products(source_key, old_products, fetcher, state_target):
    try:
        products = fetcher()
    except Exception as error:
        _source_failure(state_target, source_key, error)
        raise

    if not isinstance(products, dict):
        error = RuntimeError("kilden returnerede ikke et produkt-dictionary")
        _source_failure(state_target, source_key, error)
        raise error

    new_count = len(products)
    old_count = len(old_products) if isinstance(old_products, dict) else 0
    minimum = SOURCE_MIN_PRODUCTS.get(source_key, 1)

    if new_count < minimum:
        error = RuntimeError(
            f"mistænkeligt lavt produktantal: {new_count} < {minimum}"
        )
        _source_failure(state_target, source_key, error, new_count)
        raise error

    if (
        old_count >= minimum
        and new_count < old_count * (1.0 - SOURCE_MAX_DROP_RATIO)
    ):
        error = RuntimeError(
            f"mistænkeligt produktfald: {old_count} → {new_count}"
        )
        _source_failure(state_target, source_key, error, new_count)
        raise error

    old_health = (state_target.get("_source_health") or {}).get(source_key) or {}
    was_failed = safe_int(old_health.get("consecutive_failures"), 0) >= 3
    _source_health_update(
        state_target,
        source_key,
        status="ok",
        last_attempt=datetime.now(ZoneInfo("UTC")).isoformat(),
        last_success=datetime.now(ZoneInfo("UTC")).isoformat(),
        last_count=new_count,
        observed_count=new_count,
        consecutive_failures=0,
        last_error="",
    )

    if was_failed:
        send_discord(
            "✅ **SCANNERKILDE KØRER IGEN**\n"
            f"**{source_key.upper()}**\n"
            f"Produkter fundet: {new_count}"
        )

    return products
        

# ============================================================
# SHARED RELEVANCE FILTER
# ============================================================

ACCESSORY_HARD_BLOCK_MARKERS = (
    "penalhus",
    "pencil case",
    "repack",
)

ACCESSORY_BLOCK_MARKERS = (
    "portfolio",
    "binder",
    "mappe",
    "samlemappe",
    "album",
    "pocket page",
    "kortlomme",
    "kortlommer",
    "sleeve",
    "dragonshield",
    "dragon shield",
    "ultrapro",
    "ultra pro",
    "playmat",
    "play mat",
    "deck protector",
    "deck box",
    "deckbox",
    "storage box",
    "opbevaring",
    "toploader",
    "top loader",
    "card saver",
    "card case",
    "display case",
    "card holder",
    "kortbeskytter",
    "kortbeskyttelse",
    "acrylic",
    "acryl",
    "akryl",
)

# These are real sealed TCG products with boosters, not loose accessories.
ACCESSORY_COLLECTION_EXCEPTIONS = (
    "binder collection",
    "playmat collection",
    "play mat collection",
    "accessory pouch special collection",
    "sleeved booster",
)


def is_low_signal_accessory_name(name):
    """Return True for accessories/repack products that should stay silent."""
    text = " " + re.sub(r"\s+", " ", str(name or "").lower()) + " "

    if any(marker in text for marker in ACCESSORY_HARD_BLOCK_MARKERS):
        return True

    if any(marker in text for marker in ACCESSORY_COLLECTION_EXCEPTIONS):
        return False

    return any(marker in text for marker in ACCESSORY_BLOCK_MARKERS)


NON_ENGLISH_CARD_MARKERS = (
    "japansk", "japanese", "japan import",
    "kinesisk", "chinese", "simplified chinese", "traditional chinese",
    "koreansk", "korean",
    "tysk", "german", "deutsch",
    "fransk", "french",
    "italiensk", "italian",
    "spansk", "spanish",
    "portugisisk", "portuguese",
    "hollandsk", "dutch",
    "thai", "thailand",
    "indonesisk", "indonesian",
)


def is_english_card_product(name):
    """Allow English/unspecified card language; block explicit foreign editions."""
    text = " " + re.sub(r"\s+", " ", str(name or "").lower()) + " "

    if any(marker in text for marker in NON_ENGLISH_CARD_MARKERS):
        return False

    # Only bracketed/separated short codes are treated as language markers,
    # avoiding false positives from ordinary Danish words.
    if re.search(
        r"(?:\(|\[|\{|\-|/)\s*(?:jp|jpn|cn|chs|cht|kr|kor)\s*(?:\)|\]|\}|\-|/)",
        text,
        flags=re.IGNORECASE,
    ):
        return False

    return True


# ============================================================
# RESTOCK ALERT FILTER
# ============================================================

def restock_alert_allowed(product, game_override=None):
    """Keep low-signal products in state, but silence them on Discord."""
    name = str((product or {}).get("name", "")).lower()
    game = game_override or (product or {}).get("game")

    if not is_english_card_product(name):
        return False

    if is_low_signal_accessory_name(name):
        return False

    if game == "POKÉMON" and any(
        marker in name
        for marker in (
            "checklane",
            "check lane",
            "battle deck",
            "battledeck",
            "premium ex box mega zygarde",
            "mega zygarde ex premium collection",
        )
    ):
        return False

    if game == "LORCANA" and any(
        marker in name
        for marker in ("starter deck", "starterdeck", "starter decks")
    ):
        return False

    return True


def filter_restock_alert_products(products, game_override=None):
    return {
        key: product
        for key, product in (products or {}).items()
        if restock_alert_allowed(product, game_override)
    }


# ============================================================
# PRICE WATCH - PRODUKTTYPER
# ============================================================

def get_price_watch_type(name, game):
    text = (name or "").lower()

    if not is_english_card_product(text):
        return None

    if is_low_signal_accessory_name(text):
        return None

    # Produkter der aldrig må komme med i Price Watch.
    blocked = (
        "akryl",
        "acryl",
        "acrylic",
        "protector",
        "display case",
        "opbevaring",
        "storage",
        "binder",
        "portfolio",
        "sleeves",
        "deck box",
        "toploader",
        "lodtrækning",
        "lottery",
        "reward",
        "one piece",
        "magic the gathering",
        "magic: the gathering",
        "yu-gi-oh",
        "yugioh"
    )

    if any(word in text for word in blocked):
        return None

    # Større produkter der blot INDEHOLDER en booster box
    # må ikke sammenlignes med en almindelig booster box.
    if (
        "with booster box" in text
        or "med booster box" in text
    ):
        return None

    # Cases / multi-displays are wholesale-style products and must not be
    # compared with one normal retail booster box.
    if (
        "booster box case" in text
        or "booster case" in text
        or "case of booster" in text
        or re.search(r"\b(?:4|6|8|10|12)\s*[x×]\s*36\b", text)
    ):
        return None

    # Pokémon ETB
    if game == "POKÉMON":
        if (
            "elite trainer box" in text
            or re.search(r"\betb\b", text)
        ):
            return "ETB"

    # Booster Bundle Display er ikke samme produkt
    # som én almindelig Booster Bundle.
    
    # Displays med flere Booster Bundles tæller ikke som én bundle.
    if (
        "booster bundle display" in text
        or "bundle display" in text
    ):
        return None

    # Booster Box / Booster Display
    if (
        "booster box" in text
        or "booster display" in text
    ):
        return "BOOSTER BOX"

    # Booster Bundle
    if "booster bundle" in text:
        return "BOOSTER BUNDLE"

    # Sleeved Booster holdes separat fra løs booster.
    if "sleeved booster" in text:
        return "SLEEVED BOOSTER"

    # Booster Pack
    if "booster pack" in text:
        return "BOOSTER PACK"

    # Nogle butikker kalder enkeltpakker blot "Booster".
    if (
        "booster" in text
        and "box" not in text
        and "bundle" not in text
        and "display" not in text
    ):
        return "BOOSTER PACK"

    return None

def get_price_watch_language(name):
    text = (name or "").lower()

    japanese_markers = (
        "japansk",
        "japanese",
        "japan import",
    )

    if any(marker in text for marker in japanese_markers):
        return "JP"

    return "EN"


def normalize_price_watch_set_name(name, game, product_type):
    text = (name or "").lower()

    # Ensret tegn.
    text = (
        text
        .replace("’", "'")
        .replace("–", " ")
        .replace("—", " ")
        .replace("&", " and ")
    )

    # Apostroffer skal ikke skabe forskellige produktnøgler.
    # Ursula's Return = Ursulas Return.
    text = text.replace("'", "")

    # Fjern webshop-produktkoder som POK10407-101.
    text = re.sub(
        r"\b(?:pok|dis|lor)[a-z0-9-]*\d[a-z0-9-]*\b",
        " ",
        text
    )

    # Fjern setkoder som ME04, SV08 osv.
    text = re.sub(
        r"\b(?:me|sv)\d+(?:\.\d+)?[a-z]?\b",
        " ",
        text
    )

    # Fjern japanske produkt/setkoder som M5 og M2A.
    # Sproget er allerede gemt separat som JP.
    text = re.sub(
        r"\bm\d+[a-z]?\b",
        " ",
        text
    )

    # Fjern normale antal-pakker.
    # Vi bruger kun realistiske pack-counts, så Pokémon 151 bevares.
    text = re.sub(
        r"\(?\b(?:6|10|18|20|24|30|36)\s*"
        r"(?:engelsk\s+)?"
        r"(?:booster\s*)?"
        r"(?:packs?|boosters?|boostere|pakker)\b\)?",
        " ",
        text
    )

    # Længste produktfraser først.
    noise_phrases = (
        "pokemon trading card game",
        "pokémon trading card game",
        "disney lorcana tcg",
        "disney lorcana",
        "pokemon tcg",
        "pokémon tcg",
        "lorcana tcg",
        "booster bundle display",
        "booster display box",
        "booster box display",
        "elite trainer box",
        "booster bundle",
        "booster display",
        "booster box",
        "sleeved booster",
        "booster pack",
        "pokemon kort",
        "pokémon kort",
        "sealed set",
        "sealed",
        "engelsk",
        "english",
        "japansk",
        "japanese",
        "pokemon",
        "pokémon",
        "lorcana",
        "booster",
        "tcg",
    )

    for phrase in noise_phrases:
        text = text.replace(
            phrase,
            " "
        )

    # Fjern Lorcana "Set 2", "Set 3" osv.
    text = re.sub(
        r"\bset\s+\d+\b",
        " ",
        text
    )

    # Ryd øvrige tegn væk.
    text = re.sub(
        r"[^a-z0-9æøå ]+",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    # Fjern serie-æra når selve sætnavnet følger efter.
    era_prefixes = (
        "scarlet and violet",
        "mega evolution",
    )

    for prefix in era_prefixes:
        if text.startswith(prefix + " "):
            text = text[len(prefix):].strip()

    return text


def get_price_watch_product_key(product):
    game = product.get("game", "")
    product_type = product.get("type", "")
    name = product.get("name", "")

    language = get_price_watch_language(
        name
    )

    set_name = normalize_price_watch_set_name(
        name,
        game,
        product_type
    )

    if not set_name:
        return None

    return (
        f"{game}|"
        f"{product_type}|"
        f"{language}|"
        f"{set_name}"
    )

def get_price_watch_availability(source_key, product):
    # Proshop
    if source_key == "proshop":
        stock = product.get("stock")

        if stock in ("PÅ LAGER", "FJERNLAGER"):
            return stock

        return None

    # BR
    if source_key == "br":
        if product.get("online_stock"):
            return "ONLINE"

        if safe_int(product.get("kolding_stock")) > 0:
            return "KOLDING"

        if safe_int(product.get("esbjerg_stock")) > 0:
            return "ESBJERG"

        return None

    # Bilka and Føtex expose numeric local stock.
    if source_key in ("bilka", "foetex"):
        if product.get("online_stock"):
            return "ONLINE"

        local_stocks = product.get("local_stocks") or {}

        for store in local_stocks.values():
            if safe_int(store.get("stock")) > 0:
                return store.get("name") or "LOKALT"

        return None

    # Elgiganten exposes local availability as in_stock/display instead of a
    # numeric stock field.
    if source_key == "elgiganten":
        if product.get("online_stock"):
            return "ONLINE"

        local_stocks = product.get("local_stocks") or {}

        for store in local_stocks.values():
            if store.get("in_stock"):
                return store.get("name") or "LOKALT"

        return None

    # Coolshop
    if source_key == "coolshop":
        if product.get("online_stock"):
            return "PÅ LAGER"

        return None

    # Shopify, WooCommerce, Epic Panda,
    # Steffen-O og Next Level Games
    # Preorders tæller ikke som aktuel bedste pris.
    if product.get("preorder"):
        return None

    if product.get("in_stock"):
        return "PÅ LAGER"

    return None


def collect_price_watch_candidates(
    current_state,
    fresh_sources=None
):
    candidates = []

    def add_products(
        shop,
        source_key,
        products,
        game_override=None
    ):
        if (
            fresh_sources is not None
            and source_key not in fresh_sources
        ):
            return

        for product_key, product in (products or {}).items():
            name = product.get("name", "")
            game = game_override or product.get("game")

            if game not in ("POKÉMON", "LORCANA"):
                continue

            product_type = get_price_watch_type(
                name,
                game
            )

            if not product_type:
                continue

            price = product.get("price")

            try:
                price_value = float(price)
            except (TypeError, ValueError):
                continue

            if price_value <= 0:
                continue

            max_price = PRICE_WATCH_MAX_PRICE.get(product_type)
            if max_price is not None and price_value > max_price:
                continue

            availability = get_price_watch_availability(
                source_key,
                product
            )

            if not availability:
                continue

            url = product.get("url", "")

            # Coolshop gemmer URL'en som dictionary-key.
            if (
                not url
                and isinstance(product_key, str)
                and product_key.startswith(("http://", "https://"))
            ):
                url = product_key

            candidates.append({
                "shop": shop,
                "source": source_key,
                "game": game,
                "type": product_type,
                "name": name,
                "price": price_value,
                "availability": availability,
                "url": url
            })

    add_products(
        "COOLSHOP",
        "coolshop",
        current_state.get("coolshop", {})
    )

    add_products(
        "PROSHOP",
        "proshop",
        current_state.get("proshop", {}),
        "POKÉMON"
    )

    add_products(
        "BR",
        "br",
        current_state.get("br", {}),
        "POKÉMON"
    )

    add_products(
        "BILKA",
        "bilka",
        current_state.get("bilka", {}),
        "POKÉMON"
    )

    add_products(
        "FØTEX",
        "foetex",
        current_state.get("foetex", {}),
        "POKÉMON"
    )

    shopify_state = current_state.get("shopify", {})

    for site_key, site in SHOPIFY_SITES.items():
        add_products(
            site["label"],
            site_key,
            shopify_state.get(site_key, {})
        )

    woocommerce_state = current_state.get("woocommerce", {})

    for site_key, site in WOOCOMMERCE_SITES.items():
        add_products(
            site["label"],
            site_key,
            woocommerce_state.get(site_key, {})
        )

    add_products(
        "EPIC PANDA",
        "epicpanda",
        current_state.get("epicpanda", {})
    )

    add_products(
        "STEFFEN-O",
        "steffeno",
        current_state.get("steffeno", {}),
        "POKÉMON"
    )

    add_products(
        "NEXT LEVEL GAMES",
        "nextlevel",
        current_state.get("nextlevel", {})
    )

    return candidates


# =========================================================
# PRICE WATCH V4 - SOURCE-CONFIRMED ANTI-FLAP
# =========================================================

def _price_watch_raw_products_for_source(current_state, source_key):
    if source_key in {
        "coolshop", "proshop", "br", "bilka", "foetex",
        "epicpanda", "steffeno", "nextlevel"
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
    pokemon_only = {"proshop", "br", "bilka", "foetex", "steffeno"}

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


# =========================================================
# PRICE WATCH V4
# =========================================================

PRICE_WATCH_TYPE_ORDER = (
    "ETB",
    "BOOSTER BOX",
    "BOOSTER BUNDLE",
    "SLEEVED BOOSTER",
    "BOOSTER PACK",
)

PRICE_WATCH_DAILY_MAX_SIGNALS_PER_GAME = 3
PRICE_WATCH_DAILY_MIN_SAVING_DKK = 25.0
PRICE_WATCH_DAILY_MIN_SAVING_PCT = 5.0
PRICE_HISTORY_DAILY_MAX_SIGNALS_TOTAL = 3
PRICE_HISTORY_NEW_LOW_MIN_DKK = 25.0
PRICE_HISTORY_NEW_LOW_MIN_PCT = 5.0

# User-defined retail relevance ceilings. Products above these prices remain
# in raw restock state, but are excluded from Price Watch + Price History.
PRICE_WATCH_MAX_PRICE = {
    "BOOSTER PACK": 150.0,
    "SLEEVED BOOSTER": 175.0,
    "BOOSTER BUNDLE": 750.0,
    "ETB": 1500.0,
    "BOOSTER BOX": 1750.0,
}


def build_price_watch_groups(candidates):
    raw_groups = {}

    for product in candidates:
        product_key = get_price_watch_product_key(
            product
        )

        if not product_key:
            continue

        raw_groups.setdefault(
            product_key,
            []
        ).append(product)

    comparable_groups = {}

    for product_key, products in raw_groups.items():
        # Samme shop kan i sjældne tilfælde have flere listings.
        # Brug kun den billigste listing fra hver shop.
        cheapest_by_shop = {}

        for product in products:
            shop = product["shop"]
            current = cheapest_by_shop.get(shop)

            if (
                current is None
                or product["price"] < current["price"]
            ):
                cheapest_by_shop[shop] = product

        if len(cheapest_by_shop) < 2:
            continue

        comparable_groups[product_key] = sorted(
            cheapest_by_shop.values(),
            key=lambda product: (
                product["price"],
                product["shop"]
            )
        )

    return comparable_groups


def parse_price_watch_key(product_key):
    parts = product_key.split(
        "|",
        3
    )

    if len(parts) != 4:
        return {
            "game": "",
            "type": "",
            "language": "",
            "set_name": product_key
        }

    return {
        "game": parts[0],
        "type": parts[1],
        "language": parts[2],
        "set_name": parts[3]
    }


def price_watch_display_name(product_key):
    info = parse_price_watch_key(
        product_key
    )

    set_name = info["set_name"].strip()

    if set_name:
        display = " ".join(
            word.upper()
            if word in {"x", "y"}
            else word.capitalize()
            for word in set_name.split()
        )
    else:
        display = "Ukendt produkt"

    if info["language"] == "JP":
        display += " (Japansk)"

    return display


def price_watch_game_label(game):
    if game == "POKÉMON":
        return "Pokémon"

    if game == "LORCANA":
        return "Lorcana"

    return game


def price_watch_type_label(product_type):
    labels = {
        "ETB": "ETB",
        "BOOSTER BOX": "Booster Boxes",
        "BOOSTER BUNDLE": "Booster Bundles",
        "SLEEVED BOOSTER": "Sleeved Boosters",
        "BOOSTER PACK": "Booster Packs",
    }

    return labels.get(
        product_type,
        product_type.title()
    )


def price_watch_best_entry(products):
    return min(
        products,
        key=lambda product: (
            product["price"],
            product["shop"]
        )
    )


def price_watch_lowest_shops(products):
    if not products:
        return []

    best_price = min(
        product["price"]
        for product in products
    )

    return sorted(
        {
            product["shop"]
            for product in products
            if abs(product["price"] - best_price) < 0.005
        }
    )


def send_price_watch_change(
    product_key,
    old_entry,
    products
):
    best = price_watch_best_entry(
        products
    )

    info = parse_price_watch_key(
        product_key
    )

    try:
        old_price = float(
            old_entry.get("current_best")
        )
    except (TypeError, ValueError):
        return

    new_price = float(
        best["price"]
    )

    # Price Watch er handlingsorienteret. Prisopgang og butiksskift ved
    # samme pris gemmes i historikken, men er ikke Discord-alerts.
    price_drop = old_price - new_price
    price_drop_pct = price_drop / old_price if old_price > 0 else 0.0
    if (
        price_drop < PRICE_ALERT_MIN_IMPROVEMENT_DKK
        or price_drop_pct < PRICE_ALERT_MIN_IMPROVEMENT_PCT
    ):
        return

    headline = "🔥 **BEDRE PRIS FUNDET**"

    top = products[:3]
    ranking_lines = []

    for index, product in enumerate(
        top,
        start=1
    ):
        medal = {
            1: "🥇",
            2: "🥈",
            3: "🥉"
        }.get(index, "•")

        ranking_lines.append(
            f"{medal} {product['shop']} — "
            f"**{format_price(product['price'])}**"
        )

    change_line = (
        f"{format_price(old_price)} → "
        f"**{format_price(new_price)}** "
        f"(-{price_drop_pct * 100.0:.0f}%)"
    )

    language_line = (
        "\n🌐 Japansk"
        if info["language"] == "JP"
        else ""
    )

    link_line = (
        f"\n🔗 {best['url']}"
        if best.get("url")
        else ""
    )

    send_price_watch(
        f"{headline}\n"
        f"**{price_watch_game_label(info['game'])} · "
        f"{price_watch_display_name(product_key)} · "
        f"{price_watch_type_label(info['type'])}**"
        f"{language_line}\n"
        f"{change_line}\n\n"
        + "\n".join(ranking_lines)
        + link_line
    )


def split_discord_message(message, limit=1900):
    if len(message) <= limit:
        return [message]

    chunks = []
    current = ""

    for line in message.splitlines():
        candidate = (
            line
            if not current
            else current + "\n" + line
        )

        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)

        current = line

    if current:
        chunks.append(current)

    return chunks


def send_price_watch_daily_summary(
    comparable_groups,
    now_local
):
    if not comparable_groups:
        print(
            "PRICE WATCH: ingen sammenlignelige produkter "
            "til dagens oversigt."
        )
        return False

    signals_by_game = {"POKÉMON": [], "LORCANA": []}

    for product_key, products in comparable_groups.items():
        info = parse_price_watch_key(product_key)
        game = info["game"]
        if game not in signals_by_game:
            continue

        ordered = sorted(
            products,
            key=lambda product: (product["price"], product["shop"])
        )
        best = ordered[0]
        best_price = float(best["price"])
        next_prices = [
            float(product["price"])
            for product in ordered
            if float(product["price"]) > best_price + 0.005
        ]

        # Samme pris hos alle butikker er ikke et beslutningssignal.
        if not next_prices:
            continue

        next_price = min(next_prices)
        saving_dkk = next_price - best_price
        saving_pct = (
            saving_dkk / next_price * 100.0
            if next_price > 0
            else 0.0
        )

        if (
            saving_dkk < PRICE_WATCH_DAILY_MIN_SAVING_DKK
            or saving_pct < PRICE_WATCH_DAILY_MIN_SAVING_PCT
        ):
            continue

        signals_by_game[game].append({
            "product_key": product_key,
            "best": best,
            "shops": price_watch_lowest_shops(products),
            "next_price": next_price,
            "saving_dkk": saving_dkk,
            "saving_pct": saving_pct,
        })

    lines = [
        "🎯 **DAGENS KØBSOVERSIGT**",
        (
            f"*{now_local.strftime('%d.%m.%Y')} · kun tydelige prisfordele "
            "på varer hos mindst 2 butikker*"
        ),
    ]
    signal_count = 0

    for game in ("POKÉMON", "LORCANA"):
        signals = sorted(
            signals_by_game[game],
            key=lambda row: (row["saving_pct"], row["saving_dkk"]),
            reverse=True,
        )[:PRICE_WATCH_DAILY_MAX_SIGNALS_PER_GAME]

        lines.append("")
        lines.append(f"**{price_watch_game_label(game)}**")

        if not signals:
            lines.append("• Ingen tydelige prisfordele i dag")
            continue

        for index, signal in enumerate(signals, start=1):
            info = parse_price_watch_key(signal["product_key"])
            shops = " + ".join(signal["shops"])
            lines.append(
                f"{index}. **{price_watch_display_name(signal['product_key'])} · "
                f"{price_watch_type_label(info['type'])}** — "
                f"{format_price(signal['best']['price'])} hos {shops} · "
                f"næste {format_price(signal['next_price'])} · "
                f"spar **{signal['saving_pct']:.0f}%**"
            )
            signal_count += 1

    lines.append("")
    lines.append(
        "*Fuld prisliste og historik ligger i Price History-filen.*"
    )

    sent = send_price_watch("\n".join(lines))
    print(f"PRICE WATCH: daglig oversigt med {signal_count} købssignaler")
    return bool(sent)


def process_price_watch(
    old_price_watch_state,
    current_state,
    fresh_sources
):
    candidates = collect_price_watch_candidates(
        current_state,
        fresh_sources=fresh_sources
    )

    comparable_groups = build_price_watch_groups(
        candidates
    )

    source_observations = build_price_watch_source_observations(
        current_state,
        fresh_sources
    )

    print(
        f"PRICE WATCH V4: "
        f"{len(candidates)} friske prislinjer | "
        f"{len(comparable_groups)} produkter hos mindst 2 butikker | "
        f"{len(fresh_sources)} friske kilder"
    )

    previous = (
        old_price_watch_state
        if isinstance(old_price_watch_state, dict)
        else {}
    )

    previous_version = safe_int(
        previous.get("version"),
        0
    )

    previous_products = previous.get("products")
    is_first_price_watch_run = not isinstance(previous_products, dict)

    if not isinstance(previous_products, dict):
        previous_products = {}

    try:
        now_local = datetime.now(ZoneInfo(PRICE_WATCH_TIMEZONE))
    except Exception:
        now_local = datetime.now(ZoneInfo("Europe/Copenhagen"))

    today = now_local.date().isoformat()
    last_daily_date = str(previous.get("last_daily_date", "") or "")

    daily_due = (
        bool(PRICE_WATCH_WEBHOOK_URL)
        and now_local.hour >= PRICE_WATCH_DAILY_HOUR
        and last_daily_date != today
    )

    daily_sent = False

    if daily_due:
        daily_sent = send_price_watch_daily_summary(
            comparable_groups,
            now_local
        )

        if daily_sent:
            last_daily_date = today

    # V4: Negative ændringer kræver både eksplicit kildebevis og to
    # ens scans. En vare, der blot mangler fra et frisk kategori-feed,
    # må aldrig løfte den registrerede bedste pris.
    changes_enabled = (
        bool(PRICE_WATCH_WEBHOOK_URL)
        and last_daily_date == today
        and not daily_sent
        and not is_first_price_watch_run
        and previous_version >= 4
    )

    next_products = dict(previous_products)

    def confirmed_entry(product_key, best, current_best, current_shops, current_sources):
        return {
            "current_best": current_best,
            "current_shop": best["shop"],
            "current_shops": current_shops,
            "current_sources": current_sources,
            "name": price_watch_display_name(product_key),
            "last_seen": now_local.isoformat()
        }

    for product_key, products in comparable_groups.items():
        best = price_watch_best_entry(products)
        current_best = float(best["price"])
        current_shops = price_watch_lowest_shops(products)
        current_sources = sorted({
            product["source"]
            for product in products
            if abs(product["price"] - current_best) < 0.005
        })

        old_entry = previous_products.get(product_key)

        if not isinstance(old_entry, dict):
            next_products[product_key] = confirmed_entry(
                product_key,
                best,
                current_best,
                current_shops,
                current_sources
            )
            continue

        try:
            old_price = float(old_entry.get("current_best"))
        except (TypeError, ValueError):
            old_price = None

        old_shops = old_entry.get("current_shops")
        if not isinstance(old_shops, list):
            old_shop = old_entry.get("current_shop")
            old_shops = [old_shop] if old_shop else []

        old_sources = old_entry.get("current_sources")
        if not isinstance(old_sources, list):
            old_sources = []

        price_is_lower = (
            old_price is not None
            and current_best < old_price - 0.005
        )
        price_is_higher = (
            old_price is not None
            and current_best > old_price + 0.005
        )
        cheapest_shop_changed = (
            old_price is not None
            and abs(current_best - old_price) < 0.005
            and bool(old_shops)
            and not set(old_shops).intersection(current_shops)
        )

        # En reel lavere pris er positiv information fra en frisk kilde
        # og kan derfor bekræftes med det samme.
        if price_is_lower:
            if changes_enabled:
                send_price_watch_change(product_key, old_entry, products)

            next_products[product_key] = confirmed_entry(
                product_key,
                best,
                current_best,
                current_shops,
                current_sources
            )
            continue

        # Pris op / billigste butik væk er negativ information. Før vi
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
                f"{current_best:.2f}|"
                + ",".join(sorted(current_shops))
            )
            pending = old_entry.get("pending_change")

            if (
                isinstance(pending, dict)
                and pending.get("signature") == signature
            ):
                pending_count = safe_int(pending.get("count"), 0) + 1
            else:
                pending_count = 1

            if pending_count >= 2:
                if changes_enabled:
                    send_price_watch_change(product_key, old_entry, products)

                next_products[product_key] = confirmed_entry(
                    product_key,
                    best,
                    current_best,
                    current_shops,
                    current_sources
                )
            else:
                kept = dict(old_entry)
                kept["pending_change"] = {
                    "signature": signature,
                    "count": pending_count,
                    "observed_best": current_best,
                    "observed_shops": current_shops,
                    "observed_sources": current_sources,
                    "first_seen": now_local.isoformat()
                }
                kept["last_seen"] = now_local.isoformat()
                next_products[product_key] = kept

            continue

        # Stabilt scan: opdater metadata og nulstil evt. pending flap.
        next_products[product_key] = confirmed_entry(
            product_key,
            best,
            current_best,
            current_shops,
            current_sources
        )

    if is_first_price_watch_run:
        print("PRICE WATCH V4 baseline oprettet uden ændringsalerts.")
    elif previous_version < 4:
        print("PRICE WATCH V4 source-confirmed anti-flap aktiveret uden overgangsalerts.")

    return {
        "version": 4,
        "products": next_products,
        "last_daily_date": last_daily_date
    }


# =========================================================
# PRICE HISTORY V1
# =========================================================

def build_price_history_groups(candidates):
    """Price history tracks every comparable sealed product, even with one shop."""
    raw_groups = {}

    for product in candidates:
        product_key = get_price_watch_product_key(product)
        if not product_key:
            continue
        raw_groups.setdefault(product_key, []).append(product)

    groups = {}

    for product_key, products in raw_groups.items():
        cheapest_by_shop = {}

        for product in products:
            shop = product["shop"]
            current = cheapest_by_shop.get(shop)
            if current is None or product["price"] < current["price"]:
                cheapest_by_shop[shop] = product

        if cheapest_by_shop:
            groups[product_key] = sorted(
                cheapest_by_shop.values(),
                key=lambda product: (product["price"], product["shop"])
            )

    return groups


def _history_short_type(product_type):
    return {
        "ETB": "ETB",
        "BOOSTER BOX": "Box",
        "BOOSTER BUNDLE": "Bundle",
        "SLEEVED BOOSTER": "Sleeved",
        "BOOSTER PACK": "Pack",
    }.get(product_type, product_type.title())


def _history_product_label(product_key):
    info = parse_price_watch_key(product_key)
    return (
        f"{price_watch_display_name(product_key)} "
        f"[{_history_short_type(info['type'])}]"
    )


def _history_pct(current_price, historical_low):
    try:
        current_price = float(current_price)
        historical_low = float(historical_low)
    except (TypeError, ValueError):
        return None

    if historical_low <= 0:
        return None

    return ((current_price / historical_low) - 1.0) * 100.0


def _history_pct_text(value):
    if value is None:
        return "-"
    if abs(value) < 0.05:
        return "0,0%"
    return (f"+{value:.1f}%").replace(".", ",")


def _history_money_short(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "-"

    if abs(value - round(value)) < 0.005:
        return f"{int(round(value))}"

    return f"{value:.2f}".replace(".", ",")


def _history_cell(value, width):
    value = str(value or "-")
    if len(value) > width:
        value = value[: max(1, width - 1)] + "…"
    return value.ljust(width)


def _history_table(entries, include_cardmarket=False):
    if include_cardmarket:
        header = (
            f"{'Produkt':25} {'Lavest':7} {'Butik':11} "
            f"{'Nu':7} {'Diff':7} {'CM €':7}"
        )
        divider = "-" * len(header)
    else:
        header = (
            f"{'Produkt':27} {'Lavest':7} {'Butik':12} "
            f"{'Nu':7} {'Diff':7}"
        )
        divider = "-" * len(header)

    lines = [header, divider]

    for entry in entries:
        diff = _history_pct(
            entry.get("current_best"),
            entry.get("historical_low")
        )

        low_shops = entry.get("historical_low_shops") or []
        low_shop = " + ".join(low_shops) if low_shops else "-"

        if include_cardmarket:
            cardmarket = entry.get("cardmarket") or {}
            cm_price = cardmarket.get("eur")
            line = (
                _history_cell(entry.get("label"), 25)
                + " " + _history_cell(_history_money_short(entry.get("historical_low")), 7)
                + " " + _history_cell(low_shop, 11)
                + " " + _history_cell(_history_money_short(entry.get("current_best")), 7)
                + " " + _history_cell(_history_pct_text(diff), 7)
                + " " + _history_cell(_history_money_short(cm_price), 7)
            )
        else:
            line = (
                _history_cell(entry.get("label"), 27)
                + " " + _history_cell(_history_money_short(entry.get("historical_low")), 7)
                + " " + _history_cell(low_shop, 12)
                + " " + _history_cell(_history_money_short(entry.get("current_best")), 7)
                + " " + _history_cell(_history_pct_text(diff), 7)
            )

        lines.append(line.rstrip())

    return "```text\n" + "\n".join(lines) + "\n```"


# =========================================================
# CARDMARKET - OPTIONAL DAILY REFERENCE
# =========================================================

def cardmarket_enabled():
    return bool(
        OAuth1 is not None
        and CARDMARKET_APP_TOKEN
        and CARDMARKET_APP_SECRET
    )


def _cardmarket_auth(url):
    kwargs = {
        "client_key": CARDMARKET_APP_TOKEN,
        "client_secret": CARDMARKET_APP_SECRET,
        "signature_method": "HMAC-SHA1",
        "signature_type": "AUTH_HEADER",
        "realm": url,
    }

    if CARDMARKET_ACCESS_TOKEN and CARDMARKET_ACCESS_SECRET:
        kwargs["resource_owner_key"] = CARDMARKET_ACCESS_TOKEN
        kwargs["resource_owner_secret"] = CARDMARKET_ACCESS_SECRET

    return OAuth1(**kwargs)


def _cardmarket_get(path, params=None):
    url = CARDMARKET_BASE + path
    last_error = None

    for attempt in range(2):
        response = requests.get(
            url,
            params=params or {},
            auth=_cardmarket_auth(url),
            headers={
                "Accept": "application/json",
                "User-Agent": "Pokemon-Lorcana-MasterBot/1.4",
            },
            timeout=30,
        )

        if response.status_code == 429:
            last_error = RuntimeError("Cardmarket 429 Too Many Requests")
            time.sleep(2.0 + attempt * 3.0)
            continue

        response.raise_for_status()
        # Cardmarket marketplace calls are intentionally serialized.
        time.sleep(0.4)
        return response.json()

    raise last_error or RuntimeError("Cardmarket request failed")


def _cardmarket_game_id(game):
    cached = CARDMARKET_GAME_IDS.get(game)
    if cached:
        return cached

    payload = _cardmarket_get("/games")
    games = payload.get("game") or payload.get("games") or []
    if isinstance(games, dict):
        games = [games]

    wanted = "pokemon" if game == "POKÉMON" else "lorcana"

    for row in games:
        name = str(
            row.get("name")
            or row.get("gameName")
            or ""
        ).lower().replace("é", "e")

        if wanted in name:
            game_id = safe_int(row.get("idGame"), 0)
            if game_id:
                CARDMARKET_GAME_IDS[game] = game_id
                return game_id

    return None


def _cardmarket_search_name(product_key):
    info = parse_price_watch_key(product_key)
    set_name = price_watch_display_name(product_key).replace(" (Japansk)", "")
    suffix = {
        "ETB": "Elite Trainer Box",
        "BOOSTER BOX": "Booster Box",
        "BOOSTER BUNDLE": "Booster Bundle",
        "SLEEVED BOOSTER": "Sleeved Booster",
        "BOOSTER PACK": "Booster Pack",
    }.get(info["type"], "")
    return f"{set_name} {suffix}".strip()


def _cardmarket_name_score(product_key, candidate_name):
    desired = re.sub(
        r"[^a-z0-9 ]+",
        " ",
        _cardmarket_search_name(product_key).lower()
    )
    candidate = re.sub(
        r"[^a-z0-9 ]+",
        " ",
        str(candidate_name or "").lower()
    )

    desired_tokens = {
        token for token in desired.split()
        if token not in {"pokemon", "pokémon", "tcg", "disney", "lorcana"}
    }
    candidate_tokens = set(candidate.split())

    if not desired_tokens:
        return 0.0

    overlap = len(desired_tokens.intersection(candidate_tokens)) / len(desired_tokens)

    info = parse_price_watch_key(product_key)
    type_checks = {
        "ETB": ("elite", "trainer", "box"),
        "BOOSTER BOX": ("booster", "box"),
        "BOOSTER BUNDLE": ("booster", "bundle"),
        "SLEEVED BOOSTER": ("sleeved", "booster"),
        "BOOSTER PACK": ("booster",),
    }.get(info["type"], ())

    if type_checks and not all(token in candidate_tokens for token in type_checks):
        overlap -= 0.35

    return overlap


def _cardmarket_find_product(product_key, previous_cardmarket=None):
    previous_cardmarket = previous_cardmarket or {}
    previous_id = safe_int(previous_cardmarket.get("product_id"), 0)
    if previous_id:
        return {
            "idProduct": previous_id,
            "name": previous_cardmarket.get("product_name") or "",
        }

    info = parse_price_watch_key(product_key)
    game_id = _cardmarket_game_id(info["game"])
    if not game_id:
        return None

    payload = _cardmarket_get(
        "/products/find",
        params={
            "search": _cardmarket_search_name(product_key),
            "exact": "false",
            "idGame": game_id,
            "idLanguage": 1,
            "start": 0,
            "maxResults": 20,
        },
    )

    products = payload.get("product") or payload.get("products") or []
    if isinstance(products, dict):
        products = [products]

    scored = sorted(
        (
            (_cardmarket_name_score(product_key, row.get("name")), row)
            for row in products
        ),
        key=lambda item: item[0],
        reverse=True,
    )

    if not scored or scored[0][0] < 0.55:
        return None

    return scored[0][1]


def _cardmarket_floor(product_key, previous_cardmarket=None):
    product = _cardmarket_find_product(product_key, previous_cardmarket)
    if not product:
        return None

    product_id = safe_int(product.get("idProduct"), 0)
    if not product_id:
        return None

    # IMPORTANT: this tracker follows sealed products. Cardmarket's
    # minCondition=MT filter is singles-only, so it is deliberately NOT sent
    # for sealed products. English is enforced; seller quality is filtered
    # locally using seller.sellCount, and UK/Switzerland are excluded locally.
    payload = _cardmarket_get(
        f"/articles/{product_id}",
        params={
            "idLanguage": 1,
            "start": 0,
            "maxResults": 100,
        },
    )

    articles = payload.get("article") or payload.get("articles") or []
    if isinstance(articles, dict):
        articles = [articles]

    qualified = []

    for article in articles:
        language = article.get("language") or {}
        if safe_int(language.get("idLanguage"), 0) != 1:
            continue

        seller = article.get("seller") or {}
        if safe_int(seller.get("sellCount"), 0) < CARDMARKET_MIN_SELLS:
            continue

        address = seller.get("address") or {}
        country = str(address.get("country") or "").upper()
        if country in CARDMARKET_EXCLUDED_COUNTRIES:
            continue

        if seller.get("onVacation") is True:
            continue

        try:
            price = float(article.get("price"))
        except (TypeError, ValueError):
            continue

        if price <= 0:
            continue

        qualified.append((price, article, seller, country))

    if not qualified:
        return {
            "product_id": product_id,
            "product_name": product.get("name") or "",
            "checked_at": datetime.now(ZoneInfo(PRICE_WATCH_TIMEZONE)).isoformat(),
            "qualified_offers": 0,
        }

    price, article, seller, country = min(
        qualified,
        key=lambda row: row[0]
    )

    return {
        "eur": price,
        "seller": seller.get("username") or "",
        "country": country,
        "sales": safe_int(seller.get("sellCount"), 0),
        "product_id": product_id,
        "product_name": product.get("name") or "",
        "checked_at": datetime.now(ZoneInfo(PRICE_WATCH_TIMEZONE)).isoformat(),
        "qualified_offers": len(qualified),
        "shipping_included": False,
    }


def _price_history_row_line(entry):
    diff = _history_pct(
        entry.get("current_best"),
        entry.get("historical_low")
    )
    low_shops = entry.get("historical_low_shops") or []
    low_shop = " + ".join(low_shops) if low_shops else "-"
    current_shops = entry.get("current_shops") or []
    current_shop = " + ".join(current_shops) if current_shops else entry.get("current_shop") or "-"

    return (
        f"**{entry.get('label') or 'Ukendt produkt'}**\n"
        f"Lavest **{format_price(entry.get('historical_low'))}** · {low_shop}  |  "
        f"Nu **{format_price(entry.get('current_best'))}** · {current_shop}  |  "
        f"**{_history_pct_text(diff)}**"
    )


def _price_history_category_embeds(game, entries):
    order = {value: index for index, value in enumerate(PRICE_WATCH_TYPE_ORDER)}
    grouped = {}

    for entry in entries:
        info = parse_price_watch_key(entry["product_key"])
        grouped.setdefault(info["type"], []).append(entry)

    embeds = []

    for product_type in sorted(grouped, key=lambda value: order.get(value, 99)):
        category_entries = sorted(
            grouped[product_type],
            key=lambda entry: entry["label"].lower()
        )

        chunks = []
        current = []
        current_len = 0

        for entry in category_entries:
            block = _price_history_row_line(entry)
            block_len = len(block) + 2

            if current and current_len + block_len > 3700:
                chunks.append(current)
                current = []
                current_len = 0

            current.append(block)
            current_len += block_len

        if current:
            chunks.append(current)

        for index, chunk in enumerate(chunks, start=1):
            suffix = (
                f" · {index}/{len(chunks)}"
                if len(chunks) > 1
                else ""
            )
            embeds.append({
                "title": (
                    f"{price_watch_game_label(game)} · "
                    f"{price_watch_type_label(product_type)}"
                    f" ({len(category_entries)}){suffix}"
                )[:256],
                "description": "\n\n".join(chunk)[:4096],
                "color": 0x5865F2 if game == "POKÉMON" else 0x9B59B6,
                "footer": {
                    "text": "Lavest = dansk rekord siden tracking start · Diff = nu vs. rekord"
                },
            })

    return embeds


def _send_price_history_embed_batches(embeds):
    if not PRICE_HISTORY_WEBHOOK_URL or not embeds:
        return False

    # Discord tillader højst 10 embeds og 6.000 samlede embed-tegn pr.
    # webhook-besked. Den gamle kode begrænsede kun antallet og kunne
    # derfor få HTTP 400, når kataloget voksede.
    def embed_text_length(embed):
        total = len(str(embed.get("title") or ""))
        total += len(str(embed.get("description") or ""))

        footer = embed.get("footer")
        if isinstance(footer, dict):
            total += len(str(footer.get("text") or ""))

        author = embed.get("author")
        if isinstance(author, dict):
            total += len(str(author.get("name") or ""))

        for field in embed.get("fields") or []:
            if not isinstance(field, dict):
                continue
            total += len(str(field.get("name") or ""))
            total += len(str(field.get("value") or ""))

        return total

    batches = []
    current_batch = []
    current_chars = 0

    for embed in embeds:
        embed_chars = embed_text_length(embed)

        if current_batch and (
            len(current_batch) >= 10
            or current_chars + embed_chars > 5500
        ):
            batches.append(current_batch)
            current_batch = []
            current_chars = 0

        current_batch.append(embed)
        current_chars += embed_chars

    if current_batch:
        batches.append(current_batch)

    sent = False

    for batch in batches:
        response = requests.post(
            PRICE_HISTORY_WEBHOOK_URL,
            json={
                "username": "MasterBot",
                "allowed_mentions": {"parse": []},
                "embeds": batch,
            },
            headers={
                "User-Agent": "Pokemon-Lorcana-MasterBot/1.4.1"
            },
            timeout=20,
        )
        response.raise_for_status()
        sent = True

    return sent


def _send_price_history_csv(products, active_keys, now_local):
    if not PRICE_HISTORY_WEBHOOK_URL:
        return False

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "Game",
        "Kategori",
        "Produkt",
        "Historisk laveste DKK",
        "Laveste butik",
        "Laveste dato",
        "Nuværende pris DKK",
        "Nuværende butik",
        "Difference %",
        "Produkt URL",
    ])

    rows = []

    for product_key in active_keys:
        entry = products.get(product_key)
        if not isinstance(entry, dict):
            continue

        info = parse_price_watch_key(product_key)
        diff = _history_pct(
            entry.get("current_best"),
            entry.get("historical_low")
        )
        low_shops = " + ".join(entry.get("historical_low_shops") or [])
        current_shops = " + ".join(entry.get("current_shops") or [])

        rows.append((
            info["game"],
            price_watch_type_label(info["type"]),
            price_watch_display_name(product_key),
            entry.get("historical_low"),
            low_shops,
            entry.get("historical_low_date") or "",
            entry.get("current_best"),
            current_shops or entry.get("current_shop") or "",
            None if diff is None else round(diff, 1),
            entry.get("current_url") or "",
        ))

    rows.sort(key=lambda row: (row[0], row[1], row[2].lower()))

    for row in rows:
        writer.writerow(row)

    filename = f"price_history_{now_local.strftime('%Y-%m-%d')}.csv"
    payload = {
        "username": "MasterBot",
        "content": (
            "📎 **Fuld Price History** · Excel/CSV · "
            f"{len(rows)} aktive produkter"
        ),
        "allowed_mentions": {"parse": []},
    }

    response = requests.post(
        PRICE_HISTORY_WEBHOOK_URL,
        data={"payload_json": json.dumps(payload, ensure_ascii=False)},
        files={
            "files[0]": (
                filename,
                output.getvalue().encode("utf-8-sig"),
                "text/csv",
            )
        },
        headers={
            "User-Agent": "Pokemon-Lorcana-MasterBot/1.4.1"
        },
        timeout=30,
    )
    response.raise_for_status()
    return True


def _price_history_daily_summary(products, active_keys, now_local, started_at):
    if not PRICE_HISTORY_WEBHOOK_URL:
        return False

    signals_by_game = {
        "POKÉMON": {"buy": [], "wait": []},
        "LORCANA": {"buy": [], "wait": []},
    }
    today = now_local.date().isoformat()

    for product_key in active_keys:
        entry = products.get(product_key)
        if not isinstance(entry, dict):
            continue

        info = parse_price_watch_key(product_key)
        game = info["game"]
        if game not in signals_by_game:
            continue

        # En baseline er ikke en prisbevægelse. Vi viser først et signal,
        # når produktet er observeret på mindst to dage og prisen faktisk
        # har ændret sig siden tracking start.
        if safe_int(entry.get("observation_days"), 0) < 2:
            continue
        if safe_int(entry.get("price_changes"), 0) < 1:
            continue

        last_change_date = str(entry.get("last_change_date") or "")[:10]
        last_signal_date = str(entry.get("last_daily_signal_date") or "")[:10]
        if not last_change_date or last_signal_date >= last_change_date:
            continue

        try:
            previous_best = float(entry.get("previous_best"))
            current_best = float(entry.get("current_best"))
            movement_dkk = abs(current_best - previous_best)
        except (TypeError, ValueError):
            movement_dkk = 0.0

        movement_pct = abs(float(entry.get("last_change_pct") or 0.0))
        if (
            movement_dkk < PRICE_ALERT_MIN_IMPROVEMENT_DKK
            or movement_pct < PRICE_ALERT_MIN_IMPROVEMENT_PCT * 100.0
        ):
            # Preserve the exact movement in history, but mark this change as
            # handled so it cannot keep resurfacing in future daily digests.
            entry["last_daily_signal_date"] = today
            continue

        diff = _history_pct(
            entry.get("current_best"),
            entry.get("historical_low")
        )
        if diff is None:
            continue

        row = {
            "product_key": product_key,
            "entry": entry,
            "diff": diff,
            "last_change_pct": float(entry.get("last_change_pct") or 0.0),
        }

        if diff <= 3.0:
            signals_by_game[game]["buy"].append(row)
        elif diff >= 10.0:
            signals_by_game[game]["wait"].append(row)

    selected_by_game = {
        "POKÉMON": {"buy": [], "wait": []},
        "LORCANA": {"buy": [], "wait": []},
    }
    selected_rows = []
    handled_rows = []
    candidate_rows = []

    for game in ("POKÉMON", "LORCANA"):
        for row in signals_by_game[game]["buy"]:
            handled_rows.append(row)
            candidate = dict(row)
            candidate["signal_kind"] = "buy"
            candidate_rows.append(candidate)

        for row in signals_by_game[game]["wait"]:
            handled_rows.append(row)
            candidate = dict(row)
            candidate["signal_kind"] = "wait"
            candidate_rows.append(candidate)

    def signal_priority(row):
        # Buy signals win ties; within each class show the strongest signal.
        if row["signal_kind"] == "buy":
            return (
                0,
                row["diff"],
                row["last_change_pct"],
                price_watch_display_name(row["product_key"]).lower(),
            )

        return (
            1,
            -row["diff"],
            -abs(row["last_change_pct"]),
            price_watch_display_name(row["product_key"]).lower(),
        )

    selected_rows = sorted(
        candidate_rows,
        key=signal_priority,
    )[:PRICE_HISTORY_DAILY_MAX_SIGNALS_TOTAL]

    for row in selected_rows:
        game = parse_price_watch_key(row["product_key"])["game"]
        if game not in selected_by_game:
            continue
        selected_by_game[game][row["signal_kind"]].append(row)

    lines = [
        (
            f"*{now_local.strftime('%d.%m.%Y')} · kun nye, dokumenterede "
            "prisbevægelser*"
        )
    ]

    for game in ("POKÉMON", "LORCANA"):
        game_signals = selected_by_game[game]
        lines.append("")
        lines.append(f"**{price_watch_game_label(game)}**")

        if not game_signals["buy"] and not game_signals["wait"]:
            lines.append("• Ingen nye signaler i dag")
            continue

        if game_signals["buy"]:
            lines.append("🟢 **SLÅ TIL**")
            for row in game_signals["buy"]:
                entry = row["entry"]
                shops = " + ".join(entry.get("current_shops") or [])
                shops = shops or entry.get("current_shop") or "ukendt butik"
                change = row["last_change_pct"]
                change_text = (
                    f" · seneste ændring {change:+.0f}%"
                    if abs(change) >= 0.5
                    else ""
                )
                lines.append(
                    f"• **{_history_product_label(row['product_key'])}** — "
                    f"{format_price(entry.get('current_best'))} hos {shops} · "
                    f"{row['diff']:.0f}% over historisk low{change_text}"
                )

        if game_signals["wait"]:
            lines.append("🟠 **AFVENT**")
            for row in game_signals["wait"]:
                entry = row["entry"]
                lines.append(
                    f"• **{_history_product_label(row['product_key'])}** — "
                    f"{format_price(entry.get('current_best'))} · "
                    f"{row['diff']:.0f}% over historisk low"
                )

    if not selected_rows:
        lines.append("")
        lines.append(
            "✅ Ingen nye købssignaler eller tydelige afvent-priser i dag."
        )

    embed = {
        "title": "🎯 PRISUDVIKLING & KØBSSIGNALER",
        "description": "\n".join(lines)[:4096],
        "color": 0x2ECC71 if selected_rows else 0x95A5A6,
        "footer": {
            "text": (
                "Slå til = højst 3% over historisk low · "
                "Afvent = mindst 10% over historisk low"
            )
        },
    }

    sent_any = _send_price_history_embed_batches([embed])

    if sent_any:
        # Også de signaler, der lå under dagens topgrænse, markeres som
        # behandlet. Ellers kan et stort katalog skabe en flerugers kø af
        # gamle signaler i Discord.
        for row in handled_rows:
            row["entry"]["last_daily_signal_date"] = today

    # Den fulde statistik bevares, men Discord får kun CSV én gang om
    # ugen (søndag) i stedet for hver dag.
    if now_local.weekday() == 6:
        if _send_price_history_csv(products, active_keys, now_local):
            sent_any = True

    return sent_any


def process_price_history(old_history_state, current_state, fresh_sources):
    candidates = collect_price_watch_candidates(
        current_state,
        fresh_sources=fresh_sources
    )
    groups = build_price_history_groups(candidates)

    previous = old_history_state if isinstance(old_history_state, dict) else {}
    previous_products = previous.get("products")
    if not isinstance(previous_products, dict):
        previous_products = {}

    try:
        now_local = datetime.now(ZoneInfo(PRICE_WATCH_TIMEZONE))
    except Exception:
        now_local = datetime.now(ZoneInfo("Europe/Copenhagen"))

    today = now_local.date().isoformat()
    started_at = str(previous.get("started_at") or now_local.isoformat())
    last_daily_date = str(previous.get("last_daily_date") or "")
    last_daily_attempt_date = str(
        previous.get("last_daily_attempt_date") or ""
    )
    first_run = not bool(previous_products)
    next_products = dict(previous_products)
    active_keys = set(groups.keys())

    daily_due = (
        bool(PRICE_HISTORY_WEBHOOK_URL)
        and now_local.hour >= PRICE_HISTORY_DAILY_HOUR
        and last_daily_date != today
        and last_daily_attempt_date != today
    )

    new_lows = []

    for product_key, products in groups.items():
        best = price_watch_best_entry(products)
        current_best = float(best["price"])
        current_shops = price_watch_lowest_shops(products)
        old_entry = previous_products.get(product_key)

        if not isinstance(old_entry, dict):
            entry = {
                "name": price_watch_display_name(product_key),
                "current_best": current_best,
                "current_shops": current_shops,
                "current_shop": best["shop"],
                "current_url": best.get("url") or "",
                "historical_low": current_best,
                "historical_low_shops": current_shops,
                "historical_low_date": today,
                "historical_low_url": best.get("url") or "",
                "first_seen": now_local.isoformat(),
                "last_seen": now_local.isoformat(),
                "baseline_price": current_best,
                "observation_days": 1,
                "last_observation_date": today,
                "price_changes": 0,
            }
        else:
            entry = dict(old_entry)

            try:
                old_current = float(entry.get("current_best"))
            except (TypeError, ValueError):
                old_current = current_best

            observation_days = safe_int(entry.get("observation_days"), 0)
            if observation_days < 1:
                first_seen_date = str(entry.get("first_seen") or "")[:10]
                observation_days = 2 if first_seen_date and first_seen_date < today else 1

            if str(entry.get("last_observation_date") or "")[:10] != today:
                observation_days += 1

            entry.setdefault(
                "baseline_price",
                entry.get("historical_low", old_current)
            )
            entry.setdefault("price_changes", 0)
            entry["observation_days"] = observation_days
            entry["last_observation_date"] = today

            if abs(current_best - old_current) > 0.005:
                entry["previous_best"] = old_current
                entry["last_change_pct"] = _history_pct(
                    current_best,
                    old_current,
                )
                entry["last_change_date"] = today
                entry["price_changes"] = safe_int(
                    entry.get("price_changes"), 0
                ) + 1

            entry.update({
                "name": price_watch_display_name(product_key),
                "current_best": current_best,
                "current_shops": current_shops,
                "current_shop": best["shop"],
                "current_url": best.get("url") or "",
                "last_seen": now_local.isoformat(),
            })

            try:
                old_low = float(entry.get("historical_low"))
            except (TypeError, ValueError):
                old_low = current_best

            if current_best < old_low - 0.005:
                entry["historical_low"] = current_best
                entry["historical_low_shops"] = current_shops
                entry["historical_low_date"] = today
                entry["historical_low_url"] = best.get("url") or ""
                new_lows.append((product_key, old_low, entry, best))

        next_products[product_key] = entry

    # Cardmarket is an optional once-daily reference. It is never mixed into
    # the Danish historical low because Cardmarket prices exclude shipping.
    if daily_due and cardmarket_enabled():
        print("PRICE HISTORY: opdaterer Cardmarket-reference ...")
        for product_key in sorted(active_keys):
            entry = next_products.get(product_key)
            if not isinstance(entry, dict):
                continue

            existing = entry.get("cardmarket")
            checked_date = ""
            if isinstance(existing, dict):
                checked_date = str(existing.get("checked_at") or "")[:10]

            if checked_date == today:
                continue

            try:
                cardmarket = _cardmarket_floor(product_key, existing)
                if cardmarket:
                    entry["cardmarket"] = cardmarket
            except Exception as error:
                print(
                    f"Cardmarket fejl for {_history_product_label(product_key)}: {error}"
                )

    # Individual historical-low alerts are intentionally suppressed.
    # New lows stay in state and remain eligible for the next compact daily
    # Price History digest (max 3 total signals).

    if daily_due:
        last_daily_attempt_date = today

        if first_run:
            pokemon_count = sum(
                1 for key in active_keys
                if parse_price_watch_key(key)["game"] == "POKÉMON"
            )
            lorcana_count = sum(
                1 for key in active_keys
                if parse_price_watch_key(key)["game"] == "LORCANA"
            )

            send_price_history_embed(
                "📊 PRICE HISTORY AKTIVERET",
                (
                    f"Baseline gemt for **{len(active_keys)} aktive produkter**.\n\n"
                    f"⚡ Pokémon: **{pokemon_count}**\n"
                    f"✨ Lorcana: **{lorcana_count}**\n\n"
                    "Fra nu registreres nye historiske lavpunkter. "
                    "En kort signaloversigt sendes én gang dagligt."
                ),
                color=0x5865F2,
                footer=f"Historik startet {started_at[:10]}",
            )
            _send_price_history_csv(
                next_products,
                active_keys,
                now_local,
            )
            last_daily_date = today
        elif _price_history_daily_summary(
            next_products,
            active_keys,
            now_local,
            started_at,
        ):
            last_daily_date = today

    print(
        f"PRICE HISTORY V1: {len(active_keys)} aktive produkter | "
        f"{len(new_lows)} nye historiske lows"
    )

    return {
        "version": 1,
        "started_at": started_at,
        "last_daily_date": last_daily_date,
        "last_daily_attempt_date": last_daily_attempt_date,
        "products": next_products,
    }


# =========================================================
# COOLSHOP FETCH
# =========================================================

def get_coolshop_feed(feed):
    products = {}

    offset = 0
    size = 20

    while True:
        payload = {
            "path": feed["path"],
            "add_facets": {},
            "remove_facets": {},
            "sort": feed["sort"],
            "size": size,
            "offset": offset
        }

        response = requests.post(
            COOLSHOP_API,
            headers={
                **BROWSER_HEADERS,
                "Content-Type": "application/json",
                "Referer": (
                    COOLSHOP_BASE
                    + "/"
                    + feed["path"]
                )
            },
            json=payload,
            timeout=20
        )

        response.raise_for_status()

        data = response.json()

        total = data.get("count", 0)

        if offset >= total:
            break

        soup = BeautifulSoup(
            data.get("results", ""),
            "html.parser"
        )

        cards = soup.select(
            ".product__card"
        )

        for card in cards:
            image = card.find("img")
            link = card.find(
                "a",
                href=True
            )

            if not image or not link:
                continue

            name = image.get(
                "alt",
                ""
            ).strip()

            if not name:
                continue

            if feed["filter"]:
                if (
                    feed["filter"].lower()
                    not in name.lower()
                ):
                    continue

            url = urljoin(
                COOLSHOP_BASE,
                link["href"]
            )

            text = card.get_text(
                " ",
                strip=True
            )

            price = parse_price(text)

            online_stock = (
                "På lager" in text
                or "Kun få på lager" in text
            )

            products[url] = {
                "name": name,
                "game": feed["game"],
                "price": price,
                "online_stock": online_stock
            }

        offset += size

    return products


def get_coolshop_products():
    all_products = {}

    for feed in COOLSHOP_FEEDS:
        products = get_coolshop_feed(
            feed
        )

        all_products.update(
            products
        )

    return all_products


# =========================================================
# PROSHOP
# =========================================================

def clean_proshop_name(href):
    parts = href.rstrip("/").split("/")

    if len(parts) < 2:
        return "Ukendt produkt"

    slug = parts[-2]

    slug = unquote(slug)
    slug = slug.replace("-", " ")

    slug = re.sub(
        r"\s+",
        " ",
        slug
    ).strip()

    return slug


def _parse_proshop_products(response):
    soup = BeautifulSoup(response.text, "html.parser")
    products = {}

    # Product card class names change regularly. Anchor the parser on the
    # stable public product URL and only use the surrounding card for price
    # and stock text.
    link_pattern = re.compile(
        r"/Pokemon/[^?#]+/\d+(?:[?#].*)?$",
        re.IGNORECASE,
    )
    links = soup.find_all("a", href=link_pattern)

    for link in links:
        href = link.get("href") or ""
        match = re.search(r"/(\d+)(?:[?#].*)?$", href)
        if not match:
            continue

        product_id = match.group(1)

        # Find the smallest useful ancestor containing stock/price text.
        # The previous implementation referenced an undefined `card` variable,
        # forcing an otherwise healthy direct response into the Jina fallback.
        card = None
        for parent in link.parents:
            if parent is soup:
                break
            parent_text = parent.get_text(" ", strip=True)
            low_parent = parent_text.lower()
            if (
                "kr" in low_parent
                or "på lager" in low_parent
                or "fjernlager" in low_parent
                or "bestillingsvare" in low_parent
            ):
                card = parent
                break

        if card is None:
            card = link.parent or link

        text_card = card.get_text(" ", strip=True)
        name = clean_proshop_name(href)

        # /Pokemon is a broad fallback with figures, games etc. Keep only
        # trading-card-related rows when that route is used.
        # Classify from the product title/link label, not the full
        # description. Legitimate sealed collections often mention sleeves,
        # playmats or deck boxes in their included contents.
        tcg_text = name + " " + link.get_text(" ", strip=True)
        if not _proshop_is_tcg_text(tcg_text):
            continue

        price = parse_price(text_card)

        if "På lager" in text_card:
            stock = "PÅ LAGER"
        elif "Fjernlager" in text_card:
            stock = "FJERNLAGER"
        elif "Bestillingsvare" in text_card or "Bestilt" in text_card:
            stock = "BESTILLINGSVARE"
        else:
            stock = "UKENDT"

        products[product_id] = {
            "name": name,
            "price": price,
            "stock": stock,
            "url": urljoin(PROSHOP_BASE, href),
        }

    return products


PROSHOP_READER_URL = "https://r.jina.ai/" + PROSHOP_URL


def _proshop_is_tcg_text(value):
    """Keep real sealed/playable Pokemon TCG products, not accessories."""
    low = " " + re.sub(r"\s+", " ", (value or "").lower()) + " "

    # These are genuine sealed products even when their names contain words
    # that can also describe accessories.
    sealed_allow = (
        "booster pack", "booster packs", "booster box", "booster display",
        "booster bundle", "sleeved booster", "elite trainer box", " etb ",
        "blister", "poké ball tin", "poke ball tin", "mini tin", " tin ",
        "binder collection", "playmat collection",
        "accessory pouch special collection",
        "premium collection", "illustration collection", "collection box",
        "ultra-premium collection", "ultra premium collection",
        "league battle deck", "deluxe battle deck", "ex battle deck",
        "battle deck", "world championships deck", "championship deck",
        "trainer toolkit", "battle academy", "build & battle", "build and battle",
    )
    if any(marker in low for marker in sealed_allow):
        return True

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

    # Some Proshop titles are simply named "Collection".
    return " collection " in low


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

        if not _proshop_is_tcg_text(name + " " + label):
            continue

        price_match = re.search(
            r"(?<!\d)(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d+(?:,\d{2})?)\s*kr\.?",
            segment,
            flags=re.IGNORECASE,
        )
        price = None

        if price_match:
            raw_price = price_match.group(1).replace(".", "").replace(",", ".")

            try:
                price = float(raw_price)
            except ValueError:
                price = None

        # Keep real products without a current price. Proshop uses this for
        # unavailable preorders, which must remain in state for later restock.
        if price is not None and price <= 0:
            price = None

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
            "User-Agent": "Pokemon-Lorcana-MasterBot/2.5 ProshopPrimary",
            "x-no-cache": "true",
            "x-engine": "browser",
        },
        timeout=50,
    )
    response.raise_for_status()

    raw_link_pattern = re.compile(
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

    # A page with many raw links but zero parsed products is a parser failure,
    # not a valid empty shop snapshot.
    if not products:
        raise RuntimeError(
            f"Jina Reader parser extracted 0 products from "
            f"{raw_product_links} raw product links"
        )

    print(
        f"PROSHOP: bruger Jina Reader primary "
        f"({len(products)} relevante TCG-produkter; "
        f"{priced} med pris; {raw_product_links} rå produktlinks)"
    )
    return products


def get_proshop_products():
    errors = []

    # GitHub-hosted requests are consistently blocked with HTTP 403, while
    # Jina/browser rendering exposes the public category reliably. Treat it
    # as the production transport instead of pretending it is an emergency
    # fallback.
    try:
        products = get_proshop_products_via_reader()
        if products:
            return products
        errors.append("Jina Reader: 0 produkter")
    except Exception as error:
        errors.append(f"Jina Reader: {error}")

    # Safety fallback only: if Reader is temporarily unavailable, try the two
    # public Proshop routes once each. No retry storm.
    headers = {
        **BROWSER_HEADERS,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "da-DK,da;q=0.9,en-US;q=0.7,en;q=0.6",
        "Referer": PROSHOP_BASE + "/",
        "Upgrade-Insecure-Requests": "1",
    }
    urls = [
        (PROSHOP_URL, "pokemon-kort"),
        (PROSHOP_BASE + "/Pokemon", "Pokemon fallback"),
    ]

    if curl_requests is not None:
        try:
            session = curl_requests.Session(impersonate="chrome")
            for url, label in urls:
                try:
                    response = session.get(url, headers=headers, timeout=25)
                except Exception as error:
                    errors.append(f"{label}: {error}")
                    continue
                if response.status_code != 200:
                    errors.append(f"{label}: HTTP {response.status_code}")
                    continue
                products = _parse_proshop_products(response)
                if products:
                    print(
                        f"PROSHOP: Reader utilgængelig; direct fallback {label} "
                        f"gav {len(products)} TCG-produkter"
                    )
                    return products
                errors.append(f"{label}: 200 men ingen TCG-produkter parsed")
        except Exception as error:
            errors.append(f"curl_cffi: {error}")

    short = "; ".join(errors[-5:]) if errors else "ukendt fejl"
    raise RuntimeError(f"Proshop utilgængelig ({short})")


# =========================================================
# BR FRONTEND CONFIG
# =========================================================

def extract_br_config_value(text, key):
    pattern = (
        re.escape(key)
        + r'["\']?\s*:\s*["\']([^"\']+)["\']'
    )

    match = re.search(pattern, text)

    if match:
        return match.group(1)

    return None


def get_br_frontend_config(force=False):
    global BR_CONFIG_CACHE

    if BR_CONFIG_CACHE is not None and not force:
        return BR_CONFIG_CACHE

    response = requests.get(
        BR_HOME,
        headers=BROWSER_HEADERS,
        timeout=20
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    script_urls = []

    for script in soup.find_all("script", src=True):
        script_urls.append(
            urljoin(
                BR_BASE,
                script["src"]
            )
        )

    # app.js først, fordi BR's offentlige NUXT_ENV-værdier ligger der.
    script_urls = list(dict.fromkeys(script_urls))
    script_urls.sort(
        key=lambda url: (
            0 if "app.js" in url.lower() else 1,
            0 if "commons.app.js" in url.lower() else 1,
            len(url)
        )
    )

    texts_to_check = [response.text]

    # Begræns antallet af scripts vi downloader.
    for script_url in script_urls[:25]:
        try:
            script_response = requests.get(
                script_url,
                headers=BROWSER_HEADERS,
                timeout=20
            )

            script_response.raise_for_status()
            texts_to_check.append(script_response.text)

            if (
                "NUXT_ENV_API_TOKEN" in script_response.text
                and "NUXT_ENV_ALGOLIA_API_KEY" in script_response.text
            ):
                break

        except requests.RequestException:
            continue

    api_token = None
    algolia_api_key = None
    algolia_app_id = None

    for text in texts_to_check:
        api_token = (
            api_token
            or extract_br_config_value(
                text,
                "NUXT_ENV_API_TOKEN"
            )
        )

        algolia_api_key = (
            algolia_api_key
            or extract_br_config_value(
                text,
                "NUXT_ENV_ALGOLIA_API_KEY"
            )
        )

        algolia_app_id = (
            algolia_app_id
            or extract_br_config_value(
                text,
                "NUXT_ENV_ALGOLIA_APLICATION_ID"
            )
            or extract_br_config_value(
                text,
                "NUXT_ENV_ALGOLIA_APPLICATION_ID"
            )
        )

        if api_token and algolia_api_key and algolia_app_id:
            break

    if not api_token:
        raise RuntimeError(
            "Kunne ikke finde BR API-token i den offentlige frontend."
        )

    if not algolia_api_key or not algolia_app_id:
        raise RuntimeError(
            "Kunne ikke finde BR Algolia-konfiguration."
        )

    BR_CONFIG_CACHE = {
        "api_token": api_token,
        "algolia_api_key": algolia_api_key,
        "algolia_app_id": algolia_app_id
    }

    return BR_CONFIG_CACHE


# =========================================================
# BR PRODUKTFILTER
# =========================================================

def get_br_facet_values(product, facet_name):
    values = []

    for facet_group in product.get("facets") or []:
        if facet_name not in facet_group:
            continue

        facet_values = facet_group.get(facet_name) or []

        if isinstance(facet_values, list):
            values.extend(facet_values)
        else:
            values.append(facet_values)

    return values


def is_real_pokemon_tcg(product):
    supplier = (
        product.get("supplier_information")
        or {}
    )

    manufacturer = (
        supplier.get("manufacturer_name")
        or ""
    ).lower()

    if (
        "pokemon" not in manufacturer
        and "pokémon" not in manufacturer
    ):
        return False

    merchandise_types = get_br_facet_values(
        product,
        "typeOfFanMerchandise"
    )

    blocked_types = {
        "Samlemappe",
        "Kortlommer"
    }

    if any(
        value in blocked_types
        for value in merchandise_types
    ):
        return False

    return True


# =========================================================
# BR LOKALT LAGER - KOLDING + ESBJERG
# =========================================================

def get_br_local_stocks(sku, session):
    config = get_br_frontend_config()

    url = (
        f"{BR_API_BASE}/clickcollect/availability/{sku}"
    )

    headers = {
        **BROWSER_HEADERS,
        "Accept": "application/json, text/plain, */*",
        "Authorization": (
            f"Bearer {config['api_token']}"
        ),
        "Origin": BR_BASE,
        "Referer": BR_HOME
    }

    response = session.get(
        url,
        headers=headers,
        timeout=20
    )

    # Hvis BR har skiftet frontend-token, hent ny config og prøv én gang.
    if response.status_code == 401:
        config = get_br_frontend_config(
            force=True
        )

        headers["Authorization"] = (
            f"Bearer {config['api_token']}"
        )

        response = session.get(
            url,
            headers=headers,
            timeout=20
        )

    response.raise_for_status()

    stocks = {
        "kolding_stock": 0,
        "esbjerg_stock": 0
    }

    for item in response.json():
        store = item.get("store") or {}
        site_id = str(store.get("sapSiteId") or "")
        stock = max(
            0,
            safe_int(
                item.get("currentStock"),
                0
            )
        )

        if site_id == BR_KOLDING_SITE_ID:
            stocks["kolding_stock"] = stock

        elif site_id == BR_ESBJERG_SITE_ID:
            stocks["esbjerg_stock"] = stock

    return stocks


# =========================================================
# BR FETCH
# =========================================================

def get_br_products(old_products=None):
    if old_products is None:
        old_products = {}

    config = get_br_frontend_config()

    algolia_url = (
        "https://"
        f"{config['algolia_app_id'].lower()}"
        "-dsn.algolia.net/1/indexes/*/queries"
    )

    params = {
        "query": "",
        "attributesToRetrieve": '["*"]',
        "filters": (
            'is_exposed:true AND '
            'cfh_nodes:"CFH.CollectionCards" AND '
            'f_brand:"Pokemon" OR '
            'f_brand:"Pokémon" OR '
            'facets.productSeriesToys:"Pokémon"'
        ),
        "distinct": "true",
        "facetingAfterDistinct": "false",
        "page": 0,
        "hitsPerPage": 60,
        "facets": (
            '["price_filter",'
            '"f_stock_availability",'
            '"brand",'
            '"f_category",'
            '"f_campaign_name",'
            '"facets.childrenToys.ageList"]'
        ),
        "getRankingInfo": "true"
    }

    payload = {
        "requests": [
            {
                "indexName": BR_ALGOLIA_INDEX,
                "params": urlencode(params)
            }
        ],
        "strategy": "none"
    }

    response = requests.post(
        algolia_url,
        headers={
            **BROWSER_HEADERS,
            "Content-Type": "application/json",
            "x-algolia-application-id": config["algolia_app_id"],
            "x-algolia-api-key": config["algolia_api_key"]
        },
        json=payload,
        timeout=20
    )

    response.raise_for_status()

    data = response.json()
    all_hits = data["results"][0].get("hits", [])

    hits = [
        product
        for product in all_hits
        if is_real_pokemon_tcg(product)
    ]

    products = {}
    session = requests.Session()

    for product in hits:
        product_id = str(
            product.get("id")
            or product.get("objectID")
            or ""
        )

        if not product_id:
            continue

        name = product.get(
            "name",
            "Ukendt produkt"
        )

        price = product.get(
            "sales_price"
        )

        try:
            if price is not None:
                price = float(price)
        except (TypeError, ValueError):
            price = None

        online_count = max(
            0,
            safe_int(
                product.get("stock_count_online"),
                0
            )
        )

        store_count = max(
            0,
            safe_int(
                product.get("in_stock_stores_count"),
                0
            )
        )

        sku = (
            product.get("sku")
            or product.get("erp_product_id")
        )

        product_url = product.get(
            "product_url"
        )

        url = (
            urljoin(BR_BASE, product_url)
            if product_url
            else BR_HOME
        )

        quantity_limit = product.get(
            "quantity_restriction"
        )

        # Hvis ingen BR-butik har lager, er begge lokale butikker sikkert 0.
        if store_count <= 0:
            local_stocks = {
                "kolding_stock": 0,
                "esbjerg_stock": 0
            }

        elif sku:
            try:
                local_stocks = get_br_local_stocks(
                    sku,
                    session
                )

            except Exception as error:
                print(
                    f"BR lokal lagerfejl for {product_id}: {error}"
                )

                old_product = old_products.get(
                    product_id,
                    {}
                )

                local_stocks = {
                    "kolding_stock": old_product.get("kolding_stock"),
                    "esbjerg_stock": old_product.get("esbjerg_stock")
                }

        else:
            local_stocks = {
                "kolding_stock": None,
                "esbjerg_stock": None
            }

        products[product_id] = {
            "name": name,
            "price": price,
            "online_count": online_count,
            "online_stock": online_count > 0,
            "store_count": store_count,
            "kolding_stock": local_stocks.get("kolding_stock"),
            "esbjerg_stock": local_stocks.get("esbjerg_stock"),
            "quantity_limit": quantity_limit,
            "sku": sku,
            "url": url
        }

    return products


# =========================================================
# BILKA + FOETEX FRONTEND CONFIG
# =========================================================

def extract_salling_config_value(text, key):
    pattern = (
        re.escape(key)
        + r'["\']?\s*:\s*["\']([^"\']+)["\']'
    )

    match = re.search(pattern, text)

    if match:
        return match.group(1)

    return None


def get_salling_frontend_config(site_key, force=False):
    site = SALLING_SITES[site_key]

    if site_key in SALLING_CONFIG_CACHE and not force:
        return SALLING_CONFIG_CACHE[site_key]

    response = requests.get(
        site["home"],
        headers=BROWSER_HEADERS,
        timeout=20
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    script_urls = []

    for script in soup.find_all("script", src=True):
        script_urls.append(
            urljoin(
                site["base"],
                script["src"]
            )
        )

    script_urls = list(dict.fromkeys(script_urls))
    script_urls.sort(
        key=lambda url: (
            0 if "app.js" in url.lower() else 1,
            0 if "commons.app.js" in url.lower() else 1,
            len(url)
        )
    )

    texts_to_check = [response.text]

    for script_url in script_urls[:30]:
        try:
            script_response = requests.get(
                script_url,
                headers=BROWSER_HEADERS,
                timeout=20
            )

            script_response.raise_for_status()
            texts_to_check.append(script_response.text)

            if (
                "NUXT_ENV_API_TOKEN" in script_response.text
                and "NUXT_ENV_ALGOLIA_DEFAULT_INDEX" in script_response.text
            ):
                break

        except requests.RequestException:
            continue

    keys = {
        "api_token": "NUXT_ENV_API_TOKEN",
        "api_url": "NUXT_ENV_API_URL",
        "algolia_api_key": "NUXT_ENV_ALGOLIA_API_KEY",
        "algolia_app_id": "NUXT_ENV_ALGOLIA_APLICATION_ID",
        "algolia_index": "NUXT_ENV_ALGOLIA_DEFAULT_INDEX"
    }

    config = {
        key: None
        for key in keys
    }

    for source_text in texts_to_check:
        for out_key, source_key in keys.items():
            if not config[out_key]:
                config[out_key] = extract_salling_config_value(
                    source_text,
                    source_key
                )

        if not config["algolia_app_id"]:
            config["algolia_app_id"] = extract_salling_config_value(
                source_text,
                "NUXT_ENV_ALGOLIA_APPLICATION_ID"
            )

    missing = [
        key
        for key in (
            "api_token",
            "api_url",
            "algolia_api_key",
            "algolia_app_id",
            "algolia_index"
        )
        if not config[key]
    ]

    if missing:
        raise RuntimeError(
            f"{site['label']} mangler frontend-config: "
            + ", ".join(missing)
        )

    SALLING_CONFIG_CACHE[site_key] = config

    return config


# =========================================================
# BILKA + FOETEX LOKALT LAGER - KOLDING + ESBJERG
# =========================================================

def get_salling_local_stocks(
    site_key,
    sku,
    session,
    config
):
    site = SALLING_SITES[site_key]

    url = (
        f"{config['api_url']}"
        f"/clickcollect/availability/{sku}"
    )

    headers = {
        **BROWSER_HEADERS,
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {config['api_token']}",
        "Origin": site["base"],
        "Referer": site["home"]
    }

    response = session.get(
        url,
        headers=headers,
        timeout=20
    )

    # Hent frisk offentlig frontend-config ved token-skift.
    if response.status_code == 401:
        config = get_salling_frontend_config(
            site_key,
            force=True
        )

        headers["Authorization"] = (
            f"Bearer {config['api_token']}"
        )

        response = session.get(
            f"{config['api_url']}"
            f"/clickcollect/availability/{sku}",
            headers=headers,
            timeout=20
        )

    response.raise_for_status()

    local_stocks = {
        site_id: {
            "name": store_name,
            "stock": 0
        }
        for site_id, store_name
        in site["local_stores"].items()
    }

    for item in response.json():
        store = item.get("store") or {}
        site_id = str(store.get("sapSiteId") or "")

        if site_id not in local_stocks:
            continue

        local_stocks[site_id] = {
            "name": (
                store.get("name")
                or site["local_stores"][site_id]
            ),
            "stock": max(
                0,
                safe_int(
                    item.get("currentStock"),
                    0
                )
            )
        }

    return local_stocks


# =========================================================
# BILKA + FOETEX FETCH
# =========================================================

def get_salling_products(
    site_key,
    old_products=None
):
    if old_products is None:
        old_products = {}

    site = SALLING_SITES[site_key]
    config = get_salling_frontend_config(site_key)

    algolia_url = (
        "https://"
        f"{config['algolia_app_id'].lower()}"
        "-dsn.algolia.net/1/indexes/*/queries"
    )

    params = {
        "query": "",
        "attributesToRetrieve": '["*"]',
        "filters": (
            'is_exposed:true AND '
            'cfh_nodes:"CFH.CollectionCards" AND '
            'f_brand:"Pokemon" OR '
            'f_brand:"Pokémon" OR '
            'facets.productSeriesToys:"Pokémon"'
        ),
        "distinct": "true",
        "facetingAfterDistinct": "false",
        "page": 0,
        "hitsPerPage": 100,
        "facets": (
            '["price_filter",'
            '"f_stock_availability",'
            '"brand",'
            '"f_category",'
            '"f_campaign_name",'
            '"facets.childrenToys.ageList"]'
        ),
        "getRankingInfo": "true"
    }

    payload = {
        "requests": [
            {
                "indexName": config["algolia_index"],
                "params": urlencode(params)
            }
        ],
        "strategy": "none"
    }

    response = requests.post(
        algolia_url,
        headers={
            **BROWSER_HEADERS,
            "Content-Type": "application/json",
            "x-algolia-application-id": config["algolia_app_id"],
            "x-algolia-api-key": config["algolia_api_key"]
        },
        json=payload,
        timeout=20
    )

    response.raise_for_status()

    all_hits = response.json()["results"][0].get(
        "hits",
        []
    )

    hits = [
        product
        for product in all_hits
        if is_real_pokemon_tcg(product)
    ]

    products = {}
    session = requests.Session()

    for product in hits:
        product_id = str(
            product.get("id")
            or product.get("objectID")
            or ""
        )

        if not product_id:
            continue

        name = product.get(
            "name",
            "Ukendt produkt"
        )

        price = product.get("sales_price")

        try:
            if price is not None:
                price = float(price)
        except (TypeError, ValueError):
            price = None

        online_count = max(
            0,
            safe_int(
                product.get("stock_count_online"),
                0
            )
        )

        store_count = max(
            0,
            safe_int(
                product.get("in_stock_stores_count"),
                0
            )
        )

        sku = (
            product.get("sku")
            or product.get("erp_product_id")
        )

        product_url = product.get("product_url")

        url = (
            urljoin(site["base"], product_url)
            if product_url
            else site["home"]
        )

        quantity_limit = product.get(
            "quantity_restriction"
        )

        if store_count <= 0:
            local_stocks = {
                site_id: {
                    "name": store_name,
                    "stock": 0
                }
                for site_id, store_name
                in site["local_stores"].items()
            }

        elif sku:
            try:
                local_stocks = get_salling_local_stocks(
                    site_key,
                    sku,
                    session,
                    config
                )

            except Exception as error:
                print(
                    f"{site['label']} lokal lagerfejl "
                    f"for {product_id}: {error}"
                )

                old_product = old_products.get(
                    product_id,
                    {}
                )

                local_stocks = old_product.get(
                    "local_stocks"
                )

                if local_stocks is None:
                    local_stocks = {
                        site_id: {
                            "name": store_name,
                            "stock": None
                        }
                        for site_id, store_name
                        in site["local_stores"].items()
                    }

        else:
            local_stocks = {
                site_id: {
                    "name": store_name,
                    "stock": None
                }
                for site_id, store_name
                in site["local_stores"].items()
            }

        products[product_id] = {
            "name": name,
            "price": price,
            "online_count": online_count,
            "online_stock": online_count > 0,
            "store_count": store_count,
            "local_stocks": local_stocks,
            "quantity_limit": quantity_limit,
            "sku": sku,
            "url": url
        }

    return products


def count_salling_local_products(site_key, products):
    counts = {
        site_id: 0
        for site_id in SALLING_SITES[site_key]["local_stores"]
    }

    for product in products.values():
        local_stocks = product.get("local_stocks") or {}

        for site_id in counts:
            store_data = local_stocks.get(site_id) or {}
            stock = store_data.get("stock")

            if stock is not None and safe_int(stock, 0) > 0:
                counts[site_id] += 1

    return counts


# =========================================================
# ELGIGANTEN FETCH
# =========================================================

def get_elgiganten_key_valid_until(api_key):
    try:
        padded = api_key + "=" * (-len(api_key) % 4)
        decoded = base64.b64decode(padded).decode(
            "utf-8",
            errors="ignore"
        )
        decoded = unquote(decoded)
        match = re.search(r"validUntil=(\d+)", decoded)

        if match:
            return int(match.group(1))

    except Exception:
        pass

    return 0


def get_elgiganten_signed_key(force=False):
    cached_key = ELGIGANTEN_KEY_CACHE.get("api_key")
    retry_after_epoch = safe_int(
        ELGIGANTEN_KEY_CACHE.get("retry_after"),
        0,
    )

    # Let Algolia be the authority on whether the signed key still works.
    # This avoids refreshing a usable key simply because our decoded expiry
    # estimate is conservative.
    if cached_key and not force:
        return cached_key

    if not force and retry_after_epoch and time.time() < retry_after_epoch:
        remaining = max(1, int(retry_after_epoch - time.time()))
        raise RuntimeError(
            f"Elgiganten signed-key cooldown aktiv ({remaining}s tilbage)"
        )

    headers = {
        **BROWSER_HEADERS,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
        "Referer": ELGIGANTEN_CATEGORY_URL,
        "Origin": ELGIGANTEN_BASE,
    }

    if curl_requests is not None:
        session = curl_requests.Session(impersonate="chrome")
    else:
        session = requests.Session()

    # Warm the exact public category route first. Elgiganten documents an
    # algolia-refresh-nonce cookie used for secure search-key rotation; using
    # one browser session lets necessary cookies flow automatically.
    try:
        session.get(
            ELGIGANTEN_CATEGORY_URL,
            headers={
                **BROWSER_HEADERS,
                "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
            },
            timeout=25,
        )
    except Exception:
        pass

    response = session.get(
        ELGIGANTEN_SIGNED_KEY_URL,
        headers=headers,
        timeout=20,
    )

    if response.status_code == 429:
        retry_after = safe_int(response.headers.get("Retry-After"), 0)
        failures = (
            safe_int(ELGIGANTEN_KEY_CACHE.get("rate_limit_failures"), 0)
            + 1
        )

        # Persisted exponential backoff prevents each new five-minute GitHub
        # runner from hammering the same public key endpoint. An explicit
        # Retry-After header always wins.
        if retry_after > 0:
            cooldown = retry_after
        else:
            cooldown = min(12 * 60 * 60, 30 * 60 * (2 ** min(failures - 1, 4)))

        cooldown = max(300, min(cooldown, 12 * 60 * 60))
        ELGIGANTEN_KEY_CACHE["retry_after"] = int(time.time() + cooldown)
        ELGIGANTEN_KEY_CACHE["rate_limit_failures"] = failures
        print(
            f"ELGIGANTEN signed-key 429 - cooldown {cooldown}s "
            f"(rate-limit #{failures}); ingen immediate retries"
        )
        response.raise_for_status()

    response.raise_for_status()

    data = response.json()
    api_key = data.get("apiKey")
    if not api_key:
        raise RuntimeError("Elgiganten signed-api-key svarede uden apiKey.")

    ELGIGANTEN_KEY_CACHE["api_key"] = api_key
    ELGIGANTEN_KEY_CACHE["valid_until"] = get_elgiganten_key_valid_until(api_key)
    ELGIGANTEN_KEY_CACHE["retry_after"] = 0
    ELGIGANTEN_KEY_CACHE["rate_limit_failures"] = 0

    return api_key


def is_real_elgiganten_pokemon_tcg(product):
    title = (product.get("title") or "").lower()
    brand = (product.get("brand") or "").lower()

    if brand == "ultrapro":
        return False

    # Official sealed collections remain valid even when a binder/playmat is
    # part of the product.
    allowed_collections = (
        "binder collection",
        "playmat collection",
        "accessory pouch special collection",
    )
    if any(phrase in title for phrase in allowed_collections):
        return True

    blocked_words = (
        "binder",
        "mappe",
        "portfolio",
        "sleeve",
        "kortlommer",
    )

    return not any(word in title for word in blocked_words)


def get_elgiganten_store_stock(product, store_id, store_name):
    department_stock = product.get("departmentStock") or {}
    stock_data = department_stock.get(store_id) or {}

    return {
        "name": store_name,
        "in_stock": bool(stock_data.get("inStock", False)),
        "display": str(stock_data.get("display", "0"))
    }


ELGIGANTEN_LAST_FETCH_MODE = "algolia"
ELGIGANTEN_FALLBACK_BATCH_SIZE = 6


def get_elgiganten_products_from_public_pages(old_products):
    if not isinstance(old_products, dict) or not old_products:
        raise RuntimeError("Elgiganten public fallback mangler tidligere produktstate")

    products = {
        str(product_id): dict(product)
        for product_id, product in old_products.items()
        if isinstance(product, dict)
    }
    product_ids = [
        product_id
        for product_id in sorted(products)
        if str(products[product_id].get("url") or "").startswith("https://www.elgiganten.dk/product/")
    ]

    if not product_ids:
        raise RuntimeError("Elgiganten public fallback har ingen kendte produkt-URL'er")

    batch_size = min(ELGIGANTEN_FALLBACK_BATCH_SIZE, len(product_ids))
    bucket = int(time.time() // max(CHECK_EVERY, 300))
    start = (bucket * batch_size) % len(product_ids)
    selected = [
        product_ids[(start + offset) % len(product_ids)]
        for offset in range(batch_size)
    ]

    if curl_requests is not None:
        session = curl_requests.Session(impersonate="chrome")
    else:
        session = requests.Session()

    checked = 0
    changed = 0
    errors = 0

    for product_id in selected:
        old = products[product_id]
        url = old.get("url")
        try:
            response = session.get(
                url,
                headers={
                    **BROWSER_HEADERS,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
                },
                timeout=25,
            )
            response.raise_for_status()
        except Exception as error:
            errors += 1
            print(f"ELGIGANTEN public fallback {product_id}: {error}")
            continue

        checked += 1
        soup = BeautifulSoup(response.text, "html.parser")
        page_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
        low = page_text.lower()

        explicit_out = any(
            marker in low
            for marker in (
                "denne vare er desværre udsolgt",
                "begrænsede lager nu er solgt",
                "varen er udsolgt",
            )
        )
        explicit_in = any(
            marker in low
            for marker in (
                "læg i kurv",
                "tilføj til kurv",
                "på lager online",
                "kan leveres",
            )
        )

        new = dict(old)
        if explicit_out:
            new["online_stock"] = False
            new["online_display"] = "0"
        elif explicit_in:
            new["online_stock"] = True
            if not str(new.get("online_display") or "").strip() or str(new.get("online_display")) == "0":
                new["online_display"] = "1+"

        # Product pages expose a human-readable DKK price. Only accept a
        # plausible first match; otherwise preserve the last trusted price.
        price_match = re.search(
            r"(?<!\d)(\d{1,5}(?:[.,]\d{1,2})?)\s*(?:DKK|kr\.?)",
            page_text,
            flags=re.IGNORECASE,
        )
        if price_match:
            try:
                parsed_price = float(price_match.group(1).replace(".", "").replace(",", "."))
                if 5 <= parsed_price <= 50000:
                    new["price"] = parsed_price
            except ValueError:
                pass

        new["fetch_via"] = "public_product_page_fallback"
        new["fallback_checked_at"] = datetime.now(ZoneInfo("UTC")).isoformat()
        if (
            new.get("online_stock") != old.get("online_stock")
            or new.get("price") != old.get("price")
        ):
            changed += 1
        products[product_id] = new

    if checked == 0:
        raise RuntimeError(
            f"Elgiganten public fallback kunne ikke læse nogen af {batch_size} valgte produktsider"
        )

    print(
        f"ELGIGANTEN: public product-page fallback | "
        f"{checked}/{batch_size} tjekket | {changed} ændringer | {errors} fejl"
    )
    return products


def _get_elgiganten_products_algolia():
    api_key = get_elgiganten_signed_key()

    algolia_url = (
        "https://"
        f"{ELGIGANTEN_ALGOLIA_APP_ID.lower()}"
        "-dsn.algolia.net/1/indexes/*/queries"
    )

    request_params = {
        "analyticsTags": json.dumps(
            ["plp", "plp-virtual-category", "plp-navigational"],
            separators=(",", ":")
        ),
        "clickAnalytics": "false",
        "facets": '["*"]',
        "filters": (
            "productTaxonomy.id:PT1395 AND "
            "attributes.33253:Pokemon"
        ),
        "hitsPerPage": 48,
        "maxValuesPerFacet": 1000,
        "page": 0,
        "query": "",
        "ruleContexts": '["desktop","windows"]'
    }

    payload = {
        "requests": [
            {
                "indexName": ELGIGANTEN_ALGOLIA_INDEX,
                "params": urlencode(request_params)
            }
        ]
    }

    def do_request(key):
        algolia_query = {
            "x-algolia-agent": (
                "Algolia for JavaScript (5.56.0); "
                "Lite (5.56.0); Browser"
            ),
            "x-algolia-api-key": key,
            "x-algolia-application-id": ELGIGANTEN_ALGOLIA_APP_ID
        }

        return requests.post(
            algolia_url,
            params=algolia_query,
            headers={
                **BROWSER_HEADERS,
                "Accept": "application/json",
                "Content-Type": "text/plain",
                "Origin": ELGIGANTEN_BASE,
                "Referer": ELGIGANTEN_HOME
            },
            data=json.dumps(payload),
            timeout=20
        )

    response = do_request(api_key)

    if response.status_code in (401, 403):
        api_key = get_elgiganten_signed_key(force=True)
        response = do_request(api_key)

    response.raise_for_status()

    hits = response.json()["results"][0].get("hits", [])
    products = {}

    for product in hits:
        if not is_real_elgiganten_pokemon_tcg(product):
            continue

        product_id = str(
            product.get("articleNumber")
            or product.get("objectID")
            or ""
        )

        if not product_id:
            continue

        price = (product.get("price") or {}).get("amount")

        try:
            if price is not None:
                price = float(price)
        except (TypeError, ValueError):
            price = None

        whole_sale = product.get("wholeSaleStock") or {}
        online_stock = bool(whole_sale.get("inStock", False))
        online_display = str(whole_sale.get("display", "0"))

        kolding = get_elgiganten_store_stock(
            product,
            ELGIGANTEN_KOLDING_STORE_ID,
            "Elgiganten Kolding"
        )
        esbjerg = get_elgiganten_store_stock(
            product,
            ELGIGANTEN_ESBJERG_STORE_ID,
            "Elgiganten Esbjerg"
        )

        stores_with_stock = product.get("storesWithStock") or []
        store_count = len(stores_with_stock)

        url = (
            product.get("productUrl")
            or product.get("urlB2C")
            or ELGIGANTEN_HOME
        )

        products[product_id] = {
            "name": product.get("title") or "Ukendt produkt",
            "price": price,
            "online_stock": online_stock,
            "online_display": online_display,
            "store_count": store_count,
            "local_stocks": {
                ELGIGANTEN_KOLDING_STORE_ID: kolding,
                ELGIGANTEN_ESBJERG_STORE_ID: esbjerg
            },
            "quantity_text": (
                product.get("advertisingText")
                or product.get("salesPoint")
                or ""
            ).strip(),
            "release_date": product.get("releaseDate"),
            "url": url
        }

    return products


def get_elgiganten_products(old_products=None):
    global ELGIGANTEN_LAST_FETCH_MODE

    try:
        products = _get_elgiganten_products_algolia()
        ELGIGANTEN_LAST_FETCH_MODE = "algolia"
        return products
    except Exception as algolia_error:
        print(f"ELGIGANTEN Algolia utilgængelig: {algolia_error}")
        try:
            products = get_elgiganten_products_from_public_pages(old_products or {})
        except Exception as fallback_error:
            raise RuntimeError(
                f"Elgiganten både Algolia og public fallback fejlede: "
                f"{algolia_error}; fallback: {fallback_error}"
            ) from fallback_error
        ELGIGANTEN_LAST_FETCH_MODE = "public_product_pages"
        return products


def count_elgiganten_local_products(products):
    counts = {
        ELGIGANTEN_KOLDING_STORE_ID: 0,
        ELGIGANTEN_ESBJERG_STORE_ID: 0
    }

    for product in products.values():
        local_stocks = product.get("local_stocks") or {}

        for store_id in counts:
            store = local_stocks.get(store_id) or {}

            if store.get("in_stock"):
                counts[store_id] += 1

    return counts


# =========================================================
# SHOPIFY FETCH
# =========================================================

def shopify_text(product):
    tags = product.get("tags") or []

    if isinstance(tags, list):
        tags_text = " ".join(str(tag) for tag in tags)
    else:
        tags_text = str(tags)

    return " ".join(
        [
            str(product.get("title", "")),
            str(product.get("product_type", "")),
            str(product.get("vendor", "")),
            tags_text
        ]
    ).lower()


def detect_shopify_game(product):
    text = shopify_text(product)

    if "lorcana" in text:
        return "LORCANA"

    if "pokemon" in text or "pokémon" in text:
        return "POKÉMON"

    return None


def is_relevant_shopify_tcg(product, game):
    text = shopify_text(product)
    title = str(product.get("title", "")).lower()
    product_type = str(product.get("product_type", "")).lower()

    if game == "POKÉMON":
        if "pokemon" not in text and "pokémon" not in text:
            return False

    elif game == "LORCANA":
        if "lorcana" not in text:
            return False

    else:
        return False

    # Hard block: akryl-display/cases er tilbehør,
    # selv hvis titlen også indeholder booster, ETB, bundle osv.
    hard_accessory_markers = (
        "akryl",
        "acryl",
        "acrylic",
    )

    if any(marker in title for marker in hard_accessory_markers):
        return False
    
    # Enkeltkort/gradede kort giver meget støj i en restock-bot.
    single_markers = (
        "graded",
        "gradede",
        "raw card",
        "single card",
        "singles",
        "enkeltkort",
        "psa 10",
        "psa 9",
        "psa 8",
        "cgc 10",
        "bgs 10"
    )

    if any(marker in product_type for marker in single_markers):
        return False

    if any(marker in text for marker in single_markers):
        return False

    sealed_markers = (
        "booster",
        "elite trainer",
        " etb",
        "etb ",
        "collection",
        "box",
        "bundle",
        "blister",
        " tin",
        "tin ",
        "deck",
        "toolkit",
        "battle academy",
        "chest",
        "trove",
        "starter",
        "gift set",
        "premium",
        " upc",
        "upc ",
        "poster",
        "julekalender",
        "calendar",
        "display"
    )

    accessory_markers = (
        "sleeve",
        "sleeves",
        "kortlommer",
        "mappe",
        "binder",
        "portfolio",
        "playmat",
        "deck box",
        "deckbox",
        "toploader",
        "top loader",
        "akryl",
        "acryl",
        "acrylic",
        "storage box",
        "display case",
        "card case",
        "kortbeskytt"
    )

    is_sealed = any(marker in title for marker in sealed_markers)
    is_accessory = any(marker in title for marker in accessory_markers)

    if any(marker in title for marker in ("league night", "draft night")):
        return False

    if is_accessory:
        # Officielle Binder Collections indeholder boosters og er sealed.
        return "binder" in title and "collection" in title

    return is_sealed


def shopify_variant_available(product):
    return any(
        variant.get("available") is True
        for variant in product.get("variants", [])
    )


def shopify_min_price(product):
    prices = []

    for variant in product.get("variants", []):
        try:
            price = float(variant.get("price"))
        except (TypeError, ValueError):
            continue

        # 0 kr. bruges nogle steder som placeholder før rigtig pris.
        if price > 0:
            prices.append(price)

    if not prices:
        return None

    return min(prices)


def shopify_is_preorder(product):
    text = shopify_text(product)

    return any(
        marker in text
        for marker in (
            "preorder",
            "pre-order",
            "pre order",
            "forudbestil",
            "forudbestilling"
        )
    )


def fetch_shopify_feed(base, path):
    collected = {}

    for page in range(1, SHOPIFY_MAX_PAGES + 1):
        response = requests.get(
            base + path,
            headers={
                **BROWSER_HEADERS,
                "Accept": "application/json,text/plain,*/*"
            },
            params={
                "limit": SHOPIFY_PAGE_SIZE,
                "page": page
            },
            timeout=30
        )

        response.raise_for_status()

        data = response.json()
        page_products = data.get("products", [])

        if not page_products:
            break

        new_on_page = 0

        for product in page_products:
            product_id = str(product.get("id", "")).strip()

            if not product_id:
                continue

            if product_id not in collected:
                new_on_page += 1

            collected[product_id] = product

        # Beskytter mod shops der ignorerer page-parameteren.
        if new_on_page == 0:
            break

        if len(page_products) < SHOPIFY_PAGE_SIZE:
            break

    return list(collected.values())


def get_shopify_products(site_key):
    site = SHOPIFY_SITES[site_key]
    products = {}

    for feed in site["feeds"]:
        raw_products = fetch_shopify_feed(
            site["base"],
            feed["path"]
        )

        for raw in raw_products:
            game = feed.get("game") or detect_shopify_game(raw)

            if not game:
                continue

            if not is_relevant_shopify_tcg(raw, game):
                continue

            product_id = str(raw.get("id", "")).strip()
            handle = str(raw.get("handle", "")).strip()
            name = str(raw.get("title", "")).strip()

            if not product_id or not name or not handle:
                continue

            products[product_id] = {
                "name": name,
                "game": game,
                "price": shopify_min_price(raw),
                "in_stock": shopify_variant_available(raw),
                "preorder": bool(feed.get("preorder")) or shopify_is_preorder(raw),
                "url": f"{site['base']}/products/{handle}"
            }

    return products


def count_shopify_products(products):
    counts = {
        "POKÉMON": 0,
        "LORCANA": 0,
        "POKÉMON_STOCK": 0,
        "LORCANA_STOCK": 0
    }

    for product in products.values():
        game = product.get("game")

        if game not in ("POKÉMON", "LORCANA"):
            continue

        counts[game] += 1

        if product.get("in_stock"):
            counts[f"{game}_STOCK"] += 1

    return counts


# =========================================================
# WOOCOMMERCE FETCH
# =========================================================

def woocommerce_clean_text(value):
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def woocommerce_norm(value):
    text = woocommerce_clean_text(value).lower()
    text = unicodedata.normalize("NFKD", text)

    return "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )


def woocommerce_category_text(product):
    return " | ".join(
        woocommerce_norm(category.get("name"))
        for category in (product.get("categories") or [])
    )


def woocommerce_product_text(product):
    category_names = " ".join(
        woocommerce_clean_text(category.get("name"))
        for category in (product.get("categories") or [])
    )

    return woocommerce_norm(
        " ".join(
            [
                woocommerce_clean_text(product.get("name")),
                category_names,
                woocommerce_clean_text(product.get("short_description")),
                woocommerce_clean_text(product.get("description"))
            ]
        )
    )


def woocommerce_is_relevant_sealed(product):
    title = woocommerce_norm(product.get("name"))
    categories = woocommerce_category_text(product)

    # Singles og gradede kort skal aldrig kunne reddes af ord som
    # "Collection" eller "Booster" i kortets navn/serie.
    hard_blocked_categories = (
        "single",
        "singles",
        "enkeltkort",
        "graded",
        "gradede"
    )

    if any(marker in categories for marker in hard_blocked_categories):
        return False

    # Tydeligt ikke-sealed / støj.
    blocked_titles = (
        "[test]",
        "mystery box",
        "mystery pack",
        "store credit",
        "reverse foil",
        "card sleeve",
        "sleeve pack",
        "sleeves pack",
        "deck case",
        "deck box",
        "playmat",
        "play mat",
        "toploader",
        "top loader",
        "akryl",
        "acryl",
        "acrylic",
        "card saver",
        "storage box",
        "display case"
    )

    if any(marker in title for marker in blocked_titles):
        return False

    # En ren binder/mappe er tilbehør. Binder Collection/Gift Box er
    # derimod ofte et officielt sealed produkt med boosters og skal med.
    if (
        "binder" in title
        and "collection" not in title
        and "gift box" not in title
    ):
        return False

    if "portfolio" in title:
        return False

    sealed_patterns = (
        r"\bbooster(?:s)?\b",
        r"\bdisplay\b",
        r"\bbox\b",
        r"\bcollection\b",
        r"\bbundle\b",
        r"\bblister\b",
        r"\btins?\b",
        r"\bdeck\b",
        r"\bstarter\b",
        r"\belite trainer\b",
        r"\betb\b",
        r"\btrove\b",
        r"\bgift set\b",
        r"\bgift box\b",
        r"\bbattle academy\b",
        r"\btoolkit\b",
        r"\bcalendar\b",
        r"\bjulekalender\b",
        r"\bchest\b",
        r"\bpremium\b",
        r"\bpacks?\b",
        r"\bupc\b",
        r"\bbuild (?:&|and) battle\b",
        r"\bpre release kit\b",
        r"\bprerelease kit\b"
    )

    return any(
        re.search(pattern, title)
        for pattern in sealed_patterns
    )


def woocommerce_price(product):
    prices = product.get("prices") or {}
    raw_price = prices.get("price")
    minor_unit = prices.get("currency_minor_unit", 2)

    if raw_price is None:
        return None

    try:
        price = int(raw_price) / (10 ** int(minor_unit))
    except (TypeError, ValueError):
        return None

    # 0 kr. bruges indimellem som placeholder på kommende produkter.
    if price <= 0:
        return None

    return price


def woocommerce_is_preorder(product):
    text = woocommerce_product_text(product)

    return any(
        marker in text
        for marker in (
            "preorder",
            "pre-order",
            "pre order",
            "forudbestil",
            "forudbestilling"
        )
    )


def fetch_woocommerce_category(base, category_id, trust_total_pages=True):
    collected = {}

    for page in range(1, WOOCOMMERCE_MAX_PAGES + 1):
        response = requests.get(
            base + WOOCOMMERCE_API_PATH,
            headers={
                **BROWSER_HEADERS,
                "Accept": "application/json,text/plain,*/*"
            },
            params={
                "category": category_id,
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

        if total_pages and trust_total_pages:
            try:
                if page >= int(total_pages):
                    break
            except ValueError:
                pass

        if len(page_products) < WOOCOMMERCE_PAGE_SIZE:
            break

    return list(collected.values())


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


def count_woocommerce_products(products):
    counts = {
        "POKÉMON": 0,
        "LORCANA": 0,
        "POKÉMON_STOCK": 0,
        "LORCANA_STOCK": 0
    }

    for product in products.values():
        game = product.get("game")

        if game not in ("POKÉMON", "LORCANA"):
            continue

        counts[game] += 1

        if product.get("in_stock"):
            counts[f"{game}_STOCK"] += 1

    return counts



# =========================================================
# NEXT LEVEL GAMES
# =========================================================

def nextlevel_clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def nextlevel_parse_price(text):
    matches = re.findall(
        r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d+(?:,\d{2})?)\s*kr\. ?",
        nextlevel_clean_text(text),
        flags=re.I
    )

    if not matches:
        return None

    raw = matches[-1].replace(".", "").replace(",", ".")

    try:
        return float(raw)
    except ValueError:
        return None


def nextlevel_status_from_text(text, preorder_feed=False):
    low = nextlevel_clean_text(text).lower()

    if (
        preorder_feed
        or "forudbestil" in low
        or "forudbestilling" in low
        or "preorder" in low
        or "pre-order" in low
    ):
        return "FORUDBESTILLING"

    if (
        "udsolgt" in low
        or "ikke på lager" in low
        or "ikke pa lager" in low
    ):
        return "UDSOLGT"

    if (
        "på lager" in low
        or "pa lager" in low
        or "levering 1-2 dage" in low
    ):
        return "PÅ LAGER"

    return "UKENDT"


def nextlevel_card_title(card):
    selectors = (
        ".product-title a",
        ".product-name a",
        "h2 a",
        "h3 a",
        "h4 a",
        "a.product-thumbnail"
    )

    for selector in selectors:
        node = card.select_one(selector)
        if not node:
            continue

        title = nextlevel_clean_text(node.get_text(" ", strip=True))
        if len(title) >= 4:
            return title

        image = node.find("img", alt=True)
        if image:
            alt = nextlevel_clean_text(image.get("alt"))
            if len(alt) >= 4:
                return alt

    for image in card.find_all("img", alt=True):
        alt = nextlevel_clean_text(image.get("alt"))
        if len(alt) >= 4:
            return alt

    return ""


def nextlevel_card_url(card, page_url):
    for anchor in card.find_all("a", href=True):
        href = urljoin(page_url, anchor["href"])
        if ".html" in href and "nextlevelgames.dk" in href:
            return href
    return None


def get_nextlevel_feed(feed):
    response = requests.get(
        feed["url"],
        headers={
            **BROWSER_HEADERS,
            "Accept-Language": "da-DK,da;q=0.9,en;q=0.8"
        },
        timeout=30
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    products = {}

    cards = soup.select(
        "article.product-miniature, .product-miniature, [data-id-product]"
    )

    for card in cards:
        product_id = card.get("data-id-product")
        if not product_id:
            continue

        name = nextlevel_card_title(card)
        if not name:
            continue

        low = name.lower()
        if any(marker in low for marker in NEXTLEVEL_BLOCKED_MARKERS):
            continue

        card_text = nextlevel_clean_text(card.get_text(" ", strip=True))
        status = nextlevel_status_from_text(
            card_text,
            feed.get("preorder_feed", False)
        )

        products[str(product_id)] = {
            "name": name,
            "game": feed["game"],
            "price": nextlevel_parse_price(card_text),
            "status": status,
            "in_stock": status == "PÅ LAGER",
            "preorder": status == "FORUDBESTILLING",
            "url": nextlevel_card_url(card, feed["url"]) or feed["url"]
        }

    return products


def get_nextlevel_products():
    products = {}

    for feed in NEXTLEVEL_FEEDS:
        feed_products = get_nextlevel_feed(feed)

        for product_id, product in feed_products.items():
            old = products.get(product_id)

            if old is None:
                products[product_id] = product
                continue

            if product.get("preorder"):
                products[product_id] = product
                continue

            if (
                old.get("status") == "UKENDT"
                and product.get("status") != "UKENDT"
            ):
                products[product_id] = product

    return products


def count_nextlevel_products(products):
    counts = {
        "POKÉMON": 0,
        "LORCANA": 0,
        "POKÉMON_STOCK": 0,
        "LORCANA_STOCK": 0,
        "PREORDER": 0
    }

    for product in products.values():
        game = product.get("game")
        if game not in ("POKÉMON", "LORCANA"):
            continue

        counts[game] += 1

        if product.get("in_stock"):
            counts[f"{game}_STOCK"] += 1

        if product.get("preorder"):
            counts["PREORDER"] += 1

    return counts


def nextlevel_status_lines(product):
    if product.get("preorder"):
        stock_line = "🚨 Forudbestilling"
    elif product.get("in_stock"):
        stock_line = "📦 På lager"
    elif product.get("status") == "UDSOLGT":
        stock_line = "📦 Udsolgt"
    else:
        stock_line = "📦 Lagerstatus ukendt"

    return (
        f"{stock_line}\n"
        f"💰 {format_price(product.get('price'))}"
    )


# =========================================================
# EPIC PANDA
# =========================================================

EPICPANDA_SEALED_MARKERS = (
    "booster",
    "box",
    "boks",
    "bundle",
    "blister",
    "collection",
    "tin",
    "deck",
    "starter",
    "elite trainer",
    "etb",
    "trove",
    "gift",
    "battle academy",
    "toolkit",
    "calendar",
    "julekalender",
    "chest",
    "premium",
    "pack",
    "display",
    "prerelease",
    "pre release",
    "world championship",
    "quest"
)

EPICPANDA_BLOCKED_MARKERS = (
    "playmat",
    "mappe",
    "binder",
    "sleeves",
    "sleeve pack",
    "lommer",
    "deck box",
    "deck boks",
    "portfolio",
    "toploader",
    "top loader",
    "plush",
    "funko",
    "figure",
    "figur",
    "accessor",
    "tilbehør"
)


def epicpanda_clean_text(text):
    return re.sub(
        r"\s+",
        " ",
        text or ""
    ).strip()


def epicpanda_parse_price(text):
    matches = re.findall(
        r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*DKK",
        text
    )

    if not matches:
        return None

    raw = matches[-1].replace(
        ".",
        ""
    ).replace(
        ",",
        "."
    )

    try:
        price = float(raw)
    except ValueError:
        return None

    if price <= 0:
        return None

    return price


def epicpanda_status_from_text(text):
    low = text.lower()

    if (
        "forudbestilling" in low
        or "forudbestil" in low
    ):
        return "FORUDBESTILLING"

    if (
        "ikke på lager" in low
        or "ikke pa lager" in low
    ):
        return "UDSOLGT"

    if (
        "på lager" in low
        or "pa lager" in low
    ):
        return "PÅ LAGER"

    return "UKENDT"


def epicpanda_is_relevant_sealed(title):
    low = title.lower()

    if any(
        marker in low
        for marker in EPICPANDA_BLOCKED_MARKERS
    ):
        return False

    return any(
        marker in low
        for marker in EPICPANDA_SEALED_MARKERS
    )


def epicpanda_nearest_product_node(anchor):
    node = anchor
    best = anchor

    for _ in range(9):
        node = node.parent

        if node is None:
            break

        text = epicpanda_clean_text(
            node.get_text(
                " ",
                strip=True
            )
        )

        if text:
            best = node

        if (
            "DKK" in text
            and (
                "På lager" in text
                or "Ikke på lager" in text
                or "Forudbestilling" in text
                or "Forudbestil" in text
            )
        ):
            return node

    return best


def get_epicpanda_page(url, game):
    response = requests.get(
        url,
        headers=BROWSER_HEADERS,
        timeout=30
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    products = {}

    for anchor in soup.find_all(
        "a",
        href=True
    ):
        href = urljoin(
            EPICPANDA_BASE,
            anchor["href"]
        )

        match = re.search(
            r"-(\d+)p\.html(?:\?|$)",
            href
        )

        if not match:
            continue

        product_id = match.group(1)

        name = epicpanda_clean_text(
            anchor.get_text(
                " ",
                strip=True
            )
        )

        if (
            len(name) < 4
            or name.lower() in {
                "vis produkt",
                "image"
            }
        ):
            continue

        node = epicpanda_nearest_product_node(
            anchor
        )

        node_text = epicpanda_clean_text(
            node.get_text(
                " ",
                strip=True
            )
        )

        status = epicpanda_status_from_text(
            node_text
        )

        products[product_id] = {
            "name": name,
            "game": game,
            "price": epicpanda_parse_price(
                node_text
            ),
            "status": status,
            "in_stock": status == "PÅ LAGER",
            "preorder": status == "FORUDBESTILLING",
            "url": href
        }

    return products


def get_epicpanda_products():
    products = {}

    for feed in EPICPANDA_FEEDS:
        seen_ids = set()

        for page in range(
            1,
            EPICPANDA_MAX_PAGES + 1
        ):
            url = feed["pattern"].format(
                page=page
            )

            page_products = get_epicpanda_page(
                url,
                feed["game"]
            )

            page_ids = set(
                page_products.keys()
            )

            new_ids = (
                page_ids
                - seen_ids
            )

            if (
                not page_products
                or not new_ids
            ):
                break

            seen_ids.update(
                page_ids
            )

            for product_id, product in page_products.items():
                if not epicpanda_is_relevant_sealed(
                    product["name"]
                ):
                    continue

                products[product_id] = product

    return products


def count_epicpanda_products(products):
    counts = {
        "POKÉMON": 0,
        "LORCANA": 0,
        "POKÉMON_STOCK": 0,
        "LORCANA_STOCK": 0,
        "PREORDER": 0
    }

    for product in products.values():
        game = product.get(
            "game"
        )

        if game not in (
            "POKÉMON",
            "LORCANA"
        ):
            continue

        counts[game] += 1

        if product.get(
            "in_stock"
        ):
            counts[
                f"{game}_STOCK"
            ] += 1

        if product.get(
            "preorder"
        ):
            counts["PREORDER"] += 1

    return counts


def epicpanda_status_lines(product):
    if product.get(
        "preorder"
    ):
        stock_line = "🚨 Forudbestilling"

    elif product.get(
        "in_stock"
    ):
        stock_line = "📦 På lager"

    else:
        status = product.get(
            "status",
            "UDSOLGT"
        )

        if status == "UKENDT":
            stock_line = "📦 Lagerstatus ukendt"
        else:
            stock_line = "📦 Udsolgt"

    return (
        f"{stock_line}\n"
        f"💰 {format_price(product.get('price'))}"
    )


# =========================================================
# STEFFEN-O
# =========================================================

STEFFENO_SEALED_MARKERS = (
    "booster",
    "box",
    "boks",
    "bundle",
    "blister",
    "collection",
    "tin",
    "elite trainer",
    " etb",
    "etb ",
    "starter deck",
    "battle deck",
    "league battle",
    "battle academy",
    "trainer toolkit",
    "toolkit",
    "display",
    "checklane",
    "build & battle",
    "build and battle",
    "premium collection",
    "special collection",
    "illustration collection",
    "first partner",
    "world championship",
    "julekalender",
    "calendar",
    "chest",
    "pack",
    "pakke"
)

STEFFENO_BLOCKED_MARKERS = (
    "lomme",
    "lommer",
    "sleeve",
    "sleeves",
    "mappe",
    "binder",
    "portfolio",
    "album",
    "playmat",
    "play mat",
    "deck box",
    "deckbox",
    "toploader",
    "top loader",
    "card saver",
    "opbevaring",
    "storage"
)


def steffeno_clean_text(value):
    return re.sub(
        r"\s+",
        " ",
        value or ""
    ).strip()


def steffeno_is_relevant_sealed(title):
    low = steffeno_clean_text(
        title
    ).lower()

    if any(
        marker in low
        for marker in STEFFENO_BLOCKED_MARKERS
    ):
        return False

    return any(
        marker in low
        for marker in STEFFENO_SEALED_MARKERS
    )


def steffeno_price(product):
    prices = (
        product.get("Prices")
        or []
    )

    if not prices:
        return None

    row = (
        prices[0]
        or {}
    )

    for key in (
        "PriceMinWithVat",
        "PriceMin",
        "PriceMaxWithVat",
        "PriceMax"
    ):
        value = row.get(
            key
        )

        if isinstance(
            value,
            (int, float)
        ):
            return float(
                value
            )

    return None


def steffeno_stock(product):
    stock = product.get(
        "StockWithoutReservation"
    )

    if not isinstance(
        stock,
        (int, float)
    ):
        stock = product.get(
            "Stock"
        )

    if not isinstance(
        stock,
        (int, float)
    ):
        return None

    return int(
        stock
    )


def steffeno_preorder(product):
    text = " ".join(
        [
            steffeno_clean_text(
                product.get("Title")
            ),
            steffeno_clean_text(
                product.get("DeliveryTimeText")
            )
        ]
    ).lower()

    return (
        "forudbestilling" in text
        or "forudbestil" in text
        or "preorder" in text
        or "pre-order" in text
    )


def steffeno_status(product):
    if steffeno_preorder(
        product
    ):
        return "FORUDBESTILLING"

    stock = steffeno_stock(
        product
    )

    if stock is not None:
        if stock > 0:
            return "PÅ LAGER"

        return "UDSOLGT"

    text = steffeno_clean_text(
        product.get(
            "DeliveryTimeText"
        )
    ).lower()

    if (
        "ikke på lager" in text
        or "ikke pa lager" in text
    ):
        return "UDSOLGT"

    if (
        "på lager" in text
        or "pa lager" in text
    ):
        return "PÅ LAGER"

    return "UKENDT"


def get_steffeno_products():
    session = requests.Session()

    session.headers.update(
        {
            **BROWSER_HEADERS,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "da-DK,da;q=0.9,en;q=0.8"
        }
    )

    # Samme session-flow som webshoppen selv bruger.
    session.get(
        STEFFENO_BASE + "/",
        timeout=20
    ).raise_for_status()

    session.get(
        STEFFENO_CATEGORY_URL,
        timeout=20
    ).raise_for_status()

    response = session.get(
        STEFFENO_API_URL,
        params={
            "field": "categoryId",
            "id": STEFFENO_CATEGORY_ID,
            "page": 1,
            "limit": STEFFENO_PAGE_SIZE,
            "filterGenerate": "true",
            "currencyIso": "DKK"
        },
        headers={
            "Referer": STEFFENO_CATEGORY_URL
        },
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    products = {}

    for raw_product in (
        data.get("products")
        or []
    ):
        name = steffeno_clean_text(
            raw_product.get("Title")
        )

        if (
            not name
            or not steffeno_is_relevant_sealed(
                name
            )
        ):
            continue

        product_id = str(
            raw_product.get("Id")
        )

        handle = (
            raw_product.get("Handle")
            or ""
        )

        stock = steffeno_stock(
            raw_product
        )

        status = steffeno_status(
            raw_product
        )

        products[
            product_id
        ] = {
            "name": name,
            "game": "POKÉMON",
            "price": steffeno_price(
                raw_product
            ),
            "stock": stock,
            "status": status,
            "in_stock": (
                status == "PÅ LAGER"
            ),
            "preorder": (
                status == "FORUDBESTILLING"
            ),
            "url": urljoin(
                STEFFENO_BASE,
                handle
            )
        }

    return products


def count_steffeno_products(
    products
):
    return {
        "POKÉMON": len(
            products
        ),
        "POKÉMON_STOCK": sum(
            1
            for product
            in products.values()
            if product.get(
                "in_stock"
            )
        ),
        "PREORDER": sum(
            1
            for product
            in products.values()
            if product.get(
                "preorder"
            )
        )
    }


def steffeno_status_lines(
    product
):
    stock = product.get(
        "stock"
    )

    if product.get(
        "preorder"
    ):
        status_line = (
            "🚨 Forudbestilling"
        )

    elif product.get(
        "in_stock"
    ):
        if stock is None:
            status_line = (
                "📦 På lager"
            )
        else:
            status_line = (
                f"📦 På lager: {stock} stk."
            )

    else:
        status_line = (
            "📦 Udsolgt"
        )

    return (
        f"{status_line}\n"
        f"💰 {format_price(product.get('price'))}"
    )


# =========================================================
# STATE
# =========================================================

def load_state():
    if not os.path.exists(
        STATE_FILE
    ):
        return None

    with open(
        STATE_FILE,
        "r",
        encoding="utf-8"
    ) as file:
        return json.load(file)


def save_state(state):
    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=2
        )


# =========================================================
# COOLSHOP ÆNDRINGER
# =========================================================

def process_coolshop_changes(
    old_products,
    new_products
):
    new_products = filter_restock_alert_products(new_products)

    # NYE PRODUKTER
    for url, product in new_products.items():
        if url not in old_products:
            send_discord(
                f"🆕 **[{product['game']}] NYT FUNDET PÅ COOLSHOP**\n"
                f"**{product['name']}**\n"
                f"💰 {format_price(product['price'])}\n"
                f"🔗 {url}"
            )

    # RESTOCK + PRISFALD
    for url, product in new_products.items():
        if url not in old_products:
            continue

        old = old_products[url]

        old_stock = old.get(
            "online_stock",
            False
        )

        new_stock = product.get(
            "online_stock",
            False
        )

        if (
            not old_stock
            and new_stock
        ):
            send_discord(
                f"🔥 **[{product['game']}] COOLSHOP RESTOCK**\n"
                f"**{product['name']}**\n"
                "✅ På lager online\n"
                f"💰 {format_price(product['price'])}\n"
                f"🔗 {url}"
            )

        old_price = old.get(
            "price"
        )

        new_price = product.get(
            "price"
        )

        if (
            old_price is not None
            and new_price is not None
            and new_price < old_price
        ):
            send_discord(
                f"💰 **[{product['game']}] COOLSHOP PRISFALD**\n"
                f"**{product['name']}**\n"
                f"{format_price(old_price)} → "
                f"**{format_price(new_price)}**\n"
                f"🔗 {url}"
            )


# =========================================================
# PROSHOP ÆNDRINGER
# =========================================================

def process_proshop_changes(
    old_products,
    new_products
):
    new_products = filter_restock_alert_products(new_products, "POKÉMON")

    # NYE PRODUKTER
    for product_id, product in new_products.items():
        if product_id not in old_products:
            send_discord(
                "🆕 **[POKÉMON] NYT PÅ PROSHOP**\n"
                f"**{product['name']}**\n"
                f"📦 {product['stock']}\n"
                f"💰 {format_price(product['price'])}\n"
                f"🔗 {product['url']}"
            )

    # RESTOCK + PRISFALD
    for product_id, product in new_products.items():
        if product_id not in old_products:
            continue

        old = old_products[
            product_id
        ]

        old_stock = old.get(
            "stock",
            "UKENDT"
        )

        new_stock = product.get(
            "stock",
            "UKENDT"
        )

        if (
            old_stock != "PÅ LAGER"
            and new_stock == "PÅ LAGER"
        ):
            send_discord(
                "🔥 **[POKÉMON] PROSHOP RESTOCK**\n"
                f"**{product['name']}**\n"
                f"📦 {old_stock} → **PÅ LAGER**\n"
                f"💰 {format_price(product['price'])}\n"
                f"🔗 {product['url']}"
            )

        old_price = old.get(
            "price"
        )

        new_price = product.get(
            "price"
        )

        if (
            old_price is not None
            and new_price is not None
            and new_price < old_price
        ):
            send_discord(
                "💰 **[POKÉMON] PROSHOP PRISFALD**\n"
                f"**{product['name']}**\n"
                f"{format_price(old_price)} → "
                f"**{format_price(new_price)}**\n"
                f"🔗 {product['url']}"
            )


# =========================================================
# BR ÆNDRINGER
# =========================================================

def format_br_stock(stock):
    if stock is None:
        return "Ukendt"

    return f"{stock} stk."


def br_status_lines(product):
    lines = [
        (
            "🏪 BR Kolding: "
            f"{format_br_stock(product.get('kolding_stock'))}"
        ),
        (
            "🏪 BR Esbjerg: "
            f"{format_br_stock(product.get('esbjerg_stock'))}"
        ),
        (
            "🌐 Online: "
            f"{product.get('online_count', 0)} stk."
        ),
        (
            "🇩🇰 Butikker med lager: "
            f"{product.get('store_count', 0)}"
        ),
        f"💰 {format_price(product.get('price'))}"
    ]

    quantity_limit = product.get(
        "quantity_limit"
    )

    if quantity_limit is not None:
        lines.append(
            f"👤 Max pr. kunde: {quantity_limit}"
        )

    return "\n".join(lines)


def process_br_changes(
    old_products,
    new_products
):
    new_products = filter_restock_alert_products(new_products, "POKÉMON")

    # NYE PRODUKTER
    for product_id, product in new_products.items():
        if product_id not in old_products:
            send_discord(
                "🆕 **[POKÉMON] NYT PÅ BR**\n"
                f"**{product['name']}**\n"
                f"{br_status_lines(product)}\n"
                f"🔗 {product['url']}"
            )

    # RESTOCK + PRISFALD
    for product_id, product in new_products.items():
        if product_id not in old_products:
            continue

        old = old_products[product_id]

        old_kolding = old.get("kolding_stock")
        new_kolding = product.get("kolding_stock")
        old_esbjerg = old.get("esbjerg_stock")
        new_esbjerg = product.get("esbjerg_stock")

        old_online = max(
            0,
            safe_int(
                old.get("online_count"),
                0
            )
        )

        new_online = max(
            0,
            safe_int(
                product.get("online_count"),
                0
            )
        )

        kolding_restock = (
            old_kolding is not None
            and new_kolding is not None
            and safe_int(old_kolding, 0) <= 0
            and safe_int(new_kolding, 0) > 0
        )

        esbjerg_restock = (
            old_esbjerg is not None
            and new_esbjerg is not None
            and safe_int(old_esbjerg, 0) <= 0
            and safe_int(new_esbjerg, 0) > 0
        )

        online_restock = (
            old_online <= 0
            and new_online > 0
        )

        local_restock = kolding_restock or esbjerg_restock

        if local_restock or online_restock:
            if local_restock and online_restock:
                title = "🔥 **[POKÉMON] BR RESTOCK**"
            elif kolding_restock and esbjerg_restock:
                title = "🏪 **[POKÉMON] BR LOKAL RESTOCK**"
            elif kolding_restock:
                title = "🏪 **[POKÉMON] BR KOLDING RESTOCK**"
            elif esbjerg_restock:
                title = "🏪 **[POKÉMON] BR ESBJERG RESTOCK**"
            else:
                title = "🌐 **[POKÉMON] BR ONLINE RESTOCK**"

            transition_lines = []

            if kolding_restock:
                transition_lines.append(
                    "🏪 BR Kolding: "
                    f"{safe_int(old_kolding, 0)} → "
                    f"**{safe_int(new_kolding, 0)} stk.**"
                )
            else:
                transition_lines.append(
                    "🏪 BR Kolding: "
                    f"{format_br_stock(new_kolding)}"
                )

            if esbjerg_restock:
                transition_lines.append(
                    "🏪 BR Esbjerg: "
                    f"{safe_int(old_esbjerg, 0)} → "
                    f"**{safe_int(new_esbjerg, 0)} stk.**"
                )
            else:
                transition_lines.append(
                    "🏪 BR Esbjerg: "
                    f"{format_br_stock(new_esbjerg)}"
                )

            if online_restock:
                transition_lines.append(
                    "🌐 Online: "
                    f"{old_online} → **{new_online} stk.**"
                )
            else:
                transition_lines.append(
                    f"🌐 Online: {new_online} stk."
                )

            transition_lines.append(
                "🇩🇰 Butikker med lager: "
                f"{product.get('store_count', 0)}"
            )

            transition_lines.append(
                f"💰 {format_price(product.get('price'))}"
            )

            quantity_limit = product.get(
                "quantity_limit"
            )

            if quantity_limit is not None:
                transition_lines.append(
                    f"👤 Max pr. kunde: {quantity_limit}"
                )

            send_discord(
                f"{title}\n"
                f"**{product['name']}**\n"
                + "\n".join(transition_lines)
                + f"\n🔗 {product['url']}"
            )

        old_price = old.get("price")
        new_price = product.get("price")

        if (
            old_price is not None
            and new_price is not None
            and new_price < old_price
        ):
            send_discord(
                "💰 **[POKÉMON] BR PRISFALD**\n"
                f"**{product['name']}**\n"
                f"{format_price(old_price)} → "
                f"**{format_price(new_price)}**\n"
                f"🏪 BR Kolding: {format_br_stock(product.get('kolding_stock'))}\n"
                f"🏪 BR Esbjerg: {format_br_stock(product.get('esbjerg_stock'))}\n"
                f"🌐 Online: {product.get('online_count', 0)} stk.\n"
                f"🇩🇰 Butikker med lager: {product.get('store_count', 0)}\n"
                f"🔗 {product['url']}"
            )


# =========================================================
# BILKA + FOETEX ÆNDRINGER
# =========================================================

def format_local_stock(stock):
    if stock is None:
        return "Ukendt"

    return f"{stock} stk."


def salling_status_lines(site_key, product):
    site = SALLING_SITES[site_key]
    local_stocks = product.get("local_stocks") or {}
    lines = []

    for site_id, default_name in site["local_stores"].items():
        store_data = local_stocks.get(site_id) or {}
        store_name = store_data.get("name") or default_name
        stock = store_data.get("stock")

        lines.append(
            f"🏪 {store_name}: {format_local_stock(stock)}"
        )

    lines.extend(
        [
            f"🌐 Online: {product.get('online_count', 0)} stk.",
            (
                "🇩🇰 Butikker med lager: "
                f"{product.get('store_count', 0)}"
            ),
            f"💰 {format_price(product.get('price'))}"
        ]
    )

    quantity_limit = product.get("quantity_limit")

    if quantity_limit is not None:
        lines.append(
            f"👤 Max pr. kunde: {quantity_limit}"
        )

    return "\n".join(lines)


def process_salling_changes(
    site_key,
    old_products,
    new_products
):
    new_products = filter_restock_alert_products(new_products, "POKÉMON")
    site = SALLING_SITES[site_key]
    label = site["label"]

    # NYE PRODUKTER
    for product_id, product in new_products.items():
        if product_id not in old_products:
            send_discord(
                f"🆕 **[POKÉMON] NYT PÅ {label}**\n"
                f"**{product['name']}**\n"
                f"{salling_status_lines(site_key, product)}\n"
                f"🔗 {product['url']}"
            )

    # RESTOCK + PRISFALD
    for product_id, product in new_products.items():
        if product_id not in old_products:
            continue

        old = old_products[product_id]
        old_local = old.get("local_stocks") or {}
        new_local = product.get("local_stocks") or {}

        local_restock_ids = []

        for site_id in site["local_stores"]:
            old_store = old_local.get(site_id) or {}
            new_store = new_local.get(site_id) or {}

            old_stock = old_store.get("stock")
            new_stock = new_store.get("stock")

            if (
                old_stock is not None
                and new_stock is not None
                and safe_int(old_stock, 0) <= 0
                and safe_int(new_stock, 0) > 0
            ):
                local_restock_ids.append(site_id)

        old_online = max(
            0,
            safe_int(
                old.get("online_count"),
                0
            )
        )

        new_online = max(
            0,
            safe_int(
                product.get("online_count"),
                0
            )
        )

        online_restock = (
            old_online <= 0
            and new_online > 0
        )

        if local_restock_ids or online_restock:
            if local_restock_ids and online_restock:
                title = f"🔥 **[POKÉMON] {label} RESTOCK**"
            elif local_restock_ids:
                if len(local_restock_ids) == 1:
                    store_name = site["local_stores"][local_restock_ids[0]]
                    title = (
                        f"🏪 **[POKÉMON] {store_name.upper()} RESTOCK**"
                    )
                else:
                    title = (
                        f"🏪 **[POKÉMON] {label} LOKAL RESTOCK**"
                    )
            else:
                title = (
                    f"🌐 **[POKÉMON] {label} ONLINE RESTOCK**"
                )

            transition_lines = []

            for site_id, default_name in site["local_stores"].items():
                old_store = old_local.get(site_id) or {}
                new_store = new_local.get(site_id) or {}
                store_name = (
                    new_store.get("name")
                    or old_store.get("name")
                    or default_name
                )
                old_stock = old_store.get("stock")
                new_stock = new_store.get("stock")

                if site_id in local_restock_ids:
                    transition_lines.append(
                        f"🏪 {store_name}: "
                        f"{safe_int(old_stock, 0)} → "
                        f"**{safe_int(new_stock, 0)} stk.**"
                    )
                else:
                    transition_lines.append(
                        f"🏪 {store_name}: "
                        f"{format_local_stock(new_stock)}"
                    )

            if online_restock:
                transition_lines.append(
                    f"🌐 Online: {old_online} → "
                    f"**{new_online} stk.**"
                )
            else:
                transition_lines.append(
                    f"🌐 Online: {new_online} stk."
                )

            transition_lines.append(
                "🇩🇰 Butikker med lager: "
                f"{product.get('store_count', 0)}"
            )

            transition_lines.append(
                f"💰 {format_price(product.get('price'))}"
            )

            quantity_limit = product.get("quantity_limit")

            if quantity_limit is not None:
                transition_lines.append(
                    f"👤 Max pr. kunde: {quantity_limit}"
                )

            send_discord(
                f"{title}\n"
                f"**{product['name']}**\n"
                + "\n".join(transition_lines)
                + f"\n🔗 {product['url']}"
            )

        old_price = old.get("price")
        new_price = product.get("price")

        if (
            old_price is not None
            and new_price is not None
            and new_price < old_price
        ):
            send_discord(
                f"💰 **[POKÉMON] {label} PRISFALD**\n"
                f"**{product['name']}**\n"
                f"{format_price(old_price)} → "
                f"**{format_price(new_price)}**\n"
                f"{salling_status_lines(site_key, product)}\n"
                f"🔗 {product['url']}"
            )


# =========================================================
# ELGIGANTEN ÆNDRINGER
# =========================================================

def format_elgiganten_stock(store):
    if not store:
        return "0 stk."

    display = str(store.get("display", "0"))

    if display in ("", "None"):
        display = "0"

    return f"{display} stk."


def elgiganten_status_lines(product):
    local_stocks = product.get("local_stocks") or {}
    kolding = local_stocks.get(ELGIGANTEN_KOLDING_STORE_ID) or {}
    esbjerg = local_stocks.get(ELGIGANTEN_ESBJERG_STORE_ID) or {}

    lines = [
        f"🏪 Elgiganten Kolding: {format_elgiganten_stock(kolding)}",
        f"🏪 Elgiganten Esbjerg: {format_elgiganten_stock(esbjerg)}",
        f"🌐 Online: {product.get('online_display', '0')} stk.",
        f"🇩🇰 Butikker med lager: {product.get('store_count', 0)}",
        f"💰 {format_price(product.get('price'))}"
    ]

    quantity_text = product.get("quantity_text")

    if quantity_text:
        lines.append(f"👤 {quantity_text}")

    return "\n".join(lines)


def process_elgiganten_changes(old_products, new_products):
    new_products = filter_restock_alert_products(new_products, "POKÉMON")

    for product_id, product in new_products.items():
        if product_id not in old_products:
            send_discord(
                "🆕 **[POKÉMON] NYT PÅ ELGIGANTEN**\n"
                f"**{product['name']}**\n"
                f"{elgiganten_status_lines(product)}\n"
                f"🔗 {product['url']}"
            )

    for product_id, product in new_products.items():
        if product_id not in old_products:
            continue

        old = old_products[product_id]
        old_local = old.get("local_stocks") or {}
        new_local = product.get("local_stocks") or {}

        local_restock_ids = []

        for store_id in (
            ELGIGANTEN_KOLDING_STORE_ID,
            ELGIGANTEN_ESBJERG_STORE_ID
        ):
            old_store = old_local.get(store_id) or {}
            new_store = new_local.get(store_id) or {}

            if (
                not old_store.get("in_stock", False)
                and new_store.get("in_stock", False)
            ):
                local_restock_ids.append(store_id)

        online_restock = (
            not old.get("online_stock", False)
            and product.get("online_stock", False)
        )

        if local_restock_ids or online_restock:
            if local_restock_ids and online_restock:
                title = "🔥 **[POKÉMON] ELGIGANTEN RESTOCK**"
            elif len(local_restock_ids) == 1:
                store_id = local_restock_ids[0]
                store_name = (
                    "ELGIGANTEN KOLDING"
                    if store_id == ELGIGANTEN_KOLDING_STORE_ID
                    else "ELGIGANTEN ESBJERG"
                )
                title = f"🏪 **[POKÉMON] {store_name} RESTOCK**"
            elif local_restock_ids:
                title = "🏪 **[POKÉMON] ELGIGANTEN LOKAL RESTOCK**"
            else:
                title = "🌐 **[POKÉMON] ELGIGANTEN ONLINE RESTOCK**"

            transition_lines = []

            for store_id, store_name in (
                (ELGIGANTEN_KOLDING_STORE_ID, "Elgiganten Kolding"),
                (ELGIGANTEN_ESBJERG_STORE_ID, "Elgiganten Esbjerg")
            ):
                old_store = old_local.get(store_id) or {}
                new_store = new_local.get(store_id) or {}

                if store_id in local_restock_ids:
                    transition_lines.append(
                        f"🏪 {store_name}: "
                        f"{format_elgiganten_stock(old_store)} → "
                        f"**{format_elgiganten_stock(new_store)}**"
                    )
                else:
                    transition_lines.append(
                        f"🏪 {store_name}: "
                        f"{format_elgiganten_stock(new_store)}"
                    )

            if online_restock:
                transition_lines.append(
                    "🌐 Online: "
                    f"{old.get('online_display', '0')} stk. → "
                    f"**{product.get('online_display', '0')} stk.**"
                )
            else:
                transition_lines.append(
                    f"🌐 Online: {product.get('online_display', '0')} stk."
                )

            transition_lines.append(
                "🇩🇰 Butikker med lager: "
                f"{product.get('store_count', 0)}"
            )
            transition_lines.append(
                f"💰 {format_price(product.get('price'))}"
            )

            quantity_text = product.get("quantity_text")

            if quantity_text:
                transition_lines.append(f"👤 {quantity_text}")

            send_discord(
                f"{title}\n"
                f"**{product['name']}**\n"
                + "\n".join(transition_lines)
                + f"\n🔗 {product['url']}"
            )

        old_price = old.get("price")
        new_price = product.get("price")

        if (
            old_price is not None
            and new_price is not None
            and new_price < old_price
        ):
            send_discord(
                "💰 **[POKÉMON] ELGIGANTEN PRISFALD**\n"
                f"**{product['name']}**\n"
                f"{format_price(old_price)} → "
                f"**{format_price(new_price)}**\n"
                f"{elgiganten_status_lines(product)}\n"
                f"🔗 {product['url']}"
            )


# =========================================================
# SHOPIFY ÆNDRINGER
# =========================================================

def shopify_status_lines(product):
    availability = "På lager" if product.get("in_stock") else "Udsolgt"

    lines = [
        f"📦 {availability}",
        f"💰 {format_price(product.get('price'))}"
    ]

    if product.get("preorder"):
        lines.append("📅 Forudbestilling/preorder")

    return "\n".join(lines)


def process_shopify_changes(site_key, old_products, new_products):
    new_products = filter_restock_alert_products(new_products)
    site = SHOPIFY_SITES[site_key]
    label = site["label"]

    # Nye produkter
    for product_id, product in new_products.items():
        if product_id in old_products:
            continue

        game = product.get("game", "TCG")

        if product.get("preorder"):
            headline = f"🚨 **[{game}] NY FORUDBESTILLING HOS {label}**"
        else:
            headline = f"🆕 **[{game}] NYT FUNDET HOS {label}**"

        send_discord(
            f"{headline}\n"
            f"**{product['name']}**\n"
            f"{shopify_status_lines(product)}\n"
            f"🔗 {product['url']}"
        )

    # Restocks + prisfald
    for product_id, product in new_products.items():
        if product_id not in old_products:
            continue

        old = old_products[product_id]
        game = product.get("game", old.get("game", "TCG"))

        if (
            not old.get("in_stock", False)
            and product.get("in_stock", False)
        ):
            send_discord(
                f"🔥 **[{game}] {label} RESTOCK**\n"
                f"**{product['name']}**\n"
                "📦 Udsolgt → **På lager**\n"
                f"💰 {format_price(product.get('price'))}\n"
                f"🔗 {product['url']}"
            )

        old_price = old.get("price")
        new_price = product.get("price")

        if (
            old_price is not None
            and new_price is not None
            and new_price < old_price
        ):
            send_discord(
                f"💰 **[{game}] {label} PRISFALD**\n"
                f"**{product['name']}**\n"
                f"{format_price(old_price)} → "
                f"**{format_price(new_price)}**\n"
                f"📦 {'På lager' if product.get('in_stock') else 'Udsolgt'}\n"
                f"🔗 {product['url']}"
            )


# =========================================================
# WOOCOMMERCE ÆNDRINGER
# =========================================================

def woocommerce_status_lines(product):
    availability = "På lager" if product.get("in_stock") else "Udsolgt"

    lines = [
        f"📦 {availability}",
        f"💰 {format_price(product.get('price'))}"
    ]

    if product.get("preorder"):
        lines.append("📅 Forudbestilling/preorder")

    return "\n".join(lines)


def process_woocommerce_changes(site_key, old_products, new_products):
    new_products = filter_restock_alert_products(new_products)
    site = WOOCOMMERCE_SITES[site_key]
    label = site["label"]

    # Nye produkter
    for product_id, product in new_products.items():
        if product_id in old_products:
            continue

        game = product.get("game", "TCG")

        if product.get("preorder"):
            headline = f"🚨 **[{game}] NY FORUDBESTILLING HOS {label}**"
        else:
            headline = f"🆕 **[{game}] NYT HOS {label}**"

        send_discord(
            f"{headline}\n"
            f"**{product['name']}**\n"
            f"{woocommerce_status_lines(product)}\n"
            f"🔗 {product['url']}"
        )

    # Restocks + prisfald
    for product_id, product in new_products.items():
        if product_id not in old_products:
            continue

        old = old_products[product_id]
        game = product.get("game", old.get("game", "TCG"))

        if (
            not old.get("in_stock", False)
            and product.get("in_stock", False)
        ):
            send_discord(
                f"🔥 **[{game}] {label} RESTOCK**\n"
                f"**{product['name']}**\n"
                "📦 Udsolgt → **På lager**\n"
                f"💰 {format_price(product.get('price'))}\n"
                f"🔗 {product['url']}"
            )

        old_price = old.get("price")
        new_price = product.get("price")

        if (
            old_price is not None
            and new_price is not None
            and new_price < old_price
        ):
            send_discord(
                f"💰 **[{game}] {label} PRISFALD**\n"
                f"**{product['name']}**\n"
                f"{format_price(old_price)} → "
                f"**{format_price(new_price)}**\n"
                f"📦 {'På lager' if product.get('in_stock') else 'Udsolgt'}\n"
                f"🔗 {product['url']}"
            )



# =========================================================
# NEXT LEVEL GAMES ÆNDRINGER
# =========================================================

def process_nextlevel_changes(old_products, current_products):
    current_products = filter_restock_alert_products(current_products)
    label = "NEXT LEVEL GAMES"

    for product_id, product in current_products.items():
        old = old_products.get(product_id)

        if old is None:
            if product.get("preorder"):
                headline = (
                    f"🚨 **[{product['game']}] NY FORUDBESTILLING HOS {label}**"
                )
            else:
                headline = f"🆕 **[{product['game']}] NYT HOS {label}**"

            send_discord(
                f"{headline}\n"
                f"**{product['name']}**\n"
                f"{nextlevel_status_lines(product)}\n"
                f"🔗 {product['url']}"
            )
            continue

        if (
            not old.get("preorder", False)
            and product.get("preorder", False)
        ):
            send_discord(
                f"🚨 **[{product['game']}] NY FORUDBESTILLING HOS {label}**\n"
                f"**{product['name']}**\n"
                f"{nextlevel_status_lines(product)}\n"
                f"🔗 {product['url']}"
            )

        if (
            not old.get("in_stock", False)
            and product.get("in_stock", False)
        ):
            send_discord(
                f"🔥 **[{product['game']}] {label} RESTOCK**\n"
                f"**{product['name']}**\n"
                f"📦 **PÅ LAGER**\n"
                f"💰 {format_price(product.get('price'))}\n"
                f"🔗 {product['url']}"
            )

        old_price = old.get("price")
        new_price = product.get("price")

        if (
            old_price is not None
            and new_price is not None
            and new_price < old_price
        ):
            send_discord(
                f"💰 **[{product['game']}] {label} PRISFALD**\n"
                f"**{product['name']}**\n"
                f"{format_price(old_price)} → **{format_price(new_price)}**\n"
                f"🔗 {product['url']}"
            )


# =========================================================
# EPIC PANDA ÆNDRINGER
# =========================================================

def process_epicpanda_changes(
    old_products,
    new_products
):
    new_products = filter_restock_alert_products(new_products)
    label = "EPIC PANDA"

    # Nye produkter / nye preorders
    for product_id, product in new_products.items():
        if product_id in old_products:
            continue

        game = product.get(
            "game",
            "TCG"
        )

        if product.get(
            "preorder"
        ):
            headline = (
                f"🚨 **[{game}] NY FORUDBESTILLING HOS {label}**"
            )
        else:
            headline = (
                f"🆕 **[{game}] NYT HOS {label}**"
            )

        send_discord(
            f"{headline}\n"
            f"**{product['name']}**\n"
            f"{epicpanda_status_lines(product)}\n"
            f"🔗 {product['url']}"
        )

    # Restocks + prisfald
    for product_id, product in new_products.items():
        if product_id not in old_products:
            continue

        old = old_products[
            product_id
        ]

        game = product.get(
            "game",
            old.get(
                "game",
                "TCG"
            )
        )

        if (
            not old.get(
                "in_stock",
                False
            )
            and product.get(
                "in_stock",
                False
            )
        ):
            old_status = old.get(
                "status",
                "UDSOLGT"
            )

            send_discord(
                f"🔥 **[{game}] {label} RESTOCK**\n"
                f"**{product['name']}**\n"
                f"📦 {old_status} → **PÅ LAGER**\n"
                f"💰 {format_price(product.get('price'))}\n"
                f"🔗 {product['url']}"
            )

        old_price = old.get(
            "price"
        )

        new_price = product.get(
            "price"
        )

        if (
            old_price is not None
            and new_price is not None
            and new_price < old_price
        ):
            send_discord(
                f"💰 **[{game}] {label} PRISFALD**\n"
                f"**{product['name']}**\n"
                f"{format_price(old_price)} → "
                f"**{format_price(new_price)}**\n"
                f"📦 {product.get('status', 'UKENDT')}\n"
                f"🔗 {product['url']}"
            )


# =========================================================
# STEFFEN-O ÆNDRINGER
# =========================================================

def process_steffeno_changes(
    old_products,
    new_products
):
    new_products = filter_restock_alert_products(new_products, "POKÉMON")
    label = "STEFFEN-O"

    # Nye produkter / nye preorders
    for product_id, product in new_products.items():
        if product_id in old_products:
            continue

        if product.get(
            "preorder"
        ):
            headline = (
                "🚨 **[POKÉMON] NY FORUDBESTILLING HOS STEFFEN-O**"
            )

        else:
            headline = (
                "🆕 **[POKÉMON] NYT HOS STEFFEN-O**"
            )

        send_discord(
            f"{headline}\n"
            f"**{product['name']}**\n"
            f"{steffeno_status_lines(product)}\n"
            f"🔗 {product['url']}"
        )

    # Restocks + prisfald
    for product_id, product in new_products.items():
        if product_id not in old_products:
            continue

        old = old_products[
            product_id
        ]

        old_stock = old.get(
            "stock"
        )

        new_stock = product.get(
            "stock"
        )

        old_in_stock = old.get(
            "in_stock",
            False
        )

        new_in_stock = product.get(
            "in_stock",
            False
        )

        if (
            not old_in_stock
            and new_in_stock
        ):
            if (
                old_stock is not None
                and new_stock is not None
            ):
                stock_line = (
                    f"📦 {old_stock} → "
                    f"**{new_stock} stk.**"
                )

            elif new_stock is not None:
                stock_line = (
                    f"📦 **{new_stock} stk. på lager**"
                )

            else:
                stock_line = (
                    "📦 **PÅ LAGER**"
                )

            send_discord(
                f"🔥 **[POKÉMON] {label} RESTOCK**\n"
                f"**{product['name']}**\n"
                f"{stock_line}\n"
                f"💰 {format_price(product.get('price'))}\n"
                f"🔗 {product['url']}"
            )

        old_price = old.get(
            "price"
        )

        new_price = product.get(
            "price"
        )

        if (
            old_price is not None
            and new_price is not None
            and new_price < old_price
        ):
            stock_text = (
                f"{new_stock} stk."
                if new_stock is not None
                else product.get(
                    "status",
                    "UKENDT"
                )
            )

            send_discord(
                f"💰 **[POKÉMON] {label} PRISFALD**\n"
                f"**{product['name']}**\n"
                f"{format_price(old_price)} → "
                f"**{format_price(new_price)}**\n"
                f"📦 {stock_text}\n"
                f"🔗 {product['url']}"
            )


# =========================================================
# START
# =========================================================

print("========================================")
print("Pokemon + Lorcana Restock Bot")
print("========================================")
if RUN_ONCE:
    print(
        "GitHub Actions mode: kører ét scan og afslutter."
    )
else:
    print(
        f"Tjekker Coolshop + Proshop + BR + Bilka + Føtex + Elgiganten "
        f"+ PokeHulen + Rogerz + MTGwebshop + Luckbox + Spilforsyningen "
        f"+ Musen & Slottet + Symbizon + CardX + Matraws + Halmes Hule "
        f"+ CardsDirect + Baltzer Games + TCG Shoppen + Pokemons.dk "
        f"+ Pocket Monster + Fun-shop + PokéPulls + Staalz + PBCards + KoCardz "
        f"+ Nostalgic + &Cards + Pokecards.dk + Epic Panda + Steffen-O "
        f"+ Next Level Games hvert {CHECK_EVERY}. sekund."
    )
print()


state = load_state()

if isinstance(state, dict):
    RESTOCK_ALERT_MEMORY = _alert_memory_cleanup(
        state.get("_restock_alert_memory") or {}
    )
    PRICE_ALERT_MEMORY = _alert_memory_cleanup(
        state.get("_price_alert_memory") or {}
    )

# Persist the public Elgiganten signed Algolia key between GitHub Action
# runs. Without this, process-memory cache resets every five minutes.
if isinstance(state, dict):
    saved_elgiganten_cache = state.get(
        "_elgiganten_key_cache"
    )

    if isinstance(saved_elgiganten_cache, dict):
        cached_api_key = saved_elgiganten_cache.get("api_key")
        cached_valid_until = safe_int(
            saved_elgiganten_cache.get("valid_until"),
            0
        )
        cached_retry_after = safe_int(
            saved_elgiganten_cache.get("retry_after"),
            0
        )
        cached_rate_limit_failures = safe_int(
            saved_elgiganten_cache.get("rate_limit_failures"),
            0
        )

        if cached_api_key:
            ELGIGANTEN_KEY_CACHE["api_key"] = cached_api_key
            ELGIGANTEN_KEY_CACHE["valid_until"] = cached_valid_until

        # The cooldown is just as important as the key. Without hydrating it,
        # every short-lived GitHub runner repeats the same rate-limited call.
        ELGIGANTEN_KEY_CACHE["retry_after"] = cached_retry_after
        ELGIGANTEN_KEY_CACHE[
            "rate_limit_failures"
        ] = cached_rate_limit_failures


# =========================================================
# FØRSTE KØRSEL
# =========================================================

while state is None:
    try:
        print(
            "Opretter første baseline..."
        )

        coolshop = (
            get_coolshop_products()
        )

        proshop = (
            get_proshop_products()
        )

        br = get_br_products()

        bilka = get_salling_products("bilka")

        foetex = get_salling_products("foetex")

        elgiganten = get_elgiganten_products()

        shopify = {}

        for site_key in SHOPIFY_SITES:
            shopify[site_key] = get_shopify_products(site_key)

        woocommerce = {}

        for site_key in WOOCOMMERCE_SITES:
            woocommerce[site_key] = get_woocommerce_products(site_key)

        epicpanda = get_epicpanda_products()

        steffeno = get_steffeno_products()

        nextlevel = get_nextlevel_products()

        pokemon_count = sum(
            1
            for product
            in coolshop.values()
            if product["game"]
            == "POKÉMON"
        )

        lorcana_count = sum(
            1
            for product
            in coolshop.values()
            if product["game"]
            == "LORCANA"
        )

        br_kolding_count = sum(
            1
            for product in br.values()
            if (
                product.get("kolding_stock")
                is not None
                and product.get("kolding_stock") > 0
            )
        )

        br_esbjerg_count = sum(
            1
            for product in br.values()
            if (
                product.get("esbjerg_stock")
                is not None
                and product.get("esbjerg_stock") > 0
            )
        )

        bilka_local_counts = count_salling_local_products(
            "bilka",
            bilka
        )

        foetex_local_counts = count_salling_local_products(
            "foetex",
            foetex
        )

        elgiganten_local_counts = count_elgiganten_local_products(
            elgiganten
        )

        state = {
            "coolshop": coolshop,
            "proshop": proshop,
            "br": br,
            "bilka": bilka,
            "foetex": foetex,
            "elgiganten": elgiganten,
            "shopify": shopify,
            "woocommerce": woocommerce,
            "epicpanda": epicpanda,
            "steffeno": steffeno,
            "nextlevel": nextlevel,
            "_source_health": {},
            "_restock_alert_memory": RESTOCK_ALERT_MEMORY,
            "_price_alert_memory": PRICE_ALERT_MEMORY,
            "_elgiganten_key_cache": dict(ELGIGANTEN_KEY_CACHE)
        }

        save_state(
            state
        )

        print(
            f"Coolshop Pokémon: "
            f"{pokemon_count}"
        )

        print(
            f"Coolshop Lorcana: "
            f"{lorcana_count}"
        )

        print(
            f"Proshop Pokémon: "
            f"{len(proshop)}"
        )

        print(
            f"BR Pokémon TCG: "
            f"{len(br)}"
        )

        print(
            f"BR Kolding på lager: "
            f"{br_kolding_count} produkter"
        )

        print(
            f"BR Esbjerg på lager: "
            f"{br_esbjerg_count} produkter"
        )

        print(
            f"Bilka Pokémon TCG: {len(bilka)}"
        )

        print(
            "Bilka Kolding på lager: "
            f"{bilka_local_counts.get('1662', 0)} produkter"
        )

        print(
            "Bilka Esbjerg på lager: "
            f"{bilka_local_counts.get('1659', 0)} produkter"
        )

        print(
            f"Føtex Pokémon TCG: {len(foetex)}"
        )

        print(
            "føtex Kolding på lager: "
            f"{foetex_local_counts.get('1307', 0)} produkter"
        )

        print(
            "føtex Kolding Syd på lager: "
            f"{foetex_local_counts.get('1370', 0)} produkter"
        )

        print(
            "føtex Esbjerg Broen på lager: "
            f"{foetex_local_counts.get('1223', 0)} produkter"
        )

        print(
            f"Elgiganten Pokémon TCG: {len(elgiganten)}"
        )

        print(
            "Elgiganten Kolding på lager: "
            f"{elgiganten_local_counts.get('3003', 0)} produkter"
        )

        print(
            "Elgiganten Esbjerg på lager: "
            f"{elgiganten_local_counts.get('3022', 0)} produkter"
        )

        for site_key, products in shopify.items():
            counts = count_shopify_products(products)
            label = SHOPIFY_SITES[site_key]["label"]
            print(
                f"{label}: {counts['POKÉMON']} Pokémon | "
                f"{counts['LORCANA']} Lorcana | "
                f"på lager {counts['POKÉMON_STOCK'] + counts['LORCANA_STOCK']}"
            )

        for site_key, products in woocommerce.items():
            counts = count_woocommerce_products(products)
            label = WOOCOMMERCE_SITES[site_key]["label"]
            print(
                f"{label}: {counts['POKÉMON']} Pokémon | "
                f"{counts['LORCANA']} Lorcana | "
                f"på lager {counts['POKÉMON_STOCK'] + counts['LORCANA_STOCK']}"
            )

        epic_counts = count_epicpanda_products(epicpanda)
        print(
            f"EPIC PANDA: {epic_counts['POKÉMON']} Pokémon | "
            f"{epic_counts['LORCANA']} Lorcana | "
            f"på lager "
            f"{epic_counts['POKÉMON_STOCK'] + epic_counts['LORCANA_STOCK']} | "
            f"preorders {epic_counts['PREORDER']}"
        )

        steffeno_counts = count_steffeno_products(
            steffeno
        )

        print(
            f"STEFFEN-O: {steffeno_counts['POKÉMON']} Pokémon | "
            f"på lager {steffeno_counts['POKÉMON_STOCK']} | "
            f"preorders {steffeno_counts['PREORDER']}"
        )

        nextlevel_counts = count_nextlevel_products(nextlevel)

        print(
            f"NEXT LEVEL GAMES: {nextlevel_counts['POKÉMON']} Pokémon | "
            f"{nextlevel_counts['LORCANA']} Lorcana | "
            f"på lager "
            f"{nextlevel_counts['POKÉMON_STOCK'] + nextlevel_counts['LORCANA_STOCK']} | "
            f"preorders {nextlevel_counts['PREORDER']}"
        )

        print(
            "Baseline gemt."
        )

        send_discord(
            "🟢 **Restock Bot aktiv**\n"
            f"⚡ Coolshop Pokémon: {pokemon_count}\n"
            f"✨ Coolshop Lorcana: {lorcana_count}\n"
            f"⚡ Proshop Pokémon: {len(proshop)}\n"
            f"🏪 BR Pokémon TCG: {len(br)}\n"
            f"📍 BR Kolding: {br_kolding_count} | Esbjerg: {br_esbjerg_count}\n"
            f"🏪 Bilka Pokémon TCG: {len(bilka)}\n"
            f"📍 Bilka Kolding: {bilka_local_counts.get('1662', 0)} | "
            f"Esbjerg: {bilka_local_counts.get('1659', 0)}\n"
            f"🏪 Føtex Pokémon TCG: {len(foetex)}\n"
            f"📍 føtex Kolding: {foetex_local_counts.get('1307', 0)} | "
            f"Kolding Syd: {foetex_local_counts.get('1370', 0)} | "
            f"Esbjerg Broen: {foetex_local_counts.get('1223', 0)}\n"
            f"🏪 Elgiganten Pokémon TCG: {len(elgiganten)}\n"
            f"📍 Elgiganten Kolding: {elgiganten_local_counts.get('3003', 0)} | "
            f"Esbjerg: {elgiganten_local_counts.get('3022', 0)}\n"
            + "".join(
                f"🛒 {SHOPIFY_SITES[key]['label']}: "
                f"{count_shopify_products(products)['POKÉMON']} Pokémon | "
                f"{count_shopify_products(products)['LORCANA']} Lorcana\n"
                for key, products in shopify.items()
            )
            + "".join(
                f"🛒 {WOOCOMMERCE_SITES[key]['label']}: "
                f"{count_woocommerce_products(products)['POKÉMON']} Pokémon | "
                f"{count_woocommerce_products(products)['LORCANA']} Lorcana\n"
                for key, products in woocommerce.items()
            )
            + (
                f"🛒 EPIC PANDA: {count_epicpanda_products(epicpanda)['POKÉMON']} "
                f"Pokémon | {count_epicpanda_products(epicpanda)['LORCANA']} Lorcana\n"
            )
            + (
                f"🛒 STEFFEN-O: {count_steffeno_products(steffeno)['POKÉMON']} "
                f"Pokémon\n"
            )
            + (
                f"🛒 NEXT LEVEL GAMES: {count_nextlevel_products(nextlevel)['POKÉMON']} "
                f"Pokémon | {count_nextlevel_products(nextlevel)['LORCANA']} Lorcana\n"
            )
            + f"⏱️ Tjekker hvert {CHECK_EVERY}. sekund."
        )

        if RUN_ONCE:
            print(
                "Baseline oprettet. GitHub-run afsluttes."
            )
            raise SystemExit(0)

    except KeyboardInterrupt:
        print(
            "\nBot stoppet."
        )
        exit()

    except Exception as error:
        print(
            "Fejl under baseline:",
            error
        )

        if RUN_ONCE:
            raise

        print(
            f"Prøver igen om {CHECK_EVERY} sekunder..."
        )

        time.sleep(
            CHECK_EVERY
        )


# =========================================================
# NORMAL OVERVÅGNING
# =========================================================

while True:
    try:
        new_state = dict(state)
        price_watch_fresh_sources = set()
        price_watch_nextlevel_live = None

        # -------------------------
        # COOLSHOP
        # -------------------------

        try:
            old_coolshop = state.get("coolshop", {})
            coolshop = fetch_source_products(
                "coolshop",
                old_coolshop,
                get_coolshop_products,
                new_state,
            )

            pokemon_count = sum(
                1
                for product
                in coolshop.values()
                if product["game"]
                == "POKÉMON"
            )

            lorcana_count = sum(
                1
                for product
                in coolshop.values()
                if product["game"]
                == "LORCANA"
            )

            print(
                f"COOLSHOP: "
                f"{pokemon_count} Pokémon | "
                f"{lorcana_count} Lorcana"
            )

            process_coolshop_changes(
                old_coolshop,
                coolshop
            )

            new_state[
                "coolshop"
            ] = coolshop

            price_watch_fresh_sources.add(
                "coolshop"
            )

        except Exception as error:
            print(
                "Coolshop fejl:",
                error
            )

        # -------------------------
        # PROSHOP
        # -------------------------

        try:
            old_proshop = state.get("proshop", {})
            proshop = fetch_source_products(
                "proshop",
                old_proshop,
                get_proshop_products,
                new_state,
            )

            print(
                f"PROSHOP: "
                f"{len(proshop)} Pokémon"
            )

            process_proshop_changes(
                old_proshop,
                proshop
            )

            new_state[
                "proshop"
            ] = proshop

            price_watch_fresh_sources.add(
                "proshop"
            )

        except Exception as error:
            print(
                "Proshop fejl:",
                error
            )

        # -------------------------
        # BR
        # -------------------------

        try:
            br_was_initialized = (
                "br" in state
            )

            old_br = state.get(
                "br",
                {}
            )

            br = fetch_source_products(
                "br",
                old_br,
                lambda: get_br_products(old_products=old_br),
                new_state,
            )

            br_kolding_count = sum(
                1
                for product in br.values()
                if (
                    product.get("kolding_stock")
                    is not None
                    and product.get("kolding_stock") > 0
                )
            )

            br_esbjerg_count = sum(
                1
                for product in br.values()
                if (
                    product.get("esbjerg_stock")
                    is not None
                    and product.get("esbjerg_stock") > 0
                )
            )

            print(
                f"BR: {len(br)} Pokémon TCG | "
                f"Kolding {br_kolding_count} | "
                f"Esbjerg {br_esbjerg_count}"
            )

            if br_was_initialized:
                process_br_changes(
                    old_br,
                    br
                )

            else:
                print(
                    "BR baseline tilføjet uden historiske alerts."
                )

                send_discord(
                    "🟢 **BR overvågning aktiveret**\n"
                    f"⚡ Pokémon TCG: {len(br)} produkter\n"
                    f"📍 BR Kolding: {br_kolding_count} produkter\n"
                    f"📍 BR Esbjerg: {br_esbjerg_count} produkter\n"
                    "🌐 Online lager + nationalt butikstal overvåges også."
                )

            new_state[
                "br"
            ] = br

            price_watch_fresh_sources.add(
                "br"
            )

        except Exception as error:
            print(
                "BR fejl:",
                error
            )

        # -------------------------
        # BILKA
        # -------------------------

        try:
            bilka_was_initialized = (
                "bilka" in state
            )

            old_bilka = state.get(
                "bilka",
                {}
            )

            bilka = fetch_source_products(
                "bilka",
                old_bilka,
                lambda: get_salling_products(
                    "bilka",
                    old_products=old_bilka,
                ),
                new_state,
            )

            bilka_local_counts = count_salling_local_products(
                "bilka",
                bilka
            )

            print(
                f"BILKA: {len(bilka)} Pokémon TCG | "
                f"Kolding {bilka_local_counts.get('1662', 0)} | "
                f"Esbjerg {bilka_local_counts.get('1659', 0)}"
            )

            if bilka_was_initialized:
                process_salling_changes(
                    "bilka",
                    old_bilka,
                    bilka
                )

            else:
                print(
                    "Bilka baseline tilføjet uden historiske alerts."
                )

                send_discord(
                    "🟢 **Bilka overvågning aktiveret**\n"
                    f"⚡ Pokémon TCG: {len(bilka)} produkter\n"
                    f"📍 Bilka Kolding: "
                    f"{bilka_local_counts.get('1662', 0)} produkter\n"
                    f"📍 Bilka Esbjerg: "
                    f"{bilka_local_counts.get('1659', 0)} produkter\n"
                    "🌐 Online lager + nationalt butikstal overvåges også."
                )

            new_state[
                "bilka"
            ] = bilka

            price_watch_fresh_sources.add(
                "bilka"
            )

        except Exception as error:
            print(
                "Bilka fejl:",
                error
            )

        # -------------------------
        # FOETEX
        # -------------------------

        try:
            foetex_was_initialized = (
                "foetex" in state
            )

            old_foetex = state.get(
                "foetex",
                {}
            )

            foetex = fetch_source_products(
                "foetex",
                old_foetex,
                lambda: get_salling_products(
                    "foetex",
                    old_products=old_foetex,
                ),
                new_state,
            )

            foetex_local_counts = count_salling_local_products(
                "foetex",
                foetex
            )

            print(
                f"FØTEX: {len(foetex)} Pokémon TCG | "
                f"Kolding {foetex_local_counts.get('1307', 0)} | "
                f"Kolding Syd {foetex_local_counts.get('1370', 0)} | "
                f"Esbjerg Broen {foetex_local_counts.get('1223', 0)}"
            )

            if foetex_was_initialized:
                process_salling_changes(
                    "foetex",
                    old_foetex,
                    foetex
                )

            else:
                print(
                    "Føtex baseline tilføjet uden historiske alerts."
                )

                send_discord(
                    "🟢 **Føtex overvågning aktiveret**\n"
                    f"⚡ Pokémon TCG: {len(foetex)} produkter\n"
                    f"📍 føtex Kolding: "
                    f"{foetex_local_counts.get('1307', 0)} produkter\n"
                    f"📍 føtex Kolding Syd: "
                    f"{foetex_local_counts.get('1370', 0)} produkter\n"
                    f"📍 føtex Esbjerg Broen: "
                    f"{foetex_local_counts.get('1223', 0)} produkter\n"
                    "🌐 Online lager + nationalt butikstal overvåges også."
                )

            new_state[
                "foetex"
            ] = foetex

            price_watch_fresh_sources.add(
                "foetex"
            )

        except Exception as error:
            print(
                "Føtex fejl:",
                error
            )

        # -------------------------
        # ELGIGANTEN - RETIRED V25
        # -------------------------

        # Public product pages, signed Algolia and the anonymous orchestrator
        # are all blocked/rate-limited from the runner. Preserve historical
        # data, but make no network calls and never expose stale Elgiganten
        # prices/stock as live signals.
        old_elgiganten = state.get("elgiganten", {})
        new_state["elgiganten"] = old_elgiganten
        _source_health_update(
            new_state,
            "elgiganten",
            status="retired",
            consecutive_failures=0,
            last_error="Retired V25: no reliable public live-stock path",
            observed_count=len(old_elgiganten) if isinstance(old_elgiganten, dict) else 0,
        )
        print(
            "ELGIGANTEN: retired fra aktiv scanning; historisk state bevares "
            "og bruges ikke i Price Watch/History."
        )

        # -------------------------
        # SHOPIFY-WEBSHOPS
        # -------------------------

        old_shopify_all = state.get("shopify", {})
        new_shopify_all = dict(old_shopify_all)

        for site_key, site in SHOPIFY_SITES.items():
            try:
                was_initialized = site_key in old_shopify_all
                old_products = old_shopify_all.get(site_key, {})
                products = fetch_source_products(
                    site_key,
                    old_products,
                    lambda site_key=site_key: get_shopify_products(site_key),
                    new_state,
                )
                counts = count_shopify_products(products)

                print(
                    f"{site['label']}: "
                    f"{counts['POKÉMON']} Pokémon | "
                    f"{counts['LORCANA']} Lorcana | "
                    f"på lager "
                    f"{counts['POKÉMON_STOCK'] + counts['LORCANA_STOCK']}"
                )

                if was_initialized:
                    process_shopify_changes(
                        site_key,
                        old_products,
                        products
                    )
                else:
                    print(
                        f"{site['label']} baseline tilføjet "
                        "uden historiske alerts."
                    )

                    send_discord(
                        f"🟢 **{site['label']} overvågning aktiveret**\n"
                        f"⚡ Pokémon: {counts['POKÉMON']} produkter "
                        f"({counts['POKÉMON_STOCK']} på lager)\n"
                        f"✨ Lorcana: {counts['LORCANA']} produkter "
                        f"({counts['LORCANA_STOCK']} på lager)\n"
                        "🆕 Nye produkter, restocks, preorders og "
                        "prisfald overvåges."
                    )

                new_shopify_all[site_key] = products
                price_watch_fresh_sources.add(
                    site_key
                )

            except Exception as error:
                print(
                    f"{site['label']} fejl:",
                    error
                )

        new_state["shopify"] = new_shopify_all

        # -------------------------
        # WOOCOMMERCE-WEBSHOPS
        # -------------------------

        old_woocommerce_all = state.get("woocommerce", {})
        new_woocommerce_all = {
            key: value
            for key, value in old_woocommerce_all.items()
            if key in WOOCOMMERCE_SITES
        }

        for site_key, site in WOOCOMMERCE_SITES.items():
            try:
                was_initialized = site_key in old_woocommerce_all
                old_products = old_woocommerce_all.get(site_key, {})
                products = fetch_source_products(
                    site_key,
                    old_products,
                    lambda site_key=site_key: get_woocommerce_products(site_key),
                    new_state,
                )
                counts = count_woocommerce_products(products)
                scope_expansion = (
                    site_key == "pokecards"
                    and 0 < len(old_products) <= WOOCOMMERCE_PAGE_SIZE
                    and len(products) >= len(old_products) * 3
                )

                print(
                    f"{site['label']}: "
                    f"{counts['POKÉMON']} Pokémon | "
                    f"{counts['LORCANA']} Lorcana | "
                    f"på lager "
                    f"{counts['POKÉMON_STOCK'] + counts['LORCANA_STOCK']}"
                )

                if was_initialized and not scope_expansion:
                    process_woocommerce_changes(
                        site_key,
                        old_products,
                        products
                    )
                elif scope_expansion:
                    print(
                        f"{site['label']} fuld katalogbaseline: "
                        f"{len(old_products)} → {len(products)} produkter; "
                        "historiske produkt-alerts undertrykkes."
                    )

                    send_discord(
                        f"🟢 **{site['label']} fuld katalogdækning aktiveret**\n"
                        f"⚡ Pokémon: {counts['POKÉMON']} produkter "
                        f"({counts['POKÉMON_STOCK']} på lager)\n"
                        "Historiske produkter blev indlæst som baseline uden "
                        "produkt-alerts."
                    )
                else:
                    print(
                        f"{site['label']} baseline tilføjet "
                        "uden historiske alerts."
                    )

                    send_discord(
                        f"🟢 **{site['label']} overvågning aktiveret**\n"
                        f"⚡ Pokémon: {counts['POKÉMON']} produkter "
                        f"({counts['POKÉMON_STOCK']} på lager)\n"
                        f"✨ Lorcana: {counts['LORCANA']} produkter "
                        f"({counts['LORCANA_STOCK']} på lager)\n"
                        "🆕 Nye produkter, restocks, preorders og "
                        "prisfald overvåges."
                    )

                new_woocommerce_all[site_key] = products
                price_watch_fresh_sources.add(
                    site_key
                )

            except Exception as error:
                print(
                    f"{site['label']} fejl:",
                    error
                )

        new_state["woocommerce"] = new_woocommerce_all

        # -------------------------
        # EPIC PANDA
        # -------------------------

        try:
            epicpanda_was_initialized = (
                "epicpanda" in state
            )

            old_epicpanda = state.get(
                "epicpanda",
                {}
            )

            epicpanda = fetch_source_products(
                "epicpanda",
                old_epicpanda,
                get_epicpanda_products,
                new_state,
            )
            epic_counts = count_epicpanda_products(
                epicpanda
            )

            print(
                f"EPIC PANDA: {epic_counts['POKÉMON']} Pokémon | "
                f"{epic_counts['LORCANA']} Lorcana | "
                f"på lager "
                f"{epic_counts['POKÉMON_STOCK'] + epic_counts['LORCANA_STOCK']} | "
                f"preorders {epic_counts['PREORDER']}"
            )

            if epicpanda_was_initialized:
                process_epicpanda_changes(
                    old_epicpanda,
                    epicpanda
                )

            else:
                print(
                    "EPIC PANDA baseline tilføjet "
                    "uden historiske alerts."
                )

                send_discord(
                    "🟢 **EPIC PANDA overvågning aktiveret**\n"
                    f"⚡ Pokémon: {epic_counts['POKÉMON']} produkter "
                    f"({epic_counts['POKÉMON_STOCK']} på lager)\n"
                    f"✨ Lorcana: {epic_counts['LORCANA']} produkter "
                    f"({epic_counts['LORCANA_STOCK']} på lager)\n"
                    f"🚨 Aktuelle preorders: {epic_counts['PREORDER']}\n"
                    "🆕 Nye produkter, restocks, preorders og "
                    "prisfald overvåges."
                )

            new_state[
                "epicpanda"
            ] = epicpanda

            price_watch_fresh_sources.add(
                "epicpanda"
            )

        except Exception as error:
            print(
                "EPIC PANDA fejl:",
                error
            )

        # -------------------------
        # STEFFEN-O
        # -------------------------

        try:
            steffeno_was_initialized = (
                "steffeno" in state
            )

            old_steffeno = state.get(
                "steffeno",
                {}
            )

            steffeno = fetch_source_products(
                "steffeno",
                old_steffeno,
                get_steffeno_products,
                new_state,
            )

            steffeno_counts = count_steffeno_products(
                steffeno
            )

            print(
                f"STEFFEN-O: {steffeno_counts['POKÉMON']} Pokémon | "
                f"på lager {steffeno_counts['POKÉMON_STOCK']} | "
                f"preorders {steffeno_counts['PREORDER']}"
            )

            if steffeno_was_initialized:
                process_steffeno_changes(
                    old_steffeno,
                    steffeno
                )

            else:
                print(
                    "STEFFEN-O baseline tilføjet "
                    "uden historiske alerts."
                )

                send_discord(
                    "🟢 **STEFFEN-O overvågning aktiveret**\n"
                    f"⚡ Pokémon: {steffeno_counts['POKÉMON']} produkter "
                    f"({steffeno_counts['POKÉMON_STOCK']} på lager)\n"
                    "📦 Eksakt lagerantal overvåges.\n"
                    "🆕 Nye produkter, restocks og prisfald overvåges."
                )

            new_state[
                "steffeno"
            ] = steffeno

            price_watch_fresh_sources.add(
                "steffeno"
            )

        except Exception as error:
            print(
                "STEFFEN-O fejl:",
                error
            )

        # -------------------------
        # NEXT LEVEL GAMES
        # -------------------------

        try:
            nextlevel_was_initialized = "nextlevel" in state
            old_nextlevel = state.get("nextlevel", {})
            current_nextlevel = fetch_source_products(
                "nextlevel",
                old_nextlevel,
                get_nextlevel_products,
                new_state,
            )
            price_watch_nextlevel_live = current_nextlevel
            nextlevel_counts = count_nextlevel_products(current_nextlevel)

            print(
                f"NEXT LEVEL GAMES: {nextlevel_counts['POKÉMON']} Pokémon | "
                f"{nextlevel_counts['LORCANA']} Lorcana | "
                f"på lager "
                f"{nextlevel_counts['POKÉMON_STOCK'] + nextlevel_counts['LORCANA_STOCK']} | "
                f"preorders {nextlevel_counts['PREORDER']}"
            )

            if nextlevel_was_initialized:
                process_nextlevel_changes(
                    old_nextlevel,
                    current_nextlevel
                )

                # Behold gamle produkter, hvis en kategori midlertidigt skjuler
                # dem. Det forhindrer falske "nyt produkt" alerts ved comeback.
                merged_nextlevel = {
                    **old_nextlevel,
                    **current_nextlevel
                }
            else:
                print(
                    "NEXT LEVEL GAMES baseline tilføjet uden historiske alerts."
                )

                send_discord(
                    "🟢 **NEXT LEVEL GAMES overvågning aktiveret**\n"
                    f"⚡ Pokémon: {nextlevel_counts['POKÉMON']} produkter "
                    f"({nextlevel_counts['POKÉMON_STOCK']} på lager)\n"
                    f"✨ Lorcana: {nextlevel_counts['LORCANA']} produkter "
                    f"({nextlevel_counts['LORCANA_STOCK']} på lager)\n"
                    f"🚨 Aktuelle preorders: {nextlevel_counts['PREORDER']}\n"
                    "🆕 Nye produkter, restocks, preorders og prisfald overvåges."
                )

                merged_nextlevel = current_nextlevel

            new_state["nextlevel"] = merged_nextlevel
            price_watch_fresh_sources.add(
                "nextlevel"
            )

        except Exception as error:
            print(
                "NEXT LEVEL GAMES fejl:",
                error
            )


        # -------------------------
        # CARDSTORECPH - RETIRED
        # -------------------------

        old_cardstore = state.get("cardstorecph", {})
        new_state["cardstorecph"] = old_cardstore
        _source_health_update(
            new_state,
            "cardstorecph",
            status="retired",
            consecutive_failures=0,
            last_error=(
                "Retired V30: shoppen er primært enkeltkort og gav 0 "
                "relevante sealed produkter"
            ),
            observed_count=(
                len(old_cardstore)
                if isinstance(old_cardstore, dict)
                else 0
            ),
        )
        print(
            "CARDSTORECPH: retired fra aktiv scanning; primært enkeltkort, "
            "historisk state bevares."
        )

        # -------------------------
        # PRICE WATCH V3
        # -------------------------

        price_watch_current_state = dict(
            new_state
        )

        if price_watch_nextlevel_live is not None:
            price_watch_current_state[
                "nextlevel"
            ] = price_watch_nextlevel_live

        new_state["price_watch"] = process_price_watch(
            state.get("price_watch"),
            price_watch_current_state,
            price_watch_fresh_sources
        )

        # -------------------------
        # PRICE HISTORY V1
        # -------------------------

        try:
            new_state["price_history"] = process_price_history(
                state.get("price_history"),
                price_watch_current_state,
                price_watch_fresh_sources
            )
        except Exception as error:
            # Price History er et ekstra dashboard og må aldrig blokere
            # lagring af restock- eller Price Watch-state. Ellers sendes
            # dagens Price Watch igen ved næste femminutterskørsel.
            print("PRICE HISTORY fejl (isoleret):", error)
            failed_history = dict(state.get("price_history") or {})

            try:
                failed_today = datetime.now(
                    ZoneInfo(PRICE_WATCH_TIMEZONE)
                ).date().isoformat()
            except Exception:
                failed_today = datetime.now(
                    ZoneInfo("Europe/Copenhagen")
                ).date().isoformat()

            failed_history["last_daily_attempt_date"] = failed_today
            failed_history["last_error"] = str(error)[:500]
            failed_history["last_error_at"] = datetime.now(
                ZoneInfo("UTC")
            ).isoformat()
            new_state["price_history"] = failed_history

        # -------------------------
        # GEM STATE
        # -------------------------

        new_state["_elgiganten_key_cache"] = dict(
            ELGIGANTEN_KEY_CACHE
        )
        new_state["_restock_alert_memory"] = _alert_memory_cleanup(
            RESTOCK_ALERT_MEMORY
        )
        new_state["_price_alert_memory"] = _alert_memory_cleanup(
            PRICE_ALERT_MEMORY
        )

        save_state(
            new_state
        )

        state = new_state

        print(
            "Scan færdig.\n"
        )

    except KeyboardInterrupt:
        print(
            "\nBot stoppet."
        )
        break

    except Exception as error:
        print(
            "Generel fejl:",
            error
        )

        if RUN_ONCE:
            raise

    if RUN_ONCE:
        print(
            "GitHub scan afsluttet."
        )
        break

    time.sleep(
        CHECK_EVERY
    )
