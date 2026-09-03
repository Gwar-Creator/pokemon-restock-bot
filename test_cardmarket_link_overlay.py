import json
import unittest
from pathlib import Path

from personal.cardmarket_link_overlay import apply_links


def collection():
    return {
        "fields": ["name", "set", "number", "variant", "quantity", "language", "cardmarket_product_id"],
        "totals": {"linked_cardmarket_product_ids": 0},
        "groups": {
            "modern_pokemon": [
                ["Pikachu", "Example Set", "001/100", "standard", 1, "EN", None],
                ["Mew", "Example Set", "002/100", "illustration rare", 1, "EN", None],
            ],
            "modern_lorcana": [["Elsa", "Example", "1/100", "enchanted", 1, "EN", None]],
        },
    }


class CardmarketLinkOverlayTests(unittest.TestCase):
    def test_exact_link_is_applied(self):
        links = {"links": [{"tcg": "POKEMON", "name": "Pikachu", "set": "Example Set", "number": "001/100", "variant": "standard", "cardmarket_product_id": "123456"}]}
        linked, stats = apply_links(collection(), links)
        self.assertEqual(linked["groups"]["modern_pokemon"][0][-1], "123456")
        self.assertEqual(stats["linked_records"], 1)
        self.assertEqual(stats["unlinked_records"], 2)

    def test_wrong_variant_fails_closed(self):
        links = {"links": [{"tcg": "POKEMON", "name": "Pikachu", "set": "Example Set", "number": "001/100", "variant": "reverse holo", "cardmarket_product_id": "123456"}]}
        with self.assertRaisesRegex(ValueError, "no exact collection record"):
            apply_links(collection(), links)

    def test_duplicate_link_fails_closed(self):
        row = {"tcg": "POKEMON", "name": "Pikachu", "set": "Example Set", "number": "001/100", "variant": "standard", "cardmarket_product_id": "123456"}
        with self.assertRaisesRegex(ValueError, "duplicate exact link"):
            apply_links(collection(), {"links": [row, dict(row)]})

    def test_conflicting_existing_id_fails_closed(self):
        base = collection()
        base["groups"]["modern_pokemon"][0][-1] = "999999"
        links = {"links": [{"tcg": "POKEMON", "name": "Pikachu", "set": "Example Set", "number": "001/100", "variant": "standard", "cardmarket_product_id": "123456"}]}
        with self.assertRaisesRegex(ValueError, "id conflict"):
            apply_links(base, links)

    def test_compact_links_are_supported(self):
        links = {
            "fields": ["tcg", "name", "set", "number", "variant", "cardmarket_product_id"],
            "links": [["POKEMON", "Mew", "Example Set", "002/100", "illustration rare", "222222"]],
        }
        linked, stats = apply_links(collection(), links)
        self.assertEqual(linked["groups"]["modern_pokemon"][1][-1], "222222")
        self.assertEqual(stats["applied_links"], 1)

    def test_real_v52_sidecar_matches_collection_exactly(self):
        real_collection = json.loads(Path("personal/collection.json").read_text(encoding="utf-8"))
        real_links = json.loads(Path("personal/cardmarket_links.json").read_text(encoding="utf-8"))
        linked, stats = apply_links(real_collection, real_links)
        self.assertEqual(stats["collection_records"], 125)
        self.assertEqual(stats["applied_links"], 116)
        self.assertEqual(stats["linked_records"], 116)
        self.assertEqual(stats["unlinked_records"], 9)
        self.assertEqual(linked["totals"]["linked_cardmarket_product_ids"], 116)


if __name__ == "__main__":
    unittest.main()
