from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from src import PROJECT_ROOT, data_loader, deep_model, heuristic_engine, modulo_engine, online_learning, pair_engine, regime_engine, ticket_generator, tracking_engine


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return deepcopy(default)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_runtime_configuration(project_root: Path | None = None) -> dict[str, Any]:
    project_root = project_root or PROJECT_ROOT
    return {
        "predictor_config": _read_json(project_root / "config" / "predictor_config.json", {}),
        "column_mapping": _read_json(project_root / "config" / "column_mapping.json", {}),
        "feature_flags": _read_json(project_root / "config" / "feature_flags.json", {}),
    }


def load_runtime_state(project_root: Path | None = None) -> dict[str, Any]:
    project_root = project_root or PROJECT_ROOT
    return {
        "tracking_state": tracking_engine.load_tracking_state(project_root / "state" / "tracking_state.json"),
        "last_prediction": _read_json(project_root / "state" / "last_prediction.json", {}),
        "metrics": _read_json(project_root / "state" / "metrics.json", {}),
    }


def save_runtime_state(
    tracking_state: dict[str, Any],
    last_prediction: dict[str, Any],
    metrics: dict[str, Any],
    project_root: Path | None = None,
) -> None:
    project_root = project_root or PROJECT_ROOT
    tracking_engine.save_tracking_state(project_root / "state" / "tracking_state.json", tracking_state)
    _write_json(project_root / "state" / "last_prediction.json", last_prediction)
    _write_json(project_root / "state" / "metrics.json", metrics)


def _build_special_notes(selected_special: int | None, scoring_context: dict[str, Any], tracking_state: dict[str, Any]) -> list[str]:
    notes = []
    prioritized_special = set(tracking_state.get("prioritized_special") or [])
    hot_special_values = set((scoring_context.get("prediction_context") or {}).get("hot_special_values") or [])
    if selected_special is not None and selected_special in prioritized_special:
        notes.append(f"Special {selected_special} is still supported by tracking memory.")
    if selected_special is not None and selected_special in hot_special_values:
        notes.append(f"Special {selected_special} remains active in the recent special window.")
    downgraded = list(scoring_context.get("special_downgraded_due_to_misses") or [])
    if downgraded:
        notes.append(f"Special candidates cooled by misses: {downgraded}.")
    return notes


def build_prediction_from_history(
    draws: list[Any],
    tracking_state: dict[str, Any],
    predictor_config: dict[str, Any],
    feature_flags: dict[str, Any],
    target_info: dict[str, Any],
    project_root: Path | None = None,
    backup_count: int | None = None,
    blend_mode: str | None = None,
) -> dict[str, Any]:
    project_root = project_root or PROJECT_ROOT
    scoring_context = heuristic_engine.build_scoring_context(
        draws=draws,
        tracking_state=tracking_state,
        predictor_config=predictor_config,
        feature_flags=feature_flags,
        target_weekday=int(target_info["target_weekday"]),
        time_slot_enabled=bool(target_info.get("time_slot_enabled")),
        project_root=project_root,
        target_time=target_info.get("target_time"),
        blend_mode=blend_mode,
    )
    ticket_selection = ticket_generator.generate_tickets(
        scoring_context=scoring_context,
        tracking_state=tracking_state,
        predictor_config=predictor_config,
        backup_count=backup_count,
    )
    main_ticket_payload = dict(ticket_selection["main_ticket"])
    backup_tickets_payload = list(ticket_selection["backup_tickets"])
    main_ticket = list(main_ticket_payload["ticket"])
    selected_special = main_ticket_payload.get("special")
    explanation = {
        "kept_from_previous_success": [number for number in main_ticket if number in set(tracking_state.get("kept_numbers") or [])],
        "downgraded_due_to_misses": list(scoring_context.get("downgraded_due_to_misses") or []),
        "modulo_notes": modulo_engine.summarize_modulo_notes(
            scoring_context["prediction_context"]["modulo_context"],
            selected_ticket=main_ticket,
            selected_special=selected_special,
        ),
        "pair_notes": pair_engine.summarize_pair_notes(scoring_context["pair_context"], selected_ticket=main_ticket),
        "regime_notes": regime_engine.summarize_regime_notes(scoring_context["regime_context"]),
        "special_notes": _build_special_notes(selected_special, scoring_context, tracking_state),
        "deep_status_line": str((scoring_context.get("deep_result") or {}).get("deep_status_line", "")),
        "why_selected": list(ticket_selection.get("why_selected") or []),
    }
    disagreement_analysis = dict(ticket_selection.get("disagreement_analysis") or scoring_context.get("disagreement_analysis") or {})
    return {
        "game": "power_6_55",
        "target_draw_id": int(target_info["target_draw_id"]),
        "target_date_estimate": str(target_info["target_date_estimate"]),
        "regime": str(scoring_context["regime_context"]["regime"]),
        "tracking_state": {
            "kept_numbers": list(tracking_state.get("kept_numbers") or []),
            "true_hot_numbers": list(tracking_state.get("true_hot_numbers") or []),
            "temporary_excluded_numbers": list(tracking_state.get("temporary_excluded_numbers") or []),
            "prioritized_special": list(tracking_state.get("prioritized_special") or []),
        },
        "top_main_candidates": list(ticket_selection["top_main_candidates"]),
        "top_special_candidates": list(ticket_selection["top_special_candidates"]),
        "top_heuristic_candidates": list(ticket_selection.get("top_heuristic_candidates") or []),
        "top_deep_candidates": list(ticket_selection.get("top_deep_candidates") or []),
        "top_heuristic_special_candidates": list(ticket_selection.get("top_heuristic_special_candidates") or []),
        "top_deep_special_candidates": list(ticket_selection.get("top_deep_special_candidates") or []),
        "main_ticket": main_ticket,
        "backup_tickets": [list(ticket["ticket"]) for ticket in backup_tickets_payload],
        "special": selected_special,
        "special_backups": list(ticket_selection.get("special_backups") or []),
        "quality_score": float(main_ticket_payload["quality_score"]),
        "qualityScore": float(main_ticket_payload["quality_score"]),
        "blend_mode_used": str(scoring_context.get("blend_mode_used", "blended")),
        "blend_weights_used": dict(scoring_context.get("blend_weights_used") or {}),
        "assembly_mode": str(ticket_selection.get("assembly_mode", "blended")),
        "assembly_variants": list(ticket_selection.get("assembly_variants") or []),
        "disagreement_score": float(disagreement_analysis.get("score", 0.0) or 0.0),
        "disagreement_level": str(disagreement_analysis.get("level", "low") or "low"),
        "disagreement_analysis": disagreement_analysis,
        "why_selected": list(ticket_selection.get("why_selected") or []),
        "deep_enabled": bool((scoring_context.get("deep_result") or {}).get("deep_enabled")),
        "deep_status": str((scoring_context.get("deep_result") or {}).get("deep_status", "")),
        "deep_status_reason": str((scoring_context.get("deep_result") or {}).get("deep_status_reason", "")),
        "deep_status_line": str((scoring_context.get("deep_result") or {}).get("deep_status_line", "")),
        "deep_model_type": str((scoring_context.get("deep_result") or {}).get("deep_model_type", "")),
        "deep_model_version": str((scoring_context.get("deep_result") or {}).get("deep_model_version", "")),
        "deep_last_trained_at": str((scoring_context.get("deep_result") or {}).get("deep_last_trained_at", "")),
        "deep_artifacts": dict((scoring_context.get("deep_result") or {}).get("deep_artifacts") or {}),
        "explanation": explanation,
        "scoring_context": scoring_context,
        "ticket_selection": ticket_selection,
    }


def _build_last_prediction_payload(prediction_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "resolved": False,
        "target_draw_id": prediction_result["target_draw_id"],
        "target_date_estimate": prediction_result["target_date_estimate"],
        "created_at": tracking_engine.now_iso(),
        "main_ticket": list(prediction_result["main_ticket"]),
        "backup_tickets": [list(ticket) for ticket in prediction_result["backup_tickets"]],
        "top_main_candidates": list(prediction_result["top_main_candidates"]),
        "top_special_candidates": list(prediction_result["top_special_candidates"]),
        "special": prediction_result["special"],
        "special_backups": list(prediction_result["special_backups"]),
        "quality_score": float(prediction_result["quality_score"]),
        "regime": str(prediction_result["regime"]),
        "blend_mode_used": prediction_result.get("blend_mode_used"),
        "explanation": dict(prediction_result["explanation"]),
    }


def _public_prediction_payload(prediction_result: dict[str, Any]) -> dict[str, Any]:
    hidden_keys = {"scoring_context", "ticket_selection"}
    return {key: value for key, value in prediction_result.items() if key not in hidden_keys}


def get_blend_status(project_root: Path | None = None) -> dict[str, Any]:
    project_root = project_root or PROJECT_ROOT
    runtime_config = load_runtime_configuration(project_root)
    runtime_state = load_runtime_state(project_root)
    predictor_config = dict(runtime_config["predictor_config"])
    return {
        "game": "power_6_55",
        "blend_mode_default": str(predictor_config.get("blend_mode_default", "blended")),
        "blend_profiles": dict(predictor_config.get("blend_profiles") or {}),
        "assembly": dict(predictor_config.get("assembly") or {}),
        "deep_status": deep_model.get_deep_status(project_root=project_root),
        "last_ablation_report": dict((runtime_state.get("metrics") or {}).get("last_ablation_report") or {}),
    }


def audit_assembly(csv_path: str | Path, project_root: Path | None = None, backup_count: int | None = None) -> dict[str, Any]:
    prediction = predict(csv_path, project_root=project_root, backup_count=backup_count)
    return {
        "game": "power_6_55",
        "blend_mode_used": prediction.get("blend_mode_used"),
        "blend_weights_used": prediction.get("blend_weights_used"),
        "deep_enabled": prediction.get("deep_enabled"),
        "deep_status": prediction.get("deep_status"),
        "disagreement_score": prediction.get("disagreement_score"),
        "disagreement_level": prediction.get("disagreement_level"),
        "assembly_mode": prediction.get("assembly_mode"),
        "top_heuristic_candidates": prediction.get("top_heuristic_candidates"),
        "top_deep_candidates": prediction.get("top_deep_candidates"),
        "top_heuristic_special_candidates": prediction.get("top_heuristic_special_candidates"),
        "top_deep_special_candidates": prediction.get("top_deep_special_candidates"),
        "main_ticket": prediction.get("main_ticket"),
        "special": prediction.get("special"),
        "backup_tickets": prediction.get("backup_tickets"),
        "why_selected": prediction.get("why_selected"),
        "assembly_variants": prediction.get("assembly_variants"),
    }


def predict(csv_path: str | Path, project_root: Path | None = None, backup_count: int | None = None, blend_mode: str | None = None) -> dict[str, Any]:
    project_root = project_root or PROJECT_ROOT
    runtime_config = load_runtime_configuration(project_root)
    runtime_state = load_runtime_state(project_root)
    predictor_config = dict(runtime_config["predictor_config"])
    feature_flags = dict(runtime_config["feature_flags"])
    bundle = data_loader.load_draw_records(csv_path, column_mapping_path=project_root / "config" / "column_mapping.json")
    draws = list(bundle["records"])
    time_slot_enabled = bool(feature_flags.get("use_time_slot_auto", True)) and bool(bundle.get("time_slot_usable"))

    sync_result = online_learning.sync_pending_prediction(
        draws=draws,
        tracking_state=runtime_state["tracking_state"],
        last_prediction=runtime_state["last_prediction"],
        predictor_config=predictor_config,
        feature_flags=feature_flags,
        project_root=project_root,
        csv_path=csv_path,
    )
    tracking_state = sync_result["tracking_state"]

    target_info = data_loader.infer_next_draw(
        draws,
        predictor_config.get("schedule_weekdays") or [1, 3, 5],
        predictor_config.get("schedule_time"),
    )
    target_info["time_slot_enabled"] = time_slot_enabled
    prediction_result = build_prediction_from_history(
        draws=draws,
        tracking_state=tracking_state,
        predictor_config=predictor_config,
        feature_flags=feature_flags,
        target_info=target_info,
        project_root=project_root,
        backup_count=backup_count,
        blend_mode=blend_mode,
    )
    dataset_summary = data_loader.build_dataset_summary(bundle)
    prediction_result["dataset"] = dataset_summary
    prediction_result["sync"] = {
        "updated": bool(sync_result.get("updated")),
        "message": str(sync_result.get("message", "")),
    }

    last_prediction_state = _build_last_prediction_payload(prediction_result)
    metrics = dict(runtime_state["metrics"])
    metrics["last_prediction_run"] = {
        "run_at": tracking_engine.now_iso(),
        "target_draw_id": prediction_result["target_draw_id"],
        "target_date_estimate": prediction_result["target_date_estimate"],
        "quality_score": prediction_result["quality_score"],
        "main_ticket": prediction_result["main_ticket"],
        "special": prediction_result["special"],
    }
    save_runtime_state(tracking_state, last_prediction_state, metrics, project_root)
    return _public_prediction_payload(prediction_result)


def _build_update_payload(
    tracking_state: dict[str, Any],
    last_prediction: dict[str, Any],
    tracking_update: dict[str, Any],
    regime_after: dict[str, Any],
    deep_result: dict[str, Any],
    actual_main_numbers: list[int],
    actual_special: int | None,
    actual_draw_id: int,
) -> dict[str, Any]:
    return {
        "updated": True,
        "game": "power_6_55",
        "actual_draw_id": actual_draw_id,
        "actual_main_numbers": list(actual_main_numbers),
        "actual_special": actual_special,
        "exact_main_hit_numbers": tracking_update["exact_main_hit_numbers"],
        "special_hit": tracking_update["special_hit"],
        "near_cluster_useful_numbers": tracking_update["near_cluster_useful_numbers"],
        "missed_numbers": tracking_update["missed_numbers"],
        "numbers_to_keep": tracking_update["numbers_to_keep"],
        "numbers_to_cool_down": tracking_update["numbers_to_cool_down"],
        "updated_tracking_state": {
            "kept_numbers": list(tracking_state.get("kept_numbers") or []),
            "true_hot_numbers": list(tracking_state.get("true_hot_numbers") or []),
            "temporary_excluded_numbers": list(tracking_state.get("temporary_excluded_numbers") or []),
            "prioritized_special": list(tracking_state.get("prioritized_special") or []),
        },
        "regime_change_status": {
            "before": str(last_prediction.get("regime", "")),
            "after": str(regime_after.get("regime", "")),
            "changed": str(last_prediction.get("regime", "")) != str(regime_after.get("regime", "")),
        },
        "deep_fine_tune_triggered": bool(deep_result.get("triggered")),
    }


def update_after_actual(
    csv_path: str | Path,
    actual_main_raw: str | None = None,
    actual_special_raw: str | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    project_root = project_root or PROJECT_ROOT
    runtime_config = load_runtime_configuration(project_root)
    runtime_state = load_runtime_state(project_root)
    predictor_config = dict(runtime_config["predictor_config"])
    feature_flags = dict(runtime_config["feature_flags"])
    bundle = data_loader.load_draw_records(csv_path, column_mapping_path=project_root / "config" / "column_mapping.json")
    draws = list(bundle["records"])
    tracking_state = runtime_state["tracking_state"]
    last_prediction = dict(runtime_state["last_prediction"])
    metrics = dict(runtime_state["metrics"])

    if actual_main_raw or actual_special_raw:
        if not actual_main_raw or not actual_special_raw:
            raise ValueError("Manual update requires both actual main numbers and actual special.")
        if not last_prediction or bool(last_prediction.get("resolved", True)):
            raise ValueError("No unresolved prediction is available for a manual update.")
        actual_main_numbers = list(data_loader.parse_actual_main_numbers(actual_main_raw))
        actual_special = data_loader.parse_actual_special(actual_special_raw)
        if actual_special in set(actual_main_numbers):
            raise ValueError("Power 6/55 special number must not duplicate the main numbers.")

        manual_draw_id = int(last_prediction.get("target_draw_id"))
        tracking_update = tracking_engine.update_after_actual(
            state=tracking_state,
            prediction_payload=last_prediction,
            actual_main_numbers=actual_main_numbers,
            actual_special=actual_special,
            tracking_config=dict(predictor_config.get("tracking") or {}),
            draw_id=manual_draw_id,
        )
        tracking_state = tracking_update["next_state"]
        last_prediction["resolved"] = True
        last_prediction["actual_draw_id"] = manual_draw_id
        last_prediction["actual_main_numbers"] = actual_main_numbers
        last_prediction["actual_special"] = actual_special
        last_prediction["evaluation"] = {
            "exact_main_hit_numbers": tracking_update["exact_main_hit_numbers"],
            "special_hit": tracking_update["special_hit"],
            "near_cluster_useful_numbers": tracking_update["near_cluster_useful_numbers"],
            "missed_numbers": tracking_update["missed_numbers"],
            "numbers_to_keep": tracking_update["numbers_to_keep"],
            "numbers_to_cool_down": tracking_update["numbers_to_cool_down"],
        }
        synthetic_history = deepcopy(draws)
        if draws:
            latest = draws[-1]
            if manual_draw_id > latest.draw_id:
                synthetic_history.append(
                    data_loader.DrawRecord(
                        draw_id=manual_draw_id,
                        weekday_text="",
                        draw_date=data_loader.parse_csv_date(last_prediction.get("target_date_estimate")) or latest.draw_date,
                        draw_time=None,
                        main_numbers=tuple(actual_main_numbers),
                        special=actual_special,
                        display_text="",
                        game_label="Power_6/55",
                        source_url="",
                        source_date=None,
                        raw_row={},
                    )
                )
        deep_result = deep_model.fine_tune_after_actual(
            actual_main_numbers=actual_main_numbers,
            actual_special=actual_special,
            predictor_config=predictor_config,
            feature_flags=feature_flags,
            project_root=project_root,
            draws=synthetic_history,
            csv_path=csv_path,
        )
        regime_after = regime_engine.detect_regime(synthetic_history[-8:])
        result = _build_update_payload(
            tracking_state=tracking_state,
            last_prediction=last_prediction,
            tracking_update=tracking_update,
            regime_after=regime_after,
            deep_result=deep_result,
            actual_main_numbers=actual_main_numbers,
            actual_special=actual_special,
            actual_draw_id=manual_draw_id,
        )
        metrics["last_update_run"] = {
            "run_at": tracking_engine.now_iso(),
            "actual_draw_id": manual_draw_id,
            "exact_main_hit_count": len(tracking_update["exact_main_hit_numbers"]),
            "special_hit": tracking_update["special_hit"],
        }
        save_runtime_state(tracking_state, last_prediction, metrics, project_root)
        return result

    sync_result = online_learning.sync_pending_prediction(
        draws=draws,
        tracking_state=tracking_state,
        last_prediction=last_prediction,
        predictor_config=predictor_config,
        feature_flags=feature_flags,
        project_root=project_root,
    )
    if not sync_result.get("updated"):
        return {
            "updated": False,
            "game": "power_6_55",
            "message": str(sync_result.get("message", "")),
        }

    tracking_state = sync_result["tracking_state"]
    last_prediction = sync_result["last_prediction"]
    actual_draw = sync_result["actual_draw"]
    tracking_update = sync_result["update_summary"]
    regime_after = sync_result["regime_after"]
    deep_result = sync_result["deep_result"]
    result = _build_update_payload(
        tracking_state=tracking_state,
        last_prediction=last_prediction,
        tracking_update=tracking_update,
        regime_after=regime_after,
        deep_result=deep_result,
        actual_main_numbers=list(actual_draw.main_numbers),
        actual_special=actual_draw.special,
        actual_draw_id=actual_draw.draw_id,
    )
    metrics["last_update_run"] = {
        "run_at": tracking_engine.now_iso(),
        "actual_draw_id": actual_draw.draw_id,
        "exact_main_hit_count": len(tracking_update["exact_main_hit_numbers"]),
        "special_hit": tracking_update["special_hit"],
    }
    save_runtime_state(tracking_state, last_prediction, metrics, project_root)
    return result
