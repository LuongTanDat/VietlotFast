"""Vietnam-midnight pricing, immutable quotes and real payment APIs on private data."""
import concurrent.futures
import json
import os
import sqlite3
import subprocess
import unittest
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from tests import test_account_balances as fixtures
from tests import test_vnpay_payments as vnpay
from tests.test_prize_web import JAVA, JAVAC

HARNESS='''import java.nio.file.*;import java.time.*;import java.util.*;
public class DailyRateHarness {
 public static void main(String[] a)throws Exception {
  Path root=Paths.get(a[1]);Instant now=Instant.parse(a[2]);
  LottoWebServer.ExchangeMarket m=new LottoWebServer.ExchangeMarket(root.resolve("market.db"),root.resolve("market.json"),new Random(37));
  LottoWebServer.DailyTopupRates d=new LottoWebServer.DailyTopupRates(root.resolve("daily.db"),root.resolve("daily.json"),m);
  if(a[0].equals("init")){m.initialize(now);System.out.println("true");}
  if(a[0].equals("tick"))System.out.println(m.tick(now));
  if(a[0].equals("quote"))System.out.println(d.quote(now).json());
  if(a[0].equals("guardedTicks")){
   m.retentionGuard=at->d.quote(at);m.initialize(now);
   for(int i=1;i<=720;i++)m.tick(now.plusSeconds(i*60));
   System.out.println(d.quote(now.plusSeconds(43200)).json());
  }
  if(a[0].equals("calc"))System.out.println(new LottoWebServer.DailyTopupRates.Quote("2026-11-08",Long.parseLong(a[3]),"","","fixture").base(Long.parseLong(a[4])));
 }
}'''


def policy(at):
    return dict(version=1,timeZone='Asia/Ho_Chi_Minh',activatedAt=at,
                source='last_market_tick_before_midnight',initialRate='1.25',orderRateLock='created_at')


class DailyTopupRateTests(unittest.TestCase):
    tearDownClass=classmethod(fixtures.AccountBalanceTests.tearDownClass.__func__)
    start_server=classmethod(fixtures.AccountBalanceTests.start_server.__func__)
    request=classmethod(fixtures.AccountBalanceTests.request.__func__)
    login=classmethod(fixtures.AccountBalanceTests.login.__func__)

    @classmethod
    def setUpClass(cls):
        fixtures.AccountBalanceTests.setUpClass.__func__(cls)
        (cls.work/'DailyRateHarness.java').write_text(HARNESS,encoding='utf-8')
        subprocess.run([JAVAC,'-encoding','UTF-8','-cp','build','-d','build','DailyRateHarness.java'],cwd=cls.work,capture_output=True,check=True)

    def setUp(self):
        self.case=Path('daily-cases')/uuid.uuid4().hex
        folder=self.work/self.case;folder.mkdir(parents=True)
        self.policy=policy('2026-11-07T12:00:00Z')
        (folder/'daily.json').write_text(json.dumps(self.policy),encoding='utf-8')
        (folder/'market.json').write_text(json.dumps(dict(version=2,enabled=True,intervalSeconds=60,maxStepBasisPoints=100,appliesTo='chart_preview_only',trackingStartedAt='2026-11-07T12:00:00Z')),encoding='utf-8')

    def run_java(self,action,at='2026-11-07T12:00:00Z',*extra,valid=True):
        result=subprocess.run([JAVA,'-Dfile.encoding=UTF-8','-cp','build'+os.pathsep+'sqlite-jdbc.jar','DailyRateHarness',action,str(self.case),at,*map(str,extra)],cwd=self.work,capture_output=True,encoding='utf-8')
        if not valid:
            self.assertNotEqual(result.returncode,0);return result.stderr
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(result.stdout)

    def snapshot(self):
        with closing(sqlite3.connect(self.work/self.case/'daily.db')) as db:
            return db.execute('SELECT * FROM daily_topup_rates ORDER BY day').fetchall()

    def test_midnight_uses_last_prior_tick_and_holds_for_entire_day(self):
        self.run_java('init');self.run_java('tick','2026-11-07T16:59:59Z')
        self.run_java('tick','2026-11-07T17:00:00Z')
        before=self.run_java('quote','2026-11-07T16:59:59.999999999Z')
        after=self.run_java('quote','2026-11-07T17:00:00Z')
        self.assertEqual((before['day'],before['rate']),('2026-11-07','1.25'))
        self.assertEqual((after['day'],after['sourceAt']),('2026-11-08','2026-11-07T16:59:59Z'))
        with closing(sqlite3.connect(self.work/self.case/'market.db')) as db:
            expected=db.execute("SELECT rate_units FROM market_ticks WHERE recorded_at='2026-11-07T16:59:59Z'").fetchone()[0]
        self.assertEqual(after['numerator'],str(expected))
        self.assertEqual(after,self.run_java('quote','2026-11-08T16:59:59.999999999Z'))
        self.assertEqual(after['nextCloseAt'],'2026-11-08T17:00:00Z')

    def test_restart_offline_catchup_and_immutable_history(self):
        self.run_java('init');self.run_java('tick','2026-11-07T16:59:00Z')
        quote=self.run_java('quote','2026-11-10T00:00:00Z')
        rows=self.snapshot();self.assertEqual(len(rows),4)
        self.assertTrue(all(row[1]==int(quote['numerator']) for row in rows[1:]))
        self.assertEqual(quote,self.run_java('quote','2026-11-10T05:00:00Z'))
        self.assertEqual(rows,self.snapshot())
        self.run_java('quote','2026-11-09T12:00:00Z',valid=False)
        with closing(sqlite3.connect(self.work/self.case/'daily.db')) as db:
            for sql in ['DELETE FROM daily_topup_rates','UPDATE daily_topup_rates SET rate_units=1']:
                with self.assertRaises(sqlite3.IntegrityError):db.execute(sql)

    def test_six_processes_close_once_without_altering_market(self):
        self.run_java('init');self.run_java('tick','2026-11-07T16:59:00Z')
        with closing(sqlite3.connect(self.work/self.case/'market.db')) as db:before=db.execute('SELECT * FROM market_ticks').fetchall()
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(lambda _:self.run_java('quote','2026-11-07T17:00:01Z'),range(6)))
        self.assertTrue(all(row==results[0] for row in results))
        self.assertEqual(len(self.snapshot()),2)
        with closing(sqlite3.connect(self.work/self.case/'market.db')) as db:self.assertEqual(before,db.execute('SELECT * FROM market_ticks').fetchall())

    def test_missing_invalid_or_changed_policy_and_missing_source_fail_closed(self):
        self.run_java('quote');before=self.snapshot();path=self.work/self.case/'daily.json'
        for value in ['not json',json.dumps({**self.policy,'version':9}),json.dumps({**self.policy,'activatedAt':'2026-11-06T12:00:00Z'})]:
            path.write_text(value,encoding='utf-8');self.run_java('quote',valid=False);self.assertEqual(self.snapshot(),before)
        path.unlink();self.run_java('quote',valid=False);self.assertEqual(self.snapshot(),before)
        path.write_text(json.dumps(self.policy),encoding='utf-8')
        self.run_java('quote','2026-11-07T17:00:00Z',valid=False)
        self.assertEqual(self.snapshot(),before)
        self.run_java('init');self.assertEqual(self.run_java('quote','2026-11-07T17:00:00Z')['day'],'2026-11-08')

    def test_failed_close_rolls_back_all_rows_then_retries(self):
        self.run_java('init');self.run_java('quote');before=self.snapshot()
        with closing(sqlite3.connect(self.work/self.case/'daily.db')) as db,db:
            db.execute("CREATE TRIGGER fixture_fail BEFORE INSERT ON daily_topup_rates WHEN NEW.day='2026-11-09' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        self.run_java('quote','2026-11-09T12:00:00Z',valid=False)
        self.assertEqual(self.snapshot(),before)
        with closing(sqlite3.connect(self.work/self.case/'daily.db')) as db,db:db.execute('DROP TRIGGER fixture_fail')
        self.run_java('quote','2026-11-09T12:00:00Z');self.assertEqual(len(self.snapshot()),3)

    def test_daily_close_survives_pruning_the_source_tick(self):
        result=self.run_java('guardedTicks')
        self.assertEqual((result['day'],result['sourceAt']),('2026-11-08','2026-11-07T16:59:00Z'))
        with closing(sqlite3.connect(self.work/self.case/'market.db')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM market_ticks').fetchone()[0],50)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM market_ticks WHERE recorded_at=?',(result['sourceAt'],)).fetchone()[0],0)
        self.assertEqual(result,self.run_java('quote','2026-11-08T01:00:00Z'))

    def test_whole_paypal_round_half_up_is_exact(self):
        self.assertEqual(self.run_java('calc','2026-11-07T12:00:00Z',150000000,3),5)
        self.assertEqual(self.run_java('calc','2026-11-07T12:00:00Z',133995123,50000),66998)
        self.assertEqual(self.run_java('calc','2026-11-07T12:00:00Z',9007199254740991,100000000),9007199254740991)


class DailyTopupAPITests(unittest.TestCase):
    tearDownClass=classmethod(fixtures.AccountBalanceTests.tearDownClass.__func__)
    request=classmethod(fixtures.AccountBalanceTests.request.__func__)
    login=classmethod(fixtures.AccountBalanceTests.login.__func__)
    configure=vnpay.VnpayBackendTests.configure
    signed=vnpay.VnpayBackendTests.signed

    @classmethod
    def setUpClass(cls):
        fixtures.AccountBalanceTests.setUpClass.__func__(cls)

    @classmethod
    def start_server(cls):
        folder=cls.work/'config';folder.mkdir(exist_ok=True)
        policyPath=folder/'paypal-topup-rates.json'
        if not policyPath.exists():
            now=datetime.now(timezone.utc);stamp=lambda at:at.isoformat().replace('+00:00','Z')
            cls.daily_policy=policy(stamp(now-timedelta(days=2)))
            policyPath.write_text(json.dumps(cls.daily_policy),encoding='utf-8')
            chart=dict(version=2,enabled=True,intervalSeconds=60,maxStepBasisPoints=100,appliesTo='chart_preview_only',trackingStartedAt=stamp(now-timedelta(days=3)))
            chartPath=folder/'paypal-exchange-chart.json';chartPath.write_text(json.dumps(chart),encoding='utf-8')
            (cls.work/'SeedDaily.java').write_text('''import java.nio.file.*;import java.time.*;import java.util.*;
public class SeedDaily{public static void main(String[] a)throws Exception{
 LottoWebServer.ExchangeMarket m=new LottoWebServer.ExchangeMarket(Paths.get("runtime/paypal_exchange.db"),Paths.get("config/paypal-exchange-chart.json"),new Random(37));
 Instant now=Instant.now(),boundary=now.atZone(ZoneId.of("Asia/Ho_Chi_Minh")).toLocalDate().atStartOfDay(ZoneId.of("Asia/Ho_Chi_Minh")).toInstant();
 m.initialize(now.minusSeconds(172800));m.tick(boundary.minusSeconds(60));m.tick(now);
}}''',encoding='utf-8')
            subprocess.run([JAVAC,'-encoding','UTF-8','-cp','build','-d','build','SeedDaily.java'],cwd=cls.work,capture_output=True,check=True)
            subprocess.run([JAVA,'-Dfile.encoding=UTF-8','-cp','build'+os.pathsep+'sqlite-jdbc.jar','SeedDaily'],cwd=cls.work,capture_output=True,check=True)
            chart['enabled']=False;chartPath.write_text(json.dumps(chart),encoding='utf-8')
        fixtures.AccountBalanceTests.start_server.__func__(cls)

    def setUp(self):
        self.configure(enabled=True)
        (self.work/'config/paypal-topup-rates.json').write_text(json.dumps(self.daily_policy),encoding='utf-8')
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db,db:
            db.execute('DELETE FROM manual_topup_details');db.execute('DELETE FROM payment_orders')
            db.execute("UPDATE stores SET store_json='{}'")

    def draft(self,**extra):
        result=dict(mode='account-id',amount=50000,requestId=uuid.uuid4().hex,rateDay=datetime.now(timezone(timedelta(hours=7))).date().isoformat())
        result.update(extra);return result

    def test_rate_snapshot_exact_credit_stale_day_and_late_approval(self):
        code,data,_=self.request('/api/payments/manual',cookie=self.member);self.assertEqual(code,200,data)
        rate=data['topupRate'];self.assertEqual(rate['source'],'market_close')
        current=self.request('/api/payments/vnpay/config',cookie=self.member)[1]['topupRate'];self.assertEqual(rate,current)
        form=self.draft(rateDay=rate['day'],credit=999999999,rate='999')
        code,data,_=self.request('/api/payments/manual',form,self.member);self.assertEqual(code,200,data);order=data['order']
        base=int((Decimal(50000)*Decimal(rate['rate'])).quantize(Decimal(1),rounding=ROUND_HALF_UP))
        bonus=int((Decimal(base)/100).quantize(Decimal(1),rounding=ROUND_HALF_UP))
        self.assertEqual((order['baseCredit'],order['bonusCredit'],order['credit']),(base,bonus,base+bonus))
        self.assertEqual(order['exchangeRate'],rate)
        # An idempotent retry keeps its original receipt even with a stale day.
        retry=self.request('/api/payments/manual',{**form,'rateDay':'1999-01-01'},self.member)
        self.assertEqual(retry[0],200,retry[1]);self.assertEqual(retry[1]['order'],order)
        self.assertEqual(self.request('/api/payments/manual',self.draft(rateDay='1999-01-01'),self.member)[0],409)
        self.assertEqual(self.request('/api/payments/manual',self.draft(rateDay=''),self.member)[0],409)
        # A policy outage must never block settlement of already-quoted orders.
        (self.work/'config/paypal-topup-rates.json').unlink()
        self.assertEqual(self.request('/api/payments/manual',self.draft(),self.member)[0],503)
        review=dict(id=order['id'],action='approve',reviewNote='')
        for _ in range(2):self.assertEqual(self.request('/api/admin/deposits/review',review,self.admin)[0],200)
        self.assertEqual(self.request('/api/store',cookie=self.member)[1]['store']['paypalBalance'],order['credit'])
        self.assertEqual(self.request('/api/admin/deposits?status=PAID',cookie=self.admin)[1]['orders'][0]['exchangeRate'],rate)

    def test_concurrent_manual_retries_freeze_one_order_and_snapshot_is_immutable(self):
        form=self.draft()
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            replies=list(pool.map(lambda _:self.request('/api/payments/manual',form,self.member),range(6)))
        self.assertTrue(all(reply[0]==200 for reply in replies),replies)
        self.assertEqual(len({reply[1]['order']['id'] for reply in replies}),1)
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM payment_orders').fetchone()[0],1)
            with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE payment_orders SET rate_json='{}'")

    def test_vnpay_callback_credits_frozen_daily_quote_once(self):
        form=dict(amount=50000,requestId=uuid.uuid4().hex,credit=999999999,rateDay=datetime.now(timezone(timedelta(hours=7))).date().isoformat())
        code,data,_=self.request('/api/payments/vnpay/orders',form,self.member);self.assertEqual(code,200,data);order=data['order']
        self.assertEqual(order['exchangeRate']['source'],'market_close')
        self.assertEqual(self.request('/api/payments/vnpay/orders',{**form,'rateDay':'1999-01-01'},self.member)[1]['order'],order)
        path="/api/payments/vnpay/ipn?"+self.signed(order)
        for _ in range(2):self.assertEqual(self.request(path)[1]['RspCode'],'00' if _==0 else '02')
        self.assertEqual(self.request('/api/store',cookie=self.member)[1]['store']['paypalBalance'],order['credit'])

    def test_bad_policy_blocks_new_quotes_and_orders_without_financial_writes(self):
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db:before=db.execute('SELECT * FROM stores ORDER BY username').fetchall()
        (self.work/'config/paypal-topup-rates.json').write_text('{"version":999}',encoding='utf-8')
        self.assertEqual(self.request('/api/payments/vnpay/config',cookie=self.member)[0],503)
        self.assertEqual(self.request('/api/payments/manual',self.draft(),self.member)[0],503)
        self.assertEqual(self.request('/api/payments/vnpay/orders',dict(amount=50000,requestId=uuid.uuid4().hex),self.member)[0],503)
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db:
            self.assertEqual(before,db.execute('SELECT * FROM stores ORDER BY username').fetchall())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM payment_orders').fetchone()[0],0)


if __name__=='__main__':unittest.main()
