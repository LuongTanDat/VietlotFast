import csv
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from ai import prediction_effectiveness as effectiveness
from ai import prediction_ledger as ledger


class PredictionEffectivenessTests(unittest.TestCase):
    GAME = "LOTO_5_35"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.db = self.root / "ledger.db"
        self.csv = self.root / "canonical.csv"
        self.clock = datetime(2030, 1, 6, 7, tzinfo=timezone.utc)  # 14:00 UTC+7
        self.draws = [{"ky": str(n), "date": "06/01/2030", "time": "13:00",
                       "main": sorted({((n + j * 7) % 35) + 1 for j in range(5)}), "special": n % 12 + 1}
                      for n in range(1, 41)]
        self._write()
        self.path_patch = mock.patch.object(effectiveness.dp, "get_canonical_csv_read_path", return_value=self.csv)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.now_patch = mock.patch.object(effectiveness, "_now", return_value=self.clock)
        self.now = self.now_patch.start()
        self.addCleanup(self.now_patch.stop)
        self.web_patch = mock.patch.object(effectiveness, "_production_web_prediction", side_effect=self._web)
        self.web = self.web_patch.start()
        self.addCleanup(self.web_patch.stop)

    def _write(self):
        with self.csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=("Kỳ", "Ngày", "Giờ", "Bộ Số", "ĐB"))
            writer.writeheader()
            for row in self.draws:
                writer.writerow({"Kỳ": row["ky"], "Ngày": row["date"], "Giờ": row["time"],
                                 "Bộ Số": ",".join(map(str, row["main"])), "ĐB": row["special"]})

    def _web(self, game, count, snapshot):
        result = effectiveness._baseline(game, "bayesian", count, snapshot)
        result.update({"engine": "classic", "adaptiveCoverage": {"seed": 777},
                       "notes": ["Full pipeline test fixture"]})
        return result

    def _counts(self):
        with closing(effectiveness._connect(self.db)) as connection:
            return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("effectiveness_cycles", "effectiveness_predictions", "prediction_runs", "prediction_scores")}

    def _actual(self):
        self.draws.append({"ky": "41", "date": "06/01/2030", "time": "21:00",
                           "main": [1, 2, 3, 4, 5], "special": 2})
        self._write()
        self.now.return_value = datetime(2030, 1, 6, 15, tzinfo=timezone.utc)  # 22:00 UTC+7

    def test_disabled_defaults_report_never_generates_or_fabricates_history(self):
        initial = effectiveness.settings(self.GAME, self.db)
        self.assertFalse(initial["settings"]["enabled"])
        self.assertEqual(initial["settings"]["ticketCount"], 3)
        result = effectiveness.report(self.GAME, db_path=self.db)
        self.assertEqual(result["counts"], {"locked": 0, "scored": 0, "total": 0})
        self.assertEqual(result["cycles"], [])
        self.assertTrue(all(method["sampleCount"] == 0 and method["meanHits"] is None for method in result["methods"]))
        self.web.assert_not_called()
        self.assertEqual(self._counts()["prediction_runs"], 0)

    def test_configure_validates_settings_and_audits_actor(self):
        for enabled, count, actor in (("true", 3, "admin"), (True, 0, "admin"),
                                      (True, 11, "admin"), (True, 2.5, "admin"), (True, 3, "")):
            with self.assertRaises(ValueError):
                effectiveness.configure(self.GAME, enabled, count, actor, self.db)
        result = effectiveness.configure(self.GAME, True, 4, "owner", self.db)
        self.assertTrue(result["settings"]["enabled"])
        self.assertEqual(result["settings"]["updatedBy"], "owner")
        with closing(effectiveness._connect(self.db)) as connection:
            row = connection.execute("SELECT * FROM effectiveness_config_audit").fetchone()
            self.assertEqual(row["actor"], "owner")
            self.assertEqual(json.loads(row["settings_json"])["ticketCount"], 4)

    def test_four_predictions_lock_atomically_and_cannot_reroll_same_target(self):
        first = effectiveness.cycle(self.GAME, self.db)
        self.assertEqual(first["status"], "locked")
        self.assertEqual(self._counts(), {"effectiveness_cycles": 1, "effectiveness_predictions": 4,
                                         "prediction_runs": 4, "prediction_scores": 0})
        effectiveness.configure(self.GAME, True, 8, "admin", self.db)
        second = effectiveness.cycle(self.GAME, self.db)
        self.assertEqual(second["cycleId"], first["cycleId"])
        self.assertEqual(second["status"], "already_locked")
        self.assertEqual(self.web.call_count, 1)
        result = effectiveness.report(self.GAME, db_path=self.db)
        for method in result["cycles"][0]["methods"].values():
            self.assertEqual(len(method["tickets"]), 3)
        self.assertEqual(result["cycles"][0]["methods"]["web"]["seed"], 777)
        with closing(effectiveness._connect(self.db)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE effectiveness_cycles SET target_draw_id='99'")

    def test_failure_on_third_prediction_rolls_back_entire_cycle(self):
        real = ledger.lock_prediction
        calls = []

        def fail(payload, **kwargs):
            calls.append(payload)
            if len(calls) == 3:
                raise RuntimeError("simulated third-write failure")
            return real(payload, **kwargs)

        with mock.patch.object(ledger, "lock_prediction", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "third-write"):
                effectiveness.cycle(self.GAME, self.db)
        self.assertTrue(all(count == 0 for count in self._counts().values()))

    def test_past_target_rejected_without_skipping_or_generating(self):
        self.now.return_value = datetime(2030, 1, 6, 15, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "giờ quay"):
            effectiveness.cycle(self.GAME, self.db)
        self.web.assert_not_called()
        self.assertEqual(self._counts()["prediction_runs"], 0)

    def test_deadline_is_rechecked_after_expensive_generation(self):
        def delayed(game, count, snapshot):
            result = self._web(game, count, snapshot)
            self.now.return_value = datetime(2030, 1, 6, 15, tzinfo=timezone.utc)
            return result
        self.web.side_effect = delayed
        with self.assertRaisesRegex(ValueError, "giờ quay"):
            effectiveness.cycle(self.GAME, self.db)
        self.assertEqual(self._counts()["prediction_runs"], 0)

    def test_deadline_rechecked_after_database_transaction_lock(self):
        real = effectiveness._guard
        calls = []

        def expired_after_wait(snapshot):
            calls.append(snapshot)
            if len(calls) == 3:
                raise ValueError("database wait crossed deadline")
            return real(snapshot)

        with mock.patch.object(effectiveness, "_guard", side_effect=expired_after_wait):
            with self.assertRaisesRegex(ValueError, "database wait"):
                effectiveness.cycle(self.GAME, self.db)
        self.assertTrue(all(count == 0 for count in self._counts().values()))

    def test_changed_canonical_cancels_all_four_predictions(self):
        def changed(game, count, snapshot):
            result = self._web(game, count, snapshot)
            self.draws[0]["special"] = 12
            self._write()
            return result
        self.web.side_effect = changed
        with self.assertRaisesRegex(RuntimeError, "Canonical thay đổi"):
            effectiveness.cycle(self.GAME, self.db)
        self.assertTrue(all(count == 0 for count in self._counts().values()))

    def test_bad_web_budget_cutoff_or_probabilities_never_locks_partial_baselines(self):
        def variant(field, value):
            def produce(game, count, snapshot):
                result = self._web(game, count, snapshot)
                result[field] = value
                return result
            return produce
        for field, value in (("tickets", []), ("latestKy", "39"), ("nextKy", "40"),
                             ("probabilities", {"1": float("nan")}), ("ready", False)):
            self.web.side_effect = variant(field, value)
            with self.assertRaises(ValueError):
                effectiveness.cycle(self.GAME, self.db)
            self.assertEqual(self._counts()["prediction_runs"], 0)

    def test_fixed_baselines_are_seeded_history_only_and_equal_budget(self):
        snapshot = effectiveness._snapshot(self.GAME)
        for method in ("random", "bayesian", "ewma"):
            first = effectiveness._baseline(self.GAME, method, 10, snapshot)
            second = effectiveness._baseline(self.GAME, method, 10, snapshot)
            self.assertEqual(first, second)
            self.assertEqual(len(first["tickets"]), 10)
            self.assertEqual(len({tuple(ticket["main"]) for ticket in first["tickets"]}), 10)
            self.assertAlmostEqual(sum(first["probabilities"].values()), 5)
            self.assertTrue(all(1 <= ticket["special"] <= 12 for ticket in first["tickets"]))
            effectiveness._validate(first, self.GAME, 10, snapshot)
        cfg = effectiveness.ml_pipeline.game_config(self.GAME)
        prior = cfg["draw_size"] / cfg["universe_size"]
        payload = effectiveness._baseline(self.GAME, "bayesian", 3, snapshot)
        count_1 = sum(1 in row["main"] for row in snapshot["draws"])
        self.assertAlmostEqual(payload["probabilities"]["1"], (count_1 + 100 * prior) / 140)

    def test_scores_only_owned_cycles_and_keeps_personal_history_untouched(self):
        snapshot = effectiveness._snapshot(self.GAME)
        personal = effectiveness._baseline(self.GAME, "random", 1, snapshot)
        user_run = ledger.lock_prediction(personal, username="personal_user", db_path=self.db)
        effectiveness.cycle(self.GAME, self.db)
        self._actual()
        result = effectiveness.score_cycles(self.GAME, self.db)
        self.assertEqual(result["scored"], ["41"])
        self.assertEqual(self._counts()["prediction_scores"], 4)
        with closing(effectiveness._connect(self.db)) as connection:
            self.assertEqual(connection.execute("SELECT status FROM prediction_runs WHERE prediction_id=?",
                                                (user_run["prediction_id"],)).fetchone()[0], "locked")
        again = effectiveness.score_cycles(self.GAME, self.db)
        self.assertEqual(again["scored"], [])
        self.assertEqual(self._counts()["prediction_scores"], 4)
        result = effectiveness.report(self.GAME, db_path=self.db)
        self.assertEqual(result["counts"], {"locked": 0, "scored": 1, "total": 1})
        self.assertEqual(result["cycles"][0]["actualMain"], [1, 2, 3, 4, 5])
        for method in result["methods"]:
            self.assertEqual(method["sampleCount"], 1)
            self.assertIn(method["decision"], ("baseline", "insufficient_evidence"))
            self.assertTrue(0 <= method["rate3"] <= 1)
            self.assertEqual(sum(method["hitHistogram"].values()), 3)

    def test_complete_paired_cycle_required_and_v1_scores_excluded(self):
        effectiveness.cycle(self.GAME, self.db)
        self._actual()
        effectiveness.score_cycles(self.GAME, self.db)
        with closing(effectiveness._connect(self.db)) as connection:
            target = connection.execute("SELECT prediction_id FROM effectiveness_predictions WHERE method='ewma'").fetchone()[0]
            connection.execute("UPDATE prediction_scores SET scoring_version='ledger_scoring_v1' WHERE prediction_id=?", (target,))
        result = effectiveness.report(self.GAME, db_path=self.db)
        self.assertEqual(result["counts"]["scored"], 0)
        self.assertTrue(all(method["sampleCount"] == 0 for method in result["methods"]))

    def test_malformed_actual_or_wrong_slot_does_not_permanently_score_predictions(self):
        effectiveness.cycle(self.GAME, self.db)
        self._actual()
        for main, special, slot in (([1, 2, 3, 4], 2, "21:00"),
                                     ([1, 1, 2, 3, 4], 2, "21:00"),
                                     ([1, 2, 3, 4, 36], 2, "21:00"),
                                     ([1, 2, 3, 4, 5], 13, "21:00"),
                                     ([1, 2, 3, 4, 5], 2, "13:00")):
            self.draws[-1].update({"main": main, "special": special, "time": slot})
            self._write()
            result = effectiveness.score_cycles(self.GAME, self.db)
            self.assertFalse(result["ok"])
            self.assertEqual(self._counts()["prediction_scores"], 0)
            self.assertEqual(effectiveness.report(self.GAME, db_path=self.db)["counts"]["locked"], 1)

    def test_generic_ledger_scorer_cannot_bypass_atomic_effectiveness_scoring(self):
        snapshot = effectiveness._snapshot(self.GAME)
        personal = effectiveness._baseline(self.GAME, "random", 1, snapshot)
        user_run = ledger.lock_prediction(personal, username="personal_user", db_path=self.db)
        effectiveness.cycle(self.GAME, self.db)
        self._actual()
        actual = effectiveness.ml_pipeline.load_actual_draws(self.GAME)
        generic = ledger.score_pending_predictions(self.GAME, lambda game, target: actual.get(target),
                                                   35, 5, 5, db_path=self.db)
        self.assertEqual([run["prediction_id"] for run in generic["scored"]], [user_run["prediction_id"]])
        self.assertEqual(self._counts()["prediction_scores"], 1)
        with closing(effectiveness._connect(self.db)) as connection:
            statuses = connection.execute("SELECT status FROM prediction_runs WHERE username=?", (effectiveness.ACTOR,)).fetchall()
            self.assertEqual([row[0] for row in statuses], ["locked"] * 4)
        result = effectiveness.score_cycles(self.GAME, self.db)
        self.assertEqual(result["scored"], ["41"])
        self.assertEqual(self._counts()["prediction_scores"], 5)
        self.assertEqual(effectiveness.report(self.GAME, db_path=self.db)["counts"]["scored"], 1)

    def test_config_changes_visible_but_previous_locked_budget_preserved(self):
        effectiveness.cycle(self.GAME, self.db)
        self._actual()
        effectiveness.score_cycles(self.GAME, self.db)
        effectiveness.configure(self.GAME, True, 5, "admin", self.db)
        effectiveness.cycle(self.GAME, self.db)
        result = effectiveness.report(self.GAME, limit=1, db_path=self.db)
        self.assertEqual(result["counts"]["total"], 2)
        self.assertEqual(len(result["cycles"]), 1)
        self.assertTrue(result["mixedConfigurations"])
        self.assertEqual(result["configurationCount"], 2)
        self.assertEqual(result["cycles"][0]["config"]["ticketCount"], 5)
        self.assertEqual(result["methods"][0]["sampleCount"], 1)

    def test_paired_confidence_interval_uses_draw_means_and_conservative_decision(self):
        cfg = effectiveness.ml_pipeline.game_config(self.GAME)

        def sample(hits):
            return {"meanHits": hits, "brierScore": .12, "logLoss": .4, "rate3": .1, "rate4": 0,
                    "hitHistogram": {"0": 1, "1": 2}}

        positive = [sample(2)] * 30
        random = [sample(1)] * 30
        first = effectiveness._summary("web", positive, random, cfg)
        second = effectiveness._summary("web", positive, random, cfg)
        self.assertEqual(first, second)
        self.assertEqual(first["deltaVsRandom"], 1)
        self.assertEqual(first["ci95"], {"lower": 1, "upper": 1})
        self.assertEqual(first["decision"], "possible_improvement")
        self.assertEqual(effectiveness._summary("web", positive[:29], random[:29], cfg)["decision"], "insufficient_evidence")
        self.assertEqual(effectiveness._summary("web", random, positive, cfg)["decision"], "no_clear_advantage")

    def test_disabled_tick_still_scores_pending_predictions(self):
        effectiveness.cycle(self.GAME, self.db)
        self._actual()
        with mock.patch.object(effectiveness, "score_cycles", wraps=effectiveness.score_cycles) as score:
            result = effectiveness.tick(self.db)
        self.assertEqual(score.call_count, 3)
        self.assertTrue(result["ok"])
        self.assertEqual(self._counts()["prediction_scores"], 4)
        self.assertEqual(self.web.call_count, 1)
        self.assertEqual(effectiveness.report(self.GAME, db_path=self.db)["counts"]["scored"], 1)

    def test_cli_stdout_is_json_and_error_contains_message(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = effectiveness.main(["settings", self.GAME, "--db-path", str(self.db)])
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(output.getvalue())["settings"]["enabled"])
        self.now.return_value = datetime(2030, 1, 6, 15, tzinfo=timezone.utc)
        output = io.StringIO()
        with redirect_stdout(output):
            code = effectiveness.main(["cycle", self.GAME, "--db-path", str(self.db)])
        self.assertEqual(code, 1)
        result = json.loads(output.getvalue())
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], result["error"])

    def test_actual_web_pipeline_reads_pinned_history_without_canonical_rewrite(self):
        from ai.predictors import ai_predict as predictor
        snapshot = effectiveness._snapshot(self.GAME)
        # Retrieve the real implementation hidden by this test's web fixture.
        self.web_patch.stop()
        self.addCleanup(self.web_patch.start)
        summary = {"historyFile": self.csv.name, "historyCount": 40, "bootstrapComplete": True,
                   "latestKy": "40", "latestDate": "06/01/2030", "latestTime": "13:00", "errors": []}
        with mock.patch.object(predictor, "build_readonly_sync_summary", return_value=summary), \
                mock.patch.object(predictor.lr, "load_canonical_rows", side_effect=AssertionError("Canonical rewrite attempted")), \
                mock.patch("ai.controlled_models.champion_prediction", return_value=None):
            result = effectiveness._production_web_prediction(self.GAME, 3, snapshot)
        self.assertIn("adaptiveCoverage", result)
        self.assertEqual(result["engine"], "classic")
        self.assertEqual(result["latestKy"], "40")
        self.assertEqual(len(result["tickets"]), 3)
        effectiveness._validate(result, self.GAME, 3, snapshot)
        self.assertEqual(self._counts()["prediction_runs"], 0)

    def test_mega_and_power_real_web_pipeline_and_schedule_with_equal_budget(self):
        from ai.predictors import ai_predict as predictor
        self.web_patch.stop()
        self.addCleanup(self.web_patch.start)
        for game, size, latest_day, weekdays in (("LOTO_6_45", 45, "04/01/2030", {2, 4, 6}),
                                                ("LOTO_6_55", 55, "05/01/2030", {1, 3, 5})):
            self.draws = [{"ky": str(n), "date": latest_day, "time": "",
                           "main": sorted({((n + j * 7) % size) + 1 for j in range(6)}),
                           "special": next((value for value in range(1, 56) if value not in
                                            {((n + j * 7) % size) + 1 for j in range(6)}), None)
                           if game == "LOTO_6_55" else None}
                          for n in range(1, 41)]
            self._write()
            snapshot = effectiveness._snapshot(game)
            self.assertEqual(snapshot["deadline"].hour, 18)
            self.assertIn(snapshot["deadline"].weekday(), weekdays)
            self.assertGreater(snapshot["deadline"], self.clock)
            summary = {"historyFile": self.csv.name, "historyCount": 40, "bootstrapComplete": True,
                       "latestKy": "40", "latestDate": latest_day, "latestTime": "", "errors": []}
            with mock.patch.object(predictor, "build_readonly_sync_summary", return_value=summary), \
                    mock.patch.object(predictor.lr, "load_canonical_rows", side_effect=AssertionError("Canonical rewrite attempted")), \
                    mock.patch("ai.controlled_models.champion_prediction", return_value=None):
                result = effectiveness._production_web_prediction(game, 3, snapshot)
            self.assertIn("adaptiveCoverage", result)
            effectiveness._validate(result, game, 3, snapshot)
            for method in ("random", "bayesian", "ewma"):
                effectiveness._validate(effectiveness._baseline(game, method, 3, snapshot), game, 3, snapshot)
            with mock.patch.object(predictor, "build_readonly_sync_summary", return_value=summary), \
                    mock.patch("ai.controlled_models.champion_prediction", return_value=None):
                locked = effectiveness.cycle(game, self.db)
            self.assertEqual(locked["targetDrawId"], "41")
            self.assertEqual(effectiveness.report(game, db_path=self.db)["counts"]["locked"], 1)
        self.assertEqual(self._counts()["prediction_runs"], 8)


if __name__ == "__main__":
    unittest.main()
