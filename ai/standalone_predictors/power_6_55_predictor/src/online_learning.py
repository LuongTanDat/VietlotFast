from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from src import data_loader, deep_model, regime_engine, tracking_engine


def sync_pending_prediction(
    draws: list[Any],
    tracking_state: dict[str, Any],
    last_prediction: dict[str, Any],
    predictor_config: dict[str, Any],
    feature_flags: dict[str, Any],
    project_root: Path,
    csv_path: str | Path | None = None,
) -> dict[str, Any]:
    prediction_payload = dict(last_prediction or {})
    if not prediction_payload or bool(prediction_payload.get("resolved", True)):
        return {
            "updated": False,
            "tracking_state": tracking_state,
            "last_prediction": prediction_payload,
            "message": "No unresolved prediction was waiting for a real draw.",
        }

    target_draw_id = prediction_payload.get("target_draw_id")
    actual_draw = data_loader.find_draw_by_id(draws, target_draw_id)
    if actual_draw is None:
        return {
            "updated": False,
            "tracking_state": tracking_state,
            "last_prediction": prediction_payload,
            "message": "Latest CSV does not contain the unresolved target draw yet.",
        }

    tracking_update = tracking_engine.update_after_actual(
        state=tracking_state,
        prediction_payload=prediction_payload,
        actual_main_numbers=list(actual_draw.main_numbers),
        actual_special=actual_draw.special,
        tracking_config=dict(predictor_config.get("tracking") or {}),
        draw_id=actual_draw.draw_id,
    )
    next_state = tracking_update["next_state"]
    deep_update = deep_model.fine_tune_after_actual(
        actual_main_numbers=list(actual_draw.main_numbers),
        actual_special=actual_draw.special,
        predictor_config=predictor_config,
        feature_flags=feature_flags,
        project_root=project_root,
        draws=draws,
        csv_path=csv_path,
    )
    resolved_prediction = deepcopy(prediction_payload)
    resolved_prediction["resolved"] = True
    resolved_prediction["actual_draw_id"] = actual_draw.draw_id
    resolved_prediction["actual_main_numbers"] = list(actual_draw.main_numbers)
    resolved_prediction["actual_special"] = actual_draw.special
    resolved_prediction["evaluation"] = {
        "exact_main_hit_numbers": tracking_update["exact_main_hit_numbers"],
        "special_hit": tracking_update["special_hit"],
        "near_cluster_useful_numbers": tracking_update["near_cluster_useful_numbers"],
        "missed_numbers": tracking_update["missed_numbers"],
        "numbers_to_keep": tracking_update["numbers_to_keep"],
        "numbers_to_cool_down": tracking_update["numbers_to_cool_down"],
    }
    resolved_prediction["deep_fine_tune"] = deep_update
    regime_after = regime_engine.detect_regime(draws[-8:])
    return {
        "updated": True,
        "tracking_state": next_state,
        "last_prediction": resolved_prediction,
        "actual_draw": actual_draw,
        "update_summary": tracking_update,
        "regime_after": regime_after,
        "deep_result": deep_update,
        "message": f"Resolved pending prediction against actual draw #{actual_draw.draw_id}.",
    }
