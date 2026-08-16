from pathlib import Path

BOT = Path("restock_bot_github.py")
PATCH = Path("patch_v19_sources.py")

text = BOT.read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
old_elgiganten_constants = '''ELGIGANTEN_SIGNED_KEY_URL = (
    "https://www.elgiganten.dk/api/algolia/signed-api-key"
)
ELGIGANTEN_ALGOLIA_APP_ID = "Z0FL7R8UBH"
'''
new_elgiganten_constants = '''ELGIGANTEN_SIGNED_KEY_URL = (
    "https://www.elgiganten.dk/api/algolia/signed-api-key"
)
ELGIGANTEN_CATEGORY_URL = (
    "https://www.elgiganten.dk/sport-fritid-hobby/"
    "samleobjekter-merchandise/samlekort/pokemon-kort-tcg"
)
ELGIGANTEN_ALGOLIA_APP_ID = "Z0FL7R8UBH"
'''
if old_elgiganten_constants in text:
    text = text.replace(old_elgiganten_constants, new_elgiganten_constants, 1)

# ---------------------------------------------------------------------------
# Proshop: use official /pokemon-kort first, then official /Pokemon fallback.
# No repeated 403/429 loops: retrying the same blocked GitHub IP immediately
# only creates noise and load without adding information.
# ---------------------------------------------------------------------------
proshop_start = text.index("def get_proshop_products():")
proshop_end = text.index(
    "# =========================================================\n# BR FRONTEND CONFIG",
    proshop_start,
)

new_proshop = r'''def _parse_proshop_products(response):
    soup = BeautifulSoup(response.text, "html.parser")
    products = {}

    cards = soup.select("li.site-productlist-item")

    for card in cards:
        link = card.find(
            "a",
            href=re.compile(
                r"/Pokemon/[^?#]+/\d+(?:[?#].*)?$",
                re.IGNORECASE,
            ),
        )
        if not link:
            continue

        href = link["href"]
        match = re.search(r"/(\d+)(?:[?#].*)?$", href)
        if not match:
            continue

        product_id = match.group(1)
        text_card = card.get_text(" ", strip=True)
        name = clean_proshop_name(href)

        # /Pokemon is a broad fallback with figures, games etc. Keep only
        # trading-card-related rows when that route is used.
        tcg_text = (name + " " + text_card).lower()
        tcg_markers = (
            " tcg ", "tcg ", " tcg", "booster", "elite trainer",
            "battle deck", "world championships deck", "samlekort",
            "poké ball tin", "poke ball tin", "premium collection",
            "illustration collection", "trainer box", "trainer toolkit",
            "portfolio", "card game",
        )
        if not any(marker in tcg_text for marker in tcg_markers):
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


def get_proshop_products():
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
    errors = []

    # Prefer Chrome TLS/browser fingerprint. Do not immediately repeat the
    # same 403 three times; try the second official route instead.
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
                    if url != PROSHOP_URL:
                        print(
                            f"PROSHOP: primær route blokeret; bruger {label} "
                            f"({len(products)} TCG-produkter)"
                        )
                    return products

                errors.append(f"{label}: 200 men ingen TCG-produkter parsed")
        except Exception as error:
            errors.append(f"curl_cffi: {error}")

    # Plain requests is only a fallback when curl_cffi is unavailable or
    # failed unexpectedly. One request per route, no sleep/retry storm.
    if curl_requests is None:
        session = requests.Session()
        session.headers.update(headers)
        for url, label in urls:
            try:
                response = session.get(url, timeout=25)
            except requests.RequestException as error:
                errors.append(f"{label}: {error}")
                continue

            if response.status_code != 200:
                errors.append(f"{label}: HTTP {response.status_code}")
                continue

            products = _parse_proshop_products(response)
            if products:
                return products
            errors.append(f"{label}: 200 men ingen TCG-produkter parsed")

    short = "; ".join(errors[-4:]) if errors else "ukendt fejl"
    raise RuntimeError(f"Proshop utilgængelig fra GitHub runner ({short})")


'''
text = text[:proshop_start] + new_proshop + text[proshop_end:]

# ---------------------------------------------------------------------------
# Elgiganten: reuse a cached signed key until Algolia rejects it. On refresh,
# establish a browser-like session on the official category page first so the
# site's necessary Algolia refresh nonce/session cookies can be set. On 429,
# back off until a later GitHub run instead of 5/10/15-second retry storms.
# ---------------------------------------------------------------------------
elg_start = text.index("def get_elgiganten_signed_key(force=False):")
elg_end = text.index("def is_real_elgiganten_pokemon_tcg", elg_start)

new_elg = r'''def get_elgiganten_signed_key(force=False):
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
        # If the server gives no explicit window, give it 30 minutes. This is
        # far healthier than three immediate retries every five minutes.
        cooldown = retry_after if retry_after > 0 else 1800
        cooldown = max(300, min(cooldown, 21600))
        ELGIGANTEN_KEY_CACHE["retry_after"] = int(time.time() + cooldown)
        print(
            f"ELGIGANTEN signed-key 429 - cooldown {cooldown}s; "
            "ingen immediate retries"
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

    return api_key


'''
text = text[:elg_start] + new_elg + text[elg_end:]

BOT.write_text(text, encoding="utf-8")
PATCH.unlink(missing_ok=True)
print("V1.9 applied: Proshop official fallback + Elgiganten session-aware key refresh.")
