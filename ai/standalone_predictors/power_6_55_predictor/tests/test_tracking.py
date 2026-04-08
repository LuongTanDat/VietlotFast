import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import predictor_api, tracking_engine


class TrackingTests(unittest.TestCase):
    def test_tracking_updates_hits_and_misses_for_main_and_special(self):
        runtime = predictor_api.load_runtime_configuration(PROJECT_ROOT)
        state = tracking_engine.clone_default_state()
        update = tracking_engine.update_after_actual(
            state=state,
            prediction_payload={"main_ticket": [9, 21, 32, 34, 52, 53], "special": 22, "target_draw_id": 9999},
            actual_main_numbers=[9, 22, 32, 40, 52, 54],
            actual_special=22,
            tracking_config=runtime["predictor_config"]["tracking"],
            draw_id=9999,
        )
        self.assertEqual(update["exact_main_hit_numbers"], [9, 32, 52])
        self.assertEqual(update["near_cluster_useful_numbers"], [21, 53])
        self.assertEqual(update["missed_numbers"], [34])
        self.assertTrue(update["special_hit"])
        self.assertIn(22, update["next_state"]["prioritized_special"])


if __name__ == "__main__":
    unittest.main()
