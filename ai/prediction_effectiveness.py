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
from ai import tracking_portfolio as portfolio
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
    if value not in (*GAMES, "KENO"):
        raise ValueError("Hiệu quả dự đoán hỗ trợ Loto 5/35, Mega 6/45, Power 6/55 và Keno.")
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
            ticket_count INTEGER NOT NULL DEFAULT 3 CHECK(ticket_count BETWEEN 1 AND 10000),
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
    # Rebuild only the mutable settings table; forecasts and audits stay intact.
    schema = connection.execute("SELECT sql FROM sqlite_master WHERE name='effectiveness_settings'").fetchone()[0]
    if "BETWEEN 1 AND 10)" in schema:
        connection.execute("BEGIN IMMEDIATE")
        try:
            schema = connection.execute("SELECT sql FROM sqlite_master WHERE name='effectiveness_settings'").fetchone()[0]
            if "BETWEEN 1 AND 10)" in schema:
                connection.execute(schema.replace("effectiveness_settings", "effectiveness_settings_next", 1).replace("BETWEEN 1 AND 10)", "BETWEEN 1 AND 10000)"))
                connection.execute("INSERT INTO effectiveness_settings_next SELECT * FROM effectiveness_settings")
                connection.execute("DROP TABLE effectiveness_settings")
                connection.execute("ALTER TABLE effectiveness_settings_next RENAME TO effectiveness_settings")
            connection.commit()
        except Exception:
            connection.rollback()
            connection.close()
            raise
    for game in (*GAMES, "KENO"):
        connection.execute("INSERT OR IGNORE INTO effectiveness_settings(game_type) VALUES(?)", (game,))
    return connection


def _settings(row) -> dict:
    return {"enabled": bool(row["enabled"]), "ticketCount": int(row["ticket_count"]), "maxTicketCount": portfolio.MAX_TICKETS,
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
    if not isinstance(enabled, bool) or type(ticket_count) is not int or not 1 <= ticket_count <= portfolio.MAX_TICKETS:
        raise ValueError("Bật/tắt phải là boolean và số vé phải trong khoảng 1–10.000.")
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
             Path(__file__), Path(portfolio.__file__), Path(ledger.__file__)]
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
        payload = predictor.predict_json(game, min(count, 10), engine="classic", risk_mode="balanced",
                                      prediction_mode="normal", username=ACTOR, lock_ledger=False)
    return portfolio.expand_web(payload, count, ml_pipeline.game_config(game)["universe_size"], ml_pipeline.game_config(game)["draw_size"], snapshot)


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
    large_mains = portfolio.unique_mains(probabilities, draw_size, count, seed) if count > 10 else None
    for index in range(count):
        if large_mains is not None:
            main = list(large_mains[index])
        else:
            main = None
        for attempt in range(100):
            if large_mains is not None:
                break
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
            "allocationPolicy": portfolio.VERSION if count > 10 else "legacy_seeded_unique",
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
    if len({tuple(sorted(ticket.get("main") or [])) for ticket in tickets}) != count:
        raise ValueError("Danh mục có bộ số trùng nhau.")
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
    if game == "KENO":
        from ai import keno_effectiveness
        return keno_effectiveness.cycle(db_path, force)
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
            if not payloads["web"].get("trackingPortfolio") and (payloads["web"].get("adaptiveCoverage") or {}).get("seed") is not None:
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
                          "allocationPolicy": portfolio.VERSION if count > 10 else "legacy",
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
    """Score only complete system mappings using ledger v2 metrics."""
    if _game(game) == "KENO":
        from ai import keno_effectiveness
        return keno_effectiveness.score_cycles(db_path)
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
                                        metrics["lift"], ledger.canonical_json(_score_storage(metrics)), ledger.SCORING_VERSION))
                    connection.execute("UPDATE prediction_runs SET status='scored' WHERE prediction_id=? AND status='locked'", (row["prediction_id"],))
                connection.commit()
                scored.append(target)
            except Exception as exc:
                connection.rollback()
                errors.append({"targetDrawId": target, "error": str(exc)})
    return {"ok": not errors, "type": game, "scored": scored, "errors": errors}


def _score_storage(metrics):
    """All tickets are scored; large per-ticket labels are derived on read.

    Keep immutable tickets and recorded actual plus exact whole-portfolio totals,
    rather than duplicating hundreds of thousands of reconstructible labels.
    """
    if metrics["ticket_count"] <= portfolio.TICKET_PAGE_SIZE:
        return metrics
    hits = [ticket["hit_count"] for ticket in metrics["per_ticket"]]
    results = metrics["prize_results"]
    summary = {"rate3": sum(hit >= 3 for hit in hits) / len(hits),
               "rate4": sum(hit >= 4 for hit in hits) / len(hits),
               "hitHistogram": {str(hit): hits.count(hit) for hit in range(metrics["prediction_size"] + 1)},
               "prizeCounts": prize_counts(results), "prizeStatistics": prize_statistics(results)}
    return {**{key: value for key, value in metrics.items() if key not in ("per_ticket", "prize_results")},
            "report_summary": summary, "per_ticket_storage": "derive_from_immutable_tickets_and_recorded_actual"}


def _ticket_slice(connection, prediction_id, page=1):
    total = connection.execute("SELECT json_array_length(tickets_json) FROM prediction_runs WHERE prediction_id=?", (prediction_id,)).fetchone()[0]
    pages = max(1, math.ceil(total / portfolio.TICKET_PAGE_SIZE))
    page = min(page, pages)
    offset = (page - 1) * portfolio.TICKET_PAGE_SIZE
    tickets = [json.loads(row[0]) for row in connection.execute(
        "SELECT t.value FROM prediction_runs pr,json_each(pr.tickets_json) t WHERE pr.prediction_id=? LIMIT ? OFFSET ?",
        (prediction_id, portfolio.TICKET_PAGE_SIZE, offset))]
    return tickets, {"page": page, "pageSize": portfolio.TICKET_PAGE_SIZE, "total": total,
                     "totalPages": pages, "offset": offset}


def ticket_page(game, prediction_id, page=1, db_path=None):
    game = _game(game)
    if type(page) is not int or not 1 <= page <= 1000000:
        raise ValueError("Trang vé phải là số nguyên dương.")
    with closing(_connect(db_path)) as connection:
        connection.execute("BEGIN")
        mapping_table = "keno_effectiveness_predictions" if game == "KENO" else "effectiveness_predictions"
        # A private/personal run must never be exposed through the shared report.
        prediction = connection.execute(f"SELECT pr.prediction_id,ep.cycle_id FROM prediction_runs pr JOIN {mapping_table} ep ON ep.prediction_id=pr.prediction_id WHERE pr.prediction_id=? AND pr.game_type=? AND pr.username=?", (prediction_id, game, ACTOR)).fetchone()
        if not prediction:
            raise ValueError("Không tìm thấy dự đoán thuộc báo cáo hiệu quả.")
        if game == "KENO":
            cycle_row = connection.execute("SELECT status,actual_json FROM keno_effectiveness_cycles WHERE cycle_id=?", (prediction["cycle_id"],)).fetchone()
            actual = json.loads(cycle_row["actual_json"]) if cycle_row["status"] == "scored" else None
        else:
            rows = connection.execute("SELECT pr.status,json_extract(ps.metrics_json,'$.actual_main') main,json_extract(ps.metrics_json,'$.actual_special') special FROM effectiveness_predictions ep JOIN prediction_runs pr ON pr.prediction_id=ep.prediction_id LEFT JOIN prediction_scores ps ON ps.prediction_id=pr.prediction_id AND ps.scoring_version=? WHERE ep.cycle_id=?", (ledger.SCORING_VERSION, prediction["cycle_id"])).fetchall()
            complete = len(rows) == 4 and all(row["status"] == "scored" and row["main"] for row in rows)
            actual = {"main": json.loads(rows[0]["main"]) if all(row["main"] == rows[0]["main"] for row in rows) else [],
                      "special": rows[0]["special"] if all(row["special"] == rows[0]["special"] for row in rows) else None} if complete else None
        tickets, pagination = _ticket_slice(connection, prediction_id, page)
        results = classify_tickets(game, tickets, actual)
        for result in results:
            result["ticketIndex"] += pagination["offset"]
        return {"ok": True, "type": game, "predictionId": prediction_id, "tickets": tickets,
                "ticketResults": results, "ticketPagination": pagination}


def _combined_prizes(samples):
    counts, stats = {}, prize_statistics([])
    keys = ("ticketCount", "classifiedTicketCount", "winningTicketCount", "unknownTicketCount", "pendingTicketCount", "invalidTicketCount")
    for sample in samples:
        for key, value in sample.get("prizeCounts", {}).items():
            counts[key] = counts.get(key, 0) + value
        for key in keys:
            stats[key] += sample.get("prizeStatistics", {}).get(key, 0)
    stats["winningTicketRate"] = stats["winningTicketCount"] / stats["classifiedTicketCount"] if stats["classifiedTicketCount"] else None
    return counts, stats


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
    counts, stats = _combined_prizes(samples)
    return {"key": method, "label": METHODS[method], "sampleCount": count,
            "meanHits": mean(hits) if count else None, "brierScore": mean(s["brierScore"] for s in samples) if count else None,
            "logLoss": mean(s["logLoss"] for s in samples) if count else None,
            "rate3": mean(s["rate3"] for s in samples) if count else None,
            "rate4": mean(s["rate4"] for s in samples) if count else None,
            "lift": mean(hits) / expected - 1 if count else None,
            "deltaVsRandom": ci["mean"] if ci else None,
            "ci95": {"lower": ci["lower"], "upper": ci["upper"]} if ci else None,
            "hitHistogram": histogram, "decision": decision,
            "prizeCounts": counts, "prizeStatistics": stats}


def report(game: str, limit: int = 100, db_path=None, level: int = 10, page: int = 1) -> dict:
    game = _game(game)
    if game == "KENO":
        from ai import keno_effectiveness
        return keno_effectiveness.report(level, page, db_path)
    limit = max(1, min(1000, int(limit)))
    samples = {method: [] for method in METHODS}
    cycles = []
    with closing(_connect(db_path)) as connection:
        connection.execute("BEGIN")
        settings_row = connection.execute("SELECT * FROM effectiveness_settings WHERE game_type=?", (game,)).fetchone()
        rows = _cycle_rows(connection, game)
        for row in rows:
            predictions = connection.execute("""SELECT ep.method,pr.prediction_id,pr.engine,pr.model_id,pr.status,pr.random_seed,ps.metrics_json,ps.brier_score,ps.log_loss,
                json_extract(pr.payload_json,'$.probabilityCalibrationStatus') calibration,
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
                # Historical aggregates do not read full ticket/payload arrays.
                show_detail = len(cycles) < limit
                tickets, pagination = _ticket_slice(connection, prediction["prediction_id"]) if show_detail or not metrics.get("report_summary") else ([], {})
                method_row = {"predictionId": prediction["prediction_id"], "tickets": tickets,
                              "ticketPagination": pagination, "ticketCount": metrics.get("ticket_count", pagination.get("total", 0)),
                              "engine": prediction["engine"], "modelId": prediction["model_id"], "status": prediction["status"],
                              "meanHits": metrics.get("mean_hits_per_ticket"), "bestHits": metrics.get("hit_count"),
                              "brierScore": prediction["brier_score"] if complete else None,
                              "logLoss": prediction["log_loss"] if complete else None,
                              "seed": prediction["random_seed"], "calibrationStatus": prediction["calibration"] or "uncalibrated"}
                # Classification uses only the immutable score's recorded result;
                # never fill an old missing special ball from today's CSV.
                recorded_actual = {"main": actual_main, "special": actual_special} if complete else None
                ticket_results = classify_tickets(game, method_row["tickets"], recorded_actual)
                method_row.update({"ticketResults": ticket_results, "prizeCounts": prize_counts(ticket_results),
                                   "prizeStatistics": prize_statistics(ticket_results), "prizeSource": item["actualSource"]})
                if not complete and pagination.get("total", 0) > len(tickets):
                    total_tickets = pagination["total"]
                    method_row.update({"prizeCounts": {"PENDING": total_tickets},
                                       "prizeStatistics": {**prize_statistics([]), "ticketCount": total_tickets, "pendingTicketCount": total_tickets}})
                if complete:
                    if metrics.get("report_summary"):
                        method_row.update(metrics["report_summary"])
                        if not same_main or (game != "LOTO_6_45" and not same_special):
                            # Corrupt/conflicting historical recorded results must
                            # not inherit apparently certain whole-portfolio prizes.
                            full_tickets = json.loads(connection.execute("SELECT tickets_json FROM prediction_runs WHERE prediction_id=?", (prediction["prediction_id"],)).fetchone()[0])
                            full_results = classify_tickets(game, full_tickets, recorded_actual)
                            method_row.update({"prizeCounts": prize_counts(full_results), "prizeStatistics": prize_statistics(full_results)})
                    else:
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
                          "Tối đa 10.000 bộ số khác nhau/phương pháp. Nhật ký tải 20 vé mỗi trang; thống kê chấm toàn bộ danh mục đã khóa.",
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
    result = {"ok": True, "results": results}
    from ai import keno_effectiveness
    try:
        result["keno"] = keno_effectiveness.tick(db_path)
    except Exception as exc:
        result["keno"] = {"ok": False, "error": str(exc)}
    if db_path is None:
        # Independent candidate trials have their own database and immutable
        # payloads. Fixture/explicit ledger paths never reach production trials.
        from ai import lab_trials
        try:
            result["labTrials"] = lab_trials.tick()
        except Exception as exc:
            result["labTrials"] = {"ok": False, "error": str(exc)}
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("report", "settings", "configure", "cycle", "tick", "tickets"):
        child = sub.add_parser(command)
        if command != "tick":
            child.add_argument("game", choices=(*GAMES, "KENO"))
        child.add_argument("--db-path", default=None, help=argparse.SUPPRESS)
        if command == "report":
            child.add_argument("--limit", type=int, default=100)
            child.add_argument("--level", type=int, default=10)
            child.add_argument("--page", type=int, default=1)
        if command == "configure":
            child.add_argument("--enabled", choices=("true", "false"), required=True)
            child.add_argument("--ticket-count", type=int, default=3)
            child.add_argument("--actor", required=True)
        if command == "tickets":
            child.add_argument("--prediction-id", required=True)
            child.add_argument("--page", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        # Keep stdout exclusively JSON even if a legacy engine prints a diagnostic.
        with redirect_stdout(StringIO()):
            if args.command == "report": result = report(args.game, args.limit, args.db_path, args.level, args.page)
            elif args.command == "settings": result = settings(args.game, args.db_path)
            elif args.command == "tickets": result = ticket_page(args.game, args.prediction_id, args.page, args.db_path)
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
