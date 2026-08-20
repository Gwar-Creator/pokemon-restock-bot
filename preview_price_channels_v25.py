import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

STATE_FILE = "restock_state_v2.json"
OUTPUT_FILE = "price_channels_preview_v25.txt"

PRICE_WATCH_DAILY_MAX_SIGNALS_PER_GAME = 3
PRICE_HISTORY_DAILY_MAX_SIGNALS_TOTAL = 3
PRICE_WATCH_DAILY_MIN_SAVING_DKK = 25.0
PRICE_WATCH_DAILY_MIN_SAVING_PCT = 5.0
PRICE_ALERT_MIN_IMPROVEMENT_DKK = 25.0
PRICE_ALERT_MIN_IMPROVEMENT_PCT = 5.0
PRICE_WATCH_MAX_PRICE = {
    "BOOSTER PACK": 150.0,
    "SLEEVED BOOSTER": 175.0,
    "BOOSTER BUNDLE": 750.0,
    "ETB": 1500.0,
    "BOOSTER BOX": 1750.0,
}

SOURCE_LABELS = {
    "coolshop": "COOLSHOP",
    "proshop": "PROSHOP",
    "br": "BR",
    "bilka": "BILKA",
    "foetex": "FØTEX",
    "pokehulen": "POKEHULEN",
    "rogerz": "ROGERZ",
    "mtgwebshop": "MTGWEBSHOP",
    "luckbox": "LUCKBOX",
    "spilforsyningen": "SPILFORSYNINGEN",
    "musenogslottet": "MUSEN & SLOTTET",
    "nostalgic": "NOSTALGIC",
    "andcards": "ANDCARDS",
    "pokecards": "POKECARDS.DK",
    "epicpanda": "EPIC PANDA",
    "steffeno": "STEFFEN-O",
    "nextlevel": "NEXT LEVEL GAMES",
}

SHOPIFY_SOURCES = {
    "pokehulen",
    "rogerz",
    "mtgwebshop",
    "luckbox",
    "spilforsyningen",
    "musenogslottet",
}
WOOCOMMERCE_SOURCES = {"nostalgic", "andcards", "pokecards"}
POKEMON_ONLY_SOURCES = {"proshop", "br", "bilka", "foetex", "steffeno"}

ACCESSORY_MARKERS = (
    "akryl", "acryl", "acrylic", "protector", "display case", "opbevaring",
    "storage", "binder", "portfolio", "sleeves", "deck box", "toploader",
    "lodtrækning", "lottery", "reward", "one piece", "magic the gathering",
    "magic: the gathering", "yu-gi-oh", "yugioh", "penalhus", "pencil case",
    "repack", "playmat", "play mat", "card case", "card holder",
)
ACCESSORY_EXCEPTIONS = (
    "binder collection",
    "playmat collection",
    "play mat collection",
    "accessory pouch special collection",
    "sleeved booster",
)


def load_state():
    with open(STATE_FILE, "r", encoding="utf-8") as file:
        state = json.load(file)
    if not isinstance(state, dict):
        raise RuntimeError("restock_state_v2.json er ikke et dictionary")
    return state


def fresh_sources(state):
    health = state.get("_source_health") or {}
    return {
        source
        for source, entry in health.items()
        if source in SOURCE_LABELS
        and isinstance(entry, dict)
        and entry.get("status") == "ok"
    }


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def format_price(price):
    try:
        value = float(price)
    except (TypeError, ValueError):
        return "Pris ukendt"
    return (
        f"{value:,.2f} kr."
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def is_low_signal_accessory_name(name):
    text = " " + re.sub(r"\s+", " ", str(name or "").lower()) + " "
    if any(marker in text for marker in ACCESSORY_EXCEPTIONS):
        return False
    return any(marker in text for marker in ACCESSORY_MARKERS)


def get_price_watch_type(name, game):
    text = str(name or "").lower()
    if is_low_signal_accessory_name(text):
        return None

    if "with booster box" in text or "med booster box" in text:
        return None
    if (
        "booster box case" in text
        or "booster case" in text
        or "case of booster" in text
        or re.search(r"\b(?:4|6|8|10|12)\s*[x×]\s*36\b", text)
    ):
        return None

    if game == "POKÉMON" and (
        "elite trainer box" in text or re.search(r"\betb\b", text)
    ):
        return "ETB"

    if "booster bundle display" in text or "bundle display" in text:
        return None
    if "booster box" in text or "booster display" in text:
        return "BOOSTER BOX"
    if "booster bundle" in text:
        return "BOOSTER BUNDLE"
    if "sleeved booster" in text:
        return "SLEEVED BOOSTER"
    if "booster pack" in text:
        return "BOOSTER PACK"
    if (
        "booster" in text
        and "box" not in text
        and "bundle" not in text
        and "display" not in text
    ):
        return "BOOSTER PACK"
    return None


def get_price_watch_language(name):
    text = str(name or "").lower()
    if any(marker in text for marker in ("japansk", "japanese", "japan import")):
        return "JP"
    return "EN"


def normalize_price_watch_set_name(name):
    text = str(name or "").lower()
    text = (
        text.replace("’", "'")
        .replace("–", " ")
        .replace("—", " ")
        .replace("&", " and ")
        .replace("'", "")
    )
    text = re.sub(r"\b(?:pok|dis|lor)[a-z0-9-]*\d[a-z0-9-]*\b", " ", text)
    text = re.sub(r"\b(?:me|sv)\d+(?:\.\d+)?[a-z]?\b", " ", text)
    text = re.sub(r"\bm\d+[a-z]?\b", " ", text)
    text = re.sub(
        r"\(?\b(?:6|10|18|20|24|30|36)\s*(?:engelsk\s+)?(?:booster\s*)?(?:packs?|boosters?|boostere|pakker)\b\)?",
        " ",
        text,
    )
    noise_phrases = (
        "pokemon trading card game", "pokémon trading card game", "disney lorcana tcg",
        "disney lorcana", "pokemon tcg", "pokémon tcg", "lorcana tcg",
        "booster bundle display", "booster display box", "booster box display",
        "elite trainer box", "booster bundle", "booster display", "booster box",
        "sleeved booster", "booster pack", "pokemon kort", "pokémon kort",
        "sealed set", "sealed", "engelsk", "english", "japansk", "japanese",
        "pokemon", "pokémon", "lorcana", "booster", "tcg",
    )
    for phrase in noise_phrases:
        text = text.replace(phrase, " ")
    text = re.sub(r"\bset\s+\d+\b", " ", text)
    text = re.sub(r"[^a-z0-9æøå ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for prefix in ("scarlet and violet", "mega evolution"):
        if text.startswith(prefix + " "):
            text = text[len(prefix):].strip()
    return text


def product_key(game, product_type, name):
    set_name = normalize_price_watch_set_name(name)
    if not set_name:
        return None
    return f"{game}|{product_type}|{get_price_watch_language(name)}|{set_name}"


def parse_key(key):
    parts = str(key or "").split("|", 3)
    if len(parts) != 4:
        return {"game": "", "type": "", "language": "", "set_name": str(key or "")}
    return {"game": parts[0], "type": parts[1], "language": parts[2], "set_name": parts[3]}


def display_name(key):
    info = parse_key(key)
    display = " ".join(word.capitalize() for word in info["set_name"].split()) or "Ukendt produkt"
    if info["language"] == "JP":
        display += " (Japansk)"
    return display


def type_label(product_type):
    return {
        "ETB": "ETB",
        "BOOSTER BOX": "Booster Box",
        "BOOSTER BUNDLE": "Booster Bundle",
        "SLEEVED BOOSTER": "Sleeved Booster",
        "BOOSTER PACK": "Booster Pack",
    }.get(product_type, product_type.title())


def game_label(game):
    return "Pokémon" if game == "POKÉMON" else "Lorcana" if game == "LORCANA" else game


def source_products(state, source):
    if source in SHOPIFY_SOURCES:
        return ((state.get("shopify") or {}).get(source) or {})
    if source in WOOCOMMERCE_SOURCES:
        return ((state.get("woocommerce") or {}).get(source) or {})
    return state.get(source) or {}


def availability(source, product):
    if source == "proshop":
        return product.get("stock") if product.get("stock") in ("PÅ LAGER", "FJERNLAGER") else None
    if source == "br":
        if product.get("online_stock"):
            return "ONLINE"
        if safe_int(product.get("kolding_stock")) > 0:
            return "KOLDING"
        if safe_int(product.get("esbjerg_stock")) > 0:
            return "ESBJERG"
        return None
    if source in ("bilka", "foetex"):
        if product.get("online_stock"):
            return "ONLINE"
        for store in (product.get("local_stocks") or {}).values():
            if safe_int((store or {}).get("stock")) > 0:
                return (store or {}).get("name") or "LOKALT"
        return None
    if source == "coolshop":
        return "PÅ LAGER" if product.get("online_stock") else None
    if product.get("preorder"):
        return None
    return "PÅ LAGER" if product.get("in_stock") else None


def collect_candidates(state, fresh):
    candidates = []
    for source in sorted(fresh):
        if source not in SOURCE_LABELS:
            continue
        products = source_products(state, source)
        if not isinstance(products, dict):
            continue
        for product in products.values():
            if not isinstance(product, dict):
                continue
            game = "POKÉMON" if source in POKEMON_ONLY_SOURCES else product.get("game")
            if game not in ("POKÉMON", "LORCANA"):
                continue
            name = product.get("name") or ""
            ptype = get_price_watch_type(name, game)
            if not ptype:
                continue
            try:
                price = float(product.get("price"))
            except (TypeError, ValueError):
                continue
            if price <= 0 or price > PRICE_WATCH_MAX_PRICE.get(ptype, float("inf")):
                continue
            if not availability(source, product):
                continue
            key = product_key(game, ptype, name)
            if not key:
                continue
            candidates.append({
                "key": key,
                "game": game,
                "type": ptype,
                "name": name,
                "price": price,
                "shop": SOURCE_LABELS[source],
                "source": source,
                "url": product.get("url") or "",
            })
    return candidates


def grouped_candidates(candidates):
    groups = {}
    for row in candidates:
        groups.setdefault(row["key"], []).append(row)
    return groups


def cheapest_by_shop(rows):
    result = {}
    for row in rows:
        current = result.get(row["shop"])
        if current is None or row["price"] < current["price"]:
            result[row["shop"]] = row
    return sorted(result.values(), key=lambda row: (row["price"], row["shop"]))


def preview_price_watch(candidates):
    signals = {"POKÉMON": [], "LORCANA": []}
    comparable_count = 0
    for key, rows in grouped_candidates(candidates).items():
        ordered = cheapest_by_shop(rows)
        if len(ordered) < 2:
            continue
        comparable_count += 1
        best_price = ordered[0]["price"]
        next_prices = [row["price"] for row in ordered if row["price"] > best_price + 0.005]
        if not next_prices:
            continue
        next_price = min(next_prices)
        saving_dkk = next_price - best_price
        saving_pct = saving_dkk / next_price * 100.0 if next_price > 0 else 0.0
        if saving_dkk < PRICE_WATCH_DAILY_MIN_SAVING_DKK or saving_pct < PRICE_WATCH_DAILY_MIN_SAVING_PCT:
            continue
        low_shops = sorted({row["shop"] for row in ordered if abs(row["price"] - best_price) < 0.005})
        info = parse_key(key)
        signals[info["game"]].append({
            "key": key,
            "best": ordered[0],
            "shops": low_shops,
            "next_price": next_price,
            "saving_dkk": saving_dkk,
            "saving_pct": saving_pct,
        })

    lines = [
        "🎯 DAGENS KØBSOVERSIGT — MANUEL V25 PREVIEW",
        "Kun tydelige prisfordele. Maks 3 Pokémon + 3 Lorcana.",
        "Prislofter: pack 150 · sleeved 175 · bundle 750 · ETB 1.500 · box 1.750 kr.",
    ]
    for game in ("POKÉMON", "LORCANA"):
        lines.extend(["", game_label(game)])
        selected = sorted(
            signals[game],
            key=lambda row: (row["saving_pct"], row["saving_dkk"]),
            reverse=True,
        )[:PRICE_WATCH_DAILY_MAX_SIGNALS_PER_GAME]
        if not selected:
            lines.append("• Ingen tydelige prisfordele lige nu")
            continue
        for index, row in enumerate(selected, start=1):
            info = parse_key(row["key"])
            lines.append(
                f"{index}. {display_name(row['key'])} · {type_label(info['type'])} — "
                f"{format_price(row['best']['price'])} hos {' + '.join(row['shops'])} · "
                f"næste {format_price(row['next_price'])} · spar {row['saving_pct']:.0f}%"
            )
    return lines, comparable_count


def preview_price_history(state, candidates):
    history = ((state.get("price_history") or {}).get("products") or {})
    current_groups = grouped_candidates(candidates)
    rows = []

    for key, current_rows in current_groups.items():
        entry = history.get(key)
        if not isinstance(entry, dict):
            continue
        ordered = cheapest_by_shop(current_rows)
        if not ordered:
            continue
        current = ordered[0]["price"]
        try:
            low = float(entry.get("historical_low"))
            previous = float(entry.get("previous_best"))
        except (TypeError, ValueError):
            continue
        if low <= 0 or previous <= 0:
            continue
        movement_dkk = abs(current - previous)
        movement_pct = abs((current - previous) / previous * 100.0)
        if movement_dkk < PRICE_ALERT_MIN_IMPROVEMENT_DKK or movement_pct < PRICE_ALERT_MIN_IMPROVEMENT_PCT:
            continue
        diff = (current - low) / low * 100.0
        if diff <= 3.0:
            kind = "SLÅ TIL"
        elif diff >= 10.0:
            kind = "AFVENT"
        else:
            continue
        shops = sorted({row["shop"] for row in ordered if abs(row["price"] - current) < 0.005})
        rows.append({
            "key": key,
            "kind": kind,
            "current": current,
            "low": low,
            "diff": diff,
            "movement_pct": (current - previous) / previous * 100.0,
            "shops": shops,
        })

    rows.sort(
        key=lambda row: (
            0 if row["kind"] == "SLÅ TIL" else 1,
            row["diff"] if row["kind"] == "SLÅ TIL" else -row["diff"],
            display_name(row["key"]).lower(),
        )
    )
    selected = rows[:PRICE_HISTORY_DAILY_MAX_SIGNALS_TOTAL]

    lines = [
        "🎯 PRISUDVIKLING & KØBSSIGNALER — MANUEL V25 PREVIEW",
        "Maks 3 signaler samlet. Kun bevægelser på mindst 25 kr. OG 5%.",
    ]
    if not selected:
        lines.append("✅ Ingen tydelige købssignaler eller afvent-priser lige nu.")
        return lines, 0

    for row in selected:
        emoji = "🟢" if row["kind"] == "SLÅ TIL" else "🟠"
        lines.append(
            f"{emoji} {row['kind']}: {display_name(row['key'])} — "
            f"{format_price(row['current'])} hos {' + '.join(row['shops']) or 'ukendt butik'} · "
            f"historisk low {format_price(row['low'])} · {row['diff']:.0f}% over low · "
            f"seneste ændring {row['movement_pct']:+.0f}%"
        )
    return lines, len(rows)


def main():
    state = load_state()
    fresh = fresh_sources(state)
    candidates = collect_candidates(state, fresh)
    pw_lines, comparable_count = preview_price_watch(candidates)
    ph_lines, history_signal_pool = preview_price_history(state, candidates)
    now = datetime.now(ZoneInfo("Europe/Copenhagen"))

    output = [
        f"V25 PRICE CHANNEL PREVIEW · {now.strftime('%d.%m.%Y %H:%M')}",
        f"Friske aktive kilder: {', '.join(sorted(fresh))}",
        f"Kandidater efter relevans + prislofter: {len(candidates)}",
        f"Sammenlignelige Price Watch-grupper: {comparable_count}",
        f"Price History-signalpulje efter 25 kr./5%-gate: {history_signal_pool}",
        "",
        *pw_lines,
        "",
        "----------------------------------------",
        "",
        *ph_lines,
        "",
        "NOTE: Read-only preview. Ingen netværkskald, Discord-skrivning eller state-ændringer.",
    ]
    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        file.write("\n".join(output) + "\n")
    print("\n".join(output))


if __name__ == "__main__":
    main()
