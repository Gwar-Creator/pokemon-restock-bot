import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tier_b_wave4_shadow as wave4


class TierBWave4LiveTests(unittest.TestCase):
    def _products(self, count, *, game="POKÉMON", in_stock=True, preorder=False):
        return {
            f"id-{index}": {
                "name": f"Pokemon Booster Box {index}",
                "game": game,
                "price": 1000.0,
                "in_stock": in_stock,
                "preorder": preorder,
                "url": f"https://example.test/{index}",
            }
            for index in range(count)
        }

    def _main_state(self):
        state = {"shopify": {}, "woocommerce": {}}
        for source_key, config in wave4.WAVE4_SOURCES.items():
            state[config["state_group"]][source_key] = self._products(config["minimum"])
        return state

    def test_wave4_has_expected_live_sources(self):
        expected = {"vaulted", "pokedexet", "pokemonportalen", "tcgbruus", "pokemonplaza"}
        self.assertEqual(set(wave4.WAVE4_SOURCES), expected)
        self.assertEqual(set(wave4.LIVE_SOURCES), expected)

    def test_wave4_sources_match_real_main_state_groups(self):
        self.assertEqual(wave4.WAVE4_SOURCES["vaulted"]["state_group"], "shopify")
        self.assertEqual(wave4.WAVE4_SOURCES["pokedexet"]["state_group"], "shopify")
        self.assertEqual(wave4.WAVE4_SOURCES["pokemonportalen"]["state_group"], "woocommerce")
        self.assertEqual(wave4.WAVE4_SOURCES["tcgbruus"]["state_group"], "woocommerce")
        self.assertEqual(wave4.WAVE4_SOURCES["pokemonplaza"]["state_group"], "woocommerce")

    def test_live_reuses_shadow_baseline_without_replay(self):
        main_state = self._main_state()
        sent = []

        old_state = {
            "version": 1,
            "mode": "shadow",
            "sources": {},
        }
        for source_key, config in wave4.WAVE4_SOURCES.items():
            products = main_state[config["state_group"]][source_key]
            old_state["sources"][source_key] = {
                "label": config["label"],
                "mode": "shadow",
                "health": {"status": "ok", "consecutive_failures": 0, "last_success": "old"},
                "products": products,
            }

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "wave4.json"
            state_path.write_text(json.dumps(old_state), encoding="utf-8")
            with patch.object(wave4, "STATE_FILE", state_path):
                failures = wave4.run_scan(main_state=main_state, sender=sent.append)

            self.assertEqual(failures, 0)
            self.assertEqual(sent, [])
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["mode"], "live")
            self.assertTrue(all(row["mode"] == "live" for row in state["sources"].values()))
            self.assertTrue(all(row["health"]["status"] == "ok" for row in state["sources"].values()))

    def test_restock_transition_can_alert(self):
        source_key = "vaulted"
        count = wave4.WAVE4_SOURCES[source_key]["minimum"]
        old_products = self._products(count, in_stock=False)
        new_products = self._products(count, in_stock=False)
        new_products["id-0"]["in_stock"] = True
        sent = []

        sent_count = wave4._emit_live_alerts(
            source_key,
            "VAULTED",
            old_products,
            new_products,
            sender=sent.append,
        )
        self.assertEqual(sent_count, 1)
        self.assertEqual(len(sent), 1)
        self.assertIn("RESTOCK", sent[0])

    def test_pokemonportalen_preorder_is_fail_closed(self):
        old_product = {
            "name": "Pokemon 30th Booster Box",
            "game": "POKÉMON",
            "in_stock": False,
            "preorder": False,
        }
        new_product = dict(old_product, preorder=True)
        self.assertIsNone(wave4._event_for_product("pokemonportalen", old_product, new_product))
        self.assertEqual(wave4._event_for_product("vaulted", old_product, new_product), "PREORDER")

    def test_low_count_preserves_previous_baseline(self):
        source_key = "vaulted"
        old_products = self._products(wave4.WAVE4_SOURCES[source_key]["minimum"])
        main_state = self._main_state()
        main_state["shopify"][source_key] = {
            "one": {"name": "Pokemon Booster Box", "game": "POKÉMON"}
        }

        old_state = {
            "version": 1,
            "mode": "shadow",
            "sources": {
                source_key: {
                    "label": "VAULTED",
                    "mode": "shadow",
                    "health": {"status": "ok", "consecutive_failures": 0, "last_success": "old"},
                    "products": old_products,
                }
            },
        }

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "wave4.json"
            state_path.write_text(json.dumps(old_state), encoding="utf-8")
            with patch.object(wave4, "STATE_FILE", state_path):
                failures = wave4.run_scan(main_state=main_state, sender=lambda _message: None)

            self.assertEqual(failures, 1)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["sources"][source_key]["products"], old_products)
            self.assertEqual(state["sources"][source_key]["health"]["status"], "failed")

    def test_stock_count_supports_legacy_stock_shapes(self):
        products = {
            "a": {"game": "POKÉMON", "in_stock": True},
            "b": {"game": "POKÉMON", "online_stock": True},
            "c": {"game": "LORCANA", "stock": "PÅ LAGER"},
            "d": {"game": "POKÉMON", "in_stock": False},
        }
        pokemon, lorcana, stock, preorders = wave4._counts(products)
        self.assertEqual((pokemon, lorcana, stock, preorders), (3, 1, 3, 0))


if __name__ == "__main__":
    unittest.main()
