"""Internal card routing and conservation of historical reward transfers."""
import json
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

from ai import account_card as cards
from tests.test_prediction_rewards import PredictionRewardTests


class AccountCardTests(unittest.TestCase):
    def setUp(self):
        self.fixture=PredictionRewardTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.scope=self.fixture.scope;self.account=self.fixture.account;self.policy=cards.policy
        with closing(sqlite3.connect(self.account)) as db,db:
            db.executescript('''
                CREATE TABLE account_identities(account_id TEXT PRIMARY KEY,username TEXT UNIQUE,deleted_at TEXT DEFAULT '');
                INSERT INTO account_identities VALUES('123456789012','alice','');
                INSERT INTO account_identities VALUES('234567890123','bob','');
                CREATE TABLE account_activity_links(event_id TEXT PRIMARY KEY,target_account_id TEXT);
                CREATE TRIGGER audit_link AFTER INSERT ON account_audit BEGIN
                  INSERT INTO account_activity_links VALUES(NEW.event_id,(SELECT account_id FROM account_identities WHERE username=NEW.target)); END;
            ''')

    def card(self):
        with closing(sqlite3.connect(self.account)) as db:
            row=db.execute("SELECT balance,version FROM account_cards WHERE account_id='123456789012'").fetchone()
            return row or (0,0)

    def test_new_rewards_go_to_card_wallet_unchanged_and_once(self):
        self.policy.return_value={'destination':'card','currency':'PayPal'}
        self.fixture.cycle()
        before=self.fixture.money()
        result=self.fixture.settle(apply=True)
        self.assertEqual(result['creditedPayPal'],50000000)
        self.assertEqual(self.card(),(50000000,1))
        self.assertEqual(self.fixture.money(),before)
        self.assertEqual(self.fixture.settle(apply=True)['credited'],0)
        with closing(sqlite3.connect(self.account)) as db:
            self.assertEqual(db.execute('SELECT destination,currency FROM prediction_payout_routes').fetchone(),('card','PayPal'))
            self.assertEqual(db.execute('SELECT action FROM account_audit').fetchall(),[('prediction_card_reward',)])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM card_transactions').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT target_account_id FROM account_activity_links').fetchone()[0],'123456789012')

    def test_move_old_rewards_conserves_money_and_preserves_receipts(self):
        for _ in range(2):self.fixture.cycle()
        self.fixture.settle(apply=True)
        with closing(sqlite3.connect(self.account)) as db:
            receipts=db.execute('SELECT * FROM prediction_payouts ORDER BY charge_id').fetchall()
        before=self.fixture.money()['paypalBalance']
        preview=cards.move_wallet_rewards(self.scope)
        self.assertEqual((preview['count'],preview['amount'],preview['canMove']),(2,100000000,True))
        result=cards.move_wallet_rewards(self.scope,apply=True)
        self.assertEqual(result['walletAfter']+result['cardAfter'],result['walletBefore']+result['cardBefore'])
        self.assertEqual(self.fixture.money()['paypalBalance'],500000)
        self.assertEqual(self.card()[0],100000000)
        self.assertEqual(self.fixture.money()['paypalBalance']+self.card()[0],before)
        self.assertEqual(cards.move_wallet_rewards(self.scope,apply=True)['count'],0)
        with closing(sqlite3.connect(self.account)) as db:
            self.assertEqual(db.execute('SELECT * FROM prediction_payouts ORDER BY charge_id').fetchall(),receipts)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM account_audit WHERE action='card_reward_migration'").fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reward_card_migrations').fetchone()[0],2)
        self.policy.return_value={'destination':'card','currency':'PayPal'}
        self.fixture.cycle();self.fixture.settle(apply=True)
        self.assertEqual(self.card()[0],150000000)
        self.assertEqual(self.fixture.money()['paypalBalance'],500000)

    def test_insufficient_wallet_rolls_back_entire_migration(self):
        self.fixture.cycle();self.fixture.settle(apply=True)
        with closing(sqlite3.connect(self.account)) as db,db:
            db.execute("UPDATE stores SET store_json=? WHERE username='alice'",(json.dumps({'paypalBalance':1,'walletVersion':2}),))
        self.assertFalse(cards.move_wallet_rewards(self.scope)['canMove'])
        with self.assertRaises(ValueError):cards.move_wallet_rewards(self.scope,apply=True)
        self.assertEqual(self.card()[0],0)
        with closing(sqlite3.connect(self.account)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM card_transactions').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reward_card_migrations').fetchone()[0],0)
        self.assertEqual(self.fixture.money()['paypalBalance'],1)

    def test_parallel_migrations_move_once(self):
        self.fixture.cycle();self.fixture.settle(apply=True)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:cards.move_wallet_rewards(self.scope,apply=True),range(4)))
        self.assertEqual(sum(r['count'] for r in results),1)
        self.assertEqual(self.card()[0],50000000)
        self.assertEqual(self.fixture.money()['paypalBalance'],500000)

    def test_card_reward_atomic_on_audit_failure(self):
        self.policy.return_value={'destination':'card','currency':'PayPal'}
        self.fixture.cycle()
        with closing(sqlite3.connect(self.account)) as db,db:
            db.execute("CREATE TRIGGER failure BEFORE INSERT ON account_audit WHEN NEW.action='prediction_card_reward' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        result=self.fixture.settle(apply=True)
        self.assertEqual((result['credited'],len(result['errors'])),(0,1))
        self.assertEqual(self.card()[0],0)
        self.assertEqual(self.fixture.money()['paypalBalance'],500000)
        with closing(sqlite3.connect(self.account)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM prediction_payouts').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM card_transactions').fetchone()[0],0)

    def test_identity_stays_after_rename_and_policy_change_invalidates_plan(self):
        self.fixture.cycle()
        plan=self.fixture.settle()
        self.policy.return_value={'destination':'card','currency':'PayPal'}
        from ai import prediction_rewards
        with self.assertRaises(ValueError):prediction_rewards._credit(self.scope,plan['ready'][0])
        self.assertEqual(self.fixture.money()['paypalBalance'],500000)
        with closing(sqlite3.connect(self.account)) as db,db:
            db.execute("UPDATE users SET username='renamed' WHERE username='alice'")
            db.execute("UPDATE stores SET username='renamed' WHERE username='alice'")
            db.execute("UPDATE personal_tracking_accounts SET username='renamed' WHERE username='alice'")
            db.execute("UPDATE account_identities SET username='renamed' WHERE username='alice'")
        self.scope.owner='renamed'
        self.assertEqual(self.fixture.settle(apply=True)['credited'],1)
        self.assertEqual(self.card()[0],50000000)
