from copy import deepcopy
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import config as cfg, csv_loader, feature_engineering  # noqa: E402


class FeatureSnapshotTest(unittest.TestCase):
    def test_feature_snapshot_contains_main_and_bonus_scores(self):
        draws = csv_loader.load_history(csv_path=PROJECT_ROOT / "data" / "loto_5_35.csv")
        target = csv_loader.infer_next_target_draw(draws)
        snapshot = feature_engineering.build_feature_snapshot(
            draws,
            target,
            deepcopy(cfg.DEFAULT_TRACKING_STATE),
            cfg.load_config(),
        )
        self.assertEqual(len(snapshot["mainHeuristicScores"]), 35)
        self.assertEqual(len(snapshot["bonusHeuristicScores"]), 12)
        self.assertTrue(snapshot["slotHistory"])


if __name__ == "__main__":
    unittest.main()
