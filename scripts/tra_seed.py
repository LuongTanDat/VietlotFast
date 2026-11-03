"""Interactive or one-shot seed lookup. Only reads the chosen local ledger."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai import seed_lookup


def show(result):
    if not result['matches']:
        print('Không tìm thấy seed trong danh mục/bộ lọc đã chọn.')
        if not result['searchedSchedules']:
            print('Chưa có lịch seed được hỗ trợ. Vé cũ không được gán seed riêng ngược.')
    for match in result['matches']:
        kind = f"Bao {match['baoLevel']}" if match['ticketClass'] == 'bao' else 'Vé Thường'
        print(f"\n{match['label']} | Kỳ #{match['targetDrawId']} | {match['methodLabel']} | {kind} số {match['index']}")
        print('Seed gốc:', match['rootSeed'])
        print('Bộ số:', ' '.join(f'{number:02d}' for number in match['selection']['main']))
        special = match['selection'].get('special')
        if special is not None:
            print('Số đặc biệt:' if match['type'] == 'LOTO_5_35' else 'Số phụ dự đoán:', f'{special:02d}')
        status = match['replay']['status']
        if status == 'verified':
            print('Tái lập: KHỚP CHÍNH XÁC bộ số đã lưu.')
        elif status == 'skipped':
            print('Đã tra bộ số đã lưu; chưa chạy tái lập (--no-replay).')
        else:
            print('Tái lập chưa được xác nhận:', match['replay'].get('reason', status))
    if result['ambiguous']:
        print('\nCó nhiều bộ khớp seed; đã hiển thị tất cả, không tự chọn một bộ.')
    for warning in result['warnings']:
        print('Lưu ý:', warning)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Tra seed mới đã lưu và tái lập bộ số. Không tạo lệnh mua, không trừ phí.')
    parser.add_argument('seed', nargs='?', help='Mã seed đầy đủ 64 ký tự; bỏ trống để nhập liên tục.')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--db', type=Path, help='DB đã có dữ liệu seed; chỉ mở chế độ đọc.')
    group.add_argument('--owner', help='Tên đăng nhập khi máy có nhiều danh mục cá nhân.')
    parser.add_argument('--type', dest='game', choices=sorted(seed_lookup.GAMES), help='Giới hạn loại xổ số để tìm nhanh.')
    parser.add_argument('--draw', help='Giới hạn mã kỳ để tìm nhanh.')
    parser.add_argument('--method', choices=sorted(seed_lookup.METHODS))
    parser.add_argument('--no-replay', action='store_true', help='Chỉ tra bộ số đã lưu, bỏ bước tái lập.')
    parser.add_argument('--json', action='store_true', help='Trả JSON cho một seed, không dùng chế độ nhập liên tục.')
    args = parser.parse_args(argv)
    if args.json and not args.seed:
        parser.error('--json cần truyền một mã seed.')
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    try:
        database = seed_lookup.select_database(ROOT / 'runtime', owner=args.owner, database=args.db)
    except (ValueError, OSError, sqlite3.Error) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False) if args.json else 'Lỗi: ' + str(error), file=sys.stderr)
        return 2

    def progress(value):
        if args.json:
            return
        if value['phase'] == 'search' and value['total'] >= 100000:
            print(f"Đang tra: {value['scanned']:,}/{value['total']:,} seed…", file=sys.stderr)
        elif value['phase'] == 'replay':
            print(f"Tìm thấy kỳ #{value['draw']} / {value['method']} / số {value['index']}. Đang tái lập trong bộ nhớ…", file=sys.stderr)

    def run(value):
        try:
            result = seed_lookup.lookup(value, database, game=args.game, draw=args.draw, method=args.method,
                                        replay=not args.no_replay, progress=progress)
            print(json.dumps(result, ensure_ascii=False, indent=2)) if args.json else show(result)
            if any(match['replay']['status'] in ('mismatch', 'unavailable') for match in result['matches']):
                return 3
            return 0 if result['matches'] else 1
        except (ValueError, OSError, sqlite3.Error) as error:
            print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False) if args.json else 'Lỗi: ' + str(error), file=sys.stderr)
            return 2

    if args.seed:
        return run(args.seed)
    print('TRA SEED VÉ THƯỜNG / BAO — 5/35, Mega 6/45, Power 6/55')
    print('Chỉ đọc dữ liệu; không tạo lệnh mua hoặc trừ phí.')
    print('Dán mã seed đầy đủ. Enter trống hoặc gõ q để thoát.')
    while True:
        try:
            value = input('\nSeed: ').strip()
        except EOFError:
            return 0
        if not value or value.lower() in ('q', 'quit', 'exit'):
            return 0
        run(value)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\nĐã dừng tra seed.', file=sys.stderr)
        raise SystemExit(130)
