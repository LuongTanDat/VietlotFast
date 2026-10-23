"""Manual deposit review against a disposable server and wallet, never live money."""
import concurrent.futures
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone

from tests import test_account_balances as fixtures
import unittest
import base64
import time
from pathlib import Path
from tests.browser_cdp import Browser
from tests.test_prize_web import CHROME, ROOT


class ManualTopupTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.AccountBalanceTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.AccountBalanceTests.tearDownClass.__func__)
    start_server = classmethod(fixtures.AccountBalanceTests.start_server.__func__)
    request = classmethod(fixtures.AccountBalanceTests.request.__func__)
    login = classmethod(fixtures.AccountBalanceTests.login.__func__)

    def setUp(self):
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db, db:
            db.execute('DELETE FROM manual_topup_details')
            db.execute('DELETE FROM manual_topup_legacy_sources')
            db.execute('DELETE FROM payment_orders')
            db.execute("DELETE FROM account_audit WHERE action LIKE 'manual_topup_%'")
            db.execute("UPDATE stores SET store_json='{}'")

    def draft(self, **overrides):
        result = dict(amount='50000', requestId=uuid.uuid4().hex, email='player@example.test',
                      channel='MB Bank', reference=uuid.uuid4().hex, accountId='100000000000',
                      credit='999999999', username='owner_fixture', status='PAID')
        result.update(overrides)
        return result

    def create(self, form=None, cookie=None):
        code, payload, _ = self.request('/api/payments/manual', form or self.draft(), cookie or self.member)
        self.assertEqual(code, 200, payload)
        return payload['order']

    def wallet(self, cookie=None):
        return self.request('/api/store', cookie=cookie or self.member)[1]['store']

    def restart_server(self):
        self.server.terminate(); self.server.wait(timeout=10)
        self.start_server(); self.login()
        type(self).member = self.request('/api/login', dict(username='member_fixture',password='fixture_password'))[2]['Set-Cookie']

    def review(self, order, action='approve', note='', cookie=None):
        return self.request('/api/admin/deposits/review', dict(id=order['id'], action=action, reviewNote=note), cookie or self.admin)

    def test_permissions_validation_isolation_and_idempotency(self):
        self.assertEqual(self.request('/api/payments/manual')[0], 401)
        self.assertEqual(self.request('/api/admin/deposits', cookie=self.member)[0], 403)
        form = self.draft(sender='Không thu thập',note='Không lưu',transferredAt='bad')
        order = self.create(form)
        self.assertEqual(order['username'], 'member_fixture')
        self.assertEqual(order['status'], 'PENDING')
        self.assertEqual(order['credit'], 63125)
        self.assertEqual(order['accountId'],self.wallet()['accountId'])
        self.assertEqual(order['email'],'player@example.test')
        self.assertEqual((order['sender'],order['note'],order['transferredAt']),('','',''))
        self.assertEqual(self.wallet().get('paypalBalance', 0), 0)
        self.assertEqual(self.create(form)['id'], order['id'])
        self.assertEqual(self.request('/api/payments/manual',dict(form,email='changed@example.test'),self.member)[0],400)
        self.assertEqual(self.request('/api/payments/manual', dict(form, amount=100000), self.member)[0], 400)
        self.assertEqual(self.request('/api/payments/manual', dict(form, requestId=uuid.uuid4().hex), self.admin)[0], 400)
        self.assertEqual(self.request('/api/payments/manual', cookie=self.admin)[1]['orders'], [])
        self.assertEqual(self.request('/api/payments/vnpay/orders', cookie=self.member)[1]['orders'], [])
        self.assertEqual(self.review(order, cookie=self.member)[0], 403)
        self.assertEqual(len(self.request('/api/admin/deposits', cookie=self.admin)[1]['orders']), 1)
        for changes in (dict(amount='9999'), dict(amount='10001'), dict(amount='10001000'),
                        dict(email=''),dict(email='bad'),dict(email='x'*255),
                        dict(email='player@<img>.test'),dict(reference='x'),dict(channel='Khác')):
            self.assertEqual(self.request('/api/payments/manual', self.draft(**changes), self.member)[0], 400, changes)
        self.assertEqual(self.request('/api/admin/deposits/settings', dict(instructions='x'), self.member)[0], 403)
        instructions = 'Ngân hàng thử\nSTK: fixture only\nChủ tài khoản: Kiểm thử'
        self.assertEqual(self.request('/api/admin/deposits/settings', dict(instructions=instructions), self.admin)[0], 200)
        self.assertEqual(self.request('/api/payments/manual', cookie=self.member)[1]['instructions'], instructions)

    def test_account_id_memo_only_is_authoritative_idempotent_and_payable(self):
        form=dict(mode='account-id',amount=50000,requestId=uuid.uuid4().hex,accountId='100000000000',
                  transferMemo='100000000000',email='ignored@example.test',channel='ignored',reference='ignored')
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            orders=list(pool.map(lambda _:self.create(form),range(12)))
        order=orders[0]
        self.assertTrue(all(item['id']==order['id'] for item in orders))
        self.assertEqual(order['transferMemo'],self.wallet()['accountId'])
        self.assertEqual(order['transferMemo'],order['accountId'])
        self.assertEqual((order['email'],order['channel'],order['reference']),('','',''))
        self.assertEqual(self.wallet().get('paypalBalance',0),0)
        self.assertEqual(self.request('/api/payments/manual',dict(form,amount=100000),self.member)[0],400)
        other=self.create(form,cookie=self.admin)
        self.assertEqual(other['transferMemo'],self.wallet(self.admin)['accountId'])
        self.assertNotEqual(other['transferMemo'],order['transferMemo'])
        for _ in range(2):self.assertEqual(self.review(order)[0],200)
        self.assertEqual(self.wallet()['paypalBalance'],63125)
        again=self.create(dict(form,requestId=uuid.uuid4().hex))
        self.assertNotEqual(again['id'],order['id'])
        self.assertEqual(again['status'],'PENDING')
        self.assertEqual(self.wallet()['paypalBalance'],63125)

    def test_custom_bonus_boundaries_and_locked_order_quotes(self):
        orders = {}
        forms = {}
        metadata = self.request('/api/payments/manual',cookie=self.member)[1]
        self.assertEqual((metadata['minimum'],metadata['maximum'],metadata['step']),(1000000,100000000,100000))
        for invalid in (10000,501000,900000,1000001,1050000,9999000,100100000):
            self.assertEqual(self.request('/api/payments/manual',self.draft(amount=str(invalid)),self.member)[0],400)
        for amount, bonus, credit in [(500000,15625,640625), (1100000,68750,1443750),
                                      (1000000,62500,1312500), (99900000,6243750,131118750),
                                      (100000000,6250000,131250000)]:
            form = self.draft(amount=str(amount))
            order = self.create(form)
            self.assertEqual((order['baseCredit'],order['bonusCredit'],order['credit']),
                             (amount*5//4,bonus,credit))
            self.assertEqual(self.create(form)['id'],order['id'])
            orders[amount], forms[amount] = order, form
        self.assertEqual(self.wallet().get('paypalBalance',0),0)
        self.assertEqual(self.request('/api/payments/manual',self.draft(amount='10001000'),self.member)[0],400)
        for _ in range(2): self.assertEqual(self.review(orders[100000000])[0],200)
        self.assertEqual(self.wallet()['paypalBalance'],131250000)
        # Model an order quoted before this promotion: retries/approval use its saved credit.
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db, db:
            db.execute('UPDATE payment_orders SET bonus_credit=0,credit=base_credit WHERE id=?',
                       (orders[1000000]['id'],))
        self.assertEqual(self.create(forms[1000000])['credit'],1250000)
        self.assertEqual(self.review(orders[1000000])[0],200)
        self.assertEqual(self.wallet()['paypalBalance'],132500000)
        # Retrying a real old quote outside the new range must still return it.
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db, db:
            db.execute('UPDATE payment_orders SET amount=501000,base_credit=626250,bonus_credit=31313,credit=657563 WHERE id=?',
                       (orders[500000]['id'],))
        old = self.create(dict(forms[500000],amount='501000'))
        self.assertEqual(old['credit'],657563)
        self.assertEqual(self.review(old)[0],200)
        self.assertEqual(self.wallet()['paypalBalance'],133157563)

    def test_old_request_retry_and_email_schema_upgrade_preserve_order(self):
        form=self.draft()
        order=self.create(form)
        old=dict(form,sender='Người chuyển cũ',note='Ghi chú cũ',transferredAt='2026-03-11T14:40:00Z')
        old.pop('email')
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db, db:
            db.execute('UPDATE manual_topup_details SET sender=?,note=?,transferred_at=? WHERE order_id=?',
                       (old['sender'],old['note'],old['transferredAt'],order['id']))
            db.execute('ALTER TABLE manual_topup_details DROP COLUMN email')
        self.restart_server()
        migrated=self.create(old)
        self.assertEqual((migrated['id'],migrated['credit'],migrated['email']),(order['id'],63125,''))
        self.assertEqual(migrated['sender'],old['sender'])
        self.assertEqual(migrated['transferredAt'],old['transferredAt'])
        self.assertEqual(self.wallet().get('paypalBalance',0),0)
        self.assertEqual(self.request('/api/payments/manual',dict(old,requestId=uuid.uuid4().hex,reference=uuid.uuid4().hex),self.member)[0],400)
        self.assertEqual(len(self.request('/api/payments/manual',cookie=self.member)[1]['orders']),1)
        for _ in range(2):self.assertEqual(self.review(migrated)[0],200)
        self.assertEqual(self.wallet()['paypalBalance'],63125)

    def test_atomic_exactly_once_approval_rejection_and_store_replay(self):
        order = self.create()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            replies = list(pool.map(lambda _: self.review(order), range(16)))
        self.assertTrue(all(code == 200 for code, _, _ in replies), replies)
        self.assertEqual(self.wallet()['paypalBalance'], 63125)
        self.assertEqual(self.wallet()['walletVersion'], 1)
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM account_audit WHERE action='manual_topup_credit'").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT amount FROM payment_orders WHERE environment='manual' AND status='PAID' AND paid_at<>''").fetchone()[0], 50000)
        self.request('/api/store', dict(store=json.dumps({'paypalBalance':999999999,'walletVersion':99,'paymentOrders':[{'status':'PAID'}]})), self.member)
        self.assertEqual(self.wallet()['paypalBalance'], 63125)
        self.assertEqual(self.review(order, 'reject', 'Không nhận được tiền')[0], 400)
        rejected = self.create()
        self.assertEqual(self.review(rejected, 'reject')[0], 400)
        self.assertEqual(self.review(rejected, 'reject', 'Không tìm thấy giao dịch')[0], 200)
        self.assertEqual(self.review(rejected)[0], 400)
        own = self.request('/api/payments/manual', cookie=self.member)[1]['orders']
        self.assertEqual(next(row for row in own if row['id']==rejected['id'])['reviewNote'], 'Không tìm thấy giao dịch')
        self.assertEqual(self.wallet()['paypalBalance'], 63125)

    def test_pending_limit_overflow_and_disabled_account_rollback(self):
        order = self.create()
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db, db:
            db.execute("UPDATE stores SET store_json=? WHERE username='member_fixture'", (json.dumps({'paypalBalance':9007199254740991}),))
        self.assertEqual(self.review(order)[0], 400)
        self.assertEqual(self.request('/api/payments/manual', cookie=self.member)[1]['orders'][0]['status'], 'PENDING')
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db, db:
            db.execute("UPDATE users SET enabled=0 WHERE username='member_fixture'")
        try:
            self.assertEqual(self.review(order)[0], 400)
        finally:
            with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db, db:
                db.execute("UPDATE users SET enabled=1 WHERE username='member_fixture'")
                db.execute("UPDATE stores SET store_json='{}' WHERE username='member_fixture'")
        for _ in range(4): self.create()
        self.assertEqual(self.request('/api/payments/manual', self.draft(), self.member)[0], 400)
        self.assertEqual(self.review(order)[0], 200)
        self.assertEqual(self.wallet()['paypalBalance'], 63125)
        self.create()

    def test_legacy_requests_migrate_without_credit_or_duplicate_and_survive_restart(self):
        legacy = dict(id='old-receipt',amount=100000,createdAt='2026-03-11T14:46:10Z',
                      timeText='21:46:10 11/3/2026',txnTime='2026-03-11T21:40',
                      senderName='Người chuyển cũ',email='fixture@example.test',
                      txnCode='LEGACY-100K',note='Cần kiểm tra',status='Chờ xử lý')
        no_id = dict(legacy,amount=1000000,txnCode='LEGACY-NO-ID',createdAt='',txnTime='')
        no_id.pop('id')
        entries = [legacy,dict(legacy,id='duplicate-receipt'),no_id]
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db, db:
            db.execute("UPDATE stores SET store_json=? WHERE username='member_fixture'",(json.dumps(dict(paypalBalance=750,walletVersion=7,paypalTopups=entries)),))
            db.execute("UPDATE stores SET store_json=? WHERE username='owner_fixture'",(json.dumps(dict(paypalTopups=[dict(legacy,txnCode='ADMIN-OTHER-REF')])),))
        self.restart_server()
        response = self.request('/api/payments/manual',cookie=self.member)[1]
        self.assertEqual(len(response['orders']),2)
        self.assertEqual(len(response['legacyKeys']),3)
        self.assertEqual(self.wallet()['paypalBalance'],750)
        self.assertEqual(self.wallet()['walletVersion'],7)
        order = next(item for item in response['orders'] if item['amount']==100000)
        self.assertEqual(order['status'],'PENDING')
        self.assertEqual(order['sender'],'Người chuyển cũ')
        self.assertEqual(order['legacyEmail'],'fixture@example.test')
        self.assertEqual(order['transferredAt'],'2026-03-11T14:40:00Z')
        self.assertEqual(order['createdAt'],'2026-03-11T14:46:10Z')
        self.assertEqual(order['credit'],126875)
        self.assertEqual(next(item for item in response['orders'] if item['amount']==1000000)['credit'],1250000)
        admin = self.request('/api/admin/deposits',cookie=self.admin)[1]
        self.assertEqual(admin['total'],3)
        self.assertEqual(self.request('/api/payments/manual',cookie=self.admin)[1]['legacyKeys'],['id:old-receipt'])
        # Old client snapshots cannot rewrite or inject a second migration source.
        self.request('/api/store',dict(store=json.dumps(dict(paypalTopups=[dict(legacy,id='forged',amount=500000)]))),self.member)
        self.assertEqual(self.wallet()['paypalTopups'],entries)
        self.assertEqual(self.request('/api/payments/manual',self.draft(reference=legacy['txnCode']),self.member)[0],400)
        self.assertEqual(self.review(order)[0],200)
        self.restart_server()
        response = self.request('/api/payments/manual',cookie=self.member)[1]
        self.assertEqual(len(response['orders']),2)
        self.assertEqual(len(response['legacyKeys']),3)
        self.assertEqual(self.wallet()['paypalBalance'],127625)
        self.assertEqual(self.wallet()['walletVersion'],8)
        self.assertEqual(self.review(order)[0],200)
        self.assertEqual(self.wallet()['paypalBalance'],127625)

    def test_legacy_receipt_links_to_existing_order_and_blocks_cross_account_duplicate_credit(self):
        form = self.draft()
        paid = self.create(form)
        self.assertEqual(self.review(paid)[0],200)
        legacy = dict(id='already-submitted',amount=50000,txnCode=form['reference'],status='Chờ xử lý')
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db, db:
            wallet = self.wallet()
            wallet['paypalTopups']=[legacy]
            db.execute("UPDATE stores SET store_json=? WHERE username='member_fixture'",(json.dumps(wallet),))
            db.execute("UPDATE stores SET store_json=? WHERE username='owner_fixture'",(json.dumps(dict(paypalTopups=[legacy])),))
        self.restart_server()
        own = self.request('/api/payments/manual',cookie=self.member)[1]
        self.assertEqual(len(own['orders']),1)
        self.assertEqual(own['orders'][0]['id'],paid['id'])
        self.assertEqual(own['orders'][0]['status'],'PAID')
        other = self.request('/api/payments/manual',cookie=self.admin)[1]['orders'][0]
        self.assertEqual(self.review(other)[0],400)
        self.assertEqual(self.wallet(self.admin).get('paypalBalance',0),0)
        self.restart_server()
        self.assertEqual(len(self.request('/api/payments/manual',cookie=self.member)[1]['orders']),1)
        self.assertEqual(self.wallet()['paypalBalance'],63125)

    @unittest.skipUnless(Path(CHROME).exists(), 'Chrome required')
    def test_browser_manual_request_admin_review_and_responsive_modes(self):
        instructions = 'Ngân hàng kiểm thử\nSố tài khoản: fixture-only\nKhông chuyển tiền thật'
        self.request('/api/admin/deposits/settings', dict(instructions=instructions), self.admin)
        browser = Browser(CHROME, self.work/'manual-topup-browser')
        def wait(expression):
            for _ in range(200):
                if browser.value(expression): return
                time.sleep(.05)
            self.fail('Browser timeout: '+expression+' '+str(browser.value('window.topupErrors')))
        def login(cookie, path):
            browser.call('Network.setCookie', {'name':'LOTTO_AUTH','value':cookie.split('=',1)[1].split(';',1)[0], 'url':self.url}, page=True)
            browser.call('Page.navigate', {'url':self.url+path}, page=True)
        images = ROOT/'Bin/session_1_latest/manual_topup_images'
        images.mkdir(exist_ok=True)
        try:
            browser.call('Page.enable',page=True); browser.call('Network.enable',page=True)
            browser.call('Page.addScriptToEvaluateOnNewDocument', {'source':"window.topupErrors=[];addEventListener('error',e=>topupErrors.push(e.message));addEventListener('unhandledrejection',e=>topupErrors.push(String(e.reason)));const realFetch=window.fetch;window.fetch=(input,opts)=>{const url=new URL(typeof input==='string'?input:input.url,location.href);if(url.pathname.startsWith('/api/live-'))return Promise.resolve(new Response(JSON.stringify({ok:true,results:[],rows:[],history:[],meta:{}}),{headers:{'Content-Type':'application/json'}}));return realFetch(input,opts)}"},page=True)
            login(self.member, '/nap-tien')
            wait("typeof currentUser!=='undefined' && currentUser==='member_fixture' && !document.getElementById('depositManualSubmit').disabled")
            self.assertFalse(browser.value("document.getElementById('depositManualPane').hidden"))
            self.assertEqual(browser.value("document.getElementById('depositManualInstructions').textContent"), instructions)
            self.assertEqual(browser.value("document.querySelectorAll('#adminPanelSection [data-admin-view=deposits]').length"), 1)
            self.assertTrue(browser.value("document.getElementById('adminPanelSection').hidden"))
            self.assertEqual(browser.value("[...document.getElementById('manualDepositForm').elements].filter(e=>e.name).map(e=>e.name)"),['transferMemo'])
            self.assertEqual(browser.value("document.getElementById('depositManualAccountId').value"),self.wallet()['accountId'])
            self.assertTrue(browser.value("document.getElementById('depositManualAccountId').readOnly"))
            browser.value("window.copiedMemo=null;Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async value=>{window.copiedMemo=value}}});document.getElementById('depositMemoCopy').click()")
            wait("window.copiedMemo===currentAccountId")
            browser.value("document.querySelector('[data-package-id=starter]').click();document.getElementById('manualDepositForm').requestSubmit()")
            wait("document.getElementById('depositHistoryList').textContent.includes('Chờ admin duyệt')")
            self.assertEqual(self.wallet().get('paypalBalance',0),0)
            self.assertEqual(browser.value("document.querySelectorAll('#depositHistoryList img').length"),0)
            browser.value("document.getElementById('depositFastTab').click()")
            self.assertTrue(browser.value("document.getElementById('depositManualPane').hidden && !document.getElementById('depositFastPane').hidden && document.getElementById('depositCreateBtn').disabled"))
            for width in (320,390,768,1440):
                browser.call('Emulation.setDeviceMetricsOverride',dict(width=width,height=1000,deviceScaleFactor=1,mobile=False),page=True)
                for mode in ('manual','fast'):
                    browser.value(f"document.querySelector('[data-deposit-mode={mode}]').click()")
                    for light in (False,True):
                        browser.value(f'document.body.classList.toggle("light-theme",{str(light).lower()})')
                        self.assertTrue(browser.value("document.documentElement.scrollWidth<=innerWidth+1 && [...document.querySelectorAll('#paypalDepositSection .deposit-package-card,#paypalDepositSection .deposit-form-card')].every(el=>el.scrollWidth<=el.clientWidth+1)"),(width,mode,light))
                        if (width,mode,light) in ((1440,'manual',False),(390,'fast',True)):
                            shot=browser.call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True),page=True)
                            (images/f'{mode}_{width}_{light}.png').write_bytes(base64.b64decode(shot['data']))
            self.assertEqual(browser.value('topupErrors'),[])
            login(self.admin, '/admin')
            wait("typeof currentUserRole!=='undefined' && currentUserRole==='admin' && !!window.adminPanel")
            browser.value("document.querySelector('[data-admin-view=deposits]').click()")
            wait("!!document.querySelector('[data-review-start]') && document.getElementById('pageLoader').classList.contains('hide')")
            self.assertEqual(browser.value("document.querySelectorAll('#adminDepositRows img').length"),0)
            self.assertTrue(browser.value("document.getElementById('adminDepositRows').textContent.includes('Nội dung chuyển khoản')"))
            self.assertTrue(browser.value("document.getElementById('adminDepositRows').textContent.includes("+json.dumps(self.wallet()['accountId'])+")"))
            for width in (320,768,1440):
                browser.call('Emulation.setDeviceMetricsOverride',dict(width=width,height=1000,deviceScaleFactor=1,mobile=False),page=True)
                self.assertTrue(browser.value("document.documentElement.scrollWidth<=innerWidth+1 && document.getElementById('adminDepositRows').scrollWidth<=document.getElementById('adminDepositRows').clientWidth+1"),width)
            browser.value("document.querySelector('[data-review-start]').click()")
            self.assertEqual(self.wallet().get('paypalBalance',0),0)
            self.assertFalse(browser.value("document.querySelector('.admin-deposit-confirm').hidden"))
            wait("getComputedStyle(document.getElementById('pageLoader')).opacity==='0'")
            shot=browser.call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True),page=True)
            (images/'admin_confirmation_1440.png').write_bytes(base64.b64decode(shot['data']))
            browser.value("document.querySelector('[data-review=approve]').click()")
            wait("document.getElementById('adminDepositRows').textContent.includes('Đã xử lý hết yêu cầu')")
            self.assertEqual(self.wallet()['paypalBalance'],63125)
            self.assertEqual(browser.value('topupErrors'),[])
            login(self.member, '/nap-tien')
            wait("document.getElementById('depositHistoryList')?.textContent.includes('Đã cộng ví')")
            self.assertEqual(browser.value("document.getElementById('depositPaypalBalance').textContent"),'63.125')
            browser.value("document.querySelector('[data-package-id=starter]').click();document.getElementById('manualDepositForm').requestSubmit()")
            wait("document.getElementById('depositHistoryList').textContent.includes('Chờ admin duyệt')")
            self.assertEqual(self.wallet()['paypalBalance'],63125)
            self.assertEqual(len(self.request('/api/payments/manual',cookie=self.member)[1]['orders']),2)
            proof = dict(ok=True,liveDatabaseUsed=False,realPaymentSent=False,manualRequestPendingWithoutCredit=True,adminConfirmationRequired=True,adminCreditVisibleToPlayer=True,escapedTransferInformation=True,responsiveDepositLayouts=16,responsiveAdminLayouts=3)
            (ROOT/'Bin/session_1_latest/manual_topup_browser_verification.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')
        finally:
            browser.close()

    @unittest.skipUnless(Path(CHROME).exists(), 'Chrome required')
    def test_admin_history_and_two_way_notifications(self):
        admin = Browser(CHROME, self.work/'deposit-notice-admin')
        player = Browser(CHROME, self.work/'deposit-notice-player')
        images = ROOT/'Bin/session_1_latest/admin_deposit_redesign_images'; images.mkdir(exist_ok=True)
        def wait(browser, expression):
            for _ in range(300):
                if browser.value(expression): return
                time.sleep(.05)
            self.fail('Notification timeout: '+expression+' '+str(browser.value('window.depositTestErrors')))
        def login(browser, cookie, path):
            browser.call('Page.enable',page=True); browser.call('Network.enable',page=True)
            browser.call('Page.addScriptToEvaluateOnNewDocument',{'source':"window.depositTestErrors=[];addEventListener('error',e=>depositTestErrors.push(e.message));addEventListener('unhandledrejection',e=>depositTestErrors.push(String(e.reason)));const realFetch=fetch;window.fetch=(url,opts)=>String(url).startsWith('/api/live-')?Promise.resolve(new Response(JSON.stringify({ok:true,results:[],rows:[],history:[],meta:{}}),{headers:{'Content-Type':'application/json'}})):realFetch(url,opts)"},page=True)
            browser.call('Network.setCookie',{'name':'LOTTO_AUTH','value':cookie.split('=',1)[1].split(';',1)[0],'url':self.url},page=True)
            browser.call('Page.navigate',{'url':self.url+path},page=True)
            wait(browser,"!!window.VietlottDepositNotifications&&typeof currentUser!=='undefined'&&!!currentUser&&document.getElementById('pageLoader').classList.contains('hide')")
        try:
            login(admin,self.admin,'/admin'); login(player,self.member,'/')
            order=self.create(self.draft(mode='account-id',amount='100000000'))
            admin.value('VietlottDepositNotifications.refresh()')
            wait(admin,"VietlottDepositNotifications.items().some(i=>i.audience==='admin')")
            self.assertEqual(admin.value("document.getElementById('adminDepositNavBadge').textContent"),'1')
            self.assertTrue(admin.value("collectHeaderNotifications().some(i=>i.kind==='deposit'&&i.title==='Có yêu cầu nạp mới')"))
            self.assertTrue(admin.value("!document.querySelector('.deposit-notification-toast').hidden"))
            admin.value("document.querySelector('[data-admin-view=deposits]').click();document.getElementById('adminDepositNotifications').click()")
            wait(admin,"document.getElementById('depositNotificationDialog').open&&!!document.querySelector('[data-deposit-notification-id]')")
            self.assertFalse(player.value("VietlottDepositNotifications.items().some(i=>i.audience==='admin')"))
            admin.value("document.querySelector('[data-deposit-notification-id]').click()")
            wait(admin,"!document.getElementById('depositNotificationDialog').open&&!!document.querySelector('[data-review-start]')")
            self.assertTrue(admin.value("getReadHeaderNotificationIds().has("+json.dumps('deposit-request:'+order['id'])+")"))
            for width in (320,390,768,1024,1440):
                admin.call('Emulation.setDeviceMetricsOverride',dict(width=width,height=1100,deviceScaleFactor=1,mobile=False),page=True)
                for light in (False,True):
                    admin.value(f'document.body.classList.toggle("light-theme",{str(light).lower()})')
                    self.assertTrue(admin.value("document.documentElement.scrollWidth<=innerWidth+1&&[...document.querySelectorAll('.admin-deposit-item,.admin-deposit-tools,.admin-deposit-amount')].every(e=>e.scrollWidth<=e.clientWidth+1)"),(width,light))
                    self.assertTrue(admin.value("document.querySelector('.admin-deposit-item .admin-status').getBoundingClientRect().height<35"))
                    if (width,light) in ((390,True),(1440,False)):
                        shot=admin.call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True),page=True)
                        (images/f'queue_{width}.png').write_bytes(base64.b64decode(shot['data']))
            admin.value("document.querySelector('[data-review-start]').click();document.querySelector('[data-review=approve]').click()")
            wait(admin,"document.getElementById('adminDepositRows').textContent.includes('Đã xử lý hết yêu cầu')")
            self.assertEqual(self.wallet()['paypalBalance'],131250000)
            player.value('VietlottDepositNotifications.refresh()')
            wait(player,"VietlottDepositNotifications.items().some(i=>i.title==='Nạp tiền thành công')")
            self.assertEqual(player.value('store.paypalBalance'),131250000)
            self.assertTrue(player.value("collectHeaderNotifications().some(i=>i.kind==='deposit'&&i.detail.includes('131.250.000'))"))
            self.assertTrue(player.value("!document.querySelector('.deposit-notification-toast').hidden"))
            admin.value("document.getElementById('adminDepositHistoryOpen').click()")
            wait(admin,"document.querySelector('#adminDepositHistoryRows table')?.textContent.includes('131.250.000')")
            for width in (320,390,768,1440):
                admin.call('Emulation.setDeviceMetricsOverride',dict(width=width,height=1100,deviceScaleFactor=1,mobile=False),page=True)
                self.assertTrue(admin.value("(()=>{const d=document.getElementById('adminDepositHistoryDialog'),r=d.getBoundingClientRect();return d.open&&r.left>=0&&r.right<=innerWidth&&r.bottom<=innerHeight&&d.scrollWidth<=d.clientWidth+1})()"),width)
                if width in (390,1440):
                    shot=admin.call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=False),page=True)
                    (images/f'history_{width}.png').write_bytes(base64.b64decode(shot['data']))
            admin.value("document.getElementById('adminDepositHistoryStatus').value='REJECTED';document.getElementById('adminDepositHistoryStatus').dispatchEvent(new Event('change'))")
            wait(admin,"document.getElementById('adminDepositHistoryRows').textContent.includes('Chưa có giao dịch')")
            rejected=self.create(self.draft(mode='account-id'))
            self.assertEqual(self.review(rejected,'reject','Không tìm thấy giao dịch <img src=x>')[0],200)
            player.value('VietlottDepositNotifications.refresh()')
            wait(player,"VietlottDepositNotifications.items().some(i=>i.title==='Yêu cầu nạp đã bị từ chối')")
            self.assertEqual(player.value('store.paypalBalance'),131250000)
            self.assertEqual(player.value("document.querySelectorAll('.deposit-notification-toast img').length"),0)
            player.value("VietlottDepositNotifications.open()")
            wait(player,"document.getElementById('depositNotificationDialog').open")
            player.value("document.querySelector('[data-deposit-notification-id]').click()")
            wait(player,"location.pathname==='/nap-tien'&&document.getElementById('depositHistoryDialog').open")
            self.assertTrue(player.value("getReadHeaderNotificationIds().has('deposit-result:"+rejected['id']+":REJECTED')"))
            player.value("window.foreignDeposit={id:'foreign-fixture',kind:'deposit',audience:'user',action:'deposit-history',recipientAccountId:'111111111111',title:'Không được hiển thị',detail:'Private',timestamp:Date.now()};writeHeaderNotificationValue(HEADER_NOTIFICATION_HISTORY_KEY,[...collectHeaderNotifications(),foreignDeposit])")
            self.assertFalse(player.value("collectHeaderNotifications().some(i=>i.id==='foreign-fixture')"))
            self.assertFalse(player.value("getReadHeaderNotificationIds().has('deposit-request:"+order['id']+"')"))
            player.value("document.getElementById('depositHistoryDialog').close();currentUser=null;currentUserRole='';currentAccountId='';window.dispatchEvent(new Event('dvlf:auth-changed'))")
            self.assertEqual(player.value('VietlottDepositNotifications.items().length'),0)
            self.assertTrue(player.value("document.querySelector('.deposit-notification-toast').hidden&&!document.getElementById('depositNotificationDialog').open"))
            self.assertEqual(admin.value('depositTestErrors'),[]);self.assertEqual(player.value('depositTestErrors'),[])
        finally:
            admin.close();player.close()

    def test_rename_delete_and_restart_preserve_reviews(self):
        # Dedicated account keeps other fixtures stable.
        name = 'manual_'+uuid.uuid4().hex[:10]
        self.request('/api/register', dict(username=name, password='fixture_password'))
        cookie = self.request('/api/login', dict(username=name, password='fixture_password'))[2]['Set-Cookie']
        paid = self.create(cookie=cookie)
        renamed = name+'_new'
        self.assertEqual(self.request('/api/admin/rename-user', dict(username=name,newUsername=renamed), self.admin)[0], 200)
        self.assertEqual(self.review(paid)[0], 200)
        cookie = self.request('/api/login', dict(username=renamed,password='fixture_password'))[2]['Set-Cookie']
        pending = self.create(cookie=cookie)
        self.assertEqual(self.request('/api/admin/delete-user', dict(username=renamed), self.admin)[0], 200)
        self.assertEqual(self.review(pending)[0], 400)
        self.request('/api/register', dict(username=renamed,password='fixture_password'))
        cookie = self.request('/api/login', dict(username=renamed,password='fixture_password'))[2]['Set-Cookie']
        self.assertEqual(self.request('/api/payments/manual',cookie=cookie)[1]['orders'], [])
        self.assertEqual(self.wallet(cookie).get('paypalBalance',0), 0)
        order = self.create()
        self.review(order)
        self.restart_server()
        self.assertEqual(self.review(order)[0], 200)
        self.assertEqual(self.wallet()['paypalBalance'], 63125)
