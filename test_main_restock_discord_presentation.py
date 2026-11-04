"""Offline regression tests for ordinary Restock Discord embed presentation.

The production scanner has startup side effects, so parse only its four
pure formatting functions. No network, Discord or inventory writes.
"""
import ast
from pathlib import Path
import re
import unittest

SOURCE = Path(__file__).with_name("restock_bot_github.py")
FUNCTIONS = {
    "_discord_embed_color",
    "_discord_clean_line",
    "_discord_message_parts",
    "_discord_product_embed",
}


def formatter_namespace():
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    functions = [
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS
    ]
    if len(functions) != len(FUNCTIONS):
        raise AssertionError("Restock Discord formatter function missing")
    namespace = {"re": re}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace


class RestockDiscordPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.functions = formatter_namespace()

    def embed(self, message, kind="restock"):
        return self.functions["_discord_product_embed"](message, kind)

    def fields(self, embed):
        return {row["name"]: row["value"] for row in embed.get("fields", [])}

    def test_new_proshop_discovery_preserves_shop_and_no_purchase_claim(self):
        sample = (
            "🆕 **[POKÉMON] NYT PÅ PROSHOP**\n"
            "**Pokemon 151 Booster Bundle**\n"
            "📦 BESTILLINGSVARE\n"
            "💰 499,00 kr.\n"
            "🔗 https://www.proshop.dk/Pokemon/Bundle/12345"
        )
        embed = self.embed(sample)
        self.assertEqual(embed["title"], "NYT PRODUKT · PROSHOP")
        self.assertIn("NYT I KATALOG", self.fields(embed)["STATUS"])
        self.assertIn("ikke bekræftet", self.fields(embed)["STATUS"])
        self.assertNotEqual(embed["color"], 0x57F287)
        self.assertIn("499,00 kr.", self.fields(embed)["Pris"])
        self.assertEqual(embed["url"], "https://www.proshop.dk/Pokemon/Bundle/12345")

    def test_bilka_and_br_new_catalogue_show_shop(self):
        for shop in ("BR", "BILKA", "FØTEX"):
            msg = (
                f"🆕 **[POKÉMON] NYT PÅ {shop}**\n"
                "**Pokemon Booster Bundle**\n"
                "🌐 Online: 3 stk.\n"
                "🔗 https://example.org/product"
            )
            with self.subTest(shop=shop):
                embed = self.embed(msg)
                self.assertEqual(embed["title"], f"NYT PRODUKT · {shop}")
                self.assertIn("NYT I KATALOG", self.fields(embed)["STATUS"])
                self.assertNotEqual(embed["color"], 0x57F287)

    def test_coolshop_new_found_source_is_preserved(self):
        msg = (
            "🆕 **[POKÉMON] NYT FUNDET PÅ COOLSHOP**\n"
            "**Pokemon Collector Box**\n"
            "💰 399,00 kr.\n"
            "🔗 https://www.coolshop.dk/produkt/item"
        )
        self.assertEqual(self.embed(msg)["title"], "NYT PRODUKT · COOLSHOP")

    def test_preorder_is_purple_and_explicit_not_on_hand(self):
        msg = (
            "🚨 **[POKÉMON] NY FORUDBESTILLING HOS HALMES HULE**\n"
            "**Pokemon Illustration Collection**\n"
            "📅 Forudbestilling\n"
            "🔗 https://example.org/item"
        )
        embed = self.embed(msg)
        self.assertEqual(embed["title"], "FORUDBESTILLING · HALMES HULE")
        self.assertEqual(embed["color"], 0x9B59B6)
        self.assertIn("ikke dokumenteret på lager", self.fields(embed)["STATUS"])
        self.assertNotIn("KØB NU", str(embed))

    def test_regular_restock_keeps_legacy_semantics_for_now(self):
        sample = (
            "🔥 **[POKÉMON] COOLSHOP RESTOCK**\n"
            "**Pokemon 151 Booster Bundle**\n"
            "✅ På lager online\n"
            "💰 289,00 kr.\n"
            "🔗 https://www.coolshop.dk/produkt/item"
        )
        embed = self.embed(sample)
        self.assertEqual(embed["title"], "RESTOCK · COOLSHOP")
        self.assertEqual(embed["color"], 0x57F287)
        self.assertNotIn("STATUS", self.fields(embed))

    def test_price_history_summary_remains_unchanged(self):
        sample = "📉 DAGENS BEDSTE PRISER\nPokemon 151 ETB 499 kr."
        embed = self.embed(sample, kind="price")
        self.assertEqual(embed["title"], "📉 DAGENS BEDSTE PRISER")
        self.assertIn("499 kr.", embed["description"])
        self.assertEqual(embed["footer"]["text"], "MasterBot · Price Watch")

    def test_bad_links_are_not_rendered(self):
        msg = (
            "🆕 **[POKÉMON] NYT PÅ PROSHOP**\n"
            "**Pokemon Booster Bundle**\n"
            "🔗 https://example.org/product with-whitespace"
        )
        # Extracted first whitespace-delimited valid link remains informational.
        embed = self.embed(msg)
        self.assertEqual(embed["url"], "https://example.org/product")
        broken = (
            "🆕 **[POKÉMON] NYT PÅ PROSHOP**\n"
            "**Pokemon Booster Bundle**\n"
            "🔗 http://"
        )
        self.assertNotIn("url", self.embed(broken))

    def test_deduplication_is_unmodified_by_formatter(self):
        self.assertTrue(callable(self.functions["_discord_product_embed"]))
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("alert_decision = restock_alert_decision(message)", source)
        self.assertIn('RESTOCK_ALERT_MEMORY[alert_key] = alert_entry', source)


if __name__ == "__main__":
    unittest.main()
