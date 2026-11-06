"""Interest accounting against disposable SQLite ledgers and a frozen clock."""
import json
import sqlite3
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from ai import account_card as cards, card_interest as interest
from tests.test_prize_web import ROOT

SETTINGS = {'enabled': True, 'version': interest.VERSION, 'method': 'midnight_balance',
            'dailyDenominator': 4000, 'timeZone': 'Asia/Ho_Chi_Minh'}
ALICE, BOB = '123456789012', '234567890123'
START = '2026-11-04T12:00:00.123456789+07:00'


def midnight(day):
    return day + 'T00:00:00+07:00'


class CardInterestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='interest-', dir=ROOT/'runtime')
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name)/'accounts.db'
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript('''
                CREATE TABLE users(username TEXT PRIMARY KEY,enabled INTEGER NOT NULL);
                CREATE TABLE account_identities(account_id TEXT PRIMARY KEY,username TEXT UNIQUE,deleted_at TEXT DEFAULT '');
                CREATE TABLE stores(username TEXT PRIMARY KEY,store_json TEXT NOT NULL);
                CREATE TABLE account_audit(event_id TEXT PRIMARY KEY,actor TEXT,target TEXT,action TEXT,details_json TEXT,created_at TEXT);
                CREATE TABLE account_activity_links(event_id TEXT PRIMARY KEY,target_account_id TEXT);
                CREATE TRIGGER audit_link AFTER INSERT ON account_audit BEGIN INSERT INTO account_activity_links
                  VALUES(NEW.event_id,(SELECT account_id FROM account_identities WHERE username=NEW.target)); END;
                INSERT INTO users VALUES('alice',1),('bob',1);
                INSERT INTO account_identities VALUES('123456789012','alice',''),('234567890123','bob','');
                INSERT INTO stores VALUES('alice','{"paypalBalance":500000,"walletVersion":7}');
                INSERT INTO stores VALUES('bob','{"paypalBalance":600000,"walletVersion":9}');
            ''')
            cards.schema(db)

    def transaction(self, amount, at='2026-11-01T10:00:00Z', account=ALICE):
        event = uuid.uuid4().hex
        with closing(sqlite3.connect(self.db, isolation_level=None, timeout=30)) as db:
            db.execute('BEGIN IMMEDIATE')
            if amount >= 0:
                with patch('ai.account_card.ledger.now_iso', return_value=at):
                    cards.credit(db, account, 'PayPal', amount, event, 'topup', event, {})
            else:
                balance = db.execute('SELECT balance FROM account_cards WHERE account_id=?', (account,)).fetchone()[0] + amount
                self.assertGreaterEqual(balance, 0)
                db.execute('UPDATE account_cards SET balance=?,version=version+1,updated_at=? WHERE account_id=?', (balance, at, account))
                db.execute('INSERT INTO card_transactions VALUES(?,?,?,?,?,?,?,?,?,?)',
                           (event, account, 'PayPal', 'withdraw', amount, balance, event, '{}', at, event))
            db.commit()

    def run_at(self, at, apply=True):
        before = self.wallets()
        result = interest.settle(self.db, apply=apply, now_ns=interest.timestamp_ns(at), settings=SETTINGS)
        self.assertEqual(self.wallets(), before)
        return result

    def wallets(self):
        with closing(sqlite3.connect(self.db)) as db:
            return db.execute('SELECT * FROM stores ORDER BY username').fetchall()

    def balance(self, account=ALICE):
        with closing(sqlite3.connect(self.db)) as db:
            return db.execute('SELECT balance FROM account_cards WHERE account_id=?', (account,)).fetchone()[0]

    def rows(self, table):
        with closing(sqlite3.connect(self.db)) as db:
            return db.execute('SELECT * FROM '+table+' ORDER BY 1,2').fetchall()

    def snapshot(self):
        with closing(sqlite3.connect(self.db)) as db:
            names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            return {name: db.execute('SELECT * FROM '+name+' ORDER BY 1').fetchall() for name in names}

    def test_activation_preview_no_backpay_and_read_only_repeated_settlement(self):
        self.transaction(1000000)
        before = self.snapshot()
        self.assertEqual(self.run_at(START, apply=False)['status'], 'activation_required')
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(self.run_at(START)['activated'])
        self.assertEqual((self.balance(), len(self.rows('card_interest_days'))), (1000000, 0))
        before = self.snapshot()
        preview = self.run_at(midnight('2026-11-05'), apply=False)
        self.assertEqual(preview['creditedPayPal'], 250)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.run_at(midnight('2026-11-05'))['creditedPayPal'], 250)
        self.assertEqual(self.balance(), 1000250)
        before = self.snapshot()
        self.assertEqual(self.run_at(midnight('2026-11-05'))['credited'], 0)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.rows('card_interest_days')[0][1], '2026-11-04')
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute("SELECT action FROM account_audit").fetchall(), [('card_interest',)])
            self.assertEqual(db.execute('SELECT target_account_id FROM account_activity_links').fetchone()[0], ALICE)
            for sql in ['UPDATE card_interest_days SET interest_amount=0', 'DELETE FROM card_interest_days', 'UPDATE card_interest_policy SET denominator=1']:
                with self.assertRaises(sqlite3.IntegrityError): db.execute(sql)

    def test_exact_midnight_cutoff_and_full_closing_balance(self):
        self.transaction(1000000)
        self.run_at(START)
        self.transaction(1000000, '2026-11-04T23:59:59.999999999+07:00')
        self.transaction(-500000, midnight('2026-11-05'))
        result = self.run_at('2026-11-05T00:00:00.000000001+07:00')
        self.assertEqual(result['errors'], [])
        self.assertEqual((result['creditedPayPal'], self.balance()), (500, 1500500))
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT closing_balance FROM card_interest_days').fetchone()[0], '2000000')
        self.assertEqual(self.run_at(midnight('2026-11-06'))['creditedPayPal'], 375)
        self.assertEqual(self.balance(), 1500875)

    def test_offline_catchup_compounds_and_limits_each_batch_to_31_days(self):
        self.transaction(4000000)
        self.run_at(START)
        end = (date(2026, 11, 4) + timedelta(days=40)).isoformat()
        first = self.run_at(midnight(end)); second = self.run_at(midnight(end))
        self.assertEqual((first['processedDays'], second['processedDays']), (31, 9))
        expected, carry = 4000000, 0
        for _ in range(40):
            amount, carry = divmod(expected + carry, 4000)
            expected += amount
        self.assertEqual(self.balance(), expected)
        self.assertEqual(len(self.rows('card_interest_days')), 40)
        self.assertEqual(self.run_at(midnight(end))['credited'], 0)

    def test_fractional_interest_is_carried_and_zero_days_do_not_create_fake_cash(self):
        self.transaction(1000)
        self.run_at(START)
        for day in ['2026-11-05', '2026-11-06', '2026-11-07']:
            self.assertEqual(self.run_at(midnight(day))['creditedPayPal'], 0)
        self.assertEqual(len(self.rows('card_transactions')), 1)
        self.assertEqual(self.run_at(midnight('2026-11-08'))['creditedPayPal'], 1)
        self.assertEqual(self.balance(), 1001)
        self.assertEqual(len(self.rows('card_interest_days')), 4)

    def test_new_card_catches_up_and_new_card_in_activation_second_is_not_lost(self):
        self.run_at(START)
        self.transaction(400000, '2026-11-04T12:00:00+07:00', account=BOB)
        result = self.run_at(midnight('2026-11-06'))
        self.assertEqual(result['errors'], [])
        self.assertEqual((result['processedDays'], self.balance(BOB)), (2, 400200))

    def test_parallel_workers_credit_once(self):
        self.transaction(1000000)
        self.run_at(START)
        with ThreadPoolExecutor(max_workers=4) as pool:
            reports = list(pool.map(lambda _: interest.settle(self.db, apply=True, now_ns=interest.timestamp_ns(midnight('2026-11-05')), settings=SETTINGS), range(4)))
        self.assertTrue(all(not r['errors'] for r in reports), reports)
        self.assertEqual(sum(r['creditedPayPal'] for r in reports), 250)
        self.assertEqual((self.balance(), len(self.rows('card_interest_days'))), (1000250, 1))

    def test_concurrent_new_credit_and_interest_preserve_both(self):
        self.transaction(1000000)
        self.run_at(START)
        with ThreadPoolExecutor(max_workers=2) as pool:
            payout = pool.submit(self.run_at, '2026-11-05T00:00:01+07:00')
            incoming = pool.submit(self.transaction, 100000, '2026-11-05T00:00:00.500000000+07:00')
            incoming.result()
            result = payout.result()
        self.assertEqual((result['errors'], result['creditedPayPal']), ([], 250))
        self.assertEqual(self.balance(), 1100250)
        self.assertEqual(self.run_at(midnight('2026-11-06'))['creditedPayPal'], 275)

    def test_live_clock_refreshes_after_waiting_for_account_snapshot(self):
        self.transaction(1000000)
        self.run_at(START)
        self.transaction(4000, '2026-11-05T00:00:00.500000000+07:00')
        clocks=[interest.timestamp_ns(midnight('2026-11-05')),interest.timestamp_ns('2026-11-05T00:00:01+07:00')]
        with patch('ai.card_interest.time.time_ns',side_effect=clocks):
            result=interest.settle(self.db,apply=True,settings=SETTINGS)
        self.assertEqual((result['errors'],result['creditedPayPal']),([],250))
        self.assertEqual(self.balance(),1004250)

    def test_audit_failure_rolls_back_balance_receipt_checkpoint_and_retry(self):
        self.transaction(1000000)
        self.run_at(START)
        before = self.snapshot()
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("CREATE TRIGGER fail_interest BEFORE INSERT ON account_audit WHEN NEW.action='card_interest' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        self.assertEqual(len(self.run_at(midnight('2026-11-05'))['errors']), 1)
        self.assertEqual(self.snapshot(), before)
        with closing(sqlite3.connect(self.db)) as db: db.execute('DROP TRIGGER fail_interest')
        self.assertEqual(self.run_at(midnight('2026-11-05'))['creditedPayPal'], 250)

    def test_limit_defers_without_losing_receipt_then_retry_after_withdrawal(self):
        self.transaction(cards.MAX_SAFE)
        self.run_at(START)
        before = self.snapshot()
        self.assertEqual(len(self.run_at(midnight('2026-11-05'))['errors']), 1)
        self.assertEqual(self.snapshot(), before)
        self.transaction(-10000000000000, '2026-11-05T09:00:00+07:00')
        result = self.run_at('2026-11-05T10:00:00+07:00')
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['creditedPayPal'], cards.MAX_SAFE // 4000)
        self.assertEqual(self.balance(), cards.MAX_SAFE - 10000000000000 + cards.MAX_SAFE // 4000)

    def test_future_clock_or_unlogged_balance_change_defers(self):
        self.transaction(1000000)
        self.run_at(START)
        self.transaction(4000, '2026-11-05T02:00:00+07:00')
        before = self.snapshot()
        self.assertEqual(len(self.run_at(midnight('2026-11-05'))['errors']), 1)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.run_at('2026-11-05T03:00:00+07:00')['creditedPayPal'], 250)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE account_cards SET balance=balance+1 WHERE account_id=?', (ALICE,))
        before = self.snapshot()
        self.assertEqual(len(self.run_at(midnight('2026-11-06'))['errors']), 1)
        self.assertEqual(self.snapshot(), before)

    def test_identity_rename_disabled_owner_and_retired_id(self):
        self.transaction(1000000)
        self.run_at(START)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE users SET username='renamed',enabled=0 WHERE username='alice'")
            db.execute("UPDATE account_identities SET username='renamed' WHERE username='alice'")
        self.assertEqual(self.run_at(midnight('2026-11-05'))['creditedPayPal'], 250)
        self.assertEqual(self.rows('account_audit')[0][2], 'renamed')
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE account_identities SET deleted_at='retired',username=NULL WHERE account_id=?", (ALICE,))
            db.execute("INSERT INTO users VALUES('alice',1)")
        before = self.snapshot()
        self.assertEqual(self.run_at(midnight('2026-11-06'))['credited'], 0)
        self.assertEqual(self.snapshot(), before)

    def test_disabled_or_invalid_policy_cannot_write_or_create_database(self):
        before = self.snapshot()
        self.assertEqual(interest.settle(self.db, apply=True, settings={'enabled': False})['status'], 'disabled')
        with self.assertRaises(ValueError): interest.settle(self.db, apply=True, settings={**SETTINGS, 'dailyDenominator': 1})
        missing = Path(self.temp.name)/'missing.db'
        with self.assertRaises(ValueError): interest.settle(missing, apply=True, settings=SETTINGS)
        self.assertFalse(missing.exists())
        self.assertEqual(self.snapshot(), before)
