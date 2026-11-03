"""Seed causality, maximum unique capacity and immutable prospective provenance."""
import itertools
import json
import math
import sqlite3
import unittest
from contextlib import closing
from unittest import mock

from ai import tracking_ticket_seed as seeds, tracking_bao as bao, prediction_effectiveness as pe
from tests.test_prediction_effectiveness import PredictionEffectivenessTests as Fixture
from tests.test_tracking_bao_recovery import payload


class TicketSeedTests(unittest.TestCase):
    def spec(self, count=100, **extra):
        return seeds.schedule(1234567, 'LOTO_5_35', '975', 'web', count, **extra)

    def test_seeds_are_stable_separate_by_index_and_context(self):
        spec = self.spec(10000)
        values = [seeds.derive(spec, index) for index in range(1, 10001)]
        self.assertEqual(len(set(values)), 10000)
        self.assertEqual(values[0], seeds.derive(spec, 1))
        self.assertEqual(len(values[0]), 64)
        for key, value in [('rootSeed', '99'), ('method', 'random'), ('targetDrawId', '976'), ('type', 'LOTO_6_45'), ('baoLevel', 6), ('ticketClass', 'bao')]:
            self.assertNotEqual(seeds.derive({**spec, key: value}, 1), values[0])
        for index in (0, -1, True, 10001):
            with self.assertRaises(ValueError):
                seeds.derive(spec, index)

    def test_sparse_first_ticket_uses_its_own_stream_and_numpy_matches_fallback(self):
        spec = self.spec(1000)
        probabilities = {n: (n + 100) / 10000 for n in range(1, 36)}
        first_stream = seeds.Stream(seeds.derive(spec, 1))
        expected = tuple(sorted(sorted(probabilities, key=lambda n: -math.log(first_stream.uniform(n - 1)) / probabilities[n])[:5]))
        first = seeds.mains(probabilities, 5, 1000, spec)
        self.assertEqual(first[0], expected)
        self.assertEqual(len(set(first)), 1000)
        self.assertEqual(first, seeds.mains(probabilities, 5, 1000, spec))
        with mock.patch.object(seeds, 'np', None):
            self.assertEqual(first, seeds.mains(probabilities, 5, 1000, spec))
        self.assertNotEqual(first, seeds.mains(probabilities, 5, 1000, {**spec, 'rootSeed': '42'}))

    def test_dense_full_capacity_is_complete_and_first_seed_selects_pool_rank(self):
        count = math.comb(8, 3)
        spec = self.spec(count)
        probabilities = {number: 1 for number in range(1, 9)}
        candidates = list(itertools.combinations(range(1, 9), 3))
        rank = seeds.Stream(seeds.derive(spec, 1)).below(count * (1 << 40)) // (1 << 40)
        result = seeds.mains(probabilities, 3, count, spec)
        self.assertEqual(result[0], candidates[rank])
        self.assertEqual(set(result), set(candidates))
        self.assertEqual(result, seeds.mains(probabilities, 3, count, spec))

    def test_535_maximum_covers_every_main_combination_without_stalling(self):
        count = math.comb(35, 5)
        result = seeds.mains({number: 1 / 7 for number in range(1, 36)}, 5, count, self.spec(count))
        self.assertEqual(len(result), 324632)
        self.assertEqual(len(set(result)), count)
        self.assertTrue(all(len(main) == 5 and main[0] >= 1 and main[-1] <= 35 for main in result))

    def test_new_bao_maximum_keeps_only_parents_and_full_ticket_uniqueness(self):
        for game, level, maximum in [('LOTO_5_35', 6, 324632), ('LOTO_6_45', 7, 1000000), ('LOTO_6_55', 7, 1000000)]:
            with self.subTest(game=game):
                count = bao.limits(game, maximum)[str(level)]
                spec = seeds.schedule(123, game, '50', 'web', count, play_mode='bao', bao_level=level)
                built = bao.build(payload(game), game, level, count, maximum, seed_schedule=spec)
                self.assertEqual(built['tickets'], [])
                self.assertEqual(len(built['bao']['parents']), count)
                keys = {bao.ticket_key(game, ticket) for ticket in bao.iter_equivalents(game, built['bao']['parents'])}
                self.assertEqual(len(keys), count * bao.children_per_bao(game, level))
                self.assertNotEqual(seeds.derive(spec, 1), seeds.derive(spec, 2))


class TicketSeedCycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_all_four_methods_freeze_schedule_and_page_by_global_index(self):
        f = self.fixture
        pe.configure(f.GAME, True, 12, 'fixture', f.db)
        locked = pe.cycle(f.GAME, f.db)
        report = pe.report(f.GAME, db_path=f.db)
        cycle = report['cycles'][0]
        roots = set()
        for method, entry in cycle['methods'].items():
            spec = entry['seedSchedule']
            self.assertEqual(spec['method'], method)
            self.assertEqual(str(entry['seed']), spec['rootSeed'])
            roots.add(seeds.derive(spec, 1))
            page = pe.ticket_page(f.GAME, entry['predictionId'], 2, f.db)
            self.assertEqual([row['ticketSeed'] for row in page['tickets']], [seeds.derive(spec, index) for index in (11, 12)])
            self.assertEqual(entry['tickets'][0]['ticketSeed'], seeds.derive(spec, 1))
            with closing(pe._connect(f.db)) as connection:
                saved = json.loads(connection.execute('SELECT payload_json FROM prediction_runs WHERE prediction_id=?', (entry['predictionId'],)).fetchone()[0])
            self.assertEqual(saved['ticketSeedSchedule'], spec)
            rebuilt = seeds.normal(saved, f.GAME, spec, 12)
            self.assertEqual(rebuilt['tickets'], saved['tickets'])
        self.assertEqual(len(roots), 4)
        pe.configure(f.GAME, False, 2, 'fixture', f.db)
        self.assertEqual(pe.cycle(f.GAME, f.db)['cycleId'], locked['cycleId'])
        self.assertEqual(pe.report(f.GAME, db_path=f.db)['cycles'][0]['config']['ticketSeedSchedules'], cycle['config']['ticketSeedSchedules'])

    def test_bao_schedules_replay_original_groups_and_keep_selected_class(self):
        f = self.fixture
        pe.configure(f.GAME, True, 3, 'fixture', f.db, play_mode='bao', bao_level=6, bao_count=15)
        pe.cycle(f.GAME, f.db)
        entry = pe.report(f.GAME, db_path=f.db)['cycles'][0]['methods']['web']
        spec = entry['seedSchedule']
        with closing(pe._connect(f.db)) as connection:
            saved = json.loads(connection.execute('SELECT payload_json FROM prediction_runs WHERE prediction_id=?', (entry['predictionId'],)).fetchone()[0])
        source = {**saved, 'tickets': [{'main': spec['sourceMain'], 'special': spec['sourceSpecial']}]}
        replay = bao.build(source, f.GAME, 6, 15, 324632, seed_schedule=spec)
        self.assertEqual(saved['bao']['parents'], replay['bao']['parents'])
        page = pe.ticket_page(f.GAME, entry['predictionId'], 2, f.db)
        self.assertEqual([row['ticketSeed'] for row in page['baoParents']], [seeds.derive(spec, index) for index in range(11, 16)])
        self.assertNotIn('tickets', page)

    def test_legacy_cycle_keeps_checksum_and_has_no_invented_ticket_seeds(self):
        f = self.fixture
        pe.configure(f.GAME, True, 3, 'fixture', f.db)
        original = pe.ledger.lock_prediction
        def legacy_lock(value, **kwargs):
            value = {key: val for key, val in value.items() if key != 'ticketSeedSchedule'}
            return original(value, **kwargs)
        with mock.patch.object(pe.ledger, 'lock_prediction', side_effect=legacy_lock):
            locked = pe.cycle(f.GAME, f.db)
        # Model an old frozen config, using the same immutable-trigger bypass a
        # legacy fixture needs; production never updates a frozen cycle.
        with closing(sqlite3.connect(f.db, isolation_level=None)) as connection:
            config = json.loads(connection.execute('SELECT config_json FROM effectiveness_cycles').fetchone()[0])
            config.pop('ticketSeedSchedules'); config.pop('ticketSeedVersion')
            connection.execute('DROP TRIGGER effectiveness_cycle_immutable')
            connection.execute('UPDATE effectiveness_cycles SET config_json=?', (json.dumps(config),))
            before = [tuple(row) for row in connection.execute('SELECT prediction_id,payload_checksum,tickets_json FROM prediction_runs ORDER BY prediction_id')]
        cycle = pe.report(f.GAME, db_path=f.db)['cycles'][0]
        entry = cycle['methods']['web']
        self.assertNotIn('seedSchedule', entry)
        self.assertTrue(all('ticketSeed' not in row for row in entry['tickets']))
        self.assertTrue(all('ticketSeed' not in row for row in pe.ticket_page(f.GAME, entry['predictionId'], db_path=f.db)['tickets']))
        self.assertEqual(pe.cycle(f.GAME, f.db)['cycleId'], locked['cycleId'])
        with closing(pe._connect(f.db)) as connection:
            self.assertEqual(before, [tuple(row) for row in connection.execute('SELECT prediction_id,payload_checksum,tickets_json FROM prediction_runs ORDER BY prediction_id')])
