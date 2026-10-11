"""Bounded, seeded unique portfolios for tracking; public prediction limits stay intact."""
from __future__ import annotations

import hashlib
import heapq
import itertools
import math
import random

MAX_TICKETS = 10000
TICKET_PAGE_SIZE = 20
VERSION = "tracking_unique_portfolio_v1"


def effective_count(requested, universe, pick_size):
    if type(requested) is not int or not 1 <= requested <= MAX_TICKETS:
        raise ValueError("Số vé phải là số nguyên từ 1 đến 10.000.")
    return min(requested, math.comb(universe, pick_size))


def _unrank(rank, universe, pick_size):
    result, start = [], 1
    for remaining in range(pick_size - 1, -1, -1):
        for number in range(start, universe - remaining + 1):
            block = math.comb(universe - number, remaining)
            if rank < block:
                result.append(number)
                start = number + 1
                break
            rank -= block
    return tuple(result)


def unique_mains(probabilities, pick_size, count, seed, prefix=()):
    """No repeated main sets, including saturated small combination spaces.

    Uniform portfolios sample combination ranks without replacement. Weighted
    portfolios use exponential keys; small dense spaces are enumerated so
    rejection sampling cannot stall when all 80/3160 combinations are requested.
    """
    universe = len(probabilities)
    count = effective_count(count, universe, pick_size)
    rng = random.Random(seed)
    mains = [tuple(sorted(main)) for main in prefix]
    if len(mains) > count or len(set(mains)) != len(mains):
        raise ValueError("Danh mục gốc có vé trùng hoặc vượt ngân sách.")
    seen = set(mains)
    space = math.comb(universe, pick_size)
    weights = [max(float(probabilities[n]), 1e-12) for n in range(1, universe + 1)]
    uniform = max(weights) - min(weights) < 1e-14
    if count == len(mains):
        return mains
    if space <= 50000 and count > space // 4:
        candidates = [main for main in itertools.combinations(range(1, universe + 1), pick_size) if main not in seen]
        if uniform:
            rng.shuffle(candidates)
        else:
            log_weights = [math.log(w) for w in weights]
            candidates.sort(key=lambda main: -(sum(log_weights[n - 1] for n in main) - math.log(-math.log(max(rng.random(), 1e-12)))))
        return mains + candidates[:count - len(mains)]
    if uniform:
        # Sparse spaces: sample extra unique ranks to compensate for the prefix.
        while len(mains) < count:
            for rank in rng.sample(range(space), min(space, count - len(mains) + len(prefix) + 8)):
                main = _unrank(rank, universe, pick_size)
                if main not in seen:
                    mains.append(main)
                    seen.add(main)
                    if len(mains) == count:
                        break
        return mains
    try:
        import numpy as np
    except ImportError:
        np = None
    generator = np.random.default_rng(seed) if np is not None else None
    attempts = 0
    while len(mains) < count:
        batch = min(1024, count - len(mains) + 16)
        if generator is not None:
            keys = -np.log(np.maximum(generator.random((batch, universe)), 1e-12)) / np.asarray(weights)
            candidates = (tuple(sorted((row + 1).tolist())) for row in np.argpartition(keys, pick_size - 1, axis=1)[:, :pick_size])
        else:
            candidates = (tuple(sorted(heapq.nsmallest(pick_size, range(1, universe + 1), key=lambda n: -math.log(max(rng.random(), 1e-12)) / weights[n - 1]))) for _ in range(batch))
        for main in candidates:
            attempts += 1
            if main not in seen:
                seen.add(main)
                mains.append(main)
                if len(mains) == count:
                    break
        if attempts > 100 * count:
            raise ValueError("Phân bố quá tập trung để tạo đủ vé khác nhau; giảm số vé.")
    return mains


def expand_web(payload, count, universe, pick_size, snapshot):
    if len(payload.get("tickets") or []) == count:
        return payload
    from ai import prediction_ledger as ledger
    probabilities = ledger.normalize_probability_payload(payload.get("probabilities"))
    if set(probabilities) != set(range(1, universe + 1)):
        raise ValueError("Luồng web thiếu xác suất để mở rộng danh mục.")
    original = payload.get("tickets") or []
    provenance = {"version": VERSION, "baseEngine": payload.get("engine"),
                  "baseTicketCount": len(original), "ticketCount": count,
                  "sourcePayloadHash": ledger.payload_checksum(payload),
                  "dataHash": snapshot["dataHash"], "target": snapshot["target"]}
    seed = int(hashlib.sha256(ledger.canonical_json(provenance).encode()).hexdigest()[:12], 16) % 2147483647
    mains = unique_mains(probabilities, pick_size, count, seed, [ticket["main"] for ticket in original])
    rng = random.Random(seed)
    tickets = list(original)
    for main in mains[len(original):]:
        special = rng.randrange(1, 13) if payload["type"] == "LOTO_5_35" else rng.choice([n for n in range(1, 56) if n not in main]) if payload["type"] == "LOTO_6_55" else None
        tickets.append({"main": list(main), "special": special})
    result = {**payload, "tickets": tickets, "bundleCount": count,
              "engine": f"{payload.get('engine', 'web')}+{VERSION}",
              "randomSeed": seed, "trackingPortfolio": {**provenance, "seed": seed,
              "specialPolicy": "uniform_seeded_for_added_tickets", "uniqueBy": "main_numbers"}}
    # Metadata from the small portfolio must not describe the expanded one.
    result.pop("adaptiveCoverage", None)
    return result
