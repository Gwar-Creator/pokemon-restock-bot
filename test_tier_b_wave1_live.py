import unittest

import tier_b_wave1_shadow as runner


class TierBWave1LiveTests(unittest.TestCase):
    def test_seven_sources_are_live_and_flinamania_stays_shadow(self):
        self.assertEqual(len(runner.LIVE_SOURCES), 7)
        self.assertEqual(set(runner.SHADOW_SOURCES), {"flinamania"})
        self.assertNotIn("flinamania", runner.LIVE_SOURCES)
        self.assertEqual(runner._source_mode("flinamania"), "shadow")
        self.assertEqual(runner._source_mode("cardcollective"), "live")

    def test_event_detection_only_fires_on_actionable_transition(self):
        sold = {"in_stock": False, "preorder": False}
        live = {"in_stock": True, "preorder": False}
        preorder = {"in_stock": False, "preorder": True}

        self.assertEqual(runner._event_for_product(sold, live), "RESTOCK")
        self.assertEqual(runner._event_for_product(sold, preorder), "PREORDER")
        self.assertIsNone(runner._event_for_product(live, live))
        self.assertIsNone(runner._event_for_product(None, sold))
        self.assertEqual(runner._event_for_product(None, live), "NEW")

    def test_missing_baseline_never_replays_current_catalogue(self):
        products = {
            "1": {
                "name": "Pokemon 151 Booster Bundle",
                "game": "POKÉMON",
                "price": 599.0,
                "in_stock": True,
                "preorder": False,
                "url": "https://example.test/products/151-bundle",
            }
        }
        messages = []
        sent = runner._emit_live_alerts(
            "cardcollective",
            "CARD COLLECTIVE",
            {},
            products,
            sender=messages.append,
        )
        self.assertEqual(sent, 0)
        self.assertEqual(messages, [])

    def test_strict_tier_b_gate_only_sends_high_signal_normal_restock(self):
        old = {
            "box": {"in_stock": False, "preorder": False},
            "ordinary": {"in_stock": False, "preorder": False},
        }
        new = {
            "box": {
                "name": "Pokemon Journey Together Booster Box",
                "game": "POKÉMON",
                "price": 1799.0,
                "in_stock": True,
                "preorder": False,
                "url": "https://example.test/products/box",
            },
            "ordinary": {
                "name": "Pokemon Journey Together Collection Box",
                "game": "POKÉMON",
                "price": 299.0,
                "in_stock": True,
                "preorder": False,
                "url": "https://example.test/products/collection",
            },
        }
        messages = []
        sent = runner._emit_live_alerts(
            "cardcollective",
            "CARD COLLECTIVE",
            old,
            new,
            sender=messages.append,
        )
        self.assertEqual(sent, 1)
        self.assertEqual(len(messages), 1)
        self.assertIn("Booster Box", messages[0])

    def test_shadow_source_never_sends_even_with_actionable_transition(self):
        old = {"1": {"in_stock": False, "preorder": False}}
        new = {
            "1": {
                "name": "Pokemon 151 Booster Bundle",
                "game": "POKÉMON",
                "price": 599.0,
                "in_stock": True,
                "preorder": False,
                "url": "https://example.test/products/151-bundle",
            }
        }
        messages = []
        sent = runner._emit_live_alerts(
            "flinamania",
            "FLINAMANIA",
            old,
            new,
            sender=messages.append,
        )
        self.assertEqual(sent, 0)
        self.assertEqual(messages, [])


if __name__ == "__main__":
    unittest.main()
