(function () {
  "use strict";

  const root = document.getElementById("predictRootEffectiveness");
  if (!root) return;
  const byId = id => document.getElementById(id);
  const kenoTicketMaximum = 324632;
  const methods = [
    { key: "web", label: "Pipeline web", color: "#a78bfa" },
    { key: "random", label: "Ngẫu nhiên", color: "#94a3b8" },
    { key: "bayesian", label: "Bayesian", color: "#38bdf8" },
    { key: "ewma", label: "EWMA", color: "#34d399" },
  ];
  const methodPairs = [{ key: "web", methods: methods.slice(0, 2) }, { key: "bayesian", methods: methods.slice(2) }];
  const state = { active: false, authenticated: false, generation: 0, report: null, busy: false, loading: false, controller: null, prizeController: null, ticketController: null, exportController: null, exportCycleId: null, ticketPages: new Map(), prizeCursors: new Map(), selectedMethods: new Map(), timer: null, page: 1, lines: new Set(methods.map(item => item.key)), timelineFullScale: false, openDetails: new Map() };
  const activity = { progress: null, type: "", controller: null, timer: null, receivedAt: 0, serverTime: 0, requestStarted: 0, reportEstimate: 3, localPhase: "updating", error: "", message: "Đăng nhập để xem báo cáo.", kind: "" };
  state.draftPlayMode = "normal";
  const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const closePrizeRewardHelp = setupPrizeRewardHelp();
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
    el.textContent = /Failed to fetch|NetworkError|Load failed/i.test(message) ? "Không kết nối được server. Bấm Làm mới để thử lại." : message;
    el.dataset.kind = kind;
    el.hidden = kind !== "error";
    activity.message = el.textContent; activity.kind = kind;
    renderActivity();
  }

  function renderActivity() {
    const type = byId("effectivenessType").value;
    const progress = activity.type === type ? activity.progress : null;
    const inProgress = progress && ["updating", "creating", "scoring"].includes(progress.phase);
    const stale = inProgress && activity.serverTime + performance.now() - activity.receivedAt - Number(progress.updatedAtMs) > 20000;
    const working = inProgress && !stale;
    const el = byId("effectivenessActivity");
    let phase = working ? progress.phase : (state.loading || state.busy || !state.report ? activity.localPhase : "idle");
    const automationError = state.report?.type === type ? (state.report.settings?.configurationError || state.report.automation?.lastError || state.report.automation?.sourceSync?.error) : "";
    const error = working ? "" : (stale ? "Tiến trình bị gián đoạn. Bấm Làm mới để kiểm tra." : progress?.error || activity.error || automationError || (activity.kind === "error" ? activity.message : ""));
    if (error) phase = "error";
    el.dataset.phase = phase;
    byId("effectivenessPhase").textContent = ({ idle: "Đã cập nhật xong", updating: "Đang cập nhật", creating: "Đang tạo vé", scoring: "Đang chấm điểm", error: "Chưa cập nhật được" })[phase] || "Đang cập nhật";
    let eta = "";
    if (working && Number.isFinite(Number(progress.etaSeconds))) eta = Math.max(0, Number(progress.etaSeconds) - Math.max(0, (activity.serverTime - Number(progress.updatedAtMs || activity.serverTime)) / 1000) - (performance.now() - activity.receivedAt) / 1000);
    else if (state.loading) eta = Math.max(0, activity.reportEstimate - (performance.now() - activity.requestStarted) / 1000);
    const seconds = Math.ceil(eta);
    const etaEl = byId("effectivenessEta");
    etaEl.hidden = phase === "idle";
    etaEl.textContent = error ? "Thử làm mới" : !state.authenticated ? "Cần đăng nhập" : seconds > 0 ? `Ước tính ${seconds >= 60 ? `${Math.floor(seconds / 60)}p ` : ""}${seconds % 60}s` : "Đang ước tính…";
    const status = byId("effectivenessStatus");
    status.textContent = error || activity.message;
    status.dataset.kind = error ? "error" : activity.kind;
    status.hidden = !error && activity.kind !== "error";
    el.title = error || activity.message;
  }

  async function pollActivity() {
    if (!state.active || !state.authenticated || document.hidden || activity.controller) return;
    const controller = new AbortController(), type = byId("effectivenessType").value, generation = state.generation;
    activity.controller = controller;
    const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await request(`/api/ml/effectiveness-progress?type=${encodeURIComponent(type)}`, { signal: controller.signal });
      if (controller !== activity.controller || generation !== state.generation || type !== byId("effectivenessType").value) return;
      if (response.type !== type || !response.progress || !["idle", "updating", "creating", "scoring"].includes(response.progress.phase)) return;
      activity.progress = response.progress; activity.type = type; activity.receivedAt = performance.now(); activity.serverTime = Number(response.serverTimeMs) || Date.now(); activity.error = "";
    } catch (error) {
      if (controller !== activity.controller || generation !== state.generation) return;
      if (error.status === 401) { expireSession(); return; }
      activity.error = error.status === 404 ? "" : "Chưa đọc được tiến trình. Bấm Làm mới để thử lại.";
    } finally {
      clearTimeout(timeout);
      if (controller === activity.controller) { activity.controller = null; renderActivity(); }
    }
  }

  function syncActivity() {
    if (activity.timer) clearInterval(activity.timer);
    activity.timer = null;
    activity.controller?.abort(); activity.controller = null;
    activity.progress = null; activity.type = ""; activity.error = "";
    if (state.active && state.authenticated) {
      void pollActivity();
      let ticks = 0;
      activity.timer = setInterval(() => { renderActivity(); if (++ticks % 3 === 0) void pollActivity(); }, 1000);
    }
    renderActivity();
  }

  function supportsBao() {
    return state.report?.baoVersion === 1 && !isKeno();
  }

  function baoChildren() {
    const game = byId("effectivenessType").value;
    const level = Number(byId("effectivenessBaoLevel").value);
    const size = game === "LOTO_5_35" ? 5 : 6;
    if (!Number.isInteger(level) || level < 1) return 0;
    if (level < size) return (game === "LOTO_5_35" ? 35 : game === "LOTO_6_45" ? 45 : 55) - level;
    let count = 1;
    for (let i = 1; i <= size; i++) count = count * (level - size + i) / i;
    return Math.round(count);
  }

  function baoMaximum() {
    const cap = state.report?.settings?.maxBaoCounts?.[byId("effectivenessBaoLevel").value];
    return Number.isInteger(cap) && cap > 0 ? cap : Math.floor(ticketMaximum() / Math.max(1, baoChildren()));
  }

  function normalizeBaoCount(commit = false) {
    window.VietlottNumericInput.normalize({ target: byId("effectivenessBaoCount"), type: commit ? "change" : "input" }, { maximum: baoMaximum, minimum: 1, rejectMalformed: false });
  }

  function renderSettingsSummary() {
    const settings = state.report?.settings;
    if (!settings) return;
    const baoMode = supportsBao() && state.draftPlayMode === "bao";
    const enabled = byId("effectivenessEnabled").checked;
    const input = byId(baoMode ? "effectivenessBaoCount" : "effectivenessTicketCount");
    const raw = Number(input.value.replace(/\./g, ""));
    const count = raw > 0 ? Math.min(raw, baoMode ? baoMaximum() : ticketMaximum()) : null;
    const level = Number(byId("effectivenessBaoLevel").value);
    const savedBao = settings.playMode === "bao";
    const changed = settings.configurationValid === false || enabled !== settings.enabled || baoMode !== savedBao ||
      (baoMode ? count !== Number(settings.baoCount) || level !== Number(settings.baoLevel)
        : count !== Math.min(Number(settings.normalTicketCount ?? settings.ticketCount), ticketMaximum()));
    const label = baoMode ? `${number(count, 0)} Bao ${level}` : `${number(count, 0)} vé`;
    const summary = byId("effectivenessAdminSummary");
    summary.textContent = `${changed ? "Chưa lưu" : enabled ? "Đang bật" : "Đang tắt"} · ${label}`;
    summary.dataset.unsaved = String(changed);
    const savedLabel = savedBao ? `${number(settings.baoCount, 0)} Bao ${settings.baoLevel}` : `${number(settings.normalTicketCount ?? settings.ticketCount, 0)} vé`;
    summary.title = changed ? `Đang chỉnh: ${enabled ? "Bật" : "Tắt"} · ${label}. Đã lưu: ${settings.enabled ? "Bật" : "Tắt"} · ${savedLabel}. Bấm Lưu cấu hình để áp dụng.` : "Cấu hình đã lưu";
  }

  function renderStructureControls() {
    const enabled = supportsBao();
    if (!enabled) state.draftPlayMode = "normal";
    const baoMode = enabled && state.draftPlayMode === "bao";
    byId("effectivenessPlayMode").hidden = !enabled;
    byId("effectivenessNormalBudget").hidden = baoMode;
    byId("effectivenessBaoFields").hidden = !baoMode;
    byId("effectivenessTicketQuote").hidden = !baoMode;
    const blocked = !state.authenticated || !state.report?.canManage || state.loading || state.busy;
    byId("effectivenessPlayMode").querySelectorAll("button").forEach(button => {
      button.disabled = blocked;
      button.setAttribute("aria-pressed", String(button.dataset.effectivenessMode === state.draftPlayMode));
    });
    const game = byId("effectivenessType").value;
    const select = byId("effectivenessBaoLevel");
    if (select.dataset.game !== game) {
      const levels = game === "LOTO_5_35" ? [4, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] : [5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 18];
      select.innerHTML = levels.map(level => `<option value="${level}">Bao ${level}</option>`).join("");
      select.value = game === "LOTO_5_35" ? "6" : "7";
      select.dataset.game = game;
    }
    select.disabled = blocked;
    if (select.__syncCustomSelect) select.__syncCustomSelect();
    const existing = state.report?.cycles?.find(cycle => cycle.status === 'locked' &&
      Date.parse(cycle.deadline) > Date.now() && (cycle.config?.playMode || 'normal') === (baoMode ? 'bao' : 'normal') &&
      (!baoMode || Number(cycle.config?.baoLevel) === Number(select.value)));
    byId('effectivenessLock').textContent = existing ? 'Dùng bộ đã có' : 'Khóa kỳ tiếp theo';
    byId('effectivenessLock').title = existing ? `Kỳ #${existing.targetDrawId} đã có loại vé này; giữ bộ số, số lượng đã mua và không thu thêm phí.` : 'Tạo bộ số và thu phí cho loại vé đã chọn trước giờ quay';
    const input = byId("effectivenessBaoCount");
    const maximum = baoMaximum();
    input.placeholder = `Tối đa ${number(maximum, 0)} Vé Bao ${select.value}`;
    input.title = `${input.placeholder} · ${game === "LOTO_5_35" ? "Không trùng cả 5 số chính và số đặc biệt" : "Không trùng bộ 6 số chính"}`;
    if (input.max !== String(maximum)) { input.max = String(maximum); normalizeBaoCount(); }
    input.disabled = blocked;
    renderSettingsSummary();
    if (!baoMode) return;
    const count = Math.min(maximum, Number(input.value.replace(/\./g, "")));
    const valid = Number.isInteger(count) && count >= 1 && count <= maximum;
    if (!valid) {
      byId("effectivenessTicketQuote").innerHTML = '<small>Nhập Số Bao trong giới hạn để xem tổng vé và phí.</small>';
      byId("effectivenessLock").disabled = true;
      return;
    }
    const perBao = baoChildren();
    const amount = perBao * Number(state.report?.billing?.unitPayPal || 10000);
    const totalBao = (existing ? Number(existing.config.baoCount) : count) * methods.length;
    const cost = existing ? 0 : totalBao * amount;
    const balance = state.report?.billing?.balance;
    const missing = finite(balance) ? Math.max(0, cost - Number(balance)) : 0;
    byId("effectivenessTicketQuote").innerHTML = `<div data-quote-quantity title="${number(existing ? existing.config.baoCount : count, 0)} Bao ${select.value} / phương pháp × ${methods.length} phương pháp"><span>Số lượng vé</span><strong>${number(totalBao, 0)} <small>Bao ${select.value} · ${methods.length} phương pháp</small></strong></div><div data-quote-amount><span>Số tiền</span><strong>${number(amount, 0)} <small>PayPal / Bao ${select.value}</small></strong></div><div class="effectiveness-quote-total" title="${existing ? 'Loại Bao đã có, không thu thêm phí' : `Tổng phí của ${methods.length} phương pháp`}"><span>${existing ? 'Phí bổ sung' : 'Phí mỗi kỳ'}</span><strong>${number(cost, 0)} <small>PayPal</small></strong></div>${finite(balance) ? `<div><span>Số dư</span><strong>${number(balance, 0)} <small>PayPal</small></strong></div>` : ""}${existing ? `<small>Bao ${select.value} · kỳ #${escape(existing.targetDrawId)} đã có. Giữ số lượng đã mua, không thu thêm phí.</small>` : ''}${missing ? `<small class="effectiveness-quote-insufficient">Còn thiếu ${number(missing, 0)} PayPal.</small>` : ""}`;
    if (missing) byId("effectivenessLock").disabled = true;
  }

  function settingsForm() {
    normalizeTicketCount(true);
    const ticketCount = Number(byId("effectivenessTicketCount").value.replace(/\./g, ""));
    if (!Number.isInteger(ticketCount) || ticketCount < 1 || ticketCount > ticketMaximum()) throw new Error(`Số vé phải từ 1 đến ${number(ticketMaximum(), 0)}.`);
    const form = { type: byId("effectivenessType").value, enabled: String(byId("effectivenessEnabled").checked), ticketCount: String(ticketCount) };
    if (supportsBao()) {
      form.playMode = state.draftPlayMode;
      if (form.playMode === "bao") {
        normalizeBaoCount(true);
        const count = Number(byId("effectivenessBaoCount").value.replace(/\./g, ""));
        if (!Number.isInteger(count) || count < 1 || count > baoMaximum()) throw new Error("Số Bao không hợp lệ.");
        form.baoLevel = byId("effectivenessBaoLevel").value;
        form.baoCount = String(count);
      }
    }
    return form;
  }

  function ticketMaximum() {
    if (byId("effectivenessType").value === "LOTO_5_35") return 324632;
    if (!isKeno()) return 1000000;
    const level = Number(byId("effectivenessKenoLevel").value);
    return level === 1 ? 80 : level === 2 ? 3160 : level === 3 ? 82160 : kenoTicketMaximum;
  }

  function normalizeTicketCount(commit = false) {
    window.VietlottNumericInput.normalize({ target: byId("effectivenessTicketCount"), type: commit ? "change" : "input" }, { maximum: ticketMaximum, minimum: 1, rejectMalformed: false });
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
    updateTicketLimit();
    const cyclePages = cyclePagination(state.report);
    byId("effectivenessKenoPrevious").disabled = state.loading || state.busy || cyclePages.page <= 1;
    byId("effectivenessKenoNext").disabled = state.loading || state.busy || cyclePages.page >= cyclePages.totalPages;
    byId("effectivenessCyclePages").querySelectorAll("button").forEach(button => { button.disabled = state.loading || state.busy || !state.authenticated; });
    ["effectivenessEnabled", "effectivenessTicketCount", "effectivenessSave", "effectivenessLock"].forEach(id => { byId(id).disabled = !canManage || state.busy || state.loading; });
    renderStructureControls();
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
    const effectiveBudget = Math.min(Number(settings.ticketCount), report.type === "LOTO_5_35" ? 324632 : report.type === "KENO" ? (reportSize(report) === 1 ? 80 : reportSize(report) === 2 ? 3160 : reportSize(report) === 3 ? 82160 : kenoTicketMaximum) : 1000000);
    const cards = [
      ["Đã chấm", number(counts.scored, 0), "kỳ có kết quả"],
      ["Chờ kết quả", number(counts.locked, 0), "kỳ đã khóa"],
      ["Ngân sách", settings.playMode === "bao" ? `${number(settings.baoCount, 0)} Bao` : finite(effectiveBudget) ? `${number(effectiveBudget, 0)} vé` : "—", settings.playMode === "bao" ? `Bao ${settings.baoLevel} · ${number(effectiveBudget, 0)} vé con / phương pháp` : report.type === "KENO" ? `Kỳ mới · mỗi phương pháp / bậc ${reportSize(report)}` : "Kỳ mới · mỗi phương pháp"],
      ["Theo dõi", settings.enabled ? "Bật" : "Tắt", "Tự động khi server đang chạy"],
    ];
    byId("effectivenessSummary").innerHTML = cards.map(([label, value, note]) => `<div class="effectiveness-metric${String(value).length >= 8 ? ' is-wide' : ''}" title="${escape(`${label}: ${value} · ${note}`)}"><span>${escape(label)}</span><strong>${escape(value)}</strong><small>${escape(note)}</small></div>`).join("");
    if (!byId("effectivenessAdmin").open) {
      byId("effectivenessEnabled").checked = settings.enabled === true;
      byId("effectivenessTicketCount").value = finite(settings.normalTicketCount ?? settings.ticketCount) ? number(Math.min(Number(settings.normalTicketCount ?? settings.ticketCount), ticketMaximum()), 0) : "1";
      state.draftPlayMode = supportsBao() && settings.playMode === "bao" ? "bao" : "normal";
      renderStructureControls();
      if (settings.baoLevel) byId("effectivenessBaoLevel").value = String(settings.baoLevel);
      byId("effectivenessBaoCount").value = number(settings.baoCount || 1, 0);
      normalizeBaoCount(true);
    }
    renderStructureControls();
    if (report.billing) window.dispatchEvent(new CustomEvent('dvlf:prediction-wallet', { detail: report.billing }));
  }

  function renderComparison(report) {
    const keno = report.type === "KENO";
    const rows = methods.map(method => (Array.isArray(report.methods) ? report.methods : []).find(item => item.key === method.key) || { key: method.key, label: method.label });
    const probabilityKey = `${reportGame(report)}:probabilities`;
    const comparisonKey = `${reportGame(report)}:${keno ? reportSize(report) : ""}:comparison`;
    byId("effectivenessComparison").innerHTML = `<details class="effectiveness-comparison-panel effectiveness-fold" data-effectiveness-state="${escape(comparisonKey)}"${opened(comparisonKey)}><summary><span class="effectiveness-comparison-heading"><strong>${keno ? `Bậc ${reportSize(report)} · So sánh phương pháp` : "So sánh phương pháp"}</strong></span><span class="effectiveness-fold-toggle" aria-hidden="true"><span class="when-closed">Mở rộng</span><span class="when-open">Thu gọn</span></span></summary><div class="effectiveness-table-wrap" tabindex="0" role="region" aria-label="So sánh bốn phương pháp trên tất cả kỳ đã chấm">
      <table class="effectiveness-table effectiveness-comparison-table"><caption class="sr-only"><strong>${keno ? `Bậc ${reportSize(report)} · So sánh phương pháp` : "So sánh phương pháp"}</strong>${keno ? `<span>Ngẫu nhiên kỳ vọng ${number(reportSize(report) / 4, 2)} số / vé · tất cả kỳ đã chấm</span>` : ""}</caption>
      <thead><tr><th scope="col">Phương pháp</th><th scope="col">Trùng / vé</th><th scope="col">${keno ? "Tỷ lệ vé" : "Tỷ lệ trùng"}</th><th scope="col">So với ngẫu nhiên</th><th scope="col">Nhận định</th></tr></thead>
      <tbody>${rows.map(row => `<tr><th scope="row"><span class="effectiveness-method-dot" style="background:${methods.find(method => method.key === row.key).color}"></span>${escape(row.label || methodLabel(row.key))}<small>${number(row.sampleCount, 0)} kỳ đã chấm${keno ? ` · ${number(row.dayCount, 0)} ngày` : ""}</small></th><td data-label="Trùng / vé" class="effectiveness-mean">${number(row.meanHits)}</td><td data-label="${keno ? "Tỷ lệ vé" : "Tỷ lệ trùng"}">${keno ? `<span>Có giải <strong>${percent(row.winningTicketRate)}</strong></span><span>Trùng đủ <strong>${percent(row.fullMatchRate)}</strong></span>` : `<span>≥3 số <strong>${percent(row.rate3)}</strong></span><span>≥4 số <strong>${percent(row.rate4)}</strong></span>`}</td><td data-label="So với ngẫu nhiên"><strong>${signed(row.deltaVsRandom)}</strong><small class="effectiveness-ci">95% ${interval(row.ci95)}${keno ? " · theo ngày" : ""}</small></td><td data-label="Nhận định" class="effectiveness-decision">${escape(decisionText(row))}</td></tr>`).join("")}</tbody></table></div>
      <details class="effectiveness-probabilities" data-effectiveness-state="${escape(probabilityKey)}"${opened(probabilityKey)}><summary>Chỉ số xác suất số chính <span>Brier · Log-loss</span></summary><p>Brier và log-loss dùng xác suất biên chưa hiệu chỉnh; thấp hơn là tốt hơn. Dấu — là thiếu dữ liệu hợp lệ, không phải điểm 0. Đây không phải xác suất trúng toàn bộ vé.</p><div class="effectiveness-table-wrap"><table class="effectiveness-table"><thead><tr><th scope="col">Phương pháp</th><th scope="col">Brier</th><th scope="col">Log-loss</th></tr></thead><tbody>${rows.map(row => `<tr><th scope="row">${escape(row.label || methodLabel(row.key))}</th><td>${number(row.brierScore, 5)}</td><td>${number(row.logLoss, 5)}</td></tr>`).join("")}</tbody></table></div></details></details>`;
  }

  function renderNotes(report) {
    const notes = Array.isArray(report.notes) ? report.notes.filter(note => typeof note === "string" && note.trim()) : [];
    const count = finite(report.configurationCount) ? number(report.configurationCount, 0) : "nhiều";
    byId("effectivenessMixedWarning").innerHTML = report.mixedConfigurations === true ? `<p class="effectiveness-mixed-configurations"><strong>Gộp ${escape(count)} cấu hình / ngân sách.</strong> Xem cấu hình đã khóa trong từng kỳ.</p>` : "";
    byId("effectivenessReportNotes").innerHTML = notes.length ? `<ul>${notes.map(note => `<li>${escape(note)}</li>`).join("")}</ul>` : "";
  }

  function niceTimelineStep(rawStep) {
    if (!finite(rawStep) || Number(rawStep) <= 0) return 1;
    const power = 10 ** Math.floor(Math.log10(Number(rawStep)));
    const normalized = Number(rawStep) / power;
    const factor = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 2.5 ? 2.5 : normalized <= 5 ? 5 : 10;
    return factor * power;
  }

  function timelineScale(cycles, maxHits, forceFull = false) {
    const fullScale = () => ({ min: 0, max: maxHits, step: 1, ticks: Array.from({ length: maxHits + 1 }, (_, value) => value), zoomed: false });
    if (forceFull) return fullScale();
    const values = [];
    methods.filter(method => state.lines.has(method.key)).forEach(method => {
      cycles.forEach(cycle => {
        const value = cycle.methods?.[method.key]?.meanHits;
        if (finite(value)) values.push(Math.max(0, Math.min(maxHits, Number(value))));
      });
    });
    if (!values.length) return fullScale();
    const dataMin = Math.min(...values), dataMax = Math.max(...values);
    const minimumSpan = Math.min(maxHits, Math.max(.8, maxHits * .12));
    const desiredSpan = Math.min(maxHits, Math.max(minimumSpan, (dataMax - dataMin) * 1.4));
    let min = (dataMin + dataMax - desiredSpan) / 2;
    let max = min + desiredSpan;
    if (min < 0) { max -= min; min = 0; }
    if (max > maxHits) { min -= max - maxHits; max = maxHits; }
    min = Math.max(0, min);
    const step = niceTimelineStep((max - min) / 5);
    min = Math.max(0, Math.floor((min + 1e-9) / step) * step);
    max = Math.min(maxHits, Math.ceil((max - 1e-9) / step) * step);
    if (max <= min) max = Math.min(maxHits, min + step);
    const precision = Math.max(0, Math.min(4, Math.ceil(-Math.log10(step)) + (Math.abs(step * 10 - Math.round(step * 10)) > 1e-8 ? 1 : 0)));
    const clean = value => Number(value.toFixed(precision));
    const ticks = [];
    for (let value = min, guard = 0; value <= max + step / 10 && guard < 20; value += step, guard += 1) ticks.push(clean(value));
    return { min: clean(min), max: clean(max), step: clean(step), ticks, zoomed: min > 0 || max < maxHits };
  }

  function timelineAxisNumber(value) {
    return Number(value).toLocaleString("vi-VN", { maximumFractionDigits: 2 });
  }

  function renderTimeline(report) {
    const host = byId("effectivenessTimeline");
    const cycles = (Array.isArray(report.cycles) ? report.cycles : []).filter(cycle => cycle.status === "scored" || cycle.status === "complete" || Array.isArray(cycle.actualMain) && cycle.actualMain.length).slice(0, 30).sort((left, right) => Number(left.targetDrawId) - Number(right.targetDrawId));
    if (cycles.length < 2) { host.hidden = true; host.innerHTML = ""; return; }
    host.hidden = false;
    const width = 1000, height = 240, pad = { left: 42, top: 22, bottom: 42, right: 14 };
    const maxHits = reportSize(report);
    const scale = timelineScale(cycles, maxHits, state.timelineFullScale);
    const x = index => pad.left + index * (width - pad.left - pad.right) / (cycles.length - 1);
    const y = value => height - pad.bottom - (Number(value) - scale.min) * (height - pad.top - pad.bottom) / (scale.max - scale.min);
    const grid = scale.ticks.map(hit => `<line x1="${pad.left}" x2="${width - pad.right}" y1="${y(hit)}" y2="${y(hit)}" class="effectiveness-chart-grid"/><text x="${pad.left - 12}" y="${y(hit) + 4}" text-anchor="end">${timelineAxisNumber(hit)}</text>`).join("");
    const lines = methods.filter(method => state.lines.has(method.key)).map(method => {
      const points = cycles.map((cycle, index) => finite(cycle.methods?.[method.key]?.meanHits) ? [index, Number(cycle.methods[method.key].meanHits)] : null);
      let path = "", contiguous = false;
      points.forEach(point => { if (!point) { contiguous = false; return; } path += `${contiguous ? " L" : " M"}${x(point[0])},${y(point[1])}`; contiguous = true; });
      return `<path d="${path}" fill="none" stroke="${method.color}" stroke-width="2.5"/>${points.filter(Boolean).map(([index, value]) => `<circle cx="${x(index)}" cy="${y(value)}" r="3" fill="${method.color}"><title>${escape(`${method.label} · kỳ ${cycles[index].targetDrawId} · ${number(value)} số trùng / vé`)}</title></circle>`).join("")}`;
    }).join("");
    const trendKey = `${reportGame(report)}:trend`;
    const rangeText = `${timelineAxisNumber(scale.min)}–${timelineAxisNumber(scale.max)}`;
    const scaleState = state.timelineFullScale ? "Tất cả" : "Hiện tại";
    const scaleAction = state.timelineFullScale ? "Phóng vùng dữ liệu hiện tại" : "Hiển thị đầy đủ các mốc";
    host.innerHTML = `<details class="effectiveness-fold" data-effectiveness-state="${escape(trendKey)}"${opened(trendKey)}><summary class="effectiveness-chart-head" title="${cycles.length} kỳ gần nhất"><strong>Số trùng theo kỳ</strong><span class="effectiveness-fold-toggle" aria-hidden="true"><span class="when-closed">Mở rộng</span><span class="when-open">Thu gọn</span></span></summary><div class="effectiveness-chart-body"><div class="effectiveness-chart-tools"><div class="effectiveness-chart-legend">${methods.map(method => `<button type="button" class="secondary" data-effectiveness-line="${method.key}" aria-pressed="${state.lines.has(method.key)}"><span class="effectiveness-method-dot" style="background:${method.color}"></span>${escape(method.label)}</button>`).join("")}</div><button type="button" class="secondary effectiveness-chart-range" data-effectiveness-scale-toggle aria-pressed="${state.timelineFullScale}" title="${scaleAction}. ${state.timelineFullScale ? `Toàn thang 0–${timelineAxisNumber(maxHits)}` : `Vùng hiện tại ${rangeText}`}">Trạng thái: ${scaleState}</button></div><svg viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="effectivenessChartTitle effectivenessChartDescription" data-axis-min="${scale.min}" data-axis-max="${scale.max}" data-axis-step="${scale.step}"><title id="effectivenessChartTitle">Số trùng trung bình từng kỳ của bốn phương pháp</title><desc id="effectivenessChartDescription">Trục ngang là toàn bộ các kỳ quay đang hiển thị. Trục dọc ${state.timelineFullScale ? `hiển thị đầy đủ các mốc từ 0 đến ${timelineAxisNumber(maxHits)}` : scale.zoomed ? `được tự động phóng trong khoảng ${rangeText}` : `hiển thị toàn thang từ 0 đến ${timelineAxisNumber(maxHits)}`} theo những đường đang bật. Số liệu từng kỳ có trong nhật ký bên dưới.</desc>${grid}${lines}<text x="${pad.left}" y="${height - 12}">Kỳ ${escape(cycles[0].targetDrawId)}</text><text x="${width - pad.right}" y="${height - 12}" text-anchor="end">Kỳ ${escape(cycles[cycles.length - 1].targetDrawId)}</text></svg></div></details>`;
  }

  function ticketHtml(ticket, actual, options = {}) {
    const values = Array.isArray(ticket.main) ? ticket.main : [];
    const specialLabel = options.power ? "Phụ" : "ĐB";
    const special = escape(String(ticket.special).padStart(2, "0"));
    const specialMatched = options.specialMatched === true;
    return `<span class="effectiveness-ticket">${values.map(value => `<span class="effectiveness-ball${actual.has(Number(value)) ? " is-hit" : ""}">${escape(String(value).padStart(2, "0"))}${actual.has(Number(value)) ? '<span class="sr-only"> trùng</span>' : ""}</span>`).join("")}${options.showSpecial !== false && ticket.special !== null && ticket.special !== undefined && ticket.special !== "" ? `<span class="effectiveness-special-group"><span class="effectiveness-special-separator" aria-hidden="true">|</span><span class="effectiveness-ball effectiveness-special${specialMatched ? " is-matched" : ""}" aria-label="${specialLabel} ${special}${specialMatched ? " trùng" : ""}" title="${specialLabel} ${special}${specialMatched ? " · trùng số thực tế" : ""}${options.power ? " · Số phụ dự đoán; giải Power xét sáu số trên vé và bóng thứ 7 thực tế" : ""}">${special}</span></span>` : ""}</span>`;
  }

  function ticketSeedHtml(seed) {
    return /^[0-9a-f]{64}$/.test(seed || '') ? `<button type="button" class="effectiveness-seed-copy" data-copy-ticket-seed="${seed}" title="Seed vé: ${seed} · Bấm để sao chép đầy đủ" aria-label="Sao chép seed vé ${seed}">${seed.slice(0, 6)}</button>` : '';
  }

  async function copyTicketSeed(button) {
    const seed = button.dataset.copyTicketSeed;
    if (!/^[0-9a-f]{64}$/.test(seed || '')) return;
    try {
      await navigator.clipboard.writeText(seed);
      if (!button.isConnected) return;
      button.textContent = 'Đã chép';
      button.dataset.copied = 'true';
      setTimeout(() => { if (button.isConnected) { button.textContent = seed.slice(0, 6); delete button.dataset.copied; } }, 1800);
    } catch { showStatus('Không sao chép được seed. Bạn có thể xem mã đầy đủ khi di chuột lên nút Seed hoặc tải Excel.', 'error'); }
  }

  function ticketRowHtml(ticket, actual, index, mainCount, result = null, power = false, actualSpecial = null) {
    const values = Array.isArray(ticket.main) ? ticket.main : [];
    const hits = actual.size ? [...new Set(values.map(Number))].filter(value => actual.has(value)).length : null;
    const resultStatus = ["won", "lost", "unknown", "pending", "unsupported", "invalid"].includes(result?.status) ? result.status : "unknown";
    const prizeLabel = result?.prizeLabel || (hits === null ? "Chờ kết quả" : "Chưa có phân loại giải");
    const specialMatched = actual.size > 0 && finite(actualSpecial) && finite(ticket.special) && Number(ticket.special) === Number(actualSpecial);
    const group = ticket.bao;
    const groupLabel = group ? `Bao ${group.parentIndex} · Vé con ${group.childIndex}` : "";
    return `<div class="effectiveness-ticket-row" data-ticket-index="${index + 1}" data-ticket-prize-code="${escape(result?.prizeCode || "")}"><span class="effectiveness-ticket-label"${groupLabel ? ` title="${escape(groupLabel)}"` : ""}>${group ? "Vé con" : "Vé"} ${String(index + 1).padStart(2, "0")}${group ? `<small>B${escape(group.parentIndex)} · ${escape(group.childIndex)}</small>` : ""}${ticketSeedHtml(ticket.ticketSeed)}</span>${ticketHtml(ticket, actual, { power, showSpecial: (power && !group) || mainCount === 5, specialMatched })}<span class="effectiveness-ticket-hits${hits > 0 ? " has-hit" : ""}" aria-label="${hits === null ? "Chờ kết quả" : `${hits} trên ${mainCount} số chính trùng`}">${hits === null ? "—" : `${hits}/${mainCount}`}</span><span class="effectiveness-ticket-prize" data-prize-status="${resultStatus}"${result?.reason ? ` title="${escape(result.reason)}"` : ""}>${escape(prizeLabel)}</span></div>`;
  }

  function actualSpecialHtml(cycle, game) {
    if (game === "LOTO_6_45" || game === "KENO") return "";
    const label = game === "LOTO_6_55" ? "Bóng thứ 7" : "ĐB";
    const special = escape(String(cycle.actualSpecial).padStart(2, "0"));
    return finite(cycle.actualSpecial) ? `<span class="effectiveness-actual-special" title="${label} ${special}"><span class="effectiveness-actual-separator" aria-hidden="true">|</span><strong class="effectiveness-ball effectiveness-actual-special-ball" aria-label="${label} ${special}">${special}</strong></span>` : `<span class="effectiveness-special-unknown">${label}: chưa có dữ liệu</span>`;
  }

  function actualNumbersHtml(cycle, game) {
    const main = ticketHtml({ main: cycle.actualMain }, new Set());
    const special = actualSpecialHtml(cycle, game);
    return special && finite(cycle.actualSpecial) ? `<span class="effectiveness-actual-numbers">${main}${special}</span>` : main + special;
  }

  function cycleInfoHtml(cycle, cycleKey, budget) {
    const infoKey = `${cycleKey}:info`;
    return `<details class="effectiveness-provenance" data-effectiveness-state="${escape(infoKey)}"${opened(infoKey)}><summary>Thông tin dự đoán</summary><dl class="effectiveness-info-list"><div><dt>Dữ liệu đến</dt><dd>Kỳ ${escape(cycle.cutoffDrawId)}</dd></div><div><dt>Đã khóa lúc</dt><dd>${escape(dateTime(cycle.createdAt))} (giờ Việt Nam)</dd></div><div><dt>Giờ quay / hạn khóa</dt><dd>${escape(dateTime(cycle.deadline))} (giờ Việt Nam)</dd></div>${cycle.scoredAt ? `<div><dt>Ghi nhận điểm lúc</dt><dd>${escape(dateTime(cycle.scoredAt))} (giờ Việt Nam)</dd></div>` : ""}<div><dt>Ngân sách đã khóa</dt><dd>${escape(budget)} vé / phương pháp${cycle.level ? " / bậc" : ""}</dd></div>${methods.map(method => {
      const entry = cycle.methods?.[method.key] || {};
      const fields = [["Engine", entry.engine], ["Model", entry.modelId], ["Mã dự đoán", entry.predictionId], [entry.seedSchedule ? "Seed gốc" : "Seed", entry.seedSchedule?.rootSeed ?? entry.seed], ...(entry.seedSchedule ? [["Phiên bản seed vé", entry.seedSchedule.version], ["Sinh seed vé", "SHA256 từ seed gốc, loại xổ số, kỳ, phương pháp, loại vé/Bao và số thứ tự. Tái lập dùng thêm xác suất/cấu hình và thứ tự phân bổ đã khóa."]] : []), ["Trung bình số trùng / vé", entry.meanHits], ["Số trùng tốt nhất", entry.bestHits]];
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

  const jackpotFields = {
    LOTO_5_35: { LOTTO_JACKPOT: "specialPrize" },
    LOTO_6_45: { MEGA_JACKPOT: "jackpot" },
    LOTO_6_55: { POWER_JACKPOT_1: "jackpot1", POWER_JACKPOT_2: "jackpot2" },
  };

  function matchingPrizeDraw(game, cycle, draw) {
    const size = game === "LOTO_5_35" ? 5 : 6;
    const universe = game === "LOTO_5_35" ? 35 : game === "LOTO_6_45" ? 45 : 55;
    const balls = values => Array.isArray(values) && values.length === size && values.every(value => Number.isInteger(value) && value >= 1 && value <= universe) && new Set(values).size === size
      ? [...values].sort((a, b) => a - b).join(",") : "";
    if (!draw || !Number.isSafeInteger(Number(cycle.targetDrawId)) || Number(cycle.targetDrawId) <= 0 || Number(draw.ky) !== Number(cycle.targetDrawId)) return false;
    const actual = balls(cycle.actualMain);
    if (!actual || balls(draw.main) !== actual) return false;
    if (game === "LOTO_6_45") {
      if (cycle.actualSpecial != null || draw.special != null) return false;
    } else if (!Number.isInteger(cycle.actualSpecial) || cycle.actualSpecial < 1 || cycle.actualSpecial > (game === "LOTO_5_35" ? 12 : 55) || cycle.actualSpecial !== draw.special || game === "LOTO_6_55" && cycle.actualMain.includes(cycle.actualSpecial)) return false;
    const deadline = new Date(cycle.deadline);
    if (!Number.isFinite(deadline.getTime())) return false;
    const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Ho_Chi_Minh", day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(deadline).map(part => [part.type, part.value]));
    const drawTime = draw.time || (game === "LOTO_5_35" ? "" : "18:00");
    return draw.date === `${parts.day}/${parts.month}/${parts.year}` && drawTime === `${parts.hour}:${parts.minute}`;
  }

  async function loadPrizeContexts(report) {
    state.prizeController?.abort();
    const fields = jackpotFields[report.type];
    const cycles = fields ? (report.cycles || []).filter(cycle => (cycle.actualMain || []).length && Object.values(cycle.methods || {}).some(entry =>
      Object.keys(fields).some(code => Number(entry.prizeCounts?.[code]) > 0 || entry.ticketResults?.some(result => result.prizeCode === code)))) : [];
    if (!cycles.length) { state.prizeController = null; return; }
    cycles.forEach(cycle => { cycle.prizeContext = { status: "loading" }; });
    const controller = new AbortController(), generation = state.generation;
    state.prizeController = controller;
    const current = () => !controller.signal.aborted && state.prizeController === controller && state.report === report && generation === state.generation && state.active && state.authenticated;
    let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 10000);
    try {
      const ids = [...new Set(cycles.map(cycle => String(cycle.targetDrawId)))];
      const draws = new Map();
      for (let start = 0; start < ids.length; start += 240) {
        const params = new URLSearchParams({ type: report.type, count: "all", drawIds: ids.slice(start, start + 240).join(",") });
        const response = await request(`/api/live-history?${params}`, { signal: controller.signal });
        if (!current()) return;
        if (response.type !== report.type || !Array.isArray(response.history)) throw new Error("Dữ liệu quỹ thưởng không khớp loại xổ số.");
        response.history.forEach(draw => {
          const key = Number(draw.ky);
          draws.set(key, draws.has(key) ? null : draw);
        });
      }
      if (!current()) return;
      cycles.forEach(cycle => {
        const draw = draws.get(Number(cycle.targetDrawId));
        cycle.prizeContext = matchingPrizeDraw(report.type, cycle, draw) ? { status: "ready", draw } : { status: "mismatch" };
      });
    } catch (error) {
      if (state.prizeController === controller && state.report === report && generation === state.generation) cycles.forEach(cycle => { cycle.prizeContext = { status: timedOut ? "timeout" : "error" }; });
      if (error.status === 401 && current()) { expireSession(); return; }
    } finally {
      clearTimeout(timeout);
      const update = state.prizeController === controller && state.report === report && generation === state.generation && state.active && state.authenticated;
      if (state.prizeController === controller) state.prizeController = null;
      if (update) {
        cycles.forEach(cycle => methods.forEach(method => {
          const entry = cycle.methods?.[method.key];
          if (!entry?.predictionId) return;
          root.querySelectorAll(".effectiveness-cycle-method").forEach(panel => {
            if (panel.dataset.predictionId !== entry.predictionId) return;
            const total = Number(entry.ticketCount ?? entry.ticketPagination?.total ?? entry.tickets?.length);
            const summary = panel.querySelector(".effectiveness-prize-summary");
            if (summary) summary.outerHTML = methodPrizeSummaryHtml(cycle, entry, report.type, total, method.label);
          });
        }));
      }
    }
  }

  function prizeAmountInfo(game, group, context) {
    const fixed = prizeUnitAmount(game, group.code);
    if (fixed !== null) return { unit: fixed, amount: fixed * group.count, estimated: false };
    const top = game === 'KENO' && /^KENO_(8|9|10)_\1$/.exec(group.code);
    if (top) {
      const level=Number(top[1]), winners=context?.kenoWinnerCounts?.[String(level)];
      if (context?.status !== 'ready' || !Number.isSafeInteger(winners) || winners < 0)
        return {unit:null,amount:null,reason:'Chưa có số vé trúng thực tế đã đối chiếu cho kỳ Keno này'};
      const total=winners+group.count;
      if (!Number.isSafeInteger(total) || total<=0) return {unit:null,amount:null,reason:'Số vé chia thưởng Keno không hợp lệ'};
      const unit=total<=({8:50,9:12,10:5}[level]) ? {8:200000000,9:800000000,10:2000000000}[level] : Number(10000000000n/BigInt(total));
      return {unit,amount:unit*group.count,estimated:true,
        reason:`Keno ${level}/${level}: tính cùng ${number(winners,0)} vé thực tế và ${number(group.count,0)} vé mô phỏng; quỹ tối đa 10 tỷ ₫ riêng từng bậc/kỳ`};
    }
    const field = jackpotFields[game]?.[group.code];
    if (!field) return { unit: null, amount: null, reason: "Cần mức trả/vé của đúng kỳ cho giải chia thưởng" };
    if (!context || context.status === "loading") return { unit: null, amount: null, reason: "Đang đối chiếu quỹ Jackpot của đúng kỳ" };
    if (context.status !== "ready") return { unit: null, amount: null, reason: context.status === "mismatch" ? "Quỹ Jackpot chưa khớp kỳ, ngày giờ hoặc bộ số đã chấm" : "Chưa tải được quỹ Jackpot. Bấm Làm mới để thử lại" };
    const pool = context.draw[field], actualWinners = context.draw.prizeWinnerCounts?.[field];
    if (!Number.isSafeInteger(pool) || pool <= 0) return { unit: null, amount: null, reason: "Kỳ này chưa có giá trị quỹ Jackpot hợp lệ" };
    if (!Number.isSafeInteger(actualWinners) || actualWinners < 0) return { unit: null, amount: null, reason: "Kỳ này chưa có số vé trúng Jackpot thực tế đã xác minh" };
    const denominator = actualWinners + group.count;
    if (!Number.isSafeInteger(denominator) || denominator <= 0) return { unit: null, amount: null, reason: "Số vé chia Jackpot không hợp lệ" };
    // Each method is an independent hypothetical addition to the published
    // winners. Never multiply the whole shared pool by simulated ticket count.
    const unit = Number(BigInt(pool) / BigInt(denominator));
    return { unit, amount: unit * group.count, estimated: true,
      reason: `${group.label}: quỹ ${number(pool, 0)} ₫ ÷ (${number(actualWinners, 0)} vé thực tế + ${number(group.count, 0)} vé mô phỏng), làm tròn xuống đồng` };
  }

  function setupPrizeRewardHelp() {
    const panel = document.createElement("div");
    panel.id = "effectivenessPrizeRewardHelp";
    panel.className = "effectiveness-prize-help-popover";
    panel.setAttribute("popover", "auto");
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "Cơ cấu thưởng và thuế thu nhập cá nhân");
    panel.innerHTML = `<p data-reward-basis></p><p><b>Thuế TNCN từ 01/07/2026:</b> 10% phần tiền thưởng vượt 20.000.000 ₫ trên mỗi vé trong một đợt quay thưởng. Vé có tổng thưởng ≤ 20.000.000 ₫ không chịu thuế.</p><p>Ví dụ: một vé trúng 100 triệu ₫ → thuế 8 triệu ₫. Thuế xét khi trả thưởng, không tính trên tổng thưởng của tất cả vé. Dòng Tiền thưởng − Tiền vé cũng chưa trừ thuế.</p><p>Trước 01/07/2026, ngưỡng tính thuế là 10 triệu ₫.</p><a href="https://chinhphu.vn/?classid=1&amp;docid=218684&amp;pageid=27160&amp;typegroupid=4" target="_blank" rel="noopener noreferrer">Điều 58 · Nghị định 253/2026/NĐ-CP</a>`;
    root.append(panel);
    let trigger = null, closeTimer;
    const isOpen = () => panel.matches(":popover-open");
    const close = () => {
      clearTimeout(closeTimer);
      if (isOpen()) panel.hidePopover();
      trigger?.setAttribute("aria-expanded", "false");
      trigger = null;
    };
    const position = () => {
      if (!isOpen()) return;
      if (!trigger?.isConnected || root.hidden) { close(); return; }
      const anchor = trigger.getBoundingClientRect(), box = panel.getBoundingClientRect();
      panel.style.left = `${Math.max(12, Math.min(anchor.left, innerWidth - box.width - 12))}px`;
      const below = anchor.bottom + 8;
      panel.style.top = `${Math.max(12, Math.min(below + box.height <= innerHeight - 12 ? below : anchor.top - box.height - 8, innerHeight - box.height - 12))}px`;
    };
    const selectTrigger = button => {
      clearTimeout(closeTimer);
      trigger?.setAttribute("aria-expanded", "false");
      trigger = button;
      panel.querySelector("[data-reward-basis]").textContent = button.dataset.prizeRewardHelp === "LOTO_5_35"
        ? "Cơ cấu chuẩn, chưa gồm Chia Giải và chưa trừ thuế thu nhập cá nhân."
        : "Cơ cấu chuẩn, chưa trừ thuế thu nhập cá nhân.";
      trigger.setAttribute("aria-expanded", "true");
    };
    const show = button => {
      selectTrigger(button);
      if (!isOpen()) panel.showPopover();
      position();
    };
    const closeLater = () => {
      clearTimeout(closeTimer);
      closeTimer = setTimeout(() => {
        if (!trigger?.matches(":hover, :focus-visible") && !panel.matches(":hover, :focus-within")) close();
      }, 180);
    };
    root.addEventListener("pointerover", event => {
      const button = event.target.closest("[data-prize-reward-help]");
      if (button && event.pointerType !== "touch") show(button);
    });
    root.addEventListener("pointerout", event => {
      if (event.target.closest("[data-prize-reward-help]")) closeLater();
    });
    root.addEventListener("focusin", event => {
      const button = event.target.closest("[data-prize-reward-help]");
      if (button?.matches(":focus-visible")) show(button);
    });
    root.addEventListener("focusout", event => {
      if (event.target.closest("[data-prize-reward-help]")) closeLater();
    });
    root.addEventListener("click", event => {
      const button = event.target.closest("[data-prize-reward-help]");
      if (!button) return;
      selectTrigger(button);
    });
    root.addEventListener("toggle", event => {
      if (event.target.matches("details") && !event.target.open && trigger && event.target.contains(trigger)) close();
    }, true);
    panel.addEventListener("pointerenter", () => clearTimeout(closeTimer));
    panel.addEventListener("pointerleave", closeLater);
    panel.addEventListener("focusin", () => clearTimeout(closeTimer));
    panel.addEventListener("focusout", closeLater);
    panel.addEventListener("toggle", () => {
      if (!isOpen()) { trigger?.setAttribute("aria-expanded", "false"); trigger = null; }
      else position();
    });
    window.addEventListener("resize", position);
    document.addEventListener("scroll", position, true);
    return close;
  }

  function prizeMoneyHtml(groups, total, uncertain, game, context) {
    const ticketPrice = 10000;
    const money = value => `${number(value, 0)} ₫`;
    const rows = groups.map(group => ({ ...group, ...prizeAmountInfo(game, group, context) }));
    const reward = rows.reduce((sum, row) => sum + (row.amount ?? 0), 0);
    const cost = total * ticketPrice;
    const complete = !uncertain && rows.every(row => row.amount !== null && Number.isSafeInteger(row.amount)) && Number.isSafeInteger(reward) && Number.isSafeInteger(cost);
    const net = reward - cost;
    const estimated = rows.some(row => row.estimated);
    const notes = [...new Set(rows.filter(row => row.amount === null).map(row => row.reason).filter(Boolean))].join(" · ");
    return `<div class="effectiveness-prize-counts" role="list" aria-label="Chi tiết giải thưởng, số lượng giảm dần">${rows.map(row => `<div class="effectiveness-prize-detail" role="listitem" data-prize-code="${escape(row.code)}" data-prize-unit="${row.unit ?? ''}" data-prize-subtotal="${row.amount ?? ''}"><span class="effectiveness-prize-name">${escape(row.label)}</span><span class="effectiveness-prize-equation"><b>${number(row.count, 0)}</b><i>×</i><span>${row.unit === null ? "Chờ mức trả/vé" : money(row.unit)}</span><i>=</i><strong>${row.amount === null ? "Chưa xác định" : money(row.amount)}</strong></span></div>`).join("")}</div><div class="effectiveness-prize-total"><span class="effectiveness-prize-total-label">${complete ? estimated ? "Tổng thưởng ước tính" : "Tổng tiền thưởng" : "Thưởng đã tính"}<button type="button" class="effectiveness-prize-help-button" data-prize-reward-help="${escape(game)}" popovertarget="effectivenessPrizeRewardHelp" aria-label="Giải thích cơ cấu thưởng và thuế TNCN" aria-haspopup="dialog" aria-expanded="false">?</button></span><strong data-prize-reward="${reward}">${money(reward)}</strong></div><div class="effectiveness-prize-total effectiveness-ticket-total"><span>Tổng tiền vé</span><strong data-total-ticket-cost="${cost}">${money(cost)}</strong></div><div class="effectiveness-prize-net${complete ? net > 0 ? ' is-positive' : net < 0 ? ' is-negative' : ' is-even' : ' is-incomplete'}"><span class="effectiveness-prize-net-label">Tiền thưởng − Tiền vé</span><span class="effectiveness-prize-net-equation"><span>${complete ? money(reward) : 'Chưa đủ tổng thưởng'}</span><span>− ${money(cost)}</span><span>=</span><strong data-prize-net="${complete ? net : ''}" data-ticket-cost="${cost}">${complete ? money(net) : "Chưa tính đủ"}</strong></span></div>${notes ? `<small>${escape(notes)}</small>` : ""}`;
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
    // Old complete reports can use their full result array. A partial ticket page
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
    return `<div class="effectiveness-prize-summary" aria-label="Vé trúng và tiền thưởng mô phỏng của toàn bộ ${escape(label)} trong kỳ này"><div class="effectiveness-prize-best"><span>Cao nhất</span><button type="button" class="effectiveness-prize-jump" data-prize-jump="${escape(highest.code)}" title="Đến vé tiếp theo trúng ${escape(highest.label)} của ${escape(label)}" aria-label="Đến vé tiếp theo trúng ${escape(highest.label)} của ${escape(label)}"><strong>${escape(highest.label)}</strong></button><span>SL <b>${number(highest.count, 0)}</b></span></div>${prizeMoneyHtml(groups, total, uncertain, game, cycle.prizeContext)}${uncertain ? `<small>Còn ${number(uncertain, 0)} vé chưa xác định giải</small>` : ""}</div>`;
  }

  function cycleMethodHeaderHtml(cycle, method, game, mainCount, entry) {
    const gameLabel = ({ LOTO_5_35: "5/35", LOTO_6_45: "6/45", LOTO_6_55: "6/55" })[game] || `Keno · Bậc ${mainCount}`;
    const actual = Array.isArray(cycle.actualMain) ? cycle.actualMain : [];
    const drawDate = new Date(cycle.deadline);
    const hasDrawTime = !!cycle.deadline && Number.isFinite(drawDate.getTime());
    const drawTime = hasDrawTime ? drawDate.toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh", hour12: false, hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit", year: "numeric" }) : "—";
    const specialLabel = game === "LOTO_5_35" ? "Số đặc biệt" : game === "LOTO_6_55" ? "Bóng 7" : "";
    const specialValue = finite(cycle.actualSpecial) ? escape(String(cycle.actualSpecial).padStart(2, "0")) : "—";
    const result = actual.length ? `<span class="effectiveness-method-result-numbers">${actual.map(value => `<span class="effectiveness-method-result-ball">${escape(String(value).padStart(2, "0"))}</span>`).join("")}${specialLabel ? `<span class="effectiveness-method-result-special">${game === "LOTO_6_55" ? specialLabel + " " : ""}<b class="effectiveness-method-result-ball is-special" role="img" aria-label="${specialLabel} ${specialValue}" title="${specialLabel} ${specialValue}">${specialValue}</b></span>` : ""}</span>` : '<span class="effectiveness-method-result-pending">Chờ kết quả</span>';
    return `<div class="effectiveness-cycle-method-head" tabindex="0" role="region" aria-label="Thông tin ${escape(method.label)} · Kỳ ${escape(cycle.targetDrawId)}"><div class="effectiveness-method-head-row">
      <div class="effectiveness-method-identity"><strong><span class="effectiveness-method-dot" style="background:${method.color}"></span>${escape(method.label)}</strong><span class="effectiveness-method-game">${escape(gameLabel)}</span></div>
      <div class="effectiveness-method-context"><span class="effectiveness-method-draw">Kỳ #${escape(cycle.targetDrawId)}</span><time${hasDrawTime ? ` datetime="${escape(cycle.deadline)}"` : ""} title="Thời gian quay · Giờ Việt Nam">${escape(drawTime)}</time><div class="effectiveness-method-result" aria-label="Kết quả thực tế"><span>Kết quả</span>${result}</div></div>
      <span class="effectiveness-method-average">TB ${actual.length ? number(entry.meanHits, 2) : "—"} số / vé</span>
    </div></div>`;
  }

  function cycleMethodHtml(cycle, method, game, mainCount) {
    const entry = cycle.methods?.[method.key] || {};
    const actual = new Set((cycle.actualMain || []).map(Number));
    const tickets = Array.isArray(entry.tickets) ? entry.tickets : [];
    const view = ticketView(entry, cycle);
    const pagination = view === 'bao' ? entry.baoPagination : entry.ticketPagination;
    const offset = Number(pagination?.offset || 0);
    const total = Number(entry.ticketCount ?? pagination?.total ?? tickets.length);
    const items = view === 'bao' ? (entry.baoParents || []) : tickets;
    const unit = view === 'bao' ? 'Bao' : 'Vé';
    const itemTotal = view === 'bao' ? Number(pagination?.total || cycle.config.baoCount) : total;
    const range = items.length ? `${unit} ${number(offset + 1, 0)}–${number(offset + items.length, 0)} / ${number(itemTotal, 0)}` : '';
    const pager = pagination?.totalPages > 1 ? `<nav class="effectiveness-ticket-pager" aria-label="Phân trang ${unit} ${escape(method.label)}"><span class="effectiveness-ticket-range">${range}</span><div class="effectiveness-ticket-page-controls"><button type="button" class="secondary" data-ticket-page="${pagination.page - 1}"${pagination.page <= 1 ? " disabled" : ""} aria-label="Trang ${unit} trước">‹</button><label><span>Trang</span><input type="number" data-ticket-jump min="1" max="${pagination.totalPages}" step="1" value="${pagination.page}" aria-label="Trang ${unit} ${escape(method.label)}" /><span>/ ${number(pagination.totalPages, 0)}</span></label><button type="button" class="secondary" data-ticket-page="${pagination.page + 1}"${pagination.page >= pagination.totalPages ? " disabled" : ""} aria-label="Trang ${unit} tiếp theo">›</button></div></nav>` : range ? `<div class="effectiveness-ticket-range">${range}</div>` : '';
    const summary = methodPrizeSummaryHtml(cycle, entry, game, total, method.label);
    const footer = pager || summary ? `<div class="effectiveness-ticket-footer">${pager}${summary}</div>` : "";
    const rows = view === 'bao' ? items.map(parent => baoRowHtml(parent, cycle, game)).join('')
      : tickets.map((ticket, ticketIndex) => ticketRowHtml(ticket, actual, offset + ticketIndex, mainCount, (entry.ticketResults || []).find(result => Number(result.ticketIndex) === offset + ticketIndex + 1), game === "LOTO_6_55", cycle.actualSpecial)).join('');
    const empty = view === 'bao' ? '<button type="button" class="secondary effectiveness-bao-retry" data-bao-reload>Tải bộ Bao gốc</button>' : '<span class="muted">Chưa có bộ số</span>';
    return `${cycleMethodHeaderHtml(cycle, method, game, mainCount, entry)}<div class="effectiveness-ticket-columns${view === 'bao' ? ' effectiveness-bao-columns' : ''}" aria-hidden="true"><span>${unit}</span><span>${view === 'bao' ? 'Bộ số Bao gốc' : 'Bộ số dự đoán'}</span><span>Trùng</span><span>Kết quả</span></div><div class="effectiveness-ticket-list${view === 'bao' ? ' effectiveness-bao-list' : ''}">${rows || empty}</div>${footer}`;
  }

  function ticketView(entry, cycle) {
    return cycle.config?.playMode === 'bao' ? 'bao' : 'tickets';
  }

  function baoRowHtml(parent, cycle, game) {
    const actual = new Set((cycle.actualMain || []).map(Number));
    const hits = actual.size ? parent.main.filter(value => actual.has(Number(value))).length : null;
    const specialMatched = actual.size > 0 && Number(parent.special) === Number(cycle.actualSpecial);
    const result = parent.result || { status: actual.size ? 'unknown' : 'pending', label: actual.size ? 'Chưa xác định' : 'Chờ kết quả' };
    return `<div class="effectiveness-ticket-row effectiveness-bao-row" data-bao-index="${escape(parent.parentIndex)}"><span class="effectiveness-ticket-label">Bao ${escape(parent.parentIndex)}${ticketSeedHtml(parent.ticketSeed)}</span>${ticketHtml(parent, actual, { showSpecial: game === 'LOTO_5_35', specialMatched })}<span class="effectiveness-ticket-hits${hits > 0 ? ' has-hit' : ''}" aria-label="${hits === null ? 'Chờ kết quả' : `${hits} số chính của Bao trùng kết quả`}">${hits === null ? '—' : hits}</span><span class="effectiveness-ticket-prize" data-prize-status="${escape(result.status)}" title="${escape(result.details || result.label)}">${escape(result.label)}</span></div>`;
  }

  async function loadVisibleBaoPages() {
    if (state.loading || state.busy || state.ticketController || !state.active || !state.authenticated) return;
    for (const panel of root.querySelectorAll('.effectiveness-cycle-method')) {
      if (!panel.isConnected || panel.dataset.baoAutoFailed || !panel.getClientRects().length || !panel.querySelector('.effectiveness-bao-retry')) continue;
      if (state.loading || state.busy || state.ticketController || !state.active || !state.authenticated) return;
      await loadTicketPage(panel, 1);
    }
  }

  function focusPrizeTicket(panel, ticketIndex) {
    const row = panel.querySelector(`[data-ticket-index="${ticketIndex}"], [data-bao-index="${ticketIndex}"]`);
    if (!row) return;
    panel.querySelectorAll(".is-prize-target").forEach(item => item.classList.remove("is-prize-target"));
    row.classList.add("is-prize-target");
    row.tabIndex = -1;
    row.focus({ preventScroll: true });
    row.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }

  function prizeCursorKey(cycle, entry, method, code) {
    return JSON.stringify([entry.predictionId, state.report.type, state.report.level, cycle.targetDrawId, method, code, cycle.status, cycle.actualMain, cycle.actualSpecial]);
  }

  function jumpToPrizeTicket(button) {
    if (button.disabled || !state.authenticated || !state.active || state.loading || state.busy) return;
    const panel = button.closest(".effectiveness-cycle-method");
    const method = panel?.dataset.method;
    const cycleKey = panel.closest("[data-method-cycle]")?.dataset.methodCycle;
    const cycle = state.report?.cycles?.find(item => cycleStateKey(item, state.report) === cycleKey);
    const entry = cycle?.methods?.[method];
    if (!entry) return;
    const code = button.dataset.prizeJump;
    const cursorKey = prizeCursorKey(cycle, entry, method, code);
    const afterTicketIndex = state.prizeCursors.get(cursorKey) || 0;
    const total = Number(entry.ticketCount ?? entry.ticketPagination?.total ?? entry.tickets?.length);
    if (ticketView(entry, cycle) === 'tickets' && entry.tickets?.length === total) {
      const winners = (entry.ticketResults || []).filter(item => item.prizeCode === code && item.status === "won").sort((a, b) => a.ticketIndex - b.ticketIndex);
      const result = winners.find(item => Number(item.ticketIndex) > afterTicketIndex) || winners[0];
      if (result) {
        focusPrizeTicket(panel, Number(result.ticketIndex));
        state.prizeCursors.set(cursorKey, Number(result.ticketIndex));
        return;
      }
    }
    if (entry.predictionId) void loadTicketPage(panel, Number(entry.ticketPagination?.page || 1), code, afterTicketIndex);
  }

  async function loadTicketPage(panel, page, prizeCode = null, afterTicketIndex = 0) {
    const report = state.report;
    if (!state.authenticated || !state.active || !report || state.loading || state.busy || !Number.isInteger(page)) return;
    const predictionId = panel.dataset.predictionId;
    const method = methods.find(item => item.key === panel.dataset.method);
    const cycle = report.cycles?.find(item => item.methods?.[method?.key]?.predictionId === predictionId);
    const entry = cycle?.methods?.[method?.key];
    if (!entry || !predictionId) return;
    const view = ticketView(entry, cycle);
    const pagination = view === 'bao' ? entry.baoPagination : entry.ticketPagination;
    const pageLimit = view === 'bao' ? Math.ceil(Number(cycle.config?.baoCount || 0) / 10) : Number(pagination?.totalPages || 1);
    const loaded = view === 'bao' ? Array.isArray(entry.baoParents) : Array.isArray(entry.tickets);
    if (page < 1 || page > pageLimit || (!prizeCode && loaded && view === ticketView(entry, cycle) && page === Number(pagination?.page))) return;
    state.ticketController?.abort();
    const controller = new AbortController();
    state.ticketController = controller;
    const generation = state.generation;
    closePrizeRewardHelp();
    panel.setAttribute("aria-busy", "true");
    delete panel.dataset.baoAutoFailed;
    const placeholder = panel.querySelector('.effectiveness-bao-retry');
    if (placeholder && view === 'bao') placeholder.textContent = 'Đang tải bộ Bao…';
    panel.querySelectorAll(".effectiveness-ticket-pager button, .effectiveness-ticket-pager input, [data-prize-jump], [data-bao-reload]").forEach(input => { input.disabled = true; });
    try {
      const result = await request(`/api/ml/effectiveness-tickets?type=${encodeURIComponent(report.type)}&predictionId=${encodeURIComponent(predictionId)}&page=${page}&view=${view}${prizeCode ? `&prizeCode=${encodeURIComponent(prizeCode)}${afterTicketIndex ? `&afterTicketIndex=${afterTicketIndex}` : ""}` : ""}`, { signal: controller.signal });
      if (generation !== state.generation || state.ticketController !== controller || state.report !== report) return;
      if (result.type !== report.type || result.predictionId !== predictionId) throw new Error("Trang vé không khớp dự đoán đã khóa.");
      if (prizeCode && (view === 'bao'
        ? !Number.isInteger(result.jumpBaoIndex) || !result.baoParents?.some(parent => parent.parentIndex === result.jumpBaoIndex && parent.result?.prizeCounts?.[prizeCode] > 0 && parent.result?.status === 'won')
        : !Number.isInteger(result.jumpTicketIndex) || !result.ticketResults?.some(item => item.ticketIndex === result.jumpTicketIndex && item.prizeCode === prizeCode && item.status === 'won'))) throw new Error('Không tìm thấy vé đã chọn trúng giải này trong trang trả về.');
      if (view === 'bao') {
        if (!Array.isArray(result.baoParents) || !result.baoPagination) throw new Error('Chưa đọc được bộ Bao gốc đã khóa.');
        Object.assign(entry, { baoParents: result.baoParents, baoPagination: result.baoPagination });
      } else Object.assign(entry, { tickets: result.tickets, ticketResults: result.ticketResults, ticketPagination: result.ticketPagination });
      state.ticketPages.set(predictionId, { tickets: entry.tickets, ticketResults: entry.ticketResults, ticketPagination: entry.ticketPagination, baoParents: entry.baoParents, baoPagination: entry.baoPagination, scoreKey: JSON.stringify([cycle.status, cycle.actualMain, cycle.actualSpecial]) });
      panel.innerHTML = cycleMethodHtml(cycle, method, report.type, reportSize(report));
      if (prizeCode) {
        const selectedIndex = view === 'bao' ? result.jumpBaoIndex : result.jumpTicketIndex;
        focusPrizeTicket(panel, selectedIndex);
        state.prizeCursors.set(prizeCursorKey(cycle, entry, method.key, prizeCode), selectedIndex);
      }
    } catch (error) {
      if (error.name === "AbortError" || generation !== state.generation || state.report !== report) return;
      if (error.status === 401) { expireSession(); return; }
      if (view === 'bao') panel.dataset.baoAutoFailed = 'true';
      showStatus(error.message, "error");
      panel.innerHTML = cycleMethodHtml(cycle, method, report.type, reportSize(report));
    } finally {
      panel.removeAttribute("aria-busy");
      if (state.ticketController === controller) state.ticketController = null;
      panel.querySelectorAll(".effectiveness-ticket-pager input").forEach(input => { input.disabled = false; });
      panel.querySelectorAll("[data-prize-jump], [data-bao-reload]").forEach(button => { button.disabled = false; });
      const currentPagination = ticketView(entry, cycle) === 'bao' ? entry.baoPagination : entry.ticketPagination;
      panel.querySelectorAll("[data-ticket-page]").forEach(button => { const target = Number(button.dataset.ticketPage); button.disabled = target < 1 || target > Number(currentPagination?.totalPages || 1); });
      if (generation === state.generation && state.report === report) setTimeout(() => { void loadVisibleBaoPages(); }, 0);
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
    void loadVisibleBaoPages();
  }

  function cycleExportHtml(cycle, report) {
    const busy = state.exportCycleId === cycle.cycleId && !!state.exportController;
    return `<span class="effectiveness-cycle-actions"><button type="button" class="secondary effectiveness-cycle-export" data-cycle-export="${escape(cycle.cycleId || '')}" title="Tải toàn bộ vé của bốn phương pháp${report.type === 'KENO' ? ` · bậc ${report.level}` : ''} thành Excel"${!cycle.cycleId || state.exportController ? ' disabled' : ''}${busy ? ' aria-busy="true"' : ''}><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12m-4-4 4 4 4-4M5 16v4h14v-4"/></svg><span>${busy ? 'Đang tải…' : 'Tải Excel'}</span></button><span class="effectiveness-cycle-toggle" aria-hidden="true"><span class="when-closed">Mở rộng</span><span class="when-open">Thu gọn</span></span></span>`;
  }

  function stopCycleExport() {
    state.exportController?.abort();
    state.exportController = null;
    state.exportCycleId = null;
  }

  async function downloadCycleExcel(button) {
    if (!state.authenticated || !state.report || state.exportController || state.loading || state.busy || button.disabled) return;
    const report = state.report;
    const cycle = report.cycles?.find(item => item.cycleId === button.dataset.cycleExport);
    if (!cycle) return;
    const generation = state.generation;
    const controller = new AbortController();
    state.exportController = controller;
    state.exportCycleId = cycle.cycleId;
    root.querySelectorAll('[data-cycle-export]').forEach(item => { item.disabled = true; });
    button.setAttribute('aria-busy', 'true');
    button.querySelector('span').textContent = 'Đang tải…';
    showStatus(`Đang chuẩn bị Excel kỳ ${cycle.targetDrawId}…`);
    try {
      const saveWorkbook = blob => {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `du_doan_thuc_te_${report.type.toLowerCase()}_ky_${cycle.targetDrawId}${report.type === 'KENO' ? `_bac_${report.level}` : cycle.config?.playMode === 'bao' ? `_bao_${cycle.config.baoLevel}` : '_ve_thuong'}.xlsx`;
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
        showStatus(`Đã tải Excel kỳ ${cycle.targetDrawId} · toàn bộ vé của bốn phương pháp.`);
      };
      if (cycle.config?.playMode === 'bao' || Object.values(cycle.methods || {}).some(entry => entry.seedSchedule || Number(entry.ticketCount ?? entry.ticketPagination?.total) > 10000)) {
        const response = await fetch(`/api/ml/effectiveness-export?type=${encodeURIComponent(report.type)}&cycleId=${encodeURIComponent(cycle.cycleId)}&level=${encodeURIComponent(report.level || 10)}&format=xlsx`, { credentials: 'same-origin', signal: controller.signal });
        if (!response.ok) {
          const problem = await response.json().catch(() => ({}));
          const error = new Error(problem.message || 'Không tải được Excel. Vui lòng thử lại.');
          error.status = response.status;
          throw error;
        }
        if (!response.headers.get('Content-Type')?.includes('spreadsheetml.sheet')) throw new Error('File Excel trả về không hợp lệ.');
        const blob = await response.blob();
        if (controller.signal.aborted || state.exportController !== controller || generation !== state.generation || state.report !== report || !state.authenticated) return;
        saveWorkbook(blob);
        return;
      }
      const data = await request(`/api/ml/effectiveness-export?type=${encodeURIComponent(report.type)}&cycleId=${encodeURIComponent(cycle.cycleId)}${report.type === 'KENO' ? `&level=${encodeURIComponent(report.level)}` : ''}`, { signal: controller.signal });
      if (controller.signal.aborted || state.exportController !== controller || generation !== state.generation || state.report !== report || !state.authenticated) return;
      if (data.type !== report.type || data.cycleId !== cycle.cycleId || String(data.targetDrawId) !== String(cycle.targetDrawId) || (report.type === 'KENO' && Number(data.level) !== Number(report.level))) throw new Error('Dữ liệu Excel không khớp kỳ đã chọn.');
      if (typeof buildXlsxWorkbookBlob !== 'function') throw new Error('Chưa tải được bộ xuất Excel. Hãy tải lại trang.');
      const balls = values => (Array.isArray(values) ? values : []).map(value => String(value).padStart(2, '0')).join(' ');
      const special = value => finite(value) ? String(value).padStart(2, '0') : '';
      const overview = [
        ['Loại vé', report.label || report.type], ['Kỳ', String(data.targetDrawId)],
        ...(data.type === 'KENO' ? [['Bậc Keno', data.level]] : []),
        ['Trạng thái', data.status === 'scored' ? 'Đã chấm' : 'Chờ kết quả'],
        ['Bộ số thực tế', balls(data.actualMain)], ['ĐB / bóng thứ 7 thực tế', special(data.actualSpecial)],
        ['Dữ liệu đến kỳ', String(data.cutoffDrawId)], ['Đã khóa lúc (giờ Việt Nam)', dateTime(data.createdAt)],
        ['Hạn khóa (giờ Việt Nam)', dateTime(data.deadline)], ['Mã kỳ dự đoán', data.cycleId],
        ['Checksum dữ liệu', data.dataHash], ['Nguồn kết quả', data.actualSource === 'recorded_ledger_score' ? 'Kết quả đã lưu khi chấm' : 'Chờ kết quả'],
        ['Phạm vi', 'Toàn bộ vé đã khóa của bốn phương pháp trong kỳ được chọn.'],
      ];
      const headers = ['Vé', 'Bộ số dự đoán', 'ĐB dự đoán', 'Số chính trùng', 'SL số chính trùng', 'Trùng ĐB / bóng thứ 7', 'Kết quả', 'Giải trúng', 'Mã giải', 'Ghi chú'];
      const statuses = { won: 'Trúng giải', lost: 'Không trúng', pending: 'Chờ kết quả', unknown: 'Chưa xác định', invalid: 'Không hợp lệ', unsupported: 'Chưa hỗ trợ' };
      const actual = new Set((data.actualMain || []).map(Number));
      const sheets = methods.map(method => {
        const entry = data.methods?.[method.key];
        const tickets = entry?.tickets;
        const results = entry?.ticketResults;
        if (!entry || !Array.isArray(tickets) || tickets.length !== entry.ticketCount || tickets.length < 1 || tickets.length > 10000 || !Array.isArray(results) || results.length !== tickets.length || results.some((result, index) => Number(result.ticketIndex) !== index + 1)) throw new Error(`Dữ liệu ${method.label} chưa đầy đủ. Chưa tải file Excel.`);
        overview.push([`${method.label} · Số vé`, entry.ticketCount], [`${method.label} · Số vé trúng`, entry.prizeStatistics?.winningTicketCount ?? ''], [`${method.label} · Mã dự đoán`, entry.predictionId], [`${method.label} · Engine`, entry.engine || ''], [`${method.label} · Model`, entry.modelId || ''], [`${method.label} · Seed`, String(entry.seed ?? '')], [`${method.label} · Checksum dự đoán`, entry.payloadChecksum || '']);
        return { name: method.label, headers, columnWidths: [9, 34, 15, 30, 22, 27, 20, 25, 25, 55], rows: tickets.map((ticket, index) => {
          const result = results[index];
          return [index + 1, balls(ticket.main), special(ticket.special), balls((ticket.main || []).filter(value => actual.has(Number(value)))), finite(result.mainHits) ? Number(result.mainHits) : '', result.specialMatched === true ? 'Có' : result.specialMatched === false ? 'Không' : '', statuses[result.status] || result.status || '', result.prizeLabel || '', result.prizeCode || '', result.reason || ''];
        }) };
      });
      const title = `Dự Đoán & Thực Tế · ${report.label || report.type} · Kỳ ${data.targetDrawId}`;
      const blob = buildXlsxWorkbookBlob(['Thông tin', 'Giá trị'], overview, title, sheets, 'Tổng quan', [40, 88]);
      saveWorkbook(blob);
    } catch (error) {
      if (error.name === 'AbortError' || state.exportController !== controller || generation !== state.generation) return;
      if (error.status === 401) { expireSession(); return; }
      showStatus(error.message, 'error');
    } finally {
      if (state.exportController === controller) {
        state.exportController = null;
        state.exportCycleId = null;
        root.querySelectorAll('[data-cycle-export]').forEach(item => {
          item.disabled = !state.authenticated || !item.dataset.cycleExport || state.loading || state.busy;
          item.removeAttribute('aria-busy');
          item.querySelector('span').textContent = 'Tải Excel';
        });
      }
    }
  }

  function cycleStateKey(cycle, report) {
    const game = reportGame(report);
    return game === 'KENO' ? `${game}:${report.level}:cycle:${cycle.targetDrawId}` : `${game}:cycle:${cycle.cycleId || cycle.targetDrawId}`;
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
      const cycleKey = cycleStateKey(cycle, report);
      const selected = state.selectedMethods.get(cycleKey) || methods[0].key;
      const methodId = `cycle-method-${encodeURIComponent(cycleKey)}`;
      const lockedBudget = cycle.config?.ticketCountsByLevel?.[report.level] ?? cycle.config?.actualTicketCount ?? cycle.config?.ticketCount;
      const budget = finite(lockedBudget) ? number(lockedBudget, 0) : Array.isArray(cycle.methods?.web?.tickets) ? String(cycle.methods.web.tickets.length) : "—";
      const structureLabel = cycle.config?.playMode === "bao" ? `Bao ${cycle.config.baoLevel} · ${number(cycle.config.baoCount, 0)} Bao / phương pháp` : game === 'KENO' ? '' : `Vé Thường · ${budget} vé / phương pháp`;
      return `<details class="effectiveness-cycle${game === "KENO" ? " effectiveness-keno-cycle" : ""}" data-effectiveness-state="${escape(cycleKey)}"${opened(cycleKey)}><summary><span class="effectiveness-cycle-identity"><span><strong>Kỳ ${escape(cycle.targetDrawId)}</strong><span class="effectiveness-cycle-status${scored ? " is-scored" : ""}">${scoredText}</span></span><small>${game === "KENO" ? `Bậc ${mainCount} · Giờ quay` : "Hạn khóa"} ${escape(dateTime(cycle.deadline))}</small>${structureLabel ? `<small class="effectiveness-cycle-structure">${escape(structureLabel)}</small>` : ""}</span><span class="effectiveness-cycle-preview"><span class="effectiveness-preview-label">${actual.size ? "Số chính thực tế" : `${cycle.config?.playMode === "bao" ? `${number(cycle.config.baoCount, 0)} Bao` : `${escape(budget)} vé`} / phương pháp đã khóa`}</span>${actual.size ? actualNumbersHtml(cycle, game) : '<span class="effectiveness-waiting">Chờ dữ liệu kỳ quay</span>'}</span>${cycleExportHtml(cycle, report)}</summary><div class="effectiveness-cycle-body"><div class="effectiveness-method-view" data-method-cycle="${escape(cycleKey)}">${methodNavigationHtml(cycleKey, selected)}${methodPairs.map(pair => `<div class="effectiveness-cycle-methods effectiveness-paired-methods" id="${methodId}-${pair.key}-pair" role="tabpanel" aria-labelledby="${methodId}-${pair.key}-tab" data-method-pair="${pair.key}"${pair.key === selected ? "" : " hidden"}>${pair.methods.map(method => {
        const entry = cycle.methods?.[method.key] || {};
        const cached = state.ticketPages.get(entry.predictionId);
        if (cached?.scoreKey === JSON.stringify([cycle.status, cycle.actualMain, cycle.actualSpecial])) Object.assign(entry, { tickets: cached.tickets, ticketResults: cached.ticketResults, ticketPagination: cached.ticketPagination, baoParents: cached.baoParents, baoPagination: cached.baoPagination });
        else state.ticketPages.delete(entry.predictionId);
        return `<div class="effectiveness-cycle-method" id="${methodId}-${method.key}-panel" role="region" aria-label="${escape(method.label)}" data-prediction-id="${escape(entry.predictionId || '')}" data-method="${method.key}">${cycleMethodHtml(cycle, method, game, mainCount)}</div>`;
      }).join("")}</div>`).join("")}</div>${game === "KENO" ? `<p class="effectiveness-cycle-note">Chỉ mở bộ số bậc ${mainCount}. Các bậc còn lại đã được khóa cùng kỳ; đổi bậc để xem.</p>` : ""}${cycleInfoHtml(cycle, cycleKey, budget)}</div></details>`;
    }).join("");
    setTimeout(() => { void loadVisibleBaoPages(); }, 0);
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
    host.innerHTML = `<details class="effectiveness-keno-overview" data-effectiveness-state="${overviewKey}"${opened(overviewKey)}><summary><strong>Tổng quan 10 bậc</strong></summary><div class="effectiveness-table-wrap" tabindex="0" role="region" aria-label="Tổng quan mười bậc Keno"><table class="effectiveness-table effectiveness-keno-table"><caption><span>Số trùng trung bình / vé · tỷ lệ có giải</span></caption><thead><tr><th scope="col">Bậc</th>${methods.map(method => `<th scope="col"><span class="effectiveness-method-dot" style="background:${method.color}"></span>${escape(method.label)}</th>`).join("")}</tr></thead><tbody>${(Array.isArray(report.levels) ? report.levels : []).map(row => `<tr${Number(row.level) === Number(report.level) ? ' class="is-selected"' : ""}><th scope="row"><button type="button" class="secondary" data-keno-level="${Number(row.level)}" aria-pressed="${Number(row.level) === Number(report.level)}">Bậc ${Number(row.level)}</button><small>Ngẫu nhiên ${number(Number(row.level) / 4, 2)}</small></th>${methods.map(method => { const entry = row.methods?.[method.key] || {}; return `<td title="Chênh lệch so ngẫu nhiên cùng bậc: ${signed(entry.deltaVsRandom)}"><strong>${number(entry.meanHits, 2)}</strong><small>Có giải ${percent(entry.winningTicketRate)}</small></td>`; }).join("")}</tr>`).join("")}</tbody></table></div><p class="effectiveness-keno-caption">Mỗi bậc có mức trùng kỳ vọng khác nhau. So từng phương pháp với ngẫu nhiên cùng bậc; chưa chọn bậc tốt nhất từ bảng này.</p></details>`;
  }

  function render(report) {
    closePrizeRewardHelp();
    rememberOpenDetails();
    renderSummary(report);
    renderNotes(report);
    renderComparison(report);
    renderTimeline(report);
    renderCycles(report);
    renderCyclePager(report);
    renderKeno(report);
    const automationError = report.automation?.lastError;
    if (automationError) byId("effectivenessMixedWarning").innerHTML += `<p class="effectiveness-mixed-configurations"><strong>${String(automationError).includes("Tạm dừng tạo vé") ? "Chưa đủ dung lượng để tạo vé." : String(automationError).includes("đến giờ quay") ? "Bỏ lỡ hạn khóa kỳ. Chờ cập nhật kết quả." : "Đang chờ dữ liệu / lần khóa mới."}</strong> ${escape(automationError)}</p>`;
    const sourceSync = report.automation?.sourceSync;
    if (report.type === "KENO" && report.settings?.enabled && sourceSync?.lastAttempt) {
      const sourceText = sourceSync.error ? "Tự cập nhật Keno đang chờ nguồn; sẽ thử lại."
        : `Tự cập nhật Keno · CSV kỳ ${sourceSync.latestKy || "—"}${sourceSync.latestTime ? ` lúc ${sourceSync.latestTime}` : ""} · kiểm tra ${dateTime(sourceSync.lastSuccess || sourceSync.lastAttempt)}`;
      byId("effectivenessMixedWarning").innerHTML += `<p class="effectiveness-mixed-configurations">${escape(sourceText)}</p>`;
    }
    setControls();
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
    syncTimer();
    showStatus("Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại.", "error");
  }

  function clearReport() {
    state.prizeController?.abort();
    state.prizeController = null;
    stopCycleExport();
    closePrizeRewardHelp();
    state.ticketController?.abort();
    state.ticketController = null;
    state.ticketPages.clear();
    state.prizeCursors.clear();
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
    stopCycleExport();
    state.prizeController?.abort();
    state.prizeController = null;
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
    activity.localPhase = "updating"; activity.requestStarted = performance.now(); activity.error = "";
    setControls();
    showStatus("Đang tải báo cáo…");
    try {
      const report = await request(`/api/ml/effectiveness?type=${encodeURIComponent(type)}&limit=${encodeURIComponent(limit)}${type === "KENO" ? `&level=${encodeURIComponent(level)}&page=${page}` : ""}`, { signal: controller.signal });
      if (generation !== state.generation || state.controller !== controller || byId("effectivenessType").value !== type) return;
      if (report.type !== type) throw new Error("Báo cáo hiệu quả không khớp loại xổ số đang chọn.");
      if (type === "KENO" && (String(report.level) !== level || page !== state.page || level !== byId("effectivenessKenoLevel").value)) return;
      const keepPosition = scrollAnchor && Math.abs(window.scrollY - scrollAnchor.scrollY) < 2;
      state.report = report;
      activity.reportEstimate = Math.max(1, (performance.now() - activity.requestStarted) / 1000 * 1.2);
      render(report);
      void loadPrizeContexts(report);
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
        renderActivity();
        void loadVisibleBaoPages();
      }
    }
  }

  async function mutate(action) {
    if (!state.report?.canManage || state.busy || state.loading || !state.authenticated) return;
    const generation = state.generation;
    const type = byId("effectivenessType").value;
    const form = { type };
    const saveBeforeLock = action === "cycle" && supportsBao();
    if (action === "settings" || saveBeforeLock) {
      try { Object.assign(form, settingsForm()); }
      catch (error) { showStatus(error.message, "error"); return; }
    }
    state.busy = true;
    activity.localPhase = action === "settings" ? "updating" : "creating";
    setControls();
    showStatus(action === "settings" ? "Đang lưu cấu hình…" : "Đang tạo và khóa bộ số của bốn phương pháp…");
    let message = "", failed = false;
    try {
      if (saveBeforeLock) {
        const saved = await request('/api/ml/effectiveness-settings', { method: "POST", form });
        if (generation !== state.generation) return;
        if (saved.settings?.playMode !== form.playMode || !/^[0-9a-f]{64}$/.test(saved.settings?.configurationHash || "")) throw new Error("Cấu hình chưa được xác nhận. Hãy làm mới trước khi khóa kỳ.");
        form.configurationHash = saved.settings.configurationHash;
      }
      const response = await request(`/api/ml/effectiveness-${action === "settings" ? "settings" : "cycle"}`, { method: "POST", form });
      if (generation !== state.generation) return;
      if (response.billing) window.dispatchEvent(new CustomEvent('dvlf:prediction-wallet', { detail: response.billing }));
      const selection = response.playMode === 'bao' ? `Bao ${response.baoLevel}` : 'Loại vé này';
      message = action === "settings" ? "Đã lưu cấu hình. Trước giờ quay có thể khóa thêm loại Bao khác; bộ đã mua giữ nguyên." : response.status === "already_locked" ? `${selection} của kỳ #${response.targetDrawId} đã có. Giữ nguyên bộ số, số lượng và không trừ thêm phí.` : String(response.message || "Đã tạo bộ số và thu phí cho cơ cấu vừa chọn. Mở nhật ký để xem.");
    } catch (error) {
      if (generation !== state.generation) return;
      failed = true;
      message = error.message;
    } finally {
      if (generation === state.generation) {
        state.busy = false;
        setControls();
        renderActivity();
      }
    }
    if (generation !== state.generation) return;
    if (failed) showStatus(message, "error");
    else await refresh({ statusAfter: message });
  }

  function syncTimer() {
    if (state.timer) { clearInterval(state.timer); state.timer = null; }
    if (state.active && state.authenticated) {
      state.timer = setInterval(() => { if (!document.hidden && !state.loading && !state.busy && !state.ticketController && !state.exportController) void refresh(); }, isKeno() ? 60000 : 120000);
    }
    syncActivity();
  }

  window.VietlottEffectiveness = Object.freeze({
    activate(active) {
      const changed = state.active !== !!active;
      state.active = !!active;
      syncTimer();
      if (state.active && state.authenticated && (changed || !state.report)) void refresh();
      if (!state.active) { stopCycleExport(); state.controller?.abort(); state.ticketController?.abort(); state.ticketController = null; state.loading = false; setSettingsOpen(false); setHelpOpen(false); setControls(); }
      if (!state.active) { state.prizeController?.abort(); state.prizeController = null; closePrizeRewardHelp(); }
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
    showStatus(state.authenticated ? "Mở tab Dự Đoán & Thực Tế để tải báo cáo." : "Đăng nhập để xem báo cáo.");
    syncTimer();
    if (state.active && state.authenticated) void refresh();
  });
  root.addEventListener("toggle", event => {
    if (event.target.matches("details[data-effectiveness-state]") && root.contains(event.target)) state.openDetails.set(event.target.dataset.effectivenessState, event.target.open);
    if (event.target.open) void loadVisibleBaoPages();
  }, true);
  ["effectivenessType", "effectivenessLimit"].forEach(id => byId(id).addEventListener("change", () => {
    setSettingsOpen(false);
    setHelpOpen(false);
    rememberOpenDetails(); clearReport();
    state.page = 1;
    if (id === "effectivenessType") syncTimer();
    void refresh();
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
  byId("effectivenessRefresh").addEventListener("click", () => { syncActivity(); void refresh(); });
  byId("effectivenessCycles").addEventListener("click", event => {
    const seedButton = event.target.closest('[data-copy-ticket-seed]');
    if (seedButton) { event.preventDefault(); event.stopPropagation(); void copyTicketSeed(seedButton); return; }
    const exportButton = event.target.closest('[data-cycle-export]');
    if (exportButton) { event.preventDefault(); event.stopPropagation(); void downloadCycleExcel(exportButton); return; }
    const prizeButton = event.target.closest("[data-prize-jump]");
    if (prizeButton) { jumpToPrizeTicket(prizeButton); return; }
    const retry = event.target.closest('[data-bao-reload]');
    if (retry && !retry.disabled) { void loadTicketPage(retry.closest('.effectiveness-cycle-method'), 1); return; }
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
  byId("effectivenessPlayMode").addEventListener("click", event => {
    const button = event.target.closest("[data-effectiveness-mode]");
    if (!button || button.disabled || !supportsBao()) return;
    state.draftPlayMode = button.dataset.effectivenessMode;
    setControls();
  });
  byId("effectivenessBaoLevel").addEventListener("change", () => { normalizeBaoCount(); setControls(); });
  // Format and clamp before rendering the quote for this same input event.
  window.VietlottNumericInput.bind(byId("effectivenessBaoCount"), { maximum: baoMaximum, minimum: 1, rejectMalformed: false, liveComposition: true });
  byId("effectivenessBaoCount").addEventListener("input", () => setControls());
  byId("effectivenessBaoCount").addEventListener("change", () => setControls());
  byId("effectivenessBaoCount").addEventListener("compositionend", () => requestAnimationFrame(() => setControls()));
  window.VietlottNumericInput.bind(byId("effectivenessTicketCount"), { maximum: ticketMaximum, minimum: 1, rejectMalformed: false });
  byId("effectivenessTicketCount").addEventListener("input", renderSettingsSummary);
  byId("effectivenessTicketCount").addEventListener("change", renderSettingsSummary);
  byId("effectivenessEnabled").addEventListener("change", renderSettingsSummary);
  byId("effectivenessLock").addEventListener("click", () => void mutate("cycle"));
  byId("effectivenessTimeline").addEventListener("click", event => {
    const scaleButton = event.target.closest("[data-effectiveness-scale-toggle]");
    if (scaleButton && state.report) {
      rememberOpenDetails();
      state.timelineFullScale = !state.timelineFullScale;
      renderTimeline(state.report);
      byId("effectivenessTimeline").querySelector("[data-effectiveness-scale-toggle]")?.focus();
      return;
    }
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
  });
  setControls();
})();
