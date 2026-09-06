import os
import unittest

os.environ.setdefault("DISCORD_WEBHOOK_URL", "https://example.invalid/webhook")

import restock_v2_runner as runner


class RestockV2RunnerTests(unittest.TestCase):
    def test_tier_a_restock_always_passes_channel_tier_gate(self):
        message = (
            "🔥 **[POKÉMON] COOLSHOP RESTOCK**\n"
            "**Journey Together Elite Trainer Box**\n"
            "✅ På lager online"
        )
        self.assertTrue(runner.restock_v2_channel_alert_allowed(message))

    def test_tier_b_normal_etb_is_muted(self):
        message = (
            "🔥 **[POKÉMON] MATRAWS RESTOCK**\n"
            "**Journey Together Elite Trainer Box**\n"
            "📦 Udsolgt → På lager"
        )
        self.assertFalse(runner.restock_v2_channel_alert_allowed(message))

    def test_tier_b_booster_box_passes(self):
        message = (
            "🔥 **[POKÉMON] MATRAWS RESTOCK**\n"
            "**Journey Together Booster Box**\n"
            "📦 Udsolgt → På lager"
        )
        self.assertTrue(runner.restock_v2_channel_alert_allowed(message))

    def test_tier_b_watch_etb_passes(self):
        message = (
            "🔥 **[POKÉMON] POKEHULEN RESTOCK**\n"
            "**Pokemon 151 Elite Trainer Box**\n"
            "📦 Udsolgt → På lager"
        )
        self.assertTrue(runner.restock_v2_channel_alert_allowed(message))

    def test_tier_b_abundant_etb_is_muted(self):
        message = (
            "🔥 **[POKÉMON] CARDX RESTOCK**\n"
            "**Pitch Black Elite Trainer Box**\n"
            "📦 Udsolgt → På lager"
        )
        self.assertFalse(runner.restock_v2_channel_alert_allowed(message))

    def test_tier_b_preorder_passes(self):
        message = (
            "🚨 **[POKÉMON] NY FORUDBESTILLING HOS HALMES HULE**\n"
            "**Future Illustration Collection**\n"
            "📅 Forudbestilling"
        )
        self.assertTrue(runner.restock_v2_channel_alert_allowed(message))

    def test_faraos_v3_installs_granular_category_feeds(self):
        namespace = {
            "_faraos_name": lambda _card: "Journey Together",
            "woocommerce_clean_text": lambda value: str(value or ""),
            "FARAOS_FEEDS": (("POKÉMON", "https://example.invalid/old"),),
        }

        runner._install_faraos_parser(namespace)

        self.assertEqual(namespace["FARAOS_FEEDS"], runner.FARAOS_V3_FEEDS)
        self.assertGreaterEqual(len(namespace["FARAOS_FEEDS"]), 10)
        urls = {url for _game, url in namespace["FARAOS_FEEDS"]}
        self.assertIn(
            "https://www.faraos.dk/games/kortspil/pokemon/booster",
            urls,
        )
        self.assertIn(
            "https://www.faraos.dk/games/kortspil/lorcana/boosters",
            urls,
        )


if __name__ == "__main__":
    unittest.main()
