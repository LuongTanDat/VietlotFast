"""Complete Bao groups with a constructive, guaranteed full-ticket capacity.

The supported maximum is a reproducible system capacity, not an asserted
optimal packing bound. For 5/35 each special ball has an independent packing;
overlap between those packings is valid because the complete tickets differ.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
from functools import lru_cache
from pathlib import Path

RULE_VERSION = 'tracking_bao_full_ticket_v3'
PLAN_PATH = Path(__file__).resolve().parents[1] / 'config/tracking-bao-packing-v2.json'
GAMES = {
    'LOTO_5_35': (35, 5, (4, *range(6, 16))),
    'LOTO_6_45': (45, 6, (5, *range(7, 16), 18)),
    'LOTO_6_55': (55, 6, (5, *range(7, 16), 18)),
}

def children_per_bao(game, level):
    n, t, levels = GAMES[game]
    if type(level) is not int or level not in levels:
        raise ValueError('Mức Bao không được hỗ trợ.')
    return n - level if level < t else math.comb(level, t)

def _children(parent, n, t):
    if len(parent) < t:
        core = set(parent)
        return (tuple(sorted((*parent, number))) for number in range(1, n + 1) if number not in core)
    return itertools.combinations(parent, t)

@lru_cache(maxsize=None)
def _modular_count(n, k):
    # All k-subsets with sum zero modulo n, counted exactly (also for composite n).
    dp = [[0] * n for _ in range(k + 1)]
    dp[0][0] = 1
    for number in range(1, n + 1):
        for length in range(min(k, number), 0, -1):
            for residue, count in enumerate(dp[length - 1]):
                dp[length][(residue + number) % n] += count
    return dp[k][0]

def _modular_parents(n, k):
    for prefix in itertools.combinations(range(1, n), k - 1):
        last = (-sum(prefix)) % n or n
        if last > prefix[-1]:
            yield (*prefix, last)

@lru_cache(maxsize=1)
def _plans():
    result = json.loads(PLAN_PATH.read_text(encoding='utf-8'))
    if result.get('version') != 2:
        raise ValueError('Bộ cấu trúc Bao không đúng phiên bản.')
    return result['plans']

def unique_by(game):
    return 'main_numbers_and_special' if game == 'LOTO_5_35' else 'main_numbers'

def ticket_key(game, ticket):
    """Power's auxiliary predicted seventh number is not a purchased number."""
    main = tuple(sorted(ticket.get('main') or []))
    return (*main, ticket.get('special')) if game == 'LOTO_5_35' else main

def _family_capacity(game, level):
    n, t, _ = GAMES[game]
    return (_modular_count(n, level) if level in (t - 1, t + 1)
            else len(_plans()[game][str(level)]['parents']))

def limits(game, maximum):
    if game not in GAMES:
        return {}
    levels = GAMES[game][2]
    special_count = 12 if game == 'LOTO_5_35' else 1
    return {str(k): min(maximum // children_per_bao(game, k),
                       special_count * _family_capacity(game, k)) for k in levels}

def configuration(game, play_mode='normal', level=None, count=None, maximum=1000000, *, strict=True):
    if play_mode not in ('normal', 'bao') or (game not in GAMES and play_mode == 'bao'):
        raise ValueError('Cơ cấu vé không được hỗ trợ.')
    caps = limits(game, maximum)
    result = {'playMode': play_mode, 'supportedBaoLevels': list(GAMES[game][2]) if game in GAMES else [],
              'maxBaoCounts': caps, 'baoRuleVersion': RULE_VERSION, 'uniqueBy': unique_by(game), 'configurationValid': True,
              'configurationError': ''}
    if play_mode == 'normal':
        return {**result, 'baoLevel': None, 'baoCount': 0, 'childrenPerBao': 0, 'maxBaoCount': 0}
    per = children_per_bao(game, level)
    maximum_count = caps[str(level)]
    error = ''
    if type(count) is not int or not 1 <= count <= maximum_count:
        formatted = f'{maximum_count:,}'.replace(',', '.')
        error = f'Bao {level} hỗ trợ tối đa {formatted} Bao / phương pháp để giữ vé con không trùng hoàn toàn. Hãy lưu lại cấu hình hợp lệ.'
    if strict and error:
        raise ValueError(error)
    return {**result, 'baoLevel': level, 'baoCount': count, 'childrenPerBao': per,
            'maxBaoCount': maximum_count, 'configurationValid': not error, 'configurationError': error}

@lru_cache(maxsize=None)
def _checked_template(game, level):
    n, t, _ = GAMES[game]
    parents = tuple(tuple(row) for row in _plans()[game][str(level)]['parents'])
    seen = set()
    for parent in parents:
        if len(parent) != level or tuple(sorted(set(parent))) != parent or not 1 <= min(parent) <= max(parent) <= n:
            raise ValueError('Bộ cấu trúc Bao chứa nhóm không hợp lệ.')
        for child in _children(parent, n, t):
            if child in seen:
                raise ValueError('Bộ cấu trúc Bao có vé con trùng.')
            seen.add(child)
    return parents

def _parent_templates(game, level):
    n, t, _ = GAMES[game]
    return _modular_parents(n, level) if level in (t - 1, t + 1) else iter(_checked_template(game, level))

def _mapped_parents(game, level, probabilities, original, rng):
    n = GAMES[game][0]
    plan = _parent_templates(game, level)
    first = next(plan)
    rank = sorted(range(1, n + 1), key=lambda v: -math.log(max(rng.random(), 1e-15)) / max(probabilities[v], 1e-12))
    chosen = [v for v in rank if v in original][:level]
    chosen += [v for v in rank if v not in chosen][:level - len(chosen)]
    rng.shuffle(chosen)
    rest_vertices = [v for v in range(1, n + 1) if v not in first]
    rest_numbers = [v for v in rank if v not in chosen]
    mapping = dict(zip((*first, *rest_vertices), (*chosen, *rest_numbers)))
    for template in itertools.chain((first,), plan):
        yield tuple(sorted(mapping[v] for v in template))

def _parent_groups(game, level, count, probabilities, original, first_special, rng):
    if game == 'LOTO_5_35':
        # Distinct special balls make tickets distinct even when mains overlap.
        # Each stream is independently main-disjoint. Round-robin allocation
        # keeps group counts per special ball within one of each other.
        rest = [v for v in range(1, 13) if v != first_special]
        rng.shuffle(rest)
        streams = [(special, _mapped_parents(game, level, probabilities, original, rng))
                   for special in (first_special, *rest)]
    else:
        streams = [(None, _mapped_parents(game, level, probabilities, original, rng))]
    for index in range(count):
        special, parents = streams[index % len(streams)]
        try:
            yield next(parents), special
        except StopIteration as error:
            raise RuntimeError('Bộ cấu trúc Bao không đủ số nhóm đã xác nhận.') from error

def build(payload, game, level, count, maximum=1000000):
    structure = configuration(game, 'bao', level, count, maximum)
    n, t, _ = GAMES[game]
    source = payload.get('tickets') or []
    probabilities = {int(key): float(value) for key, value in (payload.get('probabilities') or {}).items()}
    if (set(probabilities) != set(range(1, n + 1)) or
            any(not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities.values()) or
            abs(sum(probabilities.values()) - t) > 1e-5 or not source):
        raise ValueError('Thiếu vé gốc hoặc xác suất hợp lệ để tạo Bao.')
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    seed = int(hashlib.sha256(f'{RULE_VERSION}:{game}:{level}:{count}:{encoded}'.encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    original = source[0].get('main') or []
    if len(original) != t or len(set(original)) != t or any(type(v) is not int or not 1 <= v <= n for v in original):
        raise ValueError('Vé gốc không hợp lệ.')
    first_special = source[0].get('special')
    if game == 'LOTO_5_35' and (type(first_special) is not int or not 1 <= first_special <= 12):
        raise ValueError('Thiếu số đặc biệt hợp lệ cho Bao 5/35.')
    parents = []
    groups = _parent_groups(game, level, count, probabilities, original, first_special, rng)
    for index, (parent, special) in enumerate(groups, 1):
        parents.append({'parentIndex': index, 'main': list(parent), 'special': special,
                        'childCount': structure['childrenPerBao']})
    if len(parents) != count:
        raise RuntimeError('Chưa tạo đủ số Bao đã xác nhận.')
    # Purchased Bao groups are the sole stored selection class. There is no
    # second normal-ticket portfolio and no persisted child-ticket array.
    return {**payload, 'tickets': [], 'ticketClass': 'bao', 'predictionMode': 'bao',
            'ticketStorage': 'bao_parents_v1', 'randomSeed': seed % 2147483647,
            'allocationPolicy': RULE_VERSION,
            'bao': {**structure, 'ruleVersion': RULE_VERSION, 'parents': parents,
                    'uniqueBy': unique_by(game), 'templatePolicy': 'independent_special_packings' if game == 'LOTO_5_35' else 'modular_or_verified_packing'}}


def iter_equivalents(game, parents):
    """Internal mathematical expansion for prize/fee verification, never a
    separately generated or purchased normal-ticket portfolio.
    """
    n, t, _ = GAMES[game]
    for parent in parents:
        for child in _children(tuple(parent['main']), n, t):
            special = parent.get('special')
            if game == 'LOTO_6_55':
                # The predicted auxiliary Power ball is not a purchased number.
                special = next(value for value in range(1, n + 1) if value not in child)
            yield {'main': list(child), 'special': special}


def scoring_payload(payload):
    """Score the selected Bao's combinations without storing another class."""
    if payload.get('ticketStorage') != 'bao_parents_v1':
        return payload
    return {**payload, 'tickets': list(iter_equivalents(payload['type'], payload['bao']['parents']))}


def parent_prizes(game, parent, actual):
    """Aggregate a Bao's prize multiplicities without creating normal tickets."""
    from ai.prizes import classify_ticket, prize_statistics
    n, t, _ = GAMES[game]
    main = sorted(parent['main'])
    choices = []
    if len(main) < t:
        choices = [(tuple(sorted((*main, number))), 1) for number in range(1, n + 1) if number not in main]
    else:
        matched = [number for number in main if number in (actual or {}).get('main', [])]
        auxiliary = [number for number in main if number not in matched and game == 'LOTO_6_55' and number == (actual or {}).get('special')]
        other = [number for number in main if number not in matched and number not in auxiliary]
        for hit in range(min(t, len(matched)) + 1):
            for extra in range(len(auxiliary) + 1):
                remaining = t - hit - extra
                if 0 <= remaining <= len(other):
                    multiplicity = math.comb(len(matched), hit) * math.comb(len(auxiliary), extra) * math.comb(len(other), remaining)
                    choices.append((tuple(sorted((*matched[:hit], *auxiliary[:extra], *other[:remaining]))), multiplicity))
    counts, stats, labels = {}, prize_statistics([]), {}
    for selection, multiplicity in choices:
        result = classify_ticket(game, {'main': list(selection), 'special': parent.get('special')}, actual)
        code, status = result['prizeCode'], result['status']
        counts[code] = counts.get(code, 0) + multiplicity
        labels[code] = result['prizeLabel']
        stats['ticketCount'] += multiplicity
        stats['classifiedTicketCount'] += multiplicity * (status in ('won', 'lost'))
        stats['winningTicketCount'] += multiplicity * (status == 'won')
        stats['unknownTicketCount'] += multiplicity * (status == 'unknown')
        stats['pendingTicketCount'] += multiplicity * (status == 'pending')
        stats['invalidTicketCount'] += multiplicity * (status in ('invalid', 'unsupported'))
    stats['winningTicketRate'] = stats['winningTicketCount'] / stats['classifiedTicketCount'] if stats['classifiedTicketCount'] else None
    status = ('won' if stats['winningTicketCount'] else 'unknown' if stats['unknownTicketCount'] else
              'pending' if stats['pendingTicketCount'] else 'invalid' if stats['invalidTicketCount'] else 'lost')
    return {'prizeCounts': counts, 'prizeStatistics': stats, 'status': status,
            'label': f"{stats['winningTicketCount']:,} tổ hợp trúng".replace(',', '.') if status == 'won' else
                     {'unknown': 'Chưa xác định', 'pending': 'Chờ kết quả', 'invalid': 'Không hợp lệ', 'lost': 'Không trúng'}[status],
            'details': ' · '.join(f'{labels[code]}: {count:,}'.replace(',', '.') for code, count in counts.items())}


def expand(payload, game, level, count, maximum=1000000):
    structure = configuration(game, 'bao', level, count, maximum)
    n, t, _ = GAMES[game]
    source = payload.get('tickets') or []
    probabilities = {int(key): float(value) for key, value in (payload.get('probabilities') or {}).items()}
    if (set(probabilities) != set(range(1, n + 1)) or
            any(not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities.values()) or
            abs(sum(probabilities.values()) - t) > 1e-5 or not source):
        raise ValueError('Thiếu vé gốc hoặc xác suất hợp lệ để tạo Bao.')
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    seed = int(hashlib.sha256(f'{RULE_VERSION}:{game}:{level}:{count}:{encoded}'.encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    original = source[0].get('main') or []
    if len(original) != t or len(set(original)) != t or any(type(v) is not int or not 1 <= v <= n for v in original):
        raise ValueError('Vé gốc không hợp lệ.')
    first_special = source[0].get('special')
    if game == 'LOTO_5_35' and (type(first_special) is not int or not 1 <= first_special <= 12):
        raise ValueError('Thiếu số đặc biệt hợp lệ cho Bao 5/35.')
    tickets, parents = [], []
    groups = _parent_groups(game, level, count, probabilities, original, first_special, rng)
    for index, (parent, special) in enumerate(groups, 1):
        parents.append({'parentIndex': index, 'main': list(parent), 'special': special, 'childCount': structure['childrenPerBao']})
        for child_index, child in enumerate(_children(parent, n, t), 1):
            compatibility = rng.choice([v for v in range(1, n + 1) if v not in child]) if game == 'LOTO_6_55' else special
            tickets.append({'main': list(child), 'special': compatibility,
                            'bao': {'ruleVersion': RULE_VERSION, 'parentIndex': index, 'childIndex': child_index, 'level': level}})
    if len(parents) != count or len(tickets) != count * structure['childrenPerBao']:
        raise RuntimeError('Bộ cấu trúc Bao không đủ số nhóm đã xác nhận.')
    return {**payload, 'tickets': tickets, 'randomSeed': seed % 2147483647,
            'allocationPolicy': RULE_VERSION,
            'bao': {**structure, 'ruleVersion': RULE_VERSION, 'parents': parents,
                    'uniqueBy': unique_by(game), 'templatePolicy': 'independent_special_packings' if game == 'LOTO_5_35' else 'modular_or_verified_packing'}}
