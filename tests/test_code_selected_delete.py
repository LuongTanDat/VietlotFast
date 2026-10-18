"""Selected deletion, history preservation and admin selection in isolated fixtures."""
import base64
import json
import sqlite3
import time
from contextlib import closing
from tests.test_admin_panel import AdminPanelTests
from tests.browser_cdp import Browser
from tests.test_prize_web import ROOT, CHROME


class SelectedDeleteTests(AdminPanelTests):
    def delete_codes(self, codes, cookie=None):
        return self.request('/api/admin/gift-codes', dict(action='delete', codes=codes), cookie or self.admin)

    def test_atomic_delete_permissions_history_and_restart(self):
        self.set_balance(350000)
        for name in ['DELETE_USED', 'DELETE_UNUSED', 'DELETE_KEEP']:
            self.assertEqual(self.create_code(name, paypal=100, maxUses=10)[0], 200)
        self.assertEqual(self.redeem('DELETE_USED')[0], 200)
        stats = self.listing()[1]['stats']
        wallet = self.snapshot()[0]
        for cookie, expected in [(self.member, 403), ('', 401)]:
            self.assertEqual(self.request('/api/admin/gift-codes', dict(action='delete', codes='DELETE_USED'), cookie)[0], expected)
        for value in ['', 'DELETE_UNUSED\nNO_SUCH_DELETE', 'DELETE_UNUSED\n', 'bad code', '\n'.join(['DELETE_UNUSED'] * 21)]:
            self.assertEqual(self.delete_codes(value)[0], 400, value)
            self.assertEqual(self.listing()[1]['stats'], stats)
            self.assertEqual(self.snapshot()[0], wallet)
        status, data, _ = self.delete_codes('DELETE_USED\nDELETE_UNUSED')
        self.assertEqual(status, 200); self.assertEqual(data['deletedCount'], 2)
        self.assertEqual(self.listing('?q=DELETE_USED')[1]['total'], 0)
        self.assertEqual(self.listing('?q=DELETE_UNUSED')[1]['total'], 0)
        after = self.listing()[1]['stats']
        self.assertEqual(after['total'], stats['total'] - 2)
        self.assertEqual(after['redemptions'], stats['redemptions'])
        self.assertEqual(self.snapshot()[0], wallet)
        self.assertEqual(self.listing('?q=DELETE_KEEP')[1]['total'], 1)
        self.assertEqual(self.redeem('DELETE_USED')[0], 400)
        self.assertEqual(self.request('/api/admin/gift-codes', dict(action='set-active', code='DELETE_USED', active=1), self.admin)[0], 400)
        self.assertEqual(self.create_code('DELETE_USED', paypal=1)[0], 400)
        with closing(sqlite3.connect(self.work / 'runtime/lotto_web.db')) as db:
            self.assertEqual(db.execute("SELECT received_count FROM gift_code_redemptions WHERE code='DELETE_USED'").fetchone()[0], 1)
            detail = db.execute("SELECT details_json FROM account_audit WHERE action='delete_gift_codes' ORDER BY created_at DESC LIMIT 1").fetchone()[0]
            self.assertEqual(json.loads(detail)['codes'], ['DELETE_USED', 'DELETE_UNUSED'])
        self.server.terminate(); self.server.wait(timeout=10); self.start_server(); self.login()
        self.assertEqual(self.listing('?q=DELETE_USED')[1]['total'], 0)
        self.assertEqual(self.delete_codes('DELETE_USED\nDELETE_KEEP')[0], 400)
        self.assertEqual(self.listing('?q=DELETE_KEEP')[1]['total'], 1)

    def test_selection_cancel_failure_delete_last_page_and_responsive(self):
        self.assertEqual(self.create_code('', quantity=25, prefix='UI_DELETE', paypal=1)[0], 200)
        browser = Browser(CHROME, self.work / 'selected-delete-profile')
        def wait(expression):
            for _ in range(300):
                if browser.value(expression): return
                time.sleep(.05)
            raise AssertionError(expression)
        def run(expression):
            r = browser.call('Runtime.evaluate', dict(expression=expression, awaitPromise=True, returnByValue=True), page=True)
            self.assertNotIn('exceptionDetails', r, r)
        try:
            browser.call('Network.enable', page=True)
            browser.call('Network.setCookie', dict(name='LOTTO_AUTH', value=self.admin.split(';')[0].split('=', 1)[1], url=self.url), page=True)
            browser.call('Page.navigate', dict(url=self.url + '/admin'), page=True)
            wait("!!window.adminPanel && !document.getElementById('adminPanelSection').hidden && getComputedStyle(document.getElementById('pageLoader')).opacity==='0'")
            browser.value("document.getElementById('adminListTab').click();document.getElementById('adminCodeSearch').value='UI_DELETE';document.getElementById('adminCodeSearchForm').requestSubmit()")
            wait("document.querySelectorAll('#adminCodeRows [data-admin-select]').length===20")
            self.assertTrue(browser.value("document.getElementById('adminDeleteCodesBtn').textContent==='Chỉnh Sửa' && !document.getElementById('adminDeleteCodesBtn').disabled && document.getElementById('adminFinishEditCodesBtn').hidden && [...document.querySelectorAll('#adminSelectAllCodes,[data-admin-select]')].every(e=>e.hidden)"))
            browser.value("document.getElementById('adminDeleteCodesBtn').click()")
            self.assertTrue(browser.value("document.getElementById('adminDeleteCodesBtn').textContent==='Xóa' && document.getElementById('adminDeleteCodesBtn').disabled && !document.getElementById('adminFinishEditCodesBtn').hidden && [...document.querySelectorAll('#adminSelectAllCodes,[data-admin-select]')].every(e=>!e.hidden) && !document.getElementById('adminReclaimDialog').open"))
            browser.value("document.querySelector('#adminCodeRows [data-admin-select]').click();document.getElementById('adminFinishEditCodesBtn').click()")
            self.assertTrue(browser.value("document.getElementById('adminDeleteCodesBtn').textContent==='Chỉnh Sửa' && !document.getElementById('adminDeleteCodesBtn').disabled && document.querySelectorAll('#adminCodeRows [data-admin-select]:checked').length===0 && [...document.querySelectorAll('#adminSelectAllCodes,[data-admin-select]')].every(e=>e.hidden)"))
            browser.value("document.getElementById('adminDeleteCodesBtn').click();document.querySelector('#adminCodeRows [data-admin-select]').click()")
            self.assertTrue(browser.value("document.getElementById('adminSelectAllCodes').indeterminate && document.getElementById('adminDeleteCodesBtn').textContent==='Xóa (1)'"))
            browser.value("document.getElementById('adminDeleteCodesBtn').click();document.getElementById('adminReclaimCancelBtn').click()")
            wait("!document.getElementById('adminDeleteCodesBtn').disabled")
            self.assertEqual(self.listing('?q=UI_DELETE')[1]['total'], 25)
            self.assertFalse(browser.value("document.getElementById('adminDeleteCodesBtn').disabled"))
            browser.value("document.getElementById('adminSelectAllCodes').click()")
            self.assertEqual(browser.value("document.querySelectorAll('#adminCodeRows [data-admin-select]:checked').length"), 20)
            browser.value("document.getElementById('adminNextCodesBtn').click()")
            wait("document.querySelectorAll('#adminCodeRows [data-admin-select]').length===5")
            self.assertTrue(browser.value("document.getElementById('adminDeleteCodesBtn').disabled && !document.getElementById('adminSelectAllCodes').checked"))
            browser.value("document.getElementById('adminSelectAllCodes').click();window.fixtureApi=api;api=async (...args)=>{if(args[2]?.action==='delete')throw new Error('fixture delete error');return window.fixtureApi(...args)}")
            run("(()=>{const p=document.getElementById('adminDeleteCodesBtn').onclick();document.getElementById('adminReclaimNoBtn').click();return p})()")
            self.assertTrue(browser.value("document.getElementById('adminPageMessage').textContent==='fixture delete error' && document.querySelectorAll('#adminCodeRows [data-admin-select]:checked').length===5 && !document.getElementById('adminDeleteCodesBtn').disabled"))
            browser.value("api=window.fixtureApi")
            checks=[]
            for theme in ['dark', 'light']:
                browser.value("document.body.classList.toggle('light-theme',"+str(theme=='light').lower()+")")
                for width in [1440, 390, 320]:
                    browser.call('Emulation.setDeviceMetricsOverride', dict(width=width,height=1000,deviceScaleFactor=1,mobile=width<500), page=True)
                    browser.value('document.activeElement.blur();scrollTo(0,0)')
                    data=browser.value("(()=>{const a=document.getElementById('adminRefreshCodesBtn').getBoundingClientRect(),b=document.getElementById('adminDeleteCodesBtn').getBoundingClientRect();return {sameRow:Math.abs(a.top-b.top)<.1,sameHeight:a.height===b.height,overflow:document.documentElement.scrollWidth>innerWidth+1}})()")
                    self.assertTrue(data['sameRow'] and data['sameHeight']);self.assertFalse(data['overflow'])
                    self.assertTrue(browser.value("[...document.querySelectorAll('#adminSelectAllCodes,[data-admin-select]')].every(e=>e.getBoundingClientRect().height===14)"))
                    checks.append(dict(theme=theme,width=width,**data))
                    if theme=='dark' and width==1440:
                        clip=browser.value("(()=>{const r=document.getElementById('adminListPane').getBoundingClientRect();return {x:r.left,y:r.top+scrollY,width:r.width,height:r.height,scale:1}})()")
                        shot=browser.call('Page.captureScreenshot',dict(format='png',clip=clip,captureBeyondViewport=True),page=True)
                        (ROOT/'Bin/session_1_latest/code_selected_delete_dark_1440.png').write_bytes(base64.b64decode(shot['data']))
            run("(()=>{const p=document.getElementById('adminDeleteCodesBtn').onclick();document.getElementById('adminReclaimNoBtn').click();return p})()")
            wait("document.getElementById('adminPageMessage').textContent==='Đã xóa 5 Code.' && document.getElementById('adminDeleteCodesBtn').textContent==='Chỉnh Sửa' && !document.getElementById('adminDeleteCodesBtn').disabled && [...document.querySelectorAll('#adminSelectAllCodes,[data-admin-select]')].every(e=>e.hidden) && document.querySelectorAll('#adminCodeRows [data-admin-select]').length===20")
            self.assertEqual(self.listing('?q=UI_DELETE')[1]['total'],20)
            self.assertIn('Trang 1 / 1',browser.value("document.getElementById('adminCodePageLabel').textContent"))
            browser.value("document.getElementById('adminDeleteCodesBtn').click();document.querySelector('#adminCodeRows [data-admin-select]').click();document.getElementById('adminCodeSearch').value='NO_DELETE_MATCH';document.getElementById('adminCodeSearchForm').requestSubmit()")
            wait("!!document.querySelector('#adminCodeRows .admin-empty')")
            self.assertTrue(browser.value("document.getElementById('adminDeleteCodesBtn').disabled && document.getElementById('adminSelectAllCodes').disabled"))
            (ROOT/'Bin/session_1_latest/code_selected_delete_layout_verification.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
        finally: browser.close()
