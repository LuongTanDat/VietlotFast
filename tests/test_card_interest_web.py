"""Java/Python/SQLite/Chrome integration with disposable money and users."""
import base64
import json
import shutil
import sqlite3
import time
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from ai import account_card as cards, card_interest as interest
from tests import test_account_balances as fixtures
from tests.browser_cdp import Browser
from tests.test_card_interest import SETTINGS, START, midnight
from tests.test_prize_web import ROOT, CHROME


class CardInterestWebTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.AccountBalanceTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.AccountBalanceTests.tearDownClass.__func__)
    start_server = classmethod(fixtures.AccountBalanceTests.start_server.__func__)
    request = classmethod(fixtures.AccountBalanceTests.request.__func__)
    login = classmethod(fixtures.AccountBalanceTests.login.__func__)

    @unittest.skipUnless(Path(CHROME).exists(), 'Chrome required')
    def test_interest_only_on_card_readonly_filter_browser_and_withdrawal(self):
        username = 'interest_' + uuid.uuid4().hex[:10]
        self.assertEqual(self.request('/api/register', dict(username=username, password='fixture_password'))[0], 200)
        cookie = self.request('/api/login', dict(username=username, password='fixture_password'))[2]['Set-Cookie']
        identity = self.request('/api/store', cookie=cookie)[1]['store']['accountId']
        self.assertEqual(self.request('/api/admin/update-assets', dict(username=username, diamond=500, paypal=500000), self.admin)[0], 200)
        dbfile = self.work/'runtime/lotto_web.db'
        wallet_before = self.request('/api/store', cookie=cookie)[1]['store']
        with closing(sqlite3.connect(dbfile)) as db:
            db.execute('BEGIN IMMEDIATE')
            with patch('ai.account_card.ledger.now_iso', return_value='2026-11-01T10:00:00Z'):
                cards.credit(db, identity, 'PayPal', 1000000, 'fixture:'+identity, 'topup', 'fixture', {})
            db.commit()
        interest.settle(dbfile, apply=True, now_ns=interest.timestamp_ns(START), settings=SETTINGS)
        result = interest.settle(dbfile, apply=True, now_ns=interest.timestamp_ns(midnight('2026-11-05')), settings=SETTINGS)
        self.assertEqual((result['errors'], result['creditedPayPal']), ([], 250))
        with closing(sqlite3.connect(dbfile)) as db:
            snapshot = {name: db.execute('SELECT * FROM '+name+' ORDER BY 1').fetchall() for name in ['account_cards','card_transactions','card_interest_days','card_interest_state','stores','account_audit']}
        report = self.request('/api/account/card?history=1&kind=interest', cookie=cookie)[1]
        self.assertEqual((report['total'], report['card']['balance'], report['events'][0]['kind'], report['events'][0]['delta']), (1, '1000250', 'interest', '250'))
        self.assertEqual(self.request('/api/account/card?history=1&kind=reward', cookie=cookie)[1]['total'], 0)
        self.assertEqual(self.request('/api/account/card?history=1&kind=interest&accountId='+identity, cookie=self.member)[1]['total'], 0)
        wallet_after = self.request('/api/store', cookie=cookie)[1]['store']
        self.assertEqual((wallet_after['paypalBalance'], wallet_after['walletVersion']), (wallet_before['paypalBalance'], wallet_before['walletVersion']))
        self.assertFalse(any(event['label']=='Lãi suất thẻ' for event in self.request('/api/account/wallet-history', cookie=cookie)[1]['events']))
        with closing(sqlite3.connect(dbfile)) as db:
            self.assertEqual({name: db.execute('SELECT * FROM '+name+' ORDER BY 1').fetchall() for name in snapshot}, snapshot)
        browser = Browser(CHROME, self.work/('interest-browser-'+username)); self.addCleanup(browser.close)
        browser.call('Network.enable', page=True)
        browser.call('Network.setCookie', dict(name='LOTTO_AUTH', value=cookie.split(';')[0].split('=',1)[1], url=self.url), page=True)
        browser.call('Emulation.setDeviceMetricsOverride', dict(width=390,height=844,deviceScaleFactor=1,mobile=False), page=True)
        browser.call('Page.navigate', {'url':self.url+'/'}, page=True)
        def wait(expression):
            for _ in range(200):
                if browser.value(expression): return
                time.sleep(.05)
            self.fail(expression)
        wait(f"document.readyState==='complete' && currentUser==={json.dumps(username)} && document.getElementById('authOverlay').style.display==='none'")
        browser.value("document.getElementById('walletHistoryOpen').click();document.getElementById('walletCardTab').click()")
        wait("!document.getElementById('accountCardTopup').disabled")
        browser.value("document.getElementById('accountCardHistoryToggle').click();document.querySelector('[data-card-kind=interest]').click()")
        wait("document.querySelectorAll('#cardHistoryRows tr').length===1")
        self.assertTrue(browser.value("document.getElementById('cardHistoryRows').textContent.includes('Lãi suất thẻ') && document.getElementById('accountCardBalance').textContent==='1.000.250' && store.paypalBalance===500000"))
        out=ROOT/'runtime/logs/card_daily_interest_20261104'
        (out/'interest-history-390.png').write_bytes(base64.b64decode(browser.call('Page.captureScreenshot',page=True)['data']))
        browser.value("document.getElementById('accountCardWithdraw').click();document.querySelector('[data-transfer-percent=\"100\"]').click()")
        self.assertEqual(browser.value("document.getElementById('cardTransferAmount').value"),'1.000.250')
        browser.value("document.getElementById('cardTransferSubmit').click()")
        wait("document.getElementById('accountCardBalance').textContent==='0' && store.paypalBalance===1500250 && !document.getElementById('accountCardTopup').disabled")
        self.assertEqual(interest.settle(dbfile,apply=True,now_ns=interest.timestamp_ns(midnight('2026-11-06')),settings=SETTINGS)['creditedPayPal'],0)
        self.assertEqual(self.request('/api/account/card?history=1&kind=interest',cookie=cookie)[1]['total'],1)


class CardInterestWorkerTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.AccountBalanceTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.AccountBalanceTests.tearDownClass.__func__)
    request = classmethod(fixtures.AccountBalanceTests.request.__func__)
    login = classmethod(fixtures.AccountBalanceTests.login.__func__)

    @classmethod
    def start_server(cls):
        for name in ['ai/__init__.py','ai/card_interest.py','ai/account_card.py','ai/prediction_ledger.py','ai/prizes.py','ai/configs/__init__.py','ai/configs/data_paths.py',
                     'ai/evaluation/__init__.py','ai/evaluation/baselines.py','ai/evaluation/metrics.py','ai/evaluation/probability.py']:
            target=cls.work/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,target)
        (cls.work/'config').mkdir(exist_ok=True)
        (cls.work/'config/card-interest.json').write_text(json.dumps(SETTINGS),encoding='utf-8')
        fixtures.AccountBalanceTests.start_server.__func__(cls)

    def test_real_java_scheduler_activates_python_policy_and_restart_preserves_anchor(self):
        dbfile=self.work/'runtime/lotto_web.db'
        def anchor():
            for _ in range(200):
                try:
                    with closing(sqlite3.connect(dbfile)) as db:
                        row=db.execute('SELECT version,activated_ns FROM card_interest_policy').fetchone()
                        if row:return row
                except sqlite3.OperationalError:pass
                time.sleep(.05)
            self.fail((self.work/'server.log').read_text(encoding='utf-8',errors='replace'))
        first=anchor();self.assertEqual(first[0],interest.VERSION)
        for _ in range(100):
            if 'Card interest:' in (self.work/'server.log').read_text(encoding='utf-8',errors='replace'):break
            time.sleep(.05)
        else:self.fail('Java did not collect a successful Python worker result')
        self.server.terminate();self.server.wait(timeout=10);self.start_server()
        self.assertEqual(anchor(),first)
        with closing(sqlite3.connect(dbfile)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM card_interest_days').fetchone()[0],0)
