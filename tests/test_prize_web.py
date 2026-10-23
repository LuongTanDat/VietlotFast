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
                for ky in (1, 2, 3):
                    row = {field: "" for field in lr.CSV_FIELDS}
                    row.update(Ky=str(ky), Ngay="01/10/2026", Main="1,2,3,4,5,6", Label=lr.LIVE_TYPES[key].label)
                    if key.startswith("MAX"):
                        row.update(Main="", DisplayLines="Đặc biệt: 000 000 || Giải nhất: 001 002 003 004 || Giải nhì: 005 006 007 008 009 010 || Giải ba: 011 012 013 014 015 016 017 018")
                    row.update({field: str(178900548500 + index) if ky == 2 else "" for index, field in enumerate(fields)})
                    row["PrizeHit"] = {"LOTO_5_35": "ĐB", "LOTO_6_45": "Jackpot", "LOTO_6_55": "Jackpot 1, 2"}.get(key, "") if ky == 2 else ""
                    if key == "LOTO_5_35" and ky == 3:
                        row["PrizeHit"] = "Chia Giải"
                    rows[str(ky)] = row
                lr.write_csv_rows(canonical / f"{lr.CANONICAL_OUTPUT_STEMS[key]}_all_day.csv", rows, type_key=key)
                expected[key] = [lr.csv_row_to_history_item(rows[str(ky)]) for ky in (3, 2, 1)]
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
                self.assertEqual(3, len(payload["history"]))
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
        for name in ("emptyLiveHistoryFeed", "getDrawPrizeAmount", "getDrawPrizeFields", "getDrawPrizeHit", "formatDrawPrizeAmount", "formatDrawPrizes", "cloneDraw", "kySortValue", "normalizeLiveHistoryKy", "mergeLiveHistoryDraw", "normalizeLiveHistoryRepairErrors", "buildLiveHistoryFeedFromResponse", "getDataTableHeaders", "isDataTableDrawInPrizeFilter", "getDataTableMatchingKeys", "getDataTableSelectedKeys", "buildDataTableRows", "renderDataTableRows", "renderLiveResultsBoard", "getExcelColumnName", "buildXlsxSheetXml"):
            code += js_function(source, name) + "\n"
        code += js_function(core, "getLiveResultSignature")
        code += js_function(core, "formatCompactBalance")
        for name in ("parseDataTableDateParts", "normalizeDataTableFilterNumber", "normalizeDataTableWeekdayFilter", "getDataTableDateFilters", "hasDataTableDateFilter", "isDataTableDrawInDateFilter", "setDataTableFilterSelectValue", "syncDataTableDateFilterControls", "resetDataTableDateFilters", "getDataTablePrimaryPrizeFilterLabel", "getDataTableActivePrizeFilters", "getDataTablePrizeFilterFileSuffix", "syncDataTableHitFilterControl"):
            code += js_function(source, name) + "\n"
        bindings_start = core.index('    {\n      const dataTableHitFilterBtn =')
        bindings_end = core.index('    {\n      const dataTableRefreshBtn =', bindings_start)
        code += core[bindings_start:bindings_end]
        script = '''
const TYPES = {LOTO_5_35: {hasSpecial:true}, LOTO_6_45:{}, LOTO_6_55:{hasSpecial:true}, KENO:{}};
const LIVE_HISTORY_TYPES = Object.keys(TYPES).map(key => ({key,label:key}));
const LIVE_RESULT_TYPES = LIVE_HISTORY_TYPES;
const liveSingleRefreshBusy = new Set();
const IS_LOCAL_MODE = false;
let currentUser = null;
let liveResultsState = {};
let dataTableSelectedType = 'LOTO_5_35';
let dataTableHitOnly = false;
let dataTableShareOnly = false;
let dataTableJackpotMode = 'both';
let dataTableDateFilters = {weekday:'all',day:'all',month:'all',year:'all'};
let tableLoadCalls = 0;
async function loadDataTableRows() { tableLoadCalls++; }
const normalizeKy = ky => String(ky);
const formatLiveKy = ky => String(ky);
const escapeHtml = value => String(value).replaceAll('&','&amp;').replaceAll('<','&lt;');
const escapeXml = escapeHtml;
const formatDataTableWeekday = () => 'Thứ 5';
const getDataTableLimitValue = () => 'all';
const formatDataTableNumbers = (type,draw) => ({numbers:draw.main.join(' '),special:draw.special ?? ''});
const getSyncedNowDate = () => new Date('2026-10-03T14:00:00Z');
const getLiveResultsBoardSignature = () => JSON.stringify(liveResultsState);
const getLiveUpdateBadge = () => ({});
const liveUpdateBadgeClass = () => '';
const buildUpcomingLiveMetaParts = () => [];
const buildLiveResultMetaParts = (type,item) => ['Kỳ #'+item.ky,item.date,item.time].filter(Boolean);
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
      const moneyStart = headers.length - columns.length - DRAW_WINNER_COLUMNS[type].length - 1;
      check(rows[0][moneyStart+index] === money[key],'export lost amount');
      check(rows[1][moneyStart+index] === '','missing export must be blank');
      check(getLiveResultSignature(row) !== getLiveResultSignature({...row,[key]:money[key]+1}),'amount refresh missed');
    });
    renderDataTableRows(type,feed,{});
    check(document.querySelector('#dataTableBody .data-table-prize').textContent === '178,9T','compact table money formatting');
    check(document.querySelector('#dataTableBody .data-table-prize').title.includes('178.900.548.500'),'full table money tooltip');
    check(document.querySelectorAll('#dataTableBody tr')[1].querySelector('.data-table-prize').textContent === '—','missing table money');
    check(document.querySelectorAll('#dataTableBody tr')[1].querySelector('.data-table-prize').title === 'Chưa công bố giá trị giải','missing money explanation');
    const rendered = document.querySelectorAll('#dataTableBody tr');
    check(rendered[0].lastElementChild.textContent === marker, 'hit table cell');
    check(rendered[1].lastElementChild.textContent === '', 'nonhit table cell must be empty');
    check(!document.getElementById('dataTableBody').textContent.includes('NaN'),'hit incorrectly formatted as money');
    check(formatDrawPrizes(type,row).includes('178.900.548.500 VNĐ'),'history money formatting');
    const xml = buildXlsxSheetXml(headers,rows);
    check(xml.includes(`<autoFilter ref="A1:${getExcelColumnName(headers.length)}${rows.length+1}"/>`),'Excel filters must cover all data columns and rows');
    check(xml.includes('state="frozen"'),'Excel header remains frozen');
    check(xml.includes('t="n" s="1"><v>178900548500</v>'),'Excel money must be numeric');
    check(xml.includes('>Nổ</t>') && xml.includes('>'+marker+'</t>'),'Excel lost hit column');
    liveResultsState[type] = {...row,key:type};
  }
  renderLiveResultsBoard({force:true});
  check(document.querySelectorAll('.live-card-amount').length === 4,'three games must have four prize values');
  for (const amount of ['6.000.000.000 VNĐ','12.000.000.000 VNĐ','30.000.000.000 VNĐ','3.000.000.000 VNĐ']) check(document.getElementById('liveResultGrid').textContent.includes(amount),'upcoming won pool resets to starting value');
  check(liveResultsState.LOTO_6_45.jackpot===178900548500,'reset must not rewrite historical amount');
  check(!getDrawPrizeFields('KENO',{jackpot:100}).jackpot,'unrelated game prize');
  check(!getDataTableHeaders('KENO').includes('Nổ') && !getDataTableHeaders('MAX_3D').includes('Nổ'),'unrelated game hit column');
  for (const marker of ['ĐB','Chia Giải','']) {
    const feed = buildLiveHistoryFeedFromResponse('LOTO_5_35',[{ky:'3',date:'01/10/2026',time:'21:00',main:[1,2,3,4,5],special:10,specialPrize:12000000000,prizeHit:marker}]);
    renderDataTableRows('LOTO_5_35',feed,{});
    check(document.querySelector('#dataTableBody tr').lastElementChild.textContent === marker,'Lotto sharing marker rendering');
    const xml = buildXlsxSheetXml(getDataTableHeaders('LOTO_5_35'),buildDataTableRows('LOTO_5_35',feed,'all',{}));
    if (marker) check(xml.includes('>'+marker+'</t>'),'Excel lost Lotto sharing marker');
  }
  for (const marker of ['Jackpot 1','Jackpot 2','Jackpot 1, 2','']) {
    const feed = buildLiveHistoryFeedFromResponse('LOTO_6_55',[{ky:'3',date:'01/10/2026',main:[1,2,3,4,5,6],prizeHit:marker}]);
    renderDataTableRows('LOTO_6_55',feed,{});
    check(document.querySelector('#dataTableBody tr').lastElementChild.textContent === marker,'Power marker rendering');
  }
  const hitButton = document.getElementById('dataTableHitFilterBtn');
  const shareButton = document.getElementById('dataTableShareFilterBtn');
  const clearButton = document.getElementById('dataTableClearFilterBtn');
  const allDates = {weekday:'all',day:'all',month:'all',year:'all'};
  for (const type of ['LOTO_5_35','LOTO_6_45']) {
    dataTableSelectedType = type;
    dataTableHitOnly = false;
    dataTableShareOnly = false;
    dataTableJackpotMode = 'both';
    syncDataTableHitFilterControl();
    const expectedLabel = type === 'LOTO_5_35' ? 'Nổ' : 'Jackpot';
    check(!hitButton.hidden && !hitButton.disabled && hitButton.textContent === expectedLabel,'game-specific primary filter');
    check(shareButton.hidden === (type !== 'LOTO_5_35'),'sharing only visible for 5/35');
    const marker = type === 'LOTO_5_35' ? 'ĐB' : 'Jackpot';
    const hitFeed = buildLiveHistoryFeedFromResponse(type,[
      {ky:'9',date:'03/10/2026',main:[1,2,3,4,5,6],prizeHit:''},
      {ky:'8',date:'01/10/2026',main:[1,2,3,4,5,6],prizeHit:marker},
      {ky:'1',date:'01/10/2026',main:[1,2,3,4,5,6],prizeHit:'   '},
    ]);
    hitButton.click();
    check(dataTableHitOnly && hitButton.getAttribute('aria-pressed') === 'true','click activates hit toggle');
    const filteredRows = buildDataTableRows(type,hitFeed,'all',allDates);
    check(filteredRows.length === 1 && filteredRows[0].at(-1) === marker,'primary filter selects exact marker');
    check(buildDataTableRows(type,hitFeed,'1',allDates)[0][0] === '8','filter hits before row limit');
    const october = {...allDates,month:'10',year:'2026',weekday:'4'};
    check(buildDataTableRows(type,hitFeed,'all',october).length === 1,'combine hit and date filters');
    const xml = buildXlsxSheetXml(getDataTableHeaders(type),filteredRows);
    check((xml.match(/<row r=/g) || []).length === 2,'Excel includes only filtered row');
    renderDataTableRows(type,hitFeed,{...allDates,year:'2025'});
    check(document.getElementById('dataTableBody').textContent.includes('Không có kỳ'),'empty prize filter message');
    hitButton.click();
    check(!dataTableHitOnly && buildDataTableRows(type,hitFeed,'all',allDates).length === 3,'click restores all rows');
  }

  dataTableSelectedType = 'LOTO_6_55';
  dataTableHitOnly = false;
  dataTableShareOnly = false;
  dataTableJackpotMode = 'both';
  syncDataTableHitFilterControl();
  check(!hitButton.hidden && shareButton.hidden && hitButton.textContent === 'Jackpot 1, 2' && hitButton.classList.contains('is-cycle'),'Power uses one cycling button');
  const powerFeed = buildLiveHistoryFeedFromResponse('LOTO_6_55',[
    ['9',''],['8','Jackpot 1, 2'],['7','Jackpot 1'],['6','Jackpot 2']
  ].map(([ky,prizeHit]) => ({ky,date:'01/10/2026',main:[1,2,3,4,5,6],prizeHit})));
  const powerMarkers = () => buildDataTableRows('LOTO_6_55',powerFeed,'all',allDates).map(row => row.at(-1)).join('|');
  hitButton.click();
  check(dataTableHitOnly && dataTableJackpotMode === 'both' && powerMarkers() === 'Jackpot 1, 2','Power first state filters joint Jackpot marker');
  hitButton.click();
  check(dataTableJackpotMode === 'jackpot1' && hitButton.textContent === 'Jackpot 1' && powerMarkers() === 'Jackpot 1','Power second state filters Jackpot 1');
  hitButton.click();
  check(dataTableJackpotMode === 'jackpot2' && hitButton.textContent === 'Jackpot 2' && powerMarkers() === 'Jackpot 2','Power third state filters Jackpot 2');
  hitButton.click();
  check(!dataTableHitOnly && dataTableJackpotMode === 'both' && hitButton.textContent === 'Jackpot 1, 2' && hitButton.getAttribute('aria-pressed') === 'false','Power fourth click returns to initial state');
  check(buildDataTableRows('LOTO_6_55',powerFeed,'all',allDates).length === 4,'Power initial state restores all rows');
  check(getDataTablePrizeFilterFileSuffix('LOTO_6_55') === '','Power initial state removes Excel suffix');
  document.getElementById('dataTableMonth').value = '10';
  getDataTableDateFilters();
  clearButton.click();
  check(!dataTableHitOnly && dataTableJackpotMode === 'both' && !hasDataTableDateFilter() && hitButton.getAttribute('aria-pressed') === 'false','clear resets Power and date filters');
  for (const type of ['KENO','MAX_3D','MAX_3D_PRO']) {
    dataTableHitOnly = true;
    syncDataTableHitFilterControl(type);
    check(!dataTableHitOnly && hitButton.hidden && shareButton.hidden && document.querySelector('.data-table-prize-filters').hidden,'unsupported game hides prize filters');
    hitButton.click();
    check(!dataTableHitOnly,'disabled button cannot filter');
  }
  check(buildXlsxSheetXml(['Header'],[]).includes('<autoFilter ref="A1:A1"/>'),'empty sheet has a valid header filter');
  check(buildXlsxSheetXml(Array.from({length:28},(_,i)=>String(i)),[Array(28).fill(0),Array(28).fill(1)]).includes('<autoFilter ref="A1:AB3"/>'),'wide sheet filter includes columns after Z');
  dataTableSelectedType = 'LOTO_5_35';
  dataTableHitOnly = false;
  dataTableShareOnly = false;
  syncDataTableHitFilterControl();
  check(!shareButton.disabled && shareButton.getAttribute('aria-pressed') === 'false','sharing filter available for Lotto');
  const prizeFeed = buildLiveHistoryFeedFromResponse('LOTO_5_35',[
    ['12','','01/10/2026'],['11','ĐB','01/10/2026'],['10','Chia Giải','01/09/2026'],
    ['9','Chia Giải','01/10/2026'],['8','ĐB','01/09/2026'],['7','','01/10/2026']
  ].map(([ky,prizeHit,date]) => ({ky,prizeHit,date,main:[1,2,3,4,5],special:10,specialPrize:12000000000})));
  const allPrizeDates = {weekday:'all',day:'all',month:'all',year:'all'};
  const selectedPrizes = (limit='all',filters=allPrizeDates) => buildDataTableRows('LOTO_5_35',prizeFeed,limit,filters);
  const selectedIds = () => selectedPrizes().map(row => row[0]).join(',');
  check(selectedIds() === '12,11,10,9,8,7','no prize filters shows every draw');
  hitButton.click();
  check(selectedIds() === '11,8','Nổ excludes shared and blank draws');
  shareButton.click();
  check(dataTableHitOnly && dataTableShareOnly && selectedIds() === '11,10,9,8','both filters form a union without duplicates');
  check(hitButton.getAttribute('aria-pressed') === 'true' && shareButton.getAttribute('aria-pressed') === 'true','both toggles stay active');
  hitButton.click();
  check(selectedIds() === '10,9','Chia giải alone excludes hits and blanks');
  check(selectedPrizes('1')[0][0] === '10','share filter runs before row limit');
  check(selectedPrizes('all',{...allPrizeDates,month:'10',year:'2026'})[0][0] === '9','share filter combines with date filter');
  const sharedXml = buildXlsxSheetXml(getDataTableHeaders('LOTO_5_35'),selectedPrizes());
  check((sharedXml.match(/<row r=/g)||[]).length === 3 && sharedXml.includes('>Chia Giải</t>') && !sharedXml.includes('>ĐB</t></is></c></row>'),'Excel contains only sharing rows');
  renderDataTableRows('LOTO_5_35',prizeFeed,{...allPrizeDates,year:'2025'});
  check(document.getElementById('dataTableBody').textContent.includes('Không có kỳ chia giải'),'sharing empty state');
  hitButton.click();
  const bothXml = buildXlsxSheetXml(getDataTableHeaders('LOTO_5_35'),selectedPrizes());
  check((bothXml.match(/<row r=/g)||[]).length === 5 && bothXml.includes('>ĐB</t>') && bothXml.includes('>Chia Giải</t>'),'Excel exports both groups');
  shareButton.click();
  check(selectedIds() === '11,8','turning off sharing retains Nổ');
  hitButton.click();
  check(selectedPrizes().length === 6,'turning off both restores every draw');
  shareButton.click();
  hitButton.click();
  document.getElementById('dataTableMonth').value = '10';
  getDataTableDateFilters();
  clearButton.click();
  check(!dataTableHitOnly && !dataTableShareOnly && !hasDataTableDateFilter() && selectedPrizes().length === 6,'clear resets both prize filters and dates');
  check(hitButton.getAttribute('aria-pressed') === 'false' && shareButton.getAttribute('aria-pressed') === 'false','clear resets both button states');
  for (const type of ['LOTO_6_45','LOTO_6_55','KENO','MAX_3D','MAX_3D_PRO']) {
    dataTableSelectedType = type;
    dataTableHitOnly = true;
    dataTableShareOnly = true;
    dataTableJackpotMode = 'both';
    syncDataTableHitFilterControl();
    check(!dataTableShareOnly && shareButton.hidden && shareButton.disabled && shareButton.getAttribute('aria-pressed') === 'false','Chia giải is hidden outside 5/35');
    const beforeCalls = tableLoadCalls;
    shareButton.click();
    check(!dataTableShareOnly && tableLoadCalls === beforeCalls,'unsupported sharing cannot load or filter');
    check(dataTableHitOnly === !!DRAW_PRIZE_COLUMNS[type]?.length,'Mega/Power hit filter remains supported');
    if (type === 'LOTO_6_45') check(!hitButton.hidden && hitButton.textContent === 'Jackpot','Mega shows Jackpot button');
    if (type === 'LOTO_6_55') check(!hitButton.hidden && hitButton.textContent === 'Jackpot 1, 2','Power shows joint Jackpot state');
    if (!DRAW_PRIZE_COLUMNS[type]?.length) check(hitButton.hidden,'other games hide primary prize button');
  }
  for (const value of [null,'',0,-1,'bad',Number.MAX_SAFE_INTEGER+1]) check(getDrawPrizeAmount({jackpot:value},'jackpot') === null,'invalid money');
  document.getElementById('result').textContent = 'PASS';
} catch(error) { document.getElementById('result').textContent = 'FAIL: '+error.stack; }
'''
        with tempfile.TemporaryDirectory(prefix="lotto-prize-browser-", dir=TEST_TMP) as folder:
            work = Path(folder)
            page = work / "test.html"
            page.write_text('<!doctype html><meta charset="utf-8"><div class="data-table-prize-filters"><button id="dataTableHitFilterBtn" aria-pressed="false">Nổ</button><button id="dataTableShareFilterBtn" aria-pressed="false">Chia giải</button></div><button id="dataTableClearFilterBtn">Xóa lọc</button><select id="dataTableMonth"><option value="all">Tất Cả</option><option value="10">10</option></select><table><thead id="dataTableHead"></thead><tbody id="dataTableBody"></tbody></table><div id="liveResultGrid"></div><pre id="result">PENDING</pre><script>' + script + '</script>', encoding="utf-8")
            output = subprocess.run([CHROME,"--headless","--disable-gpu","--no-sandbox","--no-first-run","--no-default-browser-check","--user-data-dir="+str(work / "profile"),"--dump-dom",page.as_uri()], capture_output=True, timeout=30, creationflags=0x08000000 if os.name == "nt" else 0)
            dom = output.stdout.decode("utf-8", errors="replace")
            result = re.search(r'<pre id="result">(.*?)</pre>', dom, re.DOTALL)
            self.assertEqual("PASS", result.group(1) if result else output.stderr.decode("utf-8", errors="replace")[-1500:])


if __name__ == "__main__":
    unittest.main()
