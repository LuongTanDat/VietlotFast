"""Gift code permissions, atomic rewards, limits, persistence and full Settings UI."""
import base64
import json
import sqlite3
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.test_account_balances import AccountBalanceTests
from tests.browser_cdp import Browser
from tests.test_prize_web import ROOT, CHROME


class GiftCodeTests(AccountBalanceTests):
    def create_code(self, code='', **rewards):
        form = dict(code=code, diamond=0, paypal=0, vipDays=0, bonusSpins=0, maxUses=10)
        form.update(rewards)
        return self.request('/api/admin/gift-codes', form, self.admin)

    def redeem(self, code, cookie=None):
        return self.request('/api/gift-codes/redeem', dict(code=code), cookie or self.admin)

    def change_wallet_fixture(self, **values):
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db:
            row = db.execute("SELECT store_json FROM stores WHERE username='owner_fixture'").fetchone()
            wallet = json.loads(row[0]) if row else {}
            wallet.update(values)
            db.execute('INSERT OR REPLACE INTO stores VALUES(?,?)', ('owner_fixture',json.dumps(wallet)))
            db.commit()

    def test_code_rate_limit_is_account_scoped(self):
        self.assertEqual(self.request('/api/register',dict(username='rate_fixture',password='fixture_password'))[0],200)
        _,_,headers=self.request('/api/login',dict(username='rate_fixture',password='fixture_password'))
        cookie=headers['Set-Cookie']
        for _ in range(20):
            self.assertEqual(self.redeem('UNKNOWN_FIXTURE',cookie)[0],400)
        self.assertEqual(self.redeem('UNKNOWN_FIXTURE',cookie)[0],429)
        self.assertEqual(self.create_code('RATE_SCOPE_FIXTURE',paypal=1)[0],200)
        self.assertEqual(self.redeem('RATE_SCOPE_FIXTURE')[0],200)

    def test_code_rewards_vip_extension_and_duplicate_account(self):
        self.set_balance(350000)
        self.change_wallet_fixture(luckyWheelStoredSpins=10, luckyWheelLastRegenAt=datetime.now(timezone.utc).isoformat())
        old_expiry = datetime.now(timezone.utc)+timedelta(days=2)
        self.assertEqual(self.request('/api/admin/vip', dict(username='owner_fixture', expiresAt=old_expiry.isoformat().replace('+00:00','Z')),self.admin)[0],200)
        self.assertEqual(self.create_code('COMBO_FIXTURE',paypal=9999999999,diamond=100,vipDays=7,bonusSpins=3)[0],200)
        code, data, _ = self.redeem(' combo_fixture ')
        self.assertEqual(code,200)
        self.assertEqual(data['reward'],dict(paypal=9999999999,diamond=100,vipDays=7,bonusSpins=3))
        self.assertEqual(data['store']['paypalBalance'],10000349999)
        self.assertEqual(data['store']['diamondBalance'],9295)
        self.assertEqual(data['store']['luckyWheelStoredSpins'],13)
        expiry = datetime.fromisoformat(data['store']['vipExpiresAt'].replace('Z','+00:00'))
        self.assertAlmostEqual((expiry-old_expiry).total_seconds(),7*86400,places=2)
        before = self.snapshot()
        self.assertEqual(self.redeem('COMBO_FIXTURE')[0],400)
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.request('/api/store',cookie=self.admin)[1]['store']['paypalBalance'],10000349999)

    def test_code_validation_expiry_overflow_and_full_spin_wallet_do_not_consume(self):
        self.assertEqual(self.request('/api/admin/gift-codes',dict(code='NO_ACCESS',paypal=1,maxUses=1),self.member)[0],403)
        self.assertEqual(self.request('/api/gift-codes/redeem',dict(code='NO_ACCESS'))[0],401)
        self.assertEqual(self.create_code('EMPTY_FIXTURE')[0],400)
        for field, value in [('paypal','-1'),('vipDays',3661),('bonusSpins',61),('maxUses',0),('code','bad code')]:
            form = dict(paypal=1); form[field] = value
            if field=='code':
                self.assertEqual(self.create_code(**form)[0],400)
            else:
                self.assertEqual(self.create_code('INVALID_FIXTURE',**form)[0],400)
        self.assertEqual(self.create_code('OVERFLOW_FIXTURE',paypal=1)[0],200)
        self.set_balance(9007199254740991)
        before = self.snapshot()
        self.assertEqual(self.redeem('OVERFLOW_FIXTURE')[0],400)
        self.assertEqual(self.snapshot(),before)
        self.set_balance(350000)
        self.assertEqual(self.redeem('OVERFLOW_FIXTURE')[0],200)
        self.assertEqual(self.create_code('SPINS_FIXTURE',bonusSpins=5)[0],200)
        self.change_wallet_fixture(luckyWheelStoredSpins=60)
        before=self.snapshot()
        self.assertEqual(self.redeem('SPINS_FIXTURE')[0],400)
        self.assertEqual(self.snapshot(),before)
        self.change_wallet_fixture(luckyWheelStoredSpins=50,luckyWheelLastRegenAt=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat().replace('+00:00','Z'))
        before=self.snapshot()
        self.assertEqual(self.redeem('SPINS_FIXTURE')[0],400)
        self.assertEqual(self.snapshot(),before)
        self.change_wallet_fixture(luckyWheelStoredSpins=10,luckyWheelLastRegenAt=datetime.now(timezone.utc).isoformat())
        self.assertEqual(self.redeem('SPINS_FIXTURE')[1]['store']['luckyWheelStoredSpins'],15)
        self.assertEqual(self.create_code('EXPIRED_FIXTURE',paypal=1)[0],200)
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db:
            db.execute("UPDATE gift_codes SET expires_at='2000-01-01T00:00:00Z' WHERE code='EXPIRED_FIXTURE'")
            db.commit()
        before=self.snapshot()
        self.assertEqual(self.redeem('EXPIRED_FIXTURE')[0],400)
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.create_code('OLD_EXPIRY',paypal=1,expiresAt='2000-01-01T00:00:00Z')[0],400)

    def test_concurrent_redemption_limit_and_renamed_account_cannot_redeem_twice(self):
        self.set_balance(350000)
        self.assertEqual(self.create_code('CONCURRENT_FIXTURE',paypal=100,maxUses=1)[0],200)
        with ThreadPoolExecutor(max_workers=5) as pool:
            results=list(pool.map(lambda _:self.redeem('CONCURRENT_FIXTURE')[0],range(5)))
        self.assertEqual(results.count(200),1)
        self.assertEqual(json.loads(self.snapshot()[0])['paypalBalance'],350100)
        self.assertEqual(self.redeem('CONCURRENT_FIXTURE',self.member)[0],400)
        self.assertEqual(self.create_code('RENAME_FIXTURE',paypal=50,maxUses=10)[0],200)
        self.assertEqual(self.redeem('RENAME_FIXTURE',self.member)[0],200)
        self.assertEqual(self.request('/api/admin/rename-user',dict(username='member_fixture',newUsername='renamed_fixture'),self.admin)[0],200)
        _,_,headers=self.request('/api/login',dict(username='renamed_fixture',password='fixture_password'))
        self.assertEqual(self.redeem('RENAME_FIXTURE',headers['Set-Cookie'])[0],400)
        self.assertEqual(self.request('/api/admin/rename-user',dict(username='renamed_fixture',newUsername='member_fixture'),self.admin)[0],200)
        _,_,headers=self.request('/api/login',dict(username='member_fixture',password='fixture_password'))
        type(self).member=headers['Set-Cookie']

    def test_large_balances_survive_users_store_and_server_restart(self):
        super().test_large_balances_survive_users_store_and_server_restart()
        code,data,_=self.redeem('COMBO_FIXTURE')
        self.assertEqual(code,400)
        self.assertIn('đã sử dụng',data['message'])

    @unittest.skipUnless(Path(CHROME).exists(),'Chrome required')
    def test_settings_code_ui_create_redeem_and_mobile_layout(self):
        self.set_balance(350000)
        browser=Browser(CHROME,self.work/f'gift-ui-profile-{time.time_ns()}')
        output=ROOT/'Bin/session_1_latest/settings_code_images'
        output.mkdir(exist_ok=True)
        def wait(expression):
            for _ in range(200):
                if browser.value(expression): return
                time.sleep(.05)
            raise AssertionError('Timeout: '+expression)
        def submit(form):
            result=browser.call('Runtime.evaluate',dict(expression=f"document.getElementById('{form}').onsubmit({{preventDefault(){{}},currentTarget:document.getElementById('{form}')}})",awaitPromise=True,returnByValue=True),page=True)
            self.assertNotIn('exceptionDetails',result,result)
        try:
            browser.call('Page.enable',page=True)
            browser.call('Network.enable',page=True)
            browser.call('Network.setCookie',dict(name='LOTTO_AUTH',value=self.admin.split(';')[0].split('=',1)[1],url=self.url),page=True)
            browser.call('Page.navigate',dict(url=self.url+'/'),page=True)
            wait("typeof api==='function' && !!document.getElementById('adminUsersEdit')")
            browser.value("document.getElementById('settingsBtn').click()")
            self.assertTrue(browser.value("document.getElementById('settingsCodeForm').hidden"))
            self.assertEqual(browser.value("document.getElementById('settingsCodeBtn').getAttribute('aria-expanded')"),'false')
            browser.value("document.getElementById('settingsCodeBtn').click()")
            self.assertEqual(browser.value("document.activeElement.id"),'settingsCodeInput')
            self.assertFalse(browser.value("document.getElementById('settingsAdminBtn').hidden"))
            browser.value("document.getElementById('settingsAdminBtn').click()")
            wait("location.pathname==='/admin' && !!window.adminPanel")
            browser.value("document.getElementById('settingsNewCode').value='BROWSER_FIXTURE';document.getElementById('settingsCodePaypal').value='1.000.000';document.getElementById('settingsCodeDiamond').value='50';document.getElementById('settingsCodeVipDays').value='3';document.getElementById('settingsCodeMaxUses').value='2'")
            submit('settingsCreateCodeForm')
            self.assertTrue(browser.value("document.getElementById('adminCodeSuccess').hidden && document.getElementById('settingsNewCode').value==='' && document.getElementById('settingsCodePaypal').value==='0'"))
            browser.value("navigateToAppPage('home');document.getElementById('settingsBtn').click();document.getElementById('settingsCodeBtn').click();document.getElementById('settingsCodeInput').value='browser_fixture'")
            submit('settingsCodeForm')
            message=browser.value("document.getElementById('settingsCodeMessage').textContent")
            self.assertIn('1.000.000 PayPal',message)
            self.assertIn('50 kim cương',message)
            self.assertIn('3 ngày VIP',message)
            self.assertEqual(json.loads(self.snapshot()[0])['paypalBalance'],1350000)
            self.assertEqual(browser.value("store.paypalBalance"),1350000)
            self.assertEqual(browser.value("document.getElementById('paypalBalance').textContent"),'1,35Tr')
            browser.value("document.getElementById('settingsCodeInput').value='BROWSER_FIXTURE'")
            submit('settingsCodeForm')
            self.assertIn('đã sử dụng',browser.value("document.getElementById('settingsCodeMessage').textContent"))
            self.assertEqual(json.loads(self.snapshot()[0])['paypalBalance'],1350000)
            for theme in ('dark','light'):
                browser.value(f"document.body.classList.toggle('light-theme',{str(theme=='light').lower()})")
                for width in (320,390,1440):
                    browser.call('Emulation.setDeviceMetricsOverride',dict(width=width,height=900,deviceScaleFactor=1,mobile=width<500),page=True)
                    for state in ('closed','input'):
                        browser.value("document.getElementById('settingsCodeForm').hidden="+str(state=='closed').lower())
                        bounds=browser.value("(()=>{const p=document.getElementById('settingsPanel'),r=p.getBoundingClientRect();return {left:r.left,right:r.right,width:p.clientWidth,scroll:p.scrollWidth,overflow:[...p.querySelectorAll('*')].filter(e=>e.getBoundingClientRect().right>r.right).map(e=>({tag:e.tagName,id:e.id,width:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right}))}})()")
                        self.assertTrue(browser.value("(()=>{const r=document.getElementById('settingsCodeBtn').getBoundingClientRect(),b=document.getElementById('settingsReloadBtn').getBoundingClientRect();return Math.abs(r.width-b.width)<1&&Math.abs(r.height-b.height)<1})()"))
                        clip=browser.value("(()=>{const r=document.getElementById('settingsPanel').getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,scale:1}})()")
                        shot=browser.call('Page.captureScreenshot',dict(format='png',clip=clip,captureBeyondViewport=True),page=True)
                        (output/f'{theme}_{width}_{state}.png').write_bytes(base64.b64decode(shot['data']))
                        self.assertTrue(bounds['left']>=0 and bounds['right']<=width+1 and bounds['scroll']<=bounds['width']+1,(theme,width,state,bounds))
            browser.call('Input.dispatchKeyEvent',dict(type='keyDown',key='Escape',code='Escape',windowsVirtualKeyCode=27),page=True)
            self.assertTrue(browser.value("document.getElementById('settingsPanel').hidden"))
            browser.value("currentUserRole='user';syncSideAccountIdentity();document.getElementById('settingsBtn').click();document.getElementById('settingsCodeBtn').click()")
            self.assertTrue(browser.value("document.getElementById('settingsAdminBtn').hidden"))
        finally:
            browser.close()


if __name__=='__main__':
    unittest.main()
