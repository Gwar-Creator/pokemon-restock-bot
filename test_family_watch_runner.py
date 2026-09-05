import unittest
from datetime import datetime, timedelta, timezone

import family_watch
import family_watch_runner as runner


class FamilyWatchRunnerTests(unittest.TestCase):
    def test_extracts_html_escaped_app_price_product(self):
        html = '''<app-data data-status="success">{&quot;data&quot;:[{&quot;publicId&quot;:&quot;offer1&quot;,&quot;name&quot;:&quot;Baby wipes&quot;,&quot;description&quot;:&quot;Gælder kun med Netto+ appen&quot;,&quot;price&quot;:25,&quot;membershipPrice&quot;:null,&quot;appPrice&quot;:20,&quot;validFrom&quot;:&quot;2026-09-04T22:00:00+0000&quot;,&quot;validUntil&quot;:&quot;2026-09-11T21:59:59+0000&quot;,&quot;business&quot;:{&quot;name&quot;:&quot;Netto&quot;},&quot;publicationPublicId&quot;:&quot;pub1&quot;}]}</app-data>'''
        products = runner.extract_embedded_product_dicts(html)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["appPrice"], 20)

    def test_enriches_jsonld_offer_with_netto_plus_price(self):
        html = '''
        <script type="application/ld+json">
        {"@type":"Offer","name":"Baby wipes","description":"Gælder kun med Netto+ appen","price":25,"validFrom":"2026-09-04T22:00:00+0000","validThrough":"2026-09-11T21:59:59+0000","seller":{"name":"Netto"},"url":"https://etilbudsavis.dk/Netto?publication=pub1&offer=offer1"}
        </script>
        <app-data>{&quot;data&quot;:[{&quot;publicId&quot;:&quot;offer1&quot;,&quot;name&quot;:&quot;Baby wipes&quot;,&quot;description&quot;:&quot;Gælder kun med Netto+ appen&quot;,&quot;price&quot;:25,&quot;membershipPrice&quot;:null,&quot;appPrice&quot;:20,&quot;validFrom&quot;:&quot;2026-09-04T22:00:00+0000&quot;,&quot;validUntil&quot;:&quot;2026-09-11T21:59:59+0000&quot;,&quot;business&quot;:{&quot;name&quot;:&quot;Netto&quot;},&quot;publicationPublicId&quot;:&quot;pub1&quot;}]}</app-data>
        '''
        raw = runner.extract_etilbudsavis_offer_dicts(html)
        self.assertEqual(raw[0]["price"], 20)
        self.assertIn("Netto+ app", raw[0]["description"])
        self.assertIn("regular_price", raw[0]["description"])

    def test_jsonld_description_alone_marks_netto_plus(self):
        html = '''
        <script type="application/ld+json">
        {"@type":"Offer","name":"Baby wipes","description":"Gælder kun med Netto+ appen","price":20,"validFrom":"2026-09-04T22:00:00+0000","validThrough":"2026-09-11T21:59:59+0000","seller":{"name":"Netto"},"url":"https://etilbudsavis.dk/Netto?publication=pub1&offer=offer1"}
        </script>
        '''
        raw = runner.extract_etilbudsavis_offer_dicts(html)
        self.assertIn("Netto+ app", raw[0]["description"])

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

    def test_lovbjerg_config_drops_query_context_groups(self):
        config = {
            "watch_groups": [
                {"id": "bleer"},
                {"id": "bornetoj", "skip_lovbjerg_direct": True},
            ]
        }
        filtered = runner.config_for_lovbjerg(config)
        self.assertEqual([g["id"] for g in filtered["watch_groups"]], ["bleer"])

    def test_collect_offers_filters_long_running_catalogue_entries(self):
        now = datetime(2026, 9, 5, tzinfo=timezone.utc)
        short = family_watch.Offer(
            source="etilbudsavis", group_id="bleer", group_label="Babybleer",
            store="Netto", name="Libero", description="", price=75,
            valid_from=now, valid_until=now + timedelta(days=7), offer_id="1",
            publication_id="p", publication_label="", url="",
        )
        long = family_watch.Offer(
            source="etilbudsavis", group_id="bleer", group_label="Babybleer",
            store="Lidl", name="Lupilu", description="", price=20,
            valid_from=now, valid_until=now + timedelta(days=120), offer_id="2",
            publication_id="p2", publication_label="", url="",
        )
        original = runner._ORIGINAL_COLLECT
        try:
            runner._ORIGINAL_COLLECT = lambda config, session, now=None: ([short, long], [])
            offers, _ = runner.collect_offers({"max_offer_days": 45}, None, now=now)
        finally:
            runner._ORIGINAL_COLLECT = original
        self.assertEqual([offer.name for offer in offers], ["Libero"])

    def test_diapers_are_rema_only(self):
        now = datetime(2026, 9, 5, tzinfo=timezone.utc)
        rema = family_watch.Offer(
            source="etilbudsavis", group_id="bleer", group_label="Babybleer",
            store="Rema 1000", name="Libero", description="", price=69,
            valid_from=now, valid_until=now + timedelta(days=7), offer_id="r1",
            publication_id="p1", publication_label="", url="",
        )
        bilka = family_watch.Offer(
            source="etilbudsavis", group_id="bleer", group_label="Babybleer",
            store="Bilka", name="Libero", description="", price=59,
            valid_from=now, valid_until=now + timedelta(days=7), offer_id="b1",
            publication_id="p2", publication_label="", url="",
        )
        config = {
            "max_offer_days": 45,
            "watch_groups": [{"id": "bleer", "allowed_stores": ["Rema 1000"]}],
        }
        original = runner._ORIGINAL_COLLECT
        try:
            runner._ORIGINAL_COLLECT = lambda config, session, now=None: ([rema, bilka], [])
            offers, _ = runner.collect_offers(config, None, now=now)
        finally:
            runner._ORIGINAL_COLLECT = original
        self.assertEqual([(o.store, o.name) for o in offers], [("Rema 1000", "Libero")])

    def test_clothing_is_store_scoped_and_aggregated(self):
        now = datetime(2026, 9, 5, tzinfo=timezone.utc)
        end = now + timedelta(days=7)
        offers_in = [
            family_watch.Offer(
                source="etilbudsavis", group_id="bornetoj", group_label="Børnetøj / babytøj",
                store="Bilka", name="Bukser", description="98-152 cm", price=79,
                valid_from=now, valid_until=end, offer_id="1", publication_id="p", publication_label="", url="u1",
            ),
            family_watch.Offer(
                source="etilbudsavis", group_id="bornetoj", group_label="Børnetøj / babytøj",
                store="Bilka", name="Flyverdragt", description="74-92 cm", price=399,
                valid_from=now, valid_until=end, offer_id="2", publication_id="p", publication_label="", url="u2",
            ),
            family_watch.Offer(
                source="etilbudsavis", group_id="bornetoj", group_label="Børnetøj / babytøj",
                store="føtex", name="Cardigan", description="98-152 cm", price=129,
                valid_from=now, valid_until=end, offer_id="3", publication_id="p2", publication_label="", url="u3",
            ),
        ]
        config = {
            "max_offer_days": 45,
            "watch_groups": [{
                "id": "bornetoj",
                "allowed_stores": ["Bilka", "Kvickly", "SuperBrugsen"],
                "aggregate": "store_period",
            }],
        }
        original = runner._ORIGINAL_COLLECT
        try:
            runner._ORIGINAL_COLLECT = lambda config, session, now=None: (offers_in, [])
            offers, _ = runner.collect_offers(config, None, now=now)
        finally:
            runner._ORIGINAL_COLLECT = original

        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].store, "Bilka")
        self.assertEqual(offers[0].name, "Børnetøj i tilbudsavisen")
        message = runner.build_message(offers[0], "current")
        self.assertIn("2 relevante tøjtilbud samlet", message)
        self.assertIn("79 kr.–399 kr.", message)
        self.assertIn("Bukser", message)
        self.assertIn("Flyverdragt", message)
        self.assertNotIn("Cardigan", message)

    def test_wool_is_highlighted_without_guld_false_positive(self):
        now = datetime(2026, 9, 5, tzinfo=timezone.utc)
        end = now + timedelta(days=7)
        wool = family_watch.Offer(
            source="etilbudsavis", group_id="bornetoj", group_label="Børnetøj / babytøj",
            store="Bilka", name="Body i merinould", description="Str. 74-92 cm, 100% uld", price=149,
            valid_from=now, valid_until=end, offer_id="w1", publication_id="p", publication_label="", url="u1",
        )
        gold = family_watch.Offer(
            source="etilbudsavis", group_id="bornetoj", group_label="Børnetøj / babytøj",
            store="Bilka", name="Guld cardigan", description="Str. 98-116 cm", price=99,
            valid_from=now, valid_until=end, offer_id="g1", publication_id="p", publication_label="", url="u2",
        )
        config = {
            "max_offer_days": 45,
            "watch_groups": [{
                "id": "bornetoj",
                "allowed_stores": ["Bilka", "Kvickly", "SuperBrugsen"],
                "aggregate": "store_period",
                "highlight_label": "ULD-FUND",
                "highlight_terms": ["uld", "merino", "merinould", "wool"],
            }],
        }
        original = runner._ORIGINAL_COLLECT
        try:
            runner._ORIGINAL_COLLECT = lambda config, session, now=None: ([wool, gold], [])
            offers, _ = runner.collect_offers(config, None, now=now)
        finally:
            runner._ORIGINAL_COLLECT = original

        self.assertEqual(len(offers), 1)
        self.assertTrue(offers[0].offer_id.endswith(":highlight"))
        message = runner.build_message(offers[0], "current")
        self.assertIn("ULD-FUND: 1 tilbud", message)
        self.assertIn("Body i merinould", message)
        self.assertNotIn("🧶 Guld cardigan", message)

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
