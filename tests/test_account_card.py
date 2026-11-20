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
        self.assertEqual(result['creditedPayPal'],40000000)
        self.assertEqual(self.card(),(40000000,1))
        calc=result['ready'][0]['calculation']
        self.assertEqual((calc['rewardVnd'],calc['paypal'],calc['rateNumerator'],calc['rateDenominator']),
                         (40000000,40000000,1,1))
        self.assertEqual(self.fixture.money(),before)
        self.assertEqual(self.fixture.settle(apply=True)['credited'],0)
        with closing(sqlite3.connect(self.account)) as db:
            self.assertEqual(db.execute('SELECT destination,currency FROM prediction_payout_routes').fetchone(),('card','PayPal'))
            self.assertEqual(db.execute('SELECT action FROM account_audit').fetchall(),[('prediction_card_reward',)])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM card_transactions').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT target_account_id FROM account_activity_links').fetchone()[0],'123456789012')
            self.assertEqual(db.execute('SELECT reward_vnd,paypal_credit FROM prediction_payouts').fetchone(),(40000000,40000000))
            details=json.loads(db.execute('SELECT details_json FROM card_transactions').fetchone()[0])
            self.assertEqual((details['paypal'],details['rateNumerator'],details['rateDenominator']),(40000000,1,1))

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
        self.assertEqual(self.card()[0],140000000)
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

    def test_card_ratio_for_normal_bao_keno_and_odd_jackpot_amount(self):
        self.policy.return_value={'destination':'card','currency':'PayPal'}
        for game in ('LOTO_5_35','LOTO_6_45','LOTO_6_55'):
            for bao in (False,True):self.fixture.cycle(game,count=6 if bao else 4,bao=bao)
        self.fixture.cycle(count=1,keno=True,counts=lambda level,i:{'KENO_1_1':1} if level==1 else {'NONE':1})
        self.fixture.cycle('LOTO_6_45',counts=lambda level,i:{'MEGA_JACKPOT':i+1,'NONE':3-i})
        context={'LOTO_6_45':{'123':{'Bộ Số':'1,2,3,4,5,6','ĐB':'','Ngày':'02/11/2026','Giờ':'18:00','Jackpot (VNĐ)':'103','counts':{'jackpot':0}}}}
        preview=self.fixture.settle(prizes=context)
        self.assertEqual((len(preview['ready']),len(preview['waiting'])),(8,0))
        self.assertEqual(preview['paypal'],preview['rewardVnd'])
        self.assertTrue(any(item['calculation']['paypal']==407 for item in preview['ready']))
        self.assertTrue(all(item['calculation']['version']=='prediction_card_reward_v2' and
                            item['calculation']['rateNumerator']==item['calculation']['rateDenominator']==1 for item in preview['ready']))
        paid=self.fixture.settle(apply=True,prizes=context)
        self.assertEqual((paid['credited'],self.card()[0]),(8,preview['rewardVnd']))
        with closing(sqlite3.connect(self.account)) as db:
            receipts=db.execute('SELECT * FROM prediction_payouts ORDER BY charge_id').fetchall()
        context['LOTO_6_45']['123']['Jackpot (VNĐ)']='9999999999'
        self.assertEqual(self.fixture.settle(apply=True,prizes=context)['credited'],0)
        with closing(sqlite3.connect(self.account)) as db:
            self.assertEqual(db.execute('SELECT * FROM prediction_payouts ORDER BY charge_id').fetchall(),receipts)

    def test_stale_card_conversion_plan_is_rejected_before_credit(self):
        from ai import prediction_rewards as rewards
        self.policy.return_value={'destination':'card','currency':'PayPal'}
        self.fixture.cycle()
        item=self.fixture.settle()['ready'][0]
        calc=item['calculation']
        calc.update(version='prediction_wallet_reward_v1',rateNumerator=5,rateDenominator=4,paypal=calc['rewardVnd']*5//4)
        item['hash']=rewards._digest(calc)
        with self.assertRaisesRegex(ValueError,'1:1'):rewards._credit(self.scope,item)
        with closing(sqlite3.connect(self.account)) as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='account_cards'").fetchone())
        self.assertEqual(self.fixture.money()['paypalBalance'],500000)
        self.assertEqual(self.fixture.settle(apply=True)['creditedPayPal'],40000000)

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
            db.execute('DROP TRIGGER failure')
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:self.fixture.settle(apply=True),range(4)))
        self.assertEqual(sum(r['credited'] for r in results),1)
        self.assertEqual(self.card(),(40000000,1))

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
        self.assertEqual(self.card()[0],40000000)
