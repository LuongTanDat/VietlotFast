"""Wallet history ownership, exact movements and actual header/dialog flow."""
import base64
import json
import sqlite3
import time
import unittest
import uuid
from contextlib import closing
from pathlib import Path

from tests import test_account_balances as fixtures
from tests.browser_cdp import Browser
from tests.test_prize_web import ROOT, CHROME


class WalletHistoryTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.AccountBalanceTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.AccountBalanceTests.tearDownClass.__func__)
    start_server = classmethod(fixtures.AccountBalanceTests.start_server.__func__)
    request = classmethod(fixtures.AccountBalanceTests.request.__func__)
    login = classmethod(fixtures.AccountBalanceTests.login.__func__)

    def setUp(self):
        self.db = self.work/'runtime/lotto_web.db'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('DELETE FROM account_activity_links')
            db.execute('DELETE FROM account_audit')
            db.execute('DELETE FROM wallet_events')
            db.execute('DELETE FROM manual_topup_details')
            db.execute('DELETE FROM payment_orders')
            db.execute("UPDATE stores SET store_json='{}'")

    def audit(self, action, details, user='member_fixture', at='2026-11-03T03:00:00Z'):
        event=uuid.uuid4().hex
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('INSERT INTO account_audit VALUES(?,?,?,?,?,?)',
                       (event,user,user,action,json.dumps(details),at))
        return event

    def history(self, query='', cookie=None):
        code, payload, headers=self.request('/api/account/wallet-history'+query, cookie=cookie or self.member)
        self.assertEqual(code,200,payload)
        self.assertEqual(headers.get('Cache-Control'),'no-store')
        return payload

    def snapshot(self):
        with closing(sqlite3.connect(self.db)) as db:
            return {table:db.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall()
                    for table in ['stores','account_audit','account_activity_links','wallet_events','payment_orders','prediction_charges']}

    def money_snapshot(self):
        result=self.snapshot()
        stores={name:json.loads(raw) for name,raw in result.pop('stores')}
        result['money']={name:{key:stores.get(name,{}).get(key,0) for key in ['paypalBalance','diamondBalance','walletVersion']}
                         for name in ['member_fixture','owner_fixture']}
        return result

    def seed(self):
        self.audit('manual_topup_credit',dict(amount=1000000,credit=1312500,id='topup-fixture'))
        self.audit('vnpay_credit',dict(amount=20000,credit=25000,id='qr-fixture'))
        self.audit('prediction_reserve',dict(paypal=40000,tickets=4,game='LOTO_5_35',draw=985,id='charge-fixture'))
        self.audit('prediction_charged',dict(paypal=40000,id='charge-fixture'))
        self.audit('prediction_refunded',dict(paypal=40000,id='refund-fixture'))
        self.audit('manual_topup_requested',dict(amount=50000))
        self.audit('manual_topup_rejected',dict(amount=50000,credit=0))
        self.audit('vnpay_test_paid',dict(amount=50000,credit=0))
        self.audit('update_assets',dict(paypal=999))
        self.audit('redeem_gift_code',dict(code='SECRET',reward=dict(paypal=100,diamond=5)))
        self.audit('reclaim_gift_code_rewards',dict(paypal=50,diamond=2))
        self.audit('manual_topup_credit',dict(amount=100000000,credit=999999999,id='other-account'),user='owner_fixture')
        self.audit('prediction_reserve',dict(paypal=1,tickets=1,game='KENO',draw='1',id='<img src=x onerror=alert(1)>'))
        with closing(sqlite3.connect(self.db)) as db, db:
            for action,details in [('exchange:3',{}),('spin:2',{'luckyWheelLastResult':{'label':'5 Kim cương + 100 PayPal','reward':{'paypal':200,'diamond':10}}})]:
                db.execute('INSERT INTO wallet_events VALUES(?,?,?,?,?)',('member_fixture',uuid.uuid4().hex,action,json.dumps(dict(ok=True,store=details)),'2026-11-03T04:00:00Z'))

    def test_permissions_movements_filters_and_read_only(self):
        self.seed()
        self.assertEqual(self.request('/api/account/wallet-history')[0],401)
        self.assertEqual(self.request('/api/account/wallet-history',dict(kind='all'),self.member)[0],405)
        for query in ['?page=0','?page=-1','?page=99999999','?page=x','?kind=unknown']:
            self.assertEqual(self.request('/api/account/wallet-history'+query,cookie=self.member)[0],400)
        before=self.snapshot()
        report=self.history('?accountId=100000000000&username=owner_fixture')
        self.assertEqual(report['owner'],'member_fixture')
        self.assertEqual(report['total'],10)
        self.assertNotIn('SECRET',json.dumps(report))
        self.assertNotIn('other-account',json.dumps(report))
        self.assertEqual(sum(int(row['delta'] or 0) for row in report['events']),1331749)
        unknown=[r for r in report['events'] if r['label']=='Điều chỉnh số dư'][0]
        self.assertIsNone(unknown['delta'])
        fee=[r for r in report['events'] if r['reference']=='charge-fixture'][0]
        self.assertIn('Kỳ #985',fee['description'])
        for kind,total in [('topup',2),('spend',3),('refund',1),('other',4)]:
            filtered=self.history('?kind='+kind)
            self.assertEqual(filtered['total'],total)
            self.assertTrue(all(row['kind']==kind for row in filtered['events']))
        self.assertEqual(self.snapshot(),before)

    def test_pagination_order_and_owner_rename(self):
        for index in range(43):
            self.audit('manual_topup_credit',dict(amount=20000,credit=index,id=f'order-{index}'),at=f'2026-11-03T03:{index:02d}:00Z')
        first=self.history(); second=self.history('?page=2'); last=self.history('?page=9999999')
        self.assertEqual((first['total'],first['pages'],len(first['events'])),(43,3,20))
        self.assertEqual((last['page'],len(last['events'])),(3,3))
        ids=[r['id'] for page in [first,second,last] for r in page['events']]
        self.assertEqual(len(set(ids)),43)
        self.assertEqual(first['events'][0]['reference'],'order-42')
        name='renamed_'+uuid.uuid4().hex[:8]
        identity=first['accountId']
        try:
            code,body,_=self.request('/api/admin/rename-user',dict(accountId=identity,newUsername=name),self.admin)
            self.assertEqual(code,200,body)
            cookie=self.request('/api/login',dict(username=name,password='fixture_password'))[2]['Set-Cookie']
            renamed=self.history(cookie=cookie)
            self.assertEqual(renamed['accountId'],identity)
            self.assertEqual(renamed['total'],43)
        finally:
            self.request('/api/admin/rename-user',dict(accountId=identity,newUsername='member_fixture'),self.admin)
            type(self).member=self.request('/api/login',dict(username='member_fixture',password='fixture_password'))[2]['Set-Cookie']

    def test_actual_deposit_adjustment_and_idempotent_wheel(self):
        form=dict(mode='account-id',amount=1000000,requestId=uuid.uuid4().hex)
        code,result,_=self.request('/api/payments/manual',form,self.member)
        self.assertEqual(code,200,result)
        self.assertEqual(self.history()['total'],0)
        code,body,_=self.request('/api/admin/deposits/review',dict(id=result['order']['id'],action='approve'),self.admin)
        self.assertEqual(code,200,body)
        self.assertEqual(self.history()['events'][0]['delta'],'1312500')
        code,body,_=self.request('/api/admin/update-assets',dict(username='member_fixture',paypal=1500000,diamond=1),self.admin)
        self.assertEqual(code,200,body)
        adjusted=[row for row in self.history()['events'] if row['label']=='Điều chỉnh số dư'][0]
        self.assertEqual(adjusted['delta'],'187500')
        # Exchanges need room in the spin store. This only touches the fixture DB.
        with closing(sqlite3.connect(self.db)) as db,db:
            wallet=json.loads(db.execute("SELECT store_json FROM stores WHERE username='member_fixture'").fetchone()[0])
            wallet.update(luckyWheelStoredSpins=0,luckyWheelLastRegenAt='2099-01-01T00:00:00Z')
            db.execute("UPDATE stores SET store_json=? WHERE username='member_fixture'",(json.dumps(wallet),))
        exchange=dict(action='exchange',count=2,requestId=uuid.uuid4().hex)
        for _ in range(2):
            code,body,_=self.request('/api/wheel',exchange,self.member)
            self.assertEqual(code,200,body)
        report=self.history('?kind=spend')
        self.assertEqual((report['total'],report['events'][0]['delta'],report['balance']),(1,'-4000',1496000))

    def test_prediction_reward_filter_conversion_details_and_wallet_version(self):
        self.audit('prediction_reward',dict(id='reward-fixture',game='LOTO_5_35',draw='985',rewardVnd=1000000,paypal=1250000))
        with closing(sqlite3.connect(self.db)) as db,db:
            db.execute("INSERT OR REPLACE INTO stores VALUES('member_fixture',?)",(json.dumps(dict(paypalBalance=1250000,walletVersion=7)),))
        before=self.snapshot()
        report=self.history('?kind=reward')
        self.assertEqual((report['total'],report['balance'],report['walletVersion']),(1,1250000,7))
        self.assertEqual(report['events'][0]['delta'],'1250000')
        self.assertIn('Kỳ #985',report['events'][0]['description'])
        self.assertIn('1.000.000 VNĐ × 1,25',report['events'][0]['description'])
        self.assertEqual(self.history('?kind=refund')['total'],0)
        self.assertEqual(self.snapshot(),before)

    @unittest.skipUnless(Path(CHROME).exists(),'Chrome required')
    def test_browser_header_filters_mobile_escape_errors_and_session_change(self):
        self.seed()
        for index in range(25):
            self.audit('prediction_reserve',dict(paypal=10000,tickets=1,game='LOTO_6_45',draw='100',id=str(index)))
        before=self.money_snapshot()
        profile=self.work/'wallet-history-browser'
        browser=Browser(CHROME,profile)
        self.addCleanup(browser.close)
        browser.call('Network.enable',page=True)
        browser.call('Network.setCookie',dict(name='LOTTO_AUTH',value=self.member.split(';')[0].split('=',1)[1],url=self.url),page=True)
        browser.call('Emulation.setDeviceMetricsOverride',dict(width=1440,height=1000,deviceScaleFactor=1,mobile=False),page=True)
        browser.call('Page.navigate',{'url':self.url+'/'},page=True)
        def wait(expression):
            for _ in range(160):
                if browser.value(expression): return
                time.sleep(.05)
            self.fail(expression+' did not become true; '+str(browser.value("({status:document.getElementById('walletHistoryStatus').textContent,open:document.getElementById('walletHistoryDialog').open,user:currentUser})")))
        wait("typeof currentUser!=='undefined' && currentUser==='member_fixture' && !!document.getElementById('walletHistoryOpen')")
        self.assertTrue(browser.value("document.getElementById('paypalBalance').compareDocumentPosition(document.getElementById('walletHistoryOpen')) & Node.DOCUMENT_POSITION_FOLLOWING ? true : false"))
        self.assertTrue(browser.value("document.getElementById('walletHistoryOpen').compareDocumentPosition(document.getElementById('notificationBtn')) & Node.DOCUMENT_POSITION_FOLLOWING ? true : false"))
        browser.value("document.getElementById('walletHistoryOpen').click()")
        wait("document.getElementById('walletHistoryDialog').open && document.querySelectorAll('#walletHistoryRows tr').length===20")
        self.assertFalse(browser.value("!!document.querySelector('#walletHistoryRows img')"))
        self.assertTrue(browser.value("document.getElementById('walletHistoryDialog').scrollWidth<=document.getElementById('walletHistoryDialog').clientWidth"))
        browser.value("document.getElementById('walletHistoryNext').click()")
        wait("document.getElementById('walletHistoryPage').textContent==='2 / 2'")
        browser.value("document.querySelector('[data-wallet-kind=topup]').click()")
        wait("document.querySelectorAll('#walletHistoryRows tr').length===2")
        self.assertIn('1.312.500',browser.value("document.getElementById('walletHistoryRows').textContent"))
        artifacts=ROOT/'runtime/logs/wallet_history_20261103';artifacts.mkdir(parents=True,exist_ok=True)
        (artifacts/'desktop.png').write_bytes(base64.b64decode(browser.call('Page.captureScreenshot',page=True)['data']))
        browser.call('Emulation.setDeviceMetricsOverride',dict(width=390,height=844,deviceScaleFactor=1,mobile=False),page=True)
        self.assertTrue(browser.value("(()=>{const d=document.getElementById('walletHistoryDialog'),r=d.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&d.scrollWidth<=d.clientWidth})()"))
        browser.value("document.querySelector('[data-wallet-kind=all]').click()")
        wait("document.querySelectorAll('#walletHistoryRows tr').length===20")
        (artifacts/'mobile.png').write_bytes(base64.b64decode(browser.call('Page.captureScreenshot',page=True)['data']))
        browser.call('Input.dispatchKeyEvent',dict(type='keyDown',key='Escape',code='Escape',windowsVirtualKeyCode=27),page=True)
        wait("!document.getElementById('walletHistoryDialog').open")
        browser.value("window.realFetch=fetch;window.fetch=(...args)=>String(args[0]).includes('/api/account/wallet-history')?Promise.reject(new Error('Lỗi thử nghiệm')):realFetch(...args);document.getElementById('walletHistoryOpen').click()")
        wait("document.getElementById('walletHistoryStatus').textContent==='Lỗi thử nghiệm'")
        self.assertEqual(browser.value("document.querySelectorAll('#walletHistoryRows tr').length"),0)
        browser.value("window.fetch=realFetch;document.getElementById('walletHistoryRefresh').click()")
        wait("document.querySelectorAll('#walletHistoryRows tr').length===20")
        # A response that arrives after a session change must never restore rows.
        browser.value("window.fetch=(...args)=>String(args[0]).includes('/api/account/wallet-history')?new Promise(resolve=>setTimeout(()=>realFetch(...args).then(resolve),150)):realFetch(...args);document.getElementById('walletHistoryRefresh').click();window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:false,user:''}}))")
        time.sleep(.3)
        self.assertTrue(browser.value("!document.getElementById('walletHistoryDialog').open && document.querySelectorAll('#walletHistoryRows tr').length===0"))
        self.assertEqual(self.money_snapshot(),before)
