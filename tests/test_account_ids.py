"""Permanent numeric identities on disposable Java/SQLite accounts only."""
import concurrent.futures
import base64
import json
import os
import sqlite3
import subprocess
import time
import unittest
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from tests import test_account_balances as fixtures
from tests.browser_cdp import Browser
from tests.test_prize_web import CHROME, JAVA, JAVAC, ROOT


class AccountIdTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.AccountBalanceTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.AccountBalanceTests.tearDownClass.__func__)
    start_server = classmethod(fixtures.AccountBalanceTests.start_server.__func__)
    request = classmethod(fixtures.AccountBalanceTests.request.__func__)
    login = classmethod(fixtures.AccountBalanceTests.login.__func__)

    def new_user(self):
        name = 'id_'+uuid.uuid4().hex[:14]
        code, payload, _ = self.request('/api/register',dict(username=name,password='fixture_password',accountId='100000000000'))
        self.assertEqual(code,200,payload)
        self.assertRegex(payload['accountId'],r'^[1-9][0-9]{11}$')
        code, me, headers = self.request('/api/login',dict(username=name,password='fixture_password'))
        self.assertEqual(code,200)
        self.assertEqual(me['accountId'],payload['accountId'])
        return name,payload['accountId'],headers['Set-Cookie']

    def restart(self):
        self.server.terminate();self.server.wait(timeout=10)
        self.start_server();self.login()
        type(self).member=self.request('/api/login',dict(username='member_fixture',password='fixture_password'))[2]['Set-Cookie']

    def test_parallel_registration_unique_constraints_and_forced_collision_retry(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            accounts=list(pool.map(lambda _:self.new_user(),range(24)))
        ids=[account[1] for account in accounts]
        self.assertEqual(len(set(ids)),24)
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db,db:
            reserved='100000000000'
            db.execute("INSERT OR IGNORE INTO account_identities(account_id,username,last_username,created_at,deleted_at) VALUES(?,NULL,'retired_fixture','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')",(reserved,))
            self.assertRaises(sqlite3.IntegrityError,db.execute,"INSERT INTO account_identities(account_id,username,last_username,created_at) VALUES(?,'duplicate_fixture','duplicate_fixture','now')",(reserved,))
            self.assertRaises(sqlite3.IntegrityError,db.execute,"UPDATE account_identities SET account_id='999999999999' WHERE account_id=?",(reserved,))
            self.assertRaises(sqlite3.IntegrityError,db.execute,'DELETE FROM account_identities WHERE account_id=?',(reserved,))
            candidate='987654321098'
            while db.execute('SELECT 1 FROM account_identities WHERE account_id=?',(candidate,)).fetchone():candidate=str(int(candidate)-1)
        # Replace randomness only in this separate, disposable Java probe. The
        # first candidate is reserved, the second is free; no production hook.
        probe=self.work/'IdentityCollisionProbe.java'
        probe.write_text('''import java.lang.reflect.*;import java.security.SecureRandom;
public class IdentityCollisionProbe {
 static class Sequence extends SecureRandom {String first,second;int calls=0;Sequence(String a,String b){first=a;second=b;}public int nextInt(int bound){int position=calls++%12;String value=calls<=12?first:second;int digit=value.charAt(position)-'0';return position==0?digit-1:digit;}}
 public static void main(String[] args)throws Exception {
  LottoWebServer server=new LottoWebServer();Field random=LottoWebServer.class.getDeclaredField("random");random.setAccessible(true);Sequence sequence=new Sequence(args[0],args[1]);random.set(server,sequence);
  Field field=LottoWebServer.class.getDeclaredField("repo");field.setAccessible(true);Object repo=field.get(server);Method register=repo.getClass().getDeclaredMethod("register",String.class,String.class);register.setAccessible(true);
  register.invoke(repo,"collision_probe_fixture","fixture_password");Method get=repo.getClass().getDeclaredMethod("getUser",String.class);get.setAccessible(true);Object user=get.invoke(repo,"collision_probe_fixture");Field id=user.getClass().getDeclaredField("accountId");id.setAccessible(true);
  if(!args[1].equals(id.get(user))||sequence.calls!=24)throw new AssertionError("Collision did not retry");
  random.set(server,new Sequence(args[0],args[0]));boolean failed=false;try{register.invoke(repo,"collision_exhausted_fixture","fixture_password");}catch(InvocationTargetException expected){failed=expected.getCause() instanceof IllegalStateException;}
  if(!failed||get.invoke(repo,"collision_exhausted_fixture")!=null)throw new AssertionError("Exhaustion must roll back");System.out.println("collision_retry_and_rollback_ok");
 }}''',encoding='utf-8')
        compiled=subprocess.run([JAVAC,'-encoding','UTF-8','-cp','build','-d','build',probe.name],cwd=self.work,capture_output=True,text=True)
        self.assertEqual(compiled.returncode,0,compiled.stderr)
        checked=subprocess.run([JAVA,'-cp','build'+os.pathsep+'sqlite-jdbc.jar','IdentityCollisionProbe',reserved,candidate],cwd=self.work,capture_output=True,text=True,timeout=30)
        self.assertEqual(checked.returncode,0,checked.stderr)
        self.assertIn('collision_retry_and_rollback_ok',checked.stdout)

    def test_identity_stays_with_deposits_codes_resources_after_rename_and_delete(self):
        name,identity,cookie=self.new_user()
        self.assertEqual(self.request('/api/me',cookie=cookie)[1]['accountId'],identity)
        self.assertEqual(self.request('/api/store',cookie=cookie)[1]['store']['accountId'],identity)
        self.request('/api/store',dict(store=json.dumps(dict(accountId='100000000000',paypalBalance=999999))),cookie)
        self.assertEqual(self.request('/api/store',cookie=cookie)[1]['store']['accountId'],identity)
        self.assertEqual(self.request('/api/admin/update-assets',dict(accountId=identity,paypal=1234,diamond=3),cookie)[0],403)
        self.assertEqual(self.request('/api/admin/update-assets',dict(accountId=identity,username='owner_fixture',paypal=1234,diamond=3),self.admin)[0],400)
        self.assertEqual(self.request('/api/admin/update-assets',dict(accountId=identity,paypal=1234,diamond=3),self.admin)[0],200)
        form=dict(amount=100000,requestId=uuid.uuid4().hex,email='identity@example.test',channel='MB Bank',reference=uuid.uuid4().hex,accountId='100000000000')
        code,created,_=self.request('/api/payments/manual',form,cookie)
        self.assertEqual(code,200,created)
        order=created['order'];self.assertEqual(order['accountId'],identity)
        self.assertEqual(self.request('/api/admin/deposits/review',dict(id=order['id'],action='approve',reviewNote='ID fixture'),self.admin)[0],200)
        gift='ID_'+uuid.uuid4().hex[:12].upper()
        self.assertEqual(self.request('/api/admin/gift-codes',dict(code=gift,diamond=0,paypal=25,vipDays=0,bonusSpins=0,maxUses=1),self.admin)[0],200)
        code,reward,_=self.request('/api/gift-codes/redeem',dict(code=gift,accountId='100000000000'),cookie)
        self.assertEqual(code,200,reward)
        self.assertEqual(reward['store']['accountId'],identity)
        self.assertEqual(reward['store']['paypalBalance'],128134)
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db:
            self.assertEqual(db.execute('SELECT account_id FROM payment_orders WHERE id=?',(order['id'],)).fetchone()[0],identity)
            self.assertEqual(db.execute('SELECT account_id FROM gift_code_redemptions WHERE code=?',(gift,)).fetchone()[0],identity)
        renamed=name+'_new'
        self.assertEqual(self.request('/api/admin/rename-user',dict(accountId=identity,newUsername=renamed),self.admin)[0],200)
        cookie=self.request('/api/login',dict(username=renamed,password='fixture_password'))[2]['Set-Cookie']
        self.assertEqual(self.request('/api/me',cookie=cookie)[1]['accountId'],identity)
        self.assertEqual(self.request('/api/payments/manual',cookie=cookie)[1]['orders'][0]['accountId'],identity)
        self.assertEqual(self.request('/api/admin/account-history?accountId='+identity)[0],401)
        self.assertEqual(self.request('/api/admin/account-history?accountId='+identity,cookie=cookie)[0],403)
        history=self.request('/api/admin/account-history?accountId='+identity,cookie=self.admin)[1]
        self.assertTrue({'update_assets','manual_topup_credit','redeem_gift_code','account_renamed'}<={item['action'] for item in history['events']})
        self.assertTrue(all(item['accountId']==identity for item in history['events']))
        self.assertEqual(self.request('/api/admin/users?accountId='+identity,cookie=self.admin)[1]['users'][0]['username'],renamed)
        self.assertEqual(self.request('/api/admin/delete-user',dict(accountId=identity),self.admin)[0],200)
        history=self.request('/api/admin/account-history?accountId='+identity,cookie=self.admin)[1]
        self.assertTrue(history['deleted'])
        self.assertIn('account_deleted',{item['action'] for item in history['events']})
        self.assertEqual(self.request('/api/admin/update-assets',dict(accountId=identity,paypal=100,diamond=0),self.admin)[0],400)
        code,fresh,_=self.request('/api/register',dict(username=renamed,password='fixture_password',accountId=identity))
        self.assertEqual(code,200)
        self.assertNotEqual(fresh['accountId'],identity)
        self.assertTrue(self.request('/api/admin/account-history?accountId='+identity,cookie=self.admin)[1]['deleted'])

        self.restart()
        self.assertEqual(self.request('/api/admin/users?accountId='+fresh['accountId'],cookie=self.admin)[1]['users'][0]['username'],renamed)
        self.assertTrue(self.request('/api/admin/account-history?accountId='+identity,cookie=self.admin)[1]['deleted'])

    def test_existing_accounts_backfill_once_without_changing_wallets_or_orders(self):
        name,_,cookie=self.new_user()
        self.request('/api/admin/update-assets',dict(username=name,paypal=12345,diamond=7),self.admin)
        form=dict(amount=50000,requestId=uuid.uuid4().hex,email='legacy@example.test',channel='Agribank',reference=uuid.uuid4().hex)
        order=self.request('/api/payments/manual',form,cookie)[1]['order']
        self.server.terminate();self.server.wait(timeout=10)
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db,db:
            # Reproduce an account database from before identity allocation.
            for trigger in ('account_audit_identity','account_id_immutable','account_id_never_reuse'):
                db.execute('DROP TRIGGER '+trigger)
            db.execute('DROP TABLE account_activity_links')
            db.execute('DROP TABLE account_identities')
            db.execute("UPDATE payment_orders SET account_id=''")
            db.execute("UPDATE gift_code_redemptions SET account_id=''")
            wallet=db.execute('SELECT store_json FROM stores WHERE username=?',(name,)).fetchone()[0]
            counts=(db.execute('SELECT COUNT(*) FROM payment_orders').fetchone()[0],db.execute('SELECT COUNT(*) FROM account_audit').fetchone()[0])
        self.start_server();self.login()
        type(self).member=self.request('/api/login',dict(username='member_fixture',password='fixture_password'))[2]['Set-Cookie']
        info=self.request('/api/login',dict(username=name,password='fixture_password'))[1]
        self.assertRegex(info['accountId'],r'^[1-9][0-9]{11}$')
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db:
            self.assertEqual(db.execute('SELECT store_json FROM stores WHERE username=?',(name,)).fetchone()[0],wallet)
            self.assertEqual((db.execute('SELECT COUNT(*) FROM payment_orders').fetchone()[0],db.execute('SELECT COUNT(*) FROM account_audit').fetchone()[0]),counts)
            self.assertEqual(db.execute('SELECT account_id FROM payment_orders WHERE id=?',(order['id'],)).fetchone()[0],info['accountId'])
        self.restart()
        self.assertEqual(self.request('/api/admin/users?accountId='+info['accountId'],cookie=self.admin)[1]['users'][0]['username'],name)

    def test_python_wallet_audit_records_the_same_public_account_id(self):
        from ai import personal_tracking
        name,identity,cookie=self.new_user()
        before=self.request('/api/store',cookie=cookie)[1]['store']
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db,db:
            personal_tracking._audit(db,name,'identity_python_fixture',dict(fixture=True))
        history=self.request('/api/admin/account-history?accountId='+identity,cookie=self.admin)[1]
        event=next(item for item in history['events'] if item['action']=='identity_python_fixture')
        self.assertEqual(event['accountId'],identity)
        self.assertEqual(event['actorAccountId'],identity)
        self.assertEqual(self.request('/api/store',cookie=cookie)[1]['store'],before)

    @unittest.skipUnless(Path(CHROME).exists(),'Chrome required')
    def test_browser_id_labels_admin_search_history_and_resource_lookup(self):
        name,identity,cookie=self.new_user()
        browser=Browser(CHROME,self.work/'account-id-browser')
        def wait(expression):
            for _ in range(200):
                if browser.value(expression):return
                time.sleep(.05)
            self.fail('Browser timeout '+expression+' '+str(browser.value('window.identityErrors')))
        def navigate(auth,path):
            browser.call('Network.setCookie',dict(name='LOTTO_AUTH',value=auth.split('=',1)[1].split(';',1)[0],url=self.url),page=True)
            browser.call('Page.navigate',dict(url=self.url+path),page=True)
        try:
            browser.call('Page.enable',page=True);browser.call('Network.enable',page=True)
            browser.call('Page.addScriptToEvaluateOnNewDocument',dict(source="window.identityErrors=[];addEventListener('error',e=>identityErrors.push(e.message));addEventListener('unhandledrejection',e=>identityErrors.push(String(e.reason)));const idFetch=fetch;window.fetch=(input,opts)=>{const url=new URL(typeof input==='string'?input:input.url,location.href);if(url.pathname.startsWith('/api/live-'))return Promise.resolve(new Response(JSON.stringify({ok:true,results:[],rows:[],history:[],meta:{}}),{headers:{'Content-Type':'application/json'}}));return idFetch(input,opts)}"),page=True)
            navigate(cookie,'/nap-tien')
            wait('typeof currentAccountId!=="undefined" && currentAccountId==='+json.dumps(identity)+' && document.querySelector("#paypalDepositSection [data-current-account-id]").textContent.includes(currentAccountId)')
            self.assertEqual(browser.value("document.querySelector('#paypalDepositSection [data-current-account-id]').textContent"),'ID: '+identity)
            self.assertEqual(browser.value("document.querySelector('#sideMenu [data-current-account-id]')?.textContent || document.querySelector('.side-account-card [data-current-account-id]').textContent"),'ID: '+identity)
            self.assertEqual(browser.value("document.querySelector('#settingsCodeForm [data-current-account-id]').textContent"),'ID: '+identity)
            self.assertEqual(browser.value('identityErrors'),[])
            images=ROOT/'Bin/session_1_latest/account_ids_images';images.mkdir(exist_ok=True)
            wait("getComputedStyle(document.getElementById('pageLoader')).opacity==='0'")
            for width in (390,1440):
                browser.call('Emulation.setDeviceMetricsOverride',dict(width=width,height=1000,deviceScaleFactor=1,mobile=False),page=True)
                shot=browser.call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True),page=True)
                (images/f'deposit_{width}.png').write_bytes(base64.b64decode(shot['data']))
            navigate(self.admin,'/admin')
            wait('typeof currentUserRole!=="undefined" && currentUserRole==="admin" && !!window.adminPanel')
            browser.value("document.querySelector('[data-admin-view=users]').click()")
            wait('document.getElementById("adminUserRows").textContent.includes('+json.dumps(identity)+')')
            browser.value('document.getElementById("adminUserSearch").value='+json.dumps(identity)+';document.getElementById("adminUserSearch").dispatchEvent(new Event("input"));document.getElementById("adminUserSearchForm").requestSubmit()')
            self.assertEqual(browser.value('document.querySelectorAll("#adminUserRows tr").length'),1)
            self.assertIn(identity,browser.value('document.getElementById("adminUserRows").textContent'))
            self.assertFalse(browser.value('!!document.querySelector("[data-account-history]")'))
            wait("getComputedStyle(document.getElementById('pageLoader')).opacity==='0'")
            shot=browser.call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True),page=True)
            (images/'admin_history_1440.png').write_bytes(base64.b64decode(shot['data']))
            browser.value('openAccountManager()')
            wait('!!document.querySelector("#accountRows [data-account-id=\\"'+identity+'\\"]")')
            browser.value('document.getElementById("accountSearch").value='+json.dumps(identity)+';document.getElementById("accountSearch").dispatchEvent(new Event("input"))')
            self.assertEqual(browser.value('document.querySelectorAll("#accountRows tr[data-user]:not([hidden])").length'),1)
            for width in (320,390,768,1440):
                browser.call('Emulation.setDeviceMetricsOverride',dict(width=width,height=1000,deviceScaleFactor=1,mobile=False),page=True)
                for light in (False,True):
                    browser.value(f'document.body.classList.toggle("light-theme",{str(light).lower()})')
                    self.assertTrue(browser.value('document.documentElement.scrollWidth<=innerWidth+1'),(width,light))
            self.assertEqual(browser.value('identityErrors'),[])
            (ROOT/'Bin/session_1_latest/account_ids_browser_verification.json').write_text(json.dumps(dict(ok=True,liveDatabaseUsed=False,identityShownInDepositCodeAndSidebar=True,adminSearchAndHistoryById=True,resourceLookupById=True,responsiveLayouts=8),indent=2)+'\n',encoding='utf-8')
        finally:browser.close()
