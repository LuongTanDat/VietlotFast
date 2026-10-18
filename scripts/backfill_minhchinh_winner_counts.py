"""Backfill published counts only, with cached source evidence and draw identity checks."""
import argparse
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import live_results as lr


def parse_page(type_key, html, url):
    cfg = lr.LIVE_TYPES[type_key]
    results = []
    for section in lr.extract_draw_sections(lr.html_to_lines(html)):
        if lr.section_matches_cfg(cfg, section):
            result = lr.parse_numeric_section(cfg, section, url)
            if result:
                results.append(result)
    return results


def apply_evidence(type_key, evidence):
    rows, meta, _ = lr.load_canonical_rows(type_key, rewrite_if_needed=False)
    changed = 0
    for ky, item in evidence.items():
        row = rows.get(ky)
        if not row or lr.loto535_draw_identity(row) != item['identity']:
            continue
        old = row.get(lr.PRIZE_WINNER_COUNTS_FIELD, {})
        # This task fills missing fields; keep already verified counts intact.
        new = {**item['counts'], **old}
        if new != old:
            row[lr.PRIZE_WINNER_COUNTS_FIELD] = new
            row['_PrizeWinnerCountsSource'] = item['sourceUrl']
            row['_PrizeWinnerCountsCheckedAt'] = item['checkedAt']
            changed += 1
    if changed:
        meta['prizeWinners'] = lr.build_prize_winner_meta(type_key, rows)
        lr.write_canonical_meta(type_key, meta)
    return changed


def coverage(type_key):
    rows, _, _ = lr.load_canonical_rows(type_key, rewrite_if_needed=False)
    keys = lr.PRIZE_WINNER_KEYS_BY_TYPE[type_key]
    missing = {ky: [k for k in keys if k not in row.get(lr.PRIZE_WINNER_COUNTS_FIELD, {})]
               for ky, row in rows.items()}
    return {'total': len(rows), 'complete': sum(not v for v in missing.values()),
            'missingByDraw': {ky: v for ky, v in missing.items() if v}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', required=True)
    parser.add_argument('--types', nargs='+', choices=list(lr.PRIZE_WINNER_KEYS_BY_TYPE),
                        default=list(lr.PRIZE_WINNER_KEYS_BY_TYPE))
    parser.add_argument('--delay', type=float, default=0.4)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not 0.2 <= args.delay <= 30:
        parser.error('delay must be 0.2–30 seconds')
    work = (ROOT / args.work).resolve()
    if not work.is_relative_to(ROOT / 'runtime'):
        parser.error('work must be inside project runtime')
    work.mkdir(parents=True, exist_ok=True)
    report_path = work / 'report.json'
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {
        'startedAt': lr.now_iso(), 'source': 'https://www.minhchinh.com/', 'types': {}, 'errors': []}
    session = lr.create_session()
    stopped = False

    def save():
        report['updatedAt'] = lr.now_iso()
        lr.write_json_file(report_path, report)

    for type_key in args.types:
        rows, _, _ = lr.load_canonical_rows(type_key, rewrite_if_needed=False)
        stat = report['types'].setdefault(type_key, {'before': coverage(type_key), 'pages': {}, 'verified': {}, 'appliedDraws': 0})
        attempted = set()
        cache_dir = work / type_key
        cache_dir.mkdir(exist_ok=True)
        keys = set(lr.PRIZE_WINNER_KEYS_BY_TYPE[type_key])
        remaining = set(ky for ky, row in rows.items()
                        if not keys.issubset(row.get(lr.PRIZE_WINNER_COUNTS_FIELD, {})))
        # Continue unfinished scans using the saved per-page coverage.
        for page in stat['pages'].values():
            attempted.update(page['draws'])
        remaining -= attempted
        while remaining:
            target = rows[max(remaining, key=int)]
            date = lr.parse_csv_date(target['Ngay'])
            url = lr.HISTORY_URL_PATTERNS[type_key].format(date=date.strftime('%d-%m-%Y'))
            filename = date.isoformat() + '.html.gz'
            cached = cache_dir / filename
            try:
                if cached.exists():
                    html = gzip.decompress(cached.read_bytes()).decode('utf-8')
                else:
                    response = session.get(url, timeout=(5, 25))
                    if response.status_code in (429, 403, 503):
                        report['errors'].append({'type': type_key, 'url': url, 'status': response.status_code,
                                                 'message': 'Source unavailable/rate limited; stopped without further requests'})
                        stopped = True
                        break
                    response.raise_for_status()
                    response.encoding = 'utf-8'
                    html = response.text
                    if 'Đang kiểm tra truy cập' in html:
                        report['errors'].append({'type': type_key, 'url': url, 'message': 'Access check; stopped'})
                        stopped = True
                        break
                    cached.write_bytes(gzip.compress(html.encode('utf-8')))
                    time.sleep(args.delay)
                results = parse_page(type_key, html, url)
                seen = []
                mismatched = []
                for result in results:
                    ky = str(result['ky'])
                    row = rows.get(ky)
                    candidate = lr.result_to_csv_row(result)
                    if row is None:
                        continue
                    if lr.loto535_draw_identity(row) != lr.loto535_draw_identity(candidate):
                        mismatched.append(ky)
                        continue
                    seen.append(ky)
                    counts = lr.valid_prize_winner_counts(type_key, result.get('prizeWinnerCounts'))
                    if counts:
                        stat['verified'][ky] = {'identity': lr.loto535_draw_identity(row), 'counts': counts,
                            'sourceUrl': url, 'checkedAt': lr.now_iso(),
                            'htmlSha256': hashlib.sha256(html.encode('utf-8')).hexdigest(),
                            'evidenceFile': cached.relative_to(ROOT).as_posix()}
                stat['pages'][date.isoformat()] = {'sourceUrl': url, 'draws': seen, 'mismatched': mismatched}
                remaining -= set(seen)
                # Mark target even when the page is unavailable or different; record explicitly.
                target_ky = target['Ky']
                if target_ky in remaining:
                    remaining.remove(target_ky)
                    report['errors'].append({'type': type_key, 'ky': target_ky, 'url': url,
                                             'message': 'Requested canonical draw absent/mismatched in source page'})
                if len(stat['pages']) % 20 == 0 or not remaining:
                    if args.apply:
                        stat['appliedDraws'] += apply_evidence(type_key, stat['verified'])
                    stat['after'] = coverage(type_key)
                    save()
                    print(json.dumps({'type': type_key, 'pages': len(stat['pages']),
                        'verified': len(stat['verified']), 'complete': stat['after']['complete'],
                        'remaining': len(remaining), 'errors': len(report['errors'])}), flush=True)
            except lr.requests.RequestException as exc:
                report['errors'].append({'type': type_key, 'url': url, 'message': str(exc)})
                stopped = True
                break
        if args.apply:
            stat['appliedDraws'] += apply_evidence(type_key, stat['verified'])
        stat['after'] = coverage(type_key)
        save()
        if stopped:
            break
    report['finishedAt'] = lr.now_iso()
    report['stoppedOnSourceError'] = stopped
    save()
    print(json.dumps({'report': str(report_path), 'stopped': stopped,
                      'coverage': {key: {f: stat['after'][f] for f in ('total', 'complete')}
                                   for key, stat in report['types'].items()}}, ensure_ascii=False), flush=True)
    return 2 if stopped else 0


if __name__ == '__main__':
    raise SystemExit(main())
