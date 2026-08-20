from pathlib import Path
import re

PATH = Path("restock_bot_github.py")
text = PATH.read_text(encoding="utf-8")

if "RETAILER_CLEANUP_V25 = True" in text:
    print("V25 retailer cleanup already applied")
    raise SystemExit(0)


def replace_once(old, new, label):
    global text
    if old not in text:
        raise RuntimeError(f"V25 patch failed: marker not found for {label}")
    text = text.replace(old, new, 1)


# Marker + remove Elgiganten from active source minimums.
replace_once(
    'PRICE_SIGNAL_CLEANUP_V23 = True\n',
    'PRICE_SIGNAL_CLEANUP_V23 = True\nRETAILER_CLEANUP_V25 = True\n',
    'V25 marker',
)
replace_once(
    '    "elgiganten": 5,\n',
    '',
    'Elgiganten source minimum',
)

# Proshop Reader is now the preferred transport. Force a fresh browser render.
replace_once(
    '''        headers={
            "Accept": "text/plain, text/markdown;q=0.9, */*;q=0.5",
            "User-Agent": "Pokemon-Lorcana-MasterBot/2.0 ProshopFallback",
        },
''',
    '''        headers={
            "Accept": "text/plain, text/markdown;q=0.9, */*;q=0.5",
            "User-Agent": "Pokemon-Lorcana-MasterBot/2.5 ProshopPrimary",
            "x-no-cache": "true",
            "x-engine": "browser",
        },
''',
    'Proshop Reader headers',
)
replace_once(
    '        f"PROSHOP: bruger Jina Reader fallback "\n',
    '        f"PROSHOP: bruger Jina Reader primary "\n',
    'Proshop log label',
)

# Replace Proshop selector: Reader primary, direct routes only as fallback.
pattern = re.compile(
    r'def get_proshop_products\(\):\n.*?\n\n# =========================================================\n# BR FRONTEND CONFIG',
    re.DOTALL,
)
replacement = '''def get_proshop_products():
    errors = []

    # GitHub-hosted requests are consistently blocked with HTTP 403, while
    # Jina/browser rendering exposes the public category reliably. Treat it
    # as the production transport instead of pretending it is an emergency
    # fallback.
    try:
        products = get_proshop_products_via_reader()
        if products:
            return products
        errors.append("Jina Reader: 0 produkter")
    except Exception as error:
        errors.append(f"Jina Reader: {error}")

    # Safety fallback only: if Reader is temporarily unavailable, try the two
    # public Proshop routes once each. No retry storm.
    headers = {
        **BROWSER_HEADERS,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "da-DK,da;q=0.9,en-US;q=0.7,en;q=0.6",
        "Referer": PROSHOP_BASE + "/",
        "Upgrade-Insecure-Requests": "1",
    }
    urls = [
        (PROSHOP_URL, "pokemon-kort"),
        (PROSHOP_BASE + "/Pokemon", "Pokemon fallback"),
    ]

    if curl_requests is not None:
        try:
            session = curl_requests.Session(impersonate="chrome")
            for url, label in urls:
                try:
                    response = session.get(url, headers=headers, timeout=25)
                except Exception as error:
                    errors.append(f"{label}: {error}")
                    continue
                if response.status_code != 200:
                    errors.append(f"{label}: HTTP {response.status_code}")
                    continue
                products = _parse_proshop_products(response)
                if products:
                    print(
                        f"PROSHOP: Reader utilgængelig; direct fallback {label} "
                        f"gav {len(products)} TCG-produkter"
                    )
                    return products
                errors.append(f"{label}: 200 men ingen TCG-produkter parsed")
        except Exception as error:
            errors.append(f"curl_cffi: {error}")

    short = "; ".join(errors[-5:]) if errors else "ukendt fejl"
    raise RuntimeError(f"Proshop utilgængelig ({short})")


# =========================================================
# BR FRONTEND CONFIG'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise RuntimeError("V25 patch failed: Proshop function block not found")

# Elgiganten is retired from Price Watch/History candidate plumbing.
replace_once(
    '        "coolshop", "proshop", "br", "bilka", "foetex",\n        "elgiganten", "epicpanda", "steffeno", "nextlevel"\n',
    '        "coolshop", "proshop", "br", "bilka", "foetex",\n        "epicpanda", "steffeno", "nextlevel"\n',
    'price raw source set',
)
replace_once(
    '    pokemon_only = {"proshop", "br", "bilka", "foetex", "elgiganten", "steffeno"}\n',
    '    pokemon_only = {"proshop", "br", "bilka", "foetex", "steffeno"}\n',
    'price pokemon-only set',
)

elg_price_block = '''    add_products(
        "ELGIGANTEN",
        "elgiganten",
        current_state.get("elgiganten", {}),
        "POKÉMON"
    )

'''
replace_once(elg_price_block, '', 'Elgiganten price candidate block')

# Replace active Elgiganten network scan with a preserved, explicit retired state.
pattern = re.compile(
    r'''        # -------------------------\n        # ELGIGANTEN\n        # -------------------------\n\n.*?\n        # -------------------------\n        # SHOPIFY-WEBSHOPS''',
    re.DOTALL,
)
replacement = '''        # -------------------------
        # ELGIGANTEN - RETIRED V25
        # -------------------------

        # Public product pages, signed Algolia and the anonymous orchestrator
        # are all blocked/rate-limited from the runner. Preserve historical
        # data, but make no network calls and never expose stale Elgiganten
        # prices/stock as live signals.
        old_elgiganten = state.get("elgiganten", {})
        new_state["elgiganten"] = old_elgiganten
        _source_health_update(
            new_state,
            "elgiganten",
            status="retired",
            consecutive_failures=0,
            last_error="Retired V25: no reliable public live-stock path",
            observed_count=len(old_elgiganten) if isinstance(old_elgiganten, dict) else 0,
        )
        print(
            "ELGIGANTEN: retired fra aktiv scanning; historisk state bevares "
            "og bruges ikke i Price Watch/History."
        )

        # -------------------------
        # SHOPIFY-WEBSHOPS'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise RuntimeError("V25 patch failed: active Elgiganten main block not found")

PATH.write_text(text, encoding="utf-8")
print("Applied V25: Proshop Reader primary; Elgiganten retired from active signals")
