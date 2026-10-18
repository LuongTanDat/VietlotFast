(() => {
  "use strict";
  const root = document.getElementById("adminPanelSection");
  const byId = id => document.getElementById(id);
  const state = { view: "codes", tab: "create", page: 1, total: 0, rows: [], stats: null, generation: 0, creation: 0, search: "", selected: new Set(), editingCodes: false, deleting: false, deletion: 0 };
  const labels = { promotion: "Khuyến mãi", vip: "VIP", gift: "Quà tặng" };
  let quickCode = "", quickPrefix = "", finishSuccessNotice = null, finishDeleteChoice = null;
  const titles = {
    codes: ["Quản lý Code", "Tạo và quản lý mã trên hệ thống"],
    overview: ["Tổng quan", "Thông tin quản trị từ dữ liệu hệ thống"],
    users: ["Người dùng", "Theo dõi và quản lý tài khoản đã đăng ký"],
    stats: ["Thống kê", "Số lượng mã và lượt sử dụng thực tế"],
    settings: ["Cài đặt", "Tùy chỉnh giao diện và cài đặt web"]
  };
  const allowed = () => currentUserRole === "admin" && !!currentUser;
  const claimTimeUnits = { seconds: [1, "giây"], minutes: [60, "phút"], hours: [3600, "giờ"], days: [86400, "ngày"] };
  const maxCooldownSeconds = 31536000;
  function claimRule(code) {
    if (code.cooldownSeconds > 0) {
      const [factor, unit] = [claimTimeUnits.days, claimTimeUnits.hours, claimTimeUnits.minutes, claimTimeUnits.seconds].find(([factor]) => code.cooldownSeconds % factor === 0);
      return `Nhận lại sau mỗi ${formatLuckyWheelAmount(code.cooldownSeconds / factor)} ${unit}, đến khi hết quà.`;
    }
    const count = code.maxPerUser || 1;
    return count === 1 ? "Mỗi ID nhận duy nhất 1 lần." : `Mỗi ID nhận tối đa ${formatLuckyWheelAmount(count)} lần.`;
  }
  function updateClaimControls(resetValue = false) {
    const once = byId("adminClaimLimit").value === "once";
    const mode = byId("adminClaimMode"), value = byId("adminClaimValue");
    mode.disabled = once; value.disabled = once; value.required = !once;
    if (once) { mode.value = "count"; value.value = "1"; }
    else if (resetValue) value.value = mode.value === "hours" ? "1" : "2";
    const timed = !once && mode.value === "hours", unit = byId("adminClaimTimeUnit");
    unit.hidden = !timed; unit.disabled = !timed;
    const scale = claimTimeUnits[unit.value];
    value.max = timed ? String(maxCooldownSeconds / scale[0]) : "1000000";
    byId("adminClaimUnit").hidden = timed;
    byId("adminClaimPolicyHint").textContent = once ? "Mỗi ID nhận duy nhất 1 lần từ mã này." : timed ? "Nhận lại sau thời gian chờ, đến khi mã hết quà; không giới hạn số lần theo ID." : "Số lần tối đa mỗi ID nhận từ mã này; mọi lần nhận đều dùng 1 phần quà.";
  }
  function updateActivationControls() {
    const scheduled = root.querySelector('[name="adminCodeActive"]:checked').value === "0";
    root.querySelector(".admin-code-basics").classList.toggle("has-activation", scheduled);
    byId("adminActivationField").hidden = !scheduled;
    byId("settingsCodeActivation").disabled = !scheduled;
  }
  function activationTime() {
    if (root.querySelector('[name="adminCodeActive"]:checked').value === "1") return "";
    const input = byId("settingsCodeActivation"), value = input.value;
    if (!value) return "";
    const time = new Date(`${value}+07:00`);
    const expiry = byId("settingsCodeExpiry").value;
    if (!Number.isFinite(time.getTime()) || time.getTime() <= getSyncedNowMs()) {
      input.focus(); throw new Error("Ngày giờ kích hoạt phải là thời gian tương lai hợp lệ.");
    }
    if (expiry && time.getTime() >= new Date(`${expiry}+07:00`).getTime()) {
      input.focus(); throw new Error("Ngày giờ kích hoạt phải trước ngày hết hạn.");
    }
    return time.toISOString();
  }
  function resetCreateForm() {
    const form = byId("settingsCreateCodeForm");
    form.reset(); form.removeAttribute("aria-busy");
    form.querySelector('button[type="submit"]').disabled = false;
    byId("adminCustomKindField").hidden = true; byId("adminCustomKindName").required = false;
    quickCode = ""; quickPrefix = "";
    updateClaimControls(); updateActivationControls();
    const node = byId("settingsCreateCodeMessage");
    node.textContent = "Chọn giá trị phần quà và quy tắc nhận code.";
    node.classList.remove("is-error", "is-success");
  }
  function dismissSuccessNotice() {
    if (finishSuccessNotice) finishSuccessNotice();
  }
  function showSuccessNotice() {
    dismissSuccessNotice();
    const notice = byId("adminCodeSuccess"), wasInert = root.inert;
    root.inert = true; notice.hidden = false;
    return new Promise(resolve => {
      const finish = () => {
        clearTimeout(timer); notice.hidden = true; root.inert = wasInert;
        finishSuccessNotice = null; resolve();
      };
      finishSuccessNotice = finish;
      const timer = setTimeout(finish, 2000);
    });
  }
  function numericValue(id, label) {
    const input = byId(id), amount = parseAccountBalance(input.value, label);
    const min = input.getAttribute("min"), max = input.getAttribute("max");
    if ((min !== null && amount < Number(min)) || (max !== null && amount > Number(max))) {
      input.focus();
      throw new Error(`${label} phải từ ${formatLuckyWheelAmount(Number(min || 0))} đến ${formatLuckyWheelAmount(Number(max))}.`);
    }
    return amount;
  }
  function message(text = "", error = false) {
    const node = byId("adminPageMessage");
    node.textContent = text; node.hidden = !text; node.classList.toggle("is-error", error);
  }
  function renderStats(stats) {
    state.stats = stats;
    byId("adminTotalCodes").textContent = formatLuckyWheelAmount(stats.total);
    byId("adminActiveCodes").textContent = formatLuckyWheelAmount(stats.active);
    const cards = items => items.map(([label, value]) => `<article><span>${label}</span><strong>${formatLuckyWheelAmount(value)}</strong></article>`).join("");
    byId("adminOverviewStats").innerHTML = cards([["Tài khoản", stats.users], ["Lượt nhận quà", stats.redemptions], ["Mã đã tắt", stats.inactive]]);
    byId("adminCodeStats").innerHTML = cards([["Mã khuyến mãi", stats.promotion], ["Mã VIP", stats.vip], ["Mã quà tặng", stats.gift], ["Mã khác", stats.custom || 0], ["Lượt nhận quà", stats.redemptions]]);
  }
  function rewardText(code, compact = false) {
    const format = compact ? formatCompactBalance : formatLuckyWheelAmount;
    const values = [];
    if (code.paypal) values.push(`${format(code.paypal)} PayPal`);
    if (code.diamond) values.push(`${format(code.diamond)} kim cương`);
    if (code.vipDays) values.push(`${code.vipDays} ngày VIP`);
    if (code.bonusSpins) values.push(`${code.bonusSpins} lượt quay`);
    return values.join(" · ");
  }
  function askReclaim(count) {
    const dialog = byId("adminReclaimDialog");
    byId("adminReclaimDescription").textContent = `Xóa ${count} Code đã chọn.`;
    return new Promise(resolve => {
      const finish = choice => {
        if (finishDeleteChoice !== finish) return;
        finishDeleteChoice = null; dialog.onclose = null;
        if (dialog.open) dialog.close();
        resolve(choice);
      };
      finishDeleteChoice = finish;
      dialog.onclose = () => { if (!dialog.open) finish(null); };
      byId("adminReclaimYesBtn").onclick = () => finish(true);
      byId("adminReclaimNoBtn").onclick = () => finish(false);
      byId("adminReclaimCancelBtn").onclick = () => finish(null);
      dialog.showModal();
    });
  }
  function updateCodeSelection() {
    const checks = [...byId("adminCodeRows").querySelectorAll('[data-admin-select]')];
    checks.forEach(input => { input.hidden = !state.editingCodes; input.checked = state.selected.has(input.dataset.adminSelect); input.disabled = !state.editingCodes || state.deleting; });
    const all = byId("adminSelectAllCodes"), count = checks.filter(input => input.checked).length;
    all.checked = checks.length > 0 && count === checks.length;
    all.indeterminate = count > 0 && count < checks.length;
    all.hidden = !state.editingCodes;
    all.disabled = !state.editingCodes || state.deleting || checks.length === 0;
    const button = byId("adminDeleteCodesBtn");
    button.disabled = state.deleting || (state.editingCodes && count === 0);
    button.classList.toggle("admin-delete", state.editingCodes);
    button.textContent = state.deleting ? "Đang xóa…" : !state.editingCodes ? "Chỉnh Sửa" : count ? `Xóa (${count})` : "Xóa";
    byId("adminFinishEditCodesBtn").hidden = !state.editingCodes;
    byId("adminFinishEditCodesBtn").disabled = state.deleting;
  }
  function setCodeEditMode(enabled) {
    state.editingCodes = enabled;
    state.selected.clear(); updateCodeSelection();
  }
  function clearCodeSelection() { state.selected.clear(); updateCodeSelection(); }
  function renderRows() {
    const visible = new Set(state.rows.map(code => code.code));
    state.selected.forEach(code => { if (!visible.has(code)) state.selected.delete(code); });
    byId("adminCodeRows").innerHTML = state.rows.map((code, index) => {
      const expired = code.expiresAt && Date.parse(code.expiresAt) <= getSyncedNowMs();
      const exhausted = code.usedCount >= code.maxUses;
      const ready = code.active && !expired && !exhausted;
      const scheduled = !code.active && !!code.activatesAt;
      const status = expired ? "Hết hạn" : exhausted ? "Hết lượt" : scheduled ? "Chờ kích hoạt" : !code.active ? "Chưa kích hoạt" : "Đang hoạt động";
      const activation = scheduled ? `<small>Kích hoạt ${escapeHtml(new Date(code.activatesAt).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh", dateStyle: "short", timeStyle: "short" }))}</small>` : "";
      const expiry = code.expiresAt ? new Date(code.expiresAt).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh", dateStyle: "short", timeStyle: "short" }) : "Không hết hạn";
      const kindName = code.kind.startsWith("custom:") ? code.kind.slice(7) : labels[code.kind] || "Quà tặng";
      return `<tr><td><div class="admin-code-cell"><input type="checkbox" hidden data-admin-select="${escapeHtml(code.code)}" aria-label="Chọn mã ${escapeHtml(code.code)}" /><strong class="admin-code-name">${escapeHtml(code.code)}</strong><button type="button" class="admin-code-copy" data-admin-copy="${index}" title="Sao chép mã" aria-label="Sao chép mã ${escapeHtml(code.code)}"><svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><rect x="9" y="9" width="11" height="12" rx="2"/><path d="M15 9V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h4"/></svg></button></div></td><td class="admin-code-kind">${escapeHtml(kindName)}</td><td title="${escapeHtml(rewardText(code))}">${escapeHtml(rewardText(code, true))}</td><td class="admin-code-limit">${escapeHtml(claimRule(code))}</td><td>${formatLuckyWheelAmount(code.usedCount)} / ${formatLuckyWheelAmount(code.maxUses)}</td><td>${escapeHtml(expiry)}</td><td><span class="admin-status ${ready ? "is-ready" : "is-paused"}">${status}</span>${activation}</td><td><div class="admin-row-actions"><button type="button" data-admin-toggle="${index}">${code.active ? "Tắt" : "Kích hoạt"}</button></div></td></tr>`;
    }).join("") || '<tr><td colspan="8" class="admin-empty">Chưa có code phù hợp.</td></tr>';
    updateCodeSelection();
    const pages = Math.max(1, Math.ceil(state.total / 20));
    byId("adminCodePageLabel").textContent = `${formatLuckyWheelAmount(state.total)} mã · Trang ${state.page} / ${pages}`;
    byId("adminPrevCodesBtn").disabled = state.page <= 1;
    byId("adminNextCodesBtn").disabled = state.page >= pages;
  }
  async function refresh() {
    if (!allowed() || root.hidden) return;
    const generation = ++state.generation, user = currentUser;
    try {
      const data = await api(`/api/admin/gift-codes?page=${state.page}&q=${encodeURIComponent(state.search)}`);
      if (!allowed() || generation !== state.generation || user !== currentUser || root.hidden) return;
      state.total = Number(data.total || 0);
      const lastPage = Math.max(1, Math.ceil(state.total / 20));
      if (state.page > lastPage) { state.page = lastPage; return refresh(); }
      state.rows = data.codes || []; renderStats(data.stats); renderRows();
    } catch (error) {
      if (generation === state.generation && user === currentUser) message(error.message, true);
    }
  }
  async function loadUsers() {
    const user = currentUser;
    try {
      const data = await api("/api/admin/users");
      if (!allowed() || user !== currentUser || root.hidden || state.view !== "users") return;
      byId("adminUserRows").innerHTML = (data.users || []).map(info => `<tr><td>${escapeHtml(info.username)}</td><td>${info.role === "admin" ? "Admin" : "Người dùng"}</td><td>${info.enabled ? "Cho phép" : "Đã khóa"}</td><td title="${formatLuckyWheelAmount(info.diamondBalance)}">${formatCompactBalance(info.diamondBalance)}</td><td title="${formatLuckyWheelAmount(info.paypalBalance)}">${formatCompactBalance(info.paypalBalance)}</td></tr>`).join("") || '<tr><td colspan="5" class="admin-empty">Chưa có tài khoản.</td></tr>';
    } catch (error) { if (user === currentUser) message(error.message, true); }
  }
  function selectTab(tab) {
    if (tab !== "list") setCodeEditMode(false);
    state.tab = tab;
    byId("adminCreatePane").hidden = tab !== "create";
    byId("adminListPane").hidden = tab !== "list";
    byId("adminCreateTab").setAttribute("aria-selected", String(tab === "create"));
    byId("adminListTab").setAttribute("aria-selected", String(tab === "list"));
    if (tab === "list") refresh();
  }
  function showView(view) {
    if (!allowed()) return;
    if (view !== "codes") setCodeEditMode(false);
    state.view = titles[view] ? view : "codes";
    byId("adminPageTitle").textContent = titles[state.view][0];
    byId("adminPageSubtitle").textContent = titles[state.view][1];
    root.querySelectorAll("[data-admin-pane]").forEach(node => node.hidden = node.dataset.adminPane !== state.view);
    root.querySelectorAll(".admin-nav [data-admin-view]").forEach(button => {
      const active = button.dataset.adminView === state.view;
      button.classList.toggle("is-active", active);
      if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
    });
    message();
    if (state.view === "users") loadUsers();
  }
  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      message("Đã sao chép code.");
    } catch {
      selectTab("create");
      const input = byId("settingsNewCode");
      input.value = text; quickCode = text; quickPrefix = "";
      input.focus(); input.select();
      message("Code đã được chọn. Nhấn Ctrl + C để sao chép.");
    }
  }
  byId("settingsCreateCodeForm").onsubmit = async event => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button[type="submit"]');
    if (button.disabled || !allowed()) return;
    const node = byId("settingsCreateCodeMessage"), user = currentUser, creation = ++state.creation;
    button.disabled = true; event.currentTarget.setAttribute("aria-busy", "true");
    node.classList.remove("is-error", "is-success");
    try {
      const expiry = byId("settingsCodeExpiry").value;
      const once = byId("adminClaimLimit").value === "once";
      const timed = !once && byId("adminClaimMode").value === "hours";
      const claimValue = once ? 1 : numericValue("adminClaimValue", timed ? "Thời gian chờ" : "Số lần nhận");
      const maxPerUser = timed ? 0 : claimValue;
      const cooldownSeconds = timed ? claimValue * claimTimeUnits[byId("adminClaimTimeUnit").value][0] : 0;
      const kind = byId("adminCodeKind").value;
      const manualCode = byId("settingsNewCode").value.trim();
      const kindName = byId("adminCustomKindName").value.trim();
      if (kind === "custom" && !kindName) {
        byId("adminCustomKindName").focus();
        throw new Error("Nhập tên loại Code.");
      }
      const response = await api("/api/admin/gift-codes", "POST", {
        code: manualCode,
        quantity: 1,
        length: byId("adminCodeLength").value, kind, kindName: kind === "custom" ? kindName : "",
        active: root.querySelector('[name="adminCodeActive"]:checked').value,
        activatesAt: activationTime(),
        paypal: numericValue("settingsCodePaypal", "PayPal"),
        diamond: numericValue("settingsCodeDiamond", "Kim cương"),
        vipDays: numericValue("settingsCodeVipDays", "Ngày VIP"),
        bonusSpins: numericValue("settingsCodeSpins", "Lượt quay"),
        maxUses: numericValue("settingsCodeMaxUses", "Số lượng phần quà"),
        maxPerUser, cooldownSeconds,
        expiresAt: expiry ? new Date(`${expiry}+07:00`).toISOString() : ""
      });
      if (user !== currentUser || !allowed() || creation !== state.creation) return;
      byId("settingsNewCode").value = response.code || response.codes[0];
      node.textContent = "";
      await showSuccessNotice();
      if (user !== currentUser || !allowed() || creation !== state.creation) return;
      clearCodeSelection(); resetCreateForm(); state.page = 1; state.search = "";
      byId("adminCodeSearch").value = "";
      if (!root.hidden) { showView("codes"); selectTab("create"); window.scrollTo(0, 0); }
      await refresh();
    } catch (error) {
      if (user === currentUser && creation === state.creation) { node.textContent = error.message; node.classList.add("is-error"); }
    } finally {
      if (creation === state.creation) {
        button.disabled = false; byId("settingsCreateCodeForm").removeAttribute("aria-busy");
      }
    }
  };
  root.querySelectorAll("[data-admin-view]").forEach(button => button.onclick = () => showView(button.dataset.adminView));
  byId("adminCreateTab").onclick = () => selectTab("create");
  byId("adminClaimLimit").onchange = () => updateClaimControls(true);
  byId("adminClaimMode").onchange = () => updateClaimControls(true);
  byId("adminClaimTimeUnit").onchange = () => updateClaimControls();
  byId("adminCodeKind").onchange = () => {
    const custom = byId("adminCodeKind").value === "custom";
    byId("adminCustomKindField").hidden = !custom;
    byId("adminCustomKindName").required = custom;
    if (custom) byId("adminCustomKindName").focus();
  };
  byId("adminListTab").onclick = () => selectTab("list");
  byId("adminBackBtn").onclick = () => navigateToAppPage("home");
  byId("adminThemeBtn").onclick = () => byId("themeToggleBtn").click();
  byId("adminWebSettingsBtn").onclick = () => { navigateToAppPage("home"); byId("settingsBtn").click(); };
  byId("adminManageUsersBtn").onclick = openAccountManager;
  byId("adminClearExpiryBtn").onclick = () => { byId("settingsCodeExpiry").value = ""; };
  byId("adminClearActivationBtn").onclick = () => { byId("settingsCodeActivation").value = ""; };
  root.querySelectorAll('[name="adminCodeActive"]').forEach(input => input.onchange = updateActivationControls);
  byId("adminRefreshCodesBtn").onclick = refresh;
  byId("adminFinishEditCodesBtn").onclick = () => { if (!state.deleting) setCodeEditMode(false); };
  byId("adminSelectAllCodes").onchange = event => {
    if (!state.editingCodes || state.deleting) return;
    state.rows.forEach(code => { if (event.target.checked) state.selected.add(code.code); else state.selected.delete(code.code); });
    updateCodeSelection();
  };
  byId("adminCodeRows").onchange = event => {
    if (!event.target.matches('[data-admin-select]') || !state.editingCodes || state.deleting) return;
    if (event.target.checked) state.selected.add(event.target.dataset.adminSelect); else state.selected.delete(event.target.dataset.adminSelect);
    updateCodeSelection();
  };
  byId("adminDeleteCodesBtn").onclick = async () => {
    if (!allowed() || state.deleting) return;
    if (!state.editingCodes) { setCodeEditMode(true); return; }
    if (state.selected.size === 0) return;
    const codes = state.rows.filter(code => state.selected.has(code.code)).map(code => code.code);
    if (!codes.length) return;
    const user = currentUser, deletion = ++state.deletion;
    state.deleting = true; updateCodeSelection();
    try {
      const reclaim = await askReclaim(codes.length);
      if (reclaim === null || user !== currentUser || !allowed() || deletion !== state.deletion) return;
      const response = await api("/api/admin/gift-codes", "POST", { action: "delete", codes: codes.join("\n"), reclaimRewards: reclaim ? "1" : "0" });
      if (user !== currentUser || !allowed() || deletion !== state.deletion) return;
      setCodeEditMode(false); message(`Đã xóa ${response.deletedCount} Code.${response.reclaimed ? " Đã thu hồi vật phẩm." : ""}`); await refresh();
      if (response.reclaimed) { await loadStoreFromServer(); renderCurrencyBar(); }
    } catch (error) { if (user === currentUser && deletion === state.deletion) message(error.message, true); }
    finally { if (user === currentUser && deletion === state.deletion) { state.deleting = false; updateCodeSelection(); } }
  };
  byId("adminCodeSearchForm").onsubmit = event => { event.preventDefault(); clearCodeSelection(); state.page = 1; state.search = byId("adminCodeSearch").value.trim(); refresh(); };
  byId("adminPrevCodesBtn").onclick = () => { if (state.page > 1) { clearCodeSelection(); state.page--; refresh(); } };
  byId("adminNextCodesBtn").onclick = () => { if (state.page < Math.ceil(state.total / 20)) { clearCodeSelection(); state.page++; refresh(); } };
  byId("adminQuickCodeBtn").onclick = () => {
    const input = byId("settingsNewCode");
    const text = input.value.trim().toUpperCase();
    const prefix = text === quickCode ? quickPrefix : text;
    if (!/^[A-Z0-9_-]{0,20}$/.test(prefix)) { message("Tiền tố tối đa 20 ký tự: chữ, số, - hoặc _.", true); return; }
    const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
    const values = crypto.getRandomValues(new Uint8Array(Number(byId("adminCodeLength").value)));
    quickPrefix = prefix;
    quickCode = (prefix ? `${prefix}-` : "") + Array.from(values, value => alphabet[value % alphabet.length]).join("");
    input.value = quickCode; input.focus(); input.select();
  };
  byId("adminCodeRows").onclick = async event => {
    const button = event.target.closest("button");
    if (!button || !allowed() || button.disabled) return;
    if (button.dataset.adminCopy != null) { copyText(state.rows[Number(button.dataset.adminCopy)].code); return; }
    if (button.dataset.adminToggle == null) return;
    const code = state.rows[Number(button.dataset.adminToggle)], user = currentUser;
    button.disabled = true;
    try {
      await api("/api/admin/gift-codes", "POST", { action: "set-active", code: code.code, active: code.active ? "0" : "1" });
      if (user !== currentUser || !allowed()) return;
      message(code.active ? "Đã tắt code." : "Đã kích hoạt code."); await refresh();
    } catch (error) { if (user === currentUser) message(error.message, true); }
    finally { button.disabled = false; }
  };
  root.addEventListener("focusin", event => {
    if (event.target.matches('input[inputmode="numeric"]') && event.target.value === "0") event.target.select();
  });
  bindGroupedIntegerInputs(root);
  window.adminPanel = {
    open() { if (allowed()) { showView(state.view); refresh(); } },
    refresh,
    reset() {
      state.deletion++; if (finishDeleteChoice) finishDeleteChoice(null); state.deleting = false; setCodeEditMode(false);
      state.creation++; dismissSuccessNotice(); resetCreateForm();
      state.generation++; state.rows = []; state.stats = null; state.page = 1; state.search = ""; state.view = "codes";
      byId("adminCodeRows").innerHTML = ""; byId("adminUserRows").innerHTML = "";
      updateCodeSelection();
      byId("adminTotalCodes").textContent = "—"; byId("adminActiveCodes").textContent = "—";
      byId("adminOverviewStats").innerHTML = ""; byId("adminCodeStats").innerHTML = ""; message();
    }
  };
  updateCodeSelection();
  updateClaimControls();
  updateActivationControls();
  if (getCurrentAppPageMode() === "admin" && allowed() && !root.hidden) window.adminPanel.open();
})();
