import ast
import re
import unittest
from pathlib import Path


def load_guard():
    source = Path("restock_bot_github.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef)
        and item.name == "is_matraws_single_alert_product"
    )
    module = ast.Module(body=[node], type_ignores=[])
    namespace = {"re": re}
    exec(
        compile(ast.fix_missing_locations(module), "<matraws-single-guard>", "exec"),
        namespace,
    )
    return namespace["is_matraws_single_alert_product"]


class MatrawsSingleGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = staticmethod(load_guard())

    def test_tcg_classic_raichu_single_is_blocked(self):
        product = {
            "name": (
                "Raichu - Pokémon Trading Card Game Classic: "
                "Charizard & Ho-Oh ex Deck (Fixed) [CLC-009]"
            ),
            "url": (
                "https://matraws.dk/products/raichu-pokemon-trading-card-game-"
                "classic-charizard-ho-oh-ex-deck-fixed-009-745701"
            ),
        }
        self.assertTrue(self.guard(product))

    def test_tcg_classic_magmar_single_is_blocked(self):
        product = {
            "name": (
                "Magmar - Pokémon Trading Card Game Classic: "
                "Charizard & Ho-Oh ex Deck (Fixed) [CLC-006]"
            ),
            "url": (
                "https://matraws.dk/products/magmar-pokemon-trading-card-game-"
                "classic-charizard-ho-oh-ex-deck-fixed-006-745698"
            ),
        }
        self.assertTrue(self.guard(product))

    def test_normal_single_with_number_only_is_blocked(self):
        product = {
            "name": "Hitmonchan - Base Set (Holo Rare) [7]",
            "url": "https://matraws.dk/products/hitmonchan-base-set-holo-rare-7",
        }
        self.assertTrue(self.guard(product))

    def test_single_with_box_in_card_name_is_still_blocked(self):
        product = {
            "name": "Box of Disaster - Lost Origin (Uncommon) [LOR-154]",
            "url": "https://matraws.dk/products/box-of-disaster-lost-origin-uncommon-154",
        }
        self.assertTrue(self.guard(product))

    def test_matraws_booster_box_is_allowed(self):
        product = {
            "name": "Pokémon TCG: Mega Evolution: Chaos Rising - Booster Box",
            "url": "https://matraws.dk/products/pokemon-tcg-chaos-rising-booster-box",
        }
        self.assertFalse(self.guard(product))

    def test_matraws_booster_pack_is_allowed(self):
        product = {
            "name": "Pokémon TCG: Scarlet & Violet: Journey Together - Booster Pack",
            "url": "https://matraws.dk/products/pokemon-tcg-journey-together-booster-pack",
        }
        self.assertFalse(self.guard(product))

    def test_matraws_upc_is_allowed(self):
        product = {
            "name": "Pokémon TCG: Mega Charizard X ex - Ultra Premium Collection (UPC)",
            "url": "https://matraws.dk/products/pokemon-tcg-mega-charizard-x-ex-upc",
        }
        self.assertFalse(self.guard(product))

    def test_same_signature_from_other_shop_is_not_matraws_blocked(self):
        product = {
            "name": "Hitmonchan - Base Set (Holo Rare) [7]",
            "url": "https://example-cardshop.dk/products/hitmonchan-base-set-7",
        }
        self.assertFalse(self.guard(product))


if __name__ == "__main__":
    unittest.main()
