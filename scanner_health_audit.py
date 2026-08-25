import json
from datetime import datetime, timezone

STATE_FILE = "restock_state_v2.json"

SOURCE_MINIMUMS = {
    "coolshop": 10,
    "proshop": 2,
    "br": 5,
    "bilka": 5,
    "foetex": 5,
    "pokehulen": 10,
    "rogerz": 20,
    "mtgwebshop": 10,
    "luckbox": 5,
    "spilforsyningen": 5,
    "musenogslottet": 5,
    "symbizon": 10,
    "cardx": 10,
    "matraws": 20,
    "halmeshule": 5,
    "cardsdirect": 5,
    "baltzer": 5,
    "tcgshoppen": 5,
    "pokemonsdk": 5,
    "pocketmonster": 5,
    "funshop": 10,
    "pokepulls": 10,
    "staalz": 5,
    "pbcards": 10,
    "kocardz": 5,
    "vaulted": 15,
    "pokedexet": 10,
    "pokemonportalen": 10,
    "tcgbruus": 5,
    "pokemonplaza": 5,
    "kelz0r": 20,
    "faraos": 5,
    "goblingames": 10,
    "hyggeonkel": 5,
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
    "symbizon",
    "cardx",
    "matraws",
    "halmeshule",
    "cardsdirect",
    "baltzer",
    "tcgshoppen",
    "funshop",
    "pokepulls",
    "staalz",
    "pbcards",
    "vaulted",
    "pokedexet",
}
WOOCOMMERCE = {
    "nostalgic",
    "andcards",
    "pokecards",
    "pokemonsdk",
    "pocketmonster",
    "kocardz",
    "pokemonportalen",
    "tcgbruus",
    "pokemonplaza",
    "kelz0r",
    "faraos",
    "goblingames",
    "hyggeonkel",
}


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
        print(
            f"AUDIT OK: alle {len(SOURCE_MINIMUMS)} aktive kilder er over minimum "
            "og uden registrerede failures."
        )

    # Diagnostic only. Source-health already owns Discord failure alerts, so
    # this audit does not create an extra noisy channel or a changing report file.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
