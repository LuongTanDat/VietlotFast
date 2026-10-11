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
                + section + "<script src=/vietlott-web-effectiveness.js></script>")

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
                    offset = (ticket_page - 1) * 20
                    tickets = [{"main": [1, 2, 3, 4, 5, 6]} for _ in range(20)]
                    return self.respond(json.dumps({"ok": True, "type": report["type"], "predictionId": params["predictionId"][0],
                        "tickets": tickets, "ticketResults": [{"ticketIndex": offset + index + 1, "status": "pending", "prizeLabel": "Chờ kết quả"} for index in range(20)],
                        "ticketPagination": {"page": ticket_page, "pageSize": 20, "offset": offset, "total": 10000, "totalPages": 500}}).encode(), "application/json")
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
                self.assertEqual(browser.value("document.querySelectorAll('#effectivenessComparison > .effectiveness-table-wrap tbody tr').length"), 4)
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
                            "meanHits": 1.5 if scored else None, "bestHits": 2 if scored else None,
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
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').max"), "10000")
                self.assertEqual(browser.value("document.getElementById('effectivenessEnabled').getAttribute('role')"), "switch")
                browser.value("document.getElementById('effectivenessEnabled').checked=true")
                self.assertEqual(browser.value("getComputedStyle(document.querySelector('.effectiveness-tracking-state'),'::after').content"), '"Bật"')
                self.assertEqual(browser.value("getComputedStyle(document.querySelector('.effectiveness-tracking-state')).backgroundColor"), 'rgb(16, 62, 48)')
                browser.value("document.getElementById('effectivenessEnabled').click()")
                self.assertEqual(browser.value("getComputedStyle(document.querySelector('.effectiveness-tracking-state'),'::after').content"), '"Tắt"')
                self.assertEqual(browser.value("getComputedStyle(document.querySelector('.effectiveness-tracking-state')).backgroundColor"), 'rgb(77, 29, 39)')
                browser.value("document.getElementById('effectivenessTicketCount').value='';document.getElementById('effectivenessTicketCount').dispatchEvent(new Event('input'))")
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').placeholder"), 'Max 10.000')
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').value"), '')
                browser.value("document.getElementById('effectivenessTicketCount').focus()")
                browser.call("Input.insertText", {"text": "10001"}, page=True)
                self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').value"), '10000')
                self.assertEqual(sum(method == "POST" for method, _, _ in requests), mutations_before)
                browser.value("document.getElementById('effectivenessSave').click()")
                wait("!document.getElementById('effectivenessRefresh').disabled")
                self.assertTrue(any(method == 'POST' and 'ticketCount=10000' in body and 'enabled=false' in body for method, _, body in requests))
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
                browser.value("document.querySelector('.effectiveness-cycle > summary').click()")
                self.assertTrue(browser.value("document.querySelector('.effectiveness-cycle').open"))
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait("!document.getElementById('effectivenessRefresh').disabled")
                self.assertTrue(browser.value("document.querySelector('.effectiveness-cycle').open"))
                cycle_requests = len(requests)
                browser.value("document.querySelector('.effectiveness-cycle > summary').click()")
                self.assertFalse(browser.value("document.querySelector('.effectiveness-cycle').open"))
                self.assertEqual(len(requests), cycle_requests)
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle .effectiveness-ticket-hits').textContent"), "—")
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-ticket-hits').textContent"), "2/6")
                self.assertFalse(browser.value("document.querySelector('.effectiveness-provenance').open"))
                self.assertFalse(browser.value("document.querySelector('.effectiveness-help').open"))
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
                self.assertEqual(browser.value("document.querySelectorAll('.effectiveness-cycle:nth-child(2) .is-hit').length"), 0)
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle:first-child .effectiveness-ticket-hits').textContent"), "—")
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-ticket-prize').textContent"), "Giải Khuyến Khích")
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-ticket-prize').dataset.prizeStatus"), "won")
                self.assertEqual(browser.value("document.querySelectorAll('.effectiveness-cycle:nth-child(2) .effectiveness-special.is-matched').length"), 4)
                for cycle in report["cycles"]:
                    cycle["actualSpecial"] = None
                    for entry in cycle["methods"].values():
                        entry["ticketResults"] = [{"ticketIndex": 1, "status": "unknown", "prizeLabel": "Chưa xác định giải", "reason": '<img src=x onerror=alert(1)>'}]
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-ticket-prize').dataset.prizeStatus==='unknown'")
                self.assertIn("chưa có dữ liệu", browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-cycle-preview').textContent"))
                self.assertEqual(browser.value("document.querySelectorAll('.effectiveness-cycle img').length"), 0)
                # A large journal loads 20 tickets, preserves absolute ticket
                # numbers across pages/refresh and never creates forecasts.
                large_entry = report['cycles'][0]['methods']['web']
                large_entry.update({'predictionId': 'page_fixture', 'ticketCount': 10000,
                    'tickets': [{'main': [1, 2, 3, 4, 5]} for _ in range(20)],
                    'ticketPagination': {'page': 1, 'pageSize': 20, 'offset': 0, 'total': 10000, 'totalPages': 500}})
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait("!!document.querySelector('[data-prediction-id=page_fixture] [data-ticket-jump]')")
                wait("!document.getElementById('effectivenessRefresh').disabled")
                post_count = sum(method == 'POST' for method, _, _ in requests)
                ticket_gets = lambda: sum('/api/ml/effectiveness-tickets?' in path for method, path, _ in requests if method == 'GET')
                before_gets = ticket_gets()
                self.assertTrue(browser.value("document.querySelector('[data-prediction-id=page_fixture] [data-ticket-page=\"0\"]').disabled"))
                for value in ('', '0', '-12', '1.9', '1'):
                    browser.value(f"{{const jump=document.querySelector('[data-prediction-id=page_fixture] [data-ticket-jump]');jump.value={json.dumps(value)};jump.dispatchEvent(new Event('change',{{bubbles:true}}))}}")
                    self.assertEqual(browser.value("document.querySelector('[data-prediction-id=page_fixture] [data-ticket-jump]').value"), '1')
                self.assertEqual(ticket_gets(), before_gets)
                browser.value("document.querySelector('[data-prediction-id=page_fixture] [data-ticket-page=\"2\"]').click()")
                wait("document.querySelector('[data-prediction-id=page_fixture] .effectiveness-ticket-label')?.textContent==='Vé 21'")
                browser.value("{const jump=document.querySelector('[data-prediction-id=page_fixture] [data-ticket-jump]');jump.value=499.9;jump.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))}")
                wait("document.querySelector('[data-prediction-id=page_fixture] .effectiveness-ticket-label')?.textContent==='Vé 9961'")
                self.assertEqual(browser.value("document.querySelector('[data-prediction-id=page_fixture] [data-ticket-jump]').value"), '499')
                browser.value("{const jump=document.querySelector('[data-prediction-id=page_fixture] [data-ticket-jump]');jump.value=900;jump.dispatchEvent(new Event('change',{bubbles:true}))}")
                wait("document.querySelector('[data-prediction-id=page_fixture] .effectiveness-ticket-label')?.textContent==='Vé 9981'")
                self.assertTrue(browser.value("document.querySelector('[data-prediction-id=page_fixture] [data-ticket-page=\"501\"]').disabled"))
                self.assertEqual(browser.value("document.querySelector('[data-prediction-id=page_fixture] .effectiveness-ticket-range').textContent"), 'Vé 9.981–10.000 / 10.000')
                before_gets = ticket_gets()
                for value in ('', '500', '9999'):
                    browser.value(f"{{const jump=document.querySelector('[data-prediction-id=page_fixture] [data-ticket-jump]');jump.value={json.dumps(value)};jump.dispatchEvent(new KeyboardEvent('keydown',{{key:'Enter',bubbles:true}}));jump.dispatchEvent(new Event('change',{{bubbles:true}}))}}")
                    self.assertEqual(browser.value("document.querySelector('[data-prediction-id=page_fixture] [data-ticket-jump]').value"), '500')
                self.assertEqual(ticket_gets(), before_gets)
                self.assertEqual(browser.value("document.querySelectorAll('[data-prediction-id=page_fixture] .effectiveness-ticket-row').length"), 20)
                browser.value("document.getElementById('effectivenessRefresh').click()")
                wait("!document.getElementById('effectivenessRefresh').disabled")
                self.assertEqual(browser.value("document.querySelector('[data-prediction-id=page_fixture] [data-ticket-jump]').value"), '500')
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
                self.assertIn("Bóng thứ 7", browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-cycle-preview').textContent"))
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-ticket-row:first-child .effectiveness-ticket-prize').textContent"), "Jackpot 2")
                self.assertEqual(browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-ticket-row:nth-child(2) .effectiveness-ticket-prize').textContent"), "Giải Nhất")
                self.assertEqual(browser.value("document.querySelectorAll('.effectiveness-cycle:nth-child(2) .effectiveness-special.is-matched').length"), 0)
                self.assertIn("Phụ 55", browser.value("document.querySelector('.effectiveness-cycle:nth-child(2) .effectiveness-ticket-row').textContent"))
                browser.value("document.querySelector('.effectiveness-cycle:nth-child(2)').open=true")
                for width in (320, 390, 1440):
                    browser.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": width < 500}, page=True)
                    self.assertTrue(browser.value("document.documentElement.scrollWidth<=window.innerWidth+2"), f"Prize row overflows at {width}px")
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
                # outside the visible 20-ticket page; counts sort independently
                # of prize rank and remain stable through paging and refresh.
                original_report = json.loads(json.dumps(report))
                original_keno_level = browser.value("document.getElementById('effectivenessKenoLevel').value")
                report['cycles'] = [json.loads(json.dumps(report['cycles'][1]))]
                summary_cycle = report['cycles'][0]
                summary_entry = summary_cycle['methods']['web']
                summary_entry.update({
                    'predictionId': 'prize_summary_fixture', 'ticketCount': 10000,
                    'tickets': [{'main': [1, 2, 3, 4, 5, 7]} for _ in range(20)],
                    'ticketPagination': {'page': 1, 'pageSize': 20, 'offset': 0, 'total': 10000, 'totalPages': 500},
                    'prizeCounts': {'POWER_JACKPOT_1': 1, 'POWER_JACKPOT_2': 2, 'FIRST': 7,
                                    'SECOND': 9, 'THIRD': 9, 'NONE': 9969, 'UNKNOWN': 3},
                })
                summary_cycle['methods']['random'].update({
                    'predictionId': 'method_random_fixture', 'ticketCount': 10000,
                    'tickets': [{'main': [1, 2, 3, 4, 5, 6]} for _ in range(20)],
                    'ticketPagination': {'page': 1, 'pageSize': 20, 'offset': 0, 'total': 10000, 'totalPages': 500},
                    'prizeCounts': {'FIRST': 10, 'SECOND': 20, 'NONE': 9970},
                })
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
                summary_posts = sum(method == 'POST' for method, _, _ in requests)
                browser.value(f"document.querySelector('{selector} [data-ticket-page=\"2\"]').click()")
                wait(f"document.querySelector('{selector} .effectiveness-ticket-label')?.textContent==='Vé 21'")
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
                wait(f"document.querySelector('{random_selector} .effectiveness-ticket-label')?.textContent==='Vé 41'")
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
                for level, maximum, hint in ((1, 80, 'Max 80'), (2, 3160, 'Max 3.160'), (3, 10000, 'Max 10.000'), (10, 10000, 'Max 10.000')):
                    browser.value(f"document.getElementById('effectivenessKenoLevel').value='{level}';document.getElementById('effectivenessKenoLevel').dispatchEvent(new Event('change'))")
                    wait(f"document.querySelector('.effectiveness-cycle .effectiveness-ticket-hits')?.textContent==='{level}/{level}'&&!document.getElementById('effectivenessTicketCount').disabled")
                    self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').max"), str(maximum))
                    self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').placeholder"), hint)
                    browser.value("document.getElementById('effectivenessTicketCount').value='';document.getElementById('effectivenessTicketCount').focus()")
                    browser.call('Input.insertText', {'text': str(maximum + 250)}, page=True)
                    self.assertEqual(browser.value("document.getElementById('effectivenessTicketCount').value"), str(maximum))
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
                    self.assertTrue(browser.value("(()=>{const panel=document.getElementById('effectivenessAdmin').getBoundingClientRect();const gear=document.getElementById('effectivenessSettings').getBoundingClientRect();const refresh=document.getElementById('effectivenessRefresh').getBoundingClientRect();return panel.width>0&&panel.left>=0&&panel.right<=innerWidth&&Math.abs(gear.top-refresh.top)<1&&Math.abs(gear.height-36)<1&&gear.left>=refresh.right})()"))
                    for theme in ("dark", "light"):
                        browser.value("document.body.classList.toggle('light-theme'," + str(theme == "light").lower() + ");window.scrollTo({top:0,behavior:'instant'})")
                        shot = browser.call("Page.captureScreenshot", {"captureBeyondViewport": True}, page=True)["data"]
                        (ROOT / f"runtime/keno_effectiveness_2026-10-08/settings_{theme}_{width}.png").write_bytes(base64.b64decode(shot))
                        browser.value("document.getElementById('effectivenessHelpButton').click()")
                        self.assertFalse(browser.value("document.getElementById('effectivenessAdmin').open"))
                        self.assertTrue(browser.value("(()=>{const help=document.getElementById('effectivenessHelpButton').getBoundingClientRect();const gear=document.getElementById('effectivenessSettings').getBoundingClientRect();const panel=document.getElementById('effectivenessHelpPanel').getBoundingClientRect();return panel.width>0&&panel.left>=0&&panel.right<=innerWidth&&help.left>=gear.right&&Math.abs(help.top-gear.top)<1&&Math.abs(help.width-36)<1&&Math.abs(help.height-gear.height)<1})()"))
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
