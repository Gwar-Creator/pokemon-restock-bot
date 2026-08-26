from pathlib import Path

RESTOCK = Path("restock_bot_github.py")
LOCAL = Path("local_stock_watch.py")

IMPORT_LINE = "from alert_policy import abundant_set_signal_allowed\n"
RESTOCK_MARKER = "# V46_UNIFIED_ABUNDANT_SET_POLICY"
LOCAL_MARKER = "# V46_UNIFIED_ABUNDANT_SET_POLICY"


def patch_restock():
    source = RESTOCK.read_text(encoding="utf-8")
    changed = False

    if IMPORT_LINE not in source:
        anchor = "import unicodedata\n"
        if anchor not in source:
            raise RuntimeError("V46: restock import-anchor mangler")
        source = source.replace(anchor, anchor + IMPORT_LINE, 1)
        changed = True

    if RESTOCK_MARKER not in source:
        anchor = (
            '    game = game_override or (product or {}).get("game")\n\n'
            '    # V43_RESTOCK_SANITATION\n'
        )
        replacement = (
            '    game = game_override or (product or {}).get("game")\n\n'
            '    # V46_UNIFIED_ABUNDANT_SET_POLICY\n'
            '    # Chaos Rising / Pitch Black low-signal formats stay in state,\n'
            '    # but may not create Restock/HOT/Early-Radar Discord alerts.\n'
            '    if game == "POKÉMON" and not abundant_set_signal_allowed(\n'
            '        name,\n'
            '        (product or {}).get("series"),\n'
            '    ):\n'
            '        return False\n\n'
            '    # V43_RESTOCK_SANITATION\n'
        )
        if anchor not in source:
            raise RuntimeError("V46: restock policy-anchor mangler")
        source = source.replace(anchor, replacement, 1)
        changed = True

    if changed:
        RESTOCK.write_text(source, encoding="utf-8")
        print("V46: restock policy applied")
    else:
        print("V46: restock policy already applied")


def patch_local_stock():
    source = LOCAL.read_text(encoding="utf-8")
    changed = False

    if IMPORT_LINE not in source:
        anchor = "from bs4 import BeautifulSoup\n"
        if anchor not in source:
            raise RuntimeError("V46: local-stock import-anchor mangler")
        source = source.replace(anchor, anchor + IMPORT_LINE, 1)
        changed = True

    discovery_guard = (
        "def send_discovery_alert(products):\n"
        "    \"\"\"Send one clearly separated PRE-PUBLISH discovery alert per Salling SKU.\"\"\"\n"
        "    # V46_UNIFIED_ABUNDANT_SET_POLICY\n"
        "    products = [\n"
        "        product for product in products\n"
        "        if abundant_set_signal_allowed(\n"
        "            product.get(\"name\"),\n"
        "            product.get(\"series\"),\n"
        "        )\n"
        "    ]\n"
    )
    if "def send_discovery_alert(products):\n    \"\"\"Send one clearly separated PRE-PUBLISH discovery alert per Salling SKU.\"\"\"\n    # V46_UNIFIED_ABUNDANT_SET_POLICY" not in source:
        anchor = (
            "def send_discovery_alert(products):\n"
            "    \"\"\"Send one clearly separated PRE-PUBLISH discovery alert per Salling SKU.\"\"\"\n"
        )
        if anchor not in source:
            raise RuntimeError("V46: discovery-anchor mangler")
        source = source.replace(anchor, discovery_guard, 1)
        changed = True

    local_guard_marker = "def send_local_alert(product, transitions):\n    # V46_UNIFIED_ABUNDANT_SET_POLICY"
    if local_guard_marker not in source:
        anchor = "def send_local_alert(product, transitions):\n"
        replacement = (
            "def send_local_alert(product, transitions):\n"
            "    # V46_UNIFIED_ABUNDANT_SET_POLICY\n"
            "    if not abundant_set_signal_allowed(\n"
            "        product.get(\"name\"),\n"
            "        product.get(\"series\"),\n"
            "    ):\n"
            "        return\n"
        )
        if anchor not in source:
            raise RuntimeError("V46: local-alert-anchor mangler")
        source = source.replace(anchor, replacement, 1)
        changed = True

    if changed:
        LOCAL.write_text(source, encoding="utf-8")
        print("V46: local-stock policy applied")
    else:
        print("V46: local-stock policy already applied")


def main():
    patch_restock()
    patch_local_stock()


if __name__ == "__main__":
    main()
