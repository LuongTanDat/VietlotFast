from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from src import backtest, config as cfg, csv_loader, deep_model, heuristic_engine, online_learning, ticket_evaluator, tracking_engine


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _build_result_notes(selection, regime, sync_result, deep_result, bundle_count):
    primary = selection.get("primary") or {}
    notes = [
        str((deep_result or {}).get("deep_status_line", "")).strip(),
        f"Loto 5/35 Vip standalone đang xuất 1 bộ chính và {len(selection.get('backups') or [])} bộ phụ.",
        str(regime.get("summary", "")).strip(),
        str(sync_result.get("message", "")).strip(),
        str((deep_result or {}).get("message", "")).strip(),
    ]
    if primary.get("qualityScore") is not None:
        notes.append(f"Chất lượng bộ chính hiện tại: {float(primary.get('qualityScore', 0.0)):.2f}/100.")
    if int(bundle_count or 0) < 3:
        notes.append("Vip standalone luôn giữ tối thiểu 1 bộ chính + 2 bộ phụ để có lớp hedge cơ bản.")
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


def predict(csv_path=None, project_root=None, game="loto_5_35", slot=None, bundle_count=3, requested_engine="", risk_mode="balanced", blend_mode=None):
    _ = project_root
    config_payload = cfg.load_config()
    draws = csv_loader.load_history(game, csv_path=csv_path)
    sync_result = online_learning.synchronize_with_latest_actual(draws, config_payload, csv_path=csv_path)
    tracking_state = sync_result.get("tracking_state") or tracking_engine.load_tracking_state()
    target = csv_loader.infer_next_target_draw(draws, slot)
    analysis = heuristic_engine.build_prediction_snapshot(
        draws,
        target,
        tracking_state,
        deepcopy(config_payload),
        bundle_count=bundle_count,
        blend_mode=blend_mode,
    )
    selection = heuristic_engine.select_vip_tickets(analysis, config_payload)
    primary = selection.get("primary")
    if not primary:
        raise RuntimeError("loto_5_35_predictor chưa tạo được bộ Vip hợp lệ.")
    backups = list(selection.get("backups") or [])
    top_main = list(analysis.get("topMain") or [])
    top_bonus = list(analysis.get("topBonus") or [])
    top_heuristic = list(selection.get("topHeuristicCandidates") or analysis.get("topHeuristic") or [])
    top_deep = list(selection.get("topDeepCandidates") or analysis.get("topDeep") or [])
    disagreement = dict(selection.get("disagreementAnalysis") or analysis.get("disagreementAnalysis") or {})
    sync_summary = csv_loader.build_sync_summary_for_path(draws, csv_path)
    backtest_summary = backtest.run_quick_backtest(draws, config_payload)
    metrics_payload = cfg.load_metrics()
    metrics_payload["last_backtest_run"] = {
        **backtest_summary,
        "game": "loto_5_35",
        "predictorVersion": cfg.PREDICTOR_VERSION,
    }
    cfg.save_metrics(metrics_payload)
    result = {
        "ok": True,
        "ready": True,
        "bootstrapComplete": True,
        "mode": "ai_predict",
        "predictionMode": "vip",
        "predictorVersion": cfg.PREDICTOR_VERSION,
        "vipProfile": "loto_5_35_adaptive",
        "vipSummary": f"Vip Loto 5/35 đang dùng predictor standalone riêng với {1 + len(backups)} bộ.",
        "engine": cfg.PREDICTOR_ENGINE,
        "engineLabel": cfg.PREDICTOR_LABEL,
        "type": "LOTO_5_35",
        "label": "Loto_5/35",
        "game": "loto_5_35",
        "modelVersion": cfg.PREDICTOR_VERSION,
        "model": {
            "key": "loto_5_35_vip_adaptive",
            "label": "Loto 5/35 Adaptive VIP",
            "samples": int(sync_summary.get("historyCount", 0)),
            "avgHits": float(backtest_summary.get("avgHits", 0.0)),
            "avgHitRate": float(backtest_summary.get("avgHitRate", 0.0)),
        },
        "champion": {
            "key": "loto_5_35_vip_main_ticket",
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
        "top_heuristic_candidates": top_heuristic[:12],
        "top_deep_candidates": top_deep[:12],
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
        "blend_mode_used": str(analysis.get("blendModeUsed", "blended")),
        "blend_weights_used": dict(analysis.get("blendWeightsUsed") or {}),
        "assembly_mode": str(selection.get("assemblyMode", "blended")),
        "assembly_variants": list(selection.get("assemblyVariants") or []),
        "disagreement_score": float(disagreement.get("score", 0.0) or 0.0),
        "disagreement_level": str(disagreement.get("level", "low") or "low"),
        "disagreement_analysis": disagreement,
        "why_selected": list(selection.get("whySelected") or []),
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
        "ticketSources": [cfg.PREDICTOR_ENGINE for _ in range(1 + len(backups))],
        "tracking_state": _tracking_summary(tracking_state),
        "regime": str((analysis.get("regime") or {}).get("regime", "")),
        "regimeLabel": str((analysis.get("regime") or {}).get("label", "")),
        "confidence": round(min(0.98, 0.58 + float(primary.get("qualityScore", 0.0)) / 250.0), 6),
        "backtest": backtest_summary,
        "sync": sync_summary,
        "deepModel": dict(analysis.get("deep") or {}),
        "deep_enabled": bool((analysis.get("deep") or {}).get("deep_enabled")),
        "deep_status": str((analysis.get("deep") or {}).get("deep_status", "")),
        "deep_status_reason": str((analysis.get("deep") or {}).get("deep_status_reason", "")),
        "deep_status_line": str((analysis.get("deep") or {}).get("deep_status_line", "")),
        "deep_model_type": str((analysis.get("deep") or {}).get("deep_model_type", "")),
        "deep_model_version": str((analysis.get("deep") or {}).get("deep_model_version", "")),
        "deep_last_trained_at": str((analysis.get("deep") or {}).get("deep_last_trained_at", "")),
        "deep_artifacts": dict((analysis.get("deep") or {}).get("deep_artifacts") or {}),
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
                "assemblyMode": str(selection.get("assemblyMode", "blended")),
                "disagreementScore": float(disagreement.get("score", 0.0) or 0.0),
            },
            "blend": {
                "main": dict((analysis.get("blendWeightsUsed") or {}).get("main") or (config_payload.get("blend_weights") or {}).get("main") or {}),
                "bonus": dict((analysis.get("blendWeightsUsed") or {}).get("bonus") or (config_payload.get("blend_weights") or {}).get("bonus") or {}),
                "mode": str(analysis.get("blendModeUsed", "blended")),
                "deepAvailable": bool((analysis.get("deep") or {}).get("available")),
                "deepStatus": str((analysis.get("deep") or {}).get("deep_status", "")),
            },
            "tracking": {
                "kept": list((tracking_state or {}).get("kept_numbers") or []),
                "hot": list((tracking_state or {}).get("true_hot_numbers") or []),
                "excluded": list((tracking_state or {}).get("temporary_excluded_numbers") or []),
                "prioritizedBonus": list((tracking_state or {}).get("prioritized_bonus") or []),
            },
            "assembly": {
                "whySelected": list(selection.get("whySelected") or []),
                "topHeuristicCandidates": top_heuristic[:12],
                "topDeepCandidates": top_deep[:12],
            },
        },
        "dataset": {
            "csv_path": str(csv_loader.resolve_csv_path(csv_path)),
            "record_count": int(sync_summary.get("historyCount", 0)),
            "latest_draw_id": str(sync_summary.get("latestKy", "")),
            "latest_draw_date": str(sync_summary.get("latestDate", "")),
            "latest_draw_slot": str(sync_summary.get("latestTime", "")),
        },
    }
    result["notes"] = _build_result_notes(selection, analysis.get("regime") or {}, sync_result, analysis.get("deep") or {}, bundle_count)

    last_prediction_payload = {
        "version": cfg.PREDICTOR_VERSION,
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


def predict_next_vip(game="loto_5_35", slot=None, bundle_count=3, requested_engine="", risk_mode="balanced", csv_path=None, blend_mode=None):
    return predict(
        csv_path=csv_path,
        game=game,
        slot=slot,
        bundle_count=bundle_count,
        requested_engine=requested_engine,
        risk_mode=risk_mode,
        blend_mode=blend_mode,
    )


def update_after_actual_vip(actual_draw: dict | None = None, csv_path=None):
    config_payload = cfg.load_config()
    draws = csv_loader.load_history("loto_5_35", csv_path=csv_path)
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
                "message": "Đã cập nhật predictor standalone Loto 5/35 bằng actual_draw truyền vào.",
            }
    return sync_result


def get_tracking_state_vip():
    return _tracking_summary(tracking_engine.load_tracking_state())


def get_blend_status():
    config_payload = cfg.load_config()
    metrics_payload = cfg.load_metrics()
    return {
        "game": "loto_5_35",
        "blend_mode_default": str(config_payload.get("blend_mode_default", "blended")),
        "blend_profiles": dict(config_payload.get("blend_profiles") or {}),
        "assembly": dict(config_payload.get("assembly") or {}),
        "deep_status": deep_model.get_deep_status(),
        "last_ablation_report": dict(metrics_payload.get("last_ablation_report") or {}),
    }


def audit_assembly(csv_path=None, slot=None, bundle_count=3):
    prediction = predict(csv_path=csv_path, slot=slot, bundle_count=bundle_count)
    return {
        "game": "loto_5_35",
        "blend_mode_used": prediction.get("blend_mode_used"),
        "blend_weights_used": prediction.get("blend_weights_used"),
        "deep_enabled": prediction.get("deep_enabled"),
        "deep_status": prediction.get("deep_status"),
        "disagreement_score": prediction.get("disagreement_score"),
        "disagreement_level": prediction.get("disagreement_level"),
        "assembly_mode": prediction.get("assembly_mode"),
        "top_heuristic_candidates": prediction.get("top_heuristic_candidates"),
        "top_deep_candidates": prediction.get("top_deep_candidates"),
        "main_ticket": prediction.get("main_ticket"),
        "bonus": prediction.get("bonus"),
        "backup_tickets": prediction.get("backup_tickets"),
        "why_selected": prediction.get("why_selected"),
        "assembly_variants": prediction.get("assembly_variants"),
    }


def evaluate_ticket_vip(ticket: dict, csv_path=None):
    config_payload = cfg.load_config()
    draws = csv_loader.load_history("loto_5_35", csv_path=csv_path)
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
        "regime": dict(analysis.get("regime") or {}),
        "clusterTransition": dict(analysis.get("clusterTransition") or {}),
        "sourceScores": dict(analysis.get("mainFinalScores") or {}),
        "referenceCandidates": list(analysis.get("topHeuristic") or []),
    }
    return ticket_evaluator.evaluate_ticket(ticket, context, config_payload)


def update_after_actual(csv_path=None, actual_draw: dict | None = None):
    return update_after_actual_vip(actual_draw=actual_draw, csv_path=csv_path)


def get_tracking_state():
    return get_tracking_state_vip()


def evaluate_ticket(ticket: dict, csv_path=None):
    return evaluate_ticket_vip(ticket, csv_path=csv_path)
