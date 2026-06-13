from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STANDALONE_ROOT = Path(__file__).resolve().parents[2]
if str(STANDALONE_ROOT) not in sys.path:
    sys.path.insert(0, str(STANDALONE_ROOT))

from shared_deep import load_artifacts, save_artifacts, train_numpy_cnn_gru
from src import config as cfg, csv_loader, deep_dataset


MODEL_FILE_NAME = "cnn_rnn_model.pt"
SCALER_FILE_NAME = "scaler.pkl"
MODEL_TYPE = "cnn_gru_numpy"
MODEL_VERSION = "loto_5_35_deep_v1"


def _empty_main_scores() -> dict[int, float]:
    return {number: 0.0 for number in range(1, 36)}


def _empty_bonus_scores() -> dict[int, float]:
    return {number: 0.0 for number in range(1, 13)}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _model_paths() -> dict[str, Path]:
    return {
        "model": cfg.MODELS_DIR / MODEL_FILE_NAME,
        "scaler": cfg.MODELS_DIR / SCALER_FILE_NAME,
        "meta": cfg.MODEL_META_PATH,
    }


def _deep_config(config_payload: dict[str, Any]) -> dict[str, Any]:
    defaults = {
        "sequence_length": 10,
        "min_samples_required_for_deep": 120,
        "epochs": 24,
        "batch_size": 32,
        "learning_rate": 0.003,
        "weight_decay": 0.0001,
        "validation_ratio": 0.18,
        "early_stopping_patience": 5,
        "early_stopping_min_delta": 0.0005,
        "conv_channels": 16,
        "hidden_size": 24,
        "shared_size": 32,
        "kernel_size": 3,
        "seed": 20260403,
        "retrain_every_n_draws": 6,
        "fine_tune_enabled": True,
        "fine_tune_epochs": 6,
    }
    payload = dict(defaults)
    payload.update(dict((config_payload or {}).get("deep_training") or {}))
    payload["head_weights"] = {"main": 1.0, "extra": 0.42, "regime": 0.16}
    payload["ticket_size"] = int((config_payload or {}).get("main_count", 5) or 5)
    payload["top_k"] = max(payload["ticket_size"], int((((config_payload or {}).get("candidate_pool") or {}).get("main", 14)) or 14))
    return payload


def _status_line(enabled: bool, status: str, reason: str, meta: dict[str, Any] | None = None) -> str:
    meta = dict(meta or {})
    if enabled:
        return (
            f"DEEP STATUS: ACTIVE ({meta.get('model_type', MODEL_TYPE)} "
            f"{meta.get('version', MODEL_VERSION)}, trained {meta.get('trained_at', 'unknown')})"
        )
    return f"DEEP STATUS: {str(status or 'fallback_heuristic_only').upper()} ({reason})"


def _public_status_payload(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "deep_enabled": bool(status.get("deep_enabled")),
        "deep_status": str(status.get("deep_status", "fallback_heuristic_only")),
        "deep_status_reason": str(status.get("deep_status_reason", "")),
        "deep_status_line": str(status.get("deep_status_line", "")),
        "deep_model_type": str(status.get("deep_model_type", MODEL_TYPE)),
        "deep_model_version": str(status.get("deep_model_version", MODEL_VERSION)),
        "deep_last_trained_at": str(status.get("deep_last_trained_at", "")),
        "deep_artifacts": dict(status.get("deep_artifacts") or {}),
    }


def _inspect_artifacts(feature_names: list[str] | None = None, sequence_length: int | None = None) -> dict[str, Any]:
    paths = _model_paths()
    meta = _read_json(paths["meta"], {})
    status = {
        "deep_enabled": False,
        "deep_status": "fallback_heuristic_only",
        "deep_status_reason": "",
        "deep_model_type": str(meta.get("model_type", MODEL_TYPE) or MODEL_TYPE),
        "deep_model_version": str(meta.get("version", MODEL_VERSION) or MODEL_VERSION),
        "deep_last_trained_at": str(meta.get("trained_at", "")),
        "deep_artifacts": {
            "model_exists": paths["model"].exists(),
            "scaler_exists": paths["scaler"].exists(),
            "meta_exists": paths["meta"].exists(),
        },
    }
    feature_flags = cfg.load_feature_flags()
    if not bool(feature_flags.get("deep_model_enabled", True)) and not bool(feature_flags.get("deep_model_scaffold", True)):
        status["deep_status_reason"] = "deep scoring disabled by feature flag"
        status["deep_status_line"] = _status_line(False, status["deep_status"], status["deep_status_reason"], meta)
        return status
    if not paths["model"].exists() or not paths["scaler"].exists() or not paths["meta"].exists():
        status["deep_status_reason"] = "missing model/scaler/meta artifacts"
        status["deep_status_line"] = _status_line(False, status["deep_status"], status["deep_status_reason"], meta)
        return status
    if paths["model"].stat().st_size < 1024 or paths["scaler"].stat().st_size < 128:
        status["deep_status"] = "artifacts_invalid"
        status["deep_status_reason"] = "placeholder-sized artifacts detected"
        status["deep_status_line"] = _status_line(False, status["deep_status"], status["deep_status_reason"], meta)
        return status
    if not bool(meta.get("artifacts_valid")):
        status["deep_status"] = "artifacts_invalid"
        status["deep_status_reason"] = "model_meta.json does not confirm valid artifacts"
        status["deep_status_line"] = _status_line(False, status["deep_status"], status["deep_status_reason"], meta)
        return status
    if str(meta.get("feature_schema_version", "")) != deep_dataset.FEATURE_SCHEMA_VERSION:
        status["deep_status"] = "artifacts_invalid"
        status["deep_status_reason"] = "feature schema version mismatch"
        status["deep_status_line"] = _status_line(False, status["deep_status"], status["deep_status_reason"], meta)
        return status
    if sequence_length is not None and int(meta.get("sequence_length", 0) or 0) != int(sequence_length):
        status["deep_status"] = "artifacts_invalid"
        status["deep_status_reason"] = "sequence length mismatch"
        status["deep_status_line"] = _status_line(False, status["deep_status"], status["deep_status_reason"], meta)
        return status
    if feature_names is not None and list(meta.get("feature_names") or []) != list(feature_names):
        status["deep_status"] = "artifacts_invalid"
        status["deep_status_reason"] = "feature name schema mismatch"
        status["deep_status_line"] = _status_line(False, status["deep_status"], status["deep_status_reason"], meta)
        return status
    try:
        model, scaler = load_artifacts(paths["model"], paths["scaler"])
    except Exception as exc:
        status["deep_status"] = "model_load_failed"
        status["deep_status_reason"] = f"artifact load failed: {exc}"
        status["deep_status_line"] = _status_line(False, status["deep_status"], status["deep_status_reason"], meta)
        return status
    if feature_names is not None and model.input_dim != len(feature_names):
        status["deep_status"] = "artifacts_invalid"
        status["deep_status_reason"] = "model input dimension does not match current features"
        status["deep_status_line"] = _status_line(False, status["deep_status"], status["deep_status_reason"], meta)
        return status
    status.update(
        {
            "deep_enabled": True,
            "deep_status": "trained_active",
            "deep_status_reason": "real trained model loaded successfully",
            "deep_status_line": _status_line(True, "trained_active", "active", meta),
            "_model": model,
            "_scaler": scaler,
            "_meta": meta,
        }
    )
    return status


def get_deep_status() -> dict[str, Any]:
    return _public_status_payload(_inspect_artifacts())


def train_from_csv(csv_path: str | Path | None = None, config_payload: dict[str, Any] | None = None, epochs_override: int | None = None) -> dict[str, Any]:
    config_payload = config_payload or cfg.load_config()
    draws = csv_loader.load_history("loto_5_35", csv_path=csv_path)
    training_config = _deep_config(config_payload)
    if epochs_override is not None:
        training_config["epochs"] = int(epochs_override)
    min_samples = int(training_config.get("min_samples_required_for_deep", 120) or 120)
    if len(draws) < min_samples:
        raise ValueError(f"Need at least {min_samples} draws before training the deep model.")
    dataset = deep_dataset.build_training_samples(draws, config_payload, sequence_length=int(training_config.get("sequence_length", 10) or 10))
    trained = train_numpy_cnn_gru(
        features=dataset["features"],
        targets_main=dataset["targets_main"],
        targets_extra=dataset["targets_extra"],
        targets_regime=dataset["targets_regime"],
        model_kwargs={},
        training_config=training_config,
    )
    paths = _model_paths()
    save_artifacts(trained["model"], trained["scaler"], paths["model"], paths["scaler"])
    meta = {
        "model_type": MODEL_TYPE,
        "game": "loto_5_35",
        "sequence_length": int(dataset["sequence_length"]),
        "feature_dim": int(dataset["features"].shape[-1]),
        "feature_schema_version": deep_dataset.FEATURE_SCHEMA_VERSION,
        "feature_names": list(dataset["feature_names"]),
        "train_samples": int(trained["train_samples"]),
        "val_samples": int(trained["val_samples"]),
        "trained_at": _now_iso(),
        "trained_on_latest_draw_id": str(draws[-1].get("ky", "")),
        "source_csv": str(csv_loader.resolve_csv_path(csv_path)),
        "version": MODEL_VERSION,
        "artifacts_valid": True,
        "deep_enabled": True,
        "metrics": {
            "main_loss": float(trained["metrics"]["train"]["main_loss"]),
            "val_main_loss": float(trained["metrics"]["validation"]["main_loss"]),
            "bonus_loss": float(trained["metrics"]["train"]["extra_loss"] or 0.0),
            "val_bonus_loss": float(trained["metrics"]["validation"]["extra_loss"] or 0.0),
            "regime_loss": float(trained["metrics"]["train"]["regime_loss"] or 0.0),
            "val_regime_loss": float(trained["metrics"]["validation"]["regime_loss"] or 0.0),
            "exact_hit_mean": float(trained["metrics"]["validation"]["exact_hit_mean"]),
            "topk_recall": float(trained["metrics"]["validation"]["topk_recall"]),
            "bonus_accuracy": float(trained["metrics"]["validation"]["extra_accuracy"] or 0.0),
            "regime_accuracy": float(trained["metrics"]["validation"]["regime_accuracy"] or 0.0),
        },
        "training_history_tail": list(trained["history"][-5:]),
        "best_epoch": int(trained["best_epoch"]),
    }
    _write_json(paths["meta"], meta)
    status = _inspect_artifacts(feature_names=list(dataset["feature_names"]), sequence_length=int(dataset["sequence_length"]))
    payload = _public_status_payload(status)
    payload["trained"] = True
    payload["metrics"] = dict(meta["metrics"])
    payload["train_samples"] = int(meta["train_samples"])
    payload["val_samples"] = int(meta["val_samples"])
    return payload


def score_candidates(
    main_numbers: list[int] | None = None,
    bonus_numbers: list[int] | None = None,
    draws: list[dict[str, Any]] | None = None,
    target: dict[str, Any] | None = None,
    tracking_state: dict[str, Any] | None = None,
    config_payload: dict[str, Any] | None = None,
):
    del target, tracking_state
    main_numbers = [int(number) for number in list(main_numbers or range(1, 36))]
    bonus_numbers = [int(number) for number in list(bonus_numbers or range(1, 13))]
    config_payload = config_payload or cfg.load_config()
    try:
        sample = deep_dataset.build_inference_sample(
            draws=list(draws or []),
            config_payload=config_payload,
            sequence_length=int((_deep_config(config_payload)).get("sequence_length", 10) or 10),
        )
    except Exception as exc:
        status = {
            "deep_enabled": False,
            "deep_status": "fallback_heuristic_only",
            "deep_status_reason": f"inference sample unavailable: {exc}",
            "deep_model_type": MODEL_TYPE,
            "deep_model_version": MODEL_VERSION,
            "deep_last_trained_at": "",
            "deep_artifacts": {
                "model_exists": _model_paths()["model"].exists(),
                "scaler_exists": _model_paths()["scaler"].exists(),
                "meta_exists": _model_paths()["meta"].exists(),
            },
            "deep_status_line": _status_line(False, "fallback_heuristic_only", f"inference sample unavailable: {exc}", {}),
        }
        return {
            "available": False,
            "mode": "heuristic_only",
            "modelType": MODEL_TYPE,
            "message": status["deep_status_line"],
            "mainScores": {int(number): 0.0 for number in main_numbers},
            "bonusScores": {int(number): 0.0 for number in bonus_numbers},
            "regimeHead": {"reset": 0.0, "neutral": 1.0, "continuation": 0.0},
            **_public_status_payload(status),
        }

    status = _inspect_artifacts(feature_names=list(sample["feature_names"]), sequence_length=int(sample["sequence_length"]))
    if not bool(status.get("deep_enabled")):
        return {
            "available": False,
            "mode": "heuristic_only",
            "modelType": MODEL_TYPE,
            "message": status["deep_status_line"],
            "mainScores": {int(number): 0.0 for number in main_numbers},
            "bonusScores": {int(number): 0.0 for number in bonus_numbers},
            "regimeHead": {"reset": 0.0, "neutral": 1.0, "continuation": 0.0},
            **_public_status_payload(status),
        }

    model = status["_model"]
    scaler = status["_scaler"]
    outputs = model.predict_proba(scaler.transform(sample["features"]))
    main_probabilities = outputs["main_probs"][0]
    bonus_probabilities = outputs.get("extra_probs")
    regime_probabilities = outputs.get("regime_probs")
    regime_head = {"reset": 0.0, "neutral": 1.0, "continuation": 0.0}
    if regime_probabilities is not None:
        regime_head = {
            "reset": float(regime_probabilities[0][0]),
            "neutral": float(regime_probabilities[0][1]),
            "continuation": float(regime_probabilities[0][2]),
        }
    return {
        "available": True,
        "mode": "trained_active",
        "modelType": MODEL_TYPE,
        "message": status["deep_status_line"],
        "mainScores": {int(number): float(main_probabilities[int(number) - 1]) for number in main_numbers},
        "bonusScores": {
            int(number): float(bonus_probabilities[0][int(number) - 1]) if bonus_probabilities is not None else 0.0
            for number in bonus_numbers
        },
        "regimeHead": regime_head,
        **_public_status_payload(status),
    }


def incremental_fine_tune(resolved_prediction=None, actual_draw=None, draws=None, config_payload=None, csv_path=None):
    del resolved_prediction, actual_draw
    config_payload = config_payload or cfg.load_config()
    deep_cfg = _deep_config(config_payload)
    if not bool(deep_cfg.get("fine_tune_enabled", True)):
        return {"updated": False, "mode": "heuristic_only", "message": "Deep fine-tune is disabled in config."}
    if not draws:
        return {"updated": False, "mode": "heuristic_only", "message": "Deep fine-tune skipped because updated history was not provided."}

    status = _inspect_artifacts()
    latest_draw_id = str((draws[-1] or {}).get("ky", ""))
    trained_draw_id = str(((status.get("_meta") or {}).get("trained_on_latest_draw_id") or ""))
    retrain_every = int(deep_cfg.get("retrain_every_n_draws", 6) or 6)
    if status.get("deep_enabled"):
        try:
            latest_int = int("".join(ch for ch in latest_draw_id if ch.isdigit()) or "0")
            trained_int = int("".join(ch for ch in trained_draw_id if ch.isdigit()) or "0")
            if latest_int - trained_int < retrain_every:
                return {
                    "updated": False,
                    "mode": "trained_active",
                    "message": f"Deep model stays active; only {latest_int - trained_int} new draws since last train.",
                }
        except Exception:
            pass
    try:
        retrain_result = train_from_csv(csv_path=csv_path, config_payload=config_payload, epochs_override=int(deep_cfg.get("fine_tune_epochs", 6) or 6))
    except Exception as exc:
        return {"updated": False, "mode": "heuristic_only", "message": f"Deep retrain failed after actual update: {exc}"}
    return {"updated": True, "mode": "trained_active", "message": retrain_result.get("deep_status_line", "Deep retrain completed.")}
