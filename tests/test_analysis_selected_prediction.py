"""Selected-number ticket constraints, diversity and read-only Analysis UI."""
import base64
import itertools
import json
import math
import subprocess
import time
import unittest
from pathlib import Path

from tests import test_analysis_frequency_web as frequency
from tests.browser_cdp import Browser
from tests.test_prize_web import ROOT, CHROME

NODE = 'C:/Program Files/nodejs/node.exe'


@unittest.skipUnless(Path(NODE).exists(), 'Node required')
class AnalysisTicketAlgorithmTests(unittest.TestCase):
    def test_domains_unique_combinations_coverage_and_bounded_large_pools(self):
        cases = []
        for type_key, size in [('LOTO_5_35', 5), ('LOTO_6_45', 6), ('LOTO_6_55', 6), ('MAX_3D', 2), ('MAX_3D_PRO', 2), ('KENO', 5)]:
            for count in range(size - 1, size + 4):
                for extras in ([[], ['01'], ['01', '02', '12']] if type_key in ('LOTO_5_35', 'LOTO_6_55') else [[]]):
                    width = 3 if type_key.startswith('MAX_3D') else 2
                    numbers = [str(n).zfill(width) for n in range(count)] if width == 3 else [str(n + 1).zfill(width) for n in range(count)]
                    cases.append(dict(type=type_key, main=numbers, special=extras, size=size))
        for type_key, count, size, extras in [('LOTO_5_35', 35, 5, ['01', '12']), ('KENO', 80, 10, []), ('KENO', 10, 1, []), ('MAX_3D', 1000, 2, []), ('LOTO_6_55', 55, 6, ['01', '02', '55'])]:
            width = 3 if type_key.startswith('MAX_3D') else 2
            numbers = [str(n).zfill(width) for n in range(count)] if width == 3 else [str(n + 1).zfill(width) for n in range(count)]
            cases.append(dict(type=type_key, main=numbers, special=extras, size=size))
        script = r'''
const fs=require('fs');
const core=fs.readFileSync('frontend/vietlott-web-core.js','utf8');
const stats=fs.readFileSync('frontend/vietlott-web-stats.js','utf8');
const typeStart=core.indexOf('const TYPES = {');
const typeCode=core.slice(typeStart,core.indexOf('\n    };',typeStart)+7);
const start=stats.indexOf('function buildAnalysisTickets(');
const code=stats.slice(start,stats.indexOf('function getAnalysisPredictionSelection()',start));
const cases=JSON.parse(fs.readFileSync(0,'utf8'));
const run=new Function('cases',typeCode+code+'return cases.map(c=>buildAnalysisTickets(c.type,c.main,c.special,c.size));');
console.log(JSON.stringify(run(cases)));
'''
        started = time.monotonic()
        result = subprocess.run([NODE, '-e', script], input=json.dumps(cases), capture_output=True, text=True, encoding='utf-8', cwd=ROOT, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(time.monotonic() - started, 15)
        for case, tickets in zip(cases, json.loads(result.stdout)):
            with self.subTest(case=case['type'], n=len(case['main']), extras=case['special']):
                n, size = len(case['main']), case['size']
                if case['type'] == 'LOTO_6_55':
                    possible = sum(math.comb(n - (extra in case['main']), size) if n - (extra in case['main']) >= size else 0 for extra in case['special'])
                else:
                    possible = (math.comb(n, size) if n >= size else 0) * (len(case['special']) if case['type'] == 'LOTO_5_35' else 1)
                self.assertEqual(len(tickets), min(5, possible))
                keys = set()
                for ticket in tickets:
                    self.assertEqual(len(ticket['main']), size)
                    self.assertEqual(len(set(ticket['main'])), size)
                    self.assertTrue(set(ticket['main']) <= set(case['main']))
                    self.assertEqual(ticket['main'], sorted(ticket['main'], key=int))
                    self.assertTrue(ticket['special'] in case['special'] if case['special'] else ticket['special'] == '')
                    if case['type'] == 'LOTO_6_55':
                        self.assertNotIn(ticket['special'], ticket['main'])
                    keys.add((tuple(ticket['main']), ticket['special']))
                self.assertEqual(len(keys), len(tickets))
                if tickets and case['type'] != 'LOTO_6_55':
                    self.assertEqual(len(set(itertools.chain.from_iterable(t['main'] for t in tickets))), min(n, len(tickets) * size))


    def test_capacity_all_unique_pages_and_large_space_random_access(self):
        cases = []
        specs = [('LOTO_5_35', 5, 5, ['01']), ('LOTO_5_35', 7, 5, ['01', '12']),
                 ('LOTO_6_45', 8, 6, []), ('LOTO_6_55', 8, 6, ['01', '09', '55']),
                 ('LOTO_6_55', 6, 6, ['01']), ('MAX_3D', 6, 2, []), ('MAX_3D_PRO', 6, 2, []),
                 ('KENO', 6, 3, []), ('KENO', 1, 1, []), ('KENO', 80, 10, []),
                 ('MAX_3D', 1000, 2, []), ('LOTO_6_55', 55, 6, [f'{n:02d}' for n in range(1, 56)])]
        for game, n, size, extras in specs:
            main = [f'{v:03d}' for v in range(n)] if game.startswith('MAX_3D') else [f'{v:02d}' for v in range(1, n + 1)]
            capacity = sum(math.comb(n - (e in main), size) if n - (e in main) >= size else 0 for e in extras) if game == 'LOTO_6_55' else math.comb(n, size) * (len(extras) if game == 'LOTO_5_35' else 1)
            cases.append(dict(type=game, main=main, special=extras, size=size, capacity=str(capacity)))
        script = r"""
const fs=require('fs'),core=fs.readFileSync('frontend/vietlott-web-core.js','utf8'),stats=fs.readFileSync('frontend/vietlott-web-stats.js','utf8');
const t=core.indexOf('const TYPES = {'),typeCode=core.slice(t,core.indexOf('\n    };',t)+7);
const a=stats.indexOf('function buildAnalysisTickets('),code=stats.slice(a,stats.indexOf('function getAnalysisPredictionSelection()',a));
const run=new Function('cases',typeCode+code+`return cases.map(c=>{
 const capacity=getAnalysisTicketCapacity(c.type,c.main,c.special,c.size), plan=createAnalysisPredictionPlan(c.type,c.main,c.special,c.size,c.capacity);
 let tickets=[];
 if(plan){if(capacity<200n){for(let offset=0n;offset<capacity;offset+=6n)tickets.push(...getAnalysisTicketPage(plan,offset));}
 else tickets=[...getAnalysisTicketPage(plan),...getAnalysisTicketPage(plan,capacity-6n)];}
 return {capacity:String(capacity),tickets,hasPlan:!!plan,
 highRejected:createAnalysisPredictionPlan(c.type,c.main,c.special,c.size,String(capacity+1n))===null,
 zeroRejected:createAnalysisPredictionPlan(c.type,c.main,c.special,c.size,'0')===null};});`);
console.log(JSON.stringify(run(JSON.parse(fs.readFileSync(0,'utf8')))));
"""
        started = time.monotonic()
        result = subprocess.run([NODE, '-e', script], input=json.dumps(cases), capture_output=True, text=True, encoding='utf-8', cwd=ROOT, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(time.monotonic() - started, 10)
        for case, actual in zip(cases, json.loads(result.stdout)):
            with self.subTest(game=case['type'], capacity=case['capacity']):
                capacity = int(case['capacity'])
                self.assertEqual(actual['capacity'], case['capacity'])
                self.assertEqual(actual['hasPlan'], capacity > 0)
                self.assertTrue(actual['highRejected'] and actual['zeroRejected'])
                tickets = actual['tickets']
                self.assertEqual(len(tickets), capacity if capacity < 200 else 12)
                self.assertEqual(len({(tuple(t['main']), t['special']) for t in tickets}), len(tickets))
                for ticket in tickets:
                    self.assertEqual(len(ticket['main']), case['size'])
                    self.assertEqual(len(set(ticket['main'])), case['size'])
                    self.assertTrue(set(ticket['main']) <= set(case['main']))
                    self.assertEqual(ticket['main'], sorted(ticket['main'], key=int))
                    if case['special']:
                        self.assertIn(ticket['special'], case['special'])
                    else:
                        self.assertEqual(ticket['special'], '')
                    if case['type'] == 'LOTO_6_55':
                        self.assertNotIn(ticket['special'], ticket['main'])


    def test_bao_levels_capacity_parent_domains_and_six_per_page(self):
        script = r"""
const fs=require('fs'),core=fs.readFileSync('frontend/vietlott-web-core.js','utf8'),stats=fs.readFileSync('frontend/vietlott-web-stats.js','utf8');
const t=core.indexOf('const TYPES = {'),b=core.indexOf('const PREDICT_BAO_LEVELS = {');
const config=core.slice(t,core.indexOf('\n    };',t)+7)+core.slice(b,core.indexOf('\n    };',b)+7)+'function getPredictBaoLevels(t){return PREDICT_BAO_LEVELS[t]||[]}';
const a=stats.indexOf('function buildAnalysisTickets('),code=stats.slice(a,stats.indexOf('function getAnalysisPredictionSelection()',a));
const run=new Function(config+code+`return Object.entries(PREDICT_BAO_LEVELS).flatMap(([type,levels])=>levels.map(size=>{
 const main=Array.from({length:size+2},(_,i)=>String(i+1).padStart(2,'0')),special=['01','12'];
 const capacity=getAnalysisTicketCapacity(type,main,special,size,'bao');
 const plan=createAnalysisPredictionPlan(type,main,special,size,String(capacity),'bao');
 const tickets=[];for(let offset=0n;offset<capacity;offset+=6n)tickets.push(...getAnalysisTicketPage(plan,offset));
 return {type,size,main,special,capacity:String(capacity),tickets,firstPage:getAnalysisTicketPage(plan).length,
 invalidMode:getAnalysisTicketCapacity(type,main,special,size,'invalid')===0n,
 badSize:getAnalysisTicketCapacity(type,main,special,TYPES[type].mainCount,'bao')===0n,
 noExtra:String(getAnalysisTicketCapacity(type,main,[],size,'bao'))};}));`);
console.log(JSON.stringify(run()));
"""
        result = subprocess.run([NODE, '-e', script], capture_output=True, text=True, encoding='utf-8', cwd=ROOT, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        for row in json.loads(result.stdout):
            with self.subTest(game=row['type'], level=row['size']):
                expected = math.comb(len(row['main']), row['size']) * (2 if row['type'] == 'LOTO_5_35' else 1)
                self.assertEqual(int(row['capacity']), expected)
                self.assertEqual(len(row['tickets']), expected)
                self.assertEqual(row['firstPage'], min(6, expected))
                self.assertEqual(len({(tuple(t['main']), t['special']) for t in row['tickets']}), expected)
                self.assertTrue(row['badSize'] and row['invalidMode'])
                self.assertEqual(int(row['noExtra']), 0 if row['type'] == 'LOTO_5_35' else expected)
                for ticket in row['tickets']:
                    self.assertEqual(len(ticket['main']), row['size'])
                    self.assertTrue(set(ticket['main']) <= set(row['main']))
                    self.assertEqual(ticket['special'] in row['special'] if row['type'] == 'LOTO_5_35' else ticket['special'] == '', True)


@unittest.skipUnless(Path(CHROME).exists(), 'Chrome required')
class AnalysisSelectedPredictionWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frequency.AnalysisFrequencyWebTests.setUpClass.__func__(cls)
        (cls.work / 'data/canonical/keno_all_day.csv').write_text(
            'Kỳ,Ngày,Giờ,Bộ Số\n1,01/01/2026,18:00,"' + ','.join(map(str, range(1, 21))) + '"\n', encoding='utf-8')

    tearDownClass = classmethod(frequency.AnalysisFrequencyWebTests.tearDownClass.__func__)
    start_server = classmethod(frequency.AnalysisFrequencyWebTests.start_server.__func__)
    request = classmethod(frequency.AnalysisFrequencyWebTests.request.__func__)
    login = classmethod(frequency.AnalysisFrequencyWebTests.login.__func__)

    def test_selected_panel_predictions_persistence_and_themes(self):
        browser = Browser(CHROME, self.work / 'selected-prediction-browser')
        self.addCleanup(browser.close)
        browser.call('Network.enable', page=True)
        browser.call('Network.setCookie', dict(name='LOTTO_AUTH', value=self.admin.split(';')[0].split('=', 1)[1], url=self.url), page=True)
        browser.call('Emulation.setDeviceMetricsOverride', dict(width=1440, height=1100, deviceScaleFactor=1, mobile=False), page=True)
        browser.call('Page.navigate', dict(url=self.url + '/'), page=True)

        def wait(expression):
            for _ in range(300):
                if browser.value(expression):
                    return
                time.sleep(.05)
            self.fail('Selected prediction timeout: ' + expression)

        def pick(number, group='main'):
            browser.value(f"document.querySelector('[data-pick-group={group}][data-frequency-pick=\"{number}\"]').click()")

        wait("typeof currentUser==='string' && currentUser==='owner_fixture' && document.getElementById('appShell').style.display==='block'")
        browser.value("document.getElementById('predictModeAnalysisTab').click()")
        wait("!analysisState.loading && !!document.getElementById('analysisPredictSelectedBtn')")
        self.assertTrue(browser.value("document.getElementById('analysisPredictSelectedBtn').disabled"))
        browser.value("window.predictionFetch=window.fetch;window.predictionApiCalls=0;window.predictionWrites=0;window.fetch=(...args)=>{if(String(args[0]).includes('/api/analysis?'))predictionApiCalls++;if(String(args[1]?.method||'GET').toUpperCase()!=='GET')predictionWrites++;return predictionFetch(...args)}")
        for number in ['09', '04', '11', '01', '05', '06', '07']:
            pick(number)
        self.assertTrue(browser.value("document.getElementById('analysisPredictSelectedBtn').disabled"))
        for number in ['03', '02']:
            pick(number, 'special')
        self.assertEqual(browser.value("[...document.querySelectorAll('[data-selected-group=main] .frequency-selected-number')].map(e=>e.lastChild.textContent)"), ['09', '04', '11', '01', '05', '06', '07'])
        self.assertFalse(browser.value("document.getElementById('analysisPredictSelectedBtn').disabled"))
        self.assertEqual(browser.value("document.getElementById('analysisPredictionCapacity').dataset.capacity"), '42')
        saved = browser.value("localStorage.getItem(analysisMarksStorageKey())")
        browser.value("document.getElementById('analysisPredictSelectedBtn').click();if(document.getElementById('analysisPredictionCountInput')){const input=document.getElementById('analysisPredictionCountInput');input.value='5';input.dispatchEvent(new Event('input'));document.getElementById('analysisPredictionCountConfirm').click()}")
        tickets = browser.value('analysisState.predictionTickets')
        self.assertEqual(len(tickets), 5)
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-ticket').length"), 5)
        self.assertIn('Phủ 7/7', browser.value("document.querySelector('.frequency-ticket-summary').textContent"))
        self.assertEqual(browser.value("localStorage.getItem(analysisMarksStorageKey())"), saved)
        self.assertEqual(browser.value('predictionApiCalls'), 0)
        self.assertEqual(browser.value('predictionWrites'), 0)
        # Opening/canceling preserves old results; values stay exact until they exceed capacity.
        browser.value("document.getElementById('analysisPredictSelectedBtn').click()")
        self.assertTrue(browser.value("!!document.getElementById('analysisPredictionCountInput')"))
        browser.value("document.getElementById('analysisPredictionCountCancel').click()")
        self.assertEqual(browser.value('analysisState.predictionTickets'), tickets)
        browser.value("document.getElementById('analysisPredictSelectedBtn').click();document.getElementById('analysisPredictionCountInput').value='0';document.getElementById('analysisPredictionCountInput').dispatchEvent(new Event('input'));document.getElementById('analysisPredictionCountConfirm').click()")
        self.assertTrue(browser.value("!!document.getElementById('analysisPredictionCountInput')"))
        self.assertEqual(browser.value('analysisState.predictionTickets'), tickets)
        browser.value("document.getElementById('analysisPredictionCountInput').value='999';document.getElementById('analysisPredictionCountInput').dispatchEvent(new Event('input'))")
        self.assertEqual(browser.value("document.getElementById('analysisPredictionCountInput').value"), '42')
        browser.value("document.getElementById('analysisPredictionCountInput').value='12';document.getElementById('analysisPredictionCountInput').dispatchEvent(new Event('input'))")
        self.assertEqual(browser.value("document.getElementById('analysisPredictionCountInput').value"), '12')
        quantity_evidence = ROOT / 'runtime/logs/prediction_bao_six_20261118'
        quantity_evidence.mkdir(parents=True, exist_ok=True)
        for width, light in [(1440, False), (320, True)]:
            browser.call('Emulation.setDeviceMetricsOverride', dict(width=width, height=900, deviceScaleFactor=1, mobile=width < 500), page=True)
            browser.value(f"document.body.classList.toggle('light-theme',{str(light).lower()});document.getElementById('analysisPredictionCountForm').scrollIntoView({{block:'center'}})")
            self.assertTrue(browser.value("(()=>{const r=document.getElementById('analysisPredictionCountForm').getBoundingClientRect();return r.left>=0 && r.right<=innerWidth})()"))
            shot = browser.call('Page.captureScreenshot', dict(format='png'), page=True)
            (quantity_evidence / f'quantity-form-{width}.png').write_bytes(base64.b64decode(shot['data']))
        browser.value("document.getElementById('analysisPredictionCountConfirm').click()")
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-ticket').length"), 6)
        browser.value("document.getElementById('analysisPredictSelectedBtn').click();document.getElementById('analysisPredictionCountInput').value='42';document.getElementById('analysisPredictionCountInput').dispatchEvent(new Event('input'));document.getElementById('analysisPredictionCountConfirm').click()")
        all_tickets = []
        for page in range(7):
            self.assertEqual(browser.value('analysisState.predictionPage'), page)
            all_tickets.extend(browser.value('analysisState.predictionTickets'))
            if page < 6:
                browser.value("document.querySelector('[data-analysis-ticket-page=next]').click()")
        self.assertEqual(len(all_tickets), 42)
        self.assertEqual(len({(tuple(t['main']), t['special']) for t in all_tickets}), 42)
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-ticket').length"), 6)
        self.assertTrue(browser.value("document.querySelector('[data-analysis-ticket-page=next]').disabled"))
        browser.value("document.querySelector('[data-analysis-ticket-page=first]').click();document.querySelector('[data-analysis-ticket-page=last]').click()")
        self.assertEqual(browser.value('analysisState.predictionPage'), 6)
        browser.value("document.querySelector('.frequency-ticket-pages').scrollIntoView({block:'center'})")
        shot = browser.call('Page.captureScreenshot', dict(format='png'), page=True)
        (quantity_evidence / 'quantity-last-page-320.png').write_bytes(base64.b64decode(shot['data']))
        browser.value("document.getElementById('analysisPredictSelectedBtn').click();document.getElementById('analysisPredictionCountInput').value='5';document.getElementById('analysisPredictionCountInput').dispatchEvent(new Event('input'));document.getElementById('analysisPredictionCountConfirm').click()")
        self.assertEqual(browser.value('analysisState.predictionTickets'), tickets)
        self.assertEqual(browser.value('predictionApiCalls'), 0)
        self.assertEqual(browser.value('predictionWrites'), 0)

        # Bao and ordinary tickets share chosen numbers, but have separate capacities/results.
        marks_before_bao = browser.value('JSON.stringify(analysisState.marksByType)')
        browser.value("document.getElementById('analysisPredictionMode').value='bao';document.getElementById('analysisPredictionMode').dispatchEvent(new Event('change'))")
        self.assertEqual(browser.value("document.getElementById('analysisPredictionCapacity').dataset.capacity"), '14')
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-ticket').length"), 0)
        browser.value("document.getElementById('analysisPredictSelectedBtn').click();document.getElementById('analysisPredictionCountInput').value='14';document.getElementById('analysisPredictionCountConfirm').click()")
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-ticket').length"), 6)
        self.assertTrue(browser.value("analysisState.predictionTickets.every(t=>t.main.length===6 && ['02','03'].includes(t.special))"))
        self.assertIn('Bao 6', browser.value("document.querySelector('.frequency-ticket-label').textContent"))
        for width, light in [(1440, False), (320, True)]:
            browser.call('Emulation.setDeviceMetricsOverride', dict(width=width, height=1100, deviceScaleFactor=1, mobile=False), page=True)
            browser.value(f"document.body.classList.toggle('light-theme',{str(light).lower()});document.querySelector('.frequency-selection').scrollIntoView({{block:'start'}})")
            self.assertTrue(browser.value("(()=>{const p=document.querySelector('.frequency-predict-actions').getBoundingClientRect();return [...document.querySelectorAll('.frequency-predict-actions select,.frequency-predict-actions button')].every(e=>{const r=e.getBoundingClientRect();return r.left>=p.left && r.right<=p.right+.5})})()"))
            self.assertTrue(browser.value("(()=>{const a=[...document.querySelectorAll('.frequency-ticket-pages > *')].map(e=>{const r=e.getBoundingClientRect();return r.top+r.height/2});return Math.max(...a)-Math.min(...a)<1})()"))
            shot=browser.call('Page.captureScreenshot', dict(format='png'), page=True)
            (quantity_evidence / f'bao-six-{width}.png').write_bytes(base64.b64decode(shot['data']))
        browser.value("document.getElementById('analysisPredictionBaoLevel').value='4';document.getElementById('analysisPredictionBaoLevel').dispatchEvent(new Event('change'))")
        self.assertEqual(browser.value("document.getElementById('analysisPredictionCapacity').dataset.capacity"), '70')
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-ticket').length"), 0)
        self.assertIn('ghép thêm 1 số', browser.value("document.querySelector('.frequency-selection').textContent"))
        browser.value("document.getElementById('analysisPredictionBaoLevel').value='15';document.getElementById('analysisPredictionBaoLevel').dispatchEvent(new Event('change'))")
        self.assertTrue(browser.value("document.getElementById('analysisPredictSelectedBtn').disabled"))
        browser.value("document.getElementById('analysisPredictionMode').value='normal';document.getElementById('analysisPredictionMode').dispatchEvent(new Event('change'));document.getElementById('analysisPredictSelectedBtn').click();document.getElementById('analysisPredictionCountInput').value='5';document.getElementById('analysisPredictionCountConfirm').click()")
        self.assertEqual(browser.value('JSON.stringify(analysisState.marksByType)'), marks_before_bao)
        self.assertEqual(browser.value('analysisState.predictionTickets'), tickets)

        browser.value("document.querySelector('[data-sort-group=main]').click()")
        self.assertEqual(browser.value('analysisState.predictionTickets'), tickets)
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-ticket').length"), 5)
        browser.call('Emulation.setDeviceMetricsOverride', dict(width=1440, height=1100, deviceScaleFactor=1, mobile=False), page=True)
        browser.value("document.body.classList.remove('light-theme')")
        self.assertTrue(browser.value("(()=>{const p=document.querySelector('.frequency-selection').getBoundingClientRect(),s=document.querySelector('[data-frequency-group=special]').getBoundingClientRect(),m=document.querySelector('[data-frequency-group=main]').getBoundingClientRect();return p.left>=m.right && p.top>=s.bottom})()"))
        evidence = ROOT / 'runtime/logs/prediction_bao_six_20261118'
        evidence.mkdir(parents=True, exist_ok=True)
        for width, theme in [(1440, 'dark'), (1440, 'light'), (390, 'dark'), (320, 'dark'), (320, 'light')]:
            browser.call('Emulation.setDeviceMetricsOverride', dict(width=width, height=1100, deviceScaleFactor=1, mobile=width < 500), page=True)
            browser.value(f"document.body.classList.toggle('light-theme',{str(theme=='light').lower()});document.querySelector('.frequency-selection').scrollIntoView({{block:'center'}})")
            metrics = browser.value("(()=>{const p=document.querySelector('.frequency-selection'),r=p.getBoundingClientRect();return {left:r.left,right:r.right,width:innerWidth,scroll:p.scrollWidth,client:p.clientWidth,body:document.documentElement.scrollWidth}})()")
            self.assertGreaterEqual(metrics['left'], 0, metrics)
            self.assertLessEqual(metrics['right'], width, metrics)
            self.assertLessEqual(metrics['scroll'], metrics['client'] + 1, metrics)
            self.assertLessEqual(metrics['body'], width + 1, metrics)
            image = browser.call('Page.captureScreenshot', dict(format='png'), page=True)
            (evidence / f'selected-{theme}-{width}.png').write_bytes(base64.b64decode(image['data']))
        pick('11')
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-ticket').length"), 0)
        self.assertEqual(browser.value('analysisState.predictionTickets'), [])
        browser.value("document.getElementById('analysisPredictSelectedBtn').click();if(document.getElementById('analysisPredictionCountInput')){const input=document.getElementById('analysisPredictionCountInput');input.value='5';input.dispatchEvent(new Event('input'));document.getElementById('analysisPredictionCountConfirm').click()}")
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-ticket').length"), 5)
        browser.call('Page.reload', dict(ignoreCache=True), page=True)
        wait("typeof currentUser==='string' && currentUser==='owner_fixture' && document.getElementById('appShell').style.display==='block'")
        browser.value("document.getElementById('predictModeAnalysisTab').click()")
        wait("!analysisState.loading && !!document.getElementById('analysisPredictSelectedBtn')")
        self.assertEqual(browser.value('getAnalysisMarks().length'), 6)
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-ticket').length"), 0)
        pick('06')
        pick('02', 'special')
        browser.value("document.getElementById('analysisPredictSelectedBtn').click();if(document.getElementById('analysisPredictionCountInput')){const input=document.getElementById('analysisPredictionCountInput');input.value='5';input.dispatchEvent(new Event('input'));document.getElementById('analysisPredictionCountConfirm').click()}")
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-ticket').length"), 1)
        browser.value("document.getElementById('analysisTypeSelect').value='LOTO_6_45';document.getElementById('analysisTypeSelect').dispatchEvent(new Event('change'))")
        wait("!analysisState.loading && !!document.querySelector('[data-frequency-group=main] tr[data-number=\"45\"]')")
        self.assertEqual(browser.value("document.querySelectorAll('[data-selected-group=special]').length"), 0)
        self.assertTrue(browser.value("document.getElementById('analysisPredictSelectedBtn').disabled"))
        for number in range(1, 9):
            pick(f'{number:02d}')
        browser.value("document.getElementById('analysisPredictSelectedBtn').click();if(document.getElementById('analysisPredictionCountInput')){const input=document.getElementById('analysisPredictionCountInput');input.value='5';input.dispatchEvent(new Event('input'));document.getElementById('analysisPredictionCountConfirm').click()}")
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-ticket').length"), 5)
        self.assertTrue(browser.value("analysisState.predictionTickets.every(t=>t.main.length===6 && t.special==='')"))
        browser.value("document.getElementById('analysisTypeSelect').value='LOTO_6_55';document.getElementById('analysisTypeSelect').dispatchEvent(new Event('change'))")
        wait("!analysisState.loading && !!document.querySelector('[data-frequency-group=main] tr[data-number=\"55\"]')")
        for number in range(1, 7):
            pick(f'{number:02d}')
        pick('01', 'special')
        self.assertTrue(browser.value("document.getElementById('analysisPredictSelectedBtn').disabled"))
        pick('07', 'special')
        browser.value("document.getElementById('analysisPredictSelectedBtn').click();if(document.getElementById('analysisPredictionCountInput')){const input=document.getElementById('analysisPredictionCountInput');input.value='5';input.dispatchEvent(new Event('input'));document.getElementById('analysisPredictionCountConfirm').click()}")
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-ticket').length"), 1)
        self.assertEqual(browser.value('analysisState.predictionTickets[0].special'), '07')
        browser.value("document.getElementById('analysisPredictionMode').value='bao';document.getElementById('analysisPredictionMode').dispatchEvent(new Event('change'));document.getElementById('analysisPredictionBaoLevel').value='5';document.getElementById('analysisPredictionBaoLevel').dispatchEvent(new Event('change'))")
        pick('01', 'special')
        pick('07', 'special')
        self.assertEqual(browser.value("document.getElementById('analysisPredictionCapacity').dataset.capacity"), '6')
        browser.value("document.getElementById('analysisPredictSelectedBtn').click();document.getElementById('analysisPredictionCountInput').value='6';document.getElementById('analysisPredictionCountConfirm').click()")
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-ticket').length"), 6)
        self.assertTrue(browser.value("analysisState.predictionTickets.every(t=>t.main.length===5 && t.special==='')"))
        browser.value("document.getElementById('analysisTypeSelect').value='KENO';document.getElementById('analysisTypeSelect').dispatchEvent(new Event('change'))")
        wait("!analysisState.loading && !!document.getElementById('analysisPredictionKenoSize')")
        self.assertIsNone(browser.value("document.getElementById('analysisPredictionMode')"))
        for number in range(1, 7):
            pick(f'{number:02d}')
        browser.value("document.getElementById('analysisPredictionKenoSize').value='3';document.getElementById('analysisPredictionKenoSize').dispatchEvent(new Event('change'));document.getElementById('analysisPredictSelectedBtn').click();if(document.getElementById('analysisPredictionCountInput')){const input=document.getElementById('analysisPredictionCountInput');input.value='5';input.dispatchEvent(new Event('input'));document.getElementById('analysisPredictionCountConfirm').click()}")
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-ticket').length"), 5)
        self.assertTrue(browser.value("analysisState.predictionTickets.every(t=>t.main.length===3 && t.special==='')"))
        browser.value("document.getElementById('analysisPredictionKenoSize').value='10';document.getElementById('analysisPredictionKenoSize').dispatchEvent(new Event('change'))")
        self.assertTrue(browser.value("document.getElementById('analysisPredictSelectedBtn').disabled"))
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-ticket').length"), 0)
        browser.value("window.predictionOwner=currentAccountId;currentAccountId=currentAccountId==='100000000001'?'100000000002':'100000000001';renderAnalysis()")
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-selected-number').length"), 0)
        self.assertTrue(browser.value("document.getElementById('analysisPredictSelectedBtn').disabled"))
        browser.value("currentAccountId=predictionOwner;renderAnalysis()")
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-selected-number').length"), 6)
        browser.value("document.getElementById('analysisPredictSelectedBtn').click();if(document.getElementById('analysisPredictionCountInput')){const input=document.getElementById('analysisPredictionCountInput');input.value='5';input.dispatchEvent(new Event('input'));document.getElementById('analysisPredictionCountConfirm').click()};resetAnalysisSession()")
        self.assertEqual(browser.value('analysisState.predictionTickets'), [])
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-selection').length"), 0)


if __name__ == '__main__':
    unittest.main()
