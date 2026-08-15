import requests
import json
import time
import os
import re
import base64
import html
import unicodedata

from bs4 import BeautifulSoup
from urllib.parse import urljoin, unquote, urlencode


# =========================================================
# INDSTILLINGER
# =========================================================

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
PRICE_WATCH_WEBHOOK_URL = os.getenv("PRICE_WATCH_WEBHOOK_URL", "").strip()

RUN_ONCE = os.getenv("RUN_ONCE", "0").strip() == "1"
CHECK_EVERY = int(os.getenv("CHECK_EVERY", "300"))
STATE_FILE = "restock_state_v2.json"

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
ELGIGANTEN_ALGOLIA_APP_ID = "Z0FL7R8UBH"
ELGIGANTEN_ALGOLIA_INDEX = "commerce_b2c_OCDKELG"
ELGIGANTEN_KOLDING_STORE_ID = "3003"
ELGIGANTEN_ESBJERG_STORE_ID = "3022"

ELGIGANTEN_KEY_CACHE = {
    "api_key": None,
    "valid_until": 0
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

def send_discord(message):
    response = requests.post(
        WEBHOOK_URL,
        json={"content": message},
        headers={
            "User-Agent": "Pokemon-Lorcana-Restock-Bot/1.0"
        },
        timeout=20
    )

    response.raise_for_status()


def send_price_watch(message):
    if not PRICE_WATCH_WEBHOOK_URL:
        print("PRICE_WATCH_WEBHOOK_URL mangler - springer Price Watch-besked over.")
        return

    response = requests.post(
        PRICE_WATCH_WEBHOOK_URL,
        json={"content": message},
        headers={
            "User-Agent": "Pokemon-Lorcana-Price-Watch/1.0"
        },
        timeout=20
    )

    response.raise_for_status()



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
        

# ============================================================
# PRICE WATCH - PRODUKTTYPER
# ============================================================

def get_price_watch_type(name, game):
    text = (name or "").lower()

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

    # Bilka, Føtex og Elgiganten
    if source_key in ("bilka", "foetex", "elgiganten"):
        if product.get("online_stock"):
            return "ONLINE"

        local_stocks = product.get("local_stocks") or {}

        for store in local_stocks.values():
            if safe_int(store.get("stock")) > 0:
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


def collect_price_watch_candidates(current_state):
    candidates = []

    def add_products(shop, source_key, products, game_override=None):
        for product in (products or {}).values():
            name = product.get("name", "")
            game = game_override or product.get("game")

            if game not in ("POKÉMON", "LORCANA"):
                continue

            product_type = get_price_watch_type(name, game)

            if not product_type:
                continue

            price = product.get("price")

            if price is None or price <= 0:
                continue

            availability = get_price_watch_availability(
                source_key,
                product
            )

            if not availability:
                continue

            candidates.append({
                "shop": shop,
                "source": source_key,
                "game": game,
                "type": product_type,
                "name": name,
                "price": price,
                "availability": availability,
                "url": product.get("url", "")
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

    add_products(
        "ELGIGANTEN",
        "elgiganten",
        current_state.get("elgiganten", {}),
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


def get_proshop_products():
    response = requests.get(
        PROSHOP_URL,
        headers=BROWSER_HEADERS,
        timeout=20
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    products = {}

    cards = soup.select(
        "li.site-productlist-item"
    )

    for card in cards:
        link = card.find(
            "a",
            href=re.compile(
                r"/Pokemon/[^?#]+/\d+(?:[?#].*)?$",
                re.IGNORECASE
            )
        )

        if not link:
            continue

        href = link["href"]

        match = re.search(
            r"/(\d+)(?:[?#].*)?$",
            href
        )

        if not match:
            continue

        product_id = match.group(1)

        text = card.get_text(
            " ",
            strip=True
        )

        name = clean_proshop_name(
            href
        )

        price = parse_price(
            text
        )

        if "På lager" in text:
            stock = "PÅ LAGER"

        elif "Fjernlager" in text:
            stock = "FJERNLAGER"

        elif "Bestillingsvare" in text:
            stock = "BESTILLINGSVARE"

        else:
            stock = "UKENDT"

        url = urljoin(
            PROSHOP_BASE,
            href
        )

        products[product_id] = {
            "name": name,
            "price": price,
            "stock": stock,
            "url": url
        }

    return products


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
    valid_until = safe_int(
        ELGIGANTEN_KEY_CACHE.get("valid_until"),
        0
    )

    if (
        not force
        and cached_key
        and (valid_until == 0 or time.time() < valid_until - 120)
    ):
        return cached_key

    session = requests.Session()

    headers = {
        **BROWSER_HEADERS,
        "Accept": "application/json, text/plain, */*",
        "Referer": ELGIGANTEN_HOME
    }

    response = session.get(
        ELGIGANTEN_SIGNED_KEY_URL,
        headers=headers,
        timeout=20
    )

    # Hvis direkte kald bliver afvist, etabler browser-session først.
    if response.status_code in (401, 403):
        session.get(
            ELGIGANTEN_HOME,
            headers=BROWSER_HEADERS,
            timeout=20
        )

        response = session.get(
            ELGIGANTEN_SIGNED_KEY_URL,
            headers=headers,
            timeout=20
        )

    response.raise_for_status()

    data = response.json()
    api_key = data.get("apiKey")

    if not api_key:
        raise RuntimeError(
            "Elgiganten signed-api-key svarede uden apiKey."
        )

    ELGIGANTEN_KEY_CACHE["api_key"] = api_key
    ELGIGANTEN_KEY_CACHE["valid_until"] = (
        get_elgiganten_key_valid_until(api_key)
    )

    return api_key


def is_real_elgiganten_pokemon_tcg(product):
    title = (product.get("title") or "").lower()
    brand = (product.get("brand") or "").lower()

    # Mapper/bindere og lignende tilbehør skal ikke give restock-alerts.
    if brand == "ultrapro":
        return False

    blocked_words = (
        "binder",
        "mappe",
        "portfolio",
        "sleeve",
        "kortlommer"
    )

    if any(word in title for word in blocked_words):
        return False

    return True


def get_elgiganten_store_stock(product, store_id, store_name):
    department_stock = product.get("departmentStock") or {}
    stock_data = department_stock.get(store_id) or {}

    return {
        "name": store_name,
        "in_stock": bool(stock_data.get("inStock", False)),
        "display": str(stock_data.get("display", "0"))
    }


def get_elgiganten_products():
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

    if is_accessory and not is_sealed:
        return False

    return True


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
                "preorder": shopify_is_preorder(raw),
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


def fetch_woocommerce_category(base, category_id):
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

        if total_pages:
            try:
                if page >= int(total_pages):
                    break
            except ValueError:
                pass

        if len(page_products) < WOOCOMMERCE_PAGE_SIZE:
            break

    return list(collected.values())


def get_woocommerce_products(site_key):
    site = WOOCOMMERCE_SITES[site_key]
    products = {}

    for game, category_id in site["categories"].items():
        raw_products = fetch_woocommerce_category(
            site["base"],
            category_id
        )

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
        f"+ PokeHulen + Rogerz + MTGwebshop + Nostalgic + &Cards + Epic Panda "
        f"+ Steffen-O + Next Level Games hvert {CHECK_EVERY}. sekund."
    )
print()


state = load_state()


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
            "nextlevel": nextlevel
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

        # -------------------------
        # COOLSHOP
        # -------------------------

        try:
            coolshop = (
                get_coolshop_products()
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
                state.get(
                    "coolshop",
                    {}
                ),
                coolshop
            )

            new_state[
                "coolshop"
            ] = coolshop

        except Exception as error:
            print(
                "Coolshop fejl:",
                error
            )

        # -------------------------
        # PROSHOP
        # -------------------------

        try:
            proshop = (
                get_proshop_products()
            )

            print(
                f"PROSHOP: "
                f"{len(proshop)} Pokémon"
            )

            process_proshop_changes(
                state.get(
                    "proshop",
                    {}
                ),
                proshop
            )

            new_state[
                "proshop"
            ] = proshop

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

            br = get_br_products(
                old_products=old_br
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

            bilka = get_salling_products(
                "bilka",
                old_products=old_bilka
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

            foetex = get_salling_products(
                "foetex",
                old_products=old_foetex
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

        except Exception as error:
            print(
                "Føtex fejl:",
                error
            )

        # -------------------------
        # ELGIGANTEN
        # -------------------------

        try:
            elgiganten_was_initialized = (
                "elgiganten" in state
            )

            old_elgiganten = state.get(
                "elgiganten",
                {}
            )

            elgiganten = get_elgiganten_products()

            elgiganten_local_counts = (
                count_elgiganten_local_products(elgiganten)
            )

            print(
                f"ELGIGANTEN: {len(elgiganten)} Pokémon TCG | "
                f"Kolding {elgiganten_local_counts.get('3003', 0)} | "
                f"Esbjerg {elgiganten_local_counts.get('3022', 0)}"
            )

            if elgiganten_was_initialized:
                process_elgiganten_changes(
                    old_elgiganten,
                    elgiganten
                )

            else:
                print(
                    "Elgiganten baseline tilføjet uden historiske alerts."
                )

                send_discord(
                    "🟢 **Elgiganten overvågning aktiveret**\n"
                    f"⚡ Pokémon TCG: {len(elgiganten)} produkter\n"
                    f"📍 Elgiganten Kolding: "
                    f"{elgiganten_local_counts.get('3003', 0)} produkter\n"
                    f"📍 Elgiganten Esbjerg: "
                    f"{elgiganten_local_counts.get('3022', 0)} produkter\n"
                    "🌐 Online lager + nationalt butikstal overvåges også."
                )

            new_state[
                "elgiganten"
            ] = elgiganten

        except Exception as error:
            print(
                "Elgiganten fejl:",
                error
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
                products = get_shopify_products(site_key)
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
                products = get_woocommerce_products(site_key)
                counts = count_woocommerce_products(products)

                print(
                    f"{site['label']}: "
                    f"{counts['POKÉMON']} Pokémon | "
                    f"{counts['LORCANA']} Lorcana | "
                    f"på lager "
                    f"{counts['POKÉMON_STOCK'] + counts['LORCANA_STOCK']}"
                )

                if was_initialized:
                    process_woocommerce_changes(
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

                new_woocommerce_all[site_key] = products

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

            epicpanda = get_epicpanda_products()
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

            steffeno = get_steffeno_products()

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
            current_nextlevel = get_nextlevel_products()
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

        except Exception as error:
            print(
                "NEXT LEVEL GAMES fejl:",
                error
            )

        # -------------------------
        # PRICE WATCH TEST
        # -------------------------

        price_watch_candidates = collect_price_watch_candidates(
            new_state
        )

        pokemon_price_watch = sum(
            1
            for product in price_watch_candidates
            if product["game"] == "POKÉMON"
        )

        lorcana_price_watch = sum(
            1
            for product in price_watch_candidates
            if product["game"] == "LORCANA"
        )

        print(
            f"PRICE WATCH: "
            f"{pokemon_price_watch} Pokémon | "
            f"{lorcana_price_watch} Lorcana | "
            f"{len(price_watch_candidates)} prislinjer i alt"
        )

        # -------------------------
        # PRICE WATCH DIAGNOSTIK
        # -------------------------

        print("\n--- PRICE WATCH DIAGNOSTIK ---")

        diagnostic_groups = [
            ("POKÉMON", "ETB"),
            ("POKÉMON", "BOOSTER BOX"),
            ("POKÉMON", "BOOSTER BUNDLE"),
            ("POKÉMON", "BOOSTER PACK"),
            ("LORCANA", "BOOSTER BOX"),
            ("LORCANA", "BOOSTER BUNDLE"),
            ("LORCANA", "BOOSTER PACK"),
        ]

        for game, product_type in diagnostic_groups:
            matches = [
                product
                for product in price_watch_candidates
                if product["game"] == game
                and product["type"] == product_type
            ]

            matches.sort(
                key=lambda product: (
                    product["name"].lower(),
                    product["price"]
                )
            )

            print(
                f"\n{game} | {product_type} | "
                f"{len(matches)} prislinjer"
            )

            for product in matches[:10]:
                print(
                    f"  {format_price(product['price'])} | "
                    f"{product['shop']} | "
                    f"{product['name']}"
                )

        print("\n--- SLUT PRICE WATCH DIAGNOSTIK ---")

                # -------------------------
        # PRICE WATCH MATCH-TEST
        # -------------------------

        price_watch_groups = {}

        for product in price_watch_candidates:
            product_key = get_price_watch_product_key(product)

            if not product_key:
                continue

            price_watch_groups.setdefault(
                product_key,
                []
            ).append(product)

        matched_groups = []

        for product_key, products in price_watch_groups.items():
            shops = {
                product["shop"]
                for product in products
            }

            if len(shops) >= 2:
                matched_groups.append(
                    (
                        product_key,
                        products
                    )
                )

        matched_groups.sort(
            key=lambda item: item[0]
        )

        print(
            f"\nPRICE WATCH MATCH: "
            f"{len(price_watch_groups)} unikke produkter | "
            f"{len(matched_groups)} findes hos mindst 2 butikker"
        )

        print("\n--- PRICE WATCH MATCH-TEST ---")

        for product_key, products in matched_groups[:30]:
            print(
                f"\n{product_key}"
            )

            products_sorted = sorted(
                products,
                key=lambda product: product["price"]
            )

            for product in products_sorted:
                print(
                    f"  {format_price(product['price'])} | "
                    f"{product['shop']} | "
                    f"{product['name']}"
                )

        print("\n--- SLUT PRICE WATCH MATCH-TEST ---")


        # -------------------------
        # GEM STATE
        # -------------------------

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
