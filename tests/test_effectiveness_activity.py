import base64
import json
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tests.browser_cdp import Browser
from tests.test_prize_web import ROOT, CHROME


class EffectivenessActivityTests(unittest.TestCase):
    def test_four_phases_estimates_placement_errors_and_logout(self):
        source = (ROOT / 'frontend/vietlott-web.html').read_text(encoding='utf-8')
        section = source[source.index('      <section id="predictRootEffectiveness"'):source.index('      <section id="predictRootManual"')]
        page = '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/vietlott-web.css"><link rel="stylesheet" href="/vietlott-web-extra.css">' + section + '<script src="/vietlott-web-numeric.js"></script><script src="/vietlott-web-effectiveness.js"></script>'
        fixture = {'phase': 'idle', 'fail': False, 'stale': False, 'error': ''}
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                query = urllib.parse.urlsplit(self.path)
                params = urllib.parse.parse_qs(query.query)
                game = params.get('type', ['LOTO_5_35'])[0]
                requests.append(self.path)
                status, mime = 200, 'application/json'
                if query.path == '/':
                    body, mime = page.encode(), 'text/html; charset=utf-8'
                elif query.path == '/api/ml/effectiveness-progress':
                    body = json.dumps({'ok': True, 'type': game, 'serverTimeMs': int(time.time() * 1000), 'progress': {'phase': fixture['phase'], 'etaSeconds': 95, 'updatedAtMs': int(time.time() * 1000) - (30000 if fixture['stale'] else 0), 'error': fixture['error']}}).encode()
                elif query.path == '/api/ml/effectiveness':
                    if fixture['fail']:
                        body, status = b'{"ok":false,"message":"Failed to fetch"}', 500
                    else:
                        body = json.dumps({'ok': True, 'type': game, 'level': int(params.get('level', ['10'])[0]), 'canManage': True, 'settings': {'enabled': True, 'ticketCount': 200000}, 'counts': {'scored': 192, 'locked': 1}, 'methods': [], 'cycles': []}).encode()
                elif query.path.startswith('/vietlott-web-') or query.path == '/vietlott-web.css':
                    asset = ROOT / 'frontend' / Path(query.path).name
                    body, mime = asset.read_bytes(), 'text/css' if asset.suffix == '.css' else 'text/javascript'
                else:
                    body, status = b'{}', 404
                self.send_response(status)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory(prefix='activity_ui_', dir=ROOT / 'runtime') as folder:
                b = Browser(CHROME, Path(folder) / 'profile')

                def wait(expression):
                    end = time.monotonic() + 15
                    while time.monotonic() < end:
                        if b.value(expression):
                            return
                        time.sleep(.04)
                    self.fail('Timeout: ' + expression + ' ' + str(b.value('document.getElementById("effectivenessStatus").textContent')))

                def activate():
                    b.value('VietlottEffectiveness.activate(false);VietlottEffectiveness.activate(true)')

                try:
                    b.call('Page.enable', page=True)
                    b.call('Page.navigate', {'url': f'http://127.0.0.1:{server.server_port}/'}, page=True)
                    wait('!!window.VietlottEffectiveness')
                    b.value('document.getElementById("predictRootEffectiveness").hidden=false;window.dispatchEvent(new CustomEvent("dvlf:auth-changed",{detail:{authenticated:true}}));VietlottEffectiveness.activate(true)')
                    wait('document.getElementById("effectivenessPhase").textContent==="Đã cập nhật xong"')
                    for phase, text in [('updating', 'Đang cập nhật'), ('creating', 'Đang tạo vé'), ('scoring', 'Đang chấm điểm')]:
                        fixture['phase'] = phase
                        activate()
                        wait(f'document.getElementById("effectivenessPhase").textContent==={json.dumps(text)}')
                        wait('document.getElementById("effectivenessEta").textContent.startsWith("Ước tính 1p ")')
                        self.assertRegex(b.value('document.getElementById("effectivenessEta").textContent'), r'^Ước tính 1p \d+s$')
                    fixture['phase'] = 'creating'
                    b.value('document.getElementById("effectivenessType").value="KENO";document.getElementById("effectivenessType").dispatchEvent(new Event("change"))')
                    wait('document.getElementById("effectivenessPhase").textContent==="Đang tạo vé"&&!document.getElementById("effectivenessKenoLevelLabel").hidden')
                    images = ROOT / 'Bin/session_1_latest/balanced_toolbar_images'
                    images.mkdir(exist_ok=True)
                    for game in ('KENO', 'LOTO_5_35'):
                        b.value(f'document.getElementById("effectivenessType").value={json.dumps(game)};document.getElementById("effectivenessType").dispatchEvent(new Event("change"))')
                        wait('document.getElementById("predictRootEffectiveness").getAttribute("aria-busy")==="false"')
                        for width in (320, 390, 760, 900, 1024, 1440, 1920):
                            b.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False}, page=True)
                            for light in (False, True):
                                b.value(f'document.body.classList.toggle("light-theme",{str(light).lower()})')
                                bounds = b.value('(()=>{const a=document.getElementById("effectivenessActivity"),b=a.getBoundingClientRect(),t=document.querySelector(".effectiveness-toolbar-actions").getBoundingClientRect();return {withActions:!!a.closest(".effectiveness-action-group"),aboveButtons:b.bottom<=t.top,alignedRight:Math.abs(b.right-t.right)<2,compact:b.height<=30,overflow:document.documentElement.scrollWidth>innerWidth+1}})()')
                                self.assertTrue(bounds['withActions'] and bounds['aboveButtons'] and bounds['alignedRight'] and bounds['compact'] and not bounds['overflow'], (width, light, bounds))
                                self.assertTrue(b.value('(()=>{const ids=["effectivenessType",document.getElementById("effectivenessKenoLevelLabel").hidden?"effectivenessLimit":"effectivenessKenoLevel","effectivenessSummary","effectivenessRefresh","effectivenessSettings","effectivenessHelpButton"],rs=ids.map(id=>document.getElementById(id).getBoundingClientRect());return rs.every(r=>Math.abs(r.height-40)<1)&&(innerWidth<=900||rs.every(r=>Math.abs(r.bottom-rs[0].bottom)<1))})()'), (width, light))
                                if (width, light) in ((1440, False), (390, True)):
                                    b.call('Runtime.evaluate', {'expression': 'Promise.all([...document.querySelectorAll(".effectiveness-toolbar select")].flatMap(el=>el.getAnimations()).map(animation=>animation.finished.catch(()=>{})))', 'awaitPromise': True}, page=True)
                                    shot = b.call('Page.captureScreenshot', {'format': 'png'}, page=True)
                                    (images / f'{game}_{width}_{"light" if light else "dark"}.png').write_bytes(base64.b64decode(shot['data']))
                    fixture['stale'] = True
                    activate()
                    wait('document.getElementById("effectivenessActivity").dataset.phase==="error"')
                    self.assertIn('gián đoạn', b.value('document.getElementById("effectivenessStatus").textContent'))
                    self.assertIn('gián đoạn', b.value('document.getElementById("effectivenessActivity").title'))
                    self.assertLessEqual(b.value('document.getElementById("effectivenessActivity").getBoundingClientRect().height'), 30)
                    source_error = 'HTTPSConnectionPool(host="www.minhchinh.com", port=443): ' + 'Connection refused; ' * 30
                    fixture.update(stale=False, phase='idle', error=source_error)
                    activate()
                    wait('document.getElementById("effectivenessActivity").title.startsWith("HTTPSConnectionPool")')
                    self.assertEqual(b.value('document.getElementById("effectivenessActivity").title'), source_error)
                    self.assertTrue(b.value('getComputedStyle(document.getElementById("effectivenessStatus")).clipPath==="inset(50%)"&&document.getElementById("effectivenessActivity").getBoundingClientRect().height<=30&&document.documentElement.scrollWidth<=innerWidth+1'))
                    fixture.update(error='', fail=True)
                    activate()
                    wait('document.getElementById("effectivenessStatus").textContent.includes("Không kết nối")')
                    self.assertNotIn('Failed to fetch', b.value('document.getElementById("effectivenessActivity").textContent'))
                    self.assertNotEqual(b.value('document.getElementById("effectivenessPhase").textContent'), 'Đã cập nhật xong')
                    fixture['fail'] = False
                    activate()
                    wait('document.getElementById("effectivenessPhase").textContent==="Đã cập nhật xong"')
                    self.assertTrue(b.value('document.getElementById("effectivenessEta").hidden'))
                    b.value('window.dispatchEvent(new CustomEvent("dvlf:auth-changed",{detail:{authenticated:false}}))')
                    count = sum('/effectiveness-progress?' in item for item in requests)
                    time.sleep(3.2)
                    self.assertEqual(sum('/effectiveness-progress?' in item for item in requests), count)
                    proof = {'ok': True, 'normalPhases': 4, 'layouts': 28, 'equalControlHeights': 40, 'desktopControlsAligned': True, 'statusAboveActionButtons': True, 'alignedRight': True, 'errorsNotReportedAsSuccess': True, 'errorDetailsInTooltip': True, 'logoutStopsPolling': True}
                    (ROOT / 'Bin/session_1_latest/balanced_toolbar_ui_verification.json').write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8')
                finally:
                    b.close()
        finally:
            server.shutdown()
            server.server_close()
