#!/usr/bin/env python3
"""HOT Restock V4 lane-ownership wrapper.

Keeps Tier A fast while removing two sources of Restock-channel noise:
1) apply the shared Tier A Discord product policy to HOT as well;
2) for BR/Bilka/Foetex, HOT owns online availability only. Local store
   transitions are owned by local_stock_watch.py.
"""

from alert_policy import tier_a_signal_allowed
import hot_restock as base

HOT_FILTER_VERSION = 4
_SALLING_LOCAL_OWNED_SOURCES = {"br", "bilka", "foetex"}
_ORIGINAL_PRODUCT_AVAILABLE = base.product_available
_ORIGINAL_FILTER_HOT_PRODUCTS = base.filter_hot_products


def online_lane_product_available(source_key, product):
    if source_key in _SALLING_LOCAL_OWNED_SOURCES:
        return int(product.get("online_count") or 0) > 0
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


def main():
    # A version bump deliberately gives the changed HOT semantics one silent
    # baseline iteration before alerts resume.
    base.FILTER_VERSION = HOT_FILTER_VERSION
    base.product_available = online_lane_product_available
    base.filter_hot_products = policy_filtered_hot_products
    base.main()


if __name__ == "__main__":
    main()
