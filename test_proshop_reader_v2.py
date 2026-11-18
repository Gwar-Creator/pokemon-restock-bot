"""Proshop Reader V2 offline regression tests; no network or Discord."""
import unittest
from unittest.mock import Mock

from proshop_reader_v2 import (
    parse_proshop_reader, raw_product_id_count, _stock, _price,
    proshop_reader_source_status, require_proshop_reader_source,
    fetch_verified_proshop_reader_catalog,
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

    def test_reader_source_identity_fails_closed_on_http_200_captcha(self):
        target = "https://www.proshop.dk/pokemon-kort"
        good = f"Title: Pokemon TCG\\nURL Source: {target}\\nMarkdown Content:\\n"
        good = good.replace("\\n", "\n")
        self.assertEqual(proshop_reader_source_status(good, target), "ok")
        self.assertTrue(require_proshop_reader_source(good, target))
        blocked = (
            f"Title: Just a moment...\nURL Source: {target}\n"
            "Warning: This page maybe requiring CAPTCHA\n"
        )
        self.assertEqual(proshop_reader_source_status(blocked, target), "blocked")
        with self.assertRaisesRegex(RuntimeError, "blocked"):
            require_proshop_reader_source(blocked, target)

    def test_reader_redirect_and_wrong_source_are_not_valid_catalogues(self):
        target = "https://www.proshop.dk/pokemon-kort"
        redirected = (
            f"URL Source: {target}\nFinal URL: https://www.proshop.dk/Pokemon/Pokemon\n"
        )
        self.assertEqual(proshop_reader_source_status(redirected, target), "redirected")
        wrong = "URL Source: https://www.proshop.dk/Pokemon/Pokemon\n"
        self.assertEqual(proshop_reader_source_status(wrong, target), "wrong_source")
        self.assertEqual(proshop_reader_source_status("hello world", target), "missing_source")

    def test_valid_brand_fallback_requires_source_and_real_product_cards(self):
        target = "https://www.proshop.dk/Pokemon/Pokemon"
        body = "URL Source: " + target + "\nMarkdown Content:\n" + card(
            1, "Pokemon-TCG-Mega-Lucario-ex-League-Battle-Deck",
            3447590, "På lager", "369,00 kr.",
        )
        response = Mock(text=body)
        response.raise_for_status.return_value = None
        getter = Mock(return_value=response)
        items = fetch_verified_proshop_reader_catalog(
            target, allowed, get=getter, min_raw_links=1
        )
        self.assertEqual(set(items), {"3447590"})
        self.assertEqual(items["3447590"]["price"], 369.0)
        self.assertEqual(items["3447590"]["stock"], "PÅ LAGER")
        getter.assert_called_once()
        self.assertEqual(getter.call_args.args[0], "https://r.jina.ai/" + target)

    def test_fallback_rejects_redirects_and_captcha_despite_real_links(self):
        target = "https://www.proshop.dk/Pokemon/Pokemon"
        cards = card(1, "Pokemon-TCG-Mega-Lucario-ex-League-Battle-Deck",
                     3447590, "På lager", "369,00 kr.")
        for prefix in (
            "Title: Just a moment...\nURL Source: " + target + "\n",
            "URL Source: " + target +
            "\nFinal URL: https://www.proshop.dk/pokemon-kort\n",
        ):
            response = Mock(text=prefix + cards)
            with self.subTest(prefix=prefix), self.assertRaisesRegex(
                RuntimeError, "invalid source"
            ):
                fetch_verified_proshop_reader_catalog(
                    target, allowed, get=Mock(return_value=response),
                    min_raw_links=1,
                )

    def test_fallback_never_accepts_accessories_as_product_coverage(self):
        target = "https://www.proshop.dk/Pokemon/Pokemon"
        body = "URL Source: " + target + "\n" + card(
            1, "Pokemon-TCG-Portfolio-9-P", 3447426,
            "På lager", "90,00 kr.",
        )
        with self.assertRaisesRegex(RuntimeError, "no parsed TCG products"):
            fetch_verified_proshop_reader_catalog(
                target, allowed, get=Mock(return_value=Mock(text=body)),
                min_raw_links=1,
            )

    def test_fallback_low_raw_link_count_does_not_satisfy_health(self):
        target = "https://www.proshop.dk/Pokemon/Pokemon"
        body = "URL Source: " + target + "\n" + card(
            1, "Pokemon-TCG-Mega-Lucario-ex-League-Battle-Deck",
            3447590, "På lager", "369,00 kr.",
        )
        with self.assertRaisesRegex(RuntimeError, "insufficient raw"):
            fetch_verified_proshop_reader_catalog(
                target, allowed, get=Mock(return_value=Mock(text=body))
            )

    def test_price_and_negative_stock(self):
        self.assertEqual(_price("2.199,00 kr. (1.759,20 kr.)"), 2199.0)
        self.assertEqual(_price("99 kr"), 99.0)
        self.assertIsNone(_price("No published price"))
        self.assertEqual(_stock("Ikke på lager"), "UDSOLGT")
        self.assertEqual(_stock("Bestilt: forventet på lager 30-10"), "BESTILLINGSVARE")
        self.assertEqual(_stock("ukendt"), "UKENDT")


if __name__ == "__main__":
    unittest.main()
