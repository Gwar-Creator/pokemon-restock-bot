import unittest

from alert_policy import abundant_set_signal_allowed


class AbundantSetPolicyTests(unittest.TestCase):
    def test_pitch_black_single_pack_aliases_are_blocked(self):
        self.assertFalse(
            abundant_set_signal_allowed("Pokémon ME05 Pitch Black samlekort")
        )
        self.assertFalse(
            abundant_set_signal_allowed(
                "Pokémon Pitch Black 1-pak – flere varianter – assorteret"
            )
        )

    def test_abundant_set_etbs_are_blocked(self):
        self.assertFalse(
            abundant_set_signal_allowed("Pokémon TCG Pitch Black Elite Trainer Box")
        )
        self.assertFalse(
            abundant_set_signal_allowed("Pokémon Chaos Rising ETB")
        )

    def test_high_signal_formats_still_pass(self):
        self.assertTrue(
            abundant_set_signal_allowed("Pokémon Pitch Black Booster Bundle")
        )
        self.assertTrue(
            abundant_set_signal_allowed("Pokémon Chaos Rising Booster Display")
        )
        self.assertTrue(
            abundant_set_signal_allowed("Pokémon Pitch Black Illustration Collection")
        )

    def test_series_metadata_can_block_generic_titles(self):
        self.assertFalse(
            abundant_set_signal_allowed(
                "Pokémon TCG booster pack samlekort",
                "Mega Evolution: Chaos Rising",
            )
        )

    def test_other_sets_are_untouched_by_this_policy(self):
        self.assertTrue(
            abundant_set_signal_allowed("Pokémon Journey Together 1-pak")
        )


if __name__ == "__main__":
    unittest.main()
