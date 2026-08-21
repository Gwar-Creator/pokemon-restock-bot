from pathlib import Path

PATH = Path("restock_bot_github.py")
text = PATH.read_text(encoding="utf-8")

MARKER = "WAVE3_SOURCE_FIX_V33 = True"

if MARKER in text:
    print("V33 Wave 3 source fixes already applied")
    raise SystemExit(0)


def replace_once(old, new, label):
    global text
    if old not in text:
        raise RuntimeError(f"V33 patch failed: marker not found for {label}")
    text = text.replace(old, new, 1)


replace_once(
    '''CARDSTORECPH_RETIRED_V30 = True
WAVE3_RETAILERS_V31 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    '''CARDSTORECPH_RETIRED_V30 = True
WAVE3_RETAILERS_V31 = True
WAVE3_SOURCE_FIX_V33 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    "V33 marker",
)


staalz_code = r"""

STAALZ_HEADLESS_BASE = "https://staalz.dk"
STAALZ_RUNTIME_CACHE = None
STAALZ_STOREFRONT_API_VERSION = "2025-07"


def _staalz_runtime_candidates():
    global STAALZ_RUNTIME_CACHE

    if STAALZ_RUNTIME_CACHE is not None:
        return STAALZ_RUNTIME_CACHE

    response = requests.get(
        STAALZ_HEADLESS_BASE + "/",
        headers=BROWSER_HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    texts = [response.text]
    script_urls = []
    for script in soup.find_all("script", src=True):
        script_urls.append(urljoin(STAALZ_HEADLESS_BASE, script.get("src")))

    for script_url in list(dict.fromkeys(script_urls))[:18]:
        try:
            script_response = requests.get(
                script_url,
                headers=BROWSER_HEADERS,
                timeout=25,
            )
            if script_response.status_code != 200:
                continue
            if len(script_response.content) > 5_000_000:
                continue
            texts.append(script_response.text)
        except requests.RequestException:
            continue

    domains = []
    tokens = []
    domain_pattern = re.compile(
        r"([a-z0-9][a-z0-9-]*\.myshopify\.com)",
        flags=re.IGNORECASE,
    )
    token_patterns = (
        re.compile(
            r"(?:storefront[_-]?access[_-]?token|"
            r"x-shopify-storefront-access-token|"
            r"shopify[_-]?storefront[_-]?token)"
            r"[^A-Za-z0-9_-]{0,40}([A-Za-z0-9_-]{20,})",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"NEXT_PUBLIC_SHOPIFY_STOREFRONT_ACCESS_TOKEN"
            r"[^A-Za-z0-9_-]{0,40}([A-Za-z0-9_-]{20,})",
            flags=re.IGNORECASE,
        ),
    )

    for source_text in texts:
        for match in domain_pattern.findall(source_text):
            domain = match.lower()
            if domain not in domains:
                domains.append(domain)

        for pattern in token_patterns:
            for match in pattern.findall(source_text):
                token = str(match).strip()
                if token and token not in tokens:
                    tokens.append(token)

    STAALZ_RUNTIME_CACHE = {"domains": domains, "tokens": tokens}
    return STAALZ_RUNTIME_CACHE


def _staalz_storefront_raw_products(domain, token):
    endpoint = f"https://{domain}/api/{STAALZ_STOREFRONT_API_VERSION}/graphql.json"
    query = r'''
query ScannerProducts($cursor: String) @inContext(country: DK) {
  products(first: 100, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      handle
      title
      productType
      vendor
      tags
      variants(first: 100) {
        nodes {
          id
          availableForSale
          price { amount currencyCode }
        }
      }
    }
  }
}
'''

    raw_products = []
    cursor = None

    for _ in range(10):
        response = requests.post(
            endpoint,
            headers={
                **BROWSER_HEADERS,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Shopify-Storefront-Access-Token": token,
            },
            json={"query": query, "variables": {"cursor": cursor}},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            raise RuntimeError("Staalz Storefront API returned GraphQL errors")

        connection = (((payload.get("data") or {}).get("products")) or {})
        nodes = connection.get("nodes") or []

        for node in nodes:
            gid = str(node.get("id") or "")
            product_id = gid.rsplit("/", 1)[-1] if gid else ""
            variants = []
            for variant in (((node.get("variants") or {}).get("nodes")) or []):
                variants.append(
                    {
                        "available": bool(variant.get("availableForSale", False)),
                        "price": ((variant.get("price") or {}).get("amount")),
                    }
                )

            raw_products.append(
                {
                    "id": product_id,
                    "handle": node.get("handle") or "",
                    "title": node.get("title") or "",
                    "product_type": node.get("productType") or "",
                    "vendor": node.get("vendor") or "",
                    "tags": node.get("tags") or [],
                    "variants": variants,
                }
            )

        page_info = connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        next_cursor = page_info.get("endCursor")
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor

    return raw_products


def _staalz_raw_products():
    runtime = _staalz_runtime_candidates()
    errors = []

    for domain in runtime.get("domains") or []:
        for token in runtime.get("tokens") or []:
            try:
                products = _staalz_storefront_raw_products(domain, token)
                if products:
                    print(f"STAALZ: headless Storefront API fundet ({len(products)} rå produkter)")
                    return products
            except Exception as error:
                errors.append(f"storefront {domain}: {error}")

    for domain in runtime.get("domains") or []:
        try:
            products = fetch_shopify_feed(f"https://{domain}", "/products.json")
            if products:
                print(f"STAALZ: Shopify backend Ajax feed fundet ({len(products)} rå produkter)")
                return products
        except Exception as error:
            errors.append(f"ajax {domain}: {error}")

    for path in (
        "/collections/all/products.json",
        "/collections/pokemon/products.json",
        "/collections/pokemon-tcg/products.json",
    ):
        try:
            products = fetch_shopify_feed(STAALZ_HEADLESS_BASE, path)
            if products:
                print(f"STAALZ: public Shopify feed {path} fundet ({len(products)} rå produkter)")
                return products
        except Exception as error:
            errors.append(f"{path}: {error}")

    details = "; ".join(errors[-4:]) if errors else "ingen Shopify runtime fundet"
    raise RuntimeError(
        "Staalz headless Shopify kunne ikke resolveres fra offentlig frontend: " + details
    )


def get_staalz_products():
    products = {}

    for raw in _staalz_raw_products():
        game = detect_shopify_game(raw)
        if not game or not is_relevant_shopify_tcg(raw, game):
            continue

        product_id = str(raw.get("id") or "").strip()
        handle = str(raw.get("handle") or "").strip()
        name = str(raw.get("title") or "").strip()
        if not product_id or not handle or not name:
            continue

        products[product_id] = {
            "name": name,
            "game": game,
            "price": shopify_min_price(raw),
            "in_stock": shopify_variant_available(raw),
            "preorder": shopify_is_preorder(raw),
            "url": f"{STAALZ_HEADLESS_BASE}/products/{handle}",
        }

    return products
"""

replace_once(
    '''def get_shopify_products(site_key):
    site = SHOPIFY_SITES[site_key]
''',
    staalz_code + '''\n\ndef get_shopify_products(site_key):
    if site_key == "staalz":
        return get_staalz_products()

    site = SHOPIFY_SITES[site_key]
''',
    "Staalz headless Shopify special case",
)


kocardz_code = r"""

KOCARDZ_CATEGORY_FEEDS = {
    "POKÉMON": "https://www.kocardz.dk/vare-kategori/pokemon/",
    "LORCANA": "https://www.kocardz.dk/vare-kategori/lorcana/",
}
KOCARDZ_MAX_PAGES = 8


def _kocardz_price(card):
    nodes = card.select(
        ".price ins .woocommerce-Price-amount, .price ins .amount"
    )
    if not nodes:
        nodes = card.select(
            ".price .woocommerce-Price-amount, .price .amount"
        )
    if not nodes:
        return None

    value_text = woocommerce_clean_text(nodes[-1].get_text(" ", strip=True))
    matches = re.findall(
        r"(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:,\d{1,2})?)",
        value_text,
    )
    if not matches:
        return None

    try:
        value = float(matches[-1].replace(".", "").replace(",", "."))
    except ValueError:
        return None
    return value if value > 0 else None


def _kocardz_card_url(card):
    selectors = (
        "a.woocommerce-LoopProduct-link[href]",
        ".wd-entities-title a[href]",
        "h2 a[href]",
        "h3 a[href]",
        'a[href*="/vare/"]',
    )
    for selector in selectors:
        node = card.select_one(selector)
        if node:
            href = urljoin("https://www.kocardz.dk", node.get("href"))
            if "/vare/" in href:
                return href
    return None


def _kocardz_card_name(card, product_url):
    for selector in (
        "h2.woocommerce-loop-product__title",
        ".wd-entities-title",
        ".product-title",
        "h3",
    ):
        node = card.select_one(selector)
        if node:
            name = woocommerce_clean_text(node.get_text(" ", strip=True))
            if len(name) >= 4:
                return name

    for anchor in card.find_all("a", href=True):
        href = urljoin("https://www.kocardz.dk", anchor.get("href"))
        if href != product_url:
            continue
        name = woocommerce_clean_text(anchor.get_text(" ", strip=True))
        if len(name) >= 4:
            return name
        image = anchor.find("img", alt=True)
        if image:
            alt = woocommerce_clean_text(image.get("alt"))
            if len(alt) >= 4:
                return alt
    return ""


def _kocardz_product_id(card, product_url):
    add_button = card.select_one("[data-product_id]")
    if add_button and add_button.get("data-product_id"):
        return str(add_button.get("data-product_id"))

    for class_name in card.get("class") or []:
        match = re.fullmatch(r"post-(\d+)", str(class_name))
        if match:
            return match.group(1)

    return hashlib.sha256(product_url.encode("utf-8")).hexdigest()[:20]


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
        seen_ids = set()

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
            cards = soup.select(
                "li.product, .product-grid-item, .wd-product, .products .product"
            )
            if not cards:
                if page == 1:
                    raise RuntimeError(
                        f"KoCardz category parser fandt ingen produktkort: {page_url}"
                    )
                break

            new_on_page = 0
            for card in cards:
                product_url = _kocardz_card_url(card)
                if not product_url:
                    continue

                product_id = _kocardz_product_id(card, product_url)
                if product_id in seen_ids:
                    continue

                name = _kocardz_card_name(card, product_url)
                if not name:
                    continue

                synthetic = {
                    "name": name,
                    "categories": [
                        {"name": "Pokemon" if game == "POKÉMON" else "Disney Lorcana"}
                    ],
                    "short_description": "",
                    "description": "",
                }
                if not woocommerce_is_relevant_sealed(synthetic):
                    continue

                card_text = woocommerce_clean_text(card.get_text(" ", strip=True))
                low = card_text.lower()
                explicit_out = (
                    "udsolgt" in low
                    or "ikke på lager" in low
                    or "ikke pa lager" in low
                )
                explicit_in = (
                    ("på lager" in low or "pa lager" in low)
                    and not explicit_out
                )
                preorder = any(
                    marker in low
                    for marker in (
                        "forudbestil",
                        "forudbestilling",
                        "preorder",
                        "pre-order",
                        "kommer snart",
                    )
                )

                products[product_id] = {
                    "name": name,
                    "game": game,
                    "price": _kocardz_price(card),
                    "in_stock": explicit_in,
                    "preorder": preorder,
                    "url": product_url,
                }
                seen_ids.add(product_id)
                new_on_page += 1

            if new_on_page == 0:
                break

    return products
"""

replace_once(
    '''def get_woocommerce_products(site_key):
    site = WOOCOMMERCE_SITES[site_key]
''',
    kocardz_code + '''\n\ndef get_woocommerce_products(site_key):
    if site_key == "kocardz":
        return get_kocardz_products()

    site = WOOCOMMERCE_SITES[site_key]
''',
    "KoCardz public category special case",
)

PATH.write_text(text, encoding="utf-8")
print("Applied V33: Staalz headless Shopify + KoCardz category parser fixes")
