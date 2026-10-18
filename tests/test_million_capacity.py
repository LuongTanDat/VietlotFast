"""Budget migration, exact compact scoring and large-export transport guards."""
import io
import json
import random
import sqlite3
import tempfile
import unittest
import urllib.request
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

from ai import prediction_effectiveness as pe, prediction_ledger as ledger, tracking_portfolio as portfolio
from ai.effectiveness_xlsx import write_cycle_xlsx


class MillionCapacityTests(unittest.TestCase):
    def test_prepared_ledger_and_chunks_match_original_payload_and_reject_corruption(self):
        import hashlib
        from concurrent.futures import ProcessPoolExecutor
        from ai import keno_effectiveness as ke
        probabilities={n:.25 for n in range(1,81)}
        snapshot={'cutoff':'40','target':'41','dataHash':'prepared-fixture'}
        web=ke._baseline('random',5,8,snapshot,probabilities)
        context={'deadline':'2035-01-06T18:00:00+07:00','dataHash':snapshot['dataHash'],'fallbackModel':'fixture_model'}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'prepared.json'
            task=(5,'web',10001,web,probabilities,snapshot,str(path))
            original=ke._recorded_payload(ke._portfolio_payload(task))
            original.update({'predictionDeadline':context['deadline'],'dataHash':context['dataHash'],
                             'modelId':original.get('modelId')or context['fallbackModel'],'effectivenessLevel':5})
            with ProcessPoolExecutor(max_workers=2) as pool:
                prepared=pool.submit(ke._stage_prepared_portfolio,(task,context)).result()
            serialized=path.read_text(encoding='utf-8')
            reconstructed=ledger.canonical_payload_json(prepared['metadata'],serialized)
            self.assertEqual(reconstructed,ledger.canonical_json(original))
            self.assertEqual(hashlib.sha256(reconstructed.encode()).hexdigest(),prepared['payloadChecksum'])
            with closing(pe._connect(Path(directory)/'private.db')) as connection:
                connection.execute('BEGIN IMMEDIATE')
                saved=ledger.lock_prediction(prepared['metadata'],username=pe.ACTOR,connection=connection,
                                             serialized_tickets=serialized,expected_checksum=prepared['payloadChecksum'])
                ke._insert_prepared_index(connection,saved['prediction_id'],path,prepared)
                stored=connection.execute('SELECT payload_json,tickets_json FROM prediction_runs').fetchone()
                self.assertEqual(stored[0],ledger.canonical_json(original))
                self.assertEqual(json.loads(stored[1]),original['tickets'])
                self.assertEqual(pe._ticket_slice(connection,saved['prediction_id'],1001)[0],original['tickets'][-1:])
                connection.commit()
                with self.assertRaisesRegex(ValueError,'checksum'):
                    ledger.lock_prediction(prepared['metadata'],username=pe.ACTOR,connection=connection,
                                           serialized_tickets=serialized.replace('[','[9,',1),expected_checksum=prepared['payloadChecksum'])
                connection.execute('BEGIN IMMEDIATE')
                another=ledger.lock_prediction(prepared['metadata'],username=pe.ACTOR,connection=connection,
                                               serialized_tickets=serialized,expected_checksum=prepared['payloadChecksum'])
                path.with_suffix('.chunks.jsonl').write_bytes(b'[]\n')
                with self.assertRaisesRegex(ValueError,'checksum'):
                    ke._insert_prepared_index(connection,another['prediction_id'],path,prepared)
                connection.rollback()
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM prediction_runs').fetchone()[0],1)

    def test_parallel_scoring_is_identical_and_does_not_write_database(self):
        from concurrent.futures import ProcessPoolExecutor
        from ai import keno_effectiveness as ke
        from tests.test_keno_effectiveness import KenoEffectivenessTests
        fixture=KenoEffectivenessTests();fixture.setUp()
        try:
            locked=ke.cycle(fixture.db)
            at=ke.next_draw_at(ke.draw_at(fixture.draws[-1]));actual=fixture.row(26,at)
            with closing(pe._connect(fixture.db)) as connection:
                ids=[row[0] for row in connection.execute('SELECT prediction_id FROM keno_effectiveness_predictions WHERE level=5 ORDER BY method LIMIT 2')]
            tasks=[(str(fixture.db),identity,actual,5,3,{'cutoff':'25','target':'26'}) for identity in ids]
            serial=[ke._score_portfolio(task) for task in tasks]
            with ProcessPoolExecutor(max_workers=2) as pool:
                parallel=list(pool.map(ke._score_portfolio,tasks))
            self.assertEqual(serial,parallel)
            self.assertEqual(fixture.counts()['prediction_scores'],0)
            self.assertEqual(fixture.counts()['prediction_runs'],40)
        finally:fixture.doCleanups()

    def test_low_disk_blocks_large_generation_before_calling_web(self):
        from tests.test_prediction_effectiveness import PredictionEffectivenessTests
        from tests.test_keno_effectiveness import KenoEffectivenessTests
        for fixture_class,game,web_name in [(PredictionEffectivenessTests,'LOTO_5_35','web'),(KenoEffectivenessTests,'KENO','web_mock')]:
            fixture=fixture_class();fixture.setUp()
            try:
                pe.configure(game,True,10001,'trial',fixture.db)
                with patch('ai.tracking_capacity.ensure_storage',side_effect=ValueError('Tạm dừng tạo vé')):
                    with self.assertRaisesRegex(ValueError,'Tạm dừng tạo vé'):
                        pe.cycle(game,fixture.db)
                getattr(fixture,web_name).assert_not_called()
                with closing(pe._connect(fixture.db)) as connection:
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM prediction_runs').fetchone()[0],0)
            finally:fixture.doCleanups()

    def test_parallel_staging_is_byte_identical_to_serial_seeded_generation(self):
        from concurrent.futures import ProcessPoolExecutor
        from ai import keno_effectiveness as ke
        probabilities={n:.25 for n in range(1,81)}
        snapshot={'cutoff':'40','target':'41','dataHash':'parallel-fixture'}
        web=ke._baseline('random',5,8,snapshot,probabilities)
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory)
            tasks=[]
            for method in ('web','random'):
                serial=(5,method,10001,web,probabilities,snapshot,str(work/f'{method}_serial.json'))
                ke._stage_portfolio(serial)
                tasks.append((5,method,10001,web,probabilities,snapshot,str(work/f'{method}_parallel.json')))
            with ProcessPoolExecutor(max_workers=2) as pool:
                for result in pool.map(ke._stage_portfolio,tasks):self.assertTrue(result[0])
            for method in ('web','random'):
                self.assertEqual((work/f'{method}_serial.json').read_bytes(),(work/f'{method}_parallel.json').read_bytes())
            self.assertFalse(list(work.glob('*.db')))

    def test_storage_guard_keeps_reserve_without_deleting_history(self):
        from ai import tracking_capacity
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            db=Path(directory)/'keep.db';db.write_bytes(b'preserve history')
            counts=[(level,4*portfolio.effective_count(1000000,80,level)) for level in range(1,11)]
            with patch.object(tracking_capacity.shutil,'disk_usage',return_value=SimpleNamespace(free=21*1024**3)):
                with self.assertRaisesRegex(ValueError,'Tạm dừng tạo vé'):
                    tracking_capacity.ensure_storage(db,counts)
            self.assertEqual(db.read_bytes(),b'preserve history')
            with patch.object(tracking_capacity.shutil,'disk_usage',return_value=SimpleNamespace(free=100*1024**3)):
                result=tracking_capacity.ensure_storage(db,counts)
                self.assertGreater(result['requiredBytes'],30*1024**3)

    def test_both_old_settings_caps_migrate_without_changing_values_or_audits(self):
        for old_cap in (10, 10000):
            with self.subTest(old_cap=old_cap), tempfile.TemporaryDirectory() as directory:
                db = Path(directory) / 'private.db'
                with closing(pe._connect(db)) as c:
                    schema = c.execute("SELECT sql FROM sqlite_master WHERE name='effectiveness_settings'").fetchone()[0]
                    c.execute('DROP TABLE effectiveness_settings')
                    c.execute(schema.replace('BETWEEN 1 AND 1000000)', f'BETWEEN 1 AND {old_cap})'))
                    c.execute("INSERT INTO effectiveness_settings VALUES('KENO',1,5,'before','owner','tick','error','123')")
                    c.execute("INSERT INTO effectiveness_config_audit VALUES('old','KENO','owner','before','{}')")
                with closing(pe._connect(db)) as c:
                    row = c.execute("SELECT * FROM effectiveness_settings WHERE game_type='KENO'").fetchone()
                    self.assertEqual(tuple(row), ('KENO',1,5,'before','owner','tick','error','123'))
                    self.assertEqual(c.execute('SELECT event_id FROM effectiveness_config_audit').fetchone()[0], 'old')
                for game in (*pe.GAMES, 'KENO'):
                    maximum = 100000 if game == 'KENO' else 1000000
                    settings = pe.configure(game, False, maximum, 'trial', db)['settings']
                    self.assertEqual(settings['ticketCount'], maximum)
                    self.assertEqual(settings['maxTicketCount'], maximum)
                    with self.assertRaises(ValueError):
                        pe.configure(game, False, maximum + 1, 'trial', db)
                with closing(pe._connect(db)) as c:
                    self.assertEqual(c.execute('PRAGMA quick_check').fetchone()[0], 'ok')

    def test_saturated_spaces_preserve_prefix_and_unique_mains(self):
        self.assertEqual(portfolio.effective_count(1000000, 35, 5), 324632)
        self.assertEqual([portfolio.effective_count(1000000,80,k) for k in range(1,5)], [80,3160,82160,1000000])
        prefix = [[1,2,3]]
        mains = portfolio.unique_mains({n: .1+n/80 for n in range(1,81)},3,82160,42,prefix)
        self.assertEqual(mains[0], (1,2,3))
        self.assertEqual(len(mains),82160)
        self.assertEqual(len(set(mains)),82160)

    def test_vectorized_unranking_matches_scalar_order_exactly(self):
        import math
        rng=random.Random(73)
        for universe,pick in [(35,5),(45,6),(55,6),(80,4),(80,10)]:
            ranks=rng.sample(range(math.comb(universe,pick)),10001)
            self.assertEqual(portfolio._unrank_many(ranks,universe,pick),[portfolio._unrank(rank,universe,pick) for rank in ranks])

    def test_compact_scoring_matches_full_storage_exactly_all_games_and_keno_levels(self):
        rng = random.Random(41)
        for game, universe, draw, levels in [('LOTO_5_35',35,5,[5]),('LOTO_6_45',45,6,[6]),('LOTO_6_55',55,6,[6]),('KENO',80,20,range(1,11))]:
            for level in levels:
                tickets = [{'main': sorted(rng.sample(range(1,universe+1),level)),
                            'special': rng.randrange(1,13) if game=='LOTO_5_35' else None} for _ in range(137)]
                actual = {'main': list(range(1,draw+1)), 'special': 2 if game=='LOTO_5_35' else 7 if game=='LOTO_6_55' else None}
                payload = {'type':game,'tickets':tickets,'pickSize':level,'probabilities':{n:draw/universe for n in range(1,universe+1)}}
                full = ledger.score_prediction_payload(payload,actual,universe,draw,level)
                compact = ledger.score_prediction_payload(payload,actual,universe,draw,level,compact=True)
                self.assertEqual(compact,pe._score_storage(full),(game,level))
        tickets = [{'main':[1,2,3,4,5],'special':2}] * 10001
        payload = {'type':'LOTO_5_35','tickets':tickets,'probabilities':{n:5/35 for n in range(1,36)}}
        with patch.object(ledger._portfolio_random_best, '__wrapped__', wraps=ledger._portfolio_random_best.__wrapped__) as uncached:
            ledger.score_prediction_payload(payload,{'main':[1,2,3,4,5],'special':2},35,5,5,compact=True)
            self.assertEqual(uncached.call_count,1)


class WorkbookTransportTests(unittest.TestCase):
    def test_workbook_preserves_recorded_data_filters_and_rejects_existing_file(self):
        from tests.test_prediction_effectiveness import PredictionEffectivenessTests
        fixture = PredictionEffectivenessTests()
        fixture.setUp()
        try:
            locked = pe.cycle(fixture.GAME,fixture.db)
            fixture._actual()
            pe.score_cycles(fixture.GAME,fixture.db)
            output = fixture.root / 'export.xlsx'
            result = write_cycle_xlsx(fixture.GAME,locked['cycleId'],output,fixture.db)
            self.assertTrue(result['ok'])
            before = output.read_bytes()
            with self.assertRaises(FileExistsError):
                write_cycle_xlsx(fixture.GAME,locked['cycleId'],output,fixture.db)
            self.assertEqual(output.read_bytes(),before)
            ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            with zipfile.ZipFile(output) as archive:
                self.assertIsNone(archive.testzip())
                for index in range(2,6):
                    sheet=ET.fromstring(archive.read(f'xl/worksheets/sheet{index}.xml'))
                    self.assertEqual(sheet.find('s:autoFilter',ns).get('ref'),'A1:J4')
                    self.assertEqual(sheet.find('s:sheetViews/s:sheetView/s:pane',ns).get('topLeftCell'),'A2')
                    self.assertEqual(len(sheet.findall('s:sheetData/s:row',ns)),4)
                    self.assertFalse(sheet.findall('.//s:f',ns))
            pe.configure(fixture.GAME,True,10001,'trial',fixture.db)
            # Separate cycle in a fresh private DB; the old immutable cycle stays intact.
            second = fixture.root / 'large.db'
            pe.configure(fixture.GAME,True,10001,'trial',second)
            fixture.now.return_value = fixture.clock
            # Remove the synthetic actual from the CSV so the fixture's target is future again.
            fixture.draws.pop();fixture._write()
            large=pe.cycle(fixture.GAME,second)
            with closing(pe._connect(second)) as connection:
                prediction=connection.execute('SELECT prediction_id FROM effectiveness_predictions LIMIT 1').fetchone()[0]
                queries=[];connection.set_trace_callback(queries.append)
                page,pagination=pe._ticket_slice(connection,prediction,1001)
                self.assertEqual(pagination['offset'],10000)
                self.assertEqual(len(page),1)
                self.assertFalse(any('json_each' in query for query in queries))
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("UPDATE effectiveness_ticket_chunks SET tickets_json='[]'")
            with self.assertRaisesRegex(ValueError,'trực tiếp file Excel'):
                pe.export_cycle(fixture.GAME,large['cycleId'],second)
        finally:
            fixture.doCleanups()

    def test_authenticated_java_binary_export_and_one_million_settings(self):
        from tests.test_effectiveness_web import EffectivenessWebTests as Server
        from tests.test_prediction_effectiveness import PredictionEffectivenessTests
        Server.setUpClass()
        fixture=PredictionEffectivenessTests();fixture.setUp()
        try:
            db=Server.work/'runtime/lotto_web.db'
            locked=pe.cycle(fixture.GAME,db)
            for game in (*pe.GAMES,'KENO'):
                maximum=100000 if game=='KENO' else 1000000
                code,data,_=Server.request('/api/ml/effectiveness-settings',{'type':game,'enabled':'false','ticketCount':maximum},Server.admin)
                self.assertEqual(code,200,data)
                self.assertEqual(data['settings']['ticketCount'],maximum)
                if game=='KENO':
                    code,data,_=Server.request('/api/ml/effectiveness-settings',{'type':game,'enabled':'false','ticketCount':100001},Server.admin)
                    self.assertEqual(code,400,data)
                    self.assertIn('100.000',str(data))
            url=Server.url+f'/api/ml/effectiveness-export?type={fixture.GAME}&cycleId={locked["cycleId"]}&format=xlsx'
            request=urllib.request.Request(url,headers={'Cookie':Server.member,'Origin':Server.url})
            with urllib.request.urlopen(request,timeout=60) as response:
                self.assertIn('spreadsheetml.sheet',response.headers['Content-Type'])
                self.assertEqual(response.headers['Cache-Control'],'no-store')
                with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
                    self.assertIsNone(archive.testzip())
            self.assertFalse(list((Server.work/'runtime').glob('effectiveness_export_*')))
            for cookie,origin in [(None,None),(Server.member,'https://untrusted.invalid')]:
                code,_,_=Server.request(url.removeprefix(Server.url),cookie=cookie,origin=origin)
                self.assertIn(code,(401,403))
        finally:
            fixture.doCleanups();Server.tearDownClass()


class LargeDownloadBrowserTests(unittest.TestCase):
    def test_large_binary_download_limits_deduplication_error_and_logout(self):
        import threading
        import time
        import urllib.parse
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from tests.browser_cdp import Browser
        from tests.test_prize_web import ROOT, CHROME
        html=(ROOT/'frontend/vietlott-web.html').read_text(encoding='utf-8')
        section=html[html.index('      <section id="predictRootEffectiveness"'):html.index('      <section id="predictRootManual"')]
        page='<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><link rel=stylesheet href=/vietlott-web.css><link rel=stylesheet href=/vietlott-web-extra.css>'+section+'<script src=/vietlott-web-numeric.js></script><script src=/vietlott-web-effectiveness.js></script>'
        state={'requests':[],'delay':0,'error':False}
        binary=io.BytesIO()
        with zipfile.ZipFile(binary,'w') as archive:
            archive.writestr('transport-fixture.txt','Binary transport fixture; workbook contents are tested separately.')
        fixture_bytes=binary.getvalue()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self):
                parsed=urllib.parse.urlparse(self.path);query=urllib.parse.parse_qs(parsed.query)
                status=200;mime='application/json'
                if parsed.path=='/api/ml/effectiveness-export':
                    state['requests'].append(self.path);time.sleep(state['delay'])
                    status=503 if state['error'] else 200
                    mime='application/json' if state['error'] else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                    body=json.dumps({'message':'Binary export fixture error'}).encode() if state['error'] else fixture_bytes
                elif parsed.path=='/api/ml/effectiveness':
                    game=query['type'][0];level=int(query.get('level',['10'])[0])
                    count=portfolio.effective_count(1000000,80,level) if game=='KENO' else 324632 if game=='LOTO_5_35' else 1000000
                    cycle={'cycleId':'00000000-0000-0000-0000-000000000001','targetDrawId':'41','cutoffDrawId':'40','status':'locked','deadline':'2035-01-06T11:00:00Z','config':{'ticketCount':1000000,'actualTicketCount':count},'methods':{key:{'predictionId':key,'ticketCount':count,'tickets':[],'ticketResults':[],'ticketPagination':{'total':count,'page':1,'totalPages':100000,'pageSize':10,'offset':0}} for key in pe.METHODS}}
                    body=json.dumps({'ok':True,'canManage':True,'type':game,'level':level,'settings':{'enabled':True,'ticketCount':1000000},'counts':{'locked':1,'scored':0,'total':1},'cycles':[cycle],'methods':[]}).encode()
                elif parsed.path=='/':body=page.encode();mime='text/html;charset=utf-8'
                elif parsed.path.startswith('/vietlott-web'):
                    asset=ROOT/'frontend'/parsed.path.lstrip('/');body=asset.read_bytes();mime='text/css' if asset.suffix=='.css' else 'application/javascript'
                else:body=b'{}'
                self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.end_headers()
                try:self.wfile.write(body)
                except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with tempfile.TemporaryDirectory(prefix='million-browser-',dir=ROOT/'runtime') as folder:
                work=Path(folder);download=work/'download';download.mkdir()
                browser=Browser(CHROME,work/'profile')
                def wait(expression,timeout=20):
                    until=time.monotonic()+timeout
                    while time.monotonic()<until:
                        if browser.value(expression):return
                        time.sleep(.05)
                    self.fail(expression)
                try:
                    browser.call('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str(download)},page=False)
                    browser.call('Page.navigate',{'url':f'http://127.0.0.1:{server.server_port}/'},page=True)
                    wait('!!window.VietlottEffectiveness')
                    browser.value('document.getElementById("predictRootEffectiveness").hidden=false;window.dispatchEvent(new CustomEvent("dvlf:auth-changed",{detail:{authenticated:true}}));VietlottEffectiveness.activate(true)')
                    wait('!!document.querySelector("[data-cycle-export]")')
                    browser.value('document.getElementById("effectivenessSettings").click()')
                    self.assertEqual(browser.value('document.getElementById("effectivenessTicketCount").max'),'1000000')
                    self.assertIn('324.632',browser.value('document.getElementById("effectivenessTicketHint").textContent'))
                    browser.value('document.querySelector("[data-cycle-export]").click();document.querySelector("[data-cycle-export]").click()')
                    wait('document.getElementById("effectivenessStatus").textContent.startsWith("Đã tải Excel")')
                    wait("document.querySelector('[data-cycle-export]').disabled===false")
                    until=time.monotonic()+10
                    while not list(download.glob('*.xlsx')) and time.monotonic()<until:time.sleep(.05)
                    self.assertEqual(list(download.glob('*.xlsx'))[0].read_bytes(),fixture_bytes)
                    self.assertEqual(len(state['requests']),1)
                    self.assertIn('format=xlsx',state['requests'][0])
                    for level,maximum in [(1,80),(2,3160),(3,82160),(10,100000)]:
                        browser.value(f'document.getElementById("effectivenessType").value="KENO";document.getElementById("effectivenessKenoLevel").value="{level}";document.getElementById("effectivenessType").dispatchEvent(new Event("change"))')
                        wait(f'!document.getElementById("effectivenessRefresh").disabled && document.getElementById("effectivenessTicketCount").max==="{maximum}"')
                    state['error']=True
                    browser.value('document.querySelector("[data-cycle-export]").click()')
                    wait('document.getElementById("effectivenessStatus").textContent.includes("Binary export fixture error")')
                    state['error']=False;state['delay']=.6
                    browser.value('document.querySelector("[data-cycle-export]").click();window.dispatchEvent(new CustomEvent("dvlf:auth-changed",{detail:{authenticated:false}}))')
                    time.sleep(.8)
                    self.assertEqual(len(list(download.glob('*.xlsx'))),1)
                finally:browser.close()
        finally:server.shutdown();server.server_close()


class TrackingStorageTests(unittest.TestCase):
    def test_http_uses_dedicated_tracking_and_account_writes_remain_available(self):
        import time
        from ai import tracking_storage as storage
        from tests.test_effectiveness_web import EffectivenessWebTests as Server
        from tests.test_prediction_effectiveness import PredictionEffectivenessTests
        Server.setUpClass();fixture=PredictionEffectivenessTests();fixture.setUp()
        try:
            shared=Server.work/'runtime/lotto_web.db';dedicated=Server.work/'runtime'/storage.DATABASE_NAME
            pe.cycle(fixture.GAME,shared)
            storage.migrate_tracking(shared,dedicated)
            (Server.work/'runtime'/storage.CONFIG_NAME).write_text(json.dumps({'version':1,'mode':'dedicated'}),encoding='utf-8')
            code,data,_=Server.request('/api/ml/effectiveness-settings',{'type':fixture.GAME,'enabled':'false','ticketCount':1000000},Server.admin)
            self.assertEqual(code,200,data)
            self.assertEqual(pe.settings(fixture.GAME,shared)['settings']['ticketCount'],3)
            self.assertEqual(pe.settings(fixture.GAME,dedicated)['settings']['ticketCount'],1000000)
            with closing(pe._connect(dedicated)) as writer:
                writer.execute('BEGIN IMMEDIATE')
                start=time.perf_counter()
                code,data,_=Server.request('/api/register',{'username':'tracking_separation_fixture','password':'fixture_password'})
                self.assertEqual(code,200,data)
                self.assertLess(time.perf_counter()-start,5)
                start=time.perf_counter()
                code,data,_=Server.request('/api/ml/effectiveness?type=LOTO_5_35',cookie=Server.member)
                self.assertEqual(code,200,data)
                self.assertEqual(data['counts']['locked'],1)
                self.assertLess(time.perf_counter()-start,5)
                writer.rollback()
            with closing(pe._connect(dedicated)) as connection:
                self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='users'").fetchone())
        finally:fixture.doCleanups();Server.tearDownClass()

    def test_migration_preserves_tracking_excludes_credentials_and_is_idempotent(self):
        from ai import tracking_storage as storage, keno_effectiveness as ke
        from tests.test_prediction_effectiveness import PredictionEffectivenessTests
        from tests.test_keno_effectiveness import KenoEffectivenessTests
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'accounts.db';destination=root/storage.DATABASE_NAME
            fixture=PredictionEffectivenessTests();fixture.setUp();fixture.db=source
            try:
                pe.configure(fixture.GAME,True,3,'owner_fixture',source)
                pe.cycle(fixture.GAME,source)
                with closing(pe._connect(source)) as connection:
                    payload=json.loads(connection.execute('SELECT payload_json FROM prediction_runs LIMIT 1').fetchone()[0])
                    ledger.lock_prediction(payload,username='personal_owner',connection=connection)
                    connection.execute('CREATE TABLE users(username TEXT,password_hash TEXT)')
                    connection.execute("INSERT INTO users VALUES('private_owner','credential_fixture')")
            finally:fixture.doCleanups()
            fixture=KenoEffectivenessTests();fixture.setUp();fixture.db=source
            try:
                ke.cycle(source)
            finally:fixture.doCleanups()
            with closing(pe._connect(source)) as connection:
                original_settings=[tuple(row) for row in connection.execute('SELECT * FROM effectiveness_settings ORDER BY game_type')]
                original_runs=[tuple(row) for row in connection.execute('SELECT prediction_id,username,payload_checksum FROM prediction_runs ORDER BY prediction_id')]
            report=storage.migrate_tracking(source,destination)
            self.assertEqual(report['counts']['prediction_runs'],44)
            self.assertEqual(report['counts']['keno_effectiveness_predictions'],40)
            with closing(pe._connect(destination)) as connection:
                self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='users'").fetchone())
                self.assertIsNone(connection.execute("SELECT prediction_id FROM prediction_runs WHERE username='personal_owner'").fetchone())
                self.assertEqual([tuple(row) for row in connection.execute('SELECT * FROM effectiveness_settings ORDER BY game_type')],original_settings)
                self.assertIsNone(connection.execute('PRAGMA foreign_key_check').fetchone())
            pe.configure('KENO',False,7,'after_migration',destination)
            self.assertEqual(storage.migrate_tracking(source,destination)['status'],'already_migrated')
            self.assertEqual(pe.settings('KENO',destination)['settings']['ticketCount'],7)
            with closing(pe._connect(source)) as connection:
                self.assertEqual([tuple(row) for row in connection.execute('SELECT prediction_id,username,payload_checksum FROM prediction_runs ORDER BY prediction_id')],original_runs)
                self.assertEqual(connection.execute('SELECT password_hash FROM users').fetchone()[0],'credential_fixture')

    def test_storage_activation_requires_existing_database_and_never_changes_explicit_fixture(self):
        from ai import tracking_storage as storage
        with tempfile.TemporaryDirectory() as directory, patch.object(storage.dp,'RUNTIME_DIR',Path(directory)):
            root=Path(directory)
            self.assertEqual(storage.database_path(),Path(ledger.DEFAULT_DB_PATH))
            (root/storage.CONFIG_NAME).write_text(json.dumps({'version':1,'mode':'dedicated'}),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'Không tìm thấy DB'):
                storage.database_path()
            target=root/storage.DATABASE_NAME;target.touch()
            self.assertEqual(storage.database_path(),target)
            self.assertEqual(storage.database_path(root/'fixture.db'),root/'fixture.db')
            (root/storage.CONFIG_NAME).write_text(json.dumps({'version':1,'mode':'unexpected'}),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'không hợp lệ'):
                storage.database_path()


if __name__ == '__main__':
    unittest.main()
