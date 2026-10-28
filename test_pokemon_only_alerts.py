"""Guard against Lorcana Discord notifications without modifying history."""
import ast
import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("restock_bot_github.py")


def load_named(name, extra):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    selected = [x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == name]
    assert len(selected) == 1
    namespace = {"re": re, **extra}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace[name]


class PokemonOnlyAlertsTests(unittest.TestCase):
    def test_restock_lorcana_messages_are_muted_before_any_state_changes(self):
        posts, decisions, memory = [], [], {}
        def evaluate(message):
            decisions.append(message)
            return ("memorykey", {"product_fp": "fp"})
        send = load_named("send_discord", {
            "_discord_message_parts": lambda message: {"headline": message.splitlines()[0]},
            "restock_channel_alert_allowed": lambda _: True,
            "restock_alert_decision": evaluate,
            "_post_discord": lambda *args: posts.append(args),
            "WEBHOOK_URL": "test",
            "RESTOCK_ALERT_MEMORY": memory,
            "RESTOCK_SEEN_PRODUCTS": set(),
        })
        self.assertFalse(send("🔥 **[LORCANA] COOLSHOP RESTOCK**\n**Booster Box**"))
        self.assertFalse(send("🆕 **NYT FUND**\n**Disney Lorcana Booster Box**"))
        self.assertEqual(posts, [])
        self.assertEqual(decisions, [])
        self.assertEqual(memory, {})

    def test_pokemon_restock_still_posts_once(self):
        posts, memory, seen = [], {}, set()
        send = load_named("send_discord", {
            "_discord_message_parts": lambda message: {"headline": message.splitlines()[0]},
            "restock_channel_alert_allowed": lambda _: True,
            "restock_alert_decision": lambda _: ("key", {"product_fp": "p"}),
            "_post_discord": lambda *args: posts.append(args),
            "WEBHOOK_URL": "test",
            "RESTOCK_ALERT_MEMORY": memory,
            "RESTOCK_SEEN_PRODUCTS": seen,
        })
        self.assertTrue(send("🔥 **[POKÉMON] COOLSHOP RESTOCK**\n**Booster Bundle**"))
        self.assertEqual(len(posts), 1)
        self.assertEqual(memory["key"]["product_fp"], "p")
        self.assertIn("p", seen)

    def test_price_watch_lorcana_is_muted_before_dedupe(self):
        posts, decisions, memory = [], [], {}
        send = load_named("send_price_watch", {
            "PRICE_WATCH_WEBHOOK_URL": "test",
            "price_alert_decision": lambda msg: decisions.append(msg) or ("key", {}),
            "_post_discord": lambda *args: posts.append(args),
            "PRICE_ALERT_MEMORY": memory,
        })
        self.assertFalse(send("🔥 BEDRE PRIS · LORCANA · Booster"))
        self.assertEqual(posts, [])
        self.assertEqual(decisions, [])
        self.assertEqual(memory, {})

    def test_price_watch_pokemon_still_posts(self):
        posts, memory = [], {}
        send = load_named("send_price_watch", {
            "PRICE_WATCH_WEBHOOK_URL": "test",
            "price_alert_decision": lambda _: ("key", {}),
            "_post_discord": lambda *args: posts.append(args),
            "PRICE_ALERT_MEMORY": memory,
        })
        self.assertTrue(send("🔥 BEDRE PRIS · POKÉMON · ETB"))
        self.assertEqual(len(posts), 1)
        self.assertIn("key", memory)

    def test_price_digest_selects_only_pokemon_even_when_lorcana_cheaper(self):
        from datetime import datetime
        groups = {
            "POKÉMON|ETB": [{"price": 250, "shop": "A"}, {"price": 310, "shop": "B"}],
            "LORCANA|BOX": [{"price": 200, "shop": "A"}, {"price": 400, "shop": "B"}],
        }
        posts = []
        digest = load_named("send_price_watch_daily_summary", {
            "parse_price_watch_key": lambda key: {
                "game": key.split("|")[0], "type": key.split("|")[1]},
            "PRICE_WATCH_DAILY_MIN_SAVING_DKK": 25,
            "PRICE_WATCH_DAILY_MIN_SAVING_PCT": 5,
            "PRICE_WATCH_DAILY_MAX_SIGNALS_PER_GAME": 3,
            "price_watch_lowest_shops": lambda _: ["A"],
            "price_watch_game_label": lambda x: x,
            "price_watch_display_name": lambda x: x,
            "price_watch_type_label": lambda x: x,
            "format_price": lambda x: str(x),
            "send_price_watch": lambda msg: posts.append(msg) or True,
        })
        self.assertTrue(digest(groups, datetime(2026, 10, 28)))
        self.assertEqual(len(posts), 1)
        self.assertIn("POKÉMON", posts[0])
        self.assertNotIn("LORCANA", posts[0])
        self.assertIn("LORCANA|BOX", groups)


if __name__ == "__main__":
    unittest.main()
