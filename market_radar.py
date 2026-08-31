import json
import math
import os
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

STATE_FILE = Path(os.getenv("MARKET_RADAR_RESTOCK_STATE", "restock_state_v2.json"))
RADAR_STATE_FILE = Path(os.getenv("MARKET_RADAR_STATE_FILE", "market_radar_state.json"))
PREVIEW_FILE = Path(os.getenv("MARKET_RADAR_PREVIEW_FILE", "market_radar_preview.json"))
WEBHOOK = os.getenv("MARKET_RADAR_WEBHOOK_URL", "").strip()
TZ_NAME = os.getenv("MARKET_RADAR_TIMEZONE", "Europe/Copenhagen").strip() or "Europe/Copenhagen"
DAILY_HOUR = max(0, min(23, int(os.getenv("MARKET_RADAR_DAILY_HOUR", "9") or 9)))
FORCE = os.getenv("MARKET_RADAR_FORCE_RUN", "0") == "1"
SHADOW = os.getenv("MARKET_RADAR_SHADOW", "1") == "1"
EUR_DKK = float(os.getenv("MARKET_RADAR_EUR_DKK", "7.46") or 7.46)
MIN_MATCH_SCORE = float(os.getenv("MARKET_RADAR_MIN_MATCH_SCORE", "0.86") or 0.86)

CARDMARKET = {
    "POKÉMON": {
        "products_url": "https://downloads.s3.cardmarket.com/productCatalog/productList/products_nonsingles_6.json",
        "prices_url": "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_6.json",
        "local_products": "products_nonsingles_6.json",
        "local_prices": "price_guide_6.json",
    },
    "LORCANA": {
        "products_url": "https://downloads.s3.cardmarket.com/productCatalog/productList/products_nonsingles_19.json",
        "prices_url": "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_19.json",
        "local_products": "products_nonsingles_19.json",
        "local_prices": "price_guide_19.json",
    },
}

SOURCE_LABELS = {
    "coolshop": "COOLSHOP", "proshop": "PROSHOP", "br": "BR", "bilka": "BILKA",
    "foetex": "FØTEX", "pokehulen": "POKEHULEN", "rogerz": "ROGERZ",
    "mtgwebshop": "MTGWEBSHOP", "luckbox": "LUCKBOX", "spilforsyningen": "SPILFORSYNINGEN",
    "musenogslottet": "MUSEN & SLOTTET", "symbizon": "SYMBIZON", "cardx": "CARDX",
    "matraws": "MATRAWS", "halmeshule": "HALMES HULE", "cardsdirect": "CARDSDIRECT",
    "baltzer": "BALTZER GAMES", "tcgshoppen": "TCG SHOPPEN", "pokemonsdk": "POKEMONS.DK",
    "pocketmonster": "POCKET MONSTER", "funshop": "FUN-SHOP", "pokepulls": "POKÉPULLS",
    "staalz": "STAALZ", "pbcards": "PBCARDS", "kocardz": "KOCARDZ", "vaulted": "VAULTED",
    "pokedexet": "POKEDEXET", "pokemonportalen": "POKEMONPORTALEN", "tcgbruus": "TCGBRUUS",
    "pokemonplaza": "POKEMON PLAZA", "kelz0r": "KELZ0R", "faraos": "FARAOS",
    "goblingames": "GOBLIN GAMES", "hyggeonkel": "HYGGEONKEL", "nostalgic": "NOSTALGIC",
    "andcards": "ANDCARDS", "pokecards": "POKECARDS.DK", "epicpanda": "EPIC PANDA",
    "steffeno": "STEFFEN-O", "nextlevel": "NEXT LEVEL GAMES",
}

TOP_LEVEL_SOURCES = {"coolshop", "proshop", "br", "bilka", "foetex", "epicpanda", "steffeno", "nextlevel"}
FOREIGN_MARKERS = (
    "japansk", "japanese", "japan import", "kinesisk", "chinese", "koreansk", "korean",
    "tysk", "german", "deutsch", "fransk", "french", "italiensk", "italian", "spansk",
    "spanish", "portugisisk", "portuguese", "hollandsk", "dutch", "thai", "indonesisk",
    "indonesian",
)
ACCESSORY_MARKERS = (
    "portfolio", "binder", "mappe", "album", "sleeves", "card sleeve", "deck box", "deckbox",
    "playmat", "play mat", "toploader", "top loader", "storage box", "acrylic", "acryl", "akryl",
    "display case", "card case", "penalhus", "pencil case", "repack",
)
ACCESSORY_EXCEPTIONS = ("binder collection", "playmat collection", "play mat collection", "sleeved booster")


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def save_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_float(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_text(value):
    value = unicodedata.normalize("NFKD", str(value or "").lower())
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.replace("’", "'").replace("–", " ").replace("—", " ").replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def is_english(name):
    text = " " + normalize_text(name) + " "
    return not any(" " + normalize_text(marker) + " " in text for marker in FOREIGN_MARKERS)


def is_accessory(name):
    text = " " + normalize_text(name) + " "
    if any(" " + normalize_text(marker) + " " in text for marker in ACCESSORY_EXCEPTIONS):
        return False
    return any(" " + normalize_text(marker) + " " in text for marker in ACCESSORY_MARKERS)


def infer_type(name, game):
    text = normalize_text(name)
    if not is_english(name) or is_accessory(name):
        return None
    if any(marker in text for marker in ("booster box case", "booster case", "case of booster")):
        return None
    if re.search(r"\b(?:4|6|8|10|12)\s*x\s*36\b", text):
        return None
    if "booster bundle display" in text or "bundle display" in text:
        return None
    if game == "POKÉMON" and ("elite trainer box" in text or re.search(r"\betb\b", text)):
        if "pokemon center" in text:
            return "PC ETB"
        return "ETB"
    if "booster box" in text or "booster display" in text:
        return "BOOSTER BOX"
    if "booster bundle" in text:
        return "BOOSTER BUNDLE"
    if "sleeved booster" in text or "sleeve booster" in text:
        return "SLEEVED BOOSTER"
    if "booster pack" in text:
        return "BOOSTER PACK"
    if "booster" in text and not any(x in text for x in ("box", "bundle", "display", "collection")):
        return "BOOSTER PACK"
    if "ultra premium collection" in text or re.search(r"\bupc\b", text):
        return "COLLECTION"
    if "premium collection" in text or "special collection" in text or "collection box" in text:
        return "COLLECTION"
    if "collection" in text and game == "POKÉMON":
        return "COLLECTION"
    if "tin" in text and game == "POKÉMON":
        return "TIN"
    if "blister" in text and game == "POKÉMON":
        return "BLISTER"
    if game == "LORCANA" and ("illumineer s trove" in text or "illumineers trove" in text):
        return "TROVE"
    if game == "LORCANA" and "gift set" in text:
        return "GIFT SET"
    return None


def canonical_name(name, product_type):
    text = normalize_text(name)
    text = re.sub(r"\b(?:pokemon|pok mon|tcg|trading card game|disney|lorcana|engelsk|english)\b", " ", text)
    text = re.sub(r"\b(?:sv|me)\s*\d+(?:\.\d+)?[a-z]?\b", " ", text)
    text = re.sub(r"\b(?:pok|dis|lor)[a-z0-9-]*\d[a-z0-9-]*\b", " ", text)
    phrases = {
        "PC ETB": ("pokemon center elite trainer box", "elite trainer box", "etb"),
        "ETB": ("elite trainer box", "etb"),
        "BOOSTER BOX": ("booster box", "booster display", "display"),
        "BOOSTER BUNDLE": ("booster bundle",),
        "SLEEVED BOOSTER": ("sleeved booster", "sleeve booster"),
        "BOOSTER PACK": ("booster pack", "booster pakke", "booster"),
        "COLLECTION": ("ultra premium collection", "premium collection", "special collection", "collection box", "collection"),
        "TIN": ("tin box", "tin"),
        "BLISTER": ("3 pack blister", "2 pack blister", "1 pack blister", "blister"),
        "TROVE": ("illumineer s trove", "illumineers trove", "trove"),
        "GIFT SET": ("gift set",),
    }.get(product_type, ())
    for phrase in phrases:
        text = text.replace(phrase, " ")
    text = re.sub(r"\b(?:6|10|18|20|24|30|36)\s*(?:packs?|boosters?|boostere|pakker)\b", " ", text)
    text = re.sub(r"\b(?:scarlet and violet|sword and shield|mega evolution)\b", " ", text)
    return " ".join(text.split())


def product_buyable(product):
    if not isinstance(product, dict) or product.get("preorder") is True:
        return False
    if product.get("in_stock") is True or product.get("online_stock") is True:
        return True
    for key in ("online_count", "store_count", "kolding_stock", "esbjerg_stock"):
        if safe_int(product.get(key), 0) > 0:
            return True
    stock = product.get("stock")
    numeric_stock = safe_float(stock)
    if numeric_stock is not None and numeric_stock > 0:
        return True
    if normalize_text(stock) in ("pa lager", "in stock", "available"):
        return True
    for store in (product.get("local_stocks") or {}).values():
        if safe_int((store or {}).get("stock"), 0) > 0:
            return True
    return False


def _iter_products(mapping, source_key, default_game=None):
    if not isinstance(mapping, dict):
        return
    for product in mapping.values():
        if not isinstance(product, dict) or not product.get("name"):
            continue
        game = product.get("game") or default_game
        if game not in ("POKÉMON", "LORCANA"):
            continue
        price = safe_float(product.get("price"))
        if price is None or price <= 0 or not product_buyable(product):
            continue
        product_type = infer_type(product.get("name"), game)
        if not product_type:
            continue
        yield {
            "source": source_key,
            "shop": SOURCE_LABELS.get(source_key, source_key.upper()),
            "game": game,
            "name": str(product.get("name")),
            "price": price,
            "url": str(product.get("url") or ""),
            "type": product_type,
            "canonical": canonical_name(product.get("name"), product_type),
        }


def collect_danish_offers(state):
    offers = []
    for source_key in TOP_LEVEL_SOURCES:
        default_game = "POKÉMON" if source_key in {"proshop", "br", "bilka", "foetex", "steffeno"} else None
        offers.extend(_iter_products(state.get(source_key), source_key, default_game) or [])
    for container_key in ("shopify", "woocommerce"):
        container = state.get(container_key) or {}
        if not isinstance(container, dict):
            continue
        for source_key, products in container.items():
            offers.extend(_iter_products(products, source_key) or [])
    return offers


def group_danish_offers(offers):
    groups = {}
    for offer in offers:
        key = (offer["game"], offer["type"], offer["canonical"])
        groups.setdefault(key, []).append(offer)
    output = []
    for key, rows in groups.items():
        by_shop = {}
        for row in rows:
            current = by_shop.get(row["shop"])
            if current is None or row["price"] < current["price"]:
                by_shop[row["shop"]] = row
        rows = sorted(by_shop.values(), key=lambda x: (x["price"], x["shop"]))
        if rows:
            output.append({"key": key, "best": rows[0], "offers": rows})
    return output


def fetch_json(url, local_name):
    local_dir = os.getenv("MARKET_RADAR_LOCAL_DATA_DIR", "").strip()
    if local_dir:
        path = Path(local_dir) / local_name
        if path.exists():
            return load_json(path, {})
    response = requests.get(url, headers={"User-Agent": "Pokemon-Market-Radar/1.0"}, timeout=60)
    response.raise_for_status()
    return response.json()


def load_cardmarket():
    output = {}
    meta = {}
    for game, config in CARDMARKET.items():
        products_doc = fetch_json(config["products_url"], config["local_products"])
        prices_doc = fetch_json(config["prices_url"], config["local_prices"])
        price_by_id = {
            safe_int(row.get("idProduct")): row
            for row in prices_doc.get("priceGuides", [])
            if safe_int(row.get("idProduct"))
        }
        rows = []
        for product in products_doc.get("products", []):
            name = str(product.get("name") or "")
            product_type = infer_type(name, game)
            if not product_type:
                continue
            product_id = safe_int(product.get("idProduct"))
            price = price_by_id.get(product_id)
            if not price:
                continue
            low = safe_float(price.get("low"))
            trend = safe_float(price.get("trend"))
            if low is None and trend is None:
                continue
            rows.append({
                "idProduct": product_id,
                "name": name,
                "type": product_type,
                "canonical": canonical_name(name, product_type),
                "low_eur": low,
                "trend_eur": trend,
                "category": product.get("categoryName") or "",
            })
        output[game] = rows
        meta[game] = {
            "products_created_at": products_doc.get("createdAt"),
            "prices_created_at": prices_doc.get("createdAt"),
            "candidate_count": len(rows),
        }
    return output, meta


def token_score(left, right):
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    jaccard = intersection / union if union else 0.0
    sequence = SequenceMatcher(None, left, right).ratio()
    containment = intersection / min(len(left_tokens), len(right_tokens))
    return 0.45 * containment + 0.35 * jaccard + 0.20 * sequence


def match_cardmarket(group, cardmarket_rows):
    game, product_type, canonical = group["key"]
    candidates = [row for row in cardmarket_rows.get(game, []) if row["type"] == product_type]
    if not candidates:
        return None
    exact = [row for row in candidates if row["canonical"] == canonical and canonical]
    if len(exact) == 1:
        result = dict(exact[0])
        result["match_score"] = 1.0
        result["match_method"] = "exact"
        return result
    scored = sorted(
        ((token_score(canonical, row["canonical"]), row) for row in candidates),
        key=lambda item: item[0],
        reverse=True,
    )
    if not scored or scored[0][0] < MIN_MATCH_SCORE:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.04:
        return None
    result = dict(scored[0][1])
    result["match_score"] = round(scored[0][0], 3)
    result["match_method"] = "fuzzy"
    return result


def fmt_dkk(value):
    return f"{value:,.0f} kr.".replace(",", ".")


def fmt_eur(value):
    if value is None:
        return "–"
    return f"€{value:.2f}".replace(".", ",")


def build_radar(state):
    offers = collect_danish_offers(state)
    groups = group_danish_offers(offers)
    cardmarket_rows, cardmarket_meta = load_cardmarket()
    matched = []
    unmatched = []
    for group in groups:
        cardmarket = match_cardmarket(group, cardmarket_rows)
        if not cardmarket:
            unmatched.append(group)
            continue
        best = group["best"]
        low_dkk = cardmarket["low_eur"] * EUR_DKK if cardmarket.get("low_eur") is not None else None
        trend_dkk = cardmarket["trend_eur"] * EUR_DKK if cardmarket.get("trend_eur") is not None else None
        benchmark = low_dkk if low_dkk and low_dkk > 0 else trend_dkk
        diff_pct = ((best["price"] / benchmark) - 1.0) * 100.0 if benchmark and benchmark > 0 else None
        matched.append({
            "game": best["game"], "type": best["type"], "name": best["name"],
            "dk_price": best["price"], "shop": best["shop"], "url": best["url"],
            "shops": len(group["offers"]), "cm_product_id": cardmarket["idProduct"],
            "cm_name": cardmarket["name"], "cm_low_eur": cardmarket.get("low_eur"),
            "cm_trend_eur": cardmarket.get("trend_eur"), "cm_low_dkk": low_dkk,
            "cm_trend_dkk": trend_dkk, "diff_pct_vs_low": diff_pct,
            "match_score": cardmarket["match_score"], "match_method": cardmarket["match_method"],
        })
    matched.sort(key=lambda row: (9999 if row["diff_pct_vs_low"] is None else row["diff_pct_vs_low"], row["dk_price"]))
    return {
        "generated_at": datetime.now(ZoneInfo(TZ_NAME)).isoformat(),
        "eur_dkk_used": EUR_DKK,
        "danish_offer_lines": len(offers),
        "danish_groups": len(groups),
        "matched_groups": len(matched),
        "unmatched_groups": len(unmatched),
        "cardmarket_meta": cardmarket_meta,
        "matched": matched,
        "unmatched": [
            {"game": group["best"]["game"], "type": group["best"]["type"], "name": group["best"]["name"],
             "price": group["best"]["price"], "shop": group["best"]["shop"]}
            for group in unmatched[:100]
        ],
    }


def make_embed(radar):
    rows = [row for row in radar["matched"] if row.get("diff_pct_vs_low") is not None]
    best = rows[:10]
    overpriced = sorted(rows, key=lambda row: row["diff_pct_vs_low"], reverse=True)[:5]
    lines = [
        f"**{radar['matched_groups']}** produkter matchet sikkert mod Cardmarket · **{radar['unmatched_groups']}** holdt ude pga. usikkert match.",
        "", "🟢 **BEDSTE DK-PRISER VS. CARDMARKET LOW**",
    ]
    for row in best:
        sign = "+" if row["diff_pct_vs_low"] >= 0 else ""
        lines.append(
            f"• **{row['name']}** — {fmt_dkk(row['dk_price'])} hos {row['shop']} · "
            f"CM {fmt_eur(row['cm_low_eur'])} · **{sign}{row['diff_pct_vs_low']:.0f}%**"
        )
    if overpriced:
        lines += ["", "🔴 **STØRSTE DK-MARKUPS VS. CARDMARKET LOW**"]
        for row in overpriced:
            sign = "+" if row["diff_pct_vs_low"] >= 0 else ""
            lines.append(
                f"• **{row['name']}** — {fmt_dkk(row['dk_price'])} · CM {fmt_eur(row['cm_low_eur'])} · "
                f"**{sign}{row['diff_pct_vs_low']:.0f}%**"
            )
    return {
        "title": "🛰️ MARKET RADAR · DANMARK VS. CARDMARKET",
        "description": "\n".join(lines)[:4096],
        "color": 0x5865F2,
        "footer": {"text": "Cardmarket low/trend er dagens prisguide og ekskl. fragt · kun sikre produktmatches vises"},
    }


def post_discord(embed):
    response = requests.post(
        WEBHOOK,
        json={"username": "MasterBot", "allowed_mentions": {"parse": []}, "embeds": [embed]},
        timeout=30,
    )
    response.raise_for_status()


def main():
    now = datetime.now(ZoneInfo(TZ_NAME))
    radar_state = load_json(RADAR_STATE_FILE, {})
    today = now.date().isoformat()
    due = FORCE or (now.hour >= DAILY_HOUR and radar_state.get("last_daily_date") != today)
    if not due:
        print(f"MARKET RADAR: ikke due endnu (sidst={radar_state.get('last_daily_date') or '-'}).")
        return 0
    state = load_json(STATE_FILE, {})
    if not state:
        raise RuntimeError(f"Market Radar kunne ikke læse {STATE_FILE}")
    radar = build_radar(state)
    save_json(PREVIEW_FILE, radar)
    print(
        f"MARKET RADAR V1: {radar['danish_offer_lines']} DK prislinjer | {radar['danish_groups']} grupper | "
        f"{radar['matched_groups']} sikre CM matches | {radar['unmatched_groups']} usikre holdt ude"
    )
    if SHADOW:
        print("MARKET RADAR: shadow mode - Discord ikke sendt.")
        return 0
    if not WEBHOOK:
        raise RuntimeError("MARKET_RADAR_WEBHOOK_URL mangler")
    post_discord(make_embed(radar))
    radar_state.update({
        "version": 1,
        "last_daily_date": today,
        "last_sent_at": now.isoformat(),
        "last_match_count": radar["matched_groups"],
    })
    save_json(RADAR_STATE_FILE, radar_state)
    print("MARKET RADAR: daglig rapport sendt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
