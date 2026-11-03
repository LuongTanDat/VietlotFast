"""Card API isolation and actual tabs/card/history against disposable money."""
import base64
import json
import shutil
import sqlite3
import time
import unittest
import uuid
from contextlib import closing
from pathlib import Path

from ai import account_card as cards,personal_tracking as billing,prediction_rewards as rewards
from tests import test_account_balances as fixtures,test_prediction_rewards as reward_fixtures
from tests.browser_cdp import Browser
from tests.test_prize_web import ROOT,CHROME


class AccountCardWebTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.AccountBalanceTests.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.AccountBalanceTests.tearDownClass.__func__)
    start_server=classmethod(fixtures.AccountBalanceTests.start_server.__func__)
    request=classmethod(fixtures.AccountBalanceTests.request.__func__)
    login=classmethod(fixtures.AccountBalanceTests.login.__func__)

    def setUp(self):
        self.db=self.work/'runtime/lotto_web.db'
        with closing(sqlite3.connect(self.db)) as db,db:
            # Card transactions are intentionally immutable; tests use a new
            # account for every case instead of clearing financial history.
            self.username='card_'+uuid.uuid4().hex[:10]
        code,_,_=self.request('/api/register',dict(username=self.username,password='fixture_password'))
        self.assertEqual(code,200)
        self.cookie=self.request('/api/login',dict(username=self.username,password='fixture_password'))[2]['Set-Cookie']
        self.identity=self.request('/api/store',cookie=self.cookie)[1]['store']['accountId']

    def snapshot(self):
        with closing(sqlite3.connect(self.db)) as db:
            return {name:db.execute('SELECT * FROM '+name+' ORDER BY 1').fetchall() for name in ['stores','account_cards','card_transactions','account_audit']}

    def test_card_get_is_read_only_owner_scoped_filtered_and_paginated(self):
        self.assertEqual(self.request('/api/account/card')[0],401)
        self.assertEqual(self.request('/api/account/card',dict(history=1),self.cookie)[0],405)
        for query in ['?kind=bad','?page=0','?history=bad']:
            self.assertEqual(self.request('/api/account/card'+query,cookie=self.cookie)[0],400)
        before=self.snapshot()
        code,report,headers=self.request('/api/account/card?accountId=100000000000&username=owner_fixture',cookie=self.cookie)
        self.assertEqual(code,200,report);self.assertEqual(headers.get('Cache-Control'),'no-store')
        self.assertEqual((report['owner'],report['card']['accountId'],report['card']['balance']),(self.username,self.identity,'0'))
        self.assertEqual(self.snapshot(),before)
        with closing(billing.account_connection(self.db)) as db:
            cards.schema(db);db.execute('BEGIN IMMEDIATE')
            for index in range(24):cards.credit(db,self.identity,'PayPal',100,f'fixture:{self.identity}:{index}','topup',str(index),{'label':'Nạp thử'})
            cards.credit(db,self.identity,'PayPal',200,'transfer:'+self.identity,'transfer','t',{'label':'Chuyển thử'})
            cards.credit(db,self.identity,'PayPal',300,'reward:'+self.identity,'reward','r',{'label':'<img src=x onerror=alert(1)>'})
            db.execute('UPDATE account_cards SET balance=balance-100,version=version+1 WHERE account_id=?',(self.identity,))
            db.execute('INSERT INTO card_transactions VALUES(?,?,?,?,?,?,?,?,?,?)',('withdraw:'+self.identity,self.identity,'PayPal','withdraw',-100,2800,'w','{}','2026-11-03T03:00:00Z','withdraw:'+self.identity))
            db.commit()
        before=self.snapshot()
        first=self.request('/api/account/card?history=1',cookie=self.cookie)[1]
        second=self.request('/api/account/card?history=1&page=2',cookie=self.cookie)[1]
        self.assertEqual((first['total'],first['pages'],len(first['events'])),(27,2,20))
        self.assertEqual(len(second['events']),7)
        self.assertEqual(first['card']['balance'],'2800')
        self.assertEqual(len({r['id'] for r in first['events']+second['events']}),27)
        for kind,count in [('topup',24),('transfer',1),('withdraw',1),('reward',1)]:
            payload=self.request('/api/account/card?history=1&kind='+kind,cookie=self.cookie)[1]
            self.assertEqual(payload['total'],count)
        other=self.request('/api/account/card?history=1&accountId='+self.identity,cookie=self.admin)[1]
        self.assertEqual((other['total'],other['card']['balance']),(0,'0'))
        self.assertEqual(self.snapshot(),before)

    @unittest.skipUnless(Path(CHROME).exists(),'Chrome required')
    def test_card_rewards_old_transfer_and_browser_tabs_history_mobile(self):
        fixture=reward_fixtures.PredictionRewardTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        cycle,charge=fixture.cycle()
        with closing(sqlite3.connect(fixture.account)) as db:
            paid_charge=db.execute('SELECT * FROM prediction_charges WHERE id=?',(charge,)).fetchone()
        with closing(sqlite3.connect(self.db)) as db,db:
            db.execute('INSERT INTO personal_tracking_accounts VALUES(?,?)',(fixture.aid,self.username))
            db.execute('INSERT INTO prediction_charges VALUES(?,?,?,?,?,?,?,?,?)',paid_charge)
        scope=billing.Scope(fixture.aid,self.username,self.db,self.work/'runtime')
        scope.database.parent.mkdir(parents=True);shutil.copy2(fixture.scope.database,scope.database)
        self.assertEqual(self.request('/api/admin/update-assets',dict(username=self.username,paypal=500000,diamond=1),self.admin)[0],200)
        # Existing payout into the old wallet, then move it exactly once.
        self.assertEqual(rewards.settle(scope,apply=True,prizes={})['creditedPayPal'],50000000)
        moved=cards.move_wallet_rewards(scope,apply=True)
        self.assertEqual((moved['walletAfter'],moved['cardAfter']),(500000,50000000))
        # Add another paid cycle and route its reward directly to the card.
        _,new_charge=fixture.cycle()
        with closing(sqlite3.connect(fixture.account)) as db:
            paid_charge=db.execute('SELECT * FROM prediction_charges WHERE id=?',(new_charge,)).fetchone()
        with closing(sqlite3.connect(self.db)) as db,db:db.execute('INSERT INTO prediction_charges VALUES(?,?,?,?,?,?,?,?,?)',paid_charge)
        shutil.copy2(fixture.scope.database,scope.database)
        cards.policy.return_value={'destination':'card','currency':'PayPal'}
        self.assertEqual(rewards.settle(scope,apply=True,prizes={})['creditedPayPal'],50000000)
        card=self.request('/api/account/card?history=1&kind=reward',cookie=self.cookie)[1]
        self.assertEqual((card['total'],card['card']['balance']),(1,'100000000'))
        self.assertEqual(self.request('/api/store',cookie=self.cookie)[1]['store']['paypalBalance'],500000)
        self.assertEqual(self.request('/api/account/wallet-history?kind=reward',cookie=self.cookie)[1]['total'],1)
        browser=Browser(CHROME,self.work/('card-browser-'+self.username));self.addCleanup(browser.close)
        browser.call('Network.enable',page=True)
        browser.call('Network.setCookie',dict(name='LOTTO_AUTH',value=self.cookie.split(';')[0].split('=',1)[1],url=self.url),page=True)
        browser.call('Emulation.setDeviceMetricsOverride',dict(width=1360,height=950,deviceScaleFactor=1,mobile=False),page=True)
        browser.call('Page.navigate',{'url':self.url+'/'},page=True)
        def wait(expression):
            for _ in range(160):
                if browser.value(expression):return
                time.sleep(.05)
            self.fail(expression)
        wait(f"typeof currentUser!=='undefined' && currentUser==={json.dumps(self.username)} && typeof store!=='undefined' && store.paypalBalance===500000")
        browser.value("document.getElementById('walletHistoryOpen').click();document.getElementById('walletCardTab').click()")
        wait("document.getElementById('accountCardBalance').textContent==='100.000.000'")
        self.assertEqual(browser.value("document.getElementById('accountCardId').textContent"),self.identity)
        self.assertEqual(browser.value("document.getElementById('accountCardHolder').textContent"),self.username)
        self.assertEqual(browser.value("document.getElementById('walletCardTab').getAttribute('aria-selected')"),'true')
        self.assertTrue(browser.value("document.getElementById('accountCardHistory').hidden"))
        artifacts=ROOT/'runtime/logs/account_card_20261103'
        (artifacts/'card-desktop.png').write_bytes(base64.b64decode(browser.call('Page.captureScreenshot',page=True)['data']))
        browser.value("document.getElementById('accountCardHistoryToggle').click()")
        wait("document.querySelectorAll('#cardHistoryRows tr').length===2")
        for kind in ['topup','withdraw']:
            browser.value(f"document.querySelector('[data-card-kind={kind}]').click()")
            wait("document.getElementById('cardHistoryStatus').textContent.includes('Chưa có')")
            self.assertEqual(browser.value("document.querySelectorAll('#cardHistoryRows tr').length"),0)
        browser.value("document.querySelector('[data-card-kind=reward]').click()")
        wait("document.querySelectorAll('#cardHistoryRows tr').length===1")
        browser.call('Emulation.setDeviceMetricsOverride',dict(width=390,height=844,deviceScaleFactor=1,mobile=False),page=True)
        self.assertTrue(browser.value("(()=>{const d=document.getElementById('walletHistoryDialog'),r=d.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&d.scrollWidth<=d.clientWidth})()"))
        (artifacts/'card-mobile.png').write_bytes(base64.b64decode(browser.call('Page.captureScreenshot',page=True)['data']))
        browser.value("document.getElementById('walletTransactionsTab').click()")
        wait("document.getElementById('walletHistoryBalance').textContent==='500.000'")
        browser.value("document.getElementById('walletCardTab').click();window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:false,user:''}}))")
        wait("!document.getElementById('walletHistoryDialog').open")
        self.assertEqual(browser.value("document.getElementById('accountCardId').textContent"),'—')
        self.assertEqual(cards.move_wallet_rewards(scope,apply=True)['count'],0)
