"""Authenticated Java -> immutable Python data -> Bao/child browser views."""
import base64
import json
import io
import tempfile
import time
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from tests.test_personal_prediction_web import PersonalPredictionWebTests
from tests.browser_cdp import Browser
from tests.test_prize_web import CHROME, ROOT


class BaoDisplayWebTests(PersonalPredictionWebTests):
    def test_only_selected_bao_class_preserves_wallet_and_pagination(self):
        self.assertEqual(self.request('/api/admin/update-assets', {'username': 'member_fixture', 'diamond': '0', 'paypal': '10000000'}, self.admin)[0], 200)
        settings = self.request('/api/ml/effectiveness-settings', {'type': 'LOTO_6_45', 'enabled': 'false', 'ticketCount': '3', 'playMode': 'bao', 'baoLevel': '7', 'baoCount': '11'}, self.member)[1]
        locked = self.request('/api/ml/effectiveness-cycle', {'type': 'LOTO_6_45', 'configurationHash': settings['settings']['configurationHash']}, self.member)
        self.assertEqual(locked[0], 200, locked[1])
        balance = locked[1]['billing']['balance']
        report = self.request('/api/ml/effectiveness?type=LOTO_6_45', cookie=self.member)[1]
        prediction = report['cycles'][0]['methods']['web']['predictionId']
        base = '/api/ml/effectiveness-tickets?type=LOTO_6_45&predictionId=' + prediction
        self.assertEqual(self.request(base + '&view=bao', cookie=self.admin)[0], 400)
        for suffix in ('&view=unknown', '&view=tickets', '&view=bao&afterTicketIndex=1'):
            self.assertEqual(self.request(base + suffix, cookie=self.member)[0], 400)
        parents = self.request(base + '&view=bao&page=2', cookie=self.member)
        self.assertEqual(parents[0], 200, parents[1])
        self.assertEqual([row['parentIndex'] for row in parents[1]['baoParents']], [11])
        self.assertNotIn('tickets', parents[1])
        expected = parents[1]['baoParents'][0]
        exported = self.request('/api/ml/effectiveness-export?type=LOTO_6_45&cycleId=' + locked[1]['cycleId'], cookie=self.member)
        self.assertEqual(exported[0], 200, exported[1])
        self.assertNotIn('tickets', exported[1]['methods']['web'])
        self.assertEqual(len(exported[1]['methods']['web']['baoParents']), 11)
        request = urllib.request.Request(self.url + '/api/ml/effectiveness-export?type=LOTO_6_45&format=xlsx&cycleId=' + locked[1]['cycleId'], headers={'Cookie': self.member})
        with urllib.request.urlopen(request, timeout=25) as response:
            self.assertIn('spreadsheetml.sheet', response.headers['Content-Type'])
            workbook = response.read()
        with zipfile.ZipFile(io.BytesIO(workbook)) as archive:
            sheet = ET.fromstring(archive.read('xl/worksheets/sheet2.xml'))
        rows = sheet.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheetData/{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row')
        self.assertEqual(len(rows), 12)
        self.assertIn('Bộ số Bao gốc', ''.join(rows[0].itertext()))
        with tempfile.TemporaryDirectory(prefix='bao-display-ui-', dir=ROOT / 'runtime') as directory:
            browser = Browser(CHROME, Path(directory))
            def wait(expression):
                for _ in range(240):
                    if browser.value(expression):
                        return
                    time.sleep(.05)
                self.fail('Timeout: ' + expression + ' errors=' + str(browser.value('window.displayErrors')))
            try:
                browser.call('Page.enable', page=True)
                browser.call('Network.enable', page=True)
                browser.call('Emulation.setDeviceMetricsOverride', {'width': 1560, 'height': 1050, 'deviceScaleFactor': 1, 'mobile': False}, page=True)
                browser.call('Page.addScriptToEvaluateOnNewDocument', {'source': "window.displayErrors=[];addEventListener('error',e=>displayErrors.push(e.message));addEventListener('unhandledrejection',e=>displayErrors.push(String(e.reason)));const originalFetch=fetch;window.fetch=(input,options)=>{const url=new URL(typeof input==='string'?input:input.url,location.href);if(url.pathname.startsWith('/api/live-'))return Promise.resolve(new Response(JSON.stringify({ok:true,results:[],rows:[],history:[],meta:{}}),{headers:{'Content-Type':'application/json'}}));return originalFetch(input,options)}"}, page=True)
                browser.call('Network.setCookie', {'name': 'LOTTO_AUTH', 'value': self.member.split('=', 1)[1].split(';', 1)[0], 'url': self.url}, page=True)
                browser.call('Page.navigate', {'url': self.url}, page=True)
                wait("!!window.VietlottEffectiveness && typeof currentUser!=='undefined' && currentUser==='member_fixture'")
                browser.value("document.getElementById('predictModeEffectivenessTab').click();document.getElementById('effectivenessType').value='LOTO_6_45';document.getElementById('effectivenessType').dispatchEvent(new Event('change'))")
                wait("!!document.querySelector('.effectiveness-cycle') && !document.getElementById('effectivenessRefresh').disabled")
                browser.value("document.querySelector('.effectiveness-cycle').open=true")
                panel = ".effectiveness-cycle-method[data-method='web']"
                wait(f"document.querySelectorAll(\"{panel} .effectiveness-bao-row\").length===10")
                wait("document.querySelectorAll(\".effectiveness-cycle-method[data-method='random'] .effectiveness-bao-row\").length===10")
                self.assertEqual(browser.value(f"document.querySelectorAll(\"{panel} .effectiveness-bao-row:first-child > .effectiveness-ticket > .effectiveness-ball\").length"), 7)
                self.assertEqual(browser.value(f"document.querySelectorAll(\"{panel} [data-ticket-view], {panel} [data-bao-children], {panel} [data-ticket-index]\").length"), 0)
                browser.value(f"document.querySelector(\"{panel} [data-ticket-page='2']\").click()")
                wait(f"document.querySelector(\"{panel} [data-bao-index='11']\")!==null")
                actual = browser.value(f"[...document.querySelectorAll(\"{panel} .effectiveness-bao-row > .effectiveness-ticket > .effectiveness-ball\")].map(x=>Number(x.textContent))")
                self.assertEqual(actual, expected['main'])
                self.assertEqual(browser.value(f"document.querySelectorAll(\"{panel} [data-ticket-index]\").length"), 0)
                for width in (390, 1560):
                    browser.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 1050, 'deviceScaleFactor': 1, 'mobile': width == 390}, page=True)
                    browser.value("document.querySelector('.effectiveness-cycle').scrollIntoView({block:'start'})")
                    time.sleep(.15)
                    self.assertTrue(browser.value(f"(()=>{{const p=document.querySelector(\"{panel}\");return p.scrollWidth<=p.clientWidth+1}})()"))
                    wait("document.querySelectorAll(\".effectiveness-cycle-method[data-method='random'] .effectiveness-bao-row\").length===10")
                    artifact = ROOT.parent / f'bao-display-{width}.png'
                    artifact.write_bytes(base64.b64decode(browser.call('Page.captureScreenshot', {'format': 'png'}, page=True)['data']))
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait(f"!document.getElementById('effectivenessRefresh').disabled && document.querySelector(\"{panel} [data-bao-index='11']\")!==null")
                browser.value("window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:false}}))")
                wait("!document.querySelector('.effectiveness-bao-row')")
                self.assertEqual(browser.value('window.displayErrors'), [])
            finally:
                browser.close()
        self.assertEqual(self.request('/api/ml/effectiveness-settings?type=LOTO_6_45', cookie=self.member)[1]['billing']['balance'], balance)
