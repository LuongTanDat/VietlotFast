"""Owner-scoped durable history for the algorithm lab, separate from production ledger."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai import prediction_effectiveness as effect, prediction_ledger as ledger
from ai.configs import data_paths as dp

DEFAULT_DB_PATH = dp.RUNTIME_DIR / "algorithm_lab.db"
MAX_REPORT_BYTES = 8 * 1024 * 1024


def _owner(value: str) -> str:
    value = str(value or "").strip()
    if not value or len(value) > 128 or any(ord(char) < 32 for char in value):
        raise ValueError("Thiếu tài khoản sở hữu phòng thử hợp lệ.")
    return value


def _identifier(value: str, label="Mã lượt thử") -> str:
    value = str(value or "").strip()
    if not value or len(value) > 128 or any(ord(char) < 32 for char in value):
        raise ValueError(f"{label} không hợp lệ.")
    return value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def connect(db_path=None) -> sqlite3.Connection:
    """Only explicitly authorized saves/tracking call this creating connection."""
    path = Path(db_path or DEFAULT_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS lab_runs (
            run_id TEXT PRIMARY KEY, owner TEXT NOT NULL, game_type TEXT NOT NULL,
            created_at TEXT NOT NULL, finished_at TEXT NOT NULL,
            report_json TEXT NOT NULL, report_hash TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS lab_runs_owner_game ON lab_runs(owner,game_type,finished_at);
        CREATE TABLE IF NOT EXISTS lab_run_metadata (
            run_id TEXT PRIMARY KEY REFERENCES lab_runs(run_id),
            metadata_json TEXT NOT NULL, metadata_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS lab_candidates (
            candidate_id TEXT PRIMARY KEY, owner TEXT NOT NULL, game_type TEXT NOT NULL,
            run_id TEXT NOT NULL REFERENCES lab_runs(run_id), profile_id TEXT NOT NULL,
            label TEXT NOT NULL, ticket_count INTEGER NOT NULL CHECK(ticket_count BETWEEN 1 AND 10),
            profile_json TEXT NOT NULL, source_manifest_json TEXT NOT NULL,
            run_data_hash TEXT NOT NULL, run_latest_draw_id TEXT NOT NULL,
            config_hash TEXT NOT NULL, enrollment_cutoff TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('active','stopped')),
            started_at TEXT NOT NULL, resumed_at TEXT NOT NULL, stopped_at TEXT NOT NULL DEFAULT '',
            revision INTEGER NOT NULL DEFAULT 1, last_tick TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '', UNIQUE(owner,game_type,run_id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS lab_candidate_active
            ON lab_candidates(owner,game_type) WHERE status='active';
        CREATE TABLE IF NOT EXISTS lab_trial_cycles (
            cycle_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES lab_candidates(candidate_id),
            game_type TEXT NOT NULL, target_draw_id TEXT NOT NULL, cutoff_draw_id TEXT NOT NULL,
            created_at TEXT NOT NULL, deadline TEXT NOT NULL, data_hash TEXT NOT NULL,
            source_version_json TEXT NOT NULL, config_json TEXT NOT NULL,
            UNIQUE(candidate_id,target_draw_id)
        );
        CREATE TABLE IF NOT EXISTS lab_trial_predictions (
            cycle_id TEXT NOT NULL REFERENCES lab_trial_cycles(cycle_id),
            method TEXT NOT NULL CHECK(method IN ('candidate','random','web')),
            payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL,
            PRIMARY KEY(cycle_id,method)
        );
        CREATE TABLE IF NOT EXISTS lab_trial_scores (
            cycle_id TEXT NOT NULL, method TEXT NOT NULL, scored_at TEXT NOT NULL,
            actual_json TEXT NOT NULL, metrics_json TEXT NOT NULL, score_hash TEXT NOT NULL,
            PRIMARY KEY(cycle_id,method),
            FOREIGN KEY(cycle_id,method) REFERENCES lab_trial_predictions(cycle_id,method)
        );
        CREATE TRIGGER IF NOT EXISTS lab_run_immutable BEFORE UPDATE ON lab_runs BEGIN
            SELECT RAISE(ABORT,'lab report is immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS lab_run_metadata_immutable BEFORE UPDATE ON lab_run_metadata BEGIN
            SELECT RAISE(ABORT,'lab history metadata is immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS lab_candidate_config_immutable
            BEFORE UPDATE OF owner,game_type,run_id,profile_id,label,ticket_count,profile_json,
                             source_manifest_json,run_data_hash,run_latest_draw_id,config_hash,
                             enrollment_cutoff,started_at ON lab_candidates BEGIN
            SELECT RAISE(ABORT,'lab candidate configuration is immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS lab_trial_cycle_immutable BEFORE UPDATE ON lab_trial_cycles BEGIN
            SELECT RAISE(ABORT,'lab trial cycle is immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS lab_trial_prediction_immutable BEFORE UPDATE ON lab_trial_predictions BEGIN
            SELECT RAISE(ABORT,'lab trial prediction is immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS lab_trial_score_immutable BEFORE UPDATE ON lab_trial_scores BEGIN
            SELECT RAISE(ABORT,'lab trial score is immutable');
        END;
    """)
    return connection


def readonly(db_path=None) -> sqlite3.Connection | None:
    path = Path(db_path or DEFAULT_DB_PATH)
    if not path.is_file():
        return None
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def _report(row) -> dict:
    serialized = row["report_json"]
    if hashlib.sha256(serialized.encode("utf-8")).hexdigest() != row["report_hash"]:
        raise ValueError("Checksum báo cáo đã lưu không khớp; không dùng làm ứng viên.")
    return json.loads(serialized)


def _history_metadata(run_id: str, game: str, report: dict, created_at: str, finished_at: str) -> dict:
    parameters, selection = report.get("parameters") or {}, report.get("selection") or {}
    return {"id": run_id, "type": game, "createdAt": created_at, "finishedAt": finished_at,
            **{key: parameters.get(key) for key in ("ticketCount", "validationCount", "testCount")},
            "selectedMethod": selection.get("selectedMethod"),
            "candidateProfileId": selection.get("candidateProfileId"),
            "candidateLabel": selection.get("candidateLabel"), "conclusion": report.get("conclusion")}


def _timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValueError(f"{label} không hợp lệ.")
    if parsed.tzinfo is None:
        raise ValueError(f"{label} phải có múi giờ.")
    return parsed


def save_run(owner: str, game: str, run_id: str, report: dict, created_at: str,
             finished_at: str, db_path=None) -> dict:
    owner, game, run_id = _owner(owner), effect._game(game), _identifier(run_id)
    if not isinstance(report, dict) or report.get("ok") is not True or report.get("type") != game:
        raise ValueError("Chỉ lưu báo cáo hoàn tất đúng game.")
    if report.get("status") != "completed" or report.get("scope") != "historical_diagnostic":
        raise ValueError("Báo cáo chưa hoàn tất kiểm tra lịch sử.")
    if _timestamp(finished_at, "Giờ hoàn tất") < _timestamp(created_at, "Giờ bắt đầu"):
        raise ValueError("Giờ hoàn tất phải sau giờ bắt đầu.")
    serialized = _json(report)
    if len(serialized.encode("utf-8")) > MAX_REPORT_BYTES:
        raise ValueError("Báo cáo vượt giới hạn 8 MiB.")
    checksum = _digest(report)
    with closing(connect(db_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            previous = connection.execute("SELECT * FROM lab_runs WHERE run_id=?", (run_id,)).fetchone()
            if previous:
                if previous["owner"] != owner or previous["game_type"] != game or previous["report_hash"] != checksum:
                    raise ValueError("Mã lượt thử đã có báo cáo khác; không ghi đè.")
            else:
                connection.execute("INSERT INTO lab_runs VALUES(?,?,?,?,?,?,?)",
                                   (run_id, owner, game, created_at, finished_at, serialized, checksum))
            metadata = _history_metadata(run_id, game, report,
                                         previous["created_at"] if previous else created_at,
                                         previous["finished_at"] if previous else finished_at)
            connection.execute("INSERT OR IGNORE INTO lab_run_metadata VALUES(?,?,?)",
                               (run_id, _json(metadata), _digest(metadata)))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {"ok": True, "type": game, "runId": run_id, "reportHash": checksum, "persisted": True}


def get_run(owner: str, game: str, run_id: str, db_path=None) -> dict | None:
    owner, game, run_id = _owner(owner), effect._game(game), _identifier(run_id)
    connection = readonly(db_path)
    if connection is None:
        return None
    with closing(connection):
        row = connection.execute("SELECT * FROM lab_runs WHERE owner=? AND game_type=? AND run_id=?",
                                 (owner, game, run_id)).fetchone()
        return {**dict(row), "report": _report(row)} if row else None


def job(owner: str, game: str, run_id: str | None = None, db_path=None) -> dict | None:
    owner, game = _owner(owner), effect._game(game)
    connection = readonly(db_path)
    if connection is None:
        return None
    with closing(connection):
        query, values = "SELECT * FROM lab_runs WHERE owner=? AND game_type=?", [owner, game]
        if run_id:
            query += " AND run_id=?"
            values.append(_identifier(run_id))
        row = connection.execute(query + " ORDER BY finished_at DESC,rowid DESC LIMIT 1", values).fetchone()
        if row is None:
            return None
        report = _report(row)
        parameters = report.get("parameters") or {}
        return {"id": row["run_id"], "type": game, "state": "completed", "createdAt": row["created_at"],
                "finishedAt": row["finished_at"], "ticketCount": parameters.get("ticketCount"),
                "validationCount": parameters.get("validationCount"), "testCount": parameters.get("testCount"),
                "report": report, "error": "", "persisted": True}


def history(owner: str, game: str, limit: int = 20, db_path=None) -> list[dict]:
    owner, game = _owner(owner), effect._game(game)
    connection = readonly(db_path)
    if connection is None:
        return []
    with closing(connection):
        has_metadata = connection.execute("SELECT 1 FROM sqlite_master WHERE name='lab_run_metadata'").fetchone()
        metadata_fields = "m.metadata_json,m.metadata_hash" if has_metadata else "NULL AS metadata_json,NULL AS metadata_hash"
        metadata_join = "LEFT JOIN lab_run_metadata m ON m.run_id=r.run_id" if has_metadata else ""
        rows = connection.execute(f"""SELECT r.run_id,r.game_type,r.created_at,r.finished_at,
                {metadata_fields},c.candidate_id
            FROM lab_runs r {metadata_join}
            LEFT JOIN lab_candidates c ON c.run_id=r.run_id AND c.owner=r.owner AND c.game_type=r.game_type
            WHERE r.owner=? AND r.game_type=? ORDER BY r.finished_at DESC,r.rowid DESC LIMIT ?""",
                                  (owner, game, max(1, min(50, int(limit))))).fetchall()
        results = []
        for row in rows:
            # Polling reads a compact immutable projection, never deserializes
            # or hashes every fold of the twenty full historical reports.
            if row["metadata_json"] is None:
                # Compatibility for an early v2 database saved before the
                # projection was introduced. Only the explicitly opened run
                # needs the full report; this history row remains identifiable.
                metadata = {"id": row["run_id"], "type": game, "createdAt": row["created_at"],
                            "finishedAt": row["finished_at"], "candidateProfileId": None}
            else:
                serialized = row["metadata_json"]
                if hashlib.sha256(serialized.encode("utf-8")).hexdigest() != row["metadata_hash"]:
                    raise ValueError("Checksum lịch sử phòng thử không khớp.")
                metadata = json.loads(serialized)
            results.append({**metadata, "trackingCandidateId": row["candidate_id"]})
        return results


def overview(owner: str, game: str, run_id: str | None = None, db_path=None) -> dict:
    from ai import lab_trials
    return {"ok": True, "type": effect._game(game), "job": job(owner, game, run_id, db_path),
            "history": history(owner, game, db_path=db_path), "tracking": lab_trials.report(owner, game, db_path=db_path)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("save", "overview", "history", "job"), required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--game", choices=effect.GAMES, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--created-at")
    parser.add_argument("--finished-at")
    parser.add_argument("--report-file")
    parser.add_argument("--db-path", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.action == "save":
            path = Path(args.report_file or "")
            if not path.is_file() or path.stat().st_size > MAX_REPORT_BYTES:
                raise ValueError("File báo cáo không hợp lệ hoặc vượt giới hạn 8 MiB.")
            result = save_run(args.owner, args.game, args.run_id,
                              json.loads(path.read_text(encoding="utf-8-sig")), args.created_at,
                              args.finished_at, args.db_path)
        elif args.action == "overview":
            result = overview(args.owner, args.game, args.run_id, args.db_path)
        elif args.action == "history":
            result = {"ok": True, "type": args.game, "history": history(args.owner, args.game, db_path=args.db_path)}
        else:
            result = {"ok": True, "type": args.game, "job": job(args.owner, args.game, args.run_id, args.db_path)}
    except Exception as exc:
        result = {"ok": False, "type": args.game, "error": str(exc), "message": str(exc)}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
