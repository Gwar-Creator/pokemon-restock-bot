from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import cardmarket_chase_watch as cm

PATCH = Path("cardmarket_v16_replay.py")


def main():
    old = cm.load(cm.STATE, {})
    cards_state = old.get("cards", {}) if isinstance(old, dict) else {}
    if not isinstance(cards_state, dict) or not cards_state:
        print("CARD MARKET V1.6 replay: ingen eksisterende card state")
        PATCH.unlink(missing_ok=True)
        return

    if int(old.get("version", 1) or 1) >= 2 and old.get("set_scores"):
        print("CARD MARKET V1.6 replay: allerede migreret")
        PATCH.unlink(missing_ok=True)
        return

    now = datetime.now(ZoneInfo(cm.TZ))
    cards = list(cards_state.values())
    ranked_cards = cm.ranked(cards)
    old_scores = old.get("set_scores", {}) if isinstance(old.get("set_scores", {}), dict) else {}
    summaries = cm.build_set_summaries(ranked_cards, old_scores=old_scores)
    opportunities = cm.sealed_opportunities(summaries, cm.price_history_products())

    file, ranked_cards = cm.workbook(
        cards,
        summaries,
        opportunities,
        now.isoformat(),
        0,
        old.get("rate_remaining"),
    )

    for game in ("POKÉMON", "LORCANA"):
        cm.discord_market_pulse(
            ranked_cards,
            game,
            summaries,
            opportunities,
            True,
            [],
            0,
            weekly=now.weekday() == 6,
        )

    if now.weekday() == 6:
        for game in ("POKÉMON", "LORCANA"):
            cm.discord_weekly_report(ranked_cards, game, summaries, opportunities)

    cm.post(
        content=(
            "📎 **Card Market Watch V1.6 · Heat baseline**\n"
            "Første Heat Score + Market Pulse er beregnet på dagens allerede hentede Cardmarket-data. "
            "Der er brugt **0 ekstra API requests** til denne migrering."
        ),
        file=file,
    )

    old["version"] = 2
    old["set_scores"] = cm.current_score_state(summaries)
    old["set_history"] = cm.update_set_history(old, summaries, now.date())
    cm.save(cm.STATE, old)
    PATCH.unlink(missing_ok=True)
    print(f"CARD MARKET V1.6 replay færdig: {len(cards)} kort | 0 API requests")


if __name__ == "__main__":
    main()
