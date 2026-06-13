from __future__ import annotations

import random
from statistics import mean
from typing import Callable, Sequence


def _default_statistic(values: Sequence[float]) -> float:
    return mean(values) if values else 0.0


def paired_differences(a: Sequence[float], b: Sequence[float]) -> list[float]:
    if len(a) != len(b):
        raise ValueError("paired samples must have the same length")
    return [float(left) - float(right) for left, right in zip(a, b)]


def paired_bootstrap_ci(
    a: Sequence[float],
    b: Sequence[float],
    iterations: int = 2000,
    confidence: float = 0.95,
    seed: int = 20260403,
    statistic: Callable[[Sequence[float]], float] | None = None,
) -> dict[str, float]:
    differences = paired_differences(a, b)
    if not differences:
        return {"mean": 0.0, "lower": 0.0, "upper": 0.0, "confidence": float(confidence)}
    statistic = statistic or _default_statistic
    rng = random.Random(int(seed))
    samples = []
    n = len(differences)
    for _ in range(max(1, int(iterations))):
        draw = [differences[rng.randrange(n)] for _ in range(n)]
        samples.append(float(statistic(draw)))
    samples.sort()
    alpha = max(0.0, min(1.0, 1.0 - float(confidence)))
    lower_index = min(len(samples) - 1, max(0, int((alpha / 2.0) * len(samples))))
    upper_index = min(len(samples) - 1, max(0, int((1.0 - alpha / 2.0) * len(samples)) - 1))
    return {
        "mean": float(statistic(differences)),
        "lower": float(samples[lower_index]),
        "upper": float(samples[upper_index]),
        "confidence": float(confidence),
    }


def paired_permutation_test(
    a: Sequence[float],
    b: Sequence[float],
    iterations: int = 2000,
    seed: int = 20260403,
    statistic: Callable[[Sequence[float]], float] | None = None,
) -> dict[str, float]:
    differences = paired_differences(a, b)
    if not differences:
        return {"observed": 0.0, "p_value": 1.0, "iterations": float(iterations)}
    statistic = statistic or _default_statistic
    rng = random.Random(int(seed))
    observed = abs(float(statistic(differences)))
    exceed = 0
    for _ in range(max(1, int(iterations))):
        signed = [value if rng.random() < 0.5 else -value for value in differences]
        if abs(float(statistic(signed))) >= observed:
            exceed += 1
    return {
        "observed": float(statistic(differences)),
        "p_value": (exceed + 1.0) / (max(1, int(iterations)) + 1.0),
        "iterations": float(max(1, int(iterations))),
    }
