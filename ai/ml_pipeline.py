from __future__ import annotations

import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai.configs import data_paths as dp
from ai.evaluation.baselines import random_baseline_summary
from ai.evaluation.metrics import brier_score, calibration_error, lift, log_loss
from ai.evaluation.probability import scores_to_probabilities
from ai.evaluation.statistical_tests import paired_bootstrap_ci, paired_permutation_test
from ai.prediction_ledger import (
    create_training_run,
    finish_training_run,
    list_models,
    list_predictions,
    migrate,
    promote_candidate as ledger_promote_candidate,
    register_model,
    reject_candidate,
    rollback_champion,
    score_pending_predictions as ledger_score_pending_predictions,
)

SUPPORTED_ML_GAMES = ("KENO", "LOTO_5_35", "LOTO_6_45", "LOTO_6_55")

GAME_CONFIGS = {
    "KENO": {
        "label": "Keno",
        "universe_size": 80,
        "draw_size": 20,
        "prediction_size": 10,
        "standalone_dir": None,
        "predictor_version": "keno_controlled_v1",
        "min_folds": 24,
        "default_min_history": 240,
        "fast_folds": 48,
    },
    "LOTO_5_35": {
        "label": "Loto 5/35",
        "universe_size": 35,
        "draw_size": 5,
        "prediction_size": 5,
        "standalone_dir": dp.PROJECT_ROOT / "ai" / "standalone_predictors" / "loto_5_35_predictor",
        "predictor_version": "loto_5_35_vip_v1",
        "min_folds": 12,
    },
    "LOTO_6_45": {
        "label": "Mega 6/45",
        "universe_size": 45,
        "draw_size": 6,
        "prediction_size": 6,
        "standalone_dir": dp.PROJECT_ROOT / "ai" / "standalone_predictors" / "mega_6_45_predictor",
        "predictor_version": "mega_6_45_vip_v1",
        "min_folds": 12,
    },
    "LOTO_6_55": {
        "label": "Power 6/55",
        "universe_size": 55,
        "draw_size": 6,
        "prediction_size": 6,
        "standalone_dir": dp.PROJECT_ROOT / "ai" / "standalone_predictors" / "power_6_55_predictor",
        "predictor_version": "power_6_55_vip_v1",
        "min_folds": 12,
    },
}


def normalize_game_type(game_type: str) -> str:
    normalized = str(game_type or "").strip().upper()
    if normalized not in SUPPORTED_ML_GAMES:
        raise ValueError("Game type is not enabled for the controlled ML pipeline.")
    return normalized


def game_config(game_type: str) -> dict[str, Any]:
    return dict(GAME_CONFIGS[normalize_game_type(game_type)])


def parse_int_list(raw: str) -> list[int]:
    return [int(token) for token in str(raw or "").replace(";", ",").split(",") if token.strip().isdigit()]


def load_actual_draws(game_type: str) -> dict[str, dict[str, Any]]:
    game_type = normalize_game_type(game_type)
    path = dp.get_canonical_csv_read_path(game_type)
    if not path.exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            ky = str(row.get("Kỳ") or row.get("Ky") or row.get("ky") or "").strip()
            if not ky:
                continue
            main = parse_int_list(row.get("Bộ Số") or row.get("Main") or row.get("Numbers") or "")
            if not main:
                continue
            special_raw = str(row.get("ĐB") or row.get("Special") or "").strip()
            rows[ky.lstrip("#")] = {
                "ky": ky.lstrip("#"),
                "date": str(row.get("Ngày") or row.get("Ngay") or "").strip(),
                "time": str(row.get("Giờ") or row.get("Time") or "").strip(),
                "main": sorted(main),
                "special": int(special_raw) if special_raw.isdigit() else None,
            }
    return rows


def actual_lookup(game_type: str, target_draw_id: str) -> dict[str, Any] | None:
    draws = load_actual_draws(game_type)
    normalized = str(target_draw_id or "").strip().lstrip("#")
    return draws.get(normalized)


def latest_actual_draw_id(game_type: str) -> str:
    draws = load_actual_draws(game_type)
    if not draws:
        return ""
    return max(draws.keys(), key=lambda value: int("".join(ch for ch in value if ch.isdigit()) or "0"))


def _draw_sort_key(draw: dict[str, Any]) -> int:
    return int("".join(ch for ch in str(draw.get("ky") or draw.get("draw_id") or "") if ch.isdigit()) or "0")


def chronological_actual_draws(game_type: str) -> list[dict[str, Any]]:
    return sorted(load_actual_draws(game_type).values(), key=_draw_sort_key)


def _score_keno_history(history: list[dict[str, Any]], universe_size: int = 80) -> dict[int, float]:
    scores = {number: 0.0 for number in range(1, universe_size + 1)}
    if not history:
        return scores
    recent_short = history[-20:]
    recent_mid = history[-80:]
    last_seen = {number: None for number in range(1, universe_size + 1)}
    for index, draw in enumerate(history):
        for number in draw.get("main") or []:
            last_seen[int(number)] = index
            scores[int(number)] += 0.15
    for draw in recent_mid:
        for number in draw.get("main") or []:
            scores[int(number)] += 0.45
    for draw in recent_short:
        for number in draw.get("main") or []:
            scores[int(number)] += 0.85
    latest_index = len(history) - 1
    for number in range(1, universe_size + 1):
        seen_at = last_seen[number]
        gap = len(history) if seen_at is None else max(0, latest_index - int(seen_at))
        scores[number] += min(2.0, gap / 30.0)
    return scores


def run_keno_backtest(
    mode: str = "fast",
    window: str = "expanding",
    rolling_window: int | None = None,
    min_history: int | None = None,
    prediction_size: int | None = None,
) -> dict[str, Any]:
    cfg = game_config("KENO")
    draws = chronological_actual_draws("KENO")
    min_history = max(40, int(min_history or cfg.get("default_min_history") or 240))
    prediction_size = max(1, min(10, int(prediction_size or cfg["prediction_size"])))
    if len(draws) <= min_history:
        raise ValueError("Not enough Keno draws to run a chronological backtest.")

    indexes = list(range(min_history, len(draws)))
    if str(mode or "fast").lower() == "fast":
        indexes = indexes[-int(cfg.get("fast_folds") or 48):]

    folds: list[dict[str, Any]] = []
    probability_rows: list[dict[int, float]] = []
    label_rows: list[list[int]] = []
    hit_values: list[int] = []
    predictions: list[list[int]] = []
    actuals: list[list[int]] = []
    for fold_number, index in enumerate(indexes, start=1):
        if str(window or "expanding").lower() == "rolling":
            scoped_window = max(min_history, int(rolling_window or min_history))
            history = list(draws[max(0, index - scoped_window):index])
        else:
            history = list(draws[:index])
        actual = draws[index]
        scores = _score_keno_history(history, cfg["universe_size"])
        ranking = sorted(scores, key=lambda number: (-scores[number], number))
        ticket = ranking[:prediction_size]
        actual_main = list(actual.get("main") or [])
        calibrated = scores_to_probabilities(scores, cfg["draw_size"], 1, cfg["universe_size"])
        hit_count = len(set(ticket) & set(actual_main))
        hit_values.append(hit_count)
        predictions.append(ticket)
        actuals.append(actual_main)
        probability_rows.append(calibrated)
        label_rows.append(actual_main)
        folds.append({
            "fold": fold_number,
            "target_draw_id": str(actual.get("ky") or ""),
            "data_cutoff_draw_id": str(history[-1].get("ky") if history else ""),
            "train_size": len(history),
            "window": str(window or "expanding"),
            "main_ticket": ticket,
            "actual_main": actual_main,
            "hit_count": hit_count,
            "calibrated_probability": calibrated,
            "deep_status": "not_applicable",
            "deep_status_reason": "Keno controlled backtest uses deterministic history-only ranking.",
        })

    mean_hit = sum(hit_values) / float(len(hit_values)) if hit_values else 0.0
    metrics = {
        "blend_mode": "keno_history_ranker",
        "draws_tested": len(folds),
        "fold_count": len(folds),
        "average_hits": mean_hit,
        "avgHits": mean_hit,
        "avgHitRate": mean_hit / float(prediction_size) if prediction_size else 0.0,
        "brier_score": brier_score(probability_rows, label_rows, cfg["universe_size"]) if probability_rows else 0.0,
        "log_loss": log_loss(probability_rows, label_rows, cfg["universe_size"]) if probability_rows else 0.0,
        "calibration_error": calibration_error(probability_rows, label_rows, cfg["universe_size"]) if probability_rows else 0.0,
        "folds": folds,
    }
    return {
        "ok": True,
        "game": "keno",
        "game_type": "KENO",
        "predictorVersion": cfg["predictor_version"],
        "dataset": {
            "historyCount": len(draws),
            "latestKy": str(draws[-1].get("ky") if draws else ""),
            "historyFile": str(dp.get_canonical_csv_read_path("KENO")),
        },
        "winner_mode": "keno_history_ranker",
        "winner_summary": metrics,
        "metrics": dict(metrics),
        "fold_predictions": folds,
        "backtest_mode": str(mode or "fast"),
        "window": str(window or "expanding"),
        "rolling_window": rolling_window,
        "prediction_size": prediction_size,
        "leakage_guard": {
            "history_rule": "each Keno fold uses draws before target_draw_id only",
            "deep_policy": "not_applicable_for_keno_history_ranker",
            "tracking_policy": "Keno backtest state is rebuilt from the fold history only",
        },
    }


def _run_standalone_json(game_type: str, args: list[str], timeout: int = 600) -> dict[str, Any]:
    cfg = game_config(game_type)
    root = Path(cfg["standalone_dir"])
    command = [sys.executable or "python", "main.py", *args]
    completed = subprocess.run(
        command,
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(message or f"standalone predictor exited with code {completed.returncode}")
    try:
        return json.loads(completed.stdout or "{}")
    except Exception as exc:
        raise RuntimeError(f"standalone predictor returned invalid JSON: {exc}")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _folds_from_backtest(result: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(result.get("fold_predictions"), list):
        return list(result.get("fold_predictions") or [])
    winner = result.get("winner_summary")
    if isinstance(winner, dict) and isinstance(winner.get("folds"), list):
        return list(winner.get("folds") or [])
    metrics = result.get("metrics")
    if isinstance(metrics, dict) and isinstance(metrics.get("folds"), list):
        return list(metrics.get("folds") or [])
    ablation = result.get("ablation_report")
    if isinstance(ablation, dict):
        winner = ablation.get("winner_summary")
        if isinstance(winner, dict) and isinstance(winner.get("folds"), list):
            return list(winner.get("folds") or [])
    return []


def _persist_backtest_result(game_type: str, result: dict[str, Any]) -> str:
    out_dir = dp.RUNTIME_DIR / "backtests"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{game_type.lower()}_{str(result.get('backtest_mode') or result.get('mode') or 'fast')}_{_utc_stamp()}.json"
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(out_path)
    return str(out_path)


def _add_baseline_comparison(game_type: str, result: dict[str, Any]) -> None:
    cfg = game_config(game_type)
    folds = _folds_from_backtest(result)
    prediction_size = int(result.get("prediction_size") or cfg["prediction_size"])
    expected_hits = prediction_size * cfg["draw_size"] / float(cfg["universe_size"])
    hit_values = [float(fold.get("hit_count", 0.0) or 0.0) for fold in folds]
    baseline_values = [expected_hits for _ in hit_values]
    mean_hit = sum(hit_values) / float(len(hit_values)) if hit_values else 0.0
    result["baseline_comparison"] = {
        "same_folds": True,
        "fold_count": len(folds),
        "mean_hit": mean_hit,
        "expected_random_hits": expected_hits,
        "lift": lift(mean_hit, cfg["universe_size"], cfg["draw_size"], prediction_size) if hit_values else 0.0,
        "paired_bootstrap_ci": paired_bootstrap_ci(hit_values, baseline_values, iterations=500, seed=20260403) if hit_values else {},
        "paired_permutation_test": paired_permutation_test(hit_values, baseline_values, iterations=500, seed=20260403) if hit_values else {},
        "warning": "" if hit_values else "not enough folds to compare against random baseline",
    }


def _compact_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    payload = dict(metrics or {})
    folds = payload.pop("folds", None)
    if isinstance(folds, list):
        payload["fold_count"] = len(folds)
    return payload


def _fold_count(metrics: dict[str, Any]) -> int:
    value = metrics.get("fold_count") or metrics.get("draws_tested") or metrics.get("samples")
    if isinstance(value, list):
        return len(value)
    if value:
        try:
            return int(value)
        except Exception:
            return 0
    folds = metrics.get("folds")
    return len(folds) if isinstance(folds, list) else 0


def run_backtest(
    game_type: str,
    mode: str = "fast",
    window: str = "expanding",
    rolling_window: int | None = None,
    min_history: int | None = None,
    retrain_interval: int | None = None,
) -> dict[str, Any]:
    game_type = normalize_game_type(game_type)
    if game_type == "KENO":
        result = run_keno_backtest(
            mode=mode,
            window=window,
            rolling_window=rolling_window,
            min_history=min_history,
            prediction_size=GAME_CONFIGS["KENO"]["prediction_size"],
        )
        cfg = game_config(game_type)
        result["random_baseline"] = random_baseline_summary(cfg["universe_size"], cfg["draw_size"], int(result.get("prediction_size") or cfg["prediction_size"]))
        _add_baseline_comparison(game_type, result)
        result["fold_predictions_path"] = _persist_backtest_result(game_type, result)
        return result
    args = ["backtest", "--csv", str(dp.get_canonical_csv_read_path(game_type)), "--mode", str(mode or "fast"), "--window", str(window or "expanding")]
    if rolling_window:
        args.extend(["--rolling-window", str(int(rolling_window))])
    if min_history:
        args.extend(["--min-history", str(int(min_history))])
    if retrain_interval:
        args.extend(["--retrain-interval", str(int(retrain_interval))])
    result = _run_standalone_json(game_type, args, timeout=900 if mode == "full" else 420)
    cfg = game_config(game_type)
    baseline = random_baseline_summary(cfg["universe_size"], cfg["draw_size"], cfg["prediction_size"])
    result["random_baseline"] = baseline
    result["game_type"] = game_type
    _add_baseline_comparison(game_type, result)
    result["fold_predictions_path"] = _persist_backtest_result(game_type, result)
    return result


def status(game_type: str | None = None) -> dict[str, Any]:
    migrate()
    games = [normalize_game_type(game_type)] if game_type else list(SUPPORTED_ML_GAMES)
    payload = {"ok": True, "games": []}
    for key in games:
        cfg = game_config(key)
        champions = list_models(key, "champion")
        candidates = list_models(key, "candidate")
        locked = list_predictions(key, "locked", limit=1000)
        scored = list_predictions(key, "scored", limit=1000)
        payload["games"].append({
            "game_type": key,
            "label": cfg["label"],
            "champion": champions[0] if champions else None,
            "candidate_count": len(candidates),
            "locked_predictions": len(locked),
            "scored_predictions": len(scored),
            "latest_actual_draw_id": latest_actual_draw_id(key),
            "baseline": random_baseline_summary(cfg["universe_size"], cfg["draw_size"], cfg["prediction_size"]),
        })
    return payload


def predictions(game_type: str | None = None, limit: int = 100, username: str | None = None) -> dict[str, Any]:
    return {"ok": True, "predictions": list_predictions(game_type, limit=limit, username=username)}


def score_pending_predictions(game_type: str) -> dict[str, Any]:
    game_type = normalize_game_type(game_type)
    cfg = game_config(game_type)
    return ledger_score_pending_predictions(
        game_type=game_type,
        actual_lookup=actual_lookup,
        universe_size=int(cfg["universe_size"]),
        draw_size=int(cfg["draw_size"]),
        prediction_size=int(cfg["prediction_size"]),
    )


def train_candidate(game_type: str, mode: str = "fast") -> dict[str, Any]:
    game_type = normalize_game_type(game_type)
    cfg = game_config(game_type)
    cutoff = latest_actual_draw_id(game_type)
    training_run = create_training_run(game_type, cutoff)
    try:
        backtest = run_backtest(game_type, mode=mode, window="expanding")
        metrics = dict(backtest.get("metrics") or backtest.get("winner_summary") or {})
        if "brier_score" not in metrics and isinstance(backtest.get("ablation_report"), dict):
            metrics.update(dict((backtest["ablation_report"].get("winner_summary") or {})))
        if "brier_score" not in metrics:
            metrics.update(dict((backtest.get("summary") or {}).get("metrics") or {}))
        metrics = _compact_metrics(metrics)
        model = register_model(
            game_type=game_type,
            version=f"{cfg['predictor_version']}_candidate",
            trained_data_cutoff=cutoff,
            status="candidate",
            artifact_paths={"note": "candidate evaluation only; production artifacts are not overwritten"},
            validation_metrics=metrics,
            outer_backtest_metrics=_compact_metrics(dict(backtest.get("metrics") or metrics)),
            feature_version="controlled_pipeline_v1",
            promotion_reason="candidate created; promotion requires explicit admin action",
        )
        finish_training_run(
            training_run["training_run_id"],
            "finished",
            candidate_model_id=model["model_id"],
            metrics=metrics,
            payload=backtest,
        )
        return {"ok": True, "game_type": game_type, "training_run": training_run, "candidate": model, "backtest": backtest}
    except Exception as exc:
        finish_training_run(training_run["training_run_id"], "failed", error={"message": str(exc)})
        raise


def _random_brier_baseline(universe_size: int, draw_size: int) -> float:
    p = draw_size / float(universe_size)
    return p * (1.0 - p)


def _candidate_passes(candidate: dict[str, Any], champion: dict[str, Any] | None, cfg: dict[str, Any]) -> tuple[bool, str]:
    metrics = dict(candidate.get("validation_metrics") or {})
    outer = dict(candidate.get("outer_backtest_metrics") or {})
    combined = {**outer, **metrics}
    folds = _fold_count(combined)
    min_folds = int(cfg.get("min_folds") or 12)
    if folds < min_folds:
        return False, f"not enough folds ({folds}/{min_folds})"
    candidate_brier = combined.get("brier_score")
    candidate_log_loss = combined.get("log_loss")
    if candidate_brier is not None and float(candidate_brier) > _random_brier_baseline(cfg["universe_size"], cfg["draw_size"]):
        return False, "candidate Brier score is worse than random baseline"
    if champion:
        champion_metrics = {**dict(champion.get("outer_backtest_metrics") or {}), **dict(champion.get("validation_metrics") or {})}
        champion_brier = champion_metrics.get("brier_score")
        champion_log_loss = champion_metrics.get("log_loss")
        if champion_brier is not None and candidate_brier is not None and float(candidate_brier) >= float(champion_brier):
            return False, "candidate Brier score is not better than champion on comparable folds"
        if champion_log_loss is not None and candidate_log_loss is not None and float(candidate_log_loss) > float(champion_log_loss) * 1.02:
            return False, "candidate Log Loss regressed more than allowed"
    return True, "promotion gates passed"


def promote_candidate(game_type: str, model_id: str, force: bool = False) -> dict[str, Any]:
    game_type = normalize_game_type(game_type)
    cfg = game_config(game_type)
    candidates = [model for model in list_models(game_type, "candidate") if model.get("model_id") == model_id]
    if not candidates:
        raise ValueError("candidate model not found")
    champion = (list_models(game_type, "champion") or [None])[0]
    candidate = candidates[0]
    passed, reason = _candidate_passes(candidate, champion, cfg)
    if not passed:
        reject_candidate(game_type, model_id, reason)
        return {"ok": False, "promoted": False, "rejected": True, "reason": reason, "model_id": model_id}
    result = ledger_promote_candidate(game_type, model_id, reason)
    result["promoted"] = True
    result["reason"] = reason
    return result


def rollback(game_type: str) -> dict[str, Any]:
    return rollback_champion(normalize_game_type(game_type))
