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


class HiddenStockLocationPolicyTests(unittest.TestCase):
    def test_all_four_approved_cities_across_retailers(self):
        accepted = (
            "BR Kolding",
            "BR Esbjerg",
            "føtex Fredericia, Venusvej",
            "føtex Fredericia City",
            "Bilka Vejle",
            "føtex Kolding Syd",
        )
        for name in accepted:
            with self.subTest(store=name):
                self.assertTrue(hidden.is_alert_store(name))

    def test_remote_and_partial_city_names_are_excluded(self):
        rejected = (
            "føtex Østerbro Centret",
            "BR Fields",
            "BR Slagelse",
            "BR Viborg",
            "BR Holbæk",
            "BR Vejen",
            "BR Brørup",
            "BR Vejleby",
            "",
            None,
        )
        for name in rejected:
            with self.subTest(store=name):
                self.assertFalse(hidden.is_alert_store(name))

    def test_nonlocal_stock_is_tracked_but_never_candidate(self):
        state = hidden.empty_state()
        hidden.merge_site(state, "foetex", [(product(), {
            "1383": {"name": "føtex Østerbro Centret", "stock": 0}
        })], "now")
        distant = [(product(), {
            "1383": {"name": "føtex Østerbro Centret", "stock": 1}
        })]
        hidden.merge_site(state, "foetex", distant, "now")
        pending = hidden.merge_site(state, "foetex", distant, "now")
        self.assertEqual(pending, {})
        key = hidden.item_key("foetex", "10831914-EA", "1383")
        self.assertEqual(state["items"][key]["stock"], 1)
        self.assertEqual(state["items"][key]["streak"], 2)
        self.assertFalse(state["items"][key]["notified"])

    def test_mixed_store_alert_only_contains_local_locations(self):
        from unittest.mock import Mock
        local_row = {
            "site": "foetex", "store": "føtex Fredericia City", "stock": 2,
            "price": 250, "name": "Pokémon Collection", "product_id": "123",
            "sku": "ABC",
        }
        remote_row = {**local_row, "store": "føtex Østerbro Centret", "stock": 12}
        posted = Mock()
        posted.raise_for_status.return_value = None
        with patch.object(hidden, "WEBHOOK", "https://example.test/webhook"), \
             patch.object(hidden.requests, "post", return_value=posted) as api:
            hidden.send_alert([remote_row, local_row])
        msg = api.call_args.kwargs["json"]["embeds"][0]
        self.assertIn("Fredericia City", msg["fields"][0]["value"])
        self.assertNotIn("Østerbro", json.dumps(msg, ensure_ascii=False))

    def test_remote_only_alert_is_rejected(self):
        remote = {"site": "br", "store": "BR Slagelse", "stock": 4}
        with patch.object(hidden, "WEBHOOK", "https://example.test/webhook"), \
             patch.object(hidden.requests, "post") as api:
            with self.assertRaisesRegex(ValueError, "no approved local"):
                hidden.send_alert([remote])
            api.assert_not_called()

    def test_main_does_not_dispatch_remote_pending_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "hidden.json"
            state = hidden.empty_state()
            distant = [(product(), {
                "1383": {"name": "føtex Østerbro Centret", "stock": 1},
            })]
            hidden.merge_site(state, "foetex", [(product(), {
                "1383": {"name": "føtex Østerbro Centret", "stock": 0},
            })], "now")
            hidden.merge_site(state, "foetex", distant, "now")
            hidden.merge_site(state, "foetex", distant, "now")
            state_path.write_text(json.dumps(state), encoding="utf-8")
            def fake_fetch(site):
                if site == "foetex":
                    return 194, 1, 0, distant
                return 194, 0, 0, []
            with patch.object(hidden, "STATE_PATH", state_path), \
                 patch.object(hidden, "fetch_site", side_effect=fake_fetch), \
                 patch.object(hidden, "send_alert") as send:
                hidden.main()
                send.assert_not_called()


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

    def test_malformed_count_is_unknown_not_zero(self):
        payload = [
            {"store": {"sapSiteId": "2021", "name": "BR Kolding"},
             "currentStock": "n/a"},
        ]
        with patch.object(hidden.requests, "get", return_value=self.FakeResponse(payload)):
            result = hidden.fetch_detailed_stocks(
                "br", {"api_url": "https://example.test", "api_token": "secret"},
                product(),
            )
        self.assertIsNone(result)

    def test_independent_store_keys_across_three_chains(self):
        self.assertNotEqual(
            hidden.item_key("br", "10831914-EA", "2021"),
            hidden.item_key("bilka", "10831914-EA", "2021")
        )
        self.assertNotEqual(
            hidden.item_key("bilka", "10831914-EA", "2021"),
            hidden.item_key("foetex", "10831914-EA", "2021")
        )

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
