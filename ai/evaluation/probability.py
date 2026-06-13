from __future__ import annotations

import math
from typing import Mapping, Sequence

from .metrics import EPSILON, clip_probability


def capped_simplex_projection(values: Sequence[float], target_sum: float, lower: float = 0.0, upper: float = 1.0) -> list[float]:
    q = [float(value) for value in values]
    if not q:
        return []
    lower = float(lower)
    upper = float(upper)
    target_sum = float(target_sum)
    if lower > upper:
        raise ValueError("lower must be <= upper")
    min_sum = lower * len(q)
    max_sum = upper * len(q)
    if target_sum < min_sum - 1e-12 or target_sum > max_sum + 1e-12:
        raise ValueError("target_sum is outside the capped simplex bounds")
    if target_sum <= min_sum:
        return [lower for _ in q]
    if target_sum >= max_sum:
        return [upper for _ in q]

    lo = min(q) - upper
    hi = max(q) - lower
    for _ in range(100):
        mid = (lo + hi) / 2.0
        projected_sum = sum(min(upper, max(lower, value - mid)) for value in q)
        if projected_sum > target_sum:
            lo = mid
        else:
            hi = mid
    theta = (lo + hi) / 2.0
    projected = [min(upper, max(lower, value - theta)) for value in q]
    drift = target_sum - sum(projected)
    if abs(drift) > 1e-10:
        for index in sorted(range(len(projected)), key=lambda i: abs(projected[i] - 0.5)):
            room = upper - projected[index] if drift > 0 else projected[index] - lower
            delta = math.copysign(min(abs(drift), room), drift)
            projected[index] += delta
            drift -= delta
            if abs(drift) <= 1e-10:
                break
    return projected


def project_probability_map(scores: Mapping[int, float], draw_size: int, universe_min: int = 1, universe_max: int | None = None) -> dict[int, float]:
    if universe_max is None:
        universe_max = max(int(key) for key in scores.keys()) if scores else 0
    numbers = list(range(int(universe_min), int(universe_max) + 1))
    values = [float(scores.get(number, 0.0)) for number in numbers]
    projected = capped_simplex_projection(values, float(draw_size), 0.0, 1.0)
    return {number: float(value) for number, value in zip(numbers, projected)}


def scores_to_probabilities(scores: Mapping[int, float], draw_size: int, universe_min: int = 1, universe_max: int | None = None) -> dict[int, float]:
    if universe_max is None:
        universe_max = max(int(key) for key in scores.keys()) if scores else 0
    numbers = list(range(int(universe_min), int(universe_max) + 1))
    values = [float(scores.get(number, 0.0)) for number in numbers]
    if not values:
        return {}
    min_value = min(values)
    shifted = [value - min_value for value in values]
    if sum(shifted) <= 0.0:
        shifted = [1.0 for _ in values]
    scale = float(draw_size) / sum(shifted)
    q = [value * scale for value in shifted]
    projected = capped_simplex_projection(q, float(draw_size), 0.0, 1.0)
    return {number: float(value) for number, value in zip(numbers, projected)}


def fit_platt_scaler(
    raw_scores: Sequence[float],
    labels: Sequence[int],
    iterations: int = 400,
    learning_rate: float = 0.05,
    l2: float = 1e-4,
) -> dict[str, float]:
    x = [float(value) for value in raw_scores]
    y = [1 if int(value) else 0 for value in labels]
    if len(x) != len(y):
        raise ValueError("raw_scores and labels must have the same length")
    if not x:
        return {"slope": 0.0, "intercept": 0.0, "mean": 0.0, "scale": 1.0}
    mean = sum(x) / float(len(x))
    variance = sum((value - mean) ** 2 for value in x) / float(len(x))
    scale = math.sqrt(variance) or 1.0
    z = [(value - mean) / scale for value in x]
    slope = 0.0
    intercept = math.log((sum(y) + 0.5) / (len(y) - sum(y) + 0.5))
    for _ in range(max(1, int(iterations))):
        grad_slope = 0.0
        grad_intercept = 0.0
        for value, label in zip(z, y):
            pred = 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, slope * value + intercept))))
            error = pred - label
            grad_slope += error * value
            grad_intercept += error
        grad_slope = grad_slope / float(len(z)) + float(l2) * slope
        grad_intercept = grad_intercept / float(len(z))
        slope -= float(learning_rate) * grad_slope
        intercept -= float(learning_rate) * grad_intercept
    return {"slope": slope, "intercept": intercept, "mean": mean, "scale": scale}


def apply_platt_scaler(raw_scores: Sequence[float], params: Mapping[str, float], epsilon: float = EPSILON) -> list[float]:
    slope = float(params.get("slope", 0.0))
    intercept = float(params.get("intercept", 0.0))
    mean = float(params.get("mean", 0.0))
    scale = float(params.get("scale", 1.0) or 1.0)
    probabilities = []
    for score in raw_scores:
        value = (float(score) - mean) / scale
        logit = max(-40.0, min(40.0, slope * value + intercept))
        probabilities.append(clip_probability(1.0 / (1.0 + math.exp(-logit)), epsilon=epsilon))
    return probabilities


def calibrate_score_map_with_platt(
    score_map: Mapping[int, float],
    platt_params: Mapping[str, float],
    draw_size: int,
    universe_min: int = 1,
    universe_max: int | None = None,
) -> dict[int, float]:
    if universe_max is None:
        universe_max = max(int(key) for key in score_map.keys()) if score_map else 0
    numbers = list(range(int(universe_min), int(universe_max) + 1))
    raw = [float(score_map.get(number, 0.0)) for number in numbers]
    calibrated = apply_platt_scaler(raw, platt_params)
    projected = capped_simplex_projection(calibrated, float(draw_size), 0.0, 1.0)
    return {number: float(value) for number, value in zip(numbers, projected)}


def fit_isotonic_calibrator(raw_scores: Sequence[float], labels: Sequence[int], min_samples: int = 80) -> dict[str, object]:
    x = [float(value) for value in raw_scores]
    y = [1 if int(value) else 0 for value in labels]
    if len(x) != len(y):
        raise ValueError("raw_scores and labels must have the same length")
    if len(x) < int(min_samples):
        raise ValueError("not enough validation samples for isotonic calibration")
    pairs = sorted(zip(x, y), key=lambda item: item[0])
    blocks: list[dict[str, float]] = []
    for score, label in pairs:
        blocks.append({"min": score, "max": score, "sum": float(label), "count": 1.0})
        while len(blocks) >= 2:
            left = blocks[-2]
            right = blocks[-1]
            if left["sum"] / left["count"] <= right["sum"] / right["count"]:
                break
            merged = {
                "min": left["min"],
                "max": right["max"],
                "sum": left["sum"] + right["sum"],
                "count": left["count"] + right["count"],
            }
            blocks[-2:] = [merged]
    return {
        "method": "isotonic",
        "thresholds": [float(block["max"]) for block in blocks],
        "values": [clip_probability(block["sum"] / block["count"]) for block in blocks],
    }


def apply_isotonic_calibrator(raw_scores: Sequence[float], params: Mapping[str, object], epsilon: float = EPSILON) -> list[float]:
    thresholds = [float(value) for value in list(params.get("thresholds") or [])]
    values = [float(value) for value in list(params.get("values") or [])]
    if not thresholds or len(thresholds) != len(values):
        raise ValueError("invalid isotonic calibration parameters")
    probabilities = []
    for score in raw_scores:
        chosen = values[-1]
        for threshold, value in zip(thresholds, values):
            if float(score) <= threshold:
                chosen = value
                break
        probabilities.append(clip_probability(chosen, epsilon=epsilon))
    return probabilities


def calibrate_scores(
    raw_scores: Sequence[float],
    validation_scores: Sequence[float],
    validation_labels: Sequence[int],
    method: str = "platt",
    isotonic_min_samples: int = 80,
) -> list[float]:
    if str(method or "platt").lower() == "isotonic" and len(validation_scores) >= int(isotonic_min_samples):
        params = fit_isotonic_calibrator(validation_scores, validation_labels, min_samples=isotonic_min_samples)
        return apply_isotonic_calibrator(raw_scores, params)
    params = fit_platt_scaler(validation_scores, validation_labels)
    return apply_platt_scaler(raw_scores, params)
