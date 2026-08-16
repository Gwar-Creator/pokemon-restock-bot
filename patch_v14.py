from pathlib import Path

BOT = Path("restock_bot_github.py")
PATCH = Path("patch_v14.py")

text = BOT.read_text(encoding="utf-8")

# ---------------------------------------------------------
# Imports
# ---------------------------------------------------------
if "from requests_oauthlib import OAuth1" not in text:
    marker = "import requests\n\n"
    replacement = '''import requests

try:
    from requests_oauthlib import OAuth1
except ImportError:
    OAuth1 = None

'''
    if marker not in text:
        raise RuntimeError("Could not find requests import marker")
    text = text.replace(marker, replacement, 1)

# ---------------------------------------------------------
# Environment/config
# ---------------------------------------------------------
old = 'PRICE_WATCH_WEBHOOK_URL = os.getenv("PRICE_WATCH_WEBHOOK_URL", "").strip()\n'
new = '''PRICE_WATCH_WEBHOOK_URL = os.getenv("PRICE_WATCH_WEBHOOK_URL", "").strip()
PRICE_HISTORY_WEBHOOK_URL = os.getenv("PRICE_HISTORY_WEBHOOK_URL", "").strip()

CARDMARKET_APP_TOKEN = os.getenv("CARDMARKET_APP_TOKEN", "").strip()
CARDMARKET_APP_SECRET = os.getenv("CARDMARKET_APP_SECRET", "").strip()
CARDMARKET_ACCESS_TOKEN = os.getenv("CARDMARKET_ACCESS_TOKEN", "").strip()
CARDMARKET_ACCESS_SECRET = os.getenv("CARDMARKET_ACCESS_SECRET", "").strip()
CARDMARKET_BASE = "https://apiv2.cardmarket.com/ws/v2.0"
CARDMARKET_MIN_SELLS = 25
CARDMARKET_EXCLUDED_COUNTRIES = {"GB", "UK", "CH"}
CARDMARKET_GAME_IDS = {}
'''
if new not in text:
    if old not in text:
        raise RuntimeError("Could not find webhook config marker")
    text = text.replace(old, new, 1)

hour_marker = '''PRICE_WATCH_DAILY_HOUR = max(
    0,
    min(23, PRICE_WATCH_DAILY_HOUR)
)
'''
hour_block = '''PRICE_WATCH_DAILY_HOUR = max(
    0,
    min(23, PRICE_WATCH_DAILY_HOUR)
)

try:
    PRICE_HISTORY_DAILY_HOUR = int(
        os.getenv("PRICE_HISTORY_DAILY_HOUR", "9")
    )
except ValueError:
    PRICE_HISTORY_DAILY_HOUR = 9

PRICE_HISTORY_DAILY_HOUR = max(
    0,
    min(23, PRICE_HISTORY_DAILY_HOUR)
)
'''
if "PRICE_HISTORY_DAILY_HOUR" not in text:
    if hour_marker not in text:
        raise RuntimeError("Could not find daily hour marker")
    text = text.replace(hour_marker, hour_block, 1)

# ---------------------------------------------------------
# Discord history sender
# ---------------------------------------------------------
sender_marker = '''def send_price_watch(message):
    if not PRICE_WATCH_WEBHOOK_URL:
        print(
            "PRICE_WATCH_WEBHOOK_URL mangler - "
            "springer Price Watch-besked over."
        )
        return

    _post_discord(
        PRICE_WATCH_WEBHOOK_URL,
        message,
        "price",
    )
'''
sender_block = sender_marker + '''

def send_price_history_embed(title, description, color=0x5865F2, footer=None):
    if not PRICE_HISTORY_WEBHOOK_URL:
        return False

    embed = {
        "title": (title or "Price History")[:256],
        "description": (description or " ")[:4096],
        "color": color,
        "footer": {
            "text": (
                footer
                or "MasterBot · Price History"
            )[:2048]
        },
    }

    response = requests.post(
        PRICE_HISTORY_WEBHOOK_URL,
        json={
            "username": "MasterBot",
            "allowed_mentions": {"parse": []},
            "embeds": [embed],
        },
        headers={
            "User-Agent": "Pokemon-Lorcana-MasterBot/1.4"
        },
        timeout=20,
    )
    response.raise_for_status()
    return True
'''
if "def send_price_history_embed(" not in text:
    if sender_marker not in text:
        raise RuntimeError("Could not find Discord sender marker")
    text = text.replace(sender_marker, sender_block, 1)

# ---------------------------------------------------------
# Price History + Cardmarket module
# ---------------------------------------------------------
insert_marker = '''# =========================================================
# COOLSHOP FETCH
# =========================================================
'''
module = r'''# =========================================================
# PRICE HISTORY V1
# =========================================================

def build_price_history_groups(candidates):
    """Price history tracks every comparable sealed product, even with one shop."""
    raw_groups = {}

    for product in candidates:
        product_key = get_price_watch_product_key(product)
        if not product_key:
            continue
        raw_groups.setdefault(product_key, []).append(product)

    groups = {}

    for product_key, products in raw_groups.items():
        cheapest_by_shop = {}

        for product in products:
            shop = product["shop"]
            current = cheapest_by_shop.get(shop)
            if current is None or product["price"] < current["price"]:
                cheapest_by_shop[shop] = product

        if cheapest_by_shop:
            groups[product_key] = sorted(
                cheapest_by_shop.values(),
                key=lambda product: (product["price"], product["shop"])
            )

    return groups


def _history_short_type(product_type):
    return {
        "ETB": "ETB",
        "BOOSTER BOX": "Box",
        "BOOSTER BUNDLE": "Bundle",
        "SLEEVED BOOSTER": "Sleeved",
        "BOOSTER PACK": "Pack",
    }.get(product_type, product_type.title())


def _history_product_label(product_key):
    info = parse_price_watch_key(product_key)
    return (
        f"{price_watch_display_name(product_key)} "
        f"[{_history_short_type(info['type'])}]"
    )


def _history_pct(current_price, historical_low):
    try:
        current_price = float(current_price)
        historical_low = float(historical_low)
    except (TypeError, ValueError):
        return None

    if historical_low <= 0:
        return None

    return ((current_price / historical_low) - 1.0) * 100.0


def _history_pct_text(value):
    if value is None:
        return "-"
    if abs(value) < 0.05:
        return "0,0%"
    return (f"+{value:.1f}%").replace(".", ",")


def _history_money_short(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "-"

    if abs(value - round(value)) < 0.005:
        return f"{int(round(value))}"

    return f"{value:.2f}".replace(".", ",")


def _history_cell(value, width):
    value = str(value or "-")
    if len(value) > width:
        value = value[: max(1, width - 1)] + "…"
    return value.ljust(width)


def _history_table(entries, include_cardmarket=False):
    if include_cardmarket:
        header = (
            f"{'Produkt':25} {'Lavest':7} {'Butik':11} "
            f"{'Nu':7} {'Diff':7} {'CM €':7}"
        )
        divider = "-" * len(header)
    else:
        header = (
            f"{'Produkt':27} {'Lavest':7} {'Butik':12} "
            f"{'Nu':7} {'Diff':7}"
        )
        divider = "-" * len(header)

    lines = [header, divider]

    for entry in entries:
        diff = _history_pct(
            entry.get("current_best"),
            entry.get("historical_low")
        )

        low_shops = entry.get("historical_low_shops") or []
        low_shop = " + ".join(low_shops) if low_shops else "-"

        if include_cardmarket:
            cardmarket = entry.get("cardmarket") or {}
            cm_price = cardmarket.get("eur")
            line = (
                _history_cell(entry.get("label"), 25)
                + " " + _history_cell(_history_money_short(entry.get("historical_low")), 7)
                + " " + _history_cell(low_shop, 11)
                + " " + _history_cell(_history_money_short(entry.get("current_best")), 7)
                + " " + _history_cell(_history_pct_text(diff), 7)
                + " " + _history_cell(_history_money_short(cm_price), 7)
            )
        else:
            line = (
                _history_cell(entry.get("label"), 27)
                + " " + _history_cell(_history_money_short(entry.get("historical_low")), 7)
                + " " + _history_cell(low_shop, 12)
                + " " + _history_cell(_history_money_short(entry.get("current_best")), 7)
                + " " + _history_cell(_history_pct_text(diff), 7)
            )

        lines.append(line.rstrip())

    return "```text\n" + "\n".join(lines) + "\n```"


# =========================================================
# CARDMARKET - OPTIONAL DAILY REFERENCE
# =========================================================

def cardmarket_enabled():
    return bool(
        OAuth1 is not None
        and CARDMARKET_APP_TOKEN
        and CARDMARKET_APP_SECRET
    )


def _cardmarket_auth(url):
    kwargs = {
        "client_key": CARDMARKET_APP_TOKEN,
        "client_secret": CARDMARKET_APP_SECRET,
        "signature_method": "HMAC-SHA1",
        "signature_type": "AUTH_HEADER",
        "realm": url,
    }

    if CARDMARKET_ACCESS_TOKEN and CARDMARKET_ACCESS_SECRET:
        kwargs["resource_owner_key"] = CARDMARKET_ACCESS_TOKEN
        kwargs["resource_owner_secret"] = CARDMARKET_ACCESS_SECRET

    return OAuth1(**kwargs)


def _cardmarket_get(path, params=None):
    url = CARDMARKET_BASE + path
    last_error = None

    for attempt in range(2):
        response = requests.get(
            url,
            params=params or {},
            auth=_cardmarket_auth(url),
            headers={
                "Accept": "application/json",
                "User-Agent": "Pokemon-Lorcana-MasterBot/1.4",
            },
            timeout=30,
        )

        if response.status_code == 429:
            last_error = RuntimeError("Cardmarket 429 Too Many Requests")
            time.sleep(2.0 + attempt * 3.0)
            continue

        response.raise_for_status()
        # Cardmarket marketplace calls are intentionally serialized.
        time.sleep(0.4)
        return response.json()

    raise last_error or RuntimeError("Cardmarket request failed")


def _cardmarket_game_id(game):
    cached = CARDMARKET_GAME_IDS.get(game)
    if cached:
        return cached

    payload = _cardmarket_get("/games")
    games = payload.get("game") or payload.get("games") or []
    if isinstance(games, dict):
        games = [games]

    wanted = "pokemon" if game == "POKÉMON" else "lorcana"

    for row in games:
        name = str(
            row.get("name")
            or row.get("gameName")
            or ""
        ).lower().replace("é", "e")

        if wanted in name:
            game_id = safe_int(row.get("idGame"), 0)
            if game_id:
                CARDMARKET_GAME_IDS[game] = game_id
                return game_id

    return None


def _cardmarket_search_name(product_key):
    info = parse_price_watch_key(product_key)
    set_name = price_watch_display_name(product_key).replace(" (Japansk)", "")
    suffix = {
        "ETB": "Elite Trainer Box",
        "BOOSTER BOX": "Booster Box",
        "BOOSTER BUNDLE": "Booster Bundle",
        "SLEEVED BOOSTER": "Sleeved Booster",
        "BOOSTER PACK": "Booster Pack",
    }.get(info["type"], "")
    return f"{set_name} {suffix}".strip()


def _cardmarket_name_score(product_key, candidate_name):
    desired = re.sub(
        r"[^a-z0-9 ]+",
        " ",
        _cardmarket_search_name(product_key).lower()
    )
    candidate = re.sub(
        r"[^a-z0-9 ]+",
        " ",
        str(candidate_name or "").lower()
    )

    desired_tokens = {
        token for token in desired.split()
        if token not in {"pokemon", "pokémon", "tcg", "disney", "lorcana"}
    }
    candidate_tokens = set(candidate.split())

    if not desired_tokens:
        return 0.0

    overlap = len(desired_tokens.intersection(candidate_tokens)) / len(desired_tokens)

    info = parse_price_watch_key(product_key)
    type_checks = {
        "ETB": ("elite", "trainer", "box"),
        "BOOSTER BOX": ("booster", "box"),
        "BOOSTER BUNDLE": ("booster", "bundle"),
        "SLEEVED BOOSTER": ("sleeved", "booster"),
        "BOOSTER PACK": ("booster",),
    }.get(info["type"], ())

    if type_checks and not all(token in candidate_tokens for token in type_checks):
        overlap -= 0.35

    return overlap


def _cardmarket_find_product(product_key, previous_cardmarket=None):
    previous_cardmarket = previous_cardmarket or {}
    previous_id = safe_int(previous_cardmarket.get("product_id"), 0)
    if previous_id:
        return {
            "idProduct": previous_id,
            "name": previous_cardmarket.get("product_name") or "",
        }

    info = parse_price_watch_key(product_key)
    game_id = _cardmarket_game_id(info["game"])
    if not game_id:
        return None

    payload = _cardmarket_get(
        "/products/find",
        params={
            "search": _cardmarket_search_name(product_key),
            "exact": "false",
            "idGame": game_id,
            "idLanguage": 1,
            "start": 0,
            "maxResults": 20,
        },
    )

    products = payload.get("product") or payload.get("products") or []
    if isinstance(products, dict):
        products = [products]

    scored = sorted(
        (
            (_cardmarket_name_score(product_key, row.get("name")), row)
            for row in products
        ),
        key=lambda item: item[0],
        reverse=True,
    )

    if not scored or scored[0][0] < 0.55:
        return None

    return scored[0][1]


def _cardmarket_floor(product_key, previous_cardmarket=None):
    product = _cardmarket_find_product(product_key, previous_cardmarket)
    if not product:
        return None

    product_id = safe_int(product.get("idProduct"), 0)
    if not product_id:
        return None

    # IMPORTANT: this tracker follows sealed products. Cardmarket's
    # minCondition=MT filter is singles-only, so it is deliberately NOT sent
    # for sealed products. English is enforced; seller quality is filtered
    # locally using seller.sellCount, and UK/Switzerland are excluded locally.
    payload = _cardmarket_get(
        f"/articles/{product_id}",
        params={
            "idLanguage": 1,
            "start": 0,
            "maxResults": 100,
        },
    )

    articles = payload.get("article") or payload.get("articles") or []
    if isinstance(articles, dict):
        articles = [articles]

    qualified = []

    for article in articles:
        language = article.get("language") or {}
        if safe_int(language.get("idLanguage"), 0) != 1:
            continue

        seller = article.get("seller") or {}
        if safe_int(seller.get("sellCount"), 0) < CARDMARKET_MIN_SELLS:
            continue

        address = seller.get("address") or {}
        country = str(address.get("country") or "").upper()
        if country in CARDMARKET_EXCLUDED_COUNTRIES:
            continue

        if seller.get("onVacation") is True:
            continue

        try:
            price = float(article.get("price"))
        except (TypeError, ValueError):
            continue

        if price <= 0:
            continue

        qualified.append((price, article, seller, country))

    if not qualified:
        return {
            "product_id": product_id,
            "product_name": product.get("name") or "",
            "checked_at": datetime.now(ZoneInfo(PRICE_WATCH_TIMEZONE)).isoformat(),
            "qualified_offers": 0,
        }

    price, article, seller, country = min(
        qualified,
        key=lambda row: row[0]
    )

    return {
        "eur": price,
        "seller": seller.get("username") or "",
        "country": country,
        "sales": safe_int(seller.get("sellCount"), 0),
        "product_id": product_id,
        "product_name": product.get("name") or "",
        "checked_at": datetime.now(ZoneInfo(PRICE_WATCH_TIMEZONE)).isoformat(),
        "qualified_offers": len(qualified),
        "shipping_included": False,
    }


def _price_history_daily_summary(products, active_keys, now_local, started_at):
    if not PRICE_HISTORY_WEBHOOK_URL:
        return False

    active_entries = []

    for product_key in active_keys:
        entry = products.get(product_key)
        if not isinstance(entry, dict):
            continue
        row = dict(entry)
        row["product_key"] = product_key
        row["label"] = _history_product_label(product_key)
        active_entries.append(row)

    if not active_entries:
        return False

    include_cm = cardmarket_enabled()
    sent_any = False

    for game in ("POKÉMON", "LORCANA"):
        game_entries = [
            entry for entry in active_entries
            if parse_price_watch_key(entry["product_key"])["game"] == game
        ]

        if not game_entries:
            continue

        order = {value: index for index, value in enumerate(PRICE_WATCH_TYPE_ORDER)}
        game_entries.sort(
            key=lambda entry: (
                order.get(parse_price_watch_key(entry["product_key"])["type"], 99),
                entry["label"].lower(),
            )
        )

        pages = [
            game_entries[index:index + 12]
            for index in range(0, len(game_entries), 12)
        ]

        for page_index, page in enumerate(pages, start=1):
            title = (
                f"📊 PRICE HISTORY · {price_watch_game_label(game).upper()}"
                + (f" · {page_index}/{len(pages)}" if len(pages) > 1 else "")
            )

            description = _history_table(page, include_cardmarket=include_cm)

            notes = [
                "Lavest = laveste observerede danske pris siden tracking start.",
                "Diff = nuværende bedste danske pris vs. historisk laveste.",
            ]
            if include_cm:
                notes.append(
                    "CM € = laveste kvalificerede Cardmarket-tilbud ekskl. fragt; English, seller ≥25 salg, UK/CH udeladt."
                )

            description += "\n" + "\n".join(f"*{note}*" for note in notes)

            footer = (
                f"Historik startet {started_at[:10]} · "
                f"Opdateret {now_local.strftime('%d.%m.%Y %H:%M')}"
            )

            send_price_history_embed(
                title,
                description,
                color=0x5865F2,
                footer=footer,
            )
            sent_any = True

    return sent_any


def process_price_history(old_history_state, current_state, fresh_sources):
    candidates = collect_price_watch_candidates(
        current_state,
        fresh_sources=fresh_sources
    )
    groups = build_price_history_groups(candidates)

    previous = old_history_state if isinstance(old_history_state, dict) else {}
    previous_products = previous.get("products")
    if not isinstance(previous_products, dict):
        previous_products = {}

    try:
        now_local = datetime.now(ZoneInfo(PRICE_WATCH_TIMEZONE))
    except Exception:
        now_local = datetime.now(ZoneInfo("Europe/Copenhagen"))

    today = now_local.date().isoformat()
    started_at = str(previous.get("started_at") or now_local.isoformat())
    last_daily_date = str(previous.get("last_daily_date") or "")
    first_run = not bool(previous_products)
    next_products = dict(previous_products)
    active_keys = set(groups.keys())

    daily_due = (
        bool(PRICE_HISTORY_WEBHOOK_URL)
        and now_local.hour >= PRICE_HISTORY_DAILY_HOUR
        and last_daily_date != today
    )

    new_lows = []

    for product_key, products in groups.items():
        best = price_watch_best_entry(products)
        current_best = float(best["price"])
        current_shops = price_watch_lowest_shops(products)
        old_entry = previous_products.get(product_key)

        if not isinstance(old_entry, dict):
            entry = {
                "name": price_watch_display_name(product_key),
                "current_best": current_best,
                "current_shops": current_shops,
                "current_shop": best["shop"],
                "current_url": best.get("url") or "",
                "historical_low": current_best,
                "historical_low_shops": current_shops,
                "historical_low_date": today,
                "historical_low_url": best.get("url") or "",
                "first_seen": now_local.isoformat(),
                "last_seen": now_local.isoformat(),
            }
        else:
            entry = dict(old_entry)
            entry.update({
                "name": price_watch_display_name(product_key),
                "current_best": current_best,
                "current_shops": current_shops,
                "current_shop": best["shop"],
                "current_url": best.get("url") or "",
                "last_seen": now_local.isoformat(),
            })

            try:
                old_low = float(entry.get("historical_low"))
            except (TypeError, ValueError):
                old_low = current_best

            if current_best < old_low - 0.005:
                entry["historical_low"] = current_best
                entry["historical_low_shops"] = current_shops
                entry["historical_low_date"] = today
                entry["historical_low_url"] = best.get("url") or ""
                new_lows.append((product_key, old_low, entry, best))

        next_products[product_key] = entry

    # Cardmarket is an optional once-daily reference. It is never mixed into
    # the Danish historical low because Cardmarket prices exclude shipping.
    if daily_due and cardmarket_enabled():
        print("PRICE HISTORY: opdaterer Cardmarket-reference ...")
        for product_key in sorted(active_keys):
            entry = next_products.get(product_key)
            if not isinstance(entry, dict):
                continue

            existing = entry.get("cardmarket")
            checked_date = ""
            if isinstance(existing, dict):
                checked_date = str(existing.get("checked_at") or "")[:10]

            if checked_date == today:
                continue

            try:
                cardmarket = _cardmarket_floor(product_key, existing)
                if cardmarket:
                    entry["cardmarket"] = cardmarket
            except Exception as error:
                print(
                    f"Cardmarket fejl for {_history_product_label(product_key)}: {error}"
                )

    if not first_run and PRICE_HISTORY_WEBHOOK_URL:
        for product_key, old_low, entry, best in new_lows:
            info = parse_price_watch_key(product_key)
            shops = " + ".join(entry.get("historical_low_shops") or [best["shop"]])
            description = (
                f"**{price_watch_game_label(info['game'])} · "
                f"{_history_product_label(product_key)}**\n\n"
                f"Tidligere rekord: {format_price(old_low)}\n"
                f"Ny rekord: **{format_price(entry['historical_low'])}**\n"
                f"Butik: **{shops}**"
            )
            if best.get("url"):
                description += f"\n🔗 {best['url']}"

            send_price_history_embed(
                "🏆 NY HISTORISK LAVESTE PRIS",
                description,
                color=0xF1C40F,
                footer="MasterBot · Price History · dansk retail",
            )

    if daily_due:
        if _price_history_daily_summary(
            next_products,
            active_keys,
            now_local,
            started_at,
        ):
            last_daily_date = today

    print(
        f"PRICE HISTORY V1: {len(active_keys)} aktive produkter | "
        f"{len(new_lows)} nye historiske lows | "
        f"Cardmarket {'aktiv' if cardmarket_enabled() else 'ikke konfigureret'}"
    )

    return {
        "version": 1,
        "started_at": started_at,
        "last_daily_date": last_daily_date,
        "products": next_products,
    }


'''

if "def process_price_history(" not in text:
    if insert_marker not in text:
        raise RuntimeError("Could not find COOLSHOP FETCH marker")
    text = text.replace(insert_marker, module + insert_marker, 1)

# ---------------------------------------------------------
# Main loop hook
# ---------------------------------------------------------
main_marker = '''        new_state["price_watch"] = process_price_watch(
            state.get("price_watch"),
            price_watch_current_state,
            price_watch_fresh_sources
        )

        # -------------------------
        # GEM STATE
        # -------------------------
'''
main_block = '''        new_state["price_watch"] = process_price_watch(
            state.get("price_watch"),
            price_watch_current_state,
            price_watch_fresh_sources
        )

        # -------------------------
        # PRICE HISTORY V1
        # -------------------------

        new_state["price_history"] = process_price_history(
            state.get("price_history"),
            price_watch_current_state,
            price_watch_fresh_sources
        )

        # -------------------------
        # GEM STATE
        # -------------------------
'''
if 'new_state["price_history"] = process_price_history(' not in text:
    if main_marker not in text:
        raise RuntimeError("Could not find Price Watch main hook")
    text = text.replace(main_marker, main_block, 1)

BOT.write_text(text, encoding="utf-8")
PATCH.unlink(missing_ok=True)
print("V1.4 patch applied: price history + optional Cardmarket reference.")
