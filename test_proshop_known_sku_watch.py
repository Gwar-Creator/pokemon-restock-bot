"""Offline regression tests for known Proshop SKU coverage; no Discord/network."""
import unittest

from proshop_known_sku_watch import (
    KNOWN_PRODUCTS, CHECK_INTERVAL_SECONDS,
    is_proshop_tcg_title, parse_verified_detail, extend_with_known_details,
)


def make_page(sku, own, url=None, related=""):
    url = url or KNOWN_PRODUCTS[sku]
    slug = url.split("/")[-2].replace("-", " ")
    return (
        f"Title: {slug} | Billig\n"
        f"URL Source: {url}\n"
        "Markdown Content:\n"
        f"Varenummer: **{sku}**\n"
        f"{own}\n"
        f"I tilfælde af trykfejl vedrørende pris eller udsolgte varer...\n"
        + related
    )


class FakeResponse:
    status_code = 200
    def __init__(self, text):
        self.text = text
    def raise_for_status(self):
        return None


class ProshopKnownSkuTests(unittest.TestCase):
    def test_two_pack_booster_allowed_but_accessories_not(self):
        old = lambda _: False
        self.assertTrue(is_proshop_tcg_title("Pokemon TCG 2-pack Booster", old))
        self.assertTrue(is_proshop_tcg_title("Pokemon TCG 2 pack Boosters", old))
        self.assertFalse(is_proshop_tcg_title("Pokemon TCG 2-pack Booster Portfolio", old))
        self.assertFalse(is_proshop_tcg_title("Pokemon TCG 2-pack Booster sleeves", old))
        self.assertFalse(is_proshop_tcg_title("Pokemon TCG 2-pack Booster Binder", old))
        self.assertFalse(is_proshop_tcg_title("Pokemon Battle Figure 2-pack", old))
        self.assertTrue(is_proshop_tcg_title("Pokemon TCG Booster Box", lambda _: True))

    def test_verified_product_on_stock_and_real_price(self):
        page = make_page("3478496", "På lager\n529,00 kr.(423,20 kr.)")
        row = parse_verified_detail(page, "3478496", KNOWN_PRODUCTS["3478496"])
        self.assertEqual(row["stock"], "PÅ LAGER")
        self.assertEqual(row["price"], 529.0)
        self.assertEqual(row["fetch_via"], "jina_verified_detail")

    def test_no_false_stock_from_recommendations_or_boilerplate(self):
        related = (
            '* [![Image 2: Another item](https://www.proshop.dk/Images/x)]'
            '(https://www.proshop.dk/Pokemon/Pokemon-TCG-Mega-Zygarde/3447589)\n'
            'På lager\n499,00 kr.\n'
        )
        page = make_page(
            "3478496", "Beskrivelse af samlerboks uden lagerstatus\n",
            related=related,
        )
        self.assertIsNone(
            parse_verified_detail(page, "3478496", KNOWN_PRODUCTS["3478496"])
        )

    def test_no_false_status_from_legal_sold_out_words(self):
        text = make_page("3417744", "Produktbeskrivelse uden lagerstatus\n")
        self.assertIsNone(
            parse_verified_detail(text, "3417744", KNOWN_PRODUCTS["3417744"])
        )

    def test_wrong_sku_and_generic_brand_redirect_rejected(self):
        url = KNOWN_PRODUCTS["3478496"]
        self.assertIsNone(
            parse_verified_detail(make_page("3417744", "På lager\n529,00 kr."),
                                  "3478496", url)
        )
        self.assertIsNone(parse_verified_detail(
            f"Title: Pokemon Pokemon\nURL Source: {url}\n"
            "Markdown Content:\nPå lager\n529,00 kr.",
            "3478496", url
        ))

    def test_price_preservation_and_no_unverified_overwrite(self):
        calls = []
        def fetch(url, **kwargs):
            calls.append(url)
            sku = url.split("/")[-1]
            if sku == "3417744":
                return FakeResponse(make_page(sku, "Ingen tydelig status"))
            return FakeResponse(make_page(sku, "På lager\n199,00 kr."))
        state = {}
        current = {"3421827": {"name": "World Championships", "stock": "PÅ LAGER"}}
        old = {"3417744": {"price": 1129.0, "stock": "BESTILLINGSVARE"}}
        result = extend_with_known_details(current, old, state, get=fetch, now=1000)
        self.assertIn("3421827", result)
        self.assertNotIn("3417744", result)
        self.assertEqual(len(calls), 2)
        self.assertEqual(state["proshop_detail_checks"]["3417744"], 1000)
        self.assertEqual(result["3447592"]["stock"], "PÅ LAGER")
        # Repeated invocation too early cannot re-request identical SKUs.
        extend_with_known_details(current, old, state, get=fetch, now=1001)
        self.assertEqual(len(calls), 4)  # Two other SKUs, not the original two.
        self.assertNotEqual(calls[0], calls[2])
        self.assertEqual(CHECK_INTERVAL_SECONDS, 900)

    def test_unknown_status_does_not_override_old(self):
        page = make_page("3478498", "Bestillingsvare, vi tager ikke imod bestillinger")
        self.assertIsNone(parse_verified_detail(
            page, "3478498", KNOWN_PRODUCTS["3478498"]
        ))


if __name__ == "__main__":
    unittest.main()
