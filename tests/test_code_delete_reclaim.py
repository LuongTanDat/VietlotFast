"""Delete with/without reclaim, negative balances and native choice dialog."""
import base64
import json
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from tests.test_code_selected_delete import SelectedDeleteTests
from tests.browser_cdp import Browser
from tests.test_prize_web import ROOT, CHROME


class ReclaimDeleteTests(SelectedDeleteTests):
    def reclaim(self, codes, value='1', cookie=None):
        return self.request('/api/admin/gift-codes',dict(action='delete',codes=codes,reclaimRewards=value),cookie or self.admin)

    def test_full_reclaim_negative_balances_vip_spins_and_debt_persistence(self):
        self.set_balance(0,0)
        self.change_wallet_fixture(luckyWheelStoredSpins=0,luckyWheelLastRegenAt=datetime.now(timezone.utc).isoformat().replace('+00:00','Z'))
        vip=(datetime.now(timezone.utc)+timedelta(days=30)).isoformat().replace('+00:00','Z')
        self.assertEqual(self.request('/api/admin/vip',dict(username='owner_fixture',expiresAt=vip),self.admin)[0],200)
        self.assertEqual(self.create_code('RECLAIM_FULL',paypal=400,diamond=100,vipDays=4,bonusSpins=6,maxPerUser=2)[0],200)
        for _ in range(2): self.assertEqual(self.redeem('RECLAIM_FULL')[0],200)
        self.change_wallet_fixture(paypalBalance=50,diamondBalance=5,luckyWheelStoredSpins=1)
        prior=json.loads(self.snapshot()[0]);received=self.listing()[1]['stats']['redemptions']
        status,data,_=self.reclaim('RECLAIM_FULL')
        self.assertEqual(status,200,data);self.assertTrue(data['reclaimed']);self.assertEqual(data['affectedUsers'],1)
        wallet=self.request('/api/store',cookie=self.admin)[1]['store']
        self.assertEqual((wallet['paypalBalance'],wallet['diamondBalance'],wallet['luckyWheelStoredSpins']),(-750,-195,-11))
        self.assertEqual(wallet['walletVersion'],prior['walletVersion']+1)
        self.assertLess(abs((datetime.fromisoformat(wallet['vipExpiresAt'].replace('Z','+00:00'))-datetime.fromisoformat(vip.replace('Z','+00:00'))).total_seconds()),.01)
        self.assertEqual(self.listing()[1]['stats']['redemptions'],received)
        self.assertEqual(self.reclaim('RECLAIM_FULL')[0],400)
        self.assertEqual(self.request('/api/store',cookie=self.admin)[1]['store']['paypalBalance'],-750)
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db:
            self.assertEqual(db.execute("SELECT received_count FROM gift_code_redemptions WHERE code='RECLAIM_FULL'").fetchone()[0],2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM account_audit WHERE action='reclaim_gift_code_rewards'").fetchone()[0],1)
        self.assertEqual(self.create_code('RECLAIM_DEBT_PAY',paypal=500,diamond=20,bonusSpins=3)[0],200)
        self.assertEqual(self.redeem('RECLAIM_DEBT_PAY')[0],200)
        wallet=self.request('/api/store',cookie=self.admin)[1]['store']
        self.assertEqual((wallet['paypalBalance'],wallet['diamondBalance'],wallet['luckyWheelStoredSpins']),(-250,-175,-8))
        for action in ['spin','exchange']:
            self.assertEqual(self.request('/api/wheel',dict(action=action,count=1,requestId='NEGATIVE_'+action),self.admin)[0],400)
        self.server.terminate();self.server.wait(timeout=10);self.start_server();self.login()
        wallet=self.request('/api/store',cookie=self.admin)[1]['store']
        self.assertEqual(wallet['paypalBalance'],-250)
        owner=next(u for u in self.request('/api/admin/users',cookie=self.admin)[1]['users'] if u['username']=='owner_fixture')
        self.assertEqual((owner['paypalBalance'],owner['diamondBalance']),(-250,-175))

    def test_no_reclaim_preserves_rewards_and_overflow_rolls_back_all(self):
        _, _, headers = self.request('/api/login',dict(username='member_fixture',password='fixture_password'))
        type(self).member = headers['Set-Cookie']
        self.set_balance(0,0)
        self.assertEqual(self.create_code('KEEP_REWARD',paypal=100)[0],200)
        self.assertEqual(self.redeem('KEEP_REWARD')[0],200)
        wallet=self.snapshot()[0]
        self.assertEqual(self.reclaim('KEEP_REWARD','invalid')[0],400)
        self.assertEqual(self.reclaim('KEEP_REWARD',cookie=self.member)[0],403)
        self.assertEqual(self.reclaim('KEEP_REWARD','0')[0],200)
        self.assertEqual(self.snapshot()[0],wallet)
        self.assertEqual(self.create_code('RECLAIM_OVERFLOW',paypal=9007199254740991,maxPerUser=2)[0],200)
        for _ in range(2):
            self.set_balance(0,0);self.assertEqual(self.redeem('RECLAIM_OVERFLOW')[0],200)
        self.set_balance(0,0)
        self.assertEqual(self.create_code('RECLAIM_OVERFLOW_KEEP',paypal=1)[0],200)
        self.assertEqual(self.reclaim('RECLAIM_OVERFLOW_KEEP\nRECLAIM_OVERFLOW')[0],400)
        self.assertEqual(self.listing('?q=RECLAIM_OVERFLOW')[1]['total'],2)
        self.assertEqual(json.loads(self.snapshot()[0])['paypalBalance'],0)

    def test_dialog_yes_no_cancel_escape_reset_and_signed_display(self):
        self.set_balance(0,0)
        self.assertEqual(self.create_code('UI_RECLAIM',paypal=100)[0],200)
        self.assertEqual(self.redeem('UI_RECLAIM')[0],200)
        self.set_balance(0,0)
        b=Browser(CHROME,self.work/'reclaim-dialog-profile')
        def wait(expression):
            for _ in range(300):
                if b.value(expression): return
                time.sleep(.05)
            raise AssertionError(expression)
        def select_code():
            b.value("document.getElementById('adminListTab').click();document.getElementById('adminCodeSearch').value='UI_RECLAIM';document.getElementById('adminCodeSearchForm').requestSubmit()")
            wait("document.querySelectorAll('#adminCodeRows [data-admin-select]').length===1")
            b.value("if(document.getElementById('adminDeleteCodesBtn').textContent==='Chỉnh Sửa')document.getElementById('adminDeleteCodesBtn').click();document.querySelector('#adminCodeRows [data-admin-select]').click()")
        try:
            b.call('Network.enable',page=True)
            b.call('Network.setCookie',dict(name='LOTTO_AUTH',value=self.admin.split(';')[0].split('=',1)[1],url=self.url),page=True)
            b.call('Page.navigate',dict(url=self.url+'/admin'),page=True)
            wait("!!window.adminPanel && !document.getElementById('adminPanelSection').hidden && getComputedStyle(document.getElementById('pageLoader')).opacity==='0'")
            select_code()
            b.value("document.getElementById('adminDeleteCodesBtn').click()")
            self.assertTrue(b.value("document.getElementById('adminReclaimDialog').open && document.activeElement.id==='adminReclaimNoBtn'"))
            b.call('Input.dispatchKeyEvent',dict(type='keyDown',key='Escape',code='Escape',windowsVirtualKeyCode=27),page=True)
            b.call('Input.dispatchKeyEvent',dict(type='keyUp',key='Escape',code='Escape',windowsVirtualKeyCode=27),page=True)
            wait("!document.getElementById('adminReclaimDialog').open && !document.getElementById('adminDeleteCodesBtn').disabled")
            self.assertEqual(self.listing('?q=UI_RECLAIM')[1]['total'],1)
            b.value("document.getElementById('adminDeleteCodesBtn').click();adminPanel.reset()")
            wait("!document.getElementById('adminReclaimDialog').open")
            select_code()
            checks=[]
            for theme in ['dark','light']:
                b.value("document.body.classList.toggle('light-theme',"+str(theme=='light').lower()+")")
                for width in [1440,390,320]:
                    b.call('Emulation.setDeviceMetricsOverride',dict(width=width,height=844,deviceScaleFactor=1,mobile=width<500),page=True)
                    b.value("document.getElementById('adminDeleteCodesBtn').click()")
                    data=b.value("(()=>{const r=document.getElementById('adminReclaimDialog').getBoundingClientRect(),a=document.getElementById('adminReclaimYesBtn').getBoundingClientRect(),c=document.getElementById('adminReclaimNoBtn').getBoundingClientRect();return {inside:r.left>=0&&r.right<=innerWidth,equalButtons:Math.abs(a.width-c.width)<.1&&a.height===c.height,centerError:Math.abs(r.left+r.width/2-document.documentElement.clientWidth/2)}})()")
                    self.assertTrue(data['inside'] and data['equalButtons']);self.assertLess(data['centerError'],1)
                    checks.append(dict(theme=theme,width=width,**data))
                    if (theme,width) in [('dark',1440),('light',390)]:
                        shot=b.call('Page.captureScreenshot',dict(format='png'),page=True)
                        (ROOT/f'Bin/session_1_latest/code_reclaim_dialog_{theme}_{width}.png').write_bytes(base64.b64decode(shot['data']))
                    b.value("document.getElementById('adminReclaimCancelBtn').click()")
                    wait("!document.getElementById('adminDeleteCodesBtn').disabled")
            b.value("document.getElementById('adminDeleteCodesBtn').click();document.getElementById('adminReclaimYesBtn').click()")
            wait("document.getElementById('adminPageMessage').textContent.includes('Đã thu hồi vật phẩm.') && store.paypalBalance===-100")
            self.assertEqual(self.request('/api/store',cookie=self.admin)[1]['store']['paypalBalance'],-100)
            self.assertIn('100',b.value("document.getElementById('paypalBalance').textContent"))
            self.assertTrue(b.value("document.getElementById('paypalBalance').textContent.startsWith('−') && formatCompactBalance(-1000000)==='−1Tr'"))
            b.call('Page.reload',page=True)
            wait("!!window.adminPanel && !document.getElementById('adminPanelSection').hidden && store.paypalBalance===-100")
            self.assertTrue(b.value("document.getElementById('paypalBalance').textContent.startsWith('−')"))
            (ROOT/'Bin/session_1_latest/code_reclaim_dialog_verification.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
        finally: b.close()
