"""Scored receipt -> Python payout -> Java API -> visible account wallet."""
import base64
import json
import shutil
import sqlite3
import time
import unittest
from contextlib import closing
from pathlib import Path

from ai import personal_tracking as billing, prediction_rewards as rewards
from tests import test_account_balances as fixtures
from tests.test_prediction_rewards import PredictionRewardTests
from tests.test_prize_web import CHROME,ROOT
from tests.browser_cdp import Browser


class PredictionRewardWebTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.AccountBalanceTests.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.AccountBalanceTests.tearDownClass.__func__)
    start_server=classmethod(fixtures.AccountBalanceTests.start_server.__func__)
    request=classmethod(fixtures.AccountBalanceTests.request.__func__)
    login=classmethod(fixtures.AccountBalanceTests.login.__func__)

    @unittest.skipUnless(Path(CHROME).exists(),'Chrome required')
    def test_scored_history_credit_api_and_browser_wallet_refresh(self):
        fixture=PredictionRewardTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.cycle()
        with closing(sqlite3.connect(fixture.account)) as db:
            charge=db.execute('SELECT * FROM prediction_charges').fetchone()
        accounts=self.work/'runtime/lotto_web.db'
        with closing(sqlite3.connect(accounts)) as db,db:
            db.execute('INSERT INTO personal_tracking_accounts VALUES(?,?)',(fixture.aid,'member_fixture'))
            db.execute('INSERT INTO prediction_charges VALUES(?,?,?,?,?,?,?,?,?)',charge)
        scope=billing.Scope(fixture.aid,'member_fixture',accounts,self.work/'runtime')
        scope.database.parent.mkdir(parents=True)
        shutil.copy2(fixture.scope.database,scope.database)
        self.assertEqual(self.request('/api/admin/update-assets',dict(username='member_fixture',paypal=500000,diamond=1),self.admin)[0],200)
        browser=Browser(CHROME,self.work/'reward-flow-browser');self.addCleanup(browser.close)
        browser.call('Network.enable',page=True)
        browser.call('Network.setCookie',dict(name='LOTTO_AUTH',value=self.member.split(';')[0].split('=',1)[1],url=self.url),page=True)
        browser.call('Emulation.setDeviceMetricsOverride',dict(width=1360,height=950,deviceScaleFactor=1,mobile=False),page=True)
        browser.call('Page.navigate',{'url':self.url+'/'},page=True)
        def wait(expression):
            for _ in range(160):
                if browser.value(expression):return
                time.sleep(.05)
            self.fail(expression)
        wait("typeof currentUser!=='undefined' && currentUser==='member_fixture' && typeof store!=='undefined' && store.paypalBalance===500000")
        paid=rewards.settle(scope,apply=True,prizes={})
        self.assertEqual((paid['credited'],paid['creditedPayPal']),(1,50000000))
        code,report,_=self.request('/api/account/wallet-history?kind=reward',cookie=self.member)
        self.assertEqual(code,200,report)
        self.assertEqual((report['total'],report['balance'],report['events'][0]['delta']),(1,50500000,'50000000'))
        self.assertEqual(self.request('/api/account/wallet-history?kind=reward',cookie=self.admin)[1]['total'],0)
        browser.value("document.getElementById('walletHistoryOpen').click();document.querySelector('[data-wallet-kind=reward]').click()")
        wait("document.querySelectorAll('#walletHistoryRows tr').length===1 && store.paypalBalance===50500000")
        self.assertIn('+50.000.000',browser.value("document.getElementById('walletHistoryRows').textContent"))
        self.assertIn('Trúng thưởng',browser.value("document.getElementById('walletHistoryRows').textContent"))
        self.assertEqual(browser.value("document.getElementById('walletHistoryBalance').textContent"),'50.500.000')
        artifacts=ROOT/'runtime/logs/prediction_rewards_20261103'
        (artifacts/'reward-dialog.png').write_bytes(base64.b64decode(browser.call('Page.captureScreenshot',page=True)['data']))
        before=self.request('/api/store',cookie=self.member)[1]['store']
        self.assertEqual(rewards.settle(scope,apply=True,prizes={})['creditedPayPal'],0)
        browser.value("document.getElementById('walletHistoryRefresh').click()")
        wait("document.getElementById('walletHistoryTable').getAttribute('aria-busy')==='false'")
        self.assertEqual(self.request('/api/store',cookie=self.member)[1]['store']['paypalBalance'],before['paypalBalance'])
