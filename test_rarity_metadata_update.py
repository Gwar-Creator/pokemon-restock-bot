import unittest

from personal import update_rarity_metadata as updater


PROFILE = {
    "priority_pokemon": ["Pikachu", "Psyduck"],
    "secondary_pokemon": ["Vaporeon"],
    "wishlist_ids": [],
    "manual_priority_ids": [],
    "owned_ids": [],
    "ignore_ids": [],
}


class RarityMetadataUpdateTests(unittest.TestCase):
    def test_ex_era_set_aliases_normalize_to_cardmarket_names(self):
        self.assertEqual(updater.normalized_set("Crystal Guardians"), "ex crystal guardians")
        self.assertEqual(updater.normalized_set("EX Crystal Guardians"), "ex crystal guardians")
        self.assertEqual(updater.normalized_set("Paldea Evolved"), "paldea evolved")

    def test_personal_candidates_include_modern_subjects(self):
        state = {
            "cards": {
                "POKÉMON|794611": {
                    "game": "POKÉMON",
                    "id": "794611",
                    "set": "Surging Sparks",
                    "name": "Pikachu ex [Resolute Heart | Topaz Bolt]",
                },
                "POKÉMON|999": {
                    "game": "POKÉMON",
                    "id": "999",
                    "set": "Test Set",
                    "name": "Bulbasaur [Tackle]",
                },
            }
        }
        result = updater.personal_candidates(state, PROFILE)
        self.assertIn("794611", result)
        self.assertEqual(result["794611"]["subject"], "Pikachu ex")
        self.assertNotIn("999", result)

    def test_candidate_briefs_require_exact_subject_and_set(self):
        candidates = {
            "794611": {
                "set": "Surging Sparks",
                "set_key": "surging sparks",
                "subject": "Pikachu ex",
                "subject_key": "pikachu ex",
            }
        }
        briefs = [
            {"id": "sv08-238", "name": "Pikachu ex"},
            {"id": "sv08-219", "name": "Pikachu ex"},
            {"id": "sv03-063", "name": "Pikachu ex"},
            {"id": "sv08-001", "name": "Pikachu"},
        ]
        sets = {"sv08": "Surging Sparks", "sv03": "Obsidian Flames"}
        self.assertEqual(
            updater.candidate_brief_ids(briefs, candidates, sets),
            ["sv08-219", "sv08-238"],
        )

    def test_exact_modern_sir_cardmarket_id_is_enriched(self):
        candidates = {
            "794611": {
                "set": "Surging Sparks",
                "set_key": "surging sparks",
                "subject": "Pikachu ex",
                "subject_key": "pikachu ex",
            }
        }
        tcgdex_card = {
            "id": "sv08-238",
            "localId": "238",
            "name": "Pikachu ex",
            "rarity": "Special illustration rare",
            "set": {"id": "sv08", "name": "Surging Sparks"},
            "variants_detailed": [
                {
                    "type": "holo",
                    "thirdParty": {"cardmarket": 794611},
                }
            ],
        }
        result = updater.metadata_from_card(tcgdex_card, candidates)
        meta = result["794611"]
        self.assertEqual(meta["canonical_rarity"], "Special illustration rare")
        self.assertEqual(meta["canonical_number"], "238")
        self.assertEqual(meta["metadata_confidence"], "EXACT_CARDMARKET_ID")
        self.assertIn("exact Cardmarket idProduct", meta["verified_by"])

    def test_wrong_cardmarket_id_never_fuzzy_matches_same_card(self):
        candidates = {
            "794611": {
                "set": "Surging Sparks",
                "set_key": "surging sparks",
                "subject": "Pikachu ex",
                "subject_key": "pikachu ex",
            }
        }
        tcgdex_card = {
            "id": "sv08-219",
            "localId": "219",
            "name": "Pikachu ex",
            "rarity": "Ultra rare",
            "set": {"id": "sv08", "name": "Surging Sparks"},
            "variants_detailed": [
                {
                    "type": "holo",
                    "thirdParty": {"cardmarket": 793587},
                }
            ],
        }
        self.assertEqual(updater.metadata_from_card(tcgdex_card, candidates), {})

    def test_root_pricing_cardmarket_id_is_supported(self):
        card = {
            "pricing": {"cardmarket": {"idProduct": 877413}},
            "variants_detailed": [],
        }
        self.assertEqual(updater.cardmarket_variant_ids(card), {"877413": "root"})


if __name__ == "__main__":
    unittest.main()
