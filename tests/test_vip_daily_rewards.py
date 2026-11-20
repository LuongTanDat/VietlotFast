"""Daily VIP chest: authoritative rank, atomic card credit, immutable daily receipt."""
import base64
import concurrent.futures
import json
import shutil
import sqlite3
import subprocess
import time
import unittest
import urllib.error
import urllib.request
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from tests import test_vip_progress as fixtures
from tests.browser_cdp import Browser
from tests.test_prize_web import ROOT, JAVA, JAVAC, CHROME

API = '/api/account/vip-daily-reward'
REWARDS = [100,500,1000,2500,5000,10000,25000,50000,100000,250000,500000,
           1000000,2500000,5000000,10000000,25000000]


class VipDailyRewardTests(unittest.TestCase):
    tearDownClass = classmethod(fixtures.VipProgressTests.tearDownClass.__func__)
    start_server = classmethod(fixtures.VipProgressTests.start_server.__func__)
    request = classmethod(fixtures.VipProgressTests.request.__func__)
    login = classmethod(fixtures.VipProgressTests.login.__func__)
    charge = fixtures.VipProgressTests.charge
    financial_snapshot = fixtures.VipProgressTests.financial_snapshot

    @classmethod
    def setUpClass(cls):
        fixtures.VipProgressTests.setUpClass.__func__(cls)

    def setUp(self):
        self.db = self.work/'runtime/lotto_web.db'
        shutil.copy2(ROOT/'config/vip-daily-rewards.json', self.work/'config/vip-daily-rewards.json')
        self.user, self.cookie, self.account = self.new_user()

    def new_user(self):
        user = 'vip_'+uuid.uuid4().hex[:16]
        self.assertEqual(self.request('/api/register',dict(username=user,password='fixture_password'))[0],200)
        code, _, headers = self.request('/api/login',dict(username=user,password='fixture_password'))
        self.assertEqual(code,200)
        with closing(sqlite3.connect(self.db)) as db, db:
            account = db.execute('SELECT account_id FROM account_identities WHERE username=?',(user,)).fetchone()[0]
            db.execute('INSERT INTO personal_tracking_accounts VALUES(?,?)',(uuid.uuid4().hex,user))
        return user, headers['Set-Cookie'], account

    def preview(self, cookie=None):
        code,data,headers = self.request(API,cookie=cookie or self.cookie)
        self.assertEqual(code,200,data)
        self.assertEqual(headers['Cache-Control'],'no-store')
        return data

    def claim(self, day=None, cookie=None):
        cookie = cookie or self.cookie
        if day is None: day=self.preview(cookie)['dailyReward']['day']
        return self.request(API,dict(day=day),cookie)

    def ledger(self):
        with closing(sqlite3.connect(self.db)) as db:
            return db.execute('SELECT amount,source_key,details_json FROM card_transactions WHERE account_id=?',(self.account,)).fetchall()

    def policy(self, update):
        path=self.work/'config/vip-daily-rewards.json'
        data=json.loads(path.read_text(encoding='utf-8')); update(data)
        path.write_text(json.dumps(data),encoding='utf-8')

    def test_preview_read_only_auth_scope_and_rejected_input(self):
        before=self.financial_snapshot()
        data=self.preview()
        self.assertEqual(data['level'],0)
        self.assertEqual(data['dailyReward']['currentAmount'],'100')
        self.assertEqual(data['dailyReward']['nextAmount'],'500')
        self.assertEqual([int(r['amount']) for r in data['dailyReward']['rewards']],REWARDS)
        self.assertFalse(data['dailyReward']['claimed'])
        for _ in range(3): self.preview()
        self.assertEqual(before,self.financial_snapshot())
        self.assertEqual(self.request(API)[0],401)
        self.assertEqual(self.request(API,dict(day=data['dailyReward']['day']))[0],401)
        self.assertEqual(self.request(API+'/extra',cookie=self.cookie)[0],404)
        self.assertEqual(self.request(API+'?username=owner_fixture',cookie=self.cookie)[0],400)
        for form in [{},{'day':'2026-02-30'},{'day':'x'},{'day':data['dailyReward']['day'],'level':15},
                     {'day':data['dailyReward']['day'],'amount':999999},
                     {'day':data['dailyReward']['day'],'accountId':self.account}]:
            self.assertEqual(self.request(API,form,self.cookie)[0],400,form)
        for method, extra, expected in [('DELETE',{},405),('POST',{'Origin':'https://untrusted.example'},403)]:
            request=urllib.request.Request(self.url+API, data=b'day=2026-11-08',method=method,
                                         headers={'Cookie':self.cookie,**extra})
            with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(request)
            self.assertEqual(error.exception.code,expected)
        self.assertEqual(self.ledger(),[])

    def test_concurrent_claims_credit_once_card_history_and_notification(self):
        day=self.preview()['dailyReward']['day']
        with closing(sqlite3.connect(self.db)) as db:
            wallet=db.execute('SELECT store_json FROM stores WHERE username=?',(self.user,)).fetchone()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:self.claim(day),range(8)))
        self.assertTrue(all(code==200 for code,_,_ in results),results)
        self.assertEqual(sum(not data['replayed'] for _,data,_ in results),1)
        self.assertTrue(all(data['claim']['amount']=='100' and data['dailyReward']['claimed'] for _,data,_ in results))
        self.assertEqual(len(self.ledger()),1)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT balance,version FROM account_cards WHERE account_id=?',(self.account,)).fetchone(),(100,1))
            self.assertEqual(db.execute('SELECT store_json FROM stores WHERE username=?',(self.user,)).fetchone(),wallet)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM account_audit WHERE target=? AND action='vip_daily_reward'",(self.user,)).fetchone()[0],1)
        code,card,_=self.request('/api/account/card?history=1&kind=reward',cookie=self.cookie)
        self.assertEqual(code,200,card)
        self.assertEqual(card['card']['balance'],'100')
        self.assertEqual(card['events'][0]['label'],'Thưởng ngày VIP 0')
        self.assertEqual(card['events'][0]['delta'],'100')
        code,notices,_=self.request('/api/account/financial-notifications',cookie=self.cookie)
        self.assertEqual(code,200,notices)
        matches=[r for r in notices['events'] if r['title']=='Thưởng ngày VIP 0']
        self.assertEqual(len(matches),1)
        self.assertEqual(matches[0]['action'],'card-history')
        self.assertIn('+100 PayPal',matches[0]['detail'])
        self.assertEqual(self.preview()['points'],'0')

    def test_all_levels_claim_only_current_reward_including_admin(self):
        thresholds=json.loads((self.work/'config/vip-levels.json').read_text())['thresholds']
        for level in range(16):
            user,cookie,account=self.new_user()
            if level: self.charge(int(Decimal(thresholds[str(level)])*100000),user=user)
            data=self.preview(cookie)
            self.assertEqual(data['level'],level)
            self.assertEqual(data['dailyReward']['currentAmount'],str(REWARDS[level]))
            self.assertEqual(data['dailyReward']['nextAmount'],str(REWARDS[level+1]) if level<15 else None)
            code,claimed,_=self.claim(cookie=cookie)
            self.assertEqual(code,200,claimed)
            self.assertEqual((claimed['claim']['level'],claimed['claim']['amount']),(level,str(REWARDS[level])))
            with closing(sqlite3.connect(self.db)) as db:
                self.assertEqual(db.execute('SELECT balance FROM account_cards WHERE account_id=?',(account,)).fetchone()[0],REWARDS[level])
        self.assertEqual(self.preview(self.admin)['level'],0)

    def test_point_rescale_preserves_rank_progress_reward_and_claim_receipt(self):
        path=self.work/'config/vip-levels.json'
        rescaled_policy=json.loads(path.read_text(encoding='utf-8'))
        legacy_policy=json.loads(json.dumps(rescaled_policy))
        legacy_policy.update(version=1,paypalPerPoint='1.25')
        legacy_policy['thresholds']={level:str(int(Decimal(value)*80000))
                                     for level,value in rescaled_policy['thresholds'].items()}
        self.charge(7679537320000,user=self.user)
        try:
            path.write_text(json.dumps(legacy_policy),encoding='utf-8')
            legacy=self.preview()
            code,first,_=self.claim()
            self.assertEqual(code,200,first)
            self.assertEqual(first['claim']['amount'],'10000000')
            path.write_text(json.dumps(rescaled_policy),encoding='utf-8')
            before=self.financial_snapshot()
            rescaled=self.preview()
            self.assertEqual(self.financial_snapshot(),before)
            self.assertEqual(rescaled['level'],legacy['level'])
            self.assertEqual(rescaled['progressBasisPoints'],legacy['progressBasisPoints'])
            self.assertEqual(Decimal(rescaled['points'])*80000,Decimal(legacy['points']))
            self.assertEqual(rescaled['dailyReward']['currentAmount'],legacy['dailyReward']['currentAmount'])
            self.assertEqual(rescaled['dailyReward']['receipt'],first['dailyReward']['receipt'])
            code,replay,_=self.claim()
            self.assertEqual(code,200,replay)
            self.assertTrue(replay['replayed'])
            self.assertEqual(replay['claim'],first['claim'])
            self.assertEqual(len(self.ledger()),1)
        finally:
            path.write_text(json.dumps(rescaled_policy),encoding='utf-8')

    def test_ceil_thresholds_preserve_earned_points_and_paid_daily_receipt(self):
        path=self.work/'config/vip-levels.json'
        rounded=json.loads(path.read_text(encoding='utf-8'))
        fractional=json.loads(json.dumps(rounded))
        fractional['thresholds'].update({'1':'1.25','2':'4.6625','3':'17.375','4':'64.75','5':'241.25'})
        self.charge(125000,user=self.user)
        try:
            path.write_text(json.dumps(fractional),encoding='utf-8')
            self.assertEqual(self.preview()['level'],1)
            code,first,_=self.claim()
            self.assertEqual(code,200,first)
            self.assertEqual(first['claim']['amount'],'500')
            path.write_text(json.dumps(rounded),encoding='utf-8')
            before=self.financial_snapshot()
            data=self.preview()
            self.assertEqual(self.financial_snapshot(),before)
            self.assertEqual((data['level'],data['points'],data['nextLevelPoints']),(0,'1.25','2'))
            self.assertTrue(data['dailyReward']['claimed'])
            self.assertEqual(data['dailyReward']['receipt'],first['dailyReward']['receipt'])
            code,replay,_=self.claim()
            self.assertEqual(code,200,replay)
            self.assertTrue(replay['replayed'])
            self.assertEqual(replay['claim'],first['claim'])
            self.assertEqual(len(self.ledger()),1)
            with closing(sqlite3.connect(self.db)) as db:
                self.assertEqual(db.execute('SELECT balance FROM account_cards WHERE account_id=?',(self.account,)).fetchone()[0],500)
        finally:
            path.write_text(json.dumps(rounded),encoding='utf-8')

    def test_upgrade_and_policy_change_do_not_allow_second_claim(self):
        code,first,_=self.claim(); self.assertEqual(code,200,first)
        self.charge(200000,user=self.user)
        self.policy(lambda p:p['rewards'].update({'0':'200','1':'600'}))
        code,replay,_=self.claim()
        self.assertEqual(code,200,replay)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['claim'],first['claim'])
        self.assertEqual(replay['dailyReward']['currentAmount'],'600')
        self.assertEqual(replay['dailyReward']['receipt']['amount'],'100')
        self.policy(lambda p:p.update(enabled=False))
        self.assertEqual(self.claim()[0],200)  # Historical receipt remains usable, no re-credit.
        self.assertEqual(len(self.ledger()),1)

    def test_disabled_invalid_policy_stale_and_future_dates_do_not_credit(self):
        day=self.preview()['dailyReward']['day']
        for offset in [-1,1]:
            other=(datetime.fromisoformat(day)+timedelta(days=offset)).date().isoformat()
            self.assertEqual(self.claim(other)[0],409)
        self.policy(lambda p:p.update(enabled=False))
        self.assertFalse(self.preview()['dailyReward']['enabled'])
        self.assertEqual(self.claim(day)[0],409)
        self.policy(lambda p:p.update(enabled=True,currency='VNĐ'))
        self.assertEqual(self.request(API,cookie=self.cookie)[0],503)
        self.assertEqual(self.claim(day)[0],503)
        self.assertEqual(self.ledger(),[])

    def test_rename_preserves_receipt_recreated_name_has_fresh_chest(self):
        self.assertEqual(self.claim()[0],200)
        renamed=self.user+'_new'
        code,body,_=self.request('/api/admin/rename-user',dict(accountId=self.account,newUsername=renamed),self.admin)
        self.assertEqual(code,200,body)
        _,_,headers=self.request('/api/login',dict(username=renamed,password='fixture_password'))
        renamed_cookie=headers['Set-Cookie']
        self.assertTrue(self.preview(renamed_cookie)['dailyReward']['claimed'])
        self.assertTrue(self.claim(cookie=renamed_cookie)[1]['replayed'])
        code,body,_=self.request('/api/admin/delete-user',dict(accountId=self.account),self.admin)
        self.assertEqual(code,200,body)
        self.assertEqual(self.request('/api/register',dict(username=renamed,password='fixture_password'))[0],200)
        _,_,headers=self.request('/api/login',dict(username=renamed,password='fixture_password'))
        fresh=self.preview(headers['Set-Cookie'])
        self.assertNotEqual(fresh['accountId'],self.account)
        self.assertFalse(fresh['dailyReward']['claimed'])
        self.assertEqual(self.claim(cookie=headers['Set-Cookie'])[0],200)
        self.assertEqual(len(self.ledger()),1)  # Tombstoned account's immutable receipt survives.

    def test_external_card_writer_is_not_overwritten_and_old_day_replay_is_safe(self):
        day=self.preview()['dailyReward']['day']
        yesterday=(datetime.fromisoformat(day)-timedelta(days=1)).date().isoformat()
        source=f'vip_daily_reward:{self.account}:{yesterday}'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('INSERT INTO card_transactions VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (source,self.account,'PayPal','reward',100,100,yesterday,
                        json.dumps(dict(rewardLevel=0,businessDate=yesterday)),yesterday+'T00:00:00Z',source))
            db.execute('INSERT INTO account_cards VALUES(?,?,?,?,?,?)',(self.account,'PayPal',100,1,yesterday+'T00:00:00Z',yesterday+'T00:00:00Z'))
        code,replayed,_=self.claim(yesterday)
        self.assertEqual(code,200,replayed)
        self.assertTrue(replayed['replayed'])
        self.assertFalse(replayed['dailyReward']['claimed'])
        self.assertEqual(replayed['claim']['day'],yesterday)
        with closing(sqlite3.connect(self.db)) as writer:
            writer.execute('BEGIN IMMEDIATE')
            writer.execute('UPDATE account_cards SET balance=600,version=2 WHERE account_id=?',(self.account,))
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                waiting=pool.submit(self.claim,day)
                time.sleep(.15)
                self.assertFalse(waiting.done())
                writer.commit()
                self.assertEqual(waiting.result()[0],200)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT balance,version FROM account_cards WHERE account_id=?',(self.account,)).fetchone(),(700,3))
        self.assertEqual(len(self.ledger()),2)

    def test_card_overflow_currency_and_audit_failure_roll_back(self):
        day=self.preview()['dailyReward']['day']
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('INSERT INTO account_cards VALUES(?,?,?,?,?,?)',(self.account,'PayPal',9007199254740990,2,'2026-01-01T00:00:00Z','2026-01-01T00:00:00Z'))
        self.assertEqual(self.claim(day)[0],409)
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute('SELECT balance,version FROM account_cards WHERE account_id=?',(self.account,)).fetchone(),(9007199254740990,2))
            db.execute("UPDATE account_cards SET currency='VNĐ',balance=0 WHERE account_id=?",(self.account,))
        self.assertEqual(self.claim(day)[0],409)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE account_cards SET currency='PayPal',balance=0 WHERE account_id=?",(self.account,))
            db.execute("CREATE TRIGGER vip_fixture_audit_fail BEFORE INSERT ON account_audit WHEN NEW.action='vip_daily_reward' BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        self.addCleanup(self.drop_failure_trigger)
        self.assertEqual(self.claim(day)[0],503)
        self.assertEqual(self.ledger(),[])
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT balance,version FROM account_cards WHERE account_id=?',(self.account,)).fetchone(),(0,2))
        self.drop_failure_trigger()
        self.assertEqual(self.claim(day)[0],200)
        with closing(sqlite3.connect(self.db)) as db:
            for sql in ['DELETE FROM card_transactions WHERE account_id=?','UPDATE card_transactions SET amount=999 WHERE account_id=?']:
                with self.assertRaises(sqlite3.IntegrityError): db.execute(sql,(self.account,))

    def drop_failure_trigger(self):
        with closing(sqlite3.connect(self.db)) as db, db: db.execute('DROP TRIGGER IF EXISTS vip_fixture_audit_fail')

    def test_vietnam_midnight_boundary_and_reset_timestamp(self):
        source=self.work/'VipClockCheck.java'
        source.write_text('''import java.time.Instant;
public class VipClockCheck { public static void main(String[] args) throws Exception {
 Class<?> c=Class.forName("LottoWebServer$VipDailyRewards");
 java.lang.reflect.Method m=c.getDeclaredMethod("dayAt",Instant.class);m.setAccessible(true);
 for(String s:args)System.out.println(m.invoke(null,Instant.parse(s)));
}}''',encoding='utf-8')
        subprocess.run([JAVAC,'-d','build',source.name],cwd=self.work,capture_output=True,check=True)
        result=subprocess.run([JAVA,'-cp','build','VipClockCheck',
                               '2026-11-08T16:59:59.999Z','2026-11-08T17:00:00Z'],cwd=self.work,capture_output=True,check=True,text=True)
        self.assertEqual(result.stdout.splitlines(),['2026-11-08','2026-11-09'])
        daily=self.preview()['dailyReward']
        now=datetime.fromisoformat(daily['serverNow'].replace('Z','+00:00'))
        reset=datetime.fromisoformat(daily['nextResetAt'].replace('Z','+00:00'))
        self.assertEqual(now.astimezone(timezone(timedelta(hours=7))).date().isoformat(),daily['day'])
        self.assertEqual((reset.hour,reset.minute,reset.second),(17,0,0))
        self.assertGreater((reset-now).total_seconds(),0)
        self.assertLessEqual((reset-now).total_seconds(),86400)

    @unittest.skipUnless(Path(CHROME).exists(),'Chrome required')
    def test_browser_current_next_chest_and_card_history(self):
        self.charge(7679537320000,user=self.user)
        browser=Browser(CHROME,self.work/'daily-browser')
        self.addCleanup(browser.close)
        browser.call('Network.enable',page=True)
        browser.call('Network.setCookie',dict(name='LOTTO_AUTH',value=self.cookie.split(';')[0].split('=',1)[1],url=self.url),page=True)
        browser.call('Emulation.setDeviceMetricsOverride',dict(width=1440,height=1000,deviceScaleFactor=1,mobile=False),page=True)
        browser.call('Page.navigate',dict(url=self.url+'/'),page=True)
        def wait(expression):
            for _ in range(200):
                if browser.value(expression): return
                time.sleep(.05)
            self.fail('Browser timeout: '+expression+'; '+str(browser.value("JSON.stringify({status:document.getElementById('vipDailyStatus').textContent,hidden:document.getElementById('vipMembershipPanel').hidden,label:document.getElementById('vipDailyClaimLabel').textContent,busy:document.getElementById('vipDailyClaim').getAttribute('aria-busy')})")))
        wait("typeof currentUser==='string' && currentUser==="+json.dumps(self.user)+" && !!document.getElementById('vipMembershipBtn').onclick")
        wait("document.getElementById('vipMembershipLevel').textContent==='V14'")
        self.assertTrue(browser.value("document.getElementById('vipMembershipPanel').hidden"))
        browser.value("document.getElementById('vipMembershipBtn').click()")
        wait("document.getElementById('vipMembershipPanel').dataset.vipLevel==='14'")
        self.assertEqual(browser.value("document.getElementById('vipCurrentDailyAmount').textContent"),'10.000.000')
        self.assertEqual(browser.value("document.getElementById('vipNextDailyAmount').textContent"),'25.000.000')
        self.assertEqual(browser.value("document.getElementById('vipProgressPoints').textContent"),'76,8 tr')
        self.assertEqual(browser.value("document.getElementById('vipProgressTarget').textContent"),'125 tr')
        self.assertEqual(browser.value("document.getElementById('vipProgressPoints').title"),'76.795.373,2 Point hiện có')
        self.assertEqual(browser.value("document.getElementById('vipPointRate').textContent"),'100.000 PayPal đã tiêu')
        self.assertEqual(browser.value("[...document.querySelectorAll('#vipProgressLevels li small')].map(el=>el.textContent)"),
                         ['0 Point','2 Point','5 Point','18 Point','65 Point','242 Point','900 Point','3.350 Point',
                          '12.500 Point','46.625 Point','173.750 Point','647.500 Point','2.412.500 Point',
                          '9.000.000 Point','33.500.000 Point','125.000.000 Point'])
        self.assertEqual(browser.value("document.querySelectorAll('.vip-tier-chest:not(:disabled)').length"),1)
        evidence=ROOT/'runtime/logs/vip_daily_20261108'; evidence.mkdir(parents=True,exist_ok=True)
        metrics=[]
        for width in [1440,390,320]:
            browser.call('Emulation.setDeviceMetricsOverride',dict(width=width,height=900,deviceScaleFactor=1,mobile=width<500),page=True)
            browser.value("document.getElementById('vipLevelsDetails').open=false")
            measure=browser.value("(()=>{const p=document.getElementById('vipMembershipPanel'),r=p.getBoundingClientRect();return {width:innerWidth,left:r.left,right:r.right,scroll:p.scrollWidth,client:p.clientWidth}})()")
            self.assertEqual(measure['width'],width,measure)
            self.assertGreaterEqual(measure['left'],0,measure)
            self.assertLessEqual(measure['right'],width,measure)
            self.assertLessEqual(measure['scroll'],measure['client']+1,measure)
            self.assertTrue(browser.value("(()=>{const b=document.getElementById('vipDailyClaim').getBoundingClientRect(),p=document.getElementById('vipProgressBar').getBoundingClientRect();return b.left>p.right && b.width>=32 && b.width<=44 && Math.abs(b.width-b.height)<1 && p.height<=6})()"))
            metrics.append(measure)
            image=browser.call('Page.captureScreenshot',dict(format='png'),page=True)
            (evidence/f'daily-{width}.png').write_bytes(base64.b64decode(image['data']))
        (evidence/'viewports.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
        browser.call('Emulation.setDeviceMetricsOverride',dict(width=390,height=900,deviceScaleFactor=1,mobile=True),page=True)
        browser.value("document.body.classList.add('light-theme');document.getElementById('vipLevelsDetails').open=true")
        image=browser.call('Page.captureScreenshot',dict(format='png'),page=True)
        (evidence/'daily-levels-light.png').write_bytes(base64.b64decode(image['data']))
        browser.value("document.body.classList.remove('light-theme')")
        image=browser.call('Page.captureScreenshot',dict(format='png'),page=True)
        (evidence/'daily-levels-dark.png').write_bytes(base64.b64decode(image['data']))
        browser.value("document.getElementById('vipLevelsDetails').open=true;document.getElementById('vipProgressLevels').querySelector('button:not(:disabled)').click();document.getElementById('vipDailyClaim').click()")
        wait("document.getElementById('vipDailyClaim').classList.contains('is-claimed') && document.getElementById('vipDailyClaim').getAttribute('aria-busy')==='false'")
        self.assertEqual(len(self.ledger()),1)
        self.assertEqual(browser.value("document.querySelectorAll('.vip-tier-chest:not(:disabled)').length"),0)
        browser.value("document.getElementById('vipLevelsDetails').open=false")
        image=browser.call('Page.captureScreenshot',dict(format='png'),page=True)
        (evidence/'daily-claimed.png').write_bytes(base64.b64decode(image['data']))
        browser.value("document.getElementById('vipMembershipBtn').click();document.getElementById('vipMembershipBtn').click()")
        wait("document.getElementById('vipDailyClaim').classList.contains('is-claimed')")
        self.assertIn('10.000.000',browser.value("document.getElementById('vipDailyClaimHint').textContent"))
        browser.value("window.VietlottAccountHistory.open('card')")
        wait("document.body.textContent.includes('Thưởng ngày VIP 14')")

    @unittest.skipUnless(Path(CHROME).exists(),'Chrome required')
    def test_browser_lost_post_response_recovers_receipt_and_late_auth_response_is_ignored(self):
        browser=Browser(CHROME,self.work/'daily-recovery-browser')
        self.addCleanup(browser.close)
        browser.call('Network.enable',page=True)
        def wait(expression):
            for _ in range(200):
                if browser.value(expression): return
                time.sleep(.05)
            self.fail('Browser timeout: '+expression+'; '+str(browser.value("JSON.stringify({hidden:document.getElementById('vipMembershipPanel').hidden,loading:document.getElementById('vipProgressStatus').textContent,status:document.getElementById('vipDailyStatus').textContent,label:document.getElementById('vipDailyClaimLabel').textContent,busy:document.getElementById('vipDailyClaim').getAttribute('aria-busy'),user:typeof currentUser==='string'?currentUser:'',id:typeof currentAccountId==='string'?currentAccountId:''})")))
        def open_for(user,cookie):
            browser.call('Network.setCookie',dict(name='LOTTO_AUTH',value=cookie.split(';')[0].split('=',1)[1],url=self.url),page=True)
            browser.call('Page.navigate',dict(url=self.url+'/'),page=True)
            wait("typeof currentUser==='string' && currentUser==="+json.dumps(user)+" && typeof currentAccountId==='string' && currentAccountId.length===12 && document.getElementById('appShell').style.display==='block' && !!document.getElementById('vipMembershipBtn').onclick")
            browser.value("document.getElementById('vipMembershipBtn').click()")
            wait("!document.getElementById('vipProgressContent').hidden")
        open_for(self.user,self.cookie)
        browser.value("window.vipRealFetch=window.fetch;window.fetch=(...a)=>String(a[0]).includes('/api/account/vip-daily-reward')&&a[1]?.method==='POST'?vipRealFetch(...a).then(()=>{throw new Error('Lost response fixture')}):vipRealFetch(...a);document.getElementById('vipDailyClaim').click()")
        wait("document.getElementById('vipDailyClaim').classList.contains('is-claimed') && document.getElementById('vipDailyStatus').classList.contains('is-success')")
        self.assertEqual(len(self.ledger()),1)
        user,cookie,account=self.new_user()
        open_for(user,cookie)
        browser.value("window.vipRealFetch=window.fetch;window.fetch=(...a)=>String(a[0]).includes('/api/account/vip-daily-reward')&&a[1]?.method==='POST'?vipRealFetch(...a).then(r=>new Promise(resolve=>setTimeout(()=>resolve(r),500))):vipRealFetch(...a);document.getElementById('vipDailyClaim').click()")
        time.sleep(.08)
        browser.value("window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:false,user:''}}))")
        time.sleep(.7)
        self.assertTrue(browser.value("document.getElementById('vipProgressContent').hidden && document.querySelectorAll('#vipProgressLevels li').length===0"))
        self.assertEqual(browser.value("document.getElementById('vipMembershipLevel').textContent"),'V—')
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM card_transactions WHERE account_id=?',(account,)).fetchone()[0],1)


if __name__=='__main__': unittest.main()
