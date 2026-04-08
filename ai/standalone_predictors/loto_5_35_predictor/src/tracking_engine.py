from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from src import config as cfg


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _ensure_memory_entry(state, section, number):
    bucket = state.setdefault("memory_scores", {}).setdefault(section, {})
    key = str(int(number))
    entry = bucket.get(key)
    if not isinstance(entry, dict):
        entry = {
            "keep_mark_score": 0.0,
            "hot_score": 0.0,
            "miss_penalty": 0.0,
            "cooldown": 0.0,
            "hit_count": 0,
            "miss_streak": 0,
            "bonus_reward": 0.0,
            "bonus_penalty": 0.0,
            "last_outcome": "",
        }
        bucket[key] = entry
    return entry


def _apply_decay(state, tracking_config):
    decay = dict((tracking_config or {}).get("decay") or {})
    for section in ("main", "bonus"):
        for entry in (state.get("memory_scores", {}).get(section, {}) or {}).values():
            entry["keep_mark_score"] = float(entry.get("keep_mark_score", 0.0)) * float(decay.get("keep", 0.92))
            entry["hot_score"] = float(entry.get("hot_score", 0.0)) * float(decay.get("hot", 0.94))
            entry["miss_penalty"] = float(entry.get("miss_penalty", 0.0)) * float(decay.get("miss", 0.88))
            entry["cooldown"] = float(entry.get("cooldown", 0.0)) * float(decay.get("cooldown", 0.86))
            entry["bonus_reward"] = float(entry.get("bonus_reward", 0.0)) * float(decay.get("bonus_reward", 0.92))
            entry["bonus_penalty"] = float(entry.get("bonus_penalty", 0.0)) * float(decay.get("bonus_penalty", 0.90))


def _rebuild_indexes(state):
    main_entries = state.get("memory_scores", {}).get("main", {}) or {}
    bonus_entries = state.get("memory_scores", {}).get("bonus", {}) or {}
    ranked_keep = sorted(
        main_entries.items(),
        key=lambda item: (
            float(item[1].get("keep_mark_score", 0.0)) + float(item[1].get("hot_score", 0.0)) * 0.45 - float(item[1].get("miss_penalty", 0.0)) * 0.35,
            -int(item[0]),
        ),
        reverse=True,
    )
    ranked_hot = sorted(
        main_entries.items(),
        key=lambda item: (
            float(item[1].get("hot_score", 0.0)) + float(item[1].get("hit_count", 0)) * 0.06 - float(item[1].get("miss_penalty", 0.0)) * 0.2,
            -int(item[0]),
        ),
        reverse=True,
    )
    ranked_excluded = sorted(
        main_entries.items(),
        key=lambda item: (
            float(item[1].get("cooldown", 0.0)) + float(item[1].get("miss_penalty", 0.0)),
            int(item[0]),
        ),
        reverse=True,
    )
    ranked_bonus = sorted(
        bonus_entries.items(),
        key=lambda item: (
            float(item[1].get("bonus_reward", 0.0)) - float(item[1].get("bonus_penalty", 0.0)),
            -int(item[0]),
        ),
        reverse=True,
    )
    state["kept_numbers"] = [int(key) for key, entry in ranked_keep if float(entry.get("keep_mark_score", 0.0)) >= 0.32][:8]
    state["true_hot_numbers"] = [int(key) for key, entry in ranked_hot if float(entry.get("hot_score", 0.0)) >= 0.20][:10]
    state["temporary_excluded_numbers"] = [
        int(key)
        for key, entry in ranked_excluded
        if float(entry.get("cooldown", 0.0)) >= 0.95 or float(entry.get("miss_penalty", 0.0)) >= 0.90
    ][:8]
    state["prioritized_bonus"] = [
        int(key)
        for key, entry in ranked_bonus
        if float(entry.get("bonus_reward", 0.0)) - float(entry.get("bonus_penalty", 0.0)) >= 0.05
    ][:6]
    state["updated_at"] = _now_iso()
    return state


def load_tracking_state():
    return cfg.load_tracking_state()


def save_tracking_state(state):
    cfg.save_tracking_state(state)


def get_tracking_score(state, number, section="main") -> float:
    entry = _ensure_memory_entry(state, section, number)
    positive = float(entry.get("keep_mark_score", 0.0)) * 0.65 + float(entry.get("hot_score", 0.0)) * 0.55
    if section == "bonus":
        positive += float(entry.get("bonus_reward", 0.0)) * 0.70
    negative = float(entry.get("miss_penalty", 0.0)) * 0.50 + float(entry.get("cooldown", 0.0)) * 0.40
    if section == "bonus":
        negative += float(entry.get("bonus_penalty", 0.0)) * 0.65
    raw = max(-2.0, min(2.0, positive - negative))
    return (raw + 2.0) / 4.0


def summarize_tracking_state(state):
    snapshot = deepcopy(state)
    snapshot["recent_prediction_log"] = list(snapshot.get("recent_prediction_log", []) or [])[-8:]
    return snapshot


def update_after_actual(state, prediction_payload, actual_draw, config_payload):
    next_state = deepcopy(state or cfg.DEFAULT_TRACKING_STATE)
    tracking_config = dict((config_payload or {}).get("tracking") or {})
    _apply_decay(next_state, tracking_config)

    actual_main = set(int(value) for value in list((actual_draw or {}).get("main") or []))
    actual_special = actual_draw.get("special")
    predicted_main = [int(value) for value in list((prediction_payload or {}).get("main_ticket") or [])]
    predicted_bonus = prediction_payload.get("bonus")

    exclude_after_misses = int(tracking_config.get("exclude_after_misses", 3) or 3)
    hits = []
    near_hits = []
    misses = []
    for number in predicted_main:
        entry = _ensure_memory_entry(next_state, "main", number)
        if number in actual_main:
            hits.append(number)
            entry["keep_mark_score"] = float(entry.get("keep_mark_score", 0.0)) + 1.35
            entry["hot_score"] = float(entry.get("hot_score", 0.0)) + 0.72
            entry["miss_penalty"] = max(0.0, float(entry.get("miss_penalty", 0.0)) - 0.45)
            entry["cooldown"] = max(0.0, float(entry.get("cooldown", 0.0)) - 0.40)
            entry["hit_count"] = int(entry.get("hit_count", 0)) + 1
            entry["miss_streak"] = 0
            entry["last_outcome"] = "exact_hit"
            continue
        if any(abs(number - actual_number) <= 1 for actual_number in actual_main):
            near_hits.append(number)
            entry["keep_mark_score"] = float(entry.get("keep_mark_score", 0.0)) + 0.28
            entry["hot_score"] = float(entry.get("hot_score", 0.0)) + 0.10
            entry["miss_penalty"] = float(entry.get("miss_penalty", 0.0)) + 0.06
            entry["miss_streak"] = max(0, int(entry.get("miss_streak", 0)))
            entry["last_outcome"] = "near_hit"
            continue
        misses.append(number)
        entry["miss_penalty"] = float(entry.get("miss_penalty", 0.0)) + 0.34
        entry["cooldown"] = float(entry.get("cooldown", 0.0)) + 0.22
        entry["miss_streak"] = int(entry.get("miss_streak", 0)) + 1
        entry["last_outcome"] = "miss"
        if entry["miss_streak"] >= exclude_after_misses:
            entry["cooldown"] = float(entry.get("cooldown", 0.0)) + 0.55

    for number in actual_main:
        if number in hits:
            continue
        entry = _ensure_memory_entry(next_state, "main", number)
        entry["hot_score"] = float(entry.get("hot_score", 0.0)) + 0.18

    if isinstance(predicted_bonus, int):
        bonus_entry = _ensure_memory_entry(next_state, "bonus", predicted_bonus)
        if isinstance(actual_special, int) and predicted_bonus == int(actual_special):
            bonus_entry["bonus_reward"] = float(bonus_entry.get("bonus_reward", 0.0)) + 1.15
            bonus_entry["bonus_penalty"] = max(0.0, float(bonus_entry.get("bonus_penalty", 0.0)) - 0.15)
            bonus_entry["miss_streak"] = 0
            bonus_entry["last_outcome"] = "bonus_hit"
        else:
            bonus_entry["bonus_penalty"] = float(bonus_entry.get("bonus_penalty", 0.0)) + 0.14
            bonus_entry["miss_streak"] = int(bonus_entry.get("miss_streak", 0)) + 1
            bonus_entry["last_outcome"] = "bonus_miss"
    if isinstance(actual_special, int):
        actual_bonus_entry = _ensure_memory_entry(next_state, "bonus", int(actual_special))
        actual_bonus_entry["bonus_reward"] = float(actual_bonus_entry.get("bonus_reward", 0.0)) + 0.12

    recent_log = list(next_state.get("recent_prediction_log", []) or [])
    recent_log.append(
        {
            "target_draw_id": str((prediction_payload or {}).get("target_draw_id", "")),
            "target_slot": str((prediction_payload or {}).get("target_slot", "")),
            "actual_draw_id": str((actual_draw or {}).get("ky", "")),
            "actual_slot": str((actual_draw or {}).get("slot", "")),
            "hits": sorted(hits),
            "near_hits": sorted(near_hits),
            "misses": sorted(misses),
            "actual_main": sorted(actual_main),
            "actual_special": int(actual_special) if isinstance(actual_special, int) else None,
            "resolved_at": _now_iso(),
        }
    )
    next_state["recent_prediction_log"] = recent_log[-max(10, int(tracking_config.get("max_recent_log", 30) or 30)) :]
    next_state["last_resolved_actual_ky"] = str((actual_draw or {}).get("ky", ""))
    return _rebuild_indexes(next_state)
