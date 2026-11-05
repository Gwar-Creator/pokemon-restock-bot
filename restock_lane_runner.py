#!/usr/bin/env python3
"""Strict routing: the ordinary #restocks channel is Local Stock only.

The broad scanner still fetches and persists product/price history, but
no broad-scanner text (including misclassified or unlabelled product events)
can be sent to #restocks. Local Stock has its own guarded sender.
"""

import restock_v2_runner as base


def restock_lane_channel_alert_allowed(message, legacy_policy=None):
    # Fail closed for every broad-scanner message. Legacy can emit product
    # changes with several different headers, including unrecognized ones.
    # All #restocks product alerts must originate from the dedicated,
    # selected-city local_stock_watch.py proof-of-stock path.
    return False


def main():
    base.restock_v2_channel_alert_allowed = restock_lane_channel_alert_allowed
    base.main()


if __name__ == "__main__":
    main()
