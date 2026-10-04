import unittest

import backend.live_results as lr
from scripts.clean_related_csv import clean_snapshot, clean_scoring, SCORING_HEADER


class RelatedCsvCleaningTests(unittest.TestCase):
    def test_snapshot_recovers_source_and_prize_only_for_matching_draw(self):
        result = lr.build_numeric_result(lr.LIVE_TYPES["LOTO_5_35"], "1", "29/06/2025",
                                         "13:00", [1, 2, 3, 4, 5, 6], "https://example.com/draw")
        result["specialPrize"] = 6000000000
        result["sourceDate"] = result["date"]
        source = lr.result_to_csv_row(result)
        original = dict(zip(lr.CSV_HEADER, [source[f] for f in lr.CSV_FIELDS]))
        original["Ngày cập nhật"] = ""
        original["Link cập nhật"] = "https://www"
        headers, rows, info = clean_snapshot("LOTO_5_35", lr.CSV_HEADER, [original], {"1": source})
        self.assertEqual("6000000000", rows[0]["Giải Đặc biệt (VNĐ)"])
        self.assertEqual(source["SourceUrl"], rows[0]["Link cập nhật"])
        self.assertEqual(1, info["drawIdentityVerified"])
        self.assertEqual(0, clean_snapshot("LOTO_5_35", headers, rows, {"1": source})[2]["changedCells"])
        original["Bộ Số"] = "11,12,13,14,15"
        with self.assertRaisesRegex(ValueError, "contradicts canonical"):
            clean_snapshot("LOTO_5_35", lr.CSV_HEADER, [original], {"1": source})

    def test_snapshot_does_not_overwrite_conflicting_prize(self):
        result = lr.build_numeric_result(lr.LIVE_TYPES["LOTO_6_45"], "1", "01/10/2026",
                                         "", [1, 2, 3, 4, 5, 6], "https://example.com/draw")
        result["jackpot"] = 178900548500
        result["sourceDate"] = result["date"]
        source = lr.result_to_csv_row(result)
        headers = lr.CSV_HEADER + ["Jackpot (VNĐ)"]
        row = dict(zip(lr.CSV_HEADER, [source[f] for f in lr.CSV_FIELDS]))
        row["Jackpot (VNĐ)"] = "12000000000"
        with self.assertRaisesRegex(ValueError, "prize contradicts"):
            clean_snapshot("LOTO_6_45", headers, [row], {"1": source})

    def test_scoring_checks_universe_ranks_and_nonfinite_values(self):
        rows = [dict(zip(SCORING_HEADER, [str(number), str(number), "10", "1", "0",
                    "0.5", "0.5", "0.5", "0.5", str(1 - number / 20)])) for number in range(1, 13)]
        self.assertEqual(12, len(clean_scoring("loto_5_35_special", SCORING_HEADER, rows)[1]))
        self.assertEqual(1, clean_scoring("loto_5_35_special", SCORING_HEADER, rows + [dict(rows[0])])[2]["duplicateRowsRemoved"])
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            clean_scoring("loto_5_35_special", SCORING_HEADER, rows[:-1])
        rows[0]["Score_i"] = "nan"
        with self.assertRaisesRegex(ValueError, "Invalid scoring value"):
            clean_scoring("loto_5_35_special", SCORING_HEADER, rows)


if __name__ == "__main__":
    unittest.main()
