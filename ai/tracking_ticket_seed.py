"""Versioned per-selection random streams, derived from one frozen root seed.

The schedule is small immutable provenance, not an array of a million seeds.
Each stream participates in selection. Dense portfolios sample the remaining
weighted combination pool; sparse portfolios reject sets already selected.
Replay therefore also needs the frozen probabilities and allocation order.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math

try:
    import numpy as np
except ImportError:
    np = None

VERSION = 'tracking_ticket_seed_v1'
MASK = (1 << 64) - 1
GAMMA = 0x9E3779B97F4A7C15


def schedule(root_seed, game, target, method, count, *, play_mode='normal', bao_level=None):
    return {'version': VERSION, 'rootSeed': str(int(root_seed)), 'type': game,
            'targetDrawId': str(target), 'method': method, 'ticketClass': play_mode,
            'baoLevel': bao_level if play_mode == 'bao' else None, 'selectionCount': int(count),
            'derivation': 'SHA256(root + game + draw + method + class + level + index)',
            'generator': 'splitmix64_weighted_unique_v1' if play_mode == 'normal' else 'verified_bao_pool_v1'}


def _prefix(spec):
    if spec.get('version') != VERSION:
        raise ValueError('Phiên bản seed vé không được hỗ trợ.')
    fields = {key: spec[key] for key in ('version', 'rootSeed', 'type', 'targetDrawId', 'method', 'ticketClass', 'baoLevel')}
    return json.dumps(fields, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode() + b':'


def derive(spec, index):
    if type(index) is not int or not 1 <= index <= spec['selectionCount']:
        raise ValueError('Vị trí vé vượt bộ seed đã khóa.')
    return hashlib.sha256(_prefix(spec) + str(index).encode('ascii')).hexdigest()


def decorate(items, spec, offset=0):
    if not spec:
        return items
    return [{**item, 'ticketSeed': derive(spec, offset + index)} for index, item in enumerate(items, 1)]


def _mix(value):
    value &= MASK
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & MASK
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & MASK
    return value ^ (value >> 31)


class Stream:
    def __init__(self, seed):
        raw = bytes.fromhex(seed)
        self.base = 0
        for start in range(0, 32, 8):
            self.base ^= int.from_bytes(raw[start:start + 8], 'big')

    def bits(self, counter):
        return _mix(self.base + GAMMA * (counter + 1))

    def uniform(self, counter):
        return ((self.bits(counter) >> 11) + 0.5) / (1 << 53)

    def below(self, bound, counter=0):
        if not 1 <= bound <= 1 << 64:
            raise ValueError('Giới hạn chọn số không hợp lệ.')
        limit = (1 << 64) - (1 << 64) % bound
        for retry in range(1024):
            value = self.bits(counter * 1024 + retry)
            if value < limit:
                return value % bound
        raise RuntimeError('Không tạo được số ngẫu nhiên trong giới hạn.')


class RemainingPool:
    """Integer Fenwick weights avoid rounding drift at a saturated portfolio."""
    def __init__(self, weights):
        self.weights = weights
        self.tree = [0, *weights]
        for index in range(1, len(self.tree)):
            parent = index + (index & -index)
            if parent < len(self.tree):
                self.tree[parent] += self.tree[index]
        self.total = sum(weights)

    def pop(self, rank):
        index = 0
        bit = 1 << (len(self.weights).bit_length() - 1)
        while bit:
            following = index + bit
            if following < len(self.tree) and self.tree[following] <= rank:
                rank -= self.tree[following]
                index = following
            bit >>= 1
        weight = self.weights[index]
        if not weight:
            raise RuntimeError('Vị trí danh mục đã được chọn trước đó.')
        self.weights[index] = 0
        self.total -= weight
        current = index + 1
        while current < len(self.tree):
            self.tree[current] -= weight
            current += current & -current
        return index


def _sparse(probabilities, size, count, spec):
    universe = len(probabilities)
    weights = [max(probabilities[n], 1e-12) for n in range(1, universe + 1)]
    seen, output = set(), []
    prefix = _prefix(spec)
    for start in range(0, count, 1024):
        length = min(1024, count - start)
        streams = [Stream(hashlib.sha256(prefix + str(start + row + 1).encode('ascii')).hexdigest()) for row in range(length)]
        if np is not None:
            with np.errstate(over='ignore'):
                raw = np.asarray([stream.base for stream in streams], dtype=np.uint64)[:, None] + np.arange(1, universe + 1, dtype=np.uint64)[None, :] * np.uint64(GAMMA)
                raw = (raw ^ (raw >> 30)) * np.uint64(0xBF58476D1CE4E5B9)
                raw = (raw ^ (raw >> 27)) * np.uint64(0x94D049BB133111EB)
                raw ^= raw >> 31
            unit = ((raw >> 11).astype(np.float64) + .5) / (1 << 53)
            keys = -np.log(unit) / np.asarray(weights)
            candidates = np.argsort(keys, axis=1, kind='stable')[:, :size]
        else:
            candidates = None
        for row, stream in enumerate(streams):
            if candidates is not None:
                main = tuple(sorted(int(n) + 1 for n in candidates[row]))
            else:
                main = tuple(sorted(sorted(range(1, universe + 1), key=lambda n: -math.log(stream.uniform(n - 1)) / weights[n - 1])[:size]))
            for retry in range(1, 1001):
                if main not in seen:
                    break
                main = tuple(sorted(sorted(range(1, universe + 1), key=lambda n: -math.log(stream.uniform(retry * universe + n - 1)) / weights[n - 1])[:size]))
            else:
                raise ValueError('Phân bố quá tập trung để tạo đủ vé có seed riêng; giảm số vé.')
            seen.add(main)
            output.append(main)
    return output


def mains(probabilities, size, count, spec):
    universe = len(probabilities)
    space = math.comb(universe, size)
    if not 1 <= count <= space or spec['selectionCount'] != count:
        raise ValueError('Số vé không khớp lịch seed đã xác nhận.')
    if space <= 2_000_000 and count > space // 4:
        candidates = list(itertools.combinations(range(1, universe + 1), size))
        peak = max(probabilities.values())
        weights = [max(1, int(math.prod(max(probabilities[n], 1e-12) / peak for n in candidate) * (1 << 40)))
                   for candidate in candidates]
        pool = RemainingPool(weights)
        prefix = _prefix(spec)
        result = []
        for index in range(1, count + 1):
            stream = Stream(hashlib.sha256(prefix + str(index).encode('ascii')).hexdigest())
            result.append(candidates[pool.pop(stream.below(pool.total))])
        return result
    return _sparse(probabilities, size, count, spec)


def normal(payload, game, spec, count):
    probabilities = {int(key): float(value) for key, value in payload['probabilities'].items()}
    size = 5 if game == 'LOTO_5_35' else 6
    tickets = []
    prefix = _prefix(spec)
    for index, main in enumerate(mains(probabilities, size, count, spec), 1):
        stream = Stream(hashlib.sha256(prefix + str(index).encode('ascii')).hexdigest())
        special = 1 + stream.below(12, 1_000_000) if game == 'LOTO_5_35' else None
        if game == 'LOTO_6_55':
            rest = [number for number in range(1, 56) if number not in main]
            special = rest[stream.below(len(rest), 1_000_000)]
        tickets.append({'main': list(main), 'special': special})
    result = {**payload, 'tickets': tickets, 'bundleCount': count, 'ticketClass': 'normal',
              'randomSeed': int(spec['rootSeed']), 'ticketSeedSchedule': spec,
              'allocationPolicy': VERSION, 'engine': str(payload.get('engine', 'web')) + '+' + VERSION}
    result.pop('adaptiveCoverage', None)
    result.pop('trackingPortfolio', None)
    return result
