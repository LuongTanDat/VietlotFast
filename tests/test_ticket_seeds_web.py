"""Authenticated seed generation -> API page -> copy UI -> actual XLSX export."""
import base64
import io
import time
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

from ai import tracking_ticket_seed as seeds
from tests.browser_cdp import Browser
from tests.test_personal_prediction_web import PersonalPredictionWebTests
from tests.test_prize_web import CHROME, ROOT


class TicketSeedsWebTests(PersonalPredictionWebTests):
    def test_normal_and_bao_seeds_are_consistent_in_api_browser_and_excel(self):
        self.assertEqual(self.request('/api/admin/update-assets', {'username': 'member_fixture', 'diamond': '0', 'paypal': '10000000'}, self.admin)[0], 200)
        settings = '/api/ml/effectiveness-settings'
        locks = []
        for form in ({'playMode': 'normal', 'ticketCount': '12'}, {'playMode': 'bao', 'ticketCount': '12', 'baoLevel': '7', 'baoCount': '11'}):
            saved = self.request(settings, {'type': 'LOTO_6_45', 'enabled': 'false', **form}, self.member)[1]
            code, locked, _ = self.request('/api/ml/effectiveness-cycle', {'type': 'LOTO_6_45', 'configurationHash': saved['settings']['configurationHash']}, self.member)
            self.assertEqual(code, 200, locked)
            locks.append(locked['cycleId'])
        report = self.request('/api/ml/effectiveness?type=LOTO_6_45', cookie=self.member)[1]
        self.assertEqual(report['billing']['balance'], 6440000)
        self.assertEqual(len(report['billing']['charges']), 2)
        expected = {}
        for cycle in report['cycles']:
            entry = cycle['methods']['web']
            schedule = entry['seedSchedule']
            page = self.request('/api/ml/effectiveness-tickets?type=LOTO_6_45&predictionId=' + entry['predictionId'] + '&page=2', cookie=self.member)[1]
            items = page.get('baoParents', page.get('tickets'))
            self.assertEqual(items[0]['ticketSeed'], seeds.derive(schedule, 11))
            expected[cycle['cycleId']] = seeds.derive(schedule, 1)
            request = urllib.request.Request(self.url + '/api/ml/effectiveness-export?type=LOTO_6_45&format=xlsx&cycleId=' + cycle['cycleId'], headers={'Cookie': self.member})
            with urllib.request.urlopen(request, timeout=25) as response:
                workbook = response.read()
            with zipfile.ZipFile(io.BytesIO(workbook)) as archive:
                sheet = ET.fromstring(archive.read('xl/worksheets/sheet2.xml'))
                overview = archive.read('xl/worksheets/sheet1.xml').decode('utf-8')
            rows = sheet.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheetData/{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row')
            self.assertEqual(len(rows), (11 if cycle['config']['playMode'] == 'bao' else 12) + 1)
            self.assertEqual([cell.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}is').find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t').text for cell in list(rows[0])[-2:]], ['Seed vé', 'Seed gốc'])
            self.assertIn(expected[cycle['cycleId']], ''.join(rows[1].itertext()))
            self.assertIn('Phiên bản seed vé', overview)
        browser = Browser(CHROME, self.work / 'ticket-seed-browser')
        def wait(expression):
            for _ in range(400):
                if browser.value(expression):
                    return
                time.sleep(.05)
            self.fail('Browser timeout: ' + expression + ' ' + str(browser.value('window.seedErrors')))
        try:
            browser.call('Page.enable', page=True)
            browser.call('Network.enable', page=True)
            browser.call('Emulation.setDeviceMetricsOverride', {'width': 1560, 'height': 1050, 'deviceScaleFactor': 1, 'mobile': False}, page=True)
            browser.call('Page.addScriptToEvaluateOnNewDocument', {'source': "window.seedErrors=[];window.seedCopies=[];addEventListener('error',e=>seedErrors.push(e.message));addEventListener('unhandledrejection',e=>seedErrors.push(String(e.reason)));Object.defineProperty(navigator,'clipboard',{value:{writeText:async value=>seedCopies.push(value)}});const oldSeedFetch=fetch;window.fetch=(input,options)=>{const url=new URL(typeof input==='string'?input:input.url,location.href);if(url.pathname.startsWith('/api/live-'))return Promise.resolve(new Response(JSON.stringify({ok:true,results:[],rows:[],history:[],meta:{}}),{headers:{'Content-Type':'application/json'}}));return oldSeedFetch(input,options)}"}, page=True)
            browser.call('Network.setCookie', {'name': 'LOTTO_AUTH', 'value': self.member.split('=', 1)[1].split(';', 1)[0], 'url': self.url}, page=True)
            browser.call('Page.navigate', {'url': self.url}, page=True)
            wait("!!window.VietlottEffectiveness && typeof currentUser!=='undefined' && currentUser==='member_fixture'")
            browser.value("document.getElementById('predictModeEffectivenessTab').click();document.getElementById('effectivenessType').value='LOTO_6_45';document.getElementById('effectivenessType').dispatchEvent(new Event('change'))")
            wait("document.querySelectorAll('.effectiveness-cycle').length===2 && !document.getElementById('effectivenessRefresh').disabled")
            for cycle in report['cycles']:
                selector = f'.effectiveness-cycle[data-effectiveness-state="LOTO_6_45:cycle:{cycle["cycleId"]}"]'
                browser.value(f"document.querySelector('{selector}').open=true")
                panel = selector + " .effectiveness-cycle-method[data-method='web']"
                wait(f'document.querySelectorAll(`{panel} [data-copy-ticket-seed]`).length===10')
                self.assertEqual(browser.value(f'document.querySelector(`{panel} [data-copy-ticket-seed]`).dataset.copyTicketSeed'), expected[cycle['cycleId']])
                browser.value(f'document.querySelector(`{panel} [data-copy-ticket-seed]`).click()')
                wait('window.seedCopies.length>0')
                self.assertEqual(browser.value('window.seedCopies.at(-1)'), expected[cycle['cycleId']])
                browser.value(f'document.querySelector(`{panel} [data-ticket-page="2"]`).click()')
                wait(f'document.querySelectorAll(`{panel} [data-copy-ticket-seed]`).length===' + ('1' if cycle['config']['playMode'] == 'bao' else '2'))
                self.assertEqual(browser.value(f'document.querySelector(`{panel} [data-copy-ticket-seed]`).dataset.copyTicketSeed'), seeds.derive(cycle['methods']['web']['seedSchedule'], 11))
            browser.value("document.getElementById('effectivenessRefresh').click()")
            wait("!document.getElementById('effectivenessRefresh').disabled")
            wait("[...document.querySelectorAll('.effectiveness-cycle-method')].filter(x=>x.getClientRects().length).every(x=>!x.querySelector('.effectiveness-bao-retry'))")
            for width in (390, 1560):
                browser.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 1050, 'deviceScaleFactor': 1, 'mobile': width == 390}, page=True)
                browser.value("document.querySelector('.effectiveness-cycle').scrollIntoView({block:'start'})")
                self.assertTrue(browser.value("document.documentElement.scrollWidth<=innerWidth+2"))
                self.assertTrue(browser.value("[...document.querySelectorAll('.effectiveness-cycle')].every(x=>x.scrollWidth<=x.clientWidth+1)"))
                (ROOT.parent / f'ticket-seeds-{width}.png').write_bytes(base64.b64decode(browser.call('Page.captureScreenshot', {'format': 'png'}, page=True)['data']))
            self.assertEqual(browser.value('window.seedErrors'), [])
        finally:
            browser.close()
        final = self.request('/api/ml/effectiveness?type=LOTO_6_45', cookie=self.member)[1]
        self.assertEqual(final['billing']['balance'], 6440000)
        self.assertEqual(len(final['billing']['charges']), 2)
        self.assertEqual(self.request('/api/ml/effectiveness?type=LOTO_6_45', cookie=self.admin)[1]['counts']['total'], 0)
