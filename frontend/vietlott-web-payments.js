(() => {
  "use strict";
  const root = document.getElementById("paypalDepositSection");
  if (!root) return;
  const byId = id => document.getElementById(id);
  const escape = text => String(text ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const money = value => Number(value || 0).toLocaleString("vi-VN");
  const time = value => value ? new Date(value).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" }) : "—";
  const state = { deps: null, user: null, epoch: 0, requests: new Set(), timer: null, loading: false, busy: false, config: null, orders: [], selected: new URLSearchParams(location.search).get("payment"), url: "" };
  const status = { PENDING: "Chờ thanh toán", PAID: "Đã cộng ví", TEST_PAID: "Thử nghiệm thành công", FAILED: "Không thành công", EXPIRED: "Hết hạn", OWNER_DELETED: "Tài khoản đã xóa" };

  function active() { return state.deps && state.deps.user() && !root.hidden && !document.hidden; }
  function current(user, epoch) { return active() && state.deps.user() === user && state.epoch === epoch; }
  function stop(clear = false) {
    clearTimeout(state.timer); state.timer = null;
    for (const request of state.requests) request.abort();
    state.requests.clear(); state.epoch++; state.loading = false; state.busy = false;
    if (clear) { state.config = null; state.orders = []; state.selected = null; state.url = ""; byId("depositPaymentPanel").hidden = true; byId("depositHistoryList").textContent = ""; byId("depositHistoryCount").textContent = "0 giao dịch"; state.deps?.message(""); }
    byId("depositCreateBtn").disabled = true;
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
    state.config = config;
    const sandbox = config.environment === "sandbox";
    byId("depositGatewayBadge").textContent = !config.configured ? "Chưa kết nối" : sandbox ? "Môi trường thử nghiệm" : "Tự động · VNPAY";
    byId("depositGatewayNotice").textContent = !config.configured ? "VNPAY chưa được cấu hình. Quản trị viên cần kết nối tài khoản VNPAY để mở thanh toán." : sandbox ? "Đây là môi trường thử nghiệm. Thanh toán thử không cộng vào số dư thật." : "Quét mã tại VNPAY bằng ứng dụng ngân hàng. Số dư chỉ được cộng sau khi server xác nhận thanh toán thành công.";
    byId("depositCreateBtn").disabled = !config.configured || state.busy;
    byId("depositAmountHint").textContent = `Từ ${money(config.minimum)} đến ${money(config.maximum)} VNĐ, bội số ${money(config.step)} VNĐ.`;
  }
  function validUrl(text) {
    try { const url = new URL(text); return url.protocol === "https:" && ((url.hostname === "sandbox.vnpayment.vn" && url.pathname === "/paymentv2/vpcpay.html") || (url.hostname === "pay.vnpay.vn" && url.pathname === "/vpcpay.html")) && !url.username && !url.password && !url.port ? url.href : ""; }
    catch { return ""; }
  }
  function renderPanel() {
    const panel = byId("depositPaymentPanel"), order = state.orders.find(item => item.id === state.selected);
    panel.hidden = !order;
    if (!order) return;
    const pending = order.status === "PENDING", link = pending ? validUrl(state.url) : "";
    panel.innerHTML = `<div class="deposit-payment-panel-head"><strong>${escape(status[order.status] || "Đang đối soát")}</strong><span>${order.environment === "sandbox" ? "Thử nghiệm" : "VNPAY"}</span></div><dl><div><dt>Số tiền</dt><dd>${money(order.amount)} VNĐ</dd></div><div><dt>${order.environment === "sandbox" ? "PayPal thử nghiệm" : "PayPal nhận"}</dt><dd>${money(order.credit)}</dd></div><div><dt>Mã đơn</dt><dd class="deposit-order-id">${escape(order.id)}</dd></div>${pending ? `<div><dt>Hạn thanh toán</dt><dd>${escape(time(order.expiresAt))}</dd></div>` : ""}</dl>${link ? `<a class="deposit-checkout-link" href="${escape(link)}" target="_blank" rel="noopener noreferrer">Mở trang quét VNPAY-QR ↗</a>` : ""}${pending ? '<p>Đang chờ xác nhận từ VNPAY. Trang sẽ tự cập nhật.</p>' : order.status === "TEST_PAID" ? '<p>Thử nghiệm đã hoàn tất; số dư thật được giữ nguyên.</p>' : ""}`;
    if (pending) panel.insertAdjacentHTML("beforeend", '<button type="button" class="deposit-payment-refresh" data-payment-refresh>↻ Kiểm tra trạng thái</button>');
  }
  function renderHistory() {
    const legacy = state.deps.legacy() || [], host = byId("depositHistoryList");
    byId("depositHistoryCount").textContent = `${state.orders.length} giao dịch${legacy.length ? ` · ${legacy.length} yêu cầu cũ` : ""}`;
    host.innerHTML = state.orders.map(order => `<details class="deposit-history-item"><summary><span class="deposit-history-amount"><strong>${money(order.amount)} VNĐ</strong><small>${escape(time(order.createdAt))}</small></span><span class="deposit-history-credit">${money(order.credit)} PayPal</span><span class="deposit-status-pill" data-payment-status="${escape(order.status)}">${escape(status[order.status] || "Đang đối soát")}</span><span class="deposit-history-chevron" aria-hidden="true">⌄</span></summary><dl class="deposit-history-detail"><div><dt>Mã đơn</dt><dd>${escape(order.id)}</dd></div><div><dt>Môi trường</dt><dd>${order.environment === "sandbox" ? "Thử nghiệm — không cộng ví thật" : "Thanh toán thật"}</dd></div><div><dt>Thưởng dự kiến</dt><dd>${money(order.bonusCredit)} PayPal</dd></div><div><dt>Mã giao dịch VNPAY</dt><dd>${escape(order.transactionNo || "—")}</dd></div></dl></details>`).join("") + legacy.map(entry => `<details class="deposit-history-item"><summary><span class="deposit-history-amount"><strong>${money(entry.amount)} VNĐ</strong><small>${escape(entry.timeText || "")}</small></span><span class="deposit-history-credit">Yêu cầu thủ công cũ</span><span class="deposit-status-pill">Chưa xác minh</span><span class="deposit-history-chevron" aria-hidden="true">⌄</span></summary><dl class="deposit-history-detail"><div><dt>Mã giao dịch đã nhập</dt><dd>${escape(entry.txnCode || "—")}</dd></div><div><dt>Ghi chú</dt><dd>Yêu cầu cũ không được dùng để tự cộng số dư.</dd></div></dl></details>`).join("");
    if (!state.orders.length && !legacy.length) host.innerHTML = '<div class="deposit-empty"><strong>Chưa có giao dịch nạp tiền</strong><span>Lịch sử được cập nhật tự động sau khi tạo đơn.</span></div>';
  }
  async function refresh() {
    if (!active() || state.loading) return;
    const user = state.deps.user();
    if (state.user !== user) { stop(true); state.user = user; state.selected = new URLSearchParams(location.search).get("payment"); }
    const epoch = state.epoch; state.loading = true; clearTimeout(state.timer);
    try {
      const [config, history] = await Promise.all([request("/api/payments/vnpay/config"), request("/api/payments/vnpay/orders")]);
      if (!current(user, epoch)) return;
      configure(config); state.orders = history.orders || []; state.deps.wallet(history.store || {}); renderHistory(); renderPanel();
      if (state.orders.some(order => order.status === "PENDING")) state.timer = setTimeout(() => void refresh(), 5000);
    } catch (error) {
      if (current(user, epoch)) { state.deps.message(error.name === "AbortError" ? "Kết nối quá thời gian. Hãy thử lại." : error.message, "warn"); byId("depositCreateBtn").disabled = true; byId("depositGatewayNotice").textContent = "Chưa đọc được trạng thái thanh toán. Hãy tải lại trang để thử lại."; }
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
    if (!active() || state.busy || !state.config?.configured) return;
    const amount = state.deps.amount(), config = state.config, user = state.deps.user(), epoch = state.epoch;
    if (!Number.isSafeInteger(amount) || amount < config.minimum || amount > config.maximum || amount % config.step) { state.deps.message(`Nhập từ ${money(config.minimum)} đến ${money(config.maximum)} VNĐ, bội số ${money(config.step)} VNĐ.`, "warn"); byId("depositAmount").focus(); return; }
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
    const user = state.deps?.user();
    if (user !== state.user) { stop(true); state.user = user; state.selected = new URLSearchParams(location.search).get("payment"); }
    if (active()) void refresh(); else stop(!user);
  }
  function init(deps) {
    if (state.deps) return;
    state.deps = deps;
    new MutationObserver(sync).observe(root, { attributes: true, attributeFilter: ["hidden"] });
    document.addEventListener("visibilitychange", sync);
    window.addEventListener("dvlf:auth-changed", sync);
    root.addEventListener("click", event => { if (event.target.closest("[data-payment-refresh]")) void refresh(); });
    sync();
  }
  window.VietlottBankTopup = Object.freeze({ init, create, refresh });
})();
