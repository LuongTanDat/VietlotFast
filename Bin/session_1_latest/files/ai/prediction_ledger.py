from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
import random
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from ai.configs import data_paths as dp
from ai.evaluation.metrics import brier_score, lift, log_loss
from ai.evaluation.probability import scores_to_probabilities

DEFAULT_DB_PATH = dp.RUNTIME_DIR / "lotto_web.db"
SCORING_VERSION = "ledger_scoring_v2"
EFFECTIVENESS_SYSTEM_ACTOR = "__effectiveness_system__"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_checksum(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    db_path = Path(db_path or DEFAULT_DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path), timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    migrate(connection)
    return connection


def migrate(connection: sqlite3.Connection | None = None, db_path: str | Path | None = None) -> dict[str, Any]:
    own_connection = connection is None
    connection = connection or sqlite3.connect(str(Path(db_path or DEFAULT_DB_PATH)), timeout=30, isolation_level=None)
    try:
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS prediction_runs (
                prediction_id TEXT PRIMARY KEY,
                username TEXT NOT NULL DEFAULT '',
                game_type TEXT NOT NULL,
                target_draw_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                data_cutoff_draw_id TEXT NOT NULL DEFAULT '',
                model_id TEXT NOT NULL DEFAULT '',
                model_version TEXT NOT NULL DEFAULT '',
                feature_version TEXT NOT NULL DEFAULT '',
                config_hash TEXT NOT NULL DEFAULT '',
                random_seed INTEGER NOT NULL DEFAULT 0,
                prediction_mode TEXT NOT NULL DEFAULT 'normal',
                engine TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL CHECK(status IN ('locked','scored','void')),
                probabilities_json TEXT NOT NULL DEFAULT '{}',
                tickets_json TEXT NOT NULL DEFAULT '[]',
                payload_json TEXT NOT NULL DEFAULT '{}',
                payload_checksum TEXT NOT NULL DEFAULT '',
                error_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS prediction_scores (
                score_id TEXT PRIMARY KEY,
                prediction_id TEXT NOT NULL,
                scored_at TEXT NOT NULL,
                actual_draw_id TEXT NOT NULL,
                hit_count INTEGER NOT NULL DEFAULT 0,
                special_hit INTEGER NOT NULL DEFAULT 0,
                brier_score REAL NOT NULL DEFAULT 0,
                log_loss REAL NOT NULL DEFAULT 0,
                lift REAL NOT NULL DEFAULT 0,
                metrics_json TEXT NOT NULL DEFAULT '{}',
                scoring_version TEXT NOT NULL DEFAULT 'ledger_scoring_v1',
                FOREIGN KEY(prediction_id) REFERENCES prediction_runs(prediction_id),
                UNIQUE(prediction_id, actual_draw_id, scoring_version)
            );

            CREATE TABLE IF NOT EXISTS model_registry (
                model_id TEXT PRIMARY KEY,
                version TEXT NOT NULL,
                game_type TEXT NOT NULL,
                trained_at TEXT NOT NULL,
                trained_data_cutoff TEXT NOT NULL DEFAULT '',
                feature_version TEXT NOT NULL DEFAULT '',
                config_hash TEXT NOT NULL DEFAULT '',
                artifact_paths_json TEXT NOT NULL DEFAULT '{}',
                validation_metrics_json TEXT NOT NULL DEFAULT '{}',
                outer_backtest_metrics_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL CHECK(status IN ('champion','candidate','archived','rejected')),
                promotion_reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS training_runs (
                training_run_id TEXT PRIMARY KEY,
                game_type TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL DEFAULT '',
                data_cutoff_draw_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'started',
                candidate_model_id TEXT NOT NULL DEFAULT '',
                metrics_json TEXT NOT NULL DEFAULT '{}',
                payload_json TEXT NOT NULL DEFAULT '{}',
                error_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_prediction_runs_game_target
                ON prediction_runs(game_type, target_draw_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_prediction_runs_status
                ON prediction_runs(status, game_type);
            CREATE INDEX IF NOT EXISTS idx_prediction_scores_prediction
                ON prediction_scores(prediction_id);
            CREATE INDEX IF NOT EXISTS idx_model_registry_game_status
                ON model_registry(game_type, status, updated_at);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_model_registry_one_champion
                ON model_registry(game_type) WHERE status = 'champion';
            CREATE INDEX IF NOT EXISTS idx_training_runs_game_status
                ON training_runs(game_type, status, started_at);

            CREATE TRIGGER IF NOT EXISTS prediction_runs_locked_payload_immutable
            BEFORE UPDATE ON prediction_runs
            WHEN OLD.status IN ('locked','scored') AND (
                NEW.prediction_id <> OLD.prediction_id OR
                NEW.username <> OLD.username OR
                NEW.game_type <> OLD.game_type OR
                NEW.target_draw_id <> OLD.target_draw_id OR
                NEW.created_at <> OLD.created_at OR
                NEW.data_cutoff_draw_id <> OLD.data_cutoff_draw_id OR
                NEW.model_id <> OLD.model_id OR
                NEW.model_version <> OLD.model_version OR
                NEW.feature_version <> OLD.feature_version OR
                NEW.config_hash <> OLD.config_hash OR
                NEW.random_seed <> OLD.random_seed OR
                NEW.prediction_mode <> OLD.prediction_mode OR
                NEW.engine <> OLD.engine OR
                NEW.probabilities_json <> OLD.probabilities_json OR
                NEW.tickets_json <> OLD.tickets_json OR
                NEW.payload_json <> OLD.payload_json OR
                NEW.payload_checksum <> OLD.payload_checksum
            )
            BEGIN
                SELECT RAISE(ABORT, 'locked prediction payload is immutable');
            END;
            """
        )
        return {"ok": True, "db_path": str(db_path or DEFAULT_DB_PATH)}
    finally:
        if own_connection:
            connection.close()


def _json_loads(text: str, default: Any) -> Any:
    try:
        return json.loads(text or "")
    except Exception:
        return default


def normalize_probability_payload(value: Any) -> dict[int, float]:
    if isinstance(value, dict):
        return {int(key): float(probability) for key, probability in value.items()}
    if isinstance(value, list):
        result: dict[int, float] = {}
        for item in value:
            if isinstance(item, dict) and item.get("number") is not None:
                result[int(item.get("number"))] = float(item.get("probability", item.get("p", 0.0)) or 0.0)
        return result
    return {}


def row_to_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    for key in ("probabilities_json", "tickets_json", "payload_json", "error_json", "metrics_json",
                "score_metrics_json", "artifact_paths_json", "validation_metrics_json", "outer_backtest_metrics_json"):
        if key in payload:
            parsed_key = key[:-5] if key.endswith("_json") else key
            payload[parsed_key] = _json_loads(str(payload.get(key) or ""), {} if key != "tickets_json" else [])
    return payload


def lock_prediction(
    payload: dict[str, Any],
    username: str = "",
    db_path: str | Path | None = None,
    model_id: str = "",
    model_version: str = "",
    feature_version: str = "",
    config_hash: str = "",
    random_seed: int = 20260403,
    status: str = "locked",
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    game_type = str(payload.get("type") or payload.get("game_type") or "").strip().upper()
    if not game_type:
        raise ValueError("prediction payload is missing game type")
    target_draw_id = str(payload.get("target_draw_id") or payload.get("targetDrawId") or payload.get("nextKy") or "").strip().lstrip("#")
    if not target_draw_id:
        raise ValueError("prediction payload is missing target draw id")
    data_cutoff_draw_id = str(
        payload.get("data_cutoff_draw_id")
        or payload.get("latestKy")
        or (payload.get("dataset") or {}).get("latest_draw_id")
        or ""
    ).strip().lstrip("#")
    if not target_draw_id.isdecimal() or not data_cutoff_draw_id.isdecimal():
        raise ValueError("target and data cutoff must be numeric draw IDs")
    if int(target_draw_id) <= int(data_cutoff_draw_id):
        raise ValueError("target draw must be after data cutoff")
    deadline = payload.get("predictionDeadline") or payload.get("prediction_deadline")
    if deadline:
        parsed_deadline = datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
        if parsed_deadline.tzinfo is None or datetime.now(timezone.utc) >= parsed_deadline:
            raise ValueError("prediction deadline has passed or lacks timezone")
    tickets = list(payload.get("tickets") or [])
    probabilities = normalize_probability_payload(
        payload.get("probabilities")
        or payload.get("calibratedProbability")
        or payload.get("calibrated_probability")
        or {}
    )
    checksum = payload_checksum(payload)
    prediction_id = str(uuid.uuid4())
    created_at = now_iso()
    model_id = str(model_id or payload.get("modelId") or payload.get("model_id") or "")
    model_version = str(model_version or payload.get("modelVersion") or "")
    config_hash = str(config_hash or payload.get("configHash") or "")
    own_connection = connection is None
    connection = connection or connect(db_path)
    try:
        # A caller-owned connection can atomically lock a complete comparison
        # cycle.  Do not migrate, commit, or close that caller's transaction.
        connection.execute(
                """
                INSERT INTO prediction_runs (
                    prediction_id, username, game_type, target_draw_id, created_at,
                    data_cutoff_draw_id, model_id, model_version, feature_version, config_hash,
                    random_seed, prediction_mode, engine, status, probabilities_json,
                    tickets_json, payload_json, payload_checksum, error_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prediction_id,
                    str(username or ""),
                    game_type,
                    target_draw_id,
                    created_at,
                    data_cutoff_draw_id,
                    str(model_id or payload.get("model_id") or ""),
                    str(model_version or payload.get("modelVersion") or payload.get("model_version") or ""),
                    str(feature_version or payload.get("featureVersion") or payload.get("feature_version") or ""),
                    str(config_hash or payload.get("configHash") or payload.get("config_hash") or ""),
                    int(random_seed or payload.get("randomSeed") or payload.get("random_seed") or 0),
                    str(payload.get("predictionMode") or payload.get("prediction_mode") or "normal"),
                    str(payload.get("engine") or ""),
                    str(status or "locked"),
                    canonical_json(probabilities),
                    canonical_json(tickets),
                    canonical_json(payload),
                    checksum,
                    canonical_json(payload.get("error") or payload.get("fallback_error") or {}),
                ),
            )
        return {
            "prediction_id": prediction_id,
            "status": status,
            "payload_checksum": checksum,
            "data_cutoff_draw_id": data_cutoff_draw_id,
            "target_draw_id": target_draw_id,
        }
    finally:
        if own_connection:
            connection.close()


def list_predictions(
    game_type: str | None = None,
    status: str | None = None,
    limit: int = 100,
    db_path: str | Path | None = None,
    username: str | None = None,
) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if game_type:
        clauses.append("pr.game_type = ?")
        params.append(str(game_type).strip().upper())
    if status:
        clauses.append("pr.status = ?")
        params.append(str(status).strip().lower())
    if username is not None:
        clauses.append("pr.username = ?")
        params.append(str(username).strip())
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    connection = connect(db_path)
    try:
        rows = connection.execute(
            f"""
            SELECT
                pr.*,
                ps.score_id AS latest_score_id,
                ps.scored_at,
                ps.actual_draw_id,
                ps.hit_count AS score_hit_count,
                ps.special_hit AS score_special_hit,
                ps.brier_score AS score_brier_score,
                ps.log_loss AS score_log_loss,
                ps.lift AS score_lift,
                ps.metrics_json AS score_metrics_json,
                ps.scoring_version
            FROM prediction_runs pr
            LEFT JOIN prediction_scores ps
                ON ps.score_id = (
                    SELECT ps2.score_id
                    FROM prediction_scores ps2
                    WHERE ps2.prediction_id = pr.prediction_id
                    ORDER BY ps2.scored_at DESC, ps2.score_id DESC
                    LIMIT 1
                )
            {where}
            ORDER BY pr.created_at DESC
            LIMIT ?
            """,
            [*params, max(1, int(limit or 100))],
        ).fetchall()
        return [row_to_dict(row) for row in rows]
    finally:
        connection.close()


def _ticket_main(ticket: Any) -> list[int]:
    if isinstance(ticket, dict):
        return [int(value) for value in list(ticket.get("main") or [])]
    return [int(value) for value in list(ticket or [])]


def _ticket_special(ticket: Any) -> int | None:
    if isinstance(ticket, dict) and ticket.get("special") is not None:
        try:
            return int(ticket.get("special"))
        except Exception:
            return None
    return None


@lru_cache(maxsize=256)
def _portfolio_random_best(tickets: tuple[tuple[int, ...], ...], universe_size: int, draw_size: int) -> float:
    """Uniform draws against the same tickets preserve budget and overlap."""
    if not tickets:
        return 0.0
    if len(set(tickets)) == 1:
        return len(set(tickets[0])) * draw_size / float(universe_size)
    rng = random.Random(20261004)
    ticket_sets = [set(ticket) for ticket in tickets]
    total = 0
    for _ in range(1024):
        actual = set(rng.sample(range(1, universe_size + 1), draw_size))
        total += max(len(ticket & actual) for ticket in ticket_sets)
    return total / 1024.0


def score_prediction_payload(
    prediction_payload: dict[str, Any],
    actual_draw: dict[str, Any],
    universe_size: int,
    draw_size: int,
    prediction_size: int,
) -> dict[str, Any]:
    tickets = list(prediction_payload.get("tickets") or [])
    inferred_prediction_size = int(prediction_payload.get("pickSize") or prediction_payload.get("pick_size") or 0)
    if inferred_prediction_size <= 0 and tickets:
        inferred_prediction_size = max((len(_ticket_main(ticket)) for ticket in tickets), default=0)
    if inferred_prediction_size > 0:
        prediction_size = inferred_prediction_size
    actual_main = [int(value) for value in list(actual_draw.get("main") or actual_draw.get("main_numbers") or [])]
    actual_special = actual_draw.get("special")
    best_hit = 0
    special_hit = 0
    per_ticket = []
    for ticket in tickets:
        main = _ticket_main(ticket)
        hit = len(set(main) & set(actual_main))
        best_hit = max(best_hit, hit)
        ticket_special = _ticket_special(ticket)
        matched_special = ticket_special is not None and actual_special is not None and int(ticket_special) == int(actual_special)
        if matched_special:
            special_hit = 1
        size = len(set(main))
        expected = size * draw_size / float(universe_size)
        per_ticket.append({"hit_count": hit, "special_hit": int(matched_special),
                           "prediction_size": size, "expected_random_hits": expected,
                           "lift": hit / expected - 1.0 if expected else 0.0})
    probabilities = normalize_probability_payload(
        prediction_payload.get("probabilities")
        or prediction_payload.get("calibratedProbability")
        or prediction_payload.get("calibrated_probability")
        or {}
    )
    if not probabilities:
        ranked = {}
        for ticket in tickets:
            for index, number in enumerate(_ticket_main(ticket)):
                ranked[int(number)] = max(float(ranked.get(int(number), 0.0)), float(prediction_size - index))
        probabilities = scores_to_probabilities(ranked, draw_size, 1, universe_size)
    metric_brier = brier_score([probabilities], [actual_main], universe_size)
    metric_log_loss = log_loss([probabilities], [actual_main], universe_size)
    mean_hits = sum(item["hit_count"] for item in per_ticket) / max(1, len(per_ticket))
    expected_mean = sum(item["expected_random_hits"] for item in per_ticket) / max(1, len(per_ticket))
    portfolio_baseline = _portfolio_random_best(tuple(tuple(sorted(set(_ticket_main(ticket)))) for ticket in tickets), universe_size, draw_size)
    return {
        "hit_count": best_hit,
        "special_hit": special_hit,
        "brier_score": metric_brier,
        "log_loss": metric_log_loss,
        "lift": mean_hits / expected_mean - 1.0 if expected_mean else 0.0,
        "lift_basis": "mean_hits_per_ticket_same_budget",
        "ticket_count": len(per_ticket),
        "per_ticket": per_ticket,
        "mean_hits_per_ticket": mean_hits,
        "expected_random_hits_per_ticket": expected_mean,
        "portfolio_best_hits": best_hit,
        "portfolio_expected_random_best_hits": portfolio_baseline,
        "portfolio_best_lift": best_hit / portfolio_baseline - 1.0 if portfolio_baseline else 0.0,
        "portfolio_baseline_method": "1024 uniform draws, same tickets and overlap, fixed seed",
        "prediction_size": int(prediction_size),
        "actual_main": actual_main,
        "actual_special": actual_special,
    }


def score_pending_predictions(
    game_type: str,
    actual_lookup: Callable[[str, str], dict[str, Any] | None],
    universe_size: int,
    draw_size: int,
    prediction_size: int,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    game_type = str(game_type or "").strip().upper()
    connection = connect(db_path)
    scored = []
    skipped = []
    try:
        rows = connection.execute(
            "SELECT * FROM prediction_runs WHERE game_type = ? AND status = 'locked' AND username <> ? ORDER BY created_at",
            (game_type, EFFECTIVENESS_SYSTEM_ACTOR),
        ).fetchall()
        with connection:
            for row in rows:
                run = row_to_dict(row)
                payload = _json_loads(str(row["payload_json"] or ""), {})
                if payload_checksum(payload) != row["payload_checksum"]:
                    skipped.append({"prediction_id": row["prediction_id"], "reason": "checksum_mismatch"})
                    continue
                actual = actual_lookup(game_type, str(row["target_draw_id"]))
                if not actual:
                    skipped.append({"prediction_id": row["prediction_id"], "reason": "actual_not_available"})
                    continue
                metrics = score_prediction_payload(payload, actual, universe_size, draw_size, prediction_size)
                score_id = str(uuid.uuid4())
                connection.execute(
                    """
                    INSERT OR IGNORE INTO prediction_scores (
                        score_id, prediction_id, scored_at, actual_draw_id, hit_count,
                        special_hit, brier_score, log_loss, lift, metrics_json, scoring_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        score_id,
                        row["prediction_id"],
                        now_iso(),
                        str(actual.get("ky") or actual.get("draw_id") or row["target_draw_id"]),
                        int(metrics["hit_count"]),
                        int(metrics["special_hit"]),
                        float(metrics["brier_score"]),
                        float(metrics["log_loss"]),
                        float(metrics["lift"]),
                        canonical_json(metrics),
                        SCORING_VERSION,
                    ),
                )
                connection.execute(
                    "UPDATE prediction_runs SET status = 'scored' WHERE prediction_id = ? AND status = 'locked'",
                    (row["prediction_id"],),
                )
                scored.append({"prediction_id": row["prediction_id"], **metrics})
        return {"ok": True, "game_type": game_type, "scored": scored, "skipped": skipped}
    finally:
        connection.close()


def register_model(
    game_type: str,
    version: str,
    trained_data_cutoff: str,
    status: str,
    artifact_paths: dict[str, Any] | None = None,
    validation_metrics: dict[str, Any] | None = None,
    outer_backtest_metrics: dict[str, Any] | None = None,
    feature_version: str = "",
    config_hash: str = "",
    promotion_reason: str = "",
    model_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    model_id = model_id or f"{str(game_type).lower()}_{uuid.uuid4().hex[:12]}"
    timestamp = now_iso()
    connection = connect(db_path)
    try:
        with connection:
            connection.execute(
                """
                INSERT INTO model_registry (
                    model_id, version, game_type, trained_at, trained_data_cutoff,
                    feature_version, config_hash, artifact_paths_json, validation_metrics_json,
                    outer_backtest_metrics_json, status, promotion_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model_id,
                    str(version or ""),
                    str(game_type).strip().upper(),
                    timestamp,
                    str(trained_data_cutoff or ""),
                    str(feature_version or ""),
                    str(config_hash or ""),
                    canonical_json(artifact_paths or {}),
                    canonical_json(validation_metrics or {}),
                    canonical_json(outer_backtest_metrics or {}),
                    str(status or "candidate"),
                    str(promotion_reason or ""),
                    timestamp,
                    timestamp,
                ),
            )
        return {"ok": True, "model_id": model_id, "status": status}
    finally:
        connection.close()


def list_models(game_type: str | None = None, status: str | None = None, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if game_type:
        clauses.append("game_type = ?")
        params.append(str(game_type).strip().upper())
    if status:
        clauses.append("status = ?")
        params.append(str(status).strip().lower())
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    connection = connect(db_path)
    try:
        rows = connection.execute(f"SELECT * FROM model_registry{where} ORDER BY updated_at DESC", params).fetchall()
        return [row_to_dict(row) for row in rows]
    finally:
        connection.close()


def promote_candidate(game_type: str, model_id: str, reason: str, db_path: str | Path | None = None, expected_champion_id: str | None = None) -> dict[str, Any]:
    game_type = str(game_type or "").strip().upper()
    connection = connect(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        with connection:
            current = connection.execute("SELECT model_id FROM model_registry WHERE game_type=? AND status='champion'", (game_type,)).fetchone()
            if expected_champion_id is not None and str(current[0] if current else "") != expected_champion_id:
                raise ValueError("champion changed during evaluation; retry promotion")
            candidate = connection.execute(
                "SELECT * FROM model_registry WHERE game_type = ? AND model_id = ? AND status = 'candidate'",
                (game_type, str(model_id)),
            ).fetchone()
            if candidate is None:
                raise ValueError("candidate model not found")
            timestamp = now_iso()
            connection.execute(
                "UPDATE model_registry SET status = 'archived', updated_at = ? WHERE game_type = ? AND status = 'champion'",
                (timestamp, game_type),
            )
            connection.execute(
                "UPDATE model_registry SET status = 'champion', promotion_reason = ?, updated_at = ? WHERE model_id = ?",
                (str(reason or "manual promotion"), timestamp, str(model_id)),
            )
        return {"ok": True, "game_type": game_type, "champion_model_id": str(model_id)}
    finally:
        connection.close()


def reject_candidate(game_type: str, model_id: str, reason: str, db_path: str | Path | None = None) -> dict[str, Any]:
    connection = connect(db_path)
    try:
        with connection:
            connection.execute(
                "UPDATE model_registry SET status = 'rejected', promotion_reason = ?, updated_at = ? WHERE game_type = ? AND model_id = ? AND status = 'candidate'",
                (str(reason or "rejected"), now_iso(), str(game_type).strip().upper(), str(model_id)),
            )
        return {"ok": True, "model_id": model_id, "status": "rejected"}
    finally:
        connection.close()


def rollback_champion(game_type: str, reason: str = "manual rollback", db_path: str | Path | None = None, expected_previous_id: str | None = None) -> dict[str, Any]:
    game_type = str(game_type or "").strip().upper()
    connection = connect(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        with connection:
            previous = connection.execute(
                "SELECT model_id FROM model_registry WHERE game_type = ? AND status = 'archived' AND model_id NOT LIKE 'execution_%' ORDER BY updated_at DESC LIMIT 1",
                (game_type,),
            ).fetchone()
            if previous is None:
                raise ValueError("no archived model is available for rollback")
            if expected_previous_id is not None and previous["model_id"] != expected_previous_id:
                raise ValueError("rollback target changed; retry rollback")
            timestamp = now_iso()
            connection.execute(
                "UPDATE model_registry SET status = 'archived', updated_at = ? WHERE game_type = ? AND status = 'champion'",
                (timestamp, game_type),
            )
            connection.execute(
                "UPDATE model_registry SET status = 'champion', promotion_reason = ?, updated_at = ? WHERE model_id = ?",
                (str(reason or "manual rollback"), timestamp, previous["model_id"]),
            )
        return {"ok": True, "game_type": game_type, "champion_model_id": previous["model_id"]}
    finally:
        connection.close()


def create_training_run(game_type: str, data_cutoff_draw_id: str = "", db_path: str | Path | None = None) -> dict[str, Any]:
    training_run_id = str(uuid.uuid4())
    connection = connect(db_path)
    try:
        with connection:
            connection.execute(
                """
                INSERT INTO training_runs (
                    training_run_id, game_type, started_at, data_cutoff_draw_id, status
                ) VALUES (?, ?, ?, ?, 'started')
                """,
                (training_run_id, str(game_type).strip().upper(), now_iso(), str(data_cutoff_draw_id or "")),
            )
        return {"ok": True, "training_run_id": training_run_id}
    finally:
        connection.close()


def finish_training_run(
    training_run_id: str,
    status: str,
    candidate_model_id: str = "",
    metrics: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    connection = connect(db_path)
    try:
        with connection:
            connection.execute(
                """
                UPDATE training_runs
                SET finished_at = ?, status = ?, candidate_model_id = ?, metrics_json = ?, payload_json = ?, error_json = ?
                WHERE training_run_id = ?
                """,
                (
                    now_iso(),
                    str(status or "finished"),
                    str(candidate_model_id or ""),
                    canonical_json(metrics or {}),
                    canonical_json(payload or {}),
                    canonical_json(error or {}),
                    str(training_run_id),
                ),
            )
        return {"ok": True, "training_run_id": training_run_id, "status": status}
    finally:
        connection.close()
