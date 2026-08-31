import importlib.util
import os
import unittest


spec = importlib.util.spec_from_file_location("market_radar", "market_radar.py")
market_radar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(market_radar)


class MarketRadarTests(unittest.TestCase):
    def test_foreign_product_is_blocked(self):
        self.assertIsNone(
            market_radar.infer_type(
                "Destined Rivals Elite Trainer Box German",
                "POKÉMON",
            )
        )

    def test_pokemon_center_etb_stays_separate(self):
        self.assertEqual(
            market_radar.infer_type(
                "Destined Rivals Pokémon Center Elite Trainer Box",
                "POKÉMON",
            ),
            "PC ETB",
        )

    def test_danish_single_shop_is_kept(self):
        state = {
            "coolshop": {
                "1": {
                    "name": "Pokémon TCG: Destined Rivals Elite Trainer Box",
                    "game": "POKÉMON",
                    "price": 828,
                    "in_stock": True,
                    "url": "https://example.invalid/dri",
                }
            }
        }
        groups = market_radar.group_danish_offers(
            market_radar.collect_danish_offers(state)
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["best"]["price"], 828)
        self.assertEqual(len(groups[0]["offers"]), 1)

    def test_exact_cardmarket_match_is_preferred(self):
        group = {
            "key": ("POKÉMON", "ETB", "destined rivals"),
            "best": {},
            "offers": [],
        }
        rows = {
            "POKÉMON": [
                {
                    "idProduct": 818585,
                    "name": "Destined Rivals Elite Trainer Box",
                    "type": "ETB",
                    "canonical": "destined rivals",
                    "low_eur": 97.98,
                    "trend_eur": 156.73,
                }
            ]
        }
        result = market_radar.match_cardmarket(group, rows)
        self.assertEqual(result["idProduct"], 818585)
        self.assertEqual(result["match_method"], "exact")
        self.assertEqual(result["match_score"], 1.0)


if __name__ == "__main__":
    unittest.main()
