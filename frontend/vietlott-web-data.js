    function buildPredictionTopHitSummary(type, entry, draw) {
      const normalizedRankings = normalizePredictionTopRankings(
        type,
        entry?.topMainRanking,
        entry?.topSpecialRanking,
        entry?.tickets,
      );
      const mainRanking = normalizedRankings.main;
      const mainMatched = mainRanking.length ? countMainMatch(mainRanking, draw.main) : 0;
      const topMain = {
        matched: mainMatched,
        total: mainRanking.length,
        rate: mainRanking.length ? (mainMatched * 100 / mainRanking.length) : 0,
      };
      const topSpecial = {
        matched: 0,
        total: 0,
        candidateCount: 0,
        rate: 0,
      };
      if (TYPES[type]?.hasSpecial) {
        const specialRanking = normalizedRankings.special;
        const specialMatched = Number.isInteger(draw?.special) && specialRanking.includes(draw.special) ? 1 : 0;
        topSpecial.matched = specialMatched;
        topSpecial.total = specialRanking.length && Number.isInteger(draw?.special) ? 1 : 0;
        topSpecial.candidateCount = specialRanking.length;
        topSpecial.rate = topSpecial.total ? specialMatched * 100 : 0;
      }
      return { topMain, topSpecial };
    }

    function getPredictionEntrySortMeta(entry) {
      return {
        kyValue: kySortValue(entry?.actualKy || entry?.predictedKy),
        timeValue: Date.parse(entry?.resolvedAt || entry?.createdAt || 0) || 0,
      };
    }

    function enrichPredictionSummary(type, entry, previousSummary = null) {
      if (!entry?.actualDraw || !Array.isArray(entry?.tickets)) return entry?.resultSummary || null;
      const baseSummary = evaluatePredictionTicketsForDraw(type, entry.tickets, entry.actualDraw);
      const hitRateBuckets = buildPredictionRateBuckets(type, baseSummary.details, entry.tickets).map(bucket => {
        const previousBucket = Array.isArray(previousSummary?.hitRateBuckets)
          ? previousSummary.hitRateBuckets.find(item => Number(item?.hitCount || 0) === bucket.hitCount)
          : null;
        return {
          ...bucket,
          trend: buildPredictionTrend(bucket.rate, Number(previousBucket?.rate || 0)),
        };
      });
      const topHitSummary = buildPredictionTopHitSummary(type, entry, entry.actualDraw);
      const previousTopMainRate = Number(previousSummary?.topHitSummary?.topMain?.rate || 0);
      const previousTopSpecialRate = Number(previousSummary?.topHitSummary?.topSpecial?.rate || 0);
      return {
        ...baseSummary,
        hitRateBuckets,
        topHitSummary: {
          topMain: {
            ...topHitSummary.topMain,
            trend: buildPredictionTrend(topHitSummary.topMain.rate, previousTopMainRate),
          },
          topSpecial: {
            ...topHitSummary.topSpecial,
            trend: buildPredictionTrend(topHitSummary.topSpecial.rate, previousTopSpecialRate),
          },
        },
      };
    }

    function refreshResolvedPredictionSummaries(type) {
      if (!PREDICTION_LOG_TYPES.includes(type)) return false;
      const logs = ensurePredictionLogBucket(type);
      const resolvedEntries = logs
        .filter(entry => entry?.resolved && entry?.actualDraw && Array.isArray(entry?.tickets))
        .sort((a, b) => {
          const aMeta = getPredictionEntrySortMeta(a);
          const bMeta = getPredictionEntrySortMeta(b);
          if (aMeta.kyValue !== bMeta.kyValue) return aMeta.kyValue - bMeta.kyValue;
          return aMeta.timeValue - bMeta.timeValue;
        });
      let previousSummary = null;
      let changed = false;
      for (const entry of resolvedEntries) {
        const nextSummary = enrichPredictionSummary(type, entry, previousSummary);
        const before = JSON.stringify(entry.resultSummary || null);
        const after = JSON.stringify(nextSummary || null);
        if (before !== after) {
          entry.resultSummary = nextSummary;
          changed = true;
        }
        previousSummary = nextSummary;
      }
      return changed;
    }

    const PREDICTION_BAO_PRIZE_CARD_CACHE = new Map();

    function normalizePredictionPrizeLookupText(value) {
      return String(value || "")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/Đ/g, "D")
        .replace(/đ/g, "d")
        .toUpperCase()
        .replace(/\s+/g, " ")
        .trim();
    }

    function parsePredictionPrizeAmount(value) {
      const lookupText = normalizePredictionPrizeLookupText(value);
      if (!lookupText) return { amount: 0, variable: false };
      let amount = 0;
      const unitPattern = /(\d+(?:[.,]\d+)*)\s*(TY|TRIEU)\b/g;
      let unitMatch = null;
      while ((unitMatch = unitPattern.exec(lookupText)) !== null) {
        const numeric = Number(String(unitMatch[1]).replace(/\./g, "").replace(",", "."));
        if (!Number.isFinite(numeric)) continue;
        amount += numeric * (unitMatch[2] === "TY" ? 1_000_000_000 : 1_000_000);
      }
      if (amount === 0) {
        const plainText = lookupText.replace(/\*/g, "").replace(/\b(VND|DONG)\b/g, "").trim();
        if (/^\d+(?:\.\d+)*$/.test(plainText)) {
          amount = Number(plainText.replace(/\./g, "")) || 0;
        }
      }

      const hasJackpot1 = /\bJACKPOT1\b/.test(lookupText);
      const hasJackpot2 = /\bJACKPOT2\b/.test(lookupText);
      const hasMegaJackpot = /\bJACKPOT\b/.test(lookupText);
      const hasDocDac = /\bDOC DAC\b/.test(lookupText);
      if (hasJackpot1) amount += 30_000_000_000;
      if (hasJackpot2) {
        const multiplierMatch = lookupText.match(/JACKPOT2\s*X\s*(\d+)/);
        amount += 3_000_000_000 * Math.max(1, Number(multiplierMatch?.[1] || 1));
      }
      if (hasMegaJackpot) amount += 12_000_000_000;
      if (hasDocDac) amount += 6_000_000_000;
      const variable = hasJackpot1
        || hasJackpot2
        || hasMegaJackpot
        || hasDocDac
        || /TOI THIEU|TICH LUY/.test(lookupText);
      return { amount: Math.max(0, Math.round(amount)), variable };
    }

    function normalizePredictionPrizeBreakdownLabel(value) {
      return String(value || "")
        .replace(/\+\s*ĐB\b/gi, "+ số phụ")
        .replace(/chỉ\s+ĐB\b/gi, "chỉ số phụ")
        .replace(/số đặc biệt/gi, "số phụ")
        .trim();
    }

    function getPredictionBaoPrizeCard(type, baoLevel) {
      const normalizedLevel = Number(baoLevel || 0);
      if (!normalizedLevel) return null;
      const cacheKey = `${type}:${normalizedLevel}`;
      if (!PREDICTION_BAO_PRIZE_CARD_CACHE.has(cacheKey)) {
        const card = getBaoBrochureData(type).find(item => Number(item?.level || 0) === normalizedLevel) || null;
        PREDICTION_BAO_PRIZE_CARD_CACHE.set(cacheKey, card);
      }
      return PREDICTION_BAO_PRIZE_CARD_CACHE.get(cacheKey) || null;
    }

    function evalBaoPrize(type, ticket, draw) {
      const baoLevel = Number(ticket?.baoLevel || ticket?.main?.length || 0);
      const card = getPredictionBaoPrizeCard(type, baoLevel);
      if (!card || !Array.isArray(card.rows)) return null;
      const mainHits = countMainMatch(ticket.main, draw.main);
      const specialHit = TYPES[type]?.hasSpecial
        && Number.isInteger(ticket?.special)
        && ticket.special === draw.special;
      const normalizedRows = card.rows.map(row => ({
        row,
        label: normalizePredictionPrizeLookupText(row?.[0]),
      }));
      const findRow = predicate => normalizedRows.find(item => predicate(item.label))?.row || null;
      let matchedRow = null;

      if (type === "LOTO_5_35") {
        if (specialHit) {
          matchedRow = findRow(label => label === `${mainHits} SO CHINH + DB`);
          if (!matchedRow && mainHits <= 1) {
            matchedRow = findRow(label => label.includes("1 SO CHINH + DB HOAC CHI DB"));
          }
          if (!matchedRow && mainHits <= 2) {
            matchedRow = findRow(label => label === "2 SO CHINH + DB");
          }
        } else {
          matchedRow = findRow(label => label === `${mainHits} SO CHINH`);
        }
      } else if (type === "LOTO_6_45") {
        matchedRow = findRow(label => label === `TRUNG ${mainHits} SO`);
      } else if (type === "LOTO_6_55") {
        if (specialHit) {
          matchedRow = findRow(label => label === `TRUNG ${mainHits} SO + SO DAC BIET`);
        }
        if (!matchedRow) matchedRow = findRow(label => label === `TRUNG ${mainHits} SO`);
      }
      if (!matchedRow) return null;
      return [normalizePredictionPrizeBreakdownLabel(matchedRow[0]), matchedRow[1]];
    }

    function evaluatePredictionTicketsForDraw(type, tickets, draw) {
      const threshold = getPredictionHitThreshold(type);
      const details = [];
      const prizeBreakdownMap = new Map();
      let bestMainHits = 0;
      let specialHits = 0;
      let thresholdTicketHits = 0;
      let prizeTicketHits = 0;
      let pricedPrizeHits = 0;
      let totalPrizeAmount = 0;
      let hasVariablePrize = false;
      let totalMainHits = 0;
      for (const ticket of (tickets || [])) {
        const cloned = clonePredictionTicket(ticket);
        if (!cloned) continue;
        const isBao = String(cloned.playMode || "").trim().toLowerCase() === "bao";
        const mainHits = countMainMatch(cloned.main, draw.main);
        const specialHit = TYPES[type].hasSpecial && Number.isInteger(cloned.special) && cloned.special === draw.special;
        const prize = isBao ? evalBaoPrize(type, cloned, draw) : evalPrize(type, cloned, draw);
        const prizeMeta = prize ? parsePredictionPrizeAmount(prize[1]) : { amount: 0, variable: false };
        if (mainHits > bestMainHits) bestMainHits = mainHits;
        totalMainHits += mainHits;
        if (specialHit) specialHits += 1;
        if (mainHits >= threshold) thresholdTicketHits += 1;
        if (prize) {
          prizeTicketHits += 1;
          if (prizeMeta.amount > 0) pricedPrizeHits += 1;
          totalPrizeAmount += prizeMeta.amount;
          hasVariablePrize = hasVariablePrize || prizeMeta.variable;
          const prizeLabel = normalizePredictionPrizeBreakdownLabel(prize[0]);
          const breakdownKey = `${prizeLabel}|${prizeMeta.amount}|${prizeMeta.variable ? 1 : 0}`;
          const breakdown = prizeBreakdownMap.get(breakdownKey) || {
            label: prizeLabel,
            count: 0,
            unitAmount: prizeMeta.amount,
            totalAmount: 0,
            variable: prizeMeta.variable,
          };
          breakdown.count += 1;
          breakdown.totalAmount += prizeMeta.amount;
          prizeBreakdownMap.set(breakdownKey, breakdown);
        }
        details.push({
          main: cloned.main,
          special: cloned.special,
          playMode: cloned.playMode || "",
          baoLevel: cloned.baoLevel,
          mainHits,
          specialHit,
          prizeLabel: prize?.[0] || "",
          prizeValue: prize?.[1] || "",
          prizeAmount: prizeMeta.amount,
          prizeVariable: prizeMeta.variable,
        });
      }
      const prizeBreakdown = [...prizeBreakdownMap.values()].sort((a, b) => (
        Number(b.unitAmount || 0) - Number(a.unitAmount || 0)
        || Number(b.totalAmount || 0) - Number(a.totalAmount || 0)
        || String(a.label || "").localeCompare(String(b.label || ""), "vi")
      ));
      return {
        ticketCount: details.length,
        bestMainHits,
        avgMainHits: details.length ? (totalMainHits / details.length) : 0,
        specialHits,
        thresholdTicketHits,
        prizeTicketHits,
        pricedPrizeHits,
        totalPrizeAmount,
        hasVariablePrize,
        losingTicketCount: Math.max(0, details.length - prizeTicketHits),
        prizeBreakdown,
        details,
      };
    }

    function resolvePredictionLogsForKy(type, ky, draw) {
      if (!PREDICTION_LOG_TYPES.includes(type)) return;
      const logs = ensurePredictionLogBucket(type);
      const normalizedKy = normalizeKy(ky);
      if (!normalizedKy || !logs.length) return;
      let changed = false;
      for (const entry of logs) {
        if (normalizeKy(entry?.predictedKy) !== normalizedKy) continue;
        if (entry.resolved && entry.actualKy === normalizedKy) continue;
        entry.resolved = true;
        entry.resolvedAt = getSyncedIsoString();
        entry.actualKy = normalizedKy;
        entry.actualDraw = cloneDraw(draw);
        entry.resultMissingData = false;
        entry.resultMissingReason = "";
        entry.resultMissingCheckedAt = "";
        changed = true;
      }
      if (changed) {
        refreshResolvedPredictionSummaries(type);
        renderPredictionHistoryPanel();
      }
    }

    function findPredictionResultDraw(dataset, ky) {
      if (!dataset?.results) return null;
      const normalizedKy = normalizeKy(ky);
      if (!normalizedKy) return null;
      const digitKy = normalizedKy.replace(/\D/g, "");
      const directHit = dataset.results[normalizedKy] || dataset.results[digitKy];
      if (directHit) return directHit;
      const targetKyValue = kySortValue(normalizedKy);
      if (!targetKyValue) return null;
      for (const [key, draw] of Object.entries(dataset.results)) {
        if (kySortValue(key) === targetKyValue) return draw;
      }
      return null;
    }

    function getPredictionResultDrawDate(type, dataset, ky) {
      const draw = findPredictionResultDraw(dataset, ky);
      if (!draw) return null;
      const resolved = resolveLiveDrawDateTime(type, draw.date, draw.time);
      return resolved instanceof Date && !Number.isNaN(resolved.getTime()) ? resolved : null;
    }

    function parsePredictionLogDate(value) {
      const parsed = value ? new Date(value) : null;
      return parsed instanceof Date && !Number.isNaN(parsed.getTime()) ? parsed : null;
    }

    function isKenoPredictionLogOverdue(entry, dataset = null, nowValue = getSyncedNowDate()) {
      if (!entry || entry.resolved) return false;
      const resultDataset = dataset || buildPredictionResultDataset("KENO");
      const predictedKy = normalizeKy(entry.predictedKy);
      const predictedKyValue = kySortValue(predictedKy);
      const latestKnownKyValue = kySortValue((resultDataset?.order || []).at(-1));
      if (predictedKyValue && latestKnownKyValue && predictedKyValue <= latestKnownKyValue) {
        return true;
      }
      const predictedDrawDate = predictedKy ? getPredictionResultDrawDate("KENO", resultDataset, predictedKy) : null;
      if (predictedDrawDate && predictedDrawDate.getTime() <= nowValue.getTime()) {
        return true;
      }
      const createdAt = parsePredictionLogDate(entry.createdAt);
      if (!createdAt) return false;
      const fallbackTargetDate = findNextLiveDrawDate("KENO", createdAt);
      return fallbackTargetDate instanceof Date
        && !Number.isNaN(fallbackTargetDate.getTime())
        && fallbackTargetDate.getTime() <= nowValue.getTime();
    }

    function getKenoPredictionHistoryRepairLookbackDays(dataset = null, nowValue = getSyncedNowDate()) {
      const logs = ensurePredictionLogBucket("KENO");
      if (!logs.length) return 0;
      const resultDataset = dataset || buildPredictionResultDataset("KENO");
      let oldestDate = null;
      logs.forEach(entry => {
        if (!isKenoPredictionLogOverdue(entry, resultDataset, nowValue)) return;
        const predictedDrawDate = getPredictionResultDrawDate("KENO", resultDataset, entry.predictedKy);
        const fallbackDate = parsePredictionLogDate(entry.createdAt);
        const candidate = predictedDrawDate || fallbackDate;
        if (!(candidate instanceof Date) || Number.isNaN(candidate.getTime())) return;
        if (!oldestDate || candidate.getTime() < oldestDate.getTime()) oldestDate = candidate;
      });
      if (!(oldestDate instanceof Date) || Number.isNaN(oldestDate.getTime())) return 0;
      const diffDays = Math.ceil((nowValue.getTime() - oldestDate.getTime()) / (24 * 60 * 60 * 1000));
      return Math.min(30, Math.max(3, diffDays + 2));
    }

    function markMissingKenoPredictionResults(dataset = null, nowValue = getSyncedNowDate()) {
      const resultDataset = dataset || buildPredictionResultDataset("KENO");
      const logs = ensurePredictionLogBucket("KENO");
      if (!logs.length) return false;
      let changed = false;
      const checkedAt = nowValue.toISOString();
      logs.forEach(entry => {
        if (!entry) return;
        const shouldMarkMissing = !entry.resolved && isKenoPredictionLogOverdue(entry, resultDataset, nowValue);
        if (shouldMarkMissing) {
          if (!entry.resultMissingData || entry.resultMissingReason !== "canonical_history_missing_result") {
            entry.resultMissingData = true;
            entry.resultMissingReason = "canonical_history_missing_result";
            changed = true;
          }
          if (entry.resultMissingCheckedAt !== checkedAt) {
            entry.resultMissingCheckedAt = checkedAt;
            changed = true;
          }
          return;
        }
        if (entry.resultMissingData || entry.resultMissingReason || entry.resultMissingCheckedAt) {
          entry.resultMissingData = false;
          entry.resultMissingReason = "";
          entry.resultMissingCheckedAt = "";
          changed = true;
        }
      });
      return changed;
    }

    function getPredictionHistoryEntryStatus(entry) {
      if (entry?.resolved) {
        return { className: "resolved", label: "Đã đối chiếu", shortLabel: "Đã đối chiếu" };
      }
      if (entry?.resultMissingData) {
        return { className: "missing", label: "Thiếu dữ liệu KQ", shortLabel: "Thiếu KQ" };
      }
      return { className: "waiting", label: "Chờ kết quả", shortLabel: "Chờ KQ" };
    }

    function hasPredictionLogEntry(entry) {
      return !!(entry && Array.isArray(entry?.tickets) && entry.tickets.length);
    }

    function getPredictionDisplaySource(predictionEntry = null, fallbackSet = null) {
      if (hasPredictionLogEntry(predictionEntry)) return "ai_log";
      if (fallbackSet instanceof Set && fallbackSet.size) return "stats_fallback";
      return "none";
    }

    window.hasPredictionLogEntry = hasPredictionLogEntry;
    window.getPredictionDisplaySource = getPredictionDisplaySource;

    function findNextKenoKyAfterDate(dataset, afterDate) {
      if (!(afterDate instanceof Date) || Number.isNaN(afterDate.getTime())) return null;
      for (const ky of (dataset?.order || [])) {
        const drawDate = getPredictionResultDrawDate("KENO", dataset, ky);
        if (drawDate && drawDate.getTime() > afterDate.getTime()) {
          return normalizeKy(ky);
        }
      }
      return null;
    }

    function repairStaleKenoPredictionLogs(dataset = null) {
      const resultDataset = dataset || buildPredictionResultDataset("KENO");
      const logs = ensurePredictionLogBucket("KENO");
      if (!logs.length || !(resultDataset?.order || []).length) return false;
      const latestKy = resultDataset.order[resultDataset.order.length - 1];
      const latestKyValue = kySortValue(latestKy);
      let changed = false;

      for (const entry of logs) {
        if (!entry || entry.resolved) continue;
        const predictedKy = normalizeKy(entry.predictedKy);
        const predictedKyValue = kySortValue(predictedKy);
        if (!predictedKy || !predictedKyValue || predictedKyValue > latestKyValue) continue;
        const predictedDrawDate = getPredictionResultDrawDate("KENO", resultDataset, predictedKy);
        const createdAt = entry.createdAt ? new Date(entry.createdAt) : null;
        if (!(createdAt instanceof Date) || Number.isNaN(createdAt.getTime()) || !predictedDrawDate) continue;
        if (createdAt.getTime() <= predictedDrawDate.getTime()) continue;
        const repairedKy = findNextKenoKyAfterDate(resultDataset, createdAt);
        if (!repairedKy || repairedKy === predictedKy) continue;
        if (!findPredictionResultDraw(resultDataset, repairedKy)) continue;
        if (!entry.predictedKyOriginal) entry.predictedKyOriginal = predictedKy;
        entry.predictedKy = repairedKy;
        entry.predictedKyRepaired = repairedKy;
        entry.repairReason = "stale_keno_client_target";
        changed = true;
      }

      return changed;
    }

    function reconcilePredictionLogsForType(type) {
      if (!PREDICTION_LOG_TYPES.includes(type)) return;
      const logs = ensurePredictionLogBucket(type);
      if (!logs.length) return;
      const dataset = buildPredictionResultDataset(type);
      if (type === "KENO") {
        const repaired = repairStaleKenoPredictionLogs(dataset);
        if (repaired) saveStore();
      }
      for (const entry of logs) {
        if (entry?.resolved) continue;
        const predictedKy = normalizeKy(entry?.predictedKy);
        const draw = findPredictionResultDraw(dataset, predictedKy);
        if (!predictedKy || !draw) continue;
        resolvePredictionLogsForKy(type, predictedKy, draw);
      }
      if (type === "KENO" && getLiveHistoryFeed("KENO")?.repairAttempted) {
        const markedMissing = markMissingKenoPredictionResults(dataset);
        if (markedMissing) saveStore();
      }
    }

    function reconcileAllPredictionLogs() {
      for (const type of PREDICTION_LOG_TYPES) reconcilePredictionLogsForType(type);
    }

    function upsertPredictionLog(type, entry) {
      if (!PREDICTION_LOG_TYPES.includes(type) || !entry) return;
      const logs = ensurePredictionLogBucket(type);
      const predictedKy = normalizeKy(entry.predictedKy);
      const normalizedRankings = normalizePredictionTopRankings(
        type,
        entry.topMainRanking,
        entry.topSpecialRanking,
        entry.tickets,
      );
      const next = {
        id: String(entry.id || `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`),
        createdAt: String(entry.createdAt || getSyncedIsoString()),
        predictedKy,
        targetDrawAt: String(entry.targetDrawAt || ""),
        strategyKey: String(entry.strategyKey || ""),
        strategyLabel: String(entry.strategyLabel || ""),
        modelKey: String(entry.modelKey || entry.strategyKey || ""),
        modelLabel: String(entry.modelLabel || entry.strategyLabel || ""),
        engineKey: String(entry.engineKey || ""),
        engineLabel: String(entry.engineLabel || ""),
        riskMode: normalizePredictRiskMode(entry.riskMode || "balanced"),
        riskModeLabel: String(entry.riskModeLabel || getPredictRiskModeMeta(entry.riskMode || "balanced").label),
        riskModeSummary: String(entry.riskModeSummary || getPredictRiskModeMeta(entry.riskMode || "balanced").summary),
        modelVersion: String(entry.modelVersion || ""),
        championKey: String(entry.championKey || ""),
        championLabel: String(entry.championLabel || ""),
        lastTrainedAt: String(entry.lastTrainedAt || ""),
        confidence: Number(entry.confidence || 0),
        stabilityScore: Number(entry.stabilityScore || entry.backtest?.stabilityScore || 0),
        recentCount: Number(entry.recentCount || 0),
        drawCount: Number(entry.drawCount || 0),
        historyFile: String(entry.historyFile || ""),
        historyCount: Number(entry.historyCount || 0),
        bundleCount: Number(entry.bundleCount || 0),
        pickSize: Number(entry.pickSize || 0),
        playMode: String(entry.playMode || "").trim().toLowerCase(),
        baoLevel: Number.isInteger(Number(entry.baoLevel)) ? Number(entry.baoLevel) : null,
        predictionMode: normalizePredictionMode(entry.predictionMode || PREDICTION_MODE_NORMAL),
        vipProfile: String(entry.vipProfile || ""),
        predictionId: String(entry.predictionId || ""),
        predictionStatus: String(entry.predictionStatus || ""),
        dataCutoffDrawId: String(entry.dataCutoffDrawId || ""),
        payloadChecksum: String(entry.payloadChecksum || ""),
        modelRole: String(entry.modelRole || ""),
        probabilitySummary: entry.probabilitySummary || null,
        calibratedProbability: Array.isArray(entry.calibratedProbability) ? entry.calibratedProbability : [],
        specialCalibratedProbability: Array.isArray(entry.specialCalibratedProbability) ? entry.specialCalibratedProbability : [],
        ticketQualityScore: Number(entry.ticketQualityScore || 0),
        scoreMetrics: entry.scoreMetrics && typeof entry.scoreMetrics === "object" ? entry.scoreMetrics : null,
        tickets: (entry.tickets || []).map(clonePredictionTicket).filter(Boolean),
        ticketSources: Array.isArray(entry.ticketSources) ? entry.ticketSources.map(item => String(item || "").trim()) : [],
          topMainRanking: normalizedRankings.main,
          topSpecialRanking: normalizedRankings.special,
          backtest: entry.backtest || null,
          metaSelectionMode: String(entry.metaSelectionMode || ""),
          metaScores: entry.metaScores || null,
          metaQuota: entry.metaQuota || null,
          metaPreferredEngine: String(entry.metaPreferredEngine || ""),
          metaSummary: String(entry.metaSummary || ""),
          resolved: !!entry.resolved,
          resolvedAt: String(entry.resolvedAt || ""),
          actualKy: String(entry.actualKy || ""),
          resultMissingData: !!entry.resultMissingData,
          resultMissingReason: String(entry.resultMissingReason || ""),
          resultMissingCheckedAt: String(entry.resultMissingCheckedAt || ""),
        actualDraw: entry.actualDraw ? cloneDraw(entry.actualDraw) : null,
        resultSummary: entry.resultSummary || null,
      };
      const idx = logs.findIndex(log => String(log?.id || "") === next.id);
      if (idx >= 0) logs[idx] = next;
      else logs.push(next);
      logs.sort((a, b) => {
        const aTime = Date.parse(a?.createdAt || 0) || 0;
        const bTime = Date.parse(b?.createdAt || 0) || 0;
        if (aTime !== bTime) return aTime - bTime;
        return kySortValue(a.predictedKy) - kySortValue(b.predictedKy);
      });
      while (logs.length > MAX_PREDICTION_LOGS_PER_TYPE) logs.shift();
      renderPredictionHistoryPanel();
      renderHeaderNotifications();
    }

    function getPredictionEntryPlayModeForMetrics(entry) {
      const directMode = String(entry?.playMode || "").trim().toLowerCase();
      if (directMode === "bao") return "bao";
      const tickets = Array.isArray(entry?.tickets) ? entry.tickets : [];
      return tickets.some(ticket => String(ticket?.playMode || "").trim().toLowerCase() === "bao") ? "bao" : "normal";
    }

    function getPredictionEntryMode(entry) {
      return normalizePredictionMode(entry?.predictionMode || PREDICTION_MODE_NORMAL);
    }

    function getPredictionEntryBaoLevelForMetrics(entry) {
      const directLevel = Number(entry?.baoLevel || 0);
      if (Number.isInteger(directLevel) && directLevel > 0) return directLevel;
      const tickets = Array.isArray(entry?.tickets) ? entry.tickets : [];
      const baoTicket = tickets.find(ticket => String(ticket?.playMode || "").trim().toLowerCase() === "bao");
      if (!baoTicket) return 0;
      const ticketLevel = Number(baoTicket?.baoLevel || (Array.isArray(baoTicket?.main) ? baoTicket.main.length : 0) || 0);
      return Number.isInteger(ticketLevel) && ticketLevel > 0 ? ticketLevel : 0;
    }

    function getPredictionEntryPickSizeForMetrics(type, entry) {
      if (type !== "KENO") return 0;
      const directSize = Number(entry?.pickSize || 0);
      if (Number.isInteger(directSize) && directSize > 0) return directSize;
      const firstTicket = Array.isArray(entry?.tickets) ? entry.tickets.find(ticket => Array.isArray(ticket?.main) && ticket.main.length) : null;
      return firstTicket ? Number(firstTicket.main.length || 0) : 0;
    }

    function findPreviousPredictionLogForMetrics(result) {
      const type = String(result?.type || "").trim().toUpperCase();
      if (!PREDICTION_LOG_TYPES.includes(type)) return null;
      const currentCreatedAtMs = Date.parse(String(result?.createdAt || "").trim());
      if (!Number.isFinite(currentCreatedAtMs)) return null;
      const currentPredictionMode = getPredictionEntryMode(result);
      const currentEngineKey = String(result?.engineKey || result?.engine || "").trim().toLowerCase();
      const currentRiskMode = currentEngineKey === "both" ? getResultRiskMode(result, "balanced") : "";
      const currentPlayMode = getPredictionEntryPlayModeForMetrics(result);
      const currentPickSize = getPredictionEntryPickSizeForMetrics(type, result);
      const currentBaoLevel = currentPlayMode === "bao" ? getPredictionEntryBaoLevelForMetrics(result) : 0;
      const logs = ensurePredictionLogBucket(type);
      const candidates = logs.filter(entry => {
        const entryCreatedAtMs = Date.parse(String(entry?.createdAt || "").trim());
        if (!Number.isFinite(entryCreatedAtMs) || entryCreatedAtMs >= currentCreatedAtMs) return false;
        if (getPredictionEntryMode(entry) !== currentPredictionMode) return false;
        const entryEngineKey = String(entry?.engineKey || "").trim().toLowerCase();
        if (entryEngineKey !== currentEngineKey) return false;
        if (currentEngineKey === "both" && normalizePredictRiskMode(entry?.riskMode || "balanced") !== currentRiskMode) return false;
        const entryPlayMode = getPredictionEntryPlayModeForMetrics(entry);
        if (entryPlayMode !== currentPlayMode) return false;
        if (type === "KENO" && getPredictionEntryPickSizeForMetrics(type, entry) !== currentPickSize) return false;
        if (currentPlayMode === "bao" && getPredictionEntryBaoLevelForMetrics(entry) !== currentBaoLevel) return false;
        return true;
      });
      if (!candidates.length) return null;
      candidates.sort((a, b) => {
        const aTime = Date.parse(String(a?.createdAt || "").trim()) || 0;
        const bTime = Date.parse(String(b?.createdAt || "").trim()) || 0;
        if (aTime !== bTime) return bTime - aTime;
        return kySortValue(b?.predictedKy) - kySortValue(a?.predictedKy);
      });
      return candidates[0] || null;
    }

    function normalizePredictionHistoryType(value) {
      const raw = String(value || "").trim().toUpperCase();
      return PREDICTION_HISTORY_TYPES.some(item => item.value === raw) ? raw : "KENO";
    }

    function getPreferredPredictionHistoryType() {
      const pdType = document.getElementById("pdType");
      return normalizePredictionHistoryType(pdType?.value || predictionHistorySelectedType);
    }

    function renderPredictionHistoryTypeTabs() {
      const tabsEl = document.getElementById("predictionHistoryTypeTabs");
      if (!tabsEl) return;
      const selectedType = normalizePredictionHistoryType(predictionHistorySelectedType);
      predictionHistorySelectedType = selectedType;
      tabsEl.innerHTML = PREDICTION_HISTORY_TYPES.map(item => {
        const isActive = item.value === selectedType;
        return `<button
          type="button"
          class="predict-history-type-tab${isActive ? " is-active" : ""}"
          data-prediction-history-type="${item.value}"
          role="tab"
          aria-selected="${isActive ? "true" : "false"}"
        >${escapeHtml(item.label)}</button>`;
      }).join("");
    }

    function getPredictionHistoryRangeItems(typeKey = predictionHistorySelectedType) {
      const normalizedType = normalizePredictionHistoryType(typeKey);
      return normalizedType === "KENO"
        ? [
            { value: "5k", label: "5 Kỳ" },
            { value: "15k", label: "15 Kỳ" },
            { value: "30k", label: "30 Kỳ" },
            { value: "today", label: "Hôm Nay" },
            { value: "all", label: "All" },
          ]
        : [
            { value: "5k", label: "5 Kỳ" },
            { value: "12k", label: "12 Kỳ" },
            { value: "30k", label: "30 Kỳ" },
            { value: "68k", label: "68 Kỳ" },
            { value: "latest", label: "Mới Nhất" },
            { value: "all", label: "All" },
          ];
    }

    function normalizePredictionHistoryRange(value, typeKey = predictionHistorySelectedType) {
      const normalized = String(value || "").trim().toLowerCase();
      const items = getPredictionHistoryRangeItems(typeKey);
      return items.some(item => item.value === normalized) ? normalized : items[0].value;
    }

    function renderPredictionHistoryRangeTabs(typeKey = predictionHistorySelectedType) {
      const tabsEl = document.getElementById("predictionHistoryRangeTabs");
      if (!tabsEl) return;
      const selectedType = normalizePredictionHistoryType(typeKey);
      const selectedRange = normalizePredictionHistoryRange(predictionHistorySelectedRange, selectedType);
      predictionHistorySelectedRange = selectedRange;
      const items = getPredictionHistoryRangeItems(selectedType);
      tabsEl.innerHTML = items.map(item => {
        const isActive = item.value === selectedRange;
        return `<button
          type="button"
          class="predict-history-range-tab${isActive ? " is-active" : ""}"
          data-prediction-history-range="${item.value}"
          role="tab"
          aria-selected="${isActive ? "true" : "false"}"
        >${escapeHtml(item.label)}</button>`;
      }).join("");
    }

    function normalizePredictionHistoryPlayMode(value) {
      const normalized = String(value || "").trim().toLowerCase();
      return normalized === "bao" ? "bao" : "normal";
    }

    function normalizePredictionHistoryBaoLevel(value) {
      if (String(value || "").trim().toLowerCase() === "all") return "all";
      const numericValue = Number(value || 0);
      return Number.isInteger(numericValue) && numericValue > 0 ? String(numericValue) : "all";
    }

    function renderPredictionHistoryPlayModeTabs(typeKey = predictionHistorySelectedType) {
      const tabsEl = document.getElementById("predictionHistoryPlayModeTabs");
      if (!tabsEl) return;
      const normalizedType = normalizePredictionHistoryType(typeKey);
      if (!hasPredictBaoMode(normalizedType)) {
        predictionHistorySelectedPlayMode = "normal";
        tabsEl.hidden = true;
        tabsEl.innerHTML = "";
        renderPredictionHistoryBaoLevelFilter(normalizedType, "normal");
        return;
      }
      tabsEl.hidden = false;
      const selectedPlayMode = normalizePredictionHistoryPlayMode(predictionHistorySelectedPlayMode);
      predictionHistorySelectedPlayMode = selectedPlayMode;
      const items = [
        { value: "normal", label: "Chơi Thường" },
        { value: "bao", label: "Chơi Bao" },
      ];
      tabsEl.innerHTML = items.map(item => {
        const isActive = item.value === selectedPlayMode;
        return `<button
          type="button"
          class="predict-history-playmode-tab${isActive ? " is-active" : ""}"
          data-prediction-history-playmode="${item.value}"
          role="tab"
          aria-selected="${isActive ? "true" : "false"}"
        >${escapeHtml(item.label)}</button>`;
      }).join("");
      renderPredictionHistoryBaoLevelFilter(normalizedType, selectedPlayMode);
    }

    function getPredictionHistoryEntryPlayMode(entry) {
      const directMode = String(entry?.playMode || "").trim().toLowerCase();
      if (directMode === "bao") return "bao";
      const tickets = Array.isArray(entry?.tickets) ? entry.tickets : [];
      return tickets.some(ticket => String(ticket?.playMode || "").trim().toLowerCase() === "bao")
        ? "bao"
        : "normal";
    }

    function getPredictionHistoryEntryBundleCount(entry) {
      const directCount = Number(entry?.bundleCount || 0);
      if (Number.isInteger(directCount) && directCount > 0) return directCount;
      const ticketCount = Array.isArray(entry?.tickets) ? entry.tickets.length : 0;
      return Number.isInteger(ticketCount) && ticketCount > 0 ? ticketCount : 0;
    }

    function getPredictionHistoryBaoLevelOptions(typeKey = predictionHistorySelectedType, predictionMode = PREDICTION_MODE_NORMAL) {
      const normalizedType = normalizePredictionHistoryType(typeKey);
      return getPredictBaoLevels(normalizedType);
    }

    function renderPredictionHistoryBaoLevelFilter(typeKey = predictionHistorySelectedType, playModeKey = predictionHistorySelectedPlayMode, predictionMode = PREDICTION_MODE_NORMAL) {
      const wrapEl = document.getElementById("predictionHistoryBaoLevelFilterWrap");
      const selectEl = document.getElementById("predictionHistoryBaoLevelSelect");
      if (!wrapEl || !selectEl) return;
      const normalizedType = normalizePredictionHistoryType(typeKey);
      const selectedPlayMode = normalizePredictionHistoryPlayMode(playModeKey);
      const shouldShow = hasPredictBaoMode(normalizedType) && selectedPlayMode === "bao";
      if (!shouldShow) {
        predictionHistorySelectedBaoLevel = "all";
        wrapEl.hidden = true;
        selectEl.innerHTML = `<option value="all">Bậc: Tất cả</option>`;
        selectEl.value = "all";
        return;
      }
      const options = getPredictionHistoryBaoLevelOptions(normalizedType, predictionMode);
      const normalizedSelectedValue = normalizePredictionHistoryBaoLevel(predictionHistorySelectedBaoLevel);
      const nextSelectedValue = normalizedSelectedValue !== "all" && options.includes(Number(normalizedSelectedValue))
        ? normalizedSelectedValue
        : "all";
      predictionHistorySelectedBaoLevel = nextSelectedValue;
      selectEl.innerHTML = [
        `<option value="all">Bậc: Tất cả</option>`,
        ...options.map(value => `<option value="${value}">${escapeHtml(`Bao ${value}`)}</option>`),
      ].join("");
      selectEl.value = nextSelectedValue;
      wrapEl.hidden = false;
    }

    function isPredictionHistoryEntryInRange(entry, rangeKey = "all", typeKey = predictionHistorySelectedType) {
      const selectedRange = normalizePredictionHistoryRange(rangeKey, typeKey);
      if (selectedRange !== "today") return true;
      const createdAtMs = Date.parse(String(entry?.createdAt || "").trim());
      if (!Number.isFinite(createdAtMs)) return false;
      const now = getSyncedNowDate();
      const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
      return createdAtMs >= startOfToday;
    }

    function getPredictionHistoryRangeLimit(rangeKey, typeKey) {
      const selectedRange = normalizePredictionHistoryRange(rangeKey, typeKey);
      if (selectedRange === "latest") return 1;
      const match = /^(\d+)k$/.exec(selectedRange);
      return match ? Math.max(1, Number(match[1])) : 0;
    }

    function formatPredictionHistoryTime(value) {
      const parsed = Date.parse(String(value || "").trim());
      if (!parsed) return "";
      return new Date(parsed).toLocaleString("vi-VN");
    }

    function getPredictionHistoryMainHitSet(entry) {
      return new Set(
        Array.isArray(entry?.actualDraw?.main)
          ? entry.actualDraw.main.map(Number).filter(Number.isInteger)
          : []
      );
    }

    function renderPredictionHistoryNumberToken(number, { isHit = false, isMiss = false, special = false, type = "" } = {}) {
      const classNames = ["predict-hit-number"];
      if (special) classNames.push("is-special");
      if (special && isHit) classNames.push("is-special-hit");
      else if (isHit) classNames.push("is-hit");
      else if (isMiss) classNames.push("is-miss");
      return `<span class="${classNames.join(" ")}">${escapeHtml(formatPredictNumber(number, type))}</span>`;
    }

    function renderPredictionHistoryNumberList(numbers, entry, { special = false, perRow = 0, highlight = true } = {}) {
      const values = (numbers || []).map(Number).filter(Number.isInteger);
      if (!values.length) return "";
      const mainHitSet = highlight ? getPredictionHistoryMainHitSet(entry) : new Set();
      const specialHit = highlight ? Number(entry?.actualDraw?.special) : Number.NaN;
      const canHighlight = !!highlight && !!entry?.resolved && !!entry?.actualDraw;
      const tokens = values.map(number => {
        const isHit = special ? number === specialHit : mainHitSet.has(number);
        const isMiss = canHighlight && !isHit;
        return renderPredictionHistoryNumberToken(number, {
          isHit: canHighlight && isHit,
          isMiss,
          special,
          type: entry?.type || "",
        });
      });
      if (!Number.isInteger(perRow) || perRow <= 0 || values.length <= perRow) {
        return `<span class="predict-hit-number-list">${tokens.join("")}</span>`;
      }
      const rows = [];
      for (let index = 0; index < tokens.length; index += perRow) {
        rows.push(`<span class="predict-hit-number-row">${tokens.slice(index, index + perRow).join("")}</span>`);
      }
      return `<span class="predict-hit-number-grid">${rows.join("")}</span>`;
    }

    function formatPredictionHistoryTicketMeta(type, index, entry, { divider = true } = {}) {
      const rawSource = String(entry?.ticketSources?.[index] || "").trim().toLowerCase();
      const algorithmLabel = rawSource === "luan_so"
        ? "Luận Số"
        : rawSource === "gen_local"
        ? "AI GEN"
        : String(entry?.championLabel || entry?.modelLabel || entry?.strategyLabel || entry?.engineLabel || "AI Gen").trim();
      if (!algorithmLabel) return "";
      const prefix = divider ? "| " : "";
      const detail = Array.isArray(entry?.resultSummary?.details) ? entry.resultSummary.details[index] : null;
      if (!entry?.resolved || !detail) {
        const pendingLabel = getPredictionHistoryEntryStatus(entry).shortLabel;
        return `<span class="predict-ticket-meta${entry?.resultMissingData ? " is-missing" : ""}">${prefix}${escapeHtml(algorithmLabel)} - ${escapeHtml(pendingLabel)}</span>`;
      }
      const mainSlotCount = Array.isArray(detail?.main) ? detail.main.length : (Array.isArray(entry?.tickets?.[index]?.main) ? entry.tickets[index].main.length : 0);
      const mainHits = Math.max(0, Number(detail?.mainHits || 0));
      const hitText = `${mainHits}/${Math.max(1, mainSlotCount)} số${detail?.specialHit ? " + số phụ" : ""}`;
      return `<span class="predict-ticket-meta">${prefix}${escapeHtml(algorithmLabel)} - ${escapeHtml(hitText)}</span>`;
    }

    function isPredictionHistoryBaoTicket(ticket) {
      const cloned = clonePredictionTicket(ticket);
      return !!cloned && String(cloned.playMode || "").trim().toLowerCase() === "bao";
    }

    function formatPredictionHistoryTicketLabel(ticket, index) {
      const cloned = clonePredictionTicket(ticket);
      if (!cloned) return `Bộ ${index + 1}`;
      const isBao = String(cloned.playMode || "").trim().toLowerCase() === "bao";
      if (!isBao) return `Bộ ${index + 1}`;
      const baoLevel = cloned.baoLevel || cloned.main.length || "";
      return `Bộ ${index + 1} • Bao ${baoLevel}`.trim();
    }

    function formatPredictionHistoryTicketHtml(type, ticket, index, entry) {
      const cloned = clonePredictionTicket(ticket);
      if (!cloned) return "";
      const label = `<span class="predict-hit-label">${escapeHtml(formatPredictionHistoryTicketLabel(cloned, index))}:</span>`;
      const isBao = isPredictionHistoryBaoTicket(cloned);
      const mainHtml = renderPredictionHistoryNumberList(cloned.main, entry, { perRow: isBao ? 10 : 0 });
      const metaHtml = formatPredictionHistoryTicketMeta(type, index, entry, { divider: !isBao });
      if (isBao) {
        const specialHtml = TYPES[type]?.hasSpecial && Number.isInteger(cloned.special)
          ? `<span class="predict-history-bao-special" aria-label="Số đặc biệt"><span class="predict-hit-divider" aria-hidden="true">|</span>${renderPredictionHistoryNumberList([cloned.special], entry, { special: true })}</span>`
          : "";
        return `${label}<span class="predict-history-bao-main">${mainHtml}</span>${specialHtml}${metaHtml}`;
      }
      if (type === "KENO") {
        return `${label}${mainHtml}${metaHtml}`;
      }
      if (TYPES[type]?.hasSpecial && Number.isInteger(cloned.special)) {
        return `${label}${mainHtml}<span class="predict-hit-divider" aria-hidden="true">|</span>${renderPredictionHistoryNumberList([cloned.special], entry, { special: true })}${metaHtml}`;
      }
      return `${label}${mainHtml}${metaHtml}`;
    }

    function formatPredictionHistoryRankingLine(label, numbers, entry, { special = false } = {}) {
      const perRow = (entry?.type === "KENO" || TYPES[entry?.type]?.threeDigit) && !special ? 10 : 0;
      const html = renderPredictionHistoryNumberList(numbers, entry, { special, perRow });
      if (!html) return "";
      return `<div class="predict-history-line${perRow ? " predict-history-line-keno" : ""}"><strong>${escapeHtml(label)}:</strong> ${html}</div>`;
    }

    function formatPredictionHistoryPlainNumberRows(numbers, perRow = 0, type = "") {
      const values = (numbers || []).map(Number).filter(Number.isInteger).map(number => formatPredictNumber(number, type));
      if (!values.length) return "";
      if (!Number.isInteger(perRow) || perRow <= 0 || values.length <= perRow) {
        return values.join(" ");
      }
      const rows = [];
      for (let index = 0; index < values.length; index += perRow) {
        rows.push(values.slice(index, index + perRow).join(" "));
      }
      return rows.join("\n");
    }

    function formatPredictionHistoryActualDrawHtml(entry) {
      if (!entry?.resolved || !entry?.actualDraw) return "";
      if (entry.type === "KENO" && Array.isArray(entry.actualDraw.main) && entry.actualDraw.main.length) {
        const html = renderPredictionHistoryNumberList(entry.actualDraw.main, entry, { perRow: 10, highlight: false });
        return html ? `<div class="predict-history-line predict-history-line-keno"><strong>Kết quả thật:</strong> ${html}</div>` : "";
      }
      if (Array.isArray(entry.actualDraw.main) && entry.actualDraw.main.length) {
        const mainHtml = renderPredictionHistoryNumberList(entry.actualDraw.main, entry, { highlight: false });
        const specialHtml = TYPES[entry.type]?.hasSpecial && Number.isInteger(Number(entry.actualDraw.special))
          ? `<span class="predict-hit-divider" aria-hidden="true">|</span>${renderPredictionHistoryNumberList([entry.actualDraw.special], entry, { special: true, highlight: false })}`
          : "";
        return `<div class="predict-history-line"><strong>Kết quả thật:</strong> ${mainHtml}${specialHtml}</div>`;
      }
      const fallbackText = String(formatLiveHistoryDraw(entry.type, entry.actualDraw) || "")
        .replace(/ĐB|DB/giu, "")
        .replace(/\s{2,}/g, " ")
        .trim();
      return `<div class="predict-history-line"><strong>Kết quả thật:</strong> ${escapeHtml(fallbackText)}</div>`;
    }

    function formatPredictionHistoryTicketMetaPlainText(type, index, entry) {
      const rawSource = String(entry?.ticketSources?.[index] || "").trim().toLowerCase();
      const algorithmLabel = rawSource === "luan_so"
        ? "Luận Số"
        : rawSource === "gen_local"
        ? "AI GEN"
        : String(entry?.championLabel || entry?.modelLabel || entry?.strategyLabel || entry?.engineLabel || "AI Gen").trim();
      if (!algorithmLabel) return "";
      const detail = Array.isArray(entry?.resultSummary?.details) ? entry.resultSummary.details[index] : null;
      if (!entry?.resolved || !detail) {
        return ` | ${algorithmLabel} - ${getPredictionHistoryEntryStatus(entry).shortLabel}`;
      }
      const mainSlotCount = Array.isArray(detail?.main) ? detail.main.length : (Array.isArray(entry?.tickets?.[index]?.main) ? entry.tickets[index].main.length : 0);
      const mainHits = Math.max(0, Number(detail?.mainHits || 0));
      return ` | ${algorithmLabel} - ${mainHits}/${Math.max(1, mainSlotCount)} số${detail?.specialHit ? " + số phụ" : ""}`;
    }

    function formatPredictionHistoryTicketPlainText(type, ticket, index, entry) {
      const cloned = clonePredictionTicket(ticket);
      if (!cloned) return "";
      const mainText = cloned.main.map(number => formatPredictNumber(number, type)).join(TYPES[type]?.threeDigit ? " | " : " ");
      const prefix = formatPredictionHistoryTicketLabel(cloned, index);
      const metaText = formatPredictionHistoryTicketMetaPlainText(type, index, entry);
      if (type === "KENO") {
        return `${prefix}: ${mainText}${metaText}`;
      }
      if (TYPES[type]?.hasSpecial && Number.isInteger(cloned.special)) {
        return `${prefix}: ${mainText} | ${formatPredictNumber(cloned.special, type)}${metaText}`;
      }
      return `${prefix}: ${mainText}${metaText}`;
    }

    function buildPredictionHistoryCopyText(entry) {
      if (!entry || typeof entry !== "object") return "";
      const titleParts = [entry.typeLabel || TYPES[entry.type]?.label || entry.type || "Không rõ loại"];
      if (entry.predictedKy) titleParts.push(`Kỳ ${formatLiveKy(entry.predictedKy)}`);
      const headerLines = [
        titleParts.join(" • "),
        `Dự đoán: ${titleParts.join(" • ")}`,
        `Thời gian: ${formatPredictionHistoryTime(entry.createdAt) || "Không rõ"}`,
      ];
      const ticketLines = [];
      if (Array.isArray(entry.tickets) && entry.tickets.length) {
        entry.tickets.forEach((ticket, index) => {
          const ticketText = formatPredictionHistoryTicketPlainText(entry.type, ticket, index, entry);
          if (ticketText) ticketLines.push(ticketText);
        });
      }
      const topLines = [];
      if (Array.isArray(entry.topMainRanking) && entry.topMainRanking.length) {
        const topRows = formatPredictionHistoryPlainNumberRows(entry.topMainRanking, 10, entry.type);
        const topParts = topRows.split("\n").filter(Boolean);
        if (topParts.length) {
          topLines.push("Top số:");
          topParts.forEach(part => topLines.push(part));
        }
      }
      if (TYPES[entry.type]?.hasSpecial && Array.isArray(entry.topSpecialRanking) && entry.topSpecialRanking.length) {
        const specialRows = formatPredictionHistoryPlainNumberRows(entry.topSpecialRanking, 10, entry.type);
        const specialParts = specialRows.split("\n").filter(Boolean);
        if (specialParts.length) {
          topLines.push(`Top ĐB: ${specialParts.shift()}`);
          specialParts.forEach(part => topLines.push(part));
        }
      }
      const sections = [
        headerLines.join("\n"),
        ticketLines.join("\n"),
        topLines.join("\n"),
      ].filter(section => String(section || "").trim());
      return sections.join("\n\n");
    }

    async function copyTextToClipboard(text) {
      const value = String(text || "").trim();
      if (!value) return false;
      try {
        if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(value);
          return true;
        }
      } catch {}
      try {
        const textarea = document.createElement("textarea");
        textarea.value = value;
        textarea.setAttribute("readonly", "readonly");
        textarea.style.position = "fixed";
        textarea.style.top = "-9999px";
        textarea.style.left = "-9999px";
        document.body.appendChild(textarea);
        textarea.select();
        textarea.setSelectionRange(0, textarea.value.length);
        const copied = document.execCommand("copy");
        textarea.remove();
        return !!copied;
      } catch {
        return false;
      }
    }

    function formatPredictionHistorySummary(type, entry) {
      const summary = entry?.resultSummary;
      if (!summary || typeof summary !== "object") return "Chưa có dữ liệu đối chiếu.";
      const isBaoMode = getPredictionHistoryEntryPlayMode(entry) === "bao";
      const unitLabel = isBaoMode ? "bộ" : "vé";
      const parts = [];
      const totalPrizeAmount = Number(summary.totalPrizeAmount || 0);
      if (totalPrizeAmount > 0) {
        const minimumLabel = summary.hasVariablePrize ? " tối thiểu" : "";
        parts.push(`Tổng tiền trúng${minimumLabel} ${formatPrizeCurrency(totalPrizeAmount)}`);
      } else if (Number(summary.prizeTicketHits || 0) > 0) {
        parts.push(`${summary.prizeTicketHits} ${unitLabel} có giải (xem bảng thưởng)`);
      } else {
        parts.push(`Tổng tiền trúng ${formatPrizeCurrency(0)}`);
      }
      const prizeBreakdown = Array.isArray(summary.prizeBreakdown)
        ? [...summary.prizeBreakdown].sort((a, b) => (
            Number(b?.unitAmount || 0) - Number(a?.unitAmount || 0)
            || Number(b?.totalAmount || 0) - Number(a?.totalAmount || 0)
          ))
        : [];
      if (prizeBreakdown.length) {
        const breakdownText = prizeBreakdown
          .filter(item => Number(item?.count || 0) > 0)
          .map(item => `${item.label}: ${item.count} ${unitLabel}`)
          .join("; ");
        if (breakdownText) parts.push(breakdownText);
      }
      const losingTicketCount = Number.isFinite(Number(summary.losingTicketCount))
        ? Math.max(0, Number(summary.losingTicketCount))
        : Math.max(0, Number(summary.ticketCount || 0) - Number(summary.prizeTicketHits || 0));
      if (Number(summary.ticketCount || 0) > 0) {
        parts.push(`${losingTicketCount} ${unitLabel} trượt`);
      }
      if (TYPES[type]?.hasSpecial && Number(summary.specialHits || 0) > 0) {
        parts.push(`${summary.specialHits} ${unitLabel} trúng số phụ`);
      }
      return parts.length ? parts.join(" • ") : "Chưa có số khớp nổi bật.";
    }

    function buildPredictionHistoryCumulativeSummary(type, entries) {
      const scoredEntries = (Array.isArray(entries) ? entries : []).filter(entry => (
        entry?.resolved
        && entry?.actualDraw
        && Array.isArray(entry?.tickets)
      ));
      const mainHitCounts = new Map();
      let total = 0;
      let maxMainHits = 0;
      let specialTotal = 0;
      let specialHits = 0;
      scoredEntries.forEach(entry => {
        const drawMainCount = Array.isArray(entry.actualDraw?.main) ? entry.actualDraw.main.length : 0;
        const largestTicketSize = entry.tickets.reduce((largest, ticket) => (
          Math.max(largest, Array.isArray(ticket?.main) ? ticket.main.length : 0)
        ), 0);
        maxMainHits = Math.max(
          maxMainHits,
          drawMainCount ? Math.min(drawMainCount, largestTicketSize) : largestTicketSize,
        );
        const cachedDetails = Array.isArray(entry.resultSummary?.details) ? entry.resultSummary.details : [];
        const details = cachedDetails.length === entry.tickets.length
          ? cachedDetails
          : entry.tickets.map(ticket => ({
              mainHits: countMainMatch(ticket?.main || [], entry.actualDraw.main || []),
              special: ticket?.special,
              specialHit: TYPES[type]?.hasSpecial
                && Number.isInteger(ticket?.special)
                && ticket.special === entry.actualDraw.special,
            }));
        details.forEach(detail => {
          const mainHits = Math.max(0, Number(detail?.mainHits || 0));
          maxMainHits = Math.max(maxMainHits, mainHits);
          mainHitCounts.set(mainHits, Number(mainHitCounts.get(mainHits) || 0) + 1);
          total += 1;
          if (TYPES[type]?.hasSpecial && Number.isInteger(detail?.special)) {
            specialTotal += 1;
            if (detail.specialHit) specialHits += 1;
          }
        });
      });
      if (!total) return null;
      return {
        total,
        unitLabel: getPredictionHistoryEntryPlayMode(scoredEntries[0]) === "bao" ? "bộ" : "vé",
        mainHitCounts: Array.from({ length: maxMainHits + 1 }, (_, hitCount) => ({
          hitCount,
          count: Number(mainHitCounts.get(hitCount) || 0),
        })),
        specialTotal,
        specialHits,
        specialMisses: Math.max(0, specialTotal - specialHits),
      };
    }

    function formatPredictionHistoryCumulativeRates(type, entries, previousEntries = []) {
      const summary = buildPredictionHistoryCumulativeSummary(type, entries);
      if (!summary) return null;
      const previous = buildPredictionHistoryCumulativeSummary(type, previousEntries);
      const previousMainCounts = new Map(
        (previous?.mainHitCounts || []).map(item => [Number(item.hitCount || 0), Number(item.count || 0)])
      );
      const items = summary.mainHitCounts.map(item => {
        const rate = item.count * 100 / summary.total;
        const previousRate = previous?.total
          ? Number(previousMainCounts.get(item.hitCount) || 0) * 100 / previous.total
          : null;
        return {
          label: item.hitCount === 0 ? "Trượt" : `${item.hitCount} số`,
          count: item.count,
          total: summary.total,
          rate,
          trend: Number.isFinite(previousRate) ? buildPredictionTrend(rate, previousRate) : null,
        };
      });
      if (TYPES[type]?.hasSpecial && summary.specialTotal) {
        const specialRate = summary.specialHits * 100 / summary.specialTotal;
        const previousSpecialRate = previous?.specialTotal
          ? previous.specialHits * 100 / previous.specialTotal
          : null;
        items.push({
          label: "ĐB",
          count: summary.specialHits,
          total: summary.specialTotal,
          rate: specialRate,
          trend: Number.isFinite(previousSpecialRate) ? buildPredictionTrend(specialRate, previousSpecialRate) : null,
        });
      }
      const html = items.map(item => {
        const isSame = item.trend?.direction === "same";
        const labelHtml = item.label === "ĐB" ? "<strong>ĐB</strong>" : escapeHtml(item.label);
        const valueHtml = `<span class="prediction-rate-item${isSame ? " same" : ""}">${labelHtml} ${escapeHtml(formatPredictionPercent(item.rate))}</span>`;
        const trendHtml = item.trend && !isSame ? ` ${formatPredictionTrendHtml(item.trend)}` : "";
        return `${valueHtml}${trendHtml}`;
      }).join(" • ");
      return { ...summary, items, html };
    }

    function syncLedgerRowsIntoPredictionHistory(type, rows) {
      const logs = ensurePredictionLogBucket(type);
      if (!logs.length || !Array.isArray(rows) || !rows.length) return false;
      const byPredictionId = new Map(
        rows
          .filter(row => String(row?.prediction_id || "").trim())
          .map(row => [String(row.prediction_id).trim(), row])
      );
      const claimedPredictionIds = new Set();
      const findLegacyLedgerRow = entry => {
        const entryTime = Date.parse(String(entry?.createdAt || "")) || 0;
        if (!entryTime) return null;
        const entryMode = normalizePredictionMode(entry?.predictionMode || PREDICTION_MODE_NORMAL);
        return rows
          .filter(row => {
            const rowId = String(row?.prediction_id || "").trim();
            if (!rowId || claimedPredictionIds.has(rowId)) return false;
            if (normalizePredictionMode(row?.prediction_mode || PREDICTION_MODE_NORMAL) !== entryMode) return false;
            const rowTime = Date.parse(String(row?.created_at || "")) || 0;
            return rowTime && Math.abs(rowTime - entryTime) <= 120000;
          })
          .sort((a, b) => {
            const targetKy = kySortValue(entry?.predictedKyOriginal || entry?.predictedKy);
            const aTargetDelta = targetKy && kySortValue(a?.target_draw_id) === targetKy ? 0 : 1;
            const bTargetDelta = targetKy && kySortValue(b?.target_draw_id) === targetKy ? 0 : 1;
            if (aTargetDelta !== bTargetDelta) return aTargetDelta - bTargetDelta;
            return Math.abs((Date.parse(String(a?.created_at || "")) || 0) - entryTime)
              - Math.abs((Date.parse(String(b?.created_at || "")) || 0) - entryTime);
          })[0] || null;
      };
      let changed = false;
      logs.forEach(entry => {
        const predictionId = String(entry?.predictionId || "").trim();
        const row = byPredictionId.get(predictionId) || (!predictionId ? findLegacyLedgerRow(entry) : null);
        if (!row) return;
        const resolvedPredictionId = String(row.prediction_id || predictionId).trim();
        if (resolvedPredictionId) claimedPredictionIds.add(resolvedPredictionId);
        const payload = row.payload && typeof row.payload === "object" ? row.payload : {};
        const scoreMetrics = row.score_metrics && typeof row.score_metrics === "object" ? row.score_metrics : {};
        const nextScoreMetrics = row.latest_score_id
          ? {
              ...scoreMetrics,
              hit_count: Number(row.score_hit_count || 0),
              special_hit: Number(row.score_special_hit || 0),
              brier_score: Number(row.score_brier_score || 0),
              log_loss: Number(row.score_log_loss || 0),
              lift: Number(row.score_lift || 0),
              actual_draw_id: String(row.actual_draw_id || ""),
              scored_at: String(row.scored_at || ""),
            }
          : null;
        const updates = {
          predictionId: resolvedPredictionId,
          predictionStatus: String(row.status || entry.predictionStatus || ""),
          dataCutoffDrawId: String(row.data_cutoff_draw_id || entry.dataCutoffDrawId || ""),
          payloadChecksum: String(row.payload_checksum || entry.payloadChecksum || ""),
          modelVersion: String(row.model_version || payload.modelVersion || entry.modelVersion || ""),
          probabilitySummary: payload.probabilitySummary || entry.probabilitySummary || null,
          calibratedProbability: Array.isArray(payload.calibratedProbability)
            ? payload.calibratedProbability
            : entry.calibratedProbability,
          specialCalibratedProbability: Array.isArray(payload.specialCalibratedProbability)
            ? payload.specialCalibratedProbability
            : entry.specialCalibratedProbability,
          scoreMetrics: nextScoreMetrics,
        };
        Object.entries(updates).forEach(([key, value]) => {
          if (JSON.stringify(entry[key] ?? null) === JSON.stringify(value ?? null)) return;
          entry[key] = value;
          changed = true;
        });
      });
      return changed;
    }

    async function refreshPredictionLedgerForHistory(type) {
      if (IS_LOCAL_MODE || !ML_PREDICTION_LOG_TYPES.has(type)) return false;
      try {
        const response = await api(`/api/ml/predictions?type=${encodeURIComponent(type)}`);
        return syncLedgerRowsIntoPredictionHistory(type, response?.predictions || []);
      } catch (error) {
        if ([404, 405].includes(Number(error?.status || 0))) return false;
        throw error;
      }
    }

    async function scorePendingPredictionLedger(type) {
      if (IS_LOCAL_MODE || !ML_PREDICTION_LOG_TYPES.has(type)) return false;
      try {
        const response = await api("/api/ml/score-pending", "POST", { type });
        return Array.isArray(response?.scored) && response.scored.length > 0;
      } catch (error) {
        if ([404, 405].includes(Number(error?.status || 0))) return false;
        throw error;
      }
    }

    async function fetchPredictionHistoryDraws(type) {
      const logs = Array.isArray(store.predictionLogs?.[type]) ? store.predictionLogs[type] : [];
      const drawIds = [...new Set(logs
        .filter(entry => !entry?.resolved || !entry?.actualDraw)
        .map(entry => String(normalizeKy(entry?.predictedKy) || "").replace(/\D/g, ""))
        .filter(Boolean))]
        .slice(-MAX_PREDICTION_LOGS_PER_TYPE);
      if (!drawIds.length || IS_LOCAL_MODE) return getLiveHistoryFeed(type);
      const params = new URLSearchParams({
        type,
        count: "all",
        drawIds: drawIds.join(","),
      });
      const res = await api(`/api/live-history?${params.toString()}`);
      const nextFeed = buildLiveHistoryFeedFromResponse(
        type,
        Array.isArray(res?.history) ? res.history : [],
        String(res?.fetchedAt || ""),
        String(res?.count || "selected"),
        {
          canonicalCount: res?.canonicalCount,
          canonicalFile: res?.canonicalFile,
          allCount: res?.allCount,
          todayCount: res?.todayCount,
          allFile: res?.allFile,
          todayFile: res?.todayFile,
          latestKy: res?.latestKy,
          latestDate: res?.latestDate,
          latestTime: res?.latestTime,
        }
      );
      // Keep draws returned by the preceding canonical-repair request.  The
      // targeted drawIds request can legitimately return only a subset (and
      // older running servers may ignore that parameter), so replacing the
      // feed here used to discard a result that had just been downloaded.
      const mergedFeed = cloneLiveHistoryFeed(getLiveHistoryFeed(type));
      for (const ky of (nextFeed.order || [])) {
        mergeLiveHistoryDraw(mergedFeed, ky, nextFeed.results?.[ky]);
      }
      Object.assign(mergedFeed, {
        loadedAt: nextFeed.loadedAt || mergedFeed.loadedAt,
        countKey: nextFeed.countKey || mergedFeed.countKey,
        canonicalCount: Math.max(mergedFeed.canonicalCount || 0, nextFeed.canonicalCount || 0),
        allCount: Math.max(mergedFeed.allCount || 0, nextFeed.allCount || 0),
        todayCount: Math.max(mergedFeed.todayCount || 0, nextFeed.todayCount || 0),
        canonicalFile: nextFeed.canonicalFile || mergedFeed.canonicalFile,
        allFile: nextFeed.allFile || mergedFeed.allFile,
        todayFile: nextFeed.todayFile || mergedFeed.todayFile,
        latestKy: nextFeed.latestKy || mergedFeed.latestKy,
        latestDate: nextFeed.latestDate || mergedFeed.latestDate,
        latestTime: nextFeed.latestTime || mergedFeed.latestTime,
      });
      setLiveHistoryFeed(type, mergedFeed);
      return getLiveHistoryFeed(type);
    }

    async function repairPredictionHistoryCanonical(type) {
      if (IS_LOCAL_MODE) return null;
      const params = new URLSearchParams({
        type,
        count: type === "KENO" ? "today" : "20",
        repair: "1",
        recentDays: type === "KENO" ? "2" : "15",
      });
      const response = await api(`/api/live-history?${params.toString()}`);
      const errors = [
        ...(Array.isArray(response?.repairErrors) ? response.repairErrors : []),
        ...(Array.isArray(response?.errors) ? response.errors : []),
      ].map(error => String(error?.message || error || "").trim()).filter(Boolean);
      if (errors.length) {
        throw new Error(`Không thể cập nhật dữ liệu ${TYPES[type]?.label || type}: ${errors.join(" | ")}`);
      }
      // The repair endpoint already returns fresh history.  Store it before
      // the follow-up targeted fetch so reconciliation can use it immediately.
      const repairedFeed = buildLiveHistoryFeedFromResponse(
        type,
        Array.isArray(response?.history) ? response.history : [],
        String(response?.fetchedAt || ""),
        String(response?.count || "20"),
        response || {},
      );
      if (repairedFeed.order.length) setLiveHistoryFeed(type, repairedFeed);
      return response;
    }

    function getPendingPredictionDrawLabels(type) {
      return (Array.isArray(store.predictionLogs?.[type]) ? store.predictionLogs[type] : [])
        .filter(entry => entry && !entry.resolved && normalizeKy(entry.predictedKy))
        .map(entry => formatLiveKy(entry.predictedKy))
        .filter(Boolean);
    }

    async function refreshPredictionHistoryData(type, { silent = true, repairCanonical = false } = {}) {
      const normalizedType = normalizePredictionHistoryType(type);
      const before = getPredictionLogsSignature(store.predictionLogs?.[normalizedType] || []);
      if (repairCanonical) await repairPredictionHistoryCanonical(normalizedType);
      await fetchPredictionHistoryDraws(normalizedType);

      let ledgerScored = false;
      if (repairCanonical && ML_PREDICTION_LOG_TYPES.has(normalizedType)) {
        ledgerScored = await scorePendingPredictionLedger(normalizedType);
      }
      const ledgerChanged = await refreshPredictionLedgerForHistory(normalizedType);
      reconcilePredictionLogsForType(normalizedType);
      const logsChanged = getPredictionLogsSignature(store.predictionLogs?.[normalizedType] || []) !== before;
      if (ledgerScored || ledgerChanged || logsChanged) saveStore();

      if (repairCanonical) {
        const pendingDraws = [...new Set(getPendingPredictionDrawLabels(normalizedType))];
        if (pendingDraws.length) {
          const feed = getLiveHistoryFeed(normalizedType);
          const latestKy = formatLiveKy(feed?.latestKy || "");
          const pendingText = pendingDraws.slice(0, 3).join(", ");
          const moreText = pendingDraws.length > 3 ? ` và ${pendingDraws.length - 3} kỳ khác` : "";
          throw new Error(`Chưa tìm thấy kết quả cho kỳ ${pendingText}${moreText}.${latestKy ? ` Dữ liệu mới nhất hiện có: kỳ ${latestKy}.` : ""}`);
        }
      }
      return { ledgerScored, ledgerChanged, logsChanged };
    }

    async function refreshKenoPredictionDataForHistory({ silent = true } = {}) {
      return refreshPredictionHistoryData("KENO", { silent, repairCanonical: !silent });
    }

    async function refreshPredictionHistoryType(type, { silent = true, repairCanonical = false } = {}) {
      const normalizedType = normalizePredictionHistoryType(type);
      if (!PREDICTION_LOG_TYPES.includes(normalizedType)) return;
      if (normalizedType === "KENO") {
        return refreshPredictionHistoryData("KENO", { silent, repairCanonical });
      }
      return refreshPredictionHistoryData(normalizedType, { silent, repairCanonical });
    }

    async function startPredictionHistoryRefresh(type, { silent = true, repairCanonical = false } = {}) {
      const normalizedType = normalizePredictionHistoryType(type);
      const refreshToken = ++predictionHistoryRefreshToken;
      predictionHistoryLoading = true;
      predictionHistoryLoadingType = normalizedType;
      predictionHistoryLoadingError = "";
      setPredictionHistoryRefreshButtonBusy(true);
      renderPredictionHistoryPanel();
      try {
        await refreshPredictionHistoryType(normalizedType, { silent, repairCanonical });
        if (refreshToken !== predictionHistoryRefreshToken) return;
        predictionHistoryLoading = false;
        predictionHistoryLoadingType = "";
        predictionHistoryLoadingError = "";
      } catch (error) {
        if (refreshToken !== predictionHistoryRefreshToken) return;
        predictionHistoryLoading = false;
        predictionHistoryLoadingType = normalizedType;
        predictionHistoryLoadingError = String(error?.message || error || "Không tải được lịch sử.");
      } finally {
        if (refreshToken !== predictionHistoryRefreshToken) return;
        setPredictionHistoryRefreshButtonBusy(false);
        renderPredictionHistoryPanel();
      }
    }

    function setPredictionHistoryRefreshButtonBusy(isBusy) {
      const btn = document.getElementById("predictionHistoryRefreshBtn");
      if (!btn) return;
      const originalText = btn.dataset.originalText || String(btn.textContent || "Cập Nhật");
      btn.dataset.originalText = originalText;
      btn.disabled = !!isBusy;
      btn.textContent = isBusy ? "Đang Cập Nhật..." : originalText;
    }

    function collectPredictionHistoryEntries(filterType = "KENO", rangeKey = "all", playModeKey = "normal", baoLevelKey = "all", predictionMode = PREDICTION_MODE_NORMAL) {
      const selectedType = normalizePredictionHistoryType(filterType);
      const selectedRange = normalizePredictionHistoryRange(rangeKey, selectedType);
      const selectedPredictionMode = normalizePredictionMode(predictionMode);
      const selectedPlayMode = hasPredictBaoMode(selectedType)
        ? normalizePredictionHistoryPlayMode(playModeKey)
        : "normal";
      const selectedBaoLevel = selectedPlayMode === "bao"
        ? normalizePredictionHistoryBaoLevel(baoLevelKey)
        : "all";
      if (!PREDICTION_LOG_TYPES.includes(selectedType)) return [];
      const groupedRows = new Map();
      ensurePredictionLogBucket(selectedType).forEach(entry => {
        const normalizedRankings = normalizePredictionTopRankings(
          selectedType,
          entry?.topMainRanking,
          entry?.topSpecialRanking,
          entry?.tickets,
        );
        const normalizedEntry = {
          type: selectedType,
          typeLabel: TYPES[selectedType]?.label || selectedType,
          ...entry,
          topMainRanking: normalizedRankings.main,
          topSpecialRanking: normalizedRankings.special,
        };
        if (getPredictionEntryMode(normalizedEntry) !== selectedPredictionMode) return;
        const entryPlayMode = getPredictionHistoryEntryPlayMode(normalizedEntry);
        if (entryPlayMode !== selectedPlayMode) return;
        const normalizedKy = normalizeKy(normalizedEntry?.predictedKy);
        const runIdentity = String(
          normalizedEntry?.predictionId
          || normalizedEntry?.id
          || `${normalizedKy || "unknown"}:${normalizedEntry?.createdAt || Math.random()}`
        );
        const dedupeKeyParts = [
          runIdentity,
          entryPlayMode,
        ];
        if (entryPlayMode === "bao") {
          dedupeKeyParts.push(String(getPredictionEntryBaoLevelForMetrics(normalizedEntry) || 0));
          dedupeKeyParts.push(String(getPredictionHistoryEntryBundleCount(normalizedEntry) || 0));
        }
        const dedupeKey = dedupeKeyParts.join("::");
        const nextTicketCount = Array.isArray(normalizedEntry?.tickets) ? normalizedEntry.tickets.length : 0;
        const current = groupedRows.get(dedupeKey);
        if (!current) {
          groupedRows.set(dedupeKey, normalizedEntry);
          return;
        }
        const currentResolved = !!current?.resolved;
        const nextResolved = !!normalizedEntry?.resolved;
        if (nextResolved && !currentResolved) {
          groupedRows.set(dedupeKey, normalizedEntry);
          return;
        }
        if (currentResolved && !nextResolved) {
          return;
        }
        const currentTicketCount = Array.isArray(current?.tickets) ? current.tickets.length : 0;
        if (nextTicketCount > currentTicketCount) {
          groupedRows.set(dedupeKey, normalizedEntry);
          return;
        }
        if (nextTicketCount < currentTicketCount) {
          return;
        }
        const currentTime = Date.parse(current?.createdAt || 0) || 0;
        const nextTime = Date.parse(normalizedEntry?.createdAt || 0) || 0;
        if (nextTime >= currentTime) groupedRows.set(dedupeKey, normalizedEntry);
      });
      const sortedEntries = [...groupedRows.values()]
        .filter(entry => isPredictionHistoryEntryInRange(entry, selectedRange, selectedType))
        .filter(entry => selectedBaoLevel === "all" || getPredictionEntryBaoLevelForMetrics(entry) === Number(selectedBaoLevel))
        .sort((a, b) => {
        const aTime = Date.parse(a?.createdAt || 0) || 0;
        const bTime = Date.parse(b?.createdAt || 0) || 0;
        if (aTime !== bTime) return bTime - aTime;
        return kySortValue(b?.predictedKy) - kySortValue(a?.predictedKy);
      });
      const rangeLimit = getPredictionHistoryRangeLimit(selectedRange, selectedType);
      return rangeLimit ? sortedEntries.slice(0, rangeLimit) : sortedEntries;
    }

    function getPredictionHistoryEntryKey(entry) {
      if (!entry || typeof entry !== "object") return "";
      return [
        getPredictionEntryMode(entry),
        normalizePredictionHistoryType(entry.type || predictionHistorySelectedType),
        normalizeKy(entry.predictedKy) || "",
        String(entry.createdAt || ""),
      ].join("::");
    }

    function getPredictionHistoryCollapsedTicketLimit(type) {
      if (type === "KENO") return 10;
      return 12;
    }

    function shouldCollapsePredictionHistoryEntry(entry) {
      const ticketCount = Array.isArray(entry?.tickets) ? entry.tickets.length : 0;
      const hasSpecialTop = TYPES[entry?.type]?.hasSpecial && Array.isArray(entry?.topSpecialRanking) && entry.topSpecialRanking.length;
      return ticketCount > getPredictionHistoryCollapsedTicketLimit(entry?.type) || hasSpecialTop || entry?.type === "KENO";
    }

    function syncPredictionHistoryBodyScroll(isOpen = predictionHistoryPanelOpen || vipPredictionHistoryPanelOpen) {
      if (isOpen) {
        document.body.style.overflow = "hidden";
        document.documentElement.style.overflow = "hidden";
        return;
      }
      document.body.style.overflow = "";
      document.documentElement.style.overflow = "";
    }

    function clampPredictionHistoryCurrentIndex(totalEntries = 0) {
      const total = Math.max(0, Number(totalEntries || 0));
      if (!Number.isInteger(predictionHistoryCurrentIndex) || predictionHistoryCurrentIndex < 0) {
        predictionHistoryCurrentIndex = 0;
      }
      if (!total) {
        predictionHistoryCurrentIndex = 0;
        return 0;
      }
      if (predictionHistoryCurrentIndex > total - 1) {
        predictionHistoryCurrentIndex = total - 1;
      }
      return predictionHistoryCurrentIndex;
    }

    function renderPredictionHistoryNavigator(totalEntries = 0) {
      const prevBtn = document.getElementById("predictionHistoryPrevBtn");
      const nextBtn = document.getElementById("predictionHistoryNextBtn");
      const positionEl = document.getElementById("predictionHistoryPosition");
      const total = Math.max(0, Number(totalEntries || 0));
      const currentIndex = clampPredictionHistoryCurrentIndex(total);
      if (positionEl) {
        positionEl.textContent = total ? `${currentIndex + 1} / ${total}` : "0 / 0";
      }
      if (prevBtn) prevBtn.disabled = total <= 1 || currentIndex <= 0;
      if (nextBtn) nextBtn.disabled = total <= 1 || currentIndex >= total - 1;
    }

    function renderPredictionHistoryEntryHtml(entry, entryIndex, historyEntries = []) {
      const statusMeta = getPredictionHistoryEntryStatus(entry);
      const statusClass = statusMeta.className;
      const statusText = statusMeta.label;
      const countdownState = buildPredictionHistoryCountdownState(entry, getSyncedNowDate());
      const titleParts = [String(entry.typeLabel || "").replace(/_/g, " ")];
      if (entry.predictedKy) titleParts.push(`Kỳ ${formatLiveKy(entry.predictedKy)}`);
      const createdAtText = formatPredictionHistoryTime(entry.createdAt) || "Không rõ";
      const engineParts = [
        String(entry.engineLabel || "").trim(),
        String(entry.engineKey || "").trim().toLowerCase() === "both" ? String(entry.riskModeLabel || getPredictRiskModeMeta(entry.riskMode || "balanced").label).trim() : "",
        String(entry.championLabel || entry.modelLabel || "").trim(),
      ].filter(Boolean);
      const topMainRanking = Array.isArray(entry.topMainRanking)
        ? entry.topMainRanking
        : [];
      const topSpecialRanking = Array.isArray(entry.topSpecialRanking)
        ? entry.topSpecialRanking
        : [];
      const primaryInfoCards = [
        `<div class="predict-history-info-chip"><span class="predict-history-info-label">Thời gian</span><strong class="predict-history-info-value">${escapeHtml(createdAtText)}</strong></div>`,
        engineParts.length
          ? `<div class="predict-history-info-chip"><span class="predict-history-info-label">Cấu hình AI</span><strong class="predict-history-info-value">${escapeHtml(engineParts.join(" • "))}</strong></div>`
          : "",
        entry.predictionStatus
          ? `<div class="predict-history-info-chip"><span class="predict-history-info-label">Trạng thái</span><strong class="predict-history-info-value">${escapeHtml(String(entry.predictionStatus).toUpperCase())}</strong></div>`
          : "",
        entry.dataCutoffDrawId
          ? `<div class="predict-history-info-chip"><span class="predict-history-info-label">Dữ liệu đến kỳ</span><strong class="predict-history-info-value">${escapeHtml(formatLiveKy(entry.dataCutoffDrawId))}</strong></div>`
          : "",
        entry.modelVersion
          ? `<div class="predict-history-info-chip"><span class="predict-history-info-label">Mô hình</span><strong class="predict-history-info-value">${escapeHtml(entry.modelVersion)}</strong></div>`
          : "",
        Number(entry.probabilitySummary?.mainProbabilitySum || 0) > 0
          ? `<div class="predict-history-info-chip"><span class="predict-history-info-label">Tổng xác suất</span><strong class="predict-history-info-value">${escapeHtml(`Σp=${Number(entry.probabilitySummary.mainProbabilitySum || 0).toFixed(2)}`)}</strong></div>`
          : "",
      ].filter(Boolean).join("");
      const metricInfoCards = [
        Number(entry.ticketQualityScore || 0) > 0
          ? `<div class="predict-history-info-chip"><span class="predict-history-info-label">Điểm chất lượng</span><strong class="predict-history-info-value">${escapeHtml(Number(entry.ticketQualityScore || 0).toFixed(2))}</strong></div>`
          : "",
        entry.scoreMetrics
          ? `<div class="predict-history-info-chip"><span class="predict-history-info-label">Trung bình trúng</span><strong class="predict-history-info-value">${escapeHtml(Number(entry.scoreMetrics.hit_count || 0).toFixed(0))}</strong></div>`
          : "",
        Number(entry.scoreMetrics?.brier_score || 0) > 0
          ? `<div class="predict-history-info-chip"><span class="predict-history-info-label">Brier</span><strong class="predict-history-info-value">${escapeHtml(Number(entry.scoreMetrics.brier_score).toFixed(5))}</strong></div>`
          : "",
        Number(entry.scoreMetrics?.log_loss || 0) > 0
          ? `<div class="predict-history-info-chip"><span class="predict-history-info-label">Log Loss</span><strong class="predict-history-info-value">${escapeHtml(Number(entry.scoreMetrics.log_loss).toFixed(5))}</strong></div>`
          : "",
        entry.scoreMetrics && Number.isFinite(Number(entry.scoreMetrics.lift))
          ? `<div class="predict-history-info-chip"><span class="predict-history-info-label">Lift</span><strong class="predict-history-info-value">${escapeHtml(`${(Number(entry.scoreMetrics.lift) * 100).toFixed(2)}%`)}</strong></div>`
          : "",
      ].filter(Boolean).join("");
      const topMainHtml = topMainRanking.length
        ? renderPredictionHistoryNumberList(topMainRanking, entry, { perRow: entry.type === "KENO" ? 10 : 0 })
        : "";
      const topSpecialHtml = TYPES[entry.type]?.hasSpecial && topSpecialRanking.length
        ? renderPredictionHistoryNumberList(topSpecialRanking, entry, { special: true })
        : "";
      const topBlocks = [
        topMainHtml
          ? `
            <div class="predict-history-stat-card">
              <div class="predict-history-stat-label">Top số:</div>
              <div class="predict-history-stat-value">${topMainHtml}</div>
            </div>
          `
          : "",
        topSpecialHtml
          ? `
            <div class="predict-history-stat-card">
              <div class="predict-history-stat-label">Top ĐB:</div>
              <div class="predict-history-stat-value">${topSpecialHtml}</div>
            </div>
          `
          : "",
      ].filter(Boolean).join("");
      const topBlockCount = [topMainHtml, topSpecialHtml].filter(Boolean).length;
      const allTickets = Array.isArray(entry.tickets) ? entry.tickets : [];
      const entryKey = getPredictionHistoryEntryKey(entry);
      const ticketLimit = getPredictionHistoryCollapsedTicketLimit(entry.type);
      const canCollapseTickets = allTickets.length > ticketLimit;
      const ticketsExpanded = canCollapseTickets && predictionHistoryExpandedKeys.has(entryKey);
      const ticketSlice = ticketsExpanded ? allTickets : allTickets.slice(0, ticketLimit);
      const ticketLines = ticketSlice.length
        ? ticketSlice.map((ticket, index) => {
            const html = formatPredictionHistoryTicketHtml(entry.type, ticket, index, entry);
            const ticketClass = isPredictionHistoryBaoTicket(ticket) ? " is-bao" : "";
            return html ? `<div class="predict-history-ticket${ticketClass}">${html}</div>` : "";
          }).filter(Boolean).join("")
        : "";
      const ticketToggleHtml = canCollapseTickets
        ? `<div class="predict-history-more-row"><button type="button" class="predict-history-more-btn" data-prediction-history-toggle="${escapeHtml(entryKey)}">${ticketsExpanded ? "Thu gọn" : `Xem thêm ${allTickets.length - ticketSlice.length} bộ`}</button></div>`
        : "";
      const actualDrawLine = formatPredictionHistoryActualDrawHtml(entry);
      const actualMetaLine = entry.resolved && (entry.actualKy || entry.resolvedAt)
        ? `<div class="predict-history-note">${escapeHtml([entry.actualKy ? `Đã ra ${formatLiveKy(entry.actualKy)}` : "", entry.resolvedAt ? `Đối chiếu lúc ${formatPredictionHistoryTime(entry.resolvedAt)}` : ""].filter(Boolean).join(" • "))}</div>`
        : "";
      const summaryText = entry.resolved ? formatPredictionHistorySummary(entry.type, entry) : "";
      const previousEntry = historyEntries[entryIndex + 1] || null;
      const periodRates = entry.resolved
        ? formatPredictionHistoryCumulativeRates(entry.type, [entry], previousEntry ? [previousEntry] : [])
        : null;
      const cumulativeRates = entry.resolved
        ? formatPredictionHistoryCumulativeRates(
            entry.type,
            historyEntries.slice(Math.max(0, entryIndex)),
            historyEntries.slice(Math.max(0, entryIndex + 1)),
          )
        : null;
      const missingNote = !entry.resolved && entry.resultMissingData
        ? `<div class="predict-history-note predict-history-note-warning">Đã rà canonical history nhưng chưa tìm thấy kết quả thật cho kỳ này.</div>`
        : "";
      return `
        <article class="predict-history-item${ticketsExpanded ? " is-expanded" : ""}">
          <div class="predict-history-top">
            <div class="predict-history-type">${escapeHtml(titleParts.join(" • "))}</div>
            <div class="predict-history-side">
              <button
                type="button"
                class="predict-history-copy-btn"
                data-prediction-history-copy="${entryIndex}"
                title="Chép nội dung kỳ này"
                aria-label="Chép nội dung kỳ này"
              >⧉</button>
              ${countdownState ? `
                <div class="predict-history-countdown-box" data-prediction-history-countdown="1">
                  <span class="predict-history-countdown-label">Kỳ tiếp theo</span>
                  <span class="predict-history-countdown-ky">${escapeHtml(countdownState.kyText || "Đang chờ")}</span>
                  <span class="predict-history-countdown-prefix">Còn :</span>
                  <span class="predict-history-countdown-time">${escapeHtml(countdownState.waitingForResult ? countdownState.countdownText : `${countdownState.countdownText}s`)}</span>
                </div>
              ` : ""}
              <span class="predict-history-status ${statusClass}">${escapeHtml(statusText)}</span>
            </div>
          </div>
          ${primaryInfoCards ? `<div class="predict-history-info-row predict-history-info-row-primary">${primaryInfoCards}</div>` : ""}
          ${metricInfoCards ? `<div class="predict-history-info-row predict-history-info-row-metrics">${metricInfoCards}</div>` : ""}
          ${topBlocks ? `
            <div class="predict-history-section predict-history-top-section">
              <div class="predict-history-top-grid${topBlockCount <= 1 ? " is-single" : ""}">${topBlocks}</div>
            </div>
          ` : ""}
          <div class="predict-history-section predict-history-ticket-section">
            <div class="predict-history-section-title">Bộ số dự đoán${allTickets.length ? ` • ${allTickets.length} bộ` : ""}</div>
            <div class="predict-history-tickets">${ticketLines || `<div class="predict-history-note">Không có bộ số để hiển thị.</div>`}</div>
            ${ticketToggleHtml}
            ${missingNote}
          </div>
          ${entry.resolved ? `
            <div class="predict-history-section predict-history-actual">
              <div class="predict-history-section-title">Đối chiếu</div>
              ${actualDrawLine}${actualMetaLine}
            </div>
          ` : ""}
          ${entry.resolved ? `
            <div class="predict-history-section predict-history-summary">
              <div class="predict-history-section-title">Tổng kết</div>
              <div class="predict-history-line"><strong>Tóm tắt:</strong> ${escapeHtml(summaryText)}</div>
              ${periodRates?.html ? `<div class="predict-history-line"><strong>Hiệu suất kỳ (${escapeHtml(String(periodRates.total))} ${escapeHtml(periodRates.unitLabel)}):</strong> ${periodRates.html}</div>` : ""}
              ${cumulativeRates?.html ? `<div class="predict-history-line"><strong>Tổng hiệu suất - Tổng (${escapeHtml(String(cumulativeRates.total))} ${escapeHtml(cumulativeRates.unitLabel)}):</strong> ${cumulativeRates.html}</div>` : ""}
            </div>
          ` : ""}
        </article>
      `;
    }

    // ---abc--- Prediction History / Modal Rendering ---
    function renderPredictionHistoryPanel() {
      const overlay = document.getElementById("predictionHistoryOverlay");
      const panel = document.getElementById("predictionHistoryPanel");
      const list = document.getElementById("predictionHistoryList");
      const countEl = document.getElementById("predictionHistoryCount");
      const toggleBtn = document.getElementById("predictionHistoryToggleBtn");
      if (!overlay || !panel || !list || !countEl) return;
      overlay.hidden = !predictionHistoryPanelOpen;
      syncPredictionHistoryBodyScroll(predictionHistoryPanelOpen || vipPredictionHistoryPanelOpen);
      if (toggleBtn) toggleBtn.classList.toggle("is-active", predictionHistoryPanelOpen);
      predictionHistorySelectedType = normalizePredictionHistoryType(predictionHistorySelectedType);
      predictionHistorySelectedRange = normalizePredictionHistoryRange(predictionHistorySelectedRange, predictionHistorySelectedType);
      predictionHistorySelectedPlayMode = hasPredictBaoMode(predictionHistorySelectedType)
        ? normalizePredictionHistoryPlayMode(predictionHistorySelectedPlayMode)
        : "normal";
      renderPredictionHistoryTypeTabs();
      renderPredictionHistoryRangeTabs(predictionHistorySelectedType);
      renderPredictionHistoryPlayModeTabs(predictionHistorySelectedType);
      renderPredictionHistoryBaoLevelFilter(predictionHistorySelectedType, predictionHistorySelectedPlayMode);
      const selectedType = predictionHistorySelectedType;
      const selectedLabel = PREDICTION_HISTORY_TYPES.find(item => item.value === selectedType)?.label || selectedType;
      const selectedPlayMode = predictionHistorySelectedPlayMode;
      const playModeLabel = selectedPlayMode === "bao" ? "bao số" : "vé thường";
      const isHistoryLoading = predictionHistoryLoading && predictionHistoryLoadingType === selectedType;
      const hasHistoryLoadingError = !isHistoryLoading && predictionHistoryLoadingType === selectedType && !!predictionHistoryLoadingError;
      const loadingNoticeHtml = isHistoryLoading
        ? `<div class="predict-history-empty">Đang tải lịch sử...</div>`
        : "";
      const loadingErrorHtml = hasHistoryLoadingError
        ? `<div class="predict-history-empty">${escapeHtml(predictionHistoryLoadingError)}</div>`
        : "";
      const metricsChanged = refreshResolvedPredictionSummaries(selectedType);
      if (metricsChanged) saveStore();
      const entries = collectPredictionHistoryEntries(
        selectedType,
        predictionHistorySelectedRange,
        selectedPlayMode,
        predictionHistorySelectedBaoLevel,
        PREDICTION_MODE_NORMAL
      );
      const currentIndex = clampPredictionHistoryCurrentIndex(entries.length);
      renderPredictionHistoryNavigator(entries.length);
      countEl.textContent = isHistoryLoading
        ? (entries.length ? `${formatLiveSyncCount(entries.length)} bản ghi • đang tải...` : "Đang tải...")
        : `${formatLiveSyncCount(entries.length)} bản ghi`;
      if (!predictionHistoryPanelOpen) return;
      if (isHistoryLoading && !entries.length) {
        list.innerHTML = loadingNoticeHtml;
        return;
      }
      if (!entries.length) {
        list.innerHTML = loadingErrorHtml || (PREDICTION_LOG_TYPES.includes(selectedType)
          ? `<div class="predict-history-empty">Chưa có lịch sử dự đoán ${escapeHtml(playModeLabel)} cho ${escapeHtml(selectedLabel)}. Sau mỗi lần bấm Dự đoán, bộ số của loại này sẽ tự lưu ở đây.</div>`
          : `<div class="predict-history-empty">Chưa có lịch sử dự đoán cho ${escapeHtml(selectedLabel)}. Loại này chưa có pipeline lưu log dự đoán nên hiện chỉ hiển thị trạng thái rỗng.</div>`);
        return;
      }
      const currentEntry = entries[currentIndex] || null;
      list.innerHTML = `${loadingNoticeHtml}${loadingErrorHtml}${currentEntry ? renderPredictionHistoryEntryHtml(currentEntry, currentIndex, entries) : ""}`;
    }

    function updatePredictionHistoryCountdownForList(listId, entry, nowValue) {
      const list = document.getElementById(listId);
      const box = list?.querySelector("[data-prediction-history-countdown]");
      if (!box || !entry) return false;
      const countdownState = buildPredictionHistoryCountdownState(entry, nowValue);
      if (!countdownState) {
        box.remove();
        return true;
      }
      const kyEl = box.querySelector(".predict-history-countdown-ky");
      const timeEl = box.querySelector(".predict-history-countdown-time");
      const nextKy = countdownState.kyText || "Đang chờ";
      const nextTime = countdownState.waitingForResult
        ? countdownState.countdownText
        : `${countdownState.countdownText}s`;
      if (kyEl && kyEl.textContent !== nextKy) kyEl.textContent = nextKy;
      if (timeEl && timeEl.textContent !== nextTime) timeEl.textContent = nextTime;
      return true;
    }

    function updatePredictionHistoryCountdowns() {
      const nowValue = getSyncedNowDate();
      if (predictionHistoryPanelOpen) {
        const selectedType = normalizePredictionHistoryType(predictionHistorySelectedType);
        const selectedPlayMode = hasPredictBaoMode(selectedType)
          ? normalizePredictionHistoryPlayMode(predictionHistorySelectedPlayMode)
          : "normal";
        const entries = collectPredictionHistoryEntries(
          selectedType,
          normalizePredictionHistoryRange(predictionHistorySelectedRange, selectedType),
          selectedPlayMode,
          predictionHistorySelectedBaoLevel,
          PREDICTION_MODE_NORMAL
        );
        const currentIndex = clampPredictionHistoryCurrentIndex(entries.length);
        updatePredictionHistoryCountdownForList("predictionHistoryList", entries[currentIndex] || null, nowValue);
      }
      if (vipPredictionHistoryPanelOpen) {
        const selectedType = normalizePredictionHistoryType(vipPredictionHistorySelectedType);
        const selectedPlayMode = hasPredictBaoMode(selectedType)
          ? normalizePredictionHistoryPlayMode(vipPredictionHistorySelectedPlayMode)
          : "normal";
        const entries = collectPredictionHistoryEntries(
          selectedType,
          normalizePredictionHistoryRange(vipPredictionHistorySelectedRange, selectedType),
          selectedPlayMode,
          vipPredictionHistorySelectedBaoLevel,
          PREDICTION_MODE_VIP
        );
        const currentIndex = clampVipPredictionHistoryCurrentIndex(entries.length);
        updatePredictionHistoryCountdownForList("vipPredictionHistoryList", entries[currentIndex] || null, nowValue);
      }
    }

    function togglePredictionHistoryPanel(forceOpen = null) {
      const nextOpen = typeof forceOpen === "boolean" ? forceOpen : !predictionHistoryPanelOpen;
      if (nextOpen) {
        const overlay = document.getElementById("predictionHistoryOverlay");
        const list = document.getElementById("predictionHistoryList");
        const nextType = getPreferredPredictionHistoryType();
        predictionHistorySelectedType = nextType;
        predictionHistoryCurrentIndex = 0;
        predictionHistoryLoadingError = "";
        predictionHistoryPanelOpen = true;
        if (overlay) overlay.scrollTop = 0;
        if (list) list.scrollTop = 0;
        renderPredictionHistoryPanel();
        startPredictionHistoryRefresh(nextType, { silent: true });
        return;
      }
      predictionHistoryRefreshToken += 1;
      predictionHistoryLoading = false;
      predictionHistoryLoadingType = "";
      predictionHistoryLoadingError = "";
      setPredictionHistoryRefreshButtonBusy(false);
      predictionHistoryPanelOpen = false;
      renderPredictionHistoryPanel();
    }

    function renderVipPredictionHistoryTypeTabs() {
      const tabsEl = document.getElementById("vipPredictionHistoryTypeTabs");
      if (!tabsEl) return;
      const selectedType = normalizePredictionHistoryType(vipPredictionHistorySelectedType);
      vipPredictionHistorySelectedType = selectedType;
      tabsEl.innerHTML = PREDICTION_HISTORY_TYPES.map(item => {
        const isActive = item.value === selectedType;
        return `<button type="button" class="predict-history-type-tab${isActive ? " is-active" : ""}" data-vip-prediction-history-type="${item.value}" role="tab" aria-selected="${isActive ? "true" : "false"}">${escapeHtml(item.label)}</button>`;
      }).join("");
    }

    function renderVipPredictionHistoryRangeTabs(typeKey = vipPredictionHistorySelectedType) {
      const tabsEl = document.getElementById("vipPredictionHistoryRangeTabs");
      if (!tabsEl) return;
      const selectedType = normalizePredictionHistoryType(typeKey);
      const selectedRange = normalizePredictionHistoryRange(vipPredictionHistorySelectedRange, selectedType);
      vipPredictionHistorySelectedRange = selectedRange;
      const items = getPredictionHistoryRangeItems(selectedType);
      tabsEl.innerHTML = items.map(item => {
        const isActive = item.value === selectedRange;
        return `<button type="button" class="predict-history-range-tab${isActive ? " is-active" : ""}" data-vip-prediction-history-range="${item.value}" role="tab" aria-selected="${isActive ? "true" : "false"}">${escapeHtml(item.label)}</button>`;
      }).join("");
    }

    function renderVipPredictionHistoryPlayModeTabs(typeKey = vipPredictionHistorySelectedType) {
      const tabsEl = document.getElementById("vipPredictionHistoryPlayModeTabs");
      if (!tabsEl) return;
      const normalizedType = normalizePredictionHistoryType(typeKey);
      if (!hasPredictBaoMode(normalizedType)) {
        vipPredictionHistorySelectedPlayMode = "normal";
      }
      const selectedPlayMode = hasPredictBaoMode(normalizedType)
        ? normalizePredictionHistoryPlayMode(vipPredictionHistorySelectedPlayMode)
        : "normal";
      vipPredictionHistorySelectedPlayMode = selectedPlayMode;
      const items = hasPredictBaoMode(normalizedType)
        ? [
            { value: "normal", label: "Chơi Thường" },
            { value: "bao", label: "Chơi Bao" },
          ]
        : [{ value: "normal", label: "Chơi Thường" }];
      tabsEl.innerHTML = items.map(item => {
        const isActive = item.value === selectedPlayMode;
        return `<button type="button" class="predict-history-playmode-tab${isActive ? " is-active" : ""}" data-vip-prediction-history-playmode="${item.value}" role="tab" aria-selected="${isActive ? "true" : "false"}">${escapeHtml(item.label)}</button>`;
      }).join("");
    }

    function renderVipPredictionHistoryBaoLevelFilter(typeKey = vipPredictionHistorySelectedType, playModeKey = vipPredictionHistorySelectedPlayMode) {
      const wrapEl = document.getElementById("vipPredictionHistoryBaoLevelFilterWrap");
      const selectEl = document.getElementById("vipPredictionHistoryBaoLevelSelect");
      if (!wrapEl || !selectEl) return;
      const normalizedType = normalizePredictionHistoryType(typeKey);
      const selectedPlayMode = normalizePredictionHistoryPlayMode(playModeKey);
      const shouldShow = hasPredictBaoMode(normalizedType) && selectedPlayMode === "bao";
      if (!shouldShow) {
        vipPredictionHistorySelectedBaoLevel = "all";
        wrapEl.hidden = true;
        selectEl.innerHTML = `<option value="all">Bậc: Tất cả</option>`;
        selectEl.value = "all";
        return;
      }
      const options = getPredictionHistoryBaoLevelOptions(normalizedType, PREDICTION_MODE_VIP);
      const normalizedSelectedValue = normalizePredictionHistoryBaoLevel(vipPredictionHistorySelectedBaoLevel);
      const nextSelectedValue = normalizedSelectedValue !== "all" && options.includes(Number(normalizedSelectedValue))
        ? normalizedSelectedValue
        : "all";
      vipPredictionHistorySelectedBaoLevel = nextSelectedValue;
      selectEl.innerHTML = [`<option value="all">Bậc: Tất cả</option>`, ...options.map(value => `<option value="${value}">${escapeHtml(`Bao ${value}`)}</option>`)].join("");
      selectEl.value = nextSelectedValue;
      wrapEl.hidden = false;
    }

    function clampVipPredictionHistoryCurrentIndex(totalEntries = 0) {
      const total = Math.max(0, Number(totalEntries || 0));
      if (!Number.isInteger(vipPredictionHistoryCurrentIndex) || vipPredictionHistoryCurrentIndex < 0) vipPredictionHistoryCurrentIndex = 0;
      if (!total) {
        vipPredictionHistoryCurrentIndex = 0;
        return 0;
      }
      if (vipPredictionHistoryCurrentIndex > total - 1) vipPredictionHistoryCurrentIndex = total - 1;
      return vipPredictionHistoryCurrentIndex;
    }

    function renderVipPredictionHistoryNavigator(totalEntries = 0) {
      const prevBtn = document.getElementById("vipPredictionHistoryPrevBtn");
      const nextBtn = document.getElementById("vipPredictionHistoryNextBtn");
      const positionEl = document.getElementById("vipPredictionHistoryPosition");
      const total = Math.max(0, Number(totalEntries || 0));
      const currentIndex = clampVipPredictionHistoryCurrentIndex(total);
      if (positionEl) positionEl.textContent = total ? `${currentIndex + 1} / ${total}` : "0 / 0";
      if (prevBtn) prevBtn.disabled = total <= 1 || currentIndex <= 0;
      if (nextBtn) nextBtn.disabled = total <= 1 || currentIndex >= total - 1;
    }

    function renderVipPredictionHistoryPanel() {
      const overlay = document.getElementById("vipPredictionHistoryOverlay");
      const panel = document.getElementById("vipPredictionHistoryPanel");
      const list = document.getElementById("vipPredictionHistoryList");
      const countEl = document.getElementById("vipPredictionHistoryCount");
      const toggleBtn = document.getElementById("vipPredictionHistoryToggleBtn");
      if (!overlay || !panel || !list || !countEl) return;
      overlay.hidden = !vipPredictionHistoryPanelOpen;
      syncPredictionHistoryBodyScroll(vipPredictionHistoryPanelOpen || predictionHistoryPanelOpen);
      if (toggleBtn) toggleBtn.classList.toggle("is-active", vipPredictionHistoryPanelOpen);
      vipPredictionHistorySelectedType = normalizePredictionHistoryType(vipPredictionHistorySelectedType);
      vipPredictionHistorySelectedRange = normalizePredictionHistoryRange(vipPredictionHistorySelectedRange, vipPredictionHistorySelectedType);
      vipPredictionHistorySelectedPlayMode = hasPredictBaoMode(vipPredictionHistorySelectedType)
        ? normalizePredictionHistoryPlayMode(vipPredictionHistorySelectedPlayMode)
        : "normal";
      renderVipPredictionHistoryTypeTabs();
      renderVipPredictionHistoryRangeTabs(vipPredictionHistorySelectedType);
      renderVipPredictionHistoryPlayModeTabs(vipPredictionHistorySelectedType);
      renderVipPredictionHistoryBaoLevelFilter(vipPredictionHistorySelectedType, vipPredictionHistorySelectedPlayMode);
      const selectedType = vipPredictionHistorySelectedType;
      const selectedLabel = PREDICTION_HISTORY_TYPES.find(item => item.value === selectedType)?.label || selectedType;
      const selectedPlayMode = vipPredictionHistorySelectedPlayMode;
      const playModeLabel = selectedPlayMode === "bao" ? "bao số" : "vé thường";
      const isHistoryLoading = vipPredictionHistoryLoading && vipPredictionHistoryLoadingType === selectedType;
      const hasHistoryLoadingError = !isHistoryLoading && vipPredictionHistoryLoadingType === selectedType && !!vipPredictionHistoryLoadingError;
      const loadingNoticeHtml = isHistoryLoading ? `<div class="predict-history-empty">Đang tải lịch sử Vip...</div>` : "";
      const loadingErrorHtml = hasHistoryLoadingError ? `<div class="predict-history-empty">${escapeHtml(vipPredictionHistoryLoadingError)}</div>` : "";
      const metricsChanged = refreshResolvedPredictionSummaries(selectedType);
      if (metricsChanged) saveStore();
      const entries = collectPredictionHistoryEntries(selectedType, vipPredictionHistorySelectedRange, selectedPlayMode, vipPredictionHistorySelectedBaoLevel, PREDICTION_MODE_VIP);
      const currentIndex = clampVipPredictionHistoryCurrentIndex(entries.length);
      renderVipPredictionHistoryNavigator(entries.length);
      countEl.textContent = isHistoryLoading ? (entries.length ? `${formatLiveSyncCount(entries.length)} bản ghi • đang tải...` : "Đang tải...") : `${formatLiveSyncCount(entries.length)} bản ghi`;
      if (!vipPredictionHistoryPanelOpen) return;
      if (isHistoryLoading && !entries.length) {
        list.innerHTML = loadingNoticeHtml;
        return;
      }
      if (!entries.length) {
        list.innerHTML = loadingErrorHtml || `<div class="predict-history-empty">Chưa có lịch sử dự đoán Vip ${escapeHtml(playModeLabel)} cho ${escapeHtml(selectedLabel)}. Sau mỗi lần bấm Dự đoán Vip, bộ số của loại này sẽ tự lưu ở đây.</div>`;
        return;
      }
      const currentEntry = entries[currentIndex] || null;
      list.innerHTML = `${loadingNoticeHtml}${loadingErrorHtml}${currentEntry ? renderPredictionHistoryEntryHtml(currentEntry, currentIndex, entries) : ""}`;
    }

    function setVipPredictionHistoryRefreshButtonBusy(isBusy) {
      const btn = document.getElementById("vipPredictionHistoryRefreshBtn");
      if (!btn) return;
      btn.disabled = !!isBusy;
      btn.classList.toggle("is-busy", !!isBusy);
      btn.textContent = isBusy ? "Đang tải..." : "Cập Nhật";
    }

    async function startVipPredictionHistoryRefresh(typeKey = vipPredictionHistorySelectedType, { silent = true, repairCanonical = false } = {}) {
      const normalizedType = normalizePredictionHistoryType(typeKey);
      if (!PREDICTION_LOG_TYPES.includes(normalizedType)) return;
      const refreshToken = ++vipPredictionHistoryRefreshToken;
      vipPredictionHistoryLoading = true;
      vipPredictionHistoryLoadingType = normalizedType;
      vipPredictionHistoryLoadingError = "";
      setVipPredictionHistoryRefreshButtonBusy(true);
      renderVipPredictionHistoryPanel();
      try {
        await refreshPredictionHistoryType(normalizedType, { silent, repairCanonical });
        if (refreshToken !== vipPredictionHistoryRefreshToken) return;
        vipPredictionHistoryLoading = false;
        vipPredictionHistoryLoadingType = "";
        vipPredictionHistoryLoadingError = "";
      } catch (error) {
        if (refreshToken !== vipPredictionHistoryRefreshToken) return;
        vipPredictionHistoryLoading = false;
        vipPredictionHistoryLoadingType = normalizedType;
        vipPredictionHistoryLoadingError = String(error?.message || error || "Không tải được lịch sử Vip.");
      } finally {
        if (refreshToken !== vipPredictionHistoryRefreshToken) return;
        setVipPredictionHistoryRefreshButtonBusy(false);
        renderVipPredictionHistoryPanel();
      }
    }

    function toggleVipPredictionHistoryPanel(forceOpen = null) {
      const nextOpen = typeof forceOpen === "boolean" ? forceOpen : !vipPredictionHistoryPanelOpen;
      if (nextOpen) {
        const overlay = document.getElementById("vipPredictionHistoryOverlay");
        const list = document.getElementById("vipPredictionHistoryList");
        vipPredictionHistorySelectedType = normalizePredictionHistoryType(document.getElementById("vipPdType")?.value || vipPredictionHistorySelectedType);
        vipPredictionHistoryCurrentIndex = 0;
        vipPredictionHistoryLoadingError = "";
        vipPredictionHistoryPanelOpen = true;
        if (overlay) overlay.scrollTop = 0;
        if (list) list.scrollTop = 0;
        renderVipPredictionHistoryPanel();
        startVipPredictionHistoryRefresh(vipPredictionHistorySelectedType, { silent: true });
        return;
      }
      vipPredictionHistoryRefreshToken += 1;
      vipPredictionHistoryLoading = false;
      vipPredictionHistoryLoadingType = "";
      vipPredictionHistoryLoadingError = "";
      setVipPredictionHistoryRefreshButtonBusy(false);
      vipPredictionHistoryPanelOpen = false;
      renderVipPredictionHistoryPanel();
    }

    function putResult(type, ky, draw) {
      if (!store.results[type][ky]) store.resultOrder[type].push(ky);
      store.results[type][ky] = draw;
      while (store.resultOrder[type].length > MAX_RESULTS_PER_TYPE) {
        const old = store.resultOrder[type].shift();
        delete store.results[type][old];
      }
      resolvePredictionLogsForKy(type, ky, draw);
      saveStore();
    }

    function addPick(type, ky, ticket) {
      if (!store.picks[type][ky]) {
        store.picks[type][ky] = [];
        store.pickOrder[type].push(ky);
      }
      store.picks[type][ky].push(ticket);
      while (store.pickOrder[type].length > MAX_PICKS_PER_TYPE) {
        const old = store.pickOrder[type].shift();
        delete store.picks[type][old];
      }
      saveStore();
    }

    function line(el, msg, cls="") {
      el.innerHTML = `<span class="${cls}">${msg}</span>`;
    }

    function kySortValue(ky) {
      return Number(String(ky || "").replace(/\D/g, "")) || 0;
    }

    function emptyKenoCsvFeed() {
      return { results: {}, order: [], sourceLabels: [], loadedAt: "" };
    }

    function cloneDraw(draw) {
      if (!draw || (!Array.isArray(draw.main) && !Array.isArray(draw.displayLines))) return null;
      return {
        ...draw,
        main: Array.isArray(draw.main) ? [...draw.main].sort((a, b) => a - b) : [],
        displayLines: Array.isArray(draw.displayLines) ? draw.displayLines.map(String) : []
      };
    }

    function cloneKenoCsvFeed(feed = kenoCsvFeed) {
      const next = emptyKenoCsvFeed();
      next.sourceLabels = [...(feed.sourceLabels || [])];
      next.loadedAt = feed.loadedAt || "";
      for (const ky of (feed.order || [])) {
        const cloned = cloneDraw(feed.results?.[ky]);
        if (!cloned) continue;
        next.results[ky] = cloned;
      }
      next.order = Object.keys(next.results).sort((a, b) => kySortValue(a) - kySortValue(b));
      return next;
    }

    function emptyLiveHistoryFeed(label = "") {
      return {
        label,
        results: {},
        order: [],
        loadedAt: "",
        countKey: "",
        rangeLabel: "",
        historyNote: "",
        canonicalCount: 0,
        canonicalFile: "",
        allCount: 0,
        todayCount: 0,
        allFile: "",
        todayFile: "",
        latestKy: "",
        latestDate: "",
        latestTime: "",
        repairAttempted: false,
        repairNewRows: 0,
        repairRepairedDates: 0,
        repairRepairedKyGaps: 0,
        repairErrors: [],
      };
    }

    function emptyLiveHistoryState() {
      return Object.fromEntries(
        LIVE_HISTORY_TYPES.map(meta => [meta.key, emptyLiveHistoryFeed(meta.label)])
      );
    }

    function normalizeLiveHistoryKy(ky) {
      const normalized = normalizeKy(String(ky || ""));
      if (normalized) return normalized;
      const formatted = formatLiveKy(ky);
      return formatted || null;
    }

    function normalizeLiveHistoryRepairErrors(items) {
      if (!Array.isArray(items)) return [];
      return items.map(item => {
        if (item && typeof item === "object") {
          const type = String(item.type || "").trim();
          const date = String(item.date || "").trim();
          const message = String(item.message || "").trim();
          return [type, date, message].filter(Boolean).join(" • ");
        }
        return String(item || "").trim();
      }).filter(Boolean);
    }

    function mergeLiveHistoryDraw(feed, ky, draw) {
      const key = normalizeLiveHistoryKy(ky);
      const cloned = cloneDraw(draw);
      if (!key || !cloned) return false;
      const existed = !!feed.results[key];
      feed.results[key] = cloned;
      feed.order = Object.keys(feed.results).sort((a, b) => kySortValue(a) - kySortValue(b));
      return !existed;
    }

    function cloneLiveHistoryFeed(feed = emptyLiveHistoryFeed()) {
      const next = emptyLiveHistoryFeed(feed.label || "");
      next.loadedAt = String(feed.loadedAt || "");
      next.countKey = String(feed.countKey || "");
      next.rangeLabel = String(feed.rangeLabel || "");
      next.historyNote = String(feed.historyNote || "");
      next.canonicalCount = Math.max(0, Number(feed.canonicalCount || feed.allCount || 0));
      next.canonicalFile = String(feed.canonicalFile || feed.allFile || "");
      next.allCount = Math.max(0, Number(feed.allCount || 0));
      next.todayCount = Math.max(0, Number(feed.todayCount || 0));
      next.allFile = String(feed.allFile || "");
      next.todayFile = String(feed.todayFile || "");
      next.latestKy = String(feed.latestKy || "");
      next.latestDate = String(feed.latestDate || "");
      next.latestTime = String(feed.latestTime || "");
      next.repairAttempted = !!feed.repairAttempted;
      next.repairNewRows = Math.max(0, Number(feed.repairNewRows || 0));
      next.repairRepairedDates = Math.max(0, Number(feed.repairRepairedDates || 0));
      next.repairRepairedKyGaps = Math.max(0, Number(feed.repairRepairedKyGaps || 0));
      next.repairErrors = normalizeLiveHistoryRepairErrors(feed.repairErrors);
      for (const ky of (feed.order || [])) {
        const cloned = cloneDraw(feed.results?.[ky]);
        if (!cloned) continue;
        next.results[ky] = cloned;
      }
      next.order = Object.keys(next.results).sort((a, b) => kySortValue(a) - kySortValue(b));
      return next;
    }

    function clearLiveHistoryState() {
      liveHistoryState = emptyLiveHistoryState();
    }

    function setLiveHistoryFeed(type, nextFeed) {
      const meta = LIVE_HISTORY_TYPES.find(item => item.key === type);
      if (!meta) return;
      const nextState = liveHistoryState && typeof liveHistoryState === "object"
        ? { ...liveHistoryState }
        : emptyLiveHistoryState();
      nextState[type] = cloneLiveHistoryFeed({
        ...emptyLiveHistoryFeed(meta.label),
        ...(nextFeed || {}),
      });
      liveHistoryState = nextState;
      clearStatsEntriesCache(type);
      clearStatsRecentComputationCache(type);
    }

    function getLiveHistoryFeed(type) {
      return liveHistoryState?.[type] || emptyLiveHistoryFeed(TYPES[type]?.label || type);
    }

    function doesLiveHistoryFeedSatisfyCount(type, feed, countRaw) {
      if (!feed?.order?.length && !String(feed?.historyNote || "").trim()) return false;
      const loadedCountKey = String(feed?.countKey || "").trim().toLowerCase();
      const requestedCountKey = String(countRaw || "").trim().toLowerCase();
      if (type === "KENO" && isKenoLiveHistoryRangeKey(requestedCountKey) && !/^\d+$/.test(requestedCountKey)) {
        return !!loadedCountKey && loadedCountKey === requestedCountKey;
      }
      if (loadedCountKey === "all") return true;
      return !!loadedCountKey && loadedCountKey === requestedCountKey;
    }

    function buildMergedResultDataset(type) {
      const baseResults = store.results[type] || {};
      const baseOrder = store.resultOrder[type] || [];
      if (type === "KENO") {
        return buildPredictionResultDataset(type);
      }

      const externalFeed = getLiveHistoryFeed(type);
      const mergedResults = {};
      const mergeFromSource = (ky, draw) => {
        const key = normalizeLiveHistoryKy(ky);
        const cloned = cloneDraw(draw);
        if (!key || !cloned) return;
        mergedResults[key] = cloned;
      };

      for (const ky of (externalFeed.order || [])) mergeFromSource(ky, externalFeed.results?.[ky]);
      for (const ky of baseOrder) mergeFromSource(ky, baseResults[ky]);

      const order = Object.keys(mergedResults).sort((a, b) => kySortValue(a) - kySortValue(b));
      const parts = [];
      if (externalFeed.order?.length) parts.push(`CSV canonical ${externalFeed.order.length} kỳ`);
      if (baseOrder.length) parts.push(`trong trang ${baseOrder.length} kỳ`);
      return {
        results: mergedResults,
        order,
        sourceText: parts.length
          ? `Nguồn ${TYPES[type].label} đã gộp: ${parts.join(" + ")}. Tổng dùng: ${order.length} kỳ`
          : `Chưa có dữ liệu ${TYPES[type].label}`
      };
    }

    function buildLiveHistoryFeedFromResponse(type, rows, loadedAt = "", countKey = "", responseMeta = {}) {
      const meta = LIVE_HISTORY_TYPES.find(item => item.key === type) || { key: type, label: TYPES[type]?.label || type };
      const next = emptyLiveHistoryFeed(meta.label);
      next.loadedAt = String(loadedAt || "");
      next.countKey = String(countKey || "");
      next.rangeLabel = String(responseMeta?.rangeLabel || "");
      next.historyNote = String(responseMeta?.historyNote || "");
      next.canonicalCount = Math.max(0, Number(responseMeta?.canonicalCount || responseMeta?.allCount || 0));
      next.canonicalFile = String(responseMeta?.canonicalFile || responseMeta?.allFile || "");
      next.allCount = Math.max(0, Number(responseMeta?.allCount || 0));
      next.todayCount = Math.max(0, Number(responseMeta?.todayCount || 0));
      next.allFile = String(responseMeta?.allFile || "");
      next.todayFile = String(responseMeta?.todayFile || "");
      next.latestKy = String(responseMeta?.latestKy || "");
      next.latestDate = String(responseMeta?.latestDate || "");
      next.latestTime = String(responseMeta?.latestTime || "");
      next.repairAttempted = !!responseMeta?.repairAttempted;
      next.repairNewRows = Math.max(0, Number(responseMeta?.repairNewRows || 0));
      next.repairRepairedDates = Math.max(0, Number(responseMeta?.repairRepairedDates || 0));
      next.repairRepairedKyGaps = Math.max(0, Number(responseMeta?.repairRepairedKyGaps || 0));
      next.repairErrors = normalizeLiveHistoryRepairErrors(responseMeta?.repairErrors);
      (Array.isArray(rows) ? rows : []).forEach(row => {
        const main = Array.isArray(row?.main)
          ? row.main.map(Number).filter(Number.isFinite).sort((a, b) => a - b)
          : [];
        const specialValue = row?.special;
        const special = Number.isInteger(Number(specialValue)) ? Number(specialValue) : null;
        mergeLiveHistoryDraw(next, row?.ky, {
          main,
          special,
          displayLines: Array.isArray(row?.displayLines) ? row.displayLines.map(String) : [],
          date: String(row?.date || ""),
          time: String(row?.time || ""),
          sourceUrl: String(row?.sourceUrl || ""),
          sourceDate: String(row?.sourceDate || ""),
          label: String(row?.label || meta.label),
        });
      });
      next.allCount = Math.max(next.allCount, next.order.length);
      next.canonicalCount = Math.max(next.canonicalCount, next.order.length);
      return next;
    }

    function isLiveHistoryRouteMissingError(err) {
      const message = String(err?.message || err || "").trim().toLowerCase();
      return message === "not found" || message.includes("404");
    }

    function isAiPredictRouteMissingError(err) {
      const message = String(err?.message || err || "").trim().toLowerCase();
      return message === "not found" || message.includes("404");
    }

    async function fetchLiveHistoryFromLegacyLiveResults(type, normalizedCount) {
      if (type === "KENO" && isKenoLiveHistoryRangeKey(normalizedCount) && normalizedCount !== "all") {
        throw new Error("Server đang chạy bản cũ và chưa hỗ trợ mốc thời gian Keno trong /api/live-history. Hãy tắt server rồi chạy lại .\\chay_lotto_web.bat.");
      }
      const legacyRes = await api("/api/live-results");
      const historyMap = legacyRes?.history && typeof legacyRes.history === "object"
        ? legacyRes.history
        : {};
      if (!Array.isArray(historyMap?.[type])) {
        throw new Error("Server đang chạy bản cũ và chưa hỗ trợ /api/live-history. Hãy tắt server rồi chạy lại .\\chay_lotto_web.bat.");
      }
      const rows = Array.isArray(historyMap?.[type]) ? historyMap[type] : [];
      const limitedRows = normalizedCount === "all"
        ? rows
        : rows.slice(0, Math.max(1, Number(normalizedCount) || 20));
      const nextFeed = buildLiveHistoryFeedFromResponse(
        type,
        limitedRows,
        String(legacyRes?.fetchedAt || ""),
        normalizedCount,
        {
          allCount: rows.length,
          todayCount: 0,
          allFile: "",
          todayFile: "",
          latestKy: limitedRows?.[0]?.ky || "",
          latestDate: limitedRows?.[0]?.date || "",
          latestTime: limitedRows?.[0]?.time || ""
        }
      );
      setLiveHistoryFeed(type, nextFeed);
      return nextFeed;
    }

    async function fetchLiveHistory(type, countRaw = "2", { force = false, silent = false, repair = false, recentDays = null } = {}) {
      const out = document.getElementById("liveHistoryOut");
      const meta = LIVE_HISTORY_TYPES.find(item => item.key === type);
      if (!meta) throw new Error("Loại lịch sử không hợp lệ.");
      if (IS_LOCAL_MODE) {
        if (!silent && out) {
          line(out, "Lịch sử CSV tự động chỉ hoạt động khi mở qua http://localhost:8080.", "warn");
        }
        return getLiveHistoryFeed(type);
      }

      const normalizedCount = String(countRaw || "2").trim().toLowerCase() || "2";
      const currentFeed = getLiveHistoryFeed(type);
      if (!force && doesLiveHistoryFeedSatisfyCount(type, currentFeed, normalizedCount)) {
        return currentFeed;
      }

      if (!silent && out) {
        line(out, `Đang tải lịch sử CSV ${meta.label} từ all_day.csv...`, "muted");
      }

      let nextFeed;
      try {
        if (liveHistoryLegacyApiMode) {
          nextFeed = await fetchLiveHistoryFromLegacyLiveResults(type, normalizedCount);
        } else {
          const params = new URLSearchParams({ type, count: normalizedCount });
          if (repair) params.set("repair", "1");
          if (force) params.set("_ts", String(Date.now()));
          if (Number.isFinite(Number(recentDays)) && Number(recentDays) > 0) {
            params.set("recentDays", String(Math.max(1, Math.floor(Number(recentDays)))));
          }
          const res = await api(`/api/live-history?${params.toString()}`);
          nextFeed = buildLiveHistoryFeedFromResponse(
            type,
            Array.isArray(res?.history) ? res.history : [],
            String(res?.fetchedAt || ""),
            String(res?.count || normalizedCount),
            {
              canonicalCount: res?.canonicalCount,
              canonicalFile: res?.canonicalFile,
              allCount: res?.allCount,
              todayCount: res?.todayCount,
              allFile: res?.allFile,
              todayFile: res?.todayFile,
              latestKy: res?.latestKy,
              latestDate: res?.latestDate,
              latestTime: res?.latestTime,
              rangeLabel: res?.rangeLabel,
              historyNote: res?.historyNote,
              repairAttempted: res?.repairAttempted,
              repairNewRows: res?.repairNewRows,
              repairRepairedDates: res?.repairRepairedDates,
              repairRepairedKyGaps: res?.repairRepairedKyGaps,
              repairErrors: res?.repairErrors,
            }
          );
          setLiveHistoryFeed(type, nextFeed);
        }
      } catch (err) {
        if (!liveHistoryLegacyApiMode && isLiveHistoryRouteMissingError(err)) {
          nextFeed = await fetchLiveHistoryFromLegacyLiveResults(type, normalizedCount);
          liveHistoryLegacyApiMode = true;
        } else {
          throw err;
        }
      }
      if (PREDICTION_LOG_TYPES.includes(type) && String(nextFeed.countKey || "").toLowerCase() === "all") {
        const before = JSON.stringify(store.predictionLogs?.[type] || []);
        reconcilePredictionLogsForType(type);
        if (JSON.stringify(store.predictionLogs?.[type] || []) !== before) {
          saveStore();
        }
      }
      return getLiveHistoryFeed(type);
    }

    async function refreshCurrentLiveHistory({ force = false, silent = false } = {}) {
      const out = document.getElementById("liveHistoryOut");
      const type = document.getElementById("liveHistoryType")?.value || LIVE_HISTORY_TYPES[0]?.key;
      const countRaw = String(document.getElementById("liveHistoryCount")?.value || "2").trim().toLowerCase();
      const feed = await fetchLiveHistory(type, countRaw, { force, silent });
      if (!feed?.order?.length && !String(feed?.historyNote || "").trim()) {
        if (!out) return;
        if (IS_LOCAL_MODE) {
          line(out, "Lịch sử CSV tự động chỉ hoạt động khi mở qua http://localhost:8080.", "warn");
          return;
        }
        line(out, `Chưa có dữ liệu lịch sử CSV cho ${TYPES[type]?.label || type} trong all_day.csv.`, "warn");
        return;
      }
      renderLiveHistoryOutput();
    }

    function setLiveHistoryRefreshButtonBusy(isBusy) {
      const btn = document.getElementById("liveHistoryRefreshBtn");
      if (!btn) return;
      const originalText = btn.dataset.originalText || String(btn.textContent || "Cập nhật 15 ngày");
      btn.dataset.originalText = originalText;
      btn.disabled = !!isBusy;
      btn.textContent = isBusy ? "Đang cập nhật..." : originalText;
    }

    async function refreshRecentLiveHistoryWindow() {
      const out = document.getElementById("liveHistoryOut");
      const type = document.getElementById("liveHistoryType")?.value || LIVE_HISTORY_TYPES[0]?.key || "LOTO_5_35";
      const typeLabel = TYPES[type]?.label || type;
      if (liveHistoryRecentRefreshBusy) return;
      if (IS_LOCAL_MODE) {
        line(out, "Cập nhật lịch sử CSV chỉ hoạt động khi mở qua http://localhost:8080.", "warn");
        return;
      }
      liveHistoryRecentRefreshBusy = true;
      setLiveHistoryRefreshButtonBusy(true);
      line(out, `Đang kiểm tra và cập nhật ${typeLabel} trong ${LIVE_HISTORY_RECENT_REPAIR_DAYS} ngày gần nhất...`, "muted");
      try {
        const params = new URLSearchParams({
          type,
          repair: "1",
          recentDays: String(LIVE_HISTORY_RECENT_REPAIR_DAYS),
        });
        const requestStartedAtMs = Date.now();
        const res = await api(`/api/live-results?${params.toString()}`);
        applyLiveResultsApiResponse(res, { repairCanonical: true, requestStartedAtMs });
        await refreshCurrentLiveHistory({ force: true, silent: true });
        const historyText = String(out?.textContent || "").trim();
        line(
          out,
          `Đã kiểm tra và cập nhật dữ liệu ${typeLabel} trong ${LIVE_HISTORY_RECENT_REPAIR_DAYS} ngày gần nhất.` + (historyText ? `\n\n${historyText}` : ""),
          "ok"
        );
      } finally {
        liveHistoryRecentRefreshBusy = false;
        setLiveHistoryRefreshButtonBusy(false);
      }
    }

    function formatLiveHistoryDraw(type, draw) {
      const displayLines = Array.isArray(draw?.displayLines) ? draw.displayLines.filter(Boolean) : [];
      if (TYPES[type]?.threeDigit && displayLines.length) {
        return displayLines.join(" | ");
      }
      if (TYPES[type] && Array.isArray(draw?.main) && draw.main.length) {
        return formatTicket(draw, type);
      }
      if (displayLines.length) return displayLines.join(" | ");
      if (Array.isArray(draw?.main) && draw.main.length) return draw.main.join(" ");
      return "(không có dữ liệu)";
    }

    function renderLiveHistoryOutput() {
      const out = document.getElementById("liveHistoryOut");
      const type = document.getElementById("liveHistoryType")?.value || LIVE_HISTORY_TYPES[0]?.key;
      const countRaw = String(document.getElementById("liveHistoryCount")?.value || "2").trim().toLowerCase();
      if (!out || !type) return;
      const feed = getLiveHistoryFeed(type);
      if (!feed.order.length && !String(feed.historyNote || "").trim()) {
        return line(out, "Chọn loại rồi bấm Xem lịch sử CSV để tải dữ liệu từ all_day.csv.", "muted");
      }

      const isKenoRangeMode = type === "KENO" && isKenoLiveHistoryRangeKey(countRaw);
      const selectedKeys = isKenoRangeMode || countRaw === "all"
        ? [...feed.order].reverse()
        : [...feed.order].slice(-Math.max(1, Number(countRaw) || 20)).reverse();
      const selectedCount = selectedKeys.length;
      const totalCount = Math.max(feed.order.length, Number(feed.canonicalCount || feed.allCount || 0));
      const lines = [];
      if (isKenoRangeMode) {
        lines.push(`Lịch sử CSV ${feed.label || type}: ${feed.rangeLabel || getKenoLiveHistoryRangeLabel(countRaw)} • ${formatLiveSyncCount(selectedCount)} kỳ.`);
      } else {
        lines.push(`Lịch sử CSV ${feed.label || type}: đang hiển thị ${formatLiveSyncCount(selectedCount)}/${formatLiveSyncCount(totalCount)} kỳ.`);
      }
      const sourceParts = [];
      if (feed.canonicalFile || feed.allFile) {
        sourceParts.push(`Nguồn: ${feed.canonicalFile || feed.allFile}`);
      }
      if (Number(feed.todayCount || 0) > 0) {
        sourceParts.push(`${formatLiveSyncCount(feed.todayCount)} kỳ hôm nay`);
      }
      const latestMetaParts = buildLiveMetaParts(feed.latestKy || "", feed.latestDate || "", feed.latestTime || "");
      if (latestMetaParts.length) {
        sourceParts.push(`mới nhất ${latestMetaParts.join(" • ")}`);
      }
      if (sourceParts.length) {
        lines.push(sourceParts.join(" • "));
      }
      if (feed.loadedAt) {
        lines.push(`Cập nhật cache: ${new Date(feed.loadedAt).toLocaleString("vi-VN")}.`);
      }
      if (feed.historyNote) {
        lines.push(feed.historyNote);
      }
      lines.push("");
      selectedKeys.forEach(ky => {
        const draw = feed.results[ky];
        if (!draw) return;
        const metaParts = buildLiveMetaParts(ky, draw.date, draw.time);
        lines.push(`${feed.label || type} ${metaParts.join(" • ")}: ${formatLiveHistoryDraw(type, draw)}`);
      });
      line(out, lines.join("\n"));
    }

    const DATA_TABLE_WEEKDAY_LABELS = ["Chủ nhật", "Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7"];

    function padDataTableDatePart(value) {
      return String(Math.max(0, Number(value) || 0)).padStart(2, "0");
    }

    function parseDataTableDateParts(dateText) {
      const raw = String(dateText || "").trim();
      const match = raw.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$/);
      if (!match) return null;
      const day = Number(match[1]);
      const month = Number(match[2]);
      const year = Number(match[3]);
      const date = new Date(year, month - 1, day);
      if (
        Number.isNaN(date.getTime()) ||
        date.getFullYear() !== year ||
        date.getMonth() !== month - 1 ||
        date.getDate() !== day
      ) {
        return null;
      }
      return { day, month, year, weekday: date.getDay() };
    }

    function formatDataTableWeekday(dateText) {
      const parts = parseDataTableDateParts(dateText);
      return parts ? DATA_TABLE_WEEKDAY_LABELS[parts.weekday] || "" : "";
    }

    function normalizeDataTableFilterNumber(value, min, max) {
      const raw = String(value ?? "").trim().toLowerCase();
      if (!raw || raw === "all") return "all";
      const number = Number(raw);
      if (!Number.isInteger(number) || number < min || number > max) return "all";
      return String(number);
    }

    function normalizeDataTableWeekdayFilter(value) {
      return normalizeDataTableFilterNumber(value, 0, 6);
    }

    function getDataTableDateFilters() {
      dataTableDateFilters = {
        weekday: normalizeDataTableWeekdayFilter(document.getElementById("dataTableWeekday")?.value ?? dataTableDateFilters.weekday),
        day: normalizeDataTableFilterNumber(document.getElementById("dataTableDay")?.value ?? dataTableDateFilters.day, 1, 31),
        month: normalizeDataTableFilterNumber(document.getElementById("dataTableMonth")?.value ?? dataTableDateFilters.month, 1, 12),
        year: normalizeDataTableFilterNumber(document.getElementById("dataTableYear")?.value ?? dataTableDateFilters.year, 1900, 3000),
      };
      return dataTableDateFilters;
    }

    function hasDataTableDateFilter(filters = getDataTableDateFilters()) {
      return Object.values(filters || {}).some(value => String(value || "all") !== "all");
    }

    function isDataTableDrawInDateFilter(draw, filters = getDataTableDateFilters()) {
      if (!hasDataTableDateFilter(filters)) return true;
      const parts = parseDataTableDateParts(draw?.date);
      if (!parts) return false;
      if (filters.weekday !== "all" && parts.weekday !== Number(filters.weekday)) return false;
      if (filters.day !== "all" && parts.day !== Number(filters.day)) return false;
      if (filters.month !== "all" && parts.month !== Number(filters.month)) return false;
      if (filters.year !== "all" && parts.year !== Number(filters.year)) return false;
      return true;
    }

    function setDataTableFilterSelectValue(selectId, value) {
      const select = document.getElementById(selectId);
      if (!select) return;
      const normalized = String(value || "all");
      select.value = Array.from(select.options).some(option => option.value === normalized) ? normalized : "all";
      if (select.__syncCustomSelect) select.__syncCustomSelect();
    }

    function syncDataTableYearFilterOptions(feed = null) {
      const select = document.getElementById("dataTableYear");
      if (!select) return;
      const current = normalizeDataTableFilterNumber(select.value || dataTableDateFilters.year, 1900, 3000);
      const years = new Set();
      (feed?.order || []).forEach(ky => {
        const parts = parseDataTableDateParts(feed.results?.[ky]?.date);
        if (parts) years.add(parts.year);
      });
      const sortedYears = [...years].sort((a, b) => b - a);
      select.innerHTML = [
        `<option value="all">Tất Cả</option>`,
        ...sortedYears.map(year => `<option value="${year}">${year}</option>`),
      ].join("");
      select.value = sortedYears.includes(Number(current)) ? current : "all";
      dataTableDateFilters.year = select.value;
      if (select.__syncCustomSelect) select.__syncCustomSelect();
    }

    function syncDataTableDateFilterControls(feed = null) {
      if (feed) syncDataTableYearFilterOptions(feed);
      const filters = dataTableDateFilters || {};
      setDataTableFilterSelectValue("dataTableWeekday", filters.weekday);
      setDataTableFilterSelectValue("dataTableDay", filters.day);
      setDataTableFilterSelectValue("dataTableMonth", filters.month);
      setDataTableFilterSelectValue("dataTableYear", filters.year);
    }

    function resetDataTableDateFilters() {
      dataTableDateFilters = { weekday: "all", day: "all", month: "all", year: "all" };
      syncDataTableDateFilterControls();
    }

    function formatDataTableDateFilterSummary(filters = getDataTableDateFilters()) {
      const parts = [];
      if (filters.weekday !== "all") {
        parts.push(DATA_TABLE_WEEKDAY_LABELS[Number(filters.weekday)] || "");
      }

      const hasDay = filters.day !== "all";
      const hasMonth = filters.month !== "all";
      const hasYear = filters.year !== "all";
      if (hasDay && hasMonth && hasYear) {
        parts.push(`${padDataTableDatePart(filters.day)}/${padDataTableDatePart(filters.month)}/${filters.year}`);
      } else if (hasDay && hasMonth) {
        parts.push(`${padDataTableDatePart(filters.day)}/${padDataTableDatePart(filters.month)}/mọi năm`);
      } else {
        if (hasDay) parts.push(`ngày ${padDataTableDatePart(filters.day)}`);
        if (hasMonth) parts.push(`tháng ${padDataTableDatePart(filters.month)}`);
        if (hasYear) parts.push(`năm ${filters.year}`);
      }
      return parts.filter(Boolean).join(", ");
    }

    function getDataTableFilterFileSuffix(filters = getDataTableDateFilters()) {
      const parts = [];
      if (filters.weekday !== "all") parts.push(`thu_${filters.weekday}`);
      if (filters.day !== "all") parts.push(`ngay_${padDataTableDatePart(filters.day)}`);
      if (filters.month !== "all") parts.push(`thang_${padDataTableDatePart(filters.month)}`);
      if (filters.year !== "all") parts.push(`nam_${filters.year}`);
      return parts.length ? `_${parts.join("_")}` : "";
    }

    function normalizeDataTableDisplayLine(lineText) {
      return String(lineText || "").replace(/\s+/g, " ").trim();
    }

    function splitDataTableDisplayLines(draw) {
      const rawLines = Array.isArray(draw?.displayLines) ? draw.displayLines : [];
      return rawLines.map(normalizeDataTableDisplayLine).filter(Boolean);
    }

    function formatDataTableNumbers(type, draw) {
      const displayLines = splitDataTableDisplayLines(draw);
      if (TYPES[type]?.threeDigit && displayLines.length) {
        const specialLines = [];
        const numberLines = [];
        displayLines.forEach(lineText => {
          if (/^đặc\s*biệt\s*:/i.test(lineText)) {
            specialLines.push(lineText.replace(/^đặc\s*biệt\s*:\s*/i, "").trim());
          } else {
            numberLines.push(lineText);
          }
        });
        return {
          numbers: numberLines.join(" | ") || displayLines.join(" | "),
          special: specialLines.join(" | "),
        };
      }

      const main = Array.isArray(draw?.main) ? draw.main.map(Number).filter(Number.isFinite) : [];
      const numbers = main.map(number => formatPredictNumber(number, type)).join(" ");
      const special = TYPES[type]?.hasSpecial && Number.isInteger(Number(draw?.special))
        ? formatPredictNumber(Number(draw.special), type)
        : "";
      return { numbers, special };
    }

    function getDataTableLimitValue() {
      const raw = String(document.getElementById("dataTableLimit")?.value || dataTableSelectedLimit || "500").trim().toLowerCase();
      return raw === "all" ? "all" : String(Math.max(1, Number(raw) || 500));
    }

    function getDataTableHeaders(type) {
      const hasSpecialColumn = !!TYPES[type]?.hasSpecial || !!TYPES[type]?.threeDigit;
      return ["Kỳ", "Thứ", "Ngày", "Giờ", "Số", ...(hasSpecialColumn ? ["ĐB"] : [])];
    }

    function getDataTableMatchingKeys(feed, filters = getDataTableDateFilters()) {
      return [...(feed?.order || [])]
        .reverse()
        .filter(ky => isDataTableDrawInDateFilter(feed?.results?.[ky], filters));
    }

    function getDataTableSelectedKeys(feed, limitValue = getDataTableLimitValue(), filters = getDataTableDateFilters()) {
      const keys = getDataTableMatchingKeys(feed, filters);
      if (limitValue === "all") return keys;
      return keys.slice(0, Math.max(1, Number(limitValue) || 500));
    }

    function buildDataTableRows(type, feed, limitValue = getDataTableLimitValue(), filters = getDataTableDateFilters()) {
      return getDataTableSelectedKeys(feed, limitValue, filters).map(ky => {
        const draw = feed.results?.[ky] || {};
        const cells = formatDataTableNumbers(type, draw);
        return [
          formatLiveKy(ky),
          formatDataTableWeekday(draw.date),
          draw.date || "",
          draw.time || "",
          cells.numbers || "",
          ...((!!TYPES[type]?.hasSpecial || !!TYPES[type]?.threeDigit) ? [cells.special || ""] : []),
        ];
      });
    }

    function renderDataTableShell() {
      const select = document.getElementById("dataTableType");
      const limitSelect = document.getElementById("dataTableLimit");
      if (select && !select.options.length) {
        select.innerHTML = LIVE_HISTORY_TYPES.map(item => `<option value="${item.key}">${item.label}</option>`).join("");
      }
      if (select && Array.from(select.options).some(option => option.value === dataTableSelectedType)) {
        select.value = dataTableSelectedType;
      }
      if (limitSelect && Array.from(limitSelect.options).some(option => option.value === dataTableSelectedLimit)) {
        limitSelect.value = dataTableSelectedLimit;
      }
      if (select?.__syncCustomSelect) select.__syncCustomSelect();
      if (limitSelect?.__syncCustomSelect) limitSelect.__syncCustomSelect();
      syncDataTableDateFilterControls();
    }

    function renderDataTableStatus(message, tone = "muted") {
      const status = document.getElementById("dataTableStatus");
      if (!status) return;
      status.className = `data-table-status ${tone}`;
      status.textContent = message;
    }

    function renderDataTableRows(type, feed, filters = getDataTableDateFilters()) {
      const head = document.getElementById("dataTableHead");
      const body = document.getElementById("dataTableBody");
      if (!head || !body) return;
      const headers = getDataTableHeaders(type);
      head.innerHTML = `<tr>${headers.map(label => `<th>${escapeHtml(label)}</th>`).join("")}</tr>`;

      const rows = buildDataTableRows(type, feed, getDataTableLimitValue(), filters);
      if (!rows.length) {
        body.innerHTML = `<tr><td colspan="${headers.length}" class="data-table-empty">Chưa có dữ liệu để hiển thị.</td></tr>`;
        return;
      }

      body.innerHTML = rows.map(rowCells => {
        return `<tr>${rowCells.map(value => `<td>${escapeHtml(value)}</td>`).join("")}</tr>`;
      }).join("");
    }

    async function loadDataTableRows({ force = false } = {}) {
      const select = document.getElementById("dataTableType");
      const limitSelect = document.getElementById("dataTableLimit");
      const type = select?.value || dataTableSelectedType || "LOTO_5_35";
      if (!TYPES[type] || dataTableLoading) return;
      dataTableSelectedType = type;
      dataTableSelectedLimit = getDataTableLimitValue();
      if (limitSelect?.__syncCustomSelect) limitSelect.__syncCustomSelect();
      if (IS_LOCAL_MODE) {
        renderDataTableStatus("Bảng dữ liệu chỉ tải tự động khi mở qua http://localhost:8080.", "warn");
        renderDataTableRows(type, emptyLiveHistoryFeed(TYPES[type]?.label || type), getDataTableDateFilters());
        return;
      }
      dataTableLoading = true;
      renderDataTableStatus(`Đang tải ${TYPES[type]?.label || type} từ all_day.csv...`, "muted");
      try {
        const feed = await fetchLiveHistory(type, "all", { force, silent: true });
        syncDataTableDateFilterControls(feed);
        const filters = getDataTableDateFilters();
        renderDataTableRows(type, feed, filters);
        const total = Math.max(feed.order.length, Number(feed.canonicalCount || feed.allCount || 0));
        const matching = getDataTableMatchingKeys(feed, filters).length;
        const shown = buildDataTableRows(type, feed, dataTableSelectedLimit, filters).length;
        const source = feed.canonicalFile || feed.allFile || "all_day.csv";
        const filterSummary = formatDataTableDateFilterSummary(filters);
        if (filterSummary) {
          const tone = matching > 0 ? "ok" : "warn";
          renderDataTableStatus(`Đang hiển thị ${formatLiveSyncCount(shown)}/${formatLiveSyncCount(matching)} kỳ phù hợp • Tổng ${formatLiveSyncCount(total)} kỳ • Lọc: ${filterSummary} • Nguồn: ${source}`, tone);
        } else {
          renderDataTableStatus(`Đang hiển thị ${formatLiveSyncCount(shown)}/${formatLiveSyncCount(total)} kỳ • Nguồn: ${source}`, "ok");
        }
      } catch (err) {
        renderDataTableStatus(`Không tải được bảng dữ liệu: ${err.message || err}`, "warn");
      } finally {
        dataTableLoading = false;
      }
    }

    async function downloadDataTableExcel() {
      const type = document.getElementById("dataTableType")?.value || dataTableSelectedType || "LOTO_5_35";
      if (!TYPES[type]) return;
      if (IS_LOCAL_MODE) {
        renderDataTableStatus("Tải xuống Excel chỉ hoạt động khi mở qua http://localhost:8080.", "warn");
        return;
      }
      const feed = await fetchLiveHistory(type, "all", { silent: true });
      syncDataTableDateFilterControls(feed);
      const filters = getDataTableDateFilters();
      const headers = getDataTableHeaders(type);
      const rows = buildDataTableRows(type, feed, getDataTableLimitValue(), filters);
      if (!rows.length) {
        renderDataTableStatus("Không có dữ liệu để tải xuống.", "warn");
        return;
      }
      const blob = buildXlsxWorkbookBlob(headers, rows, `Bang Du Lieu ${TYPES[type]?.label || type}`);
      const safeType = String(type || "DATA").toLowerCase();
      const safeLimit = getDataTableLimitValue() === "all" ? "tat_ca" : getDataTableLimitValue();
      const safeFilter = getDataTableFilterFileSuffix(filters);
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `bang_du_lieu_${safeType}_${safeLimit}${safeFilter}.xlsx`;
      document.body.appendChild(link);
      link.click();
      window.setTimeout(() => {
        URL.revokeObjectURL(link.href);
        link.remove();
      }, 0);
      renderDataTableStatus(`Đã tạo file Excel ${rows.length} dòng cho ${TYPES[type]?.label || type}.`, "ok");
    }

    function escapeXml(value) {
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&apos;");
    }

    function getExcelColumnName(index) {
      let n = Math.max(1, Number(index) || 1);
      let name = "";
      while (n > 0) {
        const mod = (n - 1) % 26;
        name = String.fromCharCode(65 + mod) + name;
        n = Math.floor((n - 1) / 26);
      }
      return name;
    }

    function buildXlsxSheetXml(headers, rows) {
      const allRows = [headers, ...rows];
      const rowXml = allRows.map((row, rowIndex) => {
        const rowNumber = rowIndex + 1;
        const cells = row.map((value, cellIndex) => {
          const cellRef = `${getExcelColumnName(cellIndex + 1)}${rowNumber}`;
          const text = escapeXml(value);
          return `<c r="${cellRef}" t="inlineStr"><is><t xml:space="preserve">${text}</t></is></c>`;
        }).join("");
        return `<row r="${rowNumber}">${cells}</row>`;
      }).join("");
      const lastCol = getExcelColumnName(Math.max(1, headers.length));
      const lastRow = Math.max(1, allRows.length);
      return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <dimension ref="A1:${lastCol}${lastRow}"/>
  <sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
  <sheetFormatPr defaultRowHeight="18"/>
  <cols>
    <col min="1" max="4" width="14" customWidth="1"/>
    <col min="5" max="5" width="72" customWidth="1"/>
    <col min="6" max="6" width="24" customWidth="1"/>
  </cols>
  <sheetData>${rowXml}</sheetData>
</worksheet>`;
    }

    function buildXlsxWorkbookBlob(headers, rows, title = "Bang Du Lieu") {
      const now = getSyncedIsoString();
      const files = {
        "[Content_Types].xml": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>`,
        "_rels/.rels": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>`,
        "docProps/app.xml": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>DVLF</Application>
</Properties>`,
        "docProps/core.xml": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>${escapeXml(title)}</dc:title>
  <dc:creator>DVLF</dc:creator>
  <dcterms:created xsi:type="dcterms:W3CDTF">${now}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">${now}</dcterms:modified>
</cp:coreProperties>`,
        "xl/workbook.xml": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Bang Du Lieu" sheetId="1" r:id="rId1"/></sheets>
</workbook>`,
        "xl/_rels/workbook.xml.rels": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>`,
        "xl/styles.xml": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="1"><font><sz val="11"/><name val="Arial"/></font></fonts>
  <fills count="1"><fill><patternFill patternType="none"/></fill></fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="1"><xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>
</styleSheet>`,
        "xl/worksheets/sheet1.xml": buildXlsxSheetXml(headers, rows),
      };
      return buildZipBlob(files, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
    }

    function buildCrc32Table() {
      const table = new Uint32Array(256);
      for (let i = 0; i < 256; i++) {
        let value = i;
        for (let bit = 0; bit < 8; bit++) {
          value = (value & 1) ? (0xEDB88320 ^ (value >>> 1)) : (value >>> 1);
        }
        table[i] = value >>> 0;
      }
      return table;
    }

    const ZIP_CRC32_TABLE = buildCrc32Table();

    function crc32(bytes) {
      let crc = 0xFFFFFFFF;
      for (let i = 0; i < bytes.length; i++) {
        crc = ZIP_CRC32_TABLE[(crc ^ bytes[i]) & 0xFF] ^ (crc >>> 8);
      }
      return (crc ^ 0xFFFFFFFF) >>> 0;
    }

    function pushUint16LE(out, value) {
      out.push(value & 0xFF, (value >>> 8) & 0xFF);
    }

    function pushUint32LE(out, value) {
      out.push(value & 0xFF, (value >>> 8) & 0xFF, (value >>> 16) & 0xFF, (value >>> 24) & 0xFF);
    }

    function pushBytes(out, bytes) {
      for (let i = 0; i < bytes.length; i++) out.push(bytes[i]);
    }

    function buildZipBlob(files, mimeType) {
      const encoder = new TextEncoder();
      const localParts = [];
      const centralParts = [];
      let offset = 0;
      let centralSize = 0;
      const dosTime = 0;
      const dosDate = 33;
      Object.entries(files).forEach(([path, content]) => {
        const nameBytes = encoder.encode(path);
        const dataBytes = encoder.encode(String(content || ""));
        const crc = crc32(dataBytes);
        const local = [];
        pushUint32LE(local, 0x04034b50);
        pushUint16LE(local, 20);
        pushUint16LE(local, 0x0800);
        pushUint16LE(local, 0);
        pushUint16LE(local, dosTime);
        pushUint16LE(local, dosDate);
        pushUint32LE(local, crc);
        pushUint32LE(local, dataBytes.length);
        pushUint32LE(local, dataBytes.length);
        pushUint16LE(local, nameBytes.length);
        pushUint16LE(local, 0);
        pushBytes(local, nameBytes);
        pushBytes(local, dataBytes);
        localParts.push(new Uint8Array(local));

        const central = [];
        pushUint32LE(central, 0x02014b50);
        pushUint16LE(central, 20);
        pushUint16LE(central, 20);
        pushUint16LE(central, 0x0800);
        pushUint16LE(central, 0);
        pushUint16LE(central, dosTime);
        pushUint16LE(central, dosDate);
        pushUint32LE(central, crc);
        pushUint32LE(central, dataBytes.length);
        pushUint32LE(central, dataBytes.length);
        pushUint16LE(central, nameBytes.length);
        pushUint16LE(central, 0);
        pushUint16LE(central, 0);
        pushUint16LE(central, 0);
        pushUint16LE(central, 0);
        pushUint32LE(central, 0);
        pushUint32LE(central, offset);
        pushBytes(central, nameBytes);
        centralParts.push(new Uint8Array(central));
        centralSize += central.length;
        offset += local.length;
      });
      const centralOffset = offset;
      const end = [];
      pushUint32LE(end, 0x06054b50);
      pushUint16LE(end, 0);
      pushUint16LE(end, 0);
      pushUint16LE(end, Object.keys(files).length);
      pushUint16LE(end, Object.keys(files).length);
      pushUint32LE(end, centralSize);
      pushUint32LE(end, centralOffset);
      pushUint16LE(end, 0);
      return new Blob([
        ...localParts,
        ...centralParts,
        new Uint8Array(end),
      ], { type: mimeType });
    }

    function mergeKenoDraw(feed, ky, draw) {
      const key = String(ky || "").replace(/\D/g, "");
      const cloned = cloneDraw(draw);
      if (!key || !cloned) return false;
      feed.results[key] = cloned;
      return true;
    }

    function finalizeKenoCsvFeed(feed, loadedAt = getSyncedIsoString()) {
      feed.order = Object.keys(feed.results).sort((a, b) => kySortValue(a) - kySortValue(b));
      feed.sourceLabels = [...new Set((feed.sourceLabels || []).filter(Boolean))];
      feed.loadedAt = loadedAt;
      return feed;
    }

    function normalizeHeaderName(value) {
      return String(value || "")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "");
    }

    function splitCsvRow(lineText) {
      const line = String(lineText || "");
      const cells = [];
      let cur = "";
      let inQuotes = false;
      for (let i = 0; i < line.length; i++) {
        const ch = line[i];
        if (ch === '"') {
          if (inQuotes && line[i + 1] === '"') {
            cur += '"';
            i++;
          } else {
            inQuotes = !inQuotes;
          }
          continue;
        }
        if (ch === "," && !inQuotes) {
          cells.push(cur.trim());
          cur = "";
          continue;
        }
        cur += ch;
      }
      cells.push(cur.trim());
      return cells;
    }

    function parseKenoCsvText(text, sourceLabel = "CSV") {
      const lines = String(text || "")
        .replace(/^\uFEFF/, "")
        .split(/\r?\n/)
        .filter(line => line.trim());
      if (!lines.length) return { rows: [], skipped: 0, sourceLabel };

      let startIndex = 0;
      let kyIndex = 0;
      let dateIndex = 1;
      let timeIndex = 2;
      let numbersIndex = 3;

      const headerCells = splitCsvRow(lines[0]).map(normalizeHeaderName);
      const looksLikeHeader = headerCells.includes("ky") || headerCells.includes("numbers") || headerCells.includes("ngay");
      if (looksLikeHeader) {
        startIndex = 1;
        const idxKy = headerCells.findIndex(name => name === "ky");
        const idxDate = headerCells.findIndex(name => name === "ngay" || name === "date");
        const idxTime = headerCells.findIndex(name => name === "time" || name === "gio");
        const idxNumbers = headerCells.findIndex(name => name === "numbers" || name === "so" || name === "ketqua");
        if (idxKy >= 0) kyIndex = idxKy;
        if (idxDate >= 0) dateIndex = idxDate;
        if (idxTime >= 0) timeIndex = idxTime;
        if (idxNumbers >= 0) numbersIndex = idxNumbers;
      }

      const rows = [];
      let skipped = 0;
      for (let i = startIndex; i < lines.length; i++) {
        const cells = splitCsvRow(lines[i]);
        if (!cells.some(Boolean)) continue;
        const ky = String(cells[kyIndex] || "").replace(/\D/g, "");
        const date = String(cells[dateIndex] || "").trim();
        const time = String(cells[timeIndex] || "").trim();
        try {
          const numbers = parseDistinctSortedNums(
            parseNums(cells[numbersIndex] || ""),
            1,
            80,
            20,
            20,
            `CSV ${sourceLabel} dòng ${i + 1}`
          );
          if (!ky) throw new Error("Thiếu kỳ");
          rows.push({
            ky,
            draw: { main: numbers, special: null, date, time }
          });
        } catch {
          skipped++;
        }
      }
      return { rows, skipped, sourceLabel };
    }

    function saveKenoCsvFeedCache() {
      try {
        localStorage.setItem(LOCAL_KENO_CSV_CACHE_KEY, JSON.stringify({
          results: kenoCsvFeed.results,
          order: kenoCsvFeed.order,
          sourceLabels: kenoCsvFeed.sourceLabels,
          loadedAt: kenoCsvFeed.loadedAt
        }));
      } catch {}
    }

    function restoreKenoCsvFeedCache() {
      kenoCsvFeedCacheRestored = true;
      try {
        const raw = localStorage.getItem(LOCAL_KENO_CSV_CACHE_KEY);
        if (!raw) {
          kenoCsvFeed = emptyKenoCsvFeed();
          return;
        }
        const parsed = JSON.parse(raw);
        const next = emptyKenoCsvFeed();
        next.sourceLabels = Array.isArray(parsed?.sourceLabels) ? parsed.sourceLabels : [];
        next.loadedAt = String(parsed?.loadedAt || "");
        const resultMap = parsed?.results && typeof parsed.results === "object" ? parsed.results : {};
        for (const [ky, draw] of Object.entries(resultMap)) {
          mergeKenoDraw(next, ky, draw);
        }
        kenoCsvFeed = finalizeKenoCsvFeed(next, next.loadedAt || getSyncedIsoString());
      } catch {
        kenoCsvFeed = emptyKenoCsvFeed();
      }
    }

    function setKenoCsvFeed(feed, loadedAt = getSyncedIsoString()) {
      kenoCsvFeed = finalizeKenoCsvFeed(feed, loadedAt);
      saveKenoCsvFeedCache();
      updateKenoCsvStatus();
      const predictionLogsBeforeReconcile = getPredictionLogsSignature(store.predictionLogs?.KENO || []);
      reconcilePredictionLogsForType("KENO");
      if (getPredictionLogsSignature(store.predictionLogs?.KENO || []) !== predictionLogsBeforeReconcile) {
        saveStore();
      }
    }

    function updateKenoCsvStatus(extraMessage = "", cls = "") {
      const el = document.getElementById("pdCsvStatus");
      if (!el) return;
      const statusLoadedAt = String(kenoPredictStatusMeta.loadedAt || "");
      const loadedText = statusLoadedAt
        ? new Date(statusLoadedAt).toLocaleString("vi-VN")
        : "";
      const detailMessage = extraMessage || String(kenoPredictStatusMeta.detail || "");

      let message = "";
      let level = cls || String(kenoPredictStatusMeta.level || "");
      if (statusLoadedAt) {
        message = loadedText
          ? `Cập nhật lần cuối: ${loadedText}.`
          : "Đã tự động đồng bộ CSV Keno.";
        if (!level) level = "ok";
      } else {
        message = IS_LOCAL_MODE
          ? "Chưa có CSV Keno trong bộ nhớ. Hãy mở trang qua http://localhost:8080 để web tự đồng bộ dữ liệu dự đoán."
          : "Dữ liệu Keno sẽ tự đồng bộ khi bấm Dự đoán.";
        if (!level) level = "muted";
      }

      if (detailMessage) message += `\n${detailMessage}`;
      line(el, message, level);
    }

    function setKenoPredictStatusMeta(detail = "", level = "", loadedAt = getSyncedIsoString()) {
      kenoPredictStatusMeta = {
        loadedAt: String(loadedAt || ""),
        detail: String(detail || ""),
        level: String(level || "")
      };
      updateKenoCsvStatus(detail, level);
    }

    function toKenoNumberTokens(numbers) {
      return (Array.isArray(numbers) ? numbers : [])
        .map(value => Number(value))
        .filter(Number.isFinite)
        .sort((a, b) => a - b)
        .map(value => String(Number(value) || 0).padStart(2, "0"));
    }

    function formatKenoNumberList(numbers) {
      return toKenoNumberTokens(numbers).join(", ");
    }

    function formatKenoNumberRows(numbers, perRow = 10) {
      const tokens = toKenoNumberTokens(numbers);
      const rows = [];
      for (let i = 0; i < tokens.length; i += perRow) {
        rows.push(tokens.slice(i, i + perRow).join(", "));
      }
      return rows;
    }

    // ----- CSV Keno và predictor Keno -----
    // Parse nguồn CSV Keno, chuẩn hóa hiển thị và xử lý nhánh dự đoán Keno riêng.
    function formatKenoPythonPrediction(result) {
      const sync = result?.sync || {};
      const selected = result?.selected || {};
      const selectedModel = selected?.model || {};
      const lastDraw = selected?.last_draw || {};
      const bundles = Array.isArray(selected?.prediction_bundles) ? selected.prediction_bundles : [];
      const lines = [];
      const addLine = (value = "") => {
        const text = String(value || "").trim();
        if (text) lines.push(text);
      };

      if (sync?.sync_error) {
        addLine(`Không thể đồng bộ web, đang dùng dữ liệu local: ${sync.sync_error}`);
      } else if (sync?.latest_date) {
        addLine(`Đã cập nhật web ngày ${sync.latest_date}: +${Number(sync.new_rows || 0)} kỳ mới.`);
      }
      addLine(`Bạn đã chọn: Bậc ${selected.order}`);
      addLine(`Số bộ đã chọn: ${selected.bundle_count}`);
      if (lastDraw.ky) {
        addLine(`Kỳ gần nhất trong dữ liệu: ${lastDraw.ky} - ${lastDraw.ngay || ""} ${lastDraw.time || ""}`.trim());
      }
      if (selected.next_ky) addLine(`Dự đoán kỳ tiếp theo: ${selected.next_ky}`);
      if (Array.isArray(selected.top_numbers) && selected.top_numbers.length) {
        addLine(`Top ${selected.top_numbers.length} số tham khảo:`);
        formatKenoNumberRows(selected.top_numbers, 10).forEach(addLine);
      }
      if (bundles.length) {
        addLine("Các bộ dự đoán:");
        bundles.forEach((bundle, index) => {
          addLine(`Bộ ${index + 1}: ${formatKenoNumberList(bundle)}`);
        });
      }
      if (selected.predicted_ln) addLine(`Dự đoán Lớn/Nhỏ: ${selected.predicted_ln}`);
      if (selected.predicted_cl) addLine(`Dự đoán Chẵn/Lẻ: ${selected.predicted_cl}`);
      if (selected.order && selectedModel.label) {
        addLine(
          `Độ khớp trung bình của bậc ${selected.order}: ${(Number(selectedModel.avg_hit_rate || 0) * 100).toFixed(2)}% ` +
          `(${Number(selectedModel.avg_hits || 0).toFixed(2)} số/kỳ)`
        );
      }
      return lines.map(line => line ? escapeHtml(line) : "").join("<br>");
    }

    // ----- Kết quả AI predict -----
    // Chuẩn hóa payload từ backend AI và render ra phần Tóm tắt AI / Chi tiết dự đoán.
    async function predictWithAiBackend(type, count, kenoLevel = 0, engine = "gen_local", riskMode = "balanced", predictionMode = PREDICTION_MODE_NORMAL) {
      const params = new URLSearchParams();
      params.set("type", type);
      params.set("count", String(count));
      if (type === "KENO") params.set("kenoLevel", String(kenoLevel));
      params.set("engine", String(engine || "gen_local"));
      params.set("riskMode", normalizePredictRiskMode(riskMode));
      params.set("predictionMode", normalizePredictionMode(predictionMode));
      try {
        return await api(`/api/ai-predict?${params.toString()}`);
      } catch (err) {
        if (isAiPredictRouteMissingError(err)) {
          throw new Error("Server đang chạy bản cũ và chưa hỗ trợ /api/ai-predict. Hãy tắt server rồi chạy lại .\\chay_lotto_web.bat.");
        }
        throw err;
      }
    }

    function formatPredictRemaining(ms) {
      const totalSeconds = Math.max(0, Math.ceil((Number(ms) || 0) / 1000));
      const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
      const seconds = String(totalSeconds % 60).padStart(2, "0");
      return `${minutes}:${seconds}`;
    }

    function renderPredictLoadingText(engineKey, engineLabel, elapsedMs = 0) {
      if (engineKey === "both") {
        const remainingMs = Math.max(0, predictBothAvgDurationMs - Math.max(0, elapsedMs));
        return `Đang đồng bộ dữ liệu AI và chạy đồng thời Luận Số + AI Gen... (Thời gian còn lại: ${formatPredictRemaining(remainingMs)})`;
      }
      return `Đang đồng bộ dữ liệu AI và chạy ${engineLabel}...`;
    }

    function startPredictLoading(out, engineKey, engineLabel) {
      if (!out) return;
      if (predictLoadingTimer) {
        window.clearInterval(predictLoadingTimer);
        predictLoadingTimer = null;
      }
      predictLoadingStartAt = Date.now();
      predictLoadingEngineKey = String(engineKey || "");
      line(out, renderPredictLoadingText(engineKey, engineLabel, 0), "muted");
      if (engineKey !== "both") {
        return;
      }
      predictLoadingTimer = window.setInterval(() => {
        const elapsedMs = Date.now() - predictLoadingStartAt;
        line(out, renderPredictLoadingText(engineKey, engineLabel, elapsedMs), "muted");
      }, 500);
    }

    function stopPredictLoading(engineKey, durationMs = 0) {
      if (predictLoadingTimer) {
        window.clearInterval(predictLoadingTimer);
        predictLoadingTimer = null;
      }
      if (engineKey === "both" && Number.isFinite(durationMs) && durationMs > 0) {
        const nextAvg = Math.round((predictBothAvgDurationMs * 0.7) + (durationMs * 0.3));
        predictBothAvgDurationMs = Math.max(5000, Math.min(60000, nextAvg));
      }
      predictLoadingStartAt = 0;
      predictLoadingEngineKey = "";
    }

    function formatAiPredictionText(result) {
      const sync = result?.sync || {};
      const model = result?.model || {};
      const tickets = Array.isArray(result?.tickets) ? result.tickets : [];
      const normalizedRankings = normalizePredictionTopRankings(
        result?.type,
        result?.topRanking,
        result?.topSpecialRanking,
        tickets,
      );
      const topRanking = normalizedRankings.main;
      const topSpecialRanking = normalizedRankings.special;
      const notes = Array.isArray(result?.notes) ? result.notes : [];
      const ticketSources = Array.isArray(result?.ticketSources) ? result.ticketSources : [];
      const backtest = result?.backtest || {};
      const type = String(result?.type || "");
      const engine = String(result?.engine || "gen_local").trim().toLowerCase();
      const selectedEngine = getPredictEngineMeta(engine);
      const engineLabel = String(result?.engineLabel || selectedEngine.label || "AI Gen").trim();
      const riskMode = getResultRiskMode(result, predictRiskModeValue);
      const riskModeMeta = getPredictRiskModeMeta(riskMode);
      const isAiGenEngine = engine === "gen_local" || engine === "both";
      const isLuanSoEngine = engine === "luan_so";
      const adaptiveVipMeta = getAdaptiveVipPredictorMeta(result);
      const isPredictorV2 = adaptiveVipMeta.active;
      const syncReady = sync?.bootstrapComplete !== false || Boolean(sync?.sourceLimited);
      const isReady = result?.ready !== false && (result?.bootstrapComplete !== false || syncReady);
      const getTicketSourceLabel = index => {
        const rawSource = String(ticketSources[index] || "").trim().toLowerCase();
        if (adaptiveVipMeta.active && rawSource === adaptiveVipMeta.key) return adaptiveVipMeta.sourceLabel;
        if (rawSource === "loto_5_35_vip") return "Loto 5/35 Vip";
        if (rawSource === "predictor_v2" || rawSource === "vip_v2") return "Predictor V2";
        if (rawSource === "mega_6_45_vip") return "Mega 6/45 Vip";
        if (rawSource === "power_6_55_vip") return "Power 6/55 Vip";
        if (rawSource === "luan_so") return "Luận Số";
        if (rawSource === "gen_local" || rawSource === "ai_gen" || rawSource === "ai gen") return "AI GEN";
        if (adaptiveVipMeta.active && engine === adaptiveVipMeta.key) return adaptiveVipMeta.sourceLabel;
        if (engine === "loto_5_35_vip") return "Loto 5/35 Vip";
        if (engine === "predictor_v2") return "Predictor V2";
        if (engine === "mega_6_45_vip") return "Mega 6/45 Vip";
        if (engine === "power_6_55_vip") return "Power 6/55 Vip";
        if (engine === "both") return index % 2 === 0 ? "Luận Số" : "AI GEN";
        if (engine === "luan_so") return "Luận Số";
        return "AI GEN";
      };
      const formatCount = value => Number(value || 0).toLocaleString("vi-VN");
      const backtestRate = Number(model.avgHitRate || backtest?.avgHitRate || 0);
      const backtestHits = Number(model.avgHits || backtest?.avgHits || 0);
      const backtestSamples = Number(model.samples || backtest?.samples || 0);
      const playModeLabel = String(result?.playMode || predictPlayModeValue || "normal").trim().toLowerCase() === "bao" ? "Bao Số" : "Vé Thường";
      const compactTop = topRanking;
      const topSpecialCompact = topSpecialRanking;
      const metricCards = [];
      const notesPool = [];
      const parseMetricRate = value => {
        const numeric = Number(value);
        return Number.isFinite(numeric) ? numeric : null;
      };
      const buildMetricDelta = (currentValue, baselineValue) => {
        const current = parseMetricRate(currentValue);
        const baseline = parseMetricRate(baselineValue);
        if (current == null || baseline == null) return null;
        const delta = current - baseline;
        const absDelta = Math.abs(delta);
        const direction = absDelta < 0.00005 ? "flat" : delta > 0 ? "up" : "down";
        const prefix = direction === "flat" ? "±" : delta > 0 ? "+" : "-";
        return {
          value: delta,
          direction,
          text: `${prefix}${(absDelta * 100).toFixed(2)}%`,
        };
      };
      const addMetricCard = (label, value, meta = "", accent = "", delta = null) => {
        const safeLabel = String(label || "").trim();
        const safeValue = String(value || "").trim();
        const safeMeta = String(meta || "").trim();
        if (!safeLabel || !safeValue) return;
        metricCards.push({
          label: safeLabel,
          value: safeValue,
          meta: safeMeta,
          accent: String(accent || "").trim(),
          delta: delta && typeof delta === "object" ? delta : null,
        });
      };
      const addNote = value => {
        const text = String(value || "").trim();
        if (text) notesPool.push(text);
      };
      const formatTopRowsHtml = (numbers, { special = false } = {}) => {
        if (!Array.isArray(numbers) || !numbers.length) return "";
        if (type === "KENO" && !special) {
          return formatKenoNumberRows(numbers, 10)
            .map(row => `<div class="ai-result-top-row">${escapeHtml(row.replace(/,\s*/g, " "))}</div>`)
            .join("");
        }
        if (TYPES[type]?.threeDigit && !special) {
          return formatPredictNumberRows(numbers, type, 10)
            .map(row => `<div class="ai-result-top-row">${escapeHtml(row.replace(/,\s*/g, " "))}</div>`)
            .join("");
        }
        const text = numbers.map(number => formatPredictNumber(number, type)).join(", ");
        return `<div class="ai-result-top-row">${escapeHtml(text)}</div>`;
      };
      const formatTicketNumbersHtml = ticket => {
        const main = Array.isArray(ticket?.main) ? ticket.main : [];
        if (type === "KENO") {
          const rows = formatKenoNumberRows(main, 10);
          return rows.map(row => `<div class="ai-result-ticket-row">${escapeHtml(row.replace(/,\s*/g, " "))}</div>`).join("");
        }
        if (TYPES[type]?.threeDigit && main.length) {
          return `<div class="ai-result-ticket-main">${escapeHtml(main.map(number => formatPredictNumber(number, type)).join(" | "))}</div>`;
        }
        if (TYPES[type]?.threeDigit && main.length > 10) {
          const rows = formatPredictNumberRows(main, type, 10);
          return rows.map(row => `<div class="ai-result-ticket-row">${escapeHtml(row.replace(/,\s*/g, " "))}</div>`).join("");
        }
        return `<div class="ai-result-ticket-main">${escapeHtml(main.map(number => formatPredictNumber(number, type)).join(" "))}</div>`;
      };
      const formatTicketSpecialHtml = ticket => {
        if (type === "KENO") return "";
        if (TYPES[type]?.hasSpecial && Number.isInteger(ticket?.special)) {
          return `<div class="ai-result-ticket-special">ĐB ${escapeHtml(formatPredictNumber(ticket.special, type))}</div>`;
        }
        return "";
      };
      const backtestText = !isReady
        ? "Chưa mở"
        : backtestSamples || backtestRate
        ? `${(backtestRate * 100).toFixed(2)}%`
        : "Chưa đủ mẫu";
      const backtestMeta = !isReady
        ? "Chờ bootstrap full-history hoàn tất"
        : backtestSamples
        ? `${formatCount(backtestSamples)} mẫu • ${backtestHits.toFixed(2)} số/kỳ`
        : "Đang dùng kết quả backtest hiện có";
      const previousComparableEntry = findPreviousPredictionLogForMetrics(result);
      const comparedMetaSuffix = previousComparableEntry ? " • So với lần trước cùng cấu hình" : "";
      const previousBacktestRate = parseMetricRate(previousComparableEntry?.backtest?.avgHitRate);
      const backtestDelta = buildMetricDelta(backtestRate, previousBacktestRate);
      if (model?.label) {
        addMetricCard(
          isAiGenEngine ? "Champion" : "Model thắng",
          model.label,
          [model?.key ? `Key ${model.key}` : "", result?.historyCount ? `${formatCount(result.historyCount)} kỳ train` : "", result?.latestKy ? `Mới nhất ${formatLiveKy(result.latestKy)}` : ""].filter(Boolean).join(" • ")
        );
      } else if (result?.historyCount) {
        addMetricCard("Số kỳ train", formatCount(result.historyCount), result?.latestKy ? `Mới nhất ${formatLiveKy(result.latestKy)}` : "");
      }
      addMetricCard("Độ khớp backtest", backtestText, `${backtestMeta}${comparedMetaSuffix}`, "", backtestDelta);
      const probabilitySummary = result?.probabilitySummary || {};
      const controlledMetrics = result?.backtest?.metrics || result?.backtest?.winner_summary || result?.backtest || {};
      const randomBaseline = result?.randomBaseline || result?.backtest?.random_baseline || {};
      if (result?.predictionStatus || result?.predictionId) {
        addMetricCard(
          "Ledger",
          String(result?.predictionStatus || "locked").toUpperCase(),
          [result?.predictionId ? `ID ${String(result.predictionId).slice(0, 8)}` : "", result?.dataCutoffDrawId ? `Cutoff ${formatLiveKy(result.dataCutoffDrawId)}` : ""].filter(Boolean).join(" • ")
        );
      }
      if (result?.modelVersion) {
        addMetricCard("Model version", String(result.modelVersion), result?.modelRole ? String(result.modelRole) : "Champion hiện hành");
      }
      if (Number(probabilitySummary?.mainProbabilitySum || 0) > 0) {
        addMetricCard(
          "Calibrated probability",
          `Σp=${Number(probabilitySummary.mainProbabilitySum || 0).toFixed(2)}`,
          `Main K=${Number(probabilitySummary.mainDrawSize || result?.pickSize || 0)} • capped simplex`
        );
      }
      const meanHitValue = Number(controlledMetrics.mean_hit ?? controlledMetrics.average_hits ?? controlledMetrics.avgHits ?? 0);
      const brierValue = Number(controlledMetrics.brier_score ?? controlledMetrics.brierScore ?? NaN);
      const logLossValue = Number(controlledMetrics.log_loss ?? controlledMetrics.logLoss ?? NaN);
      const liftValue = Number(controlledMetrics.lift ?? NaN);
      if (Number.isFinite(meanHitValue) && meanHitValue > 0) {
        const baselineHits = Number(randomBaseline.expected_hits || controlledMetrics.expected_random_hits || 0);
        addMetricCard("Mean Hit", meanHitValue.toFixed(3), baselineHits ? `Ngẫu nhiên ${baselineHits.toFixed(3)}` : "So sánh cùng kỳ");
      }
      if (Number.isFinite(brierValue) && brierValue > 0) {
        addMetricCard("Brier Score", brierValue.toFixed(5), "Thấp hơn là tốt hơn");
      }
      if (Number.isFinite(logLossValue) && logLossValue > 0) {
        addMetricCard("Log Loss", logLossValue.toFixed(5), "Xác suất được chặn 1e-6");
      }
      if (Number.isFinite(liftValue)) {
        addMetricCard("Lift", `${(liftValue * 100).toFixed(2)}%`, liftValue > 0 ? "Vượt baseline ngẫu nhiên" : "Chưa vượt baseline ngẫu nhiên");
        if (liftValue <= 0) addNote("Cảnh báo: backtest hiện chưa vượt baseline ngẫu nhiên trên cùng các kỳ.");
      }
      if (isAiGenEngine) {
        const confidence = Number(result?.confidence || 0);
        const stabilityScore = parseMetricRate(result?.stabilityScore ?? backtest?.stabilityScore);
        const stabilityValue = stabilityScore != null ? stabilityScore : confidence;
        const previousStabilityValue = parseMetricRate(
          previousComparableEntry?.stabilityScore ??
          previousComparableEntry?.backtest?.stabilityScore ??
          previousComparableEntry?.confidence
        );
        const stabilityDelta = buildMetricDelta(stabilityValue, previousStabilityValue);
        addMetricCard(
          "Độ ổn định",
          `${(stabilityValue * 100).toFixed(2)}%`,
          `Tự điều chỉnh theo dữ liệu mới${comparedMetaSuffix}`,
          "",
          stabilityDelta
        );
      }
      if (engine === "both" && result?.metaSelectionMode === "smart_interleave") {
        const preferredEngineLabel = String(result?.metaPreferredEngine || "").trim().toLowerCase() === "gen_local" ? "AI Gen" : "Luận Số";
        addMetricCard("Meta ưu tiên", preferredEngineLabel, result?.metaSummary || "Đang tự cân đối theo phong độ gần đây", "preferred");
      }
      // predictor_v2 integration start
      if (isPredictorV2) {
        const qualityScore = Number(result?.qualityScore ?? result?.quality_score ?? 0);
        const trackingState = result?.tracking_state || {};
        const deepEnabled = Boolean(result?.deep_enabled);
        const deepStatus = String(result?.deep_status || "").trim() || "fallback_heuristic_only";
        const deepStatusLine = String(result?.deep_status_line || "").trim();
        const prioritizedCount = Array.isArray(trackingState?.prioritized_special)
          ? trackingState.prioritized_special.length
          : Array.isArray(trackingState?.prioritized_bonus)
          ? trackingState.prioritized_bonus.length
          : 0;
        const prioritizedLabel = type === "LOTO_6_55" ? "Special" : "Bonus";
        const slotMeta = [String(result?.target_date || "").trim(), String(result?.target_slot || "").trim()].filter(Boolean).join(" • ") || "-";
        if (qualityScore > 0) {
          addMetricCard(
            "Chất lượng vé",
            `${qualityScore.toFixed(2)}/100`,
            `${String(result?.regimeLabel || result?.regime || "Neutral")} • ${slotMeta}`,
            "preferred"
          );
        }
        addMetricCard(
          "Deep Status",
          deepEnabled ? "ACTIVE" : deepStatus.toUpperCase(),
          deepStatusLine || (deepEnabled ? "CNN/RNN deep scoring is active." : "Heuristic-only fallback is active.")
        );
        addMetricCard(
          "Bộ nhớ giữ nhịp",
          `${Array.isArray(trackingState?.kept_numbers) ? trackingState.kept_numbers.length : 0} giữ • ${Array.isArray(trackingState?.temporary_excluded_numbers) ? trackingState.temporary_excluded_numbers.length : 0} cooldown`,
          `Hot ${Array.isArray(trackingState?.true_hot_numbers) ? trackingState.true_hot_numbers.length : 0} • ${prioritizedLabel} ${prioritizedCount}`
        );
      }
      // predictor_v2 integration end
      if (isLuanSoEngine && result?.signalSummary) {
        const signal = result.signalSummary || {};
          const directionLabel = signal.dominantDirection === "backward"
            ? "Backward"
            : signal.dominantDirection === "forward"
            ? "Forward"
            : "Chưa rõ";
        addMetricCard(
          "Tín hiệu chính",
          `${directionLabel} • W=${Number(signal.dominantWindow || 0) || "-"}`,
          `${Number(signal.strongPairCount || 0)} Strong • ${Number(signal.watchPairCount || 0)} Watchlist`
        );
      }

      if (!isReady) {
        addNote(
          !syncReady
            ? "Dữ liệu lịch sử chưa sẵn sàng. Predictor sẽ mở lại khi bootstrap hoàn tất."
            : "Predictor đang tạm khóa cho tới khi dữ liệu canonical sẵn sàng."
        );
        (isPredictorV2 ? notes.slice(0, 3) : notes.slice(0, 1)).forEach(addNote);
      } else {
        if (type === "KENO" && (result?.predictedLn || result?.predictedCl)) {
          const quickFlags = [result?.predictedLn, result?.predictedCl].filter(Boolean).join(" • ");
          if (quickFlags) addNote(`Dự đoán nhanh: ${quickFlags}`);
        }
        if (isPredictorV2 && (result?.target_slot || result?.target_date)) {
          const targetMeta = [String(result?.target_date || "").trim(), String(result?.target_slot || "").trim()].filter(Boolean).join(" • ");
          addNote(`Khung Vip mục tiêu: ${targetMeta}`);
        }
        (isPredictorV2 ? notes.slice(0, 3) : notes.slice(0, 1)).forEach(addNote);
      }
      const heroBadges = [
        engineLabel,
        playModeLabel,
        engine === "both" ? riskModeMeta.label : "",
        result?.nextKy ? `Kỳ ${result.nextKy}` : "",
        String(result?.playMode || predictPlayModeValue || "normal").trim().toLowerCase() === "bao" && (result?.baoLevel || predictBaoLevelValue) ? `Bao ${result?.baoLevel || predictBaoLevelValue}` : "",
        type === "KENO" && result?.pickSize ? `Bậc ${result.pickSize}` : "",
      ].filter(Boolean);
      const headerNote = result?.lastTrainedAt
        ? `Học gần nhất: ${String(result.lastTrainedAt).replace("T", " ")}`
        : "";
      const ticketCardsHtml = isReady && tickets.length
        ? tickets.map((ticket, index) => {
            const isBaoTicket = String(ticket?.playMode || "").trim().toLowerCase() === "bao";
            const isThreeDigitTicket = !!TYPES[type]?.threeDigit;
            const ticketLabel = isBaoTicket
              ? `Bộ ${index + 1} • Bao ${ticket?.baoLevel || (ticket?.main || []).length || ""}`.trim()
              : `Bộ ${index + 1}`;
            const sourceLabel = engine === "both" ? getTicketSourceLabel(index) : engineLabel;
            if (isThreeDigitTicket) {
              return `
                <article class="ai-result-ticket-card ai-result-ticket-card-inline">
                  <div class="ai-result-ticket-inline-main">
                    <div class="ai-result-ticket-label">${escapeHtml(ticketLabel)}</div>
                    <div class="ai-result-ticket-body">
                      ${formatTicketNumbersHtml(ticket)}
                      ${formatTicketSpecialHtml(ticket)}
                    </div>
                  </div>
                  <div class="ai-result-ticket-source">${escapeHtml(sourceLabel)}</div>
                </article>
              `;
            }
            return `
              <article class="ai-result-ticket-card">
                <div class="ai-result-ticket-head">
                  <div class="ai-result-ticket-label">${escapeHtml(ticketLabel)}</div>
                  <div class="ai-result-ticket-source">${escapeHtml(sourceLabel)}</div>
                </div>
                <div class="ai-result-ticket-body">
                  ${formatTicketNumbersHtml(ticket)}
                  ${formatTicketSpecialHtml(ticket)}
                </div>
              </article>
            `;
          }).join("")
        : `<div class="ai-result-empty">${escapeHtml(notesPool[0] || "Dữ liệu dự đoán chưa sẵn sàng.")}</div>`;
      const topSectionHtml = (compactTop.length || topSpecialCompact.length)
        ? `<section class="ai-result-block ai-result-top-block">
            <div class="ai-result-block-head">
              <div class="ai-result-block-title">Top số ưu tiên</div>
              <div class="ai-result-block-meta">${escapeHtml(`Top ${compactTop.length}`)}</div>
            </div>
            ${compactTop.length ? `
              <div class="ai-result-top-item">
                <div class="ai-result-top-label">Top số</div>
                <div class="ai-result-top-body">${formatTopRowsHtml(compactTop)}</div>
              </div>
            ` : ""}
            ${topSpecialCompact.length ? `
              <div class="ai-result-top-item">
                <div class="ai-result-top-label">Top ĐB</div>
                <div class="ai-result-top-body">${formatTopRowsHtml(topSpecialCompact, { special: true })}</div>
              </div>
            ` : ""}
          </section>`
        : "";
      const notesHtml = notesPool.length
        ? `<section class="ai-result-block">
            <div class="ai-result-block-head">
              <div class="ai-result-block-title">Ghi chú</div>
              <div class="ai-result-block-meta">AI</div>
            </div>
            <div class="ai-result-notes">${notesPool.map(note => `<div class="ai-result-note-line">${escapeHtml(note)}</div>`).join("")}</div>
          </section>`
        : "";
      const heroHeaderItems = [
        ...heroBadges.map(badge => {
          const isRiskBadge = engine === "both" && badge === riskModeMeta.label;
          const riskClass = isRiskBadge ? ` ai-result-badge-risk is-${riskMode}` : "";
          return `<span class="ai-result-badge${riskClass}">${escapeHtml(badge)}</span>`;
        }),
        headerNote ? `<span class="ai-result-badge ai-result-badge-note">${escapeHtml(headerNote)}</span>` : "",
      ].filter(Boolean).join("");
      const modelDetailsHtml = metricCards.length
        ? `<details class="ai-result-tech-details">
            <summary class="ai-result-tech-summary">
              <span class="ai-result-tech-summary-main">
                <span class="ai-result-tech-title">Thông tin mô hình</span>
                <span class="ai-result-tech-count">${escapeHtml(`${metricCards.length} chỉ số`)}</span>
              </span>
              <span class="ai-result-tech-chevron" aria-hidden="true">⌄</span>
            </summary>
            <div class="ai-result-tech-content">
              <section class="ai-result-metrics">
                ${metricCards.map(card => `
                  <article class="ai-result-metric${card.accent ? ` is-${card.accent}` : ""}">
                    <div class="ai-result-metric-label">${escapeHtml(card.label)}</div>
                    <div class="ai-result-metric-main">
                      <div class="ai-result-metric-value">${escapeHtml(card.value)}</div>
                      ${card.delta ? `<div class="ai-result-metric-delta is-${escapeHtml(card.delta.direction || "flat")}">${escapeHtml(card.delta.text || "")}</div>` : ""}
                    </div>
                    ${card.meta ? `<div class="ai-result-metric-meta">${escapeHtml(card.meta)}</div>` : ""}
                  </article>
                `).join("")}
              </section>
            </div>
          </details>`
        : "";
      return `<div class="ai-result-shell">
        ${heroHeaderItems ? `
          <section class="ai-result-hero ai-result-hero-compact">
            <div class="ai-result-badges">${heroHeaderItems}</div>
          </section>
        ` : ""}
        <section class="ai-result-block ai-result-ticket-block">
          <div class="ai-result-block-head">
            <div class="ai-result-block-title">Chi tiết dự đoán</div>
            <div class="ai-result-block-meta">${escapeHtml(isReady ? `${tickets.length || 0} bộ số` : "Trạng thái dữ liệu")}</div>
          </div>
          <div class="ai-result-ticket-grid">${ticketCardsHtml}</div>
        </section>
        ${topSectionHtml}
        ${notesHtml}
        ${modelDetailsHtml}
      </div>`;
    }

    function renderPredictOutput(result = predictLastDisplayResult) {
      const out = document.getElementById("predictOut");
      if (!out) return;
      predictLastDisplayResult = result || predictLastDisplayResult || null;
      if (!predictLastDisplayResult) return;
      out.classList.remove("muted");
      out.innerHTML = formatAiPredictionText(predictLastDisplayResult);
    }

    function getAdaptiveVipPredictorMeta(result = {}) {
      const version = String(result?.predictorVersion || "").trim().toLowerCase();
      if (version === "loto_5_35_vip_v1") {
        return {
          active: true,
          key: "loto_5_35_vip",
          label: String(result?.engineLabel || "Loto 5/35 Vip Adaptive").trim() || "Loto 5/35 Vip Adaptive",
          sourceLabel: "Loto 5/35 Vip",
        };
      }
      if (version === "predictor_v2") {
        return {
          active: true,
          key: "predictor_v2",
          label: String(result?.engineLabel || "Predictor V2 Vip").trim() || "Predictor V2 Vip",
          sourceLabel: "Predictor V2",
        };
      }
      if (version === "mega_6_45_vip_v1") {
        return {
          active: true,
          key: "mega_6_45_vip",
          label: String(result?.engineLabel || "Mega 6/45 Vip Adaptive").trim() || "Mega 6/45 Vip Adaptive",
          sourceLabel: "Mega 6/45 Vip",
        };
      }
      if (version === "power_6_55_vip_v1") {
        return {
          active: true,
          key: "power_6_55_vip",
          label: String(result?.engineLabel || "Power 6/55 Vip Adaptive").trim() || "Power 6/55 Vip Adaptive",
          sourceLabel: "Power 6/55 Vip",
        };
      }
      return {
        active: false,
        key: "",
        label: "",
        sourceLabel: "",
      };
    }

    function getPredictVipTicketSourceLabel(result, index) {
      const ticketSources = Array.isArray(result?.ticketSources) ? result.ticketSources : [];
      const rawSource = String(ticketSources[index] || "").trim().toLowerCase();
      const engine = String(result?.engine || "gen_local").trim().toLowerCase();
      const adaptiveVipMeta = getAdaptiveVipPredictorMeta(result);
      if (adaptiveVipMeta.active && rawSource === adaptiveVipMeta.key) return adaptiveVipMeta.sourceLabel;
      if (rawSource === "loto_5_35_vip") return "Loto 5/35 Vip";
      if (rawSource === "predictor_v2" || rawSource === "vip_v2") return "Predictor V2";
      if (rawSource === "mega_6_45_vip") return "Mega 6/45 Vip";
      if (rawSource === "power_6_55_vip") return "Power 6/55 Vip";
      if (rawSource === "luan_so") return "Luận Số";
      if (rawSource === "gen_local" || rawSource === "ai_gen" || rawSource === "ai gen") return "AI GEN";
      if (adaptiveVipMeta.active && engine === adaptiveVipMeta.key) return adaptiveVipMeta.sourceLabel;
      if (engine === "loto_5_35_vip") return "Loto 5/35 Vip";
      if (engine === "predictor_v2") return "Predictor V2";
      if (engine === "mega_6_45_vip") return "Mega 6/45 Vip";
      if (engine === "power_6_55_vip") return "Power 6/55 Vip";
      if (engine === "both") return index % 2 === 0 ? "Luận Số" : "AI GEN";
      if (engine === "luan_so") return "Luận Số";
      return "AI GEN";
    }

    function formatPredictVipTicketLabel(type, ticket, index) {
      const isBaoTicket = String(ticket?.playMode || "").trim().toLowerCase() === "bao";
      if (isBaoTicket) {
        const baoLevel = Number(ticket?.baoLevel || (Array.isArray(ticket?.main) ? ticket.main.length : 0) || 0);
        return `Bộ ${index + 1} • Bao ${baoLevel || ""}`.trim();
      }
      if (type === "KENO" && Number.isInteger(Number(ticket?.main?.length || 0))) {
        return `Bộ ${index + 1} • Bậc ${Number(ticket.main.length || 0)}`;
      }
      return `Bộ ${index + 1}`;
    }

    function formatPredictVipTopRows(numbers, type, perRow = 10) {
      const values = Array.isArray(numbers) ? numbers.map(Number).filter(Number.isInteger) : [];
      if (!values.length) return "";
      if (type === "KENO") {
        return formatKenoNumberRows(values, perRow)
          .map(row => `<div class="predict-vip-top-row">${escapeHtml(row.replace(/,\s*/g, " "))}</div>`)
          .join("");
      }
      if (TYPES[type]?.threeDigit) {
        return formatPredictNumberRows(values, type, perRow)
          .map(row => `<div class="predict-vip-top-row">${escapeHtml(row.replace(/,\s*/g, " "))}</div>`)
          .join("");
      }
      return `<div class="predict-vip-top-row">${escapeHtml(values.map(number => formatPredictNumber(number, type)).join(" "))}</div>`;
    }

    function renderPredictVipTicketNumbers(ticket, type) {
      const main = Array.isArray(ticket?.main) ? ticket.main.map(Number).filter(Number.isInteger) : [];
      const tokens = main.map(number => `<span class="predict-vip-number">${escapeHtml(formatPredictNumber(number, type))}</span>`);
      if (TYPES[type]?.hasSpecial && Number.isInteger(ticket?.special)) {
        tokens.push(`<span class="predict-vip-number is-special">ĐB ${escapeHtml(formatPredictNumber(ticket.special, type))}</span>`);
      }
      return `<div class="predict-vip-number-list">${tokens.join("")}</div>`;
    }

    function buildPredictVipTicketAnalyses(result) {
      const type = String(result?.type || "").trim().toUpperCase();
      const tickets = Array.isArray(result?.tickets) ? result.tickets : [];
      const topRanking = Array.isArray(result?.topRanking) ? result.topRanking.map(Number).filter(Number.isInteger) : [];
      const topSpecialRanking = Array.isArray(result?.topSpecialRanking) ? result.topSpecialRanking.map(Number).filter(Number.isInteger) : [];
      const topMainIndex = new Map(topRanking.map((number, index) => [number, index]));
      const topSpecialIndex = new Map(topSpecialRanking.map((number, index) => [number, index]));
      const preferredEngine = String(result?.metaPreferredEngine || "").trim().toLowerCase();
      return tickets.map((ticket, index) => {
        const main = Array.isArray(ticket?.main) ? ticket.main.map(Number).filter(Number.isInteger) : [];
        const sourceLabel = getPredictVipTicketSourceLabel(result, index);
        const sourceKey = sourceLabel === "Luận Số" ? "luan_so" : "gen_local";
        const topCoverage = main.reduce((sum, number) => sum + (topMainIndex.has(number) ? 1 : 0), 0);
        const topWeight = main.reduce((sum, number) => {
          if (!topMainIndex.has(number)) return sum;
          return sum + Math.max(1, topRanking.length - topMainIndex.get(number));
        }, 0);
        const specialWeight = Number.isInteger(ticket?.special) && topSpecialIndex.has(Number(ticket.special))
          ? Math.max(1, topSpecialRanking.length - topSpecialIndex.get(Number(ticket.special)))
          : 0;
        const sourceBonus = preferredEngine && preferredEngine === sourceKey ? 6 : 0;
        const score = topWeight + (topCoverage * 4) + (specialWeight * 3) + sourceBonus;
        return {
          ticket,
          index,
          label: formatPredictVipTicketLabel(type, ticket, index),
          sourceLabel,
          sourceKey,
          topCoverage,
          score,
        };
      }).sort((a, b) => {
        if (b.score !== a.score) return b.score - a.score;
        if (b.topCoverage !== a.topCoverage) return b.topCoverage - a.topCoverage;
        return a.index - b.index;
      });
    }

    function getPredictVipHedgePair(analyses) {
      const primary = analyses[0] || null;
      if (!primary) return { primary: null, risky: null };
      const primarySet = new Set(Array.isArray(primary.ticket?.main) ? primary.ticket.main.map(Number) : []);
      const risky = analyses.slice(1).map(item => {
        const main = Array.isArray(item.ticket?.main) ? item.ticket.main.map(Number) : [];
        const overlap = main.reduce((sum, number) => sum + (primarySet.has(number) ? 1 : 0), 0);
        const diversity = Math.max(0, main.length - overlap);
        const hedgeScore = (item.score * 0.68) + (diversity * 5) + (item.sourceKey !== primary.sourceKey ? 2 : 0);
        return { ...item, hedgeScore };
      }).sort((a, b) => {
        if (b.hedgeScore !== a.hedgeScore) return b.hedgeScore - a.hedgeScore;
        return b.score - a.score;
      })[0] || null;
      return { primary, risky };
    }

    function renderPredictVipTicketCard(item, type, title) {
      if (!item) return "";
      return `
        <article class="predict-vip-card-item">
          <div class="predict-vip-card-head">
            <div class="predict-vip-card-title">${escapeHtml(title || item.label || `Bộ ${item.index + 1}`)}</div>
            <div class="predict-vip-card-source">${escapeHtml(item.sourceLabel || "AI")}</div>
          </div>
          ${renderPredictVipTicketNumbers(item.ticket, type)}
          <div class="predict-vip-note">${escapeHtml(`${item.label} • Độ phủ top ${item.topCoverage}/${Array.isArray(item.ticket?.main) ? item.ticket.main.length : 0}`)}</div>
        </article>
      `;
    }

    function formatPredictVipOutput(result = vipPredictLastDisplayResult) {
      const type = String(result?.type || "").trim().toUpperCase();
      if (!result || !AI_PREDICT_TYPES.has(type)) {
        return "Chưa có kết quả dự đoán VIP.";
      }
      return formatAiPredictionText(result);
    }

    function renderPredictVipOutput(result = vipPredictLastDisplayResult) {
      const out = document.getElementById("predictVipOut");
      if (!out) return;
      vipPredictLastDisplayResult = result || vipPredictLastDisplayResult || null;
      const hasResult = !!vipPredictLastDisplayResult;
      out.classList.toggle("muted", !hasResult);
      out.innerHTML = formatPredictVipOutput(vipPredictLastDisplayResult);
    }

    function escapeHtml(value) {
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    function formatLiveKy(ky) {
      const digits = String(ky || "").replace(/\D/g, "");
      return digits ? `#${digits}` : "";
    }

    function parseLiveDate(value) {
      const text = String(value || "").trim();
      const match = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
      if (!match) return null;
      const day = Number(match[1]);
      const month = Number(match[2]);
      const year = Number(match[3]);
      const parsed = new Date(year, month - 1, day);
      if (
        !Number.isFinite(day) ||
        !Number.isFinite(month) ||
        !Number.isFinite(year) ||
        parsed.getFullYear() !== year ||
        parsed.getMonth() !== month - 1 ||
        parsed.getDate() !== day
      ) {
        return null;
      }
      return parsed;
    }

    function formatLiveWeekday(dateText) {
      const parsed = parseLiveDate(dateText);
      if (!parsed) return "";
      const day = parsed.getDay();
      return day === 0 ? "Chủ nhật" : `Thứ ${day + 1}`;
    }

    function formatLiveWeekdayFromDate(dateValue) {
      if (!(dateValue instanceof Date) || Number.isNaN(dateValue.getTime())) return "";
      const day = dateValue.getDay();
      return day === 0 ? "Chủ nhật" : `Thứ ${day + 1}`;
    }

    function formatLiveWeekdayShortFromDate(dateValue) {
      if (!(dateValue instanceof Date) || Number.isNaN(dateValue.getTime())) return "";
      const day = dateValue.getDay();
      return day === 0 ? "CN" : `T${day + 1}`;
    }

    function formatLiveDateFromDate(dateValue) {
      if (!(dateValue instanceof Date) || Number.isNaN(dateValue.getTime())) return "";
      const day = String(dateValue.getDate()).padStart(2, "0");
      const month = String(dateValue.getMonth() + 1).padStart(2, "0");
      const year = dateValue.getFullYear();
      return `${day}/${month}/${year}`;
    }

    function formatLiveDateShortFromDate(dateValue) {
      if (!(dateValue instanceof Date) || Number.isNaN(dateValue.getTime())) return "";
      const day = String(dateValue.getDate()).padStart(2, "0");
      const month = String(dateValue.getMonth() + 1).padStart(2, "0");
      return `${day}/${month}`;
    }

    function parseScheduleTimeToMinutes(value) {
      const match = String(value || "").trim().match(/^(\d{1,2}):(\d{2})$/);
      if (!match) return null;
      const hours = Number(match[1]);
      const minutes = Number(match[2]);
      if (!Number.isFinite(hours) || !Number.isFinite(minutes) || hours < 0 || hours > 23 || minutes < 0 || minutes > 59) {
        return null;
      }
      return hours * 60 + minutes;
    }

    function buildScheduleDate(baseDate, minutesFromMidnight) {
      if (!(baseDate instanceof Date) || Number.isNaN(baseDate.getTime()) || !Number.isFinite(minutesFromMidnight)) return null;
      const candidate = new Date(baseDate.getFullYear(), baseDate.getMonth(), baseDate.getDate(), 0, 0, 0, 0);
      candidate.setMinutes(minutesFromMidnight);
      return candidate;
    }

    function formatDrawCountdown(totalMs) {
      const safeMs = Math.max(0, Number(totalMs || 0));
      const totalSeconds = Math.floor(safeMs / 1000);
      const hours = Math.floor(totalSeconds / 3600);
      const minutes = Math.floor((totalSeconds % 3600) / 60);
      const seconds = totalSeconds % 60;
      return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    }

    function computeNextLiveKy(ky) {
      const digits = String(ky || "").replace(/\D/g, "");
      if (!digits) return "";
      const nextValue = Number(digits) + 1;
      if (!Number.isFinite(nextValue) || nextValue <= 0) return "";
      return formatLiveKy(String(nextValue));
    }

    function findNextLiveDrawDate(type, nowValue = getSyncedNowDate()) {
      const schedule = LIVE_DRAW_SCHEDULES[String(type || "").trim().toUpperCase()];
      const now = nowValue instanceof Date ? new Date(nowValue.getTime()) : getSyncedNowDate();
      if (!schedule || Number.isNaN(now.getTime())) return null;

      if (schedule.kind === "interval") {
        for (let offset = 0; offset <= 7; offset += 1) {
          const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset, 0, 0, 0, 0);
          for (let minutes = schedule.startMinutes; minutes <= schedule.endMinutes; minutes += schedule.stepMinutes) {
            const candidate = buildScheduleDate(day, minutes);
            if (candidate && candidate.getTime() > now.getTime()) return candidate;
          }
        }
        return null;
      }

      if (schedule.kind === "daily") {
        const slots = (schedule.slots || [])
          .map(parseScheduleTimeToMinutes)
          .filter(value => Number.isFinite(value))
          .sort((a, b) => a - b);
        for (let offset = 0; offset <= 2; offset += 1) {
          const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset, 0, 0, 0, 0);
          for (const minutes of slots) {
            const candidate = buildScheduleDate(day, minutes);
            if (candidate && candidate.getTime() > now.getTime()) return candidate;
          }
        }
        return null;
      }

      if (schedule.kind === "weekly") {
        const timeMinutes = parseScheduleTimeToMinutes(schedule.time);
        if (!Number.isFinite(timeMinutes)) return null;
        for (let offset = 0; offset <= 14; offset += 1) {
          const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset, 0, 0, 0, 0);
          if (!Array.isArray(schedule.weekdays) || !schedule.weekdays.includes(day.getDay())) continue;
          const candidate = buildScheduleDate(day, timeMinutes);
          if (candidate && candidate.getTime() > now.getTime()) return candidate;
        }
      }

      return null;
    }

    function buildUpcomingLiveMetaParts(type, item = null, nowValue = getSyncedNowDate()) {
      const nextDrawDate = findNextLiveDrawDate(type, nowValue);
      if (!nextDrawDate) return buildLiveCardMetaParts(item?.ky, item?.date, item?.time);
      const nextKyText = computeNextLiveKy(item?.ky);
      const parts = [];
      if (nextKyText) parts.push(`Kỳ ${nextKyText}`);
      const dayDateText = [
        formatLiveWeekdayShortFromDate(nextDrawDate),
        formatLiveDateShortFromDate(nextDrawDate)
      ].filter(Boolean).join(" ");
      if (dayDateText) parts.push(dayDateText);
      const timeText = `${String(nextDrawDate.getHours()).padStart(2, "0")}:${String(nextDrawDate.getMinutes()).padStart(2, "0")}`;
      if (timeText) parts.push(timeText);
      parts.push(formatDrawCountdown(nextDrawDate.getTime() - nowValue.getTime()));
      return parts.filter(Boolean);
    }

    function resolveLiveDrawDateTime(type, dateText, timeText) {
      const parsedDate = parseLiveDate(dateText);
      if (!parsedDate) return null;
      const parsedMinutes = parseScheduleTimeToMinutes(timeText);
      if (Number.isFinite(parsedMinutes)) return buildScheduleDate(parsedDate, parsedMinutes);
      const schedule = LIVE_DRAW_SCHEDULES[String(type || "").trim().toUpperCase()];
      if (!schedule) return parsedDate;
      if (schedule.kind === "weekly") {
        const fixedMinutes = parseScheduleTimeToMinutes(schedule.time);
        if (Number.isFinite(fixedMinutes)) return buildScheduleDate(parsedDate, fixedMinutes);
      }
      return parsedDate;
    }

    function getNthUpcomingDrawDate(type, baseDate, stepCount = 1) {
      let cursor = baseDate instanceof Date ? new Date(baseDate.getTime()) : getSyncedNowDate();
      let candidate = null;
      const safeSteps = Math.max(1, Number(stepCount || 1));
      for (let index = 0; index < safeSteps; index += 1) {
        candidate = findNextLiveDrawDate(type, new Date(cursor.getTime() + 1000));
        if (!candidate) return null;
        cursor = candidate;
      }
      return candidate;
    }

    function buildPredictionHistoryCountdownState(entry, nowValue = getSyncedNowDate()) {
      if (!entry || entry.resolved || entry.resultMissingData) return null;
      const type = String(entry.type || "").trim().toUpperCase();
      if (!type || !LIVE_DRAW_SCHEDULES[type]) return null;
      const predictedKyText = formatLiveKy(entry.predictedKy);
      const liveItem = liveResultsState?.[type] || null;
      const latestKyValue = Number(String(liveItem?.ky || "").replace(/\D/g, "")) || 0;
      const targetKyValue = Number(String(entry.predictedKy || "").replace(/\D/g, "")) || 0;
      const latestDrawDate = resolveLiveDrawDateTime(type, liveItem?.date, liveItem?.time);
      const storedTargetDate = parsePredictionLogDate(entry.targetDrawAt);
      let targetDate = storedTargetDate;

      if (!targetDate && targetKyValue > 0 && latestKyValue > 0 && targetKyValue > latestKyValue && latestDrawDate) {
        targetDate = getNthUpcomingDrawDate(type, latestDrawDate, targetKyValue - latestKyValue);
      }

      if (!targetDate) {
        const createdDate = entry.createdAt ? new Date(entry.createdAt) : null;
        if (createdDate instanceof Date && !Number.isNaN(createdDate.getTime())) {
          targetDate = findNextLiveDrawDate(type, createdDate);
        }
      }

      if (!targetDate) {
        targetDate = findNextLiveDrawDate(type, nowValue);
      }

      if (!targetDate) return null;
      const remainingMs = targetDate.getTime() - nowValue.getTime();
      if (remainingMs <= 0) {
        return {
          kyText: predictedKyText || computeNextLiveKy(liveItem?.ky),
          countdownText: "Đang chờ KQ",
          waitingForResult: true,
        };
      }
      return {
        kyText: predictedKyText || computeNextLiveKy(liveItem?.ky),
        countdownText: formatDrawCountdown(remainingMs),
        waitingForResult: false,
      };
    }

    function buildLiveMetaParts(ky, dateText, timeText) {
      const parts = [];
      const kyText = formatLiveKy(ky);
      const weekdayText = formatLiveWeekday(dateText);
      if (kyText) parts.push(`Kỳ ${kyText}`);
      if (weekdayText) parts.push(weekdayText);
      if (dateText) parts.push(String(dateText).trim());
      if (timeText) parts.push(String(timeText).trim());
      return parts.filter(Boolean);
    }

    function buildLiveCardMetaParts(ky, dateText, timeText) {
      const parts = [];
      const kyText = formatLiveKy(ky);
      const parsedDate = parseLiveDate(dateText);
      if (kyText) parts.push(`Kỳ ${kyText}`);
      if (parsedDate) {
        parts.push(`${formatLiveWeekdayShortFromDate(parsedDate)} ${formatLiveDateShortFromDate(parsedDate)}`.trim());
      } else if (dateText) {
        parts.push(String(dateText).trim());
      }
      if (timeText) parts.push(String(timeText).trim());
      return parts.filter(Boolean);
    }

    function readLiveResultsCache() {
      return readJsonLocal(LIVE_RESULTS_CACHE_KEY, {});
    }

    function saveLiveResultsCache() {
      writeJsonLocal(LIVE_RESULTS_CACHE_KEY, {
        fetchedAt: liveResultsFetchedAt,
        results: liveResultsState
      });
    }

    function restoreLiveResultsCache() {
      const cached = readLiveResultsCache();
      liveResultsFetchedAt = String(cached?.fetchedAt || "");
      liveResultsState = cached?.results && typeof cached.results === "object" ? cached.results : {};
      startLiveDrawCountdown();
    }

    function normalizeLiveSyncTimingSamples(values) {
      if (!Array.isArray(values)) return [];
      return values
        .map(value => Math.round(Number(value || 0)))
        .filter(value => Number.isFinite(value) && value > 0)
        .slice(-5);
    }

    function readLiveSyncTimingCache() {
      const cached = readJsonLocal(LIVE_SYNC_TIMING_CACHE_KEY, {});
      return {
        manual_repair: normalizeLiveSyncTimingSamples(cached?.manual_repair),
        quick_live: normalizeLiveSyncTimingSamples(cached?.quick_live),
      };
    }

    function saveLiveSyncTimingCache(cache) {
      writeJsonLocal(LIVE_SYNC_TIMING_CACHE_KEY, {
        manual_repair: normalizeLiveSyncTimingSamples(cache?.manual_repair),
        quick_live: normalizeLiveSyncTimingSamples(cache?.quick_live),
      });
    }

    function getLiveSyncTimingBucket(repairCanonical) {
      return repairCanonical ? "manual_repair" : "quick_live";
    }

    function getLiveSyncFallbackSeconds(repairCanonical) {
      return repairCanonical ? 90 : 15;
    }

    function estimateLiveSyncSeconds(repairCanonical) {
      const bucket = getLiveSyncTimingBucket(repairCanonical);
      const samples = readLiveSyncTimingCache()[bucket] || [];
      if (!samples.length) return getLiveSyncFallbackSeconds(repairCanonical);
      const sorted = [...samples].sort((a, b) => a - b);
      const middle = Math.floor(sorted.length / 2);
      if (sorted.length % 2 === 1) return Math.max(1, sorted[middle]);
      return Math.max(1, Math.round((sorted[middle - 1] + sorted[middle]) / 2));
    }

    function rememberLiveSyncDuration(repairCanonical, durationMs) {
      const durationSeconds = Math.max(1, Math.round(Number(durationMs || 0) / 1000));
      if (!Number.isFinite(durationSeconds) || durationSeconds <= 0) return;
      const bucket = getLiveSyncTimingBucket(repairCanonical);
      const cache = readLiveSyncTimingCache();
      const samples = [...(cache[bucket] || []), durationSeconds].slice(-5);
      cache[bucket] = samples;
      saveLiveSyncTimingCache(cache);
    }

    function isLiveResultStored(item) {
      if (!item || !item.importable || !TYPES[item.key]) return false;
      const ky = formatLiveKy(item.ky);
      if (!ky) return false;
      const current = store.results[item.key]?.[ky];
      if (!current) return false;
      const currentMain = Array.isArray(current.main) ? [...current.main].sort((a, b) => a - b) : [];
      const nextMain = Array.isArray(item.main) ? [...item.main].map(Number).sort((a, b) => a - b) : [];
      const currentSpecial = current.special ?? null;
      const nextSpecial = Number.isInteger(Number(item.special)) ? Number(item.special) : null;
      return JSON.stringify(currentMain) === JSON.stringify(nextMain) && currentSpecial === nextSpecial;
    }

    function importLiveResult(item) {
      if (!item || !item.importable || !TYPES[item.key]) return false;
      const ky = formatLiveKy(item.ky);
      const main = Array.isArray(item.main) ? item.main.map(Number).filter(Number.isFinite).sort((a, b) => a - b) : [];
      if (!ky || !main.length) return false;
      const special = Number.isInteger(Number(item.special)) ? Number(item.special) : null;
      const current = store.results[item.key]?.[ky];
      if (current) {
        const currentMain = Array.isArray(current.main) ? [...current.main].sort((a, b) => a - b) : [];
        if (JSON.stringify(currentMain) === JSON.stringify(main) && (current.special ?? null) === special) {
          return false;
        }
      }
      putResult(item.key, ky, { main, special });
      return true;
    }

    function applyLiveResultsToStore(results) {
      const importedKeys = new Set();
      for (const item of (results || [])) {
        if (importLiveResult(item)) importedKeys.add(item.key);
      }
      return importedKeys;
    }

    function updateLiveAutoButton() {
      const btn = document.getElementById("liveAutoBtn");
      if (!btn) return;
      const running = !!liveAutoTimer;
      btn.textContent = running ? "Tắt tự động" : "Bật tự động";
      btn.classList.toggle("secondary", !running);
    }

    function renderLiveNumberToken(typeKey, rawValue, { special = false } = {}) {
      const number = Number(rawValue);
      const text = Number.isFinite(number) ? formatPredictNumber(number, typeKey) : String(rawValue || "").trim();
      const isThreeDigit = TYPES[typeKey]?.threeDigit;
      return `<span class="live-card-number${isThreeDigit ? " is-three-digit" : ""}${special ? " is-special" : ""}">${escapeHtml(text)}</span>`;
    }

    function renderLiveInlineResultLine(typeKey, lineText, index = 0) {
      const normalizedLineText = String(lineText || "")
        .replace(/ĐB|DB/giu, "")
        .replace(/\s{2,}/g, " ");
      const parts = normalizedLineText.split(/(\b\d{1,3}\b)/g);
      if (TYPES[typeKey]?.threeDigit) {
        const firstNumberIndex = parts.findIndex(part => /^\d{1,3}$/.test(part));
        if (firstNumberIndex >= 0) {
          const labelText = parts.slice(0, firstNumberIndex).join("").trim();
          const isSpecialPrize = /đặc\s*biệt/iu.test(labelText);
          const numbersHtml = parts.slice(firstNumberIndex).map(part => {
            if (/^\d{1,3}$/.test(part)) return renderLiveNumberToken(typeKey, part, { special: isSpecialPrize });
            const text = String(part || "").trim();
            return text ? `<span class="live-card-text-segment">${escapeHtml(text)}</span>` : "";
          }).join("");
          return `<div class="live-card-line ${index === 0 ? "primary" : ""}"><span class="live-card-text-segment live-card-prize-label">${escapeHtml(labelText)}</span><span class="live-card-number-group">${numbersHtml}</span></div>`;
        }
      }
      let afterSpecialDivider = false;
      const html = parts.map(part => {
        if (/^\d{1,3}$/.test(part)) {
          return renderLiveNumberToken(typeKey, part, {
            special: !!TYPES[typeKey]?.hasSpecial && afterSpecialDivider,
          });
        }
        if (TYPES[typeKey]?.hasSpecial && String(part || "").includes("|")) afterSpecialDivider = true;
        return `<span class="live-card-text-segment">${escapeHtml(part)}</span>`;
      }).join("");
      return `<div class="live-card-line ${index === 0 ? "primary" : ""}">${html}</div>`;
    }

    function renderLiveCardMainLines(typeKey, item) {
      if (typeKey === "KENO" && Array.isArray(item?.main) && item.main.length) {
        const sorted = [...item.main].map(Number).filter(Number.isFinite).sort((a, b) => a - b);
        const rows = [];
        for (let index = 0; index < sorted.length; index += 10) {
          rows.push(sorted.slice(index, index + 10));
        }
        return rows
          .filter(row => row.length)
          .map(row => `<div class="live-card-line primary keno-row">${row.map(value => renderLiveNumberToken(typeKey, value)).join("")}</div>`)
          .join("");
      }
      return (item?.displayLines || [])
        .map((lineText, index) => renderLiveInlineResultLine(typeKey, lineText, index))
        .join("");
    }

    function getLiveResultsBoardSignature() {
      return LIVE_RESULT_TYPES.map(meta => {
        const item = liveResultsState?.[meta.key];
        const badge = getLiveUpdateBadge(meta.key);
        return [
          meta.key,
          item ? getLiveResultSignature(item) : "",
          badge.code || "",
          badge.label || "",
          badge.message || "",
        ].join("~");
      }).join("|");
    }

    function updateLiveResultsCountdownText(nowValue = getSyncedNowDate()) {
      const host = document.getElementById("liveResultGrid");
      if (!host) return false;
      let updated = false;
      host.querySelectorAll("[data-live-countdown-type]").forEach(node => {
        const type = String(node.getAttribute("data-live-countdown-type") || "").trim().toUpperCase();
        if (!type) return;
        const nextText = buildUpcomingLiveMetaParts(type, liveResultsState?.[type] || null, nowValue).join(" • ");
        if (node.textContent !== nextText) {
          node.textContent = nextText;
          updated = true;
        }
      });
      return updated;
    }

    // ----- Giao diện live results và lịch sử CSV -----
    // Render bảng 6 loại vé, status Cập Nhật và nội dung Lịch Sử CSV theo canonical all_day.
    function renderLiveResultsBoard({ force = false, onlyType = "" } = {}) {
      const host = document.getElementById("liveResultGrid");
      if (!host) return;
      const scopedType = String(onlyType || "").trim().toUpperCase();
      const signature = getLiveResultsBoardSignature();
      const nowValue = getSyncedNowDate();
      if (!force && host.dataset.liveResultsSignature === signature && host.querySelector("[data-live-countdown-type]")) {
        updateLiveResultsCountdownText(nowValue);
        return;
      }
      host.dataset.liveResultsSignature = signature;
      const cardHtml = LIVE_RESULT_TYPES.map(meta => {
        const badge = getLiveUpdateBadge(meta.key);
        const badgeClass = `live-card-badge ${liveUpdateBadgeClass(badge.code)}`.trim();
        const badgeText = badge.label || "Chờ cập nhật";
        const isRefreshing = liveSingleRefreshBusy.has(meta.key);
        const refreshButton = `
          <button
            class="${badgeClass} live-card-refresh-btn${isRefreshing ? " is-refreshing" : ""}"
            type="button"
            data-live-refresh-type="${escapeHtml(meta.key)}"
            title="${escapeHtml(isRefreshing ? `Đang cập nhật ${meta.label}` : `Cập nhật riêng ${meta.label}`)}"
            aria-label="${escapeHtml(isRefreshing ? `Đang cập nhật ${meta.label}` : `Cập nhật riêng ${meta.label}`)}"
            ${isRefreshing ? "disabled" : ""}
          >
            <span class="live-card-badge-state">${escapeHtml(badgeText)}</span>
            <span class="live-card-badge-action">${isRefreshing ? "Đang cập nhật" : "Cập nhật"}</span>
          </button>
        `;
        const cardClass = `live-card${TYPES[meta.key]?.threeDigit ? " is-three-digit" : ""}`;
        const item = liveResultsState?.[meta.key];
        if (!item) {
          const pendingMetaParts = buildUpcomingLiveMetaParts(meta.key, null, nowValue);
          return `
            <article class="${cardClass} pending" data-live-type="${escapeHtml(meta.key)}">
              <div class="live-card-top">
                <div class="live-card-info-row">
                  <span class="live-card-chip">Live</span>
                  <h3 class="live-card-title">${escapeHtml(meta.label)}</h3>
                  ${pendingMetaParts.length ? `<div class="live-card-meta" data-live-countdown-type="${escapeHtml(meta.key)}">${escapeHtml(pendingMetaParts.join(" • "))}</div>` : ""}
                </div>
                ${refreshButton}
              </div>
              <div class="live-card-empty">Chưa có kết quả live cho loại này.</div>
            </article>
          `;
        }
        const metaParts = buildUpcomingLiveMetaParts(meta.key, item, nowValue);
        const lines = renderLiveCardMainLines(meta.key, item);
        let sourceHost = "";
        try {
          sourceHost = item.sourceUrl ? new URL(item.sourceUrl).hostname : "";
        } catch {
          sourceHost = "";
        }
        const footParts = [item.sourceDate ? `Nguồn ngày ${item.sourceDate}` : "", sourceHost].filter(Boolean);
        return `
          <article class="${cardClass}" data-live-type="${meta.key}">
            <div class="live-card-top">
              <div class="live-card-info-row">
                <span class="live-card-chip">Live</span>
                <h3 class="live-card-title">${escapeHtml(meta.label)}</h3>
                <div class="live-card-meta" data-live-countdown-type="${escapeHtml(meta.key)}">${escapeHtml(metaParts.join(" • "))}</div>
              </div>
              ${refreshButton}
            </div>
            <div class="live-card-main">${lines}</div>
            <div class="live-card-foot">${escapeHtml(footParts.join(" • "))}</div>
          </article>
        `;
      });
      if (scopedType) {
        const scopedIndex = LIVE_RESULT_TYPES.findIndex(meta => meta.key === scopedType);
        const currentCard = host.querySelector(`[data-live-type="${scopedType}"]`);
        if (scopedIndex >= 0 && currentCard) {
          currentCard.outerHTML = cardHtml[scopedIndex];
          return;
        }
      }
      host.innerHTML = cardHtml.join("");
    }

    function setLiveStatus(message, cls = "") {
      const el = document.getElementById("liveSyncStatus");
      if (!el) return;
      line(el, message, cls);
    }

    let liveSyncCountdownTimer = null;
    let liveResultsProgressPollTimer = null;
    let liveResultsProgressSeenRunning = false;
    var liveDrawCountdownTimer = null;

    // ---abc--- Live Results / Countdown ---
    function startLiveDrawCountdown() {
      if (liveDrawCountdownTimer) return;
      liveDrawCountdownTimer = window.setInterval(() => {
        if (document.hidden) return;
        maybeSyncServerTimeSoon();
        const liveBoardVisible = isHomePageVisible() && isElementNearViewport(document.getElementById("liveBoardSection"));
        if (liveBoardVisible && !updateLiveResultsCountdownText()) renderLiveResultsBoard();
        if (predictionHistoryPanelOpen || vipPredictionHistoryPanelOpen) updatePredictionHistoryCountdowns();
      }, 1000);
    }

    function formatCountdownSeconds(totalSeconds) {
      const safeSeconds = Math.max(0, Number(totalSeconds || 0));
      const minutes = Math.floor(safeSeconds / 60);
      const seconds = safeSeconds % 60;
      return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    }

    function stopLiveSyncCountdown() {
      if (liveSyncCountdownTimer) {
        clearInterval(liveSyncCountdownTimer);
        liveSyncCountdownTimer = null;
      }
    }

    function startLiveSyncCountdown({ repairCanonical = false, estimatedSeconds = null, note = "" } = {}) {
      stopLiveSyncCountdown();
      const numericEstimate = Number(estimatedSeconds);
      let remainingSeconds = Math.max(
        1,
        Math.round(Number.isFinite(numericEstimate) && numericEstimate > 0
          ? numericEstimate
          : getLiveSyncFallbackSeconds(repairCanonical))
      );
      let waitingForFinish = false;
      const prefix = repairCanonical ? "Đang cập nhật 6 loại từ MinhChinh" : "Đang cập nhật 6 loại";
      const noteSuffix = note ? `\n${note}` : "";
      setLiveStatus(`${prefix} • Ước tính còn ${formatCountdownSeconds(remainingSeconds)}.${noteSuffix}`, "muted");
      liveSyncCountdownTimer = setInterval(() => {
        if (remainingSeconds > 0) {
          remainingSeconds = Math.max(0, remainingSeconds - 1);
          setLiveStatus(`${prefix} • Ước tính còn ${formatCountdownSeconds(remainingSeconds)}.${noteSuffix}`, "muted");
          return;
        }
        if (!waitingForFinish) {
          waitingForFinish = true;
          setLiveStatus(`${prefix} • Đang hoàn tất xử lý, vui lòng chờ thêm...${noteSuffix}`, "muted");
          return;
        }
        stopLiveSyncCountdown();
      }, 1000);
    }

    function getLiveResultsCompatibilityFallbackNote() {
      return "Đang dùng chế độ tương thích do phiên cũ chưa hỗ trợ cập nhật nền.";
    }

    function isLiveResultsCompatibilityError(err, { allowNotFound = false } = {}) {
      const status = Number(err?.status || 0);
      if (status === 405) return true;
      if (allowNotFound && status === 404) return true;
      const message = String(err?.message || "").trim().toLowerCase();
      if (message.includes("method not allowed")) return true;
      if (allowNotFound && message.includes("not found")) return true;
      return false;
    }

    function stopLiveResultsProgressPolling(resetButton = true) {
      if (liveResultsProgressPollTimer) {
        clearInterval(liveResultsProgressPollTimer);
        liveResultsProgressPollTimer = null;
      }
      liveResultsProgressSeenRunning = false;
      if (resetButton && typeof liveResultsProgressButtonReset === "function") {
        liveResultsProgressButtonReset();
      }
      if (resetButton) {
        liveResultsProgressButtonReset = null;
      }
    }

    function setLiveSyncButtonBusy(isBusy, originalText = "Cập Nhật") {
      const liveSyncBtn = document.getElementById("liveSyncBtn");
      if (!liveSyncBtn) return;
      if (isBusy) {
        liveSyncBtn.disabled = true;
        liveSyncBtn.textContent = "Đang Cập Nhật...";
        liveResultsProgressButtonReset = () => {
          const button = document.getElementById("liveSyncBtn");
          if (!button) return;
          button.disabled = false;
          button.textContent = originalText;
        };
        return;
      }
      liveSyncBtn.disabled = false;
      liveSyncBtn.textContent = originalText;
      liveResultsProgressButtonReset = null;
    }

    function getLiveResultsProgressStatus(progress, { repairCanonical = false } = {}) {
      const prefix = repairCanonical ? "Đang cập nhật 6 loại từ MinhChinh" : "Đang cập nhật 6 loại";
      const warnings = Array.isArray(progress?.warnings) ? progress.warnings.filter(Boolean) : [];
      const errors = Array.isArray(progress?.errors) ? progress.errors.filter(Boolean) : [];
      if (progress?.running) {
        const etaSeconds = Number(progress?.etaSeconds);
        if (Number.isFinite(etaSeconds) && etaSeconds > 0) {
          return { message: `${prefix} • Ước tính còn ${formatCountdownSeconds(etaSeconds)}.`, cls: "muted" };
        }
        if (Number(progress?.completedSteps || 0) > 0) {
          return { message: `${prefix} • Đang hoàn tất xử lý, vui lòng chờ thêm...`, cls: "muted" };
        }
        return { message: `${prefix} • Đang tính thời gian còn lại...`, cls: "muted" };
      }
      if (errors.length) return { message: errors.join(" | "), cls: "warn" };
      if (warnings.length) return { message: warnings.join(" | "), cls: "warn" };
      if (progress?.done) {
        return { message: repairCanonical ? "Hoàn Tất Cập Nhật." : "Đã Cập Nhật", cls: "ok" };
      }
      return { message: `${prefix} • Đang tính thời gian còn lại...`, cls: "muted" };
    }

    function mergeLiveResultIntoState(item) {
      const key = String(item?.key || "").trim().toUpperCase();
      if (!key || !TYPES[key]) return false;
      const previous = liveResultsState?.[key];
      const nextItem = { ...item };
      const samePayload = !!previous && getLiveResultSignature(previous) === getLiveResultSignature(nextItem);
      liveResultsState = {
        ...(liveResultsState && typeof liveResultsState === "object" ? liveResultsState : {}),
        [key]: nextItem,
      };
      const imported = applyLiveResultsToStore([nextItem]);
      nextItem.imported = imported.has(key) || isLiveResultStored(nextItem);
      if (!samePayload || imported.has(key)) {
        liveResultsFetchedAt = getSyncedIsoString();
        saveLiveResultsCache();
        startLiveDrawCountdown();
        renderLiveResultsBoard();
      }
      return !samePayload || imported.has(key);
    }

    async function refreshLiveHistoryForProgressType(type, updatedAt) {
      if (!type || liveResultsProgressHistoryRefreshBusy) return;
      const currentType = document.getElementById("liveHistoryType")?.value || "";
      if (String(currentType || "").toUpperCase() !== String(type || "").toUpperCase()) return;
      const refreshKey = `${type}:${updatedAt || ""}`;
      if (liveResultsProgressHistoryRefreshCursor[type] === refreshKey) return;
      liveResultsProgressHistoryRefreshCursor[type] = refreshKey;
      liveResultsProgressHistoryRefreshBusy = true;
      try {
        await refreshCurrentLiveHistory({ force: true, silent: true });
      } catch {
      } finally {
        liveResultsProgressHistoryRefreshBusy = false;
      }
    }

    async function applyLiveResultsProgressSnapshot(progress) {
      const typeStates = progress?.typeStates && typeof progress.typeStates === "object"
        ? progress.typeStates
        : {};
      let changed = false;
      let badgeChanged = false;
      for (const [type, state] of Object.entries(typeStates)) {
        if (!state || typeof state !== "object") continue;
        badgeChanged = applyLiveUpdateBadgeFromProgressState(type, state, { render: false }) || badgeChanged;
        const updatedAt = String(state.updatedAt || "");
        const cursorKey = String(type || "").toUpperCase();
        if (!updatedAt || liveResultsProgressTypeCursor[cursorKey] === updatedAt) continue;
        liveResultsProgressTypeCursor[cursorKey] = updatedAt;
        if (state.liveResult && typeof state.liveResult === "object") {
          changed = mergeLiveResultIntoState(state.liveResult) || changed;
        }
        await refreshLiveHistoryForProgressType(cursorKey, updatedAt);
      }
      if (changed || badgeChanged) {
        if (badgeChanged && !changed) renderLiveResultsBoard();
        renderLiveHistoryOutput();
      }
    }

    function applyLiveResultsApiResponse(res, { repairCanonical = false, requestStartedAtMs = Date.now(), requestedType = "" } = {}) {
      const scopedType = String(requestedType || "").trim().toUpperCase();
      const durationMs = Number.isFinite(Number(res.durationMs))
        ? Number(res.durationMs)
        : Math.max(1, Date.now() - requestStartedAtMs);
      if (!scopedType) rememberLiveSyncDuration(repairCanonical, durationMs);
      const resultMap = {};
      for (const item of (res.results || [])) {
        resultMap[item.key] = item;
      }
      liveResultsState = scopedType ? { ...liveResultsState, ...resultMap } : resultMap;
      liveResultsFetchedAt = String(res.fetchedAt || "");
      const importedKeys = applyLiveResultsToStore(res.results || []);
      Object.values(scopedType ? resultMap : liveResultsState).forEach(item => {
        item.imported = importedKeys.has(item.key) || isLiveResultStored(item);
      });
      saveLiveResultsCache();
      startLiveDrawCountdown();
      if (repairCanonical) {
        applyManualLiveUpdateBadgesFromApiResponse(res, { render: false });
      } else if (scopedType) {
        const scopedErrors = [
          ...(Array.isArray(res.errors) ? res.errors : []),
          ...(Array.isArray(res.canonicalBackfill?.errors) ? res.canonicalBackfill.errors : []),
        ].filter(error => String(error?.key || error?.type || "").trim().toUpperCase() === scopedType);
        const errorMessage = scopedErrors.map(error => String(error?.message || "").trim()).filter(Boolean).join(" | ");
        setLiveUpdateBadge(
          scopedType,
          buildManualLiveUpdateBadge(scopedType, {
            hasError: !resultMap[scopedType] || scopedErrors.length > 0,
            errorMessage: errorMessage || (!resultMap[scopedType] ? "Không nhận được kết quả mới." : ""),
          }),
          { render: false }
        );
      }
      renderLiveResultsBoard({ force: !!scopedType, onlyType: scopedType });
      renderHeaderNotifications();

      const statusParts = [];
      if ((res.errors || []).length) {
        const errorText = res.errors.map(err => {
          if (String(err.key || "").toUpperCase() === "KENO" && String(err.message || "").trim() === "Hoạt động từ 6:00 đến 22:00") {
            return "KENO : Hoạt động từ 6:00 đến 22:00";
          }
          return `${err.key}: ${err.message}`;
        }).join(" | ");
        statusParts.push(errorText);
      }
      const canonicalBackfillErrors = Array.isArray(res.canonicalBackfill?.errors) ? res.canonicalBackfill.errors : [];
      if (canonicalBackfillErrors.length) {
        const backfillErrorText = canonicalBackfillErrors
          .map(err => `${err.type}${err.date ? ` ${err.date}` : ""}: ${err.message}`)
          .join(" | ");
        if (backfillErrorText) statusParts.push(`Lỗi khi bù all_day.csv: ${backfillErrorText}`);
      }
      if (!statusParts.length) {
        statusParts.push(scopedType ? `Đã cập nhật riêng ${TYPES[scopedType]?.label || scopedType}.` : (repairCanonical ? "Hoàn Tất Cập Nhật." : "Đã Cập Nhật"));
      }
      setLiveStatus(statusParts.join("\n"), ((res.errors || []).length || canonicalBackfillErrors.length) ? "warn" : "ok");
      if (!scopedType) {
        refreshStatsV2AfterLiveUpdate();
        refreshAnalysisAfterLiveUpdate();
      }
    }

    async function syncSingleLiveResult(rawType) {
      const type = String(rawType || "").trim().toUpperCase();
      const meta = LIVE_RESULT_TYPES.find(item => item.key === type);
      if (!meta || liveSingleRefreshBusy.has(type)) return;
      if (IS_LOCAL_MODE) {
        setLiveStatus("Cập nhật riêng chỉ hoạt động khi mở trang qua http://localhost:8080.", "warn");
        return;
      }
      liveSingleRefreshBusy.add(type);
      setLiveUpdateBadge(type, {
        type,
        code: "running",
        label: "Đang cập nhật",
        message: `Đang cập nhật riêng ${meta.label}.`,
        updatedAt: getSyncedIsoString(),
      }, { render: false });
      renderLiveResultsBoard({ force: true, onlyType: type });
      setLiveStatus(`Đang cập nhật riêng ${meta.label}...`, "muted");
      try {
        const requestStartedAtMs = Date.now();
        const res = await api(`/api/live-results?type=${encodeURIComponent(type)}`);
        applyLiveResultsApiResponse(res, { requestedType: type, requestStartedAtMs });
      } catch (err) {
        setLiveUpdateBadge(type, buildManualLiveUpdateBadge(type, {
          hasError: true,
          errorMessage: String(err?.message || err || "Cập nhật thất bại"),
        }), { render: false });
        setLiveStatus(`Không thể cập nhật riêng ${meta.label}: ${err?.message || err}`, "warn");
      } finally {
        liveSingleRefreshBusy.delete(type);
        renderLiveResultsBoard({ force: true, onlyType: type });
      }
    }

    async function runLegacyRepairCanonicalSync({ silent = false, manageButton = false, originalButtonText = "Cập Nhật" } = {}) {
      const requestStartedAtMs = Date.now();
      const compatibilityNote = getLiveResultsCompatibilityFallbackNote();
      if (!silent) {
        if (manageButton) setLiveSyncButtonBusy(true, originalButtonText);
        startLiveSyncCountdown({
          repairCanonical: true,
          estimatedSeconds: estimateLiveSyncSeconds(true),
          note: compatibilityNote,
        });
      }
      try {
        const res = await api("/api/live-results?repair=1");
        applyLiveResultsApiResponse(res, { repairCanonical: true, requestStartedAtMs });
        return res;
      } catch (err) {
        markAllLiveUpdateBadgesFailed(err?.message || "Cập nhật thất bại", { render: true });
        setLiveStatus(`Không thể cập nhật live và bù all_day.csv: ${err.message}`, "warn");
        throw err;
      } finally {
        stopLiveSyncCountdown();
        if (!silent && manageButton) {
          setLiveSyncButtonBusy(false, originalButtonText);
        }
      }
    }

    async function pollLiveResultsProgress({ repairCanonical = false } = {}) {
      try {
        const progress = await api("/api/live-results-progress");
        await applyLiveResultsProgressSnapshot(progress);
        if (progress?.running) {
          liveResultsProgressSeenRunning = true;
        }
        if (!liveResultsProgressSeenRunning && !progress?.running) {
          const prefix = repairCanonical ? "Đang cập nhật 6 loại từ MinhChinh" : "Đang cập nhật 6 loại";
          setLiveStatus(`${prefix} • Đang tính thời gian còn lại...`, "muted");
          return;
        }
        const status = getLiveResultsProgressStatus(progress, { repairCanonical });
        setLiveStatus(status.message, status.cls);
        if (!progress?.running && progress?.done) {
          refreshStatsV2AfterLiveUpdate();
          refreshAnalysisAfterLiveUpdate();
          stopLiveResultsProgressPolling();
        }
      } catch (err) {
        if (repairCanonical && !liveResultsLegacyFallbackRunning && isLiveResultsCompatibilityError(err, { allowNotFound: true })) {
          liveResultsLegacyFallbackRunning = true;
          stopLiveResultsProgressPolling(false);
          try {
            await runLegacyRepairCanonicalSync({ silent: false, manageButton: true });
          } catch {
          } finally {
            liveResultsLegacyFallbackRunning = false;
          }
        }
      }
    }

    function startLiveResultsProgressPolling({ repairCanonical = false, initialProgress = null } = {}) {
      stopLiveResultsProgressPolling(false);
      liveResultsProgressTypeCursor = {};
      if (initialProgress) {
        void applyLiveResultsProgressSnapshot(initialProgress);
      }
      if (initialProgress) {
        if (initialProgress?.running) {
          liveResultsProgressSeenRunning = true;
        }
        const status = getLiveResultsProgressStatus(initialProgress, { repairCanonical });
        setLiveStatus(status.message, status.cls);
      } else {
        const prefix = repairCanonical ? "Đang cập nhật 6 loại từ MinhChinh" : "Đang cập nhật 6 loại";
        setLiveStatus(`${prefix} • Đang tính thời gian còn lại...`, "muted");
      }
      pollLiveResultsProgress({ repairCanonical });
      liveResultsProgressPollTimer = setInterval(() => {
        pollLiveResultsProgress({ repairCanonical });
      }, 1000);
    }

    function formatLiveSyncCount(value) {
      const numeric = Math.max(0, Number(value || 0));
      return numeric.toLocaleString("vi-VN");
    }

    async function syncLiveResults({ silent = false, repairCanonical = false } = {}) {
      const liveSyncBtn = document.getElementById("liveSyncBtn");
      const originalButtonText = liveSyncBtn ? String(liveSyncBtn.textContent || "Cập Nhật") : "";
      const requestStartedAtMs = Date.now();
      let keepProgressPolling = false;
      if (IS_LOCAL_MODE) {
        renderLiveResultsBoard();
        if (!silent) {
          setLiveStatus("Đồng bộ live chỉ hoạt động khi mở trang qua http://localhost:8080 để server gọi Python scraper.", "warn");
        }
        return;
      }

      if (!silent) {
        if (repairCanonical) setLiveSyncButtonBusy(true, originalButtonText);
        else if (liveSyncBtn) {
          liveSyncBtn.disabled = true;
          liveSyncBtn.textContent = "Đang cập nhật...";
        }
        if (repairCanonical) {
          resetLiveUpdateBadgesForManualRun({ render: true });
          setLiveStatus("Đang cập nhật 6 loại từ MinhChinh • Đang tính thời gian còn lại...", "muted");
        } else {
          startLiveSyncCountdown({ repairCanonical, estimatedSeconds: estimateLiveSyncSeconds(repairCanonical) });
        }
      }
      try {
        if (repairCanonical) {
          try {
            const res = await api("/api/live-results-start", "POST");
            startLiveResultsProgressPolling({ repairCanonical: true, initialProgress: res.progress || null });
            keepProgressPolling = true;
            return;
          } catch (startErr) {
            if (isLiveResultsCompatibilityError(startErr, { allowNotFound: true })) {
              await runLegacyRepairCanonicalSync({ silent });
              return;
            }
            throw startErr;
          }
        }
        const res = await api("/api/live-results");
        applyLiveResultsApiResponse(res, { repairCanonical, requestStartedAtMs });
      } catch (err) {
        if (repairCanonical && Number(err?.status || 0) === 409) {
          const progress = err?.payload?.progress;
          startLiveResultsProgressPolling({ repairCanonical: true, initialProgress: progress });
          keepProgressPolling = true;
          return;
        }
        if (repairCanonical) {
          markAllLiveUpdateBadgesFailed(err?.message || "Cập nhật thất bại", { render: true });
        } else {
          renderLiveResultsBoard();
        }
        setLiveStatus(
          repairCanonical
            ? `Không thể cập nhật live và bù all_day.csv: ${err.message}`
            : `Không thể đồng bộ live: ${err.message}`,
          "warn"
        );
      } finally {
        stopLiveSyncCountdown();
        if (repairCanonical && !keepProgressPolling) {
          stopLiveResultsProgressPolling();
        }
        if (!silent && liveSyncBtn && !keepProgressPolling) {
          liveSyncBtn.disabled = false;
          liveSyncBtn.textContent = originalButtonText;
        }
      }
    }

    function startLiveAutoSync() {
      const seconds = Number(document.getElementById("liveSyncInterval")?.value || 120);
      const delay = Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : 120000;
      if (liveAutoTimer) clearInterval(liveAutoTimer);
      liveAutoTimer = setInterval(() => {
        if (document.hidden) return;
        syncLiveResults({ silent: true });
      }, delay);
      updateLiveAutoButton();
    }

    function stopLiveAutoSync() {
      if (liveAutoTimer) clearInterval(liveAutoTimer);
      liveAutoTimer = null;
      updateLiveAutoButton();
    }

    function buildPredictionResultDataset(type) {
      const baseResults = store.results[type] || {};
      const baseOrder = store.resultOrder[type] || [];
      if (type !== "KENO") {
        return buildMergedResultDataset(type);
      }

      const canonicalFeed = getLiveHistoryFeed("KENO");
      const mergedResults = {};
      const mergeFromStore = (ky, draw) => {
        const key = String(ky || "").replace(/\D/g, "");
        const cloned = cloneDraw(draw);
        if (!key || !cloned) return;
        mergedResults[key] = cloned;
      };

      for (const ky of baseOrder) mergeFromStore(ky, baseResults[ky]);
      for (const ky of (kenoCsvFeed.order || [])) mergeFromStore(ky, kenoCsvFeed.results[ky]);
      for (const ky of (canonicalFeed.order || [])) mergeFromStore(ky, canonicalFeed.results?.[ky]);

      const order = Object.keys(mergedResults).sort((a, b) => kySortValue(a) - kySortValue(b));
      const parts = [];
      if (canonicalFeed.order.length) parts.push(`canonical ${canonicalFeed.order.length} kỳ`);
      if (baseOrder.length) parts.push(`trong trang ${baseOrder.length} kỳ`);
      if (kenoCsvFeed.order.length) parts.push(`CSV ${kenoCsvFeed.order.length} kỳ`);
      return {
        results: mergedResults,
        order,
        sourceText: parts.length
          ? `Nguồn Keno đã gộp: ${parts.join(" + ")}. Tổng dùng để dự đoán: ${order.length} kỳ`
          : "Chưa có dữ liệu Keno"
      };
    }

    async function mergeKenoCsvTexts(items) {
      const next = cloneKenoCsvFeed();
      let validRows = 0;
      let skippedRows = 0;
      const loadedSources = [];

      for (const item of items) {
        const parsed = parseKenoCsvText(item.text, item.label);
        if (parsed.rows.length) {
          loadedSources.push(`${item.label} (${parsed.rows.length} kỳ)`);
          next.sourceLabels.push(item.label);
          parsed.rows.forEach(row => {
            if (mergeKenoDraw(next, row.ky, row.draw)) validRows++;
          });
        }
        skippedRows += parsed.skipped;
      }

      setKenoCsvFeed(next);
      return { validRows, skippedRows, loadedSources, totalRows: kenoCsvFeed.order.length };
    }

    async function loadDefaultKenoCsvSources({ silent = false } = {}) {
      if (IS_LOCAL_MODE) {
        if (!silent) {
          updateKenoCsvStatus(
            "Hãy mở trang qua http://localhost:8080 để web tự đồng bộ CSV Keno. Khi chạy qua server, mục này không cần tải file thủ công nữa.",
            "warn"
          );
        }
        return { validRows: 0, skippedRows: 0, loadedSources: [] };
      }

      const res = await api("/api/keno-predict-data");
      const csvFileName = String(res.csvFileName || "keno_all_day.csv");
      const csvText = String(res.csvText || "");
      if (!csvText.trim()) {
        if (!silent) {
          updateKenoCsvStatus("Server đã trả về trạng thái sync nhưng chưa có nội dung CSV Keno.", "warn");
        }
        return { validRows: 0, skippedRows: 0, loadedSources: [] };
      }

      const parsed = parseKenoCsvText(csvText, csvFileName);
      const next = emptyKenoCsvFeed();
      next.sourceLabels = [csvFileName];
      parsed.rows.forEach(row => {
        mergeKenoDraw(next, row.ky, row.draw);
      });
      setKenoCsvFeed(next);

      const status = res.status || {};
      const notes = [];
      if (status.latest_date) {
        notes.push(`Đã cập nhật web ngày ${status.latest_date}: +${Number(status.new_rows || 0)} kỳ mới.`);
      }
      if (status.sync_error) {
        notes.push(`Không lấy thêm được từ web, đang dùng dữ liệu local: ${status.sync_error}`);
      }
      setKenoPredictStatusMeta(notes.join("\n"), status.sync_error ? "warn" : "ok");
      return {
        validRows: parsed.rows.length,
        skippedRows: parsed.skipped,
        loadedSources: [csvFileName],
        totalRows: parsed.rows.length,
        syncStatus: status,
      };
    }

    async function predictKenoWithPython(order, bundles) {
      if (IS_LOCAL_MODE) {
        throw new Error("Hãy mở trang qua http://localhost:8080 để dùng thuật toán Keno từ Test/L1.py.");
      }

      const params = new URLSearchParams({
        order: String(order),
        bundles: String(bundles),
      });
      const res = await api(`/api/keno-predict?${params.toString()}`);
      const sync = res?.sync || {};
      const detail = sync?.sync_error
        ? `Không thể đồng bộ web, đang dùng dữ liệu local: ${sync.sync_error}`
        : sync?.latest_date
          ? `Đã cập nhật web ngày ${sync.latest_date}: +${Number(sync.new_rows || 0)} kỳ mới.`
          : "";
      setKenoPredictStatusMeta(detail, sync?.sync_error ? "warn" : "ok", res?.generated_at || getSyncedIsoString());
      return res;
    }

    function ensureDataReady(type, outEl, featureLabel) {
      const resultDataset = buildPredictionResultDataset(type);
      const hasResult = (resultDataset.order || []).length > 0;
      const hasPick = (store.pickOrder[type] || []).length > 0;
      if (hasResult && hasPick) return true;
      const miss = [];
      if (!hasResult) miss.push("dữ liệu kết quả");
      if (!hasPick) miss.push("Nhập số đã chọn (mục 2)");
      line(
        outEl,
        `${featureLabel}: cần nhập đủ dữ liệu trước khi dùng.\nThiếu: ${miss.join(" và ")}.`,
        "warn"
      );
      return false;
    }

    function countPickTickets(type) {
      let total = 0;
      for (const ky of (store.pickOrder[type] || [])) {
        total += (store.picks[type]?.[ky] || []).length;
      }
      return total;
    }

    function ensurePickMin(type, outEl, featureLabel, minTickets = 3) {
      const total = countPickTickets(type);
      if (total >= minTickets) return true;
      line(
        outEl,
        `${featureLabel}: cần dữ liệu Nhập số đã chọn (mục 2) tối thiểu ${minTickets} cặp/vé.\nHiện có: ${total}.`,
        "warn"
      );
      return false;
    }

    function getDeleteTargetMeta(target) {
      return target === "results"
        ? { orderKey: "resultOrder", dataKey: "results", uiLabel: "Kết Quả", needText: "Kết Quả" }
        : { orderKey: "pickOrder", dataKey: "picks", uiLabel: "Số Nhập", needText: "Số Chọn" };
    }

    function ensureDeleteTargetReady(type, target, outEl) {
      const meta = getDeleteTargetMeta(target);
      const hasData = (store[meta.orderKey]?.[type] || []).length > 0;
      if (hasData) return true;
      line(outEl, `${meta.uiLabel === "Kết Quả" ? "Xóa Kết Quả" : "Xóa Số Nhập"}: Vui lòng điền ${meta.needText} trước khi xóa.`, "warn");
      return false;
    }

    async function ensureResultOnly(type, outEl, featureLabel) {
      if (!TYPES[type]?.keno && !IS_LOCAL_MODE) {
        try {
          await fetchLiveHistory(type, "all", { silent: true });
        } catch {}
      }
      const resultDataset = buildPredictionResultDataset(type);
      const hasResult = (resultDataset.order || []).length > 0;
      if (hasResult) return true;
      line(
        outEl,
        `${featureLabel}: cần dữ liệu kết quả trước khi dùng.`,
        "warn"
      );
      return false;
    }

    const saveResultBtn = document.getElementById("saveResultBtn");
    if (saveResultBtn) {
      saveResultBtn.onclick = () => {
        const type = document.getElementById("rType").value;
        const ky = normalizeKy(document.getElementById("rKy").value);
        const mode = document.getElementById("rMode").value;
        const out = document.getElementById("rMsg");
        try {
          if (!ky) throw new Error("Kỳ không hợp lệ. Nhập 1, 01, 001, 0001 hoặc #0001.");
          const t = TYPES[type];
          if (mode === "quick") {
            const rawRows = document.getElementById("rQuickRows").value;
            const rows = rawRows.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
            if (!rows.length) throw new Error("Bạn chưa nhập dòng dữ liệu nhanh.");
            const need = t.keno ? (t.resultCount || 20) : (t.mainCount + (t.hasSpecial ? 1 : 0));
            const start = Number(ky.replace("#", ""));
            let saved = 0;
            for (let i = 0; i < rows.length; i++) {
              const nums = parseNums(rows[i]);
              if (nums.length !== need) throw new Error(`Dòng ${i + 1} cần đúng ${need} số.`);
              let main = [];
              let special = null;
              if (t.keno) {
                main = parseDistinctSortedNums(nums, t.mainMin, t.mainMax, t.resultCount || 20, t.resultCount || 20, `KQ Keno dòng ${i + 1}`);
              } else {
                main = parseMain(nums.slice(0, t.mainCount).join(" "), type);
                special = t.hasSpecial ? parseSpecial(String(nums[t.mainCount]), type) : null;
              }
              const kySeq = `#${String(start + i).padStart(4, "0")}`;
              putResult(type, kySeq, { main, special });
              saved++;
            }
            line(out, `Đã lưu nhanh ${saved} kỳ từ ${ky} cho ${TYPES[type].label}.`, "ok");
          } else {
            const rawMain = document.getElementById("rMain").value;
            const rawDb = document.getElementById("rDb").value;
            let main = [];
            let special = null;
            if (t.keno) {
              const line1 = parseNums(rawMain);
              const line2 = parseNums(rawDb);
              if (line1.length !== 10 || line2.length !== 10) {
                throw new Error("KQ Keno (chế độ cơ bản) cần đúng 2 dòng, mỗi dòng 10 số.");
              }
              const nums = [...line1, ...line2];
              main = parseDistinctSortedNums(nums, t.mainMin, t.mainMax, t.resultCount || 20, t.resultCount || 20, "KQ Keno");
            } else {
              const nums = parseNums(rawMain);
              if (t.hasSpecial && !String(rawDb || "").trim() && nums.length === t.mainCount + 1) {
                main = parseMain(nums.slice(0, t.mainCount).join(" "), type);
                special = parseSpecial(String(nums[t.mainCount]), type);
              } else {
                main = parseMain(rawMain, type);
                special = parseSpecial(rawDb, type);
              }
            }
            putResult(type, ky, { main, special });
            line(out, `Đã lưu KQ ${TYPES[type].label} Kỳ ${ky}: ${formatTicket({main, special}, type)}`, "ok");
          }
        } catch (e) {
          line(out, e.message, "warn");
        }
      };
    }

    const savePickBtn = document.getElementById("savePickBtn");
    if (savePickBtn) savePickBtn.onclick = () => {
      const type = document.getElementById("pType").value;
      const ky = normalizeKy(document.getElementById("pKy").value);
      const mode = document.getElementById("pMode").value;
      const raw = mode === "quick" ? document.getElementById("pQuickRows").value : document.getElementById("pTickets").value;
      const out = document.getElementById("pMsg");
      try {
        if (!ky) throw new Error("Kỳ không hợp lệ. Nhập 1, 01, 001, 0001 hoặc #0001.");
        const t = TYPES[type];
        const need = t.mainCount + (t.hasSpecial ? 1 : 0);
        let lines = raw.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);

        // Fast input for picks:
        // - If pasted as a single long line and count is multiple of ticket size,
        //   auto-split into multiple ticket lines.
        if (lines.length === 1) {
          const allNums = parseNums(lines[0]);
          if (!t.keno && allNums.length > need && allNums.length % need === 0) {
            const auto = [];
            for (let i = 0; i < allNums.length; i += need) {
              auto.push(allNums.slice(i, i + need).join(" "));
            }
            lines = auto;
          }
        }

        if (!lines.length) throw new Error("Bạn chưa nhập vé.");
        let ok = 0;
        for (const ln of lines) {
          const nums = parseNums(ln);
          let main = [];
          let special = null;
          if (t.keno) {
            main = parseDistinctSortedNums(nums, t.mainMin, t.mainMax, t.pickMinCount || 1, t.pickMaxCount || 10, `Vé Keno "${ln}"`);
          } else {
            if (nums.length !== need) throw new Error(`Vé "${ln}" sai số lượng số.`);
            main = parseDistinctSortedNums(nums.slice(0, t.mainCount), t.mainMin, t.mainMax, t.mainCount, t.mainCount, `Vé "${ln}"`);
            special = t.hasSpecial ? nums[t.mainCount] : null;
            if (t.hasSpecial && (special < t.specialMin || special > t.specialMax)) {
              throw new Error(`Vé "${ln}" có ĐB ngoài phạm vi ${t.specialMin}-${t.specialMax}.`);
            }
          }
          addPick(type, ky, { main, special });
          ok++;
        }
        line(out, `Đã lưu ${ok} vé cho ${TYPES[type].label} Kỳ ${ky}.`, "ok");
      } catch (e) {
        line(out, e.message, "warn");
      }
    };

    const pTicketsEl = document.getElementById("pTickets");
    if (pTicketsEl) {
      pTicketsEl.addEventListener("input", () => {
        let v = pTicketsEl.value;
        v = v.replace(/\\n/g, "\n");
        v = v.replace(/[;|]+/g, "\n");
        v = v.replace(/[^\d \r\n\t]/g, " ");
        v = v.replace(/[ \t]+/g, " ");
        v = v.replace(/ *\n */g, "\n");
        pTicketsEl.value = v;
      });
    }
    const pQuickEl = document.getElementById("pQuickRows");
    if (pQuickEl) {
      pQuickEl.addEventListener("input", () => {
        let v = pQuickEl.value;
        v = v.replace(/\\n/g, "\n");
        v = v.replace(/[;|]+/g, "\n");
        v = v.replace(/[^\d \r\n\t]/g, " ");
        v = v.replace(/[ \t]+/g, " ");
        v = v.replace(/ *\n */g, "\n");
        pQuickEl.value = v;
      });
    }

    const viewBtn = document.getElementById("viewBtn");
    if (viewBtn) viewBtn.onclick = () => {
      const type = document.getElementById("vType").value;
      const mode = document.getElementById("vMode").value;
      const out = document.getElementById("viewOut");
      if (mode === "result") {
        const dataset = buildPredictionResultDataset(type);
        const keys = dataset.order || [];
        if (!keys.length) {
          return line(out, "Hiển thị Bảng Kết Quả: cần có dữ liệu kết quả trước khi dùng.", "warn");
        }
        const rows = [];
        if (dataset.sourceText) rows.push(dataset.sourceText, "");
        keys.forEach(ky => {
          const draw = dataset.results?.[ky];
          if (!draw) return;
          rows.push(`${TYPES[type].label} Kỳ ${ky} - ${formatTicket(draw, type)}`);
        });
        line(out, rows.join("\n"));
      } else {
        const keys = store.pickOrder[type];
        if (!keys.length) {
          return line(out, "Hiển thị Bảng số đã chọn: cần nhập dữ liệu số đã chọn ở mục 2 trước khi dùng.", "warn");
        }
        const lines = [];
        for (const ky of keys) {
          const arr = store.picks[type][ky] || [];
          if (!arr.length) continue;
          for (const ticket of arr) {
            lines.push(`${TYPES[type].label} Kỳ ${ky} - ${formatTicket(ticket, type)}`);
          }
        }
        line(out, lines.join("\n"));
      }
    };

    function ball(cls) {
      return `<span class="ball ${cls}">O</span>`;
    }
    function mainBalls(total, hit) {
      return `${Array.from({ length: hit }, () => ball("ball-main-hit")).join("")}${Array.from({ length: total - hit }, () => ball("ball-main-miss")).join("")}`;
    }
    function specialBall(hit) {
      return ball(hit ? "ball-special-hit" : "ball-special-miss");
    }
    function renderPrizeResult(total, hit, specialHit = false) {
      return `
        <span class="prize-result-line">
          <span class="prize-result-main">${mainBalls(total, hit)}</span>
          ${specialHit ? `<span class="prize-result-plus">+</span><span class="prize-result-special">${specialBall(true)}</span>` : ""}
        </span>
      `;
    }
    function renderLotto535Match(mainHitCount, specialHit = false) {
      const safeMainHitCount = Math.max(0, Number(mainHitCount || 0));
      const main = safeMainHitCount > 0 ? mainBalls(safeMainHitCount, safeMainHitCount) : "";
      const plus = safeMainHitCount > 0 && specialHit ? "+" : "";
      return `
        <span class="prize-match-line">
          <span class="prize-match-main">${main}</span>
          <span class="prize-match-plus">${plus}</span>
          <span class="prize-match-special">${specialHit ? specialBall(true) : ""}</span>
        </span>
      `;
    }
    function renderPrizeLegend(items) {
      const legendItems = items.map(([ballClass, label]) => `
        <span class="prize-legend-item">
          ${ball(ballClass)}
          <span>${escapeHtml(label)}</span>
        </span>
      `).join("");
      return `
        <div class="prize-note prize-legend">
          <span class="prize-legend-title">Ghi chú</span>
          ${legendItems}
          <span class="prize-legend-rule">Các số không theo thứ tự.</span>
        </div>
      `;
    }
    function formatPrizeCurrency(value) {
      return `${Math.max(0, Number(value || 0)).toLocaleString("vi-VN")} VNĐ`;
    }
    function combinationCount(n, k) {
      const safeN = Math.max(0, Number(n || 0));
      const safeK = Math.max(0, Number(k || 0));
      if (!Number.isFinite(safeN) || !Number.isFinite(safeK) || safeK > safeN) return 0;
      if (safeK === 0 || safeK === safeN) return 1;
      const choose = Math.min(safeK, safeN - safeK);
      let out = 1;
      for (let i = 1; i <= choose; i++) {
        out = (out * (safeN - choose + i)) / i;
      }
      return Math.round(out);
    }
    function buildPrizeSection(title, subtitle, content) {
      return `
        <section class="prize-section">
          <div class="prize-section-head">
            <h3 class="prize-section-title">${escapeHtml(title)}</h3>
            <div class="prize-section-subtitle">${subtitle}</div>
          </div>
          ${content}
        </section>
      `;
    }
    function buildBaoGuarantee(type, n) {
      if (type === "LOTO_5_35") {
        return `Nếu cả 5 số chính trúng đều nằm trong tập ${n} số đã bao, sẽ có ít nhất 1 vé con trúng đủ 5 số chính. Số đặc biệt vẫn cần khớp riêng theo từng vé.`;
      }
      if (type === "LOTO_6_55") {
        return `Nếu cả 6 số chính trúng đều nằm trong tập ${n} số đã bao, sẽ có ít nhất 1 vé con trúng đủ 6 số chính. Jackpot 2 vẫn phụ thuộc thêm số đặc biệt.`;
      }
      return `Nếu cả 6 số trúng đều nằm trong tập ${n} số đã bao, sẽ có ít nhất 1 vé con trúng đủ 6 số.`;
    }
    function buildBaoNote(type) {
      if (type === "LOTO_5_35") {
        return `<b>Ghi chú Bao Vé:</b> Tính theo bao số chính, giá vé cơ bản 10.000 VNĐ/vé con.`;
      }
      if (type === "LOTO_6_55") {
        return `<b>Ghi chú Bao Vé:</b> Tính theo bao 6 số chính, giá vé cơ bản 10.000 VNĐ/vé con. Jackpot 2 của Power 6/55 vẫn phụ thuộc thêm số đặc biệt trên từng vé con.`;
      }
      return `<b>Ghi chú Bao Vé:</b> Bao vé giúp tăng độ phủ tổ hợp, không làm tăng xác suất nền của việc chọn đúng tập số mạnh. Chi phí tính theo toàn bộ vé con phát sinh ở mức 10.000 VNĐ/vé.`;
    }
    function getBaoBrochureTheme(type) {
      if (type === "LOTO_5_35") return "theme-lotto";
      if (type === "LOTO_6_55") return "theme-power";
      return "theme-mega";
    }
    function getBaoBrochureData(type) {
      const data = {
        LOTO_5_35: [
          { level: 4, sub: "Bao 4 (310K/1 lần dự thưởng)", rows: [
            ["4 số chính + ĐB", "ĐỘC ĐẮC + 150 TRIỆU"],
            ["4 số chính", "25 TRIỆU ĐỒNG"],
            ["3 số chính + ĐB", "12,9 TRIỆU ĐỒNG"],
            ["3 số chính", "1,87 TRIỆU ĐỒNG"],
            ["2 số chính + ĐB", "580.000"],
            ["2 số chính", "90.000"],
            ["1 số chính + ĐB hoặc chỉ ĐB", "310.000"]
          ]},
          { level: 6, sub: "Bao 6 (60K/1 lần dự thưởng)", rows: [
            ["5 số chính + ĐB", "ĐỘC ĐẮC + 25 TRIỆU"],
            ["5 số chính", "12,5 TRIỆU ĐỒNG"],
            ["4 số chính + ĐB", "10,4 TRIỆU ĐỒNG"],
            ["4 số chính", "1,12 TRIỆU ĐỒNG"],
            ["3 số chính + ĐB", "330.000"],
            ["3 số chính", "90.000"],
            ["2 số chính + ĐB", "60.000"]
          ]},
          { level: 7, sub: "Bao 7 (210K/1 lần dự thưởng)", rows: [
            ["5 số chính + ĐB", "ĐỘC ĐẮC + 51 TRIỆU"],
            ["5 số chính", "15,3 TRIỆU ĐỒNG"],
            ["4 số chính + ĐB", "16,26 TRIỆU ĐỒNG"],
            ["4 số chính", "1,86 TRIỆU ĐỒNG"],
            ["3 số chính + ĐB", "750.000"],
            ["3 số chính", "180.000"],
            ["2 số chính + ĐB", "210.000"]
          ]},
          { level: 8, sub: "Bao 8 (560K/1 lần dự thưởng)", rows: [
            ["5 số chính + ĐB", "ĐỘC ĐẮC + 78,1 TRIỆU"],
            ["5 số chính", "18,4 TRIỆU ĐỒNG"],
            ["4 số chính + ĐB", "22,68 TRIỆU ĐỒNG"],
            ["4 số chính", "2,72 TRIỆU ĐỒNG"],
            ["3 số chính + ĐB", "1,46 TRIỆU ĐỒNG"],
            ["3 số chính", "300.000"],
            ["2 số chính + ĐB", "560.000"]
          ]},
          { level: 9, sub: "Bao 9 (1.260K/1 lần dự thưởng)", rows: [
            ["5 số chính + ĐB", "ĐỘC ĐẮC + 106,45 TRIỆU"],
            ["5 số chính", "21,8 TRIỆU ĐỒNG"],
            ["4 số chính + ĐB", "29,81 TRIỆU ĐỒNG"],
            ["4 số chính", "3,7 TRIỆU ĐỒNG"],
            ["3 số chính + ĐB", "2,61 TRIỆU ĐỒNG"],
            ["3 số chính", "450.000"],
            ["2 số chính + ĐB", "1,26 TRIỆU ĐỒNG"]
          ]},
          { level: 10, sub: "Bao 10 (2.520K/1 lần dự thưởng)", rows: [
            ["5 số chính + ĐB", "ĐỘC ĐẮC + 136,26 TRIỆU"],
            ["5 số chính", "25,5 TRIỆU ĐỒNG"],
            ["4 số chính + ĐB", "37,86 TRIỆU ĐỒNG"],
            ["4 số chính", "4,8 TRIỆU ĐỒNG"],
            ["3 số chính + ĐB", "4,41 TRIỆU ĐỒNG"],
            ["3 số chính", "630.000"],
            ["2 số chính + ĐB", "2,52 TRIỆU ĐỒNG"]
          ]},
          { level: 11, sub: "Bao 11 (4.620K/1 lần dự thưởng)", rows: [
            ["5 số chính + ĐB", "ĐỘC ĐẮC + 167,81 TRIỆU"],
            ["5 số chính", "29,5 TRIỆU ĐỒNG"],
            ["4 số chính + ĐB", "47,11 TRIỆU ĐỒNG"],
            ["4 số chính", "6,02 TRIỆU ĐỒNG"],
            ["3 số chính + ĐB", "7,14 TRIỆU ĐỒNG"],
            ["3 số chính", "840.000"],
            ["2 số chính + ĐB", "4,62 TRIỆU ĐỒNG"]
          ]},
          { level: 12, sub: "Bao 12 (7.920K/1 lần dự thưởng)", rows: [
            ["5 số chính + ĐB", "ĐỘC ĐẮC + 201,46 TRIỆU"],
            ["5 số chính", "33,8 TRIỆU ĐỒNG"],
            ["4 số chính + ĐB", "57,92 TRIỆU ĐỒNG"],
            ["4 số chính", "7,36 TRIỆU ĐỒNG"],
            ["3 số chính + ĐB", "11,16 TRIỆU ĐỒNG"],
            ["3 số chính", "1,08 TRIỆU ĐỒNG"],
            ["2 số chính + ĐB", "7,92 TRIỆU ĐỒNG"]
          ]},
          { level: 13, sub: "Bao 13 (12.870K/1 lần dự thưởng)", rows: [
            ["5 số chính + ĐB", "ĐỘC ĐẮC + 237,66 TRIỆU"],
            ["5 số chính", "38,4 TRIỆU ĐỒNG"],
            ["4 số chính + ĐB", "70,74 TRIỆU ĐỒNG"],
            ["4 số chính", "8,82 TRIỆU ĐỒNG"],
            ["3 số chính + ĐB", "16,92 TRIỆU ĐỒNG"],
            ["3 số chính", "1,35 TRIỆU ĐỒNG"],
            ["2 số chính + ĐB", "12,87 TRIỆU ĐỒNG"]
          ]},
          { level: 14, sub: "Bao 14 (20.020K/1 lần dự thưởng)", rows: [
            ["5 số chính + ĐB", "ĐỘC ĐẮC + 276,96 TRIỆU"],
            ["5 số chính", "43,3 TRIỆU ĐỒNG"],
            ["4 số chính + ĐB", "86,12 TRIỆU ĐỒNG"],
            ["4 số chính", "10,4 TRIỆU ĐỒNG"],
            ["3 số chính + ĐB", "24,97 TRIỆU ĐỒNG"],
            ["3 số chính", "1,65 TRIỆU ĐỒNG"],
            ["2 số chính + ĐB", "20,02 TRIỆU ĐỒNG"]
          ]},
          { level: 15, sub: "Bao 15 (30.030K/1 lần dự thưởng)", rows: [
            ["5 số chính + ĐB", "ĐỘC ĐẮC + 320,02 TRIỆU"],
            ["5 số chính", "48,5 TRIỆU ĐỒNG"],
            ["4 số chính + ĐB", "104,72 TRIỆU ĐỒNG"],
            ["4 số chính", "12,1 TRIỆU ĐỒNG"],
            ["3 số chính + ĐB", "35,97 TRIỆU ĐỒNG"],
            ["3 số chính", "1,98 TRIỆU ĐỒNG"],
            ["2 số chính + ĐB", "30,03 TRIỆU ĐỒNG"]
          ]}
        ],
        LOTO_6_45: [
          { level: 5, sub: "Chọn 5 số (400.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 2 số", "120.000"],
            ["Trúng 3 số", "2.010.000"],
            ["Trúng 4 số", "31.400.000"],
            ["Trúng 5 số", "JACKPOT + 390 TRIỆU"]
          ]},
          { level: 7, sub: "Chọn 7 số (70.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "120.000"],
            ["Trúng 4 số", "1.020.000"],
            ["Trúng 5 số", "21.500.000"],
            ["Trúng 6 số", "JACKPOT + 60 TRIỆU"]
          ]},
          { level: 8, sub: "Chọn 8 số (280.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "300.000"],
            ["Trúng 4 số", "2.280.000"],
            ["Trúng 5 số", "34.800.000"],
            ["Trúng 6 số", "JACKPOT + 124,5 TRIỆU"]
          ]},
          { level: 9, sub: "Chọn 9 số (840.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "600.000"],
            ["Trúng 4 số", "4.200.000"],
            ["Trúng 5 số", "50.200.000"],
            ["Trúng 6 số", "JACKPOT + 194,1 TRIỆU"]
          ]},
          { level: 10, sub: "Chọn 10 số (2.100.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "1.050.000"],
            ["Trúng 4 số", "6.900.000"],
            ["Trúng 5 số", "68.000.000"],
            ["Trúng 6 số", "JACKPOT + 269,4 TRIỆU"]
          ]},
          { level: 11, sub: "Chọn 11 số (4.620.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "1.680.000"],
            ["Trúng 4 số", "10.500.000"],
            ["Trúng 5 số", "88.500.000"],
            ["Trúng 6 số", "JACKPOT + 351 TRIỆU"]
          ]},
          { level: 12, sub: "Chọn 12 số (9.240.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "2.520.000"],
            ["Trúng 4 số", "15.120.000"],
            ["Trúng 5 số", "112.000.000"],
            ["Trúng 6 số", "JACKPOT + 439,5 TRIỆU"]
          ]},
          { level: 13, sub: "Chọn 13 số (17.160.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "3.600.000"],
            ["Trúng 4 số", "20.880.000"],
            ["Trúng 5 số", "138.800.000"],
            ["Trúng 6 số", "JACKPOT + 535,5 TRIỆU"]
          ]},
          { level: 14, sub: "Chọn 14 số (30.030.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "4.950.000"],
            ["Trúng 4 số", "27.900.000"],
            ["Trúng 5 số", "169.200.000"],
            ["Trúng 6 số", "JACKPOT + 639,6 TRIỆU"]
          ]},
          { level: 15, sub: "Chọn 15 số (50.050.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "6.600.000"],
            ["Trúng 4 số", "36.300.000"],
            ["Trúng 5 số", "203.500.000"],
            ["Trúng 6 số", "JACKPOT + 752,4 TRIỆU"]
          ]},
          { level: 18, sub: "Chọn 18 số (185.640.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "13.650.000"],
            ["Trúng 4 số", "70.980.000"],
            ["Trúng 5 số", "332.800.000"],
            ["Trúng 6 số", "JACKPOT + 1,149 TỶ"]
          ]}
        ],
        LOTO_6_55: [
          { level: 5, sub: "Chọn 5 số (500.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 2 số", "200.000"],
            ["Trúng 3 số", "3.850.000"],
            ["Trúng 4 số", "104.000.000"],
            ["Trúng 4 số + số đặc biệt", "(JACKPOT2 X 2) + 24 TRIỆU"],
            ["Trúng 5 số", "JACKPOT1 + JACKPOT2 + 1,92 TỶ"]
          ]},
          { level: 7, sub: "Chọn 7 số (70.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "200.000"],
            ["Trúng 4 số", "1.700.000"],
            ["Trúng 5 số", "82.500.000"],
            ["Trúng 5 số + số đặc biệt", "JACKPOT2 + 42,5 TRIỆU"],
            ["Trúng 6 số", "JACKPOT1 + 240 TRIỆU"],
            ["Trúng 6 số + số đặc biệt", "JACKPOT1 + (JACKPOT2 X 6)"]
          ]},
          { level: 8, sub: "Chọn 8 số (280.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "500.000"],
            ["Trúng 4 số", "3.800.000"],
            ["Trúng 5 số", "128.000.000"],
            ["Trúng 5 số + số đặc biệt", "JACKPOT2 + 88 TRIỆU"],
            ["Trúng 6 số", "JACKPOT1 + 487,5 TRIỆU"],
            ["Trúng 6 số + số đặc biệt", "JACKPOT1 + (JACKPOT2 X 6) + 247,5 TRIỆU"]
          ]},
          { level: 9, sub: "Chọn 9 số (840.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "1.000.000"],
            ["Trúng 4 số", "7.000.000"],
            ["Trúng 5 số", "177.000.000"],
            ["Trúng 5 số + số đặc biệt", "JACKPOT2 + 137 TRIỆU"],
            ["Trúng 6 số", "JACKPOT1 + 743,5 TRIỆU"],
            ["Trúng 6 số + số đặc biệt", "JACKPOT1 + (JACKPOT2 X 6) + 503,5 TRIỆU"]
          ]},
          { level: 10, sub: "Chọn 10 số (2.100.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "1.750.000"],
            ["Trúng 4 số", "11.500.000"],
            ["Trúng 5 số", "230.000.000"],
            ["Trúng 5 số + số đặc biệt", "JACKPOT2 + 190 TRIỆU"],
            ["Trúng 6 số", "JACKPOT1 + 1,009 TỶ"],
            ["Trúng 6 số + số đặc biệt", "JACKPOT1 + (JACKPOT2 X 6) + 769 TRIỆU"]
          ]},
          { level: 11, sub: "Chọn 11 số (4.620.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "2.800.000"],
            ["Trúng 4 số", "17.500.000"],
            ["Trúng 5 số", "287.500.000"],
            ["Trúng 5 số + số đặc biệt", "JACKPOT2 + 247,5 TRIỆU"],
            ["Trúng 6 số", "JACKPOT1 + 1,285 TỶ"],
            ["Trúng 6 số + số đặc biệt", "JACKPOT1 + (JACKPOT2 X 6) + 1,045 TỶ"]
          ]},
          { level: 12, sub: "Chọn 12 số (9.240.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "4.200.000"],
            ["Trúng 4 số", "25.200.000"],
            ["Trúng 5 số", "350.000.000"],
            ["Trúng 5 số + số đặc biệt", "JACKPOT2 + 310 TRIỆU"],
            ["Trúng 6 số", "JACKPOT1 + 1,575 TỶ"],
            ["Trúng 6 số + số đặc biệt", "JACKPOT1 + (JACKPOT2 X 6) + 1,335 TỶ"]
          ]},
          { level: 13, sub: "Chọn 13 số (17.160.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "6.000.000"],
            ["Trúng 4 số", "34.800.000"],
            ["Trúng 5 số", "418.000.000"],
            ["Trúng 5 số + số đặc biệt", "JACKPOT2 + 378 TRIỆU"],
            ["Trúng 6 số", "JACKPOT1 + 1,8725 TỶ"],
            ["Trúng 6 số + số đặc biệt", "JACKPOT1 + (JACKPOT2 X 6) + 1,6325 TỶ"]
          ]},
          { level: 14, sub: "Chọn 14 số (30.030.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "8.250.000"],
            ["Trúng 4 số", "46.500.000"],
            ["Trúng 5 số", "492.000.000"],
            ["Trúng 5 số + số đặc biệt", "JACKPOT2 + 452 TRIỆU"],
            ["Trúng 6 số", "JACKPOT1 + 2,186 TỶ"],
            ["Trúng 6 số + số đặc biệt", "JACKPOT1 + (JACKPOT2 X 6) + 1,946 TỶ"]
          ]},
          { level: 15, sub: "Chọn 15 số (50.050.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "11.000.000"],
            ["Trúng 4 số", "60.500.000"],
            ["Trúng 5 số", "572.500.000"],
            ["Trúng 5 số + số đặc biệt", "JACKPOT2 + 532,5 TRIỆU"],
            ["Trúng 6 số", "JACKPOT1 + 2,514 TỶ"],
            ["Trúng 6 số + số đặc biệt", "JACKPOT1 + (JACKPOT2 X 6) + 2,274 TỶ"]
          ]},
          { level: 18, sub: "Chọn 18 số (185.640.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "22.750.000"],
            ["Trúng 4 số", "118.300.000"],
            ["Trúng 5 số", "858.000.000"],
            ["Trúng 5 số + số đặc biệt", "JACKPOT2 + 818 TRIỆU"],
            ["Trúng 6 số", "JACKPOT1 + 3,595 TỶ"],
            ["Trúng 6 số + số đặc biệt", "JACKPOT1 + (JACKPOT2 X 6) + 3,355 TỶ"]
          ]}
        ]
      };
      return data[type] || [];
    }
    function renderBaoPrizeTable(type) {
      const brochureCards = getBaoBrochureData(type);
      if (!brochureCards.length) return "";
      const themeClass = getBaoBrochureTheme(type);
      const cards = brochureCards.map(card => `
        <article class="bao-prize-brochure ${themeClass}">
          <div class="bao-prize-brochure-title">BAO ${escapeHtml(card.level)}</div>
          <div class="bao-prize-brochure-sub">${escapeHtml(card.sub)}</div>
          <table class="bao-prize-mini">
            <tbody>
              ${card.rows.map(row => `
                <tr>
                  <td>${escapeHtml(row[0])}</td>
                  <td>${escapeHtml(row[1])}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </article>
      `);
      return buildPrizeSection(
        "Bao Vé",
        escapeHtml(type === "LOTO_5_35" ? "Hiển thị theo brochure Lotto 5/35" : (type === "LOTO_6_55" ? "Hiển thị theo brochure Power 6/55" : "Hiển thị theo brochure Mega 6/45")),
        `
          <div class="bao-prize-grid">${cards.join("")}</div>
          <div class="prize-note">${buildBaoNote(type)}</div>
        `
      );
    }
    // ---abc--- Prize Panel / Brochure Rendering ---
    function renderPrizeTable(type) {
      if (type === "KENO") {
        const cols = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1];
        const rows = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0];
        const head = cols.map(c => `<th>${c}</th>`).join("");
        const body = rows.map(r => {
          const tds = cols.map(c => {
            const v = KENO_PAYOUT[c]?.[r];
            return `<td class="${v ? "" : "empty"}">${v || "·"}</td>`;
          }).join("");
          return `<tr><th scope="row">${r}</th>${tds}</tr>`;
        }).join("");
        return `
          <div class="keno-prize-board">
            <div class="keno-prize-topbar">
              <div class="keno-prize-title">Bảng thưởng Keno</div>
              <div class="keno-prize-subtitle">Cột: số bạn chơi • Hàng: số bạn trúng</div>
            </div>
            <div class="keno-prize-layout">
              <div class="keno-prize-scroller">
                <table class="prize-table keno-prize-table">
                  <thead>
                    <tr>
                      <th class="corner">Trúng / Chơi</th>
                      ${head}
                    </tr>
                  </thead>
                  <tbody>${body}</tbody>
                </table>
              </div>
            </div>
            <div class="keno-prize-foot">
              <div class="keno-prize-note"><b>Cao nhất:</b> Bậc 10 trùng 10 số = 2 tỷ.</div>
              <div class="keno-prize-note"><b>*</b> Bậc 8-10 có giới hạn/chia thưởng theo quy định.</div>
            </div>
          </div>
        `;
      }
      if (TYPES[type]?.threeDigit) {
        if (type === "MAX_3D") {
          return `
            <div class="prize-sections">
              ${buildPrizeSection(
                "Phần Thưởng Max 3D",
                "Cơ cấu thưởng chính thức của Max 3D",
                `
                  <div class="prize-table-wrap">
                    <table class="prize-table">
                      <thead>
                        <tr>
                          <th>Giải thưởng</th>
                          <th>Kết quả</th>
                          <th>Giá trị giải thưởng (VNĐ)</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr><td>Giải Đặc Biệt</td><td>Trùng bất kỳ 1 trong 2 bộ ba số quay thưởng giải Đặc biệt theo đúng thứ tự các số</td><td>1.000.000</td></tr>
                        <tr><td>Giải Nhất</td><td>Trùng bất kỳ 1 trong 4 bộ ba số quay thưởng giải Nhất theo đúng thứ tự các số</td><td>350.000</td></tr>
                        <tr><td>Giải Nhì</td><td>Trùng bất kỳ 1 trong 6 bộ ba số quay thưởng giải Nhì theo đúng thứ tự các số</td><td>210.000</td></tr>
                        <tr><td>Giải Ba</td><td>Trùng bất kỳ 1 trong 8 bộ ba số quay thưởng giải Ba theo đúng thứ tự các số</td><td>100.000</td></tr>
                      </tbody>
                    </table>
                  </div>
                  <div class="prize-note"><b>Ghi chú:</b> Mỗi kỳ quay số mở thưởng chọn ra 20 bộ ba số trúng giải, gồm 2 giải Đặc biệt, 4 giải Nhất, 6 giải Nhì và 8 giải Ba. Nếu một bộ số trúng nhiều giải thì được lĩnh tổng các giải trúng.</div>
                `
              )}
            </div>
          `;
        }
        if (type === "MAX_3D_PRO") {
          return `
            <div class="prize-sections">
              ${buildPrizeSection(
                "Phần Thưởng Max 3D Pro",
                "Cơ cấu thưởng chính thức của Max 3D Pro",
                `
                  <div class="prize-table-wrap">
                    <table class="prize-table">
                      <thead>
                        <tr>
                          <th>Giải thưởng</th>
                          <th>Kết quả</th>
                          <th>Giá trị giải thưởng (VNĐ)</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr><td>Giải Đặc Biệt</td><td>Trùng hai bộ ba số quay thưởng giải Đặc biệt theo đúng thứ tự quay</td><td>2.000.000.000</td></tr>
                        <tr><td>Giải phụ Đặc Biệt</td><td>Trùng hai bộ ba số quay thưởng giải Đặc biệt theo ngược thứ tự quay</td><td>400.000.000</td></tr>
                        <tr><td>Giải Nhất</td><td>Trùng bất kỳ 2 trong 4 bộ ba số quay thưởng giải Nhất</td><td>30.000.000</td></tr>
                        <tr><td>Giải Nhì</td><td>Trùng bất kỳ 2 trong 6 bộ ba số quay thưởng giải Nhì</td><td>10.000.000</td></tr>
                        <tr><td>Giải Ba</td><td>Trùng bất kỳ 2 trong 8 bộ ba số quay thưởng giải Ba</td><td>4.000.000</td></tr>
                        <tr><td>Giải Tư</td><td>Trùng bất kỳ 2 bộ ba số quay thưởng của giải Đặc biệt, Nhất, Nhì hoặc Ba</td><td>1.000.000</td></tr>
                        <tr><td>Giải Năm</td><td>Trùng 1 bộ ba số quay thưởng giải Đặc biệt bất kỳ</td><td>100.000</td></tr>
                        <tr><td>Giải Sáu</td><td>Trùng 1 bộ ba số quay thưởng giải Nhất, Nhì hoặc Ba bất kỳ</td><td>40.000</td></tr>
                      </tbody>
                    </table>
                  </div>
                  <div class="prize-note"><b>Ghi chú:</b> Mỗi kỳ quay số mở thưởng chọn ra 20 bộ ba số trúng giải, gồm 2 bộ Đặc biệt, 4 bộ Nhất, 6 bộ Nhì và 8 bộ Ba. Nếu chọn hai bộ ba số giống nhau, giá trị giải từ Nhất đến Sáu được nhân đôi; riêng Đặc biệt/phụ Đặc biệt tính theo tổng giá trị hai giải tương ứng.</div>
                `
              )}
            </div>
          `;
        }
        return `
          <div class="prize-sections">
            ${buildPrizeSection(
              "Phần Thưởng Vietlott 3D",
              `Cơ cấu thưởng của ${escapeHtml(TYPES[type]?.label || type)}`,
              `<div class="prize-note"><b>Ghi chú:</b> Chưa có bảng thưởng riêng cho loại này trong panel hiện tại.</div>`
            )}
          </div>
        `;
      }
      if (type === "LOTO_5_35") {
        const regularSection = buildPrizeSection(
          "Vé Thường",
          "Cơ cấu thưởng chuẩn của Lotto 5/35",
          `
            <div class="prize-table-wrap">
              <table class="prize-table prize-table-lotto-535">
                <colgroup>
                  <col class="prize-col-name">
                  <col class="prize-col-match">
                  <col class="prize-col-value">
                </colgroup>
                <thead>
                  <tr>
                    <th>Giải</th>
                    <th>Trúng khớp</th>
                    <th>Giá trị giải thưởng (VNĐ)</th>
                  </tr>
                </thead>
                <tbody>
                  <tr><td>Giải Độc Đắc</td><td>${renderLotto535Match(5, true)}</td><td>(Tối thiểu 6 tỷ và tích lũy)</td></tr>
                  <tr><td>Giải Nhất</td><td>${renderLotto535Match(5)}</td><td>10.000.000 *</td></tr>
                  <tr><td>Giải Nhì</td><td>${renderLotto535Match(4, true)}</td><td>5.000.000 *</td></tr>
                  <tr><td>Giải Ba</td><td>${renderLotto535Match(4)}</td><td>500.000 *</td></tr>
                  <tr><td>Giải Tư</td><td>${renderLotto535Match(3, true)}</td><td>100.000 *</td></tr>
                  <tr><td>Giải Năm</td><td>${renderLotto535Match(3)}</td><td>30.000 *</td></tr>
                  <tr>
                    <td>Giải Khuyến Khích</td>
                    <td class="prize-lines">
                      <div>${renderLotto535Match(2, true)}</div>
                      <div>${renderLotto535Match(1, true)}</div>
                      <div>${renderLotto535Match(0, true)}</div>
                    </td>
                    <td>10.000 *</td>
                  </tr>
                </tbody>
              </table>
            </div>
            ${renderPrizeLegend([
              ["ball-main-hit", "Bóng xanh: số chính trúng"],
              ["ball-special-hit", "Bóng cam: số đặc biệt trúng"]
            ])}
          `
        );
        return `<div class="prize-sections">${regularSection}${renderBaoPrizeTable(type)}</div>`;
      }
      if (type === "LOTO_6_45") {
        const regularSection = buildPrizeSection(
          "Vé Thường",
          "Cơ cấu thưởng chuẩn của Mega 6/45",
          `
            <div class="prize-table-wrap">
              <table class="prize-table">
                <thead>
                  <tr>
                    <th>Giải thưởng</th>
                    <th>Kết quả</th>
                    <th>Giá trị giải thưởng (VNĐ)</th>
                  </tr>
                </thead>
                <tbody>
                  <tr><td>Giải Đặc biệt</td><td>${mainBalls(6, 6)}</td><td>(Tối thiểu 12 tỷ và tích lũy)</td></tr>
                  <tr><td>Giải Nhất</td><td>${mainBalls(6, 5)}</td><td>10.000.000</td></tr>
                  <tr><td>Giải Nhì</td><td>${mainBalls(6, 4)}</td><td>300.000</td></tr>
                  <tr><td>Giải Ba</td><td>${mainBalls(6, 3)}</td><td>30.000</td></tr>
                </tbody>
              </table>
            </div>
            ${renderPrizeLegend([
              ["ball-main-hit", "Bóng xanh: số trúng"],
              ["ball-main-miss", "Bóng đen/xám: số không trúng"]
            ])}
          `
        );
        return `<div class="prize-sections">${regularSection}${renderBaoPrizeTable(type)}</div>`;
      }
      const regularSection = buildPrizeSection(
        "Vé Thường",
        "Cơ cấu thưởng chuẩn của Power 6/55",
        `
          <div class="prize-table-wrap">
            <table class="prize-table">
              <thead>
                <tr>
                  <th>Giải thưởng</th>
                  <th>Kết quả</th>
                  <th>Giá trị giải thưởng (VNĐ)</th>
                </tr>
              </thead>
              <tbody>
                <tr><td>Giải Jackpot 1</td><td>${renderPrizeResult(6, 6)}</td><td>(Tối thiểu 30 tỷ và tích lũy)</td></tr>
                <tr><td>Giải Jackpot 2</td><td>${renderPrizeResult(6, 5, true)}</td><td>(Tối thiểu 3 tỷ và tích lũy)</td></tr>
                <tr><td>Giải Nhất</td><td>${renderPrizeResult(6, 5)}</td><td>40.000.000</td></tr>
                <tr><td>Giải Nhì</td><td>${renderPrizeResult(6, 4)}</td><td>500.000</td></tr>
                <tr><td>Giải Ba</td><td>${renderPrizeResult(6, 3)}</td><td>50.000</td></tr>
              </tbody>
            </table>
          </div>
          ${renderPrizeLegend([
            ["ball-main-hit", "Bóng xanh: số chính trúng"],
            ["ball-special-hit", "Bóng cam: số đặc biệt trúng (Jackpot 2)"],
            ["ball-main-miss", "Bóng đen/xám: số không trúng"]
          ])}
        `
      );
      return `<div class="prize-sections">${regularSection}${renderBaoPrizeTable(type)}</div>`;
    }
    let currentPrizePartIndex = 0;
    function setPrizePart(out, index) {
      const safeIndex = Math.max(0, Number(index || 0));
      currentPrizePartIndex = safeIndex;
      const sections = out ? [...out.querySelectorAll(".prize-sections > .prize-section")] : [];
      const buttons = [...document.querySelectorAll("#prizePartTabs .prize-part-tab")];
      sections.forEach((section, sectionIndex) => {
        section.classList.toggle("is-hidden", sectionIndex !== safeIndex);
      });
      buttons.forEach((button, buttonIndex) => {
        const active = buttonIndex === safeIndex;
        button.classList.toggle("is-active", active);
        button.setAttribute("aria-selected", active ? "true" : "false");
      });
    }
    function applyPrizePartTabs(out) {
      const host = out?.querySelector(".prize-sections");
      const buttons = [...document.querySelectorAll("#prizePartTabs .prize-part-tab")];
      if (!host) {
        currentPrizePartIndex = 0;
        buttons.forEach((button, index) => {
          const available = index === 0;
          button.disabled = !available;
          button.classList.toggle("is-disabled", !available);
          button.title = available ? "Bảng thưởng hiện tại" : "Loại vé này chưa có phần Bao Vé.";
        });
        setPrizePart(out, 0);
        return;
      }
      const sections = [...host.querySelectorAll(":scope > .prize-section")];
      buttons.forEach((button, index) => {
        const available = index < sections.length;
        button.disabled = !available;
        button.classList.toggle("is-disabled", !available);
        button.title = available
          ? (sections[index].querySelector(".prize-section-title")?.textContent?.trim() || button.textContent.trim())
          : "Loại vé này chưa có phần Bao Vé.";
      });
      if (currentPrizePartIndex >= sections.length) currentPrizePartIndex = 0;
      setPrizePart(out, currentPrizePartIndex);
    }
    function bindPrizePartTabs() {
      const tabs = document.getElementById("prizePartTabs");
      if (!tabs || tabs.dataset.bound) return;
      tabs.dataset.bound = "1";
      tabs.addEventListener("click", event => {
        const button = event.target.closest("[data-prize-part]");
        if (!button || button.disabled) return;
        const out = document.getElementById("prizeOut");
        if (!out?.classList.contains("prize-box")) {
          currentPrizePartIndex = Number(button.dataset.prizePart || 0);
          renderPrizePanel();
          return;
        }
        setPrizePart(out, Number(button.dataset.prizePart || 0));
      });
    }
    function renderPrizePanel() {
      const type = document.getElementById("prizeType").value;
      const out = document.getElementById("prizeOut");
      out.className = "result-box prize-box";
      out.innerHTML = renderPrizeTable(type);
      out.classList.toggle("is-section-layout", !!out.querySelector(":scope > .prize-sections"));
      applyPrizePartTabs(out);
    }
    document.getElementById("showPrizeBtn").onclick = () => renderPrizePanel();
    document.getElementById("prizeType").onchange = () => renderPrizePanel();
    bindPrizePartTabs();

    function range(min, max) {
      const out = [];
      for (let i = min; i <= max; i++) out.push(i);
      return out;
    }

    function countFreqFromPicks(type) {
      const t = TYPES[type];
      const freqMain = Object.fromEntries(range(t.mainMin, t.mainMax).map(n => [n, 0]));
      const freqSpecial = t.hasSpecial ? Object.fromEntries(range(t.specialMin, t.specialMax).map(n => [n, 0])) : null;
      for (const ky of store.pickOrder[type]) {
        for (const ticket of (store.picks[type][ky] || [])) {
          for (const n of ticket.main) freqMain[n]++;
          if (t.hasSpecial && Number.isInteger(ticket.special)) freqSpecial[ticket.special]++;
        }
      }
      return { freqMain, freqSpecial };
    }

    function countFreqFromResults(type, dataset = null) {
      const t = TYPES[type];
      const resultOrder = dataset?.order || store.resultOrder[type] || [];
      const resultMap = dataset?.results || store.results[type] || {};
      const freqMain = Object.fromEntries(range(t.mainMin, t.mainMax).map(n => [n, 0]));
      const freqSpecial = t.hasSpecial ? Object.fromEntries(range(t.specialMin, t.specialMax).map(n => [n, 0])) : null;
      for (const ky of resultOrder) {
        const draw = resultMap[ky];
        if (!draw) continue;
        for (const n of draw.main) freqMain[n]++;
        if (t.hasSpecial && Number.isInteger(draw.special)) freqSpecial[draw.special]++;
      }
      return { freqMain, freqSpecial };
    }

    function sortPairs(freqObj) {
      return Object.entries(freqObj)
        .map(([num, count]) => ({ num: Number(num), count }))
        .sort((a, b) => b.count - a.count || a.num - b.num);
    }

    function unhitList(freqObj) {
      return Object.entries(freqObj).filter(([, c]) => c === 0).map(([n]) => Number(n));
    }

    const statsPickBtn = document.getElementById("statsPickBtn");
    if (statsPickBtn) statsPickBtn.onclick = () => {
      const type = document.getElementById("sType").value;
      const mode = document.getElementById("sMode").value;
      const out = document.getElementById("statsPickOut");
      if (!ensurePickMin(type, out, "In Số (chưa chọn / chọn nhiều nhất)", 3)) return;
      const t = TYPES[type];
      const { freqMain, freqSpecial } = countFreqFromPicks(type);
      const unpickedMain = unhitList(freqMain);
      const rankedMain = sortPairs(freqMain);
      let text = "";
      if (mode === "1") text = `6 số chưa được chọn: ${unpickedMain.slice(0, 6).join(", ") || "(rỗng)"}`;
      else if (mode === "2") text = `Tất cả số chưa được chọn (${unpickedMain.length} số): ${unpickedMain.join(", ") || "(rỗng)"}`;
      else if (mode === "3") text = `Top 6 số chọn nhiều nhất: ${rankedMain.slice(0, 6).map(p => `${p.num}(${p.count})`).join(", ")}`;
      else text = `Tất cả số chọn nhiều nhất (${rankedMain.length} số): ${rankedMain.map(p => `${p.num}(${p.count})`).join(", ")}`;

      if (t.hasSpecial) {
        const unpickedDb = unhitList(freqSpecial);
        const rankedDb = sortPairs(freqSpecial);
        text += `\n\nĐB chưa được chọn: ${unpickedDb.join(", ") || "(rỗng)"}`;
        text += `\nSố ĐB chọn nhiều nhất: ${rankedDb.map(p => `${p.num}(${p.count})`).join(", ") || "(rỗng)"}`;
      }
      line(out, text);
    };

    const statsOutBtn = document.getElementById("statsOutBtn");
    if (statsOutBtn) statsOutBtn.onclick = async () => {
      const type = document.getElementById("oType").value;
      const mode = document.getElementById("oMode").value;
      const out = document.getElementById("statsOutOut");
      if (!await ensureResultOnly(type, out, "In kết quả (chưa trúng / trúng nhiều nhất)")) return;
      const t = TYPES[type];
      const dataset = buildPredictionResultDataset(type);
      const { freqMain, freqSpecial } = countFreqFromResults(type, dataset);
      const unhitMain = unhitList(freqMain);
      const rankedMain = sortPairs(freqMain);
      let text = `(${dataset.sourceText || "Dựa vào tất cả dữ liệu KQ hiện có"})\n\n`;
      if (mode === "1") text += `6 số chưa trúng: ${unhitMain.slice(0, 6).join(", ") || "(rỗng)"}`;
      else if (mode === "2") text += `Tất cả số chưa trúng (${unhitMain.length} số): ${unhitMain.join(", ") || "(rỗng)"}`;
      else if (mode === "3") text += `Top 6 số trúng nhiều nhất: ${rankedMain.slice(0, 6).map(p => `${p.num}(${p.count})`).join(", ")}`;
      else text += `Tất cả số trúng nhiều nhất (${rankedMain.length} số): ${rankedMain.map(p => `${p.num}(${p.count})`).join(", ")}`;

      if (t.hasSpecial) {
        const rankedDb = sortPairs(freqSpecial);
        if (type === "LOTO_5_35") {
          const unhitDb = unhitList(freqSpecial);
          text += `\n\nĐB chưa trúng: ${unhitDb.join(", ") || "(rỗng)"}`;
        }
        text += `\nSố ĐB trúng nhiều nhất: ${rankedDb.map(p => `${p.num}(${p.count})`).join(", ") || "(rỗng)"}`;
      }
      line(out, text);
    };

    function pickRandomDistinct(nums, count) {
      const arr = [...nums];
      const out = [];
      while (arr.length && out.length < count) {
        const i = Math.floor(Math.random() * arr.length);
        out.push(arr[i]);
        arr.splice(i, 1);
      }
      return out;
    }

    function buildCandidateScores(type, candidates, freqMap, recentSet = new Set(), isSpecial = false) {
      const t = TYPES[type];
      const min = isSpecial ? t.specialMin : t.mainMin;
      const max = isSpecial ? t.specialMax : t.mainMax;
      const safeCandidates = Array.isArray(candidates) ? candidates.filter(Number.isFinite) : [];
      const maxFreq = Math.max(1, ...safeCandidates.map(number => Number(freqMap?.[number] || 0)));
      const scores = {};

      safeCandidates.forEach(number => {
        const freqNorm = clamp01(Number(freqMap?.[number] || 0) / maxFreq);
        const coldNorm = 1 - freqNorm;
        const pos = (number - min) / Math.max(1, (max - min));
        const centerNorm = 1 - Math.abs((pos * 2) - 1);
        const recentPenalty = recentSet?.has(number) ? 0.42 : 0;
        const score = (freqNorm * 0.52) + (coldNorm * 0.28) + (centerNorm * 0.20) - recentPenalty;
        scores[number] = Math.max(0.02, Number(score.toFixed(6)));
      });

      return scores;
    }

    function pickWeightedDistinctByScore(candidates, scoreMap, count, options = {}) {
      const minDistance = Math.max(0, Number(options?.minDistance || 0));
      const targetCount = Math.max(0, Math.floor(Number(count || 0)));
      const pool = Array.from(new Set((Array.isArray(candidates) ? candidates : []).filter(Number.isFinite)));
      const picked = [];

      while (pool.length && picked.length < targetCount) {
        let eligible = pool.filter(number =>
          !picked.includes(number) &&
          (minDistance <= 0 || picked.every(existing => Math.abs(existing - number) >= minDistance))
        );
        if (!eligible.length) {
          eligible = pool.filter(number => !picked.includes(number));
        }
        if (!eligible.length) break;

        const weighted = eligible.map(number => ({
          number,
          weight: Math.max(0.001, Number(scoreMap?.[number] || 0.001))
        }));
        const totalWeight = weighted.reduce((sum, entry) => sum + entry.weight, 0);
        let randomValue = Math.random() * Math.max(totalWeight, 0.001);
        let chosen = weighted[weighted.length - 1]?.number;

        for (const entry of weighted) {
          randomValue -= entry.weight;
          if (randomValue <= 0) {
            chosen = entry.number;
            break;
          }
        }

        if (!Number.isFinite(chosen)) break;
        picked.push(chosen);
        const index = pool.indexOf(chosen);
        if (index >= 0) pool.splice(index, 1);
      }

      return picked;
    }

    function getSortedResultDraws(type, dataset = null) {
      const resultOrder = dataset?.order || store.resultOrder[type] || [];
      const resultMap = dataset?.results || store.results[type] || {};
      const keys = [...resultOrder].sort((a, b) => kySortValue(a) - kySortValue(b));
      return keys
        .map(ky => ({ ky, draw: resultMap[ky] }))
        .filter(x => x.draw);
    }

    function clamp01(v) {
      return Math.max(0, Math.min(1, v));
    }

    function parsePredictRecentWindowValue(rawValue) {
      const normalized = String(rawValue ?? "").trim().toLowerCase();
      const parsed = Number(normalized || "0");
      return Number.isInteger(parsed) ? parsed : NaN;
    }

    function isPredictRecentWindowDisabled(recentCount) {
      return recentCount === 0;
    }

    function getRecentResultExclusionsFromEntries(type, entries, recentCount) {
      const t = TYPES[type];
      if (isPredictRecentWindowDisabled(recentCount)) {
        return { mode: "none", keys: [], mainSet: new Set(), specialSet: new Set() };
      }
      const n = Math.max(0, recentCount);
      const recentEntries = n === 0 ? [] : entries.slice(-n);
      const keys = recentEntries.map(entry => entry.ky);
      const mainSet = new Set();
      const specialSet = new Set();
      for (const entry of recentEntries) {
        for (const number of (entry.draw?.main || [])) mainSet.add(number);
        if (t.hasSpecial && Number.isInteger(entry.draw?.special)) specialSet.add(entry.draw.special);
      }
      return { mode: "count", keys, mainSet, specialSet };
    }

    function getRecentResultExclusions(type, recentCount, dataset = null) {
      const entries = getSortedResultDraws(type, dataset);
      return getRecentResultExclusionsFromEntries(type, entries, recentCount);
    }

    function buildPairKey(a, b) {
      return a < b ? `${a}-${b}` : `${b}-${a}`;
    }

    function buildPredictionStatsFromEntries(type, entries) {
      const t = TYPES[type];
      const mainNumbers = range(t.mainMin, t.mainMax);
      const specialNumbers = t.hasSpecial ? range(t.specialMin, t.specialMax) : [];
      const recentShortEntries = entries.slice(-12);
      const recentLongEntries = entries.slice(-24);
      const stats = {
        drawCount: entries.length,
        mainFreqAll: Object.fromEntries(mainNumbers.map(n => [n, 0])),
        mainFreqRecentShort: Object.fromEntries(mainNumbers.map(n => [n, 0])),
        mainFreqRecentLong: Object.fromEntries(mainNumbers.map(n => [n, 0])),
        mainLastSeen: Object.fromEntries(mainNumbers.map(n => [n, -1])),
        specialFreqAll: t.hasSpecial ? Object.fromEntries(specialNumbers.map(n => [n, 0])) : null,
        specialFreqRecentShort: t.hasSpecial ? Object.fromEntries(specialNumbers.map(n => [n, 0])) : null,
        specialFreqRecentLong: t.hasSpecial ? Object.fromEntries(specialNumbers.map(n => [n, 0])) : null,
        specialLastSeen: t.hasSpecial ? Object.fromEntries(specialNumbers.map(n => [n, -1])) : null,
        pairCounts: new Map(),
        maxPairCount: 1,
      };

      entries.forEach((entry, idx) => {
        const main = [...(entry.draw?.main || [])].sort((a, b) => a - b);
        main.forEach(number => {
          stats.mainFreqAll[number] += 1;
          stats.mainLastSeen[number] = idx;
        });
        for (let i = 0; i < main.length; i++) {
          for (let j = i + 1; j < main.length; j++) {
            const key = buildPairKey(main[i], main[j]);
            const nextCount = Number(stats.pairCounts.get(key) || 0) + 1;
            stats.pairCounts.set(key, nextCount);
            if (nextCount > stats.maxPairCount) stats.maxPairCount = nextCount;
          }
        }
        if (t.hasSpecial && Number.isInteger(entry.draw?.special)) {
          stats.specialFreqAll[entry.draw.special] += 1;
          stats.specialLastSeen[entry.draw.special] = idx;
        }
      });

      recentShortEntries.forEach(entry => {
        for (const number of (entry.draw?.main || [])) stats.mainFreqRecentShort[number] += 1;
        if (t.hasSpecial && Number.isInteger(entry.draw?.special)) stats.specialFreqRecentShort[entry.draw.special] += 1;
      });

      recentLongEntries.forEach(entry => {
        for (const number of (entry.draw?.main || [])) stats.mainFreqRecentLong[number] += 1;
        if (t.hasSpecial && Number.isInteger(entry.draw?.special)) stats.specialFreqRecentLong[entry.draw.special] += 1;
      });

      return stats;
    }

    function getLotteryPredictionStrategies(type) {
      const specialHeavy = type === "LOTO_5_35";
      return [
        {
          key: "balanced",
          label: "Cân bằng có độ trễ",
          main: { global: 0.15, recentShort: 0.12, recentLong: 0.18, overdue: 0.24, cold: 0.08, pair: 0.11, center: 0.04, structure: 0.08, recentPenalty: 0.34, usagePenalty: 0.18 },
          special: { global: 0.20, recentShort: 0.16, recentLong: 0.22, overdue: 0.18, cold: 0.10, pair: 0, center: 0.06, structure: 0, recentPenalty: specialHeavy ? 0.38 : 0.26, usagePenalty: 0.12 },
        },
        {
          key: "momentum",
          label: "Động lực gần",
          main: { global: 0.20, recentShort: 0.26, recentLong: 0.20, overdue: 0.08, cold: 0.03, pair: 0.12, center: 0.03, structure: 0.08, recentPenalty: 0.20, usagePenalty: 0.18 },
          special: { global: 0.22, recentShort: 0.24, recentLong: 0.22, overdue: 0.08, cold: 0.04, pair: 0, center: 0.05, structure: 0, recentPenalty: specialHeavy ? 0.24 : 0.16, usagePenalty: 0.12 },
        },
        {
          key: "overdue",
          label: "Độ trễ kiểm soát",
          main: { global: 0.07, recentShort: 0.06, recentLong: 0.10, overdue: 0.39, cold: 0.18, pair: 0.10, center: 0.02, structure: 0.08, recentPenalty: 0.42, usagePenalty: 0.20 },
          special: { global: 0.08, recentShort: 0.10, recentLong: 0.14, overdue: 0.34, cold: 0.20, pair: 0, center: 0.05, structure: 0, recentPenalty: specialHeavy ? 0.34 : 0.20, usagePenalty: 0.12 },
        },
        {
          key: "pairs",
          label: "Tần suất và cặp số",
          main: { global: 0.24, recentShort: 0.14, recentLong: 0.18, overdue: 0.08, cold: 0.04, pair: 0.18, center: 0.03, structure: 0.07, recentPenalty: 0.18, usagePenalty: 0.16 },
          special: { global: 0.26, recentShort: 0.18, recentLong: 0.22, overdue: 0.10, cold: 0.05, pair: 0, center: 0.05, structure: 0, recentPenalty: specialHeavy ? 0.24 : 0.16, usagePenalty: 0.12 },
        }
      ];
    }

    function buildNumberUsageMap(tickets, kind = "main") {
      const usage = {};
      for (const ticket of tickets) {
        if (kind === "special") {
          if (Number.isInteger(ticket?.special)) usage[ticket.special] = Number(usage[ticket.special] || 0) + 1;
          continue;
        }
        for (const number of (ticket?.main || [])) {
          usage[number] = Number(usage[number] || 0) + 1;
        }
      }
      return usage;
    }

    function buildStructureBalanceScore(type, selectedNumbers) {
      if (!selectedNumbers.length) return 0.5;
      const t = TYPES[type];
      const ordered = [...selectedNumbers].sort((a, b) => a - b);
      const midpoint = (t.mainMin + t.mainMax) / 2;
      const oddCount = ordered.filter(number => number % 2 !== 0).length;
      const lowCount = ordered.filter(number => number <= midpoint).length;
      const oddTarget = ordered.length / 2;
      const lowTarget = ordered.length / 2;
      const oddScore = 1 - Math.abs(oddCount - oddTarget) / Math.max(1, ordered.length);
      const lowScore = 1 - Math.abs(lowCount - lowTarget) / Math.max(1, ordered.length);
      const spread = ordered.length >= 2
        ? (ordered[ordered.length - 1] - ordered[0]) / Math.max(1, (t.mainMax - t.mainMin))
        : 0.45;
      const spreadScore = ordered.length >= 2 ? clamp01(spread * 1.15) : 0.45;
      return (oddScore * 0.38) + (lowScore * 0.38) + (spreadScore * 0.24);
    }

    function buildPredictionContext(type, historyEntries, strategy, recentCount) {
      const t = TYPES[type];
      const stats = buildPredictionStatsFromEntries(type, historyEntries);
      const recent = getRecentResultExclusionsFromEntries(type, historyEntries, recentCount);
      const allMainCandidates = range(t.mainMin, t.mainMax);
      const allSpecialCandidates = t.hasSpecial ? range(t.specialMin, t.specialMax) : [];
      const filteredMainCandidates = allMainCandidates.filter(number => !recent.mainSet.has(number));
      const filteredSpecialCandidates = allSpecialCandidates.filter(number => !recent.specialSet.has(number));
      return {
        type,
        t,
        strategy,
        stats,
        recent,
        historyEntries,
        mainCandidates: filteredMainCandidates.length >= t.mainCount ? filteredMainCandidates : allMainCandidates,
        specialCandidates: t.hasSpecial ? (filteredSpecialCandidates.length ? filteredSpecialCandidates : allSpecialCandidates) : [],
      };
    }

    function scorePredictionCandidate(context, candidate, options = {}) {
      const isSpecial = !!options.isSpecial;
      const selected = options.selected || [];
      const usageMap = options.usageMap || {};
      const usageCount = Number(usageMap[candidate] || 0);
      const bundleIndex = Number(options.bundleIndex || 0);
      const weights = isSpecial ? context.strategy.special : context.strategy.main;
      const min = isSpecial ? context.t.specialMin : context.t.mainMin;
      const max = isSpecial ? context.t.specialMax : context.t.mainMax;
      const freqAll = isSpecial ? context.stats.specialFreqAll : context.stats.mainFreqAll;
      const freqRecentShort = isSpecial ? context.stats.specialFreqRecentShort : context.stats.mainFreqRecentShort;
      const freqRecentLong = isSpecial ? context.stats.specialFreqRecentLong : context.stats.mainFreqRecentLong;
      const lastSeen = isSpecial ? context.stats.specialLastSeen : context.stats.mainLastSeen;
      const recentSet = isSpecial ? context.recent.specialSet : context.recent.mainSet;
      const candidates = isSpecial ? context.specialCandidates : context.mainCandidates;
      const maxAll = Math.max(1, ...candidates.map(number => Number(freqAll?.[number] || 0)));
      const maxRecentShort = Math.max(1, ...candidates.map(number => Number(freqRecentShort?.[number] || 0)));
      const maxRecentLong = Math.max(1, ...candidates.map(number => Number(freqRecentLong?.[number] || 0)));
      const globalFreqNorm = clamp01(Number(freqAll?.[candidate] || 0) / maxAll);
      const recentShortNorm = clamp01(Number(freqRecentShort?.[candidate] || 0) / maxRecentShort);
      const recentLongNorm = clamp01(Number(freqRecentLong?.[candidate] || 0) / maxRecentLong);
      const coldNorm = 1 - globalFreqNorm;
      const gap = Number(lastSeen?.[candidate] ?? -1) < 0
        ? context.stats.drawCount
        : Math.max(0, context.stats.drawCount - 1 - Number(lastSeen[candidate] || 0));
      const overdueNorm = context.stats.drawCount <= 1 ? 0.5 : clamp01(gap / context.stats.drawCount);
      const pos = (candidate - min) / Math.max(1, (max - min));
      const centerNorm = 1 - Math.abs((pos * 2) - 1);
      let pairNorm = 0;
      if (!isSpecial && selected.length) {
        const pairScore = selected.reduce((sum, picked) => sum + Number(context.stats.pairCounts.get(buildPairKey(picked, candidate)) || 0), 0);
        pairNorm = clamp01((pairScore / selected.length) / Math.max(1, context.stats.maxPairCount));
      }
      const structureNorm = !isSpecial ? buildStructureBalanceScore(context.type, [...selected, candidate]) : 0;
      const recentPenalty = recentSet.has(candidate) ? 1 : 0;

      return (
        (weights.global * globalFreqNorm) +
        (weights.recentShort * recentShortNorm) +
        (weights.recentLong * recentLongNorm) +
        (weights.overdue * overdueNorm) +
        (weights.cold * coldNorm) +
        (weights.pair * pairNorm) +
        (weights.center * centerNorm) +
        (weights.structure * structureNorm) -
        (weights.recentPenalty * recentPenalty) -
        (weights.usagePenalty * usageCount) -
        (bundleIndex * usageCount * 0.015)
      );
    }

    function rankPredictionCandidates(context, options = {}) {
      const isSpecial = !!options.isSpecial;
      const candidates = isSpecial ? context.specialCandidates : context.mainCandidates;
      const selected = options.selected || [];
      const usageMap = options.usageMap || {};
      const bundleIndex = Number(options.bundleIndex || 0);
      return candidates
        .map(number => ({
          number,
          score: scorePredictionCandidate(context, number, { isSpecial, selected, usageMap, bundleIndex })
        }))
        .sort((a, b) => b.score - a.score || a.number - b.number);
    }

    function buildOptimizedPredictionTicket(context, existingTickets = []) {
      const mainUsage = buildNumberUsageMap(existingTickets, "main");
      const main = [];
      while (main.length < context.t.mainCount) {
        const ranked = rankPredictionCandidates(context, {
          selected: main,
          usageMap: mainUsage,
          bundleIndex: existingTickets.length,
        });
        const chosen = ranked.find(item => !main.includes(item.number));
        if (!chosen) break;
        main.push(chosen.number);
      }
      main.sort((a, b) => a - b);

      let special = null;
      if (context.t.hasSpecial) {
        const specialUsage = buildNumberUsageMap(existingTickets, "special");
        const rankedSpecial = rankPredictionCandidates(context, {
          isSpecial: true,
          usageMap: specialUsage,
          bundleIndex: existingTickets.length,
        });
        special = rankedSpecial[0]?.number ?? context.t.specialMin;
      }

      return { main, special };
    }

    function getPredictionHitThreshold(type) {
      if (TYPES[type]?.threeDigit) return 1;
      return type === "LOTO_5_35" ? 3 : 3;
    }

    function getResolvedPredictionLogStats(type) {
      if (!PREDICTION_LOG_TYPES.includes(type)) return { byStrategy: {}, recentResolved: [] };
      const logs = ensurePredictionLogBucket(type)
        .filter(entry => entry?.resolved && entry?.resultSummary && entry?.strategyKey)
        .sort((a, b) => Date.parse(a.resolvedAt || a.createdAt || 0) - Date.parse(b.resolvedAt || b.createdAt || 0));
      const recentResolved = logs.slice(-24);
      const byStrategy = {};
      for (const entry of recentResolved) {
        const key = String(entry.strategyKey || "");
        if (!key) continue;
        if (!byStrategy[key]) {
          byStrategy[key] = {
            strategyKey: key,
            strategyLabel: String(entry.strategyLabel || key),
            count: 0,
            bestMainHitsTotal: 0,
            avgMainHitsTotal: 0,
            thresholdLogHits: 0,
            prizeLogHits: 0,
            specialLogHits: 0,
            lastResolvedAt: "",
          };
        }
        const target = byStrategy[key];
        target.count += 1;
        target.bestMainHitsTotal += Number(entry.resultSummary.bestMainHits || 0);
        target.avgMainHitsTotal += Number(entry.resultSummary.avgMainHits || 0);
        if (Number(entry.resultSummary.thresholdTicketHits || 0) > 0) target.thresholdLogHits += 1;
        if (Number(entry.resultSummary.prizeTicketHits || 0) > 0) target.prizeLogHits += 1;
        if (Number(entry.resultSummary.specialHits || 0) > 0) target.specialLogHits += 1;
        target.lastResolvedAt = entry.resolvedAt || entry.createdAt || target.lastResolvedAt;
      }
      for (const value of Object.values(byStrategy)) {
        value.avgBestMainHits = value.count ? (value.bestMainHitsTotal / value.count) : 0;
        value.avgMainHits = value.count ? (value.avgMainHitsTotal / value.count) : 0;
        value.thresholdRate = value.count ? (value.thresholdLogHits / value.count) : 0;
        value.prizeRate = value.count ? (value.prizeLogHits / value.count) : 0;
        value.specialRate = value.count ? (value.specialLogHits / value.count) : 0;
        value.composite = value.avgBestMainHits + (value.thresholdRate * 0.72) + (value.prizeRate * 0.95) + (value.specialRate * 0.24);
      }
      return { byStrategy, recentResolved };
    }

    function evaluatePredictionStrategy(type, dataset, strategy, recentCount) {
      const t = TYPES[type];
      const draws = getSortedResultDraws(type, dataset);
      const minHistory = Math.max(18, t.mainCount * 4);
      const startIndex = Math.max(minHistory, draws.length - 36);
      let tested = 0;
      let totalMainHits = 0;
      let totalSpecialHits = 0;
      let thresholdHits = 0;
      let prizeHits = 0;

      for (let index = startIndex; index < draws.length; index++) {
        const historyEntries = draws.slice(0, index);
        if (historyEntries.length < minHistory) continue;
        const context = buildPredictionContext(type, historyEntries, strategy, recentCount);
        const ticket = buildOptimizedPredictionTicket(context, []);
        if ((ticket.main || []).length !== t.mainCount) continue;
        const actual = draws[index].draw;
        const mainHits = countMainMatch(ticket.main, actual.main);
        const specialHit = t.hasSpecial && Number.isInteger(ticket.special) && ticket.special === actual.special ? 1 : 0;
        const prize = evalPrize(type, ticket, actual);
        tested += 1;
        totalMainHits += mainHits;
        totalSpecialHits += specialHit;
        if (mainHits >= getPredictionHitThreshold(type)) thresholdHits += 1;
        if (prize) prizeHits += 1;
      }

      if (!tested) {
        return {
          strategy,
          tested: 0,
          avgMainHits: 0,
          avgMainHitRate: 0,
          specialHitRate: 0,
          thresholdHitRate: 0,
          prizeHitRate: 0,
          composite: 0,
        };
      }

      const avgMainHits = totalMainHits / tested;
      const thresholdHitRate = thresholdHits / tested;
      const specialHitRate = t.hasSpecial ? totalSpecialHits / tested : 0;
      const prizeHitRate = prizeHits / tested;
      const composite = avgMainHits + (thresholdHitRate * 0.72) + (prizeHitRate * 0.90) + (specialHitRate * 0.26);

      return {
        strategy,
        tested,
        avgMainHits,
        avgMainHitRate: avgMainHits / t.mainCount,
        specialHitRate,
        thresholdHitRate,
        prizeHitRate,
        composite,
      };
    }

    function optimizeLotteryPrediction(type, dataset, bundleCount, recentCount) {
      const draws = getSortedResultDraws(type, dataset);
      const strategies = getLotteryPredictionStrategies(type);
      const liveLogStats = getResolvedPredictionLogStats(type);
      const evaluations = strategies
        .map(strategy => {
          const base = evaluatePredictionStrategy(type, dataset, strategy, recentCount);
          const live = liveLogStats.byStrategy[strategy.key] || null;
          const liveWeight = live ? Math.min(0.65, live.count / 12) : 0;
          return {
            ...base,
            live,
            blendedComposite: base.composite + ((live?.composite || 0) * liveWeight),
          };
        })
        .sort((a, b) => b.blendedComposite - a.blendedComposite || b.prizeHitRate - a.prizeHitRate || b.avgMainHits - a.avgMainHits);
      const best = evaluations[0] || { strategy: strategies[0], tested: 0, avgMainHits: 0, thresholdHitRate: 0, prizeHitRate: 0, specialHitRate: 0 };
      const context = buildPredictionContext(type, draws, best.strategy, recentCount);
      const rankingRule = getPredictionTopRankingRule(type);
      const rawTopMainRanking = rankPredictionCandidates(context)
        .slice(0, Math.min(rankingRule?.mainMax || 20, context.mainCandidates.length))
        .map(item => item.number);
      const rawTopSpecialRanking = rankingRule?.specialMax
        ? rankPredictionCandidates(context, { isSpecial: true })
            .slice(0, context.specialCandidates.length)
            .map(item => item.number)
        : [];
      const tickets = [];
      for (let index = 0; index < bundleCount; index++) {
        let ticket = buildOptimizedPredictionTicket(context, tickets);
        let retry = 0;
        while (
          retry < 5 &&
          tickets.some(existing =>
            String(existing?.main || []) === String(ticket?.main || []) &&
            Number(existing?.special ?? -1) === Number(ticket?.special ?? -1)
          )
        ) {
          ticket = buildOptimizedPredictionTicket(context, [...tickets, ticket]);
          retry += 1;
        }
        tickets.push(ticket);
      }
      const normalizedRankings = normalizePredictionTopRankings(type, rawTopMainRanking, rawTopSpecialRanking, tickets);
      return {
        best,
        evaluations,
        tickets,
        topMainRanking: normalizedRankings.main,
        topSpecialRanking: normalizedRankings.special,
        recentKeys: context.recent.keys,
        drawCount: draws.length,
        lastEntry: draws[draws.length - 1] || null,
        liveLogStats,
      };
    }

    function formatPredictNumber(number, type = "") {
      const normalizedType = String(type || "").trim().toUpperCase();
      const width = TYPES[normalizedType]?.threeDigit ? 3 : 2;
      return String(Number(number) || 0).padStart(width, "0");
    }

    function formatPredictNumberList(numbers, type = "") {
      return (numbers || []).map(number => formatPredictNumber(number, type)).join(", ");
    }

    function formatPredictNumberRows(numbers, type = "", perRow = 10) {
      const tokens = (Array.isArray(numbers) ? numbers : [])
        .map(value => Number(value))
        .filter(Number.isFinite)
        .map(value => formatPredictNumber(value, type));
      const rows = [];
      for (let index = 0; index < tokens.length; index += perRow) {
        rows.push(tokens.slice(index, index + perRow).join(", "));
      }
      return rows;
    }

    function formatOptimizedPredictionText(type, optimized, recentCount, sourceText) {
      const t = TYPES[type];
      const lines = [];
      if (sourceText) lines.push(sourceText);
      if (isPredictRecentWindowDisabled(recentCount)) {
        lines.push(
          `Dự đoán tối ưu bằng backtest ${optimized.best.tested || 0} kỳ, không loại số theo kỳ gần nhất.`
        );
      } else {
        lines.push(
          `Dự đoán tối ưu bằng backtest ${optimized.best.tested || 0} kỳ, loại bỏ số xuất hiện trong ${Math.min(recentCount, optimized.recentKeys.length)} kỳ gần nhất (${optimized.recentKeys.length ? optimized.recentKeys.join(", ") : "chưa có kỳ"}).`
        );
      }
      lines.push(`Chiến lược tốt nhất: ${optimized.best.strategy.label}`);
      lines.push(
        `Backtest: TB trùng ${optimized.best.avgMainHits.toFixed(2)} số/kỳ | Tỷ lệ đạt ${getPredictionHitThreshold(type)}+ số: ${(optimized.best.thresholdHitRate * 100).toFixed(2)}% | Tỷ lệ có giải: ${(optimized.best.prizeHitRate * 100).toFixed(2)}%`
      );
      if (optimized.best.live?.count) {
        lines.push(
          `Log thực tế gần đây: ${optimized.best.live.count} kỳ đã chấm | TB tốt nhất ${optimized.best.live.avgBestMainHits.toFixed(2)} số/kỳ | Tỷ lệ có giải ${(optimized.best.live.prizeRate * 100).toFixed(2)}%`
        );
      }
      lines.push(`Top ${optimized.topMainRanking.length} số ưu tiên: ${formatPredictNumberList(optimized.topMainRanking, type)}`);
      if (t.hasSpecial) {
        lines.push(`Top ${optimized.topSpecialRanking.length} số ĐB ưu tiên: ${formatPredictNumberList(optimized.topSpecialRanking, type)}`);
      }
      optimized.tickets.forEach((ticket, index) => {
        if (t.hasSpecial) {
          if (type === "LOTO_5_35") lines.push(`Kết quả dự đoán #${index + 1}: 6 số (5+1): ${formatPredictNumberList(ticket.main, type)} | ĐB ${formatPredictNumber(ticket.special, type)}`);
          else lines.push(`Kết quả dự đoán #${index + 1}: ${formatPredictNumberList(ticket.main, type)} | ĐB ${formatPredictNumber(ticket.special, type)}`);
        } else {
          lines.push(`Kết quả dự đoán #${index + 1}: ${formatPredictNumberList(ticket.main, type)}`);
        }
      });
      return lines.join("\n\n");
    }

    function normalizePredictionErrorDetail(...values) {
      const unique = new Map();
      values
        .flatMap(value => String(value?.message || value || "").split("|"))
        .map(message => message
          .replace(/^Không thể dự đoán(?:\s+Vip)?(?:\s+bằng AI backend)?\s*:\s*/i, "")
          .trim())
        .filter(Boolean)
        .forEach(message => {
          const kenoLimit = message.match(/^Số bộ Keno tối đa cho bậc (\d+) là (\d+)(?:\s+bộ)?\.?$/i);
          const normalized = kenoLimit
            ? `Số bộ Keno tối đa cho bậc ${kenoLimit[1]} là ${kenoLimit[2]} Bộ.`
            : `${message.replace(/[.\s]+$/, "")}.`;
          const key = normalized.toLocaleLowerCase("vi-VN");
          if (!unique.has(key)) unique.set(key, normalized);
        });
      return [...unique.values()].join(" | ") || "Đã xảy ra lỗi không xác định.";
    }

    function formatPredictionFailure(error, prefix = "Không thể dự đoán") {
      return `${prefix} ${normalizePredictionErrorDetail(error)}`;
    }

    async function runPredictFlow({
      type,
      count,
      kenoLevel = 0,
      engineKey = null,
      triggerMode = "manual",
      triggerSourceResolvedKy = "",
    } = {}) {
      const out = document.getElementById("predictOut");
      const t = TYPES[type];
      if (predictFlowBusy) {
        if (triggerMode === "manual") line(out, "Hệ thống đang chạy một lượt dự đoán khác, bạn đợi xong rồi thử lại nhé.", "warn");
        return null;
      }
      if (!t) {
        line(out, "Loại dự đoán không hợp lệ.", "warn");
        return null;
      }
      predictFlowBusy = true;
      try {
      normalizePredictRecentWindowSelection();
      const recentCount = parsePredictRecentWindowValue(document.getElementById("pdRecentWindow").value);
      let c = Number(count || 0);
      const activePlayMode = String(predictPlayModeValue || "normal").trim().toLowerCase() === "bao" ? "bao" : "normal";
      const activeBaoLevel = Number(predictBaoLevelValue || 0);
      const aiEngine = String(engineKey || predictEngineValue || "both").trim().toLowerCase() || "both";
      const activeRiskMode = aiEngine === "both" ? normalizePredictRiskMode(predictRiskModeValue) : "balanced";
      const activeRiskModeMeta = getPredictRiskModeMeta(activeRiskMode);
      const engineMeta = getPredictEngineMeta(aiEngine);
      if (!Number.isInteger(c) || c <= 0) {
        line(out, "Số bộ dự đoán không hợp lệ.", "warn");
        return null;
      }
      const normalizedKenoLevel = t.keno ? Number(kenoLevel || 0) : 0;
      const bundleLimit = getPredictBundleLimit(type, normalizedKenoLevel);
      if (c > bundleLimit) c = bundleLimit;
      const predictCountPerTicket = t.keno ? normalizedKenoLevel : t.mainCount;
      if (AI_PREDICT_TYPES.has(type)) {
        if (t.keno && (!Number.isInteger(normalizedKenoLevel) || normalizedKenoLevel < 1 || normalizedKenoLevel > 10)) {
          out.classList.remove("muted");
          line(out, "Bậc Keno không hợp lệ (1-10).", "warn");
          return null;
        }
        if (!engineMeta.available) {
          out.classList.remove("muted");
          line(out, engineMeta.description || "Engine này chưa sẵn sàng.", "warn");
          return null;
        }
        out.classList.add("muted");
        startPredictLoading(out, engineMeta.key, engineMeta.label);
        const predictStartedAt = Date.now();
        try {
          let result;
          if (engineMeta.key === "both") {
            const [luanSoSettled, aiGenSettled] = await Promise.allSettled([
              predictWithAiBackend(type, c, normalizedKenoLevel, "luan_so", activeRiskMode, PREDICTION_MODE_NORMAL),
              predictWithAiBackend(type, c, normalizedKenoLevel, "gen_local", activeRiskMode, PREDICTION_MODE_NORMAL),
            ]);
            const luanSoResult = luanSoSettled?.status === "fulfilled" ? luanSoSettled.value : null;
            const aiGenResult = aiGenSettled?.status === "fulfilled" ? aiGenSettled.value : null;
            if (!luanSoResult && !aiGenResult) {
              throw new Error(normalizePredictionErrorDetail(
                luanSoSettled?.reason || "Luận Số lỗi",
                aiGenSettled?.reason || "AI Gen lỗi",
              ));
            }
            result = mergeBothAiResults(type, c, luanSoResult, aiGenResult, activeRiskMode);
          } else {
            result = await predictWithAiBackend(type, c, normalizedKenoLevel, engineMeta.backendEngine || "gen_local", activeRiskMode, PREDICTION_MODE_NORMAL);
          }
          result = normalizePredictionResultTopRankings(result, type);
          if (activePlayMode === "bao" && !t.keno) {
            const baoTickets = buildBaoPredictionTickets(
              type,
              c,
              activeBaoLevel,
              Array.isArray(result?.topRanking) ? result.topRanking : [],
              Array.isArray(result?.topSpecialRanking) ? result.topSpecialRanking : [],
              Array.isArray(result?.tickets) ? result.tickets : []
            );
            if (baoTickets.length) {
              result = {
                ...result,
                tickets: baoTickets,
              };
            }
          }
          const predictionCreatedAt = getSyncedIsoString();
          let displayResult = {
            ...result,
            createdAt: predictionCreatedAt,
            engine: engineMeta.key,
            engineKey: engineMeta.key,
            engineLabel: engineMeta.label,
            riskMode: activeRiskMode,
            riskModeLabel: activeRiskModeMeta.label,
            riskModeSummary: activeRiskModeMeta.summary,
            playMode: activePlayMode,
            baoLevel: activePlayMode === "bao" ? activeBaoLevel : null,
            pickSize: t.keno ? normalizedKenoLevel : 0,
            predictionMode: PREDICTION_MODE_NORMAL,
            vipProfile: "",
          };
          if (result?.ready !== false && PREDICTION_LOG_TYPES.includes(type)) {
            if (type === "KENO" && !kenoCsvFeedCacheRestored) restoreKenoCsvFeedCache();
            const predictionDataset = buildPredictionResultDataset(type);
            const latestKyValue = kySortValue(result?.latestKy);
            const predictedKyFromLatest = latestKyValue > 0 ? `#${String(latestKyValue + 1).padStart(4, "0")}` : null;
            const predictedKy = normalizeKy(result?.nextKy) || predictedKyFromLatest || getNextPredictionKy(type, predictionDataset);
            if (predictedKy) {
              upsertPredictionLog(type, {
                createdAt: predictionCreatedAt,
                predictedKy,
                targetDrawAt: String(result?.targetDrawAt || result?.target_draw_at || ""),
                strategyKey: result?.model?.key || "",
                strategyLabel: result?.model?.label || "",
                modelKey: result?.model?.key || "",
                modelLabel: result?.model?.label || "",
                engineKey: engineMeta.key,
                engineLabel: engineMeta.label,
                riskMode: activeRiskMode,
                riskModeLabel: activeRiskModeMeta.label,
                riskModeSummary: activeRiskModeMeta.summary,
                modelVersion: result?.modelVersion || "",
                championKey: result?.champion?.key || result?.model?.key || "",
                championLabel: result?.champion?.label || result?.model?.label || "",
                lastTrainedAt: result?.lastTrainedAt || "",
                confidence: Number(result?.confidence || 0),
                recentCount: 0,
                drawCount: Number(result?.historyCount || 0),
                historyFile: String(result?.historyFile || ""),
                historyCount: Number(result?.historyCount || 0),
                bundleCount: Array.isArray(result?.tickets) ? result.tickets.length : c,
                tickets: Array.isArray(result?.tickets) ? result.tickets : [],
                ticketSources: Array.isArray(result?.ticketSources) ? result.ticketSources : [],
                topMainRanking: Array.isArray(result?.topRanking) ? result.topRanking : [],
                topSpecialRanking: Array.isArray(result?.topSpecialRanking) ? result.topSpecialRanking : [],
                backtest: result?.backtest || null,
                metaSelectionMode: String(result?.metaSelectionMode || ""),
                metaScores: result?.metaScores || null,
                metaQuota: result?.metaQuota || null,
                metaPreferredEngine: String(result?.metaPreferredEngine || ""),
                metaSummary: String(result?.metaSummary || ""),
                triggerMode: String(triggerMode || "manual"),
                triggerSourceResolvedKy: String(triggerSourceResolvedKy || ""),
                playMode: activePlayMode,
                baoLevel: activePlayMode === "bao" ? activeBaoLevel : null,
                pickSize: t.keno ? normalizedKenoLevel : 0,
                stabilityScore: Number((result?.stabilityScore ?? result?.backtest?.stabilityScore) || 0),
                predictionMode: PREDICTION_MODE_NORMAL,
                vipProfile: "",
                predictionId: String(result?.predictionId || ""),
                predictionStatus: String(result?.predictionStatus || ""),
                dataCutoffDrawId: String(result?.dataCutoffDrawId || result?.data_cutoff_draw_id || ""),
                payloadChecksum: String(result?.payloadChecksum || ""),
                modelRole: String(result?.modelRole || result?.champion?.status || "champion"),
                probabilitySummary: result?.probabilitySummary || null,
                calibratedProbability: Array.isArray(result?.calibratedProbability) ? result.calibratedProbability : [],
                specialCalibratedProbability: Array.isArray(result?.specialCalibratedProbability) ? result.specialCalibratedProbability : [],
                ticketQualityScore: Number(result?.ticketQualityScore ?? result?.qualityScore ?? result?.quality_score ?? 0),
              });
              const saved = await saveStore({ reason: `${type.toLowerCase()}_prediction_log` });
              if (!saved) {
                const saveWarning = "Chưa lưu được prediction log vào tài khoản; nếu tải lại trang lúc này thì lịch sử dự đoán có thể không được giữ lại.";
                displayResult = {
                  ...displayResult,
                  storeSaveFailed: true,
                  storeSaveMessage: saveWarning,
                  notes: [saveWarning, ...(Array.isArray(displayResult?.notes) ? displayResult.notes : [])],
                };
                if (type === "KENO" && typeof setKenoPredictStatusMeta === "function") {
                  setKenoPredictStatusMeta(saveWarning, "warn");
                }
              }
            }
          }
          stopPredictLoading(engineMeta.key, Date.now() - predictStartedAt);
          renderPredictOutput(displayResult);
          return displayResult;
        } catch (err) {
          stopPredictLoading(engineMeta.key, Date.now() - predictStartedAt);
          predictLastDisplayResult = null;
          out.classList.remove("muted");
          line(out, formatPredictionFailure(err), "warn");
          return null;
        }
      }
      predictLastDisplayResult = null;
      if (![0, 1, 2, 3, 5].includes(recentCount)) return line(out, "Số kỳ gần nhất không hợp lệ.", "warn");
      if (!t.keno) {
        if (!await ensureResultOnly(type, out, "Dự Đoán Số Kỳ Tới")) return null;
      }
      if (!t.keno && !store.resultOrder[type].length) return line(out, "Chưa có KQ để dự đoán.", "warn");
      if (t.keno && (!Number.isInteger(normalizedKenoLevel) || normalizedKenoLevel < 1 || normalizedKenoLevel > 10)) {
        return line(out, "Bậc Keno không hợp lệ (1-10).", "warn");
      }
      if (t.keno && !store.resultOrder[type].length) {
        const all = range(t.mainMin, t.mainMax);
        const lines = [`Dự đoán Keno bậc ${predictCountPerTicket}: không loại theo KQ, sinh ngẫu nhiên trong dải ${t.mainMin}-${t.mainMax}.`];
        for (let i = 1; i <= c; i++) {
          const main = pickRandomDistinct(all, predictCountPerTicket).sort((a,b)=>a-b);
          lines.push(`Kết quả dự đoán #${i} (Keno bậc ${predictCountPerTicket}):\n${main.join(", ")}`);
        }
        return line(out, lines.join("\n\n"));
      }
      const { freqMain, freqSpecial } = countFreqFromResults(type);
      const { keys: recentKeys, mainSet: recentMainSet, specialSet: recentSpecialSet } = getRecentResultExclusions(type, recentCount);
      const allMainCandidates = range(t.mainMin, t.mainMax);
      const filteredMainCandidates = allMainCandidates.filter(n => !recentMainSet.has(n));
      const usableMainCandidates = filteredMainCandidates.length >= predictCountPerTicket ? filteredMainCandidates : allMainCandidates;
      const mainScores = buildCandidateScores(type, usableMainCandidates, freqMain, recentMainSet, false);

      const lines = [];
      if (isPredictRecentWindowDisabled(recentCount)) {
        lines.push("Dự đoán dựa trên KQ đã nhập, không loại số theo kỳ gần nhất.");
      } else {
        lines.push(`Dự đoán dựa trên KQ đã nhập + loại bỏ số xuất hiện trong ${Math.min(recentCount, recentKeys.length)} kỳ gần nhất (${recentKeys.length ? recentKeys.join(", ") : "chưa có kỳ"}).`);
      }
      if (activePlayMode === "bao" && !t.keno && activeBaoLevel > t.mainCount) {
        const topMainCandidates = usableMainCandidates.slice(0, Math.max(activeBaoLevel + 8, activeBaoLevel * 2));
        const topSpecialCandidates = t.hasSpecial
          ? range(t.specialMin, t.specialMax).filter(n => !recentSpecialSet.has(n)).slice(0, 6)
          : [];
        const baoTickets = buildBaoPredictionTickets(type, c, activeBaoLevel, topMainCandidates, topSpecialCandidates, []);
        baoTickets.forEach((ticket, index) => {
          if (t.hasSpecial && Number.isInteger(ticket.special)) {
            lines.push(`Bộ ${index + 1} • Bao ${ticket.baoLevel}: ${ticket.main.join(", ")} | ĐB ${ticket.special}`);
          } else {
            lines.push(`Bộ ${index + 1} • Bao ${ticket.baoLevel}: ${ticket.main.join(", ")}`);
          }
        });
        line(out, lines.join("\n\n"));
        return baoTickets;
      }
      for (let i = 1; i <= c; i++) {
        let main = pickWeightedDistinctByScore(usableMainCandidates, mainScores, predictCountPerTicket, { minDistance: 2 });
        main = main.slice(0, predictCountPerTicket).sort((a,b)=>a-b);

        if (t.hasSpecial) {
          const allDbCandidates = range(t.specialMin, t.specialMax);
          const filteredDbCandidates = allDbCandidates.filter(n => !recentSpecialSet.has(n));
          const usableDbCandidates = filteredDbCandidates.length ? filteredDbCandidates : allDbCandidates;
          const dbScores = buildCandidateScores(type, usableDbCandidates, freqSpecial, recentSpecialSet, true);
          const [dbPicked] = pickWeightedDistinctByScore(usableDbCandidates, dbScores, 1);
          const db = dbPicked || t.specialMin;
          if (type === "LOTO_5_35") lines.push(`Kết quả dự đoán #${i}: 6 số (5+1): ${main.join(", ")} | ĐB ${db}`);
          else lines.push(`Kết quả dự đoán #${i}: ${main.join(", ")} | ĐB ${db}`);
        } else {
          if (t.keno) lines.push(`Kết quả dự đoán #${i} (Keno bậc ${predictCountPerTicket}):\n${main.join(", ")}`);
          else lines.push(`Kết quả dự đoán #${i}: ${main.join(", ")}`);
        }
      }
      line(out, lines.join("\n\n"));
      if (t.keno) {
        line(out, "Đang đồng bộ và chạy thuật toán Keno...", "muted");
        try {
          const result = await predictKenoWithPython(normalizedKenoLevel, c);
          return line(out, formatKenoPythonPrediction(result));
        } catch (err) {
          predictLastDisplayResult = null;
          return line(out, `Không thể dự đoán Keno từ Test/L1.py: ${err.message}`, "warn");
        }
      }

      const predictionDataset = buildPredictionResultDataset(type);
      if (!predictionDataset.order.length) {
        return line(out, "Chưa có KQ để dự đoán.", "warn");
      }
      const optimized = optimizeLotteryPrediction(type, predictionDataset, c, recentCount);
      const predictedKy = getNextPredictionKy(type, predictionDataset);
      if (predictedKy) {
        upsertPredictionLog(type, {
          predictedKy,
          strategyKey: optimized.best.strategy.key,
          strategyLabel: optimized.best.strategy.label,
          recentCount,
          drawCount: optimized.drawCount,
          bundleCount: optimized.tickets.length,
          tickets: optimized.tickets,
          topMainRanking: optimized.topMainRanking,
          topSpecialRanking: optimized.topSpecialRanking,
          triggerMode: String(triggerMode || "manual"),
          triggerSourceResolvedKy: String(triggerSourceResolvedKy || ""),
        });
        saveStore();
      }
      line(out, formatOptimizedPredictionText(type, optimized, recentCount, predictionDataset.sourceText));
      return optimized;
      } finally {
        predictFlowBusy = false;
      }
    }

    function applyVipPredictionProfile(result, requestedBundleCount = 1) {
      const type = String(result?.type || "").trim().toUpperCase();
      if (!AI_PREDICT_TYPES.has(type)) return result;
      // predictor_v2 integration start
      const adaptiveVipMeta = getAdaptiveVipPredictorMeta(result);
      if (adaptiveVipMeta.active) {
        return {
          ...result,
          predictionMode: PREDICTION_MODE_VIP,
          vipProfile: String(result?.vipProfile || `${adaptiveVipMeta.key}_adaptive`).trim() || `${adaptiveVipMeta.key}_adaptive`,
          vipSummary: String(result?.vipSummary || `${adaptiveVipMeta.label} đang giữ 1 bộ chính và ${Math.max(0, (Array.isArray(result?.tickets) ? result.tickets.length : 0) - 1)} bộ phụ.`),
          notes: [
            String(result?.vipSummary || ""),
            ...(Array.isArray(result?.notes) ? result.notes : []),
          ].filter(Boolean),
        };
      }
      // predictor_v2 integration end
      const nextCount = Math.max(1, Math.min(VIP_PREDICT_MAX_BUNDLES, Number(requestedBundleCount || 1) || 1));
      const analyses = buildPredictVipTicketAnalyses(result);
      const selected = analyses.slice(0, Math.min(nextCount, analyses.length));
      const selectedIndexes = new Set(selected.map(item => item.index));
      const normalizedRankings = normalizePredictionTopRankings(
        type,
        result?.topRanking,
        result?.topSpecialRanking,
        selected.map(item => item.ticket),
      );
      return {
        ...result,
        predictionMode: PREDICTION_MODE_VIP,
        vipProfile: "strict_select",
        vipSummary: `Vip đang lọc gắt ${selected.length} bộ ưu tiên chính từ ${Array.isArray(result?.tickets) ? result.tickets.length : 0} bộ gốc.`,
        tickets: selected.map(item => item.ticket),
        ticketSources: Array.isArray(result?.ticketSources)
          ? result.ticketSources.filter((_, index) => selectedIndexes.has(index))
          : [],
        topRanking: normalizedRankings.main,
        topSpecialRanking: normalizedRankings.special,
        notes: [
          `Vip profile • strict_select • ${selected.length} bộ ưu tiên`,
          String(result?.vipSummary || ""),
          ...(Array.isArray(result?.notes) ? result.notes : []),
        ].filter(Boolean),
      };
    }

    async function runVipPredictFlow() {
      const type = String(document.getElementById("vipPdType")?.value || vipPredictTypeValue || "").trim().toUpperCase();
      const out = document.getElementById("predictVipOut");
      const t = TYPES[type];
      if (!t || !AI_PREDICT_TYPES.has(type)) {
        if (out) line(out, "Loại Vip không hợp lệ.", "warn");
        return null;
      }
      const count = syncVipPredictBundleLimit({ clampValue: true, forceMinimum: true }).value;
      const countInput = document.getElementById("vipPdCount");
      if (countInput) countInput.value = String(count);
      const kenoLevel = t.keno ? Math.max(1, Math.min(10, Number(document.getElementById("vipPdKenoLevel")?.value || vipPredictKenoLevelValue || 5) || 5)) : 0;
      vipPredictTypeValue = type;
      vipPredictCountValue = count;
      vipPredictKenoLevelValue = kenoLevel || vipPredictKenoLevelValue;
      saveVipPredictState();
      if (predictFlowBusy) {
        if (out) line(out, "Hệ thống đang chạy một lượt dự đoán khác, bạn đợi xong rồi thử lại nhé.", "warn");
        return null;
      }
      predictFlowBusy = true;
      try {
        const engineMeta = getPredictEngineMeta(vipPredictEngineValue);
        const activeRiskMode = engineMeta.key === "both" ? normalizePredictRiskMode(vipPredictRiskModeValue) : "balanced";
        if (!engineMeta.available) {
          if (out) line(out, engineMeta.description || "Engine Vip chưa sẵn sàng.", "warn");
          return null;
        }
        if (out) {
          out.classList.add("muted");
          line(out, "Đang tổng hợp bộ Vip theo profile chọn lọc cao...", "muted");
        }
        const startedAt = Date.now();
        let result;
        // predictor_v2 integration start
        const useAdaptiveVipPredictor = type === "LOTO_5_35" || type === "LOTO_6_45" || type === "LOTO_6_55";
        if (useAdaptiveVipPredictor) {
          result = await predictWithAiBackend(type, count, kenoLevel, engineMeta.backendEngine || "gen_local", activeRiskMode, PREDICTION_MODE_VIP);
        } else if (engineMeta.key === "both") {
          const [luanSoSettled, aiGenSettled] = await Promise.allSettled([
            predictWithAiBackend(type, count, kenoLevel, "luan_so", activeRiskMode, PREDICTION_MODE_VIP),
            predictWithAiBackend(type, count, kenoLevel, "gen_local", activeRiskMode, PREDICTION_MODE_VIP),
          ]);
          const luanSoResult = luanSoSettled?.status === "fulfilled" ? luanSoSettled.value : null;
          const aiGenResult = aiGenSettled?.status === "fulfilled" ? aiGenSettled.value : null;
          if (!luanSoResult && !aiGenResult) {
            throw new Error(normalizePredictionErrorDetail(
              luanSoSettled?.reason || "Luận Số lỗi",
              aiGenSettled?.reason || "AI Gen lỗi",
            ));
          }
          result = mergeBothAiResults(type, count, luanSoResult, aiGenResult, activeRiskMode);
        } else {
          result = await predictWithAiBackend(type, count, kenoLevel, engineMeta.backendEngine || "gen_local", activeRiskMode, PREDICTION_MODE_VIP);
        }
        result = normalizePredictionResultTopRankings(result, type);
        // predictor_v2 integration end
        if (vipPredictPlayModeValue === "bao" && !t.keno) {
          const baoTickets = buildBaoPredictionTickets(
            type,
            count,
            Number(vipPredictBaoLevelValue || 0),
            Array.isArray(result?.topRanking) ? result.topRanking : [],
            Array.isArray(result?.topSpecialRanking) ? result.topSpecialRanking : [],
            Array.isArray(result?.tickets) ? result.tickets : []
          );
          if (baoTickets.length) result = { ...result, tickets: baoTickets };
        }
        const adaptiveVipMeta = getAdaptiveVipPredictorMeta(result);
        const isPredictorV2Vip = adaptiveVipMeta.active;
        let displayResult = normalizePredictionResultTopRankings(applyVipPredictionProfile({
          ...result,
          createdAt: getSyncedIsoString(),
          // predictor_v2 integration start
          engine: isPredictorV2Vip ? adaptiveVipMeta.key : engineMeta.key,
          engineKey: isPredictorV2Vip ? adaptiveVipMeta.key : engineMeta.key,
          engineLabel: isPredictorV2Vip ? adaptiveVipMeta.label : engineMeta.label,
          // predictor_v2 integration end
          riskMode: activeRiskMode,
          riskModeLabel: getPredictRiskModeMeta(activeRiskMode).label,
          riskModeSummary: getPredictRiskModeMeta(activeRiskMode).summary,
          playMode: vipPredictPlayModeValue,
          baoLevel: vipPredictPlayModeValue === "bao" ? Number(vipPredictBaoLevelValue || 0) : null,
          pickSize: t.keno ? kenoLevel : 0,
        }, count), type);
        if (result?.ready !== false && PREDICTION_LOG_TYPES.includes(type)) {
          const predictionDataset = buildPredictionResultDataset(type);
          const predictedKy = normalizeKy(result?.nextKy) || getNextPredictionKy(type, predictionDataset);
          if (predictedKy) {
            upsertPredictionLog(type, {
              createdAt: displayResult.createdAt,
              predictedKy,
              targetDrawAt: String(result?.targetDrawAt || result?.target_draw_at || ""),
              strategyKey: result?.model?.key || "",
              strategyLabel: result?.model?.label || "",
              modelKey: result?.model?.key || "",
              modelLabel: result?.model?.label || "",
              engineKey: isPredictorV2Vip ? String(displayResult?.engineKey || adaptiveVipMeta.key) : engineMeta.key,
              engineLabel: isPredictorV2Vip ? String(displayResult?.engineLabel || adaptiveVipMeta.label) : `${engineMeta.label} • Vip`,
              riskMode: activeRiskMode,
              riskModeLabel: getPredictRiskModeMeta(activeRiskMode).label,
              riskModeSummary: getPredictRiskModeMeta(activeRiskMode).summary,
              modelVersion: result?.modelVersion || "",
              championKey: result?.champion?.key || result?.model?.key || "",
              championLabel: `Vip • ${result?.champion?.label || result?.model?.label || ""}`.trim(),
              lastTrainedAt: result?.lastTrainedAt || "",
              confidence: Number(result?.confidence || 0),
              drawCount: Number(result?.historyCount || 0),
              historyFile: String(result?.historyFile || ""),
              historyCount: Number(result?.historyCount || 0),
              bundleCount: Array.isArray(displayResult?.tickets) ? displayResult.tickets.length : count,
              tickets: Array.isArray(displayResult?.tickets) ? displayResult.tickets : [],
              ticketSources: Array.isArray(displayResult?.ticketSources) ? displayResult.ticketSources : [],
              topMainRanking: Array.isArray(displayResult?.topRanking) ? displayResult.topRanking : [],
              topSpecialRanking: Array.isArray(displayResult?.topSpecialRanking) ? displayResult.topSpecialRanking : [],
              backtest: result?.backtest || null,
              metaSelectionMode: String(result?.metaSelectionMode || ""),
              metaScores: result?.metaScores || null,
              metaQuota: result?.metaQuota || null,
              metaPreferredEngine: String(result?.metaPreferredEngine || ""),
              metaSummary: String(displayResult?.vipSummary || result?.metaSummary || ""),
              playMode: vipPredictPlayModeValue,
              baoLevel: vipPredictPlayModeValue === "bao" ? Number(vipPredictBaoLevelValue || 0) : null,
              pickSize: t.keno ? kenoLevel : 0,
              stabilityScore: Number((result?.stabilityScore ?? result?.backtest?.stabilityScore) || 0),
              predictionMode: PREDICTION_MODE_VIP,
              vipProfile: String(displayResult?.vipProfile || "strict_select"),
              predictionId: String(result?.predictionId || ""),
              predictionStatus: String(result?.predictionStatus || ""),
              dataCutoffDrawId: String(result?.dataCutoffDrawId || result?.data_cutoff_draw_id || ""),
              payloadChecksum: String(result?.payloadChecksum || ""),
              modelRole: String(result?.modelRole || result?.champion?.status || "champion"),
              probabilitySummary: result?.probabilitySummary || null,
              calibratedProbability: Array.isArray(result?.calibratedProbability) ? result.calibratedProbability : [],
              specialCalibratedProbability: Array.isArray(result?.specialCalibratedProbability) ? result.specialCalibratedProbability : [],
              ticketQualityScore: Number(result?.ticketQualityScore ?? result?.qualityScore ?? result?.quality_score ?? 0),
            });
            const saved = await saveStore({ reason: `${type.toLowerCase()}_vip_prediction_log` });
            if (!saved) {
              const saveWarning = "Chưa lưu được prediction log Vip vào tài khoản; nếu tải lại trang lúc này thì lịch sử dự đoán có thể không được giữ lại.";
              displayResult = {
                ...displayResult,
                storeSaveFailed: true,
                storeSaveMessage: saveWarning,
                notes: [saveWarning, ...(Array.isArray(displayResult?.notes) ? displayResult.notes : [])],
              };
              if (type === "KENO" && typeof setKenoPredictStatusMeta === "function") {
                setKenoPredictStatusMeta(saveWarning, "warn");
              }
            }
          }
        }
        stopPredictLoading(engineMeta.key, Date.now() - startedAt);
        renderPredictVipOutput(displayResult);
        return displayResult;
      } catch (err) {
        if (out) {
          vipPredictLastDisplayResult = null;
          out.classList.remove("muted");
          line(out, formatPredictionFailure(err, "Không thể dự đoán Vip"), "warn");
        }
        return null;
      } finally {
        predictFlowBusy = false;
      }
    }

    // ----- Hành động dự đoán ----- 
    // Nút Dự đoán đi qua đây để chọn engine phù hợp, gọi backend và đổ kết quả vào predictOut.
    document.getElementById("predictBtn").onclick = async () => {
      const type = document.getElementById("pdType").value;
      const { value: c } = syncPredictBundleLimit({ clampValue: true, forceMinimum: true });
      const t = TYPES[type];
      const kenoLevel = t?.keno ? Number(document.getElementById("pdKenoLevel").value || 0) : 0;
      await runPredictFlow({
        type,
        count: c,
        kenoLevel,
        engineKey: String(predictEngineValue || "both").trim().toLowerCase() || "both",
        triggerMode: "manual",
      });
    };
    const vipPredictBtn = document.getElementById("vipPredictBtn");
    if (vipPredictBtn) {
      vipPredictBtn.onclick = async () => {
        await runVipPredictFlow();
      };
    }

    function countMainMatch(a, b) {
      const set = new Set(b);
      let c = 0;
      for (const n of a) if (set.has(n)) c++;
      return c;
    }

    function evalPrize(type, ticket, draw) {
      if (String(ticket?.playMode || "").trim().toLowerCase() === "bao") return null;
      const m = countMainMatch(ticket.main, draw.main);
      const hasDb = TYPES[type].hasSpecial;
      const hitDb = hasDb && ticket.special === draw.special;
      if (TYPES[type]?.threeDigit) {
        const targets = Array.isArray(ticket?.main)
          ? ticket.main.map(number => formatPredictNumber(number, type))
          : [];
        if (!targets.length) return null;
        const lines = Array.isArray(draw?.displayLines) ? draw.displayLines : [];
        const matchedTargets = new Set();
        const matchedLabels = [];
        for (const lineText of lines) {
          const line = String(lineText || "");
          const hitTargets = targets.filter(target => new RegExp(`(^|\\D)${target}(\\D|$)`).test(line));
          if (!hitTargets.length) continue;
          const label = line.includes(":") ? line.split(":")[0].trim() : "Trúng";
          hitTargets.forEach(target => matchedTargets.add(target));
          if (label) matchedLabels.push(label);
        }
        if (!matchedTargets.size) return null;
        const uniqueLabels = [...new Set(matchedLabels.filter(Boolean))];
        return [
          `Trúng ${matchedTargets.size}/${targets.length} bộ`,
          uniqueLabels.length ? uniqueLabels.join(" • ") : `Theo bảng thưởng ${TYPES[type]?.label || "3D"}`
        ];
      }
      if (type === "KENO") {
        const level = ticket.main.length;
        const money = KENO_PAYOUT[level]?.[m];
        if (!money) return null;
        return [`Trúng ${m}/${level} (bậc ${level})`, money];
      }
      if (type === "LOTO_5_35") {
        if (m === 5 && hitDb) return ["Giải Độc Đắc", "Tối thiểu 6 tỷ và tích lũy"];
        if (m === 5) return ["Giải Nhất", "10.000.000"];
        if (m === 4 && hitDb) return ["Giải Nhì", "5.000.000"];
        if (m === 4) return ["Giải Ba", "500.000"];
        if (m === 3 && hitDb) return ["Giải Tư", "100.000"];
        if (m === 3) return ["Giải Năm", "30.000"];
        if (hitDb && m <= 2) return ["Giải Khuyến Khích", "10.000"];
        return null;
      }
      if (type === "LOTO_6_45") {
        if (m === 6) return ["Giải Đặc biệt", "Tối thiểu 12 tỷ và tích lũy"];
        if (m === 5) return ["Giải Nhất", "10.000.000"];
        if (m === 4) return ["Giải Nhì", "300.000"];
        if (m === 3) return ["Giải Ba", "30.000"];
        return null;
      }
      if (m === 6) return ["Giải Jackpot 1", "Tối thiểu 30 tỷ và tích lũy"];
      if (m === 5 && hitDb) return ["Giải Jackpot 2", "Tối thiểu 3 tỷ và tích lũy"];
      if (m === 5) return ["Giải Nhất", "40.000.000"];
      if (m === 4) return ["Giải Nhì", "500.000"];
      if (m === 3) return ["Giải Ba", "50.000"];
      return null;
    }

    const lModeEl = document.getElementById("lMode");
    if (lModeEl) {
      lModeEl.onchange = e => {
        const quick = e.target.value === "quick";
        const quickBox = document.getElementById("quickBox");
        const otherBox = document.getElementById("otherBox");
        if (quickBox) quickBox.style.display = quick ? "block" : "none";
        if (otherBox) otherBox.style.display = quick ? "none" : "block";
      };
    }

    const lookupBtn = document.getElementById("lookupBtn");
    if (lookupBtn) lookupBtn.onclick = () => {
      const type = document.getElementById("lType").value;
      const mode = document.getElementById("lMode").value;
      const out = document.getElementById("lookupOut");
      if (!ensureDataReady(type, out, "Truy Cứu Số Trúng")) return;
      const resultMap = store.results[type];
      const resultKeys = store.resultOrder[type];
      const pickMap = store.picks[type];
      const pickKeys = store.pickOrder[type];
      if (!resultKeys.length) return line(out, "Chưa có KQ để tra.", "warn");

      if (mode === "quick") {
        try {
          const nums = parseNums(document.getElementById("lQuick").value);
          const t = TYPES[type];
          let ticket;
          if (t.keno) {
            const main = parseDistinctSortedNums(nums, t.mainMin, t.mainMax, t.pickMinCount || 1, t.pickMaxCount || 10, "Vé Keno tra nhanh");
            ticket = { main, special: null };
          } else {
            const need = t.mainCount + (t.hasSpecial ? 1 : 0);
            if (nums.length !== need) throw new Error(`Cần đúng ${need} số.`);
            ticket = { main: nums.slice(0, t.mainCount).sort((a,b)=>a-b), special: t.hasSpecial ? nums[t.mainCount] : null };
          }
          const hitLines = [];
          for (const ky of resultKeys) {
            const draw = resultMap[ky];
            const hit = evalPrize(type, ticket, draw);
            if (!hit) continue;
            hitLines.push(`Trùng với KỲ ${ky} - KQ ${formatTicket(draw, type)} -> ${hit[0]} | ${hit[1]} VNĐ`);
          }
          const top = `Trả kết quả -> ${TYPES[type].label} Số tra cứu ${formatTicket(ticket, type)}`;
          const total = `Tổng Tìm Thấy ${hitLines.length} Kỳ Trúng.`;
          line(out, [top, "", ...hitLines, "", total].join("\n"));
        } catch (e) {
          line(out, e.message, "warn");
        }
        return;
      }

      const qk = Number(document.getElementById("lCount").value || 0);
      if (!Number.isInteger(qk) || qk <= 0) return line(out, "Số lượng kỳ QK không hợp lệ.", "warn");
      const lastResult = resultKeys.slice(-qk);
      const lastPick = pickKeys.slice(-qk);
      const cmp = lastPick.filter(k => lastResult.includes(k));
      const lines = [
        `Kỳ KQ được tra: ${lastResult.join(", ") || "(không có)"}`,
        `Kỳ vé được tra: ${lastPick.join(", ") || "(không có)"}`,
        `Kỳ dùng để đối chiếu (giao nhau): ${cmp.join(", ") || "(không có)"}`,
        ""
      ];
      let checked = 0, win = 0;
      for (const ky of cmp) {
        const draw = resultMap[ky];
        const tickets = pickMap[ky] || [];
        lines.push(`${TYPES[type].label} Kỳ ${ky} - KQ: ${formatTicket(draw, type)}`);
        tickets.forEach((t, i) => {
          checked++;
          const hit = evalPrize(type, t, draw);
          if (!hit) return;
          win++;
          lines.push(`  Vé #${i + 1}: ${formatTicket(t, type)} -> ${hit[0]} | ${hit[1]} VNĐ`);
        });
        lines.push("");
      }
      if (!checked) lines.push("Không có vé nào để đối chiếu.");
      else lines.push(`Tổng vé đã tra: ${checked} | Tổng vé trúng: ${win}`);
      line(out, lines.join("\n"));
    };

    const delAllBtn = document.getElementById("delAllBtn");
    if (delAllBtn) delAllBtn.onclick = () => {
      const type = document.getElementById("dType").value;
      const target = document.getElementById("dTarget").value;
      const out = document.getElementById("dMsg");
      const meta = getDeleteTargetMeta(target);
      if (!ensureDeleteTargetReady(type, target, out)) return;
      if (!confirm(`Xóa hết ${meta.uiLabel} theo loại ${TYPES[type].label}?`)) return;
      store[meta.dataKey][type] = {};
      store[meta.orderKey][type] = [];
      saveStore();
      line(out, `Đã xóa toàn bộ ${meta.uiLabel} của ${TYPES[type].label}.`, "ok");
    };

    const delKyBtn = document.getElementById("delKyBtn");
    if (delKyBtn) delKyBtn.onclick = () => {
      const type = document.getElementById("dType").value;
      const target = document.getElementById("dTarget").value;
      const out = document.getElementById("dMsg");
      const meta = getDeleteTargetMeta(target);
      if (!ensureDeleteTargetReady(type, target, out)) return;
      const ky = normalizeKy(document.getElementById("dKy").value);
      if (!ky) return line(out, "Kỳ không hợp lệ.", "warn");
      let removed = false;
      if (store[meta.dataKey]?.[type]?.[ky]) {
        delete store[meta.dataKey][type][ky];
        store[meta.orderKey][type] = (store[meta.orderKey][type] || []).filter(k => k !== ky);
        removed = true;
      }
      saveStore();
      line(
        out,
        removed ? `Đã xóa ${meta.uiLabel} kỳ ${ky}.` : `Không tìm thấy ${meta.uiLabel} kỳ ${ky}.`,
        removed ? "ok" : "warn"
      );
    };

