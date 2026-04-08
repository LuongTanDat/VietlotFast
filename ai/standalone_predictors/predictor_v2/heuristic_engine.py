from __future__ import annotations

from predictor_v2 import deep_model, feature_engineering, regime_engine, ticket_evaluator, tracking_engine


def _normalize_map(values):
    if not values:
        return {}
    minimum = min(float(value) for value in values.values())
    maximum = max(float(value) for value in values.values())
    if abs(maximum - minimum) <= 1e-9:
        return {key: 0.5 for key in values}
    span = maximum - minimum
    return {key: (float(value) - minimum) / span for key, value in values.items()}


def _blend_scores(heuristic_scores, deep_scores, tracking_scores, regime_scores, weights, deep_available):
    numerator = {}
    denominator = float(weights.get("heuristic", 0.0)) + float(weights.get("tracking", 0.0)) + float(weights.get("regime", 0.0))
    if deep_available:
        denominator += float(weights.get("deep", 0.0))
    denominator = max(1e-9, denominator)
    for key in heuristic_scores:
        numerator[key] = (
            float(heuristic_scores.get(key, 0.0)) * float(weights.get("heuristic", 0.0))
            + float(tracking_scores.get(key, 0.0)) * float(weights.get("tracking", 0.0))
            + float(regime_scores.get(key, 0.0)) * float(weights.get("regime", 0.0))
        )
        if deep_available:
            numerator[key] += float(deep_scores.get(key, 0.0)) * float(weights.get("deep", 0.0))
    return _normalize_map({key: value / denominator for key, value in numerator.items()})


def _repair_ticket_numbers(numbers, ordered_pool, latest_draw, target, excluded_numbers, keep_numbers, carry_limit):
    repaired = []
    latest_set = set(int(value) for value in list((latest_draw or {}).get("main") or []))
    for number in list(numbers or []):
        candidate = int(number)
        if candidate not in repaired:
            repaired.append(candidate)
    for candidate in ordered_pool:
        candidate = int(candidate)
        if candidate in repaired or candidate in excluded_numbers:
            continue
        repaired.append(candidate)
        if len(repaired) >= 5:
            break
    if target.get("same_day_follow_up"):
        overlap = [number for number in repaired if number in latest_set]
        protected = set(int(value) for value in keep_numbers[:max(0, int(carry_limit or 0))])
        while len(overlap) > int(carry_limit or 0):
            victim = next((value for value in overlap if value not in protected), overlap[-1])
            repaired.remove(victim)
            replacement = next(
                (
                    int(candidate)
                    for candidate in ordered_pool
                    if int(candidate) not in repaired and int(candidate) not in excluded_numbers and int(candidate) not in latest_set
                ),
                None,
            )
            if replacement is not None:
                repaired.append(replacement)
            overlap = [number for number in repaired if number in latest_set]
    repaired = sorted(set(repaired))[:5]
    return repaired


def _build_candidate_templates(main_pool):
    templates = [
        [0, 1, 2, 3, 4],
        [0, 1, 2, 3, 5],
        [0, 1, 2, 4, 6],
        [0, 1, 3, 4, 6],
        [0, 2, 3, 5, 7],
        [1, 2, 3, 4, 7],
        [0, 2, 4, 6, 8],
        [1, 3, 4, 6, 8],
        [0, 3, 5, 7, 9],
        [2, 4, 5, 7, 10],
        [0, 1, 4, 7, 10],
        [1, 2, 5, 8, 11],
    ]
    max_index = len(main_pool) - 1
    result = []
    for template in templates:
        picked = [main_pool[index] for index in template if 0 <= index <= max_index]
        if len(picked) >= 5:
            result.append(picked[:5])
    return result


def _candidate_ticket_context(draws, analysis):
    slot_history = list((analysis.get("snapshot") or {}).get("slotHistory") or [])
    return {
        "historicalDraws": slot_history or list(draws or [])[-24:],
        "pairContext": dict((analysis.get("snapshot") or {}).get("pairContext") or {}),
        "mainScores": dict(analysis.get("mainFinalScores") or {}),
        "bonusScores": dict(analysis.get("bonusFinalScores") or {}),
        "trackingSummary": tracking_engine.summarize_tracking_state(analysis.get("trackingState") or {}),
        "deepMainScores": dict((analysis.get("deep") or {}).get("mainScores") or {}),
        "deepBonusScores": dict((analysis.get("deep") or {}).get("bonusScores") or {}),
    }


def build_prediction_snapshot(draws, target, tracking_state, config_payload, bundle_count=3):
    snapshot = feature_engineering.build_feature_snapshot(draws, target, tracking_state, config_payload)
    regime = regime_engine.classify_regime(draws, target, tracking_state, config_payload)
    main_numbers = list(range(1, int(config_payload.get("main_max", 35)) + 1))
    bonus_numbers = list(range(1, int(config_payload.get("bonus_max", 12)) + 1))
    deep = deep_model.score_candidates(main_numbers, bonus_numbers)
    tracking_main_scores = {number: tracking_engine.get_tracking_score(tracking_state, number, "main") for number in main_numbers}
    tracking_bonus_scores = {number: tracking_engine.get_tracking_score(tracking_state, number, "bonus") for number in bonus_numbers}

    blend_weights = dict((config_payload.get("blend_weights") or {}).get("main") or {})
    bonus_blend_weights = dict((config_payload.get("blend_weights") or {}).get("bonus") or {})
    main_final_scores = _blend_scores(
        snapshot["mainHeuristicScores"],
        dict(deep.get("mainScores") or {}),
        tracking_main_scores,
        dict(regime.get("mainAdjustments") or {}),
        blend_weights,
        bool(deep.get("available")),
    )
    bonus_final_scores = _blend_scores(
        snapshot["bonusHeuristicScores"],
        dict(deep.get("bonusScores") or {}),
        tracking_bonus_scores,
        dict(regime.get("bonusAdjustments") or {}),
        bonus_blend_weights,
        bool(deep.get("available")),
    )

    top_main = sorted(main_final_scores, key=lambda number: (-float(main_final_scores[number]), int(number)))
    top_bonus = sorted(bonus_final_scores, key=lambda number: (-float(bonus_final_scores[number]), int(number)))

    candidate_pool_size = int(((config_payload.get("candidate_pool") or {}).get("main") or 14))
    main_pool = top_main[: max(8, candidate_pool_size)]
    excluded_numbers = set(int(value) for value in list((tracking_state or {}).get("temporary_excluded_numbers") or []))
    keep_numbers = [int(value) for value in list((tracking_state or {}).get("kept_numbers") or [])]
    latest_draw = target.get("latest_actual_draw") or {}
    carry_limit = int(config_payload.get("same_day_carry_limit", 1) or 1)
    bonus_candidates = top_bonus[: max(4, int(((config_payload.get("candidate_pool") or {}).get("bonus") or 6)))]

    candidate_tickets = []
    ticket_context = None
    for index, template_numbers in enumerate(_build_candidate_templates(main_pool)):
        repaired_main = _repair_ticket_numbers(
            template_numbers + keep_numbers[:2],
            top_main,
            latest_draw,
            target,
            excluded_numbers,
            keep_numbers,
            carry_limit,
        )
        if len(repaired_main) != 5:
            continue
        special = bonus_candidates[index % len(bonus_candidates)] if bonus_candidates else 1
        ticket = {
            "main": repaired_main,
            "special": int(special),
            "slot": str(target.get("target_slot", "")),
        }
        if ticket_context is None:
            ticket_context = _candidate_ticket_context(draws, {
                "snapshot": snapshot,
                "mainFinalScores": main_final_scores,
                "bonusFinalScores": bonus_final_scores,
                "trackingState": tracking_state,
                "deep": deep,
            })
        evaluation = ticket_evaluator.evaluate_ticket(ticket, ticket_context)
        ticket["qualityScore"] = float(evaluation["qualityScore"])
        ticket["beautyScore"] = float(evaluation["beautyScore"])
        ticket["qualityBreakdown"] = dict(evaluation["breakdown"] or {})
        candidate_tickets.append(ticket)

    candidate_tickets.sort(
        key=lambda ticket: (
            float(ticket.get("qualityScore", 0.0)),
            sum(float(main_final_scores.get(number, 0.0)) for number in list(ticket.get("main") or [])),
            -int(ticket.get("special", 0) or 0),
        ),
        reverse=True,
    )

    return {
        "snapshot": snapshot,
        "regime": regime,
        "deep": deep,
        "mainFinalScores": main_final_scores,
        "bonusFinalScores": bonus_final_scores,
        "topMain": top_main,
        "topBonus": top_bonus,
        "candidateTickets": candidate_tickets,
        "trackingState": tracking_state,
        "target": target,
        "requestedBundleCount": max(1, int(bundle_count or 1)),
    }


def select_vip_tickets(analysis, config_payload):
    tickets = list(analysis.get("candidateTickets") or [])
    if not tickets:
        return {"primary": None, "backups": []}
    pool_config = dict((config_payload or {}).get("candidate_pool") or {})
    backup_min = int(pool_config.get("backup_min", 2) or 2)
    backup_max = int(pool_config.get("backup_max", 5) or 5)
    total_ticket_goal = max(3, min(backup_max + 1, int(analysis.get("requestedBundleCount") or 3)))
    backup_goal = max(backup_min, min(backup_max, total_ticket_goal - 1))

    primary = tickets[0]
    selected_backups = []
    primary_set = set(int(value) for value in list(primary.get("main") or []))
    for ticket in tickets[1:]:
        if len(selected_backups) >= backup_goal:
            break
        main_set = set(int(value) for value in list(ticket.get("main") or []))
        overlap_with_primary = len(main_set.intersection(primary_set))
        overlap_with_backups = max(
            (len(main_set.intersection(set(int(value) for value in list(existing.get("main") or [])))) for existing in selected_backups),
            default=0,
        )
        if overlap_with_primary > 3 or overlap_with_backups > 4:
            continue
        selected_backups.append(ticket)
    if len(selected_backups) < backup_goal:
        for ticket in tickets[1:]:
            if len(selected_backups) >= backup_goal:
                break
            if ticket in selected_backups:
                continue
            selected_backups.append(ticket)
    return {
        "primary": primary,
        "backups": selected_backups[:backup_goal],
    }
