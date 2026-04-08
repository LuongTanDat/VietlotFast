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
            PROJECT_ROOT / "data" / "power_6_55.csv",
            column_mapping_path=PROJECT_ROOT / "config" / "column_mapping.json",
        )
        draws = bundle["records"]
        config = predictor_api.load_runtime_configuration(PROJECT_ROOT)
        state = tracking_engine.clone_default_state()
        feature_rows = feature_engineering.build_feature_rows(draws[-12:], tracking_state=state, use_mod11=True, time_slot_enabled=False)
        self.assertEqual(len(feature_rows), 12)
        self.assertIn("sum_main", feature_rows[-1])
        self.assertIn("mod3_counts", feature_rows[-1])
        self.assertIn("special_mod5", feature_rows[-1])
        context = feature_engineering.build_prediction_context(
            draws=draws,
            tracking_state=state,
            predictor_config=config["predictor_config"],
            target_weekday=3,
            time_slot_enabled=False,
            use_mod11=True,
        )
        self.assertTrue(sum(context["modulo_context"]["main"]["mod3_usage"].values()) > 0)
        self.assertEqual(len(context["position_profile"]["means"]), 6)
        self.assertIn("special_recent_frequency", context)


if __name__ == "__main__":
    unittest.main()
