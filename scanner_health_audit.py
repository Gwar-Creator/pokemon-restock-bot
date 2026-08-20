import json
import os
from datetime import datetime, timezone

STATE_FILE = "restock_state_v2.json"

SOURCE_MINIMUMS = {
    "coolshop": 10,
    "proshop": 2,
    "br": 5,
    "bilka": 5,
    "foetex": 5,
    "elgiganten": 5,
    "pokehulen": 10,
    "rogerz": 20,
    "mtgwebshop": 10,
    "luckbox": 5,
    "spilforsyningen": 5,
    "musenogslottet": 5,
    "nostalgic": 5,
    "andcards": 5,
    "pokecards": 10,
    "epicpanda": 10,
    "steffeno": 5,
    "nextlevel": 5,
}

SHOPIFY = {
    "pokehulen",
    "rogerz",
    "mtgwebshop",
    "luckbox",
    "spilforsyningen",
    "musenogslottet",
}
WOOCOMMERCE = {"nostalgic", "andcards", "pokecards"}


def load_state():
    with open(STATE_FILE, "r", encoding="utf-8") as file:
        state = json.load(file)
    if not isinstance(state, dict):
        raise RuntimeError("restock state er ikke et dictionary")
    return state


def source_products(state, source):
    if source in SHOPIFY:
        return ((state.get("shopify") or {}).get(source) or {})
    if source in WOOCOMMERCE:
        return ((state.get("woocommerce") or {}).get(source) or {})
    return state.get(source) or {}


def main():
    state = load_state()
    health = state.get("_source_health") or {}
    issues = []
    rows = []

    for source, minimum in SOURCE_MINIMUMS.items():
        products = source_products(state, source)
        count = len(products) if isinstance(products, dict) else 0
        entry = health.get(source) or {}
        status = str(entry.get("status") or "unknown")
        failures = int(entry.get("consecutive_failures") or 0)
        last_success = str(entry.get("last_success") or "")

        rows.append((source, count, status, failures, last_success))

        if count < minimum:
            issues.append(
                f"{source}: produktantal {count} er under minimum {minimum}"
            )
        if failures > 0 or status == "failed":
            issues.append(
                f"{source}: health={status}, consecutive_failures={failures}"
            )

    print("SCANNER HEALTH AUDIT")
    print(f"Tid: {datetime.now(timezone.utc).isoformat()}")
    for source, count, status, failures, last_success in rows:
        suffix = f" | last_success={last_success}" if last_success else ""
        print(
            f"- {source}: {count} produkter | health={status} | "
            f"failures={failures}{suffix}"
        )

    if issues:
        print("AUDIT ISSUES:")
        for issue in issues:
            print(f"! {issue}")
    else:
        print("AUDIT OK: alle 18 kilder er over minimum og uden registrerede failures.")

    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            source: {
                "count": count,
                "health": status,
                "consecutive_failures": failures,
                "last_success": last_success,
            }
            for source, count, status, failures, last_success in rows
        },
        "issues": issues,
    }

    with open("scanner_health_report.json", "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)

    # Audit is diagnostic: it must not kill the scanner because a retail
    # source is temporarily unavailable. The report is committed with state.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
