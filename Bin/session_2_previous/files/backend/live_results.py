import csv
import io
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import requests
from bs4 import BeautifulSoup
import ai.configs.data_paths as dp


# ----- Cau hinh crawl va dong bo -----
# Gom URL nguon, timeout, so ngay lookback va cac hang so cho Keno/full-history.
VIETLOTT_DAY_URL = "https://xsmn.net/kqxsvietlott/ngay-{date}"
KENO_URL = "https://www.minhchinh.com/xo-so-dien-toan-keno.html"
LOOKBACK_DAYS = 7
REQUEST_TIMEOUT = 30
REQUEST_RETRY_COUNT = 2
REQUEST_RETRY_SLEEP_SECONDS = 1.2
DEFAULT_HISTORY_DAYS = 100
HISTORY_REQUEST_DELAY_SECONDS = 0.08
SYNC_ALL_EMPTY_DAY_STOP = 30
SYNC_ALL_RECENT_LOOKBACK_DAYS = 30
CSV_AUTO_RECENT_LOOKBACK_DAYS = 15
FULL_HISTORY_REQUESTED_START_MODE = "full_history"
KENO_MAX_PAGES_PER_DAY = 20
KENO_FULL_DAY_DRAW_COUNT = 119
KENO_REQUEST_DELAY_SECONDS = 1.0
KENO_MANUAL_UPDATE_TIMEOUT_SECONDS = 30
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
SCRIPT_DIR = Path(__file__).resolve().parent
RUNTIME_LOG_DIR = dp.RUNTIME_LOG_DIR
LIVE_RESULTS_PROGRESS_FILE = RUNTIME_LOG_DIR / "live_results_progress.json"
LIVE_RESULTS_PROGRESS_LOCK_FILE = RUNTIME_LOG_DIR / "live_results_progress.lock"
AI_GEN_LOCAL_TRAIN_TYPES = ("LOTO_5_35", "LOTO_6_45", "LOTO_6_55", "KENO", "MAX_3D", "MAX_3D_PRO")
AI_GEN_LOCAL_TRAIN_TIMEOUT_SECONDS = 120
NUMBER_SCORING_EXPORT_TIMEOUT_SECONDS = 120
CSV_HEADER = ["Ky", "Ngay", "Time", "Main", "Special", "DisplayLines", "Label", "SourceUrl", "SourceDate"]
KENO_CSV_FIELDS = ["Ky", "Ngay", "Time", "Numbers", "L/-/N", "C/-/L"]
KENO_CSV_HEADER = ["Kỳ", "Ngày", "Thời Gian", "Numbers", "Lớn/-/Nhỏ", "Chẵn/-/Lẻ"]
KENO_CSV_HEADER_ALIASES = {
    "ky": "Ky",
    "ngay": "Ngay",
    "time": "Time",
    "thoi gian": "Time",
    "numbers": "Numbers",
    "l/-/n": "L/-/N",
    "lon/-/nho": "L/-/N",
    "c/-/l": "C/-/L",
    "chan/-/le": "C/-/L",
}
KENO_LN_VALUE_ALIASES = {
    "": "",
    "-": "-",
    "l": "Lớn",
    "lon": "Lớn",
    "n": "Nhỏ",
    "nho": "Nhỏ",
}
KENO_CL_VALUE_ALIASES = {
    "": "",
    "-": "-",
    "c": "Chẵn",
    "chan": "Chẵn",
    "l": "Lẻ",
    "le": "Lẻ",
}
THREE_DIGIT_TOKEN_RE = re.compile(r"(?<!\d)\d{3}(?!\d)")

try:
    csv.field_size_limit(10_000_000)
except (OverflowError, ValueError):
    csv.field_size_limit(1_000_000)


@dataclass(frozen=True)
class LiveType:
    key: str
    label: str
    kind: str
    marker: str = ""
    main_count: int = 0
    has_special: bool = False
    exclude: str = ""


LIVE_TYPES = {
    "LOTO_5_35": LiveType("LOTO_5_35", "Loto_5/35", "numeric", "lotto535", 5, True),
    "LOTO_6_45": LiveType("LOTO_6_45", "Mega_6/45", "numeric", "mega645", 6, False),
    "LOTO_6_55": LiveType("LOTO_6_55", "Power_6/55", "numeric", "power655", 6, True),
    "KENO": LiveType("KENO", "Keno", "keno"),
    "MAX_3D": LiveType("MAX_3D", "Max 3D", "max3d", "max3d", exclude="pro"),
    "MAX_3D_PRO": LiveType("MAX_3D_PRO", "Max 3D Pro", "max3dpro", "max3dpro"),
}

HISTORY_URL_PATTERNS = {
    "LOTO_5_35": "https://www.minhchinh.com/xs-lotto-535-ket-qua-lotto-535-ngay-{date}.html",
    "LOTO_6_45": "https://www.minhchinh.com/xs-mega-645-ket-qua-mega-645-ngay-{date}.html",
    "LOTO_6_55": "https://www.minhchinh.com/xs-power-655-ket-qua-power-655-ngay-{date}.html",
    "MAX_3D": "https://www.minhchinh.com/xs-max-3d-ket-qua-max-3d-ngay-{date}.html",
    "MAX_3D_PRO": "https://www.minhchinh.com/xs-max3d-pro-ket-qua-max3d-pro-ngay-{date}.html",
}

HISTORY_OUTPUT_STEMS = {
    "LOTO_5_35": "loto_5_35",
    "LOTO_6_45": "mega_6_45",
    "LOTO_6_55": "power_6_55",
    "MAX_3D": "max_3d",
    "MAX_3D_PRO": "max_3d_pro",
}

CANONICAL_OUTPUT_STEMS = {
    "KENO": "keno",
    "LOTO_5_35": "loto_5_35",
    "LOTO_6_45": "mega_6_45",
    "LOTO_6_55": "power_6_55",
    "MAX_3D": "max_3d",
    "MAX_3D_PRO": "max_3d_pro",
}

HISTORY_WEEKDAY_FILTERS = {
    "LOTO_6_45": {2, 4, 6},
    "LOTO_6_55": {1, 3, 5},
    "MAX_3D": {0, 2, 4},
    "MAX_3D_PRO": {1, 3, 5},
}

NUMERIC_EXPECTED_DAY_SLOTS = {
    "LOTO_5_35": ("13:00", "21:00"),
}


# ----- Ham co ban va ghi file an toan -----
# Cac ham runtime chung nhu thoi gian, doc/ghi JSON va ghi file theo kieu atomic de tranh corrupt.
def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def ensure_runtime_log_dir():
    RUNTIME_LOG_DIR.mkdir(parents=True, exist_ok=True)


def read_json_file(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def atomic_replace_text(path, text, encoding="utf-8", attempts=12, sleep_seconds=0.12):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(text, encoding=encoding, newline="")
        last_error = None
        for attempt in range(max(1, attempts)):
            try:
                os.replace(str(temp_path), str(path))
                return
            except OSError as exc:
                last_error = exc
                winerror = getattr(exc, "winerror", None)
                if winerror not in {5, 32} and attempt >= attempts - 1:
                    raise
                if attempt >= attempts - 1:
                    raise
                time.sleep(sleep_seconds * (attempt + 1))
        if last_error:
            raise last_error
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass


def write_json_file(path, payload):
    ensure_runtime_log_dir()
    atomic_replace_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_text_atomic(path, text, encoding="utf-8"):
    atomic_replace_text(path, text, encoding=encoding)


def pid_is_running(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


# ----- Theo doi tien do Cap Nhat -----
# Quan ly progress file, lock file va trang thai tung loai trong luc manual update dang chay.
def default_live_results_progress_payload():
    return {
        "ok": True,
        "running": False,
        "done": False,
        "runId": "",
        "startedAt": "",
        "updatedAt": "",
        "completedAt": "",
        "phase": "",
        "currentType": "",
        "completedSteps": 0,
        "totalSteps": 0,
        "percent": 0,
        "etaSeconds": None,
        "message": "",
        "warnings": [],
        "errors": [],
        "typeStates": {},
    }


def default_live_results_type_state(type_key):
    meta = LIVE_TYPES.get(type_key)
    return {
        "type": type_key,
        "label": meta.label if meta else type_key,
        "state": "pending",
        "resultCode": "pending",
        "resultLabel": "Chờ cập nhật",
        "resultMessage": "",
        "updatedAt": "",
        "latestKy": "",
        "latestDate": "",
        "latestTime": "",
        "canonicalCount": 0,
        "canonicalFile": "",
        "todayCount": 0,
        "allCount": 0,
        "liveResult": None,
        "error": "",
    }


def is_within_keno_operating_window(now_value=None):
    current = now_value or datetime.now()
    minutes = current.hour * 60 + current.minute
    return 6 * 60 <= minutes <= 22 * 60


def build_type_result_fields(type_key, had_errors=False, errors=None, now_value=None):
    error_text = "; ".join(
        f"{item.get('date', '')} {item.get('message', '')}".strip()
        for item in (errors or [])
        if str(item.get("message", "")).strip()
    )
    if not had_errors:
        return {
            "resultCode": "success",
            "resultLabel": "Hoàn Tất" if type_key == "KENO" else "Hoàn tất",
            "resultMessage": "",
        }
    if type_key == "KENO":
        if is_within_keno_operating_window(now_value):
            return {
                "resultCode": "failure",
                "resultLabel": "Thất Bại",
                "resultMessage": error_text,
            }
        return {
            "resultCode": "outside_hours",
            "resultLabel": "Thử Lại Trong Khung Giờ 6:00 - 22:00",
            "resultMessage": error_text,
        }
    return {
        "resultCode": "retry",
        "resultLabel": "Thử Lại",
        "resultMessage": error_text,
    }


def resolve_type_progress_outcome(type_key, result, now_value=None):
    had_errors = bool(result.get("errors"))
    error_items = list(result.get("errors") or [])
    if type_key == "KENO":
        status_had_errors = result.get("statusHadErrors")
        status_errors = result.get("statusErrors")
        if status_had_errors is not None:
            had_errors = bool(status_had_errors)
        if status_errors is not None:
            error_items = list(status_errors or [])
    return build_type_result_fields(type_key, had_errors=had_errors, errors=error_items, now_value=now_value)


def build_keno_manual_timeout_message(now_value=None):
    if is_within_keno_operating_window(now_value):
        return f"Keno cập nhật quá {KENO_MANUAL_UPDATE_TIMEOUT_SECONDS} giây."
    return "Hoạt động từ 6:00 đến 22:00"


class LiveResultsProgressTracker:
    def __init__(self, type_keys):
        requested = [str(value or "").strip().upper() for value in (type_keys or []) if str(value or "").strip()]
        self.type_keys = requested or list(LIVE_TYPES.keys())
        self.payload = default_live_results_progress_payload()
        self.payload.update({
            "runId": uuid.uuid4().hex[:12],
            "startedAt": now_iso(),
            "updatedAt": now_iso(),
            "phase": "prepare",
            "message": "Đang khởi tạo cập nhật 6 loại từ MinhChinh.",
            "typeStates": {type_key: default_live_results_type_state(type_key) for type_key in self.type_keys},
        })
        self.started_monotonic = time.perf_counter()
        self.lock_acquired = False
        self.last_write_warning = ""

    def _refresh_metrics(self):
        total_steps = max(0, int(self.payload.get("totalSteps") or 0))
        completed_steps = max(0, int(self.payload.get("completedSteps") or 0))
        completed_steps = min(completed_steps, total_steps) if total_steps > 0 else completed_steps
        self.payload["completedSteps"] = completed_steps
        self.payload["totalSteps"] = total_steps
        self.payload["updatedAt"] = now_iso()
        self.payload["percent"] = round((completed_steps / total_steps) * 100, 2) if total_steps > 0 else 0
        if self.payload.get("running") and total_steps > 0 and completed_steps > 0:
            elapsed_seconds = max(1, int(round(time.perf_counter() - self.started_monotonic)))
            remaining_steps = max(total_steps - completed_steps, 0)
            self.payload["etaSeconds"] = 0 if remaining_steps == 0 else max(
                1,
                int(round((elapsed_seconds / completed_steps) * remaining_steps)),
            )
        else:
            self.payload["etaSeconds"] = None

    def write(self):
        self._refresh_metrics()
        try:
            write_json_file(LIVE_RESULTS_PROGRESS_FILE, self.payload)
            self.last_write_warning = ""
        except OSError as exc:
            warning = f"Không thể ghi tiến độ tạm thời: {exc}"
            if warning != self.last_write_warning:
                warnings = self.payload.setdefault("warnings", [])
                if warning not in warnings:
                    warnings.append(warning)
                self.last_write_warning = warning

    def acquire_lock(self):
        ensure_runtime_log_dir()
        if LIVE_RESULTS_PROGRESS_LOCK_FILE.exists():
            existing = read_json_file(LIVE_RESULTS_PROGRESS_LOCK_FILE, {})
            existing_pid = existing.get("pid")
            if pid_is_running(existing_pid):
                raise RuntimeError("Đang có phiên cập nhật đang chạy")
            try:
                LIVE_RESULTS_PROGRESS_LOCK_FILE.unlink()
            except OSError:
                pass
        write_json_file(LIVE_RESULTS_PROGRESS_LOCK_FILE, {
            "pid": os.getpid(),
            "runId": self.payload["runId"],
            "startedAt": self.payload["startedAt"],
        })
        self.lock_acquired = True
        self.payload["running"] = True
        self.payload["done"] = False
        self.write()

    def release_lock(self):
        if not self.lock_acquired:
            return
        try:
            if LIVE_RESULTS_PROGRESS_LOCK_FILE.exists():
                LIVE_RESULTS_PROGRESS_LOCK_FILE.unlink()
        except OSError:
            pass
        self.lock_acquired = False

    def reserve_steps(self, count):
        count = max(0, int(count or 0))
        if not count:
            return
        self.payload["totalSteps"] = int(self.payload.get("totalSteps") or 0) + count
        self.write()

    def set_phase(self, phase, current_type="", message=""):
        self.payload["phase"] = str(phase or "").strip()
        self.payload["currentType"] = str(current_type or "").strip().upper()
        if message:
            self.payload["message"] = str(message)
        self.write()

    def ensure_type_state(self, type_key):
        key = str(type_key or "").strip().upper()
        if not key:
            return None
        type_states = self.payload.setdefault("typeStates", {})
        if key not in type_states:
            type_states[key] = default_live_results_type_state(key)
        return type_states[key]

    def update_type_state(self, type_key, **fields):
        bucket = self.ensure_type_state(type_key)
        if bucket is None:
            return
        bucket.update(fields)
        if "updatedAt" not in fields:
            bucket["updatedAt"] = now_iso()
        self.write()

    def mark_type_running(self, type_key, message=""):
        self.update_type_state(
            type_key,
            state="running",
            resultCode="running",
            resultLabel="Đang cập nhật",
            resultMessage=str(message or "").strip(),
            error="",
            updatedAt=now_iso(),
        )
        if message:
            self.set_phase("repair_recent", current_type=type_key, message=message)

    def complete_type(self, type_key, result, had_errors=False):
        live_result = None
        latest_results = load_latest_canonical_live_results([type_key])
        if latest_results:
            live_result = latest_results[0]
        result_fields = resolve_type_progress_outcome(type_key, result)
        self.update_type_state(
            type_key,
            state="error" if result_fields["resultCode"] in {"failure", "retry", "outside_hours"} else "done",
            resultCode=result_fields["resultCode"],
            resultLabel=result_fields["resultLabel"],
            resultMessage=result_fields["resultMessage"],
            latestKy=str(result.get("latestKy", "")).strip(),
            latestDate=str(result.get("latestDate", "")).strip(),
            latestTime=str(result.get("latestTime", "")).strip(),
            todayCount=max(0, int(result.get("todayCount") or 0)),
            allCount=max(0, int(result.get("allCount") or 0)),
            liveResult=live_result,
            error=result_fields["resultMessage"],
            updatedAt=now_iso(),
        )

    def complete_step(self, message="", current_type="", phase="", reserve_next_steps=0):
        if phase:
            self.payload["phase"] = str(phase).strip()
        if current_type:
            self.payload["currentType"] = str(current_type).strip().upper()
        if message:
            self.payload["message"] = str(message)
        self.payload["completedSteps"] = int(self.payload.get("completedSteps") or 0) + 1
        if reserve_next_steps:
            self.payload["totalSteps"] = int(self.payload.get("totalSteps") or 0) + max(0, int(reserve_next_steps))
        self.write()

    def add_warning(self, message):
        text = str(message or "").strip()
        if not text:
            return
        warnings = list(self.payload.get("warnings") or [])
        if text not in warnings:
            warnings.append(text)
        self.payload["warnings"] = warnings
        self.write()

    def add_error(self, message):
        text = str(message or "").strip()
        if not text:
            return
        errors = list(self.payload.get("errors") or [])
        if text not in errors:
            errors.append(text)
        self.payload["errors"] = errors
        self.write()

    def finish(self, message="Hoàn Tất Cập Nhật."):
        self.payload["running"] = False
        self.payload["done"] = True
        self.payload["phase"] = "complete"
        self.payload["message"] = str(message)
        self.payload["completedAt"] = now_iso()
        if self.payload.get("totalSteps"):
            self.payload["completedSteps"] = max(
                int(self.payload.get("completedSteps") or 0),
                int(self.payload.get("totalSteps") or 0),
            )
        self.write()
        self.release_lock()

    def fail(self, message):
        self.add_error(message)
        current_type = str(self.payload.get("currentType") or "").strip().upper()
        type_states = self.payload.get("typeStates") or {}
        for type_key, state in type_states.items():
            live_state = str((state or {}).get("state") or "").strip().lower()
            if live_state == "done":
                continue
            result_fields = build_type_result_fields(
                type_key,
                had_errors=True,
                errors=[{"type": type_key, "message": message}],
            )
            self.update_type_state(
                type_key,
                state="error",
                resultCode=result_fields["resultCode"],
                resultLabel=result_fields["resultLabel"],
                resultMessage=result_fields["resultMessage"],
                error=result_fields["resultMessage"],
                updatedAt=now_iso(),
            )
        self.payload["running"] = False
        self.payload["done"] = True
        self.payload["phase"] = "failed"
        self.payload["message"] = str(message)
        self.payload["completedAt"] = now_iso()
        self.write()
        self.release_lock()


def slug(text):
    normalized = unicodedata.normalize("NFD", str(text or "").lower())
    without_marks = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", without_marks)


def normalize_space(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def create_session():
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def request_with_retry(session, method, url, allow_404=False, **kwargs):
    last_error = None
    for attempt in range(REQUEST_RETRY_COUNT + 1):
        try:
            response = session.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
            if allow_404 and response.status_code == 404:
                return None
            if response.status_code == 429:
                if attempt >= REQUEST_RETRY_COUNT:
                    response.raise_for_status()
                time.sleep(REQUEST_RETRY_SLEEP_SECONDS * (attempt + 1))
                continue
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= REQUEST_RETRY_COUNT:
                raise
            time.sleep(REQUEST_RETRY_SLEEP_SECONDS * (attempt + 1))
    if last_error:
        raise last_error
    return None


def fetch_url_text(session, url):
    response = request_with_retry(session, "get", url, allow_404=True)
    if response is None:
        return None
    return response.text


def parse_csv_date(value):
    text = str(value or "").strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def format_csv_date(target_date):
    return target_date.strftime("%d/%m/%Y")


def format_minhchinh_date(target_date):
    return target_date.strftime("%d-%m-%Y")


def get_canonical_output_paths(type_key):
    all_path = dp.get_canonical_csv_write_path(type_key)
    return {
        "today": all_path,
        "all": all_path,
    }


def get_canonical_meta_path(type_key):
    return dp.get_canonical_meta_write_path(type_key)


def read_canonical_meta(type_key):
    path = dp.get_canonical_meta_read_path(type_key)
    default = {
        "type": type_key,
        "bootstrapComplete": False,
        "requestedStartMode": FULL_HISTORY_REQUESTED_START_MODE,
        "lastSyncAt": "",
        "lastBootstrapAt": "",
        "effectiveEarliestKy": "",
        "effectiveEarliestDate": "",
        "sourceLimited": False,
    }
    if not path.exists():
        return dict(default)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(default)
    merged = dict(default)
    if isinstance(payload, dict):
        merged.update(payload)
    merged["type"] = type_key
    if not merged.get("requestedStartMode"):
        merged["requestedStartMode"] = FULL_HISTORY_REQUESTED_START_MODE
    return merged


def write_canonical_meta(type_key, meta):
    payload = dict(meta or {})
    payload["type"] = type_key
    if not payload.get("requestedStartMode"):
        payload["requestedStartMode"] = FULL_HISTORY_REQUESTED_START_MODE
    write_text_atomic(
        get_canonical_meta_path(type_key),
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def retrain_gen_local_models(progress=None, skip_types=None):
    skip_type_keys = {
        str(value or "").strip().upper()
        for value in (skip_types or [])
        if str(value or "").strip()
    }
    script_path = dp.PROJECT_ROOT / "ai" / "predictors" / "ai_predict.py"
    summary = {
        "ok": True,
        "engine": "gen_local",
        "results": [],
        "errors": [],
        "skipped": [],
        "trainedAt": now_iso(),
    }
    if not script_path.exists():
        summary["ok"] = False
        summary["errors"].append({"type": "", "message": "Không tìm thấy ai_predict.py để train AI Gen Local."})
        return summary

    if progress:
        progress.reserve_steps(len(AI_GEN_LOCAL_TRAIN_TYPES))

    for type_key in AI_GEN_LOCAL_TRAIN_TYPES:
        label = LIVE_TYPES.get(type_key).label if LIVE_TYPES.get(type_key) else type_key
        if type_key in skip_type_keys:
            summary["skipped"].append({
                "type": type_key,
                "label": label,
                "message": "Bỏ qua train AI Gen Local vì lần cập nhật vừa rồi của loại này chưa hoàn tất.",
            })
            if progress:
                progress.complete_step(
                    message=f"{label}: bỏ qua train AI Gen Local.",
                    current_type=type_key,
                    phase="train_ai",
                )
            continue
        if progress:
            progress.set_phase(
                "train_ai",
                current_type=type_key,
                message=f"{label}: đang huấn luyện AI Gen Local.",
            )
        command = [
            sys.executable,
            str(script_path),
            "train_json",
            type_key,
            "--engine=gen_local",
        ]
        result_payload = None
        error_message = ""
        try:
            completed = subprocess.run(
                command,
                cwd=str(dp.PROJECT_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=AI_GEN_LOCAL_TRAIN_TIMEOUT_SECONDS,
                check=False,
            )
            stdout_text = str(completed.stdout or "").strip()
            stderr_text = str(completed.stderr or "").strip()
            if completed.returncode != 0:
                error_message = stderr_text or stdout_text or "Tiến trình train AI Gen Local kết thúc với mã lỗi."
            else:
                try:
                    result_payload = json.loads(stdout_text or "{}")
                except json.JSONDecodeError:
                    error_message = stdout_text or "Train AI Gen Local trả dữ liệu JSON không hợp lệ."
        except subprocess.TimeoutExpired:
            error_message = f"Train AI Gen Local quá {AI_GEN_LOCAL_TRAIN_TIMEOUT_SECONDS} giây."
        except Exception as exc:
            error_message = str(exc)

        if result_payload and result_payload.get("ok"):
            summary["results"].append(result_payload)
            step_message = f"{label}: đã cập nhật mô hình AI Gen Local."
        else:
            failure = {
                "type": type_key,
                "message": error_message or str((result_payload or {}).get("message") or "Train AI Gen Local thất bại."),
            }
            summary["ok"] = False
            summary["errors"].append(failure)
            step_message = f"{label}: train AI Gen Local lỗi, đang giữ model cũ."
            if progress:
                progress.add_warning(f"{label}: {failure['message']}")

        if progress:
            progress.complete_step(
                message=step_message,
                current_type=type_key,
                phase="train_ai",
            )

    return summary


def refresh_scoring_csv_exports(type_keys=None, progress=None):
    requested = []
    seen = set()
    for raw in (type_keys or AI_GEN_LOCAL_TRAIN_TYPES):
        key = str(raw or "").strip().upper()
        if key in LIVE_TYPES and key not in seen:
            seen.add(key)
            requested.append(key)
    if not requested:
        requested = list(AI_GEN_LOCAL_TRAIN_TYPES)

    script_path = dp.PROJECT_ROOT / "ai" / "predictors" / "ai_predict.py"
    summary = {
        "ok": True,
        "mode": "score_csv_refresh",
        "results": [],
        "errors": [],
        "updatedAt": now_iso(),
    }
    if not script_path.exists():
        summary["ok"] = False
        summary["errors"].append({"type": "", "message": "Không tìm thấy ai_predict.py để xuất CSV scoring."})
        return summary

    if progress:
        progress.set_phase(
            "export_scoring",
            current_type="",
            message="Đang cập nhật file CSV Top 10 cho các loại vé.",
        )

    for type_key in requested:
        command = [
            sys.executable,
            str(script_path),
            "score_csv",
            type_key,
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=str(dp.PROJECT_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=NUMBER_SCORING_EXPORT_TIMEOUT_SECONDS,
                check=False,
            )
            stdout_text = str(completed.stdout or "").strip()
            stderr_text = str(completed.stderr or "").strip()
            if completed.returncode != 0:
                raise RuntimeError(stderr_text or stdout_text or "Tiến trình score_csv kết thúc với mã lỗi.")
            payload = json.loads(stdout_text or "{}")
            if not payload.get("ok"):
                raise RuntimeError(str(payload.get("message") or "Xuất CSV scoring thất bại."))
            summary["results"].append(payload)
        except Exception as exc:
            summary["ok"] = False
            summary["errors"].append({
                "type": type_key,
                "label": LIVE_TYPES.get(type_key).label if LIVE_TYPES.get(type_key) else type_key,
                "message": str(exc),
            })
            if progress:
                progress.add_warning(f"{LIVE_TYPES.get(type_key).label if LIVE_TYPES.get(type_key) else type_key}: xuất CSV scoring lỗi - {exc}")
    return summary


def sort_key_from_ky(ky_value):
    digits = re.sub(r"\D", "", str(ky_value or ""))
    if digits:
        return int(digits)
    return -1


def get_latest_and_earliest_rows(rows_by_ky):
    sorted_rows = sorted(
        rows_by_ky.values(),
        key=lambda item: sort_key_from_ky(item.get("Ky", "")),
        reverse=True,
    )
    latest_row = sorted_rows[0] if sorted_rows else {}
    earliest_row = sorted_rows[-1] if sorted_rows else {}
    return latest_row, earliest_row


def read_csv_text_safely(csv_path):
    info = {"sanitized": False, "issues": []}
    if not csv_path.exists():
        return "", info

    try:
        raw = csv_path.read_bytes()
    except OSError as exc:
        info["sanitized"] = True
        info["issues"].append(f"read_failed:{exc}")
        return "", info

    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
        info["sanitized"] = True
        info["issues"].append("bom_removed")
    if b"\x00" in raw:
        raw = raw.replace(b"\x00", b"")
        info["sanitized"] = True
        info["issues"].append("nul_removed")

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        info["sanitized"] = True
        info["issues"].append("decode_replaced")
    return text, info


def normalize_csv_row_dict(header_map, row, fieldnames):
    normalized = {}
    for field in fieldnames:
        index = header_map.get(field.lower())
        normalized[field] = str(row[index] or "").strip() if index is not None and index < len(row) else ""
    return normalized


def normalize_header_label(value):
    text = str(value or "").strip().lower().replace("đ", "d")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text)


def resolve_keno_csv_header_map(header):
    resolved = {}
    for index, name in enumerate(header):
        canonical = KENO_CSV_HEADER_ALIASES.get(normalize_header_label(name))
        if canonical and canonical not in resolved:
            resolved[canonical] = index
    return resolved


def normalize_keno_ln_value(value):
    text = str(value or "").strip()
    return KENO_LN_VALUE_ALIASES.get(normalize_header_label(text), text)


def normalize_keno_cl_value(value):
    text = str(value or "").strip()
    return KENO_CL_VALUE_ALIASES.get(normalize_header_label(text), text)


def serialize_keno_csv_value(field, value):
    if field == "L/-/N":
        return normalize_keno_ln_value(value)
    if field == "C/-/L":
        return normalize_keno_cl_value(value)
    return str(value or "").strip()


def normalize_meta_from_rows(type_key, meta, rows_by_ky):
    cleaned = dict(meta or {})
    cleaned["type"] = type_key
    if not cleaned.get("requestedStartMode"):
        cleaned["requestedStartMode"] = FULL_HISTORY_REQUESTED_START_MODE

    _, earliest_row = get_latest_and_earliest_rows(rows_by_ky)
    expected_earliest_ky = str(earliest_row.get("Ky", "")).strip()
    expected_earliest_date = str(earliest_row.get("Ngay", "")).strip()

    current_earliest_ky = re.sub(r"\D", "", str(cleaned.get("effectiveEarliestKy", "")).strip())
    current_earliest_date = str(cleaned.get("effectiveEarliestDate", "")).strip()
    if parse_csv_date(current_earliest_date) is None:
        current_earliest_date = ""

    cleaned["effectiveEarliestKy"] = expected_earliest_ky
    cleaned["effectiveEarliestDate"] = expected_earliest_date
    if type_key == "KENO":
        cleaned["sourceLimited"] = bool(expected_earliest_ky and sort_key_from_ky(expected_earliest_ky) > 1)

    inferred_bootstrap_complete = bool(cleaned.get("bootstrapComplete"))
    if (
        type_key != "KENO"
        and not inferred_bootstrap_complete
        and expected_earliest_ky
        and sort_key_from_ky(expected_earliest_ky) == 1
    ):
        gap_count, _ = count_gap_intervals_for_type(type_key, rows_by_ky)
        if gap_count == 0:
            inferred_bootstrap_complete = True
            if not str(cleaned.get("lastBootstrapAt", "")).strip():
                cleaned["lastBootstrapAt"] = datetime.now().isoformat(timespec="seconds")
    cleaned["bootstrapComplete"] = inferred_bootstrap_complete

    changed = (
        current_earliest_ky != expected_earliest_ky
        or current_earliest_date != expected_earliest_date
        or bool(cleaned.get("bootstrapComplete")) != bool(meta.get("bootstrapComplete"))
        or str(cleaned.get("lastBootstrapAt", "")).strip() != str(meta.get("lastBootstrapAt", "")).strip()
        or str(cleaned.get("type", "")).strip().upper() != type_key
    )
    return cleaned, changed


# ----- Lam sach va nap canonical CSV -----
# Doc file canonical theo huong an toan, salvage dong hop le va tu sua meta neu can.
def load_csv_rows(csv_path, return_info=False):
    rows_by_ky = {}
    info = {"sanitized": False, "issues": []}
    if not csv_path.exists():
        return (rows_by_ky, info) if return_info else rows_by_ky

    text, read_info = read_csv_text_safely(csv_path)
    info["sanitized"] = bool(read_info.get("sanitized"))
    info["issues"].extend(read_info.get("issues") or [])
    if not text:
        return (rows_by_ky, info) if return_info else rows_by_ky

    reader = csv.reader(io.StringIO(text), skipinitialspace=True)
    header = next(reader, None)
    if not header:
        return (rows_by_ky, info) if return_info else rows_by_ky

    header_map = {str(name or "").strip().lower(): index for index, name in enumerate(header)}
    if "ky" not in header_map or "ngay" not in header_map:
        info["sanitized"] = True
        info["issues"].append("missing_required_header")
        return (rows_by_ky, info) if return_info else rows_by_ky

    for row in reader:
        if not any(str(cell or "").strip() for cell in row):
            continue
        if len(row) > len(header):
            info["sanitized"] = True
            if "extra_fields" not in info["issues"]:
                info["issues"].append("extra_fields")
        normalized = normalize_csv_row_dict(header_map, row, CSV_HEADER)
        ky = re.sub(r"\D", "", str(normalized.get("Ky", "")).strip())
        row_date = parse_csv_date(normalized.get("Ngay"))
        if not ky or row_date is None:
            info["sanitized"] = True
            if "invalid_row_skipped" not in info["issues"]:
                info["issues"].append("invalid_row_skipped")
            continue
        if not any(str(normalized.get(field, "")).strip() for field in ("Main", "Special", "DisplayLines")):
            info["sanitized"] = True
            if "empty_result_row_skipped" not in info["issues"]:
                info["issues"].append("empty_result_row_skipped")
            continue
        normalized["Ky"] = ky
        normalized["Ngay"] = format_csv_date(row_date)
        rows_by_ky[ky] = normalized
    return (rows_by_ky, info) if return_info else rows_by_ky


def load_canonical_rows(type_key, rewrite_if_needed=True):
    read_path = dp.get_canonical_csv_read_path(type_key)
    write_path = get_canonical_output_paths(type_key)["all"]
    loader = load_keno_csv_rows if type_key == "KENO" else load_csv_rows
    writer = write_keno_csv_rows if type_key == "KENO" else write_csv_rows
    rows_by_ky, info = loader(read_path, return_info=True)

    removed_rows = 0
    if type_key != "KENO":
        filtered_rows, removed_rows = filter_rows_for_type(type_key, rows_by_ky)
        if removed_rows:
            rows_by_ky = filtered_rows
            info["sanitized"] = True
            info["issues"].append(f"type_filter_removed:{removed_rows}")

    meta = read_canonical_meta(type_key)
    normalized_meta, meta_changed = normalize_meta_from_rows(type_key, meta, rows_by_ky)

    if rewrite_if_needed and info.get("sanitized"):
        writer(write_path, rows_by_ky)
    if rewrite_if_needed and (info.get("sanitized") or meta_changed):
        write_canonical_meta(type_key, normalized_meta)

    return rows_by_ky, normalized_meta, info


def count_rows_for_date(rows_by_ky, target_date):
    if hasattr(target_date, "strftime"):
        target_text = format_csv_date(target_date)
    else:
        target_text = str(target_date or "").strip()
    if not target_text:
        return 0
    return sum(
        1
        for row in rows_by_ky.values()
        if str(row.get("Ngay", "")).strip() == target_text
    )


def result_to_csv_row(result):
    main = ",".join(str(int(value)) for value in (result.get("main") or []) if str(value).strip())
    special = ""
    if result.get("special") is not None and str(result.get("special")).strip():
        special = str(result.get("special"))
    display_lines = " || ".join(str(item).strip() for item in (result.get("displayLines") or []) if str(item).strip())
    return {
        "Ky": str(result.get("ky", "")).strip(),
        "Ngay": str(result.get("date", "")).strip(),
        "Time": str(result.get("time", "")).strip(),
        "Main": main,
        "Special": special,
        "DisplayLines": display_lines,
        "Label": str(result.get("label", "")).strip(),
        "SourceUrl": str(result.get("sourceUrl", "")).strip(),
        "SourceDate": str(result.get("sourceDate", "")).strip(),
    }


def write_csv_rows(csv_path, rows_by_ky):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    sorted_rows = sorted(
        rows_by_ky.values(),
        key=lambda item: sort_key_from_ky(item.get("Ky", "")),
        reverse=True,
    )
    temp_path = csv_path.with_name(f"{csv_path.name}.tmp")
    with temp_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writeheader()
        writer.writerows(sorted_rows)
    os.replace(str(temp_path), str(csv_path))


def filter_rows_from_start_date(rows_by_ky, start_date):
    filtered_rows = {}
    removed_rows = 0
    for ky, row in rows_by_ky.items():
        row_date = parse_csv_date(row.get("Ngay"))
        if row_date is None or row_date < start_date:
            removed_rows += 1
            continue
        filtered_rows[ky] = row
    return filtered_rows, removed_rows


def row_matches_type_key(type_key, row):
    if type_key == "KENO":
        return True

    label = normalize_space(row.get("Label", "")).lower()
    source_url = normalize_space(row.get("SourceUrl", "")).lower()

    if type_key == "LOTO_5_35":
        if "5/35" in label or "lotto-535" in source_url:
            return True
    elif type_key == "LOTO_6_45":
        if "6/45" in label or "mega-645" in source_url:
            return True
    elif type_key == "LOTO_6_55":
        if "6/55" in label or "power-655" in source_url:
            return True
    elif type_key == "MAX_3D":
        if "3d pro" in label or "max3d-pro" in source_url:
            return False
        if "max 3d" in label or "max-3d" in source_url:
            return True
    elif type_key == "MAX_3D_PRO":
        if "3d pro" in label or "max3d-pro" in source_url:
            return True
        if "max 3d" in label and "pro" not in label:
            return False

    return not label and not source_url


def filter_rows_for_type(type_key, rows_by_ky):
    filtered_rows = {}
    removed_rows = 0
    for ky, row in rows_by_ky.items():
        if not row_matches_type_key(type_key, row):
            removed_rows += 1
            continue
        filtered_rows[ky] = row
    return filtered_rows, removed_rows


def sync_result_to_canonical_csv(result):
    type_key = str(result.get("key", "")).strip().upper()
    if type_key not in CANONICAL_OUTPUT_STEMS:
        return None

    today = datetime.now().date()
    canonical_paths = get_canonical_output_paths(type_key)
    rows_by_ky, canonical_meta, _ = load_canonical_rows(type_key)
    if type_key == "KENO":
        row = keno_result_to_csv_row(result)
    else:
        row = result_to_csv_row(result)

    ky = row["Ky"]
    previous = rows_by_ky.get(ky)
    rows_by_ky[ky] = row
    canonical_paths, today_count, all_count = write_canonical_rows(type_key, rows_by_ky, today)
    latest_row, earliest_row = get_latest_and_earliest_rows(rows_by_ky)
    earliest_ky = str(earliest_row.get("Ky", "")).strip()
    earliest_date = str(earliest_row.get("Ngay", "")).strip()
    canonical_meta["lastSyncAt"] = datetime.now().isoformat(timespec="seconds")
    canonical_meta["effectiveEarliestKy"] = earliest_ky
    canonical_meta["effectiveEarliestDate"] = earliest_date
    if type_key == "KENO":
        canonical_meta["sourceLimited"] = sort_key_from_ky(earliest_ky) > 1
    write_canonical_meta(type_key, canonical_meta)

    return {
        "type": type_key,
        "key": type_key,
        "canonicalFile": canonical_paths["all"].name,
        "canonicalCount": all_count,
        "allFile": canonical_paths["all"].name,
        "todayFile": canonical_paths["today"].name,
        "new_rows": 1 if previous is None else 0,
        "updated_rows": 1 if previous is not None and previous != row else 0,
        "todayCount": today_count,
        "allCount": all_count,
        "total_rows": all_count,
        "latestKy": str(latest_row.get("Ky", "")).strip(),
        "latestDate": str(latest_row.get("Ngay", "")).strip(),
        "latestTime": str(latest_row.get("Time", "")).strip(),
        "effectiveEarliestKy": earliest_ky,
        "effectiveEarliestDate": earliest_date,
        "bootstrapComplete": bool(canonical_meta.get("bootstrapComplete")),
        "sourceLimited": bool(canonical_meta.get("sourceLimited", False)),
        "requestedStartMode": str(canonical_meta.get("requestedStartMode", FULL_HISTORY_REQUESTED_START_MODE)),
    }


# ----- Payload lich su va ket qua live -----
# Chuyen row CSV thanh payload de web hien thi o bang live va lich su CSV.
def csv_row_to_history_item(row):
    main = [
        int(token) for token in str(row.get("Main", "")).split(",")
        if str(token).strip().isdigit()
    ]
    special_raw = str(row.get("Special", "")).strip()
    display_lines = [
        part.strip() for part in str(row.get("DisplayLines", "")).split("||")
        if part.strip()
    ]
    label = str(row.get("Label", "")).strip()
    label_upper = label.upper()
    source_url = str(row.get("SourceUrl", "")).strip()
    if not main and display_lines and (
        label_upper in {"MAX_3D", "MAX_3D_PRO", "MAX 3D", "MAX 3D PRO"}
        or "max3d" in source_url.lower()
        or "max-3d" in source_url.lower()
    ):
        main = extract_three_digit_numbers_from_display_lines(display_lines)
    return {
        "ky": str(row.get("Ky", "")).strip(),
        "date": str(row.get("Ngay", "")).strip(),
        "time": str(row.get("Time", "")).strip(),
        "main": main,
        "special": int(special_raw) if special_raw.isdigit() else None,
        "displayLines": display_lines,
        "label": label,
        "sourceUrl": source_url,
        "sourceDate": str(row.get("SourceDate", "")).strip(),
    }


def extract_three_digit_numbers_from_display_lines(display_lines):
    values = []
    seen = set()
    for line in display_lines or []:
        for token in THREE_DIGIT_TOKEN_RE.findall(str(line or "")):
            number = int(token)
            if number in seen:
                continue
            seen.add(number)
            values.append(number)
    return sorted(values)


KENO_HISTORY_RANGE_LABELS = {
    "today": "Hôm Nay",
    "3d": "3 Ngày",
    "1w": "1 Tuần",
    "1m": "1 Tháng",
    "3m": "3 Tháng",
    "6m": "6 Tháng",
    "1y": "1 Năm",
    "all": "Tất cả Kỳ",
}
KENO_HISTORY_REFRESH_KEYS = {"today", "3d", "1w", "1m", "3m", "6m", "1y"}
KENO_HISTORY_DAY_START_MINUTES = 6 * 60
KENO_HISTORY_DAY_END_MINUTES = 22 * 60


def normalize_live_history_count_key(type_key, value):
    raw = str(value or "").strip().lower()
    if type_key == "KENO":
        if not raw:
            return "today"
        if raw in KENO_HISTORY_RANGE_LABELS:
            return raw
        if raw.isdigit():
            return str(max(1, int(raw)))
        return "today"
    if not raw:
        return str(DEFAULT_HISTORY_DAYS)
    if raw == "all":
        return "all"
    if raw.isdigit():
        return str(max(1, int(raw)))
    return str(DEFAULT_HISTORY_DAYS)


def normalize_history_count(value):
    normalized = normalize_live_history_count_key("LOTO_5_35", value)
    if normalized == "all":
        return None
    if normalized.isdigit():
        return max(1, int(normalized))
    return max(1, DEFAULT_HISTORY_DAYS)


def parse_time_to_minutes(value):
    match = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(value or ""))
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        return None
    return hours * 60 + minutes


def first_day_of_shifted_month(target_date, months_back):
    year = target_date.year
    month = target_date.month - months_back
    while month <= 0:
        month += 12
        year -= 1
    return datetime(year, month, 1).date()


def keno_history_window_start_date(today, count_key):
    if count_key == "today":
        return today
    if count_key == "3d":
        return today - timedelta(days=2)
    if count_key == "1w":
        return today - timedelta(days=6)
    if count_key == "1m":
        return today.replace(day=1)
    if count_key == "3m":
        return first_day_of_shifted_month(today, 2)
    if count_key == "6m":
        return first_day_of_shifted_month(today, 5)
    if count_key == "1y":
        return datetime(today.year, 1, 1).date()
    return None


def load_history_items_for_type(type_key, count=None):
    if type_key == "KENO":
        return load_keno_history_items(count)

    limit = normalize_history_count(count)
    rows_by_ky, _, _ = load_canonical_rows(type_key)
    sorted_rows = sorted(
        rows_by_ky.values(),
        key=lambda item: sort_key_from_ky(item.get("Ky", "")),
        reverse=True,
    )
    items = [csv_row_to_history_item(row) for row in sorted_rows]
    return items if limit is None else items[:limit]


def history_item_to_live_result(type_key, item):
    if not item:
        return None
    display_lines = [
        str(line).strip()
        for line in (item.get("displayLines") or [])
        if str(line).strip()
    ]
    if type_key == "KENO" and not display_lines:
        display_lines = [" ".join(f"{int(value):02d}" for value in (item.get("main") or []) if str(value).strip())]
    return {
        "key": type_key,
        "label": LIVE_TYPES[type_key].label,
        "ky": str(item.get("ky", "")).strip(),
        "date": str(item.get("date", "")).strip(),
        "time": str(item.get("time", "")).strip(),
        "main": [int(value) for value in (item.get("main") or []) if str(value).strip()],
        "special": item.get("special"),
        "displayLines": display_lines,
        "importable": True,
        "sourceUrl": str(item.get("sourceUrl", "")).strip(),
        "sourceDate": str(item.get("sourceDate", "")).strip(),
    }


def load_latest_canonical_live_results(type_keys=None):
    results = []
    keys = [key for key in (type_keys or list(LIVE_TYPES.keys())) if key in LIVE_TYPES]
    for type_key in keys:
        items = load_history_items_for_type(type_key, 1)
        if not items:
            continue
        result = history_item_to_live_result(type_key, items[0])
        if result:
            results.append(result)
    return results


def load_history_payload(type_keys=None, count=None):
    payload = {}
    keys = [key for key in (type_keys or list(LIVE_TYPES.keys())) if key in LIVE_TYPES]
    for type_key in keys:
        payload[type_key] = load_history_items_for_type(type_key, count)
    return payload


def repair_canonical_history_type(type_key, recent_lookback_days=None):
    session = create_session()
    cache = {}
    try:
        if type_key == "KENO":
            return sync_all_keno_type(
                session,
                allow_bootstrap=False,
                recent_lookback_days=recent_lookback_days,
            )
        return sync_all_numeric_type(
            session,
            cache,
            type_key,
            allow_bootstrap=False,
            recent_lookback_days=recent_lookback_days,
        )
    finally:
        try:
            session.close()
        except Exception:
            pass


def build_canonical_history_payload(type_key, count=None, repair=False, recent_lookback_days=None):
    count_raw = normalize_live_history_count_key(type_key, count)
    history_note = ""
    range_label = ""
    now_value = datetime.now()
    repair_attempted = bool(repair)
    repair_result = None
    repair_errors = []
    if repair_attempted:
        try:
            repair_result = repair_canonical_history_type(type_key, recent_lookback_days=recent_lookback_days)
        except Exception as exc:
            repair_errors.append(str(exc))
    if type_key == "KENO":
        refresh_result = refresh_keno_history_for_requested_range(count_raw, now_value=now_value)
        history_items, history_meta = load_keno_history_items(count_raw, now_value=now_value, return_meta=True)
        range_label = str(history_meta.get("rangeLabel", "")).strip()
        history_notes = []
        if repair_errors:
            history_notes.extend([f"Không repair được canonical Keno: {message}" for message in repair_errors if str(message).strip()])
        if str(refresh_result.get("historyNote", "")).strip():
            history_notes.append(str(refresh_result.get("historyNote", "")).strip())
        if str(history_meta.get("historyNote", "")).strip():
            history_notes.append(str(history_meta.get("historyNote", "")).strip())
        history_note = "\n".join(dict.fromkeys(history_notes))
    else:
        history_items = load_history_items_for_type(type_key, count_raw)
        if repair_errors:
            history_note = "\n".join(dict.fromkeys([f"Không repair được canonical {LIVE_TYPES[type_key].label}: {message}" for message in repair_errors if str(message).strip()]))
    canonical_paths = get_canonical_output_paths(type_key)
    all_rows_by_ky, canonical_meta, _ = load_canonical_rows(type_key)
    today_count = count_rows_for_date(all_rows_by_ky, datetime.now().date())
    sorted_rows = sorted(
        all_rows_by_ky.values(),
        key=lambda item: sort_key_from_ky(item.get("Ky", "")),
        reverse=True,
    )
    latest_row = sorted_rows[0] if sorted_rows else {}
    return {
        "ok": True,
        "mode": "canonical_history",
        "type": type_key,
        "label": LIVE_TYPES[type_key].label,
        "count": count_raw,
        "returnedCount": len(history_items),
        "canonicalCount": len(all_rows_by_ky),
        "canonicalFile": canonical_paths["all"].name,
        "allCount": len(all_rows_by_ky),
        "todayCount": today_count,
        "allFile": canonical_paths["all"].name,
        "todayFile": canonical_paths["all"].name,
        "latestKy": str(latest_row.get("Ky", "")).strip(),
        "latestDate": str(latest_row.get("Ngay", "")).strip(),
        "latestTime": str(latest_row.get("Time", "")).strip(),
        "effectiveEarliestKy": str(canonical_meta.get("effectiveEarliestKy", "")).strip(),
        "effectiveEarliestDate": str(canonical_meta.get("effectiveEarliestDate", "")).strip(),
        "rangeLabel": range_label,
        "historyNote": history_note,
        "repairAttempted": repair_attempted,
        "repairNewRows": int((repair_result or {}).get("newRows", 0) or 0),
        "repairRepairedDates": int((repair_result or {}).get("repairedDates", 0) or 0),
        "repairRepairedKyGaps": int((repair_result or {}).get("repairedKyGaps", 0) or 0),
        "repairErrors": repair_errors or list((repair_result or {}).get("errors", []) or []),
        "fetchedAt": datetime.now().isoformat(timespec="seconds"),
        "history": history_items,
    }


def calc_keno_ln(numbers):
    big = sum(1 for value in numbers if value > 40)
    small = len(numbers) - big
    if big > small:
        return "Lớn"
    if small > big:
        return "Nhỏ"
    return "-"


def calc_keno_cl(numbers):
    even = sum(1 for value in numbers if value % 2 == 0)
    odd = len(numbers) - even
    if even > odd:
        return "Chẵn"
    if odd > even:
        return "Lẻ"
    return "-"


def get_keno_search_date(soup):
    date_input = soup.select_one("#frmSearch input[name='date']")
    if not date_input or not date_input.get("value"):
        raise RuntimeError("Không tìm thấy ngày tìm kiếm trên trang Keno.")
    return date_input["value"]


def parse_keno_rows(soup):
    results = []
    rows = soup.select("#containerKQKeno .wrapperKQKeno")
    for row in rows:
        ky_node = row.select_one(".kyKQKeno")
        time_parts = row.select(".timeKQ > div")
        numbers = [int(node.get_text(strip=True)) for node in row.select(".boxKQKeno > div")]

        if not ky_node or len(time_parts) < 2 or len(numbers) != 20:
            continue

        ky = re.sub(r"\D", "", ky_node.get_text(" ", strip=True))
        date_value = time_parts[0].get_text(strip=True)
        time_value = time_parts[1].get_text(strip=True)
        results.append({
            "key": "KENO",
            "label": "Keno",
            "ky": ky,
            "date": date_value,
            "time": time_value,
            "main": numbers,
            "special": None,
            "displayLines": [" ".join(f"{value:02d}" for value in numbers)],
            "importable": True,
            "sourceUrl": KENO_URL,
            "sourceDate": date_value,
        })
    return results


def fetch_latest_keno_page(session):
    response = request_with_retry(session, "get", KENO_URL)
    soup = BeautifulSoup(response.text, "html.parser")
    return get_keno_search_date(soup), parse_keno_rows(soup)


# ----- Parse Keno va MinhChinh -----
# Tach logic crawl/phat hien page Keno va parse ket qua tu cac trang MinhChinh/Vietlott.
def fetch_keno_day_results(session, target_date, page_progress=None, deadline_monotonic=None, timeout_state=None):
    day_results = []
    seen_ky = set()
    target_date_text = format_minhchinh_date(target_date)

    def mark_timeout():
        if timeout_state is not None:
            timeout_state["timedOut"] = True

    for page in range(1, KENO_MAX_PAGES_PER_DAY + 1):
        if deadline_monotonic is not None and time.perf_counter() >= deadline_monotonic:
            mark_timeout()
            if page_progress:
                page_progress(page=page, new_count=0, has_results=False, will_continue=False, new_results=[], collected_count=len(day_results))
            break
        response = request_with_retry(
            session,
            "post",
            KENO_URL,
            data={
                "date": target_date_text,
                "ky": "0",
                "number": "",
                "page": str(page),
            },
            allow_404=True,
        )
        if response is None:
            if page_progress:
                page_progress(page=page, new_count=0, has_results=False, will_continue=False, new_results=[], collected_count=len(day_results))
            break

        soup = BeautifulSoup(response.text, "html.parser")
        page_results = parse_keno_rows(soup)
        if not page_results:
            if page_progress:
                page_progress(page=page, new_count=0, has_results=False, will_continue=False, new_results=[], collected_count=len(day_results))
            break

        new_count = 0
        new_page_results = []
        for result in page_results:
            ky = result["ky"]
            if ky in seen_ky:
                continue
            seen_ky.add(ky)
            result["sourceDate"] = format_csv_date(target_date)
            day_results.append(result)
            new_page_results.append(result)
            new_count += 1

        will_continue = new_count > 0 and page < KENO_MAX_PAGES_PER_DAY
        if page_progress:
            page_progress(
                page=page,
                new_count=new_count,
                has_results=True,
                will_continue=will_continue,
                new_results=new_page_results,
                collected_count=len(day_results),
            )
        if deadline_monotonic is not None and time.perf_counter() >= deadline_monotonic:
            mark_timeout()
            break
        time.sleep(KENO_REQUEST_DELAY_SECONDS)
        if new_count == 0:
            break

    return day_results


def build_keno_history_items(rows_by_ky):
    sorted_rows = sorted(
        rows_by_ky.values(),
        key=lambda item: sort_key_from_ky(item.get("Ky", "")),
        reverse=True,
    )
    return [{
        "ky": str(row.get("Ky", "")).strip(),
        "date": str(row.get("Ngay", "")).strip(),
        "time": str(row.get("Time", "")).strip(),
        "main": [
            int(token) for token in str(row.get("Numbers", "")).split(",")
            if str(token).strip().isdigit()
        ],
        "special": None,
        "displayLines": [],
        "label": "Keno",
        "sourceUrl": str(KENO_URL),
        "sourceDate": str(row.get("Ngay", "")).strip(),
    } for row in sorted_rows]


def filter_keno_history_items(items, count_key, now_value=None):
    normalized_count = normalize_live_history_count_key("KENO", count_key)
    if normalized_count.isdigit():
        return items[:max(1, int(normalized_count))], "", ""
    if normalized_count == "all":
        return items, KENO_HISTORY_RANGE_LABELS["all"], ""

    current = now_value or datetime.now()
    today = current.date()
    current_minutes = current.hour * 60 + current.minute
    start_date = keno_history_window_start_date(today, normalized_count)
    end_minutes = min(current_minutes, KENO_HISTORY_DAY_END_MINUTES)
    note = ""
    if current_minutes < KENO_HISTORY_DAY_START_MINUTES:
        note = "Chưa vào khung giờ Keno hôm nay (06:00 - 22:00)."

    filtered = []
    for item in items:
        row_date = parse_csv_date(item.get("date"))
        if row_date is None:
            continue
        if start_date and row_date < start_date:
            continue
        if row_date > today:
            continue
        if row_date == today:
            row_minutes = parse_time_to_minutes(item.get("time"))
            if row_minutes is None or row_minutes < KENO_HISTORY_DAY_START_MINUTES:
                continue
            if row_minutes > end_minutes:
                continue
        filtered.append(item)
    return filtered, KENO_HISTORY_RANGE_LABELS.get(normalized_count, ""), note


def load_keno_history_items(count=None, now_value=None, return_meta=False):
    count_key = normalize_live_history_count_key("KENO", count)
    rows_by_ky, _, _ = load_canonical_rows("KENO")
    items = build_keno_history_items(rows_by_ky)
    filtered_items, range_label, history_note = filter_keno_history_items(items, count_key, now_value=now_value)
    meta = {
        "countKey": count_key,
        "rangeLabel": range_label,
        "historyNote": history_note,
    }
    return (filtered_items, meta) if return_meta else filtered_items


def refresh_keno_history_for_requested_range(count_key, now_value=None):
    normalized_count = normalize_live_history_count_key("KENO", count_key)
    current = now_value or datetime.now()
    if normalized_count not in KENO_HISTORY_REFRESH_KEYS:
        return {"historyNote": ""}
    if current.hour * 60 + current.minute < KENO_HISTORY_DAY_START_MINUTES:
        return {"historyNote": "Chưa vào khung giờ Keno hôm nay (06:00 - 22:00)."}

    session = create_session()
    try:
        rows_by_ky, canonical_meta, _ = load_canonical_rows("KENO")
        day_results = fetch_keno_day_results(session, current.date())
        if day_results:
            merge_keno_result_rows(rows_by_ky, day_results)
            write_canonical_rows("KENO", rows_by_ky, current.date())
            _, earliest_row = get_latest_and_earliest_rows(rows_by_ky)
            earliest_ky = str(earliest_row.get("Ky", "")).strip()
            canonical_meta["lastSyncAt"] = current.isoformat(timespec="seconds")
            canonical_meta["effectiveEarliestKy"] = earliest_ky
            canonical_meta["effectiveEarliestDate"] = str(earliest_row.get("Ngay", "")).strip()
            canonical_meta["sourceLimited"] = bool(earliest_ky and sort_key_from_ky(earliest_ky) > 1)
            write_canonical_meta("KENO", canonical_meta)
        return {"historyNote": ""}
    except Exception as exc:
        return {
            "historyNote": f"Không tự rà được Keno hôm nay từ MinhChinh, đang dùng dữ liệu đã có: {exc}",
        }
    finally:
        try:
            session.close()
        except Exception:
            pass


def keno_result_to_csv_row(result):
    numbers = [int(value) for value in (result.get("main") or [])]
    return {
        "Ky": str(result.get("ky", "")).strip(),
        "Ngay": str(result.get("date", "")).strip(),
        "Time": str(result.get("time", "")).strip(),
        "Numbers": ",".join(str(value) for value in numbers),
        "L/-/N": calc_keno_ln(numbers),
        "C/-/L": calc_keno_cl(numbers),
    }


def load_keno_csv_rows(csv_path, return_info=False):
    rows_by_ky = {}
    info = {"sanitized": False, "issues": []}
    if not csv_path.exists():
        return (rows_by_ky, info) if return_info else rows_by_ky

    text, read_info = read_csv_text_safely(csv_path)
    info["sanitized"] = bool(read_info.get("sanitized"))
    info["issues"].extend(read_info.get("issues") or [])
    if not text:
        return (rows_by_ky, info) if return_info else rows_by_ky

    reader = csv.reader(io.StringIO(text), skipinitialspace=True)
    header = next(reader, None)
    if not header:
        return (rows_by_ky, info) if return_info else rows_by_ky

    header_lookup = resolve_keno_csv_header_map(header)
    ky_index = header_lookup.get("Ky")
    date_index = header_lookup.get("Ngay")
    time_index = header_lookup.get("Time")
    numbers_index = header_lookup.get("Numbers")
    ln_index = header_lookup.get("L/-/N")
    cl_index = header_lookup.get("C/-/L")

    if None in {ky_index, date_index, time_index, numbers_index}:
        info["sanitized"] = True
        info["issues"].append("missing_required_header")
        return (rows_by_ky, info) if return_info else rows_by_ky

    for row in reader:
        if not any(str(cell or "").strip() for cell in row):
            continue
        ky = re.sub(r"\D", "", str(row[ky_index] or "").strip()) if ky_index < len(row) else ""
        date_value = str(row[date_index] or "").strip() if date_index < len(row) else ""
        time_value = str(row[time_index] or "").strip() if time_index < len(row) else ""
        numbers_raw = str(row[numbers_index] or "").strip() if numbers_index < len(row) else ""
        row_date = parse_csv_date(date_value)
        if not ky or len(ky) > 6 or not numbers_raw or row_date is None:
            info["sanitized"] = True
            if "invalid_row_skipped" not in info["issues"]:
                info["issues"].append("invalid_row_skipped")
            continue
        try:
            numbers = [int(token.strip()) for token in numbers_raw.split(",") if token.strip()]
        except ValueError:
            info["sanitized"] = True
            if "invalid_numbers_skipped" not in info["issues"]:
                info["issues"].append("invalid_numbers_skipped")
            continue
        if len(numbers) != 20:
            info["sanitized"] = True
            if "invalid_numbers_skipped" not in info["issues"]:
                info["issues"].append("invalid_numbers_skipped")
            continue
        ln_value = ""
        if ln_index is not None and ln_index < len(row):
            ln_value = normalize_keno_ln_value(row[ln_index])
        cl_value = ""
        if cl_index is not None and cl_index < len(row):
            cl_value = normalize_keno_cl_value(row[cl_index])
        rows_by_ky[ky] = {
            "Ky": ky,
            "Ngay": format_csv_date(row_date),
            "Time": time_value,
            "Numbers": ",".join(str(value) for value in numbers),
            "L/-/N": ln_value or calc_keno_ln(numbers),
            "C/-/L": cl_value or calc_keno_cl(numbers),
        }
    return (rows_by_ky, info) if return_info else rows_by_ky


def write_keno_csv_rows(csv_path, rows_by_ky):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    sorted_rows = sorted(
        rows_by_ky.values(),
        key=lambda item: sort_key_from_ky(item.get("Ky", "")),
        reverse=True,
    )
    temp_path = csv_path.with_name(f"{csv_path.name}.tmp")
    with temp_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(KENO_CSV_HEADER)
        for row in sorted_rows:
            writer.writerow([serialize_keno_csv_value(field, row.get(field, "")) for field in KENO_CSV_FIELDS])
    os.replace(str(temp_path), str(csv_path))


def merge_result_rows(rows_by_ky, results):
    new_rows = 0
    updated_rows = 0
    for result in results:
        row = result_to_csv_row(result)
        ky = row["Ky"]
        previous = rows_by_ky.get(ky)
        if previous is None:
            new_rows += 1
        elif previous != row:
            updated_rows += 1
        rows_by_ky[ky] = row
    return new_rows, updated_rows


def merge_keno_result_rows(rows_by_ky, results):
    new_rows = 0
    updated_rows = 0
    for result in results:
        row = keno_result_to_csv_row(result)
        ky = row["Ky"]
        previous = rows_by_ky.get(ky)
        if previous is None:
            new_rows += 1
        elif previous != row:
            updated_rows += 1
        rows_by_ky[ky] = row
    return new_rows, updated_rows


def iter_type_dates(type_key, start_date, end_date):
    cursor = start_date
    while cursor <= end_date:
        if type_key == "KENO" or should_fetch_history_date(type_key, cursor):
            yield cursor
        cursor += timedelta(days=1)


def rows_grouped_by_date(rows_by_ky):
    grouped = defaultdict(list)
    for row in rows_by_ky.values():
        row_date = parse_csv_date(row.get("Ngay"))
        if row_date is None:
            continue
        grouped[row_date].append(row)
    return grouped


def get_earliest_row_date(rows_by_ky):
    dates = [
        parse_csv_date(row.get("Ngay"))
        for row in rows_by_ky.values()
    ]
    dates = [value for value in dates if value is not None]
    return min(dates) if dates else None


def collect_seed_files(type_key):
    paths = {}
    canonical_paths = get_canonical_output_paths(type_key)
    canonical_all_path = canonical_paths["all"]
    if canonical_all_path.exists():
        paths[canonical_all_path.resolve()] = canonical_all_path

    if type_key == "KENO":
        patterns = ["keno*.csv"]
    else:
        stem = HISTORY_OUTPUT_STEMS[type_key]
        patterns = [f"{stem}*.csv"]

    for pattern in patterns:
        for path in PROJECT_ROOT.glob(pattern):
            if path.is_file():
                if path.name.endswith("_hom_nay.csv"):
                    continue
                if type_key == "MAX_3D" and path.name.startswith("max_3d_pro_"):
                    continue
                paths[path.resolve()] = path

    return sorted(paths.values(), key=lambda path: (path.stat().st_mtime, path.name))


def load_seed_rows(type_key):
    loader = load_keno_csv_rows if type_key == "KENO" else load_csv_rows
    rows_by_ky = {}
    seed_files = []
    canonical_all_path = get_canonical_output_paths(type_key)["all"].resolve()
    for path in collect_seed_files(type_key):
        if path.resolve() == canonical_all_path:
            file_rows, _, _ = load_canonical_rows(type_key)
        else:
            file_rows = loader(path)
        if not file_rows:
            continue
        rows_by_ky.update(file_rows)
        seed_files.append(path.name)
    rows_by_ky, _ = filter_rows_for_type(type_key, rows_by_ky)
    return rows_by_ky, seed_files


def count_gap_intervals(rows_by_ky):
    sorted_rows = sorted(
        rows_by_ky.values(),
        key=lambda item: sort_key_from_ky(item.get("Ky", "")),
        reverse=True,
    )
    gap_count = 0
    gap_dates = set()
    for previous, current in zip(sorted_rows, sorted_rows[1:]):
        previous_ky = sort_key_from_ky(previous.get("Ky", ""))
        current_ky = sort_key_from_ky(current.get("Ky", ""))
        if previous_ky <= 0 or current_ky <= 0 or previous_ky - current_ky <= 1:
            continue
        gap_count += 1
        previous_date = parse_csv_date(previous.get("Ngay"))
        current_date = parse_csv_date(current.get("Ngay"))
        if previous_date and current_date:
            start_date = min(previous_date, current_date)
            end_date = max(previous_date, current_date)
            for target_date in iter_type_dates("LOTO_5_35", start_date, end_date):
                gap_dates.add(target_date)
        else:
            if previous_date:
                gap_dates.add(previous_date)
            if current_date:
                gap_dates.add(current_date)
    return gap_count, gap_dates


def count_gap_intervals_for_type(type_key, rows_by_ky):
    sorted_rows = sorted(
        rows_by_ky.values(),
        key=lambda item: sort_key_from_ky(item.get("Ky", "")),
        reverse=True,
    )
    gap_count = 0
    gap_dates = set()
    for previous, current in zip(sorted_rows, sorted_rows[1:]):
        previous_ky = sort_key_from_ky(previous.get("Ky", ""))
        current_ky = sort_key_from_ky(current.get("Ky", ""))
        if previous_ky <= 0 or current_ky <= 0 or previous_ky - current_ky <= 1:
            continue
        gap_count += 1
        previous_date = parse_csv_date(previous.get("Ngay"))
        current_date = parse_csv_date(current.get("Ngay"))
        if previous_date and current_date:
            start_date = min(previous_date, current_date)
            end_date = max(previous_date, current_date)
            for target_date in iter_type_dates(type_key, start_date, end_date):
                gap_dates.add(target_date)
        else:
            if previous_date and (type_key == "KENO" or should_fetch_history_date(type_key, previous_date)):
                gap_dates.add(previous_date)
            if current_date and (type_key == "KENO" or should_fetch_history_date(type_key, current_date)):
                gap_dates.add(current_date)
    return gap_count, gap_dates


def is_complete_keno_day(day_rows):
    if len(day_rows) != KENO_FULL_DAY_DRAW_COUNT:
        return False
    kys = sorted(sort_key_from_ky(row.get("Ky", "")) for row in day_rows)
    if not kys or kys[0] <= 0:
        return False
    return all(current - previous == 1 for previous, current in zip(kys, kys[1:]))

def html_to_lines(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n")
    return [normalize_space(line) for line in text.splitlines() if normalize_space(line)]


def find_first_index(lines, predicate, start=0):
    for index in range(start, len(lines)):
        if predicate(lines[index]):
            return index
    return -1


def parse_result_header(line):
    match = re.search(
        r"kết quả qsmt kỳ\s*#?0*(\d+).*?ngày\s*(\d{2}/\d{2}/\d{4})"
        r"(?:\s*-\s*lúc\s*(\d{2}:\d{2})|\s+(\d{2}:\d{2}))?",
        normalize_space(line),
        re.IGNORECASE,
    )
    if not match:
        return None
    return {
        "ky": match.group(1),
        "date": match.group(2),
        "time": match.group(3) or match.group(4) or "",
    }


def parse_result_header_window(lines, start=0, limit=6):
    window = [normalize_space(line) for line in lines[start:start + limit] if normalize_space(line)]
    if not window:
        return None
    return parse_result_header(" ".join(window))


def parse_ky(lines, start, limit=10):
    parsed = parse_result_header_window(lines, start, limit)
    if parsed:
        return parsed["ky"]
    for line in lines[start:start + limit]:
        parsed = parse_result_header(line)
        if parsed:
            return parsed["ky"]
        match = re.search(r"#0*(\d+)", line)
        if match:
            return match.group(1)
    return None


def parse_date_time(lines, start, limit=12):
    date_value = ""
    time_value = ""
    parsed_window = parse_result_header_window(lines, start, limit)
    if parsed_window:
        return parsed_window["date"], parsed_window["time"]
    for line in lines[start:start + limit]:
        parsed = parse_result_header(line)
        if parsed:
            date_value = parsed["date"]
            time_value = parsed["time"]
            return date_value, time_value
        match = re.search(r"(\d{2}/\d{2}/\d{4})(?:\s+(\d{2}:\d{2}))?", line)
        if match:
            date_value = match.group(1)
            time_value = match.group(2) or ""
            return date_value, time_value
    return date_value, time_value


def collect_numbers(lines, start, needed, exact_digits=None, line_limit=30):
    numbers = []
    token_pattern = r"\b\d+\b" if exact_digits is None else rf"\b\d{{{exact_digits}}}\b"
    for line in lines[start:start + line_limit]:
        for token in re.findall(token_pattern, line):
            if exact_digits is None:
                if len(token) > 2:
                    continue
                numbers.append(int(token))
            else:
                numbers.append(token)
            if len(numbers) >= needed:
                return numbers
    return numbers


def collect_draw_balls(lines, start, needed, line_limit=20):
    numbers = []
    started = False
    for line in lines[start:start + line_limit]:
        text = normalize_space(line)
        if not text:
            continue
        if re.search(r"[^\d\s,]", text):
            if started:
                break
            continue
        tokens = [int(token) for token in re.findall(r"\b\d+\b", text) if len(token) <= 2]
        if not tokens:
            if started:
                break
            continue
        started = True
        numbers.extend(tokens)
        if len(numbers) >= needed:
            return numbers[:needed]
    return numbers


def build_numeric_result(cfg, ky, date_value, time_value, balls, source_url):
    main = balls[:cfg.main_count]
    special = balls[cfg.main_count] if cfg.has_special else None
    display = " ".join(f"{value:02d}" for value in main)
    if special is not None:
        display += f" | ĐB {special:02d}"
    return {
        "key": cfg.key,
        "label": cfg.label,
        "ky": ky,
        "date": date_value,
        "time": time_value,
        "main": main,
        "special": special,
        "displayLines": [display],
        "importable": True,
        "sourceUrl": source_url,
    }


def parse_numeric_block(cfg, lines, source_url):
    def is_block_start(line):
        line_slug = slug(line)
        if cfg.marker not in line_slug:
            return False
        if "xoso" not in line_slug and "ketqu" not in line_slug:
            return False
        if cfg.exclude and cfg.exclude in line_slug:
            return False
        return True

    start = find_first_index(lines, is_block_start, start=120)
    if start < 0:
        return None

    ky = parse_ky(lines, start)
    if not ky:
        return None

    date_value, time_value = parse_date_time(lines, start)
    if not date_value:
        return None

    date_line_index = find_first_index(
        lines,
        lambda value: re.search(r"\d{2}/\d{2}/\d{4}", value) is not None,
        start=start,
    )
    if date_line_index < 0:
        return None

    needed = cfg.main_count + (1 if cfg.has_special else 0)
    balls = collect_numbers(lines, date_line_index + 1, needed)
    if len(balls) != needed:
        return None

    return build_numeric_result(cfg, ky, date_value, time_value, balls, source_url)


def collect_block_slice(lines, start, max_lines=120):
    end = min(len(lines), start + max_lines)
    for index in range(start + 1, min(len(lines), start + max_lines)):
        line_slug = slug(lines[index])
        if "inton" in line_slug and index > start + 5:
            end = index
            break
    return lines[start:end]


def collect_prize_tokens(block_lines, start_idx, end_idx):
    tokens = []
    for line in block_lines[start_idx + 1:end_idx]:
        tokens.extend(re.findall(r"\b\d{3}\b", line))
    return tokens


def find_next_prize_boundary(block_lines, start_idx):
    return find_first_index(
        block_lines,
        lambda value: slug(value).startswith("giai") or slug(value) == "acbiet",
        start=start_idx + 1,
    )


def extract_draw_sections(lines, pre_context=1):
    start_indices = []
    for index, line in enumerate(lines):
        if "kết quả qsmt kỳ" in normalize_space(line).lower():
            start_indices.append(index)

    sections = []
    for position, start_index in enumerate(start_indices):
        section_start = max(0, start_index - pre_context)
        end_index = start_indices[position + 1] if position + 1 < len(start_indices) else len(lines)
        sections.append(lines[section_start:end_index])
    return sections


def section_matches_cfg(cfg, section_lines):
    head_slugs = [slug(line) for line in section_lines[:8]]
    if cfg.kind == "numeric":
        return any(cfg.marker in value for value in head_slugs)
    if cfg.kind == "max3d":
        return any("max3d" in value and "pro" not in value for value in head_slugs)
    if cfg.kind == "max3dpro":
        return any("max3dpro" in value for value in head_slugs)
    return True


def parse_numeric_section(cfg, section_lines, source_url):
    if not section_lines:
        return None

    header_index = find_first_index(
        section_lines,
        lambda value: "kết quả qsmt kỳ" in normalize_space(value).lower(),
        start=0,
    )
    if header_index < 0:
        header_index = 0
    header = parse_result_header_window(section_lines, header_index, 6)
    if not header:
        return None

    needed = cfg.main_count + (1 if cfg.has_special else 0)
    balls = collect_draw_balls(section_lines, header_index + 1, needed, line_limit=18)
    if len(balls) != needed:
        return None

    return build_numeric_result(
        cfg,
        header["ky"],
        header["date"],
        header["time"],
        balls,
        source_url,
    )


def parse_display_section(cfg, section_lines, source_url, label_specs):
    if not section_lines:
        return None

    header_index = find_first_index(
        section_lines,
        lambda value: "kết quả qsmt kỳ" in normalize_space(value).lower(),
        start=0,
    )
    if header_index < 0:
        header_index = 0
    header = parse_result_header_window(section_lines, header_index, 6)
    if not header:
        return None

    indices = []
    cursor = header_index + 1
    for _, label_candidates in label_specs:
        index = find_first_index(
            section_lines,
            lambda value, candidates=label_candidates: slug(value) in candidates,
            start=cursor,
        )
        if index < 0:
            return None
        indices.append(index)
        cursor = index + 1

    display_lines = []
    for idx, (label, _) in enumerate(label_specs):
        start_idx = indices[idx]
        if idx + 1 < len(indices):
            end_idx = indices[idx + 1]
        else:
            end_idx = find_next_prize_boundary(section_lines, start_idx)
            if end_idx < 0:
                end_idx = len(section_lines)
        tokens = collect_prize_tokens(section_lines, start_idx, end_idx)
        if tokens:
            display_lines.append(f"{label}: {' '.join(tokens)}")

    if not display_lines:
        return None

    return {
        "key": cfg.key,
        "label": cfg.label,
        "ky": header["ky"],
        "date": header["date"],
        "time": header["time"],
        "main": [],
        "special": None,
        "displayLines": display_lines,
        "importable": False,
        "sourceUrl": source_url,
    }


def parse_display_block(cfg, lines, source_url, label_specs):
    def is_block_start(line):
        line_slug = slug(line)
        if cfg.marker not in line_slug:
            return False
        if "xoso" not in line_slug and "ketqu" not in line_slug:
            return False
        if cfg.exclude and cfg.exclude in line_slug:
            return False
        return True

    start = find_first_index(lines, is_block_start, start=120)
    if start < 0:
        return None

    ky = parse_ky(lines, start)
    date_value, time_value = parse_date_time(lines, start)
    if not ky or not date_value:
        return None

    block_lines = collect_block_slice(lines, start)
    indices = []
    cursor = 0
    for _, label_candidates in label_specs:
        index = find_first_index(
            block_lines,
            lambda value, candidates=label_candidates: slug(value) in candidates,
            start=cursor,
        )
        if index < 0:
            return None
        indices.append(index)
        cursor = index + 1

    display_lines = []
    for idx, (label, _) in enumerate(label_specs):
        start_idx = indices[idx]
        if idx + 1 < len(indices):
            end_idx = indices[idx + 1]
        else:
            end_idx = find_next_prize_boundary(block_lines, start_idx)
            if end_idx < 0:
                end_idx = len(block_lines)
        tokens = collect_prize_tokens(block_lines, start_idx, end_idx)
        if tokens:
            display_lines.append(f"{label}: {' '.join(tokens)}")

    if not display_lines:
        return None

    return {
        "key": cfg.key,
        "label": cfg.label,
        "ky": ky,
        "date": date_value,
        "time": time_value,
        "main": [],
        "special": None,
        "displayLines": display_lines,
        "importable": False,
        "sourceUrl": source_url,
    }


def parse_max3d_block(cfg, lines, source_url):
    label_specs = [
        ("Đặc biệt", {"acbiet"}),
        ("Giải nhất", {"giainhat"}),
        ("Giải nhì", {"giainhi"}),
        ("Giải ba", {"giaiba"}),
    ]
    return parse_display_block(cfg, lines, source_url, label_specs)


def parse_max3dpro_block(cfg, lines, source_url):
    label_specs = [
        ("Đặc biệt", {"acbiet"}),
        ("Giải nhất", {"giainhat"}),
        ("Giải nhì", {"giainhi"}),
        ("Giải ba", {"giaiba"}),
    ]
    return parse_display_block(cfg, lines, source_url, label_specs)


def parse_max3d_section(cfg, section_lines, source_url):
    label_specs = [
        ("Đặc biệt", {"acbiet"}),
        ("Giải nhất", {"giainhat"}),
        ("Giải nhì", {"giainhi"}),
        ("Giải ba", {"giaiba"}),
    ]
    return parse_display_section(cfg, section_lines, source_url, label_specs)


def parse_max3dpro_section(cfg, section_lines, source_url):
    label_specs = [
        ("Đặc biệt", {"acbiet"}),
        ("Giải nhất", {"giainhat"}),
        ("Giải nhì", {"giainhi"}),
        ("Giải ba", {"giaiba"}),
    ]
    return parse_display_section(cfg, section_lines, source_url, label_specs)


def parse_keno_from_minhchinh(session):
    response = session.get(KENO_URL, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    row = soup.select_one("#containerKQKeno .wrapperKQKeno")
    if not row:
        raise RuntimeError("Hoạt động từ 6:00 đến 22:00")

    ky_node = row.select_one(".kyKQKeno")
    time_parts = row.select(".timeKQ > div")
    numbers = [int(node.get_text(strip=True)) for node in row.select(".boxKQKeno > div")]
    if not ky_node or len(time_parts) < 2 or len(numbers) != 20:
        raise RuntimeError("Dữ liệu Keno mới nhất không đúng định dạng.")

    ky = re.sub(r"\D", "", ky_node.get_text(" ", strip=True))
    date_value = time_parts[0].get_text(strip=True)
    time_value = time_parts[1].get_text(strip=True)
    display = " ".join(f"{value:02d}" for value in numbers)
    return {
        "key": "KENO",
        "label": "Keno",
        "ky": ky,
        "date": date_value,
        "time": time_value,
        "main": numbers,
        "special": None,
        "displayLines": [display],
        "importable": True,
        "sourceUrl": KENO_URL,
    }


def fetch_vietlott_day_lines(session, cache, target_date):
    date_key = target_date.strftime("%d-%m-%Y")
    if date_key in cache:
        return cache[date_key]
    url = VIETLOTT_DAY_URL.format(date=date_key)
    html = fetch_url_text(session, url)
    if html is None:
        cache[date_key] = (url, [])
        return cache[date_key]
    lines = html_to_lines(html)
    cache[date_key] = (url, lines)
    return cache[date_key]


def fetch_minhchinh_history_lines(session, cache, cfg, target_date):
    date_key = f"{cfg.key}:{target_date.strftime('%d-%m-%Y')}"
    if date_key in cache:
        return cache[date_key]

    url_pattern = HISTORY_URL_PATTERNS.get(cfg.key)
    if not url_pattern:
        raise RuntimeError(f"Chưa cấu hình URL lịch sử MinhChinh cho {cfg.label}.")

    url = url_pattern.format(date=target_date.strftime("%d-%m-%Y"))
    html = fetch_url_text(session, url)
    lines = html_to_lines(html) if html else []
    cache[date_key] = (url, lines)
    return cache[date_key]


def fetch_latest_vietlott_result(session, cache, cfg):
    parser = parse_numeric_block
    if cfg.kind == "max3d":
        parser = parse_max3d_block
    elif cfg.kind == "max3dpro":
        parser = parse_max3dpro_block

    today = datetime.now()
    for offset in range(LOOKBACK_DAYS + 1):
        target_date = today - timedelta(days=offset)
        url, lines = fetch_vietlott_day_lines(session, cache, target_date)
        result = parser(cfg, lines, url)
        if result:
            result["sourceDate"] = target_date.strftime("%d/%m/%Y")
            return result

    raise RuntimeError(f"Không tìm thấy kết quả gần nhất cho {cfg.label} trong {LOOKBACK_DAYS + 1} ngày.")


def fetch_latest_minhchinh_result(session, cache, cfg):
    today = datetime.now().date()
    for offset in range(LOOKBACK_DAYS + 1):
        target_date = today - timedelta(days=offset)
        if not should_fetch_history_date(cfg.key, target_date):
            continue
        url, lines = fetch_minhchinh_history_lines(session, cache, cfg, target_date)
        results = parse_history_results(cfg, lines, url, target_date)
        if not results:
            continue
        return max(results, key=lambda item: sort_key_from_ky(item.get("ky", "")))

    raise RuntimeError(f"Không tìm thấy kết quả MinhChinh gần nhất cho {cfg.label} trong {LOOKBACK_DAYS + 1} ngày.")


def fetch_live_result(session, cache, type_key):
    cfg = LIVE_TYPES[type_key]
    if cfg.kind == "keno":
        return parse_keno_from_minhchinh(session)
    if cfg.kind in {"max3d", "max3dpro"}:
        return fetch_latest_minhchinh_result(session, cache, cfg)
    return fetch_latest_vietlott_result(session, cache, cfg)


def parse_history_results(cfg, lines, source_url, source_date):
    parser = parse_numeric_section
    if cfg.kind == "max3d":
        parser = parse_max3d_section
    elif cfg.kind == "max3dpro":
        parser = parse_max3dpro_section

    results = []
    for section_lines in extract_draw_sections(lines):
        if not section_matches_cfg(cfg, section_lines):
            continue
        result = parser(cfg, section_lines, source_url)
        if not result:
            continue
        result_date = parse_csv_date(result.get("date"))
        if result_date != source_date:
            continue
        result["sourceDate"] = source_date.strftime("%d/%m/%Y")
        results.append(result)
    return results


def should_fetch_history_date(type_key, target_date):
    allowed_weekdays = HISTORY_WEEKDAY_FILTERS.get(type_key)
    if not allowed_weekdays:
        return True
    return target_date.weekday() in allowed_weekdays

def fetch_history_results_for_date(session, cache, cfg, target_date):
    url, lines = fetch_minhchinh_history_lines(session, cache, cfg, target_date)
    return parse_history_results(cfg, lines, url, target_date)


def get_expected_numeric_day_slots(type_key):
    return tuple(NUMERIC_EXPECTED_DAY_SLOTS.get(type_key, ()))


def normalize_draw_time_slot(value):
    text = str(value or "").strip()
    match = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", text)
    if not match:
        return text
    return f"{int(match.group(1)):02d}:{int(match.group(2)):02d}"


def is_complete_numeric_day(type_key, day_rows):
    expected_slots = get_expected_numeric_day_slots(type_key)
    if not expected_slots:
        return True
    existing_slots = {
        normalize_draw_time_slot(row.get("Time", ""))
        for row in day_rows
        if normalize_draw_time_slot(row.get("Time", ""))
    }
    return all(slot in existing_slots for slot in expected_slots)


def is_complete_numeric_results_for_date(type_key, results):
    expected_slots = get_expected_numeric_day_slots(type_key)
    if not expected_slots:
        return bool(results)
    result_slots = {
        normalize_draw_time_slot(item.get("time", ""))
        for item in (results or [])
        if normalize_draw_time_slot(item.get("time", ""))
    }
    return all(slot in result_slots for slot in expected_slots)


def count_keno_partial_days(rows_by_ky, today):
    grouped = rows_grouped_by_date(rows_by_ky)
    partial_dates = set()
    for row_date, day_rows in grouped.items():
        if row_date >= today:
            continue
        if not is_complete_keno_day(day_rows):
            partial_dates.add(row_date)
    return len(partial_dates), partial_dates


def count_numeric_partial_days(type_key, rows_by_ky, today):
    expected_slots = get_expected_numeric_day_slots(type_key)
    if not expected_slots:
        return 0, set()
    grouped = rows_grouped_by_date(rows_by_ky)
    partial_dates = set()
    for row_date, day_rows in grouped.items():
        if row_date >= today:
            continue
        if not is_complete_numeric_day(type_key, day_rows):
            partial_dates.add(row_date)
    return len(partial_dates), partial_dates


def write_canonical_rows(type_key, rows_by_ky, today):
    canonical_paths = get_canonical_output_paths(type_key)
    today_count = count_rows_for_date(rows_by_ky, today)

    if type_key == "KENO":
        write_keno_csv_rows(canonical_paths["all"], rows_by_ky)
    else:
        write_csv_rows(canonical_paths["all"], rows_by_ky)

    return canonical_paths, today_count, len(rows_by_ky)


def bootstrap_numeric_full_history(session, cache, type_key, rows_by_ky):
    cfg = LIVE_TYPES[type_key]
    today = datetime.now().date()
    earliest_date = get_earliest_row_date(rows_by_ky) or today
    cursor = earliest_date - timedelta(days=1) if rows_by_ky else today
    empty_hits = 0
    new_rows = 0
    updated_rows = 0
    errors = []

    while empty_hits < SYNC_ALL_EMPTY_DAY_STOP:
        if not should_fetch_history_date(type_key, cursor):
            cursor -= timedelta(days=1)
            continue
        try:
            results = fetch_history_results_for_date(session, cache, cfg, cursor)
        except Exception as exc:
            errors.append({
                "type": type_key,
                "date": format_minhchinh_date(cursor),
                "message": str(exc),
            })
            break
        if results:
            added, updated = merge_result_rows(rows_by_ky, results)
            new_rows += added
            updated_rows += updated
            empty_hits = 0
        else:
            empty_hits += 1
        cursor -= timedelta(days=1)
        time.sleep(HISTORY_REQUEST_DELAY_SECONDS)

    return {
        "newRows": new_rows,
        "updatedRows": updated_rows,
        "errors": errors,
        "bootstrapComplete": empty_hits >= SYNC_ALL_EMPTY_DAY_STOP,
    }


def bootstrap_keno_full_history(session, rows_by_ky):
    today = datetime.now().date()
    earliest_date = get_earliest_row_date(rows_by_ky) or today
    cursor = earliest_date - timedelta(days=1) if rows_by_ky else today
    empty_hits = 0
    new_rows = 0
    updated_rows = 0
    errors = []

    while empty_hits < SYNC_ALL_EMPTY_DAY_STOP:
        try:
            results = fetch_keno_day_results(session, cursor)
        except Exception as exc:
            errors.append({
                "type": "KENO",
                "date": format_minhchinh_date(cursor),
                "message": str(exc),
            })
            break
        if results:
            added, updated = merge_keno_result_rows(rows_by_ky, results)
            new_rows += added
            updated_rows += updated
            empty_hits = 0
        else:
            empty_hits += 1
        cursor -= timedelta(days=1)

    return {
        "newRows": new_rows,
        "updatedRows": updated_rows,
        "errors": errors,
        "bootstrapComplete": empty_hits >= SYNC_ALL_EMPTY_DAY_STOP,
    }


# ----- Dong bo canonical full-history -----
# Day la core sync cho numeric/Keno, gom repair 30 ngay, bootstrap va ghi vao all_day.
def sync_all_numeric_type(session, cache, type_key, allow_bootstrap=True, progress=None, recent_lookback_days=None):
    cfg = LIVE_TYPES[type_key]
    today = datetime.now().date()
    meta = read_canonical_meta(type_key)
    rows_by_ky, seed_files = load_seed_rows(type_key)
    initial_row_count = len(rows_by_ky)
    initial_gap_count, gap_dates = count_gap_intervals_for_type(type_key, rows_by_ky)
    repairs = {"missingDates": 0, "partialDates": 0, "kyGaps": 0}
    errors = []
    new_rows = 0
    updated_rows = 0

    grouped = rows_grouped_by_date(rows_by_ky)
    existing_dates = set(grouped.keys())
    earliest_date = get_earliest_row_date(rows_by_ky) or today
    missing_dates = set()
    partial_count_before, partial_dates = count_numeric_partial_days(type_key, rows_by_ky, today)
    for target_date in iter_type_dates(type_key, earliest_date, today):
        if target_date not in existing_dates:
            missing_dates.add(target_date)

    dates_to_fetch = set(missing_dates)
    dates_to_fetch.update(partial_dates)
    dates_to_fetch.update(gap_dates)
    lookback_days = max(1, int(recent_lookback_days or SYNC_ALL_RECENT_LOOKBACK_DAYS))
    recent_start = max(earliest_date, today - timedelta(days=lookback_days))
    for target_date in iter_type_dates(type_key, recent_start, today):
        dates_to_fetch.add(target_date)

    sorted_dates_to_fetch = sorted(dates_to_fetch, reverse=True)
    if progress:
        progress.set_phase(
            "repair_recent",
            current_type=type_key,
                message=f"{cfg.label}: đang rà soát {len(sorted_dates_to_fetch)} ngày gần nhất từ MinhChinh.",
        )
        progress.reserve_steps(len(sorted_dates_to_fetch))

    repaired_missing_dates = set()
    repaired_partial_dates = set()
    for target_date in sorted_dates_to_fetch:
        progress_message = f"{cfg.label}: đã rà ngày {format_minhchinh_date(target_date)}."
        try:
            results = fetch_history_results_for_date(session, cache, cfg, target_date)
        except Exception as exc:
            errors.append({
                "type": type_key,
                "date": format_minhchinh_date(target_date),
                "message": str(exc),
            })
            if progress:
                progress.add_warning(f"{cfg.label} {format_minhchinh_date(target_date)}: {exc}")
                progress.complete_step(
                    message=progress_message,
                    current_type=type_key,
                    phase="repair_recent",
                )
            continue
        if target_date in missing_dates and results:
            repaired_missing_dates.add(target_date)
        if (
            target_date in partial_dates
            and target_date < today
            and is_complete_numeric_results_for_date(type_key, results)
        ):
            repaired_partial_dates.add(target_date)
        added, updated = merge_result_rows(rows_by_ky, results)
        new_rows += added
        updated_rows += updated
        if progress:
            progress.complete_step(
                message=progress_message,
                current_type=type_key,
                phase="repair_recent",
            )
        time.sleep(HISTORY_REQUEST_DELAY_SECONDS)

    if allow_bootstrap and not meta.get("bootstrapComplete"):
        bootstrap_result = bootstrap_numeric_full_history(session, cache, type_key, rows_by_ky)
        new_rows += bootstrap_result["newRows"]
        updated_rows += bootstrap_result["updatedRows"]
        errors.extend(bootstrap_result["errors"])
        if bootstrap_result["bootstrapComplete"]:
            meta["bootstrapComplete"] = True
            meta["lastBootstrapAt"] = datetime.now().isoformat(timespec="seconds")

    final_gap_count, _ = count_gap_intervals_for_type(type_key, rows_by_ky)
    partial_count_after, _ = count_numeric_partial_days(type_key, rows_by_ky, today)
    repairs["missingDates"] = len(repaired_missing_dates)
    repairs["partialDates"] = max(partial_count_before - partial_count_after, len(repaired_partial_dates))
    repairs["kyGaps"] = max(initial_gap_count - final_gap_count, 0)

    canonical_paths, today_count, all_count = write_canonical_rows(type_key, rows_by_ky, today)
    latest_row, earliest_row = get_latest_and_earliest_rows(rows_by_ky)
    earliest_row_date = parse_csv_date(earliest_row.get("Ngay", ""))
    earliest_ky = str(earliest_row.get("Ky", "")).strip()
    source_limited = bool(meta.get("bootstrapComplete")) and sort_key_from_ky(earliest_ky) > 1
    meta["bootstrapComplete"] = bool(meta.get("bootstrapComplete")) and bool(earliest_ky)
    meta["lastSyncAt"] = datetime.now().isoformat(timespec="seconds")
    meta["effectiveEarliestKy"] = earliest_ky
    meta["effectiveEarliestDate"] = str(earliest_row.get("Ngay", "")).strip()
    meta["sourceLimited"] = source_limited
    write_canonical_meta(type_key, meta)
    return {
        "type": type_key,
        "label": cfg.label,
        "seedFiles": seed_files,
        "canonicalFile": canonical_paths["all"].name,
        "canonicalCount": all_count,
        "todayFile": canonical_paths["today"].name,
        "allFile": canonical_paths["all"].name,
        "todayCount": today_count,
        "allCount": all_count,
        "newRows": max(len(rows_by_ky) - initial_row_count, new_rows),
        "updatedRows": updated_rows,
        "trimmedRows": 0,
        "repairedDates": repairs["missingDates"] + repairs["partialDates"],
        "repairedKyGaps": repairs["kyGaps"],
        "latestKy": str(latest_row.get("Ky", "")).strip(),
        "latestDate": str(latest_row.get("Ngay", "")).strip(),
        "latestTime": str(latest_row.get("Time", "")).strip(),
        "effectiveEarliestKy": earliest_ky,
        "effectiveEarliestDate": format_csv_date(earliest_row_date) if earliest_row_date else "",
        "bootstrapComplete": bool(meta.get("bootstrapComplete")),
        "requestedStartMode": str(meta.get("requestedStartMode", FULL_HISTORY_REQUESTED_START_MODE)),
        "sourceLimited": source_limited,
        "repairs": repairs,
        "errors": errors,
    }


def sync_all_keno_type(session, allow_bootstrap=True, progress=None, recent_lookback_days=None):
    today = datetime.now().date()
    now_value = datetime.now()
    meta = read_canonical_meta("KENO")
    rows_by_ky, seed_files = load_seed_rows("KENO")
    initial_row_count = len(rows_by_ky)
    partial_count_before, partial_dates = count_keno_partial_days(rows_by_ky, today)
    errors = []
    new_rows = 0
    updated_rows = 0
    manual_timeout_enabled = progress is not None and not allow_bootstrap
    manual_timeout_deadline = (
        time.perf_counter() + KENO_MANUAL_UPDATE_TIMEOUT_SECONDS
        if manual_timeout_enabled else None
    )
    manual_timeout_message = build_keno_manual_timeout_message(now_value)
    manual_timeout_recorded = False
    latest_page_sync_success = False

    def manual_timeout_reached():
        return manual_timeout_deadline is not None and time.perf_counter() >= manual_timeout_deadline

    def record_manual_timeout(error_date=""):
        nonlocal manual_timeout_recorded
        if manual_timeout_recorded:
            return
        manual_timeout_recorded = True
        errors.append({
            "type": "KENO",
            "date": str(error_date or "").strip(),
            "message": manual_timeout_message,
        })
        if progress:
            date_text = f" {error_date}" if str(error_date or "").strip() else ""
            progress.add_warning(f"Keno{date_text}: {manual_timeout_message}")

    grouped = rows_grouped_by_date(rows_by_ky)
    existing_dates = set(grouped.keys())
    earliest_date = get_earliest_row_date(rows_by_ky) or today
    missing_dates = set()
    for target_date in iter_type_dates("KENO", earliest_date, today):
        if target_date not in existing_dates:
            missing_dates.add(target_date)

    dates_to_fetch = set(missing_dates)
    dates_to_fetch.update(partial_dates)
    lookback_days = max(1, int(recent_lookback_days or SYNC_ALL_RECENT_LOOKBACK_DAYS))
    recent_start = max(earliest_date, today - timedelta(days=lookback_days))
    for target_date in iter_type_dates("KENO", recent_start, today):
        dates_to_fetch.add(target_date)

    try:
        latest_search_date, _ = fetch_latest_keno_page(session)
        latest_available_date = parse_csv_date(latest_search_date)
        if latest_available_date is not None:
            dates_to_fetch.add(latest_available_date)
    except Exception:
        latest_available_date = None

    if manual_timeout_reached():
        record_manual_timeout("")
        latest_available_date = None

    latest_page_date = latest_available_date if latest_available_date in dates_to_fetch else None
    regular_dates_to_fetch = [target_date for target_date in sorted(dates_to_fetch, reverse=True) if target_date != latest_page_date]
    if progress:
        progress.set_phase(
            "repair_recent",
            current_type="KENO",
            message=f"Keno: đang rà soát {len(dates_to_fetch)} ngày từ MinhChinh.",
        )
        progress.reserve_steps(len(regular_dates_to_fetch))
        if latest_page_date is not None:
            progress.reserve_steps(1)

    repaired_missing_dates = set()
    repaired_partial_dates = set()
    for target_date in sorted(dates_to_fetch, reverse=True):
        if manual_timeout_reached():
            record_manual_timeout(format_minhchinh_date(target_date))
            break
        progress_message = f"Keno: đã rà ngày {format_minhchinh_date(target_date)}."
        page_merge_counts = {"new": 0, "updated": 0}
        timeout_state = {}
        try:
            if progress and latest_page_date is not None and target_date == latest_page_date:
                def handle_keno_page_progress(page, new_count, has_results, will_continue, new_results=None, collected_count=0):
                    if new_results:
                        added_now, updated_now = merge_keno_result_rows(rows_by_ky, new_results)
                        page_merge_counts["new"] += added_now
                        page_merge_counts["updated"] += updated_now
                        _, page_today_count, page_all_count = write_canonical_rows("KENO", rows_by_ky, today)
                        progress.update_type_state(
                            "KENO",
                            state="running",
                            latestKy=str(next(iter(sorted(rows_by_ky.keys(), key=sort_key_from_ky, reverse=True)), "")).strip(),
                            latestDate=str(get_latest_and_earliest_rows(rows_by_ky)[0].get("Ngay", "")).strip() if rows_by_ky else "",
                            latestTime=str(get_latest_and_earliest_rows(rows_by_ky)[0].get("Time", "")).strip() if rows_by_ky else "",
                            todayCount=page_today_count,
                            allCount=page_all_count,
                            liveResult=(load_latest_canonical_live_results(["KENO"]) or [None])[0],
                            updatedAt=now_iso(),
                        )
                    page_message = (
                        f"Keno: đã quét ngày {format_minhchinh_date(target_date)} • page {page}."
                    )
                    progress.complete_step(
                        message=page_message,
                        current_type="KENO",
                        phase="repair_recent",
                        reserve_next_steps=1 if will_continue else 0,
                    )

                results = fetch_keno_day_results(
                    session,
                    target_date,
                    page_progress=handle_keno_page_progress,
                    deadline_monotonic=manual_timeout_deadline,
                    timeout_state=timeout_state,
                )
            else:
                results = fetch_keno_day_results(
                    session,
                    target_date,
                    deadline_monotonic=manual_timeout_deadline,
                    timeout_state=timeout_state,
                )
        except Exception as exc:
            errors.append({
                "type": "KENO",
                "date": format_minhchinh_date(target_date),
                "message": str(exc),
            })
            if progress:
                progress.add_warning(f"Keno {format_minhchinh_date(target_date)}: {exc}")
                progress.complete_step(
                    message=progress_message,
                    current_type="KENO",
                    phase="repair_recent",
                )
            continue
        if target_date in missing_dates and results:
            repaired_missing_dates.add(target_date)
        if target_date in partial_dates and target_date < today and len(results) >= KENO_FULL_DAY_DRAW_COUNT:
            repaired_partial_dates.add(target_date)
        if latest_page_date is not None and target_date == latest_page_date and results and not timeout_state.get("timedOut"):
            latest_page_sync_success = True
        added, updated = merge_keno_result_rows(rows_by_ky, results)
        new_rows += page_merge_counts["new"] + added
        updated_rows += page_merge_counts["updated"] + updated
        if progress and (latest_page_date is None or target_date != latest_page_date):
            progress.complete_step(
                message=progress_message,
                current_type="KENO",
                phase="repair_recent",
            )
        if timeout_state.get("timedOut"):
            record_manual_timeout(format_minhchinh_date(target_date))
            break

    if allow_bootstrap and not meta.get("bootstrapComplete"):
        bootstrap_result = bootstrap_keno_full_history(session, rows_by_ky)
        new_rows += bootstrap_result["newRows"]
        updated_rows += bootstrap_result["updatedRows"]
        errors.extend(bootstrap_result["errors"])
        if bootstrap_result["bootstrapComplete"]:
            meta["bootstrapComplete"] = True
            meta["lastBootstrapAt"] = datetime.now().isoformat(timespec="seconds")

    partial_count_after, _ = count_keno_partial_days(rows_by_ky, today)
    repairs = {
        "missingDates": len(repaired_missing_dates),
        "partialDates": max(partial_count_before - partial_count_after, 0),
        "kyGaps": max(partial_count_before - partial_count_after, 0),
    }

    canonical_paths, today_count, all_count = write_canonical_rows("KENO", rows_by_ky, today)
    latest_row, earliest_row = get_latest_and_earliest_rows(rows_by_ky)
    earliest_row_date = parse_csv_date(earliest_row.get("Ngay", ""))
    earliest_ky = str(earliest_row.get("Ky", "")).strip()
    source_limited = sort_key_from_ky(earliest_ky) > 1
    meta["bootstrapComplete"] = bool(meta.get("bootstrapComplete")) and bool(earliest_ky)
    meta["lastSyncAt"] = datetime.now().isoformat(timespec="seconds")
    meta["effectiveEarliestKy"] = earliest_ky
    meta["effectiveEarliestDate"] = str(earliest_row.get("Ngay", "")).strip()
    meta["sourceLimited"] = source_limited
    write_canonical_meta("KENO", meta)
    status_errors = list(errors)
    status_had_errors = bool(status_errors)
    if manual_timeout_enabled and latest_page_sync_success:
        status_errors = []
        status_had_errors = False
    return {
        "type": "KENO",
        "label": "Keno",
        "seedFiles": seed_files,
        "canonicalFile": canonical_paths["all"].name,
        "canonicalCount": all_count,
        "todayFile": canonical_paths["today"].name,
        "allFile": canonical_paths["all"].name,
        "todayCount": today_count,
        "allCount": all_count,
        "newRows": max(len(rows_by_ky) - initial_row_count, new_rows),
        "updatedRows": updated_rows,
        "trimmedRows": 0,
        "repairedDates": repairs["missingDates"] + repairs["partialDates"],
        "repairedKyGaps": repairs["kyGaps"],
        "latestKy": str(latest_row.get("Ky", "")).strip(),
        "latestDate": str(latest_row.get("Ngay", "")).strip(),
        "latestTime": str(latest_row.get("Time", "")).strip(),
        "effectiveEarliestKy": earliest_ky,
        "effectiveEarliestDate": format_csv_date(earliest_row_date) if earliest_row_date else "",
        "bootstrapComplete": bool(meta.get("bootstrapComplete")),
        "requestedStartMode": str(meta.get("requestedStartMode", FULL_HISTORY_REQUESTED_START_MODE)),
        "sourceLimited": source_limited,
        "repairs": repairs,
        "errors": errors,
        "statusHadErrors": status_had_errors,
        "statusErrors": status_errors,
    }


def sync_all_canonical_csvs(session, requested_type_keys=None, recent_lookback_days=None):
    return sync_requested_canonical_csvs(
        session,
        requested_type_keys or ["LOTO_5_35", "LOTO_6_45", "LOTO_6_55", "MAX_3D", "MAX_3D_PRO", "KENO"],
        allow_bootstrap=True,
        recent_lookback_days=recent_lookback_days,
    )


# ----- Payload tong hop cho live-results -----
# Gom ket qua sync cua tung loai thanh JSON ma frontend va server Java se su dung.
def sync_requested_canonical_csvs(session, requested_type_keys=None, allow_bootstrap=True, progress=None, recent_lookback_days=None):
    cache = {}
    outputs = []
    errors = []
    repairs = []
    default_type_keys = ["LOTO_5_35", "LOTO_6_45", "LOTO_6_55", "MAX_3D", "MAX_3D_PRO", "KENO"]
    type_keys = []
    seen = set()
    for raw in (requested_type_keys or default_type_keys):
        key = str(raw or "").strip().upper()
        if key in CANONICAL_OUTPUT_STEMS and key not in seen:
            seen.add(key)
            type_keys.append(key)
    if not type_keys:
        type_keys = list(default_type_keys)

    for type_key in type_keys:
        if progress:
            progress.mark_type_running(
                type_key,
                message=f"{LIVE_TYPES[type_key].label}: đang rà soát dữ liệu từ MinhChinh.",
            )
            progress.set_phase(
                "repair_recent",
                current_type=type_key,
                message=f"{LIVE_TYPES[type_key].label}: đang rà soát dữ liệu từ MinhChinh.",
            )
        if type_key == "KENO":
            result = sync_all_keno_type(
                session,
                allow_bootstrap=allow_bootstrap,
                progress=progress,
                recent_lookback_days=recent_lookback_days,
            )
        else:
            result = sync_all_numeric_type(
                session,
                cache,
                type_key,
                allow_bootstrap=allow_bootstrap,
                progress=progress,
                recent_lookback_days=recent_lookback_days,
            )
        outputs.append({
            "type": result["type"],
            "canonicalFile": result.get("canonicalFile") or result["allFile"],
            "canonicalCount": result.get("canonicalCount") or result["allCount"],
            "todayFile": result["todayFile"],
            "allFile": result["allFile"],
            "todayCount": result["todayCount"],
            "allCount": result["allCount"],
            "newRows": result["newRows"],
            "trimmedRows": result.get("trimmedRows", 0),
            "repairedDates": result["repairedDates"],
            "repairedKyGaps": result["repairedKyGaps"],
            "latestKy": result["latestKy"],
            "latestDate": result["latestDate"],
            "latestTime": result.get("latestTime", ""),
            "effectiveEarliestKy": result.get("effectiveEarliestKy", ""),
            "effectiveEarliestDate": result.get("effectiveEarliestDate", ""),
            "bootstrapComplete": bool(result.get("bootstrapComplete", False)),
            "requestedStartMode": result.get("requestedStartMode", FULL_HISTORY_REQUESTED_START_MODE),
            "sourceLimited": bool(result.get("sourceLimited", False)),
        })
        repairs.append({
            "type": result["type"],
            **result["repairs"],
        })
        errors.extend(result["errors"])
        if progress:
            progress.complete_type(type_key, result, had_errors=bool(result["errors"]))
            for item in (result["errors"] or []):
                date_text = f" {item.get('date')}" if item.get("date") else ""
                progress.add_warning(f"{item.get('type', type_key)}{date_text}: {item.get('message', '')}")

    scoring_exports = refresh_scoring_csv_exports(type_keys, progress=progress)

    return {
        "ok": True,
        "mode": "sync_all",
        "fetchedAt": datetime.now().isoformat(timespec="seconds"),
        "types": type_keys,
        "outputs": outputs,
        "repairs": repairs,
        "scoringExports": scoring_exports,
        "errors": errors,
    }


# ----- Phan tich tham so CLI -----
# Ho tro cac mode sync_all, live_history, history export va luong update thu cong.
def parse_cli_args():
    raw_args = [str(value).strip() for value in sys.argv[1:] if str(value).strip()]
    repair_canonical = False
    recent_lookback_days = None
    args = []
    idx = 0
    while idx < len(raw_args):
        raw = raw_args[idx]
        lowered = raw.lower()
        if lowered in {"--repair-canonical", "--backfill-all-day", "--sync-canonical", "repair_canonical"}:
            repair_canonical = True
            idx += 1
            continue
        if lowered.startswith("--recent-days="):
            value = lowered.split("=", 1)[1].strip()
            if value.isdigit():
                recent_lookback_days = max(1, int(value))
            idx += 1
            continue
        if lowered == "--recent-days":
            next_value = raw_args[idx + 1].strip() if idx + 1 < len(raw_args) else ""
            if next_value.isdigit():
                recent_lookback_days = max(1, int(next_value))
                idx += 2
                continue
        args.append(raw)
        idx += 1
    if args and args[0].lower() in {"sync_all", "sync-all", "canonical", "canonical_sync"}:
        requested = []
        for raw in args[1:]:
            key = raw.strip().upper()
            if key in CANONICAL_OUTPUT_STEMS and key not in requested:
                requested.append(key)
        return {
            "mode": "sync_all",
            "types": requested or list(CANONICAL_OUTPUT_STEMS.keys()),
            "recentLookbackDays": recent_lookback_days,
        }
    if args and args[0].lower() in {"live_history", "live-history", "canonical_history", "canonical-history"}:
        remaining = args[1:]
        requested_type = next((raw.strip().upper() for raw in remaining if raw.strip().upper() in LIVE_TYPES), "LOTO_5_35")
        requested_count = next((
            raw.strip() for raw in remaining
            if (
                raw.strip().lower() == "all"
                or raw.strip().isdigit()
                or (requested_type == "KENO" and raw.strip().lower() in KENO_HISTORY_RANGE_LABELS)
            )
        ), "today" if requested_type == "KENO" else "20")
        return {
            "mode": "canonical_history",
            "type": requested_type,
            "count": requested_count,
            "repairCanonical": repair_canonical,
            "recentLookbackDays": recent_lookback_days,
        }
    requested = []
    for raw in args:
        key = raw.strip().upper()
        if key in LIVE_TYPES:
            requested.append(key)
    return {
        "mode": "live",
        "types": requested or list(LIVE_TYPES.keys()),
        "repairCanonical": repair_canonical,
        "recentLookbackDays": recent_lookback_days,
    }


# ----- Diem vao CLI -----
# Dieu phoi mode chinh cua file khi duoc Java server hoac terminal goi.
def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    session = create_session()
    cli = parse_cli_args()
    if cli["mode"] == "sync_all":
        payload = sync_all_canonical_csvs(session, cli["types"], recent_lookback_days=cli.get("recentLookbackDays"))
        print(json.dumps(payload, ensure_ascii=False))
        return
    if cli["mode"] == "canonical_history":
        payload = build_canonical_history_payload(
            cli["type"],
            cli["count"],
            repair=cli.get("repairCanonical"),
            recent_lookback_days=cli.get("recentLookbackDays"),
        )
        print(json.dumps(payload, ensure_ascii=False))
        return
    cache = {}
    results = []
    errors = []
    canonical_syncs = []
    canonical_backfill = None
    ai_retrain = None
    scoring_exports = []
    started_at = datetime.now()
    started_monotonic = time.perf_counter()
    progress = None

    if cli.get("repairCanonical"):
        progress = LiveResultsProgressTracker(cli["types"])
        progress.acquire_lock()
        try:
            progress.set_phase(
                "repair_recent",
                current_type="",
                message="Đang cập nhật 6 loại từ MinhChinh.",
            )
            canonical_backfill = sync_requested_canonical_csvs(
                session,
                cli["types"],
                allow_bootstrap=False,
                progress=progress,
                recent_lookback_days=cli.get("recentLookbackDays"),
            )
            skip_train_types = {
                str(item.get("type", "")).strip().upper()
                for item in (canonical_backfill.get("errors") or [])
                if str(item.get("type", "")).strip().upper() in AI_GEN_LOCAL_TRAIN_TYPES
            }
            ai_retrain = retrain_gen_local_models(progress=progress, skip_types=skip_train_types)
            if canonical_backfill is not None:
                canonical_backfill["genLocalRetrain"] = ai_retrain
            results = load_latest_canonical_live_results(cli["types"])
            progress_errors = list(canonical_backfill.get("errors") or [])
            retrain_errors = list((ai_retrain or {}).get("errors") or [])
            if progress_errors or retrain_errors:
                progress.payload["message"] = "Cập nhật xong nhưng còn cảnh báo cần kiểm tra."
            else:
                progress.payload["message"] = "Hoàn Tất Cập Nhật."
            progress.finish(progress.payload["message"])
        except Exception as exc:
            progress.fail(f"Cập nhật bị lỗi: {exc}")
            raise
    else:
        for type_key in cli["types"]:
            try:
                result = fetch_live_result(session, cache, type_key)
                results.append(result)
                canonical_sync = sync_result_to_canonical_csv(result)
                if canonical_sync:
                    canonical_syncs.append(canonical_sync)
                    if canonical_sync.get("new_rows", 0) > 0 or canonical_sync.get("updated_rows", 0) > 0:
                        scoring_exports.append(refresh_scoring_csv_exports([type_key]))
            except Exception as exc:
                errors.append({"key": type_key, "message": str(exc)})

    completed_at = datetime.now()
    payload = {
        "ok": bool(results),
        "fetchedAt": datetime.now().isoformat(timespec="seconds"),
        "startedAt": started_at.isoformat(timespec="seconds"),
        "completedAt": completed_at.isoformat(timespec="seconds"),
        "durationMs": int(round((time.perf_counter() - started_monotonic) * 1000)),
        "results": results,
        "canonicalSyncs": canonical_syncs,
        "canonicalBackfill": canonical_backfill,
        "aiRetrain": ai_retrain,
        "scoringExports": scoring_exports,
        "errors": errors,
    }
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
