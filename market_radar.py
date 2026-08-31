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
MIN_MATCH_SCORE = float(os.getenv("MARKET_RADAR_MIN_MATCH_SCORE", "0.90") or 0.90)
MAX_CM_DIVERGENCE_PCT = float(os.getenv("MARKET_RADAR_MAX_CM_DIVERGENCE_PCT", "50") or 50)

# V4 deliberately stays narrow: Pokemon core sealed only.
CARDMARKET = {
    "POKÉMON": {
        "products_url": "https://downloads.s3.cardmarket.com/productCatalog/productList/products_nonsingles_6.json",
        "prices_url": "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_6.json",
        "local_products": "products_nonsingles_6.json",
        "local_prices": "price_guide_6.json",
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
ACCESSORY_EXCEPTIONS = ("binder collection",)

COLLECTION_TYPES = {
    "UPC", "SPC", "PREMIUM COLLECTION", "SPECIAL COLLECTION", "ILLUSTRATION COLLECTION",
    "POSTER COLLECTION", "BINDER COLLECTION", "EX BOX", "V BOX", "VSTAR BOX", "VMAX BOX",
    "COLLECTION BOX", "COLLECTION",
}


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
    if game != "POKÉMON":
        return None

    text = normalize_text(name)
    if not text or not is_english(name) or is_accessory(name):
        return None

    if any(marker in text for marker in ("booster box case", "booster case", "case of booster", "case 6", "case 10")):
        return None
    if re.search(r"\b(?:4|6|8|10|12)\s*x\s*36\b", text):
        return None
    if "display" in text and "booster display" not in text:
        return None
    if "booster bundle display" in text or "bundle display" in text:
        return None

    if any(marker in text for marker in (
        "mini tin", " tin ", "tin box", "booster pack", "booster pakke",
        "sleeved booster", "sleeve booster", "checklane", "blister",
    )):
        return None
    if text.startswith("tin ") or text.endswith(" tin"):
        return None

    if "elite trainer box" in text or re.search(r"\betb\b", text):
        return "PC ETB" if "pokemon center" in text else "ETB"
    if "booster bundle" in text:
        return "BOOSTER BUNDLE"
    if "booster box" in text or "booster display" in text:
        return "BOOSTER BOX"

    if "ultra premium collection" in text or re.search(r"\bupc\b", text):
        return "UPC"
    if "super premium collection" in text or re.search(r"\bspc\b", text):
        return "SPC"
    if "premium collection" in text or "premium figure collection" in text:
        return "PREMIUM COLLECTION"
    if "special collection" in text:
        return "SPECIAL COLLECTION"
    if "illustration collection" in text:
        return "ILLUSTRATION COLLECTION"
    if "poster collection" in text:
        return "POSTER COLLECTION"
    if "binder collection" in text:
        return "BINDER COLLECTION"
    if re.search(r"\bex\b.*\bbox\b", text):
        return "EX BOX"
    if re.search(r"\bvstar\b.*\bbox\b", text):
        return "VSTAR BOX"
    if re.search(r"\bvmax\b.*\bbox\b", text):
        return "VMAX BOX"
    if re.search(r"\bv\b.*\bbox\b", text):
        return "V BOX"
    if "collection box" in text:
        return "COLLECTION BOX"
    if "collection" in text:
        return "COLLECTION"

    return None


def type_family(product_type):
    if product_type in ("ETB", "PC ETB"):
        return product_type
    if product_type == "BOOSTER BUNDLE":
        return "BOOSTER BUNDLE"
    if product_type == "BOOSTER BOX":
        return "BOOSTER BOX"
    if product_type in COLLECTION_TYPES:
        return "COLLECTION"
    return product_type


def canonical_name(name, product_type):
    text = normalize_text(name)
    text = re.sub(r"\b(?:pokemon|pok mon|tcg|trading card game|engelsk|english|sealed)\b", " ", text)
    text = re.sub(r"\b(?:sv|me)\s*\d+(?:\.\d+)?[a-z]?\b", " ", text)
    text = re.sub(r"\bpok[a-z0-9-]*\d[a-z0-9-]*\b", " ", text)

    phrases = {
        "PC ETB": ("pokemon center elite trainer box", "elite trainer box", "etb", "pokemon center"),
        "ETB": ("elite trainer box", "etb"),
        "BOOSTER BOX": ("booster box", "booster display"),
        "BOOSTER BUNDLE": ("booster bundle",),
        "UPC": ("ultra premium collection", "upc"),
        "SPC": ("super premium collection", "spc"),
        "PREMIUM COLLECTION": ("premium figure collection", "premium collection"),
        "SPECIAL COLLECTION": ("special collection",),
        "ILLUSTRATION COLLECTION": ("illustration collection",),
        "POSTER COLLECTION": ("poster collection",),
        "BINDER COLLECTION": ("binder collection",),
        "EX BOX": ("box",),
        "V BOX": ("box",),
        "VSTAR BOX": ("box",),
        "VMAX BOX": ("box",),
        "COLLECTION BOX": ("collection box",),
        "COLLECTION": ("collection box", "collection"),
    }.get(product_type, ())
    for phrase in phrases:
        text = text.replace(phrase, " ")

    text = re.sub(r"\b(?:with|med)\s+\d+\s+(?:packs?|boosters?|boostere|pakker)\b", " ", text)
    text = re.sub(r"\b(?:6|8|9|10|11|12|18|20|24|30|36)\s*(?:packs?|boosters?|boostere|pakker)\b", " ", text)
    text = " ".join(text.split())

    for prefix in ("scarlet and violet", "sword and shield"):
        if text.startswith(prefix + " "):
            remainder = text[len(prefix):].strip()
            if remainder and remainder != "base set" and len(remainder.split()) >= 2:
                text = remainder

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
        if game != "POKÉMON":
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
            "family": type_family(product_type),
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
        group_type = offer["family"]
        key = (offer["game"], group_type, offer["canonical"])
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
    response = requests.get(url, headers={"User-Agent": "Pokemon-Market-Radar/4.0"}, timeout=60)
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
                "family": type_family(product_type),
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
    return 0.50 * containment + 0.30 * jaccard + 0.20 * sequence


def _match_guard(left, right):
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    shared = left_tokens & right_tokens
    if not left_tokens or not right_tokens:
        return False

    if "base" in shared and "set" in shared and left_tokens != right_tokens:
        return False

    return len(shared) >= 2


def match_cardmarket(group, cardmarket_rows):
    game, family, canonical = group["key"]
    candidates = [
        row for row in cardmarket_rows.get(game, [])
        if row.get("family", type_family(row.get("type"))) == family
    ]
    if not candidates or not canonical:
        return None

    exact = [row for row in candidates if row.get("canonical") == canonical]
    if len(exact) == 1:
        result = dict(exact[0])
        result["match_score"] = 1.0
        result["match_method"] = "exact"
        return result

    scored = []
    for row in candidates:
        other = row.get("canonical") or ""
        if not _match_guard(canonical, other):
            continue
        scored.append((token_score(canonical, other), row))
    scored.sort(key=lambda item: item[0], reverse=True)

    if not scored or scored[0][0] < MIN_MATCH_SCORE:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.08:
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


def _dedupe_shop_offers(offers):
    by_shop = {}
    for offer in offers:
        current = by_shop.get(offer["shop"])
        if current is None or offer["price"] < current["price"]:
            by_shop[offer["shop"]] = offer
    return sorted(by_shop.values(), key=lambda row: (row["price"], row["shop"]))


def _cardmarket_reference(cardmarket):
    """Return reference price plus a reliability gate.

    Trend remains the primary benchmark, but when Cardmarket low and trend are
    more than MAX_CM_DIVERGENCE_PCT apart (measured against the smaller value),
    the product is marked unstable and is excluded from buy/overprice rankings.
    A benchmark with only one of the two signals is also not rankable.
    """
    trend = safe_float(cardmarket.get("trend_eur"))
    low = safe_float(cardmarket.get("low_eur"))
    trend_ok = trend is not None and trend > 0
    low_ok = low is not None and low > 0

    if trend_ok and low_ok:
        smaller = min(trend, low)
        divergence_pct = ((max(trend, low) / smaller) - 1.0) * 100.0
        stable = divergence_pct <= MAX_CM_DIVERGENCE_PCT
        return trend, "trend", stable, divergence_pct
    if trend_ok:
        return trend, "trend_only", False, None
    if low_ok:
        return low, "low_only", False, None
    return None, "none", False, None


def consolidate_cardmarket_matches(raw_matches):
    """Collapse Danish aliases after they resolve to the same Cardmarket product."""
    buckets = {}
    for item in raw_matches:
        key = (item["game"], item["cardmarket"]["idProduct"])
        bucket = buckets.setdefault(key, {
            "cardmarket": item["cardmarket"],
            "offers": [],
            "aliases": set(),
            "scores": [],
            "methods": set(),
        })
        bucket["offers"].extend(item["offers"])
        bucket["aliases"].add(item["best"]["name"])
        bucket["scores"].append(item["cardmarket"]["match_score"])
        bucket["methods"].add(item["cardmarket"]["match_method"])

    matched = []
    for (game, _product_id), bucket in buckets.items():
        cardmarket = bucket["cardmarket"]
        offers = _dedupe_shop_offers(bucket["offers"])
        if not offers:
            continue
        best = offers[0]
        low_eur = safe_float(cardmarket.get("low_eur"))
        trend_eur = safe_float(cardmarket.get("trend_eur"))
        low_dkk = low_eur * EUR_DKK if low_eur is not None else None
        trend_dkk = trend_eur * EUR_DKK if trend_eur is not None else None
        reference_eur, reference_kind, price_stable, divergence_pct = _cardmarket_reference(cardmarket)
        reference_dkk = reference_eur * EUR_DKK if reference_eur is not None else None
        diff_reference = (
            ((best["price"] / reference_dkk) - 1.0) * 100.0
            if reference_dkk and reference_dkk > 0 else None
        )
        diff_low = (
            ((best["price"] / low_dkk) - 1.0) * 100.0
            if low_dkk and low_dkk > 0 else None
        )
        value_status = "UNSTABLE_CM_PRICE"
        if price_stable and diff_reference is not None:
            if diff_reference <= -10:
                value_status = "EU_KUP"
            elif diff_reference <= 0:
                value_status = "KUP"
            elif diff_reference <= 15:
                value_status = "FAIR"
            else:
                value_status = "OVERPRIS"

        matched.append({
            "game": game,
            "type": cardmarket.get("type") or best["type"],
            "family": cardmarket.get("family") or best["family"],
            "name": cardmarket["name"],
            "dk_name": best["name"],
            "dk_price": best["price"],
            "shop": best["shop"],
            "url": best["url"],
            "shops": len(offers),
            "shop_prices": [
                {"shop": row["shop"], "price": row["price"], "url": row["url"], "name": row["name"]}
                for row in offers
            ],
            "aliases": sorted(bucket["aliases"]),
            "cm_product_id": cardmarket["idProduct"],
            "cm_name": cardmarket["name"],
            "cm_type": cardmarket.get("type"),
            "cm_low_eur": low_eur,
            "cm_trend_eur": trend_eur,
            "cm_low_dkk": low_dkk,
            "cm_trend_dkk": trend_dkk,
            "cm_reference_eur": reference_eur,
            "cm_reference_dkk": reference_dkk,
            "cm_reference_kind": reference_kind,
            "cm_price_stable": price_stable,
            "cm_divergence_pct": divergence_pct,
            "rankable": price_stable,
            "value_status": value_status,
            "diff_pct_vs_reference": diff_reference,
            "diff_pct_vs_low": diff_low,
            "match_score": min(bucket["scores"]) if bucket["scores"] else None,
            "match_methods": sorted(bucket["methods"]),
            "alias_groups_merged": len(bucket["aliases"]),
        })

    matched.sort(key=lambda row: (
        0 if row["rankable"] else 1,
        9999 if row["diff_pct_vs_reference"] is None else row["diff_pct_vs_reference"],
        row["dk_price"],
    ))
    return matched


def build_radar(state):
    offers = collect_danish_offers(state)
    groups = group_danish_offers(offers)
    cardmarket_rows, cardmarket_meta = load_cardmarket()
    raw_matches = []
    unmatched = []

    for group in groups:
        cardmarket = match_cardmarket(group, cardmarket_rows)
        if not cardmarket:
            unmatched.append(group)
            continue
        raw_matches.append({
            "game": group["best"]["game"],
            "best": group["best"],
            "offers": group["offers"],
            "cardmarket": cardmarket,
        })

    matched = consolidate_cardmarket_matches(raw_matches)

    type_counts = {}
    for row in matched:
        type_counts[row["type"]] = type_counts.get(row["type"], 0) + 1
    stable_count = sum(1 for row in matched if row["rankable"])
    unstable_count = len(matched) - stable_count

    return {
        "version": 4,
        "scope": "pokemon_core_sealed",
        "benchmark": "cardmarket_trend_with_stability_gate",
        "cm_max_divergence_pct": MAX_CM_DIVERGENCE_PCT,
        "generated_at": datetime.now(ZoneInfo(TZ_NAME)).isoformat(),
        "eur_dkk_used": EUR_DKK,
        "danish_offer_lines": len(offers),
        "danish_groups": len(groups),
        "matched_alias_groups": len(raw_matches),
        "matched_groups": len(matched),
        "stable_price_groups": stable_count,
        "unstable_price_groups": unstable_count,
        "merged_alias_groups": len(raw_matches) - len(matched),
        "unmatched_groups": len(unmatched),
        "matched_type_counts": dict(sorted(type_counts.items())),
        "cardmarket_meta": cardmarket_meta,
        "matched": matched,
        "unmatched": [
            {"game": group["best"]["game"], "type": group["best"]["type"], "name": group["best"]["name"],
             "price": group["best"]["price"], "shop": group["best"]["shop"]}
            for group in unmatched[:100]
        ],
    }


def make_embed(radar):
    stable = [
        row for row in radar["matched"]
        if row.get("rankable") and row.get("diff_pct_vs_reference") is not None
    ]
    unstable = [row for row in radar["matched"] if not row.get("rankable")]
    best = stable[:10]
    overpriced = sorted(stable, key=lambda row: row["diff_pct_vs_reference"], reverse=True)[:5]
    unstable = sorted(
        unstable,
        key=lambda row: -1 if row.get("cm_divergence_pct") is None else -row["cm_divergence_pct"],
    )[:5]

    lines = [
        f"**{radar['matched_groups']}** unikke core sealed-produkter · "
        f"**{radar['stable_price_groups']}** med stabil CM-reference · "
        f"**{radar['unstable_price_groups']}** markeret ustabile.",
        "", "🟢 **BEDSTE OBSERVEREDE DK-PRISER VS. CARDMARKET TREND**",
    ]
    for row in best:
        sign = "+" if row["diff_pct_vs_reference"] >= 0 else ""
        lines.append(
            f"• **{row['cm_name']}** — {fmt_dkk(row['dk_price'])} hos {row['shop']} · "
            f"CM ref {fmt_eur(row['cm_reference_eur'])} · **{sign}{row['diff_pct_vs_reference']:.0f}%**"
        )
    if overpriced:
        lines += ["", "🔴 **STØRSTE DK-MARKUPS · KUN STABILE CM-PRISER**"]
        for row in overpriced:
            sign = "+" if row["diff_pct_vs_reference"] >= 0 else ""
            lines.append(
                f"• **{row['cm_name']}** — {fmt_dkk(row['dk_price'])} · "
                f"CM ref {fmt_eur(row['cm_reference_eur'])} · **{sign}{row['diff_pct_vs_reference']:.0f}%**"
            )
    if unstable:
        lines += ["", "⚠️ **USTABIL CARDMARKET-PRIS · IKKE RANKET**"]
        for row in unstable:
            divergence = "mangler dobbelt signal" if row.get("cm_divergence_pct") is None else f"{row['cm_divergence_pct']:.0f}% spænd"
            lines.append(
                f"• **{row['cm_name']}** — DK {fmt_dkk(row['dk_price'])} · "
                f"CM low {fmt_eur(row['cm_low_eur'])} / trend {fmt_eur(row['cm_trend_eur'])} · {divergence}"
            )
    return {
        "title": "🛰️ MARKET RADAR V4 · CORE SEALED",
        "description": "\n".join(lines)[:4096],
        "color": 0x5865F2,
        "footer": {
            "text": "Bedste offentligt observerede DK-webpris · CM trend er reference · low/trend >50% fra hinanden rankes ikke · ekskl. fragt"
        },
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
        f"MARKET RADAR V4 CORE SEALED: {radar['danish_offer_lines']} DK prislinjer | "
        f"{radar['danish_groups']} alias-grupper | {radar['matched_groups']} unikke CM produkter | "
        f"{radar['stable_price_groups']} stabile | {radar['unstable_price_groups']} ustabile | "
        f"{radar['merged_alias_groups']} aliases samlet | {radar['unmatched_groups']} usikre holdt ude"
    )
    if SHADOW:
        print("MARKET RADAR: shadow mode - Discord ikke sendt.")
        return 0
    if not WEBHOOK:
        raise RuntimeError("MARKET_RADAR_WEBHOOK_URL mangler")
    post_discord(make_embed(radar))
    radar_state.update({
        "version": 4,
        "last_daily_date": today,
        "last_sent_at": now.isoformat(),
        "last_match_count": radar["matched_groups"],
        "last_stable_count": radar["stable_price_groups"],
        "last_unstable_count": radar["unstable_price_groups"],
    })
    save_json(RADAR_STATE_FILE, radar_state)
    print("MARKET RADAR: daglig rapport sendt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
