import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# Import the production helpers without enabling any Discord writes.
os.environ.setdefault("DISCORD_WEBHOOK_URL", "https://example.invalid/webhook")
os.environ.pop("PRICE_WATCH_WEBHOOK_URL", None)
os.environ.pop("PRICE_HISTORY_WEBHOOK_URL", None)

import restock_bot_github as bot

STATE_FILE = "restock_state_v2.json"
OUTPUT_FILE = "price_channels_preview_v25.txt"


def load_state():
    with open(STATE_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def fresh_sources(state):
    health = state.get("_source_health") or {}
    return {
        source
        for source, entry in health.items()
        if isinstance(entry, dict) and entry.get("status") == "ok"
    }


def preview_price_watch(state, fresh):
    candidates = bot.collect_price_watch_candidates(state, fresh_sources=fresh)
    groups = bot.build_price_watch_groups(candidates)
    signals_by_game = {"POKÉMON": [], "LORCANA": []}

    for product_key, products in groups.items():
        info = bot.parse_price_watch_key(product_key)
        game = info["game"]
        if game not in signals_by_game:
            continue

        ordered = sorted(products, key=lambda product: (product["price"], product["shop"]))
        best = ordered[0]
        best_price = float(best["price"])
        next_prices = [
            float(product["price"])
            for product in ordered
            if float(product["price"]) > best_price + 0.005
        ]
        if not next_prices:
            continue

        next_price = min(next_prices)
        saving_dkk = next_price - best_price
        saving_pct = saving_dkk / next_price * 100.0 if next_price > 0 else 0.0
        if (
            saving_dkk < bot.PRICE_WATCH_DAILY_MIN_SAVING_DKK
            or saving_pct < bot.PRICE_WATCH_DAILY_MIN_SAVING_PCT
        ):
            continue

        signals_by_game[game].append({
            "product_key": product_key,
            "best": best,
            "shops": bot.price_watch_lowest_shops(products),
            "next_price": next_price,
            "saving_dkk": saving_dkk,
            "saving_pct": saving_pct,
        })

    lines = [
        "🎯 DAGENS KØBSOVERSIGT — MANUEL V25 PREVIEW",
        "Kun tydelige prisfordele. Maks 3 Pokémon + 3 Lorcana.",
        "Prislofter: pack 150 · sleeved 175 · bundle 750 · ETB 1.500 · box 1.750 kr.",
    ]

    for game in ("POKÉMON", "LORCANA"):
        lines.append("")
        lines.append(bot.price_watch_game_label(game))
        signals = sorted(
            signals_by_game[game],
            key=lambda row: (row["saving_pct"], row["saving_dkk"]),
            reverse=True,
        )[:bot.PRICE_WATCH_DAILY_MAX_SIGNALS_PER_GAME]
        if not signals:
            lines.append("• Ingen tydelige prisfordele lige nu")
            continue

        for index, signal in enumerate(signals, start=1):
            info = bot.parse_price_watch_key(signal["product_key"])
            shops = " + ".join(signal["shops"])
            lines.append(
                f"{index}. {bot.price_watch_display_name(signal['product_key'])} · "
                f"{bot.price_watch_type_label(info['type'])} — "
                f"{bot.format_price(signal['best']['price'])} hos {shops} · "
                f"næste {bot.format_price(signal['next_price'])} · "
                f"spar {signal['saving_pct']:.0f}%"
            )

    return lines, len(candidates), len(groups)


def preview_price_history(state, fresh):
    # Recalculate current groups with the exact V25 candidate rules, but do not
    # mutate the production history or send webhooks.
    candidates = bot.collect_price_watch_candidates(state, fresh_sources=fresh)
    groups = bot.build_price_history_groups(candidates)
    history = ((state.get("price_history") or {}).get("products") or {})
    rows = []

    for product_key, products in groups.items():
        best = bot.price_watch_best_entry(products)
        current = float(best["price"])
        old = history.get(product_key) or {}
        try:
            low = float(old.get("historical_low"))
        except (TypeError, ValueError):
            low = current
        if low <= 0:
            continue
        diff = (current - low) / low * 100.0
        rows.append({
            "key": product_key,
            "current": current,
            "low": low,
            "diff": diff,
            "shops": bot.price_watch_lowest_shops(products),
        })

    actionable = [row for row in rows if row["diff"] <= 3.0]
    wait = [row for row in rows if row["diff"] >= 10.0]

    actionable.sort(key=lambda row: (row["diff"], row["current"]))
    wait.sort(key=lambda row: (-row["diff"], row["current"]))

    selected = []
    for row in actionable:
        selected.append(("SLÅ TIL", row))
        if len(selected) >= bot.PRICE_HISTORY_DAILY_MAX_SIGNALS_TOTAL:
            break
    if len(selected) < bot.PRICE_HISTORY_DAILY_MAX_SIGNALS_TOTAL:
        for row in wait:
            selected.append(("AFVENT", row))
            if len(selected) >= bot.PRICE_HISTORY_DAILY_MAX_SIGNALS_TOTAL:
                break

    lines = [
        "🎯 PRISUDVIKLING & KØBSSIGNALER — MANUEL V25 PREVIEW",
        "Maks 3 signaler samlet. Små bevægelser gemmes i data, men vises ikke som Discord-støj.",
    ]
    if not selected:
        lines.append("✅ Ingen tydelige købssignaler eller afvent-priser lige nu.")
        return lines, len(rows)

    for label, row in selected:
        shops = " + ".join(row["shops"]) or "ukendt butik"
        emoji = "🟢" if label == "SLÅ TIL" else "🟠"
        lines.append(
            f"{emoji} {label}: {bot.price_watch_display_name(row['key'])} — "
            f"{bot.format_price(row['current'])} hos {shops} · "
            f"historisk low {bot.format_price(row['low'])} · "
            f"{row['diff']:.0f}% over low"
        )

    return lines, len(rows)


def main():
    state = load_state()
    fresh = fresh_sources(state)
    pw_lines, candidate_count, comparable_count = preview_price_watch(state, fresh)
    ph_lines, history_count = preview_price_history(state, fresh)
    now = datetime.now(ZoneInfo("Europe/Copenhagen"))

    output = [
        f"V25 PRICE CHANNEL PREVIEW · {now.strftime('%d.%m.%Y %H:%M')}",
        f"Friske kilder: {', '.join(sorted(fresh))}",
        f"Price Watch kandidater efter filtre/lofter: {candidate_count}",
        f"Sammenlignelige produktgrupper: {comparable_count}",
        f"Price History aktive grupper efter filtre/lofter: {history_count}",
        "",
        *pw_lines,
        "",
        "----------------------------------------",
        "",
        *ph_lines,
        "",
        "NOTE: Dette er en read-only preview. Den sender intet til Discord og ændrer ikke state.",
    ]
    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        file.write("\n".join(output) + "\n")
    print("\n".join(output))


if __name__ == "__main__":
    main()
