import unittest

from personal import cardmarket_official_listing_probe as probe


class CardmarketOfficialListingProbeTests(unittest.TestCase):
    def test_normalize_article_extracts_exact_offer_fields(self):
        article = {
            "idArticle": 123,
            "idProduct": 794611,
            "language": {"idLanguage": 1, "languageName": "English"},
            "price": 99.95,
            "condition": "NM",
            "isFoil": True,
            "isSigned": False,
            "isAltered": False,
            "seller": {"username": "Example", "address": {"country": "D"}},
        }
        row = probe.normalize_article(
            article,
            product_id="794611",
            expected_variant="Foil",
            checked_at="2026-09-03T16:00:00Z",
        )
        self.assertEqual(row["product_id"], "794611")
        self.assertEqual(row["language_id"], 1)
        self.assertEqual(row["seller_country"], "D")
        self.assertTrue(row["variant_match"])
        self.assertIsNone(row["ships_to_denmark"])
        self.assertIsNone(row["shipping_eur"])

    def test_normalize_article_rejects_wrong_product(self):
        row = probe.normalize_article(
            {"idProduct": 2, "price": 1.0},
            product_id="1",
            expected_variant="Normal",
            checked_at="2026-09-03T16:00:00Z",
        )
        self.assertIsNone(row)

    def test_normalize_article_marks_finish_mismatch(self):
        article = {
            "idArticle": 1,
            "idProduct": 1,
            "language": {"idLanguage": 1, "languageName": "English"},
            "price": 1.0,
            "condition": "NM",
            "isFoil": True,
            "seller": {"username": "Example", "address": {"country": "DE"}},
        }
        row = probe.normalize_article(
            article,
            product_id="1",
            expected_variant="Normal",
            checked_at="2026-09-03T16:00:00Z",
        )
        self.assertFalse(row["variant_match"])

    def test_extract_articles_accepts_cardmarket_article_key(self):
        self.assertEqual(
            probe.extract_articles({"article": [{"idArticle": 1}, {"idArticle": 2}]}),
            [{"idArticle": 1}, {"idArticle": 2}],
        )


if __name__ == "__main__":
    unittest.main()
