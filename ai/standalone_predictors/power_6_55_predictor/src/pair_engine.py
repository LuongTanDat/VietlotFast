from __future__ import annotations

from collections import Counter
from itertools import combinations
from typing import Any


def _normalize_pair(number_a: int, number_b: int) -> tuple[int, int]:
    return tuple(sorted((int(number_a), int(number_b))))


def build_pair_context(draws: list[Any], history_limit: int = 220) -> dict[str, Any]:
    scoped_draws = list(draws[-history_limit:]) if history_limit else list(draws)
    total_draws = len(scoped_draws)
    if total_draws == 0:
        return {"total_draws": 0, "number_counts": {}, "pair_stats": {}, "top_pairs": []}

    number_counts: Counter[int] = Counter()
    pair_counts: Counter[tuple[int, int]] = Counter()
    for draw in scoped_draws:
        numbers = list(draw.main_numbers)
        number_counts.update(numbers)
        pair_counts.update(_normalize_pair(a, b) for a, b in combinations(numbers, 2))

    pair_stats: dict[tuple[int, int], dict[str, float]] = {}
    for pair, count in pair_counts.items():
        a, b = pair
        pair_probability = count / total_draws
        probability_a = number_counts[a] / total_draws
        probability_b = number_counts[b] / total_draws
        denominator = probability_a * probability_b
        lift = (pair_probability / denominator) if denominator else 1.0
        confidence = count / max(1, min(number_counts[a], number_counts[b]))
        pair_stats[pair] = {
            "pair_count": float(count),
            "confidence": float(confidence),
            "lift": float(lift),
        }

    top_pairs = sorted(pair_stats.items(), key=lambda item: (item[1]["lift"], item[1]["pair_count"]), reverse=True)[:12]
    return {
        "total_draws": total_draws,
        "number_counts": dict(number_counts),
        "pair_stats": pair_stats,
        "top_pairs": [(pair[0], pair[1], stats["lift"]) for pair, stats in top_pairs],
    }


def score_number(number: int, anchor_numbers: list[int], pair_context: dict[str, Any]) -> float:
    anchors = [int(anchor) for anchor in anchor_numbers if int(anchor) != int(number)]
    if not anchors:
        return 0.5
    pair_stats = dict(pair_context.get("pair_stats") or {})
    values = []
    for anchor in anchors:
        stats = pair_stats.get(_normalize_pair(number, anchor))
        if not stats:
            values.append(0.48)
            continue
        lift = float(stats.get("lift", 1.0))
        confidence = float(stats.get("confidence", 0.0))
        values.append(max(0.0, min(1.0, 0.38 + 0.16 * confidence + 0.12 * min(2.3, lift) / 2.3)))
    return sum(values) / len(values)


def anti_pair_adjustment(number: int, anchor_numbers: list[int], pair_context: dict[str, Any]) -> float:
    anchors = [int(anchor) for anchor in anchor_numbers if int(anchor) != int(number)]
    if not anchors:
        return 0.5
    pair_stats = dict(pair_context.get("pair_stats") or {})
    values = []
    for anchor in anchors:
        stats = pair_stats.get(_normalize_pair(number, anchor))
        if not stats:
            values.append(0.54)
            continue
        lift = float(stats.get("lift", 1.0))
        if lift >= 1.0:
            values.append(min(1.0, 0.55 + min(1.4, lift - 1.0) * 0.22))
        else:
            values.append(max(0.0, 0.55 - (1.0 - lift) * 0.60))
    return sum(values) / len(values)


def score_ticket(ticket_numbers: list[int] | tuple[int, ...], pair_context: dict[str, Any]) -> dict[str, float]:
    pair_stats = dict(pair_context.get("pair_stats") or {})
    compatibility_values = []
    anti_pair_values = []
    for number_a, number_b in combinations(ticket_numbers, 2):
        stats = pair_stats.get(_normalize_pair(number_a, number_b))
        if not stats:
            compatibility_values.append(0.48)
            anti_pair_values.append(0.22)
            continue
        lift = float(stats.get("lift", 1.0))
        confidence = float(stats.get("confidence", 0.0))
        compatibility_values.append(max(0.0, min(1.0, 0.38 + 0.14 * confidence + 0.14 * min(2.3, lift) / 2.3)))
        anti_pair_values.append(max(0.0, min(1.0, 1.0 - min(lift, 1.0))))
    pair_compatibility = sum(compatibility_values) / len(compatibility_values) if compatibility_values else 0.5
    anti_pair_penalty = sum(anti_pair_values) / len(anti_pair_values) if anti_pair_values else 0.0
    return {
        "pair_compatibility": pair_compatibility,
        "anti_pair_penalty": anti_pair_penalty,
    }


def summarize_pair_notes(pair_context: dict[str, Any], selected_ticket: list[int] | None = None) -> list[str]:
    notes = []
    top_pairs = list(pair_context.get("top_pairs") or [])
    if top_pairs:
        preview = ", ".join(f"{a}-{b} (lift {lift:.2f})" for a, b, lift in top_pairs[:4])
        notes.append(f"Top historical pairs: {preview}.")
    if selected_ticket:
        ticket_scores = score_ticket(selected_ticket, pair_context)
        notes.append(
            "Selected ticket pair balance "
            f"pair={ticket_scores['pair_compatibility']:.2f}, "
            f"anti={ticket_scores['anti_pair_penalty']:.2f}."
        )
    return notes
