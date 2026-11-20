/* Shared server-generated simulation; never changes financial balances or rates. */
(() => {
  "use strict";
  const el = id => document.getElementById(id), pane = el("adminExchangePane"), root = el("adminPanelSection");
  if (!pane || !root) return;
  const plot = el("exchangePlot"), svg = el("exchangeChart");
  const state = { range: "1d", mode: "line", historyPage: 0, data: null, serial: 0, controller: null, timer: null, clock: null, offset: 0, authenticated: true, cursor: 0 };
  const owner = () => ({ user: state.authenticated && typeof currentUser === "string" ? currentUser : "", id: state.authenticated && typeof currentAccountId === "string" ? currentAccountId : "" });
  const active = () => !pane.hidden && !root.hidden && !document.hidden && state.authenticated && typeof currentUserRole === "string" && currentUserRole === "admin" && !!owner().user;
  const number = value => BigInt(value).toLocaleString("vi-VN");
  const price = (value, digits) => Number(value).toLocaleString("vi-VN", { minimumFractionDigits: digits ?? (Number(value) < .01 ? 8 : 4), maximumFractionDigits: digits ?? (Number(value) < .01 ? 8 : 4) });
  const date = (value, options = {}) => new Date(value).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh", ...options });
  const sign = value => Number(value) > 0 ? "+" : "";
  function cancel() { state.serial++; state.controller?.abort(); state.controller = null; clearTimeout(state.timer); clearInterval(state.clock); }
  function clear() {
    state.data = null; state.historyPage = 0; el("exchangeHistoryPager").hidden = true; el("exchangeContent").hidden = true; el("exchangeStatus").hidden = false;
    el("exchangeStatus").textContent = "Đang tải tỉ giá…"; el("exchangeRetry").hidden = true;
    el("exchangeHistoryRows").replaceChildren(); svg.replaceChildren(); el("exchangeTooltip").hidden = true;
    el("exchangeRateValue").textContent = "—"; el("exchangeConvertResult").textContent = "—"; el("exchangeNextTick").textContent = "";
    delete pane.dataset.rateUnits; pane.removeAttribute("aria-busy");
  }
  function validate(data, identity, range) {
    const positive = value => typeof value === "string" && /^(0|[1-9][0-9]*)(\.[0-9]{1,8})?$/.test(value) && Number(value) > 0 && Number.isFinite(Number(value));
    const validBar = row => row && [row.time, row.endTime].every(x => Number.isFinite(Date.parse(x))) && [row.open, row.high, row.low, row.close].every(positive)
      && Number(row.high) >= Math.max(Number(row.open), Number(row.close)) && Number(row.low) <= Math.min(Number(row.open), Number(row.close));
    if (!data?.ok || data.owner !== identity.user || !identity.id || data.accountId !== identity.id || data.source !== "internal_simulation" || data.fixed !== false
      || data.appliesTo !== "chart_preview_only" || typeof data.enabled !== "boolean" || typeof data.stale !== "boolean" || data.intervalSeconds !== 60 || data.maxStepPercent !== "1"
      || data.baseCurrency !== "VNĐ" || data.quoteCurrency !== "PayPal" || !/^[1-9][0-9]{0,15}$/.test(data.numerator) || data.denominator !== "100000000"
      || !positive(data.rate) || !positive(data.inverseRate) || !Number.isFinite(Number(data.change)) || !Number.isFinite(Number(data.changePercent)) || Math.abs(Number(data.changePercent)) > 1 || data.range !== range
      || ![data.from, data.asOf, data.trackingStartedAt, data.simulationStartedAt, data.lastUpdateAt].every(value => Number.isFinite(Date.parse(value)))
      || Date.parse(data.from) < Date.parse(data.trackingStartedAt) || Date.parse(data.from) > Date.parse(data.asOf) || Date.parse(data.lastUpdateAt) > Date.parse(data.asOf)
      || (data.enabled && !Number.isFinite(Date.parse(data.nextUpdateAt))) || !data.ohlc || !Object.values(data.ohlc).every(positive)
      || !Array.isArray(data.bars) || !data.bars.length || data.bars.length > 362 || data.bars.some((row, index) => !validBar(row) || Date.parse(row.endTime) > Date.parse(data.asOf) || (index && Date.parse(row.endTime) < Date.parse(data.bars[index - 1].endTime)))
      || !Array.isArray(data.history) || !data.history.length || data.history.length > 50 || data.history.some(row => !positive(row.rate) || !Number.isFinite(Date.parse(row.effectiveAt)) || typeof row.change !== "string" || !/^-?(0|[1-9][0-9]*)(\.[0-9]{1,8})?$/.test(row.change) || !Number.isFinite(Number(row.changePercent)))
      || !Number.isSafeInteger(data.historyTotal) || data.historyTotal < data.history.length || data.historyTotal > 50 || data.historyLimit !== 50 || data.historyPageSize !== 5) throw new Error("Tỉ giá chưa hợp lệ. Hãy tải lại.");
    const scaled = data.rate.split("."), exact = BigInt(scaled[0]) * 100000000n + BigInt((scaled[1] || "").padEnd(8, "0"));
    if (exact !== BigInt(data.numerator) || data.bars.at(-1).close !== data.rate) throw new Error("Giá không khớp.");
    return data;
  }
  function converter() {
    if (!state.data) return;
    const input = el("exchangeConvertInput"), digits = input.value.replace(/\D/g, "").replace(/^0+(?=\d)/, "");
    const maximum = 1000000000000n, amount = digits.length > 13 ? maximum : digits ? BigInt(digits) : 0n, value = amount > maximum ? maximum : amount;
    input.value = digits ? number(value) : "";
    const cents = value * BigInt(state.data.numerator) * 100n / BigInt(state.data.denominator), fraction = String(cents % 100n).padStart(2, "0").replace(/0+$/, "");
    el("exchangeConvertResult").textContent = number(cents / 100n) + (fraction ? "," + fraction : "");
  }
  function node(tag, attributes = {}, text) {
    const item = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attributes).forEach(([key, value]) => item.setAttribute(key, String(value)));
    if (text !== undefined) item.textContent = text;
    return item;
  }
  let geometry = null, cursorLine = null, cursorDot = null;
  function cursor(index, show = true) {
    if (!geometry || !state.data) return;
    const bars = state.data.bars; state.cursor = Math.max(0, Math.min(bars.length - 1, index));
    const row = bars[state.cursor], x = geometry.x(Date.parse(row.endTime)), y = geometry.y(Number(row.close));
    cursorLine.setAttribute("x1", x); cursorLine.setAttribute("x2", x); cursorLine.style.display = show ? "" : "none";
    cursorDot.setAttribute("cx", x); cursorDot.setAttribute("cy", y); cursorDot.style.display = show ? "" : "none";
    const tooltip = el("exchangeTooltip"); tooltip.hidden = !show;
    tooltip.textContent = `${date(row.endTime)} · ${price(row.close)} PayPal / VNĐ`;
    tooltip.style.left = Math.max(8, Math.min(plot.clientWidth - Math.min(tooltip.offsetWidth, plot.clientWidth - 16) - 8, x + 10)) + "px";
    tooltip.style.top = Math.max(8, y - 45) + "px";
    plot.setAttribute("aria-label", `Biểu đồ PayPal, tối đa ±1% mỗi phút. ${show ? tooltip.textContent : "Dùng phím mũi tên để xem các mốc giá."}`);
  }
  function draw() {
    if (!state.data || !active() || plot.clientWidth < 1) return;
    const data = state.data, bars = data.bars, width = Math.max(240, plot.clientWidth), height = plot.clientHeight || 320;
    const left = 16, right = width - 82, top = 44, bottom = height - 36, start = Date.parse(data.from), end = Date.parse(data.asOf), duration = Math.max(1, end - start);
    const low = Number(data.ohlc.low), high = Number(data.ohlc.high), padding = Math.max((high - low) * .15, high * .001, .00000001);
    const min = Math.max(0, low - padding), max = high + padding;
    const x = time => left + Math.max(0, Math.min(1, (time - start) / duration)) * (right - left), y = value => bottom - (value - min) / (max - min) * (bottom - top);
    geometry = { left, right, start, end, x, y };
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`); svg.replaceChildren();
    const defs = node("defs"), gradient = node("linearGradient", { id: "exchangeAreaGradient", x1: 0, y1: 0, x2: 0, y2: 1 });
    gradient.append(node("stop", { offset: "0%", "stop-color": "var(--exchange-accent)", "stop-opacity": ".16" }), node("stop", { offset: "100%", "stop-color": "var(--exchange-accent)", "stop-opacity": "0" })); defs.append(gradient); svg.append(defs);
    for (let i = 0; i <= 4; i++) {
      const at = top + (bottom - top) * i / 4, value = max - (max - min) * i / 4;
      svg.append(node("line", { x1: left, x2: right, y1: at, y2: at, class: "exchange-grid" }), node("text", { x: right + 8, y: at + 3, class: "exchange-axis" }, price(value)));
    }
    for (let i = 0; i <= 3; i++) {
      const at = left + (right - left) * i / 3, value = start + duration * i / 3;
      const options = duration < 86400000 ? { hour: "2-digit", minute: "2-digit", ...(duration < 900000 ? { second: "2-digit" } : {}) } : { day: "2-digit", month: "2-digit" };
      svg.append(node("line", { x1: at, x2: at, y1: top, y2: bottom, class: "exchange-grid" }), node("text", { x: at, y: bottom + 23, "text-anchor": i === 0 ? "start" : i === 3 ? "end" : "middle", class: "exchange-axis" }, date(value, options)));
    }
    if (state.mode === "line") {
      let path = `M${left},${y(Number(bars[0].open))}`;
      bars.forEach(row => { path += `L${x(Date.parse(row.endTime))},${y(Number(row.close))}`; }); path += `H${right}`;
      svg.append(node("path", { d: path + `V${bottom}H${left}Z`, fill: "url(#exchangeAreaGradient)" }), node("path", { d: path, fill: "none", class: "exchange-price-line" }));
    } else {
      const bodyWidth = Math.max(1, Math.min(10, (right - left) * data.bucketMinutes * 60000 / duration * .65));
      bars.forEach(row => {
        const at = x(Date.parse(row.endTime)), open = y(Number(row.open)), close = y(Number(row.close)), direction = Number(row.close) >= Number(row.open) ? "is-up" : "is-down";
        svg.append(node("line", { x1: at, x2: at, y1: y(Number(row.high)), y2: y(Number(row.low)), class: "exchange-candle-wick " + direction }), node("rect", { x: at - bodyWidth / 2, y: Math.min(open, close), width: bodyWidth, height: Math.max(1.5, Math.abs(close - open)), rx: .6, class: "exchange-candle " + direction }));
      });
    }
    const currentY = y(Number(data.rate));
    svg.append(node("line", { x1: left, x2: right, y1: currentY, y2: currentY, class: "exchange-current-guide" }), node("rect", { x: right + 3, y: currentY - 10, width: 74, height: 20, rx: 4, class: "exchange-price-tag" }), node("text", { x: right + 40, y: currentY + 3.5, "text-anchor": "middle", class: "exchange-price-tag-text" }, price(data.rate)));
    cursorLine = node("line", { x1: right, x2: right, y1: top, y2: bottom, class: "exchange-crosshair", style: "display:none" }); cursorDot = node("circle", { cx: right, cy: currentY, r: 4, class: "exchange-cursor-dot", style: "display:none" });
    svg.append(cursorLine, cursorDot); el("exchangeTooltip").hidden = true;
    if (document.activeElement === plot) cursor(state.cursor);
  }
  function countdown() {
    if (!state.data || !active()) return;
    const seconds = Math.max(0, Math.ceil((Date.parse(state.data.nextUpdateAt) - Date.now() - state.offset) / 1000));
    el("exchangeNextTick").textContent = !state.data.enabled ? "Đang Tạm Ngừng" : seconds ? `Đổi giá sau ${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}` : "Đang cập nhật giá…";
  }
  function renderHistory(data = state.data) {
    if (!data) return;
    const pages = Math.max(1, Math.ceil(data.history.length / 5));
    state.historyPage = Math.max(0, Math.min(pages - 1, state.historyPage));
    const first = state.historyPage * 5, last = Math.min(first + 5, data.history.length);
    el("exchangeHistoryCount").textContent = `${first + 1}–${last} / ${number(data.historyTotal)} mốc ghi nhận`;
    const rows = data.history.slice(first, last).map(item => {
      const row = document.createElement("tr");
      const delta = sign(item.change) + price(item.change, 8).replace(/0+$/, "").replace(/,$/, "");
      for (const [i, value] of [date(item.effectiveAt), price(item.rate) + " PayPal", delta, sign(item.changePercent) + price(item.changePercent, 2) + "%", item.label].entries()) {
        const cell = document.createElement("td"); cell.textContent = value;
        if (i === 2 || i === 3) cell.className = Number(item.change) < 0 ? "is-down" : Number(item.change) > 0 ? "is-up" : "";
        if (i === 2) cell.title = delta + " PayPal so với mốc trước";
        row.append(cell);
      }
      return row;
    }); el("exchangeHistoryRows").replaceChildren(...rows);
    el("exchangeHistoryNote").textContent = "Dữ Liệu 50 mốc gần nhất.";
    el("exchangeHistoryPager").hidden = pages <= 1;
    el("exchangeHistoryPageInfo").textContent = `Trang ${state.historyPage + 1} / ${pages}`;
    el("exchangeHistoryPrevious").disabled = state.historyPage === 0;
    el("exchangeHistoryNext").disabled = state.historyPage >= pages - 1;
  }
  function render(data) {
    state.data = data; state.offset = Date.parse(data.asOf) - Date.now(); pane.dataset.rateUnits = data.numerator;
    el("exchangeRateValue").textContent = price(data.rate);
    el("exchangeChange").textContent = `${sign(data.change)}${price(data.change, 4)} (${sign(data.changePercent)}${price(data.changePercent, 2)}%)`;
    el("exchangeChange").title = "So với mốc giá liền trước";
    el("exchangeChange").classList.toggle("is-up", Number(data.change) > 0); el("exchangeChange").classList.toggle("is-down", Number(data.change) < 0);
    el("exchangeMarketBadge").querySelector("span").textContent = !data.enabled ? "Đang Tạm Ngừng" : data.stale ? "Đang chờ cập nhật" : "Chốt Tỉ Giá Sau · 00h00 Hàng Ngày";
    el("exchangeActive").textContent = !data.enabled ? "Đang Tạm Ngừng" : data.stale ? "Chờ cập nhật" : "Đang Hoạt Động";
    el("exchangeInfoRate").textContent = price(data.rate, 8).replace(/0+$/, "").replace(/,$/, "") + " PayPal";
    el("exchangeInfoInverse").textContent = price(data.inverseRate, 8).replace(/0+$/, "").replace(/,$/, "") + " VNĐ";
    for (const [id, key] of [["exchangeOpen", "open"], ["exchangeHigh", "high"], ["exchangeLow", "low"], ["exchangeClose", "close"]]) el(id).textContent = price(data.ohlc[key]);
    const shortRange = data.range.endsWith("min") || data.range.endsWith("h");
    const periodFormat = shortRange ? { hour: "2-digit", minute: "2-digit", ...(data.range === "1min" ? { second: "2-digit" } : {}) } : { day: "2-digit", month: "2-digit", year: "numeric" };
    el("exchangeChartPeriod").textContent = `${date(data.from, periodFormat)} → ${date(data.asOf, periodFormat)}`;
    el("exchangeChartPeriod").title = `${date(data.from)} → ${date(data.asOf)}`;
    el("exchangeUpdatedAt").textContent = "Giá cập nhật lúc " + date(data.lastUpdateAt);
    renderHistory(data);
    pane.querySelectorAll("[data-exchange-range]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.exchangeRange === data.range)));
    el("exchangeStatus").hidden = true; el("exchangeRetry").hidden = true; el("exchangeContent").hidden = false;
    converter(); draw(); countdown(); clearInterval(state.clock); state.clock = setInterval(countdown, 1000);
  }
  async function refresh(loading = false) {
    if (!active()) return;
    cancel(); const identity = owner(), serial = state.serial, range = state.range;
    if (!identity.id) { clear(); el("exchangeStatus").textContent = "Đăng nhập lại để xem tỉ giá."; return; }
    if (loading) { el("exchangeContent").hidden = true; el("exchangeStatus").hidden = false; el("exchangeStatus").textContent = "Đang tải tỉ giá…"; }
    pane.setAttribute("aria-busy", "true"); el("exchangeRefresh").disabled = true;
    const controller = new AbortController(); state.controller = controller; const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch("/api/admin/exchange-rate?range=" + encodeURIComponent(range), { credentials: "same-origin", cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error("Chưa tải được tỉ giá.");
      const data = validate(await response.json(), identity, range);
      if (serial !== state.serial || !active() || owner().id !== identity.id || owner().user !== identity.user) return;
      render(data);
    } catch (_) {
      if (serial !== state.serial || !active()) return;
      clear(); el("exchangeStatus").textContent = "Chưa tải được tỉ giá. Hãy thử lại."; el("exchangeRetry").hidden = false;
    } finally {
      clearTimeout(timeout);
      if (serial === state.serial) {
        state.controller = null; pane.removeAttribute("aria-busy"); el("exchangeRefresh").disabled = false;
        if (active()) {
          const due = state.data?.enabled ? Date.parse(state.data.nextUpdateAt) - Date.parse(state.data.asOf) + 1200 : 60000;
          state.timer = setTimeout(() => refresh(), Math.max(1000, Math.min(60000, due)));
        }
      }
    }
  }
  el("exchangeHistoryPrevious").addEventListener("click", () => { state.historyPage--; renderHistory(); });
  el("exchangeHistoryNext").addEventListener("click", () => { state.historyPage++; renderHistory(); });
  pane.querySelectorAll("[data-exchange-range]").forEach(button => button.addEventListener("click", () => { state.range = button.dataset.exchangeRange; void refresh(true); }));
  pane.querySelectorAll("[data-exchange-mode]").forEach(button => button.addEventListener("click", () => { state.mode = button.dataset.exchangeMode; pane.querySelectorAll("[data-exchange-mode]").forEach(item => item.setAttribute("aria-pressed", String(item === button))); draw(); }));
  el("exchangeConvertInput").addEventListener("input", converter); el("exchangeRefresh").addEventListener("click", () => refresh()); el("exchangeRetry").addEventListener("click", () => refresh(true));
  plot.addEventListener("pointermove", event => {
    if (!geometry || !state.data) return;
    const fraction = Math.max(0, Math.min(1, (event.clientX - plot.getBoundingClientRect().left - geometry.left) / (geometry.right - geometry.left))), at = geometry.start + (geometry.end - geometry.start) * fraction;
    let best = 0; state.data.bars.forEach((bar, index) => { if (Math.abs(Date.parse(bar.endTime) - at) < Math.abs(Date.parse(state.data.bars[best].endTime) - at)) best = index; }); cursor(best);
  });
  plot.addEventListener("pointerleave", () => cursor(state.cursor, false)); plot.addEventListener("focus", () => cursor((state.data?.bars.length || 1) - 1)); plot.addEventListener("blur", () => cursor(state.cursor, false));
  plot.addEventListener("keydown", event => { if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return; event.preventDefault(); cursor(event.key === "Home" ? 0 : event.key === "End" ? (state.data?.bars.length || 1) - 1 : state.cursor + (event.key === "ArrowLeft" ? -1 : 1)); });
  let resizeFrame = 0, lastWidth = 0;
  new ResizeObserver(entries => { const width = entries[0].contentRect.width; if (width === lastWidth) return; lastWidth = width; cancelAnimationFrame(resizeFrame); resizeFrame = requestAnimationFrame(draw); }).observe(plot);
  const observer = new MutationObserver(() => { if (active()) void refresh(true); else cancel(); }); observer.observe(root, { attributes: true, attributeFilter: ["hidden"] }); observer.observe(pane, { attributes: true, attributeFilter: ["hidden"] });
  document.addEventListener("visibilitychange", () => { if (active()) void refresh(); else cancel(); });
  window.addEventListener("dvlf:auth-changed", event => { state.authenticated = event.detail?.authenticated === true; cancel(); clear(); if (active()) void refresh(true); });
  if (active()) void refresh(true);
})();
