"""Freeze a validation-selected lab configuration and measure only future draws."""
from __future__ import annotations

import argparse
import copy
import json
import sqlite3
import sys
import uuid
from collections import Counter
from contextlib import closing, redirect_stdout
from datetime import datetime
from io import StringIO
from statistics import mean

if __package__ in (None, ""):
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai import lab_store as store, prediction_effectiveness as effect, prediction_ledger as ledger
from ai.evaluation.statistical_tests import paired_bootstrap_ci
from backend.file_guard import resource_lock

PIPELINE = "prospective_lab_candidate_v1"
METHODS = {"candidate": "Ứng viên", "random": "Ngẫu nhiên", "web": "Web hiện tại"}
MAX_ACTIVE_CANDIDATES = 8


def _candidate(row) -> dict:
    return {"id": row["candidate_id"], "type": row["game_type"], "runId": row["run_id"],
            "profileId": row["profile_id"], "label": row["label"], "status": row["status"],
            "ticketCount": row["ticket_count"], "startedAt": row["started_at"],
            "resumedAt": row["resumed_at"], "stoppedAt": row["stopped_at"],
            "lastTick": row["last_tick"], "lastError": row["last_error"],
            "configHash": row["config_hash"], "configuration": json.loads(row["profile_json"]),
            "enrollmentCutoffDrawId": row["enrollment_cutoff"]}


def _find(connection, owner: str, game: str, candidate_id=None):
    values = [owner, game]
    query = "SELECT * FROM lab_candidates WHERE owner=? AND game_type=?"
    if candidate_id:
        query += " AND candidate_id=?"
        values.append(store._identifier(candidate_id, "Mã ứng viên"))
    return connection.execute(query + " ORDER BY (status='active') DESC,resumed_at DESC,rowid DESC LIMIT 1", values).fetchone()


def _frozen_configuration(run: dict, snapshot: dict) -> tuple[dict, dict]:
    from ai import algorithm_lab as lab, lab_profiles
    report = run["report"]
    selection, provenance = report.get("selection") or {}, report.get("provenance") or {}
    if selection.get("validationOnly") is not True:
        raise ValueError("Ứng viên phải được chọn bằng validation trước tập kiểm tra.")
    profile = lab_profiles.profile_definition(str(selection.get("candidateProfileId") or ""))
    recorded = selection.get("profileDefinition") or selection.get("candidateConfig")
    if recorded != profile or selection.get("configHash") != store._digest(profile):
        raise ValueError("Cấu hình hoặc phiên bản ứng viên không khớp báo cáo; chạy phòng thử mới.")
    manifest = lab._source_manifest()
    if provenance.get("sourceManifest") != manifest or provenance.get("sourceHash") != store._digest(manifest):
        raise ValueError("Mã thuật toán đã thay đổi từ lượt thử; chạy phòng thử mới trước khi theo dõi.")
    latest = str(provenance.get("latestDrawId") or "")
    if not latest.isdecimal() or int(latest) > int(snapshot["cutoff"]):
        raise ValueError("Kỳ cuối của báo cáo không thuộc lịch sử canonical hiện tại.")
    prefix = [row for row in snapshot["draws"] if int(row["ky"]) <= int(latest)]
    if not prefix or str(prefix[-1]["ky"]) != latest or store._digest(prefix) != provenance.get("dataHash"):
        raise ValueError("Lịch sử của lượt thử đã thay đổi; chạy phòng thử mới trước khi theo dõi.")
    return profile, manifest


def _guard_candidate(candidate, snapshot):
    from ai import algorithm_lab as lab, lab_profiles
    profile = json.loads(candidate["profile_json"])
    if profile != lab_profiles.profile_definition(candidate["profile_id"]) or store._digest(profile) != candidate["config_hash"]:
        raise ValueError("Cấu hình ứng viên thay đổi; dừng theo dõi và chạy phòng thử mới.")
    if lab._source_manifest() != json.loads(candidate["source_manifest_json"]):
        raise ValueError("Mã thuật toán thay đổi từ lúc khóa ứng viên; cần chạy phòng thử mới.")
    prefix = [row for row in snapshot["draws"] if int(row["ky"]) <= int(candidate["run_latest_draw_id"])]
    if not prefix or str(prefix[-1]["ky"]) != candidate["run_latest_draw_id"] or store._digest(prefix) != candidate["run_data_hash"]:
        raise ValueError("Lịch sử đã dùng chọn ứng viên thay đổi; chưa khóa kỳ mới.")
    if int(snapshot["target"]) <= int(candidate["enrollment_cutoff"]):
        raise ValueError("Không tạo dự đoán ngược trước thời điểm bắt đầu theo dõi ứng viên.")


def _set_error(candidate_id, error: str, db_path=None):
    with closing(store.connect(db_path)) as connection:
        connection.execute("UPDATE lab_candidates SET last_tick=?,last_error=? WHERE candidate_id=?",
                           (ledger.now_iso(), str(error)[:2000], candidate_id))


def start(owner: str, game: str, run_id: str, db_path=None) -> dict:
    owner, game = store._owner(owner), effect._game(game)
    run = store.get_run(owner, game, run_id, db_path)
    if run is None:
        raise ValueError("Không tìm thấy lượt thử thuộc tài khoản và game này.")
    snapshot = effect._snapshot(game)
    profile, manifest = _frozen_configuration(run, snapshot)
    count = (run["report"].get("parameters") or {}).get("ticketCount")
    if type(count) is not int or not 1 <= count <= 10:
        raise ValueError("Ngân sách vé của lượt thử không hợp lệ.")
    timestamp = ledger.now_iso()
    with closing(store.connect(db_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            existing = connection.execute("SELECT * FROM lab_candidates WHERE owner=? AND game_type=? AND run_id=?",
                                          (owner, game, run_id)).fetchone()
            active = connection.execute("SELECT candidate_id FROM lab_candidates WHERE owner=? AND game_type=? AND status='active'",
                                        (owner, game)).fetchone()
            # Selecting another candidate explicitly replaces the active one for
            # this owner/game. Already locked predictions remain immutable.
            if active and (existing is None or active[0] != existing["candidate_id"]):
                connection.execute("UPDATE lab_candidates SET status='stopped',stopped_at=?,revision=revision+1 WHERE candidate_id=?",
                                   (timestamp, active[0]))
            if existing is None or existing["status"] != "active":
                active_count = connection.execute("SELECT COUNT(*) FROM lab_candidates WHERE status='active'").fetchone()[0]
                if active_count >= MAX_ACTIVE_CANDIDATES:
                    raise ValueError("Đã có 8 ứng viên đang theo dõi; dừng một ứng viên trước khi bật thêm.")
            if existing:
                candidate_id = existing["candidate_id"]
                if existing["status"] != "active":
                    connection.execute("UPDATE lab_candidates SET status='active',resumed_at=?,stopped_at='',last_error='',revision=revision+1 WHERE candidate_id=?",
                                       (timestamp, candidate_id))
            else:
                candidate_id = str(uuid.uuid4())
                provenance = run["report"]["provenance"]
                connection.execute("""INSERT INTO lab_candidates (
                    candidate_id,owner,game_type,run_id,profile_id,label,ticket_count,profile_json,
                    source_manifest_json,run_data_hash,run_latest_draw_id,config_hash,enrollment_cutoff,
                    status,started_at,resumed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'active',?,?)""",
                    (candidate_id, owner, game, run_id, profile["id"],
                     (run["report"]["selection"].get("candidateLabel") or profile.get("label") or profile["id"]),
                     count, store._json(profile), store._json(manifest), provenance["dataHash"],
                     str(provenance["latestDrawId"]), store._digest(profile), snapshot["cutoff"], timestamp, timestamp))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    try:
        cycle(owner, game, candidate_id, db_path)
    except Exception as exc:
        # Enrollment can wait for a stale canonical feed. It cannot fill past
        # draws and will only create the next future cycle once data catches up.
        _set_error(candidate_id, str(exc), db_path)
    return {"ok": True, "type": game, "tracking": report(owner, game, candidate_id, db_path)}


def stop(owner: str, game: str, candidate_id: str, db_path=None) -> dict:
    owner, game = store._owner(owner), effect._game(game)
    candidate_id = store._identifier(candidate_id, "Mã ứng viên")
    readonly = store.readonly(db_path)
    if readonly is None:
        raise ValueError("Không tìm thấy ứng viên thuộc tài khoản và game này.")
    with closing(readonly):
        if _find(readonly, owner, game, candidate_id) is None:
            raise ValueError("Không tìm thấy ứng viên thuộc tài khoản và game này.")
    with closing(store.connect(db_path)) as connection:
        row = _find(connection, owner, game, candidate_id)
        if row is None:
            raise ValueError("Không tìm thấy ứng viên thuộc tài khoản và game này.")
        connection.execute("UPDATE lab_candidates SET status='stopped',stopped_at=?,revision=revision+1 WHERE candidate_id=? AND status='active'",
                           (ledger.now_iso(), row["candidate_id"]))
    return {"ok": True, "type": game, "tracking": report(owner, game, candidate_id, db_path)}


def cycle(owner: str, game: str, candidate_id: str, db_path=None) -> dict:
    from ai import algorithm_lab as lab, lab_profiles
    owner, game = store._owner(owner), effect._game(game)
    candidate_id = store._identifier(candidate_id, "Mã ứng viên")
    database = store.DEFAULT_DB_PATH if db_path is None else db_path
    with resource_lock(str(database) + ".trials", timeout=15), closing(store.connect(db_path)) as connection:
        candidate = _find(connection, owner, game, candidate_id)
        if candidate is None:
            raise ValueError("Không tìm thấy ứng viên thuộc tài khoản và game này.")
        if candidate["status"] != "active":
            return {"status": "stopped", "type": game}
        snapshot = effect._snapshot(game)
        existing = connection.execute("SELECT cycle_id FROM lab_trial_cycles WHERE candidate_id=? AND target_draw_id=?",
                                      (candidate_id, snapshot["target"])).fetchone()
        if existing:
            return {"status": "already_locked", "type": game, "cycleId": existing[0], "targetDrawId": snapshot["target"]}
        effect._guard(snapshot)
        _guard_candidate(candidate, snapshot)
        registry = lab._freeze_registry(game, snapshot["draws"], snapshot["target"])
        count = candidate["ticket_count"]
        payloads = {"candidate": lab_profiles.predict_profile(game, candidate["profile_id"], snapshot["draws"], count),
                    "random": effect._baseline(game, "random", count, snapshot),
                    "web": lab._production_prediction(game, count, snapshot["draws"], registry)}
        for payload in payloads.values():
            effect._validate(payload, game, count, snapshot)
        registry.assert_unchanged()
        with resource_lock(snapshot["path"]):
            fresh = effect._snapshot(game)
            if fresh["version"] != snapshot["version"] or fresh["dataHash"] != snapshot["dataHash"]:
                raise RuntimeError("Canonical thay đổi trong lúc dự đoán; hủy cả ba bộ số.")
            effect._guard(fresh)
            _guard_candidate(candidate, fresh)
            registry.assert_unchanged()
            connection.execute("BEGIN IMMEDIATE")
            try:
                current = _find(connection, owner, game, candidate_id)
                if current is None or current["status"] != "active" or current["revision"] != candidate["revision"]:
                    raise RuntimeError("Ứng viên đã dừng hoặc thay đổi trong khi tạo dự đoán; chưa khóa kỳ.")
                effect._guard(fresh)
                _guard_candidate(current, fresh)
                registry.assert_unchanged()
                cycle_id, created_at = str(uuid.uuid4()), ledger.now_iso()
                configuration = {"pipeline": PIPELINE, "candidateId": candidate_id,
                                 "profileDefinition": json.loads(candidate["profile_json"]),
                                 "profileConfigHash": candidate["config_hash"], "ticketCount": count,
                                 "sourceManifest": json.loads(candidate["source_manifest_json"]),
                                 "registryModel": registry.provenance(), "scope": "main_numbers_only"}
                connection.execute("INSERT INTO lab_trial_cycles VALUES(?,?,?,?,?,?,?,?,?,?)",
                                   (cycle_id, candidate_id, game, snapshot["target"], snapshot["cutoff"], created_at,
                                    snapshot["deadline"].isoformat(timespec="seconds"), snapshot["dataHash"],
                                    store._json(snapshot["version"]), store._json(configuration)))
                for method, original in payloads.items():
                    payload = {**copy.deepcopy(original), "labCandidateId": candidate_id,
                               "labTrialCycleId": cycle_id, "labTrialMethod": method,
                               "predictionDeadline": snapshot["deadline"].isoformat(timespec="seconds"),
                               "dataHash": snapshot["dataHash"], "labTrialConfigHash": store._digest(configuration)}
                    connection.execute("INSERT INTO lab_trial_predictions VALUES(?,?,?,?)",
                                       (cycle_id, method, store._json(payload), store._digest(payload)))
                effect._guard(fresh)
                connection.execute("UPDATE lab_candidates SET last_tick=?,last_error='' WHERE candidate_id=?", (created_at, candidate_id))
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return {"status": "locked", "type": game, "cycleId": cycle_id,
                "targetDrawId": snapshot["target"], "cutoffDrawId": snapshot["cutoff"], "ticketCount": count}


def _prediction(row, cycle_row, candidate) -> dict:
    payload = json.loads(row["payload_json"])
    if store._digest(payload) != row["payload_hash"]:
        raise ValueError("Checksum dự đoán ứng viên không khớp.")
    if (payload.get("type") != candidate["game_type"] or payload.get("labCandidateId") != candidate["candidate_id"]
            or payload.get("labTrialCycleId") != cycle_row["cycle_id"] or payload.get("labTrialMethod") != row["method"]):
        raise ValueError("Dự đoán không thuộc đúng chu kỳ ứng viên.")
    snapshot = {"cutoff": cycle_row["cutoff_draw_id"], "target": cycle_row["target_draw_id"]}
    effect._validate(payload, candidate["game_type"], candidate["ticket_count"], snapshot)
    return payload


def score_candidate(candidate_id: str, db_path=None) -> dict:
    from ai import algorithm_lab as lab, ml_pipeline
    errors, scored = [], []
    with closing(store.connect(db_path)) as connection:
        candidate = connection.execute("SELECT * FROM lab_candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
        if candidate is None:
            return {"scored": [], "errors": []}
        game = candidate["game_type"]
        actuals = ml_pipeline.load_actual_draws(game)
        cycles = connection.execute("SELECT * FROM lab_trial_cycles WHERE candidate_id=? ORDER BY CAST(target_draw_id AS INTEGER)",
                                    (candidate_id,)).fetchall()
        for cycle_row in cycles:
            target = cycle_row["target_draw_id"]
            if target not in actuals:
                continue
            if connection.execute("SELECT COUNT(*) FROM lab_trial_scores WHERE cycle_id=?", (cycle_row["cycle_id"],)).fetchone()[0] == 3:
                continue
            try:
                actual = actuals[target]
                effect._validate_actual_row(actual, game)
                actual_at = effect._draw_at(actual, game)
                if actual_at > effect._now():
                    continue
                if actual_at != datetime.fromisoformat(cycle_row["deadline"]):
                    raise ValueError("Ngày/giờ kết quả không khớp kỳ ứng viên đã khóa.")
                if datetime.fromisoformat(cycle_row["created_at"]) >= actual_at:
                    raise ValueError("Chu kỳ không được khóa trước giờ quay.")
                connection.execute("BEGIN IMMEDIATE")
                rows = connection.execute("SELECT * FROM lab_trial_predictions WHERE cycle_id=?", (cycle_row["cycle_id"],)).fetchall()
                if len(rows) != 3 or {row["method"] for row in rows} != set(METHODS):
                    raise ValueError("Chu kỳ ứng viên phải có đủ ba phương pháp.")
                for row in rows:
                    payload = _prediction(row, cycle_row, candidate)
                    measured = lab._measure(game, payload, actual)
                    document = {"actual": actual, "metrics": measured}
                    connection.execute("INSERT OR IGNORE INTO lab_trial_scores VALUES(?,?,?,?,?,?)",
                                       (cycle_row["cycle_id"], row["method"], ledger.now_iso(),
                                        store._json(actual), store._json(measured), store._digest(document)))
                connection.commit()
                scored.append(target)
            except Exception as exc:
                connection.rollback()
                errors.append({"targetDrawId": target, "error": str(exc)})
    return {"scored": scored, "errors": errors}


def _summary(key: str, samples: list[dict], comparisons: dict[str, list[dict]]) -> dict:
    count = len(samples)
    histogram = Counter()
    for sample in samples:
        histogram.update(sample["prizeHistogram"])
    result = {"key": key, "label": METHODS[key], "sampleCount": count,
              **{field: mean(sample[field] for sample in samples) if count else None
                 for field in ("meanHits", "brierScore", "logLoss", "rate3", "rate4")},
              "prizeHistogram": dict(histogram), "comparisons": {}}
    for other in ("random", "web"):
        baseline = comparisons[other]
        if count:
            ci = paired_bootstrap_ci([s["meanHits"] for s in samples], [s["meanHits"] for s in baseline])
            brier = paired_bootstrap_ci([s["brierScore"] for s in samples], [s["brierScore"] for s in baseline])
            log = paired_bootstrap_ci([s["logLoss"] for s in samples], [s["logLoss"] for s in baseline])
            comparison = {"deltaMeanHits": ci["mean"], "ci95": {"lower": ci["lower"], "upper": ci["upper"]},
                          "brierDelta": brier["mean"], "brierCi95": {"lower": brier["lower"], "upper": brier["upper"]},
                          "logLossDelta": log["mean"], "logLossCi95": {"lower": log["lower"], "upper": log["upper"]}}
        else:
            comparison = {"deltaMeanHits": None, "ci95": None, "brierDelta": None, "brierCi95": None,
                          "logLossDelta": None, "logLossCi95": None}
        result["comparisons"][other] = comparison
    result.update({"deltaVsRandom": result["comparisons"]["random"]["deltaMeanHits"],
                   "ci95": result["comparisons"]["random"]["ci95"],
                   "brierDeltaVsRandom": result["comparisons"]["random"]["brierDelta"],
                   "brierCi95": result["comparisons"]["random"]["brierCi95"]})
    return result


def _conclusion(candidate_summary: dict | None) -> dict:
    count = candidate_summary["sampleCount"] if candidate_summary else 0
    if count < 30:
        return {"status": "insufficient_evidence", "title": "Chưa đủ kỳ thực tế để kết luận",
                "summary": f"Đã chấm {count}/30 kỳ tối thiểu. Tiếp tục theo dõi các kỳ khóa trước giờ quay.",
                "minimumCycles": 30, "remainingCycles": max(0, 30 - count), "canApply": False}
    advantages = all(comparison["brierCi95"]["upper"] < 0 and comparison["logLossDelta"] < 0
                     and comparison["ci95"]["lower"] > 0 for comparison in candidate_summary["comparisons"].values())
    return {"status": "possible_improvement" if advantages else "no_clear_advantage",
            "title": "Có dấu hiệu cải thiện trên kỳ thực tế" if advantages else "Chưa thấy lợi thế rõ trước hai đối chứng",
            "summary": ("Ứng viên cải thiện Brier, log-loss và số trùng trước ngẫu nhiên lẫn web trong mẫu đã khóa. Cần kiểm chứng tiếp trước khi đổi cấu hình."
                        if advantages else "Giữ cấu hình web hiện tại; thử cấu hình khác trên một tập kỳ tương lai mới."),
            "minimumCycles": 30, "remainingCycles": 0, "canApply": False}


def report(owner: str, game: str, candidate_id: str | None = None, db_path=None, limit: int = 20) -> dict:
    owner, game = store._owner(owner), effect._game(game)
    empty = {"type": game, "scope": "prospective_equal_budget", "pipeline": PIPELINE,
             "candidate": None, "counts": {"locked": 0, "scored": 0, "total": 0},
             "methods": [], "cycles": [], "conclusion": _conclusion(None)}
    connection = store.readonly(db_path)
    if connection is None:
        return empty
    with closing(connection):
        candidate = _find(connection, owner, game, candidate_id)
        if candidate is None:
            return empty
        cycles = connection.execute("SELECT * FROM lab_trial_cycles WHERE candidate_id=? ORDER BY CAST(target_draw_id AS INTEGER) DESC",
                                    (candidate["candidate_id"],)).fetchall()
        grouped = {key: [] for key in METHODS}
        items, errors = [], []
        for cycle_row in cycles:
            try:
                predictions = connection.execute("SELECT * FROM lab_trial_predictions WHERE cycle_id=?", (cycle_row["cycle_id"],)).fetchall()
                if len(predictions) != 3 or {row["method"] for row in predictions} != set(METHODS):
                    raise ValueError("Chu kỳ không đủ ba dự đoán đã khóa.")
                methods = {}
                for prediction in predictions:
                    payload = _prediction(prediction, cycle_row, candidate)
                    methods[prediction["method"]] = {"tickets": payload["tickets"], "engine": payload.get("engine"),
                                                     "modelId": payload.get("modelId"), "seed": payload.get("randomSeed"),
                                                     "payloadChecksum": prediction["payload_hash"], "ticketResults": [],
                                                     "probabilityCalibrationStatus": payload.get("probabilityCalibrationStatus", "uncalibrated")}
                scores = connection.execute("SELECT * FROM lab_trial_scores WHERE cycle_id=?", (cycle_row["cycle_id"],)).fetchall()
                actual = None
                measured = {}
                if scores:
                    if len(scores) != 3 or {row["method"] for row in scores} != set(METHODS):
                        raise ValueError("Chu kỳ chưa có đủ ba điểm hợp lệ; không gộp một phần.")
                    for score in scores:
                        recorded_actual, metrics = json.loads(score["actual_json"]), json.loads(score["metrics_json"])
                        if store._digest({"actual": recorded_actual, "metrics": metrics}) != score["score_hash"]:
                            raise ValueError("Checksum điểm đã lưu không khớp.")
                        if actual is not None and actual != recorded_actual:
                            raise ValueError("Các phương pháp không dùng cùng kết quả thực tế.")
                        actual = recorded_actual
                        measured[score["method"]] = metrics
                        methods[score["method"]].update({key: metrics[key] for key in ("meanHits", "bestHits", "brierScore", "logLoss", "rate3", "rate4", "prizeHistogram")})
                        methods[score["method"]]["ticketResults"] = [
                            {**item["result"], "ticketIndex": index + 1}
                            for index, item in enumerate(metrics["tickets"])]
                    for key in METHODS:
                        grouped[key].append(measured[key])
                items.append({"id": cycle_row["cycle_id"], "targetDrawId": cycle_row["target_draw_id"],
                              "cutoffDrawId": cycle_row["cutoff_draw_id"], "createdAt": cycle_row["created_at"],
                              "deadline": cycle_row["deadline"], "dataHash": cycle_row["data_hash"],
                              "status": "scored" if actual else "locked", "actualMain": actual["main"] if actual else None,
                              "actualSpecial": actual.get("special") if actual else None, "methods": methods})
            except Exception as exc:
                errors.append({"targetDrawId": cycle_row["target_draw_id"], "error": str(exc)})
        methods = [_summary(key, grouped[key], grouped) for key in METHODS]
        return {**empty, "candidate": _candidate(candidate),
                "counts": {"locked": sum(item["status"] == "locked" for item in items),
                           "scored": len(grouped["candidate"]), "total": len(items)},
                "methods": methods, "cycles": items[:max(1, min(100, int(limit)))],
                "conclusion": _conclusion(methods[0]), "errors": errors,
                "notes": ["Chỉ gồm dự đoán đã khóa trước kỳ thực tế, cùng số vé cho ba phương pháp.",
                          "Số trùng/Brier/log-loss chấm số chính; hạng giải từng vé xét riêng. Không tự thay model web.",
                          "Dừng theo dõi ngăn tạo kỳ mới; các kỳ đã khóa vẫn được chấm khi có kết quả."]}


def tick(db_path=None) -> dict:
    connection = store.readonly(db_path)
    if connection is None:
        return {"ok": True, "results": []}
    with closing(connection):
        # Stopped candidates with pending cycles remain scoreable, but never
        # generate new predictions. Completed stopped runs are omitted.
        candidates = connection.execute("""SELECT c.* FROM lab_candidates c
            WHERE c.status='active' OR EXISTS (
                SELECT 1 FROM lab_trial_cycles cy WHERE cy.candidate_id=c.candidate_id
                AND (SELECT COUNT(*) FROM lab_trial_scores s WHERE s.cycle_id=cy.cycle_id)<3)
            ORDER BY c.started_at""").fetchall()
    results = []
    for candidate in candidates:
        try:
            scoring = score_candidate(candidate["candidate_id"], db_path)
            action = cycle(candidate["owner"], candidate["game_type"], candidate["candidate_id"], db_path) if candidate["status"] == "active" else {"status": "stopped"}
            error = "; ".join(item["error"] for item in scoring["errors"])
            _set_error(candidate["candidate_id"], error, db_path)
            results.append({"candidateId": candidate["candidate_id"], "type": candidate["game_type"],
                            "ok": not error, "scoring": scoring, "cycle": action})
        except Exception as exc:
            _set_error(candidate["candidate_id"], str(exc), db_path)
            results.append({"candidateId": candidate["candidate_id"], "type": candidate["game_type"], "ok": False, "error": str(exc)})
    return {"ok": True, "results": results}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("start", "stop", "report", "tick"), required=True)
    parser.add_argument("--owner")
    parser.add_argument("--game", choices=effect.GAMES)
    parser.add_argument("--run-id")
    parser.add_argument("--candidate-id")
    parser.add_argument("--db-path", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        with redirect_stdout(StringIO()):
            if args.action == "tick":
                result = tick(args.db_path)
            elif args.action == "start":
                result = start(args.owner, args.game, args.run_id, args.db_path)
            elif args.action == "stop":
                result = stop(args.owner, args.game, args.candidate_id, args.db_path)
            else:
                result = {"ok": True, "type": effect._game(args.game), "tracking": report(args.owner, args.game, args.candidate_id, args.db_path)}
    except Exception as exc:
        result = {"ok": False, "type": args.game, "error": str(exc), "message": str(exc)}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
