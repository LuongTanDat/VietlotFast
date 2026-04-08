from __future__ import annotations

import json
from pathlib import Path

from predictor_v2 import config as cfg


def score_candidates(main_numbers, bonus_numbers):
    model_meta_path = Path(cfg.MODEL_META_PATH)
    if not model_meta_path.exists():
        return {
            "available": False,
            "mode": "heuristic_only",
            "modelType": "cnn_gru_scaffold",
            "message": "Chưa có trọng số CNN+GRU, predictor_v2 đang chạy ở chế độ heuristic-only.",
            "mainScores": {int(number): 0.0 for number in main_numbers},
            "bonusScores": {int(number): 0.0 for number in bonus_numbers},
            "regimeHead": {"reset": 0.0, "neutral": 1.0, "continuation": 0.0},
        }
    try:
        meta = json.loads(model_meta_path.read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    scale = float(meta.get("scoreScale", 0.18) or 0.18)
    main_bias = {int(key): float(value) for key, value in dict(meta.get("mainBias") or {}).items()}
    bonus_bias = {int(key): float(value) for key, value in dict(meta.get("bonusBias") or {}).items()}
    return {
        "available": True,
        "mode": "cnn_gru_scaffold",
        "modelType": "cnn_gru_scaffold",
        "message": "Đang dùng scaffold CNN+GRU với bias nhẹ từ model_meta.json.",
        "mainScores": {int(number): max(0.0, min(1.0, float(main_bias.get(int(number), 0.0)) * scale)) for number in main_numbers},
        "bonusScores": {int(number): max(0.0, min(1.0, float(bonus_bias.get(int(number), 0.0)) * scale)) for number in bonus_numbers},
        "regimeHead": {
            "reset": float(meta.get("regimeReset", 0.25) or 0.25),
            "neutral": float(meta.get("regimeNeutral", 0.50) or 0.50),
            "continuation": float(meta.get("regimeContinuation", 0.25) or 0.25),
        },
    }


def incremental_fine_tune(resolved_prediction, actual_draw):
    model_meta_path = Path(cfg.MODEL_META_PATH)
    if not model_meta_path.exists():
        return {
            "updated": False,
            "mode": "heuristic_only",
            "message": "Bỏ qua fine-tune vì chưa có model deep.",
        }
    return {
        "updated": False,
        "mode": "cnn_gru_scaffold",
        "message": "Scaffold deep_model đã nhận hook fine-tune nhưng chưa mở training thực sự trong pass đầu.",
    }
