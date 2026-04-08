import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import data_loader, feature_engineering, predictor_api, tracking_engine


class FeatureTests(unittest.TestCase):
    def test_feature_rows_and_context_exist(self):
        bundle = data_loader.load_draw_records(
            PROJECT_ROOT / "data" / "mega_6_45.csv",
            column_mapping_path=PROJECT_ROOT / "config" / "column_mapping.json",
        )
        draws = bundle["records"]
        config = predictor_api.load_runtime_configuration(PROJECT_ROOT)
        state = tracking_engine.clone_default_state()
        feature_rows = feature_engineering.build_feature_rows(draws[-12:], tracking_state=state, use_mod9=True, time_slot_enabled=False)
        self.assertEqual(len(feature_rows), 12)
        self.assertIn("sum_main", feature_rows[-1])
        self.assertIn("mod3_counts", feature_rows[-1])
        context = feature_engineering.build_prediction_context(
            draws=draws,
            tracking_state=state,
            predictor_config=config["predictor_config"],
            target_weekday=4,
            time_slot_enabled=False,
            use_mod9=True,
        )
        self.assertEqual(sum(context["modulo_context"]["mod3_usage"].values()) > 0, True)
        self.assertEqual(len(context["position_profile"]["means"]), 6)


if __name__ == "__main__":
    unittest.main()
