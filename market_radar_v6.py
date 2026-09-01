import json
import math
import os
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

try:
    from requests_oauthlib import OAuth1
except ImportError:
    OAuth1 = None

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None

import market_radar as v5

PREVIEW_FILE = Path(os.getenv("MARKET_RADAR_V6_PREVIEW_FILE", "market_radar_v6_preview.json"))
ALLOWLIST_FILE = Path(os.getenv("MARKET_RADAR_DK_SHIPPING_ALLOWLIST", "market_radar_dk_shipping_allowlist.json"))
TZ_NAME = os.getenv("MARKET_RADAR_TIMEZONE", "Europe/Copenhagen").strip() or "Europe/Copenhagen"
CARDMARKET_API_BASE = "https://apiv2.cardmarket.com/ws/v2.0"
CARDMARKET_APP_TOKEN = os.getenv("CARDMARKET_APP_TOKEN", "").strip()
CARDMARKET_APP_SECRET = os.getenv("CARDMARKET_APP_SECRET", "").strip()
CARDMARKET_ACCESS_TOKEN = os.getenv("CARDMARKET_ACCESS_TOKEN", "").strip()
CARDMARKET_ACCESS_SECRET = os.getenv("CARDMARKET_ACCESS_SECRET", "").strip()
MAX_PRODUCTS = max(1, int(os.getenv("MARKET_RADAR_V6_MAX_PRODUCTS", "150") or 150))
PUBLIC_MAX_PRODUCTS = max(1, int(os.getenv("MARKET_RADAR_V6_PUBLIC_MAX_PRODUCTS", "12") or 12))
REQUEST_DELAY = max(0.0, float(os.getenv("MARKET_RADAR_V6_REQUEST_DELAY", "0.20") or 0.20))
MIN_SELLS = max(0, int(os.getenv("MARKET_RADAR_V6_MIN_SELLS", "25") or 25))

# High-value probe products. These are always attempted even if the normal public
# probe budget has already been consumed.
PUBLIC_PRIORITY_IDS = {
    819414,  # Team Rocket's Mewtwo ex Box
    818585,  # Destined Rivals ETB
    884751,  # Mega Greninja ex Premium Collection
    860578,  # Ascended Heroes Booster Bundle
}

DAMAGE_MARKERS = (
    "damaged", "damage", "dented", "dent", "crushed", "crease", "creased",
    "tear", "torn", "ripped", "corner damage", "box damage", "packaging damage",
    "opened", "open box", "unsealed", "resealed", "broken seal", "seal broken",
    "beschadigt", "beschädigt", "schaden", "delle", "geoffnet", "geöffnet",
    "offen", "eingerissen", "knick", "defekt", "plastic damaged", "folie nicht perfekt",
)

FOREIGN_LANGUAGE_MARKERS = (
    "german", "deutsch", "tysk", "french", "francais", "français", "fransk",
    "italian", "italiano", "italiensk", "spanish", "espanol", "español", "spansk",
    "portuguese", "portugues", "português", "portugisisk", "dutch", "nederlands",
    "hollandsk", "japanese", "japansk", "korean", "koreansk", "chinese", "kinesisk",
)

SPECIFIC_COLLECTION_MARKERS = (
    " ex ", " v ", " vstar ", " vmax ", " gx ", " premium ", " special ",
    " illustration ", " poster ", " binder ", " figure ", " deluxe ", " pin ",
    " ultra ", " super ", " trainer ", " collection box ",
)

COUNTRY_CODES = {
    "denmark": "DK", "danmark": "DK", "germany": "DE", "deutschland": "DE",
    "italy": "IT", "italia": "IT", "france": "FR", "spain": "ES", "espana": "ES",
    "españa": "ES", "netherlands": "NL", "nederland": "NL", "belgium": "BE",
    "belgie": "BE", "belgië": "BE", "austria": "AT", "osterreich": "AT",
    "österreich": "AT", "poland": "PL", "polska": "PL", "sweden": "SE",
    "sverige": "SE", "finland": "FI", "suomi": "FI", "norway": "NO",
    "norge": "NO", "czech republic": "CZ", "czechia": "CZ", "portugal": "PT",
    "greece": "GR", "slovakia": "SK", "slovenia": "SI", "croatia": "HR",
    "hungary": "HU", "romania": "RO", "ireland": "IE", "united kingdom": "GB",
    "switzerland": "CH",
}


def _load_allowlist():
    try:
        data = json.loads(ALLOWLIST_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    sellers = data.get("confirmed_sellers") or []
    return {str(value).strip().lower() for value in sellers if str(value).strip()}


def _credentials_available():
    return bool(OAuth1 and CARDMARKET_APP_TOKEN and CARDMARKET_APP_SECRET)


def _oauth(url):
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


def _comment_has_foreign_language(comment):
    text = " " + v5.normalize_text(comment) + " "
    return any(v5.normalize_text(marker) in text for marker in FOREIGN_LANGUAGE_MARKERS)


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
    cm_canonical = v5.canonical_name(row.get("cm_name") or "", row.get("cm_type") or product_type)
    normalized = " " + v5.normalize_text(dk_name) + " "

    if not canonical or canonical != cm_canonical:
        return False, "CANONICAL_IDENTITY_MISMATCH"

    if family == "COLLECTION" and product_type == "COLLECTION":
        has_specific_marker = any(marker in normalized for marker in SPECIFIC_COLLECTION_MARKERS)
        if len(canonical.split()) <= 3 and not has_specific_marker:
            return False, "UNRESOLVED_VARIANT"

    return True, "EXACT_PRODUCT"


def _fetch_articles(product_id):
    url = f"{CARDMARKET_API_BASE}/articles/{int(product_id)}"
    response = requests.get(
        url,
        params={"idLanguage": 1, "start": 0, "maxResults": 100},
        auth=_oauth(url),
        headers={"Accept": "application/json", "User-Agent": "Pokemon-Market-Radar/6.1"},
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
        "seller_too_new": 0,
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
        if v5.safe_int(seller.get("sellCount"), 0) < MIN_SELLS:
            rejected["seller_too_new"] += 1
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
            "seller_sell_count": seller.get("sellCount"),
            "comments": comment[:300],
            "delivery_verification": delivery_reason,
            "language": "English",
            "language_verified": True,
            "sealed_basis": "Cardmarket sealed/non-single product; opened/damage comments rejected",
        })
    valid.sort(key=lambda row: (row["price_eur"], row["seller"]))
    return valid, rejected


def _cm_slug(name):
    value = unicodedata.normalize("NFKD", str(name or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.replace("’", "").replace("'", "").replace("&", " and ")
    value = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-")
    return value


def _public_product_url(row):
    product_type = str(row.get("cm_type") or row.get("type") or "")
    if product_type in {"ETB", "PC ETB"}:
        category = "Elite-Trainer-Boxes"
    elif product_type in {"BOOSTER BOX", "BOOSTER BUNDLE"}:
        category = "Booster-Boxes"
    else:
        category = "Box-Sets"
    return f"https://www.cardmarket.com/en/Pokemon/Products/{category}/{_cm_slug(row.get('cm_name'))}"


def _looks_like_cloudflare(status_code, text):
    lower = str(text or "").lower()
    return status_code in {403, 429, 503} or any(marker in lower for marker in (
        "just a moment", "cf-chl-", "cloudflare ray id", "challenge-platform",
    ))


def _public_get(url):
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    }
    attempts = []

    if curl_requests is not None:
        try:
            response = curl_requests.get(
                url,
                headers=headers,
                impersonate="chrome",
                timeout=30,
                allow_redirects=True,
            )
            attempts.append({"client": "curl_cffi", "status": response.status_code, "bytes": len(response.text or "")})
            if response.status_code == 200 and not _looks_like_cloudflare(response.status_code, response.text):
                return response.text, "PUBLIC_OK_CURL_CFFI", attempts
            if _looks_like_cloudflare(response.status_code, response.text):
                attempts[-1]["cloudflare"] = True
        except Exception as exc:
            attempts.append({"client": "curl_cffi", "error": f"{type(exc).__name__}: {exc}"[:200]})

    try:
        response = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        attempts.append({"client": "requests", "status": response.status_code, "bytes": len(response.text or "")})
        if response.status_code == 200 and not _looks_like_cloudflare(response.status_code, response.text):
            return response.text, "PUBLIC_OK_REQUESTS", attempts
        if _looks_like_cloudflare(response.status_code, response.text):
            attempts[-1]["cloudflare"] = True
            return "", "PUBLIC_CLOUDFLARE_BLOCKED", attempts
        return "", f"PUBLIC_HTTP_{response.status_code}", attempts
    except Exception as exc:
        attempts.append({"client": "requests", "error": f"{type(exc).__name__}: {exc}"[:200]})
        return "", "PUBLIC_FETCH_ERROR", attempts


def _parse_eur(text):
    match = re.search(r"(\d{1,3}(?:\.\d{3})*|\d+)(?:[,.](\d{1,2}))?\s*€", str(text or ""))
    if not match:
        return None
    whole = match.group(1).replace(".", "")
    cents = (match.group(2) or "0").ljust(2, "0")[:2]
    try:
        return float(f"{whole}.{cents}")
    except ValueError:
        return None


def _country_from_row(row):
    candidates = []
    for tag in row.select("[title], [data-original-title], [data-bs-original-title], img[alt]"):
        for attr in ("title", "data-original-title", "data-bs-original-title", "alt"):
            value = str(tag.get(attr) or "").strip()
            if value:
                candidates.append(value)
    for value in candidates:
        normalized = v5.normalize_text(value)
        if normalized in COUNTRY_CODES:
            return COUNTRY_CODES[normalized]
    return ""


def _parse_public_listings(html):
    soup = BeautifulSoup(html, "html.parser")
    listings = []
    rows = soup.select("#table .article-row, .table-body .article-row, .article-row")
    seen = set()
    for row in rows:
        seller_link = row.select_one('a[href*="/Users/"]')
        seller = seller_link.get_text(" ", strip=True) if seller_link else ""
        if not seller:
            continue

        price = None
        for node in row.select(".price-container, .color-primary, [class*='price']"):
            price = _parse_eur(node.get_text(" ", strip=True))
            if price is not None:
                break
        if price is None:
            price = _parse_eur(row.get_text(" ", strip=True))
        if price is None or price <= 0:
            continue

        comment_node = row.select_one(".col-comments, .comments, [class*='comment']")
        comment = comment_node.get_text(" ", strip=True) if comment_node else ""
        country = _country_from_row(row)
        key = (seller, price, comment)
        if key in seen:
            continue
        seen.add(key)
        listings.append({
            "seller": seller,
            "seller_country": country,
            "price_eur": price,
            "comments": comment[:300],
            "damaged_or_opened": _comment_has_damage(comment),
            "foreign_language_warning": _comment_has_foreign_language(comment),
            "language": "UNVERIFIED_ON_PUBLIC_SEALED_PAGE",
            "language_verified": False,
        })
    listings.sort(key=lambda item: (item["price_eur"], item["seller"]))
    return listings


def _public_probe(row, allowlist):
    url = _public_product_url(row)
    html, status, attempts = _public_get(url)
    result = {
        "public_page_url": url,
        "public_fetch_status": status,
        "public_fetch_attempts": attempts,
        "public_listings": [],
        "public_clean_listings": [],
        "public_verified_dk_listings": [],
        "public_actionable": False,
    }
    if not html:
        return result

    listings = _parse_public_listings(html)
    clean = [item for item in listings if not item["damaged_or_opened"] and not item["foreign_language_warning"]]
    verified_dk = []
    for item in clean:
        seller = item["seller"].lower()
        if item["seller_country"] == "DK" or seller in allowlist:
            verified_dk.append(item)

    result["public_listings"] = listings[:20]
    result["public_listing_count"] = len(listings)
    result["public_clean_listings"] = clean[:10]
    result["public_clean_listing_count"] = len(clean)
    result["public_verified_dk_listings"] = verified_dk[:10]
    result["public_verified_dk_listing_count"] = len(verified_dk)
    if clean:
        result["public_clean_floor_eur"] = clean[0]["price_eur"]
        result["public_clean_floor_dkk"] = clean[0]["price_eur"] * v5.EUR_DKK
    if verified_dk:
        result["public_verified_dk_floor_eur"] = verified_dk[0]["price_eur"]
        result["public_verified_dk_floor_dkk"] = verified_dk[0]["price_eur"] * v5.EUR_DKK

    # Public sealed pages do not expose a reliable per-listing English-language
    # field. Therefore public scraping remains a probe/reference and is NEVER
    # promoted to an actionable benchmark solely from HTML.
    result["public_actionable"] = False
    if not listings:
        result["public_fetch_status"] = "PUBLIC_PARSE_EMPTY"
    return result


def _listing_signal(dk_price, listings):
    if not listings:
        return None
    prices = [row["price_eur"] for row in listings]
    floor_eur = prices[0]
    floor_dkk = floor_eur * v5.EUR_DKK
    top = prices[: min(5, len(prices))]
    median_eur = median(top)
    median_dkk = median_eur * v5.EUR_DKK
    return {
        "actionable_floor_eur": floor_eur,
        "actionable_floor_dkk": floor_dkk,
        "top5_median_eur": median_eur,
        "top5_median_dkk": median_dkk,
        "diff_pct_vs_actionable_floor": ((dk_price / floor_dkk) - 1.0) * 100.0 if floor_dkk > 0 else None,
        "diff_pct_vs_top5_median": ((dk_price / median_dkk) - 1.0) * 100.0 if median_dkk > 0 else None,
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
    public_attempted = 0
    public_ok = 0
    public_blocked = 0
    public_parse_empty = 0

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

        if api_ready and index < MAX_PRODUCTS:
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
        elif not api_ready:
            product_id = v5.safe_int(item.get("cm_product_id"), 0)
            should_probe = product_id in PUBLIC_PRIORITY_IDS or public_attempted < PUBLIC_MAX_PRODUCTS
            if should_probe:
                public_attempted += 1
                probe = _public_probe(item, allowlist)
                item.update(probe)
                status = probe.get("public_fetch_status")
                if status in {"PUBLIC_OK_CURL_CFFI", "PUBLIC_OK_REQUESTS"}:
                    public_ok += 1
                elif status == "PUBLIC_CLOUDFLARE_BLOCKED":
                    public_blocked += 1
                elif status == "PUBLIC_PARSE_EMPTY":
                    public_parse_empty += 1
                item["listing_validation_status"] = "PUBLIC_LISTING_PROBE_ONLY"
            else:
                item["listing_validation_status"] = "PUBLIC_PROBE_LIMIT_REACHED"
        else:
            item["listing_validation_status"] = "API_VALIDATION_LIMIT_REACHED"

        rows.append(item)
        if REQUEST_DELAY:
            time.sleep(REQUEST_DELAY)

    rows.sort(key=lambda row: (
        0 if row.get("actionable") else 1,
        0 if row.get("cm_product_id") in PUBLIC_PRIORITY_IDS else 1,
        999999 if row.get("diff_pct_vs_actionable_floor") is None else row["diff_pct_vs_actionable_floor"],
        row.get("dk_price") or 0,
    ))

    return {
        "version": 6.1,
        "scope": "pokemon_core_sealed",
        "mode": "shadow_listing_validator_public_probe",
        "generated_at": datetime.now(ZoneInfo(TZ_NAME)).isoformat(),
        "benchmark": "official_articles_when_available_else_public_listing_probe_only",
        "price_guide_role": "info_only",
        "delivery_policy": {
            "automatic": "Cardmarket seller country DK",
            "foreign": "only explicit confirmed_sellers allowlist",
            "note": "Foreign seller location is not proof of delivery to Denmark.",
        },
        "language_policy": {
            "official_articles": "idLanguage=1 required",
            "public_pages": "language not reliably exposed per sealed listing; never actionable",
        },
        "sealed_policy": "Cardmarket sealed product page plus rejection of opened/damaged listing comments",
        "seller_minimum_sales": MIN_SELLS,
        "cardmarket_api_credentials_available": api_ready,
        "matched_groups_from_v5": len(base.get("matched") or []),
        "exact_identity_groups": exact_identity,
        "unresolved_identity_groups": unresolved_identity,
        "actionable_groups": actionable,
        "api_errors": api_errors,
        "public_probe_attempted": public_attempted,
        "public_probe_ok": public_ok,
        "public_probe_cloudflare_blocked": public_blocked,
        "public_probe_parse_empty": public_parse_empty,
        "confirmed_foreign_sellers_for_dk": len(allowlist),
        "rows": rows,
    }


def make_embed(preview):
    lines = [
        f"**{preview['exact_identity_groups']}** exact identities · "
        f"**{preview['unresolved_identity_groups']}** variants held out · "
        f"**{preview['actionable_groups']}** fully actionable benchmarks.",
        "",
        f"Public probe: {preview['public_probe_attempted']} attempted · "
        f"{preview['public_probe_ok']} fetched · "
        f"{preview['public_probe_cloudflare_blocked']} Cloudflare-blocked · "
        f"{preview['public_probe_parse_empty']} parse-empty.",
        "",
        "Public Cardmarket listings are reference-only until English language and DK delivery can both be verified.",
    ]
    return {
        "title": "🛰️ MARKET RADAR V6.1 · PUBLIC LISTING PROBE",
        "description": "\n".join(lines)[:4096],
        "color": 0xF1C40F,
        "footer": {"text": "Shadow only · no Discord post"},
    }


def main():
    preview = build_v6()
    PREVIEW_FILE.write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "MARKET RADAR V6.1: "
        f"{preview['exact_identity_groups']} exact | "
        f"{preview['unresolved_identity_groups']} unresolved | "
        f"public {preview['public_probe_ok']}/{preview['public_probe_attempted']} fetched | "
        f"CF blocked={preview['public_probe_cloudflare_blocked']} | "
        f"actionable={preview['actionable_groups']}"
    )
    print("MARKET RADAR V6.1: shadow mode only - Discord ikke sendt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
