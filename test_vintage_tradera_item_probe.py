"""Safety tests for bounded, read-only official Tradera detail schema probe."""
import json
import unittest
from unittest.mock import Mock

import requests
from vintage_tradera_item_probe import (
    SAMPLE_IDS, ITEMS_URL, probe_item, probe_samples,
)


class TraderaItemProbeTests(unittest.TestCase):
    def test_public_metadata_only_no_real_values_or_seller_leak(self):
        body = {
            "id": 123,
            "description": "A SECRET expensive vintage lot",
            "seller": {"alias": "SELLER_SECRET", "email": "PII@example.invalid"},
            "images": [{"url": "SECRET_IMAGE", "id": 15}],
            "price": 999,
        }
        response = Mock(status_code=200)
        response.json.return_value = body
        transport = Mock(return_value=response)
        result = probe_item(SAMPLE_IDS[0], "  APP  ", " KEY\n ", transport)
        text = json.dumps(result)
        self.assertIn("seller", text)
        self.assertIn("images", text)
        self.assertIn("description", text)
        for secret in ("SECRET", "PII@example.invalid", "999", "123"):
            self.assertNotIn(secret, text)
        args, kwargs = transport.call_args
        self.assertEqual(args, (f"{ITEMS_URL}/{SAMPLE_IDS[0]}",))
        self.assertEqual(kwargs["headers"]["X-App-Id"], "APP")
        self.assertEqual(kwargs["headers"]["X-App-Key"], "KEY")
        self.assertEqual(kwargs["timeout"], 20)

    def test_id_guard_prevents_network(self):
        transport = Mock()
        for bad in ("123", 0, -1, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                probe_item(bad, "A", "B", transport)
        transport.assert_not_called()

    def test_status_json_and_network_errors_are_redacted(self):
        response = Mock(status_code=403, text="SECRET RESPONSE")
        with self.assertRaisesRegex(RuntimeError, "HTTP 403") as caught:
            probe_item(12, "APP", "KEY", Mock(return_value=response))
        self.assertNotIn("SECRET", str(caught.exception))

        response = Mock(status_code=200)
        response.json.side_effect = requests.exceptions.JSONDecodeError(
            "SECRET ERROR", "<SECRET>", 0
        )
        with self.assertRaisesRegex(RuntimeError, "invalid JSON") as caught:
            probe_item(12, "APP", "KEY", Mock(return_value=response))
        self.assertNotIn("SECRET", str(caught.exception))

        broken = Mock(side_effect=requests.ConnectionError("SECRET URL"))
        with self.assertRaisesRegex(RuntimeError, "network request failed") as caught:
            probe_item(12, "APP", "KEY", broken)
        self.assertNotIn("SECRET", str(caught.exception))

    def test_four_fixed_calls_no_discord_no_bids(self):
        response = Mock(status_code=200)
        response.json.return_value = {"id": 12, "title": "SECRET CARD"}
        client = Mock(return_value=response)
        report = probe_samples("ID", "KEY", client)
        self.assertEqual(client.call_count, 4)
        self.assertEqual(len(report["results"]), len(SAMPLE_IDS))
        self.assertEqual(report["buy_bid_alerts"], 0)
        self.assertNotIn("SECRET", json.dumps(report))
        for call in client.call_args_list:
            self.assertEqual(call.args[0].split("/")[2], "api.tradera.com")
            self.assertEqual(call.kwargs["headers"]["Accept"], "application/json")

    def test_empty_credentials_fail_before_request(self):
        client = Mock()
        with self.assertRaises(ValueError):
            probe_item(12, "  ", "KEY", client)
        client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
