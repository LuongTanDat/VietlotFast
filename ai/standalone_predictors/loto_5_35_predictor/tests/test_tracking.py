from copy import deepcopy
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import config as cfg, tracking_engine  # noqa: E402


class TrackingTest(unittest.TestCase):
    def test_update_after_actual_marks_hits_and_bonus(self):
        state = deepcopy(cfg.DEFAULT_TRACKING_STATE)
        prediction = {
            "target_draw_id": "999",
            "target_slot": "13:00",
            "main_ticket": [3, 7, 14, 18, 24],
            "bonus": 5,
        }
        actual_draw = {
            "ky": "999",
            "slot": "13:00",
            "main": [3, 8, 14, 25, 31],
            "special": 5,
        }
        next_state = tracking_engine.update_after_actual(state, prediction, actual_draw, cfg.load_config())
        self.assertIn(3, next_state["kept_numbers"])
        self.assertIn(14, next_state["kept_numbers"])
        self.assertIn(5, next_state["prioritized_bonus"])


if __name__ == "__main__":
    unittest.main()
