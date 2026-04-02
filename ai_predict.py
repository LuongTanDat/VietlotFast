import json
import math
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import live_results as lr
import number_scoring as ns
import data_paths as dp


# ----- Cau hinh AI -----
# Tap trung cac hang so cho predictor classic, AI Gen Local va nguong du lieu toi thieu.
AI_SUPPORTED_TYPES = ("KENO", "LOTO_5_35", "LOTO_6_45", "LOTO_6_55", "MAX_3D", "MAX_3D_PRO")
AI_ENGINE_CLASSIC = "classic"
AI_ENGINE_GEN_LOCAL = "gen_local"
AI_ENGINE_LUAN_SO = "luan_so"
AI_RISK_MODE_STABLE = "stable"
AI_RISK_MODE_BALANCED = "balanced"
AI_RISK_MODE_AGGRESSIVE = "aggressive"
PREDICTION_MODE_NORMAL = "normal"
PREDICTION_MODE_VIP = "vip"
AI_ENGINE_LABELS = {
    AI_ENGINE_CLASSIC: "AI Lite hiện tại",
    AI_ENGINE_GEN_LOCAL: "AI Gen Local",
    AI_ENGINE_LUAN_SO: "Luận Số",
}
AI_RISK_MODE_LABELS = {
    AI_RISK_MODE_STABLE: "Ổn Định",
    AI_RISK_MODE_BALANCED: "Cân Bằng",
    AI_RISK_MODE_AGGRESSIVE: "Tấn Công",
}
AI_RECENT_LOOKBACK_DAYS = 7
AI_KENO_RECENT_LOOKBACK_DAYS = 2
AI_NUMERIC_MIN_HISTORY = 24
AI_KENO_MIN_HISTORY = 80
AI_NUMERIC_EVAL_SAMPLES = 96
AI_KENO_EVAL_SAMPLES = 240
AI_TOP_RANKING_COUNT = 20
AI_SPECIAL_TOP_COUNT = 10
SCORING_DEFAULT_RECENT_WINDOW_NUMERIC = 24
SCORING_DEFAULT_RECENT_WINDOW_KENO = 80
SCORING_DEFAULT_TOP_ROWS = 20
SCORING_DEFAULT_BACKTEST_TOP_K = {
    "LOTO_5_35": 5,
    "LOTO_6_45": 6,
    "LOTO_6_55": 6,
    "KENO": 20,
    "MAX_3D": 10,
    "MAX_3D_PRO": 10,
}
LUAN_SO_WINDOWS = (1, 2, 3, 4, 5)
LUAN_SO_ANALYSIS_LIMITS = {
    "LOTO_5_35": 528,
    "LOTO_6_45": 800,
    "LOTO_6_55": 800,
    "KENO": 3000,
    "MAX_3D": 720,
    "MAX_3D_PRO": 720,
}
LUAN_SO_MAX_STRONGEST_PAIRS = 120
LUAN_SO_REPORT_DRAW_PREVIEW = 120
LUAN_SO_REPORT_BASELINE_PREVIEW = 160
LUAN_SO_REPORT_MATRIX_PREVIEW = 10
GEN_LOCAL_MODEL_VERSION = "gen_local_v4_stable"
LUAN_SO_MODEL_VERSION = "luan_so_v3_stable"
ONLINE_META_MODEL_VERSION = "online_meta_v1_stable"
GEN_LOCAL_MODEL_DIR = Path(__file__).resolve().parent / "runtime_models"
SCORING_EXPORT_DIR = dp.get_scoring_export_dir()
GEN_LOCAL_NUMERIC_RECENT_WINDOW = 24
GEN_LOCAL_KENO_RECENT_WINDOW = 48
GEN_LOCAL_VERY_RECENT_NUMERIC_WINDOW = 10
GEN_LOCAL_VERY_RECENT_KENO_WINDOW = 20
GEN_LOCAL_MEDIUM_RECENT_NUMERIC_WINDOW = 56
GEN_LOCAL_MEDIUM_RECENT_KENO_WINDOW = 120
ONLINE_META_MIN_WEIGHT = 0.12
ONLINE_META_HISTORY_LIMIT = 120
META_EXPERT_GEN = AI_ENGINE_GEN_LOCAL
META_EXPERT_LUAN_SO = AI_ENGINE_LUAN_SO
META_EXPERT_BOTH = "both_combo"
META_EXPERT_KEYS = (META_EXPERT_GEN, META_EXPERT_LUAN_SO, META_EXPERT_BOTH)
META_STATE_STABLE = "stable"
META_STATE_WARMING = "warming"
META_STATE_VOLATILE = "volatile"
ONLINE_META_GAME_CONFIG = {
    "KENO": {
        "learningRate": 0.92,
        "weightDecay": 0.72,
        "minWeight": 0.12,
        "maxShift": 0.085,
        "warmDrift": 0.085,
        "volatileDrift": 0.145,
    },
    "LOTO_5_35": {
        "learningRate": 0.66,
        "weightDecay": 0.82,
        "minWeight": 0.14,
        "maxShift": 0.060,
        "warmDrift": 0.060,
        "volatileDrift": 0.115,
    },
    "LOTO_6_45": {
        "learningRate": 0.64,
        "weightDecay": 0.84,
        "minWeight": 0.14,
        "maxShift": 0.055,
        "warmDrift": 0.054,
        "volatileDrift": 0.105,
    },
    "LOTO_6_55": {
        "learningRate": 0.64,
        "weightDecay": 0.84,
        "minWeight": 0.14,
        "maxShift": 0.055,
        "warmDrift": 0.054,
        "volatileDrift": 0.105,
    },
    "MAX_3D": {
        "learningRate": 0.62,
        "weightDecay": 0.84,
        "minWeight": 0.14,
        "maxShift": 0.052,
        "warmDrift": 0.058,
        "volatileDrift": 0.112,
    },
    "MAX_3D_PRO": {
        "learningRate": 0.62,
        "weightDecay": 0.84,
        "minWeight": 0.14,
        "maxShift": 0.052,
        "warmDrift": 0.058,
        "volatileDrift": 0.112,
    },
}


def normalize_risk_mode(raw):
    value = str(raw or "").strip().lower().replace("-", "_")
    if not value:
        return AI_RISK_MODE_BALANCED
    if value in {"on_dinh", "stable_mode"}:
        return AI_RISK_MODE_STABLE
    if value in {"can_bang", "balance"}:
        return AI_RISK_MODE_BALANCED
    if value in {"tan_cong", "attack"}:
        return AI_RISK_MODE_AGGRESSIVE
    if value not in AI_RISK_MODE_LABELS:
        return AI_RISK_MODE_BALANCED
    return value


def build_risk_mode_summary(risk_mode):
    risk_mode = normalize_risk_mode(risk_mode)
    if risk_mode == AI_RISK_MODE_STABLE:
        return "Meta đang ưu tiên giữ nhịp và giảm dao động giữa 2 engine."
    if risk_mode == AI_RISK_MODE_AGGRESSIVE:
        return "Meta đang mở rộng cửa cho tín hiệu nóng và quota co giãn mạnh hơn."
    return "Meta đang giữ cân bằng giữa độ ổn định và cơ hội bùng nhịp."


def attach_risk_mode_metadata(payload, risk_mode):
    result = dict(payload or {})
    normalized = normalize_risk_mode(risk_mode)
    result["riskMode"] = normalized
    result["riskModeLabel"] = AI_RISK_MODE_LABELS.get(normalized, AI_RISK_MODE_LABELS[AI_RISK_MODE_BALANCED])
    result["riskModeSummary"] = build_risk_mode_summary(normalized)
    return result


def normalize_prediction_mode(raw):
    value = str(raw or "").strip().lower()
    return PREDICTION_MODE_VIP if value == PREDICTION_MODE_VIP else PREDICTION_MODE_NORMAL


def _ticket_top_coverage(ticket, top_numbers):
    main_values = [int(v) for v in list(ticket.get("main") or []) if isinstance(v, int)]
    if not main_values:
        return 0.0
    top_set = set(int(v) for v in list(top_numbers or []) if isinstance(v, int))
    return sum(1 for value in main_values if value in top_set) / max(1, len(main_values))


def apply_vip_prediction_profile(payload, bundle_count):
    result = dict(payload or {})
    tickets = list(result.get("tickets") or [])
    top_ranking = list(result.get("topRanking") or [])
    top_special = list(result.get("topSpecialRanking") or [])
    requested_count = max(1, min(3, int(bundle_count or 1)))
    if tickets:
        def ticket_score(ticket):
            coverage = _ticket_top_coverage(ticket, top_ranking[:20])
            special_bonus = 0.0
            special_value = ticket.get("special")
            if isinstance(special_value, int) and special_value in top_special[:6]:
                special_bonus = 0.18
            return coverage + special_bonus
        ranked = sorted(tickets, key=ticket_score, reverse=True)
        result["tickets"] = ranked[:requested_count]
    result["topRanking"] = top_ranking[:20 if result.get("type") == "KENO" else 12]
    result["topSpecialRanking"] = top_special[:6]
    result["predictionMode"] = PREDICTION_MODE_VIP
    result["vipProfile"] = "strict_select"
    notes = list(result.get("notes") or [])
    result["notes"] = [
        f"Vip profile • strict_select • lọc gắt {len(result.get('tickets') or [])} bộ ưu tiên",
        *notes,
    ]
    result["vipSummary"] = f"Vip đang ưu tiên {len(result.get('tickets') or [])} bộ mạnh nhất từ lượt dự đoán hiện tại."
    return result
AI_GAME_CONFIG = {
    "LOTO_5_35": {"mainMax": 35, "mainCount": 5, "hasSpecial": True, "specialMin": 1, "specialMax": 12},
    "LOTO_6_45": {"mainMax": 45, "mainCount": 6, "hasSpecial": False, "specialMin": 0, "specialMax": 0},
    "LOTO_6_55": {"mainMax": 55, "mainCount": 6, "hasSpecial": True, "specialMin": 1, "specialMax": 55},
    "KENO": {"mainMax": 80, "mainCount": 20, "hasSpecial": False, "specialMin": 0, "specialMax": 0},
    "MAX_3D": {"mainMax": 999, "mainCount": 2, "hasSpecial": False, "specialMin": 0, "specialMax": 0},
    "MAX_3D_PRO": {"mainMax": 999, "mainCount": 2, "hasSpecial": False, "specialMin": 0, "specialMax": 0},
}
THREE_DIGIT_TYPES = {"MAX_3D", "MAX_3D_PRO"}
THREE_DIGIT_EVAL_TOP_SPAN = 12
THREE_DIGIT_STRATEGIES = [
    {
        "key": "3d_recent_hot",
        "label": "3D recent hot",
        "weights": {
            "recent6": 0.24,
            "recent12": 0.20,
            "recent24": 0.16,
            "global": 0.08,
            "weekday": 0.12,
            "digitRecent": 0.12,
            "digitWeekday": 0.10,
            "gap": -0.10,
            "last1": -0.18,
            "last2": -0.08,
        },
    },
    {
        "key": "3d_gap_recovery",
        "label": "3D gap recovery",
        "weights": {
            "recent6": 0.08,
            "recent12": 0.10,
            "recent24": 0.12,
            "global": 0.10,
            "weekday": 0.10,
            "digitRecent": 0.10,
            "digitWeekday": 0.08,
            "gap": 0.28,
            "last1": -0.20,
            "last2": -0.10,
        },
    },
    {
        "key": "3d_weekday_digits",
        "label": "3D weekday digits",
        "weights": {
            "recent6": 0.10,
            "recent12": 0.12,
            "recent24": 0.12,
            "global": 0.08,
            "weekday": 0.16,
            "digitRecent": 0.16,
            "digitWeekday": 0.18,
            "gap": 0.10,
            "last1": -0.14,
            "last2": -0.06,
        },
    },
]
THREE_DIGIT_LUAN_SO_STRATEGY = {
    "key": "3d_digit_flow",
    "label": "Luận Số 3D",
    "weights": {
        "recent6": 0.12,
        "recent12": 0.14,
        "recent24": 0.12,
        "global": 0.08,
        "weekday": 0.12,
        "digitRecent": 0.20,
        "digitWeekday": 0.18,
        "gap": 0.18,
        "last1": -0.10,
        "last2": -0.04,
    },
}

MAIN_STRATEGIES = [
    {
        "key": "recent_hot",
        "label": "Recent hot",
        "weights": {
            "recent5": 0.32,
            "recent10": 0.22,
            "recent20": 0.16,
            "recent50": 0.08,
            "recent100": 0.04,
            "global": 0.06,
            "trend": 0.18,
            "weekday": 0.12,
            "lag1": 0.12,
            "lagN": 0.05,
            "pairLast": 0.12,
            "gap": -0.08,
            "last1": -0.16,
            "last2": -0.08,
        },
    },
    {
        "key": "gap_recovery",
        "label": "Gap recovery",
        "weights": {
            "recent5": 0.08,
            "recent10": 0.10,
            "recent20": 0.12,
            "recent50": 0.08,
            "recent100": 0.06,
            "global": 0.08,
            "trend": 0.12,
            "weekday": 0.14,
            "lag1": 0.04,
            "lagN": 0.06,
            "pairLast": 0.08,
            "gap": 0.34,
            "selfRepeat": 0.06,
            "last1": -0.20,
            "last2": -0.10,
        },
    },
    {
        "key": "markov_transition",
        "label": "Markov transition",
        "weights": {
            "recent5": 0.14,
            "recent10": 0.12,
            "recent20": 0.08,
            "global": 0.04,
            "trend": 0.10,
            "weekday": 0.10,
            "lag1": 0.38,
            "lagN": 0.22,
            "pairLast": 0.24,
            "gap": 0.04,
            "selfRepeat": 0.10,
            "last1": 0.04,
        },
    },
    {
        "key": "hybrid_ai_lite",
        "label": "Hybrid AI-lite",
        "weights": {
            "recent5": 0.22,
            "recent10": 0.16,
            "recent20": 0.12,
            "recent50": 0.08,
            "recent100": 0.04,
            "global": 0.08,
            "trend": 0.14,
            "weekday": 0.10,
            "lag1": 0.20,
            "lagN": 0.12,
            "pairLast": 0.18,
            "gap": 0.12,
            "selfRepeat": 0.08,
            "last1": -0.08,
            "last2": -0.04,
        },
    },
]

SPECIAL_STRATEGIES = [
    {
        "key": "special_recent_hot",
        "label": "Special recent hot",
        "weights": {
            "recent5": 0.30,
            "recent10": 0.22,
            "recent20": 0.14,
            "recent50": 0.08,
            "global": 0.08,
            "trend": 0.18,
            "weekday": 0.16,
            "gap": -0.04,
            "last1": -0.10,
            "last2": -0.06,
        },
    },
    {
        "key": "special_gap_recovery",
        "label": "Special gap recovery",
        "weights": {
            "recent5": 0.06,
            "recent10": 0.08,
            "recent20": 0.10,
            "recent50": 0.08,
            "global": 0.08,
            "trend": 0.10,
            "weekday": 0.18,
            "gap": 0.42,
            "last1": -0.18,
            "last2": -0.12,
        },
    },
    {
        "key": "special_hybrid_ai_lite",
        "label": "Special hybrid AI-lite",
        "weights": {
            "recent5": 0.18,
            "recent10": 0.14,
            "recent20": 0.12,
            "recent50": 0.08,
            "global": 0.10,
            "trend": 0.14,
            "weekday": 0.16,
            "gap": 0.18,
            "lag1": 0.12,
            "lagN": 0.08,
            "last1": -0.08,
            "last2": -0.05,
        },
    },
]


# ----- Ham co ban -----
# Cac ham chuan hoa gia tri dau vao, thoi gian va validate engine AI.
def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def canonical_history_path(type_key):
    return lr.get_canonical_output_paths(type_key)["all"]


def read_ai_source_meta(type_key):
    return lr.read_canonical_meta(type_key)


def sync_summary_is_ready(sync_summary):
    return bool(sync_summary.get("bootstrapComplete")) or bool(sync_summary.get("sourceLimited"))


def normalize_positive_int(raw_value, field_name):
    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} phải là số nguyên dương.") from exc
    if value <= 0:
        raise ValueError(f"{field_name} phải lớn hơn 0.")
    return value


def normalize_engine(raw_value):
    value = str(raw_value or AI_ENGINE_CLASSIC).strip().lower().replace("-", "_")
    if value in {"gen", "genlocal", "gen_local"}:
        value = AI_ENGINE_GEN_LOCAL
    if value in {"luanso", "luan_so", "luan so"}:
        value = AI_ENGINE_LUAN_SO
    if value not in AI_ENGINE_LABELS:
        raise ValueError("Engine AI không hợp lệ. Dùng classic, gen_local hoặc luan_so.")
    return value


def clamp01(value):
    return max(0.0, min(1.0, float(value or 0.0)))


def normalize_optional_positive_int(raw_value, field_name):
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return None
    return normalize_positive_int(text, field_name)


def default_scoring_recent_window(type_key):
    return SCORING_DEFAULT_RECENT_WINDOW_KENO if type_key == "KENO" else SCORING_DEFAULT_RECENT_WINDOW_NUMERIC


def default_scoring_backtest_top_k(type_key):
    return int(SCORING_DEFAULT_BACKTEST_TOP_K.get(type_key, AI_GAME_CONFIG.get(type_key, {}).get("mainCount", 6) or 6))


def build_scoring_number_formatter(type_key):
    if is_three_digit_type(type_key):
        return lambda value: f"{int(value):03d}"
    return lambda value: str(int(value))


def build_scoring_universe(type_key):
    if is_three_digit_type(type_key):
        return range(0, 1000)
    cfg = AI_GAME_CONFIG[type_key]
    return range(1, int(cfg["mainMax"]) + 1)


def build_scoring_draws(draws):
    items = []
    for draw in draws or []:
        numbers = sorted({int(value) for value in list(draw.get("main") or []) if isinstance(value, int)})
        items.append({
            "draw_id": str(draw.get("ky", "")).strip(),
            "draw_date": str(draw.get("date", "")).strip(),
            "numbers": numbers,
        })
    return items


# ----- Nap du lieu va tom tat sync -----
# Doc canonical all_day, chuan hoa thanh sync summary va xac dinh AI da san sang hay chua.
def safe_rate(hit_count, target_size):
    if target_size <= 0:
        return 0.0
    return float(hit_count or 0) / float(target_size)


def recent_window_for_type(type_key):
    return GEN_LOCAL_KENO_RECENT_WINDOW if type_key == "KENO" else GEN_LOCAL_NUMERIC_RECENT_WINDOW


def load_ai_source_rows(type_key):
    rows_by_ky, normalized_meta, _ = lr.load_canonical_rows(type_key)
    return rows_by_ky, normalized_meta


def build_sync_summary(type_key, rows_by_ky, meta):
    latest_row, earliest_row = lr.get_latest_and_earliest_rows(rows_by_ky)
    earliest_date = lr.parse_csv_date(earliest_row.get("Ngay", ""))
    return {
        "type": type_key,
        "label": lr.LIVE_TYPES[type_key].label,
        "historyFile": canonical_history_path(type_key).name,
        "historyCount": len(rows_by_ky),
        "seedFiles": [canonical_history_path(type_key).name],
        "newRows": 0,
        "updatedRows": 0,
        "repairedDates": 0,
        "repairedKyGaps": 0,
        "latestKy": str(latest_row.get("Ky", "")).strip(),
        "latestDate": str(latest_row.get("Ngay", "")).strip(),
        "latestTime": str(latest_row.get("Time", "")).strip(),
        "effectiveEarliestKy": str(earliest_row.get("Ky", "")).strip(),
        "effectiveEarliestDate": lr.format_csv_date(earliest_date) if earliest_date else "",
        "bootstrapComplete": bool(meta.get("bootstrapComplete")),
        "requestedStartMode": str(meta.get("requestedStartMode", lr.FULL_HISTORY_REQUESTED_START_MODE)),
        "sourceLimited": bool(meta.get("sourceLimited", False)),
        "errors": [],
        "syncedAt": now_iso(),
    }


def sync_ai_history(type_key):
    if type_key not in AI_SUPPORTED_TYPES:
        raise ValueError("Loại AI không được hỗ trợ.")
    rows_by_ky, meta = load_ai_source_rows(type_key)
    return build_sync_summary(type_key, rows_by_ky, meta)


def parse_numeric_draws(rows_by_ky):
    draws = []
    sorted_rows = sorted(
        rows_by_ky.values(),
        key=lambda item: lr.sort_key_from_ky(item.get("Ky", "")),
    )
    for row in sorted_rows:
        date_obj = lr.parse_csv_date(row.get("Ngay", ""))
        if date_obj is None:
            continue
        main = [
            int(token) for token in str(row.get("Main", "")).split(",")
            if str(token).strip().isdigit()
        ]
        if not main:
            continue
        special_raw = str(row.get("Special", "")).strip()
        draws.append({
            "ky": str(row.get("Ky", "")).strip(),
            "date": str(row.get("Ngay", "")).strip(),
            "time": str(row.get("Time", "")).strip(),
            "date_obj": date_obj,
            "weekday": date_obj.weekday(),
            "main": sorted(main),
            "special": int(special_raw) if special_raw.isdigit() else None,
        })
    return draws


def parse_keno_draws(rows_by_ky):
    draws = []
    sorted_rows = sorted(
        rows_by_ky.values(),
        key=lambda item: lr.sort_key_from_ky(item.get("Ky", "")),
    )
    for row in sorted_rows:
        date_obj = lr.parse_csv_date(row.get("Ngay", ""))
        if date_obj is None:
            continue
        main = [
            int(token) for token in str(row.get("Numbers", "")).split(",")
            if str(token).strip().isdigit()
        ]
        if len(main) != 20:
            continue
        draws.append({
            "ky": str(row.get("Ky", "")).strip(),
            "date": str(row.get("Ngay", "")).strip(),
            "time": str(row.get("Time", "")).strip(),
            "date_obj": date_obj,
            "weekday": date_obj.weekday(),
            "main": sorted(main),
            "special": None,
        })
    return draws


def is_three_digit_type(type_key):
    return str(type_key or "").strip().upper() in THREE_DIGIT_TYPES


def parse_three_digit_draws(rows_by_ky):
    draws = []
    sorted_rows = sorted(
        rows_by_ky.values(),
        key=lambda item: lr.sort_key_from_ky(item.get("Ky", "")),
    )
    for row in sorted_rows:
        date_obj = lr.parse_csv_date(row.get("Ngay", ""))
        if date_obj is None:
            continue
        display_lines = [
            part.strip() for part in str(row.get("DisplayLines", "")).split("||")
            if part.strip()
        ]
        main = lr.extract_three_digit_numbers_from_display_lines(display_lines)
        if not main:
            continue
        draws.append({
            "ky": str(row.get("Ky", "")).strip(),
            "date": str(row.get("Ngay", "")).strip(),
            "time": str(row.get("Time", "")).strip(),
            "date_obj": date_obj,
            "weekday": date_obj.weekday(),
            "main": main,
            "special": None,
            "displayLines": display_lines,
        })
    return draws


def load_ai_draws(type_key):
    path = canonical_history_path(type_key)
    if type_key == "KENO":
        return parse_keno_draws(lr.load_keno_csv_rows(path))
    if is_three_digit_type(type_key):
        return parse_three_digit_draws(lr.load_csv_rows(path))
    return parse_numeric_draws(lr.load_csv_rows(path))


def split_three_digit_number(number):
    value = max(0, min(999, int(number or 0)))
    return value // 100, (value // 10) % 10, value % 10


def build_three_digit_digit_profile(draws):
    profile = [[0 for _ in range(10)] for _ in range(3)]
    total = 0
    for draw in draws or []:
        for number in set(int(value) for value in (draw.get("main") or [])):
            digits = split_three_digit_number(number)
            for index, digit in enumerate(digits):
                profile[index][digit] += 1
            total += 1
    return profile, total


def build_three_digit_context(draws, target_weekday):
    draw_list = list(draws or [])
    draw_count = len(draw_list)
    global_counts = [0] * 1000
    weekday_counts = [0] * 1000
    last_seen = [-1] * 1000
    weekday_draw_count = 0
    for index, draw in enumerate(draw_list):
        numbers = set(int(value) for value in (draw.get("main") or []))
        if draw.get("weekday") == target_weekday:
            weekday_draw_count += 1
        for number in numbers:
            if number < 0 or number > 999:
                continue
            global_counts[number] += 1
            last_seen[number] = index
            if draw.get("weekday") == target_weekday:
                weekday_counts[number] += 1

    def build_window_counts(window_size):
        counts = [0] * 1000
        sample = draw_list[-max(1, int(window_size or 1)):]
        for draw in sample:
            for number in set(int(value) for value in (draw.get("main") or [])):
                if 0 <= number <= 999:
                    counts[number] += 1
        return counts, len(sample)

    recent6, recent6_total = build_window_counts(6)
    recent12, recent12_total = build_window_counts(12)
    recent24, recent24_total = build_window_counts(24)
    recent48, recent48_total = build_window_counts(48)
    digit_recent_profile, digit_recent_total = build_three_digit_digit_profile(draw_list[-24:])
    digit_weekday_profile, digit_weekday_total = build_three_digit_digit_profile(
        [draw for draw in draw_list if draw.get("weekday") == target_weekday]
    )
    last1 = set(int(value) for value in (draw_list[-1].get("main") or [])) if draw_list else set()
    last2 = set()
    for draw in draw_list[-2:]:
        last2.update(int(value) for value in (draw.get("main") or []))
    return {
        "drawCount": draw_count,
        "globalCounts": global_counts,
        "weekdayCounts": weekday_counts,
        "weekdayDrawCount": weekday_draw_count,
        "lastSeen": last_seen,
        "recent6": recent6,
        "recent6Total": recent6_total,
        "recent12": recent12,
        "recent12Total": recent12_total,
        "recent24": recent24,
        "recent24Total": recent24_total,
        "recent48": recent48,
        "recent48Total": recent48_total,
        "digitRecentProfile": digit_recent_profile,
        "digitRecentTotal": digit_recent_total,
        "digitWeekdayProfile": digit_weekday_profile,
        "digitWeekdayTotal": digit_weekday_total,
        "last1": last1,
        "last2": last2,
    }


def score_three_digit_candidate(candidate, context, strategy):
    number = int(candidate or 0)
    digits = split_three_digit_number(number)
    draw_count = max(1, int(context.get("drawCount") or 0))
    last_seen_index = int((context.get("lastSeen") or [-1])[number])
    gap = draw_count - 1 - last_seen_index if last_seen_index >= 0 else draw_count + 6
    digit_recent_profile = context.get("digitRecentProfile") or [[0] * 10 for _ in range(3)]
    digit_weekday_profile = context.get("digitWeekdayProfile") or [[0] * 10 for _ in range(3)]
    digit_recent_total = max(1, int(context.get("digitRecentTotal") or 0))
    digit_weekday_total = max(1, int(context.get("digitWeekdayTotal") or 0))
    features = {
        "recent6": float((context.get("recent6") or [0] * 1000)[number]) / max(1, int(context.get("recent6Total") or 0)),
        "recent12": float((context.get("recent12") or [0] * 1000)[number]) / max(1, int(context.get("recent12Total") or 0)),
        "recent24": float((context.get("recent24") or [0] * 1000)[number]) / max(1, int(context.get("recent24Total") or 0)),
        "recent48": float((context.get("recent48") or [0] * 1000)[number]) / max(1, int(context.get("recent48Total") or 0)),
        "global": float((context.get("globalCounts") or [0] * 1000)[number]) / draw_count,
        "weekday": float((context.get("weekdayCounts") or [0] * 1000)[number]) / max(1, int(context.get("weekdayDrawCount") or 0)),
        "gap": min(1.0, gap / 24.0),
        "last1": 1.0 if number in (context.get("last1") or set()) else 0.0,
        "last2": 1.0 if number in (context.get("last2") or set()) else 0.0,
        "digitRecent": sum(digit_recent_profile[index][digit] for index, digit in enumerate(digits)) / (3.0 * digit_recent_total),
        "digitWeekday": sum(digit_weekday_profile[index][digit] for index, digit in enumerate(digits)) / (3.0 * digit_weekday_total),
    }
    score = 0.0
    for key, weight in dict(strategy.get("weights") or {}).items():
        score += float(weight or 0.0) * float(features.get(key) or 0.0)
    return score


def rank_three_digit_candidates(draws, target_weekday, strategy):
    context = build_three_digit_context(draws, target_weekday)
    return sorted(
        range(1000),
        key=lambda number: (-score_three_digit_candidate(number, context, strategy), number),
    )


def evaluate_three_digit_strategies(draws, strategies, final_weekday, eval_top_span=THREE_DIGIT_EVAL_TOP_SPAN):
    min_history = max(AI_NUMERIC_MIN_HISTORY, 36)
    start_index = max(min_history, len(draws) - AI_NUMERIC_EVAL_SAMPLES)
    results = []
    for strategy in strategies:
        hits = []
        for index in range(start_index, len(draws)):
            history_entries = draws[:index]
            if len(history_entries) < min_history:
                continue
            ranking = rank_three_digit_candidates(history_entries, draws[index]["weekday"], strategy)[:eval_top_span]
            actual_set = set(int(value) for value in (draws[index].get("main") or []))
            hits.append(len(actual_set.intersection(ranking)))
        final_ranking = rank_three_digit_candidates(draws, final_weekday, strategy)
        samples = len(hits)
        avg_hits = (sum(hits) / samples) if samples else 0.0
        results.append({
            "key": str(strategy.get("key") or ""),
            "label": str(strategy.get("label") or ""),
            "samples": samples,
            "avgHits": avg_hits,
            "avgHitRate": safe_rate(avg_hits, eval_top_span),
            "hits": hits,
            "ranking": final_ranking,
        })
    results.sort(
        key=lambda item: (
            float(item.get("avgHitRate") or 0.0),
            float(item.get("avgHits") or 0.0),
            int(item.get("samples") or 0),
            str(item.get("label") or ""),
        ),
        reverse=True,
    )
    return results


# ----- Feature va danh gia chien luoc -----
# Xay state thong ke, tinh feature, cham diem ranking va backtest cac chien luoc.
def initialize_state(max_number, max_lag=2):
    return {
        "history_draws": [],
        "history_weekdays": [],
        "global_counts": [0.0] * (max_number + 1),
        "last_seen": [-1] * (max_number + 1),
        "transitions": [
            [[0 for _ in range(max_number + 1)] for _ in range(max_number + 1)]
            for _ in range(max_lag + 1)
        ],
        "transition_totals": [
            [0 for _ in range(max_number + 1)]
            for _ in range(max_lag + 1)
        ],
        "pair_counts": [
            [0 for _ in range(max_number + 1)]
            for _ in range(max_number + 1)
        ],
        "weekday_counts": [
            [0.0 for _ in range(max_number + 1)]
            for _ in range(7)
        ],
        "weekday_totals": [0 for _ in range(7)],
        "max_number": max_number,
        "max_lag": max_lag,
    }


def normalized_recent_counts(history_draws, max_number, window_size):
    counts = [0.0] * (max_number + 1)
    recent_draws = history_draws[-window_size:]
    if not recent_draws:
        return counts
    denominator = float(len(recent_draws))
    for draw in recent_draws:
        for number in draw:
            counts[number] += 1.0 / denominator
    return counts


def normalize_feature_values(values):
    if not values:
        return values
    max_value = max(values[1:] or [0.0])
    if max_value <= 0:
        return values
    return [0.0] + [value / max_value for value in values[1:]]


def compute_feature_scores(state, target_weekday):
    history_draws = state["history_draws"]
    total_history = len(history_draws)
    max_number = state["max_number"]
    features = {
        "recent5": normalized_recent_counts(history_draws, max_number, 5),
        "recent10": normalized_recent_counts(history_draws, max_number, 10),
        "recent20": normalized_recent_counts(history_draws, max_number, 20),
        "recent50": normalized_recent_counts(history_draws, max_number, 50),
        "recent100": normalized_recent_counts(history_draws, max_number, 100),
        "global": [0.0] * (max_number + 1),
        "gap": [0.0] * (max_number + 1),
        "trend": [0.0] * (max_number + 1),
        "weekday": [0.0] * (max_number + 1),
        "lag1": [0.0] * (max_number + 1),
        "lagN": [0.0] * (max_number + 1),
        "last1": [0.0] * (max_number + 1),
        "last2": [0.0] * (max_number + 1),
        "pairLast": [0.0] * (max_number + 1),
        "selfRepeat": [0.0] * (max_number + 1),
    }
    if total_history == 0:
        return features

    weekday_total = max(1, state["weekday_totals"][target_weekday])
    for number in range(1, max_number + 1):
        features["global"][number] = state["global_counts"][number] / total_history
        last_seen_index = state["last_seen"][number]
        features["gap"][number] = 1.0 if last_seen_index < 0 else min(total_history - last_seen_index, 100) / 100.0
        features["trend"][number] = features["recent10"][number] - features["recent50"][number]
        features["weekday"][number] = state["weekday_counts"][target_weekday][number] / weekday_total

    if history_draws:
        last_draw = history_draws[-1]
        for number in last_draw:
            features["last1"][number] = 1.0
        for base in last_draw:
            row = state["pair_counts"][base]
            for candidate in range(1, max_number + 1):
                if candidate == base:
                    continue
                features["pairLast"][candidate] += row[candidate]

    if len(history_draws) >= 2:
        for number in history_draws[-2]:
            features["last2"][number] = 1.0

    lookback = min(state["max_lag"], len(history_draws))
    for lag in range(1, lookback + 1):
        previous_draw = history_draws[-lag]
        lag_weight = (state["max_lag"] - lag + 1) / max(1, state["max_lag"])
        target_key = "lag1" if lag == 1 else "lagN"
        for previous_number in previous_draw:
            total_links = state["transition_totals"][lag][previous_number]
            if total_links <= 0:
                continue
            transition_row = state["transitions"][lag][previous_number]
            multiplier = lag_weight / total_links
            for candidate in range(1, max_number + 1):
                count = transition_row[candidate]
                if count:
                    features[target_key][candidate] += count * multiplier

    for number in range(1, max_number + 1):
        total_links = state["transition_totals"][1][number] if lookback >= 1 else 0
        if total_links:
            features["selfRepeat"][number] = state["transitions"][1][number][number] / total_links

    for key in ("lag1", "lagN", "pairLast"):
        features[key] = normalize_feature_values(features[key])
    return features


def update_state(state, actual_numbers, weekday):
    history_draws = state["history_draws"]
    lookback = min(state["max_lag"], len(history_draws))
    for lag in range(1, lookback + 1):
        previous_draw = history_draws[-lag]
        for previous_number in previous_draw:
            state["transition_totals"][lag][previous_number] += 1
            transition_row = state["transitions"][lag][previous_number]
            for candidate in actual_numbers:
                transition_row[candidate] += 1

    draw_index = len(history_draws)
    unique_numbers = sorted(set(int(number) for number in actual_numbers))
    for number in unique_numbers:
        state["global_counts"][number] += 1
        state["last_seen"][number] = draw_index
        state["weekday_counts"][weekday][number] += 1
    state["weekday_totals"][weekday] += 1

    for left in unique_numbers:
        row = state["pair_counts"][left]
        for right in unique_numbers:
            if left == right:
                continue
            row[right] += 1

    history_draws.append(unique_numbers)
    state["history_weekdays"].append(weekday)


def build_ranking_from_strategy(features, strategy, max_number):
    scores = [0.0] * (max_number + 1)
    for feature_name, feature_weight in strategy.get("weights", {}).items():
        feature_values = features.get(feature_name)
        if not feature_values or feature_weight == 0:
            continue
        for number in range(1, max_number + 1):
            scores[number] += feature_values[number] * feature_weight
    return sorted(
        range(1, max_number + 1),
        key=lambda number: (-scores[number], number),
    )


def evaluate_strategies(sequence_items, target_size, max_number, strategies, min_history, eval_limit, final_weekday):
    state = initialize_state(max_number)
    hits_by_strategy = {strategy["key"]: [] for strategy in strategies}
    evaluate_from = max(0, len(sequence_items) - eval_limit)

    for index, item in enumerate(sequence_items):
        actual_numbers = item["numbers"]
        actual_set = set(actual_numbers)
        if index >= evaluate_from and len(state["history_draws"]) >= min_history:
            features = compute_feature_scores(state, item["weekday"])
            for strategy in strategies:
                ranking = build_ranking_from_strategy(features, strategy, max_number)
                predicted = ranking[:target_size]
                hit_count = len(actual_set & set(predicted))
                hits_by_strategy[strategy["key"]].append(hit_count)
        update_state(state, actual_numbers, item["weekday"])

    final_features = compute_feature_scores(state, final_weekday)
    results = []
    for strategy in strategies:
        hits = hits_by_strategy[strategy["key"]]
        avg_hits = (sum(hits) / len(hits)) if hits else 0.0
        avg_hit_rate = (avg_hits / max(1, target_size)) if hits else 0.0
        results.append({
            "key": strategy["key"],
            "label": strategy["label"],
            "samples": len(hits),
            "avgHits": avg_hits,
            "avgHitRate": avg_hit_rate,
            "ranking": build_ranking_from_strategy(final_features, strategy, max_number),
            "hits": list(hits),
        })
    results.sort(
        key=lambda item: (
            item["avgHitRate"],
            item["avgHits"],
            item["samples"],
            item["label"],
        ),
        reverse=True,
    )
    return results


def build_numeric_main_items(draws):
    return [{"numbers": draw["main"], "weekday": draw["weekday"]} for draw in draws]


def build_numeric_special_items(draws):
    items = []
    for draw in draws:
        if draw["special"] is None:
            continue
        items.append({"numbers": [draw["special"]], "weekday": draw["weekday"]})
    return items


def next_target_weekday(type_key, latest_draw):
    if not latest_draw:
        return datetime.now().date().weekday()
    last_date = latest_draw["date_obj"]
    if type_key in {"KENO", "LOTO_5_35"}:
        return last_date.weekday()
    allowed = lr.HISTORY_WEEKDAY_FILTERS.get(type_key)
    if not allowed:
        return (last_date + timedelta(days=1)).weekday()
    cursor = last_date + timedelta(days=1)
    while cursor.weekday() not in allowed:
        cursor += timedelta(days=1)
    return cursor.weekday()


def next_prediction_ky(draws):
    if not draws:
        return ""
    digits = "".join(ch for ch in str(draws[-1].get("ky", "")) if ch.isdigit())
    if not digits:
        return ""
    return f"#{int(digits) + 1}"


# ----- Engine Luận Số -----
# Phân tích cặp điều kiện forward/backward, đo confidence-baseline-lift và dùng tín hiệu đó để chấm số cho kỳ kế tiếp.
def get_luan_so_relation_configs(type_key):
    cfg = AI_GAME_CONFIG[type_key]
    relations = [
        {
            "key": "main_main",
            "label": "Main->Main",
            "source_kind": "main",
            "target_kind": "main",
            "source_max": cfg["mainMax"],
            "target_max": cfg["mainMax"],
        }
    ]
    if cfg["hasSpecial"]:
        relations.extend([
            {
                "key": "main_db",
                "label": "Main->DB",
                "source_kind": "main",
                "target_kind": "special",
                "source_max": cfg["mainMax"],
                "target_max": cfg["specialMax"],
            },
            {
                "key": "db_main",
                "label": "DB->Main",
                "source_kind": "special",
                "target_kind": "main",
                "source_max": cfg["specialMax"],
                "target_max": cfg["mainMax"],
            },
            {
                "key": "db_db",
                "label": "DB->DB",
                "source_kind": "special",
                "target_kind": "special",
                "source_max": cfg["specialMax"],
                "target_max": cfg["specialMax"],
            },
        ])
    return relations


def get_relation_value_set(draw, kind):
    if kind == "main":
        return set(int(number) for number in (draw.get("main") or []) if isinstance(number, int))
    special = draw.get("special")
    return {int(special)} if isinstance(special, int) else set()


def limit_luan_so_draws(type_key, draws):
    limit = int(LUAN_SO_ANALYSIS_LIMITS.get(type_key) or 0)
    if limit <= 0 or len(draws) <= limit:
        return list(draws)
    return list(draws[-limit:])


def base_pair_note(label, lift, support_n, pair_count, confidence, baseline):
    if label == "Strong":
        return (
            f"Tín hiệu khá bền: lift {lift:.3f}x, support {support_n}, pair {pair_count}, "
            f"confidence {confidence:.3f} cao hơn baseline {baseline:.3f}."
        )
    if label == "Watchlist":
        return (
            f"Đáng theo dõi: lift {lift:.3f}x nhưng support/pair chưa thật dày "
            f"({support_n}/{pair_count})."
        )
    return (
        f"Tín hiệu mỏng hoặc gần nền: lift {lift:.3f}x, support {support_n}, pair {pair_count}."
    )


def classify_luan_so_pair(type_key, relation_key, support_n, pair_count, confidence, baseline, lift):
    delta = confidence - baseline
    if type_key == "KENO":
        strong = support_n >= 180 and pair_count >= 70 and lift >= 1.025 and delta >= 0.012
        watch = support_n >= 100 and pair_count >= 36 and lift >= 1.008 and delta >= 0.004
    elif relation_key in {"main_db", "db_main", "db_db"}:
        strong = support_n >= 18 and pair_count >= 6 and lift >= 1.22 and delta >= 0.04
        watch = support_n >= 10 and pair_count >= 3 and lift >= 1.08 and delta >= 0.015
    elif type_key == "LOTO_5_35":
        strong = support_n >= 26 and pair_count >= 8 and lift >= 1.20 and delta >= 0.05
        watch = support_n >= 15 and pair_count >= 4 and lift >= 1.06 and delta >= 0.018
    else:
        strong = support_n >= 28 and pair_count >= 8 and lift >= 1.16 and delta >= 0.034
        watch = support_n >= 16 and pair_count >= 4 and lift >= 1.05 and delta >= 0.012
    if strong:
        return "Strong"
    if watch:
        return "Watchlist"
    return "Weak/Noisy"


def apply_luan_so_shrinkage(type_key, relation_key, support_n, pair_count, confidence, baseline):
    if baseline <= 0:
        return confidence, 0.0, 0.0
    if type_key == "KENO":
        support_anchor = 220.0
        pair_anchor = 80.0
    elif relation_key in {"main_db", "db_main", "db_db"}:
        support_anchor = 22.0
        pair_anchor = 8.0
    elif type_key == "LOTO_5_35":
        support_anchor = 34.0
        pair_anchor = 10.0
    else:
        support_anchor = 38.0
        pair_anchor = 11.0
    shrink = min(0.96, (support_n / support_anchor) * 0.68 + (pair_count / pair_anchor) * 0.32)
    shrunk_confidence = baseline + (confidence - baseline) * max(0.0, shrink)
    delta = max(0.0, shrunk_confidence - baseline)
    lift = (shrunk_confidence / baseline) if baseline > 0 else 0.0
    return shrunk_confidence, lift, shrink


def build_luan_so_pair_rows(type_key, relation, source_sets, target_sets):
    total_draws = len(source_sets)
    rows = []
    matrix_map = {}
    baseline_map = {}
    strongest_rows = []

    for direction in ("forward", "backward"):
        for window in LUAN_SO_WINDOWS:
            support_counts = [0] * (relation["source_max"] + 1)
            baseline_counts = [0] * (relation["target_max"] + 1)
            pair_counts = [
                [0] * (relation["target_max"] + 1)
                for _ in range(relation["source_max"] + 1)
            ]
            valid_positions = 0

            if direction == "forward":
                for idx in range(total_draws):
                    start = idx + 1
                    end = min(total_draws - 1, idx + window)
                    if start > end:
                        continue
                    valid_positions += 1
                    future_targets = set()
                    for cursor in range(start, end + 1):
                        future_targets.update(target_sets[cursor])
                    for target in future_targets:
                        if 1 <= target <= relation["target_max"]:
                            baseline_counts[target] += 1
                    current_sources = source_sets[idx]
                    for source in current_sources:
                        if not (1 <= source <= relation["source_max"]):
                            continue
                        support_counts[source] += 1
                        row = pair_counts[source]
                        for target in future_targets:
                            if 1 <= target <= relation["target_max"]:
                                row[target] += 1
            else:
                for idx in range(total_draws):
                    start = max(0, idx - window)
                    end = idx - 1
                    if start > end:
                        continue
                    valid_positions += 1
                    previous_sources = set()
                    for cursor in range(start, end + 1):
                        previous_sources.update(source_sets[cursor])
                    current_targets = target_sets[idx]
                    for target in current_targets:
                        if 1 <= target <= relation["target_max"]:
                            baseline_counts[target] += 1
                    for source in previous_sources:
                        if not (1 <= source <= relation["source_max"]):
                            continue
                        support_counts[source] += 1
                        row = pair_counts[source]
                        for target in current_targets:
                            if 1 <= target <= relation["target_max"]:
                                row[target] += 1

            baseline_rows = []
            for target in range(1, relation["target_max"] + 1):
                baseline = (baseline_counts[target] / valid_positions) if valid_positions else 0.0
                if baseline <= 0:
                    continue
                baseline_rows.append({
                    "to_number": target,
                    "direction": direction,
                    "window": window,
                    "relation_kind": relation["key"],
                    "baseline": round(baseline, 6),
                    "valid_n": valid_positions,
                })
            baseline_map[(direction, window)] = baseline_rows

            confidence_matrix = [
                [0.0] * (relation["target_max"] + 1)
                for _ in range(relation["source_max"] + 1)
            ]
            lift_matrix = [
                [0.0] * (relation["target_max"] + 1)
                for _ in range(relation["source_max"] + 1)
            ]
            for source in range(1, relation["source_max"] + 1):
                support_n = support_counts[source]
                if support_n <= 0:
                    continue
                for target in range(1, relation["target_max"] + 1):
                    pair_count = pair_counts[source][target]
                    baseline = (baseline_counts[target] / valid_positions) if valid_positions else 0.0
                    confidence = (pair_count / support_n) if support_n else 0.0
                    adjusted_confidence, adjusted_lift, shrink_factor = apply_luan_so_shrinkage(
                        type_key,
                        relation["key"],
                        support_n,
                        pair_count,
                        confidence,
                        baseline,
                    )
                    confidence_matrix[source][target] = round(adjusted_confidence, 6)
                    lift_matrix[source][target] = round(adjusted_lift, 6) if adjusted_lift else 0.0
                    if pair_count <= 0 or baseline <= 0:
                        continue
                    label = classify_luan_so_pair(type_key, relation["key"], support_n, pair_count, adjusted_confidence, baseline, adjusted_lift)
                    row = {
                        "from_number": source,
                        "to_number": target,
                        "direction": direction,
                        "window": window,
                        "relation_kind": relation["key"],
                        "support_n": support_n,
                        "pair_count": pair_count,
                        "confidence": round(adjusted_confidence, 6),
                        "baseline": round(baseline, 6),
                        "lift": round(adjusted_lift, 6),
                        "rawConfidence": round(confidence, 6),
                        "shrinkFactor": round(shrink_factor, 6),
                        "label": label,
                        "note": base_pair_note(label, adjusted_lift, support_n, pair_count, adjusted_confidence, baseline),
                    }
                    rows.append(row)
                    if label != "Weak/Noisy":
                        strongest_rows.append(row)
            matrix_map[(direction, window)] = {
                "confidence": confidence_matrix,
                "lift": lift_matrix,
                "valid_n": valid_positions,
            }

    strongest_rows.sort(
        key=lambda item: (
            {"Strong": 2, "Watchlist": 1, "Weak/Noisy": 0}.get(item["label"], 0),
            item["lift"],
            item["pair_count"],
            item["support_n"],
            item["confidence"] - item["baseline"],
        ),
        reverse=True,
    )
    return {
        "rows": rows,
        "baseline": baseline_map,
        "matrices": matrix_map,
        "strongest_rows": strongest_rows[:LUAN_SO_MAX_STRONGEST_PAIRS],
    }


def build_luan_so_pair_index(relation_results):
    pair_index = defaultdict(list)
    directional_presence = defaultdict(set)
    for relation_key, result in relation_results.items():
        for row in result.get("rows") or []:
            if row["label"] == "Weak/Noisy" or row["lift"] <= 1.0:
                continue
            key = (relation_key, row["from_number"])
            pair_index[key].append(row)
            directional_presence[(relation_key, row["from_number"], row["to_number"])].add(row["direction"])
    return pair_index, directional_presence


def build_luan_so_strength(row, lag_distance, directional_presence):
    lift = float(row.get("lift") or 0.0)
    confidence = float(row.get("confidence") or 0.0)
    baseline = float(row.get("baseline") or 0.0)
    support_n = int(row.get("support_n") or 0)
    pair_count = int(row.get("pair_count") or 0)
    window = int(row.get("window") or 1)
    shrink_factor = float(row.get("shrinkFactor") or 0.0)
    delta = max(0.0, confidence - baseline)
    label_factor = 1.28 if row.get("label") == "Strong" else 0.82
    support_factor = min(1.35, math.log1p(max(0, support_n)) / 4.15)
    pair_factor = min(1.26, math.log1p(max(0, pair_count)) / 3.25)
    lag_factor = 1.0 / max(1.0, lag_distance ** 1.26)
    if row.get("direction") == "backward":
        window_factor = 1.04 + max(0, 5 - window) * 0.035
    else:
        window_factor = max(0.18, (window - lag_distance + 1) / max(1, window))
    base_score = max(0.0, (lift - 1.0) * 1.72 + delta * 6.0)
    strength = base_score * label_factor * support_factor * pair_factor * lag_factor * window_factor * max(0.54, shrink_factor)
    direction_count = len(directional_presence.get((row["relation_kind"], row["from_number"], row["to_number"]), set()))
    if direction_count > 1:
        strength *= 1.20
    else:
        strength *= 0.78
    if row.get("relation_kind") in {"main_db", "db_main", "db_db"}:
        strength *= 0.80
    return strength


def build_luan_so_top_numbers(type_key, draws, relation_results, recent_draw_count=5):
    relation_configs = {relation["key"]: relation for relation in get_luan_so_relation_configs(type_key)}
    pair_index, directional_presence = build_luan_so_pair_index(relation_results)
    main_scores = defaultdict(float)
    special_scores = defaultdict(float)
    evidence = []
    total_draws = len(draws)
    recent_draw_count = min(max(1, recent_draw_count), total_draws)

    for lag_distance in range(1, recent_draw_count + 1):
        draw = draws[-lag_distance]
        for relation_key, relation in relation_configs.items():
            trigger_numbers = get_relation_value_set(draw, relation["source_kind"])
            if not trigger_numbers:
                continue
            for source in trigger_numbers:
                for row in pair_index.get((relation_key, source), []):
                    if lag_distance > int(row.get("window") or 0):
                        continue
                    strength = build_luan_so_strength(row, lag_distance, directional_presence)
                    if strength <= 0:
                        continue
                    target = int(row["to_number"])
                    target_map = special_scores if relation["target_kind"] == "special" else main_scores
                    target_map[target] += strength
                    evidence.append({
                        "relation_kind": relation_key,
                        "from_number": source,
                        "to_number": target,
                        "direction": row["direction"],
                        "window": row["window"],
                        "lag": lag_distance,
                        "strength": round(strength, 6),
                        "label": row["label"],
                        "lift": row["lift"],
                        "confidence": row["confidence"],
                        "baseline": row["baseline"],
                    })

    def sort_ranking(score_map):
        return [number for number, _ in sorted(score_map.items(), key=lambda item: (-item[1], item[0]))]

    return {
        "mainRanking": sort_ranking(main_scores),
        "specialRanking": sort_ranking(special_scores),
        "mainScores": {str(key): round(value, 6) for key, value in sorted(main_scores.items())},
        "specialScores": {str(key): round(value, 6) for key, value in sorted(special_scores.items())},
        "evidence": sorted(evidence, key=lambda item: (-item["strength"], item["lag"], item["to_number"])),
    }


def summarize_luan_so_analysis(type_key, relation_results):
    strongest = []
    for result in relation_results.values():
        strongest.extend(result.get("strongest_rows") or [])
    strongest.sort(
        key=lambda item: (
            {"Strong": 2, "Watchlist": 1, "Weak/Noisy": 0}.get(item["label"], 0),
            item["lift"],
            item["pair_count"],
            item["support_n"],
        ),
        reverse=True,
    )
    pair_count = len(strongest)
    median_lift = 1.0
    if strongest:
        lifts = sorted(float(item["lift"]) for item in strongest)
        median_lift = lifts[len(lifts) // 2]
    strong_count = sum(1 for item in strongest if item["label"] == "Strong")
    watch_count = sum(1 for item in strongest if item["label"] == "Watchlist")
    lines = [
        "Đây là phân tích thống kê điều kiện, không phải dự đoán chắc chắn.",
        f"Đa số cặp số vẫn gần mức nền; nhóm nhô lên hiện có {pair_count} cặp đáng theo dõi.",
        f"Strong {strong_count} • Watchlist {watch_count} • median lift khoảng {median_lift:.3f}x.",
    ]
    if type_key == "KENO":
        lines.append("Keno ra 20 số mỗi kỳ nên lift thường chỉ nhích nhẹ quanh 1.00x; cần ưu tiên support lớn.")
    else:
        lines.append("Cặp đáng chú ý hơn là cặp có lift khá và support đủ dày, đặc biệt nếu sống được ở cả forward lẫn backward.")
    return lines, strongest[:LUAN_SO_MAX_STRONGEST_PAIRS]


def build_luan_so_report(type_key, draws, relation_results):
    normalized_draws = []
    for draw in draws:
        normalized_draws.append({
            "ky": draw["ky"],
            "date": draw["date"],
            "time": draw["time"],
            "weekday": draw["weekday"],
            "main": list(draw.get("main") or []),
            "special": draw.get("special"),
        })
    normalized_draw_preview = normalized_draws[-LUAN_SO_REPORT_DRAW_PREVIEW:]
    baseline_rows = []
    strongest_pairs = []
    confidence_matrix = {}
    lift_matrix = {}
    top_numbers = {}
    summary_lines, strongest = summarize_luan_so_analysis(type_key, relation_results)
    for relation_key, result in relation_results.items():
        for rows in (result.get("baseline") or {}).values():
            baseline_rows.extend(rows)
        strongest_pairs.extend(result.get("strongest_rows") or [])
        confidence_matrix[relation_key] = {}
        lift_matrix[relation_key] = {}
        for key, matrix_info in (result.get("matrices") or {}).items():
            direction, window = key
            matrix_key = f"{direction}_w{window}"
            confidence_rows = matrix_info.get("confidence") or []
            lift_rows = matrix_info.get("lift") or []
            confidence_matrix[relation_key][matrix_key] = {
                "size": len(confidence_rows),
                "preview": [row[:LUAN_SO_REPORT_MATRIX_PREVIEW] for row in confidence_rows[:LUAN_SO_REPORT_MATRIX_PREVIEW]],
            }
            lift_matrix[relation_key][matrix_key] = {
                "size": len(lift_rows),
                "preview": [row[:LUAN_SO_REPORT_MATRIX_PREVIEW] for row in lift_rows[:LUAN_SO_REPORT_MATRIX_PREVIEW]],
            }
        top_numbers[relation_key] = {
            "count": len(result.get("strongest_rows") or []),
            "top_pairs": (result.get("strongest_rows") or [])[:20],
        }
    strongest_pairs.sort(
        key=lambda item: (
            {"Strong": 2, "Watchlist": 1, "Weak/Noisy": 0}.get(item["label"], 0),
            item["lift"],
            item["pair_count"],
        ),
        reverse=True,
    )
    baseline_rows.sort(
        key=lambda item: (
            {"Strong": 2, "Watchlist": 1, "Weak/Noisy": 0}.get(str(item.get("label", "")).strip(), 0),
            float(item.get("lift") or 0.0),
            int(item.get("pair_count") or 0),
        ),
        reverse=True,
    )
    return {
        "normalized_draws": normalized_draw_preview,
        "normalized_draws_total": len(normalized_draws),
        "normalized_draws_preview_count": len(normalized_draw_preview),
        "baseline": baseline_rows[:LUAN_SO_REPORT_BASELINE_PREVIEW],
        "baseline_total": len(baseline_rows),
        "strongest_pairs": strongest_pairs[:LUAN_SO_MAX_STRONGEST_PAIRS],
        "confidence_matrix": confidence_matrix,
        "lift_matrix": lift_matrix,
        "top_numbers": top_numbers,
        "summary": {
            "lines": summary_lines,
            "strongest": strongest,
        },
    }


def choose_luan_so_champion(type_key, relation_results, evidence):
    relation_configs = {relation["key"]: relation["label"] for relation in get_luan_so_relation_configs(type_key)}
    rows = []
    for relation_key, result in relation_results.items():
        for row in result.get("strongest_rows") or []:
            rows.append((relation_key, row))
    if not rows:
        return {
            "key": "luan_so_conditional",
            "label": "Luận Số điều kiện",
            "direction": "",
            "window": 0,
            "relationKind": "",
            "strongPairs": 0,
            "watchPairs": 0,
            "topLift": 0.0,
            "topConfidence": 0.0,
            "topBaseline": 0.0,
            "topSupport": 0,
            "topPairCount": 0,
            "adaptiveScore": 0.0,
        }
    rows.sort(
        key=lambda item: (
            {"Strong": 2, "Watchlist": 1, "Weak/Noisy": 0}.get(item[1]["label"], 0),
            item[1]["lift"],
            item[1]["pair_count"],
            item[1]["support_n"],
        ),
        reverse=True,
    )
    relation_key, best = rows[0]
    direction_counts = defaultdict(int)
    window_counts = defaultdict(float)
    for item in evidence[:80]:
        direction_counts[item["direction"]] += 1
        window_counts[int(item["window"])] += float(item["strength"] or 0.0)
    dominant_direction = max(direction_counts, key=direction_counts.get) if direction_counts else best["direction"]
    dominant_window = max(window_counts, key=window_counts.get) if window_counts else int(best["window"])
    strong_pairs = sum(1 for _, row in rows if row["label"] == "Strong")
    watch_pairs = sum(1 for _, row in rows if row["label"] == "Watchlist")
    support_norm = min(1.0, float(best["support_n"]) / (260.0 if type_key == "KENO" else 90.0))
    pair_norm = min(1.0, float(best["pair_count"]) / (78.0 if type_key == "KENO" else 24.0))
    lift_norm = min(1.0, max(0.0, float(best["lift"]) - 1.0) / (0.30 if type_key == "KENO" else 0.65))
    coverage_norm = min(1.0, (strong_pairs + watch_pairs * 0.45) / (24.0 if type_key == "KENO" else 16.0))
    shrink_norm = min(1.0, float(best.get("shrinkFactor") or 0.0))
    adaptive_score = max(
        0.0,
        min(
            1.0,
            float(best["confidence"]) * 0.30 +
            support_norm * 0.24 +
            pair_norm * 0.18 +
            shrink_norm * 0.12 +
            lift_norm * 0.08 +
            coverage_norm * 0.08,
        ),
    )
    return {
        "key": "luan_so_conditional",
        "label": f"Luận Số • {relation_configs.get(relation_key, relation_key)}",
        "direction": dominant_direction,
        "window": dominant_window,
        "relationKind": relation_key,
        "strongPairs": strong_pairs,
        "watchPairs": watch_pairs,
        "topLift": float(best["lift"]),
        "topConfidence": float(best["confidence"]),
        "topBaseline": float(best["baseline"]),
        "topSupport": int(best["support_n"]),
        "topPairCount": int(best["pair_count"]),
        "topShrinkFactor": round(float(best.get("shrinkFactor") or 0.0), 6),
        "adaptiveScore": round(adaptive_score, 6),
    }


def compute_luan_so_confidence(type_key, champion, evidence):
    top_confidence = float(champion.get("topConfidence") or 0.0)
    adaptive_score = float(champion.get("adaptiveScore") or 0.0)
    strong_pairs = int(champion.get("strongPairs") or 0)
    watch_pairs = int(champion.get("watchPairs") or 0)
    support_norm = min(1.0, float(champion.get("topSupport") or 0) / (260.0 if type_key == "KENO" else 90.0))
    evidence_norm = min(1.0, len(list(evidence or [])) / (80.0 if type_key == "KENO" else 50.0))
    pair_coverage = min(1.0, (strong_pairs + watch_pairs * 0.32) / (22.0 if type_key == "KENO" else 14.0))
    shrink_norm = min(1.0, float(champion.get("topShrinkFactor") or 0.0))
    confidence = (
        top_confidence * 0.24 +
        adaptive_score * 0.24 +
        support_norm * 0.20 +
        shrink_norm * 0.14 +
        evidence_norm * 0.08 +
        pair_coverage * 0.10
    )
    return max(0.0, min(1.0, confidence))


def build_luan_so_notes(sync_summary, champion, evidence, type_key):
    notes = summarize_sync_notes(sync_summary)
    notes.insert(0, "Luận Số stable v3 dùng thống kê điều kiện cục bộ đã siết nhiễu và thêm lớp giữ nhịp để bớt dao động.")
    if champion.get("relationKind"):
        notes.append(
            f"Tín hiệu mạnh nhất hiện tại: {champion['label']} • {champion.get('direction', '')} • W={int(champion.get('window') or 0)}."
        )
    strong_pairs = int(champion.get("strongPairs") or 0)
    watch_pairs = int(champion.get("watchPairs") or 0)
    notes.append(f"Cặp Strong {strong_pairs} • Watchlist {watch_pairs}. Stable v3 ưu tiên support, pair_count, shrinkage và đồng thuận hai hướng.")
    if champion.get("adaptiveScore"):
        notes.append(
            f"Luận Số đang tự ưu tiên các tín hiệu bền hơn nền: support {int(champion.get('topSupport') or 0)} • pair_count {int(champion.get('topPairCount') or 0)} • shrink {float(champion.get('topShrinkFactor') or 0.0) * 100:.2f}% • adaptive score {float(champion.get('adaptiveScore') or 0.0) * 100:.2f}%."
        )
    if type_key == "KENO":
        notes.append("Keno có mật độ số cao nên lift thường chỉ nhích nhẹ quanh 1.00x; support lớn quan trọng hơn lift đẹp.")
    elif evidence:
        notes.append("Những số được giữ lại là số có bias thống kê cục bộ tốt hơn nền ở nhiều góc nhìn gần đây.")
    return notes


def build_luan_so_prediction(type_key, bundle_count, keno_level=None, sync_summary=None, include_meta=True):
    if is_three_digit_type(type_key):
        return build_luan_so_three_digit_prediction(type_key, bundle_count, sync_summary=sync_summary, include_meta=include_meta)
    sync_summary = sync_summary or sync_ai_history(type_key)
    cfg = AI_GAME_CONFIG[type_key]
    pick_size = keno_level if type_key == "KENO" else cfg["mainCount"]
    if not sync_summary_is_ready(sync_summary):
        return build_bootstrap_pending_payload(type_key, sync_summary, bundle_count, pick_size, AI_ENGINE_LUAN_SO)

    draws = limit_luan_so_draws(type_key, load_ai_draws(type_key))
    min_history = AI_KENO_MIN_HISTORY if type_key == "KENO" else AI_NUMERIC_MIN_HISTORY
    if len(draws) < min_history:
        raise RuntimeError(f"Chưa đủ dữ liệu để chạy Luận Số cho {lr.LIVE_TYPES[type_key].label}.")

    relation_results = {}
    for relation in get_luan_so_relation_configs(type_key):
        source_sets = [get_relation_value_set(draw, relation["source_kind"]) for draw in draws]
        target_sets = [get_relation_value_set(draw, relation["target_kind"]) for draw in draws]
        relation_results[relation["key"]] = build_luan_so_pair_rows(type_key, relation, source_sets, target_sets)

    top_numbers = build_luan_so_top_numbers(type_key, draws, relation_results, recent_draw_count=max(LUAN_SO_WINDOWS))
    main_ranking = list(top_numbers["mainRanking"])
    if not main_ranking:
        raise RuntimeError("Luận Số chưa tạo được ranking cho số chính.")
    special_ranking = list(top_numbers["specialRanking"]) if cfg["hasSpecial"] else []
    champion = choose_luan_so_champion(type_key, relation_results, top_numbers["evidence"])
    confidence = compute_luan_so_confidence(type_key, champion, top_numbers["evidence"])

    tickets = []
    for index, main in enumerate(build_prediction_bundles(main_ranking, pick_size, bundle_count)):
        ticket = {"main": main}
        if cfg["hasSpecial"]:
            ticket["special"] = special_ranking[index % len(special_ranking)] if special_ranking else cfg["specialMin"]
        else:
            ticket["special"] = None
        tickets.append(ticket)

    report = build_luan_so_report(type_key, draws, relation_results)
    latest_draw = draws[-1]
    notes = build_luan_so_notes(sync_summary, champion, top_numbers["evidence"], type_key)
    top_evidence = top_numbers["evidence"][:20]
    result = {
        "ok": True,
        "ready": True,
        "bootstrapComplete": True,
        "mode": "ai_predict",
        "engine": AI_ENGINE_LUAN_SO,
        "engineLabel": AI_ENGINE_LABELS[AI_ENGINE_LUAN_SO],
        "modelVersion": LUAN_SO_MODEL_VERSION,
        "type": type_key,
        "label": lr.LIVE_TYPES[type_key].label,
        "model": champion,
        "champion": champion,
        "lastTrainedAt": now_iso(),
        "trainingSamples": len(draws),
        "confidence": round(confidence, 6),
        "historyFile": sync_summary["historyFile"],
        "historyCount": sync_summary["historyCount"],
        "latestKy": latest_draw["ky"],
        "latestDate": latest_draw["date"],
        "latestTime": latest_draw["time"],
        "nextKy": next_prediction_ky(draws),
        "bundleCount": bundle_count,
        "pickSize": pick_size,
        "topRanking": main_ranking[:AI_TOP_RANKING_COUNT],
        "topSpecialRanking": special_ranking[:AI_SPECIAL_TOP_COUNT],
        "tickets": tickets,
        "predictedLn": lr.calc_keno_ln(main_ranking[:AI_TOP_RANKING_COUNT]) if type_key == "KENO" else None,
        "predictedCl": lr.calc_keno_cl(main_ranking[:AI_TOP_RANKING_COUNT]) if type_key == "KENO" else None,
        "backtest": {
            "avgHits": 0.0,
            "avgHitRate": round(confidence, 6),
            "samples": len(draws),
            "specialHitRate": None,
            "shrinkageAdjustedConfidence": round(float(champion.get("topConfidence") or 0.0), 6),
            "shrinkageAdjustedLift": round(float(champion.get("topLift") or 0.0), 6),
            "directionalAgreementRatio": round(min(1.0, (int(champion.get("strongPairs") or 0) + int(champion.get("watchPairs") or 0) * 0.4) / max(1.0, len(relation_results) * 8.0)), 6),
        },
        "sync": sync_summary,
        "notes": notes,
        "learnedWeights": [],
        "analysisReport": report,
        "signalSummary": {
            "dominantDirection": champion.get("direction", ""),
            "dominantWindow": int(champion.get("window") or 0),
            "strongPairCount": int(champion.get("strongPairs") or 0),
            "watchPairCount": int(champion.get("watchPairs") or 0),
            "filteredPairCount": sum(1 for item in (top_numbers.get("evidence") or []) if float(item.get("strength") or 0.0) > 0),
            "directionalAgreementRatio": round(min(1.0, (int(champion.get("strongPairs") or 0) + int(champion.get("watchPairs") or 0) * 0.4) / max(1.0, len(relation_results) * 8.0)), 6),
            "topShrinkFactor": round(float(champion.get("topShrinkFactor") or 0.0), 6),
            "topEvidence": top_evidence,
        },
    }
    if include_meta:
        meta_model, _ = ensure_online_meta_model(type_key, sync_summary)
        result = apply_online_meta_to_result(result, meta_model, AI_ENGINE_LUAN_SO)
    return result


# ----- Luu va doc model AI Gen Local -----
# Quan ly file model runtime tren disk, kiem tra do moi va tinh hop le cua model da hoc.
def ensure_gen_local_model_dir():
    GEN_LOCAL_MODEL_DIR.mkdir(parents=True, exist_ok=True)


def get_gen_local_model_path(type_key):
    return GEN_LOCAL_MODEL_DIR / f"{type_key}_gen_model.json"


def write_gen_local_model(type_key, payload):
    ensure_gen_local_model_dir()
    lr.write_text_atomic(
        get_gen_local_model_path(type_key),
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_gen_local_model(type_key):
    path = get_gen_local_model_path(type_key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("type", "")).strip().upper() != type_key:
        return None
    if str(payload.get("engine", "")).strip().lower() != AI_ENGINE_GEN_LOCAL:
        return None
    if str(payload.get("modelVersion", "")).strip() != GEN_LOCAL_MODEL_VERSION:
        return None
    return payload


def gen_local_model_is_fresh(model_payload, sync_summary):
    if not isinstance(model_payload, dict):
        return False
    return (
        str(model_payload.get("historyFile", "")).strip() == str(sync_summary.get("historyFile", "")).strip()
        and int(model_payload.get("historyCount") or 0) == int(sync_summary.get("historyCount") or 0)
        and str(model_payload.get("latestKy", "")).strip() == str(sync_summary.get("latestKy", "")).strip()
        and str(model_payload.get("latestDate", "")).strip() == str(sync_summary.get("latestDate", "")).strip()
        and str(model_payload.get("latestTime", "")).strip() == str(sync_summary.get("latestTime", "")).strip()
    )


def compute_recent_hit_rate(hits, target_size, recent_window):
    if not hits:
        return 0.0
    window = max(1, min(len(hits), int(recent_window or 1)))
    sample = hits[-window:]
    return sum(safe_rate(value, target_size) for value in sample) / len(sample)


def very_recent_window_for_type(type_key):
    return GEN_LOCAL_VERY_RECENT_KENO_WINDOW if type_key == "KENO" else GEN_LOCAL_VERY_RECENT_NUMERIC_WINDOW


def medium_recent_window_for_type(type_key):
    return GEN_LOCAL_MEDIUM_RECENT_KENO_WINDOW if type_key == "KENO" else GEN_LOCAL_MEDIUM_RECENT_NUMERIC_WINDOW


def compute_recent_hit_profile(type_key, hits, target_size):
    return {
        "veryRecentAvgHitRate": compute_recent_hit_rate(hits, target_size, very_recent_window_for_type(type_key)),
        "recentAvgHitRate": compute_recent_hit_rate(hits, target_size, recent_window_for_type(type_key)),
        "mediumRecentAvgHitRate": compute_recent_hit_rate(hits, target_size, medium_recent_window_for_type(type_key)),
    }


def compute_hit_stability(hits, target_size):
    if not hits:
        return 0.0
    rates = [safe_rate(value, target_size) for value in hits]
    average = sum(rates) / len(rates)
    variance = sum((rate - average) ** 2 for rate in rates) / len(rates)
    standard_deviation = variance ** 0.5
    return max(0.0, min(1.0, 1.0 - min(standard_deviation / 0.5, 1.0)))


def normalize_weighted_entries(entries):
    if not entries:
        return []
    total = sum(max(float(item.get("rawScore", 0.0)), 0.0001) for item in entries)
    for item in entries:
        item["learnedWeight"] = max(float(item.get("rawScore", 0.0)), 0.0001) / total
    return entries


def build_consensus_ranking(strategy_results, max_number):
    if max_number <= 0:
        return []
    min_candidate = 0 if max_number > 99 else 1
    scores = [0.0] * (max_number + 1)
    for result in strategy_results:
        ranking = list(result.get("ranking") or [])
        if not ranking:
            continue
        ranking_size = max(1, len(ranking))
        for index, number in enumerate(ranking):
            try:
                candidate = int(number)
            except (TypeError, ValueError):
                continue
            if candidate < 0 or candidate > max_number:
                continue
            scores[candidate] += (ranking_size - index) / ranking_size
    return sorted(range(min_candidate, max_number + 1), key=lambda candidate: (-scores[candidate], candidate))


def compute_ranking_agreement_score(ranking, consensus_ranking, top_span):
    ranked = list(ranking or [])[:max(1, int(top_span or 0))]
    consensus = list(consensus_ranking or [])[:max(1, int(top_span or 0))]
    if not ranked or not consensus:
        return 0.0
    consensus_positions = {number: index for index, number in enumerate(consensus)}
    span = max(1, len(ranked))
    weighted_hits = 0.0
    total_weight = 0.0
    for index, number in enumerate(ranked):
        weight = (span - index) / span
        total_weight += weight
        if number not in consensus_positions:
            continue
        consensus_weight = (span - min(consensus_positions[number], span - 1)) / span
        weighted_hits += weight * consensus_weight
    return max(0.0, min(1.0, weighted_hits / max(total_weight, 1e-9)))


def build_gen_local_strategy_entries(type_key, strategy_results, target_size):
    recent_window = recent_window_for_type(type_key)
    max_number = 0
    for result in strategy_results:
        ranking = list(result.get("ranking") or [])
        for number in ranking:
            try:
                candidate = int(number)
            except (TypeError, ValueError):
                continue
            if candidate > max_number:
                max_number = candidate
    consensus_ranking = build_consensus_ranking(strategy_results, max_number)
    top_span = max(8, int(target_size) * (3 if type_key == "KENO" else 2))
    entries = []
    for result in strategy_results:
        hits = list(result.get("hits") or [])
        recent_profile = compute_recent_hit_profile(type_key, hits, target_size)
        very_recent_avg_hit_rate = float(recent_profile["veryRecentAvgHitRate"])
        recent_avg_hit_rate = float(recent_profile["recentAvgHitRate"])
        medium_recent_avg_hit_rate = float(recent_profile["mediumRecentAvgHitRate"])
        avg_hit_rate = float(result.get("avgHitRate") or 0.0)
        stability = compute_hit_stability(hits, target_size)
        momentum = max(0.0, very_recent_avg_hit_rate - avg_hit_rate)
        recent_consistency = max(0.0, 1.0 - min(1.0, abs(very_recent_avg_hit_rate - medium_recent_avg_hit_rate) * (4.5 if type_key == "KENO" else 6.0)))
        agreement_score = compute_ranking_agreement_score(result.get("ranking") or [], consensus_ranking, top_span)
        sample_factor = min(1.0, int(result.get("samples") or 0) / max(18.0, float(recent_window or 1)))
        if type_key == "KENO":
            base_score = (
                very_recent_avg_hit_rate * 0.30 +
                recent_avg_hit_rate * 0.24 +
                medium_recent_avg_hit_rate * 0.18 +
                avg_hit_rate * 0.10 +
                stability * 0.10 +
                recent_consistency * 0.08
            )
        else:
            base_score = (
                very_recent_avg_hit_rate * 0.28 +
                recent_avg_hit_rate * 0.24 +
                medium_recent_avg_hit_rate * 0.20 +
                avg_hit_rate * 0.12 +
                stability * 0.10 +
                recent_consistency * 0.06
            )
        degradation = max(0.0, medium_recent_avg_hit_rate - very_recent_avg_hit_rate)
        cooldown_penalty = max(0.54, 1.0 - degradation * (1.24 if type_key == "KENO" else 1.52))
        short_spike_penalty = max(0.62 if type_key == "KENO" else 0.58, 1.0 - max(0.0, very_recent_avg_hit_rate - medium_recent_avg_hit_rate) * (0.50 if type_key == "KENO" else 0.64))
        adaptive_score = (
            base_score * 0.68 +
            agreement_score * 0.12 +
            sample_factor * 0.06 +
            momentum * 0.02 +
            recent_consistency * 0.12
        ) * cooldown_penalty * short_spike_penalty
        raw_score = adaptive_score
        if int(result.get("samples") or 0) < max(12, recent_window // 2):
            raw_score *= 0.74
        entries.append({
            "key": result["key"],
            "label": result["label"],
            "samples": int(result.get("samples") or 0),
            "avgHits": float(result.get("avgHits") or 0.0),
            "avgHitRate": avg_hit_rate,
            "veryRecentAvgHitRate": very_recent_avg_hit_rate,
            "recentAvgHitRate": recent_avg_hit_rate,
            "mediumRecentAvgHitRate": medium_recent_avg_hit_rate,
            "stability": stability,
            "recentConsistency": recent_consistency,
            "agreementScore": agreement_score,
            "sampleFactor": sample_factor,
            "cooldownPenalty": cooldown_penalty,
            "shortSpikePenalty": short_spike_penalty,
            "adaptiveScore": adaptive_score,
            "rawScore": raw_score,
            "ranking": list(result.get("ranking") or []),
        })
    normalize_weighted_entries(entries)
    entries.sort(
        key=lambda item: (
            item["rawScore"],
            item.get("agreementScore", 0.0),
            item["recentAvgHitRate"],
            item["avgHitRate"],
            item["samples"],
            item["label"],
        ),
        reverse=True,
    )
    return entries


def blend_strategy_rankings(strategy_entries, max_number):
    min_candidate = 0 if max_number > 99 else 1
    scores = [0.0] * (max_number + 1)
    for entry in strategy_entries:
        ranking = list(entry.get("ranking") or [])
        if not ranking:
            continue
        weight = float(entry.get("learnedWeight") or 0.0)
        ranking_size = max(1, len(ranking))
        for index, number in enumerate(ranking):
            try:
                candidate = int(number)
            except (TypeError, ValueError):
                continue
            if candidate < 0 or candidate > max_number:
                continue
            scores[candidate] += weight * ((ranking_size - index) / ranking_size)
    return sorted(range(min_candidate, max_number + 1), key=lambda candidate: (-scores[candidate], candidate))


def compute_gen_local_confidence(type_key, history_count, champion_entry):
    history_norm = min(1.0, float(history_count or 0) / (6000.0 if type_key == "KENO" else 800.0))
    champion_weight = float(champion_entry.get("learnedWeight") or 0.0)
    very_recent_rate = float(champion_entry.get("veryRecentAvgHitRate") or 0.0)
    recent_rate = float(champion_entry.get("recentAvgHitRate") or 0.0)
    medium_recent_rate = float(champion_entry.get("mediumRecentAvgHitRate") or 0.0)
    stability = float(champion_entry.get("stability") or 0.0)
    recent_consistency = float(champion_entry.get("recentConsistency") or 0.0)
    confidence = (
        champion_weight * 0.22 +
        very_recent_rate * 0.16 +
        recent_rate * 0.18 +
        medium_recent_rate * 0.14 +
        recent_consistency * 0.12 +
        stability * 0.12 +
        history_norm * 0.06
    )
    return max(0.0, min(1.0, confidence))


def serializable_strategy_entry(entry):
    return {
        "key": entry["key"],
        "label": entry["label"],
        "samples": int(entry.get("samples") or 0),
        "avgHits": round(float(entry.get("avgHits") or 0.0), 4),
        "avgHitRate": round(float(entry.get("avgHitRate") or 0.0), 6),
        "veryRecentAvgHitRate": round(float(entry.get("veryRecentAvgHitRate") or 0.0), 6),
        "recentAvgHitRate": round(float(entry.get("recentAvgHitRate") or 0.0), 6),
        "mediumRecentAvgHitRate": round(float(entry.get("mediumRecentAvgHitRate") or 0.0), 6),
        "stability": round(float(entry.get("stability") or 0.0), 6),
        "recentConsistency": round(float(entry.get("recentConsistency") or 0.0), 6),
        "agreementScore": round(float(entry.get("agreementScore") or 0.0), 6),
        "sampleFactor": round(float(entry.get("sampleFactor") or 0.0), 6),
        "cooldownPenalty": round(float(entry.get("cooldownPenalty") or 0.0), 6),
        "shortSpikePenalty": round(float(entry.get("shortSpikePenalty") or 0.0), 6),
        "adaptiveScore": round(float(entry.get("adaptiveScore") or 0.0), 6),
        "learnedWeight": round(float(entry.get("learnedWeight") or 0.0), 6),
        "rawScore": round(float(entry.get("rawScore") or 0.0), 6),
    }


def build_gen_local_profile(type_key, strategy_results, max_number, target_size, history_count):
    strategy_entries = build_gen_local_strategy_entries(type_key, strategy_results, target_size)
    champion_entry = dict(strategy_entries[0]) if strategy_entries else {
        "key": "",
        "label": "",
        "samples": 0,
        "avgHits": 0.0,
        "avgHitRate": 0.0,
        "veryRecentAvgHitRate": 0.0,
        "recentAvgHitRate": 0.0,
        "mediumRecentAvgHitRate": 0.0,
        "stability": 0.0,
        "recentConsistency": 0.0,
        "agreementScore": 0.0,
        "sampleFactor": 0.0,
        "cooldownPenalty": 1.0,
        "shortSpikePenalty": 1.0,
        "adaptiveScore": 0.0,
        "learnedWeight": 0.0,
        "rawScore": 0.0,
        "ranking": [],
    }
    ranking = blend_strategy_rankings(strategy_entries, max_number)
    confidence = compute_gen_local_confidence(type_key, history_count, champion_entry)
    return {
        "targetSize": int(target_size),
        "ranking": ranking,
        "champion": serializable_strategy_entry(champion_entry),
        "strategies": [serializable_strategy_entry(entry) for entry in strategy_entries],
        "trainingSamples": int(champion_entry.get("samples") or 0),
        "confidence": round(confidence, 6),
        "backtest": {
            "avgHits": round(float(champion_entry.get("avgHits") or 0.0), 4),
            "avgHitRate": round(float(champion_entry.get("avgHitRate") or 0.0), 6),
            "veryRecentAvgHitRate": round(float(champion_entry.get("veryRecentAvgHitRate") or 0.0), 6),
            "recentAvgHitRate": round(float(champion_entry.get("recentAvgHitRate") or 0.0), 6),
            "mediumRecentAvgHitRate": round(float(champion_entry.get("mediumRecentAvgHitRate") or 0.0), 6),
            "samples": int(champion_entry.get("samples") or 0),
            "stability": round(float(champion_entry.get("stability") or 0.0), 6),
            "recentConsistency": round(float(champion_entry.get("recentConsistency") or 0.0), 6),
            "agreementScore": round(float(champion_entry.get("agreementScore") or 0.0), 6),
            "cooldownPenalty": round(float(champion_entry.get("cooldownPenalty") or 0.0), 6),
            "shortSpikePenalty": round(float(champion_entry.get("shortSpikePenalty") or 0.0), 6),
            "adaptiveScore": round(float(champion_entry.get("adaptiveScore") or 0.0), 6),
        },
    }


# ----- Train AI Gen Local -----
# Tao champion model moi tu canonical all_day va ghi lai model da hoc cho tung loai.
def build_numeric_gen_local_model(type_key, sync_summary, draws):
    cfg = AI_GAME_CONFIG[type_key]
    final_weekday = next_target_weekday(type_key, draws[-1])
    main_results = evaluate_strategies(
        build_numeric_main_items(draws),
        cfg["mainCount"],
        cfg["mainMax"],
        MAIN_STRATEGIES,
        AI_NUMERIC_MIN_HISTORY,
        AI_NUMERIC_EVAL_SAMPLES,
        final_weekday,
    )
    main_profile = build_gen_local_profile(
        type_key,
        main_results,
        cfg["mainMax"],
        cfg["mainCount"],
        sync_summary["historyCount"],
    )
    special_profile = None
    if cfg["hasSpecial"]:
        special_items = build_numeric_special_items(draws)
        if special_items:
            special_results = evaluate_strategies(
                special_items,
                1,
                cfg["specialMax"],
                SPECIAL_STRATEGIES,
                AI_NUMERIC_MIN_HISTORY,
                AI_NUMERIC_EVAL_SAMPLES,
                final_weekday,
            )
            special_profile = build_gen_local_profile(
                type_key,
                special_results,
                cfg["specialMax"],
                1,
                sync_summary["historyCount"],
            )
    latest_draw = draws[-1]
    return {
        "engine": AI_ENGINE_GEN_LOCAL,
        "engineLabel": AI_ENGINE_LABELS[AI_ENGINE_GEN_LOCAL],
        "modelVersion": GEN_LOCAL_MODEL_VERSION,
        "type": type_key,
        "label": lr.LIVE_TYPES[type_key].label,
        "historyFile": sync_summary["historyFile"],
        "historyCount": sync_summary["historyCount"],
        "latestKy": latest_draw["ky"],
        "latestDate": latest_draw["date"],
        "latestTime": latest_draw["time"],
        "lastTrainedAt": now_iso(),
        "trainingSamples": main_profile["trainingSamples"],
        "currentChampion": main_profile["champion"],
        "learnedWeights": main_profile["strategies"],
        "recentBacktestSummary": main_profile["backtest"],
        "confidence": main_profile["confidence"],
        "mainProfile": main_profile,
        "specialProfile": special_profile,
    }


def build_keno_gen_local_model(sync_summary, draws):
    items = [{"numbers": draw["main"], "weekday": draw["weekday"]} for draw in draws]
    final_weekday = next_target_weekday("KENO", draws[-1])
    profiles = {}
    for order in range(1, 11):
        strategy_results = evaluate_strategies(
            items,
            order,
            80,
            MAIN_STRATEGIES,
            AI_KENO_MIN_HISTORY,
            AI_KENO_EVAL_SAMPLES,
            final_weekday,
        )
        profiles[str(order)] = build_gen_local_profile(
            "KENO",
            strategy_results,
            80,
            order,
            sync_summary["historyCount"],
        )
    default_profile = profiles.get("5") or next(iter(profiles.values()))
    latest_draw = draws[-1]
    return {
        "engine": AI_ENGINE_GEN_LOCAL,
        "engineLabel": AI_ENGINE_LABELS[AI_ENGINE_GEN_LOCAL],
        "modelVersion": GEN_LOCAL_MODEL_VERSION,
        "type": "KENO",
        "label": "Keno",
        "historyFile": sync_summary["historyFile"],
        "historyCount": sync_summary["historyCount"],
        "latestKy": latest_draw["ky"],
        "latestDate": latest_draw["date"],
        "latestTime": latest_draw["time"],
        "lastTrainedAt": now_iso(),
        "trainingSamples": default_profile["trainingSamples"],
        "currentChampion": default_profile["champion"],
        "learnedWeights": default_profile["strategies"],
        "recentBacktestSummary": default_profile["backtest"],
        "confidence": default_profile["confidence"],
        "defaultOrder": 5,
        "profiles": profiles,
    }


def build_three_digit_gen_local_model(type_key, sync_summary, draws):
    final_weekday = next_target_weekday(type_key, draws[-1])
    strategy_results = evaluate_three_digit_strategies(draws, THREE_DIGIT_STRATEGIES, final_weekday)
    main_profile = build_gen_local_profile(
        type_key,
        strategy_results,
        999,
        THREE_DIGIT_EVAL_TOP_SPAN,
        sync_summary["historyCount"],
    )
    latest_draw = draws[-1]
    return {
        "engine": AI_ENGINE_GEN_LOCAL,
        "engineLabel": AI_ENGINE_LABELS[AI_ENGINE_GEN_LOCAL],
        "modelVersion": GEN_LOCAL_MODEL_VERSION,
        "type": type_key,
        "label": lr.LIVE_TYPES[type_key].label,
        "historyFile": sync_summary["historyFile"],
        "historyCount": sync_summary["historyCount"],
        "latestKy": latest_draw["ky"],
        "latestDate": latest_draw["date"],
        "latestTime": latest_draw["time"],
        "lastTrainedAt": now_iso(),
        "trainingSamples": main_profile["trainingSamples"],
        "currentChampion": main_profile["champion"],
        "learnedWeights": main_profile["strategies"],
        "recentBacktestSummary": main_profile["backtest"],
        "confidence": main_profile["confidence"],
        "mainProfile": main_profile,
        "specialProfile": None,
    }


def train_gen_local_model(type_key, sync_summary=None):
    sync_summary = sync_summary or sync_ai_history(type_key)
    if not sync_summary_is_ready(sync_summary):
        raise RuntimeError("Dữ liệu canonical all_day chưa sẵn sàng để train AI Gen Local.")
    draws = load_ai_draws(type_key)
    if type_key == "KENO":
        if len(draws) < AI_KENO_MIN_HISTORY:
            raise RuntimeError("Chưa đủ dữ liệu để train AI Gen Local cho Keno.")
        model_payload = build_keno_gen_local_model(sync_summary, draws)
    elif is_three_digit_type(type_key):
        if len(draws) < AI_NUMERIC_MIN_HISTORY:
            raise RuntimeError(f"Chưa đủ dữ liệu để train AI Gen Local cho {lr.LIVE_TYPES[type_key].label}.")
        model_payload = build_three_digit_gen_local_model(type_key, sync_summary, draws)
    else:
        if len(draws) < AI_NUMERIC_MIN_HISTORY:
            raise RuntimeError(f"Chưa đủ dữ liệu để train AI Gen Local cho {lr.LIVE_TYPES[type_key].label}.")
        model_payload = build_numeric_gen_local_model(type_key, sync_summary, draws)
    write_gen_local_model(type_key, model_payload)
    return model_payload


def ensure_gen_local_model(type_key, sync_summary=None):
    sync_summary = sync_summary or sync_ai_history(type_key)
    cached = read_gen_local_model(type_key)
    if cached and gen_local_model_is_fresh(cached, sync_summary):
        return cached, False
    return train_gen_local_model(type_key, sync_summary), True


# ----- Meta model online giu nhip -----
# Meta-learner hoc tu ky da resolve, cap nhat trong so expert va kiem soat do rung cua he.
def meta_config_for_type(type_key):
    return ONLINE_META_GAME_CONFIG.get(type_key, ONLINE_META_GAME_CONFIG["LOTO_6_45"])


def get_online_meta_model_path(type_key):
    return GEN_LOCAL_MODEL_DIR / f"{type_key}_meta_model.json"


def read_online_meta_model(type_key):
    path = get_online_meta_model_path(type_key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("type", "")).strip().upper() != type_key:
        return None
    if str(payload.get("modelVersion", "")).strip() != ONLINE_META_MODEL_VERSION:
        return None
    return payload


def write_online_meta_model(type_key, payload):
    ensure_gen_local_model_dir()
    lr.write_text_atomic(
        get_online_meta_model_path(type_key),
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def online_meta_model_is_fresh(model_payload, sync_summary):
    if not isinstance(model_payload, dict):
        return False
    return (
        str(model_payload.get("historyFile", "")).strip() == str(sync_summary.get("historyFile", "")).strip()
        and int(model_payload.get("historyCount") or 0) == int(sync_summary.get("historyCount") or 0)
        and str(model_payload.get("latestKy", "")).strip() == str(sync_summary.get("latestKy", "")).strip()
        and str(model_payload.get("latestDate", "")).strip() == str(sync_summary.get("latestDate", "")).strip()
        and str(model_payload.get("latestTime", "")).strip() == str(sync_summary.get("latestTime", "")).strip()
    )


def normalize_weight_map(raw_weights, min_weight=ONLINE_META_MIN_WEIGHT):
    weights = {}
    for key in META_EXPERT_KEYS:
        try:
            weights[key] = max(float((raw_weights or {}).get(key) or 0.0), 0.0)
        except (TypeError, ValueError):
            weights[key] = 0.0
    total = sum(weights.values())
    if total <= 0:
        even = 1.0 / len(META_EXPERT_KEYS)
        return {key: even for key in META_EXPERT_KEYS}
    weights = {key: value / total for key, value in weights.items()}
    floor = max(0.0, min(0.3, float(min_weight or 0.0)))
    if floor <= 0:
        total = sum(weights.values()) or 1.0
        return {key: value / total for key, value in weights.items()}
    bumped = {key: max(floor, value) for key, value in weights.items()}
    total = sum(bumped.values()) or 1.0
    return {key: value / total for key, value in bumped.items()}


def apply_weight_shift_limit(previous_weights, target_weights, min_weight, max_shift):
    previous = normalize_weight_map(previous_weights, min_weight)
    limited = {}
    for key in META_EXPERT_KEYS:
        current = previous.get(key, 0.0)
        target = float((target_weights or {}).get(key) or 0.0)
        delta = target - current
        if delta > max_shift:
            target = current + max_shift
        elif delta < -max_shift:
            target = current - max_shift
        limited[key] = max(0.0, target)
    return normalize_weight_map(limited, min_weight)


def compute_weight_shift(previous_weights, next_weights):
    total = 0.0
    for key in META_EXPERT_KEYS:
        total += abs(float((next_weights or {}).get(key) or 0.0) - float((previous_weights or {}).get(key) or 0.0))
    return total / 2.0


def compute_top_ranking_overlap(ranking_a, ranking_b, top_span):
    top_span = max(1, int(top_span or 1))
    first = list(ranking_a or [])[:top_span]
    second = list(ranking_b or [])[:top_span]
    if not first or not second:
        return 0.0
    second_positions = {int(number): index for index, number in enumerate(second)}
    weighted_hits = 0.0
    total_weight = 0.0
    for index, number in enumerate(first):
        try:
            candidate = int(number)
        except (TypeError, ValueError):
            continue
        weight = (top_span - index) / top_span
        total_weight += weight
        if candidate not in second_positions:
            continue
        pair_weight = (top_span - min(second_positions[candidate], top_span - 1)) / top_span
        weighted_hits += weight * pair_weight
    return clamp01(weighted_hits / max(total_weight, 1e-9))


def build_gen_local_meta_snapshot(type_key, sync_summary):
    if type_key == "KENO":
        model_payload, _ = ensure_gen_local_model("KENO", sync_summary)
        default_order = int(model_payload.get("defaultOrder") or 5)
        profile = dict((model_payload.get("profiles") or {}).get(str(default_order)) or {})
    else:
        model_payload, _ = ensure_gen_local_model(type_key, sync_summary)
        profile = dict(model_payload.get("mainProfile") or {})
    champion = dict(profile.get("champion") or model_payload.get("currentChampion") or {})
    ranking = list(profile.get("ranking") or [])
    return {
        "engine": AI_ENGINE_GEN_LOCAL,
        "latestKy": str(model_payload.get("latestKy", "")).strip(),
        "confidence": float(profile.get("confidence") or model_payload.get("confidence") or 0.0),
        "ranking": ranking[:AI_TOP_RANKING_COUNT],
        "backtest": dict(profile.get("backtest") or model_payload.get("recentBacktestSummary") or {}),
        "champion": champion,
    }


def build_luan_so_meta_snapshot(type_key, sync_summary):
    if type_key == "KENO":
        result = build_luan_so_prediction("KENO", 1, 5, sync_summary=sync_summary, include_meta=False)
    else:
        result = build_luan_so_prediction(type_key, 1, sync_summary=sync_summary, include_meta=False)
    return {
        "engine": AI_ENGINE_LUAN_SO,
        "latestKy": str(result.get("latestKy", "")).strip(),
        "confidence": float(result.get("confidence") or 0.0),
        "ranking": list(result.get("topRanking") or [])[:AI_TOP_RANKING_COUNT],
        "backtest": dict(result.get("backtest") or {}),
        "champion": dict(result.get("champion") or result.get("model") or {}),
        "signalSummary": dict(result.get("signalSummary") or {}),
    }


def compute_gen_local_meta_reward(snapshot):
    backtest = dict(snapshot.get("backtest") or {})
    champion = dict(snapshot.get("champion") or {})
    reward = (
        float(backtest.get("veryRecentAvgHitRate") or 0.0) * 0.28 +
        float(backtest.get("recentAvgHitRate") or 0.0) * 0.22 +
        float(backtest.get("mediumRecentAvgHitRate") or 0.0) * 0.12 +
        float(backtest.get("avgHitRate") or 0.0) * 0.10 +
        float(backtest.get("stability") or 0.0) * 0.10 +
        float(backtest.get("recentConsistency") or 0.0) * 0.10 +
        float(backtest.get("agreementScore") or 0.0) * 0.05 +
        float(snapshot.get("confidence") or 0.0) * 0.03
    )
    reward *= max(0.72, float(backtest.get("cooldownPenalty") or champion.get("cooldownPenalty") or 1.0))
    reward *= max(0.78, float(backtest.get("shortSpikePenalty") or champion.get("shortSpikePenalty") or 1.0))
    return clamp01(reward)


def compute_luan_so_meta_reward(type_key, snapshot):
    champion = dict(snapshot.get("champion") or {})
    signal_summary = dict(snapshot.get("signalSummary") or {})
    backtest = dict(snapshot.get("backtest") or {})
    if is_three_digit_type(type_key):
        support_anchor = 16.0
        pair_anchor = 6.0
        coverage_anchor = 12.0
    else:
        support_anchor = 260.0 if type_key == "KENO" else 90.0
        pair_anchor = 78.0 if type_key == "KENO" else 24.0
        coverage_anchor = 22.0 if type_key == "KENO" else 14.0
    support_norm = min(1.0, float(champion.get("topSupport") or 0.0) / support_anchor)
    pair_norm = min(1.0, float(champion.get("topPairCount") or 0.0) / pair_anchor)
    coverage_norm = min(1.0, (float(champion.get("strongPairs") or 0.0) + float(champion.get("watchPairs") or 0.0) * 0.42) / coverage_anchor)
    reward = (
        float(snapshot.get("confidence") or 0.0) * 0.30 +
        float(champion.get("adaptiveScore") or 0.0) * 0.24 +
        support_norm * 0.14 +
        pair_norm * 0.12 +
        float(backtest.get("directionalAgreementRatio") or signal_summary.get("directionalAgreementRatio") or 0.0) * 0.10 +
        float(champion.get("topShrinkFactor") or signal_summary.get("topShrinkFactor") or 0.0) * 0.06 +
        coverage_norm * 0.04
    )
    relation_penalty = 0.90 if champion.get("relationKind") in {"main_db", "db_main", "db_db"} else 1.0
    return clamp01(reward * relation_penalty)


def compute_online_meta_signals(type_key, gen_snapshot, luan_snapshot):
    gen_reward = compute_gen_local_meta_reward(gen_snapshot)
    luan_reward = compute_luan_so_meta_reward(type_key, luan_snapshot)
    overlap_span = 12 if type_key == "KENO" else 10
    overlap = compute_top_ranking_overlap(gen_snapshot.get("ranking") or [], luan_snapshot.get("ranking") or [], overlap_span)
    both_reward = clamp01((gen_reward * 0.46 + luan_reward * 0.46 + overlap * 0.08) * (0.96 + overlap * 0.08))
    gen_backtest = dict(gen_snapshot.get("backtest") or {})
    drift_recent = abs(float(gen_backtest.get("recentAvgHitRate") or 0.0) - float(gen_backtest.get("mediumRecentAvgHitRate") or 0.0))
    drift_spike = max(0.0, float(gen_backtest.get("veryRecentAvgHitRate") or 0.0) - float(gen_backtest.get("mediumRecentAvgHitRate") or 0.0))
    cross_gap = abs(gen_reward - luan_reward)
    luan_gap = abs(float(luan_snapshot.get("confidence") or 0.0) - float((luan_snapshot.get("champion") or {}).get("adaptiveScore") or 0.0))
    drift_score = clamp01(drift_recent * 4.4 + drift_spike * 3.1 + cross_gap * 1.45 + luan_gap * 0.90)
    cfg = meta_config_for_type(type_key)
    if drift_score >= float(cfg["volatileDrift"]):
        meta_state = META_STATE_VOLATILE
    elif drift_score >= float(cfg["warmDrift"]):
        meta_state = META_STATE_WARMING
    else:
        meta_state = META_STATE_STABLE
    stability_score = clamp01(1.0 - drift_score * 0.92)
    return {
        "rewards": {
            META_EXPERT_GEN: round(gen_reward, 6),
            META_EXPERT_LUAN_SO: round(luan_reward, 6),
            META_EXPERT_BOTH: round(both_reward, 6),
        },
        "rankingOverlap": round(overlap, 6),
        "driftScore": round(drift_score, 6),
        "metaState": meta_state,
        "stabilityScore": round(stability_score, 6),
    }


def compute_target_meta_weights(type_key, previous_weights, rewards, meta_state):
    cfg = meta_config_for_type(type_key)
    previous = normalize_weight_map(previous_weights, cfg["minWeight"])
    learning_rate = float(cfg["learningRate"]) * (0.58 if meta_state == META_STATE_VOLATILE else 0.82 if meta_state == META_STATE_WARMING else 1.0)
    raw = {}
    for key in META_EXPERT_KEYS:
        previous_weight = max(previous.get(key, 0.0), float(cfg["minWeight"]))
        reward = float((rewards or {}).get(key) or 0.0)
        raw[key] = (previous_weight ** float(cfg["weightDecay"])) * math.exp(learning_rate * reward)
    target = normalize_weight_map(raw, cfg["minWeight"])
    shifted = apply_weight_shift_limit(previous, target, cfg["minWeight"], float(cfg["maxShift"]))
    return shifted, compute_weight_shift(previous, shifted)


def build_online_meta_model(type_key, sync_summary):
    previous = read_online_meta_model(type_key)
    previous_weights = dict(previous.get("weights") or {}) if previous else {}
    gen_snapshot = build_gen_local_meta_snapshot(type_key, sync_summary)
    luan_snapshot = build_luan_so_meta_snapshot(type_key, sync_summary)
    signals = compute_online_meta_signals(type_key, gen_snapshot, luan_snapshot)
    weights, weight_shift = compute_target_meta_weights(type_key, previous_weights, signals["rewards"], signals["metaState"])
    preferred_engine = max(weights, key=weights.get)
    reward_history = list(previous.get("rewardHistory") or []) if previous else []
    reward_history.append({
        "ky": str(sync_summary.get("latestKy", "")).strip(),
        "learnedAt": now_iso(),
        "metaState": signals["metaState"],
        "rewards": signals["rewards"],
        "weights": {key: round(float(value), 6) for key, value in weights.items()},
        "weightShift": round(weight_shift, 6),
    })
    reward_history = reward_history[-ONLINE_META_HISTORY_LIMIT:]
    return {
        "type": type_key,
        "modelVersion": ONLINE_META_MODEL_VERSION,
        "historyFile": sync_summary["historyFile"],
        "historyCount": sync_summary["historyCount"],
        "latestKy": str(sync_summary.get("latestKy", "")).strip(),
        "latestDate": str(sync_summary.get("latestDate", "")).strip(),
        "latestTime": str(sync_summary.get("latestTime", "")).strip(),
        "lastLearnedKy": str(sync_summary.get("latestKy", "")).strip(),
        "lastLearnedAt": now_iso(),
        "metaState": signals["metaState"],
        "stabilityScore": signals["stabilityScore"],
        "driftScore": signals["driftScore"],
        "rankingOverlap": signals["rankingOverlap"],
        "preferredEngine": preferred_engine,
        "weights": {key: round(float(value), 6) for key, value in weights.items()},
        "weightShift": round(weight_shift, 6),
        "rewards": signals["rewards"],
        "rewardHistory": reward_history,
        "snapshots": {
            META_EXPERT_GEN: {
                "confidence": round(float(gen_snapshot.get("confidence") or 0.0), 6),
                "backtest": dict(gen_snapshot.get("backtest") or {}),
                "champion": dict(gen_snapshot.get("champion") or {}),
            },
            META_EXPERT_LUAN_SO: {
                "confidence": round(float(luan_snapshot.get("confidence") or 0.0), 6),
                "backtest": dict(luan_snapshot.get("backtest") or {}),
                "champion": dict(luan_snapshot.get("champion") or {}),
                "signalSummary": dict(luan_snapshot.get("signalSummary") or {}),
            },
        },
    }


def ensure_online_meta_model(type_key, sync_summary=None):
    sync_summary = sync_summary or sync_ai_history(type_key)
    cached = read_online_meta_model(type_key)
    if cached and online_meta_model_is_fresh(cached, sync_summary):
        return cached, False
    payload = build_online_meta_model(type_key, sync_summary)
    write_online_meta_model(type_key, payload)
    return payload, True


def meta_expert_key_for_engine(engine):
    if engine == AI_ENGINE_GEN_LOCAL:
        return META_EXPERT_GEN
    if engine == AI_ENGINE_LUAN_SO:
        return META_EXPERT_LUAN_SO
    return META_EXPERT_BOTH


def build_online_meta_note_lines(meta_model, expert_key):
    weights = dict(meta_model.get("weights") or {})
    preferred = str(meta_model.get("preferredEngine") or "").strip()
    labels = {
        META_EXPERT_GEN: AI_ENGINE_LABELS[AI_ENGINE_GEN_LOCAL],
        META_EXPERT_LUAN_SO: AI_ENGINE_LABELS[AI_ENGINE_LUAN_SO],
        META_EXPERT_BOTH: "Blend ổn định AI Gen + Luận Số",
    }
    notes = [
        f"Meta online {str(meta_model.get('metaState') or META_STATE_WARMING)} • stability {float(meta_model.get('stabilityScore') or 0.0) * 100:.2f}% • drift {float(meta_model.get('driftScore') or 0.0) * 100:.2f}%.",
        f"Meta trust của engine hiện tại: {float(weights.get(expert_key) or 0.0) * 100:.2f}% • shift kỳ này {float(meta_model.get('weightShift') or 0.0) * 100:.2f}%.",
        (
            "Trọng số expert: "
            f"AI Gen {float(weights.get(META_EXPERT_GEN) or 0.0) * 100:.2f}% • "
            f"Luận Số {float(weights.get(META_EXPERT_LUAN_SO) or 0.0) * 100:.2f}% • "
            f"both_combo {float(weights.get(META_EXPERT_BOTH) or 0.0) * 100:.2f}%."
        ),
    ]
    if preferred:
        notes.append(f"Meta hiện đang ưu tiên: {labels.get(preferred, preferred)}.")
    return notes


def apply_online_meta_to_result(result, meta_model, engine):
    expert_key = meta_expert_key_for_engine(engine)
    weights = dict(meta_model.get("weights") or {})
    stability_score = clamp01(meta_model.get("stabilityScore") or 0.0)
    meta_trust = clamp01(weights.get(expert_key) or 0.0)
    meta_state = str(meta_model.get("metaState") or META_STATE_WARMING).strip()
    volatility_factor = 0.92 if meta_state == META_STATE_VOLATILE else 0.97 if meta_state == META_STATE_WARMING else 1.0
    base_confidence = float(result.get("confidence") or (result.get("backtest") or {}).get("avgHitRate") or 0.0)
    adjusted_confidence = clamp01((base_confidence * 0.82 + meta_trust * 0.12 + stability_score * 0.06) * volatility_factor)

    result["baseConfidence"] = round(base_confidence, 6)
    result["confidence"] = round(adjusted_confidence, 6)
    result["metaModelVersion"] = ONLINE_META_MODEL_VERSION
    result["metaState"] = meta_state
    result["stabilityScore"] = round(stability_score, 6)
    result["metaTrust"] = round(meta_trust, 6)
    result["weightShift"] = round(float(meta_model.get("weightShift") or 0.0), 6)
    result["lastLearnedKy"] = str(meta_model.get("lastLearnedKy", "")).strip()
    result["lastLearnedAt"] = str(meta_model.get("lastLearnedAt", "")).strip()
    result["metaPreferredEngine"] = str(meta_model.get("preferredEngine", "")).strip()
    result["metaWeights"] = {key: round(float(value), 6) for key, value in weights.items()}
    result["metaRewards"] = {key: round(float(value), 6) for key, value in dict(meta_model.get("rewards") or {}).items()}
    result["metaRankingOverlap"] = round(float(meta_model.get("rankingOverlap") or 0.0), 6)
    if isinstance(result.get("backtest"), dict):
        result["backtest"]["metaState"] = meta_state
        result["backtest"]["metaTrust"] = round(meta_trust, 6)
        result["backtest"]["stabilityScore"] = round(stability_score, 6)
        result["backtest"]["weightShift"] = round(float(meta_model.get("weightShift") or 0.0), 6)
    champion = result.get("champion")
    if isinstance(champion, dict):
        champion["metaTrust"] = round(meta_trust, 6)
        champion["metaState"] = meta_state
        champion["stabilityScore"] = round(stability_score, 6)
        if "adaptiveScore" in champion:
            champion["metaAdjustedAdaptiveScore"] = round(clamp01(float(champion.get("adaptiveScore") or 0.0) * volatility_factor * (0.94 + meta_trust * 0.12)), 6)
    model = result.get("model")
    if isinstance(model, dict):
        model["metaTrust"] = round(meta_trust, 6)
        model["metaState"] = meta_state
        model["stabilityScore"] = round(stability_score, 6)
    notes = list(result.get("notes") or [])
    insert_at = 1 if notes else 0
    for offset, line in enumerate(build_online_meta_note_lines(meta_model, expert_key)):
        notes.insert(insert_at + offset, line)
    result["notes"] = notes
    return result


def build_online_meta_summary(meta_model):
    return {
        "modelVersion": str(meta_model.get("modelVersion", "")).strip(),
        "metaState": str(meta_model.get("metaState", "")).strip(),
        "stabilityScore": round(float(meta_model.get("stabilityScore") or 0.0), 6),
        "weightShift": round(float(meta_model.get("weightShift") or 0.0), 6),
        "preferredEngine": str(meta_model.get("preferredEngine", "")).strip(),
        "lastLearnedKy": str(meta_model.get("lastLearnedKy", "")).strip(),
        "lastLearnedAt": str(meta_model.get("lastLearnedAt", "")).strip(),
        "weights": {key: round(float(value), 6) for key, value in dict(meta_model.get("weights") or {}).items()},
        "rewards": {key: round(float(value), 6) for key, value in dict(meta_model.get("rewards") or {}).items()},
    }


def build_gen_local_training_summary(type_key, model_payload):
    return {
        "ok": True,
        "engine": AI_ENGINE_GEN_LOCAL,
        "engineLabel": AI_ENGINE_LABELS[AI_ENGINE_GEN_LOCAL],
        "type": type_key,
        "label": lr.LIVE_TYPES[type_key].label,
        "modelVersion": str(model_payload.get("modelVersion", "")).strip(),
        "historyFile": str(model_payload.get("historyFile", "")).strip(),
        "historyCount": int(model_payload.get("historyCount") or 0),
        "latestKy": str(model_payload.get("latestKy", "")).strip(),
        "latestDate": str(model_payload.get("latestDate", "")).strip(),
        "latestTime": str(model_payload.get("latestTime", "")).strip(),
        "lastTrainedAt": str(model_payload.get("lastTrainedAt", "")).strip(),
        "trainingSamples": int(model_payload.get("trainingSamples") or 0),
        "currentChampion": dict(model_payload.get("currentChampion") or {}),
        "confidence": float(model_payload.get("confidence") or 0.0),
        "profileCount": len(model_payload.get("profiles") or {}) if type_key == "KENO" else 1,
    }


def train_gen_local_json(type_key):
    model_payload = train_gen_local_model(type_key)
    summary = build_gen_local_training_summary(type_key, model_payload)
    meta_model, _ = ensure_online_meta_model(type_key, model_payload)
    summary["meta"] = build_online_meta_summary(meta_model)
    return summary


def train_all_gen_local_json():
    results = []
    errors = []
    for type_key in AI_SUPPORTED_TYPES:
        try:
            results.append(train_gen_local_json(type_key))
        except Exception as exc:
            errors.append({"type": type_key, "message": str(exc)})
    return {
        "ok": not errors,
        "engine": AI_ENGINE_GEN_LOCAL,
        "engineLabel": AI_ENGINE_LABELS[AI_ENGINE_GEN_LOCAL],
        "results": results,
        "errors": errors,
        "trainedAt": now_iso(),
    }


# ----- Tao bo so va ghi chu chung -----
# Dong goi ranking thanh tung bo du doan va sinh note hien thi cho UI/backend.
def build_prediction_bundles(ranking, pick_size, bundle_count):
    if pick_size <= 0 or bundle_count <= 0:
        return []
    bundles = [[] for _ in range(bundle_count)]
    pool = list(ranking or [])
    if not pool:
        return bundles
    cursor = 0
    direction = 1
    while any(len(bundle) < pick_size for bundle in bundles):
        indexes = range(bundle_count) if direction > 0 else range(bundle_count - 1, -1, -1)
        for bundle_index in indexes:
            if len(bundles[bundle_index]) >= pick_size:
                continue
            candidate = pool[cursor % len(pool)]
            cursor += 1
            while candidate in bundles[bundle_index]:
                candidate = pool[cursor % len(pool)]
                cursor += 1
            bundles[bundle_index].append(candidate)
            if not any(len(bundle) < pick_size for bundle in bundles):
                break
        direction *= -1
    return [sorted(bundle) for bundle in bundles]


def summarize_sync_notes(sync_summary):
    notes = []
    errors = list(sync_summary.get("errors", []))
    if errors:
        retry_dates = []
        for error in errors:
            date_text = str(error.get("date", "")).strip()
            if date_text:
                retry_dates.append(date_text)
        retry_dates = sorted(set(retry_dates))
        if retry_dates:
            preview = ", ".join(retry_dates[:3])
            if len(retry_dates) > 3:
                preview += ", ..."
            notes.append(
                f"Còn {len(errors)} mốc web cần thử lại ({preview}); predictor vẫn dùng dữ liệu local đã có."
            )
        else:
            notes.append(
                f"Còn {len(errors)} lần thử web chưa hoàn tất; predictor vẫn dùng dữ liệu local đã có."
            )
    if sync_summary.get("newRows", 0) > 0:
        notes.append(f"Đã bổ sung {sync_summary['newRows']} dòng mới vào {sync_summary['historyFile']}.")
    if sync_summary.get("repairedDates", 0) > 0:
        notes.append(f"Đã sửa {sync_summary['repairedDates']} ngày/khoảng dữ liệu còn thiếu.")
    if sync_summary.get("repairedKyGaps", 0) > 0:
        notes.append(f"Đã vá {sync_summary['repairedKyGaps']} khoảng trống kỳ.")
    if sync_summary_is_ready(sync_summary) and sync_summary.get("sourceLimited"):
        notes.append("Đã tới mốc sớm nhất MinhChinh hiện trả được; predictor dùng canonical all_day theo chế độ source-limited complete.")
    if not sync_summary_is_ready(sync_summary):
        notes.append("Dữ liệu canonical all_day chưa full-history; predictor vẫn chờ bootstrap hoàn tất.")
    return notes


def build_bootstrap_pending_payload(type_key, sync_summary, bundle_count, pick_size, engine=AI_ENGINE_CLASSIC):
    label = lr.LIVE_TYPES[type_key].label
    note_lines = summarize_sync_notes(sync_summary)
    note_lines.insert(0, "Dữ liệu canonical all_day chưa full-history, predictor đang tạm khóa cho tới khi bootstrap hoàn tất.")
    return {
        "ok": True,
        "ready": False,
        "bootstrapComplete": False,
        "mode": "ai_predict",
        "engine": engine,
        "engineLabel": AI_ENGINE_LABELS.get(engine, AI_ENGINE_LABELS[AI_ENGINE_CLASSIC]),
        "type": type_key,
        "label": label,
        "model": None,
        "specialModel": None,
        "historyFile": sync_summary["historyFile"],
        "historyCount": sync_summary["historyCount"],
        "latestKy": sync_summary.get("latestKy", ""),
        "latestDate": sync_summary.get("latestDate", ""),
        "latestTime": sync_summary.get("latestTime", ""),
        "nextKy": "",
        "bundleCount": bundle_count,
        "pickSize": pick_size,
        "topRanking": [],
        "topSpecialRanking": [],
        "tickets": [],
        "backtest": {
            "avgHits": 0,
            "avgHitRate": 0,
            "samples": 0,
            "specialHitRate": None,
        },
        "sync": sync_summary,
        "notes": note_lines,
    }


# ----- Predictor classic va Gen Local -----
# Tra ket qua du doan cho 2 engine, gom numeric va Keno, nhung van dung chung nguon canonical.
def summarize_gen_local_notes(sync_summary, model_payload, trained_now=False):
    notes = summarize_sync_notes(sync_summary)
    if trained_now:
        notes.insert(0, "AI Gen Local vừa tự huấn luyện lại từ canonical all_day mới nhất.")
    notes.insert(1 if trained_now else 0, "AI Gen Local v4 stable đang tự điều chỉnh trọng số theo phong độ rất gần, phong độ gần, độ ổn định dài hơn và có thêm lớp giữ nhịp chống rung.")
    champion = dict(model_payload.get("currentChampion") or {})
    if champion.get("label"):
        notes.append(
            f"Champion hiện tại: {champion['label']} • trọng số học được {float(champion.get('learnedWeight') or 0.0) * 100:.2f}%."
        )
        notes.append(
            f"Đồng thuận strategy {float(champion.get('agreementScore') or 0.0) * 100:.2f}% • hệ số hạ nhiệt {float(champion.get('cooldownPenalty') or 0.0) * 100:.2f}% • chống bùng ngắn {float(champion.get('shortSpikePenalty') or 0.0) * 100:.2f}%."
        )
        notes.append(
            f"Recent profile: rất gần {float(champion.get('veryRecentAvgHitRate') or 0.0) * 100:.2f}% • gần {float(champion.get('recentAvgHitRate') or 0.0) * 100:.2f}% • trung hạn {float(champion.get('mediumRecentAvgHitRate') or 0.0) * 100:.2f}%."
        )
    confidence = float(model_payload.get("confidence") or 0.0)
    notes.append(f"Độ ổn định mô hình: {confidence * 100:.2f}% theo dữ liệu train hiện có.")
    return notes


def three_digit_game_label(type_key):
    normalized = str(type_key or "").strip().upper()
    return str(lr.LIVE_TYPES.get(normalized).label if normalized in lr.LIVE_TYPES else "3D").strip() or "3D"


def summarize_three_digit_notes(sync_summary, headline, type_key=""):
    notes = summarize_sync_notes(sync_summary)
    game_label = three_digit_game_label(type_key or sync_summary.get("type", ""))
    notes.insert(0, headline)
    notes.append(f"{game_label} đang được chấm theo không gian 000-999, ưu tiên nhịp recent, gap hồi, weekday và nhịp chữ số theo vị trí.")
    return notes


def build_three_digit_prediction(type_key, bundle_count):
    sync_summary = sync_ai_history(type_key)
    cfg = AI_GAME_CONFIG[type_key]
    game_label = three_digit_game_label(type_key)
    if not sync_summary_is_ready(sync_summary):
        return build_bootstrap_pending_payload(type_key, sync_summary, bundle_count, cfg["mainCount"])
    draws = load_ai_draws(type_key)
    if len(draws) < AI_NUMERIC_MIN_HISTORY:
        raise RuntimeError(f"Chưa đủ dữ liệu để dự đoán {lr.LIVE_TYPES[type_key].label}.")

    final_weekday = next_target_weekday(type_key, draws[-1])
    results = evaluate_three_digit_strategies(draws, THREE_DIGIT_STRATEGIES, final_weekday)
    best = dict(results[0] or {})
    ranking = list(best.get("ranking") or [])
    tickets = [{"main": bundle, "special": None} for bundle in build_prediction_bundles(ranking, cfg["mainCount"], bundle_count)]
    latest_draw = draws[-1]
    return {
        "ok": True,
        "ready": True,
        "bootstrapComplete": True,
        "mode": "ai_predict",
        "engine": AI_ENGINE_CLASSIC,
        "engineLabel": AI_ENGINE_LABELS[AI_ENGINE_CLASSIC],
        "type": type_key,
        "label": lr.LIVE_TYPES[type_key].label,
        "model": {
            "key": str(best.get("key") or ""),
            "label": f"AI Lite {game_label}",
            "samples": int(best.get("samples") or 0),
            "avgHits": round(float(best.get("avgHits") or 0.0), 4),
            "avgHitRate": round(float(best.get("avgHitRate") or 0.0), 6),
        },
        "historyFile": sync_summary["historyFile"],
        "historyCount": sync_summary["historyCount"],
        "latestKy": latest_draw["ky"],
        "latestDate": latest_draw["date"],
        "latestTime": latest_draw["time"],
        "nextKy": next_prediction_ky(draws),
        "bundleCount": bundle_count,
        "pickSize": cfg["mainCount"],
        "topRanking": ranking[:AI_TOP_RANKING_COUNT],
        "topSpecialRanking": [],
        "tickets": tickets,
        "backtest": {
            "avgHits": round(float(best.get("avgHits") or 0.0), 4),
            "avgHitRate": round(float(best.get("avgHitRate") or 0.0), 6),
            "samples": int(best.get("samples") or 0),
            "specialHitRate": None,
        },
        "sync": sync_summary,
        "notes": summarize_three_digit_notes(sync_summary, f"AI Lite {game_label} đang dùng blend tần suất recent + weekday + gap hồi cho không gian số 000-999.", type_key),
    }


def build_three_digit_gen_local_prediction(type_key, bundle_count, sync_summary=None, include_meta=True):
    sync_summary = sync_summary or sync_ai_history(type_key)
    game_label = three_digit_game_label(type_key)
    cfg = AI_GAME_CONFIG[type_key]
    if not sync_summary_is_ready(sync_summary):
        return build_bootstrap_pending_payload(type_key, sync_summary, bundle_count, cfg["mainCount"], AI_ENGINE_GEN_LOCAL)
    model_payload, trained_now = ensure_gen_local_model(type_key, sync_summary)
    main_profile = dict(model_payload.get("mainProfile") or {})
    ranking = list(main_profile.get("ranking") or [])
    if not ranking:
        raise RuntimeError("AI Gen 3D chưa tạo được ranking cho không gian số 000-999.")
    tickets = [{"main": bundle, "special": None} for bundle in build_prediction_bundles(ranking, cfg["mainCount"], bundle_count)]
    champion = dict(main_profile.get("champion") or model_payload.get("currentChampion") or {})
    if champion:
        champion["label"] = f"{game_label} • {str(champion.get('label') or 'AI Gen 3D').strip()}"
    result = {
        "ok": True,
        "ready": True,
        "bootstrapComplete": True,
        "mode": "ai_predict",
        "engine": AI_ENGINE_GEN_LOCAL,
        "engineLabel": AI_ENGINE_LABELS[AI_ENGINE_GEN_LOCAL],
        "modelVersion": str(model_payload.get("modelVersion", "")).strip(),
        "type": type_key,
        "label": lr.LIVE_TYPES[type_key].label,
        "model": champion,
        "champion": champion,
        "lastTrainedAt": str(model_payload.get("lastTrainedAt", "")).strip(),
        "trainingSamples": int(main_profile.get("trainingSamples") or model_payload.get("trainingSamples") or 0),
        "confidence": float(main_profile.get("confidence") or model_payload.get("confidence") or 0.0),
        "historyFile": sync_summary["historyFile"],
        "historyCount": sync_summary["historyCount"],
        "latestKy": str(model_payload.get("latestKy", "")).strip(),
        "latestDate": str(model_payload.get("latestDate", "")).strip(),
        "latestTime": str(model_payload.get("latestTime", "")).strip(),
        "nextKy": next_prediction_ky([{"ky": model_payload.get("latestKy", "")}]),
        "bundleCount": bundle_count,
        "pickSize": cfg["mainCount"],
        "topRanking": ranking[:AI_TOP_RANKING_COUNT],
        "topSpecialRanking": [],
        "tickets": tickets,
        "backtest": dict(main_profile.get("backtest") or model_payload.get("recentBacktestSummary") or {}),
        "sync": sync_summary,
        "notes": summarize_gen_local_notes(sync_summary, model_payload, trained_now=trained_now),
        "learnedWeights": list(main_profile.get("strategies") or model_payload.get("learnedWeights") or []),
    }
    if include_meta:
        meta_model, _ = ensure_online_meta_model(type_key, sync_summary)
        result = apply_online_meta_to_result(result, meta_model, AI_ENGINE_GEN_LOCAL)
    return result


def build_luan_so_three_digit_prediction(type_key, bundle_count, sync_summary=None, include_meta=True):
    sync_summary = sync_summary or sync_ai_history(type_key)
    game_label = three_digit_game_label(type_key)
    cfg = AI_GAME_CONFIG[type_key]
    if not sync_summary_is_ready(sync_summary):
        return build_bootstrap_pending_payload(type_key, sync_summary, bundle_count, cfg["mainCount"], AI_ENGINE_LUAN_SO)
    draws = limit_luan_so_draws(type_key, load_ai_draws(type_key))
    if len(draws) < AI_NUMERIC_MIN_HISTORY:
        raise RuntimeError(f"Chưa đủ dữ liệu để chạy Luận Số cho {lr.LIVE_TYPES[type_key].label}.")

    final_weekday = next_target_weekday(type_key, draws[-1])
    ranking = rank_three_digit_candidates(draws, final_weekday, THREE_DIGIT_LUAN_SO_STRATEGY)
    eval_results = evaluate_three_digit_strategies(draws, [THREE_DIGIT_LUAN_SO_STRATEGY], final_weekday)
    best = dict(eval_results[0] or {})
    context = build_three_digit_context(draws, final_weekday)
    top_number = ranking[0] if ranking else 0
    top_support = int((context.get("globalCounts") or [0] * 1000)[top_number])
    top_pair_count = int((context.get("recent24") or [0] * 1000)[top_number])
    top_shrink_factor = clamp01((top_support / 42.0) * 0.62 + (top_pair_count / 12.0) * 0.38)
    strong_pairs = sum(
        1
        for number in ranking[:AI_TOP_RANKING_COUNT]
        if int((context.get("recent12") or [0] * 1000)[number]) >= 1 and int((context.get("globalCounts") or [0] * 1000)[number]) >= 3
    )
    watch_pairs = sum(
        1
        for number in ranking[:AI_TOP_RANKING_COUNT]
        if int((context.get("recent24") or [0] * 1000)[number]) >= 1
    )
    directional_agreement = clamp01((strong_pairs + watch_pairs * 0.4) / 18.0)
    adaptive_score = clamp01(float(best.get("avgHitRate") or 0.0) * 0.44 + top_shrink_factor * 0.30 + directional_agreement * 0.26)
    confidence = clamp01(float(best.get("avgHitRate") or 0.0) * 0.42 + top_shrink_factor * 0.24 + directional_agreement * 0.20 + adaptive_score * 0.14)
    champion = {
        "key": str(THREE_DIGIT_LUAN_SO_STRATEGY.get("key") or "3d_digit_flow"),
        "label": f"Luận Số {game_label}",
        "window": 3,
        "direction": "forward",
        "relationKind": "main_main",
        "topSupport": top_support,
        "topPairCount": top_pair_count,
        "topConfidence": round(confidence, 6),
        "topLift": round(1.0 + top_shrink_factor * 0.35, 6),
        "topShrinkFactor": round(top_shrink_factor, 6),
        "strongPairs": strong_pairs,
        "watchPairs": watch_pairs,
        "adaptiveScore": round(adaptive_score, 6),
    }
    tickets = [{"main": bundle, "special": None} for bundle in build_prediction_bundles(ranking, cfg["mainCount"], bundle_count)]
    latest_draw = draws[-1]
    result = {
        "ok": True,
        "ready": True,
        "bootstrapComplete": True,
        "mode": "ai_predict",
        "engine": AI_ENGINE_LUAN_SO,
        "engineLabel": AI_ENGINE_LABELS[AI_ENGINE_LUAN_SO],
        "modelVersion": LUAN_SO_MODEL_VERSION,
        "type": type_key,
        "label": lr.LIVE_TYPES[type_key].label,
        "model": champion,
        "champion": champion,
        "lastTrainedAt": now_iso(),
        "trainingSamples": len(draws),
        "confidence": round(confidence, 6),
        "historyFile": sync_summary["historyFile"],
        "historyCount": sync_summary["historyCount"],
        "latestKy": latest_draw["ky"],
        "latestDate": latest_draw["date"],
        "latestTime": latest_draw["time"],
        "nextKy": next_prediction_ky(draws),
        "bundleCount": bundle_count,
        "pickSize": cfg["mainCount"],
        "topRanking": ranking[:AI_TOP_RANKING_COUNT],
        "topSpecialRanking": [],
        "tickets": tickets,
        "backtest": {
            "avgHits": round(float(best.get("avgHits") or 0.0), 4),
            "avgHitRate": round(float(best.get("avgHitRate") or 0.0), 6),
            "samples": int(best.get("samples") or 0),
            "specialHitRate": None,
            "shrinkageAdjustedConfidence": round(confidence, 6),
            "shrinkageAdjustedLift": round(float(champion.get("topLift") or 0.0), 6),
            "directionalAgreementRatio": round(directional_agreement, 6),
        },
        "sync": sync_summary,
        "notes": summarize_three_digit_notes(sync_summary, f"Luận Số {game_label} đang gom nhịp recent, gap hồi và tín hiệu chữ số theo vị trí để chấm các số 000-999.", type_key),
        "learnedWeights": [],
        "analysisReport": {},
        "signalSummary": {
            "dominantDirection": "forward",
            "dominantWindow": 3,
            "strongPairCount": strong_pairs,
            "watchPairCount": watch_pairs,
            "filteredPairCount": strong_pairs + watch_pairs,
            "directionalAgreementRatio": round(directional_agreement, 6),
            "topShrinkFactor": round(top_shrink_factor, 6),
            "topEvidence": [],
        },
    }
    if include_meta:
        meta_model, _ = ensure_online_meta_model(type_key, sync_summary)
        result = apply_online_meta_to_result(result, meta_model, AI_ENGINE_LUAN_SO)
    return result


def build_numeric_gen_local_prediction(type_key, bundle_count, sync_summary=None, include_meta=True):
    if is_three_digit_type(type_key):
        return build_three_digit_gen_local_prediction(type_key, bundle_count, sync_summary=sync_summary, include_meta=include_meta)
    sync_summary = sync_summary or sync_ai_history(type_key)
    cfg = AI_GAME_CONFIG[type_key]
    if not sync_summary_is_ready(sync_summary):
        return build_bootstrap_pending_payload(type_key, sync_summary, bundle_count, cfg["mainCount"], AI_ENGINE_GEN_LOCAL)
    model_payload, trained_now = ensure_gen_local_model(type_key, sync_summary)
    main_profile = dict(model_payload.get("mainProfile") or {})
    main_ranking = list(main_profile.get("ranking") or [])
    if not main_ranking:
        raise RuntimeError("AI Gen Local chưa tạo được ranking cho số chính.")
    special_profile = dict(model_payload.get("specialProfile") or {}) if cfg["hasSpecial"] else {}
    special_ranking = list(special_profile.get("ranking") or [])[:AI_SPECIAL_TOP_COUNT]
    tickets = []
    for index, main in enumerate(build_prediction_bundles(main_ranking, cfg["mainCount"], bundle_count)):
        ticket = {"main": main}
        ticket["special"] = special_ranking[index % len(special_ranking)] if special_ranking else (cfg["specialMin"] if cfg["hasSpecial"] else None)
        tickets.append(ticket)
    champion = dict(main_profile.get("champion") or model_payload.get("currentChampion") or {})
    special_champion = dict(special_profile.get("champion") or {}) if special_profile else None
    result = {
        "ok": True,
        "ready": True,
        "bootstrapComplete": True,
        "mode": "ai_predict",
        "engine": AI_ENGINE_GEN_LOCAL,
        "engineLabel": AI_ENGINE_LABELS[AI_ENGINE_GEN_LOCAL],
        "modelVersion": str(model_payload.get("modelVersion", "")).strip(),
        "type": type_key,
        "label": lr.LIVE_TYPES[type_key].label,
        "model": champion,
        "specialModel": special_champion if special_champion and special_champion.get("label") else None,
        "champion": champion,
        "lastTrainedAt": str(model_payload.get("lastTrainedAt", "")).strip(),
        "trainingSamples": int(main_profile.get("trainingSamples") or model_payload.get("trainingSamples") or 0),
        "confidence": float(main_profile.get("confidence") or model_payload.get("confidence") or 0.0),
        "historyFile": sync_summary["historyFile"],
        "historyCount": sync_summary["historyCount"],
        "latestKy": str(model_payload.get("latestKy", "")).strip(),
        "latestDate": str(model_payload.get("latestDate", "")).strip(),
        "latestTime": str(model_payload.get("latestTime", "")).strip(),
        "nextKy": next_prediction_ky([{"ky": model_payload.get("latestKy", "")}]),
        "bundleCount": bundle_count,
        "pickSize": cfg["mainCount"],
        "topRanking": main_ranking[:AI_TOP_RANKING_COUNT],
        "topSpecialRanking": special_ranking,
        "tickets": tickets,
        "backtest": dict(main_profile.get("backtest") or model_payload.get("recentBacktestSummary") or {}),
        "sync": sync_summary,
        "notes": summarize_gen_local_notes(sync_summary, model_payload, trained_now=trained_now),
        "learnedWeights": list(main_profile.get("strategies") or model_payload.get("learnedWeights") or []),
    }
    if include_meta:
        meta_model, _ = ensure_online_meta_model(type_key, sync_summary)
        result = apply_online_meta_to_result(result, meta_model, AI_ENGINE_GEN_LOCAL)
    return result


def build_keno_gen_local_prediction(bundle_count, order, sync_summary=None, include_meta=True):
    sync_summary = sync_summary or sync_ai_history("KENO")
    if not sync_summary_is_ready(sync_summary):
        return build_bootstrap_pending_payload("KENO", sync_summary, bundle_count, order, AI_ENGINE_GEN_LOCAL)
    model_payload, trained_now = ensure_gen_local_model("KENO", sync_summary)
    profiles = dict(model_payload.get("profiles") or {})
    profile = dict(profiles.get(str(order)) or {})
    ranking = list(profile.get("ranking") or [])
    if not ranking:
        raise RuntimeError(f"AI Gen Local chưa tạo được profile cho Keno bậc {order}.")
    tickets = [{"main": bundle, "special": None} for bundle in build_prediction_bundles(ranking, order, bundle_count)]
    champion = dict(profile.get("champion") or model_payload.get("currentChampion") or {})
    top_numbers = ranking[:AI_TOP_RANKING_COUNT]
    result = {
        "ok": True,
        "ready": True,
        "bootstrapComplete": True,
        "mode": "ai_predict",
        "engine": AI_ENGINE_GEN_LOCAL,
        "engineLabel": AI_ENGINE_LABELS[AI_ENGINE_GEN_LOCAL],
        "modelVersion": str(model_payload.get("modelVersion", "")).strip(),
        "type": "KENO",
        "label": "Keno",
        "model": champion,
        "champion": champion,
        "lastTrainedAt": str(model_payload.get("lastTrainedAt", "")).strip(),
        "trainingSamples": int(profile.get("trainingSamples") or model_payload.get("trainingSamples") or 0),
        "confidence": float(profile.get("confidence") or model_payload.get("confidence") or 0.0),
        "historyFile": sync_summary["historyFile"],
        "historyCount": sync_summary["historyCount"],
        "latestKy": str(model_payload.get("latestKy", "")).strip(),
        "latestDate": str(model_payload.get("latestDate", "")).strip(),
        "latestTime": str(model_payload.get("latestTime", "")).strip(),
        "nextKy": next_prediction_ky([{"ky": model_payload.get("latestKy", "")}]),
        "bundleCount": bundle_count,
        "pickSize": order,
        "topRanking": top_numbers,
        "topSpecialRanking": [],
        "tickets": tickets,
        "predictedLn": lr.calc_keno_ln(top_numbers),
        "predictedCl": lr.calc_keno_cl(top_numbers),
        "backtest": dict(profile.get("backtest") or model_payload.get("recentBacktestSummary") or {}),
        "sync": sync_summary,
        "notes": summarize_gen_local_notes(sync_summary, model_payload, trained_now=trained_now),
        "learnedWeights": list(profile.get("strategies") or model_payload.get("learnedWeights") or []),
    }
    if include_meta:
        meta_model, _ = ensure_online_meta_model("KENO", sync_summary)
        result = apply_online_meta_to_result(result, meta_model, AI_ENGINE_GEN_LOCAL)
    return result


def build_numeric_prediction(type_key, bundle_count):
    if is_three_digit_type(type_key):
        return build_three_digit_prediction(type_key, bundle_count)
    sync_summary = sync_ai_history(type_key)
    cfg = AI_GAME_CONFIG[type_key]
    if not sync_summary_is_ready(sync_summary):
        return build_bootstrap_pending_payload(type_key, sync_summary, bundle_count, cfg["mainCount"])
    draws = load_ai_draws(type_key)
    label = lr.LIVE_TYPES[type_key].label
    if len(draws) < AI_NUMERIC_MIN_HISTORY:
        raise RuntimeError(f"Chưa đủ dữ liệu để dự đoán {label}.")

    main_items = build_numeric_main_items(draws)
    final_weekday = next_target_weekday(type_key, draws[-1])
    main_results = evaluate_strategies(
        main_items,
        cfg["mainCount"],
        cfg["mainMax"],
        MAIN_STRATEGIES,
        AI_NUMERIC_MIN_HISTORY,
        AI_NUMERIC_EVAL_SAMPLES,
        final_weekday,
    )
    best_main = main_results[0]

    special_ranking = []
    best_special = None
    if cfg["hasSpecial"]:
        special_items = build_numeric_special_items(draws)
        if special_items:
            special_results = evaluate_strategies(
                special_items,
                1,
                cfg["specialMax"],
                SPECIAL_STRATEGIES,
                AI_NUMERIC_MIN_HISTORY,
                AI_NUMERIC_EVAL_SAMPLES,
                final_weekday,
            )
            if special_results:
                best_special = special_results[0]
                special_ranking = best_special["ranking"][:AI_SPECIAL_TOP_COUNT]

    main_ranking = best_main["ranking"][:max(AI_TOP_RANKING_COUNT, cfg["mainCount"] * bundle_count + 6)]
    tickets = []
    main_bundles = build_prediction_bundles(main_ranking, cfg["mainCount"], bundle_count)
    for index, main in enumerate(main_bundles):
        ticket = {"main": main}
        ticket["special"] = special_ranking[index % len(special_ranking)] if special_ranking else (cfg["specialMin"] if cfg["hasSpecial"] else None)
        tickets.append(ticket)

    latest_draw = draws[-1]
    return {
        "ok": True,
        "ready": True,
        "bootstrapComplete": True,
        "mode": "ai_predict",
        "engine": AI_ENGINE_CLASSIC,
        "engineLabel": AI_ENGINE_LABELS[AI_ENGINE_CLASSIC],
        "type": type_key,
        "label": label,
        "model": {
            "key": best_main["key"],
            "label": best_main["label"],
            "samples": best_main["samples"],
            "avgHits": round(best_main["avgHits"], 4),
            "avgHitRate": round(best_main["avgHitRate"], 6),
        },
        "specialModel": {
            "key": best_special["key"],
            "label": best_special["label"],
            "samples": best_special["samples"],
            "avgHits": round(best_special["avgHits"], 4),
            "avgHitRate": round(best_special["avgHitRate"], 6),
        } if best_special else None,
        "historyFile": sync_summary["historyFile"],
        "historyCount": sync_summary["historyCount"],
        "latestKy": latest_draw["ky"],
        "latestDate": latest_draw["date"],
        "latestTime": latest_draw["time"],
        "nextKy": next_prediction_ky(draws),
        "bundleCount": bundle_count,
        "pickSize": cfg["mainCount"],
        "topRanking": best_main["ranking"][:AI_TOP_RANKING_COUNT],
        "topSpecialRanking": special_ranking,
        "tickets": tickets,
        "backtest": {
            "avgHits": round(best_main["avgHits"], 4),
            "avgHitRate": round(best_main["avgHitRate"], 6),
            "samples": best_main["samples"],
            "specialHitRate": round(best_special["avgHitRate"], 6) if best_special else None,
        },
        "sync": sync_summary,
        "notes": summarize_sync_notes(sync_summary),
    }


def build_keno_prediction(bundle_count, order):
    sync_summary = sync_ai_history("KENO")
    if not sync_summary_is_ready(sync_summary):
        return build_bootstrap_pending_payload("KENO", sync_summary, bundle_count, order)
    draws = load_ai_draws("KENO")
    if len(draws) < AI_KENO_MIN_HISTORY:
        raise RuntimeError("Chưa đủ dữ liệu để dự đoán Keno.")

    items = [{"numbers": draw["main"], "weekday": draw["weekday"]} for draw in draws]
    final_weekday = next_target_weekday("KENO", draws[-1])
    results = evaluate_strategies(
        items,
        order,
        80,
        MAIN_STRATEGIES,
        AI_KENO_MIN_HISTORY,
        AI_KENO_EVAL_SAMPLES,
        final_weekday,
    )
    best = results[0]
    ranking = best["ranking"][:max(AI_TOP_RANKING_COUNT, order * bundle_count + 10)]
    tickets = [{"main": bundle, "special": None} for bundle in build_prediction_bundles(ranking, order, bundle_count)]
    top_numbers = ranking[:AI_TOP_RANKING_COUNT]
    latest_draw = draws[-1]
    return {
        "ok": True,
        "ready": True,
        "bootstrapComplete": True,
        "mode": "ai_predict",
        "engine": AI_ENGINE_CLASSIC,
        "engineLabel": AI_ENGINE_LABELS[AI_ENGINE_CLASSIC],
        "type": "KENO",
        "label": "Keno",
        "model": {
            "key": best["key"],
            "label": best["label"],
            "samples": best["samples"],
            "avgHits": round(best["avgHits"], 4),
            "avgHitRate": round(best["avgHitRate"], 6),
        },
        "historyFile": sync_summary["historyFile"],
        "historyCount": sync_summary["historyCount"],
        "latestKy": latest_draw["ky"],
        "latestDate": latest_draw["date"],
        "latestTime": latest_draw["time"],
        "nextKy": next_prediction_ky(draws),
        "bundleCount": bundle_count,
        "pickSize": order,
        "topRanking": top_numbers,
        "topSpecialRanking": [],
        "tickets": tickets,
        "predictedLn": lr.calc_keno_ln(top_numbers),
        "predictedCl": lr.calc_keno_cl(top_numbers),
        "backtest": {
            "avgHits": round(best["avgHits"], 4),
            "avgHitRate": round(best["avgHitRate"], 6),
            "samples": best["samples"],
        },
        "sync": sync_summary,
        "notes": summarize_sync_notes(sync_summary),
    }


# ----- API du doan cong khai -----
# Day la lop public ma Java server goi toi khi can lay payload predict_json/sync_json/train_json.
def predict_json(type_key, bundle_count, keno_level=None, engine=AI_ENGINE_CLASSIC, risk_mode=AI_RISK_MODE_BALANCED, prediction_mode=PREDICTION_MODE_NORMAL):
    if type_key not in AI_SUPPORTED_TYPES:
        raise ValueError("Loại AI không được hỗ trợ.")
    engine = normalize_engine(engine)
    risk_mode = normalize_risk_mode(risk_mode)
    prediction_mode = normalize_prediction_mode(prediction_mode)
    bundle_count = normalize_positive_int(bundle_count, "Số bộ")
    if type_key == "KENO":
        order = normalize_positive_int(keno_level, "Bậc Keno")
        if order < 1 or order > 10:
            raise ValueError("Bậc Keno phải trong khoảng 1-10.")
        max_bundles = max(1, 80 // order)
        if bundle_count > max_bundles:
            raise ValueError(f"Số bộ Keno tối đa cho bậc {order} là {max_bundles}.")
        if engine == AI_ENGINE_LUAN_SO:
            payload = attach_risk_mode_metadata(build_luan_so_prediction("KENO", bundle_count, order), risk_mode)
            return apply_vip_prediction_profile(payload, bundle_count) if prediction_mode == PREDICTION_MODE_VIP else payload
        if engine == AI_ENGINE_GEN_LOCAL:
            payload = attach_risk_mode_metadata(build_keno_gen_local_prediction(bundle_count, order), risk_mode)
            return apply_vip_prediction_profile(payload, bundle_count) if prediction_mode == PREDICTION_MODE_VIP else payload
        payload = attach_risk_mode_metadata(build_keno_prediction(bundle_count, order), risk_mode)
        return apply_vip_prediction_profile(payload, bundle_count) if prediction_mode == PREDICTION_MODE_VIP else payload
    if engine == AI_ENGINE_LUAN_SO:
        payload = attach_risk_mode_metadata(build_luan_so_prediction(type_key, bundle_count), risk_mode)
        return apply_vip_prediction_profile(payload, bundle_count) if prediction_mode == PREDICTION_MODE_VIP else payload
    if engine == AI_ENGINE_GEN_LOCAL:
        payload = attach_risk_mode_metadata(build_numeric_gen_local_prediction(type_key, bundle_count), risk_mode)
        return apply_vip_prediction_profile(payload, bundle_count) if prediction_mode == PREDICTION_MODE_VIP else payload
    payload = attach_risk_mode_metadata(build_numeric_prediction(type_key, bundle_count), risk_mode)
    return apply_vip_prediction_profile(payload, bundle_count) if prediction_mode == PREDICTION_MODE_VIP else payload


def sync_json(type_key):
    if type_key not in AI_SUPPORTED_TYPES:
        raise ValueError("Loại AI không được hỗ trợ.")
    return {
        "ok": True,
        "mode": "ai_sync",
        "type": type_key,
        "sync": sync_ai_history(type_key),
    }

def build_scoring_csv_text(rows):
    header = ["rank", "number", "frequencyCount", "recentCount", "currentDelay", "F_i", "D_i", "T_i", "C_i", "Score_i"]
    lines = [",".join(header)]
    for index, row in enumerate(rows or [], start=1):
        lines.append(",".join([
            str(index),
            str(row.get("number", "")),
            str(row.get("frequencyCount", "")),
            str(row.get("recentCount", "")),
            str(row.get("currentDelay", "")),
            str(row.get("F_i", "")),
            str(row.get("D_i", "")),
            str(row.get("T_i", "")),
            str(row.get("C_i", "")),
            str(row.get("Score_i", "")),
        ]))
    return "\n".join(lines)


def write_scoring_csv_export(type_key, rows, recent_window, limit_value=None, top_only=False, file_slug=None):
    SCORING_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    type_slug = str(file_slug or f"{str(type_key or '').strip().lower()}_number_scoring").strip().lower()
    prefix = f"{type_slug}_"
    for old_path in SCORING_EXPORT_DIR.glob(f"{prefix}*.csv"):
        try:
            old_path.unlink()
        except OSError:
            pass
    scope = "toponly" if top_only else (f"limit{int(limit_value)}" if limit_value is not None else "full")
    file_name = f"{type_slug}_{scope}_latest.csv"
    file_path = SCORING_EXPORT_DIR / file_name
    file_path.write_text(build_scoring_csv_text(rows), encoding="utf-8")
    return file_path


def build_special_scoring_draws(draws):
    items = []
    for draw in draws or []:
        special = draw.get("special")
        if not isinstance(special, int):
            continue
        items.append({
            "draw_id": str(draw.get("ky", "")).strip(),
            "draw_date": str(draw.get("date", "")).strip(),
            "numbers": [int(special)],
        })
    return items


def build_special_scoring_universe(type_key):
    cfg = AI_GAME_CONFIG.get(type_key) or {}
    if not cfg.get("hasSpecial"):
        return None
    special_min = int(cfg.get("specialMin") or 0)
    special_max = int(cfg.get("specialMax") or 0)
    if special_min <= 0 or special_max < special_min:
        return None
    return range(special_min, special_max + 1)


def export_special_scoring_csv(type_key, draws, recent_window, weights, co_top_k):
    universe = build_special_scoring_universe(type_key)
    if universe is None:
        return None
    scoring_draws = build_special_scoring_draws(draws)
    if not scoring_draws:
        return None
    rows = ns.build_number_scoring_rows(
        scoring_draws,
        universe,
        recent_window=recent_window,
        weights=weights,
        co_top_k=co_top_k,
        number_formatter=build_scoring_number_formatter(type_key),
    )
    csv_path = write_scoring_csv_export(
        type_key,
        rows,
        recent_window,
        limit_value=None,
        top_only=False,
        file_slug=f"{str(type_key or '').strip().lower()}_special_number_scoring",
    )
    return {
        "rows": rows,
        "csvSaved": True,
        "csvFileName": csv_path.name,
        "csvRelativePath": str(csv_path.relative_to(Path(__file__).resolve().parent)).replace("\\", "/"),
        "csvPath": str(csv_path),
        "returnedRows": len(rows),
        "topNumbers": [item["number"] for item in rows[:min(SCORING_DEFAULT_TOP_ROWS, len(rows))]],
    }


def score_json(type_key, recent_window=None, weights=None, co_top_k=None, include_backtest=False, backtest_top_k=None,
               limit=None, top_only=False, export_csv=False):
    if type_key not in AI_SUPPORTED_TYPES:
        raise ValueError("Loại scoring không được hỗ trợ.")
    sync_summary = sync_ai_history(type_key)
    draws = load_ai_draws(type_key)
    if not draws:
        raise RuntimeError("Không có dữ liệu lịch sử để chấm điểm.")
    scoring_draws = build_scoring_draws(draws)
    recent_window_value = normalize_optional_positive_int(recent_window, "recent_window") or default_scoring_recent_window(type_key)
    co_top_k_value = normalize_optional_positive_int(co_top_k, "co_top_k") or ns.DEFAULT_CO_TOP_K
    weights_value = ns.normalize_weights(weights)
    universe = build_scoring_universe(type_key)
    formatter = build_scoring_number_formatter(type_key)
    universe_size = len(list(universe)) if not isinstance(universe, range) else len(universe)
    limit_value = normalize_optional_positive_int(limit, "limit")
    backtest_top_k_value = min(
        universe_size,
        int(normalize_optional_positive_int(backtest_top_k, "backtest_top_k") or default_scoring_backtest_top_k(type_key)),
    )
    all_rows = ns.build_number_scoring_rows(
        scoring_draws,
        universe,
        recent_window=recent_window_value,
        weights=weights_value,
        co_top_k=co_top_k_value,
        number_formatter=formatter,
    )
    top_rows = all_rows[:min(SCORING_DEFAULT_TOP_ROWS, len(all_rows))]
    if top_only:
        visible_rows = list(top_rows)
    elif limit_value is not None:
        visible_rows = all_rows[:limit_value]
    else:
        visible_rows = all_rows
    latest_draw = draws[-1]
    payload = {
        "ok": True,
        "mode": "number_scoring",
        "type": type_key,
        "label": lr.LIVE_TYPES[type_key].label,
        "historyFile": sync_summary["historyFile"],
        "historyCount": sync_summary["historyCount"],
        "latestKy": latest_draw["ky"],
        "latestDate": latest_draw["date"],
        "latestTime": latest_draw["time"],
        "params": {
            "recentWindow": recent_window_value,
            "weights": {
                "a": round(weights_value[0], 6),
                "b": round(weights_value[1], 6),
                "c": round(weights_value[2], 6),
                "d": round(weights_value[3], 6),
            },
            "weightsVector": [round(value, 6) for value in weights_value],
            "coTopK": co_top_k_value,
            "backtestTopK": backtest_top_k_value,
            "backtestEnabled": bool(include_backtest),
            "limit": limit_value,
            "topOnly": bool(top_only),
            "exportCsv": bool(export_csv),
        },
        "totalRows": len(all_rows),
        "returnedRows": len(visible_rows),
        "rows": visible_rows,
        "topRows": top_rows,
        "topNumbers": [item["number"] for item in top_rows],
        "notes": [
            "Score_i là điểm xếp hạng thống kê, không phải xác suất trúng tuyệt đối.",
            "T_i dùng trend delta giữa recent rate và long-term rate.",
            f"C_i dùng trung bình strength của Top {co_top_k_value} partner mạnh nhất.",
        ],
        "sync": sync_summary,
    }
    if export_csv:
        csv_text = build_scoring_csv_text(visible_rows)
        csv_path = write_scoring_csv_export(type_key, visible_rows, recent_window_value, limit_value, top_only)
        payload["csvFileName"] = csv_path.name
        payload["csvRelativePath"] = str(csv_path.relative_to(Path(__file__).resolve().parent)).replace("\\", "/")
        payload["csvPath"] = str(csv_path)
        payload["csvSaved"] = True
        payload["csvText"] = csv_text
    if include_backtest:
        min_history = max(recent_window_value, SCORING_DEFAULT_RECENT_WINDOW_KENO if type_key == "KENO" else SCORING_DEFAULT_RECENT_WINDOW_NUMERIC)
        payload["backtest"] = ns.backtest_number_scoring(
            scoring_draws,
            universe,
            recent_window=recent_window_value,
            weights=weights_value,
            co_top_k=co_top_k_value,
            top_k=backtest_top_k_value,
            min_history=min_history,
            number_formatter=formatter,
        )
    return payload


def score_csv(type_key, recent_window=None, weights=None, co_top_k=None, include_backtest=False, backtest_top_k=None,
              limit=None, top_only=False):
    payload = score_json(
        type_key,
        recent_window=recent_window,
        weights=weights,
        co_top_k=co_top_k,
        include_backtest=include_backtest,
        backtest_top_k=backtest_top_k,
        limit=limit,
        top_only=top_only,
        export_csv=True,
    )
    result = {
        "ok": bool(payload.get("ok")),
        "mode": "number_scoring_csv",
        "type": payload.get("type"),
        "label": payload.get("label"),
        "message": "Đã xuất file CSV scoring mới nhất thành công.",
        "historyFile": payload.get("historyFile"),
        "historyCount": payload.get("historyCount"),
        "latestKy": payload.get("latestKy"),
        "latestDate": payload.get("latestDate"),
        "latestTime": payload.get("latestTime"),
        "params": payload.get("params", {}),
        "totalRows": payload.get("totalRows"),
        "returnedRows": payload.get("returnedRows"),
        "topNumbers": payload.get("topNumbers", []),
        "csvSaved": bool(payload.get("csvSaved")),
        "csvFileName": payload.get("csvFileName"),
        "csvRelativePath": payload.get("csvRelativePath"),
        "csvPath": payload.get("csvPath"),
        "notes": payload.get("notes", []),
        "sync": payload.get("sync"),
    }
    if include_backtest and "backtest" in payload:
        result["backtest"] = payload["backtest"]
    if str(type_key or "").strip().upper() == "LOTO_5_35":
        special_export = export_special_scoring_csv(
            type_key,
            load_ai_draws(type_key),
            int(payload.get("params", {}).get("recentWindow") or default_scoring_recent_window(type_key)),
            ns.normalize_weights(weights),
            int(payload.get("params", {}).get("coTopK") or ns.DEFAULT_CO_TOP_K),
        )
        if special_export:
            result["specialCsvSaved"] = bool(special_export.get("csvSaved"))
            result["specialCsvFileName"] = special_export.get("csvFileName")
            result["specialCsvRelativePath"] = special_export.get("csvRelativePath")
            result["specialCsvPath"] = special_export.get("csvPath")
            result["specialReturnedRows"] = special_export.get("returnedRows")
            result["specialTopNumbers"] = special_export.get("topNumbers", [])
    return result


def extract_engine_arg(extra_args):
    engine = AI_ENGINE_CLASSIC
    remaining = []
    for raw in extra_args:
        text = str(raw or "").strip()
        if not text:
            continue
        if text.startswith("--engine="):
            engine = text.split("=", 1)[1]
            continue
        if text.lower() in AI_ENGINE_LABELS:
            engine = text.lower()
            continue
        remaining.append(text)
    return normalize_engine(engine), remaining


def extract_risk_mode_arg(extra_args):
    risk_mode = AI_RISK_MODE_BALANCED
    remaining = []
    for raw in extra_args:
        text = str(raw or "").strip()
        if not text:
            continue
        if text.startswith("--risk-mode="):
            risk_mode = text.split("=", 1)[1]
            continue
        remaining.append(text)
    return normalize_risk_mode(risk_mode), remaining


def extract_prediction_mode_arg(extra_args):
    prediction_mode = PREDICTION_MODE_NORMAL
    remaining = []
    for raw in extra_args:
        text = str(raw or "").strip()
        if not text:
            continue
        if text.startswith("--prediction-mode="):
            prediction_mode = text.split("=", 1)[1]
            continue
        remaining.append(text)
    return normalize_prediction_mode(prediction_mode), remaining


def extract_recent_window_arg(extra_args):
    recent_window = None
    remaining = []
    for raw in extra_args:
        text = str(raw or "").strip()
        if not text:
            continue
        if text.startswith("--recent-window="):
            recent_window = text.split("=", 1)[1]
            continue
        remaining.append(text)
    return recent_window, remaining


def extract_weights_arg(extra_args):
    weights = None
    remaining = []
    for raw in extra_args:
        text = str(raw or "").strip()
        if not text:
            continue
        if text.startswith("--weights="):
            weights = text.split("=", 1)[1]
            continue
        remaining.append(text)
    return weights, remaining


def extract_co_top_k_arg(extra_args):
    co_top_k = None
    remaining = []
    for raw in extra_args:
        text = str(raw or "").strip()
        if not text:
            continue
        if text.startswith("--co-top-k="):
            co_top_k = text.split("=", 1)[1]
            continue
        remaining.append(text)
    return co_top_k, remaining


def extract_backtest_args(extra_args):
    include_backtest = False
    backtest_top_k = None
    remaining = []
    for raw in extra_args:
        text = str(raw or "").strip()
        if not text:
            continue
        if text == "--backtest":
            include_backtest = True
            continue
        if text.startswith("--backtest="):
            lowered = text.split("=", 1)[1].strip().lower()
            include_backtest = lowered not in {"0", "false", "off", "no"}
            continue
        if text.startswith("--backtest-top-k="):
            backtest_top_k = text.split("=", 1)[1]
            continue
        remaining.append(text)
    return include_backtest, backtest_top_k, remaining


def extract_limit_arg(extra_args):
    limit = None
    remaining = []
    for raw in extra_args:
        text = str(raw or "").strip()
        if not text:
            continue
        if text.startswith("--limit="):
            limit = text.split("=", 1)[1]
            continue
        remaining.append(text)
    return limit, remaining


def extract_top_only_arg(extra_args):
    top_only = False
    remaining = []
    for raw in extra_args:
        text = str(raw or "").strip()
        if not text:
            continue
        if text == "--top-only":
            top_only = True
            continue
        if text.startswith("--top-only="):
            lowered = text.split("=", 1)[1].strip().lower()
            top_only = lowered not in {"0", "false", "off", "no"}
            continue
        remaining.append(text)
    return top_only, remaining


def extract_export_csv_arg(extra_args):
    export_csv = False
    remaining = []
    for raw in extra_args:
        text = str(raw or "").strip()
        if not text:
            continue
        if text == "--export-csv":
            export_csv = True
            continue
        if text.startswith("--export-csv="):
            lowered = text.split("=", 1)[1].strip().lower()
            export_csv = lowered not in {"0", "false", "off", "no"}
            continue
        remaining.append(text)
    return export_csv, remaining


# ----- Diem vao CLI -----
# Ho tro goi file truc tiep tu terminal de predict, sync va train model.
def main():
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        mode = str(sys.argv[1] if len(sys.argv) > 1 else "help").strip().lower()
        if mode in {"predict_json", "predict-json", "predict"}:
            if len(sys.argv) < 4:
                raise ValueError("Thiếu tham số: ai_predict.py predict_json TYPE COUNT [KENO_LEVEL]")
            type_key = str(sys.argv[2]).strip().upper()
            bundle_count = sys.argv[3]
            extra_args = list(sys.argv[4:])
            engine, remaining = extract_engine_arg(extra_args)
            risk_mode, remaining = extract_risk_mode_arg(remaining)
            prediction_mode, remaining = extract_prediction_mode_arg(remaining)
            keno_level = remaining[0] if remaining else None
            payload = predict_json(type_key, bundle_count, keno_level, engine, risk_mode, prediction_mode)
        elif mode in {"sync_json", "sync-json", "sync"}:
            if len(sys.argv) < 3:
                raise ValueError("Thiếu tham số: ai_predict.py sync_json TYPE")
            payload = sync_json(str(sys.argv[2]).strip().upper())
        elif mode in {"train_json", "train-json", "train"}:
            if len(sys.argv) < 3:
                raise ValueError("Thiếu tham số: ai_predict.py train_json TYPE [ENGINE]")
            type_key = str(sys.argv[2]).strip().upper()
            engine, _ = extract_engine_arg(list(sys.argv[3:]))
            if engine != AI_ENGINE_GEN_LOCAL:
                raise ValueError("V1 chỉ hỗ trợ train cho engine gen_local.")
            payload = train_gen_local_json(type_key)
        elif mode in {"train_all", "train-all"}:
            engine, _ = extract_engine_arg(list(sys.argv[2:]))
            if engine != AI_ENGINE_GEN_LOCAL:
                raise ValueError("V1 chỉ hỗ trợ train_all cho engine gen_local.")
            payload = train_all_gen_local_json()
        elif mode in {"score_json", "score-json", "score"}:
            if len(sys.argv) < 3:
                raise ValueError("Thiếu tham số: ai_predict.py score_json TYPE")
            type_key = str(sys.argv[2]).strip().upper()
            extra_args = list(sys.argv[3:])
            recent_window, remaining = extract_recent_window_arg(extra_args)
            weights, remaining = extract_weights_arg(remaining)
            co_top_k, remaining = extract_co_top_k_arg(remaining)
            include_backtest, backtest_top_k, remaining = extract_backtest_args(remaining)
            limit, remaining = extract_limit_arg(remaining)
            top_only, remaining = extract_top_only_arg(remaining)
            export_csv, remaining = extract_export_csv_arg(remaining)
            if remaining:
                raise ValueError("Tham số score_json không hợp lệ.")
            payload = score_json(type_key, recent_window, weights, co_top_k, include_backtest, backtest_top_k, limit, top_only, export_csv)
        elif mode in {"score_csv", "score-csv"}:
            if len(sys.argv) < 3:
                raise ValueError("Thiếu tham số: ai_predict.py score_csv TYPE")
            type_key = str(sys.argv[2]).strip().upper()
            extra_args = list(sys.argv[3:])
            recent_window, remaining = extract_recent_window_arg(extra_args)
            weights, remaining = extract_weights_arg(remaining)
            co_top_k, remaining = extract_co_top_k_arg(remaining)
            include_backtest, backtest_top_k, remaining = extract_backtest_args(remaining)
            limit, remaining = extract_limit_arg(remaining)
            top_only, remaining = extract_top_only_arg(remaining)
            _, remaining = extract_export_csv_arg(remaining)
            if remaining:
                raise ValueError("Tham số score_csv không hợp lệ.")
            payload = score_csv(type_key, recent_window, weights, co_top_k, include_backtest, backtest_top_k, limit, top_only)
        else:
            payload = {
                "ok": False,
                "message": "Mode không hợp lệ. Dùng predict_json TYPE COUNT [KENO_LEVEL] [--engine=classic|gen_local|luan_so] [--risk-mode=stable|balanced|aggressive] [--prediction-mode=normal|vip], sync_json TYPE, train_json TYPE [--engine=gen_local], train_all [--engine=gen_local], score_json TYPE [--recent-window=N] [--weights=a,b,c,d] [--co-top-k=K] [--backtest] [--backtest-top-k=N] [--limit=N] [--top-only] [--export-csv], hoặc score_csv TYPE [--recent-window=N] [--weights=a,b,c,d] [--co-top-k=K] [--backtest] [--backtest-top-k=N] [--limit=N] [--top-only].",
            }
        print(json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "message": str(exc),
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
