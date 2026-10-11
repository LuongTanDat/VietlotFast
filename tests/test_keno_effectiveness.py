"""Keno draw identity, atomic lock, late-result scoring and bounded reports."""
import csv
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from ai import keno_effectiveness as keno, prediction_effectiveness as pe
from ai import prediction_ledger as ledger
from ai.prizes import classify_ticket


class KenoEffectivenessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "private.db"
        self.csv = Path(self.temp.name) / "keno.csv"
        first = datetime(2035, 1, 1, 6, 8, tzinfo=pe.LOCAL_TZ)
        self.draws = [self.row(n + 1, first + timedelta(minutes=8 * n)) for n in range(25)]
        self.write()
        patch = mock.patch.object(keno.dp, "get_canonical_csv_read_path", return_value=self.csv)
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(pe, "_now", return_value=keno.draw_at(self.draws[-1]) + timedelta(minutes=1))
        self.now = patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(keno, "_web_predictions", side_effect=self.web)
        self.web_mock = patch.start()
        self.addCleanup(patch.stop)

    @staticmethod
    def row(identity, at):
        return {"ky": str(identity), "date": at.strftime("%d/%m/%Y"), "time": at.strftime("%H:%M"),
                "main": sorted(((identity + n * 3) % 80) + 1 for n in range(20)), "special": None}

    def write(self):
        with self.csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=("Kỳ", "Ngày", "Giờ", "Bộ Số"))
            writer.writeheader()
            for row in self.draws:
                writer.writerow({"Kỳ": row["ky"], "Ngày": row["date"], "Giờ": row["time"], "Bộ Số": ",".join(map(str, row["main"]))})

    def web(self, snapshot, count, db_path=None):
        probabilities = keno._probabilities(snapshot)["bayesian"]
        return {level: {**keno._baseline("bayesian", level, count, snapshot, probabilities), "engine": "classic"} for level in keno.LEVELS}

    def counts(self):
        with closing(keno._connect(self.db)) as connection:
            return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("keno_effectiveness_cycles", "keno_effectiveness_predictions", "prediction_runs", "prediction_scores", "keno_effectiveness_metrics")}

    def add_actual(self, arrival_delay=1):
        at = keno.next_draw_at(keno.draw_at(self.draws[-1]))
        self.draws.append(self.row(int(self.draws[-1]["ky"]) + 1, at))
        self.write()
        self.now.return_value = at + timedelta(minutes=arrival_delay)

    def test_defaults_and_report_do_not_generate_history(self):
        result = pe.report("KENO", db_path=self.db, level=4)
        self.assertFalse(result["settings"]["enabled"])
        self.assertEqual(result["counts"]["total"], 0)
        self.assertEqual(len(result["levels"]), 10)
        self.assertEqual(result["level"], 4)
        self.web_mock.assert_not_called()

    def test_all_120_tickets_lock_once_and_level_changes_cannot_reroll(self):
        first = pe.cycle("KENO", self.db)
        self.assertEqual(first["totalTickets"], 120)
        self.assertEqual(self.counts(), {"keno_effectiveness_cycles": 1, "keno_effectiveness_predictions": 40,
                                         "prediction_runs": 40, "prediction_scores": 0, "keno_effectiveness_metrics": 0})
        pe.configure("KENO", True, 5, "admin_fixture", self.db)
        second = pe.cycle("KENO", self.db)
        self.assertEqual(first["cycleId"], second["cycleId"])
        for level in (1, 5, 10):
            cycle = pe.report("KENO", db_path=self.db, level=level)["cycles"][0]
            self.assertEqual(cycle["config"]["ticketCount"], 3)
            self.assertEqual(sum(len(m["tickets"]) for m in cycle["methods"].values()), 12)
            self.assertTrue(all(len(t["main"]) == level for m in cycle["methods"].values() for t in m["tickets"]))
        self.assertEqual(self.web_mock.call_count, 1)

    def test_max_budget_caps_each_level_and_scores_all_unique_tickets(self):
        pe.configure("KENO", True, 10000, "admin_fixture", self.db)
        first = keno.cycle(self.db)
        self.assertEqual(first["ticketCountsByLevel"], {str(level): 80 if level == 1 else 3160 if level == 2 else 10000 for level in keno.LEVELS})
        self.assertEqual(first["totalTickets"], 332960)
        with closing(keno._connect(self.db)) as connection:
            rows = connection.execute('SELECT payload_json,payload_checksum FROM prediction_runs').fetchall()
            self.assertEqual(len(rows), 40)
            for row in rows:
                payload = json.loads(row['payload_json'])
                self.assertEqual(ledger.payload_checksum(payload), row['payload_checksum'])
                self.assertEqual(len(payload['tickets']), len({tuple(ticket['main']) for ticket in payload['tickets']}))
        pe.configure('KENO', False, 1, 'admin_fixture', self.db)
        same = keno.cycle(self.db)
        self.assertEqual(same['cycleId'], first['cycleId'])
        self.add_actual()
        self.assertEqual(keno.score_cycles(self.db)["scored"], [first["targetDrawId"]])
        with closing(keno._connect(self.db)) as connection:
            self.assertEqual(connection.execute('SELECT SUM(ticket_count) FROM keno_effectiveness_metrics').fetchone()[0], 332960)
        for level, total in ((1, 80), (2, 3160), (10, 10000)):
            report = keno.report(level, db_path=self.db)
            entry = report['cycles'][0]['methods']['web']
            self.assertEqual(len(entry['tickets']), 20)
            self.assertEqual(entry['ticketPagination']['total'], total)
            self.assertEqual(entry['prizeStatistics']['ticketCount'], total)
            last = pe.ticket_page('KENO', entry['predictionId'], entry['ticketPagination']['totalPages'], self.db)
            self.assertEqual(last['ticketResults'][-1]['ticketIndex'], total)
        self.assertEqual(keno.cycle(self.db, force=False)['status'], 'disabled')

    def test_late_result_scores_same_target_and_next_deadline_not_arrival(self):
        first = keno.cycle(self.db)
        deadline = datetime.fromisoformat(first["deadline"])
        self.now.return_value = deadline + timedelta(minutes=1)
        self.assertEqual(keno.score_cycles(self.db)["scored"], [])
        self.assertEqual(keno.report(db_path=self.db)["cycles"][0]["status"], "locked")
        self.add_actual(arrival_delay=1)
        result = keno.score_cycles(self.db)
        self.assertEqual(result["scored"], [first["targetDrawId"]])
        self.assertEqual(self.counts()["prediction_scores"], 40)
        self.assertEqual(self.counts()["keno_effectiveness_metrics"], 40)
        second = keno.cycle(self.db)
        self.assertEqual(datetime.fromisoformat(second["deadline"]), deadline + timedelta(minutes=8))
        self.assertEqual(int(second["targetDrawId"]), int(first["targetDrawId"]) + 1)
        self.assertEqual(keno.score_cycles(self.db)["scored"], [])

    def test_source_late_past_deadline_never_skips_or_backfills(self):
        first = keno.cycle(self.db)
        self.now.return_value = datetime.fromisoformat(first["deadline"]) + timedelta(minutes=9)
        self.assertEqual(keno.cycle(self.db)["status"], "already_locked")
        self.add_actual(arrival_delay=9)
        self.assertEqual(keno.score_cycles(self.db)["scored"], [first["targetDrawId"]])
        with self.assertRaisesRegex(ValueError, "đến giờ quay"):
            keno.cycle(self.db)
        self.assertEqual(self.counts()["keno_effectiveness_cycles"], 1)
        pe.configure("KENO", True, 3, "fixture", self.db)
        result = keno.tick(self.db)
        self.assertFalse(result["ok"])
        self.assertIn("đến giờ quay", keno.report(db_path=self.db)["automation"]["lastError"])

    def test_overnight_target_is_next_day_0608_same_id_plus_one(self):
        self.draws = [self.row(700, datetime(2035, 1, 1, 21, 52, tzinfo=pe.LOCAL_TZ))]
        self.write()
        self.now.return_value = keno.draw_at(self.draws[-1]) + timedelta(minutes=1)
        result = keno.cycle(self.db)
        self.assertEqual(result["targetDrawId"], "701")
        self.assertEqual(result["deadline"], "2035-01-02T06:08:00+07:00")

    def test_source_jump_cannot_leave_locked_target_missing_and_lock_farther_draw(self):
        first = keno.cycle(self.db)
        skipped_at = datetime.fromisoformat(first["deadline"]) + timedelta(minutes=8)
        self.draws.append(self.row(27, skipped_at))  # Provider supplied 27 but not locked draw 26.
        self.write()
        self.now.return_value = skipped_at + timedelta(minutes=1)
        self.assertEqual(keno.score_cycles(self.db)["scored"], [])
        with self.assertRaisesRegex(ValueError, "thiếu kết quả đúng mã/giờ"):
            keno.cycle(self.db)
        self.assertEqual(self.counts()["keno_effectiveness_cycles"], 1)

    def test_wrong_time_same_id_is_not_scored(self):
        keno.cycle(self.db)
        self.add_actual()
        self.draws[-1]["time"] = "09:36"
        self.write()
        self.now.return_value += timedelta(minutes=10)
        result = keno.score_cycles(self.db)
        self.assertFalse(result["ok"])
        self.assertIn("không khớp", result["errors"][0]["error"])
        self.assertEqual(self.counts()["prediction_scores"], 0)

    def test_disabled_tracking_still_scores_pending(self):
        keno.cycle(self.db)
        pe.configure("KENO", False, 3, "fixture", self.db)
        self.add_actual()
        result = keno.tick(self.db)
        self.assertEqual(result["scoring"]["scored"], ["26"])
        self.assertEqual(result["cycle"]["status"], "disabled")
        self.assertEqual(self.counts()["keno_effectiveness_cycles"], 1)

    def test_source_refresh_then_score_then_lock_happens_in_one_tick(self):
        pe.configure("KENO", True, 3, "fixture", self.db)
        first = keno.cycle(self.db)
        self.now.return_value = datetime.fromisoformat(first["deadline"]) + timedelta(minutes=1)
        def refreshed(_):
            self.add_actual(arrival_delay=1)
            return {"status": "updated", "latestKy": first["targetDrawId"]}
        with mock.patch.object(keno, "_sync_source", side_effect=refreshed) as source:
            result = keno.tick(self.db, sync_source=True)
        source.assert_called_once_with(self.db)
        self.assertTrue(result["ok"])
        self.assertEqual(result["scoring"]["scored"], ["26"])
        self.assertEqual(result["cycle"]["targetDrawId"], "27")
        self.assertEqual(result["cycle"]["deadline"], (datetime.fromisoformat(first["deadline"]) + timedelta(minutes=8)).isoformat())
        self.assertEqual(self.counts()["keno_effectiveness_cycles"], 2)
        self.assertEqual(self.counts()["prediction_scores"], 40)

    def test_disabled_and_explicit_fixture_ticks_do_not_fetch_source(self):
        with mock.patch.object(keno, "_sync_source", side_effect=AssertionError("unexpected network")):
            self.assertEqual(keno.tick(self.db, sync_source=True)["cycle"]["status"], "disabled")
            pe.configure("KENO", True, 3, "fixture", self.db)
            self.assertTrue(keno.tick(self.db)["ok"])

    def test_source_failure_does_not_block_available_results_or_valid_next_lock(self):
        pe.configure("KENO", True, 3, "fixture", self.db)
        keno.cycle(self.db)
        self.add_actual()
        with mock.patch.object(keno, "_sync_source", return_value={"status": "error", "error": "source offline"}):
            result = keno.tick(self.db, sync_source=True)
        self.assertEqual(result["scoring"]["scored"], ["26"])
        self.assertEqual(result["cycle"]["targetDrawId"], "27")
        self.assertEqual(result["sourceSync"]["error"], "source offline")

    def test_disabled_pending_cycle_still_fetches_result_without_locking_new_tickets(self):
        keno.cycle(self.db)
        def refreshed(_):
            self.add_actual()
            return {"status": "updated"}
        with mock.patch.object(keno, "_sync_source", side_effect=refreshed) as source:
            result = keno.tick(self.db, sync_source=True)
        source.assert_called_once_with(self.db)
        self.assertEqual(result["scoring"]["scored"], ["26"])
        self.assertEqual(result["cycle"]["status"], "disabled")
        self.assertEqual(self.counts()["keno_effectiveness_cycles"], 1)

    def test_failed_source_poll_retries_after_interval_and_keeps_last_success(self):
        with mock.patch("backend.keno_live_sync.refresh", side_effect=[{"status": "updated", "latestKy": "25"}, TimeoutError("source offline"), {"status": "up_to_date", "latestKy": "25"}]) as source:
            first = keno._sync_source(self.db)
            self.now.return_value += timedelta(seconds=60)
            failed = keno._sync_source(self.db)
            self.assertEqual(failed["lastSuccess"], first["lastSuccess"])
            self.assertEqual(failed["status"], "error")
            self.now.return_value += timedelta(seconds=60)
            recovered = keno._sync_source(self.db)
            self.assertEqual(recovered["error"], "")
            self.assertGreater(recovered["lastSuccess"], first["lastSuccess"])
            self.assertEqual(source.call_count, 3)

    def test_poll_state_throttles_requests_and_skips_overnight(self):
        with mock.patch("backend.keno_live_sync.refresh", return_value={"status": "updated", "latestKy": "25"}) as refresh:
            first = keno._sync_source(self.db)
            self.now.return_value += timedelta(seconds=30)
            self.assertEqual(keno._sync_source(self.db), first)
            refresh.assert_called_once()
            self.now.return_value = datetime(2035, 1, 1, 23, 0, tzinfo=pe.LOCAL_TZ)
            self.assertEqual(keno._sync_source(self.db)["status"], "outside_hours")
            refresh.assert_called_once()
        self.assertEqual(keno.report(db_path=self.db)["automation"]["sourceSync"]["latestKy"], "25")

    def test_partial_lock_failure_rolls_back_all_40_groups(self):
        original = ledger.lock_prediction
        calls = 0
        def failing(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 13:
                raise RuntimeError("fixture write failure")
            return original(*args, **kwargs)
        with mock.patch.object(ledger, "lock_prediction", side_effect=failing):
            with self.assertRaisesRegex(RuntimeError, "write failure"):
                keno.cycle(self.db)
        self.assertTrue(all(value == 0 for value in self.counts().values()))

    def test_bad_level_payload_rejects_entire_cycle(self):
        def invalid(snapshot, count, db_path):
            result = self.web(snapshot, count, db_path)
            result[6]["tickets"][0]["main"] = [1, 1, 2, 3, 4, 5]
            return result
        self.web_mock.side_effect = invalid
        with self.assertRaisesRegex(ValueError, "không hợp lệ"):
            keno.cycle(self.db)
        self.assertEqual(self.counts()["prediction_runs"], 0)

    def test_configuration_change_during_generation_rejects_cycle(self):
        def changed(snapshot, count, db_path):
            result = self.web(snapshot, count, db_path)
            pe.configure("KENO", True, 4, "fixture", self.db)
            return result
        self.web_mock.side_effect = changed
        with self.assertRaisesRegex(RuntimeError, "Cấu hình"):
            keno.cycle(self.db)
        self.assertEqual(self.counts()["prediction_runs"], 0)

    def test_manifest_change_rejects_cycle(self):
        with mock.patch.object(keno, "_manifest", side_effect=[{"version": 1}, {"version": 2}]):
            with self.assertRaisesRegex(RuntimeError, "thay đổi"):
                keno.cycle(self.db)
        self.assertEqual(self.counts()["prediction_runs"], 0)

    def test_checksum_corruption_rolls_back_whole_scoring_cycle(self):
        keno.cycle(self.db)
        with closing(keno._connect(self.db)) as connection:
            connection.execute("DROP TRIGGER prediction_runs_locked_payload_immutable")
            connection.execute("UPDATE prediction_runs SET payload_checksum='bad' WHERE prediction_id=(SELECT prediction_id FROM keno_effectiveness_predictions WHERE level=6 AND method='ewma')")
        self.add_actual()
        self.assertFalse(keno.score_cycles(self.db)["ok"])
        self.assertEqual(self.counts()["prediction_scores"], 0)

    def test_scored_report_reads_saved_result_and_same_level_baseline(self):
        keno.cycle(self.db)
        self.add_actual()
        keno.score_cycles(self.db)
        with mock.patch.object(keno.ml_pipeline, "load_actual_draws", side_effect=AssertionError("report reads current CSV")):
            result = keno.report(level=2, db_path=self.db)
        self.assertEqual(result["counts"]["scored"], 1)
        self.assertEqual(result["cycles"][0]["actualMain"], self.draws[-1]["main"])
        for method in result["methods"]:
            self.assertEqual(method["expectedRandomHits"], .5)
            self.assertEqual(method["dayCount"], 1)
            self.assertIsNone(method["ci95"])
        self.assertTrue(all(m["decision"] in ("baseline", "insufficient_evidence") for m in result["methods"]))

    def test_pagination_reads_only_selected_level_and_does_not_limit_aggregates(self):
        for _ in range(22):
            keno.cycle(self.db)
            self.add_actual()
        self.assertEqual(len(keno.score_cycles(self.db)["scored"]), 22)
        first = keno.report(level=3, page=1, db_path=self.db)
        second = keno.report(level=3, page=2, db_path=self.db)
        third = keno.report(level=3, page=3, db_path=self.db)
        self.assertEqual(len(first["cycles"]), 10)
        self.assertEqual(len(second["cycles"]), 10)
        self.assertEqual(len(third["cycles"]), 2)
        self.assertEqual(first["pagination"]["total"], 22)
        self.assertEqual(first["pagination"]["pageSize"], 10)
        self.assertEqual(first["pagination"]["totalPages"], 3)
        self.assertEqual(first["counts"]["scored"], 22)
        self.assertTrue(all(m["sampleCount"] == 22 for m in first["methods"]))
        self.assertEqual(first["methods"], second["methods"])
        self.assertEqual(first["methods"], third["methods"])
        ids = [cycle["targetDrawId"] for page in (first, second, third) for cycle in page["cycles"]]
        self.assertEqual(len(set(ids)), 22)
        self.assertEqual(ids, sorted(ids, key=int, reverse=True))
        self.assertTrue(all(len(t["main"]) == 3 for c in second["cycles"] for m in c["methods"].values() for t in m["tickets"]))
        self.assertEqual(keno.report(page=99, db_path=self.db)["pagination"]["page"], 3)

    def test_report_validates_level_and_page(self):
        for level, page in ((0, 1), (11, 1), (1.5, 1), (True, 1), (1, 0), (1, -2), (1, 1000001)):
            with self.assertRaises(ValueError):
                keno.report(level, page, self.db)

    def test_latest_schedule_mismatch_blocks_lock_but_old_anomaly_is_reported(self):
        self.draws[3]["time"] = "06:40"  # Valid slot, inconsistent old ID/time.
        self.write()
        result = keno.cycle(self.db)
        self.assertEqual(result["status"], "locked")
        self.assertGreater(keno.report(db_path=self.db)["historyScheduleMismatchCount"], 0)
        self.add_actual()
        self.draws[-1]["time"] = "09:36"
        self.write()
        self.now.return_value += timedelta(minutes=10)
        with self.assertRaisesRegex(ValueError, "mới nhất"):
            keno.cycle(self.db)

    def test_daily_bootstrap_does_not_treat_intraday_draws_as_independent_days(self):
        samples = [{"day": "2035-01-01", "mean_hits": 1, "winning_rate": .1,
                    "full_match_rate": 0, "brier": .2, "log_loss": .6}] * 400
        pairs = [{"day": "2035-01-01", "delta": .5}] * 400
        result = keno._summary("web", samples, pairs, 4)
        self.assertEqual(result["dayCount"], 1)
        self.assertEqual(result["decision"], "insufficient_evidence")
        self.assertIsNone(result["ci95"])
        samples = [{**samples[0], "day": f"2035-01-{n % 7 + 1:02d}"} for n in range(400)]
        pairs = [{"day": row["day"], "delta": .5} for row in samples]
        result = keno._summary("web", samples, pairs, 4)
        self.assertEqual(result["decision"], "possible_improvement")
        self.assertEqual(result["ci95"], {"lower": .5, "upper": .5})

    def test_zero_hit_prizes_are_separate_from_full_match(self):
        actual = {"main": list(range(1, 21))}
        for level in range(1, 11):
            zero = classify_ticket("KENO", {"main": list(range(61, 61 + level))}, actual)
            self.assertEqual(zero["isWinning"], level >= 8)
            full = classify_ticket("KENO", {"main": list(range(1, level + 1))}, actual)
            self.assertTrue(full["isWinning"])
            self.assertEqual(full["mainHits"], level)
        self.assertFalse(classify_ticket("KENO", {"main": [1, 2, 3, 4, 61, 62, 63, 64, 65, 66]}, actual)["isWinning"])

    def test_shared_classic_evaluation_matches_all_ten_original_calls(self):
        from ai.predictors import ai_predict as predictor
        items = [{"numbers": row["main"], "weekday": 0} for row in self.draws]
        strategies = predictor.MAIN_STRATEGIES
        shared = keno._multi_level_evaluation(predictor, items, 80, strategies, 10, 10, 0)
        for level in keno.LEVELS:
            expected = predictor.evaluate_strategies(items, level, 80, strategies, 10, 10, 0)
            self.assertEqual(shared[level], expected)


if __name__ == "__main__":
    unittest.main()
