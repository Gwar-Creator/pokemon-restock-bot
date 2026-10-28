"""Read-only Discord V2 classifiers for Salling local and early signals.

These adapters do not post messages or modify state. They intentionally avoid
BUY_NOW and RESERVE_NOW: the source records cannot guarantee checkout.
"""
from datetime import datetime, timezone

from discord_alert_v2 import classify, webhook_payload

SOURCE_LABELS = {"br": "BR", "bilka": "BILKA", "foetex": "FØTEX"}


def _utc_checked():
    return datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M UTC")


def _stores_from_transitions(transitions):
    stores = []
    for row in transitions or []:
        if not isinstance(row, dict):
            continue
        stores.append({"name": row.get("name"), "stock": row.get("new")})
    return stores


def local_stock_event(product, transitions):
    """Positive per-store observations are system stock, not reservation."""
    visibility = str(product.get("visibility") or "UNKNOWN").upper()
    return {
        "source": product.get("site") or "SALLING",
        "name": product.get("name") or "Ukendt produkt",
        "price": product.get("price"),
        "url": product.get("url"),
        "stores": _stores_from_transitions(transitions),
        "is_pre_publish": visibility == "PRE-PUBLISH",
        "checked_at": product.get("observed_at") or _utc_checked(),
        # Never infer buyability from a positive local-store quantity.
        "online_buyable": False,
        "click_collect_reservable": False,
    }


def hidden_stock_event(rows):
    """Take ONLY rows previously approved by the hidden-stock location gate."""
    if not rows:
        raise ValueError("No local hidden-stock rows")
    first = rows[0]
    return {
        "source": SOURCE_LABELS.get(first.get("site"), "SALLING"),
        "name": first.get("name") or "Ukendt produkt",
        "price": first.get("price"),
        "url": first.get("url"),
        "stores": [
            {"name": row.get("store"), "stock": row.get("stock")}
            for row in rows
        ],
        "is_pre_publish": True,
        "checked_at": _utc_checked(),
        "online_buyable": False,
        "click_collect_reservable": False,
    }


def early_radar_event(title, product, detail, preferred_site=None):
    """Catalog/metadata/radar events cannot establish an orderable product."""
    sites = product.get("sites") or {}
    preferred = (sites.get(preferred_site) or {}) if preferred_site else {}
    selected = preferred or next(iter(sites.values()), {})
    # A hidden listing in another chain must not make a visible listing
    # at the preferred retailer appear hidden.
    explicitly_hidden = (
        selected.get("is_exposed") is False if preferred_site and selected
        else bool(sites) and all(
            isinstance(site, dict) and site.get("is_exposed") is False
            for site in sites.values()
        )
    )
    return {
        "source": "SALLING EARLY RADAR",
        "name": product.get("name") or "Ukendt produkt",
        "price": selected.get("price", product.get("price")),
        "url": selected.get("url") or "",
        # Country-wide store_count does not identify a reservable local shop.
        "stores": [],
        "is_pre_publish": explicitly_hidden,
        "checked_at": _utc_checked(),
        "online_buyable": False,
        "click_collect_reservable": False,
    }


def shadow_line(channel, event):
    """A diagnostic line with no URL, stock leak, webhook, or state updates."""
    status = classify(event)
    name = str(event.get("name") or "Ukendt produkt").replace("\n", " ")[:90]
    return f"DISCORD V2 SHADOW {channel}: {status} | {name}"


def preview_payload(event):
    """Use production renderer for a deterministic preview; do not send."""
    return webhook_payload(event)
