import importlib.util
import unittest


spec = importlib.util.spec_from_file_location("market_radar_v6", "market_radar_v6.py")
market_radar_v6 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(market_radar_v6)


class MarketRadarV6Tests(unittest.TestCase):
    def test_generic_collection_variant_is_blocked(self):
        row = {
            "match_methods": ["exact"],
            "dk_name": "Ascended Heroes Collection",
            "type": "COLLECTION",
            "family": "COLLECTION",
            "cm_name": "Ascended Heroes Collection",
            "cm_type": "COLLECTION",
        }
        ok, status = market_radar_v6._identity_gate(row)
        self.assertFalse(ok)
        self.assertEqual(status, "UNRESOLVED_VARIANT")

    def test_specific_collection_can_pass_identity_gate(self):
        row = {
            "match_methods": ["exact"],
            "dk_name": "Team Rocket's Mewtwo ex Box",
            "type": "EX BOX",
            "family": "COLLECTION",
            "cm_name": "Team Rocket's Mewtwo ex Box",
            "cm_type": "EX BOX",
        }
        ok, status = market_radar_v6._identity_gate(row)
        self.assertTrue(ok)
        self.assertEqual(status, "EXACT_PRODUCT")

    def test_fuzzy_match_is_never_actionable_identity(self):
        row = {
            "match_methods": ["fuzzy"],
            "dk_name": "Team Rocket's Mewtwo ex Box",
            "type": "EX BOX",
            "family": "COLLECTION",
            "cm_name": "Team Rocket's Mewtwo ex Box",
            "cm_type": "EX BOX",
        }
        ok, status = market_radar_v6._identity_gate(row)
        self.assertFalse(ok)
        self.assertEqual(status, "NON_EXACT_CARDMARKET_MATCH")

    def test_damage_comments_are_rejected(self):
        self.assertTrue(market_radar_v6._comment_has_damage("Box damaged in one corner"))
        self.assertTrue(market_radar_v6._comment_has_damage("Verpackung beschädigt"))
        self.assertFalse(market_radar_v6._comment_has_damage("Factory sealed"))

    def test_foreign_delivery_is_not_assumed(self):
        article = {
            "seller": {
                "username": "GermanSeller",
                "address": {"country": "D"},
            }
        }
        ok, reason = market_radar_v6._delivery_verified(article, set())
        self.assertFalse(ok)
        self.assertEqual(reason, "foreign_shipping_not_verified")

    def test_danish_seller_delivery_is_verified(self):
        article = {
            "seller": {
                "username": "DanishSeller",
                "address": {"country": "DK"},
            }
        }
        ok, reason = market_radar_v6._delivery_verified(article, set())
        self.assertTrue(ok)
        self.assertEqual(reason, "seller_in_denmark")

    def test_allowlisted_foreign_seller_is_verified(self):
        article = {
            "seller": {
                "username": "KnownGoodSeller",
                "address": {"country": "D"},
            }
        }
        ok, reason = market_radar_v6._delivery_verified(article, {"knowngoodseller"})
        self.assertTrue(ok)
        self.assertEqual(reason, "seller_allowlisted_for_dk")

    def test_clean_english_listing_survives_filters(self):
        article = {
            "idArticle": 123,
            "idLanguage": 1,
            "price": 40.0,
            "comments": "Factory sealed",
            "seller": {
                "username": "DanishSeller",
                "address": {"country": "DK"},
                "sellCount": 100,
                "onVacation": False,
            },
        }
        valid, rejected = market_radar_v6._validate_articles([article], set())
        self.assertEqual(len(valid), 1)
        self.assertEqual(valid[0]["price_eur"], 40.0)
        self.assertEqual(rejected["damaged_or_opened"], 0)

    def test_damaged_cheapest_listing_is_removed(self):
        damaged = {
            "idArticle": 1,
            "idLanguage": 1,
            "price": 30.0,
            "comments": "Damaged box",
            "seller": {
                "username": "DanishSeller1",
                "address": {"country": "DK"},
                "sellCount": 100,
                "onVacation": False,
            },
        }
        clean = {
            "idArticle": 2,
            "idLanguage": 1,
            "price": 40.0,
            "comments": "Factory sealed",
            "seller": {
                "username": "DanishSeller2",
                "address": {"country": "DK"},
                "sellCount": 100,
                "onVacation": False,
            },
        }
        valid, rejected = market_radar_v6._validate_articles([damaged, clean], set())
        self.assertEqual(len(valid), 1)
        self.assertEqual(valid[0]["price_eur"], 40.0)
        self.assertEqual(rejected["damaged_or_opened"], 1)


if __name__ == "__main__":
    unittest.main()
