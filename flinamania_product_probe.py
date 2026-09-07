"""Flinamania-specific product page stock probe.

Flinamania's public Shopify products feed currently exposes useful catalog and
price data but not reliable variant availability. The storefront itself renders
a definitive add-to-cart control on each product page, so this module overlays
only the stock bit from that control while Wave 1 remains shadow-only.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup


BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
}

IN_STOCK_MARKERS = (
    "læg i kurv",
    "laeg i kurv",
    "tilføj kurv",
    "tilfoj kurv",
    "add to cart",
)

OUT_OF_STOCK_MARKERS = (
    "udsolgt",
    "ikke på lager",
    "ikke pa lager",
    "out of stock",
    "sold out",
)


def _clean(value) -> str:
    return " ".join(str(value or "").split()).strip()


def _disabled(control) -> bool:
    if control.has_attr("disabled"):
        return True
    return str(control.get("aria-disabled") or "").strip().lower() == "true"


def _hidden(node) -> bool:
    current = node
    for _ in range(6):
        if current is None or not getattr(current, "attrs", None):
            break
        if current.has_attr("hidden"):
            return True
        if str(current.get("aria-hidden") or "").strip().lower() == "true":
            return True
        style = str(current.get("style") or "").replace(" ", "").lower()
        if "display:none" in style or "visibility:hidden" in style:
            return True
        classes = {str(value).lower() for value in (current.get("class") or [])}
        if "hidden" in classes:
            return True
        current = getattr(current, "parent", None)
    return False


def _control_text(control) -> str:
    values = [
        _clean(control.get_text(" ", strip=True)),
        _clean(control.get("value")),
        _clean(control.get("aria-label")),
        _clean(control.get("title")),
    ]
    return " ".join(value for value in values if value).lower()


def parse_product_page_stock(document: str):
    """Return True/False from a product add-to-cart form, or None if ambiguous."""
    soup = BeautifulSoup(document or "", "html.parser")
    positives = 0
    negatives = 0

    forms = soup.select('form[action*="/cart/add"]')
    for form in forms:
        controls = form.select(
            'button[name="add"], button[type="submit"], input[type="submit"], [name="add"]'
        )
        for control in controls:
            if _hidden(control):
                continue
            text = _control_text(control)
            is_disabled = _disabled(control)

            if any(marker in text for marker in OUT_OF_STOCK_MARKERS):
                negatives += 1
                continue

            if any(marker in text for marker in IN_STOCK_MARKERS):
                if is_disabled:
                    negatives += 1
                else:
                    positives += 1
                continue

            classes = {str(value).lower() for value in (control.get("class") or [])}
            if not is_disabled and (
                str(control.get("name") or "").lower() == "add"
                or "product-form__submit" in classes
            ):
                positives += 1
            elif is_disabled:
                negatives += 1

    # Enabled cart controls are stronger evidence than stale sale/sold-out badges
    # elsewhere on the product page.
    if positives:
        return True
    if negatives:
        return False
    return None


def _fetch_one(url: str, timeout: int = 15):
    response = requests.get(
        url,
        headers={
            **BROWSER_HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return parse_product_page_stock(response.text)


def apply_product_page_stock(products, *, fetch_one=_fetch_one, max_workers: int = 4):
    """Overlay Flinamania stock from product pages without changing catalog data."""
    if not isinstance(products, dict) or not products:
        return products

    jobs = {}
    positives = 0
    negatives = 0
    unknown = 0
    errors = 0

    with ThreadPoolExecutor(max_workers=max(1, int(max_workers or 1))) as executor:
        for product_id, product in products.items():
            url = str((product or {}).get("url") or "").strip()
            if not url:
                unknown += 1
                continue
            jobs[executor.submit(fetch_one, url)] = product_id

        for future in as_completed(jobs):
            product_id = jobs[future]
            try:
                value = future.result()
            except requests.RequestException:
                errors += 1
                continue
            except Exception:
                errors += 1
                continue

            if value is True:
                products[product_id]["in_stock"] = True
                positives += 1
            elif value is False:
                products[product_id]["in_stock"] = False
                negatives += 1
            else:
                unknown += 1

    print(
        "FLINAMANIA PRODUCT PROBE: "
        f"{len(products)} produkter | buyable={positives} | sold_out={negatives} | "
        f"unknown={unknown} | errors={errors}"
    )
    return products
