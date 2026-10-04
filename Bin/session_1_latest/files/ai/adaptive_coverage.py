from __future__ import annotations

import hashlib
import heapq
import itertools
import json
import math
import random
from collections import defaultdict
from typing import Any, Mapping, Sequence

from ai.evaluation.probability import scores_to_probabilities

try:
    import numpy as np
except ImportError:  # pragma: no cover - the standard-library fallback remains fully supported.
    np = None


ADAPTIVE_COVERAGE_VERSION = "adaptive_coverage_v1"
ADAPTIVE_CANDIDATE_METHOD = "gumbel_top_k_without_replacement"

GAME_SPECS: dict[str, dict[str, Any]] = {
    "LOTO_5_35": {
        "universeMin": 1,
        "universeMax": 35,
        "drawSize": 5,
        "defaultPickSize": 5,
        "specialMin": 1,
        "specialMax": 12,
        "specialExcludesMain": False,
    },
    "LOTO_6_45": {
        "universeMin": 1,
        "universeMax": 45,
        "drawSize": 6,
        "defaultPickSize": 6,
        "specialMin": 0,
        "specialMax": 0,
        "specialExcludesMain": False,
    },
    "LOTO_6_55": {
        "universeMin": 1,
        "universeMax": 55,
        "drawSize": 6,
        "defaultPickSize": 6,
        "specialMin": 1,
        "specialMax": 55,
        "specialExcludesMain": True,
    },
    "KENO": {
        "universeMin": 1,
        "universeMax": 80,
        "drawSize": 20,
        "defaultPickSize": 5,
        "specialMin": 0,
        "specialMax": 0,
        "specialExcludesMain": False,
    },
    "MAX_3D": {
        "universeMin": 0,
        "universeMax": 999,
        "drawSize": 21,
        "defaultPickSize": 2,
        "specialMin": 0,
        "specialMax": 0,
        "specialExcludesMain": False,
    },
    "MAX_3D_PRO": {
        "universeMin": 0,
        "universeMax": 999,
        "drawSize": 20,
        "defaultPickSize": 2,
        "specialMin": 0,
        "specialMax": 0,
        "specialExcludesMain": False,
    },
}

RISK_PROFILES = {
    "stable": {"exploration": 0.20, "quality": 0.55, "coverage": 0.32, "overlap": 0.13},
    "balanced": {"exploration": 0.15, "quality": 0.48, "coverage": 0.36, "overlap": 0.16},
    "aggressive": {"exploration": 0.10, "quality": 0.62, "coverage": 0.26, "overlap": 0.12},
}


def candidate_pool_size(bundle_count: int) -> int:
    requested = max(1, int(bundle_count or 1))
    if requested <= 1:
        return 500
    if requested <= 3:
        return 1000
    if requested <= 6:
        return 1500
    return 2000


def _normalize_risk_mode(raw: Any) -> str:
    value = str(raw or "balanced").strip().lower().replace("-", "_")
    aliases = {"on_dinh": "stable", "can_bang": "balanced", "tan_cong": "aggressive"}
    value = aliases.get(value, value)
    return value if value in RISK_PROFILES else "balanced"


def _coerce_number(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_ranking(payload: Mapping[str, Any], field_names: Sequence[str], minimum: int, maximum: int) -> list[int]:
    output: list[int] = []
    seen: set[int] = set()
    for field_name in field_names:
        for item in list(payload.get(field_name) or []):
            value = item.get("number") if isinstance(item, Mapping) else item
            number = _coerce_number(value)
            if number is None or number < minimum or number > maximum or number in seen:
                continue
            seen.add(number)
            output.append(number)
    return output


def _ranking_score_map(ranking: Sequence[int], minimum: int, maximum: int) -> dict[int, float]:
    size = len(ranking)
    scores = {number: 0.0 for number in range(minimum, maximum + 1)}
    for index, number in enumerate(ranking):
        if minimum <= int(number) <= maximum:
            scores[int(number)] = float(size - index)
    return scores


def _edge_gate(payload: Mapping[str, Any], spec: Mapping[str, Any], pick_size: int) -> dict[str, Any]:
    universe_size = int(spec["universeMax"]) - int(spec["universeMin"]) + 1
    baseline_rate = float(spec["drawSize"]) / float(universe_size)
    backtest = dict(payload.get("backtest") or {})
    try:
        observed_rate = float(backtest.get("avgHitRate") or 0.0)
    except (TypeError, ValueError):
        observed_rate = 0.0
    try:
        average_hits = float(backtest.get("avgHits") or 0.0)
    except (TypeError, ValueError):
        average_hits = 0.0
    try:
        samples = max(0, int(backtest.get("samples") or 0))
    except (TypeError, ValueError):
        samples = 0

    effective_trials = max(1, samples * max(1, int(pick_size)))
    bounded_rate = min(1.0, max(0.0, observed_rate))
    standard_error = math.sqrt(max(1e-12, bounded_rate * (1.0 - bounded_rate)) / effective_trials)
    lower_rate = max(0.0, bounded_rate - 1.96 * standard_error)
    upper_rate = min(1.0, bounded_rate + 1.96 * standard_error)
    has_consistent_backtest = observed_rate <= 0.0 or average_hits > 0.0
    if samples < 30 or observed_rate <= 0.0 or not has_consistent_backtest:
        state = "unverified"
    elif lower_rate > baseline_rate:
        state = "verified_edge"
    elif upper_rate < baseline_rate:
        state = "below_random"
    else:
        state = "unverified"
    return {
        "state": state,
        "baselineHitRate": round(baseline_rate, 8),
        "observedHitRate": round(observed_rate, 8),
        "observedAverageHits": round(average_hits, 8),
        "lower95": round(lower_rate, 8),
        "upper95": round(upper_rate, 8),
        "samples": samples,
        "evidenceConsistent": has_consistent_backtest,
    }


def _exploration_rate(payload: Mapping[str, Any], risk_mode: str, gate: Mapping[str, Any]) -> float:
    rate = float(RISK_PROFILES[risk_mode]["exploration"])
    gate_state = str(gate.get("state") or "unverified")
    if gate_state == "below_random":
        rate = max(rate, 0.65)
    elif gate_state != "verified_edge":
        rate = max(rate, 0.35)
    meta_state = str(payload.get("metaState") or (payload.get("onlineMeta") or {}).get("metaState") or "").lower()
    if meta_state == "volatile":
        rate += 0.08
    elif meta_state == "warming":
        rate += 0.04
    return min(0.80, max(0.05, rate))


def _build_probability_map(
    ranking: Sequence[int],
    minimum: int,
    maximum: int,
    draw_size: int,
    exploration_rate: float,
) -> dict[int, float]:
    scores = _ranking_score_map(ranking, minimum, maximum)
    calibrated = scores_to_probabilities(scores, draw_size, minimum, maximum)
    baseline = float(draw_size) / float(maximum - minimum + 1)
    return {
        number: (1.0 - exploration_rate) * float(calibrated.get(number, 0.0)) + exploration_rate * baseline
        for number in range(minimum, maximum + 1)
    }


def _stable_seed(payload: Mapping[str, Any], risk_mode: str, probabilities: Mapping[int, float]) -> int:
    seed_payload = {
        "version": ADAPTIVE_COVERAGE_VERSION,
        "type": str(payload.get("type") or ""),
        "engine": str(payload.get("engine") or ""),
        "riskMode": risk_mode,
        "latestKy": str(payload.get("latestKy") or ""),
        "nextKy": str(payload.get("nextKy") or ""),
        "bundleCount": int(payload.get("bundleCount") or 1),
        "pickSize": int(payload.get("pickSize") or 0),
        "probabilities": [[int(key), round(float(value), 10)] for key, value in sorted(probabilities.items())],
    }
    digest = hashlib.sha256(json.dumps(seed_payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFF


def _gumbel_top_k(
    probability_map: Mapping[int, float],
    pick_size: int,
    rng: random.Random,
    excluded: set[int] | None = None,
) -> list[int]:
    excluded = excluded or set()
    scored = []
    for number, probability in probability_map.items():
        if int(number) in excluded:
            continue
        uniform = min(1.0 - 1e-15, max(1e-15, rng.random()))
        gumbel = -math.log(-math.log(uniform))
        scored.append((math.log(max(float(probability), 1e-15)) + gumbel, int(number)))
    selected = heapq.nlargest(max(1, int(pick_size)), scored, key=lambda item: (item[0], -item[1]))
    return sorted(number for _, number in selected)


def _ticket_key(ticket: Mapping[str, Any]) -> tuple[tuple[int, ...], int | None]:
    return tuple(sorted(int(value) for value in list(ticket.get("main") or []))), _coerce_number(ticket.get("special"))


def _ticket_quality(ticket: Mapping[str, Any], main_probabilities: Mapping[int, float], special_probabilities: Mapping[int, float]) -> float:
    main = list(ticket.get("main") or [])
    if not main:
        return -1e9
    quality = sum(math.log(max(float(main_probabilities.get(int(number), 0.0)), 1e-15)) for number in main) / len(main)
    special = _coerce_number(ticket.get("special"))
    if special is not None and special_probabilities:
        quality += 0.15 * math.log(max(float(special_probabilities.get(special, 0.0)), 1e-15))
    return quality


def _normalize_existing_ticket(ticket: Mapping[str, Any], spec: Mapping[str, Any], pick_size: int) -> dict[str, Any] | None:
    minimum = int(spec["universeMin"])
    maximum = int(spec["universeMax"])
    main = sorted({int(number) for value in list(ticket.get("main") or []) if (number := _coerce_number(value)) is not None and minimum <= number <= maximum})
    if len(main) != pick_size:
        return None
    special = _coerce_number(ticket.get("special"))
    special_min = int(spec.get("specialMin") or 0)
    special_max = int(spec.get("specialMax") or 0)
    if special_min and not (special_min <= int(special or -1) <= special_max):
        special = None
    if bool(spec.get("specialExcludesMain")) and special in main:
        return None
    return {"main": main, "special": special}


def _generate_candidates(
    payload: Mapping[str, Any],
    spec: Mapping[str, Any],
    main_probabilities: Mapping[int, float],
    special_probabilities: Mapping[int, float],
    pick_size: int,
    requested_count: int,
    rng: random.Random,
    numpy_seed: int | None = None,
) -> tuple[list[dict[str, Any]], int, int]:
    universe_size = int(spec["universeMax"]) - int(spec["universeMin"]) + 1
    special_options = max(1, int(spec.get("specialMax") or 0) - int(spec.get("specialMin") or 0) + 1)
    maximum_unique = math.comb(universe_size, pick_size) * special_options
    target_count = min(maximum_unique, max(1, int(requested_count)))
    candidates: dict[tuple[tuple[int, ...], int | None], dict[str, Any]] = {}

    for raw_ticket in list(payload.get("tickets") or []):
        if not isinstance(raw_ticket, Mapping):
            continue
        normalized = _normalize_existing_ticket(raw_ticket, spec, pick_size)
        if normalized:
            candidates[_ticket_key(normalized)] = normalized

    attempts = 0
    max_attempts = max(500, target_count * 8)
    if np is not None and universe_size >= 200 and not special_probabilities:
        number_order = list(range(int(spec["universeMin"]), int(spec["universeMax"]) + 1))
        log_probabilities = np.log(
            np.maximum(
                np.asarray([float(main_probabilities[number]) for number in number_order], dtype=np.float64),
                1e-15,
            )
        )
        numpy_rng = np.random.default_rng(int(numpy_seed or 0))
        while len(candidates) < target_count and attempts < max_attempts:
            batch_size = min(256, max_attempts - attempts, max(32, target_count - len(candidates)))
            gumbels = numpy_rng.gumbel(size=(batch_size, universe_size))
            top_indexes = np.argpartition(log_probabilities + gumbels, -pick_size, axis=1)[:, -pick_size:]
            attempts += batch_size
            for row in top_indexes:
                main = sorted(number_order[int(index)] for index in row.tolist())
                ticket = {"main": main, "special": None}
                candidates.setdefault(_ticket_key(ticket), ticket)
                if len(candidates) >= target_count:
                    break

    while len(candidates) < target_count and attempts < max_attempts:
        attempts += 1
        main = _gumbel_top_k(main_probabilities, pick_size, rng)
        special = None
        if special_probabilities:
            excluded = set(main) if bool(spec.get("specialExcludesMain")) else set()
            special_values = _gumbel_top_k(special_probabilities, 1, rng, excluded=excluded)
            special = special_values[0] if special_values else None
        ticket = {"main": main, "special": special}
        candidates.setdefault(_ticket_key(ticket), ticket)

    if len(candidates) < target_count and maximum_unique <= 5000:
        number_space = range(int(spec["universeMin"]), int(spec["universeMax"]) + 1)
        special_space = list(special_probabilities) if special_probabilities else [None]
        for main_values in itertools.combinations(number_space, pick_size):
            for special in special_space:
                if bool(spec.get("specialExcludesMain")) and special in main_values:
                    continue
                ticket = {"main": list(main_values), "special": special}
                candidates.setdefault(_ticket_key(ticket), ticket)
                if len(candidates) >= target_count:
                    break
            if len(candidates) >= target_count:
                break

    output = list(candidates.values())
    for ticket in output:
        ticket["_qualityRaw"] = _ticket_quality(ticket, main_probabilities, special_probabilities)
    return output, target_count, attempts


def _select_portfolio(
    candidates: Sequence[Mapping[str, Any]],
    bundle_count: int,
    pick_size: int,
    main_probabilities: Mapping[int, float],
    special_probabilities: Mapping[int, float],
    risk_mode: str,
) -> list[dict[str, Any]]:
    if not candidates:
        return []
    quality_values = [float(candidate.get("_qualityRaw") or -1e9) for candidate in candidates]
    quality_min = min(quality_values)
    quality_max = max(quality_values)
    quality_span = max(1e-12, quality_max - quality_min)
    max_main_mass = max(
        sum(float(main_probabilities.get(int(number), 0.0)) for number in list(candidate.get("main") or []))
        for candidate in candidates
    ) or 1.0
    weights = RISK_PROFILES[risk_mode]
    coverage_counts: defaultdict[int, int] = defaultdict(int)
    special_counts: defaultdict[int, int] = defaultdict(int)
    remaining = list(candidates)
    selected: list[dict[str, Any]] = []

    while remaining and len(selected) < max(1, int(bundle_count)):
        best_index = 0
        best_rank: tuple[float, float, tuple[tuple[int, ...], int | None]] | None = None
        best_metrics: dict[str, float] = {}
        for index, candidate in enumerate(remaining):
            main = [int(value) for value in list(candidate.get("main") or [])]
            quality_norm = (float(candidate.get("_qualityRaw") or quality_min) - quality_min) / quality_span
            coverage_gain = sum(
                float(main_probabilities.get(number, 0.0)) / (1.0 + coverage_counts[number])
                for number in main
            ) / max_main_mass
            special = _coerce_number(candidate.get("special"))
            if special is not None and special_probabilities:
                coverage_gain += 0.12 * float(special_probabilities.get(special, 0.0)) / (1.0 + special_counts[special])
            overlaps = [len(set(main) & set(ticket.get("main") or [])) / max(1, pick_size) for ticket in selected]
            max_overlap = max(overlaps) if overlaps else 0.0
            portfolio_score = (
                float(weights["quality"]) * quality_norm
                + float(weights["coverage"]) * coverage_gain
                - float(weights["overlap"]) * max_overlap
            )
            rank = (portfolio_score, quality_norm, _ticket_key(candidate))
            if best_rank is None or rank > best_rank:
                best_index = index
                best_rank = rank
                best_metrics = {
                    "adaptiveScore": portfolio_score,
                    "qualityScore": quality_norm,
                    "coverageGain": coverage_gain,
                    "maxOverlap": max_overlap,
                }
        chosen = dict(remaining.pop(best_index))
        chosen.pop("_qualityRaw", None)
        for key, value in best_metrics.items():
            chosen[key] = round(float(value), 6)
        selected.append(chosen)
        for number in list(chosen.get("main") or []):
            coverage_counts[int(number)] += 1
        special = _coerce_number(chosen.get("special"))
        if special is not None:
            special_counts[special] += 1
    return selected


def _portfolio_summary(tickets: Sequence[Mapping[str, Any]], probabilities: Mapping[int, float]) -> dict[str, Any]:
    main_sets = [set(int(value) for value in list(ticket.get("main") or [])) for ticket in tickets]
    overlaps = []
    for left_index in range(len(main_sets)):
        for right_index in range(left_index + 1, len(main_sets)):
            overlaps.append(len(main_sets[left_index] & main_sets[right_index]))
    covered = set().union(*main_sets) if main_sets else set()
    return {
        "uniqueMainNumbers": len(covered),
        "weightedCoverage": round(sum(float(probabilities.get(number, 0.0)) for number in covered), 8),
        "averagePairwiseOverlap": round(sum(overlaps) / len(overlaps), 6) if overlaps else 0.0,
        "maxPairwiseOverlap": max(overlaps) if overlaps else 0,
    }


def apply_adaptive_coverage(payload: Mapping[str, Any], risk_mode: Any = "balanced") -> dict[str, Any]:
    result = dict(payload or {})
    type_key = str(result.get("type") or "").strip().upper()
    spec = GAME_SPECS.get(type_key)
    if not spec or not bool(result.get("ready", True)):
        return result

    normalized_risk = _normalize_risk_mode(risk_mode or result.get("riskMode"))
    bundle_count = max(1, int(result.get("bundleCount") or len(result.get("tickets") or []) or 1))
    pick_size = max(1, int(result.get("pickSize") or spec["defaultPickSize"]))
    universe_min = int(spec["universeMin"])
    universe_max = int(spec["universeMax"])
    pick_size = min(pick_size, universe_max - universe_min + 1)

    main_ranking = _extract_ranking(
        result,
        ("topRanking", "top_main_candidates", "topMainRanking"),
        universe_min,
        universe_max,
    )
    if not main_ranking:
        return result

    gate = _edge_gate(result, spec, pick_size)
    exploration = _exploration_rate(result, normalized_risk, gate)
    main_probabilities = _build_probability_map(
        main_ranking,
        universe_min,
        universe_max,
        int(spec["drawSize"]),
        exploration,
    )

    special_probabilities: dict[int, float] = {}
    special_min = int(spec.get("specialMin") or 0)
    special_max = int(spec.get("specialMax") or 0)
    if special_min and special_max >= special_min:
        special_ranking = _extract_ranking(
            result,
            ("topSpecialRanking", "top_bonus_candidates", "topSpecialCandidates"),
            special_min,
            special_max,
        )
        if not special_ranking:
            special_ranking = list(range(special_min, special_max + 1))
        special_probabilities = _build_probability_map(
            special_ranking,
            special_min,
            special_max,
            1,
            exploration,
        )

    requested_candidates = candidate_pool_size(bundle_count)
    seed = _stable_seed(result, normalized_risk, main_probabilities)
    candidates, target_candidates, attempts = _generate_candidates(
        result,
        spec,
        main_probabilities,
        special_probabilities,
        pick_size,
        requested_candidates,
        random.Random(seed),
        numpy_seed=seed,
    )
    selected = _select_portfolio(
        candidates,
        bundle_count,
        pick_size,
        main_probabilities,
        special_probabilities,
        normalized_risk,
    )
    if len(selected) < bundle_count:
        return result

    probability_rows = [
        {"number": int(number), "probability": round(float(probability), 8)}
        for number, probability in sorted(main_probabilities.items(), key=lambda item: (-item[1], item[0]))[:50]
    ]
    result["tickets"] = selected
    result["bundleCount"] = len(selected)
    result["predictionMode"] = "normal"
    result["adaptiveCoverageVersion"] = ADAPTIVE_COVERAGE_VERSION
    result["adaptiveProbabilityTop"] = probability_rows
    if len(main_probabilities) <= 100:
        result["adaptiveProbabilities"] = {str(number): round(float(value), 10) for number, value in main_probabilities.items()}
    if special_probabilities:
        result["adaptiveSpecialProbabilities"] = {
            str(number): round(float(value), 10) for number, value in special_probabilities.items()
        }
    result["randomBaselineGate"] = gate
    result["adaptiveCoverage"] = {
        "version": ADAPTIVE_COVERAGE_VERSION,
        "candidateMethod": ADAPTIVE_CANDIDATE_METHOD,
        "candidateCountRequested": requested_candidates,
        "candidateCountTarget": target_candidates,
        "candidateCountGenerated": len(candidates),
        "generationAttempts": attempts,
        "selectedCount": len(selected),
        "seed": seed,
        "riskMode": normalized_risk,
        "explorationRate": round(exploration, 6),
        "gate": gate,
        "portfolio": _portfolio_summary(selected, main_probabilities),
    }
    notes = list(result.get("notes") or [])
    generated_text = f"{len(candidates):,}".replace(",", ".")
    requested_text = f"{requested_candidates:,}".replace(",", ".")
    adaptive_note = (
        f"Adaptive Coverage v1 đã sinh {generated_text}/{requested_text} vé ứng viên bằng Gumbel Top-k "
        f"và chọn {len(selected)} bộ theo chất lượng, độ phủ và mức trùng lặp."
    )
    if target_candidates < requested_candidates:
        adaptive_note += " Không gian tổ hợp của cấu hình hiện tại nhỏ hơn số ứng viên yêu cầu nên hệ thống chỉ giữ các ứng viên duy nhất."
    result["notes"] = [adaptive_note, *notes]
    return result
