from __future__ import annotations

import csv
import json
from datetime import timedelta
from pathlib import Path

import ai.configs.data_paths as dp


SUPPORTED_GAME = "loto_5_35"
SUPPORTED_TYPE = "LOTO_5_35"
SUPPORTED_SLOTS = ("13:00", "21:00")
HEADER_ALIASES = {
    "Ky": ("Ky", "Kỳ"),
    "Ngay": ("Ngay", "Ngày"),
    "Time": ("Time", "Giờ", "Thời Gian"),
    "Main": ("Main", "Bộ Số", "Numbers"),
    "Special": ("Special", "ĐB"),
    "Label": ("Label", "Loại"),
}


def _sort_key_from_ky(ky_value) -> int:
    digits = "".join(ch for ch in str(ky_value or "") if ch.isdigit())
    return int(digits) if digits else -1


def _parse_csv_date(raw_value):
    parts = str(raw_value or "").strip().split("/")
    if len(parts) != 3:
        return None
    try:
        day, month, year = (int(part) for part in parts)
    except ValueError:
        return None
    try:
        from datetime import date

        return date(year, month, day)
    except ValueError:
        return None


def _format_csv_date(date_obj) -> str:
    return date_obj.strftime("%d/%m/%Y") if date_obj else ""


def _parse_number_list(raw_value):
    values = []
    for token in str(raw_value or "").split(","):
        token = token.strip()
        if token.isdigit():
            values.append(int(token))
    return values


def normalize_game(game: str = SUPPORTED_GAME) -> str:
    normalized = str(game or "").strip().lower()
    if normalized not in {SUPPORTED_GAME, "loto5/35", "loto_5_35"}:
        raise ValueError("predictor_v2 hiện chỉ hỗ trợ loto_5_35.")
    return SUPPORTED_GAME


def normalize_slot(raw_slot: str | None) -> str:
    value = str(raw_slot or "").strip()
    return value if value in SUPPORTED_SLOTS else ""


def canonical_csv_path() -> Path:
    return dp.get_canonical_csv_read_path(SUPPORTED_TYPE)


def _resolve_header_map(fieldnames):
    resolved = {}
    header_lookup = {str(name or "").strip().lower(): name for name in list(fieldnames or [])}
    for canonical, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            actual = header_lookup.get(str(alias).strip().lower())
            if actual:
                resolved[canonical] = actual
                break
    return resolved


def _read_row_value(row, header_map, canonical):
    actual_key = header_map.get(canonical)
    if not actual_key:
        return ""
    return row.get(actual_key, "")


def load_history(game: str = SUPPORTED_GAME):
    normalize_game(game)
    path = canonical_csv_path()
    draws = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        header_map = _resolve_header_map(reader.fieldnames)
        for row in reader:
            date_obj = _parse_csv_date(_read_row_value(row, header_map, "Ngay"))
            main = sorted(set(_parse_number_list(_read_row_value(row, header_map, "Main"))))
            special_text = str(_read_row_value(row, header_map, "Special")).strip()
            slot = normalize_slot(_read_row_value(row, header_map, "Time"))
            if date_obj is None or len(main) != 5 or not slot or not special_text.isdigit():
                continue
            ky_text = str(_read_row_value(row, header_map, "Ky")).strip()
            draws.append(
                {
                    "ky": ky_text,
                    "ky_int": _sort_key_from_ky(ky_text),
                    "date": _format_csv_date(date_obj),
                    "date_obj": date_obj,
                    "time": slot,
                    "slot": slot,
                    "weekday": date_obj.weekday(),
                    "main": main,
                    "special": int(special_text),
                    "label": str(_read_row_value(row, header_map, "Label")).strip(),
                }
            )
    draws.sort(key=lambda item: item["ky_int"])
    return draws


def latest_actual_draw(draws):
    return draws[-1] if draws else None


def find_draw_by_ky(draws, ky_value):
    target = _sort_key_from_ky(ky_value)
    for draw in draws:
        if draw.get("ky_int") == target:
            return draw
    return None


def infer_next_target_draw(draws, slot: str | None = None):
    latest = latest_actual_draw(draws)
    if not latest:
        raise RuntimeError("Không tìm thấy lịch sử loto_5_35 để xác định kỳ đích.")
    requested_slot = normalize_slot(slot)
    if requested_slot:
        target_slot = requested_slot
        if latest["slot"] == "13:00" and target_slot == "21:00":
            target_date = latest["date_obj"]
        elif latest["slot"] == "21:00" and target_slot == "13:00":
            target_date = latest["date_obj"] + timedelta(days=1)
        elif latest["slot"] == target_slot:
            target_date = latest["date_obj"] + timedelta(days=1)
        else:
            target_date = latest["date_obj"]
    elif latest["slot"] == "13:00":
        target_slot = "21:00"
        target_date = latest["date_obj"]
    else:
        target_slot = "13:00"
        target_date = latest["date_obj"] + timedelta(days=1)
    next_ky = latest["ky_int"] + 1 if latest["ky_int"] >= 0 else ""
    return {
        "target_draw_id": str(next_ky) if next_ky != "" else "",
        "target_slot": target_slot,
        "target_date": _format_csv_date(target_date),
        "target_date_obj": target_date,
        "target_weekday": target_date.weekday(),
        "same_day_follow_up": target_date == latest["date_obj"] and target_slot != latest["slot"],
        "latest_actual_draw": latest,
        "previous_draw": draws[-2] if len(draws) > 1 else None,
    }


def build_sync_summary(draws):
    meta_path = dp.get_canonical_meta_read_path(SUPPORTED_TYPE)
    meta = {}
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    latest = latest_actual_draw(draws) or {}
    earliest = draws[0] if draws else {}
    return {
        "type": SUPPORTED_TYPE,
        "label": "Loto_5/35",
        "historyFile": canonical_csv_path().name,
        "historyCount": len(draws),
        "latestKy": str(latest.get("ky", "")),
        "latestDate": str(latest.get("date", "")),
        "latestTime": str(latest.get("slot", "")),
        "effectiveEarliestKy": str(earliest.get("ky", "")),
        "effectiveEarliestDate": str(earliest.get("date", "")),
        "bootstrapComplete": bool(meta.get("bootstrapComplete", True)),
        "sourceLimited": bool(meta.get("sourceLimited", False)),
        "errors": [],
    }
