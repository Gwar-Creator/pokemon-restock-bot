"""Ensure no Discord publish and exact existing-channel verification."""
import unittest
from unittest.mock import Mock

from vintage_marketplace_webhook_check import verify_webhook_destination

URL = "https://discord.com/api/webhooks/123456789/opaqueSecretToken12345"


class WebhookDestinationTests(unittest.TestCase):
    def test_channel_match_succeeds_only_with_exact_external_expectation(self):
        response = Mock(status_code=200)
        response.json.return_value = {"channel_id": "987654321",
                                      "name": "PRIVATE", "token": "SECRET"}
        transport = Mock(return_value=response)
        self.assertEqual(verify_webhook_destination(URL, "987654321", transport),
                         "VERIFIED")
        transport.assert_called_once()
        self.assertEqual(transport.call_args.kwargs["headers"],
                         {"Accept": "application/json"})
        self.assertEqual(transport.call_args.kwargs["timeout"], 10)
        self.assertEqual(verify_webhook_destination(URL, "987654322", transport),
                         "NOT_VERIFIED")

    def test_missing_expected_channel_cannot_trigger_probe(self):
        for expected in (None, "", "my-channel", "987654321\n"):
            with self.subTest(expected=expected):
                client = Mock()
                self.assertEqual(verify_webhook_destination(URL, expected, client),
                                 "NOT_VERIFIED")
                client.assert_not_called()

    def test_reject_wrong_or_impersonated_webhook_without_network(self):
        values = (
            "https://discord.com.evil.invalid/api/webhooks/123/tokenXXXXXXXX",
            "http://discord.com/api/webhooks/123/tokenXXXXXXXX",
            "https://discord.com/api/webhooks/123/tokenXXXXXXXX?wait=true",
            "https://discord.com/api/webhooks/123/tokenXXXXXXXX#fragment",
            "https://discord.com:8443/api/webhooks/123/tokenXXXXXXXX",
            "https://user@discord.com/api/webhooks/123/tokenXXXXXXXX",
            "https://discord.com/api/webhooks/123",
            "https://discord.com/api/webhooks/invalid/tokenXXXXXXXX",
            "https://discord.com/api/webhooks/123/x",
        )
        for value in values:
            with self.subTest(value=value):
                client = Mock()
                self.assertEqual(
                    verify_webhook_destination(value, "987654321", client),
                    "NOT_VERIFIED",
                )
                client.assert_not_called()

    def test_failed_http_invalid_json_and_unknown_return_no_identity(self):
        for result in (Mock(status_code=403),
                       Mock(status_code=200, json=Mock(return_value={})),
                       Mock(status_code=200, json=Mock(return_value=["no"]))):
            self.assertEqual(
                verify_webhook_destination(URL, "987654321", Mock(return_value=result)),
                "NOT_VERIFIED",
            )


if __name__ == "__main__":
    unittest.main()
