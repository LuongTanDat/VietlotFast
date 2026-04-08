from __future__ import annotations

from collections import Counter


MODULO_BASES = (2, 3, 5, 10)


def _collect_residue_counts(draws, base, selector, slot="", weekday=None):
    counts = Counter()
    total = 0
    for draw in draws or []:
        if slot and str(draw.get("slot", "")) != slot:
            continue
        if weekday is not None and draw.get("weekday") != weekday:
            continue
        for value in selector(draw):
            counts[int(value) % base] += 1
            total += 1
    return counts, total


def build_modulo_context(draws, target, selector):
    slot = str(target.get("target_slot", "")).strip()
    weekday = target.get("target_weekday")
    context = {}
    for base in MODULO_BASES:
        recent_counts, recent_total = _collect_residue_counts(draws[-24:], base, selector)
        slot_counts, slot_total = _collect_residue_counts(draws[-48:], base, selector, slot=slot)
        weekday_counts, weekday_total = _collect_residue_counts(draws, base, selector, weekday=weekday)
        context[base] = {
            "recent": recent_counts,
            "recentTotal": recent_total,
            "slot": slot_counts,
            "slotTotal": slot_total,
            "weekday": weekday_counts,
            "weekdayTotal": weekday_total,
        }
    return context


def score_candidate(value, context) -> float:
    candidate = int(value or 0)
    scores = []
    for base, payload in (context or {}).items():
        residue = candidate % int(base)
        recent_score = float(payload["recent"].get(residue, 0)) / max(1, int(payload.get("recentTotal") or 0))
        slot_score = float(payload["slot"].get(residue, 0)) / max(1, int(payload.get("slotTotal") or 0))
        weekday_score = float(payload["weekday"].get(residue, 0)) / max(1, int(payload.get("weekdayTotal") or 0))
        scores.append((recent_score * 0.45) + (slot_score * 0.35) + (weekday_score * 0.20))
    if not scores:
        return 0.0
    return sum(scores) / float(len(scores))


def evaluate_ticket_modulo(ticket_numbers):
    numbers = [int(value) for value in list(ticket_numbers or [])]
    if not numbers:
        return {
            "modulo3Balance": 0.0,
            "modulo5Pattern": 0.0,
            "tailPattern": 0.0,
        }
    residues3 = Counter(number % 3 for number in numbers)
    residues5 = Counter(number % 5 for number in numbers)
    tails = Counter(number % 10 for number in numbers)
    modulo3_balance = 1.0 - (max(residues3.values()) - min(residues3.values(), default=0)) / max(1.0, len(numbers))
    modulo5_pattern = len(residues5) / min(5.0, float(len(numbers)))
    tail_pattern = len(tails) / float(len(numbers))
    return {
        "modulo3Balance": max(0.0, min(1.0, modulo3_balance)),
        "modulo5Pattern": max(0.0, min(1.0, modulo5_pattern)),
        "tailPattern": max(0.0, min(1.0, tail_pattern)),
    }
