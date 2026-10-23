"""Reproduce stale-result locking failures without production data or charges."""
import argparse
import json
import unittest
from contextlib import closing
from datetime import timedelta
from unittest import mock

from ai import personal_tracking as billing, prediction_effectiveness as pe
from backend import prospective_live_sync as sync
from tests.test_personal_prediction_billing import PersonalPredictionBillingTests


class ProspectiveLiveSyncTests(unittest.TestCase):
    def setUp(self):
        self.parent = PersonalPredictionBillingTests()
        self.parent.setUp()
        self.addCleanup(self.parent.doCleanups)
        self.f = self.parent.fixture
        self.scope = self.parent.alice
        self.now = self.f.now
        self.now.return_value = self.f.clock + timedelta(hours=8)  # 22:00 VN, CSV still 13:00.
        for name, value in [('get_canonical_csv_write_path', self.f.csv),
                            ('get_canonical_meta_read_path', self.f.root/'canonical.meta.json'),
                            ('get_canonical_meta_write_path', self.f.root/'canonical.meta.json')]:
            patch = mock.patch.object(sync.live.dp, name, return_value=value)
            patch.start(); self.addCleanup(patch.stop)
        for target, name, value in [(billing.dp, 'RUNTIME_DIR', self.f.root),
                                    (billing.ledger, 'DEFAULT_DB_PATH', self.parent.account_db)]:
            patch = mock.patch.object(target, name, value)
            patch.start(); self.addCleanup(patch.stop)
        self.page = self.enterContext(mock.patch.object(sync, '_page', return_value=[self.result()]))
        self.enterContext(mock.patch.object(sync.live, 'create_session'))

    def result(self, identity='41'):
        return {'key': self.f.GAME, 'ky': identity, 'date': '06/01/2030', 'time': '21:00',
                'main': [1, 2, 3, 4, 5], 'special': 2, 'sourceUrl': 'https://source.invalid/fixture',
                'specialPrize': 6000000000}

    def execute(self):
        return billing.execute(argparse.Namespace(command='cycle', game=self.f.GAME,
                               personal_id=self.scope.account_id, owner='alice', db_path=None))

    def test_manual_lock_refreshes_missing_result_and_charges_only_future_cycle(self):
        with self.assertRaises(ValueError):
            pe._guard(pe._snapshot(self.f.GAME))
        before = sync.live.load_csv_rows(self.f.csv, type_key=self.f.GAME)
        with mock.patch.object(sync.live, 'retrain_gen_local_models', side_effect=AssertionError('training')), \
                mock.patch.object(sync.live, 'refresh_scoring_csv_exports', side_effect=AssertionError('export')):
            result = self.execute()
        self.assertEqual(result['status'], 'locked')
        self.assertEqual(result['targetDrawId'], '42')
        after = sync.live.load_csv_rows(self.f.csv, type_key=self.f.GAME)
        self.assertEqual(set(after)-set(before), {'41'})
        for identity in before:
            for field in ('Main', 'Special', 'Ngay', 'Time'):
                self.assertEqual(after[identity][field], before[identity][field])
        self.assertEqual(result['billing']['balance'], 1880000)
        self.assertEqual(self.parent.charges()[0]['target_draw_id'], '42')
        self.assertEqual(self.execute()['status'], 'already_locked')
        self.assertEqual(len(self.parent.charges()), 1)
        self.page.assert_called_once()

    def test_worker_refreshes_before_scoring_and_locking(self):
        pe.configure(self.f.GAME, True, 3, 'alice', self.scope.database)
        with self.scope.job():
            result = pe.tick(self.scope.database, sync_sources=True)
        self.assertEqual(result['results'][0]['cycle']['targetDrawId'], '42')
        self.assertEqual(self.parent.wallet()['paypalBalance'], 1880000)
        with closing(pe._connect(self.scope.database)) as connection:
            error = connection.execute('SELECT last_error FROM effectiveness_settings WHERE game_type=?', (self.f.GAME,)).fetchone()[0]
        self.assertEqual(error, '')

    def test_missing_or_offline_source_never_creates_expired_tickets_or_debits(self):
        self.page.return_value = []
        original = self.f.csv.read_bytes()
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.parent.charges(), [])
        self.assertEqual(self.parent.wallet()['paypalBalance'], 2000000)
        self.assertEqual(self.f.csv.read_bytes(), original)
        self.page.assert_called_once()
        self.execute_failure()
        self.page.assert_called_once()  # Shared 55-second retry throttle.

    def execute_failure(self):
        with self.assertRaises(ValueError):
            self.execute()

    def test_conflict_wrong_game_gap_and_future_result_preserve_canonical(self):
        original = self.f.csv.read_bytes()
        bad_cases = [[self.result('42')], [{**self.result(), 'key': 'LOTO_6_45'}],
                     [{**self.result(), 'date': '07/01/2030'}],
                     [{**self.result('40'), 'main': [1, 2, 3, 4, 5]}, self.result()]]
        for index, results in enumerate(bad_cases):
            self.page.return_value = results
            result = sync.refresh(self.f.GAME, now=self.now.return_value+timedelta(seconds=60*index))
            self.assertEqual(result['status'], 'error', result)
            self.assertEqual(self.f.csv.read_bytes(), original)

    def test_source_failure_retries_and_preserves_last_success(self):
        self.page.side_effect = TimeoutError('fixture offline')
        first = sync.refresh(self.f.GAME, now=self.now.return_value)
        self.assertEqual(first['status'], 'error')
        self.page.side_effect = None
        second = sync.refresh(self.f.GAME, now=self.now.return_value+timedelta(seconds=60))
        self.assertEqual(second['latestKy'], '41')
        self.assertEqual(second['error'], '')
        self.assertEqual(self.page.call_count, 2)

    def test_current_canonical_does_not_request_or_rewrite_source(self):
        self.now.return_value = self.f.clock
        original = self.f.csv.read_bytes()
        result = sync.refresh(self.f.GAME, now=self.now.return_value)
        self.assertEqual(result['status'], 'up_to_date')
        self.assertEqual(self.f.csv.read_bytes(), original)
        self.page.assert_not_called()


if __name__ == '__main__':
    unittest.main()
