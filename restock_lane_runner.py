#!/usr/bin/env python3
"""Ordinary #restocks is reserved for documented local-store signals.

The broad scanner still fetches all sources and updates saved data, but does
not post generic NEW/PREORDER/RESTOCK messages to the local Restocks channel.
HOT owns Tier 1 online changes; local_stock_watch.py owns verified *source*
store-count transitions for LIVE products; Early Radar owns pre-publish signals.
"""

import restock_v2_runner as base

_ORIGINAL_CHANNEL_POLICY = base.restock_v2_channel_alert_allowed


def restock_lane_channel_alert_allowed(message, legacy_policy=None):
    lines = base._clean_lines(message)
    if not lines:
        return False

    event = base._event_from_headline(lines[0])
    if event in {"NEW", "PREORDER", "RESTOCK"}:
        # This source is data/history only. A product event alone cannot
        # establish a selected-city local inventory transition.
        return False

    return _ORIGINAL_CHANNEL_POLICY(
        message,
        legacy_policy=legacy_policy,
    )


def main():
    base.restock_v2_channel_alert_allowed = restock_lane_channel_alert_allowed
    base.main()


if __name__ == "__main__":
    main()
