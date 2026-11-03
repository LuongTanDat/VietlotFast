"""Exactly-once wallet credits for paid, fully scored private portfolios.

The user-approved wallet reward is the displayed hypothetical VND payout,
converted at 5/4 and floored once per purchased cycle. Viewing reports is read-only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from ai import account_statistics as stats
from ai import personal_tracking as billing
from ai import prediction_ledger as ledger
from ai import account_card as cards

VERSION = 'prediction_wallet_reward_v1'


def schema(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS prediction_payouts (
            account_id TEXT NOT NULL, cycle_id TEXT NOT NULL, charge_id TEXT NOT NULL UNIQUE,
            game_type TEXT NOT NULL, target_draw_id TEXT NOT NULL,
            reward_vnd INTEGER NOT NULL CHECK(reward_vnd>=0),
            paypal_credit INTEGER NOT NULL CHECK(paypal_credit>=0),
            calculation_json TEXT NOT NULL, calculation_hash TEXT NOT NULL,
            created_at TEXT NOT NULL, event_id TEXT NOT NULL,
            PRIMARY KEY(account_id,cycle_id));
        CREATE TRIGGER IF NOT EXISTS prediction_payout_immutable_update
            BEFORE UPDATE ON prediction_payouts BEGIN SELECT RAISE(ABORT,'Immutable payout'); END;
        CREATE TRIGGER IF NOT EXISTS prediction_payout_immutable_delete
            BEFORE DELETE ON prediction_payouts BEGIN SELECT RAISE(ABORT,'Immutable payout'); END;
    ''')


def _digest(value):
    return hashlib.sha256(ledger.canonical_json(value).encode()).hexdigest()


def _integer(value, positive=False):
    return type(value) is int and (value > 0 if positive else value >= 0) and value <= billing.MAX_SAFE


def _calculate(cycle, groups, receipt, charge, prizes, now):
    game = charge['game_type']
    levels = range(1, 11) if game == 'KENO' else (None,)
    if set(groups) != set(levels):
        raise ValueError('Chưa đủ các bậc/phương pháp đã chấm.')
    components, ticket_total, reward_total = [], 0, 0
    first = next(iter(groups.values()))[0]
    deadline, created = stats.stamp(first['deadline']), stats.stamp(first['created_at'])
    if deadline > now:
        raise ValueError('Chờ đến giờ quay và chấm kết quả.')
    if not stats.stamp(charge['created_at']) <= created < deadline or str(first['target_draw_id']) != str(charge['target_draw_id']):
        raise ValueError('Kỳ/giờ quay hoặc thời điểm khóa không hợp lệ.')
    for level in levels:
        rows = groups[level]
        if len(rows) != 4 or {r['method'] for r in rows} != set(stats.METHODS):
            raise ValueError('Chu kỳ chưa đủ bốn phương pháp.')
        common_actual = None
        counts_at_level = []
        for row in sorted(rows, key=lambda r: r['method']):
            if (row['status'] != 'scored' or row['cycle_id'] != cycle
                    or row['deadline'] != first['deadline'] or row['created_at'] != first['created_at']
                    or str(row['target_draw_id']) != str(charge['target_draw_id'])):
                raise ValueError('Chưa chấm đầy đủ hoặc nhận diện bộ vé không khớp.')
            if game == 'KENO':
                if row['cycle_status'] != 'scored':
                    raise ValueError('Keno chưa chấm đủ các bậc.')
                actual = json.loads(row['actual_json'])
            else:
                actual = {'main':json.loads(row['actual_main'] or '[]'), 'special':row['actual_special']}
            main = actual.get('main', [])
            size, maximum = (20, 80) if game == 'KENO' else (5, 35) if game == 'LOTO_5_35' else (6, 45 if game == 'LOTO_6_45' else 55)
            if len(main) != size or len(set(main)) != size or any(type(n) is not int or not 1 <= n <= maximum for n in main):
                raise ValueError('Bộ số thực tế đã ghi không hợp lệ.')
            special = actual.get('special')
            if game in ('KENO','LOTO_6_45') and special is not None:
                raise ValueError('Kết quả có số đặc biệt ngoài cơ cấu giải.')
            if game == 'LOTO_5_35' and (type(special) is not int or not 1 <= special <= 12):
                raise ValueError('Thiếu số đặc biệt đã chấm.')
            if game == 'LOTO_6_55' and (type(special) is not int or not 1 <= special <= 55 or special in main):
                raise ValueError('Thiếu bóng Power đã chấm.')
            identity = (tuple(sorted(main)), special)
            if common_actual is not None and identity != common_actual:
                raise ValueError('Các phương pháp có kết quả thực tế mâu thuẫn.')
            common_actual = identity
            ticket_count = row['ticket_count']
            summary = json.loads(row['summary_json'] or '{}')
            counts = summary.get('prizeCounts')
            if counts is None and game != 'KENO':
                counts = dict(Counter(r.get('prizeCode', 'UNKNOWN') for r in json.loads(row['legacy_results'] or '[]')))
            if (not _integer(ticket_count, True) or not isinstance(counts, dict)
                    or any(not _integer(count) for count in counts.values()) or sum(counts.values()) != ticket_count
                    or any(counts.get(key, 0) for key in ('UNKNOWN','PENDING','INVALID'))):
                raise ValueError('Số vé/giải chưa được phân loại đầy đủ.')
            if row['configured_count'] != ticket_count:
                raise ValueError('Số vé được chấm khác ngân sách đã khóa.')
            counts_at_level.append(ticket_count)
            units, method_reward = {}, 0
            for code, count in sorted(counts.items()):
                if code == 'NONE' or not count:
                    continue
                amount, missing, _, unknown = stats.reward_amount(game, {code:count}, actual, deadline,
                                                                 row['target_draw_id'], prizes, level)
                if missing or unknown or not _integer(amount) or amount % count:
                    raise ValueError('Chờ dữ liệu quỹ/số vé trúng đã đối chiếu cho ' + code + '.')
                units[code] = {'count':count, 'unitVnd':amount // count, 'amountVnd':amount}
                method_reward += amount
            ticket_total += ticket_count
            reward_total += method_reward
            components.append({'level':level, 'method':row['method'], 'tickets':ticket_count,
                               'actual':{'main':main,'special':special}, 'prizes':units, 'rewardVnd':method_reward})
        if len(set(counts_at_level)) != 1:
            raise ValueError('Ngân sách bốn phương pháp không khớp.')
    if (ticket_total != receipt['ticket_count'] or ticket_total != charge['ticket_count']
            or charge['paypal_cost'] != ticket_total * billing.UNIT_PAYPAL):
        raise ValueError('Số vé/biên nhận và khoản thu phí không khớp.')
    credit = reward_total * 5 // 4
    if not _integer(reward_total) or not _integer(credit):
        raise ValueError('Tiền thưởng vượt giới hạn số nguyên an toàn của ví.')
    calculation = {'version':VERSION, 'cycleId':cycle, 'chargeId':charge['id'], 'game':game,
                   'draw':str(charge['target_draw_id']), 'deadline':first['deadline'],
                   'rateNumerator':5, 'rateDenominator':4, 'rounding':'floor_per_cycle',
                   'ticketCount':ticket_total, 'rewardVnd':reward_total, 'paypal':credit,
                   'prizeContextHash':_digest(prizes.get(str(charge['target_draw_id']),{})),
                   'prizeContext':prizes.get(str(charge['target_draw_id']),{}), 'components':components}
    return {'cycleId':cycle, 'charge':charge, 'calculation':calculation, 'hash':_digest(calculation)}


def plan(scope, prizes=None, now=None):
    """Prepare without creating schemas, changing balances or opening generators."""
    now = now or datetime.now(timezone.utc)
    destination = cards.policy()
    with closing(stats.readonly(scope.account_db)) as db:
        billing._account(db, scope.account_id, scope.owner, enabled=False)
        card_id = cards.public_id(db,scope.owner) if destination['destination']=='card' else ''
        charges = {r['id']:dict(r) for r in db.execute(
            "SELECT * FROM prediction_charges WHERE account_id=? AND status='charged'", (scope.account_id,))}
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='prediction_payouts'").fetchone()
        paid = {r[0] for r in db.execute('SELECT cycle_id FROM prediction_payouts WHERE account_id=?', (scope.account_id,))} if exists else set()
    result = {'ready':[], 'waiting':[], 'alreadySettled':len(paid), 'rewardVnd':0, 'paypal':0}
    with closing(stats.readonly(scope.database)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='paid_cycle_receipts'").fetchone():
            return result
        receipts = {r['cycle_id']:dict(r) for r in db.execute('SELECT * FROM paid_cycle_receipts')
                    if r['cycle_id'] not in paid and r['charge_id'] in charges}
        games = {charges[r['charge_id']]['game_type'] for r in receipts.values()}
        grouped = defaultdict(lambda: defaultdict(list))
        for game in games:
            if game not in stats.GAMES:
                continue
            for level in range(1,11) if game == 'KENO' else (None,):
                for row in stats.simulation_rows(db, game, level or 10):
                    if row['cycle_id'] in receipts:
                        grouped[row['cycle_id']][level].append(dict(row))
    contexts = {}
    for cycle, receipt in receipts.items():
        charge = charges[receipt['charge_id']]
        game = charge['game_type']
        try:
            if game not in contexts:
                contexts[game] = prizes.get(game,{}) if prizes is not None else stats.keno_prizes.load_cache()['draws'] if game == 'KENO' else stats.canonical_prizes(game)
            item = _calculate(cycle, grouped[cycle], receipt, charge, contexts[game], now)
            item['calculation']['destination'] = {**destination,'cardAccountId':card_id}
            item['hash'] = _digest(item['calculation'])
            result['ready'].append(item)
        except (ValueError, TypeError, KeyError, OSError, IndexError) as error:
            result['waiting'].append({'cycleId':cycle, 'game':game, 'draw':charge['target_draw_id'], 'reason':str(error)})
    result['rewardVnd'] = sum(r['calculation']['rewardVnd'] for r in result['ready'])
    result['paypal'] = sum(r['calculation']['paypal'] for r in result['ready'])
    return result


def _credit(scope, item):
    calc, expected = item['calculation'], item['charge']
    if _digest(calc) != item['hash']:
        raise ValueError('Bản tính thưởng đã thay đổi.')
    destination = calc.get('destination',{'destination':'wallet','currency':'PayPal','cardAccountId':''})
    if {key:destination[key] for key in ('destination','currency')} != cards.policy():
        raise ValueError('Nơi nhận thưởng đã thay đổi. Cần lập lại bản tính.')
    with closing(billing.account_connection(scope.account_db)) as db:
        schema(db)
        cards.schema(db)
        db.execute('BEGIN IMMEDIATE')
        try:
            owner = billing._account(db, scope.account_id, enabled=False)
            if db.execute('SELECT 1 FROM prediction_payouts WHERE account_id=? AND cycle_id=?', (scope.account_id,calc['cycleId'])).fetchone():
                db.rollback(); return False
            charge = db.execute('SELECT * FROM prediction_charges WHERE id=? AND account_id=?', (expected['id'],scope.account_id)).fetchone()
            if charge is None or dict(charge) != expected or charge['status'] != 'charged':
                raise ValueError('Biên nhận thu phí đã thay đổi; chưa cộng thưởng.')
            to_card = destination['destination']=='card'
            card_id = cards.public_id(db,owner) if to_card else ''
            if card_id != destination.get('cardAccountId',''):
                raise ValueError('ID chủ thẻ đã thay đổi.')
            amount = calc['rewardVnd'] if to_card and destination['currency']=='VNĐ' else calc['paypal']
            event, stamp = 'prediction_reward:' + calc['chargeId'], ledger.now_iso()
            db.execute('INSERT INTO prediction_payouts VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (scope.account_id,calc['cycleId'],calc['chargeId'],calc['game'],calc['draw'],calc['rewardVnd'],calc['paypal'],
                        ledger.canonical_json(calc),item['hash'],stamp,event))
            db.execute('INSERT INTO prediction_payout_routes VALUES(?,?,?,?,?,?,?,?)',
                       (calc['chargeId'],scope.account_id,calc['cycleId'],destination['destination'],destination['currency'],amount,card_id,stamp))
            if calc['paypal']:
                details = {'id':calc['chargeId'], 'cycleId':calc['cycleId'], 'game':calc['game'], 'draw':calc['draw'],
                           'rewardVnd':calc['rewardVnd'], 'paypal':calc['paypal'], 'rateNumerator':5,'rateDenominator':4,
                           'calculationHash':item['hash']}
                if to_card:
                    label = {'LOTO_5_35':'Loto 5/35','LOTO_6_45':'Mega 6/45','LOTO_6_55':'Power 6/55'}.get(calc['game'],calc['game'])
                    if not cards.credit(db,card_id,destination['currency'],amount,event,'reward',calc['chargeId'],
                                        {'label':'Thưởng dự đoán','description':label+' · Kỳ #'+calc['draw'],**details}):
                        raise ValueError('Giao dịch thưởng trên thẻ đã tồn tại nhưng thiếu biên nhận.')
                    details.update(cardAccountId=card_id,cardCurrency=destination['currency'],cardAmount=amount)
                else:
                    wallet = billing._wallet(db, owner);balance = wallet.get('paypalBalance',0)
                    if type(balance) is not int or not -billing.MAX_SAFE <= balance <= billing.MAX_SAFE or not -billing.MAX_SAFE <= balance + calc['paypal'] <= billing.MAX_SAFE:
                        raise ValueError('Chưa thể cộng thưởng vì số dư vượt giới hạn.')
                    wallet['paypalBalance'] = balance + calc['paypal'];billing._save_wallet(db, owner, wallet)
                    details.update(balanceBefore=balance,balanceAfter=wallet['paypalBalance'])
                db.execute('INSERT INTO account_audit VALUES(?,?,?,?,?,?)',
                           (event,owner,owner,'prediction_card_reward' if to_card else 'prediction_reward',ledger.canonical_json(details),stamp))
            db.commit()
            return True
        except BaseException:
            db.rollback()
            raise


def settle(scope, apply=False, prizes=None, now=None):
    result = plan(scope, prizes, now)
    result.update(credited=0, creditedPayPal=0, duplicates=0, errors=[])
    if apply:
        for item in result['ready']:
            try:
                if _credit(scope, item):
                    result['credited'] += 1
                    result['creditedPayPal'] += item['calculation']['paypal']
                else:
                    result['duplicates'] += 1
            except (ValueError, sqlite3.Error) as error:
                result['errors'].append({'cycleId':item['cycleId'], 'reason':str(error)})
    return result


def summary(result):
    return {key:value for key,value in result.items() if key != 'ready'} | {'readyCycles':len(result['ready'])}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',help='Commit each verified payout once; default is read-only preview.')
    parser.add_argument('--owner')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    with closing(stats.readonly(ledger.DEFAULT_DB_PATH)) as db:
        rows=db.execute('SELECT id,username FROM personal_tracking_accounts WHERE (? IS NULL OR username=?)',(args.owner,args.owner)).fetchall()
    results=[]
    for row in rows:
        scope=billing.Scope(row['id'],row['username'])
        result=settle(scope,apply=args.apply)
        print(json.dumps(summary(result),ensure_ascii=False))
        results.append({'accountId':row['id'],**result})
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 1 if any(result['errors'] for result in results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
