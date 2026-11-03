"""Different Bao levels in one future draw: immutable purchases and real fees."""
import json
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
from unittest import mock

from ai import prediction_effectiveness as pe, tracking_storage as storage, personal_tracking as billing
from tests.test_personal_prediction_billing import PersonalPredictionBillingTests as BillingFixture


def legacy_cycle_schema(database):
    """A real pre-upgrade table with live FK mappings, not a separate mock schema."""
    with closing(sqlite3.connect(database, isolation_level=None)) as connection:
        connection.executescript('''PRAGMA foreign_keys=OFF; BEGIN IMMEDIATE;
            CREATE TABLE effectiveness_cycles_old (
                cycle_id TEXT PRIMARY KEY, game_type TEXT NOT NULL, target_draw_id TEXT NOT NULL,
                cutoff_draw_id TEXT NOT NULL, created_at TEXT NOT NULL, deadline TEXT NOT NULL,
                data_hash TEXT NOT NULL, source_version_json TEXT NOT NULL, config_json TEXT NOT NULL,
                UNIQUE(game_type,target_draw_id));
            INSERT INTO effectiveness_cycles_old SELECT cycle_id,game_type,target_draw_id,cutoff_draw_id,
                created_at,deadline,data_hash,source_version_json,config_json FROM effectiveness_cycles;
            DROP TABLE effectiveness_cycles;
            ALTER TABLE effectiveness_cycles_old RENAME TO effectiveness_cycles;
            CREATE TRIGGER effectiveness_cycle_immutable BEFORE UPDATE ON effectiveness_cycles BEGIN
                SELECT RAISE(ABORT,'prospective cycle is immutable'); END;
            COMMIT; PRAGMA foreign_keys=ON;''')


class MultiBaoCycleTests(unittest.TestCase):
    setUp = BillingFixture.setUp
    scope = BillingFixture.scope
    wallet = BillingFixture.wallet
    charges = BillingFixture.charges

    def select(self, level, count=1, scope=None):
        scope = scope or self.alice
        with scope.job():
            return pe.configure(self.fixture.GAME, True, 3, scope.owner, scope.database,
                                play_mode='bao', bao_level=level, bao_count=count)['settings']

    def lock(self, force=True, scope=None, configuration_hash=None):
        scope = scope or self.alice
        with scope.job():
            configuration_hash = configuration_hash or pe.settings(self.fixture.GAME, scope.database)['settings']['configurationHash']
            return pe.cycle(self.fixture.GAME, scope.database, force=force, configuration_hash=configuration_hash)

    def test_distinct_bao_paid_once_and_quantity_change_cannot_reroll(self):
        self.select(6, 2)
        first = self.lock()
        self.select(7)
        second = self.lock()
        self.assertEqual(first['targetDrawId'], second['targetDrawId'])
        self.assertNotEqual(first['cycleId'], second['cycleId'])
        self.assertEqual(self.wallet()['paypalBalance'], 680000)  # (2*6 + 1*21) * 4 * 10,000.
        self.assertEqual([row['status'] for row in self.charges()], ['charged', 'charged'])
        self.select(6, 3)
        with mock.patch.object(pe, '_production_web_prediction', side_effect=AssertionError('must reuse')):
            repeated = self.lock()
        self.assertEqual(repeated['cycleId'], first['cycleId'])
        self.assertEqual(repeated['baoCount'], 2)
        self.assertEqual(repeated['ticketCount'], 12)
        self.assertEqual(repeated['status'], 'already_locked')
        self.assertEqual(self.wallet()['paypalBalance'], 680000)
        self.assertEqual(len(self.charges()), 2)
        report = pe.report(self.fixture.GAME, db_path=self.alice.database)
        self.assertEqual({row['selectionKey'] for row in report['cycles']}, {'bao:6', 'bao:7'})
        self.assertEqual(report['counts']['total'], 2)
        self.assertEqual(pe.report(self.fixture.GAME, db_path=self.bob.database)['counts']['total'], 0)
        for row in report['cycles']:
            exported = pe.export_cycle(self.fixture.GAME, row['cycleId'], self.alice.database)
            self.assertEqual(exported['config']['baoLevel'], row['config']['baoLevel'])
            page = pe.ticket_page(self.fixture.GAME, row['methods']['web']['predictionId'], db_path=self.alice.database)
            self.assertEqual(len(page['baoParents']), row['config']['baoCount'])
            self.assertTrue(all(len(parent['main']) == row['config']['baoLevel'] for parent in page['baoParents']))

    def test_automatic_and_concurrent_retries_only_charge_new_level_once(self):
        self.select(6)
        self.lock(force=False)
        self.select(7)
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: self.lock(force=False), range(2)))
        self.assertEqual(sorted(row['status'] for row in results), ['already_locked', 'locked'])
        self.assertEqual(len(self.charges()), 2)
        self.assertEqual(self.wallet()['paypalBalance'], 920000)

    def test_new_level_after_deadline_is_rejected_without_charge(self):
        self.select(6)
        self.lock()
        self.select(7)
        snapshot = pe._snapshot(self.fixture.GAME)
        self.fixture.now.return_value = snapshot['deadline'] + timedelta(seconds=1)
        with self.assertRaises(ValueError):
            self.lock()
        self.assertEqual(len(self.charges()), 1)
        self.assertEqual(self.wallet()['paypalBalance'], 1760000)

    def test_failed_new_level_refunds_without_changing_first_purchase(self):
        self.select(6)
        first = self.lock()
        self.select(7)
        with mock.patch.object(pe, '_production_web_prediction', side_effect=RuntimeError('fixture failure')):
            with self.assertRaisesRegex(RuntimeError, 'fixture failure'):
                self.lock()
        self.assertEqual(self.wallet()['paypalBalance'], 1760000)
        self.assertEqual([row['status'] for row in self.charges()], ['charged', 'refunded'])
        report = pe.report(self.fixture.GAME, db_path=self.alice.database)
        self.assertEqual([row['cycleId'] for row in report['cycles']], [first['cycleId']])
        self.assertEqual(self.lock()['status'], 'locked')
        self.assertEqual(self.wallet()['paypalBalance'], 920000)

    def test_stale_confirmation_of_new_level_does_not_charge(self):
        old = self.select(6)
        self.lock()
        self.select(7)
        with self.assertRaisesRegex(ValueError, 'Cấu hình đã thay đổi'):
            self.lock(configuration_hash=old['configurationHash'])
        self.assertEqual(len(self.charges()), 1)

    def test_all_batches_score_once_and_statistics_count_one_independent_draw(self):
        self.select(6, 2)
        self.lock()
        self.select(7)
        self.lock()
        balance = self.wallet()['paypalBalance']
        self.fixture._actual()
        self.assertEqual(len(pe.score_cycles(self.fixture.GAME, self.alice.database)['scored']), 2)
        self.assertEqual(pe.score_cycles(self.fixture.GAME, self.alice.database)['scored'], [])
        report = pe.report(self.fixture.GAME, db_path=self.alice.database)
        self.assertEqual(report['counts']['scored'], 2)
        for method in report['methods']:
            self.assertEqual(method['sampleCount'], 1)
            self.assertEqual(sum(method['hitHistogram'].values()), 33)
            self.assertEqual(method['prizeStatistics']['ticketCount'], 33)
        self.assertEqual(self.wallet()['paypalBalance'], balance)
        self.assertEqual(len(self.charges()), 2)

    def test_legacy_upgrade_preserves_payload_receipt_fk_and_immutable_trigger(self):
        self.select(6)
        first = self.lock()
        with closing(pe._connect(self.alice.database)) as connection:
            runs = [tuple(row) for row in connection.execute('SELECT * FROM prediction_runs ORDER BY prediction_id')]
            cycles = [tuple(row)[:9] for row in connection.execute('SELECT * FROM effectiveness_cycles')]
            receipts = [tuple(row) for row in connection.execute('SELECT * FROM paid_cycle_receipts')]
        legacy_cycle_schema(self.alice.database)
        with closing(pe._connect(self.alice.database)) as connection:
            self.assertEqual(connection.execute('PRAGMA foreign_keys').fetchone()[0], 1)
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual([tuple(row) for row in connection.execute('SELECT * FROM prediction_runs ORDER BY prediction_id')], runs)
            self.assertEqual([tuple(row)[:9] for row in connection.execute('SELECT * FROM effectiveness_cycles')], cycles)
            self.assertEqual([tuple(row) for row in connection.execute('SELECT * FROM paid_cycle_receipts')], receipts)
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'immutable'):
                connection.execute("UPDATE effectiveness_cycles SET selection_key='bao:7'")
        self.assertEqual(self.lock()['cycleId'], first['cycleId'])
        self.select(7)
        self.assertEqual(self.lock()['status'], 'locked')
        self.assertEqual(len(self.charges()), 2)

    def test_legacy_storage_copy_derives_selection_key_without_touching_source(self):
        # Use the non-personal system fixture; it has no private account data.
        pe.configure(self.fixture.GAME, True, 3, 'fixture', self.fixture.db, play_mode='bao', bao_level=6, bao_count=1)
        locked = pe.cycle(self.fixture.GAME, self.fixture.db)
        legacy_cycle_schema(self.fixture.db)
        destination = self.fixture.root / 'copied.db'
        with mock.patch.object(storage.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 10**15})()):
            copied = storage.migrate_tracking(self.fixture.db, destination)
        self.assertEqual(copied['status'], 'migrated')
        with closing(pe._connect(destination)) as connection:
            row = connection.execute('SELECT * FROM effectiveness_cycles').fetchone()
            self.assertEqual(row['cycle_id'], locked['cycleId'])
            self.assertEqual(row['selection_key'], 'bao:6')
        with closing(sqlite3.connect(self.fixture.db)) as connection:
            self.assertNotIn('selection_key', {row[1] for row in connection.execute('PRAGMA table_info(effectiveness_cycles)')})

    def test_mega_and_power_18_allow_separate_bao_and_charge_exact_combinations(self):
        with closing(billing.account_connection(self.account_db)) as connection:
            connection.execute("UPDATE stores SET store_json=json_set(store_json,'$.paypalBalance',1000000000) WHERE username='alice'")
        balance = 1000000000
        for game, level, date, special, equivalent in (
                ('LOTO_6_45', 8, '04/01/2030', None, 28),
                ('LOTO_6_55', 18, '05/01/2030', 55, 18564)):
            with self.subTest(game=game):
                self.fixture.GAME = game
                for row in self.fixture.draws:
                    row.update(date=date, time='18:00', main=[1, 2, 3, 4, 5, 6], special=special)
                self.fixture._write()
                self.select(7)
                first = self.lock()
                self.select(level)
                second = self.lock()
                self.assertEqual(second['targetDrawId'], first['targetDrawId'])
                self.assertEqual(second['ticketCount'], equivalent)
                self.assertEqual(self.lock()['status'], 'already_locked')
                balance -= (7 + equivalent) * 4 * 10000
                self.assertEqual(self.wallet()['paypalBalance'], balance)
                self.assertEqual(pe.report(game, db_path=self.alice.database)['counts']['total'], 2)
