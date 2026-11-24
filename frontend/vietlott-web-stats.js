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
      const selectedKeys = new Set();
      const ticketKey = ticket => {
        const main = (Array.isArray(ticket?.main) ? ticket.main : [])
          .map(Number)
          .filter(Number.isInteger)
          .sort((left, right) => left - right)
          .join("-");
        const special = Number(ticket?.special);
        return `${main}|${Number.isInteger(special) ? special : ""}`;
      };
      const takeNextUnique = sourceKey => {
        const pool = Array.isArray(ticketPools?.[sourceKey]) ? ticketPools[sourceKey] : [];
        while (indexes[sourceKey] < pool.length) {
          const ticket = pool[indexes[sourceKey]++] || null;
          if (!ticket) continue;
          const key = ticketKey(ticket);
          if (!key || selectedKeys.has(key)) continue;
          selectedKeys.add(key);
          return ticket;
        }
        return null;
      };
      while (mergedTickets.length < bundleCount) {
        let pushed = false;
        for (const sourceKey of [preferred, secondary]) {
          if ((remaining[sourceKey] || 0) <= 0) continue;
          const nextTicket = takeNextUnique(sourceKey);
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
      for (const sourceKey of [preferred, secondary]) {
        while (mergedTickets.length < bundleCount) {
          const nextTicket = takeNextUnique(sourceKey);
          if (!nextTicket) break;
          mergedTickets.push(nextTicket);
          ticketSources.push(sourceKey);
        }
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
      const adaptiveSources = [luanPayload?.adaptiveCoverage, aiPayload?.adaptiveCoverage].filter(Boolean);
      const combinedAdaptiveCoverage = adaptiveSources.length ? {
        version: "adaptive_coverage_v1",
        candidateMethod: "gumbel_top_k_without_replacement",
        candidateCountRequested: adaptiveSources.reduce((total, item) => total + Number(item?.candidateCountRequested || 0), 0),
        candidateCountGenerated: adaptiveSources.reduce((total, item) => total + Number(item?.candidateCountGenerated || 0), 0),
        selectedCount: merged.tickets.length,
        riskMode: String(metaSelection?.riskMode || getResultRiskMode(aiPayload, riskMode)),
        sourceRuns: {
          luan_so: luanPayload?.adaptiveCoverage || null,
          gen_local: aiPayload?.adaptiveCoverage || null,
        },
      } : null;
      const normalizedRankings = normalizePredictionTopRankings(
        type,
        mergeUniquePredictionNumbers(luanPayload?.topRanking, aiPayload?.topRanking, 20),
        mergeUniquePredictionNumbers(luanPayload?.topSpecialRanking, aiPayload?.topSpecialRanking, 55),
        merged.tickets,
      );
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
        adaptiveCoverageVersion: combinedAdaptiveCoverage?.version || "",
        adaptiveCoverage: combinedAdaptiveCoverage,
        topRanking: normalizedRankings.main,
        topSpecialRanking: normalizedRankings.special,
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
      let activeButton = null;
      document.querySelectorAll("[data-predict-mode-tab]").forEach(button => {
        const tabMode = normalizePredictionMode(button.dataset.predictModeTab);
        const isActive = tabMode === predictPageModeValue;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
        if (isActive) activeButton = button;
      });
      const tabBar = activeButton?.closest(".predict-tab-bar");
      if (tabBar && tabBar.scrollWidth > tabBar.clientWidth) {
        window.requestAnimationFrame(() => {
          const centeredLeft = activeButton.offsetLeft - ((tabBar.clientWidth - activeButton.offsetWidth) / 2);
          const maxLeft = Math.max(0, tabBar.scrollWidth - tabBar.clientWidth);
          tabBar.scrollTo({
            left: Math.max(0, Math.min(maxLeft, centeredLeft)),
            behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ? "auto" : "smooth",
          });
        });
      }
      const normalRoot = document.getElementById("predictRootNormal");
      const manualRoot = document.getElementById("predictRootManual");
      const vipRoot = document.getElementById("predictRootVip");
      const statsRoot = document.getElementById("predictRootStats");
      const statsV2Root = document.getElementById("predictRootStatsV2");
      const chartsRoot = document.getElementById("predictRootCharts");
      const dashboardRoot = document.getElementById("predictRootDashboard");
      const analysisRoot = document.getElementById("predictRootAnalysis");
      const effectivenessRoot = document.getElementById("predictRootEffectiveness");
      if (normalRoot) normalRoot.hidden = predictPageModeValue !== PREDICTION_MODE_NORMAL;
      if (manualRoot) manualRoot.hidden = predictPageModeValue !== PREDICTION_MODE_MANUAL;
      if (vipRoot) vipRoot.hidden = predictPageModeValue !== PREDICTION_MODE_VIP;
      if (statsRoot) statsRoot.hidden = predictPageModeValue !== PREDICTION_MODE_STATS;
      if (statsV2Root) statsV2Root.hidden = predictPageModeValue !== PREDICTION_MODE_STATS_V2;
      if (chartsRoot) chartsRoot.hidden = predictPageModeValue !== PREDICTION_MODE_CHARTS;
      if (dashboardRoot) dashboardRoot.hidden = predictPageModeValue !== PREDICTION_MODE_DASHBOARD;
      if (analysisRoot) analysisRoot.hidden = predictPageModeValue !== PREDICTION_MODE_ANALYSIS;
      if (effectivenessRoot) effectivenessRoot.hidden = predictPageModeValue !== PREDICTION_MODE_EFFECTIVENESS;
      window.VietlottEffectiveness?.activate(predictPageModeValue === PREDICTION_MODE_EFFECTIVENESS);
      syncStatsPanelAutoRefreshTimer();
      syncStatsV2AutoRefreshTimer();
    }

    function normalizeManualPredictionType(value) {
      const normalized = String(value || "").trim().toUpperCase();
      return TYPE_KEYS.includes(normalized) ? normalized : "LOTO_5_35";
    }

    function normalizeManualPredictionBundleCount(value) {
      const parsed = Number.parseInt(String(value || "").replace(/\D/g, ""), 10);
      return Number.isInteger(parsed) ? Math.max(1, Math.min(PREDICT_MAX_BUNDLES, parsed)) : 1;
    }

    function createManualPredictionBundle() {
      return { main: [], special: [] };
    }

    function ensureManualPredictionBundles() {
      manualPredictBundleCountValue = normalizeManualPredictionBundleCount(manualPredictBundleCountValue);
      const current = Array.isArray(manualPredictBundles) ? manualPredictBundles : [];
      manualPredictBundles = Array.from({ length: manualPredictBundleCountValue }, (_, index) => {
        const bundle = current[index];
        return {
          main: Array.isArray(bundle?.main) ? bundle.main : [],
          special: Array.isArray(bundle?.special) ? bundle.special : [],
        };
      });
      manualPredictActiveBundleIndex = Math.max(
        0,
        Math.min(manualPredictBundles.length - 1, Number(manualPredictActiveBundleIndex || 0) || 0),
      );
      const pageCount = Math.max(1, Math.ceil(manualPredictBundles.length / MANUAL_PREDICT_BUNDLE_PAGE_SIZE));
      manualPredictBundlePageValue = Math.max(
        0,
        Math.min(pageCount - 1, Number(manualPredictBundlePageValue || 0) || 0),
      );
      const activeBundle = manualPredictBundles[manualPredictActiveBundleIndex] || createManualPredictionBundle();
      manualPredictMainNumbers = activeBundle.main;
      manualPredictSpecialNumbers = activeBundle.special;
      return activeBundle;
    }

    function resetManualPredictionBundles(notice = "") {
      manualPredictBundleCountValue = normalizeManualPredictionBundleCount(manualPredictBundleCountValue);
      manualPredictBundles = Array.from({ length: manualPredictBundleCountValue }, createManualPredictionBundle);
      manualPredictActiveBundleIndex = 0;
      manualPredictBundlePageValue = 0;
      manualPredictEditorOpenValue = false;
      manualPredictNotice = notice;
      clearManualPredictionCalculationLog();
      ensureManualPredictionBundles();
      renderManualPredictionPanel();
    }

    function setManualPredictionBundleCount(value) {
      const nextCount = normalizeManualPredictionBundleCount(value);
      ensureManualPredictionBundles();
      manualPredictBundleCountValue = nextCount;
      ensureManualPredictionBundles();
      manualPredictNotice = "";
      renderManualPredictionPanel();
    }

    function changeManualPredictionBundlePage(offset) {
      ensureManualPredictionBundles();
      const pageCount = Math.max(1, Math.ceil(manualPredictBundles.length / MANUAL_PREDICT_BUNDLE_PAGE_SIZE));
      const nextPage = Math.max(
        0,
        Math.min(pageCount - 1, manualPredictBundlePageValue + Number(offset || 0)),
      );
      if (nextPage === manualPredictBundlePageValue) return;
      manualPredictBundlePageValue = nextPage;
      manualPredictEditorOpenValue = false;
      manualPredictNotice = "";
      renderManualPredictionPanel();
    }

    async function saveManualPrediction() {
      const meta = getManualPredictionMeta();
      ensureManualPredictionBundles();
      const completedBundles = manualPredictBundles.filter(bundle => isManualPredictionBundleComplete(bundle, meta));
      if (!completedBundles.length) {
        manualPredictNotice = "Hãy hoàn thành ít nhất 1 bộ trước khi lưu.";
        renderManualPredictionPanel();
        return;
      }
      const predictionDataset = buildPredictionResultDataset(meta.type);
      const predictedKy = getNextPredictionKy(meta.type, predictionDataset);
      if (!predictedKy) {
        manualPredictNotice = "Chưa xác định được kỳ quay tiếp theo để lưu.";
        renderManualPredictionPanel();
        return;
      }
      const saveButton = document.getElementById("manualPredictSaveBtn");
      if (saveButton) {
        saveButton.disabled = true;
        saveButton.textContent = "Đang lưu...";
      }
      const playMode = meta.isBao ? "bao" : "normal";
      const tickets = completedBundles.map(bundle => ({
        main: [...bundle.main],
        special: meta.hasManualSpecial && Number.isInteger(bundle.special[0]) ? bundle.special[0] : null,
        playMode,
        baoLevel: meta.isBao ? meta.baoLevel : null,
      }));
      try {
        upsertPredictionLog(meta.type, {
          id: `manual_${meta.type}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
          createdAt: getSyncedIsoString(),
          predictedKy,
          predictionMode: PREDICTION_MODE_MANUAL,
          strategyKey: "manual_selection",
          strategyLabel: "Dự đoán thủ công",
          modelKey: "manual_selection",
          modelLabel: "Người chơi tự chọn",
          engineKey: "manual",
          engineLabel: "Thủ công",
          playMode,
          baoLevel: meta.isBao ? meta.baoLevel : null,
          pickSize: meta.isKeno ? meta.required : 0,
          bundleCount: tickets.length,
          tickets,
          topMainRanking: [...new Set(tickets.flatMap(ticket => ticket.main))],
          topSpecialRanking: [...new Set(tickets.map(ticket => ticket.special).filter(Number.isInteger))],
          triggerMode: "manual_save",
        });
        const saved = await saveStore({ reason: "manual_prediction_save" });
        if (saved === false) throw new Error("Không thể đồng bộ dữ liệu");
        manualPredictNotice = `Đã lưu ${tickets.length} bộ hoàn chỉnh vào lịch sử.`;
      } catch (error) {
        manualPredictNotice = `Lưu thất bại: ${error?.message || error}`;
      } finally {
        renderManualPredictionPanel();
      }
    }

    function activateManualPredictionBundle(index) {
      ensureManualPredictionBundles();
      manualPredictActiveBundleIndex = Math.max(
        0,
        Math.min(manualPredictBundles.length - 1, Number(index || 0) || 0),
      );
      manualPredictBundlePageValue = Math.floor(manualPredictActiveBundleIndex / MANUAL_PREDICT_BUNDLE_PAGE_SIZE);
      manualPredictEditorOpenValue = true;
      manualPredictNotice = "";
      clearManualPredictionCalculationLog();
      ensureManualPredictionBundles();
      renderManualPredictionPanel();
    }

    // Rút gọn một giá trị về miền 1..maxNumber theo quy tắc thương + số dư.
    function reduceToRange(value, maxNumber, detailLog = null) {
      if (!Number.isInteger(value) || value < 0) {
        throw new Error("Giá trị cần rút gọn phải là số nguyên không âm.");
      }
      if (!Number.isInteger(maxNumber) || maxNumber <= 0) {
        throw new Error("maxNumber phải là số nguyên lớn hơn 0.");
      }
      if (maxNumber === 1) {
        if (Array.isArray(detailLog) && value !== 1) detailLog.push(`${value} → miền chỉ có số 1`);
        return 1;
      }

      let result = value;
      while (result > maxNumber) {
        const quotient = Math.floor(result / maxNumber);
        const remainder = result % maxNumber;
        const nextValue = quotient + remainder;
        if (Array.isArray(detailLog)) {
          detailLog.push(`${result} / ${maxNumber} → thương ${quotient}, dư ${remainder}`);
          detailLog.push(`${quotient} + ${remainder} = ${nextValue}`);
        }
        result = nextValue;
      }

      if (result === 0) {
        result = maxNumber;
        if (Array.isArray(detailLog)) detailLog.push(`Kết quả 0 → đổi thành ${maxNumber}`);
      }
      return result;
    }

    // Nếu số đã có, tăng dần và quay về minNumber khi vượt giới hạn.
    function resolveDuplicate(value, usedNumbers, maxNumber, minNumber = 1, detailLog = null) {
      if (!(usedNumbers instanceof Set)) {
        throw new Error("usedNumbers phải là một Set.");
      }
      if (!Number.isInteger(minNumber) || !Number.isInteger(maxNumber) || minNumber > maxNumber) {
        throw new Error("Khoảng số không hợp lệ.");
      }

      const rangeSize = maxNumber - minNumber + 1;
      let result = value;
      let checkedCount = 0;
      while (usedNumbers.has(result)) {
        const duplicatedValue = result;
        result += 1;
        const didWrap = result > maxNumber;
        if (didWrap) result = minNumber;
        if (Array.isArray(detailLog)) {
          detailLog.push(
            `${duplicatedValue} bị trùng → ${didWrap ? "quay vòng" : "tăng"} thành ${result}`,
          );
        }
        checkedCount += 1;
        if (checkedCount >= rangeSize) {
          throw new Error("Không còn số hợp lệ chưa được sử dụng.");
        }
      }
      return result;
    }

    // Sinh số theo đúng thứ tự vị trí; không tự động sắp xếp kết quả.
    function generateNumbers(timeValue, numberCount, maxNumber, minNumber = 1, detailLog = null) {
      if (!Number.isInteger(timeValue) || timeValue < 0) {
        throw new Error("timeValue phải là số nguyên không âm.");
      }
      if (!Number.isInteger(numberCount) || numberCount <= 0) {
        throw new Error("numberCount phải là số nguyên lớn hơn 0.");
      }
      if (!Number.isInteger(maxNumber) || maxNumber <= 0) {
        throw new Error("maxNumber phải là số nguyên lớn hơn 0.");
      }
      if (!Number.isInteger(minNumber) || minNumber < 0 || minNumber > maxNumber) {
        throw new Error("minNumber không hợp lệ.");
      }

      const rangeSize = maxNumber - minNumber + 1;
      if (numberCount > rangeSize) {
        throw new Error("Số lượng cần tạo không được lớn hơn giới hạn số.");
      }

      const effectiveTimeValue = timeValue === 0 ? maxNumber : timeValue;
      const numbers = [];
      const usedNumbers = new Set();
      for (let i = 1; i <= numberCount; i += 1) {
        const positionLog = [];
        const rawValue = effectiveTimeValue * i;
        positionLog.push(`Số thứ ${i}:`);
        if (timeValue === 0) {
          positionLog.push(`timeValue = 00 → dùng ${maxNumber}`);
        }
        positionLog.push(`${effectiveTimeValue} × ${i} = ${rawValue}`);

        const reducedValue = reduceToRange(rawValue, rangeSize, positionLog);
        let result = minNumber === 1 ? reducedValue : minNumber + reducedValue - 1;
        if (minNumber !== 1) {
          positionLog.push(`Quy đổi về ${minNumber}–${maxNumber}: ${result}`);
        }
        result = resolveDuplicate(result, usedNumbers, maxNumber, minNumber, positionLog);
        positionLog.push(`Kết quả: ${result}`);
        if (Array.isArray(detailLog)) {
          detailLog.push(...positionLog, "");
        }
        numbers.push(result);
        usedNumbers.add(result);
      }
      return numbers;
    }

    function getManualPredictionRealtimeNow() {
      return globalThis.performance?.now?.() ?? Date.now();
    }

    function formatManualPredictionRealtimeCounter(nowValue = getManualPredictionRealtimeNow()) {
      const elapsedCentiseconds = Math.max(
        0,
        Math.floor((nowValue - manualPredictRealtimeCounterStartedAt) / 10),
      );
      const minutes = Math.floor(elapsedCentiseconds / 6000) % 100;
      const seconds = Math.floor(elapsedCentiseconds / 100) % 60;
      const centiseconds = elapsedCentiseconds % 100;
      return [minutes, seconds, centiseconds]
        .map(value => String(value).padStart(2, "0"))
        .join(":");
    }

    function updateManualPredictionRealtimeCounter() {
      const counter = document.getElementById("manualPredictRealtimeCounter");
      if (counter) counter.textContent = formatManualPredictionRealtimeCounter();
    }

    function ensureManualPredictionRealtimeCounter() {
      updateManualPredictionRealtimeCounter();
      if (manualPredictRealtimeCounterTimer !== null) return;
      manualPredictRealtimeCounterTimer = window.setInterval(
        updateManualPredictionRealtimeCounter,
        10,
      );
    }

    function captureManualPredictionTimeValue() {
      const displayedValue = String(
        document.getElementById("manualPredictRealtimeCounter")?.textContent || "",
      );
      const match = displayedValue.match(/(\d{2})\s*$/);
      if (match) return Number(match[1]);
      const elapsedCentiseconds = Math.max(
        0,
        Math.floor((getManualPredictionRealtimeNow() - manualPredictRealtimeCounterStartedAt) / 10),
      );
      return elapsedCentiseconds % 100;
    }

    function clearManualPredictionCalculationLog() {
      const log = document.getElementById("manualPredictRandomLog");
      const content = document.getElementById("manualPredictRandomLogContent");
      if (log) {
        log.hidden = true;
        log.open = false;
      }
      if (content) content.textContent = "";
    }

    function showManualPredictionCalculationLog(timeValue, meta, mainLog, specialLog = []) {
      const log = document.getElementById("manualPredictRandomLog");
      const content = document.getElementById("manualPredictRandomLogContent");
      if (!log || !content) return;
      const sections = [
        `timeValue = ${String(timeValue).padStart(2, "0")} (đã chụp cố định)`,
        `SỐ CHÍNH · ${meta.required} số · phạm vi ${meta.min}–${meta.max}`,
        ...mainLog,
      ];
      if (meta.hasManualSpecial) {
        sections.push(
          `SỐ ĐẶC BIỆT · 1 số · phạm vi ${meta.specialMin}–${meta.specialMax}`,
          ...specialLog,
        );
      }
      content.textContent = sections.join("\n").trim();
      log.hidden = false;
      log.open = false;
    }

    function sampleManualPredictionNumbers(minValue, maxValue, count, useSecureRandom = false, excludedValues = []) {
      const excluded = new Set(Array.isArray(excludedValues) ? excludedValues.map(Number) : []);
      const pool = Array.from(
        { length: Math.max(0, maxValue - minValue + 1) },
        (_, index) => minValue + index,
      ).filter(value => !excluded.has(value));
      const randomIndex = upperBound => {
        if (useSecureRandom && globalThis.crypto?.getRandomValues) {
          const value = new Uint32Array(1);
          globalThis.crypto.getRandomValues(value);
          return value[0] % upperBound;
        }
        return Math.floor(Math.random() * upperBound);
      };
      for (let index = pool.length - 1; index > 0; index -= 1) {
        const swapIndex = randomIndex(index + 1);
        [pool[index], pool[swapIndex]] = [pool[swapIndex], pool[index]];
      }
      return pool.slice(0, Math.max(0, count)).sort((a, b) => a - b);
    }

    function randomizeManualPredictionBundle(variant = "fortune") {
      const meta = getManualPredictionMeta();
      const activeBundle = ensureManualPredictionBundles();
      if (variant === "fortune") {
        const timeValue = captureManualPredictionTimeValue();
        const mainLog = [];
        const specialLog = [];
        activeBundle.main = generateNumbers(
          timeValue,
          meta.required,
          meta.max,
          meta.min,
          mainLog,
        );
        if (meta.hasManualSpecial) {
          activeBundle.special = generateNumbers(
            timeValue,
            1,
            meta.specialMax,
            meta.specialMin,
            specialLog,
          );
          if (meta.specialExcludesMain) {
            activeBundle.special[0] = resolveDuplicate(
              activeBundle.special[0],
              new Set(activeBundle.main),
              meta.specialMax,
              meta.specialMin,
              specialLog,
            );
            specialLog.push(`Kết quả sau khi loại trùng số chính: ${activeBundle.special[0]}`, "");
          }
        } else {
          activeBundle.special = [];
        }
        showManualPredictionCalculationLog(timeValue, meta, mainLog, specialLog);
        manualPredictNotice = `Đã tạo Ngẫu nhiên 1 từ timeValue ${String(timeValue).padStart(2, "0")}.`;
      } else {
        activeBundle.main = sampleManualPredictionNumbers(meta.min, meta.max, meta.required, true);
        if (meta.hasManualSpecial) {
          activeBundle.special = sampleManualPredictionNumbers(
            meta.specialMin,
            meta.specialMax,
            1,
            true,
            meta.specialExcludesMain ? activeBundle.main : [],
          );
        } else {
          activeBundle.special = [];
        }
        clearManualPredictionCalculationLog();
        manualPredictNotice = "Đã tạo phương án Ngẫu nhiên 2; bạn có thể chỉnh lại từng số.";
      }
      ensureManualPredictionBundles();
      renderManualPredictionPanel();
    }

    function getManualPredictionMeta(typeValue = manualPredictTypeValue) {
      const type = normalizeManualPredictionType(typeValue);
      const source = TYPES[type] || TYPES.LOTO_5_35;
      const isKeno = type === "KENO";
      const isThreeDigit = Boolean(source.threeDigit);
      const baoLevels = getPredictBaoLevels(type);
      const supportsBao = baoLevels.length > 0;
      const isBao = supportsBao && String(manualPredictPlayModeValue || "").trim().toLowerCase() === "bao";
      const selectedBaoLevel = Number(manualPredictBaoLevelValue || 0);
      const baoLevel = isBao
        ? (baoLevels.includes(selectedBaoLevel) ? selectedBaoLevel : Number(baoLevels[0] || source.mainCount || 1))
        : 0;
      if (!supportsBao) manualPredictPlayModeValue = "normal";
      if (isBao) manualPredictBaoLevelValue = String(baoLevel);
      return {
        type,
        label: String(source.label || type).replaceAll("_", " "),
        min: Number(source.mainMin || 0),
        max: Number(source.mainMax || 0),
        required: isBao
          ? baoLevel
          : isKeno
            ? Math.max(1, Math.min(10, Number(manualPredictKenoLevelValue || 5) || 5))
            : Math.max(1, Number(source.mainCount || 1)),
        isKeno,
        isThreeDigit,
        supportsBao,
        isBao,
        baoLevels,
        baoLevel,
        hasManualSpecial: Boolean(source.hasSpecial),
        specialMin: Number(source.specialMin || 0),
        specialMax: Number(source.specialMax || 0),
        specialExcludesMain: type === "LOTO_6_55",
      };
    }

    function formatManualPredictionNumber(value, isThreeDigit = false) {
      return String(Math.max(0, Number(value) || 0)).padStart(isThreeDigit ? 3 : 2, "0");
    }

    function getManualPredictionVisibleNumbers(meta) {
      if (meta.isThreeDigit) {
        const page = Math.max(0, Math.min(9, Number(manualPredict3dPageValue || 0) || 0));
        return Array.from({ length: 100 }, (_, index) => (page * 100) + index);
      }
      return Array.from({ length: Math.max(0, meta.max - meta.min + 1) }, (_, index) => meta.min + index);
    }

    function renderManualPredictionNumberButtons(values, selectedValues, options = {}) {
      const selected = new Set(Array.isArray(selectedValues) ? selectedValues.map(Number) : []);
      const disabled = new Set(Array.isArray(options.disabledValues) ? options.disabledValues.map(Number) : []);
      const isThreeDigit = Boolean(options.isThreeDigit);
      const kindLabel = options.kind === "special" ? "số đặc biệt" : "số";
      return values.map(value => {
        const isSelected = selected.has(Number(value));
        const isDisabled = disabled.has(Number(value)) && !isSelected;
        const label = formatManualPredictionNumber(value, isThreeDigit);
        return `
          <button
            type="button"
            class="manual-predict-number${isSelected ? " is-selected" : ""}${isDisabled ? " is-disabled" : ""}"
            data-manual-predict-number="${Number(value)}"
            aria-pressed="${isSelected ? "true" : "false"}"
            ${isDisabled ? "disabled" : ""}
            aria-label="${isSelected ? "Bỏ chọn" : "Chọn"} ${kindLabel} ${label}"
          >${label}</button>
        `;
      }).join("");
    }

    function toggleManualPredictionNumber(kind, rawValue) {
      ensureManualPredictionBundles();
      const meta = getManualPredictionMeta();
      const value = Number(rawValue);
      const isSpecial = kind === "special";
      if (!Number.isInteger(value)) return;
      if (isSpecial && (!meta.hasManualSpecial || value < meta.specialMin || value > meta.specialMax)) return;
      if (!isSpecial && (value < meta.min || value > meta.max)) return;
      if (isSpecial && meta.specialExcludesMain && manualPredictMainNumbers.includes(value)) {
        manualPredictNotice = "Số đặc biệt của Power 6/55 không được trùng số chính.";
        renderManualPredictionPanel();
        return;
      }

      const selected = isSpecial ? manualPredictSpecialNumbers : manualPredictMainNumbers;
      const limit = isSpecial ? 1 : meta.required;
      const existingIndex = selected.indexOf(value);
      if (existingIndex >= 0) {
        selected.splice(existingIndex, 1);
        manualPredictNotice = "";
      } else if (isSpecial && limit === 1) {
        selected.splice(0, selected.length, value);
        manualPredictNotice = "";
      } else if (selected.length >= limit) {
        manualPredictNotice = `Đã chọn đủ ${limit} số. Bỏ một số trước khi chọn số khác.`;
      } else {
        selected.push(value);
        if (!isSpecial && meta.specialExcludesMain && manualPredictSpecialNumbers.includes(value)) {
          manualPredictSpecialNumbers.splice(manualPredictSpecialNumbers.indexOf(value), 1);
        }
        manualPredictNotice = "";
      }
      clearManualPredictionCalculationLog();
      renderManualPredictionPanel();
    }

    function isManualPredictionBundleComplete(bundle, meta) {
      const mainCount = Array.isArray(bundle?.main) ? bundle.main.length : 0;
      const specialCount = Array.isArray(bundle?.special) ? bundle.special.length : 0;
      return mainCount === meta.required && (!meta.hasManualSpecial || specialCount === 1);
    }

    function renderManualPredictionPanel() {
      const root = document.getElementById("predictRootManual");
      if (!root) return;
      ensureManualPredictionRealtimeCounter();
      manualPredictTypeValue = normalizeManualPredictionType(manualPredictTypeValue);
      const meta = getManualPredictionMeta();
      ensureManualPredictionBundles();
      manualPredictBundles.forEach(bundle => {
        bundle.main = bundle.main
          .map(Number)
          .filter(value => Number.isInteger(value) && value >= meta.min && value <= meta.max)
          .slice(0, meta.required);
        bundle.special = meta.hasManualSpecial
          ? bundle.special
              .map(Number)
              .filter(value => Number.isInteger(value) && value >= meta.specialMin && value <= meta.specialMax)
              .filter(value => !meta.specialExcludesMain || !bundle.main.includes(value))
              .slice(0, 1)
          : [];
      });
      const activeBundle = manualPredictBundles[manualPredictActiveBundleIndex] || createManualPredictionBundle();
      manualPredictMainNumbers = activeBundle.main;
      manualPredictSpecialNumbers = activeBundle.special;

      const typeSelect = document.getElementById("manualPredictTypeSelect");
      if (typeSelect) {
        typeSelect.value = meta.type;
        if (typeof typeSelect.__syncCustomSelect === "function") typeSelect.__syncCustomSelect();
      }
      const playModeControl = document.getElementById("manualPredictPlayModeControl");
      const playModeSelect = document.getElementById("manualPredictPlayMode");
      if (playModeControl) playModeControl.hidden = !meta.supportsBao;
      if (playModeSelect) {
        playModeSelect.value = meta.isBao ? "bao" : "normal";
        if (typeof playModeSelect.__syncCustomSelect === "function") playModeSelect.__syncCustomSelect();
      }
      const baoLevelControl = document.getElementById("manualPredictBaoLevelControl");
      const baoLevelSelect = document.getElementById("manualPredictBaoLevel");
      if (baoLevelControl) baoLevelControl.hidden = !meta.isBao;
      if (baoLevelSelect) {
        baoLevelSelect.innerHTML = meta.baoLevels.map(level => `<option value="${level}">Bao ${level}</option>`).join("");
        baoLevelSelect.value = meta.isBao ? String(meta.baoLevel) : "";
        if (typeof baoLevelSelect.__syncCustomSelect === "function") baoLevelSelect.__syncCustomSelect();
      }
      const kenoControl = document.getElementById("manualPredictKenoLevelControl");
      const kenoLevel = document.getElementById("manualPredictKenoLevel");
      if (kenoControl) kenoControl.hidden = !meta.isKeno;
      if (kenoLevel) {
        kenoLevel.value = String(meta.required);
        if (typeof kenoLevel.__syncCustomSelect === "function") kenoLevel.__syncCustomSelect();
      }
      const pageControl = document.getElementById("manualPredict3dPageControl");
      const pageSelect = document.getElementById("manualPredict3dPage");
      if (pageControl) pageControl.hidden = !meta.isThreeDigit;
      if (pageSelect) {
        pageSelect.value = String(Math.max(0, Math.min(9, Number(manualPredict3dPageValue || 0) || 0)));
        if (typeof pageSelect.__syncCustomSelect === "function") pageSelect.__syncCustomSelect();
      }
      const bundleCountInput = document.getElementById("manualPredictBundleCount");
      if (bundleCountInput && document.activeElement !== bundleCountInput) {
        bundleCountInput.value = String(manualPredictBundleCountValue);
      }
      const toolbar = document.querySelector("#predictRootManual .manual-predict-toolbar");
      if (toolbar) {
        const toolbarColumnCount = 3
          + Number(meta.supportsBao)
          + Number(meta.isBao)
          + Number(meta.isKeno)
          + Number(meta.isThreeDigit);
        toolbar.style.setProperty("--manual-toolbar-columns", String(toolbarColumnCount));
      }

      const numberGrid = document.getElementById("manualPredictNumberGrid");
      if (numberGrid) {
        const typeGridClass = ` is-${meta.type.toLowerCase().replaceAll("_", "-")}`;
        numberGrid.className = `manual-predict-number-grid${typeGridClass}${meta.isKeno ? " is-keno" : ""}${meta.isThreeDigit ? " is-three-digit" : ""}`;
        numberGrid.innerHTML = renderManualPredictionNumberButtons(
          getManualPredictionVisibleNumbers(meta),
          manualPredictMainNumbers,
          { isThreeDigit: meta.isThreeDigit },
        );
      }

      const specialSection = document.getElementById("manualPredictSpecialSection");
      const specialGrid = document.getElementById("manualPredictSpecialGrid");
      if (specialSection) specialSection.hidden = !meta.hasManualSpecial;
      if (specialGrid) {
        specialGrid.className = `manual-predict-number-grid is-special is-${meta.type.toLowerCase().replaceAll("_", "-")}${meta.specialMax > 12 ? " is-wide" : ""}`;
        specialGrid.innerHTML = meta.hasManualSpecial
          ? renderManualPredictionNumberButtons(
              Array.from({ length: Math.max(0, meta.specialMax - meta.specialMin + 1) }, (_, index) => meta.specialMin + index),
              manualPredictSpecialNumbers,
              {
                kind: "special",
                disabledValues: meta.specialExcludesMain ? manualPredictMainNumbers : [],
              },
            )
          : "";
      }

      const mainComplete = manualPredictMainNumbers.length === meta.required;
      const specialComplete = !meta.hasManualSpecial || manualPredictSpecialNumbers.length === 1;
      const isComplete = mainComplete && specialComplete;
      const readyBundleCount = manualPredictBundles.filter(bundle => isManualPredictionBundleComplete(bundle, meta)).length;
      const remaining = Math.max(0, meta.required - manualPredictMainNumbers.length);
      const activeBundleNumber = manualPredictActiveBundleIndex + 1;
      const defaultStatus = isComplete
        ? `Bộ ${String(activeBundleNumber).padStart(2, "0")} đã đủ và sẵn sàng.`
        : remaining > 0
          ? `Chọn thêm ${remaining} số chính${meta.hasManualSpecial && !specialComplete ? " và 1 số đặc biệt" : ""}.`
          : "Chọn thêm 1 số đặc biệt.";
      const selectedMainHtml = manualPredictMainNumbers
        .map(value => `<span class="manual-predict-selected-ball">${formatManualPredictionNumber(value, meta.isThreeDigit)}</span>`)
        .join("");
      const selectedSpecialHtml = manualPredictSpecialNumbers.length
        ? `<span class="manual-predict-selected-ball is-special" title="Số đặc biệt ${formatManualPredictionNumber(manualPredictSpecialNumbers[0])}" aria-label="Số đặc biệt ${formatManualPredictionNumber(manualPredictSpecialNumbers[0])}">${formatManualPredictionNumber(manualPredictSpecialNumbers[0])}</span>`
        : "";
      const selectedHtml = selectedMainHtml || selectedSpecialHtml
        ? `${selectedMainHtml}${selectedSpecialHtml}`
        : '<span class="manual-predict-empty">Chưa chọn số</span>';

      const setText = (id, value) => {
        const host = document.getElementById(id);
        if (host) host.textContent = value;
      };
      const modeLabel = meta.isBao ? `Bao ${meta.baoLevel}` : meta.isKeno ? `Bậc ${meta.required}` : "Vé thường";
      const specialRangeLabel = `${formatManualPredictionNumber(meta.specialMin)}–${formatManualPredictionNumber(meta.specialMax)}`;
      setText("manualPredictBoardTitle", `${meta.label} • ${modeLabel}`);
      setText("manualPredictSummaryType", `${meta.label} • ${modeLabel}`);
      setText("manualPredictMainCount", `${manualPredictMainNumbers.length} / ${meta.required}`);
      setText("manualPredictSpecialCount", `${manualPredictSpecialNumbers.length} / 1`);
      setText("manualPredictSpecialTitle", `Chọn 1 số từ ${specialRangeLabel}`);
      setText(
        "manualPredictActiveBundleLabel",
        manualPredictEditorOpenValue
          ? `Bộ ${String(activeBundleNumber).padStart(2, "0")} đang chọn`
          : "Chọn bộ",
      );
      setText(
        "manualPredictHint",
        meta.isBao
          ? `Bao ${meta.baoLevel}: mỗi bộ chọn đúng ${meta.required} số chính${meta.hasManualSpecial ? " và 1 số đặc biệt" : ""}.`
          : meta.isThreeDigit
            ? `Mỗi bộ chọn ${meta.required} bộ 3 chữ số. Dùng mục Nhóm số để chuyển giữa 000–999.`
            : meta.isKeno
              ? `Mỗi bộ chọn đúng ${meta.required} số cho Keno bậc ${meta.required}.`
              : `Mỗi bộ chọn đủ ${meta.required} số chính${meta.hasManualSpecial ? " và 1 số đặc biệt" : ""}.`,
      );
      const bundleTabs = document.getElementById("manualPredictBundleTabs");
      const bundlePageCount = Math.max(1, Math.ceil(manualPredictBundles.length / MANUAL_PREDICT_BUNDLE_PAGE_SIZE));
      manualPredictBundlePageValue = Math.max(0, Math.min(bundlePageCount - 1, manualPredictBundlePageValue));
      const bundlePageStart = manualPredictBundlePageValue * MANUAL_PREDICT_BUNDLE_PAGE_SIZE;
      const bundlePageEnd = Math.min(bundlePageStart + MANUAL_PREDICT_BUNDLE_PAGE_SIZE, manualPredictBundles.length);
      const visibleBundleCount = Math.max(1, bundlePageEnd - bundlePageStart);
      const workspace = document.querySelector("#predictRootManual .manual-predict-workspace");
      if (workspace) {
        const workspaceMinHeight = Math.max(214, Math.min(554, 124 + visibleBundleCount * 43));
        workspace.style.setProperty("--manual-workspace-min-height", `${workspaceMinHeight}px`);
      }
      if (bundleTabs) {
        bundleTabs.innerHTML = manualPredictBundles.slice(bundlePageStart, bundlePageEnd).map((bundle, offset) => {
          const index = bundlePageStart + offset;
          const isActive = manualPredictEditorOpenValue && index === manualPredictActiveBundleIndex;
          const isReady = isManualPredictionBundleComplete(bundle, meta);
          const hasSelection = bundle.main.length > 0 || bundle.special.length > 0;
          const bundleLabel = `Bộ ${String(index + 1).padStart(2, "0")}`;
          const preview = bundle.main.length
            ? bundle.main.slice(0, 5).map(value => formatManualPredictionNumber(value, meta.isThreeDigit)).join(" · ")
            : "Chưa chọn số";
          const countLabel = `${bundle.main.length}/${meta.required}${meta.hasManualSpecial ? ` · ĐB ${bundle.special.length}/1` : ""}`;
          return `
            <button
              type="button"
              class="manual-predict-bundle-tab${isActive ? " is-active" : ""}${isReady ? " is-ready" : ""}${hasSelection && !isReady ? " has-selection" : ""}"
              data-manual-predict-bundle="${index}"
              role="tab"
              aria-selected="${isActive ? "true" : "false"}"
              aria-label="${bundleLabel}${isReady ? ", đã đủ số" : ", chưa đủ số"}"
            >
              <span class="manual-predict-bundle-identity"><strong>${bundleLabel}</strong><small>${countLabel}</small></span>
              <span class="manual-predict-bundle-preview">${preview}</span>
              <i aria-hidden="true"></i>
            </button>
          `;
        }).join("");
      }
      setText("manualPredictBundleRange", `${bundlePageStart + 1}–${bundlePageEnd}`);
      setText("manualPredictBundleTotal", `${manualPredictBundleCountValue} bộ`);
      const bundlePrev = document.getElementById("manualPredictBundlePrev");
      const bundleNext = document.getElementById("manualPredictBundleNext");
      if (bundlePrev) bundlePrev.disabled = manualPredictBundlePageValue === 0;
      if (bundleNext) bundleNext.disabled = manualPredictBundlePageValue >= bundlePageCount - 1;
      const editorEmpty = document.getElementById("manualPredictEditorEmpty");
      const editorContent = document.getElementById("manualPredictEditorContent");
      if (editorEmpty) editorEmpty.hidden = manualPredictEditorOpenValue;
      if (editorContent) editorContent.hidden = !manualPredictEditorOpenValue;
      const selectedHost = document.getElementById("manualPredictSelectedNumbers");
      if (selectedHost) selectedHost.innerHTML = selectedHtml;
      const summaryHost = document.querySelector("#predictRootManual .manual-predict-summary");
      if (summaryHost) summaryHost.classList.toggle("is-three-digit", meta.isThreeDigit);
      const status = document.getElementById("manualPredictStatus");
      if (status) {
        const isSavedNotice = /^(Đã lưu |Đã tạo )/.test(String(manualPredictNotice || ""));
        status.textContent = manualPredictNotice || defaultStatus;
        status.classList.toggle("is-ready", isComplete && (!manualPredictNotice || isSavedNotice));
        status.classList.toggle("is-warning", Boolean(manualPredictNotice) && !isSavedNotice);
      }
      const readyBadge = document.getElementById("manualPredictReadyBadge");
      if (readyBadge) {
        readyBadge.textContent = manualPredictBundleCountValue === 1
          ? (isComplete ? "Đã đủ số" : "Chưa đủ số")
          : `${readyBundleCount} / ${manualPredictBundleCountValue} bộ đã đủ`;
        readyBadge.classList.toggle("is-ready", readyBundleCount === manualPredictBundleCountValue);
      }
      const saveButton = document.getElementById("manualPredictSaveBtn");
      if (saveButton) {
        saveButton.disabled = readyBundleCount === 0;
        saveButton.textContent = "Lưu";
        saveButton.title = readyBundleCount
          ? `Lưu ${readyBundleCount} bộ hoàn chỉnh`
          : "Cần ít nhất 1 bộ hoàn chỉnh";
      }
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
        .filter(entry =>
          getPredictionEntryMode(entry) === PREDICTION_MODE_STATS &&
          Array.isArray(entry?.tickets) &&
          entry.tickets.length
        );
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
      const ordered = [];
      const seen = new Set();
      const limit = getStatsPredictionMainLimit(type);
      const sources = [mostItems, overdueItems, mostItems];
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
        .filter(entry =>
          getPredictionEntryMode(entry) === PREDICTION_MODE_STATS &&
          Array.isArray(entry?.tickets) &&
          entry.tickets.length
        );
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
          getPredictionEntryMode(entry) === PREDICTION_MODE_STATS &&
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
          getPredictionEntryMode(entry) === PREDICTION_MODE_STATS &&
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

    function buildStatsNeutralPredictionComparisonContext(label = "kỳ gần nhất") {
      return {
        entry: null,
        isLatestEntry: false,
        actualSet: new Set(),
        actualSpecialSet: new Set(),
        label,
      };
    }

    function getStatsPredictionComparisonContext(type, latestEntry = null, latestActualSet = null, latestActualSpecialSet = null, options = {}) {
      const allowResolvedFallback = options?.allowResolvedFallback !== false;
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
      if (!allowResolvedFallback) return buildStatsNeutralPredictionComparisonContext();
      const fallbackEntry = findStatsLatestResolvedPredictionLog(type);
      if (!fallbackEntry) return buildStatsNeutralPredictionComparisonContext("kỳ trước");
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

    function buildStatsAutomaticPrediction(type, sourceEntries) {
      const entries = Array.isArray(sourceEntries) ? sourceEntries : [];
      if (!entries.length) return { main: [], special: [] };
      const recentEntries = filterStatsRecentEntriesByMode(
        entries,
        statsRecentModeValue,
        statsRecentWindowValue,
      );
      const mainFrequency = buildStatsFrequencyItems(type, recentEntries);
      const mainOverdue = buildStatsOverdueItems(type, mainFrequency, entries);
      const main = [...buildStatsRecentFallbackPredictionSet(type, {
        mostItems: mainFrequency,
        overdueItems: mainOverdue,
      })];
      let special = [];
      if (TYPES[type]?.hasSpecial) {
        const specialFrequency = buildStatsFrequencyItems(type, recentEntries, { special: true });
        const specialOverdue = buildStatsOverdueItems(type, specialFrequency, entries, { special: true });
        special = [...collectOrderedHighlightNumbers(
          specialFrequency.map(item => item.value),
          specialOverdue.map(item => item.value),
          4,
        )];
      }
      return { main, special };
    }

    function hasStatsPredictionForKy(type, ky) {
      const normalizedKy = normalizeKy(ky);
      if (!normalizedKy) return false;
      return ensurePredictionLogBucket(type).some(entry =>
        getPredictionEntryMode(entry) === PREDICTION_MODE_STATS &&
        normalizeKy(entry?.predictedKy) === normalizedKy &&
        Array.isArray(entry?.tickets) &&
        entry.tickets.length
      );
    }

    function createStatsPredictionLog(type, predictedKy, sourceEntries, actualEntry = null) {
      const prediction = buildStatsAutomaticPrediction(type, sourceEntries);
      if (!prediction.main.length) return false;
      const special = prediction.special[0];
      const windowLabel = getStatsRecentWindowLabel(statsRecentWindowValue, statsRecentModeValue);
      const resolved = !!actualEntry?.draw;
      upsertPredictionLog(type, {
        id: `stats_${type}_${String(normalizeKy(predictedKy) || "").replace(/\D/g, "")}`,
        createdAt: getSyncedIsoString(),
        predictedKy,
        predictionMode: PREDICTION_MODE_STATS,
        strategyKey: "stats_frequency_overdue_v1",
        strategyLabel: `Thống kê ${windowLabel}`,
        modelKey: "stats_frequency_overdue_v1",
        modelLabel: `Thống kê ${windowLabel}`,
        engineKey: "stats_auto",
        engineLabel: "Tần suất + gan",
        playMode: "stats",
        pickSize: prediction.main.length,
        bundleCount: 1,
        tickets: [{
          main: prediction.main,
          special: Number.isInteger(special) ? special : null,
          playMode: "stats",
        }],
        topMainRanking: prediction.main,
        topSpecialRanking: prediction.special,
        resolved,
        resolvedAt: resolved ? getSyncedIsoString() : "",
        actualKy: resolved ? normalizeKy(actualEntry.ky) : "",
        actualDraw: resolved ? actualEntry.draw : null,
      });
      if (resolved) refreshResolvedPredictionSummaries(type);
      return true;
    }

    function ensureStatsPredictionCycle(type, entries) {
      const sourceEntries = Array.isArray(entries) ? entries : [];
      if (sourceEntries.length < 2) return false;
      const latestEntry = sourceEntries[sourceEntries.length - 1];
      const latestKy = normalizeKy(latestEntry?.ky);
      if (!latestKy) return false;
      let changed = false;

      // Use only draws before the target so the reconstructed score has no data leakage.
      if (!hasStatsPredictionForKy(type, latestKy)) {
        changed = createStatsPredictionLog(type, latestKy, sourceEntries.slice(0, -1), latestEntry) || changed;
      }

      const nextKyValue = kySortValue(latestKy) + 1;
      const nextKy = nextKyValue ? `#${String(nextKyValue).padStart(4, "0")}` : null;
      if (nextKy && !hasStatsPredictionForKy(type, nextKy)) {
        changed = createStatsPredictionLog(type, nextKy, sourceEntries) || changed;
      }
      return changed;
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

    function getStatsRecentSetCount(type) {
      const key = normalizeStatsType(type);
      const config = getStatsRecentTicketConfig(key);
      const numeric = Number(statsRecentSetCountByType[key]);
      if (Number.isInteger(numeric)) return Math.min(Math.max(numeric, 1), config.maxSets);
      const storedSets = Array.isArray(statsRecentSelectedByType[key]?.sets) ? statsRecentSelectedByType[key].sets : [];
      const lastFilledIndex = storedSets.reduce((last, set, index) => (
        (set?.main?.length || set?.special !== null) ? index : last
      ), -1);
      return Math.min(config.maxSets, Math.max(1, lastFilledIndex + 1, getStatsRecentActiveSetIndex(key) + 1));
    }

    function setStatsRecentSetCount(type, value) {
      const key = normalizeStatsType(type);
      const config = getStatsRecentTicketConfig(key);
      const numeric = Number(value);
      const count = Number.isInteger(numeric) ? Math.min(Math.max(numeric, 1), config.maxSets) : 1;
      statsRecentSetCountByType[key] = count;
      setStatsRecentActiveSetIndex(key, Math.min(getStatsRecentActiveSetIndex(key), count - 1));
    }

    function copyStatsRecentSelectedSet(type, sourceIndexValue, targetIndexValue) {
      const key = normalizeStatsType(type);
      const config = getStatsRecentTicketConfig(key);
      const sourceIndex = Number(sourceIndexValue);
      const targetIndex = Number(targetIndexValue);
      if (
        !Number.isInteger(sourceIndex) ||
        !Number.isInteger(targetIndex) ||
        sourceIndex === targetIndex ||
        sourceIndex < 0 || targetIndex < 0 ||
        sourceIndex >= config.maxSets || targetIndex >= getStatsRecentSetCount(key)
      ) return false;
      const sets = getStatsRecentSelectedSets(key);
      const sourceSet = sets[sourceIndex];
      if (!sourceSet || (!sourceSet.main.length && sourceSet.special === null)) return false;
      while (sets.length <= targetIndex) sets.push(createStatsRecentTicketSet());
      sets[targetIndex] = {
        main: [...sourceSet.main],
        special: sourceSet.special,
      };
      statsRecentSelectedByType[key] = { sets };
      return true;
    }

    function createStatsRecentTicketSet() {
      return { main: [], special: null };
    }

    function normalizeStatsRecentTicketSet(setValue) {
      const set = setValue && typeof setValue === "object" ? setValue : {};
      const main = Array.isArray(set.main)
        ? set.main.map(value => Number(value)).filter(value => Number.isInteger(value))
        : [];
      const hasSpecialValue = set.special !== null && set.special !== undefined && String(set.special).trim() !== "";
      const special = hasSpecialValue ? Number(set.special) : NaN;
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

    function getStatsModernOrderedItems(type, countByValue, fallbackItems = [], { special = false, limit = null, displayMode = statsRecentDisplayModeValue } = {}) {
      const config = TYPES[type] || {};
      const map = countByValue instanceof Map ? countByValue : new Map();
      const normalizedDisplayMode = typeof normalizeStatsRecentDisplayMode === "function"
        ? normalizeStatsRecentDisplayMode(displayMode)
        : (String(displayMode || "").trim().toLowerCase() === "count" ? "count" : "order");
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
      const numberOrderedItems = range(min, max).map(value => ({
        value: Number(value),
        count: Number(map.get(Number(value)) || 0),
        label: getStatsDisplayLabel(type, value, special),
      }));
      if (normalizedDisplayMode === "count") {
        const rankedItems = Array.isArray(fallbackItems) && fallbackItems.length
          ? fallbackItems
          : numberOrderedItems;
        return rankedItems.map(item => ({
          value: Number(item?.value),
          count: Number(item?.count || 0),
          label: getStatsDisplayLabel(type, item?.value, special),
        }));
      }
      return numberOrderedItems;
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
      const markerLabel = "Kết quả kỳ trước";
      return `
        <div class="stats-modern-legend" aria-label="Chú thích màu">
          <span><i class="stats-modern-dot is-purple"></i>Nền dự đoán hiện tại</span>
          <span><i class="stats-modern-badge is-hit">✓</i>Đúng ${escapeHtml(comparisonLabel)}</span>
          <span><i class="stats-modern-badge is-missed">×</i>Sai ${escapeHtml(comparisonLabel)}</span>
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

    function renderStatsModernDisplayModePicker(displayMode = statsRecentDisplayModeValue) {
      const normalizedDisplayMode = typeof normalizeStatsRecentDisplayMode === "function"
        ? normalizeStatsRecentDisplayMode(displayMode)
        : (String(displayMode || "").trim().toLowerCase() === "count" ? "count" : "order");
      const options = [
        { value: "order", label: "Số thứ tự" },
        { value: "count", label: "Số lần" },
      ];
      const label = options.find(option => option.value === normalizedDisplayMode)?.label || "Số thứ tự";
      return `
        <div class="stats-modern-select" aria-label="Chọn cách hiển thị bảng số">
          <button type="button" class="stats-modern-select-trigger" aria-haspopup="menu">
            <span class="stats-modern-select-text">
              <span class="stats-modern-select-label">Hiển thị</span>
              <strong class="stats-modern-select-value">${escapeHtml(label)}</strong>
            </span>
            <span class="stats-modern-chevron" aria-hidden="true"></span>
          </button>
          <div class="stats-modern-select-menu" role="menu">
            ${options.map(option => `
              <button
                type="button"
                class="stats-modern-select-option${option.value === normalizedDisplayMode ? " is-active" : ""}"
                data-stats-display-mode="${escapeHtml(option.value)}"
                role="menuitemradio"
                aria-checked="${option.value === normalizedDisplayMode ? "true" : "false"}"
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
      const actualTitle = comparisonLabel === "kỳ đã chấm"
        ? "Kỳ đã chấm"
        : (comparisonLabel === "kỳ gần nhất" ? "Kỳ gần nhất" : "Kỳ trước");
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
      const setCount = getStatsRecentSetCount(type);
      let activeSetIndex = getStatsRecentActiveSetIndex(type);
      if (activeSetIndex >= setCount) {
        setStatsRecentActiveSetIndex(type, setCount - 1);
        activeSetIndex = getStatsRecentActiveSetIndex(type);
      }
      const activeSet = selectedSets[activeSetIndex] || createStatsRecentTicketSet();
      const visibleRows = Array.from({ length: setCount }, (_, index) => ({
        index,
        set: selectedSets[index] || createStatsRecentTicketSet(),
      }));
      const filledSetCount = selectedSets.slice(0, setCount).filter(set => (set?.main?.length || 0) || set?.special !== null).length;
      const isKeno = normalizedType === "KENO";
      const selectedSummary = isKeno
        ? `Bậc ${config.kenoLevel} • Bộ ${activeSetIndex + 1}: ${activeSet.main.length}/${config.mainCount}`
        : `${filledSetCount}/${setCount}`;
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
              ${isKeno ? renderStatsRecentKenoLevelControl(config) : ""}
              <div class="stats-modern-set-dropdowns">
                <label>
                  <span>Số lượng</span>
                  <select data-stats-recent-set-count aria-label="Chọn số lượng bộ">
                    ${Array.from({ length: config.maxSets }, (_, index) => {
                      const value = index + 1;
                      return `<option value="${value}"${value === setCount ? " selected" : ""}>${value} bộ</option>`;
                    }).join("")}
                  </select>
                </label>
                <label>
                  <span>Đang chọn</span>
                  <select data-stats-recent-active-set-select aria-label="Chọn bộ đang thao tác">
                    ${Array.from({ length: setCount }, (_, index) => `<option value="${index}"${index === activeSetIndex ? " selected" : ""}>Bộ ${index + 1}</option>`).join("")}
                  </select>
                </label>
              </div>
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
          <div class="stats-modern-selected-list is-compact-grid">
            ${visibleRows.map(({ index, set }) => `
              <div
                class="stats-modern-selected-row${index === activeSetIndex ? " is-active" : ""}"
                data-stats-recent-set-card="${index}"
                draggable="true"
                title="Kéo Bộ ${index + 1} sang Bộ khác để sao chép nhanh"
              >
                <button type="button" class="stats-modern-selected-row-label" data-stats-recent-active-set="${index}">
                  <span>Bộ ${index + 1}</span>
                  <small>${set.main.length}/${config.mainCount}</small>
                </button>
                <div class="stats-modern-selected-balls">
                  ${set.main.length ? set.main.map(value => renderTicketBall(value, index, "main")).join("") : `<button type="button" class="stats-modern-selected-placeholder" data-stats-recent-active-set="${index}">Chưa chọn số</button>`}
                  ${config.hasSpecial ? `
                    <span class="stats-modern-special-text">${escapeHtml(config.specialLabel)}:</span>
                    ${set.special !== null
                      ? renderTicketBall(set.special, index, "special")
                      : `<span class="stats-modern-selected-placeholder">--</span>`}
                  ` : ""}
                </div>
              </div>
            `).join("")}
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
          <div class="stats-modern-keno-ticket-card is-summary">
            <div class="stats-modern-keno-ticket-main">
              <span class="stats-modern-keno-ticket-eyebrow">Kỳ mới nhất</span>
              <strong>Kỳ vé ${escapeHtml(kyText)}</strong>
              <span class="stats-modern-keno-ticket-meta">${escapeHtml(drawDateTimeText)}</span>
            </div>
            <div class="stats-modern-keno-ticket-divider" aria-hidden="true"></div>
            <div class="stats-modern-keno-ticket-side" aria-label="Thời gian tới kỳ Keno kế tiếp">
              <span class="stats-modern-keno-ticket-side-label">Kỳ sau</span>
              <strong data-stats-draw-countdown="KENO">${escapeHtml(getStatsDrawCountdownText("KENO"))}</strong>
            </div>
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
      const recentEntries = filterStatsRecentEntriesByMode(sourceEntries, recentMode, recentWindow);
      const specialFrequencyItems = typeConfig.hasSpecial ? buildStatsFrequencyItems(type, recentEntries, { special: true }) : [];
      const specialCountByValue = new Map(specialFrequencyItems.map(item => [Number(item.value), Number(item.count || 0)]));
      const specialMostItems = specialFrequencyItems.slice(0, STATS_RECENT100_SIDE_LIMIT);
      const specialCurrentPredictionSet = getStatsLatestSpecialPredictionHighlight(type, latestEntry).numbers;
      const latestActualSpecialSet = buildStatsLatestActualSpecialSet(type, latestEntry);
      const fallbackPredictionSet = currentPredictionSet instanceof Set && currentPredictionSet.size
        ? new Set()
        : buildStatsRecentFallbackPredictionSet(type, { mostItems, overdueItems });
      const effectiveCurrentPredictionSet = currentPredictionSet instanceof Set && currentPredictionSet.size
        ? currentPredictionSet
        : fallbackPredictionSet;
      const currentPredictionSource = typeof getPredictionDisplaySource === "function"
        ? getPredictionDisplaySource(currentPredictionEntry, effectiveCurrentPredictionSet)
        : (currentPredictionEntry ? "ai_log" : (effectiveCurrentPredictionSet instanceof Set && effectiveCurrentPredictionSet.size ? "stats_fallback" : "none"));
      const isFallbackPrediction = currentPredictionSource === "stats_fallback";
      const effectiveComparisonContext = currentPredictionSource === "ai_log"
        ? (comparisonContext && typeof comparisonContext === "object"
          ? comparisonContext
          : buildStatsNeutralPredictionComparisonContext("kỳ trước"))
        : buildStatsNeutralPredictionComparisonContext("kỳ gần nhất");
      const effectiveHitNumberSet = currentPredictionSource === "ai_log"
        ? (hitNumberSet instanceof Set ? hitNumberSet : new Set())
        : new Set();
      const effectiveMissedNumberSet = currentPredictionSource === "ai_log"
        ? (missedNumberSet instanceof Set ? missedNumberSet : new Set())
        : new Set();
      const effectiveSpecialHitSet = currentPredictionSource === "ai_log"
        ? getStatsLatestHitSpecialPredictionSet(type, latestEntry, latestActualSpecialSet)
        : new Set();
      const effectiveSpecialMissedSet = currentPredictionSource === "ai_log"
        ? getStatsLatestMissedSpecialPredictionSet(type, latestEntry, latestActualSpecialSet)
        : new Set();
      const comparisonActualSet = effectiveComparisonContext.actualSet instanceof Set
        ? effectiveComparisonContext.actualSet
        : latestActualSet;
      const comparisonEntry = effectiveComparisonContext.entry || null;
      const mainResultMarkerSet = latestActualSet instanceof Set ? latestActualSet : new Set();
      const specialResultMarkerSet = latestActualSpecialSet instanceof Set ? latestActualSpecialSet : new Set();
      const titleText = getStatsRecentPanelTitle(recentWindow, recentMode);
      const windowBadge = getStatsRecentWindowLabel(recentWindow, recentMode);
      const displayMode = typeof normalizeStatsRecentDisplayMode === "function"
        ? normalizeStatsRecentDisplayMode(statsRecentDisplayModeValue)
        : (String(statsRecentDisplayModeValue || "").trim().toLowerCase() === "count" ? "count" : "order");
      const mainItems = getStatsModernOrderedItems(type, countByValue, displayItems, {
        displayMode,
        limit: TYPES[type]?.threeDigit ? 50 : null,
      });
      const specialItems = typeConfig.hasSpecial
        ? getStatsModernOrderedItems(type, specialCountByValue, specialFrequencyItems, { special: true, displayMode })
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
            ${renderStatsModernDisplayModePicker(displayMode)}
            ${renderStatsModernWindowButtons(recentWindowOptions, recentWindow, recentMode)}
          </div>

          <div class="stats-modern-body">
            <div class="stats-modern-left">
              <section class="stats-modern-card stats-modern-main-card">
                <div class="stats-modern-main-head ${type === "KENO" ? "is-keno-live-head" : ""}">
                  ${mainHeadingHtml}
                  ${renderStatsModernLegend(type, effectiveComparisonContext.label)}
                </div>
                ${pending ? `
                  <div class="stats-modern-loading">Đang tính thống kê trong nền...</div>
                ` : `
                  ${renderStatsModernNumberGrid(type, mainItems, {
                    hitNumberSet: effectiveHitNumberSet,
                    missedNumberSet: effectiveMissedNumberSet,
                    currentPredictionSet: effectiveCurrentPredictionSet,
                    specialMarkerSet: mainResultMarkerSet,
                    showSpecialMarker: false,
                    countLabel: TYPES[type]?.threeDigit ? "lần" : "lần",
                  })}
                `}
              </section>

              ${typeConfig.hasSpecial ? `
                <section class="stats-modern-card stats-modern-special-card">
                  ${renderStatsModernPanelTitle("◆", `${type === "LOTO_6_55" ? "Số ĐB T7" : "Số đặc biệt"} (${getStatsModernRangeText(type, { special: true })})`)}
                  ${renderStatsModernNumberGrid(type, specialItems, {
                    hitNumberSet: effectiveSpecialHitSet,
                    missedNumberSet: effectiveSpecialMissedSet,
                    currentPredictionSet: specialCurrentPredictionSet,
                    specialMarkerSet: specialResultMarkerSet,
                    pickRole: "special",
                    compact: true,
                    showSpecialMarker: false,
                  })}
                </section>
              ` : ""}

              <div data-stats-recent-selected-host>
                ${renderStatsRecentSelectedPanel(type, {
                  hitNumberSet: effectiveHitNumberSet,
                  missedNumberSet: effectiveMissedNumberSet,
                  currentPredictionSet: effectiveCurrentPredictionSet,
                  countByValue,
                })}
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
                  hitNumberSet: effectiveHitNumberSet,
                  missedNumberSet: effectiveMissedNumberSet,
                })}
                ${renderStatsModernInsightPanel(type, {
                  mostItems,
                  leastItems,
                  overdueItems,
                  hitNumberSet: effectiveHitNumberSet,
                  missedNumberSet: effectiveMissedNumberSet,
                  currentPredictionSet: effectiveCurrentPredictionSet,
                })}
                ${renderStatsModernMetrics(type, {
                  mostItems,
                  leastItems,
                  overdueItems,
                  specialMostItems,
                  hitNumberSet: effectiveHitNumberSet,
                  missedNumberSet: effectiveMissedNumberSet,
                  countByValue,
                  latestActualSet,
                  latestEntry,
                  comparisonLabel: effectiveComparisonContext.label,
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
      const { computation } = getStatsRecentComputation(type, allEntries, statsRecentModeValue, statsRecentWindowValue);
      const fallbackPredictionSet = currentPredictionHighlight.numbers instanceof Set && currentPredictionHighlight.numbers.size
        ? new Set()
        : buildStatsRecentFallbackPredictionSet(type, {
            mostItems: computation?.mostItems || [],
            overdueItems: computation?.overdueItems || [],
          });
      const currentPredictionSource = typeof getPredictionDisplaySource === "function"
        ? getPredictionDisplaySource(currentPredictionHighlight.entry, currentPredictionHighlight.numbers instanceof Set && currentPredictionHighlight.numbers.size ? currentPredictionHighlight.numbers : fallbackPredictionSet)
        : (currentPredictionHighlight.entry ? "ai_log" : (fallbackPredictionSet instanceof Set && fallbackPredictionSet.size ? "stats_fallback" : "none"));
      const hitPredictionSet = currentPredictionSource === "ai_log"
        ? getStatsLatestHitPredictionSet(type, latestEntry, latestActualSet)
        : new Set();
      const missedPredictionSet = currentPredictionSource === "ai_log"
        ? getStatsLatestMissedPredictionSet(type, latestEntry, latestActualSet)
        : new Set();
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
      const currentPredictionSource = typeof getPredictionDisplaySource === "function"
        ? getPredictionDisplaySource(currentPredictionHighlight.entry, currentPredictionHighlight.numbers)
        : (currentPredictionHighlight.entry ? "ai_log" : (currentPredictionHighlight.numbers instanceof Set && currentPredictionHighlight.numbers.size ? "stats_fallback" : "none"));
      const hasAiPredictionEntry = currentPredictionSource === "ai_log";
      const comparisonContext = hasAiPredictionEntry
        ? getStatsPredictionComparisonContext(type, latestEntry, latestActualSet)
        : buildStatsNeutralPredictionComparisonContext("kỳ gần nhất");
      const hitPredictionSet = hasAiPredictionEntry
        ? getStatsLatestHitPredictionSet(type, latestEntry, latestActualSet)
        : new Set();
      const missedPredictionSet = hasAiPredictionEntry
        ? getStatsLatestMissedPredictionSet(type, latestEntry, latestActualSet)
        : new Set();
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
        await fetchLiveHistory(type, "all", { force, silent });
        if (refreshToken !== statsPanelRefreshToken) return;
        renderStatsPanel();
        let storeChanged = false;
        try {
          const ledgerScored = await scorePendingPredictionLedger(type);
          const ledgerChanged = await refreshPredictionLedgerForHistory(type);
          storeChanged = ledgerScored || ledgerChanged;
        } catch (ledgerError) {
          console.warn("Không thể đồng bộ chấm điểm prediction ledger:", ledgerError);
        }
        if (refreshToken !== statsPanelRefreshToken) return;
        reconcilePredictionLogsForType(type);
        const refreshedEntries = buildStatsEntriesForFeed(type, getLiveHistoryFeed(type));
        storeChanged = ensureStatsPredictionCycle(type, refreshedEntries) || storeChanged;
        if (storeChanged) await saveStore({ reason: `${type.toLowerCase()}_stats_prediction_cycle` });
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
        if (document.hidden || predictPageModeValue !== PREDICTION_MODE_STATS || statsPanelLoading) return;
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
        ["Phạm vi combo", payload?.comboMode === "keno_window" ? "Cửa sổ số liền nhau sau sắp xếp; không gồm mọi tổ hợp" : "Tổ hợp đầy đủ"],
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

    function normalizeAnalysisDrawPreset(value) {
      const normalized = String(value || "").trim();
      return ANALYSIS_DRAW_COUNT_OPTIONS.some(item => item.value === normalized) ? normalized : "30";
    }

    function restoreAnalysisUiState() {
      const saved = readJsonLocal(ANALYSIS_UI_KEY, {});
      analysisState.type = normalizeAnalysisType(saved?.type);
      analysisState.drawPreset = normalizeAnalysisDrawPreset(saved?.drawPreset);
      analysisState.customCount = String(saved?.customCount || "");
      analysisState.dateFrom = String(saved?.dateFrom || "");
      analysisState.dateTo = String(saved?.dateTo || "");
      analysisState.dateToTime = String(saved?.dateToTime || "");
      analysisState.sortMain = saved?.sortMain === "number" ? "number" : "frequency";
      analysisState.sortSpecial = saved?.sortSpecial === "number" ? "number" : "frequency";
    }

    function saveAnalysisUiState() {
      const { type, drawPreset, customCount, dateFrom, dateTo, dateToTime, sortMain, sortSpecial } = analysisState;
      writeJsonLocal(ANALYSIS_UI_KEY, { type, drawPreset, customCount, dateFrom, dateTo, dateToTime, sortMain, sortSpecial });
    }

    function getAnalysisMaxDrawCount() {
      const count = analysisState.availableDrawsByType[normalizeAnalysisType(analysisState.type)];
      return Number.isSafeInteger(count) && count > 0 ? Math.min(count, 2147483647) : null;
    }

    function clampAnalysisCustomCount() {
      const maximum = getAnalysisMaxDrawCount();
      if (maximum !== null && Number(analysisState.customCount) > maximum) {
        analysisState.customCount = String(maximum);
        document.getElementById("analysisCustomCountInput").value = analysisState.customCount;
        saveAnalysisUiState();
      }
    }

    function initAnalysisPanel() {
      const typeSelect = document.getElementById("analysisTypeSelect");
      const countSelect = document.getElementById("analysisDrawCountSelect");
      if (typeSelect && !typeSelect.options.length) {
        typeSelect.innerHTML = TYPE_KEYS.map(key => `<option value="${escapeHtml(key)}">${escapeHtml(TYPES[key]?.label || key)}</option>`).join("");
      }
      if (countSelect && !countSelect.options.length) {
        countSelect.innerHTML = ANALYSIS_DRAW_COUNT_OPTIONS.map(item => `<option value="${item.value}">${escapeHtml(item.label)}</option>`).join("");
      }
      if (typeSelect) {
        typeSelect.value = analysisState.type;
        typeSelect.__syncCustomSelect?.();
      }
      if (countSelect) {
        countSelect.value = analysisState.drawPreset;
        countSelect.__syncCustomSelect?.();
      }
      const customInput = document.getElementById("analysisCustomCountInput");
      const maximum = getAnalysisMaxDrawCount();
      const countLabel = document.getElementById("analysisDrawCountLabel");
      const available = analysisState.availableDrawsByType[normalizeAnalysisType(analysisState.type)];
      if (countLabel) countLabel.textContent = analysisState.drawPreset === "all" && Number.isSafeInteger(available) && available >= 0
        ? `Số kỳ • ${available.toLocaleString("vi-VN")} Kỳ` : "Số kỳ";
      clampAnalysisCustomCount();
      customInput.max = maximum === null ? "2147483647" : String(maximum);
      customInput.disabled = maximum === null;
      customInput.placeholder = maximum === null ? "Chờ tải số kỳ…" : "Nhập số kỳ";
      customInput.title = maximum === null ? "Đang xác định số kỳ hiện có" : `Tối đa ${maximum.toLocaleString("vi-VN")} kỳ`;
      if (customInput.value !== analysisState.customCount) customInput.value = analysisState.customCount;
      document.getElementById("analysisCustomCountField").hidden = analysisState.drawPreset !== "custom";
      syncAnalysisDateNavigation();
      const refreshButton = document.getElementById("analysisRefreshBtn");
      refreshButton.disabled = analysisState.loading;
      refreshButton.setAttribute("aria-busy", String(analysisState.loading));
      const captureButton = document.getElementById("analysisCaptureBtn");
      if (captureButton) {
        captureButton.disabled = analysisState.loading || !analysisState.lastPayload || !!analysisState.error || analysisState.captureBusy;
        captureButton.setAttribute("aria-busy", String(analysisState.captureBusy));
        captureButton.querySelector("span").textContent = analysisState.captureBusy ? "Đang chụp…" : "Chụp hình";
      }
    }

    let analysisCaptureToastTimer = null;

    function hideAnalysisCaptureToast() {
      clearTimeout(analysisCaptureToastTimer);
      analysisCaptureToastTimer = null;
      const toast = document.getElementById("analysisCaptureToast");
      if (!toast) return;
      toast.hidden = true;
      toast.classList.remove("is-fading");
      toast.querySelector("strong").textContent = "";
    }

    function showAnalysisCaptureToast() {
      hideAnalysisCaptureToast();
      const toast = document.getElementById("analysisCaptureToast");
      if (!toast) return;
      toast.hidden = false;
      toast.querySelector("strong").textContent = "Đã Tải Xong";
      analysisCaptureToastTimer = setTimeout(() => {
        toast.classList.add("is-fading");
        analysisCaptureToastTimer = setTimeout(hideAnalysisCaptureToast, 350);
      }, 1000);
    }

    async function captureAnalysisImage() {
      const source = document.getElementById("predictRootAnalysis");
      if (!source || source.hidden || !currentUser || analysisState.captureBusy || analysisState.loading ||
        analysisState.error || !analysisState.lastPayload) return;
      const owner = analysisSessionKey(), serial = ++analysisState.captureSerial;
      const type = normalizeAnalysisType(analysisState.type);
      const themeClass = document.body.className;
      const clone = source.cloneNode(true), controls = [...source.querySelectorAll("select,input")].filter(field => !field.closest("[data-analysis-export-ignore]"));
      const controlText = controls.map(field => field.tagName === "SELECT" ? field.selectedOptions[0]?.textContent || "" : field.value);
      [...clone.querySelectorAll("select,input")].filter(field => !field.closest("[data-analysis-export-ignore]")).forEach((field, i) => {
        if (field.tagName === "SELECT") field.value = controls[i].value;
        else field.setAttribute("value", controls[i].value);
      });
      clone.querySelectorAll("[data-analysis-export-ignore],script").forEach(node => node.remove());
      clone.hidden = false;
      const status = document.getElementById("analysisCaptureStatus");
      hideAnalysisCaptureToast();
      analysisState.captureBusy = true;
      status.hidden = false; status.textContent = "Đang tạo ảnh toàn bộ Phân tích…";
      initAnalysisPanel();
      let frame = null, downloadUrl = "", image = null, canvas = null, imageTimer = null;
      const stillCurrent = () => serial === analysisState.captureSerial && owner === analysisSessionKey();
      try {
        await document.fonts.ready;
        if (!stillCurrent()) return;
        const width = Math.max(1440, Math.min(1920, Math.ceil(source.getBoundingClientRect().width)));
        const rules = [...document.styleSheets].flatMap(sheet => [...sheet.cssRules].map(rule => rule.cssText)).join("\n");
        frame = document.createElement("iframe");
        frame.setAttribute("sandbox", "allow-same-origin");
        frame.setAttribute("aria-hidden", "true"); frame.tabIndex = -1;
        frame.style.cssText = `position:fixed;left:-100000px;top:0;width:${width}px;height:1000px;border:0;pointer-events:none;`;
        document.body.appendChild(frame);
        const doc = frame.contentDocument;
        doc.open();
        doc.write("<!doctype html><html><head></head><body></body></html>");
        doc.close();
        doc.documentElement.lang = "vi";
        doc.body.className = themeClass;
        const style = doc.createElement("style");
        style.textContent = rules + `
          html,body{margin:0!important;padding:0!important;width:${width}px!important;height:auto!important;min-height:0!important;overflow:visible!important;}
          *,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important;}
          #predictRootAnalysis{display:block!important;margin:0!important;width:${width}px!important;max-width:none!important;box-sizing:border-box!important;}
          #predictRootAnalysis .frequency-table-wrap,#predictRootAnalysis .frequency-selected-numbers{overflow:visible!important;max-height:none!important;}
          #predictRootAnalysis .frequency-table tr>:first-child{position:static!important;}
          #predictRootAnalysis :focus{outline:none!important;}
        `;
        doc.head.appendChild(style);
        doc.body.appendChild(doc.importNode(clone, true));
        const root = doc.getElementById("predictRootAnalysis");
        root.querySelectorAll("select,input").forEach((field, i) => {
          const computed = frame.contentWindow.getComputedStyle(field), replacement = doc.createElement("div");
          for (const property of computed) replacement.style.setProperty(property, computed.getPropertyValue(property));
          replacement.style.display = "flex"; replacement.style.alignItems = "center";
          replacement.id = field.id;
          replacement.textContent = controlText[i];
          field.replaceWith(replacement);
        });
        await doc.fonts.ready;
        // Standards mode keeps table sizing identical in the iframe and SVG image.
        // Keep native flex/grid layout rather than freezing rounded computed widths.
        const height = Math.ceil(Math.max(root.scrollHeight, root.getBoundingClientRect().height));
        if (!height || !stillCurrent()) return;
        const background = frame.contentWindow.getComputedStyle(root).backgroundColor;
        doc.body.style.cssText = `margin:0;padding:0;width:${width}px;height:${height}px;`;
        doc.body.prepend(style.cloneNode(true));
        const body = new XMLSerializer().serializeToString(doc.body);
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><foreignObject width="100%" height="100%">${body}</foreignObject></svg>`;
        image = new Image();
        await new Promise((resolve, reject) => {
          image.onload = resolve; image.onerror = () => reject(new Error("Chưa dựng được ảnh. Hãy thử chụp lại."));
          imageTimer = setTimeout(() => reject(new Error("Tạo ảnh quá thời gian chờ. Hãy thử lại.")), 30000);
          image.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
        });
        clearTimeout(imageTimer); imageTimer = null;
        if (!stillCurrent()) return;
        const scale = Math.min(2, 32760 / width, 32760 / height, Math.sqrt(48000000 / (width * height)));
        canvas = document.createElement("canvas");
        canvas.width = Math.floor(width * scale); canvas.height = Math.floor(height * scale);
        const context = canvas.getContext("2d");
        if (!context) throw new Error("Trình duyệt chưa thể tạo ảnh. Hãy thử lại.");
        context.fillStyle = background; context.fillRect(0, 0, canvas.width, canvas.height);
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
        if (!blob || !blob.size) throw new Error("Chưa lưu được ảnh PNG. Hãy thử lại.");
        if (!stillCurrent()) return;
        const parts = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Ho_Chi_Minh", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }).formatToParts(new Date());
        const time = Object.fromEntries(parts.map(part => [part.type, part.value]));
        const filename = `DVLF_Phan-tich_${type}_${time.year}${time.month}${time.day}_${time.hour}${time.minute}${time.second}.png`;
        downloadUrl = URL.createObjectURL(blob);
        const link = document.createElement("a"); link.href = downloadUrl; link.download = filename;
        document.body.appendChild(link); link.click(); link.remove();
        status.hidden = true; status.textContent = "";
        showAnalysisCaptureToast();
        const releaseUrl = downloadUrl; downloadUrl = "";
        setTimeout(() => URL.revokeObjectURL(releaseUrl), 60000);
      } catch (error) {
        if (stillCurrent()) { status.hidden = false; status.textContent = error.message || "Chưa chụp được ảnh. Hãy thử lại."; }
      } finally {
        clearTimeout(imageTimer);
        if (image) { image.onload = null; image.onerror = null; image.src = ""; }
        if (canvas) { canvas.width = 0; canvas.height = 0; }
        frame?.remove();
        if (downloadUrl) URL.revokeObjectURL(downloadUrl);
        if (stillCurrent()) { analysisState.captureBusy = false; initAnalysisPanel(); }
      }
    }

    function getAnalysisDateError(from, to) {
      const valid = value => /^\d{4}-\d{2}-\d{2}$/.test(value)
        && Number.isFinite(Date.parse(`${value}T00:00:00Z`))
        && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
      if (!valid(from) || !valid(to)) return "Vui lòng nhập đầy đủ ngày bắt đầu và ngày kết thúc hợp lệ.";
      return from > to ? "Ngày bắt đầu phải trước hoặc bằng ngày kết thúc." : "";
    }

    function getAnalysisDateBounds() {
      return analysisState.availableDatesByType[normalizeAnalysisType(analysisState.type)] || null;
    }

    function getAnalysisDateBoundsError(from, to) {
      const bounds = getAnalysisDateBounds();
      if (!bounds) return "Chưa xác định được giới hạn ngày của loại xổ số này. Hãy bấm Cập nhật.";
      if (from < bounds.from || to > bounds.to) return `Chỉ được chọn ngày từ ${bounds.from} đến ${bounds.to}.`;
      return "";
    }

    function isAnalysis535() {
      return normalizeAnalysisType(analysisState.type) === "LOTO_5_35";
    }

    function getAnalysisCutoffError(from, to, time = "") {
      const message = getAnalysisDateBoundsError(from, to);
      if (message || !isAnalysis535()) return message;
      const bounds = getAnalysisDateBounds();
      if (!["13:00", "21:00"].includes(time)) return "Chọn kỳ quay 13:00 hoặc 21:00.";
      if ((to === bounds.from && time < bounds.fromTime) || (to === bounds.to && time > bounds.toTime)) {
        return `Chỉ chọn đến kỳ mới nhất ${bounds.to} ${bounds.toTime}.`;
      }
      return "";
    }

    function isAnalysisAtLatestDraw(payload) {
      if (!payload || !payload.availableToDate || !payload.toDate) return false;
      if (payload.toDate !== payload.availableToDate) return payload.toDate > payload.availableToDate;
      return !isAnalysis535() || payload.toTime >= payload.availableToTime;
    }

    function getAnalysisNavigationTarget(payload, direction) {
      const bounds = getAnalysisDateBounds();
      if (!payload || !bounds || (direction > 0 && isAnalysisAtLatestDraw(payload))) return null;
      if (!isAnalysis535()) return getAnalysisShiftedDates(bounds.from, payload.toDate, direction);
      const time = payload.toTime;
      if (!["13:00", "21:00"].includes(time)) return null;
      if ((direction < 0 && time === "21:00") || (direction > 0 && time === "13:00")) {
        return { from: bounds.from, to: payload.toDate, time: direction < 0 ? "13:00" : "21:00" };
      }
      const dates = getAnalysisShiftedDates(bounds.from, payload.toDate, direction);
      return dates && { ...dates, time: direction < 0 ? "21:00" : "13:00" };
    }

    function syncAnalysisSessionInput() {
      const field = document.getElementById("analysisDateSessionField");
      field.hidden = !isAnalysis535();
      if (!isAnalysis535()) return;
      const bounds = getAnalysisDateBounds();
      const end = document.getElementById("analysisDateTo").value;
      const select = document.getElementById("analysisDateToTime");
      for (const option of select.options) option.disabled = !bounds || !!getAnalysisCutoffError(bounds.from, end, option.value);
      if (!select.selectedOptions.length || select.selectedOptions[0].disabled) {
        select.value = [...select.options].filter(option => !option.disabled).at(-1)?.value || "";
      }
      document.getElementById("analysisDateFirstTime").textContent = bounds ? `Kỳ đầu: ${bounds.fromTime}` : "";
    }

    function syncAnalysisDateNavigation(payload = analysisState.lastPayload) {
      const bounds = getAnalysisDateBounds();
      for (const [id, direction] of [["analysisDatePrev", -1], ["analysisDateNext", 1]]) {
        const button = document.getElementById(id);
        if (!button) continue;
        const target = getAnalysisNavigationTarget(payload, direction);
        button.title = `${direction < 0 ? "Lùi" : "Tiến"} ${isAnalysis535() ? "1 kỳ quay" : "ngày kết thúc 1 ngày"}`;
        if (direction > 0 && isAnalysisAtLatestDraw(payload)) button.title = "Đã ở kỳ hiện tại (kỳ mới nhất có kết quả)";
        button.setAttribute("aria-label", button.title);
        button.hidden = !payload;
        button.disabled = !target || !bounds || !!getAnalysisCutoffError(target.from, target.to, target.time)
          || analysisState.loading || analysisState.captureBusy || !document.getElementById("analysisDateForm").hidden;
        button.setAttribute("aria-disabled", String(button.disabled));
      }
      for (const id of ["analysisDateFrom", "analysisDateTo"]) {
        const input = document.getElementById(id);
        if (!input) continue;
        input.min = bounds?.from || "";
        input.max = bounds?.to || "";
      }
    }

    function getAnalysisShiftedDates(from, to, direction) {
      if (getAnalysisDateError(from, to) || ![-1, 1].includes(direction)) return null;
      const shift = value => {
        const day = new Date(`${value}T00:00:00Z`);
        day.setUTCDate(day.getUTCDate() + direction);
        return day.toISOString().slice(0, 10);
      };
      const dates = { from, to: shift(to) };
      return getAnalysisDateError(dates.from, dates.to) ? null : dates;
    }

    async function shiftAnalysisDates(direction) {
      const payload = analysisState.lastPayload;
      if (!payload || analysisState.loading || analysisState.captureBusy || !document.getElementById("analysisDateForm").hidden) return;
      const dates = getAnalysisNavigationTarget(payload, direction);
      if (!dates || getAnalysisCutoffError(dates.from, dates.to, dates.time)) return;
      const previous = { drawPreset: analysisState.drawPreset, dateFrom: analysisState.dateFrom, dateTo: analysisState.dateTo, dateToTime: analysisState.dateToTime };
      const owner = analysisSessionKey();
      const token = analysisState.refreshToken + 1;
      Object.assign(analysisState, { drawPreset: "dates", dateFrom: dates.from, dateTo: dates.to, dateToTime: dates.time || "" });
      saveAnalysisUiState();
      await loadAnalysis({ force: true, silent: false });
      if (owner !== analysisSessionKey() || token !== analysisState.refreshToken) return;
      if (!analysisState.lastPayload) {
        Object.assign(analysisState, previous, { lastPayload: payload });
        saveAnalysisUiState();
        renderAnalysis(payload);
      }
      document.getElementById(direction < 0 ? "analysisDatePrev" : "analysisDateNext").focus();
    }

    function openAnalysisDateEditor() {
      const payload = analysisState.lastPayload;
      const form = document.getElementById("analysisDateForm");
      document.getElementById("analysisDateFrom").value = getAnalysisDateBounds()?.from || "";
      document.getElementById("analysisDateTo").value = analysisState.drawPreset === "dates" ? analysisState.dateTo : payload?.toDate || "";
      document.getElementById("analysisDateToTime").value = analysisState.drawPreset === "dates" ? analysisState.dateToTime || payload?.toTime || "21:00" : payload?.toTime || "21:00";
      syncAnalysisSessionInput();
      document.getElementById("analysisDateError").hidden = true;
      form.hidden = false;
      syncAnalysisDateNavigation();
      document.querySelector("[data-analysis-edit-dates]")?.setAttribute("aria-expanded", "true");
      document.getElementById("analysisDateTo").focus();
    }

    function closeAnalysisDateEditor() {
      document.getElementById("analysisDateForm").hidden = true;
      syncAnalysisDateNavigation();
      document.querySelector("[data-analysis-edit-dates]")?.setAttribute("aria-expanded", "false");
    }

    function applyAnalysisDates(event) {
      event?.preventDefault();
      const form = document.getElementById("analysisDateForm");
      const from = getAnalysisDateBounds()?.from || "";
      document.getElementById("analysisDateFrom").value = from;
      const to = document.getElementById("analysisDateTo").value;
      const time = isAnalysis535() ? document.getElementById("analysisDateToTime").value : "";
      const message = getAnalysisDateError(from, to) || getAnalysisCutoffError(from, to, time);
      const error = document.getElementById("analysisDateError");
      error.textContent = message;
      error.hidden = !message;
      if (message || !form.reportValidity()) return;
      analysisState.dateFrom = from;
      analysisState.dateTo = to;
      analysisState.dateToTime = time;
      analysisState.drawPreset = "dates";
      saveAnalysisUiState();
      closeAnalysisDateEditor();
      void loadAnalysis({ force: true, silent: false });
      document.getElementById("analysisRefreshBtn").focus();
    }

    function buildAnalysisQuery() {
      if (analysisState.drawPreset === "dates") {
        const firstDate = getAnalysisDateBounds()?.from;
        if (firstDate && analysisState.dateFrom !== firstDate) {
          analysisState.dateFrom = firstDate;
          saveAnalysisUiState();
        }
        if (isAnalysis535() && !analysisState.dateToTime) {
          analysisState.dateToTime = analysisState.dateTo === getAnalysisDateBounds()?.to ? getAnalysisDateBounds().toTime : "21:00";
          saveAnalysisUiState();
        }
        const message = getAnalysisDateError(analysisState.dateFrom, analysisState.dateTo) || getAnalysisCutoffError(analysisState.dateFrom, analysisState.dateTo, analysisState.dateToTime);
        if (message) throw new Error(message);
        return new URLSearchParams({ type: normalizeAnalysisType(analysisState.type), period: "custom", mode: "frequency",
          from: analysisState.dateFrom, to: analysisState.dateTo, ...(isAnalysis535() ? { toTime: analysisState.dateToTime } : {}), drawMarkers: "2", delayVersion: "2", dateBoundsVersion: "2" });
      }
      clampAnalysisCustomCount();
      // Request the full available range, including draws added after this page was opened.
      const raw = analysisState.drawPreset === "all" ? "2147483647"
        : analysisState.drawPreset === "custom" ? analysisState.customCount : normalizeAnalysisDrawPreset(analysisState.drawPreset);
      const drawCount = Number(raw);
      if (!/^[0-9]+$/.test(raw) || !Number.isSafeInteger(drawCount) || drawCount < 1 || drawCount > 2147483647) {
        throw new Error("Nhập số kỳ là số nguyên dương hợp lệ.");
      }
      return new URLSearchParams({ type: normalizeAnalysisType(analysisState.type), period: "all", mode: "frequency", drawCount: String(drawCount), drawMarkers: "2", delayVersion: "2", dateBoundsVersion: "2" });
    }

    function analysisSessionKey() {
      return String(currentUser || "") + ":" + String(currentAccountId || "");
    }

    function validateAnalysisFrequency(payload, type, drawCount) {
      if (!payload || payload.ok !== true || payload.type !== type || payload.mode !== "frequency"
        || !Number.isSafeInteger(payload.totalDraws) || payload.totalDraws < 1
        || payload.requestedDrawCount !== drawCount || !Number.isSafeInteger(payload.availableDraws)
        || payload.availableDraws < payload.totalDraws
        || (drawCount !== null && payload.totalDraws !== Math.min(drawCount, payload.availableDraws))
        || (drawCount === null && payload.period !== "custom")) {
        throw new Error("Dữ liệu tần suất chưa hợp lệ. Hãy bấm Cập nhật để thử lại.");
      }
      if (getAnalysisDateError(payload.availableFromDate, payload.availableToDate)) {
        throw new Error("Giới hạn ngày dữ liệu chưa hợp lệ. Hãy bấm Cập nhật để thử lại.");
      }
      if (type === "LOTO_5_35" && [payload.availableFromTime, payload.availableToTime, payload.fromTime, payload.toTime].some(time => !["13:00", "21:00"].includes(time))) {
        throw new Error("Giờ các kỳ 5/35 chưa hợp lệ. Hãy bấm Cập nhật để thử lại.");
      }
      const cfg = TYPES[type];
      const latest = payload.latestDraw;
      const previous = payload.previousDraw;
      if (!latest || !Array.isArray(latest.numbers) || !latest.numbers.length) {
        throw new Error("Chưa có dữ liệu kỳ gần nhất để đánh dấu.");
      }
      if (previous !== null && (!previous || !Array.isArray(previous.numbers) || !previous.numbers.length)) {
        throw new Error("Dữ liệu kỳ trước chưa hợp lệ. Hãy bấm Cập nhật để thử lại.");
      }
      for (const special of [false, true]) {
        const group = payload.data?.[special ? "special" : "main"];
        const supported = !special || cfg.hasSpecial;
        if (!group || group.supported !== supported || !Array.isArray(group.items)) throw new Error("Dữ liệu nhóm số chưa đầy đủ.");
        if (!supported) {
          if (group.items.length || group.totalOccurrences !== 0) throw new Error("Dữ liệu số đặc biệt chưa hợp lệ.");
          continue;
        }
        const min = special ? cfg.specialMin : cfg.mainMin;
        const max = special ? cfg.specialMax : cfg.mainMax;
        const width = cfg.threeDigit ? 3 : 2;
        const expected = new Set(Array.from({ length: max - min + 1 }, (_, i) => String(min + i).padStart(width, "0")));
        const latestNumbers = special ? (latest.special ? [latest.special] : []) : latest.numbers;
        if (latestNumbers.some(number => !expected.has(number))) throw new Error("Bộ số kỳ gần nhất chưa hợp lệ.");
        const previousNumbers = previous ? (special ? (previous.special ? [previous.special] : []) : previous.numbers) : [];
        if (previousNumbers.some(number => !expected.has(number))) throw new Error("Bộ số kỳ trước chưa hợp lệ.");
        let total = 0;
        for (const row of group.items) {
          if (!expected.delete(row.number) || !Number.isSafeInteger(row.count) || row.count < 0) throw new Error("Dữ liệu bộ số hoặc số lượt chưa hợp lệ.");
          if (!Number.isSafeInteger(row.currentDelay) || row.currentDelay < 0 || row.currentDelay > payload.totalDraws
            || typeof row.delayLowerBound !== "boolean" || row.delayLowerBound !== (row.count === 0)
            || (row.count === 0 ? row.currentDelay !== payload.totalDraws : row.currentDelay >= payload.totalDraws)
            || (row.averageDelay !== null && (!Number.isFinite(row.averageDelay) || row.averageDelay < 0
              || row.averageDelay > Math.max(0, payload.totalDraws - 2) || row.count < 2))) {
            throw new Error("Dữ liệu độ trễ chưa hợp lệ. Hãy bấm Cập nhật để thử lại.");
          }
          const previousCount = drawCount === null ? payload.totalDraws - 1 : Math.min(drawCount, payload.availableDraws - 1);
          if ((row.previousDelay !== null && (!Number.isSafeInteger(row.previousDelay) || row.previousDelay < 0 || row.previousDelay >= previousCount))
            || (row.previousAverageDelay !== null && (!Number.isFinite(row.previousAverageDelay) || row.previousAverageDelay < 0
              || row.previousAverageDelay > Math.max(0, previousCount - 2) || row.previousDelay === null || previousCount < 2))) {
            throw new Error("Dữ liệu chuỗi kỳ trước chưa hợp lệ. Hãy bấm Cập nhật để thử lại.");
          }
          total += row.count;
        }
        if (expected.size || !Number.isSafeInteger(total) || total !== group.totalOccurrences) throw new Error("Tổng lượt xuất hiện chưa khớp dữ liệu.");
      }
      return payload;
    }

    async function fetchAnalysisFrequency(params, signal) {
      const response = await fetch(`/api/analysis?${params}`, { credentials: "same-origin", cache: "no-store", signal });
      const payload = await response.json();
      if (!response.ok || payload?.ok === false) throw new Error(payload?.message || "Không tải được dữ liệu tần suất.");
      const result = validateAnalysisFrequency(payload, params.get("type"), params.has("drawCount") ? Number(params.get("drawCount")) : null);
      if (!params.has("drawCount") && (result.fromDate !== params.get("from") || result.toDate !== params.get("to"))) {
        throw new Error("Khoảng ngày trả về chưa khớp yêu cầu. Hãy bấm Cập nhật để thử lại.");
      }
      if (params.has("toTime") && result.toTime !== params.get("toTime")) throw new Error("Kỳ kết thúc trả về chưa khớp yêu cầu.");
      return result;
    }

    async function loadAnalysis({ force = false, silent = true } = {}) {
      if (analysisState.predictionKey && analysisState.predictionKey !== getAnalysisPredictionSelection().key) clearAnalysisPrediction();
      const token = ++analysisState.refreshToken;
      const owner = analysisSessionKey();
      analysisState.controller?.abort();
      const controller = new AbortController();
      analysisState.controller = controller;
      analysisState.loading = true;
      analysisState.predictionCountOpen = false;
      analysisState.error = "";
      analysisState.lastPayload = null;
      renderAnalysis(null);
      let timedOut = false;
      const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 45000);
      try {
        if ((analysisState.drawPreset === "custom" && getAnalysisMaxDrawCount() === null)
          || (analysisState.drawPreset === "dates" && !getAnalysisDateBounds())) {
          const type = normalizeAnalysisType(analysisState.type);
          const probe = await fetchAnalysisFrequency(new URLSearchParams({ type, period: "all", mode: "frequency", drawCount: "1", drawMarkers: "2", delayVersion: "2", dateBoundsVersion: "2" }), controller.signal);
          if (token !== analysisState.refreshToken || owner !== analysisSessionKey()) return;
          analysisState.availableDrawsByType[type] = probe.availableDraws;
          analysisState.availableDatesByType[type] = { from: probe.availableFromDate, to: probe.availableToDate, fromTime: probe.availableFromTime, toTime: probe.availableToTime };
          initAnalysisPanel();
        }
        const params = buildAnalysisQuery();
        const payload = await fetchAnalysisFrequency(params, controller.signal);
        if (token !== analysisState.refreshToken || owner !== analysisSessionKey()) return;
        analysisState.availableDrawsByType[payload.type] = payload.availableDraws;
        analysisState.availableDatesByType[payload.type] = { from: payload.availableFromDate, to: payload.availableToDate, fromTime: payload.availableFromTime, toTime: payload.availableToTime };
        if (analysisState.drawPreset === "dates" && analysisState.dateFrom !== payload.availableFromDate) {
          analysisState.dateFrom = payload.availableFromDate;
          saveAnalysisUiState();
          return loadAnalysis({ force, silent });
        }
        clampAnalysisCustomCount();
        if (analysisState.drawPreset === "custom" && payload.requestedDrawCount > payload.availableDraws) {
          return loadAnalysis({ force, silent });
        }
        analysisState.lastPayload = payload;
      } catch (error) {
        if (token !== analysisState.refreshToken || owner !== analysisSessionKey()) return;
        analysisState.error = timedOut ? "Tải tần suất quá thời gian chờ. Bấm Cập nhật để thử lại." : String(error?.message || "Không tải được dữ liệu tần suất.");
      } finally {
        clearTimeout(timeout);
        if (token === analysisState.refreshToken && owner === analysisSessionKey()) {
          analysisState.loading = false;
          analysisState.controller = null;
          renderAnalysis(analysisState.lastPayload);
        }
      }
    }

    function analysisMarksStorageKey() {
      const id = String(currentAccountId || "");
      return currentUser && /^[1-9][0-9]{11}$/.test(id) ? `vietlott_analysis_marks_v1:${id}` : "";
    }

    function restoreAnalysisMarks() {
      const key = analysisMarksStorageKey();
      if (analysisState.marksOwner === key) return key;
      analysisState.marksOwner = key;
      analysisState.marksByType = {};
      if (!key) return key;
      const saved = readJsonLocal(key, {});
      for (const type of TYPE_KEYS) {
        if (!saved[type] || typeof saved[type] !== "object") continue;
        const cfg = TYPES[type];
        const clean = special => {
          if (special && !cfg.hasSpecial) return [];
          const values = saved[type][special ? "special" : "main"];
          if (!Array.isArray(values)) return [];
          const min = special ? cfg.specialMin : cfg.mainMin, max = special ? cfg.specialMax : cfg.mainMax;
          const width = cfg.threeDigit ? 3 : 2;
          return [...new Set(values.filter(value => typeof value === "string" && /^[0-9]+$/.test(value) &&
            Number(value) >= min && Number(value) <= max && String(Number(value)).padStart(width, "0") === value))];
        };
        analysisState.marksByType[type] = { main: clean(false), special: clean(true) };
      }
      return key;
    }

    function saveAnalysisMarks() {
      const key = analysisMarksStorageKey();
      if (!key || analysisState.marksOwner !== key) return;
      try { writeJsonLocal(key, analysisState.marksByType); } catch { /* Keep in-memory selection if browser storage is unavailable. */ }
    }

    function getAnalysisMarks(special = false) {
      restoreAnalysisMarks();
      const type = normalizeAnalysisType(analysisState.type);
      if (!analysisState.marksByType[type]) analysisState.marksByType[type] = { main: [], special: [] };
      return analysisState.marksByType[type][special ? "special" : "main"];
    }

    function getAnalysisStreak(row) {
      if (row.delayLowerBound || !Number.isSafeInteger(row.currentDelay) || row.currentDelay < 0 ||
        !Number.isFinite(row.averageDelay) || row.averageDelay <= 0) return 0;
      // Compare against the same two-decimal mean shown in the table, using integer hundredths.
      const displayedAverage = row.averageDelay.toLocaleString("en-US", { useGrouping: false, maximumFractionDigits: 2 });
      const averageHundredths = Math.round(Number(displayedAverage) * 100);
      return averageHundredths > 0 ? Math.floor(row.currentDelay * 100 / averageHundredths) : 0;
    }

    function renderAnalysisFlameSvg(color, id, level = 0) {
      const colors = color === "green" ? ["#16a34a", "#22c55e", "#4ade80", "#b8ffbc", "#dcfce7", "#f0fff4"]
        : color === "gray" ? ["#64748b", "#94a3b8", "#b6c2d0", "#dbe4ed", "#edf2f7", "#ffffff"]
          : ["#ff4038", "#ff7900", "#ffa000", "#fff46b", "#fff99a", "#fff5ce"];
      return `<svg viewBox="0 0 40 50" aria-hidden="true" focusable="false">
        <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop stop-color="${colors[0]}"/><stop offset=".58" stop-color="${colors[1]}"/><stop offset="1" stop-color="${colors[2]}"/></linearGradient><linearGradient id="${id}-core" x1="0" y1="0" x2="0" y2="1"><stop stop-color="${colors[3]}"/><stop offset=".75" stop-color="${colors[4]}"/><stop offset="1" stop-color="${colors[5]}"/></linearGradient></defs>
        <path fill="url(#${id})" d="M15 1C12-1 12 2 15 5C23 17 8 16 9 28C6 24 8 20 7 18C0 24-2 37 4 44C10 52 29 52 36 43C42 35 37 27 34 24C33 23 33 31 28 28C22 24 38 4 15 1Z"/>
        <path fill="url(#${id}-core)" d="M24 19C15 23 13 31 15 36C13 38 12 35 12 33C8 38 10 45 16 47C23 50 32 46 31 39C30 31 19 29 24 19Z"/>
        ${level >= 2 ? `<text class="frequency-fire-count" x="20" y="42" text-anchor="middle"${level >= 10 ? ' textLength="21" lengthAdjust="spacingAndGlyphs"' : ""}>${level}</text>` : ""}
      </svg>`;
    }

    function renderAnalysisStreak(row, groupKey) {
      const state = getAnalysisStreakState(row);
      if (!state) return "";
      const { color, level } = state;
      const id = `frequency-fire-${groupKey}-${row.number}`;
      const average = color === "gray" ? row.previousAverageDelay : row.averageDelay;
      const mean = average.toLocaleString("vi-VN", { maximumFractionDigits: 2 });
      const label = color === "gray"
        ? `Vừa mất chuỗi đỏ ${level.toLocaleString("vi-VN")} lần: số vừa ra ở kỳ hiện tại; trước đó trễ ${row.previousDelay.toLocaleString("vi-VN")} kỳ, trễ TB ${mean} kỳ.`
        : color === "green"
          ? `Sắp đạt chuỗi đỏ: hiện trễ ${row.currentDelay.toLocaleString("vi-VN")} kỳ, trễ TB ${mean} kỳ. Nếu kỳ tiếp theo chưa ra sẽ đạt ngưỡng đỏ.`
          : `Chuỗi ${level.toLocaleString("vi-VN")} lần: độ trễ ${row.currentDelay.toLocaleString("vi-VN")} kỳ, trễ TB ${mean} kỳ.`;
      return `<span class="frequency-fire is-${color}" data-streak="${level}" data-streak-state="${color}" role="img" aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}">${renderAnalysisFlameSvg(color, id, level)}</span>`;
    }

    function getAnalysisStreakState(row) {
      const level = getAnalysisStreak(row);
      if (level >= 1) return { color: "red", level };
      if (row.currentDelay === 0) {
        const lost = getAnalysisStreak({ currentDelay: row.previousDelay, averageDelay: row.previousAverageDelay, delayLowerBound: false });
        if (lost >= 1) return { color: "gray", level: lost };
      }
      if (!row.delayLowerBound && Number.isSafeInteger(row.currentDelay) && row.currentDelay >= 0
        && getAnalysisStreak({ ...row, currentDelay: row.currentDelay + 1 }) >= 1) return { color: "green", level: 1 };
      return null;
    }

    function renderFrequencyTable(group, special = false, latestDraw = {}, previousDraw = null) {
      const title = `Thống kê tần suất xuất hiện bộ số ${special ? "đặc biệt" : "chính"}`;
      const groupKey = special ? "special" : "main";
      const marks = getAnalysisMarks(special);
      const latestNumbers = new Set(special ? (latestDraw.special ? [latestDraw.special] : []) : latestDraw.numbers || []);
      const previousNumbers = new Set(previousDraw ? (special ? (previousDraw.special ? [previousDraw.special] : []) : previousDraw.numbers || []) : []);
      const drawLabel = (label, draw) => `${label}${draw.drawId ? " #" + draw.drawId : ""}${draw.date ? " · " + draw.date : ""}${draw.time ? " " + draw.time : ""}`;
      const latestLabel = drawLabel("Hiện Tại", latestDraw);
      const previousLabel = previousDraw ? drawLabel("Kỳ Trước", previousDraw) : "Chưa có dữ liệu kỳ trước";
      const sort = analysisState[special ? "sortSpecial" : "sortMain"];
      const metricSort = analysisState[special ? "sortMetricSpecial" : "sortMetricMain"];
      const streakSort = !metricSort && analysisState[special ? "sortStreakSpecial" : "sortStreakMain"];
      const baseOrder = (a, b) => (sort === "number" ? 0 : b.count - a.count) || Number(a.number) - Number(b.number);
      const streaks = streakSort ? new Map(group.items.map(row => [row, getAnalysisStreakState(row)])) : null;
      const colorPriority = { red: 3, green: 2, gray: 1 };
      const items = [...group.items].sort((a, b) => {
        if (metricSort) {
          const left = a[metricSort], right = b[metricSort];
          const leftKnown = Number.isFinite(left), rightKnown = Number.isFinite(right);
          if (leftKnown !== rightKnown) return leftKnown ? -1 : 1;
          if (leftKnown && left !== right) return right - left;
        }
        if (streakSort) {
          const left = streaks.get(a), right = streaks.get(b);
          const byColor = (colorPriority[right?.color] || 0) - (colorPriority[left?.color] || 0);
          const byLevel = (right?.level || 0) - (left?.level || 0);
          if (byColor || byLevel) return byColor || byLevel;
        }
        return baseOrder(a, b);
      });
      const sortLabel = sort === "number" ? "Theo số thứ tự" : "Tần suất";
      const streakSortLabel = streakSort ? `Đỏ → Xanh → Xám → Trống, mức chuỗi giảm dần. Bấm để trở lại ${sortLabel}` : "Bấm để xếp Đỏ → Xanh → Xám → Trống, mức chuỗi từ lớn đến nhỏ";
      const streakButton = `<button type="button" class="frequency-column-sort frequency-streak-sort" data-streak-sort="${groupKey}" aria-pressed="${!!streakSort}" title="${streakSortLabel}" aria-label="Số ${special ? "đặc biệt" : "chính"}: ${streakSortLabel}">Chuỗi</button>`;
      const metricButton = (key, label) => {
        const active = metricSort === key;
        const hint = active ? `${label} giảm dần. Bấm để trở lại ${sortLabel}` : `Bấm để sắp xếp ${label} từ lớn đến nhỏ`;
        return `<button type="button" class="frequency-column-sort" data-metric-sort="${key}" data-metric-group="${groupKey}" aria-pressed="${active}" title="${hint}" aria-label="Số ${special ? "đặc biệt" : "chính"}: ${hint}">${label}</button>`;
      };
      const nextSort = sort === "number" ? "frequency" : "number";
      const nextSortLabel = nextSort === "number" ? "Theo số thứ tự" : "Tần suất";
      const sortButton = `<button type="button" class="frequency-sort-toggle${sort === "number" ? " is-number" : ""}" data-frequency-sort="${nextSort}" data-sort-group="${groupKey}" title="${sortLabel} · Bấm để chuyển sang ${nextSortLabel}" aria-label="Số ${special ? "đặc biệt" : "chính"}: ${sortLabel}. Chuyển sang ${nextSortLabel}"><svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="m4 6 4 4 4-4"/></svg></button>`;
      const maximum = Math.max(0, ...items.map(row => row.count));
      const maximumLabel = maximum.toLocaleString("vi-VN");
      const barLegend = maximum ? `<span class="frequency-bar-legend"><span><i class="frequency-max-key" aria-hidden="true"></i>Mốc cao nhất: ${maximumLabel} lượt</span><span>% trên tổng lượt</span></span>` : '<span class="frequency-bar-legend">Chưa có lượt xuất hiện</span>';
      const rows = items.map(row => {
        const percentage = group.totalOccurrences ? row.count * 100 / group.totalOccurrences : 0;
        const share = percentage.toFixed(2) + "%";
        const width = maximum ? row.count * 80 / maximum : 0;
        const order = marks.indexOf(row.number) + 1;
        const wasLatest = latestNumbers.has(row.number);
        const delayLabel = row.delayLowerBound ? `Chưa xuất hiện trong ${row.currentDelay.toLocaleString("vi-VN")} kỳ đang chọn; độ trễ ít nhất bằng số kỳ này.` : `${row.currentDelay.toLocaleString("vi-VN")} kỳ liên tiếp chưa xuất hiện; vừa ra = 0.`;
        const averageLabel = row.averageDelay === null ? "Chưa đủ hai lần xuất hiện để tính trễ trung bình trong số kỳ đang chọn." : "Trung bình số kỳ không xuất hiện giữa hai lần ra trong số kỳ đang chọn; không tính hai đầu chưa đủ khoảng.";
        const pickLabel = `${order ? "Bỏ đánh dấu" : "Đánh dấu"} số ${row.number}${order ? `, thứ tự ${order}` : ""}`;
        return `<tr data-number="${row.number}" data-count="${row.count}">
          <th scope="row">${row.number}</th>
          <td class="frequency-bar-cell"><span class="frequency-track" title="${escapeHtml(`Số ${row.number}: ${row.count.toLocaleString("vi-VN")} lượt. ${maximum ? `Thanh so với mốc cao nhất ${maximumLabel} lượt (vạch vàng).` : "Chưa có lượt để so sánh thanh."} ${group.totalOccurrences ? `Tỷ trọng trên tổng lượt: ${row.count.toLocaleString("vi-VN")} / ${group.totalOccurrences.toLocaleString("vi-VN")} = ${share}.` : "Chưa có tổng lượt để tính tỷ trọng."}`)}" aria-hidden="true"><span class="frequency-fill" style="width:${width.toFixed(4)}%"></span>${maximum ? `<span class="frequency-max-marker" title="Mốc cao nhất: ${maximumLabel} lượt"></span>` : ""}</span></td>
          <td class="frequency-percent">${share}</td><td class="frequency-count">${row.count.toLocaleString("vi-VN")} lượt</td>
          <td class="frequency-delay" title="${escapeHtml(delayLabel)}">${row.delayLowerBound ? "≥" : ""}${row.currentDelay.toLocaleString("vi-VN")}</td>
          <td class="frequency-average-delay" title="${escapeHtml(averageLabel)}">${row.averageDelay === null ? "—" : row.averageDelay.toLocaleString("vi-VN", { maximumFractionDigits: 2 })}</td>
          <td class="frequency-streak">${renderAnalysisStreak(row, groupKey)}</td>
          <td class="frequency-marker-cell" data-draw-marker="current">${wasLatest ? `<span class="frequency-latest-mark" title="${escapeHtml(latestLabel)}" aria-label="Số ${row.number} xuất hiện ở ${escapeHtml(latestLabel)}">✓</span>` : ""}</td>
          <td class="frequency-marker-cell" data-draw-marker="previous">${previousNumbers.has(row.number) ? `<span class="frequency-previous-mark" title="${escapeHtml(previousLabel)}" aria-label="Số ${row.number} xuất hiện ở ${escapeHtml(previousLabel)}">✓</span>` : ""}</td>
          <td class="frequency-marker-cell"><button type="button" class="frequency-pick${order ? " is-picked" : ""}" data-frequency-pick="${row.number}" data-pick-group="${groupKey}" aria-pressed="${order > 0}" aria-label="${escapeHtml(pickLabel)}" title="${escapeHtml(pickLabel)}">${order || ""}</button></td>
        </tr>`;
      }).join("");
      return `<div class="frequency-table-wrap" role="region" tabindex="0" aria-label="${title}. Có thể cuộn ngang để xem đủ cột."><table class="frequency-table${special ? " is-special" : ""}" data-frequency-group="${special ? "special" : "main"}" aria-label="${title}">
        <colgroup><col class="frequency-number-col"><col><col class="frequency-percent-col"><col class="frequency-count-col"><col class="frequency-delay-col"><col class="frequency-delay-col"><col class="frequency-streak-col"><col class="frequency-marker-col"><col class="frequency-marker-col"><col class="frequency-marker-col"></colgroup>
        <thead><tr><th scope="col" aria-sort="${streakSort || metricSort ? "none" : sort === "number" ? "ascending" : "other"}"><div class="frequency-number-heading"><span>Bộ số</span>${sortButton}</div></th><th scope="colgroup" colspan="3">${title}${barLegend}</th><th scope="col" class="frequency-delay-heading" aria-sort="${metricSort === "currentDelay" ? "descending" : "none"}" title="Số kỳ liên tiếp chưa xuất hiện trong số kỳ đang chọn. Vừa ra = 0; ≥N nếu chưa thấy trong N kỳ.">${metricButton("currentDelay", "Độ Trễ")}</th><th scope="col" class="frequency-delay-heading" aria-sort="${metricSort === "averageDelay" ? "descending" : "none"}" title="Trung bình số kỳ không xuất hiện giữa hai lần ra trong số kỳ đang chọn. Cần ít nhất hai lần ra.">${metricButton("averageDelay", "Trễ Trung Bình")}</th><th scope="col" class="frequency-streak-heading" aria-sort="${streakSort ? "descending" : "none"}" title="Đỏ: đạt ngưỡng trễ / TB. Xanh lá: còn một kỳ chưa ra sẽ đạt đỏ. Xám: chuỗi đỏ vừa mất vì số đã ra ở kỳ hiện tại. Thiếu dữ liệu để trống.">${streakButton}</th><th scope="col" class="frequency-marker-heading" title="${escapeHtml(latestLabel)}">Hiện Tại</th><th scope="col" class="frequency-marker-heading" title="${escapeHtml(previousLabel)}">Kỳ Trước</th><th scope="col" class="frequency-marker-heading" title="Đánh dấu theo thứ tự bạn chọn">Chọn</th></tr></thead><tbody>${rows}</tbody>${renderAnalysisSummary(group, special)}
      </table></div>`;
    }

    function buildAnalysisTickets(type, selectedMain, selectedSpecial, size, mode = "normal") {
      const pools = getAnalysisTicketPools(type, selectedMain, selectedSpecial, size, mode);
      if (!pools) return [];
      const { cfg, main, special } = pools;
      const used = new Map(), usedSpecial = new Map(), pairs = new Map(), seen = new Set(), tickets = [], base = [];
      const pairKey = (a, b) => a < b ? a + ":" + b : b + ":" + a;
      // Bound enumeration even for 1,000 three-digit numbers; greedy candidates cover the rest.
      const enumerate = (start, chosen) => {
        if (base.length >= 256) return;
        if (chosen.length === size) { base.push([...chosen]); return; }
        for (let i = start; i <= main.length - (size - chosen.length) && base.length < 256; i++) {
          chosen.push(main[i]); enumerate(i + 1, chosen); chosen.pop();
        }
      };
      enumerate(0, []);
      for (let round = 0; round < 5; round++) {
        let best = null, bestScore = null;
        const consider = (numbers, extra) => {
          if (numbers.length !== size || (type === "LOTO_6_55" && numbers.includes(extra))) return;
          const ordered = [...numbers].sort((a, b) => Number(a) - Number(b));
          const key = ordered.join(",") + "|" + extra;
          if (seen.has(key)) return;
          let pairHits = 0;
          for (let i = 0; i < ordered.length; i++) for (let j = i + 1; j < ordered.length; j++) pairHits += pairs.get(pairKey(ordered[i], ordered[j])) || 0;
          const overlap = Math.max(0, ...tickets.map(ticket => ordered.filter(n => ticket.main.includes(n)).length));
          const score = [ordered.filter(n => !used.has(n)).length, extra && !usedSpecial.has(extra) ? 1 : 0,
            -overlap, -pairHits, -ordered.reduce((sum, n) => sum + (used.get(n) || 0), 0), -(usedSpecial.get(extra) || 0)];
          const different = bestScore ? score.findIndex((value, i) => value !== bestScore[i]) : -1;
          if (!bestScore || (different >= 0 && score[different] > bestScore[different])) {
            best = { main: ordered, special: extra, key }; bestScore = score;
          }
        };
        for (const extra of special) {
          for (const numbers of base) consider(numbers, extra);
          for (let shift = 0; shift < Math.min(16, main.length); shift++) {
            const chosen = [], available = main.filter(n => type !== "LOTO_6_55" || n !== extra);
            if (available.length < size) continue;
            while (chosen.length < size) {
              let next = "", nextScore = null;
              for (let i = 0; i < available.length; i++) {
                const n = available[i];
                if (chosen.includes(n)) continue;
                const score = [(used.get(n) || 0), chosen.reduce((sum, other) => sum + (pairs.get(pairKey(n, other)) || 0), 0),
                  (i - shift + available.length) % available.length];
                const different = nextScore ? score.findIndex((value, at) => value !== nextScore[at]) : -1;
                if (!nextScore || (different >= 0 && score[different] < nextScore[different])) { next = n; nextScore = score; }
              }
              chosen.push(next);
            }
            consider(chosen, extra);
          }
        }
        if (!best) break;
        seen.add(best.key);
        tickets.push({ main: best.main, special: best.special });
        best.main.forEach(n => used.set(n, (used.get(n) || 0) + 1));
        if (best.special) usedSpecial.set(best.special, (usedSpecial.get(best.special) || 0) + 1);
        for (let i = 0; i < best.main.length; i++) for (let j = i + 1; j < best.main.length; j++) {
          const key = pairKey(best.main[i], best.main[j]); pairs.set(key, (pairs.get(key) || 0) + 1);
        }
      }
      return tickets;
    }

    function getAnalysisTicketPools(type, selectedMain, selectedSpecial, size, mode = "normal") {
      const cfg = TYPES[type], bao = mode === "bao";
      if (!cfg || !["normal", "bao"].includes(mode) || !Number.isInteger(size) ||
        (bao ? !getPredictBaoLevels(type).includes(size) : size < 1 || size > (cfg.keno ? 10 : cfg.mainCount) || (!cfg.keno && size !== cfg.mainCount))) return null;
      // Power Bao consists only of its main-number parent, as in the existing Bao rules.
      const usesSpecial = cfg.hasSpecial && (!bao || type === "LOTO_5_35");
      const main = [...new Set(selectedMain)], special = usesSpecial ? [...new Set(selectedSpecial)] : [""];
      const valid = (number, min, max) => typeof number === "string" && /^\d+$/.test(number) &&
        Number(number) >= min && Number(number) <= max && String(Number(number)).padStart(cfg.threeDigit ? 3 : 2, "0") === number;
      if (main.length < size || !special.length || main.some(n => !valid(n, cfg.mainMin, cfg.mainMax)) ||
        (usesSpecial && special.some(n => !valid(n, cfg.specialMin, cfg.specialMax)))) return null;
      return { type, cfg, main, special, size, mode };
    }

    function analysisChoose(n, k) {
      if (k < 0 || n < k) return 0n;
      k = Math.min(k, n - k);
      let value = 1n;
      for (let i = 1; i <= k; i++) value = value * BigInt(n - k + i) / BigInt(i);
      return value;
    }

    function getAnalysisTicketCapacity(type, main, special, size, mode = "normal") {
      const pools = getAnalysisTicketPools(type, main, special, size, mode);
      if (!pools) return 0n;
      return pools.special.reduce((sum, extra) => sum + analysisChoose(pools.main.length - (type === "LOTO_6_55" && pools.main.includes(extra) ? 1 : 0), size), 0n);
    }

    function analysisCombinationRank(indices, n) {
      let rank = 0n, start = 0;
      indices.forEach((index, i) => {
        for (let j = start; j < index; j++) rank += analysisChoose(n - j - 1, indices.length - i - 1);
        start = index + 1;
      });
      return rank;
    }

    function analysisCombinationAt(pool, size, rank) {
      const chosen = [];
      for (let i = 0; i < pool.length && chosen.length < size; i++) {
        const count = analysisChoose(pool.length - i - 1, size - chosen.length - 1);
        if (rank < count) chosen.push(pool[i]);
        else rank -= count;
      }
      return chosen.sort((a, b) => Number(a) - Number(b));
    }

    function createAnalysisPredictionPlan(type, main, special, size, requested, mode = "normal") {
      const pools = getAnalysisTicketPools(type, main, special, size, mode);
      if (!pools || !/^\d+$/.test(String(requested))) return null;
      const count = BigInt(requested), capacity = getAnalysisTicketCapacity(type, main, special, size, mode);
      if (count < 1n || count > capacity) return null;
      let start = 0n;
      const groups = pools.special.map(extra => {
        const numbers = pools.main.filter(n => type !== "LOTO_6_55" || n !== extra);
        const ways = analysisChoose(numbers.length, size), group = { extra, numbers, start, ways };
        start += ways;
        return group;
      }).filter(group => group.ways > 0n);
      const seeds = buildAnalysisTickets(type, main, special, size, mode).slice(0, Number(count < 5n ? count : 5n));
      // A coprime stride visits every valid combination once, without enumerating the space.
      const gcd = (a, b) => { while (b) [a, b] = [b, a % b]; return a; };
      let step = capacity * 618033988n / 1000000000n || 1n;
      while (gcd(step, capacity) !== 1n) step++;
      let a = step, b = capacity, x = 1n, y = 0n;
      while (b) { const q = a / b; [a, b] = [b, a - q * b]; [x, y] = [y, x - q * y]; }
      const inverse = (x % capacity + capacity) % capacity;
      const excluded = seeds.map(ticket => {
        const group = groups.find(group => group.extra === ticket.special);
        const indices = ticket.main.map(n => group.numbers.indexOf(n)).sort((a, b) => a - b);
        const rank = group.start + analysisCombinationRank(indices, group.numbers.length);
        return rank * inverse % capacity;
      }).sort((a, b) => a < b ? -1 : a > b ? 1 : 0);
      return { count, capacity, groups, size, mode, seeds, step, excluded };
    }

    function getAnalysisTicketPage(plan, offset = 0n, limit = 6) {
      const tickets = [];
      offset = BigInt(offset);
      const end = offset + BigInt(limit) < plan.count ? offset + BigInt(limit) : plan.count;
      for (let index = offset; index < end; index++) {
        if (index < BigInt(plan.seeds.length)) { tickets.push(plan.seeds[Number(index)]); continue; }
        let position = index - BigInt(plan.seeds.length);
        for (const omitted of plan.excluded) { if (omitted > position) break; position++; }
        const rank = position * plan.step % plan.capacity;
        const group = plan.groups.find(group => rank >= group.start && rank < group.start + group.ways);
        tickets.push({ main: analysisCombinationAt(group.numbers, plan.size, rank - group.start), special: group.extra });
      }
      return tickets;
    }

    function getAnalysisPredictionSelection() {
      const type = normalizeAnalysisType(analysisState.type), cfg = TYPES[type];
      const main = getAnalysisMarks(), special = cfg.hasSpecial ? getAnalysisMarks(true) : [];
      const baoLevels = getPredictBaoLevels(type);
      const mode = baoLevels.length && analysisState.predictionMode === "bao" ? "bao" : "normal";
      const size = mode === "bao" ? (baoLevels.includes(analysisState.predictionBaoLevel) ? analysisState.predictionBaoLevel : baoLevels.find(n => n > cfg.mainCount))
        : cfg.keno ? analysisState.predictionKenoSize : cfg.mainCount;
      const usesSpecial = cfg.hasSpecial && (mode === "normal" || type === "LOTO_5_35");
      const needs = [];
      if (main.length < size) needs.push(`thêm ${size - main.length} số chính`);
      if (usesSpecial && !special.length) needs.push("ít nhất 1 số đặc biệt");
      let message = needs.length ? `Chọn ${needs.join(" và ")} để dự đoán.` : "";
      if (!message && mode === "normal" && type === "LOTO_6_55" && !special.some(n => main.filter(number => number !== n).length >= size)) {
        message = "Chọn thêm số chính hoặc số đặc biệt khác: mỗi vé Power cần 6 số chính khác số đặc biệt.";
      }
      return { type, cfg, main, special, size, mode, baoLevels, usesSpecial,
        capacity: getAnalysisTicketCapacity(type, main, special, size, mode), message,
        key: JSON.stringify([analysisMarksStorageKey(), type, main, special, size, mode]) };
    }

    function clearAnalysisPrediction() {
      analysisState.predictionKey = "";
      analysisState.predictionTickets = [];
      analysisState.predictionPlan = null;
      analysisState.predictionPage = 0;
      analysisState.predictionCountOpen = false;
    }

    function renderAnalysisSelectedPrediction() {
      const selection = getAnalysisPredictionSelection(), { cfg, main, special, size, mode, baoLevels, usesSpecial, capacity, message, key } = selection;
      if (analysisState.predictionKey && analysisState.predictionKey !== key) clearAnalysisPrediction();
      const plan = analysisState.predictionKey === key ? analysisState.predictionPlan : null;
      const tickets = plan ? analysisState.predictionTickets : [];
      const page = analysisState.predictionPage, offset = BigInt(page) * 6n;
      const pages = plan ? (plan.count + 5n) / 6n : 0n;
      const chips = (numbers, extra = false) => numbers.length ? numbers.map((n, i) => `<span class="frequency-selected-number${extra ? " is-special" : ""}"><small>${i + 1}</small>${n}</span>`).join("") : '<span class="frequency-selection-empty">Chưa chọn số</span>';
      const balls = (numbers, extra = false) => numbers.map(n => `<span class="frequency-ticket-number${extra ? " is-special" : ""}">${n}</span>`).join("");
      const covered = new Set(tickets.flatMap(ticket => ticket.main)).size;
      const coveredSpecial = new Set(tickets.map(ticket => ticket.special).filter(Boolean)).size;
      return `<section class="frequency-selection" aria-labelledby="analysisSelectionTitle">
        <div class="frequency-selection-head"><h3 id="analysisSelectionTitle">Bộ số bạn đã chọn</h3><span id="analysisPredictionCapacity" data-capacity="${capacity}">Tối đa ${capacity.toLocaleString("vi-VN")} bộ</span></div>
        <div class="frequency-selected-group"><h4>Số chính <span>${main.length}</span></h4><div class="frequency-selected-numbers" data-selected-group="main">${chips(main)}</div></div>
        ${cfg.hasSpecial ? `<div class="frequency-selected-group"><h4>Số đặc biệt <span>${special.length}</span></h4><div class="frequency-selected-numbers" data-selected-group="special">${chips(special, true)}</div></div>` : ""}
        <p class="frequency-selection-description">Phối hợp từ bộ số bạn chọn, ưu tiên phủ số và giảm trùng lặp giữa các vé.</p>
        <div class="frequency-predict-actions">${baoLevels.length ? `<label class="frequency-field">Loại vé<select id="analysisPredictionMode"><option value="normal"${mode === "normal" ? " selected" : ""}>Vé thường</option><option value="bao"${mode === "bao" ? " selected" : ""}>Bao</option></select></label>` : ""}${mode === "bao" ? `<label class="frequency-field">Cấp Bao<select id="analysisPredictionBaoLevel">${baoLevels.map(level => `<option value="${level}"${size === level ? " selected" : ""}>Bao ${level}</option>`).join("")}</select></label>` : ""}${cfg.keno ? `<label class="frequency-field">Bậc Keno<select id="analysisPredictionKenoSize">${Array.from({ length: 10 }, (_, i) => `<option value="${i + 1}"${size === i + 1 ? " selected" : ""}>Bậc ${i + 1}</option>`).join("")}</select></label>` : ""}<button type="button" id="analysisPredictSelectedBtn"${message ? " disabled" : ""}>Dự Đoán<span aria-hidden="true"> →</span></button></div>
        ${mode === "bao" ? `<p class="frequency-selection-help">Bao ${size} · ${size} số chính${usesSpecial ? " + 1 số đặc biệt" : ""}.${size < cfg.mainCount ? ` Đây là bộ số cố định; vé con ghép thêm 1 số còn lại trong miền ${cfg.mainMin}–${cfg.mainMax} theo quy tắc Bao.` : ""}${selection.type === "LOTO_6_55" ? " Số đặc biệt đã chọn không dùng cho Bao Power." : ""}</p>` : ""}
        ${analysisState.predictionCountOpen && !message ? `<form id="analysisPredictionCountForm" class="frequency-count-form"><label class="frequency-field">Số bộ dự đoán<input id="analysisPredictionCountInput" type="text" inputmode="numeric" maxlength="32" pattern="[0-9]+" required autocomplete="off" value="${escapeHtml(analysisState.predictionCount)}" aria-describedby="analysisPredictionCountHint"></label><p id="analysisPredictionCountHint">Từ 1 đến ${capacity.toLocaleString("vi-VN")} bộ khác nhau.</p><div class="frequency-count-actions"><button id="analysisPredictionCountCancel" type="button">Hủy</button><button id="analysisPredictionCountConfirm" type="submit">Tạo dự đoán</button></div></form>` : ""}
        ${message ? `<p class="frequency-selection-help">${escapeHtml(message)}</p>` : ""}
        <div class="frequency-ticket-results" aria-live="polite" aria-atomic="true">${tickets.length ? `<div class="frequency-ticket-summary">${plan.count.toLocaleString("vi-VN")} bộ · ${pages > 1n ? "Trang này phủ" : "Phủ"} ${covered}/${main.length} số chính${usesSpecial ? ` · ${coveredSpecial}/${special.length} số ĐB` : ""}</div>${tickets.map((ticket, i) => `<div class="frequency-ticket"><span class="frequency-ticket-label">${mode === "bao" ? `Bao ${size}` : "Vé thường"} · Bộ ${(offset + BigInt(i) + 1n).toLocaleString("vi-VN").padStart(2, "0")}</span><div class="frequency-ticket-balls">${balls(ticket.main)}${ticket.special ? `<span class="frequency-ticket-special-label">ĐB</span>${balls([ticket.special], true)}` : ""}</div></div>`).join("")}${pages > 1n ? `<nav class="frequency-ticket-pages" aria-label="Trang bộ dự đoán"><button type="button" data-analysis-ticket-page="first" aria-label="Trang đầu"${page === 0 ? " disabled" : ""}>«</button><button type="button" data-analysis-ticket-page="prev" aria-label="Trang trước"${page === 0 ? " disabled" : ""}>‹</button><span>Trang ${(BigInt(page) + 1n).toLocaleString("vi-VN")} / ${pages.toLocaleString("vi-VN")}</span><button type="button" data-analysis-ticket-page="next" aria-label="Trang sau"${BigInt(page) + 1n === pages ? " disabled" : ""}>›</button><button type="button" data-analysis-ticket-page="last" aria-label="Trang cuối"${BigInt(page) + 1n === pages ? " disabled" : ""}>»</button></nav>` : ""}` : ""}</div>
      </section>`;
    }

    function renderAnalysisSummary(group, special = false) {
      const counts = { red: 0, green: 0, gray: 0, empty: 0, selected: 0 };
      const marks = new Set(getAnalysisMarks(special));
      for (const row of group.items) {
        const state = getAnalysisStreakState(row);
        if (state) counts[state.color]++;
        else counts.empty++;
        if (marks.has(row.number)) counts.selected++;
      }
      const labels = { red: "Đỏ", green: "Xanh", gray: "Xám" };
      const flames = ["red", "green", "gray"].map(key => `<span class="frequency-summary-${key}" title="${counts[key].toLocaleString("vi-VN")} ô chuỗi ${labels[key].toLocaleLowerCase("vi-VN")}">${renderAnalysisFlameSvg(key, `frequency-summary-fire-${special ? "special" : "main"}-${key}`)}${labels[key]} <strong data-summary-count="${key}">${counts[key].toLocaleString("vi-VN")}</strong></span>`).join("");
      return `<tfoot><tr class="frequency-summary-row" data-summary-group="${special ? "special" : "main"}">
        <th scope="row">Tổng</th><td colspan="8" title="Mỗi ô có lửa tính 1 chuỗi; ô không có lửa được tính là trống"><div class="frequency-summary-counts">${flames}<span class="frequency-summary-empty" title="${counts.empty.toLocaleString("vi-VN")} ô Chuỗi trống, không có lửa đỏ, xanh hoặc xám"><svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"><rect x="3" y="3" width="10" height="10" rx="2"/></svg>Trống <strong data-summary-count="empty">${counts.empty.toLocaleString("vi-VN")}</strong></span></div></td>
        <td class="frequency-summary-selected" data-summary-count="selected" title="${counts.selected.toLocaleString("vi-VN")} ô số đã tích chọn"><span class="frequency-summary-picked"><svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 8 3 3 7-7"/></svg>${counts.selected.toLocaleString("vi-VN")}</span></td>
      </tr></tfoot>`;
    }

    function renderAnalysis(payload = analysisState.lastPayload) {
      const out = document.getElementById("analysisFrequencyOut");
      if (!out) return;
      initAnalysisPanel();
      const status = document.getElementById("analysisStatus");
      status.hidden = !analysisState.error;
      status.textContent = analysisState.error;
      out.setAttribute("aria-busy", String(analysisState.loading));
      document.getElementById("analysisUpdatedAt").textContent = payload?.generatedAt ? formatStatsV2UpdatedAt(payload.generatedAt).replace(/^Cập nhật /, "Cập nhật lúc ") : analysisState.loading ? "Đang tải dữ liệu…" : "Chưa có dữ liệu";
      const scope = document.getElementById("analysisScope");
      scope.textContent = "";
      syncAnalysisDateNavigation(payload);
      if (!payload) {
        out.innerHTML = analysisState.error ? "" : `<div class="frequency-empty">${analysisState.loading ? "Đang tổng hợp tần suất xuất hiện…" : analysisState.drawPreset === "custom" ? "Nhập số kỳ cần phân tích, rồi bấm Cập nhật." : "Chọn loại xổ số và số kỳ, rồi bấm Cập nhật."}</div>`;
        return;
      }
      const drawLabel = payload.totalDraws < payload.requestedDrawCount
        ? `${payload.totalDraws.toLocaleString("vi-VN")} / ${payload.requestedDrawCount.toLocaleString("vi-VN")}`
        : payload.totalDraws.toLocaleString("vi-VN");
      scope.textContent = ["all", "dates"].includes(analysisState.drawPreset)
        ? ""
        : `${drawLabel} kỳ gần nhất • `;
      const dates = document.createElement("button");
      dates.type = "button";
      dates.dataset.analysisEditDates = "";
      dates.title = "Chỉnh sửa khoảng ngày phân tích";
      dates.setAttribute("aria-label", `Chỉnh sửa khoảng ngày ${payload.fromDate} đến ${payload.toDate}`);
      dates.setAttribute("aria-controls", "analysisDateForm");
      dates.setAttribute("aria-expanded", String(!document.getElementById("analysisDateForm").hidden));
      dates.className = "frequency-scope-dates";
      const rangeEndpoint = (date, time, label) => `<span class="frequency-range-endpoint" data-label="${label}"><span class="frequency-range-date">${escapeHtml(date)}</span>${isAnalysis535() ? ` <span class="frequency-range-time">${escapeHtml(time)}</span>` : ""}</span>`;
      dates.innerHTML = `${rangeEndpoint(payload.fromDate, payload.fromTime, "Từ kỳ")} <span class="frequency-range-divider" aria-hidden="true">→</span> ${rangeEndpoint(payload.toDate, payload.toTime, "Đến kỳ ✎")}`;
      scope.append(dates);
      const { main, special } = payload.data;
      const balancedTables = special.supported && main.items.length === special.items.length;
      out.innerHTML = `<div class="frequency-tables has-side${special.supported ? " has-special" : ""}${balancedTables ? " has-balanced-tables" : ""}">${renderFrequencyTable(main, false, payload.latestDraw, payload.previousDraw)}<div class="frequency-side">${special.supported ? renderFrequencyTable(special, true, payload.latestDraw, payload.previousDraw) : ""}${renderAnalysisSelectedPrediction()}</div></div>`;
      out.querySelector("#analysisPredictSelectedBtn")?.addEventListener("click", () => {
        const selection = getAnalysisPredictionSelection();
        if (selection.message) return;
        const prior = /^\d+$/.test(analysisState.predictionCount) && BigInt(analysisState.predictionCount) > 0n ? BigInt(analysisState.predictionCount) : 5n;
        analysisState.predictionCount = String(prior > selection.capacity ? selection.capacity : prior);
        analysisState.predictionCountOpen = true;
        renderAnalysis();
        const input = out.querySelector("#analysisPredictionCountInput"); input?.focus(); input?.select();
      });
      out.querySelector("#analysisPredictionCountInput")?.addEventListener("input", event => {
        const input = event.target, capacity = getAnalysisPredictionSelection().capacity;
        if (/^\d+$/.test(input.value) && BigInt(input.value) > capacity) input.value = String(capacity);
        analysisState.predictionCount = input.value;
        input.setCustomValidity("");
      });
      out.querySelector("#analysisPredictionCountCancel")?.addEventListener("click", () => {
        analysisState.predictionCountOpen = false;
        renderAnalysis();
        out.querySelector("#analysisPredictSelectedBtn")?.focus({ preventScroll: true });
      });
      out.querySelector("#analysisPredictionCountForm")?.addEventListener("submit", event => {
        event.preventDefault();
        const selection = getAnalysisPredictionSelection(), input = out.querySelector("#analysisPredictionCountInput");
        if (selection.message || !input) return;
        const plan = createAnalysisPredictionPlan(selection.type, selection.main, selection.special, selection.size, input.value, selection.mode);
        if (!plan) { input.setCustomValidity(`Nhập số bộ từ 1 đến ${selection.capacity.toLocaleString("vi-VN")}.`); input.reportValidity(); return; }
        analysisState.predictionPlan = plan;
        analysisState.predictionCount = input.value;
        analysisState.predictionPage = 0;
        analysisState.predictionTickets = getAnalysisTicketPage(plan);
        analysisState.predictionKey = selection.key;
        analysisState.predictionCountOpen = false;
        renderAnalysis();
        out.querySelector("#analysisPredictSelectedBtn")?.focus({ preventScroll: true });
      });
      out.querySelectorAll("[data-analysis-ticket-page]").forEach(button => button.addEventListener("click", () => {
        const plan = analysisState.predictionPlan;
        if (!plan || analysisState.predictionKey !== getAnalysisPredictionSelection().key) return;
        const last = Number((plan.count - 1n) / 6n), action = button.dataset.analysisTicketPage;
        analysisState.predictionPage = action === "first" ? 0 : action === "last" ? last
          : Math.max(0, Math.min(last, analysisState.predictionPage + (action === "next" ? 1 : -1)));
        analysisState.predictionTickets = getAnalysisTicketPage(plan, BigInt(analysisState.predictionPage) * 6n);
        renderAnalysis();
        out.querySelector(`[data-analysis-ticket-page="${action}"]`)?.focus({ preventScroll: true });
      }));
      ["analysisPredictionMode", "analysisPredictionBaoLevel"].forEach(id => out.querySelector(`#${id}`)?.addEventListener("change", event => {
        if (id === "analysisPredictionMode") analysisState.predictionMode = event.target.value === "bao" ? "bao" : "normal";
        else analysisState.predictionBaoLevel = Number(event.target.value);
        clearAnalysisPrediction();
        renderAnalysis();
        out.querySelector(`#${id}`)?.focus({ preventScroll: true });
      }));
      out.querySelector("#analysisPredictionKenoSize")?.addEventListener("change", event => {
        analysisState.predictionKenoSize = Math.max(1, Math.min(10, Number(event.target.value) || 5));
        clearAnalysisPrediction();
        renderAnalysis();
        out.querySelector("#analysisPredictionKenoSize")?.focus({ preventScroll: true });
      });
      out.querySelectorAll("[data-metric-sort]").forEach(button => button.addEventListener("click", () => {
        const groupKey = button.dataset.metricGroup, metric = button.dataset.metricSort;
        if (!["currentDelay", "averageDelay"].includes(metric)) return;
        const stateKey = groupKey === "special" ? "sortMetricSpecial" : "sortMetricMain";
        analysisState[stateKey] = analysisState[stateKey] === metric ? "" : metric;
        analysisState[groupKey === "special" ? "sortStreakSpecial" : "sortStreakMain"] = false;
        renderAnalysis();
        out.querySelector(`[data-metric-group="${groupKey}"][data-metric-sort="${metric}"]`)?.focus({ preventScroll: true });
      }));
      out.querySelectorAll("[data-streak-sort]").forEach(button => button.addEventListener("click", () => {
        const groupKey = button.dataset.streakSort;
        const stateKey = groupKey === "special" ? "sortStreakSpecial" : "sortStreakMain";
        analysisState[stateKey] = !analysisState[stateKey];
        analysisState[groupKey === "special" ? "sortMetricSpecial" : "sortMetricMain"] = "";
        renderAnalysis();
        out.querySelector(`[data-streak-sort="${groupKey}"]`)?.focus({ preventScroll: true });
      }));
      out.querySelectorAll("[data-frequency-sort]").forEach(button => {
        button.addEventListener("click", () => {
          const groupKey = button.dataset.sortGroup;
          analysisState[groupKey === "special" ? "sortSpecial" : "sortMain"] = button.dataset.frequencySort;
          analysisState[groupKey === "special" ? "sortStreakSpecial" : "sortStreakMain"] = false;
          analysisState[groupKey === "special" ? "sortMetricSpecial" : "sortMetricMain"] = "";
          saveAnalysisUiState();
          renderAnalysis();
          out.querySelector(`[data-frequency-group="${groupKey}"] .frequency-sort-toggle`)?.focus({ preventScroll: true });
        });
      });
      out.querySelectorAll("[data-frequency-pick]").forEach(button => {
        button.addEventListener("click", () => {
          const number = button.dataset.frequencyPick;
          const groupKey = button.dataset.pickGroup;
          const marks = getAnalysisMarks(groupKey === "special");
          const index = marks.indexOf(number);
          if (index >= 0) marks.splice(index, 1);
          else marks.push(number);
          clearAnalysisPrediction();
          saveAnalysisMarks();
          renderAnalysis();
          out.querySelector(`[data-pick-group="${groupKey}"][data-frequency-pick="${number}"]`)?.focus({ preventScroll: true });
        });
      });
    }

    function resetAnalysisSession() {
      closeAnalysisDateEditor();
      hideAnalysisCaptureToast();
      analysisState.captureSerial++;
      analysisState.captureBusy = false;
      const captureStatus = document.getElementById("analysisCaptureStatus");
      if (captureStatus) { captureStatus.hidden = true; captureStatus.textContent = ""; }
      analysisState.refreshToken++;
      analysisState.controller?.abort();
      analysisState.controller = null;
      analysisState.loading = false;
      analysisState.lastPayload = null;
      analysisState.error = "";
      analysisState.availableDrawsByType = {};
      analysisState.availableDatesByType = {};
      analysisState.marksByType = {};
      analysisState.marksOwner = "";
      analysisState.sortStreakMain = false;
      analysisState.sortStreakSpecial = false;
      analysisState.sortMetricMain = "";
      analysisState.sortMetricSpecial = "";
      clearAnalysisPrediction();
      analysisState.predictionCount = "5";
      analysisState.predictionKenoSize = 5;
      analysisState.predictionMode = "normal";
      analysisState.predictionBaoLevel = 0;
      renderAnalysis(null);
    }

    function refreshAnalysisAfterLiveUpdate() {
      if (!document.hidden && predictPageModeValue === PREDICTION_MODE_ANALYSIS) void loadAnalysis();
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
            <div class="chart-stats-summary-meta">Phân bố theo nhóm số</div>
          </article>
          <article class="chart-stats-summary-card">
            <div class="chart-stats-summary-label">Kỳ đã chọn</div>
            <div class="chart-stats-summary-value">${escapeHtml(requestedInfo.mode === "all" ? "All" : formatLiveSyncCount(requestedInfo.requestedCount))}</div>
            <div class="chart-stats-summary-meta">${escapeHtml(requestedInfo.mode === "all" ? "Toàn bộ dữ liệu" : "Theo bộ lọc hiện tại")}</div>
          </article>
          <article class="chart-stats-summary-card">
            <div class="chart-stats-summary-label">Kỳ sử dụng</div>
            <div class="chart-stats-summary-value">${escapeHtml(formatLiveSyncCount(requestedInfo.actualUsedCount))}</div>
            <div class="chart-stats-summary-meta">Dữ liệu hợp lệ gần nhất</div>
          </article>
          <article class="chart-stats-summary-card">
            <div class="chart-stats-summary-label">Lượt số phân tích</div>
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
            <div class="chart-stats-block-title">Tần suất theo nhóm</div>
            <div class="chart-stats-block-meta">${escapeHtml(`${meta.label} • ${titleLabel}`)}</div>
          </div>
          <div class="chart-stats-frequency-chart">
            ${rows.map(item => `
              <article class="chart-stats-frequency-item">
                <div class="chart-stats-frequency-value">${escapeHtml(formatLiveSyncCount(item.count))}</div>
                <div class="chart-stats-frequency-bar-shell">
                  <div class="chart-stats-frequency-bar" style="--chart-bar-size:${(Number(item.count || 0) > 0 ? Math.max(6, Number(item.frequencyRatio || 0) * 100) : 0).toFixed(2)}%; --chart-bar-color:${escapeHtml(item.color)}; --chart-bar-opacity:${(0.82 + Math.max(0, Math.min(1, Number(item.frequencyRatio || 0))) * 0.18).toFixed(3)}; --chart-bar-bright:${(0.96 + Math.max(0, Math.min(1, Number(item.frequencyRatio || 0))) * 0.1).toFixed(3)}; --chart-bar-sat:${(1.02 + Math.max(0, Math.min(1, Number(item.frequencyRatio || 0))) * 0.08).toFixed(3)};"></div>
                </div>
                <div class="chart-stats-frequency-label">${escapeHtml(item.label)}</div>
                <div class="chart-stats-frequency-percent">${escapeHtml(formatChartStatsPercent(item.percent))}</div>
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
              <div class="chart-stats-block-title">Tỷ trọng theo nhóm</div>
              <div class="chart-stats-block-meta">${escapeHtml(`${formatLiveSyncCount(totalHits)} lượt số`)}</div>
            </div>
            <div class="chart-stats-donut-empty">Chưa có đủ dữ liệu để dựng donut tỷ trọng %.</div>
          </section>
        `;
      }
      const separatorInnerRadius = radius - (stroke / 2) - 0.5;
      const separatorOuterRadius = radius + (stroke / 2) + 0.5;
      let separatorAccumulated = 0;
      const donutSeparatorsHtml = activeRows.map(item => {
        const angle = (separatorAccumulated / circumference) * Math.PI * 2;
        const x1 = 90 + Math.cos(angle) * separatorInnerRadius;
        const y1 = 90 + Math.sin(angle) * separatorInnerRadius;
        const x2 = 90 + Math.cos(angle) * separatorOuterRadius;
        const y2 = 90 + Math.sin(angle) * separatorOuterRadius;
        separatorAccumulated += (Math.max(0, Number(item.percent || 0)) / 100) * circumference;
        return `<line class="chart-stats-donut-separator" x1="${x1.toFixed(3)}" y1="${y1.toFixed(3)}" x2="${x2.toFixed(3)}" y2="${y2.toFixed(3)}"></line>`;
      }).join("");
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
          style="--chart-bar-opacity:${(0.86 + Math.max(0, Math.min(1, percent / 100)) * 0.14).toFixed(3)}; --chart-bar-bright:${(0.98 + Math.max(0, Math.min(1, percent / 100)) * 0.08).toFixed(3)}; --chart-bar-sat:${(1.02 + Math.max(0, Math.min(1, percent / 100)) * 0.08).toFixed(3)};"
        />`;
      }).join("");
      return `
        <section class="chart-stats-block">
          <div class="chart-stats-block-head">
            <div class="chart-stats-block-title">Tỷ trọng theo nhóm</div>
            <div class="chart-stats-block-meta">${escapeHtml(`${meta.label} • ${titleLabel} • ${formatLiveSyncCount(totalHits)} lượt`)}</div>
          </div>
          <div class="chart-stats-donut-layout">
            <div class="chart-stats-donut-wrap">
              <svg class="chart-stats-donut-svg" viewBox="0 0 180 180" aria-hidden="true">
                <circle class="chart-stats-donut-track" cx="90" cy="90" r="${radius}" fill="none" stroke-width="${stroke}"></circle>
                <g class="chart-stats-donut-ring">${donutSegmentsHtml}</g>
                <g class="chart-stats-donut-separators">${donutSeparatorsHtml}</g>
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
          <div class="chart-stats-grid${chartBlocks.length === 1 ? " is-single" : ""}">
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

    function filterDashboardEntriesInRange(entries, startDate, endDate) {
      const startTime = startDate.getTime();
      const endTime = endDate.getTime();
      return (Array.isArray(entries) ? entries : []).filter(entry => {
        const currentTime = entry?.dayStart instanceof Date ? entry.dayStart.getTime() : NaN;
        return Number.isFinite(currentTime) && currentTime >= startTime && currentTime <= endTime;
      });
    }

    function buildDashboardSmoothPath(points) {
      if (!Array.isArray(points) || !points.length) return "";
      if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;
      let path = `M ${points[0].x} ${points[0].y}`;
      for (let index = 0; index < points.length - 1; index += 1) {
        const previous = points[index - 1] || points[index];
        const current = points[index];
        const next = points[index + 1];
        const following = points[index + 2] || next;
        const control1X = current.x + (next.x - previous.x) / 6;
        const control1Y = current.y + (next.y - previous.y) / 6;
        const control2X = next.x - (following.x - current.x) / 6;
        const control2Y = next.y - (following.y - current.y) / 6;
        path += ` C ${control1X} ${control1Y}, ${control2X} ${control2Y}, ${next.x} ${next.y}`;
      }
      return path;
    }

    function buildDashboardAreaPath(points, baseY) {
      if (!Array.isArray(points) || !points.length) return "";
      return `${buildDashboardSmoothPath(points)} L ${points.at(-1).x} ${baseY} L ${points[0].x} ${baseY} Z`;
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
      const entries = buildStatsEntriesForFeed(type, getLiveHistoryFeed(type))
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
      return filterDashboardEntriesByScope(entries);
    }

    function filterDashboardEntriesByScope(entries) {
      const safeEntries = Array.isArray(entries) ? entries : [];
      const preset = normalizeDashboardScopePreset(dashboardScopePreset);
      if (!safeEntries.length || preset === "all") return safeEntries;

      if (preset === "today") {
        const todayTime = floorDashboardDate(getSyncedNowDate()).getTime();
        return safeEntries.filter(entry => entry?.dayStart instanceof Date && entry.dayStart.getTime() === todayTime);
      }

      const count = normalizeDashboardScopeCount(dashboardScopeCount);
      if (normalizeDashboardScopeMode(dashboardScopeMode) === "draw") {
        return safeEntries.slice(-count);
      }

      const latestDay = safeEntries.at(-1)?.dayStart;
      if (!(latestDay instanceof Date) || Number.isNaN(latestDay.getTime())) return safeEntries;
      const startTime = shiftDashboardDate(latestDay, -(count - 1)).getTime();
      return safeEntries.filter(entry => entry?.dayStart instanceof Date && entry.dayStart.getTime() >= startTime);
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
      const normalizedMode = normalizeDashboardActivityView(mode);
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
      const feed = getLiveHistoryFeed(type);
      const formattedTime = String(latestEntry.draw?.time || feed?.latestTime || "").trim() || "--:--";
      const rawDrawId = String(latestEntry.ky || "").trim().replace(/^#+\s*/, "");
      const drawIdLabel = rawDrawId ? `#${rawDrawId}` : "--";
      return `
        <article class="lotto-dashboard-hero-shell" style="--dashboard-accent:${escapeHtml(meta.accent)}">
          <div class="lotto-dashboard-hero-copy">
            <div class="lotto-dashboard-hero-kicker">${escapeHtml(meta.label)}</div>
            <h3 class="lotto-dashboard-hero-title">Kỳ: ${escapeHtml(drawIdLabel)}</h3>
            <div class="lotto-dashboard-hero-meta">Ngày quay: ${escapeHtml(formattedDate)}</div>
            <div class="lotto-dashboard-hero-note">Thời gian quay: ${escapeHtml(formattedTime)}</div>
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

    function getDashboardScopeDisplay() {
      const mode = normalizeDashboardScopeMode(dashboardScopeMode);
      const preset = normalizeDashboardScopePreset(dashboardScopePreset);
      const modeLabel = mode === "draw" ? "Kỳ" : "Ngày";
      const rangeLabel = preset === "today"
        ? "Today"
        : preset === "all"
          ? "All"
          : formatDashboardInteger(normalizeDashboardScopeCount(dashboardScopeCount));
      return { mode, preset, modeLabel, rangeLabel };
    }

    function renderDashboardScopeFilter() {
      const summaryHost = document.getElementById("lottoDashboardScopeSummary");
      const countInput = document.getElementById("lottoDashboardScopeCount");
      const inputLabel = document.getElementById("lottoDashboardScopeInputLabel");
      const customPresetButton = document.getElementById("lottoDashboardScopeCustomPreset");
      const hintHost = document.getElementById("lottoDashboardScopeHint");
      const scope = getDashboardScopeDisplay();
      if (summaryHost) summaryHost.textContent = `${scope.modeLabel} · ${scope.rangeLabel}`;
      if (inputLabel) inputLabel.textContent = scope.mode === "draw" ? "Số kỳ" : "Số ngày";
      if (countInput) {
        countInput.placeholder = scope.mode === "draw" ? "Nhập số kỳ" : "Nhập số ngày";
        countInput.setAttribute("aria-label", countInput.placeholder);
        countInput.value = scope.preset === "custom" ? String(normalizeDashboardScopeCount(dashboardScopeCount)) : "";
      }
      if (customPresetButton) {
        const customCount = formatDashboardInteger(normalizeDashboardScopeCount(dashboardScopeCount));
        customPresetButton.textContent = `${customCount} ${scope.mode === "draw" ? "kỳ" : "ngày"}`;
        customPresetButton.title = `Hiển thị ${customCount} ${scope.mode === "draw" ? "kỳ gần nhất" : "ngày gần nhất"}`;
      }
      document.querySelectorAll("[data-dashboard-scope-mode]").forEach(button => {
        const isActive = normalizeDashboardScopeMode(button.dataset.dashboardScopeMode) === scope.mode;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-selected", isActive ? "true" : "false");
      });
      document.querySelectorAll("[data-dashboard-scope-preset]").forEach(button => {
        const isActive = normalizeDashboardScopePreset(button.dataset.dashboardScopePreset) === scope.preset;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
      if (hintHost) {
        hintHost.textContent = scope.preset === "today"
          ? "Chỉ hiển thị các kỳ quay trong hôm nay."
          : scope.preset === "all"
            ? `Đang hiển thị toàn bộ ${scope.mode === "draw" ? "kỳ" : "ngày"} có dữ liệu.`
            : `Hiển thị ${scope.rangeLabel} ${scope.mode === "draw" ? "kỳ gần nhất" : "ngày gần nhất"}.`;
      }
    }

    function getDashboardDistributionSubtitle(type, mode) {
      const meta = getDashboardTypeMeta(type);
      const normalizedMode = normalizeDashboardDistributionView(mode);
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
        { key: "very-hot", label: "Rất nóng", color: "#ff7a63", count: 0, items: [] },
        { key: "hot", label: "Nóng", color: "#ffb44d", count: 0, items: [] },
        { key: "warm", label: "Trung tính", color: "#7aa8ff", count: 0, items: [] },
        { key: "cold", label: "Lạnh", color: "#63d5ff", count: 0, items: [] },
        { key: "sleep", label: "Vắng", color: "#d7e2ff", count: 0, items: [] },
      ];
      sorted.forEach((item, index) => {
        const ratio = index / total;
        let bucketIndex = 4;
        if (ratio < 0.12) bucketIndex = 0;
        else if (ratio < 0.3) bucketIndex = 1;
        else if (ratio < 0.6) bucketIndex = 2;
        else if (ratio < 0.85) bucketIndex = 3;
        groups[bucketIndex].count += 1;
        groups[bucketIndex].items.push(item);
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
      const normalizedMode = normalizeDashboardDistributionView(mode);
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

    function renderDashboardTemperatureDetail(type, row) {
      if (!row) {
        return `
          <div id="lottoDashboardTemperatureDetail" class="lotto-dashboard-temperature-detail is-hint" aria-live="polite">
            <span class="lotto-dashboard-temperature-detail-icon" aria-hidden="true">◎</span>
            <span>Chọn một nhóm nhiệt để xem các bóng số thuộc nhóm đó.</span>
          </div>
        `;
      }
      const items = Array.isArray(row.items) ? row.items : [];
      const unitLabel = getDashboardFamily(type) === "threeDigit" ? "bộ số" : "bóng số";
      return `
        <section id="lottoDashboardTemperatureDetail" class="lotto-dashboard-temperature-detail" style="--dashboard-color:${escapeHtml(row.color)}" role="region" aria-label="Các số thuộc nhóm ${escapeHtml(row.label)}" aria-live="polite">
          <div class="lotto-dashboard-temperature-detail-head">
            <div>
              <div class="lotto-dashboard-temperature-detail-title">${escapeHtml(row.label)}</div>
              <div class="lotto-dashboard-temperature-detail-meta">${escapeHtml(`${formatDashboardInteger(items.length)} ${unitLabel} • xếp từ tần suất cao xuống thấp`)}</div>
            </div>
            <span class="lotto-dashboard-temperature-detail-count">${escapeHtml(row.countLabel || "")}</span>
          </div>
          <div class="lotto-dashboard-temperature-balls" role="list" aria-label="${escapeHtml(unitLabel)} thuộc nhóm ${escapeHtml(row.label)}">
            ${items.map(item => `
              <span
                class="lotto-dashboard-temperature-ball"
                role="listitem"
                title="${escapeHtml(`${item.label}: xuất hiện ${formatDashboardInteger(item.count)} lượt trong mẫu`)}"
              >${escapeHtml(item.label || formatPredictNumber(item.value, type))}</span>
            `).join("")}
          </div>
        </section>
      `;
    }

    function renderDashboardPieSegments(rows) {
      const safeRows = (Array.isArray(rows) ? rows : []).filter(row => Number(row.percent || 0) > 0);
      const radius = 88;
      let accumulatedPercent = 0;
      const pointAtAngle = angle => {
        const radians = (angle * Math.PI) / 180;
        return {
          x: 100 + (radius * Math.cos(radians)),
          y: 100 + (radius * Math.sin(radians)),
        };
      };
      return safeRows.map(row => {
        const percent = Math.max(0, Math.min(100, Number(row.percent || 0)));
        const startAngle = -90 + (accumulatedPercent * 3.6);
        const endAngle = startAngle + (percent * 3.6);
        accumulatedPercent += percent;
        const exactPercent = formatChartStatsPercent(percent);
        const roundedPercent = `${Math.round(percent)}%`;
        if (percent >= 99.999) {
          return `
            <g class="lotto-dashboard-pie-slice">
              <circle class="lotto-dashboard-pie-segment" cx="100" cy="100" r="${radius}" fill="${escapeHtml(row.color)}">
                <title>${escapeHtml(`${row.label}: ${exactPercent}`)}</title>
              </circle>
              <text class="lotto-dashboard-pie-slice-label is-full" x="100" y="101">${escapeHtml(roundedPercent)}</text>
            </g>
          `;
        }
        const start = pointAtAngle(startAngle);
        const end = pointAtAngle(endAngle);
        const largeArcFlag = percent > 50 ? 1 : 0;
        const labelAngle = startAngle + ((percent * 3.6) / 2);
        const labelRadius = percent < 12 ? 65 : 56;
        const labelRadians = (labelAngle * Math.PI) / 180;
        const labelX = 100 + (labelRadius * Math.cos(labelRadians));
        const labelY = 100 + (labelRadius * Math.sin(labelRadians));
        const label = percent >= 7
          ? `<text class="lotto-dashboard-pie-slice-label" x="${labelX.toFixed(2)}" y="${labelY.toFixed(2)}">${escapeHtml(roundedPercent)}</text>`
          : "";
        return `
          <g class="lotto-dashboard-pie-slice">
            <path
              class="lotto-dashboard-pie-segment"
              d="M 100 100 L ${start.x.toFixed(3)} ${start.y.toFixed(3)} A ${radius} ${radius} 0 ${largeArcFlag} 1 ${end.x.toFixed(3)} ${end.y.toFixed(3)} Z"
              fill="${escapeHtml(row.color)}"
            ><title>${escapeHtml(`${row.label}: ${exactPercent}`)}</title></path>
            ${label}
          </g>
        `;
      }).join("");
    }

    function renderDashboardDistributionPanel(type, entries, mode) {
      const rows = computeDashboardDistributionRows(type, entries, mode);
      const normalizedMode = normalizeDashboardDistributionView(mode);
      const isTemperatureMode = normalizedMode === "temperature";
      const total = rows.reduce((sum, row) => sum + Number(row.count || 0), 0);
      const activeRows = rows.filter(row => Number(row.count || 0) > 0);
      if (!activeRows.length || !total) {
        return `<div class="lotto-dashboard-empty-state">Chưa đủ dữ liệu để dựng phân bổ riêng cho ${escapeHtml(getDashboardTypeMeta(type).label)}.</div>`;
      }
      const segments = renderDashboardPieSegments(activeRows);
      const selectedTemperatureRow = isTemperatureMode
        ? rows.find(row => row.key === dashboardSelectedTemperatureKey && Number(row.count || 0) > 0) || null
        : null;
      const centerLabel = selectedTemperatureRow?.label
        || getDashboardDistributionOptions(type).find(option => option.value === normalizedMode)?.label
        || "Tỷ trọng";
      const centerValue = selectedTemperatureRow
        ? formatChartStatsPercent(selectedTemperatureRow.percent)
        : "100%";
      const centerMeta = selectedTemperatureRow?.countLabel || `${formatDashboardInteger(activeRows.length)} nhóm`;
      return `
        <div class="lotto-dashboard-donut-layout">
          <div class="lotto-dashboard-donut-wrap">
            <svg class="lotto-dashboard-donut-svg is-pie" viewBox="0 0 200 200" role="img" aria-label="Biểu đồ tròn tỷ lệ ${escapeHtml(centerLabel)}">
              <g class="lotto-dashboard-pie">${segments}</g>
            </svg>
            <div class="lotto-dashboard-pie-summary">
              <div class="lotto-dashboard-pie-summary-value">${escapeHtml(centerValue)}</div>
              <div class="lotto-dashboard-pie-summary-copy">
                <div class="lotto-dashboard-pie-summary-label">${escapeHtml(centerLabel)}</div>
                <div class="lotto-dashboard-pie-summary-meta">${escapeHtml(centerMeta)}</div>
              </div>
            </div>
          </div>
          <div class="lotto-dashboard-donut-legend">
            ${rows.map(row => {
              const isSelected = isTemperatureMode && row.key === selectedTemperatureRow?.key;
              const tagName = isTemperatureMode ? "button" : "div";
              const interactiveAttributes = isTemperatureMode
                ? ` type="button" data-dashboard-temperature-key="${escapeHtml(row.key)}" aria-controls="lottoDashboardTemperatureDetail" aria-expanded="${isSelected ? "true" : "false"}"${Number(row.count || 0) > 0 ? "" : " disabled"}`
                : "";
              return `
              <${tagName} class="lotto-dashboard-donut-legend-item${isTemperatureMode ? " is-interactive" : ""}${isSelected ? " is-active" : ""}" style="--dashboard-color:${escapeHtml(row.color)}"${interactiveAttributes}>
                <span class="lotto-dashboard-donut-legend-swatch" style="--dashboard-color:${escapeHtml(row.color)}"></span>
                <div class="lotto-dashboard-donut-legend-copy">
                  <div class="lotto-dashboard-donut-legend-label">${escapeHtml(row.label)}</div>
                  <div class="lotto-dashboard-donut-legend-meta">${escapeHtml(row.meta || "")}</div>
                  <div class="lotto-dashboard-donut-legend-ratio" aria-hidden="true">
                    <span style="width:${Math.max(0, Math.min(100, Number(row.percent || 0))).toFixed(2)}%;--dashboard-color:${escapeHtml(row.color)}"></span>
                  </div>
                </div>
                <div class="lotto-dashboard-donut-legend-values">
                  <div class="lotto-dashboard-donut-legend-percent">${escapeHtml(formatChartStatsPercent(row.percent))}</div>
                  <div class="lotto-dashboard-donut-legend-count">${escapeHtml(row.countLabel || `${formatDashboardInteger(row.count)}`)}</div>
                </div>
              </${tagName}>
            `;
            }).join("")}
          </div>
          ${isTemperatureMode ? renderDashboardTemperatureDetail(type, selectedTemperatureRow) : ""}
        </div>
      `;
    }

    function bindDashboardTemperatureLegend(type, entries, mode) {
      if (normalizeDashboardDistributionView(mode) !== "temperature") return;
      const host = document.getElementById("lottoDashboardDistributionOut");
      if (!host) return;
      host.querySelectorAll("[data-dashboard-temperature-key]").forEach(button => {
        button.addEventListener("click", () => {
          const nextKey = String(button.dataset.dashboardTemperatureKey || "").trim();
          if (!nextKey || button.disabled) return;
          dashboardSelectedTemperatureKey = nextKey === dashboardSelectedTemperatureKey ? "" : nextKey;
          host.innerHTML = renderDashboardDistributionPanel(type, entries, mode);
          bindDashboardTemperatureLegend(type, entries, mode);
          Array.from(host.querySelectorAll("[data-dashboard-temperature-key]"))
            .find(nextButton => nextButton.dataset.dashboardTemperatureKey === nextKey)
            ?.focus({ preventScroll: true });
        });
      });
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
      const normalizedMode = normalizeDashboardActivityView(mode);
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
                  <stop offset="0%" stop-color="rgba(79, 200, 223, .28)"></stop>
                  <stop offset="100%" stop-color="rgba(79, 200, 223, 0)"></stop>
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
        const viewMode = normalizeDashboardActivityView(button.dataset.dashboardActivityView);
        const isActive = viewMode === dashboardActivityViewMode;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-selected", isActive ? "true" : "false");
      });
    }

    function renderDashboardDistributionTabs() {
      const host = document.getElementById("lottoDashboardDistributionTabs");
      if (!host) return;
      const options = getDashboardDistributionOptions(dashboardSelectedGame);
      host.innerHTML = options.map(option => {
        const isActive = option.value === dashboardDistributionViewMode;
        return `<button type="button" class="lotto-dashboard-tab${isActive ? " is-active" : ""}" data-dashboard-distribution-view="${escapeHtml(option.value)}" role="tab" aria-selected="${isActive ? "true" : "false"}" aria-controls="lottoDashboardDistributionOut">${escapeHtml(option.label)}</button>`;
      }).join("");
      host.querySelectorAll("[data-dashboard-distribution-view]").forEach(button => {
        button.addEventListener("click", () => {
          const nextView = normalizeDashboardDistributionView(button.dataset.dashboardDistributionView);
          if (nextView === dashboardDistributionViewMode) return;
          dashboardSelectedTemperatureKey = "";
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
      renderDashboardScopeFilter();
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
      bindDashboardTemperatureLegend(type, entries, dashboardDistributionViewMode);
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
      if (trend.direction === "same") return "0.00%";
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

