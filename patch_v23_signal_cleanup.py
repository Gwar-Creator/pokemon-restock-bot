from pathlib import Path
import re

PATH = Path("restock_bot_github.py")
text = PATH.read_text(encoding="utf-8")

if "PRICE_SIGNAL_CLEANUP_V23 = True" in text:
    print("V23 signal cleanup already applied")
    raise SystemExit(0)


def replace_once(old, new, label):
    global text
    if old not in text:
        raise RuntimeError(f"V23 patch failed: marker not found for {label}")
    text = text.replace(old, new, 1)


# 1) Stronger anti-spam / meaningful-change thresholds.
replace_once(
    '''RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 60 * 60
RESTOCK_NEW_PRODUCT_COOLDOWN_SECONDS = 24 * 60 * 60
PRICE_ALERT_COOLDOWN_SECONDS = 24 * 60 * 60
PRICE_ALERT_MIN_IMPROVEMENT_DKK = 10.0
PRICE_ALERT_MIN_IMPROVEMENT_PCT = 0.02
''',
    '''PRICE_SIGNAL_CLEANUP_V23 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
RESTOCK_NEW_PRODUCT_COOLDOWN_SECONDS = 24 * 60 * 60
PRICE_ALERT_COOLDOWN_SECONDS = 24 * 60 * 60
PRICE_ALERT_MIN_IMPROVEMENT_DKK = 25.0
PRICE_ALERT_MIN_IMPROVEMENT_PCT = 0.05
''',
    "alert thresholds",
)

# Price alerts are deduped by normalized product/event, not retailer URL.
replace_once(
    '''    raw = "|".join((channel, event_type, product, url))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32], event_type
''',
    '''    identity_url = "" if channel == "price" else url
    raw = "|".join((channel, event_type, product, identity_url))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32], event_type
''',
    "price dedupe identity",
)

replace_once(
    '''    previous = PRICE_ALERT_MEMORY.get(key)
    now_epoch = _now_epoch()

    if event_type == "PRICE":
''',
    '''    previous = PRICE_ALERT_MEMORY.get(key)
    now_epoch = _now_epoch()

    # A retailer becoming cheapest at the same price is not actionable enough
    # for an intraday Discord alert. Price/history state still records it.
    if event_type == "SHOP":
        return None

    if event_type == "PRICE":
''',
    "shop-only price alert suppression",
)

# 2) Price Watch scope: block cases/multi-displays and apply user price ceilings.
replace_once(
    '''    if (
        "with booster box" in text
        or "med booster box" in text
    ):
        return None

    # Pokémon ETB
''',
    '''    if (
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
        or re.search(r"\\b(?:4|6|8|10|12)\\s*[x×]\\s*36\\b", text)
    ):
        return None

    # Pokémon ETB
''',
    "case exclusion",
)

replace_once(
    '''PRICE_WATCH_DAILY_MAX_SIGNALS_PER_GAME = 5
PRICE_WATCH_DAILY_MIN_SAVING_DKK = 20.0
PRICE_WATCH_DAILY_MIN_SAVING_PCT = 3.0
PRICE_HISTORY_DAILY_MAX_BUY_PER_GAME = 3
PRICE_HISTORY_DAILY_MAX_WAIT_PER_GAME = 2
PRICE_HISTORY_NEW_LOW_MIN_DKK = 20.0
PRICE_HISTORY_NEW_LOW_MIN_PCT = 3.0
''',
    '''PRICE_WATCH_DAILY_MAX_SIGNALS_PER_GAME = 3
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
''',
    "price watch limits",
)

replace_once(
    '''            price = product.get("price")

            if price is None or price <= 0:
                continue

            availability = get_price_watch_availability(
''',
    '''            price = product.get("price")

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
''',
    "candidate price ceiling",
)
replace_once(
    '''                "price": float(price),
                "availability": availability,
''',
    '''                "price": price_value,
                "availability": availability,
''',
    "candidate parsed price",
)

# 3) Price History: tiny moves remain in data but do not become Discord signals.
replace_once(
    '''        if not last_change_date or last_signal_date >= last_change_date:
            continue

        diff = _history_pct(
''',
    '''        if not last_change_date or last_signal_date >= last_change_date:
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
''',
    "history meaningful movement gate",
)

pattern = re.compile(
    r'''    selected_by_game = \{\}\n    selected_rows = \[\]\n    handled_rows = \[\]\n\n    for game in \("POKÉMON", "LORCANA"\):.*?        selected_rows\.extend\(wait\)\n''',
    re.DOTALL,
)
replacement = '''    selected_by_game = {
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
'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise RuntimeError("V23 patch failed: Price History selection block not found")

replace_once(
    '''    # Fuld, utrunkeret Excel-venlig eksport bevares til fordybelse.
    if _send_price_history_csv(products, active_keys, now_local):
        sent_any = True
''',
    '''    # Den fulde statistik bevares, men Discord får kun CSV én gang om
    # ugen (søndag) i stedet for hver dag.
    if now_local.weekday() == 6:
        if _send_price_history_csv(products, active_keys, now_local):
            sent_any = True
''',
    "weekly history CSV",
)

# 4) Fix the latent direct Proshop parser bug. Jina remains a fallback only.
replace_once(
    '''        product_id = match.group(1)
        text_card = card.get_text(" ", strip=True)
        name = clean_proshop_name(href)
''',
    '''        product_id = match.group(1)

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
''',
    "Proshop direct parser",
)

# 5) Elgiganten: signed Algolia remains primary; known public product pages are
# a rotating read-only fallback during key cooldown/rate limiting.
replace_once(
    '''def get_elgiganten_products():
    api_key = get_elgiganten_signed_key()
''',
    '''ELGIGANTEN_LAST_FETCH_MODE = "algolia"
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
        page_text = re.sub(r"\\s+", " ", soup.get_text(" ", strip=True)).strip()
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
            r"(?<!\\d)(\\d{1,5}(?:[.,]\\d{1,2})?)\\s*(?:DKK|kr\\.?)",
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
''',
    "Elgiganten fallback helper",
)

replace_once(
    '''    return products


def count_elgiganten_local_products(products):
''',
    '''    return products


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
''',
    "Elgiganten wrapper",
)

replace_once(
    '''            elgiganten = fetch_source_products(
                "elgiganten",
                old_elgiganten,
                get_elgiganten_products,
                new_state,
            )
''',
    '''            elgiganten = fetch_source_products(
                "elgiganten",
                old_elgiganten,
                lambda: get_elgiganten_products(old_products=old_elgiganten),
                new_state,
            )

            if ELGIGANTEN_LAST_FETCH_MODE != "algolia":
                _source_health_update(
                    new_state,
                    "elgiganten",
                    status="degraded",
                    consecutive_failures=0,
                    last_error=(
                        "Signed Algolia key unavailable; rotating public "
                        "product-page fallback active"
                    ),
                    observed_count=len(elgiganten),
                )
''',
    "Elgiganten caller fallback mode",
)

replace_once(
    '''            price_watch_fresh_sources.add(
                "elgiganten"
            )
''',
    '''            if ELGIGANTEN_LAST_FETCH_MODE == "algolia":
                price_watch_fresh_sources.add(
                    "elgiganten"
                )
            else:
                print(
                    "ELGIGANTEN: partial fallback holdes ude af Price Watch/History "
                    "indtil fuld Algolia-scan er frisk igen."
                )
''',
    "Elgiganten price freshness",
)

PATH.write_text(text, encoding="utf-8")
print("Applied V23: Elgiganten fallback, Proshop parser fix, stronger dedupe, compact price channels, price ceilings")
