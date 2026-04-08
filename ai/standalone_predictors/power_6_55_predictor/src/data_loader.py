from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from src import PROJECT_ROOT


DEFAULT_COLUMN_MAPPING_PATH = PROJECT_ROOT / "config" / "column_mapping.json"


@dataclass(frozen=True)
class DrawRecord:
    draw_id: int
    weekday_text: str
    draw_date: date
    draw_time: str | None
    main_numbers: tuple[int, ...]
    special: int
    display_text: str
    game_label: str
    source_url: str
    source_date: date | None
    raw_row: dict[str, str]


def resolve_project_path(path_value: str | Path, project_root: Path | None = None) -> Path:
    project_root = project_root or PROJECT_ROOT
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate
    if candidate.exists():
        return candidate.resolve()
    return (project_root / candidate).resolve()


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def normalize_header_label(value: Any) -> str:
    text = str(value or "").strip().lower().replace("đ", "d")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text)


def parse_csv_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def format_csv_date(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value is not None else ""


def parse_optional_time(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def parse_main_numbers(raw_value: Any) -> tuple[int, ...]:
    tokens = [token.strip() for token in str(raw_value or "").split(",") if token.strip()]
    if len(tokens) != 6:
        raise ValueError(f"Expected 6 main numbers, got {len(tokens)} from {raw_value!r}.")
    values = sorted(int(token) for token in tokens)
    if len(set(values)) != 6:
        raise ValueError(f"Main numbers must be unique: {raw_value!r}.")
    if any(value < 1 or value > 55 for value in values):
        raise ValueError(f"Main numbers must be between 1 and 55: {raw_value!r}.")
    return tuple(values)


def parse_special(value: Any) -> int:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Power 6/55 special value is required.")
    special = int(text)
    if special < 1 or special > 55:
        raise ValueError(f"Special number must be between 1 and 55: {value!r}.")
    return special


def parse_actual_main_numbers(raw_value: Any) -> tuple[int, ...]:
    return parse_main_numbers(raw_value)


def parse_actual_special(raw_value: Any) -> int:
    return parse_special(raw_value)


def load_column_mapping(path: str | Path | None = None) -> dict[str, list[str]]:
    path = resolve_project_path(path or DEFAULT_COLUMN_MAPPING_PATH)
    payload = read_json(path, {})
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid column mapping file: {path}")
    return {str(key): list(value or []) for key, value in payload.items()}


def resolve_header_mapping(headers: list[str], column_mapping: dict[str, list[str]]) -> dict[str, str]:
    normalized_headers = {normalize_header_label(header): header for header in headers}
    resolved: dict[str, str] = {}
    for logical_name, aliases in column_mapping.items():
        for alias in aliases:
            actual = normalized_headers.get(normalize_header_label(alias))
            if actual is not None:
                resolved[logical_name] = actual
                break
    required = ("draw_id", "draw_date", "main_numbers_raw", "special_raw", "game_label")
    missing = [name for name in required if name not in resolved]
    if missing:
        raise ValueError(f"Missing required CSV columns: {', '.join(missing)}.")
    return resolved


def _validate_game_label(label: str) -> None:
    normalized = normalize_header_label(label)
    if normalized and "power" not in normalized and "6/55" not in normalized:
        raise ValueError(f"Unexpected game label for Power 6/55 dataset: {label!r}")


def _fallback_weekday_text(draw_date: date) -> str:
    mapping = {
        0: "Thứ 2",
        1: "Thứ 3",
        2: "Thứ 4",
        3: "Thứ 5",
        4: "Thứ 6",
        5: "Thứ 7",
        6: "Chủ nhật",
    }
    return mapping.get(draw_date.weekday(), "")


def load_draw_records(csv_path: str | Path, column_mapping_path: str | Path | None = None) -> dict[str, Any]:
    csv_path = resolve_project_path(csv_path)
    column_mapping = load_column_mapping(column_mapping_path)

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        header_mapping = resolve_header_mapping(headers, column_mapping)
        records: list[DrawRecord] = []
        non_blank_time_count = 0
        for row in reader:
            if not any(str(value or "").strip() for value in row.values()):
                continue
            draw_id = int(str(row.get(header_mapping["draw_id"], "")).strip())
            draw_date = parse_csv_date(row.get(header_mapping["draw_date"]))
            if draw_date is None:
                raise ValueError(f"Invalid draw date in row {row!r}")
            draw_time = parse_optional_time(row.get(header_mapping.get("draw_time", "")))
            main_numbers = parse_main_numbers(row.get(header_mapping["main_numbers_raw"]))
            special = parse_special(row.get(header_mapping["special_raw"]))
            weekday_text = str(row.get(header_mapping.get("weekday_text", ""), "")).strip() or _fallback_weekday_text(draw_date)
            display_text = str(row.get(header_mapping.get("display_text", ""), "")).strip()
            game_label = str(row.get(header_mapping["game_label"], "")).strip()
            _validate_game_label(game_label)
            source_url = str(row.get(header_mapping.get("source_url", ""), "")).strip()
            source_date = parse_csv_date(row.get(header_mapping.get("source_date", "")))
            if draw_time:
                non_blank_time_count += 1
            records.append(
                DrawRecord(
                    draw_id=draw_id,
                    weekday_text=weekday_text,
                    draw_date=draw_date,
                    draw_time=draw_time,
                    main_numbers=main_numbers,
                    special=special,
                    display_text=display_text,
                    game_label=game_label,
                    source_url=source_url,
                    source_date=source_date,
                    raw_row={str(key): str(value or "") for key, value in row.items()},
                )
            )

    records.sort(key=lambda item: (item.draw_id, item.draw_date))
    time_slot_usable = bool(records) and (non_blank_time_count / len(records)) >= 0.40
    return {
        "records": records,
        "csv_path": csv_path,
        "header_mapping": header_mapping,
        "time_slot_usable": time_slot_usable,
    }


def build_dataset_summary(bundle: dict[str, Any]) -> dict[str, Any]:
    records = list(bundle.get("records") or [])
    latest = records[-1] if records else None
    earliest = records[0] if records else None
    return {
        "csv_path": str(bundle.get("csv_path", "")),
        "record_count": len(records),
        "time_slot_usable": bool(bundle.get("time_slot_usable")),
        "latest_draw_id": latest.draw_id if latest else None,
        "latest_draw_date": format_csv_date(latest.draw_date if latest else None),
        "earliest_draw_id": earliest.draw_id if earliest else None,
        "earliest_draw_date": format_csv_date(earliest.draw_date if earliest else None),
        "label": latest.game_label if latest else "Power_6/55",
    }


def find_draw_by_id(records: list[DrawRecord], draw_id: int | str | None) -> DrawRecord | None:
    if draw_id in (None, ""):
        return None
    lookup = int(draw_id)
    for record in records:
        if record.draw_id == lookup:
            return record
    return None


def infer_next_draw(
    records: list[DrawRecord],
    schedule_weekdays: list[int] | tuple[int, ...],
    schedule_time: str | None = None,
) -> dict[str, Any]:
    if not records:
        raise ValueError("Cannot infer next draw from an empty history.")
    latest = records[-1]
    allowed = set(int(value) for value in schedule_weekdays)
    cursor = latest.draw_date + timedelta(days=1)
    while cursor.weekday() not in allowed:
        cursor += timedelta(days=1)
    return {
        "target_draw_id": latest.draw_id + 1,
        "target_date_estimate": format_csv_date(cursor),
        "target_weekday": cursor.weekday(),
        "target_time": schedule_time,
        "latest_draw_id": latest.draw_id,
        "latest_draw_date": format_csv_date(latest.draw_date),
    }


def draw_to_dict(record: DrawRecord) -> dict[str, Any]:
    return {
        "draw_id": record.draw_id,
        "weekday_text": record.weekday_text,
        "draw_date": format_csv_date(record.draw_date),
        "draw_time": record.draw_time,
        "main_numbers": list(record.main_numbers),
        "special": record.special,
        "display_text": record.display_text,
        "game_label": record.game_label,
        "source_url": record.source_url,
        "source_date": format_csv_date(record.source_date),
    }
