import gzip
import hashlib
import json
import sqlite3
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
URL = 'http://127.0.0.1:8080'

def request(path, data=None, headers=None):
    req=urllib.request.Request(URL+path,data=data,headers=headers or {})
    try:
        with urllib.request.urlopen(req,timeout=10) as response:
            return response.status,{key.lower():value for key,value in response.headers.items()},response.read()
    except urllib.error.HTTPError as response:
        return response.code,{key.lower():value for key,value in response.headers.items()},response.read()

report={}
for path in ('/api/time','/api/store','/api/admin/users'):
    status,_,_=request(path)
    report[path]=status
    assert status==(200 if path=='/api/time' else 401),report
for path in ('/api/recover-admin','/api/admin/vip'):
    status,_,_=request(path,data=b'')
    report[path]=status
    assert status==(403 if path=='/api/recover-admin' else 401),report
status,_,_=request('/api/time',headers={'Origin':'https://untrusted.example'})
report['untrusted_origin_status']=status
assert status==403,report
status,headers,raw=request('/vietlott-web-core.js',headers={'Accept-Encoding':'gzip'})
decoded=gzip.decompress(raw) if headers.get('content-encoding')=='gzip' else raw
assert status==200 and decoded==(ROOT/'frontend/vietlott-web-core.js').read_bytes()
report['served_source_matches']=True
etag=headers.get('etag')
status,_,_=request('/vietlott-web-core.js',headers={'If-None-Match':etag})
report['conditional_status']=status
assert status==304
with closing(sqlite3.connect((ROOT/'runtime/lotto_web.db').resolve().as_uri()+'?mode=ro',uri=True)) as connection:
    report['sqlite_quick_check']=connection.execute('PRAGMA quick_check').fetchone()[0]
    report['tables']=[row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('account_entitlements','wallet_events','account_audit')")]
    report['users']=connection.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    report['stores']=connection.execute('SELECT COUNT(*) FROM stores').fetchone()[0]
assert report['sqlite_quick_check']=='ok' and len(report['tables'])==3
backup=ROOT/'Bin/session_1_latest/files/runtime/lotto_web.db'
with closing(sqlite3.connect(backup.resolve().as_uri()+'?mode=ro',uri=True)) as connection:
    assert report['users']==connection.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    assert report['stores']==connection.execute('SELECT COUNT(*) FROM stores').fetchone()[0]
report['user_and_store_counts_preserved']=True
(ROOT/'runtime/audit_2026-10-04/fix_production_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
