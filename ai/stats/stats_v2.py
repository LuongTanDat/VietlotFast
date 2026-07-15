import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from itertools import combinations
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "canonical"


GAME_CONFIGS = {
    "LOTO_5_35": {
        "label": "Lotto 5/35",
        "file": "loto_5_35_all_day.csv",
        "kind": "numeric",
        "main_min": 1,
        "main_max": 35,
        "main_width": 2,
        "has_special": True,
        "special_min": 1,
        "special_max": 12,
        "special_width": 2,
    },
    "LOTO_6_45": {
        "label": "Mega 6/45",
        "file": "mega_6_45_all_day.csv",
        "kind": "numeric",
        "main_min": 1,
        "main_max": 45,
        "main_width": 2,
        "has_special": False,
    },
    "LOTO_6_55": {
        "label": "Power 6/55",
        "file": "power_6_55_all_day.csv",
        "kind": "numeric",
        "main_min": 1,
        "main_max": 55,
        "main_width": 2,
        "has_special": True,
        "special_min": 1,
        "special_max": 55,
        "special_width": 2,
    },
    "KENO": {
        "label": "Keno",
        "file": "keno_all_day.csv",
        "kind": "keno",
        "main_min": 1,
        "main_max": 80,
        "main_width": 2,
        "has_special": False,
    },
    "MAX_3D": {
        "label": "Max 3D",
        "file": "max_3d_all_day.csv",
        "kind": "three_digit",
        "main_min": 0,
        "main_max": 999,
        "main_width": 3,
        "has_special": False,
    },
    "MAX_3D_PRO": {
        "label": "Max 3D Pro",
        "file": "max_3d_pro_all_day.csv",
        "kind": "three_digit",
        "main_min": 0,
        "main_max": 999,
        "main_width": 3,
        "has_special": False,
    },
}


HEADER_ALIASES = {
    "ky": "ky",
    "thu": "weekday",
    "ngay": "date",
    "date": "date",
    "time": "time",
    "gio": "time",
    "thoi gian": "time",
    "main": "numbers",
    "numbers": "numbers",
    "bo so": "numbers",
    "boso": "numbers",
    "special": "special",
    "db": "special",
    "dac biet": "special",
    "hien thi": "display",
    "display": "display",
    "displaylines": "display",
    "display lines": "display",
    "loai": "label",
    "label": "label",
    "link cap nhat": "source_url",
    "sourceurl": "source_url",
    "source url": "source_url",
    "ngay cap nhat": "source_date",
    "source date": "source_date",
}

SORT_KEYS = {"most", "least", "overdue", "streak"}
PERIOD_KEYS = {"7d", "30d", "60d", "1y", "custom", "all"}
GROUP_KEYS = {"main", "special"}
THREE_DIGIT_TOKEN_RE = re.compile(r"(?<!\d)\d{3}(?!\d)")
DEFAULT_MAX_COMBO_SIZE = 5
KENO_MAX_COMBO_SIZE = 10
KENO_EXHAUSTIVE_COMBO_LIMIT = 3


def normalize_header(value):
    text = unicodedata.normalize("NFKD", str(value or "")).strip().lower()
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d")
    text = re.sub(r"\s+", " ", text.replace("_", " ")).strip()
    return text


def normalize_type(value):
    text = str(value or "").strip().upper().replace("-", "_").replace("/", "_")
    aliases = {
        "LOTO_535": "LOTO_5_35",
        "LOTTO_535": "LOTO_5_35",
        "LOTTO_5_35": "LOTO_5_35",
        "MEGA_645": "LOTO_6_45",
        "MEGA_6_45": "LOTO_6_45",
        "POWER_655": "LOTO_6_55",
        "POWER_6_55": "LOTO_6_55",
        "MAX3D": "MAX_3D",
        "MAX3DPRO": "MAX_3D_PRO",
        "MAX_3DPRO": "MAX_3D_PRO",
    }
    return aliases.get(text, text)


def max_combo_size_for_type(type_key):
    return KENO_MAX_COMBO_SIZE if normalize_type(type_key) == "KENO" else DEFAULT_MAX_COMBO_SIZE


def parse_date_value(value):
    text = str(value or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def parse_time_minutes(value):
    match = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(value or ""))
    if not match:
        return -1
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return -1
    return hour * 60 + minute


def ky_sort_value(value):
    digits = re.sub(r"\D", "", str(value or ""))
    return int(digits) if digits else -1


def parse_number_tokens(value):
    return [int(token) for token in re.findall(r"\d+", str(value or ""))]


def format_token(value, width):
    if isinstance(value, str) and not value.isdigit():
        return value
    try:
        return f"{int(value):0{width}d}"
    except (TypeError, ValueError):
        return str(value)


def normalize_csv_row(raw_row):
    out = {}
    for key, value in (raw_row or {}).items():
        canonical = HEADER_ALIASES.get(normalize_header(key))
        if canonical:
            out[canonical] = str(value or "").strip()
    return out


def read_csv_rows(csv_path):
    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [normalize_csv_row(row) for row in reader]


def row_to_draw(type_key, row):
    cfg = GAME_CONFIGS[type_key]
    row_date = parse_date_value(row.get("date"))
    if row_date is None:
        return None
    ky = re.sub(r"\D", "", str(row.get("ky", "")).strip())
    if cfg["kind"] == "three_digit":
        main = sorted(set(THREE_DIGIT_TOKEN_RE.findall(row.get("display", ""))))
    else:
        raw_numbers = parse_number_tokens(row.get("numbers", ""))
        main = sorted({
            number
            for number in raw_numbers
            if int(cfg["main_min"]) <= number <= int(cfg["main_max"])
        })
    special = None
    if cfg.get("has_special"):
        special_numbers = parse_number_tokens(row.get("special", ""))
        if special_numbers:
            candidate = special_numbers[0]
            if int(cfg.get("special_min", 0)) <= candidate <= int(cfg.get("special_max", 0)):
                special = candidate
    if not main and special is None:
        return None
    return {
        "ky": ky,
        "date": row_date,
        "dateText": row_date.strftime("%d/%m/%Y"),
        "time": str(row.get("time", "")).strip(),
        "timeMinutes": parse_time_minutes(row.get("time", "")),
        "main": main,
        "special": special,
        "display": str(row.get("display", "")).strip(),
    }


def load_draws(type_key, csv_path):
    rows = read_csv_rows(csv_path)
    draws = [row_to_draw(type_key, row) for row in rows]
    draws = [draw for draw in draws if draw]
    draws.sort(key=lambda item: (
        item["date"].toordinal(),
        item.get("timeMinutes", -1),
        ky_sort_value(item.get("ky", "")),
    ))
    return draws


def filter_draws_by_period(draws, period="30d", from_date=None, to_date=None):
    period_key = str(period or "30d").strip().lower()
    if period_key not in PERIOD_KEYS:
        period_key = "30d"
    if not draws:
        return [], None, None
    latest_date = max(draw["date"] for draw in draws)
    start = None
    end = latest_date
    if period_key == "custom":
        start = parse_date_value(from_date)
        end = parse_date_value(to_date) or latest_date
    elif period_key == "7d":
        start = latest_date - timedelta(days=6)
    elif period_key == "30d":
        start = latest_date - timedelta(days=29)
    elif period_key == "60d":
        start = latest_date - timedelta(days=59)
    elif period_key == "1y":
        start = latest_date - timedelta(days=364)
    elif period_key == "all":
        start = None
    if start and end and start > end:
        start, end = end, start
    filtered = [
        draw for draw in draws
        if (start is None or draw["date"] >= start) and (end is None or draw["date"] <= end)
    ]
    if filtered:
        return filtered, min(draw["date"] for draw in filtered), max(draw["date"] for draw in filtered)
    return [], start, end


def number_universe(type_key, group):
    cfg = GAME_CONFIGS[type_key]
    if group == "special":
        if not cfg.get("has_special"):
            return []
        return [
            format_token(number, int(cfg.get("special_width", cfg.get("main_width", 2))))
            for number in range(int(cfg["special_min"]), int(cfg["special_max"]) + 1)
        ]
    return [
        format_token(number, int(cfg.get("main_width", 2)))
        for number in range(int(cfg["main_min"]), int(cfg["main_max"]) + 1)
    ]


def draw_tokens(type_key, draw, group):
    cfg = GAME_CONFIGS[type_key]
    if group == "special":
        if draw.get("special") is None:
            return []
        return [format_token(draw["special"], int(cfg.get("special_width", cfg.get("main_width", 2))))]
    if cfg["kind"] == "three_digit":
        return [format_token(value, 3) for value in draw.get("main", [])]
    return [format_token(value, int(cfg.get("main_width", 2))) for value in draw.get("main", [])]


def draw_combo_items(type_key, draw, group, combo_size):
    tokens = sorted(set(draw_tokens(type_key, draw, group)))
    if combo_size <= 1:
        return {(token,) for token in tokens}
    if group == "special":
        return set()
    if combo_size > len(tokens):
        return set()
    if type_key == "KENO" and combo_size > KENO_EXHAUSTIVE_COMBO_LIMIT:
        return {
            tuple(tokens[index:index + combo_size])
            for index in range(0, len(tokens) - combo_size + 1)
        }
    return {tuple(combo) for combo in combinations(tokens, combo_size)}


def candidate_items(type_key, group, combo_size, observed):
    if combo_size <= 1:
        return [(token,) for token in number_universe(type_key, group)]
    cfg = GAME_CONFIGS[type_key]
    if cfg["kind"] == "three_digit":
        return sorted(observed)
    if combo_size <= KENO_EXHAUSTIVE_COMBO_LIMIT:
        universe = number_universe(type_key, group)
        return [tuple(combo) for combo in combinations(universe, combo_size)]
    return sorted(observed)


def item_label(item):
    return "-".join(str(part) for part in item)


def compute_stats(type_key, draws, group="main", combo_size=1, sort_key="most", limit=120):
    type_key = normalize_type(type_key)
    combo_size = max(1, min(max_combo_size_for_type(type_key), int(combo_size or 1)))
    sort_key = sort_key if sort_key in SORT_KEYS else "most"
    total_draws = len(draws)
    counts = Counter()
    last_seen_index = {}
    last_seen_meta = {}
    current_run = defaultdict(int)
    max_streak = defaultdict(int)
    observed = set()

    for index, draw in enumerate(draws):
        items = draw_combo_items(type_key, draw, group, combo_size)
        observed.update(items)
        for item in items:
            counts[item] += 1
            if last_seen_index.get(item) == index - 1:
                current_run[item] += 1
            else:
                current_run[item] = 1
            max_streak[item] = max(max_streak[item], current_run[item])
            last_seen_index[item] = index
            last_seen_meta[item] = {
                "ky": str(draw.get("ky", "")),
                "date": str(draw.get("dateText", "")),
            }

    rows = []
    for item in candidate_items(type_key, group, combo_size, observed):
        count = int(counts.get(item, 0))
        last_idx = last_seen_index.get(item)
        current_gap = total_draws if last_idx is None else max(0, total_draws - 1 - last_idx)
        rows.append({
            "key": item_label(item),
            "numbers": list(item),
            "label": item_label(item),
            "count": count,
            "avgCycle": round(total_draws / count, 4) if count else None,
            "currentGap": current_gap,
            "maxStreak": int(max_streak.get(item, 0)),
            "currentStreak": int(current_run.get(item, 0)) if last_idx == total_draws - 1 else 0,
            "lastSeenKy": last_seen_meta.get(item, {}).get("ky", ""),
            "lastSeenDate": last_seen_meta.get(item, {}).get("date", ""),
            "rate": round(count / total_draws, 6) if total_draws else 0,
        })

    if sort_key == "least":
        rows.sort(key=lambda item: (item["count"], -item["currentGap"], item["label"]))
    elif sort_key == "overdue":
        rows.sort(key=lambda item: (-item["currentGap"], item["count"], item["label"]))
    elif sort_key == "streak":
        rows.sort(key=lambda item: (-item["currentStreak"], -item["maxStreak"], -item["count"], item["label"]))
    else:
        rows.sort(key=lambda item: (-item["count"], item["currentGap"], item["label"]))

    safe_limit = max(1, min(500, int(limit or 120)))
    return rows[:safe_limit], rows


def build_loto_535_summary(draws):
    main_top, main_all = compute_stats("LOTO_5_35", draws, "main", 1, "most", 35)
    least_top = sorted(main_all, key=lambda item: (item["count"], item["label"]))
    streak_top = sorted(main_all, key=lambda item: (-item["currentStreak"], -item["maxStreak"], -item["count"], item["label"]))
    return {
        "mainMost": main_top[0] if main_top else None,
        "mainLeast": least_top[0] if least_top else None,
        "mainCurrentStreak": streak_top[0] if streak_top else None,
    }


def build_stats_payload(
    type_key,
    period="30d",
    group="main",
    combo_size=1,
    sort_key="most",
    from_date=None,
    to_date=None,
    limit=120,
    data_dir=None,
    csv_path=None,
):
    normalized_type = normalize_type(type_key)
    if normalized_type not in GAME_CONFIGS:
        return {"ok": False, "message": "Loại thống kê không hợp lệ."}
    group = str(group or "main").strip().lower()
    if group not in GROUP_KEYS:
        group = "main"
    combo_size = max(1, min(max_combo_size_for_type(normalized_type), int(combo_size or 1)))
    sort_key = str(sort_key or "most").strip().lower()
    if sort_key not in SORT_KEYS:
        sort_key = "most"

    cfg = GAME_CONFIGS[normalized_type]
    if group == "special" and not cfg.get("has_special"):
        return {"ok": False, "message": f"{cfg['label']} không có nhóm số đặc biệt."}
    if group == "special" and combo_size != 1:
        return {"ok": False, "message": "Nhóm số đặc biệt chỉ hỗ trợ combo 1 số."}

    source_path = Path(csv_path) if csv_path else Path(data_dir or DEFAULT_DATA_DIR) / cfg["file"]
    if not source_path.exists():
        return {"ok": False, "message": f"Không tìm thấy CSV canonical: {source_path.name}"}

    draws = load_draws(normalized_type, source_path)
    if cfg["kind"] == "three_digit" and not any(draw.get("main") for draw in draws):
        return {
            "ok": True,
            "supported": False,
            "message": f"{cfg['label']} chưa hỗ trợ đầy đủ vì CSV chưa có dữ liệu 3 chữ số trong cột Hiển thị.",
            "type": normalized_type,
            "items": [],
        }

    filtered_draws, filtered_from, filtered_to = filter_draws_by_period(draws, period, from_date, to_date)
    items, _ = compute_stats(normalized_type, filtered_draws, group, combo_size, sort_key, limit)
    combo_mode = (
        "keno_window"
        if normalized_type == "KENO" and group == "main" and combo_size > KENO_EXHAUSTIVE_COMBO_LIMIT
        else "exact"
    )
    payload = {
        "ok": True,
        "supported": True,
        "mode": "stats_v2",
        "type": normalized_type,
        "label": cfg["label"],
        "sourceFile": source_path.name,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "comboMode": combo_mode,
        "params": {
            "period": period,
            "group": group,
            "comboSize": combo_size,
            "sort": sort_key,
            "from": from_date or "",
            "to": to_date or "",
            "limit": int(limit or 120),
        },
        "totalRows": len(draws),
        "totalDraws": len(filtered_draws),
        "filteredFrom": filtered_from.strftime("%d/%m/%Y") if isinstance(filtered_from, date) else "",
        "filteredTo": filtered_to.strftime("%d/%m/%Y") if isinstance(filtered_to, date) else "",
        "items": items,
    }
    if normalized_type == "LOTO_5_35":
        payload["jackpot"] = {
            "title": "Giá trị Độc đắc",
            "value": "Tối thiểu 6 tỷ và tích lũy",
            "note": "Theo cơ cấu giải Lotto 5/35; thống kê bên dưới chỉ đọc từ canonical all_day.csv.",
        }
        payload["loto535Summary"] = build_loto_535_summary(filtered_draws)
    return payload


def parse_args(argv):
    parser = argparse.ArgumentParser(description="DVLF Stats V2")
    sub = parser.add_subparsers(dest="command")
    stats = sub.add_parser("stats_json")
    stats.add_argument("--type", required=True)
    stats.add_argument("--period", default="30d", choices=sorted(PERIOD_KEYS))
    stats.add_argument("--group", default="main", choices=sorted(GROUP_KEYS))
    stats.add_argument("--combo-size", type=int, default=1)
    stats.add_argument("--sort", default="most", choices=sorted(SORT_KEYS))
    stats.add_argument("--from", dest="from_date", default="")
    stats.add_argument("--to", dest="to_date", default="")
    stats.add_argument("--limit", type=int, default=120)
    stats.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    if args.command != "stats_json":
        print(json.dumps({"ok": False, "message": "Thiếu lệnh stats_json."}, ensure_ascii=False))
        return 2
    payload = build_stats_payload(
        args.type,
        period=args.period,
        group=args.group,
        combo_size=args.combo_size,
        sort_key=args.sort,
        from_date=args.from_date,
        to_date=args.to_date,
        limit=args.limit,
        data_dir=args.data_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
