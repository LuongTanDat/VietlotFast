import gc
import itertools
import json
import math
import random
import unittest
from contextlib import closing
from unittest import mock

from ai import tracking_bao as bao, prediction_effectiveness as pe
from tests.test_prediction_effectiveness import PredictionEffectivenessTests


def payload(game, seed=1):
    n, t, _ = bao.GAMES[game]
    return {'ok': True, 'ready': True, 'type': game, 'randomSeed': seed, 'engine': 'random',
            'tickets': [{'main': list(range(1, t + 1)), 'special': 1 if t == 5 else n if n == 55 else None}],
            'probabilities': {str(v): t / n for v in range(1, n + 1)}}


class BaoPackingTests(unittest.TestCase):
    def test_every_advertised_maximum_has_complete_disjoint_groups(self):
        for game, (n, t, levels) in bao.GAMES.items():
            caps = bao.limits(game, pe.ticket_limit(game))
            for level in levels:
                with self.subTest(game=game, level=level):
                    groups = bao._parent_groups(game, level, caps[str(level)],
                        {v: t / n for v in range(1, n + 1)}, list(range(1, t + 1)), 1, random.Random(17))
                    seen, count = set(), 0
                    for parent, special in groups:
                        children = list(bao._children(parent, n, t))
                        self.assertEqual(len(children), bao.children_per_bao(game, level))
                        keys = [(*child, special) if game == 'LOTO_5_35' else child for child in children]
                        self.assertFalse(any(key in seen for key in keys))
                        seen.update(keys)
                        count += 1
                    self.assertEqual(count, caps[str(level)])
                    self.assertLessEqual(len(seen), pe.ticket_limit(game))
                    del seen
        self.assertEqual(bao.limits('LOTO_5_35', 324632)['6'], 54105)
        self.assertEqual(bao.limits('LOTO_6_45', 1000000)['7'], 142857)
        self.assertEqual(bao.limits('LOTO_6_55', 1000000)['7'], 142857)

    def test_maximum_default_expansion_is_complete_unique_and_reproducible(self):
        for game, (n, t, _) in bao.GAMES.items():
            maximum = pe.ticket_limit(game)
            cap = bao.limits(game, maximum)[str(t + 1)]
            result = bao.expand(payload(game), game, t + 1, cap, maximum)
            tickets = result['tickets']
            self.assertEqual(len(tickets), cap * (t + 1))
            self.assertEqual(len({bao.ticket_key(game, ticket) for ticket in tickets}), len(tickets))
            self.assertEqual(len(result['bao']['parents']), cap)
            self.assertEqual(result['probabilities'], payload(game)['probabilities'])
            self.assertTrue(set(range(1, t + 1)) <= set(result['bao']['parents'][0]['main']))
            if t == 5:
                self.assertLess(len({tuple(ticket['main']) for ticket in tickets}), len(tickets))
                counts = [sum(parent['special'] == special for parent in result['bao']['parents']) for special in range(1, 13)]
                self.assertLessEqual(max(counts) - min(counts), 1)
                for start in range(0, len(tickets), t + 1):
                    self.assertEqual(len({row['special'] for row in tickets[start:start + t + 1]}), 1)
            if n == 55:
                self.assertTrue(all(row['special'] not in row['main'] for row in tickets))
            del tickets, result
            gc.collect()
        a = bao.expand(payload('LOTO_5_35'), 'LOTO_5_35', 6, 100, 324632)
        self.assertEqual(a, bao.expand(payload('LOTO_5_35'), 'LOTO_5_35', 6, 100, 324632))
        self.assertNotEqual(a['tickets'], bao.expand(payload('LOTO_5_35', 2), 'LOTO_5_35', 6, 100, 324632)['tickets'])

    def test_invalid_cap_rejected_without_partial_generation(self):
        with mock.patch.object(bao, '_modular_parents') as generator:
            with self.assertRaisesRegex(ValueError, '54.105'):
                bao.expand(payload('LOTO_5_35'), 'LOTO_5_35', 6, 54106, 324632)
            generator.assert_not_called()

    def test_zero_probability_is_valid_but_invalid_vectors_are_rejected(self):
        source = payload('LOTO_5_35')
        amount = source['probabilities']['35']
        source['probabilities']['35'] = 0
        source['probabilities']['1'] += amount
        self.assertEqual(len(bao.expand(source, 'LOTO_5_35', 6, 2, 324632)['tickets']), 12)
        source['probabilities']['35'] = -1
        with self.assertRaises(ValueError):
            bao.expand(source, 'LOTO_5_35', 6, 2, 324632)


class BaoCycleTests(PredictionEffectivenessTests):
    def test_bao_four_methods_atomic_charge_count_hash_and_immutability(self):
        settings = pe.configure(self.GAME, True, 3, 'fixture', self.db,
                                play_mode='bao', bao_level=6, bao_count=10)['settings']
        with mock.patch.object(pe.billing, 'reserve', return_value=None) as reserve:
            with self.assertRaisesRegex(ValueError, 'Cấu hình đã thay đổi'):
                pe.cycle(self.GAME, self.db, configuration_hash='0' * 64)
            reserve.assert_not_called()
            result = pe.cycle(self.GAME, self.db, configuration_hash=settings['configurationHash'])
            reserve.assert_called_once_with(self.GAME, '41', 240)
        self.assertEqual(result['ticketCount'], 60)
        with closing(pe._connect(self.db)) as connection:
            runs = connection.execute('SELECT payload_json FROM prediction_runs').fetchall()
            self.assertEqual(len(runs), 4)
            for run in runs:
                saved = json.loads(run[0])
                self.assertEqual(saved['tickets'], [])
                self.assertEqual(saved['ticketClass'], 'bao')
                self.assertEqual(len(saved['bao']['parents']), 10)
        before = self._counts()
        self.assertEqual(pe.cycle(self.GAME, self.db)['status'], 'already_locked')
        self.assertEqual(self._counts(), before)

    def test_legacy_oversized_settings_readable_but_never_reserves_money(self):
        pe.configure(self.GAME, True, 3, 'fixture', self.db, play_mode='bao', bao_level=6, bao_count=10)
        with closing(pe._connect(self.db)) as connection:
            connection.execute('UPDATE effectiveness_settings SET bao_count=54106 WHERE game_type=?', (self.GAME,))
        settings = pe.settings(self.GAME, self.db)['settings']
        self.assertFalse(settings['configurationValid'])
        self.assertEqual(settings['maxBaoCount'], 54105)
        with mock.patch.object(pe.billing, 'reserve') as reserve:
            with self.assertRaisesRegex(ValueError, '54.105'):
                pe.cycle(self.GAME, self.db)
            reserve.assert_not_called()
        self.assertEqual(self._counts()['prediction_runs'], 0)

    def test_same_mains_different_special_survive_lock_scoring_and_export(self):
        def web(game, count, snapshot):
            result = self._web(game, count, snapshot)
            result['tickets'] = [{'main': [1, 2, 3, 4, 5], 'special': 2}]
            return result
        self.web.side_effect = web
        pe.configure(self.GAME, True, 3, 'fixture', self.db, play_mode='bao', bao_level=6, bao_count=2)
        cycle = pe.cycle(self.GAME, self.db)
        self._actual()
        self.assertTrue(pe.score_cycles(self.GAME, self.db)['ok'])
        exported = pe.export_cycle(self.GAME, cycle['cycleId'], self.db)
        entry = exported['methods']['web']
        self.assertNotIn('tickets', entry)
        self.assertEqual(len(entry['baoParents']), 2)
        self.assertEqual(entry['prizeCounts'].get('LOTTO_JACKPOT'), 1)
        self.assertEqual(entry['prizeCounts'].get('FIRST'), 1)
        self.assertEqual(exported['config']['uniqueBy'], 'main_numbers_and_special')


if __name__ == '__main__':
    unittest.main()
