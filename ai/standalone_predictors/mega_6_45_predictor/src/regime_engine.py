from __future__ import annotations

from statistics import mean
from typing import Any


def _average_overlap(draws: list[Any]) -> float:
    if len(draws) < 2:
        return 0.0
    overlaps = []
    for index in range(1, len(draws)):
        current = set(draws[index].main_numbers)
        previous = set(draws[index - 1].main_numbers)
        overlaps.append(len(current & previous))
    return mean(overlaps) if overlaps else 0.0


def detect_regime(draws: list[Any], recent_frequency: dict[int, float] | None = None) -> dict[str, Any]:
    scoped_draws = list(draws[-8:])
    if not scoped_draws:
        return {
            "regime": "neutral",
            "notes": ["No recent history was available, defaulting regime to neutral."],
        }

    ranges = [max(draw.main_numbers) - min(draw.main_numbers) for draw in scoped_draws]
    p6_values = [draw.main_numbers[-1] for draw in scoped_draws]
    p5_values = [draw.main_numbers[-2] for draw in scoped_draws]
    avg_range = mean(ranges)
    avg_p6 = mean(p6_values)
    avg_p5 = mean(p5_values)
    avg_overlap = _average_overlap(scoped_draws)
    spread_trend = 0.0
    if len(scoped_draws) >= 6:
        first_half = ranges[: len(ranges) // 2]
        second_half = ranges[len(ranges) // 2 :]
        if first_half and second_half:
            spread_trend = mean(second_half) - mean(first_half)

    hot_cluster_share = 0.0
    if recent_frequency:
        top_hot = {number for number, _score in sorted(recent_frequency.items(), key=lambda item: item[1], reverse=True)[:10]}
        slots = len(scoped_draws) * 6
        hot_hits = sum(1 for draw in scoped_draws for number in draw.main_numbers if number in top_hot)
        hot_cluster_share = hot_hits / max(1, slots)

    notes = [
        f"avg_range={avg_range:.2f}",
        f"avg_p5={avg_p5:.2f}",
        f"avg_p6={avg_p6:.2f}",
        f"avg_overlap={avg_overlap:.2f}",
        f"spread_trend={spread_trend:.2f}",
        f"hot_cluster_share={hot_cluster_share:.2f}",
    ]

    if avg_range <= 24.0 and avg_p6 <= 39.0 and spread_trend <= -1.0:
        regime = "reset"
        notes.append("Recent span compressed and upper tail softened, so the regime leans reset.")
    elif avg_range >= 28.0 and avg_p6 >= 40.0 and avg_overlap >= 1.0:
        regime = "continuation"
        notes.append("Recent span stayed wide with a steady upper tail, so the regime leans continuation.")
    else:
        regime = "neutral"
        notes.append("Recent structure stayed mixed, so the regime remains neutral.")

    return {
        "regime": regime,
        "average_range": avg_range,
        "average_p5": avg_p5,
        "average_p6": avg_p6,
        "average_overlap": avg_overlap,
        "hot_cluster_share": hot_cluster_share,
        "notes": notes,
    }


def score_number(number: int, regime_context: dict[str, Any]) -> float:
    regime = str(regime_context.get("regime", "neutral"))
    if regime == "reset":
        if number >= 41:
            return 0.30
        if 10 <= number <= 36:
            return 0.75
        return 0.55
    if regime == "continuation":
        if number >= 37:
            return 0.78
        if 24 <= number <= 36:
            return 0.65
        return 0.50
    if 8 <= number <= 38:
        return 0.68
    return 0.52


def summarize_regime_notes(regime_context: dict[str, Any]) -> list[str]:
    return list(regime_context.get("notes") or [])
