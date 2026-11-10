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

    def test_booster_bundle_spacing_variants_are_relevant(self):
        shared = {
            # The common alert gate is deliberately kept strict here to
            # exercise the same canonical name used by its production filter.
            "restock_alert_allowed": lambda p, g: " booster bundle " in (
                " " + p["name"].lower() + " "
            ),
        }
        for spelling in (
            "Booster Bundle",
            "Boosterbundle",
            "Booster-Bundle",
            "booster_bundle",
            "BOOSTERBUNDLE",
        ):
            name = "Pokémon TCG Mega Evolution Delta Reign " + spelling
            with self.subTest(spelling=spelling):
                self.assertTrue(radar.early_product_allowed(shared, {"name": name}))
                self.assertEqual(radar.priority_for(name), "HIGH")
        self.assertFalse(radar.early_product_allowed(
            shared, {"name": "Pokémon TCG Delta Reign Booster Pack"}
        ))

    def test_alias_migration_is_quiet_once_without_resetting_state(self):
        alias = {"name": "Pokémon Delta Reign Boosterbundle"}
        self.assertTrue(radar.quiet_alias_migration({"version": 3}, alias))
        self.assertFalse(radar.quiet_alias_migration(
            {"version": 3, "filter_revision": radar.PRODUCT_FILTER_REVISION},
            alias,
        ))
        self.assertFalse(radar.quiet_alias_migration(
            {"version": 3}, {"name": "Pokémon Delta Reign Elite Trainer Box"}
        ))

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

    def test_normal_hidden_product_metadata_movement_is_silent(self):
        old = {**self._product(), "priority": "NORMAL"}
        updated = {**old, "sites": {**old["sites"],
            "bilka": _site(self.bilka_url, release_date="2026-11-20")}}
        self.assertEqual(radar.actionable_early_movement(old, updated), [])

    def test_high_hidden_image_campaign_and_price_churn_is_silent(self):
        old = {**self._product(), "priority": "HIGH"}
        updated = {**old, "sites": {**old["sites"],
            "bilka": _site(
                self.bilka_url, price=449, campaign="Demo Campaign",
                description_hash="changed", image_primary="https://example.org/pic",
            )}}
        self.assertTrue(radar.site_movement_changes(old, updated))
        self.assertEqual(radar.actionable_early_movement(old, updated), [])

    def test_high_hidden_launch_date_change_is_still_alertable(self):
        old = {**self._product(), "priority": "HIGH"}
        updated = {**old, "sites": {**old["sites"],
            "foetex": _site(self.foetex_url, release_date="2026-11-20")}}
        messages = radar.actionable_early_movement(old, updated)
        self.assertEqual(len(messages), 1)
        self.assertIn("FOETEX release", messages[0])

    def test_high_visible_product_is_not_an_early_movement(self):
        old = {**self._product(), "priority": "HIGH"}
        updated = {**old, "sites": {**old["sites"],
            "foetex": _site(
                self.foetex_url, is_exposed=True, release_date="2026-11-20",
            )}}
        self.assertEqual(radar.actionable_early_movement(old, updated), [])

    def test_watch_hidden_preorder_and_stock_transitions_remain(self):
        old = {**self._product(), "priority": "WATCH"}
        preorder = {**old, "sites": {**old["sites"],
            "foetex": _site(self.foetex_url, expected_available_from="2026-11-20")}}
        self.assertTrue(radar.actionable_early_movement(old, preorder))
        stocked = {**old, "sites": {**old["sites"],
            "foetex": _site(self.foetex_url, store_count=2)}}
        self.assertTrue(radar.became_hidden_stocked(old, stocked))
        self.assertTrue(radar.became_live(old, stocked))

    def test_foetex_epoch_only_movement_selects_foetex_link(self):
        old = self._product()
        current = self._product(
            foetex=_site(self.foetex_url, epoch_updated_at=101),
        )
        self.assertEqual(radar.preferred_site_for_change(old, current), "foetex")


if __name__ == "__main__":
    unittest.main()
