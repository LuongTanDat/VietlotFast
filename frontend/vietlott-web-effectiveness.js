(function () {
  "use strict";

  const root = document.getElementById("predictRootEffectiveness");
  if (!root) return;
  const byId = id => document.getElementById(id);
  const methods = [
    { key: "web", label: "Pipeline web", color: "#a78bfa" },
    { key: "random", label: "Ngẫu nhiên", color: "#94a3b8" },
    { key: "bayesian", label: "Bayesian", color: "#38bdf8" },
    { key: "ewma", label: "EWMA", color: "#34d399" },
  ];
  const methodPairs = [{ key: "web", methods: methods.slice(0, 2) }, { key: "bayesian", methods: methods.slice(2) }];
  const state = { active: false, authenticated: false, generation: 0, report: null, busy: false, loading: false, controller: null, ticketController: null, ticketPages: new Map(), selectedMethods: new Map(), timer: null, page: 1, lines: new Set(methods.map(item => item.key)), openDetails: new Map() };
  const lab = { job: null, history: [], tracking: null, selectedJobId: null, canManage: false, loading: false, busy: false, controller: null, serial: 0, timer: null };
  const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const finite = value => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
  const number = (value, digits = 3) => finite(value) ? Number(value).toLocaleString("vi-VN", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : "—";
  const percent = value => finite(value) ? `${number(Number(value) * 100, 1)}%` : "—";
  const signed = value => finite(value) ? `${Number(value) > 0 ? "+" : ""}${number(value)}` : "—";
  const dateTime = value => {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isFinite(date.getTime()) ? date.toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh", hour12: false }) : "—";
  };
  const interval = value => value && finite(value.lower) && finite(value.upper) ? `[${signed(value.lower)}; ${signed(value.upper)}]` : "—";
  const methodLabel = key => methods.find(item => item.key === key)?.label || key;
  const reportGame = report => String(report.type || byId("effectivenessType").value);
  const isKeno = () => byId("effectivenessType").value === "KENO";
  const reportSize = report => report.type === "KENO" ? Number(report.level || 10) : report.type === "LOTO_5_35" ? 5 : 6;
  const opened = (key, fallback = false) => (state.openDetails.has(key) ? state.openDetails.get(key) : fallback) ? " open" : "";

  function rememberOpenDetails() {
    root.querySelectorAll("details[data-effectiveness-state]").forEach(details => state.openDetails.set(details.dataset.effectivenessState, details.open));
  }

  function showStatus(message, kind = "") {
    const el = byId("effectivenessStatus");
    el.textContent = message;
    el.dataset.kind = kind;
  }

  function ticketMaximum() {
    if (!isKeno()) return 10000;
    const level = Number(byId("effectivenessKenoLevel").value);
    return level === 1 ? 80 : level === 2 ? 3160 : 10000;
  }

  function normalizeTicketCount(commit = false) {
    const input = byId("effectivenessTicketCount");
    const value = input.valueAsNumber;
    if (!Number.isFinite(value)) {
      if (commit) input.value = "1";
    } else if (value > ticketMaximum()) input.value = String(ticketMaximum());
    else if (commit) input.value = String(Math.max(1, Math.trunc(value)));
  }

  function updateTicketLimit() {
    const input = byId("effectivenessTicketCount");
    const maximum = ticketMaximum();
    const changed = input.max !== String(maximum);
    input.max = String(maximum);
    input.placeholder = `Max ${number(maximum, 0)}`;
    input.title = `Tối đa ${number(maximum, 0)} vé${isKeno() ? ` ở bậc ${byId("effectivenessKenoLevel").value}` : ""}`;
    byId("effectivenessTicketMax").textContent = `Tối đa ${number(maximum, 0)}`;
    if (changed) normalizeTicketCount();
  }

  function setSettingsOpen(open, returnFocus = false) {
    const panel = byId("effectivenessAdmin");
    const button = byId("effectivenessSettings");
    panel.open = !!open && !panel.hidden;
    button.setAttribute("aria-expanded", String(panel.open));
    if (panel.open) { setHelpOpen(false); normalizeTicketCount(); byId("effectivenessEnabled").focus({ preventScroll: true }); }
    else if (returnFocus && !button.hidden) button.focus({ preventScroll: true });
  }

  function setHelpOpen(open, returnFocus = false) {
    const panel = byId("effectivenessHelpPanel");
    const button = byId("effectivenessHelpButton");
    panel.open = !!open;
    button.setAttribute("aria-expanded", String(panel.open));
    if (panel.open) { setSettingsOpen(false); panel.focus({ preventScroll: true }); }
    else if (returnFocus) button.focus({ preventScroll: true });
  }

  function setControls() {
    const canManage = !!state.report?.canManage && state.authenticated;
    if (!canManage) setSettingsOpen(false);
    byId("effectivenessAdmin").hidden = !canManage;
    byId("effectivenessSettings").hidden = !canManage;
    byId("effectivenessSettings").disabled = state.busy || state.loading;
    byId("effectivenessSettings").setAttribute("aria-expanded", String(byId("effectivenessAdmin").open));
    byId("effectivenessRefresh").disabled = !state.authenticated || state.loading || state.busy;
    ["effectivenessType", "effectivenessLimit", "effectivenessKenoLevel"].forEach(id => { byId(id).disabled = state.busy; });
    byId("effectivenessLimitLabel").hidden = isKeno();
    byId("effectivenessKenoLevelLabel").hidden = !isKeno();
    const levelBar = byId("effectivenessKenoLevels");
    levelBar.hidden = !isKeno();
    const selectedLevel = byId("effectivenessKenoLevel").value;
    levelBar.querySelectorAll("[data-keno-level]").forEach(button => {
      button.disabled = !state.authenticated || state.busy;
      button.setAttribute("aria-pressed", String(button.dataset.kenoLevel === selectedLevel));
    });
    if (isKeno() && levelBar.dataset.selectedLevel !== selectedLevel) {
      levelBar.dataset.selectedLevel = selectedLevel;
      const selectedButton = levelBar.querySelector('[aria-pressed="true"]');
      if (selectedButton) {
        const buttonRect = selectedButton.getBoundingClientRect();
        const barRect = levelBar.getBoundingClientRect();
        if (buttonRect.left < barRect.left) levelBar.scrollLeft -= barRect.left - buttonRect.left + 4;
        else if (buttonRect.right > barRect.right) levelBar.scrollLeft += buttonRect.right - barRect.right + 4;
      }
    }
    byId("effectivenessLab").hidden = isKeno();
    updateTicketLimit();
    byId("effectivenessTicketHint").textContent = isKeno()
      ? "Theo dõi cả 10 bậc · Vé không trùng · Cấu hình áp dụng từ kỳ chưa khóa."
      : "Vé không trùng · Tự khóa khi server chạy · Cấu hình áp dụng từ kỳ chưa khóa.";
    const cyclePages = cyclePagination(state.report);
    byId("effectivenessKenoPrevious").disabled = state.loading || state.busy || cyclePages.page <= 1;
    byId("effectivenessKenoNext").disabled = state.loading || state.busy || cyclePages.page >= cyclePages.totalPages;
    byId("effectivenessCyclePages").querySelectorAll("button").forEach(button => { button.disabled = state.loading || state.busy || !state.authenticated; });
    ["effectivenessEnabled", "effectivenessTicketCount", "effectivenessSave", "effectivenessLock"].forEach(id => { byId(id).disabled = !canManage || state.busy || state.loading; });
    root.setAttribute("aria-busy", state.loading || state.busy ? "true" : "false");
    setLabControls();
  }

  async function request(path, { method = "GET", form = null, signal } = {}) {
    const options = { method, credentials: "same-origin", cache: "no-store", signal, headers: { Accept: "application/json" } };
    if (form) {
      options.body = new URLSearchParams(form);
      options.headers["Content-Type"] = "application/x-www-form-urlencoded;charset=UTF-8";
    }
    const response = await fetch(path, options);
    let payload;
    try { payload = await response.json(); } catch { throw new Error("Server chưa trả báo cáo hợp lệ. Hãy kiểm tra server rồi làm mới."); }
    if (!response.ok || payload.ok === false) {
      const error = new Error(response.status === 401 ? "Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại." : String(payload.error || payload.message || "Không thể hoàn tất thao tác."));
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function decisionText(row) {
    const decision = String(row.decision || "").toLowerCase();
    if (row.key === "random") return "Đối chứng cùng số vé";
    if (!Number(row.sampleCount)) return "Chưa có kỳ đã chấm";
    if (["insufficient", "insufficient_evidence", "insufficient_samples"].includes(decision)) return "Chưa đủ bằng chứng";
    if (["better", "positive", "better_than_random"].includes(decision)) return "Cao hơn ngẫu nhiên trong mẫu này";
    if (decision === "possible_improvement") return "Có dấu hiệu tốt hơn; cần xác nhận thêm";
    if (["worse", "negative", "worse_than_random"].includes(decision)) return "Thấp hơn ngẫu nhiên trong mẫu này";
    if (["inconclusive", "no_evidence", "not_significant", "uncertain", "no_clear_advantage"].includes(decision)) return "Chưa thấy lợi thế rõ ràng";
    return "Cần thêm kỳ để kết luận";
  }

  function renderSummary(report) {
    const counts = report.counts || {};
    const settings = report.settings || {};
    const effectiveBudget = report.type === "KENO" ? Math.min(Number(settings.ticketCount), reportSize(report) === 1 ? 80 : reportSize(report) === 2 ? 3160 : 10000) : settings.ticketCount;
    const cards = [
      ["Đã chấm", number(counts.scored, 0), "kỳ có kết quả"],
      ["Chờ kết quả", number(counts.locked, 0), "kỳ đã khóa"],
      ["Ngân sách", finite(effectiveBudget) ? `${number(effectiveBudget, 0)} vé` : "—", report.type === "KENO" ? `Kỳ mới · mỗi phương pháp / bậc ${reportSize(report)}` : "Kỳ mới · mỗi phương pháp"],
      ["Theo dõi", settings.enabled ? "Bật" : "Tắt", "Tự động khi server đang chạy"],
    ];
    byId("effectivenessSummary").innerHTML = cards.map(([label, value, note]) => `<div class="effectiveness-metric${String(value).length >= 8 ? ' is-wide' : ''}" title="${escape(`${label}: ${value} · ${note}`)}"><span>${escape(label)}</span><strong>${escape(value)}</strong><small>${escape(note)}</small></div>`).join("");
    if (!byId("effectivenessAdmin").open) {
      byId("effectivenessEnabled").checked = settings.enabled === true;
      byId("effectivenessTicketCount").value = finite(settings.ticketCount) ? String(Math.min(Number(settings.ticketCount), ticketMaximum())) : "1";
    }
    byId("effectivenessAdminSummary").textContent = `${settings.enabled ? "Đang bật" : "Đang tắt"} · ${number(settings.ticketCount, 0)} vé`;
  }

  function renderComparison(report) {
    const keno = report.type === "KENO";
    const rows = methods.map(method => (Array.isArray(report.methods) ? report.methods : []).find(item => item.key === method.key) || { key: method.key, label: method.label });
    const probabilityKey = `${reportGame(report)}:probabilities`;
    byId("effectivenessComparison").innerHTML = `<div class="effectiveness-table-wrap" tabindex="0" role="region" aria-label="So sánh bốn phương pháp trên tất cả kỳ đã chấm">
      <table class="effectiveness-table effectiveness-comparison-table"><caption><strong>${keno ? `Bậc ${reportSize(report)} · So sánh phương pháp` : "So sánh phương pháp"}</strong><span>${keno ? `Ngẫu nhiên kỳ vọng ${number(reportSize(report) / 4, 2)} số / vé · tất cả kỳ đã chấm` : "Tất cả các kỳ đã chấm · cùng số vé trong từng kỳ"}</span></caption>
      <thead><tr><th scope="col">Phương pháp</th><th scope="col">Trùng / vé</th><th scope="col">${keno ? "Tỷ lệ vé" : "Tỷ lệ trùng"}</th><th scope="col">So với ngẫu nhiên</th><th scope="col">Nhận định</th></tr></thead>
      <tbody>${rows.map(row => `<tr><th scope="row"><span class="effectiveness-method-dot" style="background:${methods.find(method => method.key === row.key).color}"></span>${escape(row.label || methodLabel(row.key))}<small>${number(row.sampleCount, 0)} kỳ đã chấm${keno ? ` · ${number(row.dayCount, 0)} ngày` : ""}</small></th><td data-label="Trùng / vé" class="effectiveness-mean">${number(row.meanHits)}</td><td data-label="${keno ? "Tỷ lệ vé" : "Tỷ lệ trùng"}">${keno ? `<span>Có giải <strong>${percent(row.winningTicketRate)}</strong></span><span>Trùng đủ <strong>${percent(row.fullMatchRate)}</strong></span>` : `<span>≥3 số <strong>${percent(row.rate3)}</strong></span><span>≥4 số <strong>${percent(row.rate4)}</strong></span>`}</td><td data-label="So với ngẫu nhiên"><strong>${signed(row.deltaVsRandom)}</strong><small class="effectiveness-ci">95% ${interval(row.ci95)}${keno ? " · theo ngày" : ""}</small></td><td data-label="Nhận định" class="effectiveness-decision">${escape(decisionText(row))}</td></tr>`).join("")}</tbody></table></div>
      <details class="effectiveness-probabilities" data-effectiveness-state="${escape(probabilityKey)}"${opened(probabilityKey)}><summary>Chỉ số xác suất số chính <span>Brier · Log-loss</span></summary><p>Brier và log-loss dùng xác suất biên chưa hiệu chỉnh; thấp hơn là tốt hơn. Dấu — là thiếu dữ liệu hợp lệ, không phải điểm 0. Đây không phải xác suất trúng toàn bộ vé.</p><div class="effectiveness-table-wrap"><table class="effectiveness-table"><thead><tr><th scope="col">Phương pháp</th><th scope="col">Brier</th><th scope="col">Log-loss</th></tr></thead><tbody>${rows.map(row => `<tr><th scope="row">${escape(row.label || methodLabel(row.key))}</th><td>${number(row.brierScore, 5)}</td><td>${number(row.logLoss, 5)}</td></tr>`).join("")}</tbody></table></div></details>`;
  }

  function renderNotes(report) {
    const notes = Array.isArray(report.notes) ? report.notes.filter(note => typeof note === "string" && note.trim()) : [];
    const count = finite(report.configurationCount) ? number(report.configurationCount, 0) : "nhiều";
    byId("effectivenessMixedWarning").innerHTML = report.mixedConfigurations === true ? `<p class="effectiveness-mixed-configurations"><strong>Gộp ${escape(count)} cấu hình / ngân sách.</strong> Xem cấu hình đã khóa trong từng kỳ.</p>` : "";
    byId("effectivenessReportNotes").innerHTML = notes.length ? `<ul>${notes.map(note => `<li>${escape(note)}</li>`).join("")}</ul>` : "";
  }

  function renderTimeline(report) {
    const host = byId("effectivenessTimeline");
    const cycles = (Array.isArray(report.cycles) ? report.cycles : []).filter(cycle => cycle.status === "scored" || cycle.status === "complete" || Array.isArray(cycle.actualMain) && cycle.actualMain.length).slice(0, 30).sort((left, right) => Number(left.targetDrawId) - Number(right.targetDrawId));
    if (cycles.length < 2) { host.hidden = true; host.innerHTML = ""; return; }
    host.hidden = false;
    const width = 1000, height = 240, pad = { left: 42, top: 22, bottom: 42, right: 14 };
    const maxHits = reportSize(report);
    const x = index => pad.left + index * (width - pad.left - pad.right) / (cycles.length - 1);
    const y = value => height - pad.bottom - value * (height - pad.top - pad.bottom) / maxHits;
    const grid = Array.from({ length: maxHits + 1 }, (_, hit) => `<line x1="${pad.left}" x2="${width - pad.right}" y1="${y(hit)}" y2="${y(hit)}" class="effectiveness-chart-grid"/><text x="${pad.left - 12}" y="${y(hit) + 4}" text-anchor="end">${hit}</text>`).join("");
    const lines = methods.filter(method => state.lines.has(method.key)).map(method => {
      const points = cycles.map((cycle, index) => finite(cycle.methods?.[method.key]?.meanHits) ? [index, Number(cycle.methods[method.key].meanHits)] : null);
      let path = "", contiguous = false;
      points.forEach(point => { if (!point) { contiguous = false; return; } path += `${contiguous ? " L" : " M"}${x(point[0])},${y(point[1])}`; contiguous = true; });
      return `<path d="${path}" fill="none" stroke="${method.color}" stroke-width="2.5"/>${points.filter(Boolean).map(([index, value]) => `<circle cx="${x(index)}" cy="${y(value)}" r="3" fill="${method.color}"><title>${escape(`${method.label} · kỳ ${cycles[index].targetDrawId} · ${number(value)} số trùng / vé`)}</title></circle>`).join("")}`;
    }).join("");
    const trendKey = `${reportGame(report)}:trend`;
    host.innerHTML = `<details data-effectiveness-state="${escape(trendKey)}"${opened(trendKey)}><summary class="effectiveness-chart-head"><strong>Số trùng theo kỳ</strong><span>${cycles.length} kỳ gần nhất · xem biểu đồ</span></summary><div class="effectiveness-chart-body"><div class="effectiveness-chart-legend">${methods.map(method => `<button type="button" class="secondary" data-effectiveness-line="${method.key}" aria-pressed="${state.lines.has(method.key)}"><span class="effectiveness-method-dot" style="background:${method.color}"></span>${escape(method.label)}</button>`).join("")}</div><svg viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="effectivenessChartTitle effectivenessChartDescription"><title id="effectivenessChartTitle">Số trùng trung bình từng kỳ của bốn phương pháp</title><desc id="effectivenessChartDescription">Trục ngang là kỳ quay theo thời gian. Trục dọc là số chính trùng trung bình trên mỗi vé. Số liệu từng kỳ có trong nhật ký bên dưới.</desc>${grid}${lines}<text x="${pad.left}" y="${height - 12}">Kỳ ${escape(cycles[0].targetDrawId)}</text><text x="${width - pad.right}" y="${height - 12}" text-anchor="end">Kỳ ${escape(cycles[cycles.length - 1].targetDrawId)}</text></svg></div></details>`;
  }

  function ticketHtml(ticket, actual, options = {}) {
    const values = Array.isArray(ticket.main) ? ticket.main : [];
    const specialLabel = options.power ? "Phụ" : "ĐB";
    return `<span class="effectiveness-ticket">${values.map(value => `<span class="effectiveness-ball${actual.has(Number(value)) ? " is-hit" : ""}">${escape(String(value).padStart(2, "0"))}${actual.has(Number(value)) ? '<span class="sr-only"> trùng</span>' : ""}</span>`).join("")}${options.showSpecial !== false && ticket.special !== null && ticket.special !== undefined && ticket.special !== "" ? `<span class="effectiveness-special${options.specialMatched === true && !options.power ? " is-matched" : ""}"${options.power ? ' title="Số phụ dự đoán; giải Power xét sáu số trên vé và bóng thứ 7 thực tế"' : ""}>${specialLabel} ${escape(String(ticket.special).padStart(2, "0"))}</span>` : ""}</span>`;
  }

  function ticketRowHtml(ticket, actual, index, mainCount, result = null, power = false) {
    const values = Array.isArray(ticket.main) ? ticket.main : [];
    const hits = actual.size ? [...new Set(values.map(Number))].filter(value => actual.has(value)).length : null;
    const resultStatus = ["won", "lost", "unknown", "pending", "unsupported", "invalid"].includes(result?.status) ? result.status : "unknown";
    const prizeLabel = result?.prizeLabel || (hits === null ? "Chờ kết quả" : "Chưa có phân loại giải");
    return `<div class="effectiveness-ticket-row"><span class="effectiveness-ticket-label">Vé ${String(index + 1).padStart(2, "0")}</span>${ticketHtml(ticket, actual, { power, showSpecial: power || mainCount === 5, specialMatched: result?.specialMatched })}<span class="effectiveness-ticket-hits${hits > 0 ? " has-hit" : ""}" aria-label="${hits === null ? "Chờ kết quả" : `${hits} trên ${mainCount} số chính trùng`}">${hits === null ? "—" : `${hits}/${mainCount}`}</span><span class="effectiveness-ticket-prize" data-prize-status="${resultStatus}"${result?.reason ? ` title="${escape(result.reason)}"` : ""}>${escape(prizeLabel)}</span></div>`;
  }

  function actualSpecialHtml(cycle, game) {
    if (game === "LOTO_6_45" || game === "KENO") return "";
    const label = game === "LOTO_6_55" ? "Bóng thứ 7" : "ĐB";
    return finite(cycle.actualSpecial) ? `<span class="effectiveness-actual-special">${label} <strong>${escape(String(cycle.actualSpecial).padStart(2, "0"))}</strong></span>` : `<span class="effectiveness-special-unknown">${label}: chưa có dữ liệu</span>`;
  }

  function cycleInfoHtml(cycle, cycleKey, budget) {
    const infoKey = `${cycleKey}:info`;
    return `<details class="effectiveness-provenance" data-effectiveness-state="${escape(infoKey)}"${opened(infoKey)}><summary>Thông tin dự đoán</summary><dl class="effectiveness-info-list"><div><dt>Dữ liệu đến</dt><dd>Kỳ ${escape(cycle.cutoffDrawId)}</dd></div><div><dt>Đã khóa lúc</dt><dd>${escape(dateTime(cycle.createdAt))} (giờ Việt Nam)</dd></div><div><dt>Giờ quay / hạn khóa</dt><dd>${escape(dateTime(cycle.deadline))} (giờ Việt Nam)</dd></div>${cycle.scoredAt ? `<div><dt>Ghi nhận điểm lúc</dt><dd>${escape(dateTime(cycle.scoredAt))} (giờ Việt Nam)</dd></div>` : ""}<div><dt>Ngân sách đã khóa</dt><dd>${escape(budget)} vé / phương pháp${cycle.level ? " / bậc" : ""}</dd></div>${methods.map(method => {
      const entry = cycle.methods?.[method.key] || {};
      const fields = [["Engine", entry.engine], ["Model", entry.modelId], ["Mã dự đoán", entry.predictionId], ["Seed", entry.seed], ["Trung bình số trùng / vé", entry.meanHits], ["Số trùng tốt nhất", entry.bestHits]];
      return fields.filter(([, value]) => value !== null && value !== undefined && value !== "").map(([label, value]) => `<div><dt>${escape(method.label)} · ${label}</dt><dd>${escape(value)}</dd></div>`).join("");
    }).join("")}</dl></details>`;
  }

  // Standard 10,000 VND selections, before tax. Variable jackpots are NOT
  // individual payouts. Keno's top tiers also depend on shared prize limits.
  // https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/view-detail-keno-result?id=0292457
  function prizeUnitAmount(game, code) {
    const fixed = {
      LOTO_5_35: { FIRST: 10000000, SECOND: 5000000, THIRD: 500000, FOURTH: 100000, FIFTH: 30000, CONSOLATION: 10000 },
      LOTO_6_45: { FIRST: 10000000, SECOND: 300000, THIRD: 30000 },
      LOTO_6_55: { FIRST: 40000000, SECOND: 500000, THIRD: 50000 },
    };
    const keno = {
      1: { 1: 20000 }, 2: { 2: 90000 }, 3: { 2: 20000, 3: 200000 },
      4: { 2: 10000, 3: 50000, 4: 400000 }, 5: { 3: 10000, 4: 150000, 5: 4400000 },
      6: { 3: 10000, 4: 40000, 5: 450000, 6: 12500000 },
      7: { 3: 10000, 4: 20000, 5: 100000, 6: 1200000, 7: 40000000 },
      8: { 0: 10000, 4: 10000, 5: 50000, 6: 500000, 7: 5000000 },
      9: { 0: 10000, 4: 10000, 5: 30000, 6: 150000, 7: 1500000, 8: 12000000 },
      10: { 0: 10000, 5: 20000, 6: 80000, 7: 710000, 8: 8000000, 9: 150000000 },
    };
    const match = game === "KENO" && /^KENO_(\d+)_(\d+)$/.exec(code);
    return match ? keno[Number(match[1])]?.[Number(match[2])] ?? null : fixed[game]?.[code] ?? null;
  }

  function prizeMoneyHtml(groups, total, uncertain, game) {
    const ticketPrice = 10000;
    const money = value => `${number(value, 0)} ₫`;
    const rows = groups.map(group => {
      const unit = prizeUnitAmount(game, group.code);
      return { ...group, unit, amount: unit === null ? null : unit * group.count };
    });
    const reward = rows.reduce((sum, row) => sum + (row.amount ?? 0), 0);
    const cost = total * ticketPrice;
    const complete = !uncertain && rows.every(row => row.amount !== null && Number.isSafeInteger(row.amount)) && Number.isSafeInteger(reward) && Number.isSafeInteger(cost);
    const net = reward - cost;
    const notes = [
      game === "LOTO_5_35" ? "Cơ cấu chuẩn, chưa gồm Chia Giải" : "",
      rows.some(row => row.unit === null) ? "Cần mức trả/vé của đúng kỳ cho giải chia thưởng/Jackpot" : "",
    ].filter(Boolean).join(" · ");
    return `<div class="effectiveness-prize-counts" role="list" aria-label="Chi tiết giải thưởng, số lượng giảm dần">${rows.map(row => `<div class="effectiveness-prize-detail" role="listitem" data-prize-code="${escape(row.code)}" data-prize-unit="${row.unit ?? ''}" data-prize-subtotal="${row.amount ?? ''}"><span class="effectiveness-prize-name">${escape(row.label)}</span><span class="effectiveness-prize-equation"><b>${number(row.count, 0)}</b><i>×</i><span>${row.unit === null ? "Chờ mức trả/vé" : money(row.unit)}</span><i>=</i><strong>${row.amount === null ? "Chưa xác định" : money(row.amount)}</strong></span></div>`).join("")}</div><div class="effectiveness-prize-total"><span>${complete ? "Tổng tiền thưởng" : "Thưởng đã tính"}</span><strong data-prize-reward="${reward}">${money(reward)}</strong></div><div class="effectiveness-prize-total effectiveness-ticket-total"><span>Tổng tiền vé</span><strong data-total-ticket-cost="${cost}">${money(cost)}</strong></div><div class="effectiveness-prize-net${complete ? net > 0 ? ' is-positive' : net < 0 ? ' is-negative' : ' is-even' : ' is-incomplete'}"><span class="effectiveness-prize-net-label">Tiền thưởng − Tiền vé</span><span class="effectiveness-prize-net-equation"><span>${complete ? money(reward) : 'Chưa đủ tổng thưởng'}</span><span>− ${money(cost)}</span><span>=</span><strong data-prize-net="${complete ? net : ''}" data-ticket-cost="${cost}">${complete ? money(net) : "Chưa tính đủ"}</strong></span></div>${notes ? `<small>${notes}</small>` : ""}`;
  }

  function methodPrizeSummaryHtml(cycle, entry, game, total, label) {
    if (!total) return '<div class="effectiveness-prize-summary is-muted">Chưa có vé đã khóa</div>';
    if (!(cycle.actualMain || []).length) return '<div class="effectiveness-prize-summary is-muted">Chờ kết quả</div>';
    const labels = {
      LOTTO_JACKPOT: "Độc Đắc", MEGA_JACKPOT: "Jackpot", POWER_JACKPOT_1: "Jackpot 1", POWER_JACKPOT_2: "Jackpot 2",
      FIRST: "Giải Nhất", SECOND: "Giải Nhì", THIRD: "Giải Ba", FOURTH: "Giải Tư", FIFTH: "Giải Năm", CONSOLATION: "Giải Khuyến Khích",
    };
    const tiers = {
      LOTO_5_35: ["LOTTO_JACKPOT", "FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH", "CONSOLATION"],
      LOTO_6_45: ["MEGA_JACKPOT", "FIRST", "SECOND", "THIRD"],
      LOTO_6_55: ["POWER_JACKPOT_1", "POWER_JACKPOT_2", "FIRST", "SECOND", "THIRD"],
    };
    const tier = code => {
      if (game === "KENO") {
        const match = /^KENO_(\d+)_(\d+)$/.exec(code);
        const winningHits = { 1: [1], 2: [2], 3: [2, 3], 4: [2, 3, 4], 5: [3, 4, 5], 6: [3, 4, 5, 6], 7: [3, 4, 5, 6, 7], 8: [0, 4, 5, 6, 7, 8], 9: [0, 4, 5, 6, 7, 8, 9], 10: [0, 5, 6, 7, 8, 9, 10] };
        if (!match || Number(match[1]) !== Number(cycle.level || state.report?.level) || !winningHits[Number(match[1])]?.includes(Number(match[2]))) return null;
        return { label: `Trúng ${Number(match[2])}/${Number(match[1])} số`, rank: 10 - Number(match[2]) };
      }
      const rank = (tiers[game] || []).indexOf(code);
      return rank < 0 ? null : { label: labels[code], rank };
    };
    let counts = entry.prizeCounts;
    // Old complete reports can use their full result array. A 20-ticket page
    // must never be counted as the whole prediction.
    if (!counts && entry.tickets?.length === total && entry.ticketResults?.length === total) {
      const results = entry.ticketResults;
      const indices = new Set(results.map(result => Number(result.ticketIndex)));
      if (indices.size === total && results.every(result => Number.isInteger(Number(result.ticketIndex)) && result.ticketIndex >= 1 && result.ticketIndex <= total && result.prizeCode)) {
        counts = results.reduce((all, result) => { all[result.prizeCode] = (all[result.prizeCode] || 0) + 1; return all; }, Object.create(null));
      }
    }
    const entries = counts && typeof counts === "object" && !Array.isArray(counts) ? Object.entries(counts) : [];
    if (!entries.length || entries.some(([, count]) => !Number.isSafeInteger(count) || count < 0) || entries.reduce((sum, [, count]) => sum + count, 0) !== total) {
      return '<div class="effectiveness-prize-summary is-muted">Chưa đủ dữ liệu thống kê toàn bộ vé</div>';
    }
    const groups = entries.flatMap(([code, count]) => { const info = tier(code); return count > 0 && info ? [{ code, count, ...info }] : []; });
    const uncertain = entries.filter(([code]) => !tier(code) && code !== "NONE").reduce((sum, [, count]) => sum + count, 0);
    if (!groups.length) return uncertain ? '<div class="effectiveness-prize-summary is-muted">Chưa xác định vé trúng</div>' : `<div class="effectiveness-prize-summary"><span class="effectiveness-prize-empty">Chưa có vé trúng</span>${prizeMoneyHtml([], total, 0, game)}</div>`;
    const highest = [...groups].sort((a, b) => a.rank - b.rank)[0];
    groups.sort((a, b) => b.count - a.count || a.rank - b.rank);
    return `<div class="effectiveness-prize-summary" aria-label="Vé trúng và tiền thưởng mô phỏng của toàn bộ ${escape(label)} trong kỳ này"><div class="effectiveness-prize-best"><span>Cao nhất</span><strong>${escape(highest.label)}</strong><span>SL <b>${number(highest.count, 0)}</b></span></div>${prizeMoneyHtml(groups, total, uncertain, game)}${uncertain ? `<small>Còn ${number(uncertain, 0)} vé chưa xác định giải</small>` : ""}</div>`;
  }

  function cycleMethodHtml(cycle, method, game, mainCount) {
    const entry = cycle.methods?.[method.key] || {};
    const actual = new Set((cycle.actualMain || []).map(Number));
    const tickets = Array.isArray(entry.tickets) ? entry.tickets : [];
    const pagination = entry.ticketPagination;
    const offset = Number(pagination?.offset || 0);
    const total = Number(entry.ticketCount ?? pagination?.total ?? tickets.length);
    const pager = pagination?.totalPages > 1 ? `<nav class="effectiveness-ticket-pager" aria-label="Phân trang vé ${escape(method.label)}"><span class="effectiveness-ticket-range">Vé ${number(offset + 1, 0)}–${number(offset + tickets.length, 0)} / ${number(total, 0)}</span><div class="effectiveness-ticket-page-controls"><button type="button" class="secondary" data-ticket-page="${pagination.page - 1}"${pagination.page <= 1 ? " disabled" : ""} aria-label="Trang vé trước">‹</button><label><span>Trang</span><input type="number" data-ticket-jump min="1" max="${pagination.totalPages}" step="1" value="${pagination.page}" aria-label="Trang vé ${escape(method.label)}" /><span>/ ${number(pagination.totalPages, 0)}</span></label><button type="button" class="secondary" data-ticket-page="${pagination.page + 1}"${pagination.page >= pagination.totalPages ? " disabled" : ""} aria-label="Trang vé tiếp theo">›</button></div></nav>` : "";
    const summary = methodPrizeSummaryHtml(cycle, entry, game, total, method.label);
    const footer = pager || summary ? `<div class="effectiveness-ticket-footer">${pager}${summary}</div>` : "";
    return `<div class="effectiveness-cycle-method-head"><strong><span class="effectiveness-method-dot" style="background:${method.color}"></span>${escape(method.label)}</strong><span>${actual.size ? `TB ${number(entry.meanHits, 2)} số / vé` : `${number(total, 0)} vé đã khóa`}</span></div><div class="effectiveness-ticket-columns" aria-hidden="true"><span>Vé</span><span>Bộ số dự đoán</span><span>Trùng</span><span>Kết quả</span></div><div class="effectiveness-ticket-list">${tickets.length ? tickets.map((ticket, ticketIndex) => ticketRowHtml(ticket, actual, offset + ticketIndex, mainCount, (entry.ticketResults || []).find(result => Number(result.ticketIndex) === offset + ticketIndex + 1), game === "LOTO_6_55")).join("") : '<span class="muted">Chưa có bộ số</span>'}</div>${footer}`;
  }

  async function loadTicketPage(panel, page) {
    const report = state.report;
    if (!state.authenticated || !state.active || !report || state.loading || state.busy || !Number.isInteger(page)) return;
    const predictionId = panel.dataset.predictionId;
    const method = methods.find(item => item.key === panel.dataset.method);
    const cycle = report.cycles?.find(item => item.methods?.[method?.key]?.predictionId === predictionId);
    const entry = cycle?.methods?.[method?.key];
    if (!entry || page < 1 || page > Number(entry.ticketPagination?.totalPages || 1) || page === Number(entry.ticketPagination?.page)) return;
    state.ticketController?.abort();
    const controller = new AbortController();
    state.ticketController = controller;
    const generation = state.generation;
    panel.setAttribute("aria-busy", "true");
    panel.querySelectorAll(".effectiveness-ticket-pager button, .effectiveness-ticket-pager input").forEach(input => { input.disabled = true; });
    try {
      const result = await request(`/api/ml/effectiveness-tickets?type=${encodeURIComponent(report.type)}&predictionId=${encodeURIComponent(predictionId)}&page=${page}`, { signal: controller.signal });
      if (generation !== state.generation || state.ticketController !== controller || state.report !== report) return;
      if (result.type !== report.type || result.predictionId !== predictionId) throw new Error("Trang vé không khớp dự đoán đã khóa.");
      Object.assign(entry, { tickets: result.tickets, ticketResults: result.ticketResults, ticketPagination: result.ticketPagination });
      state.ticketPages.set(predictionId, { tickets: result.tickets, ticketResults: result.ticketResults, ticketPagination: result.ticketPagination, scoreKey: JSON.stringify([cycle.status, cycle.actualMain, cycle.actualSpecial]) });
      panel.innerHTML = cycleMethodHtml(cycle, method, report.type, reportSize(report));
    } catch (error) {
      if (error.name === "AbortError" || generation !== state.generation || state.report !== report) return;
      if (error.status === 401) { expireSession(); return; }
      showStatus(error.message, "error");
      panel.innerHTML = cycleMethodHtml(cycle, method, report.type, reportSize(report));
    } finally {
      panel.removeAttribute("aria-busy");
      if (state.ticketController === controller) state.ticketController = null;
      panel.querySelectorAll(".effectiveness-ticket-pager input").forEach(input => { input.disabled = false; });
      panel.querySelectorAll("[data-ticket-page]").forEach(button => { const target = Number(button.dataset.ticketPage); button.disabled = target < 1 || target > Number(entry.ticketPagination?.totalPages || 1); });
    }
  }

  function commitTicketPage(input) {
    if (input.disabled) return;
    const parsed = input.value.trim() ? Number(input.value) : NaN;
    const page = Number.isFinite(parsed) ? Math.max(1, Math.min(Number(input.max), Math.trunc(parsed))) : Number(input.defaultValue);
    input.value = page;
    void loadTicketPage(input.closest(".effectiveness-cycle-method"), page);
  }

  function cyclePagination(report) {
    const keno = report?.type === "KENO";
    const pageSize = keno ? 10 : 3;
    const total = keno ? Number(report.pagination?.total || 0) : (report?.cycles?.length || 0);
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    const requestedPage = keno ? Number(report.pagination?.page || state.page) : state.page;
    const page = Math.max(1, Math.min(totalPages, requestedPage));
    return { page, pageSize, totalPages, total, offset: (page - 1) * pageSize };
  }

  function renderCyclePager(report) {
    const pagination = cyclePagination(report);
    const { page, pageSize, totalPages, total, offset } = pagination;
    byId("effectivenessKenoPager").hidden = totalPages <= 1;
    byId("effectivenessKenoPageInfo").textContent = `Trang ${page} / ${totalPages} · Kỳ ${offset + 1}–${Math.min(total, offset + pageSize)} / ${total}${report.type === "KENO" ? ` · bậc ${report.level}` : ""}`;
    const first = Math.max(2, Math.min(page - 1, totalPages - 3));
    const pages = totalPages <= 7 ? Array.from({ length: totalPages }, (_, index) => index + 1)
      : [1, first, first + 1, first + 2, totalPages];
    byId("effectivenessCyclePages").innerHTML = pages.map((value, index) => `${index && value > pages[index - 1] + 1 ? '<span class="effectiveness-page-gap" aria-hidden="true">…</span>' : ""}<button type="button" class="secondary" data-cycle-page="${value}" aria-label="Trang kỳ ${value}"${value === page ? ' aria-current="page"' : ""}>${value}</button>`).join("");
  }

  function methodNavigationHtml(cycleKey, selected) {
    const id = `cycle-method-${encodeURIComponent(cycleKey)}`;
    return `<div class="effectiveness-method-navigation"><button type="button" class="secondary effectiveness-method-arrow" data-method-step="-1" aria-label="Cặp phương pháp trước">‹</button><div class="effectiveness-method-tabs" role="tablist" aria-label="Cặp phương pháp đối chiếu">${methodPairs.map(pair => `<button type="button" role="tab" id="${id}-${pair.key}-tab" data-cycle-method="${pair.key}" aria-controls="${id}-${pair.key}-pair" aria-selected="${pair.key === selected}" tabindex="${pair.key === selected ? 0 : -1}">${pair.methods.map(method => `<span>${escape(method.label)}</span>`).join('<span class="effectiveness-pair-divider" aria-hidden="true">|</span>')}</button>`).join("")}</div><button type="button" class="secondary effectiveness-method-arrow" data-method-step="1" aria-label="Cặp phương pháp tiếp theo">›</button></div>`;
  }

  function selectCycleMethod(view, key, focusTab = false) {
    const pair = methodPairs.find(item => item.methods.some(method => method.key === key));
    if (!view || !pair) return;
    state.selectedMethods.set(view.dataset.methodCycle, pair.key);
    view.querySelectorAll("[data-cycle-method]").forEach(tab => {
      const selected = tab.dataset.cycleMethod === pair.key;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected && focusTab) tab.focus({ preventScroll: true });
    });
    view.querySelectorAll("[data-method-pair]").forEach(panel => { panel.hidden = panel.dataset.methodPair !== pair.key; });
  }

  function renderCycles(report) {
    const pagination = cyclePagination(report);
    state.page = pagination.page;
    const allCycles = Array.isArray(report.cycles) ? report.cycles : [];
    const cycles = report.type === "KENO" ? allCycles.slice(0, 10) : allCycles.slice(pagination.offset, pagination.offset + 3);
    if (!cycles.length) {
      byId("effectivenessCycles").innerHTML = `<div class="effectiveness-empty"><strong>Chưa có lượt theo dõi thực tế.</strong><p>${report.canManage ? "Bật theo dõi tự động hoặc khóa kỳ tiếp theo để bắt đầu." : "Quản trị viên có thể bật theo dõi cho các kỳ sắp tới."} Các kỳ trong dữ liệu cũ không được thêm vào như dự đoán đã khóa.</p></div>`;
      return;
    }
    const game = reportGame(report);
    const mainCount = reportSize(report);
    byId("effectivenessCycles").innerHTML = cycles.map(cycle => {
      const actualList = Array.isArray(cycle.actualMain) ? cycle.actualMain : [];
      const actual = new Set(actualList.map(Number));
      const scored = cycle.status === "scored" || cycle.status === "complete" || actual.size > 0;
      const scoredText = scored ? "Đã chấm" : "Chờ kết quả";
      const cycleKey = game === "KENO" ? `${game}:${report.level}:cycle:${cycle.targetDrawId}` : `${game}:cycle:${cycle.targetDrawId}`;
      const selected = state.selectedMethods.get(cycleKey) || methods[0].key;
      const methodId = `cycle-method-${encodeURIComponent(cycleKey)}`;
      const lockedBudget = cycle.config?.ticketCountsByLevel?.[report.level] ?? cycle.config?.ticketCount;
      const budget = finite(lockedBudget) ? number(lockedBudget, 0) : Array.isArray(cycle.methods?.web?.tickets) ? String(cycle.methods.web.tickets.length) : "—";
      return `<details class="effectiveness-cycle${game === "KENO" ? " effectiveness-keno-cycle" : ""}" data-effectiveness-state="${escape(cycleKey)}"${opened(cycleKey)}><summary><span class="effectiveness-cycle-identity"><span><strong>Kỳ ${escape(cycle.targetDrawId)}</strong><span class="effectiveness-cycle-status${scored ? " is-scored" : ""}">${scoredText}</span></span><small>${game === "KENO" ? `Bậc ${mainCount} · Giờ quay` : "Hạn khóa"} ${escape(dateTime(cycle.deadline))}</small></span><span class="effectiveness-cycle-preview"><span class="effectiveness-preview-label">${actual.size ? "Số chính thực tế" : `${escape(budget)} vé / phương pháp đã khóa`}</span>${actual.size ? `${ticketHtml({ main: actualList }, new Set())}${actualSpecialHtml(cycle, game)}` : '<span class="effectiveness-waiting">Chờ dữ liệu kỳ quay</span>'}</span><span class="effectiveness-cycle-chevron" aria-hidden="true">⌄</span></summary><div class="effectiveness-cycle-body"><div class="effectiveness-method-view" data-method-cycle="${escape(cycleKey)}">${methodNavigationHtml(cycleKey, selected)}${methodPairs.map(pair => `<div class="effectiveness-cycle-methods effectiveness-paired-methods" id="${methodId}-${pair.key}-pair" role="tabpanel" aria-labelledby="${methodId}-${pair.key}-tab" data-method-pair="${pair.key}"${pair.key === selected ? "" : " hidden"}>${pair.methods.map(method => {
        const entry = cycle.methods?.[method.key] || {};
        const cached = state.ticketPages.get(entry.predictionId);
        if (cached?.scoreKey === JSON.stringify([cycle.status, cycle.actualMain, cycle.actualSpecial])) Object.assign(entry, { tickets: cached.tickets, ticketResults: cached.ticketResults, ticketPagination: cached.ticketPagination });
        else state.ticketPages.delete(entry.predictionId);
        return `<div class="effectiveness-cycle-method" id="${methodId}-${method.key}-panel" role="region" aria-label="${escape(method.label)}" data-prediction-id="${escape(entry.predictionId || '')}" data-method="${method.key}">${cycleMethodHtml(cycle, method, game, mainCount)}</div>`;
      }).join("")}</div>`).join("")}</div><p class="effectiveness-cycle-note">${game === "KENO" ? `Chỉ mở bộ số bậc ${mainCount}. Các bậc còn lại đã được khóa cùng kỳ; đổi bậc để xem.` : "Số trùng chỉ tính số chính. Nhãn giải do backend đối chiếu cơ cấu giải chuẩn; ĐB / bóng thứ 7 được xét riêng."}</p>${cycleInfoHtml(cycle, cycleKey, budget)}</div></details>`;
    }).join("");
  }

  function renderKeno(report) {
    const keno = report.type === "KENO";
    const host = byId("effectivenessKenoOverview");
    host.hidden = !keno;
    byId("effectivenessExplainer").textContent = keno
      ? "Theo dõi đồng thời 10 bậc. Chỉ mở chi tiết bậc đang chọn; nhật ký 10 kỳ/trang. So sánh dùng mọi kỳ đã chấm, cùng bậc và cùng ngân sách. Tỷ lệ có giải và trùng đủ số được tính riêng."
      : "Nhật ký 3 kỳ/trang; lựa chọn 30 / 100 / 300 giới hạn số kỳ trong nhật ký. Bảng so sánh dùng tất cả các kỳ đã chấm, mỗi kỳ có trọng số như nhau. Số trùng và tỷ lệ ≥3 / ≥4 xét từng vé, chỉ tính số chính. Đây chưa phải xác suất trúng ĐB hoặc Jackpot.";
    if (!keno) { host.innerHTML = ""; return; }
    const overviewKey = "KENO:overview";
    host.innerHTML = `<details class="effectiveness-keno-overview" data-effectiveness-state="${overviewKey}"${opened(overviewKey)}><summary><strong>Tổng quan 10 bậc</strong><span>Mở bảng · chọn bậc để xem chi tiết</span></summary><div class="effectiveness-table-wrap" tabindex="0" role="region" aria-label="Tổng quan mười bậc Keno"><table class="effectiveness-table effectiveness-keno-table"><caption><span>Số trùng trung bình / vé · tỷ lệ có giải</span></caption><thead><tr><th scope="col">Bậc</th>${methods.map(method => `<th scope="col"><span class="effectiveness-method-dot" style="background:${method.color}"></span>${escape(method.label)}</th>`).join("")}</tr></thead><tbody>${(Array.isArray(report.levels) ? report.levels : []).map(row => `<tr${Number(row.level) === Number(report.level) ? ' class="is-selected"' : ""}><th scope="row"><button type="button" class="secondary" data-keno-level="${Number(row.level)}" aria-pressed="${Number(row.level) === Number(report.level)}">Bậc ${Number(row.level)}</button><small>Ngẫu nhiên ${number(Number(row.level) / 4, 2)}</small></th>${methods.map(method => { const entry = row.methods?.[method.key] || {}; return `<td title="Chênh lệch so ngẫu nhiên cùng bậc: ${signed(entry.deltaVsRandom)}"><strong>${number(entry.meanHits, 2)}</strong><small>Có giải ${percent(entry.winningTicketRate)}</small></td>`; }).join("")}</tr>`).join("")}</tbody></table></div><p class="effectiveness-keno-caption">Mỗi bậc có mức trùng kỳ vọng khác nhau. So từng phương pháp với ngẫu nhiên cùng bậc; chưa chọn bậc tốt nhất từ bảng này.</p></details>`;
  }

  function render(report) {
    rememberOpenDetails();
    renderSummary(report);
    renderNotes(report);
    renderComparison(report);
    renderTimeline(report);
    renderCycles(report);
    renderCyclePager(report);
    renderKeno(report);
    const automationError = report.automation?.lastError;
    if (report.type === "KENO" && automationError) byId("effectivenessMixedWarning").innerHTML += `<p class="effectiveness-mixed-configurations"><strong>${String(automationError).includes("đến giờ quay") ? "Bỏ lỡ hạn khóa kỳ. Chờ cập nhật kết quả." : "Đang chờ dữ liệu / lần khóa mới."}</strong> ${escape(automationError)}</p>`;
    const sourceSync = report.automation?.sourceSync;
    if (report.type === "KENO" && report.settings?.enabled && sourceSync?.lastAttempt) {
      const sourceText = sourceSync.error ? "Tự cập nhật Keno đang chờ nguồn; sẽ thử lại."
        : `Tự cập nhật Keno · CSV kỳ ${sourceSync.latestKy || "—"}${sourceSync.latestTime ? ` lúc ${sourceSync.latestTime}` : ""} · kiểm tra ${dateTime(sourceSync.lastSuccess || sourceSync.lastAttempt)}`;
      byId("effectivenessMixedWarning").innerHTML += `<p class="effectiveness-mixed-configurations">${escape(sourceText)}</p>`;
    }
    setControls();
  }

  function labIsVisible() {
    return state.active && state.authenticated && !isKeno() && byId("effectivenessLab").open && !document.hidden;
  }

  function labIsRunning() {
    return ["queued", "running"].includes(lab.job?.state);
  }

  function setLabControls() {
    const canManage = state.authenticated && (lab.canManage || state.report?.canManage === true);
    const running = labIsRunning();
    byId("effectivenessLabAdmin").hidden = !canManage;
    ["effectivenessLabTickets", "effectivenessLabValidation", "effectivenessLabTest", "effectivenessLabRun"].forEach(id => { byId(id).disabled = !canManage || lab.loading || lab.busy || running; });
    byId("effectivenessLabCancel").hidden = !canManage || !running;
    byId("effectivenessLabCancel").disabled = !canManage || lab.busy;
    root.querySelectorAll("[data-lab-job]").forEach(button => { button.disabled = lab.loading || lab.busy || running; });
    const candidateActive = lab.tracking?.candidate?.status === "active";
    root.querySelectorAll("[data-lab-track-start]").forEach(button => { button.disabled = !canManage || lab.loading || lab.busy || candidateActive || !lab.job?.report?.conclusion?.canTrack; button.hidden = !canManage; });
    root.querySelectorAll("[data-lab-track-stop]").forEach(button => { button.disabled = !canManage || lab.loading || lab.busy || !candidateActive; button.hidden = !canManage; });
    byId("effectivenessLab").setAttribute("aria-busy", lab.loading || lab.busy || running ? "true" : "false");
  }

  function showLabStatus(message, error = false) {
    byId("effectivenessLabStatus").textContent = message;
    byId("effectivenessLabStatus").dataset.kind = error ? "error" : "";
  }

  function resetLab() {
    lab.serial += 1;
    lab.controller?.abort();
    lab.controller = null;
    clearTimeout(lab.timer);
    lab.timer = null;
    lab.job = null;
    lab.history = [];
    lab.tracking = null;
    lab.selectedJobId = null;
    lab.canManage = false;
    lab.loading = false;
    lab.busy = false;
    byId("effectivenessLabResult").innerHTML = "";
    byId("effectivenessLabHistory").innerHTML = "";
    byId("effectivenessLabHistoryCount").textContent = "0 lượt";
    byId("effectivenessLabHistoryDetails").open = false;
    byId("effectivenessLabTracking").innerHTML = "";
    showLabStatus(state.authenticated ? "Mở phòng thử để tải kết quả gần nhất của tài khoản." : "Đăng nhập để xem phòng thử.");
    setLabControls();
  }

  function expireSession() {
    state.generation += 1;
    state.authenticated = false;
    state.controller?.abort();
    state.controller = null;
    state.loading = false;
    state.busy = false;
    state.openDetails.clear();
    state.selectedMethods.clear();
    clearReport();
    byId("effectivenessAdmin").open = false;
    setHelpOpen(false);
    byId("effectivenessLab").open = false;
    resetLab();
    syncTimer();
    showStatus("Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại.", "error");
  }

  function validateLabJob(payload, type) {
    if (payload.job && (payload.job.type !== type || payload.job.report && payload.job.report.type !== type)) {
      throw new Error("Báo cáo thử nghiệm không khớp loại xổ số đang chọn.");
    }
    if (payload.type && payload.type !== type || (Array.isArray(payload.history) ? payload.history : []).some(row => row.type !== type) || payload.tracking?.type && payload.tracking.type !== type || payload.tracking?.candidate?.type && payload.tracking.candidate.type !== type) {
      throw new Error("Lịch sử hoặc ứng viên không khớp loại xổ số đang chọn.");
    }
  }

  function labProvenanceHtml(report) {
    const provenance = report.provenance || {};
    const registry = provenance.registryModel || {};
    const webRuns = (Array.isArray(report.folds) ? report.folds : []).map(fold => fold.methods?.web).filter(Boolean);
    const unique = values => [...new Set(values.filter(value => value !== null && value !== undefined && value !== "").map(String))].join(" · ");
    const engines = unique(webRuns.map(run => run.engine)) || provenance.requestedEngine || "Chưa có thông tin";
    const models = unique(webRuns.map(run => run.modelId)) || registry.modelId || (registry.mode === "legacy_classic" ? "Không có champion khi bắt đầu · engine classic" : "Chưa có thông tin");
    const fields = [["Engine web thực tế", engines], ["Model được giữ cố định", models],
      ["Dữ liệu đầu vào", "Mỗi lượt chỉ dùng lịch sử trước kỳ mục tiêu"],
      ["Huấn luyện trong phòng thử", "Giữ nguyên artifact · không huấn luyện lại từng kỳ"],
      ["Pipeline", report.pipeline], ["Model đã học đến kỳ", registry.trainedCutoff],
      ["Mã phiên bản nguồn", provenance.sourceHash], ["Mã dữ liệu", provenance.dataHash],
      ["Mã artifact", registry.artifactHash]];
    return `<dl class="effectiveness-info-list">${fields.filter(([, value]) => value !== null && value !== undefined && value !== "").map(([label, value]) => `<div><dt>${escape(label)}</dt><dd>${escape(value)}</dd></div>`).join("")}</dl>`;
  }

  function renderLabReport(report) {
    rememberOpenDetails();
    const rows = Array.isArray(report.methods) ? report.methods : [];
    const profiles = Array.isArray(report.profiles) ? report.profiles : [];
    const split = report.split || {};
    const selection = report.selection || {};
    const parameters = report.parameters || {};
    const conclusion = report.conclusion || {};
    const notes = Array.isArray(report.notes) ? report.notes.filter(note => typeof note === "string") : [];
    const candidate = rows.find(row => row.profileId === selection.candidateProfileId && row.kind === "candidate");
    const random = conclusion.evidence?.random || {};
    const status = ["insufficient_evidence", "no_clear_advantage", "possible_improvement"].includes(conclusion.status) ? conclusion.status : "insufficient_evidence";
    const title = conclusion.title || "Báo cáo lịch sử";
    const summary = conclusion.message || "Lượt thử này chưa so sánh các cấu hình mới. Chạy lượt thử mới để tìm và theo dõi ứng viên.";
    const reportKey = `${reportGame(report)}:lab:${lab.job?.id || "latest"}`;
    const candidateLabel = selection.candidateLabel || conclusion.candidateLabel || "Chưa có ứng viên cấu hình";
    const active = lab.tracking?.candidate?.status === "active";
    const sameRun = active && String(lab.tracking.candidate.runId) === String(lab.job?.id);
    byId("effectivenessLabResult").innerHTML = `<div class="effectiveness-lab-conclusion" data-conclusion="${status}"><span class="effectiveness-lab-kicker">Kết luận lượt thử</span><h4>${escape(title)}</h4><p>${escape(summary)}</p><div class="effectiveness-lab-outcome"><span><small>Ứng viên được chọn</small><strong>${escape(candidateLabel)}</strong></span><span><small>Kiểm tra giữ riêng</small><strong>${number(conclusion.sampleCount ?? split.test?.count, 0)} kỳ</strong></span><span><small>Brier so ngẫu nhiên · thấp hơn tốt hơn</small><strong>${finite(random.brierDelta) ? `${Number(random.brierDelta) > 0 ? "+" : ""}${number(random.brierDelta, 5)}` : "—"}</strong></span></div>${conclusion.recommendation ? `<p class="effectiveness-lab-next">${escape(conclusion.recommendation)}</p>` : ""}${conclusion.canTrack === true && selection.candidateProfileId ? `<div class="effectiveness-lab-action"><button type="button" class="secondary" data-lab-track-start>Theo dõi ứng viên trên kỳ mới</button><span>${sameRun ? "Ứng viên này đang được theo dõi." : active ? "Dừng ứng viên đang theo dõi trước khi chọn cấu hình khác." : "Khóa bộ số trước quay · đối chiếu với web và ngẫu nhiên."}</span></div>` : ""}</div>
      <details class="effectiveness-lab-detail effectiveness-lab-comparison" data-effectiveness-state="${escape(reportKey)}:comparison"${opened(`${reportKey}:comparison`)}><summary>So sánh cấu hình và đối chứng <span>${rows.length} phương pháp</span></summary><div class="effectiveness-lab-split">${[["training", "Lịch sử ban đầu"], ["validation", "Chọn cấu hình"], ["test", "Kiểm tra giữ riêng"]].map(([key, label]) => `<span><strong>${escape(label)} · ${number(split[key]?.count, 0)} kỳ</strong><small>Kỳ ${escape(split[key]?.firstDrawId ?? "—")} → ${escape(split[key]?.lastDrawId ?? "—")}</small></span>`).join("")}</div>
      <p class="effectiveness-lab-selection"><strong>${escape(selection.label || methodLabel(selection.selectedMethod || "")) || "Chưa có lựa chọn"}</strong> được chọn trước khi chấm tập kiểm tra phía sau. Điểm kiểm tra không dùng để chọn lại thuật toán. ${number(parameters.ticketCount, 0)} vé / phương pháp / kỳ.</p>
      <div class="effectiveness-table-wrap"><table class="effectiveness-table effectiveness-comparison-table"><caption><strong>Kiểm tra lịch sử ngoài mẫu</strong><span>Cấu hình cố định trước tập test · không phải dự đoán tương lai đã khóa</span></caption><thead><tr><th scope="col">Phương pháp</th><th scope="col">Brier validation</th><th scope="col">Brier test</th><th scope="col">Trùng / vé test</th><th scope="col">Số trùng so với ngẫu nhiên</th><th scope="col">Nhận định test</th></tr></thead><tbody>${rows.map(row => {
        const test = row.test || {};
        const selected = row.key === selection.selectedMethod;
        const chosenProfile = row === candidate;
        return `<tr${chosenProfile ? ' class="effectiveness-lab-candidate-row"' : ""}><th scope="row">${escape(row.label || methodLabel(row.key))}${selected ? '<small class="effectiveness-lab-selected">Thấp nhất trên tập chọn</small>' : chosenProfile ? '<small class="effectiveness-lab-selected">Ứng viên cấu hình</small>' : `<small>${row.kind === "candidate" ? "Cấu hình thử" : "Đối chứng"} · ${number(test.sampleCount, 0)} kỳ test</small>`}</th><td data-label="Brier validation">${number(row.validation?.brierScore, 5)}</td><td data-label="Brier test">${number(test.brierScore, 5)}</td><td data-label="Trùng / vé test" class="effectiveness-mean">${number(test.meanHits)}</td><td data-label="So với ngẫu nhiên"><strong>${signed(test.deltaVsRandom)}</strong><small class="effectiveness-ci">95% ${interval(test.ci95)}</small></td><td data-label="Nhận định test" class="effectiveness-decision">${escape(decisionText({ ...test, key: row.key }))}</td></tr>`;
      }).join("")}</tbody></table></div>
      </details>${profiles.length ? `<details class="effectiveness-lab-detail effectiveness-lab-profiles" data-effectiveness-state="${escape(reportKey)}:profiles"${opened(`${reportKey}:profiles`)}><summary>Các cấu hình được thử <span>${profiles.length} cấu hình</span></summary><div class="effectiveness-lab-profile-grid">${profiles.map(profile => `<div><strong>${escape(profile.label || profile.id)}</strong><p>${escape(profile.description || "")}</p><small>${profile.historyWindow === null ? "Toàn bộ lịch sử" : `${number(profile.historyWindow, 0)} kỳ lịch sử`} · ${number(profile.recentWindow, 0)} kỳ gần · ${profile.allocation === "aggressive" ? "Phân bổ mạnh" : "Phân bổ ổn định"}</small></div>`).join("")}</div></details>` : ""}
      <details class="effectiveness-lab-detail effectiveness-lab-provenance" data-effectiveness-state="${escape(reportKey)}:provenance"${opened(`${reportKey}:provenance`)}><summary>Chỉ số và ghi chú thử nghiệm</summary><p>Validation là tập chọn cấu hình; test là tập kiểm tra giữ riêng. Brier / log-loss càng thấp càng tốt. Giữ nguyên artifact model, không huấn luyện lại mỗi kỳ. Tỷ lệ trùng xét số chính trên từng vé; kết quả lịch sử không bảo đảm kỳ sau và không tự nâng model.</p>${conclusion.evidence ? `<div class="effectiveness-table-wrap"><table class="effectiveness-table"><caption><strong>Ứng viên so với đối chứng</strong><span>Chênh lệch Brier / log-loss âm là tốt hơn</span></caption><thead><tr><th>Đối chứng</th><th>Δ Brier</th><th>Khoảng 95% Δ Brier</th><th>Δ Log-loss</th></tr></thead><tbody>${["random", "web"].map(key => { const evidence = conclusion.evidence[key] || {}; return `<tr><th scope="row">${escape(methodLabel(key))}</th><td>${number(evidence.brierDelta, 5)}</td><td>${evidence.brierCi95 && finite(evidence.brierCi95.lower) && finite(evidence.brierCi95.upper) ? `[${number(evidence.brierCi95.lower, 5)}; ${number(evidence.brierCi95.upper, 5)}]` : "—"}</td><td>${number(evidence.logLossDelta, 5)}</td></tr>`; }).join("")}</tbody></table></div>` : ""}<div class="effectiveness-table-wrap"><table class="effectiveness-table"><thead><tr><th>Phương pháp</th><th>Log-loss test</th><th>Trùng ≥3</th><th>Trùng ≥4</th></tr></thead><tbody>${rows.map(row => `<tr><th scope="row">${escape(row.label || methodLabel(row.key))}</th><td>${number(row.test?.logLoss, 5)}</td><td>${percent(row.test?.rate3)}</td><td>${percent(row.test?.rate4)}</td></tr>`).join("")}</tbody></table></div>${conclusion.highPrizeNote ? `<p>${escape(conclusion.highPrizeNote)}</p>` : ""}${labProvenanceHtml(report)}${selection.reason ? `<p>${escape(selection.reason)}</p>` : ""}${notes.length ? `<ul>${notes.map(note => `<li>${escape(note)}</li>`).join("")}</ul>` : ""}</details>`;
  }

  function renderLabHistory() {
    const history = lab.history;
    byId("effectivenessLabHistoryCount").textContent = `${history.length} lượt`;
    byId("effectivenessLabHistory").innerHTML = history.length ? `<div class="effectiveness-lab-history-list">${history.map(row => `<button type="button" class="secondary effectiveness-lab-history-item" data-lab-job="${escape(row.id)}" aria-pressed="${String(row.id) === String(lab.job?.id)}"><span><strong>${escape(row.candidateLabel || methodLabel(row.selectedMethod || "") || "Báo cáo lịch sử")}</strong><small>${escape(dateTime(row.finishedAt || row.createdAt))} · ${number(row.ticketCount, 0)} vé · ${number(row.validationCount, 0)} + ${number(row.testCount, 0)} kỳ</small></span><span>${escape(typeof row.conclusion === "object" ? row.conclusion?.title || "Xem báo cáo" : row.conclusion || "Xem báo cáo")}</span></button>`).join("")}</div><p>Lượt thử được lưu trên server và giữ lại khi khởi động lại.</p>` : '<p>Chưa có báo cáo đã lưu. Chạy thử để so sánh các cấu hình.</p>';
  }

  function renderLabTracking() {
    rememberOpenDetails();
    const tracking = lab.tracking;
    const candidate = tracking?.candidate;
    const host = byId("effectivenessLabTracking");
    if (!candidate) { host.innerHTML = ""; return; }
    const game = tracking.type || byId("effectivenessType").value;
    const counts = tracking.counts || {};
    const rows = Array.isArray(tracking.methods) ? tracking.methods : [];
    const cycles = (Array.isArray(tracking.cycles) ? tracking.cycles : []).slice(0, 6);
    const active = candidate.status === "active";
    const key = `${game}:lab:tracking:${candidate.id}`;
    host.innerHTML = `<div class="effectiveness-lab-tracking"><div class="effectiveness-lab-tracking-head"><div><span class="effectiveness-lab-kicker">Theo dõi trên kỳ mới</span><h4>${escape(candidate.label || candidate.profileId)}</h4></div><span class="effectiveness-lab-tracking-state${active ? " is-active" : ""}">${active ? "Đang theo dõi" : "Đã dừng tạo kỳ mới"}</span>${active ? '<button type="button" class="secondary" data-lab-track-stop>Dừng theo dõi</button>' : ""}</div><div class="effectiveness-lab-tracking-counts"><span><strong>${number(counts.scored, 0)}</strong> kỳ đã chấm</span><span><strong>${number(counts.locked, 0)}</strong> kỳ chờ kết quả</span><span>${number(candidate.ticketCount, 0)} vé / phương pháp</span></div><p class="effectiveness-lab-tracking-note">${escape(tracking.conclusion?.title || "Chờ đủ kỳ thực tế để đánh giá")}${tracking.conclusion?.summary ? ` · ${escape(tracking.conclusion.summary)}` : ""}</p>${candidate.lastError ? `<p class="effectiveness-lab-tracking-error">${escape(candidate.lastError)}</p>` : ""}<details class="effectiveness-lab-detail" data-effectiveness-state="${escape(key)}:comparison"${opened(`${key}:comparison`)}><summary>So sánh trên kết quả thực tế <span>Ứng viên · Web · Ngẫu nhiên</span></summary><div class="effectiveness-table-wrap"><table class="effectiveness-table effectiveness-comparison-table"><thead><tr><th scope="col">Phương pháp</th><th scope="col">Trùng / vé</th><th scope="col">Brier</th><th scope="col">Trùng ≥3 / ≥4</th><th scope="col">Số trùng so ngẫu nhiên</th></tr></thead><tbody>${rows.map(row => `<tr><th scope="row">${escape(row.label || methodLabel(row.key))}<small>${number(row.sampleCount, 0)} kỳ thực tế</small></th><td data-label="Trùng / vé">${number(row.meanHits)}</td><td data-label="Brier">${number(row.brierScore, 5)}</td><td data-label="Trùng ≥3 / ≥4">${percent(row.rate3)} / ${percent(row.rate4)}</td><td data-label="So ngẫu nhiên"><strong>${signed(row.deltaVsRandom)}</strong><small class="effectiveness-ci">95% ${interval(row.ci95)}</small></td></tr>`).join("")}</tbody></table></div></details><details class="effectiveness-lab-detail effectiveness-lab-tracking-journal" data-effectiveness-state="${escape(key)}:journal"${opened(`${key}:journal`, true)}><summary>Bộ số đã khóa trước quay <span>${cycles.length} kỳ gần nhất</span></summary><div class="effectiveness-cycles">${cycles.length ? cycles.map(cycle => {
      const actualList = Array.isArray(cycle.actualMain) ? cycle.actualMain : [];
      const actual = new Set(actualList.map(Number));
      const cycleKey = `${key}:cycle:${cycle.id || cycle.targetDrawId}`;
      return `<details class="effectiveness-cycle" data-effectiveness-state="${escape(cycleKey)}"${opened(cycleKey)}><summary><span class="effectiveness-cycle-identity"><span><strong>Kỳ ${escape(cycle.targetDrawId)}</strong><span class="effectiveness-cycle-status${actual.size ? " is-scored" : ""}">${actual.size ? "Đã chấm" : "Chờ kết quả"}</span></span><small>Khóa ${escape(dateTime(cycle.createdAt))}</small></span><span class="effectiveness-cycle-preview"><span class="effectiveness-preview-label">${actual.size ? "Số chính thực tế" : `${number(candidate.ticketCount, 0)} vé / phương pháp đã khóa`}</span>${actual.size ? ticketHtml({ main: actualList }, new Set()) + actualSpecialHtml(cycle, game) : '<span class="effectiveness-waiting">Chờ dữ liệu kỳ quay</span>'}</span><span class="effectiveness-cycle-chevron" aria-hidden="true">⌄</span></summary><div class="effectiveness-cycle-body"><div class="effectiveness-cycle-methods effectiveness-lab-cycle-methods">${["candidate", "web", "random"].map(methodKey => {
        const entry = cycle.methods?.[methodKey] || {};
        const tickets = Array.isArray(entry.tickets) ? entry.tickets : [];
        const results = Array.isArray(entry.ticketResults) ? entry.ticketResults : [];
        const label = methodKey === "candidate" ? candidate.label || "Ứng viên" : methodLabel(methodKey);
        return `<div class="effectiveness-cycle-method"><div class="effectiveness-cycle-method-head"><strong>${escape(label)}</strong><span>${actual.size ? `TB ${number(entry.meanHits, 2)} số / vé` : `${tickets.length} vé đã khóa`}</span></div><div class="effectiveness-ticket-list">${tickets.map((ticket, index) => ticketRowHtml(ticket, actual, index, game === "LOTO_5_35" ? 5 : 6, results.find(result => Number(result.ticketIndex) === index + 1) || results[index], game === "LOTO_6_55")).join("")}</div></div>`;
      }).join("")}</div><p class="effectiveness-lab-cycle-cutoff">Dữ liệu đến kỳ ${escape(cycle.cutoffDrawId)} · hạn khóa ${escape(dateTime(cycle.deadline))}</p></div></details>`;
    }).join("") : '<p>Server sẽ khóa bộ số khi có kỳ hợp lệ tiếp theo. Mở lại mục này để đối chiếu kết quả.</p>'}</div></details><p class="effectiveness-lab-tracking-footnote">Ứng viên chạy song song với dự đoán web. Dừng theo dõi vẫn giữ bộ số đã khóa và tiếp tục chấm kỳ đang chờ.</p></div>`;
  }

  function applyLabPayload(payload, type) {
    validateLabJob(payload, type);
    if (typeof payload.canManage === "boolean") lab.canManage = payload.canManage;
    if (Object.prototype.hasOwnProperty.call(payload, "job")) lab.job = payload.job || null;
    if (Array.isArray(payload.history)) lab.history = payload.history;
    if (Object.prototype.hasOwnProperty.call(payload, "tracking")) lab.tracking = payload.tracking || null;
    renderLabJob();
  }

  function renderLabJob() {
    rememberOpenDetails();
    const job = lab.job;
    byId("effectivenessLabResult").innerHTML = "";
    if (!job) {
      showLabStatus("Tài khoản chưa có lượt thử cho loại xổ số này.");
    } else if (labIsRunning()) {
      const total = Number(job.progress?.total) || Number(job.validationCount) + Number(job.testCount);
      const completed = Math.max(0, Math.min(total, Number(job.progress?.completed) || 0));
      showLabStatus(`Đang chạy thử · đã xử lý ${number(completed, 0)}/${number(total, 0)} kỳ (${number(job.validationCount, 0)} chọn cấu hình + ${number(job.testCount, 0)} kiểm tra). Có thể đóng phòng thử và quay lại sau.`);
    } else if (job.state === "completed" && job.report) {
      showLabStatus(`Hoàn tất ${dateTime(job.finishedAt || job.createdAt)} · báo cáo riêng của tài khoản.`);
      renderLabReport(job.report);
    } else if (job.state === "cancelled") {
      showLabStatus("Đã hủy lượt thử. Không có model sản xuất nào được thay đổi.");
    } else {
      showLabStatus(String(job.error || "Lượt thử chưa có báo cáo hoàn chỉnh."), true);
    }
    renderLabTracking();
    renderLabHistory();
    setLabControls();
  }

  function scheduleLabPoll() {
    clearTimeout(lab.timer);
    lab.timer = null;
    if (labIsVisible() && !lab.busy && (labIsRunning() || lab.tracking?.candidate?.status === "active" || Number(lab.tracking?.counts?.locked) > 0)) lab.timer = setTimeout(() => void loadLab(), labIsRunning() ? 2000 : 60000);
  }

  function pauseLab() {
    clearTimeout(lab.timer);
    lab.timer = null;
    if (lab.loading) {
      lab.serial += 1;
      lab.controller?.abort();
      lab.controller = null;
      lab.loading = false;
    }
    setLabControls();
  }

  async function loadLab() {
    if (!labIsVisible() || lab.loading || lab.busy) return;
    const serial = ++lab.serial;
    const generation = state.generation;
    const type = byId("effectivenessType").value;
    const controller = new AbortController();
    lab.controller?.abort();
    lab.controller = controller;
    lab.loading = true;
    if (!lab.job) showLabStatus("Đang tải kết quả thử nghiệm…");
    setLabControls();
    try {
      const jobId = lab.selectedJobId || lab.job?.id;
      const payload = await request(`/api/ml/algorithm-lab?type=${encodeURIComponent(type)}${jobId ? `&jobId=${encodeURIComponent(jobId)}` : ""}`, { signal: controller.signal });
      if (serial !== lab.serial || generation !== state.generation || type !== byId("effectivenessType").value) return;
      applyLabPayload(payload, type);
    } catch (error) {
      if (error.name !== "AbortError" && serial === lab.serial && generation === state.generation) {
        if (error.status === 401) { expireSession(); return; }
        showLabStatus(error.message, true);
      }
    } finally {
      if (serial === lab.serial) {
        lab.loading = false;
        lab.controller = null;
        setLabControls();
        scheduleLabPoll();
      }
    }
  }

  async function runLab(cancel = false) {
    if (!state.authenticated || !(lab.canManage || state.report?.canManage === true) || lab.busy || lab.loading || !cancel && labIsRunning()) return;
    const type = byId("effectivenessType").value;
    const form = { type };
    if (cancel) {
      if (!lab.job?.id) return;
      form.action = "cancel";
      form.jobId = lab.job.id;
    } else {
      const ticketCount = Number(byId("effectivenessLabTickets").value);
      const validationCount = Number(byId("effectivenessLabValidation").value);
      const testCount = Number(byId("effectivenessLabTest").value);
      if (!Number.isInteger(ticketCount) || ticketCount < 1 || ticketCount > 10 || !Number.isInteger(validationCount) || validationCount < 5 || validationCount > 50 || !Number.isInteger(testCount) || testCount < 5 || testCount > 50 || validationCount + testCount > 100) {
        showLabStatus("Chọn 1–10 vé; validation và test mỗi tập 5–50 kỳ, tổng không quá 100 kỳ.", true); return;
      }
      Object.assign(form, { ticketCount: String(ticketCount), validationCount: String(validationCount), testCount: String(testCount) });
    }
    const serial = ++lab.serial;
    const generation = state.generation;
    const controller = new AbortController();
    lab.controller?.abort();
    lab.controller = controller;
    clearTimeout(lab.timer);
    lab.busy = true;
    setLabControls();
    showLabStatus(cancel ? "Đang hủy lượt thử…" : "Đang bắt đầu thử nghiệm…");
    try {
      const payload = await request("/api/ml/algorithm-lab", { method: "POST", form, signal: controller.signal });
      if (serial !== lab.serial || generation !== state.generation || type !== byId("effectivenessType").value) return;
      lab.selectedJobId = null;
      applyLabPayload(payload, type);
    } catch (error) {
      if (error.name !== "AbortError" && serial === lab.serial && generation === state.generation) {
        if (error.status === 401) { expireSession(); return; }
        showLabStatus(error.message, true);
      }
    } finally {
      if (serial === lab.serial) {
        lab.busy = false;
        lab.controller = null;
        setLabControls();
        scheduleLabPoll();
      }
    }
  }

  async function mutateLabTracking(action) {
    if (!state.authenticated || !(lab.canManage || state.report?.canManage === true) || lab.busy || lab.loading) return;
    const type = byId("effectivenessType").value;
    const form = { type, action };
    if (action === "start_tracking") {
      if (!lab.job?.id || !lab.job.report?.conclusion?.canTrack || !lab.job.report.selection?.candidateProfileId || lab.tracking?.candidate?.status === "active") return;
      form.jobId = String(lab.job.id);
    } else {
      if (!lab.tracking?.candidate?.id || lab.tracking.candidate.status !== "active") return;
      form.candidateId = String(lab.tracking.candidate.id);
    }
    const serial = ++lab.serial;
    const generation = state.generation;
    const controller = new AbortController();
    lab.controller?.abort();
    lab.controller = controller;
    clearTimeout(lab.timer);
    lab.busy = true;
    setLabControls();
    showLabStatus(action === "start_tracking" ? "Đang bật theo dõi ứng viên trên kỳ mới…" : "Đang dừng tạo kỳ mới cho ứng viên…");
    let succeeded = false;
    try {
      const payload = await request("/api/ml/algorithm-lab", { method: "POST", form, signal: controller.signal });
      if (serial !== lab.serial || generation !== state.generation || type !== byId("effectivenessType").value) return;
      applyLabPayload(payload, type);
      succeeded = true;
      showLabStatus(action === "start_tracking" ? "Đã bật theo dõi. Xem bộ số được khóa trước quay ở bên dưới." : "Đã dừng tạo kỳ mới. Các kỳ đang chờ vẫn được chấm khi có kết quả.");
    } catch (error) {
      if (error.name !== "AbortError" && serial === lab.serial && generation === state.generation) {
        if (error.status === 401) { expireSession(); return; }
        showLabStatus(error.message, true);
      }
    } finally {
      if (serial === lab.serial) {
        lab.busy = false;
        lab.controller = null;
        setLabControls();
        scheduleLabPoll();
      }
    }
    if (succeeded && serial === lab.serial && labIsVisible()) await loadLab();
  }

  function clearReport() {
    state.ticketController?.abort();
    state.ticketController = null;
    state.ticketPages.clear();
    state.report = null;
    ["effectivenessSummary", "effectivenessMixedWarning", "effectivenessReportNotes", "effectivenessComparison", "effectivenessTimeline", "effectivenessCycles", "effectivenessKenoOverview"].forEach(id => { byId(id).innerHTML = ""; });
    byId("effectivenessTimeline").hidden = true;
    byId("effectivenessKenoOverview").hidden = true;
    byId("effectivenessKenoPager").hidden = true;
    byId("effectivenessUpdated").textContent = "";
    setControls();
  }

  async function refresh({ statusAfter = "", scrollAnchor = null, scrollToCycles = false } = {}) {
    if (!state.authenticated || !state.active || state.busy) return;
    state.controller?.abort();
    state.ticketController?.abort();
    state.ticketController = null;
    const controller = new AbortController();
    state.controller = controller;
    const generation = state.generation;
    const type = byId("effectivenessType").value;
    const limit = byId("effectivenessLimit").value;
    const level = byId("effectivenessKenoLevel").value;
    const page = state.page;
    state.loading = true;
    setControls();
    showStatus("Đang tải báo cáo…");
    try {
      const report = await request(`/api/ml/effectiveness?type=${encodeURIComponent(type)}&limit=${encodeURIComponent(limit)}${type === "KENO" ? `&level=${encodeURIComponent(level)}&page=${page}` : ""}`, { signal: controller.signal });
      if (generation !== state.generation || state.controller !== controller || byId("effectivenessType").value !== type) return;
      if (report.type !== type) throw new Error("Báo cáo hiệu quả không khớp loại xổ số đang chọn.");
      if (type === "KENO" && (String(report.level) !== level || page !== state.page || level !== byId("effectivenessKenoLevel").value)) return;
      const keepPosition = scrollAnchor && Math.abs(window.scrollY - scrollAnchor.scrollY) < 2;
      state.report = report;
      render(report);
      if (scrollToCycles) root.querySelector(".effectiveness-history-head").scrollIntoView({ behavior: "smooth", block: "start" });
      byId("effectivenessUpdated").textContent = `Cập nhật ${dateTime(new Date().toISOString())}`;
      showStatus(statusAfter || (Number(report.counts?.scored) ? "Báo cáo đã cập nhật." : "Chưa có kỳ đã chấm. Đang chờ kết quả thực tế."));
      if (keepPosition) window.scrollBy({ top: scrollAnchor.element.getBoundingClientRect().top - scrollAnchor.top, left: 0, behavior: "instant" });
    } catch (error) {
      if (error.name === "AbortError" || generation !== state.generation || state.controller !== controller) return;
      if (error.status === 401) { expireSession(); return; }
      if (type === "KENO" && state.report?.type === type) byId("effectivenessKenoLevel").value = String(state.report.level);
      showStatus(error.message, "error");
    } finally {
      if (state.controller === controller) {
        state.loading = false;
        state.controller = null;
        setControls();
      }
    }
  }

  async function mutate(action) {
    if (!state.report?.canManage || state.busy || state.loading || !state.authenticated) return;
    const generation = state.generation;
    const type = byId("effectivenessType").value;
    const form = { type };
    if (action === "settings") {
      normalizeTicketCount(true);
      const ticketCount = Number(byId("effectivenessTicketCount").value);
      const maximum = ticketMaximum();
      if (!Number.isInteger(ticketCount) || ticketCount < 1 || ticketCount > maximum) { showStatus(`Số vé phải là số nguyên từ 1 đến ${maximum}.`, "error"); return; }
      form.enabled = String(byId("effectivenessEnabled").checked);
      form.ticketCount = String(ticketCount);
    }
    state.busy = true;
    setControls();
    showStatus(action === "settings" ? "Đang lưu cấu hình…" : "Đang tạo và khóa bộ số của bốn phương pháp…");
    let message = "", failed = false;
    try {
      const response = await request(`/api/ml/effectiveness-${action === "settings" ? "settings" : "cycle"}`, { method: "POST", form });
      if (generation !== state.generation) return;
      message = action === "settings" ? "Đã lưu cấu hình. Kỳ đã khóa giữ nguyên bộ số và số vé." : String(response.message || "Đã xử lý khóa kỳ tiếp theo. Mở nhật ký để xem bộ số.");
    } catch (error) {
      if (generation !== state.generation) return;
      failed = true;
      message = error.message;
    } finally {
      if (generation === state.generation) {
        state.busy = false;
        setControls();
      }
    }
    if (generation !== state.generation) return;
    if (failed) showStatus(message, "error");
    else await refresh({ statusAfter: message });
  }

  function syncTimer() {
    if (state.timer) { clearInterval(state.timer); state.timer = null; }
    if (state.active && state.authenticated) {
      state.timer = setInterval(() => { if (!document.hidden && !state.loading && !state.busy && !state.ticketController) void refresh(); }, isKeno() ? 60000 : 120000);
    }
  }

  window.VietlottEffectiveness = Object.freeze({
    activate(active) {
      const changed = state.active !== !!active;
      state.active = !!active;
      syncTimer();
      if (state.active && state.authenticated && (changed || !state.report)) void refresh();
      if (state.active && labIsVisible() && changed) void loadLab();
      if (!state.active) { state.controller?.abort(); state.ticketController?.abort(); state.ticketController = null; state.loading = false; setSettingsOpen(false); setHelpOpen(false); setControls(); }
      if (!state.active) pauseLab();
    },
  });
  window.addEventListener("dvlf:auth-changed", event => {
    state.generation += 1;
    state.authenticated = event.detail?.authenticated === true;
    state.controller?.abort();
    state.controller = null;
    state.busy = false;
    state.loading = false;
    state.openDetails.clear();
    state.selectedMethods.clear();
    state.page = 1;
    byId("effectivenessAdmin").open = false;
    setHelpOpen(false);
    clearReport();
    byId("effectivenessLab").open = false;
    resetLab();
    showStatus(state.authenticated ? "Mở tab Hiệu quả dự đoán để tải báo cáo." : "Đăng nhập để xem báo cáo.");
    syncTimer();
    if (state.active && state.authenticated) void refresh();
  });
  root.addEventListener("toggle", event => {
    if (event.target.matches("details[data-effectiveness-state]") && root.contains(event.target)) state.openDetails.set(event.target.dataset.effectivenessState, event.target.open);
  }, true);
  byId("effectivenessLab").addEventListener("toggle", () => { if (labIsVisible()) void loadLab(); else pauseLab(); });
  ["effectivenessType", "effectivenessLimit"].forEach(id => byId(id).addEventListener("change", () => {
    setSettingsOpen(false);
    setHelpOpen(false);
    rememberOpenDetails(); clearReport();
    state.page = 1;
    if (id === "effectivenessType") { resetLab(); syncTimer(); }
    void refresh();
    if (id === "effectivenessType" && labIsVisible()) void loadLab();
  }));
  byId("effectivenessKenoLevel").addEventListener("change", () => { rememberOpenDetails(); void refresh(); });
  root.addEventListener("click", event => {
    const button = event.target.closest("[data-keno-level]");
    if (!button || !isKeno() || button.disabled || state.busy || byId("effectivenessKenoLevel").value === button.dataset.kenoLevel) return;
    const anchorElement = button.closest("#effectivenessKenoLevels") ? root.querySelector(".effectiveness-history-head") : null;
    const scrollAnchor = anchorElement ? { element: anchorElement, top: anchorElement.getBoundingClientRect().top, scrollY: window.scrollY } : null;
    byId("effectivenessKenoLevel").value = button.dataset.kenoLevel;
    rememberOpenDetails();
    void refresh({ scrollAnchor });
  });
  function goCyclePage(page) {
    const pagination = cyclePagination(state.report);
    if (!state.authenticated || !state.report || state.busy || state.loading || !Number.isInteger(page) || page < 1 || page > pagination.totalPages || page === pagination.page) return;
    rememberOpenDetails();
    state.page = page;
    if (isKeno()) { clearReport(); void refresh({ scrollToCycles: true }); }
    else {
      renderCycles(state.report);
      renderCyclePager(state.report);
      setControls();
      root.querySelector(".effectiveness-history-head").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }
  byId("effectivenessKenoPrevious").addEventListener("click", () => goCyclePage(state.page - 1));
  byId("effectivenessKenoNext").addEventListener("click", () => goCyclePage(state.page + 1));
  byId("effectivenessCyclePages").addEventListener("click", event => {
    const button = event.target.closest("[data-cycle-page]");
    if (button && !button.disabled) goCyclePage(Number(button.dataset.cyclePage));
  });
  byId("effectivenessRefresh").addEventListener("click", () => void refresh());
  byId("effectivenessCycles").addEventListener("click", event => {
    const methodButton = event.target.closest("[data-cycle-method], [data-method-step]");
    if (methodButton) {
      const view = methodButton.closest(".effectiveness-method-view");
      const current = view.querySelector('[data-cycle-method][aria-selected="true"]')?.dataset.cycleMethod;
      const index = methodPairs.findIndex(pair => pair.key === current);
      const key = methodButton.dataset.cycleMethod || methodPairs[(index + Number(methodButton.dataset.methodStep) + methodPairs.length) % methodPairs.length].key;
      selectCycleMethod(view, key);
      return;
    }
    const button = event.target.closest("[data-ticket-page]");
    if (button && !button.disabled) void loadTicketPage(button.closest(".effectiveness-cycle-method"), Number(button.dataset.ticketPage));
  });
  byId("effectivenessCycles").addEventListener("keydown", event => {
    if (event.target.matches("[data-ticket-jump]") && event.key === "Enter") {
      event.preventDefault();
      commitTicketPage(event.target);
      return;
    }
    const tab = event.target.closest("[data-cycle-method]");
    if (!tab || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const index = methodPairs.findIndex(pair => pair.key === tab.dataset.cycleMethod);
    const next = event.key === "Home" ? 0 : event.key === "End" ? methodPairs.length - 1 : (index + (event.key === "ArrowLeft" ? -1 : 1) + methodPairs.length) % methodPairs.length;
    selectCycleMethod(tab.closest(".effectiveness-method-view"), methodPairs[next].key, true);
  });
  byId("effectivenessCycles").addEventListener("change", event => {
    if (event.target.matches("[data-ticket-jump]")) commitTicketPage(event.target);
  });
  byId("effectivenessSettings").addEventListener("click", () => setSettingsOpen(!byId("effectivenessAdmin").open));
  byId("effectivenessHelpButton").addEventListener("click", () => setHelpOpen(!byId("effectivenessHelpPanel").open));
  byId("effectivenessHelpPanel").addEventListener("toggle", () => {
    byId("effectivenessHelpButton").setAttribute("aria-expanded", String(byId("effectivenessHelpPanel").open));
  });
  byId("effectivenessAdmin").addEventListener("toggle", () => {
    byId("effectivenessSettings").setAttribute("aria-expanded", String(byId("effectivenessAdmin").open));
  });
  document.addEventListener("click", event => {
    if (byId("effectivenessAdmin").open && !event.target.closest(".effectiveness-toolbar-actions")) setSettingsOpen(false);
    if (byId("effectivenessHelpPanel").open && !event.target.closest(".effectiveness-toolbar-actions")) setHelpOpen(false);
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && byId("effectivenessAdmin").open) { event.preventDefault(); setSettingsOpen(false, true); }
    if (event.key === "Escape" && byId("effectivenessHelpPanel").open) { event.preventDefault(); setHelpOpen(false, true); }
  });
  byId("effectivenessSave").addEventListener("click", () => void mutate("settings"));
  byId("effectivenessTicketCount").addEventListener("input", () => normalizeTicketCount());
  byId("effectivenessTicketCount").addEventListener("change", () => normalizeTicketCount(true));
  byId("effectivenessTicketCount").addEventListener("blur", () => normalizeTicketCount(true));
  byId("effectivenessLock").addEventListener("click", () => void mutate("cycle"));
  byId("effectivenessLabRun").addEventListener("click", () => void runLab());
  byId("effectivenessLabCancel").addEventListener("click", () => void runLab(true));
  byId("effectivenessLab").addEventListener("click", event => {
    const button = event.target.closest("button");
    if (!button || button.disabled) return;
    if (button.hasAttribute("data-lab-track-start")) void mutateLabTracking("start_tracking");
    else if (button.hasAttribute("data-lab-track-stop")) void mutateLabTracking("stop_tracking");
    else if (button.dataset.labJob && !lab.loading && !lab.busy && !labIsRunning()) {
      lab.selectedJobId = button.dataset.labJob;
      void loadLab();
    }
  });
  byId("effectivenessTimeline").addEventListener("click", event => {
    const button = event.target.closest("[data-effectiveness-line]");
    if (!button || !state.report) return;
    rememberOpenDetails();
    const key = button.dataset.effectivenessLine;
    if (state.lines.has(key)) state.lines.delete(key); else state.lines.add(key);
    renderTimeline(state.report);
    byId("effectivenessTimeline").querySelector(`[data-effectiveness-line="${key}"]`)?.focus();
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && state.active && state.authenticated && !state.loading && !state.busy) void refresh();
    if (labIsVisible()) void loadLab(); else pauseLab();
  });
  setControls();
})();
