"""Regression tests: focused Price Watch alerts must meet *both* minimums.

The tests extract just the production functions to avoid importing or running
the live scanner, touching network/state, or emitting Discord notifications.
"""
import ast
from datetime import datetime
import math
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo

SOURCE = Path(__file__).with_name("restock_bot_github.py")


def load_price_functions():
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    selected = {
        "price_watch_focus_drop_is_actionable",
        "process_price_watch",
    }
    nodes = [
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name in selected
    ]
    if {node.name for node in nodes} != selected:
        raise AssertionError("Production Price Watch functions not found")
    namespace = {
        "math": math,
        "datetime": datetime,
        "ZoneInfo": ZoneInfo,
        "PRICE_ALERT_MIN_IMPROVEMENT_DKK": 25.0,
        "PRICE_ALERT_MIN_IMPROVEMENT_PCT": 0.05,
        "PRICE_WATCH_TIMEZONE": "Europe/Copenhagen",
        "PRICE_WATCH_FOCUS_SETS": (("151", ("151",)),),
        "safe_int": lambda v, default=0: int(v or default),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace


class FocusPriceMinimumTests(unittest.TestCase):
    def setUp(self):
        self.ns = load_price_functions()

    def test_both_thresholds_are_required(self):
        allowed = self.ns["price_watch_focus_drop_is_actionable"]
        cases = (
            (100, 99, False),       # tiny movement
            (100, 80, False),       # 20 DKK even though 20%
            (1000, 975, False),    # 25 DKK but only 2.5%
            (500, 475, True),      # exactly 25 DKK and 5%
            (1000, 925, True),     # both thresholds clearly exceeded
            (500, 475.01, False),  # 24.99 DKK
            (500, 476, False),     # 4.8% and 24 DKK
            (500, 501, False),     # price increase
            (500, 500, False),     # no change
            (0, 0, False),
            (float("nan"), 90, False),
            (100, float("inf"), False),
            ("invalid", 95, False),
        )
        for old, new, expected in cases:
            with self.subTest(old=old, new=new):
                self.assertEqual(allowed(old, new), expected)

    def test_process_sends_only_the_large_enough_price_fall(self):
        events = []
        listing = {
            "listing_key": "example",
            "source": "coolshop",
            "shop": "COOLSHOP",
            "raw_id": "test",
            "name": "Pokemon 151 Elite Trainer Box",
            "set": "151",
            "type": "ETB",
            "in_stock": True,
            "url": "https://example.invalid/item",
            "stock_lines": ["Online"],
        }
        self.ns["collect_price_watch_focus_listings"] = (
            lambda state, fresh_sources=None: {"example": listing}
        )
        self.ns["_price_watch_focus_alert"] = (
            lambda item, previous, combo=False: events.append((previous, item["price"])) or True
        )
        old_state = {
            "version": 15,
            "listings": {
                "example": {
                    "price": 500,
                    "in_stock": True,
                }
            },
        }
        process = self.ns["process_price_watch"]
        for new_price, expected in ((499, 0), (480, 0), (475, 1)):
            listing["price"] = new_price
            events.clear()
            output = process(old_state, {}, {"coolshop"})
            self.assertEqual(len(events), expected)
            self.assertEqual(output["listings"]["example"]["price"], new_price)

    def test_first_baseline_never_sends(self):
        events = []
        listing = {
            "listing_key": "example", "source": "coolshop", "shop": "COOLSHOP",
            "raw_id": "test", "name": "151 ETB", "set": "151", "type": "ETB",
            "price": 250, "in_stock": True, "url": "https://example.invalid/item",
        }
        self.ns["collect_price_watch_focus_listings"] = (
            lambda state, fresh_sources=None: {"example": listing}
        )
        self.ns["_price_watch_focus_alert"] = lambda *args, **kwargs: events.append(1)
        result = self.ns["process_price_watch"]({"version": 0, "listings": {}}, {}, {"coolshop"})
        self.assertEqual(events, [])
        self.assertEqual(result["version"], 15)
        self.assertEqual(result["listings"]["example"]["price"], 250)


if __name__ == "__main__":
    unittest.main()
