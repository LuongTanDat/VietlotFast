from __future__ import annotations

from itertools import combinations
from typing import Any

from src import regime_engine, ticket_evaluator


def _passes_basic_filters(ticket: list[int], context: dict[str, Any], predictor_config: dict[str, Any]) -> bool:
    filters = dict(predictor_config.get("filters") or {})
    ticket_sum = sum(ticket)
    ticket_range = ticket[-1] - ticket[0]
    if ticket_sum < int(filters.get("min_sum", 85)) or ticket_sum > int(filters.get("max_sum", 185)):
        return False
    if ticket_range < int(filters.get("min_range", 16)) or ticket_range > int(filters.get("max_range", 39)):
        return False
    last_draw = context.get("prediction_context", {}).get("last_draw")
    if last_draw is not None:
        overlap = len(set(ticket) & set(last_draw.main_numbers))
        if overlap > int(filters.get("max_last_draw_overlap", 3)):
            return False
    excluded_numbers = set((context.get("tracking_state") or {}).get("temporary_excluded_numbers") or [])
    if sum(1 for number in ticket if number in excluded_numbers) > int(filters.get("max_excluded_per_ticket", 1)):
        return False
    return True


def _rank_numbers(score_map: dict[int, float]) -> list[int]:
    return [int(number) for number, _score in sorted(score_map.items(), key=lambda item: (-float(item[1]), int(item[0])))]


def _cluster_number_score(number: int, cluster_transition: dict[str, Any]) -> float:
    target_center = float(cluster_transition.get("target_center", 22.5))
    target_tail = float(cluster_transition.get("target_tail", 40.0))
    center_closeness = max(0.0, 1.0 - abs(float(number) - target_center) / 18.0)
    tail_closeness = max(0.0, 1.0 - abs(float(number) - target_tail) / 18.0)
    if number >= target_center:
        direction_score = tail_closeness
    else:
        direction_score = center_closeness
    return max(0.0, min(1.0, 0.55 * center_closeness + 0.45 * direction_score))


def _build_candidate_pool(
    ranked_numbers: list[int],
    tracking_state: dict[str, Any],
    hot_numbers: list[int],
    pool_size: int,
) -> list[int]:
    candidate_pool: list[int] = []
    for number in [*(tracking_state.get("kept_numbers") or [])[:2], *hot_numbers[:4], *ranked_numbers]:
        candidate = int(number)
        if candidate not in candidate_pool:
            candidate_pool.append(candidate)
        if len(candidate_pool) >= pool_size:
            break
    return candidate_pool


def _mode_score_map(mode_name: str, scoring_context: dict[str, Any]) -> dict[int, float] | None:
    heuristic_scores = dict(scoring_context.get("heuristic_scores") or {})
    final_scores = dict(scoring_context.get("final_scores") or {})
    tracking_scores = dict(scoring_context.get("tracking_scores") or {})
    deep_scores = {
        int(number): float(score)
        for number, score in dict((scoring_context.get("deep_result") or {}).get("main_scores") or {}).items()
    }
    regime_context = dict(scoring_context.get("regime_context") or {})
    cluster_transition = dict(scoring_context.get("cluster_transition") or {})
    heuristic_ranked = list(scoring_context.get("heuristic_ranked_numbers") or [])
    deep_ranked = list(scoring_context.get("deep_ranked_numbers") or [])
    shared_top = set(heuristic_ranked[:10]) & set(deep_ranked[:10])

    if mode_name == "deep_led" and not bool((scoring_context.get("deep_result") or {}).get("available")):
        return None

    mode_scores: dict[int, float] = {}
    for number in range(1, 46):
        heuristic_value = float(heuristic_scores.get(number, 0.0))
        final_value = float(final_scores.get(number, 0.0))
        tracking_value = float(tracking_scores.get(number, 0.0))
        deep_value = float(deep_scores.get(number, 0.0))
        regime_value = float(regime_engine.score_number(number, regime_context))
        cluster_value = float(_cluster_number_score(number, cluster_transition))
        agreement_value = 1.0 if number in shared_top else 0.0
        if mode_name == "heuristic_led":
            score = 0.72 * heuristic_value + 0.16 * final_value + 0.07 * regime_value + 0.05 * tracking_value
        elif mode_name == "deep_led":
            score = 0.70 * deep_value + 0.18 * heuristic_value + 0.08 * regime_value + 0.04 * cluster_value
        elif mode_name == "regime_shift":
            score = 0.44 * final_value + 0.22 * regime_value + 0.18 * cluster_value + 0.10 * heuristic_value + 0.06 * tracking_value
        elif mode_name == "conservative":
            score = 0.40 * final_value + 0.22 * heuristic_value + 0.18 * agreement_value + 0.12 * tracking_value + 0.08 * regime_value
        else:
            score = final_value
        mode_scores[number] = max(0.0, min(1.0, score))
    return mode_scores


def _selection_score(
    ticket_result: dict[str, Any],
    final_scores: dict[int, float],
    mode_name: str,
    scoring_context: dict[str, Any],
    predictor_config: dict[str, Any],
) -> float:
    ticket = list(ticket_result.get("ticket") or [])
    breakdown = dict(ticket_result.get("breakdown") or {})
    average_number_score = sum(final_scores.get(number, 0.0) for number in ticket) / max(1, len(ticket))
    quality_norm = float(ticket_result.get("quality_score", 0.0)) / 100.0
    assembly_config = dict(predictor_config.get("assembly") or {})
    disagreement = dict(scoring_context.get("disagreement_analysis") or {})
    disagreement_level = str(disagreement.get("level", "low"))
    mode_bias = float((assembly_config.get("mode_bias") or {}).get(mode_name, 1.0))
    disagreement_bonus = 0.0
    if disagreement_level == "high":
        if mode_name in {"heuristic_led", "deep_led", "regime_shift"}:
            disagreement_bonus += 1.25
        elif mode_name == "blended":
            disagreement_bonus -= 0.60
    elif disagreement_level == "low":
        if mode_name == "conservative":
            disagreement_bonus += 0.85
        elif mode_name == "blended":
            disagreement_bonus += 0.45

    composite = (
        34.0 * quality_norm
        + 18.0 * average_number_score
        + 12.0 * float(breakdown.get("regime_fit", 0.0))
        + 10.0 * float(breakdown.get("cluster_shift_fit", 0.0))
        + 9.0 * float(breakdown.get("source_confidence", 0.0))
        + 7.0 * float(breakdown.get("recent_alignment", 0.0))
        + disagreement_bonus
    )
    return composite * mode_bias


def _build_mode_reason(candidate: dict[str, Any], scoring_context: dict[str, Any]) -> list[str]:
    breakdown = dict(candidate.get("breakdown") or {})
    disagreement = dict(scoring_context.get("disagreement_analysis") or {})
    notes = [
        f"Mode {candidate.get('assembly_mode', 'blended')} đạt selection score {float(candidate.get('selection_score', 0.0)):.2f}.",
        f"regime_fit={float(breakdown.get('regime_fit', 0.0)):.2f}, cluster_shift_fit={float(breakdown.get('cluster_shift_fit', 0.0)):.2f}, source_confidence={float(breakdown.get('source_confidence', 0.0)):.2f}.",
    ]
    if disagreement.get("available"):
        notes.append(
            f"disagreement={float(disagreement.get('score', 0.0)):.2f} ({str(disagreement.get('level', 'low'))}) giữa ranking heuristic và deep."
        )
    return notes


def _evaluate_mode(
    mode_name: str,
    scoring_context: dict[str, Any],
    tracking_state: dict[str, Any],
    predictor_config: dict[str, Any],
    requested_backup_count: int,
    top_candidate_count: int,
) -> dict[str, Any] | None:
    mode_scores = _mode_score_map(mode_name, scoring_context)
    if not mode_scores:
        return None
    ranked_numbers = _rank_numbers(mode_scores)
    hot_numbers = list((scoring_context.get("prediction_context") or {}).get("hot_numbers") or [])
    candidate_pool_size = int(predictor_config.get("candidate_pool_size", 12))
    candidate_pool = _build_candidate_pool(ranked_numbers, tracking_state, hot_numbers, candidate_pool_size)
    reference_candidates = (
        list(scoring_context.get("deep_ranked_numbers") or [])
        if mode_name == "heuristic_led"
        else list(scoring_context.get("heuristic_ranked_numbers") or [])
    )
    evaluation_context = {
        **scoring_context,
        "tracking_state": tracking_state,
        "deep_result": dict(scoring_context.get("ticket_deep_result") or scoring_context.get("deep_result") or {}),
        "source_scores": mode_scores,
        "reference_candidates": reference_candidates,
        "assembly_mode": mode_name,
    }
    candidate_results = []
    for combo in combinations(sorted(candidate_pool), 6):
        ticket = list(combo)
        if not _passes_basic_filters(ticket, evaluation_context, predictor_config):
            continue
        evaluation = ticket_evaluator.evaluate_ticket(ticket, evaluation_context, predictor_config)
        evaluation["selection_score"] = _selection_score(
            evaluation,
            dict(scoring_context.get("final_scores") or {}),
            mode_name,
            scoring_context,
            predictor_config,
        )
        evaluation["assembly_mode"] = mode_name
        evaluation["candidate_pool"] = list(candidate_pool)
        evaluation["source_top_candidates"] = ranked_numbers[:top_candidate_count]
        candidate_results.append(evaluation)

    if not candidate_results:
        fallback_ticket = sorted(candidate_pool[:6])
        evaluation = ticket_evaluator.evaluate_ticket(fallback_ticket, evaluation_context, predictor_config)
        evaluation["selection_score"] = _selection_score(
            evaluation,
            dict(scoring_context.get("final_scores") or {}),
            mode_name,
            scoring_context,
            predictor_config,
        )
        evaluation["assembly_mode"] = mode_name
        evaluation["candidate_pool"] = list(candidate_pool)
        evaluation["source_top_candidates"] = ranked_numbers[:top_candidate_count]
        candidate_results.append(evaluation)

    candidate_results.sort(key=lambda item: (float(item["selection_score"]), float(item["quality_score"])), reverse=True)
    winner = dict(candidate_results[0])
    winner["why_mode"] = _build_mode_reason(winner, scoring_context)
    return {
        "mode": mode_name,
        "ranked_numbers": ranked_numbers,
        "candidate_pool": candidate_pool,
        "winner": winner,
        "candidates": candidate_results[: max(2, requested_backup_count + 1)],
    }


def _build_selected_reasons(candidate: dict[str, Any], scoring_context: dict[str, Any], predictor_config: dict[str, Any]) -> list[str]:
    reasons = list(candidate.get("why_mode") or [])
    disagreement = dict(scoring_context.get("disagreement_analysis") or {})
    mode_name = str(candidate.get("assembly_mode", "blended"))
    if str(disagreement.get("level", "low")) == "high":
        allowlist = list((predictor_config.get("assembly") or {}).get("main_mode_allowlist_when_high_disagreement") or [])
        if allowlist and mode_name in allowlist:
            reasons.append("Main ticket tránh collapse sớm vào vé trung bình vì disagreement đang cao.")
    if mode_name == "regime_shift":
        reasons.append("Mode regime_shift thắng vì vé bám dịch chuyển band/cluster tốt hơn lớp beauty thuần.")
    elif mode_name == "heuristic_led":
        reasons.append("Mode heuristic_led giữ ticket chính an toàn hơn khi deep chưa thật sự đồng pha.")
    elif mode_name == "deep_led":
        reasons.append("Mode deep_led thắng nhờ source confidence và regime fit cùng lúc đủ mạnh.")
    elif mode_name == "conservative":
        reasons.append("Mode conservative thắng vì heuristic và deep đang đồng thuận khá tốt.")
    return reasons


def generate_tickets(
    scoring_context: dict[str, Any],
    tracking_state: dict[str, Any],
    predictor_config: dict[str, Any],
    backup_count: int | None = None,
) -> dict[str, Any]:
    top_candidate_count = int(predictor_config.get("top_candidate_count", 14))
    requested_backup_count = int(backup_count if backup_count is not None else predictor_config.get("backup_ticket_count", 3))
    assembly_config = dict(predictor_config.get("assembly") or {})
    enabled_modes = [str(mode) for mode in list(assembly_config.get("modes") or ["blended"])]
    mode_results = []
    fallback_candidates = []
    for mode_name in enabled_modes:
        mode_result = _evaluate_mode(
            mode_name,
            scoring_context=scoring_context,
            tracking_state=tracking_state,
            predictor_config=predictor_config,
            requested_backup_count=requested_backup_count,
            top_candidate_count=top_candidate_count,
        )
        if not mode_result:
            continue
        mode_results.append(mode_result)
        fallback_candidates.extend(list(mode_result.get("candidates") or []))

    if not mode_results:
        raise RuntimeError("No ticket assembly mode produced a valid Mega 6/45 candidate.")

    disagreement_level = str((scoring_context.get("disagreement_analysis") or {}).get("level", "low"))
    allowlist = set(enabled_modes)
    if disagreement_level == "high":
        scoped_allowlist = set(assembly_config.get("main_mode_allowlist_when_high_disagreement") or [])
        if scoped_allowlist:
            allowlist = scoped_allowlist

    variant_winners = [dict(mode_result["winner"]) for mode_result in mode_results]
    candidate_for_main = [candidate for candidate in variant_winners if candidate.get("assembly_mode") in allowlist] or variant_winners
    candidate_for_main.sort(key=lambda item: (float(item["selection_score"]), float(item["quality_score"])), reverse=True)
    main_ticket = candidate_for_main[0]

    selected = [main_ticket]
    overlap_limit = int(assembly_config.get("diversity_overlap_limit", 4) or 4)
    for candidate in variant_winners:
        if candidate == main_ticket:
            continue
        ticket = list(candidate.get("ticket") or [])
        if all(len(set(ticket) & set(existing.get("ticket") or [])) <= overlap_limit for existing in selected):
            selected.append(candidate)
        if len(selected) >= 1 + requested_backup_count:
            break

    if len(selected) < 1 + requested_backup_count:
        for candidate in fallback_candidates:
            if candidate in selected:
                continue
            ticket = list(candidate.get("ticket") or [])
            if all(len(set(ticket) & set(existing.get("ticket") or [])) <= overlap_limit for existing in selected):
                selected.append(candidate)
            if len(selected) >= 1 + requested_backup_count:
                break

    if len(selected) < 1 + requested_backup_count:
        for candidate in fallback_candidates:
            if candidate in selected:
                continue
            selected.append(candidate)
            if len(selected) >= 1 + requested_backup_count:
                break

    assembly_variants = [
        {
            "mode": str(mode_result.get("mode", "")),
            "ticket": list((mode_result.get("winner") or {}).get("ticket") or []),
            "quality_score": float((mode_result.get("winner") or {}).get("quality_score", 0.0)),
            "selection_score": float((mode_result.get("winner") or {}).get("selection_score", 0.0)),
            "candidate_count": len(mode_result.get("candidates") or []),
        }
        for mode_result in mode_results
    ]
    return {
        "candidate_pool": list(main_ticket.get("candidate_pool") or []),
        "top_main_candidates": list(scoring_context.get("top_main_candidates") or [])[:top_candidate_count],
        "top_heuristic_candidates": list(scoring_context.get("heuristic_ranked_numbers") or [])[:top_candidate_count],
        "top_deep_candidates": list(scoring_context.get("deep_ranked_numbers") or [])[:top_candidate_count],
        "disagreement_analysis": dict(scoring_context.get("disagreement_analysis") or {}),
        "assembly_variants": assembly_variants,
        "assembly_mode": str(main_ticket.get("assembly_mode", "blended")),
        "why_selected": _build_selected_reasons(main_ticket, scoring_context, predictor_config),
        "main_ticket": main_ticket,
        "backup_tickets": selected[1 : 1 + requested_backup_count],
    }
