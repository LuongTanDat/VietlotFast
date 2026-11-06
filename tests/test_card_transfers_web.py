"""Wallet/card transfers use disposable accounts, money, Java and Chrome."""
import base64
import json
import sqlite3
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from ai import account_card as cards
from tests import test_account_balances as fixtures
from tests.browser_cdp import Browser
from tests.test_prize_web import ROOT, CHROME


class CardTransferTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.AccountBalanceTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.AccountBalanceTests.tearDownClass.__func__)
    start_server = classmethod(fixtures.AccountBalanceTests.start_server.__func__)
    request = classmethod(fixtures.AccountBalanceTests.request.__func__)
    login = classmethod(fixtures.AccountBalanceTests.login.__func__)

    def setUp(self):
        self.username = 'transfer_' + uuid.uuid4().hex[:10]
        self.db = self.work / 'runtime/lotto_web.db'
        self.assertEqual(self.request('/api/register', dict(username=self.username, password='fixture_password'))[0], 200)
        self.cookie = self.request('/api/login', dict(username=self.username, password='fixture_password'))[2]['Set-Cookie']
        self.identity = self.request('/api/store', cookie=self.cookie)[1]['store']['accountId']
        self.fund(1000000)

    def fund(self, amount):
        self.assertEqual(self.request('/api/admin/update-assets', dict(username=self.username, diamond=500, paypal=amount), self.admin)[0], 200)

    def transfer(self, kind, amount, key=None, **extra):
        form = dict(kind=kind, amount=amount, requestId=key or uuid.uuid4().hex)
        form.update(extra)
        return self.request('/api/account/card-transfer', form, self.cookie)

    def snapshot(self):
        with closing(sqlite3.connect(self.db)) as db:
            return dict(wallet=db.execute('SELECT store_json FROM stores WHERE username=?', (self.username,)).fetchone()[0],
                        card=db.execute('SELECT * FROM account_cards WHERE account_id=?', (self.identity,)).fetchall(),
                        transactions=db.execute('SELECT * FROM card_transactions WHERE account_id=? ORDER BY event_id', (self.identity,)).fetchall(),
                        audit=db.execute('SELECT * FROM account_audit WHERE target=? ORDER BY event_id', (self.username,)).fetchall())

    def money(self):
        report = self.request('/api/account/card', cookie=self.cookie)[1]
        return int(report['walletBalance']), int(report['card']['balance'])

    def test_conservation_histories_replay_and_owner_isolation(self):
        key = uuid.uuid4().hex
        result = self.transfer('topup', 125000, key, accountId='100000000000', username='owner_fixture')
        self.assertEqual(result[0], 200, result[1])
        self.assertEqual((result[1]['balance'], result[1]['cardBalance'], result[1]['replayed']), ('875000', '125000', False))
        self.assertEqual(self.transfer('withdraw', 25000)[0], 200)
        self.assertEqual(self.money(), (900000, 100000))
        before = self.snapshot()
        replay = self.transfer('topup', 125000, key)
        self.assertEqual((replay[0], replay[1]['replayed'], replay[1]['balance']), (200, True, '900000'))
        self.assertEqual(self.snapshot(), before)
        for kind, amount in [('withdraw', 125000), ('topup', 125001)]:
            self.assertEqual(self.transfer(kind, amount, key)[0], 400)
            self.assertEqual(self.snapshot(), before)
        report = self.request('/api/account/card?history=1', cookie=self.cookie)[1]
        self.assertEqual({(r['kind'], r['delta']) for r in report['events']}, {('topup', '125000'), ('withdraw', '-25000')})
        history = self.request('/api/account/wallet-history?kind=other', cookie=self.cookie)[1]['events']
        self.assertTrue({('Nạp vào thẻ', '-125000'), ('Rút từ thẻ về ví', '25000')} <= {(r['label'], r['delta']) for r in history})
        other = self.request('/api/account/card?history=1&accountId=' + self.identity, cookie=self.member)[1]
        self.assertEqual((other['total'], other['card']['balance']), (0, '0'))
        self.assertEqual(self.snapshot(), before)

    def test_validation_origin_auth_and_insufficient_funds_write_nothing(self):
        before = self.snapshot()
        self.assertEqual(self.request('/api/account/card-transfer', dict(kind='topup', amount=1, requestId=uuid.uuid4().hex))[0], 401)
        self.assertEqual(self.request('/api/account/card-transfer', cookie=self.cookie)[0], 405)
        self.assertEqual(self.request('/api/account/card-transfer/bad', dict(), self.cookie)[0], 404)
        for amount in ['', 0, -1, '1.25', '1e5', '1.000', '9007199254740992', '9' * 100, 1000001]:
            self.assertEqual(self.transfer('topup', amount)[0], 400, amount)
        self.assertEqual(self.transfer('withdraw', 1)[0], 400)
        self.assertEqual(self.transfer('reward', 1)[0], 400)
        self.assertEqual(self.transfer('topup', 1, 'bad')[0], 400)
        req = urllib.request.Request(self.url + '/api/account/card-transfer',
              data=urllib.parse.urlencode(dict(kind='topup', amount=1, requestId=uuid.uuid4().hex)).encode(),
              headers={'Cookie': self.cookie, 'Origin': 'https://untrusted.example', 'Content-Type': 'application/x-www-form-urlencoded'})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(error.exception.code, 403)
        error.exception.close()
        self.assertEqual(self.snapshot(), before)

    def test_large_integer_balances_and_destination_limits(self):
        self.fund(4553502331749)
        self.assertEqual(self.transfer('topup', '4553502331749')[0], 200)
        self.assertEqual(self.money(), (0, 4553502331749))
        self.assertEqual(self.transfer('withdraw', '4553502331748')[0], 200)
        self.assertEqual(self.money(), (4553502331748, 1))
        self.fund(9007199254740991)
        before = self.snapshot()
        self.assertEqual(self.transfer('withdraw', 1)[0], 400)
        self.assertEqual(self.snapshot(), before)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE account_cards SET balance=9007199254740991 WHERE account_id=?', (self.identity,))
        before = self.snapshot()
        self.assertEqual(self.transfer('topup', 1)[0], 400)
        self.assertEqual(self.snapshot(), before)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE account_cards SET currency='VNĐ' WHERE account_id=?", (self.identity,))
        before = self.snapshot()
        self.assertEqual(self.transfer('withdraw', 1)[0], 400)
        self.assertEqual(self.snapshot(), before)

    def test_concurrent_retries_and_overspending(self):
        key = uuid.uuid4().hex
        with ThreadPoolExecutor(max_workers=6) as pool:
            reports = list(pool.map(lambda _: self.transfer('topup', 200000, key), range(12)))
        self.assertTrue(all(r[0] == 200 for r in reports), reports)
        self.assertEqual(sum(not r[1]['replayed'] for r in reports), 1)
        self.assertEqual(self.money(), (800000, 200000))
        with ThreadPoolExecutor(max_workers=6) as pool:
            reports = list(pool.map(lambda _: self.transfer('topup', 300000), range(6)))
        self.assertEqual(sum(r[0] == 200 for r in reports), 2)
        self.assertEqual(sum(r[0] == 400 for r in reports), 4)
        self.assertEqual(self.money(), (200000, 800000))
        self.assertEqual(len(self.snapshot()['transactions']), 3)

    def test_audit_failure_rolls_back_both_balances_then_same_request_can_retry(self):
        key = uuid.uuid4().hex
        before = self.snapshot()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("CREATE TRIGGER fail_card_transfer BEFORE INSERT ON account_audit WHEN NEW.action='card_topup' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        try:
            self.assertEqual(self.transfer('topup', 100000, key)[0], 500)
            self.assertEqual(self.snapshot(), before)
        finally:
            with closing(sqlite3.connect(self.db)) as db, db:
                db.execute('DROP TRIGGER fail_card_transfer')
        self.assertEqual(self.transfer('topup', 100000, key)[0], 200)
        self.assertEqual(self.money(), (900000, 100000))

    def test_transfer_waits_for_concurrent_reward_without_losing_it(self):
        self.assertEqual(self.transfer('topup', 100000)[0], 200)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with closing(sqlite3.connect(self.db)) as db:
                db.execute('BEGIN IMMEDIATE')
                cards.credit(db, self.identity, 'PayPal', 777, 'fixture-reward:' + self.identity,
                             'reward', 'fixture-reward', {'label': 'Concurrent reward fixture'})
                future = pool.submit(self.transfer, 'withdraw', 777)
                try:
                    time.sleep(.2)
                    self.assertFalse(future.done())
                finally:
                    db.commit()
            self.assertEqual(future.result()[0], 200)
        self.assertEqual(self.money(), (900777, 100000))
        self.assertEqual(sum(self.money()), 1000777)

    @unittest.skipUnless(Path(CHROME).exists(), 'Chrome required')
    def test_browser_transfer_format_double_click_and_lost_response_reload(self):
        b = Browser(CHROME, self.work / ('transfer-browser-' + self.username))
        self.addCleanup(b.close)
        b.call('Network.enable', page=True)
        b.call('Network.setCookie', dict(name='LOTTO_AUTH', value=self.cookie.split(';')[0].split('=', 1)[1], url=self.url), page=True)
        b.call('Emulation.setDeviceMetricsOverride', dict(width=1360, height=950, deviceScaleFactor=1, mobile=False), page=True)
        def wait(expression):
            for _ in range(200):
                if b.value(expression): return
                time.sleep(.05)
            self.fail(expression)
        def open_card():
            b.call('Page.navigate', {'url': self.url + '/'}, page=True)
            wait(f"document.readyState==='complete' && typeof currentUser!=='undefined' && currentUser==={json.dumps(self.username)} && document.getElementById('authOverlay').style.display==='none'")
            b.value("document.getElementById('walletHistoryOpen').click();document.getElementById('walletCardTab').click()")
            wait("!document.getElementById('accountCardTopup').disabled")
        def amount(text):
            b.value("document.getElementById('cardTransferAmount').focus();document.getElementById('cardTransferAmount').select()")
            b.call('Input.insertText', {'text': text}, page=True)
        open_card()
        before = self.snapshot()
        b.value("document.getElementById('accountCardWithdraw').click()")
        amount('999999999999999999999')
        self.assertEqual(b.value("document.getElementById('cardTransferAmount').value"), '0')
        b.value("document.getElementById('accountCardTopup').click()")
        amount('100')
        self.assertEqual(b.value("document.getElementById('cardTransferAmount').value"), '100')
        amount('1000')
        self.assertEqual(b.value("document.getElementById('cardTransferAmount').value"), '1.000')
        b.call('Input.insertText', {'text': '0'}, page=True)
        self.assertEqual(b.value("document.getElementById('cardTransferAmount').value"), '10.000')
        for raw in ['999999999999999999999', '11.110000000000000000000']:
            amount(raw)
            self.assertEqual(b.value("document.getElementById('cardTransferAmount').value"), '1.000.000')
            b.call('Input.insertText', {'text': '9'}, page=True)
            self.assertEqual(b.value("document.getElementById('cardTransferAmount').value"), '1.000.000')
        self.assertEqual(self.snapshot(), before)
        amount('125000')
        self.assertEqual(b.value("document.getElementById('cardTransferAmount').value"), '125.000')
        b.value("document.getElementById('cardTransferSubmit').click();document.getElementById('cardTransferSubmit').click()")
        wait("document.getElementById('accountCardBalance').textContent==='125.000' && !document.getElementById('accountCardWithdraw').disabled")
        self.assertEqual(self.money(), (875000, 125000))
        self.assertEqual(len(self.snapshot()['transactions']), 1)
        b.value("document.getElementById('accountCardWithdraw').click()")
        amount('999999999999999999999')
        self.assertEqual(b.value("document.getElementById('cardTransferAmount').value"), '125.000')
        amount('25000')
        b.value("document.getElementById('cardTransferSubmit').click()")
        wait("document.getElementById('accountCardBalance').textContent==='100.000' && store.paypalBalance===900000 && !document.getElementById('accountCardTopup').disabled")
        # Commit on the server, then discard only the response in this test tab.
        b.value("window.fixtureFetch=window.fetch;window.fetch=async(...args)=>{const r=await window.fixtureFetch(...args);if(String(args[0]).includes('/api/account/card-transfer')){await r.text();throw new TypeError('fixture lost response')}return r};document.getElementById('accountCardWithdraw').click()")
        amount('100000')
        b.value("document.getElementById('cardTransferSubmit').click()")
        wait("document.getElementById('cardTransferSubmit').textContent==='Kiểm tra giao dịch'")
        self.assertEqual(self.money(), (1000000, 0))
        open_card()
        b.value("document.getElementById('accountCardTopup').click()")
        self.assertEqual(b.value("document.getElementById('cardTransferAmount').value"), '100.000')
        self.assertTrue(b.value("document.getElementById('cardTransferAmount').readOnly"))
        b.value("document.getElementById('cardTransferSubmit').click()")
        wait("document.getElementById('cardTransferStatus').classList.contains('is-success') && !document.getElementById('accountCardTopup').disabled")
        self.assertEqual(self.money(), (1000000, 0))
        self.assertEqual(len(self.snapshot()['transactions']), 3)
        self.fund(992987351987875)
        b.value("document.getElementById('walletCardTab').click()")
        wait("!document.getElementById('accountCardTopup').disabled && store.paypalBalance===992987351987875")
        b.value("document.getElementById('accountCardTopup').click()")
        amount('999999999999999999999')
        self.assertEqual(b.value("document.getElementById('cardTransferAmount').value"), '992.987.351.987.875')
        self.assertEqual(self.money(), (992987351987875, 0))
        self.assertEqual(len(self.snapshot()['transactions']), 3)
        artifacts = ROOT / 'runtime/logs/card_transfer_input_cap_20261104'
        artifacts.mkdir(parents=True, exist_ok=True)
        for width in [1360, 390, 320]:
            b.call('Emulation.setDeviceMetricsOverride', dict(width=width, height=950 if width>600 else 844, deviceScaleFactor=1, mobile=False), page=True)
            time.sleep(.1)
            self.assertTrue(b.value("(()=>{const p=document.querySelector('.account-card-action-buttons'),r=p.getBoundingClientRect(),buttons=[...p.children].map(x=>x.getBoundingClientRect()),f=document.getElementById('accountCardTransfer');return buttons.every(x=>Math.abs(x.top-buttons[0].top)<1 && x.left>=r.left && x.right<=r.right+1) && p.scrollWidth<=p.clientWidth && f.scrollWidth<=f.clientWidth})()"))
            (artifacts / f'transfer-{width}.png').write_bytes(base64.b64decode(b.call('Page.captureScreenshot', page=True)['data']))
