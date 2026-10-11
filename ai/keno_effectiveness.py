"""Prospective Keno comparisons: one atomic lock for all ten ticket sizes.

Draw identity/time comes from canonical, never from result arrival or wall-clock
rounding. Reports read compact recorded scores and only one page of tickets.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import uuid
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

from ai import ml_pipeline, prediction_effectiveness as pe, prediction_ledger as ledger
from ai import tracking_portfolio as portfolio
from ai.configs import data_paths as dp
from ai.prizes import classify_tickets, prize_counts, prize_statistics, PRIZE_SCOPE, RULE_VERSION
from backend.file_guard import resource_lock, version

GAME = "KENO"
LEVELS = tuple(range(1, 11))
PIPELINE = "keno_prospective_all_levels_v1"
PAGE_SIZE = 10
FIRST_MINUTE, LAST_MINUTE, INTERVAL = 368, 1312, 8


def _connect(db_path=None):
    connection = pe._connect(db_path)
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS keno_effectiveness_cycles (
            cycle_id TEXT PRIMARY KEY, target_draw_id TEXT NOT NULL UNIQUE,
            target_number INTEGER NOT NULL UNIQUE, cutoff_draw_id TEXT NOT NULL,
            created_at TEXT NOT NULL, deadline TEXT NOT NULL, data_hash TEXT NOT NULL,
            config_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'locked',
            scored_at TEXT NOT NULL DEFAULT '', actual_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS keno_effectiveness_pending
            ON keno_effectiveness_cycles(status,target_number);
        CREATE TABLE IF NOT EXISTS keno_effectiveness_source_state (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), state_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS keno_effectiveness_predictions (
            cycle_id TEXT NOT NULL REFERENCES keno_effectiveness_cycles(cycle_id),
            level INTEGER NOT NULL CHECK(level BETWEEN 1 AND 10),
            method TEXT NOT NULL CHECK(method IN ('web','random','bayesian','ewma')),
            prediction_id TEXT NOT NULL UNIQUE REFERENCES prediction_runs(prediction_id),
            PRIMARY KEY(cycle_id,level,method)
        );
        CREATE INDEX IF NOT EXISTS keno_effectiveness_level
            ON keno_effectiveness_predictions(level,cycle_id);
        CREATE TABLE IF NOT EXISTS keno_effectiveness_metrics (
            cycle_id TEXT NOT NULL REFERENCES keno_effectiveness_cycles(cycle_id),
            level INTEGER NOT NULL, method TEXT NOT NULL, day TEXT NOT NULL,
            mean_hits REAL NOT NULL, best_hits INTEGER NOT NULL,
            winning_rate REAL NOT NULL, full_match_rate REAL NOT NULL,
            brier REAL NOT NULL, log_loss REAL NOT NULL, ticket_count INTEGER NOT NULL,
            summary_json TEXT NOT NULL, PRIMARY KEY(cycle_id,level,method)
        );
        CREATE INDEX IF NOT EXISTS keno_effectiveness_metric_level
            ON keno_effectiveness_metrics(level,method,day);
        CREATE TRIGGER IF NOT EXISTS keno_effectiveness_cycle_guard
        BEFORE UPDATE ON keno_effectiveness_cycles WHEN
            OLD.status <> 'locked' OR NEW.status <> 'scored' OR
            NEW.cycle_id <> OLD.cycle_id OR NEW.target_draw_id <> OLD.target_draw_id OR
            NEW.target_number <> OLD.target_number OR NEW.cutoff_draw_id <> OLD.cutoff_draw_id OR
            NEW.created_at <> OLD.created_at OR NEW.deadline <> OLD.deadline OR
            NEW.data_hash <> OLD.data_hash OR NEW.config_json <> OLD.config_json
        BEGIN SELECT RAISE(ABORT,'Keno cycle is immutable after scoring'); END;
        CREATE TRIGGER IF NOT EXISTS keno_effectiveness_mapping_guard
        BEFORE UPDATE ON keno_effectiveness_predictions
        BEGIN SELECT RAISE(ABORT,'Keno mapping is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS keno_effectiveness_metrics_guard
        BEFORE UPDATE ON keno_effectiveness_metrics
        BEGIN SELECT RAISE(ABORT,'Keno metrics are immutable'); END;
    """)
    return connection


def draw_at(row):
    day = None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            day = datetime.strptime(str(row.get("date") or ""), fmt)
            break
        except ValueError:
            pass
    try:
        hour, minute = map(int, str(row.get("time") or "").split(":"))
        at = day.replace(hour=hour, minute=minute, tzinfo=pe.LOCAL_TZ)
    except (ValueError, AttributeError, TypeError):
        raise ValueError("Không xác minh được ngày/giờ kỳ Keno canonical.")
    slot = hour * 60 + minute
    if not FIRST_MINUTE <= slot <= LAST_MINUTE or (slot - FIRST_MINUTE) % INTERVAL:
        raise ValueError("Giờ Keno không khớp lịch 8 phút, từ 06:08 đến 21:52.")
    return at


def next_draw_at(at):
    if at.hour * 60 + at.minute == LAST_MINUTE:
        return (at + timedelta(days=1)).replace(hour=6, minute=8)
    return at + timedelta(minutes=INTERVAL)


def _snapshot():
    path = dp.get_canonical_csv_read_path(GAME)
    initial = version(path)
    if initial is None:
        raise ValueError("Chưa có lịch sử Keno canonical.")
    actual = ml_pipeline.load_actual_draws(GAME)
    if version(path) != initial:
        raise RuntimeError("Canonical Keno thay đổi trong lúc đọc; thử lại sau.")
    draws = sorted(actual.values(), key=lambda row: int(row["ky"]))
    if not draws:
        raise ValueError("Lịch sử Keno rỗng.")
    previous_at, previous_id = None, None
    anomalies = []
    now = pe._now()
    for index, row in enumerate(draws):
        pe._validate_actual_row(row, GAME)
        at = draw_at(row)
        if at > now:
            raise ValueError("Canonical Keno chứa kết quả tương lai.")
        identity = int(row["ky"])
        if previous_at is not None:
            bad_order = at <= previous_at
            # Missing old draws are allowed, but consecutive IDs must have the
            # exact scheduled successor, including the overnight boundary.
            bad_schedule = identity == previous_id + 1 and at != next_draw_at(previous_at)
            if bad_order or bad_schedule:
                if index == len(draws) - 1:
                    raise ValueError("Các kỳ Keno mới nhất không khớp mã kỳ và lịch quay; cần kiểm tra canonical.")
                anomalies.append({"cutoff": str(previous_id), "target": str(identity)})
        previous_at, previous_id = at, identity
    return {"path": path, "version": initial, "actual": actual, "draws": draws,
            "cutoff": str(previous_id), "target": str(previous_id + 1),
            "deadline": next_draw_at(previous_at), "dataHash": pe._digest(draws),
            "historyScheduleMismatchCount": len(anomalies)}


def _manifest(db_path=None):
    paths = [Path(__file__), dp.PROJECT_ROOT / "ai/prediction_effectiveness.py",
             dp.PROJECT_ROOT / "ai/prediction_ledger.py", dp.PROJECT_ROOT / "ai/prizes.py",
             dp.PROJECT_ROOT / "ai/predictors/ai_predict.py", dp.PROJECT_ROOT / "ai/adaptive_coverage.py",
             dp.PROJECT_ROOT / "ai/controlled_models.py", Path(portfolio.__file__)]
    models = ledger.list_models(GAME, "champion", db_path)
    for model in models:
        artifact = (model.get("artifact_paths") or {}).get("model")
        if artifact:
            paths.append(Path(artifact))
    return {"files": {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in paths if path.is_file()}, "champions": models}


def _multi_level_evaluation(predictor, items, size, strategies, minimum, limit, weekday):
    """Share feature/ranking work; preserve classic's winner at EACH pick size."""
    state = predictor.initialize_state(size)
    hits = {k: {s["key"]: [] for s in strategies} for k in LEVELS}
    start = max(0, len(items) - limit)
    for index, item in enumerate(items):
        actual = set(item["numbers"])
        if index >= start and len(state["history_draws"]) >= minimum:
            features = predictor.compute_feature_scores(state, item["weekday"])
            for strategy in strategies:
                ranking = predictor.build_ranking_from_strategy(features, strategy, size)
                for level in LEVELS:
                    hits[level][strategy["key"]].append(len(actual & set(ranking[:level])))
        predictor.update_state(state, item["numbers"], item["weekday"])
    features = predictor.compute_feature_scores(state, weekday)
    rankings = {s["key"]: predictor.build_ranking_from_strategy(features, s, size) for s in strategies}
    results = {}
    for level in LEVELS:
        results[level] = []
        for strategy in strategies:
            values = hits[level][strategy["key"]]
            average = sum(values) / len(values) if values else 0.0
            results[level].append({"key": strategy["key"], "label": strategy["label"],
                                   "samples": len(values), "avgHits": average,
                                   "avgHitRate": average / level, "hits": list(values),
                                   "ranking": list(rankings[strategy["key"]])})
        results[level].sort(key=lambda row: (row["avgHitRate"], row["avgHits"], row["samples"], row["label"]), reverse=True)
    return results


def _web_predictions(snapshot, count, db_path=None):
    from unittest.mock import patch
    from ai import controlled_models
    from ai.predictors import ai_predict as predictor
    draws = [{**row, "date_obj": draw_at(row).date(), "weekday": draw_at(row).weekday()}
             for row in snapshot["draws"]]
    summary = {"type": GAME, "ready": True, "bootstrapComplete": True,
               "historyFile": str(snapshot["path"]), "historyCount": len(draws),
               "latestKy": snapshot["cutoff"], "latestDate": draws[-1]["date"],
               "latestTime": draws[-1]["time"]}
    evaluate = predictor.evaluate_strategies
    champion = controlled_models.champion_prediction
    cache = {}

    def shared(items, target_size, size, strategies, minimum, limit, weekday):
        key = (size, minimum, limit, weekday, tuple(s["key"] for s in strategies))
        if size != 80:
            return evaluate(items, target_size, size, strategies, minimum, limit, weekday)
        if key not in cache:
            cache[key] = _multi_level_evaluation(predictor, items, size, strategies, minimum, limit, weekday)
        return cache[key][target_size]

    with patch.object(predictor, "sync_ai_history", return_value=summary), \
            patch.object(predictor, "build_readonly_sync_summary", return_value=summary), \
            patch.object(predictor, "load_ai_draws", return_value=draws), \
            patch.object(ml_pipeline, "load_actual_draws", return_value=snapshot["actual"]), \
            patch.object(predictor, "evaluate_strategies", side_effect=shared), \
            patch.object(controlled_models, "champion_prediction", side_effect=lambda *args: champion(*args, db_path=db_path)):
        return {level: portfolio.expand_web(predictor.predict_json(GAME, min(count, 8), level, engine="classic", risk_mode="balanced",
                                             prediction_mode="normal", username=pe.ACTOR, lock_ledger=False, pure=True)
                                            , portfolio.effective_count(count, 80, level), 80, level, snapshot)
                for level in LEVELS}


def _probabilities(snapshot):
    counts = defaultdict(int)
    ewma = {n: 0.25 for n in range(1, 81)}
    decay = 0.5 ** (1 / pe.HALF_LIFE)
    for row in snapshot["draws"]:
        numbers = set(row["main"])
        for n in ewma:
            counts[n] += n in numbers
            ewma[n] = decay * ewma[n] + (1 - decay) * (n in numbers)
    denominator = len(snapshot["draws"]) + pe.PRIOR_STRENGTH
    return {"random": {n: .25 for n in ewma},
            "bayesian": {n: (counts[n] + pe.PRIOR_STRENGTH * .25) / denominator for n in ewma},
            "ewma": ewma}


def _baseline(method, level, count, snapshot, probabilities):
    count = portfolio.effective_count(count, 80, level)
    seed = int(pe._digest({"method": method, "level": level, "count": count,
                          "target": snapshot["target"], "hash": snapshot["dataHash"], "pipeline": PIPELINE})[:12], 16) % 2147483647
    rng, seen, tickets = random.Random(seed), set(), []
    large_mains = portfolio.unique_mains(probabilities, level, count, seed) if count > 8 else None
    for index in range(count):
        for attempt in range(1000):
            if large_mains is not None:
                main = list(large_mains[index])
                break
            if method == "random":
                main = sorted(rng.sample(range(1, 81), level))
            elif index == 0 and attempt == 0:
                main = sorted(sorted(probabilities, key=lambda n: (-probabilities[n], n))[:level])
            else:
                main = sorted(sorted(probabilities, key=lambda n: -math.log(max(rng.random(), 1e-12)) / probabilities[n])[:level])
            if tuple(main) not in seen:
                break
        else:
            raise ValueError("Không tạo đủ các vé Keno khác nhau.")
        tickets.append({"main": main, "special": None})
        seen.add(tuple(main))
    return {"ok": True, "ready": True, "type": GAME, "engine": method,
            "latestKy": snapshot["cutoff"], "nextKy": snapshot["target"], "pickSize": level,
            "tickets": tickets, "probabilities": {str(n): p for n, p in probabilities.items()},
            "randomSeed": seed, "modelId": f"{method}_{PIPELINE}", "modelVersion": PIPELINE,
            "allocationPolicy": portfolio.VERSION if count > 8 else "legacy_seeded_unique",
            "probabilityCalibrationStatus": "uncalibrated", "predictionMode": "normal"}


def _validate(payload, level, count, snapshot):
    if payload.get("ok") is False or payload.get("ready") is False:
        raise ValueError("Luồng web Keno chưa sẵn sàng; chưa khóa các đối chứng.")
    if payload.get("type") != GAME or str(payload.get("latestKy", "")).lstrip("#") != snapshot["cutoff"] or str(payload.get("nextKy", "")).lstrip("#") != snapshot["target"]:
        raise ValueError("Dự đoán Keno không khớp kỳ/cutoff canonical.")
    tickets = payload.get("tickets") or []
    if payload.get("pickSize") != level or len(tickets) != count:
        raise ValueError("Bậc/số vé Keno không khớp cấu hình.")
    if len({tuple(sorted(t.get("main") or [])) for t in tickets}) != count:
        raise ValueError("Danh mục Keno có vé trùng nhau.")
    for ticket in tickets:
        main = ticket.get("main") or []
        if len(main) != level or len(set(main)) != level or any(type(n) is not int or not 1 <= n <= 80 for n in main) or ticket.get("special") is not None:
            raise ValueError("Bộ số Keno không hợp lệ.")
    probs = ledger.normalize_probability_payload(payload.get("probabilities"))
    if set(probs) != set(range(1, 81)) or any(not math.isfinite(p) or not 0 <= p <= 1 for p in probs.values()) or abs(sum(probs.values()) - 20) > 1e-5:
        raise ValueError("Vector xác suất Keno cần đủ 80 số và tổng bằng 20.")


def _recorded_payload(payload):
    # Ranking/probability compatibility aliases repeat the same 80 numbers.
    # Keep the authoritative vector plus execution provenance, not UI exports.
    keys = ("ok", "ready", "type", "engine", "engineLabel", "model", "modelId", "modelVersion",
            "modelTrainingCutoff", "modelArtifactHash", "registryModel", "configHash", "predictionMode",
            "riskMode", "latestKy", "latestDate", "latestTime", "nextKy", "pickSize", "bundleCount",
            "tickets", "probabilities", "probabilityCalibrationStatus", "randomSeed",
            "adaptiveCoverageVersion", "adaptiveCoverage", "probabilitySummary", "trackingPortfolio", "allocationPolicy")
    return {key: payload[key] for key in keys if key in payload}


def cycle(db_path=None, force=True):
    database = Path(db_path or ledger.DEFAULT_DB_PATH)
    with resource_lock(database.parent / "effectiveness_keno", timeout=15), closing(_connect(db_path)) as connection:
        settings = pe._settings(connection.execute("SELECT * FROM effectiveness_settings WHERE game_type=?", (GAME,)).fetchone())
        if not settings["enabled"] and not force:
            return {"ok": True, "type": GAME, "status": "disabled"}
        snapshot = _snapshot()
        past_pending = connection.execute("SELECT target_draw_id,deadline FROM keno_effectiveness_cycles WHERE status='locked' AND target_number<=?", (int(snapshot["cutoff"]),)).fetchall()
        for pending in past_pending:
            observed = snapshot["actual"].get(pending["target_draw_id"])
            if observed is None or draw_at(observed) != datetime.fromisoformat(pending["deadline"]):
                raise ValueError(f"Kỳ Keno {pending['target_draw_id']} đã khóa còn thiếu kết quả đúng mã/giờ. Cần bổ sung canonical trước khi khóa kỳ xa hơn.")
        existing = connection.execute("SELECT cycle_id FROM keno_effectiveness_cycles WHERE target_draw_id=?", (snapshot["target"],)).fetchone()
        if existing:
            return {"ok": True, "type": GAME, "status": "already_locked", "cycleId": existing[0], "targetDrawId": snapshot["target"]}
        pe._guard(snapshot)
        manifest = _manifest(db_path)
        count = settings["ticketCount"]
        counts_by_level = {str(level): portfolio.effective_count(count, 80, level) for level in LEVELS}
        web = _web_predictions(snapshot, count, db_path)
        probabilities = _probabilities(snapshot)
        payloads = {(level, method): dict(web[level]) if method == "web" else
                    _baseline(method, level, count, snapshot, probabilities[method])
                    for level in LEVELS for method in pe.METHODS}
        for (level, method), payload in payloads.items():
            _validate(payload, level, counts_by_level[str(level)], snapshot)
            if method == "web" and not payload.get("trackingPortfolio"):
                payload["randomSeed"] = int((payload.get("adaptiveCoverage") or {}).get("seed", payload.get("randomSeed", 0)))
        payloads = {key: _recorded_payload(payload) for key, payload in payloads.items()}
        config = {**settings, "pipeline": PIPELINE, "levels": list(LEVELS), "sourceManifest": manifest,
                  "ticketCountsByLevel": counts_by_level, "allocationPolicy": portfolio.VERSION if count > 8 else "legacy",
                  "historyScheduleMismatchCount": snapshot["historyScheduleMismatchCount"],
                  "actualWebEngines": {str(k): web[k].get("engine") for k in LEVELS},
                  "actualWebModels": {str(k): web[k].get("modelId", web[k].get("modelVersion", "classic")) for k in LEVELS}}
        cycle_id = str(uuid.uuid4())
        with resource_lock(snapshot["path"]):
            fresh = _snapshot()
            if fresh["version"] != snapshot["version"] or fresh["dataHash"] != snapshot["dataHash"] or _manifest(db_path) != manifest:
                raise RuntimeError("Dữ liệu/mã/model Keno thay đổi; hủy toàn bộ lần khóa.")
            pe._guard(fresh)
            connection.execute("BEGIN IMMEDIATE")
            try:
                current = pe._settings(connection.execute("SELECT * FROM effectiveness_settings WHERE game_type=?", (GAME,)).fetchone())
                if current != settings:
                    raise RuntimeError("Cấu hình Keno thay đổi khi tạo vé; thử lại sau.")
                connection.execute("INSERT INTO keno_effectiveness_cycles(cycle_id,target_draw_id,target_number,cutoff_draw_id,created_at,deadline,data_hash,config_json) VALUES(?,?,?,?,?,?,?,?)",
                                   (cycle_id, snapshot["target"], int(snapshot["target"]), snapshot["cutoff"], ledger.now_iso(), snapshot["deadline"].isoformat(), snapshot["dataHash"], ledger.canonical_json(config)))
                for (level, method), payload in payloads.items():
                    payload.update({"predictionDeadline": snapshot["deadline"].isoformat(), "dataHash": snapshot["dataHash"],
                                    "modelId": payload.get("modelId") or f"web_{pe._digest(manifest)[:20]}", "effectivenessLevel": level})
                    saved = ledger.lock_prediction(payload, username=pe.ACTOR, connection=connection,
                                                   config_hash=pe._digest(config), random_seed=payload.get("randomSeed", 0), feature_version=PIPELINE)
                    connection.execute("INSERT INTO keno_effectiveness_predictions VALUES(?,?,?,?)", (cycle_id, level, method, saved["prediction_id"]))
                pe._guard(fresh)
                if version(snapshot["path"]) != snapshot["version"]:
                    raise RuntimeError("Canonical thay đổi trước khi ghi chu kỳ Keno.")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return {"ok": True, "type": GAME, "status": "locked", "cycleId": cycle_id,
                "targetDrawId": snapshot["target"], "deadline": snapshot["deadline"].isoformat(),
                "ticketCount": count, "ticketCountsByLevel": counts_by_level, "levelCount": 10, "totalTickets": 4 * sum(counts_by_level.values()),
                "message": f"Đã khóa đủ 10 bậc Keno cho kỳ {snapshot['target']} · {4 * sum(counts_by_level.values()):,} vé."}


def score_cycles(db_path=None):
    scored, errors = [], []
    with closing(_connect(db_path)) as connection:
        pending = connection.execute("SELECT * FROM keno_effectiveness_cycles WHERE status='locked' ORDER BY target_number").fetchall()
        if not pending:
            return {"ok": True, "type": GAME, "scored": [], "errors": []}
        path = dp.get_canonical_csv_read_path(GAME)
        initial = version(path)
        actual = ml_pipeline.load_actual_draws(GAME)
        if initial != version(path):
            raise RuntimeError("Canonical thay đổi trong khi đọc kết quả Keno.")
        for cycle_row in pending:
            target = cycle_row["target_draw_id"]
            if target not in actual:
                continue
            try:
                row = actual[target]
                pe._validate_actual_row(row, GAME)
                at = draw_at(row)
                if at > pe._now() or at != datetime.fromisoformat(cycle_row["deadline"]):
                    raise ValueError("Ngày/giờ kết quả không khớp mã kỳ Keno đã khóa.")
                predictions = connection.execute("SELECT kp.level,kp.method,pr.* FROM keno_effectiveness_predictions kp JOIN prediction_runs pr ON pr.prediction_id=kp.prediction_id WHERE kp.cycle_id=?", (cycle_row["cycle_id"],)).fetchall()
                if {(p["level"], p["method"]) for p in predictions} != {(k, m) for k in LEVELS for m in pe.METHODS}:
                    raise ValueError("Chu kỳ Keno không đủ 10 bậc và bốn phương pháp.")
                # Heavy calculations outside the write transaction; keep other
                # account requests responsive while checking all 120 tickets.
                computed = []
                snapshot = {"cutoff": cycle_row["cutoff_draw_id"], "target": target}
                config = json.loads(cycle_row["config_json"])
                for prediction in predictions:
                    payload = json.loads(prediction["payload_json"])
                    if prediction["username"] != pe.ACTOR or prediction["status"] != "locked" or ledger.payload_checksum(payload) != prediction["payload_checksum"]:
                        raise ValueError("Dự đoán Keno đã khóa không còn hợp lệ.")
                    count = config.get("ticketCountsByLevel", {}).get(str(prediction["level"]), config["ticketCount"])
                    _validate(payload, prediction["level"], count, snapshot)
                    if datetime.fromisoformat(prediction["created_at"]) >= at:
                        raise ValueError("Bộ số Keno không được khóa trước giờ quay.")
                    metrics = ledger.score_prediction_payload(payload, row, 80, 20, prediction["level"])
                    prizes = metrics["prize_results"]
                    hits = [item["hit_count"] for item in metrics["per_ticket"]]
                    compact = {"hitHistogram": {str(h): hits.count(h) for h in range(prediction["level"] + 1)},
                               "prizeCounts": prize_counts(prizes), "prizeStatistics": prize_statistics(prizes)}
                    computed.append((prediction, pe._score_storage(metrics), compact, sum(p["isWinning"] is True for p in prizes) / len(prizes), sum(h == prediction["level"] for h in hits) / len(hits)))
                stamp = ledger.now_iso()
                connection.execute("BEGIN IMMEDIATE")
                if connection.execute("SELECT status FROM keno_effectiveness_cycles WHERE cycle_id=?", (cycle_row["cycle_id"],)).fetchone()[0] != "locked":
                    connection.rollback()
                    continue
                for prediction, metrics, compact, winning, full in computed:
                    connection.execute("INSERT INTO prediction_scores VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                       (str(uuid.uuid4()), prediction["prediction_id"], stamp, target, metrics["hit_count"], metrics["special_hit"], metrics["brier_score"], metrics["log_loss"], metrics["lift"], ledger.canonical_json(metrics), ledger.SCORING_VERSION))
                    connection.execute("UPDATE prediction_runs SET status='scored' WHERE prediction_id=? AND status='locked'", (prediction["prediction_id"],))
                    connection.execute("INSERT INTO keno_effectiveness_metrics VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                                       (cycle_row["cycle_id"], prediction["level"], prediction["method"], at.date().isoformat(), metrics["mean_hits_per_ticket"], metrics["hit_count"], winning, full, metrics["brier_score"], metrics["log_loss"], metrics["ticket_count"], ledger.canonical_json(compact)))
                connection.execute("UPDATE keno_effectiveness_cycles SET status='scored',scored_at=?,actual_json=? WHERE cycle_id=?", (stamp, ledger.canonical_json({"main": row["main"], "special": None, "drawAt": at.isoformat()}), cycle_row["cycle_id"]))
                connection.commit()
                scored.append(target)
            except Exception as exc:
                connection.rollback()
                errors.append({"targetDrawId": target, "error": str(exc)})
    return {"ok": not errors, "type": GAME, "scored": scored, "errors": errors}


def _summary(method, rows, pairs, level):
    daily = defaultdict(list)
    for row in pairs:
        daily[row["day"]].append(row["delta"])
    count, days = len(rows), len(daily)
    delta = mean(row["delta"] for row in pairs) if pairs else None
    # Bootstrap whole days, preserving within-day draw dependence. Selecting
    # levels/methods is exploratory, so no automatic promotion or winner.
    ci = None
    if days >= 2:
        blocks = [(sum(daily[day]), len(daily[day])) for day in sorted(daily)]
        rng = random.Random(20261008 + level)
        values = []
        for _ in range(1000):
            sampled = rng.choices(blocks, k=days)
            values.append(sum(total for total, n in sampled) / sum(n for total, n in sampled))
        values.sort()
        ci = {"lower": values[24], "upper": values[974]}
    decision = "baseline" if method == "random" else "insufficient_evidence" if count < 300 or days < 7 else "possible_improvement" if ci and ci["lower"] > 0 else "no_clear_advantage"
    return {"key": method, "label": pe.METHODS[method], "sampleCount": count, "dayCount": days,
            "meanHits": mean(row["mean_hits"] for row in rows) if rows else None,
            "winningTicketRate": mean(row["winning_rate"] for row in rows) if rows else None,
            "fullMatchRate": mean(row["full_match_rate"] for row in rows) if rows else None,
            "brierScore": mean(row["brier"] for row in rows) if rows else None,
            "logLoss": mean(row["log_loss"] for row in rows) if rows else None,
            "expectedRandomHits": level / 4, "deltaVsRandom": delta,
            "ci95": ci, "ciMethod": "paired_day_block_bootstrap", "decision": decision}


def report(level=10, page=1, db_path=None):
    if type(level) is not int or level not in LEVELS or type(page) is not int or not 1 <= page <= 1000000:
        raise ValueError("Bậc Keno phải từ 1 đến 10 và trang phải là số nguyên dương.")
    with closing(_connect(db_path)) as connection:
        connection.execute("BEGIN")
        settings_row = connection.execute("SELECT * FROM effectiveness_settings WHERE game_type=?", (GAME,)).fetchone()
        counts = {row["status"]: row["n"] for row in connection.execute("SELECT status,COUNT(*) n FROM keno_effectiveness_cycles GROUP BY status")}
        total, scored = sum(counts.values()), counts.get("scored", 0)
        pages = max(1, math.ceil(total / PAGE_SIZE))
        page = min(page, pages)
        selected = connection.execute("SELECT * FROM keno_effectiveness_cycles ORDER BY target_number DESC LIMIT ? OFFSET ?", (PAGE_SIZE, (page - 1) * PAGE_SIZE)).fetchall()
        # Only scalar metrics for all levels; no historical payloads/probability
        # vectors or 120-ticket pages are read for the overview.
        overview = []
        aggregates = connection.execute("SELECT level,method,COUNT(*) n,COUNT(DISTINCT day) days,AVG(mean_hits) hits,AVG(winning_rate) wins,AVG(full_match_rate) full_rate FROM keno_effectiveness_metrics GROUP BY level,method").fetchall()
        for k in LEVELS:
            values = {r["method"]: {"sampleCount": r["n"], "dayCount": r["days"], "meanHits": r["hits"], "winningTicketRate": r["wins"], "fullMatchRate": r["full_rate"]} for r in aggregates if r["level"] == k}
            random_hits = values.get("random", {}).get("meanHits")
            for item in values.values():
                item["deltaVsRandom"] = item["meanHits"] - random_hits if random_hits is not None else None
            overview.append({"level": k, "expectedRandomHits": k / 4, "methods": values})
        sample_rows = connection.execute("SELECT method,day,mean_hits,winning_rate,full_match_rate,brier,log_loss FROM keno_effectiveness_metrics WHERE level=?", (level,)).fetchall()
        pair_rows = connection.execute("SELECT m.method,m.day,m.mean_hits-r.mean_hits delta FROM keno_effectiveness_metrics m JOIN keno_effectiveness_metrics r ON r.cycle_id=m.cycle_id AND r.level=m.level AND r.method='random' WHERE m.level=?", (level,)).fetchall()
        summaries = [_summary(method, [r for r in sample_rows if r["method"] == method], [r for r in pair_rows if r["method"] == method], level) for method in pe.METHODS]
        cycles = []
        for row in selected:
            actual = json.loads(row["actual_json"])
            item = {"cycleId": row["cycle_id"], "targetDrawId": row["target_draw_id"], "cutoffDrawId": row["cutoff_draw_id"],
                    "createdAt": row["created_at"], "deadline": row["deadline"], "scoredAt": row["scored_at"],
                    "status": row["status"], "actualMain": actual.get("main", []), "actualSpecial": None,
                    "actualSpecialStatus": "not_applicable", "actualSource": "recorded_ledger_score" if row["status"] == "scored" else "pending",
                    "config": json.loads(row["config_json"]), "level": level, "methods": {}}
            # Avoid repeating a large source manifest twenty times in HTTP.
            item["config"].pop("sourceManifest", None)
            predictions = connection.execute("SELECT kp.method,pr.prediction_id,pr.engine,pr.model_id,pr.random_seed,pr.status,km.mean_hits,km.best_hits,km.summary_json FROM keno_effectiveness_predictions kp JOIN prediction_runs pr ON pr.prediction_id=kp.prediction_id LEFT JOIN keno_effectiveness_metrics km ON km.cycle_id=kp.cycle_id AND km.level=kp.level AND km.method=kp.method WHERE kp.cycle_id=? AND kp.level=?", (row["cycle_id"], level)).fetchall()
            for prediction in predictions:
                tickets, pagination = pe._ticket_slice(connection, prediction["prediction_id"])
                results = classify_tickets(GAME, tickets, actual if row["status"] == "scored" else None)
                compact = json.loads(prediction["summary_json"] or "{}")
                item["methods"][prediction["method"]] = {"predictionId": prediction["prediction_id"], "tickets": tickets,
                                                          "ticketPagination": pagination, "ticketCount": pagination["total"],
                                                          "ticketResults": results, "prizeCounts": compact.get("prizeCounts", {"PENDING": pagination["total"]}), "prizeStatistics": compact.get("prizeStatistics", {**prize_statistics([]), "ticketCount": pagination["total"], "pendingTicketCount": pagination["total"]}),
                                                          "meanHits": prediction["mean_hits"], "bestHits": prediction["best_hits"],
                                                          "engine": prediction["engine"], "modelId": prediction["model_id"], "seed": prediction["random_seed"], "status": prediction["status"]}
            cycles.append(item)
        configurations = connection.execute("SELECT config_json FROM keno_effectiveness_cycles GROUP BY config_json").fetchall()
        source_row = connection.execute("SELECT state_json FROM keno_effectiveness_source_state WHERE singleton=1").fetchone()
        source_sync = json.loads(source_row[0]) if source_row else {}
        config_count = len(configurations)
        historical_anomalies = max((json.loads(r["config_json"]).get("historyScheduleMismatchCount", 0) for r in configurations), default=0)
        return {"ok": True, "type": GAME, "label": "Keno", "level": level, "levels": overview,
                "settings": pe._settings(settings_row), "counts": {"total": total, "scored": scored, "locked": total - scored},
                "methods": summaries, "cycles": cycles, "pagination": {"page": page, "pageSize": PAGE_SIZE, "totalPages": pages, "total": total},
                "configurationCount": config_count, "mixedConfigurations": config_count > 1,
                "historyScheduleMismatchCount": historical_anomalies,
                "scope": "main_numbers_only", "metricWeighting": "equal_weight_per_draw", "prizeScope": PRIZE_SCOPE, "prizeRuleVersion": RULE_VERSION,
                "automation": {"lastError": settings_row["last_error"], "lastTick": settings_row["last_tick"], "nextTargetDrawId": settings_row["next_target"], "sourceSync": source_sync},
                "notes": ["Mỗi kỳ khóa đồng thời 10 bậc × 4 phương pháp. Đổi bậc hoặc trang chỉ đổi phần xem, không tạo lại vé.",
                          "Tối đa 10.000 vé khác nhau/phương pháp/bậc; bậc 1 tối đa 80 và bậc 2 tối đa 3.160. Mỗi trang vé hiển thị 20; thống kê chấm toàn bộ danh mục.",
                          f"Bậc {level}: số trùng kỳ vọng ngẫu nhiên là {level / 4:g} số/vé; chỉ so các vé cùng bậc và ngân sách.",
                          "Tỷ lệ có giải gồm cả trùng 0 ở bậc 8–10; trùng đủ và có giải là hai chỉ số riêng. Không tính tiền lĩnh thưởng.",
                          "Chấm theo mã kỳ và giờ quay canonical. Kết quả trễ giữ kỳ đã khóa; không cộng 8 phút từ thời điểm nhận dữ liệu.",
                          "Nếu kỳ gần nhất chưa cập nhật và hạn kỳ tiếp theo đã qua: bỏ lỡ lần khóa, chờ canonical mới; không nhảy kỳ hoặc tạo ngược.",
                          "So sánh dùng mọi kỳ đã chấm; nhật ký 10 kỳ/trang. CI ghép cặp theo khối ngày; dưới 300 kỳ hoặc 7 ngày còn thiếu bằng chứng.",
                          "Thử 10 bậc và nhiều phương pháp là phân tích thăm dò, chưa điều chỉnh thử nhiều giả thuyết; không tự chọn bậc thắng hoặc promote.",
                          f"Snapshot đã khóa có {historical_anomalies} cặp kỳ lịch sử lệch lịch giờ; giữ nguyên dữ liệu gốc và kiểm tra chặt các kỳ mới nhất trước khi khóa.",
                          "Xác suất biên chưa hiệu chỉnh; nhiều kỳ trong một ngày không bảo đảm dự đoán trúng kỳ sau."]}


def _sync_source(db_path=None):
    """Poll only tracking data; no bootstrap, model fitting or scoring exports."""
    database = Path(db_path or ledger.DEFAULT_DB_PATH)
    with resource_lock(database.parent / "keno_effectiveness_source", timeout=1):
        with closing(_connect(db_path)) as connection:
            row = connection.execute("SELECT state_json FROM keno_effectiveness_source_state WHERE singleton=1").fetchone()
            state = json.loads(row[0]) if row else {}
            pending = [dict(r) for r in connection.execute("SELECT target_draw_id,deadline FROM keno_effectiveness_cycles WHERE status='locked' ORDER BY target_number")]
        now = pe._now()
        local = now.astimezone(pe.LOCAL_TZ)
        minute = local.hour * 60 + local.minute
        # Include the closing result's publication delay; overnight predictions
        # still lock from the last canonical draw without repeated HTTP calls.
        if not FIRST_MINUTE <= minute <= 22 * 60 + 2:
            return {**state, "status": "outside_hours"}
        if state.get("lastAttempt") and 0 <= (now - datetime.fromisoformat(state["lastAttempt"])).total_seconds() < 55:
            return state
        stamp = now.isoformat(timespec="seconds")
        try:
            from backend import keno_live_sync
            refreshed = keno_live_sync.refresh(now=now, pending=pending)
            state = {**state, **refreshed, "lastAttempt": stamp, "lastSuccess": stamp, "error": ""}
        except Exception as exc:
            state = {**state, "lastAttempt": stamp, "status": "error", "error": str(exc)[:600]}
        with closing(_connect(db_path)) as connection:
            connection.execute("INSERT INTO keno_effectiveness_source_state VALUES(1,?) ON CONFLICT(singleton) DO UPDATE SET state_json=excluded.state_json", (ledger.canonical_json(state),))
        return state


def tick(db_path=None, sync_source=None):
    error, target = "", ""
    synchronization = None
    # Explicit/private DBs and read-only report requests never contact a source.
    # The production Java worker invokes tick without a DB argument each minute.
    if sync_source is True or (sync_source is None and db_path is None):
        with closing(_connect(db_path)) as connection:
            enabled = bool(connection.execute("SELECT enabled FROM effectiveness_settings WHERE game_type=?", (GAME,)).fetchone()[0])
            pending = connection.execute("SELECT 1 FROM keno_effectiveness_cycles WHERE status='locked' LIMIT 1").fetchone() is not None
        if enabled or pending:
            try:
                synchronization = _sync_source(db_path)
            except Exception as exc:
                synchronization = {"status": "error", "error": str(exc)[:600]}
    try:
        scoring = score_cycles(db_path)
        error = "; ".join(item["error"] for item in scoring["errors"])
        action = cycle(db_path, force=False)
        target = action.get("targetDrawId", "")
        result = {"ok": not error, "type": GAME, "scoring": scoring, "cycle": action}
    except Exception as exc:
        error = str(exc)
        result = {"ok": False, "type": GAME, "error": error}
    if synchronization is not None:
        result["sourceSync"] = synchronization
    with closing(_connect(db_path)) as connection:
        connection.execute("UPDATE effectiveness_settings SET last_tick=?,last_error=?,next_target=? WHERE game_type=?", (ledger.now_iso(), error, target, GAME))
    return result
