import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import predictor_api, tracking_engine


class TrackingTests(unittest.TestCase):
    def test_tracking_updates_hits_and_misses(self):
        runtime = predictor_api.load_runtime_configuration(PROJECT_ROOT)
        state = tracking_engine.clone_default_state()
        update = tracking_engine.update_after_actual(
            state=state,
            prediction_payload={"main_ticket": [6, 12, 18, 25, 31, 42], "target_draw_id": 9999},
            actual_numbers=[6, 13, 18, 24, 31, 45],
            tracking_config=runtime["predictor_config"]["tracking"],
            draw_id=9999,
        )
        self.assertEqual(update["exact_hit_numbers"], [6, 18, 31])
        self.assertEqual(update["near_cluster_useful_numbers"], [12, 25])
        self.assertEqual(update["missed_numbers"], [42])


if __name__ == "__main__":
    unittest.main()
