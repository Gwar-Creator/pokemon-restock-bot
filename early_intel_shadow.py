#!/usr/bin/env python3
"""Shadow-only early retail intelligence audit.

Purpose: learn which public metadata moves before real Pokemon TCG launches/restocks.
No Discord output. The script persists richer snapshots for BR/Bilka/Foetex and
Proshop, keeps a bounded event history, and reports cross-Salling SKU movement.
"""

import json
import re
import time
from pathlib import Path
from urllib.parse import unquote, urlencode, urljoin, urlparse

import requests

ROOT = Path(__file__).resolve().parent
SHARED_FILE = ROOT / "restock_bot_github.py"
STATE_FILE = ROOT / "early_intel_shadow_state.json"
STATE_VERSION = 1
SALLING_SITES = ("br", "bilka", "foetex")
EVENT_MAX_AGE_SECONDS = 45 * 24 * 60 * 60
EVENT_MAX_COUNT = 1200

TRACKED_SALLING_FIELDS = (
    "sales_price",
    "is_exposed",
    "stock_count_online",
    "in_stock_stores_count",
    "f_campaign_name",
    "f_stock_availability",
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
    "quantity_restriction",
    "has_image",
    "image_primary",
    "epoch_updated_at",
)

EXPECTED_DATE_RE = re.compile(
    r"(?:forventet\s+p[åa]\s+lager|forventes\s+p[åa]\s+eget\s+lager)\s*"
    r"[:(]?\s*(\d{1,2}[-./]\d{1,2}[-./]\d{4})",
    re.I,
)

PROSHOP_RESEARCH_SURFACES = (
    ("pokemon-kort", None),
    ("pokemon-brand", "https://r.jina.ai/https://www.proshop.dk/Pokemon/Pokemon"),
)

PROSHOP_RESEARCH_BLOCK = (
    "portfolio",
    "samlemappe",
    "kortmappe",
    "binder",
    "sleeve",
    "deck box",
    "battle deck",
    "battledeck",
    "league battle deck",
    "world championships deck",
    "championships deck",
    "theme deck",
    "starter deck",
    "demo",
)

PROSHOP_RESEARCH_SIGNAL = (
    "booster box",
    "booster display",
    "booster bundle",
    "elite trainer box",
    "ultra premium collection",
    "ultra-premium collection",
    "super premium collection",
    "super-premium collection",
    "premium collection",
    "special collection",
    "illustration collection",
    "first partner",
    "collection box",
    "poké ball tin",
    "poke ball tin",
    "mini tin",
    " tin ",
    "30th",
    "anniversary",
)


def load_shared_namespace():
    source = SHARED_FILE.read_text(encoding="utf-8")
    marker = (
        "# =========================================================\n"
        "# START\n"
        "# ========================================================="
    )
    definitions = source.split(marker, 1)[0]
    namespace = {"__name__": "early_intel_shared", "__file__": str(SHARED_FILE)}
    exec(compile(definitions, str(SHARED_FILE), "exec"), namespace)
    return namespace


def normalize(value):
    if isinstance(value, list):
        return sorted(str(item) for item in value if item not in (None, ""))
    if isinstance(value, dict):
        return {str(k): normalize(v) for k, v in sorted(value.items())}
    return value


def load_state():
    if not STATE_FILE.exists():
        return None
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if state.get("version") != STATE_VERSION:
        return None
    return state


def compact_events(events, now_epoch=None):
    now_epoch = float(now_epoch or time.time())
    cutoff = now_epoch - EVENT_MAX_AGE_SECONDS
    compacted = [
        event
        for event in (events or [])
        if isinstance(event, dict) and float(event.get("ts") or 0) >= cutoff
    ]
    return compacted[-EVENT_MAX_COUNT:]


def save_state(snapshot):
    payload = {
        "version": STATE_VERSION,
        "updated_at": time.time(),
        **snapshot,
    }
    payload["events"] = compact_events(payload.get("events"))
    STATE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def salling_config(shared, site_key):
    if site_key == "br":
        config = shared["get_br_frontend_config"]()
        return {
            "base": shared["BR_BASE"],
            # BR uses a fixed public index constant; its frontend config only
            # carries the Algolia credentials.
            "index": shared["BR_ALGOLIA_INDEX"],
            "app_id": config["algolia_app_id"],
            "api_key": config["algolia_api_key"],
        }

    site = shared["SALLING_SITES"][site_key]
    config = shared["get_salling_frontend_config"](site_key)
    return {
        "base": site["base"],
        "index": config["algolia_index"],
        "app_id": config["algolia_app_id"],
        "api_key": config["algolia_api_key"],
    }


def fetch_salling_catalog(shared, site_key):
    config = salling_config(shared, site_key)
    url = f"https://{config['app_id'].lower()}-dsn.algolia.net/1/indexes/*/queries"
    params = {
        "query": "",
        "attributesToRetrieve": '["*"]',
        "filters": (
            'cfh_nodes:"CFH.CollectionCards" AND '
            '(f_brand:"Pokemon" OR f_brand:"Pokémon" OR facets.productSeriesToys:"Pokémon")'
        ),
        "hitsPerPage": 500,
        "page": 0,
        "getRankingInfo": "true",
    }
    response = requests.post(
        url,
        headers={
            **shared["BROWSER_HEADERS"],
            "Content-Type": "application/json",
            "x-algolia-application-id": config["app_id"],
            "x-algolia-api-key": config["api_key"],
        },
        json={"requests": [{"indexName": config["index"], "params": urlencode(params)}]},
        timeout=25,
    )
    response.raise_for_status()
    result = response.json().get("results", [{}])[0]
    hits = result.get("hits") or []

    products = {}
    for hit in hits:
        if not shared["is_real_pokemon_tcg"](hit):
            continue
        product_id = str(hit.get("id") or hit.get("objectID") or "").strip()
        if not product_id:
            continue
        name = str(hit.get("name") or "")
        # Research remains broader than Discord, but still excludes obvious
        # non-card/accessory noise through the shared TCG identification above.
        row = {
            "id": product_id,
            "sku": str(hit.get("sku") or hit.get("erp_product_id") or ""),
            "name": name,
            "url": urljoin(config["base"], hit.get("product_url") or ""),
        }
        for field in TRACKED_SALLING_FIELDS:
            row[field] = normalize(hit.get(field))
        row["stage"] = salling_stage(row)
        products[product_id] = row
    return products, int(result.get("nbHits") or len(hits))


def salling_stage(product):
    online = int(product.get("stock_count_online") or 0)
    stores = int(product.get("in_stock_stores_count") or 0)
    exposed = bool(product.get("is_exposed"))
    stock = online + stores

    if stock > 0 and not exposed:
        return "HIDDEN_STOCK"
    if stock > 0 and exposed:
        return "LIVE_STOCK"
    if exposed:
        return "EXPOSED_NO_STOCK"
    if any(
        product.get(field)
        for field in (
            "expected_available_from",
            "promotion_start_date",
            "not_reservable_from",
        )
    ):
        return "DATED_PREP"
    if (
        product.get("sales_price") not in (None, 0, 0.0)
        and product.get("has_image")
        and (
            product.get("sold_online")
            or product.get("sold_in_stores")
            or product.get("is_reservable")
        )
    ):
        return "PREPARED"
    return "CATALOG_RECORD"


def clean_proshop_name(label, product_url):
    """Use the URL slug to avoid Reader labels swallowing product descriptions."""
    try:
        parts = [part for part in urlparse(product_url).path.split("/") if part]
        if parts and parts[-1].isdigit() and len(parts) >= 2:
            slug = unquote(parts[-2]).replace("-", " ")
            slug = re.sub(r"\s+", " ", slug).strip()
            if "pokemon" in slug.lower():
                return slug
    except Exception:
        pass
    return re.sub(r"\s+", " ", label or "").strip()[:220]


def proshop_research_allowed(name):
    text = " " + re.sub(r"\s+", " ", str(name or "").lower()).strip() + " "
    if " pokemon " not in text or " tcg " not in text:
        return False
    if any(marker in text for marker in PROSHOP_RESEARCH_BLOCK):
        return False
    if re.search(r"\b(?:ex|v|vmax|vstar)\s+box\b", text):
        return True
    return any(marker in text for marker in PROSHOP_RESEARCH_SIGNAL)


def normalize_expected_date(value):
    if not value:
        return None
    return value.replace(".", "-").replace("/", "-")


def proshop_status(segment):
    low = segment.lower()
    if "bestilt: forventet på lager" in low:
        return "BESTILT_DATO"
    if "fjernlager" in low:
        return "FJERNLAGER"
    if "på lager" in low or "pa lager" in low:
        return "PÅ LAGER"
    if (
        "bestillingsvare" in low
        or "bestilt - ukendt leveringsdato" in low
        or "bestilt" in low
    ):
        return "BESTILLINGSVARE"
    return "UKENDT"


def proshop_stage(product):
    status = product.get("status")
    if status == "PÅ LAGER":
        return "LIVE_STOCK"
    if status == "FJERNLAGER":
        return "NEAR_STOCK"
    if product.get("expected_stock_date"):
        return "INBOUND_DATED"
    if status in ("BESTILT_DATO", "BESTILLINGSVARE"):
        return "INBOUND_UNDATED"
    if product.get("price") not in (None, 0, 0.0):
        return "PRICED_RECORD"
    return "CATALOG_RECORD"


def parse_proshop_reader(text, surface="pokemon-kort"):
    products = {}
    matches = list(
        re.finditer(
            r"\[([^\]]+)\]\((https://www\.proshop\.dk/[^)]+/(\d+))\)",
            text,
        )
    )
    for index, match in enumerate(matches):
        product_url = match.group(2)
        name = clean_proshop_name(match.group(1), product_url)
        if not proshop_research_allowed(name):
            continue

        end = matches[index + 1].start() if index + 1 < len(matches) else min(
            len(text), match.end() + 3000
        )
        segment = text[match.end():end]
        # Badges are rendered immediately BEFORE their product link. Reading
        # them from the following segment associates NYHED with the wrong item.
        previous_end = matches[index - 1].end() if index > 0 else max(0, match.start() - 300)
        prefix = text[previous_end:match.start()][-220:]

        expected = EXPECTED_DATE_RE.search(segment)
        price_match = re.search(
            r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*kr\.",
            segment,
        )
        price = None
        if price_match:
            try:
                price = float(price_match.group(1).replace(".", "").replace(",", "."))
            except ValueError:
                pass

        product_id = match.group(3)
        row = {
            "id": product_id,
            "name": name,
            "url": product_url,
            "status": proshop_status(segment),
            "expected_stock_date": normalize_expected_date(expected.group(1)) if expected else None,
            "price": price,
            "new_badge": bool(re.search(r"\bNYHED\b", prefix, flags=re.I)),
            "low_stock_badge": bool(re.search(r"FÅ PÅ LAGER|FA PÅ LAGER", prefix, flags=re.I)),
            "surfaces": [surface],
            "surface_statuses": {surface: proshop_status(segment)},
            "raw_status_excerpt": re.sub(r"\s+", " ", segment)[:500],
        }
        row["stage"] = proshop_stage(row)
        products[product_id] = row
    return products


def merge_proshop_products(target, incoming):
    status_rank = {
        "UKENDT": 0,
        "BESTILLINGSVARE": 1,
        "BESTILT_DATO": 2,
        "FJERNLAGER": 3,
        "PÅ LAGER": 4,
    }
    for product_id, row in incoming.items():
        current = target.get(product_id)
        if current is None:
            target[product_id] = dict(row)
            continue

        current["surfaces"] = sorted(set(current.get("surfaces") or []) | set(row.get("surfaces") or []))
        statuses = dict(current.get("surface_statuses") or {})
        statuses.update(row.get("surface_statuses") or {})
        current["surface_statuses"] = statuses
        current["new_badge"] = bool(current.get("new_badge") or row.get("new_badge"))
        current["low_stock_badge"] = bool(current.get("low_stock_badge") or row.get("low_stock_badge"))

        if current.get("price") is None and row.get("price") is not None:
            current["price"] = row["price"]
        if current.get("expected_stock_date") is None and row.get("expected_stock_date"):
            current["expected_stock_date"] = row["expected_stock_date"]
        if status_rank.get(row.get("status"), 0) > status_rank.get(current.get("status"), 0):
            current["status"] = row.get("status")
            current["raw_status_excerpt"] = row.get("raw_status_excerpt")
        current["stage"] = proshop_stage(current)


def fetch_proshop(shared):
    merged = {}
    failures = []
    for surface, explicit_url in PROSHOP_RESEARCH_SURFACES:
        reader_url = explicit_url or shared["PROSHOP_READER_URL"]
        try:
            response = requests.get(
                reader_url,
                headers={
                    "Accept": "text/plain, text/markdown;q=0.9, */*;q=0.5",
                    "User-Agent": "Pokemon-Lorcana-MasterBot/2.7 EarlyIntelShadow",
                    "x-no-cache": "true",
                    "x-engine": "browser",
                },
                timeout=40,
            )
            response.raise_for_status()
            parsed = parse_proshop_reader(response.text, surface=surface)
            merge_proshop_products(merged, parsed)
            print(f"EARLY INTEL PROSHOP surface={surface}: {len(parsed)} high-signal sealed")
        except Exception as error:
            failures.append(f"{surface}: {error}")

    if not merged:
        raise RuntimeError("; ".join(failures) or "ingen Proshop-data")
    if failures:
        print("EARLY INTEL PROSHOP delvis fejl: " + "; ".join(failures))
    return merged


def changed_fields(old, new, ignore=()):
    keys = sorted(set(old) | set(new))
    return [key for key in keys if key not in ignore and old.get(key) != new.get(key)]


def event_record(source, product_id, event_type, product, fields=None, before_stage=None):
    return {
        "ts": time.time(),
        "source": source,
        "product_id": str(product_id),
        "sku": str((product or {}).get("sku") or ""),
        "event": event_type,
        "fields": list(fields or []),
        "name": (product or {}).get("name") or "",
        "stage_before": before_stage,
        "stage_after": (product or {}).get("stage"),
    }


def report_source(source, old_products, new_products, baseline=False):
    old_products = old_products or {}
    new_ids = sorted(set(new_products) - set(old_products))
    removed_ids = sorted(set(old_products) - set(new_products))
    changes = []
    epoch_only = 0
    events = []
    is_salling = source in SALLING_SITES

    for product_id in sorted(set(new_products) & set(old_products)):
        ignored = {"raw_status_excerpt", "surfaces"}
        all_fields = changed_fields(old_products[product_id], new_products[product_id], ignore=ignored)
        meaningful = [field for field in all_fields if field != "epoch_updated_at"]
        if is_salling and all_fields == ["epoch_updated_at"]:
            epoch_only += 1
            continue
        if meaningful:
            changes.append((product_id, meaningful, new_products[product_id]))
            events.append(
                event_record(
                    source,
                    product_id,
                    "CHANGE",
                    new_products[product_id],
                    fields=meaningful,
                    before_stage=old_products[product_id].get("stage"),
                )
            )

    mode = "baseline" if baseline else "delta"
    print(
        f"EARLY INTEL SHADOW {source.upper()}: {len(new_products)} products | "
        f"mode={mode} | new={len(new_ids)} | removed={len(removed_ids)} | "
        f"changed={len(changes)} | epoch_only={epoch_only}"
    )

    if not baseline:
        for product_id in new_ids[:15]:
            product = new_products[product_id]
            print(
                f"EARLY INTEL NEW: {source} | {product_id} | "
                f"stage={product.get('stage')} | {product.get('name')}"
            )
            events.append(event_record(source, product_id, "NEW", product))
        for product_id in removed_ids[:15]:
            product = old_products[product_id]
            print(f"EARLY INTEL REMOVED: {source} | {product_id} | {product.get('name')}")
            events.append(event_record(source, product_id, "REMOVED", product))

    for product_id, fields, product in changes[:25]:
        print(
            f"EARLY INTEL CHANGE: {source} | {product_id} | "
            f"{','.join(fields)} | stage={product.get('stage')} | {product.get('name')}"
        )

    return events


def build_cross_salling(sources):
    cross = {}
    for source in SALLING_SITES:
        for product in (sources.get(source) or {}).values():
            sku = str(product.get("sku") or "").strip().upper()
            identity = sku or f"ID:{product.get('id')}"
            entry = cross.setdefault(
                identity,
                {"sku": sku, "name": product.get("name") or "", "sources": {}},
            )
            entry["sources"][source] = {
                "id": product.get("id"),
                "stage": product.get("stage"),
                "price": product.get("sales_price"),
                "is_exposed": bool(product.get("is_exposed")),
                "stock_online": int(product.get("stock_count_online") or 0),
                "stock_stores": int(product.get("in_stock_stores_count") or 0),
                "expected_available_from": product.get("expected_available_from"),
                "sold_online": bool(product.get("sold_online")),
                "sold_in_stores": bool(product.get("sold_in_stores")),
            }
    return cross


def report_cross_salling(old_cross, new_cross, suppress=False):
    if suppress or not old_cross:
        multi = sum(1 for value in new_cross.values() if len(value.get("sources") or {}) >= 2)
        print(
            f"EARLY INTEL CROSS-SALLING: baseline | {len(new_cross)} identities | "
            f"{multi} present in 2+ brands"
        )
        return []

    events = []
    changes = []
    for identity in sorted(set(old_cross) & set(new_cross)):
        old_sources = old_cross[identity].get("sources") or {}
        new_sources = new_cross[identity].get("sources") or {}
        if old_sources != new_sources:
            changes.append(identity)
            events.append(
                {
                    "ts": time.time(),
                    "source": "cross_salling",
                    "product_id": identity,
                    "sku": new_cross[identity].get("sku") or "",
                    "event": "CROSS_CHANGE",
                    "fields": changed_fields(old_sources, new_sources),
                    "name": new_cross[identity].get("name") or "",
                    "stage_before": None,
                    "stage_after": None,
                }
            )

    new_identities = sorted(set(new_cross) - set(old_cross))
    for identity in new_identities:
        entry = new_cross[identity]
        if len(entry.get("sources") or {}) < 2:
            continue
        events.append(
            {
                "ts": time.time(),
                "source": "cross_salling",
                "product_id": identity,
                "sku": entry.get("sku") or "",
                "event": "CROSS_NEW",
                "fields": ["sources"],
                "name": entry.get("name") or "",
                "stage_before": None,
                "stage_after": None,
            }
        )

    print(
        f"EARLY INTEL CROSS-SALLING: {len(new_cross)} identities | "
        f"changed={len(changes)} | new_multi={sum(1 for e in events if e['event'] == 'CROSS_NEW')}"
    )
    for identity in changes[:20]:
        entry = new_cross[identity]
        stages = ", ".join(
            f"{source}:{data.get('stage')}"
            for source, data in sorted((entry.get("sources") or {}).items())
        )
        print(f"EARLY INTEL CROSS CHANGE: {identity} | {stages} | {entry.get('name')}")
    return events


def main():
    shared = load_shared_namespace()
    previous = load_state() or {"sources": {}, "events": [], "cross_salling": {}}
    old_sources = previous.get("sources") or {}
    sources = {}
    events = compact_events(previous.get("events") or [])
    newly_baselined_sources = set()

    for site_key in SALLING_SITES:
        try:
            products, raw_count = fetch_salling_catalog(shared, site_key)
            sources[site_key] = products
            baseline = site_key not in old_sources
            if baseline:
                newly_baselined_sources.add(site_key)
            print(f"EARLY INTEL {site_key.upper()}: raw Pokemon hits={raw_count}")
            events.extend(report_source(site_key, old_sources.get(site_key), products, baseline=baseline))
        except Exception as error:
            print(f"EARLY INTEL {site_key.upper()} FEJL: {error}")
            if site_key in old_sources:
                sources[site_key] = old_sources[site_key]

    try:
        proshop = fetch_proshop(shared)
        sources["proshop"] = proshop
        baseline = "proshop" not in old_sources
        events.extend(report_source("proshop", old_sources.get("proshop"), proshop, baseline=baseline))
    except Exception as error:
        print(f"EARLY INTEL PROSHOP FEJL: {error}")
        if "proshop" in old_sources:
            sources["proshop"] = old_sources["proshop"]

    cross_salling = build_cross_salling(sources)
    events.extend(
        report_cross_salling(
            previous.get("cross_salling") or {},
            cross_salling,
            suppress=bool(newly_baselined_sources),
        )
    )

    save_state(
        {
            "sources": sources,
            "cross_salling": cross_salling,
            "events": events,
        }
    )
    print(
        f"EARLY INTEL SHADOW: snapshot saved; Discord=off; "
        f"event_history={len(compact_events(events))}"
    )


if __name__ == "__main__":
    main()
