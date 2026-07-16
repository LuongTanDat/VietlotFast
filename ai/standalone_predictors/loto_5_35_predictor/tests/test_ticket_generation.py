from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import predictor_api  # noqa: E402


class PredictorApiTest(unittest.TestCase):
    def test_predict_returns_new_standalone_engine(self):
        payload = predictor_api.predict_pure(PROJECT_ROOT / "data" / "loto_5_35.csv", bundle_count=3)
        self.assertEqual(payload["predictorVersion"], "loto_5_35_vip_v1")
        self.assertEqual(payload["engine"], "loto_5_35_vip")
        self.assertEqual(len(payload["main_ticket"]), 5)
        self.assertEqual(3, len(payload["tickets"]))

    def test_predict_honors_vip_bundle_count_from_one_to_ten(self):
        for bundle_count in (1, 10):
            with self.subTest(bundle_count=bundle_count):
                payload = predictor_api.predict_pure(
                    PROJECT_ROOT / "data" / "loto_5_35.csv",
                    bundle_count=bundle_count,
                )
                self.assertEqual(bundle_count, len(payload["tickets"]))


if __name__ == "__main__":
    unittest.main()
