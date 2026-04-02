from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable


DEFAULT_WEIGHTS = (0.30, 0.20, 0.30, 0.20)
DEFAULT_CO_TOP_K = 5
NEUTRAL_SCORE = 0.5


@dataclass(frozen=True)
class NumberScoringConfig:
    recent_window: int
    weights: tuple[float, float, float, float]
    co_top_k: int = DEFAULT_CO_TOP_K


def normalize_weights(raw_weights) -> tuple[float, float, float, float]:
    if raw_weights is None:
        return DEFAULT_WEIGHTS
    if isinstance(raw_weights, str):
        parts = [part.strip() for part in raw_weights.split(",") if part.strip()]
    else:
        parts = [str(part).strip() for part in list(raw_weights or []) if str(part).strip()]
    if len(parts) != 4:
        raise ValueError("weights phải gồm đúng 4 giá trị a,b,c,d.")
    try:
        values = tuple(float(part) for part in parts)
    except ValueError as exc:
        raise ValueError("weights phải là các số hợp lệ.") from exc
    if any(value < 0 for value in values):
        raise ValueError("weights không được âm.")
    total = sum(values)
    if total <= 0:
        raise ValueError("Tổng weights phải lớn hơn 0.")
    normalized = tuple(value / total for value in values)
    if abs(sum(normalized) - 1.0) > 1e-9:
        raise ValueError("weights không hợp lệ.")
    return normalized


def clamp_positive_int(raw_value, field_name: str, minimum: int = 1) -> int:
    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} phải là số nguyên dương.") from exc
    if value < minimum:
        raise ValueError(f"{field_name} phải lớn hơn hoặc bằng {minimum}.")
    return value


def _normalize_flat_aware(values_by_number: dict[int, float], keep_unit_scale: bool = False) -> dict[int, float]:
    if not values_by_number:
        return {}
    values = list(values_by_number.values())
    min_value = min(values)
    max_value = max(values)
    if abs(max_value - min_value) <= 1e-12:
        return {number: NEUTRAL_SCORE for number in values_by_number}
    if keep_unit_scale:
        return {number: max(0.0, min(1.0, float(value))) for number, value in values_by_number.items()}
    span = max_value - min_value
    return {number: (float(value) - min_value) / span for number, value in values_by_number.items()}


def build_number_scoring_rows(
    draws: Iterable[dict],
    universe: Iterable[int],
    recent_window: int,
    weights,
    co_top_k: int = DEFAULT_CO_TOP_K,
    number_formatter: Callable[[int], str] | None = None,
):
    draw_list = list(draws or [])
    if not draw_list:
        raise ValueError("Không có dữ liệu lịch sử để chấm điểm.")
    universe_values = sorted({int(value) for value in universe})
    if not universe_values:
        raise ValueError("Universe rỗng, không thể chấm điểm.")
    recent_window = min(len(draw_list), clamp_positive_int(recent_window, "recent_window"))
    co_top_k = clamp_positive_int(co_top_k, "co_top_k")
    weights = normalize_weights(weights)
    format_number = number_formatter or (lambda value: str(int(value)))

    total_draws = len(draw_list)
    recent_draws = draw_list[-recent_window:]

    frequency_count = {number: 0 for number in universe_values}
    recent_count = {number: 0 for number in universe_values}
    last_seen_index = {number: -1 for number in universe_values}
    pair_counts = {number: {} for number in universe_values}

    for draw_index, draw in enumerate(draw_list):
        numbers = sorted({int(value) for value in list(draw.get("numbers") or []) if isinstance(value, (int, float, str)) and str(value).strip()})
        for number in numbers:
            if number not in frequency_count:
                continue
            frequency_count[number] += 1
            last_seen_index[number] = draw_index
        for left in numbers:
            if left not in pair_counts:
                continue
            row = pair_counts[left]
            for right in numbers:
                if left == right or right not in frequency_count:
                    continue
                row[right] = row.get(right, 0) + 1

    for draw in recent_draws:
        numbers = sorted({int(value) for value in list(draw.get("numbers") or []) if isinstance(value, (int, float, str)) and str(value).strip()})
        for number in numbers:
            if number in recent_count:
                recent_count[number] += 1

    delays = {}
    raw_frequency = {}
    raw_delay = {}
    raw_trend = {}
    raw_co = {}

    max_delay = 1
    for number in universe_values:
        last_seen = last_seen_index[number]
        delay = total_draws if last_seen < 0 else max(0, total_draws - 1 - last_seen)
        delays[number] = delay
        max_delay = max(max_delay, delay)

    for number in universe_values:
        count_all = frequency_count[number]
        count_recent = recent_count[number]
        raw_frequency[number] = float(count_all) / float(total_draws)
        raw_delay[number] = float(delays[number]) / float(max_delay)
        long_rate = float(count_all) / float(total_draws)
        recent_rate = float(count_recent) / float(recent_window)
        raw_trend[number] = recent_rate - long_rate

        if count_all <= 0:
            raw_co[number] = 0.0
            continue
        strengths = sorted(
            (
                float(pair_count) / float(count_all)
                for partner, pair_count in (pair_counts.get(number) or {}).items()
                if partner != number and pair_count > 0
            ),
            reverse=True,
        )
        if not strengths:
            raw_co[number] = 0.0
            continue
        top_strengths = strengths[:co_top_k]
        raw_co[number] = sum(top_strengths) / float(len(top_strengths))

    frequency_scores = _normalize_flat_aware(raw_frequency, keep_unit_scale=True)
    delay_scores = _normalize_flat_aware(raw_delay, keep_unit_scale=True)
    trend_scores = _normalize_flat_aware(raw_trend, keep_unit_scale=False)
    co_scores = _normalize_flat_aware(raw_co, keep_unit_scale=True)

    rows = []
    a, b, c, d = weights
    for number in universe_values:
        score_value = (
            a * frequency_scores[number]
            + b * delay_scores[number]
            + c * trend_scores[number]
            + d * co_scores[number]
        )
        rows.append({
            "number": format_number(number),
            "numberValue": number,
            "frequencyCount": int(frequency_count[number]),
            "recentCount": int(recent_count[number]),
            "currentDelay": int(delays[number]),
            "F_i": round(float(frequency_scores[number]), 6),
            "D_i": round(float(delay_scores[number]), 6),
            "T_i": round(float(trend_scores[number]), 6),
            "C_i": round(float(co_scores[number]), 6),
            "Score_i": round(float(score_value), 6),
        })
    rows.sort(key=lambda item: (-float(item["Score_i"]), int(item["numberValue"])))
    return rows


def backtest_number_scoring(
    draws: Iterable[dict],
    universe: Iterable[int],
    recent_window: int,
    weights,
    co_top_k: int,
    top_k: int,
    min_history: int,
    number_formatter: Callable[[int], str] | None = None,
):
    draw_list = list(draws or [])
    if len(draw_list) <= min_history:
        return {
            "samples": 0,
            "topK": int(top_k),
            "avgHits": 0.0,
            "avgHitRate": 0.0,
            "hitDistribution": {},
            "lastWindowSummary": [],
        }
    recent_window = clamp_positive_int(recent_window, "recent_window")
    top_k = clamp_positive_int(top_k, "backtest_top_k")
    min_history = clamp_positive_int(min_history, "min_history")
    hit_counts = []
    last_window_summary = []
    distribution = {}
    format_number = number_formatter or (lambda value: str(int(value)))

    for index in range(min_history, len(draw_list)):
        history_draws = draw_list[:index]
        target_draw = draw_list[index]
        rows = build_number_scoring_rows(
            history_draws,
            universe,
            recent_window=recent_window,
            weights=weights,
            co_top_k=co_top_k,
            number_formatter=format_number,
        )
        predicted = rows[:top_k]
        predicted_values = {int(item["numberValue"]) for item in predicted}
        actual_values = {int(value) for value in list(target_draw.get("numbers") or [])}
        hit_count = len(predicted_values & actual_values)
        hit_rate = float(hit_count) / float(top_k)
        hit_counts.append(hit_count)
        distribution[str(hit_count)] = int(distribution.get(str(hit_count), 0)) + 1
        last_window_summary.append({
            "drawId": str(target_draw.get("draw_id", "")),
            "drawDate": str(target_draw.get("draw_date", "")),
            "hitCount": int(hit_count),
            "hitRate": round(hit_rate, 6),
            "topNumbers": [item["number"] for item in predicted],
        })
        if len(last_window_summary) > 5:
            last_window_summary = last_window_summary[-5:]

    if not hit_counts:
        return {
            "samples": 0,
            "topK": int(top_k),
            "avgHits": 0.0,
            "avgHitRate": 0.0,
            "hitDistribution": distribution,
            "lastWindowSummary": last_window_summary,
        }
    avg_hits = sum(hit_counts) / float(len(hit_counts))
    avg_hit_rate = avg_hits / float(top_k)
    return {
        "samples": len(hit_counts),
        "topK": int(top_k),
        "avgHits": round(avg_hits, 4),
        "avgHitRate": round(avg_hit_rate, 6),
        "hitDistribution": distribution,
        "lastWindowSummary": last_window_summary,
    }
