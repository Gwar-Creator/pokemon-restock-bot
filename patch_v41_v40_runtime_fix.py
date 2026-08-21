from pathlib import Path

PATH = Path("restock_bot_github.py")
text = PATH.read_text(encoding="utf-8")

MARKER = "V40_RUNTIME_FIX_V41 = True"

if MARKER in text:
    print("V41 V40 runtime fix already applied")
    raise SystemExit(0)

if "MATCHING_OPPORTUNITY_V40 = True" not in text:
    raise RuntimeError("V41 requires V40 to be applied first")

old = '''import hashlib
import unicodedata

from bs4 import BeautifulSoup
'''
new = '''import hashlib
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup
'''
if old not in text and "from pathlib import Path" not in text:
    raise RuntimeError("V41 could not locate import block")
if "from pathlib import Path" not in text:
    text = text.replace(old, new, 1)

text = text.replace(
    '''MATCHING_OPPORTUNITY_V40 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    '''MATCHING_OPPORTUNITY_V40 = True
V40_RUNTIME_FIX_V41 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    1,
)

PATH.write_text(text, encoding="utf-8")
print("Applied V41: pathlib import for V40 matching audit output")
