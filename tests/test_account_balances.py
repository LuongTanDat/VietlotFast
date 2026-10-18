"""Large wallet balances and rejected edits against a disposable Java server/DB."""
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from pathlib import Path

from tests.browser_cdp import Browser
from tests.test_prize_web import ROOT, JAVA, JAVAC, CHROME


@unittest.skipUnless(Path(JAVAC).exists(), 'JDK required')
class AccountBalanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='account-wallet-', dir=ROOT/'runtime')
        cls.work = Path(cls.temp.name)
        (cls.work/'runtime').mkdir()
        shutil.copytree(ROOT/'frontend', cls.work/'frontend')
        shutil.copy2(ROOT/'backend/lib/sqlite-jdbc-3.51.2.0.jar', cls.work/'sqlite-jdbc.jar')
        (cls.work/'build').mkdir()
        compile_result = subprocess.run(
            [JAVAC, '-encoding', 'UTF-8', '-d', str((cls.work/'build').relative_to(ROOT)),
             'backend/LottoWebServer.java'], cwd=ROOT, capture_output=True)
        if compile_result.returncode:
            cls.temp.cleanup()
            raise AssertionError(compile_result.stderr.decode(errors='replace'))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            cls.port = sock.getsockname()[1]
        cls.url = f'http://127.0.0.1:{cls.port}'
        cls.log = (cls.work/'server.log').open('wb')
        cls.start_server()
        for user in ('owner_fixture', 'member_fixture'):
            code, _, _ = cls.request('/api/register', dict(username=user, password='fixture_password'))
            assert code == 200, code
        cls.login()
        _, _, headers = cls.request('/api/login', dict(username='member_fixture', password='fixture_password'))
        cls.member = headers['Set-Cookie']

    @classmethod
    def start_server(cls):
        cls.server = subprocess.Popen(
            [JAVA, '-Dfile.encoding=UTF-8', f'-Dlotto.port={cls.port}',
             '-Dlotto.effectivenessWorker=false', '-cp', 'build'+os.pathsep+'sqlite-jdbc.jar',
             'LottoWebServer'], cwd=cls.work, stdout=cls.log, stderr=subprocess.STDOUT,
            creationflags=0x08000000 if os.name == 'nt' else 0)
        for _ in range(100):
            if cls.server.poll() is not None:
                raise AssertionError((cls.work/'server.log').read_text(encoding='utf-8', errors='replace'))
            try:
                urllib.request.urlopen(cls.url+'/api/time', timeout=1).close()
                return
            except OSError:
                time.sleep(.05)
        raise AssertionError('Disposable server did not start')

    @classmethod
    def login(cls):
        code, _, headers = cls.request('/api/login', dict(username='owner_fixture', password='fixture_password'))
        assert code == 200
        cls.admin = headers['Set-Cookie']

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.log.close()
        cls.temp.cleanup()

    @classmethod
    def request(cls, path, form=None, cookie=None):
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        if cookie:
            headers['Cookie'] = cookie
        request = urllib.request.Request(cls.url+path, data=data, headers=headers)
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read()), response.headers

    @classmethod
    def set_balance(cls, paypal, diamond=9195, cookie=None):
        return cls.request('/api/admin/update-assets',
                           dict(username='owner_fixture', diamond=diamond, paypal=paypal),
                           cookie or cls.admin)

    @classmethod
    def snapshot(cls):
        with closing(sqlite3.connect(cls.work/'runtime/lotto_web.db')) as db:
            wallet = db.execute("SELECT store_json FROM stores WHERE username='owner_fixture'").fetchone()[0]
            audits = db.execute('SELECT COUNT(*) FROM account_audit').fetchone()[0]
        return wallet, audits

    def test_large_balances_survive_users_store_and_server_restart(self):
        for value in (350000, 2147483647, 2147483648, 9999999999, 1000000000000, 9007199254740991):
            with self.subTest(value=value):
                self.assertEqual(self.set_balance(value, value)[0], 200)
                code, data, _ = self.request('/api/admin/users', cookie=self.admin)
                owner = next(u for u in data['users'] if u['username']=='owner_fixture')
                self.assertEqual(code, 200)
                self.assertEqual(owner['paypalBalance'], value)
                self.assertEqual(owner['diamondBalance'], value)
                self.assertEqual(self.request('/api/store', cookie=self.admin)[1]['store']['paypalBalance'], value)
        self.set_balance(9999999999)
        self.server.terminate()
        self.server.wait(timeout=10)
        self.start_server()
        self.login()
        self.assertEqual(self.request('/api/store', cookie=self.admin)[1]['store']['paypalBalance'], 9999999999)
        owner = next(u for u in self.request('/api/admin/users', cookie=self.admin)[1]['users']
                     if u['username']=='owner_fixture')
        self.assertEqual(owner['paypalBalance'], 9999999999)

    def test_invalid_asset_fields_reject_entire_update_and_leave_audit_unchanged(self):
        self.set_balance(350000)
        before = self.snapshot()
        invalid = ('', '-1', 'NaN', 'Infinity', '1e10', '1000000000.25',
                   '999.999.9999', '9007199254740992', '999999999999999999999')
        for value in invalid:
            for field in ('paypal', 'diamond'):
                with self.subTest(value=value, field=field):
                    form = dict(username='owner_fixture', paypal=9999999999, diamond=1000000)
                    form[field] = value
                    code, payload, _ = self.request('/api/admin/update-assets', form, self.admin)
                    self.assertEqual(code, 400)
                    self.assertFalse(payload['ok'])
                    self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.set_balance(1000000000, cookie=self.member)[0], 403)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.set_balance(0, 0)[0], 200)
        self.assertEqual(json.loads(self.snapshot()[0])['paypalBalance'], 0)

    @unittest.skipUnless(Path(CHROME).exists(), 'Chrome required')
    def test_real_account_editor_paste_validation_and_large_save(self):
        self.set_balance(350000)
        browser = Browser(CHROME, self.work/f'chrome-profile-{time.time_ns()}')
        def wait(expression):
            for _ in range(200):
                if browser.value(expression):
                    return
                time.sleep(.05)
            raise AssertionError('Timeout: '+expression)
        def run_async(expression):
            result = browser.call('Runtime.evaluate',
                                  dict(expression=expression, awaitPromise=True, returnByValue=True), page=True)
            self.assertNotIn('exceptionDetails', result, result)
        def edit(field, value):
            browser.value(f"document.querySelector('#accountRows tr[data-user=owner_fixture] .acc-{field}').focus();"
                          f"document.querySelector('#accountRows tr[data-user=owner_fixture] .acc-{field}').select()")
            browser.call('Input.insertText', dict(text=value), page=True)
        try:
            browser.call('Page.enable', page=True)
            browser.call('Network.enable', page=True)
            browser.call('Network.setCookie', dict(name='LOTTO_AUTH', value=self.admin.split(';')[0].split('=',1)[1],
                                                  url=self.url), page=True)
            browser.call('Page.navigate', dict(url=self.url+'/'), page=True)
            wait("typeof openAccountManager==='function' && document.getElementById('openAccountBtn').style.display==='flex'")
            run_async('openAccountManager()')
            run_async("document.getElementById('toggleAccountEditBtn').onclick()")
            paypal = "document.querySelector('#accountRows tr[data-user=owner_fixture] .acc-paypal')"
            self.assertEqual(browser.value(paypal+'.type'), 'text')
            self.assertEqual(browser.value(paypal+'.value'), '350.000')
            before = self.snapshot()
            run_async("document.getElementById('saveAccountEditBtn').onclick()")
            self.assertEqual(self.snapshot(), before)
            for invalid in ('999.999.9999', '', '-1', '1.5', 'NaN', '9007199254740992'):
                edit('paypal', invalid)
                display = f'{int(invalid):,}'.replace(',','.') if invalid.isdigit() else invalid
                self.assertEqual(browser.value(paypal+'.value'), display)
                run_async("document.getElementById('saveAccountEditBtn').onclick()")
                self.assertIn('lỗi 1 dòng', browser.value("document.getElementById('accountMsg').textContent"))
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(browser.value(paypal+'.value'), '350.000')
            for value, expected in (('9.999.999.999',9999999999), ('350.000',350000),
                                    ('1000000000000',1000000000000), ('0',0)):
                edit('paypal', value)
                run_async("document.getElementById('saveAccountEditBtn').onclick()")
                self.assertIn('1 dòng thay đổi', browser.value("document.getElementById('accountMsg').textContent"))
                self.assertEqual(json.loads(self.snapshot()[0])['paypalBalance'], expected)
                self.assertEqual(browser.value(paypal+'.value'), f'{expected:,}'.replace(',','.'))
                self.assertEqual(browser.value("Number(document.querySelector('#accountRows tr[data-user=owner_fixture]').dataset.paypal)"), expected)
            edit('diamond','2.500.000')
            run_async("document.getElementById('saveAccountEditBtn').onclick()")
            self.assertEqual(json.loads(self.snapshot()[0])['diamondBalance'], 2500000)
            # Focusing a zero balance and typing replaces the default, without selecting manually.
            browser.value(paypal+'.focus()')
            self.assertEqual(browser.value(paypal+'.selectionStart'), 0)
            self.assertEqual(browser.value(paypal+'.selectionEnd'), 1)
            browser.call('Input.insertText', dict(text='999'), page=True)
            self.assertEqual(browser.value(paypal+'.value'), '999')
            for value, expected in (('0999','999'),('000350000','350.000'),('000','0')):
                edit('paypal',value)
                self.assertEqual(browser.value(paypal+'.value'),expected)
                self.assertEqual(browser.value(paypal+'.selectionStart'),len(expected))
            edit('paypal','0999')
            run_async("document.getElementById('saveAccountEditBtn').onclick()")
            self.assertEqual(json.loads(self.snapshot()[0])['paypalBalance'],999)
            edit('diamond','00050')
            self.assertEqual(browser.value("document.querySelector('#accountRows tr[data-user=owner_fixture] .acc-diamond').value"),'50')
            run_async("document.getElementById('saveAccountEditBtn').onclick()")
            self.assertEqual(json.loads(self.snapshot()[0])['diamondBalance'],50)
            edit('paypal','0')
            browser.value(paypal+'.select()')
            for length in range(1,11):
                browser.call('Input.insertText',dict(text='9'),page=True)
                expected = f'{int("9"*length):,}'.replace(',','.')
                self.assertEqual(browser.value(paypal+'.value'),expected)
                self.assertEqual(browser.value(paypal+'.selectionStart'),len(expected))
            run_async("document.getElementById('saveAccountEditBtn').onclick()")
            self.assertEqual(json.loads(self.snapshot()[0])['paypalBalance'],9999999999)
            # Inserting in the middle keeps the caret adjacent to the inserted digit.
            edit('paypal','12345')
            self.assertEqual(browser.value(paypal+'.value'),'12.345')
            browser.value(paypal+'.setSelectionRange(2,2)')
            browser.call('Input.insertText',dict(text='9'),page=True)
            self.assertEqual(browser.value(paypal+'.value'),'129.345')
            self.assertEqual(browser.value(paypal+'.selectionStart'),3)
            # Backspace across a group boundary must not move the caret to the end.
            edit('paypal','1234')
            browser.value(paypal+'.setSelectionRange(2,2)')
            for key in ('keyDown','keyUp'):
                browser.call('Input.dispatchKeyEvent',dict(type=key,key='Backspace',code='Backspace',windowsVirtualKeyCode=8),page=True)
            self.assertEqual(browser.value(paypal+'.value'),'1.234')
            self.assertEqual(browser.value(paypal+'.selectionStart'),1)
            for key in ('keyDown','keyUp'):
                browser.call('Input.dispatchKeyEvent',dict(type=key,key='Backspace',code='Backspace',windowsVirtualKeyCode=8),page=True)
            self.assertEqual(browser.value(paypal+'.value'),'234')
            self.assertEqual(browser.value(paypal+'.selectionStart'),0)
            # Deleting the first digit also removes an orphaned separator.
            edit('paypal','1234')
            browser.value(paypal+'.setSelectionRange(0,1)')
            for key in ('keyDown','keyUp'):
                browser.call('Input.dispatchKeyEvent',dict(type=key,key='Backspace',code='Backspace',windowsVirtualKeyCode=8),page=True)
            self.assertEqual(browser.value(paypal+'.value'),'234')
        finally:
            browser.close()


if __name__ == '__main__':
    unittest.main()
