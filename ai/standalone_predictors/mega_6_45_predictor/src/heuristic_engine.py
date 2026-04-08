from __future__ import annotations

from pathlib import Path
from statistics import mean
from typing import Any

from src import deep_model, feature_engineering, modulo_engine, pair_engine, regime_engine, tracking_engine


def _position_fit_score(number: int, position_profile: dict[str, list[float]], regime_context: dict[str, Any]) -> float:
    means = list(position_profile.get("means") or [7.5, 14.0, 21.0, 28.0, 35.0, 41.0])
    stds = list(position_profile.get("stds") or [4.0] * 6)
    weights = [0.14, 0.14, 0.17, 0.17, 0.19, 0.19]
    total = 0.0
    for index, (mean_value, spread) in enumerate(zip(means, stds)):
        closeness = max(0.0, 1.0 - abs(number - mean_value) / max(8.0, float(spread) * 4.0))
        if index <= 1 and number > 20:
            closeness *= 0.75
        if index >= 4 and number < 20:
            closeness *= 0.75
        if index == 5:
            closeness = 0.65 * closeness + 0.35 * regime_engine.score_number(number, regime_context)
        total += closeness * weights[index]
    return max(0.0, min(1.0, total / sum(weights)))


def _true_hot_score(number: int, secondary_frequency: dict[int, float], hot_numbers: list[int]) -> float:
    return max(0.0, min(1.0, 0.70 * secondary_frequency.get(number, 0.0) + 0.30 * float(number in set(hot_numbers))))


def _recent_score(number: int, recent_frequency: dict[int, float], secondary_frequency: dict[int, float]) -> float:
    return max(0.0, min(1.0, 0.76 * recent_frequency.get(number, 0.0) + 0.24 * secondary_frequency.get(number, 0.0)))


def _weekday_score(number: int, weekday_frequency: dict[int, float], same_weekday_draw_count: int) -> float:
    if same_weekday_draw_count <= 0:
        return 0.5
    return max(0.0, min(1.0, weekday_frequency.get(number, 0.0)))


def _build_anchor_numbers(prediction_context: dict[str, Any], tracking_state: dict[str, Any]) -> list[int]:
    anchors: list[int] = []
    anchors.extend(int(number) for number in list(tracking_state.get("kept_numbers") or [])[:3])
    anchors.extend(int(number) for number in list(prediction_context.get("hot_numbers") or [])[:4])
    last_draw = prediction_context.get("last_draw")
    if last_draw is not None:
        anchors.extend(int(number) for number in list(last_draw.main_numbers)[:2])
    deduped = []
    for number in anchors:
        if number not in deduped:
            deduped.append(number)
    return deduped[:6]


def _rank_numbers(score_map: dict[int, float]) -> list[int]:
    return [int(number) for number, _score in sorted(score_map.items(), key=lambda item: (-float(item[1]), int(item[0])))]


def _band_profile(numbers: list[int], number_max: int) -> dict[str, float]:
    if not numbers:
        return {"low": 0.0, "mid": 0.0, "high": 0.0}
    first_cut = number_max / 3.0
    second_cut = 2.0 * number_max / 3.0
    counts = {"low": 0, "mid": 0, "high": 0}
    for number in numbers:
        if number <= first_cut:
            counts["low"] += 1
        elif number <= second_cut:
            counts["mid"] += 1
        else:
            counts["high"] += 1
    total = float(len(numbers))
    return {band: count / total for band, count in counts.items()}


def _build_disagreement_analysis(
    heuristic_scores: dict[int, float],
    deep_scores: dict[int, float],
    predictor_config: dict[str, Any],
) -> dict[str, Any]:
    assembly_config = dict(predictor_config.get("assembly") or {})
    top_n = max(4, int(assembly_config.get("disagreement_top_n", 10) or 10))
    deep_ranked = _rank_numbers(deep_scores)
    if not deep_ranked or max(float(value) for value in deep_scores.values()) <= 0.0:
        return {
            "available": False,
            "score": 0.0,
            "level": "low",
            "top_n": top_n,
            "overlap_ratio": 1.0,
            "band_shift": 0.0,
            "center_shift": 0.0,
            "tail_shift": 0.0,
        }

    heuristic_ranked = _rank_numbers(heuristic_scores)[:top_n]
    deep_ranked = deep_ranked[:top_n]
    scoped_n = max(1, min(len(heuristic_ranked), len(deep_ranked), top_n))
    heuristic_top = heuristic_ranked[:scoped_n]
    deep_top = deep_ranked[:scoped_n]
    overlap_ratio = len(set(heuristic_top) & set(deep_top)) / float(scoped_n)
    heuristic_band = _band_profile(heuristic_top, 45)
    deep_band = _band_profile(deep_top, 45)
    band_shift = sum(abs(float(heuristic_band[band]) - float(deep_band[band])) for band in ("low", "mid", "high")) / 2.0
    center_shift = abs(mean(heuristic_top) - mean(deep_top)) / 45.0
    tail_span = max(2, scoped_n // 3)
    tail_shift = abs(mean(heuristic_top[-tail_span:]) - mean(deep_top[-tail_span:])) / 45.0
    score = max(
        0.0,
        min(
            1.0,
            0.50 * (1.0 - overlap_ratio)
            + 0.25 * band_shift
            + 0.15 * center_shift
            + 0.10 * tail_shift,
        ),
    )
    low_threshold = float(assembly_config.get("low_disagreement_threshold", 0.18) or 0.18)
    high_threshold = float(assembly_config.get("high_disagreement_threshold", 0.40) or 0.40)
    if score >= high_threshold:
        level = "high"
    elif score >= low_threshold:
        level = "medium"
    else:
        level = "low"
    return {
        "available": True,
        "score": score,
        "level": level,
        "top_n": scoped_n,
        "overlap_ratio": overlap_ratio,
        "band_shift": band_shift,
        "center_shift": center_shift,
        "tail_shift": tail_shift,
    }


def _build_cluster_transition(prediction_context: dict[str, Any], regime_context: dict[str, Any]) -> dict[str, Any]:
    recent_primary = list(prediction_context.get("recent_primary") or [])
    recent_secondary = list(prediction_context.get("recent_secondary") or [])
    older_window = recent_secondary[:-len(recent_primary)] if recent_primary and len(recent_secondary) > len(recent_primary) else list(recent_secondary[:-1])

    def _average_center(scoped_draws: list[Any], default_value: float) -> float:
        if not scoped_draws:
            return default_value
        return mean(sum(draw.main_numbers) / 6.0 for draw in scoped_draws)

    def _average_tail(scoped_draws: list[Any], default_value: float) -> float:
        if not scoped_draws:
            return default_value
        return mean(draw.main_numbers[-1] for draw in scoped_draws)

    position_profile = dict(prediction_context.get("position_profile") or {})
    default_center = float(prediction_context.get("average_sum_recent", 135.0)) / 6.0
    default_tail = float((position_profile.get("means") or [7.5, 14.0, 21.0, 28.0, 35.0, 41.0])[-1])
    baseline_center = _average_center(older_window or recent_secondary or recent_primary, default_center)
    current_center = _average_center(recent_primary or recent_secondary, default_center)
    baseline_tail = _average_tail(older_window or recent_secondary or recent_primary, default_tail)
    current_tail = _average_tail(recent_primary or recent_secondary, default_tail)
    center_shift = current_center - baseline_center
    tail_shift = current_tail - baseline_tail
    target_center = current_center + 0.45 * center_shift
    target_tail = current_tail + 0.40 * tail_shift
    regime_name = str(regime_context.get("regime", "neutral"))
    if regime_name == "reset":
        target_center -= 1.0
        target_tail -= 1.5
    elif regime_name == "continuation":
        target_center += 0.6
        target_tail += 1.0
    if target_center >= baseline_center + 1.0:
        migration = "up"
    elif target_center <= baseline_center - 1.0:
        migration = "down"
    else:
        migration = "stable"
    return {
        "baseline_center": baseline_center,
        "current_center": current_center,
        "target_center": target_center,
        "baseline_tail": baseline_tail,
        "current_tail": current_tail,
        "target_tail": target_tail,
        "center_shift": center_shift,
        "tail_shift": tail_shift,
        "band_migration": migration,
    }


def _resolve_blend_profile(
    predictor_config: dict[str, Any],
    requested_mode: str | None,
    deep_available: bool,
) -> tuple[str, dict[str, float]]:
    profiles = dict(predictor_config.get("blend_profiles") or {})
    default_mode = str(requested_mode or predictor_config.get("blend_mode_default") or "blended").strip() or "blended"
    mode_used = default_mode if default_mode in profiles else "blended"
    weights = dict(profiles.get(mode_used) or predictor_config.get("deep_blend") or {})
    if mode_used == "deep_only" and not deep_available:
        mode_used = "heuristic_only"
        weights = dict(profiles.get("heuristic_only") or {"heuristic": 0.45, "deep": 0.0, "tracking": 0.20})
    return mode_used, weights


def _ticket_deep_result(deep_result: dict[str, Any], blend_mode: str) -> dict[str, Any]:
    if blend_mode != "heuristic_only":
        return dict(deep_result or {})
    muted = dict(deep_result or {})
    muted["available"] = False
    muted["main_scores"] = {number: 0.0 for number in range(1, 46)}
    return muted


def build_scoring_context(
    draws: list[Any],
    tracking_state: dict[str, Any],
    predictor_config: dict[str, Any],
    feature_flags: dict[str, Any],
    target_weekday: int,
    time_slot_enabled: bool,
    project_root: Path,
    blend_mode: str | None = None,
) -> dict[str, Any]:
    prediction_context = feature_engineering.build_prediction_context(
        draws,
        tracking_state=tracking_state,
        predictor_config=predictor_config,
        target_weekday=target_weekday,
        time_slot_enabled=time_slot_enabled,
        use_mod9=bool(feature_flags.get("use_mod9", True)),
    )
    pair_context = pair_engine.build_pair_context(
        draws,
        history_limit=int((predictor_config.get("windows") or {}).get("pair_history", 180)),
    )
    regime_context = regime_engine.detect_regime(
        prediction_context.get("recent_secondary") or draws,
        recent_frequency=prediction_context.get("secondary_frequency"),
    )
    anchor_numbers = _build_anchor_numbers(prediction_context, tracking_state)
    scoring_weights = dict(predictor_config.get("scoring_weights") or {})

    component_scores: dict[int, dict[str, float]] = {}
    heuristic_scores: dict[int, float] = {}
    tracking_scores: dict[int, float] = {}
    raw_without_tracking: dict[int, float] = {}

    for number in range(1, 46):
        tracking_score = tracking_engine.get_tracking_score(tracking_state, number)
        components = {
            "recent_score": _recent_score(number, prediction_context["recent_frequency"], prediction_context["secondary_frequency"]),
            "weekday_score": _weekday_score(number, prediction_context["weekday_frequency"], len(prediction_context["same_weekday_draws"])),
            "modulo_score": modulo_engine.score_number(number, prediction_context["modulo_context"]),
            "position_fit_score": _position_fit_score(number, prediction_context["position_profile"], regime_context),
            "pair_score": pair_engine.score_number(number, anchor_numbers, pair_context),
            "anti_pair_adjustment": pair_engine.anti_pair_adjustment(number, anchor_numbers, pair_context),
            "true_hot_score": _true_hot_score(number, prediction_context["secondary_frequency"], prediction_context["hot_numbers"]),
            "keep_mark_adjustment": tracking_score,
        }
        heuristic_score = sum(
            float(scoring_weights.get(component_name, 0.0)) * component_value
            for component_name, component_value in components.items()
        )
        if time_slot_enabled:
            heuristic_score = 0.95 * heuristic_score + 0.05 * 0.50
        component_scores[number] = components
        raw_without_tracking[number] = heuristic_score - float(scoring_weights.get("keep_mark_adjustment", 0.13)) * tracking_score
        heuristic_scores[number] = max(0.0, min(1.0, heuristic_score))
        tracking_scores[number] = tracking_score

    deep_result = deep_model.score_numbers(
        prediction_context=prediction_context,
        tracking_state=tracking_state,
        predictor_config=predictor_config,
        feature_flags=feature_flags,
        project_root=project_root,
    )
    deep_scores = {
        int(number): float(score)
        for number, score in dict(deep_result.get("main_scores") or {}).items()
    }
    blend_mode_used, blend_weights = _resolve_blend_profile(
        predictor_config=predictor_config,
        requested_mode=blend_mode,
        deep_available=bool(deep_result.get("available")),
    )
    deep_for_tickets = _ticket_deep_result(deep_result, blend_mode_used)
    disagreement_analysis = _build_disagreement_analysis(heuristic_scores, deep_scores, predictor_config)
    cluster_transition = _build_cluster_transition(prediction_context, regime_context)
    final_scores: dict[int, float] = {}
    for number in range(1, 46):
        if blend_mode_used == "heuristic_only" or not bool(deep_result.get("available")):
            final_score = heuristic_scores[number]
        elif blend_mode_used == "deep_only":
            final_score = float(deep_scores.get(number, 0.0))
        else:
            final_score = (
                float(blend_weights.get("heuristic", 0.45)) * heuristic_scores[number]
                + float(blend_weights.get("deep", 0.35)) * float(deep_scores.get(number, 0.0))
                + float(blend_weights.get("tracking", 0.20)) * tracking_scores[number]
            )
        final_scores[number] = max(0.0, min(1.0, final_score))

    top_main_candidates = _rank_numbers(final_scores)
    heuristic_ranked_numbers = _rank_numbers(heuristic_scores)
    deep_ranked_numbers = _rank_numbers(deep_scores) if deep_scores else []
    excluded_set = set(tracking_state.get("temporary_excluded_numbers") or [])
    downgraded_due_to_misses = [
        number
        for number, _score in sorted(raw_without_tracking.items(), key=lambda item: item[1], reverse=True)
        if number in excluded_set and number not in top_main_candidates[:10]
    ][:6]

    return {
        "prediction_context": prediction_context,
        "pair_context": pair_context,
        "regime_context": regime_context,
        "anchor_numbers": anchor_numbers,
        "component_scores": component_scores,
        "tracking_scores": tracking_scores,
        "heuristic_scores": heuristic_scores,
        "final_scores": final_scores,
        "deep_result": deep_result,
        "ticket_deep_result": deep_for_tickets,
        "blend_mode_used": blend_mode_used,
        "blend_weights_used": blend_weights,
        "heuristic_ranked_numbers": heuristic_ranked_numbers,
        "deep_ranked_numbers": deep_ranked_numbers,
        "disagreement_analysis": disagreement_analysis,
        "cluster_transition": cluster_transition,
        "top_main_candidates": top_main_candidates,
        "downgraded_due_to_misses": downgraded_due_to_misses,
    }
