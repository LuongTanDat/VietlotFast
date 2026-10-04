"""Exercise prize serialization and the actual UI functions with isolated fixtures."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import backend.live_results as lr

ROOT = Path(__file__).resolve().parents[1]
JAVA_HOME = Path(os.environ.get("JAVA_HOME", "C:/java-1.8.0-openjdk-1.8.0.392-1.b08.redhat.windows.x86_64"))
JAVAC = shutil.which("javac") or str(JAVA_HOME / "bin/javac.exe")
JAVA = str(Path(JAVAC).with_name("java.exe")) if os.name == "nt" else shutil.which("java")
CHROME = os.environ.get("LOTTO_TEST_CHROME") or shutil.which("google-chrome") or "C:/Program Files/Google/Chrome/Application/chrome.exe"
TEST_TMP = ROOT / "runtime/logs"
TEST_TMP.mkdir(parents=True, exist_ok=True)


def js_function(source, name):
    start = source.index(f"    function {name}(")
    end = re.search(r"^    }", source[start:], re.MULTILINE).end() + start
    return source[start:end]


class PrizeWebTests(unittest.TestCase):
    @unittest.skipUnless(Path(JAVAC).exists(), "JDK required")
    def test_java_history_matches_python_with_large_and_missing_amounts(self):
        with tempfile.TemporaryDirectory(prefix="lotto-prize-java-", dir=TEST_TMP) as folder:
            work = Path(folder)
            canonical = work / "data/canonical"
            canonical.mkdir(parents=True)
            (work / "runtime").mkdir()
            shutil.copy2(ROOT / "backend/lib/sqlite-jdbc-3.51.2.0.jar", work / "sqlite-jdbc.jar")
            expected = {}
            for key in (*lr.PRIZE_FIELDS_BY_TYPE, "MAX_3D", "MAX_3D_PRO"):
                fields = lr.PRIZE_FIELDS_BY_TYPE.get(key, ())
                rows = {}
                for ky in (1, 2):
                    row = {field: "" for field in lr.CSV_FIELDS}
                    row.update(Ky=str(ky), Ngay="01/10/2026", Main="1,2,3,4,5,6", Label=lr.LIVE_TYPES[key].label)
                    if key.startswith("MAX"):
                        row.update(Main="", DisplayLines="Đặc biệt: 000 000 || Giải nhất: 001 002 003 004 || Giải nhì: 005 006 007 008 009 010 || Giải ba: 011 012 013 014 015 016 017 018")
                    row.update({field: str(178900548500 + index) if ky == 2 else "" for index, field in enumerate(fields)})
                    row["PrizeHit"] = {"LOTO_5_35": "ĐB", "LOTO_6_45": "Jackpot", "LOTO_6_55": "Jackpot 1, 2"}.get(key, "") if ky == 2 else ""
                    rows[str(ky)] = row
                lr.write_csv_rows(canonical / f"{lr.CANONICAL_OUTPUT_STEMS[key]}_all_day.csv", rows, type_key=key)
                expected[key] = [lr.csv_row_to_history_item(rows[str(ky)]) for ky in (2, 1)]
            harness = work / "PrizeHistoryHarness.java"
            harness.write_text('''import java.lang.reflect.Method;
import java.util.Collections;
import java.util.Set;
public class PrizeHistoryHarness {
  public static void main(String[] args) throws Exception {
    LottoWebServer server = new LottoWebServer();
    Method history = LottoWebServer.class.getDeclaredMethod("buildCanonicalHistoryPayload", String.class, String.class, Set.class);
    history.setAccessible(true);
    for (String type : args) System.out.println(history.invoke(server, type, "all", Collections.emptySet()));
  }
}''', encoding="utf-8")
            compilation = subprocess.run([JAVAC, "-encoding", "UTF-8", "-d", str(work.relative_to(ROOT)), "backend/LottoWebServer.java", str(harness.relative_to(ROOT))], cwd=ROOT, capture_output=True)
            self.assertEqual(0, compilation.returncode, compilation.stderr.decode("utf-8", errors="replace"))
            execution = subprocess.run([JAVA, "-Dfile.encoding=UTF-8", "-cp", "." + os.pathsep + "sqlite-jdbc.jar", "PrizeHistoryHarness", *expected], cwd=work, capture_output=True)
            self.assertEqual(0, execution.returncode, execution.stderr.decode("utf-8", errors="replace"))
            output = execution.stdout.decode("utf-8")
            for line in output.splitlines():
                payload = json.loads(line)
                key = payload["type"]
                self.assertEqual(2, len(payload["history"]))
                for actual, wanted in zip(payload["history"], expected[key]):
                    for field in ("ky", "main", "date", "special", "displayLines", "label", "prizeHit", *[lr.PRIZE_RESULT_KEYS[f] for f in lr.PRIZE_FIELDS_BY_TYPE.get(key, ())]):
                        self.assertEqual(wanted.get(field), actual.get(field))

    @unittest.skipUnless(Path(CHROME).exists(), "Chrome required")
    def test_browser_history_table_cards_refresh_and_excel(self):
        source = (ROOT / "frontend/vietlott-web-data.js").read_text(encoding="utf-8")
        core = (ROOT / "frontend/vietlott-web-core.js").read_text(encoding="utf-8")
        columns_start = source.index("    const DRAW_PRIZE_COLUMNS")
        columns_end = source.index("    function getDrawPrizeAmount", columns_start)
        code = source[columns_start:columns_end]
        for name in ("emptyLiveHistoryFeed", "getDrawPrizeAmount", "getDrawPrizeFields", "getDrawPrizeHit", "formatDrawPrizeAmount", "formatDrawPrizes", "cloneDraw", "kySortValue", "normalizeLiveHistoryKy", "mergeLiveHistoryDraw", "normalizeLiveHistoryRepairErrors", "buildLiveHistoryFeedFromResponse", "getDataTableHeaders", "getDataTableMatchingKeys", "getDataTableSelectedKeys", "buildDataTableRows", "renderDataTableRows", "renderLiveResultsBoard", "getExcelColumnName", "buildXlsxSheetXml"):
            code += js_function(source, name) + "\n"
        code += js_function(core, "getLiveResultSignature")
        script = '''
const TYPES = {LOTO_5_35: {hasSpecial:true}, LOTO_6_45:{}, LOTO_6_55:{hasSpecial:true}, KENO:{}};
const LIVE_HISTORY_TYPES = Object.keys(TYPES).map(key => ({key,label:key}));
const LIVE_RESULT_TYPES = LIVE_HISTORY_TYPES;
const liveSingleRefreshBusy = new Set();
let liveResultsState = {};
const normalizeKy = ky => String(ky);
const formatLiveKy = ky => String(ky);
const escapeHtml = value => String(value).replaceAll('&','&amp;').replaceAll('<','&lt;');
const escapeXml = escapeHtml;
const formatDataTableWeekday = () => 'Thứ 5';
const getDataTableLimitValue = () => 'all';
const getDataTableDateFilters = () => ({});
const isDataTableDrawInDateFilter = () => true;
const formatDataTableNumbers = (type,draw) => ({numbers:draw.main.join(' '),special:draw.special ?? ''});
const getSyncedNowDate = () => new Date('2026-10-03T14:00:00Z');
const getLiveResultsBoardSignature = () => JSON.stringify(liveResultsState);
const getLiveUpdateBadge = () => ({});
const liveUpdateBadgeClass = () => '';
const buildUpcomingLiveMetaParts = () => [];
const renderLiveCardMainLines = () => '<div>01 02 03 04 05 06</div>';
const updateLiveResultsCountdownText = () => {};
function check(value,message) { if (!value) throw new Error(message); }
''' + code + '''
try {
  for (const [type,columns] of Object.entries(DRAW_PRIZE_COLUMNS)) {
    const money = Object.fromEntries(columns.map(({key},index) => [key,178900548500+index]));
    const marker = {LOTO_5_35:'ĐB',LOTO_6_45:'Jackpot',LOTO_6_55:'Jackpot 1, 2'}[type];
    const row = {ky:'2',date:'01/10/2026',main:[1,2,3,4,5,6],special:10,prizeHit:marker,...money};
    const feed = buildLiveHistoryFeedFromResponse(type,[row,{...row,ky:'1',prizeHit:'',...Object.fromEntries(columns.map(({key}) => [key,null]))}]);
    const rows = buildDataTableRows(type,feed,'all',{});
    const headers = getDataTableHeaders(type);
    check(rows[0].length === headers.length,'header alignment');
    check(headers.at(-1) === 'Nổ','missing hit column');
    check(rows[0].at(-1) === marker && rows[1].at(-1) === '', 'hit must match source and nonhit must be blank');
    check(feed.results['2'].prizeHit === marker,'feed lost hit');
    check(getLiveResultSignature(row) !== getLiveResultSignature({...row,prizeHit:''}),'hit refresh missed');
    columns.forEach(({key},index) => {
      check(feed.results['2'][key] === money[key],'feed lost amount');
      check(rows[0][headers.length-columns.length-1+index] === money[key],'export lost amount');
      check(rows[1][headers.length-columns.length-1+index] === '','missing export must be blank');
      check(getLiveResultSignature(row) !== getLiveResultSignature({...row,[key]:money[key]+1}),'amount refresh missed');
    });
    renderDataTableRows(type,feed,{});
    check(document.getElementById('dataTableBody').textContent.includes('178.900.548.500'),'table money formatting');
    check(document.getElementById('dataTableBody').textContent.includes('Chưa có dữ liệu'),'missing table money');
    const rendered = document.querySelectorAll('#dataTableBody tr');
    check(rendered[0].lastElementChild.textContent === marker, 'hit table cell');
    check(rendered[1].lastElementChild.textContent === '', 'nonhit table cell must be empty');
    check(!document.getElementById('dataTableBody').textContent.includes('NaN'),'hit incorrectly formatted as money');
    check(formatDrawPrizes(type,row).includes('178.900.548.500 VNĐ'),'history money formatting');
    const xml = buildXlsxSheetXml(headers,rows);
    check(xml.includes('t="n" s="1"><v>178900548500</v>'),'Excel money must be numeric');
    check(xml.includes('>Nổ</t>') && xml.includes('>'+marker+'</t>'),'Excel lost hit column');
    liveResultsState[type] = {...row,key:type};
  }
  renderLiveResultsBoard({force:true});
  check(document.querySelectorAll('.live-card-amount').length === 4,'three games must have four prize values');
  check(document.getElementById('liveResultGrid').textContent.includes('178.900.548.500 VNĐ'),'live card amount');
  check(!getDrawPrizeFields('KENO',{jackpot:100}).jackpot,'unrelated game prize');
  check(!getDataTableHeaders('KENO').includes('Nổ') && !getDataTableHeaders('MAX_3D').includes('Nổ'),'unrelated game hit column');
  for (const marker of ['Jackpot 1','Jackpot 2','Jackpot 1, 2','']) {
    const feed = buildLiveHistoryFeedFromResponse('LOTO_6_55',[{ky:'3',date:'01/10/2026',main:[1,2,3,4,5,6],prizeHit:marker}]);
    renderDataTableRows('LOTO_6_55',feed,{});
    check(document.querySelector('#dataTableBody tr').lastElementChild.textContent === marker,'Power marker rendering');
  }
  for (const value of [null,'',0,-1,'bad',Number.MAX_SAFE_INTEGER+1]) check(getDrawPrizeAmount({jackpot:value},'jackpot') === null,'invalid money');
  document.getElementById('result').textContent = 'PASS';
} catch(error) { document.getElementById('result').textContent = 'FAIL: '+error.stack; }
'''
        with tempfile.TemporaryDirectory(prefix="lotto-prize-browser-", dir=TEST_TMP) as folder:
            work = Path(folder)
            page = work / "test.html"
            page.write_text('<!doctype html><meta charset="utf-8"><table><thead id="dataTableHead"></thead><tbody id="dataTableBody"></tbody></table><div id="liveResultGrid"></div><pre id="result">PENDING</pre><script>' + script + '</script>', encoding="utf-8")
            output = subprocess.run([CHROME,"--headless","--disable-gpu","--no-sandbox","--no-first-run","--no-default-browser-check","--user-data-dir="+str(work / "profile"),"--dump-dom",page.as_uri()], capture_output=True, timeout=30, creationflags=0x08000000 if os.name == "nt" else 0)
            dom = output.stdout.decode("utf-8", errors="replace")
            result = re.search(r'<pre id="result">(.*?)</pre>', dom, re.DOTALL)
            self.assertEqual("PASS", result.group(1) if result else output.stderr.decode("utf-8", errors="replace")[-1500:])


if __name__ == "__main__":
    unittest.main()
