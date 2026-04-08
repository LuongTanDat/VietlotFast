from __future__ import annotations


def classify_regime(draws, target, tracking_state, config_payload):
    latest = draws[-1] if draws else None
    previous = draws[-2] if len(draws) > 1 else None
    latest_set = set(int(value) for value in list((latest or {}).get("main") or []))
    previous_set = set(int(value) for value in list((previous or {}).get("main") or []))
    overlap = len(latest_set.intersection(previous_set))
    same_day_follow_up = bool(target.get("same_day_follow_up"))

    if same_day_follow_up:
        regime = "reset"
        summary = "Cùng ngày 13:00 -> 21:00 nên predictor ưu tiên reset nhịp, tránh copy cả cụm số vừa ra."
    elif overlap >= 2:
        regime = "continuation"
        summary = "Hai kỳ gần nhất đang còn độ dính đủ mạnh, predictor cho phép giữ nhịp chọn lọc."
    elif overlap == 0:
        regime = "reset"
        summary = "Hai kỳ gần nhất tách nhịp khá rõ, predictor tăng ưu tiên nhóm hồi gap và số đổi pha."
    else:
        regime = "neutral"
        summary = "Nhịp hiện tại trung tính, predictor cân bằng giữa số nóng, số gap và bộ nhớ giữ nhịp."

    kept_numbers = set(int(value) for value in list((tracking_state or {}).get("kept_numbers") or []))
    hot_numbers = set(int(value) for value in list((tracking_state or {}).get("true_hot_numbers") or []))
    same_day_limit = int((config_payload or {}).get("same_day_carry_limit", 1) or 1)

    main_adjustments = {}
    bonus_adjustments = {}
    for number in range(1, 36):
        recent_boost = 1.0 if number in hot_numbers else 0.0
        keep_boost = 1.0 if number in kept_numbers else 0.0
        latest_penalty = 1.0 if number in latest_set else 0.0
        if regime == "continuation":
            score = (recent_boost * 0.65) + (keep_boost * 0.55) - (latest_penalty * 0.10)
        elif regime == "reset":
            score = (1.0 - latest_penalty) * 0.65 + (keep_boost * 0.12) + (recent_boost * 0.18)
            if same_day_follow_up and latest_penalty:
                score -= 0.35 + max(0, len(latest_set) - same_day_limit) * 0.03
        else:
            score = (recent_boost * 0.40) + (keep_boost * 0.30) + ((1.0 - latest_penalty) * 0.30)
        main_adjustments[number] = max(0.0, min(1.0, score))
    for bonus in range(1, 13):
        if regime == "continuation":
            bonus_adjustments[bonus] = 0.62 if bonus in kept_numbers else 0.48
        elif regime == "reset":
            bonus_adjustments[bonus] = 0.35
        else:
            bonus_adjustments[bonus] = 0.50
    return {
        "regime": regime,
        "label": regime.title(),
        "summary": summary,
        "sameDayCarryLimit": same_day_limit,
        "mainAdjustments": main_adjustments,
        "bonusAdjustments": bonus_adjustments,
        "latestOverlap": overlap,
    }
