from __future__ import annotations

import sys
import json
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from statistics import mean

from src import config as cfg, csv_loader, heuristic_engine, tracking_engine

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai.evaluation.metrics import brier_score, calibration_error, log_loss  # noqa: E402
from ai.evaluation.probability import scores_to_probabilities  # noqa: E402


ABLATION_MODES = ("heuristic_only", "deep_only", "blended")


def _atomic_write_json(path, payload):
    if not path:
        return ""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_path, output_path)
    return str(output_path)


def run_quick_backtest(draws, config_payload, blend_mode=None):
    sample_count = min(
        max(6, int(((config_payload.get("history_limits") or {}).get("backtest_samples") or 18))),
        max(0, len(draws) - 12),
    )
    if sample_count <= 0:
        return {
            "blend_mode": blend_mode or str(config_payload.get("blend_mode_default", "blended")),
            "samples": 0,
            "avgHits": 0.0,
            "avgHitRate": 0.0,
            "bonusAccuracy": 0.0,
            "note": "Chưa đủ dữ liệu để chạy backtest Loto 5/35 standalone.",
        }

    hits = []
    bonus_hits = []
    for offset in range(sample_count, 0, -1):
        history = list(draws[:-offset])
        actual = draws[-offset]
        if len(history) < 24:
            continue
        tracking_state = deepcopy(cfg.DEFAULT_TRACKING_STATE)
        latest = history[-1]
        target = {
            "target_draw_id": str(int(actual.get("ky_int", 0) or 0)),
            "target_slot": str(actual.get("slot", "")),
            "target_date": str(actual.get("date", "")),
            "target_date_obj": actual.get("date_obj"),
            "target_weekday": actual.get("weekday"),
            "same_day_follow_up": bool(latest.get("date") == actual.get("date") and latest.get("slot") != actual.get("slot")),
            "latest_actual_draw": latest,
            "previous_draw": history[-2] if len(history) > 1 else None,
        }
        analysis = heuristic_engine.build_prediction_snapshot(
            history,
            target,
            tracking_state,
            deepcopy(config_payload),
            bundle_count=3,
            blend_mode=blend_mode,
        )
        selection = heuristic_engine.select_vip_tickets(analysis, config_payload)
        primary = selection.get("primary") or {}
        predicted_main = set(int(value) for value in list(primary.get("main") or []))
        actual_main = set(int(value) for value in list(actual.get("main") or []))
        hits.append(len(predicted_main.intersection(actual_main)))
        bonus_hits.append(int(primary.get("special") == actual.get("special")))

    if not hits:
        return {
            "blend_mode": blend_mode or str(config_payload.get("blend_mode_default", "blended")),
            "samples": 0,
            "avgHits": 0.0,
            "avgHitRate": 0.0,
            "bonusAccuracy": 0.0,
            "note": "Không tạo được cửa sổ backtest hợp lệ cho predictor standalone Loto 5/35.",
        }

    average_hits = sum(hits) / float(len(hits))
    return {
        "blend_mode": blend_mode or str(config_payload.get("blend_mode_default", "blended")),
        "samples": len(hits),
        "avgHits": round(average_hits, 4),
        "avgHitRate": round(average_hits / 5.0, 6),
        "bonusAccuracy": round(sum(bonus_hits) / float(len(bonus_hits)), 6),
        "note": "Backtest nhanh predictor standalone Loto 5/35 trên các kỳ gần nhất với lớp heuristic + tracking.",
    }


def _evaluate_mode(draws, config_payload, blend_mode, min_history=24, mode="fast", window="expanding", rolling_window=None):
    if len(draws) <= 24:
        raise ValueError("Not enough draws to run a chronological backtest.")

    tracking_state = deepcopy(cfg.DEFAULT_TRACKING_STATE)
    hits = []
    recalls = []
    bonus_hits = []
    quality_scores = []
    probability_rows = []
    label_rows = []
    folds = []

    min_history = max(24, int(min_history or 24))
    indexes = list(range(min_history, len(draws)))
    if str(mode or "fast").lower() == "fast":
        indexes = indexes[-24:]

    for fold_number, index in enumerate(indexes, start=1):
        if str(window or "expanding").lower() == "rolling":
            scoped_window = max(min_history, int(rolling_window or min_history))
            history = list(draws[max(0, index - scoped_window):index])
        else:
            history = list(draws[:index])
        actual = draws[index]
        latest = history[-1]
        target = {
            "target_draw_id": str(int(actual.get("ky_int", 0) or 0)),
            "target_slot": str(actual.get("slot", "")),
            "target_date": str(actual.get("date", "")),
            "target_date_obj": actual.get("date_obj"),
            "target_weekday": actual.get("weekday"),
            "same_day_follow_up": bool(latest.get("date") == actual.get("date") and latest.get("slot") != actual.get("slot")),
            "latest_actual_draw": latest,
            "previous_draw": history[-2] if len(history) > 1 else None,
        }
        analysis = heuristic_engine.build_prediction_snapshot(
            history,
            target,
            deepcopy(tracking_state),
            deepcopy(config_payload),
            bundle_count=3,
            blend_mode=blend_mode,
        )
        selection = heuristic_engine.select_vip_tickets(analysis, config_payload)
        primary = selection.get("primary") or {}
        predicted_main = set(int(value) for value in list(primary.get("main") or []))
        actual_main = set(int(value) for value in list(actual.get("main") or []))
        top_main = list(analysis.get("topMain") or [])[:10]

        hits.append(len(predicted_main.intersection(actual_main)))
        recalls.append(len(set(top_main).intersection(actual_main)) / 5.0)
        bonus_hits.append(int(primary.get("special") == actual.get("special")))
        quality_scores.append(float(primary.get("qualityScore", 0.0)))
        calibrated = scores_to_probabilities(dict(analysis.get("mainFinalScores") or {}), 5, 1, 35)
        probability_rows.append(calibrated)
        label_rows.append(list(actual.get("main") or []))
        folds.append({
            "fold": fold_number,
            "target_draw_id": str(target.get("target_draw_id", "")),
            "data_cutoff_draw_id": str(history[-1].get("ky", "")),
            "train_size": len(history),
            "window": str(window or "expanding"),
            "main_ticket": list(primary.get("main") or []),
            "bonus": primary.get("special"),
            "actual_main": list(actual.get("main") or []),
            "actual_special": actual.get("special"),
            "hit_count": len(predicted_main.intersection(actual_main)),
            "bonus_hit": int(primary.get("special") == actual.get("special")),
            "top_k_recall": len(set(top_main).intersection(actual_main)) / 5.0,
            "quality_score": float(primary.get("qualityScore", 0.0)),
            "deep_status": str((analysis.get("deep") or {}).get("deep_status", "")),
            "deep_status_reason": str((analysis.get("deep") or {}).get("deep_status_reason", "")),
            "calibrated_probability": calibrated,
        })

        tracking_state = tracking_engine.update_after_actual(
            deepcopy(tracking_state),
            {
                "main_ticket": list(primary.get("main") or []),
                "bonus": primary.get("special"),
                "target_draw_id": str(target.get("target_draw_id", "")),
                "target_slot": str(target.get("target_slot", "")),
            },
            actual,
            deepcopy(config_payload),
        )

    avg_hits = mean(hits) if hits else 0.0
    return {
        "blend_mode": blend_mode,
        "draws_tested": len(hits),
        "fold_count": len(folds),
        "average_hits": avg_hits,
        "avgHits": avg_hits,
        "avgHitRate": avg_hits / 5.0 if hits else 0.0,
        "top_k_recall": mean(recalls) if recalls else 0.0,
        "bonus_or_special_accuracy": mean(bonus_hits) if bonus_hits else 0.0,
        "ticket_quality_mean": mean(quality_scores) if quality_scores else 0.0,
        "brier_score": brier_score(probability_rows, label_rows, 35) if probability_rows else 0.0,
        "log_loss": log_loss(probability_rows, label_rows, 35) if probability_rows else 0.0,
        "calibration_error": calibration_error(probability_rows, label_rows, 35) if probability_rows else 0.0,
        "folds": folds,
    }


def _winner_key(summary):
    return (
        float(summary.get("average_hits", 0.0)),
        float(summary.get("top_k_recall", 0.0)),
        float(summary.get("bonus_or_special_accuracy", 0.0)),
        float(summary.get("ticket_quality_mean", 0.0)),
    )


def run_ablation_report(csv_path=None, min_history=24, mode="fast", window="expanding", rolling_window=None):
    config_payload = cfg.load_config()
    draws = csv_loader.load_history("loto_5_35", csv_path=csv_path)
    mode_reports = {
        blend_mode: _evaluate_mode(
            draws,
            config_payload,
            blend_mode,
            min_history=min_history,
            mode=mode,
            window=window,
            rolling_window=rolling_window,
        )
        for blend_mode in ABLATION_MODES
    }
    winner_mode = max(mode_reports, key=lambda mode: _winner_key(mode_reports[mode]))
    return {
        "game": "loto_5_35",
        "predictorVersion": cfg.PREDICTOR_VERSION,
        "dataset": csv_loader.build_sync_summary_for_path(draws, csv_path),
        "modes": mode_reports,
        "winner_mode": winner_mode,
        "winner_summary": mode_reports[winner_mode],
        "metric_priority": ["average_hits", "top_k_recall", "bonus_or_special_accuracy", "ticket_quality_mean"],
        "backtest_mode": str(mode or "fast"),
        "window": str(window or "expanding"),
        "rolling_window": rolling_window,
        "metrics": dict(mode_reports.get("blended") or {}),
    }


def run_backtest(
    csv_path=None,
    min_history=24,
    mode="fast",
    window="expanding",
    rolling_window=None,
    retrain_interval=None,
    output_path=None,
    persist_metrics=False,
):
    config_payload = cfg.load_config()
    draws = csv_loader.load_history("loto_5_35", csv_path=csv_path)
    quick_summary = run_quick_backtest(draws, config_payload, blend_mode=str(config_payload.get("blend_mode_default", "blended")))
    ablation_report = run_ablation_report(
        csv_path=csv_path,
        min_history=min_history,
        mode=mode,
        window=window,
        rolling_window=rolling_window,
    )
    winner_summary = dict(ablation_report["winner_summary"])
    fold_predictions = list(winner_summary.get("folds") or [])
    result = {
        "ok": True,
        "game": "loto_5_35",
        "predictorVersion": cfg.PREDICTOR_VERSION,
        "dataset": csv_loader.build_sync_summary_for_path(draws, csv_path),
        "quick_summary": quick_summary,
        "ablation_report": ablation_report,
        "winner_mode": ablation_report["winner_mode"],
        "winner_summary": winner_summary,
        "metrics": dict(ablation_report.get("metrics") or winner_summary),
        "fold_predictions": fold_predictions,
        "backtest_mode": str(mode or "fast"),
        "window": str(window or "expanding"),
        "rolling_window": rolling_window,
        "retrain_interval": int(retrain_interval or 1),
        "leakage_guard": {
            "history_rule": "each fold uses draws before target_draw_id only",
            "deep_policy": "latest artifacts are rejected for a fold when trained_on_latest_draw_id >= target_draw_id",
            "tracking_policy": "tracking state is simulated sequentially after each target is scored",
        },
    }
    if output_path:
        result["fold_predictions_path"] = _atomic_write_json(output_path, result)
    if persist_metrics:
        metrics = cfg.load_metrics()
        metrics["last_backtest_run"] = {
            **quick_summary,
            "game": "loto_5_35",
            "predictorVersion": cfg.PREDICTOR_VERSION,
            "winner_mode": ablation_report["winner_mode"],
            "run_at": datetime.now().isoformat(timespec="seconds"),
        }
        metrics["last_ablation_report"] = {
            "game": "loto_5_35",
            "predictorVersion": cfg.PREDICTOR_VERSION,
            **ablation_report,
            "run_at": datetime.now().isoformat(timespec="seconds"),
        }
        cfg.save_metrics(metrics)
    return result
