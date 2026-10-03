import csv
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import backend.live_results as lr
from scripts.update_prize_history import apply_prizes


def draw(key="LOTO_6_55", ky="1405", amount=True):
    cfg = lr.LIVE_TYPES[key]
    balls = list(range(1, cfg.main_count + 1)) + ([10] if cfg.has_special else [])
    result = lr.build_numeric_result(cfg, ky, "01/10/2026", "", balls, "https://example.com/")
    if amount:
        values = {"SpecialPrize": 7911320000, "Jackpot": 178900548500,
                  "Jackpot1": 106521287250, "Jackpot2": 3739088100}
        result.update({lr.PRIZE_RESULT_KEYS[f]: values[f] for f in lr.PRIZE_FIELDS_BY_TYPE[key]})
    return result


class PrizeHistoryTests(unittest.TestCase):
    def test_history_and_canonical_live_payloads_preserve_money(self):
        for key, fields in lr.PRIZE_FIELDS_BY_TYPE.items():
            with self.subTest(key=key):
                result = draw(key)
                item = lr.csv_row_to_history_item(lr.result_to_csv_row(result))
                live = lr.history_item_to_live_result(key, item)
                for field in fields:
                    name = lr.PRIZE_RESULT_KEYS[field]
                    self.assertEqual(result[name], item[name])
                    self.assertEqual(result[name], live[name])
                    self.assertIsInstance(item[name], int)
                self.assertNotIn("jackpot", lr.csv_row_to_history_item({"Jackpot": ""}))
                self.assertNotIn("jackpot", lr.csv_row_to_history_item({"Jackpot": "0"}))

    def test_pool_is_not_divided_per_winner(self):
        lines = ["Giá trị Jackpot 1", "106,521,287,250", "Giá trị Jackpot 2", "3,739,088,100",
                 "Giải", "Trùng khớp", "Số lượng", "Giá trị", "Jackpot 2", "2", "1,869,544,050"]
        self.assertEqual({"jackpot1": 106521287250, "jackpot2": 3739088100},
                         lr.parse_numeric_prizes(lr.LIVE_TYPES["LOTO_6_55"], lines))
        self.assertEqual({}, lr.parse_numeric_prizes(lr.LIVE_TYPES["LOTO_6_55"], lines[8:]))
        self.assertEqual({"jackpot": 14327867000}, lr.parse_numeric_prizes(
            lr.LIVE_TYPES["LOTO_6_45"], ["Giá trị Jackpot: 14.327.867.000 đồng"]))

    def test_two_loto_draws_keep_separate_prizes(self):
        lines = []
        for ky, time, amount in [(922, "21:00", "7,749,247,500"), (921, "13:00", "7.500.000.000")]:
            lines.extend(["Kết quả Lotto 5/35", f"Kết quả QSMT kỳ #{ky} ngày 02/10/2026 - Lúc {time}",
                          "01", "02", "03", "04", "05", "06", "Giá trị Độc Đắc", amount])
        results = lr.parse_history_results(lr.LIVE_TYPES["LOTO_5_35"], lines, "source",
                                          lr.parse_csv_date("02/10/2026"))
        self.assertEqual([("922", "21:00", 7749247500), ("921", "13:00", 7500000000)],
                         [(r["ky"], r["time"], r["specialPrize"]) for r in results])

    def test_csv_roundtrip_and_fallback_preserve_prizes(self):
        with tempfile.TemporaryDirectory() as temp:
            for key, fields in lr.PRIZE_FIELDS_BY_TYPE.items():
                with self.subTest(key=key):
                    result = draw(key)
                    path = Path(temp) / f"{lr.CANONICAL_OUTPUT_STEMS[key]}_all_day.csv"
                    rows = {result["ky"]: lr.result_to_csv_row(result)}
                    lr.write_csv_rows(path, rows)
                    with path.open(encoding="utf-8", newline="") as stream:
                        self.assertEqual(lr.CSV_HEADER + [lr.PRIZE_CSV_HEADERS[f] for f in fields],
                                         next(csv.reader(stream)))
                    restored, info = lr.load_csv_rows(path, return_info=True)
                    self.assertFalse(info["sanitized"])
                    self.assertEqual(rows, restored)
                    self.assertEqual((0, 0), lr.merge_result_rows(restored, [draw(key, amount=False)]))
                    self.assertEqual(rows, restored)
            path = Path(temp) / "max_3d_all_day.csv"
            lr.write_csv_rows(path, {"1": {"Ky": "1", "Label": "Max 3D"}})
            with path.open(encoding="utf-8", newline="") as stream:
                self.assertEqual(lr.CSV_HEADER, next(csv.reader(stream)))

    def test_backfill_changes_only_money_and_rejects_wrong_draw(self):
        result = draw()
        original = lr.result_to_csv_row(draw(amount=False))
        rows = {result["ky"]: dict(original)}
        self.assertEqual(2, apply_prizes("LOTO_6_55", rows, [result]))
        self.assertEqual({f: original[f] for f in lr.CSV_FIELDS},
                         {f: rows[result["ky"]][f] for f in lr.CSV_FIELDS})
        result["main"] = [11, 12, 13, 14, 15, 16]
        with self.assertRaisesRegex(ValueError, "Draw mismatch"):
            apply_prizes("LOTO_6_55", rows, [result])

    def test_live_enrichment_checks_draw_identity(self):
        base, source = draw(amount=False), draw()
        with mock.patch.object(lr, "fetch_latest_vietlott_result", return_value=base), \
             mock.patch.object(lr, "fetch_history_results_for_date", return_value=[source]):
            result = lr.fetch_live_result(object(), {}, "LOTO_6_55")
        self.assertEqual(3739088100, result["jackpot2"])
        base, source = draw(amount=False), draw(ky="1404")
        with mock.patch.object(lr, "fetch_latest_vietlott_result", return_value=base), \
             mock.patch.object(lr, "fetch_history_results_for_date", return_value=[source]):
            self.assertNotIn("jackpot2", lr.fetch_live_result(object(), {}, "LOTO_6_55"))

    def test_metadata_marks_new_draw_without_amount_incomplete(self):
        rows = {"1405": lr.result_to_csv_row(draw())}
        self.assertTrue(lr.build_prize_amount_meta("LOTO_6_55", rows)["complete"])
        rows["1406"] = lr.result_to_csv_row(draw(ky="1406", amount=False))
        meta = lr.build_prize_amount_meta("LOTO_6_55", rows)
        self.assertFalse(meta["complete"])
        self.assertEqual((2, 1, ["1406"]), (meta["totalRows"], meta["completeRows"], meta["missingDraws"]))
        previous = {"sourceOverrides": {"1405": "https://alternate.example/result"}}
        self.assertEqual(previous["sourceOverrides"],
                         lr.build_prize_amount_meta("LOTO_6_55", rows, previous)["sourceOverrides"])

    def test_corrected_draw_does_not_reuse_old_amounts(self):
        result = draw(amount=False)
        rows = {result["ky"]: lr.result_to_csv_row(draw())}
        result["special"] = 11
        lr.merge_result_rows(rows, [result])
        self.assertEqual("", rows[result["ky"]]["Jackpot2"])

    def test_live_results_remain_available_if_prize_source_is_offline(self):
        base = draw(amount=False)
        with mock.patch.object(lr, "fetch_latest_vietlott_result", return_value=base), \
             mock.patch.object(lr, "fetch_history_results_for_date", side_effect=lr.requests.ConnectionError):
            self.assertEqual(base, lr.fetch_live_result(object(), {}, "LOTO_6_55"))


if __name__ == "__main__":
    unittest.main()
