"""Minute simulation properties, atomic persistence and bounded read-only OHLC."""
import concurrent.futures
import json
import os
import sqlite3
import subprocess
import unittest
import uuid
from decimal import Decimal
from contextlib import closing
from pathlib import Path
from tests import test_account_balances as fixtures
from tests.test_prize_web import JAVA, JAVAC

HARNESS = '''import java.nio.file.*;import java.time.*;import java.util.*;import java.math.*;
public class MarketHarness {
 public static void main(String[] a) throws Exception {
  LottoWebServer.ExchangeMarket m=new LottoWebServer.ExchangeMarket(Paths.get(a[1]),Paths.get(a[2]),new Random(7));Instant n=Instant.parse(a[3]);
  if(a[0].equals("init")){m.initialize(n);System.out.println("true");}
  if(a[0].equals("tick"))System.out.println(m.tick(n));
  if(a[0].equals("many")){for(int i=1;i<=Integer.parseInt(a[4]);i++)m.tick(n.plusSeconds(i*60));System.out.println("true");}
  if(a[0].equals("report"))System.out.println(m.report("fixture","123456789012",a.length>4?a[4]:"all",n));
  if(a[0].equals("properties")){
   Random r=new Random(19);long v=125000000L;int up=0,down=0;
   for(int i=0;i<20000;i++){int bp=(r.nextInt(100)+1)*(r.nextBoolean()?1:-1);long next=LottoWebServer.ExchangeMarket.nextRate(v,bp);
    if(next<1||next>LottoWebServer.ExchangeMarket.MAX_PRICE||BigInteger.valueOf(Math.abs(next-v)).multiply(BigInteger.valueOf(100)).compareTo(BigInteger.valueOf(v))>0)throw new AssertionError("bound");
    if(next>v)up++;if(next<v)down++;v=next;
   }
   for(long edge:new long[]{1,2,99,100,125000000L,LottoWebServer.ExchangeMarket.MAX_PRICE})for(int bp:new int[]{-100,-1,0,1,100}){
    long next=LottoWebServer.ExchangeMarket.nextRate(edge,bp);if(next<1||next>LottoWebServer.ExchangeMarket.MAX_PRICE||BigInteger.valueOf(Math.abs(next-edge)).multiply(BigInteger.valueOf(100)).compareTo(BigInteger.valueOf(edge))>0)throw new AssertionError("edge");
   }
   if(up<9000||down<9000)throw new AssertionError("directions");System.out.println("true");
  }
 }
}'''


class ExchangeSimulationTests(unittest.TestCase):
    tearDownClass=classmethod(fixtures.AccountBalanceTests.tearDownClass.__func__)
    start_server=classmethod(fixtures.AccountBalanceTests.start_server.__func__)
    request=classmethod(fixtures.AccountBalanceTests.request.__func__)
    login=classmethod(fixtures.AccountBalanceTests.login.__func__)

    @classmethod
    def setUpClass(cls):
        fixtures.AccountBalanceTests.setUpClass.__func__(cls)
        (cls.work/'MarketHarness.java').write_text(HARNESS,encoding='utf-8')
        result=subprocess.run([JAVAC,'-encoding','UTF-8','-cp','build','-d','build','MarketHarness.java'],cwd=cls.work,capture_output=True)
        assert result.returncode==0,result.stderr.decode(errors='replace')

    def setUp(self):
        self.case=Path('cases')/uuid.uuid4().hex
        (self.work/self.case).mkdir(parents=True)
        self.db=self.case/'market.db';self.config=self.case/'policy.json'
        self.policy=dict(version=2,enabled=True,intervalSeconds=60,maxStepBasisPoints=100,
                         appliesTo='chart_preview_only',trackingStartedAt='2026-11-07T12:00:00Z')
        self.write_policy()

    def write_policy(self):
        (self.work/self.config).write_text(json.dumps(self.policy),encoding='utf-8')

    def run_java(self,action,at='2026-11-07T12:00:00Z',extra=None,valid=True):
        command=[JAVA,'-Dfile.encoding=UTF-8','-cp','build'+os.pathsep+'sqlite-jdbc.jar','MarketHarness',action,str(self.db),str(self.config),at]
        if extra is not None: command.append(str(extra))
        result=subprocess.run(command,cwd=self.work,capture_output=True,encoding='utf-8')
        if valid:
            self.assertEqual(result.returncode,0,result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode,0)
        return result

    def snapshot(self):
        with closing(sqlite3.connect(self.work/self.db)) as db:
            return [db.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall() for table in ['market_ticks','market_meta']]

    def test_twenty_thousand_random_steps_and_numeric_edges_within_one_percent(self):
        self.assertTrue(self.run_java('properties'))

    def test_same_minute_duplicate_restart_clock_and_offline_skip(self):
        self.run_java('init');before=self.snapshot()
        self.assertFalse(self.run_java('tick','2026-11-07T12:00:59Z'))
        self.assertEqual(self.snapshot(),before)
        self.assertTrue(self.run_java('tick','2026-11-07T12:01:00Z'))
        first=self.run_java('report','2026-11-07T12:01:01Z')
        self.run_java('init','2026-11-07T12:01:20Z')
        self.assertEqual(self.run_java('report','2026-11-07T12:01:21Z')['numerator'],first['numerator'])
        self.assertFalse(self.run_java('tick','2026-11-07T12:00:00Z'))
        self.run_java('report','2026-11-07T12:00:00Z',valid=False)
        self.assertTrue(self.run_java('tick','2026-11-08T12:01:00Z'))
        self.assertEqual(len(self.snapshot()[0]),3)  # No fabricated 24-hour backfill.

    def test_parallel_processes_generate_only_one_tick_in_a_minute(self):
        self.run_java('init')
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(lambda _:self.run_java('tick','2026-11-07T12:01:00Z'),range(6)))
        self.assertEqual(sum(results),1)
        self.assertEqual(len(self.snapshot()[0]),2)

    def test_failed_tick_rolls_back_price_and_minute_then_retry_succeeds(self):
        self.run_java('init');before=self.snapshot()
        with closing(sqlite3.connect(self.work/self.db)) as db,db:
            db.execute("CREATE TRIGGER fixture_tick_fail BEFORE INSERT ON market_ticks BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        self.run_java('tick','2026-11-07T12:01:00Z',valid=False)
        self.assertEqual(self.snapshot(),before)
        with closing(sqlite3.connect(self.work/self.db)) as db,db:db.execute('DROP TRIGGER fixture_tick_fail')
        self.assertTrue(self.run_java('tick','2026-11-07T12:01:00Z'))
        self.assertEqual(len(self.snapshot()[0]),2)

    def test_read_only_report_ohlc_history_and_bounded_chart(self):
        self.run_java('init');self.run_java('many',extra=720)
        before=self.snapshot()
        report=self.run_java('report','2026-11-08T00:00:01Z')
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(report['historyTotal'],50)
        self.assertEqual(len(report['history']),50)
        self.assertLessEqual(len(report['bars']),362)
        self.assertEqual(len(report['bars']),50)
        self.assertEqual(report['ohlc']['close'],report['rate'])
        self.assertEqual(report['bars'][-1]['close'],report['rate'])
        for prior,current in zip(report['bars'],report['bars'][1:]): self.assertEqual(prior['close'],current['open'])
        self.assertTrue(all(float(r['high'])>=max(float(r['open']),float(r['close'])) and float(r['low'])<=min(float(r['open']),float(r['close'])) for r in report['bars']))
        self.assertTrue(all(abs(float(r['changePercent']))<=1 for r in report['history']))
        self.assertTrue(report['stale'] is False)
        self.assertTrue(self.run_java('report','2026-11-08T00:03:00Z')['stale'])
        with closing(sqlite3.connect(self.work/self.db)) as db:
            for sql in ['DELETE FROM market_ticks','UPDATE market_ticks SET rate_units=1']:
                with self.assertRaises(sqlite3.IntegrityError):db.execute(sql)

    def test_fifty_tick_retention_keeps_exact_oldest_change_and_restart(self):
        self.run_java('init');self.run_java('many',extra=75)
        before=self.snapshot();self.assertEqual(len(before[0]),50)
        report=self.run_java('report','2026-11-07T13:15:01Z')
        with closing(sqlite3.connect(self.work/self.db)) as db:
            previous=int(db.execute("SELECT value FROM market_meta WHERE key='retained_previous_units'").fetchone()[0])
        oldest=report['history'][-1]
        self.assertEqual(Decimal(oldest['change']),Decimal(oldest['rate'])-Decimal(previous)/Decimal(100000000))
        self.assertGreater(report['historyStartedAt'],report['trackingStartedAt'])
        self.run_java('init','2026-11-07T13:15:10Z')
        self.assertEqual(before,self.snapshot())
        self.run_java('tick','2026-11-07T13:16:00Z')
        self.assertEqual(len(self.snapshot()[0]),50)
        self.assertNotIn(before[0][0],self.snapshot()[0])

    def test_missing_invalid_disabled_or_changed_policy_cannot_generate_ticks(self):
        self.run_java('report',valid=False)
        self.assertFalse((self.work/self.db).exists())
        self.run_java('init');before=self.snapshot()
        self.policy['enabled']=False;self.write_policy()
        self.assertFalse(self.run_java('tick','2026-11-07T12:01:00Z'))
        self.assertFalse(self.run_java('report','2026-11-07T12:01:00Z')['enabled'])
        self.assertEqual(self.snapshot(),before)
        for key,value in [('version',9),('maxStepBasisPoints',101),('appliesTo','payments')]:
            original=self.policy[key];self.policy[key]=value;self.write_policy()
            self.run_java('tick','2026-11-07T12:02:00Z',valid=False)
            self.policy[key]=original
        self.policy['enabled']=True;self.policy['trackingStartedAt']='2026-11-07T11:00:00Z';self.write_policy()
        self.run_java('tick','2026-11-07T12:02:00Z',valid=False)
        self.assertEqual(self.snapshot(),before)


if __name__=='__main__':unittest.main()
