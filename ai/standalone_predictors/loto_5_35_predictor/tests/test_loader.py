from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import csv_loader  # noqa: E402


class LoaderTest(unittest.TestCase):
    def test_load_history_from_local_snapshot(self):
        draws = csv_loader.load_history(csv_path=PROJECT_ROOT / "data" / "loto_5_35.csv")
        self.assertGreater(len(draws), 10)
        latest = draws[-1]
        self.assertEqual(len(latest["main"]), 5)
        self.assertIsInstance(latest["special"], int)
        self.assertIn(latest["slot"], ("13:00", "21:00"))


if __name__ == "__main__":
    unittest.main()
