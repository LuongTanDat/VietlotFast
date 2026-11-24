"""Real Java -> Python frequency endpoint and responsive Analysis tab."""
import base64
import json
import shutil
import time
import unittest
from pathlib import Path

from tests import test_account_balances as fixtures
from tests.browser_cdp import Browser
from tests.test_analysis import SAMPLE_LOTO_535
from tests.test_analysis_frequency import frequency_draw_fixture
from tests.test_prize_web import ROOT, CHROME


class AnalysisFrequencyWebTests(unittest.TestCase):
    tearDownClass = classmethod(fixtures.AccountBalanceTests.tearDownClass.__func__)
    start_server = classmethod(fixtures.AccountBalanceTests.start_server.__func__)
    request = classmethod(fixtures.AccountBalanceTests.request.__func__)
    login = classmethod(fixtures.AccountBalanceTests.login.__func__)

    @classmethod
    def setUpClass(cls):
        fixtures.AccountBalanceTests.setUpClass.__func__(cls)
        (cls.work / 'ai').mkdir()
        for name in ['analysis', 'configs']:
            shutil.copytree(ROOT / 'ai' / name, cls.work / 'ai' / name,
                            ignore=shutil.ignore_patterns('__pycache__'))
        canonical = cls.work / 'data/canonical'
        canonical.mkdir(parents=True)
        (canonical / 'loto_5_35_all_day.csv').write_text(SAMPLE_LOTO_535, encoding='utf-8')
        (canonical / 'mega_6_45_all_day.csv').write_text(SAMPLE_LOTO_535, encoding='utf-8')
        (canonical / 'power_6_55_all_day.csv').write_text(frequency_draw_fixture(type_key='LOTO_6_55'), encoding='utf-8')

    def test_authenticated_endpoint_has_full_tables_and_correct_denominators(self):
        self.assertEqual(self.request('/api/analysis?type=LOTO_5_35&mode=frequency&period=all')[0], 401)
        code, data, _ = self.request('/api/analysis?type=LOTO_5_35&mode=frequency&period=all', cookie=self.admin)
        self.assertEqual(code, 200, data)
        self.assertEqual(data['mode'], 'frequency')
        self.assertEqual(len(data['data']['main']['items']), 35)
        self.assertEqual(len(data['data']['special']['items']), 12)
        self.assertEqual(data['data']['main']['totalOccurrences'], 25)
        self.assertEqual(data['data']['special']['totalOccurrences'], 5)

    def test_draw_count_bridge_presets_custom_and_invalid_counts(self):
        for count in [10, 30, 50, 80, 100, 7, 150, 2147483647]:
            with self.subTest(count=count):
                code, data, _ = self.request(f'/api/analysis?type=LOTO_6_55&mode=frequency&drawCount={count}', cookie=self.admin)
                self.assertEqual(code, 200, data)
                self.assertTrue(data['ok'], data)
                self.assertEqual(data['requestedDrawCount'], count)
                self.assertEqual(data['availableDraws'], 120)
                self.assertEqual(data['totalDraws'], min(count, 120))
                self.assertEqual(data['data']['main']['totalOccurrences'], min(count, 120) * 6)
                self.assertEqual(data['data']['special']['totalOccurrences'], min(count, 120))
        for value in ['', '0', '-1', '1.5', 'abc', '2147483648']:
            with self.subTest(invalid=value):
                self.assertEqual(self.request('/api/analysis?type=LOTO_5_35&mode=frequency&drawCount=' + value, cookie=self.admin)[0], 400)

    @unittest.skipUnless(Path(CHROME).exists(), 'Chrome required')
    def test_browser_tables_filters_errors_stale_response_and_mobile(self):
        browser = Browser(CHROME, self.work / 'frequency-browser')
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
            self.fail('Frequency UI timeout: ' + expression + '; ' + str(browser.value("document.getElementById('analysisStatus').textContent")))

        wait("typeof currentUser==='string' && currentUser==='owner_fixture' && document.getElementById('appShell').style.display==='block'")
        browser.value("document.getElementById('predictModeAnalysisTab').click()")
        wait("document.querySelectorAll('[data-frequency-group=main] tbody tr').length===35")
        self.assertEqual(browser.value("document.querySelectorAll('[data-frequency-group=special] tbody tr').length"), 12)
        self.assertEqual(browser.value("getComputedStyle(document.querySelector('[data-frequency-group=main] .frequency-fill')).backgroundColor"), 'rgb(17, 147, 71)')
        self.assertEqual(browser.value("getComputedStyle(document.querySelector('[data-frequency-group=special] .frequency-fill')).backgroundColor"), 'rgb(243, 128, 50)')
        self.assertEqual(browser.value("getComputedStyle(document.querySelector('.frequency-table')).backgroundColor"), 'rgb(12, 27, 41)')
        self.assertEqual(browser.value("document.querySelector('[data-frequency-group=main] tbody tr .frequency-percent').textContent"), '16.00%')
        self.assertEqual(browser.value("document.querySelector('[data-frequency-group=special] tbody tr .frequency-percent').textContent"), '60.00%')
        self.assertEqual(browser.value("document.querySelector('[data-frequency-group=main] tr[data-number=\"35\"] .frequency-count').textContent"), '0 lượt')
        self.assertTrue(browser.value("!document.getElementById('analysisModeSelect') && !document.getElementById('analysisSummaryCards') && !document.getElementById('analysisSaveBtn')"))
        self.assertFalse(browser.value("!!document.getElementById('bootErrorBanner')"))
        self.assertEqual(browser.value("[...document.getElementById('analysisDrawCountSelect').options].map(option=>option.value)"), ['10', '30', '50', '80', '100', 'all', 'custom', 'dates'])
        self.assertEqual(browser.value("document.querySelector('#analysisDrawCountSelect option[value=all]').textContent"), 'Tất cả')
        self.assertTrue(browser.value("document.getElementById('analysisScope').textContent.startsWith('5 / 30 kỳ gần nhất')"))
        self.assertLess(browser.value("document.getElementById('analysisRefreshBtn').getBoundingClientRect().width"), 200)

        code, payload, _ = self.request('/api/analysis?type=LOTO_5_35&mode=frequency&drawCount=30', cookie=self.admin)
        self.assertEqual(code, 200)
        marked = "[...document.querySelectorAll('[data-frequency-group=main] tbody tr')].filter(r=>r.querySelector('.frequency-latest-mark')).map(r=>r.dataset.number).sort()"
        self.assertEqual(browser.value(marked), sorted(set(payload['latestDraw']['numbers'])))
        self.assertEqual(browser.value("document.querySelector('[data-frequency-group=special] .frequency-latest-mark').closest('tr').dataset.number"), payload['latestDraw']['special'])
        previous_marked = "[...document.querySelectorAll('[data-frequency-group=main] .frequency-previous-mark')].map(e=>e.closest('tr').dataset.number).sort()"
        self.assertEqual(browser.value(previous_marked), sorted(set(payload['previousDraw']['numbers'])))
        self.assertEqual(browser.value("document.querySelector('[data-frequency-group=special] .frequency-previous-mark').closest('tr').dataset.number"), payload['previousDraw']['special'])
        self.assertEqual(browser.value("[...document.querySelectorAll('[data-frequency-group=main] .frequency-marker-heading')].map(e=>e.textContent)"), ['Hiện Tại', 'Kỳ Trước', 'Chọn'])
        self.assertEqual(browser.value("document.querySelector('[data-frequency-group=main] tbody tr').cells.length"), 10)
        self.assertEqual(browser.value("[...document.querySelectorAll('[data-frequency-group=main] .frequency-delay-heading')].map(e=>e.textContent)"), ['Độ Trễ', 'Trễ Trung Bình'])
        self.assertEqual(browser.value("document.querySelector('[data-frequency-group=main] tr[data-number=\"35\"] .frequency-delay').textContent"), '≥5')
        self.assertEqual(browser.value("document.querySelector('[data-frequency-group=main] tr[data-number=\"35\"] .frequency-average-delay').textContent"), '—')
        self.assertEqual(browser.value("document.querySelector('[data-frequency-group=main] tr[data-number=\"04\"] .frequency-average-delay').textContent"), '1')
        self.assertEqual(browser.value("document.querySelector('[data-frequency-group=special] tr[data-number=\"01\"] .frequency-average-delay').textContent"), '1')
        self.assertEqual(browser.value("document.querySelector('[data-frequency-group=main] .frequency-streak-heading').textContent"), 'Chuỗi')
        streak_cases = [(5, 4, 0), (5, 5, 1), (5, 9, 1), (5, 10, 2), (5, 15, 3),
                        (5.96, 5, 0), (5.96, 6, 1), (5.96, 11, 1), (5.96, 12, 2), (5.96, 17, 2), (5.96, 18, 3),
                        (6.55, 13, 1), (6.55, 14, 2), (.2, 1, 5), (1.005, 2, 1), (.01, 12, 1200), (0, 9, 0), (None, 9, 0)]
        for average, delay, expected in streak_cases:
            with self.subTest(average=average, delay=delay):
                row = dict(number='01', averageDelay=average, currentDelay=delay, delayLowerBound=False)
                self.assertEqual(browser.value(f'getAnalysisStreak({json.dumps(row)})'), expected)
        self.assertEqual(browser.value("getAnalysisStreak({currentDelay:20,averageDelay:5,delayLowerBound:true})"), 0)
        states = [
            (5.96, 4, None), (5.96, 5, dict(color='green', level=1)),
            (5.96, 6, dict(color='red', level=1)), (5.96, 11, dict(color='red', level=1)),
            (5.96, 12, dict(color='red', level=2)), (0, 5, None), (None, 5, None),
        ]
        for average, delay, expected in states:
            row = dict(number='01', averageDelay=average, currentDelay=delay, delayLowerBound=False)
            self.assertEqual(browser.value(f'getAnalysisStreakState({json.dumps(row)})'), expected)
        gray = dict(number='01', currentDelay=0, averageDelay=4, delayLowerBound=False,
                    previousDelay=7, previousAverageDelay=1)
        self.assertEqual(browser.value(f'getAnalysisStreakState({json.dumps(gray)})'), dict(color='gray', level=7))
        for changes in [dict(previousAverageDelay=None), dict(previousDelay=None),
                        dict(previousAverageDelay=0), dict(previousDelay=0), dict(currentDelay=1)]:
            row = {**gray, **changes}
            self.assertIsNone(browser.value(f'getAnalysisStreakState({json.dumps(row)})'))
        self.assertIsNone(browser.value("getAnalysisStreakState({currentDelay:5,averageDelay:5.96,delayLowerBound:true})"))
        self.assertTrue(browser.value("(()=>{const h=renderAnalysisStreak({number:'01',currentDelay:6,averageDelay:5.96,delayLowerBound:false},'main');const t=document.createElement('div');t.innerHTML=h;return t.querySelector('[data-streak=\"1\"]')!==null && t.querySelector('text')===null})()"))
        self.assertTrue(browser.value("(()=>{const h=renderAnalysisStreak({number:'01',currentDelay:12,averageDelay:5.96,delayLowerBound:false},'special');const t=document.createElement('div');t.innerHTML=h;return t.querySelector('[data-streak=\"2\"] text')?.textContent==='2' && t.querySelector('[role=img]').getAttribute('aria-label').includes('2 lần')})()"))
        browser.value("window.frequencySavedPayload=analysisState.lastPayload;renderAnalysis({...frequencySavedPayload,previousDraw:null})")
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-previous-mark').length"), 0)
        browser.value("renderAnalysis(frequencySavedPayload)")

        def pick(number, group='main'):
            browser.value(f"document.querySelector('[data-pick-group={group}][data-frequency-pick=\"{number}\"]').click()")

        def summary(group, key):
            return browser.value(f"Number(document.querySelector('[data-summary-group={group}] [data-summary-count={key}]').textContent)")

        selected = "[...document.querySelectorAll('[data-pick-group=main][aria-pressed=true]')].map(b=>[b.dataset.frequencyPick,b.textContent]).sort()"
        browser.value("window.markOriginalFetch=window.fetch;window.markApiCalls=0;window.fetch=(...args)=>{if(String(args[0]).includes('/api/analysis?'))markApiCalls++;return markOriginalFetch(...args)}")
        for number in ['09', '04', '11']:
            pick(number)
        self.assertEqual(summary('main', 'selected'), 3)
        self.assertEqual(browser.value(selected), [['04', '2'], ['09', '1'], ['11', '3']])
        pick('04')
        self.assertEqual(summary('main', 'selected'), 2)
        self.assertEqual(browser.value(selected), [['09', '1'], ['11', '2']])
        pick('04')
        self.assertEqual(browser.value(selected), [['04', '3'], ['09', '1'], ['11', '2']])
        browser.value("document.querySelector('[data-sort-group=main]').click()")
        self.assertEqual(browser.value(selected), [['04', '3'], ['09', '1'], ['11', '2']])
        browser.value("document.querySelector('[data-sort-group=main]').click()")
        pick('01', 'special')
        self.assertEqual(summary('special', 'selected'), 1)
        self.assertEqual(browser.value("document.querySelector('[data-pick-group=special][data-frequency-pick=\"01\"]').textContent"), '1')
        self.assertEqual(browser.value('markApiCalls'), 0)
        browser.value("window.fetch=markOriginalFetch;document.getElementById('analysisRefreshBtn').click()")
        wait("!analysisState.loading && !!document.querySelector('[data-pick-group=main]')")
        self.assertEqual(browser.value(selected), [['04', '3'], ['09', '1'], ['11', '2']])
        self.assertTrue(browser.value("(()=>{const p=JSON.parse(JSON.stringify(analysisState.lastPayload));p.latestDraw.numbers=['99'];try{validateAnalysisFrequency(p,p.type,p.requestedDrawCount);return false}catch(e){return true}})()"))
        self.assertTrue(browser.value("(()=>{const p=JSON.parse(JSON.stringify(analysisState.lastPayload));p.previousDraw.numbers=['99'];try{validateAnalysisFrequency(p,p.type,p.requestedDrawCount);return false}catch(e){return true}})()"))
        self.assertTrue(browser.value("(()=>{const p=JSON.parse(JSON.stringify(analysisState.lastPayload));p.data.main.items[0].currentDelay=-1;try{validateAnalysisFrequency(p,p.type,p.requestedDrawCount);return false}catch(e){return true}})()"))
        for field, value in [('previousDelay', -1), ('previousDelay', 99999), ('previousAverageDelay', -1), ('previousAverageDelay', '5')]:
            self.assertTrue(browser.value("(()=>{const p=JSON.parse(JSON.stringify(analysisState.lastPayload));p.data.main.items[0][" + json.dumps(field) + "]=" + json.dumps(value) + ";try{validateAnalysisFrequency(p,p.type,p.requestedDrawCount);return false}catch(e){return true}})()"))

        # Presentation-only fixture exercises flame artwork and embedded digits in both themes.
        browser.value("window.streakPreview=JSON.parse(JSON.stringify(analysisState.lastPayload));for(const group of ['main','special']){for(const [i,delay] of [6,12,18,5].entries()){const row=streakPreview.data[group].items[i];row.currentDelay=delay;row.averageDelay=5.96;row.delayLowerBound=false;}}renderAnalysis(streakPreview)")
        browser.value("for(const group of ['main','special']){Object.assign(streakPreview.data[group].items[4],{currentDelay:0,averageDelay:4,previousDelay:7,previousAverageDelay:1,delayLowerBound:false});}renderAnalysis(streakPreview)")
        for group in ['main', 'special']:
            self.assertEqual(browser.value(f"[...document.querySelectorAll('[data-frequency-group={group}] .frequency-fire')].slice(0,5).map(e=>e.dataset.streakState)"), ['red', 'red', 'red', 'green', 'gray'])
            self.assertEqual(browser.value(f"document.querySelector('[data-frequency-group={group}] .is-gray text').textContent"), '7')
            self.assertIsNone(browser.value(f"document.querySelector('[data-frequency-group={group}] .is-green text')"))
        self.assertEqual(browser.value("[...document.querySelectorAll('[data-frequency-group=main] .frequency-fire')].slice(0,3).map(e=>e.dataset.streak)"), ['1', '2', '3'])
        self.assertEqual(browser.value("[...document.querySelectorAll('[data-frequency-group=special] .frequency-fire')].slice(0,3).map(e=>e.dataset.streak)"), ['1', '2', '3'])
        for group, selected_count in [('main', 3), ('special', 1)]:
            expected = [3, 1, 1, 30 if group == 'main' else 7, selected_count]
            self.assertEqual([summary(group, key) for key in ['red', 'green', 'gray', 'empty', 'selected']], expected)
            self.assertEqual(sum(summary(group, key) for key in ['red', 'green', 'gray', 'empty']),
                             browser.value(f"document.querySelectorAll('[data-frequency-group={group}] tbody tr').length"))
        self.assertTrue(browser.value("[...document.querySelectorAll('.frequency-table')].every(t=>t.tFoot.rows.length===1 && Math.abs(t.tFoot.getBoundingClientRect().top-t.tBodies[0].getBoundingClientRect().bottom)<1 && [...t.tFoot.rows[0].cells].reduce((n,c)=>n+c.colSpan,0)===10)"))
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-summary').length"), 0)
        # Group flame colors before descending levels, then restore the exact base order.
        browser.value("window.streakSourcePayload=analysisState.lastPayload;window.streakSortPreview=JSON.parse(JSON.stringify(streakPreview));for(const group of ['main','special']){for(const [i,level] of [[5,1],[6,2]])Object.assign(streakSortPreview.data[group].items[i],{currentDelay:0,averageDelay:4,previousDelay:level,previousAverageDelay:1,delayLowerBound:false});for(const i of [7,8])Object.assign(streakSortPreview.data[group].items[i],{currentDelay:6,averageDelay:5.96,delayLowerBound:false});}for(const group of ['main','special'])Object.assign(streakSortPreview.data[group].items[9],{currentDelay:1,averageDelay:0,delayLowerBound:false});analysisState.lastPayload=streakSortPreview;renderAnalysis();window.streakOriginalFetch=fetch;window.streakSortApiCalls=0;window.fetch=(...args)=>{if(String(args[0]).includes('/api/analysis?'))streakSortApiCalls++;return streakOriginalFetch(...args)}")
        def numbers(group):
            return browser.value(f"[...document.querySelectorAll('[data-frequency-group={group}] tbody tr')].map(r=>r.dataset.number)")
        def levels(group):
            return browser.value(f"[...document.querySelectorAll('[data-frequency-group={group}] tbody tr')].map(r=>Number(r.querySelector('.frequency-fire')?.dataset.streak||0))")
        def colors(group):
            return browser.value(f"[...document.querySelectorAll('[data-frequency-group={group}] tbody tr')].map(r=>r.querySelector('.frequency-fire')?.dataset.streakState||'empty')")
        def streak_click(group):
            browser.value(f"document.querySelector('[data-streak-sort={group}]').click()")
        initial = {group: numbers(group) for group in ['main', 'special']}
        marks_before_sort = browser.value('JSON.stringify(analysisState.marksByType)')
        source_before_sort = browser.value('JSON.stringify(streakSortPreview)')
        def metric_click(group, metric):
            browser.value(f"document.querySelector('[data-metric-group={group}][data-metric-sort={metric}]').click()")
        for group in ['main', 'special']:
            source_rows = browser.value(f'streakSortPreview.data.{group}.items')
            for metric in ['currentDelay', 'averageDelay']:
                expected = sorted(source_rows, key=lambda row: (row[metric] is None, -(row[metric] or 0), -row['count'], int(row['number'])))
                metric_click(group, metric)
                self.assertEqual(numbers(group), [row['number'] for row in expected])
                self.assertEqual(browser.value(f"document.querySelector('[data-metric-group={group}][data-metric-sort={metric}]').closest('th').getAttribute('aria-sort')"), 'descending')
                self.assertEqual(numbers('special' if group == 'main' else 'main'), initial['special' if group == 'main' else 'main'])
                metric_click(group, metric)
                self.assertEqual(numbers(group), initial[group])
        metric_click('main', 'currentDelay')
        metric_click('main', 'averageDelay')
        self.assertEqual(browser.value('analysisState.sortMetricMain'), 'averageDelay')
        self.assertEqual(browser.value("document.querySelectorAll('[data-frequency-group=main] .frequency-column-sort[aria-pressed=true]').length"), 1)
        metric_click('special', 'currentDelay')
        self.assertEqual(browser.value('analysisState.sortMetricMain'), 'averageDelay')
        delay_evidence = ROOT / 'runtime/logs/delay_sort_20261118'
        delay_evidence.mkdir(parents=True, exist_ok=True)
        for width, light in [(1440, False), (320, True)]:
            browser.call('Emulation.setDeviceMetricsOverride', dict(width=width, height=1100, deviceScaleFactor=1, mobile=width < 500), page=True)
            browser.value(f"(()=>{{document.body.classList.toggle('light-theme',{str(light).lower()});const wrap=document.querySelector('.frequency-table-wrap');wrap.scrollLeft=wrap.scrollWidth;document.querySelector('[data-metric-group=main][data-metric-sort=averageDelay]').scrollIntoView({{block:'center'}})}})()")
            self.assertTrue(browser.value("[...document.querySelectorAll('[data-frequency-group=main] [data-metric-sort]')].every(b=>{const r=b.getBoundingClientRect(),h=b.closest('th').getBoundingClientRect();return r.width<=h.width+.5 && r.height<=h.height+.5 && r.left>=0 && r.right<=innerWidth})"))
            shot=browser.call('Page.captureScreenshot', dict(format='png'), page=True)
            (delay_evidence / f'delay-sort-{width}.png').write_bytes(base64.b64decode(shot['data']))
        browser.call('Emulation.setDeviceMetricsOverride', dict(width=1440, height=1100, deviceScaleFactor=1, mobile=False), page=True)
        browser.value("document.body.classList.remove('light-theme')")
        metric_click('special', 'currentDelay')
        streak_click('main')
        self.assertEqual(browser.value('analysisState.sortMetricMain'), '')
        metric_click('main', 'currentDelay')
        self.assertFalse(browser.value('analysisState.sortStreakMain'))
        metric_click('main', 'currentDelay')
        self.assertEqual(numbers('main'), initial['main'])
        streak_click('main')
        self.assertEqual(colors('main'), ['red'] * 5 + ['green'] + ['gray'] * 3 + ['empty'] * 26)
        self.assertEqual(levels('main')[:9], [3, 2, 1, 1, 1, 1, 7, 2, 1])
        self.assertEqual(numbers('special'), initial['special'])
        self.assertEqual(browser.value("document.querySelector('[data-streak-sort=main]').closest('th').getAttribute('aria-sort')"), 'descending')
        streak_click('special')
        self.assertEqual(colors('special'), ['red'] * 5 + ['green'] + ['gray'] * 3 + ['empty'] * 3)
        self.assertEqual(levels('special')[:9], [3, 2, 1, 1, 1, 1, 7, 2, 1])
        streak_click('main')
        self.assertEqual(numbers('main'), initial['main'])
        self.assertEqual(colors('special'), ['red'] * 5 + ['green'] + ['gray'] * 3 + ['empty'] * 3)
        self.assertEqual(levels('special')[:9], [3, 2, 1, 1, 1, 1, 7, 2, 1])
        streak_click('special')
        self.assertEqual(numbers('special'), initial['special'])
        browser.value("document.querySelector('[data-sort-group=main]').click()")
        number_order = numbers('main')
        self.assertEqual(number_order, sorted(number_order, key=int))
        for metric in ['currentDelay', 'averageDelay']:
            metric_click('main', metric)
            metric_click('main', metric)
            self.assertEqual(numbers('main'), number_order)
        streak_click('main')
        streak_click('main')
        self.assertEqual(numbers('main'), number_order)
        streak_click('main')
        browser.value("document.querySelector('[data-sort-group=main]').click()")
        self.assertEqual(numbers('main'), initial['main'])
        self.assertFalse(browser.value('analysisState.sortStreakMain'))
        self.assertEqual(browser.value('JSON.stringify(analysisState.marksByType)'), marks_before_sort)
        self.assertEqual(browser.value('JSON.stringify(streakSortPreview)'), source_before_sort)
        self.assertEqual(browser.value('streakSortApiCalls'), 0)
        sort_evidence = ROOT / 'runtime/logs/delay_sort_20261118'
        sort_evidence.mkdir(parents=True, exist_ok=True)
        streak_click('main')
        for width, light in [(1440, False), (320, True)]:
            browser.call('Emulation.setDeviceMetricsOverride', dict(width=width, height=1100, deviceScaleFactor=1, mobile=width < 500), page=True)
            browser.value(f"(()=>{{document.body.classList.toggle('light-theme',{str(light).lower()});const wrap=document.querySelector('.frequency-table-wrap');wrap.scrollLeft=wrap.scrollWidth;document.querySelector('[data-streak-sort=main]').scrollIntoView({{block:'center'}})}})()")
            self.assertTrue(browser.value("(()=>{const b=document.querySelector('[data-streak-sort=main]'),r=b.getBoundingClientRect();return b.getAttribute('aria-pressed')==='true' && r.left>=0 && r.right<=innerWidth})()"))
            shot = browser.call('Page.captureScreenshot', dict(format='png'), page=True)
            (sort_evidence / f'streak-sort-{width}.png').write_bytes(base64.b64decode(shot['data']))
        streak_click('main')
        browser.call('Emulation.setDeviceMetricsOverride', dict(width=1440, height=1100, deviceScaleFactor=1, mobile=False), page=True)
        browser.value("window.fetch=streakOriginalFetch;analysisState.lastPayload=streakSourcePayload;document.body.classList.remove('light-theme');document.querySelector('.frequency-table-wrap').scrollLeft=0;renderAnalysis(streakPreview)")
        evidence = ROOT / 'runtime/logs/summary_empty_20261117'
        evidence.mkdir(parents=True, exist_ok=True)
        browser.value("document.getElementById('predictRootAnalysis').scrollIntoView({block:'start'})")
        for width in [1440, 390, 320]:
            browser.call('Emulation.setDeviceMetricsOverride', dict(width=width, height=1100, deviceScaleFactor=1, mobile=width < 500), page=True)
            browser.value("document.getElementById('predictRootAnalysis').scrollIntoView({block:'start'})")
            metrics = browser.value("(()=>{const a=document.getElementById('predictRootAnalysis'),r=a.getBoundingClientRect();return {left:r.left,right:r.right,width:innerWidth,scroll:a.scrollWidth,client:a.clientWidth}})()")
            self.assertGreaterEqual(metrics['left'], 0, metrics)
            self.assertLessEqual(metrics['right'], width + 1, metrics)
            self.assertLessEqual(metrics['scroll'], metrics['client'] + 1, metrics)
            if width < 500:
                self.assertTrue(browser.value("(()=>{const w=document.querySelector('.frequency-table-wrap');w.scrollLeft=w.scrollWidth;return w.scrollWidth>w.clientWidth && w.scrollLeft>0})()"))
                self.assertTrue(browser.value("(()=>{const w=document.querySelector('.frequency-table-wrap').getBoundingClientRect(),n=document.querySelector('.frequency-table tbody th').getBoundingClientRect();return n.left>=w.left && n.right<=w.right})()"))
            image = browser.call('Page.captureScreenshot', dict(format='png'), page=True)
            (evidence / f'frequency-{width}.png').write_bytes(base64.b64decode(image['data']))
        browser.value("document.body.classList.add('light-theme')")
        self.assertEqual(browser.value("getComputedStyle(document.querySelector('.frequency-table')).backgroundColor"), 'rgb(255, 255, 255)')
        self.assertEqual(browser.value("getComputedStyle(document.getElementById('analysisTypeSelect')).backgroundColor"), 'rgb(255, 255, 255)')
        image = browser.call('Page.captureScreenshot', dict(format='png'), page=True)
        (evidence / 'frequency-light-320.png').write_bytes(base64.b64decode(image['data']))
        for width, light in [(1440, False), (320, True)]:
            browser.call('Emulation.setDeviceMetricsOverride', dict(width=width, height=700, deviceScaleFactor=1, mobile=width < 500), page=True)
            browser.value(f"document.body.classList.toggle('light-theme',{str(light).lower()});document.querySelector('.frequency-summary-row').scrollIntoView({{block:'center'}})")
            self.assertTrue(browser.value("(()=>{const e=document.querySelector('.frequency-summary-row').closest('.frequency-table-wrap'),r=e.getBoundingClientRect();return r.left>=0 && r.right<=innerWidth+1})()"))
            image = browser.call('Page.captureScreenshot', dict(format='png'), page=True)
            (evidence / f'summary-{width}.png').write_bytes(base64.b64decode(image['data']))
        browser.value("renderAnalysis(analysisState.lastPayload)")
        browser.value("document.body.classList.remove('light-theme');document.getElementById('analysisTypeSelect').value='LOTO_6_45';document.getElementById('analysisTypeSelect').dispatchEvent(new Event('change'))")
        wait("document.querySelectorAll('[data-frequency-group=main] tbody tr').length===45")
        self.assertEqual(browser.value("document.querySelectorAll('[data-frequency-group=special]').length"), 0)
        self.assertEqual(browser.value("document.querySelectorAll('[data-summary-group=special]').length"), 0)
        self.assertEqual(summary('main', 'selected'), 0)
        self.assertEqual(browser.value("document.querySelectorAll('[data-frequency-pick][aria-pressed=true]').length"), 0)
        browser.value("document.getElementById('analysisTypeSelect').value='LOTO_6_55';document.getElementById('analysisTypeSelect').dispatchEvent(new Event('change'))")
        wait("document.getElementById('analysisScope').textContent.startsWith('30 kỳ gần nhất')")
        for count in [10, 30, 50, 80, 100]:
            browser.value(f"document.getElementById('analysisDrawCountSelect').value='{count}';document.getElementById('analysisDrawCountSelect').dispatchEvent(new Event('change'))")
            wait(f"document.getElementById('analysisScope').textContent.startsWith('{count} kỳ gần nhất')")
        browser.value("document.getElementById('analysisDrawCountSelect').value='all';document.getElementById('analysisDrawCountSelect').dispatchEvent(new Event('change'))")
        wait("!analysisState.loading && (analysisState.lastPayload?.totalDraws === 120 && document.getElementById('analysisScope').textContent === analysisState.lastPayload.fromDate + (analysisState.type==='LOTO_5_35' ? ' '+analysisState.lastPayload.fromTime : '') + ' → ' + analysisState.lastPayload.toDate + (analysisState.type==='LOTO_5_35' ? ' '+analysisState.lastPayload.toTime : ''))")
        self.assertEqual(browser.value('analysisState.lastPayload.data.main.totalOccurrences'), 720)
        self.assertEqual(browser.value('analysisState.lastPayload.data.special.totalOccurrences'), 120)
        self.assertTrue(browser.value("document.getElementById('analysisCustomCountField').hidden"))
        self.assertNotIn('2.147', browser.value("document.getElementById('analysisScope').textContent"))
        all_evidence = ROOT / 'runtime/logs/analysis_all_draws_20261118'
        all_evidence.mkdir(parents=True, exist_ok=True)
        browser.value("document.getElementById('predictRootAnalysis').scrollIntoView({block:'start'})")
        image = browser.call('Page.captureScreenshot', dict(format='png'), page=True)
        (all_evidence / 'analysis-all-320.png').write_bytes(base64.b64decode(image['data']))
        browser.value("document.getElementById('analysisTypeSelect').value='LOTO_5_35';document.getElementById('analysisTypeSelect').dispatchEvent(new Event('change'))")
        wait("!analysisState.loading && (analysisState.lastPayload?.totalDraws === 5 && document.getElementById('analysisScope').textContent === analysisState.lastPayload.fromDate + (analysisState.type==='LOTO_5_35' ? ' '+analysisState.lastPayload.fromTime : '') + ' → ' + analysisState.lastPayload.toDate + (analysisState.type==='LOTO_5_35' ? ' '+analysisState.lastPayload.toTime : ''))")
        self.assertEqual(browser.value("document.getElementById('analysisDrawCountSelect').value"), 'all')
        browser.value("document.getElementById('analysisTypeSelect').value='LOTO_6_55';document.getElementById('analysisTypeSelect').dispatchEvent(new Event('change'))")
        wait("!analysisState.loading && (analysisState.lastPayload?.totalDraws === 120 && document.getElementById('analysisScope').textContent === analysisState.lastPayload.fromDate + (analysisState.type==='LOTO_5_35' ? ' '+analysisState.lastPayload.fromTime : '') + ' → ' + analysisState.lastPayload.toDate + (analysisState.type==='LOTO_5_35' ? ' '+analysisState.lastPayload.toTime : ''))")
        browser.call('Page.reload', dict(ignoreCache=True), page=True)
        wait("typeof currentUser==='string' && currentUser==='owner_fixture' && document.getElementById('appShell').style.display==='block'")
        browser.value("document.getElementById('predictModeAnalysisTab').click()")
        wait("!analysisState.loading && (analysisState.lastPayload?.totalDraws === 120 && document.getElementById('analysisScope').textContent === analysisState.lastPayload.fromDate + (analysisState.type==='LOTO_5_35' ? ' '+analysisState.lastPayload.fromTime : '') + ' → ' + analysisState.lastPayload.toDate + (analysisState.type==='LOTO_5_35' ? ' '+analysisState.lastPayload.toTime : ''))")
        self.assertEqual(browser.value("document.getElementById('analysisDrawCountSelect').value"), 'all')
        browser.value("document.getElementById('analysisDrawCountSelect').value='custom';document.getElementById('analysisDrawCountSelect').dispatchEvent(new Event('change'))")
        wait("document.getElementById('analysisStatus').textContent.includes('số nguyên dương')")
        self.assertFalse(browser.value("document.getElementById('analysisCustomCountField').hidden"))
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-table').length"), 0)
        browser.value("document.getElementById('analysisCustomCountInput').value='7';document.getElementById('analysisCustomCountInput').dispatchEvent(new Event('input'));document.getElementById('analysisCustomCountInput').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))")
        wait("document.getElementById('analysisScope').textContent.startsWith('7 kỳ gần nhất')")
        self.assertEqual(browser.value("document.querySelectorAll('[data-frequency-group=main] tbody tr').length"), 55)
        browser.value("document.getElementById('analysisCustomCountInput').value='0';document.getElementById('analysisCustomCountInput').dispatchEvent(new Event('input'));document.getElementById('analysisRefreshBtn').click()")
        wait("document.getElementById('analysisStatus').textContent.includes('số nguyên dương')")
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-table').length"), 0)
        browser.value("document.getElementById('analysisCustomCountInput').value='150';document.getElementById('analysisCustomCountInput').dispatchEvent(new Event('input'))")
        self.assertEqual(browser.value("document.getElementById('analysisCustomCountInput').value"), '120')
        self.assertEqual(browser.value("document.getElementById('analysisCustomCountInput').max"), '120')
        browser.value("document.getElementById('analysisRefreshBtn').click()")
        wait("document.getElementById('analysisScope').textContent.startsWith('120 kỳ gần nhất')")
        image = browser.call('Page.captureScreenshot', dict(format='png'), page=True)
        (evidence / 'frequency-custom-320.png').write_bytes(base64.b64decode(image['data']))
        browser.value("document.getElementById('analysisTypeSelect').value='LOTO_5_35';document.getElementById('analysisTypeSelect').dispatchEvent(new Event('change'))")
        wait("document.getElementById('analysisScope').textContent.startsWith('5 kỳ gần nhất')")
        self.assertEqual(browser.value("document.getElementById('analysisCustomCountInput').value"), '5')
        self.assertEqual(browser.value(selected), [['04', '3'], ['09', '1'], ['11', '2']])
        browser.value("document.getElementById('analysisTypeSelect').value='LOTO_6_55';document.getElementById('analysisTypeSelect').dispatchEvent(new Event('change'))")
        wait("document.getElementById('analysisCustomCountInput').max==='120' && !analysisState.loading")
        browser.value("document.getElementById('analysisCustomCountInput').value='2000';document.getElementById('analysisCustomCountInput').dispatchEvent(new InputEvent('input',{inputType:'insertFromPaste',bubbles:true}))")
        self.assertEqual(browser.value("document.getElementById('analysisCustomCountInput').value"), '120')
        browser.value("document.getElementById('analysisCustomCountInput').value='';document.getElementById('analysisCustomCountInput').dispatchEvent(new Event('input'))")
        self.assertEqual(browser.value("document.getElementById('analysisCustomCountInput').value"), '')
        browser.value("localStorage.setItem(ANALYSIS_UI_KEY,JSON.stringify({...JSON.parse(localStorage.getItem(ANALYSIS_UI_KEY)),customCount:'2000'}))")
        browser.call('Page.reload', dict(ignoreCache=True), page=True)
        wait("typeof currentUser==='string' && currentUser==='owner_fixture' && document.getElementById('appShell').style.display==='block'")
        browser.value("document.getElementById('predictModeAnalysisTab').click()")
        wait("document.getElementById('analysisScope').textContent.startsWith('120 kỳ gần nhất')")
        self.assertEqual(browser.value("document.getElementById('analysisCustomCountInput').value"), '120')
        self.assertFalse(browser.value("document.getElementById('analysisCustomCountInput').disabled"))
        browser.value("window.frequencyOriginalFetch=window.fetch;window.fetch=(...a)=>String(a[0]).includes('/api/analysis?')?Promise.resolve(new Response(JSON.stringify({ok:false,message:'Lỗi nguồn thử'}),{status:503,headers:{'Content-Type':'application/json'}})):frequencyOriginalFetch(...a);document.getElementById('analysisRefreshBtn').click()")
        wait("document.getElementById('analysisStatus').textContent==='Lỗi nguồn thử'")
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-table').length"), 0)
        browser.value("window.fetch=(...a)=>String(a[0]).includes('/api/analysis?')?frequencyOriginalFetch(...a).then(r=>new Promise(resolve=>setTimeout(()=>resolve(r),500))):frequencyOriginalFetch(...a);document.getElementById('analysisTypeSelect').value='LOTO_5_35';document.getElementById('analysisTypeSelect').dispatchEvent(new Event('change'));window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:false}}))")
        time.sleep(.8)
        self.assertEqual(browser.value("document.querySelectorAll('.frequency-table').length"), 0)
        self.assertFalse(browser.value("document.getElementById('analysisFrequencyOut').getAttribute('aria-busy')==='true'"))
        self.assertEqual(browser.value("Object.keys(analysisState.marksByType).length"), 0)

        # Marks belong to the stable account, not the current draw or page load.
        expected_marks = [['04', '3'], ['09', '1'], ['11', '2']]
        browser.value("window.fetch=frequencyOriginalFetch;analysisState.type='LOTO_5_35';analysisState.drawPreset='30';saveAnalysisUiState();loadAnalysis()")
        wait("!analysisState.loading && document.querySelectorAll('[data-frequency-group=main] tbody tr').length===35")
        self.assertEqual(browser.value(selected), expected_marks)
        self.assertEqual(browser.value("document.querySelector('[data-pick-group=special][data-frequency-pick=\"01\"]').textContent"), '1')
        storage_key = browser.value('analysisMarksStorageKey()')
        saved_marks = browser.value(f'localStorage.getItem({json.dumps(storage_key)})')
        browser.value("resetAnalysisSession();loadAnalysis()")
        wait("!analysisState.loading && !!document.querySelector('[data-pick-group=main]')")
        self.assertEqual(browser.value(selected), expected_marks)
        self.assertEqual(browser.value(f'localStorage.getItem({json.dumps(storage_key)})'), saved_marks)

        browser.call('Page.reload', dict(ignoreCache=True), page=True)
        wait("typeof currentUser==='string' && currentUser==='owner_fixture' && document.getElementById('appShell').style.display==='block'")
        browser.value("document.getElementById('predictModeAnalysisTab').click()")
        wait("!analysisState.loading && document.querySelectorAll('[data-frequency-group=main] tbody tr').length===35")
        self.assertEqual(browser.value(selected), expected_marks)
        self.assertEqual(browser.value("document.querySelector('[data-pick-group=special][data-frequency-pick=\"01\"]').textContent"), '1')

        canonical = self.work / 'data/canonical/loto_5_35_all_day.csv'
        old_csv = canonical.read_text(encoding='utf-8')
        browser.value("analysisState.drawPreset='all';saveAnalysisUiState();loadAnalysis()")
        wait("!analysisState.loading && (analysisState.lastPayload?.totalDraws === 5 && document.getElementById('analysisScope').textContent === analysisState.lastPayload.fromDate + (analysisState.type==='LOTO_5_35' ? ' '+analysisState.lastPayload.fromTime : '') + ' → ' + analysisState.lastPayload.toDate + (analysisState.type==='LOTO_5_35' ? ' '+analysisState.lastPayload.toTime : ''))")
        try:
            canonical.write_text(old_csv + '6,Thứ 3,06/01/2026,21:00,"6,7,8,9,10",2,06 07 08 09 10 | ĐB 02,Loto_5/35,https://example.test,06/01/2026\n', encoding='utf-8')
            browser.value("document.getElementById('analysisRefreshBtn').click()")
            wait("!analysisState.loading && analysisState.lastPayload?.latestDraw.drawId==='6'")
            self.assertTrue(browser.value("(analysisState.lastPayload?.totalDraws === 6 && document.getElementById('analysisScope').textContent === analysisState.lastPayload.fromDate + (analysisState.type==='LOTO_5_35' ? ' '+analysisState.lastPayload.fromTime : '') + ' → ' + analysisState.lastPayload.toDate + (analysisState.type==='LOTO_5_35' ? ' '+analysisState.lastPayload.toTime : ''))"))
            self.assertEqual(browser.value('analysisState.lastPayload.totalDraws'), 6)
            self.assertEqual(browser.value(selected), expected_marks)
            self.assertEqual(browser.value(marked), ['06', '07', '08', '09', '10'])
            self.assertEqual(browser.value(previous_marked), ['01', '02', '03', '04', '05'])
            self.assertEqual(browser.value("document.querySelector('[data-frequency-group=special] .frequency-previous-mark').closest('tr').dataset.number"), '01')
            self.assertEqual(browser.value("document.querySelector('[data-frequency-group=special] .frequency-latest-mark').closest('tr').dataset.number"), '02')
            self.assertEqual(browser.value("document.querySelector('[data-pick-group=special][data-frequency-pick=\"01\"]').textContent"), '1')
            self.assertEqual(browser.value(f'localStorage.getItem({json.dumps(storage_key)})'), saved_marks)
        finally:
            canonical.write_text(old_csv, encoding='utf-8')

        browser.value("window.markerAccountId=currentAccountId;currentAccountId=currentAccountId==='100000000001'?'100000000002':'100000000001';renderAnalysis()")
        self.assertEqual(browser.value("document.querySelectorAll('[data-frequency-pick][aria-pressed=true]').length"), 0)
        pick('06')
        self.assertEqual(browser.value(selected), [['06', '1']])
        browser.value("currentAccountId=markerAccountId;renderAnalysis()")
        self.assertEqual(browser.value(selected), expected_marks)
        self.assertEqual(browser.value(f'localStorage.getItem({json.dumps(storage_key)})'), saved_marks)

        browser.value("logout()")
        wait("currentUser===null && document.getElementById('authOverlay').style.display==='flex'")
        self.assertEqual(browser.value(f'localStorage.getItem({json.dumps(storage_key)})'), saved_marks)
        self.login()
        browser.call('Network.setCookie', dict(name='LOTTO_AUTH', value=self.admin.split(';')[0].split('=', 1)[1], url=self.url), page=True)
        browser.call('Page.reload', dict(ignoreCache=True), page=True)
        wait("typeof currentUser==='string' && currentUser==='owner_fixture' && document.getElementById('appShell').style.display==='block'")
        browser.value("document.getElementById('predictModeAnalysisTab').click()")
        wait("!analysisState.loading && !!document.querySelector('[data-pick-group=main]')")
        self.assertEqual(browser.value(selected), expected_marks)
        pick('11')
        self.assertEqual(browser.value(selected), [['04', '2'], ['09', '1']])
        browser.value("resetAnalysisSession();loadAnalysis()")
        wait("!analysisState.loading && !!document.querySelector('[data-pick-group=main]')")
        self.assertEqual(browser.value(selected), [['04', '2'], ['09', '1']])


    def test_editable_date_range_filters_validates_and_preserves_marks(self):
        canonical = self.work/'data/canonical/loto_5_35_all_day.csv'
        original = canonical.read_bytes()
        self.addCleanup(canonical.write_bytes, original)
        canonical.write_text(frequency_draw_fixture(count=5),encoding='utf-8')
        browser = Browser(CHROME, (self.work/'session-cutoff-browser').resolve())
        self.addCleanup(browser.close)
        browser.call('Network.enable',page=True)
        browser.call('Network.setCookie',dict(name='LOTTO_AUTH',value=self.admin.split(';')[0].split('=',1)[1],url=self.url),page=True)
        browser.call('Page.navigate',dict(url=self.url+'/'),page=True)
        def wait(expression):
            for _ in range(400):
                if browser.value(expression):return
                time.sleep(.05)
            self.fail('Session timeout: '+expression+'; '+str(browser.value("document.getElementById('analysisStatus').textContent")))
        def edit(day,slot):
            browser.value("openAnalysisDateEditor()")
            browser.value(f"document.getElementById('analysisDateTo').value='{day}';document.getElementById('analysisDateTo').dispatchEvent(new Event('change'));document.getElementById('analysisDateToTime').value='{slot}';document.getElementById('analysisDateForm').requestSubmit()")
        def hook():
            browser.value("window.sessionRequests=[];window.origSessionFetch=window.fetch;window.fetch=(url,options)=>{if(String(url).startsWith('/api/analysis?'))sessionRequests.push(String(url));return origSessionFetch(url,options)}")
        wait("typeof currentUser==='string' && currentUser==='owner_fixture' && document.getElementById('appShell').style.display==='block'")
        browser.value("document.getElementById('predictModeAnalysisTab').click()")
        wait("!analysisState.loading && analysisState.lastPayload?.totalDraws===5")
        self.assertEqual(browser.value('analysisState.lastPayload.availableToTime'),'13:00')
        self.assertIn('2026-01-03 13:00',browser.value("document.getElementById('analysisScope').textContent"))
        self.assertTrue(browser.value("document.getElementById('analysisDateNext').disabled"))
        browser.value("document.querySelector('[data-frequency-group=main] [data-number=\"01\"] [data-frequency-pick]').click()")
        selected=browser.value('getAnalysisMarks(false)')
        hook()
        self.assertEqual(browser.value("document.getElementById('analysisDateNext').getAttribute('aria-disabled')"),'true')
        self.assertIn('Đã ở kỳ hiện tại',browser.value("document.getElementById('analysisDateNext').title"))
        browser.value("document.getElementById('analysisDateNext').click();shiftAnalysisDates(1)")
        self.assertEqual(browser.value('sessionRequests.length'),0)
        self.assertEqual(browser.value('analysisState.lastPayload.totalDraws'),5)
        browser.value("openAnalysisDateEditor()")
        self.assertTrue(browser.value("document.getElementById('analysisDateFrom').readOnly"))
        self.assertFalse(browser.value("document.getElementById('analysisDateSessionField').hidden"))
        self.assertTrue(browser.value("document.querySelector('#analysisDateToTime option[value=\"21:00\"]').disabled"))
        self.assertEqual(browser.value("document.getElementById('analysisDateFirstTime').textContent"),'Kỳ đầu: 13:00')
        browser.value("document.getElementById('analysisDateCancel').click();document.getElementById('analysisDatePrev').click()")
        wait("!analysisState.loading && analysisState.lastPayload?.totalDraws===4")
        self.assertEqual(browser.value('analysisState.lastPayload.latestDraw.drawId'),'4')
        self.assertFalse(browser.value("document.getElementById('analysisDateNext').disabled"))
        self.assertEqual(browser.value("document.getElementById('analysisDateNext').getAttribute('aria-disabled')"),'false')
        self.assertEqual(browser.value('analysisState.lastPayload.toTime'),'21:00')
        browser.value("document.getElementById('analysisDatePrev').click()")
        wait("!analysisState.loading && analysisState.lastPayload?.totalDraws===3")
        self.assertEqual(browser.value('analysisState.lastPayload.toDate'),'2026-01-02')
        self.assertEqual(browser.value('analysisState.lastPayload.toTime'),'13:00')
        self.assertEqual(browser.value('analysisState.lastPayload.data.main.totalOccurrences'),15)
        self.assertEqual(browser.value('analysisState.lastPayload.previousDraw.drawId'),'2')
        self.assertTrue(browser.value("sessionRequests.every(url=>new URL(url,location.origin).searchParams.has('toTime'))"))
        browser.value("document.getElementById('analysisDateNext').click()")
        wait("!analysisState.loading && analysisState.lastPayload?.totalDraws===4")
        edit('2026-01-02','13:00')
        wait("!analysisState.loading && analysisState.lastPayload?.totalDraws===3")
        self.assertEqual(browser.value('analysisState.dateFrom'),'2026-01-01')
        self.assertEqual(browser.value('getAnalysisMarks(false)'),selected)
        count=browser.value('sessionRequests.length')
        edit('2026-01-03','21:00')
        self.assertEqual(browser.value('sessionRequests.length'),count)
        self.assertFalse(browser.value("document.getElementById('analysisDateError').hidden"))
        browser.value("document.getElementById('analysisDateCancel').click();analysisState.dateFrom='2026-01-02';saveAnalysisUiState()")
        browser.call('Page.reload',dict(ignoreCache=True),page=True)
        wait("typeof currentUser==='string' && currentUser==='owner_fixture' && document.getElementById('appShell').style.display==='block'")
        browser.value("document.getElementById('predictModeAnalysisTab').click()")
        wait("!analysisState.loading && analysisState.lastPayload?.totalDraws===3 && analysisState.dateFrom==='2026-01-01'")
        self.assertEqual(browser.value('analysisState.dateToTime'),'13:00')
        self.assertEqual(browser.value('getAnalysisMarks(false)'),selected)
        edit('2026-01-01','13:00')
        wait("!analysisState.loading && analysisState.lastPayload?.totalDraws===1")
        self.assertTrue(browser.value("document.getElementById('analysisDatePrev').disabled"))
        browser.value("document.getElementById('analysisDateNext').click()")
        wait("!analysisState.loading && analysisState.lastPayload?.totalDraws===2")
        self.assertEqual(browser.value('analysisState.lastPayload.toDate'),'2026-01-01')
        self.assertEqual(browser.value('analysisState.lastPayload.toTime'),'21:00')
        edit('2026-01-03','13:00')
        wait("!analysisState.loading && analysisState.lastPayload?.totalDraws===5")
        evidence=ROOT/'runtime/logs/analysis_535_sessions_20261121';evidence.mkdir(parents=True,exist_ok=True)
        for width,light in [(1440,False),(320,True)]:
            browser.call('Emulation.setDeviceMetricsOverride',dict(width=width,height=1000,deviceScaleFactor=1,mobile=width<500),page=True)
            browser.value(f"document.body.classList.toggle('light-theme',{str(light).lower()});openAnalysisDateEditor();document.getElementById('predictRootAnalysis').scrollIntoView({{block:'start'}})")
            self.assertTrue(browser.value("(()=>{const b=document.getElementById('analysisDateForm').getBoundingClientRect();return b.left>=0 && b.right<=document.documentElement.clientWidth})()"))
            self.assertTrue(browser.value("(()=>{const b=document.querySelector('.frequency-range-navigation').getBoundingClientRect();return b.right<=document.documentElement.clientWidth})()"))
            image=browser.call('Page.captureScreenshot',dict(format='png'),page=True);(evidence/f'sessions-{width}.png').write_bytes(base64.b64decode(image['data']))
        for slot,expected in [('13:00',3),('21:00',4)]:
            status,payload,_=self.request('/api/analysis?type=LOTO_5_35&mode=frequency&period=custom&from=2026-01-01&to=2026-01-02&toTime='+slot,cookie=self.admin)
            self.assertEqual(status,200);self.assertEqual(payload['totalDraws'],expected)
        status,_,_=self.request('/api/analysis?type=LOTO_5_35&mode=frequency&period=custom&to=2026-01-02&toTime=18:00',cookie=self.admin);self.assertEqual(status,400)
        browser.value("document.getElementById('analysisDateCancel').click();document.getElementById('analysisTypeSelect').value='LOTO_6_55';document.getElementById('analysisTypeSelect').dispatchEvent(new Event('change'))")
        wait("!analysisState.loading && analysisState.lastPayload?.type==='LOTO_6_55'")
        browser.value("openAnalysisDateEditor()")
        self.assertTrue(browser.value("document.getElementById('analysisDateSessionField').hidden"))

    def test_real_draws_change_green_to_red_to_gray_and_reload(self):
        canonical = self.work / 'data/canonical/loto_5_35_all_day.csv'
        original = canonical.read_text(encoding='utf-8')
        self.addCleanup(lambda: canonical.write_text(original, encoding='utf-8'))

        def write_draws(count):
            lines = ['Kỳ,Ngày,Giờ,Bộ Số,ĐB']
            for i in range(count):
                hit = i in [0, 6, 12]
                lines.append(f'{i+1},{i+1:02d}/01/2026,21:00,"{("1,2,3,4,5" if hit else "6,7,8,9,10")}",{1 if hit else 2}')
            canonical.write_text('\n'.join(lines) + '\n', encoding='utf-8')

        write_draws(11)
        browser = Browser(CHROME, self.work / 'streak-transitions-browser')
        self.addCleanup(browser.close)
        browser.call('Network.enable', page=True)
        browser.call('Network.setCookie', dict(name='LOTTO_AUTH', value=self.admin.split(';')[0].split('=', 1)[1], url=self.url), page=True)
        browser.call('Emulation.setDeviceMetricsOverride', dict(width=1440, height=900, deviceScaleFactor=1, mobile=False), page=True)

        def wait(expression):
            for _ in range(400):
                if browser.value(expression):
                    return
                time.sleep(.05)
            self.fail(expression + ': ' + str(browser.value("document.getElementById('analysisStatus')?.textContent")))

        def open_analysis():
            wait("typeof currentUser==='string' && currentUser==='owner_fixture' && document.getElementById('appShell').style.display==='block'")
            browser.value("document.getElementById('predictModeAnalysisTab').click()")

        def check(count, color):
            wait(f"!analysisState.loading && analysisState.lastPayload?.totalDraws==={count}")
            for group in ['main', 'special']:
                state = browser.value(f"document.querySelector('[data-frequency-group={group}] tr[data-number=\"01\"] .frequency-fire')?.dataset.streakState || null")
                self.assertEqual(state, color)

        browser.call('Page.navigate', dict(url=self.url + '/'), page=True)
        open_analysis()
        check(11, 'green')
        write_draws(12)
        browser.value("document.getElementById('analysisRefreshBtn').click()")
        check(12, 'red')
        write_draws(13)
        browser.value("document.getElementById('analysisRefreshBtn').click()")
        check(13, 'gray')
        browser.call('Page.reload', dict(ignoreCache=True), page=True)
        open_analysis()
        check(13, 'gray')
        evidence = ROOT / 'runtime/logs/streak_states_20261117'
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / 'real-transition-row.json').write_text(json.dumps(browser.value("analysisState.lastPayload.data.main.items.find(r=>r.number==='01')"), indent=2), encoding='utf-8')
        write_draws(14)
        browser.value("document.getElementById('analysisRefreshBtn').click()")
        check(14, None)


if __name__ == '__main__':
    unittest.main()
