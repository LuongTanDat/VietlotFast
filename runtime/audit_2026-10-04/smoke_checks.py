from pathlib import Path
import gzip
import json
import os
import re
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from tests.test_prize_web import CHROME
from ai.analysis.analysis import build_analysis_payload
from ai.stats.stats_v2 import build_stats_payload

report = {'live_http':{},'chatbot':{},'analysis':{},'stats':{}}
for path in ('/bang-du-lieu','/vietlott-web-core.js','/vietlott-web-data.js','/vietlott-web-stats.js','/vietlott-web-extra.css','/api/time','/api/live-history?type=LOTO_6_45&limit=100','/api/admin/users'):
    start=time.perf_counter()
    try:
        response=urlopen(Request('http://localhost:8080'+path,headers={'Accept-Encoding':'gzip'}),timeout=10)
        body=response.read()
        value={'status':response.status,'elapsed_ms':round((time.perf_counter()-start)*1000,1),'transfer_bytes':len(body),'gzip':response.headers.get('Content-Encoding')=='gzip'}
        if value['gzip']:
            value['decoded_bytes']=len(gzip.decompress(body))
        if response.headers.get('ETag'):
            try:
                cached=urlopen(Request('http://localhost:8080'+path,headers={'If-None-Match':response.headers['ETag']}),timeout=10)
                value['conditional_status']=cached.status
            except HTTPError as error:
                value['conditional_status']=error.code
        report['live_http'][path]=value
    except HTTPError as error:
        report['live_http'][path]={'status':error.code}
    except Exception as error:
        report['live_http'][path]={'error':str(error)}
result=subprocess.run([CHROME,'--headless','--disable-gpu','--no-sandbox','--no-first-run','--no-default-browser-check','--user-data-dir='+str(OUT/'chrome_smoke_profile'),'--virtual-time-budget=1500','--dump-dom',(ROOT/'tests/chatbot_harness.html').as_uri()],capture_output=True,timeout=25,creationflags=0x08000000 if os.name=='nt' else 0)
dom=result.stdout.decode('utf-8',errors='replace')
report['chatbot'] = dict(re.findall(r'data-([a-z-]+-test)="(pass|fail)"',dom))
(OUT/'chatbot_dom.html').write_text(dom,encoding='utf-8')
for game in ('LOTO_5_35','LOTO_6_45','LOTO_6_55','KENO','MAX_3D','MAX_3D_PRO'):
    start=time.perf_counter()
    payload=build_analysis_payload(game,period='30d',mode='all',limit=5)
    report['analysis'][game]={'ok':payload.get('ok'),'elapsed_seconds':round(time.perf_counter()-start,3),'message':payload.get('message',''),'warnings':payload.get('warnings',[])}
    start=time.perf_counter()
    payload=build_stats_payload(game,period='30d',combo_size=2,limit=5)
    report['stats'][game]={'ok':payload.get('ok'),'elapsed_seconds':round(time.perf_counter()-start,3),'comboMode':payload.get('comboMode'),'message':payload.get('message','')}
(OUT/'smoke_checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
