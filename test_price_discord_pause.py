"""Regression tests for intentionally paused price-related Discord traffic.

Tests extract just the relevant production functions and never run the scanner.
"""
import ast
import io
import os
from pathlib import Path
import unittest
from unittest.mock import Mock

SOURCE = Path(__file__).with_name("restock_bot_github.py")


def function_under_test(name, global_values):
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    nodes = [n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(nodes) != 1:
        raise AssertionError(f"Expected exactly one function {name}")
    namespace = dict(global_values)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace[name]


class PriceDiscordPauseTests(unittest.TestCase):
    def test_config_is_default_off_even_if_webhook_present(self):
        # Ensure no implicit side-effect merely because a webhook secret exists.
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('PRICE_WATCH_DISCORD_ENABLED = os.getenv("PRICE_WATCH_DISCORD_ENABLED", "0") == "1"', source)
        self.assertIn('PRICE_HISTORY_DISCORD_ENABLED = os.getenv("PRICE_HISTORY_DISCORD_ENABLED", "0") == "1"', source)

    def test_price_watch_off_does_not_send_or_modify_alert_memory(self):
        post = Mock(side_effect=AssertionError("must not post"))
        decision = Mock(side_effect=AssertionError("must not touch cooldown state"))
        memory = {"existing": {"sent_at": 100}}
        sender = function_under_test("send_price_watch", {
            "PRICE_WATCH_DISCORD_ENABLED": False,
            "PRICE_WATCH_WEBHOOK_URL": "https://example.invalid/webhook",
            "price_alert_decision": decision,
            "_post_discord": post,
            "PRICE_ALERT_MEMORY": memory,
            "re": __import__("re"),
        })
        self.assertFalse(sender("🔥 BEDRE PRIS · POKÉMON · 151 ETB"))
        self.assertEqual(memory, {"existing": {"sent_at": 100}})
        post.assert_not_called()
        decision.assert_not_called()

    def test_price_watch_opt_in_has_same_legacy_behavior(self):
        post = Mock()
        memory = {}
        sender = function_under_test("send_price_watch", {
            "PRICE_WATCH_DISCORD_ENABLED": True,
            "PRICE_WATCH_WEBHOOK_URL": "https://example.invalid/webhook",
            "price_alert_decision": lambda _: ("event", {"sent_at": 1}),
            "_post_discord": post,
            "PRICE_ALERT_MEMORY": memory,
            "re": __import__("re"),
        })
        self.assertTrue(sender("🔥 BEDRE PRIS · POKÉMON · 151 ETB"))
        post.assert_called_once()
        self.assertIn("event", memory)

    def test_history_embed_off_does_not_post(self):
        req = Mock()
        sender = function_under_test("send_price_history_embed", {
            "PRICE_HISTORY_DISCORD_ENABLED": False,
            "PRICE_HISTORY_WEBHOOK_URL": "https://example.invalid/historical",
            "requests": Mock(post=req),
        })
        self.assertFalse(sender("PRICE HISTORY", "A price changed"))
        req.assert_not_called()

    def test_history_csv_off_does_not_post(self):
        req = Mock()
        sender = function_under_test("_send_price_history_csv", {
            "PRICE_HISTORY_DISCORD_ENABLED": False,
            "PRICE_HISTORY_WEBHOOK_URL": "https://example.invalid/historical",
            "requests": Mock(post=req),
            "io": io,
        })
        self.assertFalse(sender({}, set(), None))
        req.assert_not_called()

    def test_main_price_history_remains_stateful(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('new_state["price_watch"] = process_price_watch(', source)
        self.assertIn('new_state["price_history"] = process_price_history(', source)


if __name__ == "__main__":
    unittest.main()
