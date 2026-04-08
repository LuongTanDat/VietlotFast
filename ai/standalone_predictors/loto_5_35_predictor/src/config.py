from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
STATE_DIR = PROJECT_ROOT / "state"
DATA_DIR = PROJECT_ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
MODELS_DIR = PROJECT_ROOT / "models"
TRACKING_STATE_PATH = STATE_DIR / "tracking_state.json"
LAST_PREDICTION_PATH = STATE_DIR / "last_prediction.json"
METRICS_PATH = STATE_DIR / "metrics.json"
CONFIG_PATH = CONFIG_DIR / "predictor_config.json"
FEATURE_FLAGS_PATH = CONFIG_DIR / "feature_flags.json"
COLUMN_MAPPING_PATH = CONFIG_DIR / "column_mapping.json"
MODEL_META_PATH = MODELS_DIR / "model_meta.json"
PREDICTOR_VERSION = "loto_5_35_vip_v1"
PREDICTOR_ENGINE = "loto_5_35_vip"
PREDICTOR_LABEL = "Loto 5/35 Vip Adaptive"

DEFAULT_TRACKING_STATE = {
    "version": PREDICTOR_VERSION,
    "game": "loto_5_35",
    "kept_numbers": [],
    "true_hot_numbers": [],
    "temporary_excluded_numbers": [],
    "prioritized_bonus": [],
    "memory_scores": {
        "main": {},
        "bonus": {},
    },
    "recent_prediction_log": [],
    "last_resolved_actual_ky": "",
    "updated_at": "",
}

DEFAULT_LAST_PREDICTION = {
    "version": PREDICTOR_VERSION,
    "game": "loto_5_35",
    "resolved": True,
    "target_draw_id": "",
    "target_slot": "",
    "created_at": "",
    "resolved_at": "",
}

DEFAULT_CONFIG = {
    "game": "loto_5_35",
    "label": "Loto_5/35",
    "main_count": 5,
    "main_min": 1,
    "main_max": 35,
    "bonus_min": 1,
    "bonus_max": 12,
    "default_csv_path": "data/loto_5_35.csv",
    "time_slots": ["13:00", "21:00"],
    "same_day_carry_limit": 1,
    "recent_windows": {
        "main": [6, 12, 24, 48],
        "bonus": [8, 16, 32],
    },
    "history_limits": {
        "slot": 24,
        "weekday": 18,
        "pair": 96,
        "anti_pair": 48,
        "backtest_samples": 18,
    },
    "candidate_pool": {
        "main": 14,
        "bonus": 6,
        "backup_min": 2,
        "backup_max": 5,
        "candidate_tickets": 16,
    },
    "heuristic_weights": {
        "main": {
            "recent": 0.28,
            "slot": 0.16,
            "weekday": 0.10,
            "modulo": 0.12,
            "pair": 0.10,
            "gap": 0.08,
            "position": 0.08,
            "overlap": 0.08,
        },
        "bonus": {
            "recent": 0.32,
            "slot": 0.20,
            "weekday": 0.14,
            "modulo": 0.12,
            "gap": 0.10,
            "overlap": 0.12,
        },
    },
    "blend_mode_default": "blended",
    "blend_profiles": {
        "heuristic_only": {
            "main": {"heuristic": 0.40, "deep": 0.00, "tracking": 0.15, "regime": 0.10},
            "bonus": {"heuristic": 0.35, "deep": 0.00, "tracking": 0.20, "regime": 0.10},
        },
        "deep_only": {
            "main": {"heuristic": 0.00, "deep": 1.00, "tracking": 0.00, "regime": 0.00},
            "bonus": {"heuristic": 0.00, "deep": 1.00, "tracking": 0.00, "regime": 0.00},
        },
        "blended": {
            "main": {"heuristic": 0.32, "deep": 0.42, "tracking": 0.16, "regime": 0.10},
            "bonus": {"heuristic": 0.23, "deep": 0.47, "tracking": 0.20, "regime": 0.10},
        },
    },
    "blend_weights": {
        "main": {"heuristic": 0.32, "deep": 0.42, "tracking": 0.16, "regime": 0.10},
        "bonus": {"heuristic": 0.23, "deep": 0.47, "tracking": 0.20, "regime": 0.10},
    },
    "ticket_weights": {
        "sumBalance": 0.08,
        "parityBalance": 0.05,
        "modulo3Balance": 0.05,
        "modulo5Pattern": 0.04,
        "tailPattern": 0.04,
        "pairCompatibility": 0.08,
        "antiPairPenalty": -0.08,
        "positionPlausibility": 0.06,
        "rangeScore": 0.05,
        "hotColdBalance": 0.10,
        "keepReuseScore": 0.08,
        "exclusionPenalty": -0.10,
        "deepTicketSupport": 0.05,
        "bonusSupport": 0.07,
        "regimeFit": 0.09,
        "clusterShiftFit": 0.08,
        "recentAlignment": 0.06,
        "sourceConfidence": 0.07,
    },
    "assembly": {
        "modes": ["heuristic_led", "blended", "deep_led", "regime_shift", "conservative"],
        "disagreement_top_n": 8,
        "low_disagreement_threshold": 0.24,
        "high_disagreement_threshold": 0.48,
        "diversity_overlap_limit": 3,
        "mode_bias": {
            "heuristic_led": 0.99,
            "blended": 1.03,
            "deep_led": 1.05,
            "regime_shift": 1.01,
            "conservative": 0.99,
        },
        "main_mode_allowlist_when_high_disagreement": ["heuristic_led", "blended", "deep_led", "regime_shift"],
    },
    "tracking": {
        "decay": {
            "keep": 0.92,
            "hot": 0.94,
            "miss": 0.88,
            "cooldown": 0.86,
            "bonus_reward": 0.92,
            "bonus_penalty": 0.90,
        },
        "exclude_after_misses": 3,
        "max_recent_log": 30,
    },
    "deep_training": {
        "sequence_length": 10,
        "min_samples_required_for_deep": 120,
        "epochs": 24,
        "batch_size": 32,
        "learning_rate": 0.003,
        "weight_decay": 0.0001,
        "validation_ratio": 0.18,
        "early_stopping_patience": 5,
        "early_stopping_min_delta": 0.0005,
        "conv_channels": 16,
        "hidden_size": 24,
        "shared_size": 32,
        "kernel_size": 3,
        "seed": 20260403,
        "retrain_every_n_draws": 6,
        "fine_tune_enabled": True,
        "fine_tune_epochs": 6,
    },
}

DEFAULT_FEATURE_FLAGS = {
    "heuristic_first": True,
    "deep_model_scaffold": True,
    "deep_model_enabled": True,
    "slot_bias": True,
    "weekday_bias": True,
    "tracking_memory": True,
    "ticket_quality": True,
}

DEFAULT_COLUMN_MAPPING = {
    "draw_id": ["Kỳ", "Ky"],
    "weekday_text": ["Thứ", "Thu"],
    "draw_date": ["Ngày", "Ngay"],
    "draw_time": ["Giờ", "Time", "Thời Gian"],
    "main_numbers_raw": ["Bộ Số", "Main", "Numbers"],
    "bonus_raw": ["ĐB", "Special"],
    "display_text": ["Hiển thị", "DisplayLines"],
    "game_label": ["Loại", "Label"],
    "source_url": ["Link cập nhật", "SourceUrl"],
    "source_date": ["Ngày cập nhật", "SourceDate"],
}


def ensure_directories() -> None:
    for path in (CONFIG_DIR, STATE_DIR, DATA_DIR, PROCESSED_DIR, MODELS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def _deep_merge(base, override):
    if not isinstance(base, dict) or not isinstance(override, dict):
        return deepcopy(override)
    merged = deepcopy(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def read_json(path: Path, default):
    ensure_directories()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return deepcopy(default)
    if isinstance(default, dict) and isinstance(payload, dict):
        return _deep_merge(default, payload)
    return payload if payload is not None else deepcopy(default)


def write_json(path: Path, payload) -> None:
    ensure_directories()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config():
    return read_json(CONFIG_PATH, DEFAULT_CONFIG)


def load_tracking_state():
    return read_json(TRACKING_STATE_PATH, DEFAULT_TRACKING_STATE)


def save_tracking_state(payload) -> None:
    write_json(TRACKING_STATE_PATH, payload)


def load_last_prediction():
    return read_json(LAST_PREDICTION_PATH, DEFAULT_LAST_PREDICTION)


def save_last_prediction(payload) -> None:
    write_json(LAST_PREDICTION_PATH, payload)


def load_metrics():
    return read_json(METRICS_PATH, {})


def save_metrics(payload) -> None:
    write_json(METRICS_PATH, payload)


def load_feature_flags():
    return read_json(FEATURE_FLAGS_PATH, DEFAULT_FEATURE_FLAGS)


def load_column_mapping():
    return read_json(COLUMN_MAPPING_PATH, DEFAULT_COLUMN_MAPPING)
