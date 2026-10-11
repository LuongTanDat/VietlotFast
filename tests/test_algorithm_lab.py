import copy
import hashlib
import io
import json
import random
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from ai import algorithm_lab as lab, controlled_models, ml_pipeline, prediction_ledger as ledger
from ai.predictors import ai_predict as predictor


def history(game="LOTO_5_35", count=70):
    cfg = ml_pipeline.game_config(game)
    rng = random.Random(8675309)
    result = []
    for index in range(count):
        day = datetime(2024, 1, 1) + timedelta(days=index // 2 if game == "LOTO_5_35" else index * 3)
        main = sorted(rng.sample(range(1, cfg["universe_size"] + 1), cfg["draw_size"]))
        special = rng.randrange(1, 13) if game == "LOTO_5_35" else (
            rng.choice([n for n in range(1, 56) if n not in main]) if game == "LOTO_6_55" else None)
        result.append({"ky": str(index + 1), "date": day.strftime("%d/%m/%Y"),
                       "time": ("13:00" if index % 2 == 0 else "21:00") if game == "LOTO_5_35" else "18:00",
                       "main": main, "special": special})
    return result


class AlgorithmLabTests(unittest.TestCase):
    GAME = "LOTO_5_35"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.db = self.root / "ledger.sqlite"
        self.draws = history()
        runtime_patch = mock.patch.object(lab.dp, "RUNTIME_DIR", self.root)
        runtime_patch.start()
        self.addCleanup(runtime_patch.stop)
        db_patch = mock.patch.object(ledger, "DEFAULT_DB_PATH", self.db)
        db_patch.start()
        self.addCleanup(db_patch.stop)

    def _champion(self, training=None, transform=None):
        training = training or self.draws[:60]
        artifact = controlled_models.fit_artifact(self.GAME, training, ml_pipeline.game_config(self.GAME))
        if transform:
            transform(artifact)
        paths = controlled_models.save_artifact(self.GAME, artifact, "fixture_champion")
        ledger.register_model(self.GAME, controlled_models.PIPELINE, artifact["trained_data_cutoff"], "champion",
                              artifact_paths=paths, model_id="fixture_champion", db_path=self.db)
        return paths

    def _files(self):
        return {str(path.relative_to(self.root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.root.rglob("*") if path.is_file()}

    def _fast_web(self, game, count, prefix, registry):
        snapshot = lab._fold_snapshot(game, prefix, {"ky": str(int(prefix[-1]["ky"]) + 1)})
        return lab.effect._baseline(game, "bayesian", count, snapshot)

    def test_full_web_pipeline_all_games_equal_budget_and_no_production_writes(self):
        # These are real production ranking and Adaptive Coverage calls, not a
        # surrogate model. Canonical/registry writes must remain unreachable.
        for game in lab.effect.GAMES:
            with self.subTest(game=game), \
                    mock.patch.object(predictor.lr, "sync_requested_canonical_csvs", side_effect=AssertionError("must not sync")), \
                    mock.patch.object(predictor, "ensure_gen_local_model", side_effect=AssertionError("must not fit")), \
                    mock.patch.object(ledger, "connect", side_effect=AssertionError("must not initialize ledger")):
                draws = history(game)
                before = copy.deepcopy(draws)
                files = self._files()
                progress = []
                report = lab.evaluate_draws(game, draws, 2, 5, 5, registry=lab.FrozenRegistry(),
                                            progress=lambda done, total: progress.append((done, total)))
                self.assertEqual(draws, before)
                self.assertEqual(self._files(), files)
                self.assertEqual(progress, [(n, 10) for n in range(1, 11)])
                self.assertEqual(report["split"]["training"], {"count": 60, "firstDrawId": "1", "lastDrawId": "60"})
                self.assertEqual(report["split"]["validation"]["lastDrawId"], "65")
                self.assertEqual(report["split"]["test"]["firstDrawId"], "66")
                self.assertEqual(report["scope"], "historical_diagnostic")
                self.assertTrue(report["selection"]["validationOnly"])
                self.assertEqual(len(report["profiles"]), 6)
                self.assertEqual(len(report["methods"]), 10)
                self.assertEqual(report["profileVersion"], lab.lab_profiles.PROFILE_VERSION)
                self.assertEqual(report["selection"]["profileDefinition"],
                                 lab.lab_profiles.profile_definition(report["selection"]["candidateProfileId"]))
                self.assertEqual(report["selection"]["configHash"],
                                 lab.lab_profiles.config_hash(report["selection"]["profileDefinition"]))
                self.assertTrue(report["conclusion"]["canTrack"])
                self.assertEqual(report["conclusion"]["status"], "insufficient_evidence")
                self.assertEqual(set(report["conclusion"]["evidence"]), {"random", "web"})
                self.assertEqual(len(report["provenance"]["sourceHash"]), 64)
                for fold in report["folds"]:
                    self.assertEqual(int(fold["cutoffDrawId"]) + 1, int(fold["targetDrawId"]))
                    self.assertEqual(set(fold["methods"]), set(lab.METHODS))
                    for method in fold["methods"].values():
                        self.assertEqual(len(method["tickets"]), 2)
                        self.assertTrue(all(len(ticket["main"]) == ml_pipeline.game_config(game)["draw_size"]
                                            for ticket in method["tickets"]))
                        self.assertEqual(sum(method["prizeHistogram"].values()), 2)
                        self.assertIsInstance(method["seed"], int)
                    self.assertEqual(fold["methods"]["web"]["engine"], "classic")
                    self.assertEqual(fold["methods"]["web"]["probabilityCalibrationStatus"], "uncalibrated")
                self.assertFalse(self.db.exists())

    def test_future_result_mutations_do_not_change_validation_or_selected_method(self):
        first = lab.evaluate_draws(self.GAME, self.draws, 1, 5, 5, registry=lab.FrozenRegistry())
        altered = copy.deepcopy(self.draws)
        for row in altered[65:]:
            row["main"] = sorted(((n + 10) % 35) + 1 for n in row["main"])
            row["special"] = row["special"] % 12 + 1
        second = lab.evaluate_draws(self.GAME, altered, 1, 5, 5, registry=lab.FrozenRegistry())
        self.assertEqual(first["folds"][:5], second["folds"][:5])
        self.assertEqual(first["selection"], second["selection"])
        for before, after in zip(first["methods"], second["methods"]):
            self.assertEqual(before["validation"], after["validation"])
        self.assertNotEqual(first["folds"][5]["actualMain"], second["folds"][5]["actualMain"])
        # The first test forecast still has exactly the same history prefix.
        for method in lab.METHODS:
            self.assertEqual(first["folds"][5]["methods"][method]["payloadChecksum"],
                             second["folds"][5]["methods"][method]["payloadChecksum"])

    def test_prefix_prediction_is_repeatable_and_never_reads_full_history(self):
        prefix = self.draws[:60]
        with mock.patch.object(predictor, "load_ai_source_rows", side_effect=AssertionError("future source read")), \
                mock.patch.object(ml_pipeline, "load_actual_draws", side_effect=AssertionError("unfiltered read")), \
                mock.patch.object(predictor, "evaluate_strategies", wraps=predictor.evaluate_strategies) as strategies:
            first = lab._production_prediction(self.GAME, 3, prefix, lab.FrozenRegistry())
            second = lab._production_prediction(self.GAME, 3, prefix, lab.FrozenRegistry())
        self.assertEqual(first, second)
        self.assertEqual(first["latestKy"], "60")
        self.assertEqual(first["nextKy"].lstrip("#"), "61")
        self.assertEqual(first["adaptiveCoverage"]["seed"], first["randomSeed"])
        self.assertTrue(all(len(call.args[0]) == 60 for call in strategies.call_args_list))
        self.assertFalse(self.db.exists())

    def test_frozen_real_champion_runs_full_pipeline_readonly(self):
        self._champion()
        before = self._files()
        frozen = lab._freeze_registry(self.GAME, self.draws[:60], "61", self.db)
        with mock.patch.object(ledger, "connect", side_effect=AssertionError("registry write")):
            report = lab.evaluate_draws(self.GAME, self.draws, 2, 5, 5, registry=frozen)
        self.assertEqual(self._files(), before)
        self.assertEqual(report["provenance"]["registryModel"]["mode"], "frozen_registry_champion")
        for fold in report["folds"]:
            self.assertEqual(fold["methods"]["web"]["engine"], "registry_champion")
            self.assertEqual(fold["methods"]["web"]["modelId"], "fixture_champion")
            self.assertEqual(len(fold["methods"]["web"]["tickets"]), 2)

    def test_champion_pointer_is_frozen_for_whole_job(self):
        self._champion()
        frozen = lab._freeze_registry(self.GAME, self.draws[:60], "61", self.db)
        # A concurrent registry update cannot switch the replay to another model.
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute("UPDATE model_registry SET status='archived'")
            connection.commit()
        payload = lab._production_prediction(self.GAME, 1, self.draws[:60], frozen)
        self.assertEqual(payload["modelId"], "fixture_champion")

    def test_registry_snapshot_reads_committed_wal_without_touching_source_files(self):
        self._champion()
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute("PRAGMA wal_autocheckpoint=0")
            connection.execute("UPDATE model_registry SET version='committed_in_wal'")
            connection.commit()
            self.assertGreater(self.db.with_name(self.db.name + "-wal").stat().st_size, 0)
            before = self._files()
            frozen = lab._freeze_registry(self.GAME, self.draws[:60], "61", self.db)
            self.assertEqual(frozen.model["version"], "committed_in_wal")
            self.assertEqual(self._files(), before)

    def test_registry_changed_during_snapshot_is_rejected(self):
        self._champion()
        original = lab.version
        calls = []
        def changed(path):
            calls.append(path)
            value = original(path)
            return (value[0] + 1, value[1]) if path == self.db and calls.count(path) > 1 else value
        with mock.patch.object(lab, "version", side_effect=changed):
            with self.assertRaisesRegex(RuntimeError, "Registry thay đổi"):
                lab._freeze_registry(self.GAME, self.draws[:60], "61", self.db)

    def test_deleted_registry_does_not_switch_frozen_job_to_classic(self):
        self._champion()
        frozen = lab._freeze_registry(self.GAME, self.draws[:60], "61", self.db)
        self.db.unlink()  # Only this test's disposable database.
        with mock.patch.object(predictor, "build_numeric_prediction") as classic:
            with self.assertRaisesRegex(RuntimeError, "không tự đổi engine"):
                lab._production_prediction(self.GAME, 1, self.draws[:60], frozen)
            classic.assert_not_called()

    def test_champion_trained_on_heldout_target_is_rejected(self):
        self._champion(self.draws[:61])
        with self.assertRaisesRegex(ValueError, "validation/test"):
            lab.evaluate_draws(self.GAME, self.draws, 1, 5, 5)

    def test_champion_training_snapshot_mismatch_is_rejected(self):
        self._champion()
        changed = copy.deepcopy(self.draws)
        changed[0]["special"] = changed[0]["special"] % 12 + 1
        with self.assertRaisesRegex(ValueError, "prefix canonical"):
            lab.evaluate_draws(self.GAME, changed, 1, 5, 5)

    def test_unsafe_artifact_is_not_silently_replaced_by_classic(self):
        paths = self._champion()
        Path(paths["model"]).write_text("{}", encoding="utf-8")
        with mock.patch.object(predictor, "build_numeric_prediction") as classic:
            with self.assertRaisesRegex(ValueError, "artifact hash"):
                lab.evaluate_draws(self.GAME, self.draws, 1, 5, 5)
            classic.assert_not_called()

    def test_wrong_game_dimensions_are_rejected_even_with_valid_checksum(self):
        def wrong_dimensions(artifact):
            artifact["universe_size"] = 45
            artifact["probabilities"] = {str(n): 5 / 45 for n in range(1, 46)}
        self._champion(transform=wrong_dimensions)
        with self.assertRaisesRegex(ValueError, "không khớp game"):
            lab.evaluate_draws(self.GAME, self.draws, 1, 5, 5)

    def test_artifact_changed_mid_replay_aborts_report(self):
        paths = self._champion()
        frozen = lab._freeze_registry(self.GAME, self.draws[:60], "61", self.db)
        def mutate(done, total):
            if done == 1:
                Path(paths["model"]).write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "Artifact thay đổi"):
            lab.evaluate_draws(self.GAME, self.draws, 1, 5, 5, registry=frozen, progress=mutate)

    def test_missing_registry_database_and_schema_are_readonly_legacy(self):
        missing = lab._freeze_registry(self.GAME, self.draws[:60], "61", self.db)
        self.assertIsNone(missing.model)
        self.assertFalse(self.db.exists())
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute("CREATE TABLE unrelated(value TEXT)")
            connection.commit()
        before = self._files()
        frozen = lab._freeze_registry(self.GAME, self.draws[:60], "61", self.db)
        self.assertIsNone(frozen.model)
        self.assertEqual(self._files(), before)

    def test_broken_registry_schema_fails_instead_of_falling_back(self):
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute("CREATE TABLE model_registry(value TEXT)")
            connection.commit()
        with self.assertRaises(sqlite3.OperationalError):
            lab._freeze_registry(self.GAME, self.draws[:60], "61", self.db)

    def test_parameters_and_minimum_history_are_validated_before_prediction(self):
        with mock.patch.object(lab, "_production_prediction") as production:
            for count, validation, testing in ((0, 5, 5), (11, 5, 5), (True, 5, 5),
                                                (1, 4, 5), (1, 51, 5), (1, 5, 4), (1, 5, 51)):
                with self.subTest(parameters=(count, validation, testing)), self.assertRaises(ValueError):
                    lab.evaluate_draws(self.GAME, self.draws, count, validation, testing)
            with self.assertRaisesRegex(ValueError, "60 kỳ"):
                lab.evaluate_draws(self.GAME, self.draws[:-1], 1, 5, 5)
            with self.assertRaises(ValueError):
                lab.evaluate_draws("KENO", self.draws, 1, 5, 5)
            production.assert_not_called()

    def test_duplicate_gap_invalid_ball_and_nonchronological_dates_rejected(self):
        changes = (
            lambda rows: rows[1].update(ky="1"),
            lambda rows: rows[1].update(ky="200"),
            lambda rows: rows[1].update(main=[1, 1, 2, 3, 4]),
            lambda rows: rows[1].update(date="01/01/2023"),
        )
        for change in changes:
            rows = copy.deepcopy(self.draws)
            change(rows)
            with self.subTest(change=change), self.assertRaises(ValueError):
                lab.evaluate_draws(self.GAME, rows, 1, 5, 5, registry=lab.FrozenRegistry())

    def test_changed_source_manifest_aborts_instead_of_returning_mixed_version(self):
        with mock.patch.object(lab, "_source_manifest", side_effect=({"source": "before"}, {"source": "after"})), \
                mock.patch.object(lab, "_production_prediction", side_effect=self._fast_web):
            with self.assertRaisesRegex(RuntimeError, "Mã nguồn thay đổi"):
                lab.evaluate_draws(self.GAME, self.draws, 1, 5, 5, registry=lab.FrozenRegistry())

    def test_changed_canonical_version_aborts_run(self):
        snapshot = {"draws": self.draws, "path": self.root / "canonical.csv", "version": (1, 2)}
        with mock.patch.object(lab.effect, "_snapshot", return_value=snapshot), \
                mock.patch.object(lab, "evaluate_draws", return_value={"ok": True}), \
                mock.patch.object(lab, "version", return_value=(2, 3)):
            with self.assertRaisesRegex(RuntimeError, "Canonical thay đổi"):
                lab.run(self.GAME, 1, 5, 5)

    def test_cli_has_single_json_failure_and_nonzero_status(self):
        output = io.StringIO()
        with mock.patch.object(lab, "run", side_effect=ValueError("fixture failure")), redirect_stdout(output):
            status = lab.main(["--action=run", "--game=LOTO_5_35"])
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(output.getvalue())["error"], "fixture failure")

    def test_power_jackpot_two_uses_purchased_six_numbers_in_lab_measurement(self):
        game = "LOTO_6_55"
        prefix = history(game, 60)
        actual = {"main": [1, 2, 3, 4, 5, 6], "special": 7}
        snapshot = lab._fold_snapshot(game, prefix, {"ky": "61"})
        payload = lab.effect._baseline(game, "random", 1, snapshot)
        payload["tickets"] = [{"main": [1, 2, 3, 4, 5, 7], "special": 8}]
        scored = lab._measure(game, payload, actual)
        self.assertEqual(scored["bestHits"], 5)
        self.assertEqual(scored["prizeHistogram"], {"POWER_JACKPOT_2": 1})
        self.assertTrue(scored["tickets"][0]["result"]["specialMatched"])

    def test_candidate_selection_uses_validation_hits_only_for_identical_brier(self):
        samples = {profile["id"]: [{"brierScore": 0.2, "meanHits": 1.0}] for profile in lab.PROFILES}
        samples["short_aggressive"] = [{"brierScore": 0.2, "meanHits": 2.0}]
        self.assertEqual(lab._choose_candidate(samples), "short_aggressive")
        samples["long_stable"] = [{"brierScore": 0.19, "meanHits": 0.0}]
        self.assertEqual(lab._choose_candidate(samples), "long_stable")

    def test_conclusion_requires_enough_test_pairs_and_both_controls(self):
        candidate = [{"meanHits": 2.0, "brierScore": 0.10, "logLoss": 0.3}] * 35
        controls = [{"meanHits": 1.0, "brierScore": 0.12, "logLoss": 0.4}] * 35
        grouped = {"test": {"short_stable": candidate, "random": controls, "web": controls}}
        conclusion = lab._conclusion("short_stable", grouped)
        self.assertEqual(conclusion["status"], "possible_improvement")
        grouped["test"]["web"] = candidate
        self.assertEqual(lab._conclusion("short_stable", grouped)["status"], "no_clear_advantage")
        grouped["test"] = {key: values[:10] for key, values in grouped["test"].items()}
        self.assertEqual(lab._conclusion("short_stable", grouped)["status"], "insufficient_evidence")


if __name__ == "__main__":
    unittest.main()
