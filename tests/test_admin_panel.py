"""Admin code page and API with disposable Java/SQLite and real Chrome."""
import base64
import json
import re
import sqlite3
import time
import unittest
from contextlib import closing
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from tests.test_gift_codes import GiftCodeTests
from tests.browser_cdp import Browser
from tests.test_prize_web import ROOT, CHROME


class AdminPanelTests(GiftCodeTests):
    def listing(self, query=''):
        return self.request('/api/admin/gift-codes'+query,cookie=self.admin)

    def test_batch_creation_pagination_activation_and_permission(self):
        self.set_balance(350000)
        before=self.listing()[1]['stats']
        code,data,_=self.create_code('',quantity=25,prefix='TESTBATCH',length=12,active=0,kind='gift',paypal=500,maxUses=1)
        self.assertEqual(code,200)
        codes=data['codes']; self.assertEqual(len(codes),25); self.assertEqual(len(set(codes)),25)
        self.assertTrue(all(re.fullmatch('TESTBATCH-[A-F0-9]{12}',c) for c in codes))
        first=self.listing('?q=TESTBATCH&page=1')[1]
        second=self.listing('?q=TESTBATCH&page=2')[1]
        self.assertEqual(first['total'],25)
        self.assertEqual(len(first['codes']),20);self.assertEqual(len(second['codes']),5)
        self.assertEqual(len({c['code'] for c in first['codes']+second['codes']}),25)
        self.assertTrue(all(not c['active'] and c['kind']=='gift' for c in first['codes']))
        self.assertEqual(first['stats']['total'],before['total']+25)
        self.assertEqual(first['stats']['active'],before['active'])
        wallet=self.snapshot()
        self.assertEqual(self.redeem(codes[0])[0],400)
        self.assertEqual(self.snapshot(),wallet)
        form=dict(action='set-active',code=codes[0],active=1)
        self.assertEqual(self.request('/api/admin/gift-codes',form,self.member)[0],403)
        self.assertEqual(self.request('/api/admin/gift-codes',cookie=self.member)[0],403)
        self.assertEqual(self.request('/api/admin/gift-codes')[0],401)
        self.assertEqual(self.request('/api/admin/gift-codes',form,self.admin)[0],200)
        self.assertEqual(self.redeem(codes[0])[0],200)
        self.assertEqual(json.loads(self.snapshot()[0])['paypalBalance'],350500)
        form['active']=0
        self.assertEqual(self.request('/api/admin/gift-codes',form,self.admin)[0],200)
        self.assertEqual(self.listing('?q='+codes[0])[1]['codes'][0]['usedCount'],1)
        self.assertEqual(self.listing('?q='+codes[0])[1]['stats']['redemptions'],before['redemptions']+1)

    def test_batch_invalid_fields_do_not_write_and_old_single_create_still_works(self):
        before=self.listing()[1]['stats']['total'];wallet=self.snapshot()
        for field,value in [('quantity',0),('quantity',101),('prefix','bad prefix'),('length',7),('active','true'),('kind','admin')]:
            self.assertEqual(self.create_code('',paypal=1,**{field:value})[0],400,(field,value))
        self.assertEqual(self.create_code('BULK_CUSTOM_INVALID',paypal=1,quantity=2)[0],400)
        self.assertEqual(self.listing()[1]['stats']['total'],before)
        self.assertEqual(self.snapshot(),wallet)
        self.assertEqual(self.create_code('SINGLE_BACKWARD_FIXTURE',paypal=1)[0],200)
        self.assertEqual(self.listing('?q=SINGLE_BACKWARD_FIXTURE')[1]['codes'][0]['kind'],'promotion')
        for query in ('?page=0','?page=abc','?page=1000001'):
            self.assertEqual(self.listing(query)[0],400)

    def test_legacy_code_schema_migration_preserves_wallet_and_code(self):
        self.assertEqual(self.create_code('LEGACY_FIXTURE',paypal=123)[0],200)
        self.assertEqual(self.create_code('LEGACY_USED_FIXTURE',paypal=1)[0],200)
        self.assertEqual(self.redeem('LEGACY_USED_FIXTURE')[0],200)
        before=self.snapshot()[0]
        self.server.terminate();self.server.wait(timeout=10)
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db:
            db.execute('ALTER TABLE gift_codes RENAME TO gift_codes_migration_fixture')
            db.execute("CREATE TABLE gift_codes (code TEXT PRIMARY KEY, diamond INTEGER NOT NULL, paypal INTEGER NOT NULL, vip_days INTEGER NOT NULL, bonus_spins INTEGER NOT NULL, max_uses INTEGER NOT NULL, used_count INTEGER NOT NULL DEFAULT 0, expires_at TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL)")
            names='code,diamond,paypal,vip_days,bonus_spins,max_uses,used_count,expires_at,created_by,created_at'
            db.execute(f'INSERT INTO gift_codes({names}) SELECT {names} FROM gift_codes_migration_fixture')
            db.execute('DROP TABLE gift_codes_migration_fixture')
            db.execute('ALTER TABLE gift_code_redemptions RENAME TO old_claims_fixture')
            db.execute('CREATE TABLE gift_code_redemptions (code TEXT NOT NULL,username TEXT NOT NULL,redeemed_at TEXT NOT NULL,PRIMARY KEY(code,username))')
            db.execute('INSERT INTO gift_code_redemptions SELECT code,username,redeemed_at FROM old_claims_fixture')
            db.execute('DROP TABLE old_claims_fixture');db.commit()
        self.start_server();self.login()
        self.assertEqual(self.snapshot()[0],before)
        row=self.listing('?q=LEGACY_FIXTURE')[1]['codes'][0]
        self.assertTrue(row['active']);self.assertEqual(row['kind'],'promotion');self.assertEqual(row['paypal'],123)
        self.assertEqual(row['maxPerUser'],1);self.assertEqual(row['cooldownSeconds'],0)
        self.assertEqual(self.redeem('LEGACY_USED_FIXTURE')[0],400)
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db:
            self.assertEqual(db.execute("SELECT received_count FROM gift_code_redemptions WHERE code='LEGACY_USED_FIXTURE'").fetchone()[0],1)
        _,_,headers=self.request('/api/login',dict(username='member_fixture',password='fixture_password'))
        type(self).member=headers['Set-Cookie']

    def test_custom_code_kind_validation_storage_and_rewards(self):
        before=self.snapshot()
        for name in ('', '   ', 'x'*61, 'Tên\nkhác', 'Tên\x00khác'):
            self.assertEqual(self.create_code('',kind='custom',kindName=name,paypal=7)[0],400)
            self.assertEqual(self.snapshot(),before)
        stats=self.listing()[1]['stats']
        self.assertEqual(self.create_code('CUSTOM_KIND_FIXTURE',kind='custom',kindName='  Quà sinh nhật  ',paypal=7)[0],200)
        row=self.listing('?q=CUSTOM_KIND_FIXTURE')[1]['codes'][0]
        self.assertEqual(row['kind'],'custom:Quà sinh nhật')
        self.assertEqual(self.listing()[1]['stats']['custom'],stats['custom']+1)
        self.assertEqual(self.redeem('CUSTOM_KIND_FIXTURE')[1]['reward']['paypal'],7)
        self.assertEqual(self.create_code('CUSTOM_MAX_NAME_FIXTURE',kind='custom',kindName='x'*60,paypal=1)[0],200)

    def claim_account(self,name):
        self.assertEqual(self.request('/api/register',dict(username=name,password='fixture_password'))[0],200)
        _,_,headers=self.request('/api/login',dict(username=name,password='fixture_password'))
        return headers['Set-Cookie']

    def test_repeat_count_concurrency_rename_and_total_capacity(self):
        cookie=self.claim_account('repeat_count_fixture')
        self.assertEqual(self.create_code('REPEAT_COUNT_FIXTURE',paypal=100,maxUses=10,maxPerUser=3)[0],200)
        self.assertEqual(self.redeem('REPEAT_COUNT_FIXTURE',cookie)[0],200)
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db:
            saved=db.execute("SELECT store_json FROM stores WHERE username='repeat_count_fixture'").fetchone()[0]
            full=json.loads(saved);full['paypalBalance']=9007199254740991
            db.execute("UPDATE stores SET store_json=? WHERE username='repeat_count_fixture'",(json.dumps(full),));db.commit()
        self.assertEqual(self.redeem('REPEAT_COUNT_FIXTURE',cookie)[0],400)
        self.assertEqual(self.listing('?q=REPEAT_COUNT_FIXTURE')[1]['codes'][0]['usedCount'],1)
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db:
            self.assertEqual(db.execute("SELECT received_count FROM gift_code_redemptions WHERE code='REPEAT_COUNT_FIXTURE'").fetchone()[0],1)
            db.execute("UPDATE stores SET store_json=? WHERE username='repeat_count_fixture'",(saved,));db.commit()
        with ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(lambda _:self.redeem('REPEAT_COUNT_FIXTURE',cookie)[0],range(6)))
        self.assertEqual(results.count(200),2)
        self.assertEqual(self.request('/api/store',cookie=cookie)[1]['store']['paypalBalance'],300)
        row=self.listing('?q=REPEAT_COUNT_FIXTURE')[1]['codes'][0]
        self.assertEqual(row['usedCount'],3);self.assertEqual(row['maxPerUser'],3)
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db:
            self.assertEqual(db.execute("SELECT received_count FROM gift_code_redemptions WHERE code='REPEAT_COUNT_FIXTURE'").fetchone()[0],3)
        self.assertEqual(self.request('/api/admin/rename-user',dict(username='repeat_count_fixture',newUsername='repeat_renamed_fixture'),self.admin)[0],200)
        _,_,headers=self.request('/api/login',dict(username='repeat_renamed_fixture',password='fixture_password'))
        self.assertEqual(self.redeem('REPEAT_COUNT_FIXTURE',headers['Set-Cookie'])[0],400)
        other=self.claim_account('repeat_total_fixture')
        self.assertEqual(self.create_code('REPEAT_TOTAL_FIXTURE',paypal=1,maxUses=2,maxPerUser=3)[0],200)
        self.assertEqual(self.redeem('REPEAT_TOTAL_FIXTURE',other)[0],200)
        status,data,_=self.redeem('REPEAT_TOTAL_FIXTURE',other)
        self.assertEqual(status,200);self.assertEqual(data['claim']['remainingGifts'],0)
        self.assertEqual(self.redeem('REPEAT_TOTAL_FIXTURE',other)[0],400)

    def test_repeat_hours_cooldown_rollback_and_concurrent_next_claim(self):
        cookie=self.claim_account('repeat_hours_fixture')
        self.assertEqual(self.create_code('REPEAT_HOURS_FIXTURE',paypal=100,maxUses=4,maxPerUser=0,cooldownHours=3)[0],200)
        status,data,_=self.redeem('REPEAT_HOURS_FIXTURE',cookie)
        self.assertEqual(status,200);self.assertEqual(data['claim']['cooldownSeconds'],10800)
        next_time=datetime.fromisoformat(data['claim']['nextEligibleAt'].replace('Z','+00:00'))
        self.assertTrue(next_time>datetime.now(timezone.utc)+timedelta(hours=2,minutes=59))
        before=self.request('/api/store',cookie=cookie)[1]['store']
        status,data,_=self.redeem('REPEAT_HOURS_FIXTURE',cookie)
        self.assertEqual(status,400);self.assertIn('thời gian chờ',data['message'])
        self.assertEqual(self.request('/api/store',cookie=cookie)[1]['store'],before)
        self.assertEqual(self.listing('?q=REPEAT_HOURS_FIXTURE')[1]['codes'][0]['usedCount'],1)
        # Only the isolated fixture clock is moved; production timestamps are untouched.
        old=(datetime.now(timezone.utc)-timedelta(hours=3,seconds=1)).isoformat().replace('+00:00','Z')
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db:
            db.execute("UPDATE gift_code_redemptions SET redeemed_at=? WHERE code='REPEAT_HOURS_FIXTURE'",(old,));db.commit()
        with ThreadPoolExecutor(max_workers=5) as pool:
            results=list(pool.map(lambda _:self.redeem('REPEAT_HOURS_FIXTURE',cookie)[0],range(5)))
        self.assertEqual(results.count(200),1)
        self.assertEqual(self.request('/api/store',cookie=cookie)[1]['store']['paypalBalance'],200)
        for _ in range(2):
            with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db:
                db.execute("UPDATE gift_code_redemptions SET redeemed_at=? WHERE code='REPEAT_HOURS_FIXTURE'",(old,));db.commit()
            self.assertEqual(self.redeem('REPEAT_HOURS_FIXTURE',cookie)[0],200)
        self.assertEqual(self.listing('?q=REPEAT_HOURS_FIXTURE')[1]['codes'][0]['usedCount'],4)
        self.assertEqual(self.redeem('REPEAT_HOURS_FIXTURE',cookie)[0],400)

    def test_repeat_policy_invalid_input_writes_nothing(self):
        before=self.snapshot();total=self.listing()[1]['stats']['total']
        for fields in [dict(maxPerUser=0),dict(maxPerUser=-1),dict(maxPerUser='1.5'),dict(maxPerUser=1000001),dict(maxPerUser=0,cooldownHours=8761),dict(maxPerUser=0,cooldownHours='0.5'),dict(maxPerUser=2,cooldownHours=1)]:
            self.assertEqual(self.create_code('',paypal=1,**fields)[0],400)
            self.assertEqual(self.snapshot(),before)
            self.assertEqual(self.listing()[1]['stats']['total'],total)

    def test_repeat_restart_preserves_count_and_cooldown(self):
        cookie=self.claim_account('repeat_persist_fixture')
        self.assertEqual(self.create_code('REPEAT_PERSIST_COUNT',paypal=1,maxUses=10,maxPerUser=2)[0],200)
        self.assertEqual(self.create_code('REPEAT_PERSIST_HOURS',paypal=1,maxUses=10,maxPerUser=0,cooldownHours=1)[0],200)
        for code in ('REPEAT_PERSIST_COUNT','REPEAT_PERSIST_HOURS'):
            self.assertEqual(self.redeem(code,cookie)[0],200)
        self.server.terminate();self.server.wait(timeout=10);self.start_server();self.login()
        _,_,headers=self.request('/api/login',dict(username='member_fixture',password='fixture_password'));type(self).member=headers['Set-Cookie']
        _,_,headers=self.request('/api/login',dict(username='repeat_persist_fixture',password='fixture_password'));cookie=headers['Set-Cookie']
        self.assertEqual(self.redeem('REPEAT_PERSIST_COUNT',cookie)[0],200)
        self.assertEqual(self.redeem('REPEAT_PERSIST_COUNT',cookie)[0],400)
        self.assertEqual(self.redeem('REPEAT_PERSIST_HOURS',cookie)[0],400)
        self.assertEqual(self.listing('?q=REPEAT_PERSIST_COUNT')[1]['codes'][0]['usedCount'],2)
        self.assertEqual(self.listing('?q=REPEAT_PERSIST_HOURS')[1]['codes'][0]['usedCount'],1)

    @unittest.skipUnless(Path(CHROME).exists(),'Chrome required')
    def test_shared_numeric_inputs_live_typing_and_exact_code_save(self):
        browser = Browser(CHROME, self.work / f'numeric-ui-profile-{time.time_ns()}')
        def wait(expression):
            for _ in range(200):
                if browser.value(expression): return
                time.sleep(.05)
            raise AssertionError('Timeout: ' + expression)
        def run(expression):
            result = browser.call('Runtime.evaluate', dict(expression=expression, awaitPromise=True, returnByValue=True), page=True)
            self.assertNotIn('exceptionDetails', result, result)
        def type_value(field, text, expected):
            node = f'document.getElementById({json.dumps(field)})'
            browser.value(node + '.focus();' + node + '.select()')
            browser.call('Input.insertText', dict(text=text), page=True)
            self.assertEqual(browser.value(node + '.value'), expected, field)
            self.assertEqual(browser.value(node + '.selectionStart'), len(expected), field)
        try:
            browser.call('Page.enable', page=True); browser.call('Network.enable', page=True)
            browser.call('Network.setCookie', dict(name='LOTTO_AUTH', value=self.admin.split(';')[0].split('=',1)[1], url=self.url), page=True)
            browser.call('Page.navigate', dict(url=self.url + '/admin'), page=True)
            wait("!!window.adminPanel && !document.getElementById('adminPanelSection').hidden && document.getElementById('adminTotalCodes').textContent!=='—'")
            # Default zero is selected on focus, then replaced by the first digit.
            for field in ('settingsCodePaypal', 'settingsCodeDiamond', 'settingsCodeVipDays', 'settingsCodeSpins'):
                node = f'document.getElementById({json.dumps(field)})'
                browser.value(node + '.focus()')
                self.assertEqual(browser.value(node + '.selectionStart'), 0)
                self.assertEqual(browser.value(node + '.selectionEnd'), 1)
                browser.call('Input.insertText', dict(text='1'), page=True)
                self.assertEqual(browser.value(node + '.value'), '1')
            # Clearing any reward immediately restores a selected zero; typing replaces it.
            for field in ('settingsCodePaypal', 'settingsCodeDiamond', 'settingsCodeVipDays', 'settingsCodeSpins'):
                node = f'document.getElementById({json.dumps(field)})'
                for key, code in [('Backspace',8),('Delete',46)]:
                    browser.value(node + '.focus();' + node + '.select()')
                    for event in ('keyDown','keyUp'):
                        browser.call('Input.dispatchKeyEvent',dict(type=event,key=key,code=key,windowsVirtualKeyCode=code),page=True)
                    self.assertEqual(browser.value(node + '.value'),'0',field)
                    self.assertEqual(browser.value(node + '.selectionStart'),0,field)
                    self.assertEqual(browser.value(node + '.selectionEnd'),1,field)
                    browser.call('Input.insertText',dict(text='7'),page=True)
                    self.assertEqual(browser.value(node + '.value'),'7',field)
                # Deleting the final digit also restores zero without leaving the field.
                browser.value(node + '.setSelectionRange(1,1)')
                for event in ('keyDown','keyUp'):
                    browser.call('Input.dispatchKeyEvent',dict(type=event,key='Backspace',code='Backspace',windowsVirtualKeyCode=8),page=True)
                self.assertEqual(browser.value(node + '.value'),'0',field)
                browser.call('Input.imeSetComposition',dict(text='07',selectionStart=2,selectionEnd=2),page=True)
                self.assertEqual(browser.value(node + '.value'),'7',field)
                browser.call('Input.insertText',dict(text='07'),page=True)
                self.assertEqual(browser.value(node + '.value'),'7',field)
            # Format during every real IME update, before committing or leaving the field.
            # Rewriting the input must not duplicate a continuing composition or its commit.
            for field in ('settingsCodePaypal', 'settingsCodeDiamond', 'settingsCodeVipDays', 'settingsCodeSpins'):
                node = f'document.getElementById({json.dumps(field)})'
                browser.value(node + '.focus();' + node + '.select()')
                for raw, expected in [('01','1'),('010','10'),('0100','100'),('01000','1.000')]:
                    browser.call('Input.imeSetComposition', dict(text=raw, selectionStart=len(raw), selectionEnd=len(raw)), page=True)
                    self.assertEqual(browser.value(node + '.value'), expected, (field,raw))
                    self.assertEqual(browser.value('document.activeElement.id'),field)
                    self.assertEqual(browser.value(node + '.selectionStart'),len(expected))
                browser.call('Input.insertText', dict(text='01000'), page=True)
                self.assertEqual(browser.value(node + '.value'), '1.000', field)
                browser.value(node + '.select()')
                browser.call('Input.imeSetComposition', dict(text='010000', selectionStart=6, selectionEnd=6), page=True)
                self.assertEqual(browser.value(node + '.value'), '10.000', field)
                browser.call('Input.insertText', dict(text='010000'), page=True)
                self.assertEqual(browser.value(node + '.value'), '10.000', field)
                self.assertEqual(browser.value(node + '.selectionStart'), 6, field)
            node = "document.getElementById('settingsCodeDiamond')"
            browser.value(node + '.focus();' + node + '.select()')
            browser.call('Input.imeSetComposition',dict(text='05',selectionStart=2,selectionEnd=2),page=True)
            self.assertEqual(browser.value(node + '.value'),'5')
            # A real next key is a new digit, even if equal to the composing digit.
            browser.call('Input.dispatchKeyEvent',dict(type='keyDown',key='5',code='Digit5',text='5',windowsVirtualKeyCode=53),page=True)
            browser.call('Input.dispatchKeyEvent',dict(type='keyUp',key='5',code='Digit5',windowsVirtualKeyCode=53),page=True)
            self.assertEqual(browser.value(node + '.value'),'55')
            browser.call('Input.imeSetComposition',dict(text='5',selectionStart=1,selectionEnd=1),page=True)
            self.assertEqual(browser.value(node + '.value'),'555')
            browser.call('Input.insertText',dict(text='5'),page=True)
            self.assertEqual(browser.value(node + '.value'),'555')
            type_value('settingsCodeDiamond','12.345','12.345')
            browser.value(node + '.setSelectionRange(0,2)')
            browser.call('Input.imeSetComposition',dict(text='09',selectionStart=2,selectionEnd=2),page=True)
            self.assertEqual(browser.value(node + '.value'),'9.345')
            browser.call('Input.insertText',dict(text='09'),page=True)
            self.assertEqual(browser.value(node + '.value'),'9.345')
            # Change/focusout also format valid values inserted by autofill or a picker.
            browser.value("document.getElementById('settingsCodePaypal').value='0100';document.getElementById('settingsCodePaypal').dispatchEvent(new Event('change',{bubbles:true}))")
            self.assertEqual(browser.value("document.getElementById('settingsCodePaypal').value"),'100')
            browser.value("document.getElementById('settingsCodePaypal').value='010000';document.getElementById('settingsCodePaypal').focus();document.getElementById('settingsCodeDiamond').focus()")
            self.assertEqual(browser.value("document.getElementById('settingsCodePaypal').value"),'10.000')
            browser.value("document.getElementById('adminClaimLimit').value='repeat';document.getElementById('adminClaimLimit').dispatchEvent(new Event('change'))")
            for field, text, expected in [('settingsCodePaypal','01000','1.000'), ('settingsCodeDiamond','010000','10.000'), ('settingsCodeVipDays','010','10'), ('settingsCodeSpins','0100','100'), ('settingsCodeMaxUses','0001000','1.000'), ('adminClaimValue','0001000','1.000')]:
                type_value(field, text, expected)
            # Every keystroke groups the digits while retaining the caret at the end.
            node = "document.getElementById('settingsCodePaypal')"
            browser.value(node + '.focus();' + node + '.select()')
            for length in range(1,11):
                browser.call('Input.insertText', dict(text='9'), page=True)
                expected = f'{int("9"*length):,}'.replace(',','.')
                self.assertEqual(browser.value(node + '.value'), expected)
                self.assertEqual(browser.value(node + '.selectionStart'), len(expected))
            type_value('settingsNewCode', 'NUMERIC_RULES_FIXTURE', 'NUMERIC_RULES_FIXTURE')
            submit = "document.getElementById('settingsCreateCodeForm').onsubmit({preventDefault(){},currentTarget:document.getElementById('settingsCreateCodeForm')})"
            before = self.listing()[1]['stats']['total']
            run(submit)
            self.assertIn('60', browser.value("document.getElementById('settingsCreateCodeMessage').textContent"))
            self.assertEqual(self.listing()[1]['stats']['total'], before)
            type_value('settingsCodeSpins','00010','10')
            type_value('settingsCodeVipDays','01000','1.000')
            type_value('settingsCodePaypal','999.999.9999','999.999.9999')
            browser.value("document.getElementById('settingsCodeDiamond').focus()")
            self.assertEqual(browser.value("document.getElementById('settingsCodePaypal').value"),'999.999.9999')
            run(submit)
            self.assertEqual(self.listing()[1]['stats']['total'], before)
            type_value('settingsCodePaypal','0001000','1.000')
            run(submit)
            self.assertEqual(browser.value("document.getElementById('settingsNewCode').value"), '')
            row = self.listing('?q=NUMERIC_RULES_FIXTURE')[1]['codes'][0]
            self.assertEqual((row['paypal'], row['diamond'], row['vipDays'], row['bonusSpins'], row['maxUses'], row['maxPerUser']), (1000,10000,1000,10,1000,1000))
            browser.value("document.getElementById('adminClaimLimit').value='repeat';document.getElementById('adminClaimLimit').dispatchEvent(new Event('change'));document.getElementById('adminClaimMode').value='hours';document.getElementById('adminClaimMode').dispatchEvent(new Event('change'));document.getElementById('settingsCodePaypal').value='1.000'")
            type_value('adminClaimValue','08760','8.760')
            type_value('settingsNewCode','NUMERIC_HOURS_FIXTURE','NUMERIC_HOURS_FIXTURE')
            run(submit)
            row = self.listing('?q=NUMERIC_HOURS_FIXTURE')[1]['codes'][0]
            self.assertEqual(row['cooldownSeconds'],8760*3600)
        finally:
            browser.close()

    def test_created_notice_two_seconds_defaults_errors_and_cancel(self):
        browser = Browser(CHROME, self.work / 'created-notice-profile')
        def wait(expression):
            for _ in range(200):
                if browser.value(expression):
                    return
                time.sleep(.025)
            self.fail('Timeout: ' + expression)
        submit = "document.getElementById('settingsCreateCodeForm').onsubmit({preventDefault(){},currentTarget:document.getElementById('settingsCreateCodeForm')})"
        def start_submit(await_promise=False):
            result = browser.call('Runtime.evaluate', dict(expression=submit, awaitPromise=await_promise, returnByValue=True), page=True)
            self.assertNotIn('exceptionDetails', result, result)
        try:
            browser.call('Network.enable', page=True)
            browser.call('Network.setCookie', dict(name='LOTTO_AUTH', value=self.admin.split(';')[0].split('=', 1)[1], url=self.url), page=True)
            browser.call('Emulation.setDeviceMetricsOverride', dict(width=1440, height=900, deviceScaleFactor=1, mobile=False), page=True)
            browser.call('Page.navigate', dict(url=self.url + '/admin'), page=True)
            wait("!!window.adminPanel && document.getElementById('adminTotalCodes').textContent!=='—' && getComputedStyle(document.getElementById('pageLoader')).opacity==='0'")
            local = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime('%Y-%m-%dT%H:%M')
            expiry = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime('%Y-%m-%dT%H:%M')
            browser.value("document.getElementById('adminCodeKind').value='custom';document.getElementById('adminCodeKind').dispatchEvent(new Event('change'));document.getElementById('adminCustomKindName').value='Quà thử';document.getElementById('settingsNewCode').value='TWO_SECOND_FIXTURE';document.getElementById('settingsCodeMaxUses').value='25';document.getElementById('adminCodeLength').value='12';document.querySelector('[name=adminCodeActive][value=\"0\"]').click();document.getElementById('adminClaimLimit').value='repeat';document.getElementById('adminClaimLimit').dispatchEvent(new Event('change'));document.getElementById('adminClaimMode').value='hours';document.getElementById('adminClaimMode').dispatchEvent(new Event('change'));document.getElementById('adminClaimValue').value='3';document.getElementById('settingsCodePaypal').value='1.000';document.getElementById('settingsCodeDiamond').value='50';document.getElementById('settingsCodeVipDays').value='5';document.getElementById('settingsCodeSpins').value='3';document.getElementById('adminCodeSearch').value='old search'")
            browser.value("document.getElementById('settingsCodeActivation').value=" + json.dumps(local) + ";document.getElementById('settingsCodeExpiry').value=" + json.dumps(expiry))
            browser.value("window.createdNoticeTimes={};new MutationObserver(()=>{const e=document.getElementById('adminCodeSuccess');if(!e.hidden)createdNoticeTimes.shown=performance.now();else if(createdNoticeTimes.shown)createdNoticeTimes.hidden=performance.now()}).observe(document.getElementById('adminCodeSuccess'),{attributes:true,attributeFilter:['hidden']})")
            before = self.listing()[1]['total']
            start_submit()
            wait("!document.getElementById('adminCodeSuccess').hidden")
            self.assertEqual(browser.value("document.querySelector('#adminCodeSuccess strong').textContent"), 'Đã Tạo')
            self.assertTrue(browser.value("document.getElementById('adminPanelSection').inert && document.querySelector('#settingsCreateCodeForm button[type=submit]').disabled && document.getElementById('settingsCreateCodeForm').getAttribute('aria-busy')==='true'"))
            geometry = browser.value("(()=>{const r=document.querySelector('.admin-code-success-card').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,width:document.documentElement.clientWidth,height:document.documentElement.clientHeight}})()")
            self.assertAlmostEqual(geometry['x'], geometry['width'] / 2, delta=.1)
            self.assertAlmostEqual(geometry['y'], geometry['height'] / 2, delta=.1)
            browser.value("document.querySelector('#settingsCreateCodeForm button[type=submit]').click()")
            self.assertEqual(self.listing()[1]['total'], before + 1)
            shot = browser.call('Page.captureScreenshot', dict(format='png'), page=True)
            (ROOT / 'Bin/session_1_latest/code_created_notice_dark_1440.png').write_bytes(base64.b64decode(shot['data']))
            time.sleep(.4)
            self.assertFalse(browser.value("document.getElementById('adminCodeSuccess').hidden"))
            wait("document.getElementById('adminCodeSuccess').hidden && !document.querySelector('#settingsCreateCodeForm button[type=submit]').disabled")
            times = browser.value('createdNoticeTimes')
            elapsed = times['hidden'] - times['shown']
            self.assertGreaterEqual(elapsed, 1950)
            self.assertLess(elapsed, 3000)
            defaults = browser.value("(()=>{const ids=['settingsNewCode','adminCodeKind','adminCustomKindName','settingsCodeMaxUses','adminCodeLength','settingsCodeExpiry','settingsCodeActivation','adminClaimLimit','adminClaimMode','adminClaimValue','settingsCodePaypal','settingsCodeDiamond','settingsCodeVipDays','settingsCodeSpins','adminCodeSearch'];return Object.fromEntries(ids.map(id=>[id,document.getElementById(id).value]))})()")
            self.assertEqual(defaults, dict(settingsNewCode='', adminCodeKind='promotion', adminCustomKindName='', settingsCodeMaxUses='10', adminCodeLength='8', settingsCodeExpiry='', settingsCodeActivation='', adminClaimLimit='once', adminClaimMode='count', adminClaimValue='1', settingsCodePaypal='0', settingsCodeDiamond='0', settingsCodeVipDays='0', settingsCodeSpins='0', adminCodeSearch=''))
            self.assertTrue(browser.value("document.querySelector('[name=adminCodeActive][value=\"1\"]').checked && document.getElementById('adminActivationField').hidden && document.getElementById('settingsCodeActivation').disabled && document.getElementById('adminCustomKindField').hidden && !document.getElementById('adminCustomKindName').required && document.getElementById('adminClaimMode').disabled && document.getElementById('adminClaimValue').disabled && !document.getElementById('adminPanelSection').inert && !document.getElementById('settingsCreateCodeForm').hasAttribute('aria-busy') && !document.querySelector('.admin-code-basics').classList.contains('has-activation') && !document.getElementById('adminCreatePane').hidden"))
            wait("document.getElementById('adminTotalCodes').textContent===" + json.dumps(str(before + 1)))
            self.assertEqual(browser.value("document.getElementById('adminTotalCodes').textContent"), str(before + 1))
            row = self.listing('?q=TWO_SECOND_FIXTURE')[1]['codes'][0]
            self.assertEqual((row['kind'], row['maxUses'], row['paypal'], row['diamond'], row['vipDays'], row['bonusSpins'], row['cooldownSeconds']), ('custom:Quà thử', 25, 1000, 50, 5, 3, 10800))
            # A failed creation preserves the draft and never shows a success notice.
            browser.value("document.getElementById('settingsNewCode').value='TWO_SECOND_FIXTURE';document.getElementById('settingsCodePaypal').value='999'")
            start_submit(True)
            self.assertTrue(browser.value("document.getElementById('settingsCreateCodeMessage').classList.contains('is-error') && document.getElementById('settingsNewCode').value==='TWO_SECOND_FIXTURE' && document.getElementById('settingsCodePaypal').value==='999' && document.getElementById('adminCodeSuccess').hidden && !document.getElementById('adminPanelSection').inert"))
            # Cancel/reset must not leave a timer that clears a later draft.
            browser.call('Emulation.setDeviceMetricsOverride', dict(width=390, height=844, deviceScaleFactor=1, mobile=True), page=True)
            browser.value("document.body.classList.add('light-theme');document.getElementById('settingsNewCode').value='CANCEL_NOTICE_FIXTURE'")
            start_submit()
            wait("!document.getElementById('adminCodeSuccess').hidden")
            geometry = browser.value("(()=>{const r=document.querySelector('.admin-code-success-card').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,width:document.documentElement.clientWidth,height:document.documentElement.clientHeight}})()")
            self.assertAlmostEqual(geometry['x'], geometry['width'] / 2, delta=.1)
            self.assertAlmostEqual(geometry['y'], geometry['height'] / 2, delta=.1)
            shot = browser.call('Page.captureScreenshot', dict(format='png'), page=True)
            (ROOT / 'Bin/session_1_latest/code_created_notice_light_390.png').write_bytes(base64.b64decode(shot['data']))
            browser.value("window.adminPanel.reset();document.getElementById('settingsNewCode').value='NEXT_DRAFT'")
            time.sleep(2.2)
            self.assertTrue(browser.value("document.getElementById('adminCodeSuccess').hidden && !document.getElementById('adminPanelSection').inert && document.getElementById('settingsNewCode').value==='NEXT_DRAFT' && !document.querySelector('#settingsCreateCodeForm button[type=submit]').disabled"))
            (ROOT / 'Bin/session_1_latest/code_created_notice_verification.json').write_text(json.dumps(dict(durationMs=elapsed,defaults=defaults,centeredDesktopAndMobile=True,failedCreationKeepsDraft=True,cancelPreventsLateReset=True), ensure_ascii=False, indent=2), encoding='utf-8')
        finally:
            browser.close()

    def test_admin_page_navigation_real_batch_and_responsive_design(self):
        browser=Browser(CHROME,self.work/f'admin-ui-profile-{time.time_ns()}')
        images=ROOT/'Bin/session_1_latest/admin_panel_images';images.mkdir(exist_ok=True)
        def wait(expression):
            for _ in range(200):
                if browser.value(expression): return
                time.sleep(.05)
            raise AssertionError('Timeout: '+expression)
        def run(expression):
            value=browser.call('Runtime.evaluate',dict(expression=expression,awaitPromise=True,returnByValue=True),page=True)
            self.assertNotIn('exceptionDetails',value,value)
        try:
            browser.call('Page.enable',page=True);browser.call('Network.enable',page=True)
            browser.call('Network.setCookie',dict(name='LOTTO_AUTH',value=self.admin.split(';')[0].split('=',1)[1],url=self.url),page=True)
            browser.call('Page.navigate',dict(url=self.url+'/'),page=True)
            wait("!!window.adminPanel && document.getElementById('openAccountBtn').style.display==='flex'")
            browser.value("document.getElementById('settingsBtn').click()")
            self.assertTrue(browser.value("document.getElementById('settingsAdminBtn').getBoundingClientRect().top<document.getElementById('settingsCodeBtn').getBoundingClientRect().top"))
            browser.value("document.getElementById('settingsAdminBtn').click()")
            wait("location.pathname==='/admin' && document.getElementById('adminTotalCodes').textContent!=='—'")
            self.assertFalse(browser.value("document.getElementById('adminPanelSection').hidden"))
            self.assertTrue(browser.value("document.getElementById('mainContentGrid').hidden"))
            # Defaults match the reference; rewards must be explicitly chosen.
            self.assertEqual(browser.value("document.getElementById('settingsNewCode').value"),'')
            self.assertTrue(browser.value("document.getElementById('settingsNewCode').matches(':placeholder-shown')"))
            self.assertEqual(browser.value("document.getElementById('settingsNewCode').placeholder"),'Ví dụ: ADMIN-8K2JH9XQ')
            browser.value("document.getElementById('settingsNewCode').value='TEST';document.getElementById('settingsNewCode').dispatchEvent(new Event('input',{bubbles:true}))")
            self.assertFalse(browser.value("document.getElementById('settingsNewCode').matches(':placeholder-shown')"))
            browser.value("document.getElementById('settingsNewCode').value=''")
            browser.value("document.getElementById('settingsNewCode').value='ABCDEFGHIJKLMNOPQRST';document.getElementById('adminCodeLength').value='16';document.getElementById('adminQuickCodeBtn').click()")
            generated=browser.value("document.getElementById('settingsNewCode').value")
            self.assertRegex(generated,r'^ABCDEFGHIJKLMNOPQRST-[A-Z0-9]{16}$')
            self.assertTrue(browser.value("document.activeElement.id==='settingsNewCode' && document.getElementById('settingsNewCode').selectionStart===0 && document.getElementById('settingsNewCode').selectionEnd===37"))
            browser.value("document.getElementById('adminQuickCodeBtn').click()")
            generated_again=browser.value("document.getElementById('settingsNewCode').value")
            self.assertRegex(generated_again,r'^ABCDEFGHIJKLMNOPQRST-[A-Z0-9]{16}$')
            self.assertNotEqual(generated,generated_again)
            browser.value("document.getElementById('settingsNewCode').value='';document.getElementById('adminCodeLength').value='8'")
            self.assertEqual(browser.value("document.getElementById('settingsCodeMaxUses').value"),'10')
            self.assertTrue(browser.value("document.getElementById('adminClaimValue').disabled && document.getElementById('adminClaimValue').value==='1'"))
            browser.value("document.getElementById('adminClaimLimit').value='repeat';document.getElementById('adminClaimLimit').dispatchEvent(new Event('change'))")
            self.assertTrue(browser.value("!document.getElementById('adminClaimValue').disabled && document.getElementById('adminClaimValue').value==='2'"))
            browser.value("document.getElementById('adminClaimMode').value='hours';document.getElementById('adminClaimMode').dispatchEvent(new Event('change'));document.getElementById('adminClaimValue').value='3'")
            self.assertEqual(browser.value("document.getElementById('adminCodeKind').lastElementChild.textContent"),'Khác…')
            self.assertTrue(browser.value("document.getElementById('adminCustomKindField').hidden"))
            browser.value("document.getElementById('adminCodeKind').value='custom';document.getElementById('adminCodeKind').dispatchEvent(new Event('change'))")
            self.assertTrue(browser.value("document.getElementById('adminCustomKindName').required && document.activeElement.id==='adminCustomKindName'"))
            run("document.getElementById('settingsCreateCodeForm').onsubmit({preventDefault(){},currentTarget:document.getElementById('settingsCreateCodeForm')})")
            self.assertEqual(browser.value("document.getElementById('settingsCreateCodeMessage').textContent"),'Nhập tên loại Code.')
            browser.value("document.getElementById('adminCodeKind').value='gift';document.getElementById('adminCodeKind').dispatchEvent(new Event('change'))")
            self.assertTrue(browser.value("document.getElementById('adminCustomKindField').hidden && !document.getElementById('adminCustomKindName').required"))
            browser.value("document.getElementById('adminCodeKind').value='custom';document.getElementById('adminCodeKind').dispatchEvent(new Event('change'));document.getElementById('adminCustomKindName').value='Sinh nhật <b>VIP</b>'")
            for theme in ('dark','light'):
                browser.value(f"document.body.classList.toggle('light-theme',{str(theme=='light').lower()})")
                for width in (320,390,768,1440):
                    browser.call('Emulation.setDeviceMetricsOverride',dict(width=width,height=1100,deviceScaleFactor=1,mobile=width<500),page=True)
                    for tab in ('adminCreateTab','adminListTab'):
                        browser.value(f"document.getElementById('{tab}').click()")
                        self.assertTrue(browser.value("(()=>{const p=document.getElementById('adminPanelSection'),r=p.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth+1&&p.scrollWidth<=p.clientWidth+1&&document.documentElement.scrollWidth<=innerWidth+1})()"),(theme,width,tab))
                        rect=browser.value("(()=>{const r=document.getElementById('adminPanelSection').getBoundingClientRect();return {x:r.x,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()")
                        shot=browser.call('Page.captureScreenshot',dict(format='png',clip=rect,captureBeyondViewport=True),page=True)
                        (images/f'{theme}_{width}_{tab}.png').write_bytes(base64.b64decode(shot['data']))
            browser.value("document.getElementById('adminCreateTab').click();document.getElementById('settingsNewCode').value='UIBATCH';document.getElementById('settingsCodeMaxUses').value='1000';document.getElementById('settingsCodePaypal').value='100';document.querySelector('[name=adminCodeActive][value=\"0\"]').checked=true;document.getElementById('adminQuickCodeBtn').click()")
            self.assertEqual(browser.value("document.getElementById('settingsCodeMaxUses').value"),'1000')
            visible_code=browser.value("document.getElementById('settingsNewCode').value")
            run("document.getElementById('settingsCreateCodeForm').onsubmit({preventDefault(){},currentTarget:document.getElementById('settingsCreateCodeForm')})")
            codes=[visible_code]
            self.assertEqual(browser.value("document.getElementById('settingsNewCode').value"), '')
            self.assertEqual(len(codes),1);self.assertTrue(all(c.startswith('UIBATCH-') for c in codes))
            self.assertEqual(codes[0],visible_code)
            self.assertTrue(browser.value("!document.getElementById('adminCreatedCodes') && !document.getElementById('adminCreatedCodesText') && !document.getElementById('adminCopyCreatedBtn')"))
            self.assertEqual(self.listing('?q='+codes[0])[1]['codes'][0]['code'],visible_code)
            self.assertEqual(self.listing('?q='+codes[0])[1]['codes'][0]['maxUses'],1000)
            self.assertEqual(self.listing('?q='+codes[0])[1]['codes'][0]['maxPerUser'],0)
            self.assertEqual(self.listing('?q='+codes[0])[1]['codes'][0]['cooldownSeconds'],10800)
            self.assertTrue(browser.value("document.getElementById('adminCodeSuccess').hidden && document.querySelector('[name=adminCodeActive][value=\"1\"]').checked"))
            browser.value("document.getElementById('adminListTab').click();document.getElementById('adminCodeSearch').value='UIBATCH';document.getElementById('adminCodeSearchForm').requestSubmit()")
            wait("document.querySelectorAll('#adminCodeRows tr').length===1 && document.getElementById('adminCodeRows').textContent.includes('UIBATCH')")
            self.assertEqual(browser.value("document.querySelector('#adminCodeRows .admin-code-kind').textContent"),'Sinh nhật <b>VIP</b>')
            self.assertFalse(browser.value("!!document.querySelector('#adminCodeRows .admin-code-kind b')"))
            self.assertEqual(browser.value("[...document.querySelectorAll('.admin-code-table th')].map(e=>e.textContent)"),['Code','Loại Code','Phần quà','Giới Hạn','Đã dùng','Hạn code','Trạng thái','Thao tác'])
            self.assertEqual(browser.value("document.querySelector('#adminCodeRows tr').cells.length"),8)
            self.assertIn('3 giờ',browser.value("document.querySelector('#adminCodeRows .admin-code-limit').textContent"))
            self.assertFalse(browser.value("!!document.querySelector('#adminCodeRows td:first-child small')"))
            rowcode=browser.value("document.querySelector('#adminCodeRows .admin-code-name').textContent")
            self.assertTrue(browser.value("!!document.querySelector('#adminCodeRows td:first-child .admin-code-copy svg') && document.querySelectorAll('#adminCodeRows [data-admin-copy]').length===1 && !document.querySelector('#adminCodeRows .admin-row-actions [data-admin-copy]')"))
            browser.value("Object.defineProperty(navigator.clipboard,'writeText',{configurable:true,value:text=>{window.copiedCodeFixture=text;return Promise.resolve()}});document.querySelector('#adminCodeRows .admin-code-copy svg').dispatchEvent(new MouseEvent('click',{bubbles:true}))")
            wait("document.getElementById('adminPageMessage').textContent==='Đã sao chép code.'")
            self.assertEqual(browser.value('window.copiedCodeFixture'),rowcode)
            browser.value("Object.defineProperty(navigator.clipboard,'writeText',{configurable:true,value:()=>Promise.reject(new Error('fixture clipboard denied'))});document.querySelector('#adminCodeRows [data-admin-copy]').click()")
            wait("document.activeElement.id==='settingsNewCode' && !document.getElementById('adminCreatePane').hidden")
            self.assertEqual(browser.value("document.getElementById('settingsNewCode').value"),rowcode)
            self.assertEqual(browser.value("[document.getElementById('settingsNewCode').selectionStart,document.getElementById('settingsNewCode').selectionEnd]"),[0,len(rowcode)])
            self.assertIn('Ctrl + C',browser.value("document.getElementById('adminPageMessage').textContent"))
            browser.value("document.getElementById('adminListTab').click()")
            wait("!!document.querySelector('#adminCodeRows [data-admin-toggle]')")
            browser.value("document.querySelector('#adminCodeRows [data-admin-toggle]').click()")
            wait("document.getElementById('adminPageMessage').textContent.includes('Đã kích hoạt') && document.getElementById('adminCodeRows').textContent.includes('Đang hoạt động')")
            self.assertTrue(self.listing('?q='+rowcode)[1]['codes'][0]['active'])
            browser.value("document.getElementById('adminCreateTab').click();document.getElementById('adminClaimLimit').value='repeat';document.getElementById('adminClaimLimit').dispatchEvent(new Event('change'));document.getElementById('settingsCodePaypal').value='100';document.getElementById('adminClaimMode').value='count';document.getElementById('adminClaimMode').dispatchEvent(new Event('change'));document.getElementById('adminClaimValue').value='4';document.getElementById('settingsNewCode').value='UICOUNT';document.getElementById('adminQuickCodeBtn').click()")
            count_code=browser.value("document.getElementById('settingsNewCode').value")
            run("document.getElementById('settingsCreateCodeForm').onsubmit({preventDefault(){},currentTarget:document.getElementById('settingsCreateCodeForm')})")
            count_row=self.listing('?q='+count_code)[1]['codes'][0]
            self.assertEqual(count_row['maxPerUser'],4);self.assertEqual(count_row['cooldownSeconds'],0)
            browser.value("document.getElementById('adminClaimLimit').value='once';document.getElementById('adminClaimLimit').dispatchEvent(new Event('change'))")
            self.assertTrue(browser.value("document.getElementById('adminClaimValue').disabled && document.getElementById('adminClaimValue').value==='1'"))
            for view,title in [('overview','Tổng quan'),('users','Người dùng'),('stats','Thống kê'),('settings','Cài đặt')]:
                browser.value(f"document.querySelector('.admin-nav [data-admin-view={view}]').click()")
                self.assertEqual(browser.value("document.getElementById('adminPageTitle').textContent"),title)
                if view == 'users':
                    wait("document.getElementById('adminUserRows').textContent.includes('member_fixture')")
            browser.value("document.getElementById('adminBackBtn').click()")
            self.assertEqual(browser.value('location.pathname'),'/')
            browser.value("navigateToAppPage('admin')")
            browser.call('Page.reload',page=True)
            wait("!!window.adminPanel && document.getElementById('adminTotalCodes').textContent!=='—' && location.pathname==='/admin'")
            # A real member session cannot enter the admin page or view its code data.
            browser.call('Network.setCookie',dict(name='LOTTO_AUTH',value=self.member.split(';')[0].split('=',1)[1],url=self.url),page=True)
            browser.call('Page.navigate',dict(url=self.url+'/admin'),page=True)
            wait("document.getElementById('appShell').style.display==='block' && location.pathname==='/'")
            self.assertTrue(browser.value("document.getElementById('settingsAdminBtn').hidden"))
            self.assertTrue(browser.value("document.getElementById('adminPanelSection').hidden"))
        finally: browser.close()


if __name__=='__main__': unittest.main()
