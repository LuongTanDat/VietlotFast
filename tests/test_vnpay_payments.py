"""Signed VNPAY callback fixtures on a disposable Java server; no gateway calls."""
import concurrent.futures
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from tests import test_account_balances as account_fixtures
from tests.test_prize_web import JAVA


class VnpayBackendTests(unittest.TestCase):
    setUpClass = classmethod(account_fixtures.AccountBalanceTests.setUpClass.__func__)
    tearDownClass = classmethod(account_fixtures.AccountBalanceTests.tearDownClass.__func__)
    request = classmethod(account_fixtures.AccountBalanceTests.request.__func__)
    login = classmethod(account_fixtures.AccountBalanceTests.login.__func__)

    @classmethod
    def start_server(cls):
        env = {key: value for key, value in os.environ.items() if not key.startswith('LOTTO_VNPAY_')}
        cls.server = subprocess.Popen([JAVA, '-Dfile.encoding=UTF-8', f'-Dlotto.port={cls.port}', '-Dlotto.effectivenessWorker=false', '-cp', 'build'+os.pathsep+'sqlite-jdbc.jar', 'LottoWebServer'], cwd=cls.work, env=env, stdout=cls.log, stderr=subprocess.STDOUT, creationflags=0x08000000 if os.name == 'nt' else 0)
        for _ in range(100):
            if cls.server.poll() is not None:
                raise AssertionError((cls.work/'server.log').read_text(encoding='utf-8', errors='replace'))
            try:
                urllib.request.urlopen(cls.url+'/api/time', timeout=1).close()
                return
            except OSError:
                time.sleep(.05)
        raise AssertionError('Fixture server did not start')

    def setUp(self):
        self.configure(enabled=False)
        with self.db() as db:
            db.execute('DELETE FROM payment_orders')
            db.execute("DELETE FROM account_audit WHERE action LIKE 'vnpay_%'")
            db.execute("UPDATE stores SET store_json='{}'")

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.work/'runtime/lotto_web.db', timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def configure(self, mode='production', enabled=True):
        (self.work/'runtime/vnpay.properties').write_text(f'enabled={str(enabled).lower()}\nenvironment={mode}\ntmnCode=TEST0001\nhashSecret=fixture_only_secret_not_a_merchant_key\npublicBaseUrl=https://merchant.example.test\nmaxAmount=10000000\n', encoding='utf-8')

    def order(self, amount=50000, cookie=None, request_id=None):
        code, payload, _ = self.request('/api/payments/vnpay/orders', dict(amount=amount, requestId=request_id or uuid.uuid4().hex, credit=999999999, bonusCredit=999999999), cookie or self.admin)
        self.assertEqual(code, 200, payload)
        return payload

    def signed(self, order, **overrides):
        p = dict(vnp_TmnCode='TEST0001', vnp_Amount=str(order['amount']*100), vnp_TxnRef=order['id'], vnp_OrderInfo='Nap PayPal '+order['id'], vnp_ResponseCode='00', vnp_TransactionStatus='00', vnp_TransactionNo=str(uuid.uuid4().int % 10**15 + 1), vnp_PayDate='20261017120000', vnp_BankCode='NCB', vnp_CurrCode='VND')
        p.update(overrides)
        data = urllib.parse.urlencode(sorted((k, str(v)) for k, v in p.items() if v != ''))
        signature = hmac.new(b'fixture_only_secret_not_a_merchant_key', data.encode(), hashlib.sha512).hexdigest()
        return data+'&vnp_SecureHash='+signature

    def ipn(self, query):
        return self.request('/api/payments/vnpay/ipn?'+query)[1]['RspCode']

    def balance(self, cookie=None):
        return self.request('/api/store', cookie=cookie or self.admin)[1]['store'].get('paypalBalance', 0)

    def test_01_configuration_server_amount_and_idempotency(self):
        self.assertEqual(self.request('/api/payments/vnpay/config')[0], 401)
        self.assertFalse(self.request('/api/payments/vnpay/config', cookie=self.admin)[1]['configured'])
        self.assertEqual(self.request('/api/payments/vnpay/orders', dict(amount=50000, requestId=uuid.uuid4().hex), self.admin)[0], 503)
        self.configure()
        metadata = self.request('/api/payments/vnpay/config', cookie=self.admin)[1]
        self.assertTrue(metadata['configured'])
        self.assertNotIn('fixture_only_secret', json.dumps(metadata))
        for amount in ('-1', '9999', '10001', '10000001', '50.000', '1e5'):
            self.assertEqual(self.request('/api/payments/vnpay/orders', dict(amount=amount, requestId=uuid.uuid4().hex), self.admin)[0], 400)
        request_id = uuid.uuid4().hex
        first = self.order(request_id=request_id)
        self.assertEqual(self.order(request_id=request_id)['order']['id'], first['order']['id'])
        self.assertEqual(first['order']['credit'], 63125)
        self.assertEqual(first['order']['bonusCredit'], 625)
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(first['paymentUrl']).query))
        signature = query.pop('vnp_SecureHash')
        expected = hmac.new(b'fixture_only_secret_not_a_merchant_key', urllib.parse.urlencode(sorted(query.items())).encode(), hashlib.sha512).hexdigest()
        self.assertEqual(signature, expected)
        self.assertEqual(query['vnp_Amount'], '5000000')
        self.assertEqual(query['vnp_BankCode'], 'VNPAYQR')
        self.assertEqual(query['vnp_ReturnUrl'], 'https://merchant.example.test/api/payments/vnpay/return')
        self.assertEqual(self.balance(), 0)
        self.assertEqual(self.request('/api/payments/vnpay/orders', cookie=self.member)[1]['orders'], [])
        self.assertEqual(self.request('/api/payments/vnpay/orders', dict(amount=20000, requestId=request_id), self.admin)[0], 400)

    def test_02_signature_return_exactly_once_and_duplicate_transactions(self):
        self.configure()
        order = self.order()['order']
        signed = self.signed(order)
        self.assertEqual(self.ipn(signed[:-1]+('a' if signed[-1]!='a' else 'b')), '97')
        self.assertEqual(self.ipn(signed+'&vnp_Amount=1'), '97')
        self.assertEqual(self.ipn(self.signed(order, vnp_Amount='1')), '04')
        self.assertEqual(self.ipn(self.signed(order, vnp_TmnCode='OTHER001')), '97')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args):
                return None
        with self.assertRaises(urllib.error.HTTPError) as redirect:
            urllib.request.build_opener(NoRedirect).open(self.url+'/api/payments/vnpay/return?'+signed)
        self.assertEqual(redirect.exception.code, 303)
        self.assertEqual(self.balance(), 0)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            codes = list(pool.map(lambda _: self.ipn(signed), range(16)))
        self.assertEqual(codes.count('00'), 1)
        self.assertEqual(codes.count('02'), 15)
        self.assertEqual(self.balance(), 63125)
        second = self.order(cookie=self.member)['order']
        transaction = dict(urllib.parse.parse_qsl(signed))['vnp_TransactionNo']
        self.assertEqual(self.ipn(self.signed(second, vnp_TransactionNo=transaction)), '99')
        self.assertEqual(self.balance(self.member), 0)
        self.assertEqual(self.ipn(self.signed(second)), '00')
        self.assertEqual(self.balance(self.member), 63125)
        with self.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM account_audit WHERE action='vnpay_credit'").fetchone()[0], 2)
        forged = {'paypalBalance': 9999999999, 'paymentOrders': [{'status': 'PAID'}]}
        self.request('/api/store', {'store': json.dumps(forged)}, self.admin)
        self.assertEqual(self.balance(), 63125)

    def test_03_sandbox_failure_overflow_and_late_notification(self):
        self.configure('sandbox')
        sandbox = self.order()['order']
        self.assertEqual(self.ipn(self.signed(sandbox)), '00')
        self.assertEqual(self.balance(), 0)
        self.assertEqual(self.request('/api/payments/vnpay/orders', cookie=self.admin)[1]['orders'][0]['status'], 'TEST_PAID')
        self.configure()
        failed = self.order()['order']
        self.assertEqual(self.ipn(self.signed(failed, vnp_ResponseCode='24', vnp_TransactionStatus='02')), '00')
        self.assertEqual(self.balance(), 0)
        order = self.order()['order']
        with self.db() as db:
            db.execute('UPDATE payment_orders SET expires_at=? WHERE id=?', ('2020-01-01T00:00:00Z', order['id']))
            db.execute("UPDATE stores SET store_json=? WHERE username='owner_fixture'", (json.dumps({'paypalBalance': 9007199254740991}),))
        signed = self.signed(order)
        self.assertEqual(self.ipn(signed), '99')
        with self.db() as db:
            self.assertEqual(db.execute('SELECT status FROM payment_orders WHERE id=?', (order['id'],)).fetchone()[0], 'PENDING')
            db.execute("UPDATE stores SET store_json='{}' WHERE username='owner_fixture'")
        self.assertEqual(self.ipn(signed), '00')
        self.assertEqual(self.balance(), 63125)

    def test_04_rename_delete_and_restart_durability(self):
        self.configure()
        order = self.order(cookie=self.member)['order']
        self.assertEqual(self.request('/api/admin/rename-user', dict(username='member_fixture', newUsername='renamed_fixture'), self.admin)[0], 200)
        self.assertEqual(self.ipn(self.signed(order)), '00')
        with self.db() as db:
            wallet = json.loads(db.execute("SELECT store_json FROM stores WHERE username='renamed_fixture'").fetchone()[0])
            self.assertEqual(wallet['paypalBalance'], 63125)
        _, _, headers = self.request('/api/login', dict(username='renamed_fixture', password='fixture_password'))
        pending = self.order(cookie=headers['Set-Cookie'])['order']
        self.assertEqual(self.request('/api/admin/delete-user', dict(username='renamed_fixture'), self.admin)[0], 200)
        self.assertEqual(self.ipn(self.signed(pending)), '02')
        self.request('/api/register', dict(username='renamed_fixture', password='fixture_password'))
        with self.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM payment_orders WHERE username='renamed_fixture'").fetchone()[0], 0)
        paid = self.order()['order']; signed = self.signed(paid)
        self.assertEqual(self.ipn(signed), '00')
        self.server.terminate(); self.server.wait(timeout=10)
        self.start_server(); self.login()
        self.assertEqual(self.ipn(signed), '02')
        self.assertEqual(self.balance(), 63125)
        proof = {'ok': True, 'realGatewayCalled': False, 'liveDatabaseUsed': False, 'signedAmounts': True, 'ipnOnlyCredit': True, 'concurrentExactlyOnce': True, 'sandboxWalletIsolation': True, 'atomicRollback': True, 'renameAndDeleteSafe': True, 'restartDurability': True}
        from tests.test_prize_web import ROOT
        (ROOT/'Bin/session_1_latest/vnpay_backend_verification.json').write_text(json.dumps(proof, indent=2)+'\n', encoding='utf-8')
