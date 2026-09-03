import json
import unittest
from pathlib import Path

from personal import singles_collection_runner as cr


class CollectionIntegrationTests(unittest.TestCase):
    def test_real_collection_baseline_counts(self):
        collection = json.loads(Path("personal/collection.json").read_text(encoding="utf-8"))
        stats = cr.validate_collection(collection)
        self.assertEqual(stats["physical_cards"], 133)
        self.assertEqual(stats["unique_exact_records"], 125)
        self.assertEqual(stats["pokemon_cards"], 132)
        self.assertEqual(stats["lorcana_cards"], 1)
        self.assertEqual(stats["linked_cardmarket_product_ids"], 0)

    def test_unlinked_owned_card_does_not_guess_an_id(self):
        collection = {"cards": [{"collection_key": "pokemon|set|1|pikachu|normal", "tcg": "POKEMON", "quantity": 1, "status": "owned", "cardmarket_product_id": None}]}
        profile, stats = cr.apply_collection_filters({"owned_ids": []}, collection, {"cards": []})
        self.assertEqual(profile["owned_ids"], [])
        self.assertEqual(stats["linked_owned_ids"], 0)

    def test_verified_owned_id_is_blocked(self):
        collection = {"cards": [{"collection_key": "pokemon|set|1|pikachu|normal", "tcg": "POKEMON", "quantity": 1, "status": "owned", "cardmarket_product_id": "123456"}]}
        profile, stats = cr.apply_collection_filters({"owned_ids": []}, collection, {"cards": []})
        self.assertEqual(profile["owned_ids"], ["123456"])
        self.assertEqual(stats["linked_owned_ids"], 1)

    def test_verified_incoming_id_is_also_blocked(self):
        collection = {"cards": [{"collection_key": "pokemon|set|1|mew|normal", "tcg": "POKEMON", "quantity": 1, "status": "owned", "cardmarket_product_id": None}]}
        incoming = {"cards": [{"tcg": "POKEMON", "status": "incoming", "cardmarket_product_id": "999999"}]}
        profile, stats = cr.apply_collection_filters({"owned_ids": []}, collection, incoming)
        self.assertEqual(profile["owned_ids"], ["999999"])
        self.assertEqual(stats["linked_incoming_ids"], 1)

    def test_legacy_owned_ids_are_preserved(self):
        collection = {"cards": [{"collection_key": "pokemon|set|1|mew|normal", "tcg": "POKEMON", "quantity": 1, "status": "owned", "cardmarket_product_id": "222222"}]}
        profile, _ = cr.apply_collection_filters({"owned_ids": ["111111"]}, collection, {"cards": []})
        self.assertEqual(set(profile["owned_ids"]), {"111111", "222222"})

    def test_duplicate_collection_key_fails_closed(self):
        card = {"collection_key": "pokemon|set|1|mew|normal", "tcg": "POKEMON", "quantity": 1, "status": "owned", "cardmarket_product_id": None}
        with self.assertRaisesRegex(ValueError, "duplicate collection_key"):
            cr.validate_collection({"cards": [card, dict(card)]})

    def test_declared_totals_must_match(self):
        collection = {"totals": {"physical_cards": 2}, "cards": [{"collection_key": "pokemon|set|1|mew|normal", "tcg": "POKEMON", "quantity": 1, "status": "owned", "cardmarket_product_id": None}]}
        with self.assertRaisesRegex(ValueError, "totals mismatch"):
            cr.validate_collection(collection)

    def test_non_numeric_verified_id_fails_closed(self):
        collection = {"cards": [{"collection_key": "pokemon|set|1|mew|normal", "tcg": "POKEMON", "quantity": 1, "status": "owned", "cardmarket_product_id": "mew"}]}
        with self.assertRaisesRegex(ValueError, "invalid Cardmarket product id"):
            cr.validate_collection(collection)

    def test_unresolved_rows_are_explicit(self):
        collection = {"cards": [
            {"collection_key": "pokemon|set|1|mew|normal", "tcg": "POKEMON", "quantity": 1, "status": "owned", "name": "Mew", "set": "Set", "number": "1/10", "variant": "normal", "cardmarket_product_id": None},
            {"collection_key": "pokemon|set|2|pikachu|normal", "tcg": "POKEMON", "quantity": 1, "status": "owned", "name": "Pikachu", "set": "Set", "number": "2/10", "variant": "normal", "cardmarket_product_id": "123"},
        ]}
        unresolved = cr.unresolved_collection_rows(collection)
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["name"], "Mew")

    def test_suppression_diagnostics_counts_exact_owned_and_incoming(self):
        state = {"cards": {
            "1": {"id": "101", "game": "POKÉMON", "name": "Pikachu", "set": "Set", "trend": 1, "avg7": 1.2, "avg30": 1.3},
            "2": {"id": "202", "game": "POKÉMON", "name": "Mew", "set": "Set", "trend": 1, "avg7": 1.2, "avg30": 1.3},
            "3": {"id": "303", "game": "POKÉMON", "name": "Snorlax", "set": "Set", "trend": 1, "avg7": 1.2, "avg30": 1.3},
        }}
        profile = {"owned_ids": [], "priority_pokemon": ["Pikachu", "Mew", "Snorlax"]}
        collection = {"cards": [{"collection_key": "pokemon|set|1|pikachu|normal", "tcg": "POKEMON", "quantity": 1, "status": "owned", "cardmarket_product_id": "101"}]}
        incoming = {"cards": [{"tcg": "POKEMON", "status": "incoming", "cardmarket_product_id": "202"}]}
        diagnostics = cr.suppression_diagnostics(state, profile, collection, incoming)
        self.assertEqual(diagnostics["baseline_personal_candidates"], 3)
        self.assertEqual(diagnostics["owned_filtered"], 1)
        self.assertEqual(diagnostics["incoming_filtered"], 1)
        self.assertEqual(diagnostics["exact_filtered_union"], 2)


if __name__ == "__main__":
    unittest.main()
