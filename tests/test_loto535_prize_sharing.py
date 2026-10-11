"""Verify sharing belongs to the preceding draw and survives separate live updates."""
import copy
import csv
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import backend.live_results as lr
from tests.test_prize_history import draw


def loto(ky, pool, count=None, date="01/10/2026", time="21:00"):
    result = draw("LOTO_5_35", str(ky))
    result.update(date=date, time=time, specialPrize=pool)
    if count is not None:
        result.update(prizeHit="ĐB" if count else "", prizeHitKnown=True,
                      prizeWinnerCounts={"specialPrize": count})
    return result


class Loto535PrizeSharingTests(unittest.TestCase):
    def test_pool_drop_marks_previous_draw_only_and_is_idempotent(self):
        rows = {r["ky"]: lr.result_to_csv_row(r) for r in
                [loto(15, 12000000000, 0), loto(16, 6000000000, 0, "02/10/2026", "13:00")]}
        before = copy.deepcopy(rows)
        self.assertEqual(["15"], lr.refresh_loto535_prize_sharing(rows))
        self.assertEqual("Chia Giải", rows["15"]["PrizeHit"])
        self.assertEqual("", rows["16"]["PrizeHit"])
        for ky in rows:
            self.assertEqual({k: v for k, v in before[ky].items() if k != "PrizeHit"},
                             {k: v for k, v in rows[ky].items() if k != "PrizeHit"})
        self.assertEqual([], lr.refresh_loto535_prize_sharing(rows))

    def test_one_or_multiple_winners_take_precedence_over_sharing(self):
        for count in (1, 2, 10):
            rows = {r["ky"]: lr.result_to_csv_row(r) for r in
                    [loto(15, 12000000000, count), loto(16, 6000000000, 0, "02/10/2026", "13:00")]}
            lr.refresh_loto535_prize_sharing(rows)
            self.assertEqual("ĐB", rows["15"]["PrizeHit"])

    def test_unknown_winners_are_not_zero_and_zero_without_drop_is_blank(self):
        for count in (None, 0):
            for pool in (6000000000, 12000000000, 13000000000, None):
                with self.subTest(count=count, next_pool=pool):
                    rows = {r["ky"]: lr.result_to_csv_row(r) for r in
                            [loto(15, 12000000000, count), loto(16, pool, 0, "02/10/2026", "13:00")]}
                    lr.refresh_loto535_prize_sharing(rows)
                    expected = "Chia Giải" if count == 0 and pool == 6000000000 else ""
                    self.assertEqual(expected, rows["15"]["PrizeHit"])

    def test_gaps_missing_pool_and_wrong_time_order_do_not_imply_sharing(self):
        for following in [loto(17, 6000000000, 0, "02/10/2026", "13:00"),
                          loto(16, 6000000000, 0, "01/10/2026", "13:00"),
                          loto(16, 6000000000, 0, "02/10/2026", "bad")]:
            rows = {r["ky"]: lr.result_to_csv_row(r) for r in [loto(15, 12000000000, 0), following]}
            lr.refresh_loto535_prize_sharing(rows)
            self.assertEqual("", rows["15"]["PrizeHit"])
        rows["15"]["SpecialPrize"] = ""
        self.assertEqual([], lr.refresh_loto535_prize_sharing(rows))

    def test_corrected_pool_or_winner_count_replaces_obsolete_sharing(self):
        rows = {r["ky"]: lr.result_to_csv_row(r) for r in
                [loto(15, 12000000000, 0), loto(16, 6000000000, 0, "02/10/2026", "13:00")]}
        lr.refresh_loto535_prize_sharing(rows)
        lr.merge_result_rows(rows, [loto(16, 13000000000, 0, "02/10/2026", "13:00")])
        lr.refresh_loto535_prize_sharing(rows)
        self.assertEqual("", rows["15"]["PrizeHit"])
        rows["16"]["SpecialPrize"] = "6000000000"
        lr.refresh_loto535_prize_sharing(rows)
        lr.merge_result_rows(rows, [loto(15, 12000000000, 2)])
        lr.refresh_loto535_prize_sharing(rows)
        self.assertEqual("ĐB", rows["15"]["PrizeHit"])

    def test_fallback_preserves_counts_but_corrected_identity_invalidates_them(self):
        row = lr.result_to_csv_row(loto(15, 12000000000, 0))
        rows = {"15": row}
        lr.merge_result_rows(rows, [loto(15, None)])
        self.assertEqual(0, rows["15"][lr.SPECIAL_WINNER_COUNT_FIELD])
        self.assertEqual("12000000000", rows["15"]["SpecialPrize"])
        corrected = loto(15, 12000000000)
        corrected["special"] = 11
        lr.merge_result_rows(rows, [corrected])
        self.assertNotIn(lr.SPECIAL_WINNER_COUNT_FIELD, rows["15"])

    def test_metadata_evidence_is_bound_to_draw_identity(self):
        original = lr.result_to_csv_row(loto(15, 12000000000, 0))
        meta = {"prizeSharing": lr.build_loto535_prize_sharing_meta({"15": original})}
        disk_row = {k: v for k, v in original.items() if k != lr.SPECIAL_WINNER_COUNT_FIELD}
        rows = {"15": disk_row}
        lr.restore_loto535_winner_evidence(rows, meta)
        self.assertEqual(0, disk_row.pop(lr.SPECIAL_WINNER_COUNT_FIELD))
        disk_row["Special"] = "11"
        lr.restore_loto535_winner_evidence(rows, meta)
        self.assertNotIn(lr.SPECIAL_WINNER_COUNT_FIELD, disk_row)

    def test_live_updates_survive_disk_reload_and_mark_prior_draw(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as patches:
            canonical = Path(folder) / "loto_5_35_all_day.csv"
            metadata = canonical.with_suffix(".meta.json")
            for name in ("get_canonical_csv_read_path", "get_canonical_csv_write_path"):
                patches.enter_context(mock.patch.object(lr.dp, name, return_value=canonical))
            for name in ("get_canonical_meta_read_path", "get_canonical_meta_write_path"):
                patches.enter_context(mock.patch.object(lr.dp, name, return_value=metadata))
            lr.sync_result_to_canonical_csv(loto(15, 12000000000, 0))
            self.assertEqual("", lr.load_csv_rows(canonical)["15"]["PrizeHit"])
            # This call reloads the first draw from CSV and its verified count from metadata.
            lr.sync_result_to_canonical_csv(loto(16, 6000000000, 0, "02/10/2026", "13:00"))
            rows = lr.load_csv_rows(canonical)
            self.assertEqual("Chia Giải", rows["15"]["PrizeHit"])
            self.assertEqual("", rows["16"]["PrizeHit"])
            lr.sync_result_to_canonical_csv(loto(15, None))
            self.assertEqual("Chia Giải", lr.load_csv_rows(canonical)["15"]["PrizeHit"])
            # Re-fetching a known zero must also retain a valid sharing classification.
            lr.sync_result_to_canonical_csv(loto(15, 12000000000, 0))
            self.assertEqual("Chia Giải", lr.load_csv_rows(canonical)["15"]["PrizeHit"])
            self.assertEqual(["15"], lr.read_canonical_meta("LOTO_5_35")["prizeSharing"]["sharedDraws"])
            with canonical.open(encoding="utf-8", newline="") as stream:
                self.assertEqual(lr.get_csv_header("LOTO_5_35"), next(csv.reader(stream)))

    def test_sharing_label_is_allowed_for_loto_only(self):
        self.assertTrue(lr.valid_prize_hit("LOTO_5_35", "Chia Giải"))
        for key in ("LOTO_6_45", "LOTO_6_55", "KENO", "MAX_3D", "MAX_3D_PRO"):
            self.assertFalse(lr.valid_prize_hit(key, "Chia Giải"))


if __name__ == "__main__":
    unittest.main()
