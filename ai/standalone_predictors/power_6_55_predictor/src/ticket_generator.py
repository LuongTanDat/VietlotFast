from __future__ import annotations

from itertools import combinations
from typing import Any

from src import regime_engine, ticket_evaluator


def _passes_basic_filters(ticket: list[int], context: dict[str, Any], predictor_config: dict[str, Any]) -> bool:
    filters = dict(predictor_config.get("filters") or {})
    ticket_sum = sum(ticket)
    ticket_range = ticket[-1] - ticket[0]
    if ticket_sum < int(filters.get("min_sum", 110)) or ticket_sum > int(filters.get("max_sum", 240)):
        return False
    if ticket_range < int(filters.get("min_range", 20)) or ticket_range > int(filters.get("max_range", 50)):
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
    target_center = float(cluster_transition.get("target_center", 27.5))
    target_tail = float(cluster_transition.get("target_tail", 49.0))
    center_closeness = max(0.0, 1.0 - abs(float(number) - target_center) / 22.0)
    tail_closeness = max(0.0, 1.0 - abs(float(number) - target_tail) / 20.0)
    if number >= target_center:
        direction_score = tail_closeness
    else:
        direction_score = center_closeness
    return max(0.0, min(1.0, 0.55 * center_closeness + 0.45 * direction_score))


def _build_candidate_pool(
    tracking_state: dict[str, Any],
    ranked_numbers: list[int],
    pool_size: int,
    hot_numbers: list[int],
) -> list[int]:
    candidate_pool: list[int] = []
    for number in [*(tracking_state.get("kept_numbers") or [])[:2], *hot_numbers[:4], *ranked_numbers]:
        candidate = int(number)
        if candidate not in candidate_pool:
            candidate_pool.append(candidate)
        if len(candidate_pool) >= pool_size:
            break
    return candidate_pool


def _mode_score_maps(mode_name: str, scoring_context: dict[str, Any]) -> tuple[dict[int, float], dict[int, float]] | tuple[None, None]:
    heuristic_main_scores = dict(scoring_context.get("heuristic_main_scores") or {})
    heuristic_special_scores = dict(scoring_context.get("heuristic_special_scores") or {})
    final_main_scores = dict(scoring_context.get("final_main_scores") or {})
    final_special_scores = dict(scoring_context.get("final_special_scores") or {})
    tracking_main_scores = dict(scoring_context.get("tracking_scores_main") or {})
    tracking_special_scores = dict(scoring_context.get("tracking_scores_special") or {})
    deep_main_scores = {
        int(number): float(score)
        for number, score in dict((scoring_context.get("deep_result") or {}).get("main_scores") or {}).items()
    }
    deep_special_scores = {
        int(number): float(score)
        for number, score in dict((scoring_context.get("deep_result") or {}).get("special_scores") or {}).items()
    }
    regime_context = dict(scoring_context.get("regime_context") or {})
    cluster_transition = dict(scoring_context.get("cluster_transition") or {})
    heuristic_ranked = list(scoring_context.get("heuristic_ranked_numbers") or [])
    deep_ranked = list(scoring_context.get("deep_ranked_numbers") or [])
    shared_top = set(heuristic_ranked[:12]) & set(deep_ranked[:12])

    if mode_name == "deep_led" and not bool((scoring_context.get("deep_result") or {}).get("available")):
        return None, None

    main_scores: dict[int, float] = {}
    special_scores: dict[int, float] = {}
    for number in range(1, 56):
        heuristic_value = float(heuristic_main_scores.get(number, 0.0))
        final_value = float(final_main_scores.get(number, 0.0))
        tracking_value = float(tracking_main_scores.get(number, 0.0))
        deep_value = float(deep_main_scores.get(number, 0.0))
        regime_value = float(regime_engine.score_main_number(number, regime_context))
        cluster_value = float(_cluster_number_score(number, cluster_transition))
        agreement_value = 1.0 if number in shared_top else 0.0
        if mode_name == "heuristic_led":
            score = 0.68 * heuristic_value + 0.16 * final_value + 0.08 * regime_value + 0.08 * tracking_value
        elif mode_name == "deep_led":
            score = 0.66 * deep_value + 0.18 * heuristic_value + 0.08 * regime_value + 0.08 * cluster_value
        elif mode_name == "regime_shift":
            score = 0.40 * final_value + 0.20 * regime_value + 0.18 * cluster_value + 0.12 * heuristic_value + 0.10 * tracking_value
        elif mode_name == "conservative":
            score = 0.38 * final_value + 0.22 * heuristic_value + 0.18 * agreement_value + 0.12 * tracking_value + 0.10 * regime_value
        else:
            score = final_value
        main_scores[number] = max(0.0, min(1.0, score))

        heuristic_special = float(heuristic_special_scores.get(number, 0.0))
        final_special = float(final_special_scores.get(number, 0.0))
        tracking_special = float(tracking_special_scores.get(number, 0.0))
        deep_special = float(deep_special_scores.get(number, 0.0))
        regime_special = float(regime_engine.score_special_number(number, regime_context))
        if mode_name == "heuristic_led":
            special_score = 0.64 * heuristic_special + 0.18 * final_special + 0.10 * regime_special + 0.08 * tracking_special
        elif mode_name == "deep_led":
            special_score = 0.62 * deep_special + 0.18 * heuristic_special + 0.10 * regime_special + 0.10 * tracking_special
        elif mode_name == "regime_shift":
            special_score = 0.42 * final_special + 0.22 * regime_special + 0.18 * heuristic_special + 0.18 * tracking_special
        elif mode_name == "conservative":
            special_score = 0.42 * final_special + 0.22 * heuristic_special + 0.18 * tracking_special + 0.18 * regime_special
        else:
            special_score = final_special
        special_scores[number] = max(0.0, min(1.0, special_score))
    return main_scores, special_scores


def _pick_best_special(
    ticket: list[int],
    ranked_specials: list[int],
    special_scores: dict[int, float],
) -> tuple[int | None, list[int]]:
    selected = [number for number in ranked_specials if int(number) not in set(ticket)]
    if not selected:
        return None, []
    primary = int(selected[0])
    backups = sorted((int(number) for number in selected[1:5]), key=lambda number: (-float(special_scores.get(number, 0.0)), number))
    return primary, backups[:3]


def _selection_score(
    ticket_result: dict[str, Any],
    final_main_scores: dict[int, float],
    final_special_scores: dict[int, float],
    mode_name: str,
    scoring_context: dict[str, Any],
    predictor_config: dict[str, Any],
) -> float:
    ticket = list(ticket_result.get("ticket") or [])
    special = ticket_result.get("special")
    breakdown = dict(ticket_result.get("breakdown") or {})
    average_main_score = sum(final_main_scores.get(number, 0.0) for number in ticket) / max(1, len(ticket))
    special_score = final_special_scores.get(int(special), 0.0) if special is not None else 0.0
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
        32.0 * quality_norm
        + 16.0 * average_main_score
        + 4.0 * special_score
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
    main_scores, special_scores = _mode_score_maps(mode_name, scoring_context)
    if not main_scores or not special_scores:
        return None
    ranked_numbers = _rank_numbers(main_scores)
    ranked_specials = _rank_numbers(special_scores)
    hot_numbers = list((scoring_context.get("prediction_context") or {}).get("hot_numbers") or [])
    candidate_pool_size = int(predictor_config.get("candidate_pool_size", 14))
    max_ticket_combinations = int(predictor_config.get("max_ticket_combinations", 900))
    enabled_modes = list((predictor_config.get("assembly") or {}).get("modes") or ["blended"])
    per_mode_limit = max(60, max_ticket_combinations // max(1, len(enabled_modes)))
    candidate_pool = _build_candidate_pool(tracking_state, ranked_numbers, candidate_pool_size, hot_numbers)
    reference_candidates = (
        list(scoring_context.get("deep_ranked_numbers") or [])
        if mode_name == "heuristic_led"
        else list(scoring_context.get("heuristic_ranked_numbers") or [])
    )
    evaluation_context = {
        **scoring_context,
        "tracking_state": tracking_state,
        "deep_result": dict(scoring_context.get("ticket_deep_result") or scoring_context.get("deep_result") or {}),
        "source_scores": main_scores,
        "reference_candidates": reference_candidates,
        "assembly_mode": mode_name,
    }

    candidate_results = []
    for combo_index, combo in enumerate(combinations(candidate_pool, 6)):
        if combo_index >= per_mode_limit:
            break
        ticket = list(combo)
        if not _passes_basic_filters(ticket, evaluation_context, predictor_config):
            continue
        special, special_backups = _pick_best_special(ticket, ranked_specials, special_scores)
        evaluation = ticket_evaluator.evaluate_ticket(ticket, special, evaluation_context, predictor_config)
        evaluation["special_backups"] = special_backups
        evaluation["selection_score"] = _selection_score(
            evaluation,
            dict(scoring_context.get("final_main_scores") or {}),
            dict(scoring_context.get("final_special_scores") or {}),
            mode_name,
            scoring_context,
            predictor_config,
        )
        evaluation["assembly_mode"] = mode_name
        evaluation["candidate_pool"] = list(candidate_pool)
        evaluation["source_top_candidates"] = ranked_numbers[:top_candidate_count]
        evaluation["source_top_specials"] = ranked_specials[:10]
        candidate_results.append(evaluation)

    if not candidate_results:
        fallback_ticket = sorted(candidate_pool[:6])
        special, special_backups = _pick_best_special(fallback_ticket, ranked_specials, special_scores)
        evaluation = ticket_evaluator.evaluate_ticket(fallback_ticket, special, evaluation_context, predictor_config)
        evaluation["special_backups"] = special_backups
        evaluation["selection_score"] = _selection_score(
            evaluation,
            dict(scoring_context.get("final_main_scores") or {}),
            dict(scoring_context.get("final_special_scores") or {}),
            mode_name,
            scoring_context,
            predictor_config,
        )
        evaluation["assembly_mode"] = mode_name
        evaluation["candidate_pool"] = list(candidate_pool)
        evaluation["source_top_candidates"] = ranked_numbers[:top_candidate_count]
        evaluation["source_top_specials"] = ranked_specials[:10]
        candidate_results.append(evaluation)

    candidate_results.sort(key=lambda item: (float(item["selection_score"]), float(item["quality_score"])), reverse=True)
    winner = dict(candidate_results[0])
    winner["why_mode"] = _build_mode_reason(winner, scoring_context)
    return {
        "mode": mode_name,
        "ranked_numbers": ranked_numbers,
        "ranked_specials": ranked_specials,
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
            reasons.append("Main ticket giữ nhiều ứng viên nguồn riêng thay vì ép trung bình sớm khi disagreement còn cao.")
    if mode_name == "regime_shift":
        reasons.append("Mode regime_shift thắng vì vé theo dịch chuyển band/cluster tốt hơn lớp beauty thuần.")
    elif mode_name == "heuristic_led":
        reasons.append("Mode heuristic_led giữ ticket chính ổn định hơn trong game rộng số như Power 6/55.")
    elif mode_name == "deep_led":
        reasons.append("Mode deep_led thắng vì source confidence và regime fit cùng bật đủ mạnh.")
    elif mode_name == "conservative":
        reasons.append("Mode conservative thắng vì heuristic và deep đang đồng pha khá tốt.")
    return reasons


def generate_tickets(
    scoring_context: dict[str, Any],
    tracking_state: dict[str, Any],
    predictor_config: dict[str, Any],
    backup_count: int | None = None,
) -> dict[str, Any]:
    top_candidate_count = int(predictor_config.get("top_candidate_count", 16))
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
        raise RuntimeError("No ticket assembly mode produced a valid Power 6/55 candidate.")

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

    selected_special = int(main_ticket["special"]) if main_ticket.get("special") is not None else None
    selected_special_backups = [number for number in list(main_ticket.get("special_backups") or []) if number != selected_special][:3]
    assembly_variants = [
        {
            "mode": str(mode_result.get("mode", "")),
            "ticket": list((mode_result.get("winner") or {}).get("ticket") or []),
            "special": (mode_result.get("winner") or {}).get("special"),
            "quality_score": float((mode_result.get("winner") or {}).get("quality_score", 0.0)),
            "selection_score": float((mode_result.get("winner") or {}).get("selection_score", 0.0)),
            "candidate_count": len(mode_result.get("candidates") or []),
        }
        for mode_result in mode_results
    ]
    return {
        "candidate_pool": list(main_ticket.get("candidate_pool") or []),
        "top_main_candidates": list(scoring_context.get("top_main_candidates") or [])[:top_candidate_count],
        "top_special_candidates": list(scoring_context.get("top_special_candidates") or [])[:10],
        "top_heuristic_candidates": list(scoring_context.get("heuristic_ranked_numbers") or [])[:top_candidate_count],
        "top_deep_candidates": list(scoring_context.get("deep_ranked_numbers") or [])[:top_candidate_count],
        "top_heuristic_special_candidates": list(scoring_context.get("heuristic_ranked_specials") or [])[:10],
        "top_deep_special_candidates": list(scoring_context.get("deep_ranked_specials") or [])[:10],
        "disagreement_analysis": dict(scoring_context.get("disagreement_analysis") or {}),
        "assembly_variants": assembly_variants,
        "assembly_mode": str(main_ticket.get("assembly_mode", "blended")),
        "why_selected": _build_selected_reasons(main_ticket, scoring_context, predictor_config),
        "main_ticket": main_ticket,
        "backup_tickets": selected[1 : 1 + requested_backup_count],
        "special": selected_special,
        "special_backups": selected_special_backups,
    }
