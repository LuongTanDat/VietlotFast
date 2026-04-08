import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import data_loader


class LoaderTests(unittest.TestCase):
    def test_loader_parses_real_repo_csv(self):
        bundle = data_loader.load_draw_records(
            PROJECT_ROOT / "data" / "power_6_55.csv",
            column_mapping_path=PROJECT_ROOT / "config" / "column_mapping.json",
        )
        records = bundle["records"]
        self.assertEqual(len(records), 1323)
        self.assertFalse(bundle["time_slot_usable"])
        self.assertEqual(records[0].draw_id, 5)
        self.assertEqual(records[-1].draw_id, 1327)
        self.assertEqual(records[-1].main_numbers, (9, 21, 32, 34, 52, 53))
        self.assertEqual(records[-1].special, 22)


if __name__ == "__main__":
    unittest.main()
