"""Real Java API, wallet and browser for two Bao levels in one future draw."""
import base64
import time
from pathlib import Path

from tests.browser_cdp import Browser
from tests.test_personal_prediction_web import PersonalPredictionWebTests
from tests.test_prize_web import CHROME, ROOT


class MultiBaoCycleWebTests(PersonalPredictionWebTests):
    def test_change_bao_in_browser_locks_same_draw_and_repeats_for_free(self):
        self.assertEqual(self.request('/api/admin/update-assets', {'username': 'member_fixture', 'diamond': '0', 'paypal': '10000000'}, self.admin)[0], 200)
        settings = self.request('/api/ml/effectiveness-settings', {'type': 'LOTO_6_45', 'enabled': 'false', 'ticketCount': '3', 'playMode': 'bao', 'baoLevel': '7', 'baoCount': '11'}, self.member)[1]
        code, first, _ = self.request('/api/ml/effectiveness-cycle', {'type': 'LOTO_6_45', 'configurationHash': settings['settings']['configurationHash']}, self.member)
        self.assertEqual(code, 200, first)
        self.assertEqual(first['billing']['balance'], 6920000)
        self.assertTrue(Path(CHROME).is_file())
        browser = Browser(CHROME, self.work / 'multi-bao-browser')
        def wait(expression):
            for _ in range(600):
                if browser.value(expression):
                    return
                time.sleep(.05)
            self.fail('Browser timeout: ' + expression + ' ' + str(browser.value('window.multiBaoErrors')))
        try:
            browser.call('Page.enable', page=True)
            browser.call('Network.enable', page=True)
            browser.call('Emulation.setDeviceMetricsOverride', {'width': 1560, 'height': 1050, 'deviceScaleFactor': 1, 'mobile': False}, page=True)
            browser.call('Page.addScriptToEvaluateOnNewDocument', {'source': "window.multiBaoErrors=[];addEventListener('error',e=>multiBaoErrors.push(e.message));addEventListener('unhandledrejection',e=>multiBaoErrors.push(String(e.reason)));const oldFetch=fetch;window.fetch=(input,options)=>{const url=new URL(typeof input==='string'?input:input.url,location.href);if(url.pathname.startsWith('/api/live-'))return Promise.resolve(new Response(JSON.stringify({ok:true,results:[],rows:[],history:[],meta:{}}),{headers:{'Content-Type':'application/json'}}));return oldFetch(input,options)}"}, page=True)
            browser.call('Network.setCookie', {'name': 'LOTTO_AUTH', 'value': self.member.split('=', 1)[1].split(';', 1)[0], 'url': self.url}, page=True)
            browser.call('Page.navigate', {'url': self.url}, page=True)
            wait("!!window.VietlottEffectiveness && typeof currentUser!=='undefined' && currentUser==='member_fixture'")
            browser.value("document.getElementById('predictModeEffectivenessTab').click();document.getElementById('effectivenessType').value='LOTO_6_45';document.getElementById('effectivenessType').dispatchEvent(new Event('change'))")
            wait("document.querySelectorAll('.effectiveness-cycle').length===1 && !document.getElementById('effectivenessSettings').disabled")
            browser.value("document.getElementById('effectivenessSettings').click();document.getElementById('effectivenessBaoLevel').value='8';document.getElementById('effectivenessBaoLevel').dispatchEvent(new Event('change'));document.getElementById('effectivenessBaoCount').value='1';document.getElementById('effectivenessBaoCount').dispatchEvent(new Event('input'));document.getElementById('effectivenessLock').click()")
            wait("document.querySelectorAll('.effectiveness-cycle').length===2 && !document.getElementById('effectivenessLock').disabled")
            report = self.request('/api/ml/effectiveness?type=LOTO_6_45', cookie=self.member)[1]
            self.assertEqual(report['billing']['balance'], 5800000)
            self.assertEqual({row['targetDrawId'] for row in report['cycles']}, {first['targetDrawId']})
            self.assertEqual({row['selectionKey'] for row in report['cycles']}, {'bao:7', 'bao:8'})
            self.assertEqual(len(report['billing']['charges']), 2)
            keys = browser.value("[...document.querySelectorAll('.effectiveness-cycle')].map(x=>x.dataset.effectivenessState)")
            self.assertEqual(len(set(keys)), 2)
            for row in report['cycles']:
                selector = f'.effectiveness-cycle[data-effectiveness-state="LOTO_6_45:cycle:{row["cycleId"]}"]'
                browser.value(f"document.querySelector('{selector}').open=true")
                panel = selector + " .effectiveness-cycle-method[data-method='web']"
                wait(f'document.querySelectorAll(`{panel} .effectiveness-bao-row`).length>0')
                self.assertEqual(browser.value(f'document.querySelectorAll(`{panel} .effectiveness-bao-row:first-child > .effectiveness-ticket > .effectiveness-ball`).length'), row['config']['baoLevel'])
                self.assertIn(f"Bao {row['config']['baoLevel']}", browser.value(f"document.querySelector('{selector} > summary').textContent"))
            # Changing the quantity within an existing Bao level cannot buy/reroll it again.
            self.assertEqual(self.request('/api/admin/update-assets', {'username': 'member_fixture', 'diamond': '0', 'paypal': '0'}, self.admin)[0], 200)
            browser.value("document.getElementById('effectivenessRefresh').click()")
            wait("!document.getElementById('effectivenessRefresh').disabled && document.querySelector('.effectiveness-quote-total strong').textContent.trim()==='0 PayPal'")
            self.assertEqual(browser.value("document.getElementById('effectivenessLock').textContent"), 'Dùng bộ đã có')
            browser.value("document.getElementById('effectivenessBaoCount').value='2';document.getElementById('effectivenessBaoCount').dispatchEvent(new Event('input'));document.getElementById('effectivenessLock').click()")
            wait("!document.getElementById('effectivenessLock').disabled && document.getElementById('effectivenessStatus').textContent.includes('không trừ thêm phí')")
            final = self.request('/api/ml/effectiveness?type=LOTO_6_45', cookie=self.member)[1]
            self.assertEqual(final['billing']['balance'], 0)
            self.assertEqual(len(final['billing']['charges']), 2)
            self.assertEqual(next(row for row in final['cycles'] if row['config']['baoLevel'] == 8)['config']['baoCount'], 1)
            self.assertEqual(browser.value("document.querySelectorAll('.effectiveness-cycle').length"), 2)
            for width in (390, 1560):
                browser.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 1050, 'deviceScaleFactor': 1, 'mobile': width == 390}, page=True)
                browser.value("document.getElementById('effectivenessAdmin').open=false;document.querySelector('.effectiveness-cycle').scrollIntoView({block:'start'})")
                self.assertTrue(browser.value("[...document.querySelectorAll('.effectiveness-cycle')].every(x=>x.scrollWidth<=x.clientWidth+1)"))
                (ROOT.parent / f'multi-bao-cycle-{width}.png').write_bytes(base64.b64decode(browser.call('Page.captureScreenshot', {'format': 'png'}, page=True)['data']))
            self.assertEqual(browser.value('window.multiBaoErrors'), [])
        finally:
            browser.close()
        self.assertEqual(self.request('/api/ml/effectiveness?type=LOTO_6_45', cookie=self.admin)[1]['counts']['total'], 0)
