from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import Any


def count_mod_residues(numbers: list[int] | tuple[int, ...], modulus: int) -> dict[int, int]:
    counts = {residue: 0 for residue in range(modulus)}
    for number in numbers:
        counts[int(number) % modulus] += 1
    return counts


def describe_main_numbers(numbers: list[int] | tuple[int, ...], use_mod11: bool = True) -> dict[str, Any]:
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
    if use_mod11:
        payload["mod11_counts"] = count_mod_residues(numbers, 11)
    return payload


def describe_special_number(number: int) -> dict[str, Any]:
    special = int(number)
    return {
        "special_mod2": special % 2,
        "special_mod3": special % 3,
        "special_mod5": special % 5,
        "special_mod10": special % 10,
    }


def build_recent_modulo_context(draws: list[Any], window: int = 10, use_mod11: bool = True) -> dict[str, Any]:
    scoped_draws = list(draws[-window:]) if window else list(draws)
    if not scoped_draws:
        return {
            "draw_count": 0,
            "main": {
                "parity_usage": {0: 0.5, 1: 0.5},
                "mod3_usage": {0: 1 / 3, 1: 1 / 3, 2: 1 / 3},
                "mod5_usage": {index: 0.2 for index in range(5)},
                "mod10_usage": {index: 0.1 for index in range(10)},
                "mod11_usage": {index: 1 / 11 for index in range(11)} if use_mod11 else {},
                "mod5_blank_frequency": {index: 0.0 for index in range(5)},
                "average_even_count": 3.0,
                "average_sum": 175.0,
                "average_range": 34.0,
                "recent_pattern_labels": [],
            },
            "special": {
                "mod2_usage": {0: 0.5, 1: 0.5},
                "mod3_usage": {0: 1 / 3, 1: 1 / 3, 2: 1 / 3},
                "mod5_usage": {index: 0.2 for index in range(5)},
                "mod10_usage": {index: 0.1 for index in range(10)},
                "repeat_rate": 0.0,
                "recent_values": [],
            },
        }

    total_slots = max(1, len(scoped_draws) * 6)
    parity_counter = Counter()
    mod3_counter = Counter()
    mod5_counter = Counter()
    mod10_counter = Counter()
    mod11_counter = Counter()
    blank_counter = Counter()
    even_counts: list[int] = []
    sums: list[int] = []
    ranges: list[int] = []
    pattern_labels: list[str] = []

    special_mod2 = Counter()
    special_mod3 = Counter()
    special_mod5 = Counter()
    special_mod10 = Counter()
    special_values: list[int] = []
    special_repeats = 0

    for index, draw in enumerate(scoped_draws):
        description = describe_main_numbers(draw.main_numbers, use_mod11=use_mod11)
        parity_counter.update({0: description["mod2_counts"]["even"], 1: description["mod2_counts"]["odd"]})
        mod3_counter.update(description["mod3_counts"])
        mod5_counter.update(description["mod5_counts"])
        mod10_counter.update(description["mod10_counts"])
        if use_mod11:
            mod11_counter.update(description["mod11_counts"])
        blank_counter.update(description["mod5_blank_zones"])
        even_counts.append(description["mod2_counts"]["even"])
        sums.append(sum(draw.main_numbers))
        ranges.append(max(draw.main_numbers) - min(draw.main_numbers))
        pattern_labels.append(description["modulo_pattern_class"])

        special_values.append(int(draw.special))
        special_mod2[draw.special % 2] += 1
        special_mod3[draw.special % 3] += 1
        special_mod5[draw.special % 5] += 1
        special_mod10[draw.special % 10] += 1
        if index > 0 and draw.special == scoped_draws[index - 1].special:
            special_repeats += 1

    return {
        "draw_count": len(scoped_draws),
        "main": {
            "parity_usage": {key: parity_counter[key] / total_slots for key in range(2)},
            "mod3_usage": {key: mod3_counter[key] / total_slots for key in range(3)},
            "mod5_usage": {key: mod5_counter[key] / total_slots for key in range(5)},
            "mod10_usage": {key: mod10_counter[key] / total_slots for key in range(10)},
            "mod11_usage": {key: mod11_counter[key] / total_slots for key in range(11)} if use_mod11 else {},
            "mod5_blank_frequency": {key: blank_counter[key] / len(scoped_draws) for key in range(5)},
            "average_even_count": mean(even_counts),
            "average_sum": mean(sums),
            "average_range": mean(ranges),
            "recent_pattern_labels": pattern_labels[-5:],
        },
        "special": {
            "mod2_usage": {key: special_mod2[key] / len(scoped_draws) for key in range(2)},
            "mod3_usage": {key: special_mod3[key] / len(scoped_draws) for key in range(3)},
            "mod5_usage": {key: special_mod5[key] / len(scoped_draws) for key in range(5)},
            "mod10_usage": {key: special_mod10[key] / len(scoped_draws) for key in range(10)},
            "repeat_rate": special_repeats / max(1, len(scoped_draws) - 1),
            "recent_values": special_values[-8:],
        },
    }


def score_main_number(number: int, modulo_context: dict[str, Any]) -> float:
    main_context = dict(modulo_context.get("main") or {})
    parity_usage = dict(main_context.get("parity_usage") or {})
    mod3_usage = dict(main_context.get("mod3_usage") or {})
    mod5_usage = dict(main_context.get("mod5_usage") or {})
    mod10_usage = dict(main_context.get("mod10_usage") or {})
    mod11_usage = dict(main_context.get("mod11_usage") or {})
    mod5_blank_frequency = dict(main_context.get("mod5_blank_frequency") or {})

    parity_component = 1.0 - min(1.0, parity_usage.get(number % 2, 0.5))
    mod3_component = 1.0 - min(1.0, mod3_usage.get(number % 3, 1 / 3))
    mod5_component = 0.7 * (1.0 - min(1.0, mod5_usage.get(number % 5, 0.2))) + 0.3 * min(1.0, mod5_blank_frequency.get(number % 5, 0.0))
    tail_component = 1.0 - min(1.0, mod10_usage.get(number % 10, 0.1))
    mod11_component = 1.0 - min(1.0, mod11_usage.get(number % 11, 1 / 11)) if mod11_usage else 0.5
    score = (
        0.20 * parity_component
        + 0.24 * mod3_component
        + 0.24 * mod5_component
        + 0.20 * tail_component
        + 0.12 * mod11_component
    )
    return max(0.0, min(1.0, score))


def score_special_number(number: int, modulo_context: dict[str, Any]) -> float:
    special_context = dict(modulo_context.get("special") or {})
    mod2_usage = dict(special_context.get("mod2_usage") or {})
    mod3_usage = dict(special_context.get("mod3_usage") or {})
    mod5_usage = dict(special_context.get("mod5_usage") or {})
    mod10_usage = dict(special_context.get("mod10_usage") or {})
    recent_values = list(special_context.get("recent_values") or [])
    repeat_rate = float(special_context.get("repeat_rate", 0.0))

    parity_component = 1.0 - min(1.0, mod2_usage.get(number % 2, 0.5))
    mod3_component = 1.0 - min(1.0, mod3_usage.get(number % 3, 1 / 3))
    mod5_component = 1.0 - min(1.0, mod5_usage.get(number % 5, 0.2))
    tail_component = 1.0 - min(1.0, mod10_usage.get(number % 10, 0.1))
    recent_repeat_component = 0.65 if number in set(recent_values[-3:]) and repeat_rate < 0.18 else 1.0
    score = (0.22 * parity_component + 0.24 * mod3_component + 0.24 * mod5_component + 0.20 * tail_component) * recent_repeat_component
    return max(0.0, min(1.0, score))


def score_ticket_structure(ticket_numbers: list[int] | tuple[int, ...], modulo_context: dict[str, Any]) -> dict[str, float]:
    description = describe_main_numbers(ticket_numbers, use_mod11=bool((modulo_context.get("main") or {}).get("mod11_usage")))
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


def score_special_support(special_number: int, ticket_numbers: list[int] | tuple[int, ...], modulo_context: dict[str, Any]) -> float:
    if int(special_number) in set(int(number) for number in ticket_numbers):
        return 0.0
    special_context = dict(modulo_context.get("special") or {})
    base_score = score_special_number(int(special_number), modulo_context)
    recent_values = list(special_context.get("recent_values") or [])
    repeat_rate = float(special_context.get("repeat_rate", 0.0))
    distance_score = min(1.0, sum(min(abs(int(special_number) - int(number)), 20) for number in ticket_numbers) / (len(ticket_numbers) * 10.0))
    repeat_reset_score = 0.55
    if recent_values:
        if int(special_number) == int(recent_values[-1]):
            repeat_reset_score = 0.30 if repeat_rate < 0.18 else 0.62
        elif int(special_number) in set(recent_values[-4:]):
            repeat_reset_score = 0.52
        else:
            repeat_reset_score = 0.76
    return max(0.0, min(1.0, 0.55 * base_score + 0.20 * distance_score + 0.25 * repeat_reset_score))


def summarize_modulo_notes(
    modulo_context: dict[str, Any],
    selected_ticket: list[int] | None = None,
    selected_special: int | None = None,
) -> list[str]:
    main_context = dict(modulo_context.get("main") or {})
    special_context = dict(modulo_context.get("special") or {})
    blank_zones = [residue for residue, frequency in dict(main_context.get("mod5_blank_frequency") or {}).items() if frequency >= 0.35]
    notes = []
    if blank_zones:
        notes.append(f"Recent mod5 blank zones were residues {blank_zones}.")
    patterns = list(main_context.get("recent_pattern_labels") or [])
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
    if selected_special is not None:
        recent_values = list(special_context.get("recent_values") or [])
        notes.append(
            f"Selected special {selected_special} aligns with special modulo score "
            f"{score_special_number(selected_special, modulo_context):.2f} "
            f"against recent specials {recent_values[-4:]}."
        )
    return notes
