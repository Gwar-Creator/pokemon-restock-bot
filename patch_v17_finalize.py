from pathlib import Path

BOT = Path("restock_bot_github.py")
PATCH = Path("patch_v17_finalize.py")

text = BOT.read_text(encoding="utf-8")

text = text.replace(
    'print("PRICE WATCH V3 baseline oprettet uden ændringsalerts.")',
    'print("PRICE WATCH V4 baseline oprettet uden ændringsalerts.")',
    1,
)

text = text.replace(
    '''    elif previous_version < 3:
        print("PRICE WATCH V3 anti-flap aktiveret uden overgangsalerts.")
''',
    '''    elif previous_version < 4:
        print("PRICE WATCH V4 source-confirmed anti-flap aktiveret uden overgangsalerts.")
''',
    1,
)

old_return = '''    return {
        "version": 3,
        "products": next_products,
        "last_daily_date": last_daily_date
    }
'''
new_return = '''    return {
        "version": 4,
        "products": next_products,
        "last_daily_date": last_daily_date
    }
'''

if old_return in text:
    text = text.replace(old_return, new_return, 1)
elif '"version": 4,' not in text:
    raise RuntimeError("Could not migrate Price Watch state version to V4")

if "def build_price_watch_source_observations(" not in text:
    raise RuntimeError("V4 source-confirmed helper was not applied")

if "and previous_version >= 4" not in text:
    raise RuntimeError("V4 change gate was not applied")

BOT.write_text(text, encoding="utf-8")
PATCH.unlink(missing_ok=True)
print("V1.7 finalized: Price Watch state migrated to V4.")
