"""Fixed, deterministic research profiles shared by replay and future trials.

Only supplied historical draws are read. Profiles do not load canonical data,
consult the model registry, or save state. Their marginal estimates are deliberately
shrunk toward uniform and remain uncalibrated; they are not ticket win probabilities.
"""
from __future__ import annotations

import copy
import hashlib
import math
import random

from ai import prediction_ledger as ledger
from ai.evaluation.probability import scores_to_probabilities

PROFILE_VERSION = "lab_scoring_profiles_v1"
_SCORING_SETUPS = (
    ("short", "Ngắn hạn", 60, 15, (0.60, 0.00, 0.30, 0.10)),
    ("medium", "Trung hạn", 180, 30, (0.80, 0.00, 0.15, 0.05)),
    ("long", "Toàn lịch sử", None, 60, (0.90, 0.00, 0.05, 0.05)),
)
_ALLOCATIONS = (("stable", "Ổn định"), ("aggressive", "Tập trung"))
_GAMES = ("LOTO_5_35", "LOTO_6_45", "LOTO_6_55")


def _digest(value) -> str:
    return hashlib.sha256(ledger.canonical_json(value).encode("utf-8")).hexdigest()


def _catalog() -> list[dict]:
    return [{"id": f"{key}_{allocation}", "label": f"{label} · {allocation_label}",
             "version": PROFILE_VERSION, "historyWindow": window, "recentWindow": recent,
             "weights": list(weights), "allocation": allocation, "uniformMix": 0.85,
             "weightLabels": ["Tần suất", "Độ trễ", "Xu hướng gần", "Đồng xuất hiện"],
             "description": (f"Dùng {window if window else 'toàn bộ'} kỳ trước mục tiêu; "
                             f"xu hướng {recent} kỳ, phân bổ {allocation_label.lower()}. "
                             "Ước lượng trộn 85% đối chứng đều, chưa hiệu chỉnh xác suất.")}
            for key, label, window, recent, weights in _SCORING_SETUPS
            for allocation, allocation_label in _ALLOCATIONS]


def list_profiles(game: str | None = None) -> list[dict]:
    if game is not None and game not in _GAMES:
        raise ValueError("Game không hỗ trợ Phòng thử thuật toán.")
    return copy.deepcopy(_catalog())


def profile_definition(profile_id: str) -> dict:
    for profile in _catalog():
        if profile["id"] == profile_id:
            return copy.deepcopy(profile)
    raise ValueError("Cấu hình phòng thử không còn hợp lệ; hãy chạy lượt thử mới.")


def config_hash(profile: dict | str) -> str:
    return _digest(profile_definition(profile) if isinstance(profile, str) else profile)


def _probabilities(rows: list[dict], universe_size: int, draw_size: int,
                   profile: dict, field: str = "main") -> dict[int, float]:
    from ai.predictors import number_scoring
    observed = [{"numbers": list(row[field]) if field == "main" else [row[field]]}
                for row in rows if row.get(field) is not None]
    if not observed:
        return {number: draw_size / universe_size for number in range(1, universe_size + 1)}
    scored = number_scoring.build_number_scoring_rows(
        observed, range(1, universe_size + 1), profile["recentWindow"], profile["weights"])
    estimated = scores_to_probabilities({row["numberValue"]: row["Score_i"] for row in scored},
                                       draw_size, 1, universe_size)
    uniform = draw_size / universe_size
    mix = profile["uniformMix"]
    return {number: (1 - mix) * value + mix * uniform for number, value in estimated.items()}


def _validate_history(game: str, history: list[dict]):
    from ai import ml_pipeline
    cfg = ml_pipeline.game_config(game)
    if not history:
        raise ValueError("Cấu hình cần lịch sử trước kỳ mục tiêu.")
    ids = [int(row["ky"]) for row in history]
    if ids != sorted(set(ids)):
        raise ValueError("Lịch sử cấu hình phải tăng theo kỳ và không lặp.")
    for row in history:
        main = row.get("main", [])
        if (len(main) != cfg["draw_size"] or len(set(main)) != len(main)
                or any(type(n) is not int or not 1 <= n <= cfg["universe_size"] for n in main)):
            raise ValueError("Lịch sử cấu hình chứa bộ số không hợp lệ.")
        special = row.get("special")
        if special is not None and (type(special) is not int or not 1 <= special <= (12 if game == "LOTO_5_35" else cfg["universe_size"])):
            raise ValueError("Lịch sử cấu hình chứa số đặc biệt không hợp lệ.")
        if game == "LOTO_6_45" and special is not None:
            raise ValueError("Mega không có số đặc biệt.")
        if game == "LOTO_6_55" and special in main:
            raise ValueError("Bóng thứ bảy Power phải khác số chính.")


def predict_profile(game: str, profile_id: str, history: list[dict], ticket_count: int) -> dict:
    """Return a ledger-compatible forecast from exactly the passed history prefix."""
    from ai import adaptive_coverage as coverage, ml_pipeline
    if game not in _GAMES:
        raise ValueError("Game không hỗ trợ cấu hình phòng thử.")
    if type(ticket_count) is not int or not 1 <= ticket_count <= 10:
        raise ValueError("Số vé cấu hình phải trong khoảng 1–10.")
    profile = profile_definition(profile_id)
    history = copy.deepcopy(history)
    _validate_history(game, history)
    cfg = ml_pipeline.game_config(game)
    window = profile["historyWindow"]
    scoring_history = history[-window:] if window else history
    main_probs = _probabilities(scoring_history, cfg["universe_size"], cfg["draw_size"], profile)
    # Loto's DB is a purchased seventh choice. Power's auxiliary prediction is
    # retained for payload compatibility; actual JP2 grading uses purchased six.
    special_probs = (_probabilities(scoring_history, 12, 1, profile, "special") if game == "LOTO_5_35"
                     else {n: 1 / 55 for n in range(1, 56)} if game == "LOTO_6_55" else {})
    cutoff, target = str(history[-1]["ky"]), str(int(history[-1]["ky"]) + 1)
    data_hash = _digest(history)
    # Allocation pairs use the same sampled candidate pool. Only portfolio
    # selection weights vary, allowing their effect to be compared directly.
    scoring_config = {key: profile[key] for key in ("historyWindow", "recentWindow", "weights", "uniformMix", "version")}
    seed = int(_digest({"game": game, "dataHash": data_hash, "target": target,
                        "count": ticket_count, "scoringConfig": scoring_config})[:12], 16) % 2147483647
    candidates, target_count, attempts = coverage._generate_candidates(
        {}, coverage.GAME_SPECS[game], main_probs, special_probs, cfg["draw_size"],
        coverage.candidate_pool_size(ticket_count), random.Random(seed), numpy_seed=seed)
    tickets = coverage._select_portfolio(candidates, ticket_count, cfg["draw_size"],
                                          main_probs, special_probs, profile["allocation"])
    if len(tickets) != ticket_count or any(not math.isfinite(p) for p in main_probs.values()):
        raise RuntimeError("Không tạo được danh mục cấu hình hợp lệ cùng ngân sách.")
    return {"ok": True, "ready": True, "type": game, "engine": "lab_scoring_profile",
            "predictionMode": "normal", "latestKy": cutoff, "nextKy": target,
            "latestDate": history[-1].get("date"), "latestTime": history[-1].get("time"),
            "data_cutoff_draw_id": cutoff, "target_draw_id": target, "dataHash": data_hash,
            "pickSize": cfg["draw_size"], "bundleCount": ticket_count, "tickets": tickets,
            "probabilities": {str(n): p for n, p in main_probs.items()},
            "specialProbabilities": {str(n): p for n, p in special_probs.items()},
            "randomSeed": seed, "modelId": f"profile_{profile_id}_{PROFILE_VERSION}",
            "modelVersion": PROFILE_VERSION, "labProfileId": profile_id,
            "profileDefinition": profile, "configHash": config_hash(profile),
            "probabilityCalibrationStatus": "uncalibrated", "evaluationScope": "main_numbers_only",
            "historyCount": len(history), "scoringHistoryCount": len(scoring_history),
            "allocation": {"policy": profile["allocation"], "candidateCount": len(candidates),
                           "candidateTarget": target_count, "attempts": attempts,
                           **coverage._portfolio_summary(tickets, main_probs)}}
