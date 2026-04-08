from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import Any


def count_mod_residues(numbers: list[int] | tuple[int, ...], modulus: int) -> dict[int, int]:
    counts = {residue: 0 for residue in range(modulus)}
    for number in numbers:
        counts[number % modulus] += 1
    return counts


def describe_numbers(numbers: list[int] | tuple[int, ...], use_mod9: bool = True) -> dict[str, Any]:
    mod2_counts = count_mod_residues(numbers, 2)
    mod3_counts = count_mod_residues(numbers, 3)
    mod5_counts = count_mod_residues(numbers, 5)
    mod10_counts = count_mod_residues(numbers, 10)
    payload = {
        "mod2_counts": {"even": mod2_counts[0], "odd": mod2_counts[1]},
        "mod3_counts": mod3_counts,
        "mod5_counts": mod5_counts,
        "mod10_counts": mod10_counts,
        "mod5_blank_zones": [residue for residue, count in mod5_counts.items() if count == 0],
        "modulo_pattern_class": (
            f"m2_{mod2_counts[0]}-{mod2_counts[1]}|"
            f"m3_{'-'.join(str(mod3_counts[index]) for index in range(3))}|"
            f"m5_blank_{len([count for count in mod5_counts.values() if count == 0])}"
        ),
    }
    if use_mod9:
        payload["mod9_counts"] = count_mod_residues(numbers, 9)
    return payload


def build_recent_modulo_context(draws: list[Any], window: int = 10, use_mod9: bool = True) -> dict[str, Any]:
    scoped_draws = list(draws[-window:]) if window else list(draws)
    if not scoped_draws:
        return {
            "draw_count": 0,
            "parity_usage": {0: 0.5, 1: 0.5},
            "mod3_usage": {0: 1 / 3, 1: 1 / 3, 2: 1 / 3},
            "mod5_usage": {index: 0.2 for index in range(5)},
            "mod10_usage": {index: 0.1 for index in range(10)},
            "mod5_blank_frequency": {index: 0.0 for index in range(5)},
            "average_even_count": 3.0,
            "average_sum": 135.0,
            "average_range": 27.0,
        }

    total_slots = max(1, len(scoped_draws) * 6)
    parity_counter = Counter()
    mod3_counter = Counter()
    mod5_counter = Counter()
    mod10_counter = Counter()
    mod9_counter = Counter()
    blank_counter = Counter()
    even_counts: list[int] = []
    sums: list[int] = []
    ranges: list[int] = []
    pattern_labels: list[str] = []

    for draw in scoped_draws:
        description = describe_numbers(draw.main_numbers, use_mod9=use_mod9)
        parity_counter.update({0: description["mod2_counts"]["even"], 1: description["mod2_counts"]["odd"]})
        mod3_counter.update(description["mod3_counts"])
        mod5_counter.update(description["mod5_counts"])
        mod10_counter.update(description["mod10_counts"])
        if use_mod9:
            mod9_counter.update(description["mod9_counts"])
        blank_counter.update(description["mod5_blank_zones"])
        even_counts.append(description["mod2_counts"]["even"])
        sums.append(sum(draw.main_numbers))
        ranges.append(max(draw.main_numbers) - min(draw.main_numbers))
        pattern_labels.append(description["modulo_pattern_class"])

    return {
        "draw_count": len(scoped_draws),
        "parity_usage": {key: parity_counter[key] / total_slots for key in range(2)},
        "mod3_usage": {key: mod3_counter[key] / total_slots for key in range(3)},
        "mod5_usage": {key: mod5_counter[key] / total_slots for key in range(5)},
        "mod10_usage": {key: mod10_counter[key] / total_slots for key in range(10)},
        "mod9_usage": {key: mod9_counter[key] / total_slots for key in range(9)} if use_mod9 else {},
        "mod5_blank_frequency": {key: blank_counter[key] / len(scoped_draws) for key in range(5)},
        "average_even_count": mean(even_counts),
        "average_sum": mean(sums),
        "average_range": mean(ranges),
        "recent_pattern_labels": pattern_labels[-5:],
    }


def score_number(number: int, modulo_context: dict[str, Any]) -> float:
    parity_usage = dict(modulo_context.get("parity_usage") or {})
    mod3_usage = dict(modulo_context.get("mod3_usage") or {})
    mod5_usage = dict(modulo_context.get("mod5_usage") or {})
    mod10_usage = dict(modulo_context.get("mod10_usage") or {})
    mod9_usage = dict(modulo_context.get("mod9_usage") or {})
    mod5_blank_frequency = dict(modulo_context.get("mod5_blank_frequency") or {})

    parity_component = 1.0 - min(1.0, parity_usage.get(number % 2, 0.5))
    mod3_component = 1.0 - min(1.0, mod3_usage.get(number % 3, 1 / 3))
    mod5_component = (
        0.7 * (1.0 - min(1.0, mod5_usage.get(number % 5, 0.2)))
        + 0.3 * min(1.0, mod5_blank_frequency.get(number % 5, 0.0))
    )
    tail_component = 1.0 - min(1.0, mod10_usage.get(number % 10, 0.1))
    mod9_component = 1.0 - min(1.0, mod9_usage.get(number % 9, 1 / 9)) if mod9_usage else 0.5
    score = (
        0.22 * parity_component
        + 0.24 * mod3_component
        + 0.26 * mod5_component
        + 0.20 * tail_component
        + 0.08 * mod9_component
    )
    return max(0.0, min(1.0, score))


def score_ticket_structure(ticket_numbers: list[int] | tuple[int, ...], modulo_context: dict[str, Any]) -> dict[str, float]:
    description = describe_numbers(ticket_numbers, use_mod9=bool(modulo_context.get("mod9_usage")))
    even_count = description["mod2_counts"]["even"]
    parity_balance = max(0.0, 1.0 - min(abs(even_count - 3), abs(even_count - 4)) / 3.0)

    mod3_counts = list(description["mod3_counts"].values())
    modulo3_balance = max(0.0, 1.0 - sum(abs(count - 2) for count in mod3_counts) / 8.0)

    mod5_distinct = sum(1 for count in description["mod5_counts"].values() if count > 0)
    modulo5_pattern = max(0.0, 1.0 - abs(mod5_distinct - 4) / 4.0)

    tail_counts = list(description["mod10_counts"].values())
    tail_distinct = sum(1 for count in tail_counts if count > 0)
    max_tail_repeat = max(tail_counts)
    tail_structure = max(0.0, min(1.0, 0.65 * (tail_distinct / 6.0) + 0.35 * (1.0 - (max_tail_repeat - 1) / 5.0)))

    return {
        "parity_balance": parity_balance,
        "modulo3_balance": modulo3_balance,
        "modulo5_pattern": modulo5_pattern,
        "tail_structure": tail_structure,
    }


def summarize_modulo_notes(modulo_context: dict[str, Any], selected_ticket: list[int] | None = None) -> list[str]:
    blank_zones = [
        residue
        for residue, frequency in dict(modulo_context.get("mod5_blank_frequency") or {}).items()
        if frequency >= 0.35
    ]
    notes = []
    if blank_zones:
        notes.append(f"Recent mod5 blank zones were residues {blank_zones}.")
    patterns = list(modulo_context.get("recent_pattern_labels") or [])
    if patterns:
        notes.append(f"Recent modulo patterns: {', '.join(patterns[-3:])}.")
    if selected_ticket:
        ticket_structure = score_ticket_structure(selected_ticket, modulo_context)
        notes.append(
            "Selected ticket modulo balance "
            f"p={ticket_structure['parity_balance']:.2f}, "
            f"m3={ticket_structure['modulo3_balance']:.2f}, "
            f"m5={ticket_structure['modulo5_pattern']:.2f}."
        )
    return notes
