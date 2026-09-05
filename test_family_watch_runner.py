import unittest
from datetime import datetime, timezone

import family_watch
import family_watch_runner as runner


class FamilyWatchRunnerTests(unittest.TestCase):
    def test_extracts_embedded_app_price_product(self):
        html = '''<script>{"data":[{"publicId":"offer1","name":"Baby wipes","description":"Gælder kun med Netto+ appen","price":25,"membershipPrice":null,"appPrice":20,"validFrom":"2026-09-04T22:00:00+0000","validUntil":"2026-09-11T21:59:59+0000","business":{"name":"Netto"},"publicationPublicId":"pub1"}]}</script>'''
        products = runner.extract_embedded_product_dicts(html)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["appPrice"], 20)

    def test_enriches_jsonld_offer_with_netto_plus_price(self):
        html = '''
        <script type="application/ld+json">
        {"@type":"Offer","name":"Baby wipes","description":"Gælder kun med Netto+ appen","price":25,"validFrom":"2026-09-04T22:00:00+0000","validThrough":"2026-09-11T21:59:59+0000","seller":{"name":"Netto"},"url":"https://etilbudsavis.dk/Netto?publication=pub1&offer=offer1"}
        </script>
        <script>{"data":[{"publicId":"offer1","name":"Baby wipes","description":"Gælder kun med Netto+ appen","price":25,"membershipPrice":null,"appPrice":20,"validFrom":"2026-09-04T22:00:00+0000","validUntil":"2026-09-11T21:59:59+0000","business":{"name":"Netto"},"publicationPublicId":"pub1"}]}</script>
        '''
        raw = runner.extract_etilbudsavis_offer_dicts(html)
        self.assertEqual(raw[0]["price"], 20)
        self.assertIn("Netto+ app", raw[0]["description"])
        self.assertIn("regular_price", raw[0]["description"])

    def test_lidl_plus_note(self):
        note = runner.infer_access_note("Lidl", "Med Lidl Plus", 10.0, None)
        self.assertEqual(note, "Lidl Plus app/medlemskab")

    def test_coop_membership_note(self):
        note = runner.infer_access_note("365discount", "MEDLEMSPRIS", 12.0, None)
        self.assertEqual(note, "Coop-medlemskab/app")

    def test_include_any_sets_catches_brand_after_smoothie(self):
        group = {
            "include_all": [],
            "include_any": [],
            "exclude_any": ["blender", "protein"],
            "include_any_sets": [
                ["smoothie", "frugtmos"],
                ["semper", "hipp", "ella", "organix", "baby", "grød"],
            ],
        }
        self.assertTrue(runner.matches_group({"name": "Smoothie yoghurt m. abrikos fra Semper"}, group))
        self.assertFalse(runner.matches_group({"name": "Valsølille Smoothie med æble"}, group))

    def test_message_shows_access_requirement_and_regular_price(self):
        offer = family_watch.Offer(
            source="etilbudsavis",
            group_id="vadservietter",
            group_label="Vådservietter",
            store="Netto",
            name="Baby wipes",
            description='Gælder kun med Netto+ appen\n[FW_ACCESS]{"access":"Netto+ app","regular_price":25}',
            price=20.0,
            valid_from=datetime(2026, 9, 5, tzinfo=timezone.utc),
            valid_until=datetime(2026, 9, 11, 21, 59, 59, tzinfo=timezone.utc),
            offer_id="o1",
            publication_id="p1",
            publication_label="",
            url="",
        )
        message = runner.build_message(offer, "current")
        self.assertIn("20 kr.", message)
        self.assertIn("normalpris 25 kr.", message)
        self.assertIn("Kræver: **Netto+ app**", message)


if __name__ == "__main__":
    unittest.main()
