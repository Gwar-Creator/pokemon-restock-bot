import argparse
import json
import os
from datetime import datetime, timezone

STATE_FILE = "restock_state_v2.json"

SOURCE_MINIMUMS = {
    "coolshop": 10,
    "proshop": 3,
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


def inspect_sources(state, minimums=None):
    """Classify saved source health without treating cached stock as live stock.

    OK: last source scan succeeded and the stored count meets its sanity check.
    DEGRADED: transient failure, explicit degradation or suspicious count.
    DOWN: at least three consecutive failed scans.
    UNKNOWN: the latest recorded health is absent or not interpretable.
    """
    if minimums is None:
        minimums = SOURCE_MINIMUMS
    health = state.get("_source_health") or {}
    rows = []

    for source, minimum in minimums.items():
        products = source_products(state, source)
        cached_count = len(products) if isinstance(products, dict) else 0
        entry = health.get(source) or {}
        raw_status = str(entry.get("status") or "unknown").lower()
        try:
            failures = max(0, int(entry.get("consecutive_failures") or 0))
        except (ValueError, TypeError):
            failures = 0
            raw_status = "unknown"

        if raw_status == "failed" or failures:
            status = "DOWN" if failures >= 3 else "DEGRADED"
            reason = f"{failures} consecutive failure(s)"
        elif raw_status == "degraded":
            status = "DEGRADED"
            reason = "source reported degraded"
        elif raw_status == "ok":
            if cached_count < minimum:
                status = "DEGRADED"
                reason = f"cached count {cached_count} below sanity threshold {minimum}"
            else:
                status = "OK"
                reason = ""
        else:
            status = "UNKNOWN"
            reason = "no trustworthy saved source-health status"

        rows.append({
            "source": source,
            "status": status,
            "reason": reason,
            "cached_count": cached_count,
            "minimum": minimum,
            "failures": failures,
            "last_success": str(entry.get("last_success") or ""),
        })

    return rows


def write_github_summary(rows, path):
    """Append a concise diagnostic table; never alter scanner state."""
    counts = {
        status: sum(row["status"] == status for row in rows)
        for status in ("OK", "DEGRADED", "DOWN", "UNKNOWN")
    }
    with open(path, "a", encoding="utf-8") as file:
        file.write("\n### Scanner health (last saved scan)\n\n")
        file.write(
            "Cached product counts are **not** confirmation of current "
            "availability. This audit does not send Discord messages.\n\n"
        )
        file.write(
            f"OK: {counts['OK']} | DEGRADED: {counts['DEGRADED']} | "
            f"DOWN: {counts['DOWN']} | UNKNOWN: {counts['UNKNOWN']}\n\n"
        )
        file.write("| Source | Health | Cached products | Failed scans | Last success |\n")
        file.write("| --- | --- | ---: | ---: | --- |\n")
        for row in rows:
            file.write(
                f"| {row['source']} | {row['status']} | "
                f"{row['cached_count']} | {row['failures']} | "
                f"{row['last_success']} |\n"
            )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only scanner health audit")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 for any non-OK source, for a visible diagnostic step failure.",
    )
    args = parser.parse_args(argv)
    state = load_state()
    rows = inspect_sources(state)
    issues = [row for row in rows if row["status"] != "OK"]

    print("SCANNER HEALTH AUDIT (saved source state, not live availability)")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    for row in rows:
        extra = f" | reason={row['reason']}" if row["reason"] else ""
        last = f" | last_success={row['last_success']}" if row["last_success"] else ""
        print(
            f"- {row['source']}: {row['status']} | "
            f"{row['cached_count']} cached products | failures={row['failures']}"
            f"{last}{extra}"
        )

    if issues:
        counts = {
            status: sum(row["status"] == status for row in issues)
            for status in ("DEGRADED", "DOWN", "UNKNOWN")
        }
        print(
            f"::warning title=Scanner source health::"
            f"{counts['DOWN']} down, {counts['DEGRADED']} degraded, "
            f"{counts['UNKNOWN']} unknown. See scanner health job summary."
        )
        print("AUDIT ISSUES:")
        for row in issues:
            print(f"! {row['source']}: {row['status']} - {row['reason']}")
    else:
        print(f"AUDIT OK: {len(rows)} sources with healthy recorded scans.")

    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        write_github_summary(rows, summary_path)

    # Keep the default safe for local diagnostics. In GitHub Actions --strict
    # visibly marks the audit step as failed; the workflow uses
    # continue-on-error so current scanner/state saves are not interrupted.
    return 1 if args.strict and issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
