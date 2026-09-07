import unittest

import early_intel_shadow as intel


class EarlyIntelShadowTests(unittest.TestCase):
    def test_br_config_uses_fixed_index_constant(self):
        shared = {
            "get_br_frontend_config": lambda: {
                "algolia_app_id": "APP123",
                "algolia_api_key": "KEY123",
            },
            "BR_BASE": "https://www.br.dk",
            "BR_ALGOLIA_INDEX": "prod_BR_PRODUCTS",
        }
        config = intel.salling_config(shared, "br")
        self.assertEqual(config["index"], "prod_BR_PRODUCTS")
        self.assertEqual(config["app_id"], "APP123")
        self.assertEqual(config["api_key"], "KEY123")

    def test_proshop_research_filter_keeps_high_signal_sealed(self):
        self.assertTrue(
            intel.proshop_research_allowed(
                "Pokemon TCG Mega Charizard X ex Ultra Premium Collection"
            )
        )
        self.assertTrue(
            intel.proshop_research_allowed(
                "Pokemon TCG Mega Evolution Pitch Black Elite Trainer Box"
            )
        )
        self.assertTrue(
            intel.proshop_research_allowed(
                "Pokemon TCG Mega Greninja ex Premium Collection"
            )
        )
        self.assertFalse(
            intel.proshop_research_allowed("Pokemon TCG Portfolio 9 P Pikachu")
        )
        self.assertFalse(
            intel.proshop_research_allowed("Pokemon TCG Deluxe Battle Deck Ninetales ex")
        )

    def test_proshop_badge_belongs_to_following_product(self):
        text = (
            "[Pokemon TCG Mega Charizard X ex Ultra Premium Collection description]"
            "(https://www.proshop.dk/Pokemon/Pokemon-TCG-Mega-Charizard-X-ex-Ultra-Premium-Collection/3417744)\n"
            "Bestillingsvare, leveringstiden kan ikke oplyses\n"
            "* NYHED\n"
            "[Pokemon TCG Mega Evolution Pitch Black Elite Trainer Box description]"
            "(https://www.proshop.dk/Pokemon/Pokemon-TCG-Mega-Evolution-Pitch-Black-Elite-Trainer-Box/3470001)\n"
            "Bestilt: forventet på lager 17-09-2026\n"
            "899,00 kr.\n"
        )
        products = intel.parse_proshop_reader(text)
        first = products["3417744"]
        second = products["3470001"]

        self.assertFalse(first["new_badge"])
        self.assertTrue(second["new_badge"])
        self.assertEqual(first["name"], "Pokemon TCG Mega Charizard X ex Ultra Premium Collection")
        self.assertEqual(second["expected_stock_date"], "17-09-2026")
        self.assertEqual(second["status"], "BESTILT_DATO")
        self.assertEqual(second["stage"], "INBOUND_DATED")
        self.assertEqual(second["price"], 899.0)

    def test_epoch_only_salling_change_is_not_event_history(self):
        old = {
            "1": {
                "id": "1",
                "name": "Pokemon TCG Test Elite Trainer Box",
                "epoch_updated_at": 100,
                "stage": "PREPARED",
            }
        }
        new = {
            "1": {
                "id": "1",
                "name": "Pokemon TCG Test Elite Trainer Box",
                "epoch_updated_at": 200,
                "stage": "PREPARED",
            }
        }
        events = intel.report_source("bilka", old, new)
        self.assertEqual(events, [])

    def test_salling_stage_detects_hidden_stock(self):
        product = {
            "stock_count_online": 4,
            "in_stock_stores_count": 0,
            "is_exposed": False,
        }
        self.assertEqual(intel.salling_stage(product), "HIDDEN_STOCK")

    def test_cross_salling_groups_same_sku(self):
        sources = {
            "br": {
                "11": {
                    "id": "11",
                    "sku": "SKU-1",
                    "name": "Pokemon TCG Test Elite Trainer Box",
                    "stage": "PREPARED",
                    "sales_price": 399.0,
                }
            },
            "bilka": {
                "22": {
                    "id": "22",
                    "sku": "SKU-1",
                    "name": "Pokemon TCG Test Elite Trainer Box",
                    "stage": "HIDDEN_STOCK",
                    "sales_price": 399.0,
                    "stock_count_online": 5,
                }
            },
            "foetex": {},
        }
        cross = intel.build_cross_salling(sources)
        self.assertEqual(set(cross["SKU-1"]["sources"]), {"br", "bilka"})
        self.assertEqual(cross["SKU-1"]["sources"]["bilka"]["stage"], "HIDDEN_STOCK")


if __name__ == "__main__":
    unittest.main()
