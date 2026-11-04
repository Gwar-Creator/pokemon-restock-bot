"""Cross-lane Discord mobile contract: offline renderers and no extra alerts."""
import re
import unittest
from unittest.mock import patch

from discord_alert_v2 import (
    STATUS, MAX_STORE_LINES, classify, compact_store_lines, render_embed,
)
from tools.discord_mobile_preview import WIDTH, case_payloads, preview_markdown

COLOR_GREEN = 0x57F287
COLOR_NEUTRAL = 0x95A5A6


class DiscordMobileContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (
            patch("requests.get", side_effect=AssertionError("Preview must be offline")),
            patch("requests.post", side_effect=AssertionError("Preview must not send Discord")),
        ):
            cls.samples = case_payloads()

    def test_all_six_shared_statuses_have_preview_examples(self):
        expected = {"BUY_NOW", "RESERVE_NOW", "STORE_STOCK",
                    "PREPUBLISH", "PREORDER", "UNKNOWN"}
        actual = {status for _, status, _ in self.samples}
        self.assertTrue(expected.issubset(actual))
        self.assertEqual(len(STATUS), 6)
        self.assertGreaterEqual(len(self.samples), 12)

    def test_every_payload_is_discord_safe_with_one_embed_and_no_mentions(self):
        for case, status, payload in self.samples:
            with self.subTest(case=case):
                self.assertEqual(payload.get("allowed_mentions"), {"parse": []})
                self.assertEqual(len(payload["embeds"]), 1)
                embed = payload["embeds"][0]
                self.assertLessEqual(len(embed.get("title", "")), 256)
                self.assertLessEqual(len(embed.get("description", "")), 4096)
                fields = embed.get("fields", [])
                self.assertLessEqual(len(fields), 25)
                for field in fields:
                    self.assertGreater(len(field["name"]), 0)
                    self.assertLessEqual(len(field["name"]), 256)
                    self.assertGreater(len(field["value"]), 0)
                    self.assertLessEqual(len(field["value"]), 1024)
                self.assertLessEqual(len(embed.get("footer", {}).get("text", "")), 2048)
                if embed.get("url"):
                    self.assertTrue(embed["url"].startswith("https://"))
                if embed.get("thumbnail"):
                    self.assertTrue(embed["thumbnail"]["url"].startswith("https://"))

    def test_only_verified_action_examples_use_green(self):
        for case, status, payload in self.samples:
            with self.subTest(case=case):
                embed = payload["embeds"][0]
                if status in {"UNKNOWN", "STORE_STOCK", "PREPUBLISH", "CATALOG", "REVIEW"}:
                    self.assertNotEqual(embed["color"], COLOR_GREEN)
                    self.assertNotIn("KØB NU", embed["title"])
                elif status == "BUY_NOW":
                    self.assertEqual(embed["color"], COLOR_GREEN)
                    self.assertIn("KØB NU", embed["title"])
                elif status == "RESERVE_NOW":
                    self.assertIn("RESERVÉR NU", embed["title"])
                    self.assertNotEqual(embed["color"], COLOR_GREEN)
                elif status == "PREORDER":
                    self.assertEqual(embed["color"], STATUS["PREORDER"][1])

    def test_unverified_system_stock_has_no_clickable_buy_link(self):
        for case, status, payload in self.samples:
            if "systemlager" in case or status in {"STORE_STOCK", "PREPUBLISH"}:
                with self.subTest(case=case):
                    self.assertNotIn("url", payload["embeds"][0])

    def test_cardmarket_and_vintage_never_imply_confirmed_deals(self):
        for case, status, payload in self.samples:
            if "Cardmarket" in case or "Vintage Finder" in case:
                with self.subTest(case=case):
                    embed = payload["embeds"][0]
                    self.assertEqual(status, "REVIEW")
                    self.assertEqual(embed["color"], COLOR_NEUTRAL)
                    summary = str(embed).lower()
                    self.assertTrue(
                        "ikke et købsråd" in summary or
                        "ikke en købsanbefaling" in summary
                    )
                    self.assertNotIn("KØB NU", embed["title"])

    def test_capped_store_lines_do_not_cut_a_store_row_mid_name(self):
        stores = [
            (("Butik med langt navn " + "X" * 140 + str(i)), i + 1)
            for i in range(30)
        ]
        result = compact_store_lines(stores)
        self.assertLessEqual(len(result), 1024)
        self.assertLessEqual(len(result.splitlines()), MAX_STORE_LINES + 1)
        lines = result.splitlines()
        self.assertTrue(any("yderligere butikker" in line for line in lines))
        for line in lines:
            with self.subTest(line=line[:22]):
                self.assertTrue(
                    re.search(r": \d+ stk\.$", line) or
                    re.search(r"^\u2026 samt \d+ yderligere butikker$", line),
                    f"Incomplete store line: {line}",
                )
        missing = int(re.search(r"(\d+) yderligere butikker", lines[-1]).group(1))
        self.assertEqual(missing + len(lines) - 1, len(stores))

    def test_normal_store_listing_keeps_first_twelve_and_remainder(self):
        stores = [(f"Butik {idx}", idx + 1) for idx in range(30)]
        output = compact_store_lines(stores)
        self.assertEqual(output.splitlines()[0], "Butik 0: 1 stk.")
        self.assertEqual(output.splitlines()[11], "Butik 11: 12 stk.")
        self.assertIn("18 yderligere butikker", output)

    def test_unsafe_booleans_do_not_create_phantom_stock(self):
        value = render_embed({
            "source": "BR", "name": "EKSEMPEL",
            "stores": [{"name": "BR Kolding", "stock": True}],
            "online_buyable": False,
        })
        self.assertEqual(value["title"], "UKENDT · BR")
        self.assertNotIn("REGISTRERET BUTIKSLAGER", str(value))

    def test_mobile_preview_is_wrapped_and_synthetic(self):
        with (
            patch("requests.get", side_effect=AssertionError("No network")),
            patch("requests.post", side_effect=AssertionError("No Discord")),
        ):
            doc = preview_markdown(self.samples)
        self.assertIn("Kun syntetiske eksempler", doc)
        self.assertIn("ikke et Discord-screenshot", doc)
        self.assertIn("Cardmarket · konkret REVIEW", doc)
        self.assertIn("Hidden · BR Kolding", doc)
        self.assertIn("V2 · hypotetisk C&C-verifikation", doc)
        fence = chr(96) * 3
        inside = False
        for line in doc.splitlines():
            if line.startswith(fence):
                inside = not inside
                continue
            if inside:
                self.assertLessEqual(len(line), WIDTH, line)

    def test_fixtures_do_not_modify_live_product_state(self):
        product = {"source": "BR", "name": "EKSEMPEL",
                   "stores": [{"name": "BR Kolding", "stock": 3}]}
        original = {"source": product["source"], "name": product["name"],
                    "stores": [dict(product["stores"][0])]}
        self.assertEqual(classify(product), "STORE_STOCK")
        self.assertEqual(product, original)


if __name__ == "__main__":
    unittest.main()
