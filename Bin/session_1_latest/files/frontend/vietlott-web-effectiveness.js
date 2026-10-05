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
  const state = { active: false, authenticated: false, generation: 0, report: null, busy: false, loading: false, controller: null, timer: null, lines: new Set(methods.map(item => item.key)), openDetails: new Map(), initializedGames: new Set() };
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
  const opened = (key, fallback = false) => (state.openDetails.has(key) ? state.openDetails.get(key) : fallback) ? " open" : "";

  function rememberOpenDetails() {
    root.querySelectorAll("details[data-effectiveness-state]").forEach(details => state.openDetails.set(details.dataset.effectivenessState, details.open));
  }

  function showStatus(message, kind = "") {
    const el = byId("effectivenessStatus");
    el.textContent = message;
    el.dataset.kind = kind;
  }

  function setControls() {
    const canManage = !!state.report?.canManage && state.authenticated;
    byId("effectivenessAdmin").hidden = !canManage;
    byId("effectivenessRefresh").disabled = !state.authenticated || state.loading || state.busy;
    ["effectivenessType", "effectivenessLimit"].forEach(id => { byId(id).disabled = state.busy; });
    ["effectivenessEnabled", "effectivenessTicketCount", "effectivenessSave", "effectivenessLock"].forEach(id => { byId(id).disabled = !canManage || state.busy || state.loading; });
    root.setAttribute("aria-busy", state.loading || state.busy ? "true" : "false");
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
    const cards = [
      ["Đã chấm", number(counts.scored, 0), "kỳ có kết quả"],
      ["Chờ kết quả", number(counts.locked, 0), "kỳ đã khóa"],
      ["Ngân sách kỳ mới", finite(settings.ticketCount) ? `${number(settings.ticketCount, 0)} vé` : "—", "mỗi phương pháp"],
      ["Theo dõi tự động", settings.enabled ? "Bật" : "Tắt", "khi server đang chạy"],
    ];
    byId("effectivenessSummary").innerHTML = cards.map(([label, value, note]) => `<div class="effectiveness-metric"><span>${escape(label)}</span><strong>${escape(value)}</strong><small>${escape(note)}</small></div>`).join("");
    byId("effectivenessEnabled").checked = settings.enabled === true;
    byId("effectivenessTicketCount").value = finite(settings.ticketCount) ? String(settings.ticketCount) : "1";
    byId("effectivenessAdminSummary").textContent = `${settings.enabled ? "Đang bật" : "Đang tắt"} · ${number(settings.ticketCount, 0)} vé / phương pháp`;
  }

  function renderComparison(report) {
    const rows = methods.map(method => (Array.isArray(report.methods) ? report.methods : []).find(item => item.key === method.key) || { key: method.key, label: method.label });
    const probabilityKey = `${reportGame(report)}:probabilities`;
    byId("effectivenessComparison").innerHTML = `<div class="effectiveness-table-wrap" tabindex="0" role="region" aria-label="So sánh bốn phương pháp trên tất cả kỳ đã chấm">
      <table class="effectiveness-table effectiveness-comparison-table"><caption><strong>So sánh phương pháp</strong><span>Tất cả các kỳ đã chấm · cùng số vé trong từng kỳ</span></caption>
      <thead><tr><th scope="col">Phương pháp</th><th scope="col">Trùng / vé</th><th scope="col">Tỷ lệ trùng</th><th scope="col">So với ngẫu nhiên</th><th scope="col">Nhận định</th></tr></thead>
      <tbody>${rows.map(row => `<tr><th scope="row"><span class="effectiveness-method-dot" style="background:${methods.find(method => method.key === row.key).color}"></span>${escape(row.label || methodLabel(row.key))}<small>${number(row.sampleCount, 0)} kỳ đã chấm</small></th><td data-label="Trùng / vé" class="effectiveness-mean">${number(row.meanHits)}</td><td data-label="Tỷ lệ trùng"><span>≥3 số <strong>${percent(row.rate3)}</strong></span><span>≥4 số <strong>${percent(row.rate4)}</strong></span></td><td data-label="So với ngẫu nhiên"><strong>${signed(row.deltaVsRandom)}</strong><small class="effectiveness-ci">95% ${interval(row.ci95)}</small></td><td data-label="Nhận định" class="effectiveness-decision">${escape(decisionText(row))}</td></tr>`).join("")}</tbody></table></div>
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
    const maxHits = report.type === "LOTO_5_35" ? 5 : 6;
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

  function ticketHtml(ticket, actual) {
    const values = Array.isArray(ticket.main) ? ticket.main : [];
    return `<span class="effectiveness-ticket">${values.map(value => `<span class="effectiveness-ball${actual.has(Number(value)) ? " is-hit" : ""}">${escape(String(value).padStart(2, "0"))}${actual.has(Number(value)) ? '<span class="sr-only"> trùng</span>' : ""}</span>`).join("")}${ticket.special !== null && ticket.special !== undefined && ticket.special !== "" ? `<span class="effectiveness-special">ĐB ${escape(String(ticket.special).padStart(2, "0"))}</span>` : ""}</span>`;
  }

  function ticketRowHtml(ticket, actual, index, mainCount) {
    const values = Array.isArray(ticket.main) ? ticket.main : [];
    const hits = actual.size ? [...new Set(values.map(Number))].filter(value => actual.has(value)).length : null;
    return `<div class="effectiveness-ticket-row"><span class="effectiveness-ticket-label">Vé ${String(index + 1).padStart(2, "0")}</span>${ticketHtml(ticket, actual)}<span class="effectiveness-ticket-hits${hits > 0 ? " has-hit" : ""}" aria-label="${hits === null ? "Chờ kết quả" : `${hits} trên ${mainCount} số chính trùng`}">${hits === null ? "—" : `${hits}/${mainCount}`}</span></div>`;
  }

  function cycleInfoHtml(cycle, cycleKey, budget) {
    const infoKey = `${cycleKey}:info`;
    return `<details class="effectiveness-provenance" data-effectiveness-state="${escape(infoKey)}"${opened(infoKey)}><summary>Thông tin dự đoán</summary><dl class="effectiveness-info-list"><div><dt>Dữ liệu đến</dt><dd>Kỳ ${escape(cycle.cutoffDrawId)}</dd></div><div><dt>Đã khóa lúc</dt><dd>${escape(dateTime(cycle.createdAt))} (giờ Việt Nam)</dd></div><div><dt>Hạn khóa</dt><dd>${escape(dateTime(cycle.deadline))} (giờ Việt Nam)</dd></div><div><dt>Ngân sách đã khóa</dt><dd>${escape(budget)} vé / phương pháp</dd></div>${methods.map(method => {
      const entry = cycle.methods?.[method.key] || {};
      const fields = [["Engine", entry.engine], ["Model", entry.modelId], ["Mã dự đoán", entry.predictionId], ["Seed", entry.seed], ["Trung bình số trùng / vé", entry.meanHits], ["Số trùng tốt nhất", entry.bestHits]];
      return fields.filter(([, value]) => value !== null && value !== undefined && value !== "").map(([label, value]) => `<div><dt>${escape(method.label)} · ${label}</dt><dd>${escape(value)}</dd></div>`).join("");
    }).join("")}</dl></details>`;
  }

  function renderCycles(report) {
    const cycles = Array.isArray(report.cycles) ? report.cycles : [];
    if (!cycles.length) {
      byId("effectivenessCycles").innerHTML = `<div class="effectiveness-empty"><strong>Chưa có lượt theo dõi thực tế.</strong><p>${report.canManage ? "Bật theo dõi tự động hoặc khóa kỳ tiếp theo để bắt đầu." : "Quản trị viên có thể bật theo dõi cho các kỳ sắp tới."} Các kỳ trong dữ liệu cũ không được thêm vào như dự đoán đã khóa.</p></div>`;
      return;
    }
    const game = reportGame(report);
    const initialize = !state.initializedGames.has(game);
    const mainCount = game === "LOTO_5_35" ? 5 : 6;
    byId("effectivenessCycles").innerHTML = cycles.map((cycle, index) => {
      const actualList = Array.isArray(cycle.actualMain) ? cycle.actualMain : [];
      const actual = new Set(actualList.map(Number));
      const scored = cycle.status === "scored" || cycle.status === "complete" || actual.size > 0;
      const scoredText = scored ? "Đã chấm" : "Chờ kết quả";
      const cycleKey = `${game}:cycle:${cycle.targetDrawId}`;
      const lockedBudget = cycle.config?.ticketCount;
      const budget = finite(lockedBudget) ? number(lockedBudget, 0) : Array.isArray(cycle.methods?.web?.tickets) ? String(cycle.methods.web.tickets.length) : "—";
      return `<details class="effectiveness-cycle" data-effectiveness-state="${escape(cycleKey)}"${opened(cycleKey, initialize && index === 0)}><summary><span class="effectiveness-cycle-identity"><span><strong>Kỳ ${escape(cycle.targetDrawId)}</strong><span class="effectiveness-cycle-status${scored ? " is-scored" : ""}">${scoredText}</span></span><small>Hạn khóa ${escape(dateTime(cycle.deadline))}</small></span><span class="effectiveness-cycle-preview"><span class="effectiveness-preview-label">${actual.size ? "Số chính thực tế" : `${escape(budget)} vé / phương pháp đã khóa`}</span>${actual.size ? ticketHtml({ main: actualList }, new Set()) : '<span class="effectiveness-waiting">Chờ dữ liệu kỳ quay</span>'}</span><span class="effectiveness-cycle-chevron" aria-hidden="true">⌄</span></summary><div class="effectiveness-cycle-body"><div class="effectiveness-cycle-methods">${methods.map(method => {
        const entry = cycle.methods?.[method.key] || {};
        const tickets = Array.isArray(entry.tickets) ? entry.tickets : [];
        return `<div class="effectiveness-cycle-method"><div class="effectiveness-cycle-method-head"><strong><span class="effectiveness-method-dot" style="background:${method.color}"></span>${escape(method.label)}</strong><span>${actual.size ? `TB ${number(entry.meanHits, 2)} số / vé` : `${tickets.length} vé đã khóa`}</span></div><div class="effectiveness-ticket-list">${tickets.length ? tickets.map((ticket, ticketIndex) => ticketRowHtml(ticket, actual, ticketIndex, mainCount)).join("") : '<span class="muted">Chưa có bộ số</span>'}</div></div>`;
      }).join("")}</div><p class="effectiveness-cycle-note">Chấm số chính; ĐB chưa tính vào số trùng trên trang này.</p>${cycleInfoHtml(cycle, cycleKey, budget)}</div></details>`;
    }).join("");
    state.initializedGames.add(game);
  }

  function render(report) {
    rememberOpenDetails();
    renderSummary(report);
    renderNotes(report);
    renderComparison(report);
    renderTimeline(report);
    renderCycles(report);
    setControls();
  }

  function clearReport() {
    state.report = null;
    ["effectivenessSummary", "effectivenessMixedWarning", "effectivenessReportNotes", "effectivenessComparison", "effectivenessTimeline", "effectivenessCycles"].forEach(id => { byId(id).innerHTML = ""; });
    byId("effectivenessTimeline").hidden = true;
    byId("effectivenessUpdated").textContent = "";
    setControls();
  }

  async function refresh({ statusAfter = "" } = {}) {
    if (!state.authenticated || !state.active || state.busy) return;
    state.controller?.abort();
    const controller = new AbortController();
    state.controller = controller;
    const generation = state.generation;
    const type = byId("effectivenessType").value;
    const limit = byId("effectivenessLimit").value;
    state.loading = true;
    setControls();
    showStatus("Đang tải báo cáo…");
    try {
      const report = await request(`/api/ml/effectiveness?type=${encodeURIComponent(type)}&limit=${encodeURIComponent(limit)}`, { signal: controller.signal });
      if (generation !== state.generation || state.controller !== controller || byId("effectivenessType").value !== type) return;
      state.report = report;
      render(report);
      byId("effectivenessUpdated").textContent = `Cập nhật ${dateTime(new Date().toISOString())}`;
      showStatus(statusAfter || (Number(report.counts?.scored) ? "Báo cáo đã cập nhật." : "Chưa có kỳ đã chấm. Đang chờ kết quả thực tế."));
    } catch (error) {
      if (error.name === "AbortError" || generation !== state.generation || state.controller !== controller) return;
      if (error.status === 401) clearReport();
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
      const ticketCount = Number(byId("effectivenessTicketCount").value);
      if (!Number.isInteger(ticketCount) || ticketCount < 1 || ticketCount > 10) { showStatus("Số vé phải là số nguyên từ 1 đến 10.", "error"); return; }
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
      state.timer = setInterval(() => { if (!document.hidden && !state.loading && !state.busy) void refresh(); }, 120000);
    }
  }

  window.VietlottEffectiveness = Object.freeze({
    activate(active) {
      const changed = state.active !== !!active;
      state.active = !!active;
      syncTimer();
      if (state.active && state.authenticated && (changed || !state.report)) void refresh();
      if (!state.active) { state.controller?.abort(); state.loading = false; setControls(); }
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
    state.initializedGames.clear();
    byId("effectivenessAdmin").open = false;
    clearReport();
    showStatus(state.authenticated ? "Mở tab Hiệu quả dự đoán để tải báo cáo." : "Đăng nhập để xem báo cáo.");
    syncTimer();
    if (state.active && state.authenticated) void refresh();
  });
  root.addEventListener("toggle", event => {
    if (event.target.matches("details[data-effectiveness-state]") && root.contains(event.target)) state.openDetails.set(event.target.dataset.effectivenessState, event.target.open);
  }, true);
  ["effectivenessType", "effectivenessLimit"].forEach(id => byId(id).addEventListener("change", () => { rememberOpenDetails(); clearReport(); void refresh(); }));
  byId("effectivenessRefresh").addEventListener("click", () => void refresh());
  byId("effectivenessSave").addEventListener("click", () => void mutate("settings"));
  byId("effectivenessLock").addEventListener("click", () => void mutate("cycle"));
  byId("effectivenessTimeline").addEventListener("click", event => {
    const button = event.target.closest("[data-effectiveness-line]");
    if (!button || !state.report) return;
    rememberOpenDetails();
    const key = button.dataset.effectivenessLine;
    if (state.lines.has(key)) state.lines.delete(key); else state.lines.add(key);
    renderTimeline(state.report);
    byId("effectivenessTimeline").querySelector(`[data-effectiveness-line="${key}"]`)?.focus();
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && state.active && state.authenticated && !state.loading && !state.busy) void refresh(); });
  setControls();
})();
