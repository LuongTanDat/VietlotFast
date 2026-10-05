"""Prospective, equal-budget comparison of the real web pipeline and fixed baselines.

Only future predictions are recorded. Reports never fabricate historical forecasts,
rescore personal runs, fit a model, or promote a registry candidate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sqlite3
import sys
import uuid
from contextlib import closing, redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from statistics import mean
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai import ml_pipeline, prediction_ledger as ledger
from ai.configs import data_paths as dp
from ai.evaluation.statistical_tests import paired_bootstrap_ci
from ai.prizes import RULE_VERSION as PRIZE_RULE_VERSION, PRIZE_SCOPE, classify_tickets, prize_counts, prize_statistics
from backend.file_guard import resource_lock, version

GAMES = ("LOTO_5_35", "LOTO_6_45", "LOTO_6_55")
METHODS = {"web": "Luồng dự đoán web", "random": "Ngẫu nhiên", "bayesian": "Bayesian", "ewma": "EWMA"}
ACTOR = ledger.EFFECTIVENESS_SYSTEM_ACTOR
PIPELINE = "prospective_equal_budget_v1"
LOCAL_TZ = timezone(timedelta(hours=7))
PRIOR_STRENGTH = 100.0
HALF_LIFE = 60.0


def _game(value: str) -> str:
    value = str(value or "").strip().upper()
    if value not in GAMES:
        raise ValueError("Hiệu quả dự đoán chỉ hỗ trợ Loto 5/35, Mega 6/45 và Power 6/55.")
    return value


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _digest(value: Any) -> str:
    return hashlib.sha256(ledger.canonical_json(value).encode("utf-8")).hexdigest()


def _connect(db_path=None):
    connection = ledger.connect(db_path)
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS effectiveness_settings (
            game_type TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
            ticket_count INTEGER NOT NULL DEFAULT 3 CHECK(ticket_count BETWEEN 1 AND 10),
            updated_at TEXT NOT NULL DEFAULT '', updated_by TEXT NOT NULL DEFAULT '',
            last_tick TEXT NOT NULL DEFAULT '', last_error TEXT NOT NULL DEFAULT '',
            next_target TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS effectiveness_cycles (
            cycle_id TEXT PRIMARY KEY, game_type TEXT NOT NULL, target_draw_id TEXT NOT NULL,
            cutoff_draw_id TEXT NOT NULL, created_at TEXT NOT NULL, deadline TEXT NOT NULL,
            data_hash TEXT NOT NULL, source_version_json TEXT NOT NULL,
            config_json TEXT NOT NULL, UNIQUE(game_type,target_draw_id)
        );
        CREATE TABLE IF NOT EXISTS effectiveness_predictions (
            cycle_id TEXT NOT NULL REFERENCES effectiveness_cycles(cycle_id),
            method TEXT NOT NULL CHECK(method IN ('web','random','bayesian','ewma')),
            prediction_id TEXT NOT NULL UNIQUE REFERENCES prediction_runs(prediction_id),
            PRIMARY KEY(cycle_id,method)
        );
        CREATE TABLE IF NOT EXISTS effectiveness_config_audit (
            event_id TEXT PRIMARY KEY, game_type TEXT NOT NULL, actor TEXT NOT NULL,
            created_at TEXT NOT NULL, settings_json TEXT NOT NULL
        );
        CREATE TRIGGER IF NOT EXISTS effectiveness_cycle_immutable
        BEFORE UPDATE ON effectiveness_cycles BEGIN
            SELECT RAISE(ABORT,'prospective cycle is immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS effectiveness_mapping_immutable
        BEFORE UPDATE ON effectiveness_predictions BEGIN
            SELECT RAISE(ABORT,'prospective mapping is immutable');
        END;
    """)
    for game in GAMES:
        connection.execute("INSERT OR IGNORE INTO effectiveness_settings(game_type) VALUES(?)", (game,))
    return connection


def _settings(row) -> dict:
    return {"enabled": bool(row["enabled"]), "ticketCount": int(row["ticket_count"]),
            "engine": "classic", "riskMode": "balanced", "predictionMode": "normal",
            "bayesianPrior": PRIOR_STRENGTH, "ewmaHalfLife": HALF_LIFE,
            "updatedAt": row["updated_at"], "updatedBy": row["updated_by"]}


def settings(game: str, db_path=None) -> dict:
    game = _game(game)
    with closing(_connect(db_path)) as connection:
        row = connection.execute("SELECT * FROM effectiveness_settings WHERE game_type=?", (game,)).fetchone()
        return {"ok": True, "type": game, "settings": _settings(row)}


def configure(game: str, enabled: bool, ticket_count: int = 3, actor: str = "", db_path=None) -> dict:
    game = _game(game)
    if not isinstance(enabled, bool) or type(ticket_count) is not int or not 1 <= ticket_count <= 10:
        raise ValueError("Bật/tắt phải là boolean và số vé phải trong khoảng 1–10.")
    if not str(actor).strip():
        raise ValueError("Thiếu tài khoản quản trị thay đổi cấu hình.")
    with closing(_connect(db_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute("UPDATE effectiveness_settings SET enabled=?,ticket_count=?,updated_at=?,updated_by=? WHERE game_type=?",
                               (int(enabled), int(ticket_count), ledger.now_iso(), actor, game))
            row = connection.execute("SELECT * FROM effectiveness_settings WHERE game_type=?", (game,)).fetchone()
            result = _settings(row)
            connection.execute("INSERT INTO effectiveness_config_audit VALUES(?,?,?,?,?)",
                               (str(uuid.uuid4()), game, actor, ledger.now_iso(), ledger.canonical_json(result)))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {"ok": True, "type": game, "settings": result,
            "note": "Cấu hình chỉ áp dụng kỳ chưa khóa; thay đổi không tạo lại bộ số cùng kỳ."}


def _draw_at(row: dict, game: str) -> datetime:
    date_text = str(row.get("date") or "").strip()
    day = None
    for pattern in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            day = datetime.strptime(date_text, pattern)
            break
        except ValueError:
            pass
    slot = str(row.get("time") or ("18:00" if game != "LOTO_5_35" else "")).strip()
    if day is None or not slot:
        raise ValueError("Không xác minh được ngày/giờ kỳ canonical.")
    try:
        hour, minute = [int(item) for item in slot.split(":")]
        result = day.replace(hour=hour, minute=minute, tzinfo=LOCAL_TZ)
    except (ValueError, TypeError):
        raise ValueError("Giờ canonical không hợp lệ.")
    if game == "LOTO_5_35" and (hour, minute) not in ((13, 0), (21, 0)):
        raise ValueError("Giờ Loto 5/35 phải là 13:00 hoặc 21:00.")
    if game != "LOTO_5_35" and (hour, minute) != (18, 0):
        raise ValueError("Giờ Mega/Power phải là 18:00.")
    return result


def _validate_actual_row(row: dict, game: str):
    cfg = ml_pipeline.game_config(game)
    main = row.get("main") or []
    if len(main) != cfg["draw_size"] or len(set(main)) != len(main) or any(type(n) is not int or not 1 <= n <= cfg["universe_size"] for n in main):
        raise ValueError("Bộ số canonical không hợp lệ.")
    special = row.get("special")
    if game == "LOTO_5_35" and (type(special) is not int or not 1 <= special <= 12):
        raise ValueError("Số đặc biệt canonical Loto 5/35 không hợp lệ.")
    if game == "LOTO_6_55" and (type(special) is not int or not 1 <= special <= 55 or special in main):
        raise ValueError("Số thứ bảy canonical Power không hợp lệ.")
    if game == "LOTO_6_45" and special is not None:
        raise ValueError("Canonical Mega không có số đặc biệt.")


def _snapshot(game: str) -> dict:
    path = dp.get_canonical_csv_read_path(game)
    initial = version(path)
    if initial is None:
        raise ValueError("Chưa có lịch sử canonical.")
    actual = ml_pipeline.load_actual_draws(game)
    if version(path) != initial:
        raise RuntimeError("Canonical thay đổi trong lúc đọc; thử lại sau.")
    if not actual:
        raise ValueError("Lịch sử canonical rỗng.")
    draws = sorted(actual.values(), key=lambda row: int(row["ky"]))
    for row in draws:
        _validate_actual_row(row, game)
        if _draw_at(row, game) > _now():
            raise ValueError("Canonical chứa kỳ có thời gian tương lai.")
    latest = draws[-1]
    latest_at = _draw_at(latest, game)
    if game == "LOTO_5_35":
        deadline = latest_at.replace(hour=21) if latest_at.hour == 13 else (latest_at + timedelta(days=1)).replace(hour=13)
    else:
        weekdays = {"LOTO_6_45": {2, 4, 6}, "LOTO_6_55": {1, 3, 5}}[game]
        deadline = (latest_at + timedelta(days=1)).replace(hour=18, minute=0)
        while deadline.weekday() not in weekdays:
            deadline += timedelta(days=1)
    return {"draws": draws, "actual": actual, "path": path, "version": initial,
            "dataHash": _digest(draws), "cutoff": str(int(latest["ky"])),
            "target": str(int(latest["ky"]) + 1), "deadline": deadline}


def _guard(snapshot: dict):
    if _now() >= snapshot["deadline"]:
        raise ValueError("Kỳ mục tiêu đã đến giờ quay. Cập nhật kết quả canonical trước khi khóa kỳ tiếp theo.")
    if int(snapshot["target"]) <= int(snapshot["cutoff"]) or snapshot["target"] in snapshot["actual"]:
        raise ValueError("Kỳ mục tiêu đã có kết quả hoặc không sau cutoff.")


def _execution_manifest(game: str) -> dict:
    paths = [dp.PROJECT_ROOT / "ai/predictors/ai_predict.py", dp.PROJECT_ROOT / "ai/adaptive_coverage.py",
             Path(__file__)]
    paths += [path for path in (dp.MODELS_DIR / game).glob("*.json") if path.is_file()]
    return {str(path.relative_to(dp.PROJECT_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths if path.is_file()}


def _production_web_prediction(game: str, count: int, snapshot: dict) -> dict:
    # Pin both classic history and registry's canonical read to the same verified
    # snapshot. The scoring/fallback/Adaptive Coverage pipeline itself is unchanged.
    # Each invocation runs in its own CLI process, so these overrides cannot affect
    # an unrelated live user's prediction process.
    from ai.predictors import ai_predict as predictor
    from unittest.mock import patch
    draws = [{**row, "date_obj": _draw_at(row, game).date(), "weekday": _draw_at(row, game).weekday()}
             for row in snapshot["draws"]]
    summary = predictor.build_readonly_sync_summary(game)
    with patch.object(predictor, "sync_ai_history", return_value=summary), \
            patch.object(predictor, "load_ai_draws", return_value=draws), \
            patch.object(ml_pipeline, "load_actual_draws", return_value=snapshot["actual"]):
        return predictor.predict_json(game, count, engine="classic", risk_mode="balanced",
                                      prediction_mode="normal", username=ACTOR, lock_ledger=False)


def _seed(game: str, method: str, snapshot: dict, count: int) -> int:
    return int(_digest({"game": game, "method": method, "target": snapshot["target"],
                        "dataHash": snapshot["dataHash"], "count": count, "pipeline": PIPELINE})[:12], 16) % 2147483647


def _baseline(game: str, method: str, count: int, snapshot: dict) -> dict:
    cfg = ml_pipeline.game_config(game)
    size, draw_size = cfg["universe_size"], cfg["draw_size"]
    prior = draw_size / size
    probabilities = {n: prior for n in range(1, size + 1)}
    if method != "random":
        weights = [1.0 if method == "bayesian" else 2 ** (-age / HALF_LIFE)
                   for age in range(len(snapshot["draws"]) - 1, -1, -1)]
        counts = {n: 0.0 for n in probabilities}
        for row, weight in zip(snapshot["draws"], weights):
            for number in row["main"]:
                counts[number] += weight
        denominator = sum(weights) + PRIOR_STRENGTH
        probabilities = {n: (counts[n] + PRIOR_STRENGTH * prior) / denominator for n in counts}
    seed = _seed(game, method, snapshot, count)
    rng = random.Random(seed)
    tickets, seen = [], set()
    for index in range(count):
        for attempt in range(100):
            if method == "random":
                main = sorted(rng.sample(range(1, size + 1), draw_size))
            elif index == 0 and attempt == 0:
                main = sorted(sorted(probabilities, key=lambda n: (-probabilities[n], n))[:draw_size])
            else:
                main = sorted(sorted(probabilities, key=lambda n: -math.log(max(rng.random(), 1e-12)) / probabilities[n])[:draw_size])
            if tuple(main) not in seen:
                break
        else:
            raise RuntimeError("Không tạo được danh mục vé khác nhau.")
        seen.add(tuple(main))
        special = rng.randrange(1, 13) if game == "LOTO_5_35" else (
            rng.choice([n for n in range(1, 56) if n not in main]) if game == "LOTO_6_55" else None)
        tickets.append({"main": main, "special": special})
    return {"ok": True, "ready": True, "type": game, "engine": method, "predictionMode": "normal",
            "latestKy": snapshot["cutoff"], "nextKy": snapshot["target"], "pickSize": draw_size,
            "tickets": tickets, "probabilities": {str(n): p for n, p in probabilities.items()},
            "randomSeed": seed, "modelId": f"{method}_{PIPELINE}", "modelVersion": PIPELINE,
            "probabilityCalibrationStatus": "uncalibrated", "evaluationScope": "main_numbers_only"}


def _validate(payload: dict, game: str, count: int, snapshot: dict):
    cfg = ml_pipeline.game_config(game)
    if payload.get("ready") is False or payload.get("ok") is False:
        raise ValueError("Luồng web chưa sẵn sàng; chưa khóa đối chứng đơn lẻ.")
    cutoff = str(payload.get("data_cutoff_draw_id") or payload.get("latestKy") or "").lstrip("#")
    target = str(payload.get("target_draw_id") or payload.get("nextKy") or "").lstrip("#")
    if str(payload.get("type")) != game or cutoff != snapshot["cutoff"] or target != snapshot["target"]:
        raise ValueError("Luồng dự đoán dùng cutoff/kỳ khác canonical.")
    tickets = payload.get("tickets") or []
    if len(tickets) != count:
        raise ValueError("Các phương pháp phải có cùng số vé.")
    for ticket in tickets:
        main = ticket.get("main") or []
        if len(main) != cfg["draw_size"] or len(set(main)) != len(main) or any(type(n) is not int or not 1 <= n <= cfg["universe_size"] for n in main):
            raise ValueError("Bộ số dự đoán không hợp lệ.")
        special = ticket.get("special")
        if game == "LOTO_5_35" and (type(special) is not int or not 1 <= special <= 12):
            raise ValueError("Số đặc biệt Loto 5/35 không hợp lệ.")
        if game == "LOTO_6_55" and (type(special) is not int or not 1 <= special <= 55 or special in main):
            raise ValueError("Số đặc biệt Power 6/55 không hợp lệ.")
        if game == "LOTO_6_45" and special is not None:
            raise ValueError("Mega không có số đặc biệt.")
    probs = ledger.normalize_probability_payload(payload.get("probabilities") or {})
    if set(probs) != set(range(1, cfg["universe_size"] + 1)) or any(not math.isfinite(p) or not 0 <= p <= 1 for p in probs.values()):
        raise ValueError("Vector xác suất thiếu số hoặc không hữu hạn.")
    if abs(sum(probs.values()) - cfg["draw_size"]) > 1e-5:
        raise ValueError("Tổng xác suất biên không khớp cỡ kỳ quay.")


def _cycle_rows(connection, game: str):
    return connection.execute("SELECT * FROM effectiveness_cycles WHERE game_type=? ORDER BY CAST(target_draw_id AS INTEGER) DESC", (game,)).fetchall()


def cycle(game: str, db_path=None, force=True) -> dict:
    game = _game(game)
    database = Path(db_path or ledger.DEFAULT_DB_PATH)
    with resource_lock(database.parent / f"effectiveness_{game.lower()}", timeout=15):
        with closing(_connect(db_path)) as connection:
            row = connection.execute("SELECT * FROM effectiveness_settings WHERE game_type=?", (game,)).fetchone()
            configuration = _settings(row)
            if not configuration["enabled"] and not force:
                return {"ok": True, "type": game, "status": "disabled"}
            snapshot = _snapshot(game)
            existing = connection.execute("SELECT cycle_id FROM effectiveness_cycles WHERE game_type=? AND target_draw_id=?",
                                          (game, snapshot["target"])).fetchone()
            if existing:
                return {"ok": True, "type": game, "status": "already_locked", "cycleId": existing[0], "targetDrawId": snapshot["target"]}
            _guard(snapshot)
            count = configuration["ticketCount"]
            manifest = _execution_manifest(game)
            payloads = {"web": _production_web_prediction(game, count, snapshot)}
            payloads["web"] = dict(payloads["web"])
            if (payloads["web"].get("adaptiveCoverage") or {}).get("seed") is not None:
                payloads["web"]["randomSeed"] = int(payloads["web"]["adaptiveCoverage"]["seed"])
            for method in ("random", "bayesian", "ewma"):
                payloads[method] = _baseline(game, method, count, snapshot)
            for payload in payloads.values():
                _validate(payload, game, count, snapshot)
            with resource_lock(snapshot["path"]):
                fresh = _snapshot(game)
                if fresh["version"] != snapshot["version"] or fresh["dataHash"] != snapshot["dataHash"]:
                    raise RuntimeError("Canonical thay đổi trong khi tạo dự đoán; hủy toàn bộ chu kỳ và thử lại.")
                if _execution_manifest(game) != manifest:
                    raise RuntimeError("Mã/model thay đổi trong khi dự đoán; chưa khóa chu kỳ.")
                _guard(fresh)
                config = {**configuration, "pipeline": PIPELINE, "sourceManifest": manifest,
                          "scope": "main_numbers_only", "specialBaseline": "uniform_seeded",
                          "actualWebEngine": payloads["web"].get("engine"), "actualWebModelId": payloads["web"].get("modelId")}
                config_hash = _digest(config)
                created_at, cycle_id = ledger.now_iso(), str(uuid.uuid4())
                connection.execute("BEGIN IMMEDIATE")
                try:
                    _guard(fresh)
                    # Recheck settings to avoid silently recording the old budget
                    # if an admin changed it while generation was running.
                    current = connection.execute("SELECT * FROM effectiveness_settings WHERE game_type=?", (game,)).fetchone()
                    if _settings(current) != configuration:
                        raise RuntimeError("Cấu hình thay đổi trong lúc dự đoán; thử lại.")
                    connection.execute("INSERT INTO effectiveness_cycles VALUES(?,?,?,?,?,?,?,?,?)",
                                       (cycle_id, game, snapshot["target"], snapshot["cutoff"], created_at,
                                        snapshot["deadline"].isoformat(timespec="seconds"), snapshot["dataHash"],
                                        ledger.canonical_json(snapshot["version"]), ledger.canonical_json(config)))
                    for method, payload in payloads.items():
                        payload = {**payload, "predictionDeadline": snapshot["deadline"].isoformat(timespec="seconds"),
                                   "dataHash": snapshot["dataHash"], "configHash": config_hash,
                                   "effectivenessMethod": method, "effectivenessCycleId": cycle_id,
                                   "executionManifest": manifest if method == "web" else {}, "evaluationScope": "main_numbers_only"}
                        if not payload.get("modelId"):
                            payload["modelId"] = f"execution_effectiveness_{_digest(manifest)[:20]}"
                        locked = ledger.lock_prediction(payload, username=ACTOR, connection=connection,
                                                        random_seed=int(payload.get("randomSeed") or _seed(game, method, snapshot, count)))
                        connection.execute("INSERT INTO effectiveness_predictions VALUES(?,?,?)", (cycle_id, method, locked["prediction_id"]))
                    _guard(snapshot)
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
            return {"ok": True, "type": game, "status": "locked", "cycleId": cycle_id,
                    "targetDrawId": snapshot["target"], "cutoffDrawId": snapshot["cutoff"], "ticketCount": count}


def score_cycles(game: str, db_path=None) -> dict:
    """Score only our own complete four-way mappings using ledger v2 metrics."""
    game = _game(game)
    actual = ml_pipeline.load_actual_draws(game)
    cfg = ml_pipeline.game_config(game)
    scored, errors = [], []
    with closing(_connect(db_path)) as connection:
        for cycle_row in _cycle_rows(connection, game):
            target = cycle_row["target_draw_id"]
            if target not in actual:
                continue
            try:
                _validate_actual_row(actual[target], game)
                actual_at = _draw_at(actual[target], game)
                if actual_at > _now():
                    continue
                if actual_at != datetime.fromisoformat(cycle_row["deadline"]):
                    raise ValueError("Ngày/giờ kết quả không khớp kỳ đã khóa.")
            except Exception as exc:
                errors.append({"targetDrawId": target, "error": str(exc)})
                continue
            rows = connection.execute("SELECT ep.method,pr.* FROM effectiveness_predictions ep JOIN prediction_runs pr ON pr.prediction_id=ep.prediction_id WHERE ep.cycle_id=?", (cycle_row["cycle_id"],)).fetchall()
            if len(rows) != 4 or {row["method"] for row in rows} != set(METHODS):
                errors.append({"targetDrawId": target, "error": "Chu kỳ không đủ bốn phương pháp."})
                continue
            if all(row["status"] == "scored" for row in rows):
                continue
            try:
                connection.execute("BEGIN IMMEDIATE")
                for row in rows:
                    payload = json.loads(row["payload_json"])
                    if ledger.payload_checksum(payload) != row["payload_checksum"]:
                        raise ValueError("Checksum dự đoán không khớp.")
                    if row["username"] != ACTOR or row["status"] not in ("locked", "scored"):
                        raise ValueError("Run không thuộc chu kỳ hệ thống hợp lệ.")
                    metrics = ledger.score_prediction_payload(payload, actual[target], cfg["universe_size"], cfg["draw_size"], cfg["prediction_size"])
                    connection.execute("INSERT OR IGNORE INTO prediction_scores VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                       (str(uuid.uuid4()), row["prediction_id"], ledger.now_iso(), target,
                                        metrics["hit_count"], metrics["special_hit"], metrics["brier_score"], metrics["log_loss"],
                                        metrics["lift"], ledger.canonical_json(metrics), ledger.SCORING_VERSION))
                    connection.execute("UPDATE prediction_runs SET status='scored' WHERE prediction_id=? AND status='locked'", (row["prediction_id"],))
                connection.commit()
                scored.append(target)
            except Exception as exc:
                connection.rollback()
                errors.append({"targetDrawId": target, "error": str(exc)})
    return {"ok": not errors, "type": game, "scored": scored, "errors": errors}


def _summary(method: str, samples: list[dict], random_samples: list[dict], cfg: dict) -> dict:
    count = len(samples)
    hits = [sample["meanHits"] for sample in samples]
    base_hits = [sample["meanHits"] for sample in random_samples]
    ci = paired_bootstrap_ci(hits, base_hits, iterations=2000) if count else None
    expected = cfg["prediction_size"] * cfg["draw_size"] / cfg["universe_size"]
    histogram = {str(n): sum(sample["hitHistogram"].get(str(n), 0) for sample in samples)
                 for n in range(cfg["draw_size"] + 1)}
    decision = "baseline" if method == "random" else ("insufficient_evidence" if count < 30 else (
        "possible_improvement" if ci["lower"] > 0 else "no_clear_advantage"))
    results = [result for sample in samples for result in sample.get("ticketResults", [])]
    return {"key": method, "label": METHODS[method], "sampleCount": count,
            "meanHits": mean(hits) if count else None, "brierScore": mean(s["brierScore"] for s in samples) if count else None,
            "logLoss": mean(s["logLoss"] for s in samples) if count else None,
            "rate3": mean(s["rate3"] for s in samples) if count else None,
            "rate4": mean(s["rate4"] for s in samples) if count else None,
            "lift": mean(hits) / expected - 1 if count else None,
            "deltaVsRandom": ci["mean"] if ci else None,
            "ci95": {"lower": ci["lower"], "upper": ci["upper"]} if ci else None,
            "hitHistogram": histogram, "decision": decision,
            "prizeCounts": prize_counts(results), "prizeStatistics": prize_statistics(results)}


def report(game: str, limit: int = 100, db_path=None) -> dict:
    game = _game(game)
    limit = max(1, min(1000, int(limit)))
    samples = {method: [] for method in METHODS}
    cycles = []
    with closing(_connect(db_path)) as connection:
        settings_row = connection.execute("SELECT * FROM effectiveness_settings WHERE game_type=?", (game,)).fetchone()
        rows = _cycle_rows(connection, game)
        for row in rows:
            predictions = connection.execute("""SELECT ep.method,pr.*,ps.metrics_json,ps.brier_score,ps.log_loss,
                ps.scoring_version FROM effectiveness_predictions ep
                JOIN prediction_runs pr ON pr.prediction_id=ep.prediction_id
                LEFT JOIN prediction_scores ps ON ps.prediction_id=pr.prediction_id AND ps.scoring_version=?
                WHERE ep.cycle_id=?""", (ledger.SCORING_VERSION, row["cycle_id"])).fetchall()
            if len(predictions) != 4 or {p["method"] for p in predictions} != set(METHODS):
                continue
            complete = all(p["status"] == "scored" and p["metrics_json"] for p in predictions)
            recorded = [json.loads(p["metrics_json"]) for p in predictions] if complete else []
            same_main = bool(recorded) and all(m.get("actual_main") == recorded[0].get("actual_main") for m in recorded)
            same_special = bool(recorded) and all(m.get("actual_special") == recorded[0].get("actual_special") for m in recorded)
            actual_main = recorded[0].get("actual_main", []) if same_main else []
            actual_special = recorded[0].get("actual_special") if same_special else None
            item = {"cycleId": row["cycle_id"], "targetDrawId": row["target_draw_id"], "cutoffDrawId": row["cutoff_draw_id"],
                    "createdAt": row["created_at"], "deadline": row["deadline"], "dataHash": row["data_hash"],
                    "status": "scored" if complete else "locked", "actualMain": actual_main,
                    "actualSpecial": actual_special, "actualSpecialStatus": "not_applicable" if game == "LOTO_6_45" else (
                        "recorded" if complete and same_special and type(actual_special) is int else "missing" if complete else "pending"),
                    "actualSource": "recorded_ledger_score" if complete else "pending", "methods": {},
                    "config": json.loads(row["config_json"])}
            for prediction in predictions:
                method = prediction["method"]
                metrics = json.loads(prediction["metrics_json"] or "{}") if complete else {}
                payload = json.loads(prediction["payload_json"])
                method_row = {"predictionId": prediction["prediction_id"], "tickets": json.loads(prediction["tickets_json"]),
                              "engine": prediction["engine"], "modelId": prediction["model_id"], "status": prediction["status"],
                              "meanHits": metrics.get("mean_hits_per_ticket"), "bestHits": metrics.get("hit_count"),
                              "brierScore": prediction["brier_score"] if complete else None,
                              "logLoss": prediction["log_loss"] if complete else None,
                              "seed": prediction["random_seed"], "calibrationStatus": payload.get("probabilityCalibrationStatus", "uncalibrated")}
                # Classification uses only the immutable score's recorded result;
                # never fill an old missing special ball from today's CSV.
                recorded_actual = {"main": actual_main, "special": actual_special} if complete else None
                ticket_results = classify_tickets(game, method_row["tickets"], recorded_actual)
                method_row.update({"ticketResults": ticket_results, "prizeCounts": prize_counts(ticket_results),
                                   "prizeStatistics": prize_statistics(ticket_results), "prizeSource": item["actualSource"]})
                if complete:
                    ticket_hits = [ticket["hit_count"] for ticket in metrics["per_ticket"]]
                    method_row.update({"rate3": sum(hit >= 3 for hit in ticket_hits) / len(ticket_hits),
                                       "rate4": sum(hit >= 4 for hit in ticket_hits) / len(ticket_hits),
                                       "hitHistogram": {str(n): ticket_hits.count(n) for n in range(ml_pipeline.game_config(game)["draw_size"] + 1)}})
                    samples[method].append(method_row)
                item["methods"][method] = method_row
            cycles.append(item)
        scored = len(samples["web"])
        configurations = {_digest({key: item["config"].get(key) for key in
                                   ("ticketCount", "actualWebEngine", "actualWebModelId", "sourceManifest", "pipeline")})
                          for item in cycles}
        return {"ok": True, "type": game, "label": ml_pipeline.game_config(game)["label"], "settings": _settings(settings_row),
                "counts": {"locked": len(cycles) - scored, "scored": scored, "total": len(cycles)},
                "methods": [_summary(method, samples[method], samples["random"], ml_pipeline.game_config(game)) for method in METHODS],
                "cycles": cycles[:limit], "scope": "main_numbers_only", "metricWeighting": "equal_weight_per_draw",
                "prizeScope": PRIZE_SCOPE, "prizeRuleVersion": PRIZE_RULE_VERSION,
                "configurationCount": len(configurations), "mixedConfigurations": len(configurations) > 1,
                "automation": {"lastError": settings_row["last_error"], "lastTick": settings_row["last_tick"],
                               "nextTargetDrawId": settings_row["next_target"]},
                "notes": ["Chỉ đánh giá kỳ đã khóa trước giờ quay; không dựng lại dự đoán lịch sử.",
                          "So bốn phương pháp cùng kỳ và cùng số vé. Số trùng/Brier/CI vẫn chấm số chính; nhãn giải chấm riêng theo thể lệ vé chuẩn.",
                          "Giải dựa trên kết quả đã lưu lúc chấm; thiếu ĐB cũ ghi chưa xác định, không bổ sung từ CSV hiện tại. Số đặc biệt đối chứng lấy ngẫu nhiên.",
                          "Jackpot 2 Power cần trùng 5 số chính và số thứ bảy thực tế nằm trong 6 số của vé; số phụ dự đoán không quyết định giải.",
                          "Brier/log loss dùng xác suất biên chưa hiệu chỉnh. CI bootstrap ghép cặp theo kỳ, chưa điều chỉnh thử nhiều phương pháp.",
                          "Dưới 30 kỳ hoặc CI chứa 0: chưa đủ bằng chứng lợi thế. Kết quả quá khứ không bảo đảm kỳ sau."]}


def tick(db_path=None) -> dict:
    results = []
    for game in GAMES:
        error = ""
        try:
            scoring = score_cycles(game, db_path)
            if not scoring["ok"]:
                error = "; ".join(item["error"] for item in scoring["errors"])
            action = cycle(game, db_path, force=False)
            result = {"ok": not error, "type": game, "scoring": scoring, "cycle": action}
            target = action.get("targetDrawId", "")
        except Exception as exc:
            error, target = str(exc), ""
            result = {"ok": False, "type": game, "error": error}
        with closing(_connect(db_path)) as connection:
            connection.execute("UPDATE effectiveness_settings SET last_tick=?,last_error=?,next_target=? WHERE game_type=?",
                               (ledger.now_iso(), error, target, game))
        results.append(result)
    return {"ok": True, "results": results}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("report", "settings", "configure", "cycle", "tick"):
        child = sub.add_parser(command)
        if command != "tick":
            child.add_argument("game", choices=GAMES)
        child.add_argument("--db-path", default=None, help=argparse.SUPPRESS)
        if command == "report":
            child.add_argument("--limit", type=int, default=100)
        if command == "configure":
            child.add_argument("--enabled", choices=("true", "false"), required=True)
            child.add_argument("--ticket-count", type=int, default=3)
            child.add_argument("--actor", required=True)
    args = parser.parse_args(argv)
    try:
        # Keep stdout exclusively JSON even if a legacy engine prints a diagnostic.
        with redirect_stdout(StringIO()):
            if args.command == "report": result = report(args.game, args.limit, args.db_path)
            elif args.command == "settings": result = settings(args.game, args.db_path)
            elif args.command == "configure": result = configure(args.game, args.enabled == "true", args.ticket_count, args.actor, args.db_path)
            elif args.command == "cycle":
                score_cycles(args.game, args.db_path)
                result = cycle(args.game, args.db_path)
            else: result = tick(args.db_path)
    except Exception as exc:
        result = {"ok": False, "type": getattr(args, "game", ""), "error": str(exc), "message": str(exc)}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
