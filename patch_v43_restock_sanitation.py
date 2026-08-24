from pathlib import Path

TARGET = Path("restock_bot_github.py")
MARKER = "# V43_RESTOCK_SANITATION"

needle = '''    game = game_override or (product or {}).get("game")\n\n'''

insertion = '''    game = game_override or (product or {}).get("game")\n\n    # V43_RESTOCK_SANITATION\n    # Keep the 5-minute Discord channel focused on useful sealed restocks.\n    # Products remain in state; this only suppresses low-signal Discord alerts.\n    if game == "POKÉMON":\n        padded_name = " " + re.sub(r"\\s+", " ", name).strip() + " "\n\n        core_booster = any(\n            marker in padded_name\n            for marker in (" booster bundle ", " booster box ", " booster display ")\n        )\n        is_etb = (\n            " elite trainer box " in padded_name\n            or bool(re.search(r"\\betb\\b", padded_name))\n        )\n        is_single_booster = any(\n            marker in padded_name\n            for marker in (" booster pack ", " sleeved booster ", " sleeve booster ")\n        ) or (\n            " booster " in padded_name\n            and not core_booster\n            and not is_etb\n            and " collection " not in padded_name\n        )\n\n        # Chaos Rising / Pitch Black are abundant enough that loose packs and\n        # ETBs add noise. Bundles, displays/boxes and collections still pass.\n        if any(set_name in padded_name for set_name in (" chaos rising ", " pitch black ")):\n            if is_etb or is_single_booster:\n                return False\n\n        # Pure accessories do not belong in the restock channel. Do not block\n        # official collection products that happen to include a binder/playmat.\n        accessory_markers = (\n            " portfolio ",\n            " penalhus ",\n            " pencil case ",\n            " card sleeves ",\n            " card sleeve ",\n            " deck sleeves ",\n            " deck protector ",\n            " deck box ",\n            " toploader ",\n            " top loader ",\n            " storage box ",\n            " card album ",\n        )\n        if any(marker in padded_name for marker in accessory_markers):\n            return False\n        if " playmat " in padded_name and " collection " not in padded_name:\n            return False\n        if " binder " in padded_name and " collection " not in padded_name:\n            return False\n\n'''

text = TARGET.read_text(encoding="utf-8")
if MARKER in text:
    print("V43 restock sanitation already applied")
    raise SystemExit(0)
if needle not in text:
    raise RuntimeError("Could not find restock_alert_allowed insertion point")
text = text.replace(needle, insertion, 1)
TARGET.write_text(text, encoding="utf-8")
print("Applied V43 restock sanitation")
