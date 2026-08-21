from pathlib import Path
import re

PATH = Path("restock_bot_github.py")
text = PATH.read_text(encoding="utf-8")

MARKER = "PRICE_HISTORY_COMPACT_V27 = True"

if MARKER in text:
    print("V27 compact Price History already applied")
    raise SystemExit(0)


def replace_once(old, new, label):
    global text
    if old not in text:
        raise RuntimeError(f"V27 patch failed: marker not found for {label}")
    text = text.replace(old, new, 1)


# Keep a durable marker in the production scanner so the patch is idempotent.
replace_once(
    '''RETAILER_CLEANUP_V25 = True
ENGLISH_ONLY_V26 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    '''RETAILER_CLEANUP_V25 = True
ENGLISH_ONLY_V26 = True
PRICE_HISTORY_COMPACT_V27 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    "V27 marker",
)

# Price History is a daily dashboard. Historical lows are still recorded in
# state, but they must not create one Discord message per product. Price Watch
# remains responsible for meaningful intraday price alerts. The daily Price
# History digest already caps output at PRICE_HISTORY_DAILY_MAX_SIGNALS_TOTAL.
pattern = re.compile(
    r'''\n    if not first_run and PRICE_HISTORY_WEBHOOK_URL:\n.*?\n    if daily_due:\n''',
    re.DOTALL,
)
replacement = '''
    # Individual historical-low alerts are intentionally suppressed.
    # New lows stay in state and remain eligible for the next compact daily
    # Price History digest (max 3 total signals).

    if daily_due:
'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise RuntimeError(
        "V27 patch failed: individual Price History new-low block not found"
    )

PATH.write_text(text, encoding="utf-8")
print("Applied V27 compact Price History: no per-product new-low Discord spam")
