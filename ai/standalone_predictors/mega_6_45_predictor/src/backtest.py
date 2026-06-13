from __future__ import annotations

import sys
import json
import os
from copy import deepcopy
from pathlib import Path
from statistics import mean
from typing import Any

from src import PROJECT_ROOT, data_loader, predictor_api, tracking_engine

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai.evaluation.metrics import brier_score, calibration_error, log_loss  # noqa: E402
from ai.evaluation.probability import scores_to_probabilities  # noqa: E402


ABLATION_MODES = ("heuristic_only", "deep_only", "blended")


def _atomic_write_json(path: str | Path | None, payload: dict[str, Any]) -> str:
    if not path:
        return ""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_path, output_path)
    return str(output_path)


def _evaluate_mode(
    draws: list[Any],
    predictor_config: dict[str, Any],
    feature_flags: dict[str, Any],
    project_root,
    blend_mode: str,
    backup_count: int,
    min_history: int,
    mode: str = "fast",
    window: str = "expanding",
    rolling_window: int | None = None,
) -> dict[str, Any]:
    if len(draws) <= min_history:
        raise ValueError("Not enough draws to run a chronological backtest.")

    tracking_state = tracking_engine.clone_default_state()
    exact_hits_per_draw: list[int] = []
    top_k_recalls: list[float] = []
    quality_scores: list[float] = []
    probability_rows: list[dict[int, float]] = []
    label_rows: list[list[int]] = []
    folds: list[dict[str, Any]] = []

    indexes = list(range(min_history, len(draws)))
    if str(mode or "fast").lower() == "fast":
        indexes = indexes[-24:]

    for fold_number, index in enumerate(indexes, start=1):
        if str(window or "expanding").lower() == "rolling":
            scoped_window = max(min_history, int(rolling_window or min_history))
            history = draws[max(0, index - scoped_window):index]
        else:
            history = draws[:index]
        actual = draws[index]
        target_info = data_loader.infer_next_draw(history, predictor_config.get("schedule_weekdays") or [2, 4, 6])
        target_info["target_draw_id"] = int(actual.draw_id)
        feature_flags_fold = deepcopy(feature_flags)
        feature_flags_fold["backtest_target_draw_id"] = int(actual.draw_id)
        prediction = predictor_api.build_prediction_from_history(
            draws=history,
            tracking_state=deepcopy(tracking_state),
            predictor_config=predictor_config,
            feature_flags=feature_flags_fold,
            target_info=deepcopy(target_info),
            project_root=project_root,
            backup_count=backup_count,
            blend_mode=blend_mode,
        )
        actual_set = set(actual.main_numbers)
        main_ticket_set = set(prediction["main_ticket"])
        exact_hits = len(main_ticket_set & actual_set)
        top_candidates = set(prediction["top_main_candidates"][:12])

        exact_hits_per_draw.append(exact_hits)
        top_k_recalls.append(len(top_candidates & actual_set) / 6.0)
        quality_scores.append(float(prediction["quality_score"]))
        final_scores = dict((prediction.get("scoring_context") or {}).get("final_scores") or {})
        calibrated = scores_to_probabilities(final_scores, 6, 1, 45) if final_scores else {}
        if calibrated:
            probability_rows.append(calibrated)
            label_rows.append(list(actual.main_numbers))
        folds.append({
            "fold": fold_number,
            "target_draw_id": int(actual.draw_id),
            "data_cutoff_draw_id": int(history[-1].draw_id),
            "train_size": len(history),
            "window": str(window or "expanding"),
            "main_ticket": list(prediction["main_ticket"]),
            "actual_main": list(actual.main_numbers),
            "hit_count": exact_hits,
            "top_k_recall": len(top_candidates & actual_set) / 6.0,
            "quality_score": float(prediction["quality_score"]),
            "deep_status": str(prediction.get("deep_status", "")),
            "deep_status_reason": str(prediction.get("deep_status_reason", "")),
            "calibrated_probability": calibrated,
        })

        update = tracking_engine.update_after_actual(
            state=tracking_state,
            prediction_payload={
                "main_ticket": prediction["main_ticket"],
                "target_draw_id": prediction["target_draw_id"],
            },
            actual_numbers=list(actual.main_numbers),
            tracking_config=dict(predictor_config.get("tracking") or {}),
            draw_id=actual.draw_id,
        )
        tracking_state = update["next_state"]

    brier = brier_score(probability_rows, label_rows, 45) if probability_rows else 0.0
    ll = log_loss(probability_rows, label_rows, 45) if probability_rows else 0.0
    cal = calibration_error(probability_rows, label_rows, 45) if probability_rows else 0.0
    avg_hits = mean(exact_hits_per_draw) if exact_hits_per_draw else 0.0
    return {
        "blend_mode": blend_mode,
        "draws_tested": len(exact_hits_per_draw),
        "fold_count": len(folds),
        "average_hits": avg_hits,
        "avgHits": avg_hits,
        "avgHitRate": avg_hits / 6.0 if exact_hits_per_draw else 0.0,
        "top_k_recall": mean(top_k_recalls) if top_k_recalls else 0.0,
        "ticket_quality_mean": mean(quality_scores) if quality_scores else 0.0,
        "bonus_or_special_accuracy": None,
        "brier_score": brier,
        "log_loss": ll,
        "calibration_error": cal,
        "folds": folds,
    }


def _winner_key(summary: dict[str, Any]) -> tuple[float, float, float]:
    return (
        float(summary.get("average_hits", 0.0)),
        float(summary.get("top_k_recall", 0.0)),
        float(summary.get("ticket_quality_mean", 0.0)),
    )


def run_ablation_report(
    csv_path: str,
    project_root=PROJECT_ROOT,
    min_history: int = 60,
    modes: tuple[str, ...] = ABLATION_MODES,
    mode: str = "fast",
    window: str = "expanding",
    rolling_window: int | None = None,
) -> dict[str, Any]:
    runtime_config = predictor_api.load_runtime_configuration(project_root)
    predictor_config = dict(runtime_config["predictor_config"])
    feature_flags = dict(runtime_config["feature_flags"])
    bundle = data_loader.load_draw_records(csv_path, column_mapping_path=project_root / "config" / "column_mapping.json")
    draws = list(bundle["records"])
    backup_count = int(predictor_config.get("backup_ticket_count", 3))

    backtest_mode = str(mode or "fast")
    mode_reports = {
        blend_mode: _evaluate_mode(
            draws=draws,
            predictor_config=predictor_config,
            feature_flags=feature_flags,
            project_root=project_root,
            blend_mode=blend_mode,
            backup_count=backup_count,
            min_history=min_history,
            mode=backtest_mode,
            window=window,
            rolling_window=rolling_window,
        )
        for blend_mode in modes
    }
    winner_mode = max(mode_reports, key=lambda mode: _winner_key(mode_reports[mode]))
    return {
        "game": "mega_6_45",
        "dataset": data_loader.build_dataset_summary(bundle),
        "modes": mode_reports,
        "winner_mode": winner_mode,
        "winner_summary": mode_reports[winner_mode],
        "metric_priority": ["average_hits", "top_k_recall", "ticket_quality_mean"],
        "backtest_mode": backtest_mode,
        "window": str(window or "expanding"),
        "rolling_window": rolling_window,
        "metrics": dict(mode_reports.get("blended") or {}),
    }


def run_backtest(
    csv_path: str,
    project_root=PROJECT_ROOT,
    min_history: int = 60,
    mode: str = "fast",
    window: str = "expanding",
    rolling_window: int | None = None,
    retrain_interval: int | None = None,
    output_path: str | Path | None = None,
    persist_metrics: bool = False,
) -> dict[str, Any]:
    ablation_report = run_ablation_report(
        csv_path,
        project_root=project_root,
        min_history=min_history,
        mode=mode,
        window=window,
        rolling_window=rolling_window,
    )
    result = dict(ablation_report)
    winner_summary = dict(result.get("winner_summary") or {})
    result["ok"] = True
    result["fold_predictions"] = list(winner_summary.get("folds") or [])
    result["retrain_interval"] = int(retrain_interval or 1)
    result["leakage_guard"] = {
        "history_rule": "each fold uses draws before target_draw_id only",
        "deep_policy": "latest artifacts are rejected for a fold when trained_on_latest_draw_id >= target_draw_id",
        "tracking_policy": "tracking state is simulated sequentially after each target is scored",
    }
    if output_path:
        result["fold_predictions_path"] = _atomic_write_json(output_path, result)
    if persist_metrics:
        runtime_state = predictor_api.load_runtime_state(project_root)
        metrics = dict(runtime_state["metrics"])
        metrics["last_backtest_run"] = {
            "run_at": tracking_engine.now_iso(),
            **dict(ablation_report["modes"]["blended"]),
            "winner_mode": ablation_report["winner_mode"],
        }
        metrics["last_ablation_report"] = {
            "run_at": tracking_engine.now_iso(),
            **ablation_report,
        }
        predictor_api.save_runtime_state(runtime_state["tracking_state"], runtime_state["last_prediction"], metrics, project_root)
    return result
