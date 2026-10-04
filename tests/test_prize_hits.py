import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import backend.live_results as lr
from scripts.update_prize_hits import verify_result
from tests.test_prize_history import draw


class PrizeHitTests(unittest.TestCase):
    def test_counts_distinguish_power_jackpots_and_both(self):
        for first, second, expected in [(0, 0, ""), (1, 0, "Jackpot 1"), (0, 2, "Jackpot 2"), (1, 2, "Jackpot 1, 2")]:
            lines = ["Giá trị Jackpot 1", "100,000,000,000", "Giá trị Jackpot 2", "6,000,000,000",
                     "Giải", "Trùng khớp", "Số lượng", "Giá trị", "Jackpot 1", str(first), "100,000,000,000",
                     "Jackpot 2", str(second), "3,000,000,000"]
            parsed = lr.parse_numeric_prize_hits(lr.LIVE_TYPES["LOTO_6_55"], lines)
            self.assertTrue(parsed["prizeHitKnown"])
            self.assertEqual(expected, parsed["prizeHit"])
            self.assertEqual({"jackpot1": first, "jackpot2": second}, parsed["prizeWinnerCounts"])

    def test_loto_and_mega_only_mark_positive_winner_counts(self):
        for key, label, marker in [("LOTO_5_35", "Độc đắc", "ĐB"), ("LOTO_6_45", "Jackpot", "Jackpot")]:
            for count in (0, 1, 2):
                parsed = lr.parse_numeric_prize_hits(lr.LIVE_TYPES[key],
                    ["Giải", "Trùng khớp", "Số lượng", "Giá trị", label, str(count), "6,000,000,000"])
                self.assertEqual(marker if count else "", parsed["prizeHit"])

    def test_incomplete_counts_and_advertised_pools_do_not_imply_a_hit(self):
        cfg = lr.LIVE_TYPES["LOTO_6_55"]
        self.assertEqual({}, lr.parse_numeric_prize_hits(cfg, ["Giá trị Jackpot 1", "100,000,000,000"]))
        self.assertEqual({}, lr.parse_numeric_prize_hits(cfg,
            ["Giải", "Trùng khớp", "Số lượng", "Giá trị", "Jackpot 1", "0", "100,000,000,000",
             "Jackpot 2", "-", "6,000,000,000"]))

    def test_fallback_preserves_hit_and_confirmed_zero_can_clear_it(self):
        result = draw()
        result.update(prizeHit="Jackpot 2", prizeHitKnown=True)
        row = lr.result_to_csv_row(result)
        rows = {result["ky"]: row}
        fallback = draw()
        self.assertEqual((0, 0), lr.merge_result_rows(rows, [fallback]))
        self.assertEqual("Jackpot 2", rows[result["ky"]]["PrizeHit"])
        zero = copy.deepcopy(result)
        zero["prizeHit"] = ""
        self.assertEqual((0, 1), lr.merge_result_rows(rows, [zero]))
        self.assertEqual("", rows[result["ky"]]["PrizeHit"])

    def test_disk_api_and_source_verification_preserve_marker(self):
        result = draw()
        result.update(prizeHit="Jackpot 1, 2", prizeHitKnown=True, prizeWinnerCounts={"jackpot1": 1, "jackpot2": 2})
        row = lr.result_to_csv_row(result)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "power_6_55_all_day.csv"
            lr.write_csv_rows(path, {result["ky"]: row})
            restored = lr.load_csv_rows(path)[result["ky"]]
            self.assertEqual("Jackpot 1, 2", restored["PrizeHit"])
            self.assertEqual("Jackpot 1, 2", lr.csv_row_to_history_item(restored)["prizeHit"])
            self.assertEqual("Nổ", lr.get_csv_header("LOTO_6_55")[-1])
            self.assertEqual("Jackpot 1, 2", verify_result("LOTO_6_55", restored, result))
            result["main"] = [11, 12, 13, 14, 15, 16]
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                verify_result("LOTO_6_55", restored, result)

    def test_live_sync_does_not_erase_verified_hit_when_source_omits_counts(self):
        result = draw()
        previous = lr.result_to_csv_row(result)
        previous["PrizeHit"] = "Jackpot 2"
        paths = lr.get_canonical_output_paths("LOTO_6_55")
        with mock.patch.object(lr, "load_canonical_rows", return_value=({result["ky"]: previous}, {}, {})), \
             mock.patch.object(lr, "write_canonical_rows", return_value=(paths, 1, 1)) as writer, \
             mock.patch.object(lr, "write_canonical_meta"):
            lr.sync_result_to_canonical_csv(result)
            self.assertEqual("Jackpot 2", writer.call_args.args[1][result["ky"]]["PrizeHit"])

    def test_backfill_rejects_markers_that_contradict_winner_counts(self):
        result = draw()
        row = lr.result_to_csv_row(result)
        result.update(prizeHit="Jackpot 1", prizeHitKnown=True, prizeWinnerCounts={"jackpot1": 0, "jackpot2": 0})
        with self.assertRaisesRegex(ValueError, "contradicts source winner counts"):
            verify_result("LOTO_6_55", row, result)


if __name__ == "__main__":
    unittest.main()
