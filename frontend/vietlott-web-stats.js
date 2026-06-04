    function mergeUniquePredictionNumbers(primary, secondary = [], limit = 20) {
      const merged = [];
      const seen = new Set();
      const sources = [Array.isArray(primary) ? primary : [], Array.isArray(secondary) ? secondary : []];
      let cursor = 0;
      while (merged.length < limit) {
        let pushed = false;
        for (const source of sources) {
          if (cursor >= source.length) continue;
          const value = Number(source[cursor]);
          if (Number.isInteger(value) && !seen.has(value)) {
            seen.add(value);
            merged.push(value);
            pushed = true;
            if (merged.length >= limit) break;
          }
        }
        cursor += 1;
        if (!pushed && cursor > Math.max(...sources.map(source => source.length), 0)) break;
      }
      return merged;
    }

    function buildBaoPredictionTickets(type, bundleCount, baoLevel, topRanking = [], topSpecialRanking = [], regularTickets = []) {
      const t = TYPES[type];
      const baseLevel = Number(baoLevel || 0);
      if (!t || t.keno || !Number.isInteger(baseLevel) || baseLevel <= t.mainCount) return [];
      const candidatePool = mergeUniquePredictionNumbers(
        topRanking,
        regularTickets.flatMap(ticket => Array.isArray(ticket?.main) ? ticket.main : []),
        Math.min(t.mainMax, Math.max(baseLevel + 10, baseLevel * 3))
      );
      const allCandidates = candidatePool.length >= baseLevel ? candidatePool : range(t.mainMin, t.mainMax);
      const specialPool = Array.isArray(topSpecialRanking) && topSpecialRanking.length
        ? topSpecialRanking.map(Number).filter(Number.isInteger)
        : regularTickets.map(ticket => Number(ticket?.special)).filter(Number.isInteger);
      const tickets = [];
      for (let index = 0; index < bundleCount; index++) {
        const rotated = allCandidates.slice(index).concat(allCandidates.slice(0, index));
        let picked = [];
        for (const value of rotated) {
          const number = Number(value);
          if (!Number.isInteger(number) || picked.includes(number)) continue;
          picked.push(number);
          if (picked.length >= baseLevel) break;
        }
        if (picked.length < baseLevel) {
          for (const number of range(t.mainMin, t.mainMax)) {
            if (!picked.includes(number)) picked.push(number);
            if (picked.length >= baseLevel) break;
          }
        }
        picked = picked.slice(0, baseLevel).sort((a, b) => a - b);
        const special = t.hasSpecial
          ? (Number.isInteger(Number(specialPool[index % Math.max(1, specialPool.length)]))
            ? Number(specialPool[index % Math.max(1, specialPool.length)])
            : (Number.isInteger(Number(regularTickets[index]?.special)) ? Number(regularTickets[index].special) : null))
          : null;
        tickets.push({
          main: picked,
          special,
          playMode: "bao",
          baoLevel: baseLevel,
        });
      }
      return tickets;
    }

    function clampMetaScore(value) {
      return Math.max(0, Math.min(1, Number(value || 0) || 0));
    }

    function formatMetaPercent(value) {
      return `${(clampMetaScore(value) * 100).toFixed(2)}%`;
    }

    function computeAiGenMetaScore(result, type) {
      const backtest = result?.backtest || {};
      const recentRate = Number(backtest?.recentAvgHitRate ?? backtest?.avgHitRate ?? result?.confidence ?? 0);
      const avgRate = Number(backtest?.avgHitRate ?? 0);
      const confidence = Number(result?.confidence ?? 0);
      const agreement = Number(backtest?.agreementScore ?? result?.model?.agreementScore ?? 0);
      const cooldownPenalty = Number(backtest?.cooldownPenalty ?? result?.model?.cooldownPenalty ?? 1);
      const rawScore = (
        recentRate * 0.42 +
        avgRate * 0.18 +
        confidence * 0.24 +
        agreement * 0.16
      ) * Math.max(0.72, Math.min(1.05, cooldownPenalty || 1));
      const score = clampMetaScore(rawScore);
      const reason = backtest?.recentAvgHitRate
        ? `AI Gen đang nhỉnh hơn ở recent backtest ${(Number(backtest.recentAvgHitRate) * 100).toFixed(2)}%`
        : `AI Gen đang được giữ nhờ confidence ${formatMetaPercent(confidence)}`;
      return {
        key: "gen_local",
        label: "AI Gen",
        score,
        reason,
      };
    }

    function getResultRiskMode(result, fallback = "balanced") {
      return normalizePredictRiskMode(result?.riskMode || fallback);
    }

    function getRiskModeQuotaConfig(type, riskMode) {
      const normalized = normalizePredictRiskMode(riskMode);
      const isKeno = type === "KENO";
      if (normalized === "stable") {
        return {
          key: normalized,
          label: "Ổn Định",
          summary: "Meta đang ưu tiên giữ nhịp và giảm dao động giữa 2 engine.",
          tieThreshold: isKeno ? 0.06 : 0.035,
          scoreExponent: 0.95,
          minShare: 0.35,
          maxShare: 0.65,
          preferredBoost: 0.015,
        };
      }
      if (normalized === "aggressive") {
        return {
          key: normalized,
          label: "Tấn Công",
          summary: "Meta đang mở rộng cửa cho tín hiệu nóng và quota co giãn mạnh hơn.",
          tieThreshold: isKeno ? 0.02 : 0.012,
          scoreExponent: 1.32,
          minShare: 0.15,
          maxShare: 0.85,
          preferredBoost: 0.04,
        };
      }
      return {
        key: "balanced",
        label: "Cân Bằng",
        summary: "Meta đang giữ cân bằng giữa độ ổn định và cơ hội bùng nhịp.",
        tieThreshold: isKeno ? 0.04 : 0.02,
        scoreExponent: 1,
        minShare: 0.25,
        maxShare: 0.75,
        preferredBoost: 0.025,
      };
    }

    function getMetaStabilityBias(result) {
      const stabilityScore = Number(result?.stabilityScore ?? result?.backtest?.stabilityScore ?? result?.confidence ?? 0);
      const metaTrust = Number(result?.metaTrust || 0);
      const confidence = Number(result?.confidence || 0);
      const blend = Math.max(0, Math.min(1, (stabilityScore * 0.55) + (metaTrust * 0.3) + (confidence * 0.15)));
      return Number.isFinite(blend) ? blend : 0;
    }

    function computeLuanSoMetaScore(result, type) {
      const signal = result?.signalSummary || {};
      const champion = result?.champion || result?.model || {};
      const confidence = Number(result?.confidence ?? 0);
      const adaptiveScore = Number(champion?.adaptiveScore ?? confidence ?? 0);
      const strongPairs = Number(signal?.strongPairCount ?? champion?.strongPairs ?? 0);
      const watchPairs = Number(signal?.watchPairCount ?? champion?.watchPairs ?? 0);
      const topSupport = Number(champion?.topSupport ?? 0);
      const topPairCount = Number(champion?.topPairCount ?? 0);
      const strongNorm = Math.min(1, strongPairs / (type === "KENO" ? 40 : 24));
      const watchNorm = Math.min(1, watchPairs / (type === "KENO" ? 24 : 12));
      const supportNorm = Math.min(1, topSupport / (type === "KENO" ? 220 : 80));
      const pairNorm = Math.min(1, topPairCount / (type === "KENO" ? 60 : 22));
      const score = clampMetaScore(
        confidence * 0.36 +
        adaptiveScore * 0.28 +
        strongNorm * 0.18 +
        watchNorm * 0.06 +
        supportNorm * 0.07 +
        pairNorm * 0.05
      );
      const reason = `Luận Số đang mạnh ở adaptive score ${formatMetaPercent(adaptiveScore)} và cặp Strong ${strongPairs}`;
      return {
        key: "luan_so",
        label: "Luận Số",
        score,
        reason,
      };
    }

    function buildBothMetaSelection(type, bundleCount, luanSoResult, aiGenResult, riskMode = "balanced") {
      const pools = {
        luan_so: Array.isArray(luanSoResult?.tickets) ? luanSoResult.tickets : [],
        gen_local: Array.isArray(aiGenResult?.tickets) ? aiGenResult.tickets : [],
      };
      const available = {
        luan_so: pools.luan_so.length,
        gen_local: pools.gen_local.length,
      };
      const riskModeMeta = getRiskModeQuotaConfig(type, riskMode);
      const scores = {
        luan_so: available.luan_so ? computeLuanSoMetaScore(luanSoResult, type) : { key: "luan_so", label: "Luận Số", score: 0, reason: "Luận Số không trả đủ dữ liệu." },
        gen_local: available.gen_local ? computeAiGenMetaScore(aiGenResult, type) : { key: "gen_local", label: "AI Gen", score: 0, reason: "AI Gen không trả đủ dữ liệu." },
      };
      const validKeys = Object.keys(available).filter(key => available[key] > 0);
      if (!validKeys.length) {
        return {
          preferredEngine: "",
          scores,
          quota: { luan_so: 0, gen_local: 0 },
          summary: `${riskModeMeta.summary} Không có engine nào trả về bộ số hợp lệ.`,
          reasons: ["Luận Số và AI Gen đều chưa trả được vé hợp lệ."],
          riskMode: riskModeMeta.key,
          riskModeLabel: riskModeMeta.label,
          riskModeSummary: riskModeMeta.summary,
        };
      }
      if (validKeys.length === 1) {
        const onlyKey = validKeys[0];
        return {
          preferredEngine: onlyKey,
          scores,
          quota: {
            luan_so: onlyKey === "luan_so" ? Math.min(bundleCount, available.luan_so) : 0,
            gen_local: onlyKey === "gen_local" ? Math.min(bundleCount, available.gen_local) : 0,
          },
          summary: `${riskModeMeta.summary} ${scores[onlyKey].label} đang gánh toàn bộ lượt vì engine còn lại chưa đủ dữ liệu hoặc lỗi.`,
          reasons: [scores[onlyKey].reason],
          riskMode: riskModeMeta.key,
          riskModeLabel: riskModeMeta.label,
          riskModeSummary: riskModeMeta.summary,
        };
      }
      let luanScore = Math.max(0.0001, scores.luan_so.score || 0);
      let aiScore = Math.max(0.0001, scores.gen_local.score || 0);
      if (riskModeMeta.key === "stable") {
        luanScore *= 0.82 + (getMetaStabilityBias(luanSoResult) * 0.22);
        aiScore *= 0.82 + (getMetaStabilityBias(aiGenResult) * 0.22);
      }
      const weightedLuan = Math.pow(luanScore, riskModeMeta.scoreExponent);
      const weightedAi = Math.pow(aiScore, riskModeMeta.scoreExponent);
      const scoreTotal = weightedLuan + weightedAi;
      const preferredEngine = luanScore >= aiScore ? "luan_so" : "gen_local";
      const scoreGap = Math.abs(luanScore - aiScore);
      const isNearTie = scoreGap < riskModeMeta.tieThreshold;
      let quotaLuan = 0;
      let quotaAi = 0;
      if (bundleCount <= 1) {
        if (preferredEngine === "luan_so") quotaLuan = Math.min(1, available.luan_so);
        else quotaAi = Math.min(1, available.gen_local);
      } else {
        quotaLuan = Math.min(1, available.luan_so);
        quotaAi = Math.min(1, available.gen_local);
        let remaining = Math.max(0, bundleCount - quotaLuan - quotaAi);
        let targetLuan = isNearTie ? 0.5 : (weightedLuan / Math.max(0.0001, scoreTotal));
        targetLuan = Math.max(riskModeMeta.minShare, Math.min(riskModeMeta.maxShare, targetLuan));
        if (!isNearTie) {
          if (preferredEngine === "luan_so") targetLuan = Math.min(riskModeMeta.maxShare, targetLuan + riskModeMeta.preferredBoost);
          else targetLuan = Math.max(riskModeMeta.minShare, targetLuan - riskModeMeta.preferredBoost);
        }
        const desiredLuan = remaining * targetLuan;
        const extraLuanBase = Math.floor(desiredLuan);
        const extraAiBase = remaining - extraLuanBase;
        quotaLuan += Math.min(extraLuanBase, Math.max(0, available.luan_so - quotaLuan));
        quotaAi += Math.min(extraAiBase, Math.max(0, available.gen_local - quotaAi));
        remaining = bundleCount - quotaLuan - quotaAi;
        while (remaining > 0) {
          const luanRoom = available.luan_so - quotaLuan;
          const aiRoom = available.gen_local - quotaAi;
          if (luanRoom <= 0 && aiRoom <= 0) break;
          const firstKey = preferredEngine;
          const secondKey = preferredEngine === "luan_so" ? "gen_local" : "luan_so";
          const tryOrder = isNearTie ? ["luan_so", "gen_local"] : [firstKey, secondKey];
          let assigned = false;
          for (const key of tryOrder) {
            if (key === "luan_so" && luanRoom > 0) {
              quotaLuan += 1;
              assigned = true;
              break;
            }
            if (key === "gen_local" && aiRoom > 0) {
              quotaAi += 1;
              assigned = true;
              break;
            }
          }
          if (!assigned) break;
          remaining -= 1;
        }
      }
      const summary = isNearTie
        ? `${riskModeMeta.summary} Hai engine đang khá sát nhau nên meta giữ phân bổ gần cân bằng.`
        : `${riskModeMeta.summary} ${scores[preferredEngine].label} đang được ưu tiên theo phong độ gần đây.`;
      return {
        preferredEngine,
        scores,
        quota: {
          luan_so: quotaLuan,
          gen_local: quotaAi,
        },
        summary,
        reasons: [
          scores[preferredEngine].reason,
          preferredEngine === "luan_so" ? scores.gen_local.reason : scores.luan_so.reason,
        ].filter(Boolean),
        riskMode: riskModeMeta.key,
        riskModeLabel: riskModeMeta.label,
        riskModeSummary: riskModeMeta.summary,
      };
    }

    function buildSmartInterleavedTickets(bundleCount, ticketPools, metaSelection) {
      const quota = metaSelection?.quota || {};
      const preferred = metaSelection?.preferredEngine === "gen_local" ? "gen_local" : "luan_so";
      const secondary = preferred === "luan_so" ? "gen_local" : "luan_so";
      const remaining = {
        luan_so: Math.max(0, Number(quota.luan_so || 0)),
        gen_local: Math.max(0, Number(quota.gen_local || 0)),
      };
      const indexes = { luan_so: 0, gen_local: 0 };
      const mergedTickets = [];
      const ticketSources = [];
      while (mergedTickets.length < bundleCount) {
        let pushed = false;
        for (const sourceKey of [preferred, secondary]) {
          if ((remaining[sourceKey] || 0) <= 0) continue;
          const nextTicket = ticketPools?.[sourceKey]?.[indexes[sourceKey]++] || null;
          if (!nextTicket) {
            remaining[sourceKey] = 0;
            continue;
          }
          mergedTickets.push(nextTicket);
          ticketSources.push(sourceKey);
          remaining[sourceKey] -= 1;
          pushed = true;
          if (mergedTickets.length >= bundleCount) break;
        }
        if (!pushed) break;
      }
      return { tickets: mergedTickets, ticketSources };
    }

    function mergeBothAiResults(type, bundleCount, luanSoResult, aiGenResult, riskMode = "balanced") {
      const luanPayload = luanSoResult && typeof luanSoResult === "object" ? luanSoResult : {};
      const aiPayload = aiGenResult && typeof aiGenResult === "object" ? aiGenResult : {};
      const metaSelection = buildBothMetaSelection(type, bundleCount, luanSoResult, aiGenResult, riskMode);
      const merged = buildSmartInterleavedTickets(bundleCount, {
        luan_so: Array.isArray(luanPayload?.tickets) ? luanPayload.tickets : [],
        gen_local: Array.isArray(aiPayload?.tickets) ? aiPayload.tickets : [],
      }, metaSelection);
      const luanSignal = luanPayload?.signalSummary || {};
      const preferredLabel = metaSelection?.preferredEngine === "gen_local" ? "AI Gen" : "Luận Số";
      const metaQuota = metaSelection?.quota || { luan_so: 0, gen_local: 0 };
      return {
        ...aiPayload,
        ...luanPayload,
        engine: "both",
        engineLabel: "Cả 2",
        model: {
          key: "both_combo",
          label: "Meta • Luận Số + AI Gen",
          direction: luanSignal?.dominantDirection || "",
          window: Number(luanSignal?.dominantWindow || 0),
        },
        champion: {
          key: "both_combo",
          label: "Meta • Luận Số + AI Gen",
          direction: luanSignal?.dominantDirection || "",
          window: Number(luanSignal?.dominantWindow || 0),
        },
        confidence: Math.max(Number(luanPayload?.confidence || 0), Number(aiPayload?.confidence || 0)),
        historyCount: Math.max(Number(luanPayload?.historyCount || 0), Number(aiPayload?.historyCount || 0)),
        latestKy: String(luanPayload?.latestKy || aiPayload?.latestKy || ""),
        latestDate: String(luanPayload?.latestDate || aiPayload?.latestDate || ""),
        latestTime: String(luanPayload?.latestTime || aiPayload?.latestTime || ""),
        nextKy: String(luanPayload?.nextKy || aiPayload?.nextKy || ""),
        tickets: merged.tickets,
        ticketSources: merged.ticketSources,
        topRanking: mergeUniquePredictionNumbers(luanPayload?.topRanking, aiPayload?.topRanking, 20),
        topSpecialRanking: mergeUniquePredictionNumbers(luanPayload?.topSpecialRanking, aiPayload?.topSpecialRanking, 10),
        notes: [
          metaSelection?.summary || "Chế độ Cả 2 đang phân bổ thông minh giữa Luận Số và AI Gen.",
          metaSelection?.riskModeSummary ? `Chế độ AI: ${metaSelection.riskModeLabel} • ${metaSelection.riskModeSummary}` : "",
          `Meta ưu tiên: ${preferredLabel}.`,
          `Điểm phong độ: Luận Số ${formatMetaPercent(metaSelection?.scores?.luan_so?.score)} • AI Gen ${formatMetaPercent(metaSelection?.scores?.gen_local?.score)}.`,
          `Phân bổ bộ: Luận Số ${Number(metaQuota.luan_so || 0)} bộ • AI Gen ${Number(metaQuota.gen_local || 0)} bộ.`,
          ...(Array.isArray(metaSelection?.reasons) ? metaSelection.reasons.slice(0, 2) : []),
          ...(Array.isArray(luanPayload?.notes) ? luanPayload.notes.slice(0, 1) : []),
          ...(Array.isArray(aiPayload?.notes) ? aiPayload.notes.slice(0, 1) : []),
        ].filter(Boolean),
        signalSummary: luanPayload?.signalSummary || null,
        analysisReport: luanPayload?.analysisReport || null,
        backtest: aiPayload?.backtest || null,
        metaSelectionMode: "smart_interleave",
        metaScores: {
          luan_so: Number(metaSelection?.scores?.luan_so?.score || 0),
          gen_local: Number(metaSelection?.scores?.gen_local?.score || 0),
        },
        metaQuota: {
          luan_so: Number(metaQuota.luan_so || 0),
          gen_local: Number(metaQuota.gen_local || 0),
        },
        metaPreferredEngine: String(metaSelection?.preferredEngine || ""),
        riskMode: String(metaSelection?.riskMode || getResultRiskMode(aiPayload, riskMode)),
        riskModeLabel: String(metaSelection?.riskModeLabel || getPredictRiskModeMeta(riskMode).label),
        riskModeSummary: String(metaSelection?.riskModeSummary || getPredictRiskModeMeta(riskMode).summary),
        metaSummary: [
          metaSelection?.riskModeLabel ? `${metaSelection.riskModeLabel}` : "",
          metaSelection?.summary || "",
          `Ưu tiên ${preferredLabel}`,
          `Luận Số ${Number(metaQuota.luan_so || 0)} bộ • AI Gen ${Number(metaQuota.gen_local || 0)} bộ`,
        ].filter(Boolean).join(" • "),
      };
    }

    function renderPredictEngineChoice() {
      const select = document.getElementById("pdEngine");
      const choiceWrap = document.getElementById("pdEngineChoice");
      if (select) select.value = String(predictEngineValue || "both").trim().toLowerCase() || "both";
      if (!choiceWrap) return;
      const selected = String(predictEngineValue || "both").trim().toLowerCase() || "both";
      choiceWrap.querySelectorAll("[data-pd-engine]").forEach(button => {
        const isActive = String(button.dataset.pdEngine || "").trim().toLowerCase() === selected;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
    }

    function renderPredictRiskModeChoice() {
      const choiceWrap = document.getElementById("pdRiskModeChoice");
      if (!choiceWrap) return;
      const selected = normalizePredictRiskMode(predictRiskModeValue);
      choiceWrap.querySelectorAll("[data-pd-risk-mode]").forEach(button => {
        const modeKey = normalizePredictRiskMode(button.dataset.pdRiskMode);
        const isActive = modeKey === selected;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
    }

    function renderPredictModeTabs() {
      document.querySelectorAll("[data-predict-mode-tab]").forEach(button => {
        const tabMode = normalizePredictionMode(button.dataset.predictModeTab);
        const isActive = tabMode === predictPageModeValue;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
      const normalRoot = document.getElementById("predictRootNormal");
      const vipRoot = document.getElementById("predictRootVip");
      const statsRoot = document.getElementById("predictRootStats");
      const statsV2Root = document.getElementById("predictRootStatsV2");
      const chartsRoot = document.getElementById("predictRootCharts");
      const dashboardRoot = document.getElementById("predictRootDashboard");
      const analysisRoot = document.getElementById("predictRootAnalysis");
      if (normalRoot) normalRoot.hidden = predictPageModeValue !== PREDICTION_MODE_NORMAL;
      if (vipRoot) vipRoot.hidden = predictPageModeValue !== PREDICTION_MODE_VIP;
      if (statsRoot) statsRoot.hidden = predictPageModeValue !== PREDICTION_MODE_STATS;
      if (statsV2Root) statsV2Root.hidden = predictPageModeValue !== PREDICTION_MODE_STATS_V2;
      if (chartsRoot) chartsRoot.hidden = predictPageModeValue !== PREDICTION_MODE_CHARTS;
      if (dashboardRoot) dashboardRoot.hidden = predictPageModeValue !== PREDICTION_MODE_DASHBOARD;
      if (analysisRoot) analysisRoot.hidden = predictPageModeValue !== PREDICTION_MODE_ANALYSIS;
      syncStatsPanelAutoRefreshTimer();
      syncStatsV2AutoRefreshTimer();
      if (predictPageModeValue === PREDICTION_MODE_ANALYSIS) startAnalysisAutoRefresh();
      else stopAnalysisAutoRefresh();
    }

    function getStatsTypeUiMeta(typeKey) {
      const normalized = normalizeStatsType(typeKey);
      const mapping = {
        LOTO_5_35: { label: "5/35", accentClass: "loto535", fullAccentClass: "stats-insight-accent-loto535", chartColor: "#58d89c" },
        LOTO_6_45: { label: "6/45", accentClass: "loto645", fullAccentClass: "stats-insight-accent-loto645", chartColor: "#63c8ff" },
        LOTO_6_55: { label: "6/55", accentClass: "loto655", fullAccentClass: "stats-insight-accent-loto655", chartColor: "#ffb560" },
        KENO: { label: "Keno", accentClass: "keno", fullAccentClass: "stats-insight-accent-keno", chartColor: "#56dfd7" },
        MAX_3D: { label: "3D", accentClass: "max3d", fullAccentClass: "stats-insight-accent-max3d", chartColor: "#ff8a74" },
        MAX_3D_PRO: { label: "3D Pro", accentClass: "max3dpro", fullAccentClass: "stats-insight-accent-max3dpro", chartColor: "#59dfab" },
      };
      return mapping[normalized] || mapping.KENO;
    }

    function renderStatsTypeTabs() {
      const host = document.getElementById("statsTypeSelect");
      if (!host) return;
      statsSelectedType = normalizeStatsType(statsSelectedType);
      host.innerHTML = STATS_TYPE_OPTIONS.map(item => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`).join("");
      host.value = STATS_TYPE_OPTIONS.some(item => item.value === statsSelectedType) ? statsSelectedType : STATS_TYPE_OPTIONS[0]?.value || "KENO";
      if (typeof host.__syncCustomSelect === "function") host.__syncCustomSelect();
    }

    function renderStatsWindowTabs() {
      const host = document.getElementById("statsWindowSelect");
      if (!host) return;
      statsSelectedDayWindow = normalizeStatsDayWindow(statsSelectedDayWindow);
      host.innerHTML = STATS_DAY_WINDOWS.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(STATS_DAY_WINDOW_LABELS[value] || value)}</option>`).join("");
      host.value = STATS_DAY_WINDOWS.includes(statsSelectedDayWindow) ? statsSelectedDayWindow : "30";
      if (typeof host.__syncCustomSelect === "function") host.__syncCustomSelect();
      renderStatsCustomDateRange();
    }

    function formatStatsDateInputValue(dateValue) {
      if (!(dateValue instanceof Date) || Number.isNaN(dateValue.getTime())) return "";
      const year = dateValue.getFullYear();
      const month = String(dateValue.getMonth() + 1).padStart(2, "0");
      const day = String(dateValue.getDate()).padStart(2, "0");
      return `${year}-${month}-${day}`;
    }

    function parseStatsDateInputValue(rawValue, endOfDay = false) {
      const normalized = String(rawValue || "").trim();
      if (!normalized) return null;
      const parts = normalized.split("-");
      if (parts.length !== 3) return null;
      const [year, month, day] = parts.map(Number);
      if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) return null;
      const dateValue = new Date(year, month - 1, day, endOfDay ? 23 : 0, endOfDay ? 59 : 0, endOfDay ? 59 : 0, endOfDay ? 999 : 0);
      return Number.isNaN(dateValue.getTime()) ? null : dateValue;
    }

    function getStatsLatestFeedDate(type) {
      const entries = buildStatsEntriesForFeed(type, getLiveHistoryFeed(type));
      const latestEntry = entries[entries.length - 1] || null;
      const parsed = parseLiveDate(latestEntry?.draw?.date || "");
      return parsed instanceof Date && !Number.isNaN(parsed.getTime()) ? parsed : getSyncedNowDate();
    }

    function ensureStatsCustomDateDefaults() {
      if (statsSelectedDayWindow !== "custom") return;
      const latestDate = getStatsLatestFeedDate(statsSelectedType);
      if (!statsDateTo) {
        statsDateTo = formatStatsDateInputValue(latestDate);
      }
      if (!statsDateFrom) {
        const startDate = new Date(latestDate.getTime());
        startDate.setDate(startDate.getDate() - 29);
        statsDateFrom = formatStatsDateInputValue(startDate);
      }
    }

    function buildStatsCustomRangeLabel() {
      const fromDate = parseStatsDateInputValue(statsDateFrom);
      const toDate = parseStatsDateInputValue(statsDateTo);
      if (fromDate && toDate) {
        const start = fromDate.getTime() <= toDate.getTime() ? fromDate : toDate;
        const end = fromDate.getTime() <= toDate.getTime() ? toDate : fromDate;
        return `${formatLiveDateFromDate(start)} - ${formatLiveDateFromDate(end)}`;
      }
      if (fromDate) return `Từ ${formatLiveDateFromDate(fromDate)}`;
      if (toDate) return `Đến ${formatLiveDateFromDate(toDate)}`;
      return "Khoảng ngày tùy chọn";
    }

    function renderStatsCustomDateRange() {
      const wrap = document.getElementById("statsCustomDateRange");
      const fromInput = document.getElementById("statsDateFrom");
      const toInput = document.getElementById("statsDateTo");
      if (!wrap || !fromInput || !toInput) return;
      const shouldShow = statsSelectedDayWindow === "custom";
      wrap.hidden = !shouldShow;
      if (shouldShow) ensureStatsCustomDateDefaults();
      fromInput.value = String(statsDateFrom || "");
      toInput.value = String(statsDateTo || "");
    }

    function extractThreeDigitTokensFromLines(lines) {
      const out = [];
      (Array.isArray(lines) ? lines : []).forEach(lineText => {
        const matches = String(lineText || "").match(/\b\d{3}\b/g) || [];
        matches.forEach(token => {
          const numeric = Number(token);
          if (Number.isInteger(numeric) && numeric >= 0 && numeric <= 999) out.push(numeric);
        });
      });
      return out;
    }

    function getStatsDisplayLabel(type, value, isSpecial = false) {
      if (TYPES[type]?.threeDigit) return formatPredictNumber(value, type);
      if (isSpecial && TYPES[type]?.hasSpecial) return formatPredictNumber(value, type);
      return formatPredictNumber(value, type);
    }

    function buildStatsFrequencyItems(type, entries, { special = false } = {}) {
      const counts = new Map();
      const typeConfig = TYPES[type] || {};
      if (!typeConfig?.threeDigit) {
        const seedNumbers = special
          ? (typeConfig?.hasSpecial ? range(typeConfig.specialMin, typeConfig.specialMax) : [])
          : range(typeConfig.mainMin, typeConfig.mainMax);
        seedNumbers.forEach(number => {
          counts.set(Number(number), 0);
        });
      }
      if (TYPES[type]?.threeDigit) {
        entries.forEach(entry => {
          extractThreeDigitTokensFromLines(entry.draw?.displayLines).forEach(number => {
            counts.set(number, Number(counts.get(number) || 0) + 1);
          });
        });
      } else if (special) {
        entries.forEach(entry => {
          const value = entry.draw?.special;
          if (Number.isInteger(Number(value))) {
            const specialValue = Number(value);
            counts.set(specialValue, Number(counts.get(specialValue) || 0) + 1);
          }
        });
      } else {
        entries.forEach(entry => {
          (Array.isArray(entry.draw?.main) ? entry.draw.main : []).forEach(value => {
            const number = Number(value);
            if (Number.isInteger(number)) counts.set(number, Number(counts.get(number) || 0) + 1);
          });
        });
      }
      return [...counts.entries()]
        .map(([value, count]) => ({
          value: Number(value),
          count: Number(count || 0),
          label: getStatsDisplayLabel(type, value, special),
        }))
        .sort((a, b) => b.count - a.count || a.value - b.value);
    }

    function buildStatsEntriesForFeed(type, feed) {
      const normalizedType = normalizeStatsType(type);
      const latestKy = Array.isArray(feed?.order) ? feed.order[feed.order.length - 1] || "" : "";
      const cacheKey = [
        normalizedType,
        Array.isArray(feed?.order) ? feed.order.length : 0,
        latestKy,
        feed?.loadedAt || "",
        feed?.countKey || "",
      ].join("|");
      const cached = statsEntriesCache.get(cacheKey);
      if (cached) return cached;
      const entries = (Array.isArray(feed?.order) ? feed.order : [])
        .map(ky => ({ ky, draw: feed?.results?.[ky] }))
        .filter(entry => entry.draw)
        .sort((a, b) => {
          const kyDelta = kySortValue(a.ky) - kySortValue(b.ky);
          if (kyDelta !== 0) return kyDelta;
          const aTime = parseLiveDate(a.draw?.date || "")?.getTime?.() || 0;
          const bTime = parseLiveDate(b.draw?.date || "")?.getTime?.() || 0;
          return aTime - bTime;
        });
      statsEntriesCache.set(cacheKey, entries);
      return entries;
    }

    function filterStatsEntriesByDayWindow(entries, windowKey) {
      const normalizedWindow = normalizeStatsDayWindow(windowKey);
      if (normalizedWindow === "custom") {
        const fromRaw = parseStatsDateInputValue(statsDateFrom, false);
        const toRaw = parseStatsDateInputValue(statsDateTo, true);
        if (!fromRaw && !toRaw) return [...entries];
        let start = fromRaw;
        let end = toRaw;
        if (start && end && start.getTime() > end.getTime()) {
          const swappedStart = parseStatsDateInputValue(statsDateTo, false);
          const swappedEnd = parseStatsDateInputValue(statsDateFrom, true);
          start = swappedStart;
          end = swappedEnd;
        }
        return entries.filter(entry => {
          const parsed = parseLiveDate(entry.draw?.date || "");
          if (!(parsed instanceof Date) || Number.isNaN(parsed.getTime())) return false;
          if (start && parsed.getTime() < start.getTime()) return false;
          if (end && parsed.getTime() > end.getTime()) return false;
          return true;
        });
      }
      if (normalizedWindow === "all") return [...entries];
      const dayCount = Math.max(1, Number(normalizedWindow) || 30);
      const cutoff = getSyncedNowDate();
      cutoff.setHours(0, 0, 0, 0);
      cutoff.setDate(cutoff.getDate() - (dayCount - 1));
      return entries.filter(entry => {
        const parsed = parseLiveDate(entry.draw?.date || "");
        return parsed instanceof Date && !Number.isNaN(parsed.getTime()) && parsed.getTime() >= cutoff.getTime();
      });
    }

    function collectStatsHighlightNumberSetFromTickets(tickets) {
      const values = new Set();
      for (const ticket of (Array.isArray(tickets) ? tickets : [])) {
        for (const raw of (Array.isArray(ticket?.main) ? ticket.main : [])) {
          const numeric = Number(raw);
          if (Number.isInteger(numeric)) values.add(numeric);
        }
      }
      return values;
    }

    function collectStatsHighlightSpecialSetFromTickets(tickets) {
      const values = new Set();
      for (const ticket of (Array.isArray(tickets) ? tickets : [])) {
        const numeric = Number(ticket?.special);
        if (Number.isInteger(numeric)) values.add(numeric);
      }
      return values;
    }

    function collectOrderedHighlightNumbers(primaryValues = [], fallbackValues = [], limit = 10) {
      const ordered = [];
      const seen = new Set();
      const safeLimit = Math.max(1, Number(limit || 0) || 10);
      for (const value of [...primaryValues, ...fallbackValues]) {
        const numeric = Number(value);
        if (!Number.isInteger(numeric) || seen.has(numeric)) continue;
        seen.add(numeric);
        ordered.push(numeric);
        if (ordered.length >= safeLimit) break;
      }
      return new Set(ordered);
    }

    function buildStatsLatestActualNumberSet(type, latestEntry) {
      if (!latestEntry?.draw) return new Set();
      return buildStatsActualNumberSetFromDraw(type, latestEntry.draw);
    }

    function buildStatsActualNumberSetFromDraw(type, draw) {
      if (!draw) return new Set();
      if (TYPES[type]?.threeDigit) {
        return new Set(extractThreeDigitTokensFromLines(draw?.displayLines));
      }
      return new Set(
        (Array.isArray(draw?.main) ? draw.main : [])
          .map(value => Number(value))
          .filter(value => Number.isInteger(value))
      );
    }

    function buildStatsLatestActualSpecialSet(type, latestEntry) {
      if (!TYPES[type]?.hasSpecial || !latestEntry?.draw) return new Set();
      return buildStatsActualSpecialSetFromDraw(type, latestEntry.draw);
    }

    function buildStatsActualSpecialSetFromDraw(type, draw) {
      if (!TYPES[type]?.hasSpecial || !draw) return new Set();
      const specialValue = Number(draw?.special);
      return Number.isInteger(specialValue) ? new Set([specialValue]) : new Set();
    }

    function getStatsLatestPredictionHighlight(type, latestEntry = null) {
      const logs = ensurePredictionLogBucket(type)
        .filter(entry => Array.isArray(entry?.tickets) && entry.tickets.length);
      if (!logs.length) return { entry: null, numbers: new Set() };
      const latestKyValue = kySortValue(latestEntry?.ky) || 0;
      const targetNextKyValue = latestKyValue + 1;
      const preferredLogs = targetNextKyValue
        ? logs.filter(entry => kySortValue(entry?.predictedKy) === targetNextKyValue)
        : [];
      const futureLogs = latestKyValue
        ? logs.filter(entry => !entry?.resolved && kySortValue(entry?.predictedKy) > latestKyValue)
        : [];
      if (targetNextKyValue && !preferredLogs.length && !futureLogs.length) return { entry: null, numbers: new Set() };
      const candidateLogs = preferredLogs.length ? preferredLogs : (futureLogs.length ? futureLogs : logs);
      const sorted = [...candidateLogs].sort((a, b) => {
        const kyDelta = kySortValue(b?.predictedKy) - kySortValue(a?.predictedKy);
        if (kyDelta !== 0) return kyDelta;
        return (Date.parse(String(b?.createdAt || "").trim()) || 0) - (Date.parse(String(a?.createdAt || "").trim()) || 0);
      });
      const entry = sorted[0] || null;
      const highlightLimit = type === "KENO" ? 20 : 10;
      const rankedNumbers = Array.isArray(entry?.topMainRanking)
        ? entry.topMainRanking.map(value => Number(value)).filter(value => Number.isInteger(value))
        : [];
      const usageRanking = Object.entries(buildNumberUsageMap(entry?.tickets || [], "main"))
        .map(([value, count]) => ({ value: Number(value), count: Number(count || 0) }))
        .filter(item => Number.isInteger(item.value))
        .sort((a, b) => b.count - a.count || a.value - b.value)
        .map(item => item.value);
      return {
        entry,
        numbers: collectOrderedHighlightNumbers(rankedNumbers, usageRanking, highlightLimit),
      };
    }

    function buildStatsRecentFallbackPredictionSet(type, { mostItems = [], overdueItems = [] } = {}) {
      if (normalizeStatsType(type) !== "KENO") return new Set();
      const ordered = [];
      const seen = new Set();
      const limit = 20;
      const sources = [mostItems, overdueItems];
      for (let index = 0; ordered.length < limit; index++) {
        let pushed = false;
        for (const source of sources) {
          const item = Array.isArray(source) ? source[index] : null;
          const numeric = Number(item?.value);
          if (!Number.isInteger(numeric) || seen.has(numeric)) continue;
          seen.add(numeric);
          ordered.push(numeric);
          pushed = true;
          if (ordered.length >= limit) break;
        }
        if (!pushed && index > Math.max(...sources.map(source => Array.isArray(source) ? source.length : 0), 0)) break;
      }
      return new Set(ordered);
    }

    function getStatsLatestSpecialPredictionHighlight(type, latestEntry = null) {
      if (!TYPES[type]?.hasSpecial) return { entry: null, numbers: new Set() };
      const logs = ensurePredictionLogBucket(type)
        .filter(entry => Array.isArray(entry?.tickets) && entry.tickets.length);
      if (!logs.length) return { entry: null, numbers: new Set() };
      const targetNextKyValue = (kySortValue(latestEntry?.ky) || 0) + 1;
      const preferredLogs = targetNextKyValue
        ? logs.filter(entry => kySortValue(entry?.predictedKy) === targetNextKyValue)
        : [];
      if (targetNextKyValue && !preferredLogs.length) return { entry: null, numbers: new Set() };
      const candidateLogs = preferredLogs.length ? preferredLogs : logs;
      const sorted = [...candidateLogs].sort((a, b) => {
        const kyDelta = kySortValue(b?.predictedKy) - kySortValue(a?.predictedKy);
        if (kyDelta !== 0) return kyDelta;
        return (Date.parse(String(b?.createdAt || "").trim()) || 0) - (Date.parse(String(a?.createdAt || "").trim()) || 0);
      });
      const entry = sorted[0] || null;
      const rankedSpecials = Array.isArray(entry?.topSpecialRanking)
        ? entry.topSpecialRanking.map(value => Number(value)).filter(value => Number.isInteger(value))
        : [];
      const usageRanking = Object.entries(buildNumberUsageMap(entry?.tickets || [], "special"))
        .map(([value, count]) => ({ value: Number(value), count: Number(count || 0) }))
        .filter(item => Number.isInteger(item.value))
        .sort((a, b) => b.count - a.count || a.value - b.value)
        .map(item => item.value);
      return {
        entry,
        numbers: collectOrderedHighlightNumbers(rankedSpecials, usageRanking, 4),
      };
    }

    function getStatsPredictionLogSortTime(entry) {
      return Date.parse(String(entry?.resolvedAt || entry?.createdAt || "").trim()) || 0;
    }

    function findStatsPredictionLogForKy(type, ky) {
      const normalizedKy = normalizeKy(ky);
      if (!normalizedKy) return null;
      const logs = ensurePredictionLogBucket(type)
        .filter(entry =>
          Array.isArray(entry?.tickets) &&
          entry.tickets.length &&
          (
            normalizeKy(entry?.actualKy) === normalizedKy ||
            normalizeKy(entry?.predictedKy) === normalizedKy ||
            normalizeKy(entry?.predictedKyRepaired) === normalizedKy ||
            normalizeKy(entry?.predictedKyOriginal) === normalizedKy
          )
        );
      if (!logs.length) return null;
      logs.sort((a, b) => {
        const resolvedDelta = Number(!!b?.resolved) - Number(!!a?.resolved);
        if (resolvedDelta !== 0) return resolvedDelta;
        const timeDelta = getStatsPredictionLogSortTime(b) - getStatsPredictionLogSortTime(a);
        if (timeDelta !== 0) return timeDelta;
        return kySortValue(b?.predictedKy) - kySortValue(a?.predictedKy);
      });
      return logs[0] || null;
    }

    function findStatsLatestResolvedPredictionLog(type) {
      const logs = ensurePredictionLogBucket(type)
        .filter(entry =>
          Array.isArray(entry?.tickets) &&
          entry.tickets.length &&
          entry?.resolved &&
          (entry?.actualDraw || entry?.actualKy)
        );
      if (!logs.length) return null;
      logs.sort((a, b) => {
        const kyDelta = kySortValue(b?.actualKy || b?.predictedKy) - kySortValue(a?.actualKy || a?.predictedKy);
        if (kyDelta !== 0) return kyDelta;
        return getStatsPredictionLogSortTime(b) - getStatsPredictionLogSortTime(a);
      });
      return logs[0] || null;
    }

    function getStatsPredictionComparisonContext(type, latestEntry = null, latestActualSet = null, latestActualSpecialSet = null) {
      const latestKy = latestEntry?.ky;
      const directEntry = findStatsPredictionLogForKy(type, latestKy);
      if (directEntry) {
        return {
          entry: directEntry,
          isLatestEntry: true,
          actualSet: latestActualSet instanceof Set ? latestActualSet : buildStatsLatestActualNumberSet(type, latestEntry),
          actualSpecialSet: latestActualSpecialSet instanceof Set ? latestActualSpecialSet : buildStatsLatestActualSpecialSet(type, latestEntry),
          label: "kỳ trước",
        };
      }
      const fallbackEntry = findStatsLatestResolvedPredictionLog(type);
      if (!fallbackEntry) {
        return {
          entry: null,
          isLatestEntry: false,
          actualSet: new Set(),
          actualSpecialSet: new Set(),
          label: "kỳ trước",
        };
      }
      return {
        entry: fallbackEntry,
        isLatestEntry: false,
        actualSet: buildStatsActualNumberSetFromDraw(type, fallbackEntry.actualDraw),
        actualSpecialSet: buildStatsActualSpecialSetFromDraw(type, fallbackEntry.actualDraw),
        label: "kỳ đã chấm",
      };
    }

    function getStatsPredictionMainLimit(type) {
      return normalizeStatsType(type) === "KENO" ? 20 : 10;
    }

    function collectStatsPredictionMainSet(type, entry) {
      const limit = getStatsPredictionMainLimit(type);
      const rankedNumbers = Array.isArray(entry?.topMainRanking)
        ? entry.topMainRanking.map(value => Number(value)).filter(value => Number.isInteger(value))
        : [];
      const usageRanking = Object.entries(buildNumberUsageMap(entry?.tickets || [], "main"))
        .map(([value, count]) => ({ value: Number(value), count: Number(count || 0) }))
        .filter(item => Number.isInteger(item.value))
        .sort((a, b) => b.count - a.count || a.value - b.value)
        .map(item => item.value);
      const predictedSet = collectOrderedHighlightNumbers(rankedNumbers, usageRanking, limit);
      if (predictedSet.size) return predictedSet;
      return collectOrderedHighlightNumbers([...collectStatsHighlightNumberSetFromTickets(entry?.tickets || [])], [], limit);
    }

    function getStatsLatestMissedPredictionSet(type, latestEntry = null, latestActualSet = null) {
      const comparison = getStatsPredictionComparisonContext(type, latestEntry, latestActualSet);
      const previousPrediction = comparison.entry;
      if (!previousPrediction) return new Set();
      const actualSet = comparison.actualSet instanceof Set ? comparison.actualSet : new Set();
      const predictedSet = collectStatsPredictionMainSet(type, previousPrediction);
      const missed = new Set();
      predictedSet.forEach(value => {
        if (!actualSet.has(value)) missed.add(value);
      });
      return missed;
    }

    function getStatsLatestHitPredictionSet(type, latestEntry = null, latestActualSet = null) {
      const comparison = getStatsPredictionComparisonContext(type, latestEntry, latestActualSet);
      const previousPrediction = comparison.entry;
      if (!previousPrediction) return new Set();
      const actualSet = comparison.actualSet instanceof Set ? comparison.actualSet : new Set();
      const predictedSet = collectStatsPredictionMainSet(type, previousPrediction);
      const hits = new Set();
      predictedSet.forEach(value => {
        if (actualSet.has(value)) hits.add(value);
      });
      return hits;
    }

    function getStatsLatestMissedSpecialPredictionSet(type, latestEntry = null, latestActualSpecialSet = null) {
      if (!TYPES[type]?.hasSpecial) return new Set();
      const comparison = getStatsPredictionComparisonContext(type, latestEntry, null, latestActualSpecialSet);
      const previousPrediction = comparison.entry;
      if (!previousPrediction) return new Set();
      const actualSet = comparison.actualSpecialSet instanceof Set ? comparison.actualSpecialSet : new Set();
      const rankedSpecials = Array.isArray(previousPrediction?.topSpecialRanking)
        ? previousPrediction.topSpecialRanking.map(value => Number(value)).filter(value => Number.isInteger(value))
        : [];
      const usageRanking = Object.entries(buildNumberUsageMap(previousPrediction?.tickets || [], "special"))
        .map(([value, count]) => ({ value: Number(value), count: Number(count || 0) }))
        .filter(item => Number.isInteger(item.value))
        .sort((a, b) => b.count - a.count || a.value - b.value)
        .map(item => item.value);
      const predictedSet = collectOrderedHighlightNumbers(rankedSpecials, usageRanking, 4);
      const missed = new Set();
      predictedSet.forEach(value => {
        if (!actualSet.has(value)) missed.add(value);
      });
      return missed;
    }

    function getStatsLatestHitSpecialPredictionSet(type, latestEntry = null, latestActualSpecialSet = null) {
      if (!TYPES[type]?.hasSpecial) return new Set();
      const comparison = getStatsPredictionComparisonContext(type, latestEntry, null, latestActualSpecialSet);
      const previousPrediction = comparison.entry;
      if (!previousPrediction) return new Set();
      const actualSet = comparison.actualSpecialSet instanceof Set ? comparison.actualSpecialSet : new Set();
      const rankedSpecials = Array.isArray(previousPrediction?.topSpecialRanking)
        ? previousPrediction.topSpecialRanking.map(value => Number(value)).filter(value => Number.isInteger(value))
        : [];
      const usageRanking = Object.entries(buildNumberUsageMap(previousPrediction?.tickets || [], "special"))
        .map(([value, count]) => ({ value: Number(value), count: Number(count || 0) }))
        .filter(item => Number.isInteger(item.value))
        .sort((a, b) => b.count - a.count || a.value - b.value)
        .map(item => item.value);
      const predictedSet = collectOrderedHighlightNumbers(rankedSpecials, usageRanking, 4);
      const hits = new Set();
      predictedSet.forEach(value => {
        if (actualSet.has(value)) hits.add(value);
      });
      return hits;
    }

    function getStatsHighlightClass(value, currentTopSet, previousActualSet, missedPredictionSet) {
      const numeric = Number(value);
      const isCurrentTop = Number.isInteger(numeric) && currentTopSet instanceof Set && currentTopSet.has(numeric);
      const isPreviousActual = Number.isInteger(numeric) && previousActualSet instanceof Set && previousActualSet.has(numeric);
      const isMissedPrediction = Number.isInteger(numeric) && missedPredictionSet instanceof Set && missedPredictionSet.has(numeric);
      if (isCurrentTop && isPreviousActual && isMissedPrediction) return "is-current-previous-missed";
      if (isCurrentTop && isPreviousActual) return "is-hit-and-prediction";
      if (isCurrentTop && isMissedPrediction) return "is-current-and-missed";
      if (isPreviousActual && isMissedPrediction) return "is-previous-and-missed";
      if (isMissedPrediction) return "is-missed-prediction";
      if (isCurrentTop) return "is-latest-hit";
      if (isPreviousActual) return "is-next-prediction";
      return "";
    }

    function renderStatsTopGrid(type, items, { currentTopSet = null, previousActualSet = null, missedPredictionSet = null } = {}) {
      return `<div class="stats-insight-top-grid">${items.map((item, index) => `
        <article class="stats-insight-top-item ${getStatsHighlightClass(item?.value, currentTopSet, previousActualSet, missedPredictionSet)}">
          <div class="stats-insight-top-rank">Top ${index + 1}</div>
          <div class="stats-insight-top-number">${escapeHtml(item.label)}</div>
          <div class="stats-insight-top-count">${escapeHtml(`${formatLiveSyncCount(item.count)} lần xuất hiện`)}</div>
        </article>
      `).join("")}</div>`;
    }

    function shouldRenderStatsRankGrid(type) {
      return STATS_SIX_GRID_TYPES.has(type) || type === "KENO";
    }

    function getStatsRankGridClass(type) {
      if (STATS_SIX_GRID_TYPES.has(type)) return "is-six";
      if (type === "KENO") return "is-keno";
      return "";
    }

    function renderStatsRankingGrid(type, items, { currentTopSet = null, previousActualSet = null, missedPredictionSet = null, extraClass = "" } = {}) {
      const gridClass = getStatsRankGridClass(type);
      return `<div class="stats-insight-rank-grid ${gridClass} ${extraClass}">${items.map((item, index) => `
        <article class="stats-insight-rank-card ${getStatsHighlightClass(item?.value, currentTopSet, previousActualSet, missedPredictionSet)}">
          <div class="stats-insight-rank-card-position">#${index + 1}</div>
          <div class="stats-insight-rank-card-number">${escapeHtml(item.label)}</div>
          <div class="stats-insight-rank-card-count">${escapeHtml(`${formatLiveSyncCount(item.count)} lần`)}</div>
        </article>
      `).join("")}</div>`;
    }

    function renderStatsSpecialCompactGrid(type, items, { currentTopSet = null, previousActualSet = null, missedPredictionSet = null } = {}) {
      return `<div class="stats-insight-special-mini-grid">${items.map((item, index) => `
        <article class="stats-insight-rank-card stats-insight-special-mini-card ${getStatsHighlightClass(item?.value, currentTopSet, previousActualSet, missedPredictionSet)}">
          <div class="stats-insight-rank-card-position">#${index + 1}</div>
          <div class="stats-insight-rank-card-number">${escapeHtml(getStatsDisplayLabel(type, item?.value, true))}</div>
          <div class="stats-insight-rank-card-count">${escapeHtml(`${formatLiveSyncCount(item?.count || 0)} lần`)}</div>
        </article>
      `).join("")}</div>`;
    }

    function renderStatsRankingList(type, items, { currentTopSet = null, previousActualSet = null, missedPredictionSet = null } = {}) {
      return `<div class="stats-insight-rank-list">${items.map((item, index) => `
        <div class="stats-insight-rank-row ${getStatsHighlightClass(item?.value, currentTopSet, previousActualSet, missedPredictionSet)}">
          <div class="stats-insight-rank-position">#${index + 1}</div>
          <div class="stats-insight-rank-number">${escapeHtml(item.label)}</div>
          <div class="stats-insight-rank-count">${escapeHtml(`${formatLiveSyncCount(item.count)} lần`)}</div>
        </div>
      `).join("")}</div>`;
    }

    function renderStatsColorLegend(items = []) {
      const safeItems = (Array.isArray(items) ? items : [])
        .filter(item => item?.tone && item?.label);
      if (!safeItems.length) return "";
      return `
        <div class="stats-insight-color-legend" aria-label="Chú thích màu thống kê">
          ${safeItems.map(item => `
            <span
              class="stats-insight-legend-chip"
              tabindex="0"
              aria-label="${escapeHtml(item.label)}"
            >
              <span class="stats-insight-legend-swatch is-${escapeHtml(item.tone)}"></span>
              <span class="stats-insight-legend-text">${escapeHtml(item.label)}</span>
            </span>
          `).join("")}
        </div>
      `;
    }

    function doesStatsEntryContainNumber(type, entry, value, { special = false } = {}) {
      const numeric = Number(value);
      if (!Number.isInteger(numeric) || !entry?.draw) return false;
      if (TYPES[type]?.threeDigit) {
        return extractThreeDigitTokensFromLines(entry.draw?.displayLines).includes(numeric);
      }
      if (special) {
        return Number(entry.draw?.special) === numeric;
      }
      return (Array.isArray(entry.draw?.main) ? entry.draw.main : [])
        .some(item => Number(item) === numeric);
    }

    function buildStatsOverdueItems(type, frequencyItems, entries, { special = false } = {}) {
      const sourceEntries = Array.isArray(entries) ? entries : [];
      return (Array.isArray(frequencyItems) ? frequencyItems : [])
        .map(item => {
          let gap = sourceEntries.length;
          for (let index = sourceEntries.length - 1; index >= 0; index--) {
            if (doesStatsEntryContainNumber(type, sourceEntries[index], item?.value, { special })) {
              gap = sourceEntries.length - 1 - index;
              break;
            }
          }
          return {
            ...item,
            gap,
          };
        })
        .sort((a, b) => b.gap - a.gap || a.count - b.count || a.value - b.value);
    }

    function getStatsRecent100BallClass(value, hitNumberSet = null, missedNumberSet = null, currentPredictionSet = null) {
      const numeric = Number(value);
      const isHitPrediction = Number.isInteger(numeric) && hitNumberSet instanceof Set && hitNumberSet.has(numeric);
      const isMissedPrediction = Number.isInteger(numeric) && missedNumberSet instanceof Set && missedNumberSet.has(numeric);
      const isCurrentPrediction = Number.isInteger(numeric) && currentPredictionSet instanceof Set && currentPredictionSet.has(numeric);
      return [
        isCurrentPrediction ? "is-current-prediction" : "",
        isHitPrediction ? "is-previous-hit" : "",
        isMissedPrediction ? "is-previous-missed" : "",
      ].filter(Boolean).join(" ");
    }

    function normalizeStatsRecentMode(value) {
      const normalized = String(value || "").trim().toLowerCase();
      return STATS_RECENT_MODE_OPTIONS.some(option => option.value === normalized) ? normalized : "draw";
    }

    function getStatsRecentWindowOptions(mode = statsRecentModeValue) {
      return normalizeStatsRecentMode(mode) === "day"
        ? STATS_RECENT_DAY_WINDOW_OPTIONS
        : STATS_RECENT_DRAW_WINDOW_OPTIONS;
    }

    function normalizeStatsRecentWindow(value, mode = statsRecentModeValue) {
      const options = getStatsRecentWindowOptions(mode);
      const normalized = String(value || "").trim().toLowerCase();
      if (normalized === "all" && options.includes("all")) return "all";
      const numeric = Number(normalized);
      return options.includes(numeric) ? numeric : STATS_RECENT_WINDOW_DEFAULT;
    }

    function getStatsRecentWindowLabel(value, mode = statsRecentModeValue) {
      const normalizedMode = normalizeStatsRecentMode(mode);
      const normalizedWindow = normalizeStatsRecentWindow(value, normalizedMode);
      if (normalizedWindow === "all") return "All";
      return `${normalizedWindow} ${normalizedMode === "day" ? "ngày" : "kỳ"}`;
    }

    function getStatsRecentPanelTitle(value, mode = statsRecentModeValue) {
      const normalizedMode = normalizeStatsRecentMode(mode);
      const normalizedWindow = normalizeStatsRecentWindow(value, normalizedMode);
      if (normalizedWindow === "all") {
        return normalizedMode === "day" ? "TẤT CẢ NGÀY GẦN NHẤT" : "TẤT CẢ KỲ XỔ";
      }
      return `${normalizedWindow} ${normalizedMode === "day" ? "NGÀY" : "KỲ"} XỔ GẦN NHẤT`;
    }

    function filterStatsRecentEntriesByMode(entries, mode = statsRecentModeValue, value = statsRecentWindowValue) {
      const safeEntries = Array.isArray(entries) ? entries : [];
      const normalizedMode = normalizeStatsRecentMode(mode);
      const normalizedWindow = normalizeStatsRecentWindow(value, normalizedMode);
      if (normalizedWindow === "all") return [...safeEntries];
      const windowCount = Math.max(1, Number(normalizedWindow) || STATS_RECENT_WINDOW_DEFAULT);
      if (normalizedMode !== "day") return safeEntries.slice(-windowCount);

      let latestDate = null;
      for (let index = safeEntries.length - 1; index >= 0; index--) {
        const parsed = parseLiveDate(safeEntries[index]?.draw?.date || "");
        if (parsed instanceof Date && !Number.isNaN(parsed.getTime())) {
          latestDate = parsed;
          break;
        }
      }
      if (!latestDate) return safeEntries.slice(-windowCount);
      const cutoff = new Date(latestDate.getTime());
      cutoff.setHours(0, 0, 0, 0);
      cutoff.setDate(cutoff.getDate() - (windowCount - 1));
      return safeEntries.filter(entry => {
        const parsed = parseLiveDate(entry?.draw?.date || "");
        return parsed instanceof Date && !Number.isNaN(parsed.getTime()) && parsed.getTime() >= cutoff.getTime();
      });
    }

    function clearStatsRecentComputationCache(type = "") {
      const normalizedType = type ? normalizeStatsType(type) : "";
      if (!normalizedType) {
        statsRecentComputationCache.clear();
        return;
      }
      [...statsRecentComputationCache.keys()].forEach(key => {
        if (String(key).startsWith(`${normalizedType}|`)) statsRecentComputationCache.delete(key);
      });
    }

    function clearStatsEntriesCache(type = "") {
      const normalizedType = type ? normalizeStatsType(type) : "";
      if (!normalizedType) {
        statsEntriesCache.clear();
        return;
      }
      [...statsEntriesCache.keys()].forEach(key => {
        if (String(key).startsWith(`${normalizedType}|`)) statsEntriesCache.delete(key);
      });
    }

    function getStatsRecentEntriesSignature(type, entries, mode = statsRecentModeValue, value = statsRecentWindowValue) {
      const safeEntries = Array.isArray(entries) ? entries : [];
      const latestEntry = safeEntries[safeEntries.length - 1] || null;
      const firstEntry = safeEntries[0] || null;
      return [
        normalizeStatsType(type),
        normalizeStatsRecentMode(mode),
        String(normalizeStatsRecentWindow(value, mode)),
        safeEntries.length,
        firstEntry?.ky || "",
        latestEntry?.ky || "",
        latestEntry?.draw?.date || "",
        latestEntry?.draw?.time || "",
      ].join("|");
    }

    function getStatsRecentGridClass(type) {
      return type === "KENO"
        ? "is-keno"
        : type === "LOTO_5_35"
          ? "is-five"
          : STATS_SIX_GRID_TYPES.has(type)
            ? "is-six"
            : TYPES[type]?.threeDigit ? "is-three-digit" : "";
    }

    function labelStatsRecentItems(type, items, { special = false } = {}) {
      return (Array.isArray(items) ? items : []).map(item => ({
        ...item,
        value: Number(item?.value),
        count: Number(item?.count || 0),
        ...(Object.prototype.hasOwnProperty.call(item || {}, "gap") ? { gap: Number(item?.gap || 0) } : {}),
        label: getStatsDisplayLabel(type, item?.value, special),
      }));
    }

    function normalizeStatsRecentComputation(type, raw) {
      if (!raw || typeof raw !== "object") return null;
      const frequencyItems = labelStatsRecentItems(type, raw.frequencyItems);
      const countPairs = Array.isArray(raw.countPairs)
        ? raw.countPairs
        : frequencyItems.map(item => [Number(item.value), Number(item.count || 0)]);
      return {
        frequencyItems,
        displayItems: labelStatsRecentItems(type, raw.displayItems || (TYPES[type]?.threeDigit ? frequencyItems.slice(0, 100) : frequencyItems)),
        mostItems: labelStatsRecentItems(type, raw.mostItems || frequencyItems.slice(0, STATS_RECENT100_SIDE_LIMIT)),
        leastItems: labelStatsRecentItems(type, raw.leastItems),
        overdueItems: labelStatsRecentItems(type, raw.overdueItems),
        countByValue: new Map(countPairs.map(pair => [Number(pair[0]), Number(pair[1] || 0)])),
      };
    }

    function buildStatsRecentComputationSync(type, sourceEntries, mode = statsRecentModeValue, value = statsRecentWindowValue) {
      const safeEntries = Array.isArray(sourceEntries) ? sourceEntries : [];
      const recentEntries = filterStatsRecentEntriesByMode(safeEntries, mode, value);
      const frequencyItems = buildStatsFrequencyItems(type, recentEntries);
      const displayItems = TYPES[type]?.threeDigit ? frequencyItems.slice(0, 100) : frequencyItems;
      const mostItems = frequencyItems.slice(0, STATS_RECENT100_SIDE_LIMIT);
      const leastItems = [...frequencyItems]
        .sort((a, b) => a.count - b.count || a.value - b.value)
        .slice(0, STATS_RECENT100_SIDE_LIMIT);
      const overdueItems = buildStatsOverdueItems(type, frequencyItems, safeEntries).slice(0, STATS_RECENT100_SIDE_LIMIT);
      return normalizeStatsRecentComputation(type, {
        frequencyItems,
        displayItems,
        mostItems,
        leastItems,
        overdueItems,
        countPairs: frequencyItems.map(item => [Number(item.value), Number(item.count || 0)]),
      });
    }

    function serializeStatsRecentEntriesForWorker(entries) {
      return (Array.isArray(entries) ? entries : []).map(entry => ({
        ky: String(entry?.ky || ""),
        draw: {
          main: Array.isArray(entry?.draw?.main) ? entry.draw.main.map(Number).filter(Number.isFinite) : [],
          special: Number.isInteger(Number(entry?.draw?.special)) ? Number(entry.draw.special) : null,
          displayLines: Array.isArray(entry?.draw?.displayLines) ? entry.draw.displayLines.map(String) : [],
          date: String(entry?.draw?.date || ""),
          time: String(entry?.draw?.time || ""),
        },
      }));
    }

    function getStatsRecentWorker() {
      if (!statsRecentWorkerSupported) return null;
      if (statsRecentWorker) return statsRecentWorker;
      if (typeof Worker === "undefined" || typeof Blob === "undefined" || typeof URL === "undefined") {
        statsRecentWorkerSupported = false;
        return null;
      }
      const workerSource = `
        function parseLiveDate(value) {
          const text = String(value || '').trim();
          const match = text.match(/^(\\d{1,2})\\/(\\d{1,2})\\/(\\d{4})$/);
          if (!match) return null;
          const day = Number(match[1]);
          const month = Number(match[2]);
          const year = Number(match[3]);
          const parsed = new Date(year, month - 1, day);
          return parsed.getFullYear() === year && parsed.getMonth() === month - 1 && parsed.getDate() === day ? parsed : null;
        }
        function range(min, max) {
          const out = [];
          for (let value = Number(min); value <= Number(max); value++) out.push(value);
          return out;
        }
        function extractThreeDigitTokensFromLines(lines) {
          const out = [];
          (Array.isArray(lines) ? lines : []).forEach(lineText => {
            const matches = String(lineText || '').match(/\\b\\d{3}\\b/g) || [];
            matches.forEach(token => {
              const numeric = Number(token);
              if (Number.isInteger(numeric) && numeric >= 0 && numeric <= 999) out.push(numeric);
            });
          });
          return out;
        }
        function filterEntries(entries, mode, value) {
          const safeEntries = Array.isArray(entries) ? entries : [];
          if (String(value) === 'all') return safeEntries.slice();
          const windowCount = Math.max(1, Number(value) || 100);
          if (mode !== 'day') return safeEntries.slice(-windowCount);
          let latestDate = null;
          for (let index = safeEntries.length - 1; index >= 0; index--) {
            const parsed = parseLiveDate(safeEntries[index]?.draw?.date || '');
            if (parsed && !Number.isNaN(parsed.getTime())) {
              latestDate = parsed;
              break;
            }
          }
          if (!latestDate) return safeEntries.slice(-windowCount);
          const cutoff = new Date(latestDate.getTime());
          cutoff.setHours(0, 0, 0, 0);
          cutoff.setDate(cutoff.getDate() - (windowCount - 1));
          return safeEntries.filter(entry => {
            const parsed = parseLiveDate(entry?.draw?.date || '');
            return parsed && !Number.isNaN(parsed.getTime()) && parsed.getTime() >= cutoff.getTime();
          });
        }
        function buildFrequencyItems(typeConfig, entries) {
          const counts = new Map();
          if (!typeConfig?.threeDigit) {
            range(typeConfig.mainMin, typeConfig.mainMax).forEach(number => counts.set(Number(number), 0));
          }
          if (typeConfig?.threeDigit) {
            entries.forEach(entry => {
              extractThreeDigitTokensFromLines(entry?.draw?.displayLines).forEach(number => {
                counts.set(number, Number(counts.get(number) || 0) + 1);
              });
            });
          } else {
            entries.forEach(entry => {
              (Array.isArray(entry?.draw?.main) ? entry.draw.main : []).forEach(value => {
                const number = Number(value);
                if (Number.isInteger(number)) counts.set(number, Number(counts.get(number) || 0) + 1);
              });
            });
          }
          return [...counts.entries()]
            .map(([value, count]) => ({ value: Number(value), count: Number(count || 0) }))
            .sort((a, b) => b.count - a.count || a.value - b.value);
        }
        function doesEntryContainNumber(typeConfig, entry, value) {
          const numeric = Number(value);
          if (!Number.isInteger(numeric) || !entry?.draw) return false;
          if (typeConfig?.threeDigit) return extractThreeDigitTokensFromLines(entry.draw.displayLines).includes(numeric);
          return (Array.isArray(entry.draw.main) ? entry.draw.main : []).some(item => Number(item) === numeric);
        }
        function buildOverdueItems(typeConfig, frequencyItems, sourceEntries) {
          return (Array.isArray(frequencyItems) ? frequencyItems : [])
            .map(item => {
              let gap = sourceEntries.length;
              for (let index = sourceEntries.length - 1; index >= 0; index--) {
                if (doesEntryContainNumber(typeConfig, sourceEntries[index], item?.value)) {
                  gap = sourceEntries.length - 1 - index;
                  break;
                }
              }
              return { value: Number(item.value), count: Number(item.count || 0), gap };
            })
            .sort((a, b) => b.gap - a.gap || a.count - b.count || a.value - b.value);
        }
        self.onmessage = event => {
          const payload = event.data || {};
          try {
            const entries = Array.isArray(payload.entries) ? payload.entries : [];
            const recentEntries = filterEntries(entries, payload.mode, payload.windowValue);
            const frequencyItems = buildFrequencyItems(payload.typeConfig || {}, recentEntries);
            const sideLimit = Math.max(1, Number(payload.sideLimit || 20));
            const displayItems = payload.typeConfig?.threeDigit ? frequencyItems.slice(0, 100) : frequencyItems;
            const mostItems = frequencyItems.slice(0, sideLimit);
            const leastItems = frequencyItems.slice().sort((a, b) => a.count - b.count || a.value - b.value).slice(0, sideLimit);
            const overdueItems = buildOverdueItems(payload.typeConfig || {}, frequencyItems, entries).slice(0, sideLimit);
            self.postMessage({
              id: payload.id,
              ok: true,
              key: payload.key,
              frequencyItems,
              displayItems,
              mostItems,
              leastItems,
              overdueItems,
              countPairs: frequencyItems.map(item => [Number(item.value), Number(item.count || 0)]),
            });
          } catch (error) {
            self.postMessage({ id: payload.id, ok: false, key: payload.key, error: String(error && error.message || error || 'Worker error') });
          }
        };
      `;
      try {
        const blob = new Blob([workerSource], { type: "application/javascript" });
        statsRecentWorker = new Worker(URL.createObjectURL(blob));
        statsRecentWorker.onmessage = event => {
          const data = event.data || {};
          const job = statsRecentWorkerJobs.get(data.id);
          if (!job) return;
          statsRecentWorkerJobs.delete(data.id);
          statsRecentWorkerJobKeys.delete(job.key);
          if (!data.ok) {
            job.reject(new Error(data.error || "Không tính được thống kê trong Worker."));
            return;
          }
          const normalized = normalizeStatsRecentComputation(job.type, data);
          statsRecentComputationCache.set(job.key, normalized);
          job.resolve(normalized);
        };
        statsRecentWorker.onerror = error => {
          statsRecentWorkerSupported = false;
          statsRecentWorkerJobs.forEach(job => job.reject(error));
          statsRecentWorkerJobs.clear();
          statsRecentWorkerJobKeys.clear();
        };
      } catch {
        statsRecentWorkerSupported = false;
        statsRecentWorker = null;
      }
      return statsRecentWorker;
    }

    function requestStatsRecentComputationWorker(type, entries, mode, value, key) {
      const worker = getStatsRecentWorker();
      if (!worker) return null;
      const existingJobId = statsRecentWorkerJobKeys.get(key);
      if (statsRecentWorkerJobs.has(existingJobId)) return statsRecentWorkerJobs.get(existingJobId).promise;
      const id = ++statsRecentWorkerSeq;
      let resolveJob;
      let rejectJob;
      const promise = new Promise((resolve, reject) => {
        resolveJob = resolve;
        rejectJob = reject;
      });
      statsRecentWorkerJobs.set(id, { id, key, type, resolve: resolveJob, reject: rejectJob, promise });
      statsRecentWorkerJobKeys.set(key, id);
      worker.postMessage({
        id,
        key,
        type,
        typeConfig: TYPES[type] || {},
        entries: serializeStatsRecentEntriesForWorker(entries),
        mode,
        windowValue: value,
        sideLimit: STATS_RECENT100_SIDE_LIMIT,
      });
      return promise;
    }

    function getStatsRecentComputation(type, entries, mode = statsRecentModeValue, value = statsRecentWindowValue, { preferWorker = false } = {}) {
      const key = getStatsRecentEntriesSignature(type, entries, mode, value);
      const cached = statsRecentComputationCache.get(key);
      if (cached) return { key, computation: cached, pending: false };
      if (preferWorker) {
        const pending = requestStatsRecentComputationWorker(type, entries, mode, value, key);
        if (pending) {
          statsRecentPendingComputationKey = key;
          pending.then(() => {
            if (statsRecentPendingComputationKey === key && predictPageModeValue === PREDICTION_MODE_STATS) renderStatsPanel();
          }).catch(() => {
            if (statsRecentPendingComputationKey === key) {
              const fallback = buildStatsRecentComputationSync(type, entries, mode, value);
              statsRecentComputationCache.set(key, fallback);
              renderStatsPanel();
            }
          });
          return { key, computation: null, pending: true };
        }
      }
      const computation = buildStatsRecentComputationSync(type, entries, mode, value);
      statsRecentComputationCache.set(key, computation);
      return { key, computation, pending: false };
    }

    function normalizeStatsRecentKenoLevel(value) {
      const numeric = Number(value);
      if (!Number.isInteger(numeric)) return 10;
      return Math.min(10, Math.max(1, numeric));
    }

    function getStatsRecentKenoMaxSets(level = statsRecentKenoLevelValue) {
      const normalizedLevel = normalizeStatsRecentKenoLevel(level);
      if (normalizedLevel <= 6) return 6;
      if (normalizedLevel <= 8) return 4;
      return 3;
    }

    function getStatsRecentKenoLimitText(level = statsRecentKenoLevelValue) {
      const normalizedLevel = normalizeStatsRecentKenoLevel(level);
      const maxSets = getStatsRecentKenoMaxSets(normalizedLevel);
      if (normalizedLevel <= 6) return `Bậc 1-6: tối đa ${maxSets} bộ`;
      if (normalizedLevel <= 8) return `Bậc 7-8: tối đa ${maxSets} bộ`;
      return `Bậc 9-10: tối đa ${maxSets} bộ`;
    }

    function setStatsRecentKenoLevel(value) {
      statsRecentKenoLevelValue = normalizeStatsRecentKenoLevel(value);
      const sets = getStatsRecentSelectedSets("KENO");
      statsRecentSelectedByType.KENO = { sets };
      setStatsRecentActiveSetIndex("KENO", getStatsRecentActiveSetIndex("KENO"));
      if (typeof saveStatsRecentSelectedState === "function") saveStatsRecentSelectedState();
    }

    function getStatsRecentTicketConfig(type) {
      const normalized = normalizeStatsType(type);
      if (normalized === "KENO") {
        const kenoLevel = normalizeStatsRecentKenoLevel(statsRecentKenoLevelValue);
        statsRecentKenoLevelValue = kenoLevel;
        return {
          maxSets: getStatsRecentKenoMaxSets(kenoLevel),
          mainCount: kenoLevel,
          hasSpecial: false,
          specialLabel: "",
          specialMin: 0,
          specialMax: 0,
          kenoLevel,
        };
      }
      if (normalized === "LOTO_5_35") {
        return { maxSets: 6, mainCount: 5, hasSpecial: true, specialLabel: "ĐB", specialMin: 1, specialMax: 12 };
      }
      if (normalized === "LOTO_6_55") {
        return { maxSets: 6, mainCount: 6, hasSpecial: true, specialLabel: "Số 7", specialMin: 1, specialMax: 55 };
      }
      if (TYPES[normalized]?.threeDigit) {
        return { maxSets: 6, mainCount: 1, hasSpecial: false, specialLabel: "", specialMin: 0, specialMax: 0 };
      }
      return { maxSets: 6, mainCount: 6, hasSpecial: false, specialLabel: "", specialMin: 0, specialMax: 0 };
    }

    function getStatsRecentActiveSetIndex(type) {
      const key = normalizeStatsType(type);
      const config = getStatsRecentTicketConfig(key);
      const numeric = Number(statsRecentActiveSetByType[key]);
      if (!Number.isInteger(numeric)) return 0;
      return Math.min(Math.max(numeric, 0), config.maxSets - 1);
    }

    function setStatsRecentActiveSetIndex(type, value) {
      const key = normalizeStatsType(type);
      const config = getStatsRecentTicketConfig(key);
      const numeric = Number(value);
      statsRecentActiveSetByType[key] = Number.isInteger(numeric)
        ? Math.min(Math.max(numeric, 0), config.maxSets - 1)
        : 0;
    }

    function createStatsRecentTicketSet() {
      return { main: [], special: null };
    }

    function normalizeStatsRecentTicketSet(setValue) {
      const set = setValue && typeof setValue === "object" ? setValue : {};
      const main = Array.isArray(set.main)
        ? set.main.map(value => Number(value)).filter(value => Number.isInteger(value))
        : [];
      const special = Number(set.special);
      return {
        main: [...new Set(main)],
        special: Number.isInteger(special) ? special : null,
      };
    }

    function getStatsRecentSelectedSets(type) {
      const key = normalizeStatsType(type);
      const config = getStatsRecentTicketConfig(key);
      const stored = statsRecentSelectedByType[key];
      if (Array.isArray(stored)) {
        const migrated = [];
        stored
          .map(value => Number(value))
          .filter(value => Number.isInteger(value))
          .forEach(value => {
            if (!migrated.length || migrated[migrated.length - 1].main.length >= config.mainCount) {
              if (migrated.length < config.maxSets) migrated.push(createStatsRecentTicketSet());
            }
            const target = migrated[migrated.length - 1];
            if (target && !target.main.includes(value)) target.main.push(value);
          });
        statsRecentSelectedByType[key] = { sets: migrated };
      }
      const sets = (Array.isArray(statsRecentSelectedByType[key]?.sets)
        ? statsRecentSelectedByType[key].sets.map(normalizeStatsRecentTicketSet)
        : [])
        .slice(0, config.maxSets)
        .map(set => ({
          main: set.main.slice(0, config.mainCount),
          special: config.hasSpecial ? set.special : null,
        }));
      statsRecentSelectedByType[key] = { sets };
      setStatsRecentActiveSetIndex(key, getStatsRecentActiveSetIndex(key));
      return sets;
    }

    function addStatsRecentSelectedNumber(type, value, role = "main") {
      const numeric = Number(value);
      if (!Number.isInteger(numeric)) return;
      const key = normalizeStatsType(type);
      const config = getStatsRecentTicketConfig(key);
      const sets = getStatsRecentSelectedSets(key);
      const activeSetIndex = getStatsRecentActiveSetIndex(key);
      if (!sets[activeSetIndex]) sets[activeSetIndex] = createStatsRecentTicketSet();
      const set = sets[activeSetIndex];
      if (
        role === "special" &&
        config.hasSpecial &&
        numeric >= config.specialMin &&
        numeric <= config.specialMax
      ) {
        if (set.main.includes(numeric) || set.special === numeric) return;
        set.special = numeric;
        statsRecentSelectedByType[key] = { sets };
        if (typeof saveStatsRecentSelectedState === "function") saveStatsRecentSelectedState();
        return;
      }
      if (set.main.length < config.mainCount) {
        if (set.main.includes(numeric) || set.special === numeric) return;
        set.main.push(numeric);
        statsRecentSelectedByType[key] = { sets };
        if (typeof saveStatsRecentSelectedState === "function") saveStatsRecentSelectedState();
        return;
      }
      if (
        config.hasSpecial &&
        set.special === null &&
        numeric >= config.specialMin &&
        numeric <= config.specialMax
      ) {
        if (set.main.includes(numeric)) return;
        set.special = numeric;
        statsRecentSelectedByType[key] = { sets };
        if (typeof saveStatsRecentSelectedState === "function") saveStatsRecentSelectedState();
        return;
      }
      statsRecentSelectedByType[key] = { sets };
      if (typeof saveStatsRecentSelectedState === "function") saveStatsRecentSelectedState();
    }

    function removeStatsRecentSelectedNumber(type, value, setIndex = null, role = "main") {
      const numeric = Number(value);
      if (!Number.isInteger(numeric)) return;
      const key = normalizeStatsType(type);
      const sets = getStatsRecentSelectedSets(key);
      const numericSetIndex = Number(setIndex);
      if (Number.isInteger(numericSetIndex) && sets[numericSetIndex]) {
        if (role === "special") {
          sets[numericSetIndex].special = null;
        } else {
          sets[numericSetIndex].main = sets[numericSetIndex].main.filter(item => item !== numeric);
        }
      } else {
        sets.forEach(set => {
          set.main = set.main.filter(item => item !== numeric);
          if (set.special === numeric) set.special = null;
        });
      }
      statsRecentSelectedByType[key] = { sets };
      if (typeof saveStatsRecentSelectedState === "function") saveStatsRecentSelectedState();
    }

    function clearStatsRecentSelectedNumbers(type) {
      const key = normalizeStatsType(type);
      const sets = getStatsRecentSelectedSets(key);
      sets[getStatsRecentActiveSetIndex(key)] = createStatsRecentTicketSet();
      statsRecentSelectedByType[key] = { sets };
      if (typeof saveStatsRecentSelectedState === "function") saveStatsRecentSelectedState();
    }

    const STATS_RECENT_HELP_RULES = {
      LOTO_5_35: {
        title: "5/35",
        mainLabel: "Số chính",
        mainRange: "1-35",
        mainCount: 5,
        hasSpecial: true,
        specialLabel: "Số ĐB",
        specialRange: "1-12",
        specialCount: 1,
        maxSets: "6 bộ",
        setDescription: "5 số chính + 1 số ĐB",
        chooseLines: [
          "Chọn 5 số chính từ 1 đến 35.",
          "Chọn 1 số đặc biệt từ 1 đến 12.",
        ],
        notes: [
          "Mỗi lần chơi được lưu tối đa 6 bộ số.",
          "Trúng thưởng khi khớp đủ số chính và số đặc biệt theo quy tắc hệ thống.",
          "Thống kê chỉ mang tính chất tham khảo.",
        ],
      },
      LOTO_6_45: {
        title: "6/45",
        mainLabel: "Số chính",
        mainRange: "1-45",
        mainCount: 6,
        hasSpecial: false,
        specialLabel: "",
        specialRange: "",
        specialCount: 0,
        maxSets: "6 bộ",
        setDescription: "6 số chính",
        chooseLines: [
          "Chọn 6 số chính từ 1 đến 45.",
          "Loại 6/45 không có số đặc biệt.",
        ],
        notes: [
          "Mỗi lần chơi được lưu tối đa 6 bộ số.",
          "Thống kê chỉ mang tính chất tham khảo.",
        ],
      },
      LOTO_6_55: {
        title: "6/55",
        mainLabel: "Số chính",
        mainRange: "1-55",
        mainCount: 6,
        hasSpecial: true,
        specialLabel: "Số ĐB T7",
        specialRange: "1-55",
        specialCount: 1,
        maxSets: "6 bộ",
        setDescription: "6 số chính + 1 số ĐB T7",
        chooseLines: [
          "Chọn 6 số chính từ 1 đến 55.",
          "Số ĐB là số T7, cũng nằm trong dải 1 đến 55.",
        ],
        notes: [
          "Mỗi lần chơi được lưu tối đa 6 bộ số.",
          "Thống kê chỉ mang tính chất tham khảo.",
        ],
      },
      KENO: {
        title: "Keno",
        mainLabel: "Số chính",
        mainRange: "1-80",
        mainCount: "Theo bậc 1-10",
        hasSpecial: false,
        specialLabel: "",
        specialRange: "",
        specialCount: 0,
        maxSets: "Theo bậc",
        setDescription: "Chọn số theo bậc Keno",
        chooseLines: [
          "Keno dùng dải số từ 1 đến 80.",
          "Chọn số theo bậc Keno từ 1 đến 10 số.",
        ],
        kenoRanks: [
          ["Bậc 1-6", "Tối đa 6 bộ"],
          ["Bậc 7-8", "Tối đa 4 bộ"],
          ["Bậc 9-10", "Tối đa 3 bộ"],
        ],
        notes: [
          "Mỗi kỳ quay 20 số từ 1 đến 80.",
          "Thống kê chỉ mang tính chất tham khảo.",
        ],
      },
      MAX_3D: {
        title: "3D",
        mainLabel: "Số chính",
        mainRange: "000-999",
        mainCount: "1 số có 3 chữ số",
        hasSpecial: false,
        specialLabel: "",
        specialRange: "",
        specialCount: 0,
        maxSets: "6 bộ",
        setDescription: "Mỗi bộ là 1 số 3 chữ số",
        chooseLines: [
          "Chọn hoặc nhập số từ 000 đến 999.",
          "Luôn hiển thị đủ 3 chữ số, ví dụ: 007, 028, 305.",
        ],
        notes: [
          "Mỗi lần chơi được lưu tối đa 6 bộ số.",
          "Thống kê chỉ mang tính chất tham khảo.",
        ],
      },
      MAX_3D_PRO: {
        title: "3D Pro",
        mainLabel: "Số chính",
        mainRange: "000-999",
        mainCount: "1 số có 3 chữ số",
        hasSpecial: false,
        specialLabel: "",
        specialRange: "",
        specialCount: 0,
        maxSets: "6 bộ",
        setDescription: "Hỗ trợ thường / bao / đảo nếu hệ thống có",
        chooseLines: [
          "Chọn hoặc nhập số từ 000 đến 999.",
          "Luôn hiển thị đủ 3 chữ số, ví dụ: 001, 079, 888.",
        ],
        notes: [
          "Có thể mở rộng thêm kiểu thường, bao, đảo.",
          "Mỗi lần chơi được lưu tối đa 6 bộ số.",
          "Thống kê chỉ mang tính chất tham khảo.",
        ],
      },
    };

    function getStatsRecentHelpRule(type) {
      return STATS_RECENT_HELP_RULES[normalizeStatsType(type)] || STATS_RECENT_HELP_RULES.LOTO_5_35;
    }

    function renderStatsRecentHelpList(items = []) {
      return `
        <ul class="stats-recent100-help-list">
          ${(Array.isArray(items) ? items : []).map(item => `
            <li><span>•</span><strong>${escapeHtml(item)}</strong></li>
          `).join("")}
        </ul>
      `;
    }

    function renderStatsRecentHelpConfigCard(rule) {
      const mainText = typeof rule.mainCount === "number"
        ? `${rule.mainCount} số từ ${rule.mainRange}`
        : `${rule.mainCount}`;
      const specialText = rule.hasSpecial
        ? `${rule.specialCount} số từ ${rule.specialRange}`
        : "Không có";
      return `
        <div class="stats-recent100-help-card">
          <div><span>Loại</span><strong>${escapeHtml(rule.title)}</strong></div>
          <div><span>${escapeHtml(rule.mainLabel)}</span><strong>${escapeHtml(mainText)}</strong></div>
          <div><span>Số ĐB</span><strong>${escapeHtml(specialText)}</strong></div>
          <div><span>Số bộ tối đa</span><strong>${escapeHtml(rule.maxSets)}</strong></div>
        </div>
      `;
    }

    function renderStatsRecentHelpPopover(type) {
      const rule = getStatsRecentHelpRule(type);
      const normalizedType = normalizeStatsType(type);
      const starLegendText = normalizedType === "KENO" ? "Kết quả kỳ trước" : "Số ĐB";
      return `
        <div class="stats-recent100-help" data-stats-recent-help>
          <button
            type="button"
            class="stats-recent100-help-toggle"
            data-stats-recent-help-toggle
            aria-label="Hướng dẫn ${escapeHtml(rule.title)}"
            aria-expanded="false"
          >?</button>
          <div class="stats-recent100-help-popover" data-stats-recent-help-panel role="dialog" aria-label="Hướng dẫn ${escapeHtml(rule.title)}">
            <div class="stats-recent100-help-head">
              <div class="stats-recent100-help-title">
                <span>?</span>
                <strong>Hướng dẫn ${escapeHtml(rule.title)}</strong>
              </div>
            </div>
            <div class="stats-recent100-help-body">
              <section class="stats-recent100-help-section is-config">
                <h4>Cấu hình vé</h4>
                ${renderStatsRecentHelpConfigCard(rule)}
              </section>
              <section class="stats-recent100-help-section is-choose">
                <h4>Cách chọn số</h4>
                ${renderStatsRecentHelpList(rule.chooseLines)}
              </section>
              <section class="stats-recent100-help-section is-limits">
                <h4>Số bộ tối đa</h4>
                <div class="stats-recent100-help-card">
                  <div><span>Giới hạn</span><strong>${escapeHtml(rule.maxSets)}</strong></div>
                  ${Array.isArray(rule.kenoRanks) ? rule.kenoRanks.map(([label, value]) => `
                    <div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>
                  `).join("") : ""}
                </div>
              </section>
              <section class="stats-recent100-help-section is-legend">
                <h4>Chú thích màu</h4>
                <div class="stats-recent100-help-legend">
                  <div><span class="stats-recent100-help-dot is-yellow"></span><strong>Vàng: thống kê</strong></div>
                  <div><span class="stats-recent100-help-dot is-purple"></span><strong>Tím: dự đoán</strong></div>
                  <div><span class="stats-recent100-help-dot is-green"></span><strong>Xanh: đúng</strong></div>
                  <div><span class="stats-recent100-help-dot is-red"></span><strong>Đỏ: sai</strong></div>
                  <div><span class="stats-recent100-help-star">★</span><strong>${escapeHtml(starLegendText)}</strong></div>
                </div>
              </section>
              <section class="stats-recent100-help-section is-note">
                <h4>Lưu ý</h4>
                ${renderStatsRecentHelpList(rule.notes)}
              </section>
            </div>
          </div>
        </div>
      `;
    }

    function renderStatsRecentColorLegend() {
      return `
        <div class="stats-recent100-color-balls" aria-label="Chú thích màu bóng">
          <span class="stats-recent100-color-ball is-yellow" tabindex="0">
            <span class="stats-recent100-color-tip">
              <strong>Vàng</strong>
              <small>Số thống kê thường</small>
            </span>
          </span>
          <span class="stats-recent100-color-ball is-green" tabindex="0">
            <span class="stats-recent100-color-tip">
              <strong>Xanh</strong>
              <small>Dự đoán đúng kỳ trước</small>
            </span>
          </span>
          <span class="stats-recent100-color-ball is-red" tabindex="0">
            <span class="stats-recent100-color-tip">
              <strong>Đỏ</strong>
              <small>Dự đoán sai kỳ trước</small>
            </span>
          </span>
          <span class="stats-recent100-color-ball is-purple" tabindex="0">
            <span class="stats-recent100-color-tip">
              <strong>Tím</strong>
              <small>Dự đoán hiện tại</small>
            </span>
          </span>
        </div>
      `;
    }

    function getStatsModernRangeText(type, { special = false } = {}) {
      const config = TYPES[type] || {};
      if (TYPES[type]?.threeDigit) return "000 - 999";
      const min = special ? config.specialMin : config.mainMin;
      const max = special ? config.specialMax : config.mainMax;
      return `${min} - ${max}`;
    }

    function getStatsModernOrderedItems(type, countByValue, fallbackItems = [], { special = false, limit = null } = {}) {
      const config = TYPES[type] || {};
      const map = countByValue instanceof Map ? countByValue : new Map();
      if (TYPES[type]?.threeDigit && !special) {
        return (Array.isArray(fallbackItems) ? fallbackItems : [])
          .slice(0, Number(limit || 50))
          .map(item => ({
            value: Number(item?.value),
            count: Number(item?.count || 0),
            label: getStatsDisplayLabel(type, item?.value),
          }));
      }
      const min = special ? config.specialMin : config.mainMin;
      const max = special ? config.specialMax : config.mainMax;
      return range(min, max).map(value => ({
        value: Number(value),
        count: Number(map.get(Number(value)) || 0),
        label: getStatsDisplayLabel(type, value, special),
      }));
    }

    function getStatsModernMetricItem(items, fallback = null) {
      const item = Array.isArray(items) && items.length ? items[0] : fallback;
      if (!item) return null;
      return {
        ...item,
        value: Number(item.value),
        count: Number(item.count || 0),
        gap: Number(item.gap || 0),
      };
    }

    function renderStatsModernLegend(type, comparisonLabel = "kỳ trước") {
      const normalizedType = normalizeStatsType(type);
      const markerLabel = normalizedType === "KENO" ? "Kết quả kỳ trước" : "Số ĐB";
      return `
        <div class="stats-modern-legend" aria-label="Chú thích màu">
          <span><i class="stats-modern-dot is-yellow"></i>Số thống kê thường</span>
          <span><i class="stats-modern-dot is-purple"></i>Dự đoán hiện tại</span>
          <span><i class="stats-modern-dot is-green"></i>Đúng ${escapeHtml(comparisonLabel)}</span>
          <span><i class="stats-modern-dot is-red"></i>Sai ${escapeHtml(comparisonLabel)}</span>
          <span><i class="stats-modern-star">★</i>${escapeHtml(markerLabel)}</span>
        </div>
      `;
    }

    function renderStatsModernTypePicker(type, currentTypeMeta) {
      return `
        <div class="stats-modern-select" aria-label="Chọn loại vé thống kê">
          <button type="button" class="stats-modern-select-trigger" aria-haspopup="menu">
            <span class="stats-modern-select-text">
              <span class="stats-modern-select-label">Loại</span>
              <strong class="stats-modern-select-value">${escapeHtml(currentTypeMeta.label)}</strong>
            </span>
            <span class="stats-modern-chevron" aria-hidden="true"></span>
          </button>
          <div class="stats-modern-select-menu" role="menu">
            ${STATS_TYPE_OPTIONS.map(option => `
              <button
                type="button"
                class="stats-modern-select-option${option.value === type ? " is-active" : ""}"
                data-stats-recent-type="${escapeHtml(option.value)}"
                role="menuitemradio"
                aria-checked="${option.value === type ? "true" : "false"}"
              >${escapeHtml(option.label)}</button>
            `).join("")}
          </div>
        </div>
      `;
    }

    function renderStatsModernModePicker(recentMode) {
      const label = STATS_RECENT_MODE_OPTIONS.find(option => option.value === recentMode)?.label || "Kỳ";
      return `
        <div class="stats-modern-select" aria-label="Chọn hình thức thống kê">
          <button type="button" class="stats-modern-select-trigger" aria-haspopup="menu">
            <span class="stats-modern-select-text">
              <span class="stats-modern-select-label">Hình thức</span>
              <strong class="stats-modern-select-value">${escapeHtml(label)}</strong>
            </span>
            <span class="stats-modern-chevron" aria-hidden="true"></span>
          </button>
          <div class="stats-modern-select-menu" role="menu">
            ${STATS_RECENT_MODE_OPTIONS.map(option => `
              <button
                type="button"
                class="stats-modern-select-option${option.value === recentMode ? " is-active" : ""}"
                data-stats-recent-mode="${escapeHtml(option.value)}"
                role="menuitemradio"
                aria-checked="${option.value === recentMode ? "true" : "false"}"
              >${escapeHtml(option.label)}</button>
            `).join("")}
          </div>
        </div>
      `;
    }

    function renderStatsModernWindowButtons(recentWindowOptions, recentWindow, recentMode) {
      return `
        <div class="stats-modern-window-buttons" aria-label="Chọn phạm vi hiển thị">
          ${recentWindowOptions.map(option => `
            <button
              type="button"
              class="stats-modern-window-btn${option === recentWindow ? " is-active" : ""}"
              data-stats-recent-window="${escapeHtml(String(option))}"
              aria-pressed="${option === recentWindow ? "true" : "false"}"
            >${escapeHtml(getStatsRecentWindowLabel(option, recentMode))}</button>
          `).join("")}
        </div>
      `;
    }

    function renderStatsModernNumberCard(type, item, {
      hitNumberSet = null,
      missedNumberSet = null,
      currentPredictionSet = null,
      specialMarkerSet = null,
      pickRole = "main",
      compact = false,
      showSpecialMarker = false,
      countLabel = "lần",
    } = {}) {
      const value = Number(item?.value);
      const label = item?.label || getStatsDisplayLabel(type, value, pickRole === "special");
      const markerSet = specialMarkerSet instanceof Set ? specialMarkerSet : new Set();
      const hasSpecialMarker = showSpecialMarker || markerSet.has(value);
      return `
        <button
          type="button"
          class="stats-modern-number ${compact ? "is-compact" : ""} ${getStatsRecent100BallClass(value, hitNumberSet, missedNumberSet, currentPredictionSet)}"
          data-stats-recent-pick="${value}"
          data-stats-recent-pick-role="${escapeHtml(pickRole)}"
          aria-label="Chọn số ${escapeHtml(label)}"
          title="${escapeHtml(`${label} • ${formatLiveSyncCount(item?.count || 0)} ${countLabel}`)}"
        >
          ${hasSpecialMarker ? `<span class="stats-modern-number-star" aria-hidden="true">★</span>` : ""}
          <span class="stats-modern-number-value">${escapeHtml(label)}</span>
          <span class="stats-modern-number-count">${escapeHtml(`${formatLiveSyncCount(item?.count || 0)} ${countLabel}`)}</span>
        </button>
      `;
    }

    function renderStatsModernNumberGrid(type, items, options = {}) {
      const gridClass = getStatsRecentGridClass(type);
      return `
        <div class="stats-modern-number-grid ${gridClass}">
          ${(Array.isArray(items) ? items : []).map(item => renderStatsModernNumberCard(type, item, options)).join("")}
        </div>
      `;
    }

    function renderStatsModernPanelTitle(icon, title, subtitle = "") {
      const cleanSubtitle = String(subtitle || "").replace(/^[\s•]+|[\s•]+$/g, "").trim();
      return `
        <div class="stats-modern-panel-title">
          <span class="stats-modern-panel-icon">${escapeHtml(icon)}</span>
          <div>
            <h3>${escapeHtml(title)}</h3>
            ${cleanSubtitle ? `<p>${escapeHtml(cleanSubtitle)}</p>` : ""}
          </div>
        </div>
      `;
    }

    function normalizeStatsModernInsightTab(value) {
      const key = String(value || "").trim().toLowerCase();
      return ["most", "least", "overdue"].includes(key) ? key : "most";
    }

    function renderStatsModernInsightPanel(type, {
      mostItems = [],
      leastItems = [],
      overdueItems = [],
      hitNumberSet = null,
      missedNumberSet = null,
      currentPredictionSet = null,
    } = {}) {
      const tabs = [
        { key: "most", label: "Nhiều nhất", items: mostItems, valueKey: "count", unit: "lần" },
        { key: "least", label: "Ít nhất", items: leastItems, valueKey: "count", unit: "lần" },
        { key: "overdue", label: "Chưa về", items: overdueItems, valueKey: "gap", unit: "kỳ" },
      ];
      const activeKey = normalizeStatsModernInsightTab(statsModernInsightTab);
      const activeTab = tabs.find(tab => tab.key === activeKey) || tabs[0];
      const maxItems = statsModernInsightExpanded ? 20 : 10;
      const topItems = (Array.isArray(activeTab.items) ? activeTab.items : []).slice(0, maxItems);
      const rowCount = Math.ceil(topItems.length / 2);
      const canExpand = (Array.isArray(activeTab.items) ? activeTab.items.length : 0) > 10;
      return `
        <section class="stats-modern-card stats-modern-insight">
          ${renderStatsModernPanelTitle("♢", "Nhận định")}
          <div class="stats-modern-tabs" aria-label="Nhóm nhận định">
            ${tabs.map(tab => `
              <button
                type="button"
                class="${tab.key === activeKey ? "is-active" : ""}"
                data-stats-modern-insight-tab="${escapeHtml(tab.key)}"
                aria-pressed="${tab.key === activeKey ? "true" : "false"}"
              >${escapeHtml(tab.label)}</button>
            `).join("")}
          </div>
          <div class="stats-modern-rank-list">
            ${Array.from({ length: rowCount }, (_, rowIndex) => [topItems[rowIndex], topItems[rowIndex + rowCount]]).map((pair, rowIndex) => `
              <div class="stats-modern-rank-row">
                ${pair.map((item, index) => item ? `
                  <div class="stats-modern-rank-cell">
                    <span class="stats-modern-rank-index">${rowIndex + 1 + (index ? rowCount : 0)}</span>
                    <span class="stats-modern-rank-ball ${getStatsRecent100BallClass(item.value, hitNumberSet, missedNumberSet, currentPredictionSet)}">${escapeHtml(item.label || getStatsDisplayLabel(type, item.value))}</span>
                    <strong>${escapeHtml(`${formatLiveSyncCount(item[activeTab.valueKey] || 0)} ${activeTab.unit}`)}</strong>
                  </div>
                ` : `<div class="stats-modern-rank-cell is-empty"></div>`).join("")}
              </div>
            `).join("")}
          </div>
          ${canExpand ? `
            <button
              type="button"
              class="stats-modern-view-all"
              data-stats-modern-insight-toggle="1"
              aria-expanded="${statsModernInsightExpanded ? "true" : "false"}"
            >${statsModernInsightExpanded ? "Thu gọn" : "Xem đầy đủ"} <span>›</span></button>
          ` : ""}
        </section>
      `;
    }

    function renderStatsModernMetricCard(title, item, valueKey, icon, tone, type, { special = false } = {}) {
      const label = item ? getStatsDisplayLabel(type, item.value, special) : "--";
      const value = item ? (valueKey === "gap" ? item.gap : item.count) : 0;
      const unit = valueKey === "gap" ? "kỳ" : "lần";
      return `
        <article class="stats-modern-metric is-${escapeHtml(tone)}">
          <div class="stats-modern-metric-head">
            <span>${escapeHtml(icon)}</span>
            <strong>${escapeHtml(title)}</strong>
          </div>
          <div class="stats-modern-metric-body">
            <span>${escapeHtml(label)}</span>
            <small>${escapeHtml(`${formatLiveSyncCount(value)} ${unit}`)}</small>
          </div>
        </article>
      `;
    }

    function renderStatsModernSummaryMetricCard(title, label, detail, icon, tone) {
      return `
        <article class="stats-modern-metric is-${escapeHtml(tone)}">
          <div class="stats-modern-metric-head">
            <span>${escapeHtml(icon)}</span>
            <strong>${escapeHtml(title)}</strong>
          </div>
          <div class="stats-modern-metric-body">
            <span>${escapeHtml(label)}</span>
            <small>${escapeHtml(detail)}</small>
          </div>
        </article>
      `;
    }

    function renderStatsModernMetrics(type, {
      mostItems,
      leastItems,
      overdueItems,
      specialMostItems,
      hitNumberSet,
      missedNumberSet,
      countByValue,
      latestActualSet = null,
      latestEntry = null,
      comparisonLabel = "kỳ trước",
      comparisonActualSet = null,
      comparisonEntry = null,
    }) {
      const hot = getStatsModernMetricItem(mostItems);
      const cold = getStatsModernMetricItem(leastItems);
      const overdue = getStatsModernMetricItem(overdueItems);
      const specialHot = getStatsModernMetricItem(specialMostItems, hot);
      const hitCount = hitNumberSet instanceof Set ? hitNumberSet.size : 0;
      const missedCount = missedNumberSet instanceof Set ? missedNumberSet.size : 0;
      const scoredCount = hitCount + missedCount;
      const actualSetForMetric = comparisonActualSet instanceof Set ? comparisonActualSet : latestActualSet;
      const actualCountForMetric = actualSetForMetric instanceof Set ? actualSetForMetric.size : 0;
      const actualKyForMetric = comparisonEntry?.actualKy || comparisonEntry?.predictedKy || latestEntry?.ky || "";
      const actualTitle = comparisonLabel === "kỳ đã chấm" ? "Kỳ đã chấm" : "Kỳ trước";
      const latestActualMetric = normalizeStatsType(type) === "KENO"
        ? renderStatsModernSummaryMetricCard(
            actualTitle,
            actualCountForMetric ? `${actualCountForMetric} số` : "--",
            actualKyForMetric ? `Kỳ ${formatLiveKy(actualKyForMetric)}` : "Chưa có dữ liệu",
            "★",
            "special"
          )
        : renderStatsModernMetricCard("Số ĐB", specialHot, "count", "★", "special", type, { special: TYPES[type]?.hasSpecial });
      return `
        <div class="stats-modern-metrics">
          ${renderStatsModernMetricCard("Nóng nhất", hot, "count", "🔥", "hot", type)}
          ${renderStatsModernMetricCard("Lạnh nhất", cold, "count", "❄", "cold", type)}
          ${renderStatsModernMetricCard("Chưa về lâu", overdue, "gap", "⌛", "overdue", type)}
          ${latestActualMetric}
          ${renderStatsModernSummaryMetricCard(
            `Đúng ${comparisonLabel}`,
            scoredCount ? `${formatLiveSyncCount(hitCount)}/${formatLiveSyncCount(scoredCount)}` : "--",
            scoredCount ? `${formatLiveSyncCount(hitCount)} số trùng kết quả` : "Chưa có dữ liệu chấm",
            "✓",
            "hit"
          )}
          ${renderStatsModernSummaryMetricCard(
            `Sai ${comparisonLabel}`,
            scoredCount ? `${formatLiveSyncCount(missedCount)}/${formatLiveSyncCount(scoredCount)}` : "--",
            scoredCount ? `${formatLiveSyncCount(missedCount)} số không trùng` : "Chưa có dữ liệu chấm",
            "×",
            "missed"
          )}
        </div>
      `;
    }

    function getStatsPredictionSetItems(type, predictionSet, countByValue = null) {
      const values = predictionSet instanceof Set ? [...predictionSet] : [];
      const countMap = countByValue instanceof Map ? countByValue : new Map();
      return values
        .map(value => Number(value))
        .filter(value => Number.isInteger(value))
        .sort((a, b) => a - b)
        .map(value => ({
          value,
          count: Number(countMap.get(value) || 0),
          label: getStatsDisplayLabel(type, value),
        }));
    }

    function renderStatsModernPredictionPanel(type, {
      predictionSet = null,
      predictionEntry = null,
      isFallback = false,
      latestEntry = null,
      countByValue = null,
      hitNumberSet = null,
      missedNumberSet = null,
    } = {}) {
      const items = getStatsPredictionSetItems(type, predictionSet, countByValue);
      const sourceLabel = isFallback
        ? "Theo thống kê hiện tại"
        : (predictionEntry ? (predictionEntry?.engineLabel || predictionEntry?.modelLabel || predictionEntry?.strategyLabel || "AI đã lưu") : "");
      const kyLabel = predictionEntry?.predictedKy
        ? `Kỳ ${formatLiveKy(predictionEntry.predictedKy)}`
        : (latestEntry?.ky ? `Sau kỳ ${formatLiveKy(latestEntry.ky)}` : "");
      const subtitle = [kyLabel, sourceLabel]
        .map(part => String(part || "").replace(/^[\s•]+|[\s•]+$/g, "").trim())
        .filter(Boolean)
        .join(" • ");
      return `
        <section class="stats-modern-card stats-modern-prediction-card">
          ${renderStatsModernPanelTitle("◎", "Dự đoán", subtitle)}
          ${items.length ? `
            <div class="stats-modern-prediction-grid ${getStatsRecentGridClass(type)}">
              ${items.map(item => `
                <button
                  type="button"
                  class="stats-modern-prediction-ball ${getStatsRecent100BallClass(item.value, hitNumberSet, missedNumberSet, predictionSet)}"
                  data-stats-recent-pick="${Number(item.value)}"
                  data-stats-recent-pick-role="main"
                  aria-label="Chọn số dự đoán ${escapeHtml(item.label)}"
                  title="${escapeHtml(`${item.label} • ${formatLiveSyncCount(item.count)} lần trong thống kê`)}"
                >
                  ${escapeHtml(item.label)}
                </button>
              `).join("")}
            </div>
          ` : `<div class="stats-modern-prediction-empty">Chưa có bộ dự đoán để hiển thị.</div>`}
        </section>
      `;
    }

    function renderStatsModernConfigCards(type) {
      const rule = getStatsRecentHelpRule(type);
      const mainText = typeof rule.mainCount === "number"
        ? `${rule.mainCount} số từ ${rule.mainRange}`
        : `${rule.mainCount}`;
      return `
        <section class="stats-modern-card stats-modern-config">
          ${renderStatsModernPanelTitle("⚙", "Cấu hình vé")}
          <div class="stats-modern-config-lines">
            <div><span>Loại</span><strong>${escapeHtml(rule.title)}</strong></div>
            <div><span>${escapeHtml(rule.mainLabel)}</span><strong>${escapeHtml(mainText)}</strong></div>
            <div><span>Số ĐB</span><strong>${rule.hasSpecial ? escapeHtml(`${rule.specialCount} số từ ${rule.specialRange}`) : "Không có"}</strong></div>
            <div><span>Số bộ tối đa</span><strong>${escapeHtml(rule.maxSets)}</strong></div>
          </div>
        </section>
        <section class="stats-modern-card stats-modern-notes">
          ${renderStatsModernPanelTitle("✓", "Quy tắc & lưu ý")}
          <ul>
            ${(Array.isArray(rule.notes) ? rule.notes : []).slice(0, 3).map(note => `<li>${escapeHtml(note)}</li>`).join("")}
          </ul>
        </section>
      `;
    }

    function renderStatsRecentKenoLevelControl(config) {
      const level = normalizeStatsRecentKenoLevel(config?.kenoLevel || statsRecentKenoLevelValue);
      return `
        <div class="stats-modern-keno-level-control">
          <label for="statsRecentKenoLevel">Bậc</label>
          <select id="statsRecentKenoLevel" data-stats-recent-keno-level aria-label="Chọn bậc Keno">
            ${Array.from({ length: 10 }, (_, index) => {
              const value = index + 1;
              return `<option value="${value}"${value === level ? " selected" : ""}>Bậc ${value}</option>`;
            }).join("")}
          </select>
          <small>${escapeHtml(getStatsRecentKenoLimitText(level))}</small>
        </div>
      `;
    }

    function renderStatsRecentSelectedPanel(type, { hitNumberSet = null, missedNumberSet = null, currentPredictionSet = null, countByValue = null } = {}) {
      const normalizedType = normalizeStatsType(type);
      const config = getStatsRecentTicketConfig(type);
      const selectedSets = getStatsRecentSelectedSets(type);
      const activeSetIndex = getStatsRecentActiveSetIndex(type);
      const activeSet = selectedSets[activeSetIndex] || createStatsRecentTicketSet();
      const visibleRows = Array.from({ length: config.maxSets }, (_, index) => ({
        index,
        set: selectedSets[index] || createStatsRecentTicketSet(),
      })).filter(({ set }) => set.main.length || set.special !== null);
      const filledSetCount = selectedSets.filter(set => (set?.main?.length || 0) || set?.special !== null).length;
      const isKeno = normalizedType === "KENO";
      const selectedSummary = isKeno
        ? `Bậc ${config.kenoLevel} • Bộ ${activeSetIndex + 1}: ${activeSet.main.length}/${config.mainCount}`
        : `${filledSetCount}/${config.maxSets}`;
      const hasSelection = activeSet.main.length > 0 || activeSet.special !== null;
      const renderTicketBall = (value, setIndex, role = "main") => `
        <button
          type="button"
          class="stats-modern-picked-ball ${getStatsRecent100BallClass(value, hitNumberSet, missedNumberSet, currentPredictionSet)}"
          data-stats-recent-selected-remove="${Number(value)}"
          data-stats-recent-selected-set="${Number(setIndex)}"
          data-stats-recent-selected-role="${escapeHtml(role)}"
          aria-label="Xóa số ${escapeHtml(getStatsDisplayLabel(type, value))} khỏi Bộ ${Number(setIndex) + 1}"
        >${escapeHtml(getStatsDisplayLabel(type, value))}</button>
      `;
      return `
        <section class="stats-modern-card stats-modern-selected-panel">
          <div class="stats-modern-selected-head">
            <div>
              <span class="stats-modern-selected-icon">↻</span>
              <strong>Bộ số đang chọn</strong>
              <small>(${selectedSummary})</small>
            </div>
            <div class="stats-modern-selected-actions">
              <button
                type="button"
                class="stats-modern-save-btn"
                data-stats-recent-save="1"
                ${filledSetCount ? "" : "disabled"}
              >Lưu</button>
              <button
                type="button"
                class="stats-modern-clear-btn"
                data-stats-recent-clear="1"
                ${hasSelection ? "" : "disabled"}
              >Xóa</button>
            </div>
          </div>
          <div class="stats-modern-selection-controls${isKeno ? " is-keno" : ""}">
            ${isKeno ? renderStatsRecentKenoLevelControl(config) : ""}
            <div class="stats-modern-set-tabs" aria-label="Chọn bộ số đang thao tác">
              ${Array.from({ length: config.maxSets }, (_, index) => `
                <button
                  type="button"
                  class="${index === activeSetIndex ? "is-active" : ""}"
                  data-stats-recent-active-set="${index}"
                  aria-pressed="${index === activeSetIndex ? "true" : "false"}"
                >Bộ ${index + 1}</button>
              `).join("")}
            </div>
          </div>
          <div class="stats-modern-selected-list${visibleRows.length ? "" : " is-empty"}">
            ${visibleRows.length ? visibleRows.map(({ index, set }) => `
              <div class="stats-modern-selected-row${index === activeSetIndex ? " is-active" : ""}">
                <button type="button" class="stats-modern-selected-row-label" data-stats-recent-active-set="${index}">Bộ ${index + 1}</button>
                <div class="stats-modern-selected-balls">
                  ${set.main.length ? set.main.map(value => renderTicketBall(value, index, "main")).join("") : `<span class="stats-modern-selected-placeholder">${set.main.length}/${config.mainCount}</span>`}
                  ${config.hasSpecial ? `
                    <span class="stats-modern-special-text">${escapeHtml(config.specialLabel)}:</span>
                    ${set.special !== null
                      ? renderTicketBall(set.special, index, "special")
                      : `<span class="stats-modern-selected-placeholder">--</span>`}
                  ` : ""}
                </div>
              </div>
            `).join("") : `<span class="stats-modern-selected-empty">Chọn Bộ ${activeSetIndex + 1}, rồi bấm số trong bảng tần suất.</span>`}
          </div>
        </section>
      `;
    }

    function formatStatsRefreshCountdown(ms) {
      const totalSeconds = Math.max(0, Math.ceil(Number(ms || 0) / 1000));
      const minutes = Math.floor(totalSeconds / 60);
      const seconds = totalSeconds % 60;
      return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    }

    function getStatsRefreshCountdownText() {
      if (!statsPanelNextRefreshAt) return "--:--";
      return formatStatsRefreshCountdown(statsPanelNextRefreshAt - getSyncedNowMs());
    }

    function getStatsDrawCountdownText(type = "KENO") {
      const normalizedType = normalizeStatsType(type);
      const nowValue = getSyncedNowDate();
      const nextDrawDate = typeof findNextLiveDrawDate === "function"
        ? findNextLiveDrawDate(normalizedType, nowValue)
        : null;
      if (!(nextDrawDate instanceof Date) || Number.isNaN(nextDrawDate.getTime())) return "--:--";
      return formatStatsRefreshCountdown(nextDrawDate.getTime() - nowValue.getTime());
    }

    function updateStatsRefreshCountdownText() {
      document.querySelectorAll("[data-stats-refresh-countdown]").forEach(node => {
        node.textContent = getStatsRefreshCountdownText();
      });
      document.querySelectorAll("[data-stats-draw-countdown]").forEach(node => {
        const type = String(node.getAttribute("data-stats-draw-countdown") || "KENO").trim().toUpperCase();
        node.textContent = getStatsDrawCountdownText(type || "KENO");
      });
    }

    function renderStatsKenoLiveHeading(latestEntry = null) {
      const kyText = formatLiveKy(latestEntry?.ky) || "--";
      const dateText = String(latestEntry?.draw?.date || "").trim();
      const timeText = String(latestEntry?.draw?.time || "").trim();
      const drawDateTimeText = [dateText, timeText].filter(Boolean).join(" ") || "--";
      return `
        <div class="stats-modern-keno-live-heading" aria-label="Kỳ Keno mới nhất">
          <div class="stats-modern-keno-ticket-card">
            <strong>Kỳ vé ${escapeHtml(kyText)}</strong>
            <span>Ngày ${escapeHtml(drawDateTimeText)}</span>
          </div>
          <div class="stats-modern-keno-next-card" aria-label="Thời gian tới kỳ Keno kế tiếp">
            <span>Kỳ sau:</span>
            <strong data-stats-draw-countdown="KENO">${escapeHtml(getStatsDrawCountdownText("KENO"))}</strong>
          </div>
        </div>
      `;
    }

    function renderStatsRecent100Table(title, items, valueKey = "count", { hitNumberSet = null, missedNumberSet = null, currentPredictionSet = null } = {}) {
      const safeItems = Array.isArray(items) ? items : [];
      const rowCount = Math.ceil(safeItems.length / 2);
      const rows = Array.from({ length: rowCount }, (_, rowIndex) => [
        safeItems[rowIndex],
        safeItems[rowIndex + rowCount],
      ]);
      return `
        <section class="stats-recent100-side-panel">
          <div class="stats-recent100-side-title">${escapeHtml(title)}</div>
          <div class="stats-recent100-side-rows">
            ${rows.map(rowItems => `
              <div class="stats-recent100-side-row">
                ${rowItems.map(item => item ? `
                  <span class="stats-recent100-side-cell">
                    <button
                      type="button"
                      class="stats-recent100-side-number ${getStatsRecent100BallClass(item?.value, hitNumberSet, missedNumberSet, currentPredictionSet)}"
                      data-ball="${escapeHtml(item?.label || "--")}"
                      data-stats-recent-pick="${Number(item?.value)}"
                      aria-label="Chọn số ${escapeHtml(item?.label || "--")}"
                    ></button>
                    <span class="stats-recent100-side-count">${escapeHtml(`${formatLiveSyncCount(item?.[valueKey] || 0)} lần`)}</span>
                  </span>
                ` : `<span class="stats-recent100-side-cell is-empty"></span>`).join("")}
              </div>
            `).join("")}
          </div>
        </section>
      `;
    }

    function renderStatsRecent100Panel(type, entries, {
      hitNumberSet = null,
      missedNumberSet = null,
      currentPredictionSet = null,
      currentPredictionEntry = null,
      comparisonLabel = "kỳ trước",
      comparisonContext = null,
    } = {}) {
      const sourceEntries = Array.isArray(entries) ? entries : [];
      if (!sourceEntries.length) return "";
      statsRecentModeValue = normalizeStatsRecentMode(statsRecentModeValue);
      statsRecentWindowValue = normalizeStatsRecentWindow(statsRecentWindowValue, statsRecentModeValue);
      const recentMode = statsRecentModeValue;
      const recentWindow = statsRecentWindowValue;
      const recentWindowOptions = getStatsRecentWindowOptions(recentMode);
      const { computation, pending } = getStatsRecentComputation(type, sourceEntries, recentMode, recentWindow, { preferWorker: true });
      const displayItems = computation?.displayItems || [];
      const countByValue = computation?.countByValue || new Map();
      const mostItems = computation?.mostItems || [];
      const leastItems = computation?.leastItems || [];
      const overdueItems = computation?.overdueItems || [];
      const gridClass = getStatsRecentGridClass(type);
      const currentTypeMeta = getStatsTypeUiMeta(type);
      const typeConfig = TYPES[type] || {};
      const latestEntry = sourceEntries[sourceEntries.length - 1] || null;
      const latestActualSet = buildStatsLatestActualNumberSet(type, latestEntry);
      const comparisonActualSet = comparisonContext?.actualSet instanceof Set ? comparisonContext.actualSet : latestActualSet;
      const comparisonEntry = comparisonContext?.entry || null;
      const recentEntries = filterStatsRecentEntriesByMode(sourceEntries, recentMode, recentWindow);
      const specialFrequencyItems = typeConfig.hasSpecial ? buildStatsFrequencyItems(type, recentEntries, { special: true }) : [];
      const specialCountByValue = new Map(specialFrequencyItems.map(item => [Number(item.value), Number(item.count || 0)]));
      const specialMostItems = specialFrequencyItems.slice(0, STATS_RECENT100_SIDE_LIMIT);
      const specialCurrentPredictionSet = getStatsLatestSpecialPredictionHighlight(type, latestEntry).numbers;
      const latestActualSpecialSet = buildStatsLatestActualSpecialSet(type, latestEntry);
      const specialHitSet = getStatsLatestHitSpecialPredictionSet(type, latestEntry, latestActualSpecialSet);
      const specialMissedSet = getStatsLatestMissedSpecialPredictionSet(type, latestEntry, latestActualSpecialSet);
      const fallbackPredictionSet = currentPredictionSet instanceof Set && currentPredictionSet.size
        ? new Set()
        : buildStatsRecentFallbackPredictionSet(type, { mostItems, overdueItems });
      const effectiveCurrentPredictionSet = currentPredictionSet instanceof Set && currentPredictionSet.size
        ? currentPredictionSet
        : fallbackPredictionSet;
      const isFallbackPrediction = !(currentPredictionSet instanceof Set && currentPredictionSet.size) && fallbackPredictionSet.size > 0;
      const specialMarkerSet = new Set([
        ...specialCurrentPredictionSet,
        ...specialHitSet,
        ...specialMissedSet,
        ...(type === "KENO" ? [...latestActualSet] : []),
        ...(typeConfig.hasSpecial ? specialMostItems.slice(0, 4).map(item => Number(item.value)) : []),
      ]);
      const titleText = getStatsRecentPanelTitle(recentWindow, recentMode);
      const windowBadge = getStatsRecentWindowLabel(recentWindow, recentMode);
      const mainItems = getStatsModernOrderedItems(type, countByValue, displayItems, {
        limit: TYPES[type]?.threeDigit ? 50 : null,
      });
      const specialItems = typeConfig.hasSpecial
        ? getStatsModernOrderedItems(type, specialCountByValue, specialFrequencyItems, { special: true })
        : [];
      const mainPanelTitle = TYPES[type]?.threeDigit
        ? (type === "MAX_3D_PRO" ? "Tần suất 100 kỳ gần nhất" : "Số nổi bật 3D")
        : type === "KENO"
          ? `${titleText}`
          : `Số chính (${getStatsModernRangeText(type)})`;
      const mainPanelSubtitle = TYPES[type]?.threeDigit
        ? getStatsModernRangeText(type)
        : type === "KENO"
          ? "Dải số 1 - 80"
          : "";
      const mainHeadingHtml = type === "KENO"
        ? renderStatsKenoLiveHeading(latestEntry)
        : renderStatsModernPanelTitle(type === "KENO" ? "▥" : "▥", mainPanelTitle, mainPanelSubtitle);
      return `
        <section class="stats-modern-shell ${gridClass}">
          <div class="stats-modern-top">
            <div class="stats-modern-title-wrap">
              <h2>Thống kê ${escapeHtml(currentTypeMeta.label)}</h2>
              <span>${escapeHtml(windowBadge)} gần nhất</span>
            </div>
            <div class="stats-modern-refresh-help">
              <button
                type="button"
                class="stats-recent100-refresh-timer stats-modern-refresh"
                data-stats-manual-refresh="1"
                aria-label="Cập nhật thống kê mới nhất từ MinhChính"
                ${statsPanelLoading ? "disabled" : ""}
              >
                <span>${statsPanelLoading ? "Đang cập nhật..." : "Làm mới"}</span>
              </button>
              ${renderStatsRecentHelpPopover(type)}
            </div>
          </div>

          <div class="stats-modern-controls">
            ${renderStatsModernTypePicker(type, currentTypeMeta)}
            ${renderStatsModernModePicker(recentMode)}
            ${renderStatsModernWindowButtons(recentWindowOptions, recentWindow, recentMode)}
          </div>

          <div class="stats-modern-body">
            <div class="stats-modern-left">
              <section class="stats-modern-card stats-modern-main-card">
                <div class="stats-modern-main-head ${type === "KENO" ? "is-keno-live-head" : ""}">
                  ${mainHeadingHtml}
                  ${renderStatsModernLegend(type, comparisonLabel)}
                </div>
                ${pending ? `
                  <div class="stats-modern-loading">Đang tính thống kê trong nền...</div>
                ` : `
                  ${renderStatsModernNumberGrid(type, mainItems, {
                    hitNumberSet,
                    missedNumberSet,
                    currentPredictionSet: effectiveCurrentPredictionSet,
                    specialMarkerSet,
                    showSpecialMarker: false,
                    countLabel: TYPES[type]?.threeDigit ? "lần" : "lần",
                  })}
                `}
              </section>

              ${typeConfig.hasSpecial ? `
                <section class="stats-modern-card stats-modern-special-card">
                  ${renderStatsModernPanelTitle("★", `${type === "LOTO_6_55" ? "Số ĐB T7" : "Số đặc biệt"} (${getStatsModernRangeText(type, { special: true })})`)}
                  ${renderStatsModernNumberGrid(type, specialItems, {
                    hitNumberSet: specialHitSet,
                    missedNumberSet: specialMissedSet,
                    currentPredictionSet: specialCurrentPredictionSet,
                    pickRole: "special",
                    compact: true,
                    showSpecialMarker: false,
                  })}
                </section>
              ` : ""}

              <div data-stats-recent-selected-host>
                ${renderStatsRecentSelectedPanel(type, { hitNumberSet, missedNumberSet, currentPredictionSet: effectiveCurrentPredictionSet, countByValue })}
              </div>
            </div>

            <aside class="stats-modern-right">
              ${pending ? `
                <section class="stats-modern-card">
                  ${renderStatsModernPanelTitle("…", "Đang tải")}
                  <div class="stats-modern-loading">Worker đang tính dữ liệu thống kê...</div>
                </section>
              ` : `
                ${renderStatsModernPredictionPanel(type, {
                  predictionSet: effectiveCurrentPredictionSet,
                  predictionEntry: currentPredictionEntry,
                  isFallback: isFallbackPrediction,
                  latestEntry,
                  countByValue,
                  hitNumberSet,
                  missedNumberSet,
                })}
                ${renderStatsModernInsightPanel(type, {
                  mostItems,
                  leastItems,
                  overdueItems,
                  hitNumberSet,
                  missedNumberSet,
                  currentPredictionSet: effectiveCurrentPredictionSet,
                })}
                ${renderStatsModernMetrics(type, {
                  mostItems,
                  leastItems,
                  overdueItems,
                  specialMostItems,
                  hitNumberSet,
                  missedNumberSet,
                  countByValue,
                  latestActualSet,
                  latestEntry,
                  comparisonLabel,
                  comparisonActualSet,
                  comparisonEntry,
                })}
              `}
            </aside>
          </div>
          <p class="stats-modern-footnote">Lưu ý: Thống kê mang tính chất tham khảo, không đảm bảo kết quả trúng thưởng.</p>
        </section>
      `;
    }

    function renderStatsRecentSelectedHostOnly() {
      const host = document.querySelector("[data-stats-recent-selected-host]");
      if (!host) {
        renderStatsPanel();
        return;
      }
      const type = normalizeStatsType(statsSelectedType);
      const allEntries = buildStatsEntriesForFeed(type, getLiveHistoryFeed(type));
      const latestEntry = allEntries[allEntries.length - 1] || null;
      const latestActualSet = buildStatsLatestActualNumberSet(type, latestEntry);
      const currentPredictionHighlight = getStatsLatestPredictionHighlight(type, latestEntry);
      const hitPredictionSet = getStatsLatestHitPredictionSet(type, latestEntry, latestActualSet);
      const missedPredictionSet = getStatsLatestMissedPredictionSet(type, latestEntry, latestActualSet);
      const { computation } = getStatsRecentComputation(type, allEntries, statsRecentModeValue, statsRecentWindowValue);
      const fallbackPredictionSet = currentPredictionHighlight.numbers instanceof Set && currentPredictionHighlight.numbers.size
        ? new Set()
        : buildStatsRecentFallbackPredictionSet(type, {
            mostItems: computation?.mostItems || [],
            overdueItems: computation?.overdueItems || [],
          });
      const effectiveCurrentPredictionSet = currentPredictionHighlight.numbers instanceof Set && currentPredictionHighlight.numbers.size
        ? currentPredictionHighlight.numbers
        : fallbackPredictionSet;
      host.innerHTML = renderStatsRecentSelectedPanel(type, {
        hitNumberSet: hitPredictionSet,
        missedNumberSet: missedPredictionSet,
        currentPredictionSet: effectiveCurrentPredictionSet,
        countByValue: computation?.countByValue || new Map(),
      });
    }

    function renderStatsPanel() {
      const out = document.getElementById("statsInsightsOut");
      if (!out) return;
      const type = normalizeStatsType(statsSelectedType);
      const feed = getLiveHistoryFeed(type);
      const meta = getStatsTypeUiMeta(type);
      if (statsPanelLoading && !feed?.order?.length) {
        out.classList.add("muted");
        out.innerHTML = "Đang tải dữ liệu thống kê từ all_day.csv...";
        return;
      }
      if (statsPanelError) {
        out.classList.add("muted");
        out.innerHTML = escapeHtml(statsPanelError);
        return;
      }
      if (!feed?.order?.length) {
        out.classList.add("muted");
        out.innerHTML = IS_LOCAL_MODE
          ? "Khung thống kê cần mở qua http://localhost:8080 để đọc dữ liệu all_day.csv."
          : "Chưa có dữ liệu thống kê. Hệ thống sẽ tự tải all_day.csv khi bạn mở tab này.";
        return;
      }
      const allEntries = buildStatsEntriesForFeed(type, feed);
      if (!allEntries.length) {
        out.classList.remove("muted");
        out.innerHTML = `<div class="stats-insight-empty">Không có dữ liệu ${escapeHtml(meta.label)} trong all_day.csv.</div>`;
        return;
      }
      const latestEntry = allEntries[allEntries.length - 1] || null;
      const latestActualSet = buildStatsLatestActualNumberSet(type, latestEntry);
      const currentPredictionHighlight = getStatsLatestPredictionHighlight(type, latestEntry);
      const comparisonContext = getStatsPredictionComparisonContext(type, latestEntry, latestActualSet);
      const hitPredictionSet = getStatsLatestHitPredictionSet(type, latestEntry, latestActualSet);
      const missedPredictionSet = getStatsLatestMissedPredictionSet(type, latestEntry, latestActualSet);
      out.classList.remove("muted");
      out.innerHTML = renderStatsRecent100Panel(type, allEntries, {
        hitNumberSet: hitPredictionSet,
        missedNumberSet: missedPredictionSet,
        currentPredictionSet: currentPredictionHighlight.numbers,
        currentPredictionEntry: currentPredictionHighlight.entry,
        comparisonLabel: comparisonContext.label,
        comparisonContext,
      });
    }

    async function startStatsPanelRefresh({ force = false, silent = true } = {}) {
      const type = normalizeStatsType(statsSelectedType);
      const refreshToken = ++statsPanelRefreshToken;
      statsPanelLoading = true;
      statsPanelError = "";
      renderStatsPanel();
      try {
        await fetchLiveHistory(type, "all", {
          force,
          silent,
          repair: type === "KENO",
          recentDays: type === "KENO" ? 1 : null,
        });
        if (refreshToken !== statsPanelRefreshToken) return;
        statsPanelLoading = false;
        statsPanelError = "";
      } catch (error) {
        if (refreshToken !== statsPanelRefreshToken) return;
        statsPanelLoading = false;
        statsPanelError = `Không tải được thống kê ${getStatsTypeUiMeta(type).label}: ${String(error?.message || error || "Lỗi không rõ")}`;
      } finally {
        if (refreshToken !== statsPanelRefreshToken) return;
        renderStatsPanel();
      }
    }

    function stopStatsPanelAutoRefreshTimer() {
      if (statsPanelAutoRefreshTimer) {
        window.clearInterval(statsPanelAutoRefreshTimer);
        statsPanelAutoRefreshTimer = null;
      }
      if (statsPanelCountdownTimer) {
        window.clearInterval(statsPanelCountdownTimer);
        statsPanelCountdownTimer = null;
      }
      statsPanelNextRefreshAt = 0;
      updateStatsRefreshCountdownText();
    }

    function startStatsPanelRefreshCountdownTimer() {
      if (statsPanelCountdownTimer) window.clearInterval(statsPanelCountdownTimer);
      updateStatsRefreshCountdownText();
      statsPanelCountdownTimer = window.setInterval(updateStatsRefreshCountdownText, 1000);
    }

    function syncStatsPanelAutoRefreshTimer() {
      stopStatsPanelAutoRefreshTimer();
      if (predictPageModeValue !== PREDICTION_MODE_STATS) return;
      statsPanelNextRefreshAt = getSyncedNowMs() + STATS_PANEL_AUTO_REFRESH_MS;
      startStatsPanelRefreshCountdownTimer();
      statsPanelAutoRefreshTimer = window.setInterval(() => {
        statsPanelNextRefreshAt = getSyncedNowMs() + STATS_PANEL_AUTO_REFRESH_MS;
        updateStatsRefreshCountdownText();
        if (predictPageModeValue !== PREDICTION_MODE_STATS || statsPanelLoading) return;
        startStatsPanelRefresh({ force: true, silent: true });
      }, STATS_PANEL_AUTO_REFRESH_MS);
    }

    function normalizeStatsV2Type(value) {
      const normalized = String(value || "").trim().toUpperCase();
      return TYPE_KEYS.includes(normalized) ? normalized : "LOTO_5_35";
    }

    function normalizeStatsV2Period(value) {
      const normalized = String(value || "").trim().toLowerCase();
      return STATS_V2_PERIOD_OPTIONS.some(item => item.value === normalized) ? normalized : "30d";
    }

    function normalizeStatsV2Sort(value) {
      const normalized = String(value || "").trim().toLowerCase();
      return STATS_V2_SORT_OPTIONS.some(item => item.value === normalized) ? normalized : "most";
    }

    function getStatsV2MaxComboSize(type = statsV2State?.type) {
      return normalizeStatsV2Type(type) === "KENO" ? STATS_V2_MAX_COMBO_KENO : STATS_V2_MAX_COMBO_DEFAULT;
    }

    function getStatsV2ComboOptions(type = statsV2State?.type) {
      const maxCombo = getStatsV2MaxComboSize(type);
      return STATS_V2_COMBO_OPTIONS.filter(item => item.value <= maxCombo);
    }

    function normalizeStatsV2ComboSize(value, type = statsV2State?.type) {
      const parsed = Number(value || 1);
      if (!Number.isInteger(parsed) || parsed < 1) return 1;
      return Math.min(parsed, getStatsV2MaxComboSize(type));
    }

    function normalizeStatsV2Group(value) {
      return String(value || "").trim().toLowerCase() === "special" ? "special" : "main";
    }

    function normalizeStatsV2Loto535View(value) {
      const normalized = String(value || "").trim().toLowerCase();
      return STATS_V2_LOTO535_VIEW_OPTIONS.some(item => item.value === normalized) ? normalized : "frequency";
    }

    function getStatsV2EffectiveGroup() {
      const type = normalizeStatsV2Type(statsV2State.type);
      if (type === "LOTO_5_35" && statsV2State.loto535View === "frequency") {
        return normalizeStatsV2Group(statsV2State.group);
      }
      return "main";
    }

    function restoreStatsV2UiState() {
      const saved = readJsonLocal(STATS_V2_UI_KEY, {});
      statsV2State.type = normalizeStatsV2Type(saved.type || statsV2State.type);
      statsV2State.period = normalizeStatsV2Period(saved.period || statsV2State.period);
      statsV2State.sort = normalizeStatsV2Sort(saved.sort || statsV2State.sort);
      statsV2State.comboSize = normalizeStatsV2ComboSize(saved.comboSize || statsV2State.comboSize, statsV2State.type);
      statsV2State.group = normalizeStatsV2Group(saved.group || statsV2State.group);
      statsV2State.loto535View = normalizeStatsV2Loto535View(saved.loto535View || statsV2State.loto535View);
      statsV2State.from = String(saved.from || "");
      statsV2State.to = String(saved.to || "");
      statsV2State.autoRefresh = !!saved.autoRefresh;
      if (getStatsV2EffectiveGroup() === "special") statsV2State.comboSize = 1;
    }

    function saveStatsV2UiState() {
      writeJsonLocal(STATS_V2_UI_KEY, {
        type: statsV2State.type,
        period: statsV2State.period,
        sort: statsV2State.sort,
        comboSize: statsV2State.comboSize,
        group: statsV2State.group,
        loto535View: statsV2State.loto535View,
        from: statsV2State.from,
        to: statsV2State.to,
        autoRefresh: !!statsV2State.autoRefresh,
      });
    }

    function clearStatsV2Selection() {
      statsV2State.selected = [];
      renderStatsV2Selection();
    }

    function renderStatsV2Controls() {
      const typeSelect = document.getElementById("statsV2TypeSelect");
      if (typeSelect) {
        typeSelect.innerHTML = TYPE_KEYS.map(key => `<option value="${escapeHtml(key)}">${escapeHtml(TYPES[key]?.label || key)}</option>`).join("");
        typeSelect.value = normalizeStatsV2Type(statsV2State.type);
        if (typeof typeSelect.__syncCustomSelect === "function") typeSelect.__syncCustomSelect();
      }
      const periodTabs = document.getElementById("statsV2PeriodTabs");
      if (periodTabs) {
        periodTabs.innerHTML = STATS_V2_PERIOD_OPTIONS.map(item => {
          const active = item.value === statsV2State.period;
          return `<button type="button" class="stats-v2-tab${active ? " is-active" : ""}" data-stats-v2-period="${escapeHtml(item.value)}" role="tab" aria-selected="${active ? "true" : "false"}">${escapeHtml(item.label)}</button>`;
        }).join("");
      }
      const customRange = document.getElementById("statsV2CustomRange");
      if (customRange) customRange.hidden = statsV2State.period !== "custom";
      const fromInput = document.getElementById("statsV2DateFrom");
      const toInput = document.getElementById("statsV2DateTo");
      if (fromInput && fromInput.value !== statsV2State.from) fromInput.value = statsV2State.from;
      if (toInput && toInput.value !== statsV2State.to) toInput.value = statsV2State.to;
      const sortSelect = document.getElementById("statsV2SortSelect");
      if (sortSelect) {
        sortSelect.innerHTML = STATS_V2_SORT_OPTIONS.map(item => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`).join("");
        sortSelect.value = normalizeStatsV2Sort(statsV2State.sort);
        if (typeof sortSelect.__syncCustomSelect === "function") sortSelect.__syncCustomSelect();
      }
      const effectiveGroup = getStatsV2EffectiveGroup();
      const comboTabs = document.getElementById("statsV2ComboTabs");
      if (comboTabs) {
        statsV2State.comboSize = effectiveGroup === "special" ? 1 : normalizeStatsV2ComboSize(statsV2State.comboSize, statsV2State.type);
        const comboOptions = effectiveGroup === "special" ? STATS_V2_COMBO_OPTIONS.slice(0, 1) : getStatsV2ComboOptions(statsV2State.type);
        comboTabs.style.setProperty("--stats-v2-combo-columns", String(Math.min(5, Math.max(1, comboOptions.length))));
        comboTabs.innerHTML = comboOptions.map(item => {
          const disabled = effectiveGroup === "special" && item.value !== 1;
          const active = item.value === statsV2State.comboSize;
          return `<button type="button" class="stats-v2-tab${active ? " is-active" : ""}" data-stats-v2-combo="${item.value}" role="tab" aria-selected="${active ? "true" : "false"}"${disabled ? " disabled" : ""}>${escapeHtml(item.label)}</button>`;
        }).join("");
      }
      const lotoTabs = document.getElementById("statsV2Loto535Tabs");
      if (lotoTabs) {
        const isLoto535 = normalizeStatsV2Type(statsV2State.type) === "LOTO_5_35";
        lotoTabs.hidden = !isLoto535;
        lotoTabs.innerHTML = STATS_V2_LOTO535_VIEW_OPTIONS.map(item => {
          const active = item.value === statsV2State.loto535View;
          return `<button type="button" class="stats-v2-tab${active ? " is-active" : ""}" data-stats-v2-loto535-view="${escapeHtml(item.value)}" role="tab" aria-selected="${active ? "true" : "false"}">${escapeHtml(item.label)}</button>`;
        }).join("");
      }
      const autoInput = document.getElementById("statsV2AutoRefresh");
      if (autoInput) autoInput.checked = !!statsV2State.autoRefresh;
    }

    function setStatsV2Status(message = "", tone = "warn") {
      const status = document.getElementById("statsV2Status");
      if (!status) return;
      status.hidden = !message;
      status.textContent = message;
      status.classList.toggle("is-ok", tone === "ok");
    }

    function buildStatsV2Query() {
      const params = new URLSearchParams();
      params.set("type", normalizeStatsV2Type(statsV2State.type));
      params.set("period", normalizeStatsV2Period(statsV2State.period));
      params.set("group", getStatsV2EffectiveGroup());
      params.set("comboSize", String(getStatsV2EffectiveGroup() === "special" ? 1 : normalizeStatsV2ComboSize(statsV2State.comboSize, statsV2State.type)));
      params.set("sort", normalizeStatsV2Sort(statsV2State.sort));
      if (statsV2State.period === "custom") {
        if (statsV2State.from) params.set("from", statsV2State.from);
        if (statsV2State.to) params.set("to", statsV2State.to);
      }
      return params;
    }

    async function loadStatsV2({ force = false, silent = true } = {}) {
      const refreshToken = ++statsV2State.refreshToken;
      statsV2State.loading = true;
      statsV2State.error = "";
      if (force) statsV2State.payload = null;
      if (!silent) statsV2State.message = "";
      renderStatsV2Panel();
      try {
        const params = buildStatsV2Query();
        if (force) params.set("force", "1");
        const res = await api(`/api/stats-v2?${params.toString()}`);
        if (refreshToken !== statsV2State.refreshToken) return;
        statsV2State.payload = res;
        statsV2State.loading = false;
        statsV2State.error = "";
        statsV2State.message = "";
      } catch (error) {
        if (refreshToken !== statsV2State.refreshToken) return;
        statsV2State.loading = false;
        statsV2State.error = String(error?.message || error || "Không tải được Thống Kê V2.");
      } finally {
        if (refreshToken !== statsV2State.refreshToken) return;
        renderStatsV2Panel();
      }
    }

    function formatStatsV2Metric(value, fallback = "--") {
      if (value == null || value === "") return fallback;
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) return String(value);
      if (Math.abs(numeric) < 1 && numeric > 0) return `${(numeric * 100).toFixed(2)}%`;
      return numeric.toLocaleString("vi-VN", { maximumFractionDigits: 2 });
    }

    function formatStatsV2UpdatedAt(value) {
      const text = String(value || "").trim();
      if (!text) return "Chưa tải";
      const match = text.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})(?::\d{2})?/);
      if (match) return `Cập nhật ${match[4]} • ${match[3]}/${match[2]}`;
      return `Cập nhật ${text}`;
    }

    function renderStatsV2Balls(item, group = "main") {
      const numbers = Array.isArray(item?.numbers) ? item.numbers : [item?.label || item?.key || ""];
      const specialClass = group === "special" ? " is-special" : "";
      return `<div class="stats-v2-ball-stack">${numbers.map(number => `<span class="stats-v2-ball${specialClass}">${escapeHtml(number)}</span>`).join("")}</div>`;
    }

    function renderStatsV2GroupTabs() {
      if (normalizeStatsV2Type(statsV2State.type) !== "LOTO_5_35" || statsV2State.loto535View !== "frequency") return "";
      const items = [
        { value: "main", label: "Số chính 01-35" },
        { value: "special", label: "Số đặc biệt 01-12" },
      ];
      return `<div class="stats-v2-subtabs">${items.map(item => {
        const active = item.value === getStatsV2EffectiveGroup();
        return `<button type="button" class="stats-v2-tab${active ? " is-active" : ""}" data-stats-v2-group="${escapeHtml(item.value)}" role="tab" aria-selected="${active ? "true" : "false"}">${escapeHtml(item.label)}</button>`;
      }).join("")}</div>`;
    }

    function renderStatsV2Summary(payload) {
      const items = [
        ["Số kỳ", formatLiveSyncCount(payload?.totalDraws || 0)],
        ["Từ ngày", payload?.filteredFrom || "--"],
        ["Đến ngày", payload?.filteredTo || "--"],
        ["Nguồn", payload?.sourceFile || "--"],
      ];
      return `<div class="stats-v2-summary">${items.map(([label, value]) => `
        <div class="stats-v2-summary-item">
          <div class="stats-v2-summary-label">${escapeHtml(label)}</div>
          <div class="stats-v2-summary-value">${escapeHtml(value)}</div>
        </div>
      `).join("")}</div>`;
    }

    function renderStatsV2Loto535Footer(payload) {
      const summary = payload?.loto535Summary || {};
      const cards = [
        ["Số chính ra nhiều nhất", summary.mainMost],
        ["Số chính ra ít nhất", summary.mainLeast],
        ["Số chính ra liên tiếp", summary.mainCurrentStreak],
      ];
      return `<div class="stats-v2-summary">${cards.map(([label, item]) => `
        <div class="stats-v2-summary-item">
          <div class="stats-v2-summary-label">${escapeHtml(label)}</div>
          <div class="stats-v2-summary-value">${escapeHtml(item?.label || "--")}</div>
          <div class="stats-v2-row-meta">${escapeHtml(item ? `${formatLiveSyncCount(item.count)} lần • streak ${formatLiveSyncCount(item.currentStreak || item.maxStreak || 0)}` : "")}</div>
        </div>
      `).join("")}</div>`;
    }

    function renderStatsV2Frequency(payload) {
      const items = Array.isArray(payload?.items) ? payload.items : [];
      if (!items.length) return `<div class="stats-insight-empty">Không có dữ liệu phù hợp.</div>`;
      const maxCount = Math.max(1, ...items.map(item => Number(item.count || 0)));
      const group = payload?.params?.group || getStatsV2EffectiveGroup();
      const tableMode = normalizeStatsV2Type(statsV2State.type) === "LOTO_5_35" && Number(payload?.params?.comboSize || 1) === 1;
      const rows = items.map(item => {
        const selected = statsV2State.selected.some(entry => entry.key === item.key);
        const percent = Math.max(2, Math.round((Number(item.count || 0) / maxCount) * 100));
        return `
          <div class="stats-v2-row${selected ? " is-selected" : ""}" data-stats-v2-item="${escapeHtml(item.key)}">
            ${renderStatsV2Balls(item, group)}
            <div class="stats-v2-bar-wrap">
              <div class="stats-v2-bar-track"><div class="stats-v2-bar-fill" style="width:${percent}%"></div></div>
              <div class="stats-v2-row-meta">${escapeHtml(`TB ${formatStatsV2Metric(item.avgCycle)} kỳ • Chưa về ${formatLiveSyncCount(item.currentGap || 0)} kỳ • Streak ${formatLiveSyncCount(item.currentStreak || 0)}`)}</div>
            </div>
            <div class="stats-v2-count">${escapeHtml(`${formatLiveSyncCount(item.count || 0)} lần`)}</div>
          </div>
        `;
      }).join("");
      const table = tableMode ? `
        <div class="stats-v2-table-wrap">
          <table class="stats-v2-table">
            <thead><tr><th>Số</th><th>Số lần về</th><th>Trung bình số kỳ về</th><th>Số kỳ chưa về</th></tr></thead>
            <tbody>${items.map(item => `
              <tr data-stats-v2-item="${escapeHtml(item.key)}">
                <td>${renderStatsV2Balls(item, group)}</td>
                <td>${escapeHtml(formatLiveSyncCount(item.count || 0))}</td>
                <td>${escapeHtml(formatStatsV2Metric(item.avgCycle))}</td>
                <td>${escapeHtml(formatLiveSyncCount(item.currentGap || 0))}</td>
              </tr>
            `).join("")}</tbody>
          </table>
        </div>
      ` : "";
      return `
        ${renderStatsV2GroupTabs()}
        <div class="stats-v2-list">${rows}</div>
        ${table}
        ${normalizeStatsV2Type(statsV2State.type) === "LOTO_5_35" ? renderStatsV2Loto535Footer(payload) : ""}
      `;
    }

    function renderStatsV2Jackpot(payload) {
      const jackpot = payload?.jackpot || {};
      return `
        <div class="stats-v2-jackpot">
          <div class="stats-v2-jackpot-title">${escapeHtml(jackpot.title || "Giá trị Độc đắc")}</div>
          <div class="stats-v2-jackpot-value">${escapeHtml(jackpot.value || "Tối thiểu 6 tỷ và tích lũy")}</div>
          <div class="stats-v2-jackpot-note">${escapeHtml(jackpot.note || "")}</div>
        </div>
        ${renderStatsV2Loto535Footer(payload)}
      `;
    }

    function renderStatsV2Panel() {
      const out = document.getElementById("statsV2Out");
      if (!out) return;
      statsV2State.type = normalizeStatsV2Type(statsV2State.type);
      statsV2State.period = normalizeStatsV2Period(statsV2State.period);
      statsV2State.sort = normalizeStatsV2Sort(statsV2State.sort);
      statsV2State.comboSize = getStatsV2EffectiveGroup() === "special" ? 1 : normalizeStatsV2ComboSize(statsV2State.comboSize, statsV2State.type);
      renderStatsV2Controls();
      renderStatsV2Selection();
      syncStatsV2AutoRefreshTimer();
      const updated = document.getElementById("statsV2UpdatedAt");
      if (updated) updated.textContent = formatStatsV2UpdatedAt(statsV2State.payload?.generatedAt || "");
      setStatsV2Status(statsV2State.message || "");
      if (statsV2State.loading && !statsV2State.payload) {
        out.classList.add("muted");
        out.innerHTML = "Đang tải Thống Kê V2...";
        return;
      }
      if (statsV2State.error) {
        out.classList.add("muted");
        out.innerHTML = escapeHtml(statsV2State.error);
        return;
      }
      const payload = statsV2State.payload;
      if (!payload) {
        out.classList.add("muted");
        out.innerHTML = "Chọn tab Thống Kê V2 để tải dữ liệu.";
        return;
      }
      if (payload.supported === false) {
        out.classList.add("muted");
        out.innerHTML = escapeHtml(payload.message || "Loại này chưa hỗ trợ đầy đủ.");
        return;
      }
      out.classList.remove("muted");
      const showJackpot = normalizeStatsV2Type(statsV2State.type) === "LOTO_5_35" && statsV2State.loto535View === "jackpot";
      out.innerHTML = `
        ${renderStatsV2Summary(payload)}
        ${showJackpot ? renderStatsV2Jackpot(payload) : renderStatsV2Frequency(payload)}
      `;
    }

    function getStatsV2PayloadItem(key) {
      const items = Array.isArray(statsV2State.payload?.items) ? statsV2State.payload.items : [];
      return items.find(item => String(item.key) === String(key)) || null;
    }

    function toggleStatsV2Selection(key) {
      const item = getStatsV2PayloadItem(key);
      if (!item) return;
      const index = statsV2State.selected.findIndex(entry => entry.key === item.key);
      if (index >= 0) {
        statsV2State.selected.splice(index, 1);
      } else {
        statsV2State.selected.push({
          key: item.key,
          label: item.label,
          numbers: Array.isArray(item.numbers) ? item.numbers : [],
          type: normalizeStatsV2Type(statsV2State.type),
          group: statsV2State.payload?.params?.group || getStatsV2EffectiveGroup(),
          comboSize: Number(statsV2State.payload?.params?.comboSize || statsV2State.comboSize || 1),
        });
      }
      renderStatsV2Panel();
    }

    function renderStatsV2Selection() {
      const text = document.getElementById("statsV2SelectedText");
      const saveBtn = document.getElementById("statsV2SaveBtn");
      const buyBtn = document.getElementById("statsV2BuyBtn");
      const hasSelection = statsV2State.selected.length > 0;
      if (text) {
        text.textContent = hasSelection
          ? statsV2State.selected.map(item => item.label || item.key).join(", ")
          : "Bạn chưa chọn số nào";
      }
      if (saveBtn) saveBtn.disabled = !hasSelection;
      if (buyBtn) buyBtn.disabled = !hasSelection;
    }

    function buildStatsV2UserSelection(action) {
      return {
        id: `statsv2_${Date.now()}_${Math.random().toString(16).slice(2)}`,
        action,
        createdAt: getSyncedIsoString(),
        type: normalizeStatsV2Type(statsV2State.type),
        period: statsV2State.period,
        sort: statsV2State.sort,
        group: statsV2State.payload?.params?.group || getStatsV2EffectiveGroup(),
        comboSize: Number(statsV2State.payload?.params?.comboSize || statsV2State.comboSize || 1),
        selected: statsV2State.selected.map(item => ({
          key: item.key,
          label: item.label,
          numbers: Array.isArray(item.numbers) ? item.numbers : [],
        })),
      };
    }

    function addStatsV2History(action = "select") {
      if (!statsV2State.selected.length) return null;
      if (!Array.isArray(store.statsV2History)) store.statsV2History = [];
      const entry = buildStatsV2UserSelection(action);
      store.statsV2History.unshift(entry);
      while (store.statsV2History.length > MAX_STATS_V2_HISTORY) store.statsV2History.pop();
      saveStore();
      return entry;
    }

    function saveStatsV2Favorite() {
      if (!statsV2State.selected.length) return;
      if (!Array.isArray(store.statsV2Favorites)) store.statsV2Favorites = [];
      const entry = buildStatsV2UserSelection("favorite");
      store.statsV2Favorites.unshift(entry);
      while (store.statsV2Favorites.length > MAX_STATS_V2_FAVORITES) store.statsV2Favorites.pop();
      addStatsV2History("favorite");
      saveStore();
      statsV2State.message = "Đã lưu lựa chọn vào yêu thích.";
      renderStatsV2Panel();
    }

    function buyStatsV2Selection() {
      if (!statsV2State.selected.length) return;
      addStatsV2History("buy");
      statsV2State.message = "Đã ghi nhận lựa chọn mua ngay.";
      renderStatsV2Panel();
    }

    function syncStatsV2AutoRefreshTimer() {
      if (statsV2State.timer) {
        clearInterval(statsV2State.timer);
        statsV2State.timer = null;
      }
      if (!statsV2State.autoRefresh || predictPageModeValue !== PREDICTION_MODE_STATS_V2) return;
      statsV2State.timer = setInterval(() => {
        loadStatsV2({ force: true, silent: true });
      }, STATS_V2_AUTO_REFRESH_MS);
    }

    function refreshStatsV2AfterLiveUpdate() {
      if (predictPageModeValue !== PREDICTION_MODE_STATS_V2) return;
      loadStatsV2({ force: true, silent: true });
    }

    function normalizeAnalysisType(value) {
      const normalized = String(value || "").trim().toUpperCase();
      return TYPE_KEYS.includes(normalized) ? normalized : "LOTO_5_35";
    }

    function normalizeAnalysisPeriod(value) {
      const normalized = String(value || "").trim().toLowerCase();
      return ANALYSIS_PERIOD_OPTIONS.some(item => item.value === normalized) ? normalized : "30d";
    }

    function normalizeAnalysisMode(value) {
      const normalized = String(value || "").trim().toLowerCase().replace(/-/g, "_");
      return ANALYSIS_MODE_OPTIONS.some(item => item.value === normalized) ? normalized : "overview";
    }

    function clampAnalysisInt(value, fallback, min, max) {
      const parsed = Number(value);
      if (!Number.isFinite(parsed)) return fallback;
      return Math.max(min, Math.min(max, Math.floor(parsed)));
    }

    function restoreAnalysisUiState() {
      const saved = readJsonLocal(ANALYSIS_UI_KEY, {});
      analysisState.type = normalizeAnalysisType(saved.type || analysisState.type);
      analysisState.period = normalizeAnalysisPeriod(saved.period || analysisState.period);
      analysisState.mode = normalizeAnalysisMode(saved.mode || analysisState.mode);
      analysisState.from = String(saved.from || "");
      analysisState.to = String(saved.to || "");
      analysisState.limit = clampAnalysisInt(saved.limit, analysisState.limit, 1, 100);
      analysisState.k = clampAnalysisInt(saved.k, analysisState.k, 1, 20);
      analysisState.comboSize = clampAnalysisInt(saved.comboSize, analysisState.comboSize, 1, 3);
      analysisState.includeSpecial = saved.includeSpecial !== false;
      analysisState.autoRefresh = !!saved.autoRefresh;
    }

    function saveAnalysisUiState() {
      writeJsonLocal(ANALYSIS_UI_KEY, {
        type: analysisState.type,
        period: analysisState.period,
        from: analysisState.from,
        to: analysisState.to,
        mode: analysisState.mode,
        limit: analysisState.limit,
        k: analysisState.k,
        comboSize: analysisState.comboSize,
        includeSpecial: !!analysisState.includeSpecial,
        autoRefresh: !!analysisState.autoRefresh,
      });
    }

    function initAnalysisPanel() {
      analysisState.type = normalizeAnalysisType(analysisState.type);
      analysisState.period = normalizeAnalysisPeriod(analysisState.period);
      analysisState.mode = normalizeAnalysisMode(analysisState.mode);
      const typeSelect = document.getElementById("analysisTypeSelect");
      if (typeSelect) {
        typeSelect.innerHTML = TYPE_KEYS.map(key => `<option value="${escapeHtml(key)}">${escapeHtml(TYPES[key]?.label || key)}</option>`).join("");
        typeSelect.value = analysisState.type;
        if (typeof typeSelect.__syncCustomSelect === "function") typeSelect.__syncCustomSelect();
      }
      const periodSelect = document.getElementById("analysisPeriodSelect");
      if (periodSelect) {
        periodSelect.innerHTML = ANALYSIS_PERIOD_OPTIONS.map(item => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`).join("");
        periodSelect.value = analysisState.period;
        if (typeof periodSelect.__syncCustomSelect === "function") periodSelect.__syncCustomSelect();
      }
      const modeSelect = document.getElementById("analysisModeSelect");
      if (modeSelect) {
        modeSelect.innerHTML = ANALYSIS_MODE_OPTIONS.map(item => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`).join("");
        modeSelect.value = analysisState.mode;
        if (typeof modeSelect.__syncCustomSelect === "function") modeSelect.__syncCustomSelect();
      }
      const customRange = document.getElementById("analysisCustomRange");
      if (customRange) customRange.hidden = analysisState.period !== "custom";
      const fromInput = document.getElementById("analysisDateFrom");
      const toInput = document.getElementById("analysisDateTo");
      if (fromInput && fromInput.value !== analysisState.from) fromInput.value = analysisState.from;
      if (toInput && toInput.value !== analysisState.to) toInput.value = analysisState.to;
      const limitInput = document.getElementById("analysisLimitInput");
      const kInput = document.getElementById("analysisKInput");
      const comboInput = document.getElementById("analysisComboSizeInput");
      if (limitInput) limitInput.value = String(analysisState.limit);
      if (kInput) kInput.value = String(analysisState.k);
      if (comboInput) comboInput.value = String(analysisState.comboSize);
      const autoInput = document.getElementById("analysisAutoRefresh");
      if (autoInput) autoInput.checked = !!analysisState.autoRefresh;
    }

    function buildAnalysisQuery() {
      const params = new URLSearchParams();
      params.set("type", normalizeAnalysisType(analysisState.type));
      params.set("period", normalizeAnalysisPeriod(analysisState.period));
      params.set("mode", normalizeAnalysisMode(analysisState.mode));
      params.set("limit", String(clampAnalysisInt(analysisState.limit, 20, 1, 100)));
      params.set("k", String(clampAnalysisInt(analysisState.k, 5, 1, 20)));
      params.set("comboSize", String(clampAnalysisInt(analysisState.comboSize, 2, 1, 3)));
      params.set("includeSpecial", analysisState.includeSpecial ? "true" : "false");
      if (analysisState.period === "custom") {
        if (analysisState.from) params.set("from", analysisState.from);
        if (analysisState.to) params.set("to", analysisState.to);
      }
      return params;
    }

    async function loadAnalysis({ force = false, silent = true } = {}) {
      const refreshToken = ++analysisState.refreshToken;
      analysisState.loading = true;
      analysisState.error = "";
      if (force) analysisState.lastPayload = null;
      renderAnalysis(analysisState.lastPayload);
      try {
        const params = buildAnalysisQuery();
        const payload = await api(`/api/analysis?${params.toString()}`);
        if (refreshToken !== analysisState.refreshToken) return;
        analysisState.lastPayload = payload;
        analysisState.loading = false;
        analysisState.error = payload?.ok === false ? String(payload.message || "Không phân tích được dữ liệu.") : "";
      } catch (error) {
        if (refreshToken !== analysisState.refreshToken) return;
        analysisState.loading = false;
        analysisState.error = String(error?.message || error || "Không tải được Phân Tích.");
      } finally {
        if (refreshToken !== analysisState.refreshToken) return;
        renderAnalysis(analysisState.lastPayload);
      }
    }

    function formatAnalysisModeLabel(mode) {
      return ANALYSIS_MODE_OPTIONS.find(item => item.value === normalizeAnalysisMode(mode))?.label || "Tổng quan";
    }

    function formatAnalysisValue(value, fallback = "--") {
      if (value == null || value === "") return fallback;
      if (Array.isArray(value)) return value.join(", ");
      if (typeof value === "number") return value.toLocaleString("vi-VN", { maximumFractionDigits: 3 });
      return String(value);
    }

    function renderAnalysisChips(values, empty = "--") {
      const list = Array.isArray(values) ? values : [];
      if (!list.length) return `<span class="analysis-chip is-muted">${escapeHtml(empty)}</span>`;
      return list.map(value => `<span class="analysis-chip">${escapeHtml(formatAnalysisValue(value))}</span>`).join("");
    }

    function renderAnalysisMetricCards(items) {
      return (items || []).map(item => `
        <article class="analysis-card">
          <div class="analysis-card-title">${escapeHtml(item.label)}</div>
          <div class="analysis-card-value">${escapeHtml(formatAnalysisValue(item.value))}</div>
          ${item.meta ? `<div class="analysis-card-meta">${escapeHtml(item.meta)}</div>` : ""}
        </article>
      `).join("");
    }

    function renderAnalysisSimpleTable(headers, rows) {
      if (!Array.isArray(rows) || !rows.length) return `<div class="analysis-empty">Chưa có dữ liệu phù hợp.</div>`;
      return `
        <div class="analysis-table-wrap">
          <table class="analysis-table">
            <thead><tr>${headers.map(header => `<th>${escapeHtml(header.label)}</th>`).join("")}</tr></thead>
            <tbody>${rows.map(row => `
              <tr>${headers.map(header => `<td>${escapeHtml(formatAnalysisValue(row[header.key]))}</td>`).join("")}</tr>
            `).join("")}</tbody>
          </table>
        </div>
      `;
    }

    function renderAnalysisNumberCountList(items, numberKey = "number", countKey = "count") {
      const rows = (Array.isArray(items) ? items : []).map(item => ({
        number: item[numberKey] || item.combo || item.pair || item.triple || "",
        count: item[countKey] ?? item.observed ?? "",
        status: item.status || item.hotColdStatus || "",
      }));
      return renderAnalysisSimpleTable([
        { key: "number", label: "Số / Nhóm" },
        { key: "count", label: "Số lần" },
        { key: "status", label: "Trạng thái" },
      ], rows);
    }

    function renderAnalysis(payload = analysisState.lastPayload) {
      initAnalysisPanel();
      const status = document.getElementById("analysisStatus");
      const out = document.getElementById("analysisOut");
      const summary = document.getElementById("analysisSummaryCards");
      const detail = document.getElementById("analysisDetailPanel");
      const updated = document.getElementById("analysisUpdatedAt");
      if (!detail || !summary || !out) return;
      if (updated) updated.textContent = payload?.generatedAt ? formatStatsV2UpdatedAt(payload.generatedAt) : "Chưa tải";
      const warningLines = [];
      if (analysisState.error) warningLines.push(analysisState.error);
      if (Array.isArray(payload?.warnings)) warningLines.push(...payload.warnings);
      if (status) {
        status.hidden = !warningLines.length;
        status.textContent = warningLines.join(" • ");
      }
      out.innerHTML = (Array.isArray(payload?.explanations) && payload.explanations.length)
        ? payload.explanations.map(text => `<div>${escapeHtml(text)}</div>`).join("")
        : `<div>${escapeHtml("Đây là phân tích thống kê tham khảo, không cam kết dự đoán trúng.")}</div>`;
      if (analysisState.loading && !payload) {
        summary.innerHTML = "";
        detail.className = "analysis-detail-panel muted";
        detail.innerHTML = "Đang tải Phân Tích...";
        return;
      }
      if (analysisState.error && (!payload || payload.ok === false)) {
        summary.innerHTML = "";
        detail.className = "analysis-detail-panel muted";
        detail.innerHTML = escapeHtml(analysisState.error);
        return;
      }
      if (!payload) {
        summary.innerHTML = "";
        detail.className = "analysis-detail-panel muted";
        detail.innerHTML = "Chọn tab Phân Tích để tải dữ liệu.";
        return;
      }
      const latest = payload.latestDraw || {};
      summary.innerHTML = renderAnalysisMetricCards([
        { label: "Loại vé", value: TYPES[payload.type]?.label || payload.type },
        { label: "Chế độ", value: formatAnalysisModeLabel(payload.mode) },
        { label: "Số kỳ", value: payload.totalDraws || 0, meta: `${payload.fromDate || "--"} đến ${payload.toDate || "--"}` },
        { label: "Kỳ mới nhất", value: latest.drawId || "--", meta: latest.date || "--" },
      ]);
      detail.className = "analysis-detail-panel";
      const mode = normalizeAnalysisMode(payload.mode);
      const renderer = {
        overview: renderAnalysisOverview,
        general: renderAnalysisGeneral,
        distribution: renderAnalysisDistribution,
        ratios: renderAnalysisRatios,
        latest_draw: renderAnalysisLatestDraw,
        consecutive: renderAnalysisConsecutive,
        overdue: renderAnalysisOverdue,
        poisson: renderAnalysisPoisson,
        knn: renderAnalysisKnn,
        chain: renderAnalysisChain,
        relationships: renderAnalysisRelationships,
        modulo: renderAnalysisModulo,
        advanced: renderAnalysisAdvanced,
        special: renderAnalysisSpecial,
        weekday: renderAnalysisWeekday,
        smart_wheel: renderAnalysisSmartWheel,
        score: renderAnalysisScore,
        all: renderAnalysisAll,
      }[mode] || renderAnalysisOverview;
      detail.innerHTML = renderer(payload);
    }

    function renderAnalysisOverview(payload) {
      const data = payload?.data || {};
      return `
        <div class="analysis-section-grid">
          <section class="analysis-card"><div class="analysis-card-title">Số nóng</div><div class="analysis-chip-row">${renderAnalysisChips((data.hotNumbers || []).slice(0, 10).map(item => `${item.number} (${item.count})`))}</div></section>
          <section class="analysis-card"><div class="analysis-card-title">Số lạnh</div><div class="analysis-chip-row">${renderAnalysisChips((data.coldNumbers || []).slice(0, 10).map(item => `${item.number} (${item.count})`))}</div></section>
          <section class="analysis-card"><div class="analysis-card-title">Gan lâu</div><div class="analysis-chip-row">${renderAnalysisChips((data.longestOverdue || []).slice(0, 8).map(item => `${item.number}: ${item.currentSkip} kỳ`))}</div></section>
        </div>
        <h3 class="analysis-panel-title">Top cặp</h3>
        ${renderAnalysisNumberCountList(data.topPairs || [], "combo", "count")}
        <h3 class="analysis-panel-title">Top bộ ba</h3>
        ${renderAnalysisNumberCountList(data.topTriples || [], "combo", "count")}
      `;
    }

    function renderAnalysisGeneral(payload) {
      const d = payload?.data || {};
      return `<div class="analysis-grid">${renderAnalysisMetricCards([
        { label: "Tổng", value: d.sum },
        { label: "Trung bình", value: d.mean },
        { label: "Độ lệch chuẩn", value: d.standardDeviation },
        { label: "Biên độ", value: d.span, meta: `Range: ${d.rangeStatus || "--"}` },
        { label: "Số nhỏ nhất", value: d.minNumber },
        { label: "Số lớn nhất", value: d.maxNumber, meta: `Sum: ${d.sumStatus || "--"}` },
      ])}</div>`;
    }

    function renderAnalysisDistribution(payload) {
      const d = payload?.data || {};
      return `
        <div class="analysis-badge-row">
          <span class="analysis-badge">Expected ${escapeHtml(formatAnalysisValue(d.expectedCount))}</span>
          <span class="analysis-badge">Chi-square ${escapeHtml(formatAnalysisValue(d.chiSquare))}</span>
          <span class="analysis-badge">p-value ${escapeHtml(formatAnalysisValue(d.pValue))}</span>
        </div>
        ${renderAnalysisSimpleTable([
          { key: "number", label: "Số" },
          { key: "observed", label: "Thực tế" },
          { key: "expected", label: "Kỳ vọng" },
          { key: "deviation", label: "Lệch" },
          { key: "status", label: "Trạng thái" },
        ], d.items || [])}
      `;
    }

    function renderAnalysisRatios(payload) {
      const d = payload?.data || {};
      return `
        <div class="analysis-grid">${renderAnalysisMetricCards([
          { label: "Chẵn/Lẻ", value: d.evenOddRatio, meta: `${d.evenCount || 0} chẵn • ${d.oddCount || 0} lẻ` },
          { label: "Thấp/Cao", value: d.lowHighRatio, meta: `${d.lowCount || 0} thấp • ${d.highCount || 0} cao` },
          { label: "Trạng thái", value: d.ratioStatus || "--" },
          { label: "Vùng trống", value: (d.blankZones || []).length },
        ])}</div>
        <div class="analysis-chip-row">${renderAnalysisChips(d.blankZones || [], "Không có vùng trống")}</div>
      `;
    }

    function renderAnalysisLatestDraw(payload) {
      const d = payload?.data || {};
      return `
        <div class="analysis-card">
          <div class="analysis-card-title">Kỳ mới nhất</div>
          <div class="analysis-chip-row">${renderAnalysisChips(d.latestDraw?.numbers || [])}</div>
        </div>
        <div class="analysis-section-grid">
          <section class="analysis-card"><div class="analysis-card-title">Lặp từ kỳ trước</div><div class="analysis-chip-row">${renderAnalysisChips(d.repeatedFromPrevious || [])}</div></section>
          <section class="analysis-card"><div class="analysis-card-title">Slide ±1</div><div class="analysis-chip-row">${renderAnalysisChips(d.slideNumbers || [])}</div></section>
        </div>
      `;
    }

    function renderAnalysisConsecutive(payload) {
      const d = payload?.data || {};
      return `
        <div class="analysis-grid">${renderAnalysisMetricCards([
          { label: "Chuỗi dài nhất", value: d.maxConsecutiveLength || 0 },
          { label: "Trạng thái", value: d.sequenceRiskStatus || "--" },
          { label: "Có chuỗi dài", value: d.hasLongSequence ? "Có" : "Không" },
        ])}</div>
        <h3 class="analysis-panel-title">Cặp liên tiếp</h3>
        <div class="analysis-chip-row">${renderAnalysisChips((d.consecutivePairs || []).map(item => item.join("-")))}</div>
        <h3 class="analysis-panel-title">Bộ ba liên tiếp</h3>
        <div class="analysis-chip-row">${renderAnalysisChips((d.consecutiveTriples || []).map(item => item.join("-")))}</div>
      `;
    }

    function renderAnalysisOverdue(payload) {
      const rows = (payload?.data?.items || []).map(item => ({
        number: item.number,
        currentSkip: item.currentSkip,
        maxSkip: item.maxSkip,
        avgGap: item.avgGap,
        overdueIndex: item.overdueIndex,
        status: item.status,
      }));
      return renderAnalysisSimpleTable([
        { key: "number", label: "Số" },
        { key: "currentSkip", label: "Kỳ chưa về" },
        { key: "maxSkip", label: "Max skip" },
        { key: "avgGap", label: "Avg gap" },
        { key: "overdueIndex", label: "Index" },
        { key: "status", label: "Trạng thái" },
      ], rows);
    }

    function renderAnalysisPoisson(payload) {
      const d = payload?.data || {};
      return `
        <div class="analysis-badge-row">
          <span class="analysis-badge">lambda ${escapeHtml(formatAnalysisValue(d.lambda))}</span>
          <span class="analysis-badge">P0 ${escapeHtml(formatAnalysisValue(d.p0))}</span>
          <span class="analysis-badge">P1 ${escapeHtml(formatAnalysisValue(d.p1))}</span>
          <span class="analysis-badge">P2 ${escapeHtml(formatAnalysisValue(d.p2))}</span>
          <span class="analysis-badge">P3+ ${escapeHtml(formatAnalysisValue(d.p3plus))}</span>
        </div>
        ${renderAnalysisSimpleTable([
          { key: "number", label: "Số" },
          { key: "observed", label: "Thực tế" },
          { key: "expected", label: "Kỳ vọng" },
          { key: "hotColdStatus", label: "Hot/Cold" },
          { key: "anomalyScore", label: "Bất thường" },
        ], d.items || [])}
      `;
    }

    function renderAnalysisKnn(payload) {
      const d = payload?.data || {};
      return `
        ${renderAnalysisSimpleTable([
          { key: "drawId", label: "Kỳ" },
          { key: "drawDate", label: "Ngày" },
          { key: "numbersText", label: "Bộ số" },
          { key: "distance", label: "Khoảng cách" },
          { key: "similarityPercent", label: "Tương đồng %" },
          { key: "nextText", label: "Kỳ sau lịch sử" },
        ], (d.neighbors || []).map(item => ({
          ...item,
          numbersText: (item.numbers || []).join(" "),
          nextText: (item.nextDrawNumbers || []).join(" "),
        })))}
        <h3 class="analysis-panel-title">Số theo sau từ các kỳ tương đồng</h3>
        ${renderAnalysisNumberCountList(d.followNumbersFromNeighbors || [])}
      `;
    }

    function renderAnalysisChain(payload) {
      return renderAnalysisSimpleTable([
        { key: "leadNumber", label: "Lead" },
        { key: "followNumber", label: "Follow" },
        { key: "count", label: "Số lần" },
        { key: "leadCount", label: "Lead count" },
        { key: "probability", label: "Xác suất" },
      ], payload?.data?.topChains || []);
    }

    function renderAnalysisRelationships(payload) {
      const d = payload?.data || {};
      return `
        <h3 class="analysis-panel-title">Cặp thân thiết</h3>
        ${renderAnalysisNumberCountList(d.coOccurrencePairs || [], "pair", "count")}
        <h3 class="analysis-panel-title">Bộ ba thường gặp</h3>
        ${renderAnalysisNumberCountList(d.frequentTriples || [], "triple", "count")}
        <h3 class="analysis-panel-title">Cặp kỵ</h3>
        ${renderAnalysisNumberCountList(d.incompatiblePairs || [], "pair", "count")}
      `;
    }

    function renderAnalysisModulo(payload) {
      const d = payload?.data || {};
      const rows = [
        ...Object.entries(d.mod3 || {}).map(([key, value]) => ({ group: `mod3 = ${key}`, count: value })),
        ...Object.entries(d.mod5 || {}).map(([key, value]) => ({ group: `mod5 = ${key}`, count: value })),
        ...Object.entries(d.unitDigits || {}).map(([key, value]) => ({ group: `đuôi ${key}`, count: value })),
      ];
      return `
        <div class="analysis-badge-row">
          <span class="analysis-badge">Pattern mod3: ${escapeHtml(d.positionalModulo?.mod3 || "--")}</span>
          <span class="analysis-badge">Pattern mod5: ${escapeHtml(d.positionalModulo?.mod5 || "--")}</span>
        </div>
        ${renderAnalysisSimpleTable([
          { key: "group", label: "Nhóm" },
          { key: "count", label: "Số lần" },
        ], rows)}
      `;
    }

    function renderAnalysisAdvanced(payload) {
      const d = payload?.data || {};
      return `
        <div class="analysis-grid">${renderAnalysisMetricCards([
          { label: "Span", value: d.span },
          { label: "Prime count", value: d.primeCount },
          { label: "Beauty score", value: d.beautyScore },
        ])}</div>
        <h3 class="analysis-panel-title">Số nguyên tố</h3>
        <div class="analysis-chip-row">${renderAnalysisChips(d.primeNumbers || [])}</div>
        <h3 class="analysis-panel-title">Cặp bóng / đảo / slide</h3>
        <div class="analysis-chip-row">${renderAnalysisChips([...(d.shadowPairs || []), ...(d.invertedPairs || []), ...(d.slideNumbers || [])].map(item => item.join("-")))}</div>
      `;
    }

    function renderAnalysisSpecial(payload) {
      const d = payload?.data || {};
      if (d.supported === false) return `<div class="analysis-empty">${escapeHtml(d.message || "Không hỗ trợ số đặc biệt.")}</div>`;
      return `
        <div class="analysis-badge-row">
          <span class="analysis-badge">Expected ${escapeHtml(formatAnalysisValue(d.specialExpected))}</span>
          <span class="analysis-badge">Current skip ${escapeHtml(formatAnalysisValue(d.specialCurrentSkip))}</span>
          <span class="analysis-badge">Overdue index ${escapeHtml(formatAnalysisValue(d.specialOverdueIndex))}</span>
        </div>
        <h3 class="analysis-panel-title">ĐB nóng</h3>
        ${renderAnalysisNumberCountList(d.topSpecialHot || [])}
        <h3 class="analysis-panel-title">ĐB lạnh</h3>
        ${renderAnalysisNumberCountList(d.topSpecialCold || [])}
      `;
    }

    function renderAnalysisWeekday(payload) {
      const d = payload?.data || {};
      return `
        <h3 class="analysis-panel-title">Gợi ý theo thứ hiện tại</h3>
        <div class="analysis-chip-row">${renderAnalysisChips((d.currentWeekdaySuggestion?.numbers || []).map(item => `${item.number} (${item.count})`))}</div>
        ${renderAnalysisSimpleTable([
          { key: "weekday", label: "Thứ" },
          { key: "drawCount", label: "Số kỳ" },
          { key: "topText", label: "Top số" },
        ], (d.weekdayStats || []).map(item => ({
          ...item,
          topText: (item.topNumbers || []).map(row => `${row.number}(${row.count})`).join(", "),
        })))}
      `;
    }

    function renderAnalysisSmartWheel(payload) {
      const d = payload?.data || {};
      return `
        <div class="analysis-card">
          <div class="analysis-card-title">Pool được chọn</div>
          <div class="analysis-chip-row">${renderAnalysisChips(d.selectedPool || [])}</div>
        </div>
        <h3 class="analysis-panel-title">Vé sinh ra</h3>
        <div class="analysis-ticket-list">${(d.generatedTickets || []).map(ticket => `<div class="analysis-ticket">${renderAnalysisChips(ticket)}</div>`).join("") || `<div class="analysis-empty">${escapeHtml(d.message || "Chưa tạo vé.")}</div>`}</div>
      `;
    }

    function renderAnalysisScore(payload) {
      const d = payload?.data || {};
      return `
        <div class="analysis-score-box">
          <div class="analysis-score-ring">${escapeHtml(formatAnalysisValue(d.finalScore || 0))}</div>
          <div>
            <div class="analysis-card-title">Final score</div>
            <div class="analysis-chip-row">${renderAnalysisChips(d.numbers || [])}</div>
          </div>
        </div>
        <div class="analysis-grid">${renderAnalysisMetricCards([
          { label: "Balance", value: d.balanceScore },
          { label: "Sum", value: d.sumScore },
          { label: "Gap", value: d.gapScore },
          { label: "Distribution", value: d.distributionScore },
          { label: "Relationship", value: d.relationshipScore },
          { label: "Beauty", value: d.beautyScore },
        ])}</div>
      `;
    }

    function renderAnalysisAll(payload) {
      const d = payload?.data || {};
      const blocks = [
        ["Tổng quan", renderAnalysisOverview({ data: d.overview || {} })],
        ["Bộ số", renderAnalysisGeneral({ data: d.general || {} })],
        ["Tỷ lệ", renderAnalysisRatios({ data: d.ratios || {} })],
        ["Gan", renderAnalysisOverdue({ data: { items: d.overdue?.topOverdue || [] } })],
        ["Poisson", renderAnalysisPoisson({ data: d.poisson || {} })],
        ["KNN", renderAnalysisKnn({ data: d.knn || {} })],
        ["Quan hệ", renderAnalysisRelationships({ data: d.relationships || {} })],
        ["Nâng cao", renderAnalysisAdvanced({ data: d.advanced || {} })],
        ["Điểm", renderAnalysisScore({ data: d.score || {} })],
      ];
      return blocks.map(([title, html]) => `<section class="analysis-all-block"><h3 class="analysis-panel-title">${escapeHtml(title)}</h3>${html}</section>`).join("");
    }

    function getAnalysisTopNumbers(payload) {
      const data = payload?.data || {};
      if (Array.isArray(data.hotNumbers)) return data.hotNumbers.slice(0, 3).map(item => item.number);
      if (Array.isArray(data.numbers)) return data.numbers.slice(0, 3);
      if (Array.isArray(data.items)) return data.items.slice(0, 3).map(item => item.number).filter(Boolean);
      if (Array.isArray(payload?.latestDraw?.numbers)) return payload.latestDraw.numbers.slice(0, 3);
      return [];
    }

    function saveAnalysisHistory() {
      const payload = analysisState.lastPayload;
      if (!payload?.ok) {
        analysisState.error = "Chưa có phân tích hợp lệ để lưu.";
        renderAnalysis(payload);
        return;
      }
      if (!Array.isArray(store.analysisHistory)) store.analysisHistory = [];
      const summary = payload.data?.summaryText || payload.explanations?.[1] || `${formatAnalysisModeLabel(payload.mode)} ${payload.type}`;
      const entry = {
        id: `analysis_${Date.now()}_${Math.random().toString(16).slice(2)}`,
        type: payload.type,
        period: payload.period,
        mode: payload.mode,
        createdAt: getSyncedIsoString(),
        summary,
        topNumbers: getAnalysisTopNumbers(payload),
        snapshot: {
          totalDraws: payload.totalDraws || 0,
          latestDrawId: payload.latestDraw?.drawId || "",
          mainHighlights: getAnalysisTopNumbers(payload),
        },
      };
      store.analysisHistory.unshift(entry);
      while (store.analysisHistory.length > MAX_ANALYSIS_HISTORY) store.analysisHistory.pop();
      saveStore();
      const status = document.getElementById("analysisStatus");
      if (status) {
        status.hidden = false;
        status.textContent = "Đã lưu phân tích vào lịch sử.";
      }
    }

    function startAnalysisAutoRefresh() {
      stopAnalysisAutoRefresh();
      if (!analysisState.autoRefresh || predictPageModeValue !== PREDICTION_MODE_ANALYSIS) return;
      analysisState.timer = setInterval(() => {
        loadAnalysis({ force: true, silent: true });
      }, ANALYSIS_AUTO_REFRESH_MS);
    }

    function stopAnalysisAutoRefresh() {
      if (analysisState.timer) clearInterval(analysisState.timer);
      analysisState.timer = null;
    }

    function refreshAnalysisAfterLiveUpdate() {
      if (predictPageModeValue !== PREDICTION_MODE_ANALYSIS) return;
      loadAnalysis({ force: true, silent: true });
    }

    function getChartStatsTypeMeta(typeKey) {
      return getStatsTypeUiMeta(normalizeChartStatsType(typeKey));
    }

    function getChartStatsPresetLabel(value, typeKey = chartStatsSelectedType) {
      const normalized = normalizeChartStatsPreset(value, typeKey);
      return CHART_STATS_PRESET_LABELS[normalized] || `${normalized} kỳ`;
    }

    function getChartStatsGroupConfig(typeKey) {
      return CHART_STATS_GROUPS[normalizeChartStatsType(typeKey)] || CHART_STATS_GROUPS.KENO;
    }

    function getChartStatsNumbersPerDraw(typeKey) {
      return Math.max(1, Number(TYPES[normalizeChartStatsType(typeKey)]?.mainCount || 0));
    }

    function renderChartStatsTypeOptions() {
      const host = document.getElementById("chartStatsTypeSelect");
      if (!host) return;
      chartStatsSelectedType = normalizeChartStatsType(chartStatsSelectedType);
      host.innerHTML = CHART_STATS_TYPE_OPTIONS.map(item => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`).join("");
      host.value = CHART_STATS_TYPE_OPTIONS.some(item => item.value === chartStatsSelectedType) ? chartStatsSelectedType : "KENO";
      if (typeof host.__syncCustomSelect === "function") host.__syncCustomSelect();
    }

    function renderChartStatsPresetOptions() {
      const host = document.getElementById("chartStatsPresetSelect");
      if (!host) return;
      chartStatsSelectedPreset = normalizeChartStatsPreset(chartStatsSelectedPreset, chartStatsSelectedType);
      host.innerHTML = getChartStatsPresetOptions(chartStatsSelectedType)
        .map(value => `<option value="${escapeHtml(value)}">${escapeHtml(getChartStatsPresetLabel(value, chartStatsSelectedType))}</option>`)
        .join("");
      host.value = chartStatsSelectedPreset;
      if (typeof host.__syncCustomSelect === "function") host.__syncCustomSelect();
    }

    function renderChartStatsViewOptions() {
      const host = document.getElementById("chartStatsViewSelect");
      if (!host) return;
      chartStatsViewMode = normalizeChartStatsViewMode(chartStatsViewMode);
      host.innerHTML = CHART_STATS_VIEW_OPTIONS.map(item => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`).join("");
      host.value = chartStatsViewMode;
      if (typeof host.__syncCustomSelect === "function") host.__syncCustomSelect();
    }

    function renderChartStatsControls(totalAvailable = 0) {
      ensureChartStatsPresetForType();
      renderChartStatsTypeOptions();
      renderChartStatsPresetOptions();
      renderChartStatsViewOptions();
      const input = document.getElementById("chartStatsCustomCount");
      const note = document.getElementById("chartStatsCountHint");
      if (!input || !note) return;
      input.disabled = chartStatsSelectedPreset !== "custom";
      input.min = "1";
      input.max = totalAvailable > 0 ? String(totalAvailable) : "";
      input.value = chartStatsSelectedPreset === "custom" ? String(chartStatsCustomCountValue || "") : "";
      if (chartStatsSelectedPreset === "custom") {
        note.textContent = totalAvailable > 0
          ? `Nhập từ 1 đến ${formatLiveSyncCount(totalAvailable)} kỳ. Nếu nhập lớn hơn dữ liệu hiện có, hệ thống sẽ tự dùng toàn bộ dữ liệu đang có.`
          : "Nhập số kỳ tùy chỉnh để phân tích.";
      } else if (chartStatsSelectedPreset === "all") {
        note.textContent = totalAvailable > 0
          ? `Đang dùng toàn bộ ${formatLiveSyncCount(totalAvailable)} kỳ hiện có của ${getChartStatsTypeMeta(chartStatsSelectedType).label}.`
          : "Đang dùng toàn bộ dữ liệu hiện có.";
      } else {
        note.textContent = `Preset hiện tại: ${getChartStatsPresetLabel(chartStatsSelectedPreset, chartStatsSelectedType)}. Chuyển sang Tùy chỉnh nếu bạn muốn nhập số kỳ bất kỳ.`;
      }
    }

    function resolveChartStatsRequestedCount(totalAvailable) {
      const available = Math.max(0, Number(totalAvailable || 0));
      const preset = normalizeChartStatsPreset(chartStatsSelectedPreset, chartStatsSelectedType);
      if (preset === "all") {
        return {
          mode: "all",
          requestedCount: available,
          requestedLabel: "All",
          actualUsedCount: available,
          valid: true,
          helperText: `Dùng toàn bộ ${formatLiveSyncCount(available)} kỳ hiện có.`,
        };
      }
      if (preset === "custom") {
        const customCount = Number(chartStatsCustomCountValue || 0);
        if (!Number.isInteger(customCount) || customCount <= 0) {
          return {
            mode: "custom",
            requestedCount: 0,
            requestedLabel: "Tùy chỉnh",
            actualUsedCount: 0,
            valid: false,
            helperText: available > 0
              ? `Nhập số kỳ từ 1 đến ${formatLiveSyncCount(available)} để xem biểu đồ.`
              : "Chưa có dữ liệu để nhập số kỳ.",
          };
        }
        return {
          mode: "custom",
          requestedCount: customCount,
          requestedLabel: String(customCount),
          actualUsedCount: Math.min(customCount, available),
          valid: true,
          helperText: customCount > available
            ? `Yêu cầu ${formatLiveSyncCount(customCount)} kỳ nhưng hiện chỉ có ${formatLiveSyncCount(available)} kỳ, hệ thống sẽ dùng toàn bộ dữ liệu hiện có.`
            : `Đang dùng ${formatLiveSyncCount(Math.min(customCount, available))} kỳ theo số bạn nhập.`,
        };
      }
      const presetCount = Math.max(1, Number(preset) || 1);
      return {
        mode: "preset",
        requestedCount: presetCount,
        requestedLabel: String(presetCount),
        actualUsedCount: Math.min(presetCount, available),
        valid: true,
        helperText: presetCount > available
          ? `Preset yêu cầu ${formatLiveSyncCount(presetCount)} kỳ nhưng dữ liệu hiện có là ${formatLiveSyncCount(available)} kỳ.`
          : `Preset đang dùng ${formatLiveSyncCount(presetCount)} kỳ gần nhất.`,
      };
    }

    function buildChartStatsEntries(typeKey, requestedInfo) {
      const entries = buildStatsEntriesForFeed(typeKey, getLiveHistoryFeed(typeKey));
      const actualUsed = Math.max(0, Number(requestedInfo?.actualUsedCount || 0));
      if (!entries.length || actualUsed <= 0) return [];
      return entries.slice(-actualUsed);
    }

    function computeChartStatsGroupRows(typeKey, entries) {
      const groups = getChartStatsGroupConfig(typeKey).map(item => ({
        ...item,
        count: 0,
      }));
      let totalHits = 0;
      (Array.isArray(entries) ? entries : []).forEach(entry => {
        const numbers = Array.isArray(entry?.draw?.main) ? entry.draw.main.map(Number).filter(Number.isInteger) : [];
        numbers.forEach(number => {
          const group = groups.find(item => number >= item.min && number <= item.max);
          if (!group) return;
          group.count += 1;
          totalHits += 1;
        });
      });
      const maxCount = groups.reduce((max, item) => Math.max(max, item.count), 0) || 1;
      return groups.map(item => ({
        ...item,
        percent: totalHits > 0 ? (item.count / totalHits) * 100 : 0,
        frequencyRatio: maxCount > 0 ? item.count / maxCount : 0,
      }));
    }

    function formatChartStatsPercent(value) {
      return `${Number(value || 0).toFixed(2)}%`;
    }

    function renderChartStatsSummary(meta, requestedInfo, entries, rows) {
      const totalHits = rows.reduce((sum, item) => sum + Number(item.count || 0), 0);
      return `
        <section class="chart-stats-summary ${escapeHtml(meta.fullAccentClass)}">
          <article class="chart-stats-summary-card">
            <div class="chart-stats-summary-label">Loại xổ số</div>
            <div class="chart-stats-summary-value">${escapeHtml(meta.label)}</div>
            <div class="chart-stats-summary-meta">Nhóm số theo cấu hình của ${escapeHtml(meta.label)}</div>
          </article>
          <article class="chart-stats-summary-card">
            <div class="chart-stats-summary-label">Kỳ yêu cầu</div>
            <div class="chart-stats-summary-value">${escapeHtml(requestedInfo.mode === "all" ? "All" : formatLiveSyncCount(requestedInfo.requestedCount))}</div>
            <div class="chart-stats-summary-meta">${escapeHtml(requestedInfo.helperText || "Phân tích theo số kỳ đã chọn")}</div>
          </article>
          <article class="chart-stats-summary-card">
            <div class="chart-stats-summary-label">Kỳ thực dùng</div>
            <div class="chart-stats-summary-value">${escapeHtml(formatLiveSyncCount(requestedInfo.actualUsedCount))}</div>
            <div class="chart-stats-summary-meta">${escapeHtml(`Lấy từ ${formatLiveSyncCount(entries.length)} kỳ gần nhất phù hợp`)}</div>
          </article>
          <article class="chart-stats-summary-card">
            <div class="chart-stats-summary-label">Tổng lượt số đã phân tích</div>
            <div class="chart-stats-summary-value">${escapeHtml(formatLiveSyncCount(totalHits))}</div>
            <div class="chart-stats-summary-meta">${escapeHtml(`${getChartStatsNumbersPerDraw(chartStatsSelectedType)} số / kỳ`)}</div>
          </article>
        </section>
      `;
    }

    function renderChartStatsFrequencyChart(meta, requestedInfo, rows) {
      const titleLabel = requestedInfo.mode === "all" ? "All kỳ" : `${formatLiveSyncCount(requestedInfo.requestedCount)} kỳ`;
      return `
        <section class="chart-stats-block">
          <div class="chart-stats-block-head">
            <div class="chart-stats-block-title">${escapeHtml(`${meta.label} - ${titleLabel} - Tần suất theo nhóm`)}</div>
            <div class="chart-stats-block-meta">${escapeHtml(`Thực dùng ${formatLiveSyncCount(requestedInfo.actualUsedCount)} kỳ`)}</div>
          </div>
          <div class="chart-stats-frequency-chart">
            ${rows.map(item => `
              <article class="chart-stats-frequency-item">
                <div class="chart-stats-frequency-value">${escapeHtml(formatLiveSyncCount(item.count))}</div>
                <div class="chart-stats-frequency-bar-shell">
                  <div class="chart-stats-frequency-bar" style="height:${(Number(item.count || 0) > 0 ? Math.max(6, Number(item.frequencyRatio || 0) * 100) : 0).toFixed(2)}%; --chart-bar-color:${escapeHtml(item.color)}; --chart-bar-opacity:${(0.26 + Math.max(0, Math.min(1, Number(item.frequencyRatio || 0))) * 0.74).toFixed(3)}; --chart-bar-bright:${(0.76 + Math.max(0, Math.min(1, Number(item.frequencyRatio || 0))) * 0.44).toFixed(3)}; --chart-bar-sat:${(0.84 + Math.max(0, Math.min(1, Number(item.frequencyRatio || 0))) * 0.32).toFixed(3)};"></div>
                </div>
                <div class="chart-stats-frequency-label">${escapeHtml(item.label)}</div>
              </article>
            `).join("")}
          </div>
        </section>
      `;
    }

    function renderChartStatsPercentChart(meta, requestedInfo, rows) {
      const titleLabel = requestedInfo.mode === "all" ? "All kỳ" : `${formatLiveSyncCount(requestedInfo.requestedCount)} kỳ`;
      const totalHits = rows.reduce((sum, item) => sum + Number(item.count || 0), 0);
      const radius = 72;
      const stroke = 18;
      const circumference = 2 * Math.PI * radius;
      const activeRows = rows.filter(item => Number(item.count || 0) > 0 && Number(item.percent || 0) > 0);
      if (!activeRows.length || totalHits <= 0) {
        return `
          <section class="chart-stats-block">
            <div class="chart-stats-block-head">
              <div class="chart-stats-block-title">${escapeHtml(`${meta.label} - ${titleLabel} - Tỷ trọng %`)}</div>
              <div class="chart-stats-block-meta">${escapeHtml(`Tổng lượt số ${formatLiveSyncCount(totalHits)}`)}</div>
            </div>
            <div class="chart-stats-donut-empty">Chưa có đủ dữ liệu để dựng donut tỷ trọng %.</div>
          </section>
        `;
      }
      let accumulated = 0;
      const donutSegmentsHtml = activeRows.map(item => {
        const percent = Math.max(0, Number(item.percent || 0));
        const segmentLength = (percent / 100) * circumference;
        const dashOffset = circumference - accumulated;
        accumulated += segmentLength;
        return `<circle
          class="chart-stats-donut-segment"
          cx="90"
          cy="90"
          r="${radius}"
          fill="none"
          stroke="${escapeHtml(item.color)}"
          stroke-width="${stroke}"
          stroke-linecap="round"
          stroke-dasharray="${segmentLength.toFixed(3)} ${(circumference - segmentLength).toFixed(3)}"
          stroke-dashoffset="${dashOffset.toFixed(3)}"
          style="--chart-bar-opacity:${(0.34 + Math.max(0, Math.min(1, percent / 100)) * 0.66).toFixed(3)}; --chart-bar-bright:${(0.84 + Math.max(0, Math.min(1, percent / 100)) * 0.34).toFixed(3)}; --chart-bar-sat:${(0.88 + Math.max(0, Math.min(1, percent / 100)) * 0.26).toFixed(3)};"
        />`;
      }).join("");
      return `
        <section class="chart-stats-block">
          <div class="chart-stats-block-head">
            <div class="chart-stats-block-title">${escapeHtml(`${meta.label} - ${titleLabel} - Tỷ trọng %`)}</div>
            <div class="chart-stats-block-meta">${escapeHtml(`Tổng lượt số ${formatLiveSyncCount(totalHits)}`)}</div>
          </div>
          <div class="chart-stats-donut-layout">
            <div class="chart-stats-donut-wrap">
              <svg class="chart-stats-donut-svg" viewBox="0 0 180 180" aria-hidden="true">
                <circle class="chart-stats-donut-track" cx="90" cy="90" r="${radius}" fill="none" stroke-width="${stroke}"></circle>
                <g class="chart-stats-donut-ring">${donutSegmentsHtml}</g>
              </svg>
              <div class="chart-stats-donut-center">
                <div class="chart-stats-donut-center-value">100%</div>
                <div class="chart-stats-donut-center-label">Tỷ trọng</div>
                <div class="chart-stats-donut-center-meta">${escapeHtml(`${formatLiveSyncCount(activeRows.length)} nhóm`)}</div>
              </div>
            </div>
            <div class="chart-stats-donut-legend">
              ${rows.map(item => `
                <div class="chart-stats-donut-legend-item">
                  <span class="chart-stats-donut-legend-swatch" style="--chart-bar-color:${escapeHtml(item.color)}"></span>
                  <span class="chart-stats-donut-legend-label">${escapeHtml(item.label)}</span>
                  <span class="chart-stats-donut-legend-percent">${escapeHtml(formatChartStatsPercent(item.percent))}</span>
                  <span class="chart-stats-donut-legend-count">${escapeHtml(formatLiveSyncCount(item.count))}</span>
                </div>
              `).join("")}
            </div>
          </div>
        </section>
      `;
    }

    function renderChartStatsTable(rows) {
      return `
        <section class="chart-stats-block">
          <div class="chart-stats-block-head">
            <div class="chart-stats-block-title">Bảng thống kê theo nhóm</div>
            <div class="chart-stats-block-meta">${escapeHtml(`${formatLiveSyncCount(rows.length)} nhóm số`)}</div>
          </div>
          <div class="chart-stats-table-wrap">
            <table class="chart-stats-table">
              <thead>
                <tr>
                  <th>Nhóm số</th>
                  <th>Tần suất</th>
                  <th>Tỷ trọng %</th>
                </tr>
              </thead>
              <tbody>
                ${rows.map(item => `
                  <tr>
                    <td><span class="chart-stats-table-chip" style="--chart-bar-color:${escapeHtml(item.color)};">${escapeHtml(item.label)}</span></td>
                    <td>${escapeHtml(formatLiveSyncCount(item.count))}</td>
                    <td>${escapeHtml(formatChartStatsPercent(item.percent))}</td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>
        </section>
      `;
    }

    function renderChartStatsPanel() {
      const out = document.getElementById("chartStatsOut");
      if (!out) return;
      const type = normalizeChartStatsType(chartStatsSelectedType);
      const feed = getLiveHistoryFeed(type);
      const meta = getChartStatsTypeMeta(type);
      const allEntries = buildStatsEntriesForFeed(type, feed);
      renderChartStatsControls(allEntries.length);
      if (chartStatsPanelLoading && !feed?.order?.length) {
        out.classList.add("muted");
        out.innerHTML = "Đang tải dữ liệu biểu đồ thống kê từ all_day.csv...";
        return;
      }
      if (chartStatsPanelError) {
        out.classList.add("muted");
        out.innerHTML = escapeHtml(chartStatsPanelError);
        return;
      }
      if (!feed?.order?.length) {
        out.classList.add("muted");
        out.innerHTML = IS_LOCAL_MODE
          ? "Khung biểu đồ thống kê cần mở qua http://localhost:8080 để đọc dữ liệu all_day.csv."
          : "Chưa có dữ liệu biểu đồ thống kê. Hệ thống sẽ tự tải all_day.csv khi bạn mở tab này.";
        return;
      }
      const requestedInfo = resolveChartStatsRequestedCount(allEntries.length);
      if (!requestedInfo.valid) {
        out.classList.add("muted");
        out.innerHTML = escapeHtml(requestedInfo.helperText || "Chưa đủ thông tin để hiển thị biểu đồ.");
        return;
      }
      const entries = buildChartStatsEntries(type, requestedInfo);
      if (!entries.length) {
        out.classList.remove("muted");
        out.innerHTML = `<div class="chart-stats-empty">Không có dữ liệu ${escapeHtml(meta.label)} cho số kỳ đã chọn.</div>`;
        return;
      }
      const rows = computeChartStatsGroupRows(type, entries);
      const chartBlocks = [];
      if (chartStatsViewMode === "all" || chartStatsViewMode === "frequency") {
        chartBlocks.push(renderChartStatsFrequencyChart(meta, requestedInfo, rows));
      }
      if (chartStatsViewMode === "all" || chartStatsViewMode === "percent") {
        chartBlocks.push(renderChartStatsPercentChart(meta, requestedInfo, rows));
      }
      out.classList.remove("muted");
      out.innerHTML = `
        <div class="chart-stats-shell-grid ${escapeHtml(meta.fullAccentClass)}">
          ${renderChartStatsSummary(meta, requestedInfo, entries, rows)}
          <div class="chart-stats-grid">
            ${chartBlocks.join("")}
          </div>
          ${renderChartStatsTable(rows)}
        </div>
      `;
    }

    async function startChartStatsRefresh({ force = false, silent = true } = {}) {
      const type = normalizeChartStatsType(chartStatsSelectedType);
      const refreshToken = ++chartStatsPanelRefreshToken;
      chartStatsPanelLoading = true;
      chartStatsPanelError = "";
      renderChartStatsPanel();
      try {
        await fetchLiveHistory(type, "all", { force, silent });
        if (refreshToken !== chartStatsPanelRefreshToken) return;
        chartStatsPanelLoading = false;
        chartStatsPanelError = "";
      } catch (error) {
        if (refreshToken !== chartStatsPanelRefreshToken) return;
        chartStatsPanelLoading = false;
        chartStatsPanelError = `Không tải được biểu đồ thống kê ${getChartStatsTypeMeta(type).label}: ${String(error?.message || error || "Lỗi không rõ")}`;
      } finally {
        if (refreshToken !== chartStatsPanelRefreshToken) return;
        renderChartStatsPanel();
      }
    }

    function getDashboardTypeMeta(type) {
      const mapping = {
        KENO: { label: "Keno", accent: "#6f66ff" },
        LOTO_5_35: { label: "Lotto 5/35", accent: "#6c63ff" },
        LOTO_6_45: { label: "Mega 6/45", accent: "#4f8cff" },
        LOTO_6_55: { label: "Power 6/55", accent: "#7f63ff" },
      };
      return mapping[type] || mapping.KENO;
    }

    function floorDashboardDate(dateValue) {
      const next = new Date(dateValue instanceof Date ? dateValue.getTime() : getSyncedNowMs());
      next.setHours(0, 0, 0, 0);
      return next;
    }

    function shiftDashboardDate(dateValue, deltaDays) {
      const next = new Date(dateValue.getTime());
      next.setDate(next.getDate() + Number(deltaDays || 0));
      return next;
    }

    function addDashboardMonths(dateValue, deltaMonths) {
      return new Date(dateValue.getFullYear(), dateValue.getMonth() + Number(deltaMonths || 0), 1);
    }

    function getDashboardWeekStart(dateValue) {
      const next = floorDashboardDate(dateValue);
      const weekday = next.getDay();
      const diff = weekday === 0 ? -6 : 1 - weekday;
      next.setDate(next.getDate() + diff);
      return next;
    }

    function formatDashboardDateKey(dateValue) {
      const year = dateValue.getFullYear();
      const month = String(dateValue.getMonth() + 1).padStart(2, "0");
      const day = String(dateValue.getDate()).padStart(2, "0");
      return `${year}-${month}-${day}`;
    }

    function formatDashboardShortDate(dateValue) {
      const day = String(dateValue.getDate()).padStart(2, "0");
      const month = String(dateValue.getMonth() + 1).padStart(2, "0");
      return `${day}/${month}`;
    }

    function formatDashboardMonthLabel(dateValue) {
      const month = String(dateValue.getMonth() + 1).padStart(2, "0");
      return `${month}/${dateValue.getFullYear()}`;
    }

    function formatDashboardNumber(value, fractionDigits = 1) {
      const numeric = Number(value || 0);
      return new Intl.NumberFormat("vi-VN", {
        minimumFractionDigits: fractionDigits,
        maximumFractionDigits: fractionDigits,
      }).format(Number.isFinite(numeric) ? numeric : 0);
    }

    function formatDashboardInteger(value) {
      return new Intl.NumberFormat("vi-VN").format(Math.max(0, Number(value || 0)));
    }

    function formatDashboardRelativeTime(value) {
      const parsed = value instanceof Date ? value : new Date(String(value || "").trim());
      if (!(parsed instanceof Date) || Number.isNaN(parsed.getTime())) return "chưa rõ";
      const diffMs = Math.max(0, getSyncedNowMs() - parsed.getTime());
      const diffMinutes = Math.floor(diffMs / 60000);
      if (diffMinutes < 1) return "vừa xong";
      if (diffMinutes < 60) return `${diffMinutes} phút trước`;
      const diffHours = Math.floor(diffMinutes / 60);
      if (diffHours < 24) return `${diffHours} giờ trước`;
      const diffDays = Math.floor(diffHours / 24);
      return `${diffDays} ngày trước`;
    }

    function normalizeDashboardActivityViewMode(value) {
      return normalizeDashboardActivityView(value);
    }

    function normalizeDashboardDistributionViewMode(value) {
      return normalizeDashboardDistributionView(value);
    }

    function buildDashboardEntries() {
      return DASHBOARD_LOTTO_TYPES
        .flatMap(type => {
          const feedEntries = buildStatsEntriesForFeed(type, getLiveHistoryFeed(type));
          return feedEntries
            .map(entry => {
              const parsedDate = parseLiveDate(entry.draw?.date || "");
              if (!(parsedDate instanceof Date) || Number.isNaN(parsedDate.getTime())) return null;
              const mainNumbers = (Array.isArray(entry.draw?.main) ? entry.draw.main : [])
                .map(Number)
                .filter(Number.isInteger);
              return {
                type,
                ky: entry.ky,
                draw: entry.draw,
                date: parsedDate,
                dayStart: floorDashboardDate(parsedDate),
                mainNumbers,
                hitCount: mainNumbers.length,
              };
            })
            .filter(Boolean);
        })
        .sort((a, b) => {
          const dateDelta = a.date.getTime() - b.date.getTime();
          if (dateDelta !== 0) return dateDelta;
          const typeDelta = DASHBOARD_LOTTO_TYPES.indexOf(a.type) - DASHBOARD_LOTTO_TYPES.indexOf(b.type);
          if (typeDelta !== 0) return typeDelta;
          return kySortValue(a.ky) - kySortValue(b.ky);
        });
    }

    function getDashboardLatestDate(entries) {
      const latest = (Array.isArray(entries) ? entries : []).at(-1)?.dayStart;
      return latest instanceof Date && !Number.isNaN(latest.getTime()) ? latest : floorDashboardDate(getSyncedNowDate());
    }

    function filterDashboardEntriesInRange(entries, startDate, endDate) {
      const startTime = startDate.getTime();
      const endTime = endDate.getTime();
      return (Array.isArray(entries) ? entries : []).filter(entry => {
        const currentTime = entry?.dayStart instanceof Date ? entry.dayStart.getTime() : NaN;
        return Number.isFinite(currentTime) && currentTime >= startTime && currentTime <= endTime;
      });
    }

    function computeDashboardWindowMetrics(entries, windowDays, latestDate) {
      const safeWindowDays = Math.max(1, Number(windowDays || 0) || 1);
      const latest = latestDate instanceof Date ? latestDate : getDashboardLatestDate(entries);
      const currentEnd = floorDashboardDate(latest);
      const currentStart = shiftDashboardDate(currentEnd, -(safeWindowDays - 1));
      const previousEnd = shiftDashboardDate(currentStart, -1);
      const previousStart = shiftDashboardDate(previousEnd, -(safeWindowDays - 1));
      const currentEntries = filterDashboardEntriesInRange(entries, currentStart, currentEnd);
      const previousEntries = filterDashboardEntriesInRange(entries, previousStart, previousEnd);
      const currentDraws = currentEntries.length;
      const previousDraws = previousEntries.length;
      const currentHits = currentEntries.reduce((sum, entry) => sum + Number(entry.hitCount || 0), 0);
      const previousHits = previousEntries.reduce((sum, entry) => sum + Number(entry.hitCount || 0), 0);
      const currentSessionsPerDay = currentDraws / safeWindowDays;
      const previousFrequencyPerDay = previousHits / safeWindowDays;
      const currentFrequencyPerDay = currentHits / safeWindowDays;
      const trendRatio = (currentFrequencyPerDay - previousFrequencyPerDay) / Math.max(1, previousFrequencyPerDay || 1);
      let badge = { label: "Ổn định", tone: "stable", detail: "Biên độ gần như giữ nguyên so với giai đoạn trước." };
      if (trendRatio >= 0.08) {
        badge = { label: "Tăng", tone: "up", detail: "Lượng phân tích đang tăng rõ trong giai đoạn này." };
      } else if (trendRatio <= -0.08) {
        badge = { label: "Giảm nhẹ", tone: "down", detail: "Lượng phân tích đang giảm nhẹ so với giai đoạn trước." };
      }
      return {
        currentDraws,
        currentHits,
        currentFrequencyPerDay,
        currentSessionsPerDay,
        previousDraws,
        badge,
      };
    }

    function renderDashboardKpiCard(title, metrics) {
      return `
        <article class="lotto-dashboard-kpi-card">
          <div class="lotto-dashboard-kpi-head">
            <div class="lotto-dashboard-kpi-title">${escapeHtml(title)}</div>
            <span class="lotto-dashboard-badge is-${escapeHtml(metrics.badge.tone)}">${escapeHtml(metrics.badge.label)}</span>
          </div>
          <div class="lotto-dashboard-kpi-metrics">
            <div class="lotto-dashboard-kpi-metric">
              <div class="lotto-dashboard-kpi-metric-label">Số kỳ đã phân tích</div>
              <div class="lotto-dashboard-kpi-metric-value">${escapeHtml(formatDashboardInteger(metrics.currentDraws))}</div>
              <div class="lotto-dashboard-kpi-metric-meta">${escapeHtml(`${formatDashboardInteger(metrics.previousDraws)} kỳ ở giai đoạn trước`)}</div>
            </div>
            <div class="lotto-dashboard-kpi-metric">
              <div class="lotto-dashboard-kpi-metric-label">Tần suất trung bình / ngày</div>
              <div class="lotto-dashboard-kpi-metric-value is-accent">${escapeHtml(formatDashboardNumber(metrics.currentFrequencyPerDay, 1))}</div>
              <div class="lotto-dashboard-kpi-metric-meta">lượt số/ngày</div>
            </div>
            <div class="lotto-dashboard-kpi-metric">
              <div class="lotto-dashboard-kpi-metric-label">Số phiên phân tích / ngày</div>
              <div class="lotto-dashboard-kpi-metric-value is-secondary">${escapeHtml(formatDashboardNumber(metrics.currentSessionsPerDay, 1))}</div>
              <div class="lotto-dashboard-kpi-metric-meta">phiên/ngày</div>
            </div>
          </div>
          <div class="lotto-dashboard-kpi-note">${escapeHtml(metrics.badge.detail)}</div>
        </article>
      `;
    }

    function getDashboardBucketKey(dateValue, mode) {
      if (mode === "month") {
        return `${dateValue.getFullYear()}-${String(dateValue.getMonth() + 1).padStart(2, "0")}`;
      }
      if (mode === "week") {
        return `week-${formatDashboardDateKey(getDashboardWeekStart(dateValue))}`;
      }
      return formatDashboardDateKey(floorDashboardDate(dateValue));
    }

    function getDashboardActivityBuckets(entries, mode) {
      const normalizedMode = normalizeDashboardActivityViewMode(mode);
      const latestDate = getDashboardLatestDate(entries);
      const limit = DASHBOARD_ACTIVITY_BUCKET_LIMITS[normalizedMode] || 12;
      const buckets = [];
      if (normalizedMode === "month") {
        const latestMonth = new Date(latestDate.getFullYear(), latestDate.getMonth(), 1);
        for (let index = limit - 1; index >= 0; index -= 1) {
          const start = addDashboardMonths(latestMonth, -index);
          const end = new Date(start.getFullYear(), start.getMonth() + 1, 0, 23, 59, 59, 999);
          buckets.push({
            key: getDashboardBucketKey(start, normalizedMode),
            label: formatDashboardMonthLabel(start),
            tooltipLabel: `Tháng ${formatDashboardMonthLabel(start)}`,
            start,
            end,
            value: 0,
            drawCount: 0,
          });
        }
      } else if (normalizedMode === "week") {
        const latestWeek = getDashboardWeekStart(latestDate);
        for (let index = limit - 1; index >= 0; index -= 1) {
          const start = shiftDashboardDate(latestWeek, -7 * index);
          const end = new Date(start.getTime());
          end.setDate(end.getDate() + 6);
          end.setHours(23, 59, 59, 999);
          buckets.push({
            key: getDashboardBucketKey(start, normalizedMode),
            label: formatDashboardShortDate(start),
            tooltipLabel: `${formatDashboardShortDate(start)} - ${formatDashboardShortDate(end)}`,
            start,
            end,
            value: 0,
            drawCount: 0,
          });
        }
      } else {
        const latestDay = floorDashboardDate(latestDate);
        for (let index = limit - 1; index >= 0; index -= 1) {
          const start = shiftDashboardDate(latestDay, -index);
          const end = new Date(start.getTime());
          end.setHours(23, 59, 59, 999);
          buckets.push({
            key: getDashboardBucketKey(start, normalizedMode),
            label: formatDashboardShortDate(start),
            tooltipLabel: formatLiveDateFromDate(start),
            start,
            end,
            value: 0,
            drawCount: 0,
          });
        }
      }
      const bucketMap = new Map(buckets.map(item => [item.key, item]));
      (Array.isArray(entries) ? entries : []).forEach(entry => {
        const bucketKey = getDashboardBucketKey(entry.date, normalizedMode);
        const bucket = bucketMap.get(bucketKey);
        if (!bucket) return;
        bucket.value += Number(entry.hitCount || 0);
        bucket.drawCount += 1;
      });
      return buckets;
    }

    function buildDashboardSmoothPath(points) {
      if (!Array.isArray(points) || !points.length) return "";
      if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;
      let d = `M ${points[0].x} ${points[0].y}`;
      for (let index = 0; index < points.length - 1; index += 1) {
        const p0 = points[index - 1] || points[index];
        const p1 = points[index];
        const p2 = points[index + 1];
        const p3 = points[index + 2] || p2;
        const cp1x = p1.x + (p2.x - p0.x) / 6;
        const cp1y = p1.y + (p2.y - p0.y) / 6;
        const cp2x = p2.x - (p3.x - p1.x) / 6;
        const cp2y = p2.y - (p3.y - p1.y) / 6;
        d += ` C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${p2.x} ${p2.y}`;
      }
      return d;
    }

    function buildDashboardAreaPath(points, baseY) {
      if (!Array.isArray(points) || !points.length) return "";
      return `${buildDashboardSmoothPath(points)} L ${points.at(-1).x} ${baseY} L ${points[0].x} ${baseY} Z`;
    }

    function renderDashboardActivityStats(buckets) {
      const totalDraws = buckets.reduce((sum, bucket) => sum + Number(bucket.drawCount || 0), 0);
      const totalAnalyses = buckets.reduce((sum, bucket) => sum + Number(bucket.value || 0), 0);
      const averagePerSession = totalDraws > 0 ? totalAnalyses / totalDraws : 0;
      return `
        <div class="lotto-dashboard-mini-stat">
          <div class="lotto-dashboard-mini-stat-label">Tổng số kỳ</div>
          <div class="lotto-dashboard-mini-stat-value">${escapeHtml(formatDashboardInteger(totalDraws))}</div>
        </div>
        <div class="lotto-dashboard-mini-stat">
          <div class="lotto-dashboard-mini-stat-label">Số lần phân tích</div>
          <div class="lotto-dashboard-mini-stat-value">${escapeHtml(formatDashboardInteger(totalAnalyses))}</div>
        </div>
        <div class="lotto-dashboard-mini-stat">
          <div class="lotto-dashboard-mini-stat-label">Trung bình mỗi phiên</div>
          <div class="lotto-dashboard-mini-stat-value">${escapeHtml(formatDashboardNumber(averagePerSession, 1))}</div>
        </div>
      `;
    }

    function renderDashboardActivityChart(buckets, mode) {
      const normalizedMode = normalizeDashboardActivityViewMode(mode);
      const totalDraws = buckets.reduce((sum, bucket) => sum + Number(bucket.drawCount || 0), 0);
      if (!totalDraws) {
        return `<div class="lotto-dashboard-empty-state">Chưa đủ dữ liệu thật để dựng biểu đồ hoạt động theo ${normalizedMode === "day" ? "ngày" : normalizedMode === "week" ? "tuần" : "tháng"}.</div>`;
      }
      const values = buckets.map(item => Number(item.value || 0));
      const targetValue = values.reduce((sum, value) => sum + value, 0) / Math.max(1, values.length);
      const maxValue = Math.max(1, targetValue, ...values);
      const width = 720;
      const height = 310;
      const paddingX = 28;
      const paddingTop = 16;
      const paddingBottom = 42;
      const chartWidth = width - paddingX * 2;
      const chartHeight = height - paddingTop - paddingBottom;
      const points = buckets.map((bucket, index) => ({
        ...bucket,
        x: paddingX + (buckets.length === 1 ? chartWidth / 2 : (chartWidth / Math.max(1, buckets.length - 1)) * index),
        y: paddingTop + chartHeight - ((Number(bucket.value || 0) / maxValue) * chartHeight),
      }));
      const goalY = paddingTop + chartHeight - ((targetValue / maxValue) * chartHeight);
      const linePath = buildDashboardSmoothPath(points);
      const areaPath = buildDashboardAreaPath(points, paddingTop + chartHeight);
      const gridLines = Array.from({ length: 4 }, (_, index) => {
        const ratio = index / 3;
        const y = paddingTop + chartHeight - ratio * chartHeight;
        const value = maxValue * ratio;
        return { y, value };
      }).reverse();
      return `
        <div class="lotto-dashboard-line-chart-shell">
          <div class="lotto-dashboard-line-chart-wrap">
            <svg class="lotto-dashboard-line-chart" viewBox="0 0 ${width} ${height}" aria-hidden="true">
              <defs>
                <linearGradient id="lottoDashboardAreaFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="rgba(109, 92, 255, .28)"></stop>
                  <stop offset="100%" stop-color="rgba(109, 92, 255, 0)"></stop>
                </linearGradient>
              </defs>
              ${gridLines.map(line => `
                <g>
                  <line class="lotto-dashboard-grid-line" x1="${paddingX}" y1="${line.y}" x2="${width - paddingX}" y2="${line.y}"></line>
                  <text class="lotto-dashboard-grid-label" x="${paddingX - 8}" y="${line.y + 4}" text-anchor="end">${escapeHtml(formatDashboardInteger(Math.round(line.value)))}</text>
                </g>
              `).join("")}
              <line class="lotto-dashboard-target-line" x1="${paddingX}" y1="${goalY}" x2="${width - paddingX}" y2="${goalY}"></line>
              <path class="lotto-dashboard-line-area" d="${areaPath}"></path>
              <path class="lotto-dashboard-line-path" d="${linePath}"></path>
              ${points.map(point => `
                <circle
                  class="lotto-dashboard-line-point"
                  cx="${point.x}"
                  cy="${point.y}"
                  r="5"
                  data-dashboard-label="${escapeHtml(point.tooltipLabel)}"
                  data-dashboard-value="${escapeHtml(formatDashboardInteger(point.value))}"
                  data-dashboard-meta="${escapeHtml(`${formatDashboardInteger(point.drawCount)} kỳ • ${point.value ? formatDashboardNumber(point.value / Math.max(1, point.drawCount), 1) : "0.0"} số/kỳ`)}"
                ></circle>
              `).join("")}
              ${points.map(point => `<text class="lotto-dashboard-axis-label" x="${point.x}" y="${height - 10}" text-anchor="middle">${escapeHtml(point.label)}</text>`).join("")}
              <text class="lotto-dashboard-target-text" x="${width - paddingX}" y="${goalY - 8}" text-anchor="end">Mục tiêu</text>
            </svg>
            <div class="lotto-dashboard-line-tooltip" hidden></div>
          </div>
        </div>
      `;
    }

    function computeDashboardNumberMetrics(entries) {
      const latestDate = getDashboardLatestDate(entries);
      const recent30Start = shiftDashboardDate(latestDate, -29);
      const recent7Start = shiftDashboardDate(latestDate, -6);
      const recent30Entries = filterDashboardEntriesInRange(entries, recent30Start, latestDate);
      const recent7Entries = filterDashboardEntriesInRange(entries, recent7Start, latestDate);
      const longCountMap = new Map();
      const recent30CountMap = new Map();
      const recent7CountMap = new Map();
      const lastSeenMap = new Map();
      entries.forEach((entry, index) => {
        entry.mainNumbers.forEach(number => {
          longCountMap.set(number, Number(longCountMap.get(number) || 0) + 1);
          lastSeenMap.set(number, index);
        });
      });
      recent30Entries.forEach(entry => {
        entry.mainNumbers.forEach(number => {
          recent30CountMap.set(number, Number(recent30CountMap.get(number) || 0) + 1);
        });
      });
      recent7Entries.forEach(entry => {
        entry.mainNumbers.forEach(number => {
          recent7CountMap.set(number, Number(recent7CountMap.get(number) || 0) + 1);
        });
      });
      const totalLongEntries = Math.max(1, entries.length);
      const totalRecent30Entries = Math.max(1, recent30Entries.length || 1);
      const totalRecent7Entries = Math.max(1, recent7Entries.length || 1);
      const baseRows = range(1, 80).map(number => {
        const longCount = Number(longCountMap.get(number) || 0);
        const recent30Count = Number(recent30CountMap.get(number) || 0);
        const recent7Count = Number(recent7CountMap.get(number) || 0);
        const lastSeenIndex = lastSeenMap.has(number) ? Number(lastSeenMap.get(number)) : -1;
        const delay = lastSeenIndex >= 0 ? Math.max(0, entries.length - 1 - lastSeenIndex) : entries.length;
        const longRate = longCount / totalLongEntries;
        const recent30Rate = recent30Count / totalRecent30Entries;
        return {
          number,
          longCount,
          recent30Count,
          recent7Count,
          delay,
          longRate,
          recent30Rate,
        };
      });
      const maxLong = Math.max(1, ...baseRows.map(row => row.longCount));
      const maxRecent30 = Math.max(1, ...baseRows.map(row => row.recent30Count));
      const maxRecent7 = Math.max(1, ...baseRows.map(row => row.recent7Count));
      const maxDelay = Math.max(1, ...baseRows.map(row => row.delay));
      return baseRows.map(row => {
        const longNorm = row.longCount / maxLong;
        const recent30Norm = row.recent30Count / maxRecent30;
        const recent7Norm = row.recent7Count / maxRecent7;
        const delayNorm = row.delay / maxDelay;
        const stability = 1 - Math.min(1, Math.abs(row.recent30Rate - row.longRate) / Math.max(0.02, row.longRate || 0.02));
        return {
          ...row,
          score: (0.35 * longNorm) + (0.35 * recent30Norm) + (0.15 * recent7Norm) + (0.15 * (1 - delayNorm)),
          confidence: (0.45 * stability) + (0.35 * longNorm) + (0.2 * (1 - delayNorm)),
        };
      });
    }

    function computeDashboardDistributionRows(entries, mode) {
      const normalizedMode = normalizeDashboardDistributionViewMode(mode);
      const metrics = computeDashboardNumberMetrics(entries);
      if (normalizedMode === "numberType") {
        const latestDate = getDashboardLatestDate(entries);
        const recent30Entries = filterDashboardEntriesInRange(entries, shiftDashboardDate(latestDate, -29), latestDate);
        const groups = [
          { key: "low", label: "Số thấp 1-20", min: 1, max: 20, color: DASHBOARD_DISTRIBUTION_COLORS.low, count: 0 },
          { key: "midlow", label: "Số giữa 21-40", min: 21, max: 40, color: DASHBOARD_DISTRIBUTION_COLORS.midlow, count: 0 },
          { key: "midhigh", label: "Số cao 41-60", min: 41, max: 60, color: DASHBOARD_DISTRIBUTION_COLORS.midhigh, count: 0 },
          { key: "high", label: "Số rất cao 61-80", min: 61, max: 80, color: DASHBOARD_DISTRIBUTION_COLORS.high, count: 0 },
        ];
        recent30Entries.forEach(entry => {
          entry.mainNumbers.forEach(number => {
            const group = groups.find(item => number >= item.min && number <= item.max);
            if (group) group.count += 1;
          });
        });
        const total = groups.reduce((sum, item) => sum + item.count, 0) || 1;
        return groups.map(item => ({
          ...item,
          percent: (item.count / total) * 100,
          countLabel: `${formatDashboardInteger(item.count)} lượt`,
          meta: "30 ngày gần nhất",
        }));
      }
      if (normalizedMode === "confidence") {
        const groups = [
          { key: "trusted", label: "Rất tin cậy", color: DASHBOARD_DISTRIBUTION_COLORS.trusted, count: 0 },
          { key: "reliable", label: "Khá tin cậy", color: DASHBOARD_DISTRIBUTION_COLORS.reliable, count: 0 },
          { key: "watching", label: "Đang theo dõi", color: DASHBOARD_DISTRIBUTION_COLORS.watching, count: 0 },
          { key: "volatile", label: "Biến động", color: DASHBOARD_DISTRIBUTION_COLORS.volatile, count: 0 },
          { key: "risky", label: "Rủi ro cao", color: DASHBOARD_DISTRIBUTION_COLORS.risky, count: 0 },
        ];
        metrics.forEach(item => {
          let key = "risky";
          if (item.confidence >= 0.82) key = "trusted";
          else if (item.confidence >= 0.66) key = "reliable";
          else if (item.confidence >= 0.48) key = "watching";
          else if (item.confidence >= 0.3) key = "volatile";
          groups.find(group => group.key === key).count += 1;
        });
        const total = groups.reduce((sum, item) => sum + item.count, 0) || 1;
        return groups.map(item => ({
          ...item,
          percent: (item.count / total) * 100,
          countLabel: `${formatDashboardInteger(item.count)} số`,
          meta: "Recent vs long-term",
        }));
      }
      const groups = [
        { key: "strong", label: "Rất mạnh", color: DASHBOARD_DISTRIBUTION_COLORS.strong, count: 0 },
        { key: "potential", label: "Tiềm năng", color: DASHBOARD_DISTRIBUTION_COLORS.potential, count: 0 },
        { key: "neutral", label: "Trung tính", color: DASHBOARD_DISTRIBUTION_COLORS.neutral, count: 0 },
        { key: "weak", label: "Yếu", color: DASHBOARD_DISTRIBUTION_COLORS.weak, count: 0 },
        { key: "reject", label: "Loại bỏ", color: DASHBOARD_DISTRIBUTION_COLORS.reject, count: 0 },
      ];
      const sorted = [...metrics].sort((a, b) => b.score - a.score || a.number - b.number);
      const totalNumbers = Math.max(1, sorted.length);
      sorted.forEach((item, index) => {
        const ratio = index / totalNumbers;
        let key = "reject";
        if (ratio < 0.15) key = "strong";
        else if (ratio < 0.4) key = "potential";
        else if (ratio < 0.7) key = "neutral";
        else if (ratio < 0.9) key = "weak";
        groups.find(group => group.key === key).count += 1;
      });
      return groups.map(item => ({
        ...item,
        percent: (item.count / totalNumbers) * 100,
        countLabel: `${formatDashboardInteger(item.count)} số`,
        meta: "Scoring nội bộ từ dữ liệu thật",
      }));
    }

    function renderDashboardDistributionPanel(entries, mode) {
      const rows = computeDashboardDistributionRows(entries, mode);
      const total = rows.reduce((sum, row) => sum + Number(row.count || 0), 0);
      const activeRows = rows.filter(row => Number(row.count || 0) > 0);
      if (!activeRows.length || !total) {
        return `<div class="lotto-dashboard-empty-state">Chưa đủ dữ liệu để dựng donut phân bổ cho dashboard.</div>`;
      }
      const radius = 76;
      const stroke = 22;
      const circumference = 2 * Math.PI * radius;
      let accumulated = 0;
      const segments = activeRows.map(row => {
        const segmentLength = (Number(row.percent || 0) / 100) * circumference;
        const dashOffset = circumference - accumulated;
        accumulated += segmentLength;
        return `<circle class="lotto-dashboard-donut-segment" cx="100" cy="100" r="${radius}" fill="none" stroke="${escapeHtml(row.color)}" stroke-width="${stroke}" stroke-linecap="round" stroke-dasharray="${segmentLength.toFixed(3)} ${(circumference - segmentLength).toFixed(3)}" stroke-dashoffset="${dashOffset.toFixed(3)}"></circle>`;
      }).join("");
      return `
        <div class="lotto-dashboard-donut-layout">
          <div class="lotto-dashboard-donut-wrap">
            <svg class="lotto-dashboard-donut-svg" viewBox="0 0 200 200" aria-hidden="true">
              <circle class="lotto-dashboard-donut-track" cx="100" cy="100" r="${radius}" fill="none" stroke-width="${stroke}"></circle>
              <g class="lotto-dashboard-donut-ring">${segments}</g>
            </svg>
            <div class="lotto-dashboard-donut-center">
              <div class="lotto-dashboard-donut-center-value">100%</div>
              <div class="lotto-dashboard-donut-center-label">Tỷ trọng</div>
              <div class="lotto-dashboard-donut-center-meta">${escapeHtml(`${formatDashboardInteger(activeRows.length)} nhóm`)}</div>
            </div>
          </div>
          <div class="lotto-dashboard-donut-legend">
            ${rows.map(row => `
              <div class="lotto-dashboard-donut-legend-item">
                <span class="lotto-dashboard-donut-legend-swatch" style="--dashboard-color:${escapeHtml(row.color)}"></span>
                <div class="lotto-dashboard-donut-legend-copy">
                  <div class="lotto-dashboard-donut-legend-label">${escapeHtml(row.label)}</div>
                  <div class="lotto-dashboard-donut-legend-meta">${escapeHtml(row.meta || "")}</div>
                </div>
                <div class="lotto-dashboard-donut-legend-values">
                  <div class="lotto-dashboard-donut-legend-percent">${escapeHtml(formatChartStatsPercent(row.percent))}</div>
                  <div class="lotto-dashboard-donut-legend-count">${escapeHtml(row.countLabel || `${formatDashboardInteger(row.count)}`)}</div>
                </div>
              </div>
            `).join("")}
          </div>
        </div>
      `;
    }

    function renderDashboardActivityTabs() {
      document.querySelectorAll("[data-dashboard-activity-view]").forEach(button => {
        const viewMode = normalizeDashboardActivityViewMode(button.dataset.dashboardActivityView);
        const isActive = viewMode === dashboardActivityViewMode;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
    }

    function renderDashboardDistributionTabs() {
      document.querySelectorAll("[data-dashboard-distribution-view]").forEach(button => {
        const viewMode = normalizeDashboardDistributionViewMode(button.dataset.dashboardDistributionView);
        const isActive = viewMode === dashboardDistributionViewMode;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
    }

    function bindDashboardLineTooltip() {
      const wrap = document.querySelector("#lottoDashboardActivityOut .lotto-dashboard-line-chart-wrap");
      const tooltip = wrap?.querySelector(".lotto-dashboard-line-tooltip");
      if (!wrap || !tooltip) return;
      const hide = () => {
        tooltip.hidden = true;
      };
      wrap.querySelectorAll(".lotto-dashboard-line-point").forEach(point => {
        const show = event => {
          const bounds = wrap.getBoundingClientRect();
          const offsetX = Math.max(14, Math.min(bounds.width - 14, event.clientX - bounds.left));
          const offsetY = Math.max(16, event.clientY - bounds.top - 18);
          tooltip.innerHTML = `
            <div class="lotto-dashboard-line-tooltip-label">${escapeHtml(point.dataset.dashboardLabel || "")}</div>
            <div class="lotto-dashboard-line-tooltip-value">${escapeHtml(point.dataset.dashboardValue || "0")}</div>
            <div class="lotto-dashboard-line-tooltip-meta">${escapeHtml(point.dataset.dashboardMeta || "")}</div>
          `;
          tooltip.style.left = `${offsetX}px`;
          tooltip.style.top = `${offsetY}px`;
          tooltip.hidden = false;
        };
        point.addEventListener("mouseenter", show);
        point.addEventListener("mousemove", show);
        point.addEventListener("mouseleave", hide);
      });
      wrap.addEventListener("mouseleave", hide);
    }

    function renderDashboardPanel() {
      const kpisHost = document.getElementById("lottoDashboardKpis");
      const activityStatsHost = document.getElementById("lottoDashboardActivityStats");
      const activityOut = document.getElementById("lottoDashboardActivityOut");
      const distributionOut = document.getElementById("lottoDashboardDistributionOut");
      const updatedAtHost = document.getElementById("lottoDashboardUpdatedAt");
      const statusHost = document.getElementById("lottoDashboardStatus");
      if (!kpisHost || !activityStatsHost || !activityOut || !distributionOut || !updatedAtHost || !statusHost) return;

      renderDashboardActivityTabs();
      renderDashboardDistributionTabs();

      const entries = buildDashboardEntries();
      const loadedTimes = DASHBOARD_LOTTO_TYPES
        .map(type => new Date(String(getLiveHistoryFeed(type)?.loadedAt || "").trim()))
        .filter(dateValue => dateValue instanceof Date && !Number.isNaN(dateValue.getTime()));
      updatedAtHost.textContent = `Cập nhật: ${loadedTimes.length ? formatDashboardRelativeTime(loadedTimes.sort((a, b) => b.getTime() - a.getTime())[0]) : "đang chờ dữ liệu"}`;

      if (dashboardPanelError) {
        statusHost.hidden = false;
        statusHost.className = "lotto-dashboard-status is-warning";
        statusHost.textContent = dashboardPanelError;
      } else {
        statusHost.hidden = true;
        statusHost.className = "lotto-dashboard-status";
        statusHost.textContent = "";
      }

      if (dashboardPanelLoading && !entries.length) {
        kpisHost.innerHTML = `
          <div class="lotto-dashboard-empty-card">Đang gom dữ liệu all_day.csv để dựng KPI 7 ngày và 30 ngày...</div>
          <div class="lotto-dashboard-empty-card">Dashboard đang tải biểu đồ hoạt động và phân bổ số lotto.</div>
        `;
        activityStatsHost.innerHTML = "";
        activityOut.className = "lotto-dashboard-panel-body lotto-dashboard-panel-body-muted";
        activityOut.innerHTML = "Đang tải biểu đồ đường từ dữ liệu thật...";
        distributionOut.className = "lotto-dashboard-panel-body lotto-dashboard-panel-body-muted";
        distributionOut.innerHTML = "Đang tải donut phân bổ số lotto...";
        return;
      }

      if (!entries.length) {
        kpisHost.innerHTML = `<div class="lotto-dashboard-empty-card">Chưa có dữ liệu Keno, 5/35, 6/45 hoặc 6/55 để dựng dashboard lotto.</div>`;
        activityStatsHost.innerHTML = "";
        activityOut.className = "lotto-dashboard-panel-body lotto-dashboard-panel-body-muted";
        activityOut.innerHTML = "Hệ thống cần ít nhất một nguồn all_day.csv đã nạp để vẽ biểu đồ hoạt động.";
        distributionOut.className = "lotto-dashboard-panel-body lotto-dashboard-panel-body-muted";
        distributionOut.innerHTML = "Khi có dữ liệu thật, donut phân bổ sẽ hiển thị ngay tại đây.";
        return;
      }

      const latestDate = getDashboardLatestDate(entries);
      const recent7 = computeDashboardWindowMetrics(entries, 7, latestDate);
      const recent30 = computeDashboardWindowMetrics(entries, 30, latestDate);
      kpisHost.innerHTML = `
        ${renderDashboardKpiCard("7 Ngày Qua", recent7)}
        ${renderDashboardKpiCard("30 Ngày Qua", recent30)}
      `;

      const activityBuckets = getDashboardActivityBuckets(entries, dashboardActivityViewMode);
      activityStatsHost.innerHTML = renderDashboardActivityStats(activityBuckets);
      activityOut.className = "lotto-dashboard-panel-body";
      activityOut.innerHTML = renderDashboardActivityChart(activityBuckets, dashboardActivityViewMode);

      distributionOut.className = "lotto-dashboard-panel-body";
      distributionOut.innerHTML = renderDashboardDistributionPanel(entries, dashboardDistributionViewMode);
      window.setTimeout(bindDashboardLineTooltip, 0);
    }

    async function startDashboardRefresh({ force = false, silent = true } = {}) {
      const refreshToken = ++dashboardPanelRefreshToken;
      dashboardPanelLoading = true;
      dashboardPanelError = "";
      renderDashboardPanel();
      const results = await Promise.allSettled(
        DASHBOARD_LOTTO_TYPES.map(type => fetchLiveHistory(type, "all", { force, silent }))
      );
      if (refreshToken !== dashboardPanelRefreshToken) return;
      dashboardPanelLoading = false;
      const failed = results
        .map((result, index) => ({ result, type: DASHBOARD_LOTTO_TYPES[index] }))
        .filter(item => item.result.status === "rejected")
        .map(item => `${getDashboardTypeMeta(item.type).label}: ${String(item.result.reason?.message || item.result.reason || "Lỗi không rõ")}`);
      dashboardPanelError = failed.length
        ? `Một vài nguồn dashboard chưa tải được: ${failed.join(" • ")}`
        : "";
      renderDashboardPanel();
    }

    function getDashboardTypeMeta(type) {
      const mapping = {
        KENO: { label: "Keno", accent: "#29d2d4", icon: "◎", family: "keno", heroNote: "20 số mỗi kỳ, ưu tiên nhìn dải nóng và nhịp lặp lại gần đây." },
        LOTO_5_35: { label: "Lotto 5/35", accent: "#6d5cff", icon: "◈", family: "ball", heroNote: "Theo dõi riêng 5 số chính và ĐB để nhìn rõ nhịp của game 5/35." },
        LOTO_6_45: { label: "Mega 6/45", accent: "#4f8cff", icon: "◉", family: "ball", heroNote: "Nhìn nhịp 6 bóng chính, nhiệt bóng và chẵn lẻ của Mega 6/45." },
        LOTO_6_55: { label: "Power 6/55", accent: "#ffb44d", icon: "✦", family: "ball", heroNote: "Tập trung vào 6 bóng chính cùng số ĐB để đọc đúng nhịp của Power 6/55." },
        MAX_3D: { label: "Lotto 3D", accent: "#ff7760", icon: "▣", family: "threeDigit", heroNote: "Phân tích riêng đầu, đuôi và nhịp bộ 3 số của 3D." },
        MAX_3D_PRO: { label: "Lotto 3D Pro", accent: "#27c18c", icon: "⬢", family: "threeDigit", heroNote: "Theo dõi bộ 3 số, đầu đuôi và cường độ xuất hiện của 3D Pro." },
      };
      return mapping[normalizeDashboardGame(type)] || mapping.KENO;
    }

    function getDashboardLatestEntry(entries) {
      return Array.isArray(entries) && entries.length ? entries[entries.length - 1] : null;
    }

    function getDashboardLatestDate(entries) {
      const latest = getDashboardLatestEntry(entries)?.dayStart;
      return latest instanceof Date && !Number.isNaN(latest.getTime()) ? latest : floorDashboardDate(getSyncedNowDate());
    }

    function getDashboardFamily(type) {
      return getDashboardTypeMeta(type).family || "ball";
    }

    function getDashboardRangeGroups(type) {
      return CHART_STATS_GROUPS[normalizeDashboardGame(type)] || [];
    }

    function computeDashboardDigitSum(value) {
      return String(Math.max(0, Number(value || 0))).padStart(3, "0").split("").reduce((sum, digit) => sum + Number(digit || 0), 0);
    }

    function computeDashboardEntryActivityValue(type, numbers, draw) {
      const safeNumbers = (Array.isArray(numbers) ? numbers : []).map(Number).filter(Number.isInteger);
      if (getDashboardFamily(type) === "threeDigit") {
        return safeNumbers.reduce((sum, value) => sum + computeDashboardDigitSum(value), 0);
      }
      const specialValue = TYPES[type]?.hasSpecial && Number.isInteger(Number(draw?.special)) ? Number(draw.special) : 0;
      return safeNumbers.reduce((sum, value) => sum + value, 0) + specialValue;
    }

    function buildDashboardEntries() {
      const type = normalizeDashboardGame(dashboardSelectedGame);
      return buildStatsEntriesForFeed(type, getLiveHistoryFeed(type))
        .map(entry => {
          const parsedDate = parseLiveDate(entry.draw?.date || "");
          if (!(parsedDate instanceof Date) || Number.isNaN(parsedDate.getTime())) return null;
          const mainNumbers = TYPES[type]?.threeDigit
            ? [...new Set(extractThreeDigitTokensFromLines(entry.draw?.displayLines))]
            : (Array.isArray(entry.draw?.main) ? entry.draw.main : []).map(Number).filter(Number.isInteger);
          return {
            type,
            ky: entry.ky,
            draw: entry.draw,
            date: parsedDate,
            dayStart: floorDashboardDate(parsedDate),
            mainNumbers,
            hitCount: mainNumbers.length,
            activityValue: computeDashboardEntryActivityValue(type, mainNumbers, entry.draw),
          };
        })
        .filter(Boolean)
        .sort((a, b) => {
          const dateDelta = a.date.getTime() - b.date.getTime();
          if (dateDelta !== 0) return dateDelta;
          return kySortValue(a.ky) - kySortValue(b.ky);
        });
    }

    function getDashboardBucketKey(dateValue, mode) {
      if (mode === "month") {
        return `${dateValue.getFullYear()}-${String(dateValue.getMonth() + 1).padStart(2, "0")}`;
      }
      if (mode === "week") {
        return `week-${formatDashboardDateKey(getDashboardWeekStart(dateValue))}`;
      }
      return formatDashboardDateKey(floorDashboardDate(dateValue));
    }

    function getDashboardActivityBuckets(entries, mode) {
      const normalizedMode = normalizeDashboardActivityViewMode(mode);
      const latestDate = getDashboardLatestDate(entries);
      const limit = DASHBOARD_ACTIVITY_BUCKET_LIMITS[normalizedMode] || 12;
      const buckets = [];
      if (normalizedMode === "month") {
        const latestMonth = new Date(latestDate.getFullYear(), latestDate.getMonth(), 1);
        for (let index = limit - 1; index >= 0; index -= 1) {
          const start = addDashboardMonths(latestMonth, -index);
          const end = new Date(start.getFullYear(), start.getMonth() + 1, 0, 23, 59, 59, 999);
          buckets.push({ key: getDashboardBucketKey(start, normalizedMode), label: formatDashboardMonthLabel(start), tooltipLabel: `Tháng ${formatDashboardMonthLabel(start)}`, start, end, value: 0, drawCount: 0 });
        }
      } else if (normalizedMode === "week") {
        const latestWeek = getDashboardWeekStart(latestDate);
        for (let index = limit - 1; index >= 0; index -= 1) {
          const start = shiftDashboardDate(latestWeek, -7 * index);
          const end = new Date(start.getTime());
          end.setDate(end.getDate() + 6);
          end.setHours(23, 59, 59, 999);
          buckets.push({ key: getDashboardBucketKey(start, normalizedMode), label: formatDashboardShortDate(start), tooltipLabel: `${formatDashboardShortDate(start)} - ${formatDashboardShortDate(end)}`, start, end, value: 0, drawCount: 0 });
        }
      } else {
        const latestDay = floorDashboardDate(latestDate);
        for (let index = limit - 1; index >= 0; index -= 1) {
          const start = shiftDashboardDate(latestDay, -index);
          const end = new Date(start.getTime());
          end.setHours(23, 59, 59, 999);
          buckets.push({ key: getDashboardBucketKey(start, normalizedMode), label: formatDashboardShortDate(start), tooltipLabel: formatLiveDateFromDate(start), start, end, value: 0, drawCount: 0 });
        }
      }
      const bucketMap = new Map(buckets.map(item => [item.key, item]));
      (Array.isArray(entries) ? entries : []).forEach(entry => {
        const bucketKey = getDashboardBucketKey(entry.date, normalizedMode);
        const bucket = bucketMap.get(bucketKey);
        if (!bucket) return;
        bucket.value += Number(entry.activityValue || 0);
        bucket.drawCount += 1;
      });
      return buckets;
    }

    function buildDashboardHeroStatus(type, entries) {
      const latestDate = getDashboardLatestDate(entries);
      const recentWindow = filterDashboardEntriesInRange(entries, shiftDashboardDate(latestDate, -6), latestDate);
      const previousWindow = filterDashboardEntriesInRange(entries, shiftDashboardDate(latestDate, -13), shiftDashboardDate(latestDate, -7));
      const recentValue = recentWindow.reduce((sum, entry) => sum + Number(entry.activityValue || 0), 0);
      const previousValue = previousWindow.reduce((sum, entry) => sum + Number(entry.activityValue || 0), 0);
      const diffRatio = previousValue > 0 ? (recentValue - previousValue) / previousValue : 0;
      if (diffRatio >= 0.08) return { label: "Tăng", tone: "up" };
      if (diffRatio <= -0.08) return { label: "Giảm nhẹ", tone: "down" };
      return { label: "Ổn định", tone: "stable" };
    }

    function renderDashboardHeroNumbers(type, latestEntry) {
      if (!latestEntry?.draw) return `<div class="lotto-dashboard-empty-state">Chưa có kỳ quay mới nhất để hiển thị.</div>`;
      if (getDashboardFamily(type) === "threeDigit") {
        const lines = Array.isArray(latestEntry.draw?.displayLines) && latestEntry.draw.displayLines.length
          ? latestEntry.draw.displayLines
          : latestEntry.mainNumbers.map(number => formatPredictNumber(number, type));
        return `
          <div class="lotto-dashboard-hero-lines">
            ${lines.map(lineText => `<div class="lotto-dashboard-hero-line">${escapeHtml(String(lineText || "").trim())}</div>`).join("")}
          </div>
        `;
      }
      const mainNumbers = (Array.isArray(latestEntry.draw?.main) ? latestEntry.draw.main : latestEntry.mainNumbers)
        .map(number => `<span class="lotto-dashboard-result-ball">${escapeHtml(formatPredictNumber(number, type))}</span>`)
        .join("");
      const specialHtml = TYPES[type]?.hasSpecial && Number.isInteger(Number(latestEntry.draw?.special))
        ? `<span class="lotto-dashboard-result-ball is-special">ĐB ${escapeHtml(formatPredictNumber(Number(latestEntry.draw.special), type))}</span>`
        : "";
      return `
        <div class="lotto-dashboard-result-stack ${type === "KENO" ? "is-keno" : ""}">
          <div class="lotto-dashboard-result-row">${mainNumbers}</div>
          ${specialHtml ? `<div class="lotto-dashboard-result-row is-special-row">${specialHtml}</div>` : ""}
        </div>
      `;
    }

    function renderDashboardHeroCard(type, entries) {
      const meta = getDashboardTypeMeta(type);
      const latestEntry = getDashboardLatestEntry(entries);
      if (!latestEntry) {
        return `<div class="lotto-dashboard-empty-card">Chưa có dữ liệu ${escapeHtml(meta.label)} để dựng overview riêng cho game này.</div>`;
      }
      const badge = buildDashboardHeroStatus(type, entries);
      const formattedDate = latestEntry.date instanceof Date ? formatLiveDateFromDate(latestEntry.date) : "Chưa rõ ngày";
      const hotMain = buildStatsFrequencyItems(type, entries)[0] || null;
      const hotSpecial = TYPES[type]?.hasSpecial ? buildStatsFrequencyItems(type, entries, { special: true })[0] : null;
      const insightLine = hotSpecial
        ? `Nhiệt bóng: ${hotMain ? hotMain.label : "--"} • ĐB nóng: ${hotSpecial ? hotSpecial.label : "--"}`
        : `Nhiệt bóng: ${hotMain ? hotMain.label : "--"} • ${meta.heroNote}`;
      return `
        <article class="lotto-dashboard-hero-shell" style="--dashboard-accent:${escapeHtml(meta.accent)}">
          <div class="lotto-dashboard-hero-copy">
            <div class="lotto-dashboard-hero-kicker">${escapeHtml(meta.label)}</div>
            <h3 class="lotto-dashboard-hero-title">Kỳ quay mới nhất #${escapeHtml(latestEntry.ky || "--")}</h3>
            <div class="lotto-dashboard-hero-meta">${escapeHtml(formattedDate)} • ${escapeHtml(`${formatDashboardInteger(latestEntry.hitCount)} kết quả ghi nhận`)}</div>
            <div class="lotto-dashboard-hero-note">${escapeHtml(insightLine)}</div>
          </div>
          <div class="lotto-dashboard-hero-result">
            <div class="lotto-dashboard-hero-result-panel">
              <div class="lotto-dashboard-hero-result-head">
                <div class="lotto-dashboard-hero-result-label">Bộ số kỳ này</div>
                <span class="lotto-dashboard-badge is-${escapeHtml(badge.tone)}">${escapeHtml(badge.label)}</span>
              </div>
              <div class="lotto-dashboard-hero-result-body">
                ${renderDashboardHeroNumbers(type, latestEntry)}
              </div>
            </div>
          </div>
        </article>
      `;
    }

    function computeDashboardQuickStats(type, entries) {
      const family = getDashboardFamily(type);
      const recentEntries = entries.slice(-Math.min(entries.length, 36));
      if (!recentEntries.length) return [];
      if (family === "threeDigit") {
        const tokenCount = recentEntries.reduce((sum, entry) => sum + entry.mainNumbers.length, 0);
        const tokenValues = recentEntries.flatMap(entry => entry.mainNumbers);
        const tokenFreq = buildStatsFrequencyItems(type, recentEntries);
        const headCounts = Array.from({ length: 10 }, (_, digit) => ({ digit, count: 0 }));
        const tailCounts = Array.from({ length: 10 }, (_, digit) => ({ digit, count: 0 }));
        tokenValues.forEach(value => {
          const head = Math.floor(Number(value) / 100);
          const tail = Number(value) % 10;
          if (headCounts[head]) headCounts[head].count += 1;
          if (tailCounts[tail]) tailCounts[tail].count += 1;
        });
        const hotHead = [...headCounts].sort((a, b) => b.count - a.count || a.digit - b.digit)[0];
        const hotTail = [...tailCounts].sort((a, b) => b.count - a.count || a.digit - b.digit)[0];
        const averageDigitSum = tokenCount ? tokenValues.reduce((sum, value) => sum + computeDashboardDigitSum(value), 0) / tokenCount : 0;
        const averageSpan = recentEntries.length
          ? recentEntries.reduce((sum, entry) => {
              const ordered = [...entry.mainNumbers].sort((a, b) => a - b);
              return sum + (ordered.length > 1 ? (ordered[ordered.length - 1] - ordered[0]) : 0);
            }, 0) / recentEntries.length
          : 0;
        return [
          { label: "Tổng kỳ", value: formatDashboardInteger(recentEntries.length), meta: "kỳ gần nhất đang xét", accent: "neutral" },
          { label: "Tổng bộ", value: formatDashboardInteger(tokenCount), meta: "bộ 3 số ghi nhận", accent: "accent" },
          { label: "Bộ nóng", value: tokenFreq[0]?.label || "--", meta: tokenFreq[0] ? `${formatDashboardInteger(tokenFreq[0].count)} lần` : "chưa có dữ liệu", accent: "accent" },
          { label: "Đầu nóng", value: hotHead ? `${hotHead.digit}` : "--", meta: hotHead ? `${formatDashboardInteger(hotHead.count)} lượt` : "chưa có dữ liệu", accent: "secondary" },
          { label: "Đuôi nóng", value: hotTail ? `${hotTail.digit}` : "--", meta: hotTail ? `${formatDashboardInteger(hotTail.count)} lượt` : "chưa có dữ liệu", accent: "secondary" },
          { label: "Tổng điểm TB", value: formatDashboardNumber(averageDigitSum, 1), meta: `biên độ TB ${formatDashboardNumber(averageSpan, 1)}`, accent: "neutral" },
        ];
      }
      const totalNumbers = recentEntries.reduce((sum, entry) => sum + entry.mainNumbers.length, 0);
      const midpoint = (TYPES[type].mainMin + TYPES[type].mainMax) / 2;
      let oddCount = 0;
      let evenCount = 0;
      let highCount = 0;
      let lowCount = 0;
      recentEntries.forEach(entry => {
        entry.mainNumbers.forEach(number => {
          if (number % 2 === 0) evenCount += 1;
          else oddCount += 1;
          if (number > midpoint) highCount += 1;
          else lowCount += 1;
        });
      });
      const mainRanking = buildStatsFrequencyItems(type, recentEntries);
      const averageSpan = recentEntries.length
        ? recentEntries.reduce((sum, entry) => {
            const ordered = [...entry.mainNumbers].sort((a, b) => a - b);
            return sum + (ordered.length > 1 ? (ordered[ordered.length - 1] - ordered[0]) : 0);
          }, 0) / recentEntries.length
        : 0;
      const averageShift = recentEntries.length > 1
        ? recentEntries.slice(1).reduce((sum, entry, index) => {
            const previous = recentEntries[index];
            return sum + Math.abs(Number(entry.activityValue || 0) - Number(previous.activityValue || 0));
          }, 0) / Math.max(1, recentEntries.length - 1)
        : 0;
      const specialRanking = TYPES[type]?.hasSpecial ? buildStatsFrequencyItems(type, recentEntries, { special: true }) : [];
      if (type === "KENO") {
        const groups = getDashboardRangeGroups(type).map(group => ({ ...group, count: 0 }));
        recentEntries.forEach(entry => {
          entry.mainNumbers.forEach(number => {
            const match = groups.find(group => number >= group.min && number <= group.max);
            if (match) match.count += 1;
          });
        });
        const hotGroup = [...groups].sort((a, b) => b.count - a.count || a.min - b.min)[0];
        const averageRepeat = recentEntries.length > 1
          ? recentEntries.slice(1).reduce((sum, entry, index) => {
              const previousSet = new Set(recentEntries[index].mainNumbers);
              const overlap = entry.mainNumbers.filter(number => previousSet.has(number)).length;
              return sum + overlap;
            }, 0) / Math.max(1, recentEntries.length - 1)
          : 0;
        return [
          { label: "Tổng kỳ", value: formatDashboardInteger(recentEntries.length), meta: "kỳ gần nhất đang xét", accent: "neutral" },
          { label: "Tổng lượt số", value: formatDashboardInteger(totalNumbers), meta: "20 số mỗi kỳ", accent: "accent" },
          { label: "Chẵn / Lẻ", value: `${formatDashboardInteger(evenCount)} / ${formatDashboardInteger(oddCount)}`, meta: "cân bằng nhịp bóng", accent: "neutral" },
          { label: "Tài / Xỉu", value: `${formatDashboardInteger(highCount)} / ${formatDashboardInteger(lowCount)}`, meta: "trên / dưới mốc 40.5", accent: "secondary" },
          { label: "Dải nóng", value: hotGroup?.label || "--", meta: hotGroup ? `${formatDashboardInteger(hotGroup.count)} lượt` : "chưa có dữ liệu", accent: "accent" },
          { label: "Lặp lại TB", value: formatDashboardNumber(averageRepeat, 1), meta: `tịnh tiến ${formatDashboardNumber(averageShift, 1)}`, accent: "secondary" },
        ];
      }
      return [
        { label: "Tổng kỳ", value: formatDashboardInteger(recentEntries.length), meta: "kỳ gần nhất đang xét", accent: "neutral" },
        { label: "TB bóng / kỳ", value: formatDashboardNumber(totalNumbers / Math.max(1, recentEntries.length), 1), meta: `${formatDashboardInteger(totalNumbers)} lượt số`, accent: "accent" },
        { label: "Chẵn / Lẻ", value: `${formatDashboardInteger(evenCount)} / ${formatDashboardInteger(oddCount)}`, meta: "theo toàn bộ bóng trong mẫu", accent: "neutral" },
        { label: "Tài / Xỉu", value: `${formatDashboardInteger(highCount)} / ${formatDashboardInteger(lowCount)}`, meta: `mốc ${formatDashboardNumber(midpoint, 1)}`, accent: "secondary" },
        { label: TYPES[type]?.hasSpecial ? "ĐB nóng" : "Nhiệt bóng", value: (specialRanking[0]?.label || mainRanking[0]?.label || "--"), meta: specialRanking[0] ? `${formatDashboardInteger(specialRanking[0].count)} lần` : (mainRanking[0] ? `${formatDashboardInteger(mainRanking[0].count)} lần` : "chưa có dữ liệu"), accent: "accent" },
        { label: "Khoảng cách TB", value: formatDashboardNumber(averageSpan, 1), meta: `tịnh tiến ${formatDashboardNumber(averageShift, 1)}`, accent: "secondary" },
      ];
    }

    function renderDashboardQuickStats(type, entries) {
      const cards = computeDashboardQuickStats(type, entries);
      if (!cards.length) {
        return `<div class="lotto-dashboard-empty-card">Chưa đủ dữ liệu để dựng quick stats riêng cho ${escapeHtml(getDashboardTypeMeta(type).label)}.</div>`;
      }
      return cards.map(card => `
        <article class="lotto-dashboard-quick-stat is-${escapeHtml(card.accent || "neutral")}">
          <div class="lotto-dashboard-quick-stat-label">${escapeHtml(card.label)}</div>
          <div class="lotto-dashboard-quick-stat-value">${escapeHtml(card.value)}</div>
          <div class="lotto-dashboard-quick-stat-meta">${escapeHtml(card.meta || "")}</div>
        </article>
      `).join("");
    }

    function renderDashboardGameSelect() {
      const host = document.getElementById("lottoDashboardGameSelect");
      if (!host) return;
      host.innerHTML = DASHBOARD_LOTTO_TYPES.map(type => {
        const meta = getDashboardTypeMeta(type);
        return `<option value="${escapeHtml(type)}">${escapeHtml(meta.label)}</option>`;
      }).join("");
      host.value = normalizeDashboardGame(dashboardSelectedGame);
      if (typeof host.__syncCustomSelect === "function") host.__syncCustomSelect();
    }

    function getDashboardDistributionSubtitle(type, mode) {
      const meta = getDashboardTypeMeta(type);
      const normalizedMode = normalizeDashboardDistributionViewMode(mode);
      if (normalizedMode === "range") return `Phân bổ ${meta.label} theo từng dải số đặc trưng của game đang chọn.`;
      if (normalizedMode === "parity") return `Nhìn nhanh chẵn / lẻ để biết nhịp phân bổ của ${meta.label}.`;
      if (normalizedMode === "head") return `Tập trung vào đầu số của các bộ 3 số trong ${meta.label}.`;
      if (normalizedMode === "tail") return `Tập trung vào đuôi số để soi nhịp ra của ${meta.label}.`;
      return `Phân loại theo mức nóng / lạnh từ dữ liệu thật của ${meta.label}.`;
    }

    function buildDashboardTemperatureRows(type, entries) {
      const items = buildStatsFrequencyItems(type, entries);
      const sorted = [...items].sort((a, b) => b.count - a.count || a.value - b.value);
      const total = Math.max(1, sorted.length);
      const groups = [
        { key: "very-hot", label: "Rất nóng", color: "#ff7a63", count: 0 },
        { key: "hot", label: "Nóng", color: "#ffb44d", count: 0 },
        { key: "warm", label: "Trung tính", color: "#7aa8ff", count: 0 },
        { key: "cold", label: "Lạnh", color: "#63d5ff", count: 0 },
        { key: "sleep", label: "Vắng", color: "#d7e2ff", count: 0 },
      ];
      sorted.forEach((item, index) => {
        const ratio = index / total;
        let bucketIndex = 4;
        if (ratio < 0.12) bucketIndex = 0;
        else if (ratio < 0.3) bucketIndex = 1;
        else if (ratio < 0.6) bucketIndex = 2;
        else if (ratio < 0.85) bucketIndex = 3;
        groups[bucketIndex].count += 1;
      });
      return groups.map(group => ({
        ...group,
        percent: (group.count / total) * 100,
        countLabel: `${formatDashboardInteger(group.count)} ${getDashboardFamily(type) === "threeDigit" ? "bộ" : "số"}`,
        meta: "xếp theo tần suất gần nhất",
      }));
    }

    function computeDashboardDistributionRows(type, entries, mode) {
      const normalizedType = normalizeDashboardGame(type);
      const normalizedMode = normalizeDashboardDistributionViewMode(mode);
      if (normalizedMode === "range") {
        const groups = getDashboardRangeGroups(normalizedType).map(group => ({ ...group, count: 0 }));
        entries.forEach(entry => {
          entry.mainNumbers.forEach(number => {
            const match = groups.find(group => number >= group.min && number <= group.max);
            if (match) match.count += 1;
          });
        });
        const total = groups.reduce((sum, item) => sum + item.count, 0) || 1;
        return groups.map(item => ({
          key: item.key,
          label: item.label,
          color: item.color,
          count: item.count,
          percent: (item.count / total) * 100,
          countLabel: `${formatDashboardInteger(item.count)} lượt`,
          meta: getDashboardTypeMeta(normalizedType).label,
        }));
      }
      if (normalizedMode === "parity") {
        const groups = [
          { key: "even", label: "Chẵn", color: "#5a7cff", count: 0 },
          { key: "odd", label: "Lẻ", color: "#57d4a6", count: 0 },
        ];
        entries.forEach(entry => {
          entry.mainNumbers.forEach(number => {
            groups[number % 2 === 0 ? 0 : 1].count += 1;
          });
        });
        const total = groups.reduce((sum, item) => sum + item.count, 0) || 1;
        return groups.map(item => ({
          ...item,
          percent: (item.count / total) * 100,
          countLabel: `${formatDashboardInteger(item.count)} lượt`,
          meta: "theo toàn bộ bóng trong mẫu",
        }));
      }
      if (normalizedMode === "head" || normalizedMode === "tail") {
        const groups = Array.from({ length: 10 }, (_, digit) => ({
          key: String(digit),
          label: normalizedMode === "head" ? `Đầu ${digit}` : `Đuôi ${digit}`,
          color: `hsl(${200 + (digit * 14)}, 78%, 62%)`,
          count: 0,
        }));
        entries.forEach(entry => {
          entry.mainNumbers.forEach(number => {
            const digit = normalizedMode === "head" ? Math.floor(Number(number) / 100) : (Number(number) % 10);
            if (groups[digit]) groups[digit].count += 1;
          });
        });
        const total = groups.reduce((sum, item) => sum + item.count, 0) || 1;
        return groups.map(item => ({
          ...item,
          percent: (item.count / total) * 100,
          countLabel: `${formatDashboardInteger(item.count)} lượt`,
          meta: normalizedMode === "head" ? "theo đầu số" : "theo đuôi số",
        }));
      }
      return buildDashboardTemperatureRows(normalizedType, entries);
    }

    function renderDashboardDistributionPanel(type, entries, mode) {
      const rows = computeDashboardDistributionRows(type, entries, mode);
      const total = rows.reduce((sum, row) => sum + Number(row.count || 0), 0);
      const activeRows = rows.filter(row => Number(row.count || 0) > 0);
      if (!activeRows.length || !total) {
        return `<div class="lotto-dashboard-empty-state">Chưa đủ dữ liệu để dựng phân bổ riêng cho ${escapeHtml(getDashboardTypeMeta(type).label)}.</div>`;
      }
      const radius = 76;
      const stroke = 22;
      const circumference = 2 * Math.PI * radius;
      let accumulated = 0;
      const segments = activeRows.map(row => {
        const segmentLength = (Number(row.percent || 0) / 100) * circumference;
        const dashOffset = circumference - accumulated;
        accumulated += segmentLength;
        return `<circle class="lotto-dashboard-donut-segment" cx="100" cy="100" r="${radius}" fill="none" stroke="${escapeHtml(row.color)}" stroke-width="${stroke}" stroke-linecap="round" stroke-dasharray="${segmentLength.toFixed(3)} ${(circumference - segmentLength).toFixed(3)}" stroke-dashoffset="${dashOffset.toFixed(3)}"></circle>`;
      }).join("");
      const centerLabel = getDashboardDistributionOptions(type).find(option => option.value === normalizeDashboardDistributionViewMode(mode))?.label || "Tỷ trọng";
      return `
        <div class="lotto-dashboard-donut-layout">
          <div class="lotto-dashboard-donut-wrap">
            <svg class="lotto-dashboard-donut-svg" viewBox="0 0 200 200" aria-hidden="true">
              <circle class="lotto-dashboard-donut-track" cx="100" cy="100" r="${radius}" fill="none" stroke-width="${stroke}"></circle>
              <g class="lotto-dashboard-donut-ring">${segments}</g>
            </svg>
            <div class="lotto-dashboard-donut-center">
              <div class="lotto-dashboard-donut-center-value">100%</div>
              <div class="lotto-dashboard-donut-center-label">${escapeHtml(centerLabel)}</div>
              <div class="lotto-dashboard-donut-center-meta">${escapeHtml(`${formatDashboardInteger(activeRows.length)} nhóm`)}</div>
            </div>
          </div>
          <div class="lotto-dashboard-donut-legend">
            ${rows.map(row => `
              <div class="lotto-dashboard-donut-legend-item">
                <span class="lotto-dashboard-donut-legend-swatch" style="--dashboard-color:${escapeHtml(row.color)}"></span>
                <div class="lotto-dashboard-donut-legend-copy">
                  <div class="lotto-dashboard-donut-legend-label">${escapeHtml(row.label)}</div>
                  <div class="lotto-dashboard-donut-legend-meta">${escapeHtml(row.meta || "")}</div>
                </div>
                <div class="lotto-dashboard-donut-legend-values">
                  <div class="lotto-dashboard-donut-legend-percent">${escapeHtml(formatChartStatsPercent(row.percent))}</div>
                  <div class="lotto-dashboard-donut-legend-count">${escapeHtml(row.countLabel || `${formatDashboardInteger(row.count)}`)}</div>
                </div>
              </div>
            `).join("")}
          </div>
        </div>
      `;
    }

    function renderDashboardActivityStats(buckets, type) {
      const totalDraws = buckets.reduce((sum, bucket) => sum + Number(bucket.drawCount || 0), 0);
      const totalValue = buckets.reduce((sum, bucket) => sum + Number(bucket.value || 0), 0);
      const averagePerDraw = totalDraws > 0 ? totalValue / totalDraws : 0;
      const totalLabel = getDashboardFamily(type) === "threeDigit" ? "Tổng điểm bộ" : "Tổng điểm";
      return `
        <div class="lotto-dashboard-mini-stat">
          <div class="lotto-dashboard-mini-stat-label">Tổng số kỳ</div>
          <div class="lotto-dashboard-mini-stat-value">${escapeHtml(formatDashboardInteger(totalDraws))}</div>
        </div>
        <div class="lotto-dashboard-mini-stat">
          <div class="lotto-dashboard-mini-stat-label">${escapeHtml(totalLabel)}</div>
          <div class="lotto-dashboard-mini-stat-value">${escapeHtml(formatDashboardInteger(Math.round(totalValue)))}</div>
        </div>
        <div class="lotto-dashboard-mini-stat">
          <div class="lotto-dashboard-mini-stat-label">Trung bình mỗi kỳ</div>
          <div class="lotto-dashboard-mini-stat-value">${escapeHtml(formatDashboardNumber(averagePerDraw, 1))}</div>
        </div>
      `;
    }

    function renderDashboardActivityChart(buckets, mode, type) {
      const normalizedMode = normalizeDashboardActivityViewMode(mode);
      const totalDraws = buckets.reduce((sum, bucket) => sum + Number(bucket.drawCount || 0), 0);
      if (!totalDraws) {
        return `<div class="lotto-dashboard-empty-state">Chưa đủ dữ liệu ${escapeHtml(getDashboardTypeMeta(type).label)} để dựng biểu đồ hoạt động theo ${normalizedMode === "day" ? "ngày" : normalizedMode === "week" ? "tuần" : "tháng"}.</div>`;
      }
      const values = buckets.map(item => Number(item.value || 0));
      const targetValue = values.reduce((sum, value) => sum + value, 0) / Math.max(1, values.length);
      const maxValue = Math.max(1, targetValue, ...values);
      const width = 720;
      const height = 310;
      const paddingX = 28;
      const paddingTop = 16;
      const paddingBottom = 42;
      const chartWidth = width - paddingX * 2;
      const chartHeight = height - paddingTop - paddingBottom;
      const points = buckets.map((bucket, index) => ({
        ...bucket,
        x: paddingX + (buckets.length === 1 ? chartWidth / 2 : (chartWidth / Math.max(1, buckets.length - 1)) * index),
        y: paddingTop + chartHeight - ((Number(bucket.value || 0) / maxValue) * chartHeight),
      }));
      const goalY = paddingTop + chartHeight - ((targetValue / maxValue) * chartHeight);
      const linePath = buildDashboardSmoothPath(points);
      const areaPath = buildDashboardAreaPath(points, paddingTop + chartHeight);
      const gridLines = Array.from({ length: 4 }, (_, index) => {
        const ratio = index / 3;
        const y = paddingTop + chartHeight - ratio * chartHeight;
        const value = maxValue * ratio;
        return { y, value };
      }).reverse();
      return `
        <div class="lotto-dashboard-line-chart-shell">
          <div class="lotto-dashboard-line-chart-wrap">
            <svg class="lotto-dashboard-line-chart" viewBox="0 0 ${width} ${height}" aria-hidden="true">
              <defs>
                <linearGradient id="lottoDashboardAreaFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="rgba(109, 92, 255, .24)"></stop>
                  <stop offset="100%" stop-color="rgba(109, 92, 255, 0)"></stop>
                </linearGradient>
              </defs>
              ${gridLines.map(line => `
                <g>
                  <line class="lotto-dashboard-grid-line" x1="${paddingX}" y1="${line.y}" x2="${width - paddingX}" y2="${line.y}"></line>
                  <text class="lotto-dashboard-grid-label" x="${paddingX - 8}" y="${line.y + 4}" text-anchor="end">${escapeHtml(formatDashboardInteger(Math.round(line.value)))}</text>
                </g>
              `).join("")}
              <line class="lotto-dashboard-target-line" x1="${paddingX}" y1="${goalY}" x2="${width - paddingX}" y2="${goalY}"></line>
              <path class="lotto-dashboard-line-area" d="${areaPath}"></path>
              <path class="lotto-dashboard-line-path" d="${linePath}"></path>
              ${points.map(point => `
                <circle
                  class="lotto-dashboard-line-point"
                  cx="${point.x}"
                  cy="${point.y}"
                  r="5"
                  data-dashboard-label="${escapeHtml(point.tooltipLabel)}"
                  data-dashboard-value="${escapeHtml(formatDashboardInteger(Math.round(point.value || 0)))}"
                  data-dashboard-meta="${escapeHtml(`${formatDashboardInteger(point.drawCount)} kỳ • TB ${formatDashboardNumber(point.value / Math.max(1, point.drawCount || 1), 1)}`)}"
                ></circle>
              `).join("")}
              ${points.map(point => `<text class="lotto-dashboard-axis-label" x="${point.x}" y="${height - 10}" text-anchor="middle">${escapeHtml(point.label)}</text>`).join("")}
              <text class="lotto-dashboard-target-text" x="${width - paddingX}" y="${goalY - 8}" text-anchor="end">Mục tiêu</text>
            </svg>
            <div class="lotto-dashboard-line-tooltip" hidden></div>
          </div>
        </div>
      `;
    }

    function renderDashboardActivityTabs() {
      document.querySelectorAll("[data-dashboard-activity-view]").forEach(button => {
        const viewMode = normalizeDashboardActivityViewMode(button.dataset.dashboardActivityView);
        const isActive = viewMode === dashboardActivityViewMode;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
    }

    function renderDashboardDistributionTabs() {
      const host = document.getElementById("lottoDashboardDistributionTabs");
      if (!host) return;
      const options = getDashboardDistributionOptions(dashboardSelectedGame);
      host.innerHTML = options.map(option => {
        const isActive = option.value === dashboardDistributionViewMode;
        return `<button type="button" class="lotto-dashboard-tab${isActive ? " is-active" : ""}" data-dashboard-distribution-view="${escapeHtml(option.value)}" aria-pressed="${isActive ? "true" : "false"}">${escapeHtml(option.label)}</button>`;
      }).join("");
      host.querySelectorAll("[data-dashboard-distribution-view]").forEach(button => {
        button.addEventListener("click", () => {
          const nextView = normalizeDashboardDistributionViewMode(button.dataset.dashboardDistributionView);
          if (nextView === dashboardDistributionViewMode) return;
          dashboardDistributionViewMode = nextView;
          saveDashboardUiState();
          renderDashboardPanel();
        });
      });
    }

    function bindDashboardLineTooltip() {
      const wrap = document.querySelector("#lottoDashboardActivityOut .lotto-dashboard-line-chart-wrap");
      const tooltip = wrap?.querySelector(".lotto-dashboard-line-tooltip");
      if (!wrap || !tooltip) return;
      const hide = () => {
        tooltip.hidden = true;
      };
      wrap.querySelectorAll(".lotto-dashboard-line-point").forEach(point => {
        const show = event => {
          const bounds = wrap.getBoundingClientRect();
          const offsetX = Math.max(14, Math.min(bounds.width - 14, event.clientX - bounds.left));
          const offsetY = Math.max(16, event.clientY - bounds.top - 18);
          tooltip.innerHTML = `
            <div class="lotto-dashboard-line-tooltip-label">${escapeHtml(point.dataset.dashboardLabel || "")}</div>
            <div class="lotto-dashboard-line-tooltip-value">${escapeHtml(point.dataset.dashboardValue || "0")}</div>
            <div class="lotto-dashboard-line-tooltip-meta">${escapeHtml(point.dataset.dashboardMeta || "")}</div>
          `;
          tooltip.style.left = `${offsetX}px`;
          tooltip.style.top = `${offsetY}px`;
          tooltip.hidden = false;
        };
        point.addEventListener("mouseenter", show);
        point.addEventListener("mousemove", show);
        point.addEventListener("mouseleave", hide);
      });
      wrap.addEventListener("mouseleave", hide);
    }

    function renderDashboardPanel() {
      const heroHost = document.getElementById("lottoDashboardHero");
      const quickStatsHost = document.getElementById("lottoDashboardQuickStats");
      const activityStatsHost = document.getElementById("lottoDashboardActivityStats");
      const activityOut = document.getElementById("lottoDashboardActivityOut");
      const distributionOut = document.getElementById("lottoDashboardDistributionOut");
      const updatedAtHost = document.getElementById("lottoDashboardUpdatedAt");
      const statusHost = document.getElementById("lottoDashboardStatus");
      const statusBtn = document.getElementById("lottoDashboardStatusBtn");
      const distributionSubtitleHost = document.getElementById("lottoDashboardDistributionSubtitle");
      const activitySubtitleHost = document.getElementById("lottoDashboardActivitySubtitle");
      if (!heroHost || !quickStatsHost || !activityStatsHost || !activityOut || !distributionOut || !updatedAtHost || !statusHost) return;

      renderDashboardGameSelect();
      renderDashboardActivityTabs();
      renderDashboardDistributionTabs();

      const type = normalizeDashboardGame(dashboardSelectedGame);
      const meta = getDashboardTypeMeta(type);
      const entries = buildDashboardEntries();
      const feed = getLiveHistoryFeed(type);
      const loadedAt = new Date(String(feed?.loadedAt || "").trim());
      updatedAtHost.textContent = `Cập nhật: ${loadedAt instanceof Date && !Number.isNaN(loadedAt.getTime()) ? formatDashboardRelativeTime(loadedAt) : "đang chờ dữ liệu"}`;
      if (distributionSubtitleHost) distributionSubtitleHost.textContent = getDashboardDistributionSubtitle(type, dashboardDistributionViewMode);
      if (activitySubtitleHost) {
        activitySubtitleHost.textContent = getDashboardFamily(type) === "threeDigit"
          ? `Theo dõi biến động tổng điểm bộ 3 số của ${meta.label} theo ngày, tuần hoặc tháng.`
          : `Theo dõi biến động tổng điểm kỳ của ${meta.label} theo ngày, tuần hoặc tháng.`;
      }

      if (dashboardPanelError) {
        statusHost.hidden = false;
        statusHost.className = "lotto-dashboard-status is-warning";
        statusHost.textContent = dashboardPanelError;
      } else {
        statusHost.hidden = true;
        statusHost.className = "lotto-dashboard-status";
        statusHost.textContent = "";
      }

      if (statusBtn) {
        statusBtn.className = "lotto-dashboard-icon-btn is-status";
        if (dashboardPanelLoading) {
          statusBtn.classList.add("is-loading");
          statusBtn.textContent = "…";
          statusBtn.title = `Đang tải dữ liệu ${meta.label}`;
        } else if (dashboardPanelError) {
          statusBtn.classList.add("is-danger");
          statusBtn.textContent = "!";
          statusBtn.title = dashboardPanelError;
        } else if (entries.length) {
          statusBtn.classList.add("is-success");
          statusBtn.textContent = "●";
          statusBtn.title = `${meta.label}: ${formatDashboardInteger(entries.length)} kỳ đã nạp`;
        } else {
          statusBtn.classList.add("is-idle");
          statusBtn.textContent = "○";
          statusBtn.title = `${meta.label}: chưa có dữ liệu`;
        }
      }

      if (dashboardPanelLoading && !entries.length) {
        heroHost.innerHTML = `<div class="lotto-dashboard-empty-card">Đang tải overview riêng của ${escapeHtml(meta.label)}...</div>`;
        quickStatsHost.innerHTML = `<div class="lotto-dashboard-empty-card">Đang tính quick stats riêng của ${escapeHtml(meta.label)}...</div>`;
        activityStatsHost.innerHTML = "";
        activityOut.className = "lotto-dashboard-panel-body lotto-dashboard-panel-body-muted";
        activityOut.innerHTML = "Đang tải biểu đồ hoạt động từ dữ liệu thật...";
        distributionOut.className = "lotto-dashboard-panel-body lotto-dashboard-panel-body-muted";
        distributionOut.innerHTML = "Đang dựng phân bổ riêng cho game đang chọn...";
        return;
      }

      if (!entries.length) {
        heroHost.innerHTML = `<div class="lotto-dashboard-empty-card">Chưa có dữ liệu ${escapeHtml(meta.label)} để dựng dashboard riêng cho game này.</div>`;
        quickStatsHost.innerHTML = `<div class="lotto-dashboard-empty-card">Quick stats sẽ xuất hiện khi feed ${escapeHtml(meta.label)} có dữ liệu thật.</div>`;
        activityStatsHost.innerHTML = "";
        activityOut.className = "lotto-dashboard-panel-body lotto-dashboard-panel-body-muted";
        activityOut.innerHTML = `Hệ thống cần ít nhất một nguồn all_day.csv của ${escapeHtml(meta.label)} để vẽ biểu đồ hoạt động.`;
        distributionOut.className = "lotto-dashboard-panel-body lotto-dashboard-panel-body-muted";
        distributionOut.innerHTML = `Khi có dữ liệu thật của ${escapeHtml(meta.label)}, donut phân bổ sẽ hiển thị ngay tại đây.`;
        return;
      }

      heroHost.innerHTML = renderDashboardHeroCard(type, entries);
      quickStatsHost.innerHTML = renderDashboardQuickStats(type, entries);

      const activityBuckets = getDashboardActivityBuckets(entries, dashboardActivityViewMode);
      activityStatsHost.innerHTML = renderDashboardActivityStats(activityBuckets, type);
      activityOut.className = "lotto-dashboard-panel-body";
      activityOut.innerHTML = renderDashboardActivityChart(activityBuckets, dashboardActivityViewMode, type);

      distributionOut.className = "lotto-dashboard-panel-body";
      distributionOut.innerHTML = renderDashboardDistributionPanel(type, entries, dashboardDistributionViewMode);
      window.setTimeout(bindDashboardLineTooltip, 0);
    }

    async function startDashboardRefresh({ force = false, silent = true } = {}) {
      const refreshToken = ++dashboardPanelRefreshToken;
      const type = normalizeDashboardGame(dashboardSelectedGame);
      dashboardPanelLoading = true;
      dashboardPanelError = "";
      renderDashboardPanel();
      try {
        await fetchLiveHistory(type, "all", { force, silent });
        if (refreshToken !== dashboardPanelRefreshToken) return;
        dashboardPanelLoading = false;
        dashboardPanelError = "";
      } catch (error) {
        if (refreshToken !== dashboardPanelRefreshToken) return;
        dashboardPanelLoading = false;
        dashboardPanelError = `Không tải được dashboard ${getDashboardTypeMeta(type).label}: ${String(error?.message || error || "Lỗi không rõ")}`;
      } finally {
        if (refreshToken !== dashboardPanelRefreshToken) return;
        renderDashboardPanel();
      }
    }

    function renderVipPredictEngineChoice() {
      const select = document.getElementById("vipPdEngine");
      const choiceWrap = document.getElementById("vipPdEngineChoice");
      if (select) select.value = String(vipPredictEngineValue || "both").trim().toLowerCase() || "both";
      if (!choiceWrap) return;
      const selected = String(vipPredictEngineValue || "both").trim().toLowerCase() || "both";
      choiceWrap.querySelectorAll("[data-vip-pd-engine]").forEach(button => {
        const isActive = String(button.dataset.vipPdEngine || "").trim().toLowerCase() === selected;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
    }

    function renderVipPredictRiskModeChoice() {
      const choiceWrap = document.getElementById("vipPdRiskModeChoice");
      if (!choiceWrap) return;
      const selected = normalizePredictRiskMode(vipPredictRiskModeValue);
      choiceWrap.querySelectorAll("[data-vip-pd-risk-mode]").forEach(button => {
        const modeKey = normalizePredictRiskMode(button.dataset.vipPdRiskMode);
        const isActive = modeKey === selected;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
    }

    function maybeAutoSwitchRiskModeForBao(typeKey, playModeValue) {
      const normalizedType = String(typeKey || "").trim().toUpperCase();
      const normalizedPlayMode = String(playModeValue || "").trim().toLowerCase();
      const normalizedEngine = String(predictEngineValue || "both").trim().toLowerCase();
      if (!hasPredictBaoMode(normalizedType) || normalizedPlayMode !== "bao" || normalizedEngine !== "both") {
        return false;
      }
      const currentMode = normalizePredictRiskMode(predictRiskModeValue);
      if (currentMode === "balanced") return false;
      savePredictRiskMode("balanced");
      renderPredictRiskModeChoice();
      const out = document.getElementById("predictOut");
      if (out && (out.classList.contains("muted") || !out.querySelector(".ai-result-shell"))) {
        line(out, "Bao Số đã tự chuyển sang Cân Bằng để giữ nhịp ổn định hơn.", "muted");
      }
      return true;
    }

    function maybeAutoSwitchVipRiskModeForBao(typeKey, playModeValue) {
      const normalizedType = String(typeKey || "").trim().toUpperCase();
      const normalizedPlayMode = String(playModeValue || "").trim().toLowerCase();
      const normalizedEngine = String(vipPredictEngineValue || "both").trim().toLowerCase();
      if (!hasPredictBaoMode(normalizedType) || normalizedPlayMode !== "bao" || normalizedEngine !== "both") {
        return false;
      }
      const currentMode = normalizePredictRiskMode(vipPredictRiskModeValue);
      if (currentMode === "balanced") return false;
      vipPredictRiskModeValue = "balanced";
      saveVipPredictState();
      renderVipPredictRiskModeChoice();
      return true;
    }

    function enforcePredictRiskModeVisibility(isAiPredict) {
      const riskModeBox = document.getElementById("pdRiskModeBox");
      if (!riskModeBox) return;
      const shouldShow = !!isAiPredict && String(predictEngineValue || "both").trim().toLowerCase() === "both";
      riskModeBox.hidden = !shouldShow;
      riskModeBox.style.display = shouldShow ? "grid" : "none";
    }

    function enforceVipPredictRiskModeVisibility(isAiPredict) {
      const riskModeBox = document.getElementById("vipPdRiskModeBox");
      if (!riskModeBox) return;
      const shouldShow = !!isAiPredict && String(vipPredictEngineValue || "both").trim().toLowerCase() === "both";
      riskModeBox.hidden = !shouldShow;
      riskModeBox.style.display = shouldShow ? "grid" : "none";
    }

    function enforcePredictEngineVisibility(isKenoPredict, isAiPredict) {
      const pdEngineBox = document.getElementById("pdEngineBox");
      const pdEngineSelect = document.getElementById("pdEngine");
      const pdEngineShell = document.querySelector('.select-shell[data-select-id="pdEngine"]');
      const pdEngineChoice = document.getElementById("pdEngineChoice");
      if (pdEngineBox) {
        pdEngineBox.style.display = isAiPredict ? "grid" : "none";
        pdEngineBox.classList.toggle("keno-engine-mode", !!isKenoPredict);
      }
      if (pdEngineSelect) {
        pdEngineSelect.hidden = !isAiPredict || !isKenoPredict;
        pdEngineSelect.disabled = !isAiPredict || !isKenoPredict;
        pdEngineSelect.style.display = isAiPredict && isKenoPredict ? "block" : "none";
      }
      if (pdEngineShell) {
        pdEngineShell.hidden = !isAiPredict || !isKenoPredict;
        pdEngineShell.style.display = isAiPredict && isKenoPredict ? "" : "none";
      }
      if (pdEngineChoice) {
        pdEngineChoice.hidden = !isAiPredict || !!isKenoPredict;
        pdEngineChoice.style.display = isAiPredict && !isKenoPredict ? "grid" : "none";
      }
      enforcePredictRiskModeVisibility(isAiPredict);
    }

    function enforceVipPredictEngineVisibility(isKenoPredict, isAiPredict) {
      const vipPdEngineBox = document.getElementById("vipPdEngineBox");
      const vipPdEngineSelect = document.getElementById("vipPdEngine");
      const vipPdEngineChoice = document.getElementById("vipPdEngineChoice");
      if (vipPdEngineBox) vipPdEngineBox.style.display = isAiPredict ? "grid" : "none";
      if (vipPdEngineSelect) {
        vipPdEngineSelect.hidden = !isAiPredict || !isKenoPredict;
        vipPdEngineSelect.disabled = !isAiPredict || !isKenoPredict;
        vipPdEngineSelect.style.display = isAiPredict && isKenoPredict ? "block" : "none";
      }
      if (vipPdEngineChoice) {
        vipPdEngineChoice.hidden = !isAiPredict || !!isKenoPredict;
        vipPdEngineChoice.style.display = isAiPredict && !isKenoPredict ? "grid" : "none";
      }
      enforceVipPredictRiskModeVisibility(isAiPredict);
    }

    function getPredictionHitSlotCount(type, tickets = []) {
      const firstTicketSize = Array.isArray(tickets?.[0]?.main) ? tickets[0].main.length : 0;
      const mainCount = firstTicketSize || Number(TYPES[type]?.mainCount || 0);
      return Math.max(0, mainCount + (TYPES[type]?.hasSpecial ? 1 : 0));
    }

    function formatPredictionPercent(value) {
      return `${Number(value || 0).toFixed(2)}%`;
    }

    function buildPredictionTrend(currentRate, previousRate) {
      const current = Number(currentRate || 0);
      const previous = Number(previousRate || 0);
      const delta = current - previous;
      if (delta > 0.0001) {
        return { direction: "up", icon: "↑", delta };
      }
      if (delta < -0.0001) {
        return { direction: "down", icon: "↓", delta };
      }
      return { direction: "same", icon: "→", delta: 0 };
    }

    function formatPredictionTrendText(trend) {
      if (!trend || typeof trend !== "object") return "";
      if (trend.direction === "same") return "→0.00%";
      return `${trend.icon}${formatPredictionPercent(Math.abs(Number(trend.delta || 0)))}`;
    }

    function formatPredictionTrendHtml(trend) {
      if (!trend || typeof trend !== "object") return "";
      const direction = String(trend.direction || "same");
      return `<span class="prediction-trend ${direction}">${escapeHtml(formatPredictionTrendText(trend))}</span>`;
    }

    function buildPredictionRateBuckets(type, details, tickets) {
      const slotCount = getPredictionHitSlotCount(type, tickets);
      const ticketCount = Array.isArray(details) ? details.length : 0;
      const buckets = [];
      for (let hitCount = 1; hitCount <= slotCount; hitCount++) {
        const matchedCount = (details || []).filter(detail => {
          const totalHits = Number(detail?.mainHits || 0) + (detail?.specialHit ? 1 : 0);
          return totalHits === hitCount;
        }).length;
        buckets.push({
          hitCount,
          count: matchedCount,
          rate: ticketCount ? (matchedCount * 100 / ticketCount) : 0,
        });
      }
      return buckets;
    }

