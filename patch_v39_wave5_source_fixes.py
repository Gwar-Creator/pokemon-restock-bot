from pathlib import Path
import re

PATH = Path("restock_bot_github.py")
text = PATH.read_text(encoding="utf-8")

MARKER = "WAVE5_SOURCE_FIXES_V39 = True"

if MARKER in text:
    print("V39 Wave 5 source fixes already applied")
    raise SystemExit(0)


def replace_once(old, new, label):
    global text
    if old not in text:
        raise RuntimeError(f"V39 patch failed: marker not found for {label}")
    text = text.replace(old, new, 1)


replace_once(
    '''TCGBRUUS_BROWSER_PARSER_V37 = True
WAVE5_RETAILERS_V38 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    '''TCGBRUUS_BROWSER_PARSER_V37 = True
WAVE5_RETAILERS_V38 = True
WAVE5_SOURCE_FIXES_V39 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    "V39 marker",
)

# ZZGames' dedicated collection is already scoped to Pokemon. A few official
# sealed products (for example character-named Premium Collections) do not
# contain the word Pokemon in title/vendor/tags, so add category context only
# for this source before running the normal sealed filter.
replace_once(
    '''            if not is_relevant_shopify_tcg(raw, game):
                continue

            product_id = str(raw.get("id", "")).strip()
''',
    '''            relevance_raw = raw
            if site_key == "zzgames":
                relevance_raw = dict(raw)
                tags = relevance_raw.get("tags") or []
                if not isinstance(tags, list):
                    tags = [tags]
                relevance_raw["tags"] = [*tags, "Pokemon"]

            if not is_relevant_shopify_tcg(relevance_raw, game):
                continue

            product_id = str(raw.get("id", "")).strip()
''',
    "ZZGames Pokemon collection context",
)

# Kelz0r can localise the buy button even when DKK is requested. Their current
# live pages use Swedish "Köp nu" for buyable products and "Meddela" when the
# item cannot be bought. Keep the existing out-of-stock markers and recognise
# the additional positive purchase labels.
replace_once(
    '''                explicit_in = any(marker in low for marker in (
                    "køb nu", "koeb nu", "læg i indkøbskurv", "laeg i indkoebskurv",
                    "læg i kurv", "laeg i kurv", "add to cart"
                ))
''',
    '''                explicit_in = any(marker in low for marker in (
                    "køb nu", "koeb nu", "köp nu", "kop nu", "buy now",
                    "læg i indkøbskurv", "laeg i indkoebskurv",
                    "læg i kurv", "laeg i kurv", "add to cart"
                ))
''',
    "Kelz0r localised stock button",
)

# Hyggeonkel exposes the correct data in its public category HTML, but each
# product appears through several anchors (image/title/read-more). V38 marked a
# URL as seen after the first weak anchor, which could discard the later title
# anchor and result in zero products. Group anchors by product URL first, then
# choose the strongest title and the nearest single-product container.
hyggeonkel_function = r'''
def get_hyggeonkel_products():
    products = {}
    seen_urls = set()
    session = requests.Session()
    session.headers.update(
        {
            **BROWSER_HEADERS,
            "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
        }
    )

    def is_product_url(value):
        return "/produkt/" in (value or "")

    def nearest_card(anchor, page_url, product_url):
        node = anchor
        best = anchor.parent or anchor

        for _ in range(10):
            node = node.parent
            if node is None:
                break

            links = set()
            for child in node.find_all("a", href=True):
                href = urljoin(page_url, child.get("href"))
                href = href.split("#", 1)[0].split("?", 1)[0].rstrip("/")
                if is_product_url(href):
                    links.add(href)

            if product_url not in links:
                continue
            if len(links) > 1:
                break

            best = node
            low = woocommerce_clean_text(node.get_text(" ", strip=True)).lower()
            if any(
                marker in low
                for marker in (
                    " kr", "på lager", "pa lager", "ikke på lager", "ikke pa lager",
                    "udsolgt", "læg i kurv", "laeg i kurv", "er på vej"
                )
            ):
                return node

        return best

    def best_name(anchors, card):
        candidates = []

        for selector in ("h2", "h3", "h4", ".product-title", ".product-name"):
            node = card.select_one(selector)
            if node:
                candidates.append(woocommerce_clean_text(node.get_text(" ", strip=True)))

        for anchor in anchors:
            candidates.append(woocommerce_clean_text(anchor.get_text(" ", strip=True)))
            image = anchor.find("img", alt=True)
            if image:
                candidates.append(woocommerce_clean_text(image.get("alt")))

        ignored = {
            "", "nyhed", "fri fragt", "læs mere", "laes mere", "se produkt",
            "læg i kurv", "laeg i kurv", "image"
        }
        candidates = [
            value for value in candidates
            if len(value) >= 4 and value.lower() not in ignored
        ]
        if not candidates:
            return ""

        # Prefer a descriptive Lorcana title; otherwise the longest useful text.
        candidates.sort(
            key=lambda value: (
                "lorcana" in value.lower(),
                any(marker in value.lower() for marker in (
                    "booster", "display", "collection", "trove", "gift", "starter", "quest"
                )),
                len(value),
            ),
            reverse=True,
        )
        return candidates[0]

    for page in range(1, 7):
        params = {
            "brand_filter": "ZLorcana",
            "isgoodprice": "false",
            "isinstock": "false",
            "onlynew": "false",
            "order": "newestfirst",
            "page": page,
        }
        response = session.get(HYGGEONKEL_LORCANA_URL, params=params, timeout=30)
        response.raise_for_status()
        page_url = response.url
        soup = BeautifulSoup(response.text, "html.parser")

        anchors_by_url = {}
        for anchor in soup.find_all("a", href=True):
            href = urljoin(page_url, anchor.get("href"))
            href = href.split("#", 1)[0].split("?", 1)[0].rstrip("/")
            if not is_product_url(href):
                continue
            anchors_by_url.setdefault(href, []).append(anchor)

        new_on_page = 0
        for product_url, anchors in anchors_by_url.items():
            if product_url in seen_urls:
                continue

            # Start from the anchor with the most descriptive text/image alt.
            anchor = max(
                anchors,
                key=lambda item: len(
                    woocommerce_clean_text(item.get_text(" ", strip=True))
                    + woocommerce_clean_text((item.find("img", alt=True) or {}).get("alt") if item.find("img", alt=True) else "")
                ),
            )
            card = nearest_card(anchor, page_url, product_url)
            name = best_name(anchors, card)
            seen_urls.add(product_url)

            if not name:
                continue
            if not woocommerce_is_relevant_sealed(_wave5_synthetic(name, "LORCANA")):
                continue

            card_text = woocommerce_clean_text(card.get_text(" ", strip=True))
            low = card_text.lower()
            preorder = any(
                marker in low
                for marker in (
                    "er på vej", "forventes på lager", "forudbestil", "forudbestilling",
                    "preorder", "pre-order"
                )
            )
            explicit_out = any(
                marker in low
                for marker in ("ikke på lager", "ikke pa lager", "udsolgt")
            )
            explicit_in = any(
                marker in low
                for marker in ("på lager", "pa lager", "læg i kurv", "laeg i kurv")
            )

            product_id = _wave5_stable_id("hyggeonkel", name, product_url)
            products[product_id] = _wave5_product(
                name,
                "LORCANA",
                _wave5_price(card_text),
                explicit_in and not explicit_out,
                preorder,
                product_url,
            )
            new_on_page += 1

        if not anchors_by_url or new_on_page == 0:
            break

    if not products:
        raise RuntimeError("Hyggeonkel parser fandt 0 relevante Lorcana sealed produkter")

    return products
'''

pattern = re.compile(
    r'''\ndef get_hyggeonkel_products\(\):\n.*?\n    return products\n\n\ndef get_woocommerce_products''',
    flags=re.DOTALL,
)
text, count = pattern.subn(
    lambda match: "\n" + hyggeonkel_function.strip("\n") + "\n\n\ndef get_woocommerce_products",
    text,
    count=1,
)
if count != 1:
    raise RuntimeError(f"V39 patch failed: Hyggeonkel function replacement count={count}")

PATH.write_text(text, encoding="utf-8")
print("Applied V39: ZZGames context, Kelz0r stock labels, Hyggeonkel grouped-anchor parser")
