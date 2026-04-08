from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from src import config as cfg, csv_loader, deep_model, tracking_engine


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def synchronize_with_latest_actual(draws, config_payload, csv_path=None):
    tracking_state = tracking_engine.load_tracking_state()
    last_prediction = cfg.load_last_prediction()
    target_draw_id = str(last_prediction.get("target_draw_id", "")).strip()
    if not target_draw_id or bool(last_prediction.get("resolved", True)):
        return {
            "updated": False,
            "tracking_state": tracking_state,
            "last_prediction": last_prediction,
            "message": "Chưa có kỳ VIP nào đang chờ đối chiếu.",
        }
    actual_draw = csv_loader.find_draw_by_ky(draws, target_draw_id)
    if not actual_draw:
        return {
            "updated": False,
            "tracking_state": tracking_state,
            "last_prediction": last_prediction,
            "message": "Kỳ thật mới chưa về tới target_draw_id nên predictor giữ nguyên tracking.",
        }
    updated_state = tracking_engine.update_after_actual(tracking_state, last_prediction, actual_draw, config_payload)
    tracking_engine.save_tracking_state(updated_state)
    fine_tune_result = deep_model.incremental_fine_tune(
        last_prediction,
        actual_draw,
        draws=draws,
        config_payload=config_payload,
        csv_path=csv_path,
    )
    next_prediction = deepcopy(last_prediction)
    next_prediction["resolved"] = True
    next_prediction["resolved_at"] = _now_iso()
    next_prediction["actual_draw"] = {
        "ky": str(actual_draw.get("ky", "")),
        "date": str(actual_draw.get("date", "")),
        "slot": str(actual_draw.get("slot", "")),
        "main": list(actual_draw.get("main") or []),
        "special": actual_draw.get("special"),
    }
    cfg.save_last_prediction(next_prediction)
    return {
        "updated": True,
        "tracking_state": updated_state,
        "last_prediction": next_prediction,
        "fine_tune": fine_tune_result,
        "message": "Đã cập nhật predictor standalone Loto 5/35 sau khi kỳ thật mới xuất hiện.",
    }
