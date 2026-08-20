import os
import re
import json
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup


WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )
}

SITES = {
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

# Første test-scope: de områder vi faktisk vil kunne køre efter.
TARGET_STORE_MARKERS = (
    "kolding",
    "fredericia",
    "vejen",
    "brørup",
    "brorup",
)

# Salling bruger ofte generiske produkttitler som "Pokemon TCG booster pack".
# Serien ligger dog ofte et andet sted i Algolia-recorden (beskrivelse, slug,
# kampagnetekst osv.). Vi søger derfor hele recorden efter kendte set-navne.
# Længste/mest specifikke aliases først for at undgå fejlmatch.
KNOWN_SET_ALIASES = (
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

# Kendte Salling-varenumre hvor den offentlige titel er generisk, men den
# offentlige produktside entydigt dokumenterer serien.
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
    text = str(value or "").lower()
    text = text.replace("pokémon", "pokemon")
    text = text.replace("–", " ").replace("—", " ")
    text = re.sub(r"[^a-z0-9æøå:]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def infer_series(product):
    """Best-effort set identification from the complete Salling record."""
    raw_text = json.dumps(product, ensure_ascii=False, sort_keys=True)
    normalized = normalize_search_text(raw_text)

    # Exact product/ERP IDs win over fuzzy text.
    for marker, series_name in KNOWN_PRODUCT_SERIES.items():
        if normalize_search_text(marker) in normalized:
            return series_name, "product-id"

    for series_name, aliases in KNOWN_SET_ALIASES:
        for alias in aliases:
            if normalize_search_text(alias) in normalized:
                return series_name, "metadata"

    return None, None


def extract_config_value(text, key):
    pattern = re.escape(key) + r'["\']?\s*:\s*["\']([^"\']+)["\']'
    match = re.search(pattern, text)
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
                and "NUXT_ENV_ALGOLIA_DEFAULT_INDEX" in script_response.text
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
    config = {key: None for key in keys}

    for text in texts:
        for out_key, source_key in keys.items():
            if not config[out_key]:
                config[out_key] = extract_config_value(text, source_key)
        if not config["algolia_app_id"]:
            config["algolia_app_id"] = extract_config_value(
                text, "NUXT_ENV_ALGOLIA_APPLICATION_ID"
            )

    missing = [key for key, value in config.items() if not value]
    if missing:
        raise RuntimeError(
            f"{site['label']} mangler frontend-config: {', '.join(missing)}"
        )

    return config


def pokemon_product_type(name):
    text = " " + re.sub(r"\s+", " ", str(name or "").lower()) + " "

    blocked = (
        "checklane",
        "check lane",
        "battle deck",
        "battledeck",
        "blister",
        "portfolio",
        "binder",
        "mappe",
        "sleeve",
        "playmat",
        "deck box",
        "penalhus",
        "pencil case",
    )
    if any(marker in text for marker in blocked):
        return None

    if "elite trainer box" in text or re.search(r"\betb\b", text):
        return "ETB"

    if (
        "mini tin" in text
        or "poké ball tin" in text
        or "poke ball tin" in text
        or re.search(r"\btins?\b", text)
    ):
        return "TIN"

    if "booster" in text:
        if any(
            marker in text
            for marker in (
                "booster box",
                "booster display",
                "booster bundle",
                "bundle display",
            )
        ):
            return None
        return "BOOSTER PACK"

    return None


def is_pokemon_hit(product):
    name = str(product.get("name") or "")
    brand = str(product.get("brand") or product.get("f_brand") or "")
    series = str(product.get("facets.productSeriesToys") or "")
    text = f"{name} {brand} {series}".lower()
    return "pokemon" in text or "pokémon" in text


def get_algolia_candidates(site_key, config):
    # Vigtigt: ingen is_exposed:true her. Det er selve testen af PRE-PUBLISH.
    algolia_url = (
        "https://"
        f"{config['algolia_app_id'].lower()}"
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

        product_type = pokemon_product_type(product.get("name"))
        if not product_type:
            continue

        sku = product.get("sku") or product.get("erp_product_id")
        if not sku:
            continue

        product_url = product.get("product_url") or ""
        exposed_raw = product.get("is_exposed")
        exposed = exposed_raw is True or str(exposed_raw).lower() == "true"
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
                "pre_publish": not exposed,
                "url": urljoin(SITES[site_key]["base"], product_url)
                if product_url
                else "",
            }
        )

    return candidates, len(hits)


def get_target_store_stock(site_key, config, sku, session):
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

    stores = []
    for item in response.json():
        store = item.get("store") or {}
        store_name = str(store.get("name") or "").strip()
        normalized_name = store_name.lower()
        if not any(marker in normalized_name for marker in TARGET_STORE_MARKERS):
            continue

        stock = max(0, safe_int(item.get("currentStock"), 0))
        if stock <= 0:
            continue

        stores.append(
            {
                "name": store_name or str(store.get("sapSiteId") or "Ukendt butik"),
                "stock": stock,
                "site_id": str(store.get("sapSiteId") or ""),
            }
        )

    return stores


def scan_site(site_key):
    config = get_frontend_config(site_key)
    candidates, raw_hits = get_algolia_candidates(site_key, config)
    session = requests.Session()
    stocked = []
    errors = 0

    for product in candidates:
        try:
            stores = get_target_store_stock(
                site_key,
                config,
                product["sku"],
                session,
            )
        except Exception as error:
            errors += 1
            print(
                f"{SITES[site_key]['label']} availability-fejl "
                f"for {product['name']}: {error}"
            )
            continue

        if not stores:
            continue

        row = dict(product)
        row["stores"] = stores
        row["site"] = SITES[site_key]["label"]
        stocked.append(row)

    hidden_candidates = sum(1 for product in candidates if product["pre_publish"])
    identified_stocked = sum(1 for product in stocked if product.get("series"))
    print(
        f"LOCAL STOCK TEST {SITES[site_key]['label']}: "
        f"{raw_hits} Algolia hits | {len(candidates)} V1 candidates | "
        f"{hidden_candidates} pre-publish candidates | "
        f"{len(stocked)} lokale fund | {identified_stocked} med serie | "
        f"{errors} availability-fejl"
    )
    return stocked, len(candidates), hidden_candidates, errors


def format_price(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "pris ukendt"
    return f"{value:,.2f} kr.".replace(",", "X").replace(".", ",").replace("X", ".")


def short_series_name(value):
    value = str(value or "Serie ukendt")
    for prefix in ("Mega Evolution: ", "Scarlet & Violet: "):
        if value.startswith(prefix):
            return value[len(prefix):]
    return value


def send_test_report(all_stocked, stats):
    if not WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL mangler")

    all_stocked.sort(
        key=lambda row: (
            not row["pre_publish"],
            row.get("series") or "zzzz",
            row["type"],
            row["site"],
            row["name"],
        )
    )

    total_candidates = sum(row["candidates"] for row in stats.values())
    total_hidden = sum(row["hidden"] for row in stats.values())
    total_errors = sum(row["errors"] for row in stats.values())
    identified_stocked = sum(1 for row in all_stocked if row.get("series"))

    lines = [
        "**Isoleret test — ændrer ikke den normale restock-bot.**",
        "Scope: Booster packs · ETB · Tins",
        "Område: Kolding · Fredericia · Vejen · Brørup",
        "",
        f"🔎 V1-kandidater: **{total_candidates}**",
        f"🟡 PRE-PUBLISH kandidater: **{total_hidden}**",
        f"📦 Produkter med lokal stock nu: **{len(all_stocked)}**",
        f"🏷️ Lokale fund med identificeret serie: **{identified_stocked}/{len(all_stocked)}**",
        f"⚠️ Availability-fejl: **{total_errors}**",
    ]

    if all_stocked:
        lines.append("")
        lines.append("**Fund lige nu:**")

        for row in all_stocked[:12]:
            status = "🔥 PRE-PUBLISH" if row["pre_publish"] else "📍 LIVE"
            series = short_series_name(row.get("series"))
            series_icon = "🏷️" if row.get("series") else "❓"
            lines.append(
                f"\n{status} · **{row['site']} · {series.upper()} · {row['type']}**\n"
                f"{series_icon} Serie: **{series}**\n"
                f"{row['name']} · {format_price(row['price'])}"
            )
            if not row.get("series"):
                lines.append(f"🔎 SKU: `{row['sku']}`")
            for store in row["stores"]:
                lines.append(f"🏪 {store['name']}: **{store['stock']} stk.**")
    else:
        lines.extend(
            [
                "",
                "Ingen positive lokale lagerfund i dette scan.",
                "Det er stadig et gyldigt testresultat; workflow-loggen viser om skjulte varer blev fundet.",
            ]
        )

    description = "\n".join(lines)[:4090]
    payload = {
        "username": "MasterBot",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": "🧪 LOCAL STOCK V1 — SERIETEST",
                "description": description,
                "color": 0xF1C40F,
                "footer": {"text": "MasterBot · Local Stock V1 · serietest"},
            }
        ],
    }

    response = requests.post(WEBHOOK_URL, json=payload, timeout=20)
    response.raise_for_status()


if __name__ == "__main__":
    all_stocked = []
    stats = {}

    for site_key in ("bilka", "foetex"):
        try:
            stocked, candidates, hidden, errors = scan_site(site_key)
            all_stocked.extend(stocked)
            stats[site_key] = {
                "candidates": candidates,
                "hidden": hidden,
                "errors": errors,
            }
        except Exception as error:
            print(f"LOCAL STOCK TEST {site_key.upper()} FEJL: {error}")
            stats[site_key] = {"candidates": 0, "hidden": 0, "errors": 1}

    send_test_report(all_stocked, stats)
