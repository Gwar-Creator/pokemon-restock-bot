from pathlib import Path

TARGET = Path("local_stock_watch.py")
MARKER = "SALLING_DISCOVERY_V45 = True"

text = TARGET.read_text(encoding="utf-8")
if MARKER in text:
    print("V45 Salling discovery already applied")
    raise SystemExit(0)


def replace_once(old, new, label):
    global text
    if old not in text:
        raise RuntimeError(f"V45 patch failed: marker not found for {label}")
    text = text.replace(old, new, 1)
    print(f"V45 applied: {label}")


replace_once(
    '''WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()\nSTATE_FILE = "local_stock_state_v1.json"\n''',
    '''WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()\nSTATE_FILE = "local_stock_state_v1.json"\nSALLING_DISCOVERY_V45 = True\n''',
    "V45 marker",
)

helpers = r'''

def canonical_salling_product_key(product):
    """Stable identity shared across BR/Bilka/Foetex for discovery de-duplication."""
    sku = str((product or {}).get("sku") or "").strip().upper()
    if sku:
        return f"sku:{sku}"
    product_id = str((product or {}).get("id") or "").strip()
    return f"id:{product_id}" if product_id else ""


def send_discovery_alert(products):
    """Send one clearly separated PRE-PUBLISH discovery alert per Salling SKU."""
    if not WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL mangler")
    if not products:
        return

    site_order = {"BR": 0, "BILKA": 1, "FØTEX": 2}
    products = sorted(
        products,
        key=lambda product: site_order.get(product.get("site"), 99),
    )
    representative = products[0]
    series = short_series_name(representative.get("series"))
    product_line = (
        f"**{series} · {representative['type']}**"
        if series
        else f"**{representative['name']} · {representative['type']}**"
    )

    lines = [
        "👀 **NY SKJULT VARE — ikke en lageralarm**",
        product_line,
    ]
    for product in products:
        store_count = max(0, safe_int(product.get("store_count"), 0))
        lines.append(
            f"• **{product['site']}** · {format_price(product.get('price'))} · "
            f"{store_count} butikker med registreret lager"
        )
    lines.append(f"🔎 SKU: `{representative['sku']}`")
    lines.append(
        "⏭️ Discovery sendes kun én gang. Næste signal kommer først ved "
        "lokal 0 → positiv lagerstatus."
    )

    payload = {
        "username": "MasterBot",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": "👀 [POKÉMON] SALLING PRE-PUBLISH DISCOVERY",
                "description": "\n".join(lines)[:4096],
                "color": 0x5865F2,
                "footer": {
                    "text": "MasterBot · Salling Discovery · NY SKJULT VARE"
                },
            }
        ],
    }
    response = requests.post(WEBHOOK_URL, json=payload, timeout=20)
    response.raise_for_status()

'''
replace_once(
    '''def send_local_alert(product, transitions):\n''',
    helpers + '''def send_local_alert(product, transitions):\n''',
    "discovery helpers and Discord format",
)

replace_once(
    '''    total_errors = 0\n    fresh_keys = set()\n\n    for site_key in ("br", "bilka", "foetex"):\n        site_had_baseline = any(\n            key.startswith(f"{site_key}:")\n            for key in old_products\n        )\n''',
    '''    total_errors = 0\n    fresh_keys = set()\n    all_observations = {}\n    stock_alerted_products = set()\n    known_product_keys = {\n        canonical_salling_product_key(product)\n        for product in old_products.values()\n        if canonical_salling_product_key(product)\n    }\n    site_baselines = {\n        site_key: any(\n            key.startswith(f"{site_key}:")\n            for key in old_products\n        )\n        for site_key in ("br", "bilka", "foetex")\n    }\n\n    for site_key in ("br", "bilka", "foetex"):\n        site_had_baseline = site_baselines[site_key]\n''',
    "global discovery de-duplication state",
)

replace_once(
    '''        total_errors += errors\n        next_products.update(observations)\n        fresh_keys.update(observations.keys())\n''',
    '''        total_errors += errors\n        next_products.update(observations)\n        fresh_keys.update(observations.keys())\n        all_observations.update(observations)\n''',
    "collect observations across Salling chains",
)

replace_once(
    '''            if transitions:\n                send_local_alert(product, transitions)\n\n    next_state = {\n''',
    '''            if transitions:\n                send_local_alert(product, transitions)\n                canonical_key = canonical_salling_product_key(product)\n                if canonical_key:\n                    stock_alerted_products.add(canonical_key)\n\n    # Discovery is deliberately separate from stock alerts:\n    # - only genuinely new Salling identities are eligible;\n    # - BR/Bilka/Foetex sightings of the same SKU collapse to one Discord post;\n    # - if local stock already triggered, the weaker discovery alert is suppressed.\n    discovery_groups = {}\n    if baseline_complete:\n        for observation_key, product in all_observations.items():\n            if product.get("visibility") != "PRE-PUBLISH":\n                continue\n            canonical_key = canonical_salling_product_key(product)\n            if (\n                not canonical_key\n                or canonical_key in known_product_keys\n                or canonical_key in stock_alerted_products\n            ):\n                continue\n            site_key = observation_key.split(":", 1)[0]\n            if not site_baselines.get(site_key, False):\n                continue\n            discovery_groups.setdefault(canonical_key, []).append(product)\n\n        for products in discovery_groups.values():\n            send_discovery_alert(products)\n\n    discovery_count = len(discovery_groups)\n\n    next_state = {\n''',
    "one-time grouped PRE-PUBLISH discovery alerts",
)

replace_once(
    '''        print(\n            f"LOCAL STOCK: scan færdig | {len(fresh_keys)} "\n            f"friske produktobservationer | {total_errors} fejl"\n        )\n''',
    '''        print(\n            f"LOCAL STOCK: scan færdig | {len(fresh_keys)} "\n            f"friske produktobservationer | {discovery_count} nye "\n            f"PRE-PUBLISH discoveries | {total_errors} fejl"\n        )\n''',
    "discovery run summary",
)

TARGET.write_text(text, encoding="utf-8")
print(
    "Applied V45: one-time grouped Salling PRE-PUBLISH discovery alerts "
    "+ stock-alert suppression"
)
