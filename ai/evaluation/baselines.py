from __future__ import annotations

from math import comb


def random_number_probability(universe_size: int, draw_size: int) -> float:
    universe_size = int(universe_size)
    draw_size = int(draw_size)
    if universe_size <= 0:
        raise ValueError("universe_size must be positive")
    if draw_size < 0 or draw_size > universe_size:
        raise ValueError("draw_size must be between 0 and universe_size")
    return draw_size / float(universe_size)


def hypergeometric_match_distribution(universe_size: int, draw_size: int, prediction_size: int) -> dict[int, float]:
    universe_size = int(universe_size)
    draw_size = int(draw_size)
    prediction_size = int(prediction_size)
    if universe_size <= 0:
        raise ValueError("universe_size must be positive")
    if draw_size < 0 or draw_size > universe_size:
        raise ValueError("draw_size must be between 0 and universe_size")
    if prediction_size < 0 or prediction_size > universe_size:
        raise ValueError("prediction_size must be between 0 and universe_size")

    denominator = comb(universe_size, prediction_size)
    low = max(0, prediction_size - (universe_size - draw_size))
    high = min(draw_size, prediction_size)
    return {
        hits: comb(draw_size, hits) * comb(universe_size - draw_size, prediction_size - hits) / float(denominator)
        for hits in range(low, high + 1)
    }


def expected_random_hits(universe_size: int, draw_size: int, prediction_size: int) -> float:
    return int(prediction_size) * int(draw_size) / float(int(universe_size))


def random_baseline_summary(universe_size: int, draw_size: int, prediction_size: int) -> dict[str, object]:
    distribution = hypergeometric_match_distribution(universe_size, draw_size, prediction_size)
    return {
        "p0": random_number_probability(universe_size, draw_size),
        "expected_hits": expected_random_hits(universe_size, draw_size, prediction_size),
        "match_distribution": distribution,
    }
