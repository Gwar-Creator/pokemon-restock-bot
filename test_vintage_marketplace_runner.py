"""No-network tests of official-only shortlist runner."""
import unittest
from unittest.mock import Mock

from vintage_marketplace_runner import discover
from vintage_tradera_quality import AUDIT_QUERIES


def item(i, title):
    return {"id": i, "shortDescription": title,
            "itemUrl": f"http://www.tradera.com/item/1001342/{i}"}


class VintageRunnerTests(unittest.TestCase):
    def test_official_only_and_no_buy_labels(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"errors": [], "items": [
            item(1, "Pokemon WotC vintage lot"),
            item(2, "Pokemon modern VMAX collection"),
            item(3, "Pokemon Aquapolis binder"),
            item(4, "Pokemon Fossil Kingler 38/62"),
        ]}
        client = Mock(return_value=response)
        report = discover(" APP\n", " SECRET\n", client)
        self.assertEqual(client.call_count, len(AUDIT_QUERIES))
        self.assertEqual(report["selected_lot_count"], 2)
        self.assertEqual(len(report["selected"]), 2)
        self.assertEqual(report["discord_alerts"], 0)
        self.assertTrue(all(r["status"] == "UNVERIFIED_MANUAL_REVIEW"
                            for r in report["selected"]))
        self.assertTrue(all(r["buy_bid_signal"] is None
                            for r in report["selected"]))
        self.assertNotIn("SECRET", str(report))
        for call in client.call_args_list:
            self.assertEqual(call.args[0], "https://api.tradera.com/v4/search")
            self.assertEqual(call.kwargs["headers"]["X-App-Key"], "SECRET")

    def test_empty_credentials_fail_before_network(self):
        client = Mock()
        with self.assertRaises(ValueError):
            discover(" \n", "KEY", client)
        client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
