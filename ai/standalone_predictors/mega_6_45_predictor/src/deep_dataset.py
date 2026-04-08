from __future__ import annotations

from statistics import mean
from typing import Any

import numpy as np

from src import feature_engineering, regime_engine


FEATURE_SCHEMA_VERSION = "mega_6_45_deep_features_v1"
TIME_SLOT_ORDER = ["13:00", "21:00"]


def _multi_hot(numbers: list[int] | tuple[int, ...], size: int) -> list[float]:
    payload = [0.0] * size
    for number in numbers:
        if 1 <= int(number) <= size:
            payload[int(number) - 1] = 1.0
    return payload


def _one_hot(index: int | None, size: int) -> list[float]:
    payload = [0.0] * size
    if index is not None and 0 <= int(index) < size:
        payload[int(index)] = 1.0
    return payload


def _count_residues(numbers: list[int] | tuple[int, ...], modulus: int) -> list[float]:
    counts = [0.0] * modulus
    scoped = [int(number) for number in numbers]
    total = float(max(1, len(scoped)))
    for number in scoped:
        counts[number % modulus] += 1.0 / total
    return counts


def _find_previous_same_weekday(draws: list[Any], index: int) -> Any | None:
    current = draws[index]
    target_weekday = current.draw_date.weekday()
    for cursor in range(index - 1, -1, -1):
        candidate = draws[cursor]
        if candidate.draw_date.weekday() == target_weekday:
            return candidate
    return None


def _recent_frequency(draws: list[Any], number_max: int) -> dict[int, float]:
    if not draws:
        return {number: 0.0 for number in range(1, number_max + 1)}
    return feature_engineering.build_number_frequency(draws)


def _step_features(draws: list[Any], index: int, time_slot_enabled: bool) -> tuple[list[float], list[str]]:
    draw = draws[index]
    previous_draw = draws[index - 1] if index > 0 else None
    previous_same_weekday = _find_previous_same_weekday(draws, index)
    recent_primary = draws[max(0, index - 4) : index]
    recent_secondary = draws[max(0, index - 10) : index]
    recent_union = {number for scoped in recent_primary for number in scoped.main_numbers}
    recent_frequency = _recent_frequency(recent_secondary, 45)

    values: list[float] = []
    names: list[str] = []

    for position, value in enumerate(_multi_hot(draw.main_numbers, 45), start=1):
        names.append(f"main_hot_{position}")
        values.append(float(value))

    for offset, number in enumerate(draw.main_numbers, start=1):
        names.append(f"position_{offset}")
        values.append(float(number) / 45.0)

    for offset in range(5):
        names.append(f"gap_{offset + 1}_{offset + 2}")
        values.append(float(draw.main_numbers[offset + 1] - draw.main_numbers[offset]) / 45.0)

    summary_values = {
        "sum_main": sum(draw.main_numbers) / (45.0 * 6.0),
        "mean_main": (sum(draw.main_numbers) / 6.0) / 45.0,
        "min_main": min(draw.main_numbers) / 45.0,
        "max_main": max(draw.main_numbers) / 45.0,
        "range_main": (max(draw.main_numbers) - min(draw.main_numbers)) / 45.0,
        "day_of_month": draw.draw_date.day / 31.0,
        "day_of_month_is_odd": float(draw.draw_date.day % 2 == 1),
    }
    for key, value in summary_values.items():
        names.append(key)
        values.append(float(value))

    for weekday_index, value in enumerate(_one_hot(draw.draw_date.weekday(), 7)):
        names.append(f"weekday_{weekday_index}")
        values.append(float(value))

    slot_index = TIME_SLOT_ORDER.index(draw.draw_time) if time_slot_enabled and draw.draw_time in TIME_SLOT_ORDER else None
    for slot_pos, value in enumerate(_one_hot(slot_index, len(TIME_SLOT_ORDER))):
        names.append(f"time_slot_{slot_pos}")
        values.append(float(value))

    for modulus in (2, 3, 5, 10, 9):
        for residue, value in enumerate(_count_residues(draw.main_numbers, modulus)):
            names.append(f"mod{modulus}_{residue}")
            values.append(float(value))

    overlap_previous = len(set(draw.main_numbers) & set(previous_draw.main_numbers)) / 6.0 if previous_draw else 0.0
    overlap_same_weekday = len(set(draw.main_numbers) & set(previous_same_weekday.main_numbers)) / 6.0 if previous_same_weekday else 0.0
    overlap_recent = len(set(draw.main_numbers) & recent_union) / 6.0 if recent_union else 0.0
    recent_activity_mean = mean(recent_frequency.get(number, 0.0) for number in draw.main_numbers) if draw.main_numbers else 0.0
    summary_overlap = {
        "overlap_previous_draw": overlap_previous,
        "overlap_previous_same_weekday_draw": overlap_same_weekday,
        "overlap_recent_window": overlap_recent,
        "recent_activity_mean": recent_activity_mean,
        "recent_window_fill": min(1.0, len(recent_secondary) / 10.0),
    }
    for key, value in summary_overlap.items():
        names.append(key)
        values.append(float(value))
    return values, names


def _regime_target(history: list[Any]) -> int:
    recent_frequency = feature_engineering.build_number_frequency(history[-10:]) if history else {}
    regime = regime_engine.detect_regime(history, recent_frequency=recent_frequency).get("regime", "neutral")
    return int({"reset": 0, "neutral": 1, "continuation": 2}.get(str(regime), 1))


def build_training_samples(
    draws: list[Any],
    predictor_config: dict[str, Any],
    time_slot_enabled: bool = False,
    sequence_length: int | None = None,
) -> dict[str, Any]:
    config_sequence_length = int(((predictor_config.get("deep_training") or {}).get("sequence_length", 10)) or 10)
    sequence_length = max(4, int(sequence_length or config_sequence_length))
    if len(draws) <= sequence_length:
        raise ValueError("Not enough Mega 6/45 draws to build deep-learning sequence samples.")

    feature_cache = []
    feature_names: list[str] | None = None
    for index in range(len(draws)):
        feature_values, current_feature_names = _step_features(draws, index, time_slot_enabled=time_slot_enabled)
        if feature_names is None:
            feature_names = list(current_feature_names)
        feature_cache.append(feature_values)

    samples = []
    targets_main = []
    targets_regime = []
    for target_index in range(sequence_length, len(draws)):
        history = draws[target_index - sequence_length : target_index]
        samples.append(np.asarray(feature_cache[target_index - sequence_length : target_index], dtype=np.float32))
        targets_main.append(np.asarray(_multi_hot(draws[target_index].main_numbers, 45), dtype=np.float32))
        targets_regime.append(_regime_target(history))

    return {
        "features": np.asarray(samples, dtype=np.float32),
        "targets_main": np.asarray(targets_main, dtype=np.float32),
        "targets_extra": None,
        "targets_regime": np.asarray(targets_regime, dtype=np.int64),
        "feature_names": list(feature_names or []),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "sequence_length": sequence_length,
        "time_slot_enabled": bool(time_slot_enabled),
    }


def build_inference_sample(
    draws: list[Any],
    predictor_config: dict[str, Any],
    time_slot_enabled: bool = False,
    sequence_length: int | None = None,
) -> dict[str, Any]:
    config_sequence_length = int(((predictor_config.get("deep_training") or {}).get("sequence_length", 10)) or 10)
    sequence_length = max(4, int(sequence_length or config_sequence_length))
    if len(draws) < sequence_length:
        raise ValueError("Not enough Mega 6/45 draws to build the deep inference sequence.")

    feature_cache = []
    feature_names: list[str] | None = None
    for index in range(len(draws)):
        feature_values, current_feature_names = _step_features(draws, index, time_slot_enabled=time_slot_enabled)
        if feature_names is None:
            feature_names = list(current_feature_names)
        feature_cache.append(feature_values)

    features = np.asarray([feature_cache[-sequence_length:]], dtype=np.float32)
    return {
        "features": features,
        "feature_names": list(feature_names or []),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "sequence_length": sequence_length,
        "time_slot_enabled": bool(time_slot_enabled),
    }
