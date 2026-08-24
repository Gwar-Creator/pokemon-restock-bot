import json
import os
import re
from pathlib import Path
from urllib.parse import urlencode

import requests

ROOT = Path(__file__).resolve().parent
SHARED_FILE = ROOT / "restock_bot_github.py"
TARGET_PRODUCT_ID = "200329839"

SEARCH_TERMS = (
    "victini",
    "black bolt",
    "white flare",
    "illustration collection",
)

WATCH_MARKERS = SEARCH_TERMS + (
    "unova",
    "collection",
)

METADATA_MARKERS = (
    "date",
    "time",
    "start",
    "end",
    "from",
    "until",
    "campaign",
    "publish",
    "release",
    "avail",
    "stock",
    "expos",
    "active",
    "create",
    "update",
    "valid",
    "launch",
)

SITES = ("bilka", "foetex")


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
        "__name__": "salling_prerelease_probe_shared",
        "__file__": str(SHARED_FILE),
    }
    exec(compile(source.split(marker, 1)[0], str(SHARED_FILE), "exec"), namespace)
    return namespace


def compact_hit(site_key, term, hit):
    return {
        "site": site_key,
        "term": term,
        "id": str(hit.get("id") or hit.get("objectID") or ""),
        "name": hit.get("name"),
        "price": hit.get("sales_price"),
        "is_exposed": hit.get("is_exposed"),
        "online_stock": hit.get("stock_count_online"),
        "stores": hit.get("in_stock_stores_count"),
        "sku": hit.get("sku") or hit.get("erp_product_id"),
        "product_url": hit.get("product_url"),
    }


def algolia_query(shared, site_key, params):
    config = shared["get_salling_frontend_config"](site_key)
    algolia_url = (
        "https://"
        f"{config['algolia_app_id'].lower()}"
        "-dsn.algolia.net/1/indexes/*/queries"
    )
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
        timeout=20,
    )
    response.raise_for_status()
    return response.json().get("results", [{}])[0].get("hits", [])


def run_query(shared, site_key, term):
    hits = algolia_query(
        shared,
        site_key,
        {
            "query": term,
            "attributesToRetrieve": '["*"]',
            "hitsPerPage": 100,
            "page": 0,
            "getRankingInfo": "true",
        },
    )

    relevant = []
    for hit in hits:
        name = str(hit.get("name") or "")
        normalized = re.sub(r"\s+", " ", name.lower()).strip()
        if any(marker in normalized for marker in SEARCH_TERMS):
            relevant.append(compact_hit(site_key, term, hit))

    return relevant, len(hits)


def fetch_hidden_pokemon_hits(shared, site_key):
    hits = algolia_query(
        shared,
        site_key,
        {
            "query": "",
            "attributesToRetrieve": '["*"]',
            "filters": (
                'cfh_nodes:"CFH.CollectionCards" AND '
                '(f_brand:"Pokemon" OR f_brand:"Pokémon" OR '
                'facets.productSeriesToys:"Pokémon")'
            ),
            "hitsPerPage": 250,
            "page": 0,
            "getRankingInfo": "true",
        },
    )

    pokemon_hits = []
    for hit in hits:
        try:
            if not shared["is_real_pokemon_tcg"](hit):
                continue
        except Exception:
            continue
        pokemon_hits.append(hit)

    return hits, pokemon_hits


def run_hidden_catalog(shared, site_key):
    hits, pokemon_hits = fetch_hidden_pokemon_hits(shared, site_key)
    hidden = [hit for hit in pokemon_hits if hit.get("is_exposed") is False]
    suspicious = []
    for hit in hidden:
        name = re.sub(r"\s+", " ", str(hit.get("name") or "").lower()).strip()
        try:
            price = float(hit.get("sales_price"))
        except (TypeError, ValueError):
            price = None

        if (
            any(marker in name for marker in WATCH_MARKERS)
            or (price is not None and 278.0 <= price <= 280.0)
        ):
            suspicious.append(compact_hit(site_key, "hidden-catalog", hit))

    return len(hits), len(pokemon_hits), len(hidden), suspicious


def metadata_fields(hit):
    found = {}
    for key, value in hit.items():
        lowered = str(key).lower()
        if any(marker in lowered for marker in METADATA_MARKERS):
            found[key] = value
    return found


def run_metadata_diagnostics(shared, site_key):
    _, pokemon_hits = fetch_hidden_pokemon_hits(shared, site_key)
    hidden = [hit for hit in pokemon_hits if hit.get("is_exposed") is False]

    target = None
    for hit in pokemon_hits:
        product_id = str(hit.get("id") or hit.get("objectID") or "")
        if product_id == TARGET_PRODUCT_ID:
            target = hit
            break

    print(f"METADATA {site_key.upper()}: {len(hidden)} skjulte Pokemon-poster")

    if target is None:
        print(f"TARGET {site_key.upper()}: {TARGET_PRODUCT_ID} ikke fundet")
    else:
        print(
            f"TARGET {site_key.upper()} KEYS "
            + json.dumps(sorted(target.keys()), ensure_ascii=False)
        )
        print(
            f"TARGET {site_key.upper()} METADATA "
            + json.dumps(metadata_fields(target), ensure_ascii=False, sort_keys=True, default=str)
        )
        print(
            f"TARGET {site_key.upper()} FULL "
            + json.dumps(target, ensure_ascii=False, sort_keys=True, default=str)
        )

    # Schema-level view: show which release/time/campaign-like fields actually
    # exist anywhere in the hidden Pokemon catalogue and example values.
    examples = {}
    for hit in hidden:
        for key, value in metadata_fields(hit).items():
            bucket = examples.setdefault(key, [])
            rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
            if rendered not in bucket and len(bucket) < 5:
                bucket.append(rendered)

    print(
        f"SCHEMA {site_key.upper()} METADATA_FIELDS "
        + json.dumps(examples, ensure_ascii=False, sort_keys=True)
    )


def main():
    # restock_bot_github.py requires this env var while its shared definitions
    # are loaded. The probe itself never posts Discord messages.
    if not os.getenv("DISCORD_WEBHOOK_URL"):
        raise RuntimeError("DISCORD_WEBHOOK_URL mangler til shared loader")

    shared = load_shared_namespace()
    all_hits = []

    print("SALLING PRE-RELEASE PROBE")
    print("Public Algolia query without is_exposed:true")

    for site_key in SITES:
        for term in SEARCH_TERMS:
            try:
                relevant, raw_count = run_query(shared, site_key, term)
            except Exception as error:
                print(f"PROBE {site_key.upper()} / {term}: FEJL {error}")
                continue

            print(
                f"PROBE {site_key.upper()} / {term}: "
                f"{raw_count} rå hits · {len(relevant)} relevante"
            )
            all_hits.extend(relevant)

        try:
            raw_count, pokemon_count, hidden_count, suspicious = run_hidden_catalog(
                shared,
                site_key,
            )
            print(
                f"HIDDEN {site_key.upper()}: {raw_count} rå · "
                f"{pokemon_count} Pokémon TCG · {hidden_count} skjulte · "
                f"{len(suspicious)} interessante"
            )
            for hit in suspicious:
                print("HIDDEN HIT " + json.dumps(hit, ensure_ascii=False, sort_keys=True))
            all_hits.extend(suspicious)
        except Exception as error:
            print(f"HIDDEN {site_key.upper()}: FEJL {error}")

        try:
            run_metadata_diagnostics(shared, site_key)
        except Exception as error:
            print(f"METADATA {site_key.upper()}: FEJL {error}")

    unique = {}
    for hit in all_hits:
        key = (hit.get("site"), hit.get("id") or hit.get("name"))
        unique[key] = hit

    print(f"PROBE RESULTAT: {len(unique)} unikke relevante produkter")
    for hit in unique.values():
        print("PROBE HIT " + json.dumps(hit, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
