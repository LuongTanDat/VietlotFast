"""Committed money receipts -> authenticated feed -> the real header bell."""
import base64
import json
import sqlite3
import time
import unittest
import uuid
from contextlib import closing
from pathlib import Path

from ai import account_card as cards, card_interest
from tests import test_account_balances as fixtures
from tests.browser_cdp import Browser
from tests.test_card_interest import SETTINGS
from tests.test_prize_web import CHROME, ROOT


class FinancialNotificationTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.AccountBalanceTests.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.AccountBalanceTests.tearDownClass.__func__)
    start_server=classmethod(fixtures.AccountBalanceTests.start_server.__func__)
    request=classmethod(fixtures.AccountBalanceTests.request.__func__)
    login=classmethod(fixtures.AccountBalanceTests.login.__func__)

    def setUp(self):
        self.username='notice_'+uuid.uuid4().hex[:10]
        self.assertEqual(self.request('/api/register',dict(username=self.username,password='fixture_password'))[0],200)
        self.cookie=self.request('/api/login',dict(username=self.username,password='fixture_password'))[2]['Set-Cookie']
        self.account_id=self.request('/api/store',cookie=self.cookie)[1]['store']['accountId']
        self.db=self.work/'runtime/lotto_web.db'

    def feed(self,cursor=None,cookie=None,extra=''):
        from urllib.parse import urlencode
        code,body,headers=self.request('/api/account/financial-notifications?'+urlencode(cursor or {})+extra,cookie=cookie or self.cookie)
        self.assertEqual(code,200,body)
        self.assertEqual(headers.get('Cache-Control'),'no-store')
        return body

    def audit(self,action,details,stamp='2026-11-01T10:00:00Z'):
        event=uuid.uuid4().hex
        with closing(sqlite3.connect(self.db)) as db,db:
            db.execute('INSERT INTO account_audit VALUES(?,?,?,?,?,?)',(event,self.username,self.username,action,json.dumps(details),stamp))
        return event

    def set_wallet(self,amount=1000000):
        self.assertEqual(self.request('/api/admin/update-assets',dict(username=self.username,paypal=amount,diamond=100),self.admin)[0],200)

    def seed_card(self):
        self.set_wallet()
        for kind,amount in [('topup',400000),('withdraw',100000)]:
            form=dict(kind=kind,amount=amount,requestId=uuid.uuid4().hex)
            self.assertEqual(self.request('/api/account/card-transfer',form,self.cookie)[0],200)
            # Idempotent replay must not create another notification.
            self.assertEqual(self.request('/api/account/card-transfer',form,self.cookie)[0],200)
        event='prediction_reward:'+uuid.uuid4().hex
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('BEGIN IMMEDIATE')
            cards.credit(db,self.account_id,'PayPal',8000,event,'reward','fixture',dict(label='Thưởng dự đoán',description='Loto 5/35 · Kỳ #990'))
            db.execute('INSERT INTO account_audit VALUES(?,?,?,?,?,?)',(event,self.username,self.username,'prediction_card_reward',json.dumps(dict(paypal=8000)), '2026-11-05T12:00:00Z'))
            db.commit()
        start=card_interest.timestamp_ns('2026-11-20T10:00:00Z')
        card_interest.settle(self.db,apply=True,now_ns=start,settings=SETTINGS)
        report=card_interest.settle(self.db,apply=True,now_ns=card_interest.timestamp_ns('2026-11-20T17:00:00Z'),settings=SETTINGS)
        self.assertEqual(report['errors'],[])

    def snapshot(self):
        with closing(sqlite3.connect(self.db)) as db:
            return {t:db.execute('SELECT * FROM '+t+' ORDER BY 1').fetchall() for t in ['account_cards','card_transactions','account_audit','stores','card_interest_days','card_interest_state']}

    def test_committed_transfers_reward_interest_readonly_and_isolation(self):
        self.seed_card()
        before=self.snapshot()
        feed=self.feed()
        self.assertEqual((feed['accountId'],feed['owner']),(self.account_id,self.username))
        card=[e for e in feed['events'] if e['action']=='card-history']
        self.assertEqual(len(card),4)
        self.assertEqual(sum(e['title']=='Thưởng dự đoán' for e in card),1)
        self.assertEqual(sum(e['title']=='Lãi suất thẻ' and '+77 PayPal' in e['detail'] for e in card),1)
        self.assertTrue(any('400.000 PayPal' in e['detail'] and 'Nạp' in e['title'] for e in card))
        self.assertTrue(any('100.000 PayPal' in e['detail'] and 'Rút' in e['title'] for e in card))
        self.assertEqual(self.feed(feed['cursor'])['events'],[])
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.request('/api/admin/update-assets',dict(username=self.username,paypal=700000,diamond=102),self.admin)[0],200)
        changed=self.feed(feed['cursor'])
        self.assertEqual(len(changed['events']),1)
        self.assertIn('+2 kim cương',changed['events'][0]['detail'])
        feed=changed
        foreign=self.feed(cookie=self.member,extra='&accountId='+self.account_id+'&username='+self.username)
        self.assertFalse(any(e['recipientAccountId']==self.account_id for e in foreign['events']))
        self.assertEqual(self.request('/api/account/card-transfer',dict(kind='withdraw',amount=9999999,requestId=uuid.uuid4().hex),self.cookie)[0],400)
        self.assertEqual(self.feed(feed['cursor'])['events'],[])
        self.assertEqual(self.request('/api/account/financial-notifications')[0],401)
        self.assertEqual(self.request('/api/account/financial-notifications',{},self.cookie)[0],405)
        for suffix in ['?auditAfter=-1','?cardAfter=1e3','?wheelAfter=9223372036854775808','?auditAfter=x']:
            self.assertEqual(self.request('/api/account/financial-notifications'+suffix,cookie=self.cookie)[0],400)

    def test_backlog_late_receipts_manual_deduplication_and_safe_payload(self):
        for i in range(215):self.audit('prediction_refunded',dict(id=f'refund-{i}',paypal=i+1))
        self.audit('manual_topup_requested',dict(amount=1000000))
        self.audit('manual_topup_rejected',dict(amount=1000000))
        self.audit('prediction_charged',dict(paypal=100))
        self.audit('redeem_gift_code',dict(code='SECRET-MUST-STAY-PRIVATE',reward=dict(paypal=50,diamond=3)))
        self.audit('prediction_refunded',dict(paypal=0))
        self.audit('vnpay_test_paid',dict(credit=20000))
        found=[];cursor=None;pages=0
        while True:
            report=self.feed(cursor);found.extend(report['events']);cursor=report['cursor'];pages+=1
            if not report['hasMore']:break
            self.assertLess(pages,10)
        self.assertEqual((pages,len(found),len({e['id'] for e in found})),(3,216,216))
        self.assertNotIn('SECRET-MUST-STAY-PRIVATE',json.dumps(found))
        self.assertTrue(any('+3 kim cương' in e['detail'] for e in found))
        # Timestamp predates existing receipts, but row cursor must still deliver it.
        event=self.audit('prediction_refunded',dict(paypal=75),stamp='2020-01-01T00:00:00Z')
        self.assertEqual([e['id'] for e in self.feed(cursor)['events']],['finance:audit:'+event])
        form=dict(mode='account-id',amount=1000000,requestId=uuid.uuid4().hex)
        code,result,_=self.request('/api/payments/manual',form,self.cookie);self.assertEqual(code,200,result)
        order=result['order']['id']
        self.assertFalse(any('deposit-result:'+order in e['id'] for e in self.feed()['events']))
        self.assertEqual(self.request('/api/admin/deposits/review',dict(id=order,action='approve'),self.admin)[0],200)
        notices=self.feed(cursor)['events']
        deposit=[e for e in notices if e['id']=='deposit-result:'+order+':PAID']
        self.assertEqual(len(deposit),1)
        self.assertEqual(deposit[0]['kind'],'deposit')
        self.assertIn('+1.312.500 PayPal',deposit[0]['detail'])
        new_name='renamed_'+uuid.uuid4().hex[:10]
        self.assertEqual(self.request('/api/admin/rename-user',dict(accountId=self.account_id,newUsername=new_name),self.admin)[0],200)
        cookie=self.request('/api/login',dict(username=new_name,password='fixture_password'))[2]['Set-Cookie']
        self.assertEqual(self.feed(cursor,cookie=cookie)['accountId'],self.account_id)

    @unittest.skipUnless(Path(CHROME).exists(),'Chrome required')
    def test_bell_browser_persistence_click_read_delete_and_account_switch(self):
        self.seed_card()
        browser=Browser(CHROME,self.work/('notification-browser-'+self.username));self.addCleanup(browser.close)
        browser.call('Network.enable',page=True)
        browser.call('Page.enable',page=True)
        browser.call('Page.addScriptToEvaluateOnNewDocument',{'source':"window.noticeErrors=[];addEventListener('unhandledrejection',e=>noticeErrors.push(String(e.reason)));addEventListener('error',e=>noticeErrors.push(String(e.message)))"},page=True)
        browser.call('Network.setCookie',dict(name='LOTTO_AUTH',value=self.cookie.split(';')[0].split('=',1)[1],url=self.url),page=True)
        browser.call('Emulation.setDeviceMetricsOverride',dict(width=390,height=844,deviceScaleFactor=1,mobile=False),page=True)
        browser.call('Page.navigate',{'url':self.url+'/'},page=True)
        def wait(expression):
            for _ in range(240):
                if browser.value(expression):return
                time.sleep(.05)
            self.fail(expression)
        wait("typeof VietlottFinancialNotifications!=='undefined' && VietlottFinancialNotifications.items().filter(e=>e.action==='card-history').length===4")
        wait("document.getElementById('pageLoader').classList.contains('hide')")
        before=self.snapshot()
        browser.value("document.getElementById('notificationBtn').click()")
        wait("!document.getElementById('notificationPanel').hidden")
        out=ROOT/'runtime/logs/financial_notifications_20261105';out.mkdir(parents=True,exist_ok=True)
        (out/'all-money-bell-390.png').write_bytes(base64.b64decode(browser.call('Page.captureScreenshot',page=True)['data']))
        self.assertTrue(browser.value("collectHeaderNotifications().some(e=>e.kind==='finance' && e.title==='Lãi suất thẻ' && e.detail.includes('+77 PayPal'))"))
        interest_id=browser.value("collectHeaderNotifications().find(e=>e.title==='Lãi suất thẻ').id")
        browser.value("Array.from(document.querySelectorAll('#notificationList .header-notification-content')).find(e=>e.textContent.includes('Lãi suất thẻ')).click()")
        wait("document.getElementById('walletHistoryDialog').open && !document.getElementById('accountCardHistory').hidden && document.getElementById('cardHistoryRows').textContent.includes('Lãi suất thẻ')")
        browser.value("document.getElementById('walletHistoryClose').click();markHeaderNotificationRead("+json.dumps(interest_id)+");dismissReadHeaderNotifications("+json.dumps(interest_id)+");VietlottFinancialNotifications.refresh()")
        wait("!collectHeaderNotifications().some(e=>e.id==="+json.dumps(interest_id)+")")
        browser.call('Page.reload',{},page=True)
        wait("typeof VietlottFinancialNotifications!=='undefined' && VietlottFinancialNotifications.items().length>=4")
        wait("document.getElementById('pageLoader').classList.contains('hide')")
        self.assertFalse(browser.value("collectHeaderNotifications().some(e=>e.id==="+json.dumps(interest_id)+")"))
        browser.value("document.getElementById('notificationBtn').click()")
        out=ROOT/'runtime/logs/financial_notifications_20261105';out.mkdir(parents=True,exist_ok=True)
        (out/'bell-390.png').write_bytes(base64.b64decode(browser.call('Page.captureScreenshot',page=True)['data']))
        self.assertTrue(browser.value("(()=>{const p=document.getElementById('notificationPanel'),r=p.getBoundingClientRect();return r.left>=0 && r.right<=innerWidth+1 && p.scrollWidth<=p.clientWidth+1})()"))
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(browser.value('noticeErrors'),[])
        # Both the existing deposit provider and new financial feed expose the same receipt ID.
        form=dict(mode='account-id',amount=1000000,requestId=uuid.uuid4().hex)
        result=self.request('/api/payments/manual',form,self.cookie)[1];order=result['order']['id']
        self.assertEqual(self.request('/api/admin/deposits/review',dict(id=order,action='approve'),self.admin)[0],200)
        browser.value('VietlottFinancialNotifications.refresh();VietlottDepositNotifications.refresh()')
        notice='deposit-result:'+order+':PAID'
        wait('VietlottFinancialNotifications.items().some(e=>e.id==='+json.dumps(notice)+') && VietlottDepositNotifications.items().some(e=>e.id==='+json.dumps(notice)+')')
        self.assertEqual(browser.value('collectHeaderNotifications().filter(e=>e.id==='+json.dumps(notice)+').length'),1)
        # Auth event clears financial notices synchronously, including stale archived rows.
        browser.value("currentUser='member_fixture';currentAccountId='111111111111';dispatchEvent(new Event('dvlf:auth-changed'))")
        self.assertEqual(browser.value('VietlottFinancialNotifications.items().length'),0)
        self.assertFalse(browser.value("collectHeaderNotifications().some(e=>e.kind==='finance')"))
