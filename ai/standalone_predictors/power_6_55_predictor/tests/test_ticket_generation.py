import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import data_loader, predictor_api, tracking_engine


class TicketGenerationTests(unittest.TestCase):
    def test_ticket_generation_returns_sorted_unique_tickets_and_special(self):
        runtime = predictor_api.load_runtime_configuration(PROJECT_ROOT)
        bundle = data_loader.load_draw_records(
            PROJECT_ROOT / "data" / "power_6_55.csv",
            column_mapping_path=PROJECT_ROOT / "config" / "column_mapping.json",
        )
        draws = bundle["records"]
        state = tracking_engine.clone_default_state()
        target = data_loader.infer_next_draw(draws, runtime["predictor_config"]["schedule_weekdays"])
        target["time_slot_enabled"] = False
        result = predictor_api.build_prediction_from_history(
            draws=draws,
            tracking_state=state,
            predictor_config=runtime["predictor_config"],
            feature_flags=runtime["feature_flags"],
            target_info=target,
            project_root=PROJECT_ROOT,
            backup_count=3,
        )
        self.assertEqual(len(result["main_ticket"]), 6)
        self.assertEqual(result["main_ticket"], sorted(set(result["main_ticket"])))
        self.assertGreaterEqual(len(result["backup_tickets"]), 2)
        self.assertIsNotNone(result["special"])
        self.assertGreaterEqual(result["special"], 1)
        self.assertLessEqual(result["special"], 55)
        self.assertNotIn(result["special"], result["main_ticket"])
        self.assertGreaterEqual(len(result["special_backups"]), 2)
        self.assertGreaterEqual(result["quality_score"], 0.0)
        self.assertLessEqual(result["quality_score"], 100.0)


if __name__ == "__main__":
    unittest.main()
