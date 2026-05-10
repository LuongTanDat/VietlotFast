import json
import tempfile
import unittest
from pathlib import Path

from ai.stats import stats_v2 as sv2


SAMPLE_LOTO_535 = """Kỳ,Thứ,Ngày,Giờ,Bộ Số,ĐB,Hiển thị,Loại,Link cập nhật,Ngày cập nhật
5,Thứ 2,05/01/2026,21:00,"1,2,3,4,5",1,01 02 03 04 05 | ĐB 01,Loto_5/35,https://example.test,05/01/2026
4,Chủ Nhật,04/01/2026,21:00,"2,3,4,5,6",2,02 03 04 05 06 | ĐB 02,Loto_5/35,https://example.test,04/01/2026
3,Thứ 7,03/01/2026,21:00,"1,2,7,8,9",1,01 02 07 08 09 | ĐB 01,Loto_5/35,https://example.test,03/01/2026
2,Thứ 6,02/01/2026,21:00,"1,3,5,7,9",3,01 03 05 07 09 | ĐB 03,Loto_5/35,https://example.test,02/01/2026
1,Thứ 5,01/01/2026,21:00,"1,2,3,4,5",1,01 02 03 04 05 | ĐB 01,Loto_5/35,https://example.test,01/01/2026
"""


class StatsV2Tests(unittest.TestCase):
    def write_csv(self, text=SAMPLE_LOTO_535):
        temp = tempfile.TemporaryDirectory()
        path = Path(temp.name) / "loto_5_35_all_day.csv"
        path.write_text(text, encoding="utf-8", newline="")
        self.addCleanup(temp.cleanup)
        return path

    def payload(self, **kwargs):
        return sv2.build_stats_payload(
            kwargs.pop("type_key", "LOTO_5_35"),
            csv_path=self.write_csv(),
            **kwargs,
        )

    def find_item(self, payload, label):
        return next(item for item in payload["items"] if item["label"] == label)

    def test_parse_csv(self):
        draws = sv2.load_draws("LOTO_5_35", self.write_csv())

        self.assertEqual(5, len(draws))
        self.assertEqual("1", draws[0]["ky"])
        self.assertEqual([1, 2, 3, 4, 5], draws[0]["main"])
        self.assertEqual(1, draws[0]["special"])

    def test_filter_period(self):
        payload = self.payload(period="custom", from_date="03/01/2026", to_date="05/01/2026")

        self.assertTrue(payload["ok"])
        self.assertEqual(3, payload["totalDraws"])
        self.assertEqual("03/01/2026", payload["filteredFrom"])
        self.assertEqual("05/01/2026", payload["filteredTo"])

    def test_count_1_number(self):
        payload = self.payload(period="all", group="main", combo_size=1, sort_key="most")
        item = self.find_item(payload, "01")

        self.assertEqual(4, item["count"])
        self.assertEqual(0, item["currentGap"])

    def test_combo_2_numbers(self):
        payload = self.payload(period="all", group="main", combo_size=2, sort_key="most")
        item = self.find_item(payload, "01-02")

        self.assertEqual(3, item["count"])

    def test_combo_3_numbers(self):
        payload = self.payload(period="all", group="main", combo_size=3, sort_key="most")
        item = self.find_item(payload, "01-02-03")

        self.assertEqual(2, item["count"])

    def test_current_gap(self):
        payload = self.payload(period="all", group="main", combo_size=1, sort_key="overdue")
        item = self.find_item(payload, "07")

        self.assertEqual(2, item["currentGap"])
        self.assertEqual("3", item["lastSeenKy"])

    def test_avg_cycle(self):
        payload = self.payload(period="all", group="main", combo_size=1, sort_key="most")
        item = self.find_item(payload, "01")

        self.assertEqual(1.25, item["avgCycle"])

    def test_lotto_535_main_and_special(self):
        main_payload = self.payload(period="all", group="main", combo_size=1, sort_key="most")
        special_payload = self.payload(period="all", group="special", combo_size=1, sort_key="most")

        self.assertEqual(4, self.find_item(main_payload, "01")["count"])
        self.assertEqual(3, self.find_item(special_payload, "01")["count"])
        self.assertIn("loto535Summary", main_payload)
        self.assertIn("jackpot", main_payload)

    def test_payload_json_has_no_error(self):
        payload = self.payload(period="all", group="main", combo_size=1, sort_key="most")
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertTrue(payload["ok"])
        self.assertIn("stats_v2", encoded)


if __name__ == "__main__":
    unittest.main()

