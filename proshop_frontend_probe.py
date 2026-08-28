import re
from pathlib import Path
from urllib.parse import quote

import requests

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None

ROOT = Path(__file__).resolve().parent
SHARED_FILE = ROOT / "restock_bot_github.py"
BASE = "https://www.proshop.dk"
AUTOCOMPLETE = BASE + "/ClientPlugins/AutoComplete/SearchResult"
FULL_TERMS = ("Pokemon TCG", "Pokemon booster", "Pokemon collection")
PAGES = tuple(range(1, 7))


def load_shared_namespace():
    source = SHARED_FILE.read_text(encoding="utf-8")
    marker = (
        "# =========================================================\n"
        "# START\n"
        "# ========================================================="
    )
    namespace = {"__name__": "proshop_frontend_probe_shared", "__file__": str(SHARED_FILE)}
    exec(compile(source.split(marker, 1)[0], str(SHARED_FILE), "exec"), namespace)
    return namespace


def browser_get(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
        "Referer": BASE + "/",
    }
    try:
        response = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        if response.status_code == 200:
            return response, "requests"
    except Exception:
        pass
    if curl_requests is None:
        raise RuntimeError("curl_cffi unavailable and plain requests did not return 200")
    response = curl_requests.get(
        url,
        headers=headers,
        timeout=30,
        allow_redirects=True,
        impersonate="chrome",
    )
    response.raise_for_status()
    return response, "curl_cffi"


def raw_product_ids(text):
    return set(re.findall(
        r"(?:https?://(?:www\.)?proshop\.dk)?/Pokemon/[^\"'<>?\s]+/([0-9]{6,9})",
        text or "",
        flags=re.IGNORECASE,
    ))


def hot_like(name):
    text = " " + re.sub(r"\s+", " ", str(name or "").lower()).strip() + " "
    if any(marker in text for marker in (" booster pack ", " sleeved booster ", " sleeve booster ")):
        return False
    core = any(marker in text for marker in (" booster bundle ", " booster box ", " booster display "))
    etb = " elite trainer box " in text or bool(re.search(r"\betb\b", text))
    collection = any(marker in text for marker in (
        " premium collection ", " ultra-premium collection ", " ultra premium collection ",
        " special collection ", " illustration collection ",
    ))
    if etb and any(marker in text for marker in (" chaos rising ", " pitch black ")):
        return False
    if core or etb or collection:
        return True
    if " ultra premium " in text or bool(re.search(r"\bupc\b", text)):
        return True
    return any(marker in text for marker in (
        " first partner ", " 30th anniversary ", " 30th ", " ascended heroes ",
        " white flare ", " black bolt ",
    ))


def main():
    shared = load_shared_namespace()
    existing = shared["get_proshop_products"]()
    existing_ids = set(map(str, existing))
    print(f"DIRECT PROBE existing production route: {len(existing_ids)} parsed TCG")

    merged = {}
    raw_all = set()

    for term in FULL_TERMS:
        term_ids = set()
        term_parsed = {}
        previous_raw = None
        for page in PAGES:
            query = "s=" + quote(term)
            if page > 1:
                query += f"&pn={page}"
            url = BASE + "/?" + query
            response, method = browser_get(url)
            raw_ids = raw_product_ids(response.text)
            parsed = shared["_parse_proshop_products"](response)
            parsed = {str(k): v for k, v in parsed.items()}
            print(
                f"DIRECT PROBE {term!r} page={page}: method={method} status={response.status_code} "
                f"raw={len(raw_ids)} parsed_tcg={len(parsed)}"
            )
            if previous_raw is not None and raw_ids == previous_raw:
                print(f"DIRECT PROBE {term!r}: page {page} repeats previous page; stopping")
                break
            previous_raw = raw_ids
            term_ids.update(raw_ids)
            raw_all.update(raw_ids)
            term_parsed.update(parsed)
            merged.update(parsed)

        print(
            f"DIRECT PROBE {term!r} total: raw_unique={len(term_ids)} "
            f"parsed_tcg_unique={len(term_parsed)}"
        )

    merged_ids = set(merged)
    direct_only = sorted(merged_ids - existing_ids)
    direct_only_hot = [pid for pid in direct_only if hot_like(merged[pid].get("name"))]
    print(
        f"DIRECT PROBE SUMMARY: raw_unique={len(raw_all)} direct_parsed={len(merged_ids)} "
        f"existing={len(existing_ids)} direct_only={len(direct_only)} "
        f"direct_only_hot={len(direct_only_hot)}"
    )
    for pid in direct_only:
        p = merged[pid]
        marker = "HOT" if pid in direct_only_hot else "TCG"
        print(
            f"DIRECT PROBE {marker} ONLY {pid}: {p.get('name')} | {p.get('stock')} | "
            f"{p.get('price')} | {p.get('url')}"
        )

    # Confirm the exact frontend autocomplete path is reachable directly too.
    response, method = browser_get(AUTOCOMPLETE + "?searchInput=" + quote("Pokemon TCG"))
    print(
        f"DIRECT PROBE AUTOCOMPLETE: method={method} status={response.status_code} "
        f"raw_products={len(raw_product_ids(response.text))} bytes={len(response.content)}"
    )


if __name__ == "__main__":
    main()
