(() => {
  "use strict";
  const root = document.getElementById("adminPanelSection");
  const byId = id => document.getElementById(id);
  const state = { view: "codes", tab: "create", page: 1, total: 0, rows: [], stats: null, generation: 0, creation: 0, search: "", selected: new Set(), editingCodes: false, deleting: false, deletion: 0 };
  const labels = { promotion: "Khuyến mãi", vip: "VIP", gift: "Quà tặng" };
  let quickCode = "", quickPrefix = "", finishSuccessNotice = null, finishDeleteChoice = null;
  const titles = {
    deposits: ["Duyệt nạp tiền", "Kiểm tra giao dịch và xác nhận cộng PayPal"],
    codes: ["Quản lý Code", "Tạo và quản lý mã trên hệ thống"],
    overview: ["Tổng quan", "Thông tin quản trị từ dữ liệu hệ thống"],
    users: ["Quản Lý Use", "Theo dõi tài khoản và trạng thái truy cập"],
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
  let adminUsers = [], usersGeneration = 0, usersTimer = null;
  let usersEditing = false, usersSaving = false, usersLoading = false, usersEditGeneration = 0;
  const userDrafts = new Map();
  function userEditMessage(text="",error=false){const node=byId("adminUsersEditMessage");node.textContent=text;node.hidden=!text;node.classList.toggle("is-error",error);}
  function captureUserDrafts(){
    if(!usersEditing)return;
    byId("adminUserRows").querySelectorAll("input[data-user-balance]").forEach(input=>{
      const draft=userDrafts.get(input.dataset.accountId);if(draft)draft[input.dataset.userBalance]=input.value;
    });
  }
  function updateUserEditControls(){
    root.querySelector(".admin-users-card").classList.toggle("is-editing-balances",usersEditing);
    const button=byId("adminUsersEdit");button.textContent=usersSaving?"Đang lưu…":usersEditing?"Lưu":"Chỉnh Sửa";
    button.disabled=usersSaving||usersLoading||!adminUsers.length;button.setAttribute("aria-pressed",String(usersEditing));
    byId("adminUsersEditCancel").hidden=!usersEditing;byId("adminUsersEditCancel").disabled=usersSaving;
    byId("adminUsersRefresh").disabled=usersEditing;
    byId("adminUsersFilters").querySelectorAll("select,button").forEach(node=>node.disabled=usersSaving||(node.id==="adminUsersFilterClear"&&!userFilterIds.some(id=>byId(id).value)));
    byId("adminUserSearch").disabled=usersSaving;
  }
  function endUserEdit(){
    usersEditGeneration++;usersEditing=false;usersSaving=false;userDrafts.clear();updateUserEditControls();
  }
  function userBalanceCell(info,key,label){
    const amount=info[key+"Balance"],draft=userDrafts.get(info.accountId);
    return `<td class="admin-user-balance" title="${formatLuckyWheelAmount(amount)}">${usersEditing&&draft?`<input type="text" inputmode="numeric" autocomplete="off" spellcheck="false" data-grouped-integer data-user-balance="${key}" data-account-id="${escapeHtml(info.accountId)}" aria-label="${label} của ${escapeHtml(info.username)}" value="${escapeHtml(draft[key])}"${usersSaving?" disabled":""}>`:formatCompactBalance(amount)}</td>`;
  }
  async function saveUserBalances(){
    if(!allowed()||!usersEditing||usersSaving)return;
    captureUserDrafts();const changes=[];
    try{
      for(const [accountId,draft] of userDrafts){
        const info=draft.info;
        const diamond=draft.diamond===formatLuckyWheelAmount(info.diamondBalance)?info.diamondBalance:parseAccountBalance(draft.diamond,"Kim cương của "+info.username);
        const paypal=draft.paypal===formatLuckyWheelAmount(info.paypalBalance)?info.paypalBalance:parseAccountBalance(draft.paypal,"PayPal của "+info.username);
        if(diamond!==info.diamondBalance||paypal!==info.paypalBalance)changes.push({accountId,draft,diamond,paypal});
      }
    }catch(error){userEditMessage(error.message,true);return;}
    if(!changes.length){endUserEdit();renderUsers();userEditMessage("Không có thay đổi cần lưu.");void loadUsers();return;}
    const owner=currentUser,identity=currentAccountId,generation=usersEditGeneration;
    const valid=()=>allowed()&&currentUser===owner&&currentAccountId===identity&&generation===usersEditGeneration;
    usersSaving=true;updateUserEditControls();renderUsers();userEditMessage("Đang lưu số dư…");
    let saved=0,ownWalletChanged=false;const errors=[];
    for(const change of changes){
      if(!valid())return;
      const {accountId,draft,diamond,paypal}=change,info=draft.info;
      try{
        await api("/api/admin/update-assets","POST",{accountId,username:info.username,diamond,paypal,expectedDiamond:info.diamondBalance,expectedPaypal:info.paypalBalance});
        if(!valid())return;
        info.diamondBalance=diamond;info.paypalBalance=paypal;draft.diamond=formatLuckyWheelAmount(diamond);draft.paypal=formatLuckyWheelAmount(paypal);saved++;
        if(accountId===identity)ownWalletChanged=true;
      }catch(error){if(!valid())return;errors.push(`${info.username}: ${error.message}`);}
    }
    if(ownWalletChanged){try{await loadStoreFromServer();renderCurrencyBar();}catch(error){if(valid())errors.push(error.message);}}
    if(!valid())return;
    usersSaving=false;
    if(!errors.length)endUserEdit();else updateUserEditControls();
    renderUsers();userEditMessage(errors.length?`Đã lưu ${saved} tài khoản. ${errors.join(" · ")}`:`Đã lưu số dư của ${saved} tài khoản.`,!!errors.length);
    if(!usersEditing)void loadUsers();
  }
  const userFilterIds=["adminUserRoleFilter","adminUserVipFilter","adminUserAccessFilter","adminUserDeviceFilter","adminUserBrowserFilter"];
  function userVipStatus(info){return info.vipActive?"active":Number.isFinite(Date.parse(info.vipExpiresAt||""))?"expired":"none";}
  function updateUserFilterOptions(){
    for(const [id,key,label] of [["adminUserDeviceFilter","device","Tất cả thiết bị"],["adminUserBrowserFilter","browser","Tất cả trình duyệt"]]){
      const select=byId(id),selected=select.value,values=new Set(adminUsers.map(info=>info[key]||"Chưa ghi nhận"));
      if(selected)values.add(selected);
      select.replaceChildren(new Option(label,""),...[...values].sort((a,b)=>a.localeCompare(b,"vi")).map(value=>new Option(value,value)));
      select.value=selected;
    }
  }
  function toggleUserFilters(open){byId("adminUsersFilters").hidden=!open;byId("adminUsersFilterToggle").setAttribute("aria-expanded",String(open));}
  function resetUserFilters(){userFilterIds.forEach(id=>byId(id).value="");}
  const accessLabels = { active:"Đang Hoạt Động", idle:"Đang Treo Máy", offline:"Đang offline" };
  function usersActive() { return allowed() && !root.hidden && state.view === "users" && !document.hidden; }
  function userVipCell(info) {
    const admin=info.role==="admin",expiry=Date.parse(info.vipExpiresAt||"");
    const label=info.vipActive?"VIP":Number.isFinite(expiry)?"Hết hạn":"Chưa có";
    const date=Number.isFinite(expiry)?new Date(expiry).toLocaleDateString("vi-VN",{timeZone:"Asia/Ho_Chi_Minh"}):"";
    const detail=admin?"Quyền quản trị":date;
    const title=admin?"VIP theo quyền quản trị":Number.isFinite(expiry)?`Hạn VIP: ${new Date(expiry).toLocaleString("vi-VN",{timeZone:"Asia/Ho_Chi_Minh"})}`:"Chưa có quyền VIP";
    return `<td class="admin-user-vip" title="${escapeHtml(title)}"><span class="admin-user-vip-badge${info.vipActive?" is-active":""}">${label}</span>${detail?`<small>${escapeHtml(detail)}</small>`:""}</td>`;
  }
  function renderUsers() {
    captureUserDrafts();
    const query = byId("adminUserSearch").value.trim().toLowerCase();
    const [role,vip,access,device,browser]=userFilterIds.map(id=>byId(id).value);
    const rows = adminUsers.filter(info => `${info.username} ${info.accountId || ""} ${info.networkAddress || ""} ${info.device || ""} ${info.browser || ""}`.toLowerCase().includes(query)
      &&(!role||(info.role==="admin"?"admin":"user")===role)&&(!vip||userVipStatus(info)===vip)&&(!access||info.accessStatus===access)&&(!device||(info.device||"Chưa ghi nhận")===device)&&(!browser||(info.browser||"Chưa ghi nhận")===browser));
    const filterCount=userFilterIds.filter(id=>byId(id).value).length;
    byId("adminUsersFilterBadge").hidden=!filterCount;byId("adminUsersFilterBadge").textContent=String(filterCount);
    byId("adminUsersFilterToggle").classList.toggle("has-filters",!!filterCount);
    byId("adminUsersFilterClear").disabled=!filterCount;
    byId("adminUsersFilterResult").textContent=`Hiển thị ${rows.length} / ${adminUsers.length} tài khoản`;
    byId("adminUsersCount").textContent = `${rows.length} / ${adminUsers.length} tài khoản`;
    byId("adminUsersMetrics").innerHTML = [["Tổng tài khoản",adminUsers.length,"all"],["Đang hoạt động",adminUsers.filter(i=>i.accessStatus==="active").length,"active"],["Đang treo máy",adminUsers.filter(i=>i.accessStatus==="idle").length,"idle"],["Đang offline",adminUsers.filter(i=>i.accessStatus==="offline").length,"offline"]].map(([label,count,status])=>`<article data-status="${status}"><span>${label}</span><strong>${formatLuckyWheelAmount(count)}</strong></article>`).join("");
    byId("adminUserRows").innerHTML = rows.map(info => {
      const status = accessLabels[info.accessStatus] ? info.accessStatus : "offline";
      const seen = info.lastSeen ? `Gần nhất: ${new Date(info.lastSeen).toLocaleString("vi-VN",{timeZone:"Asia/Ho_Chi_Minh"})}` : "Chưa ghi nhận hoạt động";
      return `<tr><td><strong>${escapeHtml(info.username)}</strong><small class="account-id-text">ID: ${escapeHtml(info.accountId || "—")}</small>${!info.enabled?'<small class="admin-user-locked">Tài khoản đã khóa</small>':""}</td><td><span class="admin-user-role">${info.role === "admin" ? "Admin" : "Người dùng"}</span></td>${userVipCell(info)}<td><div class="admin-user-access"><span class="admin-access-state is-${status}" title="${escapeHtml(seen)}"><i aria-hidden="true"></i>${accessLabels[status]}</span></div><small class="admin-user-last-seen">${escapeHtml(seen)}</small></td><td class="admin-user-network">${escapeHtml(info.networkAddress || "Chưa ghi nhận")}</td><td>${escapeHtml(info.device || "Chưa ghi nhận")}</td><td>${escapeHtml(info.browser || "Chưa ghi nhận")}</td>${userBalanceCell(info,"diamond","Kim cương")}${userBalanceCell(info,"paypal","PayPal")}</tr>`;
    }).join("") || '<tr><td colspan="9" class="admin-empty">Không tìm thấy tài khoản.</td></tr>';
    updateUserEditControls();
  }
  async function loadUsers() {
    if(!usersActive()||usersEditing)return;
    clearTimeout(usersTimer);const user=currentUser,generation=++usersGeneration;
    usersLoading=true;updateUserEditControls();
    const valid=()=>usersActive()&&!usersEditing&&currentUser===user&&generation===usersGeneration;
    try { const data=await api("/api/admin/users");if(!valid())return;adminUsers=data.users||[];updateUserFilterOptions();renderUsers(); }
    catch(error){if(valid())message(error.message,true);}
    finally{if(generation===usersGeneration){usersLoading=false;updateUserEditControls();if(valid())usersTimer=setTimeout(loadUsers,15000);}}
  }
  byId("adminUserSearch").oninput=renderUsers;
  byId("adminUserSearchForm").onsubmit=event=>{event.preventDefault();renderUsers();};
  byId("adminUsersRefresh").onclick=()=>void loadUsers();
  byId("adminUsersEdit").onclick=()=>{
    if(!allowed()||usersSaving||usersLoading)return;
    if(usersEditing)return saveUserBalances();
    clearTimeout(usersTimer);usersGeneration++;usersEditGeneration++;userDrafts.clear();
    adminUsers.forEach(info=>userDrafts.set(info.accountId,{info,diamond:formatLuckyWheelAmount(info.diamondBalance),paypal:formatLuckyWheelAmount(info.paypalBalance)}));
    usersEditing=true;renderUsers();userEditMessage("Sửa Kim cương và PayPal trực tiếp trong bảng, sau đó bấm Lưu.");
    const scroll=root.querySelector(".admin-users-card .admin-table-scroll");scroll.scrollLeft=scroll.scrollWidth-scroll.clientWidth;
  };
  byId("adminUsersEditCancel").onclick=()=>{if(usersSaving)return;endUserEdit();renderUsers();userEditMessage();void loadUsers();};
  byId("adminUsersFilterToggle").onclick=()=>toggleUserFilters(byId("adminUsersFilters").hidden);
  userFilterIds.forEach(id=>byId(id).onchange=renderUsers);
  byId("adminUsersFilterClear").onclick=()=>{resetUserFilters();renderUsers();};
  byId("adminUsersFilters").onkeydown=event=>{if(event.key==="Escape"){event.preventDefault();toggleUserFilters(false);byId("adminUsersFilterToggle").focus();}};
  document.addEventListener("visibilitychange",()=>{clearTimeout(usersTimer);usersGeneration++;if(usersActive())void loadUsers();});
  new MutationObserver(()=>{if(root.hidden){clearTimeout(usersTimer);usersGeneration++;}else if(usersActive())void loadUsers();}).observe(root,{attributes:true,attributeFilter:["hidden"]});
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
    root.querySelector(".admin-metrics").hidden = ["deposits","users"].includes(state.view);
    clearTimeout(usersTimer); usersGeneration++;
    clearTimeout(depositTimer); depositGeneration++;
    if (state.view !== "deposits") closeDepositHistory();
    if (state.view === "users") loadUsers();
    if (state.view === "deposits") void loadDeposits();
  }
  let depositPage = 0, depositTotal = 0, depositRows = [], depositGeneration = 0, depositTimer = null, depositReviewBusy = false;
  const depositTime = value => value ? new Date(value).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" }) : "—";
  const depositLabels = { PENDING: "Chờ duyệt", PAID: "Đã cộng tiền", REJECTED: "Đã từ chối", OWNER_DELETED: "Tài khoản đã xóa" };
  function depositActive() { return allowed() && !root.hidden && state.view === "deposits" && !document.hidden; }
  function pollDeposits() {
    if (!depositActive()) return;
    const host = byId("adminDepositRows");
    if (host.querySelector(".admin-deposit-confirm:not([hidden])") || (host.contains(document.activeElement) && document.activeElement.matches("input"))) { depositTimer = setTimeout(pollDeposits, 15000); return; }
    void loadDeposits();
  }
  function depositCard(order) {
    return `<article class="admin-deposit-item" data-deposit-id="${escapeHtml(order.id)}"><header><div class="admin-deposit-identity"><span class="admin-deposit-avatar" aria-hidden="true">${escapeHtml(order.username.slice(0,2).toUpperCase())}</span><div><strong>${escapeHtml(order.username)}</strong>${order.accountId ? `<small class="account-id-text">ID: ${escapeHtml(order.accountId)}</small>` : ""}</div></div><span class="admin-status is-pending">Chờ duyệt</span></header><p class="admin-deposit-created">${escapeHtml(depositTime(order.createdAt))}</p><div class="admin-deposit-amount"><div><span>Tiền nạp</span><strong>${formatLuckyWheelAmount(order.amount)} <small>VNĐ</small></strong></div><div><span>PayPal nhận</span><strong>${formatLuckyWheelAmount(order.credit)} <small>PayPal</small></strong></div></div>${order.legacyKey ? `<p class="admin-note">Yêu cầu cũ · Cần đối chiếu giao dịch trước khi cộng tiền.</p>` : ""}<dl>${order.sender ? `<div><dt>Người chuyển</dt><dd>${escapeHtml(order.sender)}</dd></div>` : ""}${order.email || order.legacyEmail ? `<div><dt>Email</dt><dd>${escapeHtml(order.email || order.legacyEmail)}</dd></div>` : ""}${order.transferMemo ? `<div><dt>Nội dung chuyển khoản</dt><dd>${escapeHtml(order.transferMemo)}</dd></div>` : ""}${order.channel ? `<div><dt>Ngân hàng / Ví</dt><dd>${escapeHtml(order.channel)}</dd></div>` : ""}${order.reference ? `<div><dt>Mã giao dịch</dt><dd>${escapeHtml(order.reference)}</dd></div>` : ""}${order.transferredAt ? `<div><dt>Thời gian chuyển</dt><dd>${escapeHtml(depositTime(order.transferredAt))}</dd></div>` : ""}${order.note ? `<div><dt>Ghi chú</dt><dd>${escapeHtml(order.note)}</dd></div>` : ""}<div><dt>Mã yêu cầu</dt><dd>${escapeHtml(order.id)}</dd></div></dl><div class="admin-deposit-review"><label>Phản hồi / Lý do từ chối<input data-review-note maxlength="500" placeholder="Bắt buộc khi từ chối" /></label><div class="admin-deposit-actions"><button type="button" data-review-start class="admin-primary">Duyệt & cộng tiền</button><button type="button" data-review="reject" class="admin-deposit-reject">Từ chối</button></div><div class="admin-deposit-confirm" hidden><p>Xác nhận đã nhận <strong>${formatLuckyWheelAmount(order.amount)} VNĐ</strong> và cộng <strong>${formatLuckyWheelAmount(order.credit)} PayPal</strong> cho <strong>${escapeHtml(order.username)}</strong>?</p><div class="admin-deposit-actions"><button type="button" data-review="approve" class="admin-primary">Xác nhận cộng tiền</button><button type="button" data-review-cancel>Hủy</button></div></div></div></article>`;
  }
  async function loadDeposits() {
    if (!depositActive() || depositReviewBusy) return;
    clearTimeout(depositTimer);
    const user = currentUser, generation = ++depositGeneration;
    const valid = () => depositActive() && currentUser === user && generation === depositGeneration;
    try {
      const response = await api(`/api/admin/deposits?status=${encodeURIComponent(byId("adminDepositStatus").value)}&page=${depositPage}`);
      if (!valid()) return;
      depositRows = response.orders || []; depositTotal = response.total;
      if (depositPage > 0 && !depositRows.length) { depositPage--; void loadDeposits(); return; }
      const instructions = byId("adminDepositInstructions");
      if (!instructions.dataset.dirty) instructions.value = response.instructions || "";
      byId("adminDepositCount").textContent = `${formatLuckyWheelAmount(depositTotal)} yêu cầu`;
      byId("adminDepositPage").textContent = `Trang ${depositPage + 1} / ${Math.max(1, Math.ceil(depositTotal / 30))}`;
      byId("adminDepositPrev").disabled = depositPage === 0; byId("adminDepositNext").disabled = (depositPage + 1) * 30 >= depositTotal;
      byId("adminDepositRows").innerHTML = depositRows.map(depositCard).join("") || '<div class="admin-empty admin-deposit-empty"><strong>Đã xử lý hết yêu cầu</strong><span>Yêu cầu nạp mới sẽ xuất hiện tại đây.</span></div>';
    } catch (error) { if (valid()) message(error.message, true); }
    finally { if (valid()) depositTimer = setTimeout(pollDeposits, 15000); }
  }
  byId("adminDepositRows").onclick = async event => {
    const button = event.target.closest("button"), card = button?.closest("[data-deposit-id]");
    if (!card || !allowed() || depositReviewBusy || button.disabled) return;
    const confirm = card.querySelector(".admin-deposit-confirm");
    if (button.hasAttribute("data-review-start")) { confirm.hidden = false; button.hidden = true; clearTimeout(depositTimer); depositGeneration++; return; }
    if (button.hasAttribute("data-review-cancel")) { confirm.hidden = true; card.querySelector("[data-review-start]").hidden = false; depositTimer = setTimeout(pollDeposits, 15000); return; }
    if (!button.dataset.review) return;
    const note = card.querySelector("[data-review-note]").value.trim(), user = currentUser;
    if (button.dataset.review === "reject" && !note) { message("Nhập lý do từ chối để người chơi biết.", true); card.querySelector("[data-review-note]").focus(); return; }
    depositReviewBusy = true; clearTimeout(depositTimer); depositGeneration++;
    card.querySelectorAll("button").forEach(node => node.disabled = true);
    try {
      const response = await api("/api/admin/deposits/review", "POST", { id: card.dataset.depositId, action: button.dataset.review, reviewNote: note });
      if (!allowed() || currentUser !== user) return;
      message(response.order.status === "PAID" ? "Đã xác nhận và cộng PayPal." : "Đã từ chối yêu cầu.");
      void window.VietlottDepositNotifications?.refresh();
      if (response.order.username === currentUser) { await loadStoreFromServer(); renderCurrencyBar(); }
    } catch (error) { if (allowed() && currentUser === user) message(error.message, true); }
    finally { depositReviewBusy = false; if (allowed() && currentUser === user) void loadDeposits(); }
  };
  byId("adminDepositRefresh").onclick = () => void loadDeposits();
  byId("adminDepositStatus").onchange = () => { depositPage = 0; void loadDeposits(); };
  byId("adminDepositPrev").onclick = () => { if (depositPage > 0) { depositPage--; void loadDeposits(); } };
  byId("adminDepositNext").onclick = () => { if ((depositPage + 1) * 30 < depositTotal) { depositPage++; void loadDeposits(); } };
  let historyPage = 0, historyTotal = 0, historyGeneration = 0;
  const historyDialog = byId("adminDepositHistoryDialog");
  function closeDepositHistory() { historyGeneration++; if (historyDialog.open) historyDialog.close(); }
  async function loadDepositHistory() {
    if (!allowed() || !historyDialog.open) return;
    const user = currentUser, generation = ++historyGeneration, status = byId("adminDepositHistoryStatus").value;
    const valid = () => allowed() && currentUser === user && historyDialog.open && generation === historyGeneration;
    byId("adminDepositHistoryRows").setAttribute("aria-busy", "true");
    try {
      const response = await api(`/api/admin/deposits?status=${encodeURIComponent(status)}&page=${historyPage}`);
      if (!valid()) return;
      historyTotal = response.total;
      if (historyPage && !response.orders.length) { historyPage--; void loadDepositHistory(); return; }
      byId("adminDepositHistoryCount").textContent = `${formatLuckyWheelAmount(historyTotal)} giao dịch · ${depositLabels[status]}`;
      byId("adminDepositHistoryPage").textContent = `Trang ${historyPage + 1} / ${Math.max(1, Math.ceil(historyTotal / 30))}`;
      byId("adminDepositHistoryPrev").disabled = historyPage === 0; byId("adminDepositHistoryNext").disabled = (historyPage + 1) * 30 >= historyTotal;
      byId("adminDepositHistoryRows").innerHTML = response.orders.length ? `<table class="admin-deposit-history-table"><thead><tr><th>Thời gian xử lý</th><th>Tài khoản</th><th>Tiền nạp</th><th>PayPal</th><th>Người duyệt</th><th>Phản hồi</th></tr></thead><tbody>${response.orders.map(order => `<tr><td>${escapeHtml(depositTime(order.reviewedAt))}</td><td><strong>${escapeHtml(order.username)}</strong><small>${escapeHtml(order.accountId || "—")}</small></td><td class="is-number">${formatLuckyWheelAmount(order.amount)}<small>VNĐ</small></td><td class="is-number ${status === "PAID" ? "is-credit" : ""}">${status === "PAID" ? formatLuckyWheelAmount(order.credit) : "—"}<small>PayPal</small></td><td>${escapeHtml(order.reviewer || "—")}</td><td>${escapeHtml(order.reviewNote || (status === "PAID" ? "Đã xác nhận" : "—"))}</td></tr>`).join("")}</tbody></table>` : '<div class="admin-empty">Chưa có giao dịch trong mục này.</div>';
    } catch (error) { if (valid()) byId("adminDepositHistoryRows").textContent = error.message; }
    finally { if (valid()) byId("adminDepositHistoryRows").removeAttribute("aria-busy"); }
  }
  byId("adminDepositHistoryOpen").onclick = () => { historyPage = 0; if (!historyDialog.open) historyDialog.showModal(); void loadDepositHistory(); };
  byId("adminDepositHistoryClose").onclick = closeDepositHistory;
  historyDialog.addEventListener("close", () => historyGeneration++);
  historyDialog.onclick = event => { if (event.target !== historyDialog) return; const r = historyDialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) closeDepositHistory(); };
  byId("adminDepositHistoryStatus").onchange = () => { historyPage = 0; void loadDepositHistory(); };
  byId("adminDepositHistoryPrev").onclick = () => { if (historyPage) { historyPage--; void loadDepositHistory(); } };
  byId("adminDepositHistoryNext").onclick = () => { if ((historyPage + 1) * 30 < historyTotal) { historyPage++; void loadDepositHistory(); } };
  byId("adminDepositInstructions").oninput = event => event.target.dataset.dirty = "true";
  byId("adminDepositSettingsForm").onsubmit = async event => {
    event.preventDefault(); if (!allowed()) return;
    const user = currentUser, button = event.currentTarget.querySelector("button"), field = byId("adminDepositInstructions");
    button.disabled = true;
    try { await api("/api/admin/deposits/settings", "POST", { instructions: field.value }); if (allowed() && currentUser === user) { delete field.dataset.dirty; message("Đã lưu thông tin nhận tiền."); } }
    catch (error) { if (allowed() && currentUser === user) message(error.message, true); }
    finally { button.disabled = false; }
  };
  new MutationObserver(() => { if (depositActive()) void loadDeposits(); else { clearTimeout(depositTimer); depositGeneration++; if (root.hidden) closeDepositHistory(); } }).observe(root, { attributes: true, attributeFilter: ["hidden"] });
  document.addEventListener("visibilitychange", () => { if (depositActive()) void loadDeposits(); else { clearTimeout(depositTimer); depositGeneration++; } });
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
    openDeposits() { if (allowed()) showView("deposits"); },
    refresh,
    reset() {
      usersLoading=false;
      endUserEdit();userEditMessage();
      closeDepositHistory(); historyPage = 0; byId("adminDepositHistoryRows").replaceChildren();
      clearTimeout(depositTimer); depositGeneration++; depositPage = 0; depositRows = [];
      clearTimeout(usersTimer); usersGeneration++;  adminUsers = []; byId("adminUserSearch").value = ""; resetUserFilters();toggleUserFilters(false);byId("adminUsersFilterBadge").hidden=true;byId("adminUsersFilterToggle").classList.remove("has-filters");byId("adminUsersFilterClear").disabled=true;byId("adminUsersFilterResult").textContent="";updateUserFilterOptions();byId("adminUsersMetrics").replaceChildren(); byId("adminUsersCount").textContent = "";
      byId("adminDepositRows").textContent = ""; byId("adminDepositInstructions").value = ""; delete byId("adminDepositInstructions").dataset.dirty;
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

// Shared deposit notices run on every authenticated app page.
(() => {
  "use strict";
  const byId = id => document.getElementById(id);
  const money = value => Number(value || 0).toLocaleString("vi-VN");
  const identity = () => typeof currentUser === "undefined" || !currentUser ? "" : `${currentAccountId}:${currentUser}:${currentUserRole}`;
  let owner = "", generation = 0, timer = null, controller = null, loading = false, entries = [], pending = 0, toastTimer = null;
  const dialog = document.createElement("dialog");
  dialog.className = "deposit-notification-dialog";
  dialog.id = "depositNotificationDialog";
  dialog.setAttribute("aria-labelledby", "depositNotificationTitle");
  dialog.innerHTML = '<div class="deposit-notification-head"><div><h2 id="depositNotificationTitle">Thông báo nạp tiền</h2><p>Yêu cầu mới và kết quả xử lý</p></div><button type="button" aria-label="Đóng thông báo">×</button></div><div class="deposit-notification-list"></div>';
  document.body.appendChild(dialog);
  dialog.querySelector("button").onclick = () => dialog.close();
  dialog.addEventListener("click", event => {
    if (event.target !== dialog) return;
    const r = dialog.getBoundingClientRect();
    if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close();
  });
  const toast = document.createElement("div");
  toast.className = "deposit-notification-toast"; toast.hidden = true; toast.setAttribute("role", "status"); toast.setAttribute("aria-live", "polite");
  document.body.appendChild(toast);
  function reset() {
    clearTimeout(timer); timer = null; controller?.abort(); controller = null; generation++; loading = false;
    entries = []; pending = 0; clearTimeout(toastTimer); toast.hidden = true; toast.replaceChildren();
    if (dialog.open) dialog.close(); dialog.querySelector(".deposit-notification-list").replaceChildren();
    renderUnread();
  }
  function items() { return owner && owner === identity() ? entries : []; }
  function archived() { return typeof collectHeaderNotifications === "function" ? collectHeaderNotifications().filter(item => item.kind === "deposit") : items(); }
  function renderUnread() {
    const read = typeof getReadHeaderNotificationIds === "function" ? getReadHeaderNotificationIds() : new Set();
    const count = archivedWithoutCollect().filter(item => !read.has(item.id)).length;
    const badge = byId("adminDepositNotificationBadge"), nav = byId("adminDepositNavBadge");
    if (badge) { badge.hidden = !count || currentUserRole !== "admin"; badge.textContent = count > 99 ? "99+" : String(count); }
    if (nav) { nav.hidden = !pending || !owner || currentUserRole !== "admin"; nav.textContent = String(pending); }
    if (byId("adminDepositNotifications")) byId("adminDepositNotifications").setAttribute("aria-label", `Thông báo nạp tiền${count ? `, ${count} tin chưa đọc` : ""}`);
  }
  function archivedWithoutCollect() {
    if (!owner || owner !== identity()) return [];
    const saved = typeof readHeaderNotificationValue === "function" ? readHeaderNotificationValue(HEADER_NOTIFICATION_HISTORY_KEY, []) : [];
    const dismissed = typeof getDismissedHeaderNotificationIds === "function" ? getDismissedHeaderNotificationIds() : new Set();
    return [...new Map([...(Array.isArray(saved) ? saved : []), ...items()].filter(item => item?.kind === "deposit" && item.recipientAccountId === currentAccountId && !dismissed.has(item.id) && (item.audience !== "admin" || currentUserRole === "admin")).map(item => [item.id, item])).values()];
  }
  function activate(item) {
    if (!owner || owner !== identity()) return;
    toast.hidden = true;
    if (dialog.open) dialog.close();
    if (typeof closeHeaderPopovers === "function") closeHeaderPopovers();
    if (item.action === "admin-deposits" && currentUserRole === "admin") {
      navigateToAppPage("admin"); window.adminPanel?.openDeposits();
    } else {
      navigateToAppPage("deposit");
      byId("depositHistoryOpen")?.click();
    }
  }
  function renderInbox() {
    const host = dialog.querySelector(".deposit-notification-list"); host.replaceChildren();
    const read = getReadHeaderNotificationIds();
    const list = archived();
    if (!list.length) { const empty = document.createElement("p"); empty.className = "deposit-notification-empty"; empty.textContent = "Chưa có thông báo nạp tiền."; host.appendChild(empty); }
    for (const item of list) {
      const button = document.createElement("button"); button.type = "button"; button.className = `deposit-notification-entry${read.has(item.id) ? " is-read" : ""}`;
      button.dataset.depositNotificationId = item.id;
      const title = document.createElement("strong"), detail = document.createElement("span"), time = document.createElement("small");
      title.textContent = item.title; detail.textContent = item.detail; time.textContent = formatHeaderNotificationTime(item.timestamp);
      button.append(title, detail, time); button.onclick = () => { markHeaderNotificationRead(item.id); activate(item); };
      host.appendChild(button);
    }
    renderUnread();
  }
  function open() { if (!owner || owner !== identity()) return; renderInbox(); if (!dialog.open) dialog.showModal(); void refresh(); }
  function notify(item) {
    if (getReadHeaderNotificationIds().has(item.id)) return;
    const key = `dvlf_deposit_notice:${owner}:${item.id}`;
    try { if (sessionStorage.getItem(key)) return; sessionStorage.setItem(key, "1"); } catch { }
    toast.replaceChildren();
    const button = document.createElement("button"), close = document.createElement("button"), title = document.createElement("strong"), detail = document.createElement("span");
    button.type = "button"; close.type = "button"; close.textContent = "×"; close.setAttribute("aria-label", "Đóng thông báo");
    title.textContent = item.title; detail.textContent = item.detail; button.append(title, detail);
    button.onclick = () => { markHeaderNotificationRead(item.id); toast.hidden = true; activate(item); };
    close.onclick = () => toast.hidden = true;
    toast.append(button, close); toast.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.hidden = true, 12000);
  }
  async function read(path, signal) {
    const response = await fetch(path, { credentials: "same-origin", cache: "no-store", signal });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error("Chưa tải được thông báo");
    return payload;
  }
  async function refresh() {
    const user = identity();
    if (owner !== user) { reset(); owner = user; }
    if (!user || document.hidden || loading) return;
    loading = true; clearTimeout(timer); const epoch = generation, isAdmin = currentUserRole === "admin";
    const request = new AbortController(); controller = request; const timeout = setTimeout(() => request.abort(), 10000);
    try {
      const [own, admin] = await Promise.all([read("/api/payments/manual", request.signal), isAdmin ? read("/api/admin/deposits?status=PENDING&page=0", request.signal) : Promise.resolve(null)]);
      if (identity() !== user || epoch !== generation) return;
      const previous = new Set(entries.map(item => item.id));
      entries = (own.orders || []).filter(order => ["PAID", "REJECTED"].includes(order.status)).map(order => ({
        id: `deposit-result:${order.id}:${order.status}`, kind: "deposit", recipientAccountId: currentAccountId, audience: "user", action: "deposit-history",
        title: order.status === "PAID" ? "Nạp tiền thành công" : "Yêu cầu nạp đã bị từ chối",
        detail: order.status === "PAID" ? `Đã cộng ${money(order.credit)} PayPal · Nạp ${money(order.amount)} VNĐ.` : `Nạp ${money(order.amount)} VNĐ · ${order.reviewNote || "Xem chi tiết yêu cầu."}`,
        timestamp: Date.parse(order.reviewedAt || order.paidAt || order.createdAt) || 0,
      }));
      pending = admin?.total || 0;
      for (const order of admin?.orders || []) entries.push({
        id: `deposit-request:${order.id}`, kind: "deposit", recipientAccountId: currentAccountId, audience: "admin", action: "admin-deposits",
        title: "Có yêu cầu nạp mới", detail: `${order.username}${order.accountId ? ` · ID ${order.accountId}` : ""} · ${money(order.amount)} VNĐ`, timestamp: Date.parse(order.createdAt) || 0,
      });
      entries.sort((a, b) => b.timestamp - a.timestamp);
      applyServerWallet(own.store || {}); renderCurrencyBar(); renderHeaderNotifications();
      if (dialog.open) renderInbox(); renderUnread();
      const latest = entries.find(item => !previous.has(item.id)); if (latest) notify(latest);
    } catch { /* Existing notifications remain available during a temporary outage. */ }
    finally {
      clearTimeout(timeout);
      if (epoch === generation && owner === user) { loading = false; controller = null; if (user && !document.hidden) timer = setTimeout(refresh, 15000); }
    }
  }
  function sync() { const user = identity(); if (owner !== user || document.hidden) { reset(); owner = user; } if (!document.hidden) void refresh(); }
  byId("adminDepositNotifications")?.addEventListener("click", open);
  window.VietlottDepositNotifications = Object.freeze({ items, refresh, renderUnread, activate, open });
  window.addEventListener("dvlf:auth-changed", sync); document.addEventListener("visibilitychange", sync);
  sync();
})();
