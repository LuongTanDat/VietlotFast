import json
import tempfile
import unittest
from pathlib import Path

from ai.analysis import analysis as an


SAMPLE_LOTO_535 = """Kỳ,Thứ,Ngày,Giờ,Bộ Số,ĐB,Hiển thị,Loại,Link cập nhật,Ngày cập nhật
5,Thứ 2,05/01/2026,21:00,"1,2,3,4,5",1,01 02 03 04 05 | ĐB 01,Loto_5/35,https://example.test,05/01/2026
4,Chủ Nhật,04/01/2026,21:00,"2,3,4,5,6",2,02 03 04 05 06 | ĐB 02,Loto_5/35,https://example.test,04/01/2026
3,Thứ 7,03/01/2026,21:00,"1,2,7,8,9",1,01 02 07 08 09 | ĐB 01,Loto_5/35,https://example.test,03/01/2026
2,Thứ 6,02/01/2026,21:00,"1,3,5,7,9",3,01 03 05 07 09 | ĐB 03,Loto_5/35,https://example.test,02/01/2026
1,Thứ 5,01/01/2026,21:00,"1,2,3,4,5",1,01 02 03 04 05 | ĐB 01,Loto_5/35,https://example.test,01/01/2026
"""


class AnalysisTests(unittest.TestCase):
    def write_csv(self, text=SAMPLE_LOTO_535):
        temp = tempfile.TemporaryDirectory()
        path = Path(temp.name) / "loto_5_35_all_day.csv"
        path.write_text(text, encoding="utf-8", newline="")
        self.addCleanup(temp.cleanup)
        return path

    def payload(self, mode="overview", **kwargs):
        return an.build_analysis_payload(
            kwargs.pop("type_key", "LOTO_5_35"),
            period=kwargs.pop("period", "all"),
            mode=mode,
            csv_path=self.write_csv(),
            **kwargs,
        )

    def test_load_csv_sample_no_error(self):
        draws, source = an.load_draws("LOTO_5_35", self.write_csv())

        self.assertEqual("loto_5_35_all_day.csv", source.name)
        self.assertEqual(5, len(draws))

    def test_parse_numbers(self):
        draws, _ = an.load_draws("LOTO_5_35", self.write_csv())

        self.assertEqual(["01", "02", "03", "04", "05"], draws[0]["numbers"])
        self.assertEqual("01", draws[0]["special"])

    def test_overview_returns_total_draws(self):
        payload = self.payload("overview")

        self.assertTrue(payload["ok"])
        self.assertEqual(5, payload["totalDraws"])
        self.assertIn("hotNumbers", payload["data"])

    def test_general_sum_mean_std(self):
        data = self.payload("general")["data"]

        self.assertEqual(15, data["sum"])
        self.assertEqual(3, data["mean"])
        self.assertGreater(data["standardDeviation"], 0)

    def test_ratios_even_odd_low_high(self):
        data = self.payload("ratios")["data"]

        self.assertEqual(2, data["evenCount"])
        self.assertEqual(3, data["oddCount"])
        self.assertEqual("2:3", data["evenOddRatio"])

    def test_consecutive_detects_pairs(self):
        data = self.payload("consecutive")["data"]

        self.assertIn(["01", "02"], data["consecutivePairs"])
        self.assertGreaterEqual(data["maxConsecutiveLength"], 5)

    def test_overdue_current_skip_max_skip_avg_gap(self):
        payload = self.payload("overdue", limit=35)
        item = next(row for row in payload["data"]["items"] if row["number"] == "06")

        self.assertEqual(1, item["currentSkip"])
        self.assertIn("maxSkip", item)
        self.assertIn("avgGap", item)

    def test_poisson_fallback_math(self):
        data = self.payload("poisson")["data"]

        self.assertGreater(data["lambda"], 0)
        self.assertIn("p0", data)
        self.assertIn("items", data)

    def test_knn_returns_top_k(self):
        data = self.payload("knn", k=2)["data"]

        self.assertEqual(2, len(data["neighbors"]))
        self.assertIn("Các kỳ này có cấu trúc gần giống", data["explanation"])

    def test_chain_lead_follow(self):
        data = self.payload("chain")["data"]

        self.assertTrue(data["topChains"])
        self.assertIn("probability", data["topChains"][0])

    def test_relationships_pair_co_occurrence(self):
        data = self.payload("relationships")["data"]

        pair = next(row for row in data["coOccurrencePairs"] if row["pair"] == "01-02")
        self.assertEqual(3, pair["count"])

    def test_modulo_distributions(self):
        data = self.payload("modulo")["data"]

        self.assertEqual({"0", "1", "2"}, set(data["mod3"].keys()))
        self.assertEqual(10, len(data["unitDigits"]))

    def test_special_not_mixed_with_main(self):
        data = self.payload("special")["data"]

        hot = data["topSpecialHot"][0]
        self.assertEqual("01", hot["number"])
        self.assertEqual(3, hot["count"])

    def test_weekday_group(self):
        data = self.payload("weekday")["data"]

        weekdays = {row["weekday"] for row in data["weekdayStats"]}
        self.assertIn("Thứ 2", weekdays)

    def test_score_final_score_0_100(self):
        data = self.payload("score")["data"]

        self.assertGreaterEqual(data["finalScore"], 0)
        self.assertLessEqual(data["finalScore"], 100)

    def test_json_payload_shape(self):
        payload = self.payload("all")
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertTrue(payload["ok"])
        for key in ("ok", "type", "period", "mode", "data", "explanations", "warnings"):
            self.assertIn(key, payload)
        self.assertIn("thống kê tham khảo", encoded)


if __name__ == "__main__":
    unittest.main()
