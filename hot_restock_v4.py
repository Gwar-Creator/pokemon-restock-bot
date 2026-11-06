#!/usr/bin/env python3
"""Tier A HOT owns currently evidenced ONLINE stock, never physical store data.

The five alerting sources are Coolshop, Proshop, BR, Bilka and Foetex.
The other Tier A catalogues are read for state only. The HOT scanner keeps
all source data even when product availability is not alertable.
"""

from alert_policy import tier_a_signal_allowed
import hot_restock as base

# Retain the existing saved baseline and price/history data; alert gating only.
# A fresh transition from BESTILLINGSVARE to PÅ LAGER may be meaningful.
HOT_FILTER_VERSION = 4
_SALLING_ONLINE_SOURCES = {"br", "bilka", "foetex"}
_ORIGINAL_PRODUCT_AVAILABLE = base.product_available
_ORIGINAL_FILTER_HOT_PRODUCTS = base.filter_hot_products
_ORIGINAL_SEND_HOT_ALERT = base.send_hot_alert

# HOT is allowed to POST only genuinely actionable, fresh online stock.
# Salling (BR/Bilka/Foetex) Algolia online_count is a system-stock signal,
# NOT an independently confirmed checkout, so it remains data-only.
VERIFIED_ONLINE_HOT_SOURCES = {"coolshop", "proshop"}


def _fresh(product):
    """Cached inventory must not be re-advertised as a live online finding."""
    via = str((product or {}).get("fetch_via") or "")
    return "preserved_previous_scan" not in via.split("+")


def online_lane_product_available(source_key, product):
    """An alertable *online stock signal*, not a guaranteed successful checkout.

    For Salling, a positive published online_count is verified source-system
    data but not proof of checkout: Discord renders it neutrally, not BUY NOW.
    """
    if not isinstance(product, dict) or not _fresh(product):
        return False
    if product.get("preorder") is True:
        return False

    if source_key in _SALLING_ONLINE_SOURCES:
        # Algolia exposes separate online and local stock fields. Require
        # visible catalogue listing and positive online stock only.
        if product.get("is_exposed") is not True:
            return False
        count = product.get("online_count")
        if isinstance(count, bool):
            return False
        try:
            return int(count) > 0
        except (TypeError, ValueError, OverflowError):
            return False

    if source_key == "proshop":
        # BESTILLINGSVARE is orderable but not confirmed on-hand stock.
        return product.get("stock") == "PÅ LAGER"

    if source_key == "coolshop":
        available = product.get("online_stock")
        if isinstance(available, bool):
            return available
        if isinstance(available, (int, float)):
            return available > 0
        return False

    # Boozt/Magasin remain data-only and never post HOT Discord alerts.
    return _ORIGINAL_PRODUCT_AVAILABLE(source_key, product)


def policy_filtered_hot_products(shared, products):
    current = _ORIGINAL_FILTER_HOT_PRODUCTS(shared, products)
    return {
        product_id: product
        for product_id, product in current.items()
        if tier_a_signal_allowed(
            product.get("name"),
            event="RESTOCK",
        )
    }


def verified_only_hot_alert(source_key, product, event):
    """Final fail-closed gate BEFORE the shared #restocks webhook is called."""
    if source_key not in VERIFIED_ONLINE_HOT_SOURCES:
        print(f"HOT {str(source_key).upper()}: unverified system/catalog stock; Discord suppressed")
        return False
    if str(event or "").strip().upper() not in {"RESTOCK", "NYT"}:
        return False
    if not online_lane_product_available(source_key, product):
        return False
    try:
        _payload, status = base.hot_payload(source_key, product, event)
        if status != "BUY_NOW":
            print(f"HOT {str(source_key).upper()}: {status}; Discord suppressed")
            return False
    except Exception as error:
        print(f"HOT {str(source_key).upper()}: verification failed ({type(error).__name__}); Discord suppressed")
        return False
    return _ORIGINAL_SEND_HOT_ALERT(source_key, product, event)


def main():
    base.FILTER_VERSION = HOT_FILTER_VERSION
    base.product_available = online_lane_product_available
    base.filter_hot_products = policy_filtered_hot_products
    base.send_hot_alert = verified_only_hot_alert
    base.main()


if __name__ == "__main__":
    main()
