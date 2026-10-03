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


class _FakeAvailabilityResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAvailabilitySession:
    def __init__(self, payload):
        self._payload = payload

    def get(self, *args, **kwargs):
        return _FakeAvailabilityResponse(self._payload)


class LocalStockAvailabilityResilienceTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "api_url": "https://api.example.test",
            "api_token": "test-token",
        }
        self.old_stocks = {
            "1659": {"name": "Bilka Esbjerg", "stock": 21},
            "1662": {"name": "Bilka Kolding", "stock": 28},
        }

    def test_empty_availability_payload_is_rejected_instead_of_zeroing_stock(self):
        with self.assertRaisesRegex(RuntimeError, "tom liste"):
            local.get_store_stocks(
                "bilka",
                self.config,
                "11406830-EA",
                _FakeAvailabilitySession([]),
                old_stocks=self.old_stocks,
            )

    def test_missing_target_stores_preserve_previous_stock(self):
        payload = [
            {
                "store": {
                    "name": "Bilka Vejle",
                    "sapSiteId": "1661",
                },
                "currentStock": 6,
            }
        ]
        stocks, national = local.get_store_stocks(
            "bilka",
            self.config,
            "11406830-EA",
            _FakeAvailabilitySession(payload),
            old_stocks=self.old_stocks,
        )

        self.assertEqual(stocks["1659"]["stock"], 21)
        self.assertEqual(stocks["1662"]["stock"], 28)
        self.assertEqual(national["1661"]["stock"], 6)

    def test_nonempty_payload_with_positive_store_is_accepted(self):
        payload = [
            {
                "store": {
                    "name": "Bilka Vejle",
                    "sapSiteId": "1661",
                },
                "currentStock": 6,
            }
        ]
        stocks, national = local.get_store_stocks(
            "bilka",
            self.config,
            "11406830-EA",
            _FakeAvailabilitySession(payload),
            old_stocks=self.old_stocks,
        )
        self.assertEqual(national["1661"]["stock"], 6)
        self.assertEqual(stocks["1659"]["stock"], 21)
        self.assertEqual(stocks["1662"]["stock"], 28)

    def test_explicit_target_store_zero_is_kept_as_real_zero(self):
        payload = [
            {
                "store": {
                    "name": "Bilka Esbjerg",
                    "sapSiteId": "1659",
                },
                "currentStock": 0,
            },
            {
                "store": {
                    "name": "Bilka Kolding",
                    "sapSiteId": "1662",
                },
                "currentStock": 0,
            },
        ]
        stocks, _ = local.get_store_stocks(
            "bilka",
            self.config,
            "11406830-EA",
            _FakeAvailabilitySession(payload),
            old_stocks=self.old_stocks,
        )

        self.assertEqual(stocks["1659"]["stock"], 0)
        self.assertEqual(stocks["1662"]["stock"], 0)


if __name__ == "__main__":
    unittest.main()
