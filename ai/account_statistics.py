"""Read-only account deposits and system simulation statistics, Vietnam time.

Never infer purchases from predictions, mutate a ledger, read whole portfolios,
or count sandbox/pending payments as money deposited.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai.configs import data_paths as dp
from ai.tracking_storage import database_path
from ai.prediction_ledger import SCORING_VERSION, EFFECTIVENESS_SYSTEM_ACTOR
from ai import keno_prize_context as keno_prizes

TZ = timezone(timedelta(hours=7))
GAMES = ("LOTO_5_35", "LOTO_6_45", "LOTO_6_55", "KENO")
METHODS = ("web", "random", "bayesian", "ewma")
MAX_SAFE = 9007199254740991
FIXED = {
    "LOTO_5_35": dict(FIRST=10000000, SECOND=5000000, THIRD=500000, FOURTH=100000, FIFTH=30000, CONSOLATION=10000),
    "LOTO_6_45": dict(FIRST=10000000, SECOND=300000, THIRD=30000),
    "LOTO_6_55": dict(FIRST=40000000, SECOND=500000, THIRD=50000),
}
KENO = {
    1: {1:20000}, 2:{2:90000}, 3:{2:20000,3:200000}, 4:{2:10000,3:50000,4:400000},
    5:{3:10000,4:150000,5:4400000}, 6:{3:10000,4:40000,5:450000,6:12500000},
    7:{3:10000,4:20000,5:100000,6:1200000,7:40000000},
    8:{0:10000,4:10000,5:50000,6:500000,7:5000000},
    9:{0:10000,4:10000,5:30000,6:150000,7:1500000,8:12000000},
    10:{0:10000,5:20000,6:80000,7:710000,8:8000000,9:150000000},
}
VARIABLE = {
    "LOTO_5_35": {"LOTTO_JACKPOT":("specialPrize", "Giải Đặc biệt (VNĐ)")},
    "LOTO_6_45": {"MEGA_JACKPOT":("jackpot", "Jackpot (VNĐ)")},
    "LOTO_6_55": {"POWER_JACKPOT_1":("jackpot1", "Jackpot 1 (VNĐ)"), "POWER_JACKPOT_2":("jackpot2", "Jackpot 2 (VNĐ)")},
}


def integer(value):
    return type(value) is int and 0 <= value <= MAX_SAFE


def stamp(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Thời gian giao dịch thiếu múi giờ.")
    return result.astimezone(TZ)


def period_bounds(period, anchor):
    if period == "all":
        return None, None
    if period == "day":
        return anchor, anchor + timedelta(days=1)
    if period == "week":
        start = anchor - timedelta(days=anchor.weekday())
        return start, start + timedelta(days=7)
    if period == "month":
        start = anchor.replace(day=1)
        return start, (start.replace(year=start.year+1, month=1) if start.month == 12 else start.replace(month=start.month+1))
    if period == "year":
        return date(anchor.year, 1, 1), date(anchor.year+1, 1, 1)
    raise ValueError("Khoảng thời gian không hợp lệ.")


def bucket_key(at, period):
    return at.strftime("%Y-%m-%dT%H:00") if period == "day" else at.strftime("%Y-%m") if period in ("all", "year") else at.strftime("%Y-%m-%d")


def empty_bucket(key):
    return dict(key=key, deposited=0, spent=0, reward=0, bought=0, won=0, scored=0, pending=0, drawPending=0, incomplete=0, unknownTickets=0)


def sum_totals(buckets):
    totals = empty_bucket('total')
    for bucket in buckets:
        for key in totals:
            if key != 'key':
                totals[key] += bucket[key]
    if any(not integer(value) for value in totals.values() if not isinstance(value, str)):
        raise ValueError("Tổng vượt giới hạn số nguyên an toàn của giao diện.")
    return totals


def readonly(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError("Không tìm thấy cơ sở dữ liệu thống kê.")
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("BEGIN")
    return connection


def canonical_prizes(game):
    if game == "KENO":
        return {}
    path = dp.get_canonical_csv_read_path(game)
    meta = dp.get_canonical_meta_read_path(game)
    if not path.is_file():
        return {}
    before = (path.stat().st_mtime_ns, path.stat().st_size, meta.stat().st_mtime_ns if meta.is_file() else 0)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = {str(int(row["Kỳ"])): row for row in csv.DictReader(handle)}
    evidence = json.loads(meta.read_text(encoding="utf-8-sig")).get("prizeWinners", {}).get("countsByDraw", {}) if meta.is_file() else {}
    after = (path.stat().st_mtime_ns, path.stat().st_size, meta.stat().st_mtime_ns if meta.is_file() else 0)
    if before != after:
        return {}
    for ky, row in rows.items():
        main = ",".join(str(int(value)) for value in row.get("Bộ Số", "").split(",") if value.strip())
        special = str(int(row["ĐB"])) if row.get("ĐB", "").strip() else ""
        identity = "|".join((row.get("Ngày", ""), row.get("Giờ", ""), main, special))
        item = evidence.get(ky, {})
        row["counts"] = item.get("counts", {}) if item.get("identity") == identity else {}
    return rows


def reward_amount(game, counts, actual, deadline, draw_id, prizes, selected_level=None):
    """Same independent hypothetical Jackpot convention as effectiveness UI."""
    reward, missing, won, unknown = 0, False, 0, 0
    for code, count in counts.items():
        if not count or code == "NONE":
            continue
        unit = FIXED.get(game, {}).get(code)
        if game == "KENO" and code.startswith("KENO_"):
            try:
                _, level, hits = code.split("_")
                if selected_level is not None and int(level) != selected_level:
                    unknown += count
                    missing = True
                    continue
                unit = KENO.get(int(level), {}).get(int(hits))
                valid_hits = {1:{1},2:{2},3:{2,3},4:{2,3,4},5:{3,4,5},6:{3,4,5,6},7:{3,4,5,6,7},8:{0,4,5,6,7,8},9:{0,4,5,6,7,8,9},10:{0,5,6,7,8,9,10}}
                if int(hits) not in valid_hits.get(int(level), set()):
                    unknown += count
                    missing = True
                    continue
                if int(level) in keno_prizes.NOMINAL and int(hits) == int(level):
                    context = keno_prizes.context_for(draw_id,actual,deadline,prizes)
                    winners = context.get('kenoWinnerCounts',{}).get(level)
                    unit = keno_prizes.unit_amount(int(level),winners,count)
            except ValueError:
                unknown += count
                missing = True
                continue
        elif code not in FIXED.get(game, {}) and code not in VARIABLE.get(game, {}):
            unknown += count
            missing = True
            continue
        won += count
        if code in VARIABLE.get(game, {}):
            field, column = VARIABLE[game][code]
            row = prizes.get(str(int(draw_id)))
            if row:
                try:
                    row_main = [int(v) for v in row["Bộ Số"].split(",")]
                    row_special = int(row["ĐB"]) if row.get("ĐB") else None
                    matches = (sorted(row_main) == sorted(actual.get("main", [])) and row_special == actual.get("special")
                               and row["Ngày"] == deadline.strftime("%d/%m/%Y")
                               and (row.get("Giờ") or ("18:00" if game != "LOTO_5_35" else "")) == deadline.strftime("%H:%M"))
                    pool = int(row[column])
                    winners = row["counts"].get(field)
                    if matches and integer(pool) and pool > 0 and integer(winners) and integer(winners + count):
                        unit = pool // (winners + count)
                except (KeyError, ValueError, TypeError):
                    pass
        if unit is None:
            missing = True
        else:
            reward += unit * count
    return reward, missing, won, unknown


def simulation_rows(connection, game, level):
    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if game == "KENO":
        if not {"keno_effectiveness_cycles", "keno_effectiveness_predictions", "keno_effectiveness_metrics", "prediction_runs"} <= tables:
            return []
        return connection.execute("""SELECT c.cycle_id,c.target_draw_id,c.created_at,c.deadline,c.status cycle_status,
            c.actual_json,ep.method,pr.status,km.ticket_count,km.summary_json,
            json_extract(c.config_json,'$.ticketCountsByLevel.' || ?) configured_count,
            json_extract(c.config_json,'$.ticketCount') requested_count
            FROM keno_effectiveness_cycles c JOIN keno_effectiveness_predictions ep ON ep.cycle_id=c.cycle_id
            JOIN prediction_runs pr ON pr.prediction_id=ep.prediction_id
            LEFT JOIN keno_effectiveness_metrics km ON km.cycle_id=c.cycle_id AND km.level=ep.level AND km.method=ep.method
            WHERE ep.level=? AND pr.username=? ORDER BY c.deadline,ep.method""", (str(level), level, EFFECTIVENESS_SYSTEM_ACTOR)).fetchall()
    if not {"effectiveness_cycles", "effectiveness_predictions", "prediction_runs", "prediction_scores"} <= tables:
        return []
    return connection.execute("""SELECT c.cycle_id,c.target_draw_id,c.created_at,c.deadline,ep.method,pr.status,
        json_extract(ps.metrics_json,'$.ticket_count') ticket_count,
        json_extract(ps.metrics_json,'$.report_summary') summary_json,
        json_extract(ps.metrics_json,'$.prize_results') legacy_results,
        json_extract(ps.metrics_json,'$.actual_main') actual_main,
        json_extract(ps.metrics_json,'$.actual_special') actual_special,
        json_extract(c.config_json,'$.actualTicketCount') configured_count,
        json_extract(c.config_json,'$.ticketCount') requested_count
        FROM effectiveness_cycles c JOIN effectiveness_predictions ep ON ep.cycle_id=c.cycle_id
        JOIN prediction_runs pr ON pr.prediction_id=ep.prediction_id
        LEFT JOIN prediction_scores ps ON ps.prediction_id=pr.prediction_id AND ps.scoring_version=?
        WHERE c.game_type=? AND pr.username=? ORDER BY c.deadline,ep.method""", (SCORING_VERSION, game, EFFECTIVENESS_SYSTEM_ACTOR)).fetchall()


def report(owner, game="LOTO_5_35", method="web", level=10, period="all", anchor=None, account_db=None, tracking_db=None, prizes=None):
    if game not in (*GAMES, 'all') or method not in (*METHODS, 'all') or type(level) is not int or not 1 <= level <= 10:
        raise ValueError("Loại xổ số, phương pháp hoặc bậc Keno không hợp lệ.")
    anchor = date.fromisoformat(anchor) if isinstance(anchor, str) else anchor or datetime.now(TZ).date()
    if not 2000 <= anchor.year <= 2100:
        raise ValueError("Chọn năm từ 2000 đến 2100.")
    start, end = period_bounds(period, anchor)
    previous_start, previous_end = period_bounds(period, start-timedelta(days=1)) if start else (None, None)
    buckets = {}
    previous_buckets = {}
    warnings = set()
    method_tickets = dict.fromkeys(METHODS, 0)
    method_wins = {name:dict(method=name,tickets=0,scored=0,unknownTickets=0) for name in METHODS}
    purchase_outcomes = {name:dict(method=name,tickets=0,won=0,scored=0,unknownTickets=0,pending=0) for name in METHODS}
    def target(at):
        if start is not None and not start <= at.date() < end:
            if previous_start <= at.date() < previous_end:
                key = bucket_key(at, period)
                return previous_buckets.setdefault(key, empty_bucket(key))
            return None
        key = bucket_key(at, period)
        return buckets.setdefault(key, empty_bucket(key))
    with closing(readonly(account_db or dp.RUNTIME_DIR / 'lotto_web.db')) as connection:
        if not connection.execute("SELECT 1 FROM users WHERE username=?", (owner,)).fetchone():
            raise ValueError("Tài khoản không tồn tại.")
        payments = connection.execute("SELECT amount,paid_at FROM payment_orders WHERE username=? AND status='PAID' AND environment IN ('production','manual')", (owner,))
        for row in payments:
            try:
                at = stamp(row['paid_at'])
                if not integer(row['amount']):
                    raise ValueError('Invalid amount')
                bucket = target(at)
                if bucket is not None:
                    bucket['deposited'] += row['amount']
            except (ValueError, TypeError):
                warnings.add("Có giao dịch nạp thiếu số tiền hoặc thời gian hợp lệ.")
    games = GAMES if game == 'all' else (game,)
    scopes = [(scope_game, scope_level) for scope_game in games
              for scope_level in (range(1, 11) if game == 'all' and scope_game == 'KENO' else (level,))]
    prizes_by_game = {}
    for scope_game in games:
        if prizes is not None:
            prizes_by_game[scope_game] = prizes.get(scope_game, {}) if game == 'all' else prizes
            continue
        try:
            prizes_by_game[scope_game] = keno_prizes.load_cache()['draws'] if scope_game == 'KENO' else canonical_prizes(scope_game)
        except (OSError, ValueError, KeyError):
            prizes_by_game[scope_game] = {}
            warnings.add("Chưa đọc được dữ liệu quỹ thưởng; các giải quỹ chưa được tính đủ.")
    grouped = defaultdict(list)
    with closing(readonly(tracking_db or database_path())) as connection:
        for scope_game, scope_level in scopes:
            for row in simulation_rows(connection, scope_game, scope_level):
                grouped[(scope_game, scope_level, row['cycle_id'])].append(dict(row))
    for (scope_game, scope_level, _), group in grouped.items():
        if len(group) != 4 or {r['method'] for r in group} != set(METHODS) or any(r['status'] not in ('locked','scored') for r in group):
            warnings.add("Bỏ qua chu kỳ thiếu đủ bốn phương pháp đã khóa.")
            continue
        selected = group if method == 'all' else [next(r for r in group if r['method'] == method)]
        row = selected[0]
        counts_by_method = {}
        for item in group:
            count = item['ticket_count'] if integer(item['ticket_count']) else item['configured_count']
            if not integer(count):
                count = item['requested_count']
                if scope_game == 'KENO' and integer(count):
                    import math
                    count = min(count, math.comb(80, scope_level))
            counts_by_method[item['method']] = count
        ticket_totals = [counts_by_method[item['method']] for item in selected]
        if any(not integer(count) or count <= 0 for count in ticket_totals):
            warnings.add("Có chu kỳ thiếu số vé đã khóa; chưa đưa vào thống kê.")
            continue
        total = sum(ticket_totals)
        try:
            purchased_at, draw_at = stamp(row['created_at']), stamp(row['deadline'])
        except (ValueError, TypeError):
            warnings.add("Có chu kỳ thiếu thời gian đã khóa/giờ quay hợp lệ.")
            continue
        in_purchase_period = start is None or start <= purchased_at.date() < end
        purchase_complete = in_purchase_period and all(integer(count) and count > 0 for count in counts_by_method.values())
        if in_purchase_period:
            if purchase_complete:
                for name, count in counts_by_method.items():
                    method_tickets[name] += count
                    purchase_outcomes[name]['tickets'] += count
            else:
                warnings.add("Biểu đồ tỷ lệ bỏ qua chu kỳ chưa đủ số vé của bốn phương pháp.")
        bought = target(purchased_at)
        if bought is not None:
            bought['bought'] += total
            bought['spent'] += total * 10000
        complete = all(r['status'] == 'scored' and r['summary_json'] for r in group)
        if scope_game != 'KENO':
            complete = all(r['status'] == 'scored' and (r['summary_json'] or r['legacy_results']) for r in group)
            complete = complete and all((r['actual_main'], r['actual_special']) == (row['actual_main'], row['actual_special']) for r in group)
        else:
            complete = complete and row['cycle_status'] == 'scored'
        if not complete:
            if bought is not None:
                bought['pending'] += total
            if purchase_complete:
                for name, count in counts_by_method.items():
                    purchase_outcomes[name]['pending'] += count
            awaiting_draw = target(draw_at)
            if awaiting_draw is not None:
                awaiting_draw['drawPending'] += total
            continue
        bucket = target(draw_at)
        if bucket is None and not purchase_complete:
            continue
        in_draw_period = start is None or start <= draw_at.date() < end
        actual = json.loads(row['actual_json']) if scope_game == 'KENO' else {'main':json.loads(row['actual_main'] or '[]'), 'special':row['actual_special']}
        # Keep draw-date KPI distributions for compatibility. The aligned rings
        # instead compare wins with the SAME purchased tickets in both layers.
        if in_draw_period or purchase_complete:
            for item in group:
                count = counts_by_method[item['method']]
                if not integer(count) or count <= 0:
                    continue
                summary = json.loads(item['summary_json'] or '{}')
                counts = summary.get('prizeCounts')
                if counts is None and scope_game != 'KENO':
                    counts = dict(Counter(result.get('prizeCode', 'UNKNOWN') for result in json.loads(item['legacy_results'] or '[]')))
                if not isinstance(counts, dict) or any(not integer(n) for n in counts.values()) or sum(counts.values()) != count:
                    won, unknown = 0, count
                else:
                    _, _, won, unknown = reward_amount(scope_game, counts, actual, draw_at, row['target_draw_id'], prizes_by_game[scope_game], scope_level)
                if in_draw_period:
                    distribution = method_wins[item['method']]
                    distribution['scored'] += count
                    distribution['tickets'] += won
                    distribution['unknownTickets'] += unknown
                if purchase_complete:
                    outcome = purchase_outcomes[item['method']]
                    outcome['scored'] += count
                    outcome['won'] += won
                    outcome['unknownTickets'] += unknown
        if bucket is None:
            continue
        bucket['scored'] += total
        combined = Counter()
        valid_counts = True
        for item, count in zip(selected, ticket_totals):
            summary = json.loads(item['summary_json'] or '{}')
            counts = summary.get('prizeCounts')
            if counts is None and scope_game != 'KENO':
                counts = dict(Counter(result.get('prizeCode', 'UNKNOWN') for result in json.loads(item['legacy_results'] or '[]')))
            if not isinstance(counts, dict) or any(not integer(n) for n in counts.values()) or sum(counts.values()) != count:
                valid_counts = False
                break
            combined.update(counts)
        if not valid_counts:
            bucket['incomplete'] += 1
            bucket['unknownTickets'] += total
            continue
        reward, missing, won, unknown = reward_amount(scope_game, combined, actual, draw_at, row['target_draw_id'], prizes_by_game[scope_game], scope_level)
        bucket['reward'] += reward
        bucket['won'] += won
        bucket['unknownTickets'] += unknown
        bucket['incomplete'] += int(missing)
    if start is not None:
        cursor = datetime.combine(start, time(), TZ)
        while cursor.date() < end:
            key = bucket_key(cursor, period)
            buckets.setdefault(key, empty_bucket(key))
            cursor += timedelta(hours=1) if period == 'day' else timedelta(days=1)
    elif buckets:
        first, last = min(buckets), max(buckets)
        cursor = date.fromisoformat(first + '-01')
        while cursor.strftime('%Y-%m') <= last:
            key = cursor.strftime('%Y-%m')
            buckets.setdefault(key, empty_bucket(key))
            cursor = cursor.replace(year=cursor.year+1,month=1) if cursor.month == 12 else cursor.replace(month=cursor.month+1)
    series = [buckets[key] for key in sorted(buckets)]
    totals = sum_totals(series)
    comparison = None
    if previous_start is not None:
        cursor = datetime.combine(previous_start, time(), TZ)
        while cursor.date() < previous_end:
            key = bucket_key(cursor, period)
            previous_buckets.setdefault(key, empty_bucket(key))
            cursor += timedelta(hours=1) if period == 'day' else timedelta(days=1)
        previous_series = [previous_buckets[key] for key in sorted(previous_buckets)]
        previous_totals = sum_totals(previous_buckets.values())
        changes = {key:totals[key]-previous_totals[key] for key in ('deposited','spent','reward','bought','won')}
        estimated = {'reward':bool(totals['incomplete'] or previous_totals['incomplete'])}
        if totals['unknownTickets'] or previous_totals['unknownTickets']:
            changes['won'] = None
        comparison = {'from':previous_start.isoformat(), 'until':previous_end.isoformat(),
                      'totals':previous_totals, 'changes':changes, 'estimated':estimated,
                      'series':previous_series}
    as_of = datetime.now(TZ)
    for bucket in series:
        key = bucket['key']
        bucket_start = datetime.fromisoformat(key+'-01' if len(key)==7 else key).replace(tzinfo=TZ)
        bucket['future'] = bucket_start > as_of
    return {'ok':True, 'owner':owner, 'type':game, 'method':method, 'level':level, 'period':period, 'anchor':anchor.isoformat(),
            'timezone':'Asia/Ho_Chi_Minh', 'from':start.isoformat() if start else None, 'until':end.isoformat() if end else None,
            'totals':totals, 'comparison':comparison, 'series':series,
            'methodDistribution':[{'method':name, 'tickets':count} for name, count in method_tickets.items()],
            'methodWinDistribution':list(method_wins.values()),
            'methodPurchaseOutcomes':list(purchase_outcomes.values()),
            'warnings':sorted(warnings), 'simulationShared':True,
            'rewardEstimated':True, 'asOf':as_of.isoformat(), 'updatedAt':datetime.now(timezone.utc).isoformat()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--owner', required=True)
    parser.add_argument('--game', default='LOTO_5_35')
    parser.add_argument('--method', default='web')
    parser.add_argument('--level', type=int, default=10)
    parser.add_argument('--period', default='all')
    parser.add_argument('--date', default=None)
    parser.add_argument('--personal-id', default=None)
    args = parser.parse_args()
    try:
        tracking = None
        if args.personal_id:
            from ai.personal_tracking import Scope
            scope = Scope(args.personal_id, args.owner)
            scope.validate()
            if not scope.database.exists():
                scope.prepare()
            tracking = scope.database
        payload = report(args.owner, args.game, args.method, args.level, args.period, args.date, tracking_db=tracking)
    except Exception as error:
        payload = {'ok':False, 'message':str(error)}
    print(json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False))


if __name__ == '__main__':
    main()
