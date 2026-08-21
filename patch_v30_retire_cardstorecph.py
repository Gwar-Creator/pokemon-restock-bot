from pathlib import Path
import re

PATH = Path("restock_bot_github.py")
text = PATH.read_text(encoding="utf-8")

MARKER = "CARDSTORECPH_RETIRED_V30 = True"

if MARKER in text:
    print("V30 CardstoreCPH retirement already applied")
    raise SystemExit(0)


def replace_once(old, new, label):
    global text
    if old not in text:
        raise RuntimeError(f"V30 patch failed: marker not found for {label}")
    text = text.replace(old, new, 1)


replace_once(
    '''WAVE1_RETAILERS_V28 = True
WAVE2_RETAILERS_V29 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    '''WAVE1_RETAILERS_V28 = True
WAVE2_RETAILERS_V29 = True
CARDSTORECPH_RETIRED_V30 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    "V30 marker",
)

# CardstoreCPH is overwhelmingly singles and produced zero relevant sealed
# products. It is intentionally retired rather than weakening sealed filters.
text = text.replace('    "cardstorecph": 3,\n', '', 1)

replace_once(
    '''        f"+ CardsDirect + Baltzer Games + TCG Shoppen + Pokemons.dk "
        f"+ Pocket Monster + CardstoreCPH + Nostalgic + &Cards + Pokecards.dk "
''',
    '''        f"+ CardsDirect + Baltzer Games + TCG Shoppen + Pokemons.dk "
        f"+ Pocket Monster + Nostalgic + &Cards + Pokecards.dk "
''',
    "startup source list",
)

# Remove CardstoreCPH from Price Watch source plumbing. Historical state is
# left untouched, but the shop can no longer be considered a fresh source.
text = text.replace(
    '        "epicpanda", "steffeno", "nextlevel", "cardstorecph"\n',
    '        "epicpanda", "steffeno", "nextlevel"\n',
    1,
)

cardstore_candidate = '''\n    add_products(\n        "CARDSTORECPH",\n        "cardstorecph",\n        current_state.get("cardstorecph", {})\n    )\n'''
text = text.replace(cardstore_candidate, '', 1)

pattern = re.compile(
    r'''\n        # -------------------------\n        # CARDSTORECPH\n        # -------------------------\n\n        try:\n.*?\n        except Exception as error:\n            print\("CARDSTORECPH fejl:", error\)\n''',
    re.DOTALL,
)
replacement = '''
        # -------------------------
        # CARDSTORECPH - RETIRED
        # -------------------------

        old_cardstore = state.get("cardstorecph", {})
        new_state["cardstorecph"] = old_cardstore
        _source_health_update(
            new_state,
            "cardstorecph",
            status="retired",
            consecutive_failures=0,
            last_error=(
                "Retired V30: shoppen er primært enkeltkort og gav 0 "
                "relevante sealed produkter"
            ),
            observed_count=(
                len(old_cardstore)
                if isinstance(old_cardstore, dict)
                else 0
            ),
        )
        print(
            "CARDSTORECPH: retired fra aktiv scanning; primært enkeltkort, "
            "historisk state bevares."
        )
'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise RuntimeError("V30 patch failed: active CardstoreCPH main block not found")

PATH.write_text(text, encoding="utf-8")
print("Applied V30: CardstoreCPH retired, historical state preserved")
