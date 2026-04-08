from __future__ import annotations

from collections import Counter
from itertools import combinations


def build_pair_context(draws, lookback=96):
    recent_draws = list(draws or [])[-max(12, int(lookback or 96)) :]
    single_counts = Counter()
    pair_counts = Counter()
    draw_count = 0
    for draw in recent_draws:
        numbers = sorted(set(int(value) for value in list(draw.get("main") or [])))
        if not numbers:
            continue
        draw_count += 1
        for number in numbers:
            single_counts[number] += 1
        for left, right in combinations(numbers, 2):
            pair_counts[(left, right)] += 1
    return {
        "drawCount": draw_count,
        "singleCounts": dict(single_counts),
        "pairCounts": dict(pair_counts),
    }


def _pair_key(left, right):
    a = int(left)
    b = int(right)
    return (a, b) if a <= b else (b, a)


def pair_support(left, right, context) -> float:
    key = _pair_key(left, right)
    single_counts = context.get("singleCounts") or {}
    pair_counts = context.get("pairCounts") or {}
    left_count = float(single_counts.get(key[0], 0))
    right_count = float(single_counts.get(key[1], 0))
    pair_count = float(pair_counts.get(key, 0))
    denominator = max(1.0, min(left_count, right_count))
    return pair_count / denominator


def anti_pair_penalty(left, right, context) -> float:
    key = _pair_key(left, right)
    single_counts = context.get("singleCounts") or {}
    pair_counts = context.get("pairCounts") or {}
    draw_count = max(1.0, float(context.get("drawCount") or 0))
    left_rate = float(single_counts.get(key[0], 0)) / draw_count
    right_rate = float(single_counts.get(key[1], 0)) / draw_count
    expected = left_rate * right_rate
    actual = float(pair_counts.get(key, 0)) / draw_count
    if expected <= 0:
        return 0.0
    return max(0.0, min(1.0, (expected - actual) / expected))


def score_candidate_pairing(candidate, anchors, context) -> float:
    anchor_list = [int(value) for value in list(anchors or []) if int(value) != int(candidate)]
    if not anchor_list:
        return 0.0
    scores = [pair_support(candidate, anchor, context) for anchor in anchor_list]
    return sum(scores) / float(len(scores))


def score_candidate_anti_pair(candidate, anchors, context) -> float:
    anchor_list = [int(value) for value in list(anchors or []) if int(value) != int(candidate)]
    if not anchor_list:
        return 0.0
    penalties = [anti_pair_penalty(candidate, anchor, context) for anchor in anchor_list]
    return sum(penalties) / float(len(penalties))


def evaluate_ticket_pair_quality(numbers, context):
    values = sorted(set(int(value) for value in list(numbers or [])))
    if len(values) < 2:
        return {
            "pairCompatibility": 0.0,
            "antiPairPenalty": 0.0,
        }
    pair_scores = []
    anti_scores = []
    for left, right in combinations(values, 2):
        pair_scores.append(pair_support(left, right, context))
        anti_scores.append(anti_pair_penalty(left, right, context))
    avg_pair = sum(pair_scores) / max(1, len(pair_scores))
    avg_anti = sum(anti_scores) / max(1, len(anti_scores))
    return {
        "pairCompatibility": max(0.0, min(1.0, avg_pair)),
        "antiPairPenalty": max(0.0, min(1.0, avg_anti)),
    }
