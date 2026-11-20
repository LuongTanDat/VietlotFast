"""Check draft cost math against actual billing rules without transferring money."""
import base64
import json
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ai.personal_tracking import quote
from tests.browser_cdp import Browser
from tests.test_prize_web import ROOT, CHROME


@unittest.skipUnless(Path(CHROME).exists(), 'Chrome required')
class EffectivenessCostPreviewTests(unittest.TestCase):
    def test_normal_bao_keno_wallet_updates_and_no_spending(self):
        calls = []
        source = (ROOT / 'frontend/vietlott-web.html').read_text(encoding='utf-8')
        section = source[source.index('      <section id="predictRootEffectiveness"'):source.index('      <section id="predictRootManual"')]
        page = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                '<link rel="stylesheet" href="/vietlott-web.css"><link rel="stylesheet" href="/vietlott-web-extra.css">'
                + section + '<script src="/vietlott-web-numeric.js"></script><script src="/vietlott-web-effectiveness.js"></script>')

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                calls.append(('GET', self.path))
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)
                if parsed.path == '/':
                    body, kind = page.encode(), 'text/html;charset=utf-8'
                elif parsed.path.startswith('/vietlott-web-') or parsed.path == '/vietlott-web.css':
                    body = (ROOT / 'frontend' / parsed.path[1:]).read_bytes()
                    kind = 'text/css' if parsed.path.endswith('.css') else 'application/javascript'
                else:
                    game = params.get('type', ['LOTO_5_35'])[0]
                    result = {'ok': True, 'type': game, 'progress': {'phase': 'idle'}, 'serverTimeMs': int(time.time()*1000)}
                    if parsed.path == '/api/ml/effectiveness':
                        result = {'ok': True, 'type': game, 'level': int(params.get('level', ['10'])[0]), 'canManage': True, 'baoVersion': 1,
                                  'settings': {'enabled': False, 'ticketCount': 10, 'normalTicketCount': 10, 'playMode': 'normal',
                                               'baoCount': 2, 'baoLevel': 6 if game == 'LOTO_5_35' else 7, 'maxBaoCounts': {'6': 54105, '7': 142857}},
                                  'counts': {'scored': 0, 'locked': 0, 'total': 0}, 'methods': [], 'cycles': [],
                                  'billing': {**quote(game, 10), 'owner': 'fixture', 'balance': 1000000, 'walletVersion': 1}}
                    body, kind = json.dumps(result).encode(), 'application/json'
                self.send_response(200)
                self.send_header('Content-Type', kind)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                calls.append(('POST', self.path))
                self.send_error(400)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        folder = ROOT / 'runtime/logs/effectiveness_cost_preview_20261115'
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='quote_browser_', dir=ROOT/'runtime') as profile:
            b = Browser(CHROME, Path(profile))
            try:
                b.call('Page.enable', page=True)
                b.call('Page.addScriptToEvaluateOnNewDocument', {'source': "window.quoteErrors=[];addEventListener('error',e=>quoteErrors.push(e.message))"}, page=True)
                b.call('Page.navigate', {'url': f'http://127.0.0.1:{server.server_port}/'}, page=True)

                def wait(expression):
                    for _ in range(200):
                        if b.value(expression):
                            return
                        time.sleep(.03)
                    self.fail(expression + '; ' + str(b.value('quoteErrors')))

                def amount(count):
                    b.value(f"document.getElementById('effectivenessTicketCount').value='{count}';document.getElementById('effectivenessTicketCount').dispatchEvent(new Event('input'))")

                def cost():
                    return b.value("document.querySelector('[data-quote-cost]')?.dataset.quoteCost")

                def remaining():
                    return b.value("document.querySelector('[data-quote-remaining]')?.dataset.quoteRemaining")

                wait('!!window.VietlottEffectiveness')
                b.value("document.getElementById('predictRootEffectiveness').hidden=false;VietlottEffectiveness.activate(true);dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:true}}))")
                wait("!!document.querySelector('[data-quote-cost]') && !document.getElementById('effectivenessRefresh').disabled")
                self.assertEqual(cost(), str(quote('LOTO_5_35', 10)['totalPayPal']))
                self.assertEqual(remaining(), '600000')
                b.value("document.getElementById('effectivenessSettings').click()")
                amount(20)
                self.assertEqual((cost(), remaining()), ('800000', '200000'))
                amount(30)
                self.assertEqual(remaining(), '-200000')
                self.assertTrue(b.value("document.getElementById('effectivenessLock').disabled"))
                amount(10)
                self.assertFalse(b.value("document.getElementById('effectivenessLock').disabled"))
                for owner, version, balance, expected in [('fixture', 2, 2000000, '1600000'), ('fixture', 1, 1, '1600000'), ('other', 5, 2, '1600000')]:
                    b.value(f"dispatchEvent(new CustomEvent('dvlf:prediction-wallet',{{detail:{{owner:'{owner}',walletVersion:{version},balance:{balance}}}}}))")
                    self.assertEqual(remaining(), expected)
                amount('')
                self.assertEqual(cost(), '')
                self.assertNotIn('NaN', b.value("document.getElementById('effectivenessTicketQuote').textContent"))
                amount(10)
                for theme in ['dark', 'light']:
                    b.value("document.body.classList.toggle('light-theme',"+str(theme=='light').lower()+")")
                    for width in [1440, 320]:
                        b.call('Emulation.setDeviceMetricsOverride', dict(width=width,height=1000,deviceScaleFactor=1,mobile=False),page=True)
                        shot = b.call('Page.captureScreenshot', dict(format='png'), page=True)
                        (folder / f'normal-{theme}-{width}.png').write_bytes(base64.b64decode(shot['data']))
                b.value("document.querySelector('[data-effectiveness-mode=bao]').click()")
                self.assertEqual((cost(), remaining()), ('480000', '1520000'))
                for theme in ['dark', 'light']:
                    b.value("document.body.classList.toggle('light-theme',"+str(theme=='light').lower()+")")
                    for width in [1440, 390, 320]:
                        b.call('Emulation.setDeviceMetricsOverride', dict(width=width,height=1000,deviceScaleFactor=1,mobile=False),page=True)
                        self.assertTrue(b.value("(()=>{const e=document.getElementById('effectivenessTicketQuote');return e.scrollWidth<=e.clientWidth+1})()"))
                        shot = b.call('Page.captureScreenshot', dict(format='png'), page=True)
                        (folder / f'quote-{theme}-{width}.png').write_bytes(base64.b64decode(shot['data']))
                b.value("document.getElementById('effectivenessType').value='KENO';document.getElementById('effectivenessType').dispatchEvent(new Event('change'))")
                wait("!!document.querySelector('[data-quote-cost]') && !document.getElementById('effectivenessRefresh').disabled")
                amount(2000)
                self.assertEqual(cost(), str(quote('KENO', 2000)['totalPayPal']))
                self.assertIn('10 bậc', b.value("document.getElementById('effectivenessTicketQuote').textContent"))
                b.value("dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:false}}))")
                self.assertTrue(b.value("document.getElementById('effectivenessTicketQuote').hidden"))
                self.assertEqual(b.value("document.getElementById('effectivenessTicketQuote').textContent"), '')
                self.assertEqual(b.value('quoteErrors'), [])
                self.assertTrue(all(method == 'GET' for method, _ in calls))
            finally:
                b.close()


if __name__ == '__main__':
    unittest.main()
