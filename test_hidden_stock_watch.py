import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import hidden_stock_watch as hidden


def product(sku="10831914-EA", name="Pokémon TCG Charizard ex Super-Premium Collection",
            series=None, type_="COLLECTION"):
    return {
        "id": "200291393", "name": name, "sku": sku, "type": type_,
        "series": series, "price": 649, "url": "https://www.br.dk/test",
    }


def observation(stock, store_id="2021", store_name="BR Kolding"):
    return [(product(), {store_id: {"name": store_name, "stock": stock}})]


class HiddenStockPolicyTests(unittest.TestCase):
    def test_first_site_baseline_is_silent_even_when_positive(self):
        state = hidden.empty_state()
        pending = hidden.merge_site(state, "br", observation(4), "now")
        key = hidden.item_key("br", "10831914-EA", "2021")
        self.assertEqual(pending, {})
        self.assertEqual(state["items"][key]["stock"], 4)
        self.assertTrue(state["items"][key]["notified"])

    def test_new_stock_requires_two_consecutive_positive_scans(self):
        state = hidden.empty_state()
        hidden.merge_site(state, "br", observation(0), "now")
        key = hidden.item_key("br", "10831914-EA", "2021")
        self.assertNotIn(key, state["items"])
        self.assertEqual(hidden.merge_site(state, "br", observation(4), "now"), {})
        self.assertEqual(state["items"][key]["streak"], 1)
        confirmed = hidden.merge_site(state, "br", observation(4), "now")
        self.assertEqual(confirmed, {("br", "10831914-EA"): [key]})
        self.assertEqual(state["items"][key]["streak"], 2)
        self.assertFalse(state["items"][key]["notified"])

    def test_unavailable_intermediate_scan_breaks_positive_streak(self):
        state = hidden.empty_state()
        hidden.merge_site(state, "br", [], "now")
        hidden.merge_site(state, "br", observation(4), "now")
        hidden.merge_site(state, "br", [], "now")
        self.assertEqual(hidden.merge_site(state, "br", observation(4), "now"), {})
        self.assertEqual(state["items"]["br|10831914-EA|2021"]["streak"], 1)

    def test_explicit_zero_rearms_after_baseline(self):
        state = hidden.empty_state()
        hidden.merge_site(state, "br", observation(4), "now")
        hidden.merge_site(state, "br", observation(0), "now")
        key = "br|10831914-EA|2021"
        self.assertEqual(state["items"][key]["stock"], 0)
        self.assertFalse(state["items"][key]["notified"])
        self.assertEqual(hidden.merge_site(state, "br", observation(1), "now"), {})
        confirmed = hidden.merge_site(state, "br", observation(1), "now")
        self.assertEqual(confirmed, {("br", "10831914-EA"): [key]})

    def test_legacy_stock_does_not_turn_into_new_alert(self):
        state = hidden.empty_state()
        hidden.merge_site(state, "br", observation(4), "now")
        for _ in range(3):
            self.assertEqual(hidden.merge_site(state, "br", observation(4), "now"), {})
        self.assertTrue(state["items"]["br|10831914-EA|2021"]["notified"])

    def test_filtered_perfect_order_booster_never_enters_alert_candidates(self):
        state = hidden.empty_state()
        hidden.merge_site(state, "br", [], "now")
        pack = product("test-sku", "Pokémon Perfect Order booster pack",
                       "Mega Evolution: Perfect Order", "BOOSTER PACK")
        data = [(pack, {"2021": {"name": "BR Kolding", "stock": 4}})]
        hidden.merge_site(state, "br", data, "now")
        self.assertEqual(hidden.merge_site(state, "br", data, "now"), {})
        self.assertEqual(state["items"]["br|test-sku|2021"]["stock"], 4)

    def test_no_discord_for_unconfirmed_first_positive_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            samples = iter([
                (100, 1, 0, observation(0)),
                (100, 1, 0, observation(4)),
                (100, 1, 0, observation(4)),
            ])
            def fake_fetch(site):
                if site == "br":
                    return next(samples)
                return 100, 0, 0, []
            with (patch.object(hidden, "STATE_PATH", state_path),
                  patch.object(hidden, "fetch_site", side_effect=fake_fetch),
                  patch.object(hidden, "send_alert") as send):
                hidden.main()
                send.assert_not_called()
                hidden.main()
                send.assert_not_called()
                hidden.main()
                send.assert_called_once()
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(saved["items"]["br|10831914-EA|2021"]["notified"])

    def test_suspicious_catalog_snapshot_is_rejected(self):
        with patch.object(hidden.local, "get_frontend_config", return_value={}), \
             patch.object(hidden.local, "get_algolia_candidates", return_value=([], 4)):
            with self.assertRaisesRegex(RuntimeError, "mistænkeligt lille"):
                hidden.fetch_site("br")


class HiddenStockAPIValidationTests(unittest.TestCase):
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    def test_empty_result_is_unknown_not_zero(self):
        with patch.object(hidden.requests, "get", return_value=self.FakeResponse([])):
            self.assertIsNone(hidden.fetch_detailed_stocks(
                "br", {"api_url": "https://example.test", "api_token": "secret"},
                product(),
            ))

    def test_response_with_positive_and_explicit_zero(self):
        payload = [
            {"store": {"sapSiteId": "2021", "name": "BR Kolding"}, "currentStock": 4},
            {"store": {"sapSiteId": "2011", "name": "BR Esbjerg"}, "currentStock": 0},
        ]
        with patch.object(hidden.requests, "get", return_value=self.FakeResponse(payload)):
            stocks = hidden.fetch_detailed_stocks(
                "br", {"api_url": "https://example.test", "api_token": "secret"},
                product(),
            )
        self.assertEqual(stocks["2021"]["stock"], 4)
        self.assertEqual(stocks["2011"]["stock"], 0)


if __name__ == "__main__":
    unittest.main()
