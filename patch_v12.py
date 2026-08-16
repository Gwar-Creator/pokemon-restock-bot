from pathlib import Path

BOT = Path("restock_bot_github.py")
WORKFLOW = Path(".github/workflows/restock.yml")
PATCH = Path("patch_v12.py")

text = BOT.read_text(encoding="utf-8")

helper_marker = "# ============================================================\n# PRICE WATCH - PRODUKTTYPER\n# ============================================================\n"
helper = '''# ============================================================
# RESTOCK ALERT FILTER
# ============================================================

def restock_alert_allowed(product, game_override=None):
    """Keep low-signal products in state, but silence them on Discord."""
    name = str((product or {}).get("name", "")).lower()
    game = game_override or (product or {}).get("game")

    if game == "POKÉMON" and any(
        marker in name
        for marker in ("checklane", "check lane")
    ):
        return False

    if game == "LORCANA" and any(
        marker in name
        for marker in ("starter deck", "starterdeck", "starter decks")
    ):
        return False

    return True


def filter_restock_alert_products(products, game_override=None):
    return {
        key: product
        for key, product in (products or {}).items()
        if restock_alert_allowed(product, game_override)
    }


'''

if "def restock_alert_allowed(" not in text:
    if helper_marker not in text:
        raise RuntimeError("Could not find Price Watch marker for helper insertion")
    text = text.replace(helper_marker, helper + helper_marker, 1)

replacements = {
'''def process_coolshop_changes(
    old_products,
    new_products
):
    # NYE PRODUKTER
''': '''def process_coolshop_changes(
    old_products,
    new_products
):
    new_products = filter_restock_alert_products(new_products)

    # NYE PRODUKTER
''',
'''def process_proshop_changes(
    old_products,
    new_products
):
    # NYE PRODUKTER
''': '''def process_proshop_changes(
    old_products,
    new_products
):
    new_products = filter_restock_alert_products(new_products, "POKÉMON")

    # NYE PRODUKTER
''',
'''def process_br_changes(
    old_products,
    new_products
):
    # NYE PRODUKTER
''': '''def process_br_changes(
    old_products,
    new_products
):
    new_products = filter_restock_alert_products(new_products, "POKÉMON")

    # NYE PRODUKTER
''',
'''def process_salling_changes(
    site_key,
    old_products,
    new_products
):
    site = SALLING_SITES[site_key]
''': '''def process_salling_changes(
    site_key,
    old_products,
    new_products
):
    new_products = filter_restock_alert_products(new_products, "POKÉMON")
    site = SALLING_SITES[site_key]
''',
'''def process_elgiganten_changes(old_products, new_products):
    for product_id, product in new_products.items():
''': '''def process_elgiganten_changes(old_products, new_products):
    new_products = filter_restock_alert_products(new_products, "POKÉMON")

    for product_id, product in new_products.items():
''',
'''def process_shopify_changes(site_key, old_products, new_products):
    site = SHOPIFY_SITES[site_key]
''': '''def process_shopify_changes(site_key, old_products, new_products):
    new_products = filter_restock_alert_products(new_products)
    site = SHOPIFY_SITES[site_key]
''',
'''def process_woocommerce_changes(site_key, old_products, new_products):
    site = WOOCOMMERCE_SITES[site_key]
''': '''def process_woocommerce_changes(site_key, old_products, new_products):
    new_products = filter_restock_alert_products(new_products)
    site = WOOCOMMERCE_SITES[site_key]
''',
'''def process_nextlevel_changes(old_products, current_products):
    label = "NEXT LEVEL GAMES"
''': '''def process_nextlevel_changes(old_products, current_products):
    current_products = filter_restock_alert_products(current_products)
    label = "NEXT LEVEL GAMES"
''',
'''def process_epicpanda_changes(
    old_products,
    new_products
):
    label = "EPIC PANDA"
''': '''def process_epicpanda_changes(
    old_products,
    new_products
):
    new_products = filter_restock_alert_products(new_products)
    label = "EPIC PANDA"
''',
'''def process_steffeno_changes(
    old_products,
    new_products
):
    label = "STEFFEN-O"
''': '''def process_steffeno_changes(
    old_products,
    new_products
):
    new_products = filter_restock_alert_products(new_products, "POKÉMON")
    label = "STEFFEN-O"
''',
}

for old, new in replacements.items():
    if new in text:
        continue
    if old not in text:
        raise RuntimeError("Could not find expected restock processor block")
    text = text.replace(old, new, 1)

start = text.index("def process_price_watch(\n")
end_marker = "\n\n# =========================================================\n# COOLSHOP FETCH\n# =========================================================\n"
end = text.index(end_marker, start)

new_process = r'''def process_price_watch(
    old_price_watch_state,
    current_state,
    fresh_sources
):
    candidates = collect_price_watch_candidates(
        current_state,
        fresh_sources=fresh_sources
    )

    comparable_groups = build_price_watch_groups(
        candidates
    )

    print(
        f"PRICE WATCH V1: "
        f"{len(candidates)} friske prislinjer | "
        f"{len(comparable_groups)} produkter hos mindst 2 butikker | "
        f"{len(fresh_sources)} friske kilder"
    )

    previous = (
        old_price_watch_state
        if isinstance(old_price_watch_state, dict)
        else {}
    )

    previous_version = safe_int(
        previous.get("version"),
        0
    )

    previous_products = previous.get("products")
    is_first_price_watch_run = not isinstance(previous_products, dict)

    if not isinstance(previous_products, dict):
        previous_products = {}

    try:
        now_local = datetime.now(ZoneInfo(PRICE_WATCH_TIMEZONE))
    except Exception:
        now_local = datetime.now(ZoneInfo("Europe/Copenhagen"))

    today = now_local.date().isoformat()
    last_daily_date = str(previous.get("last_daily_date", "") or "")

    daily_due = (
        bool(PRICE_WATCH_WEBHOOK_URL)
        and now_local.hour >= PRICE_WATCH_DAILY_HOUR
        and last_daily_date != today
    )

    daily_sent = False

    if daily_due:
        daily_sent = send_price_watch_daily_summary(
            comparable_groups,
            now_local
        )

        if daily_sent:
            last_daily_date = today

    # V3: En højere bedste pris / tab af billigste butik skal ses i
    # to på hinanden følgende friske scans før den bliver bekræftet.
    # Et enkelt midlertidigt manglende produkt kan derfor ikke længere
    # få 1.479 -> 1.499 -> 1.479 til at spamme Discord.
    changes_enabled = (
        bool(PRICE_WATCH_WEBHOOK_URL)
        and last_daily_date == today
        and not daily_sent
        and not is_first_price_watch_run
        and previous_version >= 3
    )

    next_products = dict(previous_products)

    def confirmed_entry(product_key, best, current_best, current_shops, current_sources):
        return {
            "current_best": current_best,
            "current_shop": best["shop"],
            "current_shops": current_shops,
            "current_sources": current_sources,
            "name": price_watch_display_name(product_key),
            "last_seen": now_local.isoformat()
        }

    for product_key, products in comparable_groups.items():
        best = price_watch_best_entry(products)
        current_best = float(best["price"])
        current_shops = price_watch_lowest_shops(products)
        current_sources = sorted({
            product["source"]
            for product in products
            if abs(product["price"] - current_best) < 0.005
        })

        old_entry = previous_products.get(product_key)

        if not isinstance(old_entry, dict):
            next_products[product_key] = confirmed_entry(
                product_key,
                best,
                current_best,
                current_shops,
                current_sources
            )
            continue

        try:
            old_price = float(old_entry.get("current_best"))
        except (TypeError, ValueError):
            old_price = None

        old_shops = old_entry.get("current_shops")
        if not isinstance(old_shops, list):
            old_shop = old_entry.get("current_shop")
            old_shops = [old_shop] if old_shop else []

        old_sources = old_entry.get("current_sources")
        if not isinstance(old_sources, list):
            old_sources = []

        price_is_lower = (
            old_price is not None
            and current_best < old_price - 0.005
        )
        price_is_higher = (
            old_price is not None
            and current_best > old_price + 0.005
        )
        cheapest_shop_changed = (
            old_price is not None
            and abs(current_best - old_price) < 0.005
            and bool(old_shops)
            and not set(old_shops).intersection(current_shops)
        )

        old_sources_are_fresh = (
            bool(old_sources)
            and all(source in fresh_sources for source in old_sources)
        )

        # En reel lavere pris er positiv information fra en frisk kilde
        # og kan derfor bekræftes med det samme.
        if price_is_lower:
            if changes_enabled:
                send_price_watch_change(product_key, old_entry, products)

            next_products[product_key] = confirmed_entry(
                product_key,
                best,
                current_best,
                current_shops,
                current_sources
            )
            continue

        # Pris op / billigste butik væk er negativ information og kan
        # skyldes et midlertidigt hul i et produktfeed. Kræv 2 ens scans.
        if price_is_higher or cheapest_shop_changed:
            if not old_sources_are_fresh:
                kept = dict(old_entry)
                kept.pop("pending_change", None)
                kept["last_seen"] = now_local.isoformat()
                next_products[product_key] = kept
                continue

            signature = (
                f"{current_best:.2f}|"
                + ",".join(sorted(current_shops))
            )
            pending = old_entry.get("pending_change")

            if (
                isinstance(pending, dict)
                and pending.get("signature") == signature
            ):
                pending_count = safe_int(pending.get("count"), 0) + 1
            else:
                pending_count = 1

            if pending_count >= 2:
                if changes_enabled:
                    send_price_watch_change(product_key, old_entry, products)

                next_products[product_key] = confirmed_entry(
                    product_key,
                    best,
                    current_best,
                    current_shops,
                    current_sources
                )
            else:
                kept = dict(old_entry)
                kept["pending_change"] = {
                    "signature": signature,
                    "count": pending_count,
                    "observed_best": current_best,
                    "observed_shops": current_shops,
                    "observed_sources": current_sources,
                    "first_seen": now_local.isoformat()
                }
                kept["last_seen"] = now_local.isoformat()
                next_products[product_key] = kept

            continue

        # Stabilt scan: opdater metadata og nulstil evt. pending flap.
        next_products[product_key] = confirmed_entry(
            product_key,
            best,
            current_best,
            current_shops,
            current_sources
        )

    if is_first_price_watch_run:
        print("PRICE WATCH V3 baseline oprettet uden ændringsalerts.")
    elif previous_version < 3:
        print("PRICE WATCH V3 anti-flap aktiveret uden overgangsalerts.")

    return {
        "version": 3,
        "products": next_products,
        "last_daily_date": last_daily_date
    }
'''

text = text[:start] + new_process + text[end:]
BOT.write_text(text, encoding="utf-8")

final_workflow = '''name: Pokemon Restock Bot

on:
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: pokemon-restock-bot
  cancel-in-progress: false

jobs:
  scan:
    runs-on: ubuntu-latest
    timeout-minutes: 10

    steps:
      - name: Checkout repository
        uses: actions/checkout@v5
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.13"
          cache: pip

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run one restock scan
        env:
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
          PRICE_WATCH_WEBHOOK_URL: ${{ secrets.PRICE_WATCH_WEBHOOK_URL }}
          RUN_ONCE: "1"
        run: python restock_bot_github.py

      - name: Save updated state
        run: |
          if git diff --quiet -- restock_state_v2.json; then
            echo "No state changes to save."
            exit 0
          fi

          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

          git add restock_state_v2.json
          git commit -m "Update restock state"
          git push
'''

WORKFLOW.write_text(final_workflow, encoding="utf-8")
PATCH.unlink(missing_ok=True)

print("V1.2 patch applied: anti-flap + alert filters + single scheduler.")
