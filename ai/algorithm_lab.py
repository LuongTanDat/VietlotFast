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
import sqlite3
import sys
import tempfile
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

from ai import controlled_models, lab_profiles, ml_pipeline, prediction_effectiveness as effect, prediction_ledger as ledger
from ai.configs import data_paths as dp
from ai.evaluation.statistical_tests import paired_bootstrap_ci
from backend.file_guard import version

PIPELINE = "chronological_web_lab_v2"
MIN_TRAINING = 60
DEFAULT_VALIDATION = 20
DEFAULT_TEST = 30
CONTROLS = dict(effect.METHODS)
PROFILES = lab_profiles.list_profiles()
METHODS = {**CONTROLS, **{profile["id"]: profile["label"] for profile in PROFILES}}


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
        "ai/algorithm_lab.py", "ai/lab_profiles.py", "ai/lab_trials.py", "ai/lab_store.py",
        "ai/predictors/ai_predict.py", "ai/predictors/number_scoring.py",
        "ai/adaptive_coverage.py", "ai/controlled_models.py", "ai/ml_pipeline.py",
        "ai/prediction_effectiveness.py", "ai/prediction_ledger.py", "ai/prizes.py",
        "ai/evaluation/probability.py", "ai/evaluation/metrics.py", "ai/evaluation/statistical_tests.py",
        "ai/evaluation/baselines.py", "ai/configs/data_paths.py", "backend/live_results.py", "backend/file_guard.py",
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
        if self.model is not None and self.db_path is not None and not self.db_path.is_file():
            raise RuntimeError("Registry không còn tồn tại trong khi chạy lab; không tự đổi engine.")
        if self.artifact_path is not None:
            if hashlib.sha256(self.artifact_path.read_bytes()).hexdigest() != self.artifact_hash:
                raise RuntimeError("Artifact thay đổi trong khi chạy lab; không trả bằng chứng đánh giá.")


def _registry_rows_readonly(database: Path, game: str) -> list[dict]:
    # Even mode=ro may create WAL/SHM sidecars beside the source database.
    # Read SQLite only on a private byte snapshot, including the WAL; immutable=1
    # would incorrectly ignore committed data that still exists only in the WAL.
    wal = database.with_name(database.name + "-wal")
    journal = database.with_name(database.name + "-journal")
    if journal.exists():
        raise RuntimeError("Registry đang có rollback journal; thử lại sau khi giao dịch hoàn tất.")
    before = {path: version(path) for path in (database, wal)}
    with tempfile.TemporaryDirectory(prefix="algorithm_lab_registry_") as directory:
        copied = Path(directory) / "registry.sqlite"
        copied.write_bytes(database.read_bytes())
        if before[wal] is not None:
            copied.with_name(copied.name + "-wal").write_bytes(wal.read_bytes())
        if journal.exists() or any(version(path) != value for path, value in before.items()):
            raise RuntimeError("Registry thay đổi trong lúc tạo snapshot; thử lại để ghim cùng phiên bản.")
        with closing(sqlite3.connect(copied.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='model_registry'").fetchone():
                return []
            return [dict(row) for row in connection.execute(
                "SELECT * FROM model_registry WHERE game_type=? AND status='champion'", (game,))]


def _freeze_registry(game: str, history: list[dict], first_target: str, db_path=None) -> FrozenRegistry:
    database = Path(db_path or ledger.DEFAULT_DB_PATH)
    if not database.is_file():
        return FrozenRegistry(db_path=database)
    rows = _registry_rows_readonly(database, game)
    if not rows:
        return FrozenRegistry(db_path=database)
    if len(rows) != 1:
        raise ValueError("Registry có nhiều champion cho cùng game; lab từ chối kết quả không xác định.")
    model = ledger.row_to_dict(rows[0])
    artifact = controlled_models.verify_artifact(model)
    cfg = ml_pipeline.game_config(game)
    if (artifact.get("universe_size"), artifact.get("draw_size")) != (cfg["universe_size"], cfg["draw_size"]):
        raise ValueError("Miền số của artifact không khớp game; lab không đổi sang engine khác.")
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


def _validate_registry_prefix(registry: FrozenRegistry, game: str, prefix: list[dict], first_target: str):
    if (registry.model is None) != (registry.artifact is None):
        raise ValueError("Registry snapshot thiếu model hoặc artifact.")
    if registry.artifact is None:
        return
    artifact = registry.artifact
    cfg = ml_pipeline.game_config(game)
    if artifact.get("game_type") != game or registry.model.get("game_type") != game:
        raise ValueError("Registry snapshot không khớp game.")
    if (artifact.get("universe_size"), artifact.get("draw_size")) != (cfg["universe_size"], cfg["draw_size"]):
        raise ValueError("Miền số của artifact không khớp game.")
    cutoff = int(artifact["trained_data_cutoff"])
    if cutoff >= int(first_target):
        raise ValueError("Artifact huấn luyện sau cutoff đầu tiên; lab từ chối rò rỉ tương lai.")
    training = [row for row in prefix if int(row["ky"]) <= cutoff]
    if not training or int(training[-1]["ky"]) != cutoff or artifact.get("training_data_hash") != _digest(training):
        raise ValueError("Snapshot huấn luyện champion không khớp prefix canonical.")
    registry.assert_unchanged()


class _FrozenSelect:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)

    def __iter__(self):
        return iter(self.rows)


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
            "profileId": payload.get("labProfileId"), "configHash": payload.get("configHash"),
            "allocation": payload.get("allocation"),
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


def _choose_candidate(samples: dict[str, list[dict]]) -> str:
    # Allocation pairs have the same marginal estimates. Resolve Brier ties by
    # validation hits, never by held-out test scores or rare jackpot sightings.
    return min((profile["id"] for profile in PROFILES), key=lambda key: (
        mean(item["brierScore"] for item in samples[key]),
        -mean(item["meanHits"] for item in samples[key]),
        next(index for index, profile in enumerate(PROFILES) if profile["id"] == key)))


def _comparison(candidate: list[dict], control: list[dict]) -> dict:
    hits = paired_bootstrap_ci([item["meanHits"] for item in candidate],
                               [item["meanHits"] for item in control], iterations=2000)
    brier = paired_bootstrap_ci([item["brierScore"] for item in candidate],
                                [item["brierScore"] for item in control], iterations=2000)
    return {"meanHitsDelta": hits["mean"], "brierDelta": brier["mean"],
            "logLossDelta": mean(item["logLoss"] for item in candidate) - mean(item["logLoss"] for item in control),
            "hitCi95": {"lower": hits["lower"], "upper": hits["upper"]},
            "brierCi95": {"lower": brier["lower"], "upper": brier["upper"]}}


def _conclusion(candidate_id: str, grouped: dict) -> dict:
    candidate = grouped["test"][candidate_id]
    sample_count = len(candidate)
    evidence = {key: _comparison(candidate, grouped["test"][key]) for key in ("random", "web")}
    supported = all(item["brierCi95"]["upper"] < 0 and item["logLossDelta"] < 0
                    and item["hitCi95"]["lower"] > 0 for item in evidence.values())
    label = METHODS[candidate_id]
    if sample_count < 30:
        status, title = "insufficient_evidence", "Chưa đủ kỳ để kết luận"
        message = (f"{label} được chọn từ tập chọn cấu hình và đã kiểm tra trên {sample_count} kỳ riêng. "
                   "Cần ít nhất 30 kỳ kiểm tra; chênh lệch hiện tại chưa đủ làm căn cứ áp dụng.")
    elif supported:
        status, title = "possible_improvement", "Ứng viên có dấu hiệu tốt hơn"
        message = (f"{label} có Brier và log loss thấp hơn, số trùng cao hơn cả ngẫu nhiên và web "
                   f"trên {sample_count} kỳ kiểm tra, với khoảng tin cậy hỗ trợ chênh lệch. "
                   "Đây vẫn là kết quả chẩn đoán lịch sử, cần kiểm chứng trên các kỳ sắp tới.")
    else:
        status, title = "no_clear_advantage", "Chưa thấy lợi thế rõ ràng"
        message = (f"{label} chưa vượt đồng thời ngẫu nhiên và web trên {sample_count} kỳ kiểm tra "
                   "về chất lượng xác suất và số trùng với khoảng tin cậy hỗ trợ. "
                   "Giữ cấu hình web hiện tại và theo dõi ứng viên trên kỳ sắp tới để kiểm chứng.")
    return {"status": status, "title": title, "message": message,
            "recommendation": "Khóa dự đoán ứng viên trước quay và đối chiếu các kỳ sắp tới; chưa tự áp dụng vào web.",
            "canTrack": True, "candidateProfileId": candidate_id, "candidateLabel": label,
            "sampleCount": sample_count, "minimumSampleCount": 30, "evidence": evidence,
            "selectedOn": "validation", "scope": "historical_diagnostic",
            "highPrizeNote": "ĐB/Jackpot là thống kê riêng; chọn Brier không chứng minh tăng xác suất trúng giải cao."}


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
    times = [effect._draw_at(row, game) for row in history]
    if any(right <= left for left, right in zip(times, times[1:])):
        raise ValueError("Ngày/giờ kết quả phải tăng theo kỳ để chia train/validation/test đúng thời gian.")
    first_index = len(history) - validation_count - test_count
    registry = registry or _freeze_registry(game, history[:first_index], str(history[first_index]["ky"]))
    _validate_registry_prefix(registry, game, history[:first_index], str(history[first_index]["ky"]))
    manifest = _source_manifest()
    folds = []
    grouped = {phase: {method: [] for method in METHODS} for phase in ("validation", "test")}
    selected, candidate_id = None, None
    for phase, start, end in (("validation", first_index, first_index + validation_count),
                              ("test", first_index + validation_count, len(history))):
        if phase == "test":
            summaries = {method: _summary(method, grouped["validation"][method], grouped["validation"]["random"]) for method in METHODS}
            preference = {key: index for index, key in enumerate(("random", "bayesian", "ewma", "web", *(p["id"] for p in PROFILES)))}
            selected = min(METHODS, key=lambda key: (summaries[key]["brierScore"], preference[key]))
            candidate_id = _choose_candidate(grouped["validation"])
        for index in range(start, end):
            prefix, target = copy.deepcopy(history[:index]), copy.deepcopy(history[index])
            snapshot = _fold_snapshot(game, prefix, target)
            payloads = {"web": _production_prediction(game, ticket_count, prefix, registry)}
            for method in ("random", "bayesian", "ewma"):
                payloads[method] = effect._baseline(game, method, ticket_count, snapshot)
            for profile in PROFILES:
                payloads[profile["id"]] = lab_profiles.predict_profile(game, profile["id"], prefix, ticket_count)
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
    candidate_config = lab_profiles.profile_definition(candidate_id)
    methods = [{"key": key, "label": label, "selected": key == selected,
                "kind": "control" if key in CONTROLS else "candidate",
                "profileId": None if key in CONTROLS else key,
                "configuration": None if key in CONTROLS else lab_profiles.profile_definition(key),
                "validation": _summary(key, grouped["validation"][key], grouped["validation"]["random"]),
                "test": _summary(key, grouped["test"][key], grouped["test"]["random"])} for key, label in METHODS.items()]
    return {"ok": True, "status": "completed", "type": game, "label": ml_pipeline.game_config(game)["label"],
            "scope": "historical_diagnostic", "pipeline": PIPELINE, "parameters": parameters,
            "profileVersion": lab_profiles.PROFILE_VERSION, "profiles": copy.deepcopy(PROFILES),
            "split": {"training": _section(history[:first_index]),
                      "validation": _section(history[first_index:first_index + validation_count]),
                      "test": _section(history[first_index + validation_count:])},
            "selection": {"selectedMethod": selected, "label": METHODS[selected], "metric": "brier_score",
                          "validationOnly": True, "reason": "Chọn Brier thấp nhất trên tập chọn cấu hình; đồng điểm ưu tiên đối chứng đơn giản. Ứng viên đồng Brier chọn theo số trùng trên cùng tập này. Không chọn lại bằng tập kiểm tra.",
                          "candidateProfileId": candidate_id, "candidateLabel": METHODS[candidate_id],
                          "profileDefinition": candidate_config, "candidateConfig": candidate_config,
                          "configHash": lab_profiles.config_hash(candidate_config)},
            "conclusion": _conclusion(candidate_id, grouped),
            "methods": methods, "folds": folds,
            "provenance": {"sourceHash": _digest(manifest), "sourceManifest": manifest, "dataHash": _digest(history),
                           "latestDrawId": str(history[-1]["ky"]), "registryModel": registry.provenance(),
                           "profileVersion": lab_profiles.PROFILE_VERSION,
                           "trainingPolicy": "frozen artifacts; prefix-only deterministic scoring; no fold retraining", "predictionMode": "normal",
                           "requestedEngine": "classic", "riskMode": "balanced", "calibrationStatus": "uncalibrated",
                           "runtime": {"python": sys.version.split()[0],
                                       "numpy": getattr(sys.modules.get("numpy"), "__version__", None)}},
            "notes": ["Đây là kiểm tra lịch sử theo thời gian, tách khỏi dự đoán tương lai đã khóa; không phải bằng chứng trúng chắc chắn.",
                      "Mỗi fold chỉ thấy prefix trước kỳ mục tiêu. Phương pháp được chọn bằng validation trước khi chấm test.",
                      "Thử 6 cấu hình thực: ba cửa sổ lịch sử/trọng số và hai cách phân bổ vé. Mỗi phương pháp cùng số vé, cùng cỡ vé và cutoff.",
                      "Không retrain, thay model, ghi ledger hoặc tự promote. Web gồm engine thực, ranking và Adaptive Coverage/champion được ghim.",
                      "CI ghép cặp theo kỳ; chưa điều chỉnh thử nhiều phương pháp. Dưới 30 kỳ: chưa đủ bằng chứng lợi thế.",
                      "30 kỳ là ngưỡng tối thiểu, không tự đủ để kết luận: vẫn cần CI hỗ trợ so với cả ngẫu nhiên và web, rồi kiểm chứng trước quay.",
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
