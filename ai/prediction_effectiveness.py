"""Prospective, equal-budget comparison of the real web pipeline and fixed baselines.

Only future predictions are recorded. Reports never fabricate historical forecasts,
rescore personal runs, fit a model, or promote a registry candidate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
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
from ai import tracking_bao as bao
from ai import tracking_ticket_seed as ticket_seeds
from ai import tracking_progress as progress
from ai import personal_tracking as billing
from ai.tracking_storage import database_path
from ai.configs import data_paths as dp
from ai.evaluation.statistical_tests import paired_bootstrap_ci
from ai.prizes import RULE_VERSION as PRIZE_RULE_VERSION, PRIZE_SCOPE, classify_ticket, classify_tickets, prize_counts, prize_statistics
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


def cycle_selection_key(configuration: dict) -> str:
    """One immutable purchase per ticket class/Bao level, regardless of quantity."""
    if configuration.get('playMode', 'normal') == 'bao':
        level = configuration.get('baoLevel')
        if type(level) is not int or level < 1:
            raise ValueError('Cơ cấu Bao đã khóa thiếu cấp Bao hợp lệ.')
        return f'bao:{level}'
    return 'normal'


def _migrate_cycle_selections(connection, database):
    if 'selection_key' in {row[1] for row in connection.execute('PRAGMA table_info(effectiveness_cycles)')}:
        return
    # Rebuild only the small metadata table, preserving IDs, payloads, receipts
    # and FK mappings. Never rename the old table: SQLite would rewrite its FKs.
    with resource_lock(database.parent / 'cycle_selection_schema'):
        connection.execute('PRAGMA foreign_keys=OFF')
        try:
            connection.execute('BEGIN IMMEDIATE')
            if 'selection_key' not in {row[1] for row in connection.execute('PRAGMA table_info(effectiveness_cycles)')}:
                rows = connection.execute('SELECT * FROM effectiveness_cycles').fetchall()
                connection.execute('''CREATE TABLE effectiveness_cycles_next (
                    cycle_id TEXT PRIMARY KEY, game_type TEXT NOT NULL, target_draw_id TEXT NOT NULL,
                    cutoff_draw_id TEXT NOT NULL, created_at TEXT NOT NULL, deadline TEXT NOT NULL,
                    data_hash TEXT NOT NULL, source_version_json TEXT NOT NULL, config_json TEXT NOT NULL,
                    selection_key TEXT NOT NULL, UNIQUE(game_type,target_draw_id,selection_key))''')
                connection.executemany('INSERT INTO effectiveness_cycles_next VALUES(?,?,?,?,?,?,?,?,?,?)',
                                       [(*tuple(row), cycle_selection_key(json.loads(row['config_json']))) for row in rows])
                connection.execute('DROP TABLE effectiveness_cycles')
                connection.execute('ALTER TABLE effectiveness_cycles_next RENAME TO effectiveness_cycles')
                connection.execute('''CREATE TRIGGER effectiveness_cycle_immutable
                    BEFORE UPDATE ON effectiveness_cycles BEGIN
                    SELECT RAISE(ABORT,'prospective cycle is immutable'); END''')
                if connection.execute('PRAGMA foreign_key_check(effectiveness_predictions)').fetchone():
                    raise ValueError('Liên kết bộ dự đoán không hợp lệ; hủy nâng cấp cơ cấu Bao.')
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.execute('PRAGMA foreign_keys=ON')


def _connect(db_path=None):
    connection = ledger.connect(database_path(db_path))
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS effectiveness_settings (
            game_type TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
            ticket_count INTEGER NOT NULL DEFAULT 3 CHECK(ticket_count BETWEEN 1 AND 1000000),
            updated_at TEXT NOT NULL DEFAULT '', updated_by TEXT NOT NULL DEFAULT '',
            last_tick TEXT NOT NULL DEFAULT '', last_error TEXT NOT NULL DEFAULT '',
            next_target TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS effectiveness_cycles (
            cycle_id TEXT PRIMARY KEY, game_type TEXT NOT NULL, target_draw_id TEXT NOT NULL,
            cutoff_draw_id TEXT NOT NULL, created_at TEXT NOT NULL, deadline TEXT NOT NULL,
            data_hash TEXT NOT NULL, source_version_json TEXT NOT NULL,
            config_json TEXT NOT NULL, selection_key TEXT NOT NULL,
            UNIQUE(game_type,target_draw_id,selection_key)
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
        CREATE TABLE IF NOT EXISTS effectiveness_ticket_index (
            prediction_id TEXT PRIMARY KEY REFERENCES prediction_runs(prediction_id),
            ticket_count INTEGER NOT NULL, calibration_status TEXT NOT NULL,
            chunk_size INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS effectiveness_ticket_chunks (
            prediction_id TEXT NOT NULL REFERENCES prediction_runs(prediction_id),
            chunk_number INTEGER NOT NULL, tickets_json TEXT NOT NULL,
            PRIMARY KEY(prediction_id,chunk_number)
        );
        CREATE TRIGGER IF NOT EXISTS effectiveness_ticket_index_immutable
        BEFORE UPDATE ON effectiveness_ticket_index BEGIN
            SELECT RAISE(ABORT,'ticket index is immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS effectiveness_ticket_chunks_immutable
        BEFORE UPDATE ON effectiveness_ticket_chunks BEGIN
            SELECT RAISE(ABORT,'ticket chunk is immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS effectiveness_cycle_immutable
        BEFORE UPDATE ON effectiveness_cycles BEGIN
            SELECT RAISE(ABORT,'prospective cycle is immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS effectiveness_mapping_immutable
        BEFORE UPDATE ON effectiveness_predictions BEGIN
            SELECT RAISE(ABORT,'prospective mapping is immutable');
        END;
    """)
    try:
        _migrate_cycle_selections(connection, database_path(db_path))
    except Exception:
        connection.close()
        raise
    # Rebuild only the mutable settings table; forecasts and audits stay intact.
    schema = connection.execute("SELECT sql FROM sqlite_master WHERE name='effectiveness_settings'").fetchone()[0]
    if re.search(r"BETWEEN 1 AND (?:10|10000)\)", schema):
        connection.execute("BEGIN IMMEDIATE")
        try:
            schema = connection.execute("SELECT sql FROM sqlite_master WHERE name='effectiveness_settings'").fetchone()[0]
            if re.search(r"BETWEEN 1 AND (?:10|10000)\)", schema):
                connection.execute(re.sub(r"BETWEEN 1 AND (?:10|10000)\)", "BETWEEN 1 AND 1000000)", schema.replace("effectiveness_settings", "effectiveness_settings_next", 1)))
                connection.execute("INSERT INTO effectiveness_settings_next SELECT * FROM effectiveness_settings")
                connection.execute("DROP TABLE effectiveness_settings")
                connection.execute("ALTER TABLE effectiveness_settings_next RENAME TO effectiveness_settings")
            connection.commit()
        except Exception:
            connection.rollback()
            connection.close()
            raise
    # Only mutable settings gain columns; immutable cycles and forecasts are untouched.
    with resource_lock(database_path(db_path).parent / 'bao_schema'):
        columns = {row[1] for row in connection.execute('PRAGMA table_info(effectiveness_settings)')}
        for field, declaration in [('play_mode', "TEXT NOT NULL DEFAULT 'normal'"),
                                   ('bao_level', 'INTEGER NOT NULL DEFAULT 6'),
                                   ('bao_count', 'INTEGER NOT NULL DEFAULT 1')]:
            if field not in columns:
                connection.execute(f'ALTER TABLE effectiveness_settings ADD COLUMN {field} {declaration}')
    existing_games = {row[0] for row in connection.execute("SELECT game_type FROM effectiveness_settings")}
    for game in (*GAMES, "KENO"):
        if game not in existing_games:
            connection.execute("INSERT OR IGNORE INTO effectiveness_settings(game_type) VALUES(?)", (game,))
    return connection


def ticket_limit(game: str) -> int:
    if game == "LOTO_5_35":
        return math.comb(35, 5)
    return portfolio.KENO_MAX_TICKETS if game == "KENO" else portfolio.MAX_TICKETS


def _settings(row) -> dict:
    maximum = ticket_limit(row['game_type'])
    normal = min(int(row['ticket_count']), maximum) if row['game_type'] == 'LOTO_5_35' else int(row['ticket_count'])
    structure = bao.configuration(row['game_type'], row['play_mode'], int(row['bao_level']),
                                  int(row['bao_count']), maximum, strict=False)
    count = structure['baoCount'] * structure['childrenPerBao'] if structure['playMode'] == 'bao' else normal
    result = {'enabled': bool(row['enabled']), 'ticketCount': count, 'normalTicketCount': normal,
              'maxTicketCount': maximum, **structure,
              'engine': 'classic', 'riskMode': 'balanced', 'predictionMode': 'normal',
              'bayesianPrior': PRIOR_STRENGTH, 'ewmaHalfLife': HALF_LIFE,
              'updatedAt': row['updated_at'], 'updatedBy': row['updated_by']}
    result['configurationHash'] = _digest(result)
    return result


def settings(game: str, db_path=None) -> dict:
    game = _game(game)
    with closing(_connect(db_path)) as connection:
        row = connection.execute("SELECT * FROM effectiveness_settings WHERE game_type=?", (game,)).fetchone()
        return {"ok": True, "type": game, "settings": _settings(row)}


def configure(game: str, enabled: bool, ticket_count: int = 3, actor: str = "", db_path=None, *, play_mode="normal", bao_level=None, bao_count=None) -> dict:
    game = _game(game)
    maximum = ticket_limit(game)
    if not isinstance(enabled, bool) or type(ticket_count) is not int or not 1 <= ticket_count <= maximum:
        raise ValueError(f"Bật/tắt phải là boolean và số vé phải trong khoảng 1–{maximum:,}.".replace(",", "."))
    if not str(actor).strip():
        raise ValueError("Thiếu tài khoản quản trị thay đổi cấu hình.")
    structure = bao.configuration(game, play_mode, bao_level, bao_count, maximum)
    with closing(_connect(db_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute("UPDATE effectiveness_settings SET enabled=?,ticket_count=?,play_mode=?,bao_level=?,bao_count=?,last_error='',updated_at=?,updated_by=? WHERE game_type=?",
                               (int(enabled), int(ticket_count), play_mode, structure['baoLevel'] or (6 if game == 'LOTO_5_35' else 7),
                                structure['baoCount'] or 1, ledger.now_iso(), actor, game))
            row = connection.execute("SELECT * FROM effectiveness_settings WHERE game_type=?", (game,)).fetchone()
            result = _settings(row)
            connection.execute("INSERT INTO effectiveness_config_audit VALUES(?,?,?,?,?)",
                               (str(uuid.uuid4()), game, actor, ledger.now_iso(), ledger.canonical_json(result)))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {"ok": True, "type": game, "settings": result,
            "note": "Trước giờ quay có thể khóa thêm loại Bao khác; loại vé/Bao đã có trong kỳ giữ nguyên và không thu thêm phí."}


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
    paths = [dp.PROJECT_ROOT / "ai/predictors/ai_predict.py", dp.PROJECT_ROOT / "ai/adaptive_coverage.py", Path(ticket_seeds.__file__),
             Path(__file__), Path(portfolio.__file__), Path(ledger.__file__), Path(bao.__file__), bao.PLAN_PATH, dp.PROJECT_ROOT / "ai/tracking_capacity.py", dp.PROJECT_ROOT / "ai/tracking_storage.py"]
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
        if large_mains is None:
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
    if len({bao.ticket_key(game, ticket) for ticket in tickets}) != count:
        raise ValueError("Danh mục có vé trùng hoàn toàn.")
    probs = ledger.normalize_probability_payload(payload.get("probabilities") or {})
    if set(probs) != set(range(1, cfg["universe_size"] + 1)) or any(not math.isfinite(p) or not 0 <= p <= 1 for p in probs.values()):
        raise ValueError("Vector xác suất thiếu số hoặc không hữu hạn.")
    if abs(sum(probs.values()) - cfg["draw_size"]) > 1e-5:
        raise ValueError("Tổng xác suất biên không khớp cỡ kỳ quay.")


def _cycle_rows(connection, game: str):
    return connection.execute("SELECT * FROM effectiveness_cycles WHERE game_type=? ORDER BY CAST(target_draw_id AS INTEGER) DESC, created_at DESC, cycle_id DESC", (game,)).fetchall()


def _validate_bao(payload, game, count, snapshot):
    structure = payload.get('bao') or {}
    parents = structure.get('parents') or []
    level, per = structure.get('baoLevel'), structure.get('childrenPerBao')
    n, t, _ = bao.GAMES[game]
    if (payload.get('ticketClass') != 'bao' or payload.get('ticketStorage') != 'bao_parents_v1' or
            payload.get('tickets') or len(parents) != structure.get('baoCount') or
            per != bao.children_per_bao(game, level) or len(parents) * per != count):
        raise ValueError('Danh mục Bao không khớp cơ cấu đã lưu.')
    seen = set()
    for index, parent in enumerate(parents, 1):
        main = parent.get('main') or []
        if (parent.get('parentIndex') != index or parent.get('childCount') != per or
                len(main) != level or len(set(main)) != level or
                any(type(value) is not int or not 1 <= value <= n for value in main) or
                game == 'LOTO_5_35' and (type(parent.get('special')) is not int or not 1 <= parent['special'] <= 12) or
                game != 'LOTO_5_35' and parent.get('special') is not None):
            raise ValueError('Bộ Bao gốc không hợp lệ.')
        for child in bao._children(tuple(sorted(main)), n, t):
            key = (*child, parent['special']) if game == 'LOTO_5_35' else child
            if key in seen:
                raise ValueError('Danh mục Bao có tổ hợp trùng hoàn toàn.')
            seen.add(key)
    if len(seen) != count:
        raise ValueError('Danh mục Bao chưa đủ số tổ hợp quy đổi.')
    example = next(bao.iter_equivalents(game, parents))
    _validate({**payload, 'tickets': [example]}, game, 1, snapshot)


@progress.track
@billing.settle
def cycle(game: str, db_path=None, force=True, configuration_hash=None) -> dict:
    game = _game(game)
    if game == "KENO":
        from ai import keno_effectiveness
        return keno_effectiveness.cycle(db_path, force)
    database = database_path(db_path)
    with resource_lock(database.parent / f"effectiveness_{game.lower()}", timeout=15):
        with closing(_connect(db_path)) as connection:
            row = connection.execute("SELECT * FROM effectiveness_settings WHERE game_type=?", (game,)).fetchone()
            configuration = _settings(row)
            if not configuration["enabled"] and not force:
                return {"ok": True, "type": game, "status": "disabled"}
            snapshot = _snapshot(game)
            selection_key = cycle_selection_key(configuration)
            existing = connection.execute("SELECT cycle_id,config_json FROM effectiveness_cycles WHERE game_type=? AND target_draw_id=? AND selection_key=?",
                                          (game, snapshot["target"], selection_key)).fetchone()
            if existing:
                frozen = json.loads(existing['config_json'])
                return {"ok": True, "type": game, "status": "already_locked", "cycleId": existing['cycle_id'],
                        "targetDrawId": snapshot["target"], "selectionKey": selection_key,
                        "playMode": frozen.get('playMode', 'normal'), "baoLevel": frozen.get('baoLevel'),
                        "baoCount": frozen.get('baoCount'), "ticketCount": frozen.get('actualTicketCount', frozen.get('ticketCount'))}
            if configuration_hash is not None and configuration_hash != configuration['configurationHash']:
                raise ValueError('Cấu hình đã thay đổi. Hãy lưu lại và xác nhận phí trước khi khóa kỳ.')
            if not configuration['configurationValid']:
                raise ValueError(configuration['configurationError'])
            if force and configuration['playMode'] == 'bao' and billing._scope.get() is not None and not configuration_hash:
                raise ValueError('Hãy lưu cấu hình và xác nhận phí Bao trước khi khóa kỳ.')
            _guard(snapshot)
            count = portfolio.effective_count(configuration["ticketCount"], ml_pipeline.game_config(game)["universe_size"], ml_pipeline.game_config(game)["draw_size"])
            if count > 10000:
                from ai.tracking_capacity import ensure_storage
                ensure_storage(database, [(ml_pipeline.game_config(game)["draw_size"], 4 * count)])
            progress.start("creating", 8 * count, 4 * count)
            charge_id = billing.reserve(game, snapshot['target'], 4 * count)
            manifest = _execution_manifest(game)
            seed_count = 1
            payloads = {"web": _production_web_prediction(game, seed_count, snapshot)}
            payloads["web"] = dict(payloads["web"])
            if not payloads["web"].get("trackingPortfolio") and (payloads["web"].get("adaptiveCoverage") or {}).get("seed") is not None:
                payloads["web"]["randomSeed"] = int(payloads["web"]["adaptiveCoverage"]["seed"])
            progress.advance(count)
            for method in ("random", "bayesian", "ewma"):
                payloads[method] = _baseline(game, method, seed_count, snapshot)
                progress.advance(count)
            schedules = {}
            for method, payload in payloads.items():
                _validate(payload, game, seed_count, snapshot)
                root_seed = payload.get('randomSeed') if method == 'web' and payload.get('randomSeed') is not None else _seed(game, method, snapshot, count)
                schedules[method] = ticket_seeds.schedule(root_seed, game, snapshot['target'], method,
                    configuration['baoCount'] if configuration['playMode'] == 'bao' else count,
                    play_mode=configuration['playMode'], bao_level=configuration['baoLevel'])
                if configuration['playMode'] == 'bao':
                    schedules[method].update(sourceMain=payload['tickets'][0]['main'], sourceSpecial=payload['tickets'][0].get('special'))
            if configuration['playMode'] == 'bao':
                payloads = {method: bao.build(payload, game, configuration['baoLevel'], configuration['baoCount'], ticket_limit(game), seed_schedule=schedules[method])
                            for method, payload in payloads.items()}
            else:
                payloads = {method: ticket_seeds.normal(payload, game, schedules[method], count) for method, payload in payloads.items()}
            for payload in payloads.values():
                if configuration['playMode'] == 'bao':
                    _validate_bao(payload, game, count, snapshot)
                else:
                    if payload.get('bao'):
                        raise ValueError('Cấu hình Vé Thường không được sinh danh mục Bao.')
                    payload['ticketClass'] = 'normal'
                    _validate(payload, game, count, snapshot)
            with resource_lock(snapshot["path"]):
                fresh = _snapshot(game)
                if fresh["version"] != snapshot["version"] or fresh["dataHash"] != snapshot["dataHash"]:
                    raise RuntimeError("Canonical thay đổi trong khi tạo dự đoán; hủy toàn bộ chu kỳ và thử lại.")
                if _execution_manifest(game) != manifest:
                    raise RuntimeError("Mã/model thay đổi trong khi dự đoán; chưa khóa chu kỳ.")
                _guard(fresh)
                if count > 10000:
                    ensure_storage(database, [(ml_pipeline.game_config(game)["draw_size"], 4 * count)])
                config = {**configuration, "ticketClass": configuration["playMode"], "actualTicketCount": count, "pipeline": PIPELINE, "sourceManifest": manifest,
                          "ticketSeedVersion": ticket_seeds.VERSION, "ticketSeedSchedules": schedules,
                          "allocationPolicy": bao.RULE_VERSION if configuration["playMode"] == "bao" else portfolio.VERSION if count > 10 else "legacy",
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
                    connection.execute("INSERT INTO effectiveness_cycles VALUES(?,?,?,?,?,?,?,?,?,?)",
                                       (cycle_id, game, snapshot["target"], snapshot["cutoff"], created_at,
                                        snapshot["deadline"].isoformat(timespec="seconds"), snapshot["dataHash"],
                                        ledger.canonical_json(snapshot["version"]), ledger.canonical_json(config), selection_key))
                    for method, payload in payloads.items():
                        payload = {**payload, "predictionDeadline": snapshot["deadline"].isoformat(timespec="seconds"),
                                   "dataHash": snapshot["dataHash"], "configHash": config_hash,
                                   "effectivenessMethod": method, "effectivenessCycleId": cycle_id,
                                   "executionManifest": manifest if method == "web" else {}, "evaluationScope": "main_numbers_only"}
                        if not payload.get("modelId"):
                            payload["modelId"] = f"execution_effectiveness_{_digest(manifest)[:20]}"
                        locked = ledger.lock_prediction(payload, username=ACTOR, connection=connection,
                                                        random_seed=int(payload['randomSeed'] if payload.get('randomSeed') is not None else _seed(game, method, snapshot, count)))
                        connection.execute("INSERT INTO effectiveness_predictions VALUES(?,?,?)", (cycle_id, method, locked["prediction_id"]))
                        _index_tickets(connection, locked["prediction_id"], payload)
                        progress.advance(count)
                    _guard(snapshot)
                    billing.receipt(connection, charge_id, cycle_id, 4 * count)
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
            return {"ok": True, "type": game, "status": "locked", "cycleId": cycle_id,
                    "targetDrawId": snapshot["target"], "cutoffDrawId": snapshot["cutoff"], "ticketCount": count,
                    "selectionKey": selection_key, "playMode": configuration['playMode'],
                    "baoLevel": configuration['baoLevel'], "baoCount": configuration['baoCount']}


@progress.track
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
                budget = json.loads(cycle_row["config_json"])
                tickets = budget.get("actualTicketCount", budget["ticketCount"]) * 4
                progress.start("scoring", 4, tickets)
                connection.execute("BEGIN IMMEDIATE")
                for row in rows:
                    payload = json.loads(row["payload_json"])
                    if ledger.payload_checksum(payload) != row["payload_checksum"]:
                        raise ValueError("Checksum dự đoán không khớp.")
                    if row["username"] != ACTOR or row["status"] not in ("locked", "scored"):
                        raise ValueError("Run không thuộc chu kỳ hệ thống hợp lệ.")
                    scoring = bao.scoring_payload(payload)
                    metrics = ledger.score_prediction_payload(scoring, actual[target], cfg["universe_size"], cfg["draw_size"], cfg["prediction_size"], compact=bool(payload.get('bao')) or len(scoring.get("tickets") or []) > portfolio.TICKET_PAGE_SIZE)
                    connection.execute("INSERT OR IGNORE INTO prediction_scores VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                       (str(uuid.uuid4()), row["prediction_id"], ledger.now_iso(), target,
                                        metrics["hit_count"], metrics["special_hit"], metrics["brier_score"], metrics["log_loss"],
                                        metrics["lift"], ledger.canonical_json(_score_storage(metrics)), ledger.SCORING_VERSION))
                    connection.execute("UPDATE prediction_runs SET status='scored' WHERE prediction_id=? AND status='locked'", (row["prediction_id"],))
                    progress.advance(1)
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
    if metrics.get("report_summary") or metrics["ticket_count"] <= portfolio.TICKET_PAGE_SIZE:
        return metrics
    hits = [ticket["hit_count"] for ticket in metrics["per_ticket"]]
    results = metrics["prize_results"]
    summary = {"rate3": sum(hit >= 3 for hit in hits) / len(hits),
               "rate4": sum(hit >= 4 for hit in hits) / len(hits),
               "hitHistogram": {str(hit): hits.count(hit) for hit in range(metrics["prediction_size"] + 1)},
               "prizeCounts": prize_counts(results), "prizeStatistics": prize_statistics(results)}
    return {**{key: value for key, value in metrics.items() if key not in ("per_ticket", "prize_results")},
            "report_summary": summary, "per_ticket_storage": "derive_from_immutable_tickets_and_recorded_actual"}


def _index_tickets(connection, prediction_id, payload):
    """Derived read index written atomically with its immutable ledger payload."""
    tickets = payload.get("tickets") or []
    if payload.get('ticketStorage') == 'bao_parents_v1':
        count = payload['bao']['baoCount'] * payload['bao']['childrenPerBao']
        connection.execute("INSERT INTO effectiveness_ticket_index VALUES(?,?,?,?)",
                           (prediction_id, count, str(payload.get('probabilityCalibrationStatus') or 'uncalibrated'), 0))
        return
    chunk_size = 1000 if len(tickets) > 10000 else 0
    connection.execute("INSERT INTO effectiveness_ticket_index VALUES(?,?,?,?)",
                       (prediction_id, len(tickets), str(payload.get("probabilityCalibrationStatus") or "uncalibrated"), chunk_size))
    if chunk_size:
        connection.executemany("INSERT INTO effectiveness_ticket_chunks VALUES(?,?,?)",
                              ((prediction_id, start // chunk_size, ledger.canonical_json(tickets[start:start + chunk_size]))
                               for start in range(0, len(tickets), chunk_size)))


def _ticket_total(connection, prediction_id):
    indexed = connection.execute("SELECT ticket_count FROM effectiveness_ticket_index WHERE prediction_id=?", (prediction_id,)).fetchone()
    return indexed[0] if indexed else connection.execute("SELECT json_array_length(tickets_json) FROM prediction_runs WHERE prediction_id=?", (prediction_id,)).fetchone()[0]


def _iter_tickets(connection, prediction_id):
    indexed = connection.execute("SELECT chunk_size FROM effectiveness_ticket_index WHERE prediction_id=?", (prediction_id,)).fetchone()
    if indexed and indexed[0]:
        for row in connection.execute("SELECT tickets_json FROM effectiveness_ticket_chunks WHERE prediction_id=? ORDER BY chunk_number", (prediction_id,)):
            yield from json.loads(row[0])
    else:
        for row in connection.execute("SELECT t.value FROM prediction_runs pr,json_each(pr.tickets_json) t WHERE pr.prediction_id=?", (prediction_id,)):
            yield json.loads(row[0])


def _ticket_slice(connection, prediction_id, page=1):
    total = _ticket_total(connection, prediction_id)
    pages = max(1, math.ceil(total / portfolio.TICKET_PAGE_SIZE))
    page = min(page, pages)
    offset = (page - 1) * portfolio.TICKET_PAGE_SIZE
    indexed = connection.execute("SELECT chunk_size FROM effectiveness_ticket_index WHERE prediction_id=?", (prediction_id,)).fetchone()
    if indexed and indexed[0]:
        size = indexed[0]
        tickets = []
        start = offset
        while start < min(total, offset + portfolio.TICKET_PAGE_SIZE):
            row = connection.execute("SELECT tickets_json FROM effectiveness_ticket_chunks WHERE prediction_id=? AND chunk_number=?", (prediction_id, start // size)).fetchone()
            if row is None:
                raise ValueError("Thiếu dữ liệu trang vé; chưa thể mở danh mục.")
            chunk = json.loads(row[0])
            if len(chunk) != min(size, total - (start // size) * size):
                raise ValueError("Dữ liệu trang vé chưa đầy đủ.")
            count = min(size - start % size, offset + portfolio.TICKET_PAGE_SIZE - start, total - start)
            tickets.extend(chunk[start % size:start % size + count])
            start += count
        return tickets, {"page": page, "pageSize": portfolio.TICKET_PAGE_SIZE, "total": total, "totalPages": pages, "offset": offset}
    tickets = [json.loads(row[0]) for row in connection.execute(
        "SELECT t.value FROM prediction_runs pr,json_each(pr.tickets_json) t WHERE pr.prediction_id=? LIMIT ? OFFSET ?",
        (prediction_id, portfolio.TICKET_PAGE_SIZE, offset))]
    return tickets, {"page": page, "pageSize": portfolio.TICKET_PAGE_SIZE, "total": total,
                     "totalPages": pages, "offset": offset}


def _bao_slice(connection, prediction_id, config, page=1):
    """Read only the original groups on this page from the immutable payload.

    Never reconstruct a parent from a partial page of its child tickets.
    Legacy runs without original groups keep their existing child-ticket view.
    """
    if config.get('playMode') != 'bao':
        return [], {}
    total, level, per = (int(config.get(key) or 0) for key in ('baoCount', 'baoLevel', 'childrenPerBao'))
    if min(total, level, per) < 1:
        return [], {}
    size = portfolio.TICKET_PAGE_SIZE
    pages = max(1, math.ceil(total / size))
    page = min(page, pages)
    offset = (page - 1) * size
    indices = range(offset, min(total, offset + size))
    paths = [f'$.bao.parents[{index}]' for index in indices]
    row = connection.execute(
        "SELECT json_array_length(payload_json,'$.bao.parents'),json_extract(payload_json," +
        ','.join('?' for _ in paths) + ") FROM prediction_runs WHERE prediction_id=?",
        (*paths, prediction_id)).fetchone()
    if not row or row[0] is None:
        return [], {}
    if row[0] != total:
        raise ValueError('Số Bao gốc không khớp cấu hình đã khóa.')
    parents = json.loads(row[1])
    # SQLite returns an object for one path, and an array for several paths.
    if len(paths) == 1:
        parents = [parents]
    for index, parent in zip(indices, parents):
        if (not isinstance(parent, dict) or parent.get('parentIndex') != index + 1 or
                len(parent.get('main') or []) != level or parent.get('childCount') != per):
            raise ValueError('Dữ liệu Bao gốc chưa đầy đủ.')
    return parents, {'page': page, 'pageSize': size, 'total': total, 'totalPages': pages, 'offset': offset}


def ticket_page(game, prediction_id, page=1, db_path=None, prize_code=None, after_ticket_index=0, view='selected'):
    game = _game(game)
    if type(page) is not int or not 1 <= page <= 1000000:
        raise ValueError("Trang vé phải là số nguyên dương.")
    if view not in ('selected', 'tickets', 'bao') or (view == 'bao' and game == 'KENO'):
        raise ValueError('Chế độ xem vé không hợp lệ.')
    if prize_code is not None and (not isinstance(prize_code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,39}", prize_code)):
        raise ValueError("Mã giải thưởng không hợp lệ.")
    if type(after_ticket_index) is not int or not 0 <= after_ticket_index <= 1000000 or (after_ticket_index and prize_code is None):
        raise ValueError("Vị trí vé đã xem không hợp lệ.")
    with closing(_connect(db_path)) as connection:
        connection.execute("BEGIN")
        mapping_table = "keno_effectiveness_predictions" if game == "KENO" else "effectiveness_predictions"
        # A private/personal run must never be exposed through the shared report.
        prediction = connection.execute(f"SELECT pr.prediction_id,ep.cycle_id,ep.method FROM prediction_runs pr JOIN {mapping_table} ep ON ep.prediction_id=pr.prediction_id WHERE pr.prediction_id=? AND pr.game_type=? AND pr.username=?", (prediction_id, game, ACTOR)).fetchone()
        if not prediction:
            raise ValueError("Không tìm thấy dự đoán thuộc báo cáo hiệu quả.")
        config = {} if game == 'KENO' else json.loads(connection.execute(
            'SELECT config_json FROM effectiveness_cycles WHERE cycle_id=?', (prediction['cycle_id'],)).fetchone()[0])
        seed_schedule = config.get('ticketSeedSchedules', {}).get(prediction['method'])
        selected_view = 'bao' if config.get('playMode') == 'bao' else 'tickets'
        if view != 'selected' and view != selected_view:
            raise ValueError('Chỉ được xem đúng loại vé của cấu hình đã khóa.')
        view = selected_view
        if game == "KENO":
            cycle_row = connection.execute("SELECT status,actual_json FROM keno_effectiveness_cycles WHERE cycle_id=?", (prediction["cycle_id"],)).fetchone()
            actual = json.loads(cycle_row["actual_json"]) if cycle_row["status"] == "scored" else None
        else:
            rows = connection.execute("SELECT pr.status,json_extract(ps.metrics_json,'$.actual_main') main,json_extract(ps.metrics_json,'$.actual_special') special FROM effectiveness_predictions ep JOIN prediction_runs pr ON pr.prediction_id=ep.prediction_id LEFT JOIN prediction_scores ps ON ps.prediction_id=pr.prediction_id AND ps.scoring_version=? WHERE ep.cycle_id=?", (ledger.SCORING_VERSION, prediction["cycle_id"])).fetchall()
            complete = len(rows) == 4 and all(row["status"] == "scored" and row["main"] for row in rows)
            actual = {"main": json.loads(rows[0]["main"]) if all(row["main"] == rows[0]["main"] for row in rows) else [],
                      "special": rows[0]["special"] if all(row["special"] == rows[0]["special"] for row in rows) else None} if complete else None
        if view == 'bao':
            jump_parent = None
            if prize_code is not None:
                if not actual or not actual.get('main'):
                    raise ValueError('Kỳ này chưa có kết quả để tìm Bao trúng.')
                parents = json.loads(connection.execute("SELECT json_extract(payload_json,'$.bao.parents') FROM prediction_runs WHERE prediction_id=?", (prediction_id,)).fetchone()[0] or '[]')
                if after_ticket_index > len(parents):
                    raise ValueError('Vị trí Bao đã xem vượt số Bao đã khóa.')
                first_winner = None
                for parent in parents:
                    prizes = bao.parent_prizes(game, parent, actual)
                    if prizes['prizeCounts'].get(prize_code, 0) and prizes['prizeStatistics']['winningTicketCount']:
                        first_winner = first_winner or parent['parentIndex']
                        if parent['parentIndex'] > after_ticket_index:
                            jump_parent = parent['parentIndex']
                            break
                jump_parent = jump_parent or first_winner
                if jump_parent is None:
                    raise ValueError('Không tìm thấy Bao trúng giải này.')
                page = (jump_parent - 1) // portfolio.TICKET_PAGE_SIZE + 1
            parents, pagination = _bao_slice(connection, prediction_id, config, page)
            if not pagination:
                raise ValueError('Dự đoán này không có bộ Bao gốc để hiển thị.')
            for parent in parents:
                parent['result'] = bao.parent_prizes(game, parent, actual)
            parents = ticket_seeds.decorate(parents, seed_schedule, pagination['offset'])
            return {'ok': True, 'type': game, 'predictionId': prediction_id, 'view': 'bao', 'ticketClass': 'bao',
                    **({'seedSchedule': seed_schedule} if seed_schedule else {}),
                    'baoParents': parents, 'baoPagination': pagination,
                    **({'jumpBaoIndex': jump_parent} if jump_parent is not None else {})}
        jump_index = None
        if prize_code is not None:
            if not actual or not actual.get("main"):
                raise ValueError("Kỳ này chưa có kết quả để tìm vé trúng.")
            total = _ticket_total(connection, prediction_id)
            if after_ticket_index > total:
                raise ValueError("Vị trí vé đã xem vượt số vé của dự đoán.")
            first_winner = None
            for index, ticket in enumerate(_iter_tickets(connection, prediction_id), 1):
                result = classify_ticket(game, ticket, actual)
                if result["prizeCode"] == prize_code and result["status"] == "won":
                    if first_winner is None:
                        first_winner = index
                    if index > after_ticket_index:
                        jump_index = index
                        break
            if first_winner is None:
                raise ValueError("Không tìm thấy vé trúng giải này trong bộ dự đoán.")
            jump_index = jump_index or first_winner
            page = (jump_index - 1) // portfolio.TICKET_PAGE_SIZE + 1
        tickets, pagination = _ticket_slice(connection, prediction_id, page)
        tickets = ticket_seeds.decorate(tickets, seed_schedule, pagination['offset'])
        results = classify_tickets(game, tickets, actual)
        for result in results:
            result["ticketIndex"] += pagination["offset"]
        return {"ok": True, "type": game, "predictionId": prediction_id, 'view': view, 'ticketClass': 'normal', "tickets": tickets,
                **({'seedSchedule': seed_schedule} if seed_schedule else {}),
                "ticketResults": results, "ticketPagination": pagination,
                **({"jumpTicketIndex": jump_index} if jump_index is not None else {})}


def export_cycle(game, cycle_id, db_path=None, level=10, allow_large=False):
    """Read one complete locked portfolio/recorded result in one DB snapshot."""
    game = _game(game)
    try:
        uuid.UUID(cycle_id)
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Mã kỳ dự đoán không hợp lệ.")
    if type(level) is not int or not 1 <= level <= 10:
        raise ValueError("Bậc Keno phải từ 1 đến 10.")
    if game == "KENO":
        from ai import keno_effectiveness
        connect = keno_effectiveness._connect
    else:
        connect = _connect
    with closing(connect(db_path)) as connection:
        connection.execute("BEGIN")
        table = "keno_effectiveness_cycles" if game == "KENO" else "effectiveness_cycles"
        cycle = connection.execute(f"SELECT * FROM {table} WHERE cycle_id=?" +
                                   ("" if game == "KENO" else " AND game_type=?"),
                                   (cycle_id,) if game == "KENO" else (cycle_id, game)).fetchone()
        if cycle is None:
            raise ValueError("Không tìm thấy kỳ thuộc báo cáo hiệu quả.")
        if game == "KENO":
            predictions = connection.execute("SELECT ep.method,pr.prediction_id,pr.username,pr.game_type,pr.status,pr.engine,pr.model_id,pr.random_seed,pr.payload_checksum,json_array_length(pr.tickets_json) ticket_count FROM keno_effectiveness_predictions ep JOIN prediction_runs pr ON pr.prediction_id=ep.prediction_id WHERE ep.cycle_id=? AND ep.level=?", (cycle_id, level)).fetchall()
            scored = cycle["status"] == "scored"
            actual = json.loads(cycle["actual_json"]) if scored else None
        else:
            predictions = connection.execute("SELECT ep.method,pr.prediction_id,pr.username,pr.game_type,pr.status,pr.engine,pr.model_id,pr.random_seed,pr.payload_checksum,json_array_length(pr.tickets_json) ticket_count,ps.metrics_json FROM effectiveness_predictions ep JOIN prediction_runs pr ON pr.prediction_id=ep.prediction_id LEFT JOIN prediction_scores ps ON ps.prediction_id=pr.prediction_id AND ps.scoring_version=? WHERE ep.cycle_id=?", (ledger.SCORING_VERSION, cycle_id)).fetchall()
            scored = len(predictions) == 4 and all(p["status"] == "scored" and p["metrics_json"] for p in predictions)
            recorded = [json.loads(p["metrics_json"]) for p in predictions] if scored else []
            if recorded and any((m.get("actual_main"), m.get("actual_special")) !=
                                (recorded[0].get("actual_main"), recorded[0].get("actual_special")) for m in recorded):
                raise ValueError("Kết quả đã lưu của bốn phương pháp không khớp.")
            actual = {"main": recorded[0].get("actual_main", []), "special": recorded[0].get("actual_special")} if recorded else None
        if len(predictions) != 4 or {p["method"] for p in predictions} != set(METHODS) or any(
                p["username"] != ACTOR or p["game_type"] != game or p["status"] not in ("locked", "scored") for p in predictions):
            raise ValueError("Kỳ không có đủ bốn bộ dự đoán hệ thống hợp lệ.")
        if scored and not (actual or {}).get("main"):
            raise ValueError("Kỳ đã chấm thiếu kết quả thực tế đã lưu.")
        frozen_config = json.loads(cycle['config_json'])
        bao_export = frozen_config.get('playMode') == 'bao'
        if not allow_large and (frozen_config.get('baoCount', 0) > 10000 if bao_export else any(p['ticket_count'] > 10000 for p in predictions)):
            raise ValueError("Danh mục lớn cần tải trực tiếp file Excel; không tải toàn bộ vé dạng JSON.")
        result = {"ok": True, "type": game, "cycleId": cycle_id, "targetDrawId": cycle["target_draw_id"],
                  "cutoffDrawId": cycle["cutoff_draw_id"], "createdAt": cycle["created_at"],
                  "deadline": cycle["deadline"], "dataHash": cycle["data_hash"],
                  "config": json.loads(cycle["config_json"]), "status": "scored" if scored else "locked",
                  "actualMain": (actual or {}).get("main", []), "actualSpecial": (actual or {}).get("special"),
                  "actualSource": "recorded_ledger_score" if scored else "pending", "methods": {},
                  **({"level": level} if game == "KENO" else {})}
        result["config"].pop("sourceManifest", None)
        for p in predictions:
            seed_schedule = frozen_config.get('ticketSeedSchedules', {}).get(p['method'])
            if bao_export:
                parents = json.loads(connection.execute("SELECT json_extract(payload_json,'$.bao.parents') FROM prediction_runs WHERE prediction_id=?", (p['prediction_id'],)).fetchone()[0] or '[]')
                if len(parents) != frozen_config['baoCount']:
                    raise ValueError('Không đủ bộ Bao gốc để xuất dữ liệu.')
                counts, stats = {}, prize_statistics([])
                for parent in parents:
                    parent['result'] = bao.parent_prizes(game, parent, actual)
                    for code, amount in parent['result']['prizeCounts'].items():
                        counts[code] = counts.get(code, 0) + amount
                    for key in ('ticketCount', 'classifiedTicketCount', 'winningTicketCount', 'unknownTicketCount', 'pendingTicketCount', 'invalidTicketCount'):
                        stats[key] += parent['result']['prizeStatistics'][key]
                stats['winningTicketRate'] = stats['winningTicketCount'] / stats['classifiedTicketCount'] if stats['classifiedTicketCount'] else None
                result['methods'][p['method']] = {'predictionId': p['prediction_id'], 'ticketClass': 'bao',
                    'baoParents': ticket_seeds.decorate(parents, seed_schedule) if not allow_large else parents,
                    **({'seedSchedule': seed_schedule} if seed_schedule else {}),
                    'ticketCount': len(parents), 'equivalentTicketCount': frozen_config['actualTicketCount'],
                    'winningBaoCount': sum(parent['result']['status'] == 'won' for parent in parents),
                    'prizeCounts': counts, 'prizeStatistics': stats,
                    'engine': p['engine'], 'modelId': p['model_id'], 'seed': p['random_seed'], 'payloadChecksum': p['payload_checksum']}
                continue
            tickets = json.loads(connection.execute("SELECT tickets_json FROM prediction_runs WHERE prediction_id=?", (p["prediction_id"],)).fetchone()[0])
            if not 1 <= len(tickets) <= portfolio.MAX_TICKETS:
                raise ValueError("Số vé đã khóa vượt phạm vi xuất dữ liệu.")
            labels = classify_tickets(game, tickets, actual)
            result["methods"][p["method"]] = {"predictionId": p["prediction_id"], "tickets": ticket_seeds.decorate(tickets, seed_schedule) if not allow_large else tickets,
                **({'seedSchedule': seed_schedule} if seed_schedule else {}),
                "ticketCount": len(tickets), "ticketResults": labels,
                "prizeCounts": prize_counts(labels), "prizeStatistics": prize_statistics(labels),
                "engine": p["engine"], "modelId": p["model_id"], "seed": p["random_seed"],
                "payloadChecksum": p["payload_checksum"]}
        return result


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


def _draw_samples(samples):
    """Multiple purchased structures in one draw are not independent trials."""
    groups = {}
    for index, sample in enumerate(samples):
        groups.setdefault(sample.get('targetDrawId', index), []).append(sample)
    result = []
    for group in groups.values():
        if len(group) == 1:
            result.append(group[0])
            continue
        merged = dict(group[0])
        total = sum(sample['ticketCount'] for sample in group)
        for field in ('meanHits', 'brierScore', 'logLoss', 'rate3', 'rate4'):
            merged[field] = sum(sample[field] * sample['ticketCount'] for sample in group) / total
        merged['hitHistogram'] = {key: sum(sample['hitHistogram'].get(key, 0) for sample in group)
                                  for key in group[0]['hitHistogram']}
        merged['prizeCounts'], merged['prizeStatistics'] = _combined_prizes(group)
        merged['ticketCount'] = total
        result.append(merged)
    return result


def _summary(method: str, samples: list[dict], random_samples: list[dict], cfg: dict) -> dict:
    samples, random_samples = _draw_samples(samples), _draw_samples(random_samples)
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
                COALESCE(ti.calibration_status,json_extract(pr.payload_json,'$.probabilityCalibrationStatus')) calibration,
                ps.scoring_version FROM effectiveness_predictions ep
                JOIN prediction_runs pr ON pr.prediction_id=ep.prediction_id
                LEFT JOIN effectiveness_ticket_index ti ON ti.prediction_id=pr.prediction_id
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
            item = {"cycleId": row["cycle_id"], "selectionKey": row['selection_key'], "targetDrawId": row["target_draw_id"], "cutoffDrawId": row["cutoff_draw_id"],
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
                bao_cycle = item['config'].get('playMode') == 'bao'
                tickets, pagination = _ticket_slice(connection, prediction["prediction_id"]) if not bao_cycle and (show_detail or not metrics.get("report_summary")) else ([], {})
                seed_schedule = item['config'].get('ticketSeedSchedules', {}).get(method)
                tickets = ticket_seeds.decorate(tickets, seed_schedule, pagination.get('offset', 0))
                method_row = {"predictionId": prediction["prediction_id"], "targetDrawId": row['target_draw_id'], "tickets": tickets,
                              **({'seedSchedule': seed_schedule} if seed_schedule else {}),
                              "ticketPagination": pagination, "ticketCount": metrics.get("ticket_count", pagination.get("total", 0)),
                              "engine": prediction["engine"], "modelId": prediction["model_id"], "status": prediction["status"],
                              "meanHits": metrics.get("mean_hits_per_ticket"), "bestHits": metrics.get("hit_count"),
                              "brierScore": prediction["brier_score"] if complete else None,
                              "logLoss": prediction["log_loss"] if complete else None,
                              "seed": prediction["random_seed"], "calibrationStatus": prediction["calibration"] or "uncalibrated"}
                # Original groups are loaded only when their panel is visible.
                # Do not parse every large historical payload on each refresh.
                if bao_cycle:
                    method_row.update(ticketClass='bao', baoAvailable=True,
                                      selectionCount=item['config']['baoCount'],
                                      ticketCount=item['config']['actualTicketCount'])
                    for field in ('tickets', 'ticketPagination'):
                        method_row.pop(field, None)
                else:
                    method_row.update(ticketClass='normal', selectionCount=method_row['ticketCount'])
                # Classification uses only the immutable score's recorded result;
                # never fill an old missing special ball from today's CSV.
                recorded_actual = {"main": actual_main, "special": actual_special} if complete else None
                ticket_results = classify_tickets(game, tickets, recorded_actual)
                method_row.update({"ticketResults": ticket_results, "prizeCounts": prize_counts(ticket_results),
                                   "prizeStatistics": prize_statistics(ticket_results), "prizeSource": item["actualSource"]})
                if not complete and (bao_cycle or pagination.get("total", 0) > len(tickets)):
                    total_tickets = item['config']['actualTicketCount'] if bao_cycle else pagination["total"]
                    method_row.update({"prizeCounts": {"PENDING": total_tickets},
                                       "prizeStatistics": {**prize_statistics([]), "ticketCount": total_tickets, "pendingTicketCount": total_tickets}})
                if complete:
                    if metrics.get("report_summary"):
                        method_row.update(metrics["report_summary"])
                        if not same_main or (game != "LOTO_6_45" and not same_special):
                            # Corrupt/conflicting historical recorded results must
                            # not inherit apparently certain whole-portfolio prizes.
                            if bao_cycle:
                                total = item['config']['actualTicketCount']
                                method_row.update(prizeCounts={'UNKNOWN': total}, prizeStatistics={**prize_statistics([]), 'ticketCount': total, 'unknownTicketCount': total})
                            else:
                                full_tickets = json.loads(connection.execute("SELECT tickets_json FROM prediction_runs WHERE prediction_id=?", (prediction["prediction_id"],)).fetchone()[0])
                                full_results = classify_tickets(game, full_tickets, recorded_actual)
                                method_row.update({"prizeCounts": prize_counts(full_results), "prizeStatistics": prize_statistics(full_results)})
                    else:
                        ticket_hits = [ticket["hit_count"] for ticket in metrics["per_ticket"]]
                        if bao_cycle:
                            historical_results = metrics.get('prize_results') or []
                            method_row.update(prizeCounts=prize_counts(historical_results), prizeStatistics=prize_statistics(historical_results))
                        method_row.update({"rate3": sum(hit >= 3 for hit in ticket_hits) / len(ticket_hits),
                                       "rate4": sum(hit >= 4 for hit in ticket_hits) / len(ticket_hits),
                                       "hitHistogram": {str(n): ticket_hits.count(n) for n in range(ml_pipeline.game_config(game)["draw_size"] + 1)}})
                    samples[method].append(method_row)
                if bao_cycle:
                    method_row.pop('ticketResults', None)
                item["methods"][method] = method_row
            cycles.append(item)
        scored = len(samples["web"])
        configurations = {_digest({key: item["config"].get(key) for key in
                                   ("playMode", "baoLevel", "baoCount", "ticketCount", "actualWebEngine", "actualWebModelId", "sourceManifest", "pipeline")})
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
                          "Tối đa 1.000.000 vé/phương pháp; 5/35 dùng tối đa 324.632 vé con. 5/35 không trùng cả 5 số chính và ĐB; Mega/Power không trùng bộ 6 số chính. Nhật ký tải từng trang; thống kê chấm toàn bộ danh mục đã khóa.",
                          "So bốn phương pháp cùng kỳ và cùng số vé. Số trùng/Brier/CI vẫn chấm số chính; nhãn giải chấm riêng theo thể lệ vé chuẩn.",
                          "Giải dựa trên kết quả đã lưu lúc chấm; thiếu ĐB cũ ghi chưa xác định, không bổ sung từ CSV hiện tại. Số đặc biệt đối chứng lấy ngẫu nhiên.",
                          "Jackpot 2 Power cần trùng 5 số chính và số thứ bảy thực tế nằm trong 6 số của vé; số phụ dự đoán không quyết định giải.",
                          "Brier/log loss dùng xác suất biên chưa hiệu chỉnh. Các cơ cấu cùng kỳ được gộp theo số vé trước khi tính trung bình/CI ghép cặp theo kỳ, chưa điều chỉnh thử nhiều phương pháp.",
                          "Dưới 30 kỳ hoặc CI chứa 0: chưa đủ bằng chứng lợi thế. Kết quả quá khứ không bảo đảm kỳ sau."]}


@progress.track
def sync_source(game, db_path=None):
    from backend import prospective_live_sync
    with closing(_connect(db_path)) as connection:
        pending = connection.execute("SELECT DISTINCT ec.target_draw_id,ec.deadline FROM effectiveness_cycles ec "
                                     "JOIN effectiveness_predictions ep ON ep.cycle_id=ec.cycle_id "
                                     "JOIN prediction_runs pr ON pr.prediction_id=ep.prediction_id "
                                     "WHERE ec.game_type=? AND pr.status='locked'", (game,)).fetchall()
    return prospective_live_sync.refresh(game, now=_now(), pending=pending)


def tick(db_path=None, sync_sources=False) -> dict:
    results = []
    for game in GAMES:
        error = ""
        try:
            if sync_sources:
                with closing(_connect(db_path)) as connection:
                    enabled = connection.execute('SELECT enabled FROM effectiveness_settings WHERE game_type=?', (game,)).fetchone()[0]
                    pending = connection.execute("SELECT 1 FROM prediction_runs WHERE game_type=? AND status='locked' LIMIT 1", (game,)).fetchone()
                if enabled or pending:
                    sync_source(game, db_path)
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
    return result


def dispatch(args):
    if args.command == "report": return report(args.game, args.limit, args.db_path, args.level, args.page)
    if args.command == "settings": return settings(args.game, args.db_path)
    if args.command == "tickets": return ticket_page(args.game, args.prediction_id, args.page, args.db_path, args.prize_code, args.after_ticket_index, getattr(args, 'view', 'selected'))
    if args.command == "export": return export_cycle(args.game, args.cycle_id, args.db_path, args.level)
    if args.command == "export-file":
        from ai.effectiveness_xlsx import write_cycle_xlsx
        destination = Path(args.output).resolve()
        allowed = dp.RUNTIME_DIR.resolve() if getattr(args, 'personal_id', None) or not args.db_path else Path(args.db_path).resolve().parent
        # Output is always chosen by the server, under runtime.
        if not destination.is_relative_to(allowed) or destination.suffix != '.xlsx':
            raise ValueError("Đường dẫn file Excel không hợp lệ.")
        return write_cycle_xlsx(args.game, args.cycle_id, destination, args.db_path, args.level)
    if args.command == "configure":
        return configure(args.game, args.enabled == "true", args.ticket_count, args.actor, args.db_path,
                         play_mode=getattr(args, 'play_mode', 'normal'), bao_level=getattr(args, 'bao_level', None),
                         bao_count=getattr(args, 'bao_count', None))
    if args.command == "cycle":
        score_cycles(args.game, args.db_path)
        return cycle(args.game, args.db_path, configuration_hash=getattr(args, "configuration_hash", None))
    return tick(args.db_path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("report", "settings", "configure", "cycle", "tick", "tickets", "export", "export-file"):
        child = sub.add_parser(command)
        if command != "tick":
            child.add_argument("game", choices=(*GAMES, "KENO"))
        child.add_argument("--db-path", default=None, help=argparse.SUPPRESS)
        child.add_argument("--owner", default=None, help=argparse.SUPPRESS)
        child.add_argument("--personal-id", default=None, help=argparse.SUPPRESS)
        if command == "report":
            child.add_argument("--limit", type=int, default=100)
            child.add_argument("--level", type=int, default=10)
            child.add_argument("--page", type=int, default=1)
        if command == "configure":
            child.add_argument("--enabled", choices=("true", "false"), required=True)
            child.add_argument("--ticket-count", type=int, default=3)
            child.add_argument("--actor", required=True)
            child.add_argument('--play-mode', choices=('normal', 'bao'), default='normal')
            child.add_argument('--bao-level', type=int)
            child.add_argument('--bao-count', type=int)
        if command == 'cycle':
            child.add_argument('--configuration-hash')
        if command in ("export", "export-file"):
            child.add_argument("--cycle-id", required=True)
            child.add_argument("--level", type=int, default=10)
        if command == "export-file":
            child.add_argument("--output", required=True)
        if command == "tickets":
            child.add_argument('--view', choices=('selected', 'tickets', 'bao'), default='selected')
            child.add_argument("--prediction-id", required=True)
            child.add_argument("--page", type=int, default=1)
            child.add_argument("--prize-code", default=None)
            child.add_argument("--after-ticket-index", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        # Keep stdout exclusively JSON even if a legacy engine prints a diagnostic.
        with redirect_stdout(StringIO()):
            if args.owner and args.personal_id:
                result = billing.execute(args)
            elif args.command == 'tick' and args.db_path is None:
                result = billing.tick_all()
            else:
                result = dispatch(args)
    except Exception as exc:
        result = {"ok": False, "type": getattr(args, "game", ""), "error": str(exc), "message": str(exc)}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
