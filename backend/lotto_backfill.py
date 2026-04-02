import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import ai.predictors.ai_predict as ap
import ai.configs.data_paths as dp
import backend.live_results as lr


# ----- Cau hinh runner backfill -----
# Khai bao loai ve can backfill, timeout theo tung loai va duong dan log/runtime.
RUNNER_TYPES = ["LOTO_5_35", "LOTO_6_45", "LOTO_6_55", "KENO"]
CANONICAL_TIMEOUT_SECONDS = {
    "LOTO_5_35": 3 * 60 * 60,
    "LOTO_6_45": 3 * 60 * 60,
    "LOTO_6_55": 3 * 60 * 60,
    "KENO": 6 * 60 * 60,
}
SCRIPT_DIR = Path(__file__).resolve().parent
LOG_DIR = dp.RUNTIME_LOG_DIR
LOG_FILE = LOG_DIR / "full_history_backfill.log"
STATUS_FILE = LOG_DIR / "full_history_backfill.status.json"
LOCK_FILE = LOG_DIR / "full_history_backfill.lock"


# ----- Ham tro giup runtime -----
# Gom cac ham lay thoi gian, tao thu muc runtime, doc/ghi JSON va ghi log.
def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def ensure_runtime_paths():
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def append_log(message):
    ensure_runtime_paths()
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(f"[{now_iso()}] {message}\n")


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_status(status):
    ensure_runtime_paths()
    STATUS_FILE.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


# ----- Mau trang thai mac dinh -----
# Tao khung status cho tung buoc canonical/AI de file status luon co cau truc on dinh.
def step_result_template():
    return {
        "ok": None,
        "skipped": False,
        "timeout": False,
        "message": "",
        "updatedAt": "",
        "latestKy": "",
        "earliestKy": "",
        "bootstrapComplete": False,
        "sourceLimited": False,
    }


def build_type_result(type_key):
    return {
        "type": type_key,
        "label": lr.LIVE_TYPES[type_key].label,
        "canonical": step_result_template(),
        "ai": step_result_template(),
    }


# ----- Khoa runner -----
# Dam bao tai mot thoi diem chi co mot job backfill dang chay.
def pid_is_running(pid):
    if not pid or int(pid) <= 0:
        return False
    try:
        os.kill(int(pid), 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def acquire_lock():
    ensure_runtime_paths()
    if LOCK_FILE.exists():
        existing = read_json(LOCK_FILE, {})
        pid = int(existing.get("pid") or 0)
        if pid_is_running(pid):
            return False, existing
        try:
            LOCK_FILE.unlink()
        except OSError:
            pass
    payload = {"pid": os.getpid(), "startedAt": now_iso()}
    LOCK_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, payload


def release_lock():
    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
    except OSError:
        pass


# ----- Danh dau hoan tat va tong hop -----
# Xac dinh type nao da xong va tao payload tong hop de frontend/terminal doc duoc.
def canonical_complete(meta):
    return bool(meta.get("bootstrapComplete")) or bool(meta.get("sourceLimited"))


def ai_complete(meta):
    return bool(meta.get("bootstrapComplete")) or bool(meta.get("sourceLimited"))


def summarize_type(type_key):
    canonical_loader = lr.load_keno_csv_rows if type_key == "KENO" else lr.load_csv_rows
    canonical_rows = canonical_loader(lr.get_canonical_output_paths(type_key)["all"])
    canonical_latest, canonical_earliest = lr.get_latest_and_earliest_rows(canonical_rows)
    canonical_meta = lr.read_canonical_meta(type_key)
    ai_sync = ap.sync_ai_history(type_key)
    return {
        "type": type_key,
        "label": lr.LIVE_TYPES[type_key].label,
        "canonical": {
            "count": len(canonical_rows),
            "latestKy": str(canonical_latest.get("Ky", "")).strip(),
            "earliestKy": str(canonical_earliest.get("Ky", "")).strip(),
            "earliestDate": str(canonical_earliest.get("Ngay", "")).strip(),
            "bootstrapComplete": bool(canonical_meta.get("bootstrapComplete")),
            "sourceLimited": bool(canonical_meta.get("sourceLimited")),
            "lastSyncAt": str(canonical_meta.get("lastSyncAt", "")),
            "lastBootstrapAt": str(canonical_meta.get("lastBootstrapAt", "")),
        },
        "ai": {
            "count": int(ai_sync.get("historyCount", 0)),
            "latestKy": str(ai_sync.get("latestKy", "")).strip(),
            "earliestKy": str(ai_sync.get("effectiveEarliestKy", "")).strip(),
            "earliestDate": str(ai_sync.get("effectiveEarliestDate", "")).strip(),
            "bootstrapComplete": bool(ai_sync.get("bootstrapComplete")),
            "sourceLimited": bool(ai_sync.get("sourceLimited")),
            "lastSyncAt": str(canonical_meta.get("lastSyncAt", "")),
            "lastBootstrapAt": str(canonical_meta.get("lastBootstrapAt", "")),
        },
    }


def build_status(current_type="", current_step="idle", results=None, message="", ok=True):
    payload = {
        "ok": True,
        "mode": "full_history_backfill",
        "updatedAt": now_iso(),
        "logFile": str(LOG_FILE),
        "lockFile": str(LOCK_FILE),
        "currentType": current_type,
        "currentStep": current_step,
        "typeResults": results or {},
        "types": [summarize_type(type_key) for type_key in RUNNER_TYPES],
    }
    payload["ok"] = bool(ok)
    if message:
        payload["message"] = message
    return payload


# ----- Chay lenh phu tro -----
# Goi cac lenh Python con nhan JSON dau ra de backfill va dong bo AI.
def run_json_command(args, timeout_seconds):
    command = [sys.executable, *args]
    completed = subprocess.run(
        command,
        cwd=str(dp.PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
    )
    stdout_text = (completed.stdout or "").strip()
    stderr_text = (completed.stderr or "").strip()
    payload = None
    if stdout_text:
        try:
            payload = json.loads(stdout_text)
        except json.JSONDecodeError:
            payload = {"ok": completed.returncode == 0, "raw": stdout_text}
    else:
        payload = {"ok": completed.returncode == 0, "raw": ""}
    return completed.returncode, payload, stderr_text


# ----- Tung buoc canonical va AI -----
# Moi loai ve se chay dong bo canonical truoc, sau do moi cap nhat phan AI dung chung all_day.
def run_canonical_step(type_key):
    append_log(f"canonical start {type_key}")
    try:
        code, payload, stderr_text = run_json_command(
            [str(dp.BACKEND_DIR / "live_results.py"), "sync_all", type_key],
            CANONICAL_TIMEOUT_SECONDS[type_key],
        )
    except subprocess.TimeoutExpired:
        append_log(f"canonical timeout {type_key}")
        return {
            "ok": False,
            "timeout": True,
            "message": "Canonical sync timeout.",
        }
    if stderr_text:
        append_log(f"canonical stderr {type_key}: {stderr_text}")
    if code != 0 or not payload.get("ok", False):
        append_log(f"canonical failed {type_key}: {json.dumps(payload, ensure_ascii=False)}")
        return {
            "ok": False,
            "timeout": False,
            "message": str((payload or {}).get("message") or stderr_text or "Canonical sync failed."),
        }
    output = (payload.get("outputs") or [{}])[0]
    append_log(
        "canonical done "
        f"{type_key}: all={output.get('allCount', 0)} "
        f"latest={output.get('latestKy', '')} earliest={output.get('effectiveEarliestKy', '')} "
        f"bootstrap={output.get('bootstrapComplete')} sourceLimited={output.get('sourceLimited')}"
    )
    return {
        "ok": True,
        "timeout": False,
        "message": "Canonical sync completed.",
        "latestKy": str(output.get("latestKy", "")).strip(),
        "earliestKy": str(output.get("effectiveEarliestKy", "")).strip(),
        "bootstrapComplete": bool(output.get("bootstrapComplete", False)),
        "sourceLimited": bool(output.get("sourceLimited", False)),
    }


def run_ai_step(type_key):
    append_log(f"ai refresh {type_key}: dùng canonical all_day")
    sync = ap.sync_ai_history(type_key)
    append_log(
        "ai done "
        f"{type_key}: all={sync.get('historyCount', 0)} "
        f"latest={sync.get('latestKy', '')} earliest={sync.get('effectiveEarliestKy', '')} "
        f"bootstrap={sync.get('bootstrapComplete')} sourceLimited={sync.get('sourceLimited')}"
    )
    return {
        "ok": True,
        "timeout": False,
        "message": "AI dùng chung canonical all_day.",
        "latestKy": str(sync.get("latestKy", "")).strip(),
        "earliestKy": str(sync.get("effectiveEarliestKy", "")).strip(),
        "bootstrapComplete": bool(sync.get("bootstrapComplete", False)),
        "sourceLimited": bool(sync.get("sourceLimited", False)),
    }


# ----- Luong chay chinh -----
# Dieu phoi thu tu tung loai, cap nhat status lien tuc va ghi lai ket qua sau moi buoc.
def record_step_result(results, type_key, step_key, result):
    bucket = results.setdefault(type_key, build_type_result(type_key))[step_key]
    bucket.update(step_result_template())
    bucket.update(result or {})
    bucket["updatedAt"] = now_iso()
    return bucket


def mark_skipped_result(results, type_key, step_key, message, meta):
    return record_step_result(results, type_key, step_key, {
        "ok": True,
        "skipped": True,
        "timeout": False,
        "message": message,
        "latestKy": "",
        "earliestKy": str(meta.get("effectiveEarliestKy", "")).strip(),
        "bootstrapComplete": bool(meta.get("bootstrapComplete", False)),
        "sourceLimited": bool(meta.get("sourceLimited", False)),
    }) 


def run():
    locked, existing = acquire_lock()
    if not locked:
        status = build_status(message="Backfill runner đang chạy ở tiến trình khác.", ok=False)
        status["lock"] = existing
        write_status(status)
        print(json.dumps(status, ensure_ascii=False))
        return 1

    append_log("runner start")
    results = {type_key: build_type_result(type_key) for type_key in RUNNER_TYPES}
    write_status(build_status("", "starting", results=results))
    try:
        for type_key in RUNNER_TYPES:
            write_status(build_status(type_key, "canonical", results=results))
            canonical_meta = lr.read_canonical_meta(type_key)
            if canonical_complete(canonical_meta):
                append_log(f"canonical skip {type_key}: already complete")
                mark_skipped_result(
                    results,
                    type_key,
                    "canonical",
                    "Canonical full-history đã hoàn tất từ trước.",
                    canonical_meta,
                )
            else:
                record_step_result(results, type_key, "canonical", run_canonical_step(type_key))
            write_status(build_status(type_key, "ai", results=results))
            ai_meta = lr.read_canonical_meta(type_key)
            if ai_complete(ai_meta):
                append_log(f"ai skip {type_key}: already complete")
                mark_skipped_result(
                    results,
                    type_key,
                    "ai",
                    "AI dùng canonical all_day và đã sẵn sàng từ trước.",
                    ai_meta,
                )
            else:
                record_step_result(results, type_key, "ai", run_ai_step(type_key))
            write_status(build_status(type_key, "completed", results=results))
            time.sleep(1.0)
        append_log("runner end")
        all_ok = all(
            step.get("ok") is not False
            for item in results.values()
            for step in (item["canonical"], item["ai"])
        )
        final_status = build_status(
            "",
            "completed",
            results=results,
            message="Backfill runner đã hoàn tất một vòng." if all_ok else "Backfill runner đã hoàn tất một vòng, nhưng có bước lỗi hoặc timeout.",
            ok=all_ok,
        )
        write_status(final_status)
        print(json.dumps(final_status, ensure_ascii=False))
        return 0 if all_ok else 1
    except Exception as exc:
        append_log(f"runner fatal error: {exc}")
        failed_status = build_status(
            "",
            "failed",
            results=results,
            message=f"Runner gặp lỗi ngoài dự kiến: {exc}",
            ok=False,
        )
        write_status(failed_status)
        print(json.dumps(failed_status, ensure_ascii=False))
        return 1
    finally:
        release_lock()


# ----- Xem trang thai hien tai -----
# In ra file status da tong hop ma khong can chay lai ca runner.
def status():
    lock_payload = read_json(LOCK_FILE, {})
    lock_pid = int((lock_payload or {}).get("pid") or 0)
    lock_active = pid_is_running(lock_pid)
    if LOCK_FILE.exists() and not lock_active:
        try:
            LOCK_FILE.unlink()
        except OSError:
            pass
    payload = None if not lock_active else read_json(STATUS_FILE, None)
    if not isinstance(payload, dict):
        payload = build_status("", "status")
    payload["updatedAt"] = now_iso()
    payload["lockActive"] = lock_active
    print(json.dumps(payload, ensure_ascii=False))
    return 0


# ----- Diem vao CLI -----
# Cho phep goi file theo 2 che do: chay runner hoac chi xem status.
def main():
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    mode = str(sys.argv[1] if len(sys.argv) > 1 else "run").strip().lower()
    if mode == "status":
        raise SystemExit(status())
    raise SystemExit(run())


if __name__ == "__main__":
    main()
