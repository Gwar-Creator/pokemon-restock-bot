import unittest

from bs4 import BeautifulSoup

from faraos_parser_v2 import faraos_name_v2


def clean_text(value):
    return " ".join(str(value or "").split())


def card_from(html):
    return BeautifulSoup(html, "html.parser").select_one(".card")


class FaraosParserV2Tests(unittest.TestCase):
    def test_recovers_split_set_and_product_type(self):
        card = card_from(
            '<div class="card"><h3>Journey Together</h3><div>Booster</div>'
            '<div>DKK 65 00</div><div>På lager</div></div>'
        )

        self.assertEqual(
            faraos_name_v2(card, lambda _: "Journey Together", clean_text),
            "Journey Together Booster",
        )

    def test_keeps_existing_good_name_stable(self):
        card = card_from(
            '<div class="card"><h3>Chaos Rising Booster Box - Indeholder 36 Boosters</h3>'
            '<div>Pokemon: Release d.22/5</div><div>DKK 1999 00</div>'
            '<div>Varen kan kun købes i en butik</div></div>'
        )
        old_name = "Chaos Rising Booster Box - Indeholder 36 Boosters"

        self.assertEqual(
            faraos_name_v2(card, lambda _: old_name, clean_text),
            old_name,
        )

    def test_keeps_existing_generic_lorcana_booster_name_stable(self):
        card = card_from(
            '<div class="card"><h3>Booster Display (24)</h3><div>Into the Inklands</div>'
            '<div>DKK 840 00</div><div>Få på lager!</div></div>'
        )

        self.assertEqual(
            faraos_name_v2(card, lambda _: "Booster Display (24)", clean_text),
            "Booster Display (24)",
        )

    def test_strips_release_metadata_from_recovered_name(self):
        card = card_from(
            '<div class="card"><h3>Pitch Black</h3><div>Booster Bundle</div>'
            '<div>Pokemon: Release d.17/7</div><div>DKK 359 00</div>'
            '<div>Varen kan kun købes i en butik</div></div>'
        )

        self.assertEqual(
            faraos_name_v2(card, lambda _: "Pitch Black", clean_text),
            "Pitch Black Booster Bundle",
        )


if __name__ == "__main__":
    unittest.main()
