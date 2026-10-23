"""Inline Admin wallet editing against an isolated Java server and database."""
import base64
import json
import time
import unittest
from pathlib import Path

from tests import test_account_balances as fixtures
from tests.browser_cdp import Browser
from tests.test_prize_web import ROOT, CHROME


class InlineBalanceTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.AccountBalanceTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.AccountBalanceTests.tearDownClass.__func__)
    start_server = classmethod(fixtures.AccountBalanceTests.start_server.__func__)
    login = classmethod(fixtures.AccountBalanceTests.login.__func__)
    request = classmethod(fixtures.AccountBalanceTests.request.__func__)
    snapshot = classmethod(fixtures.AccountBalanceTests.snapshot.__func__)

    def users(self):
        return {row['username']: row for row in self.request('/api/admin/users', cookie=self.admin)[1]['users']}

    def test_expected_balances_reject_stale_changes_without_writes(self):
        owner = self.users()['owner_fixture']
        body = dict(username='owner_fixture', accountId=owner['accountId'], diamond=100, paypal=200,
                    expectedDiamond=owner['diamondBalance'], expectedPaypal=owner['paypalBalance'])
        self.assertEqual(self.request('/api/admin/update-assets',body,self.admin)[0],200)
        before = self.snapshot()
        body.update(diamond=300,paypal=400)
        code,data,_=self.request('/api/admin/update-assets',body,self.admin)
        self.assertEqual(code,400);self.assertIn('Số dư đã thay đổi',data['message'])
        self.assertEqual(self.snapshot(),before)
        body.update(expectedDiamond=100,expectedPaypal=200)
        self.assertEqual(self.request('/api/admin/update-assets',body,self.member)[0],403)
        self.assertEqual(self.snapshot(),before)
        del body['expectedPaypal']
        self.assertEqual(self.request('/api/admin/update-assets',body,self.admin)[0],400)
        self.assertEqual(self.snapshot(),before)
        body['expectedPaypal']=200
        self.assertEqual(self.request('/api/admin/update-assets',body,self.admin)[0],200)

    @unittest.skipUnless(Path(CHROME).exists(),'Chrome required')
    def test_browser_inline_validation_drafts_save_cancel_and_conflict(self):
        for name,diamond,paypal in [('owner_fixture',9195,350000),('member_fixture',7,55)]:
            self.assertEqual(self.request('/api/admin/update-assets',dict(username=name,diamond=diamond,paypal=paypal),self.admin)[0],200)
        identities={name:row['accountId'] for name,row in self.users().items()}
        browser=Browser(CHROME,self.work/'inline-balances-browser')
        def wait(expression):
            for _ in range(250):
                if browser.value(expression):return
                time.sleep(.05)
            self.fail('Timeout: '+expression+' '+str(browser.value('window.inlineErrors')))
        def selector(name,key):return f'#adminUserRows input[data-account-id="{identities[name]}"][data-user-balance="{key}"]'
        def edit(name,key,text):
            target=json.dumps(selector(name,key))
            browser.value(f'document.querySelector({target}).focus();document.querySelector({target}).select()')
            browser.call('Input.insertText',dict(text=text),page=True)
        def save():
            result=browser.call('Runtime.evaluate',dict(expression="document.getElementById('adminUsersEdit').onclick()",awaitPromise=True,returnByValue=True),page=True)
            self.assertNotIn('exceptionDetails',result,result)
        def search(text):
            browser.value('document.getElementById("adminUserSearch").value='+json.dumps(text)+';document.getElementById("adminUserSearch").dispatchEvent(new Event("input"))')
        try:
            browser.call('Page.enable',page=True);browser.call('Network.enable',page=True)
            browser.call('Page.addScriptToEvaluateOnNewDocument',dict(source="window.inlineErrors=[];window.assetCalls=[];window.userReads=0;addEventListener('error',e=>inlineErrors.push(e.message));addEventListener('unhandledrejection',e=>inlineErrors.push(String(e.reason)));const realFetch=fetch;window.fetch=(url,opts)=>{if(String(url)==='/api/admin/update-assets')assetCalls.push(opts.body);if(String(url)==='/api/admin/users')userReads++;if(String(url).startsWith('/api/live-'))return Promise.resolve(new Response(JSON.stringify({ok:true,results:[],rows:[],history:[],meta:{}}),{headers:{'Content-Type':'application/json'}}));return realFetch(url,opts)}"),page=True)
            browser.call('Network.setCookie',dict(name='LOTTO_AUTH',value=self.admin.split('=',1)[1].split(';',1)[0],url=self.url),page=True)
            browser.call('Page.navigate',dict(url=self.url+'/admin'),page=True)
            wait("!!window.adminPanel&&typeof currentUser!=='undefined'&&currentUser==='owner_fixture'")
            browser.value("document.querySelector('[data-admin-view=users]').click()")
            wait("document.getElementById('adminUserRows').textContent.includes('member_fixture')")
            self.assertFalse(browser.value("!!document.getElementById('openAccountBtn')"))
            self.assertEqual(browser.value("document.getElementById('adminUsersEdit').textContent"),'Chỉnh Sửa')
            browser.value("document.getElementById('adminUsersEdit').click()")
            self.assertEqual(browser.value("document.querySelectorAll('#adminUserRows input[data-user-balance]').length"),4)
            self.assertTrue(browser.value("document.getElementById('adminUsersRefresh').disabled&&!document.getElementById('adminUsersEditCancel').hidden"))
            before=self.snapshot();save();self.assertEqual(self.snapshot(),before)
            self.assertEqual(browser.value('assetCalls.length'),0)
            wait("document.getElementById('adminUsersEdit').textContent==='Chỉnh Sửa'&&!document.getElementById('adminUsersEdit').disabled")
            browser.value("document.getElementById('adminUsersEdit').click()")
            edit('owner_fixture','paypal','1000000000000')
            self.assertEqual(browser.value('document.querySelector('+json.dumps(selector('owner_fixture','paypal'))+').value'),'1.000.000.000.000')
            edit('member_fixture','diamond','-1');save()
            self.assertEqual(browser.value('assetCalls.length'),0);self.assertEqual(self.snapshot(),before)
            self.assertTrue(browser.value("document.getElementById('adminUsersEditMessage').classList.contains('is-error')"))
            edit('member_fixture','diamond','2500000')
            search('member_fixture');search('owner_fixture')
            self.assertEqual(browser.value('document.querySelector('+json.dumps(selector('owner_fixture','paypal'))+').value'),'1.000.000.000.000')
            reads=browser.value('userReads');browser.value("document.dispatchEvent(new Event('visibilitychange'))")
            self.assertEqual(browser.value('userReads'),reads)
            search('');save()
            wait("document.getElementById('adminUsersEdit').textContent==='Chỉnh Sửa'&&!document.getElementById('adminUsersEdit').disabled")
            self.assertEqual(browser.value('assetCalls.length'),2)
            rows=self.users();self.assertEqual(rows['owner_fixture']['paypalBalance'],1000000000000)
            self.assertEqual(rows['owner_fixture']['diamondBalance'],9195)
            self.assertEqual(rows['member_fixture']['diamondBalance'],2500000)
            self.assertEqual(rows['member_fixture']['paypalBalance'],55)
            self.assertEqual(browser.value('store.paypalBalance'),1000000000000)
            wait("document.getElementById('adminUserRows').textContent.includes('owner_fixture')")
            browser.value("document.getElementById('adminUsersEdit').click()")
            edit('owner_fixture','diamond','0');edit('member_fixture','paypal','999')
            # Another authenticated writer changes the member's wallet after editing began.
            self.request('/api/admin/update-assets',dict(username='member_fixture',diamond=2500000,paypal=66),self.admin)
            save();self.assertEqual(browser.value('assetCalls.length'),4)
            self.assertEqual(browser.value("document.getElementById('adminUsersEdit').textContent"),'Lưu')
            self.assertIn('Số dư đã thay đổi',browser.value("document.getElementById('adminUsersEditMessage').textContent"))
            self.assertEqual(self.users()['member_fixture']['paypalBalance'],66)
            self.assertEqual(self.users()['owner_fixture']['diamondBalance'],0)
            # Retrying submits only the failed row, preserving successful rows and drafts.
            save();self.assertEqual(browser.value('assetCalls.length'),5)
            self.assertEqual(browser.value('document.querySelector('+json.dumps(selector('member_fixture','paypal'))+').value'),'999')
            browser.value("window.beforeCancelRow=document.querySelector('#adminUserRows tr');document.getElementById('adminUsersEditCancel').click()")
            wait("document.getElementById('adminUsersEdit').textContent==='Chỉnh Sửa'&&document.querySelectorAll('#adminUserRows input').length===0")
            wait("!beforeCancelRow.isConnected&&!document.getElementById('adminUsersEdit').disabled")
            browser.value("document.getElementById('adminUsersEdit').click()")
            self.assertEqual(browser.value('document.querySelector('+json.dumps(selector('member_fixture','paypal'))+').value'),'66')
            edit('member_fixture','paypal','0');save()
            self.assertEqual(self.users()['member_fixture']['paypalBalance'],0)
            time.sleep(.2);browser.value("document.getElementById('adminUsersEdit').click()")
            images=ROOT/'Bin/session_1_latest/inline_user_balances_images';images.mkdir(exist_ok=True)
            for width in (390,1440):
                browser.call('Emulation.setDeviceMetricsOverride',dict(width=width,height=1000,deviceScaleFactor=1,mobile=False),page=True)
                browser.value("document.querySelector('.admin-users-card .admin-table-scroll').scrollLeft=9999")
                time.sleep(.3)
                self.assertTrue(browser.value("document.documentElement.scrollWidth<=innerWidth+1"))
                shot=browser.call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True),page=True)
                (images/f'edit_{width}.png').write_bytes(base64.b64decode(shot['data']))
            browser.value("window.adminPanel.reset()")
            self.assertTrue(browser.value("document.querySelectorAll('#adminUserRows input').length===0&&document.getElementById('adminUsersEditMessage').hidden&&document.getElementById('adminUsersEditCancel').hidden"))
            self.assertEqual(browser.value('inlineErrors'),[])
        finally:browser.close()
