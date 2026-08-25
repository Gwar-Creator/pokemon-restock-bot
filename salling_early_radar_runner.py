"""Run Salling Early Radar without timestamp-only Discord alerts.

Salling's epoch_updated_at behaves like a recurring index heartbeat. It is still
stored in state by the underlying radar, but it must never be sufficient on its
own to create an alert. Real product changes (stock, exposure, price, campaign,
availability, dates, image/description, new product IDs, etc.) are unchanged.
"""

import salling_early_radar as radar


def ignore_epoch_only_change(old, current):
    """Treat epoch_updated_at-only movement as indexing noise."""
    return False


# The existing radar builds timestamp-only alert candidates through this helper.
# Replacing it here suppresses only RECORD OPDATERET heartbeat alerts while
# preserving every real-change branch in radar.main().
radar.epoch_only_change = ignore_epoch_only_change


if __name__ == "__main__":
    radar.main()
