import unittest

import salling_early_radar as radar


def _site(url, **overrides):
    site = {
        "url": url,
        "is_exposed": False,
        "online_count": 0,
        "store_count": 0,
        "price": 499,
        "epoch_updated_at": 100,
    }
    site.update(overrides)
    return site


class SallingEarlyRadarLinkTests(unittest.TestCase):
    def setUp(self):
        self.bilka_url = "https://www.bilka.dk/produkter/test/200000001/"
        self.foetex_url = "https://www.foetex.dk/produkter/test/200000001/"

    def _product(self, bilka=None, foetex=None):
        return {
            "id": "200000001",
            "sites": {
                "bilka": bilka or _site(self.bilka_url),
                "foetex": foetex or _site(self.foetex_url),
            },
        }

    def test_best_url_respects_preferred_foetex_site(self):
        product = self._product()
        self.assertEqual(
            radar.best_url(product, preferred_site="foetex"),
            self.foetex_url,
        )

    def test_best_url_keeps_bilka_as_default_fallback(self):
        self.assertEqual(radar.best_url(self._product()), self.bilka_url)

    def test_foetex_stock_transition_selects_foetex_link(self):
        old = self._product()
        current = self._product(
            foetex=_site(self.foetex_url, online_count=3),
        )
        self.assertEqual(radar.preferred_site_for_change(old, current), "foetex")
        self.assertEqual(
            radar.best_url(
                current,
                preferred_site=radar.preferred_site_for_change(old, current),
            ),
            self.foetex_url,
        )

    def test_foetex_metadata_movement_selects_foetex_link(self):
        old = self._product()
        current = self._product(
            foetex=_site(self.foetex_url, price=449),
        )
        self.assertEqual(radar.preferred_site_for_change(old, current), "foetex")

    def test_foetex_epoch_only_movement_selects_foetex_link(self):
        old = self._product()
        current = self._product(
            foetex=_site(self.foetex_url, epoch_updated_at=101),
        )
        self.assertEqual(radar.preferred_site_for_change(old, current), "foetex")


if __name__ == "__main__":
    unittest.main()
