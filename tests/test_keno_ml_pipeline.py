import unittest
from unittest import mock

from ai import ml_pipeline
from ai.predictors import ai_predict
from ai.evaluation.baselines import random_baseline_summary


class KenoMlPipelineTests(unittest.TestCase):
    def test_keno_is_enabled_for_controlled_pipeline(self):
        self.assertIn("KENO", ml_pipeline.SUPPORTED_ML_GAMES)
        cfg = ml_pipeline.game_config("KENO")

        self.assertEqual(80, cfg["universe_size"])
        self.assertEqual(20, cfg["draw_size"])
        self.assertEqual(10, cfg["prediction_size"])

    def test_keno_random_baseline_for_default_level_10(self):
        baseline = random_baseline_summary(80, 20, 10)

        self.assertAlmostEqual(2.5, baseline["expected_hits"])
        self.assertAlmostEqual(0.25, baseline["p0"])

    def test_keno_pure_prediction_does_not_sync_or_lock_ledger(self):
        with mock.patch.object(ai_predict, "sync_ai_history", side_effect=AssertionError("sync called")):
            payload = ai_predict.predict_json("KENO", 1, 10, lock_ledger=True, pure=True)

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["purePrediction"])
        self.assertEqual("KENO", payload["type"])
        self.assertEqual(10, payload["pickSize"])
        self.assertNotIn("predictionId", payload)
        self.assertNotIn("payloadChecksum", payload)
        self.assertAlmostEqual(20.0, payload["probabilitySummary"]["mainProbabilitySum"], places=6)


if __name__ == "__main__":
    unittest.main()
