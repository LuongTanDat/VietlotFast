"""Chronological diagnostic of the production web pipeline, without production writes.

Validation selects one method before the independent final test is evaluated.  Each
prediction sees an immutable history prefix.  Registry models are frozen read-only
and rejected if their training includes any held-out target.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sqlite3
import sys
from collections import Counter
from contextlib import closing, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from statistics import mean
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai import controlled_models, ml_pipeline, prediction_effectiveness as effect, prediction_ledger as ledger
from ai.configs import data_paths as dp
from ai.evaluation.statistical_tests import paired_bootstrap_ci
from backend.file_guard import version

PIPELINE = "chronological_web_lab_v1"
MIN_TRAINING = 60
DEFAULT_VALIDATION = 10
DEFAULT_TEST = 20
METHODS = dict(effect.METHODS)


def _digest(value: Any) -> str:
    return hashlib.sha256(ledger.canonical_json(value).encode("utf-8")).hexdigest()


def _parameters(game: str, ticket_count: int, validation_count: int, test_count: int) -> dict:
    game = effect._game(game)
    for value, minimum, maximum, label in (
        (ticket_count, 1, 10, "Số vé"),
        (validation_count, 5, 50, "Số kỳ validation"),
        (test_count, 5, 50, "Số kỳ test"),
    ):
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"{label} phải trong khoảng {minimum}–{maximum}.")
    if validation_count + test_count > 100:
        raise ValueError("Tổng số kỳ đánh giá tối đa 100.")
    return {"game": game, "ticketCount": ticket_count,
            "validationCount": validation_count, "testCount": test_count}


def _source_manifest() -> dict:
    names = (
        "ai/algorithm_lab.py", "ai/predictors/ai_predict.py", "ai/predictors/number_scoring.py",
        "ai/adaptive_coverage.py", "ai/controlled_models.py", "ai/ml_pipeline.py",
        "ai/prediction_effectiveness.py", "ai/prediction_ledger.py", "ai/prizes.py",
        "ai/evaluation/probability.py", "ai/evaluation/metrics.py", "ai/evaluation/statistical_tests.py",
        "ai/configs/data_paths.py", "backend/live_results.py",
    )
    return {name: hashlib.sha256((dp.PROJECT_ROOT / name).read_bytes()).hexdigest()
            for name in names if (dp.PROJECT_ROOT / name).is_file()}


@dataclass
class FrozenRegistry:
    model: dict | None = None
    artifact: dict | None = None
    db_path: Path | None = None
    artifact_path: Path | None = None
    artifact_hash: str = ""

    def provenance(self) -> dict:
        if self.model is None:
            return {"mode": "legacy_classic", "modelId": None, "artifactPolicy": "no registry champion at start"}
        return {"mode": "frozen_registry_champion", "modelId": self.model["model_id"],
                "modelVersion": self.model["version"], "trainedCutoff": self.artifact["trained_data_cutoff"],
                "artifactHash": self.artifact_hash,
                "trainingDataHash": self.artifact.get("training_data_hash", "")}

    def assert_unchanged(self):
        if self.artifact_path is not None:
            if hashlib.sha256(self.artifact_path.read_bytes()).hexdigest() != self.artifact_hash:
                raise RuntimeError("Artifact thay đổi trong khi chạy lab; không trả bằng chứng đánh giá.")


def _freeze_registry(game: str, history: list[dict], first_target: str, db_path=None) -> FrozenRegistry:
    database = Path(db_path or ledger.DEFAULT_DB_PATH)
    if not database.is_file():
        return FrozenRegistry(db_path=database)
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='model_registry'").fetchone():
            return FrozenRegistry(db_path=database)
        raw = connection.execute("SELECT * FROM model_registry WHERE game_type=? AND status='champion'", (game,)).fetchone()
    if raw is None:
        return FrozenRegistry(db_path=database)
    model = ledger.row_to_dict(raw)
    artifact = controlled_models.verify_artifact(model)
    trained_cutoff = int(artifact["trained_data_cutoff"])
    if trained_cutoff >= int(first_target):
        raise ValueError("Champion đã huấn luyện bằng kỳ thuộc validation/test. Lab từ chối replay để tránh nhìn trước kết quả; không đổi model sản xuất.")
    trained_history = [row for row in history if int(row["ky"]) <= trained_cutoff]
    if not trained_history or int(trained_history[-1]["ky"]) != trained_cutoff:
        raise ValueError("Không tìm được cutoff huấn luyện của champion trong canonical.")
    if artifact.get("training_data_hash") != _digest(trained_history):
        raise ValueError("Snapshot huấn luyện champion không khớp prefix canonical; không thể chứng minh replay không rò rỉ.")
    path = Path(model["artifact_paths"]["model"])
    return FrozenRegistry(copy.deepcopy(model), copy.deepcopy(artifact), database, path,
                          str(model["artifact_paths"]["sha256"]))


class _FrozenSelect:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class _FrozenRegistryReader:
    """The production loader can only select the registry record frozen at start."""
    row_factory = None

    def __init__(self, model):
        self.model = model

    def execute(self, sql, params=()):
        if sql.startswith("SELECT 1 FROM sqlite_master"):
            return _FrozenSelect([{"exists": 1}])
        if sql.startswith("SELECT * FROM model_registry") and tuple(params) == (self.model["game_type"],):
            return _FrozenSelect([copy.deepcopy(self.model)])
        raise ValueError("Lab chỉ cho đọc registry snapshot đã khóa.")

    def close(self):
        pass


def _prefix_summary(game: str, prefix: list[dict]) -> dict:
    return {"type": game, "historyFile": "immutable_history_prefix", "historyCount": len(prefix),
            "bootstrapComplete": True, "sourceLimited": False,
            "latestKy": prefix[-1]["ky"], "latestDate": prefix[-1]["date"],
            "latestTime": prefix[-1]["time"], "effectiveEarliestKy": prefix[0]["ky"],
            "effectiveEarliestDate": prefix[0]["date"], "newRows": 0, "updatedRows": 0,
            "errors": [], "seedFiles": [], "syncedAt": "historical_cutoff"}


def _production_prediction(game: str, count: int, prefix: list[dict], registry: FrozenRegistry) -> dict:
    from ai.predictors import ai_predict as predictor
    prefix = copy.deepcopy(prefix)
    actual = {str(row["ky"]): copy.deepcopy(row) for row in prefix}
    draws = [{**row, "date_obj": effect._draw_at(row, game).date(),
              "weekday": effect._draw_at(row, game).weekday()} for row in prefix]
    original_champion = controlled_models.champion_prediction

    def frozen_champion(*args, **kwargs):
        if registry.model is None:
            return None
        registry.assert_unchanged()
        adapter = SimpleNamespace(Row=sqlite3.Row, connect=lambda *a, **k: _FrozenRegistryReader(registry.model))
        with patch.object(controlled_models, "sqlite3", adapter), \
                patch.object(controlled_models, "verify_artifact", return_value=copy.deepcopy(registry.artifact)):
            return original_champion(*args, **kwargs, db_path=registry.db_path)

    with patch.object(predictor, "sync_ai_history", return_value=_prefix_summary(game, prefix)), \
            patch.object(predictor, "build_readonly_sync_summary", return_value=_prefix_summary(game, prefix)), \
            patch.object(predictor, "load_ai_draws", return_value=draws), \
            patch.object(ml_pipeline, "load_actual_draws", return_value=actual), \
            patch.object(controlled_models, "champion_prediction", side_effect=frozen_champion), \
            patch.object(ledger, "connect", side_effect=AssertionError("Lab không được ghi ledger.")):
        result = predictor.predict_json(game, count, engine="classic", risk_mode="balanced",
                                        prediction_mode="normal", lock_ledger=False)
    result = dict(result)
    if (result.get("adaptiveCoverage") or {}).get("seed") is not None:
        result["randomSeed"] = int(result["adaptiveCoverage"]["seed"])
    return result


def _fold_snapshot(game: str, prefix: list[dict], target: dict) -> dict:
    return {"draws": prefix, "actual": {str(row["ky"]): row for row in prefix},
            "dataHash": _digest(prefix), "cutoff": str(prefix[-1]["ky"]), "target": str(target["ky"])}


def _measure(game: str, payload: dict, actual: dict) -> dict:
    from ai.prizes import classify_ticket
    cfg = ml_pipeline.game_config(game)
    metrics = ledger.score_prediction_payload(payload, actual, cfg["universe_size"], cfg["draw_size"], cfg["prediction_size"])
    tickets = [{"main": list(ticket["main"]), "special": ticket.get("special"),
                "result": classify_ticket(game, ticket, actual)} for ticket in payload["tickets"]]
    hits = [item["hit_count"] for item in metrics["per_ticket"]]
    return {"tickets": tickets, "meanHits": metrics["mean_hits_per_ticket"], "bestHits": metrics["hit_count"],
            "brierScore": metrics["brier_score"], "logLoss": metrics["log_loss"],
            "rate3": sum(n >= 3 for n in hits) / len(hits), "rate4": sum(n >= 4 for n in hits) / len(hits),
            "prizeHistogram": dict(Counter(ticket["result"]["prizeCode"] for ticket in tickets)),
            "engine": payload.get("engine"), "modelId": payload.get("modelId"), "seed": payload.get("randomSeed"),
            "probabilityCalibrationStatus": payload.get("probabilityCalibrationStatus", "uncalibrated"),
            "probabilities": payload["probabilities"], "payloadChecksum": ledger.payload_checksum(payload)}


def _summary(method: str, samples: list[dict], random_samples: list[dict]) -> dict:
    count = len(samples)
    hits = [item["meanHits"] for item in samples]
    comparison = [item["meanHits"] for item in random_samples]
    ci = paired_bootstrap_ci(hits, comparison, iterations=2000)
    brier_ci = paired_bootstrap_ci([item["brierScore"] for item in samples],
                                   [item["brierScore"] for item in random_samples], iterations=2000)
    codes = Counter()
    for item in samples:
        codes.update(item["prizeHistogram"])
    return {"sampleCount": count, "meanHits": mean(hits),
            "brierScore": mean(item["brierScore"] for item in samples),
            "logLoss": mean(item["logLoss"] for item in samples),
            "rate3": mean(item["rate3"] for item in samples), "rate4": mean(item["rate4"] for item in samples),
            "deltaVsRandom": ci["mean"], "ci95": {"lower": ci["lower"], "upper": ci["upper"]},
            "brierDeltaVsRandom": brier_ci["mean"], "brierCi95": {"lower": brier_ci["lower"], "upper": brier_ci["upper"]},
            "prizeHistogram": dict(codes), "decision": "baseline" if method == "random" else (
                "insufficient_evidence" if count < 30 else "possible_improvement" if ci["lower"] > 0 and brier_ci["upper"] < 0 else "no_clear_advantage")}


def _section(draws: list[dict]) -> dict:
    return {"count": len(draws), "firstDrawId": str(draws[0]["ky"]), "lastDrawId": str(draws[-1]["ky"])}


def evaluate_draws(game: str, history: list[dict], ticket_count: int = 3,
                   validation_count: int = DEFAULT_VALIDATION, test_count: int = DEFAULT_TEST,
                   registry: FrozenRegistry | None = None, progress=None) -> dict:
    """Evaluate immutable supplied history; no canonical/model/state/ledger writes."""
    parameters = _parameters(game, ticket_count, validation_count, test_count)
    game = parameters.pop("game")
    history = copy.deepcopy(history)
    if len(history) < MIN_TRAINING + validation_count + test_count:
        raise ValueError("Cần ít nhất 60 kỳ train trước validation và test riêng.")
    ids = [int(row["ky"]) for row in history]
    if ids != sorted(set(ids)) or any(right != left + 1 for left, right in zip(ids, ids[1:])):
        raise ValueError("Lịch sử phải tăng theo kỳ, không lặp hoặc thiếu kỳ trong phạm vi replay.")
    for row in history:
        effect._validate_actual_row(row, game)
    first_index = len(history) - validation_count - test_count
    registry = registry or _freeze_registry(game, history[:first_index], str(history[first_index]["ky"]))
    if registry.artifact is not None and int(registry.artifact["trained_data_cutoff"]) >= int(history[first_index]["ky"]):
        raise ValueError("Artifact huấn luyện sau cutoff đầu tiên; lab từ chối rò rỉ tương lai.")
    manifest = _source_manifest()
    folds = []
    grouped = {phase: {method: [] for method in METHODS} for phase in ("validation", "test")}
    selected = None
    for phase, start, end in (("validation", first_index, first_index + validation_count),
                              ("test", first_index + validation_count, len(history))):
        if phase == "test":
            summaries = {method: _summary(method, grouped["validation"][method], grouped["validation"]["random"]) for method in METHODS}
            preference = {key: index for index, key in enumerate(("random", "bayesian", "ewma", "web"))}
            selected = min(METHODS, key=lambda key: (summaries[key]["brierScore"], preference[key]))
        for index in range(start, end):
            prefix, target = copy.deepcopy(history[:index]), copy.deepcopy(history[index])
            snapshot = _fold_snapshot(game, prefix, target)
            payloads = {"web": _production_prediction(game, ticket_count, prefix, registry)}
            for method in ("random", "bayesian", "ewma"):
                payloads[method] = effect._baseline(game, method, ticket_count, snapshot)
            fold_methods = {}
            for method, payload in payloads.items():
                effect._validate(payload, game, ticket_count, snapshot)
                result = _measure(game, payload, target)
                grouped[phase][method].append(result)
                fold_methods[method] = result
            folds.append({"phase": phase, "targetDrawId": str(target["ky"]), "cutoffDrawId": str(prefix[-1]["ky"]),
                          "dataHash": snapshot["dataHash"], "actualMain": list(target["main"]),
                          "actualSpecial": target.get("special"), "methods": fold_methods})
            if progress:
                progress(len(folds), validation_count + test_count)
    registry.assert_unchanged()
    if _source_manifest() != manifest:
        raise RuntimeError("Mã nguồn thay đổi trong khi chạy lab; kết quả không còn một phiên bản cố định.")
    methods = [{"key": key, "label": label, "selected": key == selected,
                "validation": _summary(key, grouped["validation"][key], grouped["validation"]["random"]),
                "test": _summary(key, grouped["test"][key], grouped["test"]["random"])} for key, label in METHODS.items()]
    return {"ok": True, "status": "completed", "type": game, "label": ml_pipeline.game_config(game)["label"],
            "scope": "historical_diagnostic", "pipeline": PIPELINE, "parameters": parameters,
            "split": {"training": _section(history[:first_index]),
                      "validation": _section(history[first_index:first_index + validation_count]),
                      "test": _section(history[first_index + validation_count:])},
            "selection": {"selectedMethod": selected, "label": METHODS[selected], "metric": "brier_score",
                          "validationOnly": True, "reason": "Chọn Brier thấp nhất trên validation; đồng điểm ưu tiên đối chứng đơn giản. Không chọn lại bằng test."},
            "methods": methods, "folds": folds,
            "provenance": {"sourceHash": _digest(manifest), "sourceManifest": manifest, "dataHash": _digest(history),
                           "latestDrawId": str(history[-1]["ky"]), "registryModel": registry.provenance(),
                           "trainingPolicy": "frozen artifacts; no fold retraining", "predictionMode": "normal",
                           "requestedEngine": "classic", "riskMode": "balanced", "calibrationStatus": "uncalibrated"},
            "notes": ["Đây là kiểm tra lịch sử theo thời gian, tách khỏi dự đoán tương lai đã khóa; không phải bằng chứng trúng chắc chắn.",
                      "Mỗi fold chỉ thấy prefix trước kỳ mục tiêu. Phương pháp được chọn bằng validation trước khi chấm test.",
                      "Không retrain, thay model, ghi ledger hoặc tự promote. Web gồm engine thực, ranking và Adaptive Coverage/champion được ghim.",
                      "CI ghép cặp theo kỳ; chưa điều chỉnh thử nhiều phương pháp. Dưới 30 kỳ: chưa đủ bằng chứng lợi thế.",
                      "Giải được phân loại theo luật; số phụ Power do AI dự đoán không quyết định Jackpot 2. Không suy tiền nhận từ quỹ giải.",
                      "Xác suất biên chưa hiệu chỉnh. Việc đã xem lịch sử trước đây vẫn làm nghiên cứu này khác một tập tương lai chưa dùng."]}


def run(game: str, ticket_count: int = 3, validation_count: int = DEFAULT_VALIDATION,
        test_count: int = DEFAULT_TEST, progress=None) -> dict:
    _parameters(game, ticket_count, validation_count, test_count)
    game = effect._game(game)
    snapshot = effect._snapshot(game)
    result = evaluate_draws(game, snapshot["draws"], ticket_count, validation_count, test_count, progress=progress)
    if version(snapshot["path"]) != snapshot["version"]:
        raise RuntimeError("Canonical thay đổi trong khi lab chạy; thử lại để dùng cùng snapshot.")
    result["provenance"].update({"sourceVersion": list(snapshot["version"]),
                                  "sourcePath": str(snapshot["path"].relative_to(dp.PROJECT_ROOT))})
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("run",), default="run")
    parser.add_argument("--game", choices=effect.GAMES, required=True)
    parser.add_argument("--ticket-count", type=int, default=3)
    parser.add_argument("--validation-count", type=int, default=DEFAULT_VALIDATION)
    parser.add_argument("--test-count", type=int, default=DEFAULT_TEST)
    args = parser.parse_args(argv)
    try:
        with redirect_stdout(StringIO()):
            result = run(args.game, args.ticket_count, args.validation_count, args.test_count,
                         progress=lambda done, total: print(json.dumps({"completed": done, "total": total}), file=sys.stderr))
    except Exception as exc:
        result = {"ok": False, "type": args.game, "scope": "historical_diagnostic", "error": str(exc), "message": str(exc)}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
