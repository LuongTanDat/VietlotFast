(() => {
  "use strict";
  const root = document.getElementById("paypalDepositSection");
  if (!root) return;
  const byId = id => document.getElementById(id);
  const escape = text => String(text ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const money = value => Number(value || 0).toLocaleString("vi-VN");
  const time = value => value ? new Date(value).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" }) : "—";
  const state = { deps: null, user: null, epoch: 0, requests: new Set(), timer: null, loading: false, busy: false, config: null, orders: [], manualOrders: [], legacyKeys: [], manualReady: false, manualBusy: false, mode: new URLSearchParams(location.search).has("payment") ? "fast" : "manual", selected: new URLSearchParams(location.search).get("payment"), url: "" };
  const status = { PENDING: "Chờ thanh toán", PAID: "Đã cộng ví", TEST_PAID: "Thử nghiệm thành công", FAILED: "Không thành công", EXPIRED: "Hết hạn", OWNER_DELETED: "Tài khoản đã xóa" };

  function active() { return state.deps && state.deps.user() && !root.hidden && !document.hidden; }
  function current(user, epoch) { return active() && state.deps.user() === user && state.epoch === epoch; }
  function stop(clear = false) {
    clearTimeout(state.timer); state.timer = null;
    if (clear && byId("depositHistoryDialog").open) byId("depositHistoryDialog").close();
    for (const request of state.requests) request.abort();
    state.requests.clear(); state.epoch++; state.loading = false; state.busy = false;
    if (clear) { state.config = null; state.orders = []; state.manualOrders = []; state.legacyKeys = []; state.manualReady = false; byId("manualDepositForm").reset(); byId("depositManualAccountId").value = ""; state.selected = null; state.url = ""; byId("depositPaymentPanel").hidden = true; byId("depositHistoryList").textContent = ""; byId("depositHistoryCount").textContent = "0 giao dịch"; state.deps?.message(""); }
    byId("depositCreateBtn").disabled = true;
    byId("depositManualSubmit").disabled = true; state.manualBusy = false;
  }
  async function request(path, form = null) {
    const controller = new AbortController(); state.requests.add(controller);
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(path, { credentials: "same-origin", cache: "no-store", signal: controller.signal, method: form ? "POST" : "GET", ...(form ? { headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" }, body: new URLSearchParams(form).toString() } : {}) });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(response.status === 401 ? "Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại." : payload.message || "Chưa kết nối được dịch vụ thanh toán.");
      return payload;
    } finally { clearTimeout(timeout); state.requests.delete(controller); }
  }
  function configure(config) {
    config = { ...config, maximum: Math.min(Number(config.maximum) || 100000000, 100000000) };
    state.config = config;
    const sandbox = config.environment === "sandbox";
    byId("depositGatewayBadge").textContent = !config.configured ? "Chưa kết nối" : sandbox ? "Môi trường thử nghiệm" : "Tự động · VNPAY";
    byId("depositGatewayNotice").textContent = !config.configured ? "Nạp nhanh chưa kết nối cổng thanh toán. Bạn có thể dùng Nạp thủ công. MoMo sẽ được mở khi có tài khoản Business và hoàn tất liên kết." : sandbox ? "Đây là môi trường thử nghiệm. Thanh toán thử không cộng vào số dư thật." : "Quét mã tại VNPAY bằng ứng dụng ngân hàng. Số dư chỉ được cộng sau khi server xác nhận thanh toán thành công.";
    byId("depositCreateBtn").disabled = !config.configured || state.busy;
    byId("depositAmountHint").textContent = "Nạp tối thiểu Từ 1.000.000 đến tối đa 100.000.000 VNĐ, Bội số 100.000 VNĐ.";
  }
  function validUrl(text) {
    try { const url = new URL(text); return url.protocol === "https:" && ((url.hostname === "sandbox.vnpayment.vn" && url.pathname === "/paymentv2/vpcpay.html") || (url.hostname === "pay.vnpay.vn" && url.pathname === "/vpcpay.html")) && !url.username && !url.password && !url.port ? url.href : ""; }
    catch { return ""; }
  }
  function renderTransferInstructions(value) {
    const host = byId("depositManualInstructions"), text = String(value || "").trim();
    const lines = text.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
    const account = (lines[1] || "").replace(/\s/g, "");
    const structured = lines.length >= 2 && lines[0].length <= 60 && /^[0-9]{8,20}$/.test(account);
    host.classList.toggle("has-bank-card", structured);
    if (!structured) { host.textContent = text || "Chưa có thông tin chuyển khoản."; return; }
    const recipient = (lines[2] || "").match(/^(?:Tên người nhận|Chủ tài khoản)\s*:\s*(.+)$/i)?.[1]?.trim() || "";
    const extra = lines.slice(recipient ? 3 : 2).join("\n");
    host.innerHTML = `<div class="deposit-bank-heading"><span class="deposit-bank-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="m3 9 9-5 9 5H3Zm2 11h14M7 12v5m5-5v5m5-5v5"/></svg></span><div><span>Ngân hàng nhận</span><strong>${escape(lines[0])}</strong></div></div><div class="deposit-bank-number"><span>Số tài khoản</span><strong data-bank-account>${escape(account)}</strong></div><div class="deposit-bank-account">${recipient ? `<div class="deposit-bank-recipient"><span>Tên người nhận</span><strong data-bank-recipient>${escape(recipient)}</strong></div>` : "<div></div>"}<button type="button" class="deposit-bank-copy" data-copy-bank-account="${escape(account)}" aria-label="Sao chép số tài khoản"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/></svg><span>Sao chép</span></button></div>${extra ? `<p class="deposit-bank-extra">${escape(extra)}</p>` : ""}`;
  }
  function renderPanel() {
    const panel = byId("depositPaymentPanel"), order = state.orders.find(item => item.id === state.selected);
    panel.hidden = !order;
    if (!order) return;
    const pending = order.status === "PENDING", link = pending ? validUrl(state.url) : "";
    panel.innerHTML = `<div class="deposit-payment-panel-head"><strong>${escape(status[order.status] || "Đang đối soát")}</strong><span>${order.environment === "sandbox" ? "Thử nghiệm" : "VNPAY"}</span></div><dl><div><dt>Số tiền</dt><dd>${money(order.amount)} VNĐ</dd></div><div><dt>${order.environment === "sandbox" ? "PayPal thử nghiệm" : "PayPal nhận"}</dt><dd>${money(order.credit)}</dd></div><div><dt>Mã đơn</dt><dd class="deposit-order-id">${escape(order.id)}</dd></div>${pending ? `<div><dt>Hạn thanh toán</dt><dd>${escape(time(order.expiresAt))}</dd></div>` : ""}</dl>${link ? `<a class="deposit-checkout-link" href="${escape(link)}" target="_blank" rel="noopener noreferrer">Mở trang quét VNPAY-QR ↗</a>` : ""}${pending ? '<p>Đang chờ xác nhận từ VNPAY. Trang sẽ tự cập nhật.</p>' : order.status === "TEST_PAID" ? '<p>Thử nghiệm đã hoàn tất; số dư thật được giữ nguyên.</p>' : ""}`;
    if (pending) panel.insertAdjacentHTML("beforeend", '<button type="button" class="deposit-payment-refresh" data-payment-refresh>↻ Kiểm tra trạng thái</button>');
  }
  function legacyKey(entry) {
    if (entry.id != null && String(entry.id)) return "id:" + String(entry.id);
    return "fields:" + JSON.stringify(["amount", "createdAt", "txnCode", "txnTime", "senderName", "email", "note"].map(key => String(entry[key] ?? "")));
  }
  function historyRow(date, type, amount, credit, label, paymentStatus, details, index, key) {
    const parts = String(date).match(/^(\d{1,2}:\d{2}(?::\d{2})?),?\s+(.+)$/);
    const dateLabel = parts ? `<span>${escape(parts[2])}</span><small>${escape(parts[1])}</small>` : `<span>${escape(date)}</span>`;
    const detailId = `depositHistoryDetail${index}`;
    return `<tbody class="deposit-history-item"><tr class="deposit-transaction-row"><td class="deposit-transaction-time">${dateLabel}</td><td><span class="deposit-method-label" data-kind="${type === "Nạp Nhanh" ? "fast" : "manual"}">${escape(type)}</span></td><td class="deposit-transaction-number">${money(amount)} <small>VNĐ</small></td><td class="deposit-transaction-number deposit-history-credit">${credit == null ? "—" : `${money(credit)} <small>PayPal</small>`}</td><td><span class="deposit-status-pill"${paymentStatus ? ` data-payment-status="${escape(paymentStatus)}"` : ""}>${escape(label)}</span></td><td class="deposit-transaction-action"><button type="button" data-history-toggle data-history-key="${escape(key)}" aria-expanded="false" aria-controls="${detailId}" aria-label="Chi tiết giao dịch ${escape(date)}">Chi tiết<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4"/></svg></button></td></tr><tr id="${detailId}" class="deposit-transaction-details" hidden><td colspan="6"><dl class="deposit-history-detail">${details}</dl></td></tr></tbody>`;
  }
  function renderHistory() {
    if (!state.deps) return;
    const migrated = new Set(state.legacyKeys);
    const legacy = (state.deps.legacy() || []).filter(entry => !migrated.has(legacyKey(entry))), host = byId("depositHistoryList");
    const expanded = new Set([...host.querySelectorAll('[data-history-toggle][aria-expanded="true"]')].map(button => button.dataset.historyKey));
    const focused = host.contains(document.activeElement) ? document.activeElement.dataset.historyKey : null, scrollLeft = host.scrollLeft;
    const orders = [...state.orders, ...state.manualOrders].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    byId("depositHistoryCount").textContent = `${orders.length} giao dịch${legacy.length ? ` · ${legacy.length} yêu cầu cũ` : ""}`;
    const rows = orders.map((order, index) => {
      const manual = order.environment === "manual", label = manual && order.status === "PENDING" ? "Chờ admin duyệt" : order.status === "REJECTED" ? "Đã từ chối" : status[order.status] || "Đang đối soát";
      const details = `<div><dt>Mã yêu cầu</dt><dd>${escape(order.id)}</dd></div><div><dt>Thưởng dự kiến</dt><dd>${money(order.bonusCredit)} PayPal</dd></div>${manual ? `${order.accountId ? `<div><dt>ID tài khoản</dt><dd>${escape(order.accountId)}</dd></div>` : ""}${order.sender ? `<div><dt>Người chuyển</dt><dd>${escape(order.sender)}</dd></div>` : ""}${order.email || order.legacyEmail ? `<div><dt>Email</dt><dd>${escape(order.email || order.legacyEmail)}</dd></div>` : ""}${order.transferMemo ? `<div><dt>Nội dung chuyển khoản</dt><dd>${escape(order.transferMemo)}</dd></div>` : ""}${order.channel ? `<div><dt>Ngân hàng / Ví</dt><dd>${escape(order.channel)}</dd></div>` : ""}${order.reference ? `<div><dt>Mã giao dịch</dt><dd>${escape(order.reference)}</dd></div>` : ""}${order.transferredAt ? `<div><dt>Thời gian chuyển</dt><dd>${escape(time(order.transferredAt))}</dd></div>` : ""}${order.note ? `<div><dt>Ghi chú</dt><dd>${escape(order.note)}</dd></div>` : ""}${order.reviewedAt ? `<div><dt>Admin xử lý</dt><dd>${escape(time(order.reviewedAt))}</dd></div><div><dt>Phản hồi</dt><dd>${escape(order.reviewNote || "Đã xác nhận")}</dd></div>` : ""}` : `<div><dt>Môi trường</dt><dd>${order.environment === "sandbox" ? "Thử nghiệm — không cộng ví thật" : "Thanh toán thật"}</dd></div><div><dt>Mã giao dịch VNPAY</dt><dd>${escape(order.transactionNo || "—")}</dd></div>`}`;
      return historyRow(time(order.createdAt), manual ? "Thủ Công" : "Nạp Nhanh", order.amount, order.credit, label, order.status, details, index, "order:" + order.id);
    }).join("") + legacy.map((entry, index) => historyRow(entry.timeText || "—", "Thủ Công", entry.amount, null, "Chưa xác minh", "", `<div><dt>Loại yêu cầu</dt><dd>Yêu cầu thủ công cũ</dd></div><div><dt>Mã giao dịch đã nhập</dt><dd>${escape(entry.txnCode || "—")}</dd></div><div><dt>Ghi chú</dt><dd>Yêu cầu cũ không được dùng để tự cộng số dư.</dd></div>`, orders.length + index, "legacy:" + legacyKey(entry))).join("");
    host.innerHTML = rows ? `<table class="deposit-transactions"><caption class="deposit-sr-only">Bảng giao dịch nạp tiền</caption><colgroup><col class="deposit-col-time"><col class="deposit-col-method"><col class="deposit-col-amount"><col class="deposit-col-credit"><col class="deposit-col-status"><col class="deposit-col-action"></colgroup><thead><tr><th scope="col">Thời gian</th><th scope="col">Loại nạp</th><th scope="col">Số tiền nạp</th><th scope="col">PayPal</th><th scope="col">Trạng thái</th><th scope="col"><span class="deposit-sr-only">Chi tiết</span></th></tr></thead>${rows}</table>` : '<div class="deposit-empty"><strong>Chưa có giao dịch nạp tiền</strong><span>Lịch sử được cập nhật sau khi gửi yêu cầu.</span></div>';
    host.querySelectorAll("[data-history-toggle]").forEach(button => {
      if (expanded.has(button.dataset.historyKey)) { button.setAttribute("aria-expanded", "true"); byId(button.getAttribute("aria-controls")).hidden = false; }
      if (focused === button.dataset.historyKey) button.focus({ preventScroll: true });
    });
    host.scrollLeft = scrollLeft;
  }
  function setMode(mode, focus = false) {
    state.mode = mode === "fast" ? "fast" : "manual";
    root.querySelectorAll("[data-deposit-mode]").forEach(button => {
      const selected = button.dataset.depositMode === state.mode;
      button.setAttribute("aria-selected", String(selected)); button.tabIndex = selected ? 0 : -1;
      if (selected && focus) button.focus();
    });
    byId("depositAmount").setAttribute("form", state.mode === "manual" ? "manualDepositForm" : "paypalDepositForm");
    byId("depositManualPane").hidden = state.mode !== "manual";
    byId("depositFastPane").hidden = state.mode !== "fast";
    root.querySelector(".deposit-checkout-actions").hidden = state.mode !== "manual";
    state.deps?.message("");
  }
  async function createManual(event) {
    event.preventDefault();
    if (!active() || state.mode !== "manual" || state.manualBusy || !state.manualReady) return;
    const form = byId("manualDepositForm");
    if (!form.reportValidity()) return;
    const amount = state.deps.amount(), user = state.deps.user(), epoch = state.epoch;
    if (!state.deps.validAmount(amount)) { state.deps.message("Chọn gói nạp hoặc nhập từ 1.000.000 đến 100.000.000 VNĐ, bội số 100.000 VNĐ.", "warn"); byId("depositAmount").focus(); return; }
    const fields = { mode: "account-id", accountId: state.deps.accountId(), amount };
    state.manualBusy = true; byId("depositManualSubmit").disabled = true; state.deps.message("Đang gửi yêu cầu…");
    try {
      const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify([user, fields])));
      const key = "manual_topup:" + [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, "0")).join("");
      let id;
      try {
        id = sessionStorage.getItem(key);
        const previous = state.manualOrders.find(order => order.id === sessionStorage.getItem(key + ":order"));
        if (previous && previous.status !== "PENDING") id = null;
      } catch { }
      if (!/^[a-f0-9]{32}$/.test(id || "")) { id = [...crypto.getRandomValues(new Uint8Array(16))].map(value => value.toString(16).padStart(2, "0")).join(""); try { sessionStorage.setItem(key, id); sessionStorage.removeItem(key + ":order"); } catch { } }
      if (!current(user, epoch)) return;
      const response = await request("/api/payments/manual", { ...fields, requestId: id });
      if (!current(user, epoch)) return;
      try { sessionStorage.setItem(key + ":order", response.order.id); } catch { }
      state.manualOrders = [response.order, ...state.manualOrders.filter(item => item.id !== response.order.id)]; renderHistory();
      void window.VietlottDepositNotifications?.refresh();
      state.deps.message(response.order.status === "PENDING" ? "Đã gửi yêu cầu đến Admin. PayPal sẽ được cộng sau khi xác nhận." : "Yêu cầu này đã được xử lý. Xem lịch sử để biết trạng thái.", "ok");
      clearTimeout(state.timer); state.timer = setTimeout(() => void refresh(), 5000);
    } catch (error) { if (current(user, epoch)) state.deps.message(error.name === "AbortError" ? "Chưa nhận được kết quả. Thử gửi lại sẽ dùng cùng mã yêu cầu." : error.message, "warn"); }
    finally { if (state.epoch === epoch) { state.manualBusy = false; byId("depositManualSubmit").disabled = !state.manualReady; } }
  }
  async function refresh() {
    if (!active() || state.loading) return;
    const user = state.deps.user();
    if (state.user !== user) { stop(true); state.user = user; state.selected = new URLSearchParams(location.search).get("payment"); }
    const epoch = state.epoch; state.loading = true; clearTimeout(state.timer);
    try {
      const [config, history, manual] = await Promise.all([request("/api/payments/vnpay/config"), request("/api/payments/vnpay/orders"), request("/api/payments/manual")]);
      if (!current(user, epoch)) return;
      configure(config); state.orders = history.orders || []; state.manualOrders = manual.orders || []; state.legacyKeys = manual.legacyKeys || []; state.manualReady = true;
      renderTransferInstructions(manual.instructions);
      byId("depositManualSubmit").disabled = state.manualBusy;
      // Both responses may have different wallet versions; the core only applies the newest.
      state.deps.wallet(history.store || {}); state.deps.wallet(manual.store || {}); renderHistory(); renderPanel();
      if ([...state.orders, ...state.manualOrders].some(order => order.status === "PENDING")) state.timer = setTimeout(() => void refresh(), 5000);
    } catch (error) {
      if (current(user, epoch)) { state.deps.message(error.name === "AbortError" ? "Kết nối quá thời gian. Hãy thử lại." : error.message, "warn"); byId("depositCreateBtn").disabled = true; state.manualReady = false; byId("depositManualSubmit").disabled = true; byId("depositGatewayNotice").textContent = "Chưa đọc được trạng thái thanh toán. Hãy tải lại trang để thử lại."; }
    } finally { if (state.epoch === epoch) state.loading = false; }
  }
  function requestId(user, amount) {
    const key = `vnpay_request:${user}:${state.config?.environment}:${amount}`;
    try { const old = JSON.parse(sessionStorage.getItem(key)); if (old && old.at > Date.now() - 900000 && /^[a-f0-9]{32}$/.test(old.id)) return old.id; } catch { }
    const bytes = crypto.getRandomValues(new Uint8Array(16)), id = [...bytes].map(byte => byte.toString(16).padStart(2, "0")).join("");
    try { sessionStorage.setItem(key, JSON.stringify({ id, at: Date.now() })); } catch { }
    return id;
  }
  async function create() {
    if (!active() || state.mode !== "fast" || state.busy || !state.config?.configured) return;
    const amount = state.deps.amount(), config = state.config, user = state.deps.user(), epoch = state.epoch;
    if (!state.deps.validAmount(amount) || amount > config.maximum) { state.deps.message(`Chọn gói nạp hoặc nhập từ 1.000.000 đến ${money(config.maximum)} VNĐ, bội số 100.000 VNĐ.`, "warn"); byId("depositAmount").focus(); return; }
    state.busy = true; byId("depositCreateBtn").disabled = true; state.deps.message("Đang tạo đơn thanh toán…");
    try {
      const response = await request("/api/payments/vnpay/orders", { amount, requestId: requestId(user, amount) });
      if (!current(user, epoch)) return;
      state.selected = response.order.id; state.url = validUrl(response.paymentUrl);
      state.orders = [response.order, ...state.orders.filter(item => item.id !== response.order.id)]; renderHistory(); renderPanel();
      if (response.paymentUrl && !state.url) throw new Error("Địa chỉ thanh toán không hợp lệ. Không mở đường dẫn này.");
      if (response.order.status === "EXPIRED" || response.order.status !== "PENDING") {
        try { sessionStorage.removeItem(`vnpay_request:${user}:${config.environment}:${amount}`); } catch { }
        state.deps.message("Đơn đã kết thúc. Bấm tiếp tục để tạo đơn mới.");
      } else state.deps.message("Đã tạo đơn. Mở trang quét VNPAY-QR để thanh toán; số dư sẽ tự cập nhật.", "ok");
      clearTimeout(state.timer); state.timer = setTimeout(() => void refresh(), 5000);
    } catch (error) { if (current(user, epoch)) state.deps.message(error.name === "AbortError" ? "Chưa nhận được kết quả. Thử lại sẽ dùng cùng mã yêu cầu để tránh tạo trùng." : error.message, "warn"); }
    finally { if (state.epoch === epoch) { state.busy = false; byId("depositCreateBtn").disabled = !state.config?.configured; } }
  }
  function sync() {
    if (root.hidden && byId("depositHistoryDialog").open) byId("depositHistoryDialog").close();
    const user = state.deps?.user();
    if (user !== state.user) { stop(true); state.user = user; state.selected = new URLSearchParams(location.search).get("payment"); }
    byId("depositManualAccountId").value = user ? state.deps.accountId() : "";
    if (active()) void refresh(); else stop(!user);
  }
  function init(deps) {
    if (state.deps) return;
    state.deps = deps;
    byId("depositHistoryList").onclick = event => {
      const button = event.target.closest("[data-history-toggle]");
      if (!button) return;
      const expanded = button.getAttribute("aria-expanded") !== "true";
      button.setAttribute("aria-expanded", String(expanded));
      byId(button.getAttribute("aria-controls")).hidden = !expanded;
    };
    const historyDialog = byId("depositHistoryDialog");
    byId("depositHistoryOpen").onclick = () => {
      if (!historyDialog.open) historyDialog.showModal();
      void refresh();
    };
    byId("depositHistoryClose").onclick = () => historyDialog.close();
    historyDialog.onclick = event => {
      if (event.target !== historyDialog) return;
      const rect = historyDialog.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) historyDialog.close();
    };
    byId("manualDepositForm").onsubmit = createManual;
    byId("depositMemoCopy").onclick = async () => {
      const memo = state.deps.accountId(), user = state.deps.user(), epoch = state.epoch;
      if (!active() || !/^[1-9][0-9]{11}$/.test(memo || "")) return;
      try {
        await navigator.clipboard.writeText(memo);
        if (!current(user, epoch)) return;
        const button = byId("depositMemoCopy");
        button.dataset.copied = "true"; button.querySelector("span").textContent = "Đã sao chép";
        setTimeout(() => { delete button.dataset.copied; button.querySelector("span").textContent = "Sao chép"; }, 1800);
      } catch { if (current(user, epoch)) state.deps.message("Chưa sao chép được. Bạn có thể chọn và sao chép nội dung chuyển khoản.", "warn"); }
    };
    byId("depositManualInstructions").onclick = async event => {
      const button = event.target.closest("[data-copy-bank-account]");
      if (!button || !active()) return;
      const account = button.dataset.copyBankAccount, user = state.deps.user(), epoch = state.epoch;
      if (!/^[0-9]{8,20}$/.test(account || "")) return;
      try {
        await navigator.clipboard.writeText(account);
        if (!current(user, epoch) || !button.isConnected) return;
        button.dataset.copied = "true"; button.setAttribute("aria-label", "Đã sao chép số tài khoản");
        button.querySelector("span").textContent = "Đã sao chép";
        setTimeout(() => { if (button.isConnected) { delete button.dataset.copied; button.setAttribute("aria-label", "Sao chép số tài khoản"); button.querySelector("span").textContent = "Sao chép"; } }, 1800);
      } catch { if (current(user, epoch)) state.deps.message("Chưa sao chép được. Bạn có thể chọn và sao chép số tài khoản.", "warn"); }
    };
    root.querySelectorAll("[data-deposit-mode]").forEach(button => {
      button.onclick = () => setMode(button.dataset.depositMode);
      button.onkeydown = event => { if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) { event.preventDefault(); setMode(event.key === "Home" ? "manual" : event.key === "End" ? "fast" : state.mode === "manual" ? "fast" : "manual", true); } };
    });
    setMode(state.mode);
    new MutationObserver(sync).observe(root, { attributes: true, attributeFilter: ["hidden"] });
    document.addEventListener("visibilitychange", sync);
    window.addEventListener("dvlf:auth-changed", sync);
    root.addEventListener("click", event => { if (event.target.closest("[data-payment-refresh]")) void refresh(); });
    sync();
  }
  window.VietlottBankTopup = Object.freeze({ init, create, refresh, renderHistory });
})();
