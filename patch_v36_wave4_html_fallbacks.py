from pathlib import Path
import re

PATH = Path("restock_bot_github.py")
text = PATH.read_text(encoding="utf-8")

MARKER = "WAVE4_HTML_FALLBACKS_V36 = True"

if MARKER in text:
    print("V36 Wave 4 HTML fallbacks already applied")
    raise SystemExit(0)


def replace_once(old, new, label):
    global text
    if old not in text:
        raise RuntimeError(f"V36 patch failed: marker not found for {label}")
    text = text.replace(old, new, 1)


replace_once(
    '''KOCARDZ_ANCHOR_PARSER_V34 = True
WAVE4_RETAILERS_V35 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    '''KOCARDZ_ANCHOR_PARSER_V34 = True
WAVE4_RETAILERS_V35 = True
WAVE4_HTML_FALLBACKS_V36 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    "V36 marker",
)

html_code = r'''

POKEMONPORTALEN_HTML_FEEDS = (
    ("https://pokemonportalen.dk/product-category/boosters", False),
    ("https://pokemonportalen.dk/product-category/booster-boxes", False),
    ("https://pokemonportalen.dk/product-category/booster-bundle", False),
    ("https://pokemonportalen.dk/product-category/elite-trainer-box", False),
    ("https://pokemonportalen.dk/product-category/pokemin-mini-tin-og-tins", False),
    ("https://pokemonportalen.dk/product-category/collection-box", False),
    ("https://pokemonportalen.dk/product-category/blisterpakker", False),
    ("https://pokemonportalen.dk/product-category/pokemon-forudbestilling", True),
)
TCGBRUUS_SEALED_URL = "https://tcgbruus.dk/product-category/pokemon/sealed_produkter/"


def _wave4_html_price(value):
    text_value = woocommerce_clean_text(value)
    pattern = re.compile(
        r"(?:DKK|kr\.?)\s*(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:,\d{1,2})?)"
        r"|(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:,\d{1,2})?)\s*(?:DKK|kr\.?)",
        flags=re.IGNORECASE,
    )
    values = []
    for match in pattern.finditer(text_value):
        raw = match.group(1) or match.group(2)
        if not raw:
            continue
        try:
            price = float(raw.replace(".", "").replace(",", "."))
        except ValueError:
            continue
        if price > 0:
            values.append(price)
    return values[-1] if values else None


def _wave4_html_product_rows(soup, base):
    rows = []
    seen = set()

    cards = soup.select("li.product, .products .product, .product-grid-item, .wd-product")
    for card in cards:
        link = card.select_one('a[href*="/product/"]')
        if not link:
            continue
        url = urljoin(base, link.get("href"))
        url = url.split("#", 1)[0].split("?", 1)[0].rstrip("/") + "/"
        if "/product/" not in url or url in seen:
            continue
        rows.append((card, link, url))
        seen.add(url)

    if rows:
        return rows

    for link in soup.find_all("a", href=True):
        url = urljoin(base, link.get("href"))
        url = url.split("#", 1)[0].split("?", 1)[0].rstrip("/") + "/"
        if "/product/" not in url or url in seen:
            continue

        node = link
        best = link.parent or link
        for _ in range(8):
            node = node.parent
            if node is None:
                break
            candidate_links = {
                (urljoin(base, a.get("href")).split("#", 1)[0].split("?", 1)[0].rstrip("/") + "/")
                for a in node.find_all("a", href=True)
                if "/product/" in urljoin(base, a.get("href"))
            }
            if url not in candidate_links:
                continue
            if len(candidate_links) > 1:
                break
            best = node
            low = woocommerce_clean_text(node.get_text(" ", strip=True)).lower()
            if any(marker in low for marker in ("dkk", "kr.", "på lager", "pa lager", "udsolgt", "tilføj til kurv", "tilfoj til kurv")):
                break

        rows.append((best, link, url))
        seen.add(url)

    return rows


def _wave4_html_name(card, link):
    for selector in (
        ".woocommerce-loop-product__title",
        ".wd-entities-title",
        ".product-title",
        "h2",
        "h3",
        "h4",
    ):
        node = card.select_one(selector)
        if node:
            name = woocommerce_clean_text(node.get_text(" ", strip=True))
            if len(name) >= 4:
                return name

    name = woocommerce_clean_text(link.get_text(" ", strip=True))
    if len(name) >= 4:
        return name

    image = link.find("img", alt=True)
    if image:
        name = woocommerce_clean_text(image.get("alt"))
        if len(name) >= 4:
            return name
    return ""


def _wave4_html_product_id(card, url):
    for class_name in card.get("class") or []:
        match = re.fullmatch(r"post-(\d+)", str(class_name))
        if match:
            return match.group(1)
    button = card.select_one("[data-product_id]")
    if button and button.get("data-product_id"):
        return str(button.get("data-product_id"))
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]


def _wave4_html_parse_page(url, force_preorder=False):
    response = requests.get(
        url,
        headers={
            **BROWSER_HEADERS,
            "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
        },
        timeout=30,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    products = {}

    for card, link, product_url in _wave4_html_product_rows(soup, url):
        name = _wave4_html_name(card, link)
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

        card_text = woocommerce_clean_text(card.get_text(" ", strip=True))
        low = card_text.lower()
        classes = " ".join(str(value).lower() for value in (card.get("class") or []))
        preorder = force_preorder or any(
            marker in low
            for marker in ("forudbestil", "forudbestilling", "preorder", "pre-order", "kommer snart")
        )
        explicit_out = (
            "outofstock" in classes
            or "udsolgt" in low
            or "ikke på lager" in low
            or "ikke pa lager" in low
        )
        explicit_in = (
            "instock" in classes
            or "på lager" in low
            or "pa lager" in low
            or "tilføj til kurv" in low
            or "tilfoj til kurv" in low
            or "add to cart" in low
        )
        in_stock = bool(explicit_in and not explicit_out and not preorder)

        product_id = _wave4_html_product_id(card, product_url)
        products[product_id] = {
            "name": name,
            "game": "POKÉMON",
            "price": _wave4_html_price(card_text),
            "in_stock": in_stock,
            "preorder": bool(preorder),
            "url": product_url,
        }

    return products


def get_pokemonportalen_html_products():
    products = {}
    for category_url, force_preorder in POKEMONPORTALEN_HTML_FEEDS:
        seen_count = 0
        for page in range(1, 8):
            page_url = category_url if page == 1 else category_url.rstrip("/") + f"/page/{page}/"
            try:
                page_products = _wave4_html_parse_page(page_url, force_preorder=force_preorder)
            except requests.HTTPError as error:
                if page > 1 and getattr(error.response, "status_code", None) == 404:
                    break
                raise
            if not page_products:
                break
            before = len(products)
            products.update(page_products)
            if len(products) == before or len(page_products) == seen_count:
                break
            seen_count = len(page_products)
    return products


def get_tcgbruus_html_products():
    return _wave4_html_parse_page(TCGBRUUS_SEALED_URL, force_preorder=False)
'''

replace_once(
    '''def get_woocommerce_products(site_key):
    if site_key == "kocardz":
        return get_kocardz_products()
    if site_key == "pokemonplaza":
        return get_pokemonplaza_products()

    site = WOOCOMMERCE_SITES[site_key]
''',
    html_code + '''\n\ndef get_woocommerce_products(site_key):
    if site_key == "kocardz":
        return get_kocardz_products()
    if site_key == "pokemonportalen":
        return get_pokemonportalen_html_products()
    if site_key == "tcgbruus":
        return get_tcgbruus_html_products()
    if site_key == "pokemonplaza":
        return get_pokemonplaza_products()

    site = WOOCOMMERCE_SITES[site_key]
''',
    "Wave 4 HTML dispatch",
)

PATH.write_text(text, encoding="utf-8")
print("Applied V36: Pokemonportalen and TCGBruuS use direct public sealed-category HTML")
