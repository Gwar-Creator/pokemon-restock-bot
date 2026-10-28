"""Vintage Finder guardrails: no buying, no guessed valuations, no scraping."""
import unittest
from unittest.mock import Mock

from vintage_finder_tradera import (
    SEARCH_URL, SEARCH_TERMS, assess_title, extract_search_rows,
    fetch_search, normalize_listing, select_candidates, TraderaResponseFormatError,
)


class VintageFinderTraderaTests(unittest.TestCase):
    def test_real_vintage_and_collection_terms_require_review(self):
        for title in (
            "Pokemon Aquapolis English cards",
            "Pokemon Neo Destiny kort",
            "Gamla Pokemon kort samling",
            "Pokemon Base Set Fossil Jungle samling",
            "Pokemon EX Dragon rare kort",
        ):
            with self.subTest(title=title):
                self.assertIn(assess_title(title)["priority"], ("REVIEW", "REVIEW_HIGH"))

    def test_bulk_sealed_proxy_foreign_cards_and_modern_generic_are_rejected(self):
        for title in (
            "Pokemon bulk cards samling",
            "Pokemon vintage Japanese cards",
            "Pokemon Proxy Base Set kort",
            "Pokemon booster box 2003",
            "Pokemon sealed booster pack vintage",
            "Pokemon Vmax modern singles",
            "Lorcana samling",
        ):
            with self.subTest(title=title):
                self.assertEqual(assess_title(title)["priority"], "SKIP")

    def test_title_only_can_never_claim_good_buy(self):
        value = normalize_listing({"id": 123, "title": "Pokemon Neo Destiny lot", "price": 15})
        self.assertEqual(value["purchase_decision"], "DO_NOT_BUY_WITHOUT_REVIEW")
        self.assertEqual(value["card_language"], "UNVERIFIED")
        self.assertEqual(value["shipping_to_denmark"], "UNKNOWN")
        self.assertEqual(value["fair_price"], "UNVERIFIED")
        self.assertEqual(value["condition"], "UNVERIFIED")
        self.assertEqual(value["price_sek"], 15)

    def test_title_only_does_not_guess_listing_identifier(self):
        self.assertIsNone(normalize_listing({"title": "Pokemon Neo Destiny"}))

    def test_duplicates_ranked_and_bounded(self):
        rows = [
            {"id": 17, "title": "Pokemon samling vintage"},
            {"id": 17, "title": "Pokemon samling vintage"},
            {"itemId": 20, "name": "Pokemon Skyridge kort"},
            {"id": 30, "title": "Pokemon bulk cards samling"},
        ]
        value = select_candidates(rows)
        self.assertEqual([v["id"] for v in value], ["20", "17"])
        self.assertEqual(len(select_candidates(rows, limit=1)), 1)
        self.assertEqual(select_candidates(rows, limit=0), [])

    def test_official_rest_api_is_read_only_and_credentials_header_only(self):
        response = Mock()
        response.json.return_value = {"items": [{"id": 5, "title": "Pokemon Base Set lot"}]}
        transport = Mock(return_value=response)
        rows = fetch_search("pokemon samling", "123", "secret", transport=transport)
        self.assertEqual(len(rows), 1)
        response.raise_for_status.assert_called_once()
        args, kwargs = transport.call_args
        self.assertEqual(args[0], SEARCH_URL)
        self.assertEqual(kwargs["params"]["query"], "pokemon samling")
        self.assertEqual(kwargs["params"]["pageNumber"], 0)
        self.assertEqual(kwargs["headers"]["X-App-Id"], "123")
        self.assertEqual(kwargs["headers"]["X-App-Key"], "secret")
        self.assertNotIn("secret", str(kwargs["params"]))
        self.assertEqual(kwargs["timeout"], 20)

    def test_requests_json_decode_error_is_normalized_without_response_leak(self):
        import requests
        response = Mock(status_code=200, headers={"Content-Type": "text/html; charset=UTF-8"})
        response.raise_for_status.return_value = None
        response.json.side_effect = requests.exceptions.JSONDecodeError(
            "SECRET BODY", "<html>SECRET BODY</html>", 0)
        client = Mock(return_value=response)
        with self.assertRaises(TraderaResponseFormatError) as caught:
            fetch_search("pokemon samling", "APP", "KEY", transport=client)
        self.assertEqual(caught.exception.http_status, 200)
        self.assertEqual(caught.exception.content_kind, "html")
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertNotIn("SECRET", repr(caught.exception))

    def test_unknown_api_schema_rejected_not_silently_read_as_empty(self):
        with self.assertRaises(ValueError):
            extract_search_rows({"result": {"listings": []}})

    def test_verified_v4_search_listing_shape(self):
        data = {
            "errors": [],
            "totalNumberOfItems": 50,
            "totalNumberOfPages": 1,
            "items": [{
                "id": 98765,
                "shortDescription": "Pokemon Aquapolis collection",
                "itemUrl": "https://www.tradera.com/item/123/98765",
                "maxBid": 150,
                "nextBid": 160,
                "hasBids": True,
                "sellerAlias": "public_username",
            }],
        }
        rows = extract_search_rows(data)
        candidate = normalize_listing(rows[0])
        self.assertEqual(candidate["id"], "98765")
        self.assertEqual(candidate["priority"], "REVIEW_HIGH")
        self.assertEqual(candidate["title"], "Pokemon Aquapolis collection")
        self.assertEqual(candidate["url"], "https://www.tradera.com/item/123/98765")
        self.assertIsNone(candidate["price_sek"])
        self.assertEqual(candidate["purchase_decision"], "DO_NOT_BUY_WITHOUT_REVIEW")
        self.assertNotIn("sellerAlias", candidate)
        self.assertEqual(candidate["shipping_to_denmark"], "UNKNOWN")

    def test_unknown_public_link_dropped_without_dropping_candidate(self):
        candidate = normalize_listing({
            "id": 1, "shortDescription": "Pokemon Fossil lot",
            "itemUrl": "https://example.invalid/card",
        })
        self.assertEqual(candidate["url"], "")

    def test_v4_embedded_errors_rejected(self):
        with self.assertRaises(ValueError):
            extract_search_rows({"errors": ["unexpected failure"], "items": []})

    def test_no_credentials_no_request(self):
        transport = Mock()
        with self.assertRaises(ValueError):
            fetch_search("pokemon samling", "", "", transport=transport)
        transport.assert_not_called()

    def test_search_terms_are_vintage_only(self):
        self.assertGreaterEqual(len(SEARCH_TERMS), 6)
        self.assertTrue(all("pokemon" in q for q in SEARCH_TERMS))


if __name__ == "__main__":
    unittest.main()
