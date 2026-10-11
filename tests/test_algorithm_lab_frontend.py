"""Browser checks for asynchronous lab state and account/game boundaries."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]
CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
CDP_HELPER = ROOT / "tests/browser_cdp.py"
METHODS = ("web", "random", "bayesian", "ewma")


def lab_report(game="LOTO_5_35", label="Pipeline web"):
    metric = {"sampleCount": 20, "meanHits": 1.2, "brierScore": .125, "logLoss": .42,
              "rate3": .1, "rate4": 0, "deltaVsRandom": .05, "ci95": {"lower": -.1, "upper": .2},
              "decision": "insufficient_evidence"}
    return {"ok": True, "type": game, "scope": "historical_diagnostic",
            "parameters": {"ticketCount": 3, "validationCount": 10, "testCount": 20},
            "split": {"training": {"count": 60, "firstDrawId": "1", "lastDrawId": "60"},
                      "validation": {"count": 10, "firstDrawId": "61", "lastDrawId": "70"},
                      "test": {"count": 20, "firstDrawId": "71", "lastDrawId": "90"}},
            "selection": {"selectedMethod": "web", "label": label, "validationOnly": True,
                          "reason": '<img src=x onerror=alert(1)> Chọn bằng validation.'},
            "methods": [{"key": key, "label": label if key == "web" else key,
                         "validation": dict(metric, sampleCount=10), "test": copy.deepcopy(metric)} for key in METHODS],
            "provenance": {"registryModel": {"mode": "legacy_classic", "modelId": None},
                           "requestedEngine": "classic", "sourceHash": "a" * 64, "dataHash": "b" * 64},
            "notes": ["Model giữ nguyên; không retrain mỗi fold.", '<svg onload=alert(1)>'], "folds": []}


def configured_report(game="LOTO_5_35", label="Ngắn hạn · Ổn định"):
    report = lab_report(game)
    profiles = [{"id": f"profile_{index}", "label": label if index == 0 else f"Cấu hình {index + 1}",
                 "historyWindow": 60 if index < 2 else 180 if index < 4 else None,
                 "recentWindow": 15 if index < 2 else 30 if index < 4 else 60,
                 "weights": [.7, 0, .2, .1], "uniformMix": .85,
                 "allocation": "stable" if index % 2 == 0 else "aggressive",
                 "description": "Cửa sổ và phân bổ vé khác nhau.", "version": "profiles_v1"} for index in range(6)]
    for method in report["methods"]:
        method.update(kind="control", profileId=None, configuration=None)
    report["profiles"] = profiles
    report["methods"] += [{"key": profile["id"], "profileId": profile["id"], "kind": "candidate",
                           "label": profile["label"], "configuration": profile,
                           "validation": copy.deepcopy(report["methods"][0]["validation"]),
                           "test": copy.deepcopy(report["methods"][0]["test"])} for profile in profiles]
    report["selection"].update(selectedMethod="random", label="Ngẫu nhiên", candidateProfileId="profile_0",
                                candidateLabel=label, profileDefinition=profiles[0])
    report["conclusion"] = {"status": "insufficient_evidence", "title": "Chưa đủ kỳ để kết luận",
                            "message": "Ngẫu nhiên được tập chọn xếp trước; ứng viên cần thêm kết quả thực tế.",
                            "recommendation": "Theo dõi ứng viên trước giờ quay để kiểm chứng thêm.",
                            "canTrack": True, "candidateProfileId": "profile_0", "candidateLabel": label,
                            "sampleCount": 20, "evidence": {"random": {"brierDelta": .002}}}
    return report


def tracking_report(game="LOTO_5_35", run_id="saved-latest", label="Ngắn hạn · Ổn định"):
    ticket = {"main": [1, 2, 3, 4, 5], "special": 4}
    result = {"status": "won", "prizeLabel": "Độc Đắc", "prizeCode": "LOTTO_JACKPOT",
              "mainHits": 5, "specialMatched": True}
    cycle = {"id": "cycle-91", "targetDrawId": "91", "cutoffDrawId": "90", "status": "scored",
             "actualMain": [1, 2, 3, 4, 5], "actualSpecial": 4,
             "createdAt": "2026-10-06T01:00:00Z", "deadline": "2026-10-06T06:00:00Z",
             "methods": {key: {"tickets": [copy.deepcopy(ticket)], "ticketResults": [copy.deepcopy(result)],
                                "meanHits": 5, "brierScore": .09} for key in ("candidate", "random", "web")}}
    pending = copy.deepcopy(cycle)
    pending.update(id="cycle-92", targetDrawId="92", cutoffDrawId="91", status="locked", actualMain=[], actualSpecial=None)
    for method in pending["methods"].values():
        method.update(ticketResults=[{"ticketIndex": 1, "status": "pending", "prizeLabel": "Chờ kết quả"}], meanHits=None)
    return {"type": game,
            "candidate": {"id": "candidate-1", "type": game, "runId": run_id, "profileId": "profile_0", "label": label,
                          "status": "active", "ticketCount": 1, "startedAt": "2026-10-06T01:00:00Z", "lastError": None},
            "counts": {"scored": 1, "locked": 1, "total": 2},
            "methods": [{"key": key, "label": label if key == "candidate" else key, "sampleCount": 1,
                         "meanHits": 5, "brierScore": .09, "rate3": 1, "rate4": 1,
                         "deltaVsRandom": 0, "ci95": {"lower": 0, "upper": 0}} for key in ("candidate", "random", "web")],
            "cycles": [pending, cycle], "conclusion": {"title": "Chưa đủ bằng chứng", "summary": "Cần thêm kỳ thực tế.", "canApply": False}}


@unittest.skipUnless(CHROME.exists() and CDP_HELPER.exists(), "Chrome/CDP helper unavailable")
class AlgorithmLabFrontendTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("algorithm_lab_cdp", CDP_HELPER)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        self.requests = []
        self.owner = "admin"
        self.can_manage = True
        self.jobs = {}
        self.saved_jobs = {}
        self.histories = {}
        self.tracking = {}
        self.error = None
        self.hold = None
        self.gates = []
        self.job_sequence = 0
        self.cycles = []
        html = (ROOT / "frontend/vietlott-web.html").read_text(encoding="utf-8")
        section = html[html.index('      <section id="predictRootEffectiveness"'):html.index('      <section id="predictRootManual"')]
        page = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
                "<link rel=stylesheet href=/vietlott-web.css><link rel=stylesheet href=/vietlott-web-extra.css>"
                + section + "<script src=/vietlott-web-effectiveness.js></script>")
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, body, content_type="application/json", status=200):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

            def payload(self, payload, status=200):
                body = json.dumps(copy.deepcopy(payload)).encode()
                hold = fixture.hold
                if hold and hold[0] == self.command:
                    fixture.hold = None
                    hold[1].set()
                    hold[2].wait(10)
                self.respond(body, status=status)

            def do_GET(self):
                query = parse_qs(urlsplit(self.path).query)
                game = query.get("type", ["LOTO_5_35"])[0]
                if self.path.startswith("/api/ml/algorithm-lab?"):
                    fixture.requests.append(("GET", self.path, {}))
                    if fixture.error:
                        return self.payload({"ok": False, "error": fixture.error[1]}, fixture.error[0])
                    selected_id = query.get("jobId", [None])[0]
                    job = fixture.saved_jobs.get((fixture.owner, selected_id)) if selected_id else None
                    return self.payload({"ok": True, "type": game, "canManage": fixture.can_manage,
                                         "job": job or fixture.jobs.get((fixture.owner, game)),
                                         "history": fixture.histories.get((fixture.owner, game), []),
                                         "tracking": fixture.tracking.get((fixture.owner, game), {"type": game, "candidate": None})})
                if self.path.startswith("/api/ml/effectiveness?"):
                    fixture.requests.append(("REPORT", self.path, {}))
                    return self.respond(json.dumps({"ok": True, "type": game, "canManage": fixture.can_manage,
                        "settings": {"enabled": False, "ticketCount": 3}, "counts": {"scored": 2, "locked": 1},
                        "methods": [{"key": key, "sampleCount": 2, "meanHits": 1, "decision": "insufficient_evidence"} for key in METHODS],
                        "cycles": fixture.cycles}).encode())
                if self.path == "/":
                    return self.respond(page.encode(), "text/html;charset=utf-8")
                asset = ROOT / "frontend" / self.path.lstrip("/")
                if asset.is_file() and asset.parent == ROOT / "frontend":
                    return self.respond(asset.read_bytes(), "text/css" if asset.suffix == ".css" else "text/javascript")
                self.respond(b"", "text/plain", 404)

            def do_POST(self):
                form = {key: value[0] for key, value in parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode()).items()}
                fixture.requests.append(("POST", self.path, form))
                if fixture.error:
                    return self.payload({"ok": False, "error": fixture.error[1]}, fixture.error[0])
                game = form["type"]
                if form.get("action") in ("start_tracking", "stop_tracking"):
                    if form["action"] == "start_tracking":
                        existing = fixture.tracking.get((fixture.owner, game))
                        if existing:
                            existing["candidate"]["status"] = "active"
                        else:
                            selected = fixture.saved_jobs.get((fixture.owner, form["jobId"])) or fixture.jobs[(fixture.owner, game)]
                            fixture.tracking[(fixture.owner, game)] = tracking_report(game, form["jobId"], selected["report"]["selection"]["candidateLabel"])
                    else:
                        fixture.tracking[(fixture.owner, game)]["candidate"]["status"] = "stopped"
                    return self.payload({"ok": True, "type": game, "canManage": fixture.can_manage,
                                         "tracking": fixture.tracking[(fixture.owner, game)]})
                if form.get("action") == "cancel":
                    job = fixture.jobs[(fixture.owner, game)]
                    job["state"] = "cancelled"
                    job["finishedAt"] = "2026-10-06T01:15:00Z"
                else:
                    fixture.job_sequence += 1
                    job = {"id": fixture.job_sequence, "type": game, "state": "running", "report": None,
                           "createdAt": "2026-10-06T01:00:00Z", "finishedAt": None,
                           **{key: int(form[key]) for key in ("ticketCount", "validationCount", "testCount")}}
                    fixture.jobs[(fixture.owner, game)] = job
                self.payload({"ok": True, "canManage": fixture.can_manage, "job": job})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        runtime = ROOT / "runtime"
        runtime.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="algorithm_lab_ui_", dir=runtime)
        self.browser = helper.Browser(str(CHROME), Path(self.temp.name))
        self.browser.call("Page.enable", page=True)
        self.browser.call("Page.addScriptToEvaluateOnNewDocument", {"source": "window.uiErrors=[];window.addEventListener('error',e=>uiErrors.push(e.message));window.addEventListener('unhandledrejection',e=>uiErrors.push(String(e.reason)));window.nativeFetch=window.fetch;window.ignoreAbort=false;window.fetch=(url,opts)=>nativeFetch(url,ignoreAbort?{...opts,signal:undefined}:opts);"}, page=True)
        self.browser.call("Page.navigate", {"url": f"http://127.0.0.1:{self.server.server_port}/"}, page=True)
        self.wait("!!window.VietlottEffectiveness")
        self.js("document.getElementById('predictRootEffectiveness').hidden=false;VietlottEffectiveness.activate(true);window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:true,user:'admin'}}))")
        self.wait("!!document.querySelector('.effectiveness-empty')")

    def tearDown(self):
        for gate in self.gates:
            gate.set()
        self.browser.close()
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def js(self, source):
        return self.browser.value(source)

    def wait(self, expression, timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.js(expression):
                return
            time.sleep(.05)
        self.fail("Browser condition timed out: " + expression)

    def open_lab(self):
        self.js("document.getElementById('effectivenessLab').open=true")

    def hold_next(self, method):
        entered, release = threading.Event(), threading.Event()
        self.hold = (method, entered, release)
        self.gates.append(release)
        return entered, release

    def lab_gets(self):
        return [request for request in self.requests if request[0] == "GET"]

    def saved_run(self, run_id, label, finished="2026-10-06T01:10:00Z"):
        report = configured_report(label=label)
        job = {"id": run_id, "type": "LOTO_5_35", "state": "completed", "report": report,
               "ticketCount": 3, "validationCount": 10, "testCount": 20,
               "createdAt": "2026-10-06T01:00:00Z", "finishedAt": finished}
        self.saved_jobs[(self.owner, run_id)] = job
        metadata = {key: value for key, value in job.items() if key != "report"}
        metadata.update(candidateProfileId="profile_0", candidateLabel=label, selectedMethod="random", conclusion=report["conclusion"])
        self.histories.setdefault((self.owner, "LOTO_5_35"), []).append(metadata)
        return job

    def test_saved_configuration_conclusion_tracking_history_and_layout(self):
        self.assertEqual(self.js("document.getElementById('effectivenessLabValidation').value"), "20")
        self.assertEqual(self.js("document.getElementById('effectivenessLabTest').value"), "30")
        self.jobs[(self.owner, "LOTO_5_35")] = self.saved_run("saved-latest", "Ngắn hạn · Ổn định")
        self.saved_run("saved-older", "Cấu hình đã lưu trước", "2026-10-05T01:10:00Z")
        self.open_lab()
        self.wait("document.querySelectorAll('#effectivenessLabResult .effectiveness-comparison-table tbody tr').length===10")
        self.assertIn("Chưa đủ kỳ", self.js("document.querySelector('.effectiveness-lab-conclusion h4').textContent"))
        self.assertIn("Ngẫu nhiên", self.js("document.querySelector('.effectiveness-lab-conclusion').textContent"))
        self.assertFalse(self.js("document.querySelector('.effectiveness-lab-comparison').open"))
        self.assertEqual(self.js("document.querySelectorAll('.effectiveness-lab-profile-grid>div').length"), 6)
        self.assertEqual(self.js("document.getElementById('effectivenessLabHistoryCount').textContent"), "2 lượt")
        self.assertFalse(self.js("document.querySelector('[data-lab-track-start]').disabled"))
        self.js("document.getElementById('effectivenessLabHistoryDetails').open=true;document.querySelector('[data-lab-job=\"saved-older\"]').click()")
        self.wait("document.querySelector('.effectiveness-lab-outcome strong').textContent==='Cấu hình đã lưu trước'")
        self.assertTrue(any("jobId=saved-older" in item[1] for item in self.lab_gets()))
        self.assertTrue(self.js("document.querySelector('[data-lab-job=\"saved-older\"]').getAttribute('aria-pressed')==='true'"))
        self.js("document.querySelector('[data-lab-track-start]').click()")
        self.wait("!!document.querySelector('[data-lab-track-stop]')&&!document.querySelector('[data-lab-track-stop]').disabled")
        self.assertEqual([item[2] for item in self.requests if item[0] == "POST"][-1],
                         {"type": "LOTO_5_35", "action": "start_tracking", "jobId": "saved-older"})
        self.assertTrue(self.js("document.querySelector('[data-lab-track-start]').disabled"))
        self.assertEqual(self.js("document.querySelectorAll('#effectivenessLabTracking .effectiveness-comparison-table tbody tr').length"), 3)
        self.assertEqual(self.js("document.querySelectorAll('#effectivenessLabTracking .effectiveness-cycle').length"), 2)
        self.js("Array.from(document.querySelectorAll('#effectivenessLabTracking .effectiveness-cycle')).forEach(c=>c.open=true)")
        self.assertIn("Độc Đắc", self.js("document.getElementById('effectivenessLabTracking').textContent"))
        self.assertIn("Chờ kết quả", self.js("document.getElementById('effectivenessLabTracking').textContent"))
        self.assertEqual(self.js("document.querySelectorAll('#effectivenessCycles .effectiveness-cycle').length"), 0)
        self.assertEqual(self.js("document.querySelector('.effectiveness-summary .effectiveness-metric strong').textContent"), "2")
        self.assertFalse(self.js("document.getElementById('effectivenessLabTracking').textContent.includes('Áp dụng')"))
        for light in (False, True):
            self.js(f"document.body.classList.toggle('light-theme',{str(light).lower()})")
            for width in (320, 390, 760, 1440):
                self.browser.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 1000, "deviceScaleFactor": 1, "mobile": width < 500}, page=True)
                self.assertTrue(self.js("document.documentElement.scrollWidth<=window.innerWidth+2"), f"Workflow overflows at {width}px, light={light}")
                self.js("document.querySelector('.effectiveness-lab-comparison').open=true;document.querySelector('.effectiveness-lab-profiles').open=true;document.querySelector('.effectiveness-lab-provenance').open=true")
                self.assertTrue(self.js("document.documentElement.scrollWidth<=window.innerWidth+2"), f"Expanded workflow overflows at {width}px, light={light}")
                self.js("document.querySelector('.effectiveness-lab-comparison').open=false;document.querySelector('.effectiveness-lab-profiles').open=false;document.querySelector('.effectiveness-lab-provenance').open=false")
        self.js("document.querySelector('[data-lab-track-stop]').click()")
        self.wait("document.querySelector('.effectiveness-lab-tracking-state').textContent==='Đã dừng tạo kỳ mới'&&!document.querySelector('[data-lab-track-start]').disabled")
        self.assertEqual([item[2] for item in self.requests if item[0] == "POST"][-1],
                         {"type": "LOTO_5_35", "action": "stop_tracking", "candidateId": "candidate-1"})
        self.assertEqual(self.js("document.querySelectorAll('#effectivenessLabTracking .effectiveness-cycle').length"), 2)
        self.js("document.querySelector('[data-lab-track-start]').click()")
        self.wait("!!document.querySelector('[data-lab-track-stop]')&&!document.querySelector('[data-lab-track-stop]').disabled")
        self.assertEqual(self.tracking[(self.owner, "LOTO_5_35")]["candidate"]["id"], "candidate-1")
        self.assertTrue(self.js("document.querySelector('.effectiveness-lab-tracking-journal').open"))
        self.owner = "member"
        self.can_manage = False
        self.js("window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:true,user:'member'}}))")
        self.wait("document.getElementById('effectivenessStatus').textContent==='Báo cáo đã cập nhật.'")
        self.open_lab()
        self.wait("document.getElementById('effectivenessLabStatus').textContent.includes('chưa có lượt thử')")
        self.assertEqual(self.js("document.getElementById('effectivenessLabHistoryCount').textContent"), "0 lượt")
        self.assertEqual(self.js("document.getElementById('effectivenessLabTracking').textContent"), "")
        self.assertEqual(self.js("uiErrors"), [])

    def test_tracking_errors_wrong_game_and_stale_start_response(self):
        self.jobs[(self.owner, "LOTO_5_35")] = self.saved_run("saved-latest", "Ứng viên <img src=x>")
        self.open_lab()
        self.wait("!!document.querySelector('[data-lab-track-start]')&&!document.querySelector('[data-lab-track-start]').disabled")
        self.assertEqual(self.js("document.querySelectorAll('#effectivenessLabResult img').length"), 0)
        self.error = (409, "Cấu hình nguồn đã thay đổi; chạy thử lại.")
        self.js("document.querySelector('[data-lab-track-start]').click()")
        self.wait("document.getElementById('effectivenessLabStatus').dataset.kind==='error'")
        self.assertIn("chạy thử lại", self.js("document.getElementById('effectivenessLabStatus').textContent"))
        self.assertEqual(self.js("document.getElementById('effectivenessLabTracking').textContent"), "")
        self.error = None
        entered, release = self.hold_next("POST")
        self.js("window.ignoreAbort=true;document.querySelector('[data-lab-track-start]').click()")
        self.assertTrue(entered.wait(4))
        self.js("document.getElementById('effectivenessType').value='LOTO_6_55';document.getElementById('effectivenessType').dispatchEvent(new Event('change'))")
        self.wait("document.getElementById('effectivenessLabStatus').textContent.includes('chưa có lượt thử')")
        release.set()
        time.sleep(.2)
        self.assertEqual(self.js("document.getElementById('effectivenessLabTracking').textContent"), "")
        self.assertNotIn("Ứng viên", self.js("document.getElementById('effectivenessLabResult').textContent"))
        self.tracking[(self.owner, "LOTO_6_55")] = tracking_report("LOTO_5_35")
        self.js("document.getElementById('effectivenessLab').open=false")
        self.open_lab()
        self.wait("document.getElementById('effectivenessLabStatus').dataset.kind==='error'")
        self.assertEqual(self.js("document.getElementById('effectivenessLabTracking').textContent"), "")
        self.assertEqual(self.js("uiErrors"), [])

    def test_stopped_candidate_keeps_pending_results_fresh_and_pauses_when_closed(self):
        self.jobs[(self.owner, "LOTO_5_35")] = self.saved_run("saved-latest", "Ứng viên đang chờ")
        tracking = tracking_report()
        tracking["candidate"]["status"] = "stopped"
        self.tracking[(self.owner, "LOTO_5_35")] = tracking
        self.js("window.savedTimeout=window.setTimeout;window.setTimeout=(fn,delay,...args)=>savedTimeout(fn,delay>=60000?150:delay,...args)")
        self.open_lab()
        self.wait("!!document.querySelector('.effectiveness-lab-tracking-state')")
        self.assertEqual(self.js("document.querySelector('.effectiveness-lab-tracking-state').textContent"), "Đã dừng tạo kỳ mới")
        self.assertIn("Độc Đắc", self.js("document.getElementById('effectivenessLabTracking').textContent"))
        self.assertNotIn("Chưa có phân loại giải", self.js("document.getElementById('effectivenessLabTracking').textContent"))
        count = len(self.lab_gets())
        tracking["counts"].update(locked=0, scored=2)
        self.wait("document.querySelector('.effectiveness-lab-tracking-counts strong').textContent==='2'")
        self.assertGreater(len(self.lab_gets()), count)
        time.sleep(.25)
        count = len(self.lab_gets())
        time.sleep(.35)
        self.assertEqual(len(self.lab_gets()), count, "Stopped candidate without pending results must not poll")
        tracking["counts"]["locked"] = 1
        self.js("document.getElementById('effectivenessLab').open=false")
        self.open_lab()
        self.wait("document.querySelectorAll('.effectiveness-lab-tracking-counts strong')[1].textContent==='1'")
        self.js("document.getElementById('effectivenessLab').open=false")
        time.sleep(.2)
        count = len(self.lab_gets())
        time.sleep(.35)
        self.assertEqual(len(self.lab_gets()), count, "Closed lab must not poll pending candidate results")
        self.assertEqual(self.js("uiErrors"), [])

    def test_run_poll_cancel_errors_member_and_mobile(self):
        self.assertEqual(self.lab_gets(), [])
        self.open_lab()
        self.wait("document.getElementById('effectivenessLabStatus').textContent.includes('chưa có lượt thử')")
        self.assertFalse(self.js("document.getElementById('effectivenessLabAdmin').hidden"))
        self.js("document.getElementById('effectivenessLabValidation').value='4';document.getElementById('effectivenessLabRun').click()")
        self.wait("document.getElementById('effectivenessLabStatus').dataset.kind==='error'")
        self.assertFalse(any(item[0] == "POST" for item in self.requests))
        self.js("document.getElementById('effectivenessLabValidation').value='10';document.getElementById('effectivenessLabRun').click()")
        self.wait("!document.getElementById('effectivenessLabCancel').hidden")
        self.assertTrue(self.js("document.getElementById('effectivenessLabRun').disabled"))
        self.assertEqual(self.requests[-1][2], {"type": "LOTO_5_35", "ticketCount": "3", "validationCount": "10", "testCount": "30"})
        job = self.jobs[(self.owner, "LOTO_5_35")]
        job.update(state="completed", report=lab_report(label='<img src=x onerror=alert(1)>'), finishedAt="2026-10-06T01:10:00Z")
        self.wait("document.querySelectorAll('#effectivenessLabResult .effectiveness-comparison-table tbody tr').length===4")
        self.assertTrue(any("jobId=1" in item[1] for item in self.lab_gets()))
        self.assertEqual(self.js("document.querySelectorAll('#effectivenessLabResult img,#effectivenessLabResult svg').length"), 0)
        self.assertIn("không phải dự đoán tương lai đã khóa", self.js("document.getElementById('effectivenessLabResult').textContent"))
        self.assertIn("Điểm kiểm tra không dùng để chọn lại", self.js("document.querySelector('.effectiveness-lab-selection').textContent"))
        self.assertIn("Lịch sử ban đầu", self.js("document.querySelector('.effectiveness-lab-split').textContent"))
        self.assertNotIn("Huấn luyện", self.js("document.querySelector('.effectiveness-lab-split').textContent"))
        self.assertIn("Không có champion khi bắt đầu", self.js("document.querySelector('.effectiveness-lab-detail .effectiveness-info-list').textContent"))
        self.assertIn("chỉ dùng lịch sử trước kỳ mục tiêu", self.js("document.querySelector('.effectiveness-lab-detail .effectiveness-info-list').textContent"))
        self.assertEqual(self.js("document.querySelector('.effectiveness-summary .effectiveness-metric strong').textContent"), "2")
        self.assertEqual(self.js("document.querySelectorAll('#effectivenessCycles .effectiveness-cycle').length"), 0)
        for light in (False, True):
            self.js(f"document.body.classList.toggle('light-theme',{str(light).lower()});document.querySelector('.effectiveness-lab-detail').open=true")
            for width in (320, 390, 1440):
                self.browser.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": width < 500}, page=True)
                self.assertTrue(self.js("document.documentElement.scrollWidth<=window.innerWidth+2"), f"Lab overflows at {width}px, light={light}")
                self.assertTrue(self.js("Array.from(document.querySelectorAll('.effectiveness-lab-controls input')).every(input=>input.getBoundingClientRect().width<=input.parentElement.getBoundingClientRect().width+1)"))
        self.js("document.getElementById('effectivenessLabRun').click()")
        self.wait("!document.getElementById('effectivenessLabCancel').hidden")
        self.js("document.getElementById('effectivenessLabCancel').click()")
        self.wait("document.getElementById('effectivenessLabStatus').textContent.includes('Đã hủy lượt thử')")
        self.assertEqual(self.requests[-1][2]["action"], "cancel")
        self.assertEqual(self.requests[-1][2]["jobId"], "2")
        self.error = (503, "<img src=x> Không đủ dữ liệu lịch sử.")
        self.js("document.getElementById('effectivenessLabRun').click()")
        self.wait("document.getElementById('effectivenessLabStatus').textContent.includes('Không đủ dữ liệu')")
        self.assertEqual(self.js("document.querySelectorAll('#effectivenessLabStatus img').length"), 0)
        self.assertFalse(self.js("document.getElementById('effectivenessLabRun').disabled"))
        self.error = None
        self.jobs[(self.owner, "LOTO_5_35")].update(state="failed", error="Thiếu snapshot.")
        self.js("document.getElementById('effectivenessLab').open=false")
        self.open_lab()
        self.wait("document.getElementById('effectivenessLabStatus').textContent==='Thiếu snapshot.'")
        self.assertEqual(self.js("document.getElementById('effectivenessLabResult').textContent"), "")
        self.owner = "member"
        self.can_manage = False
        self.js("window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:true,user:'member'}}))")
        self.wait("document.getElementById('effectivenessStatus').textContent==='Báo cáo đã cập nhật.'")
        self.open_lab()
        self.wait("document.getElementById('effectivenessLabStatus').textContent.includes('chưa có lượt thử')")
        self.assertTrue(self.js("document.getElementById('effectivenessLabAdmin').hidden"))
        post_count = len([item for item in self.requests if item[0] == "POST"])
        self.js("document.getElementById('effectivenessLabRun').click();document.getElementById('effectivenessLabCancel').click()")
        time.sleep(.15)
        self.assertEqual(post_count, len([item for item in self.requests if item[0] == "POST"]))
        self.assertEqual(self.js("uiErrors"), [])

    def test_polling_pauses_and_stale_game_account_responses_are_discarded(self):
        self.jobs[(self.owner, "LOTO_5_35")] = {"id": 5, "type": "LOTO_5_35", "state": "running", "validationCount": 10, "testCount": 20}
        self.open_lab()
        self.wait("document.getElementById('effectivenessLabStatus').textContent.includes('Đang chạy thử')")
        self.js("document.getElementById('effectivenessLab').open=false")
        time.sleep(.15)
        count = len(self.lab_gets())
        time.sleep(2.2)
        self.assertEqual(len(self.lab_gets()), count)
        self.open_lab()
        self.wait("!document.getElementById('effectivenessLabCancel').hidden")
        self.js("VietlottEffectiveness.activate(false)")
        time.sleep(.15)
        count = len(self.lab_gets())
        time.sleep(2.2)
        self.assertEqual(len(self.lab_gets()), count)
        self.js("VietlottEffectiveness.activate(true)")
        self.wait("!document.getElementById('effectivenessLabCancel').disabled")
        self.js("Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))")
        time.sleep(.15)
        count = len(self.lab_gets())
        time.sleep(2.2)
        self.assertEqual(len(self.lab_gets()), count)
        self.js("Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'))")
        self.wait("!document.getElementById('effectivenessLabCancel').disabled")
        self.js("document.getElementById('effectivenessLab').open=false;window.ignoreAbort=true")
        self.jobs[(self.owner, "LOTO_5_35")].update(state="completed", report=lab_report(label="PRIVATE_OLD_GAME"))
        entered, release = self.hold_next("GET")
        self.open_lab()
        self.assertTrue(entered.wait(4))
        self.js("document.getElementById('effectivenessType').value='LOTO_6_55';document.getElementById('effectivenessType').dispatchEvent(new Event('change'))")
        self.wait("document.getElementById('effectivenessLabStatus').textContent.includes('chưa có lượt thử')")
        release.set()
        time.sleep(.2)
        self.assertNotIn("PRIVATE_OLD_GAME", self.js("document.getElementById('effectivenessLab').textContent"))
        self.assertEqual(self.js("document.getElementById('effectivenessLabResult').textContent"), "")
        entered, release = self.hold_next("POST")
        self.js("document.getElementById('effectivenessLabRun').click()")
        self.assertTrue(entered.wait(4))
        self.owner = "second"
        self.can_manage = False
        self.js("window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:true,user:'second'}}))")
        self.wait("document.getElementById('effectivenessStatus').textContent==='Báo cáo đã cập nhật.'")
        self.open_lab()
        self.wait("document.getElementById('effectivenessLabStatus').textContent.includes('chưa có lượt thử')")
        release.set()
        time.sleep(.2)
        self.assertTrue(self.js("document.getElementById('effectivenessLabAdmin').hidden"))
        self.assertTrue(self.js("document.getElementById('effectivenessLabCancel').hidden"))
        self.assertEqual(self.js("document.getElementById('effectivenessLabResult').textContent"), "")
        self.jobs[(self.owner, "LOTO_6_55")] = {"id": 9, "type": "LOTO_6_55", "state": "completed", "report": lab_report("LOTO_5_35", "WRONG_REPORT_TYPE")}
        self.js("document.getElementById('effectivenessLab').open=false")
        self.open_lab()
        self.wait("document.getElementById('effectivenessLabStatus').dataset.kind==='error'")
        self.assertNotIn("WRONG_REPORT_TYPE", self.js("document.getElementById('effectivenessLabResult').textContent"))
        self.error = (401, "Session expired")
        self.js("document.getElementById('effectivenessLab').open=false")
        self.open_lab()
        self.wait("document.getElementById('effectivenessStatus').textContent.includes('hết hạn')")
        self.assertTrue(self.js("document.getElementById('effectivenessLabAdmin').hidden"))
        self.assertEqual(self.js("document.getElementById('effectivenessSummary').textContent"), "")
        self.assertEqual(self.js("document.getElementById('effectivenessLabResult').textContent"), "")
        self.assertTrue(self.js("document.getElementById('effectivenessRefresh').disabled"))
        self.assertEqual(self.js("uiErrors"), [])


if __name__ == "__main__":
    unittest.main()
