from __future__ import annotations

from copy import deepcopy

from predictor_v2 import heuristic_engine


def run_quick_backtest(draws, config_payload):
    sample_count = min(max(6, int(((config_payload.get("history_limits") or {}).get("backtest_samples") or 18))), max(0, len(draws) - 12))
    if sample_count <= 0:
        return {
            "samples": 0,
            "avgHits": 0.0,
            "avgHitRate": 0.0,
            "note": "Chưa đủ dữ liệu để chạy backtest predictor_v2.",
        }
    hits = []
    for offset in range(sample_count, 0, -1):
        history = list(draws[:-offset])
        actual = draws[-offset]
        if len(history) < 24:
            continue
        tracking_state = {
            "kept_numbers": [],
            "true_hot_numbers": [],
            "temporary_excluded_numbers": [],
            "prioritized_bonus": [],
            "memory_scores": {"main": {}, "bonus": {}},
            "recent_prediction_log": [],
        }
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
        analysis = heuristic_engine.build_prediction_snapshot(history, target, tracking_state, deepcopy(config_payload), bundle_count=3)
        selection = heuristic_engine.select_vip_tickets(analysis, config_payload)
        primary = selection.get("primary") or {}
        predicted_main = set(int(value) for value in list(primary.get("main") or []))
        actual_main = set(int(value) for value in list(actual.get("main") or []))
        hits.append(len(predicted_main.intersection(actual_main)))
    if not hits:
        return {
            "samples": 0,
            "avgHits": 0.0,
            "avgHitRate": 0.0,
            "note": "Không tạo được cửa sổ backtest hợp lệ cho predictor_v2.",
        }
    average_hits = sum(hits) / float(len(hits))
    return {
        "samples": len(hits),
        "avgHits": round(average_hits, 4),
        "avgHitRate": round(average_hits / 5.0, 6),
        "note": "Backtest nhanh predictor_v2 trên các kỳ gần nhất với lớp heuristic + tracking.",
    }
