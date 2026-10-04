import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import backend.live_results as lr
from scripts.clean_canonical_data import GROUPS, max_groups, normalize_row
import scripts.clean_canonical_data as cleaning


def max_row():
    row = dict.fromkeys(lr.CSV_HEADER, "")
    row.update({"Kỳ": "1139", "Thứ": "Thứ 4", "Ngày": "30/09/2026", "Loại": "Max_3D",
        "Link cập nhật": "https://www.minhchinh.com/xs-max-3d-ket-qua-max-3d-ngay-30-09-2026.html",
        "Ngày cập nhật": "30/09/2026",
        "Hiển thị": "Đặc biệt: 788 239 || Giải nhất: 193 864 436 607 || Giải nhì: 150 441 030 217 500 179 727 || Giải ba: 156 316 690 994 965 129 442 465 958"})
    return row


class DataCleaningTests(unittest.TestCase):
    def test_parser_ignores_winner_counts_before_and_after_balls(self):
        lines = ["Giải nhì", "210K: 150", "441", "030", "217", "500", "179", "727", "123"]
        self.assertEqual(["441", "030", "217", "500", "179", "727"],
                         lr.collect_prize_tokens(lines, 0, len(lines), 6))

    def test_parser_preserves_zeroes_and_repeated_winning_positions(self):
        self.assertEqual(["000", "000"], lr.collect_prize_tokens(
            ["Đặc biệt", "1Tr: 114", "000", "000", "999"], 0, 5, 2))

    def test_incomplete_prize_group_is_not_imported(self):
        lines = ["Kết quả Max 3D", "Kết quả QSMT kỳ #1139 ngày 30/09/2026",
                 "Đặc biệt", "001", "002", "Giải nhất", "003", "004", "005", "006",
                 "Giải nhì", "007", "008", "009", "010", "011", "012", "Giải ba", "013"]
        self.assertIsNone(lr.parse_max3d_section(lr.LIVE_TYPES["MAX_3D"], lines, "source"))

    def test_corrupted_result_requires_matching_source_evidence(self):
        row = max_row()
        with self.assertRaisesRegex(ValueError, "source verification required"):
            normalize_row("MAX_3D", row)
        correct = row["Hiển thị"].replace("Giải nhì: 150 ", "Giải nhì: ").replace("Giải ba: 156 ", "Giải ba: ")
        evidence = {"ky": row["Kỳ"], "date": row["Ngày"], "displayLines": correct.split(" || ")}
        cleaned = normalize_row("MAX_3D", row, evidence)
        self.assertEqual("Max 3D", cleaned["Loại"])
        self.assertEqual([count for _, count in GROUPS], [len(g) for g in max_groups(cleaned["Hiển thị"])])
        self.assertIn("030", cleaned["Hiển thị"])
        self.assertEqual(cleaned, normalize_row("MAX_3D", cleaned, evidence))
        evidence["displayLines"][0] = "Đặc biệt: 999 239"
        with self.assertRaisesRegex(ValueError, "contradicts"):
            normalize_row("MAX_3D", row, evidence)
        evidence["ky"] = "1138"
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            normalize_row("MAX_3D", row, evidence)

    def test_numeric_normalization_retains_prize_values(self):
        row = dict.fromkeys(lr.CSV_HEADER, "")
        row.update({"Kỳ": "#001", "Thứ": "wrong", "Ngày": "29-06-2025", "Giờ": "13:00",
            "Bộ Số": "01, 02,03,04,05", "ĐB": "09", "Loại": "5/35", "Hiển thị": "wrong",
            "Link cập nhật": "https://example.com/draw", "Ngày cập nhật": "29/06/2025",
            "Giải Đặc biệt (VNĐ)": "6,000,000,000"})
        result = normalize_row("LOTO_5_35", row)
        self.assertEqual("6000000000", result["Giải Đặc biệt (VNĐ)"])
        self.assertEqual("01 02 03 04 05 | ĐB 09", result["Hiển thị"])
        self.assertEqual("1", result["Kỳ"])
        row["Bộ Số"] = "1,1,3,4,5"
        with self.assertRaisesRegex(ValueError, "repeated"):
            normalize_row("LOTO_5_35", row)

    def test_legacy_max_labels_are_not_filtered_out(self):
        for label, key in [("Max_3D", "MAX_3D"), ("Max_3D_Pro", "MAX_3D_PRO"), ("3D Pro", "MAX_3D_PRO")]:
            self.assertTrue(lr.row_matches_type_key(key, {"Label": label}))
        self.assertFalse(lr.row_matches_type_key("MAX_3D", {"Label": "Max_3D_Pro"}))

    def test_unknown_time_conflict_blocks_writes_but_verified_source_is_flagged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths, original, metas = {}, {}, {}
            for key in lr.LIVE_TYPES:
                path = root / f"{key}.csv"
                paths[key] = path
                meta_path = root / f"{key}.json"
                meta_path.write_text("{}", encoding="utf-8")
                if key == "KENO":
                    headers = lr.KENO_CSV_HEADER
                    rows = [{"Kỳ": str(ky), "Thứ": "Thứ 4", "Ngày": "30/09/2026", "Giờ": time,
                             "Bộ Số": ",".join(map(str, range(1, 21))), "Lớn/-/Nhỏ": "Nhỏ",
                             "Chẵn/-/Lẻ": "-", "Link cập nhật": lr.KENO_URL}
                            for ky, time in [(2, "12:24"), (1, "12:40")]]
                elif key.startswith("MAX"):
                    headers = lr.CSV_HEADER
                    row = max_row()
                    row["Loại"] = lr.LIVE_TYPES[key].label
                    row["Hiển thị"] = row["Hiển thị"].replace("Giải nhì: 150 ", "Giải nhì: ").replace("Giải ba: 156 ", "Giải ba: ")
                    rows = [row]
                else:
                    headers = lr.CSV_HEADER + [lr.PRIZE_CSV_HEADERS[f] for f in lr.PRIZE_FIELDS_BY_TYPE[key]]
                    row = dict.fromkeys(headers, "")
                    row.update({"Kỳ": "1", "Thứ": "Thứ 4", "Ngày": "30/09/2026",
                                "Ngày cập nhật": "30/09/2026", "Link cập nhật": "https://example.com/draw",
                                "Loại": "5/35" if key == "LOTO_5_35" else lr.LIVE_TYPES[key].label,
                                "Bộ Số": ",".join(map(str, range(1, lr.LIVE_TYPES[key].main_count + 1))),
                                "ĐB": "9" if lr.LIVE_TYPES[key].has_special else "",
                                "Giờ": "13:00" if key == "LOTO_5_35" else ""})
                    for field in lr.PRIZE_FIELDS_BY_TYPE[key]:
                        row[lr.PRIZE_CSV_HEADERS[field]] = "6000000000"
                    rows = [normalize_row(key, row)]
                    if key == "LOTO_5_35":
                        rows[0]["Loại"] = "5/35"
                with path.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=headers)
                    writer.writeheader()
                    writer.writerows({name: row[name] for name in headers} for row in rows)
                original[key] = path.read_bytes()
            evidence = root / "evidence.json"
            evidence.write_text(json.dumps([{"key": "KENO", "ky": str(ky), "date": "30/09/2026",
                "time": time, "main": list(range(1, 21)), "sourceUrl": lr.KENO_URL}
                for ky, time in [(1, "12:40"), (2, "12:24")]]), encoding="utf-8")
            with mock.patch.object(cleaning, "ROOT", root), \
                 mock.patch.object(lr, "get_canonical_output_paths", side_effect=lambda key: {"all": paths[key]}), \
                 mock.patch.object(lr, "get_canonical_meta_path", side_effect=lambda key: root / f"{key}.json"), \
                 mock.patch.object(lr, "read_canonical_meta", side_effect=lambda key: {"type": key}), \
                 mock.patch.object(lr, "write_canonical_meta", side_effect=lambda key, meta: metas.update({key: meta})), \
                 contextlib.redirect_stdout(io.StringIO()):
                with mock.patch.object(cleaning.sys, "argv", ["clean", "--apply"]):
                    self.assertEqual(1, cleaning.main())
                self.assertTrue(all(paths[key].read_bytes() == raw for key, raw in original.items()))
                self.assertEqual({}, metas)
                with mock.patch.object(cleaning.sys, "argv", ["clean", "--apply", "--keno-evidence-file", str(evidence)]):
                    self.assertEqual(0, cleaning.main())
            self.assertEqual(original["KENO"], paths["KENO"].read_bytes())
            self.assertFalse(metas["KENO"]["dataQuality"]["valid"])
            self.assertTrue(metas["KENO"]["dataQuality"]["warningDetails"][0]["sourceConfirmed"])
            self.assertNotEqual(original["LOTO_5_35"], paths["LOTO_5_35"].read_bytes())


if __name__ == "__main__":
    unittest.main()
