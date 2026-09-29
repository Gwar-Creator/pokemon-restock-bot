import unittest

import local_stock_watch as local


class LocalStockSignalPolicyTests(unittest.TestCase):
    def test_perfect_order_loose_booster_pack_is_muted(self):
        self.assertFalse(
            local.local_stock_signal_allowed(
                {
                    "name": "Pokémon TCG booster pack - samlekort",
                    "type": "BOOSTER PACK",
                    "series": "Mega Evolution: Perfect Order",
                }
            )
        )

    def test_perfect_order_booster_bundle_is_still_allowed(self):
        self.assertTrue(
            local.local_stock_signal_allowed(
                {
                    "name": "Pokémon Perfect Order Booster Bundle",
                    "type": "BOOSTER BUNDLE",
                    "series": "Mega Evolution: Perfect Order",
                }
            )
        )

    def test_other_loose_booster_pack_is_not_globally_muted(self):
        self.assertTrue(
            local.local_stock_signal_allowed(
                {
                    "name": "Pokémon TCG booster pack - samlekort",
                    "type": "BOOSTER PACK",
                    "series": "Mega Evolution: Ascended Heroes",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
