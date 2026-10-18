"""Chrome checks for effectiveness report states without changing real accounts."""
import importlib.util
import json
import base64
import os
import urllib.parse
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROOT = Path(__file__).resolve().parents[1]
CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
CDP_HELPER = ROOT / "tests/browser_cdp.py"


@unittest.skipUnless(CHROME.exists() and CDP_HELPER.exists(), "Chrome/CDP helper unavailable")
class EffectivenessFrontendTests(unittest.TestCase):
    def test_empty_scored_pending_admin_and_account_change(self):
        spec = importlib.util.spec_from_file_location("effectiveness_cdp", CDP_HELPER)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        keys = ["web", "random", "bayesian", "ewma"]
        report = {
            "ok": True, "type": "LOTO_6_45", "label": "Mega 6/45", "canManage": False,
            "settings": {"enabled": False, "ticketCount": 2, "engine": "classic"},
            "counts": {"scored": 0, "locked": 0, "total": 0},
            "methods": [{"key": key, "sampleCount": 0, "meanHits": None,
                         "decision": "insufficient_evidence"} for key in keys], "cycles": [],
        }
        requests = []
        html = (ROOT / "frontend/vietlott-web.html").read_text(encoding="utf-8")
        section = html[html.index('      <section id="predictRootEffectiveness"'):html.index('      <section id="predictRootManual"')]
        page = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
                "<link rel=stylesheet href=/vietlott-web.css><link rel=stylesheet href=/vietlott-web-extra.css>"
                + section + "<script src=/vietlott-web-numeric.js></script><script src=/vietlott-web-effectiveness.js></script>")

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, body, content_type, status=200):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    pass  # Superseded fetches deliberately abort their connections.

            def do_GET(self):
                if self.path.startswith("/api/ml/effectiveness-tickets?"):
                    requests.append(("GET", self.path, ""))
                    params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                    ticket_page = int(params.get("page", [1])[0])
                    prize_code = params.get('prizeCode', [None])[0]
                    winners = {'prize_summary_fixture':[37],'method_random_fixture':[73,75,88],'method_bayesian_fixture':[95],'method_ewma_fixture':[9994]}.get(params['predictionId'][0], [1])
                    cursor = int(params.get('afterTicketIndex', [0])[0])
                    jump_index = next((index for index in winners if index > cursor), winners[0]) if prize_code else None
                    if jump_index:
                        ticket_page = (jump_index - 1) // 10 + 1
                    offset = (ticket_page - 1) * 10
                    tickets = [{"main": [1, 2, 3, 4, 5, 6]} for _ in range(10)]
                    return self.respond(json.dumps({"ok": True, "type": report["type"], "predictionId": params["predictionId"][0],
                        "tickets": tickets, "ticketResults": [{"ticketIndex": offset + index + 1, "status": "won" if offset+index+1==jump_index else "pending", "prizeCode":prize_code if offset+index+1==jump_index else "PENDING", "prizeLabel":prize_code if offset+index+1==jump_index else "Chờ kết quả"} for index in range(10)],
                        **({'jumpTicketIndex':jump_index} if jump_index else {}),
                        "ticketPagination": {"page": ticket_page, "pageSize": 10, "offset": offset, "total": 10000, "totalPages": 1000}}).encode(), "application/json")
                if self.path.startswith("/api/ml/effectiveness?"):
                    requests.append(("GET", self.path, ""))
                    payload = json.loads(json.dumps(report))
                    if report["type"] == "KENO":
                        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                        level = int(params.get("level", [10])[0])
                        if report.get("_rejectLevel") == level:
                            return self.respond(b'{"ok":false,"message":"Fixture source unavailable"}', "application/json", 503)
                        page_number = int(params.get("page", [1])[0])
                        if level == 9:
                            time.sleep(.3)  # A superseded request must not replace the selected level.
                        payload["level"] = level
                        total = len(payload["cycles"]) if report.get("_manyCycles") else 21
                        payload["pagination"] = {"page": page_number, "pageSize": 10, "totalPages": (total + 9) // 10, "total": total}
                        payload["cycles"] = payload["cycles"][(page_number - 1) * 10:page_number * 10] if report.get("_manyCycles") else payload["cycles"][:1]
                        for cycle in payload["cycles"]:
                            if not report.get("_manyCycles"):
                                cycle["targetDrawId"] = str(300 - page_number)
                            for entry in cycle["methods"].values():
                                if report.get('_keepMethodTickets'):
                                    continue
                                entry["tickets"] = [{"main": list(range(1 + index, level + 1 + index)), "special": None} for index in range(3)]
                                entry["ticketResults"] = [{"ticketIndex": index + 1, "status": "won", "prizeLabel": f"Trúng {level}/{level} số"} for index in range(3)]
                    elif report.get("_manyCycles"):
                        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                        payload["cycles"] = payload["cycles"][:int(params.get("limit", [100])[0])]
                    return self.respond(json.dumps(payload).encode(), "application/json")
                if self.path == "/":
                    return self.respond(page.encode(), "text/html;charset=utf-8")
                asset = ROOT / "frontend" / self.path.lstrip("/")
                if asset.is_file() and asset.parent == ROOT / "frontend":
                    return self.respond(asset.read_bytes(), "text/css" if asset.suffix == ".css" else "text/javascript")
                self.respond(b"", "text/plain", 404)

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"])).decode()
                requests.append(("POST", self.path, body))
                if self.path.endswith("cycle"):
                    return self.respond(json.dumps({"ok": False, "message": "Kỳ tiếp theo đã quá hạn khóa."}).encode(), "application/json", 400)
                return self.respond(b'{"ok":true}', "application/json")

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        runtime = ROOT / "runtime"
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="effectiveness_ui_", dir=runtime) as directory:
            profile = Path(directory)
            self.assertTrue(profile.resolve().is_relative_to(runtime.resolve()))
            browser = helper.Browser(str(CHROME), profile)
            try:
                browser.call("Page.enable", page=True)
                browser.call("Page.addScriptToEvaluateOnNewDocument", {"source": "window.uiErrors=[];window.addEventListener('error',e=>uiErrors.push(e.message));window.addEventListener('unhandledrejection',e=>uiErrors.push(String(e.reason)));"}, page=True)
                browser.call("Page.navigate", {"url": f"http://127.0.0.1:{server.server_port}/"}, page=True)

                def wait(expression):
                    for _ in range(100):
                        if browser.value(expression):
                            return
                        time.sleep(.05)
                    self.fail("Browser condition timed out: " + expression)

                wait("!!window.VietlottEffectiveness")
                self.assertEqual(requests, [])
                browser.value("document.getElementById('predictRootEffectiveness').hidden=false;document.getElementById('effectivenessType').value='LOTO_6_45';VietlottEffectiveness.activate(true);window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:true,user:'fixture'}}))")
                wait("!!document.querySelector('.effectiveness-empty')")
                self.assertTrue(browser.value("document.getElementById('effectivenessAdmin').hidden"))
                self.assertTrue(browser.value("document.getElementById('effectivenessSettings').hidden"))
                self.assertTrue(browser.value("document.getElementById('effectivenessKenoLevels').hidden"))
                self.assertEqual(browser.value("document.querySelectorAll('#effectivenessComparison .effectiveness-comparison-table tbody tr').length"), 4)
                comparison = "#effectivenessComparison > .effectiveness-comparison-panel"
                self.assertFalse(browser.value(f"document.querySelector('{comparison}').open"))
                self.assertEqual(browser.value(f"document.querySelector('{comparison} .effectiveness-table-wrap').getBoundingClientRect().height"), 0)
                browser.value(f"document.querySelector('{comparison} > summary').click()")
                self.assertTrue(browser.value(f"document.querySelector('{comparison}').open"))
                self.assertGreater(browser.value(f"document.querySelector('{comparison} .effectiveness-table-wrap').getBoundingClientRect().height"), 0)
                browser.value(f"document.querySelector('{comparison} > summary').focus()")
                browser.call('Input.dispatchKeyEvent', {'type':'keyDown','key':'Enter','code':'Enter','windowsVirtualKeyCode':13,'text':'\r'}, page=True)
                browser.call('Input.dispatchKeyEvent', {'type':'keyUp','key':'Enter','code':'Enter','windowsVirtualKeyCode':13}, page=True)
                wait(f"!document.querySelector('{comparison}').open")
                self.assertFalse(browser.value(f"document.querySelector('{comparison}').open"))
                browser.value(f"document.querySelector('{comparison} > summary').click()")
                self.assertNotIn("NaN", browser.value("document.getElementById('effectivenessComparison').textContent"))
                self.assertTrue(all(item[0] == "GET" for item in requests))
                self.assertFalse(browser.value("document.getElementById('effectivenessHelpButton').hidden"))
                self.assertEqual(browser.value("document.getElementById('effectivenessHelpPanel').getBoundingClientRect().height"), 0)
                browser.value("document.getElementById('effectivenessHelpButton').click()")
                self.assertTrue(browser.value("document.getElementById('effectivenessHelpPanel').open"))
                self.assertEqual(browser.value("document.getElementById('effectivenessHelpButton').getAttribute('aria-expanded')"), 'true')
                self.assertIn('Bảng so sánh dùng tất cả', browser.value("document.getElementById('effectivenessHelpPanel').textContent"))
                browser.value("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
                self.assertFalse(browser.value("document.getElementById('effectivenessHelpPanel').open"))
                self.assertEqual(browser.value('document.activeElement.id'), 'effectivenessHelpButton')
                for key_type in ('keyDown', 'keyUp'):
                    key_event = {'type': key_type, 'key': 'Enter', 'code': 'Enter', 'windowsVirtualKeyCode': 13, 'nativeVirtualKeyCode': 13}
                    if key_type == 'keyDown':
                        key_event['text'] = '\r'
                    browser.call('Input.dispatchKeyEvent', key_event, page=True)
                wait("document.getElementById('effectivenessHelpPanel').open")
                browser.value("document.getElementById('effectivenessTitle').click()")
                self.assertFalse(browser.value("document.getElementById('effectivenessHelpPanel').open"))
                self.assertEqual(browser.value("document.getElementById('effectivenessHelpButton').getAttribute('aria-expanded')"), 'false')

                report["canManage"] = True
                report["mixedConfigurations"] = True
                report["configurationCount"] = 3
                report["notes"] = ["Brier dùng xác suất biên chưa hiệu chỉnh.", "<img src=x onerror=alert(1)>"]
                report["counts"] = {"scored": 2, "locked": 1, "total": 3}
                report["methods"] = [{"key": key, "label": "<img src=x onerror=alert(1)>" if key == "web" else key,
                                      "sampleCount": 2, "meanHits": 1.5, "rate3": .25,
                                      "rate4": .1, "deltaVsRandom": .2, "ci95": {"lower": -.1, "upper": .5},
                                      "decision": "no_clear_advantage", "brierScore": None} for key in keys]
                for draw in (105, 104, 103):
                    scored = draw != 105
                    report["cycles"].append({"targetDrawId": str(draw), "cutoffDrawId": str(draw - 1),
                        "createdAt": "2026-10-04T05:00:00Z", "deadline": "2026-10-04T11:00:00Z",
                        "status": "scored" if scored else "locked", "actualMain": [1, 2, 3, 4, 5, 6] if scored else [],
                        "methods": {key: {"tickets": [{"main": [1, 2, 10, 11, 12, 13], "special": None}, {"main": [2, 20, 21, 22, 23, 24]}],
                            "meanHits": 2.35 + keys.index(key) * .2 + (draw - 103) * .05 if scored else None, "bestHits": 3 if scored else None,
                            "engine": key, "modelId": "fixture_model"} for key in keys}})
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait("document.querySelectorAll('.effectiveness-cycle').length===3")
                self.assertFalse(browser.value("document.getElementById('effectivenessAdmin').hidden"))
                self.assertFalse(browser.value("document.getElementById('effectivenessSettings').hidden"))
                self.assertFalse(browser.value("document.getElementById('effectivenessAdmin').open"))
                self.assertEqual(browser.value("document.getElementById('effectivenessAdmin').getBoundingClientRect().height"), 0)
                mutations_before = sum(method == "POST" for method, _, _ in requests)
                browser.value("document.getElementById('effectivenessHelpButton').click()")
                browser.value("document.getElementById('effectivenessSettings').click()")
                self.assertFalse(browser.value("document.getElementById('effectivenessHelpPanel').open"))
                self.assertTrue(browser.value("document.getElementById('effectivenessAdmin').open"))
                self.assertEqual(browser.value("document.getElementById('effectivenessSettings').getAttribute('aria-expanded')"), "true")
                self.assertEqual(browser.value("document.activeElement.id"), "effectivenessEnabled")
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').max"), "1000000")
                self.assertEqual(browser.value("document.getElementById('effectivenessEnabled').getAttribute('role')"), "switch")
                browser.value("document.getElementById('effectivenessEnabled').checked=true")
                self.assertEqual(browser.value("getComputedStyle(document.querySelector('.effectiveness-tracking-state'),'::after').content"), '"Bật"')
                self.assertEqual(browser.value("getComputedStyle(document.querySelector('.effectiveness-tracking-state')).backgroundColor"), 'rgb(16, 62, 48)')
                browser.value("document.getElementById('effectivenessEnabled').click()")
                self.assertEqual(browser.value("getComputedStyle(document.querySelector('.effectiveness-tracking-state'),'::after').content"), '"Tắt"')
                self.assertEqual(browser.value("getComputedStyle(document.querySelector('.effectiveness-tracking-state')).backgroundColor"), 'rgb(77, 29, 39)')
                browser.value("document.getElementById('effectivenessTicketCount').value='';document.getElementById('effectivenessTicketCount').dispatchEvent(new Event('input'))")
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').placeholder"), 'Max 1.000.000')
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').value"), '')
                browser.value("document.getElementById('effectivenessTicketCount').focus()")
                for composing in ('2', '20', '200', '2000', '20000', '200000'):
                    browser.call('Input.imeSetComposition', {'text': composing, 'selectionStart': len(composing), 'selectionEnd': len(composing)}, page=True)
                    self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').value"), f'{int(composing):,}'.replace(',', '.'))
                browser.call('Input.insertText', {'text': '200000'}, page=True)
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').value"), '200.000')
                browser.value("document.getElementById('effectivenessTicketCount').value='';document.getElementById('effectivenessTicketCount').dispatchEvent(new Event('input'))")
                for digit, expected in zip('500000', ('5', '50', '500', '5.000', '50.000', '500.000')):
                    browser.call("Input.insertText", {"text": digit}, page=True)
                    self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').value"), expected)
                browser.value("document.getElementById('effectivenessTicketCount').setSelectionRange(4,4)")
                for expected in ('500.000', '50.000'):
                    for event_type in ('keyDown', 'keyUp'):
                        browser.call('Input.dispatchKeyEvent', {'type': event_type, 'key': 'Backspace', 'code': 'Backspace', 'windowsVirtualKeyCode': 8, 'nativeVirtualKeyCode': 8}, page=True)
                    self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').value"), expected)
                browser.value("document.getElementById('effectivenessTicketCount').select()")
                browser.call("Input.insertText", {"text": '500000'}, page=True)
                browser.value("document.getElementById('effectivenessTicketCount').setSelectionRange(1,2)")
                browser.call("Input.insertText", {"text": '1'}, page=True)
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').value"), '510.000')
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').selectionStart"), 2)
                browser.value("document.getElementById('effectivenessTicketCount').select()")
                browser.call("Input.insertText", {"text": '0500.000'}, page=True)
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').value"), '500.000')
                browser.value("document.getElementById('effectivenessTicketCount').select()")
                browser.call("Input.insertText", {"text": "1000001"}, page=True)
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').value"), '1.000.000')
                self.assertEqual(sum(method == "POST" for method, _, _ in requests), mutations_before)
                browser.value("document.getElementById('effectivenessSave').click()")
                wait("!document.getElementById('effectivenessRefresh').disabled")
                self.assertTrue(any(method == 'POST' and 'ticketCount=1000000' in body and 'enabled=false' in body for method, _, body in requests))
                mutations_before = sum(method == 'POST' for method, _, _ in requests)
                browser.value("document.getElementById('effectivenessTicketCount').value='4';document.getElementById('effectivenessEnabled').checked=true;document.getElementById('effectivenessRefresh').click()")
                wait("!document.getElementById('effectivenessRefresh').disabled")
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').value"), "4")
                self.assertTrue(browser.value("document.getElementById('effectivenessEnabled').checked"))
                browser.value("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
                self.assertFalse(browser.value("document.getElementById('effectivenessAdmin').open"))
                self.assertEqual(browser.value("document.activeElement.id"), "effectivenessSettings")
                self.assertEqual(browser.value("document.getElementById('effectivenessSettings').getAttribute('aria-expanded')"), "false")
                browser.value("document.getElementById('effectivenessSettings').click();document.getElementById('effectivenessHelpButton').click()")
                self.assertFalse(browser.value("document.getElementById('effectivenessAdmin').open"))
                self.assertTrue(browser.value("document.getElementById('effectivenessHelpPanel').open"))
                browser.value("document.getElementById('effectivenessHelpButton').click()")
                self.assertFalse(browser.value("document.getElementById('effectivenessHelpPanel').open"))
                browser.value("document.getElementById('effectivenessSettings').click();document.getElementById('effectivenessTitle').click()")
                self.assertFalse(browser.value("document.getElementById('effectivenessAdmin').open"))
                self.assertEqual(sum(method == "POST" for method, _, _ in requests), mutations_before)
                self.assertFalse(browser.value("document.getElementById('effectivenessTimeline').hidden"))
                self.assertEqual(browser.value("document.querySelectorAll('#effectivenessComparison img').length"), 0)
                self.assertIn("Gộp 3 cấu hình / ngân sách", browser.value("document.getElementById('effectivenessMixedWarning').textContent"))
                self.assertIn("chưa hiệu chỉnh", browser.value("document.getElementById('effectivenessReportNotes').textContent"))
                self.assertEqual(browser.value("document.querySelectorAll('#effectivenessReportNotes img').length"), 0)
                self.assertEqual(browser.value("document.querySelectorAll('.effectiveness-cycle:first-child .is-hit').length"), 0)
                self.assertEqual(browser.value("document.querySelectorAll('.effectiveness-cycle:nth-child(2) .is-hit').length"), 12)
                self.assertIn("fixture_model", browser.value("document.querySelector('.effectiveness-cycle').textContent"))
                self.assertEqual(browser.value("document.querySelectorAll('#effectivenessCycles .effectiveness-cycle[open]').length"), 0)
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle-toggle .when-closed').innerText"), "Mở rộng")
                browser.value("document.querySelector('.effectiveness-cycle-toggle').click()")
                self.assertTrue(browser.value("document.querySelector('.effectiveness-cycle').open"))
                self.assertNotEqual(browser.value("getComputedStyle(document.querySelector('.effectiveness-cycle-toggle .when-open')).display"), "none")
                self.assertEqual(browser.value("getComputedStyle(document.querySelector('.effectiveness-cycle-toggle .when-closed')).display"), "none")
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait("!document.getElementById('effectivenessRefresh').disabled")
                self.assertTrue(browser.value("document.querySelector('.effectiveness-cycle').open"))
                cycle_requests = len(requests)
                browser.value("document.querySelector('.effectiveness-cycle-toggle').click()")
                self.assertFalse(browser.value("document.querySelector('.effectiveness-cycle').open"))
                self.assertNotEqual(browser.value("getComputedStyle(document.querySelector('.effectiveness-cycle-toggle .when-closed')).display"), "none")
                self.assertEqual(len(requests), cycle_requests)
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle .effectiveness-ticket-hits').textContent"), "—")
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-ticket-hits').textContent"), "2/6")
                self.assertFalse(browser.value("document.querySelector('.effectiveness-provenance').open"))
                self.assertFalse(browser.value("document.querySelector('.effectiveness-help').open"))
                timeline_scale = browser.value("(()=>{const svg=document.querySelector('#effectivenessTimeline svg');return {min:Number(svg.dataset.axisMin),max:Number(svg.dataset.axisMax),step:Number(svg.dataset.axisStep),label:document.querySelector('.effectiveness-chart-range').textContent,points:[...svg.querySelectorAll('circle')].map(node=>Number(node.getAttribute('cy')))}})()")
                self.assertGreater(timeline_scale["min"], 0)
                self.assertLess(timeline_scale["max"], 6)
                self.assertLess(timeline_scale["step"], 1)
                self.assertEqual(timeline_scale["label"].strip(), "Trạng thái: Hiện tại")
                self.assertGreater(max(timeline_scale["points"]) - min(timeline_scale["points"]), 30)
                scale_button_style = browser.value("(()=>{const b=document.querySelector('[data-effectiveness-scale-toggle]'),r=b.getBoundingClientRect(),s=getComputedStyle(b),p=getComputedStyle(b,'::before');return {width:r.width,height:r.height,radius:parseFloat(s.borderRadius),display:s.display,dotWidth:parseFloat(p.width),dotColor:p.backgroundColor}})()")
                self.assertLess(scale_button_style["width"], 130)
                self.assertLessEqual(scale_button_style["height"], 30)
                self.assertGreater(scale_button_style["radius"], 12)
                self.assertEqual(scale_button_style["display"], "flex")
                self.assertEqual(scale_button_style["dotWidth"], 6)
                browser.value("document.querySelector('[data-effectiveness-scale-toggle]').click()")
                self.assertEqual(browser.value("document.querySelector('#effectivenessTimeline svg').dataset.axisMin"), "0")
                self.assertEqual(browser.value("document.querySelector('#effectivenessTimeline svg').dataset.axisMax"), "6")
                self.assertEqual(browser.value("document.querySelector('[data-effectiveness-scale-toggle]').textContent.trim()"), "Trạng thái: Tất cả")
                self.assertEqual(browser.value("document.querySelector('[data-effectiveness-scale-toggle]').getAttribute('aria-pressed')"), "true")
                self.assertNotEqual(browser.value("getComputedStyle(document.querySelector('[data-effectiveness-scale-toggle]'),'::before').backgroundColor"), scale_button_style["dotColor"])
                browser.value("document.querySelector('[data-effectiveness-scale-toggle]').click()")
                self.assertGreater(browser.value("Number(document.querySelector('#effectivenessTimeline svg').dataset.axisMin)"), 0)
                self.assertLess(browser.value("Number(document.querySelector('#effectivenessTimeline svg').dataset.axisMax)"), 6)
                self.assertEqual(browser.value("document.querySelector('[data-effectiveness-scale-toggle]').textContent.trim()"), "Trạng thái: Hiện tại")
                self.assertEqual(browser.value("document.querySelector('[data-effectiveness-scale-toggle]').getAttribute('aria-pressed')"), "false")
                browser.value("['web','random','bayesian','ewma'].forEach(key=>document.querySelector(`[data-effectiveness-line=${key}]`).click())")
                self.assertEqual(browser.value("document.querySelector('#effectivenessTimeline svg').dataset.axisMin"), "0")
                self.assertEqual(browser.value("document.querySelector('#effectivenessTimeline svg').dataset.axisMax"), "6")
                self.assertEqual(browser.value("document.querySelector('.effectiveness-chart-range').textContent.trim()"), "Trạng thái: Hiện tại")
                browser.value("['web','random','bayesian','ewma'].forEach(key=>document.querySelector(`[data-effectiveness-line=${key}]`).click())")
                timeline_artifact_dir = os.environ.get("LOTTO_TIMELINE_ZOOM_ARTIFACT_DIR")
                if timeline_artifact_dir:
                    output = Path(timeline_artifact_dir).resolve()
                    self.assertTrue(output.is_relative_to(ROOT.resolve()))
                    output.mkdir(parents=True, exist_ok=True)
                    browser.value("document.querySelector('#effectivenessTimeline details').open=true")
                    for theme, width in (("dark", 1440), ("light", 390)):
                        browser.value(f"document.body.classList.toggle('light-theme',{str(theme == 'light').lower()})")
                        browser.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": width < 500}, page=True)
                        clip = browser.value("(()=>{const r=document.getElementById('effectivenessTimeline').getBoundingClientRect();return {x:r.left+scrollX,y:r.top+scrollY,width:r.width,height:r.height,scale:1}})()")
                        screenshot = browser.call("Page.captureScreenshot", {"format": "png", "clip": clip, "captureBeyondViewport": True}, page=True)
                        (output / f"timeline_zoom_{theme}_{width}.png").write_bytes(base64.b64decode(screenshot["data"]))
                    browser.value("document.body.classList.remove('light-theme')")
                    browser.call("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False}, page=True)
                    browser.value("document.querySelector('#effectivenessTimeline details').open=false")
                fold_selectors = ['#effectivenessComparison > details', '#effectivenessTimeline > details', '#effectivenessLab']
                self.assertTrue(browser.value("!document.querySelector('#effectivenessTimeline > details').open && !document.getElementById('effectivenessLab').open"))
                for selector in fold_selectors:
                    browser.value(f"document.querySelector('{selector}').open=false")
                    browser.value(f"document.querySelector('{selector} > summary').click()")
                    self.assertTrue(browser.value(f"document.querySelector('{selector}').open"))
                    self.assertIn('Thu gọn', browser.value(f"document.querySelector('{selector} > summary').innerText"))
                    browser.value(f"document.querySelector('{selector} > summary').click()")
                    self.assertFalse(browser.value(f"document.querySelector('{selector}').open"))
                    self.assertIn('Mở rộng', browser.value(f"document.querySelector('{selector} > summary').innerText"))
                for theme in ('dark', 'light'):
                    browser.value(f"document.body.classList.toggle('light-theme',{str(theme=='light').lower()})")
                    for width in (320, 1440):
                        browser.call('Emulation.setDeviceMetricsOverride', {'width':width,'height':1000,'deviceScaleFactor':1,'mobile':False}, page=True)
                        measurements = browser.value("[...document.querySelectorAll('.effectiveness-fold > summary')].map(s=>{const r=s.getBoundingClientRect(),b=s.querySelector('.effectiveness-fold-toggle').getBoundingClientRect();return {height:r.height,width:b.width,right:b.right,title:s.querySelector('strong').getBoundingClientRect().right,left:b.left,buttonVisible:!!b.height}})")
                        self.assertEqual(len(measurements), 3)
                        self.assertLess(max(m['height'] for m in measurements)-min(m['height'] for m in measurements), 1)
                        self.assertLess(max(m['width'] for m in measurements)-min(m['width'] for m in measurements), 1)
                        self.assertLess(max(m['right'] for m in measurements)-min(m['right'] for m in measurements), 1)
                        self.assertTrue(all(m['buttonVisible'] and m['title']<=m['left'] for m in measurements))
                        artifact_dir = os.environ.get('LOTTO_FOLD_HEADERS_ARTIFACT_DIR')
                        if artifact_dir:
                            output=Path(artifact_dir).resolve(); self.assertTrue(output.is_relative_to(ROOT.resolve())); output.mkdir(parents=True,exist_ok=True)
                            clip=browser.value("(()=>{let a=document.querySelector('#effectivenessComparison').getBoundingClientRect(),b=document.getElementById('effectivenessLab').getBoundingClientRect();return {x:a.left+scrollX,y:a.top+scrollY,width:a.width,height:b.bottom-a.top,scale:1}})()")
                            screenshot=browser.call('Page.captureScreenshot', {'format':'png','clip':clip,'captureBeyondViewport':True}, page=True)
                            (output/f'fold_headers_{theme}_{width}.png').write_bytes(base64.b64decode(screenshot['data']))
                browser.value("document.body.classList.remove('light-theme')")
                browser.call('Emulation.setDeviceMetricsOverride', {'width':1440,'height':1000,'deviceScaleFactor':1,'mobile':False}, page=True)
                browser.value("document.querySelector('#effectivenessTimeline details').open=true;document.querySelector('[data-effectiveness-line=web]').click()")
                self.assertEqual(browser.value("document.querySelector('[data-effectiveness-line=web]').getAttribute('aria-pressed')"), "false")
                self.assertTrue(browser.value("document.querySelector('#effectivenessTimeline details').open"))
                browser.value("document.getElementById('effectivenessSettings').click();document.getElementById('effectivenessTicketCount').value='2';document.getElementById('effectivenessSave').click()")
                wait("document.getElementById('effectivenessStatus').textContent.includes('Đã lưu cấu hình')")
                self.assertTrue(any(method == "POST" and path.endswith("settings") and "ticketCount=2" in body for method, path, body in requests))
                browser.value("document.getElementById('effectivenessLock').click()")
                wait("document.getElementById('effectivenessStatus').textContent.includes('quá hạn khóa')")
                self.assertEqual(browser.value("document.getElementById('effectivenessStatus').dataset.kind"), "error")

                for cycle in report["cycles"]:
                    cycle["config"] = {"ticketCount": 10}
                    for entry in cycle["methods"].values():
                        entry["modelId"] = "model_" + "long_version_" * 50 + "<img src=x>"
                        entry["tickets"] = [{"main": [10, 11, 12, 13, 14, 15], "special": 7} for _ in range(10)]
                        if cycle["status"] == "scored":
                            entry["meanHits"] = entry["bestHits"] = 0
                browser.value("document.querySelector('.effectiveness-cycle').open=false;document.querySelector('.effectiveness-cycle:nth-child(2)').open=true;document.getElementById('effectivenessRefresh').click()")
                wait("document.querySelectorAll('.effectiveness-cycle:first-child .effectiveness-ticket-row').length===40")
                self.assertFalse(browser.value("document.querySelector('.effectiveness-cycle').open"))
                self.assertTrue(browser.value("document.querySelector('.effectiveness-cycle:nth-child(2)').open"))
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-ticket-hits').textContent"), "0/6")
                self.assertIn("10 vé / phương pháp", browser.value("document.querySelector('.effectiveness-cycle .effectiveness-cycle-preview').textContent"))
                self.assertEqual(browser.value("document.querySelectorAll('.effectiveness-cycle img').length"), 0)
                for width in (320, 390, 1440):
                    browser.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": width < 500}, page=True)
                    self.assertTrue(browser.value("document.documentElement.scrollWidth<=window.innerWidth+2"), f"Page overflows at {width}px")
                    browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-provenance').open=true")
                    self.assertTrue(browser.value("document.documentElement.scrollWidth<=window.innerWidth+2"), f"Long provenance overflows at {width}px")
                self.assertTrue(browser.value("document.querySelector('[data-effectiveness-line=web]').getBoundingClientRect().width<180"))
                browser.value("document.querySelector('.effectiveness-cycle:nth-child(2)').open=false;document.getElementById('effectivenessRefresh').click()")
                wait("!document.getElementById('effectivenessRefresh').disabled")
                self.assertFalse(browser.value("document.querySelector('.effectiveness-cycle').open"))
                self.assertFalse(browser.value("document.querySelector('.effectiveness-cycle:nth-child(2)').open"))
                browser.value("window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:false}}))")
                self.assertTrue(browser.value("document.getElementById('effectivenessAdmin').hidden"))
                self.assertTrue(browser.value("document.getElementById('effectivenessSettings').hidden"))
                self.assertFalse(browser.value("document.getElementById('effectivenessAdmin').open"))
                self.assertEqual(browser.value("document.getElementById('effectivenessCycles').textContent"), "")
                self.assertEqual(browser.value("document.getElementById('effectivenessReportNotes').textContent"), "")
                self.assertEqual(browser.value("document.getElementById('effectivenessMixedWarning').textContent"), "")
                report["canManage"] = False
                browser.value("window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:true,user:'second'}}))")
                wait("document.querySelectorAll('.effectiveness-cycle').length===3")
                self.assertEqual(browser.value("document.querySelectorAll('#effectivenessCycles .effectiveness-cycle[open]').length"), 0)
                self.assertTrue(browser.value("document.getElementById('effectivenessAdmin').hidden"))
                report["type"] = "LOTO_5_35"
                for cycle in report["cycles"]:
                    if cycle["status"] == "scored":
                        cycle["actualMain"] = [1, 2, 3, 4, 5]
                        cycle["actualSpecial"] = 1
                    for entry in cycle["methods"].values():
                        entry["tickets"] = [{"main": [10, 11, 12, 13, 14], "special": 1}]
                        entry["ticketResults"] = [{"ticketIndex": 1, "status": "won" if cycle["status"] == "scored" else "pending",
                            "prizeLabel": "Giải Khuyến Khích" if cycle["status"] == "scored" else "Chờ kết quả",
                            "specialMatched": cycle["status"] == "scored"}]
                browser.value("document.getElementById('effectivenessType').value='LOTO_5_35';document.getElementById('effectivenessType').dispatchEvent(new Event('change'))")
                wait("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-ticket-hits')?.textContent==='0/5'")
                actual_selector = '.effectiveness-cycle:nth-child(2) > summary .effectiveness-actual-numbers'
                self.assertEqual(browser.value(f"document.querySelector('{actual_selector} .effectiveness-actual-separator').textContent"), '|')
                self.assertEqual(browser.value(f"document.querySelector('{actual_selector} .effectiveness-actual-special-ball').getAttribute('aria-label')"), 'ĐB 01')
                for theme in ('dark', 'light'):
                    browser.value(f"document.body.classList.toggle('light-theme',{str(theme=='light').lower()})")
                    for width in (320, 1440):
                        browser.call('Emulation.setDeviceMetricsOverride', {'width':width,'height':1000,'deviceScaleFactor':1,'mobile':False}, page=True)
                        positions = browser.value(f"[...document.querySelectorAll('{actual_selector} .effectiveness-ball')].map(e=>{{const r=e.getBoundingClientRect();return {{y:r.top+r.height/2,width:r.width,height:r.height}}}})")
                        self.assertEqual(len(positions), 6)
                        self.assertLess(max(p['y'] for p in positions)-min(p['y'] for p in positions), 1)
                        self.assertTrue(all(p['width']==p['height']==26 for p in positions))
                        colors = browser.value(f"[...document.querySelectorAll('{actual_selector} .effectiveness-ball')].map(e=>getComputedStyle(e).backgroundColor)")
                        self.assertEqual(colors[:5], ["rgb(156, 231, 187)" if theme == "dark" else "rgb(198, 234, 211)"] * 5)
                        self.assertEqual(colors[5], "rgb(255, 215, 106)")
                        if width == 1440:
                            layout = browser.value("(()=>{let s=document.querySelector('.effectiveness-cycle:nth-child(2) > summary'),i=s.querySelector('.effectiveness-cycle-identity').getBoundingClientRect(),p=s.querySelector('.effectiveness-cycle-preview').getBoundingClientRect(),c=s.querySelector('.effectiveness-cycle-toggle').getBoundingClientRect();return {gap:p.left-i.right,centerGap:Math.abs((i.top+i.height/2)-(p.top+p.height/2)),arrowGap:c.left-p.right}})()")
                            self.assertAlmostEqual(layout["gap"], 15, delta=1)
                            self.assertLess(layout["centerGap"], 1)
                            self.assertGreater(layout["arrowGap"], 15)
                        self.assertTrue(browser.value('document.documentElement.scrollWidth<=innerWidth+2'))
                        artifact_dir=os.environ.get('LOTTO_ACTUAL_SPECIAL_ARTIFACT_DIR')
                        if artifact_dir:
                            output=Path(artifact_dir).resolve(); self.assertTrue(output.is_relative_to(ROOT.resolve())); output.mkdir(parents=True,exist_ok=True)
                            clip=browser.value("(()=>{let r=document.querySelector('.effectiveness-cycle:nth-child(2) > summary').getBoundingClientRect();return {x:r.left+scrollX,y:r.top+scrollY,width:r.width,height:r.height,scale:1}})()")
                            shot=browser.call('Page.captureScreenshot', {'format':'png','clip':clip,'captureBeyondViewport':True}, page=True)
                            (output/f'actual_special_{theme}_{width}.png').write_bytes(base64.b64decode(shot['data']))
                browser.value("document.body.classList.remove('light-theme')")
                browser.call('Emulation.setDeviceMetricsOverride', {'width':1440,'height':1000,'deviceScaleFactor':1,'mobile':False}, page=True)
                self.assertEqual(browser.value("document.querySelectorAll('.effectiveness-cycle:nth-child(2) .is-hit').length"), 0)
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle:first-child .effectiveness-ticket-hits').textContent"), "—")
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-ticket-prize').textContent"), "Giải Khuyến Khích")
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-ticket-prize').dataset.prizeStatus"), "won")
                self.assertEqual(browser.value("document.querySelectorAll('.effectiveness-cycle:nth-child(2) .effectiveness-special.is-matched').length"), 4)
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-special-separator').textContent"), "|")
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-special').textContent"), "01")
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-special').getAttribute('aria-label')"), "ĐB 01 trùng")
                for cycle in report["cycles"]:
                    cycle["actualSpecial"] = None
                    for entry in cycle["methods"].values():
                        entry["ticketResults"] = [{"ticketIndex": 1, "status": "unknown", "prizeLabel": "Chưa xác định giải", "reason": '<img src=x onerror=alert(1)>'}]
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-ticket-prize').dataset.prizeStatus==='unknown'")
                self.assertIn("chưa có dữ liệu", browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-cycle-preview').textContent"))
                self.assertEqual(browser.value("document.querySelectorAll('.effectiveness-cycle:nth-child(2) .effectiveness-special.is-matched').length"), 0)
                self.assertEqual(browser.value("document.querySelectorAll('.effectiveness-cycle img').length"), 0)
                # A large journal loads 10 tickets, preserves absolute ticket
                # numbers across pages/refresh and never creates forecasts.
                large_entry = report['cycles'][0]['methods']['web']
                large_entry.update({'predictionId': 'page_fixture', 'ticketCount': 10000,
                    'tickets': [{'main': [1, 2, 3, 4, 5]} for _ in range(10)],
                    'ticketPagination': {'page': 1, 'pageSize': 10, 'offset': 0, 'total': 10000, 'totalPages': 1000}})
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait("!!document.querySelector('[data-prediction-id=page_fixture] [data-ticket-jump]')")
                wait("!document.getElementById('effectivenessRefresh').disabled")
                post_count = sum(method == 'POST' for method, _, _ in requests)
                self.assertEqual(browser.value("document.querySelectorAll('[data-prediction-id=page_fixture] .effectiveness-ticket-row').length"), 10)
                self.assertEqual(browser.value("document.querySelector('[data-prediction-id=page_fixture] .effectiveness-ticket-range').textContent"), 'Vé 1–10 / 10.000')
                ticket_gets = lambda: sum('/api/ml/effectiveness-tickets?' in path for method, path, _ in requests if method == 'GET')
                before_gets = ticket_gets()
                self.assertTrue(browser.value("document.querySelector('[data-prediction-id=page_fixture] [data-ticket-page=\"0\"]').disabled"))
                for value in ('', '0', '-12', '1.9', '1'):
                    browser.value(f"{{const jump=document.querySelector('[data-prediction-id=page_fixture] [data-ticket-jump]');jump.value={json.dumps(value)};jump.dispatchEvent(new Event('change',{{bubbles:true}}))}}")
                    self.assertEqual(browser.value("document.querySelector('[data-prediction-id=page_fixture] [data-ticket-jump]').value"), '1')
                self.assertEqual(ticket_gets(), before_gets)
                browser.value("document.querySelector('[data-prediction-id=page_fixture] [data-ticket-page=\"2\"]').click()")
                wait("document.querySelector('[data-prediction-id=page_fixture] .effectiveness-ticket-label')?.textContent==='Vé 11'")
                browser.value("{const jump=document.querySelector('[data-prediction-id=page_fixture] [data-ticket-jump]');jump.value=999.9;jump.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))}")
                wait("document.querySelector('[data-prediction-id=page_fixture] .effectiveness-ticket-label')?.textContent==='Vé 9981'")
                self.assertEqual(browser.value("document.querySelector('[data-prediction-id=page_fixture] [data-ticket-jump]').value"), '999')
                browser.value("{const jump=document.querySelector('[data-prediction-id=page_fixture] [data-ticket-jump]');jump.value=1001;jump.dispatchEvent(new Event('change',{bubbles:true}))}")
                wait("document.querySelector('[data-prediction-id=page_fixture] .effectiveness-ticket-label')?.textContent==='Vé 9991'")
                self.assertTrue(browser.value("document.querySelector('[data-prediction-id=page_fixture] [data-ticket-page=\"1001\"]').disabled"))
                self.assertEqual(browser.value("document.querySelector('[data-prediction-id=page_fixture] .effectiveness-ticket-range').textContent"), 'Vé 9.991–10.000 / 10.000')
                before_gets = ticket_gets()
                for value in ('', '1000', '9999'):
                    browser.value(f"{{const jump=document.querySelector('[data-prediction-id=page_fixture] [data-ticket-jump]');jump.value={json.dumps(value)};jump.dispatchEvent(new KeyboardEvent('keydown',{{key:'Enter',bubbles:true}}));jump.dispatchEvent(new Event('change',{{bubbles:true}}))}}")
                    self.assertEqual(browser.value("document.querySelector('[data-prediction-id=page_fixture] [data-ticket-jump]').value"), '1000')
                self.assertEqual(ticket_gets(), before_gets)
                self.assertEqual(browser.value("document.querySelectorAll('[data-prediction-id=page_fixture] .effectiveness-ticket-row').length"), 10)
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait("!document.getElementById('effectivenessRefresh').disabled")
                self.assertEqual(browser.value("document.querySelector('[data-prediction-id=page_fixture] [data-ticket-jump]').value"), '1000')
                self.assertEqual(sum(method == 'POST' for method, _, _ in requests), post_count)
                large_entry.pop('ticketPagination')
                large_entry.pop('predictionId')
                large_entry.pop('ticketCount')
                report["type"] = "LOTO_6_55"
                for cycle in report["cycles"]:
                    if cycle["status"] == "scored":
                        cycle["actualMain"] = [1, 2, 3, 4, 5, 6]
                        cycle["actualSpecial"] = 7
                    for entry in cycle["methods"].values():
                        entry["tickets"] = [{"main": [1, 2, 3, 4, 5, 7], "special": 55}, {"main": [1, 2, 3, 4, 5, 8], "special": 7}]
                        entry["ticketResults"] = [{"ticketIndex": 1, "status": "won", "prizeLabel": "Jackpot 2", "specialMatched": True},
                                                  {"ticketIndex": 2, "status": "won", "prizeLabel": "Giải Nhất", "specialMatched": False}]
                browser.value("document.getElementById('effectivenessType').value='LOTO_6_55';document.getElementById('effectivenessType').dispatchEvent(new Event('change'))")
                wait("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-ticket-hits')?.textContent==='5/6'")
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) > summary .effectiveness-actual-special-ball').getAttribute('aria-label')"), 'Bóng thứ 7 07')
                self.assertIn("Bóng thứ 7", browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-actual-special').getAttribute('title')"))
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-ticket-row:first-child .effectiveness-ticket-prize').textContent"), "Jackpot 2")
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-ticket-row:nth-child(2) .effectiveness-ticket-prize').textContent"), "Giải Nhất")
                self.assertEqual(browser.value("document.querySelectorAll('.effectiveness-cycle:nth-child(2) .effectiveness-special.is-matched').length"), 4)
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-special').getAttribute('aria-label')"), "Phụ 55")
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-ticket-row:nth-child(2) .effectiveness-special').getAttribute('aria-label')"), "Phụ 07 trùng")
                browser.value("document.querySelector('.effectiveness-cycle:nth-child(2)').open=true")
                for width in (320, 390, 1440):
                    browser.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": width < 500}, page=True)
                    self.assertTrue(browser.value("document.documentElement.scrollWidth<=window.innerWidth+2"), f"Prize row overflows at {width}px")
                    for theme in ("dark", "light"):
                        browser.value(f"document.body.classList.toggle('light-theme',{str(theme == 'light').lower()})")
                        balls = browser.value("(()=>{let rows=[...document.querySelectorAll('.effectiveness-cycle:nth-child(2) [data-method=web] .effectiveness-ticket-row')];return rows.map(row=>{let main=row.querySelector('.effectiveness-ball'),special=row.querySelector('.effectiveness-special'),r=main.getBoundingClientRect(),s=special.getBoundingClientRect();return {mainWidth:r.width,mainHeight:r.height,width:s.width,height:s.height,background:getComputedStyle(special).backgroundColor}})})()")
                        self.assertEqual(len(balls), 2)
                        self.assertTrue(all(ball["width"] == ball["height"] == ball["mainWidth"] == ball["mainHeight"] for ball in balls))
                        self.assertEqual(balls[1]["background"], "rgb(255, 215, 106)")
                        self.assertNotEqual(balls[0]["background"], balls[1]["background"])
                        artifact_dir = os.environ.get("LOTTO_PREDICTED_SPECIAL_ARTIFACT_DIR")
                        if artifact_dir and width in (320, 1440):
                            output = Path(artifact_dir).resolve(); self.assertTrue(output.is_relative_to(ROOT.resolve())); output.mkdir(parents=True, exist_ok=True)
                            clip = browser.value("(()=>{let r=document.querySelector('.effectiveness-cycle:nth-child(2) [data-method=web] .effectiveness-ticket-list').getBoundingClientRect();return {x:r.left+scrollX,y:r.top+scrollY,width:r.width,height:r.height,scale:1}})()")
                            shot = browser.call("Page.captureScreenshot", {"format":"png","clip":clip,"captureBeyondViewport":True}, page=True)
                            (output/f"predicted_special_{theme}_{width}.png").write_bytes(base64.b64decode(shot["data"]))
                browser.value("document.body.classList.remove('light-theme')")
                self.assertEqual(browser.value("uiErrors"), [])
                saved_report = json.loads(json.dumps(report))
                # Each draw shows one pair. Switching uses the locked report,
                # has no API side effects and remembers each draw separately.
                views = '.effectiveness-method-view'
                self.assertTrue(browser.value(f"[...document.querySelectorAll('{views}')].every(v=>v.querySelectorAll('[role=tab]').length===2&&v.querySelectorAll('[role=tabpanel]:not([hidden])').length===1&&v.querySelector('[role=tabpanel]:not([hidden])').querySelectorAll('[data-method]').length===2)"))
                def select_method(key, cycle=1):
                    key = 'web' if key in ('web','random') else 'bayesian'
                    browser.value(f"document.querySelector('.effectiveness-cycle:nth-child({cycle})').open=true;document.querySelector('.effectiveness-cycle:nth-child({cycle}) [data-cycle-method={key}]').click()")
                def selected_method(cycle=1):
                    return browser.value(f"document.querySelector('.effectiveness-cycle:nth-child({cycle}) [role=tab][aria-selected=true]').dataset.cycleMethod")
                method_requests = len(requests)
                browser.value("document.querySelector('.effectiveness-method-view [data-method-step=\"-1\"]').click()")
                self.assertEqual(selected_method(), 'bayesian')
                browser.value("document.querySelector('.effectiveness-method-view [data-method-step=\"1\"]').click()")
                self.assertEqual(selected_method(), 'web')
                for key in ('random', 'bayesian', 'ewma', 'web'):
                    select_method(key)
                    pair_key = 'web' if key in ('web','random') else 'bayesian'
                    self.assertEqual(selected_method(), pair_key)
                    self.assertEqual(browser.value("document.querySelector('.effectiveness-method-view [role=tabpanel]:not([hidden])').dataset.methodPair"), pair_key)
                    self.assertTrue(browser.value("[...document.querySelectorAll('.effectiveness-method-view [role=tab]')].every(t=>document.getElementById(t.getAttribute('aria-controls'))?.getAttribute('aria-labelledby')===t.id)"))
                for key, expected in (('ArrowLeft', 'bayesian'), ('ArrowRight', 'web'), ('End', 'bayesian'), ('Home', 'web')):
                    browser.value(f"document.querySelector('.effectiveness-method-view [role=tab][aria-selected=true]').dispatchEvent(new KeyboardEvent('keydown',{{key:{json.dumps(key)},bubbles:true}}))")
                    self.assertEqual(selected_method(), expected)
                    self.assertEqual(browser.value('document.activeElement.dataset.cycleMethod'), expected)
                self.assertEqual(len(requests), method_requests)
                select_method('ewma')
                select_method('bayesian', 2)
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait("!document.getElementById('effectivenessRefresh').disabled")
                self.assertEqual(selected_method(), 'bayesian')
                self.assertEqual(selected_method(2), 'bayesian')
                # Authentication changes cannot inherit another user's choices.
                browser.value("window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:true,user:'method-test'}}))")
                wait("document.querySelectorAll('.effectiveness-cycle').length===3")
                self.assertEqual(selected_method(), 'web')
                self.assertEqual(selected_method(2), 'web')
                # Whole-prediction winning summary: the highest prize can be
                # outside the visible 10-ticket page; counts sort independently
                # of prize rank and remain stable through paging and refresh.
                original_report = json.loads(json.dumps(report))
                original_keno_level = browser.value("document.getElementById('effectivenessKenoLevel').value")
                report['cycles'] = [json.loads(json.dumps(report['cycles'][1]))]
                summary_cycle = report['cycles'][0]
                summary_entry = summary_cycle['methods']['web']
                summary_entry.update({
                    'predictionId': 'prize_summary_fixture', 'ticketCount': 10000,
                    'tickets': [{'main': [1, 2, 3, 4, 5, 7]} for _ in range(10)],
                    'ticketPagination': {'page': 1, 'pageSize': 10, 'offset': 0, 'total': 10000, 'totalPages': 1000},
                    'prizeCounts': {'POWER_JACKPOT_1': 1, 'POWER_JACKPOT_2': 2, 'FIRST': 7,
                                    'SECOND': 9, 'THIRD': 9, 'NONE': 9969, 'UNKNOWN': 3},
                })
                summary_cycle['methods']['random'].update({
                    'predictionId': 'method_random_fixture', 'ticketCount': 10000,
                    'tickets': [{'main': [1, 2, 3, 4, 5, 6]} for _ in range(10)],
                    'ticketPagination': {'page': 1, 'pageSize': 10, 'offset': 0, 'total': 10000, 'totalPages': 1000},
                    'prizeCounts': {'FIRST': 10, 'SECOND': 20, 'NONE': 9970},
                })
                for key in ('bayesian','ewma'):
                    summary_cycle['methods'][key].update(json.loads(json.dumps(summary_entry)), predictionId=f'method_{key}_fixture')
                selector = '[data-prediction-id=prize_summary_fixture]'
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait(f"document.querySelector('{selector} .effectiveness-prize-best strong')?.textContent==='Jackpot 1'")
                self.assertEqual(browser.value(f"document.querySelector('{selector} .effectiveness-prize-best b').textContent"), '1')
                self.assertEqual(browser.value(f"document.querySelector('{selector} [data-prize-code=POWER_JACKPOT_1]').dataset.prizeUnit"), '')
                self.assertEqual(browser.value(f"document.querySelector('{selector} [data-prize-net]').dataset.prizeNet"), '')
                self.assertEqual(browser.value(f"[...document.querySelectorAll('{selector} [data-prize-code]')].map(e=>e.dataset.prizeCode)"),
                                 ['SECOND', 'THIRD', 'FIRST', 'POWER_JACKPOT_2', 'POWER_JACKPOT_1'])
                self.assertIn('3 vé chưa xác định', browser.value(f"document.querySelector('{selector} .effectiveness-prize-summary').textContent"))
                self.assertEqual(browser.value("document.querySelectorAll('.effectiveness-cycle:first-child [data-method]:not([data-method=web]) .effectiveness-prize-summary').length"), 3)
                self.assertEqual(browser.value("document.querySelector('[data-prediction-id=method_random_fixture] [data-prize-reward]').dataset.prizeReward"), '410000000')
                random_summary_text = browser.value("document.querySelector('[data-prediction-id=method_random_fixture] .effectiveness-prize-summary').textContent")
                summary_text = browser.value(f"document.querySelector('{selector} .effectiveness-prize-summary').textContent")
                # Reward help is shared across methods, works above scrolling
                # sections, and does not change the full-portfolio amounts.
                self.assertEqual(browser.value("document.querySelectorAll('[data-prize-reward-help]').length"), browser.value("document.querySelectorAll('[data-prize-reward]').length"))
                self.assertGreaterEqual(browser.value("document.querySelectorAll('[data-prize-reward-help]').length"), 2)
                self.assertFalse(browser.value("document.getElementById('effectivenessPrizeRewardHelp').matches(':popover-open')"))
                help_selector = f"{selector} [data-prize-reward-help]"
                select_method('web')
                for width in (320, 1440):
                    browser.call('Emulation.setDeviceMetricsOverride', {'width':width,'height':900,'deviceScaleFactor':1,'mobile':width<500}, page=True)
                    for theme in ('dark', 'light'):
                        browser.value(f"document.body.classList.toggle('light-theme',{str(theme=='light').lower()});document.querySelector({json.dumps(help_selector)}).scrollIntoView({{block:'center'}})")
                        point = browser.value(f"(()=>{{let r=document.querySelector({json.dumps(help_selector)}).getBoundingClientRect();return {{x:r.left+r.width/2,y:r.top+r.height/2}}}})()")
                        browser.call('Input.dispatchMouseEvent', {'type':'mouseMoved',**point}, page=True)
                        wait("document.getElementById('effectivenessPrizeRewardHelp').matches(':popover-open')")
                        wait(f"document.querySelector({json.dumps(help_selector)}).getAttribute('aria-expanded')==='true'")
                        self.assertIn('20.000.000 ₫', browser.value("document.getElementById('effectivenessPrizeRewardHelp').textContent"))
                        self.assertIn('100 triệu ₫ → thuế 8 triệu ₫', browser.value("document.getElementById('effectivenessPrizeRewardHelp').textContent"))
                        self.assertIn('docid=218684', browser.value("document.querySelector('#effectivenessPrizeRewardHelp a').href"))
                        box = browser.value("(()=>{let r=document.getElementById('effectivenessPrizeRewardHelp').getBoundingClientRect();return {left:r.left,top:r.top,right:r.right,bottom:r.bottom}})()")
                        self.assertGreaterEqual(box['left'], 11)
                        self.assertGreaterEqual(box['top'], 11)
                        self.assertLessEqual(box['right'], width-11)
                        self.assertLessEqual(box['bottom'], 889)
                        self.assertTrue(browser.value('document.documentElement.scrollWidth<=innerWidth+2'))
                        artifact_dir = os.environ.get('LOTTO_REWARD_TAX_HELP_ARTIFACT_DIR')
                        if artifact_dir:
                            output = Path(artifact_dir).resolve(); self.assertTrue(output.is_relative_to(ROOT.resolve())); output.mkdir(parents=True,exist_ok=True)
                            shot = browser.call('Page.captureScreenshot', {'format':'png','captureBeyondViewport':False}, page=True)
                            (output/f'reward_help_{theme}_{width}.png').write_bytes(base64.b64decode(shot['data']))
                        browser.call('Input.dispatchMouseEvent', {'type':'mouseMoved','x':box['left']+20,'y':box['top']+20}, page=True)
                        time.sleep(.22)
                        self.assertTrue(browser.value("document.getElementById('effectivenessPrizeRewardHelp').matches(':popover-open')"))
                        browser.call('Input.dispatchMouseEvent', {'type':'mouseMoved','x':1,'y':1}, page=True)
                        wait("!document.getElementById('effectivenessPrizeRewardHelp').matches(':popover-open')")
                browser.value(f"{{let b=document.querySelector({json.dumps(help_selector)}),s=document.createElement('span');s.tabIndex=0;s.id='rewardHelpFocus';b.before(s);s.focus()}}")
                browser.call('Input.dispatchKeyEvent', {'type':'keyDown','key':'Tab','code':'Tab','windowsVirtualKeyCode':9}, page=True)
                browser.call('Input.dispatchKeyEvent', {'type':'keyUp','key':'Tab','code':'Tab','windowsVirtualKeyCode':9}, page=True)
                wait("document.activeElement.matches('[data-prize-reward-help]')&&document.getElementById('effectivenessPrizeRewardHelp').matches(':popover-open')")
                browser.call('Input.dispatchKeyEvent', {'type':'keyDown','key':'Escape','code':'Escape','windowsVirtualKeyCode':27}, page=True)
                browser.call('Input.dispatchKeyEvent', {'type':'keyUp','key':'Escape','code':'Escape','windowsVirtualKeyCode':27}, page=True)
                wait("!document.getElementById('effectivenessPrizeRewardHelp').matches(':popover-open')")
                browser.value("document.activeElement.blur();document.getElementById('rewardHelpFocus').remove()")
                browser.call('Emulation.setDeviceMetricsOverride', {'width':390,'height':900,'deviceScaleFactor':1,'mobile':True}, page=True)
                browser.call('Emulation.setTouchEmulationEnabled', {'enabled':True}, page=True)
                browser.value(f"document.querySelector({json.dumps(help_selector)}).scrollIntoView({{block:'center'}})")
                point = browser.value(f"(()=>{{let r=document.querySelector({json.dumps(help_selector)}).getBoundingClientRect();return {{x:r.left+r.width/2,y:r.top+r.height/2}}}})()")
                browser.call('Input.dispatchTouchEvent', {'type':'touchStart','touchPoints':[point]}, page=True)
                browser.call('Input.dispatchTouchEvent', {'type':'touchEnd','touchPoints':[]}, page=True)
                wait("document.getElementById('effectivenessPrizeRewardHelp').matches(':popover-open')")
                browser.call('Input.dispatchTouchEvent', {'type':'touchStart','touchPoints':[{'x':5,'y':5}]}, page=True)
                browser.call('Input.dispatchTouchEvent', {'type':'touchEnd','touchPoints':[]}, page=True)
                wait("!document.getElementById('effectivenessPrizeRewardHelp').matches(':popover-open')")
                browser.call('Emulation.setTouchEmulationEnabled', {'enabled':False}, page=True)
                browser.call('Emulation.setDeviceMetricsOverride', {'width':1440,'height':900,'deviceScaleFactor':1,'mobile':False}, page=True)
                browser.value("document.body.classList.remove('light-theme')")
                self.assertEqual(browser.value(f"document.querySelector('{selector} .effectiveness-prize-summary').textContent"), summary_text)
                summary_posts = sum(method == 'POST' for method, _, _ in requests)
                for key, ticket_index, prize_code in [('web',37,'POWER_JACKPOT_1'),('random',73,'FIRST'),('bayesian',95,'POWER_JACKPOT_1'),('ewma',9994,'POWER_JACKPOT_1')]:
                    select_method(key)
                    method_selector = f'[data-method={key}]'
                    before_pages = browser.value("[...document.querySelectorAll('[data-method] [data-ticket-jump]')].map(e=>e.value)")
                    browser.value(f"document.querySelector('{method_selector} [data-prize-jump]').click()")
                    wait(f"document.querySelector('{method_selector} .is-prize-target')?.dataset.ticketIndex==='{ticket_index}'")
                    self.assertEqual(browser.value(f"document.querySelector('{method_selector} .is-prize-target').dataset.ticketPrizeCode"), prize_code)
                    self.assertEqual(browser.value(f"document.querySelector('{method_selector} [data-ticket-jump]').value"), str((ticket_index-1)//10+1))
                    self.assertEqual(browser.value('document.activeElement.dataset.ticketIndex'), str(ticket_index))
                    after_pages = browser.value("[...document.querySelectorAll('[data-method] [data-ticket-jump]')].map(e=>e.value)")
                    for index in range(4):
                        if index != keys.index(key): self.assertEqual(after_pages[index], before_pages[index])
                    self.assertTrue(any(f'predictionId={summary_cycle["methods"][key]["predictionId"]}' in path and f'prizeCode={prize_code}' in path for method,path,_ in requests if method=='GET'))
                    self.assertEqual(sum(method == 'POST' for method,_,_ in requests), summary_posts)
                    # Multiple winners: same page, next page, then wrap. A sole
                    # winning ticket wraps to itself; other methods stay put.
                    next_indices = [75,88,73] if key == 'random' else [ticket_index]
                    cursor = ticket_index
                    for next_index in next_indices:
                        ticket_requests = sum('/api/ml/effectiveness-tickets?' in path for _,path,_ in requests)
                        browser.value(f"document.querySelector('{method_selector} [data-prize-jump]').click()")
                        wait(f"document.querySelector('{method_selector} .is-prize-target')?.dataset.ticketIndex==='{next_index}' && !document.querySelector('{method_selector} [data-prize-jump]').disabled")
                        self.assertGreater(sum('/api/ml/effectiveness-tickets?' in path for _,path,_ in requests), ticket_requests)
                        self.assertIn(f'afterTicketIndex={cursor}', [path for _,path,_ in requests if '/api/ml/effectiveness-tickets?' in path][-1])
                        self.assertEqual(browser.value(f"document.querySelector('{method_selector} .is-prize-target').dataset.ticketPrizeCode"), prize_code)
                        self.assertEqual(browser.value(f"document.querySelector('{method_selector} [data-ticket-jump]').value"), str((next_index-1)//10+1))
                        self.assertEqual(browser.value('document.activeElement.dataset.ticketIndex'), str(next_index))
                        pages = browser.value("[...document.querySelectorAll('[data-method] [data-ticket-jump]')].map(e=>e.value)")
                        for index in range(4):
                            if index != keys.index(key): self.assertEqual(pages[index], before_pages[index])
                        self.assertEqual(sum(method == 'POST' for method,_,_ in requests), summary_posts)
                        cursor = next_index
                for key in keys:
                    browser.value(f"{{let jump=document.querySelector('[data-method={key}] [data-ticket-jump]');jump.value=1;jump.dispatchEvent(new Event('change',{{bubbles:true}}))}}")
                    wait(f"document.querySelector('[data-method={key}] .effectiveness-ticket-label')?.textContent==='Vé 01'")
                select_method('web')
                browser.value(f"document.querySelector('{selector} [data-ticket-page=\"2\"]').click()")
                wait(f"document.querySelector('{selector} .effectiveness-ticket-label')?.textContent==='Vé 11'")
                self.assertEqual(browser.value(f"document.querySelector('{selector} .effectiveness-prize-summary').textContent"), summary_text)
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait("!document.getElementById('effectivenessRefresh').disabled")
                self.assertEqual(browser.value(f"document.querySelector('{selector} .effectiveness-prize-summary').textContent"), summary_text)
                self.assertEqual(sum(method == 'POST' for method, _, _ in requests), summary_posts)
                # Ticket pagination belongs to the method, not the carousel.
                select_method('random')
                random_selector = '[data-prediction-id=method_random_fixture]'
                self.assertEqual(browser.value(f"document.querySelector('{random_selector} [data-ticket-jump]').value"), '1')
                browser.value(f"document.querySelector('{random_selector} [data-ticket-jump]').value='3';document.querySelector('{random_selector} [data-ticket-jump]').dispatchEvent(new Event('change',{{bubbles:true}}))")
                wait(f"document.querySelector('{random_selector} .effectiveness-ticket-label')?.textContent==='Vé 21'")
                self.assertEqual(browser.value(f"document.querySelector('{random_selector} .effectiveness-prize-summary').textContent"), random_summary_text)
                select_method('bayesian')
                select_method('web')
                self.assertEqual(browser.value(f"document.querySelector('{selector} [data-ticket-jump]').value"), '2')
                select_method('random')
                self.assertEqual(browser.value(f"document.querySelector('{random_selector} [data-ticket-jump]').value"), '3')
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait("!document.getElementById('effectivenessRefresh').disabled")
                self.assertEqual(selected_method(), 'web')
                self.assertEqual(browser.value(f"document.querySelector('{random_selector} [data-ticket-jump]').value"), '3')
                select_method('web')
                self.assertEqual(browser.value(f"document.querySelector('{selector} .effectiveness-prize-summary').textContent"), summary_text)
                self.assertEqual(sum(method == 'POST' for method, _, _ in requests), summary_posts)
                carousel_artifacts = os.environ.get('LOTTO_METHOD_CAROUSEL_ARTIFACT_DIR')
                for theme in ('dark', 'light'):
                    browser.value(f"document.body.classList.toggle('light-theme',{str(theme == 'light').lower()})")
                    for width in (320, 390, 1440):
                        browser.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 900, 'deviceScaleFactor': 1, 'mobile': width < 500}, page=True)
                        browser.value("document.querySelector('.effectiveness-cycle').open=true")
                        for key in keys:
                            select_method(key)
                            self.assertTrue(browser.value('document.documentElement.scrollWidth<=innerWidth+2'))
                            self.assertTrue(browser.value("(()=>{const v=document.querySelector('.effectiveness-method-view');const tabs=[...v.querySelectorAll('[role=tab]')];const p=v.querySelector('[role=tabpanel]:not([hidden])').getBoundingClientRect();const r=v.getBoundingClientRect();return tabs.every(t=>t.scrollWidth<=t.clientWidth+2&&Math.abs(t.getBoundingClientRect().top-tabs[0].getBoundingClientRect().top)<1)&&Math.abs(p.width-r.width)<1&&v.querySelectorAll('[role=tabpanel]:not([hidden])').length===1})()"), f'{theme} {width}px {key}')
                        select_method('web')
                        if carousel_artifacts:
                            output = Path(carousel_artifacts).resolve()
                            self.assertTrue(output.is_relative_to(ROOT.resolve()))
                            output.mkdir(parents=True, exist_ok=True)
                            browser.value("document.querySelector('.effectiveness-cycle-method-head strong').setAttribute('data-fixture-label','Dữ liệu kiểm thử')")
                            browser.value("if(!document.getElementById('methodFixtureStyle')){const s=document.createElement('style');s.id='methodFixtureStyle';s.textContent='[data-fixture-label]::after {content: \\\" · \\\" attr(data-fixture-label);font-size:10px;font-weight:400;color:var(--effectiveness-muted)}';document.head.append(s)}")
                            clip = browser.value("(()=>{const r=document.querySelector('.effectiveness-method-view').getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()")
                            browser.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': int(clip['y'] + clip['height'] + 50), 'deviceScaleFactor': 1, 'mobile': width < 500}, page=True)
                            screenshot = browser.call('Page.captureScreenshot', {'format':'png','clip':clip,'captureBeyondViewport':True}, page=True)
                            (output / f'fixture_method_carousel_{theme}_{width}.png').write_bytes(base64.b64decode(screenshot['data']))
                browser.value("document.body.classList.remove('light-theme')")
                summary_artifacts = os.environ.get('LOTTO_PIPELINE_SUMMARY_ARTIFACT_DIR')
                for theme in ('dark', 'light'):
                    browser.value(f"document.body.classList.toggle('light-theme',{str(theme == 'light').lower()})")
                    for width in (320, 390, 1440):
                        browser.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 900, 'deviceScaleFactor': 1, 'mobile': width < 500}, page=True)
                        browser.value("document.querySelector('.effectiveness-cycle').open=true")
                        self.assertTrue(browser.value('document.documentElement.scrollWidth<=innerWidth+2'))
                        self.assertTrue(browser.value(f"[...document.querySelectorAll('{selector} .effectiveness-prize-counts > span')].every(e=>e.scrollWidth<=e.clientWidth+2)"))
                        self.assertTrue(browser.value(f"(()=>{{const buttons=[...document.querySelectorAll('{selector} .effectiveness-ticket-pager button')];return Math.abs(buttons[0].getBoundingClientRect().y-buttons[1].getBoundingClientRect().y)<1;}})()"))
                        if summary_artifacts:
                            output = Path(summary_artifacts).resolve()
                            self.assertTrue(output.is_relative_to(ROOT.resolve()))
                            output.mkdir(parents=True, exist_ok=True)
                            browser.value(f"document.querySelector('{selector} .effectiveness-prize-summary').setAttribute('data-fixture-label','Dữ liệu kiểm thử')")
                            rect = browser.value(f"(()=>{{const r=document.querySelector('{selector} .effectiveness-ticket-footer').getBoundingClientRect();return {{x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}};}})()")
                            capture = browser.call('Page.captureScreenshot', {'format': 'png', 'clip': rect, 'captureBeyondViewport': True}, page=True)
                            (output / f'fixture_pipeline_summary_{theme}_{width}.png').write_bytes(base64.b64decode(capture['data']))
                browser.value("document.body.classList.remove('light-theme')")
                summary_entry.pop('ticketPagination')
                summary_entry['ticketCount'] = 20
                cases = [
                    ('LOTO_5_35', {'CONSOLATION': 8, 'LOTTO_JACKPOT': 1, 'FIRST': 1, 'NONE': 10}, 'Độc Đắc', ['CONSOLATION', 'LOTTO_JACKPOT', 'FIRST']),
                    ('LOTO_6_45', {'THIRD': 18, 'MEGA_JACKPOT': 1, 'FIRST': 1}, 'Jackpot', ['THIRD', 'MEGA_JACKPOT', 'FIRST']),
                    ('KENO', {'KENO_8_0': 9, 'KENO_8_4': 10, 'KENO_8_8': 1}, 'Trúng 8/8 số', ['KENO_8_4', 'KENO_8_0', 'KENO_8_8']),
                ]
                for game, counts, best, codes in cases:
                    report['type'] = game
                    summary_cycle['level'] = 8 if game == 'KENO' else None
                    summary_entry['prizeCounts'] = counts
                    if game == 'KENO':
                        browser.value("document.getElementById('effectivenessKenoLevel').value='8'")
                    browser.value(f"document.getElementById('effectivenessType').value='{game}';document.getElementById('effectivenessType').dispatchEvent(new Event('change'))")
                    wait(f"document.querySelector('{selector} .effectiveness-prize-best strong')?.textContent==={json.dumps(best)}")
                    self.assertEqual(browser.value(f"[...document.querySelectorAll('{selector} [data-prize-code]')].map(e=>e.dataset.prizeCode)"), codes)
                    if game == 'KENO':
                        select_method('bayesian')
                        browser.value("document.getElementById('effectivenessKenoLevel').value='9';document.getElementById('effectivenessKenoLevel').dispatchEvent(new Event('change'))")
                        wait("document.querySelector('.effectiveness-method-view')?.dataset.methodCycle.startsWith('KENO:9:')")
                        self.assertEqual(selected_method(), 'web')
                        browser.value("document.getElementById('effectivenessKenoLevel').value='8';document.getElementById('effectivenessKenoLevel').dispatchEvent(new Event('change'))")
                        wait("document.querySelector('.effectiveness-method-view')?.dataset.methodCycle.startsWith('KENO:8:')")
                        self.assertEqual(selected_method(), 'bayesian')
                        select_method('web')
                # All money uses the full portfolio, including losing tickets.
                # Keno zero hits can pay, and prize rank must not affect totals.
                actual_before_money = summary_cycle['actualMain'][:]
                report['type'] = 'KENO'
                summary_cycle.update(level=10, actualMain=list(range(1, 21)))
                summary_entry['ticketCount'] = 10000
                money_counts = {'KENO_10_0': 405, 'KENO_10_5': 384, 'KENO_10_6': 73,
                                'KENO_10_7': 6, 'KENO_10_8': 2, 'NONE': 9130}
                summary_entry['prizeCounts'] = money_counts
                browser.value("document.getElementById('effectivenessKenoLevel').value='10';document.getElementById('effectivenessType').value='KENO';document.getElementById('effectivenessType').dispatchEvent(new Event('change'))")
                wait(f"document.querySelector('{selector} [data-prize-reward]')?.dataset.prizeReward==='37830000'")
                self.assertEqual(browser.value(f"document.querySelector('{selector} [data-prize-net]').dataset.prizeNet"), '-62170000')
                self.assertTrue(browser.value(f"document.querySelector('{selector} .effectiveness-prize-net').classList.contains('is-negative')"))
                self.assertEqual(browser.value(f"document.querySelector('{selector} [data-ticket-cost]').dataset.ticketCost"), '100000000')
                self.assertEqual(browser.value(f"[...document.querySelectorAll('{selector} [data-prize-subtotal]')].map(e=>[e.dataset.prizeCode,Number(e.dataset.prizeUnit),Number(e.dataset.prizeSubtotal)])"),
                                 [['KENO_10_0',10000,4050000], ['KENO_10_5',20000,7680000],
                                  ['KENO_10_6',80000,5840000], ['KENO_10_7',710000,4260000], ['KENO_10_8',8000000,16000000]])
                money_text = browser.value(f"document.querySelector('{selector} .effectiveness-prize-summary').textContent")
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait("!document.getElementById('effectivenessRefresh').disabled")
                self.assertEqual(browser.value(f"document.querySelector('{selector} .effectiveness-prize-summary').textContent"), money_text)
                # All four cards use their own full portfolio counts and cost,
                # even when only twenty tickets are displayed.
                other_entries = {key: json.loads(json.dumps(summary_cycle['methods'][key])) for key in keys[1:]}
                method_money_cases = [
                    ('random',10000,{'KENO_10_5':7,'NONE':9993},140000,-99860000,'Trúng 5/10 số'),
                    ('bayesian',3160,{'KENO_10_7':2,'KENO_10_8':1,'NONE':3157},9420000,-22180000,'Trúng 8/10 số'),
                    ('ewma',80,{'KENO_10_0':10,'NONE':70},100000,-700000,'Trúng 0/10 số'),
                ]
                for key, total, counts, reward, net, best in method_money_cases:
                    summary_cycle['methods'][key].update(ticketCount=total, prizeCounts=counts,
                        ticketPagination={'page':1,'pageSize':20,'offset':0,'total':total,'totalPages':(total+19)//20})
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait("!document.getElementById('effectivenessRefresh').disabled")
                method_posts = sum(method == 'POST' for method, _, _ in requests)
                for key, total, counts, reward, net, best in method_money_cases:
                    select_method(key)
                    card = f'.effectiveness-cycle:first-child [data-method={key}] .effectiveness-prize-summary'
                    self.assertEqual(browser.value(f"document.querySelector('{card} [data-prize-reward]').dataset.prizeReward"), str(reward))
                    self.assertEqual(browser.value(f"document.querySelector('{card} [data-prize-net]').dataset.prizeNet"), str(net))
                    self.assertEqual(browser.value(f"document.querySelector('{card} [data-ticket-cost]').dataset.ticketCost"), str(total*10000))
                    self.assertEqual(browser.value(f"document.querySelector('{card} .effectiveness-prize-best strong').textContent"), best)
                    self.assertEqual(browser.value(f"document.querySelector('{card}').getAttribute('aria-label')"),
                                     f"Vé trúng và tiền thưởng mô phỏng của toàn bộ {dict(random='Ngẫu nhiên',bayesian='Bayesian',ewma='EWMA')[key]} trong kỳ này")
                    for theme in ('dark','light'):
                        browser.value(f"document.body.classList.toggle('light-theme',{str(theme=='light').lower()})")
                        for width in (320,390,1440):
                            browser.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':1000,'deviceScaleFactor':1,'mobile':width<500},page=True)
                            self.assertTrue(browser.value('document.documentElement.scrollWidth<=innerWidth+2'))
                            self.assertTrue(browser.value(f"[...document.querySelectorAll('{card} .effectiveness-prize-equation > *')].every(e=>e.scrollWidth<=e.clientWidth+2)"))
                            artifact_dir=os.environ.get('LOTTO_ALL_METHOD_PRIZES_ARTIFACT_DIR')
                            if artifact_dir and (theme,width) in [('dark',1440),('light',320)]:
                                output=Path(artifact_dir).resolve(); self.assertTrue(output.is_relative_to(ROOT.resolve())); output.mkdir(parents=True,exist_ok=True)
                                browser.value(f"document.querySelector('{card}').setAttribute('data-method-fixture','Dữ liệu kiểm thử · {key}');if(!document.getElementById('allMethodFixtureStyle')){{const s=document.createElement('style');s.id='allMethodFixtureStyle';s.textContent='[data-method-fixture]::before{{content:attr(data-method-fixture);display:block;font-size:10px;color:var(--effectiveness-muted)}}';document.head.append(s)}}")
                                clip=browser.value(f"(()=>{{const r=document.querySelector('{card}').getBoundingClientRect();return {{x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}}}})()")
                                shot=browser.call('Page.captureScreenshot',{'format':'png','clip':clip,'captureBeyondViewport':True},page=True)
                                (output/f'fixture_{key}_prizes_{theme}_{width}.png').write_bytes(base64.b64decode(shot['data']))
                scored_main = summary_cycle['actualMain']
                summary_cycle['actualMain'] = []
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait("!document.getElementById('effectivenessRefresh').disabled")
                self.assertTrue(browser.value("[...document.querySelectorAll('.effectiveness-cycle:first-child .effectiveness-prize-summary')].every(e=>e.textContent==='Chờ kết quả'&&!e.querySelector('[data-prize-net]'))"))
                summary_cycle['actualMain'] = scored_main
                for key, entry in other_entries.items():
                    summary_cycle['methods'][key] = entry
                browser.value("document.body.classList.remove('light-theme');document.getElementById('effectivenessRefresh').click()")
                wait("!document.getElementById('effectivenessRefresh').disabled")
                select_method('web')
                self.assertEqual(browser.value(f"document.querySelector('{selector} .effectiveness-prize-summary').textContent"), money_text)
                self.assertEqual(sum(method == 'POST' for method, _, _ in requests), method_posts)
                # A complete visible Keno page verifies the whole composition:
                # shared columns, bounded width, five-by-two balls on phones,
                # and paging above rather than beside the accounting card.
                before_layout_tickets = json.loads(json.dumps(summary_entry['tickets']))
                before_layout_results = json.loads(json.dumps(summary_entry['ticketResults']))
                before_layout_mean = summary_entry.get('meanHits')
                before_pair_layout = {key:json.loads(json.dumps(summary_cycle['methods'][key])) for key in keys[1:]}
                report['_keepMethodTickets'] = True
                summary_entry['tickets'] = []
                summary_entry['ticketResults'] = []
                for index in range(20):
                    hits = [0,2,3,4,5,6,7,8][index % 8]
                    summary_entry['tickets'].append({'main':list(range(1,hits+1))+list(range(21,31-hits))})
                    summary_entry['ticketResults'].append({'ticketIndex':index+1,'prizeCode':f'KENO_10_{hits}' if hits in (0,5,6,7,8) else 'NONE',
                        'prizeLabel':f'Trúng {hits}/10 số' if hits in (0,5,6,7,8) else 'Không trúng giải',
                        'status':'won' if hits in (0,5,6,7,8) else 'lost'})
                summary_entry['ticketPagination'] = {'page':1,'pageSize':20,'offset':0,'total':10000,'totalPages':500}
                summary_entry['meanHits'] = sum([0,2,3,4,5,6,7,8][index%8] for index in range(20))/20
                for key in keys[1:]:
                    entry = summary_cycle['methods'][key]
                    entry.update(tickets=json.loads(json.dumps(summary_entry['tickets'])),
                        ticketResults=json.loads(json.dumps(summary_entry['ticketResults'])),
                        prizeCounts=dict(money_counts), ticketCount=10000,
                        ticketPagination=dict(summary_entry['ticketPagination']), meanHits=summary_entry['meanHits'])
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait("!document.getElementById('effectivenessRefresh').disabled")
                aligned_artifacts = os.environ.get('LOTTO_PAIRED_METHOD_ARTIFACT_DIR') or os.environ.get('LOTTO_ALIGNED_METHOD_ARTIFACT_DIR')
                for theme in ('dark','light'):
                    browser.value(f"document.body.classList.toggle('light-theme',{str(theme=='light').lower()})")
                    for width in (320,390,600,768,1050,1201,1220,1280,1440,1600):
                        browser.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':1100,'deviceScaleFactor':1,'mobile':width<500},page=True)
                        browser.value("document.querySelector('.effectiveness-cycle').open=true")
                        self.assertTrue(browser.value('document.documentElement.scrollWidth<=innerWidth+2'))
                        self.assertTrue(browser.value("document.querySelector('.effectiveness-method-view').getBoundingClientRect().width<=1601"))
                        self.assertTrue(browser.value("(()=>{const v=document.querySelector('.effectiveness-method-view').getBoundingClientRect();return [...document.querySelectorAll('.effectiveness-method-view:first-child .effectiveness-method-navigation > *')].every(e=>{const r=e.getBoundingClientRect();return r.left>=v.left-1&&r.right<=v.right+1})})()"), f'pair navigation fits {theme} {width}')
                        self.assertTrue(browser.value(f"(()=>{{const p=document.querySelector('{selector} .effectiveness-ticket-pager').getBoundingClientRect();const s=document.querySelector('{selector} .effectiveness-prize-summary').getBoundingClientRect();const f=document.querySelector('{selector} .effectiveness-ticket-footer').getBoundingClientRect();return p.bottom<=s.top&&Math.abs(s.width-f.width)<1&&Math.abs(p.x+p.width/2-(f.x+f.width/2))<1;}})()"))
                        self.assertTrue(browser.value(f"(()=>{{const p=document.querySelector('{selector} .effectiveness-ticket-pager');const controls=[...p.querySelectorAll('button,input')].map(e=>e.getBoundingClientRect());const r=p.getBoundingClientRect();return controls.every(e=>Math.abs(e.height-32)<1&&Math.abs(e.y-controls[0].y)<1&&e.left>=r.left&&e.right<=r.right)&&p.scrollWidth<=p.clientWidth+1;}})()"), f'pager alignment {theme} {width}')
                        self.assertTrue(browser.value(f"(()=>{{const p=document.querySelector('{selector} .effectiveness-ticket-pager');const r=p.querySelector('.effectiveness-ticket-range').getBoundingClientRect();const c=p.querySelector('.effectiveness-ticket-page-controls').getBoundingClientRect();return r.bottom<c.top&&Math.abs(r.x+r.width/2-(c.x+c.width/2))<1;}})()"), f'ticket range above controls {theme} {width}')
                        pager_artifacts = os.environ.get('LOTTO_TICKET_PAGER_ARTIFACT_DIR')
                        if pager_artifacts and width in (320,390,1440):
                            output=Path(pager_artifacts).resolve()
                            self.assertTrue(output.is_relative_to(ROOT.resolve()))
                            output.mkdir(parents=True,exist_ok=True)
                            browser.value(f"document.querySelector('{selector} .effectiveness-ticket-footer').setAttribute('data-pager-fixture','Dữ liệu kiểm thử · 10.000 vé');if(!document.getElementById('pagerFixtureStyle')){{const s=document.createElement('style');s.id='pagerFixtureStyle';s.textContent='[data-pager-fixture]::before{{content:attr(data-pager-fixture);display:block;text-align:center;font-size:10px;color:var(--effectiveness-muted)}}';document.head.append(s)}}")
                            clip=browser.value(f"(()=>{{const f=document.querySelector('{selector} .effectiveness-ticket-footer').getBoundingClientRect();const p=document.querySelector('{selector} .effectiveness-ticket-pager').getBoundingClientRect();return {{x:f.x+scrollX,y:f.y+scrollY,width:f.width,height:p.bottom-f.top+5,scale:1}}}})()")
                            browser.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':int(clip['y']+clip['height']+50),'deviceScaleFactor':1,'mobile':width<500},page=True)
                            shot=browser.call('Page.captureScreenshot',{'format':'png','clip':clip,'captureBeyondViewport':True},page=True)
                            (output/f'fixture_ticket_pager_{theme}_{width}.png').write_bytes(base64.b64decode(shot['data']))
                            browser.value(f"document.querySelector('{selector} .effectiveness-ticket-footer').removeAttribute('data-pager-fixture')")
                        self.assertTrue(browser.value(f"document.querySelectorAll('{selector} .effectiveness-ticket-row').length===20&&[...document.querySelectorAll('{selector} .effectiveness-ticket-row')].every(r=>r.querySelectorAll('.effectiveness-ball').length===10)"))
                        if width>600:
                            self.assertTrue(browser.value(f"(()=>{{const rows=[...document.querySelectorAll('{selector} .effectiveness-ticket-row')];const x=rows[0].querySelector('.effectiveness-ticket-prize').getBoundingClientRect().x;return rows.every(r=>Math.abs(r.querySelector('.effectiveness-ticket-prize').getBoundingClientRect().x-x)<1&&Math.abs(r.querySelector('.effectiveness-ticket-hits').getBoundingClientRect().y-r.querySelector('.effectiveness-ticket-prize').getBoundingClientRect().y)<6);}})()"))
                        else:
                            self.assertTrue(browser.value(f"[...document.querySelectorAll('{selector} .effectiveness-ticket-row')].every(r=>{{const b=[...r.querySelectorAll('.effectiveness-ball')].map(e=>e.getBoundingClientRect());return b.slice(0,5).every(e=>Math.abs(e.y-b[0].y)<1)&&b.slice(5).every(e=>Math.abs(e.y-b[5].y)<1)&&b[5].y>b[0].y;}})"))
                        self.assertTrue(browser.value("(()=>{const v=document.querySelector('.effectiveness-method-view');const p=v.querySelector('[data-method-pair]:not([hidden])');const cards=[...p.querySelectorAll('[data-method]')].map(e=>e.getBoundingClientRect());return cards.length===2&&(innerWidth>1200?Math.abs(cards[0].top-cards[1].top)<1&&cards[1].left>cards[0].right:Math.abs(cards[0].left-cards[1].left)<1&&cards[1].top>cards[0].bottom)})()"), f'pair geometry {theme} {width}')
                        if width>1200:
                            self.assertTrue(browser.value("[...document.querySelector('.effectiveness-method-view').querySelectorAll('[data-method-pair]:not([hidden]) .effectiveness-ticket-row')].every(r=>{const balls=[...r.querySelectorAll('.effectiveness-ball')].map(e=>e.getBoundingClientRect());return balls.length===10&&balls.every(b=>Math.abs(b.y-balls[0].y)<1)})"), f'paired Keno balls fit one row {theme} {width}')
                        if aligned_artifacts and width in (320,390,768,1440):
                            output=Path(aligned_artifacts).resolve()
                            self.assertTrue(output.is_relative_to(ROOT.resolve()))
                            output.mkdir(parents=True,exist_ok=True)
                            browser.value("document.querySelector('.effectiveness-method-view').setAttribute('data-layout-fixture','Dữ liệu kiểm thử · Keno bậc 10');if(!document.getElementById('alignedFixtureStyle')){const s=document.createElement('style');s.id='alignedFixtureStyle';s.textContent='[data-layout-fixture]::before{content:attr(data-layout-fixture);display:block;margin-bottom:5px;font-size:10px;color:var(--effectiveness-muted)}';document.head.append(s)}")
                            clip=browser.value("(()=>{const r=document.querySelector('.effectiveness-method-view').getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()")
                            browser.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':int(clip['y']+clip['height']+50),'deviceScaleFactor':1,'mobile':width<500},page=True)
                            clip=browser.value("(()=>{const r=document.querySelector('.effectiveness-method-view').getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()")
                            shot=browser.call('Page.captureScreenshot',{'format':'png','clip':clip,'captureBeyondViewport':True},page=True)
                            (output/f'fixture_paired_web_random_{theme}_{width}.png').write_bytes(base64.b64decode(shot['data']))
                            select_method('bayesian')
                            clip=browser.value("(()=>{const r=document.querySelector('.effectiveness-method-view').getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()")
                            browser.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':int(clip['y']+clip['height']+50),'deviceScaleFactor':1,'mobile':width<500},page=True)
                            clip=browser.value("(()=>{const r=document.querySelector('.effectiveness-method-view').getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()")
                            shot=browser.call('Page.captureScreenshot',{'format':'png','clip':clip,'captureBeyondViewport':True},page=True)
                            (output/f'fixture_paired_bayesian_ewma_{theme}_{width}.png').write_bytes(base64.b64decode(shot['data']))
                            select_method('web')
                browser.value("document.body.classList.remove('light-theme')")
                report.pop('_keepMethodTickets')
                summary_entry['tickets'] = before_layout_tickets
                summary_entry['ticketResults'] = before_layout_results
                summary_entry['meanHits'] = before_layout_mean
                for key, entry in before_pair_layout.items():
                    summary_cycle['methods'][key] = entry
                summary_entry.pop('ticketPagination')
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait("!document.getElementById('effectivenessRefresh').disabled")
                money_artifacts = os.environ.get('LOTTO_PRIZE_MONEY_ARTIFACT_DIR')
                for theme in ('dark', 'light'):
                    browser.value(f"document.body.classList.toggle('light-theme',{str(theme=='light').lower()})")
                    for width in (320, 390, 1440):
                        browser.call('Emulation.setDeviceMetricsOverride', {'width':width,'height':900,'deviceScaleFactor':1,'mobile':width<500}, page=True)
                        browser.value("document.querySelector('.effectiveness-cycle').open=true")
                        self.assertTrue(browser.value('document.documentElement.scrollWidth<=innerWidth+2'))
                        self.assertTrue(browser.value(f"[...document.querySelectorAll('{selector} .effectiveness-prize-equation > *')].every(e=>e.scrollWidth<=e.clientWidth+2)"), f'money overflow {theme} {width}')
                        if money_artifacts:
                            output = Path(money_artifacts).resolve()
                            self.assertTrue(output.is_relative_to(ROOT.resolve()))
                            output.mkdir(parents=True, exist_ok=True)
                            browser.value(f"document.querySelector('{selector} .effectiveness-prize-summary').setAttribute('data-fixture-label','Dữ liệu kiểm thử')")
                            clip = browser.value(f"(()=>{{const r=document.querySelector('{selector} .effectiveness-prize-summary').getBoundingClientRect();return {{x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}};}})()")
                            browser.call('Emulation.setDeviceMetricsOverride', {'width':width,'height':int(clip['y']+clip['height']+50),'deviceScaleFactor':1,'mobile':width<500}, page=True)
                            shot=browser.call('Page.captureScreenshot', {'format':'png','clip':clip,'captureBeyondViewport':True}, page=True)
                            (output/f'fixture_prize_money_{theme}_{width}.png').write_bytes(base64.b64decode(shot['data']))
                browser.value("document.body.classList.remove('light-theme')")
                # Fixed tiers for every Keno level, including bậc 1 and 2.
                money_posts = sum(method == 'POST' for method, _, _ in requests)
                for level, code, unit in [(1,'KENO_1_1',20000),(2,'KENO_2_2',90000),(3,'KENO_3_3',200000),
                                          (4,'KENO_4_4',400000),(5,'KENO_5_4',150000),(6,'KENO_6_6',12500000),
                                          (7,'KENO_7_7',40000000),(8,'KENO_8_0',10000),(9,'KENO_9_0',10000),(10,'KENO_10_5',20000)]:
                    summary_cycle['level'] = level
                    summary_entry.update(ticketCount=20, prizeCounts={code:20})
                    browser.value(f"document.getElementById('effectivenessKenoLevel').value='{level}';document.getElementById('effectivenessRefresh').click()")
                    wait("!document.getElementById('effectivenessRefresh').disabled")
                    self.assertEqual(browser.value(f"document.querySelector('{selector} [data-prize-reward]')?.dataset.prizeReward"), str(unit*20),
                                     browser.value(f"document.querySelector('{selector} .effectiveness-prize-summary')?.textContent"))
                    self.assertEqual(browser.value(f"document.querySelector('{selector} [data-prize-net]').dataset.prizeNet"), str(unit*20-200000))
                    net_class = 'is-even' if unit == 10000 else 'is-positive'
                    self.assertTrue(browser.value(f"document.querySelector('{selector} .effectiveness-prize-net').classList.contains('{net_class}')"))
                # Unknown results and variable/shared payouts cannot produce
                # a certain net amount or multiply the jackpot pool per ticket.
                for level, code in [(8,'KENO_8_8'),(9,'KENO_9_9'),(10,'KENO_10_10')]:
                    summary_cycle['level'] = level
                    summary_entry['prizeCounts'] = {code:20}
                    browser.value(f"document.getElementById('effectivenessKenoLevel').value='{level}';document.getElementById('effectivenessRefresh').click()")
                    wait(f"document.querySelector('{selector} [data-prize-code={code}]')!==null && !document.getElementById('effectivenessRefresh').disabled")
                    self.assertEqual(browser.value(f"document.querySelector('{selector} [data-prize-net]').dataset.prizeNet"), '')
                summary_entry['prizeCounts'] = {'KENO_10_5': 19, 'UNKNOWN': 1}
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait(f"document.querySelector('{selector} .effectiveness-prize-summary')?.textContent.includes('1 vé chưa xác định')")
                self.assertEqual(browser.value(f"document.querySelector('{selector} [data-prize-net]').dataset.prizeNet"), '')
                for game, counts, expected in [
                    ('LOTO_5_35',{'FIRST':1,'SECOND':2,'THIRD':3,'FOURTH':4,'FIFTH':5,'CONSOLATION':5}, 22100000),
                    ('LOTO_6_45',{'FIRST':1,'SECOND':2,'THIRD':3,'NONE':14},10690000),
                    ('LOTO_6_55',{'FIRST':1,'SECOND':2,'THIRD':3,'NONE':14},41150000)]:
                    report['type'] = game
                    summary_cycle.update(level=None, actualMain=actual_before_money)
                    summary_entry['prizeCounts'] = counts
                    browser.value(f"document.getElementById('effectivenessType').value='{game}';document.getElementById('effectivenessType').dispatchEvent(new Event('change'))")
                    wait(f"document.querySelector('{selector} [data-prize-reward]')?.dataset.prizeReward==='{expected}'")
                    self.assertEqual(browser.value(f"document.querySelector('{selector} [data-prize-net]').dataset.prizeNet"), str(expected-200000))
                self.assertEqual(sum(method == 'POST' for method, _, _ in requests), money_posts)
                report['type'] = 'LOTO_6_45'
                summary_cycle['level'] = None
                for counts, expected in [({'NONE': 20}, 'Chưa có vé trúng'), ({'UNKNOWN': 20}, 'Chưa xác định vé trúng'),
                                         ({'<img src=x onerror=alert(1)>': 20}, 'Chưa xác định vé trúng'),
                                         ({'FIRST': 1}, 'Chưa đủ dữ liệu thống kê toàn bộ vé')]:
                    summary_entry['prizeCounts'] = counts
                    browser.value("document.getElementById('effectivenessType').value='LOTO_6_45';document.getElementById('effectivenessType').dispatchEvent(new Event('change'));document.getElementById('effectivenessRefresh').click()")
                    wait(f"document.querySelector('{selector} .effectiveness-prize-summary')?.textContent.startsWith({json.dumps(expected)})")
                    if counts == {'NONE': 20}:
                        self.assertEqual(browser.value(f"document.querySelector('{selector} [data-prize-net]').dataset.prizeNet"), '-200000')
                    self.assertEqual(browser.value(f"document.querySelectorAll('{selector} .effectiveness-prize-summary img').length"), 0)
                # Legacy complete arrays are usable; an incomplete page or
                # duplicate ticket indices cannot produce a portfolio count.
                summary_entry.pop('prizeCounts')
                summary_entry['tickets'] = [{'main': [1, 2, 3, 4, 5, 6]} for _ in range(20)]
                summary_entry['ticketResults'] = [
                    {'ticketIndex': index + 1, 'prizeCode': 'MEGA_JACKPOT' if index == 0 else 'NONE',
                     'status': 'won' if index == 0 else 'lost'} for index in range(20)
                ]
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait(f"document.querySelector('{selector} .effectiveness-prize-best strong')?.textContent==='Jackpot'")
                summary_entry['ticketResults'][-1]['ticketIndex'] = 1
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait(f"document.querySelector('{selector} .effectiveness-prize-summary')?.textContent==='Chưa đủ dữ liệu thống kê toàn bộ vé'")
                summary_cycle['actualMain'] = []
                summary_entry['prizeCounts'] = {'MEGA_JACKPOT': 20}
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait(f"document.querySelector('{selector} .effectiveness-prize-summary')?.textContent==='Chờ kết quả'")
                report = original_report
                browser.value(f"document.getElementById('effectivenessKenoLevel').value={json.dumps(original_keno_level)}")
                browser.value("document.getElementById('effectivenessType').value='LOTO_6_55';document.getElementById('effectivenessType').dispatchEvent(new Event('change'))")
                wait("document.querySelectorAll('.effectiveness-cycle').length===3")
                self.assertEqual(browser.value('uiErrors'), [])
                template = json.loads(json.dumps(report["cycles"][1]))
                pagination_posts = sum(method == 'POST' for method, _, _ in requests)
                artifacts = os.environ.get('LOTTO_DRAW_PAGINATION_ARTIFACT_DIR')
                def capture_pager(game):
                    if not artifacts:
                        return
                    output = Path(artifacts).resolve()
                    self.assertTrue(output.is_relative_to(ROOT.resolve()))
                    output.mkdir(parents=True, exist_ok=True)
                    browser.value("document.querySelectorAll('#effectivenessCycles > details').forEach(item=>item.open=false)")
                    browser.value("(()=>{const note=document.createElement('p');note.id='paginationFixtureNote';note.textContent='Dữ liệu kiểm thử · '+document.getElementById('effectivenessType').selectedOptions[0].textContent;note.style.fontSize='12px';document.querySelector('.effectiveness-history-head').before(note)})()")
                    for width in (320, 390, 1440):
                        browser.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 900, 'deviceScaleFactor': 1, 'mobile': width < 500}, page=True)
                        for theme in ('dark', 'light'):
                            browser.value("document.body.classList.toggle('light-theme'," + str(theme == 'light').lower() + ");window.scrollTo({top:0,behavior:'instant'})")
                            self.assertTrue(browser.value('document.documentElement.scrollWidth <= innerWidth + 2'), f'{game} pagination overflow at {width}px')
                            clip = browser.value("(()=>{const head=document.getElementById('paginationFixtureNote').getBoundingClientRect();const bottom=document.getElementById('effectivenessKenoPager').getBoundingClientRect();const box=document.getElementById('predictRootEffectiveness').getBoundingClientRect();return {x:Math.max(0,box.left),y:Math.max(0,head.top+scrollY-8),width:box.width,height:bottom.bottom-head.top+24,scale:1}})()")
                            # Paint the whole crop on mobile rather than capturing an unpainted tail.
                            browser.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': int(clip['y'] + clip['height'] + 50), 'deviceScaleFactor': 1, 'mobile': width < 500}, page=True)
                            image = browser.call('Page.captureScreenshot', {'clip': clip, 'captureBeyondViewport': True}, page=True)['data']
                            (output / f'fixture_{game}_{theme}_{width}.png').write_bytes(base64.b64decode(image))
                    browser.value("document.getElementById('paginationFixtureNote').remove();document.body.classList.remove('light-theme')")
                for game in ('LOTO_5_35', 'LOTO_6_45', 'LOTO_6_55', 'KENO'):
                    report.update({'type': game, '_manyCycles': True, 'counts': {'scored': 44, 'locked': 0, 'total': 44}})
                    report['cycles'] = []
                    for index in range(44):
                        cycle = json.loads(json.dumps(template))
                        cycle.update(targetDrawId=str(800 - index), actualMain=list(range(1, (20 if game == 'KENO' else 5 if game == 'LOTO_5_35' else 6) + 1)))
                        for key, entry in cycle['methods'].items():
                            entry['predictionId'] = f'fixture-{game}-{index}-{key}'
                            entry.pop('ticketPagination', None)
                            entry.pop('ticketCount', None)
                        report['cycles'].append(cycle)
                    browser.value(f"document.getElementById('effectivenessType').value='{game}';document.getElementById('effectivenessType').dispatchEvent(new Event('change'))")
                    page_size = 10 if game == 'KENO' else 3
                    pages = (44 + page_size - 1) // page_size
                    wait(f"document.getElementById('effectivenessKenoPageInfo').textContent.includes('Trang 1 / {pages}') && !document.getElementById('effectivenessRefresh').disabled")
                    self.assertEqual(browser.value("document.querySelectorAll('#effectivenessCycles .effectiveness-cycle[open]').length"), 0)
                    self.assertEqual(selected_method(), 'web')
                    select_method('ewma')
                    aggregate = browser.value("document.getElementById('effectivenessComparison').textContent")
                    self.assertTrue(browser.value("document.getElementById('effectivenessKenoPrevious').disabled"))
                    if game == 'LOTO_5_35':
                        self.assertIn('…', browser.value("document.getElementById('effectivenessCyclePages').textContent"))
                        capture_pager(game)
                    if game == 'KENO':
                        capture_pager(game)
                    seen = []
                    for page_number in range(1, pages + 1):
                        wait(f"document.getElementById('effectivenessKenoPageInfo').textContent.includes('Trang {page_number} / {pages}') && !document.getElementById('effectivenessRefresh').disabled")
                        ids = browser.value("Array.from(document.querySelectorAll('#effectivenessCycles > details'),item=>item.dataset.effectivenessState.split(':').at(-1))")
                        if page_number > 1:
                            self.assertEqual(selected_method(), 'web')
                        self.assertEqual(len(ids), min(page_size, 44 - (page_number - 1) * page_size))
                        seen.extend(ids)
                        self.assertEqual(aggregate, browser.value("document.getElementById('effectivenessComparison').textContent"))
                        self.assertEqual(str(page_number), browser.value("document.querySelector('#effectivenessCyclePages [aria-current=page]').dataset.cyclePage"))
                        if page_number < pages:
                            browser.value("document.getElementById('effectivenessKenoNext').click()")
                    self.assertEqual(seen, [str(800 - index) for index in range(44)])
                    self.assertTrue(browser.value("document.getElementById('effectivenessKenoNext').disabled"))
                    browser.value("document.querySelector('#effectivenessCyclePages [data-cycle-page=\"1\"]').click()")
                    wait(f"document.getElementById('effectivenessKenoPageInfo').textContent.includes('Trang 1 / {pages}') && !document.getElementById('effectivenessRefresh').disabled")
                    self.assertEqual(selected_method(), 'bayesian')
                    select_method('web')
                    browser.value("document.getElementById('effectivenessKenoNext').click()")
                    wait(f"document.getElementById('effectivenessKenoPageInfo').textContent.includes('Trang 2 / {pages}') && !document.getElementById('effectivenessRefresh').disabled")
                    browser.value("document.getElementById('effectivenessRefresh').click()")
                    wait(f"document.getElementById('effectivenessKenoPageInfo').textContent.includes('Trang 2 / {pages}') && !document.getElementById('effectivenessRefresh').disabled")
                    if game != 'KENO':
                        browser.value("document.getElementById('effectivenessLimit').value='30';document.getElementById('effectivenessLimit').dispatchEvent(new Event('change'))")
                        wait("document.getElementById('effectivenessKenoPageInfo').textContent.includes('Trang 1 / 10') && !document.getElementById('effectivenessRefresh').disabled")
                        browser.value("document.getElementById('effectivenessLimit').value='100';document.getElementById('effectivenessLimit').dispatchEvent(new Event('change'))")
                        wait("document.getElementById('effectivenessKenoPageInfo').textContent.includes('Trang 1 / 15') && !document.getElementById('effectivenessRefresh').disabled")
                self.assertEqual(pagination_posts, sum(method == 'POST' for method, _, _ in requests))
                report.clear()
                report.update(saved_report)
                report.update({"type": "KENO", "counts": {"scored": 20, "locked": 1, "total": 21},
                               "settings": {"enabled": True, "ticketCount": 3}, "canManage": True,
                               "automation": {"sourceSync": {"lastAttempt": "2026-10-09T03:57:00Z", "lastSuccess": "2026-10-09T03:57:00Z", "latestKy": "298629", "latestTime": "10:56", "error": ""}},
                               "levels": [{"level": level, "methods": {key: {"meanHits": level / 4, "winningTicketRate": .12,
                                           "deltaVsRandom": 0, "sampleCount": 20} for key in keys}} for level in range(1, 11)]})
                report["methods"] = [{"key": key, "meanHits": 2.5, "winningTicketRate": .12, "fullMatchRate": .01,
                                      "sampleCount": 20, "dayCount": 1, "decision": "insufficient_evidence"} for key in keys]
                report["cycles"][0].update({"status": "scored", "actualMain": list(range(1, 21)),
                                           "actualSpecial": None, "scoredAt": "2026-10-08T09:53:00Z", "config": {"ticketCount": 3}})
                browser.value("document.getElementById('effectivenessType').value='KENO';document.getElementById('effectivenessType').dispatchEvent(new Event('change'))")
                wait("document.querySelectorAll('.effectiveness-cycle .effectiveness-ticket-row').length===12")
                self.assertIn("Tự cập nhật Keno · CSV kỳ 298629 lúc 10:56", browser.value("document.getElementById('effectivenessMixedWarning').textContent"))
                report["automation"]["sourceSync"]["error"] = "Nguồn offline <img src=x onerror=alert(1)>"
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait("document.getElementById('effectivenessMixedWarning').textContent.includes('đang chờ nguồn')")
                self.assertEqual(browser.value("document.querySelectorAll('#effectivenessMixedWarning img').length"), 0)
                report["automation"]["sourceSync"]["error"] = ""
                self.assertTrue(browser.value("document.getElementById('effectivenessLab').hidden"))
                self.assertTrue(browser.value("document.getElementById('effectivenessLimitLabel').hidden"))
                self.assertEqual(browser.value("document.querySelectorAll('#effectivenessKenoOverview tbody tr').length"), 10)
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle .effectiveness-ticket-hits').textContent"), "10/10")
                self.assertNotIn("ĐB", browser.value("document.querySelector('.effectiveness-cycle .effectiveness-cycle-preview').textContent"))
                self.assertIn("Có giải", browser.value("document.getElementById('effectivenessComparison').textContent"))
                self.assertIn("Trùng đủ", browser.value("document.getElementById('effectivenessComparison').textContent"))
                self.assertFalse(browser.value("document.getElementById('effectivenessKenoLevels').hidden"))
                self.assertEqual(browser.value("document.querySelectorAll('#effectivenessKenoLevels button').length"), 10)
                self.assertEqual(browser.value("document.querySelector('#effectivenessKenoLevels [aria-pressed=true]').dataset.kenoLevel"), "10")
                browser.call("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 650, "deviceScaleFactor": 1, "mobile": False}, page=True)
                browser.value("document.querySelector('.effectiveness-history-head').scrollIntoView({block:'start',behavior:'instant'});window.historyHeadTop=document.querySelector('.effectiveness-history-head').getBoundingClientRect().top;document.querySelector('#effectivenessKenoLevels [data-keno-level=\"4\"]').click()")
                wait("document.querySelector('.effectiveness-cycle .effectiveness-ticket-hits')?.textContent==='4/4' && !document.getElementById('effectivenessRefresh').disabled")
                self.assertEqual(browser.value("document.getElementById('effectivenessKenoLevel').value"), "4")
                self.assertEqual(browser.value("document.querySelector('#effectivenessKenoLevels [aria-pressed=true]').dataset.kenoLevel"), "4")
                self.assertEqual(browser.value("document.querySelectorAll('#effectivenessCycles .effectiveness-cycle[open]').length"), 0)
                # Collapsed details can shorten the page so the browser reaches
                # the document bottom before the old anchor position.
                self.assertTrue(browser.value("Math.abs(document.querySelector('.effectiveness-history-head').getBoundingClientRect().top-window.historyHeadTop)<3 || Math.abs(scrollY-Math.max(0,document.documentElement.scrollHeight-innerHeight))<3"))
                request_count = len(requests)
                browser.value("document.querySelector('#effectivenessKenoLevels [data-keno-level=\"4\"]').click()")
                time.sleep(.1)
                self.assertEqual(len(requests), request_count)
                report["_rejectLevel"] = 5
                browser.value("document.querySelector('#effectivenessKenoLevels [data-keno-level=\"5\"]').click()")
                wait("document.getElementById('effectivenessStatus').dataset.kind==='error'")
                self.assertEqual(browser.value("document.getElementById('effectivenessKenoLevel').value"), "4")
                self.assertEqual(browser.value("document.querySelector('#effectivenessKenoLevels [aria-pressed=true]').dataset.kenoLevel"), "4")
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle .effectiveness-ticket-hits').textContent"), "4/4")
                del report["_rejectLevel"]
                browser.value("document.querySelector('.effectiveness-keno-overview').open=true;document.querySelector('[data-keno-level=\"2\"]').click()")
                wait("document.querySelector('.effectiveness-cycle .effectiveness-ticket-hits')?.textContent==='2/2'")
                self.assertEqual(browser.value("document.querySelectorAll('.effectiveness-cycle .effectiveness-ticket-row').length"), 12)
                browser.value("document.getElementById('effectivenessKenoNext').click()")
                wait("document.getElementById('effectivenessKenoPageInfo').textContent.includes('Trang 2 / 3')")
                self.assertIn("Kỳ 298", browser.value("document.querySelector('.effectiveness-cycle').textContent"))
                browser.value("document.querySelector('#effectivenessKenoLevels [data-keno-level=\"9\"]').click();document.querySelector('#effectivenessKenoLevels [data-keno-level=\"1\"]').click()")
                wait("document.querySelector('.effectiveness-cycle .effectiveness-ticket-hits')?.textContent==='1/1'")
                time.sleep(.4)
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle .effectiveness-ticket-hits').textContent"), "1/1")
                self.assertEqual(browser.value("document.getElementById('effectivenessKenoLevel').value"), "1")
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').max"), '80')
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').placeholder"), 'Max 80')
                browser.value("document.getElementById('effectivenessKenoLevel').value='10';document.getElementById('effectivenessKenoLevel').dispatchEvent(new Event('change'))")
                wait("document.querySelector('.effectiveness-cycle .effectiveness-ticket-hits')?.textContent==='10/10'")
                self.assertEqual(browser.value("document.querySelector('#effectivenessKenoLevels [aria-pressed=true]').dataset.kenoLevel"), "10")
                browser.value("document.querySelector('.effectiveness-keno-overview').open=false")
                report["canManage"] = True
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait("!document.getElementById('effectivenessSettings').hidden&&!document.getElementById('effectivenessSettings').disabled")
                input_posts = sum(method == 'POST' for method, _, _ in requests)
                browser.value("document.getElementById('effectivenessSettings').click()")
                for level, maximum, hint in ((1, 80, 'Max 80'), (2, 3160, 'Max 3.160'), (3, 82160, 'Max 82.160'), (10, 100000, 'Max 100.000')):
                    browser.value(f"document.getElementById('effectivenessKenoLevel').value='{level}';document.getElementById('effectivenessKenoLevel').dispatchEvent(new Event('change'))")
                    wait(f"document.querySelector('.effectiveness-cycle .effectiveness-ticket-hits')?.textContent==='{level}/{level}'&&!document.getElementById('effectivenessTicketCount').disabled")
                    self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').max"), str(maximum))
                    self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').placeholder"), hint)
                    browser.value("document.getElementById('effectivenessTicketCount').value='';document.getElementById('effectivenessTicketCount').focus()")
                    browser.call('Input.insertText', {'text': str(maximum + 250)}, page=True)
                    self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').value"), f'{maximum:,}'.replace(',', '.'))
                    browser.value("document.getElementById('effectivenessTicketCount').value='';document.getElementById('effectivenessTicketCount').dispatchEvent(new Event('input'))")
                    self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').value"), '')
                    browser.value("document.getElementById('effectivenessTicketCount').blur()")
                    self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').value"), '1')
                self.assertEqual(sum(method == 'POST' for method, _, _ in requests), input_posts)
                browser.value("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
                for width in (320, 390, 1440):
                    browser.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 1050, "deviceScaleFactor": 1, "mobile": width < 500}, page=True)
                    self.assertTrue(browser.value("document.documentElement.scrollWidth<=window.innerWidth+2"), f"Keno overflows at {width}px")
                    self.assertTrue(browser.value("(()=>{const buttons=[...document.querySelectorAll('#effectivenessKenoLevels button')];return Math.max(...buttons.map(b=>b.getBoundingClientRect().top))-Math.min(...buttons.map(b=>b.getBoundingClientRect().top))<1})()"))
                    screenshot = browser.call("Page.captureScreenshot", {"captureBeyondViewport": True}, page=True)["data"]
                    (ROOT / f"runtime/keno_effectiveness_2026-10-08/keno_ui_{width}.png").write_bytes(base64.b64decode(screenshot))
                    browser.value("document.querySelector('#effectivenessKenoLevels [data-keno-level=\"1\"]').click()")
                    wait("document.querySelector('.effectiveness-cycle .effectiveness-ticket-hits')?.textContent==='1/1'")
                    browser.value("document.querySelector('#effectivenessKenoLevels [data-keno-level=\"10\"]').click()")
                    wait("document.querySelector('.effectiveness-cycle .effectiveness-ticket-hits')?.textContent==='10/10'")
                    self.assertTrue(browser.value("(()=>{const bar=document.getElementById('effectivenessKenoLevels').getBoundingClientRect();const selected=document.querySelector('#effectivenessKenoLevels [aria-pressed=true]').getBoundingClientRect();return selected.left>=bar.left&&selected.right<=bar.right})()"))
                    clip = browser.value("(()=>{const head=document.querySelector('.effectiveness-history-head').getBoundingClientRect();return {x:head.x,y:head.y+scrollY,width:head.width,height:head.height+80,scale:1}})()")
                    cropped = browser.call("Page.captureScreenshot", {"clip": clip, "captureBeyondViewport": True}, page=True)["data"]
                    (ROOT / f"runtime/keno_effectiveness_2026-10-08/level_buttons_{width}.png").write_bytes(base64.b64decode(cropped))
                    browser.value("document.getElementById('effectivenessSettings').click()")
                    self.assertTrue(browser.value("document.getElementById('effectivenessAdmin').open"))
                    self.assertTrue(browser.value("(()=>{const panel=document.getElementById('effectivenessAdmin').getBoundingClientRect();const gear=document.getElementById('effectivenessSettings').getBoundingClientRect();const refresh=document.getElementById('effectivenessRefresh').getBoundingClientRect();return panel.width>0&&panel.left>=0&&panel.right<=innerWidth&&Math.abs(gear.top-refresh.top)<1&&Math.abs(gear.height-40)<1&&gear.left>=refresh.right})()"))
                    for theme in ("dark", "light"):
                        browser.value("document.body.classList.toggle('light-theme'," + str(theme == "light").lower() + ");window.scrollTo({top:0,behavior:'instant'})")
                        shot = browser.call("Page.captureScreenshot", {"captureBeyondViewport": True}, page=True)["data"]
                        (ROOT / f"runtime/keno_effectiveness_2026-10-08/settings_{theme}_{width}.png").write_bytes(base64.b64decode(shot))
                        browser.value("document.getElementById('effectivenessHelpButton').click()")
                        self.assertFalse(browser.value("document.getElementById('effectivenessAdmin').open"))
                        self.assertTrue(browser.value("(()=>{const help=document.getElementById('effectivenessHelpButton').getBoundingClientRect();const gear=document.getElementById('effectivenessSettings').getBoundingClientRect();const panel=document.getElementById('effectivenessHelpPanel').getBoundingClientRect();return panel.width>0&&panel.left>=0&&panel.right<=innerWidth&&help.left>=gear.right&&Math.abs(help.top-gear.top)<1&&Math.abs(help.width-40)<1&&Math.abs(help.height-gear.height)<1})()"))
                        self.assertTrue(browser.value('document.documentElement.scrollWidth <= innerWidth + 2'))
                        help_artifacts = os.environ.get('LOTTO_HELP_BUTTON_ARTIFACT_DIR')
                        if help_artifacts:
                            output = Path(help_artifacts).resolve()
                            self.assertTrue(output.is_relative_to(ROOT.resolve()))
                            output.mkdir(parents=True, exist_ok=True)
                            browser.value("document.getElementById('effectivenessHelpTitle').textContent='Cách đọc kết quả · dữ liệu kiểm thử'")
                            clip = browser.value("(()=>{const toolbar=document.querySelector('.effectiveness-toolbar').getBoundingClientRect();const panel=document.getElementById('effectivenessHelpPanel').getBoundingClientRect();const root=document.getElementById('predictRootEffectiveness').getBoundingClientRect();return {x:Math.max(0,root.left),y:Math.max(0,toolbar.top+scrollY-6),width:root.width,height:panel.bottom-toolbar.top+16,scale:1}})()")
                            image = browser.call('Page.captureScreenshot', {'clip': clip, 'captureBeyondViewport': True}, page=True)['data']
                            (output / f'fixture_help_{theme}_{width}.png').write_bytes(base64.b64decode(image))
                            browser.value("document.getElementById('effectivenessHelpTitle').textContent='Cách đọc kết quả'")
                        browser.value("document.getElementById('effectivenessHelpButton').click();document.getElementById('effectivenessSettings').click()")
                    browser.value("document.body.classList.remove('light-theme');document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
                self.assertFalse(any(method == "POST" and "type=KENO" in body for method, path, body in requests))
                # Complete legacy arrays cycle locally without requesting a page.
                local_cycle = json.loads(json.dumps(summary_cycle))
                local_cycle.update(status='scored', actualMain=[1,2,3,4,5,6], actualSpecial=None)
                for key in keys:
                    local_cycle['methods'][key].update(predictionId=f'local_{key}', ticketCount=3,
                        tickets=[{'main':[1,2,3,4,5,7]} for _ in range(3)],
                        ticketResults=[{'ticketIndex':index, 'prizeCode':'FIRST' if index!=2 else 'NONE',
                            'prizeLabel':'Giải Nhất' if index!=2 else 'Không trúng giải',
                            'status':'won' if index!=2 else 'lost'} for index in (1,2,3)],
                        prizeCounts={'FIRST':2,'NONE':1})
                    local_cycle['methods'][key].pop('ticketPagination', None)
                report.update(type='LOTO_6_45', cycles=[local_cycle])
                browser.value("document.getElementById('effectivenessType').value='LOTO_6_45';document.getElementById('effectivenessType').dispatchEvent(new Event('change'))")
                wait("document.querySelector('[data-prediction-id=local_web] [data-prize-jump]')?.textContent==='Giải Nhất'")
                ticket_requests = sum('/api/ml/effectiveness-tickets?' in path for _,path,_ in requests)
                for key in keys:
                    select_method(key)
                    for target in (1,3,1):
                        browser.value(f"document.querySelector('[data-prediction-id=local_{key}] [data-prize-jump]').click()")
                        self.assertEqual(browser.value(f"document.querySelector('[data-prediction-id=local_{key}] .is-prize-target').dataset.ticketIndex"), str(target))
                self.assertEqual(sum('/api/ml/effectiveness-tickets?' in path for _,path,_ in requests), ticket_requests)
                self.assertEqual(browser.value("uiErrors"), [])
                self.assertTrue(any("type=KENO" in path and "level=2" in path and "page=2" in path for method, path, body in requests if method == "GET"))
                for name in ("vietlott-web-effectiveness.js", "vietlott-web-core.js"):
                    result = browser.call("Runtime.evaluate", {"expression": "(async()=>{try{new Function(await (await fetch(" + json.dumps("/" + name) + ")).text());return 'ok'}catch(e){return e.message}})()", "awaitPromise": True, "returnByValue": True}, page=True)
                    self.assertEqual(result["result"].get("value"), "ok")
            finally:
                browser.close()
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
