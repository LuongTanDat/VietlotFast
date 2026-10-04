"""Chrome checks for effectiveness report states without changing real accounts."""
import importlib.util
import json
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
                self.wfile.write(body)

            def do_GET(self):
                if self.path.startswith("/api/ml/effectiveness?"):
                    requests.append(("GET", self.path, ""))
                    return self.respond(json.dumps(report).encode(), "application/json")
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
                browser.value("document.getElementById('predictRootEffectiveness').hidden=false;VietlottEffectiveness.activate(true);window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:true,user:'fixture'}}))")
                wait("!!document.querySelector('.effectiveness-empty')")
                self.assertTrue(browser.value("document.getElementById('effectivenessAdmin').hidden"))
                self.assertEqual(browser.value("document.querySelectorAll('#effectivenessComparison > .effectiveness-table-wrap tbody tr').length"), 4)
                self.assertNotIn("NaN", browser.value("document.getElementById('effectivenessComparison').textContent"))
                self.assertTrue(all(item[0] == "GET" for item in requests))

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
                self.assertFalse(browser.value("document.getElementById('effectivenessTimeline').hidden"))
                self.assertEqual(browser.value("document.querySelectorAll('#effectivenessComparison img').length"), 0)
                self.assertIn("Gộp 3 cấu hình / ngân sách", browser.value("document.getElementById('effectivenessReportNotes').textContent"))
                self.assertIn("chưa hiệu chỉnh", browser.value("document.getElementById('effectivenessReportNotes').textContent"))
                self.assertEqual(browser.value("document.querySelectorAll('#effectivenessReportNotes img').length"), 0)
                self.assertEqual(browser.value("document.querySelectorAll('.effectiveness-cycle:first-child .is-hit').length"), 0)
                self.assertEqual(browser.value("document.querySelectorAll('.effectiveness-cycle:nth-child(2) .is-hit').length"), 12)
                self.assertIn("fixture_model", browser.value("document.querySelector('.effectiveness-cycle').textContent"))
                browser.value("document.querySelector('[data-effectiveness-line=web]').click()")
                self.assertEqual(browser.value("document.querySelector('[data-effectiveness-line=web]').getAttribute('aria-pressed')"), "false")
                browser.value("document.getElementById('effectivenessTicketCount').value='2';document.getElementById('effectivenessSave').click()")
                wait("document.getElementById('effectivenessStatus').textContent.includes('Đã lưu cấu hình')")
                self.assertTrue(any(method == "POST" and path.endswith("settings") and "ticketCount=2" in body for method, path, body in requests))
                browser.value("document.getElementById('effectivenessLock').click()")
                wait("document.getElementById('effectivenessStatus').textContent.includes('quá hạn khóa')")
                self.assertEqual(browser.value("document.getElementById('effectivenessStatus').dataset.kind"), "error")

                browser.call("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True}, page=True)
                self.assertTrue(browser.value("document.documentElement.scrollWidth<=window.innerWidth+2"))
                browser.value("window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:false}}))")
                self.assertTrue(browser.value("document.getElementById('effectivenessAdmin').hidden"))
                self.assertEqual(browser.value("document.getElementById('effectivenessCycles').textContent"), "")
                self.assertEqual(browser.value("document.getElementById('effectivenessReportNotes').textContent"), "")
                self.assertEqual(browser.value("uiErrors"), [])
                for name in ("vietlott-web-effectiveness.js", "vietlott-web-core.js"):
                    result = browser.call("Runtime.evaluate", {"expression": "(async()=>{try{new Function(await (await fetch(" + json.dumps("/" + name) + ")).text());return 'ok'}catch(e){return e.message}})()", "awaitPromise": True, "returnByValue": True}, page=True)
                    self.assertEqual(result["result"].get("value"), "ok")
            finally:
                browser.close()
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
