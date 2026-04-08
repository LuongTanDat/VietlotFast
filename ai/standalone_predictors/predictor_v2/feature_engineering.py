from __future__ import annotations

from collections import defaultdict

from predictor_v2 import modulo_engine, pair_engine, tracking_engine


def _normalize_score_map(raw_map):
    values = [float(value) for value in raw_map.values()] if raw_map else []
    if not values:
        return {}
    min_value = min(values)
    max_value = max(values)
    if abs(max_value - min_value) <= 1e-9:
        return {key: 0.5 for key in raw_map}
    span = max_value - min_value
    return {key: (float(value) - min_value) / span for key, value in raw_map.items()}


def _window_frequency(draws, window_size, selector):
    counts = defaultdict(float)
    sample = list(draws or [])[-max(1, int(window_size or 1)) :]
    denominator = float(max(1, len(sample)))
    for draw in sample:
        for value in selector(draw):
            counts[int(value)] += 1.0 / denominator
    return counts


def _build_position_profile(draws, slot):
    position_counts = [defaultdict(int) for _ in range(5)]
    total = 0
    for draw in list(draws or []):
        if slot and str(draw.get("slot", "")) != slot:
            continue
        main = sorted(int(value) for value in list(draw.get("main") or []))
        if len(main) != 5:
            continue
        total += 1
        for index, value in enumerate(main):
            position_counts[index][value] += 1
    return position_counts, total


def _position_score(number, position_profile, total):
    if total <= 0:
        return 0.0
    scores = [float(bucket.get(number, 0)) / float(total) for bucket in position_profile]
    return sum(scores) / max(1, len(scores))


def _gap_scores(draws, max_number, selector):
    last_seen = {number: -1 for number in range(1, max_number + 1)}
    total = len(draws or [])
    for index, draw in enumerate(draws or []):
        for value in selector(draw):
            last_seen[int(value)] = index
    scores = {}
    for number in range(1, max_number + 1):
        seen_index = last_seen.get(number, -1)
        delay = total if seen_index < 0 else max(0, total - 1 - seen_index)
        scores[number] = min(1.0, float(delay) / max(8.0, total * 0.35))
    return scores


def _slot_draws(draws, slot, limit):
    return [draw for draw in draws if str(draw.get("slot", "")) == slot][-max(1, int(limit or 1)) :]


def _weekday_draws(draws, weekday, limit):
    return [draw for draw in draws if draw.get("weekday") == weekday][-max(1, int(limit or 1)) :]


def build_feature_snapshot(draws, target, tracking_state, config_payload):
    history_limits = dict((config_payload or {}).get("history_limits") or {})
    heuristic_weights = dict(((config_payload or {}).get("heuristic_weights") or {}).get("main") or {})
    bonus_weights = dict(((config_payload or {}).get("heuristic_weights") or {}).get("bonus") or {})
    recent_windows = dict((config_payload or {}).get("recent_windows") or {})
    latest_draw = target.get("latest_actual_draw") or {}
    latest_main = set(int(value) for value in list(latest_draw.get("main") or []))
    slot = str(target.get("target_slot", "")).strip()
    weekday = target.get("target_weekday")
    slot_history = _slot_draws(draws, slot, history_limits.get("slot", 24))
    weekday_history = _weekday_draws(draws, weekday, history_limits.get("weekday", 18))
    position_profile, position_total = _build_position_profile(slot_history or draws, slot)

    recent_main_short = _window_frequency(draws, recent_windows.get("main", [6])[0], lambda draw: draw.get("main") or [])
    recent_main_medium = _window_frequency(draws, recent_windows.get("main", [6, 12])[1], lambda draw: draw.get("main") or [])
    recent_main_long = _window_frequency(draws, recent_windows.get("main", [6, 12, 24])[2], lambda draw: draw.get("main") or [])
    slot_main_counts = _window_frequency(slot_history, len(slot_history) or 1, lambda draw: draw.get("main") or [])
    weekday_main_counts = _window_frequency(weekday_history, len(weekday_history) or 1, lambda draw: draw.get("main") or [])
    gap_main_scores = _gap_scores(draws, 35, lambda draw: draw.get("main") or [])

    recent_bonus_short = _window_frequency(draws, recent_windows.get("bonus", [8])[0], lambda draw: [draw.get("special")] if isinstance(draw.get("special"), int) else [])
    recent_bonus_medium = _window_frequency(draws, recent_windows.get("bonus", [8, 16])[1], lambda draw: [draw.get("special")] if isinstance(draw.get("special"), int) else [])
    slot_bonus_counts = _window_frequency(slot_history, len(slot_history) or 1, lambda draw: [draw.get("special")] if isinstance(draw.get("special"), int) else [])
    weekday_bonus_counts = _window_frequency(weekday_history, len(weekday_history) or 1, lambda draw: [draw.get("special")] if isinstance(draw.get("special"), int) else [])
    gap_bonus_scores = _gap_scores(draws, 12, lambda draw: [draw.get("special")] if isinstance(draw.get("special"), int) else [])

    slot_hot = sorted(slot_main_counts, key=lambda number: (-slot_main_counts[number], number))
    weekday_hot = sorted(weekday_main_counts, key=lambda number: (-weekday_main_counts[number], number))
    kept_numbers = list((tracking_state or {}).get("kept_numbers") or [])
    anchors = []
    for source in (kept_numbers, slot_hot[:4], weekday_hot[:4]):
        for value in source:
            candidate = int(value)
            if candidate not in anchors:
                anchors.append(candidate)
    pair_context = pair_engine.build_pair_context(draws, history_limits.get("pair", 96))
    main_modulo_context = modulo_engine.build_modulo_context(draws, target, lambda draw: draw.get("main") or [])
    bonus_modulo_context = modulo_engine.build_modulo_context(
        draws,
        target,
        lambda draw: [draw.get("special")] if isinstance(draw.get("special"), int) else [],
    )

    main_raw = {}
    main_features = {}
    for number in range(1, 36):
        features = {
            "recent": (float(recent_main_short.get(number, 0.0)) * 0.45)
            + (float(recent_main_medium.get(number, 0.0)) * 0.35)
            + (float(recent_main_long.get(number, 0.0)) * 0.20),
            "slot": float(slot_main_counts.get(number, 0.0)),
            "weekday": float(weekday_main_counts.get(number, 0.0)),
            "modulo": modulo_engine.score_candidate(number, main_modulo_context),
            "pair": pair_engine.score_candidate_pairing(number, anchors, pair_context),
            "gap": float(gap_main_scores.get(number, 0.0)),
            "position": _position_score(number, position_profile, position_total),
            "overlap": 1.0 if number in latest_main else 0.0,
            "anti_pair": pair_engine.score_candidate_anti_pair(number, anchors, pair_context),
            "tracking": tracking_engine.get_tracking_score(tracking_state, number, "main"),
        }
        main_features[number] = features
        main_raw[number] = (
            features["recent"] * float(heuristic_weights.get("recent", 0.28))
            + features["slot"] * float(heuristic_weights.get("slot", 0.16))
            + features["weekday"] * float(heuristic_weights.get("weekday", 0.10))
            + features["modulo"] * float(heuristic_weights.get("modulo", 0.12))
            + features["pair"] * float(heuristic_weights.get("pair", 0.10))
            + features["gap"] * float(heuristic_weights.get("gap", 0.08))
            + features["position"] * float(heuristic_weights.get("position", 0.08))
            + ((1.0 - features["overlap"]) * float(heuristic_weights.get("overlap", 0.08)))
            - (features["anti_pair"] * 0.12)
        )

    bonus_raw = {}
    bonus_features = {}
    for number in range(1, 13):
        features = {
            "recent": (float(recent_bonus_short.get(number, 0.0)) * 0.55) + (float(recent_bonus_medium.get(number, 0.0)) * 0.45),
            "slot": float(slot_bonus_counts.get(number, 0.0)),
            "weekday": float(weekday_bonus_counts.get(number, 0.0)),
            "modulo": modulo_engine.score_candidate(number, bonus_modulo_context),
            "gap": float(gap_bonus_scores.get(number, 0.0)),
            "overlap": 1.0 if number == latest_draw.get("special") else 0.0,
            "tracking": tracking_engine.get_tracking_score(tracking_state, number, "bonus"),
        }
        bonus_features[number] = features
        bonus_raw[number] = (
            features["recent"] * float(bonus_weights.get("recent", 0.32))
            + features["slot"] * float(bonus_weights.get("slot", 0.20))
            + features["weekday"] * float(bonus_weights.get("weekday", 0.14))
            + features["modulo"] * float(bonus_weights.get("modulo", 0.12))
            + features["gap"] * float(bonus_weights.get("gap", 0.10))
            + ((1.0 - features["overlap"]) * float(bonus_weights.get("overlap", 0.12)))
        )

    return {
        "anchors": anchors,
        "pairContext": pair_context,
        "mainFeatures": main_features,
        "bonusFeatures": bonus_features,
        "mainHeuristicScores": _normalize_score_map(main_raw),
        "bonusHeuristicScores": _normalize_score_map(bonus_raw),
        "mainModuloContext": main_modulo_context,
        "bonusModuloContext": bonus_modulo_context,
        "slotHistory": slot_history,
        "weekdayHistory": weekday_history,
    }
