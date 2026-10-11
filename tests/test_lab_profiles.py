import copy
import subprocess
import sys
import unittest
from unittest import mock

from ai import lab_profiles as profiles, prediction_ledger as ledger
from tests.test_algorithm_lab import history


class LabProfileTests(unittest.TestCase):
    def test_catalog_import_does_not_require_predictors_or_coverage(self):
        script = ("import sys; from ai import lab_profiles; "
                  "assert len(lab_profiles.list_profiles()) == 6; "
                  "assert 'ai.predictors' not in sys.modules; "
                  "assert 'ai.adaptive_coverage' not in sys.modules")
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_catalog_has_bounded_real_history_weight_and_allocation_variations(self):
        catalog = profiles.list_profiles("LOTO_5_35")
        self.assertEqual(len(catalog), 6)
        self.assertEqual({item["historyWindow"] for item in catalog}, {60, 180, None})
        self.assertEqual(len({tuple(item["weights"]) for item in catalog}), 3)
        self.assertEqual({item["allocation"] for item in catalog}, {"stable", "aggressive"})
        self.assertTrue(all(item["weights"][1] == 0 for item in catalog))
        self.assertTrue(all(item["uniformMix"] == 0.85 for item in catalog))
        catalog[0]["weights"][0] = 42
        self.assertEqual(profiles.profile_definition("short_stable")["weights"][0], 0.6)

    def test_all_profiles_equal_standard_ticket_budget_deterministic_and_no_io(self):
        from ai import controlled_models, ml_pipeline, prediction_effectiveness as effect
        for game in ("LOTO_5_35", "LOTO_6_45", "LOTO_6_55"):
            draws = history(game, 60)
            original = copy.deepcopy(draws)
            snapshot = {"cutoff": "60", "target": "61"}
            with mock.patch.object(ledger, "connect", side_effect=AssertionError("ledger write")), \
                    mock.patch.object(ml_pipeline, "load_actual_draws", side_effect=AssertionError("source read")), \
                    mock.patch.object(controlled_models, "champion_prediction", side_effect=AssertionError("registry read")):
                for profile in profiles.list_profiles(game):
                    with self.subTest(game=game, profile=profile["id"]):
                        first = profiles.predict_profile(game, profile["id"], draws, 3)
                        second = profiles.predict_profile(game, profile["id"], draws, 3)
                        self.assertEqual(first, second)
                        effect._validate(first, game, 3, snapshot)
                        self.assertEqual(first["probabilityCalibrationStatus"], "uncalibrated")
                        self.assertEqual(first["configHash"], profiles.config_hash(profile))
                        self.assertEqual(first["profileDefinition"], profile)
                        self.assertTrue(all(value > 0 for value in first["probabilities"].values()))
                        self.assertEqual(len({tuple(ticket["main"]) for ticket in first["tickets"]}), 3)
            self.assertEqual(draws, original)

    def test_history_and_weight_setups_change_estimates(self):
        draws = history(count=240)
        forecasts = [profiles.predict_profile("LOTO_5_35", f"{name}_stable", draws, 2)
                     for name in ("short", "medium", "long")]
        self.assertEqual([result["scoringHistoryCount"] for result in forecasts], [60, 180, 240])
        self.assertEqual(len({ledger.canonical_json(item["probabilities"]) for item in forecasts}), 3)

    def test_allocation_changes_portfolio_on_same_candidate_pool(self):
        draws = history(count=90)
        stable = profiles.predict_profile("LOTO_5_35", "medium_stable", draws, 5)
        focused = profiles.predict_profile("LOTO_5_35", "medium_aggressive", draws, 5)
        self.assertEqual(stable["probabilities"], focused["probabilities"])
        self.assertEqual(stable["randomSeed"], focused["randomSeed"])
        self.assertNotEqual(stable["tickets"], focused["tickets"])
        self.assertNotEqual(stable["configHash"], focused["configHash"])

    def test_window_excludes_older_rows_from_estimates_but_records_full_prefix_hash(self):
        draws = history(count=90)
        before = profiles.predict_profile("LOTO_5_35", "short_stable", draws, 1)
        altered = copy.deepcopy(draws)
        altered[0]["main"] = [1, 2, 3, 4, 5]
        altered[0]["special"] = 1
        after = profiles.predict_profile("LOTO_5_35", "short_stable", altered, 1)
        self.assertEqual(before["probabilities"], after["probabilities"])
        self.assertEqual(before["specialProbabilities"], after["specialProbabilities"])
        self.assertNotEqual(before["dataHash"], after["dataHash"])

    def test_unknown_profile_invalid_budget_or_history_fail_explicitly(self):
        for profile_id, count, draws in (("bad", 1, history()), ("short_stable", True, history()),
                                         ("short_stable", 0, history()), ("short_stable", 11, history()),
                                         ("short_stable", 1, [])):
            with self.subTest(profile=profile_id, count=count), self.assertRaises(ValueError):
                profiles.predict_profile("LOTO_5_35", profile_id, draws, count)
        for game in ("KENO", "bad"):
            with self.assertRaises(ValueError):
                profiles.list_profiles(game)
        duplicate = history()
        duplicate[1]["ky"] = "1"
        with self.assertRaises(ValueError):
            profiles.predict_profile("LOTO_5_35", "short_stable", duplicate, 1)


if __name__ == "__main__":
    unittest.main()
