"""Lightweight Keno polling must preserve history, clocks and concurrent writes."""
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from backend import keno_live_sync as sync
ORIGINAL_PAGE = sync._page


class KenoLiveSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.csv = Path(self.temp.name) / "keno.csv"
        self.meta = Path(self.temp.name) / "keno.meta.json"
        self.first = datetime(2035, 1, 1, 6, 8, tzinfo=sync.LOCAL_TZ)
        self.now = self.first + timedelta(minutes=25)
        self.results = [self.result(n) for n in range(1, 4)]
        self.rows = {r["ky"]: sync.live.keno_result_to_csv_row(r) for r in self.results}
        sync.live.write_keno_csv_rows(self.csv, self.rows, normalize_schedule=False)
        stack = self.enterContext(ExitStack())
        for name, path in [("get_canonical_csv_write_path", self.csv),
                           ("get_canonical_meta_read_path", self.meta),
                           ("get_canonical_meta_write_path", self.meta)]:
            stack.enter_context(mock.patch.object(sync.live.dp, name, return_value=path))
        self.page = stack.enter_context(mock.patch.object(sync, "_page", return_value=[self.result(4)]))
        stack.enter_context(mock.patch.object(sync.live, "create_session"))

    def result(self, identity):
        at = self.first + timedelta(minutes=8 * (identity - 1))
        return {"key": "KENO", "ky": str(identity), "date": at.strftime("%d/%m/%Y"),
                "time": at.strftime("%H:%M"), "main": list(range(1, 21)), "sourceUrl": sync.live.KENO_URL}

    def read(self):
        return sync.live.load_keno_csv_rows(self.csv, normalize_schedule=False)

    def test_appends_verified_result_without_repair_training_or_history_scan(self):
        original = dict(self.read())
        with mock.patch.object(sync.live, "sync_all_keno_type", side_effect=AssertionError("full crawl")), \
                mock.patch.object(sync.live, "normalize_keno_schedule_times", side_effect=AssertionError("history rewrite")), \
                mock.patch.object(sync.live, "retrain_gen_local_models", side_effect=AssertionError("model fitting")):
            result = sync.refresh(now=self.now)
        self.assertEqual((result["latestKy"], result["newRows"]), ("4", 1))
        for identity, row in original.items():
            self.assertEqual(row, self.read()[identity])
        self.page.assert_called_once()

    def test_same_result_does_not_rewrite_csv_or_metadata(self):
        sync.refresh(now=self.now)
        original_csv, original_meta = self.csv.read_bytes(), self.meta.read_bytes()
        with mock.patch.object(sync.live, "write_keno_csv_rows", side_effect=AssertionError("unnecessary write")):
            result = sync.refresh(now=self.now + timedelta(seconds=60))
        self.assertEqual(result["status"], "up_to_date")
        self.assertEqual(self.csv.read_bytes(), original_csv)
        self.assertEqual(self.meta.read_bytes(), original_meta)

    def test_future_invalid_numbers_and_wrong_schedule_do_not_change_data(self):
        original = self.csv.read_bytes()
        for bad in [self.result(5), {**self.result(4), "main": [1] * 20},
                    {**self.result(4), "time": "06:33"}, {**self.result(4), "time": "06:40"}]:
            with self.subTest(bad=bad), mock.patch.object(sync, "_page", return_value=[bad]):
                with self.assertRaises(ValueError):
                    sync.refresh(now=self.now)
                self.assertEqual(self.csv.read_bytes(), original)

    def test_conflicting_existing_draw_is_preserved(self):
        original = self.csv.read_bytes()
        self.page.return_value = [{**self.result(3), "main": list(range(2, 22))}, self.result(4)]
        with self.assertRaisesRegex(ValueError, "mâu thuẫn"):
            sync.refresh(now=self.now)
        self.assertEqual(self.csv.read_bytes(), original)

    def test_known_old_schedule_anomaly_is_not_corrected_by_polling(self):
        self.rows["2"]["Time"] = "06:32"
        sync.live.write_keno_csv_rows(self.csv, self.rows, normalize_schedule=False)
        sync.refresh(now=self.now)
        self.assertEqual(self.read()["2"]["Time"], "06:32")

    def test_concurrent_writer_is_reloaded_without_losing_its_row(self):
        original_writer = sync.live.write_keno_csv_rows
        calls = 0
        def raced(path, rows, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                fresh = self.read()
                fresh["4"] = sync.live.keno_result_to_csv_row(self.result(4))
                original_writer(path, fresh, normalize_schedule=False)
            return original_writer(path, rows, **kwargs)
        with mock.patch.object(sync.live, "write_keno_csv_rows", side_effect=raced):
            result = sync.refresh(now=self.now)
        self.assertEqual(result["status"], "up_to_date")
        self.assertEqual(set(self.read()), {"1", "2", "3", "4"})

    def test_missing_locked_target_gets_specific_query_before_new_cycle(self):
        self.page.side_effect = [[self.result(5)], [self.result(4)]]
        pending = [{"target_draw_id": "4", "deadline": (self.first + timedelta(minutes=24)).isoformat()}]
        result = sync.refresh(now=self.first + timedelta(minutes=33), pending=pending)
        self.assertEqual(result["newRows"], 2)
        self.assertEqual(self.page.call_count, 2)
        self.assertEqual(self.page.call_args.args[2], pending[0])

    def test_page_has_bounded_timeout_without_legacy_retries(self):
        with mock.patch.object(sync.live, "request_with_retry", return_value=mock.Mock(text="<html></html>")) as request:
            self.assertEqual(ORIGINAL_PAGE(mock.Mock(), self.now), [])
        self.assertEqual(request.call_args.kwargs["timeout"], (4, 12))
        self.assertEqual(request.call_args.kwargs["retry_count"], 0)
        self.assertEqual(request.call_args.kwargs["data"]["page"], "1")


if __name__ == "__main__":
    unittest.main()
