from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[3]
STATE_DIR = PROJECT_ROOT / "state"
TRACKING_STATE_PATH = STATE_DIR / "predictor_v2_tracking_state.json"
LAST_PREDICTION_PATH = STATE_DIR / "predictor_v2_last_prediction.json"
CONFIG_PATH = STATE_DIR / "predictor_v2_config.json"
RUNTIME_LOG_DIR = REPO_ROOT / "runtime" / "logs" / "predictor_v2"
RUNTIME_MODEL_DIR = REPO_ROOT / "runtime" / "models" / "predictor_v2"
MODEL_META_PATH = RUNTIME_MODEL_DIR / "model_meta.json"

DEFAULT_TRACKING_STATE = {
    "version": "predictor_v2",
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
    "version": "predictor_v2",
    "game": "loto_5_35",
    "resolved": True,
    "target_draw_id": "",
    "target_slot": "",
    "created_at": "",
    "resolved_at": "",
}

DEFAULT_CONFIG = {
    "game": "loto_5_35",
    "main_count": 5,
    "main_min": 1,
    "main_max": 35,
    "bonus_min": 1,
    "bonus_max": 12,
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
    "blend_weights": {
        "main": {"heuristic": 0.40, "deep": 0.35, "tracking": 0.15, "regime": 0.10},
        "bonus": {"heuristic": 0.35, "deep": 0.35, "tracking": 0.20, "regime": 0.10},
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
}


def ensure_directories() -> None:
    for path in (STATE_DIR, RUNTIME_LOG_DIR, RUNTIME_MODEL_DIR):
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
