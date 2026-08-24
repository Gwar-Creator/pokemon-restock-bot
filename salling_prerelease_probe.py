import json
import os
import re
from pathlib import Path
from urllib.parse import urlencode

import requests

ROOT = Path(__file__).resolve().parent
SHARED_FILE = ROOT / "restock_bot_github.py"

SEARCH_TERMS = (
    "victini",
    "black bolt",
    "white flare",
    "illustration collection",
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


def run_query(shared, site_key, term):
    config = shared["get_salling_frontend_config"](site_key)
    algolia_url = (
        "https://"
        f"{config['algolia_app_id'].lower()}"
        "-dsn.algolia.net/1/indexes/*/queries"
    )

    params = {
        "query": term,
        "attributesToRetrieve": '["*"]',
        "hitsPerPage": 50,
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
        timeout=20,
    )
    response.raise_for_status()
    hits = response.json().get("results", [{}])[0].get("hits", [])

    relevant = []
    for hit in hits:
        name = str(hit.get("name") or "")
        normalized = re.sub(r"\s+", " ", name.lower()).strip()
        if any(marker in normalized for marker in SEARCH_TERMS):
            relevant.append(compact_hit(site_key, term, hit))

    return relevant, len(hits)


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

    unique = {}
    for hit in all_hits:
        key = (hit.get("site"), hit.get("id") or hit.get("name"))
        unique[key] = hit

    print(f"PROBE RESULTAT: {len(unique)} unikke relevante produkter")
    for hit in unique.values():
        print("PROBE HIT " + json.dumps(hit, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
