"""Internal PayPal rate view: read-only admin API, exact preview, actual Chrome UI."""
import base64
import json
import os
import subprocess
import sqlite3
import time
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from tests import test_account_balances as fixtures
from tests import test_vip_progress as vip_fixtures
from tests.browser_cdp import Browser
from tests.test_prize_web import ROOT, CHROME, JAVA, JAVAC

API='/api/admin/exchange-rate'
RANGES=[('1min',60),('5min',300),('15min',900),('30min',1800),
        ('1h',3600),('3h',10800),('6h',21600),('12h',43200),
        ('1d',86400),('7d',604800),('1m',2592000),('3m',7776000),('all',None)]
VISIBLE_RANGES=[('1h',3600),('3h',10800),('6h',21600),('12h',43200),
                ('1d',86400),('7d',604800),('1m',2592000),('3m',7776000),('all',None)]


class AdminExchangeRateTests(unittest.TestCase):
    tearDownClass=classmethod(fixtures.AccountBalanceTests.tearDownClass.__func__)
    request=classmethod(fixtures.AccountBalanceTests.request.__func__)
    login=classmethod(fixtures.AccountBalanceTests.login.__func__)
    financial_snapshot=vip_fixtures.VipProgressTests.financial_snapshot

    @classmethod
    def setUpClass(cls):
        fixtures.AccountBalanceTests.setUpClass.__func__(cls)

    @classmethod
    def start_server(cls):
        # Real component and API against a private, seeded one-hour market.
        policy=cls.work/'config/paypal-exchange-chart.json'
        if not policy.exists():
            policy.parent.mkdir(exist_ok=True)
            cls.chart_policy=json.loads((ROOT/'config/paypal-exchange-chart.json').read_text(encoding='utf-8'))
            cls.chart_policy['trackingStartedAt']=(datetime.now(timezone.utc)-timedelta(hours=3)).isoformat().replace('+00:00','Z')
            policy.write_text(json.dumps(cls.chart_policy),encoding='utf-8')
        if not (cls.work/'runtime/paypal_exchange.db').exists():
            (cls.work/'SeedMarket.java').write_text('''import java.nio.file.*;import java.time.*;import java.util.*;
public class SeedMarket {public static void main(String[] args)throws Exception {
 LottoWebServer.ExchangeMarket m=new LottoWebServer.ExchangeMarket(Paths.get("runtime/paypal_exchange.db"),Paths.get("config/paypal-exchange-chart.json"),new Random(37));
 Instant start=Instant.now().minusSeconds(3600);m.initialize(start);for(int i=1;i<=59;i++)m.tick(start.plusSeconds(i*60));
}}''',encoding='utf-8')
            subprocess.run([JAVAC,'-encoding','UTF-8','-cp','build','-d','build','SeedMarket.java'],cwd=cls.work,capture_output=True,check=True)
            subprocess.run([JAVA,'-Dfile.encoding=UTF-8','-cp','build'+os.pathsep+'sqlite-jdbc.jar','SeedMarket'],cwd=cls.work,capture_output=True,check=True)
        fixtures.AccountBalanceTests.start_server.__func__(cls)

    def setUp(self):
        self.db=self.work/'runtime/lotto_web.db'
        (self.work/'config/paypal-exchange-chart.json').write_text(json.dumps(self.chart_policy),encoding='utf-8')

    def test_admin_auth_methods_paths_query_and_no_financial_writes(self):
        before=self.financial_snapshot()
        self.assertEqual(self.request(API)[0],401)
        self.assertEqual(self.request(API,cookie=self.member)[0],403)
        self.assertEqual(self.request(API,{},self.admin)[0],405)
        self.assertEqual(self.request(API+'/other',cookie=self.admin)[0],404)
        for query in ['?range=bad','?username=member_fixture','?range=1d&rate=2','?range=1d&accountId=123']:
            self.assertEqual(self.request(API+query,cookie=self.admin)[0],400,query)
        for selected,seconds in RANGES:
            code,data,headers=self.request(API+'?range='+selected,cookie=self.admin)
            self.assertEqual(code,200,data)
            self.assertEqual(headers['Cache-Control'],'no-store')
            self.assertEqual((data['source'],data['fixed'],data['appliesTo']),('internal_simulation',False,'chart_preview_only'))
            self.assertEqual(data['denominator'],'100000000')
            self.assertLessEqual(abs(float(data['changePercent'])),1)
            self.assertEqual(data['historyTotal'],50)
            self.assertEqual((data['historyLimit'],data['historyPageSize']),(50,5))
            self.assertGreater(len(data['bars']),0)
            if seconds is None or seconds>=3600:
                self.assertGreater(len(data['bars']),10)
            self.assertEqual(data['range'],selected)
            self.assertEqual(len(data['history']),50)
            self.assertEqual(data['owner'],'owner_fixture')
            with closing(sqlite3.connect(self.work/'runtime/paypal_exchange.db')) as market:
                for row in data['history']:
                    units=market.execute('SELECT rate_units FROM market_ticks WHERE minute<=(SELECT minute FROM market_ticks WHERE recorded_at=?) ORDER BY minute DESC LIMIT 2',(row['effectiveAt'],)).fetchall()
                    previous=units[1][0] if len(units)>1 else int(market.execute("SELECT value FROM market_meta WHERE key='retained_previous_units'").fetchone()[0])
                    expected=Decimal(units[0][0]-previous)/Decimal(100000000)
                    self.assertEqual(Decimal(row['change']),expected)
        self.assertEqual(before,self.financial_snapshot())

    def test_time_ranges_clamp_to_real_tracking_start(self):
        for selected,seconds in RANGES:
            code,data,_=self.request(API+'?range='+selected,cookie=self.admin)
            self.assertEqual(code,200,data)
            begin=datetime.fromisoformat(data['from'].replace('Z','+00:00'))
            end=datetime.fromisoformat(data['asOf'].replace('Z','+00:00'))
            started=datetime.fromisoformat(data['trackingStartedAt'].replace('Z','+00:00'))
            started=max(started,datetime.fromisoformat(data['historyStartedAt'].replace('Z','+00:00')))
            expected=started if seconds is None else max(started,end-timedelta(seconds=seconds))
            self.assertAlmostEqual((begin-expected).total_seconds(),0,delta=.001)
            self.assertGreaterEqual(begin,started)

    def test_missing_invalid_future_configuration_fails_closed_then_recovers(self):
        path=self.work/'config/paypal-exchange-chart.json'
        original=path.read_text(encoding='utf-8')
        before=self.financial_snapshot()
        for text in ['{}','not json',json.dumps({**self.chart_policy,'version':9}),
                     json.dumps({**self.chart_policy,'trackingStartedAt':'1999-01-01T00:00:00Z'}),
                     json.dumps({**self.chart_policy,'trackingStartedAt':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat().replace('+00:00','Z')})]:
            path.write_text(text,encoding='utf-8')
            self.assertEqual(self.request(API,cookie=self.admin)[0],503,text)
        path.unlink()
        self.assertEqual(self.request(API,cookie=self.admin)[0],503)
        path.write_text(original,encoding='utf-8')
        self.assertEqual(self.request(API,cookie=self.admin)[0],200)
        self.assertEqual(before,self.financial_snapshot())

    @unittest.skipUnless(Path(CHROME).exists(),'Chrome required')
    def test_browser_navigation_chart_controls_conversion_errors_and_mobile(self):
        browser=Browser(CHROME,self.work/'exchange-browser')
        self.addCleanup(browser.close)
        browser.call('Network.enable',page=True)
        browser.call('Network.setCookie',dict(name='LOTTO_AUTH',value=self.admin.split(';')[0].split('=',1)[1],url=self.url),page=True)
        browser.call('Emulation.setDeviceMetricsOverride',dict(width=1440,height=1050,deviceScaleFactor=1,mobile=False),page=True)
        browser.call('Page.navigate',dict(url=self.url+'/admin'),page=True)
        def wait(expression):
            for _ in range(200):
                if browser.value(expression): return
                time.sleep(.05)
            self.fail('Timeout '+expression+'; '+str(browser.value("JSON.stringify({status:document.getElementById('exchangeStatus').textContent,hidden:document.getElementById('adminExchangePane').hidden,title:document.getElementById('adminPageTitle').textContent})")))
        wait("!!window.adminPanel && !document.getElementById('adminPanelSection').hidden && document.getElementById('adminTotalCodes').textContent!=='—'")
        browser.value("document.querySelector('.admin-nav [data-admin-view=exchange]').click()")
        wait("!document.getElementById('exchangeContent').hidden && !!document.querySelector('.exchange-price-line')")
        self.assertEqual(browser.value("document.getElementById('adminPageTitle').textContent"),'Tỉ giá')
        self.assertTrue(browser.value("document.querySelector('.admin-metrics').hidden"))
        self.assertEqual(browser.value("document.getElementById('exchangeMarketBadge').textContent"),'Chốt Tỉ Giá Sau · 00h00 Hàng Ngày')
        self.assertTrue(browser.value("document.getElementById('exchangeNextTick').textContent.includes('Đổi giá')"))
        self.assertEqual(browser.value("[...document.querySelector('.exchange-history thead tr').children].map(x=>x.textContent)"),['Thời điểm','Tỉ giá / 1 VNĐ','+/−','Thay đổi','Ghi nhận'])
        history=browser.value("[...document.getElementById('exchangeHistoryRows').children].map(row=>[...row.children].map(x=>({text:x.textContent,cls:x.className})))")
        self.assertEqual(len(history),5)
        self.assertIn('1–5 / 50',browser.value("document.getElementById('exchangeHistoryCount').textContent"))
        browser.value("document.getElementById('exchangeHistoryNext').click()")
        self.assertIn('6–10 / 50',browser.value("document.getElementById('exchangeHistoryCount').textContent"))
        self.assertEqual(browser.value("document.getElementById('exchangeHistoryRows').children.length"),5)
        for _ in range(8):browser.value("document.getElementById('exchangeHistoryNext').click()")
        self.assertIn('46–50 / 50',browser.value("document.getElementById('exchangeHistoryCount').textContent"))
        self.assertTrue(browser.value("document.getElementById('exchangeHistoryNext').disabled"))
        for _ in range(9):browser.value("document.getElementById('exchangeHistoryPrevious').click()")
        self.assertTrue(browser.value("document.getElementById('exchangeHistoryPrevious').disabled"))
        self.assertTrue(all(len(row)==5 for row in history))
        for index,row in enumerate(history[:-1]):
            parse=lambda value:Decimal(value.replace(' PayPal','').replace('.','').replace(',','.'))
            # Published prices show four decimals; deltas retain all eight.
            delta=parse(row[2]['text'])
            self.assertEqual(row[2]['cls'],row[3]['cls'])
            self.assertEqual(row[2]['cls'],'is-up' if delta>0 else 'is-down' if delta<0 else '')
            self.assertLessEqual(abs(parse(row[1]['text'])-parse(history[index+1][1]['text'])-delta),Decimal('.0001'))
        self.assertEqual(browser.value("[...document.querySelectorAll('[data-exchange-range]')].map(x=>x.dataset.exchangeRange)"),[key for key,_ in VISIBLE_RANGES])
        self.assertIn('60 phút',browser.value("document.querySelector('[data-exchange-range=\"1h\"]').title"))
        for selected,seconds in VISIBLE_RANGES:
            selector='[data-exchange-range="'+selected+'"]'
            browser.value('document.querySelector('+json.dumps(selector)+').click()')
            wait('document.querySelector('+json.dumps(selector)+').getAttribute("aria-pressed")==="true" && !document.getElementById("exchangeContent").hidden')
            self.assertEqual(browser.value("document.querySelectorAll('[data-exchange-range][aria-pressed=true]').length"),1)
            if seconds is not None and seconds<=43200:
                self.assertIn(':',browser.value("document.getElementById('exchangeChartPeriod').textContent"))
        for value,formatted,amount in [('1','1',1),('4','4',4),('20000','20.000',20000),
                                       ('999999999999999999999999','1.000.000.000.000',1000000000000)]:
            browser.value("(()=>{const x=document.getElementById('exchangeConvertInput');x.value="+json.dumps(value)+";x.dispatchEvent(new Event('input',{bubbles:true}))})()")
            self.assertEqual(browser.value("document.getElementById('exchangeConvertInput').value"),formatted)
            units=int(browser.value("document.getElementById('adminExchangePane').dataset.rateUnits"))
            cents=amount*units*100//100000000;fraction=str(cents%100).zfill(2).rstrip('0')
            result=f'{cents//100:,}'.replace(',','.')+(','+fraction if fraction else '')
            self.assertEqual(browser.value("document.getElementById('exchangeConvertResult').textContent"),result)
        browser.value("document.querySelector('[data-exchange-mode=candles]').click()")
        self.assertGreater(browser.value("document.querySelectorAll('.exchange-candle').length"),10)
        self.assertTrue(browser.value("(()=>{const a=[...document.querySelectorAll('.exchange-candle')].slice(-2).map(x=>x.getBBox());return a[0].width<a[1].x-a[0].x})()"))
        self.assertEqual(browser.value("document.querySelectorAll('.exchange-price-line').length"),0)
        browser.value("document.querySelector('[data-exchange-mode=line]').click();document.querySelector('[data-exchange-range=all]').click()")
        wait("document.querySelector('[data-exchange-range=all]').getAttribute('aria-pressed')==='true' && !document.getElementById('exchangeContent').hidden")
        browser.value("document.getElementById('exchangePlot').focus()")
        browser.call('Input.dispatchKeyEvent',dict(type='keyDown',key='ArrowLeft',code='ArrowLeft'),page=True)
        wait("!document.getElementById('exchangeTooltip').hidden")
        self.assertIn('PayPal / VNĐ',browser.value("document.getElementById('exchangeTooltip').textContent"))
        browser.value("document.getElementById('exchangePlot').blur();document.getElementById('exchangeConvertInput').value='100000';document.getElementById('exchangeConvertInput').dispatchEvent(new Event('input'))")
        evidence=ROOT/'runtime/logs/exchange_retention_20261109';evidence.mkdir(parents=True,exist_ok=True)
        metrics=[]
        for width in [1440,1024,390,320]:
            browser.call('Emulation.setDeviceMetricsOverride',dict(width=width,height=1050 if width>500 else 900,deviceScaleFactor=1,mobile=width<500),page=True)
            time.sleep(.08)
            measure=browser.value("(()=>{const p=document.getElementById('adminExchangePane'),r=p.getBoundingClientRect(),s=document.getElementById('adminPanelSection');return {deviceWidth:innerWidth,left:r.left,right:r.right,scroll:p.scrollWidth,client:p.clientWidth,body:document.documentElement.scrollWidth,root:s.scrollWidth}})()")
            metrics.append(measure)
            self.assertEqual(measure['deviceWidth'],width,measure)
            self.assertGreaterEqual(measure['left'],0,measure)
            self.assertLessEqual(measure['right'],width,measure)
            self.assertLessEqual(measure['scroll'],measure['client']+1,measure)
            countdown=browser.value("(()=>{const t=document.getElementById('exchangeNextTick'),r=t.getBoundingClientRect(),p=document.getElementById('exchangePlot').getBoundingClientRect();return {parent:t.parentElement.id,count:document.querySelectorAll('#exchangeNextTick').length,top:r.top-p.top,right:p.right-r.right,bottom:r.bottom-p.top,labelTop:document.querySelector('#exchangeChart .exchange-axis').getBoundingClientRect().top-p.top}})()")
            self.assertEqual(countdown['parent'],'exchangePlot',countdown)
            self.assertEqual(countdown['count'],1,countdown)
            self.assertAlmostEqual(countdown['top'],4,delta=1)
            self.assertAlmostEqual(countdown['right'],12,delta=1)
            self.assertGreaterEqual(countdown['labelTop']-countdown['bottom'],12,countdown)
            measure['countdown']=countdown
            self.assertTrue(browser.value("[...document.querySelectorAll('[data-exchange-range]')].every(x=>{const r=x.getBoundingClientRect();return r.width>0&&r.left>=0&&r.right<=innerWidth})"),measure)
            if width in [1440,390,320]:
                image=browser.call('Page.captureScreenshot',dict(format='png'),page=True)
                (evidence/f'exchange-{width}.png').write_bytes(base64.b64decode(image['data']))
        browser.call('Emulation.setDeviceMetricsOverride',dict(width=1440,height=1050,deviceScaleFactor=1,mobile=False),page=True)
        browser.value("document.querySelector('[data-exchange-mode=candles]').click()")
        image=browser.call('Page.captureScreenshot',dict(format='png'),page=True)
        (evidence/'exchange-candles.png').write_bytes(base64.b64decode(image['data']))
        browser.value("document.querySelector('[data-exchange-mode=line]').click()")
        browser.value("document.body.classList.add('light-theme')")
        image=browser.call('Page.captureScreenshot',dict(format='png'),page=True)
        (evidence/'exchange-light.png').write_bytes(base64.b64decode(image['data']))
        (evidence/'viewports.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
        # Errors clear stale prices; retry restores authoritative state.
        browser.value("window.exchangeRealFetch=window.fetch;window.fetch=(...a)=>String(a[0]).includes('/api/admin/exchange-rate')?Promise.reject(new Error('fixture')):exchangeRealFetch(...a);document.getElementById('exchangeRefresh').click()")
        wait("!document.getElementById('exchangeRetry').hidden")
        self.assertTrue(browser.value("document.getElementById('exchangeContent').hidden"))
        browser.value("window.fetch=exchangeRealFetch;document.getElementById('exchangeRetry').click()")
        wait("!document.getElementById('exchangeContent').hidden")
        # A late response after logout must not repopulate admin data.
        browser.value("window.fetch=(...a)=>String(a[0]).includes('/api/admin/exchange-rate')?new Promise(resolve=>setTimeout(()=>exchangeRealFetch(a[0],{...a[1],signal:undefined}).then(resolve),300)):exchangeRealFetch(...a);document.getElementById('exchangeRefresh').click();window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:false}}))")
        time.sleep(.5)
        self.assertTrue(browser.value("document.getElementById('exchangeContent').hidden && document.getElementById('exchangeHistoryRows').children.length===0"))


if __name__=='__main__':unittest.main()
