from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import Any

import numpy as np


FEATURE_SCHEMA_VERSION = "loto_5_35_deep_features_v1"
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


def _find_previous_same_weekday(draws: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    current = draws[index]
    target_weekday = int(current.get("weekday", -1))
    for cursor in range(index - 1, -1, -1):
        candidate = draws[cursor]
        if int(candidate.get("weekday", -2)) == target_weekday:
            return candidate
    return None


def _recent_number_frequency(draws: list[dict[str, Any]], number_max: int) -> dict[int, float]:
    counts = Counter()
    total = 0
    for draw in draws:
        for number in list(draw.get("main") or []):
            counts[int(number)] += 1
            total += 1
    return {number: counts[number] / max(1, total) for number in range(1, number_max + 1)}


def _recent_bonus_frequency(draws: list[dict[str, Any]], bonus_max: int) -> dict[int, float]:
    counts = Counter(int(draw.get("special", 0)) for draw in draws if isinstance(draw.get("special"), int))
    total = sum(counts.values())
    return {number: counts[number] / max(1, total) for number in range(1, bonus_max + 1)}


def _step_features(draws: list[dict[str, Any]], index: int) -> tuple[list[float], list[str]]:
    draw = draws[index]
    main_numbers = list(draw.get("main") or [])
    previous_draw = draws[index - 1] if index > 0 else None
    previous_same_weekday = _find_previous_same_weekday(draws, index)
    recent_primary = draws[max(0, index - 4) : index]
    recent_secondary = draws[max(0, index - 10) : index]
    recent_union = {number for scoped in recent_primary for number in list(scoped.get("main") or [])}
    recent_bonus_values = [int(scoped.get("special")) for scoped in recent_primary if isinstance(scoped.get("special"), int)]
    recent_number_frequency = _recent_number_frequency(recent_secondary, 35)
    recent_bonus_frequency = _recent_bonus_frequency(recent_secondary, 12)

    values: list[float] = []
    names: list[str] = []

    for position, value in enumerate(_multi_hot(main_numbers, 35), start=1):
        names.append(f"main_hot_{position}")
        values.append(float(value))
    for position, value in enumerate(_one_hot(int(draw.get("special", 0)) - 1, 12), start=1):
        names.append(f"bonus_hot_{position}")
        values.append(float(value))

    for offset, number in enumerate(main_numbers, start=1):
        names.append(f"position_{offset}")
        values.append(float(number) / 35.0)

    for offset in range(4):
        names.append(f"gap_{offset + 1}_{offset + 2}")
        values.append(float(main_numbers[offset + 1] - main_numbers[offset]) / 35.0)

    summary_values = {
        "sum_main": sum(main_numbers) / (35.0 * 5.0),
        "mean_main": (sum(main_numbers) / 5.0) / 35.0,
        "min_main": min(main_numbers) / 35.0,
        "max_main": max(main_numbers) / 35.0,
        "range_main": (max(main_numbers) - min(main_numbers)) / 35.0,
        "bonus_number": float(draw.get("special", 0) or 0) / 12.0,
        "day_of_month": float(draw.get("date_obj").day) / 31.0 if draw.get("date_obj") else 0.0,
        "day_of_month_is_odd": float((draw.get("date_obj").day % 2 == 1) if draw.get("date_obj") else 0.0),
    }
    for key, value in summary_values.items():
        names.append(key)
        values.append(float(value))

    weekday_index = int(draw.get("weekday", -1))
    for weekday_position, value in enumerate(_one_hot(weekday_index, 7)):
        names.append(f"weekday_{weekday_position}")
        values.append(float(value))

    slot_text = str(draw.get("slot", "")).strip()
    slot_index = TIME_SLOT_ORDER.index(slot_text) if slot_text in TIME_SLOT_ORDER else None
    for slot_position, value in enumerate(_one_hot(slot_index, len(TIME_SLOT_ORDER))):
        names.append(f"time_slot_{slot_position}")
        values.append(float(value))

    for modulus in (2, 3, 5, 10):
        for residue, value in enumerate(_count_residues(main_numbers, modulus)):
            names.append(f"mod{modulus}_{residue}")
            values.append(float(value))

    bonus_value = int(draw.get("special", 0) or 0)
    bonus_modulo_values = {
        "bonus_mod2": float(bonus_value % 2),
        "bonus_mod3": float(bonus_value % 3) / 2.0,
        "bonus_mod5": float(bonus_value % 5) / 4.0,
        "bonus_mod10": float(bonus_value % 10) / 9.0,
    }
    for key, value in bonus_modulo_values.items():
        names.append(key)
        values.append(float(value))

    previous_main = set(previous_draw.get("main") or []) if previous_draw else set()
    same_weekday_main = set(previous_same_weekday.get("main") or []) if previous_same_weekday else set()
    overlap_values = {
        "overlap_previous_draw": len(set(main_numbers) & previous_main) / 5.0 if previous_draw else 0.0,
        "overlap_previous_same_weekday_draw": len(set(main_numbers) & same_weekday_main) / 5.0 if previous_same_weekday else 0.0,
        "overlap_recent_window": len(set(main_numbers) & recent_union) / 5.0 if recent_union else 0.0,
        "recent_main_activity_mean": mean(recent_number_frequency.get(number, 0.0) for number in main_numbers) if main_numbers else 0.0,
        "recent_bonus_activity": recent_bonus_frequency.get(bonus_value, 0.0),
        "bonus_repeat_recent": float(bonus_value in set(recent_bonus_values)),
        "recent_window_fill": min(1.0, len(recent_secondary) / 10.0),
    }
    for key, value in overlap_values.items():
        names.append(key)
        values.append(float(value))
    return values, names


def _regime_target(history: list[dict[str, Any]], target_draw: dict[str, Any]) -> int:
    latest = history[-1] if history else {}
    latest_main = set(latest.get("main") or [])
    target_main = set(target_draw.get("main") or [])
    overlap = len(latest_main & target_main)
    same_day_follow_up = bool(latest) and latest.get("date") == target_draw.get("date") and latest.get("slot") != target_draw.get("slot")
    if same_day_follow_up or overlap == 0:
        return 0
    if overlap >= 2:
        return 2
    return 1


def build_training_samples(
    draws: list[dict[str, Any]],
    config_payload: dict[str, Any],
    sequence_length: int | None = None,
) -> dict[str, Any]:
    deep_training = dict(config_payload.get("deep_training") or {})
    sequence_length = max(4, int(sequence_length or deep_training.get("sequence_length", 10) or 10))
    if len(draws) <= sequence_length:
        raise ValueError("Not enough Loto 5/35 draws to build deep-learning sequence samples.")

    feature_cache = []
    feature_names: list[str] | None = None
    for index in range(len(draws)):
        feature_values, current_feature_names = _step_features(draws, index)
        if feature_names is None:
            feature_names = list(current_feature_names)
        feature_cache.append(feature_values)

    samples = []
    targets_main = []
    targets_bonus = []
    targets_regime = []
    for target_index in range(sequence_length, len(draws)):
        history = draws[target_index - sequence_length : target_index]
        target_draw = draws[target_index]
        samples.append(np.asarray(feature_cache[target_index - sequence_length : target_index], dtype=np.float32))
        targets_main.append(np.asarray(_multi_hot(target_draw.get("main") or [], 35), dtype=np.float32))
        targets_bonus.append(int(target_draw.get("special", 1)) - 1)
        targets_regime.append(_regime_target(history, target_draw))

    return {
        "features": np.asarray(samples, dtype=np.float32),
        "targets_main": np.asarray(targets_main, dtype=np.float32),
        "targets_extra": np.asarray(targets_bonus, dtype=np.int64),
        "targets_regime": np.asarray(targets_regime, dtype=np.int64),
        "feature_names": list(feature_names or []),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "sequence_length": sequence_length,
        "time_slot_enabled": True,
    }


def build_inference_sample(
    draws: list[dict[str, Any]],
    config_payload: dict[str, Any],
    sequence_length: int | None = None,
) -> dict[str, Any]:
    deep_training = dict(config_payload.get("deep_training") or {})
    sequence_length = max(4, int(sequence_length or deep_training.get("sequence_length", 10) or 10))
    if len(draws) < sequence_length:
        raise ValueError("Not enough Loto 5/35 draws to build the deep inference sequence.")

    feature_cache = []
    feature_names: list[str] | None = None
    for index in range(len(draws)):
        feature_values, current_feature_names = _step_features(draws, index)
        if feature_names is None:
            feature_names = list(current_feature_names)
        feature_cache.append(feature_values)

    return {
        "features": np.asarray([feature_cache[-sequence_length:]], dtype=np.float32),
        "feature_names": list(feature_names or []),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "sequence_length": sequence_length,
        "time_slot_enabled": True,
    }
