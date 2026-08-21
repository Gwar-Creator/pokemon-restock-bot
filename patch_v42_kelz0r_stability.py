from pathlib import Path
import re

PATH = Path("restock_bot_github.py")
text = PATH.read_text(encoding="utf-8")

MARKER = "KELZ0R_STABILITY_V42 = True"

if MARKER in text:
    print("V42 Kelz0r stability already applied")
    raise SystemExit(0)

if "MATCHING_OPPORTUNITY_V40 = True" not in text:
    raise RuntimeError("V42 expects V40 scanner baseline")


def replace_once(old, new, label):
    global text
    if old not in text:
        raise RuntimeError(f"V42 patch failed: marker not found for {label}")
    text = text.replace(old, new, 1)


replace_once(
    '''MATCHING_OPPORTUNITY_V40 = True
V40_RUNTIME_FIX_V41 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    '''MATCHING_OPPORTUNITY_V40 = True
V40_RUNTIME_FIX_V41 = True
KELZ0R_STABILITY_V42 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    "V42 marker",
)

kelz0r_function = r'''
def get_kelz0r_products():
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
        return bool(re.search(r"-p-\d+\.html(?:$|[?#])", value or "", flags=re.I))

    def canonical_url(value):
        return str(value or "").split("#", 1)[0].split("?", 1)[0].rstrip("/")

    def stable_product_id(product_url):
        match = re.search(r"-p-(\d+)\.html$", product_url, flags=re.I)
        if match:
            return f"kelz0r:{match.group(1)}"
        return "kelz0r:" + hashlib.sha256(product_url.encode("utf-8")).hexdigest()[:20]

    for base_url in KELZ0R_FEEDS:
        for page in range(1, 31):
            separator = "&" if "?" in base_url else "?"
            page_url = base_url if page == 1 else f"{base_url}{separator}page={page}"
            response = session.get(page_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            page_product_urls = set()
            for anchor in soup.find_all("a", href=True):
                href = urljoin(page_url, anchor.get("href"))
                if is_product_url(href):
                    page_product_urls.add(canonical_url(href))

            if not page_product_urls:
                break

            for anchor in soup.find_all("a", href=True):
                href = urljoin(page_url, anchor.get("href"))
                if not is_product_url(href):
                    continue

                product_url = canonical_url(href)
                if product_url in seen_urls:
                    continue

                card = _wave5_nearest_card(anchor, is_product_url)
                name = _wave5_anchor_name(anchor, card)
                if not name or not woocommerce_is_relevant_sealed(
                    _wave5_synthetic(name, "POKÉMON")
                ):
                    seen_urls.add(product_url)
                    continue

                card_text = woocommerce_clean_text(card.get_text(" ", strip=True))
                low = card_text.lower()
                preorder = any(
                    marker in low
                    for marker in (
                        "[preorder]", "preorder", "pre-order", "forudbestil",
                        "forudbestilling", "forhåndsbestilling", "forhandsbestilling",
                    )
                )
                explicit_out = any(
                    marker in low
                    for marker in (
                        "meddela", "notify", "giv mig besked", "udsolgt",
                        "ikke på lager", "ikke pa lager",
                    )
                )
                explicit_in = any(
                    marker in low
                    for marker in (
                        "køb nu", "koeb nu", "köp nu", "kop nu", "buy now",
                        "læg i indkøbskurv", "laeg i indkoebskurv",
                        "læg i kurv", "laeg i kurv", "add to cart",
                    )
                )

                product_id = stable_product_id(product_url)
                products[product_id] = _wave5_product(
                    name,
                    "POKÉMON",
                    _wave5_price(card_text),
                    explicit_in and not explicit_out,
                    preorder,
                    product_url,
                )
                seen_urls.add(product_url)

    return products
'''

pattern = re.compile(
    r'''\ndef get_kelz0r_products\(\):\n.*?\n    return products\n\n\ndef _faraos_cards''',
    flags=re.DOTALL,
)
text, count = pattern.subn(
    lambda match: "\n" + kelz0r_function.strip("\n") + "\n\n\ndef _faraos_cards",
    text,
    count=1,
)
if count != 1:
    raise RuntimeError(f"V42 patch failed: Kelz0r function replacement count={count}")

replace_once(
    '''                scope_expansion = (
                    site_key == "pokecards"
                    and 0 < len(old_products) <= WOOCOMMERCE_PAGE_SIZE
                    and len(products) >= len(old_products) * 3
                )

                print(
''',
    '''                scope_expansion = (
                    site_key == "pokecards"
                    and 0 < len(old_products) <= WOOCOMMERCE_PAGE_SIZE
                    and len(products) >= len(old_products) * 3
                )
                kelz0r_rebaseline = (
                    site_key == "kelz0r"
                    and not bool(state.get("_kelz0r_stability_v42_baselined"))
                )

                print(
''',
    "Kelz0r rebaseline flag",
)

replace_once(
    '''                if was_initialized and not scope_expansion:
                    process_woocommerce_changes(
                        site_key,
                        old_products,
                        products
                    )
                elif scope_expansion:
''',
    '''                if was_initialized and not scope_expansion and not kelz0r_rebaseline:
                    process_woocommerce_changes(
                        site_key,
                        old_products,
                        products
                    )
                elif kelz0r_rebaseline:
                    print(
                        f"KELZ0R V42 stabil baseline: {len(products)} produkter; "
                        "historiske false->true/new alerts undertrykkes."
                    )
                    new_state["_kelz0r_stability_v42_baselined"] = True
                elif scope_expansion:
''',
    "Kelz0r rebaseline suppression",
)

PATH.write_text(text, encoding="utf-8")
print("Applied V42: stable Kelz0r IDs, cross-feed dedupe and one-time clean rebaseline")
