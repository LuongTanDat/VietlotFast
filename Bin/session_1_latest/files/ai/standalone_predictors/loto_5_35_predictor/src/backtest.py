from __future__ import annotations

from copy import deepcopy
from statistics import mean

from src import config as cfg, csv_loader, heuristic_engine, tracking_engine


ABLATION_MODES = ("heuristic_only", "deep_only", "blended")


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


def _evaluate_mode(draws, config_payload, blend_mode):
    if len(draws) <= 24:
        raise ValueError("Not enough draws to run a chronological backtest.")

    tracking_state = deepcopy(cfg.DEFAULT_TRACKING_STATE)
    hits = []
    recalls = []
    bonus_hits = []
    quality_scores = []

    for index in range(24, len(draws)):
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

    return {
        "blend_mode": blend_mode,
        "draws_tested": len(hits),
        "average_hits": mean(hits) if hits else 0.0,
        "top_k_recall": mean(recalls) if recalls else 0.0,
        "bonus_or_special_accuracy": mean(bonus_hits) if bonus_hits else 0.0,
        "ticket_quality_mean": mean(quality_scores) if quality_scores else 0.0,
    }


def _winner_key(summary):
    return (
        float(summary.get("average_hits", 0.0)),
        float(summary.get("top_k_recall", 0.0)),
        float(summary.get("bonus_or_special_accuracy", 0.0)),
        float(summary.get("ticket_quality_mean", 0.0)),
    )


def run_ablation_report(csv_path=None):
    config_payload = cfg.load_config()
    draws = csv_loader.load_history("loto_5_35", csv_path=csv_path)
    mode_reports = {mode: _evaluate_mode(draws, config_payload, mode) for mode in ABLATION_MODES}
    winner_mode = max(mode_reports, key=lambda mode: _winner_key(mode_reports[mode]))
    return {
        "game": "loto_5_35",
        "predictorVersion": cfg.PREDICTOR_VERSION,
        "dataset": csv_loader.build_sync_summary_for_path(draws, csv_path),
        "modes": mode_reports,
        "winner_mode": winner_mode,
        "winner_summary": mode_reports[winner_mode],
        "metric_priority": ["average_hits", "top_k_recall", "bonus_or_special_accuracy", "ticket_quality_mean"],
    }


def run_backtest(csv_path=None):
    config_payload = cfg.load_config()
    draws = csv_loader.load_history("loto_5_35", csv_path=csv_path)
    quick_summary = run_quick_backtest(draws, config_payload, blend_mode=str(config_payload.get("blend_mode_default", "blended")))
    ablation_report = run_ablation_report(csv_path=csv_path)
    metrics = cfg.load_metrics()
    metrics["last_backtest_run"] = {
        **quick_summary,
        "game": "loto_5_35",
        "predictorVersion": cfg.PREDICTOR_VERSION,
        "winner_mode": ablation_report["winner_mode"],
    }
    metrics["last_ablation_report"] = {
        "game": "loto_5_35",
        "predictorVersion": cfg.PREDICTOR_VERSION,
        **ablation_report,
    }
    cfg.save_metrics(metrics)
    return {
        "ok": True,
        "game": "loto_5_35",
        "predictorVersion": cfg.PREDICTOR_VERSION,
        "dataset": csv_loader.build_sync_summary_for_path(draws, csv_path),
        "quick_summary": quick_summary,
        "ablation_report": ablation_report,
    }
