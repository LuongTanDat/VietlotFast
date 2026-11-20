/* Server-authoritative loyalty progress and one daily card reward. */
(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const panel = byId("vipMembershipPanel");
  if (!panel) return;
  const levelsPanel = byId("vipLevelsDetails"), levelsToggle = byId("vipLevelsToggle");
  function syncLevelsToggle() {
    const open = levelsPanel.open;
    levelsToggle.setAttribute("aria-expanded", String(open));
    levelsToggle.setAttribute("aria-label", open ? "Ẩn các cấp VIP" : "Xem các cấp VIP");
    levelsToggle.title = open ? "Ẩn các cấp VIP" : "Xem các cấp VIP";
    if (!open && !panel.hidden && !byId("vipProgressContent").hidden && levelsPanel.contains(document.activeElement)) levelsToggle.focus({ preventScroll: true });
  }
  levelsToggle.addEventListener("click", () => { levelsPanel.open = !levelsPanel.open; syncLevelsToggle(); });
  levelsPanel.addEventListener("toggle", syncLevelsToggle);
  let serial = 0, controller = null, pollTimer = null, refreshTimer = null;
  let state = null, claiming = false, claimController = null, claimGeneration = 0, authenticated = true;
  const endpoint = "/api/account/vip-daily-reward";
  const chestTemplate = byId("vipDailyClaim").querySelector(".vip-chest-icon");
  const identity = () => ({
    user: authenticated && typeof currentUser === "string" ? currentUser : "",
    id: authenticated && typeof currentAccountId === "string" ? currentAccountId : "",
  });
  function setHeaderLevel(level = null) {
    const button = byId("vipMembershipBtn"), label = byId("vipMembershipLevel");
    const rank = Number.isInteger(level) && level >= 0 && level <= 15 ? String(level) : "";
    const changed = (button.dataset.vipLevel || "") !== rank;
    label.textContent = rank ? "V" + rank : "V—";
    if (rank) button.dataset.vipLevel = rank;
    else delete button.dataset.vipLevel;
    if (changed) window.dispatchEvent(new Event("dvlf:vip-level"));
  }
  const number = (value) => {
    const [whole, fraction] = String(value).split(".");
    return BigInt(whole).toLocaleString("vi-VN") + (fraction ? "," + fraction : "");
  };
  const compact = (value) => {
    if (String(value).includes(".")) return number(value);
    const amount = BigInt(value);
    for (const [unit, suffix] of [[1000000000n, "tỷ"], [1000000n, "tr"], [1000n, "nghìn"]]) {
      if (amount >= unit && amount % (unit / 100n) === 0n) {
        const hundredths = amount * 100n / unit;
        const fraction = String(hundredths % 100n).padStart(2, "0").replace(/0+$/, "");
        return number(hundredths / 100n) + (fraction ? "," + fraction : "") + " " + suffix;
      }
    }
    return number(value);
  };
  const progressPoints = (value) => {
    const whole = BigInt(String(value).split(".")[0]);
    for (const [unit, suffix] of [[1000000000n, "tỷ"], [1000000n, "tr"]]) {
      if (whole >= unit) {
        const hundredths = (whole * 100n + unit / 2n) / unit;
        const fraction = String(hundredths % 100n).padStart(2, "0").replace(/0+$/, "");
        return number(hundredths / 100n) + (fraction ? "," + fraction : "") + " " + suffix;
      }
    }
    return number(value);
  };
  function clearProgress(message = "Đang tải tiến trình VIP…") {
    byId("vipProgressContent").hidden = true;
    byId("vipProgressStatus").hidden = false;
    byId("vipProgressStatus").textContent = message;
    byId("vipProgressRetry").hidden = true;
    byId("vipProgressLevels").replaceChildren();
    levelsPanel.open = false;
    syncLevelsToggle();
    state = null;
    byId("vipDailyClaim").disabled = true;
    byId("vipDailyClaim").classList.remove("is-claimed", "is-available");
    byId("vipDailyClaim").setAttribute("aria-busy", "false");
    byId("vipDailyStatus").textContent = "1 rương/ngày · Đặt lại 00:00 giờ Việt Nam";
    byId("vipDailyStatus").classList.remove("is-error", "is-success");
    byId("vipCurrentDailyLabel").textContent = "Hiện Tại · VIP —";
    for (const id of ["vipProgressLevel", "vipCurrentDailyAmount", "vipNextDailyAmount", "vipProgressRemaining", "vipProgressPoints", "vipProgressTarget"]) byId(id).textContent = "";
    for (const id of ["vipProgressPoints", "vipProgressTarget", "vipProgressRemaining", "vipDailyClaim"]) byId(id).removeAttribute("title");
    byId("vipDailyClaim").removeAttribute("aria-label");
    byId("vipProgressFill").style.width = "0%";
    const bar = byId("vipProgressBar");
    bar.setAttribute("aria-valuenow", "0");
    bar.removeAttribute("aria-valuetext");
    bar.removeAttribute("title");
    delete panel.dataset.vipLevel;
  }
  function cancel() {
    serial++;
    controller?.abort();
    controller = null;
    clearTimeout(refreshTimer);
    clearTimeout(pollTimer);
  }
  function validate(data, owner) {
    const integer = /^(0|[1-9][0-9]*)$/;
    const decimal = /^(0|[1-9][0-9]*)(\.[0-9]{1,5})?$/;
    if (!data?.ok || data.username !== owner.user || !owner.id || data.accountId !== owner.id
      || !integer.test(data.spentPayPal) || !decimal.test(data.points) || !decimal.test(data.remainingPoints)
      || !Number.isInteger(data.level) || data.level < 0 || data.level > 15 || data.maxLevel !== 15
      || !Number.isInteger(data.progressBasisPoints) || data.progressBasisPoints < 0 || data.progressBasisPoints > 10000
      || !["1.25", "100000"].includes(data.paypalPerPoint) || typeof data.draft !== "boolean"
      || !Array.isArray(data.thresholds) || data.thresholds.length !== 16
      || data.thresholds.some((row, i) => row.level !== i || !decimal.test(row.points))) throw new Error("Invalid VIP progress");
    if (data.level < 15 && (data.nextLevel !== data.level + 1 || !decimal.test(data.nextLevelPoints))) throw new Error("Invalid VIP target");
    const daily = data.dailyReward;
    if (!daily || typeof daily.enabled !== "boolean" || typeof daily.claimed !== "boolean"
      || !/^\d{4}-\d{2}-\d{2}$/.test(daily.day) || daily.timezone !== "Asia/Ho_Chi_Minh"
      || daily.currency !== "PayPal" || daily.destination !== "card" || daily.claimMode !== "current_level"
      || !Number.isFinite(Date.parse(daily.serverNow)) || !Number.isFinite(Date.parse(daily.nextResetAt))
      || !integer.test(daily.currentAmount) || (data.level < 15 ? !integer.test(daily.nextAmount) : daily.nextAmount !== null)
      || !Array.isArray(daily.rewards) || daily.rewards.length !== 16
      || daily.rewards.some((row, i) => row.level !== i || !integer.test(row.amount))
      || daily.currentAmount !== daily.rewards[data.level].amount
      || (data.level < 15 && daily.nextAmount !== daily.rewards[data.level + 1].amount)
      || (daily.claimed && (!daily.receipt || !integer.test(daily.receipt.amount) || daily.receipt.day !== daily.day)))
      throw new Error("Invalid daily VIP reward");
    return data;
  }
  function render(data) {
    state = data;
    setHeaderLevel(data.level);
    byId("vipPointRate").textContent = number(data.paypalPerPoint) + " PayPal đã tiêu";
    const daily = data.dailyReward;
    const maximum = data.level === 15;
    const levelTitle = byId("vipProgressLevel");
    const current = document.createElement("span");
    current.className = "vip-rank-number is-current";
    current.textContent = String(data.level);
    levelTitle.replaceChildren("VIP ", current);
    if (!maximum) {
      const arrow = document.createElement("span"), next = document.createElement("span");
      arrow.className = "vip-rank-arrow"; arrow.textContent = "→";
      next.className = "vip-rank-number is-next"; next.textContent = String(data.nextLevel);
      levelTitle.append(" ", arrow, " ", next);
    }
    byId("vipCurrentDailyLabel").textContent = `Hiện Tại · VIP ${data.level}`;
    byId("vipCurrentDailyAmount").textContent = number(daily.currentAmount);
    byId("vipNextDailyLabel").textContent = maximum ? "Cấp Sau" : `Cấp Sau · VIP ${data.nextLevel}`;
    byId("vipNextDailyAmount").textContent = maximum ? "Đã tối đa" : number(daily.nextAmount);
    byId("vipNextDailyUnit").textContent = maximum ? "VIP 15" : "PayPal / ngày";
    const claimButton = byId("vipDailyClaim");
    claimButton.disabled = claiming || daily.claimed || !daily.enabled;
    claimButton.classList.toggle("is-claimed", daily.claimed);
    claimButton.classList.toggle("is-available", !claimButton.disabled);
    claimButton.setAttribute("aria-busy", String(claiming));
    byId("vipDailyClaimLabel").textContent = claiming ? "Đang mở rương…" : daily.claimed ? "Đã Nhận" : daily.enabled ? "Mở rương thưởng ngày" : "Rương đang tạm đóng";
    byId("vipDailyClaimHint").textContent = daily.claimed
      ? `+${number(daily.receipt.amount)} PayPal vào thẻ · VIP ${daily.receipt.level}`
      : `+${number(daily.currentAmount)} PayPal vào thẻ`;
    const claimDescription = byId("vipDailyClaimLabel").textContent + " · " + byId("vipDailyClaimHint").textContent;
    claimButton.title = daily.claimed ? "Đã Nhận" : claiming ? "Đang mở rương…" : daily.enabled ? byId("vipDailyClaimHint").textContent : "Rương đang tạm đóng";
    claimButton.setAttribute("aria-label", claimDescription);
    byId("vipDailyStatus").textContent = daily.claimed ? `Đã Nhận · +${number(daily.receipt.amount)} PayPal vào thẻ` : "1 rương/ngày · Đặt lại 00:00 giờ Việt Nam";
    byId("vipDailyStatus").classList.remove("is-error");
    byId("vipDailyStatus").classList.toggle("is-success", daily.claimed);
    const percentage = (data.progressBasisPoints / 100).toLocaleString("vi-VN", { maximumFractionDigits: 2 });
    byId("vipProgressFill").style.width = data.progressBasisPoints / 100 + "%";
    byId("vipProgressBar").setAttribute("aria-valuenow", String(data.progressBasisPoints / 100));
    const target = maximum ? data.thresholds[15].points : data.nextLevelPoints;
    byId("vipProgressPoints").textContent = progressPoints(data.points);
    byId("vipProgressPoints").title = number(data.points) + " Point hiện có";
    byId("vipProgressTarget").textContent = progressPoints(target);
    byId("vipProgressTarget").title = number(target) + (maximum ? " Point · Mốc VIP 15" : ` Point · Mốc VIP ${data.nextLevel}`);
    byId("vipProgressBar").title = `${percentage}% · ${number(data.points)} / ${number(target)} Point`;
    const remaining = maximum ? "Đã đạt cấp VIP cao nhất. Point tiếp tục được tích lũy."
      : `Còn ${number(data.remainingPoints)} Point để lên VIP ${data.nextLevel}`;
    byId("vipProgressRemaining").textContent = maximum ? "VIP 15 · Đã đạt cấp cao nhất" : `Còn ${progressPoints(data.remainingPoints)} Point đến VIP ${data.nextLevel}`;
    byId("vipProgressRemaining").title = remaining;
    byId("vipProgressBar").setAttribute("aria-valuetext", remaining);
    byId("vipProgressDraft").hidden = !data.draft;
    const levels = data.thresholds.map((row) => {
      const item = document.createElement("li");
      item.dataset.vipLevel = String(row.level);
      item.classList.toggle("is-reached", row.level <= data.level);
      item.classList.toggle("is-current", row.level === data.level);
      if (row.level === data.level) item.setAttribute("aria-current", "step");
      const reward = daily.rewards[row.level];
      item.title = `VIP ${row.level}: ${number(row.points)} Point · ${number(reward.amount)} PayPal/ngày${row.level === data.level ? " · Cấp hiện tại" : " · Nhận theo cấp hiện tại"}`;
      const label = document.createElement("strong"); label.textContent = `VIP ${row.level}`;
      const chest = document.createElement("button");
      chest.type = "button"; chest.className = "vip-tier-chest";
      chest.disabled = row.level !== data.level || daily.claimed || !daily.enabled || claiming;
      chest.setAttribute("aria-label", item.title + (daily.claimed && row.level === data.level ? " · Đã nhận hôm nay" : ""));
      chest.append(chestTemplate.cloneNode(true));
      chest.addEventListener("click", claim);
      const amount = document.createElement("span"); amount.className = "vip-tier-reward"; amount.textContent = "+" + compact(reward.amount);
      const threshold = document.createElement("small"); threshold.textContent = number(row.points) + " Point";
      item.append(label, chest, amount, threshold);
      return item;
    });
    byId("vipProgressLevels").replaceChildren(...levels);
    byId("vipProgressStatus").hidden = true;
    byId("vipProgressRetry").hidden = true;
    byId("vipProgressContent").hidden = false;
    panel.dataset.vipLevel = String(data.level);
  }
  async function refresh(loading = false) {
    if (document.hidden || claiming) return;
    cancel();
    const owner = identity(), request = serial;
    if (!owner.user || !owner.id) { setHeaderLevel(); clearProgress("Đăng nhập để xem tiến trình VIP."); return; }
    if (loading && !panel.hidden) clearProgress();
    const pending = new AbortController(); controller = pending;
    const timeout = setTimeout(() => pending.abort(), 15000);
    try {
      const response = await fetch(endpoint, { credentials: "same-origin", cache: "no-store", signal: pending.signal });
      if (!response.ok) throw new Error("VIP progress unavailable");
      const data = validate(await response.json(), owner);
      if (request !== serial || identity().user !== owner.user || identity().id !== owner.id) return;
      setHeaderLevel(data.level);
      if (!panel.hidden) render(data);
    } catch (_) {
      if (request !== serial || identity().user !== owner.user || identity().id !== owner.id) return;
      setHeaderLevel();
      clearProgress("Chưa tải được tiến trình VIP. Hãy thử lại.");
      byId("vipProgressRetry").hidden = false;
    } finally {
      clearTimeout(timeout);
      if (request === serial) {
        controller = null;
        if (!document.hidden && identity().user && identity().id) {
          const interval = panel.hidden ? 60000 : 30000;
          const untilReset = state ? Date.parse(state.dailyReward.nextResetAt) - Date.parse(state.dailyReward.serverNow) : interval;
          pollTimer = setTimeout(() => refresh(), Math.max(1000, Math.min(interval, untilReset)));
        }
      }
    }
  }
  async function claim(event) {
    // Tier rendering replaces the clicked node; keep the header's outside-click
    // handler from treating that detached node as a click outside this popover.
    event?.stopPropagation();
    if (claiming || panel.hidden || !state || state.dailyReward.claimed || !state.dailyReward.enabled) return;
    const owner = identity(), day = state.dailyReward.day, generation = ++claimGeneration;
    cancel();
    claiming = true;
    render(state);
    const pending = new AbortController(); claimController = pending;
    const timeout = setTimeout(() => pending.abort(), 15000);
    let message = "", received = false;
    try {
      const response = await fetch(endpoint, {
        method: "POST", credentials: "same-origin", cache: "no-store", signal: pending.signal,
        headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ day }).toString(),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "Chưa xác nhận được rương. Hãy tải lại để kiểm tra.");
      validate(data, owner);
      if (!data.claim || data.claim.day !== day || !/^[1-9][0-9]*$/.test(data.claim.amount)) throw new Error("Biên nhận rương chưa hợp lệ. Hãy tải lại.");
      if (generation !== claimGeneration || identity().user !== owner.user || identity().id !== owner.id) return;
      received = true;
      if (!panel.hidden) render(data);
      message = `Đã Nhận · +${number(data.claim.amount)} PayPal vào thẻ${data.replayed ? " · Rương đã nhận trước đó" : ""}.`;
      window.VietlottFinancialNotifications?.refresh();
    } catch (error) {
      message = error.name === "AbortError" ? "Chưa xác nhận được kết quả. Đang kiểm tra lại rương…" : error.message;
    } finally {
      clearTimeout(timeout);
      if (generation === claimGeneration) {
        claiming = false; claimController = null;
        if (panel.hidden && identity().user === owner.user && identity().id === owner.id) void refresh();
        if (!panel.hidden && identity().user === owner.user && identity().id === owner.id) {
          // A timed-out response may already have committed. Read the immutable receipt before retrying.
          if (!received) {
            await refresh();
            if (generation === claimGeneration && identity().user === owner.user && identity().id === owner.id
              && state?.dailyReward.day === day && state.dailyReward.claimed) {
              received = true;
              message = `Đã Nhận · +${number(state.dailyReward.receipt.amount)} PayPal vào thẻ.`;
              window.VietlottFinancialNotifications?.refresh();
            }
          }
          else if (state) { render(state); pollTimer = setTimeout(() => refresh(), 30000); }
          if (generation === claimGeneration && !panel.hidden && identity().user === owner.user && identity().id === owner.id) {
            byId("vipDailyStatus").textContent = message;
            byId("vipDailyStatus").classList.toggle("is-error", !received);
            byId("vipDailyStatus").classList.toggle("is-success", received);
          }
        }
      }
    }
  }
  byId("vipDailyClaim").addEventListener("click", claim);
  new MutationObserver(() => {
    if (panel.hidden) { cancel(); clearProgress(); if (!claiming) void refresh(); }
    else void refresh(true);
  }).observe(panel, { attributes: true, attributeFilter: ["hidden"] });
  function scheduleRefresh() {
    if (document.hidden) return;
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => refresh(), 400);
  }
  const wallet = byId("paypalBalance");
  if (wallet) {
    const balanceKey = () => wallet.getAttribute("title") || wallet.textContent;
    let previousBalance = balanceKey();
    new MutationObserver(() => {
      const currentBalance = balanceKey();
      if (currentBalance === previousBalance) return;
      previousBalance = currentBalance;
      scheduleRefresh();
    }).observe(wallet, { attributes: true, attributeFilter: ["title"], childList: true, characterData: true, subtree: true });
  }
  window.addEventListener("dvlf:prediction-wallet", scheduleRefresh);
  window.addEventListener("dvlf:auth-changed", (event) => {
    authenticated = event.detail?.authenticated === true;
    claimGeneration++; claimController?.abort(); claimController = null; claiming = false;
    cancel(); setHeaderLevel(); clearProgress();
    if (event.detail?.authenticated) void refresh(!panel.hidden);
  });
  document.addEventListener("visibilitychange", () => { if (document.hidden) cancel(); else void refresh(); });
  byId("vipProgressRetry").addEventListener("click", () => refresh(true));
  if (identity().user && identity().id) void refresh(!panel.hidden);
})();
