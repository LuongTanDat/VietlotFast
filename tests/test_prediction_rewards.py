"""Only fixture wallets are credited; production is previewed separately."""
import json
import sqlite3
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from ai import personal_tracking as billing, prediction_rewards as rewards
from ai import account_statistics as stats
from ai import account_card as cards
from tests.test_prize_web import ROOT


class PredictionRewardTests(unittest.TestCase):
    def setUp(self):
        self.routing=patch.object(cards,'policy',return_value={'destination':'wallet','currency':'PayPal'})
        self.routing.start();self.addCleanup(self.routing.stop)
        self.temp=tempfile.TemporaryDirectory(prefix='reward-fixture-',dir=ROOT/'runtime/logs')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.account=self.root/'accounts.db'
        self.aid=str(uuid.uuid4());self.scope=billing.Scope(self.aid,'alice',self.account,self.root)
        self.scope.database.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.account)) as db, db:
            db.executescript('''
                CREATE TABLE users(username TEXT PRIMARY KEY,enabled INTEGER);
                CREATE TABLE personal_tracking_accounts(id TEXT PRIMARY KEY,username TEXT UNIQUE);
                CREATE TABLE stores(username TEXT PRIMARY KEY,store_json TEXT);
                CREATE TABLE prediction_charges(id TEXT PRIMARY KEY,account_id TEXT,game_type TEXT,target_draw_id TEXT,ticket_count INTEGER,paypal_cost INTEGER,status TEXT,created_at TEXT,settled_at TEXT);
                CREATE TABLE account_audit(event_id TEXT PRIMARY KEY,actor TEXT,target TEXT,action TEXT,details_json TEXT,created_at TEXT);
            ''')
            db.execute("INSERT INTO users VALUES('alice',1)")
            db.execute("INSERT INTO users VALUES('bob',1)")
            db.execute('INSERT INTO personal_tracking_accounts VALUES(?,?)',(self.aid,'alice'))
            db.execute("INSERT INTO stores VALUES('alice',?)",(json.dumps({'paypalBalance':500000,'walletVersion':1}),))
        with closing(sqlite3.connect(self.scope.database)) as db, db:
            db.executescript('''
                CREATE TABLE paid_cycle_receipts(charge_id TEXT PRIMARY KEY,cycle_id TEXT UNIQUE,ticket_count INTEGER);
                CREATE TABLE effectiveness_cycles(cycle_id TEXT PRIMARY KEY,game_type TEXT,target_draw_id TEXT,created_at TEXT,deadline TEXT,config_json TEXT);
                CREATE TABLE effectiveness_predictions(cycle_id TEXT,method TEXT,prediction_id TEXT);
                CREATE TABLE prediction_runs(prediction_id TEXT PRIMARY KEY,username TEXT,status TEXT);
                CREATE TABLE prediction_scores(prediction_id TEXT,metrics_json TEXT,scoring_version TEXT);
                CREATE TABLE keno_effectiveness_cycles(cycle_id TEXT PRIMARY KEY,target_draw_id TEXT,created_at TEXT,deadline TEXT,status TEXT,actual_json TEXT,config_json TEXT);
                CREATE TABLE keno_effectiveness_predictions(cycle_id TEXT,level INTEGER,method TEXT,prediction_id TEXT);
                CREATE TABLE keno_effectiveness_metrics(cycle_id TEXT,level INTEGER,method TEXT,ticket_count INTEGER,summary_json TEXT);
            ''')

    def cycle(self,game='LOTO_5_35',count=4,counts=None,bao=False,keno=False):
        game='KENO' if keno else game
        cycle,charge=str(uuid.uuid4()),str(uuid.uuid4())
        created='2026-11-01T00:00:00+00:00';deadline='2026-11-02T18:00:00+07:00';draw='123'
        total=count*(40 if keno else 4)
        with closing(sqlite3.connect(self.account)) as db, db:
            db.execute('INSERT INTO prediction_charges VALUES(?,?,?,?,?,?,?,?,?)',(charge,self.aid,game,draw,total,total*10000,'charged',created,created))
        with closing(sqlite3.connect(self.scope.database)) as db, db:
            db.execute('INSERT INTO paid_cycle_receipts VALUES(?,?,?)',(charge,cycle,total))
            config={'ticketCount':count,'actualTicketCount':count,'ticketClass':'bao' if bao else 'normal','baoLevel':6 if bao else 0,'ticketCountsByLevel':{str(i):count for i in range(1,11)}}
            main=list(range(1,21 if keno else 6 if game=='LOTO_5_35' else 7))
            special=7 if game in ('LOTO_5_35','LOTO_6_55') else None
            if keno:
                db.execute('INSERT INTO keno_effectiveness_cycles VALUES(?,?,?,?,?,?,?)',(cycle,draw,created,deadline,'scored',json.dumps({'main':main,'special':None}),json.dumps(config)))
            else:
                db.execute('INSERT INTO effectiveness_cycles VALUES(?,?,?,?,?,?)',(cycle,game,draw,created,deadline,json.dumps(config)))
            for level in range(1,11) if keno else (None,):
                for index,method in enumerate(stats.METHODS):
                    prediction=cycle+'_'+str(level)+'_'+method
                    db.execute('INSERT INTO prediction_runs VALUES(?,?,?)',(prediction,stats.EFFECTIVENESS_SYSTEM_ACTOR,'scored'))
                    selected=counts(level,index) if callable(counts) else counts or {'FIRST':1,'NONE':count-1}
                    if keno:
                        db.execute('INSERT INTO keno_effectiveness_predictions VALUES(?,?,?,?)',(cycle,level,method,prediction))
                        db.execute('INSERT INTO keno_effectiveness_metrics VALUES(?,?,?,?,?)',(cycle,level,method,count,json.dumps({'prizeCounts':selected})))
                    else:
                        db.execute('INSERT INTO effectiveness_predictions VALUES(?,?,?)',(cycle,method,prediction))
                        metrics={'ticket_count':count,'actual_main':main,'actual_special':special,'report_summary':{'prizeCounts':selected}}
                        db.execute('INSERT INTO prediction_scores VALUES(?,?,?)',(prediction,json.dumps(metrics),stats.SCORING_VERSION))
        return cycle,charge

    def money(self):
        with closing(sqlite3.connect(self.account)) as db:
            return json.loads(db.execute("SELECT store_json FROM stores WHERE username='alice'").fetchone()[0])

    def settle(self,**kwargs):
        kwargs.setdefault('prizes',{})
        return rewards.settle(self.scope,now=datetime(2026,11,3,tzinfo=timezone.utc),**kwargs)

    def test_fixed_all_games_normal_bao_read_only_then_exactly_once(self):
        for game in stats.GAMES[:3]:
            for bao in (False,True):self.cycle(game,count=6 if bao else 4,bao=bao)
        before=[p.read_bytes() for p in [self.account,self.scope.database]]
        preview=self.settle()
        self.assertEqual(len(preview['ready']),6)
        self.assertEqual(preview['paypal'],600000000)
        self.assertEqual(before,[p.read_bytes() for p in [self.account,self.scope.database]])
        tracking_before=self.scope.database.read_bytes()
        paid=self.settle(apply=True)
        self.assertEqual((paid['credited'],paid['creditedPayPal']),(6,600000000))
        self.assertEqual(self.money(),{'paypalBalance':600500000,'walletVersion':7})
        self.assertEqual(self.scope.database.read_bytes(),tracking_before)
        self.assertEqual(self.settle(apply=True)['alreadySettled'],6)
        with closing(sqlite3.connect(self.account)) as db, db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM account_audit WHERE action='prediction_reward'").fetchone()[0],6)
            self.assertRaises(sqlite3.IntegrityError,db.execute,'DELETE FROM prediction_payouts')

    def test_jackpot_independent_methods_conversion_and_missing_context_retry(self):
        self.cycle('LOTO_6_45',counts=lambda level,i:{'MEGA_JACKPOT':i+1,'NONE':3-i})
        waiting=self.settle(apply=True)
        self.assertEqual((waiting['credited'],len(waiting['waiting'])),(0,1))
        context={'LOTO_6_45':{'123':{'Bộ Số':'1,2,3,4,5,6','ĐB':'','Ngày':'02/11/2026','Giờ':'18:00','Jackpot (VNĐ)':'103','counts':{'jackpot':0}}}}
        payout=self.settle(apply=True,prizes=context)
        # 103 + (103//2)*2 + (103//3)*3 + (103//4)*4 = 407 VND.
        self.assertEqual(payout['creditedPayPal'],508)
        self.assertEqual(self.money()['paypalBalance'],500508)
        context['LOTO_6_45']['123']['Jackpot (VNĐ)']='9999999999'
        self.assertEqual(self.settle(apply=True,prizes=context)['creditedPayPal'],0)
        self.assertEqual(self.money()['paypalBalance'],500508)

    def test_keno_all_ten_levels_and_cap_per_method(self):
        self.cycle(count=1,keno=True,counts=lambda level,i:{'KENO_1_1':1} if level==1 else {'KENO_8_8':1} if level==8 else {'NONE':1})
        actual={'main':list(range(1,21))}
        identity=stats.keno_prizes.identity('123',actual,'2026-11-02T18:00:00+07:00')
        context={'KENO':{'123':{'draw':identity,'winnerCounts':{'8':50,'9':0,'10':0}}}}
        result=self.settle(apply=True,prizes=context)
        self.assertEqual(result['creditedPayPal'],(20000+10000000000//51)*4*5//4)
        self.assertEqual(len(result['ready'][0]['calculation']['components']),40)

    def test_invalid_or_unpaid_and_incomplete_cycles_never_credit(self):
        a,charge=self.cycle();b,_=self.cycle();c,_=self.cycle();d,_=self.cycle()
        with closing(sqlite3.connect(self.account)) as db, db:
            db.execute("UPDATE prediction_charges SET status='refunded' WHERE id=?",(charge,))
        with closing(sqlite3.connect(self.scope.database)) as db, db:
            db.execute("UPDATE prediction_runs SET status='locked' WHERE prediction_id LIKE ?",(b+'%',))
            db.execute('UPDATE paid_cycle_receipts SET ticket_count=17 WHERE cycle_id=?',(c,))
            db.execute('DELETE FROM effectiveness_predictions WHERE cycle_id=? AND method=\'random\'',(d,))
        result=self.settle(apply=True)
        self.assertEqual((result['credited'],len(result['waiting'])),(0,3))
        self.assertEqual(self.money()['paypalBalance'],500000)

    def test_parallel_calls_and_atomic_failure_then_retry(self):
        self.cycle()
        with closing(sqlite3.connect(self.account)) as db, db:
            db.execute("CREATE TRIGGER fixture_failure BEFORE INSERT ON account_audit WHEN NEW.action='prediction_reward' BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        failed=self.settle(apply=True)
        self.assertEqual((failed['credited'],len(failed['errors'])),(0,1))
        self.assertEqual(self.money(),{'paypalBalance':500000,'walletVersion':1})
        with closing(sqlite3.connect(self.account)) as db, db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM prediction_payouts').fetchone()[0],0)
            db.execute('DROP TRIGGER fixture_failure')
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:self.settle(apply=True),range(4)))
        self.assertEqual(sum(r['credited'] for r in results),1)
        self.assertEqual(self.money(),{'paypalBalance':50500000,'walletVersion':2})

    def test_overflow_zero_wins_and_policy_gate(self):
        self.cycle()
        with closing(sqlite3.connect(self.account)) as db, db:
            db.execute("UPDATE stores SET store_json=? WHERE username='alice'",(json.dumps({'paypalBalance':billing.MAX_SAFE,'walletVersion':1}),))
        result=self.settle(apply=True)
        self.assertEqual((result['credited'],len(result['errors'])),(0,1))
        with patch.object(billing.dp,'PROJECT_ROOT',self.root):
            self.assertEqual(self.scope.settle_rewards(),{'status':'disabled'})
        with closing(sqlite3.connect(self.account)) as db, db:
            db.execute("UPDATE prediction_charges SET status='refunded'")
        self.cycle(counts={'NONE':4})
        result=self.settle(apply=True)
        self.assertEqual((result['credited'],result['creditedPayPal']),(1,0))
        self.assertEqual(self.money()['walletVersion'],1)

    def test_enabled_policy_settles_existing_scored_receipts_without_generation(self):
        self.cycle()
        (self.root/'config').mkdir()
        (self.root/'config/prediction-rewards.json').write_text('{"enabled":true}',encoding='utf-8')
        with patch.object(billing.dp,'PROJECT_ROOT',self.root),patch.object(stats,'canonical_prizes',return_value={}):
            result=self.scope.settle_rewards()
            self.assertEqual(result['creditedPayPal'],50000000)
            self.assertEqual(self.scope.settle_rewards()['creditedPayPal'],0)


if __name__=='__main__':unittest.main()
