import hashlib
import json
import sqlite3
from contextlib import closing
from backup_fixes import backup, ROOT, LATEST

backup([str(path.relative_to(ROOT)).replace('\\', '/') for path in (ROOT/'backend/bin').glob('LottoWebServer*.class')])
source = ROOT/'runtime/lotto_web.db'
target = LATEST/'files/runtime/lotto_web.db'
if source.exists() and not target.exists():
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as reader, closing(sqlite3.connect(target)) as writer:
        reader.backup(writer)
    manifest_path=LATEST/'manifest.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['files'].append({'path':'runtime/lotto_web.db','action':'replace','method':'consistent SQLite online backup before schema migration',
                              'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print('Build and consistent database backup prepared')
