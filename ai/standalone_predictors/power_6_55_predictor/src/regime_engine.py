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


def _special_reset_share(draws: list[Any], memory_window: int = 4) -> float:
    if not draws:
        return 0.0
    values = []
    for index, draw in enumerate(draws):
        history = [item.special for item in draws[max(0, index - memory_window):index]]
        values.append(int(draw.special not in set(history)))
    return mean(values) if values else 0.0


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
        top_hot = {number for number, _score in sorted(recent_frequency.items(), key=lambda item: item[1], reverse=True)[:12]}
        slots = len(scoped_draws) * 6
        hot_hits = sum(1 for draw in scoped_draws for number in draw.main_numbers if number in top_hot)
        hot_cluster_share = hot_hits / max(1, slots)

    special_values = [draw.special for draw in scoped_draws]
    special_repeat_rate = sum(1 for index in range(1, len(special_values)) if special_values[index] == special_values[index - 1]) / max(1, len(special_values) - 1)
    special_reset_share = _special_reset_share(scoped_draws)
    notes = [
        f"avg_range={avg_range:.2f}",
        f"avg_p5={avg_p5:.2f}",
        f"avg_p6={avg_p6:.2f}",
        f"avg_overlap={avg_overlap:.2f}",
        f"spread_trend={spread_trend:.2f}",
        f"hot_cluster_share={hot_cluster_share:.2f}",
        f"special_repeat_rate={special_repeat_rate:.2f}",
        f"special_reset_share={special_reset_share:.2f}",
    ]

    if avg_range <= 31.0 and avg_p6 <= 47.5 and spread_trend <= -1.5 and special_reset_share >= 0.60:
        regime = "reset"
        notes.append("Recent span compressed, upper tail softened, and special values reset frequently.")
    elif avg_range >= 35.0 and avg_p6 >= 48.5 and avg_overlap >= 0.9 and hot_cluster_share >= 0.28:
        regime = "continuation"
        notes.append("Recent span stayed wide with sustained upper tail and recurring hot clusters.")
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
        "special_repeat_rate": special_repeat_rate,
        "special_reset_share": special_reset_share,
        "last_special": special_values[-1] if special_values else None,
        "notes": notes,
    }


def score_main_number(number: int, regime_context: dict[str, Any]) -> float:
    regime = str(regime_context.get("regime", "neutral"))
    if regime == "reset":
        if number >= 50:
            return 0.34
        if 12 <= number <= 42:
            return 0.78
        return 0.56
    if regime == "continuation":
        if number >= 44:
            return 0.80
        if 24 <= number <= 43:
            return 0.66
        return 0.50
    if 10 <= number <= 46:
        return 0.68
    return 0.53


def score_special_number(number: int, regime_context: dict[str, Any]) -> float:
    regime = str(regime_context.get("regime", "neutral"))
    last_special = regime_context.get("last_special")
    special_repeat_rate = float(regime_context.get("special_repeat_rate", 0.0))
    if regime == "reset":
        if last_special is not None and int(number) == int(last_special):
            return 0.28 if special_repeat_rate < 0.18 else 0.54
        return 0.74
    if regime == "continuation":
        if last_special is not None and abs(int(number) - int(last_special)) <= 2:
            return 0.72
        return 0.58
    if last_special is not None and int(number) == int(last_special):
        return 0.44
    return 0.62


def summarize_regime_notes(regime_context: dict[str, Any]) -> list[str]:
    return list(regime_context.get("notes") or [])
