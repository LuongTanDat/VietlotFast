"""Bounded standard-game result refresh before prospective tracking work.

Fetch only overdue draw dates. Never repair history, fit models, export scores,
or advance a forecast past a missing canonical result.
"""
from datetime import datetime, timedelta
import json
import os
import uuid

from backend import live_results as live
from backend.file_guard import resource_lock

POLL_SECONDS = 55
POLL_TIMEOUT = (4, 12)


def _next(game, at):
    if game == 'LOTO_5_35':
        return at.replace(hour=21) if at.hour == 13 else (at + timedelta(days=1)).replace(hour=13)
    weekdays = {'LOTO_6_45': (2, 4, 6), 'LOTO_6_55': (1, 3, 5)}[game]
    candidate = (at + timedelta(days=1)).replace(hour=18, minute=0)
    while candidate.weekday() not in weekdays:
        candidate += timedelta(days=1)
    return candidate


def _page(session, game, day):
    # Avoid the full live-results CLI (it also exports scores/trains models).
    url = live.HISTORY_URL_PATTERNS[game].format(date=live.format_minhchinh_date(day))
    response = live.request_with_retry(session, 'get', url, allow_404=True,
                                       retry_count=0, timeout=POLL_TIMEOUT)
    if response is None:
        return []
    return live.parse_history_results(live.LIVE_TYPES[game], live.html_to_lines(response.text), url, day)


def _row_at(row, game, pe):
    return pe._draw_at({'date': row['Ngay'], 'time': row.get('Time')}, game)


def _merge(game, fetched, now, pe):
    path = live.dp.get_canonical_csv_write_path(game)
    for attempt in range(3):
        rows, _, _ = live.load_canonical_rows(game, rewrite_if_needed=False)
        added = set()
        for result in fetched:
            identity = result['ky']
            row = live.result_to_csv_row(result)
            previous = rows.get(identity)
            if previous is not None:
                old_main = sorted(int(n) for n in previous['Main'].split(','))
                old_special = int(previous['Special']) if previous.get('Special') else None
                if (old_main != sorted(result['main']) or old_special != result.get('special')
                        or _row_at(previous, game, pe) != _row_at(row, game, pe)):
                    raise ValueError(f'Nguồn và CSV mâu thuẫn ở kỳ {identity}; giữ nguyên dữ liệu để kiểm tra.')
                continue
            rows[identity] = row
            added.add(identity)
        ordered = sorted(rows, key=int)
        for before, after in zip(ordered, ordered[1:]):
            if before not in added and after not in added:
                continue
            if (int(after) != int(before) + 1
                    or _row_at(rows[after], game, pe) != _next(game, _row_at(rows[before], game, pe))):
                raise ValueError('Kết quả mới thiếu kỳ hoặc không khớp thứ tự ngày/giờ; chưa khóa kỳ xa hơn.')
        if added:
            try:
                live.write_canonical_rows(game, rows, now.date())
            except RuntimeError as error:
                if 'CSV changed' not in str(error) or attempt == 2:
                    raise
                continue
            meta = live.read_canonical_meta(game)
            meta['lastSyncAt'] = now.isoformat(timespec='seconds')
            if game == 'LOTO_5_35':
                meta['prizeSharing'] = live.build_loto535_prize_sharing_meta(rows)
            meta['prizeWinners'] = live.build_prize_winner_meta(game, rows)
            live.write_canonical_meta(game, meta)
        latest = rows[ordered[-1]]
        return {'status': 'updated' if added else 'waiting_result', 'newRows': len(added),
                'latestKy': latest['Ky'], 'latestDate': latest['Ngay'], 'latestTime': latest.get('Time', '')}


def refresh(game, now=None, pending=()):
    from ai import prediction_effectiveness as pe, tracking_progress as progress
    if game not in pe.GAMES:
        raise ValueError('Loại xổ số không hỗ trợ cập nhật nhanh.')
    now = (now or pe._now()).astimezone(pe.LOCAL_TZ)
    state_path = live.dp.RUNTIME_DIR / f'prospective_source_{game.lower()}.json'
    with resource_lock(state_path, timeout=1):
        snapshot = pe._snapshot(game)
        dates = []
        if snapshot['deadline'] <= now:
            dates.append(snapshot['deadline'].date())
        for target in pending:
            at = datetime.fromisoformat(target['deadline'])
            if at <= now and str(target['target_draw_id']) not in snapshot['actual'] and at.date() not in dates:
                dates.append(at.date())
        if not dates:
            return {'status': 'up_to_date', 'latestKy': snapshot['cutoff'], 'error': ''}
        try:
            state = json.loads(state_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            state = {}
        if state.get('lastAttempt'):
            age = (now - datetime.fromisoformat(state['lastAttempt'])).total_seconds()
            if 0 <= age < POLL_SECONDS:
                return state
        stamp = now.isoformat(timespec='seconds')
        progress.start('updating')
        try:
            fetched = {}
            with live.create_session() as session:
                for day in dates[:2]:
                    for raw in _page(session, game, day):
                        result = dict(raw)
                        identity = str(result.get('ky', ''))
                        if result.get('key') != game or not identity.isdigit() or int(identity) < 1:
                            raise ValueError('Nguồn trả sai loại xổ số hoặc mã kỳ.')
                        pe._validate_actual_row(result, game)
                        at = pe._draw_at(result, game)
                        if at.date() != day or at > now:
                            raise ValueError('Ngày/giờ kết quả từ nguồn không khớp hoặc ở tương lai.')
                        result['ky'] = str(int(identity))
                        if result['ky'] in fetched and fetched[result['ky']] != result:
                            raise ValueError('Nguồn trả nhiều kết quả khác nhau cho cùng kỳ.')
                        fetched[result['ky']] = result
            result = _merge(game, list(fetched.values()), now, pe)
            state = {**result, 'lastAttempt': stamp, 'lastSuccess': stamp, 'error': ''}
        except Exception as error:
            state = {**state, 'status': 'error', 'lastAttempt': stamp, 'error': str(error)[:600]}
        temporary = state_path.with_name(state_path.name + '.' + uuid.uuid4().hex + '.tmp')
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, state_path)
        return state
