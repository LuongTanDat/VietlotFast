"""Complete per-cycle export without changing locked forecasts or ledger scores."""
import json
import sqlite3
import unittest
import uuid
from contextlib import closing
from unittest import mock
from ai import prediction_effectiveness as pe
from tests.test_prediction_effectiveness import PredictionEffectivenessTests as NumericFixture
from tests.test_keno_effectiveness import KenoEffectivenessTests as KenoFixture

class NumericExcelTests(unittest.TestCase):
    GAME = NumericFixture.GAME
    setUp = NumericFixture.setUp
    _write = NumericFixture._write
    _web = NumericFixture._web
    _counts = NumericFixture._counts
    _actual = NumericFixture._actual

    def snapshot(self):
        with closing(sqlite3.connect(self.db)) as c:
            return list(c.iterdump())

    def test_complete_10000_pending_scored_and_immutable_export(self):
        pe.configure(self.GAME, True, 10000, 'admin_fixture', self.db)
        locked=pe.cycle(self.GAME,self.db)
        cycle=pe.report(self.GAME,db_path=self.db)['cycles'][0]
        before=self.snapshot()
        pending=pe.export_cycle(self.GAME,cycle['cycleId'],self.db)
        self.assertEqual(pending['status'],'locked')
        self.assertEqual(pending['actualMain'],[])
        self.assertEqual(set(pending['methods']),set(pe.METHODS))
        for key,entry in pending['methods'].items():
            self.assertEqual(entry['ticketCount'],10000)
            self.assertEqual(len(entry['tickets']),10000)
            self.assertEqual(len(entry['ticketResults']),10000)
            self.assertEqual(entry['ticketResults'][-1]['ticketIndex'],10000)
            self.assertEqual(entry['prizeCounts'],{'PENDING':10000})
        self.assertEqual(before,self.snapshot())
        self._actual();pe.score_cycles(self.GAME,self.db)
        before=self.snapshot()
        scored=pe.export_cycle(self.GAME,cycle['cycleId'],self.db)
        self.assertEqual(scored['status'],'scored')
        self.assertEqual(scored['actualMain'],[1,2,3,4,5])
        self.assertEqual(scored['actualSpecial'],2)
        for key,entry in scored['methods'].items():
            self.assertEqual(entry['tickets'],pending['methods'][key]['tickets'])
            self.assertEqual(sum(entry['prizeCounts'].values()),10000)
            last=pe.ticket_page(self.GAME,entry['predictionId'],1000,self.db)
            self.assertEqual(entry['ticketResults'][-10:],last['ticketResults'])
        self.csv.write_text('changed canonical',encoding='utf-8')
        self.assertEqual(scored,pe.export_cycle(self.GAME,cycle['cycleId'],self.db))
        self.assertEqual(before,self.snapshot())
        for game,identity,level in [('LOTO_6_45',cycle['cycleId'],10),(self.GAME,str(uuid.uuid4()),10),(self.GAME,'bad',10),(self.GAME,cycle['cycleId'],0),(self.GAME,cycle['cycleId'],True)]:
            with self.assertRaises(ValueError):pe.export_cycle(game,identity,self.db,level)
        with self.assertRaises(ValueError):pe.export_cycle(self.GAME,cycle['methods']['web']['predictionId'],self.db)

class KenoExcelTests(unittest.TestCase):
    setUp=KenoFixture.setUp
    row=staticmethod(KenoFixture.row)
    write=KenoFixture.write
    web=KenoFixture.web
    counts=KenoFixture.counts
    add_actual=KenoFixture.add_actual

    def test_selected_keno_level_pending_scored_and_read_only(self):
        from ai import keno_effectiveness as keno
        keno.cycle(self.db)
        cycle=keno.report(level=4,db_path=self.db)['cycles'][0]
        before=self.counts()
        for level in (1,4,10):
            data=pe.export_cycle('KENO',cycle['cycleId'],self.db,level)
            self.assertEqual(data['level'],level)
            self.assertEqual(data['status'],'locked')
            self.assertTrue(all(len(t['main'])==level for e in data['methods'].values()for t in e['tickets']))
        self.add_actual();keno.score_cycles(self.db)
        before=self.counts()
        data=pe.export_cycle('KENO',cycle['cycleId'],self.db,4)
        self.assertEqual(data['status'],'scored')
        self.assertEqual(len(data['actualMain']),20)
        self.assertIsNone(data['actualSpecial'])
        self.assertEqual(before,self.counts())



class ExcelBrowserTests(unittest.TestCase):
    def test_real_xlsx_complete_rows_controls_layout_error_and_logout(self):
        import base64, tempfile,threading,time,urllib.parse,zipfile
        import xml.etree.ElementTree as ET
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from pathlib import Path
        from tests.browser_cdp import Browser
        from tests.test_prize_web import ROOT,CHROME,js_function
        state={'error':False,'delay':0,'requests':[]}
        methods=['web','random','bayesian','ewma'];identity=str(uuid.uuid4())
        tickets=[{'main':[1,2,3,4,5],'special':2}for _ in range(10000)]
        tickets[-1]={'main':[6,7,8,9,10],'special':3}
        from ai.prizes import classify_tickets
        labels=classify_tickets('LOTO_5_35',tickets,{'main':[1,2,3,4,5],'special':2})
        cycle={'cycleId':identity,'targetDrawId':'947','cutoffDrawId':'946','createdAt':'2030-01-06T07:00:00Z','deadline':'2030-01-06T14:00:00Z','dataHash':'fixture','status':'scored','actualMain':[1,2,3,4,5],'actualSpecial':2,'config':{'ticketCount':10000},'methods':{key:{'predictionId':str(uuid.uuid4()),'ticketCount':10000,'tickets':tickets[:10],'ticketResults':labels[:10],'ticketPagination':{'page':1,'pageSize':10,'total':10000,'totalPages':1000,'offset':0}}for key in methods}}
        report={'ok':True,'type':'LOTO_5_35','label':'Lotto 5/35','canManage':False,'settings':{'enabled':False,'ticketCount':10000},'counts':{'scored':1,'locked':0,'total':1},'methods':[{'key':key,'sampleCount':1,'meanHits':1}for key in methods],'cycles':[cycle]}
        full={**cycle,'ok':True,'type':'LOTO_5_35','actualSource':'recorded_ledger_score','methods':{key:{**cycle['methods'][key],'tickets':tickets,'ticketResults':labels,'engine':'=1+1','modelId':'fixture','seed':123,'payloadChecksum':'fixture','prizeStatistics':{'winningTicketCount':9999}}for key in methods}}
        html=(ROOT/'frontend/vietlott-web.html').read_text(encoding='utf-8')
        section=html[html.index('      <section id="predictRootEffectiveness"'):html.index('      <section id="predictRootManual"')]
        source=(ROOT/'frontend/vietlott-web-data.js').read_text(encoding='utf-8')
        helpers = 'const getSyncedIsoString=()=>new Date().toISOString(); const escapeXml=v=>String(v??"").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll(String.fromCharCode(34),"&quot;").replaceAll(String.fromCharCode(39),"&apos;");' 
        for name in ['getExcelColumnName','buildXlsxSheetXml','buildXlsxWorkbookBlob','buildCrc32Table','crc32','pushUint16LE','pushUint32LE','pushBytes','buildZipBlob']:
            helpers+=js_function(source,name)+'\n'
        helpers+='const ZIP_CRC32_TABLE=buildCrc32Table();'
        page='<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><link rel=stylesheet href=/vietlott-web.css><link rel=stylesheet href=/vietlott-web-extra.css>'+section+'<script>window.browserErrors=[];window.addEventListener("error",e=>browserErrors.push(e.message));'+helpers+'</script><script src=/vietlott-web-numeric.js></script><script src=/vietlott-web-effectiveness.js></script>'
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if self.path.startswith('/api/ml/effectiveness-export?'):
                    state['requests'].append(self.path);time.sleep(state['delay'])
                    body=json.dumps({'ok':False,'message':'Export fixture error'}if state['error']else full).encode();status=503 if state['error']else 200;content='application/json'
                elif self.path.startswith('/api/ml/effectiveness?'):
                    body=json.dumps(report).encode();status=200;content='application/json'
                elif self.path=='/':body=page.encode();status=200;content='text/html;charset=utf-8'
                elif self.path.startswith('/vietlott-web'):
                    path=ROOT/'frontend'/self.path.split('?')[0].lstrip('/')
                    body=path.read_bytes();status=200;content='text/css'if path.suffix=='.css'else'application/javascript'
                else:body=b'{}';status=200;content='application/json'
                self.send_response(status);self.send_header('Content-Type',content);self.send_header('Content-Length',str(len(body)));self.end_headers()
                try:self.wfile.write(body)
                except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        threading.Thread(target=server.serve_forever,daemon=True).start()
        artifacts=ROOT/'Bin/session_1_latest/effectiveness_excel_images';artifacts.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='excel-browser-',dir=ROOT/'runtime')as folder:
            work=Path(folder);download=work/'downloads';download.mkdir()
            browser=Browser(CHROME,work/'profile')
            def wait(expression,timeout=15):
                deadline=time.monotonic()+timeout
                while time.monotonic()<deadline:
                    if browser.value(expression):return
                    time.sleep(.05)
                self.fail('Browser timeout: '+expression+' errors='+str(browser.value('window.browserErrors')))
            try:
                browser.call('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str(download)},page=False)
                browser.call('Page.navigate',{'url':f'http://127.0.0.1:{server.server_port}/'},page=True)
                wait('!!window.VietlottEffectiveness')
                browser.value('document.getElementById("predictRootEffectiveness").hidden=false;window.dispatchEvent(new CustomEvent("dvlf:auth-changed",{detail:{authenticated:true}}));VietlottEffectiveness.activate(true)')
                wait('!!document.querySelector("[data-cycle-export]")')
                self.assertFalse(browser.value('document.querySelector(".effectiveness-cycle").open'))
                browser.value('document.querySelector("[data-cycle-export] svg").dispatchEvent(new MouseEvent("click",{bubbles:true,cancelable:true}))')
                self.assertFalse(browser.value('document.querySelector(".effectiveness-cycle").open'))
                wait('document.getElementById("effectivenessStatus").textContent.startsWith("Đã tải Excel")',30)
                deadline=time.monotonic()+15
                while not list(download.glob('*.xlsx'))and time.monotonic()<deadline:time.sleep(.05)
                files=list(download.glob('*.xlsx'));self.assertEqual(len(files),1)
                self.assertEqual(files[0].name,'du_doan_thuc_te_loto_5_35_ky_947_ve_thuong.xlsx')
                ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                with zipfile.ZipFile(files[0])as book:
                    self.assertIsNone(book.testzip())
                    workbook=ET.fromstring(book.read('xl/workbook.xml'))
                    self.assertEqual([n.attrib['name']for n in workbook.findall('s:sheets/s:sheet',ns)],['Tổng quan','Pipeline web','Ngẫu nhiên','Bayesian','EWMA'])
                    for index in range(1,6):
                        sheet=ET.fromstring(book.read(f'xl/worksheets/sheet{index}.xml'))
                        self.assertEqual(sheet.find('s:autoFilter',ns).attrib['ref'],sheet.find('s:dimension',ns).attrib['ref'])
                        pane=sheet.find('s:sheetViews/s:sheetView/s:pane',ns)
                        self.assertEqual(pane.attrib['state'],'frozen')
                        self.assertEqual(pane.attrib['topLeftCell'],'A2')
                        if index>1:self.assertEqual(sheet.find('s:autoFilter',ns).attrib['ref'],'A1:J10001')
                    for index in range(2,6):
                        xml=ET.fromstring(book.read(f'xl/worksheets/sheet{index}.xml'));rows=xml.findall('s:sheetData/s:row',ns)
                        self.assertEqual(len(rows),10001)
                        self.assertEqual(rows[-1].find('s:c/s:v',ns).text,'10000')
                        self.assertEqual(rows[1].findall('s:c',ns)[1].find('s:is/s:t',ns).text,'01 02 03 04 05')
                        self.assertEqual(rows[-1].findall('s:c',ns)[1].find('s:is/s:t',ns).text,'06 07 08 09 10')
                        self.assertEqual(rows[-1].findall('s:c',ns)[4].find('s:v',ns).text,'0')
                    summary=book.read('xl/worksheets/sheet1.xml').decode();self.assertIn('=1+1',summary);self.assertNotIn('<f>',summary)
                self.assertEqual(len(state['requests']),1)
                layouts=[]
                for width in (320,390,760,1024,1440):
                    browser.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':900,'deviceScaleFactor':1,'mobile':False},page=True)
                    for theme in ('dark','light'):
                        browser.value(f'document.body.classList.toggle("light-theme",{str(theme=="light").lower()})')
                        sizes=browser.value('(()=>{const b=document.querySelector("[data-cycle-export]").getBoundingClientRect(),e=document.querySelector(".effectiveness-cycle-actions .effectiveness-cycle-toggle").getBoundingClientRect(),s=document.querySelector(".effectiveness-cycle>summary").getBoundingClientRect();return {bh:b.height,eh:e.height,topDiff:Math.abs(b.top-e.top),inside:b.left>=s.left&&e.right<=s.right+1,overflow:document.documentElement.scrollWidth>innerWidth+1}})()')
                        self.assertEqual(sizes['bh'],28);self.assertEqual(sizes['eh'],28);self.assertLess(sizes['topDiff'],1);self.assertTrue(sizes['inside']);self.assertFalse(sizes['overflow'],(width,theme,sizes));layouts.append({'width':width,'theme':theme,**sizes})
                        if (width,theme)in ((1440,'dark'),(390,'light')):
                            browser.value('document.querySelector(".effectiveness-history-head").scrollIntoView()')
                            shot=browser.call('Page.captureScreenshot',{'format':'png'},page=True);(artifacts/f'cycle_excel_{theme}_{width}.png').write_bytes(base64.b64decode(shot['data']))
                state['error']=True
                browser.value('document.querySelector("[data-cycle-export]").click()')
                wait('document.getElementById("effectivenessStatus").textContent.includes("Export fixture error")')
                self.assertFalse(browser.value('document.querySelector("[data-cycle-export]").disabled'))
                self.assertEqual(len(list(download.glob('*.xlsx'))),1)
                state['error']=False;state['delay']=.5
                browser.value('document.querySelector("[data-cycle-export]").click();document.querySelector("[data-cycle-export]").click()')
                time.sleep(.1)
                browser.value('window.dispatchEvent(new CustomEvent("dvlf:auth-changed",{detail:{authenticated:false}}))')
                time.sleep(.8)
                self.assertEqual(len(list(download.glob('*.xlsx'))),1)
                self.assertFalse(browser.value('!!document.querySelector("[data-cycle-export]")'))
                self.assertEqual(browser.value('browserErrors'),[])
                (ROOT/'Bin/session_1_latest/effectiveness_excel_layout_verification.json').write_text(json.dumps(layouts,indent=2),encoding='utf-8')
            finally:browser.close()
        server.shutdown();server.server_close()



class ExcelHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_effectiveness_web import EffectivenessWebTests
        cls.bridge=EffectivenessWebTests;cls.bridge.setUpClass()
    @classmethod
    def tearDownClass(cls):cls.bridge.tearDownClass()
    def test_authenticated_private_cycle_complete_export_and_invalid_scope(self):
        t=self.bridge
        fixture=NumericFixture();fixture.setUp()
        try:
            self.assertEqual(t.request('/api/ml/effectiveness?type='+fixture.GAME,cookie=t.member)[0],200)
            with closing(sqlite3.connect(t.work/'runtime/lotto_web.db')) as accounts:
                account=accounts.execute("SELECT id FROM personal_tracking_accounts WHERE username='member_fixture'").fetchone()[0]
            fixture.db=t.work/'runtime/personal_tracking'/account/'tracking.db'
            fixture.csv=t.work/'data/canonical/loto_5_35_all_day.csv'
            fixture.csv.parent.mkdir(parents=True,exist_ok=True);fixture._write()
            pe.configure(fixture.GAME,True,10000,'owner_fixture',fixture.db)
            pe.cycle(fixture.GAME,fixture.db)
            cycle=pe.report(fixture.GAME,db_path=fixture.db)['cycles'][0]
            path='/api/ml/effectiveness-export?type='+fixture.GAME+'&cycleId='+cycle['cycleId']
            self.assertEqual(t.request(path)[0],401)
            self.assertEqual(t.request(path,cookie=t.member,origin='https://untrusted.example')[0],403)
            self.assertEqual(t.request(path,{},cookie=t.member)[0],405)
            for suffix in ('&level=0','&level=11','&level=bad'):
                self.assertEqual(t.request(path+suffix,cookie=t.member)[0],400)
            self.assertEqual(t.request('/api/ml/effectiveness-export?type=LOTO_5_35&cycleId=bad',cookie=t.member)[0],400)
            self.assertEqual(t.request(path.replace('LOTO_5_35','LOTO_6_45'),cookie=t.member)[0],400)
            self.assertEqual(t.request(path.replace(cycle['cycleId'],cycle['methods']['web']['predictionId']),cookie=t.member)[0],400)
            self.assertEqual(t.request(path,cookie=t.admin)[0],400)
            before=fixture._counts()
            status,data,headers=t.request(path,cookie=t.member)
            self.assertEqual(status,200,data)
            self.assertEqual(headers.get('Cache-Control'),'no-store')
            self.assertEqual(data['cycleId'],cycle['cycleId'])
            self.assertEqual(data['status'],'locked')
            self.assertTrue(all(len(e['tickets'])==10000 for e in data['methods'].values()))
            self.assertEqual(fixture._counts(),before)
        finally:fixture.doCleanups()

if __name__=='__main__':unittest.main()
