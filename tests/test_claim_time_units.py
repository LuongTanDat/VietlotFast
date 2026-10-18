"""Claim time units against disposable SQLite/Java and real Chrome."""
import base64
import json
import sqlite3
import time
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from tests.test_admin_panel import AdminPanelTests
from tests.browser_cdp import Browser
from tests.test_prize_web import CHROME, ROOT


class ClaimTimeUnitTests(AdminPanelTests):
    def test_seconds_validation_persistence_and_atomic_repeat(self):
        self.set_balance(350000)
        cookie = self.claim_account('seconds_unit_fixture')
        total = self.listing()[1]['stats']['total']
        before = self.snapshot()
        for fields in [dict(cooldownSeconds=0), dict(cooldownSeconds=-1),
                       dict(cooldownSeconds='0.5'), dict(cooldownSeconds=31536001),
                       dict(cooldownSeconds=60, cooldownHours=1),
                       dict(cooldownSeconds=60, maxPerUser=1)]:
            form = dict(maxPerUser=0, **{'paypal': 1})
            form.update(fields)
            self.assertEqual(self.create_code('', **form)[0], 400, fields)
            self.assertEqual(self.listing()[1]['stats']['total'], total)
            self.assertEqual(self.snapshot(), before)
        for seconds in [1, 90, 7200, 172800, 31536000]:
            code = f'SECOND_UNIT_{seconds}'
            self.assertEqual(self.create_code(code, paypal=1, maxUses=4,
                                              maxPerUser=0, cooldownSeconds=seconds)[0], 200)
            row = self.listing('?q=' + code)[1]['codes'][0]
            self.assertEqual((row['maxPerUser'], row['cooldownSeconds']), (0, seconds))
        code = 'SECOND_UNIT_90'
        status, data, _ = self.redeem(code, cookie)
        self.assertEqual(status, 200)
        self.assertEqual(data['claim']['cooldownSeconds'], 90)
        next_time = datetime.fromisoformat(data['claim']['nextEligibleAt'].replace('Z', '+00:00'))
        self.assertGreater(next_time, datetime.now(timezone.utc) + timedelta(seconds=88))
        self.assertEqual(self.redeem(code, cookie)[0], 400)
        self.server.terminate(); self.server.wait(timeout=10)
        self.start_server(); self.login()
        _, _, headers = self.request('/api/login', dict(username='seconds_unit_fixture', password='fixture_password'))
        cookie = headers['Set-Cookie']
        self.assertEqual(self.listing('?q=' + code)[1]['codes'][0]['cooldownSeconds'], 90)
        self.assertEqual(self.redeem(code, cookie)[0], 400)
        old = (datetime.now(timezone.utc) - timedelta(seconds=91)).isoformat().replace('+00:00', 'Z')
        with closing(sqlite3.connect(self.work / 'runtime/lotto_web.db')) as db:
            db.execute('UPDATE gift_code_redemptions SET redeemed_at=? WHERE code=?', (old, code))
            db.commit()
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(lambda _: self.redeem(code, cookie)[0], range(5)))
        self.assertEqual(results.count(200), 1)
        self.assertEqual(self.listing('?q=' + code)[1]['codes'][0]['usedCount'], 2)

    def test_four_units_ui_save_reset_shared_focus_and_responsive(self):
        browser = Browser(CHROME, self.work / 'claim-time-ui-profile')
        def wait(expression):
            for _ in range(300):
                if browser.value(expression):
                    return
                time.sleep(.05)
            raise AssertionError('Timeout: ' + expression)
        def run(expression):
            result = browser.call('Runtime.evaluate', dict(expression=expression,
                                  awaitPromise=True, returnByValue=True), page=True)
            self.assertNotIn('exceptionDetails', result, result)
        try:
            browser.call('Network.enable', page=True)
            browser.call('Network.setCookie', dict(name='LOTTO_AUTH',
                value=self.admin.split(';')[0].split('=', 1)[1], url=self.url), page=True)
            browser.call('Page.navigate', dict(url=self.url + '/admin'), page=True)
            wait("!!window.adminPanel && !document.getElementById('adminPanelSection').hidden && getComputedStyle(document.getElementById('pageLoader')).opacity==='0'")
            self.assertEqual(browser.value("document.querySelector('#adminClaimMode option[value=hours]').textContent"), 'Theo Thời Gian')
            self.assertEqual(browser.value("[...document.getElementById('adminClaimTimeUnit').options].map(o=>o.textContent)"), ['Giây', 'Phút', 'Giờ', 'Ngày'])
            for unit, amount, seconds, maximum, label in [('seconds', 15, 15, 31536000, 'giây'),
                    ('minutes', 2, 120, 525600, 'phút'), ('hours', 3, 10800, 8760, 'giờ'),
                    ('days', 2, 172800, 365, 'ngày')]:
                browser.value("document.getElementById('adminClaimLimit').value='repeat';document.getElementById('adminClaimLimit').dispatchEvent(new Event('change'));document.getElementById('adminClaimMode').value='hours';document.getElementById('adminClaimMode').dispatchEvent(new Event('change'))")
                browser.value(f"document.getElementById('adminClaimTimeUnit').value={json.dumps(unit)};document.getElementById('adminClaimTimeUnit').dispatchEvent(new Event('change'));document.getElementById('adminClaimValue').value={json.dumps(str(amount))};document.getElementById('settingsCodePaypal').value='1';document.getElementById('settingsNewCode').value='UI_TIME_{unit.upper()}'")
                self.assertEqual(browser.value("document.getElementById('adminClaimValue').max"), str(maximum))
                self.assertTrue(browser.value("!document.getElementById('adminClaimTimeUnit').hidden && !document.getElementById('adminClaimTimeUnit').disabled && document.getElementById('adminClaimUnit').hidden"))
                run("document.getElementById('settingsCreateCodeForm').onsubmit({preventDefault(){},currentTarget:document.getElementById('settingsCreateCodeForm')})")
                row = self.listing('?q=UI_TIME_' + unit.upper())[1]['codes'][0]
                self.assertEqual(row['cooldownSeconds'], seconds)
                self.assertEqual(row['maxPerUser'], 0)
                self.assertTrue(browser.value("document.getElementById('adminClaimTimeUnit').value==='hours' && document.getElementById('adminClaimTimeUnit').hidden && document.getElementById('adminClaimTimeUnit').disabled && document.getElementById('adminClaimMode').value==='count' && document.getElementById('adminClaimValue').value==='1' && !document.getElementById('adminClaimUnit').hidden"))
                browser.value("document.getElementById('adminListTab').click()")
                wait(f"document.getElementById('adminCodeRows').textContent.includes('UI_TIME_{unit.upper()}')")
                self.assertIn(f'{amount} {label}', browser.value("document.getElementById('adminCodeRows').textContent"))
                browser.value("document.getElementById('adminCreateTab').click()")
            # Over-limit draft is rejected without creating a code or resetting input.
            browser.value("document.getElementById('adminClaimLimit').value='repeat';document.getElementById('adminClaimLimit').dispatchEvent(new Event('change'));document.getElementById('adminClaimMode').value='hours';document.getElementById('adminClaimMode').dispatchEvent(new Event('change'));document.getElementById('adminClaimTimeUnit').value='days';document.getElementById('adminClaimTimeUnit').dispatchEvent(new Event('change'));document.getElementById('adminClaimValue').value='366';document.getElementById('settingsCodePaypal').value='1';document.getElementById('settingsNewCode').value='TIME_OVER_LIMIT'")
            run("document.getElementById('settingsCreateCodeForm').onsubmit({preventDefault(){},currentTarget:document.getElementById('settingsCreateCodeForm')})")
            self.assertEqual(self.listing('?q=TIME_OVER_LIMIT')[1]['total'], 0)
            self.assertTrue(browser.value("document.getElementById('settingsCreateCodeMessage').classList.contains('is-error') && document.getElementById('adminClaimValue').value==='366'"))
            checks = []
            for theme in ['dark', 'light']:
                browser.value("document.body.classList.toggle('light-theme'," + str(theme == 'light').lower() + ")")
                for width in [1440, 1280, 1100, 760, 600, 390, 320]:
                    browser.call('Emulation.setDeviceMetricsOverride', dict(width=width, height=1000,
                        deviceScaleFactor=1, mobile=width < 500), page=True)
                    for unit in ['seconds', 'minutes', 'hours', 'days']:
                        browser.value(f"document.getElementById('adminClaimTimeUnit').value={json.dumps(unit)};document.getElementById('adminClaimTimeUnit').dispatchEvent(new Event('change'));document.getElementById('adminClaimValue').value='2'")
                        for field in ['adminClaimMode', 'adminClaimValue', 'adminClaimTimeUnit']:
                            data = browser.value("""(()=>{const e=document.getElementById(FIELD);e.focus();const p=e.closest('.admin-claim-control'),r=p.getBoundingClientRect(),s=getComputedStyle(p);return {height:r.height,outline:s.outlineWidth,outlineColor:s.outlineColor,innerOutline:getComputedStyle(e).outlineStyle,inside:[...p.children].filter(x=>!x.hidden).every(x=>{const a=x.getBoundingClientRect();return a.left>=r.left && a.right<=r.right+.1}),overflow:document.documentElement.scrollWidth>innerWidth+1}})()""".replace('FIELD', json.dumps(field)))
                            self.assertEqual(data['height'], 40)
                            self.assertEqual(data['outline'], '2px')
                            self.assertEqual(data['outlineColor'], 'rgb(106, 171, 255)')
                            self.assertEqual(data['innerOutline'], 'none')
                            self.assertTrue(data['inside'])
                            self.assertFalse(data['overflow'])
                            checks.append(dict(theme=theme, width=width, unit=unit, field=field, **data))
                    if (theme, width) in [('dark', 1440), ('light', 390)]:
                        clip = browser.value("(()=>{const r=document.getElementById('adminClaimMode').closest('.admin-field').getBoundingClientRect();return {x:Math.max(0,r.left-4),y:r.top+scrollY-4,width:r.width+8,height:r.height+8,scale:1}})()")
                        shot = browser.call('Page.captureScreenshot', dict(format='png', clip=clip, captureBeyondViewport=True), page=True)
                        (ROOT / f'Bin/session_1_latest/claim_time_units_{theme}_{width}.png').write_bytes(base64.b64decode(shot['data']))
            (ROOT / 'Bin/session_1_latest/claim_time_units_layout_verification.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
        finally:
            browser.close()
