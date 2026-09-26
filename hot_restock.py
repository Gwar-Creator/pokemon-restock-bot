import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

import requests

from alert_policy import TIER_A_SOURCES

ROOT = Path(__file__).resolve().parent
SHARED_FILE = ROOT / "restock_bot_github.py"
STATE_FILE = ROOT / "hot_restock_state.json"
FILTER_VERSION = 3

HOT_ITERATIONS = max(1, int(os.getenv("HOT_ITERATIONS", "1")))
HOT_INTERVAL_SECONDS = max(30, int(os.getenv("HOT_INTERVAL_SECONDS", "60")))
HOT_DRY_RUN = os.getenv("HOT_DRY_RUN", "0").strip() == "1"
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

PROSHOP_FRONTEND_URL = "https://www.proshop.dk/?s=Pokemon+TCG"
PROSHOP_DISCOVERY_VERSION = 4

BOOZT_CATEGORY_URL = "https://www.boozt.com/dk/da/pokemon-trading-cards/born"
MAGASIN_CATEGORY_URL = "https://www.magasin.dk/boern/legetoej/samlekort-og-mapper/pokemon/"
MAGASIN_SITEMAP_INDEX_URL = "https://www.magasin.dk/sitemap_index.xml"
MAGASIN_DISCOVERY_INTERVAL_SECONDS = 240
MAGASIN_FULL_DISCOVERY_INTERVAL_SECONDS = 6 * 60 * 60
MAGASIN_TCG_URL_MARKERS = (
    "booster",
    "blister",
    "binder-coll",
    "binder-collection",
    "elite-trainer",
    "trainer-box",
    "mini-tin",
    "checklane",
    "battle-deck",
    "collection",
    "poke-box",
    "pokemon-box",
)
RETAIL_DISCOVERY_VERSION = 4
RETAIL_MIN_PRODUCTS = {
    "boozt": 2,
    "magasin": 2,
}

RATE_LIMIT_BACKOFF_SECONDS = (0, 120, 300, 900)
RATE_LIMIT_MARKERS = (
    "429",
    "too many requests",
    "rate limit",
    "ratelimit",
    "retry-after",
    "throttl",
    "403",
    "forbidden",
    "access denied",
    "temporarily blocked",
    "503",
    "service unavailable",
)

SOURCE_LABELS = {
    "coolshop": "COOLSHOP",
    "proshop": "PROSHOP",
    "br": "BR",
    "bilka": "BILKA",
    "foetex": "FØTEX",
    "boozt": "BOOZT",
    "magasin": "MAGASIN",
}

if tuple(SOURCE_LABELS) != tuple(TIER_A_SOURCES):
    raise RuntimeError("HOT source list er ikke synkron med TIER_A_SOURCES")


def load_shared_namespace():
    source = SHARED_FILE.read_text(encoding="utf-8")
    marker = (
        "# =========================================================\n"
        "# START\n"
        "# ========================================================="
    )
    if marker not in source:
        raise RuntimeError("Kunne ikke finde START-markøren i restock_bot_github.py")

    namespace = {
        "__name__": "restock_hot_shared",
        "__file__": str(SHARED_FILE),
    }
    exec(compile(source.split(marker, 1)[0], str(SHARED_FILE), "exec"), namespace)
    return namespace


def load_state():
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _source_control(state, source_key):
    controls = state.setdefault("source_controls", {})
    control = controls.setdefault(
        source_key,
        {
            "backoff_level": 0,
            "next_allowed_at": 0.0,
            "generic_failures": 0,
            "last_error": None,
            "last_failure_at": None,
            "last_success_at": None,
        },
    )
    control["backoff_level"] = max(
        0,
        min(
            len(RATE_LIMIT_BACKOFF_SECONDS) - 1,
            int(control.get("backoff_level") or 0),
        ),
    )
    control["next_allowed_at"] = float(control.get("next_allowed_at") or 0.0)
    control["generic_failures"] = max(0, int(control.get("generic_failures") or 0))
    return control


def _retry_after_seconds(error):
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None) or {}
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0, int(float(raw)))
    except (TypeError, ValueError):
        return None


def _is_rate_limit_like(error):
    text = str(error).lower()
    return any(marker in text for marker in RATE_LIMIT_MARKERS)


def _register_source_failure(state, source_key, error):
    control = _source_control(state, source_key)
    control["last_error"] = str(error)[:500]
    control["last_failure_at"] = _utc_now_iso()
    control["generic_failures"] += 1

    should_backoff = _is_rate_limit_like(error) or control["generic_failures"] >= 2
    if not should_backoff:
        return 0

    control["backoff_level"] = min(
        len(RATE_LIMIT_BACKOFF_SECONDS) - 1,
        control["backoff_level"] + 1,
    )
    delay = RATE_LIMIT_BACKOFF_SECONDS[control["backoff_level"]]
    retry_after = _retry_after_seconds(error)
    if retry_after is not None:
        delay = max(delay, retry_after)
    control["next_allowed_at"] = time.time() + delay
    return delay


def _register_source_success(state, source_key):
    control = _source_control(state, source_key)
    previous_level = control["backoff_level"]
    control["generic_failures"] = 0
    control["last_error"] = None
    control["last_success_at"] = _utc_now_iso()

    if previous_level > 0:
        control["backoff_level"] = previous_level - 1
        delay = RATE_LIMIT_BACKOFF_SECONDS[control["backoff_level"]]
        control["next_allowed_at"] = time.time() + delay if delay else 0.0
        return previous_level, control["backoff_level"]

    control["next_allowed_at"] = 0.0
    return 0, 0


def _source_wait_seconds(state, source_key):
    control = _source_control(state, source_key)
    return max(0, int(round(control["next_allowed_at"] - time.time())))


def product_available(source_key, product):
    if source_key == "coolshop":
        return bool(product.get("online_stock"))

    if source_key == "proshop":
        return product.get("stock") == "PÅ LAGER"

    if source_key == "br":
        if int(product.get("online_count") or 0) > 0:
            return True
        if int(product.get("kolding_stock") or 0) > 0:
            return True
        if int(product.get("esbjerg_stock") or 0) > 0:
            return True
        return False

    if source_key in ("bilka", "foetex"):
        if int(product.get("online_count") or 0) > 0:
            return True
        for store in (product.get("local_stocks") or {}).values():
            if int(store.get("stock") or 0) > 0:
                return True
        return False

    if source_key in ("boozt", "magasin"):
        return bool(product.get("in_stock"))

    return False


def availability_text(source_key, product):
    if source_key == "coolshop":
        return "Online" if product.get("online_stock") else "Ikke på lager"

    if source_key == "proshop":
        return product.get("stock") or "UKENDT"

    if source_key in ("boozt", "magasin"):
        return "Online" if product.get("in_stock") else "Ikke på lager"

    bits = []
    online = int(product.get("online_count") or 0)
    if online > 0:
        bits.append(f"Online {online} stk.")

    if source_key == "br":
        kolding = int(product.get("kolding_stock") or 0)
        esbjerg = int(product.get("esbjerg_stock") or 0)
        if kolding > 0:
            bits.append(f"BR Kolding {kolding} stk.")
        if esbjerg > 0:
            bits.append(f"BR Esbjerg {esbjerg} stk.")
    else:
        for store in (product.get("local_stocks") or {}).values():
            stock = int(store.get("stock") or 0)
            if stock > 0:
                bits.append(f"{store.get('name') or 'Lokal butik'} {stock} stk.")

    return " · ".join(bits) if bits else "Ikke på lager"


def format_price(value):
    if value is None:
        return "Pris ikke oplyst"
    try:
        price = float(value)
    except (TypeError, ValueError):
        return "Pris ikke oplyst"
    return f"{price:,.2f} kr.".replace(",", "X").replace(".", ",").replace("X", ".")


def send_hot_alert(source_key, product, event):
    label = SOURCE_LABELS[source_key]
    message = (
        f"🚨 **HOT {event} · {label}**\n"
        f"**{product.get('name') or 'Ukendt produkt'}**\n"
        f"💰 {format_price(product.get('price'))}\n"
        f"📦 {availability_text(source_key, product)}\n"
        f"🔗 {product.get('url') or ''}"
    )

    if HOT_DRY_RUN:
        print("HOT DRY RUN:")
        print(message)
        return

    if not WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL mangler til HOT scanner")

    response = requests.post(WEBHOOK_URL, json={"content": message}, timeout=15)
    response.raise_for_status()


def filter_hot_products(shared, products):
    """Tier A is a frequency tier, not a second product taxonomy."""
    allowed = {}
    shared_relevance = shared["restock_alert_allowed"]

    for product_id, product in (products or {}).items():
        if not isinstance(product, dict):
            continue
        game = str(product.get("game") or "POKÉMON").upper()
        if game not in {"POKÉMON", "POKEMON"}:
            continue
        if not shared_relevance(product, "POKÉMON"):
            continue
        allowed[str(product_id)] = product

    return allowed


def _proshop_raw_link_count(text):
    raw_link_pattern = re.compile(
        r"(?:https?://(?:www\.)?proshop\.dk)?/Pokemon/[^)\s?#]+/\d+",
        re.IGNORECASE,
    )
    return len(set(raw_link_pattern.findall(text or "")))


def _fetch_proshop_frontend_products(shared):
    """Read Proshop's live frontend as a best-effort freshness lane."""
    curl_requests = shared.get("curl_requests")
    if curl_requests is None:
        raise RuntimeError("curl_cffi er ikke tilgængelig til Proshop frontend")

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
        "Referer": "https://www.proshop.dk/",
        "Upgrade-Insecure-Requests": "1",
    }

    session = curl_requests.Session(impersonate="chrome")
    response = session.get(PROSHOP_FRONTEND_URL, headers=headers, timeout=25)
    response.raise_for_status()

    raw_product_links = _proshop_raw_link_count(response.text)
    if raw_product_links < 10:
        raise RuntimeError(
            "Proshop frontend returnerede for få rå produktlinks "
            f"({raw_product_links})"
        )

    products = shared["_parse_proshop_products"](response)
    if not products:
        raise RuntimeError(
            "Proshop frontend parser gav 0 TCG-produkter fra "
            f"{raw_product_links} rå links"
        )

    for product in products.values():
        if isinstance(product, dict):
            product["fetch_via"] = "direct_frontend_search"

    print(
        f"HOT PROSHOP frontend: {len(products)} TCG-produkter "
        f"fra {raw_product_links} rå produktlinks"
    )
    return products


def _merge_proshop_products(*product_sets):
    merged = {}

    for products in product_sets:
        for product_id, product in (products or {}).items():
            if not isinstance(product, dict):
                continue

            product_id = str(product_id)
            current = merged.get(product_id)
            if current is None:
                merged[product_id] = dict(product)
                continue

            combined = dict(current)
            for key in ("name", "url"):
                if product.get(key):
                    combined[key] = product[key]

            if product.get("price") is not None:
                combined["price"] = product["price"]

            stock = product.get("stock")
            if stock and stock != "UKENDT":
                combined["stock"] = stock
            elif not combined.get("stock"):
                combined["stock"] = stock or "UKENDT"

            current_via = str(current.get("fetch_via") or "")
            candidate_via = str(product.get("fetch_via") or "")
            vias = [value for value in (current_via, candidate_via) if value]
            if vias:
                combined["fetch_via"] = "+".join(dict.fromkeys(vias))

            merged[product_id] = combined

    return merged


def _fetch_expanded_proshop_products(shared):
    curated = {}
    frontend = {}
    errors = []

    with ThreadPoolExecutor(max_workers=2) as pool:
        curated_future = pool.submit(shared["get_proshop_products"])
        frontend_future = pool.submit(_fetch_proshop_frontend_products, shared)

        try:
            curated = curated_future.result()
        except Exception as error:
            errors.append(f"curated: {error}")

        try:
            frontend = frontend_future.result()
        except Exception as error:
            errors.append(f"frontend: {error}")

    if not curated and not frontend:
        detail = "; ".join(errors[-4:]) if errors else "ukendt fejl"
        raise RuntimeError(f"Alle Proshop discovery-ruter fejlede ({detail})")

    if errors:
        print("HOT PROSHOP discovery warning: " + "; ".join(errors))

    merged = _merge_proshop_products(curated, frontend)
    curated_ids = set(map(str, curated))
    frontend_ids = set(map(str, frontend))
    frontend_only = len(frontend_ids - curated_ids)

    print(
        f"HOT PROSHOP discovery: curated={len(curated)} · "
        f"frontend={len(frontend)} · merged={len(merged)} · "
        f"frontend-only={frontend_only}"
    )
    return merged



def _retail_clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _retail_price(text):
    matches = re.findall(
        r"(?<!\d)(\d{1,4}(?:\.\d{3})*(?:,\d{2})?)\s*(?:kr\.?|dkk)\b",
        str(text or ""),
        flags=re.IGNORECASE,
    )
    if not matches:
        return None

    try:
        value = matches[-1].replace(".", "").replace(",", ".")
        return float(value)
    except (TypeError, ValueError):
        return None


def _retail_name_from_card(card, anchors):
    candidates = []

    for selector in (
        "h1",
        "h2",
        "h3",
        "h4",
        "[class*='product-name']",
        "[class*='productName']",
        "[class*='product-title']",
        "[class*='productTitle']",
    ):
        node = card.select_one(selector)
        if node:
            candidates.append(_retail_clean_text(node.get_text(" ", strip=True)))

    for anchor in anchors:
        candidates.append(_retail_clean_text(anchor.get_text(" ", strip=True)))
        image = anchor.find("img", alt=True)
        if image:
            candidates.append(_retail_clean_text(image.get("alt")))

    blocked = {
        "",
        "se produkt",
        "læs mere",
        "laes mere",
        "læg i kurv",
        "laeg i kurv",
        "tilføj til kurv",
        "tilfoej til kurv",
        "giv mig besked",
        "skriv mig op",
    }
    candidates = [
        value
        for value in candidates
        if len(value) >= 4 and value.lower() not in blocked
    ]

    sealed_markers = (
        "pokemon",
        "pokémon",
        "poke ",
        "booster",
        "blister",
        "tin",
        "collection",
        "elite trainer",
        " etb",
        "bundle",
        "box",
        "display",
        "pack",
    )
    candidates.sort(
        key=lambda value: (
            any(marker in value.lower() for marker in sealed_markers),
            len(value),
        ),
        reverse=True,
    )
    return candidates[0] if candidates else ""


def _retail_nearest_card(anchor, product_url, is_product_url):
    node = anchor
    best = anchor.parent or anchor

    for _ in range(10):
        node = node.parent
        if node is None:
            break

        links = set()
        for child in node.find_all("a", href=True):
            href = urljoin(product_url, child.get("href") or "")
            if is_product_url(href):
                links.add(href.split("#", 1)[0].split("?", 1)[0].rstrip("/"))

        normalized_product_url = product_url.split("#", 1)[0].split("?", 1)[0].rstrip("/")
        if normalized_product_url not in links:
            continue

        if len(links) > 1:
            break

        best = node
        text = _retail_clean_text(node.get_text(" ", strip=True)).lower()
        if any(
            marker in text
            for marker in (
                " kr",
                "dkk",
                "læg i kurv",
                "laeg i kurv",
                "tilføj til kurv",
                "tilfoej til kurv",
                "giv mig besked",
                "skriv mig op",
                "udsolgt",
                "ikke på lager",
                "ikke pa lager",
            )
        ):
            return node

    return best


def _retail_jsonld_products(soup):
    products = []

    def walk(value):
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if not isinstance(value, dict):
            return

        item_type = value.get("@type")
        if isinstance(item_type, list):
            is_product = any(str(entry).lower() == "product" for entry in item_type)
        else:
            is_product = str(item_type or "").lower() == "product"

        if is_product:
            products.append(value)

        for child in value.values():
            if isinstance(child, (dict, list)):
                walk(child)

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            walk(json.loads(raw))
        except (TypeError, json.JSONDecodeError):
            continue

    return products


def _retail_offer_values(product):
    offers = product.get("offers")
    if isinstance(offers, dict):
        offers = [offers]
    elif not isinstance(offers, list):
        offers = []

    price = None
    in_stock = None

    for offer in offers:
        if not isinstance(offer, dict):
            continue
        if price is None:
            raw_price = offer.get("price")
            try:
                price = float(str(raw_price).replace(",", "."))
            except (TypeError, ValueError):
                pass

        availability = str(offer.get("availability") or "").lower()
        if "instock" in availability:
            in_stock = True
        elif any(marker in availability for marker in ("outofstock", "soldout", "discontinued")):
            in_stock = False

    return price, in_stock


def _retail_catalog_product_allowed(source_key, name):
    text = " " + _retail_clean_text(name).lower() + " "
    if source_key == "boozt":
        return True

    # Magasin's brand page contains figures/plush/LEGO and global navigation.
    # The dedicated TCG category is primary, but keep an explicit sealed gate
    # as a second guard against unrelated .html links.
    markers = (
        " booster ",
        " blister ",
        " tin ",
        " elite trainer ",
        " etb ",
        " booster bundle ",
        " booster box ",
        " booster display ",
        " display ",
        " collection ",
        " binder collection ",
        " binder coll ",
        " poke box ",
        " battle deck ",
        " trainer toolkit ",
        " battle academy ",
        " build & battle ",
        " build and battle ",
        " checklane ",
        " check lane ",
    )
    return any(marker in text for marker in markers)



def _retail_product_key(source_key, product_url):
    url = str(product_url or "").split("#", 1)[0].split("?", 1)[0].rstrip("/")
    if source_key == "boozt":
        match = re.search(r"_(\d{6,})(?:/\d{6,})?$", url)
        if match:
            return f"boozt:{match.group(1)}"
    return url


def _retail_name_from_slug(product_url):
    path = str(product_url or "").split("?", 1)[0].rstrip("/")
    parts = path.split("/")
    slug = parts[-2] if parts and parts[-1].lower().endswith(".html") and len(parts) > 1 else parts[-1]
    slug = re.sub(r"_\d{6,}$", "", slug)
    return re.sub(r"[-_]+", " ", slug).strip().title()


def _fetch_reader_text(url, source_key):
    response = requests.get(
        "https://r.jina.ai/" + str(url),
        headers={
            "Accept": "text/plain, text/markdown;q=0.9, */*;q=0.5",
            "User-Agent": f"Pokemon-Lorcana-MasterBot/3.0 {SOURCE_LABELS[source_key]}",
            "x-no-cache": "true",
            "x-engine": "browser",
        },
        timeout=50,
    )
    response.raise_for_status()
    text = response.text or ""
    if len(text) < 500:
        raise RuntimeError(
            f"{SOURCE_LABELS[source_key]} Reader returnerede kun {len(text)} tegn"
        )
    return text


def _markdown_price_near(markdown, start, end):
    before = (markdown[max(0, start - 250):start] or "")
    after = (markdown[end:min(len(markdown), end + 900)] or "")
    return _retail_price(after) or _retail_price(before)


def _parse_boozt_reader_markdown(shared, markdown):
    nested_pattern = re.compile(
        r"\[!\[Image\s+\d+:\s*(?P<label>[^\]]{1,800})\]\([^)]+\)\]\("
        r"(?P<url>https?://(?:www\.)?boozt\.com/dk/da/"
        r"pokmon-trading-cards/[^)\s?#]+?_(?P<style>\d{6,})"
        r"(?:/\d{6,})?(?:[?#][^)]*)?)\)",
        re.IGNORECASE | re.DOTALL,
    )
    simple_pattern = re.compile(
        r"\[(?P<label>[^\]]{1,800})\]\("
        r"(?P<url>https?://(?:www\.)?boozt\.com/dk/da/"
        r"pokmon-trading-cards/[^)\s?#]+?_(?P<style>\d{6,})"
        r"(?:/\d{6,})?(?:[?#][^)]*)?)\)",
        re.IGNORECASE | re.DOTALL,
    )

    matches = list(nested_pattern.finditer(markdown or ""))
    if not matches:
        matches = list(simple_pattern.finditer(markdown or ""))

    products = {}

    for index, match in enumerate(matches):
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        price_segment = (markdown[match.end():next_start] or "")[:1000]
        price = _retail_price(price_segment)

        url = match.group("url").split("?", 1)[0].rstrip("/")
        label = re.sub(r"\s+", " ", match.group("label") or "").strip()
        name = re.sub(r"^Image\s+\d+:\s*", "", label, flags=re.IGNORECASE).strip()
        if not name or name.lower() in {"pokemon trading cards", "pokémon trading cards"}:
            name = _retail_name_from_slug(url)

        key = f"boozt:{match.group('style')}"
        candidate = {
            "name": name,
            "game": "POKÉMON",
            "price": price,
            # Boozt's public brand catalogue currently contains the products
            # that can be purchased. Missing products stay in state as OOS.
            "in_stock": True,
            "availability_known": True,
            "url": url,
            "fetch_via": "jina_reader_category",
        }
        current = products.get(key)
        if current is None or (
            current.get("price") is None and candidate.get("price") is not None
        ):
            products[key] = candidate

    return filter_hot_products(shared, products), len(matches)

def _parse_magasin_reader_markdown(shared, markdown):
    pattern = re.compile(
        r"\[(?P<label>[^\]]{1,800})\]\("
        r"(?P<url>https?://(?:www\.)?magasin\.dk/[^)\s?#]+\.html"
        r"(?:[?#][^)]*)?)\)",
        re.IGNORECASE | re.DOTALL,
    )
    matches = list(pattern.finditer(markdown or ""))
    products = {}

    for index, match in enumerate(matches):
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        price_segment = (markdown[match.end():next_start] or "")[:900]
        price = _retail_price(price_segment)
        if price is None:
            price = _retail_price((markdown[max(0, match.start() - 250):match.start()] or ""))

        url = match.group("url").split("?", 1)[0].rstrip("/")
        label = re.sub(r"\s+", " ", match.group("label") or "").strip()
        name = re.sub(r"^Image:\s*", "", label, flags=re.IGNORECASE).strip()
        if not _retail_catalog_product_allowed("magasin", name):
            fallback = _retail_name_from_slug(url)
            if not _retail_catalog_product_allowed("magasin", fallback):
                continue
            name = fallback

        key = _retail_product_key("magasin", url)
        candidate = {
            "name": name,
            "game": "POKÉMON",
            "price": price,
            "in_stock": False,
            "availability_known": False,
            "url": url,
            "fetch_via": "jina_reader_category",
        }
        current = products.get(key)
        if current is None or (
            current.get("price") is None and candidate.get("price") is not None
        ):
            products[key] = candidate

    return filter_hot_products(shared, products), len(matches)


def _reader_detail_one(shared, source_key, product_id, product, old_products):
    current = dict(product)
    old = (old_products or {}).get(product_id)
    try:
        markdown = _fetch_reader_text(current["url"], source_key)
        available = _parse_retail_detail_availability(
            shared,
            source_key,
            markdown,
        )
    except Exception as error:
        print(
            f"HOT {SOURCE_LABELS[source_key]} Reader detail warning "
            f"{current.get('name')}: {error}"
        )
        available = None

    if available is not None:
        current["in_stock"] = bool(available)
        current["availability_known"] = True
        return product_id, current, True

    if isinstance(old, dict):
        current["in_stock"] = bool(old.get("in_stock"))
        current["availability_known"] = bool(old.get("availability_known", False))
    else:
        current["in_stock"] = False
        current["availability_known"] = False
    return product_id, current, False


def _refresh_retail_via_reader_details(shared, source_key, products, old_products):
    refreshed = {}
    known_count = 0
    items = list((products or {}).items())

    def worker(item):
        product_id, product = item
        return _reader_detail_one(
            shared,
            source_key,
            product_id,
            product,
            old_products,
        )

    with ThreadPoolExecutor(max_workers=min(4, max(1, len(items)))) as executor:
        for product_id, current, known in executor.map(worker, items):
            refreshed[product_id] = current
            known_count += int(known)

    required_known = max(
        RETAIL_MIN_PRODUCTS[source_key],
        (len(refreshed) + 1) // 2,
    )
    if known_count < required_known:
        raise RuntimeError(
            f"{SOURCE_LABELS[source_key]} Reader lagerstatus kun kendt for "
            f"{known_count}/{len(refreshed)} produkter "
            f"(minimum {required_known})"
        )
    return refreshed


def _fetch_boozt_via_reader(shared):
    markdown = _fetch_reader_text(BOOZT_CATEGORY_URL, "boozt")
    products, raw_links = _parse_boozt_reader_markdown(shared, markdown)
    if raw_links < RETAIL_MIN_PRODUCTS["boozt"] or len(products) < RETAIL_MIN_PRODUCTS["boozt"]:
        raise RuntimeError(
            f"BOOZT Reader gav {raw_links} rå links / {len(products)} relevante produkter"
        )
    return products


def _fetch_magasin_via_reader(shared, old_products):
    markdown = _fetch_reader_text(MAGASIN_CATEGORY_URL, "magasin")
    products, raw_links = _parse_magasin_reader_markdown(shared, markdown)
    if raw_links < RETAIL_MIN_PRODUCTS["magasin"] or len(products) < RETAIL_MIN_PRODUCTS["magasin"]:
        raise RuntimeError(
            f"MAGASIN Reader gav {raw_links} rå links / {len(products)} relevante produkter"
        )
    return _refresh_retail_via_reader_details(
        shared,
        "magasin",
        products,
        old_products,
    )


def _parse_broad_retail_products(
    shared,
    source_key,
    category_url,
    html_text,
    is_product_url,
):
    soup = shared["BeautifulSoup"](html_text, "html.parser")
    products = {}

    # Structured data is useful for product identity/price. Availability from
    # category pages is accepted only when Schema.org explicitly supplies it;
    # product detail pages are still refreshed below before alerts are allowed.
    for raw_product in _retail_jsonld_products(soup):
        name = _retail_clean_text(raw_product.get("name"))
        product_url = str(raw_product.get("url") or "")
        if product_url and not product_url.startswith("http"):
            product_url = shared["urljoin"](category_url, product_url)

        if (
            not name
            or not product_url
            or not is_product_url(product_url)
            or not _retail_catalog_product_allowed(source_key, name)
        ):
            continue

        price, in_stock = _retail_offer_values(raw_product)
        product_url = product_url.rstrip("/")
        product_key = _retail_product_key(source_key, product_url)
        products[product_key] = {
            "name": name,
            "game": "POKÉMON",
            "price": price,
            "in_stock": bool(in_stock),
            "availability_known": in_stock is not None,
            "url": product_url,
        }

    # DOM fallback supplies product identity and price. Do NOT infer stock from
    # category-card text: both retailers can render global/hidden stock dialogs
    # that make card-level "Skriv mig op"/cart text ambiguous.
    anchors_by_url = {}
    for anchor in soup.find_all("a", href=True):
        href = shared["urljoin"](category_url, anchor.get("href"))
        href = href.split("#", 1)[0].split("?", 1)[0].rstrip("/")
        if not is_product_url(href):
            continue
        anchors_by_url.setdefault(href, []).append(anchor)

    for product_url, anchors in anchors_by_url.items():
        anchor = max(
            anchors,
            key=lambda item: len(_retail_clean_text(item.get_text(" ", strip=True))),
        )
        card = _retail_nearest_card(anchor, product_url, is_product_url)
        text = _retail_clean_text(card.get_text(" ", strip=True))
        name = _retail_name_from_card(card, anchors)
        if not name or not _retail_catalog_product_allowed(source_key, name):
            continue

        product_key = _retail_product_key(source_key, product_url)
        old = products.get(product_key) or {}
        parsed_price = _retail_price(text)
        products[product_key] = {
            "name": name,
            "game": "POKÉMON",
            "price": parsed_price if parsed_price is not None else old.get("price"),
            "in_stock": bool(old.get("in_stock")),
            "availability_known": bool(old.get("availability_known")),
            "url": product_url,
        }

    return filter_hot_products(shared, products)


def _fetch_retail_html(shared, url, headers):
    curl_requests = shared.get("curl_requests")
    if curl_requests is not None:
        try:
            response = curl_requests.get(
                url,
                headers=headers,
                timeout=30,
                impersonate="chrome",
            )
            response.raise_for_status()
            return response.text
        except Exception as error:
            print(f"HOT retail curl warning {url}: {error}")

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def _parse_retail_detail_availability(shared, source_key, html_text):
    soup = shared["BeautifulSoup"](html_text, "html.parser")
    text = _retail_clean_text(soup.get_text(" ", strip=True)).lower()

    if source_key == "boozt":
        if "læg i kurv" in text or "laeg i kurv" in text:
            return True
        if any(
            marker in text
            for marker in ("giv mig besked", "ikke på lager", "ikke pa lager", "udsolgt")
        ):
            return False
        return None

    # Magasin renders a hidden "Skriv mig op" dialog even on some in-stock
    # pages. The actionable cart button therefore wins if both texts exist.
    if "tilføj til kurv" in text or "tilfoej til kurv" in text:
        return True
    if "skriv mig op" in text or "udsolgt" in text:
        return False
    return None


def _refresh_retail_product_availability(
    shared,
    source_key,
    products,
    old_products,
):
    headers = {
        **shared.get("BROWSER_HEADERS", {}),
        "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
    }
    refreshed = {}
    known_count = 0

    for product_id, product in (products or {}).items():
        current = dict(product)
        old = (old_products or {}).get(product_id)
        try:
            html_text = _fetch_retail_html(shared, current["url"], headers)
            available = _parse_retail_detail_availability(
                shared,
                source_key,
                html_text,
            )
        except Exception as error:
            print(
                f"HOT {SOURCE_LABELS[source_key]} detail warning "
                f"{current.get('name')}: {error}"
            )
            available = None

        if available is not None:
            current["in_stock"] = bool(available)
            current["availability_known"] = True
            known_count += 1
        elif isinstance(old, dict):
            current["in_stock"] = bool(old.get("in_stock"))
            current["availability_known"] = bool(
                old.get("availability_known", False)
            )
        else:
            current["in_stock"] = False
            current["availability_known"] = False

        refreshed[product_id] = current

    required_known = max(
        RETAIL_MIN_PRODUCTS[source_key],
        (len(refreshed) + 1) // 2,
    )
    if known_count < required_known:
        raise RuntimeError(
            f"{SOURCE_LABELS[source_key]} lagerstatus kun kendt for "
            f"{known_count}/{len(refreshed)} produkter "
            f"(minimum {required_known})"
        )

    return refreshed


def _fetch_broad_retail_products(
    shared,
    source_key,
    category_url,
    is_product_url,
    old_products,
):
    headers = {
        **shared.get("BROWSER_HEADERS", {}),
        "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
    }
    html_text = _fetch_retail_html(shared, category_url, headers)

    filtered = _parse_broad_retail_products(
        shared,
        source_key,
        category_url,
        html_text,
        is_product_url,
    )

    minimum = RETAIL_MIN_PRODUCTS[source_key]
    if len(filtered) < minimum:
        raise RuntimeError(
            f"{SOURCE_LABELS[source_key]} gav kun {len(filtered)} relevante produkter "
            f"(minimum {minimum})"
        )

    if source_key == "boozt":
        for product in filtered.values():
            product["in_stock"] = True
            product["availability_known"] = True
            product["fetch_via"] = "direct_category"
        return filtered

    return _refresh_retail_product_availability(
        shared,
        source_key,
        filtered,
        old_products,
    )

def _boozt_product_url(value):
    text = str(value or "").lower().split("#", 1)[0].split("?", 1)[0].rstrip("/")
    return "/dk/da/pokmon-trading-cards/" in text and bool(
        re.search(r"_\d{6,}(?:/\d{6,})?$", text)
    )

def _magasin_product_url(value):
    text = str(value or "").lower()
    if "magasin.dk" in text and "/search" in text:
        return False
    return text.endswith(".html") or ".html?" in text


def _preserve_missing_as_out_of_stock(source_key, old_products, current_products):
    merged = {}
    for product_id, product in (old_products or {}).items():
        if not isinstance(product, dict):
            continue
        if not _retail_catalog_product_allowed(source_key, product.get("name")):
            continue
        stale = dict(product)
        stale["in_stock"] = False
        stale["availability_known"] = True
        merged[str(product_id)] = stale

    for product_id, product in (current_products or {}).items():
        merged[str(product_id)] = product

    return merged



def _magasin_tcg_url_allowed(value):
    text = str(value or "").lower()
    if "magasin.dk/" not in text or ".html" not in text:
        return False
    if "poke" not in text and "pokemon" not in text:
        return False
    return any(marker in text for marker in MAGASIN_TCG_URL_MARKERS)


def _magasin_sitemap_number(url):
    match = re.search(r"/sitemap_(\d+)-product\.xml(?:$|[?#])", str(url or ""), re.I)
    return int(match.group(1)) if match else -1


def _magasin_meta(state):
    return (
        state.setdefault("retail_meta", {})
        .setdefault("magasin", {})
    )


def _magasin_discover_candidates(state, old_products):
    meta = _magasin_meta(state)
    now = time.time()

    candidates = {
        str(product.get("url"))
        for product in (old_products or {}).values()
        if isinstance(product, dict)
        and product.get("url")
        and _magasin_tcg_url_allowed(product.get("url"))
    }

    last_discovery = float(meta.get("last_discovery_epoch") or 0)
    if candidates and now - last_discovery < MAGASIN_DISCOVERY_INTERVAL_SECONDS:
        return sorted(candidates)

    headers = {
        "User-Agent": "Mozilla/5.0 Pokemon-Lorcana-MasterBot/4.0",
        "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.5",
        "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
    }
    response = requests.get(MAGASIN_SITEMAP_INDEX_URL, headers=headers, timeout=30)
    response.raise_for_status()
    sitemap_urls = re.findall(
        r"<loc>\s*(https://www\.magasin\.dk/sitemap_\d+-product\.xml)\s*</loc>",
        response.text or "",
        flags=re.IGNORECASE,
    )
    sitemap_urls = sorted(set(sitemap_urls), key=_magasin_sitemap_number)
    if not sitemap_urls:
        raise RuntimeError("MAGASIN sitemap-index gav ingen product-sitemaps")

    sitemap_meta = meta.setdefault("sitemaps", {})
    last_full = float(meta.get("last_full_discovery_epoch") or 0)
    full_refresh = (
        not meta.get("initialized")
        or now - last_full >= MAGASIN_FULL_DISCOVERY_INTERVAL_SECONDS
    )
    targets = sitemap_urls if full_refresh else [sitemap_urls[-1]]

    successful_targets = 0
    for sitemap_url in targets:
        cached = sitemap_meta.setdefault(sitemap_url, {})
        request_headers = dict(headers)
        if cached.get("etag"):
            request_headers["If-None-Match"] = cached["etag"]
        if cached.get("last_modified"):
            request_headers["If-Modified-Since"] = cached["last_modified"]

        try:
            sitemap_response = requests.get(
                sitemap_url,
                headers=request_headers,
                timeout=35,
            )
            if sitemap_response.status_code == 304:
                discovered = cached.get("candidates") or []
            else:
                sitemap_response.raise_for_status()
                product_urls = re.findall(
                    r"<loc>\s*(https://www\.magasin\.dk/[^<]+?\.html)\s*</loc>",
                    sitemap_response.text or "",
                    flags=re.IGNORECASE,
                )
                discovered = sorted({
                    url.strip()
                    for url in product_urls
                    if _magasin_tcg_url_allowed(url)
                })
                cached["etag"] = sitemap_response.headers.get("ETag") or ""
                cached["last_modified"] = (
                    sitemap_response.headers.get("Last-Modified") or ""
                )
                cached["candidates"] = discovered
                cached["last_checked"] = _utc_now_iso()

            candidates.update(discovered)
            successful_targets += 1
        except Exception as error:
            print(
                f"HOT MAGASIN sitemap warning {sitemap_url}: {error}"
            )
            candidates.update(cached.get("candidates") or [])

    if not successful_targets and not candidates:
        raise RuntimeError("MAGASIN product-sitemaps kunne ikke læses")

    meta["initialized"] = True
    meta["last_discovery_epoch"] = now
    if full_refresh:
        meta["last_full_discovery_epoch"] = now
    meta["product_sitemaps"] = sitemap_urls

    if len(candidates) < RETAIL_MIN_PRODUCTS["magasin"]:
        raise RuntimeError(
            f"MAGASIN sitemap gav kun {len(candidates)} TCG-kandidater"
        )

    return sorted(candidates)


def _magasin_gtm_item(html_text):
    match = re.search(
        r'gtm-product-detail-view="([^"]+)"',
        html_text or "",
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    try:
        payload = json.loads(unescape(match.group(1)))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None

    items = ((payload.get("ecommerce") or {}).get("items") or [])
    if not items or not isinstance(items[0], dict):
        return None
    return items[0]


def _magasin_parse_product_response(
    shared,
    product_url,
    html_text,
    final_url,
    old_product=None,
):
    old_product = old_product or {}
    if "productnotfound=" in str(final_url or "").lower():
        stale = dict(old_product)
        stale.update({
            "name": stale.get("name") or _retail_name_from_slug(product_url),
            "game": "POKÉMON",
            "in_stock": False,
            "availability_known": True,
            "preorder": False,
            "url": product_url,
            "fetch_via": "direct_product_redirect",
        })
        return stale

    soup = shared["BeautifulSoup"](html_text, "html.parser")
    name = ""
    price = None
    in_stock = None

    structured_products = _retail_jsonld_products(soup)
    if structured_products:
        raw_product = structured_products[0]
        name = _retail_clean_text(raw_product.get("name"))
        price, in_stock = _retail_offer_values(raw_product)

    gtm_item = _magasin_gtm_item(html_text)
    if gtm_item:
        if not name:
            name = _retail_clean_text(gtm_item.get("item_name"))
        if price is None:
            try:
                price = float(gtm_item.get("price"))
            except (TypeError, ValueError):
                pass

        stock_status = str(gtm_item.get("stock_status") or "").strip().lower()
        if stock_status in {"in stock", "instock", "på lager", "pa lager"}:
            in_stock = True
        elif stock_status in {
            "out of stock", "outofstock", "not in stock",
            "udsolgt", "ikke på lager", "ikke pa lager",
        }:
            in_stock = False

    if not name:
        name = old_product.get("name") or _retail_name_from_slug(product_url)

    if not _retail_catalog_product_allowed("magasin", name):
        raise RuntimeError(f"ikke-TCG Magasin-produkt: {name}")

    availability_known = in_stock is not None
    if not availability_known and old_product:
        in_stock = bool(old_product.get("in_stock"))
        availability_known = bool(old_product.get("availability_known", False))

    return {
        "name": name,
        "game": "POKÉMON",
        "price": price if price is not None else old_product.get("price"),
        "in_stock": bool(in_stock),
        "availability_known": availability_known,
        "preorder": False,
        "url": product_url,
        "fetch_via": "direct_product",
    }


def _magasin_fetch_product(shared, product_url, old_product=None):
    headers = {
        **shared.get("BROWSER_HEADERS", {}),
        "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
    }
    response = requests.get(
        product_url,
        headers=headers,
        timeout=30,
        allow_redirects=True,
    )
    response.raise_for_status()
    return _magasin_parse_product_response(
        shared,
        product_url,
        response.text,
        response.url,
        old_product,
    )


def _fetch_magasin_via_sitemaps(shared, old_products, state):
    candidate_urls = _magasin_discover_candidates(state, old_products)
    old_by_url = {
        str(product.get("url")): product
        for product in (old_products or {}).values()
        if isinstance(product, dict) and product.get("url")
    }

    products = {}
    known_count = 0

    def worker(product_url):
        old = old_by_url.get(product_url)
        try:
            product = _magasin_fetch_product(shared, product_url, old)
            return product_url, product, None
        except Exception as error:
            return product_url, old, error

    with ThreadPoolExecutor(
        max_workers=min(4, max(1, len(candidate_urls)))
    ) as executor:
        for product_url, product, error in executor.map(worker, candidate_urls):
            if error is not None:
                print(f"HOT MAGASIN detail warning {product_url}: {error}")
                if not isinstance(product, dict):
                    continue
                product = dict(product)
                product["fetch_via"] = "stale_after_error"

            if not isinstance(product, dict):
                continue
            if not _retail_catalog_product_allowed(
                "magasin",
                product.get("name"),
            ):
                continue

            key = _retail_product_key("magasin", product_url)
            products[key] = product
            if product.get("availability_known"):
                known_count += 1

    products = filter_hot_products(shared, products)
    required_known = max(
        RETAIL_MIN_PRODUCTS["magasin"],
        (len(products) + 1) // 2,
    )
    if len(products) < RETAIL_MIN_PRODUCTS["magasin"]:
        raise RuntimeError(
            f"MAGASIN gav kun {len(products)} relevante sitemap-produkter"
        )
    if known_count < required_known:
        raise RuntimeError(
            f"MAGASIN lagerstatus kun kendt for {known_count}/{len(products)} "
            f"(minimum {required_known})"
        )

    return products


def get_boozt_products(shared, old_products):
    errors = []
    try:
        current = _fetch_boozt_via_reader(shared)
    except Exception as error:
        errors.append(f"Reader: {error}")
        try:
            current = _fetch_broad_retail_products(
                shared,
                "boozt",
                BOOZT_CATEGORY_URL,
                _boozt_product_url,
                old_products,
            )
        except Exception as fallback_error:
            errors.append(f"direct: {fallback_error}")
            raise RuntimeError("BOOZT fejlede: " + " | ".join(errors))

    return _preserve_missing_as_out_of_stock("boozt", old_products, current)


def get_magasin_products(shared, old_products, state):
    return _fetch_magasin_via_sitemaps(
        shared,
        old_products,
        state,
    )


def fetch_source(shared, source_key, old_products, state=None):
    if source_key == "coolshop":
        return shared["get_coolshop_products"]()
    if source_key == "proshop":
        return _fetch_expanded_proshop_products(shared)
    if source_key == "br":
        return shared["get_br_products"](old_products)
    if source_key in ("bilka", "foetex"):
        return shared["get_salling_products"](source_key, old_products)
    if source_key == "boozt":
        return get_boozt_products(shared, old_products)
    if source_key == "magasin":
        return get_magasin_products(shared, old_products, state or {})
    raise KeyError(source_key)


def run_scan(shared, state):
    source_state = state.setdefault("sources", {})
    successful = 0

    for source_key in SOURCE_LABELS:
        label = SOURCE_LABELS[source_key]
        retail_version_changed = (
            source_key in ("boozt", "magasin")
            and (state.get("retail_discovery_versions") or {}).get(source_key)
            != RETAIL_DISCOVERY_VERSION
        )
        if retail_version_changed:
            control = _source_control(state, source_key)
            control["backoff_level"] = 0
            control["next_allowed_at"] = 0.0
            control["generic_failures"] = 0
            if source_key == "magasin":
                state.setdefault("retail_meta", {})["magasin"] = {}

        wait_seconds = _source_wait_seconds(state, source_key)
        if wait_seconds > 0:
            level = _source_control(state, source_key)["backoff_level"]
            if source_key == "magasin" and level == 0:
                print(
                    f"HOT {label} cadence: næste produkttjek om "
                    f"{wait_seconds}s"
                )
            else:
                print(
                    f"HOT {label} BACKOFF: springer over i {wait_seconds}s "
                    f"(niveau {level})"
                )
            continue

        old_products = source_state.get(source_key)
        source_baseline = not isinstance(old_products, dict)
        if (
            source_key == "proshop"
            and state.get("proshop_discovery_version") != PROSHOP_DISCOVERY_VERSION
        ):
            source_baseline = True
        if retail_version_changed:
            source_baseline = True
        old_products = old_products if isinstance(old_products, dict) else {}
        if retail_version_changed:
            old_products = {}

        try:
            fetched = fetch_source(shared, source_key, old_products, state)
            current = filter_hot_products(shared, fetched)
        except Exception as error:
            delay = _register_source_failure(state, source_key, error)
            if delay:
                level = _source_control(state, source_key)["backoff_level"]
                print(
                    f"HOT {label} FEJL: {error} | "
                    f"backoff {delay}s (niveau {level})"
                )
            else:
                print(f"HOT {label} FEJL: {error}")
            continue

        previous_level, current_level = _register_source_success(state, source_key)
        if previous_level > current_level:
            next_delay = RATE_LIMIT_BACKOFF_SECONDS[current_level]
            if next_delay:
                print(
                    f"HOT {label} RECOVERY: niveau {previous_level} -> "
                    f"{current_level}; næste tjek om {next_delay}s"
                )
            else:
                print(f"HOT {label} RECOVERY: tilbage på normal 1-minuts frekvens")

        successful += 1

        if source_baseline:
            print(
                f"HOT {label} baseline: "
                f"{len(current)} relevante produkter, ingen alerts"
            )
        else:
            for product_id, product in current.items():
                if not product_available(source_key, product):
                    continue

                old = old_products.get(product_id)
                if old is None:
                    send_hot_alert(source_key, product, "NYT")
                    continue

                if (
                    source_key in ("boozt", "magasin")
                    and not old.get("availability_known", False)
                ):
                    continue

                if not product_available(source_key, old):
                    send_hot_alert(source_key, product, "RESTOCK")

        source_state[source_key] = current
        if source_key == "proshop":
            state["proshop_discovery_version"] = PROSHOP_DISCOVERY_VERSION
        if source_key in ("boozt", "magasin"):
            state.setdefault("retail_discovery_versions", {})[
                source_key
            ] = RETAIL_DISCOVERY_VERSION
        if source_key == "magasin":
            _source_control(state, source_key)["next_allowed_at"] = (
                time.time() + MAGASIN_DISCOVERY_INTERVAL_SECONDS
            )

        print(
            f"HOT {label}: "
            f"{len(current)} relevante · "
            f"{sum(product_available(source_key, p) for p in current.values())} på lager"
        )

    state["filter_version"] = FILTER_VERSION
    state["updated_at"] = _utc_now_iso()
    save_state(state)
    return successful


def main():
    shared = load_shared_namespace()
    state = load_state()

    if not isinstance(state, dict) or state.get("filter_version") != FILTER_VERSION:
        state = {
            "filter_version": FILTER_VERSION,
            "sources": {},
            "source_controls": {},
            "updated_at": None,
        }
        print("HOT scanner: opretter stille baseline")
    else:
        state.setdefault("source_controls", {})

    for iteration in range(HOT_ITERATIONS):
        started = time.monotonic()
        print(f"HOT scan {iteration + 1}/{HOT_ITERATIONS}")
        successful = run_scan(shared, state)
        print(f"HOT scan færdig: {successful}/{len(SOURCE_LABELS)} kilder lykkedes")

        if iteration + 1 >= HOT_ITERATIONS:
            break

        elapsed = time.monotonic() - started
        sleep_for = max(0.0, HOT_INTERVAL_SECONDS - elapsed)
        if sleep_for:
            time.sleep(sleep_for)


if __name__ == "__main__":
    main()
