"""Authenticated Java/Python bridge and full UI, using a disposable project/DB."""
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

from tests.test_prize_web import ROOT, JAVA, JAVAC, CHROME


@unittest.skipUnless(Path(JAVAC).exists() and Path(JAVA).exists(), 'JDK required')
class EffectivenessWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='effectiveness-http-', dir=ROOT / 'runtime')
        cls.work = Path(cls.temp.name)
        (cls.work / 'runtime').mkdir()
        shutil.copytree(ROOT / 'frontend', cls.work / 'frontend')
        shutil.copytree(ROOT / 'ai', cls.work / 'ai',
                        ignore=shutil.ignore_patterns('__pycache__', 'models', 'standalone_predictors', 'predictors'))
        shutil.copytree(ROOT / 'backend', cls.work / 'backend',
                        ignore=shutil.ignore_patterns('__pycache__', 'bin', 'lib', '*.java', 'live_results.py'))
        shutil.copy2(ROOT / 'backend/lib/sqlite-jdbc-3.51.2.0.jar', cls.work / 'sqlite-jdbc.jar')
        (cls.work / 'build').mkdir()
        compilation = subprocess.run([JAVAC, '-encoding', 'UTF-8', '-d',
                                      str((cls.work / 'build').relative_to(ROOT)),
                                      'backend/LottoWebServer.java'], cwd=ROOT, capture_output=True)
        if compilation.returncode:
            cls.temp.cleanup()
            raise AssertionError(compilation.stderr.decode(errors='replace'))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        cls.url = f'http://127.0.0.1:{port}'
        cls.log = (cls.work / 'server.log').open('wb')
        cls.server = subprocess.Popen([JAVA, '-Dfile.encoding=UTF-8', f'-Dlotto.port={port}',
                                      '-Dlotto.effectivenessWorker=false', '-cp',
                                      'build' + os.pathsep + 'sqlite-jdbc.jar', 'LottoWebServer'],
                                     cwd=cls.work, stdout=cls.log, stderr=subprocess.STDOUT,
                                     creationflags=0x08000000 if os.name == 'nt' else 0)
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.url + '/api/time', timeout=1).close()
                break
            except (OSError, urllib.error.URLError):
                time.sleep(.05)
        else:
            cls.tearDownClass()
            raise AssertionError('Disposable server failed to start')
        for user in ('owner_fixture', 'member_fixture'):
            code, _, _ = cls.request('/api/register', {'username': user, 'password': 'fixture_password'})
            if code != 200:
                cls.tearDownClass()
                raise AssertionError('Fixture registration failed')
        _, _, headers = cls.request('/api/login', {'username': 'owner_fixture', 'password': 'fixture_password'})
        cls.admin = headers['Set-Cookie']
        _, _, headers = cls.request('/api/login', {'username': 'member_fixture', 'password': 'fixture_password'})
        cls.member = headers['Set-Cookie']

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.log.close()
        cls.temp.cleanup()

    @classmethod
    def request(cls, path, form=None, cookie=None, method=None, origin=None):
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        if cookie:
            headers['Cookie'] = cookie
        if origin:
            headers['Origin'] = origin
        request = urllib.request.Request(cls.url + path, data=data, headers=headers, method=method)
        try:
            response = urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read()
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = raw.decode('utf-8')
            return response.status, payload, response.headers

    def test_routes_require_login_and_admin_for_mutations(self):
        self.assertEqual(401, self.request('/api/ml/effectiveness?type=LOTO_6_45')[0])
        for route in ('effectiveness-settings', 'effectiveness-cycle'):
            form = {'type': 'LOTO_6_45', 'enabled': 'true', 'ticketCount': 3}
            self.assertEqual(401, self.request('/api/ml/' + route, form)[0])
            self.assertEqual(403, self.request('/api/ml/' + route, form, self.member)[0])
        self.assertEqual(403, self.request('/api/ml/effectiveness?type=LOTO_6_45', cookie=self.member,
                                         origin='https://untrusted.example')[0])

    def test_system_actor_cannot_be_registered_renamed_or_logged_in(self):
        form = {'username': '__effectiveness_system__', 'password': 'fixture_password'}
        self.assertEqual(400, self.request('/api/register', form)[0])
        self.assertEqual(403, self.request('/api/login', form)[0])
        rename = {'username': 'member_fixture', 'newUsername': '__effectiveness_system__'}
        self.assertEqual(400, self.request('/api/admin/rename-user', rename, self.admin)[0])

    def test_real_report_is_empty_read_only_and_settings_persist(self):
        code, report, _ = self.request('/api/ml/effectiveness?type=LOTO_6_45', cookie=self.member)
        self.assertEqual(200, code, report)
        self.assertFalse(report['canManage'])
        self.assertEqual(0, report['counts']['total'])
        self.assertEqual([], report['cycles'])
        self.assertEqual({'web', 'random', 'bayesian', 'ewma'}, {m['key'] for m in report['methods']})
        self.assertTrue(all(m['meanHits'] is None for m in report['methods']))
        form = {'type': 'LOTO_6_45', 'enabled': 'true', 'ticketCount': 4}
        code, result, _ = self.request('/api/ml/effectiveness-settings', form, self.admin)
        self.assertEqual(200, code, result)
        self.assertTrue(result['canManage'])
        code, result, _ = self.request('/api/ml/effectiveness-settings?type=LOTO_6_45', cookie=self.member)
        self.assertEqual(200, code, result)
        self.assertTrue(result['settings']['enabled'])
        self.assertEqual(4, result['settings']['ticketCount'])
        with closing(sqlite3.connect(self.work / 'runtime/lotto_web.db')) as connection:
            self.assertEqual(0, connection.execute('SELECT COUNT(*) FROM prediction_runs').fetchone()[0])

    def test_request_validation_and_empty_source_cannot_lock(self):
        for query in ('type=KENO', 'type=LOTO_6_45&limit=301', 'type=LOTO_6_45&limit=nope'):
            self.assertEqual(400, self.request('/api/ml/effectiveness?' + query, cookie=self.admin)[0])
        for enabled, count in (('maybe', '3'), ('true', '11'), ('true', '0')):
            form = {'type': 'LOTO_6_45', 'enabled': enabled, 'ticketCount': count}
            self.assertEqual(400, self.request('/api/ml/effectiveness-settings', form, self.admin)[0])
        self.assertEqual(405, self.request('/api/ml/effectiveness?type=LOTO_6_45', {}, self.admin)[0])
        self.assertEqual(405, self.request('/api/ml/effectiveness-cycle?type=LOTO_6_45', cookie=self.admin)[0])
        code, result, _ = self.request('/api/ml/effectiveness-cycle', {'type': 'LOTO_6_45'}, self.admin)
        self.assertEqual(400, code, result)
        self.assertFalse(result['ok'])
        with closing(sqlite3.connect(self.work / 'runtime/lotto_web.db')) as connection:
            self.assertEqual(0, connection.execute('SELECT COUNT(*) FROM prediction_runs').fetchone()[0])

    @unittest.skipUnless(Path(CHROME).exists(), 'Chrome required')
    def test_full_frontend_tab_empty_state_and_admin_controls(self):
        from tests.browser_cdp import Browser
        browser = Browser(CHROME, self.work / 'chrome-profile')
        try:
            browser.call('Page.navigate', {'url': self.url + '/'}, page=True)
            for _ in range(100):
                if browser.value("typeof window.VietlottEffectiveness === 'object' && !!document.getElementById('loginBtn')"):
                    break
                time.sleep(.05)
            expression = """(async () => {
                const response=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'username=owner_fixture&password=fixture_password'});
                if(!response.ok)throw new Error('fixture login');
                document.getElementById('loginUser').value='owner_fixture';
                document.getElementById('loginPass').value='fixture_password';
                document.getElementById('loginBtn').click();
                return true;
            })()"""
            result = browser.call('Runtime.evaluate', {'expression': expression, 'awaitPromise': True,
                                                     'returnByValue': True}, page=True)
            self.assertNotIn('exceptionDetails', result)
            for _ in range(150):
                if browser.value("!!document.querySelector('[data-predict-mode-tab=effectiveness]')"):
                    browser.value("document.querySelector('[data-predict-mode-tab=effectiveness]').click()")
                    break
                time.sleep(.05)
            for _ in range(150):
                text = browser.value("document.getElementById('predictRootEffectiveness')?.innerText || ''")
                if 'Ngẫu nhiên' in text and 'Bayesian' in text and 'EWMA' in text:
                    break
                time.sleep(.05)
            self.assertIn('Ngẫu nhiên', text)
            self.assertIn('Bayesian', text)
            self.assertIn('EWMA', text)
            self.assertTrue(browser.value("!document.getElementById('predictRootEffectiveness').hidden"))
            self.assertFalse(browser.value("!!document.getElementById('bootErrorBanner')"))
            self.assertNotIn('NaN', text)
        finally:
            browser.close()
