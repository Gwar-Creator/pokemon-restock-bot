import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
SHARED_FILE = ROOT / "restock_bot_github.py"
STATE_FILE = ROOT / "hot_restock_state.json"
FILTER_VERSION = 1

HOT_ITERATIONS = max(1, int(os.getenv("HOT_ITERATIONS", "1")))
HOT_INTERVAL_SECONDS = max(30, int(os.getenv("HOT_INTERVAL_SECONDS", "55")))
HOT_DRY_RUN = os.getenv("HOT_DRY_RUN", "0").strip() == "1"
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

EXCLUDED_ETB_SETS = (
    "chaos rising",
    "pitch black",
)

CORE_MARKERS = (
    "booster bundle",
    "booster box",
    "booster display",
)

COLLECTION_MARKERS = (
    "premium collection",
    "ultra-premium collection",
    "ultra premium collection",
    "special collection",
    "illustration collection",
)

WATCH_MARKERS = (
    "first partner",
    "30th anniversary",
    "30th",
    "ascended heroes",
    "white flare",
    "black bolt",
)

PACK_MARKERS = (
    "booster pack",
    "sleeved booster",
    "sleeve booster",
)

SOURCE_LABELS = {
    "proshop": "PROSHOP",
    "br": "BR",
    "bilka": "BILKA",
    "foetex": "FØTEX",
}


def _clean_name(name):
    return " " + re.sub(r"\s+", " ", str(name or "").lower()).strip() + " "


def hot_product_allowed(name):
    text = _clean_name(name)

    # Single packs stay out of the fast lane, even for watched sets.
    if any(marker in text for marker in PACK_MARKERS):
        return False

    # Some shops call a loose pack simply "booster". Keep it out unless the
    # title explicitly says bundle/box/display.
    if (
        " booster " in text
        and not any(marker in text for marker in CORE_MARKERS)
        and "elite trainer box" not in text
        and not re.search(r"\betb\b", text)
        and not any(marker in text for marker in COLLECTION_MARKERS)
    ):
        return False

    is_etb = "elite trainer box" in text or bool(re.search(r"\betb\b", text))
    if is_etb:
        return not any(blocked in text for blocked in EXCLUDED_ETB_SETS)

    if any(marker in text for marker in CORE_MARKERS):
        return True

    if any(marker in text for marker in COLLECTION_MARKERS):
        return True

    if " ultra premium " in text or bool(re.search(r"\bupc\b", text)):
        return True

    if any(marker in text for marker in WATCH_MARKERS):
        return True

    return False


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
        "__name__": "restock_hot_shared",
        "__file__": str(SHARED_FILE),
    }
    exec(compile(source.split(marker, 1)[0], str(SHARED_FILE), "exec"), namespace)
    return namespace


def load_state():
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def product_available(source_key, product):
    if source_key == "proshop":
        return product.get("stock") == "PÅ LAGER"

    if source_key == "br":
        if int(product.get("online_count") or 0) > 0:
            return True
        if int(product.get("kolding_stock") or 0) > 0:
            return True
        if int(product.get("esbjerg_stock") or 0) > 0:
            return True
        return False

    if source_key in ("bilka", "foetex"):
        if int(product.get("online_count") or 0) > 0:
            return True
        for store in (product.get("local_stocks") or {}).values():
            if int(store.get("stock") or 0) > 0:
                return True
        return False

    return False


def availability_text(source_key, product):
    if source_key == "proshop":
        return product.get("stock") or "UKENDT"

    bits = []
    online = int(product.get("online_count") or 0)
    if online > 0:
        bits.append(f"Online {online} stk.")

    if source_key == "br":
        kolding = int(product.get("kolding_stock") or 0)
        esbjerg = int(product.get("esbjerg_stock") or 0)
        if kolding > 0:
            bits.append(f"BR Kolding {kolding} stk.")
        if esbjerg > 0:
            bits.append(f"BR Esbjerg {esbjerg} stk.")
    else:
        for store in (product.get("local_stocks") or {}).values():
            stock = int(store.get("stock") or 0)
            if stock > 0:
                bits.append(f"{store.get('name') or 'Lokal butik'} {stock} stk.")

    return " · ".join(bits) if bits else "Ikke på lager"


def format_price(value):
    if value is None:
        return "Pris ikke oplyst"
    try:
        price = float(value)
    except (TypeError, ValueError):
        return "Pris ikke oplyst"
    return f"{price:,.2f} kr.".replace(",", "X").replace(".", ",").replace("X", ".")


def send_hot_alert(source_key, product, event):
    label = SOURCE_LABELS[source_key]
    message = (
        f"🚨 **HOT {event} · {label}**\n"
        f"**{product.get('name') or 'Ukendt produkt'}**\n"
        f"💰 {format_price(product.get('price'))}\n"
        f"📦 {availability_text(source_key, product)}\n"
        f"🔗 {product.get('url') or ''}"
    )

    if HOT_DRY_RUN:
        print("HOT DRY RUN:")
        print(message)
        return

    if not WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL mangler til HOT scanner")

    response = requests.post(
        WEBHOOK_URL,
        json={"content": message},
        timeout=15,
    )
    response.raise_for_status()


def filter_hot_products(shared, products):
    allowed = {}
    shared_relevance = shared["restock_alert_allowed"]

    for product_id, product in (products or {}).items():
        if not isinstance(product, dict):
            continue
        if not shared_relevance(product, "POKÉMON"):
            continue
        if not hot_product_allowed(product.get("name")):
            continue
        allowed[str(product_id)] = product

    return allowed


def fetch_source(shared, source_key, old_products):
    if source_key == "proshop":
        return shared["get_proshop_products"]()
    if source_key == "br":
        return shared["get_br_products"](old_products)
    if source_key in ("bilka", "foetex"):
        return shared["get_salling_products"](source_key, old_products)
    raise KeyError(source_key)


def run_scan(shared, state):
    source_state = state.setdefault("sources", {})
    successful = 0

    for source_key in SOURCE_LABELS:
        old_products = source_state.get(source_key)
        source_baseline = not isinstance(old_products, dict)
        old_products = old_products if isinstance(old_products, dict) else {}

        try:
            fetched = fetch_source(shared, source_key, old_products)
            current = filter_hot_products(shared, fetched)
        except Exception as error:
            print(f"HOT {SOURCE_LABELS[source_key]} FEJL: {error}")
            continue

        successful += 1

        if source_baseline:
            print(
                f"HOT {SOURCE_LABELS[source_key]} baseline: "
                f"{len(current)} relevante produkter, ingen alerts"
            )
        else:
            for product_id, product in current.items():
                if not product_available(source_key, product):
                    continue

                old = old_products.get(product_id)
                if old is None:
                    send_hot_alert(source_key, product, "NYT")
                    continue

                if not product_available(source_key, old):
                    send_hot_alert(source_key, product, "RESTOCK")

        source_state[source_key] = current
        print(
            f"HOT {SOURCE_LABELS[source_key]}: "
            f"{len(current)} relevante · "
            f"{sum(product_available(source_key, p) for p in current.values())} på lager"
        )

    state["filter_version"] = FILTER_VERSION
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    return successful


def main():
    shared = load_shared_namespace()
    state = load_state()

    if not isinstance(state, dict) or state.get("filter_version") != FILTER_VERSION:
        state = {
            "filter_version": FILTER_VERSION,
            "sources": {},
            "updated_at": None,
        }
        print("HOT scanner: opretter stille baseline")

    for iteration in range(HOT_ITERATIONS):
        started = time.monotonic()
        print(f"HOT scan {iteration + 1}/{HOT_ITERATIONS}")
        successful = run_scan(shared, state)
        print(f"HOT scan færdig: {successful}/{len(SOURCE_LABELS)} kilder lykkedes")

        if iteration + 1 >= HOT_ITERATIONS:
            break

        elapsed = time.monotonic() - started
        sleep_for = max(0.0, HOT_INTERVAL_SECONDS - elapsed)
        if sleep_for:
            time.sleep(sleep_for)


if __name__ == "__main__":
    main()
