from __future__ import annotations

import math
from collections import Counter
from typing import Iterable, Mapping, Sequence

from .baselines import expected_random_hits

EPSILON = 1e-6


def _coerce_probability_vector(values: Mapping[int, float] | Sequence[float], universe_size: int) -> list[float]:
    if isinstance(values, Mapping):
        return [float(values.get(index, 0.0)) for index in range(1, universe_size + 1)]
    vector = [float(value) for value in list(values)]
    if len(vector) != universe_size:
        raise ValueError("probability vector length does not match universe_size")
    return vector


def _coerce_label_vector(values: Iterable[int] | Mapping[int, int] | Sequence[int], universe_size: int) -> list[int]:
    if isinstance(values, Mapping):
        return [1 if int(values.get(index, 0)) else 0 for index in range(1, universe_size + 1)]
    raw = list(values)
    if len(raw) == universe_size and all(value in (0, 1, False, True) for value in raw):
        return [1 if int(value) else 0 for value in raw]
    hit_set = {int(value) for value in raw}
    return [1 if index in hit_set else 0 for index in range(1, universe_size + 1)]


def clip_probability(value: float, epsilon: float = EPSILON) -> float:
    return min(1.0 - float(epsilon), max(float(epsilon), float(value)))


def brier_score(
    probabilities: Sequence[Mapping[int, float] | Sequence[float]],
    labels: Sequence[Iterable[int] | Mapping[int, int] | Sequence[int]],
    universe_size: int,
) -> float:
    if len(probabilities) != len(labels):
        raise ValueError("probabilities and labels must have the same number of draws")
    if not probabilities:
        return 0.0
    total = 0.0
    for prob_row, label_row in zip(probabilities, labels):
        prob_vector = _coerce_probability_vector(prob_row, universe_size)
        label_vector = _coerce_label_vector(label_row, universe_size)
        total += sum((float(prob) - int(label)) ** 2 for prob, label in zip(prob_vector, label_vector))
    return total / float(len(probabilities) * universe_size)


def log_loss(
    probabilities: Sequence[Mapping[int, float] | Sequence[float]],
    labels: Sequence[Iterable[int] | Mapping[int, int] | Sequence[int]],
    universe_size: int,
    epsilon: float = EPSILON,
) -> float:
    if len(probabilities) != len(labels):
        raise ValueError("probabilities and labels must have the same number of draws")
    if not probabilities:
        return 0.0
    total = 0.0
    for prob_row, label_row in zip(probabilities, labels):
        prob_vector = _coerce_probability_vector(prob_row, universe_size)
        label_vector = _coerce_label_vector(label_row, universe_size)
        for prob, label in zip(prob_vector, label_vector):
            clipped = clip_probability(prob, epsilon=epsilon)
            total += int(label) * math.log(clipped) + (1 - int(label)) * math.log(1.0 - clipped)
    return -total / float(len(probabilities) * universe_size)


def mean_hit(predictions: Sequence[Iterable[int]], actuals: Sequence[Iterable[int]]) -> float:
    if len(predictions) != len(actuals):
        raise ValueError("predictions and actuals must have the same number of draws")
    if not predictions:
        return 0.0
    hits = []
    for predicted, actual in zip(predictions, actuals):
        hits.append(len({int(value) for value in predicted} & {int(value) for value in actual}))
    return sum(hits) / float(len(hits))


def match_count_distribution(predictions: Sequence[Iterable[int]], actuals: Sequence[Iterable[int]]) -> dict[int, int]:
    if len(predictions) != len(actuals):
        raise ValueError("predictions and actuals must have the same number of draws")
    counts = Counter()
    for predicted, actual in zip(predictions, actuals):
        counts[len({int(value) for value in predicted} & {int(value) for value in actual})] += 1
    return dict(sorted(counts.items()))


def lift(mean_hit_value: float, universe_size: int, draw_size: int, prediction_size: int) -> float:
    baseline = expected_random_hits(universe_size, draw_size, prediction_size)
    if baseline <= 0:
        return 0.0
    return float(mean_hit_value) / baseline - 1.0


def calibration_error(
    probabilities: Sequence[Mapping[int, float] | Sequence[float]],
    labels: Sequence[Iterable[int] | Mapping[int, int] | Sequence[int]],
    universe_size: int,
    bins: int = 10,
) -> float:
    if len(probabilities) != len(labels):
        raise ValueError("probabilities and labels must have the same number of draws")
    bins = max(1, int(bins))
    bucket_prob_sum = [0.0 for _ in range(bins)]
    bucket_label_sum = [0.0 for _ in range(bins)]
    bucket_count = [0 for _ in range(bins)]
    for prob_row, label_row in zip(probabilities, labels):
        prob_vector = _coerce_probability_vector(prob_row, universe_size)
        label_vector = _coerce_label_vector(label_row, universe_size)
        for prob, label in zip(prob_vector, label_vector):
            clipped = max(0.0, min(1.0, float(prob)))
            index = min(bins - 1, int(clipped * bins))
            bucket_prob_sum[index] += clipped
            bucket_label_sum[index] += int(label)
            bucket_count[index] += 1
    total = sum(bucket_count)
    if total <= 0:
        return 0.0
    error = 0.0
    for index, count in enumerate(bucket_count):
        if count <= 0:
            continue
        avg_prob = bucket_prob_sum[index] / float(count)
        avg_label = bucket_label_sum[index] / float(count)
        error += (count / float(total)) * abs(avg_prob - avg_label)
    return error


def evaluate_ticket_predictions(
    predictions: Sequence[Iterable[int]],
    actuals: Sequence[Iterable[int]],
    universe_size: int,
    draw_size: int,
    prediction_size: int,
) -> dict[str, object]:
    hit_mean = mean_hit(predictions, actuals)
    return {
        "mean_hit": hit_mean,
        "match_distribution": match_count_distribution(predictions, actuals),
        "expected_random_hits": expected_random_hits(universe_size, draw_size, prediction_size),
        "lift": lift(hit_mean, universe_size, draw_size, prediction_size),
    }
