import argparse
import csv
import json
import math
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from itertools import combinations
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import ai.configs.data_paths as dp


DISCLAIMER = "Đây là phân tích thống kê tham khảo, không cam kết dự đoán trúng."
SUPPORTED_TYPES = ("KENO", "LOTO_5_35", "LOTO_6_45", "LOTO_6_55", "MAX_3D", "MAX_3D_PRO")
PERIOD_KEYS = {"7d", "30d", "60d", "1y", "all", "custom"}
MODE_KEYS = {
    "overview", "general", "distribution", "ratios", "latest_draw", "consecutive",
    "overdue", "poisson", "knn", "chain", "relationships", "modulo", "advanced",
    "special", "weekday", "smart_wheel", "score", "all",
}
THREE_DIGIT_TOKEN_RE = re.compile(r"(?<!\d)\d{3}(?!\d)")


GAME_CONFIGS = {
    "LOTO_5_35": {
        "label": "Lotto 5/35",
        "kind": "numeric",
        "main_min": 1,
        "main_max": 35,
        "main_count": 5,
        "width": 2,
        "has_special": True,
        "special_min": 1,
        "special_max": 12,
        "special_width": 2,
    },
    "LOTO_6_45": {
        "label": "Mega 6/45",
        "kind": "numeric",
        "main_min": 1,
        "main_max": 45,
        "main_count": 6,
        "width": 2,
        "has_special": False,
    },
    "LOTO_6_55": {
        "label": "Power 6/55",
        "kind": "numeric",
        "main_min": 1,
        "main_max": 55,
        "main_count": 6,
        "width": 2,
        "has_special": True,
        "special_min": 1,
        "special_max": 55,
        "special_width": 2,
    },
    "KENO": {
        "label": "Keno",
        "kind": "keno",
        "main_min": 1,
        "main_max": 80,
        "main_count": 20,
        "width": 2,
        "has_special": False,
    },
    "MAX_3D": {
        "label": "Max 3D",
        "kind": "three_digit",
        "main_min": 0,
        "main_max": 999,
        "main_count": 18,
        "width": 3,
        "has_special": False,
    },
    "MAX_3D_PRO": {
        "label": "Max 3D Pro",
        "kind": "three_digit",
        "main_min": 0,
        "main_max": 999,
        "main_count": 20,
        "width": 3,
        "has_special": False,
    },
}


HEADER_ALIASES = {
    "ky": "draw_id",
    "thu": "weekday",
    "ngay": "date",
    "date": "date",
    "gio": "time",
    "time": "time",
    "thoi gian": "time",
    "bo so": "numbers",
    "numbers": "numbers",
    "main": "numbers",
    "db": "special",
    "dac biet": "special",
    "special": "special",
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


def normalize_header(value):
    text = unicodedata.normalize("NFKD", str(value or "")).strip().lower()
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d")
    return re.sub(r"\s+", " ", text.replace("_", " ")).strip()


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


def parse_date_value(value):
    text = str(value or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def date_iso(value):
    return value.strftime("%Y-%m-%d") if isinstance(value, date) else ""


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
    try:
        return f"{int(value):0{width}d}"
    except (TypeError, ValueError):
        return str(value)


def token_to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


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
    if cfg["kind"] == "three_digit":
        numbers = sorted(set(THREE_DIGIT_TOKEN_RE.findall(row.get("display", ""))))
    else:
        raw_numbers = parse_number_tokens(row.get("numbers", ""))
        numbers = sorted({
            format_token(number, int(cfg["width"]))
            for number in raw_numbers
            if int(cfg["main_min"]) <= int(number) <= int(cfg["main_max"])
        }, key=token_to_int)
    special = ""
    if cfg.get("has_special"):
        special_numbers = parse_number_tokens(row.get("special", ""))
        if special_numbers:
            candidate = special_numbers[0]
            if int(cfg.get("special_min", 0)) <= candidate <= int(cfg.get("special_max", 0)):
                special = format_token(candidate, int(cfg.get("special_width", cfg["width"])))
    if not numbers and not special:
        return None
    return {
        "drawId": re.sub(r"\D", "", str(row.get("draw_id", ""))).strip() or str(row.get("draw_id", "")).strip(),
        "date": row_date,
        "dateText": row_date.strftime("%d/%m/%Y"),
        "weekday": str(row.get("weekday", "")).strip(),
        "time": str(row.get("time", "")).strip(),
        "timeMinutes": parse_time_minutes(row.get("time", "")),
        "numbers": numbers,
        "special": special,
        "display": str(row.get("display", "")).strip(),
    }


def load_draws(type_key, csv_path=None):
    normalized = normalize_type(type_key)
    if normalized not in GAME_CONFIGS:
        raise ValueError("Loại vé không hợp lệ.")
    source_path = Path(csv_path) if csv_path else dp.get_canonical_csv_read_path(normalized)
    rows = read_csv_rows(source_path)
    draws = [row_to_draw(normalized, row) for row in rows]
    draws = [draw for draw in draws if draw]
    draws.sort(key=lambda item: (
        item["date"].toordinal(),
        item.get("timeMinutes", -1),
        ky_sort_value(item.get("drawId", "")),
    ))
    return draws, source_path


def filter_draws_by_period(draws, period="30d", from_date="", to_date=""):
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


def number_universe(type_key, special=False):
    cfg = GAME_CONFIGS[type_key]
    if special:
        if not cfg.get("has_special"):
            return []
        return [
            format_token(number, int(cfg.get("special_width", cfg["width"])))
            for number in range(int(cfg["special_min"]), int(cfg["special_max"]) + 1)
        ]
    if cfg["kind"] == "three_digit":
        return [format_token(number, 3) for number in range(0, 1000)]
    return [
        format_token(number, int(cfg["width"]))
        for number in range(int(cfg["main_min"]), int(cfg["main_max"]) + 1)
    ]


def draw_to_json(draw):
    if not draw:
        return {"drawId": "", "date": "", "numbers": [], "special": ""}
    return {
        "drawId": str(draw.get("drawId", "")),
        "date": date_iso(draw.get("date")),
        "dateText": str(draw.get("dateText", "")),
        "weekday": str(draw.get("weekday", "")),
        "time": str(draw.get("time", "")),
        "numbers": list(draw.get("numbers", [])),
        "special": str(draw.get("special", "")),
    }


def mean(values):
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def stddev(values):
    values = list(values)
    if not values:
        return 0.0
    avg = mean(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / len(values))


def quantile(values, ratio):
    values = sorted(values)
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * ratio))))
    return float(values[index])


def status_by_quantiles(value, values):
    low = quantile(values, 0.25)
    high = quantile(values, 0.75)
    if value < low:
        return "low"
    if value > high:
        return "high"
    return "normal"


def latest_numbers(draw):
    return [token_to_int(number) for number in (draw or {}).get("numbers", [])]


def draw_features(type_key, draw):
    cfg = GAME_CONFIGS[type_key]
    numbers = latest_numbers(draw)
    if not numbers:
        return {
            "sum": 0, "mean": 0, "standardDeviation": 0, "evenCount": 0, "oddCount": 0,
            "lowCount": 0, "highCount": 0, "span": 0, "consecutivePairCount": 0,
            "maxGapBetweenSortedNumbers": 0, "minGapBetweenSortedNumbers": 0,
        }
    sorted_numbers = sorted(numbers)
    boundary = (int(cfg["main_min"]) + int(cfg["main_max"])) // 2
    gaps = [b - a for a, b in zip(sorted_numbers, sorted_numbers[1:])]
    consecutive_pairs = sum(1 for gap in gaps if gap == 1)
    return {
        "sum": sum(numbers),
        "mean": round(mean(numbers), 4),
        "standardDeviation": round(stddev(numbers), 4),
        "evenCount": sum(1 for number in numbers if number % 2 == 0),
        "oddCount": sum(1 for number in numbers if number % 2 != 0),
        "lowCount": sum(1 for number in numbers if number <= boundary),
        "highCount": sum(1 for number in numbers if number > boundary),
        "span": max(numbers) - min(numbers),
        "consecutivePairCount": consecutive_pairs,
        "maxGapBetweenSortedNumbers": max(gaps) if gaps else 0,
        "minGapBetweenSortedNumbers": min(gaps) if gaps else 0,
    }


def frequency_counts(draws, special=False):
    counts = Counter()
    for draw in draws:
        if special:
            if draw.get("special"):
                counts[draw["special"]] += 1
        else:
            counts.update(draw.get("numbers", []))
    return counts


def top_count_items(counts, limit=10, reverse=True):
    items = [{"number": key, "count": int(value)} for key, value in counts.items()]
    if reverse:
        items.sort(key=lambda item: (-item["count"], item["number"]))
    else:
        items.sort(key=lambda item: (item["count"], item["number"]))
    return items[:max(0, int(limit or 10))]


def combo_counts(draws, size, limit=10):
    counts = Counter()
    for draw in draws:
        numbers = sorted(set(draw.get("numbers", [])), key=token_to_int)
        if len(numbers) < size:
            continue
        for combo in combinations(numbers, size):
            counts["-".join(combo)] += 1
    items = [{"combo": key, "numbers": key.split("-"), "count": value} for key, value in counts.items()]
    items.sort(key=lambda item: (-item["count"], item["combo"]))
    return items[:max(0, int(limit or 10))]


def build_overview(type_key, draws, limit=20, **kwargs):
    counts = frequency_counts(draws)
    hot = top_count_items(counts, min(limit, 20), True)
    universe = number_universe(type_key, False)
    full_counts = Counter({number: counts.get(number, 0) for number in universe})
    cold = top_count_items(full_counts, min(limit, 20), False)
    overdue_payload, _ = build_overdue(type_key, draws, limit=min(limit, 20))
    overdue_data = overdue_payload["topOverdue"]
    latest = draw_to_json(draws[-1] if draws else None)
    data = {
        "totalDraws": len(draws),
        "fromDate": date_iso(draws[0]["date"]) if draws else "",
        "toDate": date_iso(draws[-1]["date"]) if draws else "",
        "latestDraw": latest,
        "hotNumbers": hot,
        "coldNumbers": cold,
        "longestOverdue": overdue_data,
        "topPairs": combo_counts(draws, 2, 10),
        "topTriples": combo_counts(draws, 3, 10),
        "summaryText": f"{GAME_CONFIGS[type_key]['label']} có {len(draws)} kỳ trong phạm vi đang xét. Các nhóm số bên dưới chỉ là thống kê tham khảo.",
    }
    return data, [data["summaryText"]]


def build_general(type_key, draws, **kwargs):
    latest = draws[-1] if draws else None
    numbers = latest_numbers(latest)
    features = draw_features(type_key, latest)
    history_features = [draw_features(type_key, draw) for draw in draws if draw.get("numbers")]
    sums = [item["sum"] for item in history_features]
    spans = [item["span"] for item in history_features]
    data = {
        "sum": features["sum"],
        "mean": features["mean"],
        "standardDeviation": features["standardDeviation"],
        "minNumber": min(numbers) if numbers else None,
        "maxNumber": max(numbers) if numbers else None,
        "span": features["span"],
        "rangeStatus": status_by_quantiles(features["span"], spans),
        "sumStatus": status_by_quantiles(features["sum"], sums),
        "explanation": "Bộ số mới nhất được so với phân bố tổng và biên độ của lịch sử trong khoảng lọc.",
    }
    return data, [data["explanation"]]


def build_distribution(type_key, draws, limit=100, **kwargs):
    cfg = GAME_CONFIGS[type_key]
    counts = frequency_counts(draws)
    universe = number_universe(type_key, False)
    if cfg["kind"] == "three_digit":
        universe = sorted(set(universe).intersection(counts.keys()) or counts.keys())
    expected = (len(draws) * float(cfg["main_count"]) / max(1, len(number_universe(type_key, False))))
    items = []
    chi_square = 0.0
    for number in universe:
        count = int(counts.get(number, 0))
        deviation = count - expected
        if expected > 0:
            chi_square += (deviation ** 2) / expected
        rate = deviation / expected if expected else 0
        status = "high" if rate > 0.25 else ("low" if rate < -0.25 else "normal")
        items.append({
            "number": number,
            "observed": count,
            "expected": round(expected, 4),
            "deviation": round(deviation, 4),
            "deviationRate": round(rate, 6),
            "status": status,
        })
    items.sort(key=lambda item: (-abs(item["deviationRate"]), item["number"]))
    p_value = None
    try:
        from scipy.stats import chi2
        p_value = float(chi2.sf(chi_square, max(1, len(universe) - 1)))
    except Exception:
        p_value = None
    data = {
        "expectedCount": round(expected, 4),
        "chiSquare": round(chi_square, 6),
        "pValue": p_value,
        "items": items[:max(1, min(500, int(limit or 100)))],
        "explanation": "Phân phối so sánh số lần xuất hiện thực tế với mức kỳ vọng đều theo dải số.",
    }
    return data, [data["explanation"]]


def build_ratios(type_key, draws, **kwargs):
    cfg = GAME_CONFIGS[type_key]
    latest = draws[-1] if draws else None
    numbers = latest_numbers(latest)
    boundary = (int(cfg["main_min"]) + int(cfg["main_max"])) // 2
    even = sum(1 for number in numbers if number % 2 == 0)
    odd = len(numbers) - even
    low = sum(1 for number in numbers if number <= boundary)
    high = len(numbers) - low
    zone_size = 10 if cfg["kind"] != "three_digit" else 100
    zones = []
    for start in range(int(cfg["main_min"]), int(cfg["main_max"]) + 1, zone_size):
        end = min(int(cfg["main_max"]), start + zone_size - 1)
        if not any(start <= number <= end for number in numbers):
            zones.append(f"{format_token(start, cfg['width'])}-{format_token(end, cfg['width'])}")
    ratio_status = "normal"
    if numbers and (max(even, odd) >= len(numbers) - 1 or max(low, high) >= len(numbers) - 1):
        ratio_status = "skewed"
    data = {
        "evenCount": even,
        "oddCount": odd,
        "lowCount": low,
        "highCount": high,
        "evenOddRatio": f"{even}:{odd}",
        "lowHighRatio": f"{low}:{high}",
        "blankZones": zones,
        "ratioStatus": ratio_status,
        "explanation": "Tỷ lệ chẵn/lẻ và thấp/cao được tính trên kỳ mới nhất trong phạm vi lọc.",
    }
    return data, [data["explanation"]]


def build_latest_draw(type_key, draws, **kwargs):
    latest = draws[-1] if draws else None
    previous = draws[-2] if len(draws) >= 2 else None
    latest_set = set(latest.get("numbers", [])) if latest else set()
    previous_set = set(previous.get("numbers", [])) if previous else set()
    previous_ints = {token_to_int(number) for number in previous_set}
    slide = [
        number for number in sorted(latest_set, key=token_to_int)
        if token_to_int(number) - 1 in previous_ints or token_to_int(number) + 1 in previous_ints
    ]
    repeated = sorted(latest_set.intersection(previous_set), key=token_to_int)
    data = {
        "latestDraw": draw_to_json(latest),
        "previousDraw": draw_to_json(previous),
        "repeatedFromPrevious": repeated,
        "repeatCount": len(repeated),
        "slideNumbers": slide,
        "meanReversionNote": "Số lặp và số lệch ±1 chỉ mô tả nhịp gần nhất, không khẳng định kỳ sau.",
        "explanation": "So sánh kỳ mới nhất với kỳ liền trước để tìm số lặp và số trượt cạnh.",
    }
    return data, [data["explanation"], data["meanReversionNote"]]


def consecutive_runs(numbers):
    ordered = sorted(set(numbers))
    runs = []
    current = []
    for number in ordered:
        if not current or number == current[-1] + 1:
            current.append(number)
        else:
            if len(current) >= 2:
                runs.append(current)
            current = [number]
    if len(current) >= 2:
        runs.append(current)
    return runs


def build_consecutive(type_key, draws, **kwargs):
    latest = draws[-1] if draws else None
    nums = sorted(latest_numbers(latest))
    runs = consecutive_runs(nums)
    pairs = []
    triples = []
    for run in runs:
        pairs.extend([[format_token(a, GAME_CONFIGS[type_key]["width"]), format_token(b, GAME_CONFIGS[type_key]["width"])] for a, b in zip(run, run[1:])])
        if len(run) >= 3:
            triples.extend([
                [format_token(run[index], GAME_CONFIGS[type_key]["width"]),
                 format_token(run[index + 1], GAME_CONFIGS[type_key]["width"]),
                 format_token(run[index + 2], GAME_CONFIGS[type_key]["width"])]
                for index in range(len(run) - 2)
            ])
    max_len = max([len(run) for run in runs], default=0)
    data = {
        "consecutivePairs": pairs,
        "consecutiveTriples": triples,
        "maxConsecutiveLength": max_len,
        "hasLongSequence": max_len >= 4,
        "sequenceRiskStatus": "high" if max_len >= 4 else ("normal" if max_len >= 2 else "low"),
        "explanation": "Chuỗi liên tiếp được nhận diện trong bộ số mới nhất.",
    }
    return data, [data["explanation"]]


def build_overdue(type_key, draws, limit=20, special=False, **kwargs):
    universe = number_universe(type_key, special)
    seen_indices = defaultdict(list)
    for index, draw in enumerate(draws):
        values = [draw.get("special")] if special and draw.get("special") else draw.get("numbers", [])
        for number in values:
            seen_indices[number].append(index)
    rows = []
    total = len(draws)
    for number in universe:
        indices = seen_indices.get(number, [])
        current_skip = total if not indices else max(0, total - 1 - indices[-1])
        gaps = [indices[index] - indices[index - 1] for index in range(1, len(indices))]
        if indices:
            gaps.append(total - 1 - indices[-1])
            gaps.insert(0, indices[0])
        positive_gaps = [gap for gap in gaps if gap >= 0]
        max_skip = max(positive_gaps) if positive_gaps else current_skip
        avg_gap = mean(positive_gaps) if positive_gaps else None
        overdue_index = (current_skip / avg_gap) if avg_gap else 0
        if overdue_index >= 2:
            status = "very_overdue"
        elif overdue_index >= 1:
            status = "overdue"
        else:
            status = "normal"
        rhythm = "chưa đủ dữ liệu" if not indices else ("lâu chưa về" if status != "normal" else "đang trong nhịp")
        rows.append({
            "number": number,
            "currentSkip": int(current_skip),
            "maxSkip": int(max_skip),
            "avgGap": round(avg_gap, 4) if avg_gap is not None else None,
            "rhythm": rhythm,
            "overdueIndex": round(overdue_index, 4),
            "status": status,
        })
    rows.sort(key=lambda item: (-item["overdueIndex"], -item["currentSkip"], item["number"]))
    data = {
        "items": rows[:max(1, min(500, int(limit or 20)))],
        "topOverdue": rows[:min(10, max(1, int(limit or 20)))],
        "explanation": "Gan/overdue dùng tỷ lệ currentSkip chia avgGap, xử lý an toàn khi thiếu dữ liệu.",
    }
    return data, [data["explanation"]]


def build_poisson(type_key, draws, limit=20, **kwargs):
    cfg = GAME_CONFIGS[type_key]
    universe = number_universe(type_key, False)
    if cfg["kind"] == "three_digit":
        universe = sorted(set(number for draw in draws for number in draw.get("numbers", [])))
    counts = frequency_counts(draws)
    lam = len(draws) * float(cfg["main_count"]) / max(1, len(number_universe(type_key, False)))
    p0 = math.exp(-lam) if lam >= 0 else 0
    p1 = p0 * lam
    p2 = p0 * (lam ** 2) / 2
    p3plus = max(0.0, 1.0 - p0 - p1 - p2)
    rows = []
    denom = math.sqrt(lam) if lam > 0 else 1.0
    for number in universe:
        observed = int(counts.get(number, 0))
        anomaly = abs(observed - lam) / denom
        status = "hot" if observed > lam * 1.35 else ("cold" if observed < lam * 0.65 else "normal")
        rows.append({
            "number": number,
            "lambda": round(lam, 6),
            "observed": observed,
            "expected": round(lam, 4),
            "p0": round(p0, 8),
            "p1": round(p1, 8),
            "p2": round(p2, 8),
            "p3plus": round(p3plus, 8),
            "hotColdStatus": status,
            "anomalyScore": round(anomaly, 4),
        })
    rows.sort(key=lambda item: (-item["anomalyScore"], item["number"]))
    data = {
        "lambda": round(lam, 6),
        "p0": round(p0, 8),
        "p1": round(p1, 8),
        "p2": round(p2, 8),
        "p3plus": round(p3plus, 8),
        "items": rows[:max(1, min(200, int(limit or 20)))],
        "explanation": "Poisson dùng công thức math thuần để ước lượng mức xuất hiện kỳ vọng theo khoảng lọc.",
    }
    return data, [data["explanation"]]


def build_knn(type_key, draws, k=5, **kwargs):
    if len(draws) < 2:
        return {"neighbors": [], "followNumbersFromNeighbors": [], "explanation": "Không đủ dữ liệu để tìm kỳ tương đồng."}, ["Không đủ dữ liệu để tìm kỳ tương đồng."]
    latest = draws[-1]
    latest_features = draw_features(type_key, latest)
    keys = list(latest_features.keys())
    distances = []
    for index, draw in enumerate(draws[:-1]):
        features = draw_features(type_key, draw)
        distance = math.sqrt(sum((float(latest_features[key]) - float(features[key])) ** 2 for key in keys))
        next_draw = draws[index + 1] if index + 1 < len(draws) else None
        distances.append({
            "drawId": str(draw.get("drawId", "")),
            "drawDate": date_iso(draw.get("date")),
            "numbers": list(draw.get("numbers", [])),
            "distance": round(distance, 6),
            "similarityPercent": round(100.0 / (1.0 + distance), 2),
            "nextDrawNumbers": list(next_draw.get("numbers", [])) if next_draw else [],
        })
    distances.sort(key=lambda item: (item["distance"], item["drawId"]))
    neighbors = distances[:max(1, min(20, int(k or 5)))]
    follow_counts = Counter()
    for item in neighbors:
        follow_counts.update(item.get("nextDrawNumbers", []))
    data = {
        "latestFeatures": latest_features,
        "neighbors": neighbors,
        "followNumbersFromNeighbors": top_count_items(follow_counts, 12, True),
        "explanation": "Các kỳ này có cấu trúc gần giống kỳ mới nhất trong lịch sử.",
    }
    return data, [data["explanation"], "KNN không dùng để khẳng định kỳ sau sẽ ra số gì."]


def build_chain(type_key, draws, limit=20, include_special=False, **kwargs):
    lead_counts = Counter()
    pair_counts = Counter()
    for index in range(len(draws) - 1):
        current = set(draws[index].get("numbers", []))
        nxt = set(draws[index + 1].get("numbers", []))
        if include_special and draws[index].get("special"):
            current.add(f"ĐB {draws[index]['special']}")
        if include_special and draws[index + 1].get("special"):
            nxt.add(f"ĐB {draws[index + 1]['special']}")
        for lead in current:
            lead_counts[lead] += 1
            for follow in nxt:
                pair_counts[(lead, follow)] += 1
    rows = []
    for (lead, follow), count in pair_counts.items():
        lead_count = max(1, lead_counts.get(lead, 0))
        rows.append({
            "leadNumber": lead,
            "followNumber": follow,
            "count": int(count),
            "leadCount": int(lead_count),
            "probability": round(count / lead_count, 6),
        })
    rows.sort(key=lambda item: (-item["probability"], -item["count"], item["leadNumber"], item["followNumber"]))
    data = {
        "topChains": rows[:max(1, min(100, int(limit or 20)))],
        "explanation": "Lead & Follow đếm số B xuất hiện ở kỳ kế tiếp khi A xuất hiện ở kỳ hiện tại.",
    }
    return data, [data["explanation"]]


def build_relationships(type_key, draws, combo_size=2, limit=20, **kwargs):
    pair_counts = Counter()
    triple_counts = Counter()
    single_counts = frequency_counts(draws)
    for draw in draws:
        numbers = sorted(set(draw.get("numbers", [])), key=token_to_int)
        for pair in combinations(numbers, 2):
            pair_counts[pair] += 1
        for triple in combinations(numbers, 3):
            triple_counts[triple] += 1
    pair_avg = mean(pair_counts.values()) if pair_counts else 0
    pairs = [
        {"numbers": list(pair), "pair": "-".join(pair), "count": count}
        for pair, count in pair_counts.items()
    ]
    pairs.sort(key=lambda item: (-item["count"], item["pair"]))
    triples = [
        {"numbers": list(triple), "triple": "-".join(triple), "count": count}
        for triple, count in triple_counts.items()
    ]
    triples.sort(key=lambda item: (-item["count"], item["triple"]))
    top_singles = [item["number"] for item in top_count_items(single_counts, 30, True)]
    incompatible = []
    for a, b in combinations(top_singles, 2):
        pair = tuple(sorted((a, b), key=token_to_int))
        count = int(pair_counts.get(pair, 0))
        if count <= max(1, pair_avg * 0.25):
            incompatible.append({"numbers": list(pair), "pair": "-".join(pair), "count": count})
    incompatible.sort(key=lambda item: (item["count"], item["pair"]))
    data = {
        "coOccurrencePairs": pairs[:max(1, min(100, int(limit or 20)))],
        "frequentTriples": triples[:max(1, min(100, int(limit or 20)))],
        "incompatiblePairs": incompatible[:max(1, min(100, int(limit or 20)))],
        "pairCount": len(pair_counts),
        "tripleCount": len(triple_counts),
        "averagePairCount": round(pair_avg, 4),
        "requestedComboSize": int(combo_size or 2),
        "explanation": "Quan hệ cặp/bộ ba dựa trên đồng xuất hiện trong cùng một kỳ.",
    }
    return data, [data["explanation"]]


def build_modulo(type_key, draws, **kwargs):
    values = [token_to_int(number) for draw in draws for number in draw.get("numbers", [])]
    latest = latest_numbers(draws[-1] if draws else None)
    def dist(mod):
        return {str(index): sum(1 for value in values if value % mod == index) for index in range(mod)}
    unit = {str(index): sum(1 for value in values if value % 10 == index) for index in range(10)}
    blank_mod3 = [key for key, count in dist(3).items() if count == 0]
    latest_pattern = {
        "mod3": "-".join(str(sum(1 for value in latest if value % 3 == index)) for index in range(3)),
        "mod5": "-".join(str(sum(1 for value in latest if value % 5 == index)) for index in range(5)),
    }
    data = {
        "mod3": dist(3),
        "mod5": dist(5),
        "unitDigits": unit,
        "positionalModulo": latest_pattern,
        "blankModuloZones": {"mod3": blank_mod3},
        "explanation": "Modulo và đuôi số giúp quan sát độ phủ phần dư, không phải tín hiệu chắc chắn.",
    }
    return data, [data["explanation"]]


def is_prime(number):
    if number < 2:
        return False
    for candidate in range(2, int(math.sqrt(number)) + 1):
        if number % candidate == 0:
            return False
    return True


def compute_beauty_score(type_key, draw):
    cfg = GAME_CONFIGS[type_key]
    numbers = latest_numbers(draw)
    if not numbers:
        return {"beautyScore": 0, "components": {}}
    features = draw_features(type_key, draw)
    count = len(numbers)
    even_balance = 1 - abs(features["evenCount"] - features["oddCount"]) / max(1, count)
    low_balance = 1 - abs(features["lowCount"] - features["highCount"]) / max(1, count)
    all_sums = [sum(latest_numbers(item)) for item in [draw]]
    sum_score = 1.0 if all_sums else 0.5
    max_run = max([len(run) for run in consecutive_runs(numbers)], default=1)
    sequence_score = 1.0 if max_run <= 3 else 0.35
    mod_counts = [sum(1 for value in numbers if value % 3 == index) for index in range(3)]
    modulo_score = 1 - (max(mod_counts) - min(mod_counts)) / max(1, count)
    gaps = [b - a for a, b in zip(sorted(numbers), sorted(numbers)[1:])]
    gap_score = 1 - (sum(1 for gap in gaps if gap <= 1) / max(1, len(gaps)))
    components = {
        "balanceEvenOdd": round(even_balance * 20, 2),
        "balanceLowHigh": round(low_balance * 20, 2),
        "sumZone": round(sum_score * 20, 2),
        "sequence": round(sequence_score * 15, 2),
        "modulo": round(modulo_score * 15, 2),
        "gap": round(gap_score * 10, 2),
    }
    return {"beautyScore": round(sum(components.values()), 2), "components": components}


def build_advanced(type_key, draws, **kwargs):
    cfg = GAME_CONFIGS[type_key]
    latest = draws[-1] if draws else None
    numbers = latest_numbers(latest)
    tokens = list((latest or {}).get("numbers", []))
    prime_tokens = [format_token(number, cfg["width"]) for number in numbers if is_prime(number)]
    max_number = int(cfg["main_max"])
    token_set = set(tokens)
    shadows = []
    inverted = []
    slides = []
    for token in tokens:
        number = token_to_int(token)
        shadow = format_token(max_number + int(cfg["main_min"]) - number, cfg["width"])
        if shadow in token_set and shadow != token:
            shadows.append([token, shadow])
        if cfg["width"] == 2:
            rev = format_token(str(token).zfill(2)[::-1], cfg["width"])
            if rev in token_set and rev != token:
                inverted.append([token, rev])
        if format_token(number - 1, cfg["width"]) in token_set:
            slides.append([format_token(number - 1, cfg["width"]), token])
        if format_token(number + 1, cfg["width"]) in token_set:
            slides.append([token, format_token(number + 1, cfg["width"])])
    score = compute_beauty_score(type_key, latest)
    data = {
        "span": draw_features(type_key, latest)["span"],
        "primeNumbers": prime_tokens,
        "primeCount": len(prime_tokens),
        "shadowPairs": shadows,
        "invertedPairs": inverted,
        "slideNumbers": slides,
        "beautyScore": score["beautyScore"],
        "components": score["components"],
        "explanation": "Nâng cao gom các dấu hiệu cấu trúc: nguyên tố, bóng gương, đảo số, trượt cạnh và điểm cân bằng.",
    }
    return data, [data["explanation"]]


def build_special(type_key, draws, limit=20, **kwargs):
    cfg = GAME_CONFIGS[type_key]
    if not cfg.get("has_special"):
        return {
            "supported": False,
            "message": "Loại vé hiện tại không có số đặc biệt để phân tích riêng.",
            "explanation": "Không trộn số đặc biệt vào số chính.",
        }, ["Không trộn số đặc biệt vào số chính."]
    counts = frequency_counts(draws, special=True)
    universe = number_universe(type_key, True)
    expected = len(draws) / max(1, len(universe))
    overdue, _ = build_overdue(type_key, draws, limit=limit, special=True)
    data = {
        "specialFrequency": [{"number": number, "count": int(counts.get(number, 0))} for number in universe],
        "specialExpected": round(expected, 4),
        "specialCurrentSkip": overdue["topOverdue"][0]["currentSkip"] if overdue["topOverdue"] else 0,
        "specialMaxSkip": overdue["topOverdue"][0]["maxSkip"] if overdue["topOverdue"] else 0,
        "specialAvgGap": overdue["topOverdue"][0]["avgGap"] if overdue["topOverdue"] else None,
        "specialOverdueIndex": overdue["topOverdue"][0]["overdueIndex"] if overdue["topOverdue"] else 0,
        "topSpecialHot": top_count_items(counts, 10, True),
        "topSpecialCold": top_count_items(Counter({number: counts.get(number, 0) for number in universe}), 10, False),
        "topSpecialOverdue": overdue["topOverdue"],
        "explanation": "Số đặc biệt được tính riêng, không trộn vào dãy số chính.",
    }
    return data, [data["explanation"]]


def build_weekday(type_key, draws, limit=10, **kwargs):
    grouped = defaultdict(list)
    for draw in draws:
        weekday = draw.get("weekday") or draw["date"].strftime("%A")
        grouped[weekday].append(draw)
    stats = []
    top_by_weekday = {}
    for weekday, items in grouped.items():
        counts = frequency_counts(items)
        top = top_count_items(counts, limit, True)
        top_by_weekday[weekday] = top
        stats.append({"weekday": weekday, "drawCount": len(items), "topNumbers": top[:5]})
    stats.sort(key=lambda item: item["weekday"])
    latest_weekday = (draws[-1].get("weekday") if draws else "") or ""
    data = {
        "weekdayStats": stats,
        "topNumbersByWeekday": top_by_weekday,
        "currentWeekdaySuggestion": {
            "weekday": latest_weekday,
            "numbers": top_by_weekday.get(latest_weekday, [])[:10],
        },
        "explanation": "Theo thứ nhóm các kỳ cùng ngày trong tuần để quan sát nhịp lịch.",
    }
    return data, [data["explanation"]]


def parse_input_numbers(text, type_key):
    cfg = GAME_CONFIGS[type_key]
    values = []
    for number in parse_number_tokens(text):
        if int(cfg["main_min"]) <= number <= int(cfg["main_max"]):
            values.append(format_token(number, int(cfg["width"])))
    return sorted(set(values), key=token_to_int)


def build_smart_wheel(type_key, draws, limit=20, numbers="", pick=0, max_tickets=20, **kwargs):
    cfg = GAME_CONFIGS[type_key]
    pick = int(pick or cfg["main_count"] or 6)
    pick = max(1, min(10, pick))
    max_tickets = max(1, min(50, int(max_tickets or 20)))
    pool = parse_input_numbers(numbers, type_key)
    if not pool:
        counts = frequency_counts(draws)
        hot = [item["number"] for item in top_count_items(counts, 8, True)]
        cold = [item["number"] for item in top_count_items(Counter({n: counts.get(n, 0) for n in number_universe(type_key, False)}), 8, False)]
        pool = sorted(set(hot[:6] + cold[:6]), key=token_to_int)
    pool = pool[:12]
    if len(pool) < pick:
        return {
            "selectedPool": pool,
            "generatedTickets": [],
            "filtersApplied": ["Không đủ pool để tạo vé"],
            "disabled": True,
            "explanation": "Smart Wheel cần pool đủ lớn; bản đầu giới hạn pool tối đa 12 số và maxTickets tối đa 50.",
        }, ["Smart Wheel bản đầu chỉ tạo mẫu nhẹ, không chạy tổ hợp quá lớn."]
    tickets = []
    for combo in combinations(pool, pick):
        tickets.append(list(combo))
        if len(tickets) >= max_tickets:
            break
    data = {
        "selectedPool": pool,
        "generatedTickets": tickets,
        "filtersApplied": ["pool tối đa 12 số", "maxTickets tối đa 50", "lấy mẫu tổ hợp đầu sau khi sắp số"],
        "explanation": "Smart Wheel chỉ tạo bộ tham khảo từ pool thống kê, không cam kết dự đoán trúng.",
    }
    return data, [data["explanation"]]


def build_score(type_key, draws, numbers="", **kwargs):
    latest = draws[-1] if draws else None
    if numbers:
        parsed = parse_input_numbers(numbers, type_key)
        latest = dict(latest or {})
        latest["numbers"] = parsed
    beauty = compute_beauty_score(type_key, latest)
    components = beauty["components"]
    balance = components.get("balanceEvenOdd", 0) + components.get("balanceLowHigh", 0)
    data = {
        "numbers": list((latest or {}).get("numbers", [])),
        "balanceScore": round(balance, 2),
        "sumScore": components.get("sumZone", 0),
        "gapScore": components.get("gap", 0),
        "distributionScore": components.get("modulo", 0),
        "relationshipScore": components.get("sequence", 0),
        "beautyScore": beauty["beautyScore"],
        "finalScore": max(0, min(100, round(beauty["beautyScore"], 2))),
        "explanation": "Điểm số chỉ đo độ cân bằng cấu trúc của bộ số, không phải xác suất trúng thưởng.",
    }
    return data, [data["explanation"]]


MODE_BUILDERS = {
    "overview": build_overview,
    "general": build_general,
    "distribution": build_distribution,
    "ratios": build_ratios,
    "latest_draw": build_latest_draw,
    "consecutive": build_consecutive,
    "overdue": build_overdue,
    "poisson": build_poisson,
    "knn": build_knn,
    "chain": build_chain,
    "relationships": build_relationships,
    "modulo": build_modulo,
    "advanced": build_advanced,
    "special": build_special,
    "weekday": build_weekday,
    "smart_wheel": build_smart_wheel,
    "score": build_score,
}


def build_all(type_key, draws, limit=10, k=5, combo_size=2, include_special=True, numbers="", pick=0, max_tickets=20):
    data = {}
    explanations = []
    for mode in ("overview", "general", "ratios", "overdue", "poisson", "knn", "relationships", "advanced", "score"):
        builder = MODE_BUILDERS[mode]
        mode_data, mode_explanations = builder(
            type_key,
            draws,
            limit=limit,
            k=k,
            combo_size=combo_size,
            include_special=include_special,
            numbers=numbers,
            pick=pick,
            max_tickets=max_tickets,
        )
        if mode == "overdue":
            mode_data = {"topOverdue": mode_data.get("topOverdue", [])[:10], "explanation": mode_data.get("explanation", "")}
        if mode == "poisson":
            mode_data = {"lambda": mode_data.get("lambda"), "items": mode_data.get("items", [])[:10], "explanation": mode_data.get("explanation", "")}
        if mode == "relationships":
            mode_data = {
                "coOccurrencePairs": mode_data.get("coOccurrencePairs", [])[:10],
                "frequentTriples": mode_data.get("frequentTriples", [])[:10],
                "incompatiblePairs": mode_data.get("incompatiblePairs", [])[:10],
                "explanation": mode_data.get("explanation", ""),
            }
        data[mode] = mode_data
        explanations.extend(mode_explanations[:1])
    data["smart_wheel"] = {
        "disabled": True,
        "message": "Smart Wheel ở mode all chỉ hiển thị tóm tắt để tránh chạy tổ hợp nặng.",
    }
    return data, explanations


def build_analysis_payload(
    type_key,
    period="30d",
    mode="overview",
    from_date="",
    to_date="",
    limit=20,
    k=5,
    combo_size=2,
    include_special=True,
    numbers="",
    pick=0,
    max_tickets=20,
    csv_path=None,
):
    normalized_type = normalize_type(type_key)
    if normalized_type not in SUPPORTED_TYPES:
        return {"ok": False, "message": "Loại vé phân tích không hợp lệ.", "warnings": []}
    mode = str(mode or "overview").strip().lower()
    if mode not in MODE_KEYS:
        mode = "overview"
    period = str(period or "30d").strip().lower()
    if period not in PERIOD_KEYS:
        period = "30d"
    limit = max(1, min(100, int(limit or 20)))
    k = max(1, min(20, int(k or 5)))
    combo_size = max(1, min(3, int(combo_size or 2)))
    warnings = []
    try:
        draws, source_path = load_draws(normalized_type, csv_path=csv_path)
    except Exception as exc:
        return {"ok": False, "message": f"Không đọc được dữ liệu canonical: {exc}", "warnings": []}
    if GAME_CONFIGS[normalized_type]["kind"] == "three_digit" and not any(draw.get("numbers") for draw in draws):
        return {
            "ok": False,
            "message": "Chức năng này chưa hỗ trợ đầy đủ cho loại vé hiện tại.",
            "warnings": ["CSV hiện tại chưa có đủ dữ liệu 3 chữ số trong cột Hiển thị."],
        }
    filtered, from_dt, to_dt = filter_draws_by_period(draws, period, from_date, to_date)
    if not filtered:
        return {"ok": False, "message": "Không đủ dữ liệu để phân tích.", "warnings": []}
    if mode == "special" and not GAME_CONFIGS[normalized_type].get("has_special"):
        return {
            "ok": False,
            "message": "Chức năng này chưa hỗ trợ đầy đủ cho loại vé hiện tại.",
            "warnings": ["Loại vé hiện tại không có số đặc biệt để phân tích riêng."],
        }
    if mode == "all":
        data, explanations = build_all(
            normalized_type, filtered, limit=10, k=k, combo_size=combo_size,
            include_special=include_special, numbers=numbers, pick=pick, max_tickets=max_tickets,
        )
    else:
        builder = MODE_BUILDERS[mode]
        data, explanations = builder(
            normalized_type,
            filtered,
            limit=limit,
            k=k,
            combo_size=combo_size,
            include_special=include_special,
            numbers=numbers,
            pick=pick,
            max_tickets=max_tickets,
        )
    if normalized_type.startswith("MAX_3D"):
        warnings.append("MAX 3D dùng dữ liệu parse từ cột Hiển thị; một số phân tích nâng cao chỉ mang tính cơ bản.")
    explanations = [DISCLAIMER, *[text for text in explanations if text and text != DISCLAIMER]]
    return {
        "ok": True,
        "type": normalized_type,
        "label": GAME_CONFIGS[normalized_type]["label"],
        "period": period,
        "mode": mode,
        "fromDate": date_iso(from_dt),
        "toDate": date_iso(to_dt),
        "totalDraws": len(filtered),
        "latestDraw": draw_to_json(filtered[-1]),
        "sourceFile": Path(source_path).name,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "data": data,
        "explanations": explanations,
        "warnings": warnings,
    }


def parse_args(argv):
    parser = argparse.ArgumentParser(description="DVLF Analysis")
    sub = parser.add_subparsers(dest="command")
    analysis = sub.add_parser("analysis_json")
    analysis.add_argument("--type", required=True)
    analysis.add_argument("--period", default="30d", choices=sorted(PERIOD_KEYS))
    analysis.add_argument("--mode", default="overview", choices=sorted(MODE_KEYS))
    analysis.add_argument("--from", dest="from_date", default="")
    analysis.add_argument("--to", dest="to_date", default="")
    analysis.add_argument("--limit", type=int, default=20)
    analysis.add_argument("--k", type=int, default=5)
    analysis.add_argument("--combo-size", type=int, default=2)
    analysis.add_argument("--include-special", default="true")
    analysis.add_argument("--numbers", default="")
    analysis.add_argument("--pick", type=int, default=0)
    analysis.add_argument("--max-tickets", type=int, default=20)
    return parser.parse_args(argv)


def truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    if args.command != "analysis_json":
        print(json.dumps({"ok": False, "message": "Thiếu lệnh analysis_json.", "warnings": []}, ensure_ascii=False))
        return 2
    try:
        payload = build_analysis_payload(
            args.type,
            period=args.period,
            mode=args.mode,
            from_date=args.from_date,
            to_date=args.to_date,
            limit=args.limit,
            k=args.k,
            combo_size=args.combo_size,
            include_special=truthy(args.include_special),
            numbers=args.numbers,
            pick=args.pick,
            max_tickets=args.max_tickets,
        )
    except Exception as exc:
        payload = {
            "ok": False,
            "message": "Không thể hoàn tất phân tích. Vui lòng kiểm tra dữ liệu đầu vào.",
            "warnings": [str(exc)[:180]],
        }
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
