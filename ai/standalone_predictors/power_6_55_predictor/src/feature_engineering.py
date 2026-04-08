from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean, pstdev
from typing import Any

from src import modulo_engine, tracking_engine


def build_number_frequency(
    draws: list[Any],
    number_min: int = 1,
    number_max: int = 55,
    weights: list[float] | None = None,
) -> dict[int, float]:
    scores = {number: 0.0 for number in range(number_min, number_max + 1)}
    if not draws:
        return scores
    if weights is None:
        weights = [1.0 for _ in draws]
    scoped_weights = list(weights)[-len(draws):]
    scoped_draws = list(draws[-len(scoped_weights):])
    for draw, weight in zip(scoped_draws, scoped_weights):
        for number in draw.main_numbers:
            scores[int(number)] += float(weight)
    max_score = max(scores.values()) if scores else 1.0
    if max_score <= 0:
        return {number: 0.0 for number in range(number_min, number_max + 1)}
    return {number: value / max_score for number, value in scores.items()}


def build_special_frequency(
    draws: list[Any],
    number_min: int = 1,
    number_max: int = 55,
    weights: list[float] | None = None,
) -> dict[int, float]:
    scores = {number: 0.0 for number in range(number_min, number_max + 1)}
    if not draws:
        return scores
    if weights is None:
        weights = [1.0 for _ in draws]
    scoped_weights = list(weights)[-len(draws):]
    scoped_draws = list(draws[-len(scoped_weights):])
    for draw, weight in zip(scoped_draws, scoped_weights):
        scores[int(draw.special)] += float(weight)
    max_score = max(scores.values()) if scores else 1.0
    if max_score <= 0:
        return {number: 0.0 for number in range(number_min, number_max + 1)}
    return {number: value / max_score for number, value in scores.items()}


def _position_profile(draws: list[Any]) -> dict[str, list[float]]:
    if not draws:
        return {
            "means": [8.5, 16.5, 25.0, 34.0, 44.0, 51.5],
            "stds": [5.0] * 6,
        }
    positions = defaultdict(list)
    for draw in draws:
        for index, value in enumerate(draw.main_numbers):
            positions[index].append(value)
    means = [mean(positions[index]) for index in range(6)]
    stds = [max(3.0, pstdev(positions[index]) if len(positions[index]) > 1 else 4.0) for index in range(6)]
    return {"means": means, "stds": stds}


def _average_overlap(draws: list[Any]) -> float:
    if len(draws) < 2:
        return 0.0
    overlaps = []
    for index in range(1, len(draws)):
        overlaps.append(len(set(draws[index].main_numbers) & set(draws[index - 1].main_numbers)))
    return mean(overlaps) if overlaps else 0.0


def _special_repeat_rate(draws: list[Any]) -> float:
    if len(draws) < 2:
        return 0.0
    repeats = 0
    for index in range(1, len(draws)):
        repeats += int(draws[index].special == draws[index - 1].special)
    return repeats / max(1, len(draws) - 1)


def _special_reset_rate(draws: list[Any], memory_window: int = 4) -> float:
    if not draws:
        return 0.0
    reset_hits = 0
    for index, draw in enumerate(draws):
        prior = [item.special for item in draws[max(0, index - memory_window):index]]
        reset_hits += int(draw.special not in set(prior))
    return reset_hits / max(1, len(draws))


def build_feature_rows(
    draws: list[Any],
    tracking_state: dict[str, Any] | None = None,
    use_mod11: bool = True,
    time_slot_enabled: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    previous_same_weekday: dict[int, Any] = {}
    for index, draw in enumerate(draws):
        previous_draw = draws[index - 1] if index > 0 else None
        same_weekday_draw = previous_same_weekday.get(draw.draw_date.weekday())
        recent_window = draws[max(0, index - 4):index]
        recent_union = set(number for recent_draw in recent_window for number in recent_draw.main_numbers)
        recent_specials = {recent_draw.special for recent_draw in recent_window}
        modulo_description = modulo_engine.describe_main_numbers(draw.main_numbers, use_mod11=use_mod11)
        special_description = modulo_engine.describe_special_number(draw.special)
        tracking_snapshots = [tracking_engine.get_tracking_snapshot_main(tracking_state or {}, number) for number in draw.main_numbers]
        special_snapshot = tracking_engine.get_tracking_snapshot_special(tracking_state or {}, draw.special)

        feature_row = {
            "draw_id": draw.draw_id,
            "weekday_text": draw.weekday_text,
            "draw_date": draw.draw_date.strftime("%d/%m/%Y"),
            "weekday": draw.draw_date.weekday(),
            "day_of_month": draw.draw_date.day,
            "day_of_month_is_odd": int(draw.draw_date.day % 2 == 1),
            "time_slot": draw.draw_time if time_slot_enabled else None,
            "sum_main": sum(draw.main_numbers),
            "mean_main": sum(draw.main_numbers) / 6.0,
            "min_main": min(draw.main_numbers),
            "max_main": max(draw.main_numbers),
            "range_main": max(draw.main_numbers) - min(draw.main_numbers),
            "special": draw.special,
            "special_repeat_previous": int(previous_draw is not None and draw.special == previous_draw.special),
            "special_in_recent_window": int(draw.special in recent_specials),
            "overlap_previous_draw": len(set(draw.main_numbers) & set(previous_draw.main_numbers)) if previous_draw else 0,
            "overlap_previous_same_weekday_draw": len(set(draw.main_numbers) & set(same_weekday_draw.main_numbers)) if same_weekday_draw else 0,
            "overlap_recent_window": len(set(draw.main_numbers) & recent_union),
            "tracking_keep_mean": mean(snapshot["keep_mark_score"] for snapshot in tracking_snapshots) if tracking_snapshots else 0.0,
            "tracking_hot_mean": mean(snapshot["hot_score"] for snapshot in tracking_snapshots) if tracking_snapshots else 0.0,
            "tracking_penalty_mean": mean(snapshot["miss_penalty_score"] for snapshot in tracking_snapshots) if tracking_snapshots else 0.0,
            "special_keep_score": special_snapshot["special_keep_score"],
            "special_hot_score": special_snapshot["special_hot_score"],
            "special_penalty_score": special_snapshot["special_penalty_score"],
        }
        for number_index, value in enumerate(draw.main_numbers, start=1):
            feature_row[f"n{number_index}"] = value
            feature_row[f"p{number_index}"] = value
        for gap_index in range(5):
            feature_row[f"gap{gap_index + 1}{gap_index + 2}"] = draw.main_numbers[gap_index + 1] - draw.main_numbers[gap_index]
        feature_row.update(modulo_description)
        feature_row.update(special_description)
        rows.append(feature_row)
        previous_same_weekday[draw.draw_date.weekday()] = draw
    return rows


def build_prediction_context(
    draws: list[Any],
    tracking_state: dict[str, Any],
    predictor_config: dict[str, Any],
    target_weekday: int,
    time_slot_enabled: bool = False,
    use_mod11: bool = True,
    target_time: str | None = None,
) -> dict[str, Any]:
    windows = dict(predictor_config.get("windows") or {})
    primary_window = int(windows.get("primary", 4))
    secondary_window = int(windows.get("secondary", 10))
    weekday_window = int(windows.get("weekday", 18))
    recent_weights = list(predictor_config.get("recent_weights") or [1, 2, 3, 4])

    recent_primary = list(draws[-primary_window:])
    recent_secondary = list(draws[-secondary_window:])
    same_weekday_draws = [draw for draw in draws if draw.draw_date.weekday() == target_weekday][-weekday_window:]

    recent_frequency = build_number_frequency(recent_primary, weights=recent_weights[-len(recent_primary):])
    secondary_frequency = build_number_frequency(recent_secondary)
    weekday_frequency = build_number_frequency(same_weekday_draws)
    special_recent_frequency = build_special_frequency(recent_primary, weights=recent_weights[-len(recent_primary):])
    special_secondary_frequency = build_special_frequency(recent_secondary)
    special_weekday_frequency = build_special_frequency(same_weekday_draws)
    position_profile = _position_profile(recent_secondary or draws)

    hot_numbers = [number for number, _score in sorted(secondary_frequency.items(), key=lambda item: item[1], reverse=True)[:10]]
    hot_special_values = [number for number, _score in sorted(special_secondary_frequency.items(), key=lambda item: item[1], reverse=True)[:8]]
    recent_union = set(number for draw in recent_primary for number in draw.main_numbers)
    weekday_presence = Counter(number for draw in same_weekday_draws for number in draw.main_numbers)
    weekday_special_presence = Counter(draw.special for draw in same_weekday_draws)

    feature_snapshot_window = max(24, secondary_window * 2)
    feature_rows = build_feature_rows(
        draws[-feature_snapshot_window:],
        tracking_state=tracking_state,
        use_mod11=use_mod11,
        time_slot_enabled=time_slot_enabled,
    )
    modulo_context = modulo_engine.build_recent_modulo_context(recent_secondary, window=len(recent_secondary), use_mod11=use_mod11)
    recent_sums = [sum(draw.main_numbers) for draw in recent_secondary] or [175]
    recent_ranges = [max(draw.main_numbers) - min(draw.main_numbers) for draw in recent_secondary] or [34]

    return {
        "feature_rows": feature_rows,
        "recent_primary": recent_primary,
        "recent_secondary": recent_secondary,
        "same_weekday_draws": same_weekday_draws,
        "recent_frequency": recent_frequency,
        "secondary_frequency": secondary_frequency,
        "weekday_frequency": weekday_frequency,
        "special_recent_frequency": special_recent_frequency,
        "special_secondary_frequency": special_secondary_frequency,
        "special_weekday_frequency": special_weekday_frequency,
        "same_weekday_overlap": {
            number: weekday_presence[number] / max(1, len(same_weekday_draws))
            for number in range(1, 56)
        },
        "same_weekday_special_share": {
            number: weekday_special_presence[number] / max(1, len(same_weekday_draws))
            for number in range(1, 56)
        },
        "position_profile": position_profile,
        "recent_overlap_union": {number: int(number in recent_union) for number in range(1, 56)},
        "recent_special_values": [draw.special for draw in recent_secondary],
        "hot_numbers": hot_numbers,
        "hot_special_values": hot_special_values,
        "last_draw": draws[-1] if draws else None,
        "average_sum_recent": mean(recent_sums),
        "average_range_recent": mean(recent_ranges),
        "average_overlap_recent": _average_overlap(recent_secondary),
        "special_repeat_rate_recent": _special_repeat_rate(recent_secondary),
        "special_reset_rate_recent": _special_reset_rate(recent_secondary),
        "modulo_context": modulo_context,
        "target_time": target_time,
    }
