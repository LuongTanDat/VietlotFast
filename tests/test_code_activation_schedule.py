"""Code activation schedules on disposable SQLite, server clock and Chrome."""
import base64
import json
import sqlite3
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.test_gift_codes import GiftCodeTests
from tests.browser_cdp import Browser
from tests.test_prize_web import CHROME, ROOT


class CodeActivationScheduleTests(GiftCodeTests):
    def listing(self):
        return self.request('/api/admin/gift-codes', cookie=self.admin)[1]

    def row(self, code):
        return next(row for row in self.listing()['codes'] if row['code'] == code)

    def test_old_code_schema_migrates_without_activating_paused_codes(self):
        self.assertEqual(self.create_code('OLD_SCHEMA_ACTIVE', paypal=1)[0], 200)
        self.assertEqual(self.create_code('OLD_SCHEMA_PAUSED', paypal=1, active=0)[0], 200)
        before = self.snapshot()
        type(self).server.terminate()
        type(self).server.wait(timeout=10)
        with closing(sqlite3.connect(self.work / 'runtime/lotto_web.db')) as db:
            db.execute('ALTER TABLE gift_codes DROP COLUMN activates_at')
            db.commit()
        type(self).start_server()
        type(self).login()
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(self.row('OLD_SCHEMA_ACTIVE')['active'])
        self.assertFalse(self.row('OLD_SCHEMA_PAUSED')['active'])
        self.assertEqual(self.row('OLD_SCHEMA_PAUSED')['activatesAt'], '')
        self.assertEqual(self.redeem('OLD_SCHEMA_PAUSED')[0], 400)
        self.assertEqual(self.redeem('OLD_SCHEMA_ACTIVE')[0], 200)

    def test_activation_schedule_enforced_persisted_and_manual_toggle_cancels(self):
        self.set_balance(350000)
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        start = future.isoformat()
        expiry = (future + timedelta(hours=2)).isoformat()
        total = self.listing()['total']
        before = self.snapshot()
        for extra in [dict(activatesAt='bad-date'),
                      dict(activatesAt='2000-01-01T00:00:00Z'),
                      dict(activatesAt=start, active=1),
                      dict(activatesAt=expiry, expiresAt=expiry),
                      dict(activatesAt=expiry, expiresAt=start)]:
            form = dict(active=0, paypal=100)
            form.update(extra)
            self.assertEqual(self.create_code('INVALID_SCHEDULE', **form)[0], 400)
        self.assertEqual(self.listing()['total'], total)
        self.assertEqual(self.snapshot(), before)
        form = dict(code='NO_SCHEDULE_ACCESS', active=0, activatesAt=start, paypal=1, maxUses=1)
        self.assertEqual(self.request('/api/admin/gift-codes', form, self.member)[0], 403)
        self.assertEqual(self.request('/api/admin/gift-codes', form)[0], 401)
        self.assertEqual(self.create_code('PAUSED_LEGACY', active=0, paypal=1)[0], 200)
        self.assertFalse(self.row('PAUSED_LEGACY')['active'])
        self.assertEqual(self.row('PAUSED_LEGACY')['activatesAt'], '')
        offset_time = future.astimezone(timezone(timedelta(hours=7))).isoformat()
        result, created, _ = self.create_code('SCHEDULED_ONCE', active=0, paypal=100,
                                             maxUses=1, activatesAt=offset_time, expiresAt=expiry)
        self.assertEqual(result, 200, created)
        self.assertEqual(datetime.fromisoformat(created['activatesAt'].replace('Z', '+00:00')), future)
        stats = self.listing()['stats']
        before = self.snapshot()
        self.assertEqual(self.redeem('SCHEDULED_ONCE')[0], 400)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.row('SCHEDULED_ONCE')['usedCount'], 0)
        type(self).server.terminate()
        type(self).server.wait(timeout=10)
        type(self).start_server()
        type(self).login()
        self.assertFalse(self.row('SCHEDULED_ONCE')['active'])
        self.assertEqual(self.redeem('SCHEDULED_ONCE')[0], 400)
        with closing(sqlite3.connect(self.work / 'runtime/lotto_web.db')) as db:
            db.execute("UPDATE gift_codes SET activates_at=? WHERE code='SCHEDULED_ONCE'",
                       ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat().replace('+00:00', 'Z'),))
            db.commit()
        self.assertTrue(self.row('SCHEDULED_ONCE')['active'])
        self.assertEqual(self.listing()['stats']['active'], stats['active'] + 1)
        self.assertEqual(self.listing()['stats']['inactive'], stats['inactive'] - 1)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.redeem('SCHEDULED_ONCE')[0], range(4)))
        self.assertEqual(results.count(200), 1)
        self.assertEqual(self.row('SCHEDULED_ONCE')['usedCount'], 1)
        self.assertEqual(json.loads(self.snapshot()[0])['paypalBalance'], 350100)
        self.assertEqual(self.create_code('MANUAL_CANCEL', active=0, paypal=1, activatesAt=start)[0], 200)
        self.assertEqual(self.request('/api/admin/gift-codes',
                                     dict(action='set-active', code='MANUAL_CANCEL', active=0), self.admin)[0], 200)
        self.assertEqual(self.row('MANUAL_CANCEL')['activatesAt'], '')
        self.assertEqual(self.redeem('MANUAL_CANCEL')[0], 400)
        self.assertEqual(self.request('/api/admin/gift-codes',
                                     dict(action='set-active', code='MANUAL_CANCEL', active=1), self.admin)[0], 200)
        self.assertEqual(self.redeem('MANUAL_CANCEL')[0], 200)
        self.assertEqual(self.create_code('SCHEDULE_EXPIRED', active=0, paypal=1, activatesAt=start)[0], 200)
        with closing(sqlite3.connect(self.work / 'runtime/lotto_web.db')) as db:
            db.execute("UPDATE gift_codes SET activates_at='2000-01-01T00:00:00Z',expires_at='2001-01-01T00:00:00Z' WHERE code='SCHEDULE_EXPIRED'")
            db.commit()
        before = self.snapshot()
        self.assertEqual(self.redeem('SCHEDULE_EXPIRED')[0], 400)
        self.assertEqual(self.snapshot(), before)

    @unittest.skipUnless(Path(CHROME).exists(), 'Chrome required')
    def test_activation_date_ui_timezone_validation_and_responsive(self):
        browser = Browser(CHROME, self.work / 'activation-ui-profile')
        try:
            browser.call('Network.enable', page=True)
            browser.call('Network.setCookie', dict(name='LOTTO_AUTH',
                         value=self.admin.split(';')[0].split('=', 1)[1], url=self.url), page=True)
            browser.call('Emulation.setTimezoneOverride', dict(timezoneId='America/New_York'), page=True)
            browser.call('Page.navigate', dict(url=self.url + '/admin'), page=True)
            for _ in range(300):
                if browser.value("!!window.adminPanel && !document.getElementById('adminPanelSection').hidden && document.getElementById('adminTotalCodes').textContent!=='—' && getComputedStyle(document.getElementById('pageLoader')).opacity==='0'"):
                    break
                time.sleep(.05)
            else:
                self.fail('Admin page did not load')
            self.assertTrue(browser.value("document.getElementById('adminActivationField').hidden && document.getElementById('settingsCodeActivation').disabled"))
            browser.value("document.querySelector('[name=adminCodeActive][value=\"0\"]').click()")
            self.assertTrue(browser.value("!document.getElementById('adminActivationField').hidden && !document.getElementById('settingsCodeActivation').disabled"))
            future = datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(hours=2)
            expiry = future + timedelta(hours=1)
            local = future.astimezone(timezone(timedelta(hours=7))).strftime('%Y-%m-%dT%H:%M')
            local_expiry = expiry.astimezone(timezone(timedelta(hours=7))).strftime('%Y-%m-%dT%H:%M')
            browser.value("document.getElementById('settingsCodeActivation').value=" + json.dumps(local))
            browser.value("document.getElementById('adminClearActivationBtn').click()")
            self.assertEqual(browser.value("document.getElementById('settingsCodeActivation').value"), '')
            browser.value("document.getElementById('settingsCodeActivation').value=" + json.dumps(local))
            browser.value("document.querySelector('[name=adminCodeActive][value=\"1\"]').click()")
            self.assertTrue(browser.value("document.getElementById('adminActivationField').hidden && document.getElementById('settingsCodeActivation').disabled"))
            browser.value("document.querySelector('[name=adminCodeActive][value=\"0\"]').click()")
            browser.value("document.getElementById('settingsNewCode').value='UI_SCHEDULE';document.getElementById('settingsCodePaypal').value='100'")
            submit = "document.getElementById('settingsCreateCodeForm').onsubmit({preventDefault(){},currentTarget:document.getElementById('settingsCreateCodeForm')})"
            before = self.snapshot()
            browser.value("document.getElementById('settingsCodeActivation').value='2000-01-01T12:00'")
            browser.value(submit)
            self.assertIn('tương lai', browser.value("document.getElementById('settingsCreateCodeMessage').textContent"))
            self.assertEqual(self.snapshot(), before)
            browser.value("document.getElementById('settingsCodeActivation').value=" + json.dumps(local) + ";document.getElementById('settingsCodeExpiry').value=" + json.dumps(local))
            browser.value(submit)
            self.assertIn('trước ngày hết hạn', browser.value("document.getElementById('settingsCreateCodeMessage').textContent"))
            self.assertEqual(self.snapshot(), before)
            browser.value("document.getElementById('settingsCodeExpiry').value=" + json.dumps(local_expiry))
            browser.value(submit)
            for _ in range(200):
                if browser.value("!document.getElementById('adminCodeSuccess').hidden"):
                    break
                time.sleep(.05)
            else:
                self.fail(browser.value("document.getElementById('settingsCreateCodeMessage').textContent"))
            for _ in range(200):
                if browser.value("document.getElementById('adminCodeSuccess').hidden && document.getElementById('settingsNewCode').value==='' && !document.querySelector('#settingsCreateCodeForm button[type=submit]').disabled"):
                    break
                time.sleep(.05)
            else:
                self.fail('Create form did not reset after success')
            row = self.row('UI_SCHEDULE')
            self.assertFalse(row['active'])
            self.assertEqual(datetime.fromisoformat(row['activatesAt'].replace('Z', '+00:00')), future)
            self.assertEqual(datetime.fromisoformat(row['expiresAt'].replace('Z', '+00:00')), expiry)
            browser.value("document.getElementById('adminListTab').click()")
            for _ in range(200):
                if browser.value("document.getElementById('adminCodeRows').textContent.includes('Chờ kích hoạt')"):
                    break
                time.sleep(.05)
            self.assertIn('Chờ kích hoạt', browser.value("document.getElementById('adminCodeRows').textContent"))
            browser.value("document.getElementById('adminCreateTab').click();document.querySelector('[name=adminCodeActive][value=\"0\"]').click();document.getElementById('settingsCodeActivation').value=" + json.dumps(local))
            layouts = []
            for theme in ['dark', 'light']:
                browser.value("document.body.classList.toggle('light-theme'," + str(theme == 'light').lower() + ")")
                for width in [1440, 1280, 1279, 1201, 1200, 1024, 768, 760, 601, 600, 390, 320]:
                    browser.call('Emulation.setDeviceMetricsOverride', dict(width=width, height=1000, deviceScaleFactor=1, mobile=width < 500), page=True)
                    layout = browser.value("""(()=>{const e=document.getElementById('settingsCodeActivation'),r=e.closest('.admin-date-control').getBoundingClientRect(),c=e.closest('.admin-code-basics').getBoundingClientRect();return {overflow:document.documentElement.scrollWidth>innerWidth+1,visible:!document.getElementById('adminActivationField').hidden,height:r.height,inside:r.left>=c.left&&r.right<=c.right+.1,rows:[document.getElementById('adminCodeKind'),document.querySelector('.admin-prefix-control'),document.querySelector('.admin-date-control'),document.querySelector('.admin-activation-options'),e.closest('.admin-date-control')].map(x=>x.getBoundingClientRect().top)}})()""")
                    self.assertFalse(layout['overflow'], (theme, width, layout))
                    self.assertTrue(layout['visible'] and layout['inside'], (theme, width, layout))
                    self.assertEqual(layout['height'], 40)
                    if width >= 1280:
                        self.assertLess(max(layout['rows']) - min(layout['rows']), .1)
                    self.assertNotIn('Để trống để kích hoạt thủ công.', browser.value("document.getElementById('settingsCreateCodeForm').textContent"))
                    layouts.append(dict(theme=theme, width=width, **layout))
                    if (theme, width) in [('dark', 1440), ('dark', 1280), ('light', 390)]:
                        browser.value("document.activeElement.blur();window.scrollTo(0,0)")
                        clip = browser.value("(()=>{const r=document.querySelector('.admin-shell').getBoundingClientRect();return {x:r.x,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()")
                        shot = browser.call('Page.captureScreenshot', dict(format='png', clip=clip, captureBeyondViewport=True), page=True)
                        (ROOT / f'Bin/session_1_latest/inline_activation_date_{theme}_{width}.png').write_bytes(base64.b64decode(shot['data']))
            (ROOT / 'Bin/session_1_latest/inline_activation_date_layout_verification.json').write_text(json.dumps(layouts, indent=2), encoding='utf-8')
        finally:
            browser.close()
