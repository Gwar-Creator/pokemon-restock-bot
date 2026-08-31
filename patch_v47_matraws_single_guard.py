from pathlib import Path

RESTOCK = Path("restock_bot_github.py")
AGENTS = Path("AGENTS.md")

GUARD_MARKER = "# V47_MATRAWS_SINGLE_ALERT_GUARD"


def patch_restock():
    source = RESTOCK.read_text(encoding="utf-8")
    changed = False

    helper = '''# V47_MATRAWS_SINGLE_ALERT_GUARD
def is_matraws_single_alert_product(product):
    """Recognize Matraws single-card naming without removing products from state."""
    product = product or {}
    url = str(product.get("url", "")).lower()

    if "matraws.dk/" not in url:
        return False

    name = str(product.get("name", "")).strip()
    if " - " not in name:
        return False

    # Matraws singles end in a bracketed card number/code, e.g. [CLC-009]
    # or [7]. Sealed products do not use this per-card title convention.
    match = re.search(
        r"\\[([a-z0-9]{1,10}(?:[-/][a-z0-9]{1,10}){0,2})\\]\\s*$",
        name,
        flags=re.IGNORECASE,
    )
    if not match:
        return False

    return bool(re.search(r"\\d", match.group(1)))


'''

    if GUARD_MARKER not in source:
        anchor = (
            "# ============================================================\n"
            "# RESTOCK ALERT FILTER\n"
            "# ============================================================\n\n"
        )
        if anchor not in source:
            raise RuntimeError("V47: restock alert filter-anchor mangler")
        source = source.replace(anchor, anchor + helper, 1)
        changed = True

    guard_call = (
        '    if is_matraws_single_alert_product(product):\n'
        '        return False\n\n'
    )
    call_marker = (
        '    game = game_override or (product or {}).get("game")\n\n'
        '    if is_matraws_single_alert_product(product):\n'
    )
    if call_marker not in source:
        anchor = '    game = game_override or (product or {}).get("game")\n\n'
        if anchor not in source:
            raise RuntimeError("V47: restock_alert_allowed game-anchor mangler")
        source = source.replace(anchor, anchor + guard_call, 1)
        changed = True

    if changed:
        RESTOCK.write_text(source, encoding="utf-8")
        print("V47: Matraws single-card alert guard applied")
    else:
        print("V47: Matraws single-card alert guard already applied")


def patch_agents():
    if not AGENTS.exists():
        return

    source = AGENTS.read_text(encoding="utf-8")
    decision = (
        "- 2026-08-31: V47 tilføjede et Matraws-specifikt Discord-værn mod "
        "enkeltkort med Matraws' per-card titelkonvention (fx `[CLC-009]`). "
        "Produkterne bevares i state, men må ikke udløse Restock-alerts.\n"
    )

    if decision in source:
        return

    anchor = "## Kommunikation\n"
    if anchor not in source:
        raise RuntimeError("V47: AGENTS kommunikations-anchor mangler")

    source = source.replace(anchor, decision + "\n" + anchor, 1)
    AGENTS.write_text(source, encoding="utf-8")
    print("V47: AGENTS decision log updated")


def main():
    patch_restock()
    patch_agents()


if __name__ == "__main__":
    main()
