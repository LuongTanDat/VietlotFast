from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from .metrics import brier_score, calibration_error, evaluate_ticket_predictions, log_loss


@dataclass
class WalkForwardConfig:
    min_history: int = 60
    window: str = "expanding"
    rolling_window: int | None = None
    step: int = 1
    mode: str = "fast"
    max_folds: int | None = None
    retrain_interval: int = 1
    deep_policy: str = "guarded"
    random_seed: int = 20260403


def normalize_draw_id(value: Any) -> int:
    if isinstance(value, int):
        return value
    text = str(value or "").strip()
    digits = "".join(re.findall(r"\d+", text))
    return int(digits or "0")


def model_is_safe_for_target(model_meta: dict[str, Any] | None, target_draw_id: Any) -> bool:
    if not model_meta:
        return False
    trained_on = normalize_draw_id(model_meta.get("trained_on_latest_draw_id"))
    target = normalize_draw_id(target_draw_id)
    return bool(trained_on and target and trained_on < target)


def walk_forward_indices(total: int, config: WalkForwardConfig) -> list[tuple[int, int, int]]:
    total = int(total)
    min_history = max(1, int(config.min_history))
    step = max(1, int(config.step or 1))
    if total <= min_history:
        return []
    indexes = list(range(min_history, total, step))
    if config.max_folds is not None:
        indexes = indexes[-max(0, int(config.max_folds)) :]
    splits = []
    for target_index in indexes:
        if str(config.window).lower() == "rolling":
            width = max(min_history, int(config.rolling_window or min_history))
            train_start = max(0, target_index - width)
        else:
            train_start = 0
        splits.append((train_start, target_index, target_index))
    return splits


class SimpleStandardScaler:
    def __init__(self) -> None:
        self.mean_: list[float] = []
        self.scale_: list[float] = []
        self.fit_cutoff_draw_id: int | None = None

    def fit(self, rows: Sequence[Sequence[float]], cutoff_draw_id: Any = None) -> "SimpleStandardScaler":
        if not rows:
            self.mean_ = []
            self.scale_ = []
            self.fit_cutoff_draw_id = normalize_draw_id(cutoff_draw_id)
            return self
        width = len(rows[0])
        columns = [[float(row[index]) for row in rows] for index in range(width)]
        self.mean_ = [sum(column) / float(len(column)) for column in columns]
        self.scale_ = []
        for column, mean_value in zip(columns, self.mean_):
            variance = sum((value - mean_value) ** 2 for value in column) / float(len(column))
            self.scale_.append(variance ** 0.5 or 1.0)
        self.fit_cutoff_draw_id = normalize_draw_id(cutoff_draw_id)
        return self

    def transform(self, rows: Sequence[Sequence[float]]) -> list[list[float]]:
        return [
            [(float(value) - self.mean_[index]) / self.scale_[index] for index, value in enumerate(row)]
            for row in rows
        ]

    def assert_fit_before(self, target_draw_id: Any) -> None:
        target = normalize_draw_id(target_draw_id)
        if self.fit_cutoff_draw_id is not None and target and self.fit_cutoff_draw_id >= target:
            raise ValueError("scaler was fit on future data for this fold")


def run_walk_forward_backtest(
    draws: Sequence[Any],
    make_prediction: Callable[[list[Any], Any, Any], dict[str, Any]],
    get_actual_numbers: Callable[[Any], Iterable[int]],
    get_draw_id: Callable[[Any], Any],
    update_tracking: Callable[[Any, dict[str, Any], Any], Any] | None = None,
    initial_tracking: Any = None,
    config: WalkForwardConfig | None = None,
    universe_size: int | None = None,
    draw_size: int | None = None,
    prediction_size: int | None = None,
) -> dict[str, Any]:
    config = config or WalkForwardConfig()
    tracking_state = copy.deepcopy(initial_tracking)
    folds = []
    predictions = []
    actuals = []
    probability_rows = []
    for fold_index, (train_start, train_end, target_index) in enumerate(walk_forward_indices(len(draws), config), start=1):
        history = list(draws[train_start:train_end])
        target = draws[target_index]
        target_draw_id = get_draw_id(target)
        prediction = make_prediction(history, target, copy.deepcopy(tracking_state))
        predicted_main = [int(value) for value in list(prediction.get("main_ticket") or prediction.get("main") or [])]
        actual_main = [int(value) for value in list(get_actual_numbers(target))]
        probabilities = prediction.get("calibrated_probability") or prediction.get("probabilities") or {}
        predictions.append(predicted_main)
        actuals.append(actual_main)
        if probabilities:
            probability_rows.append(probabilities)
        fold = {
            "fold": fold_index,
            "train_start_index": train_start,
            "train_end_index": train_end - 1,
            "target_index": target_index,
            "target_draw_id": str(target_draw_id),
            "data_cutoff_draw_id": str(get_draw_id(history[-1]) if history else ""),
            "main_ticket": predicted_main,
            "actual_main": actual_main,
            "hit_count": len(set(predicted_main) & set(actual_main)),
            "deep_status": prediction.get("deep_status", ""),
            "deep_status_reason": prediction.get("deep_status_reason", ""),
            "calibrated_probability": probabilities,
        }
        folds.append(fold)
        if update_tracking is not None:
            tracking_state = update_tracking(tracking_state, prediction, target)
    metrics = {}
    if universe_size and draw_size and prediction_size:
        metrics.update(evaluate_ticket_predictions(predictions, actuals, universe_size, draw_size, prediction_size))
        if probability_rows and len(probability_rows) == len(actuals):
            metrics["brier_score"] = brier_score(probability_rows, actuals, universe_size)
            metrics["log_loss"] = log_loss(probability_rows, actuals, universe_size)
            metrics["calibration_error"] = calibration_error(probability_rows, actuals, universe_size)
    return {
        "ok": True,
        "mode": config.mode,
        "window": config.window,
        "rolling_window": config.rolling_window,
        "min_history": config.min_history,
        "folds": folds,
        "metrics": metrics,
    }
