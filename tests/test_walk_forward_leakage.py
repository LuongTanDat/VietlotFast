import unittest
from pathlib import Path

from ai.evaluation.walk_forward import (
    SimpleStandardScaler,
    WalkForwardConfig,
    model_is_safe_for_target,
    run_walk_forward_backtest,
)


def make_draw(draw_id, numbers):
    return {"draw_id": draw_id, "main": list(numbers)}


class WalkForwardLeakageTests(unittest.TestCase):
    def test_future_data_change_does_not_change_past_prediction(self):
        draws = [make_draw(index, [index % 10 + 1, (index + 1) % 10 + 1]) for index in range(1, 10)]
        changed_future = [dict(draw) for draw in draws]
        changed_future[-1] = make_draw(9, [99, 100])

        def make_prediction(history, target, tracking):
            del target, tracking
            return {
                "main_ticket": list(history[-1]["main"]),
                "calibrated_probability": {number: 0.2 for number in range(1, 11)},
            }

        config = WalkForwardConfig(min_history=4, max_folds=3, mode="fast")
        base = run_walk_forward_backtest(
            draws,
            make_prediction,
            lambda draw: draw["main"],
            lambda draw: draw["draw_id"],
            config=config,
            universe_size=10,
            draw_size=2,
            prediction_size=2,
        )
        mutated = run_walk_forward_backtest(
            changed_future,
            make_prediction,
            lambda draw: draw["main"],
            lambda draw: draw["draw_id"],
            config=config,
            universe_size=10,
            draw_size=2,
            prediction_size=2,
        )

        self.assertEqual(base["folds"][0]["main_ticket"], mutated["folds"][0]["main_ticket"])
        self.assertEqual(base["folds"][0]["data_cutoff_draw_id"], mutated["folds"][0]["data_cutoff_draw_id"])

    def test_future_deep_model_is_rejected_for_past_fold(self):
        self.assertFalse(model_is_safe_for_target({"trained_on_latest_draw_id": 100}, 100))
        self.assertFalse(model_is_safe_for_target({"trained_on_latest_draw_id": 101}, 100))
        self.assertTrue(model_is_safe_for_target({"trained_on_latest_draw_id": 99}, 100))

    def test_three_standalone_deep_models_have_future_artifact_guard(self):
        for path in (
            "ai/standalone_predictors/loto_5_35_predictor/src/deep_model.py",
            "ai/standalone_predictors/mega_6_45_predictor/src/deep_model.py",
            "ai/standalone_predictors/power_6_55_predictor/src/deep_model.py",
        ):
            source = Path(path).read_text(encoding="utf-8")
            self.assertIn("trained_on_latest_draw_id", source)
            self.assertIn("future_artifact_rejected", source)

    def test_scaler_fit_cutoff_must_be_before_target(self):
        scaler = SimpleStandardScaler().fit([[1.0], [2.0], [3.0]], cutoff_draw_id=10)

        scaler.assert_fit_before(11)
        with self.assertRaises(ValueError):
            scaler.assert_fit_before(10)


if __name__ == "__main__":
    unittest.main()
