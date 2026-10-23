"""Verified per-draw Keno winner counts and capped hypothetical top payouts.

Rules: https://vietlott.vn/vi/choi/keno/gioi-thieu-san-pham-keno
Each of 8/8, 9/9, 10/10 has its OWN 10 billion VND cap per draw.
Reports only read the evidence cache; the worker/CLI refresh it separately.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai.configs import data_paths as dp
from backend.file_guard import resource_lock

TZ = timezone(timedelta(hours=7))
MAX_SAFE = 9007199254740991
POOL = 10000000000
NOMINAL = {8:200000000, 9:800000000, 10:2000000000}
THRESHOLD = {8:50, 9:12, 10:5}
CACHE = dp.RUNTIME_DIR / 'keno_prize_contexts.json'


def unit_amount(level, actual_winners, simulated_winners):
    if (level not in NOMINAL or type(actual_winners) is not int or type(simulated_winners) is not int
            or actual_winners < 0 or simulated_winners <= 0 or actual_winners+simulated_winners > MAX_SAFE):
        return None
    total = actual_winners+simulated_winners
    return NOMINAL[level] if total <= THRESHOLD[level] else POOL // total


def identity(draw, actual, deadline):
    at = datetime.fromisoformat(str(deadline).replace('Z', '+00:00'))
    if at.tzinfo is None:
        raise ValueError('Giờ quay Keno thiếu múi giờ.')
    at = at.astimezone(TZ)
    main = actual.get('main', [])
    if (len(main) != 20 or len(set(main)) != 20 or any(type(n) is not int or not 1 <= n <= 80 for n in main)
            or not str(draw).isdigit() or int(draw) <= 0):
        raise ValueError('Nhận diện kỳ Keno không hợp lệ.')
    return {'ky':str(int(draw)), 'date':at.strftime('%d/%m/%Y'), 'time':at.strftime('%H:%M'),
            'main':sorted(main), 'drawAt':at.isoformat()}


def load_cache(path=None):
    try:
        value = json.loads(Path(path or CACHE).read_text(encoding='utf-8'))
        if value.get('version') == 1 and isinstance(value.get('draws'), dict):
            return value
    except (OSError, ValueError, AttributeError):
        pass
    return {'version':1, 'draws':{}, 'retries':{}}


def context_for(draw, actual, deadline, records):
    try:
        expected = identity(draw, actual, deadline)
        record = records.get(expected['ky'], {})
        if record.get('draw') != expected:
            return {'status':'mismatch'}
        counts = record.get('winnerCounts', {})
        valid = {key:n for key,n in counts.items() if key in ('8','9','10') and type(n) is int and 0 <= n <= MAX_SAFE}
        if set(valid) != {'8','9','10'}:
            return {'status':'missing'}
        return {'status':'ready', 'draw':expected, 'kenoWinnerCounts':valid}
    except (ValueError, TypeError, AttributeError):
        return {'status':'missing'}


def parse_official(html, expected):
    """Accept only complete published tables matching the draw/date/20 balls.

Vietlott's final table prints '(Số lượng: N)' for winners and omits that
suffix on zero-winner rows. Accept that zero encoding ONLY in a complete,
correctly headed level table with other published numeric winner counts.
Missing tables/rows, placeholders, changed identities never become zero.
"""
    from bs4 import BeautifulSoup
    from ai.prizes import KENO_WINNING_HITS
    soup = BeautifulSoup(html, 'html.parser')
    result = soup.select_one('#divKenoResultContent .table-result-info')
    if result is None:
        raise ValueError('Thiếu bảng kết quả Keno chính thức.')
    balls = [int(e.get_text(strip=True)) for e in result.select('.day_so_ket_qua_v2 .bong_tron')]
    rows = [[c.get_text(' ',strip=True) for c in r.find_all('td',recursive=False)] for r in result.find_all('tr')]
    matching = [r for r in rows if len(r)==3 and re.fullmatch(r'\d{2}/\d{2}/\d{4}',r[0])]
    if (len(matching)!=1 or matching[0][0]!=expected['date'] or matching[0][1]!=f"#{int(expected['ky']):07d}"
            or len(balls)!=20 or sorted(balls)!=expected['main']):
        raise ValueError('Kỳ/ngày/bộ số Keno nguồn không khớp điểm đã lưu.')
    tables = soup.select('#divKenoResultContent .tabSelNumberInfo')
    if len(tables) != 12:
        raise ValueError('Bảng giải Keno nguồn chưa đầy đủ.')
    winners, encodings, published = {}, {}, {}
    for index,level in enumerate((10,9,8)):
        table = tables[index]
        headings = [x.get_text(' ',strip=True) for x in table.select('th')]
        if headings != ['Xác định kết quả','Giá trị trúng thưởng (Số lượng trúng thưởng)']:
            raise ValueError('Tiêu đề bảng giải Keno không khớp.')
        parsed = {}
        for row in table.find_all('tr'):
            cells = row.find_all('td',recursive=False)
            if not cells:
                continue
            if len(cells)!=2:
                raise ValueError('Dòng giải Keno không đầy đủ.')
            match = re.fullmatch(r'Trùng (\d{2}) trong 20 số',cells[0].get_text(' ',strip=True))
            text = cells[1].get_text(' ',strip=True)
            amount = re.fullmatch(r'(\d{1,3}(?:\.\d{3})*|\d+) đ(?:\s*\(\s*Số lượng:\s*(\d[\d.,]*)\s*\))?',text)
            if not match or not amount or int(match[1]) in parsed:
                raise ValueError('Dòng giải Keno chưa công bố hoặc bị lặp.')
            raw_count = amount[2]
            if raw_count is not None and not re.fullmatch(r'\d+|\d{1,3}(?:[.,]\d{3})+',raw_count):
                raise ValueError('Số vé trúng Keno nguồn không hợp lệ.')
            parsed[int(match[1])] = (int(amount[1].replace('.','')),int(re.sub(r'\D','',raw_count)) if raw_count is not None else None)
        if set(parsed) != KENO_WINNING_HITS[level] or not any(n is not None for _,n in parsed.values()):
            raise ValueError('Bảng giải Keno thiếu dòng hoặc chưa có thống kê.')
        amount,count = parsed[level]
        if count is None:
            if amount != NOMINAL[level]:
                raise ValueError('Giá trị giải Keno không khớp dòng không có vé trúng.')
            count = 0
            encodings[str(level)] = 'omitted_zero_in_complete_published_level_table'
        else:
            encodings[str(level)] = 'explicit_count'
        if not 0 <= count <= MAX_SAFE or not 0 < amount <= NOMINAL[level]:
            raise ValueError('Giá trị/số vé trúng Keno nguồn không hợp lệ.')
        winners[str(level)],published[str(level)] = count,amount
    return {'draw':expected, 'winnerCounts':winners, 'countEncoding':encodings, 'publishedUnits':published,
            'checkedAt':datetime.now(timezone.utc).isoformat(), 'htmlSha256':hashlib.sha256(html.encode()).hexdigest()}


def needed_draws(db_path):
    path = Path(db_path).resolve()
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        rows = db.execute("""SELECT DISTINCT c.target_draw_id,c.deadline,c.actual_json
            FROM keno_effectiveness_cycles c JOIN keno_effectiveness_metrics m ON m.cycle_id=c.cycle_id
            WHERE c.status='scored' AND ((m.level=8 AND json_extract(m.summary_json,'$.prizeCounts.KENO_8_8')>0)
            OR (m.level=9 AND json_extract(m.summary_json,'$.prizeCounts.KENO_9_9')>0)
            OR (m.level=10 AND json_extract(m.summary_json,'$.prizeCounts.KENO_10_10')>0))
            ORDER BY c.target_draw_id DESC""").fetchall()
    result = {}
    for row in rows:
        expected = identity(row['target_draw_id'],json.loads(row['actual_json']),row['deadline'])
        key = expected['ky']
        if key in result and result[key] != expected:
            raise ValueError('Cùng kỳ Keno có nhận diện điểm mâu thuẫn.')
        result[key] = expected
    return result


def refresh(db_path, limit=3, cache_path=None, evidence_dir=None):
    """Worker/CLI only: bounded requests outside DB transactions; atomic cache."""
    from backend import live_results as lr
    path = Path(cache_path or CACHE)
    if cache_path is None:
        try:
            cooldown = json.loads(lr.OFFICIAL_PRIZE_COUNTS_COOLDOWN_FILE.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            cooldown = {}
        if cooldown.get('blockedUntil',0) > time.time():
            return {'updated':0,'attempted':0,'errors':[],'status':'source_cooldown','retryAt':cooldown['blockedUntil']}
    targets = needed_draws(db_path)
    with resource_lock(path.with_suffix('.refresh'), timeout=.1):
        cache = load_cache(path)
        jobs = [r for key,r in targets.items() if (context_for(key,{'main':r['main']},r['drawAt'],cache['draws'])['status']!='ready'
                and cache.get('retries',{}).get(key,0)<=time.time())][:limit]
        errors,updated,attempted = [],0,0
        with lr.create_session() as session:
            for expected in jobs:
                attempted += 1
                key = expected['ky']
                url = f'https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/view-detail-keno-result?id={int(key):07d}'
                try:
                    html = lr.fetch_official_counts_html(session,url)
                    record = {**parse_official(html,expected), 'sourceUrl':url}
                    if evidence_dir:
                        output = Path(evidence_dir)
                        output.mkdir(parents=True,exist_ok=True)
                        (output/f'{key}.html').write_bytes(html.encode('utf-8'))
                    cache['draws'][key] = record
                    cache.setdefault('retries',{}).pop(key,None)
                    updated += 1
                except Exception as exc:
                    errors.append({'draw':key,'error':str(exc)[:300]})
                    cache.setdefault('retries',{})[key] = time.time()+600
                with resource_lock(path,timeout=3):
                    lr.write_json_file(path,cache)
                if errors:
                    break
                time.sleep(5)
        return {'updated':updated,'attempted':attempted,'errors':errors,'needed':len(targets)}
