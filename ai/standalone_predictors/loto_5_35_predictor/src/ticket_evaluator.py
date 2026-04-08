from __future__ import annotations

from src import modulo_engine, pair_engine


def _clamp01(value):
    return max(0.0, min(1.0, float(value or 0.0)))


def _sum_balance(numbers, historical_sums):
    if not numbers or not historical_sums:
        return 0.5
    value = sum(numbers)
    average = sum(historical_sums) / float(len(historical_sums))
    spread = max(8.0, (max(historical_sums) - min(historical_sums)) / 2.0)
    return _clamp01(1.0 - min(abs(value - average) / spread, 1.0))


def _parity_balance(numbers):
    if not numbers:
        return 0.5
    even_count = sum(1 for number in numbers if int(number) % 2 == 0)
    odd_count = len(numbers) - even_count
    return _clamp01(1.0 - (abs(even_count - odd_count) / float(len(numbers))))


def _range_balance(numbers, historical_spans):
    if not numbers or not historical_spans:
        return 0.5
    span = max(numbers) - min(numbers)
    average = sum(historical_spans) / float(len(historical_spans))
    spread = max(6.0, (max(historical_spans) - min(historical_spans)) / 2.0)
    return _clamp01(1.0 - min(abs(span - average) / spread, 1.0))


def _position_plausibility(numbers, historical_position_averages):
    if not numbers or not historical_position_averages:
        return 0.5
    ordered = sorted(int(value) for value in numbers)
    deltas = []
    for index, number in enumerate(ordered):
        baseline = historical_position_averages[index]
        deltas.append(abs(number - baseline))
    average_delta = sum(deltas) / float(len(deltas))
    return _clamp01(1.0 - min(average_delta / 10.0, 1.0))


def _regime_fit(numbers, regime):
    if not numbers:
        return 0.5
    adjustments = dict((regime or {}).get("mainAdjustments") or {})
    return _clamp01(sum(float(adjustments.get(number, 0.5)) for number in numbers) / float(len(numbers)))


def _cluster_shift_fit(numbers, cluster_transition):
    if not numbers:
        return 0.5
    centroid = sum(numbers) / float(len(numbers))
    tail_value = max(numbers)
    target_center = float((cluster_transition or {}).get("targetCenter", centroid))
    target_tail = float((cluster_transition or {}).get("targetTail", tail_value))
    center_score = _clamp01(1.0 - min(abs(centroid - target_center) / 8.0, 1.0))
    tail_score = _clamp01(1.0 - min(abs(tail_value - target_tail) / 10.0, 1.0))
    migration = str((cluster_transition or {}).get("bandMigration", "stable"))
    baseline_center = float((cluster_transition or {}).get("baselineCenter", centroid))
    if migration == "up":
        direction_score = 1.0 if centroid >= baseline_center else 0.45
    elif migration == "down":
        direction_score = 1.0 if centroid <= baseline_center else 0.45
    else:
        direction_score = _clamp01(1.0 - min(abs(centroid - float((cluster_transition or {}).get("currentCenter", centroid))) / 8.0, 1.0))
    return _clamp01((center_score * 0.45) + (tail_score * 0.35) + (direction_score * 0.20))


def _recent_alignment(numbers, historical_draws, main_scores, sum_balance, range_score, position_plausibility):
    if not numbers:
        return 0.5
    recent_draws = list(historical_draws or [])[-8:]
    recent_union = {int(value) for draw in recent_draws for value in list(draw.get("main") or [])}
    hot_support = _clamp01(sum(float(main_scores.get(number, 0.0)) for number in numbers) / float(len(numbers)))
    recent_presence = _clamp01(sum(1.0 for number in numbers if number in recent_union) / float(len(numbers)))
    return _clamp01((hot_support * 0.35) + (recent_presence * 0.25) + (sum_balance * 0.20) + (range_score * 0.10) + (position_plausibility * 0.10))


def _source_confidence(numbers, source_scores, reference_candidates):
    if not numbers:
        return 0.5
    source_average = _clamp01(sum(float(source_scores.get(number, 0.0)) for number in numbers) / float(len(numbers)))
    reference_overlap = _clamp01(len(set(numbers).intersection(set(reference_candidates[: len(numbers) + 1]))) / float(len(numbers)))
    return _clamp01((source_average * 0.75) + (reference_overlap * 0.25))


def evaluate_ticket(ticket, context, config_payload=None):
    numbers = sorted(set(int(value) for value in list((ticket or {}).get("main") or [])))
    special = int(ticket.get("special")) if isinstance(ticket.get("special"), int) else None
    main_scores = dict(context.get("mainScores") or {})
    bonus_scores = dict(context.get("bonusScores") or {})
    tracking_summary = dict(context.get("trackingSummary") or {})
    temporary_excluded = set(int(value) for value in list(tracking_summary.get("temporary_excluded_numbers") or []))
    kept_numbers = set(int(value) for value in list(tracking_summary.get("kept_numbers") or []))
    historical_draws = list(context.get("historicalDraws") or [])
    pair_context = dict(context.get("pairContext") or {})
    deep_scores = dict(context.get("deepMainScores") or {})
    deep_bonus_scores = dict(context.get("deepBonusScores") or {})
    regime = dict(context.get("regime") or {})
    cluster_transition = dict(context.get("clusterTransition") or {})
    source_scores = dict(context.get("sourceScores") or main_scores)
    reference_candidates = list(context.get("referenceCandidates") or [])

    modulo_metrics = modulo_engine.evaluate_ticket_modulo(numbers)
    pair_metrics = pair_engine.evaluate_ticket_pair_quality(numbers, pair_context)
    historical_sums = [sum(draw.get("main") or []) for draw in historical_draws if draw.get("main")]
    historical_spans = [max(draw["main"]) - min(draw["main"]) for draw in historical_draws if draw.get("main")]
    position_averages = []
    if historical_draws:
        for index in range(5):
            column = [sorted(draw["main"])[index] for draw in historical_draws if len(draw.get("main") or []) == 5]
            position_averages.append(sum(column) / float(len(column)) if column else 0.0)

    hot_cold_balance = _clamp01(sum(float(main_scores.get(number, 0.0)) for number in numbers) / max(1.0, len(numbers)))
    keep_reuse_score = _clamp01(sum(1.0 for number in numbers if number in kept_numbers) / max(1.0, len(numbers)))
    exclusion_penalty = _clamp01(sum(1.0 for number in numbers if number in temporary_excluded) / max(1.0, len(numbers)))
    deep_ticket_support = _clamp01(
        (
            sum(float(deep_scores.get(number, 0.0)) for number in numbers)
            + (float(deep_bonus_scores.get(special, 0.0)) if isinstance(special, int) else 0.0)
        )
        / max(1.0, len(numbers) + (1 if isinstance(special, int) else 0))
    )
    regime_fit = _regime_fit(numbers, regime)
    cluster_shift_fit = _cluster_shift_fit(numbers, cluster_transition)
    recent_alignment = _recent_alignment(numbers, historical_draws, main_scores, breakdown_sum_balance := _sum_balance(numbers, historical_sums), breakdown_range_score := _range_balance(numbers, historical_spans), breakdown_position_plausibility := _position_plausibility(numbers, position_averages))
    source_confidence = _source_confidence(numbers, source_scores, reference_candidates)

    breakdown = {
        "sumBalance": breakdown_sum_balance,
        "parityBalance": _parity_balance(numbers),
        "modulo3Balance": modulo_metrics["modulo3Balance"],
        "modulo5Pattern": modulo_metrics["modulo5Pattern"],
        "tailPattern": modulo_metrics["tailPattern"],
        "pairCompatibility": pair_metrics["pairCompatibility"],
        "antiPairPenalty": pair_metrics["antiPairPenalty"],
        "positionPlausibility": breakdown_position_plausibility,
        "rangeScore": breakdown_range_score,
        "hotColdBalance": hot_cold_balance,
        "keepReuseScore": keep_reuse_score,
        "exclusionPenalty": exclusion_penalty,
        "deepTicketSupport": deep_ticket_support,
        "bonusSupport": _clamp01(float(bonus_scores.get(special, 0.0)) if isinstance(special, int) else 0.0),
        "regimeFit": regime_fit,
        "clusterShiftFit": cluster_shift_fit,
        "recentAlignment": recent_alignment,
        "sourceConfidence": source_confidence,
    }
    ticket_weights = dict((config_payload or {}).get("ticket_weights") or {})
    if ticket_weights:
        weighted_score = sum(float(ticket_weights.get(name, 0.0)) * float(value) for name, value in breakdown.items())
    else:
        weighted_score = (
            breakdown["sumBalance"] * 0.11
            + breakdown["parityBalance"] * 0.07
            + breakdown["modulo3Balance"] * 0.07
            + breakdown["modulo5Pattern"] * 0.06
            + breakdown["tailPattern"] * 0.06
            + breakdown["pairCompatibility"] * 0.10
            + breakdown["positionPlausibility"] * 0.09
            + breakdown["rangeScore"] * 0.08
            + breakdown["hotColdBalance"] * 0.11
            + breakdown["keepReuseScore"] * 0.09
            + breakdown["bonusSupport"] * 0.06
            + breakdown["deepTicketSupport"] * 0.05
            - breakdown["antiPairPenalty"] * 0.10
            - breakdown["exclusionPenalty"] * 0.11
        )
    quality_score = round(max(0.0, min(100.0, weighted_score * 100.0)), 2)
    return {
        "qualityScore": quality_score,
        "beautyScore": quality_score,
        "breakdown": breakdown,
    }
