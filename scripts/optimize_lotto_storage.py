"""Audit and reversibly compress Lotto storage without changing logical bytes.

Default: metadata-only audit. --benchmark tests disposable SQLite copies.
--apply requires the matching passing benchmark. No database rewriting/deletion,
shell interpolation, executable compression, OS settings, or .git mutations.
"""
from __future__ import annotations

import argparse
import ctypes
import gc
import hashlib
import json
import os
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
COMPRESSED = 0x800
LINK_TAGS = (0xA0000003, 0xA000000C)
NAMES = ('runtime', 'Bin')


def stamp():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.part')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def policy(root=ROOT):
    value = json.loads((root / 'config/storage-policy.json').read_text(encoding='utf-8-sig'))
    if (value.get('version') != 1 or value.get('method') != 'ntfs-lznt1' or
            value.get('managedRoots') != list(NAMES) or
            type(value.get('minimumFileBytes')) is not int or value['minimumFileBytes'] < 1048576 or
            type(value.get('minimumFreeBytes')) is not int or value['minimumFreeBytes'] < 1024**3 or
            not 1 <= value.get('maxReadSlowdownRatio', 0) <= 1.5 or
            not 0 <= value.get('maxReadExtraMilliseconds', -1) <= 25 or
            set(value.get('excludedSuffixes', [])) != {'.lock', '.db-wal', '.db-shm', '.part', '.tmp'} or
            value.get('healthUrl') != 'http://localhost:8080/api/time'):
        raise ValueError('Chính sách lưu trữ không hợp lệ; chưa ghi thay đổi.')
    return value


def fingerprint(settings):
    sources=b''.join((ROOT/name).read_bytes() for name in ['ai/prediction_effectiveness.py','ai/prizes.py'])
    return hashlib.sha256(Path(__file__).read_bytes() + sources + json.dumps(settings, sort_keys=True).encode()).hexdigest()


def managed(root, path):
    """Check lexical path and every existing component before resolving links."""
    root = Path(root).resolve()
    original = Path(path)
    original = original if original.is_absolute() else root / original
    lexical = Path(os.path.abspath(original))
    relative = lexical.relative_to(root)
    if not relative.parts or relative.parts[0] not in NAMES:
        raise ValueError('Đường dẫn ngoài vùng dữ liệu được quản lý.')
    node = root
    for part in relative.parts:
        node = node / part
        if node.exists():
            info = node.lstat()
            if node.is_symlink() or getattr(info, 'st_reparse_tag', 0) in LINK_TAGS:
                raise ValueError('Không đi theo symlink/junction khi tối ưu dung lượng.')
    resolved = lexical.resolve()
    resolved.relative_to(root / relative.parts[0])
    return resolved


def require_ntfs(root):
    if os.name != 'nt':
        raise OSError('Công cụ nén này chỉ chạy trên Windows/NTFS.')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    fn = kernel.GetVolumeInformationW
    fn.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
    fn.restype = ctypes.c_int
    filesystem = ctypes.create_unicode_buffer(256)
    if not fn(str(Path(root).anchor), None, 0, None, None, None, filesystem, len(filesystem)):
        raise ctypes.WinError(ctypes.get_last_error())
    if filesystem.value.upper() != 'NTFS':
        raise OSError('Ổ dữ liệu không phải NTFS; chưa áp dụng nén.')


def allocated(path):
    if os.name != 'nt':
        return path.stat().st_blocks * 512
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    fn = kernel.GetCompressedFileSizeW
    fn.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)]
    fn.restype = ctypes.c_uint32
    high = ctypes.c_uint32()
    ctypes.set_last_error(0)
    low = fn(str(path), ctypes.byref(high))
    error = ctypes.get_last_error()
    if low == 0xffffffff and error:
        raise ctypes.WinError(error)
    return high.value << 32 | low


def info(path):
    st = path.stat()
    return {'logicalBytes': st.st_size, 'allocatedBytes': allocated(path),
            'compressed': bool(getattr(st, 'st_file_attributes', 0) & COMPRESSED),
            'modifiedNs': st.st_mtime_ns}


def inventory(root=ROOT):
    root = Path(root).resolve()
    result = {'root': str(root), 'at': stamp(), 'files': [], 'directories': [], 'errors': []}
    for name in NAMES:
        stack = [root / name]
        while stack:
            path = stack.pop()
            try:
                # Parents were checked before traversal; reject link entries before opening them.
                attrs=path.lstat()
                if path.is_symlink() or getattr(attrs,'st_reparse_tag',0) in LINK_TAGS:
                    raise ValueError('Không đi theo symlink/junction.')
                if path.is_dir():
                    result['directories'].append({'path': str(path.relative_to(root)),
                        'compressed': bool(getattr(path.stat(), 'st_file_attributes', 0) & COMPRESSED)})
                    with os.scandir(path) as entries:
                        stack.extend(Path(entry.path) for entry in entries)
                elif path.is_file():
                    result['files'].append({'path': str(path.relative_to(root)), **info(path)})
            except (OSError, ValueError) as error:
                result['errors'].append({'path': str(path), 'error': str(error)})
    result['logicalBytes'] = sum(item['logicalBytes'] for item in result['files'])
    result['allocatedBytes'] = sum(item['allocatedBytes'] for item in result['files'])
    return result


def eligible(item, settings):
    return (not item['compressed'] and item['logicalBytes'] >= settings['minimumFileBytes'] and
            not any(item['path'].lower().endswith(ext) for ext in settings['excludedSuffixes']))


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            value.update(block)
    return value.hexdigest()


def health(url):
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            response.read(4096)
            return {'ok': response.status == 200, 'milliseconds': round((time.perf_counter()-started)*1000, 2), 'at': stamp()}
    except OSError as error:
        return {'ok': False, 'error': str(error), 'at': stamp()}


def compact(root, target, log, *, undo=False, tick=None, force=False):
    target = managed(root, target)
    log = managed(root, log)
    executable = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/compact.exe'
    command = [str(executable), '/U' if undo else '/C', '/Q', '/A']
    if force:
        command.append('/F')
    command.append(str(target))
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('ab') as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        last = time.monotonic()
        while process.poll() is None:
            time.sleep(.25)
            if tick is not None and time.monotonic()-last >= 10:
                tick(); last = time.monotonic()
        if process.returncode:
            raise OSError(f'compact trả mã {process.returncode}; xem {log}')
    if bool(getattr(target.stat(), 'st_file_attributes', 0) & COMPRESSED) == undo:
        raise OSError('Thuộc tính nén sau thao tác chưa khớp.')


def mark_directories(root, targets, log):
    """Bounded argument list; every path verified, no wildcard/recursive command."""
    targets=[managed(root,path) for path in targets]
    log=managed(root,log)
    if any(not path.is_dir() for path in targets):
        raise ValueError('Chỉ đặt kế thừa cho thư mục.')
    executable=Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/compact.exe'
    with log.open('ab') as stream:
        result=subprocess.run([str(executable),'/C','/Q','/A',*[str(path) for path in targets]],stdout=stream,stderr=subprocess.STDOUT,
                              creationflags=subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    return result.returncode


def benchmark(output, root=ROOT):
    from ai.prediction_effectiveness import TICKET_COUNT_SQL
    from ai.prizes import classify_ticket
    root = Path(root).resolve(); settings = policy(root); require_ntfs(root)
    source_fingerprint=fingerprint(settings)
    output = managed(root, output); output.parent.mkdir(parents=True, exist_ok=True)
    folder = managed(root, output.parent / ('sqlite-trial-'+output.stem))
    folder.mkdir(exist_ok=False)
    baseline, compressed = folder/'baseline.db', folder/'compressed.db'
    source = root/'runtime/personal_tracking'
    candidates = list(source.glob('*/tracking.db'))
    if len(candidates) != 1:
        raise ValueError('Bản thử cần đúng một DB cá nhân; chưa chọn dữ liệu tài khoản thay người dùng.')
    origin = candidates[0].resolve()
    with closing(sqlite3.connect(origin.as_uri()+'?mode=ro', uri=True)) as src, closing(sqlite3.connect(baseline)) as dst:
        src.execute('PRAGMA query_only=ON')
        dst.execute('CREATE TABLE samples(prediction_id TEXT PRIMARY KEY,game TEXT,tickets_json TEXT,payload_json TEXT)')
        dst.execute('CREATE TABLE counts(prediction_id TEXT PRIMARY KEY,ticket_count INTEGER,chunk_size INTEGER)')
        dst.execute('CREATE TABLE chunks(id TEXT,n INTEGER,tickets_json TEXT,PRIMARY KEY(id,n))')
        dst.execute('CREATE TABLE probe(id INTEGER PRIMARY KEY,value TEXT)')
        for game in ['LOTO_5_35','LOTO_6_45','LOTO_6_55','KENO']:
            rows = set()
            for order in ['ASC','DESC']:
                rows.update(row[0] for row in src.execute('SELECT prediction_id FROM prediction_runs WHERE game_type=? ORDER BY rowid '+order+' LIMIT 1', (game,)))
            for prediction in sorted(rows):
                row = src.execute('SELECT prediction_id,game_type,tickets_json,payload_json FROM prediction_runs WHERE prediction_id=?', (prediction,)).fetchone()
                dst.execute('INSERT INTO samples VALUES(?,?,?,?)', row)
                dst.executemany('INSERT INTO counts VALUES(?,?,?)',src.execute('SELECT prediction_id,ticket_count,chunk_size FROM effectiveness_ticket_index WHERE prediction_id=?',(prediction,)))
                dst.executemany('INSERT INTO chunks VALUES(?,?,?)', src.execute('SELECT prediction_id,chunk_number,tickets_json FROM effectiveness_ticket_chunks WHERE prediction_id=?', (prediction,)))
        dst.commit()
    compact(root, baseline, output.with_suffix('.compact.log'), undo=True)
    shutil.copyfile(baseline, compressed)
    before_hash = digest(compressed); before = info(compressed)
    compact(root, compressed, output.with_suffix('.compact.log'), force=True)
    after = info(compressed)
    same = before_hash == digest(compressed)
    measurements = {};hot_paths={};workflows={};histograms={};summaries = {}
    for path in [baseline, compressed]:
        samples = []
        with closing(sqlite3.connect(path)) as db:
            db.execute('PRAGMA cache_size=-8192')
            ids = [row[0] for row in db.execute('SELECT prediction_id FROM samples ORDER BY prediction_id')]
            summaries[path.name] = db.execute("SELECT prediction_id,game,json_array_length(tickets_json),json_extract(payload_json,'$.type') FROM samples ORDER BY prediction_id").fetchall()
            # Warm both paths once before comparing. SQLite JSON work remains identical.
            for _ in range(3):
                begin = time.perf_counter()
                for key in ids:
                    db.execute("SELECT json_array_length(tickets_json),json_extract(payload_json,'$.type') FROM samples WHERE prediction_id=?", (key,)).fetchone()
                    db.execute('SELECT tickets_json FROM chunks WHERE id=? AND n=0', (key,)).fetchone()
                samples.append((time.perf_counter()-begin)/max(1,len(ids)))
            hot=[]
            for _ in range(5):
                begin=time.perf_counter()
                for key in ids:
                    db.execute(f'SELECT {TICKET_COUNT_SQL},pr.game FROM samples pr LEFT JOIN counts ti ON ti.prediction_id=pr.prediction_id WHERE pr.prediction_id=?',(key,)).fetchone()
                    chunk=db.execute('SELECT tickets_json FROM chunks WHERE id=? AND n=0',(key,)).fetchone()
                    if chunk:json.loads(chunk[0])
                hot.append((time.perf_counter()-begin)/len(ids))
            hot_paths[path.name]=round(statistics.median(hot)*1000,3)
            workflow={};histogram={}
            for key in ids:
                # Do not charge release/GC of the previous million-ticket portfolio to the next small one.
                gc.collect()
                begin=time.perf_counter()
                game,raw=db.execute('SELECT game,payload_json FROM samples WHERE prediction_id=?',(key,)).fetchone()
                payload=json.loads(raw)
                size=20 if game=='KENO' else 5 if game=='LOTO_5_35' else 6
                actual={'main':list(range(1,size+1))}
                if game in ('LOTO_5_35','LOTO_6_55'):actual['special']=12
                histogram[key]=dict(Counter(classify_ticket(game,ticket,actual)['prizeCode'] for ticket in payload.get('tickets',[])))
                workflow[key]=round((time.perf_counter()-begin)*1000,3)
                del payload,raw
            workflows[path.name]=workflow;histograms[path.name]=histogram
            assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
            db.execute('PRAGMA journal_mode=WAL')
            for number in range(20):
                db.execute('INSERT INTO probe VALUES(?,?)', (number, json.dumps({'main':list(range(1,21))})))
                db.commit()
            assert db.execute('SELECT COUNT(*) FROM probe').fetchone()[0] == 20
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        measurements[path.name] = round(statistics.median(samples)*1000, 3)
    limit = hot_paths['baseline.db']*settings['maxReadSlowdownRatio']+settings['maxReadExtraMilliseconds']
    scoring_ok=all(workflows['compressed.db'][key]<=value*settings['maxReadSlowdownRatio']+settings['maxReadExtraMilliseconds'] for key,value in workflows['baseline.db'].items())
    passed = (same and summaries['baseline.db'] == summaries['compressed.db'] and
              histograms['baseline.db']==histograms['compressed.db'] and scoring_ok and
              hot_paths['compressed.db'] <= limit and after['allocatedBytes'] < before['allocatedBytes']*.85 and fingerprint(settings)==source_fingerprint)
    report = {'ok':passed, 'kind':'ntfs-sqlite-benchmark-v1', 'root':str(root), 'at':stamp(), 'fingerprint':source_fingerprint,
              'logicalBytesUnchanged':same, 'sqliteReadsWritesWal':'passed', 'before':before, 'after':after,
              'sampleCount':len(ids), 'fullJsonInspectionMilliseconds':measurements,'indexedPageMilliseconds':hot_paths,
              'classificationWorkflowMilliseconds':workflows,'classificationOutputsMatch':histograms['baseline.db']==histograms['compressed.db'],
              'classificationWithinPolicy':scoring_ok,'maximumCompressedPageMilliseconds':round(limit,3),
              'sampleFiles':[str(baseline.relative_to(root)),str(compressed.relative_to(root))]}
    save(output, report)
    return report


def verify_benchmark(path, root, settings):
    report = json.loads(managed(root, path).read_text(encoding='utf-8'))
    if (report.get('ok') is not True or report.get('kind') != 'ntfs-sqlite-benchmark-v1' or
            report.get('root') != str(root) or report.get('fingerprint') != fingerprint(settings) or
            report.get('logicalBytesUnchanged') is not True or report.get('sqliteReadsWritesWal')!='passed' or
            report.get('sampleCount',0)<4 or report.get('classificationOutputsMatch') is not True or
            report.get('classificationWithinPolicy') is not True or
            report.get('indexedPageMilliseconds',{}).get('compressed.db',float('inf'))>report.get('maximumCompressedPageMilliseconds',-1)):
        raise ValueError('Cần bản thử đạt yêu cầu của đúng công cụ/chính sách và workspace hiện tại.')
    return report


def apply(output, benchmark_path, root=ROOT):
    root = Path(root).resolve(); settings = policy(root); require_ntfs(root)
    output = managed(root, output); verify_benchmark(benchmark_path, root, settings)
    if output.exists():
        raise ValueError('Báo cáo lượt áp dụng đã tồn tại; không ghi đè chứng từ.')
    if shutil.disk_usage(root).free < settings['minimumFreeBytes']:
        raise ValueError('Thiếu dung lượng dự phòng.')
    before = inventory(root)
    save(output.with_name(output.stem+'-before.json'), before)
    report = {'ok':False, 'root':str(root), 'kind':'ntfs-storage-apply-v1','startedAt':stamp(),
              'fingerprint':fingerprint(settings), 'changes':[], 'directories':[], 'errors':[], 'health':[]}
    initial_health = health(settings['healthUrl']); report['health'].append(initial_health)
    candidates = sorted((item for item in before['files'] if eligible(item,settings)), key=lambda item:item['logicalBytes'])
    # Verify the immutable backup first; bulk active files follow once that path succeeds.
    candidates.sort(key=lambda item:0 if item['path'].startswith('Bin') and item['path'].endswith('.db') else 1)
    for item in candidates:
        target = managed(root,item['path'])
        print(json.dumps({'phase':'compress','path':item['path'],'logicalGB':round(item['logicalBytes']/1e9,3)},ensure_ascii=False),flush=True)
        report['currentFile'] = item['path']; save(output,report)
        def tick():
            check = health(settings['healthUrl']); report['health'].append(check)
            report['heartbeatAt'] = stamp()
            try:report['currentAllocatedBytes'] = allocated(target)
            except OSError:pass
            save(output,report)
        try:
            current = info(target)
            if current['compressed']:
                continue
            immutable = target.suffix == '.db' and target.is_relative_to(root/'Bin')
            checksum = digest(target) if immutable else None
            begin = time.monotonic()
            compact(root,target,output.with_suffix('.compact.log'),tick=tick,force=True)
            updated = info(target)
            if checksum is not None and digest(target) != checksum:
                raise ValueError('SHA-256 bản sao lưu thay đổi; dừng xử lý.')
            report['changes'].append({'path':item['path'],'before':current,'after':updated,'sha256':checksum,'seconds':round(time.monotonic()-begin,2)})
            if checksum is not None:
                with closing(sqlite3.connect(target.as_uri()+'?mode=ro',uri=True)) as db:
                    db.execute('PRAGMA query_only=ON')
                    if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                        raise ValueError('Bản sao SQLite chưa qua quick_check.')
            check = health(settings['healthUrl']); report['health'].append(check)
            if initial_health['ok'] and not check['ok']:
                raise OSError('Server chưa phản hồi; dừng các mục tiếp theo.')
        except (OSError, ValueError) as error:
            report['errors'].append({'path':item['path'],'error':str(error)})
            save(output,report)
            if target.suffix == '.db' or isinstance(error,ValueError):
                raise
        save(output,report)
    # Mark directories only; no /S, wildcard, or recursive opaque operation.
    directories=[item for item in before['directories'] if not item['compressed']]
    for begin in range(0,len(directories),24):
        batch=directories[begin:begin+24]
        try:
            mark_directories(root,[item['path'] for item in batch],output.with_suffix('.compact.log'))
            for item in batch:
                if getattr(managed(root,item['path']).stat(),'st_file_attributes',0) & COMPRESSED:
                    report['directories'].append(item['path'])
                else:report['errors'].append({'path':item['path'],'error':'Chưa đặt được thuộc tính kế thừa nén.'})
        except (OSError,ValueError) as error:
            report['errors'].append({'paths':[item['path'] for item in batch],'error':str(error)})
        if begin%240==0:
            report['health'].append(health(settings['healthUrl']));save(output,report)
    after = inventory(root); save(output.with_name(output.stem+'-after.json'),after)
    report.update(ok=True,completedAt=stamp(),logicalBytesBefore=before['logicalBytes'],logicalBytesAfter=after['logicalBytes'],
                  allocatedBytesBefore=before['allocatedBytes'],allocatedBytesAfter=after['allocatedBytes'],
                  savedBytes=before['allocatedBytes']-after['allocatedBytes'],inventoryErrors=after['errors'])
    report.pop('currentFile',None); save(output,report)
    return {key:value for key,value in report.items() if key not in ('changes','directories','health')}


def undo(source_report, output, root=ROOT):
    root=Path(root).resolve(); settings=policy(root); require_ntfs(root)
    output=managed(root,output)
    report=json.loads(managed(root,source_report).read_text(encoding='utf-8'))
    if report.get('root')!=str(root) or report.get('kind')!='ntfs-storage-apply-v1':
        raise ValueError('Báo cáo hoàn tác không thuộc workspace này.')
    for item in report['changes']:managed(root,item['path'])
    for name in report['directories']:managed(root,name)
    changes=[]
    for item in reversed(report['changes']):
        target=managed(root,item['path']); current=info(target)
        if item['before']['compressed'] or not current['compressed']:continue
        required=max(0,current['logicalBytes']-current['allocatedBytes'])+settings['minimumFreeBytes']
        if shutil.disk_usage(root).free<required:raise ValueError('Thiếu dung lượng để giải nén an toàn.')
        checksum=digest(target) if item.get('sha256') else None
        compact(root,target,Path(output).with_suffix('.compact.log'),undo=True)
        if checksum and digest(target)!=checksum:raise ValueError('Hash hoàn tác không khớp.')
        changes.append(item['path'])
    for name in reversed(report['directories']):
        compact(root,managed(root,name),Path(output).with_suffix('.compact.log'),undo=True)
    result={'ok':True,'root':str(root),'kind':'ntfs-storage-undo-v1','at':stamp(),'restored':changes}
    save(managed(root,output),result);return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark',action='store_true')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--benchmark-report',type=Path)
    parser.add_argument('--undo',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.benchmark and (args.apply or args.undo):parser.error('Không ghép benchmark với apply/undo.')
    if args.undo and not args.apply:parser.error('Hoàn tác cần --apply.')
    output=managed(ROOT,args.output)
    if args.benchmark:result=benchmark(output)
    elif args.apply and args.undo:result=undo(args.undo,output)
    elif args.apply:
        if not args.benchmark_report:parser.error('--apply cần --benchmark-report.')
        result=apply(output,args.benchmark_report)
    else:
        result=inventory();save(output,result)
        result={key:value for key,value in result.items() if key not in ('files','directories')}
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    return 0 if result.get('ok',True) else 1


if __name__=='__main__':
    raise SystemExit(main())
