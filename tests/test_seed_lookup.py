"""General seed lookup across games/classes/methods using disposable ledgers."""
import hashlib
import json
import sqlite3
import subprocess
import sys
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest import mock

from ai import prediction_effectiveness as pe, seed_lookup as lookup, tracking_ticket_seed as seeds
from tests.test_prediction_effectiveness import PredictionEffectivenessTests as Fixture

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/tra_seed.py'


class SeedLookupTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def lock(self, *, game='LOTO_5_35', mode='normal', count=12):
        f = self.fixture
        f.GAME = game
        if game != 'LOTO_5_35':
            for row in f.draws:
                row.update(date='04/01/2030' if game == 'LOTO_6_45' else '05/01/2030', time='18:00',
                           main=[1, 2, 3, 4, 5, 6], special=None if game == 'LOTO_6_45' else 55)
            f._write()
        pe.configure(game, True, count if mode == 'normal' else 3, 'fixture', f.db,
                     play_mode=mode, bao_level=(6 if game == 'LOTO_5_35' else 7) if mode == 'bao' else None,
                     bao_count=count if mode == 'bao' else None)
        locked = pe.cycle(game, f.db)
        return next(row for row in pe.report(game, db_path=f.db)['cycles'] if row['cycleId'] == locked['cycleId'])

    def digest(self):
        return hashlib.sha256(self.fixture.db.read_bytes()).hexdigest()

    def test_all_games_all_four_methods_normal_and_bao_replay_without_database_changes(self):
        for game in lookup.GAMES:
            for mode in ('normal', 'bao'):
                with self.subTest(game=game, mode=mode):
                    cycle = self.lock(game=game, mode=mode)
                    before = self.digest()
                    for method, entry in cycle['methods'].items():
                        for index in (1, 12):
                            spec = entry['seedSchedule']
                            seed = seeds.derive(spec, index)
                            result = lookup.lookup(seed.upper(), self.fixture.db, game=game,
                                                   draw=cycle['targetDrawId'], method=method)
                            self.assertEqual(result['status'], 'found')
                            self.assertEqual(len(result['matches']), 1)
                            match = result['matches'][0]
                            self.assertEqual(match['index'], index)
                            self.assertEqual(match['method'], method)
                            self.assertEqual(match['ticketClass'], mode)
                            self.assertEqual(match['replay']['status'], 'verified')
                            self.assertTrue(match['replay']['matchesStored'])
                            page = pe.ticket_page(game, entry['predictionId'], 1 if index == 1 else 2, self.fixture.db)
                            stored = page['baoParents' if mode == 'bao' else 'tickets'][0 if index == 1 else 1]
                            self.assertEqual(match['selection'], {'main': stored['main'], 'special': stored.get('special')})
                    self.assertEqual(before, self.digest())

    def test_invalid_unknown_and_filtered_seed_do_not_guess_or_create_data(self):
        cycle = self.lock()
        entry = cycle['methods']['web']
        seed = seeds.derive(entry['seedSchedule'], 1)
        for invalid in ('', seed[:6], 'g' * 64, seed + 'a'):
            with self.assertRaisesRegex(ValueError, '64'):
                lookup.lookup(invalid, self.fixture.db)
        self.assertEqual(lookup.lookup('0' * 64, self.fixture.db)['matches'], [])
        self.assertEqual(lookup.lookup(seed, self.fixture.db, method='random')['status'], 'not_found')
        self.assertEqual(lookup.lookup(seed, self.fixture.db, draw='999')['status'], 'not_found')
        for kwargs in ({'game': 'KENO'}, {'draw': '-1'}, {'method': 'unknown'}):
            with self.assertRaises(ValueError):
                lookup.lookup(seed, self.fixture.db, **kwargs)
        missing = self.fixture.root / 'must_not_create.db'
        with self.assertRaises(FileNotFoundError):
            lookup.lookup(seed, missing)
        self.assertFalse(missing.exists())
        with lookup.readonly(self.fixture.db) as connection:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute('DELETE FROM effectiveness_cycles')

    def test_chunked_normal_tail_and_missing_chunk_are_handled_explicitly(self):
        cycle = self.lock(count=10002)
        entry = cycle['methods']['web']
        seed = seeds.derive(entry['seedSchedule'], 10002)
        result = lookup.lookup(seed, self.fixture.db)
        self.assertEqual(result['matches'][0]['replay']['status'], 'verified')
        self.assertEqual(result['matches'][0]['index'], 10002)
        with closing(sqlite3.connect(self.fixture.db, isolation_level=None)) as connection:
            connection.execute('DELETE FROM effectiveness_ticket_chunks WHERE prediction_id=? AND chunk_number=10', (entry['predictionId'],))
        with self.assertRaisesRegex(ValueError, 'Không đủ dữ liệu vé'):
            lookup.lookup(seed, self.fixture.db)

    def test_dense_normal_replay_uses_full_frozen_budget(self):
        cycle = self.lock(count=82000)
        entry = cycle['methods']['random']
        result = lookup.lookup(seeds.derive(entry['seedSchedule'], 81999), self.fixture.db, method='random')
        self.assertEqual(result['matches'][0]['index'], 81999)
        self.assertEqual(result['matches'][0]['replay']['status'], 'verified')

    def test_changed_generator_fingerprint_preserves_stored_lookup_but_refuses_replay(self):
        with mock.patch.object(pe, '_execution_manifest', return_value={'ai/tracking_ticket_seed.py': '0' * 64}):
            cycle = self.lock()
        entry = cycle['methods']['web']
        with mock.patch.object(seeds, 'normal', side_effect=AssertionError('wrong source must not run')):
            result = lookup.lookup(seeds.derive(entry['seedSchedule'], 1), self.fixture.db)
        match = result['matches'][0]
        self.assertEqual(match['replay']['status'], 'unavailable')
        self.assertIn('Mã nguồn', match['replay']['reason'])
        self.assertEqual(match['selection']['main'], entry['tickets'][0]['main'])

    def test_replay_mismatch_is_not_reported_as_verified(self):
        original = pe.ledger.lock_prediction
        def faulty(payload, **kwargs):
            changed = {**payload, 'tickets': list(payload['tickets'])}
            main = changed['tickets'][0]['main']
            changed['tickets'][0] = {**changed['tickets'][0], 'main': [n for n in range(1, 36) if n not in main][:5]}
            return original(changed, **kwargs)
        with mock.patch.object(pe.ledger, 'lock_prediction', side_effect=faulty):
            cycle = self.lock(count=3)
        entry = cycle['methods']['web']
        result = lookup.lookup(seeds.derive(entry['seedSchedule'], 1), self.fixture.db)
        self.assertEqual(result['matches'][0]['replay']['status'], 'mismatch')
        self.assertFalse(result['matches'][0]['replay']['matchesStored'])

    def test_missing_template_still_returns_stored_bao_without_claiming_replay(self):
        cycle = self.lock(mode='bao')
        entry = cycle['methods']['web']
        with mock.patch.object(lookup.bao, 'PLAN_PATH', self.fixture.root / 'missing-template.json'):
            result = lookup.lookup(seeds.derive(entry['seedSchedule'], 1), self.fixture.db)
        self.assertEqual(result['matches'][0]['replay']['status'], 'unavailable')
        self.assertIn('Không đọc được', result['matches'][0]['replay']['reason'])
        self.assertEqual(len(result['matches'][0]['selection']['main']), 6)

    def test_missing_frozen_probabilities_is_explicit_and_lookup_only_does_not_generate(self):
        cycle = self.lock()
        seed = seeds.derive(cycle['methods']['web']['seedSchedule'], 1)
        original = lookup._record
        def incomplete(*args):
            record, stored = original(*args)
            return {**record, 'probabilities': None}, stored
        with mock.patch.object(lookup, '_record', side_effect=incomplete):
            result = lookup.lookup(seed, self.fixture.db)
        self.assertEqual(result['matches'][0]['replay']['status'], 'unavailable')
        with mock.patch.object(seeds, 'normal', side_effect=AssertionError('lookup only must not generate')):
            self.assertEqual(lookup.lookup(seed, self.fixture.db, replay=False)['matches'][0]['replay']['status'], 'skipped')

    def test_old_cycles_are_not_given_seeds_and_unknown_versions_are_reported(self):
        cycle = self.lock()
        seed = seeds.derive(cycle['methods']['web']['seedSchedule'], 1)
        config = cycle['config']
        with closing(sqlite3.connect(self.fixture.db, isolation_level=None)) as connection:
            connection.execute('DROP TRIGGER effectiveness_cycle_immutable')
            old = {key: value for key, value in config.items() if key not in ('ticketSeedSchedules', 'ticketSeedVersion')}
            connection.execute('UPDATE effectiveness_cycles SET config_json=?', (json.dumps(old),))
            result = lookup.lookup(seed, self.fixture.db)
            self.assertEqual(result['status'], 'not_found')
            self.assertEqual(result['legacyCyclesWithoutSeeds'], 1)
            for spec in config['ticketSeedSchedules'].values():
                spec['version'] = 'future_seed_v2'
            connection.execute('UPDATE effectiveness_cycles SET config_json=?', (json.dumps(config),))
        result = lookup.lookup(seed, self.fixture.db)
        self.assertEqual(result['matches'], [])
        self.assertEqual(len(result['warnings']), 4)

    def test_cli_json_interactive_and_exit_codes(self):
        cycle = self.lock()
        seed = seeds.derive(cycle['methods']['web']['seedSchedule'], 1)
        base = [sys.executable, str(SCRIPT)]
        options = ['--db', str(self.fixture.db)]
        before = self.digest()
        found = subprocess.run([*base, seed, *options, '--json'], capture_output=True, text=True, encoding='utf-8', timeout=25)
        self.assertEqual(found.returncode, 0, found.stderr)
        self.assertTrue(json.loads(found.stdout)['matches'][0]['replay']['matchesStored'])
        missing = subprocess.run([*base, '0' * 64, *options, '--json'], capture_output=True, text=True, encoding='utf-8', timeout=25)
        self.assertEqual(missing.returncode, 1)
        self.assertEqual(json.loads(missing.stdout)['status'], 'not_found')
        invalid = subprocess.run([*base, 'bad', *options, '--json'], capture_output=True, text=True, encoding='utf-8', timeout=25)
        self.assertEqual(invalid.returncode, 2)
        self.assertFalse(json.loads(invalid.stderr)['ok'])
        interactive = subprocess.run([*base, *options], input='bad\n' + seed + '\n\n', capture_output=True, text=True, encoding='utf-8', timeout=25)
        self.assertEqual(interactive.returncode, 0, interactive.stderr)
        self.assertIn('KHỚP CHÍNH XÁC', interactive.stdout)
        self.assertIn('Lỗi:', interactive.stderr)
        self.assertEqual(before, self.digest())

    def test_multiple_owners_require_explicit_selection(self):
        runtime = self.fixture.root / 'runtime'
        accounts = runtime / 'lotto_web.db'
        ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        paths = []
        for account in ids:
            path = runtime / 'personal_tracking' / account / 'tracking.db'
            path.parent.mkdir(parents=True)
            with closing(sqlite3.connect(path)):
                pass
            paths.append(path.resolve())
        with closing(sqlite3.connect(accounts)) as connection, connection:
            connection.execute('CREATE TABLE personal_tracking_accounts(id TEXT, username TEXT)')
            connection.executemany('INSERT INTO personal_tracking_accounts VALUES(?,?)', [(ids[0], 'alice'), (ids[1], 'bob')])
        with self.assertRaisesRegex(ValueError, 'nhiều tài khoản'):
            lookup.select_database(runtime)
        self.assertEqual(lookup.select_database(runtime, owner='alice'), paths[0])
        self.assertEqual(lookup.select_database(runtime, owner='bob'), paths[1])
        self.assertEqual(lookup.select_database(runtime, database=paths[1]), paths[1])
        with self.assertRaises(ValueError):
            lookup.select_database(runtime, owner="alice' OR 1=1 --")
        with self.assertRaises(ValueError):
            lookup.select_database(runtime, owner='alice', database=paths[0])

    @unittest.skipUnless(sys.platform == 'win32', 'Windows batch entry point')
    def test_windows_entry_point_finds_a_working_python(self):
        result = subprocess.run(['cmd.exe', '/d', '/c', str(ROOT / 'scripts/tra_seed.bat'), '--help'],
                                cwd=ROOT, input='', capture_output=True, text=True, encoding='utf-8',
                                creationflags=0x08000000, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('tra_seed.py', result.stdout)
        self.assertIn('--owner', result.stdout)
