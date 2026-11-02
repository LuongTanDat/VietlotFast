"""Recovered UI -> authenticated Java -> Python -> disposable wallet/ledger."""
import json
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path

from tests import test_personal_prediction_web as personal
from tests.browser_cdp import Browser
from tests.test_prize_web import CHROME


class RecoveredBaoWebTests(personal.PersonalPredictionWebTests):
    def test_recovered_bao_api_wallet_browser_and_legacy_clamp(self):
        settings = '/api/ml/effectiveness-settings'
        cycle = '/api/ml/effectiveness-cycle'
        code, _, _ = self.request('/api/admin/update-assets',
            {'username': 'member_fixture', 'diamond': '0', 'paypal': '2000000'}, self.admin)
        self.assertEqual(code, 200)
        form = {'type': 'LOTO_6_45', 'enabled': 'false', 'ticketCount': '3',
                'playMode': 'bao', 'baoLevel': '7', 'baoCount': '2'}
        code, saved, _ = self.request(settings, form, self.member)
        self.assertEqual(code, 200, saved)
        self.assertEqual(saved['settings']['ticketCount'], 14)
        self.assertEqual(saved['billing']['totalPayPal'], 560000)
        self.assertEqual(saved['settings']['maxBaoCounts']['7'], 142857)
        code, stale, _ = self.request(cycle, {'type': 'LOTO_6_45', 'configurationHash': '0' * 64}, self.member)
        self.assertEqual(code, 400, stale)
        self.assertEqual(self.request(settings + '?type=LOTO_6_45', cookie=self.member)[1]['billing']['balance'], 2000000)
        code, locked, _ = self.request(cycle, {'type': 'LOTO_6_45', 'configurationHash': saved['settings']['configurationHash']}, self.member)
        self.assertEqual(code, 200, locked)
        self.assertEqual(locked['status'], 'locked')
        self.assertEqual(locked['billing']['balance'], 1440000)
        self.assertEqual(locked['billing']['charges'][0]['status'], 'charged')
        code, repeated, _ = self.request(cycle, {'type': 'LOTO_6_45'}, self.member)
        self.assertEqual(code, 200, repeated)
        self.assertEqual(repeated['status'], 'already_locked')
        self.assertEqual(repeated['billing']['balance'], 1440000)
        code, invalid, _ = self.request(settings, {**form, 'type': 'LOTO_5_35', 'baoLevel': '6', 'baoCount': '54106'}, self.member)
        self.assertEqual(code, 400, invalid)
        self.assertIn('54.105', invalid['message'])
        accepted = self.request(settings, {**form, 'type': 'LOTO_5_35', 'baoLevel': '6', 'baoCount': '54105'}, self.member)
        self.assertEqual(accepted[0], 200, accepted[1])
        self.assertEqual(accepted[1]['settings']['uniqueBy'], 'main_numbers_and_special')
        self.assertEqual(accepted[1]['billing']['totalPayPal'], 12985200000)
        self.assertEqual(accepted[1]['billing']['balance'], 1440000)
        self.assertEqual(self.request(settings, {**form, 'type': 'LOTO_5_35', 'baoLevel': '6', 'baoCount': '2'}, self.member)[0], 200)
        # Simulate the real pre-repair setting without changing production data.
        with closing(sqlite3.connect(self.work / 'runtime/lotto_web.db')) as connection:
            account = connection.execute("SELECT id FROM personal_tracking_accounts WHERE username='member_fixture'").fetchone()[0]
        private = self.work / 'runtime/personal_tracking' / account / 'tracking.db'
        with closing(sqlite3.connect(private)) as connection:
            connection.execute("UPDATE effectiveness_settings SET bao_count=54106 WHERE game_type='LOTO_5_35'")
            connection.commit()
        report = self.request('/api/ml/effectiveness?type=LOTO_5_35', cookie=self.member)
        self.assertEqual(report[0], 200, report[1])
        self.assertFalse(report[1]['settings']['configurationValid'])
        if not Path(CHROME).exists():
            self.fail('Chrome is required to verify recovered UI')
        with tempfile.TemporaryDirectory(prefix='bao-recovery-browser-') as directory:
            browser = Browser(CHROME, Path(directory))
            def wait(expression):
                for _ in range(160):
                    if browser.value(expression):
                        return
                    time.sleep(.05)
                self.fail('Browser timeout: ' + expression + ' ' + str(browser.value('window.baoErrors')))
            try:
                browser.call('Page.enable', page=True)
                browser.call('Network.enable', page=True)
                browser.call('Page.addScriptToEvaluateOnNewDocument', {'source': "window.baoErrors=[];addEventListener('error',e=>baoErrors.push(e.message));addEventListener('unhandledrejection',e=>baoErrors.push(String(e.reason)));const originalFetch=fetch;window.fetch=(input,options)=>{const url=new URL(typeof input==='string'?input:input.url,location.href);if(url.pathname.startsWith('/api/live-'))return Promise.resolve(new Response(JSON.stringify({ok:true,results:[],rows:[],history:[],meta:{}}),{headers:{'Content-Type':'application/json'}}));return originalFetch(input,options)}"}, page=True)
                browser.call('Network.setCookie', {'name': 'LOTTO_AUTH', 'value': self.member.split('=', 1)[1].split(';', 1)[0], 'url': self.url}, page=True)
                browser.call('Page.navigate', {'url': self.url}, page=True)
                wait("!!window.VietlottEffectiveness && typeof currentUser!=='undefined' && currentUser==='member_fixture'")
                self.assertEqual(browser.value("getComputedStyle(document.getElementById('accountOverlay')).display"), 'none')
                browser.value("window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:true}}));window.VietlottEffectiveness.activate(true);document.getElementById('effectivenessType').value='LOTO_5_35';document.getElementById('effectivenessType').dispatchEvent(new Event('change'))")
                wait("!document.getElementById('effectivenessSettings').disabled && document.getElementById('effectivenessBaoCount').value==='54.105'")
                browser.value("document.getElementById('effectivenessSettings').click()")
                self.assertEqual(browser.value("document.getElementById('effectivenessBaoCount').max"), '54105')
                self.assertIn('54.105 Vé Bao 6', browser.value("document.getElementById('effectivenessBaoCount').placeholder"))
                self.assertIn('5 số chính và số đặc biệt', browser.value("document.getElementById('effectivenessBaoCount').title"))
                self.assertEqual(browser.value("document.getElementById('effectivenessAdminSummary').textContent"), 'Chưa lưu · 54.105 Bao 6')
                browser.value("document.getElementById('effectivenessBaoCount').value='10';document.getElementById('effectivenessBaoCount').dispatchEvent(new Event('input'))")
                self.assertEqual(browser.value("document.getElementById('effectivenessAdminSummary').textContent"), 'Chưa lưu · 10 Bao 6')

                browser.value("document.getElementById('effectivenessBaoCount').value='100000000000000000000';document.getElementById('effectivenessBaoCount').dispatchEvent(new Event('input'))")
                self.assertEqual(browser.value("document.getElementById('effectivenessBaoCount').value"), '54.105')
                browser.value("document.getElementById('effectivenessBaoCount').dispatchEvent(new CompositionEvent('compositionstart'));document.getElementById('effectivenessBaoCount').value='999999999999999999999';document.getElementById('effectivenessBaoCount').dispatchEvent(new InputEvent('input',{isComposing:true,inputType:'insertCompositionText',data:'999999999999999999999'}));document.getElementById('effectivenessBaoCount').dispatchEvent(new CompositionEvent('compositionend'))")
                wait("document.getElementById('effectivenessBaoCount').value==='54.105'")
                self.assertNotIn('Vé con / phương pháp', browser.value("document.getElementById('effectivenessTicketQuote').textContent"))
                self.assertEqual(browser.value('window.baoErrors'), [])
                with closing(sqlite3.connect(private)) as connection:
                    self.assertEqual(connection.execute("SELECT bao_count FROM effectiveness_settings WHERE game_type='LOTO_5_35'").fetchone()[0], 54106)
                browser.value("document.getElementById('effectivenessBaoCount').value='2';document.getElementById('effectivenessBaoCount').dispatchEvent(new Event('input'));document.getElementById('effectivenessSave').click()")
                wait("document.getElementById('effectivenessAdminSummary').textContent==='Đang tắt · 2 Bao 6'")
                self.assertEqual(browser.value("document.getElementById('effectivenessAdminSummary').dataset.unsaved"), 'false')
                browser.value("document.getElementById('effectivenessEnabled').checked=true;document.getElementById('effectivenessEnabled').dispatchEvent(new Event('change'))")
                self.assertEqual(browser.value("document.getElementById('effectivenessAdminSummary').textContent"), 'Chưa lưu · 2 Bao 6')
                with closing(sqlite3.connect(private)) as connection:
                    self.assertEqual(connection.execute("SELECT bao_count,enabled FROM effectiveness_settings WHERE game_type='LOTO_5_35'").fetchone(), (2, 0))

            finally:
                browser.close()
