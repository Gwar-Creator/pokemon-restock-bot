from pathlib import Path

PATH = Path("restock_bot_github.py")
text = PATH.read_text(encoding="utf-8")

MARKER = "TCGBRUUS_BROWSER_PARSER_V37 = True"

if MARKER in text:
    print("V37 TCGBruuS browser parser already applied")
    raise SystemExit(0)


def replace_once(old, new, label):
    global text
    if old not in text:
        raise RuntimeError(f"V37 patch failed: marker not found for {label}")
    text = text.replace(old, new, 1)


replace_once(
    '''WAVE4_RETAILERS_V35 = True
WAVE4_HTML_FALLBACKS_V36 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    '''WAVE4_RETAILERS_V35 = True
WAVE4_HTML_FALLBACKS_V36 = True
TCGBRUUS_BROWSER_PARSER_V37 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    "V37 marker",
)

replace_once(
    '''def get_tcgbruus_html_products():
    return _wave4_html_parse_page(TCGBRUUS_SEALED_URL, force_preorder=False)
''',
    r'''def get_tcgbruus_html_products():
    # TCGBruuS serves a theme/geo-specific category page that can be almost
    # empty to plain requests from GitHub runners. Use a real browser TLS
    # fingerprint first, then parse the public sealed listing by product URL.
    category_url = TCGBRUUS_SEALED_URL + "?v=0ecbf9426bcf"

    if curl_requests is not None:
        session = curl_requests.Session(impersonate="chrome")
    else:
        session = requests.Session()

    headers = {
        **BROWSER_HEADERS,
        "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    # Warm the public homepage so geo/currency cookies can be established in
    # the same session before the sealed category is requested.
    try:
        session.get("https://tcgbruus.dk/", headers=headers, timeout=25)
    except Exception:
        pass

    response = session.get(category_url, headers=headers, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    anchors_by_url = {}
    for anchor in soup.find_all("a", href=True):
        href = urljoin("https://tcgbruus.dk", anchor.get("href"))
        href = href.split("#", 1)[0].split("?", 1)[0].rstrip("/") + "/"
        if "/product/" not in href:
            continue
        anchors_by_url.setdefault(href, []).append(anchor)

    if not anchors_by_url:
        raise RuntimeError(
            "TCGBruuS browser parser fandt ingen produktlinks på sealed-siden"
        )

    products = {}

    for product_url, anchors in anchors_by_url.items():
        # Prefer the anchor carrying visible title text or an image alt.
        anchor = max(
            anchors,
            key=lambda node: len(
                woocommerce_clean_text(node.get_text(" ", strip=True))
                or woocommerce_clean_text((node.find("img") or {}).get("alt") if node.find("img") else "")
            ),
        )

        node = anchor
        best = anchor.parent or anchor
        for _ in range(9):
            node = node.parent
            if node is None:
                break

            candidate_urls = set()
            for child in node.find_all("a", href=True):
                child_url = urljoin("https://tcgbruus.dk", child.get("href"))
                child_url = child_url.split("#", 1)[0].split("?", 1)[0].rstrip("/") + "/"
                if "/product/" in child_url:
                    candidate_urls.add(child_url)

            if product_url not in candidate_urls:
                continue
            if len(candidate_urls) > 1:
                break

            best = node
            low = woocommerce_clean_text(node.get_text(" ", strip=True)).lower()
            if any(
                marker in low
                for marker in (
                    "dkk", "på lager", "pa lager", "udsolgt",
                    "ikke på lager", "ikke pa lager", "tilføj til kurv",
                    "tilfoj til kurv", "add to cart",
                )
            ):
                break

        name = ""
        for selector in (
            ".woocommerce-loop-product__title",
            ".product-title",
            ".wd-entities-title",
            "h2", "h3", "h4", "h5",
        ):
            title_node = best.select_one(selector)
            if title_node:
                candidate = woocommerce_clean_text(title_node.get_text(" ", strip=True))
                if len(candidate) >= 4:
                    name = candidate
                    break

        if not name:
            for candidate_anchor in anchors:
                candidate = woocommerce_clean_text(candidate_anchor.get_text(" ", strip=True))
                if len(candidate) >= 4:
                    name = candidate
                    break
                image = candidate_anchor.find("img", alt=True)
                if image:
                    candidate = woocommerce_clean_text(image.get("alt"))
                    if len(candidate) >= 4:
                        name = candidate
                        break

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

        card_text = woocommerce_clean_text(best.get_text(" ", strip=True))
        low = card_text.lower()
        classes = " ".join(str(value).lower() for value in (best.get("class") or []))

        preorder = any(
            marker in low
            for marker in (
                "forudbestil", "forudbestilling", "preorder", "pre-order", "kommer snart"
            )
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

        product_id = hashlib.sha256(product_url.encode("utf-8")).hexdigest()[:20]
        products[product_id] = {
            "name": name,
            "game": "POKÉMON",
            "price": _wave4_html_price(card_text),
            "in_stock": bool(explicit_in and not explicit_out and not preorder),
            "preorder": bool(preorder),
            "url": product_url,
        }

    if not products:
        raise RuntimeError(
            f"TCGBruuS browser parser fandt {len(anchors_by_url)} produktlinks, men 0 relevante sealed produkter"
        )

    print(
        f"TCGBRUUS: browser parser fandt {len(products)} relevante sealed produkter"
    )
    return products
''',
    "TCGBruuS parser",
)

PATH.write_text(text, encoding="utf-8")
print("Applied V37: TCGBruuS now uses curl_cffi browser impersonation and URL-based sealed parsing")
