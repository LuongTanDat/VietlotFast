"""Authoritative spending -> VIP, with no financial writes; actual header UI."""
import base64
import json
import shutil
import sqlite3
import time
import unittest
import uuid
from decimal import Decimal
from contextlib import closing
from pathlib import Path

from tests import test_account_balances as fixtures
from tests.browser_cdp import Browser
from tests.test_prize_web import ROOT, CHROME


class VipProgressTests(unittest.TestCase):
    tearDownClass = classmethod(fixtures.AccountBalanceTests.tearDownClass.__func__)
    start_server = classmethod(fixtures.AccountBalanceTests.start_server.__func__)
    request = classmethod(fixtures.AccountBalanceTests.request.__func__)
    login = classmethod(fixtures.AccountBalanceTests.login.__func__)

    @classmethod
    def setUpClass(cls):
        fixtures.AccountBalanceTests.setUpClass.__func__(cls)
        (cls.work/'config').mkdir()
        shutil.copy2(ROOT/'config/vip-levels.json', cls.work/'config/vip-levels.json')
        shutil.copy2(ROOT/'config/vip-daily-rewards.json', cls.work/'config/vip-daily-rewards.json')

    def setUp(self):
        self.db = self.work/'runtime/lotto_web.db'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('DELETE FROM prediction_charges')
            db.execute('DELETE FROM wallet_events')
            for user in ['owner_fixture', 'member_fixture']:
                db.execute('INSERT OR IGNORE INTO personal_tracking_accounts VALUES(?,?)', ('tracking-'+user,user))

    def charge(self, amount, status='charged', user='member_fixture'):
        with closing(sqlite3.connect(self.db)) as db, db:
            identity = db.execute('SELECT id FROM personal_tracking_accounts WHERE username=?',(user,)).fetchone()[0]
            db.execute('INSERT INTO prediction_charges VALUES(?,?,?,?,?,?,?,?,?)',
                       (uuid.uuid4().hex, identity, 'LOTO_5_35', 'fixture-draw', 1, amount, status,
                        '2026-11-07T00:00:00Z','2026-11-07T00:00:01Z'))

    def wheel(self, action='exchange:2', user='member_fixture'):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('INSERT INTO wallet_events VALUES(?,?,?,?,?)',
                       (user, uuid.uuid4().hex, action, '{"ok":true}', '2026-11-07T00:00:00Z'))

    def progress(self, cookie=None):
        code, data, headers = self.request('/api/account/vip-progress',cookie=cookie or self.member)
        self.assertEqual(code,200,data)
        self.assertEqual(headers['Cache-Control'],'no-store')
        return data

    def financial_snapshot(self):
        with closing(sqlite3.connect(self.db)) as db:
            return {table:db.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall() for table in
                    ['users','stores','account_entitlements','wallet_events','prediction_charges',
                     'personal_tracking_accounts','account_cards','card_transactions','account_audit',
                     'account_activity_links','payment_orders']}

    def test_auth_method_path_and_owner_scope(self):
        self.charge(200000)
        self.assertEqual(self.request('/api/account/vip-progress')[0],401)
        self.assertEqual(self.request('/api/account/vip-progress',{},self.member)[0],405)
        self.assertEqual(self.request('/api/account/vip-progress/other',cookie=self.member)[0],404)
        self.assertEqual(self.request('/api/account/vip-progress?username=owner_fixture',cookie=self.member)[0],400)
        self.assertEqual(self.progress()['level'],1)
        self.assertEqual(self.progress(self.admin)['level'],0)  # Admin access never grants points.

    def test_only_completed_spending_counts_and_reads_change_nothing(self):
        self.charge(121000)
        for status in ['reserved','refunded','owner_deleted']:
            self.charge(999999,status)
        self.charge(999999,user='owner_fixture')
        self.wheel()
        self.wheel('spin:2')
        self.wheel('clear:1')
        # Admin edits and prizes/refunds are not paid consumption.
        for action in ['assets_updated','prediction_reward','prediction_refunded','card_transfer','card_interest']:
            event=uuid.uuid4().hex
            with closing(sqlite3.connect(self.db)) as db, db:
                db.execute('INSERT INTO account_audit VALUES(?,?,?,?,?,?)',
                           (event,'member_fixture','member_fixture',action,'{"paypal":999999}', '2026-11-07T00:00:00Z'))
        before=self.financial_snapshot()
        for _ in range(3):
            data=self.progress()
            self.assertEqual((data['spentPayPal'],data['points'],data['level']),('125000','1.25',0))
            self.assertEqual(data['remainingPoints'],'0.75')
            self.assertEqual(data['paypalPerPoint'],'100000')
            self.assertEqual(data['progressBasisPoints'],6250)
        self.assertEqual(self.financial_snapshot(),before)

    def test_fractional_points_aggregate_before_division(self):
        for _ in range(4): self.charge(1)
        data=self.progress()
        self.assertEqual((data['spentPayPal'],data['points'],data['remainingPoints']),('4','0.00004','1.99996'))
        self.charge(1)
        self.assertEqual(self.progress()['points'],'0.00005')
        self.charge(99995)
        self.assertEqual((self.progress()['points'],self.progress()['level']),('1',0))
        self.charge(25000)
        self.assertEqual((self.progress()['points'],self.progress()['level']),('1.25',0))
        self.charge(75000)
        self.assertEqual((self.progress()['points'],self.progress()['level']),('2',1))

    def test_all_approved_threshold_boundaries_and_maximum(self):
        approved=['0','2','5','18','65','242','900','3350',
                  '12500','46625','173750','647500','2412500','9000000','33500000','125000000']
        approved_spending=[0,200000,500000,1800000,6500000,24200000,90000000,335000000,
                      1250000000,4662500000,17375000000,64750000000,241250000000,
                      900000000000,3350000000000,12500000000000]
        spent=0
        for level, points in enumerate(approved):
            if level:
                # Just below each level boundary; then cross it with 1 PayPal.
                target=int(Decimal(points)*100000)
                self.assertEqual(target,approved_spending[level])
                self.charge(target-spent-1)
                self.assertEqual(self.progress()['level'],level-1)
                self.charge(1)
                spent=target
            data=self.progress()
            self.assertEqual((data['level'],data['points']),(level,str(points)))
            self.assertEqual(data['progressBasisPoints'],10000 if level==15 else 0)
            self.assertFalse(data['draft'])
        self.charge(125000)
        data=self.progress()
        self.assertEqual((data['level'],data['nextLevel'],data['remainingPoints']),(15,None,'0'))
        self.assertEqual(data['points'],'125000001.25')

    def test_large_lifetime_totals_stay_exact_above_sqlite_sum_and_js_limits(self):
        for _ in range(2): self.charge(9000000000000000000)
        data=self.progress()
        self.assertEqual(data['spentPayPal'],'18000000000000000000')
        self.assertEqual(data['points'],'180000000000000')
        self.assertEqual(data['level'],15)

    def test_charge_refund_does_not_leave_points(self):
        self.charge(200000)
        self.assertEqual(self.progress()['level'],1)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE prediction_charges SET status='refunded'")
        self.assertEqual((self.progress()['level'],self.progress()['points']),(0,'0'))

    def test_invalid_configuration_fails_closed_and_recovers(self):
        path=self.work/'config/vip-levels.json'
        original=path.read_text(encoding='utf-8')
        try:
            for change in [lambda p:p['thresholds'].update({'2':'0'}),
                           lambda p:p['thresholds'].update({'1':'1.250001'}),
                           lambda p:p.update(paypalPerPoint='1.25'),
                           lambda p:p.update(version=999)]:
                invalid=json.loads(original)
                change(invalid)
                path.write_text(json.dumps(invalid),encoding='utf-8')
                self.assertEqual(self.request('/api/account/vip-progress',cookie=self.member)[0],503)
        finally: path.write_text(original,encoding='utf-8')
        self.assertEqual(self.progress()['level'],0)

    def test_rename_preserves_spending_and_deleted_name_does_not_inherit_it(self):
        name='loyalty_'+uuid.uuid4().hex[:8]
        self.assertEqual(self.request('/api/register',dict(username=name,password='fixture_password'))[0],200)
        _,_,headers=self.request('/api/login',dict(username=name,password='fixture_password'))
        cookie=headers['Set-Cookie']
        with closing(sqlite3.connect(self.db)) as db,db:
            db.execute('INSERT INTO personal_tracking_accounts VALUES(?,?)',(uuid.uuid4().hex,name))
        self.charge(125000,user=name)
        self.wheel(user=name)
        before=self.progress(cookie)
        renamed=name+'_new'
        code,body,_=self.request('/api/admin/rename-user',dict(accountId=before['accountId'],newUsername=renamed),self.admin)
        self.assertEqual(code,200,body)
        _,_,headers=self.request('/api/login',dict(username=renamed,password='fixture_password'))
        after=self.progress(headers['Set-Cookie'])
        self.assertEqual((after['points'],after['accountId']),(before['points'],before['accountId']))
        code,body,_=self.request('/api/admin/delete-user',dict(accountId=before['accountId']),self.admin)
        self.assertEqual(code,200,body)
        self.assertEqual(self.request('/api/register',dict(username=renamed,password='fixture_password'))[0],200)
        _,_,headers=self.request('/api/login',dict(username=renamed,password='fixture_password'))
        after=self.progress(headers['Set-Cookie'])
        self.assertNotEqual(after['accountId'],before['accountId'])
        self.assertEqual(after['points'],'0')

    @unittest.skipUnless(Path(CHROME).exists(),'Chrome required')
    def test_browser_header_rank_loads_closed_and_all_levels_have_distinct_colors(self):
        browser=Browser(CHROME,self.work/'vip-rank-badge-browser')
        self.addCleanup(browser.close)
        browser.call('Network.enable',page=True)
        browser.call('Network.setCookie',dict(name='LOTTO_AUTH',value=self.member.split(';')[0].split('=',1)[1],url=self.url),page=True)
        browser.call('Emulation.setDeviceMetricsOverride',dict(width=1440,height=900,deviceScaleFactor=1,mobile=False),page=True)
        browser.call('Page.navigate',dict(url=self.url+'/'),page=True)
        def wait(expression):
            for _ in range(240):
                if browser.value(expression):return
                time.sleep(.05)
            self.fail('Header badge timeout: '+expression)
        wait("document.getElementById('vipMembershipLevel').textContent==='V0'")
        self.assertTrue(browser.value("document.getElementById('vipMembershipPanel').hidden"))
        self.assertEqual(browser.value("document.querySelectorAll('#vipMembershipBtn svg').length"),0)
        time.sleep(.6)
        browser.value("window.vipBadgeReads=0;window.vipBadgeFetch=window.fetch;window.fetch=(...args)=>{if(String(args[0]).includes('/api/account/vip-daily-reward'))window.vipBadgeReads++;return vipBadgeFetch(...args)};const balance=document.getElementById('paypalBalance');for(let i=0;i<10;i++)balance.textContent=balance.textContent")
        time.sleep(.6)
        self.assertEqual(browser.value('window.vipBadgeReads'),0)
        browser.value("document.getElementById('paypalBalance').title='1 PayPal'")
        wait('window.vipBadgeReads>0')
        policy=json.loads((self.work/'config/vip-levels.json').read_text(encoding='utf-8'))
        evidence=ROOT/'runtime/logs/vip_level_badge_20261109'; evidence.mkdir(parents=True,exist_ok=True)
        colors=[];spent=0
        for level in range(16):
            target=int(Decimal(policy['thresholds'][str(level)])*100000)
            if target>spent:
                self.charge(target-spent)
                spent=target
                browser.value("window.dispatchEvent(new Event('dvlf:prediction-wallet'))")
            wait(f"document.getElementById('vipMembershipLevel').textContent==='V{level}' && document.getElementById('vipMembershipBtn').title.startsWith('VIP {level} ·')")
            self.assertTrue(browser.value("document.getElementById('vipMembershipPanel').hidden"))
            colors.append(browser.value("getComputedStyle(document.getElementById('vipMembershipBtn')).color"))
            if level in [0,14,15]:
                rect=browser.value("(()=>{const r=document.getElementById('vipMembershipBtn').getBoundingClientRect();return {x:r.left-3,y:r.top-3,width:r.width+6,height:r.height+6,scale:3}})()")
                image=browser.call('Page.captureScreenshot',dict(format='png',clip=rect),page=True)
                (evidence/f'V{level}.png').write_bytes(base64.b64decode(image['data']))
        self.assertEqual(len(set(colors)),16)
        browser.value("document.body.classList.add('light-theme')")
        self.assertEqual(browser.value("getComputedStyle(document.getElementById('vipMembershipBtn')).color"),colors[15])
        browser.call('Emulation.setDeviceMetricsOverride',dict(width=320,height=900,deviceScaleFactor=1,mobile=True),page=True)
        self.assertTrue(browser.value("(()=>{const b=document.getElementById('vipMembershipBtn'),r=b.getBoundingClientRect(),t=document.getElementById('vipMembershipLevel').getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&t.left>=r.left&&t.right<=r.right})()"))
        browser.value("document.getElementById('vipMembershipBtn').click()")
        wait("document.getElementById('vipMembershipPanel').dataset.vipLevel==='15'")
        browser.value("document.getElementById('vipMembershipBtn').click()")
        self.assertEqual(browser.value("document.getElementById('vipMembershipLevel').textContent"),'V15')
        browser.value("window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:false}}))")
        self.assertEqual(browser.value("document.getElementById('vipMembershipLevel').textContent"),'V—')
        self.assertTrue(browser.value("!document.getElementById('vipMembershipBtn').hasAttribute('data-vip-level')"))
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM card_transactions').fetchone()[0],0)
        (evidence/'colors.json').write_text(json.dumps(colors,indent=2),encoding='utf-8')

    @unittest.skipUnless(Path(CHROME).exists(),'Chrome required')
    def test_browser_progress_mobile_errors_refresh_and_session_isolation(self):
        self.charge(350000)  # 3.5 points -> VIP 1, halfway from 2 to 5.
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("INSERT OR REPLACE INTO stores VALUES('member_fixture',?)",
                       (json.dumps(dict(paypalBalance=350000,diamondBalance=9195,walletVersion=2)),))
        before=self.financial_snapshot()
        browser=Browser(CHROME,self.work/'vip-browser')
        self.addCleanup(browser.close)
        browser.call('Network.enable',page=True)
        browser.call('Network.setCookie',dict(name='LOTTO_AUTH',value=self.member.split(';')[0].split('=',1)[1],url=self.url),page=True)
        browser.call('Emulation.setDeviceMetricsOverride',dict(width=1440,height=1000,deviceScaleFactor=1,mobile=False),page=True)
        browser.call('Page.navigate',dict(url=self.url+'/'),page=True)
        def wait(expression):
            for _ in range(200):
                if browser.value(expression): return
                time.sleep(.05)
            details=browser.value("JSON.stringify({user:typeof currentUser==='undefined'?null:currentUser,id:typeof currentAccountId==='undefined'?null:currentAccountId,hidden:document.getElementById('vipMembershipPanel').hidden,status:document.getElementById('vipProgressStatus').textContent,retry:document.getElementById('vipProgressRetry').hidden,scripts:Array.from(document.scripts).filter(x=>x.src.includes('vip')).map(x=>x.src)})")
            raise AssertionError('Timeout: '+expression+'; '+details)
        wait("typeof currentUser==='string' && currentUser==='member_fixture' && !!document.getElementById('vipMembershipBtn').onclick")
        browser.value("document.getElementById('vipMembershipBtn').click()")
        wait("document.getElementById('vipMembershipPanel').dataset.vipLevel==='1'")
        self.assertEqual(browser.value("document.getElementById('vipCurrentDailyAmount').textContent"),'500')
        self.assertEqual(browser.value("document.getElementById('vipProgressBar').getAttribute('aria-valuenow')"),'50')
        self.assertTrue(browser.value("!document.getElementById('vipMembershipRenewBtn').hidden && document.getElementById('vipProgressDraft').hidden"))
        self.assertEqual(browser.value("document.querySelectorAll('#vipProgressLevels li').length"),16)
        evidence=ROOT/'runtime/logs/vip_progress_20261107'
        evidence.mkdir(parents=True,exist_ok=True)
        viewport_metrics=[]
        for width in [1440,390,320]:
            browser.call('Emulation.setDeviceMetricsOverride',dict(width=width,height=900,deviceScaleFactor=1,mobile=width<500),page=True)
            browser.value("document.querySelector('.vip-levels-details').open=true")
            metrics=browser.value("(()=>{const p=document.getElementById('vipMembershipPanel'),r=p.getBoundingClientRect();return {left:r.left,right:r.right,width:innerWidth,scroll:p.scrollWidth,client:p.clientWidth}})()")
            viewport_metrics.append(dict(deviceWidth=width,**metrics))
            self.assertEqual(metrics['width'],width,metrics)
            self.assertGreaterEqual(metrics['left'],0,metrics)
            self.assertLessEqual(metrics['right'],metrics['width'],metrics)
            self.assertLessEqual(metrics['scroll'],metrics['client']+1,metrics)
            if width in [1440,390]:
                image=browser.call('Page.captureScreenshot',dict(format='png'),page=True)
                (evidence/f'vip-{width}.png').write_bytes(base64.b64decode(image['data']))
        (evidence/'viewports.json').write_text(json.dumps(viewport_metrics,indent=2),encoding='utf-8')
        # Freshly settled spending updates the same opened panel through wallet events.
        self.charge(250000)
        browser.value("window.dispatchEvent(new Event('dvlf:prediction-wallet'))")
        wait("document.getElementById('vipMembershipPanel').dataset.vipLevel==='2'")
        # Network failure must not leave stale points visible; retry restores them.
        browser.value("window.vipRealFetch=window.fetch;window.fetch=(...a)=>String(a[0]).includes('/api/account/vip-daily-reward')?Promise.reject(new Error('fixture')):vipRealFetch(...a);document.getElementById('vipMembershipBtn').click();document.getElementById('vipMembershipBtn').click()")
        wait("!document.getElementById('vipProgressRetry').hidden")
        self.assertTrue(browser.value("document.getElementById('vipProgressContent').hidden"))
        self.assertEqual(browser.value("document.getElementById('vipMembershipLevel').textContent"),'V—')
        browser.value("window.fetch=vipRealFetch;document.getElementById('vipProgressRetry').click()")
        wait("document.getElementById('vipMembershipPanel').dataset.vipLevel==='2'")
        self.assertEqual(browser.value("document.getElementById('vipMembershipLevel').textContent"),'V2')
        # A response arriving after an auth boundary cannot repopulate another session.
        browser.value("window.fetch=(...a)=>String(a[0]).includes('/api/account/vip-daily-reward')?new Promise((resolve,reject)=>setTimeout(()=>vipRealFetch(a[0],{...a[1],signal:undefined}).then(resolve,reject),200)):vipRealFetch(...a);document.getElementById('vipMembershipBtn').click();document.getElementById('vipMembershipBtn').click()")
        time.sleep(.05)
        browser.value("window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:false,user:''}}))")
        time.sleep(.4)
        self.assertTrue(browser.value("document.getElementById('vipProgressContent').hidden && document.querySelectorAll('#vipProgressLevels li').length===0"))
        self.assertEqual(browser.value("document.getElementById('vipMembershipLevel').textContent"),'V—')
        # Only our intentional fixture charge can differ from the financial snapshot.
        after=self.financial_snapshot()
        before.pop('prediction_charges'); after.pop('prediction_charges')
        # The existing app saves display preferences after boot. Compare its
        # monetary fields exactly, without treating preferences as VIP writes.
        for snapshot in [before,after]:
            snapshot['stores']=[(user,{key:json.loads(raw).get(key) for key in
                                      ['paypalBalance','diamondBalance','walletVersion']})
                                for user,raw in snapshot['stores']]
        self.assertEqual(after,before)

    @unittest.skipUnless(Path(CHROME).exists(),'Chrome required')
    def test_browser_maximum_points_and_admin_access_remain_independent(self):
        self.charge(12500000000003)
        browser=Browser(CHROME,self.work/'vip-maximum-browser')
        self.addCleanup(browser.close)
        browser.call('Network.enable',page=True)
        browser.call('Emulation.setDeviceMetricsOverride',dict(width=1280,height=900,deviceScaleFactor=1,mobile=False),page=True)
        def open_for(cookie, user):
            browser.call('Network.setCookie',dict(name='LOTTO_AUTH',value=cookie.split(';')[0].split('=',1)[1],url=self.url),page=True)
            browser.call('Page.navigate',dict(url=self.url+'/'),page=True)
            for _ in range(200):
                if browser.value(f"typeof currentUser==='string' && currentUser==={json.dumps(user)} && document.getElementById('appShell').style.display==='block'"): break
                time.sleep(.05)
            else: self.fail('Login UI did not finish')
            browser.value("document.getElementById('vipMembershipBtn').click()")
            for _ in range(200):
                if browser.value("!document.getElementById('vipProgressContent').hidden"): return
                time.sleep(.05)
            self.fail('VIP did not load')
        open_for(self.member,'member_fixture')
        self.assertEqual(browser.value("document.getElementById('vipCurrentDailyAmount').textContent"),'25.000.000')
        self.assertEqual(browser.value("document.getElementById('vipProgressBar').getAttribute('aria-valuenow')"),'100')
        self.assertTrue(browser.value("document.getElementById('vipProgressRemaining').textContent.includes('cao nhất') && !hasActiveVipMembership()"))
        open_for(self.admin,'owner_fixture')
        self.assertEqual(browser.value("document.getElementById('vipProgressLevel').textContent"),'VIP 0 → 1')
        self.assertTrue(browser.value("hasActiveVipMembership() && document.getElementById('vipMembershipRenewBtn').hidden && document.getElementById('vipMembershipStateBadge').textContent==='Quản trị'"))


if __name__=='__main__': unittest.main()
