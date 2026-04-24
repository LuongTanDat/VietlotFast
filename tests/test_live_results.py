import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

import backend.live_results as lr


def make_keno_results(start_ky, count, draw_date):
    results = []
    for offset in range(count):
        total_minutes = 6 * 60 + offset * 8
        hour = total_minutes // 60
        minute = total_minutes % 60
        results.append({
            "key": "KENO",
            "label": "Keno",
            "ky": str(start_ky + offset),
            "date": draw_date,
            "time": f"{hour:02d}:{minute:02d}",
            "main": list(range(1, 21)),
            "special": None,
            "displayLines": [" ".join(f"{value:02d}" for value in range(1, 21))],
            "importable": True,
            "sourceUrl": lr.KENO_URL,
            "sourceDate": draw_date,
        })
    return results


def make_keno_rows(results):
    rows_by_ky = {}
    for result in results:
        row = lr.keno_result_to_csv_row(result)
        rows_by_ky[row["Ky"]] = row
    return rows_by_ky


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 4, 24, 12, 0, 0)
        if tz is not None:
            return value.astimezone(tz)
        return value


class LiveResultsTests(unittest.TestCase):
    def test_parse_cli_args_defaults_repair_recent_days_to_15(self):
        cli = lr.parse_cli_args(["--repair-canonical", "KENO"])

        self.assertTrue(cli["repairCanonical"])
        self.assertEqual(lr.REPAIR_DEFAULT_RECENT_DAYS, cli["recentLookbackDays"])
        self.assertEqual(["KENO"], cli["types"])

    def test_parse_cli_args_keeps_explicit_recent_days(self):
        cli = lr.parse_cli_args(["--repair-canonical", "--recent-days", "7", "live_history", "KENO", "today"])

        self.assertTrue(cli["repairCanonical"])
        self.assertEqual(7, cli["recentLookbackDays"])
        self.assertEqual("canonical_history", cli["mode"])

    def test_parse_cli_args_non_repair_keeps_recent_days_unset(self):
        cli = lr.parse_cli_args(["KENO"])

        self.assertFalse(cli["repairCanonical"])
        self.assertIsNone(cli["recentLookbackDays"])

    def test_recent_repair_window_starts_on_10_apr_2026_and_excludes_09_apr(self):
        today = date(2026, 4, 24)
        window_start = lr.get_recent_window_start_date(today, lr.REPAIR_DEFAULT_RECENT_DAYS)
        missing_dates = lr.collect_missing_dates_for_range(
            "KENO",
            {date(2026, 4, 10), date(2026, 4, 24)},
            window_start,
            today,
        )

        self.assertEqual(date(2026, 4, 10), window_start)
        self.assertNotIn(date(2026, 4, 9), missing_dates)

    def test_keno_timeout_errors_are_not_classified_as_outside_hours(self):
        timeout_message = lr.build_keno_manual_timeout_message(datetime(2026, 4, 24, 23, 0, 0))
        timeout_fields = lr.build_type_result_fields(
            "KENO",
            had_errors=True,
            errors=[{"type": "KENO", "message": timeout_message}],
            now_value=datetime(2026, 4, 24, 23, 0, 0),
        )
        outside_fields = lr.build_type_result_fields(
            "KENO",
            had_errors=True,
            errors=[{"type": "KENO", "message": lr.KENO_OUTSIDE_OPERATING_HOURS_MESSAGE}],
            now_value=datetime(2026, 4, 24, 23, 0, 0),
        )

        self.assertIn("300", timeout_message)
        self.assertEqual("failure", timeout_fields["resultCode"])
        self.assertEqual("outside_hours", outside_fields["resultCode"])

    def test_sync_all_keno_type_prioritizes_recent_gaps_and_fills_target_range(self):
        full_day_20 = make_keno_results(278125, 119, "20/04/2026")
        full_day_21 = make_keno_results(278244, 119, "21/04/2026")
        full_day_22 = make_keno_results(278363, 119, "22/04/2026")
        full_day_23 = make_keno_results(278482, 119, "23/04/2026")
        full_day_24 = make_keno_results(278601, 119, "24/04/2026")

        seed_rows = make_keno_rows(full_day_20[:112] + full_day_22[59:] + full_day_23 + full_day_24)
        fetched_dates = []
        written_rows = {}
        fetch_map = {
            date(2026, 4, 20): full_day_20,
            date(2026, 4, 21): full_day_21,
            date(2026, 4, 22): full_day_22,
            date(2026, 4, 23): full_day_23,
            date(2026, 4, 24): full_day_24,
        }

        def fake_fetch_keno_day_results(session, target_date, page_progress=None, deadline_monotonic=None, timeout_state=None):
            fetched_dates.append(target_date)
            return list(fetch_map.get(target_date, []))

        def fake_write_canonical_rows(type_key, rows_by_ky, today):
            written_rows.clear()
            written_rows.update(rows_by_ky)
            return {
                "all": Path("keno_all_day.csv"),
                "today": Path("keno_hom_nay.csv"),
            }, lr.count_rows_for_date(rows_by_ky, today), len(rows_by_ky)

        with mock.patch.object(lr, "datetime", FixedDateTime), \
             mock.patch.object(lr, "read_canonical_meta", return_value={}), \
             mock.patch.object(lr, "load_seed_rows", return_value=(seed_rows, ["keno_all_day.csv"])), \
             mock.patch.object(lr, "fetch_latest_keno_page", return_value=("24/04/2026", [])), \
             mock.patch.object(lr, "fetch_keno_day_results", side_effect=fake_fetch_keno_day_results), \
             mock.patch.object(lr, "write_canonical_rows", side_effect=fake_write_canonical_rows), \
             mock.patch.object(lr, "write_canonical_meta", return_value=None):
            result = lr.sync_all_keno_type(object(), allow_bootstrap=False, recent_lookback_days=None)

        self.assertEqual(
            [
                date(2026, 4, 22),
                date(2026, 4, 21),
                date(2026, 4, 20),
                date(2026, 4, 24),
                date(2026, 4, 23),
            ],
            fetched_dates,
        )
        self.assertEqual([], [ky for ky in range(278237, 278422) if str(ky) not in written_rows])
        self.assertEqual(119, sum(1 for row in written_rows.values() if row.get("Ngay") == "20/04/2026"))
        self.assertEqual(119, sum(1 for row in written_rows.values() if row.get("Ngay") == "21/04/2026"))
        self.assertEqual(119, sum(1 for row in written_rows.values() if row.get("Ngay") == "22/04/2026"))
        self.assertGreater(result["repairedKyGaps"], 0)
        self.assertEqual([], result["errors"])


if __name__ == "__main__":
    unittest.main()
