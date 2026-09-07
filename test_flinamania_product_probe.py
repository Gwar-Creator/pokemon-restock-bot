import unittest

import flinamania_product_probe as probe


class FlinamaniaProductProbeTests(unittest.TestCase):
    def test_enabled_add_to_cart_beats_stale_sold_out_badge(self):
        document = """
        <div class="badge">Tilbud Udsolgt</div>
        <form action="/cart/add" method="post">
          <input type="hidden" name="id" value="123">
          <button name="add" class="product-form__submit">Læg i kurv</button>
        </form>
        """
        self.assertTrue(probe.parse_product_page_stock(document))

    def test_disabled_sold_out_button_is_false(self):
        document = """
        <form action="/cart/add" method="post">
          <input type="hidden" name="id" value="123">
          <button name="add" class="product-form__submit" disabled>Udsolgt</button>
        </form>
        """
        self.assertFalse(probe.parse_product_page_stock(document))

    def test_hidden_template_add_button_does_not_create_false_positive(self):
        document = """
        <div hidden>
          <form action="/cart/add"><button name="add">Læg i kurv</button></form>
        </div>
        <form action="/cart/add">
          <button name="add" disabled>Udsolgt</button>
        </form>
        """
        self.assertFalse(probe.parse_product_page_stock(document))

    def test_overlay_changes_only_resolved_product_pages(self):
        products = {
            "1": {"url": "https://example.test/live", "in_stock": False},
            "2": {"url": "https://example.test/sold", "in_stock": True},
            "3": {"url": "https://example.test/unknown", "in_stock": False},
        }

        def fake_fetch(url):
            if url.endswith("/live"):
                return True
            if url.endswith("/sold"):
                return False
            return None

        result = probe.apply_product_page_stock(products, fetch_one=fake_fetch, max_workers=2)
        self.assertTrue(result["1"]["in_stock"])
        self.assertFalse(result["2"]["in_stock"])
        self.assertFalse(result["3"]["in_stock"])


if __name__ == "__main__":
    unittest.main()
