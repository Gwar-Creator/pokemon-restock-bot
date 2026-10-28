"""Offline tests for title-quality audit and fail-closed BUY/BYD eligibility."""
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from vintage_tradera_quality import (
    AUDIT_QUERIES, actionable_signal, audit_batches, classify_title, live_audit,
)


def row(i, title, url=None):
    return {
        "id": i, "shortDescription": title,
        "itemUrl": url or f"https://www.tradera.com/item/123/{i}",
        "sellerAlias": "not-for-output",
    }


class TraderaQualityTests(unittest.TestCase):
    def test_explicit_vintage_and_english_cards_are_title_matches(self):
        titles = (
            "Pokemon Base Set Jungle Fossil samling",
            "Pokemon Aquapolis English kort",
            "Pokemon Neo Destiny Light Arcanine",
            "Pokemon Gym Heroes binder",
            "Pokemon EX Ruby Sapphire kort",
            "Pokemon Skyridge lots",
            "Pokemon Expedition samling",
        )
        for title in titles:
            with self.subTest(title=title):
                self.assertEqual(classify_title(title)[0], "TITLE_VINTAGE")

    def test_swedish_listing_is_not_foreign_card_language(self):
        self.assertEqual(classify_title("Pokemon Fossil gamla kort samling")[0], "TITLE_VINTAGE")

    def test_modern_bulk_fakes_and_sealed_not_vintage(self):
        titles = (
            "Pokemon Prismatic samling",
            "Pokemon VMAX VSTAR samling",
            "Pokemon 151 bulk lot",
            "Pokemon Neo Destiny booster box",
            "Pokemon Base Set replica kort",
            "Pokemon japanska kort samling",
            "Pokemon samling 1000 kort 2026",
            "Pokemon Fossil sealed booster pack",
            "Lorcana Base Set samling",
        )
        for title in titles:
            with self.subTest(title=title):
                self.assertEqual(classify_title(title)[0], "EXCLUDED")

    def test_ambiguous_lots_not_dressed_up_as_verified_vintage(self):
        for title in ("Pokemon gammal mappe", "Pokemon samling 2004",
                      "Pokemon old cards lot"):
            self.assertEqual(classify_title(title)[0], "TITLE_UNCERTAIN")

    def test_audit_counts_dedupe_and_no_seller_output(self):
        result = audit_batches([
            ("first", [row(1, "Pokemon Fossil kort"), row(2, "Pokemon Prismatic samling"),
                       row(3, "Pokemon gammal samling"), row(4, "Lorcana")]),
            ("second", [row(1, "Pokemon Fossil kort"), row(5, "Pokemon Aquapolis kort"),
                        row(6, "Pokemon Neo Destiny kort", "https://example.invalid/6")]),
        ])
        self.assertEqual(result["scanned_rows"], 7)
        self.assertEqual(result["unique_valid_listings"], 5)
        self.assertEqual(result["duplicate_search_hits"], 1)
        self.assertEqual(result["malformed_or_unsafe_links"], 1)
        self.assertEqual(result["title_vintage"], 2)
        self.assertEqual(result["title_uncertain"], 1)
        self.assertEqual(result["title_excluded"], 2)
        self.assertEqual(result["buy_bid_alerts"], 0)
        self.assertIsNone(result["precision"])
        self.assertNotIn("not-for-output", str(result))
        self.assertLessEqual(len(result["public_review_samples"]), 20)

    def test_only_official_searches_and_no_discord_calls(self):
        response = Mock()
        response.json.return_value = {"errors": [], "items": [row(101, "Pokemon Jungle kort")]}
        response.raise_for_status.return_value = None
        transport = Mock(return_value=response)
        result = live_audit("APP", "KEY", transport)
        self.assertEqual(transport.call_count, len(AUDIT_QUERIES))
        for call, query in zip(transport.call_args_list, AUDIT_QUERIES):
            args, kwargs = call
            self.assertEqual(args, ("https://api.tradera.com/v4/search",))
            self.assertEqual(kwargs["params"], {"query": query, "pageNumber": 0})
            self.assertEqual(kwargs["headers"]["X-App-Key"], "KEY")
        self.assertEqual(result["unique_valid_listings"], 1)
        self.assertEqual(result["duplicate_search_hits"], len(AUDIT_QUERIES) - 1)

    def test_credentials_trimmed_like_successful_schema_probe(self):
        response = Mock()
        response.json.return_value = {"errors": [], "items": []}
        response.raise_for_status.return_value = None
        client = Mock(return_value=response)
        live_audit(" APP_ID \\n", " KEY_VALUE \\n", client)
        self.assertEqual(client.call_count, len(AUDIT_QUERIES))
        self.assertEqual(client.call_args.kwargs["headers"]["X-App-Id"], "APP_ID")
        self.assertEqual(client.call_args.kwargs["headers"]["X-App-Key"], "KEY_VALUE")
        with self.assertRaisesRegex(ValueError, "credentials are missing"):
            live_audit("  ", "KEY", client)

    def test_live_http_and_schema_failures_log_only_safe_status(self):
        import requests

        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError(
            "SECRET REQUEST URL", response=Mock(status_code=429))
        with self.assertRaises(RuntimeError) as caught:
            live_audit("APP", "SECRET", Mock(return_value=response))
        self.assertEqual(str(caught.exception),
                         "Official Tradera search HTTP 429 at query #1")
        self.assertNotIn("SECRET", str(caught.exception))

        response = Mock()
        response.raise_for_status.side_effect = requests.ConnectionError(
            "SECRET REQUEST HOST")
        with self.assertRaises(RuntimeError) as caught:
            live_audit("APP", "SECRET", Mock(return_value=response))
        self.assertEqual(str(caught.exception),
                         "Official Tradera search transport failure (ConnectionError) at query #1")
        self.assertNotIn("SECRET", str(caught.exception))

        for error_type, expected in (
            (requests.exceptions.ChunkedEncodingError, "ChunkedEncodingError"),
            (requests.exceptions.TooManyRedirects, "TooManyRedirects"),
        ):
            response = Mock()
            response.raise_for_status.side_effect = error_type("SECRET URL / HEADER")
            with self.subTest(error=expected), self.assertRaises(RuntimeError) as caught:
                live_audit("APP", "SECRET", Mock(return_value=response))
            self.assertEqual(str(caught.exception),
                             f"Official Tradera search transport failure ({expected}) at query #1")
            self.assertNotIn("SECRET", str(caught.exception))

        class UnregisteredRequestError(requests.RequestException):
            pass

        response = Mock()
        response.raise_for_status.side_effect = UnregisteredRequestError("SECRET")
        with self.assertRaises(RuntimeError) as caught:
            live_audit("APP", "SECRET", Mock(return_value=response))
        self.assertEqual(str(caught.exception),
                         "Official Tradera search transport failure (OtherRequestException) at query #1")

        response = Mock(status_code=200, headers={"Content-Type": "text/html; charset=utf-8"})
        response.raise_for_status.return_value = None
        response.json.side_effect = requests.exceptions.JSONDecodeError(
            "SECRET RAW RESPONSE", "<html>SECRET BODY</html>", 0)
        with self.assertRaises(RuntimeError) as caught:
            live_audit("APP", "SECRET", Mock(return_value=response))
        self.assertEqual(str(caught.exception),
                         "Official Tradera invalid JSON (HTTP 200, content type html) at query #1")
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertNotIn("<html>", str(caught.exception))

        response = Mock(status_code=200, headers={"Content-Type": "application/json"})
        response.raise_for_status.return_value = None
        response.json.side_effect = ValueError("SECRET JSON PARSE FAILURE")
        with self.assertRaises(RuntimeError) as caught:
            live_audit("APP", "SECRET", Mock(return_value=response))
        self.assertEqual(str(caught.exception),
                         "Official Tradera invalid JSON (HTTP 200, content type json) at query #1")
        self.assertNotIn("SECRET", str(caught.exception))

        response.json.side_effect = None
        response.json.return_value = {"items": {"unexpected": "schema"}}
        with self.assertRaises(RuntimeError) as caught:
            live_audit("APP", "SECRET", Mock(return_value=response))
        self.assertEqual(str(caught.exception),
                         "Official Tradera search response/schema failure at query #1")

    def test_fail_closed_buy_bid_without_human_evidence(self):
        listing = {"id": "10", "url": "https://www.tradera.com/item/123/10",
                   "title": "Pokemon Fossil samling"}
        self.assertIsNone(actionable_signal(listing, {}))
        self.assertIsNone(actionable_signal(listing, {"action": "KØB"}))
        now = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
        evidence = {
            "listing_id": "10", "action": "BYD", "human_approved": True,
            "card_ids_verified": True, "photos_front_back_verified": True,
            "language_english_verified": True, "condition_verified": True,
            "authenticity_verified": True, "seller_reputation_verified": True,
            "shipping_to_denmark_verified": True, "fees_verified": True,
            "current_total_verified": True, "eu_comparables_verified": True,
            "card_details": [{"name": "Vaporeon", "set": "Jungle", "number": "12",
                              "condition": "LP"}],
            "total_cost_sek": 400, "conservative_max_total_sek": 500,
            "reviewed_at": "2026-10-28T11:30:00+00:00",
        }
        self.assertEqual(actionable_signal(listing, evidence, now=now), "BYD")
        for flag in ("human_approved", "condition_verified",
                     "shipping_to_denmark_verified", "seller_reputation_verified",
                     "language_english_verified"):
            altered = {**evidence, flag: False}
            self.assertIsNone(actionable_signal(listing, altered, now=now))
        self.assertIsNone(actionable_signal(
            listing, {**evidence, "total_cost_sek": 600}, now=now))
        self.assertIsNone(actionable_signal(
            listing, {**evidence, "reviewed_at": "2026-10-27T11:30:00Z"}, now=now))
        self.assertIsNone(actionable_signal(
            {**listing, "title": "Pokemon Prismatic samling"}, evidence, now=now))
        self.assertIsNone(actionable_signal(
            listing, {**evidence, "action": "WATCH"}, now=now))
        self.assertIsNone(actionable_signal(
            listing, {**evidence, "listing_id": "11"}, now=now))


if __name__ == "__main__":
    unittest.main()
