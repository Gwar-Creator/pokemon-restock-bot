"""Conservative source adapter for Discord V2 HOT alerts.

Sources can contain system stock without confirmed orderability. Keep those
facts distinct and never promote a cached/hidden record to BUY NOW.
"""
from datetime import datetime, timezone

from discord_alert_v2 import classify, webhook_payload

LABELS = {
    "coolshop": "COOLSHOP",
    "proshop": "PROSHOP",
    "br": "BR",
    "bilka": "BILKA",
    "foetex": "FØTEX",
    "boozt": "BOOZT",
    "magasin": "MAGASIN",
}
SALLING_SOURCES = {"br", "bilka", "foetex"}


def _positive_count(value):
    if isinstance(value, bool):
        # An API boolean is not a verified number of stocked units.
        return False
    try:
        return int(value) > 0
    except (ValueError, TypeError, OverflowError):
        return False


def _stores(source_key, product):
    stores = []
    if source_key == "br":
        for field, label in (
            ("kolding_stock", "BR Kolding"),
            ("esbjerg_stock", "BR Esbjerg"),
        ):
            count = product.get(field)
            if _positive_count(count):
                stores.append({"name": label, "stock": count})
    elif source_key in ("bilka", "foetex"):
        for store in (product.get("local_stocks") or {}).values():
            if not isinstance(store, dict):
                continue
            count = store.get("stock")
            if _positive_count(count):
                stores.append({"name": store.get("name"), "stock": count})
    return stores


def hot_event(source_key, product, event):
    """Only use source-specific *fresh* buyability fields for green alerts."""
    data = product if isinstance(product, dict) else {}
    hidden = data.get("is_exposed") is False
    preserved = "preserved_previous_scan" in str(data.get("fetch_via") or "").split("+")
    preordering = data.get("preorder") is True
    online_system_signal = (
        source_key in SALLING_SOURCES
        and _positive_count(data.get("online_count"))
    )
    url = data.get("url") or ""
    online_buyable = False
    if not hidden and not preserved and not preordering:
        if source_key == "coolshop":
            online_buyable = data.get("online_stock") is True or (
                isinstance(data.get("online_stock"), (int, float))
                and not isinstance(data.get("online_stock"), bool)
                and data["online_stock"] > 0
            )
        elif source_key == "proshop":
            # An orderable BESTILLINGSVARE is not verified in-stock dispatch.
            online_buyable = data.get("stock") == "PÅ LAGER"
        elif source_key in SALLING_SOURCES:
            # Neither an exposed catalogue entry nor positive online_count
            # verifies checkout/reservation. It is only a stock-system signal.
            online_buyable = False
        elif source_key in ("boozt", "magasin"):
            # These sources are data-only in HOT today; retain conservative
            # semantics if the adapter is re-used for their future alerts.
            online_buyable = data.get("in_stock") is True

    stores = _stores(source_key, data)
    payload = {
        "source": LABELS.get(source_key, source_key.upper()),
        "event_type": "RESTOCK" if str(event).upper() == "RESTOCK" else "NYT PRODUKT",
        "sku": data.get("sku") or "",
        "name": data.get("name") or "Ukendt produkt",
        "price": data.get("price"),
        "url": url,
        "image_url": data.get("image_url") or "",
        "checked_at": datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M UTC"),
        "online_buyable": bool(online_buyable),
        "is_pre_publish": hidden,
        "preorder_open": preordering and not hidden,
        "stores": stores,
        "signal_details": (
            "Positivt online systemlager registreret. Køb og reservation er "
            "ikke verificeret; tjek butikken manuelt."
            if online_system_signal else ""
        ),
    }
    # An orderable Proshop 'BESTILLINGSVARE' is not in-stock dispatch.
    # Retain the distinction prominently in the embed.
    if source_key == "proshop" and data.get("stock") == "BESTILLINGSVARE":
        payload["event_type"] = "BESTILLINGSVARE – IKKE LAGER-RESTOCK"
        payload["order_note"] = "BESTILLINGSVARE – ikke bekræftet på lager. Kontrollér bestillingsmulighed og leveringstid hos Proshop."
    if online_system_signal:
        payload["order_note"] = "ONLINE SYSTEMLAGER – køb og reservation ikke bekræftet"
    return payload


def hot_payload(source_key, product, event):
    data = hot_event(source_key, product, event)
    payload = webhook_payload(data)
    if data.get("order_note"):
        payload["embeds"][0]["fields"].append({
            "name": "BEMÆRK",
            "value": data["order_note"],
            "inline": False,
        })
    return payload, classify(data)
