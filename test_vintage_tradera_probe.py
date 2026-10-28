"""Safety tests for a single Tradera API schema probe (no real network)."""
import json
import unittest
from unittest.mock import Mock

from vintage_tradera_probe import SEARCH_URL, SEARCH_QUERY, inspect_response, run_probe


class TraderaSafeProbeTests(unittest.TestCase):
    def test_only_schema_keys_and_lengths_are_returned(self):
        body = {
            "total": 5,
            "items": [{"id": 123, "title": "Private collection secret title", "seller": {
                "name": "Private seller", "email": "private@example.invalid"
            }}],
            "token": "SENSITIVE-VALUE",
        }
        result = inspect_response(body)
        serialized = json.dumps(result)
        self.assertIn("items", serialized)
        self.assertIn("length", serialized)
        for forbidden in ("Private collection", "private@example.invalid",
                          "SENSITIVE-VALUE", "Private seller", "123"):
            self.assertNotIn(forbidden, serialized)

    def test_one_readonly_api_request_with_headers_only(self):
        response = Mock(status_code=200)
        response.json.return_value = {"items": [{"id": 55, "title": "Card lot"}]}
        client = Mock(return_value=response)
        data = run_probe(app_id="APP123", app_key="TOPSECRET", transport=client)
        client.assert_called_once()
        args, kwargs = client.call_args
        self.assertEqual(args, (SEARCH_URL,))
        self.assertEqual(kwargs["params"], {"query": SEARCH_QUERY, "pageNumber": 0})
        self.assertEqual(kwargs["headers"]["X-App-Id"], "APP123")
        self.assertEqual(kwargs["headers"]["X-App-Key"], "TOPSECRET")
        self.assertEqual(kwargs["timeout"], 20)
        self.assertNotIn("TOPSECRET", json.dumps(data))

    def test_missing_credentials_stop_before_network(self):
        client = Mock()
        with self.assertRaisesRegex(RuntimeError, "Missing Tradera application secrets"):
            run_probe("", "", client)
        client.assert_not_called()

    def test_http_errors_do_not_dump_response_body(self):
        response = Mock(status_code=403, text="secret-key: SHOULD-NOT-LEAK")
        client = Mock(return_value=response)
        with self.assertRaisesRegex(RuntimeError, "HTTP 403") as context:
            run_probe("app", "secret", client)
        self.assertNotIn("SHOULD-NOT-LEAK", str(context.exception))

    def test_unknown_top_level_response_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            inspect_response(["unexpected", "listing"])

    def test_no_secrets_in_network_error(self):
        import requests
        client = Mock(side_effect=requests.RequestException(
            "secret-key: SHOULD-NOT-LEAK"
        ))
        with self.assertRaises(RuntimeError) as context:
            run_probe("app", "secret", client)
        self.assertEqual(str(context.exception), "Tradera network request failed")


if __name__ == "__main__":
    unittest.main()
