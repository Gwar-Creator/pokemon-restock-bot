import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent
SHARED_FILE = ROOT / "restock_bot_github.py"
STATE_FILE = ROOT / "salling_early_radar_state.json"
STATE_VERSION = 3
SITES = ("bilka", "foetex")
LOCAL_TZ = ZoneInfo("Europe/Copenhagen")
MAX_POKEMON_CATALOG_HITS = 250
MIN_POKEMON_CATALOG_HITS = 50

# High-signal sealed products. Single loose boosters and battle/accessory noise
# are deliberately excluded; the shared restock relevance filter is applied too.
CORE_MARKERS = (
    "booster bundle",
    "booster box",
    "booster display",
    "elite trainer box",
    " etb ",
    "premium collection",
    "premium box",
    "ultra-premium",
    "ultra premium",
    " upc ",
    "special collection",
    "illustration collection",
    "illustration rare collection",
    "illust rare collection",
    "binder collection",
    "poster collection",
    "first partner",
    "collection box",
    " ex box",
    "ex box",
    " tin ",
)

WATCH_MARKERS = (
    "victini",
    "first partner",
    "30th",
    "30th anniversary",
    "30 year",
    "30 år",
    "anniversary",
    "ascended heroes",
    "black bolt",
    "white flare",
)

PACK_MARKERS = (
    "booster pack",
    "sleeved booster",
    "sleeve booster",
)

# Existing hidden products can sit in Salling for years. These are the fields
# that indicate real preparation/re-activation when they change.
MOVEMENT_FIELDS = (
    "price",
    "campaign",
    "stock_availability",
    "expected_available_from",
    "online_from",
    "online_to",
    "promotion_start_date",
    "promotion_end_date",
    "not_reservable_from",
    "not_reservable_to",
    "is_click_and_collectible",
    "is_reservable",
    "sold_online",
    "sold_in_stores",
    "release_date",
    "quantity_restriction",
    "has_image",
    "image_primary",
    "description_hash",
)

FIELD_LABELS = {
    "price": "pris",
    "campaign": "campaign",
    "stock_availability": "lagerstatus",
    "expected_available_from": "forventet fra",
    "online_from": "online fra",
    "online_to": "online til",
    "promotion_start_date": "kampagne fra",
    "promotion_end_date": "kampagne til",
    "not_reservable_from": "ikke reserverbar fra",
    "not_reservable_to": "ikke reserverbar til",
    "is_click_and_collectible": "Click & Collect",
    "is_reservable": "reserverbar",
    "sold_online": "sælges online",
    "sold_in_stores": "sælges i butik",
    "release_date": "release",
    "quantity_restriction": "købsgrænse",
    "has_image": "billede",
    "image_primary": "produktbillede",
    "description_hash": "beskrivelse",
}


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
        "__name__": "salling_early_radar_shared",
        "__file__": str(SHARED_FILE),
    }
    exec(compile(source.split(marker, 1)[0], str(SHARED_FILE), "exec"), namespace)
    return namespace


def load_state():
    if not STATE_FILE.exists():
        return None
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("version") != STATE_VERSION:
        return None
    if not isinstance(value.get("products"), dict):
        return None
    return value


def save_state(products):
    payload = {
        "version": STATE_VERSION,
        "updated_at": time.time(),
        "products": products,
    }
    STATE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def clean_name(name):
    return " " + re.sub(r"\s+", " ", str(name or "").lower()).strip() + " "


def early_product_allowed(shared, hit):
    product = {
        "name": hit.get("name") or "",
        "game": "POKÉMON",
    }
    if not shared["restock_alert_allowed"](product, "POKÉMON"):
        return False

    text = clean_name(product["name"])
    if any(marker in text for marker in PACK_MARKERS):
        return False

    # A title that is merely a loose "booster" should not enter Early Radar.
    if (
        " booster " in text
        and "booster bundle" not in text
        and "booster box" not in text
        and "booster display" not in text
        and "elite trainer box" not in text
        and not re.search(r"\betb\b", text)
    ):
        return False

    if any(marker in text for marker in WATCH_MARKERS):
        return True
    return any(marker in text for marker in CORE_MARKERS)


def priority_for(name):
    text = clean_name(name)
    if any(marker in text for marker in WATCH_MARKERS):
        return "WATCH"
    if any(
        marker in text
        for marker in (
            "booster bundle",
            "booster box",
            "booster display",
            "elite trainer box",
            " etb ",
            "ultra-premium",
            "ultra premium",
            " upc ",
            "illustration collection",
            "illustration rare collection",
            "illust rare collection",
            "first partner",
        )
    ):
        return "HIGH"
    return "NORMAL"


def release_date_from_hit(hit):
    for facet in hit.get("facets") or []:
        if not isinstance(facet, dict):
            continue
        value = facet.get("releaseDate")
        if isinstance(value, list) and value:
            return value[0]
        if value:
            return value
    return None


def normalized_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return sorted(str(item) for item in value if item not in (None, ""))
    return [str(value)]


def description_snapshot(hit):
    description = re.sub(r"<[^>]+>", " ", str(hit.get("description") or ""))
    description = re.sub(r"\s+", " ", description).strip()
    digest = hashlib.sha1(description.encode("utf-8")).hexdigest() if description else None
    return digest, description[:180]


def fetch_hidden_catalog(shared, site_key):
    site = shared["SALLING_SITES"][site_key]
    config = shared["get_salling_frontend_config"](site_key)
    algolia_url = (
        "https://"
        f"{config['algolia_app_id'].lower()}"
        "-dsn.algolia.net/1/indexes/*/queries"
    )

    # IMPORTANT: filter inside Algolia before limiting hits. The old version
    # requested the first 250 products from the entire Salling index and only
    # filtered Pokemon afterwards. That made old products disappear/reappear
    # as ranking changed and caused false "NY SKJULT VARE" alerts.
    params = {
        "query": "",
        "attributesToRetrieve": '["*"]',
        "filters": (
            'cfh_nodes:"CFH.CollectionCards" AND '
            '(f_brand:"Pokemon" OR f_brand:"Pokémon" OR '
            'facets.productSeriesToys:"Pokémon")'
        ),
        "hitsPerPage": MAX_POKEMON_CATALOG_HITS,
        "page": 0,
        "getRankingInfo": "true",
    }
    payload = {
        "requests": [
            {
                "indexName": config["algolia_index"],
                "params": urlencode(params),
            }
        ],
        "strategy": "none",
    }

    response = requests.post(
        algolia_url,
        headers={
            **shared["BROWSER_HEADERS"],
            "Content-Type": "application/json",
            "x-algolia-application-id": config["algolia_app_id"],
            "x-algolia-api-key": config["algolia_api_key"],
        },
        json=payload,
        timeout=25,
    )
    response.raise_for_status()

    result = response.json().get("results", [{}])[0]
    all_hits = result.get("hits", [])
    total_hits = shared["safe_int"](result.get("nbHits"), len(all_hits))

    if total_hits > MAX_POKEMON_CATALOG_HITS:
        raise RuntimeError(
            f"Pokemon-kataloget har {total_hits} hits; paging skal implementeres før state gemmes"
        )
    if total_hits < MIN_POKEMON_CATALOG_HITS:
        raise RuntimeError(
            f"Pokemon-kataloget gav kun {total_hits} hits; afviser mulig ufuldstændig snapshot"
        )

    products = {}

    for hit in all_hits:
        if not shared["is_real_pokemon_tcg"](hit):
            continue
        if not early_product_allowed(shared, hit):
            continue

        product_id = str(hit.get("id") or hit.get("objectID") or "").strip()
        if not product_id:
            continue

        description_hash, description_excerpt = description_snapshot(hit)
        product_url = hit.get("product_url")
        products[product_id] = {
            "id": product_id,
            "sku": str(hit.get("sku") or hit.get("erp_product_id") or ""),
            "name": hit.get("name") or "Ukendt Pokemon-produkt",
            "price": hit.get("sales_price"),
            "is_exposed": bool(hit.get("is_exposed")),
            "online_count": max(0, shared["safe_int"](hit.get("stock_count_online"), 0)),
            "store_count": max(0, shared["safe_int"](hit.get("in_stock_stores_count"), 0)),
            "priority": priority_for(hit.get("name")),
            "url": urljoin(site["base"], product_url) if product_url else site["home"],
            "site": site_key,
            "epoch_updated_at": shared["safe_int"](hit.get("epoch_updated_at"), 0),
            "campaign": normalized_list(hit.get("f_campaign_name")),
            "stock_availability": normalized_list(hit.get("f_stock_availability")),
            "expected_available_from": hit.get("expected_available_from"),
            "online_from": hit.get("online_from"),
            "online_to": hit.get("online_to"),
            "promotion_start_date": hit.get("promotion_start_date"),
            "promotion_end_date": hit.get("promotion_end_date"),
            "not_reservable_from": hit.get("not_reservable_from"),
            "not_reservable_to": hit.get("not_reservable_to"),
            "is_click_and_collectible": bool(hit.get("is_click_and_collectible")),
            "is_reservable": bool(hit.get("is_reservable")),
            "sold_online": bool(hit.get("sold_online")),
            "sold_in_stores": bool(hit.get("sold_in_stores")),
            "release_date": release_date_from_hit(hit),
            "quantity_restriction": hit.get("quantity_restriction"),
            "has_image": bool(hit.get("has_image")),
            "image_primary": hit.get("image_primary"),
            "description_hash": description_hash,
            "description_excerpt": description_excerpt,
        }

    return products, total_hits


def merge_catalogs(site_catalogs):
    merged = {}
    for site_key, products in site_catalogs.items():
        for product_id, product in products.items():
            entry = merged.setdefault(
                product_id,
                {
                    "id": product_id,
                    "sku": product.get("sku") or "",
                    "name": product.get("name") or "Ukendt Pokemon-produkt",
                    "price": product.get("price"),
                    "priority": product.get("priority") or "NORMAL",
                    "sites": {},
                },
            )
            if not entry.get("sku") and product.get("sku"):
                entry["sku"] = product["sku"]
            if entry.get("price") is None and product.get("price") is not None:
                entry["price"] = product["price"]
            if product.get("priority") == "WATCH":
                entry["priority"] = "WATCH"
            elif product.get("priority") == "HIGH" and entry.get("priority") != "WATCH":
                entry["priority"] = "HIGH"

            entry["sites"][site_key] = {
                "price": product.get("price"),
                "is_exposed": product.get("is_exposed", False),
                "online_count": product.get("online_count", 0),
                "store_count": product.get("store_count", 0),
                "url": product.get("url") or "",
                "epoch_updated_at": product.get("epoch_updated_at", 0),
                "campaign": product.get("campaign") or [],
                "stock_availability": product.get("stock_availability") or [],
                "expected_available_from": product.get("expected_available_from"),
                "online_from": product.get("online_from"),
                "online_to": product.get("online_to"),
                "promotion_start_date": product.get("promotion_start_date"),
                "promotion_end_date": product.get("promotion_end_date"),
                "not_reservable_from": product.get("not_reservable_from"),
                "not_reservable_to": product.get("not_reservable_to"),
                "is_click_and_collectible": product.get("is_click_and_collectible", False),
                "is_reservable": product.get("is_reservable", False),
                "sold_online": product.get("sold_online", False),
                "sold_in_stores": product.get("sold_in_stores", False),
                "release_date": product.get("release_date"),
                "quantity_restriction": product.get("quantity_restriction"),
                "has_image": product.get("has_image", False),
                "image_primary": product.get("image_primary"),
                "description_hash": product.get("description_hash"),
                "description_excerpt": product.get("description_excerpt"),
            }

    return merged


def hidden_somewhere(product):
    return any(not site.get("is_exposed") for site in (product.get("sites") or {}).values())


def live_signal(product):
    for site in (product.get("sites") or {}).values():
        if site.get("is_exposed"):
            return True
        if int(site.get("online_count") or 0) > 0:
            return True
        if int(site.get("store_count") or 0) > 0:
            return True
    return False


def stock_signal_text(product):
    bits = []
    for site_key, site in sorted((product.get("sites") or {}).items()):
        online = int(site.get("online_count") or 0)
        stores = int(site.get("store_count") or 0)
        exposed = bool(site.get("is_exposed"))
        flags = []
        if exposed:
            flags.append("synlig")
        if online > 0:
            flags.append(f"online {online}")
        if stores > 0:
            flags.append(f"{stores} butikker")
        if flags:
            bits.append(f"{site_key.upper()}: " + ", ".join(flags))
    return " · ".join(bits) if bits else "stadig skjult uden lager"


def best_url(product):
    sites = product.get("sites") or {}
    for key in ("bilka", "foetex"):
        url = (sites.get(key) or {}).get("url")
        if url:
            return url
    return ""


def latest_record_update(product):
    values = [
        int(site.get("epoch_updated_at") or 0)
        for site in (product.get("sites") or {}).values()
    ]
    value = max(values or [0])
    if value <= 0:
        return None
    return value


def record_update_text(product):
    value = latest_record_update(product)
    if not value:
        return None
    dt = datetime.fromtimestamp(value, tz=timezone.utc).astimezone(LOCAL_TZ)
    return dt.strftime("%d/%m %H:%M")


def display_value(field, value):
    if field in ("description_hash", "image_primary"):
        return "ændret"
    if value is None or value == "" or value == []:
        return "-"
    if isinstance(value, bool):
        return "ja" if value else "nej"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "-"
    return str(value)


def site_movement_changes(old, current):
    changes = []
    old_sites = old.get("sites") or {}
    current_sites = current.get("sites") or {}

    for site_key, site in current_sites.items():
        old_site = old_sites.get(site_key) or {}
        for field in MOVEMENT_FIELDS:
            before = old_site.get(field)
            after = site.get(field)
            if before == after:
                continue

            label = FIELD_LABELS.get(field, field)
            if field == "description_hash":
                text = f"{site_key.upper()} beskrivelse ændret"
            elif field == "image_primary":
                text = f"{site_key.upper()} produktbillede ændret"
            elif field == "has_image" and not before and after:
                text = f"{site_key.upper()} billede tilføjet"
            else:
                text = (
                    f"{site_key.upper()} {label}: "
                    f"{display_value(field, before)} → {display_value(field, after)}"
                )
            changes.append(text)

    if old.get("name") != current.get("name"):
        changes.insert(0, f"navn: {old.get('name') or '-'} → {current.get('name') or '-'}")
    if old.get("sku") != current.get("sku"):
        changes.insert(0, f"SKU: {old.get('sku') or '-'} → {current.get('sku') or '-'}")

    return changes


def epoch_only_change(old, current):
    if site_movement_changes(old, current):
        return False
    if became_hidden_stocked(old, current) or became_live(old, current):
        return False

    old_sites = old.get("sites") or {}
    for site_key, site in (current.get("sites") or {}).items():
        old_epoch = int((old_sites.get(site_key) or {}).get("epoch_updated_at") or 0)
        new_epoch = int(site.get("epoch_updated_at") or 0)
        if new_epoch > old_epoch:
            return True
    return False


def recent_record_update(product, max_age_seconds=1800):
    value = latest_record_update(product)
    if not value:
        return False
    return 0 <= time.time() - value <= max_age_seconds


def send_alert(title, product, detail):
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        raise RuntimeError("DISCORD_WEBHOOK_URL mangler")

    price = product.get("price")
    price_text = f"{price} kr." if price is not None else "Pris ikke oplyst"
    updated = record_update_text(product)
    updated_line = f"\n🕒 Salling-record opdateret {updated}" if updated else ""
    message = (
        f"🕵️ **SALLING EARLY RADAR · {title}**\n"
        f"**{product.get('name') or 'Ukendt Pokemon-produkt'}**\n"
        f"🎯 {product.get('priority') or 'NORMAL'} · {detail}\n"
        f"💰 {price_text}\n"
        f"🆔 {product.get('id')} · SKU {product.get('sku') or '-'}\n"
        f"📦 {stock_signal_text(product)}"
        f"{updated_line}\n"
        f"🔗 {best_url(product)}"
    )

    response = requests.post(webhook, json={"content": message}, timeout=15)
    response.raise_for_status()


def became_live(old, current):
    return not live_signal(old) and live_signal(current)


def became_hidden_stocked(old, current):
    if not hidden_somewhere(current):
        return False

    def total_stock_signal(product):
        return sum(
            int(site.get("online_count") or 0) + int(site.get("store_count") or 0)
            for site in (product.get("sites") or {}).values()
        )

    return total_stock_signal(old) <= 0 < total_stock_signal(current)


def main():
    if not os.getenv("DISCORD_WEBHOOK_URL"):
        raise RuntimeError("DISCORD_WEBHOOK_URL mangler")

    shared = load_shared_namespace()
    site_catalogs = {}

    for site_key in SITES:
        try:
            products, raw_count = fetch_hidden_catalog(shared, site_key)
        except Exception as error:
            print(f"EARLY RADAR {site_key.upper()} FEJL: {error}")
            continue
        site_catalogs[site_key] = products
        hidden_count = sum(not product.get("is_exposed") for product in products.values())
        print(
            f"EARLY RADAR {site_key.upper()}: {raw_count} Pokémon-katalog hits · "
            f"{len(products)} relevante · {hidden_count} skjulte"
        )

    # Never write a partial baseline. If one Salling site is temporarily down,
    # keeping the previous complete state prevents every recovered product from
    # being misclassified as new on the next run.
    if len(site_catalogs) != len(SITES):
        missing = sorted(set(SITES) - set(site_catalogs))
        raise RuntimeError(
            "Ufuldstændig Early Radar snapshot; state bevares. Mangler: "
            + ", ".join(missing)
        )

    current = merge_catalogs(site_catalogs)
    previous_state = load_state()

    # Version 3 starts with a quiet baseline because v2 was built from an
    # unstable top-250 whole-catalogue query. No old v2 product may be treated
    # as a trustworthy "seen" baseline.
    if previous_state is None:
        save_state(current)
        print(
            f"EARLY RADAR v{STATE_VERSION} stabil baseline: "
            f"{len(current)} relevante produkt-ID'er, ingen alerts"
        )
        return

    previous = previous_state.get("products") or {}

    # If Salling bulk-reindexes many records at once, epoch_updated_at can move
    # without meaning anything commercially. Suppress timestamp-only noise in
    # that case, but keep real field/stock/exposure changes.
    epoch_candidates = []
    for product_id, product in current.items():
        old = previous.get(product_id)
        if not isinstance(old, dict):
            continue
        if not hidden_somewhere(product):
            continue
        if product.get("priority") not in ("WATCH", "HIGH"):
            continue
        if epoch_only_change(old, product) and recent_record_update(product):
            epoch_candidates.append(product_id)

    suppress_epoch_only = len(epoch_candidates) > 3
    if suppress_epoch_only:
        print(
            f"EARLY RADAR: undertrykker {len(epoch_candidates)} epoch-only ændringer "
            "som sandsynlig Salling batch-reindex"
        )

    for product_id, product in current.items():
        old = previous.get(product_id)

        # The main edge: a brand-new relevant product appears in the filtered
        # Pokemon catalogue before Salling exposes it on the storefront.
        if old is None:
            if hidden_somewhere(product):
                send_alert("NY SKJULT VARE", product, "nyt produkt-ID fundet før offentlig visning")
            else:
                send_alert("NY VARE", product, "nyt produkt-ID fundet")
            continue

        # Strongest signals first.
        if became_hidden_stocked(old, product):
            send_alert("LAGER FØR LIVE", product, "skjult vare har fået lager-signal")
            continue
        if became_live(old, product):
            send_alert("GÅR LIVE", product, "vare har fået første live-signal")
            continue

        changes = site_movement_changes(old, product)
        if changes:
            detail = " · ".join(changes[:4])
            if len(changes) > 4:
                detail += f" · +{len(changes) - 4} ændringer"
            send_alert("EARLY MOVEMENT", product, detail)
            continue

        if (
            not suppress_epoch_only
            and product_id in epoch_candidates
            and product.get("priority") in ("WATCH", "HIGH")
        ):
            send_alert(
                "RECORD OPDATERET",
                product,
                "skjult high-signal vare blev netop opdateret uden synlig feltændring",
            )

    save_state(current)
    print(f"EARLY RADAR færdig: {len(current)} relevante produkt-ID'er")


if __name__ == "__main__":
    main()
