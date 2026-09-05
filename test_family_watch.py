import unittest
from datetime import datetime, timezone

import family_watch


class FamilyWatchTests(unittest.TestCase):
    def test_normalize_danish_letters(self):
        self.assertEqual(family_watch.normalize_text("Vådservietter & grød"), "vadservietter & grod")

    def test_store_aliases(self):
        self.assertEqual(family_watch.canonical_store("REMA 1000"), "rema1000")
        self.assertEqual(family_watch.canonical_store("Løvbjerg"), "lovbjerg")
        self.assertEqual(family_watch.canonical_store("365 Discount"), "365discount")
        self.assertEqual(family_watch.canonical_store("Dagli'Brugsen"), "daglibrugsen")

    def test_sensilac_match(self):
        group = {
            "include_all": ["sensilac"],
            "include_any": ["sensilac 2", "expertpro sensilac 2"],
            "exclude_any": ["sensilac 1"],
        }
        self.assertTrue(family_watch.matches_group({"name": "NAN ExpertPro Sensilac 2 800 g"}, group))
        self.assertFalse(family_watch.matches_group({"name": "NAN Sensilac 1 800 g"}, group))

    def test_semper_klemmepose_match(self):
        group = {
            "include_all": ["semper"],
            "include_any": ["grod", "klemmepose", "grodpouch"],
            "exclude_any": ["pulver"],
        }
        self.assertTrue(family_watch.matches_group({"name": "Semper klemmepose", "description": "120 g"}, group))
        self.assertTrue(family_watch.matches_group({"name": "SEMPER Grødpouch 120 g"}, group))
        self.assertFalse(family_watch.matches_group({"name": "Semper grødpulver"}, group))

    def test_smoothie_requires_baby_signal(self):
        group = {
            "include_all": [],
            "include_any": ["semper smoothie", "baby smoothie", "frugtmos"],
            "exclude_any": ["blender", "protein"],
        }
        self.assertTrue(family_watch.matches_group({"name": "SEMPER Smoothie-mix"}, group))
        self.assertFalse(family_watch.matches_group({"name": "Valsølille Smoothie med æble"}, group))
        self.assertFalse(family_watch.matches_group({"name": "Semper smoothie blender"}, group))

    def test_timestamp_converts_to_copenhagen_offer_date(self):
        parsed = family_watch.parse_timestamp("2026-09-09T22:00:00+0000")
        self.assertIsNotNone(parsed)
        self.assertEqual(family_watch.format_date(parsed), "10/9")

    def test_etilbudsavis_jsonld_and_offer_parse(self):
        html = '''
        <html><script type="application/ld+json">
        {
          "@type": "SearchResultsPage",
          "mainEntity": {
            "@type": "ItemList",
            "itemListElement": [
              {"@type":"ListItem","item":{
                "@type":"Offer",
                "name":"SEMPER Smoothie-mix",
                "description":"90 g. Pr. kg 55,56",
                "price":5,
                "priceCurrency":"DKK",
                "validFrom":"2026-09-09T22:00:00+0000",
                "validThrough":"2026-09-12T21:59:59+0000",
                "seller":{"@type":"Organization","name":"Lidl"},
                "url":"https://etilbudsavis.dk/Lidl?publication=pub123&offer=offer456"
              }}
            ]
          }
        }
        </script></html>
        '''
        raw = family_watch.extract_etilbudsavis_offer_dicts(html)
        self.assertEqual(len(raw), 1)
        group = {"id": "baby_smoothies", "label": "Baby-smoothies / frugtmos"}
        offer = family_watch.parse_etilbudsavis_offer(raw[0], group)
        self.assertIsNotNone(offer)
        self.assertEqual(offer.store, "Lidl")
        self.assertEqual(offer.price, 5.0)
        self.assertEqual(offer.publication_id, "pub123")
        self.assertEqual(offer.offer_id, "offer456")
        self.assertEqual(family_watch.format_period(offer), "10/9–12/9")

    def test_offer_phase_and_two_alert_lifecycle(self):
        offer = family_watch.Offer(
            source="etilbudsavis",
            group_id="baby_smoothies",
            group_label="Baby-smoothies",
            store="Lidl",
            name="SEMPER Smoothie-mix",
            description="",
            price=5.0,
            valid_from=datetime(2026, 9, 10, 0, 0, tzinfo=timezone.utc),
            valid_until=datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc),
            offer_id="offer1",
            publication_id="pub1",
            publication_label="Lidl uge 37",
            url="",
        )
        before = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
        during = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
        after = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(family_watch.offer_phase(offer, before), "upcoming")
        self.assertEqual(family_watch.phase_alert_needed(offer, {}, before), "upcoming")
        self.assertIsNone(
            family_watch.phase_alert_needed(offer, {"upcoming_sent_at": "x"}, before)
        )
        self.assertEqual(family_watch.offer_phase(offer, during), "current")
        self.assertEqual(
            family_watch.phase_alert_needed(offer, {"upcoming_sent_at": "x"}, during),
            "current",
        )
        self.assertIsNone(
            family_watch.phase_alert_needed(
                offer,
                {"upcoming_sent_at": "x", "current_sent_at": "y"},
                during,
            )
        )
        self.assertEqual(family_watch.offer_phase(offer, after), "expired")

    def test_offer_identity_stays_same_across_price_change(self):
        base = dict(
            source="etilbudsavis",
            group_id="vadservietter",
            group_label="Vådservietter",
            store="Netto",
            name="Baby wipes",
            description="",
            valid_from=datetime(2026, 9, 5, tzinfo=timezone.utc),
            valid_until=datetime(2026, 9, 10, tzinfo=timezone.utc),
            offer_id="same-offer",
            publication_id="same-publication",
            publication_label="",
            url="",
        )
        a = family_watch.Offer(price=10.0, **base)
        b = family_watch.Offer(price=12.0, **base)
        self.assertEqual(a.key, b.key)

    def test_lovbjerg_incito_offer_parser(self):
        node = {
            "role": "offer",
            "id": "160161000",
            "accessibility_label": "Semper klemmepose, DKK 8.99",
            "child_views": [
                {"view_name": "TextView", "text": "Semper klemmepose"},
                {"view_name": "TextView", "text": "Flere varianter"},
                {"view_name": "TextView", "text": "120 g | Pr kg 74,92"},
            ],
        }
        publication = {
            "id": "QDW7NY6N",
            "label": "Vejen Uge 36",
            "run_from": "2026-09-03T22:00:00+0000",
            "run_till": "2026-09-10T21:59:59+0000",
        }
        group = {"id": "semper_grodposer", "label": "Semper grød-/klemmeposer"}
        offer = family_watch.parse_lovbjerg_offer_node(node, publication, group)
        self.assertIsNotNone(offer)
        self.assertEqual(offer.name, "Semper klemmepose")
        self.assertEqual(offer.price, 8.99)
        self.assertEqual(offer.store, "Løvbjerg")
        self.assertEqual(family_watch.format_period(offer), "4/9–10/9")
        self.assertIn("120 g", offer.description)


if __name__ == "__main__":
    unittest.main()
