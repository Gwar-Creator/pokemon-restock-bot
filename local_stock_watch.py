import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup
from alert_policy import abundant_set_signal_allowed

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
STATE_FILE = "local_stock_state_v1.json"
SALLING_DISCOVERY_V45 = True
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )
}

SITES = {
    "br": {
        "label": "BR",
        "home": "https://www.br.dk/",
        "base": "https://www.br.dk",
        "api_url": "https://api.sallinggroup.com/v1/ecommerce/br",
        "algolia_index": "prod_BR_PRODUCTS",
    },
    "bilka": {
        "label": "BILKA",
        "home": "https://www.bilka.dk/",
        "base": "https://www.bilka.dk",
    },
    "foetex": {
        "label": "FØTEX",
        "home": "https://www.foetex.dk/",
        "base": "https://www.foetex.dk",
    },
}

TARGET_STORE_MARKERS = (
    "kolding",
    "fredericia",
    "vejen",
    "brørup",
    "brorup",
    "esbjerg",
)

NON_ENGLISH_CARD_MARKERS = (
    "japansk",
    "japanese",
    "japan import",
    "kinesisk",
    "chinese",
    "simplified chinese",
    "traditional chinese",
    "koreansk",
    "korean",
    "tysk",
    "german",
    "deutsch",
    "fransk",
    "french",
    "italiensk",
    "italian",
    "spansk",
    "spanish",
    "portugisisk",
    "portuguese",
    "hollandsk",
    "dutch",
    "thai",
    "thailand",
    "indonesisk",
    "indonesian",
)


def is_english_card_product(name):
    text = " " + re.sub(r"\s+", " ", str(name or "").lower()) + " "
    return not any(marker in text for marker in NON_ENGLISH_CARD_MARKERS)


KNOWN_SET_ALIASES = (
    ("Mega Evolution: Phantasmal Flames", ("phantasmal flames",)),
    ("Mega Evolution: Chaos Rising", ("chaos rising", "mega evolution chaos rising")),
    ("Mega Evolution: Perfect Order", ("perfect order", "mega evolution perfect order")),
    ("Scarlet & Violet: Destined Rivals", ("destined rivals", "rivals booster", "pokemon rivals booster")),
    ("Mega Evolution: Pitch Black", ("pitch black",)),
    ("Mega Evolution: Ascended Heroes", ("ascended heroes",)),
    ("Scarlet & Violet: Black Bolt", ("black bolt",)),
    ("Scarlet & Violet: White Flare", ("white flare",)),
    ("Scarlet & Violet: Journey Together", ("journey together",)),
    ("Scarlet & Violet: Prismatic Evolutions", ("prismatic evolutions",)),
    ("Scarlet & Violet: Surging Sparks", ("surging sparks",)),
    ("Scarlet & Violet: Stellar Crown", ("stellar crown",)),
    ("Scarlet & Violet: Shrouded Fable", ("shrouded fable",)),
    ("Scarlet & Violet: Twilight Masquerade", ("twilight masquerade",)),
    ("Scarlet & Violet: Temporal Forces", ("temporal forces",)),
    ("Scarlet & Violet: Paldean Fates", ("paldean fates",)),
    ("Scarlet & Violet: Paradox Rift", ("paradox rift",)),
    ("Scarlet & Violet: 151", ("pokemon 151", "pokémon 151", "scarlet violet 151")),
    ("Scarlet & Violet: Obsidian Flames", ("obsidian flames",)),
    ("Scarlet & Violet: Paldea Evolved", ("paldea evolved",)),
)

KNOWN_PRODUCT_SERIES = {
    "200356078": "Mega Evolution: Perfect Order",
    "11221188-EA": "Mega Evolution: Perfect Order",
    "200366277": "Mega Evolution: Chaos Rising",
    "11263280-EA": "Mega Evolution: Chaos Rising",
}


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_search_text(value):
    text = (
        str(value or "")
        .lower()
        .replace("pokémon", "pokemon")
        .replace("–", " ")
        .replace("—", " ")
    )
    text = re.sub(r"[^a-z0-9æøå:]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def infer_series(product):
    normalized = normalize_search_text(
        json.dumps(product, ensure_ascii=False, sort_keys=True)
    )
    for marker, series_name in KNOWN_PRODUCT_SERIES.items():
        if normalize_search_text(marker) in normalized:
            return series_name, "product-id"
    for series_name, aliases in KNOWN_SET_ALIASES:
        if any(normalize_search_text(alias) in normalized for alias in aliases):
            return series_name, "metadata"
    return None, None


def extract_config_value(text, key):
    match = re.search(
        re.escape(key) + r'["\']?\s*:\s*["\']([^"\']+)["\']',
        text,
    )
    return match.group(1) if match else None


def get_frontend_config(site_key):
    site = SITES[site_key]
    response = requests.get(site["home"], headers=BROWSER_HEADERS, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    script_urls = [
        urljoin(site["base"], script["src"])
        for script in soup.find_all("script", src=True)
    ]
    script_urls = list(dict.fromkeys(script_urls))
    script_urls.sort(
        key=lambda url: (
            0 if "app.js" in url.lower() else 1,
            0 if "commons.app.js" in url.lower() else 1,
            len(url),
        )
    )

    texts = [response.text]
    for script_url in script_urls[:30]:
        try:
            script_response = requests.get(
                script_url,
                headers=BROWSER_HEADERS,
                timeout=20,
            )
            script_response.raise_for_status()
            texts.append(script_response.text)
            if (
                "NUXT_ENV_API_TOKEN" in script_response.text
                and "NUXT_ENV_ALGOLIA_API_KEY" in script_response.text
            ):
                break
        except requests.RequestException:
            continue

    keys = {
        "api_token": "NUXT_ENV_API_TOKEN",
        "api_url": "NUXT_ENV_API_URL",
        "algolia_api_key": "NUXT_ENV_ALGOLIA_API_KEY",
        "algolia_app_id": "NUXT_ENV_ALGOLIA_APLICATION_ID",
        "algolia_index": "NUXT_ENV_ALGOLIA_DEFAULT_INDEX",
    }
    config = {
        "api_token": None,
        "api_url": site.get("api_url"),
        "algolia_api_key": None,
        "algolia_app_id": None,
        "algolia_index": site.get("algolia_index"),
    }

    for text in texts:
        for out_key, source_key in keys.items():
            if not config[out_key]:
                config[out_key] = extract_config_value(text, source_key)
        if not config["algolia_app_id"]:
            config["algolia_app_id"] = extract_config_value(
                text,
                "NUXT_ENV_ALGOLIA_APPLICATION_ID",
            )

    missing = [key for key, value in config.items() if not value]
    if missing:
        raise RuntimeError(
            f"{site['label']} mangler frontend-config: {', '.join(missing)}"
        )
    return config


def pokemon_product_type(name, product=None):
    text = " " + re.sub(r"\s+", " ", str(name or "").lower()) + " "
    metadata = " " + normalize_search_text(
        json.dumps(product or {}, ensure_ascii=False, sort_keys=True)
    ) + " "

    if any(marker in text for marker in ("checklane", "check lane", "battle deck", "battledeck")):
        return None

    # Official Pokemon Mini Portfolio products include a booster pack, even if
    # the Salling title only says "Mini Portfolio". Pure portfolios/maps stay out.
    if " mini portfolio " in text:
        return "MINI PORTFOLIO"

    if " blister " in text:
        return "BLISTER"

    if " portfolio " in text or " mappe " in text:
        if " booster " in text or " booster " in metadata:
            return "PORTFOLIO + BOOSTER"
        return None

    if any(
        marker in text
        for marker in (
            " sleeve ",
            " sleeves ",
            " deck box ",
            " penalhus ",
            " pencil case ",
        )
    ):
        return None

    if "booster bundle" in text:
        if "bundle display" in text or "booster bundle display" in text:
            return None
        return "BOOSTER BUNDLE"
    if "booster box" in text or "booster display" in text:
        return "BOOSTER BOX"
    if "elite trainer box" in text or re.search(r"\betb\b", text):
        return "ETB"
    if (
        "mini tin" in text
        or "poké ball tin" in text
        or "poke ball tin" in text
        or re.search(r"\btins?\b", text)
    ):
        return "TIN"
    if any(
        marker in text
        for marker in (
            " premium collection ",
            " ultra-premium collection ",
            " special collection ",
            " illustration collection ",
            " binder collection ",
            " poster collection ",
            " playmat collection ",
            " accessory pouch special collection ",
            " first partner ",
            " collection box ",
            " ex box ",
            " upc ",
        )
    ):
        return "COLLECTION"
    if " binder " in text or " playmat " in text:
        return None
    if "booster" in text:
        return "BOOSTER PACK"
    return None


def is_pokemon_hit(product):
    text = (
        f"{product.get('name') or ''} "
        f"{product.get('brand') or product.get('f_brand') or ''} "
        f"{product.get('facets.productSeriesToys') or ''} "
        f"{(product.get('supplier_information') or {}).get('manufacturer_name') or ''}"
    ).lower()
    return "pokemon" in text or "pokémon" in text


def visibility_status(product):
    raw = product.get("is_exposed")
    normalized = str(raw).strip().lower()
    if raw is True or normalized == "true":
        return "LIVE"
    if raw is False or normalized == "false":
        return "PRE-PUBLISH"
    return "UNKNOWN"


def get_algolia_candidates(site_key, config):
    algolia_url = (
        f"https://{config['algolia_app_id'].lower()}"
        "-dsn.algolia.net/1/indexes/*/queries"
    )
    params = {
        "query": "",
        "attributesToRetrieve": '["*"]',
        "filters": 'cfh_nodes:"CFH.CollectionCards"',
        "distinct": "true",
        "page": 0,
        "hitsPerPage": 500,
    }
    payload = {
        "requests": [
            {
                "indexName": config["algolia_index"],
                "params": urlencode(params),
            }
        ]
    }
    response = requests.post(
        algolia_url,
        headers={
            **BROWSER_HEADERS,
            "Content-Type": "application/json",
            "x-algolia-application-id": config["algolia_app_id"],
            "x-algolia-api-key": config["algolia_api_key"],
        },
        json=payload,
        timeout=25,
    )
    response.raise_for_status()
    hits = response.json()["results"][0].get("hits", [])

    candidates = []
    for product in hits:
        if not is_pokemon_hit(product):
            continue
        if not is_english_card_product(product.get("name")):
            continue
        product_type = pokemon_product_type(product.get("name"), product)
        if not product_type:
            continue
        sku = product.get("sku") or product.get("erp_product_id")
        if not sku:
            continue

        product_url = product.get("product_url") or ""
        series_name, series_source = infer_series(product)
        candidates.append(
            {
                "id": str(product.get("id") or product.get("objectID") or sku),
                "name": str(product.get("name") or "Ukendt produkt"),
                "type": product_type,
                "series": series_name,
                "series_source": series_source,
                "sku": str(sku),
                "price": product.get("sales_price"),
                "visibility": visibility_status(product),
                "store_count": max(
                    0,
                    safe_int(product.get("in_stock_stores_count"), 0),
                ),
                "url": (
                    urljoin(SITES[site_key]["base"], product_url)
                    if product_url
                    else ""
                ),
            }
        )
    return candidates, len(hits)


def get_target_store_stocks(site_key, config, sku, session, old_stocks=None):
    site = SITES[site_key]
    url = f"{config['api_url']}/clickcollect/availability/{sku}"
    headers = {
        **BROWSER_HEADERS,
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {config['api_token']}",
        "Origin": site["base"],
        "Referer": site["home"],
    }
    response = session.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("availability svarede ikke med en liste")

    stocks = {}
    for item in payload:
        store = item.get("store") or {}
        store_name = str(store.get("name") or "").strip()
        if not any(marker in store_name.lower() for marker in TARGET_STORE_MARKERS):
            continue
        site_id = str(store.get("sapSiteId") or "") or (
            "name:" + normalize_search_text(store_name)
        )
        stocks[site_id] = {
            "name": store_name or site_id,
            "stock": max(0, safe_int(item.get("currentStock"), 0)),
        }

    for site_id, old_store in (old_stocks or {}).items():
        if site_id not in stocks:
            stocks[site_id] = {
                "name": old_store.get("name") or site_id,
                "stock": 0,
            }
    return stocks


def zero_known_stocks(old_stocks):
    return {
        site_id: {
            "name": (store or {}).get("name") or site_id,
            "stock": 0,
        }
        for site_id, store in (old_stocks or {}).items()
    }


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"version": 1, "baseline_complete": False, "products": {}}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            state = json.load(file)
    except Exception:
        return {"version": 1, "baseline_complete": False, "products": {}}
    if not isinstance(state, dict):
        state = {}
    state.setdefault("version", 1)
    state.setdefault("baseline_complete", False)
    state.setdefault("products", {})
    if not isinstance(state["products"], dict):
        state["products"] = {}
    return state


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)


def format_price(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "Pris ukendt"
    return (
        f"{value:,.2f} kr."
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def short_series_name(value):
    value = str(value or "")
    for prefix in ("Mega Evolution: ", "Scarlet & Violet: "):
        if value.startswith(prefix):
            return value[len(prefix):]
    return value




def canonical_salling_product_key(product):
    """Stable identity shared across BR/Bilka/Foetex for discovery de-duplication."""
    sku = str((product or {}).get("sku") or "").strip().upper()
    if sku:
        return f"sku:{sku}"
    product_id = str((product or {}).get("id") or "").strip()
    return f"id:{product_id}" if product_id else ""


def send_discovery_alert(products):
    """Send one clearly separated PRE-PUBLISH discovery alert per Salling SKU."""
    # V46_UNIFIED_ABUNDANT_SET_POLICY
    products = [
        product for product in products
        if abundant_set_signal_allowed(
            product.get("name"),
            product.get("series"),
        )
    ]
    if not WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL mangler")
    if not products:
        return

    site_order = {"BR": 0, "BILKA": 1, "FØTEX": 2}
    products = sorted(
        products,
        key=lambda product: site_order.get(product.get("site"), 99),
    )
    representative = products[0]
    series = short_series_name(representative.get("series"))
    product_line = (
        f"**{series} · {representative['type']}**"
        if series
        else f"**{representative['name']} · {representative['type']}**"
    )

    lines = [
        "👀 **NY SKJULT VARE — ikke en lageralarm**",
        product_line,
    ]
    for product in products:
        store_count = max(0, safe_int(product.get("store_count"), 0))
        lines.append(
            f"• **{product['site']}** · {format_price(product.get('price'))} · "
            f"{store_count} butikker med registreret lager"
        )
    lines.append(f"🔎 SKU: `{representative['sku']}`")
    lines.append(
        "⏭️ Discovery sendes kun én gang. Næste signal kommer først ved "
        "lokal 0 → positiv lagerstatus."
    )

    payload = {
        "username": "MasterBot",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": "👀 [POKÉMON] SALLING PRE-PUBLISH DISCOVERY",
                "description": "\n".join(lines)[:4096],
                "color": 0x5865F2,
                "footer": {
                    "text": "MasterBot · Salling Discovery · NY SKJULT VARE"
                },
            }
        ],
    }
    response = requests.post(WEBHOOK_URL, json=payload, timeout=20)
    response.raise_for_status()

def send_local_alert(product, transitions):
    # V46_UNIFIED_ABUNDANT_SET_POLICY
    if not abundant_set_signal_allowed(
        product.get("name"),
        product.get("series"),
    ):
        return
    if not WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL mangler")

    visibility = product.get("visibility") or "UNKNOWN"
    pre_publish = visibility == "PRE-PUBLISH"
    title = (
        f"🔥 [POKÉMON] {product['site']} LOCAL STOCK [PRE-PUBLISH]"
        if pre_publish
        else f"🏪 [POKÉMON] {product['site']} LOCAL STOCK"
    )
    color = 0xF1C40F if pre_publish else 0x57F287
    series = short_series_name(product.get("series"))
    product_line = (
        f"**{series} · {product['type']}**"
        if series
        else f"**{product['name']} · {product['type']}**"
    )

    lines = [product_line]
    for transition in transitions:
        lines.append(
            f"🏪 {transition['name']}: {transition['old']} → "
            f"**{transition['new']} stk.**"
        )
    lines.append(f"💰 {format_price(product.get('price'))}")

    if pre_publish:
        lines.append(
            "🟡 Ikke eksponeret på webshoppen endnu — "
            "fysisk lager bør bekræftes i butikken."
        )
        lines.append(f"🔎 SKU: `{product['sku']}`")
    elif visibility == "UNKNOWN":
        lines.append("⚪ Webshop-eksponering kunne ikke klassificeres sikkert.")

    if product.get("url") and not pre_publish:
        lines.append(f"🔗 {product['url']}")

    payload = {
        "username": "MasterBot",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": title[:256],
                "description": "\n".join(lines)[:4096],
                "color": color,
                "footer": {
                    "text": (
                        "MasterBot · Local Stock Watch · "
                        "Kolding/Fredericia/Vejen/Brørup/Esbjerg"
                    )
                },
            }
        ],
    }
    response = requests.post(WEBHOOK_URL, json=payload, timeout=20)
    response.raise_for_status()


def scan_site(site_key, old_products):
    site = SITES[site_key]
    config = get_frontend_config(site_key)
    candidates, raw_hits = get_algolia_candidates(site_key, config)
    session = requests.Session()
    observations = {}
    errors = 0

    for product in candidates:
        key = f"{site_key}:{product['id']}"
        old_product = old_products.get(key) or {}
        old_stocks = old_product.get("stocks") or {}
        try:
            if product["visibility"] == "PRE-PUBLISH" or product["store_count"] > 0:
                stocks = get_target_store_stocks(
                    site_key,
                    config,
                    product["sku"],
                    session,
                    old_stocks=old_stocks,
                )
            else:
                stocks = zero_known_stocks(old_stocks)
        except Exception as error:
            errors += 1
            print(
                f"LOCAL STOCK {site['label']} availability-fejl for "
                f"{product['name']}: {error}"
            )
            continue

        observations[key] = {
            **product,
            "site": site["label"],
            "stocks": stocks,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }

    pre_publish_count = sum(
        1 for product in candidates if product["visibility"] == "PRE-PUBLISH"
    )
    positive_products = sum(
        1
        for product in observations.values()
        if any(
            safe_int(store.get("stock"), 0) > 0
            for store in (product.get("stocks") or {}).values()
        )
    )
    print(
        f"LOCAL STOCK {site['label']}: {raw_hits} Algolia hits | "
        f"{len(candidates)} relevante candidates | "
        f"{pre_publish_count} PRE-PUBLISH | "
        f"{positive_products} med lokal stock | "
        f"{errors} availability-fejl"
    )
    return observations, errors


def main():
    old_state = load_state()
    old_products = old_state.get("products") or {}
    baseline_complete = bool(old_state.get("baseline_complete"))
    next_products = dict(old_products)
    total_errors = 0
    fresh_keys = set()
    all_observations = {}
    stock_alerted_products = set()
    known_product_keys = {
        canonical_salling_product_key(product)
        for product in old_products.values()
        if canonical_salling_product_key(product)
    }
    site_baselines = {
        site_key: any(
            key.startswith(f"{site_key}:")
            for key in old_products
        )
        for site_key in ("br", "bilka", "foetex")
    }

    for site_key in ("br", "bilka", "foetex"):
        site_had_baseline = site_baselines[site_key]

        try:
            observations, errors = scan_site(site_key, old_products)
        except Exception as error:
            total_errors += 1
            print(f"LOCAL STOCK {site_key.upper()} KILDEFEJL: {error}")
            continue

        total_errors += errors
        next_products.update(observations)
        fresh_keys.update(observations.keys())
        all_observations.update(observations)

        # A newly added retailer gets one silent baseline even when the shared
        # state already has baseline_complete=True for older retailers. This
        # prevents a one-time storm of all existing BR stock when BR is enabled.
        if not baseline_complete or not site_had_baseline:
            if baseline_complete and observations:
                print(
                    f"LOCAL STOCK {SITES[site_key]['label']}: "
                    "ny kilde baseline oprettet uden alerts."
                )
            continue

        for key, product in observations.items():
            old_product = old_products.get(key) or {}
            old_stocks = old_product.get("stocks") or {}
            transitions = []

            for store_id, store in (product.get("stocks") or {}).items():
                new_stock = max(0, safe_int(store.get("stock"), 0))
                if new_stock <= 0:
                    continue
                old_stock = max(
                    0,
                    safe_int((old_stocks.get(store_id) or {}).get("stock"), 0),
                )
                if old_stock <= 0:
                    transitions.append(
                        {
                            "id": store_id,
                            "name": store.get("name") or store_id,
                            "old": old_stock,
                            "new": new_stock,
                        }
                    )

            if transitions:
                send_local_alert(product, transitions)
                canonical_key = canonical_salling_product_key(product)
                if canonical_key:
                    stock_alerted_products.add(canonical_key)

    # Discovery is deliberately separate from stock alerts:
    # - only genuinely new Salling identities are eligible;
    # - BR/Bilka/Foetex sightings of the same SKU collapse to one Discord post;
    # - if local stock already triggered, the weaker discovery alert is suppressed.
    discovery_groups = {}
    if baseline_complete:
        for observation_key, product in all_observations.items():
            if product.get("visibility") != "PRE-PUBLISH":
                continue
            canonical_key = canonical_salling_product_key(product)
            if (
                not canonical_key
                or canonical_key in known_product_keys
                or canonical_key in stock_alerted_products
            ):
                continue
            site_key = observation_key.split(":", 1)[0]
            if not site_baselines.get(site_key, False):
                continue
            discovery_groups.setdefault(canonical_key, []).append(product)

        for products in discovery_groups.values():
            send_discovery_alert(products)

    discovery_count = len(discovery_groups)

    next_state = {
        "version": 1,
        "baseline_complete": True,
        "products": next_products,
        "last_run": datetime.now(timezone.utc).isoformat(),
        "last_run_errors": total_errors,
    }
    save_state(next_state)

    if not baseline_complete:
        print(
            "LOCAL STOCK: baseline oprettet uden alerts. "
            "Fremtidige 0 -> positiv / nye positive fund alarmeres."
        )
    else:
        print(
            f"LOCAL STOCK: scan færdig | {len(fresh_keys)} "
            f"friske produktobservationer | {discovery_count} nye "
            f"PRE-PUBLISH discoveries | {total_errors} fejl"
        )


if __name__ == "__main__":
    main()
