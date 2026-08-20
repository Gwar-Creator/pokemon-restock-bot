from pathlib import Path


def replace_once(path, old, new, label):
    text = path.read_text(encoding="utf-8")
    if new in text:
        print(f"{label}: already applied")
        return False
    if old not in text:
        raise RuntimeError(f"V26 patch failed: marker not found for {label} in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"{label}: applied")
    return True


MAIN = Path("restock_bot_github.py")
LOCAL = Path("local_stock_watch.py")
CARDMARKET = Path("cardmarket_chase_watch.py")
PREVIEW = Path("preview_price_channels_v25.py")
AGENTS = Path("AGENTS.md")

# ---------------------------------------------------------------------------
# Main bot: keep raw state, but silence explicitly non-English card products
# everywhere users see them (Restock + Price Watch + Price History).
# Unlabelled Danish webshop titles are treated as English card products.
# ---------------------------------------------------------------------------
replace_once(
    MAIN,
    "RETAILER_CLEANUP_V25 = True\n",
    "RETAILER_CLEANUP_V25 = True\nENGLISH_ONLY_V26 = True\n",
    "main marker",
)

english_helper = '''NON_ENGLISH_CARD_MARKERS = (\n    "japansk", "japanese", "japan import",\n    "kinesisk", "chinese", "simplified chinese", "traditional chinese",\n    "koreansk", "korean",\n    "tysk", "german", "deutsch",\n    "fransk", "french",\n    "italiensk", "italian",\n    "spansk", "spanish",\n    "portugisisk", "portuguese",\n    "hollandsk", "dutch",\n    "thai", "thailand",\n    "indonesisk", "indonesian",\n)\n\n\ndef is_english_card_product(name):\n    \"\"\"Allow English/unspecified card language; block explicit foreign editions.\"\"\"\n    text = " " + re.sub(r"\\s+", " ", str(name or "").lower()) + " "\n\n    if any(marker in text for marker in NON_ENGLISH_CARD_MARKERS):\n        return False\n\n    # Only bracketed/separated short codes are treated as language markers,\n    # avoiding false positives from ordinary Danish words.\n    if re.search(\n        r"(?:\\(|\\[|\\{|\\-|/)\\s*(?:jp|jpn|cn|chs|cht|kr|kor)\\s*(?:\\)|\\]|\\}|\\-|/)",\n        text,\n        flags=re.IGNORECASE,\n    ):\n        return False\n\n    return True\n\n\n'''
replace_once(
    MAIN,
    "# ============================================================\n# RESTOCK ALERT FILTER\n# ============================================================\n\n",
    english_helper + "# ============================================================\n# RESTOCK ALERT FILTER\n# ============================================================\n\n",
    "main English helper",
)
replace_once(
    MAIN,
    '''    name = str((product or {}).get("name", "")).lower()\n    game = game_override or (product or {}).get("game")\n\n    if is_low_signal_accessory_name(name):\n''',
    '''    name = str((product or {}).get("name", "")).lower()\n    game = game_override or (product or {}).get("game")\n\n    if not is_english_card_product(name):\n        return False\n\n    if is_low_signal_accessory_name(name):\n''',
    "restock English-only gate",
)
replace_once(
    MAIN,
    '''def get_price_watch_type(name, game):\n    text = (name or "").lower()\n\n    if is_low_signal_accessory_name(text):\n''',
    '''def get_price_watch_type(name, game):\n    text = (name or "").lower()\n\n    if not is_english_card_product(text):\n        return None\n\n    if is_low_signal_accessory_name(text):\n''',
    "price English-only gate",
)

# ---------------------------------------------------------------------------
# Local Stock Watch: same language rule before Click & Collect work.
# ---------------------------------------------------------------------------
local_helper = '''\nNON_ENGLISH_CARD_MARKERS = (\n    "japansk", "japanese", "japan import",\n    "kinesisk", "chinese", "simplified chinese", "traditional chinese",\n    "koreansk", "korean", "tysk", "german", "deutsch",\n    "fransk", "french", "italiensk", "italian", "spansk", "spanish",\n    "portugisisk", "portuguese", "hollandsk", "dutch",\n    "thai", "thailand", "indonesisk", "indonesian",\n)\n\ndef is_english_card_product(name):\n    text = " " + re.sub(r"\\s+", " ", str(name or "").lower()) + " "\n    return not any(marker in text for marker in NON_ENGLISH_CARD_MARKERS)\n'''
replace_once(
    LOCAL,
    'TARGET_STORE_MARKERS = ("kolding", "fredericia", "vejen", "brørup", "brorup", "esbjerg")\n',
    'TARGET_STORE_MARKERS = ("kolding", "fredericia", "vejen", "brørup", "brorup", "esbjerg")\n' + local_helper,
    "local English helper",
)
replace_once(
    LOCAL,
    '''    for product in hits:\n        if not is_pokemon_hit(product):\n            continue\n        product_type = pokemon_product_type(product.get("name"))\n''',
    '''    for product in hits:\n        if not is_pokemon_hit(product):\n            continue\n        if not is_english_card_product(product.get("name")):\n            continue\n        product_type = pokemon_product_type(product.get("name"))\n''',
    "local English-only gate",
)

# ---------------------------------------------------------------------------
# Cardmarket retail-opportunity matching already blocks foreign products;
# make the list complete enough for the new English-only project rule.
# ---------------------------------------------------------------------------
replace_once(
    CARDMARKET,
    '''FOREIGN_MARKERS = {\n    "japansk", "japanese", "kinesisk", "chinese", "korean", "koreansk",\n    "german", "tysk", "french", "fransk", "spanish", "spansk", "italian",\n}\n''',
    '''FOREIGN_MARKERS = {\n    "japansk", "japanese", "kinesisk", "chinese", "korean", "koreansk",\n    "german", "tysk", "deutsch", "french", "fransk", "spanish", "spansk",\n    "italian", "italiensk", "portuguese", "portugisisk", "dutch", "hollandsk",\n    "thai", "indonesian", "indonesisk", "simplified", "traditional",\n}\n''',
    "Cardmarket English-only markers",
)

# ---------------------------------------------------------------------------
# Manual preview: mirror production language rule without importing main bot.
# ---------------------------------------------------------------------------
preview_markers = '''NON_ENGLISH_CARD_MARKERS = (\n    "japansk", "japanese", "japan import",\n    "kinesisk", "chinese", "simplified chinese", "traditional chinese",\n    "koreansk", "korean", "tysk", "german", "deutsch",\n    "fransk", "french", "italiensk", "italian", "spansk", "spanish",\n    "portugisisk", "portuguese", "hollandsk", "dutch",\n    "thai", "thailand", "indonesisk", "indonesian",\n)\n\ndef is_english_card_product(name):\n    text = " " + re.sub(r"\\s+", " ", str(name or "").lower()) + " "\n    return not any(marker in text for marker in NON_ENGLISH_CARD_MARKERS)\n\n'''
replace_once(
    PREVIEW,
    'ACCESSORY_MARKERS = (\n',
    preview_markers + 'ACCESSORY_MARKERS = (\n',
    "preview English helper",
)
replace_once(
    PREVIEW,
    '''def get_price_watch_type(name, game):\n    text = str(name or "").lower()\n    if is_low_signal_accessory_name(text):\n''',
    '''def get_price_watch_type(name, game):\n    text = str(name or "").lower()\n    if not is_english_card_product(text):\n        return None\n    if is_low_signal_accessory_name(text):\n''',
    "preview English-only gate",
)

# ---------------------------------------------------------------------------
# Project memory: persist the temporary product-language preference and current
# Proshop/Elgiganten architecture so later chats do not re-open old decisions.
# ---------------------------------------------------------------------------
replace_once(
    AGENTS,
    '## Relevans for restock\n\n',
    '## Relevans for restock\n\n**Aktuel sprogregel (2026-08-20): Kun engelske kortprodukter er brugerrelevante.** Produkter, der eksplicit er mærket japansk, kinesisk, koreansk, tysk, fransk, italiensk, spansk, portugisisk, hollandsk, thai eller indonesisk, må gerne bevares i rå state, men skal ikke udløse Restock-, Local Stock-, Price Watch- eller Price History-signaler. Produkter uden eksplicit sprogmærkning behandles som engelske.\n\n',
    "AGENTS English-only decision",
)

print("Applied V26: English-only user-facing card-product signals")
