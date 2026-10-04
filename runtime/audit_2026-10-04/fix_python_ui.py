from pathlib import Path
from backup_fixes import backup, ROOT

def replace(path, old, new, count=1):
    file = ROOT / path
    text = file.read_text(encoding='utf-8-sig')
    if old not in text:
        raise RuntimeError(f'Missing edit anchor: {path}: {old[:80]}')
    file.write_text(text.replace(old, new, count), encoding='utf-8')

extras = ['ai/adaptive_coverage.py'] + [f'ai/standalone_predictors/{g}_predictor/src/feature_engineering.py' for g in ('mega_6_45','power_6_55')]
backup(extras)
for game in ('mega_6_45', 'power_6_55'):
    base = f'ai/standalone_predictors/{game}_predictor/src/'
    replace(base+'feature_engineering.py', '"recent_secondary": recent_secondary,', '"recent_secondary": recent_secondary,\n        "draws": list(draws),')
    replace(base+'deep_model.py', 'draws=list(prediction_context.get("recent_secondary") or []),', 'draws=list(prediction_context.get("draws") or []),')
    replace(base+'deep_dataset.py', 'for index in range(len(draws)):', 'for index in range(len(draws)):', 1) # training unchanged
    file = ROOT / (base+'deep_dataset.py')
    text = file.read_text(encoding='utf-8')
    start = text.index('def build_inference_sample(')
    text = text[:start] + text[start:].replace('for index in range(len(draws)):', 'for index in range(max(0, len(draws) - sequence_length), len(draws)):', 1)
    file.write_text(text, encoding='utf-8')
for game in ('loto_5_35','mega_6_45','power_6_55'):
    path = f'ai/standalone_predictors/{game}_predictor/src/backtest.py'
    replace(path, '"metrics": dict(mode_reports.get("blended") or {}),', '"metrics": dict(mode_reports[winner_mode]),\n        "evaluated_mode": winner_mode,\n        "selection_on_evaluation": True,\n        "mode_metrics": {key: {k: v for k, v in value.items() if k != "folds"} for key, value in mode_reports.items()},')
    if game == 'loto_5_35':
        replace(path, '"retrain_interval": int(retrain_interval or 1),', '"retrain_interval": None,\n        "requested_retrain_interval": retrain_interval,\n        "retraining_policy": "fixed_artifacts_no_fold_retraining",\n        "evaluated_mode": ablation_report["evaluated_mode"],\n        "selection_on_evaluation": True,\n        "mode_metrics": ablation_report["mode_metrics"],')
    else:
        replace(path, 'result["retrain_interval"] = int(retrain_interval or 1)', 'result["retrain_interval"] = None\n    result["requested_retrain_interval"] = retrain_interval\n    result["retraining_policy"] = "fixed_artifacts_no_fold_retraining"')
replace('ai/analysis/analysis.py', '"main_count": 18,', '"main_count": 20,')
replace('ai/adaptive_coverage.py', '"drawSize": 21', '"drawSize": 20')
replace('ai/predictors/ai_predict.py', '"note": "calibratedProbability is a marginal number probability; ticketQualityScore is not a probability.",', '"calibrationStatus": "uncalibrated",\n        "note": "Ước lượng biên từng số chưa hiệu chỉnh ngoài mẫu; không phải xác suất trúng cả vé. Điểm chất lượng không phải xác suất.",')
replace('ai/predictors/ai_predict.py', 'result["calibratedProbability"] = probability_rows', 'result["estimatedProbability"] = probability_rows\n    result["probabilityCalibrationStatus"] = "uncalibrated"\n    # Legacy keys retained for old clients; calibration status is explicit.\n    result["calibratedProbability"] = probability_rows')
replace('frontend/vietlott-web-data.js', 'const hasSpecialColumn = !!TYPES[type]?.hasSpecial || !!TYPES[type]?.threeDigit;\n      return ["Kỳ", "Thứ", "Ngày", "Giờ", "Số",', 'const hasSpecialColumn = !!TYPES[type]?.hasSpecial && !TYPES[type]?.threeDigit;\n      return ["Kỳ", "Thứ", "Ngày", ...(!TYPES[type]?.threeDigit ? ["Giờ"] : []), TYPES[type]?.threeDigit ? "Nhóm giải" : "Bộ số",')
replace('frontend/vietlott-web-data.js', 'draw.time || "",\n          cells.numbers || "",\n          ...((!!TYPES[type]?.hasSpecial || !!TYPES[type]?.threeDigit) ? [cells.special || ""] : []),', '...(!TYPES[type]?.threeDigit ? [draw.time || ""] : []),\n          TYPES[type]?.threeDigit ? [cells.special, cells.numbers].filter(Boolean).join(" | ") : (cells.numbers || ""),\n          ...((!!TYPES[type]?.hasSpecial && !TYPES[type]?.threeDigit) ? [cells.special || ""] : []),')
replace('frontend/vietlott-web-data.js', '<span class="predict-history-info-label">Tổng xác suất</span>', '<span class="predict-history-info-label">Ước lượng chưa hiệu chỉnh</span>')
replace('frontend/vietlott-web-stats.js', '["Nguồn", payload?.sourceFile || "--"],', '["Nguồn", payload?.sourceFile || "--"],\n        ["Phạm vi combo", payload?.comboMode === "keno_window" ? "Cửa sổ số liền nhau sau sắp xếp; không gồm mọi tổ hợp" : "Tổ hợp đầy đủ"],')

# Remember the username only, and erase legacy plaintext credentials on load.
replace('frontend/vietlott-web-core.js', 'const pass = String(parsed.pass || "");\n        if (!user || !pass) return null;\n        return { user, pass };', 'if (!user) { localStorage.removeItem(REMEMBER_KEY); return null; }\n        localStorage.setItem(REMEMBER_KEY, JSON.stringify({ user }));\n        return { user };')
replace('frontend/vietlott-web-core.js', 'function saveRememberedCreds(user, pass) {\n      localStorage.setItem(REMEMBER_KEY, JSON.stringify({ user, pass }));', 'function saveRememberedCreds(user) {\n      localStorage.setItem(REMEMBER_KEY, JSON.stringify({ user: normalizeUser(user) }));')
replace('frontend/vietlott-web-core.js', 'document.getElementById("loginPass").value = rememberedCreds.pass;', 'document.getElementById("loginPass").value = "";')
replace('frontend/vietlott-web-core.js', 'window.setVipMembershipExpiry = setVipMembershipExpiry;', '// VIP expiry is issued and verified by the server.')
replace('frontend/vietlott-web-core.js', 'const nextPass = prompt("Đặt mật khẩu mới cho admin:") || "";', 'setAuthMsg("Khôi phục admin bằng lệnh cục bộ: java LottoWebServer --recover-admin. Mật khẩu được nhập kín trong terminal.", "warn");\n      return;\n      const nextPass = "";')
print('Python and UI fixes applied')
