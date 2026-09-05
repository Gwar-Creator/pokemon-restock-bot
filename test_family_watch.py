import unittest

import family_watch


class FamilyWatchTests(unittest.TestCase):
    def test_normalize_danish_letters(self):
        self.assertEqual(family_watch.normalize_text("Vådservietter & grød"), "vadservietter & grod")

    def test_sensilac_match(self):
        group = {
            "include_all": ["sensilac"],
            "include_any": ["2", "expertpro"],
            "exclude_any": [],
        }
        self.assertTrue(family_watch.matches_group({"name": "NAN ExpertPro Sensilac 2 800 g"}, group))
        self.assertFalse(family_watch.matches_group({"name": "NAN Sensilac 1 800 g"}, group))

    def test_semper_grod_match(self):
        group = {
            "include_all": ["semper"],
            "include_any": ["grød", "pose", "pouch"],
            "exclude_any": [],
        }
        self.assertTrue(family_watch.matches_group({"name": "Semper spiseklar grød pære 120 g"}, group))
        self.assertFalse(family_watch.matches_group({"name": "Semper modermælkserstatning"}, group))

    def test_smoothie_exclusion(self):
        group = {
            "include_all": [],
            "include_any": ["smoothie", "frugtmos"],
            "exclude_any": ["blender", "juicepresser"],
        }
        self.assertTrue(family_watch.matches_group({"name": "ØGO økologisk grød smoothie"}, group))
        self.assertFalse(family_watch.matches_group({"name": "Smoothie blender"}, group))

    def test_offer_key_changes_with_price(self):
        base = dict(
            group_id="vadservietter",
            group_label="Vådservietter",
            store="netto",
            name="Baby wipes",
            brand="",
            unit_price=None,
            unit="",
            unit_size=None,
            product_id="123",
            ean="",
            url="",
        )
        a = family_watch.Offer(price=10.0, **base)
        b = family_watch.Offer(price=12.0, **base)
        self.assertNotEqual(a.key, b.key)


if __name__ == "__main__":
    unittest.main()
