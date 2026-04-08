from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_TRACKING_STATE = {
    "kept_numbers": [],
    "true_hot_numbers": [],
    "temporary_excluded_numbers": [],
    "memory_scores": {"main": {}},
    "recent_prediction_log": [],
    "updated_at": "",
    "last_resolved_draw_id": None,
}

DEFAULT_MEMORY_ENTRY = {
    "keep_mark_score": 0.0,
    "hot_score": 0.0,
    "miss_penalty_score": 0.0,
    "cooldown_score": 0.0,
    "hit_count": 0,
    "miss_streak": 0,
    "last_outcome": "",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def clone_default_state() -> dict[str, Any]:
    return deepcopy(DEFAULT_TRACKING_STATE)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return deepcopy(default)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_tracking_state(path: str | Path) -> dict[str, Any]:
    payload = read_json(Path(path), DEFAULT_TRACKING_STATE)
    if not isinstance(payload, dict):
        return clone_default_state()
    state = clone_default_state()
    state.update(payload)
    state.setdefault("memory_scores", {}).setdefault("main", {})
    state.setdefault("recent_prediction_log", [])
    return state


def save_tracking_state(path: str | Path, state: dict[str, Any]) -> None:
    write_json(Path(path), state)


def ensure_entry(state: dict[str, Any], number: int) -> dict[str, Any]:
    memory_scores = state.setdefault("memory_scores", {}).setdefault("main", {})
    key = str(int(number))
    entry = memory_scores.get(key)
    if not isinstance(entry, dict):
        entry = deepcopy(DEFAULT_MEMORY_ENTRY)
        memory_scores[key] = entry
    return entry


def read_entry(state: dict[str, Any], number: int) -> dict[str, Any]:
    memory_scores = dict(state.get("memory_scores", {}).get("main", {}) or {})
    entry = memory_scores.get(str(int(number)))
    if isinstance(entry, dict):
        return entry
    return deepcopy(DEFAULT_MEMORY_ENTRY)


def apply_decay(state: dict[str, Any], tracking_config: dict[str, Any]) -> None:
    decay = dict(tracking_config.get("decay") or {})
    for entry in (state.get("memory_scores", {}).get("main", {}) or {}).values():
        entry["keep_mark_score"] = float(entry.get("keep_mark_score", 0.0)) * float(decay.get("keep_mark_score", 0.95))
        entry["hot_score"] = float(entry.get("hot_score", 0.0)) * float(decay.get("hot_score", 0.97))
        entry["miss_penalty_score"] = float(entry.get("miss_penalty_score", 0.0)) * float(decay.get("miss_penalty_score", 0.97))
        entry["cooldown_score"] = float(entry.get("cooldown_score", 0.0)) * float(decay.get("cooldown_score", 0.95))


def get_tracking_score(state: dict[str, Any], number: int) -> float:
    entry = read_entry(state, number)
    raw = (
        0.55 * float(entry.get("keep_mark_score", 0.0))
        + 0.35 * float(entry.get("hot_score", 0.0))
        - 0.30 * float(entry.get("miss_penalty_score", 0.0))
        - 0.22 * float(entry.get("cooldown_score", 0.0))
    )
    return max(0.0, min(1.0, 0.5 + raw / 4.0))


def get_tracking_snapshot(state: dict[str, Any], number: int) -> dict[str, Any]:
    entry = read_entry(state, number)
    return {
        "keep_mark_score": float(entry.get("keep_mark_score", 0.0)),
        "hot_score": float(entry.get("hot_score", 0.0)),
        "miss_penalty_score": float(entry.get("miss_penalty_score", 0.0)),
        "cooldown_score": float(entry.get("cooldown_score", 0.0)),
        "temporary_exclude_flag": int(number) in set(state.get("temporary_excluded_numbers") or []),
        "tracking_score": get_tracking_score(state, number),
    }


def rebuild_indexes(state: dict[str, Any], exclude_after_misses: int = 3) -> dict[str, Any]:
    main_entries = dict(state.get("memory_scores", {}).get("main", {}) or {})
    ranked_keep = sorted(
        main_entries.items(),
        key=lambda item: (
            float(item[1].get("keep_mark_score", 0.0))
            + 0.45 * float(item[1].get("hot_score", 0.0))
            - 0.35 * float(item[1].get("miss_penalty_score", 0.0)),
            -int(item[0]),
        ),
        reverse=True,
    )
    ranked_hot = sorted(
        main_entries.items(),
        key=lambda item: (
            float(item[1].get("hot_score", 0.0))
            + 0.08 * float(item[1].get("hit_count", 0.0))
            - 0.20 * float(item[1].get("miss_penalty_score", 0.0)),
            -int(item[0]),
        ),
        reverse=True,
    )
    ranked_cooldown = sorted(
        main_entries.items(),
        key=lambda item: (
            float(item[1].get("cooldown_score", 0.0))
            + float(item[1].get("miss_penalty_score", 0.0))
            + 0.12 * float(item[1].get("miss_streak", 0.0)),
            int(item[0]),
        ),
        reverse=True,
    )

    state["kept_numbers"] = [int(key) for key, entry in ranked_keep if float(entry.get("keep_mark_score", 0.0)) >= 0.22][:8]
    state["true_hot_numbers"] = [int(key) for key, entry in ranked_hot if float(entry.get("hot_score", 0.0)) >= 0.12][:10]
    state["temporary_excluded_numbers"] = [
        int(key)
        for key, entry in ranked_cooldown
        if float(entry.get("cooldown_score", 0.0)) >= 0.85
        or float(entry.get("miss_penalty_score", 0.0)) >= 0.90
        or int(entry.get("miss_streak", 0)) >= exclude_after_misses
    ][:8]
    state["updated_at"] = now_iso()
    return state


def update_after_actual(
    state: dict[str, Any] | None,
    prediction_payload: dict[str, Any],
    actual_numbers: list[int] | tuple[int, ...],
    tracking_config: dict[str, Any],
    draw_id: int | None = None,
) -> dict[str, Any]:
    next_state = deepcopy(state or DEFAULT_TRACKING_STATE)
    apply_decay(next_state, tracking_config)

    predicted_numbers = [int(value) for value in list(prediction_payload.get("main_ticket") or [])]
    actual_set = {int(value) for value in actual_numbers}
    strong_reward = float(tracking_config.get("strong_reward", 1.35))
    medium_reward = float(tracking_config.get("medium_reward", 0.62))
    small_reward = float(tracking_config.get("small_reward", 0.22))
    success_decay = float(tracking_config.get("success_decay", 0.55))
    miss_penalty = float(tracking_config.get("miss_penalty", 0.32))
    cooldown_increment = float(tracking_config.get("cooldown_increment", 0.24))
    exclude_after_misses = int(tracking_config.get("exclude_after_misses", 3))

    exact_hits: list[int] = []
    near_cluster_hits: list[int] = []
    missed_numbers: list[int] = []

    for number in predicted_numbers:
        entry = ensure_entry(next_state, number)
        if number in actual_set:
            exact_hits.append(number)
            entry["keep_mark_score"] = float(entry.get("keep_mark_score", 0.0)) + strong_reward
            entry["hot_score"] = float(entry.get("hot_score", 0.0)) + medium_reward
            entry["miss_penalty_score"] = float(entry.get("miss_penalty_score", 0.0)) * success_decay
            entry["cooldown_score"] = float(entry.get("cooldown_score", 0.0)) * success_decay
            entry["hit_count"] = int(entry.get("hit_count", 0)) + 1
            entry["miss_streak"] = 0
            entry["last_outcome"] = "exact_hit"
            continue
        if any(abs(number - actual_number) <= 1 for actual_number in actual_set):
            near_cluster_hits.append(number)
            entry["keep_mark_score"] = float(entry.get("keep_mark_score", 0.0)) + small_reward
            entry["hot_score"] = float(entry.get("hot_score", 0.0)) + 0.10
            entry["miss_penalty_score"] = float(entry.get("miss_penalty_score", 0.0)) + 0.06
            entry["last_outcome"] = "near_cluster"
            continue
        missed_numbers.append(number)
        entry["miss_penalty_score"] = float(entry.get("miss_penalty_score", 0.0)) + miss_penalty
        entry["cooldown_score"] = float(entry.get("cooldown_score", 0.0)) + cooldown_increment
        entry["miss_streak"] = int(entry.get("miss_streak", 0)) + 1
        entry["last_outcome"] = "miss"
        if int(entry.get("miss_streak", 0)) >= exclude_after_misses:
            entry["cooldown_score"] = float(entry.get("cooldown_score", 0.0)) + 0.40

    for number in actual_set:
        entry = ensure_entry(next_state, number)
        if number in exact_hits:
            continue
        entry["hot_score"] = float(entry.get("hot_score", 0.0)) + 0.10

    recent_prediction_log = list(next_state.get("recent_prediction_log") or [])
    recent_prediction_log.append(
        {
            "target_draw_id": prediction_payload.get("target_draw_id"),
            "actual_draw_id": draw_id,
            "exact_hits": sorted(exact_hits),
            "near_cluster_hits": sorted(near_cluster_hits),
            "missed_numbers": sorted(missed_numbers),
            "resolved_at": now_iso(),
        }
    )
    next_state["recent_prediction_log"] = recent_prediction_log[-max(10, int(tracking_config.get("max_recent_log", 36))):]
    next_state["last_resolved_draw_id"] = draw_id
    rebuild_indexes(next_state, exclude_after_misses=exclude_after_misses)

    return {
        "next_state": next_state,
        "exact_hit_numbers": sorted(exact_hits),
        "near_cluster_useful_numbers": sorted(near_cluster_hits),
        "missed_numbers": sorted(missed_numbers),
        "numbers_to_keep": [number for number in sorted(exact_hits) if number in set(next_state.get("kept_numbers") or [])],
        "numbers_to_cool_down": [
            number
            for number in sorted(missed_numbers)
            if number in set(next_state.get("temporary_excluded_numbers") or [])
        ],
    }
