"""Presence and admin connection metadata on disposable servers/databases only."""
import base64
import json
import sqlite3
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from pathlib import Path

from tests import test_account_balances as fixtures
from tests.test_prize_web import CHROME, ROOT
from tests.browser_cdp import Browser


class UserAccessTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.AccountBalanceTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.AccountBalanceTests.tearDownClass.__func__)
    start_server = classmethod(fixtures.AccountBalanceTests.start_server.__func__)
    request = classmethod(fixtures.AccountBalanceTests.request.__func__)
    login = classmethod(fixtures.AccountBalanceTests.login.__func__)

    def listing(self, cookie=None):
        code,data,_=self.request('/api/admin/users',cookie=cookie or self.admin)
        self.assertEqual(code,200,data)
        return {u['username']:u for u in data['users']}

    def pulse(self, tab, state, cookie=None, ua='Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0.0.0 Safari/537.36', **fields):
        data=urllib.parse.urlencode(dict(tabId=tab,state=state,**fields)).encode()
        req=urllib.request.Request(self.url+'/api/presence',data=data,headers={'Cookie':cookie or self.member,'User-Agent':ua,'X-Forwarded-For':'203.0.113.99','Content-Type':'application/x-www-form-urlencoded'})
        try:
            with urllib.request.urlopen(req,timeout=10) as r:return r.status,json.load(r)
        except urllib.error.HTTPError as e:return e.code,json.load(e)

    def test_authenticated_metadata_three_states_and_resource_isolation(self):
        before=self.request('/api/store',cookie=self.member)[1]['store']
        self.assertEqual(self.request('/api/presence',dict(tabId='a'*24,state='active'))[0],401)
        member=self.listing()['member_fixture'];identity=member['accountId']
        self.assertEqual(self.request('/api/admin/user-access',dict(accountId=identity,flagged='true',reason='Kiểm tra'),self.admin)[0],405)
        self.assertEqual(self.pulse('bad','active')[0],400)
        self.assertEqual(self.pulse('a'*24,'fake')[0],400)
        self.assertEqual(self.pulse('a'*24,'active',accountId=self.listing()['owner_fixture']['accountId'],networkAddress='fake')[0],200)
        row=self.listing()['member_fixture']
        self.assertEqual(row['accessStatus'],'active')
        self.assertIn(row['networkAddress'],('127.0.0.1','0:0:0:0:0:0:0:1','::1'))
        self.assertEqual(row['device'],'Máy tính · Windows');self.assertEqual(row['browser'],'Chrome 130')
        self.assertGreater(row['lastSeen'],0)
        self.assertEqual(self.pulse('b'*24,'idle',ua='Mozilla/5.0 (Android 14; Mobile) Firefox/128.0')[0],200)
        self.assertEqual(self.listing()['member_fixture']['accessStatus'],'active')
        self.pulse('a'*24,'offline')
        self.assertEqual(self.listing()['member_fixture']['accessStatus'],'idle')
        self.pulse('b'*24,'offline')
        self.assertEqual(self.listing()['member_fixture']['accessStatus'],'offline')
        # Existing databases may retain historical flag columns. They must never
        # override automatic presence or appear in the public admin response.
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db, db:
            columns={row[1] for row in db.execute('PRAGMA table_info(account_access)')}
            if 'flagged' not in columns:db.execute('ALTER TABLE account_access ADD COLUMN flagged INTEGER NOT NULL DEFAULT 0')
            db.execute('UPDATE account_access SET flagged=1 WHERE account_id=?',(identity,))
        self.pulse('a'*24,'active')
        row=self.listing()['member_fixture'];self.assertEqual(row['accessStatus'],'active');self.assertNotIn('flagged',row);self.assertNotIn('flagReason',row)
        self.assertTrue(all(u['accessStatus'] in ('active','idle','offline') for u in self.listing().values()))
        self.request('/api/logout',{},self.member)
        self.assertEqual(self.listing()['member_fixture']['accessStatus'],'offline')
        self.assertEqual(self.pulse('a'*24,'active')[0],401)
        type(self).member=self.request('/api/login',dict(username='member_fixture',password='fixture_password'))[2]['Set-Cookie']
        self.assertEqual(self.request('/api/store',cookie=self.member)[1]['store'],before)

    def test_metadata_survives_restart_and_rename_without_reusing_identity(self):
        name='access_rename_fixture';self.assertEqual(self.request('/api/register',dict(username=name,password='fixture_password'))[0],200)
        cookie=self.request('/api/login',dict(username=name,password='fixture_password'))[2]['Set-Cookie']
        self.pulse('c'*24,'idle',cookie=cookie,ua='Mozilla/5.0 (iPhone) Version/18.0 Mobile Safari/604.1')
        identity=self.listing()[name]['accountId']
        self.assertEqual(self.request('/api/admin/rename-user',dict(username=name,newUsername=name+'_new'),self.admin)[0],200)
        row=self.listing()[name+'_new'];self.assertEqual(row['device'],'Điện thoại · iOS');self.assertEqual(row['browser'],'Safari 18')
        self.server.terminate();self.server.wait(timeout=10);self.start_server();self.login()
        row=self.listing()[name+'_new'];self.assertEqual(row['accountId'],identity)
        self.assertEqual(self.listing()[name+'_new']['accessStatus'],'offline')
        self.assertEqual(self.request('/api/admin/delete-user',dict(username=name+'_new'),self.admin)[0],200)
        self.request('/api/register',dict(username=name+'_new',password='fixture_password'))
        fresh=self.listing()[name+'_new'];self.assertNotEqual(fresh['accountId'],identity);self.assertEqual(fresh['networkAddress'],'')
        type(self).member=self.request('/api/login',dict(username='member_fixture',password='fixture_password'))[2]['Set-Cookie']

    def test_vip_column_uses_server_entitlement_and_preserves_resources(self):
        users=self.listing();member=users['member_fixture'];owner=users['owner_fixture']
        self.assertTrue(owner['vipActive'])
        before=(member['diamondBalance'],member['paypalBalance'])
        self.assertEqual(self.request('/api/admin/users',cookie=self.member)[0],403)
        form=dict(accountId=member['accountId'],expiresAt='2099-12-31T23:59:59Z')
        self.assertEqual(self.request('/api/admin/vip',form,self.member)[0],403)
        self.assertEqual(self.request('/api/admin/vip',form,self.admin)[0],200)
        active=self.listing()['member_fixture'];self.assertTrue(active['vipActive']);self.assertEqual(active['vipExpiresAt'],form['expiresAt'])
        form['expiresAt']='2000-01-01T00:00:00Z'
        self.assertEqual(self.request('/api/admin/vip',form,self.admin)[0],200)
        expired=self.listing()['member_fixture'];self.assertFalse(expired['vipActive']);self.assertEqual(expired['vipExpiresAt'],form['expiresAt'])
        self.assertEqual((expired['diamondBalance'],expired['paypalBalance']),before)

    @unittest.skipUnless(Path(CHROME).exists(),'Chrome required')
    def test_browser_three_states_search_and_responsive_table(self):
        browser=Browser(CHROME,self.work/'user-access-browser');images=ROOT/'Bin/session_1_latest/admin_user_filters_images';images.mkdir(exist_ok=True)
        def wait(expression):
            for _ in range(250):
                if browser.value(expression):return
                time.sleep(.05)
            self.fail('User access timeout: '+expression+' '+str(browser.value('window.accessErrors')))
        try:
            browser.call('Page.enable',page=True);browser.call('Network.enable',page=True)
            browser.call('Page.addScriptToEvaluateOnNewDocument',{'source':"window.accessErrors=[];addEventListener('error',e=>accessErrors.push(e.message));addEventListener('unhandledrejection',e=>accessErrors.push(String(e.reason)));const realFetch=fetch;window.presenceCalls=[];window.fetch=(url,opts)=>{if(String(url)==='/api/presence')presenceCalls.push(opts.body);if(String(url).startsWith('/api/live-'))return Promise.resolve(new Response(JSON.stringify({ok:true,results:[],rows:[],history:[],meta:{}}),{headers:{'Content-Type':'application/json'}}));return realFetch(url,opts)}"},page=True)
            browser.call('Network.setCookie',dict(name='LOTTO_AUTH',value=self.admin.split('=',1)[1].split(';',1)[0],url=self.url),page=True)
            browser.call('Page.navigate',dict(url=self.url+'/admin'),page=True)
            wait("!!window.adminPanel&&typeof currentUser!=='undefined'&&currentUser==='owner_fixture'")
            browser.value("document.querySelector('[data-admin-view=users]').click()")
            wait("document.getElementById('adminUserRows').textContent.includes('member_fixture')&&presenceCalls.length>0")
            self.assertEqual(browser.value("document.getElementById('adminPageTitle').textContent"),'Quản Lý Use')
            self.assertFalse(browser.value("!!document.querySelector('[data-account-history]')||document.querySelector('.admin-users-table thead').textContent.includes('Nhật ký')"))
            self.assertTrue(browser.value("document.querySelector('.admin-metrics').hidden"))
            self.assertEqual(browser.value("[...document.querySelectorAll('.admin-users-table th')].map(e=>e.textContent)")[2],'VIP')
            self.assertTrue(browser.value("[...document.querySelectorAll('#adminUserRows tr')].some(r=>r.textContent.includes('owner_fixture')&&r.querySelector('.admin-user-vip-badge.is-active')&&r.querySelector('.admin-user-vip').textContent.includes('Quyền quản trị'))"))
            self.assertTrue(browser.value("[...document.querySelectorAll('#adminUserRows tr')].some(r=>r.textContent.includes('member_fixture')&&r.querySelector('.admin-user-vip').textContent.includes('Chưa có'))"))
            # Drive the current browser to idle through elapsed inactivity, then resume
            # using a trusted keyboard event, without waiting five real minutes.
            browser.value("window.originalNow=Date.now;Date.now=()=>originalNow()+300001;document.dispatchEvent(new Event('visibilitychange'))")
            wait("presenceCalls.some(body=>new URLSearchParams(body).get('state')==='idle')")
            browser.value("Date.now=originalNow")
            time.sleep(.1)
            browser.call('Input.dispatchKeyEvent',dict(type='keyDown',key='Shift',code='ShiftLeft',windowsVirtualKeyCode=16),page=True)
            browser.call('Input.dispatchKeyEvent',dict(type='keyUp',key='Shift',code='ShiftLeft',windowsVirtualKeyCode=16),page=True)
            wait("presenceCalls.length>=3")
            identity=self.listing()['member_fixture']['accountId']
            self.pulse('d'*24,'idle')
            browser.value("document.getElementById('adminUsersRefresh').click()")
            wait("[...document.querySelectorAll('#adminUserRows tr')].some(r=>r.textContent.includes('member_fixture')&&!!r.querySelector('.is-idle'))")
            browser.value('document.getElementById("adminUserSearch").value='+json.dumps(identity)+';document.getElementById("adminUserSearchForm").requestSubmit()')
            self.assertEqual(browser.value("document.querySelectorAll('#adminUserRows tr').length"),1)
            self.assertFalse(browser.value("!!document.querySelector('[data-access-flag]')||!!document.getElementById('adminUserFlagDialog')||!!document.querySelector('.admin-users-card .is-irregular')"))
            self.assertEqual(browser.value("document.querySelectorAll('.admin-user-legend > span').length"),3)
            self.assertFalse(browser.value("document.getElementById('adminUsersMetrics').textContent.includes('Đã đánh dấu')"))
            browser.value("document.getElementById('adminUserSearch').value='';document.getElementById('adminUserSearch').dispatchEvent(new Event('input'))")
            self.assertEqual(self.request('/api/admin/vip',dict(accountId=identity,expiresAt='2099-12-31T23:59:59Z'),self.admin)[0],200)
            browser.value("document.getElementById('adminUsersRefresh').click()")
            wait("[...document.querySelectorAll('#adminUserRows tr')].some(r=>r.textContent.includes('member_fixture')&&r.querySelector('.admin-user-vip-badge.is-active'))")
            browser.value("document.getElementById('adminUsersFilterToggle').click()")
            self.assertTrue(browser.value("!document.getElementById('adminUsersFilters').hidden&&document.getElementById('adminUsersFilterToggle').getAttribute('aria-expanded')==='true'"))
            def select_filter(id,value):
                browser.value('document.getElementById('+json.dumps(id)+').value='+json.dumps(value)+';document.getElementById('+json.dumps(id)+').dispatchEvent(new Event("change"))')
            select_filter('adminUserRoleFilter','user');select_filter('adminUserVipFilter','active');select_filter('adminUserAccessFilter','idle')
            select_filter('adminUserDeviceFilter','Máy tính · Windows');select_filter('adminUserBrowserFilter','Chrome 130')
            self.assertEqual(browser.value("document.getElementById('adminUsersFilterBadge').textContent"),'5')
            self.assertEqual(browser.value("document.querySelectorAll('#adminUserRows tr').length"),1)
            self.assertTrue(browser.value("document.getElementById('adminUserRows').textContent.includes('member_fixture')"))
            select_filter('adminUserRoleFilter','admin')
            self.assertTrue(browser.value("document.getElementById('adminUserRows').textContent.includes('Không tìm thấy tài khoản')"),browser.value("({filters:[...document.querySelectorAll('#adminUsersFilters select')].map(e=>[e.id,e.value]),rows:document.getElementById('adminUserRows').textContent,errors:accessErrors})"))
            select_filter('adminUserRoleFilter','user')
            browser.value("document.getElementById('adminUserSearch').value='no-matching-ip';document.getElementById('adminUserSearch').dispatchEvent(new Event('input'))")
            self.assertTrue(browser.value("document.getElementById('adminUserRows').textContent.includes('Không tìm thấy tài khoản')"))
            browser.value("document.getElementById('adminUserSearch').value='127.0.0.1';document.getElementById('adminUserSearch').dispatchEvent(new Event('input'));window.previousUserRow=document.querySelector('#adminUserRows tr');document.getElementById('adminUsersRefresh').click()")
            wait("!previousUserRow.isConnected")
            self.assertEqual(browser.value("document.getElementById('adminUserBrowserFilter').value"),'Chrome 130')
            self.assertEqual(browser.value("document.getElementById('adminUsersFilterBadge').textContent"),'5')
            self.assertTrue(browser.value("document.getElementById('adminUserRows').textContent.includes('member_fixture')"))
            browser.value("document.getElementById('adminUsersFilterClear').click()")
            self.assertTrue(browser.value("document.getElementById('adminUsersFilterBadge').hidden&&document.getElementById('adminUsersFilterClear').disabled"))
            self.assertEqual(browser.value("document.getElementById('adminUserSearch').value"),'127.0.0.1')
            browser.value("document.getElementById('adminUserSearch').value='';document.getElementById('adminUserSearch').dispatchEvent(new Event('input'))")
            select_filter('adminUserVipFilter','expired')
            self.assertTrue(browser.value("document.getElementById('adminUserRows').textContent.includes('Không tìm thấy tài khoản')"))
            browser.value("document.getElementById('adminUsersFilterClear').click()")
            select_filter('adminUserAccessFilter','idle')
            for width in (320,390,768,1024,1440):
                browser.call('Emulation.setDeviceMetricsOverride',dict(width=width,height=1100,deviceScaleFactor=1,mobile=False),page=True)
                for light in (False,True):
                    browser.value(f'document.body.classList.toggle("light-theme",{str(light).lower()})')
                    # Let theme transitions settle before contrast checks and screenshots.
                    time.sleep(.3)
                    self.assertEqual(browser.value("getComputedStyle(document.getElementById('adminUserRoleFilter')).backgroundColor"),'rgb(255, 255, 255)' if light else 'rgb(16, 28, 43)')
                    self.assertTrue(browser.value("document.documentElement.scrollWidth<=innerWidth+1&&document.querySelector('.admin-users-card').scrollWidth<=document.querySelector('.admin-users-card').clientWidth+1"),(width,light))
                    self.assertTrue(browser.value("document.getElementById('adminUsersFilters').scrollWidth<=document.getElementById('adminUsersFilters').clientWidth+1"),(width,light))
                    if (width,light) in ((390,True),(1440,False)):
                        shot=browser.call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True),page=True);(images/f'users_{width}.png').write_bytes(base64.b64decode(shot['data']))
            browser.value("document.getElementById('adminUsersFilterClear').click();document.getElementById('adminUserRoleFilter').focus()")
            browser.call('Input.dispatchKeyEvent',dict(type='keyDown',key='Escape',code='Escape',windowsVirtualKeyCode=27),page=True)
            browser.call('Input.dispatchKeyEvent',dict(type='keyUp',key='Escape',code='Escape',windowsVirtualKeyCode=27),page=True)
            self.assertTrue(browser.value("document.getElementById('adminUsersFilters').hidden&&document.activeElement===document.getElementById('adminUsersFilterToggle')"))
            self.request('/api/admin/vip',dict(accountId=identity,expiresAt='2000-01-01T00:00:00Z'),self.admin)
            browser.value("document.getElementById('adminUsersRefresh').click()")
            wait("[...document.querySelectorAll('#adminUserRows tr')].some(r=>r.textContent.includes('member_fixture')&&r.querySelector('.admin-user-vip').textContent.includes('Hết hạn'))")
            select_filter('adminUserVipFilter','expired')
            self.assertEqual(browser.value("document.querySelectorAll('#adminUserRows tr').length"),1)
            self.assertTrue(browser.value("document.getElementById('adminUserRows').textContent.includes('member_fixture')"))
            browser.value("window.adminPanel.reset()")
            self.assertTrue(browser.value("document.getElementById('adminUserVipFilter').value===''&&document.getElementById('adminUsersFilters').hidden&&document.getElementById('adminUsersFilterBadge').hidden"))
            self.assertEqual(browser.value('accessErrors'),[])
        finally:browser.close()
