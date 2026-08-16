from pathlib import Path

BOT = Path("restock_bot_github.py")
PATCH = Path("patch_v21_cleanup_price_history_log.py")

text = BOT.read_text(encoding="utf-8")

old = '''    print(\n        f"PRICE HISTORY V1: {len(active_keys)} aktive produkter | "\n        f"{len(new_lows)} nye historiske lows | "\n        f"Cardmarket {'aktiv' if cardmarket_enabled() else 'ikke konfigureret'}"\n    )\n'''
new = '''    print(\n        f"PRICE HISTORY V1: {len(active_keys)} aktive produkter | "\n        f"{len(new_lows)} nye historiske lows"\n    )\n'''

if old not in text:
    raise RuntimeError("Could not find old Price History status line")

text = text.replace(old, new, 1)
BOT.write_text(text, encoding="utf-8")
PATCH.unlink(missing_ok=True)
print("V2.1 applied: removed obsolete official Cardmarket status from Price History log.")
