from pathlib import Path
import re

PATH = Path("restock_bot_github.py")
text = PATH.read_text(encoding="utf-8")

MARKER = "KOCARDZ_ANCHOR_PARSER_V34 = True"

if MARKER in text:
    print("V34 KoCardz anchor parser already applied")
    raise SystemExit(0)


def replace_once(old, new, label):
    global text
    if old not in text:
        raise RuntimeError(f"V34 patch failed: marker not found for {label}")
    text = text.replace(old, new, 1)


replace_once(
    '''WAVE3_RETAILERS_V31 = True
WAVE3_SOURCE_FIX_V33 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    '''WAVE3_RETAILERS_V31 = True
WAVE3_SOURCE_FIX_V33 = True
KOCARDZ_ANCHOR_PARSER_V34 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    "V34 marker",
)

new_block = r'''
def _kocardz_anchor_name(anchor):
    name = woocommerce_clean_text(anchor.get_text(" ", strip=True))
    if name and name.lower() not in {
        "image", "se produkt", "laes mere", "læs mere", "foej til kurv", "føj til kurv"
    }:
        return name

    image = anchor.find("img", alt=True)
    if image:
        alt = woocommerce_clean_text(image.get("alt"))
        if len(alt) >= 4:
            return alt

    node = anchor.parent
    for _ in range(4):
        if node is None:
            break
        for selector in ("h2", "h3", ".product-title", ".wd-entities-title"):
            title_node = node.select_one(selector)
            if title_node:
                title = woocommerce_clean_text(title_node.get_text(" ", strip=True))
                if len(title) >= 4:
                    return title
        node = node.parent

    return ""


def _kocardz_product_links(node):
    links = set()
    for child in node.find_all("a", href=True):
        href = urljoin("https://www.kocardz.dk", child.get("href"))
        href = href.split("#", 1)[0].split("?", 1)[0]
        if "/vare/" in href and "/vare-kategori/" not in href:
            links.add(href.rstrip("/") + "/")
    return links


def _kocardz_nearest_product_node(anchor, product_url):
    node = anchor
    best = anchor.parent or anchor

    for _ in range(9):
        node = node.parent
        if node is None:
            break

        links = _kocardz_product_links(node)
        if product_url not in links:
            continue

        if len(links) > 1:
            break

        best = node
        low = woocommerce_clean_text(node.get_text(" ", strip=True)).lower()
        if any(
            marker in low
            for marker in (
                "på lager", "pa lager", "udsolgt", "ikke på lager", "ikke pa lager",
                "kommer snart", "forudbestil", "føj til kurv", "foej til kurv", ",-", "kr."
            )
        ):
            return node

    return best


def _kocardz_price_from_text(value):
    text_value = woocommerce_clean_text(value)
    price_pattern = re.compile(
        r"kr\.?\s*(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:,\d{1,2})?)"
        r"|(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:,\d{1,2})?)\s*(?:,-|kr\.?|DKK)",
        flags=re.IGNORECASE,
    )

    values = []
    for match in price_pattern.finditer(text_value):
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


def get_kocardz_products():
    products = {}
    session = requests.Session()
    session.headers.update(
        {
            **BROWSER_HEADERS,
            "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
        }
    )

    for game, category_url in KOCARDZ_CATEGORY_FEEDS.items():
        seen_urls = set()

        for page in range(1, KOCARDZ_MAX_PAGES + 1):
            page_url = (
                category_url
                if page == 1
                else category_url.rstrip("/") + f"/page/{page}/"
            )
            response = session.get(page_url, timeout=30)
            if response.status_code == 404 and page > 1:
                break
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            anchors = []
            for anchor in soup.find_all("a", href=True):
                href = urljoin("https://www.kocardz.dk", anchor.get("href"))
                href = href.split("#", 1)[0].split("?", 1)[0]
                if "/vare/" not in href or "/vare-kategori/" in href:
                    continue
                product_url = href.rstrip("/") + "/"
                anchors.append((anchor, product_url))

            if not anchors:
                if page == 1:
                    raise RuntimeError(
                        f"KoCardz category parser fandt ingen produktlinks: {page_url}"
                    )
                break

            new_on_page = 0
            page_urls = set()

            for anchor, product_url in anchors:
                if product_url in seen_urls or product_url in page_urls:
                    continue

                name = _kocardz_anchor_name(anchor)
                if not name:
                    continue

                node = _kocardz_nearest_product_node(anchor, product_url)
                node_text = woocommerce_clean_text(node.get_text(" ", strip=True))
                low = node_text.lower()

                synthetic = {
                    "name": name,
                    "categories": [
                        {"name": "Pokemon" if game == "POKÉMON" else "Disney Lorcana"}
                    ],
                    "short_description": "",
                    "description": "",
                }
                if not woocommerce_is_relevant_sealed(synthetic):
                    page_urls.add(product_url)
                    continue

                preorder = any(
                    marker in low
                    for marker in (
                        "forudbestil", "forudbestilling", "preorder", "pre-order", "kommer snart"
                    )
                )
                explicit_out = (
                    "udsolgt" in low
                    or "ikke på lager" in low
                    or "ikke pa lager" in low
                )
                explicit_in = (
                    (
                        "på lager" in low
                        or "pa lager" in low
                        or "føj til kurv" in low
                        or "foej til kurv" in low
                    )
                    and not explicit_out
                    and not preorder
                )

                product_id = hashlib.sha256(product_url.encode("utf-8")).hexdigest()[:20]
                products[product_id] = {
                    "name": name,
                    "game": game,
                    "price": _kocardz_price_from_text(node_text),
                    "in_stock": explicit_in,
                    "preorder": preorder,
                    "url": product_url,
                }
                seen_urls.add(product_url)
                page_urls.add(product_url)
                new_on_page += 1

            if new_on_page == 0:
                break

    return products


def get_woocommerce_products(site_key):
'''

pattern = re.compile(
    r'''def get_kocardz_products\(\):\n.*?\n\ndef get_woocommerce_products\(site_key\):\n''',
    re.DOTALL,
)
# Use a callable replacement so backslashes inside the generated parser
# are treated literally instead of as re.sub replacement escapes.
text, count = pattern.subn(lambda match: new_block, text, count=1)
if count != 1:
    raise RuntimeError("V34 patch failed: KoCardz parser block not found")

PATH.write_text(text, encoding="utf-8")
print("Applied V34: KoCardz now parses product anchors instead of theme-specific card classes")
