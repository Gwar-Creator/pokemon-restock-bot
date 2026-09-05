import unittest
from datetime import datetime, timedelta, timezone

import family_watch as fw
import family_watch_direct as direct


class FamilyWatchDirectTests(unittest.TestCase):
    def _offer(self, *, source="etilbudsavis", store="Bilka", name="Cheasy skyr", url="https://etilbudsavis.dk/x"):
        start = datetime(2026, 9, 5, tzinfo=timezone.utc)
        return fw.Offer(
            source=source,
            group_id="cheasy_skyr",
            group_label="Cheasy skyr",
            store=store,
            name=name,
            description="",
            price=24.0,
            valid_from=start,
            valid_until=start + timedelta(days=7),
            offer_id="o1",
            publication_id="p1",
            publication_label="Uge 36",
            url=url,
            image="",
        )

    def test_coop_offer_label_normalizes_newline(self):
        name, price = direct._parse_offer_label("Friends heldragt eller 2-delt sæt\n, DKK 99.95")
        self.assertEqual(name, "Friends heldragt eller 2-delt sæt")
        self.assertEqual(price, 99.95)

    def test_direct_clothing_guard_accepts_friends_but_rejects_wool_yarn(self):
        group = {"direct_include_any": ["friends", "heldragt", "uldbody"]}
        self.assertTrue(
            direct._direct_terms_match(
                {"name": "Friends striksæt", "description": "Str. 50/56-74/80"}, group
            )
        )
        self.assertFalse(
            direct._direct_terms_match(
                {"name": "Strømpegarn", "description": "70% uld og 30% polyamid"}, group
            )
        )

    def test_official_link_replaces_etilbudsavis_link(self):
        offer = self._offer()
        self.assertEqual(direct.official_offer_url(offer), "https://www.bilka.dk/bilkaavisen/")
        message = direct.build_message(offer, "current")
        self.assertIn("[Se tilbud hos Bilka](https://www.bilka.dk/bilkaavisen/)", message)
        self.assertNotIn("etilbudsavis.dk", message)

    def test_direct_coop_deep_link_is_preserved(self):
        url = "https://kvickly.coop.dk/avis/?view_id=1074120"
        offer = self._offer(source="coop_direct", store="Kvickly", url=url)
        self.assertEqual(direct.official_offer_url(offer), url)

    def test_coop_membership_text_is_marked(self):
        description = direct._access_enriched_description(
            "Kvickly", "Kun for medlemmer. Medlemspris 20 kr."
        )
        self.assertIn(direct.runner.ACCESS_MARKER, description)
        self.assertIn("Coop-medlemskab/app", description)

    def test_source_collect_drops_third_party_coop_copy(self):
        coop_copy = self._offer(store="365discount", url="https://etilbudsavis.dk/365/x")
        bilka = self._offer(store="Bilka", url="https://etilbudsavis.dk/Bilka/x")
        direct_coop = self._offer(
            source="coop_direct",
            store="365discount",
            url="https://365discount.coop.dk/365avis/?view_id=o1",
        )
        original_base = direct.BASE_SOURCE_COLLECT
        original_coop = direct.collect_coop_offers
        try:
            direct.BASE_SOURCE_COLLECT = lambda config, session, now=None: ([coop_copy, bilka], [])
            direct.collect_coop_offers = lambda config, session, now=None: ([direct_coop], [])
            offers, errors = direct.source_collect({}, None)
        finally:
            direct.BASE_SOURCE_COLLECT = original_base
            direct.collect_coop_offers = original_coop
        self.assertEqual(errors, [])
        self.assertEqual({(o.source, o.store) for o in offers}, {("etilbudsavis", "Bilka"), ("coop_direct", "365discount")})


if __name__ == "__main__":
    unittest.main()
