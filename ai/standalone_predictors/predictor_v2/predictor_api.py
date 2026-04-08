from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from predictor_v2 import backtest, config as cfg, csv_loader, heuristic_engine, online_learning, ticket_evaluator, tracking_engine


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _build_result_notes(selection, regime, sync_result, deep_result, bundle_count):
    primary = selection.get("primary") or {}
    notes = [
        f"Predictor V2 đang xuất 1 bộ chính và {len(selection.get('backups') or [])} bộ phụ cho Vip 5/35.",
        str(regime.get("summary", "")).strip(),
        str(sync_result.get("message", "")).strip(),
        str((deep_result or {}).get("message", "")).strip(),
    ]
    if primary.get("qualityScore") is not None:
        notes.append(f"Chất lượng bộ chính hiện tại: {float(primary.get('qualityScore', 0.0)):.2f}/100.")
    if int(bundle_count or 0) < 3:
        notes.append("Vip predictor_v2 luôn giữ tối thiểu 1 bộ chính + 2 bộ phụ để có lớp hedge cơ bản.")
    return [note for note in notes if note]


def _tracking_summary(state):
    snapshot = tracking_engine.summarize_tracking_state(state)
    return {
        "kept_numbers": list(snapshot.get("kept_numbers") or []),
        "true_hot_numbers": list(snapshot.get("true_hot_numbers") or []),
        "temporary_excluded_numbers": list(snapshot.get("temporary_excluded_numbers") or []),
        "prioritized_bonus": list(snapshot.get("prioritized_bonus") or []),
        "memory_scores": dict(snapshot.get("memory_scores") or {}),
        "recent_prediction_log": list(snapshot.get("recent_prediction_log") or []),
        "updated_at": str(snapshot.get("updated_at", "")),
    }


def predict_next_vip(game="loto_5_35", slot=None, bundle_count=3, requested_engine="", risk_mode="balanced"):
    config_payload = cfg.load_config()
    draws = csv_loader.load_history(game)
    sync_result = online_learning.synchronize_with_latest_actual(draws, config_payload)
    tracking_state = sync_result.get("tracking_state") or tracking_engine.load_tracking_state()
    target = csv_loader.infer_next_target_draw(draws, slot)
    analysis = heuristic_engine.build_prediction_snapshot(draws, target, tracking_state, deepcopy(config_payload), bundle_count=bundle_count)
    selection = heuristic_engine.select_vip_tickets(analysis, config_payload)
    primary = selection.get("primary")
    if not primary:
        raise RuntimeError("predictor_v2 chưa tạo được bộ Vip hợp lệ cho loto_5_35.")
    backups = list(selection.get("backups") or [])
    top_main = list(analysis.get("topMain") or [])
    top_bonus = list(analysis.get("topBonus") or [])
    sync_summary = csv_loader.build_sync_summary(draws)
    backtest_summary = backtest.run_quick_backtest(draws, config_payload)
    result = {
        "ok": True,
        "ready": True,
        "bootstrapComplete": True,
        "mode": "ai_predict",
        "predictorVersion": "predictor_v2",
        "vipProfile": "predictor_v2_adaptive",
        "engine": "predictor_v2",
        "engineLabel": "Predictor V2 Vip",
        "type": "LOTO_5_35",
        "label": "Loto_5/35",
        "game": "loto_5_35",
        "modelVersion": "predictor_v2_heuristic_first_pass",
        "model": {
            "key": "predictor_v2_adaptive",
            "label": "Predictor V2 Adaptive VIP",
            "samples": int(sync_summary.get("historyCount", 0)),
            "avgHits": float(backtest_summary.get("avgHits", 0.0)),
            "avgHitRate": float(backtest_summary.get("avgHitRate", 0.0)),
        },
        "champion": {
            "key": "predictor_v2_primary_ticket",
            "label": "Primary VIP Ticket",
        },
        "historyFile": sync_summary["historyFile"],
        "historyCount": int(sync_summary["historyCount"]),
        "latestKy": sync_summary["latestKy"],
        "latestDate": sync_summary["latestDate"],
        "latestTime": sync_summary["latestTime"],
        "nextKy": f"#{target['target_draw_id']}" if target.get("target_draw_id") else "",
        "target_draw_id": str(target.get("target_draw_id", "")),
        "target_slot": str(target.get("target_slot", "")),
        "target_date": str(target.get("target_date", "")),
        "bundleCount": 1 + len(backups),
        "pickSize": 5,
        "topRanking": top_main[:20],
        "topSpecialRanking": top_bonus[:6],
        "top_main_candidates": [
            {
                "number": int(number),
                "score": round(float((analysis.get("mainFinalScores") or {}).get(number, 0.0)), 6),
                "heuristic": round(float(((analysis.get("snapshot") or {}).get("mainHeuristicScores") or {}).get(number, 0.0)), 6),
                "tracking": round(float(tracking_engine.get_tracking_score(tracking_state, number, "main")), 6),
                "regime": round(float(((analysis.get("regime") or {}).get("mainAdjustments") or {}).get(number, 0.0)), 6),
                "deep": round(float(((analysis.get("deep") or {}).get("mainScores") or {}).get(number, 0.0)), 6),
            }
            for number in top_main[:12]
        ],
        "top_bonus_candidates": [
            {
                "number": int(number),
                "score": round(float((analysis.get("bonusFinalScores") or {}).get(number, 0.0)), 6),
                "heuristic": round(float(((analysis.get("snapshot") or {}).get("bonusHeuristicScores") or {}).get(number, 0.0)), 6),
                "tracking": round(float(tracking_engine.get_tracking_score(tracking_state, number, "bonus")), 6),
                "regime": round(float(((analysis.get("regime") or {}).get("bonusAdjustments") or {}).get(number, 0.0)), 6),
                "deep": round(float(((analysis.get("deep") or {}).get("bonusScores") or {}).get(number, 0.0)), 6),
            }
            for number in top_bonus[:6]
        ],
        "main_ticket": list(primary.get("main") or []),
        "backup_tickets": [list(ticket.get("main") or []) for ticket in backups],
        "bonus": int(primary.get("special") or 0),
        "bonus_backups": [int(ticket.get("special") or 0) for ticket in backups if isinstance(ticket.get("special"), int)],
        "quality_score": float(primary.get("qualityScore", 0.0)),
        "qualityScore": float(primary.get("qualityScore", 0.0)),
        "tickets": [
            {
                "main": list(ticket.get("main") or []),
                "special": int(ticket.get("special") or 0),
                "qualityScore": float(ticket.get("qualityScore", 0.0)),
                "beautyScore": float(ticket.get("beautyScore", 0.0)),
                "qualityBreakdown": dict(ticket.get("qualityBreakdown") or {}),
            }
            for ticket in [primary, *backups]
        ],
        "ticketSources": ["predictor_v2" for _ in range(1 + len(backups))],
        "tracking_state": _tracking_summary(tracking_state),
        "regime": str((analysis.get("regime") or {}).get("regime", "")),
        "regimeLabel": str((analysis.get("regime") or {}).get("label", "")),
        "confidence": round(min(0.98, 0.58 + float(primary.get("qualityScore", 0.0)) / 250.0), 6),
        "backtest": backtest_summary,
        "sync": sync_summary,
        "deepModel": dict(analysis.get("deep") or {}),
        "explanation": {
            "requested_engine": str(requested_engine or ""),
            "risk_mode": str(risk_mode or ""),
            "target": {
                "drawId": str(target.get("target_draw_id", "")),
                "slot": str(target.get("target_slot", "")),
                "date": str(target.get("target_date", "")),
                "sameDayFollowUp": bool(target.get("same_day_follow_up")),
            },
            "selection": {
                "qualityScore": float(primary.get("qualityScore", 0.0)),
                "backupCount": len(backups),
                "sameDayCarryLimit": int((analysis.get("regime") or {}).get("sameDayCarryLimit", 1) or 1),
            },
            "blend": {
                "main": dict((config_payload.get("blend_weights") or {}).get("main") or {}),
                "bonus": dict((config_payload.get("blend_weights") or {}).get("bonus") or {}),
                "deepAvailable": bool((analysis.get("deep") or {}).get("available")),
            },
            "tracking": {
                "kept": list((tracking_state or {}).get("kept_numbers") or []),
                "hot": list((tracking_state or {}).get("true_hot_numbers") or []),
                "excluded": list((tracking_state or {}).get("temporary_excluded_numbers") or []),
                "prioritizedBonus": list((tracking_state or {}).get("prioritized_bonus") or []),
            },
        },
    }
    result["notes"] = _build_result_notes(selection, analysis.get("regime") or {}, sync_result, analysis.get("deep") or {}, bundle_count)

    last_prediction_payload = {
        "version": "predictor_v2",
        "game": "loto_5_35",
        "resolved": False,
        "target_draw_id": str(target.get("target_draw_id", "")),
        "target_slot": str(target.get("target_slot", "")),
        "created_at": _now_iso(),
        "source_latest_ky": str(sync_summary.get("latestKy", "")),
        "main_ticket": list(result["main_ticket"]),
        "backup_tickets": list(result["backup_tickets"]),
        "bonus": int(result["bonus"] or 0),
        "bonus_backups": list(result["bonus_backups"]),
        "quality_score": float(result["quality_score"]),
        "tickets": list(result["tickets"]),
    }
    cfg.save_last_prediction(last_prediction_payload)
    return result


def update_after_actual_vip(actual_draw: dict | None = None):
    config_payload = cfg.load_config()
    draws = csv_loader.load_history("loto_5_35")
    if actual_draw and actual_draw.get("ky"):
        target_draw = csv_loader.find_draw_by_ky(draws, actual_draw.get("ky"))
        if target_draw:
            actual_draw = target_draw
    sync_result = online_learning.synchronize_with_latest_actual(draws, config_payload)
    if actual_draw and not sync_result.get("updated"):
        tracking_state = tracking_engine.load_tracking_state()
        last_prediction = cfg.load_last_prediction()
        if str(last_prediction.get("target_draw_id", "")) == str(actual_draw.get("ky", "")):
            next_state = tracking_engine.update_after_actual(tracking_state, last_prediction, actual_draw, config_payload)
            tracking_engine.save_tracking_state(next_state)
            sync_result = {
                "updated": True,
                "tracking_state": next_state,
                "last_prediction": last_prediction,
                "message": "Đã cập nhật predictor_v2 bằng actual_draw truyền vào.",
            }
    return sync_result


def get_tracking_state_vip():
    return _tracking_summary(tracking_engine.load_tracking_state())


def evaluate_ticket_vip(ticket: dict):
    config_payload = cfg.load_config()
    draws = csv_loader.load_history("loto_5_35")
    tracking_state = tracking_engine.load_tracking_state()
    target = csv_loader.infer_next_target_draw(draws)
    analysis = heuristic_engine.build_prediction_snapshot(draws, target, tracking_state, deepcopy(config_payload), bundle_count=3)
    context = {
        "historicalDraws": list((analysis.get("snapshot") or {}).get("slotHistory") or draws[-24:]),
        "pairContext": dict((analysis.get("snapshot") or {}).get("pairContext") or {}),
        "mainScores": dict(analysis.get("mainFinalScores") or {}),
        "bonusScores": dict(analysis.get("bonusFinalScores") or {}),
        "trackingSummary": _tracking_summary(tracking_state),
        "deepMainScores": dict((analysis.get("deep") or {}).get("mainScores") or {}),
        "deepBonusScores": dict((analysis.get("deep") or {}).get("bonusScores") or {}),
    }
    return ticket_evaluator.evaluate_ticket(ticket, context)
