import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parent
SHARED_FILE = ROOT / "restock_bot_github.py"
STATE_FILE = ROOT / "hot_restock_state.json"
FILTER_VERSION = 1

HOT_ITERATIONS = max(1, int(os.getenv("HOT_ITERATIONS", "1")))
HOT_INTERVAL_SECONDS = max(30, int(os.getenv("HOT_INTERVAL_SECONDS", "60")))
HOT_DRY_RUN = os.getenv("HOT_DRY_RUN", "0").strip() == "1"
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

# Proshop's dedicated card category is small and can lag behind the broader
# Pokemon catalogue. HOT therefore reads several public discovery views and
# merges them by stable product id. Search views are especially useful for
# products that exist in Proshop's catalogue but are not exposed in a category
# yet. The first successful expanded scan is a silent Proshop-only baseline so
# rollout cannot create a burst of old "new product" alerts.
PROSHOP_BROAD_URL = "https://www.proshop.dk/Pokemon"
PROSHOP_BROAD_READER_URL = "https://r.jina.ai/" + PROSHOP_BROAD_URL
PROSHOP_SEARCH_TERMS = (
    "Pokemon TCG",
    "Pokemon booster",
)
PROSHOP_DISCOVERY_VERSION = 3

# Each source normally gets checked every HOT loop. If a source starts
# returning rate-limit/bot-block signals, only that source slows down:
# 1 min -> 2 min -> 5 min -> 15 min. Successful checks recover one step
# at a time so the remaining sources can continue at full speed.
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

EXCLUDED_ETB_SETS = (
    "chaos rising",
    "pitch black",
)

CORE_MARKERS = (
    "booster bundle",
    "booster box",
    "booster display",
)

COLLECTION_MARKERS = (
    "premium collection",
    "ultra-premium collection",
    "ultra premium collection",
    "special collection",
    "illustration collection",
)

WATCH_MARKERS = (
    "first partner",
    "30th anniversary",
    "30th",
    "ascended heroes",
    "white flare",
    "black bolt",
)

PACK_MARKERS = (
    "booster pack",
    "sleeved booster",
    "sleeve booster",
)

SOURCE_LABELS = {
    "proshop": "PROSHOP",
    "br": "BR",
    "bilka": "BILKA",
    "foetex": "FØTEX",
}


def _clean_name(name):
    return " " + re.sub(r"\s+", " ", str(name or "").lower()).strip() + " "


def hot_product_allowed(name):
    text = _clean_name(name)

    # Single packs stay out of the fast lane, even for watched sets.
    if any(marker in text for marker in PACK_MARKERS):
        return False

    # Some shops call a loose pack simply "booster". Keep it out unless the
    # title explicitly says bundle/box/display.
    if (
        " booster " in text
        and not any(marker in text for marker in CORE_MARKERS)
        and "elite trainer box" not in text
        and not re.search(r"\betb\b", text)
        and not any(marker in text for marker in COLLECTION_MARKERS)
    ):
        return False

    is_etb = "elite trainer box" in text or bool(re.search(r"\betb\b", text))
    if is_etb:
        return not any(blocked in text for blocked in EXCLUDED_ETB_SETS)

    if any(marker in text for marker in CORE_MARKERS):
        return True

    if any(marker in text for marker in COLLECTION_MARKERS):
        return True

    if " ultra premium " in text or bool(re.search(r"\bupc\b", text)):
        return True

    if any(marker in text for marker in WATCH_MARKERS):
        return True

    return False


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

    return False


def availability_text(source_key, product):
    if source_key == "proshop":
        return product.get("stock") or "UKENDT"

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

    response = requests.post(
        WEBHOOK_URL,
        json={"content": message},
        timeout=15,
    )
    response.raise_for_status()


def filter_hot_products(shared, products):
    allowed = {}
    shared_relevance = shared["restock_alert_allowed"]

    for product_id, product in (products or {}).items():
        if not isinstance(product, dict):
            continue
        if not shared_relevance(product, "POKÉMON"):
            continue
        if not hot_product_allowed(product.get("name")):
            continue
        allowed[str(product_id)] = product

    return allowed


def _reader_headers(user_agent):
    return {
        "Accept": "text/plain, text/markdown;q=0.9, */*;q=0.5",
        "User-Agent": user_agent,
        "x-no-cache": "true",
        "x-engine": "browser",
    }


def _proshop_raw_link_count(text):
    raw_link_pattern = re.compile(
        r"(?:https?://(?:www\.)?proshop\.dk)?/Pokemon/[^)\s?#]+/\d+",
        re.IGNORECASE,
    )
    return len(set(raw_link_pattern.findall(text or "")))


def _fetch_proshop_reader_view(shared, public_url, fetch_via, user_agent):
    reader_url = "https://r.jina.ai/" + public_url
    response = requests.get(
        reader_url,
        headers=_reader_headers(user_agent),
        timeout=50,
    )
    response.raise_for_status()

    raw_product_links = _proshop_raw_link_count(response.text)
    products = shared["_parse_proshop_reader_markdown"](response.text)

    for product in products.values():
        if isinstance(product, dict):
            product["fetch_via"] = fetch_via

    return products, raw_product_links


def _fetch_proshop_broad_products(shared):
    """Read Proshop's broad Pokemon catalogue through the public Reader."""
    products, raw_product_links = _fetch_proshop_reader_view(
        shared,
        PROSHOP_BROAD_URL,
        "jina_reader_broad",
        "Pokemon-Lorcana-MasterBot/2.7 ProshopBroadDiscovery",
    )

    if raw_product_links < 10:
        raise RuntimeError(
            "Proshop broad Reader returned too little raw data "
            f"({raw_product_links} product links)"
        )
    if not products:
        raise RuntimeError(
            "Proshop broad Reader parser extracted 0 TCG products from "
            f"{raw_product_links} product links"
        )

    print(
        f"HOT PROSHOP broad discovery: {len(products)} TCG-produkter "
        f"fra {raw_product_links} rå produktlinks"
    )
    return products


def _fetch_proshop_search_products(shared):
    """Probe Proshop's own public search for catalogue-only TCG listings.

    Proshop explicitly allows the ?s= search route in robots.txt. Search can
    expose a SKU even when it has not reached the dedicated Pokemon-card page,
    which is the gap we care about for short-lived listings.
    """
    merged = {}
    successful_terms = 0
    total_raw_links = 0
    errors = []

    def fetch_term(term):
        public_url = "https://www.proshop.dk/?s=" + quote(term)
        return term, _fetch_proshop_reader_view(
            shared,
            public_url,
            "jina_reader_search",
            "Pokemon-Lorcana-MasterBot/2.7 ProshopSearchDiscovery",
        )

    with ThreadPoolExecutor(max_workers=len(PROSHOP_SEARCH_TERMS)) as pool:
        futures = [pool.submit(fetch_term, term) for term in PROSHOP_SEARCH_TERMS]
        for future in futures:
            try:
                term, (products, raw_links) = future.result()
                successful_terms += 1
                total_raw_links += raw_links
                print(
                    f"HOT PROSHOP search '{term}': {len(products)} TCG-produkter "
                    f"fra {raw_links} rå produktlinks"
                )
                for product_id, product in products.items():
                    merged[str(product_id)] = product
            except Exception as error:
                errors.append(str(error))

    if successful_terms == 0:
        detail = "; ".join(errors[-4:]) if errors else "ukendt fejl"
        raise RuntimeError(f"Proshop search discovery fejlede ({detail})")

    print(
        f"HOT PROSHOP search discovery samlet: {len(merged)} TCG-produkter "
        f"fra {successful_terms}/{len(PROSHOP_SEARCH_TERMS)} søgninger · "
        f"{total_raw_links} rå links"
    )
    return merged


def _merge_proshop_products(*product_sets):
    """Merge Proshop views by stable product id without degrading good data.

    Earlier views seed discovery. Later views win for explicit price/stock,
    so the dedicated card category can override broad/search data when it has
    fresher availability while search-only SKUs remain preserved.
    """
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
    """Fetch curated, broad and search Proshop views concurrently and merge."""
    curated = {}
    broad = {}
    search = {}
    errors = []

    with ThreadPoolExecutor(max_workers=3) as pool:
        curated_future = pool.submit(shared["get_proshop_products"])
        broad_future = pool.submit(_fetch_proshop_broad_products, shared)
        search_future = pool.submit(_fetch_proshop_search_products, shared)

        try:
            curated = curated_future.result()
        except Exception as error:
            errors.append(f"curated: {error}")

        try:
            broad = broad_future.result()
        except Exception as error:
            errors.append(f"broad: {error}")

        try:
            search = search_future.result()
        except Exception as error:
            errors.append(f"search: {error}")

    if not curated and not broad and not search:
        detail = "; ".join(errors[-6:]) if errors else "ukendt fejl"
        raise RuntimeError(f"Alle Proshop discovery-ruter fejlede ({detail})")

    if errors:
        print("HOT PROSHOP discovery warning: " + "; ".join(errors))

    merged = _merge_proshop_products(broad, search, curated)
    curated_ids = set(map(str, curated))
    broad_ids = set(map(str, broad))
    search_ids = set(map(str, search))
    search_only = len(search_ids - curated_ids - broad_ids)
    broad_only = len(broad_ids - curated_ids - search_ids)

    print(
        f"HOT PROSHOP discovery: curated={len(curated)} · broad={len(broad)} · "
        f"search={len(search)} · merged={len(merged)} · "
        f"search-only={search_only} · broad-only={broad_only}"
    )
    return merged


def fetch_source(shared, source_key, old_products):
    if source_key == "proshop":
        return _fetch_expanded_proshop_products(shared)
    if source_key == "br":
        return shared["get_br_products"](old_products)
    if source_key in ("bilka", "foetex"):
        return shared["get_salling_products"](source_key, old_products)
    raise KeyError(source_key)


def run_scan(shared, state):
    source_state = state.setdefault("sources", {})
    successful = 0

    for source_key in SOURCE_LABELS:
        label = SOURCE_LABELS[source_key]
        wait_seconds = _source_wait_seconds(state, source_key)
        if wait_seconds > 0:
            level = _source_control(state, source_key)["backoff_level"]
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
        old_products = old_products if isinstance(old_products, dict) else {}

        try:
            fetched = fetch_source(shared, source_key, old_products)
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

        previous_level, current_level = _register_source_success(
            state,
            source_key,
        )
        if previous_level > current_level:
            next_delay = RATE_LIMIT_BACKOFF_SECONDS[current_level]
            if next_delay:
                print(
                    f"HOT {label} RECOVERY: niveau {previous_level} -> "
                    f"{current_level}; næste tjek om {next_delay}s"
                )
            else:
                print(
                    f"HOT {label} RECOVERY: tilbage på normal 1-minuts frekvens"
                )

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

                if not product_available(source_key, old):
                    send_hot_alert(source_key, product, "RESTOCK")

        source_state[source_key] = current
        if source_key == "proshop":
            state["proshop_discovery_version"] = PROSHOP_DISCOVERY_VERSION
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