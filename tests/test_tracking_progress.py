import hashlib
import json
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from ai import tracking_progress as progress
from tests.test_effectiveness_web import EffectivenessWebTests as Bridge


class TrackingProgressTests(unittest.TestCase):
    def test_real_private_cycles_emit_creation_and_scoring(self):
        from tests.test_prediction_effectiveness import PredictionEffectivenessTests
        from tests.test_keno_effectiveness import KenoEffectivenessTests
        from ai import prediction_effectiveness as pe, keno_effectiveness as ke
        original = progress.Session.start
        observed = []

        def start(session, phase, total=1, tickets=0):
            observed.append((session.game, phase, total, tickets))
            return original(session, phase, total, tickets)

        for fixture, game in [(PredictionEffectivenessTests(), 'LOTO_5_35'), (KenoEffectivenessTests(), 'KENO')]:
            fixture.setUp()
            try:
                with mock.patch.object(progress.Session, 'start', autospec=True, side_effect=start):
                    if game == 'KENO':
                        ke.cycle(fixture.db)
                        fixture.add_actual()
                        ke.score_cycles(fixture.db)
                    else:
                        pe.cycle(game, fixture.db)
                        fixture._actual()
                        pe.score_cycles(game, fixture.db)
                phases = [row[1] for row in observed if row[0] == game]
                self.assertEqual(phases, ['creating', 'scoring'])
                self.assertTrue(all(row[2] > 0 and row[3] > 0 for row in observed if row[0] == game))
                path = fixture.db.parent / f'effectiveness_progress_{game.lower()}.json'
                self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['phase'], 'idle')
            finally:
                fixture.doCleanups()

    def test_failure_before_work_is_visible_without_creating_database(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'fixture.db'

            @progress.track
            def task(game, db_path=None):
                raise ValueError('missing canonical fixture')

            with self.assertRaises(ValueError):
                task('KENO', db)
            value = json.loads((Path(folder) / 'effectiveness_progress_keno.json').read_text(encoding='utf-8'))
            self.assertEqual(value['phase'], 'idle')
            self.assertIn('missing canonical', value['error'])
            self.assertFalse(db.exists())

    def test_sidecar_stage_units_heartbeat_errors_and_no_database_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'fixture.db'
            with closing(sqlite3.connect(db)) as connection:
                connection.execute('CREATE TABLE history(value TEXT)')
                connection.execute("INSERT INTO history VALUES('immutable')")
                connection.commit()
            before = hashlib.sha256(db.read_bytes()).hexdigest()

            @progress.track
            def task(game, db_path=None, fail=False):
                progress.start('creating', 8, 40000)
                progress.advance(3)
                row = json.loads((Path(folder) / 'effectiveness_progress_loto_6_45.json').read_text(encoding='utf-8'))
                self.assertEqual(row['phase'], 'creating')
                self.assertEqual(row['completedUnits'], 3)
                self.assertGreater(row['etaSeconds'], 0)
                if not fail:
                    deadline = time.monotonic() + 4
                    while json.loads((Path(folder) / 'effectiveness_progress_loto_6_45.json').read_text(encoding='utf-8'))['updatedAtMs'] <= row['updatedAtMs']:
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(.04)
                if fail:
                    raise ValueError('fixture failure')
                return {'ok': True}

            task('LOTO_6_45', db)
            path = Path(folder) / 'effectiveness_progress_loto_6_45.json'
            self.assertEqual(json.loads(path.read_text())['phase'], 'idle')
            with self.assertRaisesRegex(ValueError, 'fixture failure'):
                task('LOTO_6_45', db, True)
            self.assertEqual(json.loads(path.read_text())['error'], 'fixture failure')
            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), before)
            self.assertFalse(list(Path(folder).glob('*.tmp')))


class TrackingProgressHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Bridge.setUpClass()

    @classmethod
    def tearDownClass(cls):
        Bridge.tearDownClass()

    def test_authenticated_fast_read_busy_database_stale_and_invalid_file(self):
        server = Bridge
        url = '/api/ml/effectiveness-progress?type=KENO'
        self.assertEqual(server.request(url)[0], 401)
        self.assertEqual(server.request(url, cookie=server.member)[1]['progress']['phase'], 'idle')
        self.assertEqual(server.request('/api/ml/effectiveness-progress?type=INVALID', cookie=server.member)[0], 400)
        self.assertEqual(server.request(url, {}, cookie=server.member)[0], 405)
        path = server.work / 'runtime/effectiveness_progress_keno.json'
        value = {'version': 1, 'type': 'KENO', 'phase': 'scoring', 'updatedAtMs': int(time.time() * 1000), 'etaSeconds': 90, 'error': ''}
        path.write_text(json.dumps(value), encoding='utf-8')
        (server.work / 'runtime/tracking-storage.json').write_text('{"version":1,"mode":"dedicated"}', encoding='utf-8')
        lock = sqlite3.connect(server.work / 'runtime/tracking_ledger.db')
        lock.execute('CREATE TABLE fixture(value)')
        lock.execute('BEGIN IMMEDIATE')
        try:
            started = time.monotonic()
            status, body, headers = server.request(url, cookie=server.member)
            self.assertLess(time.monotonic() - started, 2)
            self.assertEqual(status, 200)
            self.assertEqual(body['progress']['phase'], 'scoring')
            self.assertEqual(headers['Cache-Control'], 'no-store')
        finally:
            lock.rollback()
            lock.close()
        value['updatedAtMs'] -= 30000
        path.write_text(json.dumps(value), encoding='utf-8')
        body = server.request(url, cookie=server.member)[1]
        self.assertEqual(body['progress']['phase'], 'idle')
        self.assertIn('gián đoạn', body['progress']['error'])
        for text in ('invalid JSON', json.dumps({**value, 'type': 'LOTO_5_35'}), 'x' * 9000):
            path.write_text(text, encoding='utf-8')
            self.assertTrue(server.request(url, cookie=server.member)[1]['progress']['error'])
