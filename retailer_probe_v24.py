import json
import re
from datetime import datetime, timezone
from urllib.parse import quote

import requests

PROSHOP_URL = "https://www.proshop.dk/pokemon-kort"
ELGIGANTEN_PRODUCT_URL = "https://www.elgiganten.dk/product/sport-fritid-hobby/samleobjekter-merchandise/samlekort/pokemon-tcg-mega-evolution-perfect-order-booster-pack/1078228"
ELGIGANTEN_ARTICLE = "1078228"
RESULT_FILE = "retailer_probe_v24_result.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
}
JINA_HEADERS = {
    "Accept": "text/plain, text/markdown;q=0.9, */*;q=0.5",
    "User-Agent": "Pokemon-Lorcana-MasterBot/2.4 RetailerProbe",
    "x-no-cache": "true",
    "x-engine": "browser",
}


def safe_get(url, headers=None, timeout=45):
    try:
        response = requests.get(url, headers=headers or HEADERS, timeout=timeout, allow_redirects=True)
        return {
            "ok": response.ok,
            "status": response.status_code,
            "final_url": response.url,
            "content_type": response.headers.get("content-type", ""),
            "text": response.text or "",
        }
    except Exception as error:
        return {
            "ok": False,
            "status": None,
            "final_url": "",
            "content_type": "",
            "text": "",
            "error": f"{type(error).__name__}: {error}",
        }


def public_summary(result):
    text = result.get("text") or ""
    return {
        "ok": bool(result.get("ok")),
        "status": result.get("status"),
        "final_url": result.get("final_url"),
        "content_type": result.get("content_type"),
        "length": len(text),
        "error": result.get("error"),
    }


def proshop_probe():
    direct = safe_get(PROSHOP_URL, HEADERS, 30)
    jina = safe_get("https://r.jina.ai/" + PROSHOP_URL, JINA_HEADERS, 60)
    text = jina.get("text") or ""
    links = set(re.findall(r"/Pokemon/[^)\s?#]+/\d+", text, flags=re.IGNORECASE))
    return {
        "direct": public_summary(direct),
        "jina_fresh": {
            **public_summary(jina),
            "raw_product_links": len(links),
            "has_pitch_black_etb_3478494": "3478494" in text,
            "has_mega_greninja_3478496": "3478496" in text,
            "has_chaos_rising_box_3447592": "3447592" in text,
        },
    }


def cxorchestrator_url(article_number):
    variables = json.dumps({
        "articleNumber": str(article_number),
        "withCustomerSpecificPrices": False,
    }, separators=(",", ":"))
    extensions = json.dumps({
        "persistedQuery": {
            "version": 1,
            "sha256Hash": "229bbb14ee6f93449967eb326f5bfb87619a37e7ee6c4555b94496313c139ee1",
        }
    }, separators=(",", ":"))
    return (
        "https://www.elgiganten.dk/cxorchestrator/dk/api"
        "?getProductWithDynamicDetails"
        "&appMode=b2c"
        "&user=anonymous"
        "&operationName=getProductWithDynamicDetails"
        f"&variables={quote(variables, safe='')}"
        f"&extensions={quote(extensions, safe='')}"
    )


def collect_interesting_paths(value, prefix="", found=None, depth=0):
    if found is None:
        found = []
    if depth > 8 or len(found) >= 80:
        return found

    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            low = str(key).lower()
            if any(marker in low for marker in (
                "stock", "store", "availability", "available", "price", "inventory", "quantity", "department", "delivery"
            )):
                found.append(path)
            collect_interesting_paths(child, path, found, depth + 1)
    elif isinstance(value, list):
        for index, child in enumerate(value[:20]):
            collect_interesting_paths(child, f"{prefix}[{index}]", found, depth + 1)
    return found


def elgiganten_probe():
    direct_page = safe_get(ELGIGANTEN_PRODUCT_URL, HEADERS, 30)
    jina_page = safe_get("https://r.jina.ai/" + ELGIGANTEN_PRODUCT_URL, JINA_HEADERS, 60)
    jina_text = jina_page.get("text") or ""

    cx = safe_get(cxorchestrator_url(ELGIGANTEN_ARTICLE), HEADERS, 30)
    cx_summary = public_summary(cx)
    cx_text = cx.get("text") or ""
    cx_summary["json"] = False
    cx_summary["interesting_paths"] = []
    cx_summary["top_level_keys"] = []
    if cx.get("ok") and cx_text:
        try:
            payload = json.loads(cx_text)
            cx_summary["json"] = True
            if isinstance(payload, dict):
                cx_summary["top_level_keys"] = sorted(payload.keys())[:30]
            cx_summary["interesting_paths"] = collect_interesting_paths(payload)[:80]
        except Exception as error:
            cx_summary["json_error"] = f"{type(error).__name__}: {error}"

    low = jina_text.lower()
    return {
        "direct_product_page": public_summary(direct_page),
        "jina_fresh_product_page": {
            **public_summary(jina_page),
            "has_article": ELGIGANTEN_ARTICLE in jina_text,
            "has_price_69": bool(re.search(r"\b69(?:[,.]00)?\b", jina_text)),
            "mentions_not_available": (
                "ikke tilgængelig" in low
                or "ikke tilgaengelig" in low
                or "not available" in low
            ),
            "mentions_click_collect": "klik & hent" in low or "klik og hent" in low,
            "mentions_kolding": "kolding" in low,
            "mentions_esbjerg": "esbjerg" in low,
        },
        "anonymous_cxorchestrator": cx_summary,
    }


def main():
    result = {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "read-only retailer path probe; no login, purchase, or access-control bypass",
        "proshop": proshop_probe(),
        "elgiganten": elgiganten_probe(),
    }
    with open(RESULT_FILE, "w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
