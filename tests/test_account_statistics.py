"""Read-only totals, time boundaries and account isolation for the charts."""
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from contextlib import closing
from pathlib import Path

from ai import account_statistics as stats


class AccountStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='account-stats-')
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.account = self.work/'account.db'
        self.tracking = self.work/'tracking.db'
        with closing(sqlite3.connect(self.account)) as db, db:
            db.executescript('''CREATE TABLE users(username TEXT PRIMARY KEY);
                CREATE TABLE payment_orders(username TEXT,status TEXT,environment TEXT,amount INTEGER,paid_at TEXT);
                INSERT INTO users VALUES('alice'),('bob');''')
            db.executemany('INSERT INTO payment_orders VALUES(?,?,?,?,?)', [
                ('alice','PAID','production',100000,'2026-10-17T17:00:00Z'),
                ('alice','PAID','production',20000,'2026-10-17T16:59:59Z'),
                ('alice','TEST_PAID','sandbox',900000,'2026-10-18T01:00:00Z'),
                ('alice','PAID','sandbox',900000,'2026-10-18T01:00:00Z'),
                ('alice','PENDING','production',900000,''),
                ('bob','PAID','production',700000,'2026-10-18T01:00:00Z')])
        with closing(sqlite3.connect(self.tracking)) as db, db:
            db.executescript('''CREATE TABLE effectiveness_cycles(cycle_id TEXT,game_type TEXT,target_draw_id TEXT,created_at TEXT,deadline TEXT,config_json TEXT);
                CREATE TABLE effectiveness_predictions(cycle_id TEXT,method TEXT,prediction_id TEXT);
                CREATE TABLE prediction_runs(prediction_id TEXT,username TEXT,status TEXT);
                CREATE TABLE prediction_scores(prediction_id TEXT,metrics_json TEXT,scoring_version TEXT);
                CREATE TABLE keno_effectiveness_cycles(cycle_id TEXT,target_draw_id TEXT,created_at TEXT,deadline TEXT,status TEXT,actual_json TEXT,config_json TEXT);
                CREATE TABLE keno_effectiveness_predictions(cycle_id TEXT,level INTEGER,method TEXT,prediction_id TEXT);
                CREATE TABLE keno_effectiveness_metrics(cycle_id TEXT,level INTEGER,method TEXT,ticket_count INTEGER,summary_json TEXT);''')
        self.cycle('a','2026-10-17T17:30:00Z','2026-10-18T06:00:00Z')
        self.cycle('b','2026-10-16T01:00:00Z','2026-10-16T06:00:00Z', legacy=True)
        self.cycle('pending','2026-10-18T02:00:00Z','2026-10-18T14:00:00Z', pending=True)

    def cycle(self, key, created, deadline, pending=False, legacy=False, counts=None, game='LOTO_5_35'):
        with closing(sqlite3.connect(self.tracking)) as db, db:
            db.execute('INSERT INTO effectiveness_cycles VALUES(?,?,?,?,?,?)',
                (key,game,str(len(key)+100),created,deadline,json.dumps({'ticketCount':1000000,'actualTicketCount':20})))
            for method in stats.METHODS:
                prediction=key+'_'+method
                db.execute('INSERT INTO effectiveness_predictions VALUES(?,?,?)',(key,method,prediction))
                db.execute('INSERT INTO prediction_runs VALUES(?,?,?)',(prediction,stats.EFFECTIVENESS_SYSTEM_ACTOR,'locked' if pending else 'scored'))
                if not pending:
                    selected=counts or ({'THIRD':2,'NONE':18} if method!='random' else {'FIRST':1,'NONE':19})
                    metrics={'ticket_count':20,'actual_main':list(range(1,6 if game=='LOTO_5_35' else 7)),
                             'actual_special':None if game=='LOTO_6_45' else 8}
                    if legacy:
                        metrics['prize_results']=[{'prizeCode':code} for code,n in selected.items() for _ in range(n)]
                    else:
                        metrics['report_summary']={'prizeCounts':selected}
                    db.execute('INSERT INTO prediction_scores VALUES(?,?,?)',(prediction,json.dumps(metrics),stats.SCORING_VERSION))

    def report(self, **kwargs):
        return stats.report('alice', account_db=self.account, tracking_db=self.tracking, prizes={}, anchor='2026-10-18', **kwargs)

    def test_all_totals_paid_only_isolation_and_readonly(self):
        before=[p.read_bytes() for p in (self.account,self.tracking)]
        report=self.report()
        self.assertEqual(report['totals']['deposited'],120000)
        self.assertEqual(report['totals']['bought'],60)
        self.assertEqual(report['totals']['spent'],600000)
        self.assertEqual(report['totals']['reward'],2000000)
        self.assertEqual(report['totals']['won'],4)
        self.assertEqual(report['totals']['pending'],20)
        self.assertEqual(report['totals']['scored'],40)
        self.assertEqual(self.report(method='random')['totals']['reward'],20000000)
        self.assertEqual(stats.report('bob',account_db=self.account,tracking_db=self.tracking,prizes={})['totals']['deposited'],700000)
        self.assertEqual(before,[p.read_bytes() for p in (self.account,self.tracking)])
        with closing(sqlite3.connect(self.tracking)) as db, db:
            db.execute("UPDATE prediction_runs SET status='void' WHERE prediction_id='a_web'")
        self.assertEqual(self.report()['totals']['bought'],40)

    def test_manual_deposits_count_only_approved_at_review_time(self):
        with closing(sqlite3.connect(self.account)) as db, db:
            db.executemany('INSERT INTO payment_orders VALUES(?,?,?,?,?)', [
                ('alice','PAID','manual',50000,'2026-10-18T01:00:00Z'),
                ('alice','PENDING','manual',80000,''),
                ('alice','REJECTED','manual',90000,''),
                ('bob','PAID','manual',60000,'2026-10-18T01:00:00Z')])
        self.assertEqual(self.report()['totals']['deposited'],170000)
        report = self.report(period='day')
        self.assertEqual(report['totals']['deposited'],150000)
        self.assertEqual(report['series'][8]['deposited'],50000)

    def test_vietnam_midnight_week_month_year_and_zero_buckets(self):
        report=self.report(period='day')
        self.assertEqual(len(report['series']),24)
        self.assertEqual(report['totals']['deposited'],100000)
        self.assertEqual(report['totals']['bought'],40)
        self.assertEqual(report['totals']['won'],2)
        self.assertEqual(report['series'][0]['deposited'],100000)
        self.assertEqual(stats.period_bounds('week',date(2026,1,1)),(date(2025,12,29),date(2026,1,5)))
        self.assertEqual(stats.period_bounds('month',date(2026,12,4)),(date(2026,12,1),date(2027,1,1)))
        self.assertEqual(len(self.report(period='week')['series']),7)
        self.assertEqual(len(self.report(period='month')['series']),31)
        self.assertEqual(len(self.report(period='year')['series']),12)
        self.cycle('july','2026-07-05T01:00:00Z','2026-07-05T06:00:00Z')
        self.assertEqual([row['key'] for row in self.report()['series']],['2026-07','2026-08','2026-09','2026-10'])
        for period in ('bad','DAY',''):
            with self.assertRaises(ValueError): self.report(period=period)

    def test_future_days_and_draw_pending_are_marked_without_changing_totals(self):
        from unittest.mock import patch
        self.cycle('monday','2026-10-19T01:00:00Z','2026-10-19T06:00:00Z')
        self.cycle('tuesday','2026-10-20T01:00:00Z','2026-10-20T06:00:00Z')
        self.cycle('tomorrow','2026-10-20T02:00:00Z','2026-10-21T06:00:00Z',pending=True)
        before=[p.read_bytes() for p in (self.account,self.tracking)]
        now=stats.datetime(2026,10,20,14,30,tzinfo=stats.TZ)
        with patch.object(stats,'datetime',wraps=stats.datetime) as clock:
            clock.now.side_effect=lambda tz:now.astimezone(tz)
            report=stats.report('alice',method='all',period='week',anchor='2026-10-20',account_db=self.account,tracking_db=self.tracking,prizes={})
        self.assertEqual([row['future'] for row in report['series']],[False,False,True,True,True,True,True])
        self.assertEqual(report['series'][2]['drawPending'],80)
        self.assertEqual(report['series'][2]['scored'],0)
        self.assertEqual(report['totals']['won'],14)
        self.assertEqual(report['totals']['reward'],26000000)
        self.assertEqual(report['totals']['drawPending'],80)
        self.assertEqual(report['totals']['bought'],240)
        self.assertEqual(before,[p.read_bytes() for p in (self.account,self.tracking)])

    def test_scored_zero_wins_and_partial_unknown_results_remain_distinct(self):
        self.cycle('real-zero','2026-10-19T01:00:00Z','2026-10-19T06:00:00Z',counts={'NONE':20})
        self.cycle('unknown-result','2026-10-20T01:00:00Z','2026-10-20T06:00:00Z',counts={'UNKNOWN':1,'NONE':19})
        self.cycle('partial-payout','2026-10-20T01:00:00Z','2026-10-20T06:00:00Z',counts={'LOTTO_JACKPOT':1,'THIRD':1,'NONE':18})
        report=stats.report('alice',method='all',period='week',anchor='2026-10-20',account_db=self.account,tracking_db=self.tracking,prizes={})
        zero,partial=report['series'][:2]
        self.assertEqual((zero['scored'],zero['won'],zero['reward'],zero['incomplete'],zero['unknownTickets']),(80,0,0,0,0))
        self.assertEqual((partial['scored'],partial['won'],partial['reward'],partial['unknownTickets']),(160,8,2000000,4))
        self.assertGreater(partial['incomplete'],0)

    def test_all_methods_add_portfolios_but_not_personal_deposits(self):
        result = self.report(method='all')
        self.assertEqual(result['totals']['deposited'],120000)
        self.assertEqual(result['totals']['bought'],240)
        self.assertEqual(result['totals']['spent'],2400000)
        self.assertEqual(result['totals']['reward'],26000000)
        self.assertEqual(result['totals']['won'],14)
        self.assertEqual(result['totals']['pending'],80)
        self.assertEqual(result['totals']['scored'],160)
        for period in ('all','day','week','month','year'):
            total=self.report(method='all',period=period)['totals']
            individual=[self.report(method=method,period=period)['totals'] for method in stats.METHODS]
            for key in ('bought','spent','reward','won','pending','scored'):
                self.assertEqual(total[key],sum(row[key] for row in individual),(period,key))
            self.assertEqual(total['deposited'],individual[0]['deposited'])
        with self.assertRaises(ValueError): self.report(method='invalid')

    def test_method_distribution_uses_actual_counts_and_ignores_method_filter(self):
        # A different real count must produce a different slice, not four fixed 25% slices.
        with closing(sqlite3.connect(self.tracking)) as db, db:
            raw=db.execute("SELECT metrics_json FROM prediction_scores WHERE prediction_id='a_random'").fetchone()[0]
            metrics=json.loads(raw)
            metrics['ticket_count']=40
            metrics['report_summary']['prizeCounts']['NONE']=39
            db.execute("UPDATE prediction_scores SET metrics_json=? WHERE prediction_id='a_random'",(json.dumps(metrics),))
        before=[p.read_bytes() for p in (self.account,self.tracking)]
        for method in (*stats.METHODS,'all'):
            result=self.report(method=method,period='day')
            self.assertEqual(result['methodDistribution'],[
                {'method':name,'tickets':60 if name=='random' else 40} for name in stats.METHODS])
        self.assertEqual(sum(row['tickets'] for row in self.report(method='all',period='day')['methodDistribution']),180)
        self.assertEqual(stats.report('alice',account_db=self.account,tracking_db=self.tracking,prizes={},period='day',anchor='2026-10-01')['methodDistribution'],[
            {'method':name,'tickets':0} for name in stats.METHODS])
        self.assertEqual(before,[p.read_bytes() for p in (self.account,self.tracking)])

    def test_inner_ring_wins_all_methods_uses_draw_date_and_ignores_pending(self):
        before=[p.read_bytes() for p in (self.account,self.tracking)]
        expected=[{'method':name,'tickets':1 if name=='random' else 2,'scored':20,'unknownTickets':0} for name in stats.METHODS]
        for method in (*stats.METHODS,'all'):
            self.assertEqual(self.report(method=method,period='day')['methodWinDistribution'],expected)
        self.assertEqual(sum(row['tickets'] for row in expected),self.report(method='all',period='day')['totals']['won'])
        self.assertEqual(before,[p.read_bytes() for p in (self.account,self.tracking)])
        self.cycle('earlier-purchase','2026-10-01T01:00:00Z','2026-11-01T06:00:00Z')
        result=stats.report('alice',method='web',period='day',anchor='2026-11-01',account_db=self.account,tracking_db=self.tracking,prizes={})
        self.assertEqual(sum(row['tickets'] for row in result['methodDistribution']),0)
        self.assertEqual(result['methodWinDistribution'],expected)

    def test_inner_ring_unknown_and_missing_payout_are_distinct(self):
        self.cycle('unknown-ring','2026-10-18T01:00:00Z','2026-10-18T06:00:00Z',counts={'UNKNOWN':1,'NONE':19})
        self.cycle('unpaid-ring','2026-10-18T01:00:00Z','2026-10-18T06:00:00Z',counts={'LOTTO_JACKPOT':1,'NONE':19})
        for method in (*stats.METHODS,'all'):
            rows=self.report(method=method,period='day')['methodWinDistribution']
            self.assertEqual(rows,[{'method':name,'tickets':2 if name=='random' else 3,'scored':60,'unknownTickets':1} for name in stats.METHODS])
        with closing(sqlite3.connect(self.tracking)) as db, db:
            db.execute("UPDATE prediction_scores SET metrics_json=json_set(metrics_json,'$.report_summary.prizeCounts.NONE',17) WHERE prediction_id='a_web'")
        web=self.report(period='day')['methodWinDistribution'][0]
        self.assertEqual((web['tickets'],web['unknownTickets']),(1,21))

    def test_purchase_outcomes_compare_same_tickets_across_draw_boundaries(self):
        self.cycle('previous-purchase','2026-10-17T01:00:00Z','2026-10-18T06:00:00Z')
        self.cycle('later-result','2026-10-18T01:00:00Z','2026-10-19T06:00:00Z')
        before=[p.read_bytes() for p in (self.account,self.tracking)]
        expected=[{'method':name,'tickets':60,'won':2 if name=='random' else 4,
                   'scored':40,'unknownTickets':0,'pending':20} for name in stats.METHODS]
        for method in (*stats.METHODS,'all'):
            result=self.report(method=method,period='day')
            self.assertEqual(result['methodPurchaseOutcomes'],expected)
            self.assertEqual([row['tickets'] for row in result['methodDistribution']],[60]*4)
        # On the following day only results exist; the purchase chart stays empty.
        later=stats.report('alice',method='all',period='day',anchor='2026-10-19',account_db=self.account,tracking_db=self.tracking,prizes={})
        self.assertGreater(later['totals']['won'],0)
        self.assertTrue(all(row['tickets']==row['won']==0 for row in later['methodPurchaseOutcomes']))
        for period in ('all','day','week','month','year'):
            result=self.report(method='all',game='all',period=period)
            for outcome,purchased in zip(result['methodPurchaseOutcomes'],result['methodDistribution']):
                self.assertEqual(outcome['tickets'],purchased['tickets'])
                self.assertEqual(outcome['tickets'],outcome['scored']+outcome['pending'])
                self.assertLessEqual(outcome['won']+outcome['unknownTickets'],outcome['scored'])
        self.assertEqual(before,[p.read_bytes() for p in (self.account,self.tracking)])

    def test_purchase_outcomes_keep_unknown_winners_and_unpaid_jackpots(self):
        self.cycle('unknown-purchased','2026-10-18T01:00:00Z','2026-10-18T06:00:00Z',counts={'UNKNOWN':1,'NONE':19})
        self.cycle('unpaid-purchased','2026-10-18T01:00:00Z','2026-10-18T06:00:00Z',counts={'LOTTO_JACKPOT':1,'NONE':19})
        for method in (*stats.METHODS,'all'):
            rows=self.report(method=method,period='day')['methodPurchaseOutcomes']
            self.assertEqual(rows,[{'method':name,'tickets':80,'won':2 if name=='random' else 3,
                                   'scored':60,'unknownTickets':1,'pending':20} for name in stats.METHODS])

    def test_previous_calendar_periods_and_readonly_comparison(self):
        self.cycle('prev-month','2026-09-30T16:59:59Z','2026-09-30T06:00:00Z')
        self.cycle('prev-year','2025-12-31T16:59:59Z','2025-12-31T06:00:00Z')
        before=[p.read_bytes() for p in (self.account,self.tracking)]
        expected={'day':('2026-10-17','2026-10-18'), 'week':('2026-10-05','2026-10-12'),
                  'month':('2026-09-01','2026-10-01'),'year':('2025-01-01','2026-01-01')}
        for method in ('web','all'):
            for period,(start,end) in expected.items():
                result=self.report(game='all',method=method,period=period)
                previous=result['comparison']
                self.assertEqual((previous['from'],previous['until']),(start,end))
                separate=stats.report('alice',game='all',method=method,period=period,anchor=start,
                                      account_db=self.account,tracking_db=self.tracking,prizes={})
                self.assertEqual(previous['totals'],separate['totals'])
                for key in ('deposited','spent','reward','bought','won'):
                    self.assertEqual(previous['changes'][key],result['totals'][key]-separate['totals'][key])
        result=self.report(period='day')
        self.assertEqual(result['comparison']['changes']['deposited'],80000)
        self.assertEqual(result['comparison']['totals']['deposited'],20000)
        self.assertEqual(result['totals']['bought'],40)
        self.assertEqual(len(result['series']),24)
        self.assertIsNone(self.report()['comparison'])
        self.assertEqual(before,[p.read_bytes() for p in (self.account,self.tracking)])
        # Previous full calendar periods cross years and leap February correctly.
        for period,anchor,expected in [
                ('week','2026-01-01',('2025-12-22','2025-12-29')),
                ('month','2024-03-31',('2024-02-01','2024-03-01')),
                ('month','2026-01-31',('2025-12-01','2026-01-01')),
                ('year','2024-02-29',('2023-01-01','2024-01-01'))]:
            result=stats.report('alice',period=period,anchor=anchor,account_db=self.account,
                                tracking_db=self.tracking,prizes={})['comparison']
            self.assertEqual((result['from'],result['until']),expected)

    def test_previous_series_has_full_calendar_slots_and_matches_previous_totals(self):
        self.cycle('previous-day','2026-10-17T00:00:00Z','2026-10-17T06:00:00Z')
        before=[p.read_bytes() for p in (self.account,self.tracking)]
        for period,length in [('day',24),('week',7),('month',30),('year',12)]:
            result=self.report(game='all',method='all',period=period)
            comparison=result['comparison']
            self.assertEqual(len(comparison['series']),length)
            separate=stats.report('alice',game='all',method='all',period=period,anchor=comparison['from'],account_db=self.account,tracking_db=self.tracking,prizes={})
            self.assertEqual([row['key'] for row in comparison['series']],[row['key'] for row in separate['series']])
            for key in comparison['totals']:
                if key!='key':self.assertEqual(sum(row[key] for row in comparison['series']),comparison['totals'][key],(period,key))
            self.assertEqual(comparison['totals'],separate['totals'])
        day=self.report(period='day')['comparison']['series']
        self.assertEqual(day[7]['key'],'2026-10-17T07:00')
        self.assertEqual(day[7]['spent'],200000)
        self.assertEqual(day[13]['reward'],1000000)
        for anchor,previous_days in [('2024-03-31',29),('2025-03-31',28),('2026-01-31',31)]:
            result=stats.report('alice',period='month',anchor=anchor,account_db=self.account,tracking_db=self.tracking,prizes={})
            self.assertEqual(len(result['comparison']['series']),previous_days)
        self.assertEqual(before,[p.read_bytes() for p in (self.account,self.tracking)])

    def test_comparison_negative_zero_and_missing_reward(self):
        for i in range(3):
            self.cycle('yesterday'+str(i),'2026-10-17T01:00:00Z','2026-10-17T06:00:00Z')
        result=self.report(period='day')['comparison']
        self.assertEqual(result['changes']['spent'],-200000)
        self.assertEqual(result['changes']['bought'],-20)
        self.assertEqual(result['changes']['reward'],-2000000)
        # Compare the displayed known subtotals and mark partial payout totals.
        self.cycle('missing','2026-10-17T01:00:00Z','2026-10-17T06:00:00Z',counts={'LOTTO_JACKPOT':1,'NONE':19})
        result=self.report(period='day')
        self.assertEqual(result['comparison']['changes']['reward'],-2000000)
        self.assertTrue(result['comparison']['estimated']['reward'])
        self.assertEqual(result['comparison']['changes']['won'],-5)
        self.cycle('unknown','2026-10-17T01:00:00Z','2026-10-17T06:00:00Z',counts={'UNKNOWN':1,'NONE':19})
        self.assertIsNone(self.report(period='day')['comparison']['changes']['won'])
        empty=stats.report('alice',period='day',anchor='2026-11-18',account_db=self.account,
                          tracking_db=self.tracking,prizes={})
        self.assertEqual(set(empty['comparison']['changes'].values()),{0})
        self.assertFalse(empty['comparison']['estimated']['reward'])

    def test_partial_reward_comparison_for_both_sides_and_periods(self):
        self.cycle('partial-previous','2026-10-17T01:00:00Z','2026-10-17T06:00:00Z',
                   counts={'LOTTO_JACKPOT':1,'THIRD':1,'NONE':18})
        self.cycle('partial-current','2026-10-18T01:00:00Z','2026-10-18T06:00:00Z',
                   counts={'LOTTO_JACKPOT':1,'THIRD':1,'NONE':18})
        before=[p.read_bytes() for p in (self.account,self.tracking)]
        for period in ('day','week','month','year'):
            for game in ('LOTO_5_35','all'):
                result=self.report(game=game,method='all',period=period)
                comp=result['comparison']
                self.assertEqual(comp['changes']['reward'],result['totals']['reward']-comp['totals']['reward'])
                self.assertTrue(comp['estimated']['reward'])
        day=self.report(period='day')
        self.assertEqual(day['totals']['reward'],1500000)
        self.assertEqual(day['comparison']['totals']['reward'],500000)
        self.assertEqual(day['comparison']['changes']['reward'],1000000)
        self.assertGreater(day['totals']['incomplete'],0)
        self.assertGreater(day['comparison']['totals']['incomplete'],0)
        self.assertEqual(before,[p.read_bytes() for p in (self.account,self.tracking)])

    def test_all_games_fixed_rewards_filters_and_deposits_once(self):
        for game in ('LOTO_6_45','LOTO_6_55'):
            self.cycle(game,'2026-10-18T03:00:00Z','2026-10-18T11:00:00Z',
                       counts={'THIRD':1,'NONE':19},game=game)
        before=[p.read_bytes() for p in (self.account,self.tracking)]
        for method in ('all',*stats.METHODS):
            for period in ('all','day','week','month','year'):
                total=self.report(game='all',method=method,period=period)['totals']
                separate=[self.report(game=game,method=method,period=period)['totals'] for game in stats.GAMES]
                for key in ('bought','spent','reward','won','pending','scored'):
                    self.assertEqual(total[key],sum(row[key] for row in separate),(method,period,key))
                self.assertEqual(total['deposited'],separate[0]['deposited'])
        total=self.report(game='all',method='all')['totals']
        self.assertEqual((total['bought'],total['reward'],total['deposited']),(400,26320000,120000))
        self.assertEqual(before,[p.read_bytes() for p in (self.account,self.tracking)])
        with self.assertRaises(ValueError): self.report(game='invalid')

    def test_all_games_keep_jackpot_pools_separate(self):
        self.cycle('jp','2026-10-18T03:00:00Z','2026-10-18T06:00:00Z',counts={'LOTTO_JACKPOT':2,'NONE':18})
        self.cycle('mega','2026-10-18T03:00:00Z','2026-10-18T11:00:00Z',
                   counts={'MEGA_JACKPOT':2,'NONE':18},game='LOTO_6_45')
        prizes={
            'LOTO_5_35':{'102':{'Ngày':'18/10/2026','Giờ':'13:00','Bộ Số':'1,2,3,4,5','ĐB':'8',
                               'Giải Đặc biệt (VNĐ)':'6000000001','counts':{'specialPrize':2}}},
            'LOTO_6_45':{'104':{'Ngày':'18/10/2026','Bộ Số':'1,2,3,4,5,6',
                               'Jackpot (VNĐ)':'9000000001','counts':{'jackpot':1}}}}
        for method in ('all','web'):
            combined=stats.report('alice',game='all',method=method,account_db=self.account,
                                  tracking_db=self.tracking,prizes=prizes,anchor='2026-10-18')['totals']
            separate=[stats.report('alice',game=game,method=method,account_db=self.account,
                                   tracking_db=self.tracking,prizes=rows,anchor='2026-10-18')['totals']
                      for game,rows in prizes.items()]
            self.assertEqual(combined['reward'],sum(row['reward'] for row in separate))
            self.assertEqual(combined['incomplete'],0)
        self.assertEqual(combined['reward'],9002000000)

    def test_jackpot_matches_recorded_draw_and_unknown_is_not_zero(self):
        self.cycle('jp','2026-10-18T03:00:00Z','2026-10-18T06:00:00Z',counts={'LOTTO_JACKPOT':2,'NONE':18})
        prizes={'102':{'Ngày':'18/10/2026','Giờ':'13:00','Bộ Số':'1,2,3,4,5','ĐB':'8','Giải Đặc biệt (VNĐ)':'6000000001','counts':{'specialPrize':2}}}
        report=stats.report('alice',account_db=self.account,tracking_db=self.tracking,prizes=prizes,anchor='2026-10-18')
        self.assertEqual(report['totals']['reward'],3002000000)
        self.assertEqual(report['totals']['incomplete'],0)
        combined=stats.report('alice',method='all',account_db=self.account,tracking_db=self.tracking,prizes=prizes,anchor='2026-10-18')
        # Eight simulated winning tickets share ONE pool with two real tickets.
        self.assertEqual(combined['totals']['reward'],4826000000)
        self.assertEqual(combined['totals']['won'],22)
        prizes['102']['counts']={}
        report=stats.report('alice',account_db=self.account,tracking_db=self.tracking,prizes=prizes,anchor='2026-10-18')
        self.assertEqual(report['totals']['reward'],2000000)
        self.assertEqual(report['totals']['won'],6)
        self.assertEqual(report['totals']['incomplete'],1)
        prizes['102']['counts']={'specialPrize':0}
        prizes['102']['ĐB']='9'
        report=stats.report('alice',account_db=self.account,tracking_db=self.tracking,prizes=prizes,anchor='2026-10-18')
        self.assertEqual(report['totals']['incomplete'],1)

    def test_canonical_metadata_identity(self):
        from unittest.mock import patch
        path=self.work/'loto.csv'
        meta=self.work/'loto.meta.json'
        path.write_text('Kỳ,Ngày,Giờ,Bộ Số,ĐB,Giải Đặc biệt (VNĐ)\n1,18/10/2026,13:00,"1,2,3,4,5",8,6000000000\n',encoding='utf-8')
        evidence={'prizeWinners':{'countsByDraw':{'1':{'identity':'18/10/2026|13:00|1,2,3,4,5|8','counts':{'specialPrize':0}}}}}
        meta.write_text(json.dumps(evidence),encoding='utf-8')
        with patch.object(stats.dp,'get_canonical_csv_read_path',return_value=path), patch.object(stats.dp,'get_canonical_meta_read_path',return_value=meta):
            self.assertEqual(stats.canonical_prizes('LOTO_5_35')['1']['counts'],{'specialPrize':0})
            evidence['prizeWinners']['countsByDraw']['1']['identity']='different'
            meta.write_text(json.dumps(evidence),encoding='utf-8')
            self.assertEqual(stats.canonical_prizes('LOTO_5_35')['1']['counts'],{})
    def test_keno_shared_tier_and_no_duplicate_levels(self):
        with closing(sqlite3.connect(self.tracking)) as db, db:
            db.execute('INSERT INTO keno_effectiveness_cycles VALUES(?,?,?,?,?,?,?)',
                ('k','300000','2026-10-18T03:00:00Z','2026-10-18T03:08:00Z','scored',json.dumps({'main':list(range(1,21))}),json.dumps({'ticketCount':100000,'ticketCountsByLevel':{'8':20,'10':20}})))
            for level in (8,10):
                for method in stats.METHODS:
                    key=f'k{level}{method}'
                    db.execute('INSERT INTO prediction_runs VALUES(?,?,?)',(key,stats.EFFECTIVENESS_SYSTEM_ACTOR,'scored'))
                    db.execute('INSERT INTO keno_effectiveness_predictions VALUES(?,?,?,?)',('k',level,method,key))
                    db.execute('INSERT INTO keno_effectiveness_metrics VALUES(?,?,?,?,?)',('k',level,method,20,json.dumps({'prizeCounts':{f'KENO_{level}_{level if level==8 else 5}':1,'NONE':19}})))
        report=self.report(game='KENO',level=8)
        self.assertEqual(report['totals']['bought'],20)
        self.assertEqual(report['totals']['won'],1)
        self.assertEqual(report['totals']['incomplete'],1)
        report=self.report(game='KENO',level=10)
        self.assertEqual(report['totals']['reward'],20000)
        self.assertEqual(report['totals']['incomplete'],0)
        all_methods=self.report(game='KENO',level=10,method='all')['totals']
        self.assertEqual(all_methods['bought'],80)
        self.assertEqual(all_methods['won'],4)
        self.assertEqual(all_methods['reward'],80000)
        self.assertEqual(self.report(game='KENO',level=8,method='all')['totals']['incomplete'],1)
        # All four portfolios share one cap for this level/draw, using verified
        # actual winners. Never multiply four independent capped payouts.
        from ai import keno_prize_context as kp
        draw=kp.identity('300000',{'main':list(range(1,21))},'2026-10-18T03:08:00Z')
        records={'300000':{'draw':draw,'winnerCounts':{'8':49,'9':0,'10':0}}}
        resolved=stats.report('alice',game='KENO',level=8,method='all',account_db=self.account,
                              tracking_db=self.tracking,prizes=records)['totals']
        self.assertEqual(resolved['reward'],(10000000000//53)*4)
        self.assertEqual(resolved['incomplete'],0)
        before=[p.read_bytes() for p in (self.account,self.tracking)]
        total=self.report(game='all',method='all')['totals']
        base=self.report(method='all')['totals']
        self.assertEqual(total['bought'],base['bought']+160)
        self.assertEqual(total['won'],base['won']+8)
        self.assertEqual(total['reward'],base['reward']+80000)
        self.assertEqual(total['incomplete'],1)
        self.assertEqual(total['deposited'],120000)
        self.assertEqual(total,self.report(game='all',method='all',level=1)['totals'])
        self.assertEqual(before,[p.read_bytes() for p in (self.account,self.tracking)])


if __name__=='__main__': unittest.main()
