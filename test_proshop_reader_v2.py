"""Proshop Reader V2 offline regression tests; no network or Discord."""
import unittest

from proshop_reader_v2 import (
    parse_proshop_reader, raw_product_id_count, _stock, _price,
)


def card(n, slug, ident, status, price, description="A product"):
    url = "https://www.proshop.dk/Pokemon/" + slug + "/" + str(ident)
    return (
        "*   [![Image " + str(n) + ": Pokemon - " + slug + "]"
        "(https://www.proshop.dk/Images/174x116/" + str(ident) + "_a.jpg)]("
        + url + ' "Pokemon ' + slug + ' - SKU")\n'
        + "## [Pokemon " + slug + " " + description + "](" + url + ")\n"
        + status + "\n" + price + "\n" + str(ident) + "\n"
    )


def allowed(name):
    text = name.lower()
    return any(x in text for x in (
        "premium collection", "booster", "battle deck", "world championships",
        "illustration collection",
    )) and "portfolio" not in text


class ProshopReaderV2Tests(unittest.TestCase):
    def test_extracts_long_description_and_correct_price_stock(self):
        text = "Title: Pokemon TCG\nMarkdown Content:\n" + card(
            1, "Pokemon-TCG-Mega-Zygarde-ex-Premium-Collection", 3447589,
            "På lager – Levering i morgen (bestil inden kl. 22)",
            "529,00 kr.(423,20 kr.)", description="A" * 3300,
        ) + card(
            2, "Pokemon-TCG-Portfolio-9-P-Mega-Charizard-X", 3447426,
            "På lager", "90,00 kr."
        )
        rows = parse_proshop_reader(text, allowed)
        self.assertEqual(list(rows), ["3447589"])
        self.assertEqual(rows["3447589"]["price"], 529.0)
        self.assertEqual(rows["3447589"]["stock"], "PÅ LAGER")
        self.assertEqual(rows["3447589"]["fetch_via"], "jina_reader")
        self.assertEqual(raw_product_id_count(text), 2)

    def test_statuses_and_no_cross_product_bleed(self):
        text = "\n".join([
            card(1, "Pokemon-TCG-Chaos-Rising-Booster-Box", 3447592,
                 "Bestillingsvare, leveringstiden kan ikke oplyses", ""),
            card(2, "Pokemon-TCG-First-Partner-Illustration-Collection", 3478498,
                 "Fjernlager, 3-4 dages levering", "199,00 kr."),
            card(3, "Pokemon-TCG-World-Championships-Deck", 3421827,
                 "Ikke på lager", "329,00 kr."),
        ])
        rows = parse_proshop_reader(text, allowed)
        self.assertEqual(set(rows), {"3447592", "3478498", "3421827"})
        self.assertIsNone(rows["3447592"]["price"])
        self.assertEqual(rows["3447592"]["stock"], "BESTILLINGSVARE")
        self.assertEqual(rows["3478498"]["stock"], "FJERNLAGER")
        self.assertEqual(rows["3421827"]["stock"], "UDSOLGT")

    def test_quoted_image_link_without_heading_is_still_parsed(self):
        text = (
            '*   [![Image 1: Mega Greninja](https://www.proshop.dk/Images/'
            '174x116/3478496_a.jpg)](https://www.proshop.dk/Pokemon/'
            'Pokemon-TCG-Mega-Greninja-ex-Premium-Collection/3478496 '
            '"Mega Greninja")\nPå lager\n499,00 kr.\n'
        )
        rows = parse_proshop_reader(text, allowed)
        self.assertEqual(rows["3478496"]["price"], 499.0)
        self.assertEqual(rows["3478496"]["stock"], "PÅ LAGER")

    def test_captcha_and_unknown_are_not_success(self):
        self.assertEqual(parse_proshop_reader("Just a moment... CAPTCHA", allowed), {})
        self.assertEqual(parse_proshop_reader("", allowed), {})
        self.assertEqual(raw_product_id_count("Just a moment"), 0)

    def test_price_and_negative_stock(self):
        self.assertEqual(_price("2.199,00 kr. (1.759,20 kr.)"), 2199.0)
        self.assertEqual(_price("99 kr"), 99.0)
        self.assertIsNone(_price("No published price"))
        self.assertEqual(_stock("Ikke på lager"), "UDSOLGT")
        self.assertEqual(_stock("Bestilt: forventet på lager 30-10"), "BESTILLINGSVARE")
        self.assertEqual(_stock("ukendt"), "UKENDT")


if __name__ == "__main__":
    unittest.main()
