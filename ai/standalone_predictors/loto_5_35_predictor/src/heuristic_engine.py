from __future__ import annotations

from statistics import mean

from src import deep_model, feature_engineering, regime_engine, ticket_evaluator, tracking_engine


def _normalize_map(values):
    if not values:
        return {}
    minimum = min(float(value) for value in values.values())
    maximum = max(float(value) for value in values.values())
    if abs(maximum - minimum) <= 1e-9:
        return {key: 0.5 for key in values}
    span = maximum - minimum
    return {key: (float(value) - minimum) / span for key, value in values.items()}


def _rank_numbers(score_map):
    return [int(number) for number, _score in sorted(score_map.items(), key=lambda item: (-float(item[1]), int(item[0])))]


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


def _resolve_blend_profile(config_payload, requested_mode, deep_available):
    profiles = dict((config_payload.get("blend_profiles") or {}))
    default_mode = str(requested_mode or config_payload.get("blend_mode_default") or "blended").strip() or "blended"
    mode_used = default_mode if default_mode in profiles else "blended"
    profile = dict(profiles.get(mode_used) or {})
    if mode_used == "deep_only" and not deep_available:
        mode_used = "heuristic_only"
        profile = dict(profiles.get("heuristic_only") or {})
    if not profile:
        profile = dict(config_payload.get("blend_weights") or {})
    return mode_used, profile


def _ticket_deep_payload(deep_payload, blend_mode):
    if blend_mode != "heuristic_only":
        return dict(deep_payload or {})
    muted = dict(deep_payload or {})
    muted["available"] = False
    muted["mainScores"] = {number: 0.0 for number in range(1, 36)}
    muted["bonusScores"] = {number: 0.0 for number in range(1, 13)}
    return muted


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
        protected = set(int(value) for value in keep_numbers[: max(0, int(carry_limit or 0))])
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


def _band_profile(numbers, number_max):
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


def _build_disagreement_analysis(heuristic_scores, deep_scores, config_payload):
    assembly_config = dict((config_payload or {}).get("assembly") or {})
    top_n = max(4, int(assembly_config.get("disagreement_top_n", 8) or 8))
    deep_ranked = _rank_numbers(deep_scores)
    if not deep_ranked or max(float(value) for value in deep_scores.values()) <= 0.0:
        return {"available": False, "score": 0.0, "level": "low", "top_n": top_n, "overlap_ratio": 1.0, "band_shift": 0.0, "center_shift": 0.0, "tail_shift": 0.0}
    heuristic_ranked = _rank_numbers(heuristic_scores)[:top_n]
    deep_ranked = deep_ranked[:top_n]
    scoped_n = max(1, min(len(heuristic_ranked), len(deep_ranked), top_n))
    heuristic_top = heuristic_ranked[:scoped_n]
    deep_top = deep_ranked[:scoped_n]
    overlap_ratio = len(set(heuristic_top).intersection(set(deep_top))) / float(scoped_n)
    heuristic_band = _band_profile(heuristic_top, 35)
    deep_band = _band_profile(deep_top, 35)
    band_shift = sum(abs(float(heuristic_band[band]) - float(deep_band[band])) for band in ("low", "mid", "high")) / 2.0
    center_shift = abs(mean(heuristic_top) - mean(deep_top)) / 35.0
    tail_span = max(2, scoped_n // 3)
    tail_shift = abs(mean(heuristic_top[-tail_span:]) - mean(deep_top[-tail_span:])) / 35.0
    score = max(0.0, min(1.0, 0.50 * (1.0 - overlap_ratio) + 0.25 * band_shift + 0.15 * center_shift + 0.10 * tail_shift))
    low_threshold = float(assembly_config.get("low_disagreement_threshold", 0.24) or 0.24)
    high_threshold = float(assembly_config.get("high_disagreement_threshold", 0.48) or 0.48)
    level = "high" if score >= high_threshold else "medium" if score >= low_threshold else "low"
    return {"available": True, "score": score, "level": level, "top_n": scoped_n, "overlap_ratio": overlap_ratio, "band_shift": band_shift, "center_shift": center_shift, "tail_shift": tail_shift}


def _build_cluster_transition(draws, snapshot, regime):
    slot_history = list((snapshot or {}).get("slotHistory") or list(draws or [])[-12:])
    recent_primary = slot_history[-4:]
    recent_secondary = slot_history[-8:]
    older_window = recent_secondary[:-len(recent_primary)] if recent_primary and len(recent_secondary) > len(recent_primary) else list(recent_secondary[:-1])

    def _average_center(scoped_draws, default_value):
        if not scoped_draws:
            return default_value
        return mean(sum(int(value) for value in list(draw.get("main") or [])) / 5.0 for draw in scoped_draws if draw.get("main"))

    def _average_tail(scoped_draws, default_value):
        if not scoped_draws:
            return default_value
        return mean(max(int(value) for value in list(draw.get("main") or [])) for draw in scoped_draws if draw.get("main"))

    baseline_center = _average_center(older_window or recent_secondary or recent_primary, 18.0)
    current_center = _average_center(recent_primary or recent_secondary, 18.0)
    baseline_tail = _average_tail(older_window or recent_secondary or recent_primary, 28.0)
    current_tail = _average_tail(recent_primary or recent_secondary, 28.0)
    center_shift = current_center - baseline_center
    tail_shift = current_tail - baseline_tail
    target_center = current_center + (center_shift * 0.45)
    target_tail = current_tail + (tail_shift * 0.40)
    regime_name = str((regime or {}).get("regime", "neutral"))
    if regime_name == "reset":
        target_center -= 0.8
        target_tail -= 1.0
    elif regime_name == "continuation":
        target_center += 0.6
        target_tail += 0.9
    if target_center >= baseline_center + 0.9:
        migration = "up"
    elif target_center <= baseline_center - 0.9:
        migration = "down"
    else:
        migration = "stable"
    return {"baselineCenter": baseline_center, "currentCenter": current_center, "targetCenter": target_center, "baselineTail": baseline_tail, "currentTail": current_tail, "targetTail": target_tail, "centerShift": center_shift, "tailShift": tail_shift, "bandMigration": migration}


def _cluster_number_score(number, cluster_transition):
    target_center = float((cluster_transition or {}).get("targetCenter", 18.0))
    target_tail = float((cluster_transition or {}).get("targetTail", 28.0))
    center_closeness = max(0.0, 1.0 - abs(float(number) - target_center) / 12.0)
    tail_closeness = max(0.0, 1.0 - abs(float(number) - target_tail) / 12.0)
    if number >= target_center:
        direction_score = tail_closeness
    else:
        direction_score = center_closeness
    return max(0.0, min(1.0, 0.55 * center_closeness + 0.45 * direction_score))


def _candidate_ticket_context(draws, analysis, source_scores=None, reference_candidates=None, mode_name="blended"):
    slot_history = list((analysis.get("snapshot") or {}).get("slotHistory") or [])
    ticket_deep = dict(analysis.get("ticketDeep") or analysis.get("deep") or {})
    return {
        "historicalDraws": slot_history or list(draws or [])[-24:],
        "pairContext": dict((analysis.get("snapshot") or {}).get("pairContext") or {}),
        "mainScores": dict(analysis.get("mainFinalScores") or {}),
        "bonusScores": dict(analysis.get("bonusFinalScores") or {}),
        "trackingSummary": tracking_engine.summarize_tracking_state(analysis.get("trackingState") or {}),
        "deepMainScores": dict(ticket_deep.get("mainScores") or {}),
        "deepBonusScores": dict(ticket_deep.get("bonusScores") or {}),
        "regime": dict(analysis.get("regime") or {}),
        "clusterTransition": dict(analysis.get("clusterTransition") or {}),
        "sourceScores": dict(source_scores or analysis.get("mainFinalScores") or {}),
        "referenceCandidates": list(reference_candidates or analysis.get("topMain") or []),
        "assemblyMode": str(mode_name or "blended"),
    }


def _mode_score_maps(mode_name, snapshot, regime, deep, main_final_scores, bonus_final_scores, tracking_main_scores, tracking_bonus_scores, cluster_transition):
    deep_main_scores = dict(deep.get("mainScores") or {})
    deep_bonus_scores = dict(deep.get("bonusScores") or {})
    heuristic_main_scores = dict(snapshot.get("mainHeuristicScores") or {})
    heuristic_bonus_scores = dict(snapshot.get("bonusHeuristicScores") or {})
    shared_top = set(_rank_numbers(heuristic_main_scores)[:8]).intersection(set(_rank_numbers(deep_main_scores)[:8]))
    if mode_name == "deep_led" and not bool(deep.get("available")):
        return None, None
    mode_main_scores = {}
    mode_bonus_scores = {}
    for number in range(1, 36):
        heuristic_value = float(heuristic_main_scores.get(number, 0.0))
        final_value = float(main_final_scores.get(number, 0.0))
        tracking_value = float(tracking_main_scores.get(number, 0.0))
        deep_value = float(deep_main_scores.get(number, 0.0))
        regime_value = float((regime.get("mainAdjustments") or {}).get(number, 0.0))
        cluster_value = float(_cluster_number_score(number, cluster_transition))
        agreement_value = 1.0 if number in shared_top else 0.0
        if mode_name == "heuristic_led":
            score = 0.70 * heuristic_value + 0.18 * final_value + 0.07 * regime_value + 0.05 * tracking_value
        elif mode_name == "deep_led":
            score = 0.72 * deep_value + 0.18 * heuristic_value + 0.10 * regime_value
        elif mode_name == "regime_shift":
            score = 0.44 * final_value + 0.22 * regime_value + 0.18 * cluster_value + 0.10 * heuristic_value + 0.06 * tracking_value
        elif mode_name == "conservative":
            score = 0.38 * final_value + 0.22 * heuristic_value + 0.20 * agreement_value + 0.10 * tracking_value + 0.10 * regime_value
        else:
            score = final_value
        mode_main_scores[number] = max(0.0, min(1.0, score))
    for number in range(1, 13):
        heuristic_value = float(heuristic_bonus_scores.get(number, 0.0))
        final_value = float(bonus_final_scores.get(number, 0.0))
        tracking_value = float(tracking_bonus_scores.get(number, 0.0))
        deep_value = float(deep_bonus_scores.get(number, 0.0))
        regime_value = float((regime.get("bonusAdjustments") or {}).get(number, 0.0))
        if mode_name == "heuristic_led":
            score = 0.62 * heuristic_value + 0.18 * final_value + 0.10 * regime_value + 0.10 * tracking_value
        elif mode_name == "deep_led":
            score = 0.68 * deep_value + 0.18 * heuristic_value + 0.14 * regime_value
        elif mode_name == "regime_shift":
            score = 0.42 * final_value + 0.22 * regime_value + 0.18 * heuristic_value + 0.18 * tracking_value
        elif mode_name == "conservative":
            score = 0.42 * final_value + 0.20 * heuristic_value + 0.20 * tracking_value + 0.18 * regime_value
        else:
            score = final_value
        mode_bonus_scores[number] = max(0.0, min(1.0, score))
    return mode_main_scores, mode_bonus_scores


def _selection_score(ticket, analysis, config_payload):
    breakdown = dict(ticket.get("qualityBreakdown") or {})
    main_scores = dict(analysis.get("mainFinalScores") or {})
    bonus_scores = dict(analysis.get("bonusFinalScores") or {})
    average_main_score = sum(float(main_scores.get(number, 0.0)) for number in list(ticket.get("main") or [])) / max(1.0, len(list(ticket.get("main") or [])))
    bonus_score = float(bonus_scores.get(int(ticket.get("special", 0) or 0), 0.0)) if isinstance(ticket.get("special"), int) else 0.0
    quality_norm = float(ticket.get("qualityScore", 0.0)) / 100.0
    assembly_config = dict((config_payload or {}).get("assembly") or {})
    disagreement = dict(analysis.get("disagreementAnalysis") or {})
    disagreement_level = str(disagreement.get("level", "low"))
    mode_name = str(ticket.get("assemblyMode", "blended"))
    mode_bias = float((assembly_config.get("mode_bias") or {}).get(mode_name, 1.0))
    disagreement_bonus = 0.0
    if disagreement_level == "high":
        if mode_name in {"heuristic_led", "deep_led", "regime_shift"}:
            disagreement_bonus += 1.20
        elif mode_name == "blended":
            disagreement_bonus -= 0.60
    elif disagreement_level == "low":
        if mode_name == "conservative":
            disagreement_bonus += 0.80
        elif mode_name == "blended":
            disagreement_bonus += 0.45
    composite = 34.0 * quality_norm + 16.0 * average_main_score + 4.0 * bonus_score + 12.0 * float(breakdown.get("regimeFit", 0.0)) + 10.0 * float(breakdown.get("clusterShiftFit", 0.0)) + 9.0 * float(breakdown.get("sourceConfidence", 0.0)) + 7.0 * float(breakdown.get("recentAlignment", 0.0)) + disagreement_bonus
    return composite * mode_bias


def _build_mode_reason(ticket, analysis):
    breakdown = dict(ticket.get("qualityBreakdown") or {})
    disagreement = dict(analysis.get("disagreementAnalysis") or {})
    notes = [
        f"Mode {ticket.get('assemblyMode', 'blended')} đạt selection score {float(ticket.get('selectionScore', 0.0)):.2f}.",
        f"regimeFit={float(breakdown.get('regimeFit', 0.0)):.2f}, clusterShiftFit={float(breakdown.get('clusterShiftFit', 0.0)):.2f}, sourceConfidence={float(breakdown.get('sourceConfidence', 0.0)):.2f}.",
    ]
    if disagreement.get("available"):
        notes.append(f"disagreement={float(disagreement.get('score', 0.0)):.2f} ({str(disagreement.get('level', 'low'))}) giữa ranking heuristic và deep.")
    return notes


def _generate_mode_candidate_tickets(mode_name, draws, analysis, config_payload):
    snapshot = dict(analysis.get("snapshot") or {})
    regime = dict(analysis.get("regime") or {})
    deep = dict(analysis.get("deep") or {})
    tracking_state = analysis.get("trackingState") or {}
    target = dict(analysis.get("target") or {})
    main_final_scores = dict(analysis.get("mainFinalScores") or {})
    bonus_final_scores = dict(analysis.get("bonusFinalScores") or {})
    tracking_main_scores = {number: tracking_engine.get_tracking_score(tracking_state, number, "main") for number in range(1, 36)}
    tracking_bonus_scores = {number: tracking_engine.get_tracking_score(tracking_state, number, "bonus") for number in range(1, 13)}
    cluster_transition = dict(analysis.get("clusterTransition") or {})
    mode_main_scores, mode_bonus_scores = _mode_score_maps(mode_name, snapshot, regime, deep, main_final_scores, bonus_final_scores, tracking_main_scores, tracking_bonus_scores, cluster_transition)
    if not mode_main_scores or not mode_bonus_scores:
        return None
    ranked_main = _rank_numbers(mode_main_scores)
    ranked_bonus = _rank_numbers(mode_bonus_scores)
    candidate_pool_size = int(((config_payload.get("candidate_pool") or {}).get("main") or 14))
    main_pool = ranked_main[: max(8, candidate_pool_size)]
    bonus_candidates = ranked_bonus[: max(4, int(((config_payload.get("candidate_pool") or {}).get("bonus") or 6)))]
    excluded_numbers = set(int(value) for value in list((tracking_state or {}).get("temporary_excluded_numbers") or []))
    keep_numbers = [int(value) for value in list((tracking_state or {}).get("kept_numbers") or [])]
    latest_draw = target.get("latest_actual_draw") or {}
    carry_limit = int(config_payload.get("same_day_carry_limit", 1) or 1)
    reference_candidates = list(analysis.get("topDeep") or []) if mode_name == "heuristic_led" else list(analysis.get("topHeuristic") or [])
    candidate_tickets = []
    ticket_context = _candidate_ticket_context(draws, analysis, source_scores=mode_main_scores, reference_candidates=reference_candidates, mode_name=mode_name)
    for index, template_numbers in enumerate(_build_candidate_templates(main_pool)):
        repaired_main = _repair_ticket_numbers(template_numbers + keep_numbers[:2], ranked_main, latest_draw, target, excluded_numbers, keep_numbers, carry_limit)
        if len(repaired_main) != 5:
            continue
        special = bonus_candidates[index % len(bonus_candidates)] if bonus_candidates else 1
        ticket = {"main": repaired_main, "special": int(special), "slot": str(target.get("target_slot", "")), "assemblyMode": mode_name}
        evaluation = ticket_evaluator.evaluate_ticket(ticket, ticket_context, config_payload)
        ticket["qualityScore"] = float(evaluation["qualityScore"])
        ticket["beautyScore"] = float(evaluation["beautyScore"])
        ticket["qualityBreakdown"] = dict(evaluation["breakdown"] or {})
        ticket["selectionScore"] = float(_selection_score(ticket, analysis, config_payload))
        ticket["whyMode"] = _build_mode_reason(ticket, analysis)
        candidate_tickets.append(ticket)
    candidate_tickets.sort(key=lambda ticket: (float(ticket.get("selectionScore", 0.0)), float(ticket.get("qualityScore", 0.0)), sum(float(main_final_scores.get(number, 0.0)) for number in list(ticket.get("main") or []))), reverse=True)
    return {"mode": mode_name, "rankedMain": ranked_main, "rankedBonus": ranked_bonus, "winner": candidate_tickets[0] if candidate_tickets else None, "candidates": candidate_tickets}


def build_prediction_snapshot(draws, target, tracking_state, config_payload, bundle_count=3, blend_mode=None):
    snapshot = feature_engineering.build_feature_snapshot(draws, target, tracking_state, config_payload)
    regime = regime_engine.classify_regime(draws, target, tracking_state, config_payload)
    main_numbers = list(range(1, int(config_payload.get("main_max", 35)) + 1))
    bonus_numbers = list(range(1, int(config_payload.get("bonus_max", 12)) + 1))
    deep = deep_model.score_candidates(
        main_numbers=main_numbers,
        bonus_numbers=bonus_numbers,
        draws=draws,
        target=target,
        tracking_state=tracking_state,
        config_payload=config_payload,
    )
    blend_mode_used, blend_profile = _resolve_blend_profile(config_payload, blend_mode, bool(deep.get("available")))
    ticket_deep = _ticket_deep_payload(deep, blend_mode_used)
    tracking_main_scores = {number: tracking_engine.get_tracking_score(tracking_state, number, "main") for number in main_numbers}
    tracking_bonus_scores = {number: tracking_engine.get_tracking_score(tracking_state, number, "bonus") for number in bonus_numbers}
    blend_weights = dict((blend_profile.get("main") or (config_payload.get("blend_weights") or {}).get("main") or {}))
    bonus_blend_weights = dict((blend_profile.get("bonus") or (config_payload.get("blend_weights") or {}).get("bonus") or {}))
    if blend_mode_used == "heuristic_only" or not bool(deep.get("available")):
        main_final_scores = dict(snapshot["mainHeuristicScores"] or {})
        bonus_final_scores = dict(snapshot["bonusHeuristicScores"] or {})
    elif blend_mode_used == "deep_only":
        main_final_scores = _normalize_map(dict(deep.get("mainScores") or {}))
        bonus_final_scores = _normalize_map(dict(deep.get("bonusScores") or {}))
    else:
        main_final_scores = _blend_scores(snapshot["mainHeuristicScores"], dict(deep.get("mainScores") or {}), tracking_main_scores, dict(regime.get("mainAdjustments") or {}), blend_weights, bool(deep.get("available")))
        bonus_final_scores = _blend_scores(snapshot["bonusHeuristicScores"], dict(deep.get("bonusScores") or {}), tracking_bonus_scores, dict(regime.get("bonusAdjustments") or {}), bonus_blend_weights, bool(deep.get("available")))
    top_main = _rank_numbers(main_final_scores)
    top_bonus = _rank_numbers(bonus_final_scores)
    top_heuristic = _rank_numbers(dict(snapshot.get("mainHeuristicScores") or {}))
    top_deep = _rank_numbers(dict(deep.get("mainScores") or {})) if deep.get("available") else []
    top_bonus_heuristic = _rank_numbers(dict(snapshot.get("bonusHeuristicScores") or {}))
    top_bonus_deep = _rank_numbers(dict(deep.get("bonusScores") or {})) if deep.get("available") else []
    disagreement_analysis = _build_disagreement_analysis(dict(snapshot.get("mainHeuristicScores") or {}), dict(deep.get("mainScores") or {}), config_payload)
    cluster_transition = _build_cluster_transition(draws, snapshot, regime)
    base_analysis = {
        "snapshot": snapshot,
        "regime": regime,
        "deep": deep,
        "ticketDeep": ticket_deep,
        "mainFinalScores": main_final_scores,
        "bonusFinalScores": bonus_final_scores,
        "blendModeUsed": blend_mode_used,
        "blendWeightsUsed": blend_profile,
        "topMain": top_main,
        "topBonus": top_bonus,
        "topHeuristic": top_heuristic,
        "topDeep": top_deep,
        "topBonusHeuristic": top_bonus_heuristic,
        "topBonusDeep": top_bonus_deep,
        "disagreementAnalysis": disagreement_analysis,
        "clusterTransition": cluster_transition,
        "trackingState": tracking_state,
        "target": target,
        "requestedBundleCount": max(1, int(bundle_count or 1)),
    }
    assembly_modes = []
    for mode_name in list((config_payload.get("assembly") or {}).get("modes") or ["blended"]):
        mode_payload = _generate_mode_candidate_tickets(str(mode_name), draws, base_analysis, config_payload)
        if mode_payload and mode_payload.get("winner"):
            assembly_modes.append(mode_payload)
    base_analysis["assemblyModes"] = assembly_modes
    base_analysis["candidateTickets"] = [mode_payload.get("winner") for mode_payload in assembly_modes if mode_payload.get("winner")]
    return base_analysis


def select_vip_tickets(analysis, config_payload):
    assembly_modes = list(analysis.get("assemblyModes") or [])
    if not assembly_modes:
        return {"primary": None, "backups": [], "assemblyMode": "blended", "whySelected": [], "assemblyVariants": [], "disagreementAnalysis": dict(analysis.get("disagreementAnalysis") or {}), "topHeuristicCandidates": list(analysis.get("topHeuristic") or []), "topDeepCandidates": list(analysis.get("topDeep") or [])}
    assembly_config = dict((config_payload or {}).get("assembly") or {})
    disagreement = dict(analysis.get("disagreementAnalysis") or {})
    allowed_modes = {str(mode_payload.get("mode", "")) for mode_payload in assembly_modes}
    if str(disagreement.get("level", "low")) == "high":
        scoped_allowlist = set(assembly_config.get("main_mode_allowlist_when_high_disagreement") or [])
        if scoped_allowlist:
            allowed_modes = scoped_allowlist
    variant_winners = [dict(mode_payload.get("winner") or {}) for mode_payload in assembly_modes if mode_payload.get("winner")]
    candidate_for_main = [candidate for candidate in variant_winners if str(candidate.get("assemblyMode", "")) in allowed_modes] or variant_winners
    candidate_for_main.sort(key=lambda item: (float(item.get("selectionScore", 0.0)), float(item.get("qualityScore", 0.0))), reverse=True)
    primary = candidate_for_main[0]
    pool_config = dict((config_payload or {}).get("candidate_pool") or {})
    backup_min = int(pool_config.get("backup_min", 2) or 2)
    backup_max = int(pool_config.get("backup_max", 5) or 5)
    total_ticket_goal = max(3, min(backup_max + 1, int(analysis.get("requestedBundleCount") or 3)))
    backup_goal = max(backup_min, min(backup_max, total_ticket_goal - 1))
    overlap_limit = int(assembly_config.get("diversity_overlap_limit", 3) or 3)
    selected_backups = []
    primary_set = set(int(value) for value in list(primary.get("main") or []))
    for candidate in variant_winners:
        if candidate == primary:
            continue
        main_set = set(int(value) for value in list(candidate.get("main") or []))
        overlap_with_primary = len(main_set.intersection(primary_set))
        overlap_with_backups = max((len(main_set.intersection(set(int(value) for value in list(existing.get("main") or [])))) for existing in selected_backups), default=0)
        if overlap_with_primary > overlap_limit or overlap_with_backups > overlap_limit + 1:
            continue
        selected_backups.append(candidate)
        if len(selected_backups) >= backup_goal:
            break
    if len(selected_backups) < backup_goal:
        fallback_pool = []
        for mode_payload in assembly_modes:
            fallback_pool.extend(list(mode_payload.get("candidates") or []))
        for candidate in fallback_pool:
            if candidate == primary or candidate in selected_backups:
                continue
            main_set = set(int(value) for value in list(candidate.get("main") or []))
            overlap_with_primary = len(main_set.intersection(primary_set))
            overlap_with_backups = max((len(main_set.intersection(set(int(value) for value in list(existing.get("main") or [])))) for existing in selected_backups), default=0)
            if overlap_with_primary > overlap_limit or overlap_with_backups > overlap_limit + 1:
                continue
            selected_backups.append(candidate)
            if len(selected_backups) >= backup_goal:
                break
    if len(selected_backups) < backup_goal:
        fallback_pool = []
        for mode_payload in assembly_modes:
            fallback_pool.extend(list(mode_payload.get("candidates") or []))
        for candidate in fallback_pool:
            if candidate == primary or candidate in selected_backups:
                continue
            selected_backups.append(candidate)
            if len(selected_backups) >= backup_goal:
                break
    why_selected = list(primary.get("whyMode") or [])
    mode_name = str(primary.get("assemblyMode", "blended"))
    if mode_name == "regime_shift":
        why_selected.append("Mode regime_shift thắng vì ticket bám dịch chuyển band/cluster tốt hơn lớp beauty thuần.")
    elif mode_name == "heuristic_led":
        why_selected.append("Mode heuristic_led giữ bộ chính chắc hơn khi cần tránh average ticket quá sớm.")
    elif mode_name == "deep_led":
        why_selected.append("Mode deep_led thắng nhờ source confidence và regime fit cùng bật mạnh.")
    elif mode_name == "conservative":
        why_selected.append("Mode conservative thắng vì heuristic và deep đang đồng thuận khá rõ.")
    if str(disagreement.get("level", "low")) == "high":
        why_selected.append("Disagreement cao nên predictor không collapse sớm vào một vé blended trung bình.")
    assembly_variants = [{"mode": str(mode_payload.get("mode", "")), "main": list(((mode_payload.get("winner") or {}).get("main") or [])), "special": int((mode_payload.get("winner") or {}).get("special", 0) or 0), "qualityScore": float((mode_payload.get("winner") or {}).get("qualityScore", 0.0)), "selectionScore": float((mode_payload.get("winner") or {}).get("selectionScore", 0.0))} for mode_payload in assembly_modes]
    return {"primary": primary, "backups": selected_backups[:backup_goal], "assemblyMode": mode_name, "whySelected": why_selected, "assemblyVariants": assembly_variants, "disagreementAnalysis": disagreement, "topHeuristicCandidates": list(analysis.get("topHeuristic") or []), "topDeepCandidates": list(analysis.get("topDeep") or [])}
