from __future__ import annotations

from copy import deepcopy
from statistics import mean
from typing import Any

from src import PROJECT_ROOT, data_loader, predictor_api, tracking_engine


ABLATION_MODES = ("heuristic_only", "deep_only", "blended")


def _evaluate_mode(
    draws: list[Any],
    predictor_config: dict[str, Any],
    feature_flags: dict[str, Any],
    project_root,
    blend_mode: str,
    backup_count: int,
    min_history: int,
) -> dict[str, Any]:
    if len(draws) <= min_history:
        raise ValueError("Not enough draws to run a chronological backtest.")

    tracking_state = tracking_engine.clone_default_state()
    exact_hits_per_draw: list[int] = []
    top_k_recalls: list[float] = []
    quality_scores: list[float] = []

    for index in range(min_history, len(draws)):
        history = draws[:index]
        actual = draws[index]
        target_info = data_loader.infer_next_draw(history, predictor_config.get("schedule_weekdays") or [2, 4, 6])
        prediction = predictor_api.build_prediction_from_history(
            draws=history,
            tracking_state=deepcopy(tracking_state),
            predictor_config=predictor_config,
            feature_flags=feature_flags,
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

    return {
        "blend_mode": blend_mode,
        "draws_tested": len(exact_hits_per_draw),
        "average_hits": mean(exact_hits_per_draw) if exact_hits_per_draw else 0.0,
        "top_k_recall": mean(top_k_recalls) if top_k_recalls else 0.0,
        "ticket_quality_mean": mean(quality_scores) if quality_scores else 0.0,
        "bonus_or_special_accuracy": None,
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
) -> dict[str, Any]:
    runtime_config = predictor_api.load_runtime_configuration(project_root)
    predictor_config = dict(runtime_config["predictor_config"])
    feature_flags = dict(runtime_config["feature_flags"])
    bundle = data_loader.load_draw_records(csv_path, column_mapping_path=project_root / "config" / "column_mapping.json")
    draws = list(bundle["records"])
    backup_count = int(predictor_config.get("backup_ticket_count", 3))

    mode_reports = {
        mode: _evaluate_mode(
            draws=draws,
            predictor_config=predictor_config,
            feature_flags=feature_flags,
            project_root=project_root,
            blend_mode=mode,
            backup_count=backup_count,
            min_history=min_history,
        )
        for mode in modes
    }
    winner_mode = max(mode_reports, key=lambda mode: _winner_key(mode_reports[mode]))
    return {
        "game": "mega_6_45",
        "dataset": data_loader.build_dataset_summary(bundle),
        "modes": mode_reports,
        "winner_mode": winner_mode,
        "winner_summary": mode_reports[winner_mode],
        "metric_priority": ["average_hits", "top_k_recall", "ticket_quality_mean"],
    }


def run_backtest(csv_path: str, project_root=PROJECT_ROOT, min_history: int = 60) -> dict[str, Any]:
    ablation_report = run_ablation_report(csv_path, project_root=project_root, min_history=min_history)
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
    return ablation_report
