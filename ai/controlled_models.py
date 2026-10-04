"""Isolated model artifacts, chronological evaluation, and registry inference.

The first registered model family is a fixed Bayesian frequency baseline.
Legacy engines remain available and are identified as unapproved snapshots.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import uuid
import sqlite3
from pathlib import Path
from contextlib import closing
from typing import Any

from ai.configs import data_paths as dp
from ai import prediction_ledger as ledger
from ai.evaluation.metrics import brier_score, calibration_error, log_loss
from ai.evaluation.statistical_tests import paired_bootstrap_ci

PIPELINE = "bayesian_fixed_ranking_v1"


def digest(value: Any) -> str:
    return hashlib.sha256(ledger.canonical_json(value).encode("utf-8")).hexdigest()


def save_artifact(game: str, artifact: dict, model_id: str) -> dict:
    path = dp.RUNTIME_DIR / "model_registry" / game.lower() / model_id / "model.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = ledger.canonical_json(artifact).encode("utf-8")
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)
    return {"model": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(),
            "model_type": artifact["model_type"], "pipeline": PIPELINE}


def verify_artifact(model: dict) -> dict:
    paths = model.get("artifact_paths") or {}
    path = Path(paths["model"]).resolve()
    allowed = (dp.RUNTIME_DIR / "model_registry").resolve()
    if not path.is_relative_to(allowed):
        raise ValueError("model path outside registry artifact directory")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != paths.get("sha256"):
        raise ValueError("artifact hash mismatch")
    artifact = json.loads(raw)
    if artifact.get("model_type") != "bayesian_frequency_v1" or artifact.get("game_type") != model.get("game_type"):
        raise ValueError("unsupported model type or game mismatch")
    if paths.get("pipeline") != PIPELINE:
        raise ValueError("unsupported artifact inference pipeline")
    if str(artifact.get("trained_data_cutoff")) != str(model.get("trained_data_cutoff")):
        raise ValueError("artifact cutoff mismatch")
    size, draw = int(artifact["universe_size"]), int(artifact["draw_size"])
    probabilities = artifact["probabilities"]
    if set(probabilities) != {str(n) for n in range(1, size + 1)}:
        raise ValueError("incomplete probability vector")
    if any(not math.isfinite(float(p)) or not 0 < float(p) < 1 for p in probabilities.values()):
        raise ValueError("invalid probability vector")
    if abs(sum(float(p) for p in probabilities.values()) - draw) > 1e-8:
        raise ValueError("probability mass mismatch")
    return artifact


def fit_artifact(game: str, draws: list[dict], cfg: dict, prior_strength: float = 100.0) -> dict:
    if not draws:
        raise ValueError("not enough training history")
    size, draw_size = int(cfg["universe_size"]), int(cfg["draw_size"])
    prior = draw_size / size
    counts = {n: 0 for n in range(1, size + 1)}
    for row in draws:
        for number in set(row["main"]):
            counts[number] += 1
    return {"model_type": "bayesian_frequency_v1", "game_type": game,
            "trained_data_cutoff": str(draws[-1]["ky"]), "training_data_hash": digest(draws),
            "universe_size": size, "draw_size": draw_size, "prior_strength": prior_strength,
            "probabilities": {str(n): (counts[n] + prior_strength * prior) / (len(draws) + prior_strength) for n in counts},
            "training_samples": len(draws), "calibration_status": "uncalibrated"}


def evaluate_artifact(artifact: dict, draws: list[dict], prediction_size: int) -> dict:
    size, draw_size = int(artifact["universe_size"]), int(artifact["draw_size"])
    probs = {int(n): float(p) for n, p in artifact["probabilities"].items()}
    ranking = sorted(probs, key=lambda n: (-probs[n], n))
    labels = [row["main"] for row in draws]
    rows = [probs for _ in labels]
    per_draw_brier = [brier_score([probs], [label], size) for label in labels]
    baseline = (draw_size / size) * (1 - draw_size / size)
    return {"fold_count": len(draws), "brier_score": brier_score(rows, labels, size),
            "log_loss": log_loss(rows, labels, size), "calibration_error": calibration_error(rows, labels, size),
            "average_hits": sum(len(set(ranking[:prediction_size]) & set(label)) for label in labels) / max(1, len(labels)),
            "selection_on_evaluation": False,
            "brier_difference_ci": paired_bootstrap_ci(per_draw_brier, [baseline] * len(draws), iterations=2000),
            "evaluation_manifest": {"target_draw_ids": [str(row["ky"]) for row in draws],
                                    "data_hash": digest(draws), "pipeline": PIPELINE,
                                    "prediction_size": prediction_size, "ticket_count": 1}}


def train_registered_candidate(game: str, cfg: dict, draws: list[dict], mode: str, db_path=None) -> dict:
    holdout = 120 if mode == "fast" else min(480, len(draws) // 4)
    if len(draws) < holdout * 2 + 60:
        raise ValueError("need separate training, validation and test history")
    training, validation, testing = draws[:-holdout * 2], draws[-holdout * 2:-holdout], draws[-holdout:]
    artifact = fit_artifact(game, training, cfg)
    model_id = f"{game.lower()}_{uuid.uuid4().hex[:12]}"
    paths = save_artifact(game, artifact, model_id)
    validation_metrics = evaluate_artifact(artifact, validation, cfg["prediction_size"])
    outer_metrics = evaluate_artifact(artifact, testing, cfg["prediction_size"])
    ledger.register_model(game, PIPELINE, artifact["trained_data_cutoff"], "candidate",
                          artifact_paths=paths, validation_metrics=validation_metrics,
                          outer_backtest_metrics=outer_metrics, feature_version=PIPELINE,
                          config_hash=digest({"prior_strength": 100.0, "pipeline": PIPELINE}),
                          promotion_reason="fixed configuration; chronological validation and independent test; not auto-promoted",
                          model_id=model_id, db_path=db_path)
    return next(row for row in ledger.list_models(game, "candidate", db_path=db_path) if row["model_id"] == model_id)


def champion_prediction(game: str, count: int, prediction_size: int, mode: str, db_path=None) -> dict | None:
    database = Path(db_path or ledger.DEFAULT_DB_PATH)
    models = []
    if database.exists():
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            if connection.execute("SELECT 1 FROM sqlite_master WHERE name='model_registry'").fetchone():
                models = [ledger.row_to_dict(row) for row in connection.execute(
                    "SELECT * FROM model_registry WHERE game_type=? AND status='champion'", (game,))]
    if not models:
        return None
    model = models[0]
    artifact = verify_artifact(model)
    from ai.ml_pipeline import load_actual_draws
    actual = load_actual_draws(game)
    if not actual:
        raise ValueError("canonical history unavailable")
    cutoff = max(int(n) for n in actual)
    if cutoff < int(artifact["trained_data_cutoff"]):
        raise ValueError("champion uses future training data")
    probs = {int(n): float(p) for n, p in artifact["probabilities"].items()}
    ranking = sorted(probs, key=lambda n: (-probs[n], n))
    seed = int(digest({"model": model["model_id"], "target": cutoff + 1, "count": count})[:8], 16)
    rng = random.Random(seed)
    tickets = []
    for index in range(count):
        chosen = ranking[:prediction_size] if index == 0 else sorted(probs, key=lambda n: -math.log(max(rng.random(), 1e-12)) / probs[n])[:prediction_size]
        main = sorted(chosen)
        special = None
        if game == "LOTO_5_35": special = rng.randrange(1, 13)
        if game == "LOTO_6_55": special = rng.choice([n for n in range(1, 56) if n not in main])
        tickets.append({"main": main, "special": special})
    latest = actual[str(cutoff)] if str(cutoff) in actual else max(actual.values(), key=lambda row: int(row["ky"]))
    return {"ok": True, "ready": True, "type": game, "engine": "registry_champion",
            "engineLabel": "Model đã duyệt", "predictionMode": mode, "modelId": model["model_id"],
            "modelVersion": model["version"], "configHash": model["config_hash"],
            "modelArtifactHash": model["artifact_paths"]["sha256"], "registryModel": True,
            "modelTrainingCutoff": artifact["trained_data_cutoff"], "latestKy": str(cutoff), "nextKy": str(cutoff + 1),
            "latestDate": latest["date"], "latestTime": latest["time"],
            "historyCount": len(actual), "pickSize": prediction_size, "bundleCount": count,
            "tickets": tickets, "topRanking": ranking, "rawScore": artifact["probabilities"],
            "adaptiveProbabilities": artifact["probabilities"], "randomSeed": seed,
            "notes": ["Champion dùng artifact đã duyệt; chỉ số đánh giá là holdout đã lưu, không phải cam kết lợi thế cho kỳ mới."]}


def record_execution_snapshot(payload: dict, db_path=None) -> dict:
    """Identify legacy execution separately from promoted models; never auto-approve."""
    game = payload["type"]
    if payload.get("modelId"):
        return payload
    sources = [dp.PROJECT_ROOT / "ai/predictors/ai_predict.py", dp.PROJECT_ROOT / "ai/adaptive_coverage.py"]
    standalone = {"LOTO_5_35": "loto_5_35", "LOTO_6_45": "mega_6_45", "LOTO_6_55": "power_6_55"}.get(game)
    if payload.get("predictionMode") == "vip" and standalone:
        base = dp.PROJECT_ROOT / "ai/standalone_predictors" / f"{standalone}_predictor"
        sources += list((base / "src").glob("*.py")) + list((base / "config").glob("*.json")) + list((base / "state").glob("*.json"))
        sources += [path for path in (base / "models").glob("*") if path.is_file()]
    else:
        base = dp.PROJECT_ROOT / "ai/models" / game
        sources += [path for path in base.glob("*.json") if path.is_file()]
    fingerprints = {str(path.relative_to(dp.PROJECT_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources if path.is_file()}
    manifest = {"game_type": game, "engine": payload.get("engine"), "prediction_mode": payload.get("predictionMode"),
                "risk_mode": payload.get("riskMode"), "files": fingerprints}
    execution_hash = digest(manifest)
    model_id = f"execution_{game.lower()}_{execution_hash[:20]}"
    connection = ledger.connect(db_path)
    try:
        exists = connection.execute("SELECT 1 FROM model_registry WHERE model_id=?", (model_id,)).fetchone()
    finally:
        connection.close()
    if not exists:
        try:
            ledger.register_model(game, str(payload.get("modelVersion") or payload.get("engine") or "legacy"),
                                  str(payload.get("latestKy") or ""), "archived", model_id=model_id,
                                  artifact_paths={"model_type": "execution_manifest", "manifest": manifest},
                                  config_hash=execution_hash, promotion_reason="execution snapshot; effectiveness not approved", db_path=db_path)
        except sqlite3.IntegrityError:
            pass
    return {**payload, "modelId": model_id, "configHash": execution_hash, "executionManifest": manifest,
            "modelApprovalStatus": "unapproved_execution_snapshot"}
