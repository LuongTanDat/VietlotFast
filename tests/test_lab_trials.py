import copy
import csv
import random
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from ai import algorithm_lab as lab, lab_profiles, lab_store as store, lab_trials as trials
from ai import prediction_effectiveness as effect, prediction_ledger as ledger


class LabTrialsTests(unittest.TestCase):
    GAME = "LOTO_5_35"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db = self.root / "algorithm_lab.db"
        self.csv = self.root / "canonical.csv"
        rng = random.Random(112358)
        self.draws = [{"ky": str(index + 1), "date": (datetime(2024, 1, 1) + timedelta(days=index // 2)).strftime("%d/%m/%Y"),
                       "time": "13:00" if index % 2 == 0 else "21:00", "main": sorted(rng.sample(range(1, 36), 5)),
                       "special": rng.randrange(1, 13)} for index in range(70)]
        self.clock = effect._draw_at(self.draws[-1], self.GAME).astimezone(timezone.utc) + timedelta(hours=1)
        self._write()
        self.manifest = {"ai/lab_profiles.py": "a" * 64, "ai/algorithm_lab.py": "b" * 64}
        self.real_web = lab._production_prediction
        self.real_profile = lab_profiles.predict_profile
        for target, attribute, options in (
            (effect.dp, "get_canonical_csv_read_path", {"return_value": self.csv}),
            (effect, "_now", {"side_effect": lambda: self.clock}),
            (ledger, "now_iso", {"side_effect": lambda: self.clock.isoformat(timespec="seconds")}),
            (lab, "_source_manifest", {"return_value": self.manifest}),
            (lab, "_freeze_registry", {"return_value": lab.FrozenRegistry()}),
            (lab, "_production_prediction", {"side_effect": self._web}),
            (lab_profiles, "predict_profile", {"side_effect": self._profile}),
        ):
            patcher = mock.patch.object(target, attribute, **options)
            setattr(self, attribute + "_mock", patcher.start())
            self.addCleanup(patcher.stop)
        self._save()

    def _write(self):
        with self.csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=("Kỳ", "Ngày", "Giờ", "Bộ Số", "ĐB"))
            writer.writeheader()
            for row in self.draws:
                writer.writerow({"Kỳ": row["ky"], "Ngày": row["date"], "Giờ": row["time"], "Bộ Số": ",".join(map(str, row["main"])), "ĐB": row["special"]})

    def _save(self, owner="owner", run_id="run-1", profile_id="short_stable"):
        profile = lab_profiles.profile_definition(profile_id)
        self.report = {"ok": True, "status": "completed", "scope": "historical_diagnostic", "type": self.GAME,
                       "parameters": {"ticketCount": 3, "validationCount": 5, "testCount": 5},
                       "selection": {"candidateProfileId": profile_id, "candidateLabel": profile["label"],
                                     "profileDefinition": profile, "configHash": store._digest(profile), "validationOnly": True},
                       "provenance": {"sourceManifest": self.manifest, "sourceHash": store._digest(self.manifest),
                                      "dataHash": store._digest(self.draws), "latestDrawId": self.draws[-1]["ky"]}}
        store.save_run(owner, self.GAME, run_id, self.report, self.clock.isoformat(), self.clock.isoformat(), self.db)

    def _web(self, game, count, prefix, registry):
        snapshot = {"draws": prefix, "target": str(int(prefix[-1]["ky"]) + 1), "cutoff": prefix[-1]["ky"], "dataHash": store._digest(prefix)}
        return effect._baseline(game, "ewma", count, snapshot)

    def _profile(self, game, profile_id, prefix, count):
        snapshot = {"draws": prefix, "target": str(int(prefix[-1]["ky"]) + 1), "cutoff": prefix[-1]["ky"], "dataHash": store._digest(prefix)}
        return effect._baseline(game, "bayesian", count, snapshot)

    def _start(self):
        return trials.start("owner", self.GAME, "run-1", self.db)["tracking"]

    def _actual(self):
        snapshot = effect._snapshot(self.GAME)
        at = snapshot["deadline"]
        self.draws.append({"ky": snapshot["target"], "date": at.strftime("%d/%m/%Y"), "time": at.strftime("%H:%M"),
                           "main": [1, 2, 3, 4, 5], "special": 2})
        self._write()
        self.clock = at.astimezone(timezone.utc) + timedelta(hours=1)

    def _counts(self):
        with closing(store.readonly(self.db)) as connection:
            return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("lab_candidates", "lab_trial_cycles", "lab_trial_predictions", "lab_trial_scores")}

    def test_lock_three_equal_budget_predictions_atomically_without_production_ledger(self):
        with mock.patch.object(ledger, "connect", side_effect=AssertionError("production ledger must not be written")):
            tracking = self._start()
        self.assertEqual(tracking["counts"], {"locked": 1, "scored": 0, "total": 1})
        self.assertEqual(tracking["candidate"]["status"], "active")
        cycle = tracking["cycles"][0]
        self.assertEqual((cycle["cutoffDrawId"], cycle["targetDrawId"]), ("70", "71"))
        self.assertEqual(set(cycle["methods"]), {"candidate", "random", "web"})
        self.assertTrue(all(len(item["tickets"]) == 3 for item in cycle["methods"].values()))
        self.assertEqual(self._counts(), {"lab_candidates": 1, "lab_trial_cycles": 1, "lab_trial_predictions": 3, "lab_trial_scores": 0})
        with closing(store.readonly(self.db)) as connection:
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='prediction_runs'").fetchone())

    def test_real_candidate_and_web_pipeline_lock_future_cycle_without_model_or_ledger_writes(self):
        from ai.predictors import ai_predict as predictor
        self._production_prediction_mock.side_effect = self.real_web
        self.predict_profile_mock.side_effect = self.real_profile
        before = self.csv.read_bytes()
        with mock.patch.object(ledger, "connect", side_effect=AssertionError("production ledger write")), \
                mock.patch.object(predictor, "ensure_gen_local_model", side_effect=AssertionError("must not train")), \
                mock.patch.object(predictor.lr, "sync_requested_canonical_csvs", side_effect=AssertionError("must not sync")):
            tracking = self._start()
        self.assertEqual(tracking["counts"]["locked"], 1, tracking["candidate"]["lastError"])
        methods = tracking["cycles"][0]["methods"]
        self.assertEqual(methods["web"]["engine"], "classic")
        self.assertIn("short_stable", methods["candidate"]["modelId"])
        self.assertIsInstance(methods["candidate"]["seed"], int)
        self.assertEqual(self.csv.read_bytes(), before)

    def test_start_repeat_stop_resume_never_rerolls_same_target(self):
        first = self._start()
        repeated = self._start()
        self.assertEqual(first["candidate"]["id"], repeated["candidate"]["id"])
        trials.stop("owner", self.GAME, first["candidate"]["id"], self.db)
        resumed = self._start()
        self.assertEqual(first["cycles"], resumed["cycles"])
        self.assertEqual(self._production_prediction_mock.call_count, 1)
        self.assertEqual(self._counts()["lab_trial_predictions"], 3)

    def test_owner_and_game_isolation_for_report_start_and_stop(self):
        tracking = self._start()
        candidate_id = tracking["candidate"]["id"]
        self.assertIsNone(trials.report("other", self.GAME, candidate_id, self.db)["candidate"])
        self.assertIsNone(trials.report("owner", "LOTO_6_45", candidate_id, self.db)["candidate"])
        for owner, game in (("other", self.GAME), ("owner", "LOTO_6_45")):
            with self.assertRaisesRegex(ValueError, "Không tìm thấy"):
                trials.stop(owner, game, candidate_id, self.db)
            with self.assertRaisesRegex(ValueError, "Không tìm thấy"):
                trials.start(owner, game, "run-1", self.db)
        self.assertEqual(trials.report("owner", self.GAME, db_path=self.db)["candidate"]["status"], "active")

    def test_stopping_missing_candidate_does_not_create_database(self):
        missing = self.root / "missing.db"
        with self.assertRaisesRegex(ValueError, "Không tìm thấy"):
            trials.stop("owner", self.GAME, "missing-id", missing)
        self.assertFalse(missing.exists())
        with self.assertRaisesRegex(ValueError, "Mã ứng viên"):
            trials.stop("owner", self.GAME, "", self.db)

    def test_stopped_candidate_scores_pending_but_never_creates_next_cycle(self):
        tracking = self._start()
        candidate_id = tracking["candidate"]["id"]
        trials.stop("owner", self.GAME, candidate_id, self.db)
        self._actual()
        result = trials.tick(self.db)
        self.assertTrue(result["results"][0]["ok"])
        self.assertEqual(result["results"][0]["scoring"]["scored"], ["71"])
        self.assertEqual(result["results"][0]["cycle"]["status"], "stopped")
        tracking = trials.report("owner", self.GAME, candidate_id, self.db)
        self.assertEqual(tracking["counts"], {"locked": 0, "scored": 1, "total": 1})
        self.assertEqual(tracking["cycles"][0]["actualMain"], [1, 2, 3, 4, 5])
        self.assertTrue(all(len(method["ticketResults"]) == 3 for method in tracking["cycles"][0]["methods"].values()))
        for method in tracking["cycles"][0]["methods"].values():
            self.assertEqual([result["ticketIndex"] for result in method["ticketResults"]], [1, 2, 3])
            self.assertTrue(all(result["prizeLabel"] for result in method["ticketResults"]))
        self.assertEqual(trials.tick(self.db)["results"], [])
        self.assertEqual(self._counts()["lab_trial_scores"], 3)
        self.assertEqual(self._production_prediction_mock.call_count, 1)

    def test_valid_new_draw_append_allows_next_future_target_without_changing_selection(self):
        original = self._start()
        self._actual()
        result = trials.tick(self.db)
        self.assertTrue(result["results"][0]["ok"])
        tracking = trials.report("owner", self.GAME, db_path=self.db)
        self.assertEqual(tracking["counts"], {"locked": 1, "scored": 1, "total": 2})
        self.assertEqual(tracking["cycles"][0]["targetDrawId"], "72")
        self.assertEqual(tracking["candidate"]["configuration"], original["candidate"]["configuration"])

    def test_stale_deadline_enrolls_waiting_without_backfill(self):
        self.clock = effect._snapshot(self.GAME)["deadline"].astimezone(timezone.utc) + timedelta(hours=1)
        tracking = self._start()
        self.assertEqual(tracking["candidate"]["status"], "active")
        self.assertIn("giờ quay", tracking["candidate"]["lastError"])
        self.assertEqual(tracking["counts"]["total"], 0)
        self._production_prediction_mock.assert_not_called()
        self._actual()
        trials.tick(self.db)
        tracking = trials.report("owner", self.GAME, db_path=self.db)
        self.assertEqual([item["targetDrawId"] for item in tracking["cycles"]], ["72"])

    def test_source_or_old_history_changes_reject_start_and_new_future_cycle(self):
        old_source = dict(self.manifest)
        self._source_manifest_mock.return_value = {"ai/lab_profiles.py": "different"}
        with self.assertRaisesRegex(ValueError, "Mã thuật toán"):
            self._start()
        self.assertEqual(self._counts()["lab_candidates"], 0)
        self._source_manifest_mock.return_value = old_source
        self.draws[0]["special"] = self.draws[0]["special"] % 12 + 1
        self._write()
        with self.assertRaisesRegex(ValueError, "Lịch sử"):
            self._start()
        self.draws[0]["special"] = (self.draws[0]["special"] - 2) % 12 + 1
        self._write()
        self._start()
        self._actual()
        self._source_manifest_mock.return_value = {"ai/lab_profiles.py": "different"}
        result = trials.tick(self.db)
        self.assertFalse(result["results"][0]["ok"])
        self.assertEqual(self._counts()["lab_trial_cycles"], 1)
        self.assertEqual(self._counts()["lab_trial_scores"], 3)

    def test_deadline_crossing_during_generation_never_commits_partial_predictions(self):
        original = self._web
        def delayed(game, count, prefix, registry):
            payload = original(game, count, prefix, registry)
            self.clock = effect._snapshot(game)["deadline"].astimezone(timezone.utc)
            return payload
        self._production_prediction_mock.side_effect = delayed
        tracking = self._start()
        self.assertIn("giờ quay", tracking["candidate"]["lastError"])
        self.assertEqual(self._counts()["lab_trial_cycles"], 0)
        self.assertEqual(self._counts()["lab_trial_predictions"], 0)

    def test_stop_during_generation_cancels_transaction(self):
        original = self._web
        def stopping(game, count, prefix, registry):
            payload = original(game, count, prefix, registry)
            with closing(store.readonly(self.db)) as connection:
                candidate_id = connection.execute("SELECT candidate_id FROM lab_candidates").fetchone()[0]
            trials.stop("owner", game, candidate_id, self.db)
            return payload
        self._production_prediction_mock.side_effect = stopping
        tracking = self._start()
        self.assertEqual(tracking["candidate"]["status"], "stopped")
        self.assertEqual(self._counts()["lab_trial_predictions"], 0)

    def test_third_insert_failure_rolls_back_cycle_and_first_two_predictions(self):
        with closing(store.connect(self.db)) as connection:
            connection.executescript("""CREATE TRIGGER fail_third BEFORE INSERT ON lab_trial_predictions
                WHEN NEW.method='web' BEGIN SELECT RAISE(ABORT,'simulated third failure'); END;""")
        tracking = self._start()
        self.assertIn("simulated third", tracking["candidate"]["lastError"])
        self.assertEqual(self._counts()["lab_trial_cycles"], 0)
        self.assertEqual(self._counts()["lab_trial_predictions"], 0)

    def test_canonical_change_during_generation_cancels_all_predictions(self):
        original = self._web
        def changed(game, count, prefix, registry):
            payload = original(game, count, prefix, registry)
            self.draws[0]["special"] = self.draws[0]["special"] % 12 + 1
            self._write()
            return payload
        self._production_prediction_mock.side_effect = changed
        tracking = self._start()
        self.assertIn("Canonical thay đổi", tracking["candidate"]["lastError"])
        self.assertEqual(self._counts()["lab_trial_predictions"], 0)

    def test_wrong_result_deadline_and_corrupt_payload_are_never_scored(self):
        tracking = self._start()
        self._actual()
        self.draws[-1]["time"] = "21:00"
        self._write()
        self.clock += timedelta(hours=12)
        result = trials.score_candidate(tracking["candidate"]["id"], self.db)
        self.assertIn("Ngày/giờ", result["errors"][0]["error"])
        self.draws[-1]["time"] = "13:00"
        self._write()
        with closing(store.connect(self.db)) as connection:
            connection.execute("DROP TRIGGER lab_trial_prediction_immutable")
            connection.execute("UPDATE lab_trial_predictions SET payload_hash='corrupt' WHERE method='candidate'")
        result = trials.score_candidate(tracking["candidate"]["id"], self.db)
        self.assertIn("Checksum", result["errors"][0]["error"])
        self.assertEqual(self._counts()["lab_trial_scores"], 0)
        report = trials.report("owner", self.GAME, db_path=self.db)
        self.assertEqual(report["counts"]["scored"], 0)
        self.assertTrue(report["errors"])

    def test_switching_run_stops_old_candidate_and_preserves_its_pending_cycle(self):
        first = self._start()
        self._save(run_id="run-2", profile_id="long_stable")
        second = trials.start("owner", self.GAME, "run-2", self.db)["tracking"]
        self.assertNotEqual(first["candidate"]["id"], second["candidate"]["id"])
        self.assertEqual(trials.report("owner", self.GAME, first["candidate"]["id"], self.db)["candidate"]["status"], "stopped")
        self._actual()
        trials.tick(self.db)
        self.assertEqual(trials.report("owner", self.GAME, first["candidate"]["id"], self.db)["counts"]["scored"], 1)
        self.assertEqual(self._counts()["lab_trial_cycles"], 3)

    def test_new_active_candidate_limit_is_transactional_and_does_not_replace_others(self):
        for index in range(8):
            owner = f"owner-{index}"
            self._save(owner=owner, run_id=f"run-{index + 2}")
            trials.start(owner, self.GAME, f"run-{index + 2}", self.db)
        with self.assertRaisesRegex(ValueError, "8 ứng viên"):
            self._start()
        self.assertEqual(self._counts()["lab_candidates"], 8)
        with closing(store.readonly(self.db)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM lab_candidates WHERE status='active'").fetchone()[0], 8)

    def test_readiness_requires_paired_future_advantage_over_random_and_current_web(self):
        self.assertEqual(trials._conclusion({"sampleCount": 29})["status"], "insufficient_evidence")
        comparison = {"brierCi95": {"upper": -0.001}, "logLossDelta": -0.01, "ci95": {"lower": 0.01}}
        summary = {"sampleCount": 30, "comparisons": {"random": copy.deepcopy(comparison), "web": copy.deepcopy(comparison)}}
        self.assertEqual(trials._conclusion(summary)["status"], "possible_improvement")
        self.assertFalse(trials._conclusion(summary)["canApply"])
        summary["comparisons"]["web"]["brierCi95"]["upper"] = 0.002
        self.assertEqual(trials._conclusion(summary)["status"], "no_clear_advantage")

    def test_payloads_and_scores_are_immutable_and_journal_limit_does_not_limit_summary(self):
        self._start()
        self._actual()
        trials.tick(self.db)
        with closing(store.connect(self.db)) as connection:
            for statement in ("UPDATE lab_trial_cycles SET target_draw_id='99'", "UPDATE lab_trial_predictions SET payload_hash='x'",
                              "UPDATE lab_trial_scores SET score_hash='x'", "UPDATE lab_candidates SET profile_id='long_stable'"):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(statement)
        limited = trials.report("owner", self.GAME, db_path=self.db, limit=1)
        self.assertEqual(len(limited["cycles"]), 1)
        self.assertEqual(limited["counts"]["total"], 2)
        self.assertEqual(limited["methods"][0]["sampleCount"], 1)


if __name__ == "__main__":
    unittest.main()
