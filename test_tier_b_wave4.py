import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tier_b_wave4_shadow as shadow


class TierBWave4ShadowTests(unittest.TestCase):
    def _products(self, count, *, game="POKÉMON", in_stock=True):
        return {
            f"id-{index}": {
                "name": f"Pokemon Booster Box {index}",
                "game": game,
                "price": 1000.0,
                "in_stock": in_stock,
                "preorder": False,
                "url": f"https://example.test/{index}",
            }
            for index in range(count)
        }

    def test_wave4_has_expected_sources(self):
        self.assertEqual(
            set(shadow.WAVE4_SOURCES),
            {"vaulted", "pokedexet", "pokemonportalen", "tcgbruus", "pokemonplaza"},
        )

    def test_shadow_snapshots_all_sources_without_alert_side_effects(self):
        main_state = {
            source_key: self._products(config["minimum"])
            for source_key, config in shadow.WAVE4_SOURCES.items()
        }

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "wave4.json"
            with patch.object(shadow, "STATE_FILE", state_path):
                failures = shadow.run_scan(main_state=main_state)

            self.assertEqual(failures, 0)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["mode"], "shadow")
            self.assertEqual(set(state["sources"]), set(shadow.WAVE4_SOURCES))
            self.assertTrue(all(row["mode"] == "shadow" for row in state["sources"].values()))
            self.assertTrue(all(row["health"]["status"] == "ok" for row in state["sources"].values()))

    def test_low_count_preserves_previous_baseline(self):
        source_key = "vaulted"
        old_products = self._products(shadow.WAVE4_SOURCES[source_key]["minimum"])
        main_state = {
            key: self._products(config["minimum"])
            for key, config in shadow.WAVE4_SOURCES.items()
        }
        main_state[source_key] = {"one": {"name": "Pokemon Booster Box", "game": "POKÉMON"}}

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
            with patch.object(shadow, "STATE_FILE", state_path):
                failures = shadow.run_scan(main_state=main_state)

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
        pokemon, lorcana, stock, preorders = shadow._counts(products)
        self.assertEqual((pokemon, lorcana, stock, preorders), (3, 1, 3, 0))


if __name__ == "__main__":
    unittest.main()
