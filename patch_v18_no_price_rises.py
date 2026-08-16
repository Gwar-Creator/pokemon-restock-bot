from pathlib import Path

BOT = Path("restock_bot_github.py")
PATCH = Path("patch_v18_no_price_rises.py")

text = BOT.read_text(encoding="utf-8")

anchor = '''    new_price = float(\n        best["price"]\n    )\n\n    old_shops = old_entry.get(\n'''
replacement = '''    new_price = float(\n        best["price"]\n    )\n\n    # Price Watch is action-oriented: price increases are still persisted\n    # by process_price_watch, but they must never create a Discord alert.\n    # Price History/Excel keeps the upward movement for context.\n    if new_price > old_price + 0.005:\n        return\n\n    old_shops = old_entry.get(\n'''

if replacement not in text:
    if anchor not in text:
        raise RuntimeError("Could not find send_price_watch_change price anchor")
    text = text.replace(anchor, replacement, 1)

# Defensive cleanup: after the early return above, this branch is unreachable.
# Keep the function message vocabulary focused on actionable events.
text = text.replace(
    '''    if new_price < old_price - 0.005:\n        headline = "🔥 **BEDRE PRIS FUNDET**"\n    elif new_price > old_price + 0.005:\n        headline = "📈 **BEDSTE PRIS ÆNDRET**"\n    else:\n        headline = "🔄 **BILLIGSTE BUTIK ÆNDRET**"\n''',
    '''    if new_price < old_price - 0.005:\n        headline = "🔥 **BEDRE PRIS FUNDET**"\n    else:\n        headline = "🔄 **BILLIGSTE BUTIK ÆNDRET**"\n''',
    1,
)

BOT.write_text(text, encoding="utf-8")
PATCH.unlink(missing_ok=True)
print("V1.8 applied: Price Watch no longer alerts on price increases.")
