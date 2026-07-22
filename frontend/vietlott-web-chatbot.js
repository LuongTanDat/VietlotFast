(() => {
  "use strict";

  const STORAGE_KEY = "dvlf_local_chatbot_history_v1";
  const OPEN_KEY = "dvlf_local_chatbot_open_v1";
  const SIZE_KEY = "dvlf_local_chatbot_size_v1";
  const MAX_HISTORY = 40;
  const state = { history: [], pendingSets: null, pendingType: "", pendingLevel: null };

  const root = document.querySelector("[data-local-chatbot]");
  if (!root) return;
  const panel = root.querySelector("[data-local-chatbot-panel]");
  const launcher = root.querySelector("[data-local-chatbot-toggle]");
  const messages = root.querySelector("[data-local-chatbot-messages]");
  const contextNode = root.querySelector("[data-local-chatbot-context]");
  const form = root.querySelector("[data-local-chatbot-form]");
  const input = root.querySelector("[data-local-chatbot-input]");
  const settings = root.querySelector("[data-local-chatbot-settings]");
  const settingsToggle = root.querySelector("[data-local-chatbot-settings-toggle]");
  const sizeSlider = root.querySelector("[data-local-chatbot-size-slider]");

  const TYPE_LABELS = {
    KENO: "Keno",
    LOTO_5_35: "Loto 5/35",
    LOTO_6_45: "Mega 6/45",
    LOTO_6_55: "Power 6/55",
    MAX_3D: "Max 3D",
    MAX_3D_PRO: "Max 3D Pro",
  };

  function escapeChatHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function normalizeChatText(value) {
    return String(value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/đ/g, "d")
      .replace(/Đ/g, "D")
      .toLowerCase()
      .trim();
  }

  function getChatContext() {
    try {
      const type = typeof statsSelectedType === "string" ? normalizeStatsType(statsSelectedType) : "KENO";
      const config = typeof getStatsRecentTicketConfig === "function"
        ? getStatsRecentTicketConfig(type)
        : { maxSets: 6, mainCount: type === "KENO" ? 10 : 6, hasSpecial: false };
      const setCount = typeof getStatsRecentSetCount === "function" ? getStatsRecentSetCount(type) : 1;
      const sets = typeof getStatsRecentSelectedSets === "function" ? getStatsRecentSelectedSets(type) : [];
      const activeIndex = typeof getStatsRecentActiveSetIndex === "function" ? getStatsRecentActiveSetIndex(type) : 0;
      return { type, config, setCount, sets, activeIndex };
    } catch {
      return { type: "KENO", config: { maxSets: 6, mainCount: 10, hasSpecial: false }, setCount: 1, sets: [], activeIndex: 0 };
    }
  }

  function formatNumber(type, value) {
    const numeric = Number(value);
    if (type === "MAX_3D" || type === "MAX_3D_PRO") return String(numeric).padStart(3, "0");
    return String(numeric).padStart(2, "0");
  }

  function updateContextBadge() {
    const ctx = getChatContext();
    const filled = ctx.sets.slice(0, ctx.setCount).filter(set => set?.main?.length || set?.special !== null).length;
    const level = ctx.type === "KENO" ? ` • Bậc ${ctx.config.mainCount}` : "";
    contextNode.textContent = `${TYPE_LABELS[ctx.type] || ctx.type}${level} • ${filled}/${ctx.setCount} bộ đã chọn`;
  }

  function saveHistory() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state.history.slice(-MAX_HISTORY)));
    } catch {}
  }

  function loadHistory() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
      state.history = Array.isArray(saved) ? saved.slice(-MAX_HISTORY) : [];
    } catch {
      state.history = [];
    }
  }

  function addMessage(role, text, { html = "", actions = [], persist = true } = {}) {
    const item = document.createElement("article");
    item.className = `local-chatbot-message is-${role}`;
    const bubble = document.createElement("div");
    bubble.className = "local-chatbot-bubble";
    if (html) bubble.innerHTML = html;
    else bubble.textContent = text;
    item.appendChild(bubble);
    if (actions.length) {
      const actionRow = document.createElement("div");
      actionRow.className = "local-chatbot-message-actions";
      actions.forEach(action => {
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.localChatbotAction = action.id;
        button.textContent = action.label;
        actionRow.appendChild(button);
      });
      item.appendChild(actionRow);
    }
    messages.appendChild(item);
    messages.scrollTop = messages.scrollHeight;
    if (persist && text && (role === "user" || role === "bot")) {
      state.history.push({ role, text: String(text).slice(0, 1000), at: Date.now() });
      state.history = state.history.slice(-MAX_HISTORY);
      saveHistory();
    }
  }

  function renderHistory() {
    messages.innerHTML = "";
    if (!state.history.length) {
      addMessage("bot", "Chào bạn! Mình là trợ lý nội bộ DVLF. Mình có thể kiểm tra bộ số, đọc thống kê, tạo gợi ý và lưu lựa chọn — hoàn toàn không dùng API.", { persist: false });
      return;
    }
    state.history.forEach(item => addMessage(item.role === "user" ? "user" : "bot", item.text || "", { persist: false }));
  }

  function setOpen(open) {
    root.classList.toggle("is-open", !!open);
    panel.setAttribute("aria-hidden", open ? "false" : "true");
    launcher.setAttribute("aria-expanded", open ? "true" : "false");
    try { localStorage.setItem(OPEN_KEY, open ? "1" : "0"); } catch {}
    if (open) {
      updateContextBadge();
      window.setTimeout(() => input.focus(), 80);
    }
  }

  function setAuthenticated(authenticated) {
    const allowed = !!authenticated;
    root.classList.toggle("is-authenticated", allowed);
    root.setAttribute("aria-hidden", allowed ? "false" : "true");
    if (!allowed) setOpen(false);
  }

  function setSettingsOpen(open) {
    if (!settings || !settingsToggle) return;
    settings.classList.toggle("is-open", !!open);
    settings.setAttribute("aria-hidden", open ? "false" : "true");
    settingsToggle.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function applyChatSize(value, persist = true) {
    const allowed = ["25", "50", "75", "100"];
    const size = allowed.includes(String(value)) ? String(value) : "25";
    root.dataset.chatSize = size;
    if (sizeSlider) sizeSlider.value = size;
    root.querySelectorAll("[data-local-chatbot-size-option]").forEach(option => {
      option.classList.toggle("is-active", option.dataset.localChatbotSizeOption === size);
    });
    if (persist) {
      try { localStorage.setItem(SIZE_KEY, size); } catch {}
    }
  }

  function describeSets() {
    const ctx = getChatContext();
    const rows = ctx.sets.slice(0, ctx.setCount).map((set, index) => {
      const main = Array.isArray(set?.main) ? set.main : [];
      const special = set?.special;
      const missing = Math.max(0, ctx.config.mainCount - main.length);
      const duplicateCount = main.length - new Set(main).size;
      const status = !main.length && special === null
        ? "trống"
        : (missing ? `thiếu ${missing} số` : (ctx.config.hasSpecial && special === null ? "thiếu số đặc biệt" : "đã đủ"));
      return { index, main, special, missing, duplicateCount, status };
    });
    const complete = rows.filter(row => row.status === "đã đủ").length;
    const issues = rows.filter(row => row.status !== "đã đủ");
    const html = `
      <strong>${escapeChatHtml(TYPE_LABELS[ctx.type] || ctx.type)}${ctx.type === "KENO" ? ` • Bậc ${ctx.config.mainCount}` : ""}</strong>
      <p>${complete}/${ctx.setCount} bộ đã hoàn chỉnh.</p>
      <div class="local-chatbot-check-list">
        ${rows.map(row => `<span class="${row.status === "đã đủ" ? "is-ok" : ""}">Bộ ${row.index + 1}<b>${escapeChatHtml(row.status)}</b></span>`).join("")}
      </div>
      ${issues.length ? `<small>Chọn thêm số cho các bộ chưa đủ trước khi lưu dự đoán.</small>` : `<small>Các bộ đều hợp lệ theo cấu hình hiện tại.</small>`}
    `;
    addMessage("bot", `Đã kiểm tra: ${complete}/${ctx.setCount} bộ hoàn chỉnh.`, { html });
  }

  function collectNumberCandidates(role = "main") {
    const found = new Map();
    document.querySelectorAll(`[data-stats-recent-pick][data-stats-recent-pick-role="${role}"]`).forEach(node => {
      const value = Number(node.getAttribute("data-stats-recent-pick"));
      if (!Number.isInteger(value)) return;
      const title = String(node.getAttribute("title") || node.textContent || "");
      const countMatch = title.match(/(?:•|\s)(\d+)\s*(?:lần|kỳ)?/i);
      const count = countMatch ? Number(countMatch[1]) : 0;
      const existing = found.get(value);
      if (!existing || count > existing.count) found.set(value, { value, count });
    });
    return [...found.values()].sort((a, b) => b.count - a.count || a.value - b.value);
  }

  function getFallbackRange(type, config, role = "main") {
    if (role === "special" && config.hasSpecial) {
      return Array.from({ length: Math.max(0, config.specialMax - config.specialMin + 1) }, (_, i) => config.specialMin + i);
    }
    const meta = typeof TYPES === "object" ? TYPES[type] : null;
    const min = Number(meta?.mainMin ?? (type.startsWith("MAX_3D") ? 0 : 1));
    const max = Number(meta?.mainMax ?? (type === "KENO" ? 80 : 55));
    return Array.from({ length: Math.max(0, max - min + 1) }, (_, i) => min + i);
  }

  function buildRuleBasedSuggestions(requestText) {
    let ctx = getChatContext();
    const normalized = normalizeChatText(requestText);
    const levelMatch = normalized.match(/bac\s*(10|[1-9])/);
    if (ctx.type === "KENO" && levelMatch && typeof setStatsRecentKenoLevel === "function") {
      const level = Number(levelMatch[1]);
      setStatsRecentKenoLevel(level);
      if (typeof saveStatsUiState === "function") saveStatsUiState();
      ctx = getChatContext();
      state.pendingLevel = level;
    }
    const countMatch = normalized.match(/(?:tao|chon|goi y|du doan)\s*(?:cho toi\s*)?(\d+)\s*bo/)
      || normalized.match(/(\d+)\s*bo/);
    const requestedCount = countMatch ? Number(countMatch[1]) : ctx.setCount;
    const setCount = Math.min(ctx.config.maxSets, Math.max(1, Number.isInteger(requestedCount) ? requestedCount : 1));
    let mainCandidates = collectNumberCandidates("main");
    if (mainCandidates.length < ctx.config.mainCount) {
      mainCandidates = getFallbackRange(ctx.type, ctx.config).map(value => ({ value, count: 0 }));
    }
    const pool = mainCandidates.map(item => item.value);
    const suggestions = Array.from({ length: setCount }, (_, setIndex) => {
      const main = [];
      const stride = Math.max(1, Math.floor(pool.length / Math.max(1, ctx.config.mainCount)));
      for (let step = 0; step < pool.length * 2 && main.length < ctx.config.mainCount; step += 1) {
        const index = (setIndex * 3 + step * stride + Math.floor(step / Math.max(1, ctx.config.mainCount))) % pool.length;
        const value = pool[index];
        if (Number.isInteger(value) && !main.includes(value)) main.push(value);
      }
      main.sort((a, b) => a - b);
      let special = null;
      if (ctx.config.hasSpecial) {
        const specialPool = collectNumberCandidates("special").map(item => item.value);
        const fallbackSpecial = getFallbackRange(ctx.type, ctx.config, "special");
        const available = specialPool.length ? specialPool : fallbackSpecial;
        special = available.length ? available[setIndex % available.length] : null;
        if (main.includes(special)) special = available.find(value => !main.includes(value)) ?? null;
      }
      return { main, special };
    });
    state.pendingSets = suggestions;
    state.pendingType = ctx.type;
    return { ctx, suggestions, setCount };
  }

  function showSuggestions(text) {
    const { ctx, suggestions, setCount } = buildRuleBasedSuggestions(text);
    const html = `
      <strong>Gợi ý ${setCount} bộ ${escapeChatHtml(TYPE_LABELS[ctx.type] || ctx.type)}</strong>
      <p>Dựa trên tần suất đang hiển thị và quy tắc phân tán số.</p>
      <div class="local-chatbot-ticket-list">
        ${suggestions.map((set, index) => `
          <div><span>Bộ ${index + 1}</span><b>${set.main.map(value => formatNumber(ctx.type, value)).join(" ")}${set.special !== null ? ` • ĐB ${formatNumber(ctx.type, set.special)}` : ""}</b></div>
        `).join("")}
      </div>
      <small>Đây là gợi ý thống kê, không phải dự đoán chắc chắn.</small>
    `;
    addMessage("bot", `Đã tạo ${setCount} bộ gợi ý.`, {
      html,
      actions: [{ id: "apply-suggestions", label: "Áp dụng vào các Bộ" }, { id: "discard-suggestions", label: "Bỏ qua" }],
    });
  }

  function applyPendingSuggestions() {
    if (!Array.isArray(state.pendingSets) || !state.pendingSets.length) {
      addMessage("bot", "Chưa có gợi ý nào để áp dụng. Bạn hãy yêu cầu “Tạo gợi ý” trước.");
      return;
    }
    const ctx = getChatContext();
    if (ctx.type !== state.pendingType) {
      addMessage("bot", "Loại vé trên trang đã thay đổi. Hãy tạo lại gợi ý để tránh áp dụng nhầm.");
      return;
    }
    const sets = state.pendingSets.map(set => ({ main: [...set.main], special: set.special }));
    statsRecentSelectedByType[ctx.type] = { sets };
    setStatsRecentSetCount(ctx.type, sets.length);
    setStatsRecentActiveSetIndex(ctx.type, 0);
    saveStatsRecentSelectedState();
    renderStatsRecentSelectedHostOnly();
    state.pendingSets = null;
    updateContextBadge();
    addMessage("bot", `Đã áp dụng và lưu ${sets.length} bộ vào ${TYPE_LABELS[ctx.type] || ctx.type}. Bộ gốc trước đó đã được thay bằng gợi ý mới.`);
  }

  function saveCurrentSelection() {
    const ctx = getChatContext();
    const filled = ctx.sets.slice(0, ctx.setCount).filter(set => set?.main?.length || set?.special !== null).length;
    if (!filled) {
      addMessage("bot", "Chưa có bộ số nào để lưu.");
      return;
    }
    const saved = typeof saveStatsRecentSelectedState === "function" ? saveStatsRecentSelectedState() : false;
    addMessage("bot", saved
      ? `Đã lưu ${filled} bộ đang chọn trên trình duyệt này.`
      : "Không thể lưu lựa chọn. Bạn hãy kiểm tra quyền lưu dữ liệu của trình duyệt.");
  }

  function explainHelp() {
    const ctx = getChatContext();
    const html = `
      <strong>Mình có thể hỗ trợ</strong>
      <ul>
        <li><b>“Kiểm tra các bộ”</b> — báo bộ thiếu hoặc đã đủ.</li>
        <li><b>“Tạo 3 bộ Keno bậc 10”</b> — tạo gợi ý từ thống kê hiện tại.</li>
        <li><b>“Lưu các bộ”</b> — lưu lựa chọn trên trình duyệt.</li>
        <li><b>“Trạng thái”</b> — đọc loại vé và bộ đang thao tác.</li>
      </ul>
      <small>Hiện tại: ${escapeChatHtml(TYPE_LABELS[ctx.type] || ctx.type)}, Bộ ${ctx.activeIndex + 1}.</small>
    `;
    addMessage("bot", "Mình đã hiển thị các lệnh có thể sử dụng.", { html });
  }

  function answerStatus() {
    const ctx = getChatContext();
    const active = ctx.sets[ctx.activeIndex] || { main: [], special: null };
    const numbers = active.main.length ? active.main.map(value => formatNumber(ctx.type, value)).join(", ") : "chưa chọn số";
    addMessage("bot", `${TYPE_LABELS[ctx.type] || ctx.type}${ctx.type === "KENO" ? ` bậc ${ctx.config.mainCount}` : ""}. Đang thao tác Bộ ${ctx.activeIndex + 1}: ${numbers}.`);
  }

  function processUserMessage(rawText) {
    const text = String(rawText || "").trim();
    if (!text) return;
    addMessage("user", text);
    const normalized = normalizeChatText(text);
    window.setTimeout(() => {
      if (/\b(tao|goi y|du doan|chon so)\b/.test(normalized)) return showSuggestions(text);
      if (/\b(kiem tra|hop le|thieu so|du so)\b/.test(normalized)) return describeSets();
      if (/\b(luu|save)\b/.test(normalized)) return saveCurrentSelection();
      if (/\b(trang thai|dang chon|bo nao|loai ve)\b/.test(normalized)) return answerStatus();
      if (/\b(huong dan|giup|lam duoc gi|tro giup)\b/.test(normalized)) return explainHelp();
      if (/\b(xin chao|chao|hello|hi)\b/.test(normalized)) {
        return addMessage("bot", "Chào bạn! Bạn có thể nhờ mình kiểm tra Bộ, tạo gợi ý theo thống kê hoặc lưu các Bộ đang chọn.");
      }
      addMessage("bot", "Mình chưa hiểu rõ yêu cầu này. Bạn có thể thử: “Kiểm tra các bộ”, “Tạo 3 bộ Keno bậc 10”, “Lưu các bộ” hoặc “Hướng dẫn”.");
    }, 180);
  }

  launcher.addEventListener("click", () => setOpen(!root.classList.contains("is-open")));
  root.querySelector("[data-local-chatbot-close]").addEventListener("click", () => {
    setSettingsOpen(false);
    setOpen(false);
  });
  if (settingsToggle) settingsToggle.addEventListener("click", () => setSettingsOpen(!settings.classList.contains("is-open")));
  if (sizeSlider) sizeSlider.addEventListener("input", () => applyChatSize(sizeSlider.value));
  root.querySelector("[data-local-chatbot-reset]").addEventListener("click", () => {
    state.history = [];
    state.pendingSets = null;
    saveHistory();
    renderHistory();
    setSettingsOpen(false);
  });
  document.addEventListener("click", event => {
    if (!settings?.classList.contains("is-open")) return;
    if (event.target.closest("[data-local-chatbot-settings], [data-local-chatbot-settings-toggle]")) return;
    setSettingsOpen(false);
  });
  root.querySelectorAll("[data-local-chatbot-prompt]").forEach(button => {
    button.addEventListener("click", () => processUserMessage(button.dataset.localChatbotPrompt));
  });
  messages.addEventListener("click", event => {
    const button = event.target.closest("[data-local-chatbot-action]");
    if (!button) return;
    if (button.dataset.localChatbotAction === "apply-suggestions") applyPendingSuggestions();
    if (button.dataset.localChatbotAction === "discard-suggestions") {
      state.pendingSets = null;
      addMessage("bot", "Đã bỏ bản gợi ý. Các Bộ hiện tại không thay đổi.");
    }
    button.closest(".local-chatbot-message-actions")?.querySelectorAll("button").forEach(node => { node.disabled = true; });
  });
  form.addEventListener("submit", event => {
    event.preventDefault();
    const text = input.value;
    input.value = "";
    input.style.height = "auto";
    processUserMessage(text);
  });
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(96, input.scrollHeight)}px`;
  });
  input.addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  loadHistory();
  renderHistory();
  updateContextBadge();
  try { applyChatSize(localStorage.getItem(SIZE_KEY) || "25", false); } catch { applyChatSize("25", false); }
  let authenticatedAtBoot = false;
  try { authenticatedAtBoot = typeof currentUser === "string" && currentUser.trim().length > 0; } catch {}
  setAuthenticated(authenticatedAtBoot);
  try { setOpen(authenticatedAtBoot && localStorage.getItem(OPEN_KEY) === "1"); } catch { setOpen(false); }
  window.addEventListener("dvlf:auth-changed", event => {
    setAuthenticated(event.detail?.authenticated === true);
    if (event.detail?.authenticated === true) updateContextBadge();
  });
  document.addEventListener("change", event => {
    if (event.target.closest("[data-stats-recent-set-count], [data-stats-recent-active-set-select], [data-stats-recent-keno-level]")) {
      window.setTimeout(updateContextBadge, 0);
    }
  });
  document.addEventListener("click", event => {
    if (event.target.closest("[data-stats-recent-pick], [data-stats-recent-selected-remove], [data-stats-recent-active-set]")) {
      window.setTimeout(updateContextBadge, 0);
    }
  });
})();
