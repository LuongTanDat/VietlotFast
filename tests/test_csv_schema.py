"""Check compact CSVs against their actual consumers and legacy imports."""
import csv
import tempfile
import unittest
from pathlib import Path

import backend.live_results as lr
from scripts.clean_canonical_data import normalize_row


HEADERS = {
    "LOTO_5_35": ["Kỳ", "Thứ", "Ngày", "Giờ", "Bộ Số", "ĐB", "Link cập nhật", "Ngày cập nhật", "Giải Đặc biệt (VNĐ)"],
    "LOTO_6_45": ["Kỳ", "Thứ", "Ngày", "Giờ", "Bộ Số", "Link cập nhật", "Ngày cập nhật", "Jackpot (VNĐ)"],
    "LOTO_6_55": ["Kỳ", "Thứ", "Ngày", "Giờ", "Bộ Số", "ĐB", "Link cập nhật", "Ngày cập nhật", "Jackpot 1 (VNĐ)", "Jackpot 2 (VNĐ)"],
    "MAX_3D": ["Kỳ", "Thứ", "Ngày", "Hiển thị", "Link cập nhật", "Ngày cập nhật"],
    "MAX_3D_PRO": ["Kỳ", "Thứ", "Ngày", "Hiển thị", "Link cập nhật", "Ngày cập nhật"],
}
for key in lr.PRIZE_FIELDS_BY_TYPE:
    HEADERS[key].append("Nổ")
MAX_DISPLAY = "Đặc biệt: 000 000 || Giải nhất: 001 002 003 004 || Giải nhì: 005 006 007 008 009 010 || Giải ba: 011 012 013 014 015 016 017 018"


def result_for(key):
    cfg = lr.LIVE_TYPES[key]
    if key.startswith("MAX"):
        return {"key": key, "label": cfg.label, "ky": "1", "date": "01/10/2026",
                "main": [], "displayLines": MAX_DISPLAY.split(" || "),
                "sourceUrl": "https://example.com/draw", "sourceDate": "01/10/2026"}
    balls = list(range(1, cfg.main_count + 1)) + ([10] if cfg.has_special else [])
    result = lr.build_numeric_result(cfg, "1", "01/10/2026", "13:00" if key == "LOTO_5_35" else "",
                                     balls, "https://example.com/draw")
    result["sourceDate"] = result["date"]
    for field in lr.PRIZE_FIELDS_BY_TYPE[key]:
        result[lr.PRIZE_RESULT_KEYS[field]] = 178900548500
    return result


class CompactCsvTests(unittest.TestCase):
    def test_all_games_roundtrip_without_reintroducing_removed_columns(self):
        with tempfile.TemporaryDirectory() as folder:
            for key, expected_headers in HEADERS.items():
                with self.subTest(key=key):
                    path = Path(folder) / f"{lr.CANONICAL_OUTPUT_STEMS[key]}_all_day.csv"
                    rows = {"1": lr.result_to_csv_row(result_for(key))}
                    lr.write_csv_rows(path, rows)
                    with path.open(encoding="utf-8", newline="") as stream:
                        reader = csv.DictReader(stream)
                        self.assertEqual(expected_headers, reader.fieldnames)
                        disk = next(reader)
                    self.assertNotIn("Loại", disk)
                    self.assertEqual(normalize_row(key, disk), lr.expand_csv_record(key, disk))
                    loaded, info = lr.load_csv_rows(path, return_info=True)
                    self.assertFalse(info["sanitized"])
                    self.assertEqual(rows, loaded)
                    self.assertEqual(lr.csv_row_to_history_item(rows["1"]), lr.csv_row_to_history_item(loaded["1"]))
                    before = path.read_bytes()
                    lr.write_csv_rows(path, loaded)
                    self.assertEqual(before, path.read_bytes())
                    if key.startswith("MAX"):
                        self.assertEqual(MAX_DISPLAY, disk["Hiển thị"])

    def test_snapshots_and_empty_files_infer_game_from_filename(self):
        with tempfile.TemporaryDirectory() as folder:
            for filename, key in [("loto_5_35.csv", "LOTO_5_35"), ("mega_6_45.csv", "LOTO_6_45"),
                                  ("power_6_55.csv", "LOTO_6_55"), ("max_3d_pro_today.csv", "MAX_3D_PRO")]:
                path = Path(folder) / filename
                lr.write_csv_rows(path, {})
                with path.open(encoding="utf-8", newline="") as stream:
                    self.assertEqual(HEADERS[key], next(csv.reader(stream)))

    def test_legacy_headers_still_read_complete_history(self):
        with tempfile.TemporaryDirectory() as folder:
            for key in HEADERS:
                path = Path(folder) / f"{lr.CANONICAL_OUTPUT_STEMS[key]}_all_day.csv"
                original = lr.result_to_csv_row(result_for(key))
                fields = lr.CSV_FIELDS + list(lr.PRIZE_FIELDS_BY_TYPE.get(key, ()))
                with path.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(lr.CSV_HEADER + [lr.PRIZE_CSV_HEADERS[f] for f in lr.PRIZE_FIELDS_BY_TYPE.get(key, ())])
                    writer.writerow([original[f] for f in fields])
                self.assertEqual({"1": original}, lr.load_csv_rows(path))


if __name__ == "__main__":
    unittest.main()
