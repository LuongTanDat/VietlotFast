from __future__ import annotations

from typing import Any

from src import modulo_engine, pair_engine, regime_engine


def _closeness(value: float, target: float, tolerance: float) -> float:
    if tolerance <= 0:
        return 0.0
    return max(0.0, 1.0 - abs(value - target) / tolerance)


def _positional_fit(ticket_numbers: list[int], position_profile: dict[str, list[float]], regime_context: dict[str, Any]) -> float:
    means = list(position_profile.get("means") or [8.5, 16.5, 25.0, 34.0, 44.0, 51.5])
    stds = list(position_profile.get("stds") or [5.0] * 6)
    scores = []
    for index, number in enumerate(sorted(ticket_numbers)):
        closeness = _closeness(number, means[index], max(10.0, stds[index] * 4.5))
        if index == 5:
            closeness = 0.65 * closeness + 0.35 * regime_engine.score_main_number(number, regime_context)
        scores.append(closeness)
    return sum(scores) / len(scores) if scores else 0.0


def _cluster_shift_fit(ticket_numbers: list[int], cluster_transition: dict[str, Any]) -> float:
    if not ticket_numbers:
        return 0.5
    centroid = sum(ticket_numbers) / float(len(ticket_numbers))
    tail_value = max(ticket_numbers)
    center_score = _closeness(centroid, float(cluster_transition.get("target_center", centroid)), 8.0)
    tail_score = _closeness(tail_value, float(cluster_transition.get("target_tail", tail_value)), 10.0)
    migration = str(cluster_transition.get("band_migration", "stable"))
    if migration == "up":
        direction_score = 1.0 if centroid >= float(cluster_transition.get("baseline_center", centroid)) else 0.45
    elif migration == "down":
        direction_score = 1.0 if centroid <= float(cluster_transition.get("baseline_center", centroid)) else 0.45
    else:
        direction_score = 1.0 - min(abs(centroid - float(cluster_transition.get("current_center", centroid))) / 8.0, 1.0)
    return max(0.0, min(1.0, 0.45 * center_score + 0.35 * tail_score + 0.20 * direction_score))


def _recent_alignment(
    ticket_numbers: list[int],
    prediction_context: dict[str, Any],
    sum_balance: float,
    span_score: float,
    positional_fit: float,
) -> float:
    if not ticket_numbers:
        return 0.5
    recent_frequency = dict(prediction_context.get("recent_frequency") or {})
    secondary_frequency = dict(prediction_context.get("secondary_frequency") or {})
    last_draw = prediction_context.get("last_draw")
    overlap_penalty = 0.0
    if last_draw is not None:
        overlap_penalty = max(0.0, len(set(ticket_numbers) & set(last_draw.main_numbers)) - 2) / 4.0
    hot_support = sum(
        0.60 * float(recent_frequency.get(number, 0.0))
        + 0.40 * float(secondary_frequency.get(number, 0.0))
        for number in ticket_numbers
    ) / max(1, len(ticket_numbers))
    return max(
        0.0,
        min(1.0, 0.40 * hot_support + 0.20 * sum_balance + 0.20 * span_score + 0.20 * positional_fit - 0.20 * overlap_penalty),
    )


def _source_confidence(ticket_numbers: list[int], context: dict[str, Any]) -> float:
    if not ticket_numbers:
        return 0.5
    source_scores = dict(context.get("source_scores") or context.get("final_main_scores") or {})
    reference_candidates = list(context.get("reference_candidates") or [])
    source_average = sum(float(source_scores.get(number, 0.0)) for number in ticket_numbers) / max(1, len(ticket_numbers))
    reference_overlap = len(set(ticket_numbers) & set(reference_candidates[: len(ticket_numbers) + 2])) / max(1, len(ticket_numbers))
    return max(0.0, min(1.0, 0.75 * source_average + 0.25 * reference_overlap))


def evaluate_ticket(
    ticket_numbers: list[int] | tuple[int, ...],
    special_number: int | None,
    context: dict[str, Any],
    predictor_config: dict[str, Any],
) -> dict[str, Any]:
    ticket = sorted(int(number) for number in ticket_numbers)
    prediction_context = dict(context.get("prediction_context") or {})
    tracking_state = dict(context.get("tracking_state") or {})
    pair_context = dict(context.get("pair_context") or {})
    regime_context = dict(context.get("regime_context") or {})
    final_main_scores = dict(context.get("final_main_scores") or {})
    final_special_scores = dict(context.get("final_special_scores") or {})
    tracking_scores_special = dict(context.get("tracking_scores_special") or {})
    deep_result = dict(context.get("deep_result") or {})

    ticket_sum = sum(ticket)
    ticket_range = ticket[-1] - ticket[0]
    hot_numbers = set(prediction_context.get("hot_numbers") or [])
    kept_numbers = set(tracking_state.get("kept_numbers") or [])
    excluded_numbers = set(tracking_state.get("temporary_excluded_numbers") or [])
    ticket_modulo = modulo_engine.score_ticket_structure(ticket, prediction_context.get("modulo_context") or {})
    ticket_pairs = pair_engine.score_ticket(ticket, pair_context)

    hot_count = sum(1 for number in ticket if number in hot_numbers or final_main_scores.get(number, 0.0) >= 0.66)
    kept_count = sum(1 for number in ticket if number in kept_numbers)
    excluded_count = sum(1 for number in ticket if number in excluded_numbers)

    sum_balance = _closeness(ticket_sum, float(prediction_context.get("average_sum_recent", 175.0)), 60.0)
    parity_balance = ticket_modulo["parity_balance"]
    modulo3_balance = ticket_modulo["modulo3_balance"]
    modulo5_pattern = ticket_modulo["modulo5_pattern"]
    tail_structure = ticket_modulo["tail_structure"]
    pair_compatibility = ticket_pairs["pair_compatibility"]
    anti_pair_penalty = ticket_pairs["anti_pair_penalty"]
    positional_fit = _positional_fit(ticket, prediction_context.get("position_profile") or {}, regime_context)
    span_score = _closeness(ticket_range, float(prediction_context.get("average_range_recent", 34.0)), 18.0)
    hot_cold_balance = max(0.0, 1.0 - min(abs(hot_count - 3), abs(hot_count - 2)) / 4.0)
    keep_mark_reuse = max(0.0, 1.0 - min(abs(kept_count - 2), abs(kept_count - 1)) / 3.0)
    exclusion_penalty = min(1.0, excluded_count / 2.0)
    regime_fit = sum(regime_engine.score_main_number(number, regime_context) for number in ticket) / len(ticket)
    cluster_shift_fit = _cluster_shift_fit(ticket, context.get("cluster_transition") or {})
    recent_alignment = _recent_alignment(ticket, prediction_context, sum_balance, span_score, positional_fit)
    source_confidence = _source_confidence(ticket, context)
    if deep_result.get("available"):
        deep_ticket_support = sum(float((deep_result.get("main_scores") or {}).get(number, 0.0)) for number in ticket) / len(ticket)
    else:
        deep_ticket_support = 0.5

    if special_number is None:
        special_support_score = 0.5
    else:
        special_support_score = (
            0.60 * modulo_engine.score_special_support(int(special_number), ticket, prediction_context.get("modulo_context") or {})
            + 0.25 * final_special_scores.get(int(special_number), 0.0)
            + 0.15 * tracking_scores_special.get(int(special_number), 0.5)
        )

    breakdown = {
        "sum_balance": sum_balance,
        "parity_balance": parity_balance,
        "modulo3_balance": modulo3_balance,
        "modulo5_pattern": modulo5_pattern,
        "tail_structure": tail_structure,
        "pair_compatibility": pair_compatibility,
        "anti_pair_penalty": anti_pair_penalty,
        "positional_fit": positional_fit,
        "span_score": span_score,
        "hot_cold_balance": hot_cold_balance,
        "keep_mark_reuse": keep_mark_reuse,
        "exclusion_penalty": exclusion_penalty,
        "deep_ticket_support": deep_ticket_support,
        "special_support_score": special_support_score,
        "regime_fit": regime_fit,
        "cluster_shift_fit": cluster_shift_fit,
        "recent_alignment": recent_alignment,
        "source_confidence": source_confidence,
    }

    weights = dict(predictor_config.get("ticket_weights") or {})
    raw_score = sum(float(weights.get(name, 0.0)) * value for name, value in breakdown.items())
    quality_score = max(0.0, min(100.0, raw_score * 100.0))
    return {
        "ticket": ticket,
        "special": special_number,
        "quality_score": quality_score,
        "breakdown": breakdown,
    }


def evaluate_main_ticket(ticket_numbers: list[int] | tuple[int, ...], context: dict[str, Any], predictor_config: dict[str, Any]) -> dict[str, Any]:
    return evaluate_ticket(ticket_numbers, None, context, predictor_config)
