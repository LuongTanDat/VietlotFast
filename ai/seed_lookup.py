"""Read-only lookup and in-memory replay of frozen per-ticket seed schedules.

No account connection, billing job, model inference or canonical data is used.
Only the selected private ledger is read, with SQLite query_only enabled.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import uuid
from contextlib import closing, contextmanager
from pathlib import Path

from ai import tracking_bao as bao, tracking_ticket_seed as seeds
from ai.prediction_ledger import EFFECTIVENESS_SYSTEM_ACTOR

GAMES = {'LOTO_5_35': ('5/35', 35, 5), 'LOTO_6_45': ('Mega 6/45', 45, 6),
         'LOTO_6_55': ('Power 6/55', 55, 6)}
METHODS = {'web': 'Pipeline web', 'random': 'Ngẫu nhiên', 'bayesian': 'Bayesian', 'ewma': 'EWMA'}


def normalize_seed(value):
    value = str(value or '').strip().lower()
    if not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError('Nhập đầy đủ mã seed 64 ký tự hex; không dùng mã rút gọn dưới vé.')
    return value


@contextmanager
def readonly(database):
    path = Path(database).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError('Đường dẫn database phải là một tệp đã tồn tại.')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        yield connection


def select_database(runtime, *, owner=None, database=None):
    """Never choose an arbitrary owner when there are several private ledgers."""
    if owner and database:
        raise ValueError('Chọn --owner hoặc --db, không dùng cả hai.')
    if database is not None:
        path = Path(database).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError('Không tìm thấy tệp database đã chọn.')
        return path
    runtime = Path(runtime).resolve()
    folder = runtime / 'personal_tracking'
    candidates = []
    if folder.is_dir():
        for path in folder.glob('*/tracking.db'):
            try:
                valid_id = str(uuid.UUID(path.parent.name)) == path.parent.name
            except ValueError:
                valid_id = False
            resolved = path.resolve()
            if valid_id and resolved.is_file() and resolved.is_relative_to(folder.resolve()):
                candidates.append(resolved)
    if owner:
        accounts = runtime / 'lotto_web.db'
        if not accounts.is_file():
            raise ValueError('Không có DB tài khoản để tra --owner; có thể chọn --db trực tiếp.')
        with readonly(accounts) as connection:
            row = connection.execute('SELECT id FROM personal_tracking_accounts WHERE username=?', (owner,)).fetchone()
        chosen = next((path for path in candidates if row and path.parent.name == row['id']), None)
        if chosen is None:
            raise ValueError('Không tìm thấy danh mục theo dõi của tài khoản đã chọn.')
        return chosen
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError('Chưa có DB theo dõi cá nhân. Dùng --db để chọn DB đã chứa các vé có seed.')
    raise ValueError('Có nhiều tài khoản. Dùng --owner TEN_DANG_NHAP hoặc --db DUONG_DAN để chọn đúng danh mục.')


def _schedules(database, game, draw, method):
    if game is not None and game not in GAMES:
        raise ValueError('Chỉ hỗ trợ seed mới của 5/35, Mega 6/45 và Power 6/55.')
    if method is not None and method not in METHODS:
        raise ValueError('Phương pháp phải là web, random, bayesian hoặc ewma.')
    if draw is not None and not re.fullmatch(r'[1-9][0-9]*', str(draw)):
        raise ValueError('Mã kỳ phải là số nguyên dương.')
    where, arguments = [], []
    for field, value in [('game_type', game), ('target_draw_id', str(draw) if draw is not None else None)]:
        if value is not None:
            where.append(field + '=?'); arguments.append(value)
    with readonly(database) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'effectiveness_cycles', 'effectiveness_predictions', 'prediction_runs'} <= tables:
            return [], 0, []
        rows = connection.execute('SELECT cycle_id,game_type,target_draw_id,config_json FROM effectiveness_cycles' +
                                  (' WHERE ' + ' AND '.join(where) if where else '') +
                                  ' ORDER BY created_at DESC,cycle_id DESC', arguments).fetchall()
    catalog, legacy, warnings = [], 0, []
    for row in rows:
        config = json.loads(row['config_json'])
        if not isinstance(config, dict):
            raise ValueError('Cấu hình bộ vé đã lưu không hợp lệ.')
        schedules = config.get('ticketSeedSchedules')
        if not schedules:
            legacy += 1
            continue
        if not isinstance(schedules, dict):
            raise ValueError('Lịch seed trong cấu hình đã lưu không hợp lệ.')
        for key, spec in schedules.items():
            if method is not None and key != method:
                continue
            if not isinstance(spec, dict):
                raise ValueError('Thiếu thông tin lịch seed của phương pháp.')
            if spec.get('version') != seeds.VERSION:
                warnings.append(f"Kỳ {row['target_draw_id']} / {key}: chưa hỗ trợ phiên bản seed {spec.get('version')}.")
                continue
            kind, count = spec.get('ticketClass'), spec.get('selectionCount')
            maximum = math.comb(GAMES[row['game_type']][1], GAMES[row['game_type']][2]) if row['game_type'] in GAMES else 0
            valid = (row['game_type'] in GAMES and key in METHODS and kind in ('normal', 'bao') and
                     type(count) is int and 1 <= count <= min(1000000, maximum) and
                     spec.get('type') == row['game_type'] and spec.get('method') == key and
                     spec.get('targetDrawId') == row['target_draw_id'] and
                     kind == config.get('playMode', 'normal') and
                     count == config.get('baoCount' if kind == 'bao' else 'actualTicketCount') and
                     isinstance(spec.get('rootSeed'), str) and re.fullmatch(r'[0-9]{1,80}', spec['rootSeed']))
            if not valid or kind == 'bao' and spec.get('baoLevel') != config.get('baoLevel'):
                raise ValueError('Ngữ cảnh/số lượng seed không khớp với bộ vé đã khóa.')
            catalog.append({'cycleId': row['cycle_id'], 'type': row['game_type'], 'targetDrawId': row['target_draw_id'],
                            'method': key, 'schedule': spec, 'config': config})
    return catalog, legacy, warnings


def _record(database, item, index):
    with readonly(database) as connection:
        connection.execute('BEGIN')
        row = connection.execute('''SELECT ep.prediction_id,pr.game_type,pr.username,pr.payload_checksum,
                json_extract(pr.payload_json,'$.ticketClass') ticket_class,
                json_extract(pr.payload_json,'$.ticketSeedSchedule') schedule,
                json_extract(pr.payload_json,'$.probabilities') probabilities
            FROM effectiveness_predictions ep JOIN prediction_runs pr ON pr.prediction_id=ep.prediction_id
            WHERE ep.cycle_id=? AND ep.method=?''', (item['cycleId'], item['method'])).fetchone()
        spec = item['schedule']
        if (row is None or row['game_type'] != item['type'] or row['username'] != EFFECTIVENESS_SYSTEM_ACTOR or
                row['ticket_class'] != spec['ticketClass'] or json.loads(row['schedule'] or 'null') != spec):
            raise ValueError('Payload/seed không khớp với cấu hình đã khóa; chưa thể xác nhận vé.')
        if spec['ticketClass'] == 'bao':
            selected = connection.execute("SELECT json_extract(payload_json,?) FROM prediction_runs WHERE prediction_id=?",
                                          (f'$.bao.parents[{index - 1}]', row['prediction_id'])).fetchone()
        else:
            tables = {entry[0] for entry in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            chunk = connection.execute('SELECT chunk_size FROM effectiveness_ticket_index WHERE prediction_id=?',
                                       (row['prediction_id'],)).fetchone() if 'effectiveness_ticket_index' in tables else None
            if chunk and chunk['chunk_size']:
                size = chunk['chunk_size']
                selected = connection.execute('SELECT json_extract(tickets_json,?) FROM effectiveness_ticket_chunks WHERE prediction_id=? AND chunk_number=?',
                                              (f'$[{(index - 1) % size}]', row['prediction_id'], (index - 1) // size)).fetchone()
            else:
                selected = connection.execute('SELECT json_extract(tickets_json,?) FROM prediction_runs WHERE prediction_id=?',
                                              (f'$[{index - 1}]', row['prediction_id'])).fetchone()
        if not selected or not selected[0]:
            raise ValueError('Không đủ dữ liệu vé đã lưu tại vị trí tìm thấy.')
        selection = json.loads(selected[0])
        if spec['ticketClass'] == 'bao' and selection.get('parentIndex') != index:
            raise ValueError('Số thứ tự Bao không khớp dữ liệu đã khóa.')
        return dict(row), selection


def _fingerprint_reason(config, kind):
    source = config.get('sourceManifest') or {}
    if not isinstance(source, dict):
        return 'Manifest nguồn đã lưu không hợp lệ; chỉ trả bộ số đã lưu.'
    manifest = {str(key).replace('\\', '/'): value for key, value in source.items()}
    files = {'ai/tracking_ticket_seed.py': Path(seeds.__file__)}
    if kind == 'bao':
        files.update({'ai/tracking_bao.py': Path(bao.__file__),
                      'config/tracking-bao-packing-v2.json': bao.PLAN_PATH})
    for key, path in files.items():
        if key not in manifest:
            continue
        try:
            current = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return 'Không đọc được mã nguồn/template để tái lập: ' + key + '. Chỉ trả bộ số đã lưu.'
        if current != manifest[key]:
            return 'Mã nguồn/template đã đổi so với lúc sinh vé: ' + key + '. Chỉ trả bộ số đã lưu.'
    return None


def _selection(value):
    if not isinstance(value, dict) or not isinstance(value.get('main'), list):
        raise ValueError('Bộ số đã lưu không hợp lệ.')
    if any(type(number) is not int for number in value['main']) or (value.get('special') is not None and type(value['special']) is not int):
        raise ValueError('Các giá trị bộ số đã lưu không hợp lệ.')
    return {'main': value['main'], 'special': value.get('special')}


def _replay(item, record, stored, index):
    spec = item['schedule']
    reason = _fingerprint_reason(item['config'], spec['ticketClass'])
    if reason:
        return {'status': 'unavailable', 'matchesStored': None, 'reason': reason}
    try:
        probabilities = json.loads(record['probabilities'] or 'null')
        if not isinstance(probabilities, dict):
            raise ValueError('Thiếu vector xác suất gốc để tái lập.')
        universe, size = GAMES[item['type']][1:]
        numeric = {int(key): value for key, value in probabilities.items()}
        if (set(numeric) != set(range(1, universe + 1)) or
                any(type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1 for value in numeric.values()) or
                abs(sum(numeric.values()) - size) > 1e-5):
            raise ValueError('Vector xác suất gốc không hợp lệ.')
        source = {'type': item['type'], 'probabilities': probabilities}
        if spec['ticketClass'] == 'bao':
            source['tickets'] = [{'main': spec['sourceMain'], 'special': spec['sourceSpecial']}]
            replayed = bao.build(source, item['type'], spec['baoLevel'], spec['selectionCount'],
                                 math.comb(35, 5) if item['type'] == 'LOTO_5_35' else 1000000,
                                 seed_schedule=spec)['bao']['parents'][index - 1]
        else:
            replayed = seeds.normal(source, item['type'], spec, spec['selectionCount'])['tickets'][index - 1]
        matches = _selection(replayed) == _selection(stored)
        return {'status': 'verified' if matches else 'mismatch', 'matchesStored': matches,
                'selection': _selection(replayed),
                **({'reason': 'Kết quả tái lập khác bộ số đã lưu; chưa xác nhận khớp.'} if not matches else {})}
    except (ValueError, KeyError, TypeError, ArithmeticError) as error:
        return {'status': 'unavailable', 'matchesStored': None, 'reason': str(error)}


def lookup(seed, database, *, game=None, draw=None, method=None, replay=True, progress=None):
    """Search metadata in one chosen ledger; report all matches, never a fake decode."""
    seed = normalize_seed(seed)
    catalog, legacy, warnings = _schedules(database, game, draw, method)
    total = sum(item['schedule']['selectionCount'] for item in catalog)
    scanned, matches = 0, []
    for item in catalog:
        spec = item['schedule']
        prefix = seeds._prefix(spec)
        for index in range(1, spec['selectionCount'] + 1):
            scanned += 1
            if progress and (scanned == 1 or scanned % 100000 == 0):
                progress({'phase': 'search', 'scanned': scanned, 'total': total})
            if hashlib.sha256(prefix + str(index).encode('ascii')).hexdigest() != seed:
                continue
            record, stored = _record(database, item, index)
            if progress:
                progress({'phase': 'replay' if replay else 'found', 'type': item['type'],
                          'draw': item['targetDrawId'], 'method': item['method'], 'index': index})
            result = {'cycleId': item['cycleId'], 'predictionId': record['prediction_id'],
                      'type': item['type'], 'label': GAMES[item['type']][0], 'targetDrawId': item['targetDrawId'],
                      'method': item['method'], 'methodLabel': METHODS[item['method']],
                      'ticketClass': spec['ticketClass'], 'baoLevel': spec.get('baoLevel'), 'index': index,
                      'rootSeed': spec['rootSeed'], 'seedVersion': spec['version'], 'selection': _selection(stored),
                      'payloadChecksum': record['payload_checksum']}
            result['replay'] = _replay(item, record, stored, index) if replay else {'status': 'skipped', 'matchesStored': None}
            matches.append(result)
            break
    return {'ok': True, 'status': 'found' if matches else 'not_found', 'seed': seed, 'matches': matches,
            'ambiguous': len(matches) > 1, 'searchedSchedules': len(catalog), 'searchedSeeds': scanned,
            'legacyCyclesWithoutSeeds': legacy, 'warnings': list(dict.fromkeys(warnings))}
