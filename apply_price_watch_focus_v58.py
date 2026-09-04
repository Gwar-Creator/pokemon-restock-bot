from pathlib import Path
import ast

path = Path("restock_bot_github.py")
text = path.read_text(encoding="utf-8")

flag_anchor = "RESTOCK_REPLAY_GUARD_V44 = True\n"
if "PRICE_WATCH_FOCUS_V58 = True" not in text:
    if flag_anchor not in text:
        raise SystemExit("flag anchor not found")
    text = text.replace(
        flag_anchor,
        flag_anchor + "PRICE_WATCH_FOCUS_V58 = True\n",
        1,
    )

focus_marker = "\ndef get_price_watch_language(name):\n"
focus_block = r'''

# ============================================================
# PRICE WATCH V1.5 - FOCUSED SEALED WATCH
# ============================================================

PRICE_WATCH_FOCUS_SETS = (
    ("Obsidian Flames", ("obsidian flames", "obsidian flame")),
    ("Phantasmal Flames", ("phantasmal flames", "phantasmal flame")),
    ("151", ("pokemon 151", "pokémon 151", "scarlet violet 151", "scarlet and violet 151", "151")),
    ("Crown Zenith", ("crown zenith",)),
    ("Paldean Fates", ("paldean fates", "paldean fate")),
    ("Ascended Heroes", ("ascended heroes", "ascending heroes")),
    ("Prismatic Evolutions", ("prismatic evolutions", "prismatic evolution")),
    ("Destined Rivals", ("destined rivals", "destined rival")),
    ("Lost Origin", ("lost origin",)),
    ("Black Bolt", ("black bolt",)),
    ("White Flare", ("white flare",)),
)

PRICE_WATCH_FOCUS_TYPE_LABELS = {
    "ETB": "ETB",
    "BOOSTER BOX": "Booster Box / Display",
    "BOOSTER BUNDLE": "Booster Bundle",
    "UPC": "UPC",
    "SPC": "SPC",
    "COLLECTION": "Collection Box",
    "TIN": "Tin",
}


def _price_watch_focus_norm(value):
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def get_price_watch_focus_set(name):
    text = _price_watch_focus_norm(name)
    padded = f" {text} "

    for canonical, aliases in PRICE_WATCH_FOCUS_SETS:
        for alias in aliases:
            alias_norm = _price_watch_focus_norm(alias)
            if alias_norm == "151":
                if re.search(r"\b151\b", text):
                    return canonical
                continue
            if f" {alias_norm} " in padded:
                return canonical

    return None


def get_price_watch_focus_type(name, game):
    if game != "POKÉMON":
        return None

    text = _price_watch_focus_norm(name)

    if not is_english_card_product(name):
        return None

    if is_low_signal_accessory_name(name):
        return None

    if "ultra premium collection" in text or re.search(r"\bupc\b", text):
        return "UPC"

    if "super premium collection" in text or re.search(r"\bspc\b", text):
        return "SPC"

    if "elite trainer box" in text or re.search(r"\betb\b", text):
        return "ETB"

    if "booster box" in text or "booster display" in text:
        if "booster bundle display" in text or "bundle display" in text:
            return None
        return "BOOSTER BOX"

    if "booster bundle" in text:
        return "BOOSTER BUNDLE"

    if re.search(r"\bmini tins?\b", text) or re.search(r"\btins?\b", text):
        return "TIN"

    if "collection" in text:
        return "COLLECTION"

    if re.search(r"\b(?:ex|v|vmax|vstar) box\b", text):
        return "COLLECTION"

    return None


def _price_watch_focus_in_stock(source_key, product):
    return bool(get_price_watch_availability(source_key, product))


def _price_watch_focus_stock_lines(shop, source_key, product):
    lines = []

    if source_key == "br":
        kolding = safe_int(product.get("kolding_stock"), 0)
        esbjerg = safe_int(product.get("esbjerg_stock"), 0)
        online = safe_int(product.get("online_count"), 0)
        if kolding > 0:
            lines.append(f"🏪 BR Kolding: **{kolding} stk.**")
        if esbjerg > 0:
            lines.append(f"🏪 BR Esbjerg: **{esbjerg} stk.**")
        if product.get("online_stock") or online > 0:
            lines.append(
                f"🌐 Online: **{online} stk.**" if online > 0
                else "🌐 Online: **På lager**"
            )
        store_count = safe_int(product.get("store_count"), 0)
        if store_count > 0:
            lines.append(f"🇩🇰 Butikker med lager: **{store_count}**")

    elif source_key in ("bilka", "foetex"):
        online = safe_int(product.get("online_count"), 0)
        if product.get("online_stock") or online > 0:
            lines.append(
                f"🌐 Online: **{online} stk.**" if online > 0
                else "🌐 Online: **På lager**"
            )
        for store in (product.get("local_stocks") or {}).values():
            stock = safe_int((store or {}).get("stock"), 0)
            if stock > 0:
                store_name = (store or {}).get("name") or shop
                lines.append(f"🏪 {store_name}: **{stock} stk.**")
        store_count = safe_int(product.get("store_count"), 0)
        if store_count > 0:
            lines.append(f"🇩🇰 Butikker med lager: **{store_count}**")

    elif source_key == "elgiganten":
        if product.get("online_stock"):
            online_display = product.get("online_display") or "På lager"
            lines.append(f"🌐 Online: **{online_display}**")
        for store in (product.get("local_stocks") or {}).values():
            if not (store or {}).get("in_stock"):
                continue
            store_name = (store or {}).get("name") or "Elgiganten"
            display = (store or {}).get("display") or "På lager"
            lines.append(f"🏪 {store_name}: **{display}**")
        store_count = safe_int(product.get("store_count"), 0)
        if store_count > 0:
            lines.append(f"🇩🇰 Butikker med lager: **{store_count}**")

    elif source_key == "coolshop":
        if product.get("online_stock"):
            lines.append("🌐 Coolshop online: **På lager**")

    elif source_key == "proshop":
        stock = str(product.get("stock") or "").strip()
        if stock:
            lines.append(f"📦 Proshop: **{stock}**")

    else:
        stock = product.get("stock")
        if isinstance(stock, (int, float)) and stock > 0:
            lines.append(f"📦 {shop}: **{int(stock)} stk. på lager**")
        elif product.get("in_stock"):
            lines.append(f"📦 {shop}: **På lager**")

    if not lines and _price_watch_focus_in_stock(source_key, product):
        lines.append(f"📦 {shop}: **På lager**")

    return lines


def collect_price_watch_focus_listings(current_state, fresh_sources=None):
    listings = {}

    def add_products(shop, source_key, products, game_override=None):
        if fresh_sources is not None and source_key not in fresh_sources:
            return

        for raw_id, product in (products or {}).items():
            if not isinstance(product, dict):
                continue

            name = str(product.get("name") or "").strip()
            game = game_override or product.get("game")
            focus_set = get_price_watch_focus_set(name)
            product_type = get_price_watch_focus_type(name, game)

            if not name or not focus_set or not product_type:
                continue

            try:
                price = float(product.get("price"))
            except (TypeError, ValueError):
                continue

            if price <= 0:
                continue

            url = str(product.get("url") or "").strip()
            if (
                not url
                and isinstance(raw_id, str)
                and raw_id.startswith(("http://", "https://"))
            ):
                url = raw_id

            listing_key = hashlib.sha256(
                f"{source_key}|{raw_id}".encode("utf-8")
            ).hexdigest()[:32]

            listings[listing_key] = {
                "listing_key": listing_key,
                "source": source_key,
                "shop": shop,
                "raw_id": str(raw_id),
                "name": name,
                "set": focus_set,
                "type": product_type,
                "price": price,
                "in_stock": _price_watch_focus_in_stock(source_key, product),
                "stock_lines": _price_watch_focus_stock_lines(shop, source_key, product),
                "url": url,
            }

    add_products("COOLSHOP", "coolshop", current_state.get("coolshop", {}))
    add_products("PROSHOP", "proshop", current_state.get("proshop", {}), "POKÉMON")
    add_products("BR", "br", current_state.get("br", {}), "POKÉMON")
    add_products("BILKA", "bilka", current_state.get("bilka", {}), "POKÉMON")
    add_products("FØTEX", "foetex", current_state.get("foetex", {}), "POKÉMON")
    add_products("ELGIGANTEN", "elgiganten", current_state.get("elgiganten", {}), "POKÉMON")

    shopify_state = current_state.get("shopify", {})
    for site_key, site in SHOPIFY_SITES.items():
        add_products(site["label"], site_key, shopify_state.get(site_key, {}))

    woocommerce_state = current_state.get("woocommerce", {})
    for site_key, site in WOOCOMMERCE_SITES.items():
        add_products(site["label"], site_key, woocommerce_state.get(site_key, {}))

    add_products("EPIC PANDA", "epicpanda", current_state.get("epicpanda", {}))
    add_products("STEFFEN-O", "steffeno", current_state.get("steffeno", {}), "POKÉMON")
    add_products("NEXT LEVEL GAMES", "nextlevel", current_state.get("nextlevel", {}))

    return listings


def _price_watch_focus_alert(listing, old_price, combo=False):
    new_price = float(listing["price"])
    drop = old_price - new_price
    drop_pct = drop / old_price if old_price > 0 else 0.0

    headline = (
        "🚨 **BEDRE PRIS FUNDET · RESTOCK + PRISFALD**"
        if combo
        else "📉 **BEDRE PRIS FUNDET · PRISFALD**"
    )

    type_label = PRICE_WATCH_FOCUS_TYPE_LABELS.get(
        listing["type"],
        listing["type"],
    )
    stock_lines = listing.get("stock_lines") or [
        f"📦 {listing['shop']}: **På lager**"
    ]
    link_line = f"\n🔗 {listing['url']}" if listing.get("url") else ""

    return send_price_watch(
        f"{headline}\n"
        f"**{listing['shop']} · {listing['name']}**\n"
        f"🎯 {listing['set']} · {type_label}\n"
        f"💰 {format_price(old_price)} → **{format_price(new_price)}** "
        f"(-{drop_pct * 100.0:.0f}%)\n"
        + "\n".join(stock_lines)
        + link_line
    )
'''

if "PRICE_WATCH_FOCUS_SETS = (" not in text:
    if focus_marker not in text:
        raise SystemExit("focus insertion marker not found")
    text = text.replace(focus_marker, focus_block + focus_marker, 1)

start_marker = "def process_price_watch(\n"
end_marker = "\n\n# =========================================================\n# PRICE HISTORY V1\n# =========================================================\n"
start = text.find(start_marker)
end = text.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit("process_price_watch block markers not found")

replacement = r'''def process_price_watch(
    old_price_watch_state,
    current_state,
    fresh_sources,
    history_state=None
):
    listings = collect_price_watch_focus_listings(
        current_state,
        fresh_sources=fresh_sources,
    )

    previous = (
        old_price_watch_state
        if isinstance(old_price_watch_state, dict)
        else {}
    )
    previous_version = safe_int(previous.get("version"), 0)
    previous_listings = previous.get("listings")
    if not isinstance(previous_listings, dict):
        previous_listings = {}

    try:
        now_local = datetime.now(ZoneInfo(PRICE_WATCH_TIMEZONE))
    except Exception:
        now_local = datetime.now(ZoneInfo("Europe/Copenhagen"))

    baseline_only = previous_version < 15 or not previous_listings
    next_listings = dict(previous_listings)
    alerts_sent = 0

    for listing_key, listing in listings.items():
        old = previous_listings.get(listing_key)
        current_price = float(listing["price"])
        current_in_stock = bool(listing.get("in_stock"))

        if not isinstance(old, dict):
            old = {}

        was_in_stock = bool(old.get("in_stock"))

        try:
            old_seen_price = float(old.get("price"))
        except (TypeError, ValueError):
            old_seen_price = None

        is_restock = bool(old) and not was_in_stock and current_in_stock
        price_is_lower = (
            old_seen_price is not None
            and current_price < old_seen_price - 0.005
        )

        if (
            not baseline_only
            and current_in_stock
            and price_is_lower
            and old_seen_price is not None
        ):
            if _price_watch_focus_alert(
                listing,
                old_seen_price,
                combo=is_restock,
            ):
                alerts_sent += 1

        next_listings[listing_key] = {
            "source": listing["source"],
            "shop": listing["shop"],
            "raw_id": listing["raw_id"],
            "name": listing["name"],
            "set": listing["set"],
            "type": listing["type"],
            "price": current_price,
            "in_stock": current_in_stock,
            "url": listing.get("url") or "",
            "last_seen": now_local.isoformat(),
        }

    if baseline_only:
        print("PRICE WATCH V1.5: fokuseret sealed-baseline oprettet uden alerts.")

    set_counts = {}
    for listing in listings.values():
        set_counts[listing["set"]] = set_counts.get(listing["set"], 0) + 1

    print(
        "PRICE WATCH V1.5: "
        f"{len(listings)} relevante listings | "
        f"{len(set_counts)} fokus-sæt | "
        f"{alerts_sent} alerts"
    )

    return {
        "version": 15,
        "mode": "focused_sealed_price_drops",
        "sets": [canonical for canonical, _ in PRICE_WATCH_FOCUS_SETS],
        "listings": next_listings,
        "updated_at": now_local.isoformat(),
    }
'''

text = text[:start] + replacement + text[end:]
ast.parse(text)
path.write_text(text, encoding="utf-8")

required = (
    "PRICE_WATCH_FOCUS_V58 = True",
    '"Lost Origin"',
    '"Black Bolt"',
    '"White Flare"',
    '"UPC": "UPC"',
    '"SPC": "SPC"',
    '"COLLECTION": "Collection Box"',
    '"TIN": "Tin"',
    "RESTOCK + PRISFALD",
    "collect_price_watch_focus_listings",
    '"version": 15',
)
missing = [value for value in required if value not in text]
if missing:
    raise SystemExit(f"missing markers: {missing}")

print("Price Watch V1.5 migration applied")
