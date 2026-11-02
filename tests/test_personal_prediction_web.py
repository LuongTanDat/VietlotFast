"""Authenticated billing, real prediction engine and private browser controls."""
import csv
from concurrent.futures import ThreadPoolExecutor
import json
import random
import shutil
import sqlite3
import time
import urllib.error
import urllib.request
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.test_account_balances import AccountBalanceTests
from tests.test_prize_web import ROOT, CHROME
from tests.browser_cdp import Browser


class PersonalPredictionWebTests(AccountBalanceTests):
    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.log.close()
        assert cls.work.resolve().is_relative_to((ROOT/'runtime').resolve())
        for attempt in range(40):
            try:
                cls.temp.cleanup()
                return
            except PermissionError:
                if attempt == 39: raise
                time.sleep(.25)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        (cls.work / 'config').mkdir(exist_ok=True)
        shutil.copy2(ROOT / 'config/tracking-bao-packing-v2.json', cls.work / 'config/tracking-bao-packing-v2.json')
        shutil.copytree(ROOT/'ai', cls.work/'ai', ignore=shutil.ignore_patterns('__pycache__', 'models', 'standalone_predictors'))
        shutil.copytree(ROOT/'backend', cls.work/'backend', ignore=shutil.ignore_patterns('__pycache__', 'bin', 'lib', '*.java'))
        canonical = cls.work/'data/canonical/mega_6_45_all_day.csv'
        canonical.parent.mkdir(parents=True)
        now = datetime.now(timezone(timedelta(hours=7)))
        day, days = now.date(), []
        while len(days) < 70:
            if day.weekday() in (2,4,6) and datetime.combine(day, datetime.min.time(), now.tzinfo).replace(hour=18) < now:
                days.append(day)
            day -= timedelta(days=1)
        rng = random.Random(65045)
        with canonical.open('w', encoding='utf-8', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(['Kỳ','Ngày','Giờ','Bộ Số'])
            for index, day in enumerate(reversed(days)):
                writer.writerow([index+1,day.strftime('%d/%m/%Y'),'18:00',','.join(map(str,sorted(rng.sample(range(1,46),6))))])

    def test_paid_private_predictions_api_and_browser(self):
        for cookie in (None, self.admin, self.member):
            headers = {'Cookie': cookie} if cookie else {}
            request = urllib.request.Request(self.url+'/api/ml/algorithm-lab', headers=headers)
            with self.assertRaises(urllib.error.HTTPError) as missing:
                urllib.request.urlopen(request, timeout=10)
            self.assertEqual(missing.exception.code,404)
        settings = '/api/ml/effectiveness-settings'
        report = '/api/ml/effectiveness?type=LOTO_6_45'
        cycle = '/api/ml/effectiveness-cycle'
        self.assertEqual(self.request(settings, {'type':'LOTO_6_45','enabled':'true','ticketCount':'2'})[0],401)
        code, data, _ = self.request(settings, {'type':'LOTO_6_45','enabled':'true','ticketCount':'2','owner':'owner_fixture'}, self.member)
        self.assertEqual(code,200,data)
        self.assertEqual(data['billing']['owner'],'member_fixture')
        self.assertEqual(data['billing']['totalPayPal'],80000)
        self.assertTrue(data['canManage'])
        # Empty wallet cannot generate or get a free portfolio.
        code, data, _ = self.request(cycle, {'type':'LOTO_6_45','paypalCost':'0'}, self.member)
        self.assertEqual(code,400,data)
        self.assertIn('Không đủ PayPal',data['message'])
        self.assertEqual(self.request(report,cookie=self.member)[1]['counts']['total'],0)
        code, data, _ = self.request('/api/admin/update-assets', {'username':'member_fixture','diamond':'0','paypal':'200000'}, self.admin)
        self.assertEqual(code,200,data)
        code, data, _ = self.request(cycle, {'type':'LOTO_6_45','owner':'owner_fixture'}, self.member)
        self.assertEqual(code,200,data)
        self.assertEqual(data['status'],'locked')
        self.assertEqual(data['billing']['balance'],120000)
        self.assertEqual(data['billing']['charges'][0]['status'],'charged')
        first_id = data['cycleId']
        code, repeated, _ = self.request(cycle, {'type':'LOTO_6_45'}, self.member)
        self.assertEqual(code,200,repeated)
        self.assertEqual(repeated['status'],'already_locked')
        self.assertEqual(repeated['billing']['balance'],120000)
        self.assertEqual(len(repeated['billing']['charges']),1)
        member = self.request(report,cookie=self.member)[1]
        self.assertEqual(member['counts']['total'],1)
        self.assertEqual(self.request(report,cookie=self.admin)[1]['counts']['total'],0)
        prediction = member['cycles'][0]['methods']['web']['predictionId']
        self.assertEqual(self.request('/api/ml/effectiveness-tickets?type=LOTO_6_45&predictionId='+prediction,cookie=self.admin)[0],400)
        self.assertEqual(self.request('/api/ml/effectiveness-export?type=LOTO_6_45&cycleId='+first_id,cookie=self.admin)[0],400)
        statistics = '/api/account/statistics?type=LOTO_6_45&method=all&period=all&date='+datetime.now(timezone(timedelta(hours=7))).date().isoformat()+'&level=10'
        self.assertEqual(self.request(statistics,cookie=self.member)[1]['totals']['bought'],8)
        self.assertEqual(self.request(statistics,cookie=self.admin)[1]['totals']['bought'],0)
        # Client store writes cannot restore the spent balance.
        self.assertEqual(self.request('/api/store', {'store':json.dumps({'paypalBalance':200000,'walletVersion':999})}, self.member)[0],200)
        self.assertEqual(self.request(report,cookie=self.member)[1]['billing']['balance'],120000)
        # Read/export/disable do not charge. Admin lab permissions stay separate.
        self.assertEqual(self.request(settings, {'type':'LOTO_6_45','enabled':'false','ticketCount':'2'}, self.member)[0],200)
        code, keno, _ = self.request(settings, {'type':'KENO','enabled':'false','ticketCount':'324632'}, self.member)
        self.assertEqual(code,200,keno)
        self.assertEqual(keno['settings']['maxTicketCount'],324632)
        self.assertEqual(keno['billing']['totalTickets'],9431296)
        self.assertEqual(keno['billing']['totalPayPal'],94312960000)
        self.assertEqual(self.request(settings, {'type':'KENO','enabled':'false','ticketCount':'324633'}, self.member)[0],400)
        code, loto, _ = self.request(settings, {'type':'LOTO_5_35','enabled':'false','ticketCount':'324632'}, self.member)
        self.assertEqual(code,200,loto)
        self.assertEqual(loto['settings']['maxTicketCount'],324632)
        self.assertEqual(loto['billing']['totalTickets'],1298528)
        self.assertEqual(loto['billing']['totalPayPal'],12985280000)
        self.assertEqual(self.request(settings, {'type':'LOTO_5_35','enabled':'false','ticketCount':'324633'}, self.member)[0],400)
        if Path(CHROME).exists():
            browser = Browser(CHROME,self.work/'paid-prediction-ui')
            def wait(expression):
                for _ in range(160):
                    if browser.value(expression): return
                    time.sleep(.05)
                self.fail('Browser timeout: '+expression+' '+str(browser.value("({ready:document.readyState, auth:document.getElementById('authMsg')?.textContent, errors:window.paidErrors, user:typeof currentUser==='undefined'?'undefined':currentUser})")))
            try:
                browser.call('Page.enable',page=True)
                browser.call('Network.enable',page=True)
                browser.call('Page.addScriptToEvaluateOnNewDocument',{'source':"window.paidErrors=[];addEventListener('error',e=>paidErrors.push(e.message));addEventListener('unhandledrejection',e=>paidErrors.push(String(e.reason)))"},page=True)
                browser.call('Page.addScriptToEvaluateOnNewDocument',{'source':"const paidFetch=window.fetch;window.fetch=(input,options)=>{const url=new URL(typeof input==='string'?input:input.url,location.href);if(url.pathname.startsWith('/api/live-'))return Promise.resolve(new Response(JSON.stringify({ok:true,results:[],rows:[],history:[],meta:{}}),{headers:{'Content-Type':'application/json'}}));return paidFetch(input,options)}"},page=True)
                browser.call('Network.setCookie',{'name':'LOTTO_AUTH','value':self.member.split('=',1)[1].split(';',1)[0], 'url':self.url},page=True)
                browser.call('Page.navigate',{'url':self.url},page=True)
                wait("!!window.VietlottEffectiveness && typeof currentUser!=='undefined' && currentUser==='member_fixture'")
                browser.value("window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:true}}));window.VietlottEffectiveness.activate(true);document.getElementById('effectivenessType').value='LOTO_6_45';document.getElementById('effectivenessType').dispatchEvent(new Event('change'))")
                wait("!document.getElementById('effectivenessSettings').hidden && !document.getElementById('effectivenessSettings').disabled")
                browser.value("document.getElementById('effectivenessSettings').click()")
                self.assertTrue(browser.value("document.getElementById('effectivenessAdmin').open"))
                self.assertTrue(browser.value("!document.getElementById('effectivenessLab')"))
                browser.value("document.getElementById('effectivenessTicketCount').value='3';document.getElementById('effectivenessTicketCount').dispatchEvent(new Event('input'))")
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').value"),'3')
                self.assertTrue(browser.value("!document.getElementById('effectivenessTicketHint') && !document.getElementById('effectivenessBilling') && !document.querySelector('#effectivenessAdmin .effectiveness-admin-copy')"))
                self.assertEqual(self.request(report,cookie=self.member)[1]['billing']['balance'],120000)
                browser.value("document.getElementById('effectivenessType').value='KENO';document.getElementById('effectivenessType').dispatchEvent(new Event('change'))")
                wait("document.getElementById('effectivenessAdminSummary').textContent.includes('324.632') && !document.getElementById('effectivenessSettings').disabled")
                browser.value("document.getElementById('effectivenessSettings').click()")
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').max"),'324632')
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketMax').textContent"),'Tối đa 324.632')
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').value"),'324.632')
                browser.value("document.getElementById('effectivenessType').value='LOTO_5_35';document.getElementById('effectivenessType').dispatchEvent(new Event('change'))")
                wait("!document.getElementById('effectivenessSettings').disabled && document.getElementById('effectivenessAdminSummary').textContent.includes('324.632')")
                browser.value("document.getElementById('effectivenessSettings').click()")
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').max"),'324632')
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketMax').textContent"),'Tối đa 324.632')
                browser.value("document.getElementById('effectivenessTicketCount').value='1000000';document.getElementById('effectivenessTicketCount').dispatchEvent(new Event('input'))")
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').value"),'324.632')
                browser.value("document.getElementById('effectivenessTicketCount').value='999999';document.getElementById('effectivenessTicketCount').dispatchEvent(new Event('input'))")
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').value"),'324.632')
            finally:
                browser.close()
        # Another process holds the wallet write lock while the browser saves.
        # The save must preserve the balance read AFTER that process commits.
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db', isolation_level=None)) as db, ThreadPoolExecutor(max_workers=1) as workers:
            db.execute('BEGIN IMMEDIATE')
            saving = workers.submit(self.request, '/api/store', {'store':'{"paypalBalance":200000,"walletVersion":999,"theme":"light"}'}, self.member)
            time.sleep(.15)
            wallet = json.loads(db.execute("SELECT store_json FROM stores WHERE username='member_fixture'").fetchone()[0])
            wallet['paypalBalance'] = 99999
            wallet['walletVersion'] += 1
            db.execute('UPDATE stores SET store_json=? WHERE username=?', (json.dumps(wallet),'member_fixture'))
            db.execute('COMMIT')
            self.assertEqual(saving.result(timeout=10)[0],200)
        self.assertEqual(self.request(report,cookie=self.member)[1]['billing']['balance'],99999)
        code, data, _ = self.request('/api/admin/rename-user', {'username':'member_fixture','newUsername':'renamed_fixture'}, self.admin)
        self.assertEqual(code,200,data)
        code, data, headers = self.request('/api/login', {'username':'renamed_fixture','password':'fixture_password'})
        self.assertEqual(code,200,data)
        renamed_cookie = headers['Set-Cookie']
        renamed = self.request(report,cookie=renamed_cookie)[1]
        self.assertEqual(renamed['cycles'][0]['cycleId'],first_id)
        self.assertEqual(renamed['billing']['balance'],99999)
        self.assertEqual(self.request('/api/admin/delete-user', {'username':'renamed_fixture'}, self.admin)[0],200)
        self.assertEqual(self.request('/api/register', {'username':'renamed_fixture','password':'fixture_password'})[0],200)
        _, _, headers = self.request('/api/login', {'username':'renamed_fixture','password':'fixture_password'})
        fresh = self.request(report,cookie=headers['Set-Cookie'])[1]
        self.assertEqual(fresh['counts']['total'],0)
        self.assertEqual(fresh['billing']['balance'],0)
        self.assertEqual(fresh['billing']['charges'],[])
