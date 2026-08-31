import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

import requests

try:
    from requests_oauthlib import OAuth1
except ImportError:
    OAuth1 = None

import market_radar as v5

PREVIEW_FILE = Path(os.getenv("MARKET_RADAR_V6_PREVIEW_FILE", "market_radar_v6_preview.json"))
ALLOWLIST_FILE = Path(os.getenv("MARKET_RADAR_DK_SHIPPING_ALLOWLIST", "market_radar_dk_shipping_allowlist.json"))
TZ_NAME = os.getenv("MARKET_RADAR_TIMEZONE", "Europe/Copenhagen").strip() or "Europe/Copenhagen"
CARDMARKET_API_BASE = "https://apiv2.cardmarket.com/ws/v2.0/output.json"
CARDMARKET_APP_TOKEN = os.getenv("CARDMARKET_APP_TOKEN", "").strip()
CARDMARKET_APP_SECRET = os.getenv("CARDMARKET_APP_SECRET", "").strip()
CARDMARKET_ACCESS_TOKEN = os.getenv("CARDMARKET_ACCESS_TOKEN", "").strip()
CARDMARKET_ACCESS_SECRET = os.getenv("CARDMARKET_ACCESS_SECRET", "").strip()
MAX_PRODUCTS = max(1, int(os.getenv("MARKET_RADAR_V6_MAX_PRODUCTS", "150") or 150))
REQUEST_DELAY = max(0.0, float(os.getenv("MARKET_RADAR_V6_REQUEST_DELAY", "0.15") or 0.15))

# V6 is intentionally fail-closed. A product is not called actionable unless:
# 1) the DK product identity is exact and sufficiently specific,
# 2) a concrete English Cardmarket article exists,
# 3) the listing comment has no obvious damage/opened warning,
# 4) delivery to Denmark is verified. For now, Danish Cardmarket sellers are
#    automatically verified; foreign sellers require an explicit allowlist entry.

DAMAGE_MARKERS = (
    "damaged", "damage", "dented", "dent", "crushed", "crease", "creased",
    "tear", "torn", "ripped", "corner damage", "box damage", "packaging damage",
    "opened", "open box", "unsealed", "resealed", "broken seal", "seal broken",
    "beschadigt", "beschädigt", "schaden", "delle", "geoffnet", "geöffnet",
    "offen", "eingerissen", "knick", "defekt",
)

SPECIFIC_COLLECTION_MARKERS = (
    " ex ", " v ", " vstar ", " vmax ", " gx ", " premium ", " special ",
    " illustration ", " poster ", " binder ", " figure ", " deluxe ", " pin ",
    " ultra ", " super ", " trainer ", " collection box ",
)


def _load_allowlist():
    try:
        data = json.loads(ALLOWLIST_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    sellers = data.get("confirmed_sellers") or []
    return {str(value).strip().lower() for value in sellers if str(value).strip()}


def _credentials_available():
    return bool(
        OAuth1
        and CARDMARKET_APP_TOKEN
        and CARDMARKET_APP_SECRET
        and CARDMARKET_ACCESS_TOKEN
        and CARDMARKET_ACCESS_SECRET
    )


def _oauth(url):
    return OAuth1(
        client_key=CARDMARKET_APP_TOKEN,
        client_secret=CARDMARKET_APP_SECRET,
        resource_owner_key=CARDMARKET_ACCESS_TOKEN,
        resource_owner_secret=CARDMARKET_ACCESS_SECRET,
        signature_method="HMAC-SHA1",
        signature_type="AUTH_HEADER",
        realm=url,
    )


def _extract_articles(payload):
    if not isinstance(payload, dict):
        return []
    for key in ("article", "articles"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return [value]
    return []


def _article_language_id(article):
    language = article.get("language")
    if isinstance(language, dict):
        return v5.safe_int(language.get("idLanguage"), 0)
    return v5.safe_int(article.get("idLanguage"), 0)


def _seller(article):
    value = article.get("seller")
    return value if isinstance(value, dict) else {}


def _seller_username(article):
    seller = _seller(article)
    return str(seller.get("username") or seller.get("name") or "").strip()


def _seller_country(article):
    seller = _seller(article)
    address = seller.get("address")
    if isinstance(address, dict) and address.get("country"):
        return str(address.get("country")).strip().upper()
    return str(seller.get("country") or "").strip().upper()


def _comment_has_damage(comment):
    text = " " + v5.normalize_text(comment) + " "
    return any(v5.normalize_text(marker) in text for marker in DAMAGE_MARKERS)


def _delivery_verified(article, allowlist):
    username = _seller_username(article).lower()
    country = _seller_country(article)
    if country == "DK":
        return True, "seller_in_denmark"
    if username and username in allowlist:
        return True, "seller_allowlisted_for_dk"
    return False, "foreign_shipping_not_verified"


def _identity_gate(row):
    methods = set(row.get("match_methods") or [])
    if methods != {"exact"}:
        return False, "NON_EXACT_CARDMARKET_MATCH"

    dk_name = str(row.get("dk_name") or "")
    product_type = str(row.get("type") or "")
    family = str(row.get("family") or "")
    canonical = v5.canonical_name(dk_name, product_type)
    normalized = " " + v5.normalize_text(dk_name) + " "

    # Generic set-level collection names are too ambiguous. Example:
    # "Ascended Heroes Collection" can refer to several distinct sealed boxes.
    if family == "COLLECTION" and product_type == "COLLECTION":
        has_specific_marker = any(marker in normalized for marker in SPECIFIC_COLLECTION_MARKERS)
        token_count = len(canonical.split())
        if token_count <= 3 and not has_specific_marker:
            return False, "UNRESOLVED_VARIANT"

    return True, "EXACT_PRODUCT"


def _fetch_articles(product_id):
    url = f"{CARDMARKET_API_BASE}/articles/{int(product_id)}"
    params = {
        "idLanguage": 1,
        "start": 0,
        "maxResults": 100,
    }
    response = requests.get(
        url,
        params=params,
        auth=_oauth(url),
        headers={"Accept": "application/json", "User-Agent": "Pokemon-Market-Radar/6.0"},
        timeout=30,
        allow_redirects=False,
    )
    if response.status_code == 307 and response.headers.get("Location"):
        redirected = response.headers["Location"]
        response = requests.get(
            redirected,
            auth=_oauth(redirected.split("?", 1)[0]),
            headers={"Accept": "application/json", "User-Agent": "Pokemon-Market-Radar/6.0"},
            timeout=30,
        )
    response.raise_for_status()
    return _extract_articles(response.json())


def _validate_articles(articles, allowlist):
    valid = []
    rejected = {
        "non_english": 0,
        "damaged_or_opened": 0,
        "seller_on_vacation": 0,
        "delivery_unverified": 0,
        "invalid_price": 0,
    }

    for article in articles:
        if not isinstance(article, dict):
            continue
        if _article_language_id(article) != 1:
            rejected["non_english"] += 1
            continue

        price = v5.safe_float(article.get("price"))
        if price is None or price <= 0:
            rejected["invalid_price"] += 1
            continue

        comment = str(article.get("comments") or "")
        if _comment_has_damage(comment):
            rejected["damaged_or_opened"] += 1
            continue

        seller = _seller(article)
        if seller.get("onVacation") is True:
            rejected["seller_on_vacation"] += 1
            continue

        delivery_ok, delivery_reason = _delivery_verified(article, allowlist)
        if not delivery_ok:
            rejected["delivery_unverified"] += 1
            continue

        valid.append({
            "idArticle": v5.safe_int(article.get("idArticle"), 0),
            "price_eur": price,
            "seller": _seller_username(article),
            "seller_country": _seller_country(article),
            "seller_reputation": seller.get("reputation"),
            "seller_sell_count": seller.get("sellCount"),
            "comments": comment[:300],
            "delivery_verification": delivery_reason,
            "language": "English",
            "sealed_basis": "Cardmarket non-single product + no opened/damage warning",
        })

    valid.sort(key=lambda row: (row["price_eur"], row["seller"]))
    return valid, rejected


def _listing_signal(dk_price, listings):
    if not listings:
        return None
    prices = [row["price_eur"] for row in listings]
    floor_eur = prices[0]
    floor_dkk = floor_eur * v5.EUR_DKK
    median_eur = median(prices[: min(5, len(prices))])
    median_dkk = median_eur * v5.EUR_DKK
    diff_floor_pct = ((dk_price / floor_dkk) - 1.0) * 100.0 if floor_dkk > 0 else None
    diff_median_pct = ((dk_price / median_dkk) - 1.0) * 100.0 if median_dkk > 0 else None
    return {
        "actionable_floor_eur": floor_eur,
        "actionable_floor_dkk": floor_dkk,
        "top5_median_eur": median_eur,
        "top5_median_dkk": median_dkk,
        "diff_pct_vs_actionable_floor": diff_floor_pct,
        "diff_pct_vs_top5_median": diff_median_pct,
    }


def build_v6():
    state = v5.load_json(v5.STATE_FILE, {})
    if not state:
        raise RuntimeError(f"Market Radar V6 kunne ikke læse {v5.STATE_FILE}")

    base = v5.build_radar(state)
    allowlist = _load_allowlist()
    api_ready = _credentials_available()
    rows = []
    exact_identity = 0
    unresolved_identity = 0
    api_errors = 0
    actionable = 0

    for index, row in enumerate(base.get("matched") or []):
        item = dict(row)
        identity_ok, identity_status = _identity_gate(item)
        item["identity_status"] = identity_status
        item["identity_verified"] = identity_ok
        item["listing_validation_status"] = "NOT_CHECKED"
        item["concrete_listings"] = []
        item["article_filter_rejections"] = {}
        item["actionable"] = False
        item["v5_price_guide_is_info_only"] = True

        if not identity_ok:
            unresolved_identity += 1
            item["listing_validation_status"] = "IDENTITY_UNRESOLVED"
            rows.append(item)
            continue

        exact_identity += 1

        if not api_ready:
            item["listing_validation_status"] = "CARDMARKET_API_CREDENTIALS_MISSING"
            rows.append(item)
            continue

        if index >= MAX_PRODUCTS:
            item["listing_validation_status"] = "API_VALIDATION_LIMIT_REACHED"
            rows.append(item)
            continue

        try:
            articles = _fetch_articles(item["cm_product_id"])
            valid, rejected = _validate_articles(articles, allowlist)
            item["article_filter_rejections"] = rejected
            item["concrete_listings"] = valid[:5]
            item["concrete_listing_count"] = len(valid)
            if valid:
                item["listing_validation_status"] = "ACTIONABLE_LISTINGS_FOUND"
                item["actionable"] = True
                item.update(_listing_signal(item["dk_price"], valid) or {})
                actionable += 1
            else:
                item["listing_validation_status"] = "NO_VERIFIED_DK_DELIVERABLE_CLEAN_ENGLISH_LISTINGS"
        except Exception as exc:
            api_errors += 1
            item["listing_validation_status"] = "CARDMARKET_API_ERROR"
            item["listing_validation_error"] = f"{type(exc).__name__}: {exc}"[:300]

        rows.append(item)
        if REQUEST_DELAY:
            time.sleep(REQUEST_DELAY)

    rows.sort(key=lambda row: (
        0 if row.get("actionable") else 1,
        999999 if row.get("diff_pct_vs_actionable_floor") is None else row["diff_pct_vs_actionable_floor"],
        row.get("dk_price") or 0,
    ))

    preview = {
        "version": 6,
        "scope": "pokemon_core_sealed",
        "mode": "shadow_listing_validator",
        "generated_at": datetime.now(ZoneInfo(TZ_NAME)).isoformat(),
        "benchmark": "concrete_english_clean_verified_dk_deliverable_cardmarket_articles",
        "price_guide_role": "info_only",
        "delivery_policy": {
            "automatic": "Cardmarket seller country DK",
            "foreign": "only explicit confirmed_sellers allowlist",
            "note": "Foreign seller country alone is not treated as proof of delivery to Denmark.",
        },
        "sealed_policy": "Cardmarket non-single product plus rejection of opened/damaged listing comments",
        "cardmarket_api_credentials_available": api_ready,
        "matched_groups_from_v5": len(base.get("matched") or []),
        "exact_identity_groups": exact_identity,
        "unresolved_identity_groups": unresolved_identity,
        "actionable_groups": actionable,
        "api_errors": api_errors,
        "confirmed_foreign_sellers_for_dk": len(allowlist),
        "rows": rows,
    }
    return preview


def make_embed(preview):
    actionable = [row for row in preview["rows"] if row.get("actionable")][:10]
    unresolved = [row for row in preview["rows"] if row.get("identity_status") == "UNRESOLVED_VARIANT"][:5]
    lines = [
        f"**{preview['exact_identity_groups']}** exact product identities · "
        f"**{preview['unresolved_identity_groups']}** variants held out · "
        f"**{preview['actionable_groups']}** products with concrete verified listings.",
        "",
        "Cardmarket Price Guide is **info only**. V6 only benchmarks against concrete English listings that pass damage/opened checks and have verified DK delivery.",
    ]
    if actionable:
        lines += ["", "🟢 **KONKRETE CARDMARKET-LISTINGS**"]
        for row in actionable:
            listing = row["concrete_listings"][0]
            diff = row.get("diff_pct_vs_actionable_floor")
            sign = "+" if diff is not None and diff >= 0 else ""
            lines.append(
                f"• **{row['cm_name']}** — DK {v5.fmt_dkk(row['dk_price'])} · "
                f"CM {v5.fmt_eur(listing['price_eur'])} hos {listing['seller']} ({listing['seller_country']}) · "
                f"**{sign}{diff:.0f}%**" if diff is not None else
                f"• **{row['cm_name']}** — DK {v5.fmt_dkk(row['dk_price'])} · CM {v5.fmt_eur(listing['price_eur'])}"
            )
    else:
        lines += ["", "🟡 Ingen produkter har endnu et komplet, verificeret V6-benchmark."]

    if unresolved:
        lines += ["", "⚠️ **VARIANT IKKE FASTSLÅET**"]
        for row in unresolved:
            lines.append(f"• {row['dk_name']} — ingen prisdom")

    return {
        "title": "🛰️ MARKET RADAR V6 · LISTING VALIDATOR",
        "description": "\n".join(lines)[:4096],
        "color": 0xF1C40F,
        "footer": {
            "text": "Shadow only · exact product + English + clean/sealed + verified DK delivery required"
        },
    }


def main():
    preview = build_v6()
    PREVIEW_FILE.write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "MARKET RADAR V6: "
        f"{preview['exact_identity_groups']} exact identities | "
        f"{preview['unresolved_identity_groups']} unresolved variants | "
        f"{preview['actionable_groups']} actionable listing benchmarks | "
        f"API ready={preview['cardmarket_api_credentials_available']} | errors={preview['api_errors']}"
    )
    print("MARKET RADAR V6: shadow mode only - Discord ikke sendt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
