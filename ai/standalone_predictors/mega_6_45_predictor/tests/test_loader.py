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
            PROJECT_ROOT / "data" / "mega_6_45.csv",
            column_mapping_path=PROJECT_ROOT / "config" / "column_mapping.json",
        )
        records = bundle["records"]
        self.assertGreater(len(records), 1000)
        self.assertFalse(bundle["time_slot_usable"])
        self.assertEqual(records[0].draw_id, 2)
        self.assertEqual(records[-1].draw_id, 1491)
        self.assertEqual(records[-1].main_numbers, (6, 30, 34, 36, 37, 44))


if __name__ == "__main__":
    unittest.main()
