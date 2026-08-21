from pathlib import Path

PATH = Path("restock_bot_github.py")
text = PATH.read_text(encoding="utf-8")

MARKER = "WAVE5_RETAILERS_V38 = True"

if MARKER in text:
    print("V38 Wave 5 retailers already applied")
    raise SystemExit(0)


def replace_once(old, new, label):
    global text
    if old not in text:
        raise RuntimeError(f"V38 patch failed: marker not found for {label}")
    text = text.replace(old, new, 1)


replace_once(
    '''WAVE4_HTML_FALLBACKS_V36 = True
TCGBRUUS_BROWSER_PARSER_V37 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    '''WAVE4_HTML_FALLBACKS_V36 = True
TCGBRUUS_BROWSER_PARSER_V37 = True
WAVE5_RETAILERS_V38 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    "V38 marker",
)

replace_once(
    '''    "pokemonplaza": 5,
    "nostalgic": 5,
''',
    '''    "pokemonplaza": 5,
    "kelz0r": 20,
    "faraos": 5,
    "goblingames": 10,
    "zzgames": 3,
    "hyggeonkel": 5,
    "nostalgic": 5,
''',
    "Wave 5 source minimums",
)

replace_once(
    '''    "pokedexet": {
        "label": "POKEDEXET",
        "base": "https://pokedexet.dk",
        "feeds": [
            {"game": None, "path": "/collections/all/products.json"}
        ]
    }
}
''',
    '''    "pokedexet": {
        "label": "POKEDEXET",
        "base": "https://pokedexet.dk",
        "feeds": [
            {"game": None, "path": "/collections/all/products.json"}
        ]
    },
    "zzgames": {
        "label": "ZZGAMES",
        "base": "https://www.zzgames.dk",
        "feeds": [
            {"game": "POKÉMON", "path": "/collections/tcg-pokemon/products.json"}
        ]
    }
}
''',
    "ZZGames Shopify source",
)

replace_once(
    '''    "pokemonplaza": {
        "label": "POKEMON PLAZA",
        "base": "https://pokemonplaza.dk",
        "categories": {},
        "searches": {}
    },
}
''',
    '''    "pokemonplaza": {
        "label": "POKEMON PLAZA",
        "base": "https://pokemonplaza.dk",
        "categories": {},
        "searches": {}
    },
    "kelz0r": {
        "label": "KELZ0R",
        "base": "https://www.kelz0r.dk",
        "categories": {},
        "searches": {}
    },
    "faraos": {
        "label": "FARAOS",
        "base": "https://www.faraos.dk",
        "categories": {},
        "searches": {}
    },
    "goblingames": {
        "label": "GOBLIN GAMES",
        "base": "https://goblingames.dk",
        "categories": {},
        "searches": {}
    },
    "hyggeonkel": {
        "label": "HYGGEONKEL",
        "base": "https://www.hyggeonkel.dk",
        "categories": {},
        "searches": {}
    },
}
''',
    "Wave 5 custom sources",
)

wave5_code = r'''

# =========================================================
# WAVE 5 - CUSTOM PUBLIC CATEGORY PARSERS
# =========================================================

KELZ0R_FEEDS = (
    "https://www.kelz0r.dk/magic/pokemon-boosters-c-187_191.html?currency=DKK",
    "https://www.kelz0r.dk/magic/pokemon-tins-andet-c-187_457.html?currency=DKK",
)
FARAOS_FEEDS = (
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon"),
    ("LORCANA", "https://www.faraos.dk/games/kortspil/lorcana"),
)
GOBLINGAMES_POKEMON_URL = "https://goblingames.dk/pokmon-2365/"
HYGGEONKEL_LORCANA_URL = "https://www.hyggeonkel.dk/tcg/disney-lorcana/"


def _wave5_price(value):
    text_value = woocommerce_clean_text(value)

    # Faraos renders prices as e.g. "DKK 65 00".
    spaced = re.findall(r"\bDKK\s+(\d{1,5})\s+(\d{2})\b", text_value, flags=re.I)
    if spaced:
        kroner, ore = spaced[-1]
        return float(kroner) + float(ore) / 100.0

    matches = re.findall(
        r"(?:DKK|kr\.?)\s*(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:,\d{1,2})?)"
        r"|(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:,\d{1,2})?)\s*(?:DKK|kr\.?)",
        text_value,
        flags=re.I,
    )
    values = []
    for left, right in matches:
        raw = left or right
        if not raw:
            continue
        try:
            price = float(raw.replace(".", "").replace(",", "."))
        except ValueError:
            continue
        if price > 0:
            values.append(price)
    return values[-1] if values else None


def _wave5_synthetic(name, game):
    return {
        "name": name,
        "categories": [{"name": "Pokemon" if game == "POKÉMON" else "Disney Lorcana"}],
        "short_description": "",
        "description": "",
    }


def _wave5_stable_id(prefix, name, url):
    raw = f"{prefix}|{url}|{name}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:20]


def _wave5_anchor_name(anchor, card=None):
    card = card or anchor
    for selector in (
        ".product-name", ".product-title", ".product-item-name",
        "h2", "h3", "h4", "strong"
    ):
        node = card.select_one(selector)
        if node:
            name = woocommerce_clean_text(node.get_text(" ", strip=True))
            if len(name) >= 4:
                return name

    name = woocommerce_clean_text(anchor.get_text(" ", strip=True))
    if name and name.lower() not in {
        "se produktet", "se produkt", "læs mere", "laes mere", "køb nu", "koeb nu",
        "læg i kurv", "laeg i kurv", "notify", "meddela"
    }:
        return name

    image = anchor.find("img", alt=True)
    if image:
        alt = woocommerce_clean_text(image.get("alt"))
        if len(alt) >= 4:
            return alt
    return ""


def _wave5_nearest_card(anchor, link_matcher):
    node = anchor
    best = anchor.parent or anchor

    for _ in range(10):
        node = node.parent
        if node is None:
            break

        links = set()
        for child in node.find_all("a", href=True):
            href = urljoin(anchor.base_url if getattr(anchor, "base_url", None) else "", child.get("href"))
            if link_matcher(href):
                links.add(href.split("#", 1)[0].split("?", 1)[0].rstrip("/"))

        if len(links) > 1:
            break

        best = node
        low = woocommerce_clean_text(node.get_text(" ", strip=True)).lower()
        if any(
            marker in low
            for marker in (
                "dkk", " kr", "på lager", "pa lager", "ikke på lager", "ikke pa lager",
                "udsolgt", "læg i kurv", "laeg i kurv", "køb nu", "koeb nu",
                "meddela", "notify", "forudbestil", "preorder", "er på vej"
            )
        ):
            return node

    return best


def _wave5_product(name, game, price, in_stock, preorder, url):
    return {
        "name": name,
        "game": game,
        "price": price,
        "in_stock": bool(in_stock and not preorder),
        "preorder": bool(preorder),
        "url": url,
    }


def get_kelz0r_products():
    products = {}
    session = requests.Session()
    session.headers.update({**BROWSER_HEADERS, "Accept-Language": "da-DK,da;q=0.9,en;q=0.8"})

    def is_product_url(value):
        return bool(re.search(r"-p-\d+\.html(?:$|[?#])", value or "", flags=re.I))

    for base_url in KELZ0R_FEEDS:
        seen_page_urls = set()
        for page in range(1, 31):
            separator = "&" if "?" in base_url else "?"
            page_url = base_url if page == 1 else f"{base_url}{separator}page={page}"
            response = session.get(page_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            page_products = 0

            for anchor in soup.find_all("a", href=True):
                href = urljoin(page_url, anchor.get("href"))
                if not is_product_url(href):
                    continue
                product_url = href.split("#", 1)[0].split("?", 1)[0]
                if product_url in seen_page_urls:
                    continue

                card = _wave5_nearest_card(anchor, is_product_url)
                name = _wave5_anchor_name(anchor, card)
                if not name or not woocommerce_is_relevant_sealed(_wave5_synthetic(name, "POKÉMON")):
                    seen_page_urls.add(product_url)
                    continue

                card_text = woocommerce_clean_text(card.get_text(" ", strip=True))
                low = card_text.lower()
                preorder = any(marker in low for marker in (
                    "[preorder]", "preorder", "pre-order", "forudbestil", "forudbestilling",
                    "forhåndsbestilling", "forhandsbestilling"
                ))
                explicit_out = any(marker in low for marker in (
                    "meddela", "notify", "giv mig besked", "udsolgt", "ikke på lager", "ikke pa lager"
                ))
                explicit_in = any(marker in low for marker in (
                    "køb nu", "koeb nu", "læg i indkøbskurv", "laeg i indkoebskurv",
                    "læg i kurv", "laeg i kurv", "add to cart"
                ))

                product_id = _wave5_stable_id("kelz0r", name, product_url)
                products[product_id] = _wave5_product(
                    name, "POKÉMON", _wave5_price(card_text),
                    explicit_in and not explicit_out, preorder, product_url
                )
                seen_page_urls.add(product_url)
                page_products += 1

            if page_products == 0:
                break

    return products


def _faraos_cards(soup):
    # Faraos has no stable public API. Locate the smallest repeated container
    # that owns one price/status block; this is more robust than CSS class names.
    cards = []
    seen = set()
    price_nodes = soup.find_all(string=re.compile(r"\bDKK\b", flags=re.I))

    for price_node in price_nodes:
        node = price_node.parent
        best = None
        for _ in range(9):
            if node is None:
                break
            text_value = woocommerce_clean_text(node.get_text(" ", strip=True))
            dkk_count = len(re.findall(r"\bDKK\b", text_value, flags=re.I))
            if dkk_count > 2:
                break
            low = text_value.lower()
            if dkk_count >= 1 and any(marker in low for marker in (
                "på lager", "pa lager", "få på lager", "fa pa lager",
                "udsolgt", "varen kan kun købes i en butik", "varen kan kun koebes i en butik"
            )):
                best = node
            node = node.parent

        if best is not None and id(best) not in seen:
            cards.append(best)
            seen.add(id(best))

    return cards


def _faraos_name(card):
    for selector in ("h2", "h3", "h4", ".title", ".name", "a[href]"):
        for node in card.select(selector):
            name = woocommerce_clean_text(node.get_text(" ", strip=True))
            low = name.lower()
            if len(name) < 4 or low in {"email når på lager?", "email nar pa lager?", "se mere"}:
                continue
            if "dkk" in low or "lager" in low:
                continue
            return name

    text_value = woocommerce_clean_text(card.get_text(" ", strip=True))
    before_price = re.split(r"\bDKK\b", text_value, maxsplit=1, flags=re.I)[0].strip()
    return before_price[-180:].strip()


def get_faraos_products():
    products = {}
    session = requests.Session()
    session.headers.update({**BROWSER_HEADERS, "Accept-Language": "da-DK,da;q=0.9,en;q=0.8"})

    for game, category_url in FARAOS_FEEDS:
        response = session.get(category_url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        for card in _faraos_cards(soup):
            name = _faraos_name(card)
            if not name or not woocommerce_is_relevant_sealed(_wave5_synthetic(name, game)):
                continue

            card_text = woocommerce_clean_text(card.get_text(" ", strip=True))
            low = card_text.lower()
            preorder = any(marker in low for marker in (
                "forudbestil", "forudbestilling", "preorder", "pre-order"
            ))
            explicit_out = "udsolgt" in low
            store_only = (
                "varen kan kun købes i en butik" in low
                or "varen kan kun koebes i en butik" in low
            )
            explicit_in = (
                "på lager" in low
                or "pa lager" in low
                or "få på lager" in low
                or "fa pa lager" in low
            ) and not explicit_out and not store_only

            product_url = category_url
            for anchor in card.find_all("a", href=True):
                candidate = urljoin(category_url, anchor.get("href"))
                if candidate.rstrip("/") != category_url.rstrip("/"):
                    product_url = candidate
                    break

            product_id = _wave5_stable_id("faraos", name, product_url)
            products[product_id] = _wave5_product(
                name, game, _wave5_price(card_text), explicit_in, preorder, product_url
            )

    return products


def get_goblingames_products():
    products = {}
    response = requests.get(
        GOBLINGAMES_POKEMON_URL,
        headers={**BROWSER_HEADERS, "Accept-Language": "da-DK,da;q=0.9,en;q=0.8"},
        timeout=30,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    def is_product_url(value):
        return bool(re.search(r"-p\d+/?(?:$|[?#])", value or "", flags=re.I))

    seen_urls = set()
    for anchor in soup.find_all("a", href=True):
        href = urljoin(GOBLINGAMES_POKEMON_URL, anchor.get("href"))
        if not is_product_url(href):
            continue
        product_url = href.split("#", 1)[0].split("?", 1)[0]
        if product_url in seen_urls:
            continue

        card = _wave5_nearest_card(anchor, is_product_url)
        name = _wave5_anchor_name(anchor, card)
        if not name or not woocommerce_is_relevant_sealed(_wave5_synthetic(name, "POKÉMON")):
            seen_urls.add(product_url)
            continue

        card_text = woocommerce_clean_text(card.get_text(" ", strip=True))
        low = card_text.lower()
        preorder = any(marker in low for marker in ("pre-order", "preorder", "forudbestil"))
        explicit_in = bool(re.search(r"lager(?:\s+aarhus|\s+roskilde)?\s*:\s*(?:på|pa) lager", low))
        if "stk tilbage på lager" in low:
            explicit_in = True
        explicit_out = "lager: ikke på lager" in low and not explicit_in

        product_id = _wave5_stable_id("goblingames", name, product_url)
        products[product_id] = _wave5_product(
            name, "POKÉMON", _wave5_price(card_text),
            explicit_in and not explicit_out, preorder, product_url
        )
        seen_urls.add(product_url)

    return products


def get_hyggeonkel_products():
    products = {}
    seen_urls = set()
    session = requests.Session()
    session.headers.update({**BROWSER_HEADERS, "Accept-Language": "da-DK,da;q=0.9,en;q=0.8"})

    def is_product_url(value):
        return "/produkt/" in (value or "")

    for page in range(1, 6):
        separator = "&" if "?" in HYGGEONKEL_LORCANA_URL else "?"
        page_url = (
            HYGGEONKEL_LORCANA_URL
            if page == 1
            else f"{HYGGEONKEL_LORCANA_URL}{separator}page={page}"
        )
        response = session.get(page_url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        found = 0

        for anchor in soup.find_all("a", href=True):
            href = urljoin(page_url, anchor.get("href"))
            if not is_product_url(href):
                continue
            product_url = href.split("#", 1)[0].split("?", 1)[0].rstrip("/")
            if product_url in seen_urls:
                continue

            card = _wave5_nearest_card(anchor, is_product_url)
            name = _wave5_anchor_name(anchor, card)
            if not name or not woocommerce_is_relevant_sealed(_wave5_synthetic(name, "LORCANA")):
                seen_urls.add(product_url)
                continue

            card_text = woocommerce_clean_text(card.get_text(" ", strip=True))
            low = card_text.lower()
            preorder = any(marker in low for marker in (
                "er på vej", "forventes på lager", "forudbestil", "preorder", "pre-order"
            ))
            explicit_out = "ikke på lager" in low or "ikke pa lager" in low or "udsolgt" in low
            explicit_in = "på lager" in low or "pa lager" in low or "læg i kurv" in low or "laeg i kurv" in low

            product_id = _wave5_stable_id("hyggeonkel", name, product_url)
            products[product_id] = _wave5_product(
                name, "LORCANA", _wave5_price(card_text),
                explicit_in and not explicit_out, preorder, product_url
            )
            seen_urls.add(product_url)
            found += 1

        if found == 0:
            break

    return products
'''

# Insert parser code immediately before the generic WooCommerce dispatcher.
replace_once(
    '''def get_woocommerce_products(site_key):\n''',
    wave5_code + '''\n\ndef get_woocommerce_products(site_key):\n''',
    "Wave 5 parser code",
)

# Add custom dispatches before all existing special cases.
replace_once(
    '''def get_woocommerce_products(site_key):\n''',
    '''def get_woocommerce_products(site_key):\n    if site_key == "kelz0r":\n        return get_kelz0r_products()\n    if site_key == "faraos":\n        return get_faraos_products()\n    if site_key == "goblingames":\n        return get_goblingames_products()\n    if site_key == "hyggeonkel":\n        return get_hyggeonkel_products()\n''',
    "Wave 5 custom dispatch",
)

PATH.write_text(text, encoding="utf-8")
print("Applied V38 Wave 5: Kelz0r, Faraos, Goblin Games, ZZGames, Hyggeonkel")