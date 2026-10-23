"""Real cycle transactions with disposable private ledgers and wallets."""
import json
import sqlite3
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest import mock

from ai import personal_tracking as billing, prediction_effectiveness as pe
from tests.test_prediction_effectiveness import PredictionEffectivenessTests


class PersonalPredictionBillingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = PredictionEffectivenessTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.account_db = self.fixture.root / 'accounts.db'
        with closing(billing.account_connection(self.account_db)) as connection:
            connection.executescript('CREATE TABLE users(username TEXT PRIMARY KEY,enabled INTEGER);'
                                     'CREATE TABLE stores(username TEXT PRIMARY KEY,store_json TEXT);'
                                     'CREATE TABLE account_audit(event_id TEXT,actor TEXT,target TEXT,action TEXT,details_json TEXT,created_at TEXT);')
            billing.schema(connection)
            for name in ('alice', 'bob'):
                connection.execute('INSERT INTO users VALUES(?,1)', (name,))
                connection.execute('INSERT INTO stores VALUES(?,?)', (name, json.dumps({'paypalBalance': 2000000, 'walletVersion': 0, 'diamondBalance': 50})))
                connection.execute('INSERT INTO personal_tracking_accounts VALUES(?,?)', (str(uuid.uuid4()), name))
        self.alice = self.scope('alice')
        self.bob = self.scope('bob')

    def scope(self, owner):
        with closing(billing.account_connection(self.account_db)) as connection:
            account_id = connection.execute('SELECT id FROM personal_tracking_accounts WHERE username=?', (owner,)).fetchone()[0]
        scope = billing.Scope(account_id, owner, self.account_db, self.fixture.root)
        scope.prepare()
        return scope

    def wallet(self, owner='alice'):
        with closing(billing.account_connection(self.account_db)) as connection:
            return billing._wallet(connection, owner)

    def charges(self):
        with closing(billing.account_connection(self.account_db)) as connection:
            return [dict(row) for row in connection.execute('SELECT * FROM prediction_charges ORDER BY rowid')]

    def cycle(self, scope, force=True):
        with scope.job():
            return pe.cycle(self.fixture.GAME, scope.database, force=force)

    def test_manual_and_automatic_cycles_private_and_charged_once(self):
        with self.alice.job():
            pe.configure(self.fixture.GAME, True, 3, 'alice', self.alice.database)
        first = self.cycle(self.alice, force=False)
        self.assertEqual(first['status'], 'locked')
        self.assertEqual(self.wallet()['paypalBalance'], 1880000)  # 3 x 4 x 10,000
        self.assertEqual(self.wallet('bob')['paypalBalance'], 2000000)
        self.assertEqual(self.cycle(self.alice)['status'], 'already_locked')
        self.assertEqual(len(self.charges()), 1)
        self.assertEqual(self.charges()[0]['status'], 'charged')
        own = pe.report(self.fixture.GAME, db_path=self.alice.database)
        self.assertEqual(pe.report(self.fixture.GAME, db_path=self.bob.database)['counts']['total'], 0)
        prediction_id = own['cycles'][0]['methods']['web']['predictionId']
        with self.assertRaises(ValueError):
            pe.ticket_page(self.fixture.GAME, prediction_id, db_path=self.bob.database)
        with self.assertRaises(ValueError):
            pe.export_cycle(self.fixture.GAME, first['cycleId'], self.bob.database)
        second = self.cycle(self.bob)
        self.assertNotEqual(first['cycleId'], second['cycleId'])
        self.assertEqual(len(self.charges()), 2)
        self.assertEqual(self.wallet()['diamondBalance'], 50)
        # A read/refresh/settings change is free, including disabling tracking.
        with self.alice.job():
            pe.configure(self.fixture.GAME, False, 2, 'alice', self.alice.database)
        pe.report(self.fixture.GAME, db_path=self.alice.database)
        self.assertEqual(self.wallet()['paypalBalance'], 1880000)
        self.assertEqual(self.cycle(self.alice, force=False)['status'], 'disabled')

    def test_insufficient_balance_blocks_before_generation(self):
        with closing(billing.account_connection(self.account_db)) as connection:
            connection.execute('UPDATE stores SET store_json=? WHERE username=?', ('{"paypalBalance":1}', 'alice'))
        with self.assertRaisesRegex(ValueError, 'Không đủ PayPal'):
            self.cycle(self.alice)
        self.fixture.web.assert_not_called()
        self.assertEqual(self.wallet()['paypalBalance'], 1)
        self.assertEqual(self.charges(), [])
        self.assertEqual(pe.report(self.fixture.GAME, db_path=self.alice.database)['counts']['total'], 0)

    def test_generation_failure_refunds_and_retry_can_succeed(self):
        with mock.patch.object(pe, '_production_web_prediction', side_effect=RuntimeError('generation failed')):
            with self.assertRaisesRegex(RuntimeError, 'generation failed'):
                self.cycle(self.alice)
        self.assertEqual(self.wallet()['paypalBalance'], 2000000)
        self.assertEqual(self.wallet()['walletVersion'], 2)
        self.assertEqual(self.charges()[0]['status'], 'refunded')
        self.assertEqual(self.cycle(self.alice)['status'], 'locked')
        self.assertEqual(self.wallet()['paypalBalance'], 1880000)
        self.assertEqual([row['status'] for row in self.charges()], ['refunded', 'charged'])

    def test_recovery_distinguishes_committed_receipt_from_interrupted_job(self):
        # Simulate process death after debit but before tracking commit.
        with mock.patch.object(billing, 'UNIT_PAYPAL', 12500):
            first = self.alice.reserve(self.fixture.GAME, '41', 12)
        with self.alice.job():
            pass
        self.assertEqual(self.wallet()['paypalBalance'], 2000000)
        self.assertEqual(self.charges()[0]['status'], 'refunded')
        # Simulate death after tracking commit, before account settlement.
        with mock.patch.object(billing, 'UNIT_PAYPAL', 12500):
            second = self.alice.reserve(self.fixture.GAME, '41', 12)
        with closing(sqlite3.connect(self.alice.database)) as tracking, tracking:
            tracking.execute('INSERT INTO paid_cycle_receipts VALUES(?,?,?)', (second, str(uuid.uuid4()), 12))
        with self.alice.job():
            pass
        with self.alice.job():
            pass
        self.assertEqual(self.wallet()['paypalBalance'], 1850000)  # Keep the reserved old fee.
        self.assertEqual(self.charges()[-1]['paypal_cost'], 150000)
        self.assertEqual([row['status'] for row in self.charges()], ['refunded', 'charged'])
        self.assertNotEqual(first, second)

    def test_concurrent_duplicate_cycle_only_debits_once(self):
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: self.cycle(self.alice), range(2)))
        self.assertEqual(sorted(row['status'] for row in results), ['already_locked', 'locked'])
        self.assertEqual(self.wallet()['paypalBalance'], 1880000)
        self.assertEqual(len(self.charges()), 1)

    def test_actual_combinations_and_all_keno_levels_priced(self):
        self.assertEqual(billing.quote('LOTO_5_35', 324632)['totalTickets'], 1298528)
        with self.assertRaises(ValueError):
            billing.quote('LOTO_5_35', 324633)
        keno = billing.quote('KENO', 324632)
        self.assertEqual(keno['totalTickets'], 9431296)
        self.assertEqual(keno['totalPayPal'], 94312960000)
        self.assertEqual(keno['ticketCountsByLevel']['1'], 80)
        self.assertEqual(keno['ticketCountsByLevel']['3'], 82160)
        with self.assertRaises(ValueError):
            billing.quote('KENO', 324633)
        # The old generic four-million-ticket billing guard must not reject
        # Keno's combined 40 portfolios. No large portfolios are allocated here.
        with closing(billing.account_connection(self.account_db)) as connection:
            connection.execute('UPDATE stores SET store_json=? WHERE username=?',
                               ('{"paypalBalance":100000000000,"walletVersion":0}', 'alice'))
        with self.alice.job():
            self.alice.reserve('KENO', '41', keno['totalTickets'])
            self.assertEqual(self.wallet()['paypalBalance'], 5687040000)
            self.assertEqual(self.charges()[0]['paypal_cost'], 94312960000)
        self.assertEqual(self.wallet()['paypalBalance'], 100000000000)
        self.assertEqual(self.charges()[0]['status'], 'refunded')
        self.assertEqual(billing.quote('LOTO_6_55', 1)['totalPayPal'], 40000)

    def test_keno_charges_all_40_portfolios_and_scores_after_stop_for_free(self):
        from tests.test_keno_effectiveness import KenoEffectivenessTests
        from ai import keno_effectiveness as ke
        fixture = KenoEffectivenessTests()
        fixture.setUp()
        try:
            with self.alice.job():
                pe.configure('KENO', True, 3, 'alice', self.alice.database)
                result = pe.cycle('KENO', self.alice.database, force=False)
            self.assertEqual(result['totalTickets'], 120)
            self.assertEqual(self.wallet()['paypalBalance'], 800000)
            self.assertEqual(len(self.charges()), 1)
            self.assertEqual(self.charges()[0]['ticket_count'], 120)
            with self.alice.job():
                pe.configure('KENO', False, 3, 'alice', self.alice.database)
            fixture.add_actual()
            with self.alice.job():
                scored = ke.score_cycles(self.alice.database)
                self.assertEqual(pe.cycle('KENO', self.alice.database, force=False)['status'], 'disabled')
            self.assertEqual(scored['scored'], [result['targetDrawId']])
            self.assertEqual(self.wallet()['paypalBalance'], 800000)
            self.assertEqual(len(self.charges()), 1)
        finally:
            fixture.doCleanups()

    def test_owner_validation_rename_delete_and_disabled_account(self):
        with self.assertRaises(ValueError):
            billing.Scope(self.alice.account_id, 'bob', self.account_db, self.fixture.root).prepare()
        with closing(billing.account_connection(self.account_db)) as connection:
            connection.execute('UPDATE users SET enabled=0 WHERE username=?', ('alice',))
        with self.assertRaises(ValueError):
            self.cycle(self.alice)
        self.assertEqual(self.charges(), [])
        with closing(billing.account_connection(self.account_db)) as connection:
            connection.execute('UPDATE users SET enabled=1,username=? WHERE username=?', ('renamed', 'alice'))
            connection.execute('UPDATE stores SET username=? WHERE username=?', ('renamed', 'alice'))
            connection.execute('UPDATE personal_tracking_accounts SET username=? WHERE username=?', ('renamed', 'alice'))
        renamed = self.scope('renamed')
        self.assertEqual(renamed.database, self.alice.database)
        self.cycle(renamed)
        self.assertEqual(self.wallet('renamed')['paypalBalance'], 1880000)

    def test_worker_charges_each_enabled_account_and_retries_without_duplicates(self):
        from ai import keno_effectiveness as ke
        for scope in (self.alice, self.bob):
            with scope.job():
                pe.configure(self.fixture.GAME, True, 2, scope.owner, scope.database)
        with mock.patch.object(billing.ledger, 'DEFAULT_DB_PATH', self.account_db), \
                mock.patch.object(billing.dp, 'RUNTIME_DIR', self.fixture.root), \
                mock.patch.object(ke, '_sync_source', return_value={}) as source, \
                mock.patch.object(ke.prize_contexts, 'refresh', return_value={}):
            billing.tick_all()
            billing.tick_all()
            source.assert_not_called()  # Keno is disabled and has no pending draw.
        self.assertEqual(self.wallet('alice')['paypalBalance'], 1920000)
        self.assertEqual(self.wallet('bob')['paypalBalance'], 1920000)
        self.assertEqual(len(self.charges()), 2)
        self.assertTrue(all(row['status'] == 'charged' for row in self.charges()))


if __name__ == '__main__':
    unittest.main()
