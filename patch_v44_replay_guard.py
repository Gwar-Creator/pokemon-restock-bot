from pathlib import Path

TARGET = Path("restock_bot_github.py")
MARKER = "RESTOCK_REPLAY_GUARD_V44 = True"

text = TARGET.read_text(encoding="utf-8")
if MARKER in text:
    print("V44 replay guard already applied")
    raise SystemExit(0)


def replace_once(old, new, label):
    global text
    if old not in text:
        raise RuntimeError(f"V44 patch failed: marker not found for {label}")
    text = text.replace(old, new, 1)
    print(f"V44 applied: {label}")


replace_once(
    '''# Persistent alert memory is hydrated from state before scanning starts.\n# It prevents a flapping source from repeating the same Discord alert.\nRESTOCK_ALERT_MEMORY = {}\nPRICE_ALERT_MEMORY = {}\n''',
    '''# Persistent alert memory is hydrated from state before scanning starts.\n# It prevents a flapping source from repeating the same Discord alert.\nRESTOCK_ALERT_MEMORY = {}\nPRICE_ALERT_MEMORY = {}\n# Permanent product memory prevents old products from becoming \"new\" again\n# after a parser/source temporarily drops them from the current snapshot.\nRESTOCK_SEEN_PRODUCTS = set()\n# If the main scanner has been unable to save state for a prolonged period,\n# the first successful scan is a silent recovery baseline for product events.\nRESTOCK_RECOVERY_MODE = False\n''',
    "replay guard globals",
)

replace_once(
    '''KELZ0R_STABILITY_V42 = True\nRESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60\n''',
    '''KELZ0R_STABILITY_V42 = True\nRESTOCK_REPLAY_GUARD_V44 = True\nRESTOCK_RECOVERY_GAP_SECONDS = 30 * 60\nRESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60\n''',
    "V44 marker/constants",
)

helpers = r'''

def _restock_product_fingerprint(name, url=""):
    name_text = re.sub(r"\s+", " ", str(name or "").lower()).strip()
    url_text = re.sub(r"[?#].*$", "", str(url or "").lower().strip()).rstrip("/")
    if not name_text:
        return ""
    raw = f"{name_text}|{url_text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _restock_message_fingerprint(message):
    lines = [
        line.replace("**", "").strip()
        for line in str(message or "").splitlines()
        if line.strip()
    ]
    name = lines[1] if len(lines) > 1 else ""
    url_match = re.search(r"https?://\S+", str(message or ""))
    url = url_match.group(0).rstrip(").,>") if url_match else ""
    return _restock_product_fingerprint(name, url)


def _collect_restock_seen_products(state_value):
    """Collect stable product fingerprints from current + persisted state."""
    seen = set()
    if isinstance(state_value, dict):
        saved = state_value.get("_restock_seen_products")
        if isinstance(saved, list):
            seen.update(str(value) for value in saved if value)

    def walk(value):
        if isinstance(value, dict):
            name = value.get("name")
            url = value.get("url") or value.get("product_url")
            if name:
                fingerprint = _restock_product_fingerprint(name, url or "")
                if fingerprint:
                    seen.add(fingerprint)
            for key, child in value.items():
                if str(key).startswith("_"):
                    continue
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(state_value)
    return seen

'''
replace_once(
    '''def _price_values_from_change(message):\n''',
    helpers + '''def _price_values_from_change(message):\n''',
    "seen-product helpers",
)

replace_once(
    '''def restock_alert_decision(message):\n    global RESTOCK_ALERT_MEMORY\n    RESTOCK_ALERT_MEMORY = _alert_memory_cleanup(RESTOCK_ALERT_MEMORY)\n    key, event_type = _alert_identity(message, "restock")\n    previous = RESTOCK_ALERT_MEMORY.get(key)\n    now_epoch = _now_epoch()\n\n    if event_type == "PRICE":\n        if not RESTOCK_PRICE_ALERTS_ENABLED:\n            print("RESTOCK ALERT: prisændring håndteres i priskanalerne")\n            return None\n\n        _, new_price = _price_values_from_change(message)\n        if new_price is None:\n            cooldown = PRICE_ALERT_COOLDOWN_SECONDS\n            if (\n                isinstance(previous, dict)\n                and now_epoch - safe_int(previous.get("sent_at"), 0) < cooldown\n            ):\n                return None\n        elif not _price_beats_recent_alert(previous, new_price):\n            return None\n\n        return key, {"sent_at": now_epoch, "price": new_price}\n\n    cooldown = (\n        RESTOCK_NEW_PRODUCT_COOLDOWN_SECONDS\n        if event_type in ("NEW", "PREORDER")\n        else RESTOCK_DUPLICATE_COOLDOWN_SECONDS\n    )\n    if (\n        isinstance(previous, dict)\n        and now_epoch - safe_int(previous.get("sent_at"), 0) < cooldown\n    ):\n        return None\n\n    return key, {"sent_at": now_epoch}\n''',
    '''def restock_alert_decision(message):\n    global RESTOCK_ALERT_MEMORY\n    RESTOCK_ALERT_MEMORY = _alert_memory_cleanup(RESTOCK_ALERT_MEMORY)\n    key, event_type = _alert_identity(message, "restock")\n    previous = RESTOCK_ALERT_MEMORY.get(key)\n    now_epoch = _now_epoch()\n    product_fingerprint = _restock_message_fingerprint(message)\n\n    # After a prolonged outage, do not replay accumulated product events.\n    # The current scan is still saved as the new baseline.\n    if RESTOCK_RECOVERY_MODE and event_type in ("NEW", "PREORDER", "RESTOCK"):\n        print(f"RESTOCK V44: recovery baseline undertrykker {event_type}")\n        return None\n\n    # A product that has ever existed in persisted state must never be announced\n    # as NEW/PREORDER again just because a source temporarily omitted it.\n    if (\n        event_type in ("NEW", "PREORDER")\n        and product_fingerprint\n        and product_fingerprint in RESTOCK_SEEN_PRODUCTS\n    ):\n        print("RESTOCK V44: tidligere set produkt undertrykt som nyt")\n        return None\n\n    if event_type == "PRICE":\n        if not RESTOCK_PRICE_ALERTS_ENABLED:\n            print("RESTOCK ALERT: prisændring håndteres i priskanalerne")\n            return None\n\n        _, new_price = _price_values_from_change(message)\n        if new_price is None:\n            cooldown = PRICE_ALERT_COOLDOWN_SECONDS\n            if (\n                isinstance(previous, dict)\n                and now_epoch - safe_int(previous.get("sent_at"), 0) < cooldown\n            ):\n                return None\n        elif not _price_beats_recent_alert(previous, new_price):\n            return None\n\n        return key, {"sent_at": now_epoch, "price": new_price}\n\n    cooldown = (\n        RESTOCK_NEW_PRODUCT_COOLDOWN_SECONDS\n        if event_type in ("NEW", "PREORDER")\n        else RESTOCK_DUPLICATE_COOLDOWN_SECONDS\n    )\n    if (\n        isinstance(previous, dict)\n        and now_epoch - safe_int(previous.get("sent_at"), 0) < cooldown\n    ):\n        return None\n\n    entry = {"sent_at": now_epoch}\n    if event_type in ("NEW", "PREORDER") and product_fingerprint:\n        entry["product_fp"] = product_fingerprint\n    return key, entry\n''',
    "central restock replay decision",
)

replace_once(
    '''    alert_key, alert_entry = alert_decision\n    if alert_key:\n        RESTOCK_ALERT_MEMORY[alert_key] = alert_entry\n    return True\n\n\ndef send_price_watch(message):\n''',
    '''    alert_key, alert_entry = alert_decision\n    if alert_key:\n        RESTOCK_ALERT_MEMORY[alert_key] = alert_entry\n    product_fingerprint = (alert_entry or {}).get("product_fp")\n    if product_fingerprint:\n        RESTOCK_SEEN_PRODUCTS.add(product_fingerprint)\n    return True\n\n\ndef send_price_watch(message):\n''',
    "persist successfully sent new products in memory",
)

replace_once(
    '''if isinstance(state, dict):\n    RESTOCK_ALERT_MEMORY = _alert_memory_cleanup(\n        state.get("_restock_alert_memory") or {}\n    )\n    PRICE_ALERT_MEMORY = _alert_memory_cleanup(\n        state.get("_price_alert_memory") or {}\n    )\n\n# Persist the public Elgiganten signed Algolia key between GitHub Action\n''',
    '''if isinstance(state, dict):\n    RESTOCK_ALERT_MEMORY = _alert_memory_cleanup(\n        state.get("_restock_alert_memory") or {}\n    )\n    PRICE_ALERT_MEMORY = _alert_memory_cleanup(\n        state.get("_price_alert_memory") or {}\n    )\n    RESTOCK_SEEN_PRODUCTS = _collect_restock_seen_products(state)\n    last_full_scan_epoch = safe_int(state.get("_last_full_scan_epoch"), 0)\n    if (\n        last_full_scan_epoch > 0\n        and _now_epoch() - last_full_scan_epoch > RESTOCK_RECOVERY_GAP_SECONDS\n    ):\n        RESTOCK_RECOVERY_MODE = True\n        print(\n            "RESTOCK V44: scanner-gap over 30 min; "\n            "første succesfulde run bruges som stille recovery-baseline."\n        )\n\n# Persist the public Elgiganten signed Algolia key between GitHub Action\n''',
    "hydrate seen products and recovery mode",
)

replace_once(
    '''            "_restock_alert_memory": RESTOCK_ALERT_MEMORY,\n            "_price_alert_memory": PRICE_ALERT_MEMORY,\n            "_elgiganten_key_cache": dict(ELGIGANTEN_KEY_CACHE)\n        }\n\n        save_state(\n            state\n        )\n''',
    '''            "_restock_alert_memory": RESTOCK_ALERT_MEMORY,\n            "_price_alert_memory": PRICE_ALERT_MEMORY,\n            "_elgiganten_key_cache": dict(ELGIGANTEN_KEY_CACHE)\n        }\n        RESTOCK_SEEN_PRODUCTS.update(_collect_restock_seen_products(state))\n        state["_restock_seen_products"] = sorted(RESTOCK_SEEN_PRODUCTS)\n        state["_last_full_scan_epoch"] = _now_epoch()\n\n        save_state(\n            state\n        )\n''',
    "baseline seen-product persistence",
)

replace_once(
    '''        new_state["_price_alert_memory"] = _alert_memory_cleanup(\n            PRICE_ALERT_MEMORY\n        )\n\n        save_state(\n            new_state\n        )\n''',
    '''        new_state["_price_alert_memory"] = _alert_memory_cleanup(\n            PRICE_ALERT_MEMORY\n        )\n        RESTOCK_SEEN_PRODUCTS.update(_collect_restock_seen_products(new_state))\n        new_state["_restock_seen_products"] = sorted(RESTOCK_SEEN_PRODUCTS)\n        new_state["_last_full_scan_epoch"] = _now_epoch()\n\n        save_state(\n            new_state\n        )\n''',
    "normal scan seen-product persistence",
)

TARGET.write_text(text, encoding="utf-8")
print("Applied V44: permanent seen-product memory + silent outage recovery baseline")
