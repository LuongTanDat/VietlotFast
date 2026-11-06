"""Daily interest on the card balance just before midnight in Vietnam.

The CLI previews by default. --apply activates once and settles closed days.
No interest is backdated before activation; read APIs never run this module.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai import account_card as cards
from ai.configs import data_paths as dp

NS = 1_000_000_000
DAY = 86400 * NS
OFFSET = 7 * 3600 * NS
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
PREFIX = 'card_interest:'
VERSION = 'card_daily_interest_v1'
DENOMINATOR = 4000  # 0.025% = 1 / 4000


def timestamp_ns(value):
    """Keep all nine digits emitted by Java Instant; no floating point dates."""
    match = re.fullmatch(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?(Z|[+-]\d\d:\d\d)', value)
    if not match:
        raise ValueError('Thời gian chứng từ thẻ không hợp lệ.')
    stamp = datetime.fromisoformat(match[1] + match[3].replace('Z', '+00:00')).astimezone(timezone.utc) - EPOCH
    return (stamp.days * 86400 + stamp.seconds) * NS + int((match[2] or '').ljust(9, '0'))


def iso(value):
    seconds, fraction = divmod(value, NS)
    return (EPOCH + timedelta(seconds=seconds)).strftime('%Y-%m-%dT%H:%M:%S') + f'.{fraction:09d}Z'


def policy():
    file = dp.PROJECT_ROOT / 'config/card-interest.json'
    return json.loads(file.read_text(encoding='utf-8')) if file.is_file() else {'enabled': False}


def validate_policy(value):
    if value.get('version') != VERSION or value.get('method') != 'midnight_balance' or value.get('dailyDenominator') != DENOMINATOR or value.get('timeZone') != 'Asia/Ho_Chi_Minh':
        raise ValueError('Chính sách lãi suất thẻ không hợp lệ; chưa cộng lãi.')


def schema(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS card_interest_policy (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), version TEXT NOT NULL,
            activated_ns TEXT NOT NULL, method TEXT NOT NULL, denominator INTEGER NOT NULL, timezone TEXT NOT NULL,
            activation_rowid INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS card_interest_state (
            account_id TEXT PRIMARY KEY, cursor_ns TEXT NOT NULL, opening_balance TEXT NOT NULL,
            last_rowid INTEGER NOT NULL, remainder INTEGER NOT NULL CHECK(remainder>=0 AND remainder<4000));
        CREATE TABLE IF NOT EXISTS card_interest_days (
            account_id TEXT NOT NULL, business_date TEXT NOT NULL, version TEXT NOT NULL,
            period_start_ns TEXT NOT NULL, period_end_ns TEXT NOT NULL,
            opening_balance TEXT NOT NULL, closing_balance TEXT NOT NULL,
            remainder_before INTEGER NOT NULL, interest_amount INTEGER NOT NULL,
            remainder_after INTEGER NOT NULL, event_id TEXT NOT NULL UNIQUE, posted_at TEXT NOT NULL,
            PRIMARY KEY(account_id,business_date));
        CREATE TRIGGER IF NOT EXISTS card_interest_policy_no_update BEFORE UPDATE ON card_interest_policy
            BEGIN SELECT RAISE(ABORT,'Immutable interest policy'); END;
        CREATE TRIGGER IF NOT EXISTS card_interest_policy_no_delete BEFORE DELETE ON card_interest_policy
            BEGIN SELECT RAISE(ABORT,'Immutable interest policy'); END;
        CREATE TRIGGER IF NOT EXISTS card_interest_days_no_update BEFORE UPDATE ON card_interest_days
            BEGIN SELECT RAISE(ABORT,'Immutable daily interest'); END;
        CREATE TRIGGER IF NOT EXISTS card_interest_days_no_delete BEFORE DELETE ON card_interest_days
            BEGIN SELECT RAISE(ABORT,'Immutable daily interest'); END;
    ''')


def owners(db):
    return db.execute("SELECT c.*,i.username FROM account_cards c JOIN account_identities i ON i.account_id=c.account_id "
                      "JOIN users u ON u.username=i.username WHERE i.deleted_at='' AND c.currency='PayPal' ORDER BY c.account_id").fetchall()


def baseline(db, card, now):
    balance = card['balance']
    if type(balance) is not int or not 0 <= balance <= cards.MAX_SAFE:
        raise ValueError('Số dư thẻ không hợp lệ.')
    rowid = db.execute('SELECT COALESCE(MAX(rowid),0) FROM card_transactions WHERE account_id=?', (card['account_id'],)).fetchone()[0]
    return [str(now), str(balance), rowid, 0]


def activate(db, now, realtime=False):
    db.execute('BEGIN IMMEDIATE')
    try:
        row = db.execute('SELECT * FROM card_interest_policy').fetchone()
        if row:
            if (row['version'], row['method'], row['denominator'], row['timezone']) != (VERSION, 'midnight_balance', DENOMINATOR, 'Asia/Ho_Chi_Minh'):
                raise ValueError('Chính sách lãi suất đã lưu không khớp.')
            db.commit()
            return int(row['activated_ns']), row['activation_rowid'], False
        if realtime:
            now = time.time_ns()
        watermark = db.execute('SELECT COALESCE(MAX(rowid),0) FROM card_transactions').fetchone()[0]
        db.execute('INSERT INTO card_interest_policy VALUES(1,?,?,?,?,?,?)', (VERSION, str(now), 'midnight_balance', DENOMINATOR, 'Asia/Ho_Chi_Minh', watermark))
        for card in owners(db):
            db.execute('INSERT INTO card_interest_state VALUES(?,?,?,?,?)', (card['account_id'], *baseline(db, card, now)))
        db.commit()
        return now, watermark, True
    except BaseException:
        db.rollback()
        raise


def settle_account(db, account_id, activated, watermark, now, apply, realtime=False):
    """One account transaction locks out both Java transfers and Python rewards."""
    db.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
    try:
        card = db.execute("SELECT c.*,i.username FROM account_cards c JOIN account_identities i ON i.account_id=c.account_id "
                          "JOIN users u ON u.username=i.username WHERE c.account_id=? AND i.deleted_at='' AND c.currency='PayPal'", (account_id,)).fetchone()
        if card is None:
            db.rollback()
            return {'days': 0, 'credited': 0, 'amount': 0}
        if realtime:
            # A transfer may have committed while we waited for the write lock.
            # Capture the clock after establishing this account's DB snapshot.
            now = time.time_ns()
        state = db.execute('SELECT * FROM card_interest_state WHERE account_id=?', (account_id,)).fetchone()
        if state:
            cursor, opening, last, remainder = int(state['cursor_ns']), int(state['opening_balance']), state['last_rowid'], state['remainder']
        else:
            created = timestamp_ns(card['created_at'])
            # A new card starts from its first recorded credit. Old imported cards
            # without a checkpoint start now rather than guessing past balances.
            older = db.execute('SELECT 1 FROM card_transactions WHERE account_id=? AND rowid<=? LIMIT 1', (account_id, watermark)).fetchone()
            cursor, opening, last, remainder = (max(created, activated), 0, 0, 0) if created >= activated or older is None else tuple(map(int, baseline(db, card, now)))
        if cursor > now or opening < 0 or not 0 <= remainder < DENOMINATOR:
            raise ValueError('Mốc chốt lãi chưa hợp lệ hoặc đồng hồ máy chủ đi lùi.')
        physical = card['balance']
        if type(physical) is not int or not 0 <= physical <= cards.MAX_SAFE:
            raise ValueError('Số dư thẻ vượt giới hạn.')
        raw = db.execute('SELECT rowid,amount,created_at,currency FROM card_transactions WHERE account_id=? AND rowid>? '
                         'AND substr(source_key,1,14)<>? ORDER BY rowid', (account_id, last, PREFIX)).fetchall()
        events, previous = [], cursor
        for event in raw:
            if event['currency'] != 'PayPal' or type(event['amount']) is not int:
                raise ValueError('Đơn vị chứng từ không khớp số dư thẻ.')
            at = timestamp_ns(event['created_at'])
            if at > now:
                raise ValueError('Chờ đồng hồ máy chủ khớp thời gian chứng từ thẻ.')
            previous = max(previous, at)
            events.append((event['rowid'], event['amount'], previous))
        if opening + sum(event[1] for event in events) != physical:
            raise ValueError('Số dư thẻ không khớp sổ giao dịch; chưa cộng lãi.')
        days = credited = total = position = 0
        while days < 31:
            end = ((cursor + OFFSET) // DAY + 1) * DAY - OFFSET
            if end > now:
                break
            closing = opening
            while position < len(events) and events[position][2] < end:
                last, delta, _ = events[position]
                closing += delta
                if closing < 0:
                    raise ValueError('Chứng từ thẻ làm số dư âm trước mốc chốt.')
                position += 1
            amount, rest = divmod(closing + remainder, DENOMINATOR)
            if physical + amount > cards.MAX_SAFE:
                raise ValueError('Số dư thẻ chưa đủ chỗ nhận lãi; sẽ thử lại sau.')
            day = (EPOCH + timedelta(seconds=(end - 1 + OFFSET) // NS)).date().isoformat()
            event_id = PREFIX + account_id + ':' + day
            if apply:
                if db.execute('SELECT 1 FROM card_interest_days WHERE account_id=? AND business_date=?', (account_id, day)).fetchone():
                    raise ValueError('Biên nhận lãi đã có nhưng mốc chốt không khớp.')
                if amount:
                    details = {'label': 'Lãi suất thẻ', 'description': 'Ngày ' + day + ' · +0.025%/ngày · Số dư chốt: ' + f'{closing:,}'.replace(',', '.') + ' PayPal',
                               'interestDate': day, 'closingBalance': str(closing), 'rateDenominator': DENOMINATOR}
                    if not cards.credit(db, account_id, 'PayPal', amount, event_id, 'reward', day, details):
                        raise ValueError('Khoản lãi đã có nhưng thiếu biên nhận ngày.')
                    audit = {'id': event_id, 'date': day, 'paypal': amount, 'cardAccountId': account_id,
                             'closingBalance': str(closing), 'cardBefore': physical, 'cardAfter': physical + amount}
                    db.execute('INSERT INTO account_audit VALUES(?,?,?,?,?,?)',
                               (event_id, card['username'], card['username'], 'card_interest', json.dumps(audit, ensure_ascii=False, separators=(',', ':')), iso(now)))
                db.execute('INSERT INTO card_interest_days VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                           (account_id, day, VERSION, str(cursor), str(end), str(opening), str(closing), remainder, amount, rest, event_id, iso(now)))
            days += 1
            credited += bool(amount)
            total += amount
            physical += amount
            cursor, opening, remainder = end, closing + amount, rest
        if apply:
            db.execute('INSERT INTO card_interest_state VALUES(?,?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET '
                       'cursor_ns=excluded.cursor_ns,opening_balance=excluded.opening_balance,last_rowid=excluded.last_rowid,remainder=excluded.remainder',
                       (account_id, str(cursor), str(opening), last, remainder))
            db.commit()
        else:
            db.rollback()
        return {'days': days, 'credited': credited, 'amount': total}
    except BaseException:
        db.rollback()
        raise


def settle(db_path=None, *, apply=False, now_ns=None, settings=None):
    settings = policy() if settings is None else settings
    if settings.get('enabled') is not True:
        return {'ok': True, 'status': 'disabled', 'credited': 0}
    validate_policy(settings)
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise ValueError('Thời gian chốt lãi không hợp lệ.')
    path = Path(db_path or dp.RUNTIME_DIR / 'lotto_web.db').resolve()
    if not path.is_file():
        raise ValueError('Không tìm thấy DB tài khoản hiện có.')
    with closing(sqlite3.connect(path.as_uri() + ('?mode=rw' if apply else '?mode=ro'), uri=True, isolation_level=None, timeout=30)) as db:
        db.row_factory = sqlite3.Row
        if not apply:
            db.execute('PRAGMA query_only=ON')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'account_cards', 'card_transactions', 'account_identities', 'users', 'account_audit'} <= tables:
            raise ValueError('DB chưa có sổ thẻ đầy đủ.')
        if apply:
            schema(db)
            activated, watermark, fresh = activate(db, now, realtime=now_ns is None)
        else:
            row = db.execute('SELECT * FROM card_interest_policy').fetchone() if 'card_interest_policy' in tables else None
            if row is None:
                return {'ok': True, 'status': 'activation_required', 'credited': 0, 'preview': True}
            if (row['version'], row['method'], row['denominator'], row['timezone']) != (VERSION, 'midnight_balance', DENOMINATOR, 'Asia/Ho_Chi_Minh'):
                raise ValueError('Chính sách lãi suất đã lưu không khớp.')
            activated, watermark, fresh = int(row['activated_ns']), row['activation_rowid'], False
        report = {'ok': True, 'status': 'active', 'activated': fresh, 'activatedAt': iso(activated), 'preview': not apply,
                  'processedDays': 0, 'credited': 0, 'creditedPayPal': 0, 'errors': []}
        for card in owners(db):
            try:
                item = settle_account(db, card['account_id'], activated, watermark, now, apply, realtime=now_ns is None)
                report['processedDays'] += item['days']
                report['credited'] += item['credited']
                report['creditedPayPal'] += item['amount']
            except (sqlite3.Error, ValueError, OverflowError) as error:
                report['errors'].append({'accountId': card['account_id'], 'reason': str(error)})
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        result = settle(apply=args.apply)
    except (sqlite3.Error, OSError, ValueError) as error:
        result = {'ok': False, 'status': 'error', 'message': str(error)}
    payload = json.dumps(result, ensure_ascii=False, separators=(',', ':'))
    if args.output:
        args.output.write_text(payload + '\n', encoding='utf-8')
    print(payload)
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
