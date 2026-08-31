import importlib.util
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
                    "family": "ETB",
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

    def test_loose_boosters_and_tins_are_out(self):
        self.assertIsNone(
            market_radar.infer_type("Destined Rivals Booster Pack", "POKÉMON")
        )
        self.assertIsNone(
            market_radar.infer_type("Kanto Friends Mini Tin Display", "POKÉMON")
        )
        self.assertIsNone(
            market_radar.infer_type("Pokeball Tin", "POKÉMON")
        )

    def test_named_collections_stay_in(self):
        self.assertEqual(
            market_radar.infer_type(
                "Mega Greninja ex Premium Collection",
                "POKÉMON",
            ),
            "PREMIUM COLLECTION",
        )
        self.assertEqual(
            market_radar.canonical_name(
                "Mega Greninja ex Premium Collection",
                "PREMIUM COLLECTION",
            ),
            "mega greninja ex",
        )

    def test_modern_base_set_cannot_match_vintage_base_set(self):
        modern = market_radar.canonical_name(
            "Pokemon Scarlet & Violet Base Set - Booster Box",
            "BOOSTER BOX",
        )
        vintage = market_radar.canonical_name(
            "Base Set Booster Box",
            "BOOSTER BOX",
        )
        self.assertNotEqual(modern, vintage)
        self.assertFalse(market_radar._match_guard(modern, vintage))

    def test_lorcana_is_out_of_v3_scope(self):
        self.assertIsNone(
            market_radar.infer_type("Lorcana Booster Box", "LORCANA")
        )

    def test_cardmarket_reference_prefers_trend(self):
        reference, kind = market_radar._cardmarket_reference({
            "low_eur": 95.0,
            "trend_eur": 130.52,
        })
        self.assertEqual(reference, 130.52)
        self.assertEqual(kind, "trend")

    def test_alias_groups_merge_by_cardmarket_product_id(self):
        cardmarket = {
            "idProduct": 884751,
            "name": "Mega Greninja ex Premium Collection",
            "type": "PREMIUM COLLECTION",
            "family": "COLLECTION",
            "low_eur": 27.5,
            "trend_eur": 42.54,
            "match_score": 1.0,
            "match_method": "exact",
        }
        raw = [
            {
                "game": "POKÉMON",
                "best": {"name": "Mega Greninja ex Premium Collection Box"},
                "offers": [
                    {
                        "shop": "POKEMONPORTALEN", "price": 499.0,
                        "url": "https://example.invalid/a", "name": "Mega Greninja ex Premium Collection Box",
                        "type": "PREMIUM COLLECTION", "family": "COLLECTION",
                    }
                ],
                "cardmarket": dict(cardmarket),
            },
            {
                "game": "POKÉMON",
                "best": {"name": "Pokémon TCG: Mega Greninja ex Premium Collection"},
                "offers": [
                    {
                        "shop": "NOSTALGIC", "price": 529.0,
                        "url": "https://example.invalid/b", "name": "Pokémon TCG: Mega Greninja ex Premium Collection",
                        "type": "PREMIUM COLLECTION", "family": "COLLECTION",
                    }
                ],
                "cardmarket": dict(cardmarket),
            },
        ]
        rows = market_radar.consolidate_cardmarket_matches(raw)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["cm_product_id"], 884751)
        self.assertEqual(rows[0]["dk_price"], 499.0)
        self.assertEqual(rows[0]["shops"], 2)
        self.assertEqual(rows[0]["alias_groups_merged"], 2)
        self.assertEqual(rows[0]["cm_reference_kind"], "trend")


if __name__ == "__main__":
    unittest.main()
