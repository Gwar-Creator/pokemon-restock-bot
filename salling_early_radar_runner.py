"""Run Salling Early Radar without timestamp-only Discord alerts.

Salling's epoch_updated_at behaves like a recurring index heartbeat. It is still
stored in state by the underlying radar, but it must never be sufficient on its
own to create an alert. Real product changes (stock, exposure, price, campaign,
availability, dates, image/description, new product IDs, etc.) are unchanged.

This runner also keeps alert links retailer-correct when Bilka and Foetex expose
the same shared Salling product ID. The base radar stores both storefront URLs
on one merged product, so a generic "Bilka first" fallback can otherwise attach
a Bilka URL to a Foetex-triggered alert.
"""

import os

import requests

import salling_early_radar as radar


SITE_LABELS = {
    "bilka": "BILKA",
    "foetex": "FØTEX",
}


def ignore_epoch_only_change(old, current):
    """Treat epoch_updated_at-only movement as indexing noise."""
    return False


def _site_has_live_signal(site):
    site = site or {}
    return bool(
        site.get("is_exposed")
        or int(site.get("online_count") or 0) > 0
        or int(site.get("store_count") or 0) > 0
    )


def triggering_site_key(product, detail=""):
    """Infer which Salling storefront actually caused the alert."""
    sites = (product or {}).get("sites") or {}
    detail_upper = str(detail or "").upper()

    mentioned = [
        site_key
        for site_key, label in SITE_LABELS.items()
        if label in detail_upper
    ]
    if len(mentioned) == 1 and mentioned[0] in sites:
        return mentioned[0]

    live_sites = [
        site_key
        for site_key in SITE_LABELS
        if site_key in sites and _site_has_live_signal(sites.get(site_key))
    ]
    if len(live_sites) == 1:
        return live_sites[0]

    if len(sites) == 1:
        return next(iter(sites))

    return None


def source_correct_url(product, detail=""):
    """Prefer the URL for the storefront that generated the signal."""
    sites = (product or {}).get("sites") or {}
    preferred = triggering_site_key(product, detail)

    if preferred:
        url = str((sites.get(preferred) or {}).get("url") or "").strip()
        if url:
            return url

    # Ambiguous cross-store events keep the existing deterministic fallback.
    return radar.best_url(product)


def send_source_correct_alert(title, product, detail):
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        raise RuntimeError("DISCORD_WEBHOOK_URL mangler")

    price = product.get("price")
    price_text = f"{price} kr." if price is not None else "Pris ikke oplyst"
    updated = radar.record_update_text(product)
    updated_line = f"\n🕒 Salling-record opdateret {updated}" if updated else ""
    message = (
        f"🕵️ **SALLING EARLY RADAR · {title}**\n"
        f"**{product.get('name') or 'Ukendt Pokemon-produkt'}**\n"
        f"🎯 {product.get('priority') or 'NORMAL'} · {detail}\n"
        f"💰 {price_text}\n"
        f"🆔 {product.get('id')} · SKU {product.get('sku') or '-'}\n"
        f"📦 {radar.stock_signal_text(product)}"
        f"{updated_line}\n"
        f"🔗 {source_correct_url(product, detail)}"
    )

    response = requests.post(webhook, json={"content": message}, timeout=15)
    response.raise_for_status()


# Keep timestamp-only noise suppressed and make merged Salling alerts use the
# URL for the retailer that actually triggered the signal.
radar.epoch_only_change = ignore_epoch_only_change
radar.send_alert = send_source_correct_alert


if __name__ == "__main__":
    radar.main()
