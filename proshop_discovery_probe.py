import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
SHARED_FILE = ROOT / "restock_bot_github.py"

BRAND_BASE = "https://www.proshop.dk/Pokemon/Pokemon"
BRAND_PAGES = tuple(range(1, 7))
SITEMAP_URL = "https://www.proshop.dk/sitemap.xml"


def load_shared_namespace():
    source = SHARED_FILE.read_text(encoding="utf-8")
    marker = (
        "# =========================================================\n"
        "# START\n"
        "# ========================================================="
    )
    namespace = {
        "__name__": "proshop_probe_shared",
        "__file__": str(SHARED_FILE),
    }
    exec(compile(source.split(marker, 1)[0], str(SHARED_FILE), "exec"), namespace)
    return namespace


def reader_headers():
    return {
        "Accept": "text/plain, text/markdown;q=0.9, */*;q=0.5",
        "User-Agent": "Pokemon-Lorcana-MasterBot/2.8 ProshopDiscoveryProbe",
        "x-no-cache": "true",
        "x-engine": "browser",
    }


def raw_product_ids(text):
    pattern = re.compile(
        r"(?:https?://(?:www\.)?proshop\.dk)?/Pokemon/[^)\s?#]+/(\d+)",
        re.IGNORECASE,
    )
    return set(pattern.findall(text or ""))


def fetch_brand_page(shared, page):
    public_url = BRAND_BASE if page == 1 else f"{BRAND_BASE}?pn={page}"
    reader_url = "https://r.jina.ai/" + public_url
    response = requests.get(reader_url, headers=reader_headers(), timeout=50)
    response.raise_for_status()
    parsed = shared["_parse_proshop_reader_markdown"](response.text)
    ids = raw_product_ids(response.text)
    print(
        f"PROBE brand page {page}: raw={len(ids)} · parsed_tcg={len(parsed)}"
    )
    return page, parsed, ids


def fetch_brand_catalog(shared):
    merged = {}
    raw_ids = set()
    errors = []

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fetch_brand_page, shared, page) for page in BRAND_PAGES]
        for future in futures:
            try:
                _, products, ids = future.result()
                raw_ids.update(ids)
                for product_id, product in products.items():
                    product = dict(product)
                    product["fetch_via"] = "jina_reader_brand_probe"
                    merged[str(product_id)] = product
            except Exception as error:
                errors.append(str(error))

    print(
        f"PROBE brand total: unique_raw={len(raw_ids)} · parsed_tcg={len(merged)} · "
        f"failed_pages={len(errors)}"
    )
    if errors:
        print("PROBE brand errors: " + " | ".join(errors))
    return merged


def hot_like_allowed(shared, product):
    if not shared["restock_alert_allowed"](product, "POKÉMON"):
        return False

    text = " " + re.sub(r"\s+", " ", str(product.get("name") or "").lower()).strip() + " "
    if any(marker in text for marker in (" booster pack ", " sleeved booster ", " sleeve booster ")):
        return False

    is_core = any(marker in text for marker in (" booster bundle ", " booster box ", " booster display "))
    is_etb = " elite trainer box " in text or bool(re.search(r"\betb\b", text))
    is_collection = any(
        marker in text
        for marker in (
            " premium collection ",
            " ultra-premium collection ",
            " ultra premium collection ",
            " special collection ",
            " illustration collection ",
        )
    )

    if is_etb and any(marker in text for marker in (" chaos rising ", " pitch black ")):
        return False
    if is_core or is_etb or is_collection:
        return True
    if " ultra premium " in text or bool(re.search(r"\bupc\b", text)):
        return True
    return any(
        marker in text
        for marker in (
            " first partner ",
            " 30th anniversary ",
            " 30th ",
            " ascended heroes ",
            " white flare ",
            " black bolt ",
        )
    )


def probe_sitemap():
    try:
        response = requests.get(
            SITEMAP_URL,
            headers={"User-Agent": "Pokemon-Lorcana-MasterBot/2.8 ProshopDiscoveryProbe"},
            timeout=30,
        )
        response.raise_for_status()
        print(
            f"PROBE sitemap: status={response.status_code} · bytes={len(response.content)} · "
            f"content-type={response.headers.get('content-type')}"
        )
        root = ET.fromstring(response.content)
        locs = [
            (node.text or "").strip()
            for node in root.iter()
            if node.tag.rsplit("}", 1)[-1].lower() == "loc" and (node.text or "").strip()
        ]
        xml_locs = [url for url in locs if url.lower().endswith(".xml")]
        pokemon_locs = [url for url in locs if "/pokemon/" in url.lower()]
        print(
            f"PROBE sitemap root: locs={len(locs)} · child_xml={len(xml_locs)} · "
            f"pokemon_urls={len(pokemon_locs)}"
        )
        for url in xml_locs[:20]:
            print(f"PROBE sitemap child: {url}")
        for url in pokemon_locs[:20]:
            print(f"PROBE sitemap pokemon: {url}")
    except Exception as error:
        print(f"PROBE sitemap failed: {error}")


def main():
    shared = load_shared_namespace()

    curated = shared["get_proshop_products"]()
    print(f"PROBE curated: parsed_tcg={len(curated)}")

    brand = fetch_brand_catalog(shared)
    curated_ids = set(map(str, curated))
    brand_ids = set(map(str, brand))
    brand_only_ids = sorted(brand_ids - curated_ids)
    hot_only = [
        product_id
        for product_id in brand_only_ids
        if hot_like_allowed(shared, brand[product_id])
    ]

    print(
        f"PROBE comparison: curated={len(curated_ids)} · brand={len(brand_ids)} · "
        f"brand_only={len(brand_only_ids)} · brand_only_hot={len(hot_only)}"
    )

    for product_id in brand_only_ids[:30]:
        product = brand[product_id]
        marker = "HOT" if product_id in hot_only else "TCG"
        print(
            f"PROBE {marker} brand-only {product_id}: "
            f"{product.get('name')} | {product.get('stock')} | {product.get('price')} | "
            f"{product.get('url')}"
        )

    probe_sitemap()


if __name__ == "__main__":
    main()
